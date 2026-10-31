#!/usr/bin/env python3
"""End-to-end test for the clean-room overlay example (RDR2 PS4 1.00).

Compiles examples/overlay_hello_100 through compiler.py into a temp stage and
checks the produced overlay.map, then loads that stage with the OverlayIndex
runtime probe (runtime/overlay_probe.exe) to prove the full chain
install.xml -> overlay.map -> OverlayIndex resolution works. No console, no
game EBOOT, no proprietary bytes: the payload is a synthetic .meta file.

The probe part skips when overlay_probe.exe has not been built yet.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
EXAMPLE = PROJECT / "examples" / "overlay_hello_100"
PROBE = PROJECT / "runtime" / "overlay_probe.exe"
KEY = "update:/common/data/example_lml_overlay.meta"

SPEC = importlib.util.spec_from_file_location("lml_compiler", PROJECT / "compiler.py")
assert SPEC is not None and SPEC.loader is not None
compiler = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = compiler
SPEC.loader.exec_module(compiler)


class TestOverlayHello100(unittest.TestCase):
    def _compile(self, output: Path) -> dict:
        catalog = compiler.compile_catalog(EXAMPLE, set(), True)
        compiler.emit_stage(catalog, EXAMPLE, output)
        return catalog

    def test_compiles_to_single_file_replacement(self):
        with tempfile.TemporaryDirectory() as temp:
            stage = Path(temp) / "stage"
            catalog = self._compile(stage)
            self.assertEqual(catalog["summary"]["mods"], 1)
            self.assertEqual(catalog["summary"]["file_replacements"], 1)
            self.assertEqual(catalog["summary"]["streaming_files"], 0)
            self.assertEqual(catalog["summary"]["data_files"], 0)
            self.assertEqual(catalog["warnings"], [])

    def test_overlay_map_shape(self):
        with tempfile.TemporaryDirectory() as temp:
            stage = Path(temp) / "stage"
            self._compile(stage)
            lines = (stage / "overlay.map").read_text(
                encoding="utf-8").splitlines()
            self.assertEqual(lines[0], "LML_OVERLAY_V1")
            rows = [ln for ln in lines[1:] if ln and not ln.startswith("#")]
            self.assertEqual(len(rows), 1)
            kind, key, payload, digest, size = rows[0].split("\t")
            self.assertEqual(kind, "R")
            self.assertEqual(key, KEY)
            self.assertEqual(len(digest), 64)
            self.assertEqual(int(size), 436)
            self.assertTrue((stage / payload).is_file())
            self.assertEqual((stage / payload).stat().st_size, 436)

    def test_runtime_overlay_index_loads_stage(self):
        if not PROBE.is_file():
            self.skipTest("Build runtime/overlay_probe.exe first")
        with tempfile.TemporaryDirectory() as temp:
            stage = Path(temp) / "stage"
            self._compile(stage)

            def probe(*args: str) -> subprocess.CompletedProcess:
                return subprocess.run([str(PROBE), str(stage), *args],
                                      capture_output=True, text=True,
                                      timeout=10, check=False)

            stats = probe("stats")
            self.assertEqual(stats.returncode, 0, stats.stderr)
            self.assertIn("replacements=1 streaming=0 data=0", stats.stdout)

            hit = probe("replace", KEY)
            self.assertEqual(hit.returncode, 0, hit.stderr)
            self.assertIn("example_lml_overlay.meta", hit.stdout)

            upper = probe("replace", KEY.upper())
            self.assertEqual(upper.returncode, 0, upper.stderr)
            self.assertIn("example_lml_overlay.meta", upper.stdout)

            miss = probe("replace", "update:/not/here.meta")
            self.assertEqual(miss.returncode, 3)
            self.assertIn("NOT_FOUND", miss.stdout)


if __name__ == "__main__":
    unittest.main()
