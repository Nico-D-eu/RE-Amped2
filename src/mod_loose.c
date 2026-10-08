/*
 * Loose archive entries: single files that stand in for one entry of a
 * game archive, without rebuilding the archive with the asset toolkit.
 *
 *     mods\loose\Gui\Textures\Textures.gfx\Controller_all.xpr
 *     mods\packs\<name>\loose\GuiPackages\Base.rui\Scenes\Main.scene
 *
 * The folder named like the archive (path relative to the game dir) holds
 * entries by their path inside it. At start-up each archive that has loose
 * entries is merged into mods\cache\loose\<archive>: the archive the game
 * would otherwise read (the first overlay that has it, else game\), with
 * the loose files in place of, or added to, its entries. Untouched entries
 * are copied byte for byte; loose ones are stored uncompressed. A merged
 * archive is reused while its sources are unchanged (a .sig file beside it
 * lists them), so only the first start after an edit pays for the copy.
 *
 * The archives are plain ZIPs (no ZIP64, no data descriptors). Where an
 * archive's entries are sorted by name, ignoring case, new ones are put in
 * order; otherwise they go at the end.
 */
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define LOOSE_CACHE "mods\\cache\\loose"
#define MAX_ARCHIVES 256

static const char *const k_archive_exts[] = { ".gfx", ".res", ".rui", ".ruirr" };

/* ---- small helpers ----------------------------------------------------- */

static uint32_t crc_table[256];

static uint32_t crc32_update(uint32_t c, const uint8_t *p, size_t n)
{
    if (!crc_table[1]) {
        uint32_t k, j, v;
        for (k = 0; k < 256; k++) {
            for (v = k, j = 0; j < 8; j++)
                v = (v & 1) ? 0xEDB88320u ^ (v >> 1) : v >> 1;
            crc_table[k] = v;
        }
    }
    c = ~c;
    while (n--)
        c = crc_table[(c ^ *p++) & 0xFF] ^ (c >> 8);
    return ~c;
}

static uint16_t rd16(const uint8_t *p) { return (uint16_t)(p[0] | p[1] << 8); }
static uint32_t rd32(const uint8_t *p) { return p[0] | p[1] << 8 | p[2] << 16 | (uint32_t)p[3] << 24; }
static void wr16(uint8_t *p, uint32_t v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); }
static void wr32(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); p[2] = (uint8_t)(v >> 16); p[3] = (uint8_t)(v >> 24);
}

static int is_archive_name(const char *name)
{
    size_t n = strlen(name), i;
    for (i = 0; i < sizeof k_archive_exts / sizeof *k_archive_exts; i++) {
        size_t e = strlen(k_archive_exts[i]);
        if (n > e && !_stricmp(name + n - e, k_archive_exts[i]))
            return 1;
    }
    return 0;
}

static int file_info(const char *path, uint64_t *size, uint64_t *mtime)
{
    WIN32_FILE_ATTRIBUTE_DATA a;
    if (!GetFileAttributesExA(path, GetFileExInfoStandard, &a)
            || (a.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY))
        return 0;
    *size = ((uint64_t)a.nFileSizeHigh << 32) | a.nFileSizeLow;
    *mtime = ((uint64_t)a.ftLastWriteTime.dwHighDateTime << 32) | a.ftLastWriteTime.dwLowDateTime;
    return 1;
}

static int is_dir(const char *path)
{
    DWORD a = GetFileAttributesA(path);
    return a != INVALID_FILE_ATTRIBUTES && (a & FILE_ATTRIBUTE_DIRECTORY);
}

static void make_dirs(const char *path)          /* every directory above path */
{
    char buf[MAX_PATH], *p;
    snprintf(buf, sizeof buf, "%s", path);
    for (p = buf; *p; p++)
        if (*p == '\\') {
            *p = 0;
            CreateDirectoryA(buf, NULL);
            *p = '\\';
        }
}

/* ---- finding loose entries --------------------------------------------- */

typedef struct {
    char name[MAX_PATH];     /* entry name, '/'-separated */
    char path[MAX_PATH];     /* the loose file */
    uint64_t size, mtime;
} Loose;

typedef struct {
    Loose *v;
    int n, cap;
} LooseList;

