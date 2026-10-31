#!/usr/bin/env python3
"""Inspect the running PS4 game identity on PS5 FW 13.40, READ ONLY.

Only two game-state protocol commands are allowed:
  CMD_PROC_LIST            0xBDAA0001  (process names and PIDs)
  CMD_CONSOLE_FOREGROUND   0xBDDD0006  (foreground PID, CUSA, app version)

No process attach, debugger attach, memory dump/read/write, scan,
breakpoint, function call, ELF upload, game file access, or kernel write.
The ps5debug-NG v1.3.2 branding and firmware are validated FIRST
via tools/ps5debug_ng_probe.py and the Windows Tailscale route is checked.

Reference: https://github.com/Pharaoh2k/ps5debug-NG/blob/master/PROTOCOL.md
          debugger/source/proc.c and debugger/source/console.c

For the owner's Y2JB + Kstuff Lite console, game version PS4 1.00 is
separate from firmware PS5 13.40; both must be verified independently.
"""
from __future__ import annotations

import argparse
import json
import re
import socket
import struct
import sys
from typing import NamedTuple

from ps5debug_ng_probe import (
    COMMAND_PORT, DEFAULT_EXPECTED_FW, PACKET_MAGIC, parse_expected_fw,
    probe as verify_service, recv_exact, validate_local_ip,
    verify_tailscale_route,
)

# Narrow opt-in allowlist: any other opcode is a programming error.
CMD_PROC_LIST = 0xBDAA0001
CMD_CONSOLE_FOREGROUND = 0xBDDD0006
WIRE_STATUS_OK = 0x80000000  # source CMD_SUCCESS 0x40000000 after bit-swap
PROCESS_RECORD_SIZE = 36  # char name[32], signed int pid
FOREGROUND_SIZE = 140  # u32 pid, titleid[16], contentid[64], name[40], app_ver[16]
MAX_PROCESS_COUNT = 4096  # upstream proc_list_handle() hard limit
TITLEID_PATTERN = re.compile(r"CUSA[0-9]{5}\Z")
# Verified independently via public PS4 release/title databases.
# The console's CUSA08519 is the European RDR2 PS4 Play Disc.
CONFIRMED_RDR2_TITLE_IDS = frozenset({"CUSA08519"})


def is_ps4_base_version(value: str | None) -> bool:
    # PS4 SFO/param.json commonly represents v1.00 as "01.00".
    return bool(value and re.fullmatch(r"0*1\.00", value))



class Process(NamedTuple):
    pid: int
    name: str


def cstring(raw: bytes) -> str:
    # Do not pass untrusted terminal control sequences from a process name.
    return "".join(ch for ch in raw.split(b"\x00", 1)[0].decode(
        "ascii", errors="replace"
    ) if ch.isprintable())[:64]


def send_command(conn: socket.socket, opcode: int) -> None:
    if opcode not in (CMD_PROC_LIST, CMD_CONSOLE_FOREGROUND):
        raise ValueError("Commande interdite : identification en lecture seule seulement")
    conn.sendall(struct.pack("<III", PACKET_MAGIC, opcode, 0))


def check_response_ok(conn: socket.socket) -> None:
    actual = struct.unpack("<I", recv_exact(conn, 4))[0]
    if actual != WIRE_STATUS_OK:
        raise ValueError(f"Erreur ps5debug-NG (status {actual:#010x})")


def get_processes(conn: socket.socket) -> list[Process]:
    send_command(conn, CMD_PROC_LIST)
    check_response_ok(conn)
    count = struct.unpack("<I", recv_exact(conn, 4))[0]
    if count > MAX_PROCESS_COUNT:
        raise ValueError("Taille inattendue de la liste de processus")
    matches: list[Process] = []
    for _ in range(count):
        record = recv_exact(conn, PROCESS_RECORD_SIZE)
        name = cstring(record[:32])
        pid = struct.unpack_from("<i", record, 32)[0]
        if pid > 0 and name.lower().startswith("eboot.bin"):
            matches.append(Process(pid, name))
    return matches


