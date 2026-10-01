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

/* printf to stderr for a probe pasted into generated code, which cannot
 * include stdio.h (the Ghidra-named declarations collide with the CRT's). */
#include <stdarg.h>
#include <stdlib.h>
void amped2_diag(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    va_end(ap);
    fflush(stderr);
}

/* Timestamped event, for probes pasted into generated code: milliseconds
 * since the first event, the host thread, a tag and three values. */
__declspec(dllimport) unsigned long __stdcall GetCurrentThreadId(void);
__declspec(dllimport) int __stdcall QueryPerformanceCounter(long long *);
__declspec(dllimport) int __stdcall QueryPerformanceFrequency(long long *);
__declspec(dllimport) unsigned long __stdcall GetTickCount(void);
__declspec(dllimport) void __stdcall Sleep(unsigned long);
void amped2_race(const char *tag, uint32_t a, uint32_t b, uint32_t c)
{
    static long long f, t0;
    long long now;
    if (!f) {
        QueryPerformanceFrequency(&f);
        QueryPerformanceCounter(&t0);
    }
    QueryPerformanceCounter(&now);
    fprintf(stderr, "[RACE] %9.3f ms t%-6lu %s %08X %08X %08X\n",
            (double)(now - t0) * 1000.0 / (double)f, GetCurrentThreadId(), tag, a, b, c);
    fflush(stderr);
}

/* Object lifetimes through the game's operator new/delete (sub_0002CFD0 /
 * sub_0002D040), by the caller of new: which call sites keep objects alive.
 * Paste amped2_new_probe(eax, MEM32(esp + 0xC), MEM32(esp + 0x10),
 * MEM32(esp + 8)) at sub_0002CFD0's loc_0002D02C, and
 * amped2_delete_probe(MEM32(esp + 4), MEM32(esp)) at loc_0002D040.
 * Every 20000 news the callers holding the most live objects are listed. */
#define LIVE_SLOTS (1u << 20)
#define SITE_SLOTS 2048
static struct { uint32_t ptr; uint16_t site; } s_live[LIVE_SLOTS];
static struct { uint32_t ret, news, deletes, bytes, flags; } s_site[SITE_SLOTS];
static uint32_t s_news, s_deletes, s_unknown_deletes;
long _InterlockedExchange(long volatile *, long);
void _mm_pause(void);
#pragma intrinsic(_InterlockedExchange, _mm_pause)
static volatile long s_live_lock;

static void live_lock(void)   { while (_InterlockedExchange(&s_live_lock, 1)) _mm_pause(); }
static void live_unlock(void) { _InterlockedExchange(&s_live_lock, 0); }

static void live_report(void)
{
    uint32_t order[16] = {0}, i, k;
    for (i = 1; i < SITE_SLOTS; i++) {
        uint32_t live = s_site[i].news - s_site[i].deletes;
        if (!s_site[i].ret)
            continue;
        for (k = 0; k < 16; k++) {
            uint32_t o = order[k];
            if (!o || live > s_site[o].news - s_site[o].deletes) {
                memmove(&order[k + 1], &order[k], (15 - k) * sizeof order[0]);
                order[k] = i;
                break;
            }
        }
    }
    /* XACT sound cues (new at 0x0031005C): what the live ones are waiting
     * on -- refcount (+0x34), flags (+0x38), and the state (+0x30) of each
     * of the three track slots (+0x28/+0x2C/+0x30, 0 = empty). */
    {
        static struct { uint32_t key[5], count; } h[32];
        uint32_t n = 0, j, t;
        memset(h, 0, sizeof h);
        for (j = 0; j < LIVE_SLOTS; j++) {
            uint32_t p = s_live[j].ptr, key[5];
            if (!p || p == 0xFFFFFFFFu || s_site[s_live[j].site].ret != 0x0031005Cu)
                continue;
            key[0] = MEM32(p + 0x34);
            key[1] = MEM16(p + 0x38);
            for (t = 0; t < 3; t++) {
                uint32_t tr = MEM32(p + 0x28 + t * 4);
                key[2 + t] = tr ? 0x10000u | MEM16(tr + 0x30) : 0;
            }
            for (t = 0; t < 32; t++)
                if (!h[t].count || !memcmp(h[t].key, key, sizeof key)) {
                    memcpy(h[t].key, key, sizeof key);
                    h[t].count++;
                    break;
                }
            n++;
        }
        fprintf(stderr, "[LIVE] %u live XACT cues by (refs, flags, track states):\n", n);
        for (t = 0; t < 32 && h[t].count; t++)
            fprintf(stderr, "[LIVE]   refs %u flags %04X tracks %05X %05X %05X: %u\n",
                    h[t].key[0], h[t].key[1], h[t].key[2], h[t].key[3], h[t].key[4], h[t].count);
    }
    fprintf(stderr, "[LIVE] %u news, %u deletes (%u of unknown objects); top live by caller of new:\n",
            s_news, s_deletes, s_unknown_deletes);
    for (k = 0; k < 16 && order[k]; k++) {
        i = order[k];
        fprintf(stderr, "[LIVE]   ret 0x%08X flags %08X: %u new, %u deleted, %u live, %u bytes total\n",
                s_site[i].ret, s_site[i].flags, s_site[i].news, s_site[i].deletes,
                s_site[i].news - s_site[i].deletes, s_site[i].bytes);
    }
    fflush(stderr);
}

