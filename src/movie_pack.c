/*
 * The movie pack: higher-resolution copies of the title's movies.
 *
 * mods\movie_pack\<Name>.mp4 replaces the picture of Movies\<Name>.xmv. Only
 * the picture: the title's own XMV decoder keeps running, so its timing,
 * its audio, Start to skip and the end of the movie are all as before. When
 * the title opens a movie that has a copy (the kernel's path hook), a thread
 * decodes the copy with Media Foundation into a small ring of BGRA frames.
 * GetNextFrame's wrapper (recomp_manual.c, 0x002CDE60) reports the time of
 * each frame the title shows (decoder + 0xE4, ms), and the renderer, through
 * the toolkit's overlay source (g_xbox_overlay_source), draws the copy's
 * frame for that time in place of the 640x480 overlay surface.
 *
 * The copy is any file Media Foundation reads: H.264 in MP4 is built into
 * Windows. Its audio, if any, is ignored. tools\mods\movie_pack.py makes
 * the copies from the player's own movies (FFmpeg, optionally Real-ESRGAN).
 *
 * On by default when mods\movie_pack exists; AMPED2_MOVIE_PACK=0 (ini
 * [Game] MoviePack=0) turns it off. Windows only for now: elsewhere the
 * title's own picture shows.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

void movie_pack_frame(uint32_t ms);
void movie_pack_end(void);
void movie_pack_init(void);

#ifdef _WIN32
#define COBJMACROS
#include <windows.h>
#include <mfapi.h>
#include <mfidl.h>
#include <mfreadwrite.h>
#include "overlay_source.h"   /* the toolkit's g_xbox_overlay_source */

extern void (*g_xbox_path_hook)(const char *xbox_path);   /* kernel.h */

#define RING 4

typedef struct {
    uint8_t *px;
    uint32_t w, h;
    long long ms;
} Frame;

static CRITICAL_SECTION s_cs;
static CONDITION_VARIABLE s_cv;
static Frame s_ring[RING];
static int s_head, s_count;           /* under s_cs */
static volatile LONG s_stop;
static HANDLE s_thread;
static WCHAR s_file[MAX_PATH];
static volatile LONG s_frame_ms = -1; /* the title's current frame, -1 none */
static volatile ULONGLONG s_last_use;  /* when the renderer last took a frame */
static void (*s_prev_hook)(const char *);

