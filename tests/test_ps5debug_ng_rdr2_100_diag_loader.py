"""Checks for the RDR2 1.00 loader diagnostic (no console, read-only).

A fake socket serves a sparse memory model so the anchor->maps->region-sniff
chain is exercised end to end without a live PS5. The three diagnoses the tool
can emit are each pinned here, including the real-console case where the ELF
header is absent from every mapped region of the module.
"""
from __future__ import annotations
import struct
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import ps5debug_ng_rdr2_100_diag_loader as diag  # noqa: E402

PID = 117
GAME_BASE = 0x00400000
GAME_END = 0x06C00000            # must cover GAME_BASE + ANCHOR_GOT_RVA + 8
MODULE_BASE = 0x800000000
MODULE_SIZE = 0x48000
ANCHOR_PTR = MODULE_BASE + 0x16130
OK = struct.pack("<I", 0x80000000)

# Head bytes observed live at libkernel's r-x base: int3 padding, no ELF magic.
PAD = b"\xcc" * 64


def live_report(match=True):
    return {"pid": PID, "image_base": hex(GAME_BASE),
            "image_regions": [{"start": hex(GAME_BASE), "end": hex(GAME_END),
                               "prot": 5}],
            "profile": {
                "live_rage_packfile8_profile_matches_eboot_100": match}}


class FakeConn:
    """Serves CMD_PROC_READ and CMD_PROC_MAPS from a sparse memory model."""
    def __init__(self, segments, maps):
        self.segments = segments            # list of (start, bytes)
        self.maps = maps                    # list of (name, start, end, prot)
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
        assert magic == diag.read_mem.__globals__["PACKET_MAGIC"]
        body = data[12:12 + dlen]
        self.cmds.append(cmd)
        if cmd == diag.read_mem.__globals__["CMD_PROC_READ"]:
            _pid, addr, length = struct.unpack("<IQI", body)
            self.buf += OK + self._read(addr, length)
        elif cmd == diag.read_maps.__globals__["CMD_PROC_MAPS"]:
            self.buf += OK + struct.pack("<I", len(self.maps))
            for name, start, end, prot in self.maps:
                entry = name.encode()[:32].ljust(32, b"\x00")
                entry += struct.pack("<QQQH", start, end, 0, prot)
                self.buf += entry
        else:
            raise AssertionError(f"commande interdite dans le diag: {cmd:#x}")

    def recv(self, n):
        out = bytes(self.buf[:n])
        del self.buf[:n]
        return out


def base_segments(base_head):
    slot_addr = GAME_BASE + diag.ANCHOR_GOT_RVA
    return [
        (slot_addr, struct.pack("<Q", ANCHOR_PTR)),
        (MODULE_BASE, base_head + b"\x00" * (0x1000 - len(base_head))),
    ]


def run_diag(conn, match=True):
    with patch.object(diag.live, "check_live",
                      return_value=live_report(match)), \
         patch.object(diag.socket, "create_connection", return_value=conn), \
         patch.object(diag, "validate_local_ip", return_value="192.168.1.50"):
        return diag.diagnose("192.168.1.50")


class TestDiagLoader(unittest.TestCase):
    def test_elf_header_not_mapped_is_reported(self):
        # Mirrors the live console: libkernel r-x base is int3 padding and no
        # neighbouring region begins with the ELF magic.
        maps = [
            ("executable", GAME_BASE, GAME_END, 5),
            ("libkernel.sprx", MODULE_BASE, MODULE_BASE + MODULE_SIZE, 5),
            ("libkernel.sprx", MODULE_BASE + MODULE_SIZE,
             MODULE_BASE + MODULE_SIZE + 0x20000, 1),
        ]
        conn = FakeConn(base_segments(PAD), maps)
        out = run_diag(conn)
        self.assertEqual(out["status"], "elf-header-not-mapped")
        self.assertFalse(out["base_probe"]["elf_magic_at_start"])
        self.assertEqual(out["base_probe"]["head16_hex"], b"\xcc".hex() * 16)
        self.assertEqual(out["elf_header_candidates"], [])
        self.assertTrue(out["reads_only"])
        # Read-only: only READ and MAPS ever reach the wire.
        read = diag.read_mem.__globals__["CMD_PROC_READ"]
        maps_cmd = diag.read_maps.__globals__["CMD_PROC_MAPS"]
        self.assertTrue(set(conn.cmds) <= {read, maps_cmd})

    def test_elf_header_at_other_region_is_located(self):
        # The containing r-x region has no header, but a sibling region of the
        # SAME name starts with the ELF magic -> point parse_exports there.
        hdr_base = MODULE_BASE + MODULE_SIZE
        maps = [
            ("executable", GAME_BASE, GAME_END, 5),
            ("libkernel.sprx", MODULE_BASE, MODULE_BASE + MODULE_SIZE, 5),
            ("libkernel.sprx", hdr_base, hdr_base + 0x4000, 1),
        ]
        segments = base_segments(PAD) + [
            (hdr_base, b"\x7fELF" + b"\x00" * 60)]
        conn = FakeConn(segments, maps)
        out = run_diag(conn)
        self.assertEqual(out["status"], "elf-header-at-other-region")
        self.assertTrue(out["elf_header_candidates"])
        self.assertEqual(out["elf_header_candidates"][0]["start"],
                         f"0x{hdr_base:X}")

    def test_elf_at_base_flags_other_cause(self):
        maps = [
            ("executable", GAME_BASE, GAME_END, 5),
            ("libkernel.sprx", MODULE_BASE, MODULE_BASE + MODULE_SIZE, 5),
        ]
        conn = FakeConn(base_segments(b"\x7fELF" + b"\x00" * 60), maps)
        out = run_diag(conn)
        self.assertEqual(out["status"], "elf-at-base-unexpected")
        self.assertTrue(out["base_probe"]["elf_magic_at_start"])

    def test_profile_mismatch_refused(self):
        maps = [("executable", GAME_BASE, GAME_END, 5)]
        conn = FakeConn(base_segments(PAD), maps)
        with self.assertRaisesRegex(ValueError, "diagnostic refuse"):
            run_diag(conn, match=False)


if __name__ == "__main__":
    unittest.main()
