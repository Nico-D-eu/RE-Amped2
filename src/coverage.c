/*
 * coverage.c - which guessed or missing pieces of the recompiled game a run
 * actually reached.
 *
 * The generated code compiles everywhere, but some of it is a guess:
 *   unresolved-stub   a call target the disassembler never found, stubbed to
 *                     a bare return (recomp_stubs_unresolved.c);
 *   flags-fallback    a condition whose flags the lifter could not trace;
 *   unimpl            an instruction with no translation (a no-op);
 *   icall-unresolved  an indirect call to an address with no function;
 *   icall-not-code    an indirect call through a null or wild pointer.
 * A site that is never reached doesn't matter. One that is reached is where
 * the next fix is, and only play can say which -- so every run notes the
 * ones it reaches, and the long play sessions the game gets anyway build up
 * the list.
 *
 * Each address is noted once: a "[REACHED]" line in the log when it first
 * happens, and a line in amped2-coverage.txt beside the game (or
 * AMPED2_COVERAGE_FILE; "0" turns the file off). The file is read back at
 * start-up and only added to, so it collects every session's finds, with the
 * build and date each was first seen in. Lines are queued and written by a
 * background thread once a minute, and when the game quits or crashes:
 * writing a file from a game thread would cost a frame.
 *
 * The generated sites call recomp_reached() once each (RECOMP_REACHED in
 * recomp_types.h, on with RECOMP_COVERAGE); recomp_manual.c calls
 * amped2_coverage_note() for the other three.
 */

#include <windows.h>
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

/* Kinds 1 and 2 are RECOMP_REACHED_STUB and RECOMP_REACHED_FLAGS from
 * recomp_types.h, which is not included here (its names would collide with
 * windows.h); recomp_manual.c passes 3 to 5. */
enum { KINDS = 6 };
static const char *const k_kind_name[KINDS] = {
    "?", "unresolved-stub", "flags-fallback", "unimpl",
    "icall-unresolved", "icall-not-code",
};

/* An open-addressed set of (kind, address). A run finds dozens to hundreds,
 * never close to this; when it is full, further ones are only logged. */
#define SLOTS 8192
static uint64_t s_slot[SLOTS];          /* kind << 32 | va; 0 = empty */
static SRWLOCK s_lock = SRWLOCK_INIT;
static unsigned s_count[KINDS];

/* Found this session and not yet written to the file. */
#define PENDING 1024
static uint64_t s_pending[PENDING];
static int s_npending;

static char s_file[MAX_PATH];
static int s_file_on;
static char s_build[160] = "unknown";

static uint64_t key_of(int kind, uint32_t va)
{
    return ((uint64_t)(uint32_t)kind << 32) | va;
}

/* Insert (or, with insert 0, only look up) under the lock. 1 if absent. */
static int insert_or_find_locked(uint64_t key, int insert)
{
    uint32_t h = (uint32_t)(key * 0x9E3779B97F4A7C15ull >> 40) & (SLOTS - 1);
    int probe;
    for (probe = 0; probe < SLOTS; probe++) {
        uint64_t *s = &s_slot[(h + probe) & (SLOTS - 1)];
        if (*s == key)
            return 0;
        if (!*s) {
            if (insert)
                *s = key;
            return 1;
        }
    }
    return 0;
}

static int insert_locked(uint64_t key)
{
    return insert_or_find_locked(key, 1);
}

void amped2_coverage_note(int kind, uint32_t va)
{
    int is_new;
    if (kind <= 0 || kind >= KINDS)
        kind = 0;
    /* The unimpl and not-code paths can repeat in a loop: an address already
     * seen costs a shared lock and a probe. */
    AcquireSRWLockShared(&s_lock);
    is_new = insert_or_find_locked(key_of(kind, va), 0);
    ReleaseSRWLockShared(&s_lock);
    if (!is_new)
        return;
    AcquireSRWLockExclusive(&s_lock);
    is_new = insert_locked(key_of(kind, va));
    if (is_new) {
        s_count[kind]++;
        if (s_npending < PENDING)
            s_pending[s_npending++] = key_of(kind, va);
    }
    ReleaseSRWLockExclusive(&s_lock);
    if (is_new)
        fprintf(stderr, "[REACHED] %s 0x%08X\n", k_kind_name[kind], va);
}

/* RECOMP_REACHED in the generated code. */
void recomp_reached(int kind, uint32_t va)
{
    amped2_coverage_note(kind, va);
}

