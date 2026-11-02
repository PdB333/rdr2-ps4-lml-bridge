#!/usr/bin/env python3
"""Inspecte le conteneur SELF .prx d'OpenOrbis comme le fait tac_prx_inspect :
localise l'ELF embarque, liste ses program headers, repere les PT_LOAD qui se
chevauchent (le controle que TacHen applique). Lecture seule, aucun patch."""
import struct, sys

def main(path):
    with open(path, "rb") as f:
        buf = f.read()
    print(f"taille={len(buf)}")
    # En-tete SELF OpenOrbis : magic 4F 15 3D 1D
    assert buf[:4] == bytes([0x4f, 0x15, 0x3d, 0x1d]), "pas un SELF OpenOrbis"
    # Trouver l'ELF embarque : magic \x7fELF. create-fself le place apres
    # l'en-tete SELF + table de segments.
    elf_off = buf.find(b"\x7fELF", 4)
    print(f"elf_off=0x{elf_off:x}")
    e = buf[elf_off:]
    (e_type,) = struct.unpack_from("<H", e, 16)
    (e_phoff,) = struct.unpack_from("<Q", e, 32)
    (e_phentsize,) = struct.unpack_from("<H", e, 54)
    (e_phnum,) = struct.unpack_from("<H", e, 56)
    print(f"e_type=0x{e_type:x} phoff=0x{e_phoff:x} phentsize={e_phentsize} phnum={e_phnum}")
    loads = []
    for i in range(e_phnum):
        base = e_phoff + i * e_phentsize
        p_type, p_flags = struct.unpack_from("<II", e, base)
        p_off, p_vaddr, p_paddr = struct.unpack_from("<QQQ", e, base + 8)
        p_filesz, p_memsz, p_align = struct.unpack_from("<QQQ", e, base + 32)
        tag = {1: "LOAD", 2: "DYNAMIC", 0x6474e551: "GNU_STACK",
               0x6474e550: "GNU_EH_FRAME", 0x6474e552: "GNU_RELRO",
               0x61000000: "SCE_DYNLIBDATA", 0: "NULL"}.get(p_type, hex(p_type))
        print(f"  ph[{i}] type={tag:14} flags=0x{p_flags:x} off=0x{p_off:x} "
              f"vaddr=0x{p_vaddr:x} filesz=0x{p_filesz:x} memsz=0x{p_memsz:x} align=0x{p_align:x}")
        if p_type == 1:
            loads.append((i, p_vaddr, p_memsz))
    # Controle de chevauchement a la TacHen
    print("--- chevauchements PT_LOAD ---")
    bad = False
    for a in range(len(loads)):
        ia, va, ma = loads[a]
        for b in range(a):
            ib, vb, mb = loads[b]
            if va < vb + mb and vb < va + ma:
                print(f"  OVERLAP ph[{ia}] (vaddr=0x{va:x}+0x{ma:x}) <-> ph[{ib}] (vaddr=0x{vb:x}+0x{mb:x})")
                bad = True
    print("AUCUN chevauchement" if not bad else "=> rejet TacHen attendu")

if __name__ == "__main__":
    main(sys.argv[1])
