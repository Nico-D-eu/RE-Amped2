"""
Where is each thread of a running amped2_recomp.exe spending its time?

A poor man's profiler for hangs: start the exe (or attach to a running one),
wait, then repeatedly suspend every thread, read its host RIP, and map it
through the .pdb to the generated function, the C source line, and the guest
address label (loc_XXXXXXXX) that line sits under. A thread spinning in a
tight guest loop shows up as the same one or two guest addresses on every
sample.

    py -3 tools/sample_threads.py                       # start, wait 15 s, sample
    py -3 tools/sample_threads.py --env RECOMP_VBLANK=1 --wait 20
    py -3 tools/sample_threads.py --pid 1234            # attach instead

Needs the .pdb beside the .exe (CMakeLists.txt builds one in Release).
"""

import argparse
import collections
import ctypes
import ctypes.wintypes as wt
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = os.path.join(ROOT, "build", "Release", "amped2_recomp.exe")

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
dbg = ctypes.WinDLL("dbghelp", use_last_error=True)

TH32CS_SNAPTHREAD = 0x4
THREAD_ALL = 0x0002 | 0x0008 | 0x0010 | 0x0040  # suspend/resume, get/set ctx, query
PROCESS_ALL = 0x0400 | 0x0010                    # query info, vm read
CONTEXT_CONTROL = 0x00100001
CTX_SIZE = 1232
CTX_FLAGS_OFF, CTX_RSP_OFF, CTX_RIP_OFF = 0x30, 0x98, 0xF8


class THREADENTRY32(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD),
                ("th32ThreadID", wt.DWORD), ("th32OwnerProcessID", wt.DWORD),
                ("tpBasePri", wt.LONG), ("tpDeltaPri", wt.LONG),
                ("dwFlags", wt.DWORD)]


class SYMBOL_INFO(ctypes.Structure):
    _fields_ = [("SizeOfStruct", wt.ULONG), ("TypeIndex", wt.ULONG),
                ("Reserved", ctypes.c_uint64 * 2), ("Index", wt.ULONG),
                ("Size", wt.ULONG), ("ModBase", ctypes.c_uint64),
                ("Flags", wt.ULONG), ("Value", ctypes.c_uint64),
                ("Address", ctypes.c_uint64), ("Register", wt.ULONG),
                ("Scope", wt.ULONG), ("Tag", wt.ULONG), ("NameLen", wt.ULONG),
                ("MaxNameLen", wt.ULONG), ("Name", ctypes.c_char * 256)]


class IMAGEHLP_LINE64(ctypes.Structure):
    _fields_ = [("SizeOfStruct", wt.DWORD), ("Key", ctypes.c_void_p),
                ("LineNumber", wt.DWORD), ("FileName", ctypes.c_char_p),
                ("Address", ctypes.c_uint64)]


k32.OpenThread.restype = wt.HANDLE
k32.OpenProcess.restype = wt.HANDLE
k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
k32.GetThreadContext.argtypes = [wt.HANDLE, ctypes.c_void_p]
dbg.SymFromAddr.argtypes = [wt.HANDLE, ctypes.c_uint64,
                            ctypes.POINTER(ctypes.c_uint64),
                            ctypes.POINTER(SYMBOL_INFO)]
dbg.SymGetLineFromAddr64.argtypes = [wt.HANDLE, ctypes.c_uint64,
                                     ctypes.POINTER(wt.DWORD),
                                     ctypes.POINTER(IMAGEHLP_LINE64)]


def threads_of(pid):
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    te = THREADENTRY32()
    te.dwSize = ctypes.sizeof(te)
    tids = []
    ok = k32.Thread32First(snap, ctypes.byref(te))
    while ok:
        if te.th32OwnerProcessID == pid:
            tids.append(te.th32ThreadID)
        ok = k32.Thread32Next(snap, ctypes.byref(te))
    k32.CloseHandle(snap)
    return tids


def sample_rip(tid):
    """(rip, rsp) of a thread, read while it is suspended."""
    h = k32.OpenThread(THREAD_ALL, False, tid)
    if not h:
        return None
    raw = ctypes.create_string_buffer(CTX_SIZE + 16)
    base = (ctypes.addressof(raw) + 15) & ~15          # CONTEXT is 16-aligned
    ctypes.c_uint32.from_address(base + CTX_FLAGS_OFF).value = CONTEXT_CONTROL
    try:
        if k32.SuspendThread(h) == 0xFFFFFFFF:
            return None
        try:
            if not k32.GetThreadContext(h, ctypes.c_void_p(base)):
                return None
            return (ctypes.c_uint64.from_address(base + CTX_RIP_OFF).value,
                    ctypes.c_uint64.from_address(base + CTX_RSP_OFF).value)
        finally:
            k32.ResumeThread(h)
    finally:
        k32.CloseHandle(h)


