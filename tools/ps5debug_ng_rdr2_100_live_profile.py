#!/usr/bin/env python3
"""Compare a few bytes of the running RDR2 PS4 1.00 to the EBOOT profile.

Safety contract:
- PS5 FW must be 13.40, current game must be RDR2 CUSA08519 with
  PS4 base-game metadata 1.00/01.00 and a matching live PID;
- locate the contiguous regions named "executable" (r-x text, r-- RELRO,
  rw- data/bss); the image base is the start of the first r-x region and
  every approved RVA must land inside ONE readable image region before
  contacting process memory;
- issue ONLY CMD_PROC_READ (0xBDAA0002), at approved small read sizes:
    RTTI type name (21 bytes), vtable boundary header (16 bytes),
    vtable 112 slots (896 bytes), end boundary (8 bytes), and
    4 function prefixes (16 bytes each);
- NO target writes, injections, debugger attach, callbacks, patches,
  memory dumps, arbitrary address requests, or file writes;
- fail closed when ANY signature differs, and never reuse EBOOT 1.00
  RVAs on PS4 patch 1.32 or mismatched PS5 FW;
- hash only the 112 normalized addresses (FNV-1a); does NOT compute
  the SHA-256 of the full in-memory executable, does NOT prove an exact
  byte-for-byte match to the uploaded proprietary EBOOT.

Address model (verified live on PS5 13.40, 31 Oct 2026): the EBOOT is
ET_SCE_EXEC_ASLR (0xFE10), its PT_LOAD p_vaddr start at 0, so every
profile "RVA" is relative to the image base. Runtime address =
image_base + RVA, with image_base = start of the first "executable"
region (0x00400000 observed). The former code assumed the RVAs were
already absolute (bias 0), which explains the earlier false mismatch.

Protocol: https://github.com/Pharaoh2k/ps5debug-NG/blob/master/PROTOCOL.md
cmd_proc_read_packet is packed (pid u32; address u64; length u32).
"""
from __future__ import annotations
import argparse
import json
import socket
import struct
import sys

from ps5debug_ng_probe import (
    PACKET_MAGIC, COMMAND_PORT, DEFAULT_EXPECTED_FW, parse_expected_fw,
    recv_exact, validate_local_ip, verify_tailscale_route,
)
from ps5debug_ng_rdr2_maps import inspect_maps
from ps5debug_ng_rdr2_identity import check_response_ok

CMD_PROC_READ = 0xBDAA0002
MAX_IMAGE_REGIONS = 16
VTABLE = 0x066B00F8
VTABLE_SLOTS = 112
VTABLE_FNV = 0x8EAECB696678DAD0
RTTI_PTR = 0x066B0480
TYPE_RVA = 0x05D7DE40
TYPE_NAME = b"N4rage11fiPackfile8E\0"
METHODS = {
    2:0x0452A480, 6:0x0452A780, 13:0x0452B9D0,
    14:0x0452BA60, 19:0x0452BE00,
}
PREFIXES = {
    0x0452A480: bytes.fromhex("554889e54157415641554154534883ec"),
    0x0452A780: bytes.fromhex("554889e5415741564154534989d631d2"),
    0x0452B9D0: bytes.fromhex("554889e5415741564155415453504889"),
    0x0452BA60: bytes.fromhex("488b4710488b7720488b384c8b4f7048"),
}

# Restrict every memory-read request to this explicit list of tuples.
# Even the map data cannot expand the list of addresses or sizes.
READ_PLAN = (
    (TYPE_RVA, len(TYPE_NAME)),
    (VTABLE-16, 16),
    (VTABLE, VTABLE_SLOTS*8),
    (VTABLE+VTABLE_SLOTS*8, 8),
    *[(rva, 16) for rva in PREFIXES],
)
READ_PLAN_SET = frozenset(READ_PLAN)
MAX_READ = VTABLE_SLOTS*8


def fnv_vtable(table: bytes, image_bias: int) -> int:
    if len(table)!=VTABLE_SLOTS*8 or image_bias<0:
        raise ValueError("Taille de vtable ou base invalide")
    result=0xCBF29CE484222325
    for i in range(VTABLE_SLOTS):
        address=struct.unpack_from("<Q",table,i*8)[0]
        if not 0 < address-image_bias < VTABLE:
            # Method entries lie in the analyzed executable's earlier code.
            raise ValueError("Slot virtuel hors segment de code v1.00")
        for byte in (address-image_bias).to_bytes(8,"little"):
            result=((result^byte)*0x100000001B3)&0xFFFFFFFFFFFFFFFF
    return result


def select_main_image(maps: dict)->tuple[int,tuple[tuple[int,int,int],...]]:
    """Return (image_base, regions) for the regions named "executable".

    Regions must be contiguous; the first must be r-x. Bias is the start
    of that first region because the 0xFE10 EBOOT's p_vaddr start at 0.
    """
    rows=[]
    for item in maps.get("main_image_regions",[]):
        if item.get("name")!="executable":
            continue
        try:
            rows.append((int(item["start"],16),int(item["end"],16),
                         int(item.get("prot",0))))
        except (KeyError,ValueError,TypeError):
            raise ValueError("Region 'executable' illisible") from None
    rows.sort()
    if not rows or len(rows)>MAX_IMAGE_REGIONS:
        raise ValueError("Image principale 'executable' absente ou ambigue")
    for (s0,e0,_),(s1,e1,_) in zip(rows,rows[1:]):
        if e0!=s1:
            raise ValueError("Image principale 'executable' non contigue")
    if any(e<=s for s,e,_ in rows) or (rows[0][2]&5)!=5:
        raise ValueError("Image principale 'executable' absente ou ambigue")
    base=rows[0][0]
    if not 0<base<2**47:
        raise ValueError("Base de chargement non valide")
    regions=tuple(rows)
    for rva,size in READ_PLAN:
        region_for(regions,base+rva,size)
    return base,regions


