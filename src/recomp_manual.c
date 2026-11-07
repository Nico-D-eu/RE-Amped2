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
#include <stdlib.h>
#include <string.h>

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
#if defined(_WIN32)
__declspec(dllimport) unsigned long __stdcall GetCurrentThreadId(void);
__declspec(dllimport) int __stdcall QueryPerformanceCounter(long long *);
__declspec(dllimport) int __stdcall QueryPerformanceFrequency(long long *);
__declspec(dllimport) unsigned long __stdcall GetTickCount(void);
__declspec(dllimport) void __stdcall Sleep(unsigned long);
#else
/* The toolkit's POSIX versions (win32_compat.c), whose DWORD is 32 bits. */
uint32_t GetCurrentThreadId(void);
int QueryPerformanceCounter(long long *);
int QueryPerformanceFrequency(long long *);
uint32_t GetTickCount(void);
void Sleep(uint32_t);
#endif
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
            (double)(now - t0) * 1000.0 / (double)f,
            (unsigned long)GetCurrentThreadId(), tag, a, b, c);
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
#if defined(_MSC_VER)
long _InterlockedExchange(long volatile *, long);
void _mm_pause(void);
#pragma intrinsic(_InterlockedExchange, _mm_pause)
#define live_xchg(p, v) _InterlockedExchange((p), (v))
#define live_pause()    _mm_pause()
#else
#define live_xchg(p, v) __atomic_exchange_n((p), (v), __ATOMIC_SEQ_CST)
#if defined(__x86_64__) || defined(__i386__)
#define live_pause()    __builtin_ia32_pause()
#else
#define live_pause()    ((void)0)
#endif
#endif
static volatile long s_live_lock;

static void live_lock(void)   { while (live_xchg(&s_live_lock, 1)) live_pause(); }
static void live_unlock(void) { live_xchg(&s_live_lock, 0); }

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

/* Skip FMV (see sub_00150E80 in lua_probe.c). main.c sets it from
 * AMPED2_PLAY_MOVIES: movies play unless that is 0. */
int g_amped2_skip_movies = 0;

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
/*
 * 0x002CDE60: XMV's GetNextFrame(decoder, ?, PXMVSTATUS, ?), stdcall 16.
 * AMPED2_XMV_TRACE=1: the decoder's packet state before the call and the
 * status after, for the first calls and on every change -- why a movie
 * never gets a frame. Fields: +0x1C/+0x20 the packet callbacks (get next,
 * release), +0x24 their context, +0x50 frames left in the packet, +0x60 the
 * current packet, +0x68/+0x74 end flags, +0x6C a packet requested.
 *
 * AMPED2_XMV_STATS=1: once a second, the calls, how many returned each
 * status, how many found a packet request pending, and how far the next
 * frame's time (+0xF8, ms) is behind the movie clock (D3D's vblank count
 * at device + 0x1DD8, less the start at +0xB8, at 60 a second) -- whether
 * a slow movie is waiting for data or for time.
 */
extern void sub_002CDE60_gen(void);

static uint32_t xmv_vblank_count(void);   /* the count XMV sees (0x0031AE50) */

static void xmv_stats(uint32_t dec, uint32_t status, int req_before, double ms)
{
    static int on = -1;
    static unsigned long t0;
    static unsigned calls, st[4], req, why[4], drained;
    static double in_ms[2], max_ms[2], drain_ms, drain_max;
    static long long drain_t0;
    long long now, qf;
    if (on < 0)
        on = getenv("AMPED2_XMV_STATS") != NULL;
    if (!on || !dec)
        return;
    if (!t0)
        t0 = GetTickCount();
    calls++;
    st[status < 3 ? status : 3]++;
    req += req_before != 0;
    in_ms[status == 1] += ms;
    if (ms > max_ms[status == 1])
        max_ms[status == 1] = ms;
    /* Why a call had no frame: 0 the spent packet waits for its audio
     * (+0x68 set, +0x74 clear: a stream packet still pending), 1 a packet
     * read is requested, 2 a frame is decoded but not due, 3 other. */
    if (status == 0)
        why[MEM32(dec + 0x68) && !MEM32(dec + 0x74) ? 0 : MEM32(dec + 0x6C) ? 1 :
            MEM32(dec + 0xF8) != 0xFFFFFFFFu ? 2 : 3]++;
    /* How long each spent packet waited for its audio. */
    QueryPerformanceCounter(&now);
    QueryPerformanceFrequency(&qf);
    if (MEM32(dec + 0x68) && !drain_t0)
        drain_t0 = now;
    else if (!MEM32(dec + 0x68) && drain_t0) {
        double d = (double)(now - drain_t0) * 1000.0 / (double)qf;
        drain_ms += d;
        if (d > drain_max)
            drain_max = d;
        drained++;
        drain_t0 = 0;
    }
    if (GetTickCount() - t0 >= 1000) {
        extern volatile long g_xbox_vblank_count;
        static uint32_t last_d3d, last_ours;
        uint32_t dev = MEM32(0x0032CEF8u);
        uint32_t d3d = dev ? MEM32(dev + 0x1DD8) : 0, ours = (uint32_t)g_xbox_vblank_count;
        long clock_ms = dev ? (long)((xmv_vblank_count() - MEM32(dec + 0xB8)) * 1000u / 60u) : 0;
        fprintf(stderr, "  [XMV] stats: %u calls, status 0/1/2/other %u/%u/%u/%u,"
                " %u with a packet requested; next frame %u ms, clock %ld ms (%+ld);"
                " in the call %.0f ms without a frame (longest %.1f), %.0f ms with"
                " (longest %.1f); no frame: audio %u read %u early %u other %u;"
                " %u packets waited %.0f ms for audio (longest %.0f); c8 %d ms;"
                " vblanks D3D %u ours %u\n",
                calls, st[0], st[1], st[2], st[3], req, MEM32(dec + 0xF8), clock_ms,
                clock_ms - (long)MEM32(dec + 0xF8), in_ms[0], max_ms[0], in_ms[1], max_ms[1],
                why[0], why[1], why[2], why[3], drained, drain_ms, drain_max,
                (int)MEM32(dec + 0xC8), d3d - last_d3d, ours - last_ours);
        last_d3d = d3d;
        last_ours = ours;
        t0 = GetTickCount();
        calls = req = drained = 0;
        memset(st, 0, sizeof st);
        memset(why, 0, sizeof why);
        in_ms[0] = in_ms[1] = max_ms[0] = max_ms[1] = drain_ms = drain_max = 0;
    }
}

void sub_002CDE60(void)
{
    static int trace = -1;
    static unsigned n;
    static uint32_t last[6];
    uint32_t dec = MEM32(g_esp + 4), pstatus = MEM32(g_esp + 12);
    uint32_t cur[6];
    int k, changed = 0, req_before = dec ? (int)MEM32(dec + 0x6C) : 0;
    long long q0, q1, qf;

    if (trace < 0)
        trace = getenv("AMPED2_XMV_TRACE") != NULL;
    if (trace && dec) {
        cur[0] = MEM32(dec + 0x50); cur[1] = MEM32(dec + 0x60); cur[2] = MEM32(dec + 0x68);
        cur[3] = MEM32(dec + 0x6C); cur[4] = MEM32(dec + 0x74); cur[5] = MEM32(dec + 0x64);
        for (k = 0; k < 6; k++)
            changed |= cur[k] != last[k];
    }
    QueryPerformanceCounter(&q0);
    sub_002CDE60_gen();
    QueryPerformanceCounter(&q1);
    QueryPerformanceFrequency(&qf);
    if (trace && dec && (n < 12 || (changed && n < 400) || n % 120 == 0)) {
        fprintf(stderr, "  [XMV] #%u dec %08X cb %08X/%08X ctx %08X: frames %08X pkt %08X"
                " end %08X/%08X req %08X +64 %08X -> status %u (eax %08X)\n", n, dec,
                MEM32(dec + 0x1C), MEM32(dec + 0x20), MEM32(dec + 0x24), cur[0], cur[1],
                cur[2], cur[4], cur[3], cur[5], pstatus ? MEM32(pstatus) : 0xFFu, g_eax);
        fprintf(stderr, "  [XMV]    vblank %u start %u next-frame %08X e8 %08X 3c %08X"
                " b0/b4 %08X/%08X c8 %08X bc %08X\n",
                MEM32(MEM32(0x0032CEF8u) + 0x1DD8), MEM32(dec + 0xB8), MEM32(dec + 0xF8),
                MEM32(dec + 0xE8), MEM32(dec + 0x3C), MEM32(dec + 0xB0), MEM32(dec + 0xB4),
                MEM32(dec + 0xC8), MEM32(dec + 0xBC));
        if (n < 3) {   /* the per-stream decoders: object, vtable, the two flags */
            uint32_t cnt = MEM32(dec + 0x48), i;
            for (i = 0; i < cnt && i < 8; i++) {
                uint32_t obj = MEM32(MEM32(dec + 0x134) + i * 4);
                fprintf(stderr, "  [XMV]    stream %u: obj %08X vtbl %08X flag138 %08X flag13C %08X"
                        " obj+4..+1C %08X %08X %08X %08X %08X %08X %08X\n", i, obj,
                        obj ? MEM32(obj) : 0, MEM32(MEM32(dec + 0x138) + i * 4),
                        MEM32(MEM32(dec + 0x13C) + i * 4),
                        obj ? MEM32(obj + 4) : 0, obj ? MEM32(obj + 8) : 0,
                        obj ? MEM32(obj + 12) : 0, obj ? MEM32(obj + 16) : 0,
                        obj ? MEM32(obj + 20) : 0, obj ? MEM32(obj + 24) : 0,
                        obj ? MEM32(obj + 28) : 0);
            }
        }
        memcpy(last, cur, sizeof last);
    }
    xmv_stats(dec, pstatus ? MEM32(pstatus) : 3u, req_before,
              (double)(q1 - q0) * 1000.0 / (double)qf);
    {   /* The movie pack (movie_pack.c) follows the frame shown, +0xE4 (ms). */
        extern void movie_pack_frame(uint32_t ms), movie_pack_end(void);
        uint32_t st = pstatus ? MEM32(pstatus) : 0;
        if (dec && st == 1)
            movie_pack_frame(MEM32(dec + 0xE4));
        else if (st == 2)
            movie_pack_end();
    }
    n++;
}

