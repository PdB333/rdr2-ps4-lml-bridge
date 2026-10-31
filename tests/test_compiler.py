#!/usr/bin/env python3
"""Regression tests for the independently implemented LML manifest compiler."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
MODLOADER = PROJECT.parent
SPEC = importlib.util.spec_from_file_location("lml_compiler", PROJECT / "compiler.py")
assert SPEC is not None and SPEC.loader is not None
compiler = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = compiler
SPEC.loader.exec_module(compiler)


class TestLmlCompiler(unittest.TestCase):
    def test_real_example_catalog(self):
        # Counts the shipped LML sample mods plus the bridge's own clean-room
        # demo examples/overlay_hello_100 (one ungrouped .meta FileReplacement,
        # 436 bytes): +1 mod, +1 entry, +1 file_replacement, +1 xml_metadata.
        catalog = compiler.compile_catalog(MODLOADER, set(), True)
        self.assertEqual(catalog["summary"], {
            "mods": 6,
            "entries": 15,
            "file_replacements": 9,
            "streaming_files": 2,
            "data_files": 4,
            "payload_bytes": 20165366,
            "xml_rage_resources": 9,
            "xml_metadata_files": 4,
            "text_string_tables": 1,
            "native_rsc8_files": 1,
        })
        self.assertTrue(any("AUTO requires runtime handling" in x for x in catalog["warnings"]))
        for entry in catalog["entries"]:
            self.assertEqual(len(entry["sha256"]), 64)

    def test_asset_format_hints(self):
        catalog = compiler.compile_catalog(MODLOADER, set(), True)
        formats = {e["format_hint"] for e in catalog["entries"]}
        self.assertEqual(formats, {"rage_xml", "xml_metadata", "lml_text_string_table", "rsc8_binary"})
        xml_entries = [e for e in catalog["entries"] if e["format_hint"] == "rage_xml"]
        self.assertEqual(len(xml_entries), 9)
        self.assertTrue(all(e["integration_requirement"] == "requires_rage_xml_serialization"
                            for e in xml_entries))

    def test_group_default_opt_in(self):
        # 7 shipped ungrouped entries + the overlay_hello_100 demo entry.
        catalog = compiler.compile_catalog(MODLOADER, set(), False)
        self.assertEqual(catalog["summary"]["entries"], 9)
        self.assertEqual(catalog["summary"]["file_replacements"], 3)
        self.assertTrue(any("no ResourceGroup selected" in x for x in catalog["warnings"]))

    def test_specific_group(self):
        # Selected-group entries + always-on ungrouped entries (incl. the demo).
        catalog = compiler.compile_catalog(MODLOADER, {"More assertive peds"}, False)
        self.assertEqual(catalog["summary"]["entries"], 11)
        target = "update:/x64/packs/base/data/metapeds.ymt"
        self.assertEqual(
            len([e for e in catalog["entries"] if e["key"] == target]), 1)

    def test_path_rejects_traversal_absolute_and_control(self):
        for invalid in (
            "../outside.ymt", "nested/../outside.ymt", "nested//bad.ytd",
            "/root/data.meta", "C:\\windows\\bad.ymt", "a\ttab", "a/./b"):
            with self.subTest(path=invalid):
                with self.assertRaises(compiler.ConversionError):
                    compiler.relative_path(invalid)
        for invalid in ("../x", "update:/../meta", "update:\\..\\meta", "C:\\some\\file"):
            with self.subTest(game_path=invalid):
                with self.assertRaises(compiler.ConversionError):
                    compiler.game_path(invalid)

    def test_virtual_paths_are_normalized(self):
        self.assertEqual(
            compiler.game_path("UPDATE:\\COMMON\\Data\\ai\\Relationships.meta"),
            "update:/common/data/ai/relationships.meta")
        self.assertEqual(compiler.data_name("metaped_assets", "x/y.Z"), "METAPED_ASSETS/y.z")
        self.assertEqual(compiler.stream_name("DLC\\MyTexture.YTD"), "dlc/mytexture.ytd")

    def _temp_mod(self, root: Path, xml: str, files: dict[str, bytes]) -> Path:
        folder = root / "Sample"
        folder.mkdir()
        (folder / "install.xml").write_text(xml, encoding="utf-8")
        for name, data in files.items():
            path = folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return folder

    def test_stage_materializes_identical_asset_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "input"
            root.mkdir()
            self._temp_mod(root, """<EasyInstall><Name>test</Name><Resources>
                <Resource><FileReplacement><GamePath>update:/some/a.ymt</GamePath>
                <FilePath>folder/original.ymt</FilePath></FileReplacement></Resource>
                </Resources></EasyInstall>""", {"folder/original.ymt": b"\x00\xff\x11\x00payload"})
            stage = Path(temp) / "stage"
            catalog = compiler.compile_catalog(root, set(), False)
            compiler.emit_stage(catalog, root, stage)
            self.assertEqual((stage / catalog["entries"][0]["payload"]).read_bytes(),
                             b"\x00\xff\x11\x00payload")
            self.assertEqual((stage / "overlay.map").read_text(encoding="utf-8").splitlines()[0],
                             compiler.MAP_MAGIC)
            self.assertEqual(json.loads((stage / "catalog.json").read_text(encoding="utf-8"))["format"],
                             compiler.FORMAT)
            with self.assertRaises(compiler.ConversionError):
                compiler.emit_stage(catalog, root, stage)

    def test_unsafe_xml_and_unsupported_operations_fail_loudly(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "root"
            root.mkdir()
            folder = self._temp_mod(root, '<!DOCTYPE a [<!ENTITY e "test">]><EasyInstall/>', {})
            with self.assertRaises(compiler.ConversionError):
                compiler.parse_xml(folder / "install.xml")
            (folder / "install.xml").write_text(
                """<EasyInstall><Resources><Resource>
                <FileEntryReplacement>entry.xml</FileEntryReplacement>
                </Resource></Resources></EasyInstall>""", encoding="utf-8")
            with self.assertRaisesRegex(compiler.ConversionError, "Unsupported LML resource"):
                compiler.compile_catalog(root, set(), False)

    def test_duplicate_virtual_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "root"
            root.mkdir()
            self._temp_mod(root, """<EasyInstall><Resources><Resource>
                <FileReplacement><GamePath>update:/one.ymt</GamePath>
                <FilePath>a.ymt</FilePath></FileReplacement>
                <FileReplacement><GamePath>UPDATE:/ONE.YMT</GamePath>
                <FilePath>b.ymt</FilePath></FileReplacement>
                </Resource></Resources></EasyInstall>""",
                {"a.ymt": b"a", "b.ymt": b"b"})
            with self.assertRaisesRegex(compiler.ConversionError, "Ambiguous overlay"):
                compiler.compile_catalog(root, set(), False)

    def test_missing_files_are_errors(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "root"
            root.mkdir()
            self._temp_mod(root, """<EasyInstall><Resources><Resource>
                <StreamingFile>not-there.ytd</StreamingFile>
                </Resource></Resources></EasyInstall>""", {})
            with self.assertRaisesRegex(compiler.ConversionError, "Missing"):
                compiler.compile_catalog(root, set(), False)

    def test_native_resolver_rejects_malformed_map(self):
        exe = PROJECT / "runtime" / "overlay_probe.exe"
        if not exe.is_file():
            self.skipTest("Native resolver test executable missing")
        digest = "0" * 64
        with tempfile.TemporaryDirectory() as temp:
            stage = Path(temp)
            (stage / "asset.ymt").write_bytes(b"x")
            record = "R\tupdate:/test.ymt\tasset.ymt\t" + digest + "\t1"
            invalid_cases = [
                ("INVALID_HEADER\n" + record + "\n", "Unsupported overlay map format"),
                ("LML_OVERLAY_V1\n" +
                 "R\tupdate:/test.ymt\t../escaped.ymt\t" + digest + "\t1\n",
                 "Invalid map key"),
                ("LML_OVERLAY_V1\n" + record + "\n" +
                 "R\tUPDATE:/TEST.YMT\tasset.ymt\t" + digest + "\t1\n",
                 "Duplicate overlay key"),
            ]
            for map_text, expected_error in invalid_cases:
                with self.subTest(error=expected_error):
                    (stage / "overlay.map").write_text(map_text, encoding="utf-8")
                    result = subprocess.run(
                        [str(exe), str(stage), "stats"],
                        capture_output=True, text=True, timeout=10, check=False)
                    self.assertEqual(result.returncode, 2)
                    self.assertIn(expected_error, result.stderr)

    def test_compiled_native_resolver(self):
        exe = PROJECT / "runtime" / "overlay_probe.exe"
        stage = PROJECT / "staged_samples_v2"
        if not exe.is_file() or not stage.is_dir():
            self.skipTest("Compile native resolver and stage examples first")
        commands = [
            (["stats"], 0, "replacements=8 streaming=2 data=4"),
            (["replace", "UPDATE:\\COMMON\\DATA\\AI\\combatbehaviour.meta"], 0,
             "combatbehaviour.meta"),
            (["stream", "DAVID_HEAD_MERGE.YTD"], 0, "david_head_merge.ytd"),
            (["data", "METAPEDS_DAVID.YMT", "PED_METADATA_FILE"], 0, "metapeds_david.ymt"),
            (["replace", "update:/not/in/game.txt"], 3, "NOT_FOUND"),
            (["replace", "update:/../blocked.txt"], 3, "NOT_FOUND"),
        ]
        for args, expected_code, expected_text in commands:
            with self.subTest(args=args):
                result = subprocess.run([str(exe), str(stage), *args],
                                        capture_output=True, text=True,
                                        timeout=10, check=False)
                self.assertEqual(result.returncode, expected_code, result.stderr)
                self.assertIn(expected_text, result.stdout)


if __name__ == "__main__":
    unittest.main()
