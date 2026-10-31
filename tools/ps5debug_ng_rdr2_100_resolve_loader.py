#!/usr/bin/env python3
"""Read-only resolver for the RDR2 PS4 1.00 module-loader address.

PURPOSE
  The injection instrument (ps5debug_ng_rdr2_100_inject.py) refuses to guess
  --loader-addr. This tool resolves that runtime address WITHOUT writing a
  single byte to the game, following the recipe proved offline in
  orbis/PRX_LOADING_STUDY_100.md:

    1. The EBOOT does NOT import sceKernelLoadStartModule, but it DOES import
       sceKernelOpen (libkernel) at GOT RVA 0x0678CDA0. Under BIND_NOW (the
       GOT sits in a PT_SCE_RELRO r-- segment) that slot holds, at runtime,
       the resolved absolute address of sceKernelOpen inside libkernel.
    2. Read 8 bytes at image_base + 0x0678CDA0 -> a pointer into libkernel's
       r-x region.
    3. CMD_PROC_MAPS -> find the module whose region contains that pointer
       (expected: libkernel.sprx) and its base.
    4. Parse that module's Orbis export table IN RAM (ELF header -> program
       headers -> PT_DYNAMIC / PT_SCE_DYNLIBDATA -> SYMTAB/STRTAB) and look up
       the target NID wzvqT4UqKX8 (sceKernelLoadStartModule).
    5. loader_addr = module_base + st_value -> feeds inject.py --loader-addr.

SAFETY (matches the owner's rules):
- READ-ONLY. Issues ONLY CMD_PROC_READ (0xBDAA0002) and CMD_PROC_MAPS
  (0xBDAA0004). No write, alloc, call, attach, patch, dump or file write.
- Gated on ps5debug_ng_rdr2_100_live_profile.check_live: refuses a process
  whose fiPackfile8 signature does not match the 1.00 EBOOT.
- Guesses nothing. If the anchor slot is still unresolved (points inside the
  game image), or the target NID is absent from the anchor module, it reports
  the situation and returns no address rather than inventing one.
- All reads are bounded and every address is range-checked before a request.

Nothing here loads or runs anything: it only tells you which address to pass
to the (separately armed) injection instrument.
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
from inspect_rdr2_imports import nid, DT
import ps5debug_ng_rdr2_100_live_profile as live

CMD_PROC_READ = 0xBDAA0002
CMD_PROC_MAPS = 0xBDAA0004

# The anchor import whose resolved GOT slot points into libkernel.
ANCHOR_SYMBOL = "sceKernelOpen"
ANCHOR_GOT_RVA = 0x0678CDA0          # verified by inspect_rdr2_imports (1.00)
TARGET_SYMBOL = "sceKernelLoadStartModule"  # nid wzvqT4UqKX8

MAP_ENTRY_SIZE = 58
MAX_MAP_COUNT = 16384
READ_CHUNK = 0x8000                  # per CMD_PROC_READ request
MAX_TABLE = 8 * 1024 * 1024          # cap for symtab / strtab reads
MAX_PHNUM = 128
MAX_DYNAMIC = 0x10000
PT_LOAD = 1
PT_DYNAMIC = 2
PT_SCE_DYNLIBDATA = 0x61000000


def _addr_ok(addr: int) -> bool:
    return isinstance(addr, int) and 0 < addr < 2 ** 47


def _recv_exact(conn: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        packet = conn.recv(size - len(chunks))
        if not packet:
            raise ConnectionError("Connexion fermee avant la reponse complete")
        chunks.extend(packet)
    return bytes(chunks)


def read_mem(conn: socket.socket, pid: int, addr: int, length: int) -> bytes:
    """Read `length` bytes of process memory via bounded CMD_PROC_READ calls."""
    if not _addr_ok(addr) or not _addr_ok(addr + max(length - 1, 0)):
        raise ValueError(f"Adresse de lecture hors plage : 0x{addr:X}")
    if length <= 0 or length > MAX_TABLE:
        raise ValueError(f"Taille de lecture refusee : {length}")
    out = bytearray()
    while len(out) < length:
        chunk = min(READ_CHUNK, length - len(out))
        body = struct.pack("<IQI", pid, addr + len(out), chunk)
        conn.sendall(struct.pack("<III", PACKET_MAGIC, CMD_PROC_READ,
                                 len(body)) + body)
        check_response_ok(conn)
        out.extend(_recv_exact(conn, chunk))
    return bytes(out)


def read_maps(conn: socket.socket, pid: int) -> list[tuple[str, int, int, int]]:
    """Return every (name, start, end, prot) VM region (read-only)."""
    body = struct.pack("<I", pid)
    conn.sendall(struct.pack("<III", PACKET_MAGIC, CMD_PROC_MAPS,
                             len(body)) + body)
    check_response_ok(conn)
    count = struct.unpack("<I", _recv_exact(conn, 4))[0]
    if count > MAX_MAP_COUNT:
        raise ValueError("Trop de regions memoire ; refus de continuer")
    regions: list[tuple[str, int, int, int]] = []
    for _ in range(count):
        data = _recv_exact(conn, MAP_ENTRY_SIZE)
        name = data[:32].split(b"\x00", 1)[0].decode("latin1")
        start, end, _off, prot = struct.unpack_from("<QQQH", data, 32)
        if start < end:
            regions.append((name, start, end, int(prot)))
    return regions


def module_for(regions, addr: int):
    """Locate the named module whose region contains `addr`.

    The module base is the lowest start among all regions that share the
    containing region's (non-empty) name.
    """
    hit = next((r for r in regions if r[1] <= addr < r[2]), None)
    if hit is None:
        return None
    name = hit[0]
    if name in ("", "<anonymous>"):
        return {"name": name or "<anonymous>", "base": hit[1],
                "regions": [hit], "anonymous": True}
    same = [r for r in regions if r[0] == name]
    return {"name": name, "base": min(r[1] for r in same),
            "regions": same, "anonymous": False}


def parse_exports(conn: socket.socket, pid: int, base: int) -> dict[str, int]:
    """Parse an Orbis module's export table in RAM -> {nid: st_value}."""
    ehdr = read_mem(conn, pid, base, 64)
    if ehdr[:4] != b"\x7fELF":
        raise ValueError("Pas d'en-tete ELF a la base du module")
    phoff = struct.unpack_from("<Q", ehdr, 32)[0]
    phentsize = struct.unpack_from("<H", ehdr, 54)[0]
    phnum = struct.unpack_from("<H", ehdr, 56)[0]
    if phentsize < 56 or not 0 < phnum <= MAX_PHNUM:
        raise ValueError("Program headers du module invalides")
    phdrs = read_mem(conn, pid, base + phoff, phentsize * phnum)
    dyn = dld = None
    for i in range(phnum):
        typ, _fl, _off, va, _pa, fsz, _msz, _al = struct.unpack_from(
            "<IIQQQQQQ", phdrs, i * phentsize)
        if typ == PT_DYNAMIC and dyn is None:
            dyn = (va, fsz)
        elif typ == PT_SCE_DYNLIBDATA and dld is None:
            dld = (va, fsz)
    if dyn is None or dld is None:
        raise ValueError("Segments DYNAMIC / DYNLIBDATA absents du module")
    dynamic = read_mem(conn, pid, base + dyn[0], min(dyn[1], MAX_DYNAMIC))
    tags: dict[int, int] = {}
    for off in range(0, len(dynamic) - 15, 16):
        tag, val = struct.unpack_from("<QQ", dynamic, off)
        tags.setdefault(tag, val)
        if tag == 0:
            break
    need = {k: tags[v] for k, v in DT.items() if v in tags}
    for req in ("STRTAB", "STRSZ", "SYMTAB", "SYMTABSZ"):
        if req not in need:
            raise ValueError(f"Tag dynamique {req} absent du module")
    dld_rt = base + dld[0]
    strtab = read_mem(conn, pid, dld_rt + need["STRTAB"],
                      min(need["STRSZ"], MAX_TABLE))
    symtab = read_mem(conn, pid, dld_rt + need["SYMTAB"],
                      min(need["SYMTABSZ"], MAX_TABLE))
    exports: dict[str, int] = {}
    for off in range(0, len(symtab) - 23, 24):
        st_name, _info, _other, shndx, value, _size = struct.unpack_from(
            "<IBBHQQ", symtab, off)
        if shndx == 0 or value == 0:
            continue  # SHN_UNDEF / import, not an export
        if st_name >= len(strtab):
            continue
        end = strtab.find(b"\x00", st_name)
        if end < 0:
            continue
        key = strtab[st_name:end].decode("latin1").split("#", 1)[0]
        exports.setdefault(key, value)
    return exports


