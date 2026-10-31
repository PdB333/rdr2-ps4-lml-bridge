#!/usr/bin/env python3
"""Real injection instrument for RDR2 PS4 1.00 via ps5debug-NG v1.3.2.

This is the first WRITE-capable tool in the repo. It performs the documented
load sequence ALLOC -> WRITE(path) -> CALL(loader, path) to ask the game
process to load+start a module (our passive RAGE PRX), then reads back the
returned handle.

SAFETY (matches the owner's rules):
- DRY-RUN BY DEFAULT. Nothing is written or called unless --arm is passed.
  Without --arm the tool prints the exact packets it WOULD send and exits.
- Gated on ps5debug_ng_rdr2_100_live_profile.check_live: it refuses to touch
  a process whose fiPackfile8 signature does not match the 1.00 EBOOT.
- NEVER guesses an address. The loader entrypoint must be supplied with
  --loader-addr (a runtime address previously resolved read-only); the tool
  will not fabricate one.
- Wire formats are the VERIFIED ps5debug-NG layouts (PROTOCOL.md + proc.c),
  not guessed.

KNOWN UNKNOWN (to be settled by the FIRST live run, not here):
  CMD_PROC_INTALL is a no-op in ps5debug-NG (rpcstub=0), so whether
  CMD_PROC_CALL works with rpcstub=0 depends on the kernel SYS_PROC_CALL.
  If CALL proves non-functional, the fallback is CMD_PROC_ELF_RPC (0xBDAA0010,
  loads+runs a self-contained ELF) -- documented in PRX_LOADING_STUDY_100.md.

Nothing here claims a working modloader: loading a PRX is not a visible mod.
"""
from __future__ import annotations
import argparse
import json
import socket
import struct
import sys

from ps5debug_ng_probe import (
    PACKET_MAGIC, COMMAND_PORT, DEFAULT_EXPECTED_FW, parse_expected_fw,
    validate_local_ip, verify_tailscale_route,
)
import ps5debug_ng_rdr2_100_live_profile as live

CMD_PROC_ALLOC = 0xBDAA000B
CMD_PROC_FREE = 0xBDAA000C
CMD_PROC_WRITE = 0xBDAA0003
CMD_PROC_CALL = 0xBDAA0006
WIRE_STATUS_OK = 0x80000000
WIRE_STATUS_ERR = 0xF0000001

MAX_PAYLOAD = 0x1000        # we only ever write a short path string
VALID_PATH_PREFIXES = ("/data/", "/mnt/", "/system_ex/", "/app0/")


def _header(cmd: int, body: bytes) -> bytes:
    return struct.pack("<III", PACKET_MAGIC, cmd, len(body)) + body