void amped2_new_probe(uint32_t ptr, uint32_t size, uint32_t flags, uint32_t ret)
{
    uint32_t i, k, site = 0;
    if (!ptr)
        return;
    live_lock();
    for (i = (ret * 2654435761u) & (SITE_SLOTS - 1), k = 0; k < SITE_SLOTS; k++, i = (i + 1) & (SITE_SLOTS - 1)) {
        if (!i) continue;
        if (s_site[i].ret == ret || !s_site[i].ret) {
            s_site[i].ret = ret;
            site = i;
            break;
        }
    }
    if (site) {
        s_site[site].news++;
        s_site[site].bytes += size;
        s_site[site].flags = flags;
        for (i = (ptr >> 3) & (LIVE_SLOTS - 1), k = 0; k < 256; k++, i = (i + 1) & (LIVE_SLOTS - 1))
            if (!s_live[i].ptr || s_live[i].ptr == 0xFFFFFFFFu || s_live[i].ptr == ptr) {
                if (s_live[i].ptr == ptr)       /* reused without a delete we saw */
                    s_site[s_live[i].site].deletes++;
                s_live[i].ptr = ptr;
                s_live[i].site = (uint16_t)site;
                break;
            }
    }
    s_news++;
    live_unlock();
    if (s_news % 20000 == 0)
        live_report();
}

void amped2_delete_probe(uint32_t ptr, uint32_t ret)
{
    uint32_t i, k;
    (void)ret;
    if (!ptr)
        return;
    live_lock();
    s_deletes++;
    for (i = (ptr >> 3) & (LIVE_SLOTS - 1), k = 0; k < 256 && s_live[i].ptr; k++, i = (i + 1) & (LIVE_SLOTS - 1))
        if (s_live[i].ptr == ptr) {
            s_site[s_live[i].site].deletes++;
            s_live[i].ptr = 0xFFFFFFFFu;
            live_unlock();
            return;
        }
    s_unknown_deletes++;
    live_unlock();
}

/* XACT cue lifecycle trace (RECOMP_CUE_TRACE=<lines>): Play, Stop, Release
 * and notification events with the cue, its refcount and flags, and the
 * caller. For probes pasted at the entry labels of sub_00310369 (Play),
 * sub_00312FB0 (Stop), sub_00312C4F (Release), sub_00313600 (notify). */
void amped2_cue_event(const char *tag, uint32_t cue, uint32_t a, uint32_t caller)
{
    static long limit = -1, lines;
    if (limit < 0) {
        const char *e = getenv("RECOMP_CUE_TRACE");
        limit = e ? atol(e) : 0;
    }
    if (lines >= limit)
        return;
    lines++;
    fprintf(stderr, "[CUE] %-7s cue %08X refs %u flags %04X arg %08X from %08X\n", tag, cue,
            cue ? MEM32(cue + 0x34) : 0, cue ? MEM16(cue + 0x38) : 0, a, caller);
}

/* Allocation probe, for a call pasted into the generated allocators
 * (sub_000DC0F0 at loc_000DC1B8, sub_000DC1E0 at loc_000DC2AD -- see README
 * "Bring-up notes"): who allocates from which heap object, by caller and
 * thread, printed by the OOM wrapper below. RECOMP_AP_HEAP=<object> also
 * logs every 20th allocation into that one heap. Nothing calls it unless
 * the generated code has been edited to. */
