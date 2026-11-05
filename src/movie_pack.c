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
 * [Game] MoviePack=0) turns it off. On Linux and other POSIX hosts the
 * system's FFmpeg decodes instead (see the POSIX half below).
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

#else  /* POSIX: the copy decoded by FFmpeg, through a pipe */

/* There is no Media Foundation here, and linking FFmpeg's libraries would
 * tie the build to their versions, so the system's ffmpeg program decodes:
 * ffprobe lists the packets' times (no decoding, so quick), then ffmpeg
 * writes the frames as raw BGRA to a pipe, one frame per packet
 * (-vsync passthrough: FFmpeg 4.4 has no -fps_mode), in presentation order. tools/bin/ffmpeg/bin/
 * is tried first, then PATH. Otherwise as on Windows: the same ring, the
 * same hooks, the same timing. */
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <signal.h>
#include <spawn.h>
#include <strings.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
#include "overlay_source.h"   /* the toolkit's g_xbox_overlay_source */

extern void (*g_xbox_path_hook)(const char *xbox_path);   /* kernel.h */
extern char **environ;

#define RING 4

typedef struct {
    uint8_t *px;
    uint32_t w, h;
    long long ms;
} Frame;

static pthread_mutex_t s_mx = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t s_cv = PTHREAD_COND_INITIALIZER;
static Frame s_ring[RING];
static int s_head, s_count;           /* under s_mx */
static volatile int s_stop;
static int s_running;                 /* s_thread is joinable */
static pthread_t s_thread;
static volatile pid_t s_pid;          /* the decoding ffmpeg, 0 none */
static char s_file[1024];
static volatile long s_frame_ms = -1; /* the title's current frame, -1 none */
static volatile uint64_t s_last_use;  /* when the renderer last took a frame */
static void (*s_prev_hook)(const char *);

static uint64_t now_ms(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (uint64_t)t.tv_sec * 1000u + (uint64_t)t.tv_nsec / 1000000u;
}

/* The bundled tool if the install has one, else the name for PATH. */
static const char *tool(const char *name, char *buf, size_t n)
{
    snprintf(buf, n, "tools/bin/ffmpeg/bin/%s", name);
    return access(buf, X_OK) == 0 ? buf : name;
}

/* argv run with its output on a pipe (stderr to /dev/null): the pid, or -1. */
static pid_t spawn_read(char *const argv[], int *fd)
{
    posix_spawn_file_actions_t fa;
    int p[2];
    pid_t pid;

    if (pipe(p) != 0)
        return -1;
    posix_spawn_file_actions_init(&fa);
    posix_spawn_file_actions_adddup2(&fa, p[1], 1);
    posix_spawn_file_actions_addclose(&fa, p[0]);
    posix_spawn_file_actions_addclose(&fa, p[1]);
    posix_spawn_file_actions_addopen(&fa, 2, "/dev/null", O_WRONLY, 0);
    posix_spawn_file_actions_addopen(&fa, 0, "/dev/null", O_RDONLY, 0);
    if (posix_spawnp(&pid, argv[0], &fa, NULL, argv, environ) != 0)
        pid = -1;
    posix_spawn_file_actions_destroy(&fa);
    close(p[1]);
    if (pid < 0) {
        close(p[0]);
        return -1;
    }
    *fd = p[0];
    return pid;
}

static int read_full(int fd, uint8_t *buf, size_t n)
{
    while (n) {
        ssize_t got = read(fd, buf, n);
        if (got < 0 && errno == EINTR)
            continue;
        if (got <= 0)
            return 0;
        buf += got;
        n -= (size_t)got;
    }
    return 1;
}

/* A short program's whole output, NUL-terminated (malloc'd), or NULL. */
static char *run_capture(char *const argv[])
{
    size_t len = 0, cap = 1 << 16;
    char *out = (char *)malloc(cap);
    int fd, st;
    pid_t pid;

    if (!out || (pid = spawn_read(argv, &fd)) < 0) {
        free(out);
        return NULL;
    }
    for (;;) {
        ssize_t got;
        if (len + 1 >= cap) {
            char *n = (char *)realloc(out, cap * 2);
            if (!n)
                break;
            out = n;
            cap *= 2;
        }
        got = read(fd, out + len, cap - len - 1);
        if (got < 0 && errno == EINTR)
            continue;
        if (got <= 0)
            break;
        len += (size_t)got;
    }
    out[len] = 0;
    close(fd);
    waitpid(pid, &st, 0);
    if (!WIFEXITED(st) || WEXITSTATUS(st) != 0) {
        free(out);
        return NULL;
    }
    return out;
}

static int cmp_ll(const void *a, const void *b)
{
    long long x = *(const long long *)a, y = *(const long long *)b;
    return (x > y) - (x < y);
}

