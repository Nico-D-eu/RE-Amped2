/**
 * Manual function overrides and ICALL diagnostics
 *
 * This file provides:
 *   - recomp_lookup_manual()  : intercept specific Xbox VAs with hand-written code
 *   - recomp_icall_fail_log() : log when an indirect call target can't be resolved
 *   - ICALL trace ring buffer  : globals used by the RECOMP_ICALL macro
 *
 * The recomp pipeline generates an auto-dispatch table (recomp_lookup) that
 * resolves most function addresses. recomp_lookup_manual() is called FIRST,
 * giving you a chance to override any function with a custom implementation.
 *
 * Common reasons to add manual overrides:
 *   - Trace a function to understand call flow (wrap the generated version)
 *   - Fix a function the lifter translated incorrectly
 *   - Stub out a function that crashes (return early, set eax to a safe value)
 *   - Redirect a function to a native implementation (e.g., skip CRT init)
 *   - Intercept D3D/audio calls for custom rendering or sound
 */

#include <stdio.h>
#include <stdint.h>

/* ── ICALL trace ring buffer ───────────────────────────────── */

/*
 * These globals are written by the RECOMP_ICALL macro (defined in
 * recomp_types.h) every time an indirect call is dispatched. When a
 * crash occurs, the VEH handler or recomp_icall_fail_log() can dump
 * the last 16 call targets to help you trace what happened.
 *
 * The runtime owns them: xbox_kernel defines all three in
 * src/kernel/xbox_memory_layout.c, and recomp_types.h declares them extern.
 * Declare, do not define -- a definition here as well is a duplicate symbol,
 * and a project copied from this template failed to link on all three:
 *
 *   xbox_memory_layout.obj : error LNK2005: g_icall_count already defined
 *                            in recomp_manual.obj
 */
extern volatile uint32_t g_icall_trace[16];
extern volatile uint32_t g_icall_trace_idx;
extern volatile uint64_t g_icall_count;

typedef void (*recomp_func_t)(void);

/* ── Register state (defined in xbox_memory_layout.c) ──────── */

/* The generated runtime header, for the register file (g_eax, g_esp ...),
 * MEM32 and XBOX_PTR. The bare eax/esp aliases exist only under
 * RECOMP_GENERATED_CODE, so hand-written code spells the globals out. It
 * declares the registers
 * RECOMP_TLS, which a hand-written `extern uint32_t g_eax;` here would not:
 * that resolves to the image's TLS template rather than the calling thread's
 * copy, so an override would read and write registers nobody else sees. */
#include <string.h>
#include "recomp/gen/recomp_types.h"

/* ── Diagnostics ───────────────────────────────────────────── */

/*
 * Deep guest backtrace: every stack dword from esp up that is a real return
 * address, meaning the guest code bytes just before it are a call instruction.
 * Guest code is mapped at its own VA, so this is checked directly. It still
 * over-reports (dead frames keep their return addresses), but only with values
 * that genuinely were call sites, which is what makes the chain readable.
 * Much deeper than the runtime's 200-dword exit dump, which the XAPI launch
 * path's on-stack launch-data buffer alone overflows.
 */
extern uint32_t g_xbox_code_lo, g_xbox_code_hi;

static int is_return_address(uint32_t v)
{
    if (v < g_xbox_code_lo + 8 || v >= g_xbox_code_hi)
        return 0;
    if (MEM8(v - 5) == 0xE8)                                    /* call rel32 */
        return 1;
    if (MEM8(v - 2) == 0xFF && ((MEM8(v - 1) >> 3) & 7) == 2)  /* call reg/[reg] */
        return 1;
    if (MEM8(v - 3) == 0xFF && ((MEM8(v - 2) >> 3) & 7) == 2)  /* call [reg+d8] */
        return 1;
    if (MEM8(v - 6) == 0xFF && ((MEM8(v - 5) >> 3) & 7) == 2)  /* call [abs]/[reg+d32] */
        return 1;
    return 0;
}