static void loose_walk(const char *dir, const char *prefix, LooseList *out)
{
    char pat[MAX_PATH];
    WIN32_FIND_DATAA fd;
    HANDLE h;

    snprintf(pat, sizeof pat, "%s\\*", dir);
    h = FindFirstFileA(pat, &fd);
    if (h == INVALID_HANDLE_VALUE)
        return;
    do {
        char path[MAX_PATH], name[MAX_PATH];
        int i, dup = 0;
        if (!strcmp(fd.cFileName, ".") || !strcmp(fd.cFileName, ".."))
            continue;
        snprintf(path, sizeof path, "%s\\%s", dir, fd.cFileName);
        snprintf(name, sizeof name, "%s%s", prefix, fd.cFileName);
        if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) {
            strncat(name, "/", sizeof name - strlen(name) - 1);
            loose_walk(path, name, out);
            continue;
        }
        for (i = 0; i < out->n; i++)            /* an earlier pack has it */
            if (!_stricmp(out->v[i].name, name)) { dup = 1; break; }
        if (dup)
            continue;
        if (out->n == out->cap) {
            out->cap = out->cap ? out->cap * 2 : 32;
            out->v = (Loose *)realloc(out->v, (size_t)out->cap * sizeof *out->v);
        }
        snprintf(out->v[out->n].name, sizeof out->v[0].name, "%s", name);
        snprintf(out->v[out->n].path, sizeof out->v[0].path, "%s", path);
        file_info(path, &out->v[out->n].size, &out->v[out->n].mtime);
        out->n++;
    } while (FindNextFileA(h, &fd));
    FindClose(h);
}

/* Archive folders (relative paths, '\'-separated) under one loose root. */
static void find_archives(const char *root, const char *rel, char (*found)[MAX_PATH], int *n)
{
    char pat[MAX_PATH];
    WIN32_FIND_DATAA fd;
    HANDLE h;

    snprintf(pat, sizeof pat, "%s%s%s\\*", root, *rel ? "\\" : "", rel);
    h = FindFirstFileA(pat, &fd);
    if (h == INVALID_HANDLE_VALUE)
        return;
    do {
        char sub[MAX_PATH];
        int i, dup = 0;
        if (!(fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)
                || !strcmp(fd.cFileName, ".") || !strcmp(fd.cFileName, ".."))
            continue;
        snprintf(sub, sizeof sub, "%s%s%s", rel, *rel ? "\\" : "", fd.cFileName);
        if (!is_archive_name(fd.cFileName)) {
            find_archives(root, sub, found, n);
            continue;
        }
        for (i = 0; i < *n; i++)
            if (!_stricmp(found[i], sub)) { dup = 1; break; }
        if (!dup && *n < MAX_ARCHIVES)
            snprintf(found[(*n)++], MAX_PATH, "%s", sub);
    } while (FindNextFileA(h, &fd));
    FindClose(h);
}

/* ---- merging ------------------------------------------------------------ */

typedef struct {
    const uint8_t *cd;       /* central directory record (original), or NULL */
    uint32_t cd_len, lho, region_end;
    const Loose *loose;      /* replacement or new entry, or NULL */
    char name[MAX_PATH];
} Entry;

static int name_cmp(const void *a, const void *b)
{
    return _stricmp(((const Entry *)a)->name, ((const Entry *)b)->name);
}

static int lho_cmp(const void *a, const void *b)
{
    uint32_t x = (*(const Entry *const *)a)->lho, y = (*(const Entry *const *)b)->lho;
    return x < y ? -1 : x > y;
}

static int copy_bytes(FILE *in, FILE *out, uint32_t from, uint32_t len)
{
    static uint8_t buf[1 << 16];
    if (fseek(in, (long)from, SEEK_SET))
        return 0;
    while (len) {
        size_t k = len < sizeof buf ? len : sizeof buf;
        if (fread(buf, 1, k, in) != k || fwrite(buf, 1, k, out) != k)
            return 0;
        len -= (uint32_t)k;
    }
    return 1;
}

static void dos_now(uint16_t *time, uint16_t *date)
{
    SYSTEMTIME st;
    GetLocalTime(&st);
    *time = (uint16_t)(st.wHour << 11 | st.wMinute << 5 | st.wSecond / 2);
    *date = (uint16_t)((st.wYear - 1980) << 9 | st.wMonth << 5 | st.wDay);
}

/* Write base + loose entries to out_path. Returns the number of loose
 * entries used, or -1. */
