"""Runs the native-invoker and fiPackfile8-detour C harnesses (no console).

Both harnesses synthesize their own tiny memory; no game EBOOT is used. Build
them first with gcc into orbis_build/ (see orbis/NATIVE_DISPATCH_STUDY_100.md
and PRX_LOADING_STUDY_100.md); the tests skip when the binaries are absent.
"""
from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "orbis_build"
NATIVES = BUILD / "rdr2_100_natives_harness.exe"
DETOUR = BUILD / "rdr2_100_detour_harness.exe"


class TestNativeInvokerHarness(unittest.TestCase):
    def test_invoker_core_passes(self):
        if not NATIVES.is_file():
            self.skipTest("Build rdr2_100_natives_harness.exe first")
        r = subprocess.run([str(NATIVES)], text=True, capture_output=True,
                           timeout=15)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("RDR2_100_NATIVE_INVOKER_TESTS_PASSED", r.stdout)


class TestDetourPlannerHarness(unittest.TestCase):
    def test_detour_core_passes(self):
        if not DETOUR.is_file():
            self.skipTest("Build rdr2_100_detour_harness.exe first")
        r = subprocess.run([str(DETOUR)], text=True, capture_output=True,
                           timeout=15)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("RDR2_100_FIPACKFILE8_DETOUR_TESTS_PASSED", r.stdout)


if __name__ == "__main__":
    unittest.main()