#define PROBE_SLOTS 4096
static struct { uint32_t heap, ret, count, bytes, fails; unsigned long tid; } s_ap[PROBE_SLOTS];
void amped2_alloc_probe(uint32_t heap, uint32_t size, uint32_t result, uint32_t ret)
{
    unsigned long tid = GetCurrentThreadId();
    int i;
    for (i = 0; i < PROBE_SLOTS; i++) {
        if (s_ap[i].count && s_ap[i].heap == heap && s_ap[i].ret == ret && s_ap[i].tid == tid)
            break;
        if (!s_ap[i].count) {
            s_ap[i].heap = heap; s_ap[i].ret = ret; s_ap[i].tid = tid;
            break;
        }
    }
    if (i == PROBE_SLOTS)
        return;
    s_ap[i].count++;
    s_ap[i].bytes += size;
    if (!result)
        s_ap[i].fails++;
    {
        static uint32_t watch_heap = 1;
        if (watch_heap == 1) {
            const char *e = getenv("RECOMP_AP_HEAP");
            watch_heap = e ? (uint32_t)strtoul(e, NULL, 0) : 0;
        }
        if (!watch_heap || heap != watch_heap)
            return;
    }
    {
        static uint32_t n, total;
        n++;
        total += size;
        if (n % 20 == 0 || size > 1000)
            fprintf(stderr, "[AP] heap 0x%08X: alloc #%u size %u from 0x%08X tid %lu, %u bytes so far%s\n",
                    heap, n, size, ret, tid, total, result ? "" : " FAILED");
    }
}

static void alloc_probe_dump(uint32_t heap)
{
    int i;
    live_report();
    fprintf(stderr, "[AP] allocations from heap object 0x%08X, by caller and thread:\n", heap);
    for (i = 0; i < PROBE_SLOTS && s_ap[i].count; i++)
        if (s_ap[i].heap == heap || s_ap[i].count >= 200)
            fprintf(stderr, "[AP]   heap 0x%08X ret 0x%08X tid %5lu: %u allocs, %u bytes, %u failed\n",
                    s_ap[i].heap, s_ap[i].ret, s_ap[i].tid, s_ap[i].count, s_ap[i].bytes, s_ap[i].fails);
    fflush(stderr);
}

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
extern void sub_00150E80(void);   /* src/lua_probe.c */

/* Skip FMV (see sub_00150E80 in lua_probe.c). main.c clears it when
 * AMPED2_PLAY_MOVIES is set. */
int g_amped2_skip_movies = 1;

/*
 * 0x0031C4B0: D3DDevice_Swap. It writes FLIP_INCREMENT_WRITE + FLIP_STALL
 * through sub_0031C050 or sub_0031C1D0, and the title calls it once per
 * presented frame (FLIP_STALL alone also comes from sub_0031A180, several
 * times a frame). Wrapped to pace the frame on the title's thread -- see
 * xbox_PresentPace in the toolkit's nv2a_pb_exec.c -- then do what it
 * always did.
 */
extern void sub_0031C4B0_gen(void);
extern void xbox_PresentPace(void);

void sub_0031C4B0(void)
{
    /* Opt-in (RECOMP_PACE_PRESENT=1). Measured in ML1: pacing here, before
     * the swap, 48 fps; after it, 23-43 (it collides with D3D's own wait at
     * the next swap); the executor's FLIP_STALL pacing, the default, 51. */
    static int on = -1;
    if (on < 0)
        on = getenv("RECOMP_PACE_PRESENT") != NULL;
    if (on)
        xbox_PresentPace();
    sub_0031C4B0_gen();
}