/*
 * 0x00295E64: DirectSound's voice pause worker, thiscall (ecx = voice client,
 * one stack arg: the new state flags; bits 0x40 paused, 0x04 starved, 0x400
 * at +0x12). AMPED2_XMV_TRACE=1 logs every call with the old flags and the
 * caller -- whether a movie's audio stream is ever told to resume.
 */
extern void sub_00295E64_gen(void);

void sub_00295E64(void)
{
    static int trace = -1;
    static unsigned n;
    uint32_t self = g_ecx, flags = MEM32(g_esp + 4), ret = MEM32(g_esp);
    uint32_t old = self ? (MEM32(self + 0x12) & 0xFFFFu) : 0;
    if (trace < 0)
        trace = getenv("AMPED2_XMV_TRACE") != NULL;
    if (trace && n++ < 200)
        fprintf(stderr, "  [DSPAUSE] client %08X flags %04X -> %04X from %08X\n",
                self, old, flags & 0xFFFFu, ret);
    sub_00295E64_gen();
}

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

/*
 * 0x0031AE50: D3DDevice_GetDisplayFieldStatus(PD3DFIELD_STATUS), stdcall 4.
 * Writes the field (+0: 1 odd, 2 even, 3 progressive, from the device's mode
 * flags at +0x1DCC and its current field at +0x1DE8) and the vblank count
 * (+4). Its one caller is XMV's GetNextFrame (0x002CE181), which shows a
 * frame once that count, at 59.94 a second, passes the frame's time plus an
 * audio offset (decoder + 0xC8).
 *
 * D3D's count (device + 0x1DD8) only moves in its vblank DPC, and only when
 * its parity matches the field our HAL reports from g_xbox_vblank_count. Two
 * ticks before one DPC run (a late timer pass) cost it a count, so it ran at
 * 56-59 a second. That was enough to sink the movies: the picture ran a few
 * percent slow, its packets were freed late, the audio stream (two packets of
 * about 0.28 s) ran dry, and every gap went into the audio offset and delayed
 * the picture further. The intro then fell behind at about 0.6 s a second
 * from 15 s in (AMPED2_XMV_STATS, 2026-11-03), and the long career movies
 * crawled. Report the kernel's own tick instead, the one the movie loop
 * already waits on (0x0031AE90 above). AMPED2_XMV_CLOCK=d3d restores D3D's
 * count.
 */
static uint32_t xmv_vblank_count(void)
{
    extern volatile long g_xbox_vblank_count;
    static int d3d_clock = -1;

    if (d3d_clock < 0) {
        const char *s = getenv("AMPED2_XMV_CLOCK");
        d3d_clock = s && strcmp(s, "d3d") == 0;
    }
    return d3d_clock ? MEM32(MEM32(0x32CEF8) + 0x1DD8) : (uint32_t)g_xbox_vblank_count;
}