_src_cache = {}
LOC_RE = re.compile(r"^loc_([0-9A-Fa-f]{8}):")


def guest_label(path, line):
    """Nearest loc_XXXXXXXX label at or above a generated source line."""
    if path not in _src_cache:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                _src_cache[path] = f.read().splitlines()
        except OSError:
            _src_cache[path] = []
    lines = _src_cache[path]
    for i in range(min(line, len(lines)) - 1, -1, -1):
        m = LOC_RE.match(lines[i])
        if m:
            return "0x" + m.group(1).upper()
        if lines[i].startswith("void ") and lines[i].endswith("(void)"):
            break
    return "?"


def symbolize(hproc, addr):
    sym = SYMBOL_INFO()
    sym.SizeOfStruct = 88   # sizeof(SYMBOL_INFO) with a 1-char Name, per dbghelp
    sym.MaxNameLen = 255
    disp = ctypes.c_uint64(0)
    name = "?"
    if dbg.SymFromAddr(hproc, addr, ctypes.byref(disp), ctypes.byref(sym)):
        name = "%s+0x%X" % (sym.Name.decode(errors="replace"), disp.value)
    ln = IMAGEHLP_LINE64()
    ln.SizeOfStruct = ctypes.sizeof(ln)
    d32 = wt.DWORD(0)
    where, label = "", ""
    if dbg.SymGetLineFromAddr64(hproc, addr, ctypes.byref(d32), ctypes.byref(ln)):
        path = ln.FileName.decode(errors="replace")
        where = "%s:%d" % (os.path.basename(path), ln.LineNumber)
        if "recomp" + os.sep + "gen" in path or "recomp/gen" in path:
            label = guest_label(path, ln.LineNumber)
    return name, where, label


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pid", type=int, help="attach to a running process")
    ap.add_argument("--env", action="append", default=[], metavar="NAME=VALUE")
    ap.add_argument("--wait", type=float, default=15.0, help="seconds before sampling")
    ap.add_argument("--samples", type=int, default=40)
    ap.add_argument("--interval", type=float, default=0.05)
    ap.add_argument("--log", default=os.path.join(ROOT, "diag", "sample_threads.txt"),
                    help="stderr of a started exe goes here")
    args = ap.parse_args()

    proc = None
    if args.pid:
        pid = args.pid
    else:
        env = dict(os.environ)
        for kv in args.env:
            k, _, v = kv.partition("=")
            env[k] = v
        os.makedirs(os.path.dirname(args.log), exist_ok=True)
        log = open(args.log, "wb")
        proc = subprocess.Popen([EXE], cwd=ROOT, env=env,
                                stdout=subprocess.DEVNULL, stderr=log)
        pid = proc.pid
        print("started pid %d, waiting %.0fs ..." % (pid, args.wait))
        time.sleep(args.wait)
        if proc.poll() is not None:
            sys.exit("exe exited (code %s) before sampling; see %s"
                     % (proc.returncode, args.log))

    hproc = k32.OpenProcess(PROCESS_ALL, False, pid)
    dbg.SymSetOptions(0x2 | 0x10)  # UNDNAME | LOAD_LINES
    if not dbg.SymInitialize(hproc, os.path.dirname(EXE).encode(), True):
        sys.exit("SymInitialize failed: %d" % ctypes.get_last_error())

    hits = collections.defaultdict(collections.Counter)
    for _ in range(args.samples):
        for tid in threads_of(pid):
            r = sample_rip(tid)
            if r:
                hits[tid][r[0]] += 1
        time.sleep(args.interval)

    for tid, ctr in sorted(hits.items(), key=lambda kv: -max(kv[1].values())):
        total = sum(ctr.values())
        byfunc = collections.Counter()
        detail = {}
        for rip, n in ctr.items():
            name, where, label = symbolize(hproc, rip)
            key = (name.split("+")[0], label, where)
            byfunc[key] += n
        top = byfunc.most_common(4)
        print("\nthread %d  (%d samples)" % (tid, total))
        for (fn, label, where), n in top:
            print("  %3d%%  %-32s guest %-11s %s" % (100 * n // total, fn, label or "-", where))

    dbg.SymCleanup(hproc)
    if proc:
        proc.kill()


if __name__ == "__main__":
    main()