/*
 * 0x003285F0: D3D's recorded-pushbuffer patcher (RunPushBuffer's fixups). It
 * writes the buffer's jump back into the ring and copies the per-call fixup
 * data into the buffer itself. On the console D3D only does this from the CPU
 * when the GPU has finished with the buffer; otherwise it queues a NOP with an
 * interrupt and patches from the PGRAPH handler (0x322830) when the GPU gets
 * there. Our fence mirror always says the GPU is done, so D3D patched from the
 * CPU three times a frame while the pushbuffer walker was still behind: the
 * walker then followed a later call's jump back (into data, or past commands)
 * and ran earlier calls with later fixups -- the corrupted state in level 2
 * that stayed into the menus.
 *
 * So before patching, make it true. RunPushBuffer (0x328690) has written the
 * jump to the buffer at the ring's write pointer (device + 0) and not yet
 * moved the pointer, so everything before the pointer is complete: set PUT
 * there (D3D's own form, VA & 0x0FFFFFFF) and wait for the walker to report
 * it consumed (DMA_GET == PUT). Every earlier call of the buffer has then
 * run with its own patch. RECOMP_PB_PATCH_NOWAIT=1 restores the old
 * behaviour.
 */
extern void sub_003285F0_gen(void);

#define AMPED2_D3D_DEVICE_PTR 0x0032CEF8u
#define AMPED2_NV2A_DMA_PUT   0xFD800040u
#define AMPED2_NV2A_DMA_GET   0xFD800044u

void sub_003285F0(void)
{
    static int nowait = -1;
    if (nowait < 0)
        nowait = getenv("RECOMP_PB_PATCH_NOWAIT") != NULL;
    if (!nowait) {
        uint32_t dev = MEM32(AMPED2_D3D_DEVICE_PTR);
        uint32_t put = dev ? (MEM32(dev) & 0x0FFFFFFFu) : 0;
        unsigned long t0 = GetTickCount();
        if (put) {
            uint32_t cur = MEM32(AMPED2_NV2A_DMA_PUT);
            /* Only forward within the same lap; a pointer behind PUT is a
             * wrap D3D has not kicked yet, and the walker is ahead of it. */
            if (put > cur || cur - put > 0x00400000u)
                MEM32(AMPED2_NV2A_DMA_PUT) = put;
            while (MEM32(AMPED2_NV2A_DMA_GET) != MEM32(AMPED2_NV2A_DMA_PUT)) {
                if (GetTickCount() - t0 > 250) {
                    static unsigned said;
                    if (said++ < 8)
                        fprintf(stderr, "  [D3D] pushbuffer patch: GET %08X did not"
                                " reach PUT %08X in 250 ms; patching anyway\n",
                                MEM32(AMPED2_NV2A_DMA_GET), MEM32(AMPED2_NV2A_DMA_PUT));
                    break;
                }
                Sleep(0);
            }
        }
    }
    sub_003285F0_gen();
}

/*
 * 0x0032F339: XInputSetState(HANDLE, PXINPUT_FEEDBACK), stdcall. The game's
 * rumble update (0x000ACA31) calls it every frame. The device pointer it
 * follows (handle + 0xA3) is filled in once the pad is attached; until then it
 * holds XPP's fresh-block fill, 0xCCCCCCCC (the pool allocator at 0x0033195B).
 * Twice the game called it in that window -- after ten minutes of play and
 * once 40 s into a level -- and crashed reading through 0xCCCCCCCC, with the
 * USB DPC faulting on the same half-built structure. Answer
 * ERROR_DEVICE_NOT_CONNECTED for a device pointer that is not an address yet,
 * which the game already handles for an unplugged pad.
 */
extern void sub_0032F339_gen(void);

/* An XInput handle whose device pointer (handle + 0xA3) is an address. */
static int xinput_handle_ok(uint32_t h)
{
    uint32_t dev = h ? MEM32(h + 0xA3) : 0;
    int ok = h && dev >= 0x1000u && (dev < 0x04000000u
                                     || (dev >= 0x80000000u && dev < 0x84000000u));
    if (!ok && h) {
        /* The first time: physical page 0 (XPP's pool, where the handle
         * lives) and XPP's data (its pool counter is 0x0032E2C8) to
         * diag/xinput_page0.bin, and the extent of the 0xCC fill, to tell
         * which write refilled the block. */
        static int dumped;
        if (!dumped++) {
            FILE *f = fopen("diag/xinput_page0.bin", "wb");
            uint32_t a, lo = 0, hi = 0;
            for (a = 0x80000000u; a < 0x80001000u; a += 4) {
                uint32_t v = MEM32(a);
                if (f) fwrite(&v, 4, 1, f);
                if (v == 0xCCCCCCCCu) { if (!lo) lo = a; hi = a + 4; }
            }
            for (a = 0x0032E120u; a < 0x0032E420u; a += 4) {
                uint32_t v = MEM32(a);
                if (f) fwrite(&v, 4, 1, f);
            }
            if (f) fclose(f);
            fprintf(stderr, "  [XINPUT] handle %08X device %08X: XPP pool counter %08X;"
                    " 0xCC dwords in page 0 from %08X to %08X; dumped to"
                    " diag/xinput_page0.bin\n", h, dev, MEM32(0x0032E2C8u), lo, hi);
        }
    }
    return ok;
}