static int merge(const char *base_path, const LooseList *loose, const char *out_path)
{
    FILE *in = fopen(base_path, "rb"), *out = NULL;
    uint8_t *cd = NULL, tail[65536 + 22];
    long size;
    size_t got, i;
    uint32_t cd_off, cd_size, count, pos;
    Entry *e = NULL, **by_off = NULL;
    int ne = 0, sorted = 1, used = 0, ok = 0;
    uint8_t *eocd = NULL;
    uint32_t new_cd_off;

    if (!in)
        return -1;
    fseek(in, 0, SEEK_END);
    size = ftell(in);
    got = (size_t)(size < (long)sizeof tail ? size : (long)sizeof tail);
    fseek(in, size - (long)got, SEEK_SET);
    if (fread(tail, 1, got, in) != got)
        goto done;
    for (i = got >= 22 ? got - 22 : 0; i + 1 > 0; i--) {
        if (rd32(tail + i) == 0x06054B50u) { eocd = tail + i; break; }
        if (!i) break;
    }
    if (!eocd)
        goto done;
    count = rd16(eocd + 10);
    cd_size = rd32(eocd + 12);
    cd_off = rd32(eocd + 16);
    cd = (uint8_t *)malloc(cd_size ? cd_size : 1);
    e = (Entry *)calloc((size_t)count + (size_t)loose->n, sizeof *e);
    by_off = (Entry **)calloc(count ? count : 1, sizeof *by_off);
    if (!cd || !e || !by_off || fseek(in, (long)cd_off, SEEK_SET)
            || fread(cd, 1, cd_size, in) != cd_size)
        goto done;

    for (pos = 0; ne < (int)count && pos + 46 <= cd_size; ne++) {
        const uint8_t *r = cd + pos;
        uint32_t nl = rd16(r + 28), xl = rd16(r + 30), cl = rd16(r + 32);
        if (rd32(r) != 0x02014B50u || pos + 46 + nl + xl + cl > cd_size)
            goto done;
        e[ne].cd = r;
        e[ne].cd_len = 46 + nl + xl + cl;
        e[ne].lho = rd32(r + 42);
        memcpy(e[ne].name, r + 46, nl < MAX_PATH - 1 ? nl : MAX_PATH - 1);
        if (ne && _stricmp(e[ne - 1].name, e[ne].name) > 0)
            sorted = 0;
        by_off[ne] = &e[ne];
        pos += e[ne].cd_len;
    }
    /* Each entry's bytes run up to the next one's local header. */
    qsort(by_off, (size_t)ne, sizeof *by_off, lho_cmp);
    for (i = 0; i < (size_t)ne; i++)
        by_off[i]->region_end = i + 1 < (size_t)ne ? by_off[i + 1]->lho : cd_off;

    for (i = 0; i < (size_t)loose->n; i++) {
        int j, hit = 0;
        for (j = 0; j < ne; j++)
            if (e[j].cd && !_stricmp(e[j].name, loose->v[i].name)) {
                e[j].loose = &loose->v[i];
                hit = 1;
                break;
            }
        if (!hit) {
            Entry *x = &e[ne + used];
            x->loose = &loose->v[i];
            snprintf(x->name, sizeof x->name, "%s", loose->v[i].name);
            used++;
        }
    }
    {
        int total = ne + used;
        if (sorted && used)
            qsort(e, (size_t)total, sizeof *e, name_cmp);
        used = 0;

        out = fopen(out_path, "wb");
        if (!out)
            goto done;
        for (i = 0; i < (size_t)total; i++) {
            long here = ftell(out);
            if (e[i].loose) {
                FILE *lf = fopen(e[i].loose->path, "rb");
                uint8_t h[30], *data;
                uint32_t len = (uint32_t)e[i].loose->size, crc, nl = (uint32_t)strlen(e[i].name);
                uint16_t t, d;
                if (!lf)
                    goto done;
                data = (uint8_t *)malloc(len ? len : 1);
                if (!data || fread(data, 1, len, lf) != len) {
                    fclose(lf);
                    free(data);
                    goto done;
                }
                fclose(lf);
                crc = crc32_update(0, data, len);
                if (e[i].cd) {
                    t = rd16(e[i].cd + 12);
                    d = rd16(e[i].cd + 14);
                } else {
                    dos_now(&t, &d);
                }
                memset(h, 0, sizeof h);
                wr32(h, 0x04034B50u); wr16(h + 4, 10); wr16(h + 10, t); wr16(h + 12, d);
                wr32(h + 14, crc); wr32(h + 18, len); wr32(h + 22, len); wr16(h + 26, nl);
                fwrite(h, 1, 30, out);
                fwrite(e[i].name, 1, nl, out);
                fwrite(data, 1, len, out);
                free(data);
                /* The central record is built below from these. */
                e[i].lho = (uint32_t)here;
                e[i].region_end = crc;           /* reused: the CRC */
                e[i].cd_len = len;               /* reused: the size */
                used++;
            } else {
                if (!copy_bytes(in, out, e[i].lho, e[i].region_end - e[i].lho))
                    goto done;
                e[i].lho = (uint32_t)here;
            }
        }
        new_cd_off = (uint32_t)ftell(out);
        for (i = 0; i < (size_t)total; i++) {
            uint8_t r[46];
            if (e[i].loose) {
                uint32_t nl = (uint32_t)strlen(e[i].name);
                uint16_t t, d;
                if (e[i].cd) {
                    t = rd16(e[i].cd + 12);
                    d = rd16(e[i].cd + 14);
                } else {
                    dos_now(&t, &d);
                }
                memset(r, 0, sizeof r);
                wr32(r, 0x02014B50u); wr16(r + 4, 20); wr16(r + 6, 10);
                wr16(r + 12, t); wr16(r + 14, d); wr32(r + 16, e[i].region_end);
                wr32(r + 20, e[i].cd_len); wr32(r + 24, e[i].cd_len); wr16(r + 28, nl);
                wr32(r + 42, e[i].lho);
                fwrite(r, 1, 46, out);
                fwrite(e[i].name, 1, nl, out);
            } else {
                memcpy(r, e[i].cd, 46);
                wr32(r + 42, e[i].lho);
                fwrite(r, 1, 46, out);
                fwrite(e[i].cd + 46, 1, e[i].cd_len - 46, out);
            }
        }
        {
            uint8_t end[22];
            uint32_t cd_len = (uint32_t)ftell(out) - new_cd_off;
            memset(end, 0, sizeof end);
            wr32(end, 0x06054B50u);
            wr16(end + 8, (uint32_t)total); wr16(end + 10, (uint32_t)total);
            wr32(end + 12, cd_len); wr32(end + 16, new_cd_off);
            fwrite(end, 1, 22, out);
        }
        ok = !ferror(out);
    }
done:
    if (out)
        fclose(out);
    fclose(in);
    free(cd);
    free(e);
    free(by_off);
    return ok ? used : -1;
}

