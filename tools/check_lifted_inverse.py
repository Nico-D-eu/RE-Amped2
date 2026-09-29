"""Lifted sub_0002D884 (the title's 4x4 matrix inverse) against a reference.

The title cannot be mapped at its link address in a harness process (the
harness's own stack and heaps live there), so the lifted code runs over a copy
of the XBE placed through g_xbox_mem_offset -- which is how the real runtime
runs it too -- and the result is checked against a straightforward inverse.
The native code is correct by definition (the game works on an Xbox), so a
lifted result that is not the inverse is a lifting bug.

Register convention: eax = source matrix, esi = destination, ecx = optional
determinant out-pointer.

    py -3 tools\\check_lifted_inverse.py

Needs a 32-bit MSVC (found the way tools.conformance finds it). The same
shape -- lift through xbe_run, run over a copy of the image, compare with a
reference -- works for any leaf maths routine; swap the reference and the
register setup in one().
"""
import os
import subprocess
import sys

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLKIT = os.path.join(os.path.dirname(PROJECT), "xboxrecomp")
sys.path.insert(0, TOOLKIT)
from tools.conformance import xbe_run, __main__ as cm
from tools.recomp.disasm import Disassembler

XBE = os.path.join(PROJECT, "game", "default.xbe")
TARGET = int(sys.argv[1], 16) if len(sys.argv) > 1 else 0x0002D884
work = os.path.join(PROJECT, "build", "lifted_check")
os.makedirs(work, exist_ok=True)

data, sections, base = xbe_run.load(XBE)
cs = Disassembler()._cs
xbe_run._MAX_BYTES = 12000
xbe_run._MAX_INSNS = 4000
funcs, todo = {}, [TARGET]
while todo:
    va = todo.pop()
    if va in funcs:
        continue
    f = xbe_run._decode_at(data, sections, cs, va)
    if f is None:
        sys.exit(f"cannot decode {va:08X}")
    funcs[va] = f
    todo.extend(f.calls)
rows = [(va, f.end - va, f.code) for va, f in sorted(funcs.items())]
lifted, rejected = xbe_run.lift(data, sections, rows)
print("lifted", [hex(v) for v, _, _ in lifted], "rejected", rejected)

out = ['#define RECOMP_GENERATED_CODE 1',
       '#include <stdint.h>', '#include <stddef.h>', '#include <stdio.h>',
       '#include <string.h>', '#include <stdlib.h>', '#include <math.h>',
       '#include <windows.h>', '#include "recomp_types.h"',
       'RECOMP_TLS uint32_t g_eax, g_ecx, g_edx, g_esp, g_ebx, g_esi, g_edi;',
       'RECOMP_TLS uint32_t g_seh_ebp, g_ebp;',
       'RECOMP_TLS double g_fp_stack[8]; RECOMP_TLS int g_fp_top;',
       'RECOMP_TLS uint16_t g_fp_control_word = 0x027F; RECOMP_TLS int g_fp_cmp; RECOMP_TLS uint16_t g_fp_cc = 0x4000;',
       'RECOMP_TLS RecompXmm g_xmm0,g_xmm1,g_xmm2,g_xmm3,g_xmm4,g_xmm5,g_xmm6,g_xmm7;',
       'RECOMP_TLS RecompMmx g_mm0,g_mm1,g_mm2,g_mm3,g_mm4,g_mm5,g_mm6,g_mm7;',
       'volatile uint32_t g_icall_trace[16]; volatile uint32_t g_icall_trace_idx;',
       'volatile uint64_t g_icall_count;', 'ptrdiff_t g_xbox_mem_offset;',
       'void recomp_icall_fail_log(uint32_t va) { (void)va; }',
       'typedef void (*recomp_func_t)(void);',
       'recomp_func_t recomp_lookup(uint32_t va) { (void)va; return 0; }',
       'recomp_func_t recomp_lookup_manual(uint32_t va) { (void)va; return 0; }',
       'recomp_func_t recomp_lookup_kernel(uint32_t va) { (void)va; return 0; }']
for va, _, _ in lifted:
    out.append(f"void lifted_{va:08X}(void);")
for _, _, body in lifted:
    out.append(body)
