#!/usr/bin/env python3
"""Offline RAGE native-handler map extractor for a user-owned PS4 RDR2 ELF.

Read-only. Standard library + the local ``inspect_rdr2_eboot.Image`` ELF
parser only. Does not decrypt a SELF, modify the game, publish any binary
or touch a live console.

What it does
------------
RDR2's script natives are registered in the EBOOT by a fixed instruction
pattern, emitted once per native at its registration site::

    48 B9 <imm64>        movabs rcx, <native hash>
    48 8D 15 <disp32>    lea    rdx, [rip + <disp>]   ; -> native handler

Scanning the executable segments for that pattern yields, for every native,
the pair (hash, handler RVA). Because the handler RVA is STATIC in the image,
a console-side invoker can call ``(image_base + handler_rva)(NativeContext*)``
directly for a known hash -- no runtime walk of the registration list needed.

SAFETY / SCOPE
--------------
- SHA-256 gated: refuses any ELF that is not the owner-confirmed 1.00 EBOOT
  (same constant as inspect_rdr2_eboot). RVAs are 1.00-specific and MUST NOT
  be reused for 1.32.
- It emits RE-derived RVAs and hashes, never raw EBOOT bytes. Do not commit
  the generated map file or the eboot into the public repository.
- This is static reconnaissance only. The native calling convention and the
  NativeContext ABI remain UNVERIFIED until exercised on console.

Example::

  python -B tools/inspect_rage_natives.py eboot.bin \
    --expected-sha256 e3ae087f833b0f30f462bb7f880dd2955bf9f51dbb6e56706ee9bda81581feff \
    --manifest NativeTrainer.native_manifest.json \
    --out private-native-map.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import mmap
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from inspect_rdr2_eboot import Image, USER_CONFIRMED_100_SHA256  # noqa: E402

# movabs rcx, imm64 ; lea rdx, [rip + disp32]
PATTERN = re.compile(rb"\x48\xb9(.{8})\x48\x8d\x15(.{4})", re.DOTALL)
REG_SITE_LEN = 17                       # bytes of the movabs+lea pair
MIN_HASH = 0x1_0000_0000                # native hashes are full 64-bit values


def scan_natives(image: Image) -> list[tuple[int, int, int]]:
    """Return (hash, handler_rva, site_rva) for every registration site.

    Only executable segments are scanned, and a candidate is kept only when
    its handler lands in an executable segment and the hash is a genuine
    64-bit value -- this rejects incidental ``movabs rcx`` of small constants.
    """
    sites: list[tuple[int, int, int]] = []
    seen: set[int] = set()
    for va, off, size, flags in image.segments:
        if not flags & 1:               # executable only
            continue
        window = image.raw[off:off + size]
        for m in PATTERN.finditer(window):
            native_hash = struct.unpack("<Q", m.group(1))[0]
            if native_hash < MIN_HASH:
                continue
            disp = struct.unpack("<i", m.group(2))[0]
            site_rva = va + m.start()
            handler_rva = site_rva + REG_SITE_LEN + disp
            if not image.is_executable(handler_rva):
                continue
            if site_rva in seen:
                continue
            seen.add(site_rva)
            sites.append((native_hash, handler_rva, site_rva))
    return sites


def load_known_hashes(manifest: Path) -> set[int]:
    """Collect every 64-bit hex value from an arbitrary native manifest JSON."""
    known: set[int] = set()

    def walk(node) -> None:
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str):
            text = node.strip()
            if text.lower().startswith("0x") and len(text) >= 18:
                try:
                    value = int(text, 16)
                except ValueError:
                    return
                if value > 0xFFFFFFFF:
                    known.add(value)

    walk(json.loads(manifest.read_text(encoding="utf-8")))
    return known


def analyse(path: Path, expected_hash: str, manifest: Path | None) -> dict:
    sha = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            sha.update(chunk)
    digest = sha.hexdigest()
    if expected_hash and digest != expected_hash.lower():
        raise ValueError("ELF SHA-256 does not match this version profile")
    if digest != USER_CONFIRMED_100_SHA256:
        raise ValueError("Refusing: this is not the owner-confirmed 1.00 EBOOT")

    with path.open("rb") as f, \
            mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as raw:
        image = Image(raw)
        sites = scan_natives(image)

    if not sites:
        raise ValueError("No native registration site found (pattern absent)")

    by_hash: dict[int, int] = {}
    collisions = 0
    for native_hash, handler_rva, _site in sites:
        prev = by_hash.get(native_hash)
        if prev is not None and prev != handler_rva:
            collisions += 1
        by_hash.setdefault(native_hash, handler_rva)

    known = load_known_hashes(manifest) if manifest else set()
    matched = sorted(known & by_hash.keys())

    result = {
        "schema": "rdr2-orbis-rage-native-map-readonly/1",
        "input_filename": path.name,
        "sha256": digest,
        "user_reported_patch": "1.00",
        "known_profile_compatible_with_1_32": False,
        "registration_pattern": "movabs rcx,<hash>; lea rdx,[rip+disp]",
        "sites_total": len(sites),
        "natives_distinct": len(by_hash),
        "handler_rva_collisions": collisions,
        "known_hashes_in_manifest": len(known),
        "known_hashes_matched": len(matched),
        "sample_known_map": {
            f"0x{h:016X}": f"0x{by_hash[h]:08X}" for h in matched[:8]
        },
        "invoker_note": (
            "handler runtime addr = image_base + handler_rva; direct call "
            "handler(NativeContext*). Calling convention/ABI UNVERIFIED."),
        "warning": (
            "1.00-specific RVAs. Never reuse for 1.32. Do not commit the "
            "generated map or the eboot to the public repository."),
    }
    result["_full_map"] = {f"0x{h:016X}": f"0x{r:08X}"
                           for h, r in sorted(by_hash.items())}
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("eboot", type=Path)
    ap.add_argument("--expected-sha256", default="")
    ap.add_argument("--manifest", type=Path,
                    help="JSON de hashes connus pour recoupement (optionnel)")
    ap.add_argument("--out", type=Path,
                    help="Fichier local pour la carte complete hash->handler")
    args = ap.parse_args()
    try:
        result = analyse(args.eboot, args.expected_sha256, args.manifest)
        full_map = result.pop("_full_map")
        if args.out:
            if args.out.exists():
                raise ValueError("Refusing to overwrite existing report")
            payload = dict(result)
            payload["hash_to_handler_rva"] = full_map
            args.out.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8")
            print("Native map saved:", args.out,
                  f"({len(full_map)} natives)")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (OSError, ValueError, struct.error, json.JSONDecodeError) as e:
        print("Native scan failed:", e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
