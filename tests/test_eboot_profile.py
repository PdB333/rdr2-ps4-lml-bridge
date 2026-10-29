"""Safety tests for the static RDR2 PS4 RPF8 method fingerprint guard.

No game EBOOT is included or downloaded. The guarded negative-path checks
run against a tiny independent mock reader, not the proprietary game.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "orbis_build"
HARN = BUILD / "rage_eboot_profile_harness.exe"
REPORT = BUILD / "rage_vfs_report.json"
ELF = BUILD / "rage_vfs_adapter.elf"
INSPECTOR = ROOT / "tools" / "inspect_rdr2_eboot.py"
KNOWN_SHA = "e3ae087f833b0f30f462bb7f880dd2955bf9f51dbb6e56706ee9bda81581feff"


class TestEbootProfile(unittest.TestCase):
    def test_mock_guards_accept_expected_and_reject_mismatches(self):
        if not HARN.is_file():
            self.skipTest("Build the native RDR2 EBOOT guard harness first")
        r = subprocess.run([str(HARN)], text=True, capture_output=True, timeout=15)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("RDR2_EBOOT_RPF8_PROFILE_GUARD_TESTS_PASSED", r.stdout)

    def test_orbis_report_declares_static_only(self):
        self.assertTrue(REPORT.is_file())
        report = json.loads(REPORT.read_text(encoding="utf-8-sig"))
        self.assertTrue(report["eboot_static_profile_available"])
        self.assertEqual(report["profile_source_sha256"], KNOWN_SHA)
        self.assertTrue(report["profile_rva_verification_exported"])
        self.assertFalse(report["game_patch_version_confirmed"])
        self.assertFalse(report["title_verified_eboot_offsets_available"])
        self.assertFalse(report["actual_rage_hook_installed"])
        self.assertFalse(report["tested_on_ps5"])
        self.assertEqual(report["file"], "orbis_build/LmlBridge_132_rage_vfs_adapter.prx")

    def test_orbis_profile_guard_is_exported(self):
        readelf = Path(r"C:\Strawberry\c\bin\readelf.exe")
        if not ELF.is_file() or not readelf.is_file():
            self.skipTest("Orbis target ELF or readelf unavailable")
        r = subprocess.run([str(readelf), "--dyn-syms", "--wide", str(ELF)],
                           text=True, capture_output=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"(?m)\blml_eboot_verify_profile\s*$")

    def test_inspector_rejects_non_elf_and_wrong_fingerprint(self):
        self.assertTrue(INSPECTOR.is_file())
        with tempfile.TemporaryDirectory() as folder:
            fake = Path(folder) / "invalid-eboot.bin"
            fake.write_bytes(b"this is not an executable")
            for args in (
                [str(fake)],
                [str(fake), "--expected-sha256", KNOWN_SHA],
            ):
                with self.subTest(args=args):
                    r = subprocess.run([sys.executable, "-B", str(INSPECTOR),
                                        *args], capture_output=True,
                                       text=True, timeout=15)
                    self.assertEqual(r.returncode, 2)
                    self.assertIn("Inspection failed:", r.stderr)


if __name__ == "__main__":
    unittest.main()