/* Write what is queued. Win32 file calls only, so it is safe from the quit
 * path, which must not touch stdio (see stderr_drain_quit in main.c). */
void amped2_coverage_flush(void)
{
    uint64_t batch[PENDING];
    int n, i;
    char line[256], date[16];
    time_t now = time(NULL);
    struct tm tm;
    HANDLE h;
    DWORD w;

    AcquireSRWLockExclusive(&s_lock);
    n = s_npending;
    memcpy(batch, s_pending, (size_t)n * sizeof batch[0]);
    s_npending = 0;
    ReleaseSRWLockExclusive(&s_lock);
    if (!n || !s_file_on)
        return;

    localtime_s(&tm, &now);
    strftime(date, sizeof date, "%Y-%m-%d", &tm);
    h = CreateFileA(s_file, FILE_APPEND_DATA, FILE_SHARE_READ, NULL,
                    OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE)
        return;
    if (GetFileSize(h, NULL) == 0) {
        static const char head[] =
            "# RE-Amped2 coverage: guessed or missing code that play reached.\r\n"
            "# One line per address, the first time any session reached it:\r\n"
            "# kind, guest address, date, build. Written by the game (src/coverage.c);\r\n"
            "# delete the file to start over.\r\n";
        WriteFile(h, head, sizeof head - 1, &w, NULL);
    }
    for (i = 0; i < n; i++) {
        int kind = (int)(batch[i] >> 32);
        int len = snprintf(line, sizeof line, "%s 0x%08X %s %s\r\n",
                           k_kind_name[kind < KINDS ? kind : 0],
                           (uint32_t)batch[i], date, s_build);
        if (len > 0)
            WriteFile(h, line, (DWORD)len, &w, NULL);
    }
    CloseHandle(h);
}

/* "[COVERAGE]" summary for the log: this session's totals by kind. */
void amped2_coverage_summary(void)
{
    unsigned c[KINDS];
    AcquireSRWLockShared(&s_lock);
    memcpy(c, s_count, sizeof c);
    ReleaseSRWLockShared(&s_lock);
    fprintf(stderr, "[COVERAGE] reached this session: unresolved-stub %u, "
            "flags-fallback %u, unimpl %u, icall-unresolved %u, icall-not-code %u"
            " (new ones -> %s)\n",
            c[1], c[2], c[3], c[4], c[5], s_file_on ? s_file : "no file");
}

static DWORD WINAPI flush_thread(LPVOID unused)
{
    int had = 0;
    (void)unused;
    for (;;) {
        int n;
        Sleep(60 * 1000);
        AcquireSRWLockShared(&s_lock);
        n = s_npending;
        ReleaseSRWLockShared(&s_lock);
        if (n) {
            amped2_coverage_flush();
            had = 1;
        } else if (had) {
            /* A summary once things go quiet, not on every new site. */
            amped2_coverage_summary();
            had = 0;
        }
    }
}

/* Read the file back, so addresses found by earlier sessions are not new.
 * Lines this does not understand are skipped. */
static void load_file(void)
{
    FILE *f = fopen(s_file, "rb");
    char line[256];
    int loaded = 0;
    if (!f)
        return;
    while (fgets(line, sizeof line, f)) {
        char kind[32];
        unsigned va;
        int k;
        if (line[0] == '#' || sscanf(line, "%31s 0x%x", kind, &va) != 2)
            continue;
        for (k = 1; k < KINDS; k++)
            if (!strcmp(kind, k_kind_name[k]))
                break;
        if (k < KINDS && insert_locked(key_of(k, (uint32_t)va)))
            loaded++;
    }
    fclose(f);
    fprintf(stderr, "  coverage: %d address(es) already in %s\n", loaded, s_file);
}

/* Once the game root is the working directory, before guest code runs. */
void amped2_coverage_init(const char *build)
{
    const char *e = getenv("AMPED2_COVERAGE_FILE");
    if (build && *build)
        snprintf(s_build, sizeof s_build, "%s", build);
    s_file_on = !(e && !strcmp(e, "0"));
    if (s_file_on) {
        if (!GetFullPathNameA(e && *e ? e : "amped2-coverage.txt",
                              sizeof s_file, s_file, NULL))
            s_file_on = 0;
        else
            load_file();
    }
    CloseHandle(CreateThread(NULL, 0, flush_thread, NULL, 0, NULL));
}
