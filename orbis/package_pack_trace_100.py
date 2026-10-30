#!/usr/bin/env python3
"""Package independent PS4 1.00 fiPackfile8 trace source and diagnostic PRX.

LOCAL-ONLY release. Never includes the owner's EBOOT, proprietary LML
binaries, sample assets, OpenOrbis SDK, passwords or console dumps.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"LML_BRIDGE_RDR2_PS4_100_PS5_FW1340_DEVKIT.zip"
FILES=[
    "AGENTS.md", "README.md", "PORTING_STATUS.md",
    "orbis/EBOOT_RAGE_VFS_PROFILE.md",
    "orbis/RDR2_PS4_100_TRACE_STATUS.md",
    "orbis/PS5DEBUG_NG_LOCAL_NETWORK.md",
    "orbis/pack_trace_100_module.c",
    "orbis/build_pack_trace_100.ps1",
    "orbis/package_pack_trace_100.py",
    "runtime/rage_eboot_profile.c",
    "runtime/rage_eboot_profile.h",
    "runtime/rdr2_100_registry.c",
    "runtime/rdr2_100_registry.h",
    "runtime/rdr2_100_pack_trace.cpp",
    "runtime/rdr2_100_pack_trace.h",
    "tools/inspect_rdr2_eboot.py",
    "tools/verify_eboot_100.py",
    "tools/ps5debug_ng_probe.py",
    "tools/verify_pack_trace_100.ps1",
    "tests/test_rdr2_100_trace.cpp",
    "tests/test_rdr2_100_orbis.py",
    "tests/test_rdr2_100_inspector.py",
    "tests/test_ps5debug_ng_probe.py",
    "orbis_build/pack_trace_100_report.json",
    "orbis_build/pack_trace_100_final_validation.json",
    "orbis_build/LmlBridge_RDR2_PS4_100_fiPackfile8_trace.prx",
    "orbis_build/rdr2_100_trace_harness.exe",
]


def sha(blob:bytes)->str:
    return hashlib.sha256(blob).hexdigest()


def main()->None:
    if OUT.exists():
        raise ValueError(f"Output already exists: {OUT}")
    source={}
    for name in FILES:
        path=ROOT/name
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(ROOT.resolve()):
            raise ValueError(f"Missing, linked, or escaped file: {name}")
        source[name]=path.read_bytes()
    metadata=json.loads(source["orbis_build/pack_trace_100_report.json"].decode("utf-8-sig"))
    final=json.loads(source["orbis_build/pack_trace_100_final_validation.json"].decode("utf-8-sig"))
    prx=source["orbis_build/LmlBridge_RDR2_PS4_100_fiPackfile8_trace.prx"]
    assert prx[:4]==bytes.fromhex("4f153d1d")
    assert sha(prx)==metadata["sha256"]==final["prx_sha256"]
    assert len(prx)==metadata["bytes"]==final["prx_bytes"]
    assert metadata["profile_game"]=="RDR2 PS4 1.00"
    assert metadata["auto_installed_in_game"] is False
    assert metadata["direct_resource_replacement_available"] is False
    assert metadata["console_tested"] is False
    assert final["live_PS5_tested"] is False
    manifest={
        "format":"lml-rdr2-ps4-100-hardening-kit/1",
        "target_game":"RDR2 PS4 v1.00",
        "console_target":"PS5 FW13.40 Y2JB/Kstuff Lite (NOT TESTED IN GAME)",
        "status":"offline_verified_passive_trace_only",
        "source_eboot_included":False,
        "original_lml_binaries_included":False,
        "sample_mod_assets_included":False,
        "auto_hook_installed":False,
        "in_game_replacement_functional":False,
        "files":[{"name":n,"size":len(b),"sha256":sha(b)}
                 for n,b in sorted(source.items())],
    }
    inside=dict(source)
    inside["KIT_MANIFEST.json"]=(json.dumps(manifest,indent=2,ensure_ascii=False)+"\n").encode()
    with ZipFile(OUT,"x",ZIP_DEFLATED,compresslevel=7) as archive:
        for name,blob in sorted(inside.items()):
            info=ZipInfo(name,date_time=(2026,10,30,0,0,0))
            info.compress_type=ZIP_DEFLATED
            info.external_attr=0o644<<16
            archive.writestr(info,blob,compress_type=ZIP_DEFLATED,compresslevel=7)
    with ZipFile(OUT) as archive:
        if archive.testzip() is not None or set(archive.namelist())!=set(inside):
            raise RuntimeError("Corrupt archive structure")
        for name,blob in inside.items():
            if sha(archive.read(name))!=sha(blob):
                raise RuntimeError(f"Archive file checksum mismatch: {name}")
    print(json.dumps({
        "zip":str(OUT.resolve()),"bytes":OUT.stat().st_size,
        "sha256":sha(OUT.read_bytes()),"entries":len(inside),
        "prx_validated":True,"checksums_verified":True,
        "console_tested":False,"game_hook_autoinstalled":False,
    },indent=2))


if __name__=="__main__":
    main()
