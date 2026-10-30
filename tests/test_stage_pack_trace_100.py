"""FTP staging for RDR2 PS4 1.00: no overwrites, no game modifications."""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "orbis"))
from stage_pack_trace_100 import PRX, REPORT, stage  # noqa: E402

HAVE_BUILD = PRX.is_file() and REPORT.is_file()


class TestPs5V100Staging(unittest.TestCase):
    def test_01_title_id_must_be_exact(self):
        with tempfile.TemporaryDirectory() as tmp:
            for title in ("", "cusa12345", "CUSA1234", "CUSA123456",
                          "CUSA00001/../../foo", "CUSAabcde", "NPXS12345"):
                with self.subTest(title=title):
                    with self.assertRaises(ValueError):
                        stage(title, Path(tmp) / "would-be-out")
            self.assertFalse((Path(tmp) / "would-be-out").exists())

    @unittest.skipUnless(HAVE_BUILD, "Compile passive Orbis 1.00 PRX first")
    def test_02_good_manifest_and_exact_ftp_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "package"
            result = stage("CUSA12345", root)
            file = root / "data" / "etaHEN" / "game_plugins" / "CUSA12345" / PRX.name
            self.assertEqual(result["files"], 3)
            self.assertTrue(file.is_file())
            self.assertEqual(file.read_bytes(), PRX.read_bytes())
            self.assertEqual(result["sha256"], hashlib.sha256(PRX.read_bytes()).hexdigest())
            self.assertEqual(result["console_path"],
                             "/data/etaHEN/game_plugins/CUSA12345/" + PRX.name)
            manifest = json.loads((root / "STAGING_MANIFEST.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["game_patch_required"], "1.00")
            for prop in ("console_tested", "console_transfer_performed",
                         "automatic_game_hook", "in_game_mod_replacement",
                         "game_files_modified", "original_eboot_included"):
                self.assertIs(manifest[prop], False)
            self.assertFalse((root / "data" / "etaHEN" / "lml_bridge").exists())
            self.assertFalse(list(root.rglob("*.asi")))
            self.assertFalse(list(root.rglob("*.bin")))
            self.assertFalse(list(root.rglob("*.rpf")))

    @unittest.skipUnless(HAVE_BUILD, "Compile passive Orbis 1.00 PRX first")
    def test_03_does_not_overwrite_existing_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "package"
            root.mkdir()
            sentinel = root / "DO_NOT_TOUCH.txt"
            sentinel.write_text("preserve", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "existe deja"):
                stage("CUSA12345", root)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")

    @unittest.skipUnless(HAVE_BUILD, "Compile passive Orbis 1.00 PRX first")
    def test_04_mutated_prx_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "test.prx"
            raw = bytearray(PRX.read_bytes())
            raw[64] ^= 0x01
            source.write_bytes(raw)
            with self.assertRaisesRegex(ValueError, "rapport de build"):
                stage("CUSA12345", Path(tmp) / "destination",
                      source_prx=source, report_path=REPORT)
            self.assertFalse((Path(tmp) / "destination").exists())

    @unittest.skipUnless(HAVE_BUILD, "Compile passive Orbis 1.00 PRX first")
    def test_05_mismatched_game_or_false_claim_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            baseline = json.loads(REPORT.read_text(encoding="utf-8-sig"))
            for name, value in (
                ("profile_game", "RDR2 PS4 1.32"),
                ("console_tested", True),
                ("auto_installed_in_game", True),
                ("direct_resource_replacement_available", True),
                ("version_1_32_rejected_before_memory_read", False),
            ):
                with self.subTest(field=name):
                    modified = dict(baseline)
                    modified[name] = value
                    path = Path(tmp) / "bad-report.json"
                    path.write_text(json.dumps(modified), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "incompatible"):
                        stage("CUSA12345", Path(tmp) / "dest",
                              source_prx=PRX, report_path=path)
                    self.assertFalse((Path(tmp) / "dest").exists())


if __name__ == "__main__":
    unittest.main()
