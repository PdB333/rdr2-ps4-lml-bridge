"""Offline checks for the Orbis import-table audit (no proprietary file)."""
from __future__ import annotations
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import inspect_rdr2_imports as imp  # noqa: E402

# Verified NID pairs (PS4 libc / libkernel), independent of any dump.
KNOWN_NIDS = {
    "malloc": "gQX+4GDQjpM",
    "printf": "hcuQgD53UxM",
    "sceKernelLoadStartModule": "wzvqT4UqKX8",
}


def build_orbis_elf(imports: dict[str, int]) -> bytes:
    """A minimal ET_SCE_EXEC_ASLR image exposing STRTAB/SYMTAB/JMPREL.

    imports maps a plain function name to the GOT (r_offset) RVA it should
    appear at; names are stored as "<nid>#lib#mod" exactly like the game.
    """
    # dynlibdata internal layout (relative offsets).
    strtab = bytearray(b"\0")
    name_off: dict[str, int] = {}
    for func in imports:
        token = f"{imp.nid(func)}#libc#libc".encode() + b"\0"
        name_off[func] = len(strtab)
        strtab += token
    symtab = bytearray(struct.pack("<IBBHQQ", 0, 0, 0, 0, 0, 0))  # reserved [0]
    sym_index = {}
    for i, func in enumerate(imports, start=1):
        sym_index[func] = i
        symtab += struct.pack("<IBBHQQ", name_off[func], 0x11, 0, 0, 0, 0)
    jmprel = bytearray()
    for func, got in imports.items():
        jmprel += struct.pack("<QQq", got, (sym_index[func] << 32) | 7, 0)

    rel = {"STR": 0x00, "SYM": 0x100, "JMP": 0x200}
    dynlib = bytearray(0x300)
    dynlib[rel["STR"]:rel["STR"] + len(strtab)] = strtab
    dynlib[rel["SYM"]:rel["SYM"] + len(symtab)] = symtab
    dynlib[rel["JMP"]:rel["JMP"] + len(jmprel)] = jmprel

    dynamic = b"".join(struct.pack("<QQ", tag, val) for tag, val in [
        (imp.DT["STRTAB"], rel["STR"]), (imp.DT["STRSZ"], len(strtab)),
        (imp.DT["SYMTAB"], rel["SYM"]), (imp.DT["SYMENT"], 24),
        (imp.DT["SYMTABSZ"], len(symtab)),
        (imp.DT["JMPREL"], rel["JMP"]), (imp.DT["PLTRELSZ"], len(jmprel)),
        (imp.DT["PLTGOT"], 0x0678CC50),
        (0, 0),  # DT_NULL
    ])

    dyn_off, dld_off = 256, 512
    phoff, phentsize = 64, 56
    phdrs = b"".join(struct.pack("<IIQQQQQQ", typ, fl, off, va, 0, sz, sz, 0x4000)
                     for typ, fl, off, va, sz in [
        (imp.PT_LOAD, 5, 0, 0, 0x100),
        (imp.PT_DYNAMIC, 6, dyn_off, 0, len(dynamic)),
        (imp.PT_SCE_DYNLIBDATA, 4, dld_off, 0, len(dynlib)),
    ])
    header = struct.pack("<16sHHIQQQIHHHHHH",
                         b"\x7fELF\x02\x01\x01\x09" + b"\0" * 8, 0xFE10, 62,
                         1, 0, phoff, 0, 0, 64, phentsize, 3, 0, 0, 0)
    blob = bytearray(dld_off + len(dynlib))
    blob[0:len(header)] = header
    blob[phoff:phoff + len(phdrs)] = phdrs
    blob[dyn_off:dyn_off + len(dynamic)] = dynamic
    blob[dld_off:dld_off + len(dynlib)] = dynlib
    return bytes(blob)


class TestNid(unittest.TestCase):
    def test_known_pairs(self):
        for name, expected in KNOWN_NIDS.items():
            self.assertEqual(imp.nid(name), expected, name)


class TestAnalyze(unittest.TestCase):
    def setUp(self):
        self.imports = {"malloc": 0x0678D478, "printf": 0x0678CFF0,
                        "sceSysmoduleLoadModule": 0x0678CEB8}
        self.blob = build_orbis_elf(self.imports)

    def test_imported_primitives_resolved_to_got(self):
        out = imp.analyze(self.blob)
        self.assertEqual(out["jmprel_import_count"], 3)
        self.assertEqual(out["watched_imports"]["malloc"]["got_rva"],
                         "0x0678D478")
        self.assertTrue(out["watched_imports"]["sceSysmoduleLoadModule"]
                        ["imported"])
        self.assertEqual(out["pltgot_rva"], "0x0678CC50")

    def test_absent_loader_symbol_reported_false(self):
        out = imp.analyze(self.blob)
        entry = out["watched_imports"]["sceKernelLoadStartModule"]
        self.assertFalse(entry["imported"])
        self.assertIsNone(entry["got_rva"])
        self.assertEqual(entry["nid"], "wzvqT4UqKX8")

    def test_rejects_non_orbis_elf(self):
        bad = bytearray(self.blob)
        bad[16:18] = struct.pack("<H", 2)  # ET_EXEC, not ET_SCE_EXEC_ASLR
        with self.assertRaises(ValueError):
            imp.analyze(bytes(bad))


if __name__ == "__main__":
    unittest.main()
