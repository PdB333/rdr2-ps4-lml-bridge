"""Checks for the RDR2 1.00 loader-address resolver (no console, read-only).

A synthetic libkernel-like module is served from a fake socket so the parser
and the anchor->module->export chain are exercised end to end without any
proprietary file or live PS5.
"""
from __future__ import annotations
import struct
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import ps5debug_ng_rdr2_100_resolve_loader as res  # noqa: E402

PID = 120
GAME_BASE = 0x00400000
GAME_END = 0x06C00000            # must cover GAME_BASE + ANCHOR_GOT_RVA + 8
MODULE_BASE = 0x800000000
MODULE_SIZE = 0x10000
TEXT_FUNC_VA = 0x500             # exported sceKernelLoadStartModule offset
DYN_VA = 0x2000
DLD_VA = 0x3000
SYM_REL = 0x400
OK = struct.pack("<I", 0x80000000)


def build_module(target_nid: str) -> bytes:
    """A minimal in-RAM Orbis module exporting `target_nid` at TEXT_FUNC_VA."""
    strtab = bytearray(b"\x00")
    token_off = len(strtab)
    strtab += f"{target_nid}#libkernel#libkernel".encode() + b"\x00"

    symtab = bytearray(struct.pack("<IBBHQQ", 0, 0, 0, 0, 0, 0))   # reserved
    symtab += struct.pack("<IBBHQQ", token_off, 0x12, 0, 1,
                          TEXT_FUNC_VA, 0x40)                       # export
    symtab += struct.pack("<IBBHQQ", 0, 0x11, 0, 0, 0, 0)          # import

    dynlib = bytearray(0x600)
    dynlib[0:len(strtab)] = strtab
    dynlib[SYM_REL:SYM_REL + len(symtab)] = symtab

    dynamic = b"".join(struct.pack("<QQ", tag, val) for tag, val in [
        (res.DT["STRTAB"], 0), (res.DT["STRSZ"], len(strtab)),
        (res.DT["SYMTAB"], SYM_REL), (res.DT["SYMENT"], 24),
        (res.DT["SYMTABSZ"], len(symtab)), (0, 0),
    ])

    phoff, phentsize = 64, 56
    phspec = [
        (res.PT_LOAD, 5, 0, 0, MODULE_SIZE, MODULE_SIZE),
        (res.PT_DYNAMIC, 6, DYN_VA, DYN_VA, len(dynamic), len(dynamic)),
        (res.PT_SCE_DYNLIBDATA, 4, DLD_VA, DLD_VA, len(dynlib), len(dynlib)),
    ]
    phdrs = b"".join(struct.pack("<IIQQQQQQ", typ, fl, off, va, 0, fsz, msz,
                                 0x4000) for typ, fl, off, va, fsz, msz in phspec)
    header = struct.pack("<16sHHIQQQIHHHHHH",
                         b"\x7fELF\x02\x01\x01\x09" + b"\x00" * 8, 0xFE18, 62,
                         1, 0, phoff, 0, 0, 64, phentsize, len(phspec), 0, 0, 0)
    image = bytearray(MODULE_SIZE)
    image[0:len(header)] = header
    image[phoff:phoff + len(phdrs)] = phdrs
    image[DYN_VA:DYN_VA + len(dynamic)] = dynamic
    image[DLD_VA:DLD_VA + len(dynlib)] = dynlib
    return bytes(image)


def live_report(match=True):
    return {"pid": PID, "image_base": hex(GAME_BASE),
            "image_regions": [{"start": hex(GAME_BASE), "end": hex(GAME_END),
                               "prot": 5}],
            "profile": {
                "live_rage_packfile8_profile_matches_eboot_100": match}}


