/*
 * host.h - the few host services the launcher needs, on Windows and POSIX.
 *
 * The toolkit's platform layer (xbox_winnt.h, win32_compat.h) covers what
 * the kernel HLE needs. main.c, coverage.c and mod_loose.c need a handful
 * more: the exe's path, the working directory, environment defaults, making
 * directories, the path separator. Small enough to spell out here rather
 * than grow the toolkit's Win32 emulation for one game's launcher.
 */

#ifndef AMPED2_HOST_H
#define AMPED2_HOST_H

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#if defined(_WIN32)
#include <windows.h>

#define HOST_SEP  '\\'
#define HOST_SEPS "\\"
#else
#include <limits.h>
#include <strings.h>
#include <sys/stat.h>
#include <unistd.h>
#if defined(__APPLE__)
#include <mach-o/dyld.h>
#endif

#define HOST_SEP  '/'
#define HOST_SEPS "/"
#endif

/* Paths built from pieces: P("mods", "loose") is "mods\loose" on Windows and
 * "mods/loose" elsewhere. String literals only. */
#define HOST_PATH2(a, b)       a HOST_SEPS b
#define HOST_PATH3(a, b, c)    a HOST_SEPS b HOST_SEPS c

/* "NAME=value" into the environment. POSIX putenv keeps the caller's
 * pointer, which is wrong for a buffer on the stack, so setenv, which
 * copies. */
static inline void host_putenv(const char *kv)
{
#if defined(_WIN32)
    _putenv(kv);
#else
    const char *eq = strchr(kv, '=');
    char name[256];
    if (!eq || (size_t)(eq - kv) >= sizeof name)
        return;
    memcpy(name, kv, (size_t)(eq - kv));
    name[eq - kv] = 0;
    setenv(name, eq + 1, 1);
#endif
}

/* The running executable's full path. */
static inline int host_exe_path(char *buf, size_t size)
{
#if defined(_WIN32)
    DWORD n = GetModuleFileNameA(NULL, buf, (DWORD)size);
    return n > 0 && n < size;
#elif defined(__APPLE__)
    uint32_t n = (uint32_t)size;
    return _NSGetExecutablePath(buf, &n) == 0;
#else
    ssize_t n = readlink("/proc/self/exe", buf, size - 1);
    if (n <= 0)
        return 0;
    buf[n] = 0;
    return 1;
#endif
}

static inline int host_exists(const char *path)
{
#if defined(_WIN32)
    return GetFileAttributesA(path) != INVALID_FILE_ATTRIBUTES;
#else
    return access(path, F_OK) == 0;
#endif
}

static inline int host_getcwd(char *buf, size_t size)
{
#if defined(_WIN32)
    DWORD n = GetCurrentDirectoryA((DWORD)size, buf);
    return n > 0 && n < size;
#else
    return getcwd(buf, size) != NULL;
#endif
}

static inline int host_chdir(const char *dir)
{
#if defined(_WIN32)
    return SetCurrentDirectoryA(dir) != 0;
#else
    return chdir(dir) == 0;
#endif
}

/* An absolute version of `in`, which need not exist yet. */
static inline int host_full_path(const char *in, char *out, size_t size)
{
#if defined(_WIN32)
    DWORD n = GetFullPathNameA(in, (DWORD)size, out, NULL);
    return n > 0 && n < size;
#else
    char cwd[PATH_MAX];
    if (in[0] == '/')
        return snprintf(out, size, "%s", in) < (int)size;
    if (!getcwd(cwd, sizeof cwd))
        return 0;
    return snprintf(out, size, "%s/%s", cwd, in) < (int)size;
#endif
}

/* One directory; an existing one is fine. */
static inline void host_mkdir(const char *dir)
{
#if defined(_WIN32)
    CreateDirectoryA(dir, NULL);
#else
    mkdir(dir, 0755);
#endif
}

#endif /* AMPED2_HOST_H */