def region_for(regions,address:int,size:int)->tuple[int,int,int]:
    for start,end,prot in regions:
        if start<=address and address+size<=end:
            if not prot&1:
                break
            return start,end,prot
    raise ValueError("Signature v1.00 hors de l'image principale lisible")


def read_profile_chunk(conn: socket.socket, pid: int, base: int,
                       regions, rva: int, length: int)->bytes:
    if (rva,length) not in READ_PLAN_SET:
        raise ValueError("Lecture interdite hors des signatures v1.00")
    if not isinstance(pid,int) or pid<=0 or pid>0x7FFFFFFF:
        raise ValueError("PID non valide")
    if not(0<base<2**47):
        raise ValueError("Base de chargement non valide")
    address=base+rva
    region_for(regions,address,length)
    raw=struct.pack("<IQI",pid,address,length)
    conn.sendall(struct.pack("<III",PACKET_MAGIC,CMD_PROC_READ,len(raw))+raw)
    check_response_ok(conn)
    return recv_exact(conn,length) if length<=512 else (
        recv_exact(conn,512)+recv_exact(conn,length-512)
    )


def validate_profile(chunks: dict[tuple[int,int],bytes], bias: int)->dict:
    t=chunks[(TYPE_RVA,len(TYPE_NAME))]
    h=chunks[(VTABLE-16,16)]
    v=chunks[(VTABLE,VTABLE_SLOTS*8)]
    tail=chunks[(VTABLE+VTABLE_SLOTS*8,8)]
    typ_ok=t==TYPE_NAME
    header_ok=(len(h)==16 and
        struct.unpack_from("<Q",h,0)[0]==0 and
        struct.unpack_from("<Q",h,8)[0]==bias+RTTI_PTR)
    boundary_ok=tail==b"\0"*8
    method_ok=all(
        struct.unpack_from("<Q",v,index*8)[0]==bias+rva
        for index,rva in METHODS.items()
    )
    try:
        fp=fnv_vtable(v,bias)
        vtable_ok=fp==VTABLE_FNV
    except ValueError:
        fp=None
        vtable_ok=False
    code_ok=all(chunks[(rva,16)]==expected
                for rva,expected in PREFIXES.items())
    everything=all((typ_ok,header_ok,boundary_ok,method_ok,
                    vtable_ok,code_ok))
    nonzero=sum(sum(b!=0 for b in blob) for blob in chunks.values())
    return {
        "rtti_type_name_matches":typ_ok,
        "vtable_header_matches":header_ok,
        "vtable_end_boundary_matches":boundary_ok,
        "five_known_method_slots_match":method_ok,
        "all_112_virtual_methods_fingerprint_matches":vtable_ok,
        "computed_vtable_fnv64":f"{fp:016x}" if fp is not None else None,
        "four_code_entry_prefixes_match":code_ok,
        "live_rage_packfile8_profile_matches_eboot_100":everything,
        "full_executable_sha256_verified":False,
        "game_hook_installed":False,
        "game_memory_modified":False,
        "game_bytes_read":sum(len(blob) for blob in chunks.values()),
        "nonzero_game_bytes_returned":nonzero,
        "possibly_zero_filled_read_failure":nonzero==0,
    }


def check_live(ip: str, *, tailscale: bool=False,
               expected_fw: int=DEFAULT_EXPECTED_FW,
               timeout: float=8.0)->dict:
    target=validate_local_ip(ip,tailscale=tailscale)
    info=inspect_maps(target,tailscale=tailscale,
                      expected_fw=expected_fw,timeout=timeout)
    meta=info["map_metadata"]
    if info["game_title_id"]!="CUSA08519" or info["game_version_metadata"] not in ("1.00","01.00"):
        raise ValueError("Titre RDR2 1.00 non identifie : aucune lecture de code")
    bias,regions=select_main_image(meta)
    if tailscale:
        verify_tailscale_route(target)
    pid=info["pid"]
    chunks={}
    with socket.create_connection((target,COMMAND_PORT),timeout=timeout) as conn:
        conn.settimeout(timeout)
        for rva,length in READ_PLAN:
            chunks[(rva,length)]=read_profile_chunk(
                conn,pid,bias,regions,rva,length
            )
    return {
        "firmware":info["firmware"],
        "game_title_id":info["game_title_id"],
        "game_version_metadata":info["game_version_metadata"],
        "pid":pid,
        "image_base":f"0x{bias:x}",
        "image_regions":[{"start":f"0x{a:016x}","end":f"0x{b:016x}",
                          "prot":p} for a,b,p in regions],
        "profile":validate_profile(chunks,bias),
        "profile_is_read_only":True,
    }


def main(argv: list[str]|None=None)->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ip",required=True)
    parser.add_argument("--tailscale",action="store_true")
    parser.add_argument("--expected-fw",type=parse_expected_fw,
                        default=DEFAULT_EXPECTED_FW)
    parser.add_argument("--timeout",type=float,default=8.0)
    args=parser.parse_args(argv)
    try:
        result=check_live(args.ip,tailscale=args.tailscale,
                          expected_fw=args.expected_fw,timeout=args.timeout)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        if not result["profile"]["live_rage_packfile8_profile_matches_eboot_100"]:
            print("Profil fiPackfile8 non conforme : AUCUN hook permis.",
                  file=sys.stderr)
            return 4
        return 0
    except (ValueError,ConnectionError,OSError,struct.error,KeyError) as exc:
        print("Profil live interrompu sans modification : "+str(exc),
              file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