def _recv_exact(conn: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        packet = conn.recv(size - len(chunks))
        if not packet:
            raise ConnectionError("Connexion fermee avant la reponse complete")
        chunks.extend(packet)
    return bytes(chunks)


def _status(conn: socket.socket) -> int:
    status = struct.unpack("<I", _recv_exact(conn, 4))[0]
    if status != WIRE_STATUS_OK:
        raise ConnectionError(f"ps5debug a renvoye une erreur 0x{status:08X}")
    return status


def proc_alloc(conn: socket.socket, pid: int, length: int) -> int:
    conn.sendall(_header(CMD_PROC_ALLOC, struct.pack("<II", pid, length)))
    _status(conn)
    return struct.unpack("<Q", _recv_exact(conn, 8))[0]


def proc_free(conn: socket.socket, pid: int, address: int, length: int) -> None:
    conn.sendall(_header(CMD_PROC_FREE,
                         struct.pack("<IQI", pid, address, length)))
    _status(conn)


def proc_write(conn: socket.socket, pid: int, address: int, data: bytes) -> None:
    conn.sendall(_header(CMD_PROC_WRITE,
                         struct.pack("<IQI", pid, address, len(data))))
    _status(conn)          # pre-data acknowledgement
    conn.sendall(data)
    _status(conn)          # post-write confirmation


def proc_call(conn: socket.socket, pid: int, rip: int, args=(),
              rpcstub: int = 0) -> int:
    regs = list(args) + [0] * (6 - len(args))
    if len(args) > 6:
        raise ValueError("CMD_PROC_CALL accepte au plus 6 arguments")
    body = struct.pack("<IQQQQQQQQ", pid, rpcstub, rip, *regs)
    conn.sendall(_header(CMD_PROC_CALL, body))
    _status(conn)
    _pid, rax = struct.unpack("<IQ", _recv_exact(conn, 12))
    return rax


def build_plan(pid: int, base: int, module_path: str, loader_addr: int) -> dict:
    """Describe (do not execute) the ALLOC/WRITE/CALL load sequence."""
    if not module_path.startswith(VALID_PATH_PREFIXES):
        raise ValueError(
            "Chemin module refuse : attendu un chemin console absolu "
            f"{VALID_PATH_PREFIXES}")
    blob = module_path.encode() + b"\0"
    if len(blob) > MAX_PAYLOAD:
        raise ValueError("Chemin trop long")
    if not 0 < loader_addr < 2 ** 47:
        raise ValueError("--loader-addr hors plage ou absent (aucune valeur "
                         "devinee)")
    return {
        "pid": pid,
        "image_base": f"0x{base:X}",
        "loader_addr": f"0x{loader_addr:X}",
        "module_path": module_path,
        "steps": [
            {"op": "ALLOC", "length": len(blob)},
            {"op": "WRITE", "bytes": len(blob), "note": "chemin + NUL"},
            {"op": "CALL", "rip": f"0x{loader_addr:X}",
             "rdi": "<addr alloue>", "rsi": 0,
             "note": "handle attendu dans rax (>=0)"},
        ],
    }


def inject(ip: str, module_path: str, loader_addr: int, *, arm: bool = False,
           tailscale: bool = False, expected_fw: int = DEFAULT_EXPECTED_FW,
           timeout: float = 8.0) -> dict:
    report = live.check_live(ip, tailscale=tailscale, expected_fw=expected_fw,
                             timeout=timeout)
    if not report["profile"]["live_rage_packfile8_profile_matches_eboot_100"]:
        raise ValueError("Profil fiPackfile8 non conforme : injection refusee")
    pid = report["pid"]
    base = int(report["image_base"], 16)
    plan = build_plan(pid, base, module_path, loader_addr)
    result = {"plan": plan, "armed": arm, "game_memory_modified": False}
    if not arm:
        result["note"] = ("DRY-RUN : aucune ecriture envoyee. Relancer avec "
                          "--arm pour executer (jeu lance, sauvegarde faite).")
        return result
    target = validate_local_ip(ip, tailscale=tailscale)
    if tailscale:
        verify_tailscale_route(target)
    blob = module_path.encode() + b"\0"
    with socket.create_connection((target, COMMAND_PORT), timeout=timeout) as c:
        c.settimeout(timeout)
        addr = proc_alloc(c, pid, len(blob))
        try:
            proc_write(c, pid, addr, blob)
            result["game_memory_modified"] = True
            rax = proc_call(c, pid, loader_addr, args=(addr, 0))
        finally:
            try:
                proc_free(c, pid, addr, len(blob))
            except (ConnectionError, OSError, struct.error):
                pass
    signed = rax - 2 ** 64 if rax >= 2 ** 63 else rax  # errno is negative
    result.update({"alloc_addr": f"0x{addr:X}", "rax": f"0x{rax:X}",
                   "module_handle": signed,
                   "loaded": 0 <= signed < 0x7FFFFFFF})
    return result


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ip", required=True)
    p.add_argument("--module-path", required=True,
                   help="Chemin du PRX SUR la console, ex. /data/.../lml.prx")
    p.add_argument("--loader-addr", type=lambda v: int(v, 0), default=0,
                   help="Adresse runtime resolue de la primitive de chargement")
    p.add_argument("--arm", action="store_true",
                   help="Execute reellement ALLOC/WRITE/CALL (sinon dry-run)")
    p.add_argument("--tailscale", action="store_true")
    p.add_argument("--expected-fw", type=parse_expected_fw,
                   default=DEFAULT_EXPECTED_FW)
    p.add_argument("--timeout", type=float, default=8.0)
    args = p.parse_args(argv)
    try:
        result = inject(args.ip, args.module_path, args.loader_addr,
                        arm=args.arm, tailscale=args.tailscale,
                        expected_fw=args.expected_fw, timeout=args.timeout)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if (not args.arm or result.get("loaded")) else 4
    except (ValueError, ConnectionError, OSError, struct.error, KeyError) as exc:
        print("Injection interrompue : " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