def resolve_loader(ip: str, *, tailscale: bool = False,
                   expected_fw: int = DEFAULT_EXPECTED_FW, timeout: float = 8.0,
                   anchor_rva: int = ANCHOR_GOT_RVA,
                   target: str = TARGET_SYMBOL) -> dict:
    report = live.check_live(ip, tailscale=tailscale, expected_fw=expected_fw,
                             timeout=timeout)
    if not report["profile"]["live_rage_packfile8_profile_matches_eboot_100"]:
        raise ValueError("Profil fiPackfile8 non conforme : resolution refusee")
    pid = report["pid"]
    base = int(report["image_base"], 16)
    img = [(int(r["start"], 16), int(r["end"], 16))
           for r in report["image_regions"]]
    img_lo = min(s for s, _ in img)
    img_hi = max(e for _, e in img)
    target_nid, anchor_nid = nid(target), nid(ANCHOR_SYMBOL)
    out = {
        "image_base": report["image_base"], "pid": pid, "reads_only": True,
        "anchor": {"symbol": ANCHOR_SYMBOL, "nid": anchor_nid,
                   "got_rva": f"0x{anchor_rva:08X}"},
        "target": {"symbol": target, "nid": target_nid},
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
        if img_lo <= ptr < img_hi:
            out["status"] = "anchor-unresolved-in-image"
            out["note"] = ("Le slot GOT pointe dans l'image du jeu : liaison "
                           "non resolue. Re-tester jeu lance, ou repli "
                           "CMD_PROC_ELF_RPC (voir PRX_LOADING_STUDY_100.md).")
            return out
        mod = module_for(read_maps(c, pid), ptr)
        if mod is None:
            out["status"] = "anchor-outside-known-module"
            return out
        out["anchor_module"] = {"name": mod["name"],
                                "base": f"0x{mod['base']:X}"}
        if mod["anonymous"]:
            out["status"] = "anchor-module-anonymous"
            out["note"] = ("La region contenant le pointeur n'a pas de nom de "
                           "module ; impossible de delimiter ses exports.")
            return out
        exports = parse_exports(c, pid, mod["base"])
    out["anchor_module"]["export_count"] = len(exports)
    if target_nid not in exports:
        out["status"] = "target-not-exported-by-anchor-module"
        out["note"] = (f"{target} (NID {target_nid}) absent des exports de "
                       f"{mod['name']}. Essayer un autre module exportant ce "
                       "symbole.")
        return out
    loader_addr = mod["base"] + exports[target_nid]
    exec_ok = any(s <= loader_addr < e and p & 4
                  for _n, s, e, p in mod["regions"])
    out["status"] = "resolved"
    out["loader_addr"] = f"0x{loader_addr:X}"
    out["loader_addr_in_exec_region"] = exec_ok
    out["inject_hint"] = f"--loader-addr 0x{loader_addr:X}"
    out["note"] = ("Adresse RESOLUE en lecture seule (valable pour CE "
                   "lancement du jeu). A fournir a inject.py --loader-addr. "
                   "Rien n'a ete charge ni ecrit.")
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
        result = resolve_loader(args.ip, tailscale=args.tailscale,
                                expected_fw=args.expected_fw,
                                timeout=args.timeout)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("status") == "resolved" else 4
    except (ValueError, ConnectionError, OSError, struct.error, KeyError) as exc:
        print("Resolution interrompue sans modification : " + str(exc),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