/* The copy's size and its frames' times in ms, sorted (presentation order). */
static int probe(uint32_t *w, uint32_t *h, long long **times, size_t *n)
{
    char tb[256], *out, *p;
    char *size_argv[] = { (char *)tool("ffprobe", tb, sizeof tb), "-v", "error",
                          "-select_streams", "v:0", "-show_entries", "stream=width,height",
                          "-of", "csv=p=0", s_file, NULL };
    char *time_argv[] = { size_argv[0], "-v", "error", "-select_streams", "v:0",
                          "-show_entries", "packet=pts_time", "-of", "csv=p=0", s_file, NULL };
    size_t cap = 0;

    *times = NULL;
    *n = 0;
    if (!(out = run_capture(size_argv)) || sscanf(out, "%u,%u", w, h) != 2
            || !*w || !*h || *w > 8192 || *h > 8192) {
        free(out);
        return 0;
    }
    free(out);
    if (!(out = run_capture(time_argv)))
        return 0;
    for (p = out; *p; ) {
        char *end;
        double t = strtod(p, &end);
        if (end == p) {                     /* "N/A" and the like: skip the line */
            while (*p && *p != '\n') p++;
            if (*p) p++;
            continue;
        }
        if (*n == cap) {
            long long *g = (long long *)realloc(*times, (cap ? cap * 2 : 4096) * sizeof **times);
            if (!g)
                break;
            *times = g;
            cap = cap ? cap * 2 : 4096;
        }
        (*times)[(*n)++] = (long long)(t * 1000.0 + 0.5);
        p = end;
        while (*p && *p != '\n') p++;
        if (*p) p++;
    }
    free(out);
    if (*n)
        qsort(*times, *n, sizeof **times, cmp_ll);
    return *n != 0;
}

/* The copy's frames, decoded ahead into the ring until it is full. */
static void *decode_thread(void *unused)
{
    char fb[256];
    char *argv[] = { (char *)tool("ffmpeg", fb, sizeof fb), "-v", "error", "-nostdin",
                     "-i", s_file, "-an", "-f", "rawvideo", "-pix_fmt", "bgra",
                     "-vsync", "passthrough", "pipe:1", NULL };
    long long *times = NULL;
    size_t ntimes = 0;
    uint32_t w = 0, h = 0;
    unsigned frames = 0, skipped = 0;
    int fd = -1, st;
    pid_t pid;

    (void)unused;
    if (!probe(&w, &h, &times, &ntimes)) {
        fprintf(stderr, "  [MOVIES] %s: ffprobe could not read it (is FFmpeg installed?)\n", s_file);
        free(times);
        return NULL;
    }
    fprintf(stderr, "  [MOVIES] %s: %ux%u, %zu frames\n", s_file, w, h, ntimes);
    if ((pid = spawn_read(argv, &fd)) < 0) {
        fprintf(stderr, "  [MOVIES] %s: ffmpeg did not start\n", s_file);
        free(times);
        return NULL;
    }
    s_pid = pid;
    while (!s_stop) {
        Frame *f;
        /* A free slot: the renderer frees them as the title moves on. A
         * movie skipped with Start never reports its end, so a ring nobody
         * has drawn from for 10 s ends the thread. */
        pthread_mutex_lock(&s_mx);
        while (s_count == RING && !s_stop) {
            struct timespec until;
            clock_gettime(CLOCK_REALTIME, &until);
            until.tv_nsec += 100000000L;
            if (until.tv_nsec >= 1000000000L) {
                until.tv_sec++;
                until.tv_nsec -= 1000000000L;
            }
            pthread_cond_timedwait(&s_cv, &s_mx, &until);
            if (s_count == RING && now_ms() - s_last_use > 10000) {
                s_head = s_count = 0;
                s_stop = 1;
            }
        }
        f = &s_ring[(s_head + s_count) % RING];
        pthread_mutex_unlock(&s_mx);
        if (s_stop)
            break;
        if (!f->px || f->w != w || f->h != h) {
            free(f->px);
            f->px = (uint8_t *)malloc((size_t)w * h * 4);
            f->w = w;
            f->h = h;
        }
        if (!f->px || !read_full(fd, f->px, (size_t)w * h * 4))
            break;                          /* the end of the movie, or stopped */
        f->ms = frames < ntimes ? times[frames]
              : (ntimes ? times[ntimes - 1] : 0) + 33 * (long long)(frames + 1 - ntimes);
        /* Late (the probes and the start take about half a second, and the
         * renderer frees slots only as often as it presents): the next
         * frame goes into this slot, so the copy catches up at FFmpeg's
         * speed instead of a few frames per present. Seen under WSL at
         * RenderScale 2: 0.3-0.5 s behind for the whole intro without it.
         * At most two in a row: when FFmpeg itself only just keeps up,
         * skipping every late frame would queue none and freeze the
         * picture. */
        if (s_frame_ms >= 0 && f->ms + 50 < s_frame_ms && frames + 1 < ntimes && skipped < 2) {
            frames++;
            skipped++;
            continue;
        }
        skipped = 0;
        pthread_mutex_lock(&s_mx);
        s_count++;
        pthread_mutex_unlock(&s_mx);
        frames++;
    }
    fprintf(stderr, "  [MOVIES] %s: %u frames decoded\n", s_file, frames);
    s_pid = 0;
    kill(pid, SIGKILL);                     /* stopped early: no more frames wanted */
    close(fd);
    waitpid(pid, &st, 0);
    free(times);
    return NULL;
}