/* Delete merged archives whose loose folder is gone: the cache is an
 * overlay, so a stale one would go on standing in for the game's. */
static void prune(const char *rel, char (*keep)[MAX_PATH], int nkeep)
{
    char pat[MAX_PATH];
    WIN32_FIND_DATAA fd;
    HANDLE h;

    snprintf(pat, sizeof pat, LOOSE_CACHE "%s%s\\*", *rel ? "\\" : "", rel);
    h = FindFirstFileA(pat, &fd);
    if (h == INVALID_HANDLE_VALUE)
        return;
    do {
        char sub[MAX_PATH];
        size_t n = strlen(fd.cFileName);
        int i, kept = 0;
        if (!strcmp(fd.cFileName, ".") || !strcmp(fd.cFileName, ".."))
            continue;
        snprintf(sub, sizeof sub, "%s%s%s", rel, *rel ? "\\" : "", fd.cFileName);
        if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) {
            prune(sub, keep, nkeep);
            continue;
        }
        if (!is_archive_name(fd.cFileName) || n < 4)
            continue;
        for (i = 0; i < nkeep; i++)
            if (!_stricmp(keep[i], sub)) { kept = 1; break; }
        if (!kept) {
            char path[MAX_PATH];
            snprintf(path, sizeof path, LOOSE_CACHE "\\%s", sub);
            DeleteFileA(path);
            strncat(path, ".sig", sizeof path - strlen(path) - 1);
            DeleteFileA(path);
            fprintf(stderr, "  [MODS] loose: %s has no loose entries any more\n", sub);
        }
    } while (FindNextFileA(h, &fd));
    FindClose(h);
}

/* ---- entry point --------------------------------------------------------- */

/* loose_roots: ';'-separated loose folders, highest priority first.
 * overlays: the ';'-separated overlay folders the game will read through
 * (the base archive is the first of those that has it, else game\).
 * Returns the number of archives served from the cache. */
