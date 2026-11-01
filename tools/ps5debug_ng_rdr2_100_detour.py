#!/usr/bin/env python3
"""Live fiPackfile8 vtable-slot detour instrument for RDR2 PS4 1.00.

Companion to the offline planner runtime/rdr2_100_detour.{h,c}: it drives the
SAME pointer-swap on the running game via ps5debug-NG, under the same
fail-closed contract. The detour swaps two class-vtable SLOT POINTERS
(Open @slot 2, Read @slot 13) for caller-supplied trampolines, keeping the
originals so the hook body can read through. It is a pointer swap, NOT an
inline code patch and NOT a guessed address.

SAFETY (matches the owner's rules):
- DRY-RUN BY DEFAULT. Nothing is written unless --arm (install) or --revert
  (restore) is passed. Without them the exact 8-byte writes are only printed.
- Gated on ps5debug_ng_rdr2_100_live_profile.check_live: it refuses to touch a
  process whose fiPackfile8 signature does not match the 1.00 EBOOT. The two
  target slots are confirmed live by that same read-only profile
  (five_known_method_slots_match covers slots 2 and 13), so no new address is
  read outside the approved profile plan.
- NEVER guesses an address. --arm requires BOTH --trampoline-open and
  --trampoline-read (absolute runtime addresses from an already-loaded module);
  the tool will not fabricate a trampoline. The write target (base + slot rva)
  must land inside the RELRO image region and NEVER inside the r-x text.
- Writes use the VERIFIED CMD_PROC_WRITE layout (same as the inject tool).

RELRO note: the vtable lives in the r-- RELRO region. ps5debug-NG's
CMD_PROC_WRITE goes through the kernel debug write primitive, which patches
pages regardless of userland protection (this is how ps4debug/ps5debug patch
read-only code). If a future console rejects the write, a VERIFIED page-protect
step must be added here -- no protect opcode is guessed in this repo today.

Nothing here claims a working modloader: arming the detour only matters once a
PRX provides the two trampolines, which is a separate step.
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
from ps5debug_ng_rdr2_identity import check_response_ok
import ps5debug_ng_rdr2_100_live_profile as live

CMD_PROC_WRITE = 0xBDAA0003
ADDR_CEILING = 2 ** 47

# Vtable slot indices (verified by RTTI in inspect_rdr2_eboot and live).
SLOT_OPEN = 2
SLOT_READ = 13
# Handler RVAs currently occupying those slots (from live_profile.METHODS).
OPEN_RVA = live.METHODS[SLOT_OPEN]   # 0x0452A480
READ_RVA = live.METHODS[SLOT_READ]   # 0x0452B9D0


def _header(cmd: int, body: bytes) -> bytes:
    return struct.pack("<III", PACKET_MAGIC, cmd, len(body)) + body


def proc_write(conn: socket.socket, pid: int, address: int, data: bytes) -> None:
    """Verified CMD_PROC_WRITE: (pid u32, address u64, len u32) then data."""
    conn.sendall(_header(CMD_PROC_WRITE, struct.pack("<IQI", pid, address,
                                                     len(data))))
    check_response_ok(conn)          # pre-data acknowledgement
    conn.sendall(data)
    check_response_ok(conn)          # post-write confirmation


def _in_range(value: int) -> bool:
    return 0 < value < ADDR_CEILING


def relro_region(regions, slot_addr: int):
    """Return the region holding slot_addr, refusing r-x text and gaps.

    regions is a list of (start, end, prot) as reported by check_live. The
    slot must sit in a readable, NON-executable region (RELRO r-- = prot 1).
    """
    for start, end, prot in regions:
        if start <= slot_addr and slot_addr + 8 <= end:
            if not prot & 1:
                raise ValueError("Slot vtable dans une region illisible")
            if prot & 4:
                raise ValueError("Refus d'ecrire dans le segment r-x (.text)")
            return start, end, prot
    raise ValueError("Slot vtable hors de l'image principale")


def build_detour_plan(report: dict, trampoline_open: int, trampoline_read: int,
                      *, require_trampolines: bool) -> dict:
    """Mirror LmlDetourPlan from the C core, from a validated live report.

    Refuses unless the live profile matches the 1.00 EBOOT. When
    require_trampolines is True (--arm), both trampolines must be in range;
    otherwise 0 is allowed for a dry-run description.
    """
    prof = report["profile"]
    if not prof["live_rage_packfile8_profile_matches_eboot_100"]:
        raise ValueError("Profil fiPackfile8 non conforme : detour refuse")
    if not prof["five_known_method_slots_match"]:
        raise ValueError("Slots 2/13 non confirmes live : detour refuse")

    bias = int(report["image_base"], 16)
    if not _in_range(bias):
        raise ValueError("Base de chargement hors plage")
    regions = [(int(r["start"], 16), int(r["end"], 16), r["prot"])
               for r in report["image_regions"]]

    for name, tramp in (("open", trampoline_open), ("read", trampoline_read)):
        if require_trampolines and not _in_range(tramp):
            raise ValueError(
                f"--trampoline-{name} hors plage ou absent (aucune valeur "
                "devinee ; fournir l'adresse runtime du module charge)")

    slots = {}
    for key, idx, rva, tramp in (
        ("open_slot", SLOT_OPEN, OPEN_RVA, trampoline_open),
        ("read_slot", SLOT_READ, READ_RVA, trampoline_read),
    ):
        slot_rva = live.VTABLE + idx * 8
        slot_addr = bias + slot_rva
        relro_region(regions, slot_addr)          # refuse r-x / out of image
        slots[key] = {
            "slot_index": idx,
            "slot_addr": slot_addr,
            "original_value": bias + rva,
            "trampoline": tramp,
        }
    return {
        "verified": True,
        "pid": report["pid"],
        "image_load_bias": bias,
        **slots,
    }


def _writes(plan: dict, *, restore: bool) -> list[tuple[int, int]]:
    """Return [(slot_addr, value)] to send. restore=True writes originals."""
    field = "original_value" if restore else "trampoline"
    return [(plan["open_slot"]["slot_addr"], plan["open_slot"][field]),
            (plan["read_slot"]["slot_addr"], plan["read_slot"][field])]


def _render(plan: dict, *, arm: bool, revert: bool) -> dict:
    def slot(s):
        return {"slot_index": s["slot_index"],
                "slot_addr": f"0x{s['slot_addr']:X}",
                "original_value": f"0x{s['original_value']:X}",
                "trampoline": f"0x{s['trampoline']:X}"}
    return {
        "pid": plan["pid"],
        "image_base": f"0x{plan['image_load_bias']:X}",
        "open_slot": slot(plan["open_slot"]),
        "read_slot": slot(plan["read_slot"]),
        "action": "revert" if revert else ("apply" if arm else "dry-run"),
    }


def run(ip: str, trampoline_open: int, trampoline_read: int, *,
        arm: bool = False, revert: bool = False, tailscale: bool = False,
        expected_fw: int = DEFAULT_EXPECTED_FW, timeout: float = 8.0) -> dict:
    if arm and revert:
        raise ValueError("--arm et --revert sont exclusifs")
    report = live.check_live(ip, tailscale=tailscale, expected_fw=expected_fw,
                             timeout=timeout)
    # --arm needs trampolines; --revert and dry-run do not.
    plan = build_detour_plan(report, trampoline_open, trampoline_read,
                             require_trampolines=arm)
    result = {"profile_is_read_only": report["profile_is_read_only"],
              "plan": _render(plan, arm=arm, revert=revert),
              "game_memory_modified": False}
    if not (arm or revert):
        result["note"] = ("DRY-RUN : aucun octet ecrit. --arm installe le "
                          "detour (exige les 2 trampolines), --revert restaure.")
        return result

    target = validate_local_ip(ip, tailscale=tailscale)
    if tailscale:
        verify_tailscale_route(target)
    pid = plan["pid"]
    writes = _writes(plan, restore=revert)
    with socket.create_connection((target, COMMAND_PORT), timeout=timeout) as c:
        c.settimeout(timeout)
        for slot_addr, value in writes:
            proc_write(c, pid, slot_addr, struct.pack("<Q", value))
            result["game_memory_modified"] = True
    result["note"] = ("Detour restaure (slots originaux)." if revert
                      else "Detour arme (slots Open/Read remplaces).")
    return result


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ip", required=True)
    p.add_argument("--trampoline-open", type=lambda v: int(v, 0), default=0,
                   help="Adresse runtime du hook Open (module charge)")
    p.add_argument("--trampoline-read", type=lambda v: int(v, 0), default=0,
                   help="Adresse runtime du hook Read (module charge)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--arm", action="store_true",
                   help="Installe le detour (sinon dry-run)")
    g.add_argument("--revert", action="store_true",
                   help="Restaure les slots originaux")
    p.add_argument("--tailscale", action="store_true")
    p.add_argument("--expected-fw", type=parse_expected_fw,
                   default=DEFAULT_EXPECTED_FW)
    p.add_argument("--timeout", type=float, default=8.0)
    args = p.parse_args(argv)
    try:
        result = run(args.ip, args.trampoline_open, args.trampoline_read,
                     arm=args.arm, revert=args.revert, tailscale=args.tailscale,
                     expected_fw=args.expected_fw, timeout=args.timeout)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, ConnectionError, OSError, struct.error, KeyError) as exc:
        print("Detour interrompu sans modification : " + str(exc),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