void sub_0032F339(void)
{
    uint32_t h = MEM32(g_esp + 4);
    uint32_t dev = h ? MEM32(h + 0xA3) : 0;
    if (!xinput_handle_ok(h)) {
        static unsigned said;
        if (said++ < 8)
            fprintf(stderr, "  [XINPUT] SetState on handle %08X with device %08X:"
                    " not attached yet, ignored\n", h, dev);
        g_eax = 0x48Fu;                       /* ERROR_DEVICE_NOT_CONNECTED */
        g_esp += 4 + 8;                       /* ret 8 */
        return;
    }
    sub_0032F339_gen();
}

/*
 * 0x0032F2C6: XInputGetState(HANDLE, PXINPUT_STATE), stdcall. Same
 * device pointer, read the same way (test byte [dev+0x28] at raised IRQL),
 * called by the game's pad poll (0x000ABD21). With the SetState guard in
 * place, run l3t0 (2026-10-01) crashed here instead: the block holding the
 * handle (XPP's page-0 device block at 0x80000080) had been filled with
 * 0xCC again mid-level, by what is still unknown. Same answer: not
 * connected.
 */
extern void sub_0032F2C6_gen(void);

void sub_0032F2C6(void)
{
    uint32_t h = MEM32(g_esp + 4);
    if (!xinput_handle_ok(h)) {
        static unsigned said;
        if (said++ < 8)
            fprintf(stderr, "  [XINPUT] GetState on handle %08X with device %08X:"
                    " not attached, ignored\n", h, h ? MEM32(h + 0xA3) : 0);
        g_eax = 0x48Fu;                       /* ERROR_DEVICE_NOT_CONNECTED */
        g_esp += 4 + 8;                       /* ret 8 */
        return;
    }
    sub_0032F2C6_gen();
}

/*
 * 0x0031AE90: D3DDevice_BlockUntilVerticalBlank. It clears the device's
 * vblank KEVENT (device + 0x1DAC) and waits on it; D3D's GPU interrupt
 * handler sets it each vblank. Nothing here raises the NV2A interrupt, so the
 * wait never ended -- and the FMV player (sub_00150FF0, 0x0015154D) calls it
 * every frame when its decoder has nothing ready, which left AMPED2_PLAY_MOVIES
 * on a black screen at the first movie. Wait for the kernel's own 60 Hz
 * vblank tick instead (the one the title's vblank counter follows).
 */
void sub_0031AE90(void)
{
    extern volatile long g_xbox_vblank_count;
    long v = g_xbox_vblank_count;
    unsigned long t0 = GetTickCount();
    uint32_t dev = MEM32(0x32CEF8);

    if (dev)
        MEM32(dev + 0x1DB0) = 0;           /* the event's SignalState, as it did */
    while (g_xbox_vblank_count == v && GetTickCount() - t0 < 50)
        Sleep(1);
    g_esp += 4; /* ret */
}

void sub_0002B6C0(void)
{
    uint32_t obj = g_edi;

    dump_guest_backtrace("out-of-memory handler 0x0002B6C0", 4096);
    alloc_probe_dump(obj);
    if (obj && obj < 0x04000000u) {
        uint32_t i, vt = MEM32(obj);
        fprintf(stderr, "[BT]   heap object 0x%08X:", obj);
        for (i = 0; i < 56; i++)
            fprintf(stderr, "%s%08X", (i % 8) ? " " : "\n[BT]     ", MEM32(obj + i * 4));
        fprintf(stderr, "\n[BT]   its table 0x%08X:", vt);
        if (vt && vt < 0x04000000u)
            for (i = 0; i < 16; i++)
                fprintf(stderr, " %08X", MEM32(vt + i * 4));
        fprintf(stderr, "\n");
    }
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
    if (xbox_va == 0x00150E80) return sub_00150E80;  /* movie next-frame */

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
