#!/usr/bin/env python3
"""Read-only check of the RDR2 PS4 1.00 fiCollection registry hypothesis.

Safety contract:
- runs ps5debug_ng_rdr2_100_live_profile.check_live first; the registry is
  read ONLY when the full fiPackfile8 profile matches at image_base + RVA;
- issues ONLY CMD_PROC_READ (0xBDAA0002): the first 512 registry slots
  (8 reads of 512 bytes, inside a rw- "executable" region) and at most
  MAX_OBJECTS reads of 16 bytes (vptr + u16 index) of the listed objects;
- NO writes, attach, call, alloc or hook. Heap addresses are not printed.

Hypothesis tested (from the EBOOT destructor): image_base + 0x08053D40 is a
u16-indexed array of collection pointers; a fiPackfile8 object at slot i
has vptr == image_base + 0x066B00F8 and its u16 index at +8 equal to i.
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
from ps5debug_ng_rdr2_identity import check_response_ok
import ps5debug_ng_rdr2_100_live_profile as live

REGISTRY_RVA = 0x08053D40
SLOTS = 512
CHUNK = 512
MAX_OBJECTS = 64
OBJECT_READ = 16


def read_bytes(conn: socket.socket, pid: int, address: int, length: int) -> bytes:
    if length not in (CHUNK, OBJECT_READ):
        raise ValueError("Lecture interdite : taille non approuvee")
    if not isinstance(pid,int) or pid<=0 or pid>0x7FFFFFFF:
        raise ValueError("PID non valide")
    if not 0<address<2**47 or address&7:
        raise ValueError("Adresse non valide")
    raw=struct.pack("<IQI",pid,address,length)
    conn.sendall(struct.pack("<III",PACKET_MAGIC,live.CMD_PROC_READ,len(raw))+raw)
    check_response_ok(conn)
    return recv_exact(conn,length)


def registry_region(base: int, regions) -> None:
    start,end,prot=live.region_for(regions,base+REGISTRY_RVA,SLOTS*8)
    if prot&3!=3:
        raise ValueError("Registre hors d'une region rw- de l'image")


def classify(base: int, slots: tuple[int,...], objects: dict[int,bytes]) -> dict:
    packfile8=other=skipped=0
    other_vtables=set()
    for index,pointer in enumerate(slots):
        if not pointer:
            continue
        if pointer&7 or index not in objects:
            skipped+=1
            continue
        vptr,slot=struct.unpack_from("<QH",objects[index])
        if vptr==base+live.VTABLE and slot==index:
            packfile8+=1
        else:
            other+=1
            if base<=vptr<base+0x10000000:
                other_vtables.add(vptr-base)
    return {
        "registry_rva":f"0x{REGISTRY_RVA:08X}",
        "slots_read":len(slots),
        "nonzero_slots":sum(1 for p in slots if p),
        "objects_checked":len(objects),
        "fiPackfile8_with_matching_index":packfile8,
        "other_objects":other,
        "other_vtable_rvas":[f"0x{x:08X}" for x in sorted(other_vtables)][:8],
        "unchecked_nonzero_slots":skipped,
        "registry_hypothesis_supported":packfile8>0 and packfile8>=other,
        "game_memory_modified":False,
        "game_hook_installed":False,
    }


def probe(ip: str, *, tailscale: bool=False,
          expected_fw: int=DEFAULT_EXPECTED_FW, timeout: float=8.0) -> dict:
    report=live.check_live(ip,tailscale=tailscale,expected_fw=expected_fw,
                           timeout=timeout)
    if not report["profile"]["live_rage_packfile8_profile_matches_eboot_100"]:
        raise ValueError("Profil fiPackfile8 non conforme : registre non lu")
    base=int(report["image_base"],16)
    regions=tuple((int(r["start"],16),int(r["end"],16),int(r["prot"]))
                  for r in report["image_regions"])
    registry_region(base,regions)
    target=validate_local_ip(ip,tailscale=tailscale)
    if tailscale:
        verify_tailscale_route(target)
    pid=report["pid"]
    with socket.create_connection((target,COMMAND_PORT),timeout=timeout) as conn:
        conn.settimeout(timeout)
        blob=b"".join(read_bytes(conn,pid,base+REGISTRY_RVA+o,CHUNK)
                      for o in range(0,SLOTS*8,CHUNK))
        slots=struct.unpack(f"<{SLOTS}Q",blob)
        objects={}
        for index,pointer in enumerate(slots):
            if len(objects)>=MAX_OBJECTS:
                break
            if pointer and not pointer&7 and pointer<2**47:
                objects[index]=read_bytes(conn,pid,pointer,OBJECT_READ)
    result=classify(base,slots,objects)
    result.update({"pid":pid,"image_base":report["image_base"],
                   "game_bytes_read":report["profile"]["game_bytes_read"]
                   +len(blob)+OBJECT_READ*len(objects)})
    return result


def main(argv: list[str]|None=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ip",required=True)
    parser.add_argument("--tailscale",action="store_true")
    parser.add_argument("--expected-fw",type=parse_expected_fw,
                        default=DEFAULT_EXPECTED_FW)
    parser.add_argument("--timeout",type=float,default=8.0)
    args=parser.parse_args(argv)
    try:
        result=probe(args.ip,tailscale=args.tailscale,
                     expected_fw=args.expected_fw,timeout=args.timeout)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0 if result["registry_hypothesis_supported"] else 4
    except (ValueError,ConnectionError,OSError,struct.error,KeyError) as exc:
        print("Sonde registre interrompue sans modification : "+str(exc),
              file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