static void dump_guest_backtrace(const char *why, uint32_t max_dwords)
{
    uint32_t i, shown = 0;

    fprintf(stderr, "[BT] %s: esp=0x%08X eax=%08X ecx=%08X edx=%08X "
            "ebx=%08X esi=%08X edi=%08X\n", why, g_esp, g_eax, g_ecx, g_edx,
            g_ebx, g_esi, g_edi);
    fprintf(stderr, "[BT]   raw:");
    for (i = 0; i < 16; i++)
        fprintf(stderr, " %08X", MEM32(g_esp + i * 4));
    fprintf(stderr, "\n");
    for (i = 0; i < max_dwords && shown < 48; i++) {
        uint32_t a = g_esp + i * 4, v;
        if (a >= 0x04000000u)
            break;
        v = MEM32(a);
        if (is_return_address(v)) {
            fprintf(stderr, "[BT]   [esp+0x%04X] ret 0x%08X\n", i * 4, v);
            shown++;
        }
    }
    fflush(stderr);
}

/*
 * 0x0002B6C0: the title's out-of-memory handler. sub_0002B740 registers it at
 * 0x0038CE1C and 0x003A7B98; the allocator sub_000DC0F0 calls it when its pool
 * returns NULL (esi == 0, edi = the allocator object). It tears the title
 * down and launches d:\Boom.xbe. Wrapped, not replaced: it logs which
 * allocation failed, then does what it always did.
 */
extern void sub_0002B6C0_gen(void);
extern void sub_000F37E0(void);   /* src/lua_probe.c */
extern void sub_000F24C0(void);   /* src/lua_probe.c */

void sub_0002B6C0(void)
{
    uint32_t obj = g_edi;

    dump_guest_backtrace("out-of-memory handler 0x0002B6C0", 4096);
    if (obj && obj < 0x04000000u) {
        uint32_t i, vt = MEM32(obj);
        fprintf(stderr, "[BT]   allocator object 0x%08X vtable 0x%08X:", obj, vt);
        for (i = 0; i < 16; i++)
            fprintf(stderr, " %08X", MEM32(obj + i * 4));
        fprintf(stderr, "\n");
    }
    fflush(stderr);
    sub_0002B6C0_gen();
}

/*
 * Report a Lua error object: the top of a lua_State's stack after a failed
 * protected call. Called from the instrumented sub_000F37E0 in lua_probe.c.
 *
 * Layout, as this build of Lua 5.0 uses it: L->top at +8, L->stack at +0x1C;
 * a stack slot is 12 bytes, { int tt; Value value; } with value at +4; a
 * string (tt 4) points at a TString whose characters follow a 16-byte header,
 * length at +12. All reads are guarded; anything unexpected is dumped raw.
 */
void amped2_report_lua_error(uint32_t L, uint32_t status)
{
    uint32_t top, obj, tt, val, i;

    fprintf(stderr, "[LUA] protected call failed: status %u (1 run, 2 file, "
            "3 syntax, 4 memory, 5 error-in-error), L=0x%08X\n", status, L);
    if (!L || L >= 0x04000000u)
        goto out;
    top = MEM32(L + 8);
    if (!top || top >= 0x04000000u || top < 12)
        goto out;
    obj = top - 12;
    tt = MEM32(obj);
    val = MEM32(obj + 4);
    fprintf(stderr, "[LUA]   top-1 tt=%u value=0x%08X\n", tt, val);
    if (val && val < 0x04000000u) {
        uint32_t len = MEM32(val + 12);
        if (tt == 4 && len && len < 2048) {
            fprintf(stderr, "[LUA]   message (%u bytes): ", len);
            for (i = 0; i < len; i++) {
                uint8_t ch = MEM8(val + 16 + i);
                fputc((ch >= 32 && ch < 127) || ch == '\n' ? ch : '?', stderr);
            }
            fputc('\n', stderr);
        } else {
            fprintf(stderr, "[LUA]   raw at value:");
            for (i = 0; i < 64; i++) {
                uint8_t ch = MEM8(val + i);
                fputc(ch >= 32 && ch < 127 ? ch : '.', stderr);
            }
            fputc('\n', stderr);
        }
    }
    dump_guest_backtrace("failed Lua call", 2048);
out:
    fflush(stderr);
}

/* Called at entry of the instrumented luaD_throw (lua_probe.c). Logs the error
 * object as it stands when the error is raised, which says whether a nil
 * message after the protected call was thrown that way or lost on the way
 * back through setjmp/longjmp, and who raised it. Rate-limited: a title
 * can use errors for control flow. */
