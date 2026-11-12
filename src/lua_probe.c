/**
 * Hand-maintained copies of generated functions, instrumented.
 *
 * Written in the generated code's own dialect (register aliases, PUSH32/MEM32,
 * CMP_* flag helpers), which is why this lives outside recomp_manual.c: those
 * aliases exist only under RECOMP_GENERATED_CODE. Each function here is listed
 * in config/manual_functions.json so the recompiler declares it and routes
 * its callers through the manual lookup instead of generating a body, and is
 * registered in recomp_lookup_manual().
 *
 * Keep the bodies byte-for-byte what the recompiler emits, plus the probe.
 */

#define RECOMP_GENERATED_CODE
#include "recomp/gen/recomp_funcs.h"
/* No CRT headers here: recomp_funcs.h declares guest functions under the
 * names Ghidra recovered (flushall, ...), which collide with <stdio.h>.
 * Anything that needs the CRT lives in recomp_manual.c. */

extern void amped2_report_lua_error(uint32_t L, uint32_t status);
#define report_lua_error amped2_report_lua_error

/* 0x00150E80: the movie player's "next frame" call. It wraps
 * XMVDecoder_GetNextFrame (sub_002CDE60), with ecx = &result, edx = decoder,
 * one stack arg = target surface. The loop in sub_00150FF0 presents frames
 * until result is 2 (end of file) or 3 (failure).
 *
 * XMV paces video on D3D's vblank count and starts on an even field. Until
 * the toolkit delivered both (2026-10-02: vblank held until acknowledged,
 * the field pin at port 0x80C0) the decoder answered "no frame yet" (0)
 * forever and boot stopped on the MGS logo. Movies now play by default.
 * AMPED2_PLAY_MOVIES=0 (checked in main.c) skips them: the decode still
 * runs, then the result reads as end of file. */
extern int g_amped2_skip_movies;

void sub_00150E80(void)
{
    uint32_t result_ptr = ecx;                    /* probe: not in the original */
    int _flags = 0; /* fallback flag var */
    uint32_t _fa = 0, _fb = 0;
    int32_t _fas = 0, _fbs = 0;
    (void)_fa; (void)_fb; (void)_fas; (void)_fbs; (void)_flags;

loc_00150E80: ;
    PUSH32(esp, eax);
    eax = MEM32(esp + 8);
    PUSH32(esp, ecx);
    PUSH32(esp, edx);
    PUSH32(esp, eax);
    PUSH32(esp, 0x00150E8Du); RECOMP_ABI_CALL(0x002CDE60u, sub_002CDE60); /* call 0x002CDE60 */

loc_00150E8D: ;
    if (g_amped2_skip_movies && result_ptr)       /* probe: not in the original */
        MEM32(result_ptr) = 2;                    /* XMV_ENDOFFILE */
    esp += 8; return; /* ret 4 */
}

/* 0x000F24C0: luaD_throw(L = eax, errcode = edx). Stores errcode in
 * L->errorJmp->status (+0x54 -> +0x44) and longjmps to it; with no handler it
 * calls the panic function and aborts. Probe: the error object at the moment
 * of the throw, and who threw it. */
extern void amped2_report_lua_throw(uint32_t L, uint32_t errcode);