int mod_loose_build(const char *loose_roots, const char *overlays)
{
    char roots[16][MAX_PATH], archives[MAX_ARCHIVES][MAX_PATH];
    int nroots = 0, narch = 0, i, served = 0;
    static char kept[MAX_ARCHIVES][MAX_PATH];
    const char *p = loose_roots;

    while (p && *p && nroots < 16) {
        const char *end = strchr(p, ';');
        int len = end ? (int)(end - p) : (int)strlen(p);
        snprintf(roots[nroots], MAX_PATH, "%.*s", len, p);
        if (is_dir(roots[nroots]))
            nroots++;
        p = end ? end + 1 : NULL;
    }
    for (i = 0; i < nroots; i++)
        find_archives(roots[i], "", archives, &narch);

    for (i = 0; i < narch; i++) {
        char base[MAX_PATH] = "", cache[MAX_PATH], sigpath[MAX_PATH], tmp[MAX_PATH];
        char *sig = NULL, *old = NULL;
        size_t siglen = 0, cap = 0;
        LooseList list = { 0 };
        uint64_t bsize, bmtime;
        int j, n;
        const char *o = overlays;

        while (o && *o && !*base) {
            const char *end = strchr(o, ';');
            int len = end ? (int)(end - o) : (int)strlen(o);
            snprintf(tmp, sizeof tmp, "%.*s\\%s", len, o, archives[i]);
            if (GetFileAttributesA(tmp) != INVALID_FILE_ATTRIBUTES)
                snprintf(base, sizeof base, "%s", tmp);
            o = end ? end + 1 : NULL;
        }
        if (!*base)
            snprintf(base, sizeof base, "game\\%s", archives[i]);
        if (!file_info(base, &bsize, &bmtime)) {
            fprintf(stderr, "  [MODS] loose: no archive %s to put entries in\n", archives[i]);
            continue;
        }
        for (j = 0; j < nroots; j++) {
            snprintf(tmp, sizeof tmp, "%s\\%s", roots[j], archives[i]);
            if (is_dir(tmp))
                loose_walk(tmp, "", &list);
        }
        if (!list.n) {
            free(list.v);
            continue;
        }

        /* Signature: the base and every loose file, with size and time. */
        for (j = -1; j < list.n; j++) {
            char line[MAX_PATH * 2];
            int len = j < 0
                ? snprintf(line, sizeof line, "%s|%llu|%llu\n", base,
                           (unsigned long long)bsize, (unsigned long long)bmtime)
                : snprintf(line, sizeof line, "%s|%s|%llu|%llu\n", list.v[j].name,
                           list.v[j].path, (unsigned long long)list.v[j].size,
                           (unsigned long long)list.v[j].mtime);
            if (siglen + (size_t)len + 1 > cap) {
                cap = (siglen + (size_t)len + 1) * 2;
                sig = (char *)realloc(sig, cap);
            }
            memcpy(sig + siglen, line, (size_t)len + 1);
            siglen += (size_t)len;
        }
        snprintf(cache, sizeof cache, LOOSE_CACHE "\\%s", archives[i]);
        snprintf(sigpath, sizeof sigpath, "%s.sig", cache);
        {
            FILE *f = fopen(sigpath, "rb");
            if (f) {
                old = (char *)calloc(siglen + 2, 1);
                if (old && fread(old, 1, siglen + 1, f) != siglen)
                    old[0] = 0;              /* different length: stale */
                fclose(f);
            }
        }
        if (old && sig && !strcmp(old, sig) && GetFileAttributesA(cache) != INVALID_FILE_ATTRIBUTES) {
            fprintf(stderr, "  [MODS] loose: %s, %d entr%s (cached)\n", archives[i], list.n,
                    list.n == 1 ? "y" : "ies");
            snprintf(kept[served++], MAX_PATH, "%s", archives[i]);
        } else {
            DWORD t0 = GetTickCount();
            snprintf(tmp, sizeof tmp, "%s.tmp", cache);
            make_dirs(cache);
            n = merge(base, &list, tmp);
            if (n >= 0 && MoveFileExA(tmp, cache, MOVEFILE_REPLACE_EXISTING)) {
                FILE *f = fopen(sigpath, "wb");
                if (f) {
                    fwrite(sig, 1, siglen, f);
                    fclose(f);
                }
                fprintf(stderr, "  [MODS] loose: %s, %d entr%s merged into %s (%lu ms)\n",
                        archives[i], n, n == 1 ? "y" : "ies", base,
                        (unsigned long)(GetTickCount() - t0));
                snprintf(kept[served++], MAX_PATH, "%s", archives[i]);
            } else {
                DeleteFileA(tmp);
                DeleteFileA(sigpath);
                DeleteFileA(cache);          /* an older merge would still be served */
                fprintf(stderr, "  [MODS] loose: could not merge %s into %s\n", archives[i], base);
            }
        }
        free(old);
        free(sig);
        free(list.v);
    }
    prune("", kept, served);
    return served;
}
