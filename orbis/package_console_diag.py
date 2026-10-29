#!/usr/bin/env python3
"""Create a reproducible LOCAL-ONLY test kit for RDR2 1.32 / PS5 13.60.

Includes only independent project source, two Orbis PRX probes, and tests.
Never packages LML's proprietary .asi/.dll or the sample mod asset payloads.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "LML_BRIDGE_RDR2_PS4_132_CONSOLE_DIAGNOSTIC_KIT.zip"
FILES = [
    "README.md",
    "PORTING_STATUS.md",
    "compiler.py",
    "orbis/README_PS5_1360.md",
    "orbis/CONSOLE_DIAGNOSTIC.md",
    "orbis/stage_etaHEN_probe.py",
    "orbis/probe_data/overlay.map",
    "orbis/diag_probe_core.h",
    "orbis/diag_probe_core.c",
    "orbis/host_diag_probe.c",
    "orbis/loader_diag_module.c",
    "orbis/build_readonly_diag.ps1",
    "orbis/bridge_runtime_module.c",
    "orbis/build_runtime_probe.ps1",
    "orbis/lml_bridge_exports.cpp",
    "orbis/build_orbis.ps1",
    "runtime/overlay_index.hpp",
    "runtime/overlay_index.cpp",
    "tests/test_compiler.py",
    "tests/test_orbis_contract.py",
    "tests/test_etaHEN_stage.py",
    "tests/test_readonly_diag.py",
    "tests/test_runtime_module.py",
    "orbis_build/readonly_diag_report.json",
    "orbis_build/runtime_probe_report.json",
    "orbis_build/LmlBridge_132_readonly_diagnostic.prx",
    "orbis_build/LmlBridge_132_runtime_probe.prx",
    "orbis_build/host_diag_probe.exe",
]


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def main() -> None:
    if OUT.exists():
        raise RuntimeError(f"Refusing to overwrite existing archive: {OUT}")
    raw_files: dict[str, bytes] = {}
    for name in FILES:
        path = ROOT / name
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"File missing or linked: {path}")
        if not path.resolve().is_relative_to(ROOT.resolve()):
            raise RuntimeError(f"Source path escapes project: {path}")
        if not name.lower().endswith((".prx", ".exe", ".ps1", ".py", ".c", ".cpp", ".h", ".hpp", ".md", ".json", ".map")):
            raise RuntimeError(f"Unexpected archive extension: {name}")
        raw_files[name] = path.read_bytes()

    pairs = [
        ("readonly_diag_report.json", "LmlBridge_132_readonly_diagnostic.prx",
         "has_RAGE_file_hooks", "console_tested"),
        ("runtime_probe_report.json", "LmlBridge_132_runtime_probe.prx",
         "hooks_RAGE_RPF", "tested_on_console"),
    ]
    for report_name, prx_name, hook_key, test_key in pairs:
        report = json.loads(raw_files["orbis_build/" + report_name].decode("utf-8-sig"))
        raw = raw_files["orbis_build/" + prx_name]
        if raw[:4] != bytes.fromhex("4f153d1d"):
            raise RuntimeError(f"Invalid Orbis SELF magic: {prx_name}")
        if sha(raw) != report["sha256"] or len(raw) != report["bytes"]:
            raise RuntimeError(f"PRX build report mismatch: {prx_name}")
        if report.get(hook_key) is not False or report.get(test_key) is not False:
            raise RuntimeError("The package may not claim unverified console functionality")

    manifest = {
        "format": "lml-bridge-rdr2-ps4-132-console-diag-kit/1",
        "game": "RDR2 PS4 1.32",
        "console": "PS5 13.60 jailbreak",
        "purpose": "Offline build and loader diagnosis, not a working RPF modloader",
        "contains_proprietary_lml_binaries": False,
        "contains_mod_assets": False,
        "tests_reported": 39,
        "game_hook_implemented": False,
        "console_tested": False,
        "requires_user_supplied_title_id_before_staging": True,
        "files": [
            {"name": name, "bytes": len(data), "sha256": sha(data)}
            for name, data in sorted(raw_files.items())
        ],
    }
    inside = dict(raw_files)
    inside["TESTKIT_MANIFEST.json"] = (
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    with ZipFile(OUT, "x", compression=ZIP_DEFLATED, compresslevel=7) as archive:
        for name, data in sorted(inside.items()):
            info = ZipInfo(name, date_time=(2026, 10, 28, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, data, compress_type=ZIP_DEFLATED, compresslevel=7)
    with ZipFile(OUT) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("Archive failed CRC validation")
        if set(archive.namelist()) != set(inside):
            raise RuntimeError("Unexpected ZIP entries")
        for name, raw in inside.items():
            if sha(archive.read(name)) != sha(raw):
                raise RuntimeError(f"Archive SHA-256 mismatch: {name}")
    print(json.dumps({
        "path": str(OUT.resolve()),
        "archive_bytes": OUT.stat().st_size,
        "archive_sha256": sha(OUT.read_bytes()),
        "archive_entries": len(inside),
        "prx_count": 2,
        "verified": True,
        "tested_on_ps5": False,
        "game_hook_implemented": False,
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