void sub_0031AE50(void)
{
    uint32_t dev = MEM32(0x32CEF8), out = MEM32(g_esp + 4);

    MEM32(out + 4) = xmv_vblank_count();
    if (MEM32(dev + 0x1DCC) & 0x1200000u)       /* interlaced: which field */
        MEM32(out) = MEM32(dev + 0x1DE8) == 0 ? 2u : 1u;
    else
        MEM32(out) = 3;
    g_esp += 4 + 4; /* ret 4 */
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
/* ── Menu mod: a "QuitGame" shell command ──────────────────────────────
 *
 * The GUI's actions call native commands by name (PushMenu, PopMenu,
 * PlayMenuItemSelectSound ...). 0x00218140 registers them, thiscall on the
 * shell object, one name at a time into the registry at [this+4]:
 *     key = String(name)               sub_000122B0  eax = C string, push &key
 *     Register(registry, &key), ecx=fn sub_00205370  (ebx = the shell, non-zero)
 *     ~key                             sub_0001A490  ecx = &key
 * A command is thiscall with one stack argument and returns al = 0 (`ret 4`).
 *
 * The wrapper registers one more, QuitGame, after the title's own. Its name
 * lives in the unused tail of the XBE header page (headers end at
 * 0x00010B60, .text starts at 0x00011000). Its "code address" is a value
 * no guest code or data uses, above 0xFE000000: the indirect-call guard
 * (RECOMP_ICALL_IS_CODE) passes that range, and recomp_lookup_manual below
 * answers it before anything else. One in the header page was refused as
 * "not code". The menu mod (tools/mods/menus.py) gives the main menu a QUIT
 * item that calls it.
 */
#define AMPED2_QUIT_NAME_VA 0x00010F00u
#define AMPED2_QUIT_FN_VA   0xFEFFFF00u

extern void sub_000122B0(void);
extern void sub_00205370(void);
extern void sub_0001A490(void);
extern void sub_00218140_gen(void);

/* The command: close the window, which is how the game quits (the title
 * saves as it goes). */
static void amped2_cmd_quit(void)
{
    extern void xbox_RequestQuit(void);     /* toolkit fb_present.c */
    fprintf(stderr, "  [MOD] QuitGame from the menu\n");
    fflush(stderr);
    xbox_RequestQuit();
    SET_LO8(g_eax, 0);
    g_esp += 8;                             /* ret 4 */
}

static void amped2_register_command(uint32_t self, const char *name, uint32_t fn_va,
                                    uint32_t name_va)
{
    uint32_t key, saved_ebx = g_ebx, saved_ecx = g_ecx;
    size_t i;

    for (i = 0; name[i]; i++)
        MEM8(name_va + i) = (uint8_t)name[i];
    MEM8(name_va + i) = 0;

    g_esp -= 16;                            /* the key, on the guest stack */
    key = g_esp;
    MEM32(key) = 0;

    g_esp -= 4; MEM32(g_esp) = key;         /* String(name) -> key */
    g_esp -= 4; MEM32(g_esp) = 0;
    g_eax = name_va;
    sub_000122B0();

    /* Register(registry, &key). ebx is the shell object here, as in the
     * title (`ebx = edi` before its registrations): sub_00205370 builds the
     * functor from ecx only when ebx is non-zero, and with ebx = 0 it
     * stored a null function, so QuitGame() was never found. */
    g_ebx = self;
    g_esp -= 4; MEM32(g_esp) = key;         /* pushed first, as the title does */
    g_esp -= 4; MEM32(g_esp) = MEM32(self + 4);
    g_esp -= 4; MEM32(g_esp) = 0;
    g_ecx = fn_va;
    sub_00205370();

    g_ecx = key;                            /* ~key */
    g_esp -= 4; MEM32(g_esp) = 0;
    sub_0001A490();

    g_esp += 16;
    g_ebx = saved_ebx;
    g_ecx = saved_ecx;
}

/* ── Developer challenges: StartDevChallenge(n) ─────────────────────── */
#define AMPED2_DEVCHAL_NAME_VA 0x00010F10u
#define AMPED2_DEVCHAL_FN_VA   0xFEFFFF10u

static const char *amped2_gstr(uint32_t va)
{
    if (va < 0x10000u || va >= 0x08000000u)
        return "(null)";
    return (const char *)XBOX_PTR(va);
}

static int amped2_ieq(const char *a, const char *b)
{
    for (; *a && *b; a++, b++) {
        char x = *a, y = *b;
        if (x >= 'A' && x <= 'Z') x += 32;
        if (y >= 'A' && y <= 'Z') y += 32;
        if (x != y) return 0;
    }
    return *a == *b;
}

/* A C string into the header-page scratch at va (64 bytes each). */
static void amped2_put_cstr(uint32_t va, const char *s)
{
    size_t i;
    for (i = 0; s[i] && i < 63; i++)
        MEM8(va + i) = (uint8_t)s[i];
    MEM8(va + i) = 0;
}

/* Call a guest function from C: dummy return address, as the generated
 * bodies pop it themselves. Callers push stack arguments first. */
#define AMPED2_GCALL(fn) do { g_esp -= 4; MEM32(g_esp) = 0; fn(); } while (0)

extern void sub_00013800(void), sub_00020C30(void), sub_000200B0(void);
extern void sub_0010BCB0(void), sub_0010DA50(void);
extern void sub_00102360(void), sub_001022A0(void), sub_0010FED0(void), sub_0010FEA0(void);
extern void sub_002194B0(void), sub_00018B40(void);

/* The challenge StartDevChallenge set up: its level and drop point ID. The
 * next drop-point screen starts it (amped2_droppoint_push). */
static char g_devchal_level[8], g_devchal_drop[24], g_devchal_playing[24];
static int g_devchal_pending;
/* The run in progress: its drop point (guest; valid while the level is
 * loaded), whether its win was counted, and whether the shell, when it
 * starts after the level, opens the DEVELOPER CHALLENGES list. */
static uint32_t g_devchal_dp;
static int g_devchal_counted, g_devchal_return;
/* Stat points earned (one per three challenges won) and not yet handed to
 * the game's own skill-point check. */
static int g_devchal_award;

/* ── Developer challenges: results, in devchallenges.json beside amped2.ini
 *
 *     { "won": ["dev1", "dev3"], "points": 0 }
 *
 * "won" holds each challenge won (its pack ID, the drop point's ID in lower
 * case), once however often it is won; "points" the stat points already
 * given, one per three wins. Not the career save: the career only changes
 * by the stat point, spent the game's own way. */
#define AMPED2_DEVCHAL_MAX 64
static char g_devchal_won[AMPED2_DEVCHAL_MAX][24];
static int g_devchal_nwon, g_devchal_points, g_devchal_loaded;

extern int amped2_side_file(const char *name, char *path, size_t size);

static void amped2_devchal_load(void)
{
    char path[512], buf[8192], *p, *end;
    FILE *f;
    size_t len;
    if (g_devchal_loaded)
        return;
    g_devchal_loaded = 1;
    if (!amped2_side_file("devchallenges.json", path, sizeof path) || !(f = fopen(path, "rb")))
        return;
    len = fread(buf, 1, sizeof buf - 1, f);
    fclose(f);
    buf[len] = 0;
    p = strstr(buf, "\"won\"");
    p = p ? strchr(p, '[') : NULL;
    end = p ? strchr(p, ']') : NULL;
    while (p && end && g_devchal_nwon < AMPED2_DEVCHAL_MAX) {
        char *q = strchr(p + 1, '"'), *r;
        if (!q || q > end) break;
        r = strchr(q + 1, '"');
        if (!r || r > end) break;
        if (r - q - 1 > 0 && r - q - 1 < 24) {
            memcpy(g_devchal_won[g_devchal_nwon], q + 1, (size_t)(r - q - 1));
            g_devchal_won[g_devchal_nwon][r - q - 1] = 0;
            g_devchal_nwon++;
        }
        p = r;
    }
    p = strstr(buf, "\"points\"");
    p = p ? strchr(p, ':') : NULL;
    g_devchal_points = p ? atoi(p + 1) : 0;
    fprintf(stderr, "  [DEVCHAL] %s: %d won, %d point(s) given\n", path, g_devchal_nwon,
            g_devchal_points);
}

static void amped2_devchal_save(void)
{
    char path[512], tmp[520];
    FILE *f;
    int i;
    if (!amped2_side_file("devchallenges.json", path, sizeof path))
        return;
    snprintf(tmp, sizeof tmp, "%s.tmp", path);
    if (!(f = fopen(tmp, "wb")))
        return;
    fprintf(f, "{\n  \"won\": [");
    for (i = 0; i < g_devchal_nwon; i++)
        fprintf(f, "%s\"%s\"", i ? ", " : "", g_devchal_won[i]);
    fprintf(f, "],\n  \"points\": %d\n}\n", g_devchal_points);
    fclose(f);
    remove(path);
    rename(tmp, path);
}

/* A win of the run in progress: count the challenge (once) and work out
 * whether a stat point is due. */
static void amped2_devchal_win(void)
{
    char id[24];
    int i, due;
    amped2_devchal_load();
    for (i = 0; g_devchal_playing[i] && i < 23; i++)
        id[i] = (char)(g_devchal_playing[i] >= 'A' && g_devchal_playing[i] <= 'Z'
                       ? g_devchal_playing[i] + 32 : g_devchal_playing[i]);
    id[i] = 0;
    for (i = 0; i < g_devchal_nwon; i++)
        if (!strcmp(g_devchal_won[i], id))
            break;
    if (i == g_devchal_nwon && g_devchal_nwon < AMPED2_DEVCHAL_MAX) {
        snprintf(g_devchal_won[g_devchal_nwon++], 24, "%s", id);
        amped2_devchal_save();
    }
    due = g_devchal_nwon / 3 - g_devchal_points;
    g_devchal_award = due > 0 ? due : 0;
    fprintf(stderr, "  [DEVCHAL] won %s: %d challenge(s) won, %d point(s) given, %d due\n",
            id, g_devchal_nwon, g_devchal_points, g_devchal_award);
    fflush(stderr);
}

/* The i-th argument of a GUI command call as text ("" if none). Arguments
 * are 12-byte values at [args+0x84], [args+0x88] of them; a quoted one keeps
 * its text as a String (char *) at +8. */
static const char *amped2_cmd_arg(uint32_t args, uint32_t i)
{
    if (i >= MEM32(args + 0x88))
        return "";
    return amped2_gstr(MEM32(MEM32(args + 0x84) + 12 * i + 8));
}

static void amped2_cmd_devchal(void)
{
    uint32_t args = MEM32(g_esp + 4);
    uint32_t sb = g_ebx, ss = g_esi, sd = g_edi, sp = g_ebp, key;
    const char *level = amped2_cmd_arg(args, 0), *drop = amped2_cmd_arg(args, 1);
    char buf[64];
    size_t i;

    if (!level[0] || strlen(level) > 4 || !drop[0] || strlen(drop) >= sizeof g_devchal_drop) {
        fprintf(stderr, "  [DEVCHAL] StartDevChallenge(\"%s\", \"%s\"): bad arguments\n", level, drop);
        fflush(stderr);
        SET_LO8(g_eax, 0);
        g_esp += 8;
        return;
    }
    for (i = 0; level[i]; i++)
        g_devchal_level[i] = (char)(level[i] >= 'a' && level[i] <= 'z' ? level[i] - 32 : level[i]);
    g_devchal_level[i] = 0;
    snprintf(g_devchal_drop, sizeof g_devchal_drop, "%s", drop);
    g_devchal_pending = 1;

    /* What SelectLevel() does for the level's entry (sub_001E0F50), without
     * the entry's locked check: the session's level file and path, as the
     * Level Select entries hold them ("LX2.LVL", "D:\LEVELS\LX2\"). */
    snprintf(buf, sizeof buf, "%s.LVL", g_devchal_level);
    amped2_put_cstr(0x00010F40u, buf);
    snprintf(buf, sizeof buf, "D:\\LEVELS\\%s\\", g_devchal_level);
    amped2_put_cstr(0x00010F80u, buf);
    g_esp -= 16;
    key = g_esp;
    MEM32(key) = 0;
    MEM32(key + 4) = 0;
    g_esp -= 4; MEM32(g_esp) = key;         /* String("LX2.LVL") */
    g_eax = 0x00010F40u;
    AMPED2_GCALL(sub_000122B0);
    g_esp -= 4; MEM32(g_esp) = key + 4;     /* String("D:\LEVELS\LX2\") */
    g_eax = 0x00010F80u;
    AMPED2_GCALL(sub_000122B0);
    g_esp -= 4; MEM32(g_esp) = key;         /* session.SetLevelFile(file) */
    g_ecx = 0x003AD748u;
    AMPED2_GCALL(sub_00020C30);
    g_eax = key + 4;                        /* session.LevelPath = path */
    g_ebx = 0x003AD758u;
    AMPED2_GCALL(sub_00013800);
    g_ecx = 0x003AD748u;                    /* session -> SessionDetails */
    AMPED2_GCALL(sub_000200B0);
    MEM32(MEM32(0x003ACD14u) + 0x94) = 0xFFFFFFFFu;
    {
        uint32_t obj = MEM32(0x003AD0DCu), va = MEM32(MEM32(obj) + 0x58);
        recomp_func_t fn = recomp_lookup_manual(va);
        if (!fn) fn = recomp_lookup(va);
        g_ecx = obj;
        if (fn) AMPED2_GCALL(fn);
    }
    g_ecx = key;
    AMPED2_GCALL(sub_0001A490);
    g_ecx = key + 4;
    AMPED2_GCALL(sub_0001A490);
    g_esp += 16;

    fprintf(stderr, "  [DEVCHAL] StartDevChallenge: level %s ('%s', '%s'), drop point %s\n",
            g_devchal_level, amped2_gstr(MEM32(0x003AD754u)), amped2_gstr(MEM32(0x003AD758u)),
            g_devchal_drop);
    fflush(stderr);
    g_ebx = sb; g_esi = ss; g_edi = sd; g_ebp = sp;
    SET_LO8(g_eax, 0);
    g_esp += 8;                             /* ret 4 */
}

/* Has the run in progress been won? Its challenge (drop point +0x10) state
 * +4 turns 2 or 3, which the drop-point menu shows as "Completed". Checked
 * every frame of the end-of-run update and once more on the way out. */
static void amped2_devchal_poll(void)
{
    static int fake = -1;
    uint32_t chal, st;
    if (!g_devchal_dp || g_devchal_counted)
        return;
    if (fake < 0)
        fake = getenv("AMPED2_DEVCHAL_FAKEWIN") != NULL;   /* tests only */
    chal = MEM32(g_devchal_dp + 0x10);
    st = chal ? MEM32(chal + 4) : 0;
    if (st == 2 || st == 3 || (fake && st == 1)) {
        g_devchal_counted = 1;
        amped2_devchal_win();
    }
}

/* The level's drop-point screen (Game.rui DropPoint, object 0x003CDF90,
 * vtable 0x003573D8) builds its menu when pushed, slot 6 sub_0010BCB0
 * (thiscall, `ret 4`). With a developer challenge pending, start its drop
 * point straight away, as ChooseDropPoint() (sub_0010DA50) does for the
 * menu's selected item: the drop point is IsDebugOnly, so it is not in the
 * menu, and the selected item lends it its slot for the call. */
static void amped2_droppoint_push(void)
{
    uint32_t self = g_ecx, ret;
    uint32_t sb = g_ebx, ss = g_esi, sd = g_edi, sp = g_ebp;
    sub_0010BCB0();
    ret = g_eax;
    if (g_devchal_pending) {
        uint32_t mgr = MEM32(MEM32(MEM32(0x003ACDC8u) + 0x24) + 0x58);
        uint32_t list = MEM32(self + 0x3C), dp = 0, item = 0, i, n, sel = 0;
        n = mgr ? MEM32(mgr + 0xC) : 0;
        for (i = 0; i < n && !dp; i++) {
            uint32_t d = MEM32(MEM32(mgr + 8) + 4 * i);
            if (amped2_ieq(amped2_gstr(MEM32(d + 0x4C)), g_devchal_drop))
                dp = d;
        }
        n = list ? MEM32(list + 0x50) : 0;
        for (i = 0; i < n && !item; i++) {
            uint32_t it = MEM32(MEM32(list + 0x4C) + 4 * i);
            if (it && MEM32(it + 0x20) && !amped2_ieq(amped2_gstr(MEM32(it + 8)), "Locked")) {
                item = it;
                sel = i;
            }
        }
        fprintf(stderr, "  [DEVCHAL] drop-point screen: %s -> dp %08X, menu item %u of %u\n",
                g_devchal_drop, dp, sel, n);
        if (dp && item) {
            uint32_t old = MEM32(item + 0x20);
            MEM32(list + 0x24) = sel;
            MEM32(item + 0x20) = dp;
            MEM32(self + 0x7C) = 0;         /* 0.0f: the screen's input delay */
            g_ecx = self;
            g_esp -= 4; MEM32(g_esp) = 0;   /* the (unused) call arguments */
            AMPED2_GCALL(sub_0010DA50);
            MEM32(item + 0x20) = old;
            snprintf(g_devchal_playing, sizeof g_devchal_playing, "%s", g_devchal_drop);
            g_devchal_dp = dp;
            g_devchal_counted = 0;
        }
        g_devchal_pending = 0;
        fflush(stderr);
    } else if (g_devchal_playing[0]) {
        amped2_devchal_poll();
        /* Back at the drop points after the run ("Choose new run", "New
         * run"): a developer challenge has no menu here, so leave for the
         * DEVELOPER CHALLENGES list. */
        fprintf(stderr, "  [DEVCHAL] drop-point screen after %s: back to the list\n",
                g_devchal_playing);
        fflush(stderr);
        g_devchal_return = 1;
        g_esp -= 4; MEM32(g_esp) = 0;
        AMPED2_GCALL(sub_00102360);         /* LaunchShellToCareerLevelSelect() */
    }
    g_ebx = sb; g_esi = ss; g_edi = sd; g_ebp = sp;
    g_eax = ret;
}

/* Leaving the mountain during or after a developer challenge (pause menu
 * LaunchShellToMainMenu sub_001022A0, end-of-run EORLeaveMountain
 * sub_0010FED0 and EORChangeMountain sub_0010FEA0; all thiscall `ret 4`)
 * goes to the career's level select instead, which the shell's PushMenu
 * then turns into the DEVELOPER CHALLENGES list. */
static void amped2_devchal_leave(void (*orig)(void))
{
    if (g_devchal_playing[0]) {
        amped2_devchal_poll();
        fprintf(stderr, "  [DEVCHAL] leaving %s: back to the list\n", g_devchal_playing);
        fflush(stderr);
        g_devchal_return = 1;
        sub_00102360();                     /* same stack: ret 4 */
    } else {
        orig();
    }
}
static void amped2_leave_main(void) { amped2_devchal_leave(sub_001022A0); }
static void amped2_leave_eor(void) { amped2_devchal_leave(sub_0010FED0); }
static void amped2_leave_change(void) { amped2_devchal_leave(sub_0010FEA0); }

/* The GUI's PushMenu (vtable 0x0036C868 +0x50, sub_002194B0, thiscall, one
 * stack argument: the name, a String). When the shell starts after a
 * developer challenge it pushes Main, MainCareer and LevelSelect (its
 * start-up switch on [[0x003ACD0C]+0x54] = 5, at 0x00100B9B); LevelSelect
 * becomes the list (PlayerFeedback). The name is a String the wrapper makes
 * once and keeps at 0x00010FC0. */
#define AMPED2_DEVLIST_STR_VA  0x00010FC0u
#define AMPED2_DEVLIST_NAME_VA 0x00010FC4u
static void amped2_pushmenu(void)
{
    uint32_t name = MEM32(g_esp + 4);
    if (g_devchal_return && name
        && amped2_ieq(amped2_gstr(MEM32(name)), "LevelSelect")) {
        if (!MEM32(AMPED2_DEVLIST_STR_VA)) {
            uint32_t sb = g_ebx, ss = g_esi, sd = g_edi, sc = g_ecx;
            amped2_put_cstr(AMPED2_DEVLIST_NAME_VA, "PlayerFeedback");
            g_esp -= 4; MEM32(g_esp) = AMPED2_DEVLIST_STR_VA;
            g_eax = AMPED2_DEVLIST_NAME_VA;
            AMPED2_GCALL(sub_000122B0);
            g_ebx = sb; g_esi = ss; g_edi = sd; g_ecx = sc;
        }
        MEM32(g_esp + 4) = AMPED2_DEVLIST_STR_VA;
        g_devchal_return = 0;
        g_devchal_playing[0] = 0;
        g_devchal_dp = 0;
        fprintf(stderr, "  [DEVCHAL] shell: LevelSelect -> the DEVELOPER CHALLENGES list\n");
        fflush(stderr);
    }
    sub_002194B0();
}

/* The level session's update (vtable 0x00344860, sub_00018B40, thiscall,
 * `ret 8`; the flow object 0x003AD688, +0x10 = the player). It runs the
 * end of a run (results, rewards); each frame looks for a developer
 * challenge's win.
 *
 * A stat point goes through the game's own skill-point check: end-of-run
 * state +0x28 = 2 (sub-state +0x1C = 0, flow +0x20 = 0) runs sub_00017840,
 * where sub_000469E0 gives a point for every two steps the player's +0x2DD
 * climbs to +0x2DE (NumScoreChalDone, the REWARD_SCORESKILLPOINTS count),
 * then the "EarnedSkillPoints" message and the SkillPoints_InGame screen.
 * +0x2DE goes up by two per point due for that one frame and both come back
 * down after, so the career's count stays as it was (+0x2DD is not saved:
 * the career load sets it to +0x2DE). */
static void amped2_session_update(void)
{
    uint32_t sess = g_ecx, player = MEM32(sess + 0x10), bump = 0;
    static uint32_t last = 0xFFFFFFFFu;
    static int trace = -1;
    if (trace < 0)
        trace = getenv("AMPED2_DEVCHAL_TRACE") != NULL;
    if (trace) {
        uint32_t chal = g_devchal_dp ? MEM32(g_devchal_dp + 0x10) : 0;
        uint32_t now = (MEM32(sess + 0x20) << 24) | (MEM32(sess + 0x1C) << 16)
                       | (MEM32(sess + 0x28) << 8) | (chal ? MEM32(chal + 4) & 0xFF : 0xFF);
        if (now != last) {
            fprintf(stderr, "  [DEVCHAL] session flow %u sub %u end %u chal %d 2DD %u 2DE %u\n",
                    MEM32(sess + 0x20), MEM32(sess + 0x1C), MEM32(sess + 0x28),
                    chal ? (int)MEM32(chal + 4) : -1, player ? MEM8(player + 0x2DD) : 0,
                    player ? MEM8(player + 0x2DE) : 0);
            fflush(stderr);
            last = now;
        }
    }
    amped2_devchal_poll();
    if (g_devchal_award > 0 && player && MEM32(sess + 0x20) == 0 && MEM32(sess + 0x1C) == 0
        && MEM32(sess + 0x28) == 2 && MEM8(player + 0x2DD) == MEM8(player + 0x2DE)
        && MEM8(player + 0x2DE) + 2 * g_devchal_award < 256) {
        bump = 2u * (uint32_t)g_devchal_award;
        MEM8(player + 0x2DE) += (uint8_t)bump;
    }
    sub_00018B40();
    if (bump) {
        int given = (int)(MEM8(player + 0x2DD) - (MEM8(player + 0x2DE) - bump)) / 2;
        MEM8(player + 0x2DE) -= (uint8_t)bump;
        MEM8(player + 0x2DD) -= (uint8_t)(2 * given);
        fprintf(stderr, "  [DEVCHAL] skill-point check: %d stat point(s) given\n", given);
        fflush(stderr);
        if (given > 0) {
            g_devchal_points += given;
            g_devchal_award -= given;
            amped2_devchal_save();
        }
    }
}

void sub_00218140(void)
{
    uint32_t self = g_ecx, ret;
    sub_00218140_gen();
    ret = g_eax;
    amped2_register_command(self, "QuitGame", AMPED2_QUIT_FN_VA, AMPED2_QUIT_NAME_VA);
    amped2_register_command(self, "StartDevChallenge", AMPED2_DEVCHAL_FN_VA,
                            AMPED2_DEVCHAL_NAME_VA);
    fprintf(stderr, "  [MOD] shell commands QuitGame, StartDevChallenge registered\n");
    fflush(stderr);
    g_eax = ret;
}

/* Names other hand-written files call. The recompiler keeps the sub_ name of
 * every function this file mentions, whatever the Ghidra pass calls it; it
 * does not scan src/lua_probe.c, whose copy of sub_000F24C0 calls the CRT
 * longjmp. Without this, that call had to use the Ghidra name
 * (longjmp_0025B8FC), and a checkout without the cached Ghidra export
 * failed to link. */
extern void sub_0025B8FC(void);             /* longjmp */

/* ── Menu mod: PC settings in Options -> Game Options ─────────────────
 *
 * The Game Options menu object (vtable 0x00367DA0) keeps its four rows in
 * +0x40 vibration, +0x44 camera distance, +0x48 button layout, +0x4C hints.
 * sub_001EE6A0 (eax = the menu) shows them when the screen opens: for each
 * row, sub_002116F0(ecx = row, eax = combo index, push the list control
 * [menu+0x3C]), `ret 4`. Changing a value runs the GUI action
 * GameOptions_ComboChanged(listIndex, comboItemIndex), the command
 * sub_001EE7E0 (thiscall, one stack argument: the call's arguments, an
 * array of 12-byte values at [arg+0x84], the value at +4); its switch knows
 * rows 0-3 and ignores any other.
 *
 * The menu mod (tools/mods/menus.py) adds two rows to the scene, bound to
 * the two free item slots on screen: 4 Window (windowed / full screen) and
 * 5 Resolution (1x-4x). Their values come from the settings in effect and
 * are written back to amped2.ini. Window applies at once; Resolution at the
 * next start, which its help text says. A third row would make the list
 * scroll, and the value boxes do not scroll with it.
 */
#define AMPED2_OPT_WINDOW     4
#define AMPED2_OPT_RESOLUTION 5

extern void sub_001EE6A0_gen(void);
extern void sub_001EE7E0_gen(void);
extern void sub_002116F0(void);
extern void amped2_ini_set(const char *section, const char *key,
                           const char *value);       /* main.c */
extern void xbox_SetFullscreen(int on);               /* toolkit fb_present.c */
extern int xbox_IsFullscreen(void);

static uint32_t amped2_opt_current(int row)
{
    const char *e;
    int v;
    switch (row) {
    case AMPED2_OPT_WINDOW:
        return xbox_IsFullscreen() ? 1 : 0;
    case AMPED2_OPT_RESOLUTION:
        e = getenv("RECOMP_GPU_SCALE");
        v = e ? atoi(e) : 1;
        return (uint32_t)(v < 1 ? 0 : v > 4 ? 3 : v - 1);
    }
    return 0;
}

void sub_001EE6A0(void)
{
    uint32_t menu = g_eax, saved_ebx = g_ebx;
    int row;

    sub_001EE6A0_gen();                     /* the four rows; pops our return */
    for (row = AMPED2_OPT_WINDOW; row <= AMPED2_OPT_RESOLUTION; row++) {
        g_esp -= 4; MEM32(g_esp) = MEM32(menu + 0x3C);
        g_esp -= 4; MEM32(g_esp) = 0;       /* return address */
        g_ecx = (uint32_t)row;
        g_eax = amped2_opt_current(row);
        sub_002116F0();                     /* ret 4 */
    }
    g_ebx = saved_ebx;
}

void sub_001EE7E0(void)
{
    uint32_t arg = MEM32(g_esp + 4);
    uint32_t count = MEM32(arg + 0x88), values = MEM32(arg + 0x84);
    uint32_t row, combo;
    char buf[16];

    if (count < 2) {
        sub_001EE7E0_gen();
        return;
    }
    row = MEM32(values + 4);
    combo = MEM32(values + 0xC + 4);
    if (row < AMPED2_OPT_WINDOW || row > AMPED2_OPT_RESOLUTION) {
        sub_001EE7E0_gen();
        return;
    }
    switch (row) {
    case AMPED2_OPT_WINDOW:
        xbox_SetFullscreen(combo == 1);
        amped2_ini_set("Display", "WindowMode",
                       combo == 1 ? "borderless" : "windowed");
        break;
    case AMPED2_OPT_RESOLUTION:
        snprintf(buf, sizeof buf, "%u", combo + 1);
        amped2_ini_set("Display", "RenderScale", buf);
        break;
    }
    SET_LO8(g_eax, 0);
    g_esp += 8;                             /* ret 4 */
}

/* ── Menu mod: Options and Mods -> Mods ───────────────────────────────
 *
 * The Mods screen is the Xbox Live options screen with new rows: the menu
 * mod (tools/mods/menus.py) drops XBOX LIVE OPTIONS from the Options list
 * and adds MODS, which pushes the same menu, "Options_Online" (object
 * 0x003E3CC0, vtable 0x00367C98), whose scene it rewrites. Its layout is
 * Game Options': combo rows, each with a value list.
 *
 * sub_001ED950 is the menu's enter (vtable +0x18, thiscall, `ret 4`): it
 * finds the list control ([menu+0x3C]), reads the Live settings from the
 * profile and shows them in rows 0 and 1 with sub_002116F0 (ecx = row,
 * eax = combo index, push the list). The wrapper lets it run and then shows
 * the Mods values over them. Changing a value runs
 * LiveOptions_ComboChanged(listIndex, comboItemIndex), the command
 * sub_001EDF30 (same calling convention as GameOptions_ComboChanged),
 * replaced here: it wrote the Live settings, which no one uses now, and the
 * exit (sub_001ED9B0) saves those to the profile unchanged.
 *
 * Rows 0 and 1, each OFF / ON (combo 0 / 1):
 *   0  MOD PACKS     [Game] ModPacks     (mods.json packs, mods\loose)
 *   1  TEXTURE PACK  [Game] TexturePack  (mods\texture_pack)
 * Both are read once at start-up (main.c mod_packs), so they apply after a
 * restart. The environment variable is updated too, so the screen shows
 * the new value when it is opened again.
 *
 * Rows 2 and 3 (the menu mod binds them to the free item slots 3 and 4):
 *   2  UPSCALING   STANDARD / FSR          [Display] Upscale  bilinear / FSR
 *   3  SHARPENING  OFF / LOW / MEDIUM / HIGH  [Display] Sharpen  0 / 0.4 / 0.8 / 1
 * They apply at once (the toolkit's xbox_GpuSetPost) and are saved. Both
 * are written whenever either changes, so the next start shows the same
 * picture: Sharpen left out of the ini means 0.8 with FSR and 0 without.
 *
 * Row 4 (item slot 5):
 *   4  SNOWMEN AND GAPS  NORMAL / FAR / VERY FAR  [Game] MarkerDistance 1 / 2 / 4
 * How far away snowmen and gap sparkles are drawn (see "Marker distance"
 * below); applies at once and is saved.
 */
#define AMPED2_MODS_ROWS    2
#define AMPED2_OPT_UPSCALE  2
#define AMPED2_OPT_SHARPEN  3
#define AMPED2_OPT_MARKERS  4

static const char *const k_marker_names[4] = { "1", "2", "4", "always" };

static uint32_t amped2_marker_index(void);   /* below, with the markers */

static const struct { const char *key, *var; } k_mods_rows[AMPED2_MODS_ROWS] = {
    { "ModPacks",    "AMPED2_MOD_PACKS" },
    { "TexturePack", "AMPED2_TEXTURE_PACK" },
};

static const float k_sharpen_levels[4] = { 0.0f, 0.4f, 0.8f, 1.0f };
static const char *const k_sharpen_names[4] = { "0", "0.4", "0.8", "1" };

extern void xbox_GpuSetPost(int upscale, float sharpen);   /* toolkit nv2a_d3d11.c */

static int amped2_upscale_on(void)
{
    /* "fsr" or "fsr1", any case (the toolkit's test), without _stricmp,
     * which POSIX lacks. */
    const char *e = getenv("RECOMP_GPU_UPSCALE");
    return e && (e[0] | 0x20) == 'f' && (e[1] | 0x20) == 's' && (e[2] | 0x20) == 'r'
             && (!e[3] || (e[3] == '1' && !e[4]));
}

/* The sharpening in effect, as the nearest of the four levels. */
static uint32_t amped2_sharpen_level(void)
{
    const char *e = getenv("RECOMP_GPU_SHARPEN");
    float v = (e && *e) ? (float)atof(e) : amped2_upscale_on() ? 0.8f : 0.0f;
    uint32_t i, best = 0;
    for (i = 1; i < 4; i++) {
        float d = v - k_sharpen_levels[i], db = v - k_sharpen_levels[best];
        if (d * d < db * db)
            best = i;
    }
    return best;
}

static void amped2_setenv(const char *var, const char *value)
{
#if defined(_WIN32)
    char buf[96];
    snprintf(buf, sizeof buf, "%s=%s", var, value);
    _putenv(buf);
#else
    setenv(var, value, 1);
#endif
}

static void amped2_set_picture(int upscale, uint32_t level)
{
    const char *up = upscale ? "FSR" : "bilinear";
    amped2_setenv("RECOMP_GPU_UPSCALE", up);
    amped2_setenv("RECOMP_GPU_SHARPEN", k_sharpen_names[level]);
    amped2_ini_set("Display", "Upscale", up);
    amped2_ini_set("Display", "Sharpen", k_sharpen_names[level]);
    xbox_GpuSetPost(upscale, k_sharpen_levels[level]);
}

extern void sub_001ED950_gen(void);

void sub_001ED950(void)
{
    uint32_t menu = g_ecx, saved_ebx = g_ebx;
    int row;

    sub_001ED950_gen();                     /* the Live rows; pops our return */
    for (row = 0; row <= AMPED2_OPT_MARKERS; row++) {
        g_esp -= 4; MEM32(g_esp) = MEM32(menu + 0x3C);
        g_esp -= 4; MEM32(g_esp) = 0;       /* return address */
        g_ecx = (uint32_t)row;
        if (row == AMPED2_OPT_UPSCALE) {
            g_eax = (uint32_t)amped2_upscale_on();
        } else if (row == AMPED2_OPT_SHARPEN) {
            g_eax = amped2_sharpen_level();
        } else if (row == AMPED2_OPT_MARKERS) {
            g_eax = amped2_marker_index();
        } else {
            const char *v = getenv(k_mods_rows[row].var);
            g_eax = (v && *v == '0') ? 0 : 1;
        }
        sub_002116F0();                     /* ret 4 */
    }
    g_ebx = saved_ebx;
}

void sub_001EDF30(void)
{
    uint32_t arg = MEM32(g_esp + 4);
    uint32_t count = MEM32(arg + 0x88), values = MEM32(arg + 0x84);
    uint32_t row, combo;

    if (count >= 2) {
        row = MEM32(values + 4);
        combo = MEM32(values + 0xC + 4);
        if (row < AMPED2_MODS_ROWS) {
            const char *on = combo ? "1" : "0";
            amped2_ini_set("Game", k_mods_rows[row].key, on);
            amped2_setenv(k_mods_rows[row].var, on);
        } else if (row == AMPED2_OPT_UPSCALE) {
            amped2_set_picture(combo != 0, amped2_sharpen_level());
        } else if (row == AMPED2_OPT_SHARPEN && combo < 4) {
            amped2_set_picture(amped2_upscale_on(), combo);
        } else if (row == AMPED2_OPT_MARKERS && combo < 4) {
            amped2_setenv("AMPED2_MARKER_DISTANCE", k_marker_names[combo]);
            amped2_ini_set("Game", "MarkerDistance", k_marker_names[combo]);
        }
    }
    SET_LO8(g_eax, 0);
    g_esp += 8;                             /* ret 4 */
}

/* ── Marker distance: snowmen and gaps seen from further away ─────────
 *
 * The game drops a scripted object from the picture once it would look too
 * small on screen. YetiScriptedObject's visibility test (vtable 0x003627C0
 * +0x3C, 0x001B1BC0, thiscall, ret) moves the object's bounding sphere
 * ([obj+0x34], class vtable 0x0035C918: centre and radius at [[vol+4]]) to
 * the object and asks it whether the camera sees it (sphere vtable +8,
 * 0x001412B0, thiscall, [esp+4] = matrix, [esp+8] = camera, ret 8). That
 * test takes the sphere's depth along the camera's view direction, and when
 * radius / depth is below [0x00380F20] (0.02; [0x0036E894], 0.05, while
 * [0x003ACF44] is set) the object is not drawn; then it checks the frustum
 * planes. A snowman (radius 1.3) is therefore cut at about 65 m. The result
 * goes to [obj+0x9D], which the object's render (0x0023C450) requires.
 *
 * Snowmen are the "ExplorationItem<n>" objects ([obj+8] = name; eight a
 * mountain). The gap markers are challenge objects (ChallengeScriptedObject,
 * vtable 0x00361798; its test is the last slot, 0x001A2460, the same shape
 * with the sphere at [[obj+0xA4]+0x4C]). Their type is [obj+0xAC], the
 * number 0x001A1810 gives their name: 0x15 GapSparkleField (a gap's end),
 * 0x16-0x1F GapSparkle1-10 along the gap's path (the Gaps\Gap<n>.lua
 * points), 0x20-0x29 ProSparkle1-10. While one of these is tested, both
 * size limits are divided by the setting, so it is drawn that many times
 * further away; the frustum test and every other object are unchanged.
 * "always" drops the size limit for them altogether: a marker in the view
 * is drawn at any distance (the frustum's five planes have no far one).
 *
 * The snowman's model tests its parts once more while it draws: its render
 * (0x0023C450, thiscall, ret 4) calls the model's draw ([[obj+0x30]]+0x18,
 * 0x0015E1C0), and each group node in its tree (vtable 0x0035D5C0, draw
 * 0x0015EB80) puts its own sphere ([node+0x24], radius about 2) through the
 * same camera test (from 0x0015EBB8) before drawing its children. That test
 * is therefore also widened while a snowman draws; without it the snowman
 * passed but its parts were still cut at the original distance.
 * The level's fog would still hide a white snowman in white haze, so with
 * "always" a snowman is also drawn without fog: its render is bracketed by
 * two NO_OPERATION methods in D3D's push buffer that the toolkit's executor
 * reads as "fog off" and "fog back" (0x52460001 / 0x52460000).
 *
 * [Game] MarkerDistance=1 (default), 2, 4 or always: AMPED2_MARKER_DISTANCE,
 * row 4 of the Mods and Graphics screen, applies at once.
 * AMPED2_MARKER_PROBE=1 logs the first test of each sphere caller (return
 * address, centre, radius), the camera's planes once, and every visibility
 * change of the scripted objects with the depth of a marker.
 */
#define AMPED2_SIZE_LIMIT       0x00380F20u
#define AMPED2_SIZE_LIMIT_ALT   0x0036E894u

static int g_marker_test;                   /* a marker's test is running */

static float g_marker_depth;                /* of the last marker tested */

static int amped2_marker_always(const char *e)
{
    return e && (e[0] | 0x20) == 'a';
}

/* The factor the size limits are divided by; 0 = no limit ("always"). */
static float amped2_marker_scale(void)
{
    const char *e = getenv("AMPED2_MARKER_DISTANCE");
    float v;
    if (amped2_marker_always(e))
        return 0.0f;
    v = (e && *e) ? (float)atof(e) : 1.0f;
    return v < 1.0f ? 1.0f : v > 8.0f ? 8.0f : v;
}

/* The setting as the menu row's value: Normal, Far, Very far, Always. */
static uint32_t amped2_marker_index(void)
{
    float f = amped2_marker_scale();
    return f == 0.0f ? 3 : f >= 3.0f ? 2 : f >= 1.5f ? 1 : 0;
}

static int amped2_marker_probe(void)
{
    static int on = -1;
    if (on < 0) {
        const char *e = getenv("AMPED2_MARKER_PROBE");
        on = e && *e && *e != '0';
    }
    return on;
}

static int amped2_name_starts(uint32_t name_va, const char *prefix)
{
    const char *n;
    size_t i;
    if (name_va < 0x10000u || name_va >= 0x08000000u)
        return 0;
    n = (const char *)XBOX_PTR(name_va);
    for (i = 0; prefix[i]; i++)
        if (n[i] != prefix[i])
            return 0;
    return 1;
}

extern void sub_001412B0_gen(void);

void sub_001412B0(void)
{
    float scale, a = 0, b = 0;
    uint32_t cam = MEM32(g_esp + 8);

    if (amped2_marker_probe()) {
        static uint32_t seen[64];
        static int nseen;
        uint32_t ret = MEM32(g_esp), sph = MEM32(g_ecx + 4);
        int k;
        for (k = 0; k < nseen && seen[k] != ret; k++)
            ;
        if (k == nseen && nseen < 64) {
            seen[nseen++] = ret;
            amped2_diag("[MARK] sphere test from %08X: %.1f %.1f %.1f r %.2f\n", ret,
                        MEMF(sph), MEMF(sph + 4), MEMF(sph + 8), MEMF(sph + 0xC));
        }
    }
    if (!g_marker_test || (scale = amped2_marker_scale()) == 1.0f) {
        sub_001412B0_gen();
        return;
    }
    a = MEMF(AMPED2_SIZE_LIMIT);
    b = MEMF(AMPED2_SIZE_LIMIT_ALT);
    MEMF(AMPED2_SIZE_LIMIT) = scale > 0.0f ? a / scale : 0.0f;
    MEMF(AMPED2_SIZE_LIMIT_ALT) = scale > 0.0f ? b / scale : 0.0f;
    sub_001412B0_gen();
    MEMF(AMPED2_SIZE_LIMIT) = a;
    MEMF(AMPED2_SIZE_LIMIT_ALT) = b;
    if (amped2_marker_probe()) {
        /* The test leaves the sphere's world centre at 0x003E92F8; the
         * camera's position is at +0x80, its view direction at +0x70. */
        static int planes;
        int i;
        g_marker_depth = (MEMF(0x003E92F8) - MEMF(cam + 0x80)) * MEMF(cam + 0x70)
                       + (MEMF(0x003E92FC) - MEMF(cam + 0x84)) * MEMF(cam + 0x74)
                       + (MEMF(0x003E9300) - MEMF(cam + 0x88)) * MEMF(cam + 0x78);
        if (!planes++) {
            amped2_diag("[MARK] view dir %.3f %.3f %.3f\n", MEMF(cam + 0x70),
                        MEMF(cam + 0x74), MEMF(cam + 0x78));
            for (i = 0; i < 5; i++) {
                uint32_t pl = cam + 0x110 + 0x10 * (uint32_t)i;
                amped2_diag("[MARK] plane +%X: %.3f %.3f %.3f d %.1f\n", 0x110 + 0x10 * i,
                            MEMF(pl), MEMF(pl + 4), MEMF(pl + 8), MEMF(pl + 0xC));
            }
        }
    }
}

/* A visibility test (thiscall, ret) run with the marker flag set when the
 * object is a marker; the probe logs each change of its result. */
static void amped2_marker_vis(void (*gen)(void), int marker)
{
    uint32_t obj = g_ecx;

    g_marker_test = marker;
    gen();
    g_marker_test = 0;
    if (amped2_marker_probe()) {
        static uint32_t seen[512];
        static uint8_t last[512];
        static int nseen;
        int k;
        for (k = 0; k < nseen && seen[k] != obj; k++)
            ;
        if (k == nseen && nseen < 512) {
            seen[nseen++] = obj;
            last[k] = 2;
        }
        if (k < nseen && last[k] != LO8(g_eax)) {
            uint32_t n = MEM32(obj + 8);
            last[k] = LO8(g_eax);
            amped2_diag("[MARK] %08X %s%s -> %u (depth %.0f)\n", obj,
                        (n >= 0x10000u && n < 0x08000000u) ? (const char *)XBOX_PTR(n) : "?",
                        marker ? " (marker)" : "", LO8(g_eax),
                        marker ? g_marker_depth : 0.0f);
        }
    }
}

extern void sub_001B1BC0_gen(void);

void sub_001B1BC0(void)                     /* YetiScriptedObject */
{
    amped2_marker_vis(sub_001B1BC0_gen,
                      amped2_name_starts(MEM32(g_ecx + 8), "ExplorationItem"));
}

extern void sub_001A2460_gen(void);

void sub_001A2460(void)                     /* ChallengeScriptedObject */
{
    uint32_t type = MEM32(g_ecx + 0xAC);
    amped2_marker_vis(sub_001A2460_gen, type >= 0x15 && type <= 0x29);
}

/* One method into D3D's push buffer, as the XDK's own writers do: the
 * device is [0x0032CEF8], [dev] the write pointer and [dev+4] the point
 * where 0x0031E940 (stdcall, its two arguments from [0x0032DDC4]) has to
 * make room first. */
static void amped2_pb_nop(uint32_t param)
{
    uint32_t dev = MEM32(0x0032CEF8), put, saved_eax = g_eax;

    if (!dev)
        return;
    put = MEM32(dev);
    if (put >= MEM32(dev + 4)) {
        uint32_t n = MEM32(0x0032DDC4);
        g_esp -= 4; MEM32(g_esp) = n;
        g_esp -= 4; MEM32(g_esp) = n >> 1;
        g_esp -= 4; MEM32(g_esp) = 0;       /* return address */
        sub_0031E940();                     /* ret 8 */
        put = g_eax;
    }
    MEM32(put) = 0x00040100u;               /* NO_OPERATION, one parameter */
    MEM32(put + 4) = param;
    MEM32(dev) = put + 8;
    g_eax = saved_eax;
}

extern void sub_0023C450_gen(void);

void sub_0023C450(void)                     /* YetiScriptedObject render */
{
    uint32_t obj = g_ecx;
    int snowman = MEM8(obj + 0x9D)
               && amped2_name_starts(MEM32(obj + 8), "ExplorationItem");
    int fogless = snowman && amped2_marker_scale() == 0.0f;

    if (fogless)
        amped2_pb_nop(0x52460001u);
    g_marker_test = snowman;                /* its nodes' tests (0x0015EB80) */
    sub_0023C450_gen();
    g_marker_test = 0;
    if (fogless)
        amped2_pb_nop(0x52460000u);         /* keeps the result in g_eax */
}

/* ── Text aspect in the 16:9 mode ─────────────────────────────
 * The GUI draws on a 640x480 canvas. A scene's root is Scale(W/640, H/480),
 * (2.0, 1.5) at 1280x720, so text not under an AspectCorrect anchor comes
 * out 1.33x too wide. Every string goes through Font2dStandardShader::Begin
 * (0x00248FF0, thiscall: ecx = shader, [esp+4] = text node, [esp+8] = world
 * with the node's scale folded in, ret 8), which hands the world matrix to
 * the GUI device (SetWorld, 0x00247D90: a copy at [0x0038CDFC]+0x10, applied
 * when the glyph batch is drawn). After it, a world whose x axis is longer
 * than its y axis by the screen's stretch gets its x axis scaled back, about
 * the node's alignment point, so layout and line breaks stay as they were.
 * Text under an AspectCorrect anchor is already uniform and is left alone.
 * Text node: +0x34 box left, +0x38 box right, +0x54 scale, +0x58 bits 0-2
 * alignment (0 left, 1 centre, 2 right). GUI (G = [0x0038CDF4]): +0x1380
 * and +0x1384 the screen size. ini [Display] TextAspect=0 turns it off;
 * AMPED2_TEXT_ASPECT_LOG=1 logs the first 400 strings' matrices, =<n> the
 * first n (in game, the menus before it use up 400). */
extern void sub_00248FF0_gen(void);

void sub_00248FF0(void)
{
    static int on = -1, log_left = -1;
    uint32_t node = MEM32(g_esp + 4), gui = MEM32(0x0038CDF4), w;
    float sw, sh, k, l0, l1, L, R, s, xa, t;
    unsigned align;
    int i;

    sub_00248FF0_gen();                     /* pops our return and the 2 args */
    if (on < 0) {
        const char *e = getenv("AMPED2_TEXT_ASPECT");
        on = !(e && *e == '0');
        e = getenv("AMPED2_TEXT_ASPECT_LOG");
        log_left = (e && *e && *e != '0') ? (atoi(e) > 1 ? atoi(e) : 400) : 0;
    }
    if ((!on && !log_left) || !gui || !node)
        return;
    sw = (float)MEM32(gui + 0x1380);
    sh = (float)MEM32(gui + 0x1384);
    if (sw <= 0.f || sh <= 0.f)
        return;
    k = (sh * 640.f) / (sw * 480.f);        /* 0.75 at 1280x720 */
    w = MEM32(0x0038CDFC) + 0x10;
    l0 = sqrtf(MEMF(w) * MEMF(w) + MEMF(w + 4) * MEMF(w + 4) + MEMF(w + 8) * MEMF(w + 8));
    l1 = sqrtf(MEMF(w + 16) * MEMF(w + 16) + MEMF(w + 20) * MEMF(w + 20) + MEMF(w + 24) * MEMF(w + 24));
    L = MEMF(node + 0x34); R = MEMF(node + 0x38); s = MEMF(node + 0x54);
    align = MEM8(node + 0x58) & 7;
    if (log_left > 0) {
        static uint32_t seen[512];
        uint32_t tag = node ^ ((uint32_t)(l0 > 0.f ? l1 / l0 * 100.f : 0.f) << 24), h = tag % 509;
        if (seen[h] != tag) {
            uint32_t d = MEM32(0x0038CDFC);
            seen[h] = tag;
            log_left--;
            fprintf(stderr, "  [TEXT] node %08X align %u s %.3f L %.1f R %.1f x %.3f y %.3f ratio %.3f"
                    " t %.1f %.1f | d50 %.3f %.3f %.3f %.3f d90 %.3f %.3f %.3f %.3f\n",
                    node, align, s, L, R, l0, l1, l0 > 0.f ? l1 / l0 : 0.f, MEMF(w + 0x30), MEMF(w + 0x34),
                    MEMF(d + 0x50), MEMF(d + 0x64), MEMF(d + 0x78), MEMF(d + 0x8C),
                    MEMF(d + 0x90), MEMF(d + 0xA4), MEMF(d + 0xB8), MEMF(d + 0xCC));
        }
    }
    if (!on || k > 0.99f)
        return;                             /* off, or a 4:3 screen */
    /* Stretched text is wider than tall: 0.75 for plain text, 0.96 for the
     * main menu's title (Gunship, drawn condensed to 0.78), and anything
     * between during a fly-in. Text under an AspectCorrect anchor was 1.0
     * or more on every menu screen logged (1.0, 1.29, 1.4, 1.5), so 0.98
     * splits them. The old cut at halfway (0.875) missed the titles (MAIN
     * MENU, CAREER, RIDE!) and narrowed the menu rows only at the end of
     * their fly-in, so they jumped. An A/B of both cuts into ML1 showed the
     * session menu, Challenges box and HUD unchanged. */
    if (l0 <= 0.f || l1 / l0 > 0.98f)
        return;                             /* already uniform */
    switch (align) {                        /* the anchor, in the node's unscaled units */
    case 0:  xa = s != 0.f ? L / s : 0.f; break;
    case 1:  xa = s != 0.f ? 0.5f * (L + R) / s : 0.f; break;
    case 2:  xa = s != 0.f ? R / s : 0.f; break;
    default: xa = 0.f;
    }
    t = (1.f - k) * xa;                     /* M' = T(-xa) Sx(k) T(xa) M, row vectors */
    for (i = 0; i < 4; i++) {
        MEMF(w + 0x30 + 4 * i) += t * MEMF(w + 4 * i);
        MEMF(w + 4 * i) *= k;
    }
}

recomp_func_t recomp_lookup_manual(uint32_t xbox_va)
{
    if (xbox_va == 0x00248FF0) return sub_00248FF0;  /* text aspect (vtable 0x0036E518) */
    if (xbox_va == AMPED2_QUIT_FN_VA) return amped2_cmd_quit;
    if (xbox_va == AMPED2_DEVCHAL_FN_VA) return amped2_cmd_devchal;
    if (xbox_va == 0x0010BCB0) return amped2_droppoint_push;  /* drop-point screen: push */
    if (xbox_va == 0x001022A0) return amped2_leave_main;      /* LaunchShellToMainMenu */
    if (xbox_va == 0x0010FED0) return amped2_leave_eor;       /* EORLeaveMountain */
    if (xbox_va == 0x0010FEA0) return amped2_leave_change;    /* EORChangeMountain */
    if (xbox_va == 0x002194B0) return amped2_pushmenu;        /* GUI PushMenu */
    if (xbox_va == 0x00018B40) return amped2_session_update;  /* level session update */
    if (xbox_va == 0x00218140) return sub_00218140;  /* registers QuitGame */
    if (xbox_va == 0x001EE6A0) return sub_001EE6A0;  /* Game Options: show */
    if (xbox_va == 0x001EE7E0) return sub_001EE7E0;  /* Game Options: change */
    if (xbox_va == 0x001ED950) return sub_001ED950;  /* Mods: show */
    if (xbox_va == 0x001EDF30) return sub_001EDF30;  /* Mods: change */

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
/* src/coverage.c: kind 3 unimpl, 4 icall-unresolved, 5 icall-not-code. */
void amped2_coverage_note(int kind, uint32_t va);

void recomp_icall_fail_log(uint32_t va)
{
    amped2_coverage_note(4, va);
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

    amped2_coverage_note(5, va);
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

    amped2_coverage_note(3, va);
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

/*
 * 0x00255202: XAPI's disc-drive check, called once from the startup code
 * sub_002553DC. On the console it queries the DVD drive (\Device\CdRom0)
 * and compares the disc's media information with the XBE certificate; a
 * failure ends in sub_002550E6 -> sub_00252E25, a relaunch to the dashboard.
 *
 * The port has no disc drive: it runs from the files the player extracted
 * from their own disc, so there is nothing for this check to query. It is
 * answered with STATUS_SUCCESS here, with no IOCTLs sent, so the USA and
 * the European XBE start the same way (the two differ in how they use the
 * result, at 0x0025543A).
 */
void sub_00255202(void)
{
    g_eax = 0;   /* STATUS_SUCCESS */
    g_esp += 4;  /* ret */
}

/* DirectSound's DSP mailbox (sub_00292F33, a method; this in ecx). It copies
 * a command into the mailbox block, writes the command word at block + 0x810
 * and spins until the DSP clears it. The GP is a stub here, so the toolkit's
 * DSP ack clears it. The block is *(*(this + 8) + 0x10) and is contiguous
 * memory, so its address depends on every allocation before it: main.c used
 * to name it (0x8106C810), which holds for one allocation order only and
 * hung boot with RECOMP_GUEST_RAM_MB=128 and its upper-half test. Registered
 * from here instead, before the first command is posted. */
extern void sub_00292F33_gen(void);
extern void xbox_DspAckAdd(uint32_t va);

void sub_00292F33(void)
{
    static uint32_t known;
    uint32_t a = MEM32(g_ecx + 8);
    a = a ? MEM32(a + 0x10) : 0;
    a = a ? MEM32(a) : 0;
    if (a && a + 0x810 != known) {
        known = a + 0x810;
        xbox_DspAckAdd(known);
    }
    sub_00292F33_gen();
}
