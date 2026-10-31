#!/usr/bin/env python3
"""Inspect ONLY VM map metadata for the validated RDR2 PS4 1.00 process.

Command allowlist is exactly CMD_PROC_MAPS 0xBDAA0004 (read-only).
The game must first pass ps5debug_ng_rdr2_identity.py's on-console
PID + CUSA08519 + base game 01.00 checks on PS5 FW 13.40.
No target memory contents are read, no process attach or code changes.
No logs, IPs, memory maps or user data are written to files/Git.

Protocol source: Pharaoh2k/ps5debug-NG PROTOCOL.md, proc.c,
protocol.h struct proc_vm_map_entry: name[32], start/end/offset u64,
prot u16, packed 58 bytes. Actual loader base still UNVERIFIED here.
"""
from __future__ import annotations
import argparse
import json
import socket
import struct
import sys
from ps5debug_ng_probe import (
    COMMAND_PORT, DEFAULT_EXPECTED_FW, PACKET_MAGIC, parse_expected_fw,
    recv_exact, validate_local_ip, verify_tailscale_route,
)
from ps5debug_ng_rdr2_identity import identify, cstring, check_response_ok

MAP_CMD = 0xBDAA0004
MAP_ENTRY_SIZE = 58
MAX_MAP_COUNT = 16384


def request_maps(conn: socket.socket, pid: int) -> None:
    if not isinstance(pid,int) or pid <= 0 or pid > 0x7FFFFFFF:
        raise ValueError("PID de jeu non valide")
    payload=struct.pack("<I",pid)
    # These bytes are the only allowed command from THIS module.
    conn.sendall(struct.pack("<III",PACKET_MAGIC,MAP_CMD,len(payload))+payload)


def read_map_summary(conn: socket.socket) -> dict:
    check_response_ok(conn)
    count=struct.unpack("<I",recv_exact(conn,4))[0]
    if count > MAX_MAP_COUNT:
        raise ValueError("Trop de regions memoire ; refus de continuer")
    readable=executable=0
    interesting=[]
    candidate_bases=set()
    sample_exec=[]
    for _ in range(count):
        data=recv_exact(conn,MAP_ENTRY_SIZE)
        name=cstring(data[:32])
        start,end,offset,prot=struct.unpack_from("<QQQH",data,32)
        if start >= end:
            continue
        if prot&1: readable+=1
        if prot&4: executable+=1
        row={
            "name":name or "<anonymous>",
            "start":f"0x{start:016x}",
            "end":f"0x{end:016x}",
            "offset":f"0x{offset:x}",
            "prot":int(prot),
        }
        lower=name.lower()
        if ("eboot" in lower or "app0" in lower or "rdr2" in lower or
                lower=="main" or lower.startswith("main ")):
            if len(interesting)<16:
                interesting.append(row)
            if ("eboot" in lower or "app0" in lower) and start>=offset:
                candidate_bases.add(start-offset)
        if (prot&4) and len(sample_exec)<5:
            sample_exec.append(row)
    return {
        "map_count_reported":count,
        "readable_region_count":readable,
        "executable_region_count":executable,
        "named_game_region_matches":interesting,
        "executable_region_samples":sample_exec,
        "candidate_image_bases_unverified":[f"0x{x:016x}" for x in
                                              sorted(candidate_bases)[:12]],
        "any_game_process_bytes_read":False,
        "game_memory_modified":False,
        "image_base_verified":False,
    }


def inspect_maps(ip: str, *, tailscale: bool=False, expected_fw: int=DEFAULT_EXPECTED_FW,
                 timeout: float=8.0)->dict:
    target=validate_local_ip(ip,tailscale=tailscale)
    ident=identify(target,tailscale=tailscale,expected_fw=expected_fw,timeout=timeout)
    if not ident["running_rdr2_1_00_metadata_match"]:
        raise ValueError("RDR2 PS4 1.00 non confirme ; aucune carte memoire lue")
    pid=ident["foreground_process"]["pid"]
    if tailscale:
        verify_tailscale_route(target)
    with socket.create_connection((target,COMMAND_PORT),timeout=timeout) as conn:
        conn.settimeout(timeout)
        request_maps(conn,pid)
        data=read_map_summary(conn)
    return {
        "firmware":ident["firmware"],
        "game_title_id":ident["foreground_process"]["title_id"],
        "game_version_metadata":ident["foreground_process"]["game_version_metadata"],
        "pid":pid,
        "game": "Red Dead Redemption 2 PS4 (title ID confirmed)",
        "map_metadata":data,
        "read_only_command": "CMD_PROC_MAPS (0xBDAA0004)",
        "game_eboot_fingerprint_verified":False,
        "hook_installed":False,
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
        data=inspect_maps(args.ip,tailscale=args.tailscale,
                          expected_fw=args.expected_fw,timeout=args.timeout)
        print(json.dumps(data,ensure_ascii=False,indent=2))
        return 0
    except (OSError,ValueError,ConnectionError,struct.error) as exc:
        print("Inspection interrompue sans modification : "+str(exc),file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