out.append("static const struct { unsigned va, raw_off, raw_size; } g_secs[] = {")
for s in sections:
    out.append(f"    {{ 0x{s.va:08X}u, 0x{s.raw_off:08X}u, 0x{s.raw_size:08X}u }},")
out.append("};")
out.append(f'#define XBE_PATH "{XBE.replace(chr(92), chr(92) * 2)}"')
out.append(f"#define TARGET lifted_{TARGET:08X}")
out.append(r'''
#undef eax
#undef ecx
#undef edx
#undef esp
#undef ebx
#undef esi
#undef edi
#define GUEST_SIZE 0x04000000u
#define G_IN   0x00F00000u
#define G_OUT  0x00F00100u
#define G_DET  0x00F00200u
#define G_SP   0x00E00000u
static uint8_t *g_mem;

static int load(void) {
    FILE *f = fopen(XBE_PATH, "rb");
    size_t i;
    if (!f) return 0;
    g_mem = (uint8_t *)VirtualAlloc(NULL, GUEST_SIZE, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
    if (!g_mem) return 0;
    for (i = 0; i < sizeof g_secs / sizeof g_secs[0]; i++) {
        fseek(f, (long)g_secs[i].raw_off, SEEK_SET);
        fread(g_mem + g_secs[i].va, 1, g_secs[i].raw_size, f);
    }
    fclose(f);
    g_xbox_mem_offset = (ptrdiff_t)g_mem;
    return 1;
}

/* Reference: cofactor inverse in double. */
static int ref_inverse(const float *m, double *r) {
    double a[16], inv[16], det; int i;
    for (i = 0; i < 16; i++) a[i] = m[i];
    inv[0] = a[5]*a[10]*a[15] - a[5]*a[11]*a[14] - a[9]*a[6]*a[15] + a[9]*a[7]*a[14] + a[13]*a[6]*a[11] - a[13]*a[7]*a[10];
    inv[4] = -a[4]*a[10]*a[15] + a[4]*a[11]*a[14] + a[8]*a[6]*a[15] - a[8]*a[7]*a[14] - a[12]*a[6]*a[11] + a[12]*a[7]*a[10];
    inv[8] = a[4]*a[9]*a[15] - a[4]*a[11]*a[13] - a[8]*a[5]*a[15] + a[8]*a[7]*a[13] + a[12]*a[5]*a[11] - a[12]*a[7]*a[9];
    inv[12] = -a[4]*a[9]*a[14] + a[4]*a[10]*a[13] + a[8]*a[5]*a[14] - a[8]*a[6]*a[13] - a[12]*a[5]*a[10] + a[12]*a[6]*a[9];
    inv[1] = -a[1]*a[10]*a[15] + a[1]*a[11]*a[14] + a[9]*a[2]*a[15] - a[9]*a[3]*a[14] - a[13]*a[2]*a[11] + a[13]*a[3]*a[10];
    inv[5] = a[0]*a[10]*a[15] - a[0]*a[11]*a[14] - a[8]*a[2]*a[15] + a[8]*a[3]*a[14] + a[12]*a[2]*a[11] - a[12]*a[3]*a[10];
    inv[9] = -a[0]*a[9]*a[15] + a[0]*a[11]*a[13] + a[8]*a[1]*a[15] - a[8]*a[3]*a[13] - a[12]*a[1]*a[11] + a[12]*a[3]*a[9];
    inv[13] = a[0]*a[9]*a[14] - a[0]*a[10]*a[13] - a[8]*a[1]*a[14] + a[8]*a[2]*a[13] + a[12]*a[1]*a[10] - a[12]*a[2]*a[9];
    inv[2] = a[1]*a[6]*a[15] - a[1]*a[7]*a[14] - a[5]*a[2]*a[15] + a[5]*a[3]*a[14] + a[13]*a[2]*a[7] - a[13]*a[3]*a[6];
    inv[6] = -a[0]*a[6]*a[15] + a[0]*a[7]*a[14] + a[4]*a[2]*a[15] - a[4]*a[3]*a[14] - a[12]*a[2]*a[7] + a[12]*a[3]*a[6];
    inv[10] = a[0]*a[5]*a[15] - a[0]*a[7]*a[13] - a[4]*a[1]*a[15] + a[4]*a[3]*a[13] + a[12]*a[1]*a[7] - a[12]*a[3]*a[5];
    inv[14] = -a[0]*a[5]*a[14] + a[0]*a[6]*a[13] + a[4]*a[1]*a[14] - a[4]*a[2]*a[13] - a[12]*a[1]*a[6] + a[12]*a[2]*a[5];
    inv[3] = -a[1]*a[6]*a[11] + a[1]*a[7]*a[10] + a[5]*a[2]*a[11] - a[5]*a[3]*a[10] - a[9]*a[2]*a[7] + a[9]*a[3]*a[6];
    inv[7] = a[0]*a[6]*a[11] - a[0]*a[7]*a[10] - a[4]*a[2]*a[11] + a[4]*a[3]*a[10] + a[8]*a[2]*a[7] - a[8]*a[3]*a[6];
    inv[11] = -a[0]*a[5]*a[11] + a[0]*a[7]*a[9] + a[4]*a[1]*a[11] - a[4]*a[3]*a[9] - a[8]*a[1]*a[7] + a[8]*a[3]*a[5];
    inv[15] = a[0]*a[5]*a[10] - a[0]*a[6]*a[9] - a[4]*a[1]*a[10] + a[4]*a[2]*a[9] + a[8]*a[1]*a[6] - a[8]*a[2]*a[5];
    det = a[0]*inv[0] + a[1]*inv[4] + a[2]*inv[8] + a[3]*inv[12];
    if (det == 0) return 0;
    for (i = 0; i < 16; i++) r[i] = inv[i] / det;
    return 1;
}

static void one(const float *m, const char *name) {
    float *in = (float *)(g_mem + G_IN), *res = (float *)(g_mem + G_OUT);
    double ref[16];
    int i, bad = 0;
    memcpy(in, m, 64);
    memset(res, 0, 64);
    ref_inverse(m, ref);
    g_fp_cmp = 0; g_fp_cc = 0x4000; g_fp_control_word = 0x027Fu;
    memset(g_fp_stack, 0, sizeof g_fp_stack); g_fp_top = 0;
    g_eax = G_IN; g_esi = G_OUT; g_ecx = 0;
    g_edx = g_ebx = g_edi = 0; g_ebp = g_seh_ebp = 0;
    g_esp = G_SP - 4;
    *(uint32_t *)(g_mem + g_esp) = 0xDEADBEEFu;
    TARGET();
    printf("%s   (fp_top after %d)\n", name, g_fp_top);
    for (i = 0; i < 16; i++) {
        int diff = fabs(res[i] - ref[i]) > 1e-4 * (1.0 + fabs(ref[i]));
        bad |= diff;
        printf("  [%2d] reference %-12g lifted %-12g%s\n", i, ref[i], res[i], diff ? "   <-- DIFF" : "");
    }
    printf("  => %s\n", bad ? "MISMATCH" : "match");
}

int main(void) {
    static const float cam[16] = { 35,0,0,0, 0,35,0,0, 0,0,35,0, 0.5f,-0.5f,623.252f,1 };
    static const float gen[16] = { 0.8f,0.1f,-0.3f,0, -0.2f,0.9f,0.4f,0, 0.35f,-0.25f,1.1f,0, 3,-7,11,1 };
    static const float full[16] = { 2,1,0,1, 0,3,1,0, 1,0,4,2, 1,2,0,5 };
    if (!load()) { printf("load failed\n"); return 2; }
    one(cam, "camera matrix: scale 35, translate (0.5,-0.5,623.252)");
    one(gen, "general affine matrix");
    one(full, "general 4x4 matrix");
    return 0;
}
''')
open(os.path.join(work, "inv.c"), "w").write("\n".join(out))
vcvars = cm._find_vcvars()
runtime_inc = os.path.join(TOOLKIT, "templates", "runtime")
r = cm._cl(vcvars, work, f'/W1 /EHa /I"{runtime_inc}" inv.c /Feinv.exe')
if r.returncode:
    print(r.stdout[-4000:], r.stderr[-2000:])
    sys.exit(1)
print(subprocess.run([os.path.join(work, "inv.exe")], capture_output=True, text=True).stdout)
