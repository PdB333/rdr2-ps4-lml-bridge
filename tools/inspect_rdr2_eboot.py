#!/usr/bin/env python3
"""Offline fiDevice / RPF8 vtable locator for a user-owned PS4 RDR2 ELF.

Read-only. Requires Python standard library only. Does not decrypt a SELF,
modify the game, publish any binary or attempt a live PS4 hook.

Example:
  python -B tools/inspect_rdr2_eboot.py eboot.bin \
    --expected-sha256 e3ae087f833b0f30f462bb7f880dd2955bf9f51dbb6e56706ee9bda81581feff \
    --out private-eboot-audit.json

Do not put eboot.bin in the public Git repository.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import mmap
import struct
import sys
from pathlib import Path

HEADER = struct.Struct("<16sHHIQQQIHHHHHH")
PROGRAM = struct.Struct("<IIQQQQQQ")
TYPES = {
    "fiDevice": "N4rage8fiDeviceE",
    "fiPackfile7": "N4rage11fiPackfile7E",
    "fiPackfile8": "N4rage11fiPackfile8E",
    "fiDeviceRelative": "N4rage16fiDeviceRelativeE",
    "fiDeviceLocal": "N4rage13fiDeviceLocalE",
}
SLOTS = {
    0: "destructor_candidate",
    1: "deleting_destructor_candidate",
    2: "open_path_candidate",
    6: "open_bulk_candidate",
    13: "read_candidate",
    14: "read_bulk_candidate",
}


class Image:
    def __init__(self, raw: mmap.mmap) -> None:
        self.raw = raw
        if len(raw) < HEADER.size:
            raise ValueError("ELF header absent")
        (ident, kind, machine, version, entry, phoff, shoff, flags,
         ehsize, phentsize, phnum, shentsize, shnum, shstrndx) = HEADER.unpack_from(raw)
        if ident[:4] != b"\x7fELF" or ident[4:7] != bytes((2, 1, 1)):
            raise ValueError("Expected little-endian ELF64")
        if kind != 0xFE10 or machine != 62 or ident[7] != 9:
            raise ValueError("Expected x86_64 Orbis/FreeBSD executable")
        if not 0 < phnum < 200 or phentsize != PROGRAM.size:
            raise ValueError("Unexpected program header layout")
        if phoff + phnum * phentsize > len(raw):
            raise ValueError("Program headers outside file")
        self.segments = []
        for i in range(phnum):
            typ, fl, off, va, pa, n, memory, alignment = PROGRAM.unpack_from(
                raw, phoff + i * phentsize)
            if typ in (1, 0x61000010):
                if off + n > len(raw):
                    raise ValueError("Truncated load segment")
                self.segments.append((va, off, n, fl))
        if not self.segments:
            raise ValueError("No mapped segments")
        self.header = {
            "format": "Orbis ELF64 x86_64",
            "entry_rva": hex(entry),
            "phnum": phnum,
            "section_headers_present": not bool(
                shnum and shoff + shnum * shentsize > len(raw)),
        }

    def offset_rva(self, offset: int) -> int:
        for va, off, size, flags in self.segments:
            if off <= offset < off + size:
                return va + offset - off
        raise ValueError(f"Unmapped file offset 0x{offset:x}")

    def rva_offset(self, rva: int, length: int = 1) -> int:
        for va, off, size, flags in self.segments:
            if va <= rva and rva + length <= va + size:
                return off + rva - va
        raise ValueError(f"Unmapped RVA 0x{rva:x}")

    def qword(self, rva: int) -> int:
        return struct.unpack_from("<Q", self.raw, self.rva_offset(rva, 8))[0]

    def is_executable(self, rva: int) -> bool:
        return any(va <= rva < va + n and flags & 1
                   for va, off, n, flags in self.segments)

    def readonly_refs(self, value: int) -> list[int]:
        needle = struct.pack("<Q", value)
        results = []
        for va, off, n, flags in self.segments:
            if not (flags & 4) or (flags & 3):
                continue
            end = off + n
            cursor = off
            while (cursor := self.raw.find(needle, cursor, end)) >= 0:
                results.append(self.offset_rva(cursor))
                cursor += 1
        return results

    def locate(self, type_name: str) -> dict:
        name_bytes = type_name.encode("ascii") + b"\0"
        name_file = self.raw.find(name_bytes)
        if name_file < 0 or self.raw.find(name_bytes, name_file + 1) >= 0:
            raise ValueError(f"Missing/ambiguous RAGE RTTI name: {type_name}")
        name_rva = self.offset_rva(name_file)
        rtinfos = [x - 8 for x in self.readonly_refs(name_rva)
                   if self.qword(x - 8) == 0x10]
        if len(rtinfos) != 1:
            raise ValueError(f"Missing/ambiguous RTTI object: {type_name}")
        info = rtinfos[0]
        result = {"rtti_type": type_name,
                  "type_name_rva": f"0x{name_rva:08X}",
                  "typeinfo_rva": f"0x{info:08X}"}
        tables = [p + 8 for p in self.readonly_refs(info)
                  if self.qword(p - 8) == 0
                  and self.is_executable(self.qword(p + 8))]
        if not tables and type_name == "N4rage8fiDeviceE":
            result["no_concrete_vtable_identified"] = True
            return result
        if len(tables) != 1:
            raise ValueError(f"Missing/ambiguous vtable: {type_name}")
        vt = tables[0]
        result["vtable_rva"] = f"0x{vt:08X}"
        result["methods"] = {}
        for slot, label in SLOTS.items():
            method = self.qword(vt + 8 * slot)
            if not self.is_executable(method):
                raise ValueError(f"Invalid {type_name} vtable slot {slot}")
            o = self.rva_offset(method, 16)
            result["methods"][label] = {
                "slot": slot, "rva": f"0x{method:08X}",
                "first_16_bytes": self.raw[o:o+16].hex(),
            }
        return result


def inspect(path: Path, expected_hash: str) -> dict:
    sha = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            sha.update(chunk)
    digest = sha.hexdigest()
    if expected_hash and digest != expected_hash.lower():
        raise ValueError("ELF SHA-256 does not match this version profile")
    with path.open("rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as raw:
        image = Image(raw)
        return {
            "schema": "rdr2-orbis-rage-vfs-readonly-analysis/1",
            "input_filename": path.name,
            "bytes": len(raw), "sha256": digest,
            "confirmed_patch": None, "confirmed_title_id": None,
            "hook_installed": False,
            "elf": image.header,
            "classes": {name: image.locate(symbol)
                        for name, symbol in TYPES.items()},
            "warning": "Static candidate RVAs only; game patch, live loader and ABI must be verified before hooking.",
        }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("eboot", type=Path)
    ap.add_argument("--expected-sha256", default="")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    try:
        result = inspect(args.eboot, args.expected_sha256)
        content = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
        if args.out:
            if args.out.exists():
                raise ValueError("Refusing to overwrite existing report")
            args.out.write_text(content, encoding="utf-8")
            print("Static report saved:", args.out)
        else:
            print(content)
        return 0
    except (OSError, ValueError, struct.error) as e:
        print("Inspection failed:", e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
