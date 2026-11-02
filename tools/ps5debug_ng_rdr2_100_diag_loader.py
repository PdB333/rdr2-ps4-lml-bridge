#!/usr/bin/env python3
"""Diagnostic LECTURE SEULE : pourquoi resolve_loader ne trouve pas l'ELF.

CONTEXTE
  `ps5debug_ng_rdr2_100_resolve_loader.py` echoue a l'etape parse_exports avec
  « Pas d'en-tete ELF a la base du module » : les 64 octets lus a la base
  calculee (plus petit `start` des regions partageant le nom du module ancre)
  ne commencent pas par `\\x7fELF`. Sur Orbis, un SPRX est mappe segment par
  segment et l'en-tete ELF n'est PAS forcement a la region la plus basse du
  module (souvent la region r-x de code), ou bien les segments ne partagent
  pas exactement le meme nom dans CMD_PROC_MAPS.

  Ce script NE DEVINE RIEN et NE CORRIGE RIEN. Il observe, pour que la
  correction de resolve_loader s'appuie sur la disposition memoire REELLE :

    1. Lit le slot GOT ancre (sceKernelOpen @ RVA 0x0678CDA0) -> pointeur
       resolu dans libkernel (meme recette que resolve_loader).
    2. CMD_PROC_MAPS -> region contenant ce pointeur, et base de module
       calculee par module_for() (celle que resolve_loader utilise).
    3. Dump des 64 premiers octets a cette base (hex + test du magic ELF).
    4. Enumere TOUTES les regions partageant le nom du module (start/end/prot)
       ET les regions voisines (meme si anonymes/autre nom) encadrant le
       pointeur, et teste le magic ELF au debut de chacune -> localise ou
       l'en-tete ELF est reellement mappee, si elle l'est.
    5. Rapport JSON : la cause (en-tete a une autre region, module scinde en
       noms distincts, en-tete non mappee du tout, ...) et la region candidate
       a passer comme vraie base a parse_exports.

SECURITE (regles du proprietaire) :
- LECTURE SEULE stricte : uniquement CMD_PROC_READ (0xBDAA0002) et
  CMD_PROC_MAPS (0xBDAA0004), via les helpers deja audites de resolve_loader.
  Aucun write/alloc/call/attach/patch/dump/ecriture fichier.
- Barriere de profil `check_live` : refuse un process dont la signature
  fiPackfile8 ne correspond pas a l'EBOOT 1.00.
- Toutes les lectures sont bornees et toute adresse est controlee avant envoi.
- Ne resout ni ne propose aucune `--loader-addr` : il explique seulement
  pourquoi la base actuelle echoue et quelle region porte l'en-tete ELF.
"""
from __future__ import annotations
import argparse
import json
import socket
import struct
import sys

from ps5debug_ng_probe import (
    COMMAND_PORT, DEFAULT_EXPECTED_FW, parse_expected_fw,
    validate_local_ip, verify_tailscale_route,
)
from inspect_rdr2_imports import nid
import ps5debug_ng_rdr2_100_live_profile as live
from ps5debug_ng_rdr2_100_resolve_loader import (
    ANCHOR_SYMBOL, ANCHOR_GOT_RVA, TARGET_SYMBOL,
    read_mem, read_maps, module_for, _addr_ok,
)

# How many bytes to sniff at the head of each region when hunting the ELF magic.
SNIFF_LEN = 64
# How many regions below/above the containing region to inspect for the header.
NEIGHBOUR_SPAN = 4


def _sniff(conn, pid, addr, length=SNIFF_LEN):
    """Best-effort bounded read; returns (bytes|None, error-string|None)."""
    try:
        return read_mem(conn, pid, addr, length), None
    except (ValueError, ConnectionError, OSError, struct.error) as exc:
        return None, str(exc)


def _region_row(conn, pid, region):
    name, start, end, prot = region
    head, err = _sniff(conn, pid, start)
    row = {
        "name": name or "<anonymous>",
        "start": f"0x{start:X}",
        "end": f"0x{end:X}",
        "size": f"0x{end - start:X}",
        "prot": prot,
        "prot_rwx": "{}{}{}".format(
            "r" if prot & 1 else "-",
            "w" if prot & 2 else "-",
            "x" if prot & 4 else "-"),
    }
    if head is not None:
        row["head16_hex"] = head[:16].hex()
        row["elf_magic_at_start"] = head[:4] == b"\x7fELF"
    else:
        row["read_error"] = err
    return row