void sub_000F24C0(void)
{
    int _flags = 0; /* fallback flag var */
    uint32_t _fa = 0, _fb = 0;
    int32_t _fas = 0, _fbs = 0;
    (void)_fa; (void)_fb; (void)_fas; (void)_fbs; (void)_flags;

    amped2_report_lua_throw(eax, edx);            /* probe: not in the original */

loc_000F24C0: ;
    ecx = MEM32(eax + 0x54);
    _fa = (uint32_t)(ecx) & 0xFFFFFFFFu; _fb = (uint32_t)(0) & 0xFFFFFFFFu;
    _fas = (int32_t)(int32_t)(_fa); _fbs = (int32_t)(int32_t)(_fb); /* cmp ecx, 0 (32-bit) */
    if (CMP_EQ(_fa, _fb)) goto loc_000F24D8; /* je: equal / zero */

loc_000F24C7: ;
    MEM32(ecx + 0x44) = edx;
    eax = MEM32(eax + 0x54);
    PUSH32(esp, 1);
    _fb = (uint32_t)(4) & 0xFFFFFFFFu; _fbs = (int32_t)(int32_t)(_fb); /* add source, before the write */
    eax = eax + 4;
    _fa = (uint32_t)(eax) & 0xFFFFFFFFu; _fas = (int32_t)(int32_t)(_fa); /* add result */
    PUSH32(esp, eax);
    if (!recomp_guest_longjmp(MEM32(esp), MEM32(esp + 4))) { PUSH32(esp, 0x000F24D8u); sub_0025B8FC(); } /* longjmp; sub_ name pinned in recomp_manual.c */

loc_000F24D8: ;
    ecx = MEM32(eax + 0x10);
    { uint32_t _icall_esp = g_esp;
    PUSH32(esp, eax);
    { uint32_t _icall_target = MEM32(ecx + 0x28); PUSH32(esp, 0x000F24DFu); RECOMP_ICALL_SAFE_AT(_icall_target, _icall_esp, 0x000F24DCu); } /* indirect call */
    }

loc_000F24DF: ;
    _fb = (uint32_t)(4) & 0xFFFFFFFFu; _fbs = (int32_t)(int32_t)(_fb); /* add source, before the write */
    esp = esp + 4;
    _fa = (uint32_t)(esp) & 0xFFFFFFFFu; _fas = (int32_t)(int32_t)(_fa); /* add result */
    PUSH32(esp, 1);
    PUSH32(esp, 0x000F24E9u); RECOMP_ABI_CALL(0x0025B540u, sub_0025B540); /* call 0x0025B540 */

loc_000F24E9: ;
    (void)0;
}

/* 0x000F37E0: lua_pcall-shaped. eax = incoming status (0 = run it),
 * ecx = lua_State. Runs callback 0x000EDCF0 under sub_000F2DC0 (the protected
 * runner) and returns its status. sub_0014ED70 treats anything but 0 -- or a
 * retryable 2 -- as fatal and launches d:\Boom.xbe. */
void sub_000F37E0(void)
{
    int _flags = 0; /* fallback flag var */
    uint32_t _fa = 0, _fb = 0;
    int32_t _fas = 0, _fbs = 0;
    (void)_fa; (void)_fb; (void)_fas; (void)_fbs; (void)_flags;

loc_000F37E0: ;
    _fb = (uint32_t)(0x10) & 0xFFFFFFFFu; _fbs = (int32_t)(int32_t)(_fb); /* sub source, before the write */
    esp = esp - 0x10;
    _fa = (uint32_t)(esp) & 0xFFFFFFFFu; _fas = (int32_t)(int32_t)(_fa); /* sub result */
    PUSH32(esp, ebx);
    PUSH32(esp, esi);
    ebx = eax;
    _fa = (uint32_t)(ebx) & 0xFFFFFFFFu; _fb = (uint32_t)(0) & 0xFFFFFFFFu;
    _fas = (int32_t)(int32_t)(_fa); _fbs = (int32_t)(int32_t)(_fb); /* cmp ebx, 0 (32-bit) */
    PUSH32(esp, edi);
    esi = ecx;
    if (CMP_NE(_fa, _fb)) goto loc_000F381B; /* jne: not equal / not zero */

loc_000F37EE: ;
    eax = MEM32(esi + 8);
    ecx = MEM32(esi + 0x1C);
    _fb = (uint32_t)(0xC) & 0xFFFFFFFFu; _fbs = (int32_t)(int32_t)(_fb); /* sub source, before the write */
    eax = eax - 0xC;
    _fa = (uint32_t)(eax) & 0xFFFFFFFFu; _fas = (int32_t)(int32_t)(_fa); /* sub result */
    MEM32(esp + 0x10) = eax;
    PUSH32(esp, ebx);
    _fb = (uint32_t)(ecx) & 0xFFFFFFFFu; _fbs = (int32_t)(int32_t)(_fb); /* sub source, before the write */
    eax = eax - ecx;
    _fa = (uint32_t)(eax) & 0xFFFFFFFFu; _fas = (int32_t)(int32_t)(_fa); /* sub result */
    PUSH32(esp, eax);
    eax = esp + 0x18;
    PUSH32(esp, eax);
    PUSH32(esp, 0xEDCF0);
    MEM32(esp + 0x24) = 0xFFFFFFFFu;
    PUSH32(esp, 0x000F3816u); RECOMP_ABI_CALL(0x000F2DC0u, sub_000F2DC0); /* call 0x000F2DC0 */

loc_000F3816: ;
    _fb = (uint32_t)(0x10) & 0xFFFFFFFFu; _fbs = (int32_t)(int32_t)(_fb); /* add source, before the write */
    esp = esp + 0x10;
    _fa = (uint32_t)(esp) & 0xFFFFFFFFu; _fas = (int32_t)(int32_t)(_fa); /* add result */
    ebx = eax;

loc_000F381B: ;
    eax = ebx;
    edi = esi;
    PUSH32(esp, 0x000F3824u); RECOMP_ABI_CALL(0x000F36C0u, sub_000F36C0); /* call 0x000F36C0 */

loc_000F3824: ;
    if (ebx)                                  /* probe: not in the original */
        report_lua_error(esi, ebx);
    POP32(esp, edi);
    POP32(esp, esi);
    eax = ebx;
    POP32(esp, ebx);
    _fb = (uint32_t)(0x10) & 0xFFFFFFFFu; _fbs = (int32_t)(int32_t)(_fb); /* add source, before the write */
    esp = esp + 0x10;
    _fa = (uint32_t)(esp) & 0xFFFFFFFFu; _fas = (int32_t)(int32_t)(_fa); /* add result */
    esp += 4; return; /* ret */

}

