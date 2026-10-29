#!/usr/bin/env python3
"""Pack the original LML Bridge source and two diagnostic Orbis PRX modules.

Intentionally excludes third-party LML binaries, sample assets and SDK archives.
This is a development/test kit, NOT an installable modloader for RDR2 PS4.
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "LML_BRIDGE_RDR2_PS4_132_ORBIS_TESTKIT.zip"
FILES = [
    "compiler.py",
    "README.md",
    "PORTING_STATUS.md",
    "VERIFICATION.txt",
    "orbis/README_PS5_1360.md",
    "orbis/build_orbis.ps1",
    "orbis/build_loader_smoke.ps1",
    "orbis/loader_smoke.c",
    "orbis/lml_bridge_exports.cpp",
    "orbis/bridge_api_probe.cpp",
    "runtime/overlay_index.hpp",
    "runtime/overlay_index.cpp",
    "runtime/overlay_probe.cpp",
    "tests/test_compiler.py",
    "tests/test_orbis_contract.py",
    "orbis_build/build_report.json",
    "orbis_build/loader_smoke_report.json",
    "orbis_build/final_validation.txt",
    "orbis_build/LmlBridge_132_api_probe.prx",
    "orbis_build/LmlBridge_132_loader_smoke.prx",
]


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def main() -> None:
    if OUT.exists():
        raise SystemExit(f"Output already exists; refusing to overwrite: {OUT}")
    source = {}
    for name in FILES:
        path = ROOT / name
        if not path.is_file() or path.is_symlink():
            raise SystemExit(f"Required build artifact missing or linked: {path}")
        if not path.resolve().is_relative_to(ROOT.resolve()):
            raise SystemExit(f"Path escaped bundle root: {path}")
        source[name] = path.read_bytes()
    reports = {}
    for name in ["orbis_build/build_report.json", "orbis_build/loader_smoke_report.json"]:
        reports[name] = json.loads(source[name].decode("utf-8-sig"))

    api = "orbis_build/LmlBridge_132_api_probe.prx"
    smoke = "orbis_build/LmlBridge_132_loader_smoke.prx"
    if source[api][:4] != bytes.fromhex("4f153d1d"):
        raise SystemExit("API PRX has no Orbis SELF signature")
    if source[smoke][:4] != bytes.fromhex("4f153d1d"):
        raise SystemExit("Smoke PRX has no Orbis SELF signature")
    if sha256(source[api]) != reports["orbis_build/build_report.json"]["sha256"]:
        raise SystemExit("API PRX hash mismatch")
    if sha256(source[smoke]) != reports["orbis_build/loader_smoke_report.json"]["sha256"]:
        raise SystemExit("Smoke PRX hash mismatch")
    if reports["orbis_build/build_report.json"]["tested_on_ps5"] is not False:
        raise SystemExit("Unexpected console test claim")
    if reports["orbis_build/build_report.json"]["game_rpf_hook_implemented"] is not False:
        raise SystemExit("Unexpected game-hook claim")

    listing = {
        "format": "lml-bridge-ps4-132-diagnostic-kit/1",
        "target": "RDR2 PS4 v1.32 running on PS5 firmware 13.60",
        "scope": "development tools and loader diagnostics, NOT a working RAGE/RPF modloader",
        "contains_third_party_lml_binaries": False,
        "contains_sample_mod_assets": False,
        "tested_on_ps5": False,
        "game_rpf_hook_implemented": False,
        "files": [
            {"name": name, "sha256": sha256(data), "bytes": len(data)}
            for name, data in sorted(source.items())
        ],
    }
    metadata = json.dumps(listing, indent=2, ensure_ascii=False).encode("utf-8")
    archive_files = dict(source)
    archive_files["TESTKIT_MANIFEST.json"] = metadata
    with ZipFile(OUT, "x", compression=ZIP_DEFLATED, compresslevel=7) as archive:
        for name, raw in sorted(archive_files.items()):
            info = ZipInfo(name, date_time=(2026, 10, 28, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, raw, compress_type=ZIP_DEFLATED, compresslevel=7)
    with ZipFile(OUT) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("Archive integrity check failed")
        if set(archive.namelist()) != set(archive_files):
            raise RuntimeError("Archive entries differ from planned source")
        for name, raw in archive_files.items():
            if sha256(archive.read(name)) != sha256(raw):
                raise RuntimeError(f"Archived file hash mismatch: {name}")

    result = {
        "zip": str(OUT),
        "bytes": OUT.stat().st_size,
        "sha256": sha256(OUT.read_bytes()),
        "entries": len(archive_files),
        "orbis_prx_count": 2,
        "source_files": len(source) - 2,
        "original_modloader_binaries_included": False,
        "tested_on_console": False,
        "all_archived_sha256_verified": True,
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
