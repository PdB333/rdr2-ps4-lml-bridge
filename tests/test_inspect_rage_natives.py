"""Checks for the RAGE native-handler map extractor (no eboot, no console).

A minimal in-RAM Orbis ELF carries a few registration sites so the pattern
scanner, the executable-segment confinement and the hash filter are exercised
without any proprietary binary.
"""
from __future__ import annotations
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import inspect_rage_natives as nat  # noqa: E402
from inspect_rdr2_eboot import Image, PROGRAM  # noqa: E402

EXEC_OFF = 0x1000
EXEC_VA = 0x1000
RO_OFF = 0x2000
RO_VA = 0x2000
SEG_SIZE = 0x1000
IMAGE_SIZE = 0x3000

REAL_HASH = 0x15D757606D170C3C      # GET_ENTITY_MAX_HEALTH
SMALL_HASH = 0x40                   # decoy movabs of a small constant


def site_bytes(native_hash: int, handler_rva: int, site_rva: int) -> bytes:
    disp = handler_rva - site_rva - nat.REG_SITE_LEN
    return (b"\x48\xb9" + struct.pack("<Q", native_hash)
            + b"\x48\x8d\x15" + struct.pack("<i", disp))


def build_image() -> Image:
    raw = bytearray(IMAGE_SIZE)
    phoff, phentsize = 0x40, PROGRAM.size
    phdrs = PROGRAM.pack(1, 5, EXEC_OFF, EXEC_VA, 0, SEG_SIZE, SEG_SIZE, 0x4000)
    phdrs += PROGRAM.pack(1, 4, RO_OFF, RO_VA, 0, SEG_SIZE, SEG_SIZE, 0x4000)
    header = struct.pack("<16sHHIQQQIHHHHHH",
                         b"\x7fELF\x02\x01\x01\x09" + b"\x00" * 8, 0xFE10, 62,
                         1, 0, phoff, 0, 0, 64, phentsize, 2, 0, 0, 0)
    raw[0:len(header)] = header
    raw[phoff:phoff + len(phdrs)] = phdrs

    # Valid native: handler stays inside the executable segment.
    good = site_bytes(REAL_HASH, EXEC_VA + 0x500, EXEC_VA + 0x100)
    raw[EXEC_OFF + 0x100:EXEC_OFF + 0x100 + len(good)] = good
    # Decoy: hash too small -> rejected by the 64-bit filter.
    small = site_bytes(SMALL_HASH, EXEC_VA + 0x500, EXEC_VA + 0x200)
    raw[EXEC_OFF + 0x200:EXEC_OFF + 0x200 + len(small)] = small
    # Decoy: handler points into the read-only segment -> rejected.
    ro = site_bytes(0xAABBCCDDEEFF0011, RO_VA + 0x10, EXEC_VA + 0x300)
    raw[EXEC_OFF + 0x300:EXEC_OFF + 0x300 + len(ro)] = ro
    return Image(bytes(raw))


class TestScanNatives(unittest.TestCase):
    def setUp(self):
        self.sites = nat.scan_natives(build_image())

    def test_valid_native_found_with_handler_rva(self):
        self.assertIn((REAL_HASH, EXEC_VA + 0x500, EXEC_VA + 0x100), self.sites)

    def test_small_hash_rejected(self):
        self.assertFalse(any(h == SMALL_HASH for h, _, _ in self.sites))

    def test_handler_outside_exec_rejected(self):
        self.assertFalse(any(h == 0xAABBCCDDEEFF0011 for h, _, _ in self.sites))

    def test_only_the_valid_site_survives(self):
        self.assertEqual(len(self.sites), 1)


class TestManifestLoading(unittest.TestCase):
    def test_collects_only_64bit_hex(self):
        p = ROOT / "tests" / "_tmp_manifest.json"
        p.write_text('{"a":"0x15D757606D170C3C","b":"0x40","c":"hello",'
                     '"nested":[{"d":"0x0F2A2175734926D8"}]}', encoding="utf-8")
        try:
            known = nat.load_known_hashes(p)
        finally:
            p.unlink()
        self.assertEqual(known, {0x15D757606D170C3C, 0x0F2A2175734926D8})


class TestShaGate(unittest.TestCase):
    def test_non_100_eboot_refused(self):
        p = ROOT / "tests" / "_tmp_fake_eboot.bin"
        p.write_bytes(b"not an eboot")
        try:
            with self.assertRaisesRegex(ValueError, "SHA-256|1.00 EBOOT"):
                nat.analyse(p, "", None)
        finally:
            p.unlink()


if __name__ == "__main__":
    unittest.main()
