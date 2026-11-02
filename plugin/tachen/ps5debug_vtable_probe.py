#!/usr/bin/env python3
# Validation LIVE (lecture pure) de la vtable fiPackfile8 dans RDR2 1.00 via
# ps5debug-NG (port 744). Aucune ecriture : uniquement PROC_LIST / PROC_MAPS /
# PROC_READ. Conforme a la regle "ne pas modifier la memoire du jeu tant que les
# signatures ne sont pas validees".
#
# Usage : python -I ps5debug_vtable_probe.py <IP_CONSOLE> [pid]
# L'IP n'est JAMAIS commitee : passee en argument.
import socket, struct, sys

PORT        = 744
MAGIC       = 0xFFAABBCC
CMD_SUCCESS = 0x80000000          # valeur sur le fil (post bit-swap)
CMD_PROC_LIST = 0xBDAA0001
CMD_PROC_READ = 0xBDAA0002
CMD_PROC_MAPS = 0xBDAA0004

VT_RVA   = 0x066B00F8             # vtable fiPackfile8 (RVA, base Ghidra 0)
N_SLOTS  = 112
KNOWN = [  # (slot, rva, nom)
    (2,  0x0452a480, "Open"),
    (11, 0x0452a870, "Read-prim(0x58)"),
    (13, 0x0452b9d0, "Read-fwd(->+0x68)"),
    (17, 0x0452ba90, "Seek32"),
    (18, 0x0452baa0, "Seek64"),
    (19, 0x0452be00, "Close"),
    (22, 0x0452be30, "Size32"),
    (23, 0x0452be80, "Size64"),
    (48, 0x04521a00, "ReadFull(0x58)"),
]

def recv_all(s, n):
    b = b""
    while len(b) < n:
        c = s.recv(n - len(b))
        if not c:
            raise IOError("socket closed")
        b += c
    return b

def send_cmd(s, cmd, body=b""):
    s.sendall(struct.pack("<III", MAGIC, cmd, len(body)) + body)

def status(s):
    return struct.unpack("<I", recv_all(s, 4))[0]

def proc_list(s):
    send_cmd(s, CMD_PROC_LIST)
    if status(s) != CMD_SUCCESS:
        raise IOError("PROC_LIST status fail")
    num = struct.unpack("<I", recv_all(s, 4))[0]
    out = []
    for _ in range(num):
        e = recv_all(s, 36)
        name = e[:32].split(b"\x00")[0].decode("latin1")
        pid = struct.unpack("<i", e[32:36])[0]
        out.append((name, pid))
    return out

def proc_maps(s, pid):
    send_cmd(s, CMD_PROC_MAPS, struct.pack("<i", pid))
    if status(s) != CMD_SUCCESS:
        raise IOError("PROC_MAPS status fail")
    num = struct.unpack("<I", recv_all(s, 4))[0]
    out = []
    for _ in range(num):
        e = recv_all(s, 58)
        name = e[:32].split(b"\x00")[0].decode("latin1")
        start, end, off = struct.unpack("<QQQ", e[32:56])
        prot = struct.unpack("<H", e[56:58])[0]
        out.append((name, start, end, off, prot))
    return out

def proc_read(s, pid, addr, length):
    send_cmd(s, CMD_PROC_READ, struct.pack("<iQI", pid, addr, length))
    if status(s) != CMD_SUCCESS:
        raise IOError("PROC_READ status fail @%x" % addr)
    return recv_all(s, length)

def prot_str(p):
    return ("r" if p & 1 else "-") + ("w" if p & 2 else "-") + ("x" if p & 4 else "-")

def main():
    if len(sys.argv) < 2:
        print("usage: python -I ps5debug_vtable_probe.py <IP> [pid]"); return 2
    ip = sys.argv[1]
    s = socket.create_connection((ip, PORT), timeout=10)
    s.settimeout(15)

    procs = proc_list(s)
    print("[*] %d process" % len(procs))
    pid = None
    if len(sys.argv) >= 3:
        pid = int(sys.argv[2])
    else:
        cand = [p for p in procs if "eboot" in p[0].lower()]
        if not cand:
            print("[!] pas d'eboot.bin trouve. Process :")
            for n, p in procs: print("    %-28s pid=%d" % (n, p))
            return 1
        name, pid = cand[0]
        print("[*] cible %s pid=%d" % (name, pid))

    maps = proc_maps(s, pid)
    exe = [m for m in maps if m[4] & 4]          # segments executables
    if not exe:
        print("[!] aucun segment executable"); return 1
    base = min(m[1] for m in exe)                 # base = plus petit start r-x
    print("[*] base eboot = 0x%x" % base)
    vt = base + VT_RVA
    # segment contenant la vtable + sa protection (RELRO attendu : read-only)
    seg = next((m for m in maps if m[1] <= vt < m[2]), None)
    if seg:
        print("[*] vtable_VA=0x%x dans [%s] 0x%x-0x%x prot=%s (%s)" %
              (vt, seg[0], seg[1], seg[2], prot_str(seg[4]),
               "READ-ONLY/RELRO OK" if not (seg[4] & 2) else "INSCRIPTIBLE !"))
    else:
        print("[!] vtable_VA=0x%x hors de toute map" % vt)

    data = proc_read(s, pid, vt, N_SLOTS * 8)
    slots = struct.unpack("<%dQ" % N_SLOTS, data)
    print("[*] recoupement slots (base+rva) :")
    allmatch = True
    for sl, rva, nm in KNOWN:
        got = slots[sl]
        exp = base + rva
        ok = (got == exp)
        allmatch &= ok
        print("    slot %-3d = 0x%x  expect 0x%x  %s  %s"
              % (sl, got, exp, "MATCH" if ok else "DIFF ", nm))
    print("[=] %s" % ("TOUS MATCH -> signatures validees live"
                       if allmatch else "DIFF detecte -> NE PAS armer"))
    s.close()
    return 0 if allmatch else 1

if __name__ == "__main__":
    sys.exit(main())