def get_foreground(conn: socket.socket) -> dict:
    send_command(conn, CMD_CONSOLE_FOREGROUND)
    check_response_ok(conn)
    data = recv_exact(conn, FOREGROUND_SIZE)
    pid = struct.unpack_from("<I", data, 0)[0]
    title_id = cstring(data[4:20])
    # contentid[64] deliberately NOT collected or displayed.
    name = cstring(data[84:124])
    version = cstring(data[124:140])
    title_id_valid = bool(TITLEID_PATTERN.fullmatch(title_id))
    if pid == 0:
        return {
            "process_found": False,
            "pid": None,
            "title_id": None,
            "process_name": None,
            "game_version_metadata": None,
            "title_id_is_cusa": False,
        }
    return {
        "process_found": True,
        "pid": pid,
        "title_id": title_id if title_id_valid else None,
        "process_name": name,
        "game_version_metadata": version or None,
        "title_id_is_cusa": title_id_valid,
    }


def identify(ip: str, *, tailscale: bool = False,
             expected_fw: int = DEFAULT_EXPECTED_FW,
             timeout: float = 3.0) -> dict:
    # A CGNAT / 100.x IP is never contacted without explicit --tailscale
    # and a verified Windows route; verify_service enforces this first.
    target = validate_local_ip(ip, tailscale=tailscale)
    status = verify_service(target, tailscale=tailscale,
                            expected_fw=expected_fw, timeout=timeout)
    if not status["firmware_matches_expected"]:
        raise ValueError("Firmware non conforme ; aucun processus interroge")
    if not status["service"].startswith("ps5debug-NG by OSR "):
        raise ValueError("Identite du serveur ps5debug-NG non conforme")
    if tailscale:
        verify_tailscale_route(target)  # recheck before second connection
    with socket.create_connection((target, COMMAND_PORT), timeout=timeout) as conn:
        conn.settimeout(timeout)
        eboots = get_processes(conn)
        if not eboots:
            # Do NOT send foreground query when no eboot process is visible.
            foreground = {
                "process_found": False,
                "pid": None,
                "title_id": None,
                "process_name": None,
                "game_version_metadata": None,
                "title_id_is_cusa": False,
            }
        else:
            foreground = get_foreground(conn)
    same_pid = bool(foreground["process_found"] and
                    any(proc.pid == foreground["pid"] for proc in eboots))
    title_is_rdr2 = (same_pid and
                     foreground["title_id"] in CONFIRMED_RDR2_TITLE_IDS)
    is_base_version = bool(
        same_pid and foreground["title_id_is_cusa"] and
        is_ps4_base_version(foreground["game_version_metadata"])
    )
    return {
        "firmware": status["firmware"],
        "debugger": status["service"],
        "console_connection_verified": True,
        "eboot_process_count": len(eboots),
        "foreground_process": foreground,
        "foreground_pid_in_process_list": same_pid,
        "ps4_app_version_1_00_reported": is_base_version,
        "rdr2_title_independently_verified": title_is_rdr2,
        "running_rdr2_1_00_metadata_match": bool(title_is_rdr2 and is_base_version),
        "running_eboot_fingerprint_verified": False,
        "no_memory_reads_or_game_modifications": True,
        "no_process_or_debugger_attach": True,
        "game_hook_installed": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ip", required=True,
                        help="Adresse IP de la PS5, UNIQUEMENT sur le reseau du proprietaire")
    parser.add_argument("--tailscale", action="store_true",
                        help="Autoriser 100.64/10 seulement si route Windows via Tailscale")
    parser.add_argument("--expected-fw", type=parse_expected_fw,
                        default=DEFAULT_EXPECTED_FW,
                        help="Firmware PS5 attendu, 13.40 par defaut")
    parser.add_argument("--timeout", type=float, default=3.0)
    args = parser.parse_args(argv)
    try:
        result = identify(args.ip, tailscale=args.tailscale,
                          expected_fw=args.expected_fw, timeout=args.timeout)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result["foreground_pid_in_process_list"]:
            print("RDR2 n'est pas identifie avec certitude comme application "
                  "au premier plan ; aucun hook ne sera tente.", file=sys.stderr)
            return 3
        if not result["running_rdr2_1_00_metadata_match"]:
            print("RDR2 PS4 1.00 non confirme par PID/CUSA et metadonnees. "
                  "Le SHA EBOOT du jeu charge reste non verifie.",
                  file=sys.stderr)
            return 4
        return 0
    except (ValueError, OSError, ConnectionError, struct.error) as exc:
        print("Sonde interrompue sans modification du jeu : "+str(exc),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
