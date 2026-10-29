"""Offline verification for the PS4 Orbis *probe*, not a game loader test."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "orbis_build"
PRX = BUILD / "LmlBridge_132_api_probe.prx"
ELF = BUILD / "lml_bridge_api.elf"
REPORT = BUILD / "build_report.json"
ABI = [
    "lml_bridge_abi_version",
    "lml_bridge_open",
    "lml_bridge_lookup_replace",
    "lml_bridge_lookup_stream",
    "lml_bridge_lookup_data",
    "lml_bridge_get_counts",
    "lml_bridge_get_last_error",
]


class TestOrbisContract(unittest.TestCase):
    def test_prx_has_self_signature_and_matching_report(self):
        self.assertTrue(PRX.is_file(), f"Expected generated file: {PRX}")
        self.assertTrue(ELF.is_file())
        self.assertTrue(REPORT.is_file())
        raw = PRX.read_bytes()
        self.assertGreater(len(raw), 4096)
        self.assertEqual(raw[:4], bytes.fromhex("4f153d1d"))
        report = json.loads(REPORT.read_text(encoding="utf-8-sig"))
        self.assertEqual(report["target"], "RDR2 PS4 1.32")
        self.assertEqual(report["host_firmware"], "PS5 13.60")
        self.assertEqual(report["target_format"], "Orbis SELF PRX")
        self.assertEqual(report["bytes"], len(raw))
        self.assertEqual(report["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(report["dynamic_exports"], ABI)
        self.assertFalse(report["game_rpf_hook_implemented"])
        self.assertFalse(report["tested_in_rdr2_ps4"])
        self.assertFalse(report["tested_on_ps5"])
        self.assertFalse(report["loader_compatibility_proven"])

    def test_orbis_dynamic_symbol_exports(self):
        readelf = Path(r"C:\Strawberry\c\bin\readelf.exe")
        if not readelf.is_file():
            self.skipTest("Host ELF inspector not installed")
        cmd = [str(readelf), "--dyn-syms", "--wide", str(ELF)]
        proc = subprocess.run(cmd, check=False, timeout=20, capture_output=True,
                              text=True, encoding="utf-8", errors="replace")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for name in ABI:
            with self.subTest(name=name):
                self.assertRegex(proc.stdout, r"(?m)\b" + re.escape(name) + r"\s*$")

    def test_compiled_c_abi_against_staged_lml_resources(self):
        executable = BUILD / "bridge_api_probe.exe"
        stage = ROOT / "staged_samples_v2"
        self.assertTrue(executable.is_file())
        self.assertTrue(stage.is_dir())
        proc = subprocess.run([str(executable), str(stage)],
                              check=False, timeout=20, capture_output=True,
                              text=True, encoding="utf-8", errors="replace")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("LML_BRIDGE_C_ABI_HOST_TEST_PASSED", proc.stdout)


if __name__ == "__main__":
    unittest.main()
