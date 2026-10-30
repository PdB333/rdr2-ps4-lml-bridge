#!/usr/bin/env python3
"""Verify the owner's RDR2 PS4 v1.00 EBOOT against the guarded VFS profile.

READ ONLY. Never publishes, decrypts, patches, or uploads an EBOOT.
The input is the user's own decrypted ELF (NOT an encrypted SELF).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import mmap
import struct
import sys
from pathlib import Path
from inspect_rdr2_eboot import Image

KNOWN_EBOOT_100_SHA="e3ae087f833b0f30f462bb7f880dd2955bf9f51dbb6e56706ee9bda81581feff"
KNOWN_VTABLE_100_FNV=0x8EAECB696678DAD0
VTABLE_RVA=0x066B00F8
NAME_RVA=0x05D7DE40
RTTI_RVA=0x066B0480
SLOTS=112
METHODS={2:0x0452A480,6:0x0452A780,13:0x0452B9D0,
         14:0x0452BA60,19:0x0452BE00}
TYPE_NAME=b"N4rage11fiPackfile8E\0"


def inspect_100(path: Path) -> dict:
    sha=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(8*1024*1024),b""):
            sha.update(chunk)
    digest=sha.hexdigest()
    if digest!=KNOWN_EBOOT_100_SHA:
        raise ValueError("Not the known RDR2 PS4 1.00 EBOOT; refusing to use these RVAs")
    with path.open("rb") as f, mmap.mmap(f.fileno(),0,
                                         access=mmap.ACCESS_READ) as mem:
        img=Image(mem)
        def rva(location:int,length:int)->bytes:
            off=img.rva_offset(location,length)
            return mem[off:off+length]
        def qword(location:int)->int:
            return struct.unpack("<Q",rva(location,8))[0]
        if rva(NAME_RVA,len(TYPE_NAME))!=TYPE_NAME:
            raise ValueError("fiPackfile8 type name mismatch")
        if qword(VTABLE_RVA-16)!=0 or qword(VTABLE_RVA-8)!=RTTI_RVA:
            raise ValueError("fiPackfile8 RTTI header mismatch")
        methods=[qword(VTABLE_RVA+8*i) for i in range(SLOTS)]
        if qword(VTABLE_RVA+8*SLOTS)!=0:
            raise ValueError("Unexpected fiPackfile8 vtable boundary")
        fnv=0xcbf29ce484222325
        for i,addr in enumerate(methods):
            if not img.is_executable(addr):
                raise ValueError(f"Vtable slot {i} is not executable")
            for b in addr.to_bytes(8,"little"):
                fnv=((fnv^b)*0x100000001b3)&0xffffffffffffffff
        if fnv!=KNOWN_VTABLE_100_FNV:
            raise ValueError("Full 112-method vtable fingerprint mismatch")
        for index,expected in METHODS.items():
            if methods[index]!=expected:
                raise ValueError(f"Expected method slot {index} mismatch")
        return {
            "schema":"rdr2-ps4-fiPackfile8-preflight/1",
            "version_user_confirmed":"1.00",
            "source_eboot_sha256":digest,
            "source_bytes":len(mem),
            "vtable_rva":hex(VTABLE_RVA),
            "method_count":SLOTS,
            "full_vtable_fnv64":f"{fnv:016x}",
            "verified_method_rvas":{str(i):hex(methods[i])
                                     for i in METHODS},
            "supports_ps4_1_32":False,
            "live_hook_installed":False,
            "tested_on_console":False,
            "requires_live_device_lifetime_verification":True,
        }


def main()->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("eboot",type=Path)
    parser.add_argument("--out",type=Path)
    args=parser.parse_args()
    try:
        data=inspect_100(args.eboot)
        text=json.dumps(data,indent=2,ensure_ascii=False)+"\n"
        if args.out:
            if args.out.exists():
                raise ValueError("Output report already exists")
            args.out.write_text(text,encoding="utf-8")
            print("Read-only 1.00 EBOOT report saved to",args.out)
        else:
            print(text)
    except (OSError,ValueError,struct.error) as exc:
        print("Verification failed:",exc,file=sys.stderr)
        return 2
    return 0


if __name__=="__main__":
    raise SystemExit(main())
