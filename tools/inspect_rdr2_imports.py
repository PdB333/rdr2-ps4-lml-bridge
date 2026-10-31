#!/usr/bin/env python3
"""Offline Orbis import-table audit for the user-owned RDR2 PS4 1.00 EBOOT.

Read-only. Standard library only. Does not decrypt, patch, upload or hook.
Answers one question: which module-loading / filesystem primitives does the
game import, and at which GOT (JMPREL r_offset) RVA, so a later read-only
pass can check whether that slot is resolved in RAM.

PS4 symbol names are "<nid>#<lib>#<mod>"; nid = base64(sha1(name+salt)[:8]
reversed), custom alphabet "+-". Verified pairs (see tests):
  malloc -> gQX+4GDQjpM, printf -> hcuQgD53UxM,
  sceKernelLoadStartModule -> wzvqT4UqKX8.

Usage:
  python -B tools/inspect_rdr2_imports.py <eboot.bin> [--json out.json]
Never commit eboot.bin or any report containing proprietary strings.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import struct
import sys
from pathlib import Path

KNOWN_EBOOT_100_SHA = (
    "e3ae087f833b0f30f462bb7f880dd2955bf9f51dbb6e56706ee9bda81581feff")
NID_SALT = bytes.fromhex("518D64A635DED8C1E6B039B1C3E55230")
PT_LOAD = 1
PT_SCE_DYNLIBDATA = 0x61000000
PT_DYNAMIC = 2
# Orbis DT_SCE_* dynamic tags (offsets are relative to the dynlibdata segment).
DT = {"STRTAB": 0x61000035, "STRSZ": 0x61000037, "SYMTAB": 0x61000039,
      "SYMENT": 0x6100003B, "SYMTABSZ": 0x6100003F,
      "JMPREL": 0x61000029, "PLTRELSZ": 0x6100002D, "PLTGOT": 0x61000027}
# Primitives worth reporting for a plugin-loader strategy.
WATCH = ("sceKernelLoadStartModule", "sceKernelLoadStartModuleForPlugin",
         "sceSysmoduleLoadModule", "sceSysmoduleLoadModuleInternal",
         "sceKernelDlsym", "sceKernelOpen", "sceKernelStat",
         "sceKernelMmap", "sceKernelMprotect", "malloc", "printf",
         "fopen", "stat", "open")


def nid(name: str) -> str:
    digest = hashlib.sha1(name.encode() + NID_SALT).digest()[:8][::-1]
    return base64.b64encode(digest, b"+-").decode()[:11]


def _segments(raw: bytes) -> dict[int, tuple[int, int, int, int]]:
    header = struct.Struct("<16sHHIQQQIHHHHHH")
    fields = header.unpack_from(raw)
    if fields[0][:4] != b"\x7fELF" or fields[1] != 0xFE10:
        raise ValueError("Not an Orbis ET_SCE_EXEC_ASLR ELF")
    phoff, phnum = fields[5], fields[10]
    program = struct.Struct("<IIQQQQQQ")
    out: dict[int, tuple[int, int, int, int]] = {}
    for i in range(phnum):
        typ, fl, off, va, pa, fsz, msz, al = program.unpack_from(
            raw, phoff + i * program.size)
        out.setdefault(typ, (off, va, fsz, msz))
    if PT_LOAD not in out or PT_SCE_DYNLIBDATA not in out or PT_DYNAMIC not in out:
        raise ValueError("Missing LOAD / DYNAMIC / DYNLIBDATA segment")
    return out


def _dynamic(raw: bytes, dyn_off: int, dyn_sz: int) -> dict[int, int]:
    tags: dict[int, int] = {}
    for off in range(dyn_off, dyn_off + dyn_sz, 16):
        tag, val = struct.unpack_from("<QQ", raw, off)
        tags.setdefault(tag, val)
    return tags


def _cstr(raw: bytes, off: int) -> str:
    return raw[off:raw.index(b"\0", off)].decode("latin1")


def analyze(raw: bytes) -> dict:
    segs = _segments(raw)
    dld = segs[PT_SCE_DYNLIBDATA][0]
    dyn_off, _, dyn_sz, _ = segs[PT_DYNAMIC]
    tags = _dynamic(raw, dyn_off, dyn_sz)
    need = {k: tags[v] for k, v in DT.items() if v in tags}
    str_base = dld + need["STRTAB"]
    sym_base, sym_sz = dld + need["SYMTAB"], need["SYMTABSZ"]
    names: list[str] = []
    for off in range(sym_base, sym_base + sym_sz, 24):
        st_name = struct.unpack_from("<I", raw, off)[0]
        names.append(_cstr(raw, str_base + st_name).split("#", 1)[0])
    got: dict[str, int] = {}
    jmp_base, jmp_sz = dld + need["JMPREL"], need["PLTRELSZ"]
    for off in range(jmp_base, jmp_base + jmp_sz, 24):
        r_off, r_info, _ = struct.unpack_from("<QQq", raw, off)
        index = r_info >> 32
        if index < len(names):
            got[names[index]] = r_off
    imported = set(names)
    report = {}
    for func in WATCH:
        key = nid(func)
        report[func] = {
            "nid": key,
            "imported": key in imported,
            "got_rva": f"0x{got[key]:08X}" if key in got else None,
        }
    return {
        "schema": "rdr2-orbis-imports-readonly/1",
        "jmprel_import_count": jmp_sz // 24,
        "symbol_count": len(names),
        "pltgot_rva": f"0x{need.get('PLTGOT', 0):08X}",
        "watched_imports": report,
        "note": ("GOT slots are populated by the loader at runtime; a zero "
                 "value in RAM means the import is not resolved via a "
                 "readable data GOT (Orbis may patch PLT stubs instead)."),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("eboot", type=Path)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--expected-sha256", default=KNOWN_EBOOT_100_SHA)
    args = parser.parse_args(argv)
    try:
        raw = args.eboot.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if args.expected_sha256 and digest != args.expected_sha256.lower():
            raise ValueError("EBOOT SHA-256 does not match the 1.00 profile")
        result = analyze(raw)
        result["sha256"] = digest
        text = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
        if args.json:
            if args.json.exists():
                raise ValueError("Refusing to overwrite existing report")
            args.json.write_text(text, encoding="utf-8")
            print("Import report saved:", args.json)
        else:
            print(text)
        return 0
    except (OSError, ValueError, struct.error) as exc:
        print("Import inspection failed:", exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
