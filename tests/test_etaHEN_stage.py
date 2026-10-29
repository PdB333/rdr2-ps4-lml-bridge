"""Verify opt-in, local-only etaHEN staging for a supplied PS4 Title ID."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "orbis" / "stage_etaHEN_probe.py"
SPEC = importlib.util.spec_from_file_location("lml_etaHEN_stage", SCRIPT)
assert SPEC and SPEC.loader
STAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STAGE)


class TestConsoleStage(unittest.TestCase):
    def test_required_title_id_must_be_cusa(self):
        for invalid in ("", "CUSA1234", "CUSA123456", "SLUS12345",
                        "cusa08519", "../CUSA08519", "CUSA00000/other",
                        "CUSA00000\\.."):
            with self.subTest(value=invalid):
                with tempfile.TemporaryDirectory() as temp:
                    with self.assertRaises(ValueError):
                        STAGE.stage(invalid, Path(temp) / "release")

    def test_stage_creates_hash_verified_directory_and_probe_map(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "generated"
            report = STAGE.stage("CUSA12345", output)
            self.assertEqual(report["title_id"], "CUSA12345")
            self.assertTrue(report["testing_only"])
            self.assertFalse(report["console_transfer_performed"])
            self.assertEqual(report["files"], 4)
            files = {
                "data/etaHEN/game_plugins/CUSA12345/LmlBridge_132_readonly_diagnostic.prx",
                "data/etaHEN/lml_bridge/overlay.map",
                "PROBE_MANIFEST.json",
                "INSTALLATION_TEST.md",
            }
            self.assertEqual(
                {path.relative_to(output).as_posix() for path in output.rglob("*")
                 if path.is_file()}, files)
            payload = output / "data/etaHEN/game_plugins/CUSA12345/LmlBridge_132_readonly_diagnostic.prx"
            self.assertEqual(payload.read_bytes()[:4], bytes.fromhex("4f153d1d"))
            self.assertEqual(hashlib.sha256(payload.read_bytes()).hexdigest(),
                             report["prx_sha256"])
            manifest = json.loads((output / "PROBE_MANIFEST.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["title_id"], "CUSA12345")
            self.assertFalse(manifest["tested_on_console"])
            self.assertFalse(manifest["game_memory_patched"])
            self.assertFalse(manifest["rpf_vfs_hook_available"])
            for entry in manifest["files"]:
                file = output / entry["console_path"].lstrip("/")
                self.assertEqual(hashlib.sha256(file.read_bytes()).hexdigest(), entry["sha256"])
                self.assertEqual(file.stat().st_size, entry["bytes"])
            instructions = (output / "INSTALLATION_TEST.md").read_text(encoding="utf-8")
            self.assertIn("CUSA12345", instructions)
            self.assertIn("mprotect", instructions)

    def test_runtime_mode_stages_only_the_runtime_prx(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "runtime-stage"
            info = STAGE.stage("CUSA12345", out, mode="runtime")
            self.assertEqual(info["mode"], "runtime")
            prx = out / "data/etaHEN/game_plugins/CUSA12345/LmlBridge_132_runtime_probe.prx"
            self.assertTrue(prx.is_file())
            self.assertFalse(
                (out / "data/etaHEN/game_plugins/CUSA12345/LmlBridge_132_readonly_diagnostic.prx").exists())
            manifest = json.loads((out / "PROBE_MANIFEST.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["mode"], "runtime")
            self.assertFalse(manifest["rpf_vfs_hook_available"])
            self.assertIn("MAP_LOADED", manifest["expected_logs"][1])
            self.assertIn("UNIQUEMENT apres", (out / "INSTALLATION_TEST.md").read_text(encoding="utf-8"))
            self.assertEqual(
                hashlib.sha256(prx.read_bytes()).hexdigest(),
                info["prx_sha256"])

    def test_rejects_unrecognized_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, "Mode must"):
                STAGE.stage("CUSA12345", Path(temp) / "new", mode="../runtime")

    def test_never_overwrite_existing_stage(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "generated"
            STAGE.stage("CUSA08519", output)
            before = (output / "PROBE_MANIFEST.json").read_bytes()
            with self.assertRaisesRegex(ValueError, "already exists"):
                STAGE.stage("CUSA08519", output)
            self.assertEqual(before, (output / "PROBE_MANIFEST.json").read_bytes())

    def test_does_not_default_to_someone_elses_title_id(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "trial"
            STAGE.stage("CUSA02468", output)
            manifest = json.loads((output / "PROBE_MANIFEST.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["title_id"], "CUSA02468")
            self.assertNotIn("CUSA08519", [p.name for p in output.rglob("*")
                                             if p.is_dir()])


if __name__ == "__main__":
    unittest.main()