void amped2_report_lua_throw(uint32_t L, uint32_t errcode)
{
    static int reported;
    uint32_t top, tt = 0xFFFFFFFFu, val = 0;

    if (reported++ >= 8)
        return;
    top = (L && L < 0x04000000u) ? MEM32(L + 8) : 0;
    if (top >= 12 && top < 0x04000000u) {
        tt = MEM32(top - 12);
        val = MEM32(top - 8);
    }
    fprintf(stderr, "[LUA] throw #%d: errcode %u, L=0x%08X, handler=0x%08X, "
            "top-1 tt=%u value=0x%08X\n", reported, errcode, L,
            L ? MEM32(L + 0x54) : 0, tt, val);
    if (tt == 4 && val && val < 0x04000000u) {
        uint32_t len = MEM32(val + 12), i;
        if (len && len < 2048) {
            fprintf(stderr, "[LUA]   message: ");
            for (i = 0; i < len; i++) {
                uint8_t ch = MEM8(val + 16 + i);
                fputc((ch >= 32 && ch < 127) || ch == '\n' ? ch : '?', stderr);
            }
            fputc('\n', stderr);
        }
    }
    dump_guest_backtrace("luaD_throw", 1024);
}

/* ── Native CRT replacements ───────────────────────────────── */

/*
 * memmove @ 0x00259000 (LIBCMT, named by Ghidra FidDb; 142 callers).
 *
 * The lifted body is unusable: MSVC's memmove dispatches its unaligned heads
 * and tails through jump tables at 0x00259060 and 0x0025915C, and the arms
 * those tables point at (0x002592A4 onwards) sit past the function's recorded
 * end at 0x002592A2, where the disassembler decoded the tables as
 * instructions. Every copy that reaches an arm ends in an unresolved indirect
 * jump -- the first boot logged "[ICALL] Failed to resolve VA 0x002592A4" --
 * and the bytes that arm should have copied are silently skipped.
 *
 * It is a pure function of its arguments, so the host memmove is an exact
 * replacement. cdecl: void *memmove(void *dst, const void *src, size_t n),
 * caller cleans the arguments; on entry [esp] is the return address the
 * lifted call pushed, which `ret` pops.
 *
 * Skipped in codegen by tools\regen.ps1's --exclude-manual, which reads the
 * definition from this file.
 */
void sub_00259000(void)
{
    uint32_t dst = MEM32(g_esp + 4);
    uint32_t src = MEM32(g_esp + 8);
    uint32_t n   = MEM32(g_esp + 12);

    memmove((void *)XBOX_PTR(dst), (const void *)XBOX_PTR(src), n);
    g_eax = dst;
    g_esp += 4; /* ret */
}

/* ── Manual function overrides ─────────────────────────────── */

/*
 * Return a function pointer to override the given Xbox VA, or NULL
 * to fall through to the auto-generated dispatch table.
 *
 * This is called on every indirect call (RECOMP_ICALL) and every
 * direct call through the dispatch table, so keep it fast. A chain
 * of if-statements on uint32_t compiles to a simple comparison
 * sequence; for large override tables, consider a sorted array
 * with binary search.
 *
 * Examples of common override patterns:
 *
 *   // Trace wrapper: log entry/exit around the generated function
 *   extern void sub_00012345(void);
 *   static void traced_sub_00012345(void) {
 *       fprintf(stderr, "[TRACE] sub_00012345 entered, eax=0x%08X\n", g_eax);
 *       sub_00012345();
 *       fprintf(stderr, "[TRACE] sub_00012345 returned, eax=0x%08X\n", g_eax);
 *   }
 *
 *   // Stub: skip a function entirely (return 0 in eax)
 *   static void stub_00067890(void) {
 *       g_eax = 0;
 *   }
 *
 *   // Fix: replace a broken lifted function with correct C
 *   static void fixed_sub_000ABCDE(void) {
 *       // Read arguments from stack/registers per calling convention
 *       uint32_t arg1 = g_ecx;
 *       uint32_t arg2 = MEM32(g_esp + 4);
 *       // ... correct implementation ...
 *       g_eax = result;
 *   }
 */
