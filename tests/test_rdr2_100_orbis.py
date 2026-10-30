"""RDR2 PS4 1.00-only guarded diagnostic PRX and synthetic VFS hook tests.

The actual EBOOT is intentionally not committed. These tests do not
launch RDR2 or imply that any hook is installed inside a running game.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/"orbis_build"
EXE=BUILD/"rdr2_100_trace_harness.exe"
PRX=BUILD/"LmlBridge_RDR2_PS4_100_fiPackfile8_trace.prx"
ELF=BUILD/"pack_trace_100.elf"
META=BUILD/"pack_trace_100_report.json"
READELF=Path(r"C:\Strawberry\c\bin\readelf.exe")
EXPECTED_SHA="e3ae087f833b0f30f462bb7f880dd2955bf9f51dbb6e56706ee9bda81581feff"


class TestRdr2OneHundredTrace(unittest.TestCase):
    @unittest.skipUnless(EXE.is_file(), "Build host trace harness first")
    def test_01_host_trace_stress_and_version_guard(self):
        run=subprocess.run([str(EXE)], text=True, capture_output=True,
                           check=False, timeout=35)
        self.assertEqual(run.returncode, 0, run.stdout+run.stderr)
        self.assertIn("RDR2_100_HARDENED_VTABLE_TRACE_AND_REGISTRY_PASSED",
                      run.stdout)

    @unittest.skipUnless(PRX.is_file(), "Build the Orbis 1.00 PRX first")
    def test_02_orbis_self_hash_and_passive_mode(self):
        raw=PRX.read_bytes()
        report=json.loads(META.read_text(encoding="utf-8-sig"))
        self.assertEqual(raw[:4], bytes.fromhex("4f153d1d"))
        self.assertEqual(hashlib.sha256(raw).hexdigest(), report["sha256"])
        self.assertEqual(len(raw), report["bytes"])
        self.assertEqual(report["profile_game"], "RDR2 PS4 1.00")
        self.assertEqual(report["profile_source_eboot_sha256"], EXPECTED_SHA)
        self.assertEqual(report["profile_vtable_slots"], 112)
        self.assertEqual(report["profile_vtable_fnv64"], "8eaecb696678dad0")
        self.assertTrue(report["version_1_32_rejected_before_memory_read"])
        self.assertTrue(report["host_only_fixture_not_exported"])
        self.assertTrue(report["requires_module_to_remain_loaded_after_attach"])
        self.assertFalse(report["auto_installed_in_game"])
        self.assertFalse(report["direct_resource_replacement_available"])
        self.assertFalse(report["console_tested"])

    @unittest.skipUnless(ELF.is_file() and READELF.is_file(),
                         "Build Orbis PRX + install host readelf first")
    def test_03_only_expected_runtime_symbols_exported(self):
        report=json.loads(META.read_text(encoding="utf-8-sig"))
        result=subprocess.run([str(READELF), "--dyn-syms", "--wide",
                               str(ELF)], capture_output=True, text=True,
                              check=False, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in report["exported_symbols"]:
            with self.subTest(symbol=name):
                self.assertRegex(result.stdout,
                                 r"(?m)\b"+re.escape(name)+r"\s*$")
        self.assertNotIn("rdr2_100_pack_trace_host_fixture_attach",
                         result.stdout)

    def test_04_source_permanent_retirement_and_patch_check(self):
        trace=(ROOT/"runtime"/"rdr2_100_pack_trace.cpp").read_text(
            encoding="utf-8")
        self.assertIn("RDR2_100_PACK_VTABLE_FNV64",trace)
        self.assertIn("lml_eboot_verify_profile(",trace)
        self.assertIn("major!=1u || minor!=0u",trace)
        self.assertIn("Retired",trace)
        self.assertIn("g_hook.original_open",trace)
        self.assertIn("std::atomic_flag",trace)
        module=(ROOT/"orbis"/"pack_trace_100_module.c").read_text(
            encoding="utf-8")
        self.assertIn("PASSIVE_NO_GAME_HOOK",module)
        self.assertIn("REFUSE_UNLOAD_AFTER_ATTACH",module)
        self.assertIn("return 0;",module)


if __name__=="__main__":
    unittest.main()
