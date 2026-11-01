#!/usr/bin/env python3
"""Read-only ABI recovery for fiPackfile8::Open / ::Read (RDR2 PS4 1.00).

Purpose: before writing a detour TRAMPOLINE we must know the exact calling
convention of the two hooked methods -- guessing the signature would crash the
game (owner rule: never patch/guess). This disassembles the two handlers
statically from the user-owned EBOOT and infers, WITHOUT executing anything:
  - which argument registers (rdi,rsi,rdx,rcx,r8,r9) are read before written
    -> the incoming arguments and their count;
  - the stack frame size (sub rsp, N) and whether the frame is a standard
    push-rbp prologue;
  - call / tail-jmp targets count (handlers that are thin thunks).

SAFETY:
- SHA-256 gated to the confirmed 1.00 EBOOT; refuses any other binary.
- Reads only; never writes, never contacts a console, never publishes bytes.
- The FULL instruction listing (a derivative of proprietary code) is written
  ONLY to a local --out file you must NOT commit. stdout carries just the ABI
  summary (register roles, counts), not verbatim game instructions.
- The result is a STATIC HYPOTHESIS. It still has to be confirmed live before a
  trampoline is armed (see orbis/LIVE_DETOUR_100.md).

Capstone (pip install capstone) is required.
"""
from __future__ import annotations
import argparse
import json
import mmap
import sys
from pathlib import Path

from inspect_rdr2_eboot import Image, USER_CONFIRMED_100_SHA256

try:
    import capstone
except ImportError:  # pragma: no cover - environment dependent
    capstone = None

# fiPackfile8 vtable handler RVAs, confirmed live (five_known_method_slots).
TARGETS = {"open_slot2": 0x0452A480, "read_slot13": 0x0452B9D0}
# fiPackfile8 class vtable, confirmed live (ps5debug_ng_rdr2_100_live_profile).
VTABLE_RVA = 0x066B00F8
VTABLE_SLOTS = 112
ARG_ORDER = ("rdi", "rsi", "rdx", "rcx", "r8", "r9")
SUBREG = {  # normalize sub-registers to their 64-bit arg register
    "edi": "rdi", "di": "rdi", "dil": "rdi",
    "esi": "rsi", "si": "rsi", "sil": "rsi",
    "edx": "rdx", "dx": "rdx", "dl": "rdx",
    "ecx": "rcx", "cx": "rcx", "cl": "rcx",
    "r8d": "r8", "r8w": "r8", "r8b": "r8",
    "r9d": "r9", "r9w": "r9", "r9b": "r9",
}


def _canon(reg: str) -> str:
    return SUBREG.get(reg, reg)


def analyse_one(image: Image, rva: int, max_insns: int) -> tuple[dict, list[str]]:
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    off = image.rva_offset(rva, 1)
    code = image.raw[off:off + max_insns * 15]  # x86 insn <= 15 bytes

    listing: list[str] = []
    first_use: dict[str, str] = {}   # arg reg -> "read" or "written" (first seen)
    frame_bytes = 0
    push_rbp = False
    calls = 0
    tail_jmp = False
    ret_seen = False

    for insn in md.disasm(code, rva):
        listing.append(f"0x{insn.address:08x}  {insn.mnemonic} {insn.op_str}")
        regs_read, regs_written = insn.regs_access()
        for rid in regs_read:
            r = _canon(md.reg_name(rid))
            if r in ARG_ORDER and r not in first_use:
                first_use[r] = "read"
        for rid in regs_written:
            r = _canon(md.reg_name(rid))
            if r in ARG_ORDER and r not in first_use:
                first_use[r] = "written"
        if insn.mnemonic == "push" and insn.op_str == "rbp":
            push_rbp = True
        if insn.mnemonic == "sub" and insn.op_str.startswith("rsp,"):
            try:
                frame_bytes = int(insn.op_str.split(",")[1].strip(), 0)
            except ValueError:
                pass
        if insn.mnemonic == "call":
            calls += 1
        if insn.mnemonic == "ret":
            ret_seen = True
            break
        if insn.mnemonic == "jmp" and not insn.op_str.startswith(("0x", "qword", "dword")) is False:
            # a jmp to an absolute/code target before any ret: likely tail call
            if not ret_seen:
                tail_jmp = True
        if len(listing) >= max_insns:
            break

    # Incoming args: arg registers whose FIRST access is a read.
    incoming = [r for r in ARG_ORDER if first_use.get(r) == "read"]
    # Argument count = contiguous prefix of ARG_ORDER that is read-first.
    arg_count = 0
    for r in ARG_ORDER:
        if first_use.get(r) == "read":
            arg_count += 1
        else:
            break
    summary = {
        "rva": f"0x{rva:08X}",
        "incoming_arg_registers": incoming,
        "contiguous_arg_count": arg_count,
        "standard_push_rbp_prologue": push_rbp,
        "stack_frame_bytes": frame_bytes,
        "call_count": calls,
        "tail_jmp_before_ret": tail_jmp,
        "ret_reached": ret_seen,
        "instructions_decoded": len(listing),
    }
    return summary, listing


