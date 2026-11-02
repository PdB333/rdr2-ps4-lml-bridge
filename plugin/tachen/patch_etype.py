#!/usr/bin/env python3
"""Reecrit e_type d'un ELF en ET_SCE_DYNAMIC (0xfe18).

ld.lld --shared emet ET_DYN (3) ; make_fself et le validateur TacHen
(tac_prx_inspect) n'acceptent que les types SCE/EXEC. On force donc
e_type = 0xfe18 (offset 16, uint16 little-endian). Idempotent.
"""
import struct
import sys

ET_SCE_DYNAMIC = 0xFE18


def main(path: str) -> int:
    with open(path, "rb") as fh:
        data = bytearray(fh.read())
    if data[:4] != b"\x7fELF":
        print(f"{path}: pas un ELF", file=sys.stderr)
        return 1
    (cur,) = struct.unpack_from("<H", data, 16)
    if cur == ET_SCE_DYNAMIC:
        print(f"{path}: e_type deja ET_SCE_DYNAMIC")
        return 0
    struct.pack_into("<H", data, 16, ET_SCE_DYNAMIC)
    with open(path, "wb") as fh:
        fh.write(data)
    print(f"{path}: e_type {cur:#06x} -> {ET_SCE_DYNAMIC:#06x}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <fichier.prx>", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