/* Stop the decoder and empty the ring. */
static void stop_movie(void)
{
    pid_t pid;

    if (!s_running)
        return;
    s_stop = 1;
    pthread_mutex_lock(&s_mx);
    pthread_cond_broadcast(&s_cv);
    pthread_mutex_unlock(&s_mx);
    if ((pid = s_pid) > 0)
        kill(pid, SIGKILL);                 /* unblocks a read on its pipe */
    pthread_join(s_thread, NULL);
    s_running = 0;
    pthread_mutex_lock(&s_mx);
    s_head = s_count = 0;
    pthread_mutex_unlock(&s_mx);
    s_frame_ms = -1;
}

/* mods/movie_pack/<name>.mp4, whatever the case of either (the title's
 * paths and the disc's file names differ in case). */
static int find_copy(const char *name)
{
    char want[300];
    struct dirent *de;
    DIR *d = opendir("mods/movie_pack");
    int found = 0;

    if (!d)
        return 0;
    snprintf(want, sizeof want, "%s.mp4", name);
    while ((de = readdir(d)) != NULL)
        if (!strcasecmp(de->d_name, want)) {
            snprintf(s_file, sizeof s_file, "mods/movie_pack/%s", de->d_name);
            found = 1;
            break;
        }
    closedir(d);
    return found;
}

/* The kernel's path hook: a movie being opened. */
static void on_path(const char *xbox_path)
{
    const char *base, *dot;
    char name[256];
    size_t n;

    extern int g_amped2_skip_movies;   /* PlayMovies=0 (recomp_manual.c) */

    if (s_prev_hook)
        s_prev_hook(xbox_path);
    if (g_amped2_skip_movies)
        return;
    base = strrchr(xbox_path, '\\');
    base = base ? base + 1 : xbox_path;
    dot = strrchr(base, '.');
    if (!dot || strcasecmp(dot, ".xmv") != 0)
        return;
    n = (size_t)(dot - base);
    if (n == 0 || n >= sizeof name)
        return;
    memcpy(name, base, n);
    name[n] = 0;
    stop_movie();
    if (!find_copy(name))
        return;
    s_stop = 0;
    s_last_use = now_ms();
    s_running = pthread_create(&s_thread, NULL, decode_thread, NULL) == 0;
}

/* The renderer's side (g_xbox_overlay_source): the copy's frame for the
 * title's current frame time. Holds s_mx until release. */
static const void *acquire(uint32_t *w, uint32_t *h, uint32_t *pitch)
{
    long now = s_frame_ms;
    Frame *f;

    if (now < 0 || !s_running)
        return NULL;
    s_last_use = now_ms();
    pthread_mutex_lock(&s_mx);
    /* Drop the frames the title has gone past. */
    while (s_count > 1 && s_ring[(s_head + 1) % RING].ms <= now) {
        s_head = (s_head + 1) % RING;
        s_count--;
        pthread_cond_broadcast(&s_cv);
    }
    f = s_count ? &s_ring[s_head] : NULL;
    /* Too far ahead of the title (it was skipped back) or nothing yet: the
     * title's own picture this time. */
    if (!f || !f->px || f->ms > now + 100) {
        pthread_mutex_unlock(&s_mx);
        return NULL;
    }
    {   /* AMPED2_MOVIE_TRACE=1: now and then, the title's frame against ours */
        static int trace = -1;
        static unsigned k;
        if (trace < 0)
            trace = getenv("AMPED2_MOVIE_TRACE") != NULL;
        if (trace && k++ % 300 == 0)
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
    pthread_mutex_unlock(&s_mx);
}

static const XboxOverlaySource s_source = { acquire, release };

void movie_pack_frame(uint32_t ms)
{
    s_frame_ms = (long)ms;
}

void movie_pack_end(void)
{
    stop_movie();
}

void movie_pack_init(void)
{
    const char *on = getenv("AMPED2_MOVIE_PACK");
    struct stat sb;

    if ((on && *on == '0') || stat("mods/movie_pack", &sb) != 0 || !S_ISDIR(sb.st_mode))
        return;
    s_prev_hook = g_xbox_path_hook;
    g_xbox_path_hook = on_path;
    g_xbox_overlay_source = &s_source;
    fprintf(stderr, "  [MOVIES] movie pack: mods/movie_pack\n");
}

#endif
