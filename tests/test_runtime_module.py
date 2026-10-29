"""Static validation of the Orbis C++ resolver runtime probe."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
BUILD = PROJECT / "orbis_build"
PRX = BUILD / "LmlBridge_132_runtime_probe.prx"
ELF = BUILD / "lml_runtime_probe.elf"
REPORT = BUILD / "runtime_probe_report.json"
READELF = Path(r"C:\Strawberry\c\bin\readelf.exe")

NAMES = [
    "module_start", "module_stop",
    "lml_bridge_abi_version", "lml_bridge_open",
    "lml_bridge_lookup_replace", "lml_bridge_lookup_stream",
    "lml_bridge_lookup_data", "lml_bridge_get_counts",
    "lml_bridge_get_last_error", "lml_runtime_last_init_result",
]


@unittest.skipUnless(PRX.is_file() and ELF.is_file(),
                     "Run orbis/build_runtime_probe.ps1 first")
class TestRuntimeModule(unittest.TestCase):
    def test_module_self_hash_and_no_game_hooks(self):
        self.assertTrue(REPORT.is_file())
        meta = json.loads(REPORT.read_text(encoding="utf-8-sig"))
        blob = PRX.read_bytes()
        self.assertGreater(len(blob), 200_000)
        self.assertEqual(blob[:4], bytes.fromhex("4f153d1d"))
        self.assertEqual(hashlib.sha256(blob).hexdigest(), meta["sha256"])
        self.assertEqual(len(blob), meta["bytes"])
        self.assertEqual(meta["exported_symbols"], NAMES)
        self.assertTrue(meta["module_start_exported"])
        self.assertTrue(meta["cpp_constructor_array_called_in_module_start"])
        self.assertTrue(meta["reads_map_on_start"])
        self.assertFalse(meta["patches_game_memory"])
        self.assertFalse(meta["hooks_RAGE_RPF"])
        self.assertFalse(meta["tested_on_console"])
        self.assertFalse(meta["validated_in_game"])

    def test_dynamic_entrypoints_and_orbis_imports(self):
        if not READELF.is_file():
            self.skipTest("Host readelf not installed")
        symbols = subprocess.run(
            [str(READELF), "--dyn-syms", "--wide", str(ELF)],
            check=False, capture_output=True, text=True, timeout=20)
        self.assertEqual(symbols.returncode, 0, symbols.stderr)
        for name in NAMES:
            with self.subTest(symbol=name):
                self.assertRegex(
                    symbols.stdout, r"(?m)\b" + re.escape(name) + r"\s*$")
        dynamic = subprocess.run(
            [str(READELF), "-d", str(ELF)],
            check=False, capture_output=True, text=True, timeout=20)
        self.assertEqual(dynamic.returncode, 0, dynamic.stderr)
        self.assertIn("libkernel.so", dynamic.stdout)
        self.assertIn("libSceLibcInternal.so", dynamic.stdout)

    def test_startup_and_fail_open_contract_documented_in_source(self):
        source = (PROJECT / "orbis" / "bridge_runtime_module.c").read_text(
            encoding="utf-8")
        self.assertIn("int32_t module_start(", source)
        self.assertIn("constructor = __init_array_start", source)
        self.assertIn("lml_bridge_open(LML_RUNTIME_MAP_PATH", source)
        self.assertIn('"[LML-ORBI-RUNTIME] MAP_UNAVAILABLE_OR_INVALID', source)
        self.assertIn("return 0;", source)
        self.assertNotIn("VirtualProtect(", source)


if __name__ == "__main__":
    unittest.main()