/* The copy's frames, decoded ahead into the ring until it is full. */
static DWORD WINAPI decode_thread(LPVOID unused)
{
    IMFAttributes *attr = NULL;
    IMFSourceReader *rd = NULL;
    IMFMediaType *mt = NULL, *cur = NULL;
    UINT32 w = 0, h = 0;
    unsigned frames = 0;
    HRESULT hr;

    (void)unused;
    CoInitializeEx(NULL, COINIT_MULTITHREADED);
    MFStartup(MF_VERSION, MFSTARTUP_LITE);
    MFCreateAttributes(&attr, 1);
    IMFAttributes_SetUINT32(attr, &MF_SOURCE_READER_ENABLE_VIDEO_PROCESSING, TRUE);
    hr = MFCreateSourceReaderFromURL(s_file, attr, &rd);
    if (SUCCEEDED(hr)) {
        IMFSourceReader_SetStreamSelection(rd, (DWORD)MF_SOURCE_READER_ALL_STREAMS, FALSE);
        IMFSourceReader_SetStreamSelection(rd, (DWORD)MF_SOURCE_READER_FIRST_VIDEO_STREAM, TRUE);
        MFCreateMediaType(&mt);
        IMFMediaType_SetGUID(mt, &MF_MT_MAJOR_TYPE, &MFMediaType_Video);
        IMFMediaType_SetGUID(mt, &MF_MT_SUBTYPE, &MFVideoFormat_RGB32);
        hr = IMFSourceReader_SetCurrentMediaType(rd, (DWORD)MF_SOURCE_READER_FIRST_VIDEO_STREAM,
                                                 NULL, mt);
    }
    if (SUCCEEDED(hr))
        hr = IMFSourceReader_GetCurrentMediaType(rd, (DWORD)MF_SOURCE_READER_FIRST_VIDEO_STREAM,
                                                 &cur);
    if (SUCCEEDED(hr)) {   /* width in the high half, height in the low */
        UINT64 size = 0;
        hr = IMFMediaType_GetUINT64(cur, &MF_MT_FRAME_SIZE, &size);
        w = (UINT32)(size >> 32);
        h = (UINT32)size;
    }
    if (FAILED(hr) || !w || !h) {
        fprintf(stderr, "  [MOVIES] could not read %ls (0x%08lX)\n", s_file, (unsigned long)hr);
        goto done;
    }
    fprintf(stderr, "  [MOVIES] %ls: %ux%u\n", s_file, w, h);

    while (!s_stop) {
        DWORD idx, flags = 0;
        LONGLONG ts = 0;
        IMFSample *smp = NULL;
        IMFMediaBuffer *buf = NULL;
        IMF2DBuffer *b2 = NULL;
        BYTE *scan0 = NULL;
        LONG pitch = 0;
        Frame *f;
        uint32_t y;

        hr = IMFSourceReader_ReadSample(rd, (DWORD)MF_SOURCE_READER_FIRST_VIDEO_STREAM, 0,
                                        &idx, &flags, &ts, &smp);
        if (FAILED(hr) || (flags & MF_SOURCE_READERF_ENDOFSTREAM))
            break;
        if (!smp)
            continue;
        /* A free slot: the renderer frees them as the title moves on. A
         * movie skipped with Start never reports its end, so a ring nobody
         * has drawn from for 10 s ends the thread (Media Foundation and the
         * ring hold about 100 MB). */
        EnterCriticalSection(&s_cs);
        while (s_count == RING && !s_stop) {
            SleepConditionVariableCS(&s_cv, &s_cs, 100);
            if (s_count == RING && GetTickCount64() - s_last_use > 10000) {
                s_head = s_count = 0;
                InterlockedExchange(&s_stop, 1);
            }
        }
        f = &s_ring[(s_head + s_count) % RING];
        LeaveCriticalSection(&s_cs);
        if (s_stop) {
            IMFSample_Release(smp);
            break;
        }
        if (!f->px || f->w != w || f->h != h) {
            free(f->px);
            f->px = (uint8_t *)malloc((size_t)w * h * 4);
            f->w = w;
            f->h = h;
        }
        if (f->px && SUCCEEDED(IMFSample_ConvertToContiguousBuffer(smp, &buf))) {
            /* The 2D lock gives the top row and a pitch that is negative for
             * a bottom-up picture. */
            if (SUCCEEDED(IMFMediaBuffer_QueryInterface(buf, &IID_IMF2DBuffer, (void **)&b2))
                    && SUCCEEDED(IMF2DBuffer_Lock2D(b2, &scan0, &pitch))) {
                for (y = 0; y < h; y++)
                    memcpy(f->px + (size_t)y * w * 4, scan0 + (LONG_PTR)y * pitch, (size_t)w * 4);
                IMF2DBuffer_Unlock2D(b2);
            } else {
                BYTE *p = NULL;
                DWORD len = 0;
                if (SUCCEEDED(IMFMediaBuffer_Lock(buf, &p, NULL, &len))) {
                    memcpy(f->px, p, len < w * h * 4 ? len : w * h * 4);
                    IMFMediaBuffer_Unlock(buf);
                }
            }
            if (b2) IMF2DBuffer_Release(b2);
            IMFMediaBuffer_Release(buf);
        }
        IMFSample_Release(smp);
        f->ms = ts / 10000;
        EnterCriticalSection(&s_cs);
        s_count++;
        LeaveCriticalSection(&s_cs);
        frames++;
    }
    fprintf(stderr, "  [MOVIES] %ls: %u frames decoded\n", s_file, frames);
done:
    if (cur) IMFMediaType_Release(cur);
    if (mt) IMFMediaType_Release(mt);
    if (rd) IMFSourceReader_Release(rd);
    if (attr) IMFAttributes_Release(attr);
    MFShutdown();
    CoUninitialize();
    return 0;
}

/* Stop the decoder and empty the ring. */
static void stop_movie(void)
{
    if (!s_thread)
        return;
    InterlockedExchange(&s_stop, 1);
    WakeAllConditionVariable(&s_cv);
    WaitForSingleObject(s_thread, 5000);
    CloseHandle(s_thread);
    s_thread = NULL;
    EnterCriticalSection(&s_cs);
    s_head = s_count = 0;
    LeaveCriticalSection(&s_cs);
    InterlockedExchange(&s_frame_ms, -1);
}

