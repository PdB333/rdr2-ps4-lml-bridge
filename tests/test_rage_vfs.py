"""End-to-end simulated RAGE/RPF8 file-open interception.

The native harness supplies stub ORIGINAL fiDevice callbacks and real loose
overlay bytes. No PS4 eboot or proprietary RPF archive is used.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "orbis_build" / "rage_vfs_harness.exe"
PRX = ROOT / "orbis_build" / "LmlBridge_132_rage_vfs_adapter.prx"
ELF = ROOT / "orbis_build" / "rage_vfs_adapter.elf"
REPORT = ROOT / "orbis_build" / "rage_vfs_report.json"
VIRTUAL = "update:/common/data/ai/combatbehaviour.meta"
OVERRIDE = b"MODDED_CONTENT"
ORIGINAL = b"ORIGINAL_CONTENT"


@unittest.skipUnless(BIN.is_file(), "Build RAGE VFS C++ host harness first")
class TestRageVfsHost(unittest.TestCase):
    def test_rage_virtual_open_redirect_read_seek_stat_and_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            payload = root / "payload"
            payload.mkdir()
            (payload / "override.meta").write_bytes(OVERRIDE)
            (root / "original.bin").write_bytes(ORIGINAL)
            sha = hashlib.sha256(OVERRIDE).hexdigest()
            (root / "overlay.map").write_text(
                "LML_OVERLAY_V1\n"
                "# kind/resource/payload/hash/size\n"
                f"R\t{VIRTUAL}\tpayload/override.meta\t{sha}\t{len(OVERRIDE)}\n",
                encoding="utf-8"
            )
            run = subprocess.run(
                [str(BIN), str(root)], capture_output=True, text=True,
                check=False, timeout=30,
            )
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn("RAGE_VFS_READTHROUGH_HOST_PASSED", run.stdout)
            self.assertIn("redirected=1", run.stdout)
            self.assertIn("fallbacks=2", run.stdout)


@unittest.skipUnless(PRX.is_file() and ELF.is_file(),
                     "Compile the Orbis RAGE/VFS adapter first")
class TestOrbisRageVfsBuild(unittest.TestCase):
    def test_prx_orbis_magic_and_hash_verified(self):
        report = json.loads(REPORT.read_text(encoding="utf-8-sig"))
        raw = PRX.read_bytes()
        self.assertEqual(raw[:4], bytes.fromhex("4f153d1d"))
        self.assertEqual(hashlib.sha256(raw).hexdigest(), report["sha256"])
        self.assertEqual(len(raw), report["bytes"])
        self.assertFalse(report["actual_rage_hook_installed"])
        self.assertFalse(report["tested_on_ps5"])
        self.assertTrue(report["original_callbacks_required"])
        self.assertEqual(report["target"], "RDR2 PS4 1.32 on PS5 13.60")

    def test_vfs_orbis_exported_symbols(self):
        readelf = Path(r"C:\Strawberry\c\bin\readelf.exe")
        if not readelf.is_file():
            self.skipTest("Host ELF inspector missing")
        result = subprocess.run([str(readelf), "--dyn-syms", "--wide", str(ELF)],
                                capture_output=True, text=True, timeout=20,
                                check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        for symbol in (
            "module_start", "module_stop", "lml_rage_bind_game_io",
            "lml_rage_load_overlay", "lml_rage_open_file", "lml_rage_read_file",
            "lml_rage_read_at", "lml_rage_seek_file", "lml_rage_size_file",
            "lml_rage_close_file", "lml_rage_stat_path",
            "lml_rage_select_loader_path", "lml_rage_dispatch_text_loader",
            "lml_rage_clear",
            "lml_rage_get_counters", "lml_rage_abi_version",
        ):
            with self.subTest(symbol=symbol):
                self.assertRegex(result.stdout, r"(?m)\b" + symbol + r"\s*$")


if __name__ == "__main__":
    unittest.main()