def diagnose(ip: str, *, tailscale: bool = False,
             expected_fw: int = DEFAULT_EXPECTED_FW, timeout: float = 8.0,
             anchor_rva: int = ANCHOR_GOT_RVA) -> dict:
    report = live.check_live(ip, tailscale=tailscale, expected_fw=expected_fw,
                             timeout=timeout)
    if not report["profile"]["live_rage_packfile8_profile_matches_eboot_100"]:
        raise ValueError("Profil fiPackfile8 non conforme : diagnostic refuse")
    pid = report["pid"]
    base = int(report["image_base"], 16)

    out = {
        "reads_only": True,
        "command_allowlist": ["CMD_PROC_READ 0xBDAA0002",
                              "CMD_PROC_MAPS 0xBDAA0004"],
        "image_base": report["image_base"],
        "pid": pid,
        "anchor": {"symbol": ANCHOR_SYMBOL, "nid": nid(ANCHOR_SYMBOL),
                   "got_rva": f"0x{anchor_rva:08X}"},
        "target": {"symbol": TARGET_SYMBOL, "nid": nid(TARGET_SYMBOL)},
    }

    tgt = validate_local_ip(ip, tailscale=tailscale)
    if tailscale:
        verify_tailscale_route(tgt)
    with socket.create_connection((tgt, COMMAND_PORT), timeout=timeout) as c:
        c.settimeout(timeout)
        ptr = struct.unpack("<Q", read_mem(c, pid, base + anchor_rva, 8))[0]
        out["anchor"]["resolved_value"] = f"0x{ptr:X}"
        if not _addr_ok(ptr):
            out["status"] = "anchor-not-a-pointer"
            return out

        regions = read_maps(c, pid)
        regions.sort(key=lambda r: r[1])
        hit = next((r for r in regions
                    if r[1] <= ptr < r[2]), None)
        if hit is None:
            out["status"] = "anchor-outside-any-region"
            return out
        hit_idx = regions.index(hit)
        out["containing_region"] = _region_row(c, pid, hit)

        mod = module_for(regions, ptr)
        out["module_for_result"] = {
            "name": mod["name"],
            "computed_base": f"0x{mod['base']:X}",
            "anonymous": mod["anonymous"],
            "region_count_same_name": len(mod["regions"]),
        }
        # (3) The exact read resolve_loader does and fails on.
        base_head, base_err = _sniff(c, pid, mod["base"])
        if base_head is not None:
            out["base_probe"] = {
                "addr": f"0x{mod['base']:X}",
                "head16_hex": base_head[:16].hex(),
                "elf_magic_at_start": base_head[:4] == b"\x7fELF",
            }
        else:
            out["base_probe"] = {"addr": f"0x{mod['base']:X}",
                                 "read_error": base_err}

        # (4a) Every region that shares the module name, head-sniffed.
        same_name = [_region_row(c, pid, r) for r in mod["regions"]]
        out["same_name_regions"] = same_name

        # (4b) Neighbours around the containing region, regardless of name:
        # the ELF header is often at a lower-addressed sibling segment whose
        # map name differs (or is anonymous).
        lo = max(0, hit_idx - NEIGHBOUR_SPAN)
        hi = min(len(regions), hit_idx + NEIGHBOUR_SPAN + 1)
        out["neighbour_regions"] = [_region_row(c, pid, r)
                                    for r in regions[lo:hi]]

        # (5) Where, if anywhere, does the ELF header actually sit?
        elf_rows = [r for r in (same_name + out["neighbour_regions"])
                    if r.get("elf_magic_at_start")]
        # Dedup by start address.
        seen = set()
        elf_hits = []
        for r in elf_rows:
            if r["start"] not in seen:
                seen.add(r["start"])
                elf_hits.append({"name": r["name"], "start": r["start"],
                                 "prot_rwx": r["prot_rwx"]})
        out["elf_header_candidates"] = elf_hits

    # Diagnosis.
    if out["base_probe"].get("elf_magic_at_start"):
        out["status"] = "elf-at-base-unexpected"
        out["diagnosis"] = ("L'en-tete ELF EST a la base calculee : l'echec de "
                            "resolve_loader vient d'ailleurs (relire son "
                            "parse_exports). ")
    elif elf_hits:
        c0 = elf_hits[0]
        out["status"] = "elf-header-at-other-region"
        out["diagnosis"] = (
            "En-tete ELF absente de la base calculee mais presente a "
            f"{c0['start']} ({c0['name']}, {c0['prot_rwx']}). module_for() "
            "retient la plus petite region de MEME nom ; la region portant "
            "l'en-tete a un nom different ou est anonyme. Correctif : passer "
            "cette region a parse_exports comme vraie base du module.")
    else:
        out["status"] = "elf-header-not-mapped"
        out["diagnosis"] = (
            "Aucune region voisine ne commence par \\x7fELF : l'en-tete ELF "
            "n'est probablement pas mappee en RAM (chargeur Orbis segment par "
            "segment). parse_exports ne peut pas partir de l'en-tete ; il faut "
            "une autre source des program headers (ex. CMD_PROC_ELF_RPC / info "
            "module cote plugin), cf. PRX_LOADING_STUDY_100.md.")
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ip", required=True)
    p.add_argument("--tailscale", action="store_true")
    p.add_argument("--expected-fw", type=parse_expected_fw,
                   default=DEFAULT_EXPECTED_FW)
    p.add_argument("--timeout", type=float, default=8.0)
    args = p.parse_args(argv)
    try:
        result = diagnose(args.ip, tailscale=args.tailscale,
                          expected_fw=args.expected_fw, timeout=args.timeout)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, ConnectionError, OSError, struct.error, KeyError) as exc:
        print("Diagnostic interrompu sans modification : " + str(exc),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