# Signature shape -> fiDevice role hint. 2 args (this, handle) is shared by
# Close and GetSize, so those stay candidates, never an assertion.
def _role_hint(arg_count: int) -> str:
    return {
        2: "close/size candidate (this, handle)",
        3: "open-like (this, path, flag)",
        4: "seek candidate (this, handle, offset, whence)",
        5: "read-like (this, handle, buffer, size, +1)",
    }.get(arg_count, "unknown/nullary")


def sweep_vtable(image: Image, max_insns: int) -> tuple[list[dict], dict, dict]:
    """Decode every fiPackfile8 vtable slot's argument shape (read-only).

    Returns (per-slot summaries, lifecycle-candidate hints). Only argument
    shapes are inferred; which slot is semantically Close vs GetSize cannot be
    settled by register use alone, so both remain candidates to confirm live.
    """
    slots: list[dict] = []
    listings: dict[str, list[str]] = {}
    for idx in range(VTABLE_SLOTS):
        method = image.qword(VTABLE_RVA + 8 * idx)
        if not image.is_executable(method):
            slots.append({"slot": idx, "rva": f"0x{method:08X}",
                          "executable": False})
            continue
        summary, listing = analyse_one(image, method, max_insns)
        summary["slot"] = idx
        summary["role_hint"] = _role_hint(summary["contiguous_arg_count"])
        slots.append(summary)
        listings[f"slot_{idx:03d}"] = listing
    candidates = {
        "seek": [s["slot"] for s in slots
                 if s.get("contiguous_arg_count") == 4],
        "close_or_size": [s["slot"] for s in slots
                          if s.get("contiguous_arg_count") == 2],
    }
    return slots, listings, candidates


def analyse(path: Path, expected_sha: str, max_insns: int,
            sweep: bool = False) -> tuple[dict, dict]:
    import hashlib
    sha = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            sha.update(chunk)
    if sha.hexdigest() != expected_sha.lower():
        raise ValueError("EBOOT SHA-256 ne correspond pas au profil 1.00")
    if capstone is None:
        raise RuntimeError("capstone requis (pip install capstone)")
    with path.open("rb") as f, mmap.mmap(f.fileno(), 0,
                                         access=mmap.ACCESS_READ) as raw:
        image = Image(raw)
        summaries, listings = {}, {}
        for name, rva in TARGETS.items():
            if not image.is_executable(rva):
                raise ValueError(f"{name} RVA non executable : profil invalide")
            summaries[name], listings[name] = analyse_one(image, rva, max_insns)
        report = {
            "schema": "rdr2-rage-packfile-abi-readonly/1",
            "sha256": sha.hexdigest(),
            "note": ("Hypothese STATIQUE de l'ABI. A confirmer live avant "
                     "d'armer un trampoline. Aucun octet du jeu dans ce "
                     "resume."),
            "methods": summaries,
        }
        if sweep:
            slots, slot_listings, candidates = sweep_vtable(image, max_insns)
            report["vtable_sweep"] = slots
            report["lifecycle_candidates"] = candidates
            listings.update(slot_listings)
    return report, listings


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("eboot", type=Path)
    p.add_argument("--expected-sha256", default=USER_CONFIRMED_100_SHA256)
    p.add_argument("--max-insns", type=int, default=160)
    p.add_argument("--sweep", action="store_true",
                   help="Balaye les 112 slots et propose les candidats "
                        "close/seek/size (lecture seule)")
    p.add_argument("--out", type=Path,
                   help="Fichier LOCAL pour le listing complet (NE PAS commiter)")
    args = p.parse_args(argv)
    # Never clobber an existing file (the EBOOT above all) with the listing.
    if args.out:
        try:
            same = args.out.resolve() == args.eboot.resolve()
        except OSError:
            same = False
        if same:
            print("Refus : --out est l'EBOOT d'entree (ecrasement interdit)",
                  file=sys.stderr)
            return 2
        if args.out.exists():
            print("Refus d'ecraser un fichier existant : " + str(args.out),
                  file=sys.stderr)
            return 2
    try:
        report, listings = analyse(args.eboot, args.expected_sha256,
                                   args.max_insns, sweep=args.sweep)
    except (ValueError, RuntimeError, OSError) as exc:
        print("Analyse ABI interrompue : " + str(exc), file=sys.stderr)
        return 2
    if args.out:
        args.out.write_text(json.dumps(
            {"methods": report["methods"], "listings": listings},
            ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