class FakeConn:
    """Serves CMD_PROC_READ and CMD_PROC_MAPS from a sparse memory model."""
    def __init__(self, segments, maps, anchor_ptr):
        self.segments = segments            # list of (start, bytes)
        self.maps = maps                    # list of (name, start, end, prot)
        self.anchor_ptr = anchor_ptr
        self.buf = bytearray()
        self.cmds = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def settimeout(self, v):
        pass

    def _read(self, addr, length):
        for start, data in self.segments:
            if start <= addr and addr + length <= start + len(data):
                off = addr - start
                return data[off:off + length]
        return b"\x00" * length

    def sendall(self, data):
        magic, cmd, dlen = struct.unpack_from("<III", data)
        assert magic == res.PACKET_MAGIC
        body = data[12:12 + dlen]
        self.cmds.append(cmd)
        if cmd == res.CMD_PROC_READ:
            pid, addr, length = struct.unpack("<IQI", body)
            self.buf += OK + self._read(addr, length)
        elif cmd == res.CMD_PROC_MAPS:
            self.buf += OK + struct.pack("<I", len(self.maps))
            for name, start, end, prot in self.maps:
                entry = name.encode()[:32].ljust(32, b"\x00")
                entry += struct.pack("<QQQH", start, end, 0, prot)
                self.buf += entry
        else:
            raise AssertionError(f"commande interdite dans le resolveur: {cmd:#x}")

    def recv(self, n):
        out = bytes(self.buf[:n])
        del self.buf[:n]
        return out


def make_conn(target_nid, anchor_ptr=MODULE_BASE + TEXT_FUNC_VA,
              module_name="libkernel.sprx"):
    slot_addr = GAME_BASE + res.ANCHOR_GOT_RVA
    segments = [
        (slot_addr, struct.pack("<Q", anchor_ptr)),
        (MODULE_BASE, build_module(target_nid)),
    ]
    maps = [
        ("executable", GAME_BASE, GAME_END, 5),
        (module_name, MODULE_BASE, MODULE_BASE + MODULE_SIZE, 5),
    ]
    return FakeConn(segments, maps, anchor_ptr)


def run_resolver(conn, match=True):
    with patch.object(res.live, "check_live", return_value=live_report(match)), \
         patch.object(res.socket, "create_connection", return_value=conn), \
         patch.object(res, "validate_local_ip", return_value="192.168.1.50"):
        return res.resolve_loader("192.168.1.50")


class TestResolveLoader(unittest.TestCase):
    def test_resolves_target_from_anchor_module(self):
        conn = make_conn(res.nid(res.TARGET_SYMBOL))
        out = run_resolver(conn)
        self.assertEqual(out["status"], "resolved")
        self.assertEqual(out["loader_addr"],
                         f"0x{MODULE_BASE + TEXT_FUNC_VA:X}")
        self.assertTrue(out["loader_addr_in_exec_region"])
        self.assertEqual(out["anchor_module"]["name"], "libkernel.sprx")
        self.assertEqual(out["anchor"]["resolved_value"],
                         f"0x{MODULE_BASE + TEXT_FUNC_VA:X}")
        # Read-only: only READ and MAPS ever hit the wire.
        self.assertTrue(set(conn.cmds) <= {res.CMD_PROC_READ, res.CMD_PROC_MAPS})

    def test_profile_mismatch_refused(self):
        conn = make_conn(res.nid(res.TARGET_SYMBOL))
        with self.assertRaisesRegex(ValueError, "resolution refusee"):
            run_resolver(conn, match=False)

    def test_anchor_unresolved_in_image_reported(self):
        # Slot still points inside the game image -> not yet bound.
        conn = make_conn(res.nid(res.TARGET_SYMBOL),
                         anchor_ptr=GAME_BASE + 0x1000)
        out = run_resolver(conn)
        self.assertEqual(out["status"], "anchor-unresolved-in-image")
        self.assertNotIn("loader_addr", out)

    def test_target_absent_from_module_reported(self):
        conn = make_conn(res.nid("sceKernelClose"))  # wrong export
        out = run_resolver(conn)
        self.assertEqual(out["status"], "target-not-exported-by-anchor-module")
        self.assertNotIn("loader_addr", out)

    def test_anonymous_anchor_region_reported(self):
        conn = make_conn(res.nid(res.TARGET_SYMBOL), module_name="")
        out = run_resolver(conn)
        self.assertEqual(out["status"], "anchor-module-anonymous")

    def test_target_nid_is_known_pair(self):
        self.assertEqual(res.nid("sceKernelLoadStartModule"), "wzvqT4UqKX8")


if __name__ == "__main__":
    unittest.main()
