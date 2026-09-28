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
    if (!recomp_guest_longjmp(MEM32(esp), MEM32(esp + 4))) { PUSH32(esp, 0x000F24D8u); longjmp_0025B8FC(); } /* longjmp 0x0025B8FC */

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
