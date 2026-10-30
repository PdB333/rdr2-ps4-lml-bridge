#!/usr/bin/env python3
"""Read-only LAN/Tailscale ps5debug-NG v1.3.2 probe (PS5 FW 13.40 default).

No game patches, process attach, dumps, authentication, payload injection,
port forwarding, or memory read/write. Only requests public service BRANDING
and FW_VERSION. The optional UDP discovery uses a single documented
ps5debug-NG magic packet to LAN broadcast port 1010.

    python -B tools/ps5debug_ng_probe.py --discover
    python -B tools/ps5debug_ng_probe.py --ip 192.168.1.123
    python -B tools/ps5debug_ng_probe.py --ip YOUR_TAILSCALE_IP --tailscale

Source protocol:
https://github.com/Pharaoh2k/ps5debug-NG/blob/master/PROTOCOL.md
Exact v1.3.2 source: debugger/source/meta.c. Response to BRANDING is
length + payload (NO status word), contrary to an older README snippet.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import re
import socket
import subprocess
import struct
import sys
import time

PACKET_MAGIC = 0xFFAABBCC
CMD_BRANDING = 0xBD000501
CMD_FW_VERSION = 0xBD000500
DISCOVERY_MAGIC = struct.pack("<I", 0xFFFFAAAA)
COMMAND_PORT = 744
DISCOVERY_PORT = 1010
DEFAULT_EXPECTED_FW = 1340  # Owner confirmed PS5 firmware 13.40
MAX_BRAND_LENGTH = 512
TAILSCALE_RANGE = ipaddress.IPv4Network("100.64.0.0/10")
PRIVATE_RANGES = tuple(
    ipaddress.IPv4Network(cidr)
    for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)


def validate_local_ip(value: str, *, tailscale: bool = False) -> str:
    try:
        addr = ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError as exc:
        raise ValueError("Adresse IPv4 incorrecte : entrer l'IP locale de la PS5") from exc
    if tailscale and addr not in TAILSCALE_RANGE:
        raise ValueError("--tailscale exige une adresse Tailscale 100.64.0.0/10")
    if not any(addr in network for network in PRIVATE_RANGES):
        if not (tailscale and addr in TAILSCALE_RANGE):
            raise ValueError(
                "Refus d'une IP non LAN : utiliser --tailscale pour un vrai pair Tailscale"
            )
    return str(addr)


def verify_tailscale_route(target: str) -> None:
    """Explicitly require the Tailscale interface BEFORE sending commands.

    Windows-only: this repository's workstation is Windows and the user has
    confirmed a Tailscale route. A CGNAT/shared 100.x address is not proof
    of a private tailnet; never access it through the ordinary ISP route.
    """
    if sys.platform != "win32":
        raise ValueError("La verification de la route Tailscale exige Windows")
    # Only digits and dots from IPv4Address() reach this PowerShell command.
    command = (
        "$ErrorActionPreference='Stop'; "
        "(Find-NetRoute -RemoteIPAddress '" + target + "' -ErrorAction Stop "
        "| Select-Object -ExpandProperty InterfaceAlias)"
    )
    try:
        check = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, timeout=8, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("Impossible de verifier la route Tailscale Windows") from exc
    interfaces = {line.strip().casefold() for line in check.stdout.splitlines()}
    if check.returncode != 0 or "tailscale" not in interfaces:
        raise ValueError("L'adresse ne passe pas par l'interface Tailscale du PC")


def display_fw(fw: int) -> str:
    return f"{fw // 100}.{fw % 100:02d}"


def parse_expected_fw(value: str) -> int:
    # Firmware 13.40 is distinct from RDR2 PS4 game version 1.00.
    if not re.fullmatch(r"[0-9]{1,2}\.[0-9]{2}", value):
        raise argparse.ArgumentTypeError("Format firmware attendu : XX.YY (ex. 13.40)")
    major, minor = value.split(".")
    fw = int(major) * 100 + int(minor)
    if not 100 <= fw <= 2000:
        raise argparse.ArgumentTypeError("Firmware attendu hors limite")
    return fw


def recv_exact(conn: socket.socket, size: int) -> bytes:
    if not 0 <= size <= MAX_BRAND_LENGTH:
        raise ValueError("Longueur de reponse hors limite de securite")
    chunks = bytearray()
    while len(chunks) < size:
        packet = conn.recv(size - len(chunks))
        if not packet:
            raise ConnectionError("Connexion fermee avant la reponse complete")
        chunks.extend(packet)
    return bytes(chunks)


def request(conn: socket.socket, command: int) -> None:
    if command not in (CMD_BRANDING, CMD_FW_VERSION):
        raise ValueError("Seules les commandes de version non destructives sont autorisees")
    conn.sendall(struct.pack("<III", PACKET_MAGIC, command, 0))


def probe(ip: str, *, timeout: float = 3.0, tailscale: bool = False,
          expected_fw: int = DEFAULT_EXPECTED_FW) -> dict:
    target = validate_local_ip(ip, tailscale=tailscale)
    if tailscale:
        verify_tailscale_route(target)
    if not 0 < timeout <= 10:
        raise ValueError("Delai de connexion incorrect")
    if type(expected_fw) is not int or not 100 <= expected_fw <= 2000:
        raise ValueError("Firmware attendu incorrect")
    with socket.create_connection((target, COMMAND_PORT), timeout=timeout) as conn:
        conn.settimeout(timeout)
        request(conn, CMD_BRANDING)
        length = struct.unpack("<I", recv_exact(conn, 4))[0]
        if not 1 <= length <= MAX_BRAND_LENGTH:
            raise ValueError("Reponse branding inattendue : ce n'est peut-etre pas ps5debug-NG")
        reply = recv_exact(conn, length)
        title_bytes, sep, capability = reply.partition(b"\0")
        branding = title_bytes.decode("utf-8", errors="replace")
        if not branding.startswith("ps5debug-NG by OSR "):
            raise ValueError("Le service TCP 744 n'est pas ps5debug-NG")
        capability_label = (
            capability.decode("ascii", errors="replace") if sep else None
        )

        request(conn, CMD_FW_VERSION)
        firmware = struct.unpack("<H", recv_exact(conn, 2))[0]
        if not 100 <= firmware <= 2000:
            raise ValueError("Version firmware invalide")

    return {
        "ps5_address": target,
        "tcp_port": COMMAND_PORT,
        "service": branding,
        "capability": capability_label,
        "firmware": display_fw(firmware),
        "expected_firmware": display_fw(expected_fw),
        "firmware_matches_expected": firmware == expected_fw,
        "read_only_identity_test": True,
        "debug_attached": False,
        "game_memory_accessed": False,
        "plugin_injected": False,
    }


def discover(*, timeout: float = 2.0) -> list[str]:
    """One LAN broadcast only; replies must echo the documented magic."""
    if not 0 < timeout <= 10:
        raise ValueError("Delai de decouverte incorrect")
    found: set[str] = set()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as conn:
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        conn.bind(("0.0.0.0", 0))
        conn.sendto(DISCOVERY_MAGIC, ("255.255.255.255", DISCOVERY_PORT))
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            conn.settimeout(remaining)
            try:
                data, (source, _source_port) = conn.recvfrom(64)
            except socket.timeout:
                break
            if data == DISCOVERY_MAGIC:
                try:
                    found.add(validate_local_ip(source))
                except ValueError:
                    pass
    return sorted(found)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    args = p.add_mutually_exclusive_group(required=True)
    args.add_argument("--ip", help="Adresse IPv4 LAN de la PS5")
    args.add_argument("--discover", action="store_true",
                      help="Chercher le service ps5debug-NG par une requete UDP LAN")
    p.add_argument("--timeout", type=float, default=2.0)
    p.add_argument("--expected-fw", type=parse_expected_fw,
                   default=DEFAULT_EXPECTED_FW,
                   help="Firmware attendu, par defaut 13.40 (ex. --expected-fw 13.60)")
    p.add_argument("--tailscale", action="store_true",
                   help="Autoriser une adresse 100.64.0.0/10 UNIQUEMENT via route Tailscale Windows")
    config = p.parse_args(argv)
    try:
        if config.discover:
            if config.tailscale:
                raise ValueError("--tailscale s'utilise avec --ip, pas --discover")
            candidates = discover(timeout=config.timeout)
            if not candidates:
                print(
                    "Aucune PS5 ps5debug-NG detectee. Charge d'abord le .elf "
                    "via Y2JB, ou utilise --ip avec l'adresse locale de ta PS5."
                )
                return 2
            if len(candidates) > 1:
                print("Plusieurs serveurs detectes, utiliser --ip pour choisir :")
                for ip in candidates:
                    print("  " + ip)
                return 3
            ip = candidates[0]
        else:
            ip = config.ip
        result = probe(ip, timeout=config.timeout, tailscale=config.tailscale,
                       expected_fw=config.expected_fw)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        if not result["firmware_matches_expected"]:
            print("ATTENTION : firmware detecte different de "
                  + result["expected_firmware"], file=sys.stderr)
            return 4
        return 0
    except (OSError, ValueError, ConnectionError, struct.error) as exc:
        print("Connexion LAN impossible : " + str(exc), file=sys.stderr)
        print("Verifier l'IP, le reseau et le chargement de ps5debug-NG. "
              "N'ouvre pas de port Internet.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
