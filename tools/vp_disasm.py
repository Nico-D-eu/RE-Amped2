"""
Disassemble NV2A vertex-program slots, as the executor prints them.

    py -3 tools/vp_disasm.py diag/vb3.txt          # every "slot N: w1 w2 w3" line
    py -3 tools/vp_disasm.py - < listing.txt

Reads lines of the form "slot N: WWWWWWWW WWWWWWWW WWWWWWWW" (dwords 1..3 of
each 128-bit slot) and prints each as MAC and ILU operations. The field table
is the one in xboxrecomp/src/kernel/nv2a_vp.c -- this is its reading, printed,
so a listing and the interpreter cannot disagree about what a slot says.
"""
import re
import sys

MAC = ["NOP", "MOV", "MUL", "ADD", "MAD", "DP3", "DPH", "DP4", "DST", "MIN",
       "MAX", "SLT", "SGE", "ARL"] + ["MAC?"] * 2
ILU = ["NOP", "MOV", "RCP", "RCC", "RSQ", "EXP", "LOG", "LIT"]
OUT = {0: "oPos", 3: "oD0", 4: "oD1", 5: "oFog", 6: "oPts", 7: "oB0", 8: "oB1",
       9: "oT0", 10: "oT1", 11: "oT2", 12: "oT3"}


def fld(w, dword, start, length):
    return (w[dword] >> start) & ((1 << length) - 1)


def swz(s):
    v = "".join("xyzw"[(s >> (6 - 2 * i)) & 3] for i in range(4))
    return "" if v == "xyzw" else "." + v


def src(w, mux, r, neg, s):
    if mux == 1:
        base = "oPos" if r == 12 else "r%d" % r
    elif mux == 2:
        base = "v%d" % fld(w, 1, 9, 4)
    elif mux == 3:
        c = fld(w, 1, 13, 8)
        base = "c[a0+%d]" % c if fld(w, 3, 1, 1) else "c[%d]" % c
    else:
        base = "?"
    return ("-" if neg else "") + base + swz(s)


def mask(m):
    return "." + "".join(ch for bit, ch in zip((8, 4, 2, 1), "xyzw") if m & bit)


def disasm(slot, w):
    mac, ilu = fld(w, 1, 21, 4), fld(w, 1, 25, 3)
    a = src(w, fld(w, 2, 26, 2), fld(w, 2, 28, 4), fld(w, 1, 8, 1), fld(w, 1, 0, 8))
    b = src(w, fld(w, 2, 11, 2), fld(w, 2, 13, 4), fld(w, 2, 25, 1), fld(w, 2, 17, 8))
    c_r = (fld(w, 2, 0, 2) << 2) | fld(w, 3, 30, 2)
    c = src(w, fld(w, 3, 28, 2), c_r, fld(w, 2, 10, 1), fld(w, 2, 2, 8))
    out_r = fld(w, 3, 20, 4)
    mac_mask, ilu_mask, o_mask = fld(w, 3, 24, 4), fld(w, 3, 16, 4), fld(w, 3, 12, 4)
    ops = []
    dsts = []
    if mac and mac != 13 and mac_mask:
        dsts.append(("oPos" if out_r == 12 else "r%d" % out_r) + mask(mac_mask))
    if o_mask and not fld(w, 3, 2, 1):
        addr = fld(w, 3, 3, 8)
        dsts.append((OUT.get(addr & 15, "o?%d" % addr) if fld(w, 3, 11, 1)
                     else "c[%d]" % addr) + mask(o_mask))
    if mac == 13:
        ops.append("ARL a0.x, %s" % a)
    elif mac:
        args = {1: [a], 2: [a, b], 3: [a, c], 4: [a, b, c]}.get(mac, [a, b])
        ops.append("%s %s, %s" % (MAC[mac], " & ".join(dsts) or "-", ", ".join(args)))
    if ilu:
        idst = []
        ir = 1 if mac else out_r
        if ilu_mask:
            idst.append(("oPos" if ir == 12 else "r%d" % ir) + mask(ilu_mask))
        if o_mask and fld(w, 3, 2, 1):
            addr = fld(w, 3, 3, 8)
            idst.append((OUT.get(addr & 15, "o?%d" % addr) if fld(w, 3, 11, 1)
                         else "c[%d]" % addr) + mask(o_mask))
        ops.append("%s %s, %s" % (ILU[ilu], " & ".join(idst) or "-", c))
    fin = "  ; FINAL" if fld(w, 3, 0, 1) else ""
    return "%3d: %s%s" % (slot, "  ||  ".join(ops) or "NOP", fin)


def main():
    f = sys.stdin if len(sys.argv) < 2 or sys.argv[1] == "-" else open(
        sys.argv[1], encoding="latin-1")
    pat = re.compile(r"slot\s+(\d+):\s+([0-9A-Fa-f]{8})\s+([0-9A-Fa-f]{8})\s+([0-9A-Fa-f]{8})"
                     r"(?:\s+([0-9A-Fa-f]{8}))?")
    for line in f:
        m = pat.search(line)
        if not m:
            continue
        words = [int(x, 16) for x in m.groups()[1:] if x]
        if len(words) == 4:            # "slot N: w0 w1 w2 w3" (the VP trace form)
            words = words[1:]
        print(disasm(int(m.group(1)), [0] + words))


if __name__ == "__main__":
    main()
