#!/usr/bin/env python3
# Analyse LIVE en LECTURE PURE (ps5debug-NG port 744) pour trancher 11-vs-13 et
# localiser le site d'install du detour, SANS ecrire dans le jeu :
#   - DISASM_REGION des slots 11/13 (reconfirme forwarder vs primitive en live),
#   - FIND_XREFS_TO sur la vtable fiPackfile8 (ou sont construits les objets).
# Aucune ecriture, aucun breakpoint (un bp HW gelerait une primitive chaude).
# Usage : python -I ps5debug_trace.py <IP_CONSOLE> [pid]
import socket, struct, sys

PORT = 744
MAGIC = 0xFFAABBCC
OK = 0x80000000
CMD_PROC_LIST = 0xBDAA0001
CMD_PROC_DISASM = 0xBDAA0020
CMD_PROC_FIND_XREFS_TO = 0xBDAA0022

VT_RVA = 0x066B00F8
SLOT11 = 0x0452a870
SLOT13 = 0x0452b9d0
SENT = b"\xff" * 8

MNEM = {}  # on se contente du bitmask kind + operande

def rall(s, n):
    b = b""
    while len(b) < n:
        c = s.recv(n - len(b))
        if not c: raise IOError("closed")
        b += c
    return b

def cmd(s, c, body=b""):
    s.sendall(struct.pack("<III", MAGIC, c, len(body)) + body)

def st(s):
    return struct.unpack("<I", rall(s, 4))[0]

def proc_list(s):
    cmd(s, CMD_PROC_LIST)
    if st(s) != OK: raise IOError("list")
    n = struct.unpack("<I", rall(s, 4))[0]
    r = []
    for _ in range(n):
        e = rall(s, 36)
        r.append((e[:32].split(b"\x00")[0].decode("latin1"),
                  struct.unpack("<i", e[32:36])[0]))
    return r

def disasm(s, pid, addr, length, maxn=256):
    cmd(s, CMD_PROC_DISASM, struct.pack("<iQII", pid, addr, length, maxn))
    if st(s) != OK: raise IOError("disasm")
    out = []
    while True:
        e = rall(s, 32)
        if e == b"\xff" * 32: break
        a, rip, disp = struct.unpack("<QQq", e[:24])
        ln, kind, mbase, midx, mscale, mn = struct.unpack("<BBBBBB", e[24:30])
        out.append(dict(a=a, rip=rip, disp=disp, len=ln, kind=kind,
                        mbase=mbase, mscale=mscale))
    return out

def xrefs(s, pid, scan_addr, scan_len, target):
    cmd(s, CMD_PROC_FIND_XREFS_TO,
        struct.pack("<iQIQ", pid, scan_addr, scan_len, target))
    if st(s) != OK: raise IOError("xref")
    out = []
    while True:
        e = rall(s, 8)
        if e == SENT: break
        out.append(struct.unpack("<Q", e)[0])
    return out

def kinds(k):
    f = []
    if k & 0x01: f.append("CALL")
    if k & 0x04: f.append("JMP")
    if k & 0x08: f.append("Jcc")
    if k & 0x02: f.append("RET")
    if k & 0x10: f.append("mem")
    if k & 0x20: f.append("rip")
    return "|".join(f) or "-"

def show(name, ins, base):
    print("=== %s (%d instr) ===" % (name, len(ins)))
    for d in ins:
        tgt = ""
        if d["kind"] & 0x01 and d["kind"] & 0x10:   # call [reg+disp] = dispatch vtable
            tgt = "  -> call [reg+0x%x] (slot %d?)" % (d["disp"] & 0xffffffff,
                                                        (d["disp"] & 0xffffffff) // 8)
        elif d["kind"] & (0x04 | 0x01) and d["kind"] & 0x10:
            tgt = "  -> jmp [reg+0x%x]" % (d["disp"] & 0xffffffff)
        print("  0x%x (rva 0x%x) %-14s len=%d%s"
              % (d["a"], d["a"] - base, kinds(d["kind"]), d["len"], tgt))

def main():
    if len(sys.argv) < 2:
        print("usage: python -I ps5debug_trace.py <IP> [pid]"); return 2
    ip = sys.argv[1]
    s = socket.create_connection((ip, PORT), timeout=10); s.settimeout(30)
    procs = proc_list(s)
    if len(sys.argv) >= 3:
        pid = int(sys.argv[2])
    else:
        c = [p for p in procs if "eboot" in p[0].lower()]
        if not c: print("[!] eboot absent"); return 1
        pid = c[0][1]
    print("[*] pid=%d" % pid)
    base = 0x400000
    print("\n[A] DISASM slot 13 (forwarder attendu) :")
    show("slot13", disasm(s, pid, base + SLOT13, 0x40), base)
    print("\n[A] DISASM slot 11 tete (primitive attendue) :")
    show("slot11", disasm(s, pid, base + SLOT11, 0x80), base)
    print("\n[B] XREFS directs vers la vtable 0x%x (sites d'install) :" % (base + VT_RVA))
    # scan du segment code r-x : 0x400000 .. ~0x400000+0x6413b30
    xs = xrefs(s, pid, base, 0x6413b30, base + VT_RVA)
    print("    %d xref(s) directs a la vtable" % len(xs))
    for a in xs[:30]:
        print("      0x%x (rva 0x%x)" % (a, a - base))
    s.close()
    return 0

if __name__ == "__main__":
    sys.exit(main())