/* The kernel's path hook: a movie being opened. */
static void on_path(const char *xbox_path)
{
    const char *base, *dot;
    WCHAR rel[MAX_PATH];
    char name[MAX_PATH];
    size_t n;

    extern int g_amped2_skip_movies;   /* PlayMovies=0 (recomp_manual.c) */

    if (s_prev_hook)
        s_prev_hook(xbox_path);
    if (g_amped2_skip_movies)
        return;
    base = strrchr(xbox_path, '\\');
    base = base ? base + 1 : xbox_path;
    dot = strrchr(base, '.');
    if (!dot || _stricmp(dot, ".xmv") != 0)
        return;
    n = (size_t)(dot - base);
    if (n == 0 || n >= sizeof name)
        return;
    memcpy(name, base, n);
    name[n] = 0;
    stop_movie();
    _snwprintf(rel, MAX_PATH, L"mods\\movie_pack\\%hs.mp4", name);
    rel[MAX_PATH - 1] = 0;
    if (GetFileAttributesW(rel) == INVALID_FILE_ATTRIBUTES
            || !GetFullPathNameW(rel, MAX_PATH, s_file, NULL))
        return;
    InterlockedExchange(&s_stop, 0);
    s_last_use = GetTickCount64();
    s_thread = CreateThread(NULL, 0, decode_thread, NULL, 0, NULL);
}

/* The renderer's side (g_xbox_overlay_source): the copy's frame for the
 * title's current frame time. Holds s_cs until release. */
static const void *acquire(uint32_t *w, uint32_t *h, uint32_t *pitch)
{
    long now = s_frame_ms;
    Frame *f;

    if (now < 0 || !s_thread)
        return NULL;
    s_last_use = GetTickCount64();
    EnterCriticalSection(&s_cs);
    /* Drop the frames the title has gone past. */
    while (s_count > 1 && s_ring[(s_head + 1) % RING].ms <= now) {
        s_head = (s_head + 1) % RING;
        s_count--;
        WakeAllConditionVariable(&s_cv);
    }
    f = s_count ? &s_ring[s_head] : NULL;
    /* Too far ahead of the title (it was skipped back) or nothing yet: the
     * title's own picture this time. */
    if (!f || !f->px || f->ms > now + 100) {
        LeaveCriticalSection(&s_cs);
        return NULL;
    }
    {   /* AMPED2_MOVIE_TRACE=1: now and then, the title's frame against ours */
        static int trace = -1;
        static unsigned n;
        if (trace < 0)
            trace = getenv("AMPED2_MOVIE_TRACE") != NULL;
        if (trace && n++ % 300 == 0)
            fprintf(stderr, "  [MOVIES] title at %ld ms, showing %lld ms (%u queued)\n",
                    now, f->ms, (unsigned)s_count);
    }
    *w = f->w;
    *h = f->h;
    *pitch = f->w * 4;
    return f->px;
}

static void release(void)
{
    LeaveCriticalSection(&s_cs);
}

static const XboxOverlaySource s_source = { acquire, release };

void movie_pack_frame(uint32_t ms)
{
    InterlockedExchange(&s_frame_ms, (LONG)ms);
}

void movie_pack_end(void)
{
    if (s_thread)
        stop_movie();
}

void movie_pack_init(void)
{
    const char *on = getenv("AMPED2_MOVIE_PACK");
    DWORD attr = GetFileAttributesW(L"mods\\movie_pack");

    if ((on && *on == '0') || attr == INVALID_FILE_ATTRIBUTES
            || !(attr & FILE_ATTRIBUTE_DIRECTORY))
        return;
    InitializeCriticalSection(&s_cs);
    InitializeConditionVariable(&s_cv);
    s_prev_hook = g_xbox_path_hook;
    g_xbox_path_hook = on_path;
    g_xbox_overlay_source = &s_source;
    fprintf(stderr, "  [MOVIES] movie pack: mods\\movie_pack\n");
}

#else  /* not Windows: the title's own pictures */

void movie_pack_frame(uint32_t ms) { (void)ms; }
void movie_pack_end(void) { }
void movie_pack_init(void) { }

#endif
