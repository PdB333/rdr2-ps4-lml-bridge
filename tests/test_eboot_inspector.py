"""Independent, synthetic test fixture for the read-only RDR2 ELF inspector.

The fixture is NOT a Rockstar game binary. It creates two tiny ELF64
load segments and five fake Itanium RTTI classes with virtual method tables.
"""
from __future__ import annotations

import hashlib
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSPECTOR = ROOT / "tools" / "inspect_rdr2_eboot.py"
NAMES = [
    "N4rage8fiDeviceE",
    "N4rage11fiPackfile7E",
    "N4rage11fiPackfile8E",
    "N4rage16fiDeviceRelativeE",
    "N4rage13fiDeviceLocalE",
]


def fixture_bytes() -> bytes:
    raw = bytearray(0x7800)
    ident = b"\x7fELF\x02\x01\x01\x09" + b"\0" * 8
    head = struct.pack("<16sHHIQQQIHHHHHH", ident, 0xFE10, 62, 1,
                       0x80, 64, 0, 0, 64, 56, 2, 64, 0, 0)
    raw[:len(head)] = head
    ph = struct.Struct("<IIQQQQQQ")
    raw[64:120] = ph.pack(1, 5, 0x4000, 0, 0, 0x1000, 0x1000, 0x4000)
    raw[120:176] = ph.pack(1, 4, 0x5000, 0x1000, 0x1000,
                          0x2800, 0x2800, 0x4000)

    def qword(rva: int, value: int) -> None:
        struct.pack_into("<Q", raw, 0x4000 + rva, value)

    for i, name in enumerate(NAMES):
        str_rva = 0x200 + i * 0x40
        payload = name.encode("ascii") + b"\0"
        raw[0x4000 + str_rva:0x4000 + str_rva + len(payload)] = payload
        info_rva = 0x1100 + i * 0x100
        qword(info_rva, 0x10)
        qword(info_rva + 8, str_rva)
        if i == 0:  # Abstract base type, no concrete vtable.
            continue
        address_point = 0x1800 + i * 0x160
        qword(address_point - 16, 0)
        qword(address_point - 8, info_rva)
        for slot in range(15):
            qword(address_point + slot * 8, 0x500 + i * 0x150 + slot * 8)
    return bytes(raw)


class TestEbootInspector(unittest.TestCase):
    def test_synthetic_rtti_and_vtables_can_be_located(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            eboot = root / "synthetic-eboot.bin"
            data = fixture_bytes()
            eboot.write_bytes(data)
            output = root / "inspect.json"
            r = subprocess.run(
                [sys.executable, "-B", str(INSPECTOR), str(eboot),
                 "--expected-sha256", hashlib.sha256(data).hexdigest(),
                 "--out", str(output)],
                text=True, capture_output=True, timeout=20)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result["bytes"], len(data))
            self.assertEqual(len(result["classes"]), 5)
            self.assertFalse(result["hook_installed"])
            self.assertIsNone(result["confirmed_patch"])
            pack = result["classes"]["fiPackfile8"]
            self.assertEqual(pack["vtable_rva"], "0x00001AC0")
            self.assertEqual(pack["methods"]["open_path_candidate"]["slot"], 2)
            self.assertTrue(pack["methods"]["open_path_candidate"]["rva"].startswith("0x"))

    def test_bad_fingerprint_and_truncated_elf_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            eboot = root / "synthetic-eboot.bin"
            eboot.write_bytes(fixture_bytes())
            for args in (["--expected-sha256", "0" * 64], []):
                with self.subTest(args=args):
                    if not args:
                        eboot.write_bytes(b"\x7fELF")
                    r = subprocess.run(
                        [sys.executable, "-B", str(INSPECTOR), str(eboot), *args],
                        text=True, capture_output=True, timeout=20)
                    self.assertEqual(r.returncode, 2)
                    self.assertIn("Inspection failed", r.stderr)


if __name__ == "__main__":
    unittest.main()