recomp_func_t recomp_lookup_manual(uint32_t xbox_va)
{
    /*
     * TODO: Add your overrides here. Examples:
     *
     * if (xbox_va == 0x00012345) return traced_sub_00012345;
     * if (xbox_va == 0x00067890) return stub_00067890;
     * if (xbox_va == 0x000ABCDE) return fixed_sub_000ABCDE;
     */

    /* Native CRT replacements (defined above). Answered here so the calls,
     * which the recompiler routes through RECOMP_ICALL_SAFE, resolve without
     * a dispatch-table search. */
    if (xbox_va == 0x00259000) return sub_00259000;  /* memmove */

    /* Wrappers. The generated dispatch table maps a wrapped function's VA to
     * its sub_X_gen body, so a function reached only through a pointer (like
     * the OOM handler below) would skip the wrapper without this. */
    if (xbox_va == 0x0002B6C0) return sub_0002B6C0;  /* OOM handler */

    /* Hand copies in src/lua_probe.c (config/manual_functions.json). */
    if (xbox_va == 0x000F37E0) return sub_000F37E0;  /* lua_pcall-shaped */
    if (xbox_va == 0x000F24C0) return sub_000F24C0;  /* luaD_throw */

    return (recomp_func_t)0;
}

/* ── ICALL failure logging ─────────────────────────────────── */

/*
 * Called when RECOMP_ICALL cannot resolve a target address.
 * This usually means one of:
 *   - A vtable dispatch to an address not in the dispatch table
 *   - A function pointer loaded from uninitialized or corrupt memory
 *   - A kernel thunk address that the bridge doesn't handle
 *
 * During early bring-up you will see many of these. Most are harmless
 * (the ICALL macro pops the dummy return address and continues).
 * Focus on the ones that cause crashes or incorrect behavior.
 */
void recomp_icall_fail_log(uint32_t va)
{
    fprintf(stderr, "[ICALL] Failed to resolve VA 0x%08X (total calls: %llu)\n",
            va, (unsigned long long)g_icall_count);

    /* Dump last 16 call targets from the ring buffer */
    fprintf(stderr, "  Recent ICALL targets:\n");
    for (int i = 0; i < 16; i++) {
        int idx = (g_icall_trace_idx - 16 + i) & 15;
        if (g_icall_trace[idx])
            fprintf(stderr, "    [%2d] 0x%08X\n", i, g_icall_trace[idx]);
    }
    fflush(stderr);
}

/* An indirect call whose target is not code: a null or wild function pointer.
 *
 * Skipping these is right -- calling a data address is worse -- but skipping
 * them *silently* is not. They almost always arrive inside a loop, so the
 * symptom is a hang with no output rather than a diagnosable null vtable call.
 *
 * Rate-limited per address: a spin can produce millions of these, and the
 * useful information is which addresses occur, not how often.
 */
void recomp_icall_not_code_log(uint32_t va)
{
    enum { SLOTS = 16 };
    static uint32_t seen[SLOTS];
    static uint64_t hits[SLOTS];
    static int count;
    int i;

    for (i = 0; i < count; i++)
        if (seen[i] == va)
            break;
    if (i == count) {
        if (count == SLOTS)
            return;
        seen[count] = va;
        hits[count] = 0;
        count++;
    }
    hits[i]++;
    /* Report at 1, 10, 100, 1000 ... rather than once. A single line says a
     * wild pointer was skipped; the progression says it is being skipped in a
     * loop, which is the difference between a curiosity and the reason the
     * title is hung. */
    {
        uint64_t n = hits[i];
        while (n >= 10 && n % 10 == 0)
            n /= 10;
        if (n != 1)
            return;
    }
    fprintf(stderr, "[ICALL] target 0x%08X is not code -- skipped %llu time(s) "
                    "(null or wild function pointer, at call #%llu)\n",
            va, (unsigned long long)hits[i],
            (unsigned long long)g_icall_count);
    fflush(stderr);
}

/* ── Untranslated instructions ───────────────────────────────────────────
 *
 * The lifter emits RECOMP_UNIMPL(text, va) at every instruction it has no
 * translation for, in place of the bare comment it used to leave. The
 * instruction is still a no-op; this only stops the omission being silent.
 * RECOMP_UNIMPL_TRAP=1 aborts at the first hit, at the guest address of the
 * cause rather than wherever the damage surfaces. */
#include <stdlib.h>

void recomp_unimpl(const char *text, uint32_t va)
{
    static int printed;
    const char *trap = getenv("RECOMP_UNIMPL_TRAP");
    int stop = trap && *trap && *trap != '0';

    if (printed < 50 || stop) {
        printed++;
        fprintf(stderr,
                "[UNIMPL] untranslated instruction REACHED: `%s` at 0x%08X"
                " (a no-op; set RECOMP_UNIMPL_TRAP=1 to stop here)\n",
                text, va);
        fflush(stderr);
    }
    if (stop) abort();
}
