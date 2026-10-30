#!/usr/bin/env python3
"""Package the independently implemented RDR2/Orbis RAGE VFS adapter.

NO proprietary LML .asi/.dll, NO game eboot, NO mod assets, NO SDK archive.
The PRX is an adapter with unbound game callbacks, NOT a functioning in-game
hook for RDR2 PS4 1.32. Reproducible ZIP, hashes of every included byte.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "LML_BRIDGE_RDR2_PS4_100_EBOOT_PROFILE_DEVKIT.zip"
FILES = (
    "README.md",
    "PORTING_STATUS.md",
    "orbis/RAGE_VFS_132_PORT.md",
    "orbis/EBOOT_RAGE_VFS_PROFILE.md",
    "orbis/CONSOLE_DIAGNOSTIC.md",
    "orbis/build_rage_vfs.ps1",
    "orbis/rage_vfs_module.c",
    "orbis/package_rage_vfs.py",
    "runtime/overlay_index.hpp",
    "runtime/overlay_index.cpp",
    "runtime/rage_vfs_redirect.h",
    "runtime/rage_vfs_redirect.cpp",
    "runtime/rage_eboot_profile.h",
    "runtime/rage_eboot_profile.c",
    "runtime/rage_eboot_profile_harness.c",
    "tools/inspect_rdr2_eboot.py",
    "runtime/rage_vfs_harness.cpp",
    "tests/test_rage_vfs.py",
    "tests/test_eboot_profile.py",
    "tests/test_eboot_inspector.py",
    "orbis_build/rage_vfs_report.json",
    "orbis_build/FINAL_RAGE_VFS_VALIDATION.json",
    "orbis_build/LmlBridge_132_rage_vfs_adapter.prx",
    "orbis_build/rage_vfs_harness.exe",
    "orbis_build/rage_eboot_profile_harness.exe",
)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def main() -> None:
    if OUT.exists():
        raise RuntimeError(f"Archive already exists; refusing overwrite: {OUT}")
    files: dict[str, bytes] = {}
    for relative in FILES:
        path = ROOT / relative
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"Source file missing or symlink: {path}")
        if not path.resolve().is_relative_to(ROOT.resolve()):
            raise RuntimeError(f"File escapes root: {path}")
        if path.suffix.lower() in {".asi", ".dll", ".bin", ".elf", ".sprx"}:
            raise RuntimeError(f"Proprietary or unsupported binary format: {path}")
        files[relative] = path.read_bytes()
    prxname = "orbis_build/LmlBridge_132_rage_vfs_adapter.prx"
    report = json.loads(files["orbis_build/rage_vfs_report.json"].decode("utf-8-sig"))
    binary = files[prxname]
    if binary[:4] != bytes.fromhex("4f153d1d"):
        raise RuntimeError("Orbis SELF header missing")
    if digest(binary) != report["sha256"] or len(binary) != report["bytes"]:
        raise RuntimeError("PRX SHA-256/size does not match the build report")
    if report.get("profile_source_game_version") != "1.00" or report.get("profile_supports_target_game_1_32") is not False:
        raise RuntimeError("This EBOOT fingerprint is valid for PS4 v1.00 only, not 1.32")
    for field in ("actual_rage_hook_installed", "tested_on_ps5",
                  "title_verified_eboot_offsets_available"):
        if report[field] is not False:
            raise RuntimeError("Package cannot claim unsupported in-game capability")

    manifest = {
        "format": "rdr2-lml-rage-vfs-readthrough-devkit/1",
        "target_game": "RDR2 PS4 1.32 on PS5 13.60 (requires separate 1.32 EBOOT)",
        "analyzed_eboot_version_confirmed_by_user": "1.00",
        "eboot_profile_compatible_with_1_32": False,
        "profile_guard_explicitly_rejects_patch_1_32": True,
        "purpose": "Orbis adapter + offline-tested read-through RAGE VFS replacement engine",
        "in_game_hook_installed": False,
        "eboot_132_verified": False,
        "uploaded_orbis_eboot_static_analysis_done": True,
        "uploaded_eboot_sha256": "e3ae087f833b0f30f462bb7f880dd2955bf9f51dbb6e56706ee9bda81581feff",
        "profile_guard_implemented": True,
        "host_tests_passed": 48,
        "tested_on_ps5": False,
        "original_game_files_modified": False,
        "contains_third_party_lml_binaries": False,
        "contains_game_eboot": False,
        "contains_mod_assets": False,
        "files": [
            {"name": name, "size": len(raw), "sha256": digest(raw)}
            for name, raw in sorted(files.items())
        ],
    }
    everything = dict(files)
    everything["DEVKIT_MANIFEST.json"] = (
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    with ZipFile(OUT, "x", compression=ZIP_DEFLATED, compresslevel=7) as archive:
        for name, raw in sorted(everything.items()):
            meta = ZipInfo(name, date_time=(2026, 10, 28, 0, 0, 0))
            meta.compress_type = ZIP_DEFLATED
            meta.external_attr = 0o644 << 16
            archive.writestr(meta, raw, compress_type=ZIP_DEFLATED, compresslevel=7)

    with ZipFile(OUT) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("ZIP failed CRC check")
        if set(archive.namelist()) != set(everything):
            raise RuntimeError("Unexpected ZIP entries")
        for name, raw in everything.items():
            if digest(archive.read(name)) != digest(raw):
                raise RuntimeError(f"ZIP SHA-256 mismatch for {name}")

    print(json.dumps({
        "path": str(OUT.resolve()),
        "bytes": OUT.stat().st_size,
        "sha256": digest(OUT.read_bytes()),
        "entries": len(everything),
        "vfs_api_exports": len(report["exports"]),
        "all_files_verified": True,
        "prx_loadability_on_ps5_confirmed": False,
        "game_hook_installed": False,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
