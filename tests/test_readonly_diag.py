"""Read-only Orbis map scanner tested on Windows with the same C source."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
PROBE = PROJECT / "orbis_build" / "host_diag_probe.exe"
PRX = PROJECT / "orbis_build" / "LmlBridge_132_readonly_diagnostic.prx"
ELF = PROJECT / "orbis_build" / "lml_readonly_diag.elf"
REPORT = PROJECT / "orbis_build" / "readonly_diag_report.json"


@unittest.skipUnless(PROBE.is_file(), "Build orbis/build_readonly_diag.ps1 first")
class TestReadOnlyDiagnostic(unittest.TestCase):
    def invoke(self, path: Path, fail_read: bool = False) -> dict[str, str]:
        args = [str(PROBE), str(path)]
        if fail_read:
            args.append("--fail-read")
        completed = subprocess.run(args, capture_output=True, text=True,
                                   timeout=20, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        found = dict(re.findall(r"([A-Z]+)=([A-Za-z0-9_-]+)", completed.stdout))
        self.assertIn("STATUS", found)
        return found

    def make(self, folder: Path, content: bytes) -> Path:
        path = folder / "overlay.map"
        path.write_bytes(content)
        return path

    def test_compiled_map_real_examples(self) -> None:
        report = self.invoke(PROJECT / "staged_samples_v2" / "overlay.map")
        self.assertEqual(
            (report["STATUS"], report["CODE"], report["R"], report["S"],
             report["D"], report["OPEN"], report["CLOSE"]),
            ("MAP_OK", "0", "8", "2", "4", "1", "1"))
        self.assertGreater(int(report["LINES"]), 14)

    def test_empty_probe_map_is_valid(self) -> None:
        path = PROJECT / "orbis" / "probe_data" / "overlay.map"
        report = self.invoke(path)
        self.assertEqual(report["STATUS"], "MAP_OK")
        self.assertEqual((report["R"], report["S"], report["D"]), ("0", "0", "0"))

    def test_missing_map_fails_open(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            result = self.invoke(Path(folder) / "does-not-exist.map")
        self.assertEqual((result["STATUS"], result["CODE"], result["OPEN"], result["CLOSE"]),
                         ("MAP_UNAVAILABLE", "-1", "0", "0"))

    def test_empty_map_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            report = self.invoke(self.make(Path(folder), b""))
        self.assertEqual(report["STATUS"], "MAP_BAD_HEADER")
        self.assertEqual((report["OPEN"], report["CLOSE"]), ("1", "1"))

    def test_header_check_works_with_and_without_line_break(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            for raw in (b"LML_OVERLAY_V1", b"LML_OVERLAY_V1\n",
                        b"LML_OVERLAY_V1\r\n"):
                with self.subTest(raw=raw):
                    result = self.invoke(self.make(path, raw))
                    self.assertEqual(result["CODE"], "0")
            result = self.invoke(self.make(path, b"BAD_V1\n"))
            self.assertEqual(result["STATUS"], "MAP_BAD_HEADER")

    def test_invalid_record_missing_column(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            invalid = b"LML_OVERLAY_V1\nR\tupdate:/test\tpayload/demo\t00\n"
            report = self.invoke(self.make(Path(folder), invalid))
        self.assertEqual(report["STATUS"], "MAP_BAD_RECORD")

    def test_rejects_path_traversal_payload(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            invalid = (b"LML_OVERLAY_V1\nR\tupdate:/test\tpayload/../../private\t" +
                       b"0" * 64 + b"\t0\n")
            report = self.invoke(self.make(Path(folder), invalid))
        self.assertEqual(report["STATUS"], "MAP_BAD_RECORD")

    def test_rejects_short_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            invalid = b"LML_OVERLAY_V1\nR\tupdate:/test\tpayload/data\t123\t5\n"
            report = self.invoke(self.make(Path(folder), invalid))
        self.assertEqual(report["STATUS"], "MAP_BAD_RECORD")

    def test_rejects_record_with_unknown_kind(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            invalid = b"LML_OVERLAY_V1\nX\tupdate:/test\tpayload/data\t" + b"a" * 64 + b"\t5\n"
            report = self.invoke(self.make(Path(folder), invalid))
        self.assertEqual(report["STATUS"], "MAP_BAD_RECORD")

    def test_long_line_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            invalid = b"LML_OVERLAY_V1\n#" + b"Z" * 3000 + b"\n"
            report = self.invoke(self.make(Path(folder), invalid))
        self.assertEqual(report["STATUS"], "MAP_LIMIT")

    def test_large_map_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            invalid = b"LML_OVERLAY_V1\n" + (b"#" + b"x" * 1500 + b"\n") * 1500
            report = self.invoke(self.make(Path(folder), invalid))
        self.assertEqual(report["STATUS"], "MAP_LIMIT")

    def test_read_errors_close_descriptor(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            result = self.invoke(
                self.make(Path(folder), b"LML_OVERLAY_V1\n"), fail_read=True)
        self.assertEqual(
            (result["STATUS"], result["OPEN"], result["CLOSE"]),
            ("MAP_READ_FAILED", "1", "1"))

    def test_crlf_row_and_no_final_newline(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            row = (b"LML_OVERLAY_V1\r\n" +
                   b"R\tupdate:/file.meta\tpayload/example/file.meta\t" +
                   b"b" * 64 + b"\t42")
            result = self.invoke(self.make(Path(folder), row))
        self.assertEqual((result["STATUS"], result["R"]), ("MAP_OK", "1"))


@unittest.skipUnless(ELF.is_file() and PRX.is_file(),
                     "Build Orbis diagnostic PRX first")
class TestReadOnlyOrbisModule(unittest.TestCase):
    def test_orbis_module_imports_and_entrypoint(self) -> None:
        readelf = Path(r"C:\Strawberry\c\bin\readelf.exe")
        if not readelf.is_file():
            self.skipTest("Host readelf unavailable")
        symbols = subprocess.run(
            [str(readelf), "--dyn-syms", "--wide", str(ELF)],
            check=False, capture_output=True, timeout=20, text=True)
        self.assertEqual(symbols.returncode, 0)
        for name in ("module_start", "module_stop", "lml_diag_identity",
                     "lml_diag_abi_version", "lml_diag_last_status"):
            with self.subTest(name=name):
                self.assertRegex(symbols.stdout,
                                 r"(?m)\b" + re.escape(name) + r"\s*$")
        dependencies = subprocess.run(
            [str(readelf), "-d", str(ELF)],
            check=False, capture_output=True, timeout=20, text=True)
        self.assertEqual(dependencies.returncode, 0)
        self.assertIn("libkernel.so", dependencies.stdout)
        self.assertNotIn("libc++.so", dependencies.stdout)
        self.assertNotIn("libSceLibcInternal.so", dependencies.stdout)

    def test_fake_self_header_hash_and_safe_flags(self) -> None:
        report = json.loads(REPORT.read_text(encoding="utf-8-sig"))
        raw = PRX.read_bytes()
        self.assertEqual(raw[:4], bytes.fromhex("4f153d1d"))
        self.assertEqual(len(raw), report["bytes"])
        self.assertEqual(hashlib.sha256(raw).hexdigest(), report["sha256"])
        self.assertFalse(report["writes_any_files"])
        self.assertFalse(report["patches_game_memory"])
        self.assertFalse(report["has_RAGE_file_hooks"])
        self.assertFalse(report["console_tested"])


if __name__ == "__main__":
    unittest.main()