/* 0x000B1E20: the string-table lookup (thiscall-shaped, ecx unused here;
 * eax = the key String's address, stack: the table [0x0038CDF4], the out
 * String; "Pkg.Key" looks in package Pkg, `ret 8`). Every on-screen text key goes through it,
 * the Pro and photo-shoot intro cards (PreRun, filled natively around
 * 0x0004C435-0x0004D876) included. Probe: while a developer challenge runs,
 * amped2_devchal_key may hand it another key's String instead (the card's
 * title, the developer's name, the banter line; see recomp_manual.c). The
 * body copies the key into its own slot (sub_00012290) and releases that. */
extern uint32_t amped2_devchal_key(uint32_t key);

void sub_000B1E20(void)
{
    uint32_t ebp = 0;
    ebp = g_ebp;  /* frameless: caller's frame */
    int _flags = 0; /* fallback flag var */
    uint32_t _fa = 0, _fb = 0;
    int32_t _fas = 0, _fbs = 0;
    (void)_fa; (void)_fb; (void)_fas; (void)_fbs;
    ebp = g_seh_ebp; /* fpo_leaf: inherit caller's frame */

    eax = amped2_devchal_key(eax);                /* probe: not in the original */

loc_000B1E20: ;
    _fb = (uint32_t)(0x10) & 0xFFFFFFFFu; _fbs = (int32_t)(int32_t)(_fb); /* sub source, before the write */
    esp = esp - 0x10;
    _fa = (uint32_t)(esp) & 0xFFFFFFFFu; _fas = (int32_t)(int32_t)(_fa); /* sub result */
    PUSH32(esp, ebx);
    PUSH32(esp, ebp);
    ebp = MEM32(esp + 0x20);
    PUSH32(esp, esi);
    PUSH32(esp, edi);
    esi = esp + 0x28;
    edi = ecx;
    PUSH32(esp, 0x000B1E36u); RECOMP_ABI_CALL(0x00012290u, sub_00012290); /* call 0x00012290 */

loc_000B1E36: ;
    esi = MEM32(esp + 0x28);
    PUSH32(esp, 0x2E);
    PUSH32(esp, esi);
    PUSH32(esp, 0x000B1E42u); RECOMP_ABI_CALL(0x002594C0u, strrchr_002594C0); /* call 0x002594C0 */

loc_000B1E42: ;
    _fb = (uint32_t)(8) & 0xFFFFFFFFu; _fbs = (int32_t)(int32_t)(_fb); /* add source, before the write */
    esp = esp + 8;
    _fa = (uint32_t)(esp) & 0xFFFFFFFFu; _fas = (int32_t)(int32_t)(_fa); /* add result */
    _fa = (uint32_t)(eax) & 0xFFFFFFFFu; _fb = (uint32_t)(0) & 0xFFFFFFFFu;
    _fas = (int32_t)(int32_t)(_fa); _fbs = (int32_t)(int32_t)(_fb); /* cmp eax, 0 (32-bit) */
    if (CMP_EQ(_fa, _fb)) goto loc_000B1EFC; /* je: equal / zero */

loc_000B1E4D: ;
    _fb = (uint32_t)(esi) & 0xFFFFFFFFu; _fbs = (int32_t)(int32_t)(_fb); /* sub source, before the write */
    eax = eax - esi;
    _fa = (uint32_t)(eax) & 0xFFFFFFFFu; _fas = (int32_t)(int32_t)(_fa); /* sub result */
    esi = eax;
    _fa = (uint32_t)(esi) & 0xFFFFFFFFu; _fb = (uint32_t)(0xFFFFFFFFu) & 0xFFFFFFFFu;
    _fas = (int32_t)(int32_t)(_fa); _fbs = (int32_t)(int32_t)(_fb); /* cmp esi, 0xFFFFFFFFu (32-bit) */
    if (CMP_EQ(_fa, _fb)) goto loc_000B1EFC; /* je: equal / zero */

loc_000B1E5A: ;
    ecx = esi;
    ebx = esp + 0x10;
    eax = esp + 0x28;
    PUSH32(esp, 0x000B1E69u); RECOMP_ABI_CALL(0x0001A340u, sub_0001A340); /* call 0x0001A340 */

loc_000B1E69: ;
    edx = esi + 1;
    ecx = esp + 0x14;
    eax = esp + 0x28;
    PUSH32(esp, 0x000B1E79u); RECOMP_ABI_CALL(0x0001B630u, sub_0001B630); /* call 0x0001B630 */

loc_000B1E79: ;
    ebx = esp + 0x28;
    PUSH32(esp, 0x000B1E82u); RECOMP_ABI_CALL(0x00013800u, sub_00013800); /* call 0x00013800 */

loc_000B1E82: ;
    ecx = esp + 0x14;
    PUSH32(esp, 0x000B1E8Bu); RECOMP_ABI_CALL(0x0001A490u, sub_0001A490); /* call 0x0001A490 */

loc_000B1E8B: ;
    edx = MEM32(esp + 0x24);
    eax = esp + 0x24;
    PUSH32(esp, eax);
    ecx = esp + 0x14;
    PUSH32(esp, ecx);
    _fb = (uint32_t)(0x1434) & 0xFFFFFFFFu; _fbs = (int32_t)(int32_t)(_fb); /* add source, before the write */
    edx = edx + 0x1434;
    _fa = (uint32_t)(edx) & 0xFFFFFFFFu; _fas = (int32_t)(int32_t)(_fa); /* add result */
    eax = esp + 0x1C;
    ecx = esp + 0x20;
    PUSH32(esp, 0x000B1EACu); RECOMP_ABI_CALL(0x000B2990u, sub_000B2990); /* call 0x000B2990 */

loc_000B1EAC: ;
    _fa = (uint32_t)(eax) & 0xFFFFFFFFu; _fb = (uint32_t)(0) & 0xFFFFFFFFu;
    _fas = (int32_t)(int32_t)(_fa); _fbs = (int32_t)(int32_t)(_fb); /* cmp eax, 0 (32-bit) */
    if (CMP_NE(_fa, _fb)) goto loc_000B1ECE; /* jne: not equal / not zero */

loc_000B1EB0: ;
    ecx = esp + 0x10;
    PUSH32(esp, 0x000B1EB9u); RECOMP_ABI_CALL(0x0001A490u, sub_0001A490); /* call 0x0001A490 */

loc_000B1EB9: ;
    ecx = esp + 0x28;
    PUSH32(esp, 0x000B1EC2u); RECOMP_ABI_CALL(0x0001A490u, sub_0001A490); /* call 0x0001A490 */

loc_000B1EC2: ;
    POP32(esp, edi);
    POP32(esp, esi);
    POP32(esp, ebp);
    SET_LO8(eax, 0); /* xor self */
    _fa = (uint32_t)(LO8(eax)) & 0xFFu; _fas = (int32_t)(int8_t)(_fa); /* xor result */
    POP32(esp, ebx);
    _fb = (uint32_t)(0x10) & 0xFFFFFFFFu; _fbs = (int32_t)(int32_t)(_fb); /* add source, before the write */
    esp = esp + 0x10;
    _fa = (uint32_t)(esp) & 0xFFFFFFFFu; _fas = (int32_t)(int32_t)(_fa); /* add result */
    esp += 12; return; /* ret 8 */

loc_000B1ECE: ;
    eax = MEM32(eax + 4);
    PUSH32(esp, ebp);
    PUSH32(esp, eax);
    eax = esp + 0x30;
    PUSH32(esp, 0x000B1EDCu); RECOMP_ABI_CALL(0x000B4A90u, sub_000B4A90); /* call 0x000B4A90 */

loc_000B1EDC: ;
    ecx = esp + 0x10;
    SET_LO8(ebx, LO8(eax));
    PUSH32(esp, 0x000B1EE7u); RECOMP_ABI_CALL(0x0001A490u, sub_0001A490); /* call 0x0001A490 */

loc_000B1EE7: ;
    ecx = esp + 0x28;
    PUSH32(esp, 0x000B1EF0u); RECOMP_ABI_CALL(0x0001A490u, sub_0001A490); /* call 0x0001A490 */

loc_000B1EF0: ;
    POP32(esp, edi);
    POP32(esp, esi);
    POP32(esp, ebp);
    SET_LO8(eax, LO8(ebx));
    POP32(esp, ebx);
    _fb = (uint32_t)(0x10) & 0xFFFFFFFFu; _fbs = (int32_t)(int32_t)(_fb); /* add source, before the write */
    esp = esp + 0x10;
    _fa = (uint32_t)(esp) & 0xFFFFFFFFu; _fas = (int32_t)(int32_t)(_fa); /* add result */
    esp += 12; return; /* ret 8 */

loc_000B1EFC: ;
    _fa = (uint32_t)(edi) & 0xFFFFFFFFu; _fb = (uint32_t)(0) & 0xFFFFFFFFu;
    _fas = (int32_t)(int32_t)(_fa); _fbs = (int32_t)(int32_t)(_fb); /* cmp edi, 0 (32-bit) */
    if (CMP_EQ(_fa, _fb)) goto loc_000B1F43; /* je: equal / zero */

loc_000B1F00: ;
    edi = MEM32(edi + 0xB8);
    _fa = (uint32_t)(edi) & 0xFFFFFFFFu; _fb = (uint32_t)(0) & 0xFFFFFFFFu;
    _fas = (int32_t)(int32_t)(_fa); _fbs = (int32_t)(int32_t)(_fb); /* cmp edi, 0 (32-bit) */
    if (CMP_EQ(_fa, _fb)) goto loc_000B1F43; /* je: equal / zero */

loc_000B1F0A: ;
    /* nop */

loc_000B1F10: ;
    esi = MEM32(edi + 0x144);
    _fa = (uint32_t)(esi) & 0xFFFFFFFFu; _fb = (uint32_t)(0) & 0xFFFFFFFFu;
    _fas = (int32_t)(int32_t)(_fa); _fbs = (int32_t)(int32_t)(_fb); /* cmp esi, 0 (32-bit) */
    if (CMP_EQ(_fa, _fb)) goto loc_000B1F3C; /* je: equal / zero */

loc_000B1F1A: ;
    /* nop */

loc_000B1F20: ;
    eax = MEM32(esi + 8);
    PUSH32(esp, ebp);
    PUSH32(esp, eax);
    eax = esp + 0x30;
    PUSH32(esp, 0x000B1F2Eu); RECOMP_ABI_CALL(0x000B4A90u, sub_000B4A90); /* call 0x000B4A90 */

loc_000B1F2E: ;
    _fa = (uint32_t)(LO8(eax)) & 0xFFu; _fb = (uint32_t)(0) & 0xFFu;
    _fas = (int32_t)(int8_t)(_fa); _fbs = (int32_t)(int8_t)(_fb); /* cmp LO8(eax), 0 (8-bit) */
    if (CMP_NE(_fa, _fb)) goto loc_000B2001; /* jne: not equal / not zero */

loc_000B1F36: ;
    esi = MEM32(esi);
    _fa = (uint32_t)(esi) & 0xFFFFFFFFu; _fb = (uint32_t)(0) & 0xFFFFFFFFu;
    _fas = (int32_t)(int32_t)(_fa); _fbs = (int32_t)(int32_t)(_fb); /* cmp esi, 0 (32-bit) */
    if (CMP_NE(_fa, _fb)) goto loc_000B1F20; /* jne: not equal / not zero */

loc_000B1F3C: ;
    edi = MEM32(edi + 0x14);
    _fa = (uint32_t)(edi) & 0xFFFFFFFFu; _fb = (uint32_t)(0) & 0xFFFFFFFFu;
    _fas = (int32_t)(int32_t)(_fa); _fbs = (int32_t)(int32_t)(_fb); /* cmp edi, 0 (32-bit) */
    if (CMP_NE(_fa, _fb)) goto loc_000B1F10; /* jne: not equal / not zero */

loc_000B1F43: ;
    edx = esp + 0x10;
    PUSH32(esp, edx);
    eax = 0x344D84;
    PUSH32(esp, 0x000B1F52u); RECOMP_ABI_CALL(0x000122B0u, sub_000122B0); /* call 0x000122B0 */

loc_000B1F52: ;
    edi = MEM32(esp + 0x24);
    eax = esp + 0x24;
    PUSH32(esp, eax);
    ecx = esp + 0x14;
    PUSH32(esp, ecx);
    edx = edi + 0x1434;
    eax = esp + 0x20;
    ecx = esp + 0x1C;
    PUSH32(esp, 0x000B1F73u); RECOMP_ABI_CALL(0x000B2990u, sub_000B2990); /* call 0x000B2990 */

loc_000B1F73: ;
    ecx = esp + 0x10;
    esi = eax;
    PUSH32(esp, 0x000B1F7Eu); RECOMP_ABI_CALL(0x0001A490u, sub_0001A490); /* call 0x0001A490 */

loc_000B1F7E: ;
    _fa = (uint32_t)(esi) & 0xFFFFFFFFu; _fb = (uint32_t)(0) & 0xFFFFFFFFu;
    _fas = (int32_t)(int32_t)(_fa); _fbs = (int32_t)(int32_t)(_fb); /* cmp esi, 0 (32-bit) */
    if (CMP_EQ(_fa, _fb)) goto loc_000B1FA7; /* je: equal / zero */

loc_000B1F82: ;
    esi = MEM32(esi + 4);
    PUSH32(esp, ebp);
    PUSH32(esp, esi);
    eax = esp + 0x30;
    PUSH32(esp, 0x000B1F90u); RECOMP_ABI_CALL(0x000B4A90u, sub_000B4A90); /* call 0x000B4A90 */

loc_000B1F90: ;
    ecx = esp + 0x28;
    SET_LO8(ebx, LO8(eax));
    PUSH32(esp, 0x000B1F9Bu); RECOMP_ABI_CALL(0x0001A490u, sub_0001A490); /* call 0x0001A490 */

loc_000B1F9B: ;
    POP32(esp, edi);
    POP32(esp, esi);
    POP32(esp, ebp);
    SET_LO8(eax, LO8(ebx));
    POP32(esp, ebx);
    _fb = (uint32_t)(0x10) & 0xFFFFFFFFu; _fbs = (int32_t)(int32_t)(_fb); /* add source, before the write */
    esp = esp + 0x10;
    _fa = (uint32_t)(esp) & 0xFFFFFFFFu; _fas = (int32_t)(int32_t)(_fa); /* add result */
    esp += 12; return; /* ret 8 */

loc_000B1FA7: ;
    esi = edi + 0x12F0;
    ecx = esi;
    PUSH32(esp, 0x000B1FB4u); RECOMP_ABI_CALL(0x001B2B00u, sub_001B2B00); /* call 0x001B2B00 */

loc_000B1FB4: ;
    MEM32(esp + 0x18) = eax;
    MEM32(esp + 0x1C) = esi;
    /* nop */

loc_000B1FC0: ;
    _fa = (uint32_t)(eax) & 0xFFFFFFFFu; _fb = (uint32_t)(0) & 0xFFFFFFFFu;
    _fas = (int32_t)(int32_t)(_fa); _fbs = (int32_t)(int32_t)(_fb); /* cmp eax, 0 (32-bit) */
    if (CMP_EQ(_fa, _fb)) goto loc_000B1EB9; /* je: equal / zero */

loc_000B1FC8: ;
    eax = MEM32(eax + 4);
    esi = MEM32(eax + 0x144);
    _fa = (uint32_t)(esi) & 0xFFFFFFFFu; _fb = (uint32_t)(0) & 0xFFFFFFFFu;
    _fas = (int32_t)(int32_t)(_fa); _fbs = (int32_t)(int32_t)(_fb); /* cmp esi, 0 (32-bit) */
    if (CMP_EQ(_fa, _fb)) goto loc_000B1FED; /* je: equal / zero */

loc_000B1FD5: ;
    eax = MEM32(esi + 8);
    PUSH32(esp, ebp);
    PUSH32(esp, eax);
    eax = esp + 0x30;
    PUSH32(esp, 0x000B1FE3u); RECOMP_ABI_CALL(0x000B4A90u, sub_000B4A90); /* call 0x000B4A90 */

loc_000B1FE3: ;
    _fa = (uint32_t)(LO8(eax)) & 0xFFu; _fb = (uint32_t)(0) & 0xFFu;
    _fas = (int32_t)(int8_t)(_fa); _fbs = (int32_t)(int8_t)(_fb); /* cmp LO8(eax), 0 (8-bit) */
    if (CMP_NE(_fa, _fb)) goto loc_000B2001; /* jne: not equal / not zero */

loc_000B1FE7: ;
    esi = MEM32(esi);
    _fa = (uint32_t)(esi) & 0xFFFFFFFFu; _fb = (uint32_t)(0) & 0xFFFFFFFFu;
    _fas = (int32_t)(int32_t)(_fa); _fbs = (int32_t)(int32_t)(_fb); /* cmp esi, 0 (32-bit) */
    if (CMP_NE(_fa, _fb)) goto loc_000B1FD5; /* jne: not equal / not zero */

loc_000B1FED: ;
    ebx = MEM32(esp + 0x1C);
    edx = esp + 0x18;
    PUSH32(esp, edx);
    PUSH32(esp, 0x000B1FFBu); RECOMP_ABI_CALL(0x000B2450u, sub_000B2450); /* call 0x000B2450 */

loc_000B1FFB: ;
    eax = MEM32(esp + 0x18);
    goto loc_000B1FC0;

loc_000B2001: ;
    ecx = esp + 0x28;
    PUSH32(esp, 0x000B200Au); RECOMP_ABI_CALL(0x0001A490u, sub_0001A490); /* call 0x0001A490 */

loc_000B200A: ;
    POP32(esp, edi);
    POP32(esp, esi);
    POP32(esp, ebp);
    SET_LO8(eax, 1);
    POP32(esp, ebx);
    _fb = (uint32_t)(0x10) & 0xFFFFFFFFu; _fbs = (int32_t)(int32_t)(_fb); /* add source, before the write */
    esp = esp + 0x10;
    _fa = (uint32_t)(esp) & 0xFFFFFFFFu; _fas = (int32_t)(int32_t)(_fa); /* add result */
    esp += 12; return; /* ret 8 */

}
