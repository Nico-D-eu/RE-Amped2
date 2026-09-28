# Amped 2 — Static Recompilation

A static recompilation of **Amped 2** (Microsoft Game Studios / Indie Built,
2003) for the original Xbox, built on the
[xboxrecomp](https://github.com/sp00nznet/xboxrecomp) toolkit. The XBE's x86
code is lifted to C and compiled into a native Windows executable that links the
toolkit's kernel, D3D8→D3D11, audio and input runtime.

You must supply your own legally owned copy of the game. No game code or assets
are in this repository; `game/` and `src/recomp/gen/` are git-ignored and are
regenerated locally.

## Layout

```
recompilation/
├── xboxrecomp/            toolkit (libraries + Python pipeline), sibling of this dir
├── Ghidra/                Ghidra 12.0.3 (+ ghidra-xbe in the user profile), for naming
├── xdvdfs.exe             disc extractor
└── amped2/                ← this project
    ├── CMakeLists.txt     builds amped2_recomp.exe, add_subdirectory(../xboxrecomp)
    ├── tools/regen.ps1    runs the whole pipeline and regenerates src/recomp/gen
    ├── src/
    │   ├── main.c         host entry: loads the XBE, boots kernel/memory, calls the guest
    │   ├── recomp_manual.c hand-written overrides + ICALL diagnostics
    │   └── recomp/gen/    generated C (git-ignored)
    └── game/              extracted disc (git-ignored)
```

## Title facts

From `py -3 -m tools.xbe_parser` (full output in `game/default_analysis.json`):

| | |
|---|---|
| Release | Europe, Australia (En, Fr, De) |
| Title ID | `0x4D530041` — retail, DVD_X2 |
| Built | 2003-10-03, XDK **1.0.5558** — internal codename *Yeti* (`c:\depot\yeti\...\YetiGame\Default.exe`) |
| Image | base `0x00010000`, size `0x003E9520` |
| Entry point | **`0x00254899`** |
| Kernel thunks | `0x00336DE0`, 158 kernel imports |
| `.text` | `0x00011000`, 2.49 MB |
| XDK code sections | DSOUND, XONLINE, XNET, XMV, WMADEC, XACTENG, XGRPH, D3D, XPP, DOLBY, XON_RD |
| Libraries | XAPILIB, LIBCMT, DSOUND, XONLINES, XVOICE, XMV, D3D8LTCG, XGRAPHCL, XACTENLT |

Other executables on the disc (`Boom.xbe`, `cdx.xbe`, `update.xbe`,
`dashupdate.xbe`) are not part of the port; only `default.xbe` is recompiled.

Things worth knowing going in:

- **Custom engine, not RenderWare.** `func_id` finds no RW modules, so the
  RenderWare-specific tooling does not apply.
- **D3D8LTCG.** The D3D library is link-time-code-generated, so its functions do
  not have the standard XDK shapes. See
  `xboxrecomp/docs/technical/d3d8ltcg-device-context.md`.
- **Xbox Live and networking** (XONLINE, XNET, XVOICE) are linked in. Expect to
  stub or force-return the online paths during bring-up.
- **XACT audio engine and WMA decoder** (XACTENG, WMADEC) are present alongside
  DSOUND. Audio is likely a later-stage problem.
- **XMV video** is used for FMVs (`Movies/`); see `tools.xmv`.

## Pipeline status

| Step | Tool | Result |
|---|---|---|
| 1 Extract | `xdvdfs unpack` | 719 files, 4.25 GB → `game/` |
| 2 Parse | `tools.xbe_parser` | `game/default_analysis.json` |
| 3 Disassemble | `tools.disasm` (all code sections) + `config/seed_functions.json` | 14,715 functions |
| 4 Identify | `tools.func_id` | 17,843 classified; 11 CRT, 0 RW, 7,407 unknown |
| 4.5 ABI | `tools.abi_analysis` | 14,714 entries, 2,590 thiscall |
| 4.6 Names | Ghidra headless + `merge_names.py` | 190 FidDb CRT/XDK names, all on function starts |
| 5 Recompile | `tools.recomp --split 250 --exclude-manual` | 14,714 generated + 1 hand-written, 0 failed; 2.06M lines in 59 chunks (~78 MB); 109 unresolved call targets stubbed |
| — Health | `tools/doctor.py` | 348 unimplemented instructions (`outsb`, `das`, `popal`, `bound`, `arpl`…), mostly data decoded as code; each is a `RECOMP_UNIMPL` no-op that logs if reached |
| 6 Project | template customised | entry point + paths set in `main.c` |
| 7 Build | CMake + MSVC 19.51 (VS 2026) | builds `amped2_recomp.exe` + `.pdb`, 0 errors, ~20 min full rebuild |

## Regenerating

From PowerShell in this directory:

```powershell
.\tools\regen.ps1                 # steps 2-5, reusing the cached Ghidra export
.\tools\regen.ps1 -Ghidra         # also re-run the headless Ghidra analysis
.\tools\regen.ps1 -SkipAnalysis   # only re-run the recompiler
.\tools\regen.ps1 -SkipAnalysis -RecompArgs '--force-return','0x00123456=0'
```

The disassembler rewrites `functions.json` from scratch each time, which drops
the Ghidra names; the script re-applies them after step 3 for that reason.

## Building

Requires Visual Studio with the **Desktop development with C++** workload (MSVC
x64 + Windows SDK) and CMake 3.20+.

```powershell
cmake -S . -B build -G "Visual Studio 18 2026" -A x64
cmake --build build --config Release --parallel
.\build\Release\amped2_recomp.exe 2> stderr.txt   # run from this directory
```

Release builds carry a `.pdb` (`/Zi /DEBUG`), which the crash handler needs to
name the faulting guest function. The generated chunks compile 4 at a time
(`/MP4`); raise it with `-DAMPED2_MP_JOBS=8` if you have memory to spare. Peak
use at 4 stayed under ~1 GB of the 16 GB machine this was built on.

The `.exe` finds `game\default.xbe` itself. It tries the working directory
first, then the `.exe`'s folder and its parents, so a double-click in
`build\Release` finds `amped2\game`. It is a GUI-subsystem app, so a
double-click shows no log. Run it from a terminal with `2> stderr.txt` to
capture the boot trace. It will crash on first run. That is expected; see
`xboxrecomp/docs/GETTING_STARTED.md` step 8 and
`xboxrecomp/docs/pipeline/06-debugging.md`.

## Bring-up notes

Record addresses, identified functions and overrides here as they are found.

- `0x00254899` — XBE entry point (`xbe_entry_point`)
- `0x0025A120` / `0x0025A15B` — `__SEH_prolog` / `__SEH_epilog` (auto-detected by `tools.recomp`)
- `0x002838DC` / `0x0025B8FC` — CRT `setjmp` / `longjmp`
- Guest stack at `0x00780000` (8 MB) sits well above the image end `0x003F9520`; no layout conflict.

### First boot (2026-09-28)

Boot reached guest code without crashing: memory layout, all 158 kernel thunks
bridged, and a first system thread started. The log shows the title reading
`\Device\Harddisk0\partition0` and opening
`UDATA\4d530041\TitleImage.xbx`. Within 45 s it settled into
`KeDelayExecutionThread` (ordinal 99) at ~120 calls/s from one stack position,
meaning a wait loop. Two failed indirect calls came first, and both were fixed:

- **`0x00259939` is a thread routine** handed to `PsCreateSystemThreadEx`
  through the XAPI trampoline at `0x00252D12`, but the disassembler had folded
  it into `sub_0025992F`. That worker thread could never start, which is the
  likely reason the main thread waits forever. Seeded via
  `tools.seed_from_log` into `config/seed_functions.json`, along with the first
  thread's start context `0x00254825`.
- **`0x00259000` is CRT `memmove`**, and its jump-table arms (from `0x002592A4`)
  sit past its recorded end, so the lifted copy dropped its unaligned tails.
  Replaced natively in `recomp_manual.c` (`sub_00259000`) and excluded from
  codegen. The seed for `0x002592A4` was correctly rejected, since it is a
  table arm and not a function.

**Second boot, with both fixes:** no crash and no failed indirect calls until
D3D init. The worker thread starts, and the title reads its own data off the
disc: `image.res`, `guipackages/packagehierarchy.dat` and all 17 GUI packages
(`legal`, `base`, `shell`, `multiplayer`, HUDs, loading tips, each as
`.ruirr` + `.rui`), then `gameinfo/gameinfo.res` and `levels/levels.res`. It
stops in D3D8LTCG device creation: `KeConnectInterrupt` vector 3 → `0x003220C0`,
then `out dx, al` at `0x00321731` and `wbinvd` at `0x0031FFEF` (both no-ops
here), then a call through a table of NV2A init routines
(`0x0031C660`…`0x0031CE70`) to **`0x0031CB60`, which is not a detected
function**. Next step: seed it the same way and look at what the D3D init
expects from the GPU:

```powershell
cd ..\xboxrecomp
py -3 -m tools.seed_from_log ..\amped2\stderr.txt ..\amped2\game\default.xbe --functions tools\disasm\output\functions.json --seeds ..\amped2\config\seed_functions.json
cd ..\amped2
.\tools\regen.ps1
cmake --build build --config Release --parallel
```

**Third boot, with `0x0031CB60` seeded:** that call resolves. It is one of 30
entries in D3D's NV2A handler table at `0x003297F8`–`0x0032986C`, and the only
one that was missing. D3D init completes, and the GPU pushbuffer is submitted
and consumed three times (`DMA_PUT` = `DMA_GET` = `0x00709000` → `0x00709280`
→ `0x00709AD8`), then nothing more is submitted. There is no crash, no failed
call and no further log output: the title spins. `RECOMP_WATCHDOG_SECS=8`
names the loop:

- the chain is `sub_0002B740` → `sub_00027490` → `sub_0028592A` →
  `sub_00139640` → **`sub_001455C0`**, all game code in `.text`;
- `sub_001455C0` calls `sub_00029AB0` / `sub_00029A80` over and over. Those go
  to kernel thunk slots 1 and 2, which are `RtlLeaveCriticalSection` and
  `RtlEnterCriticalSection`;
- so the loop polls a shared value under a lock and waits for something that
  never happens. Candidates, in order: a GPU interrupt or vblank that the
  vector-3 ISR at `0x003220C0` would deliver (the runtime raises no NV2A
  interrupts by default), a second game thread that never starts, or a
  device probe that failed quietly (see "Runs, Never Draws a Frame" in
  `xboxrecomp/docs/pipeline/06-debugging.md`).

Next diagnostics, each a single run:

```powershell
$env:RECOMP_WATCHDOG_SECS=8; $env:RECOMP_PB_EXEC=1;      .\build\Release\amped2_recomp.exe 2> stderr.txt
$env:RECOMP_WATCHDOG_SECS=8; $env:RECOMP_AC97_READY=1;   .\build\Release\amped2_recomp.exe 2> stderr.txt
```

Note: the watchdog calls `_exit(3)` after its dump, so a watchdog run ending
by itself is expected.

Build note: `recomp_0020.c` took ~31 min to compile in this build, against
~20 min for the whole game target before. If that repeats, find the
function in that chunk that is stalling the optimiser.

**Diagnostic runs** (`tools/diag.ps1`, logs in `diag/`):

| Run | Switches | Result |
|---|---|---|
| `vblank` | `RECOMP_VBLANK` | vblank → GPU ISR `0x003220C0` claims it → `KeInsertQueueDpc` at ~60 Hz, and the DPCs run. The main thread does not move. |
| `vblank_pbexec` | + `RECOMP_PB_EXEC` | executor handles 419 methods and sets up a 640×480 target at `0x0098C000`. 0 clears, 0 draws. No change. |
| `vblank_pbexec_ac97` | + `RECOMP_AC97_READY` | APU and XAudio2 come up. No change. |

None of the switches was the gate. `tools/sample_threads.py` (host RIP → PDB →
generated line → `loc_` label) put the main thread at 100% on guest
**`0x0031E901`** in D3D's `sub_0031E7E0`. That is a self-throttle that spins
until `submitted - completed <= 2`, where *submitted* is `[device+0x2C]` (9)
and *completed* is the semaphore that `[device+0x30]` points at
(`0x80708000`, stuck at 3). Only the GPU advances it. The device pointer is at
`0x0032CEF8` (device `0x0032AA60`), confirmed live with `RECOMP_PEEK`.

**Fix:** `main.c` registers `xbox_Nv2aMirrorFence(0x0032CEF8, 0x2C, 0x30)`,
the runtime's mechanism for exactly this (Wreckless has the same fence).

**After the fence fix**, with no switches: boot continues to 61 distinct disc
files. Additions are the XACT audio banks (`audio/XACTdata/*.xsb`/`.xwb`,
English streams), `characters/boarder/MedHiResCharacter.gfx` and
`shaders/shaders.res`. Open problems:

1. **Access violation** in `sub_000DC0F0+0x42A`, reading `0xAFAFAA17` through
   `ebx = 0xAFAFAB2B`, right after `shaders.res` is read in 16 KB chunks. The
   runtime has no `0xAF` fill, so the pointer comes from the title's own
   data or allocator. Caller chain: `0x000DE958`, `0x0002F36D`, `0x000DBC09`, ...
2. **Contiguous-memory probe:** the title asks `MmAllocateContiguousMemory`
   for 60 MB and retries 8 KB smaller each time (1,567 failures) until it gets
   what is left of the 64 MB arena, about 47 MB with 16.8 MB already used. It
   keeps that as a pool, so later 4–8 KB contiguous requests fail. On
   hardware the probe would see the whole console's free memory. Here the XBE
   image and the 48 MB heap live outside the arena, so the numbers differ. This
   is a candidate cause of (1).
3. **Two undetected XPP (controller library) functions**, reached indirectly:
   `0x0032E3A4` (inside `sub_0032E208`) and `0x0032EDAB`. They pass
   `seed_from_log`'s checks and are ready to seed from
   `diag/fence_default.txt`.

**After seeding the XPP functions and fixing the contiguous allocator:**

- *Toolkit fix* (local change in `xboxrecomp/`, worth upstreaming):
  `MmFreeContiguousMemory` handed contiguous blocks to `xbox_HeapFree`, which
  does not own them, so every free was silently lost. The contiguous
  allocator (`xbox_ContiguousAlloc` in `src/kernel/xbox_memory_layout.c`) now
  tracks blocks: frees are honoured, neighbours coalesce, the top block
  rewinds, and allocation is first-fit before bump. A standalone test of the
  exact code passes (probe-then-free, split, coalesce, rewind, alignment
  gaps, double free, zeroing). The probe now gets its ~50 MB back, and the
  later 4–8 KB failures and the `0xAFAF…` crash in `sub_000DC0F0` are gone.
- **`d:\Boom.xbe` hand-off.** With no crash left, the title tore down on
  purpose (`sub_0002B740` → cleanup `sub_00026A30` →
  `sub_00252E25("d:\Boom.xbe", 0)` → `HalReturnToFirmware`). `Boom.xbe` is
  the title's own JPEG helper (libjpeg strings, jumps back to
  `D:\default.xbe`), and 39 code paths launch it. The first trigger was
  **audio**: with the AC'97 codec not ready, audio init fails and the title
  gives up. `RECOMP_AC97_READY=1` moves past it.
- **DSP mailbox.** DirectSound (`sub_00292F33`) then writes command `3` to
  `0x8105C810` and spins at `0x0029309A` until the DSP clears it. The GP DSP
  is a stub. `RECOMP_DSP_ACK=0x8105C810` clears it (the same pattern the
  runtime documents for DDS9).
- Both are now **defaults in `main.c`**; an environment variable that is
  already set wins. With no switches the title reads **111 distinct disc
  files**, through the XACT banks, `Audio/DSP/yetidsp.bin` and the sound
  effects (`Audio/SoundFX/*.wav`), starts a second worker, then launches
  `Boom.xbe` again. Just before, a worker waits on an XACT-engine lock at
  `0x003188E0`, gets it, and exits. **Next:** find which of the 39 launch
  sites fires now and what it tested. Candidates are another audio/XACT
  result, or a missing save or photo prerequisite that `Boom.xbe` exists to
  create.

`RECOMP_VBLANK` and `RECOMP_PB_EXEC` made no difference to how far boot gets.

### Overnight session (2026-09-28/29)

**Why the second `Boom.xbe` launch:** it is not out-of-memory. `sub_0002B6C0`
is the title's fatal handler. It shuts down and launches `Boom.xbe`, and it
is registered as the allocator's OOM callback (`0x0038CE1C`, `0x003A7B98`).
It is also called directly from five places. A deeper exit dump (the toolkit
dump is now 1,024 dwords, not 200) put the caller at `sub_0014ED70`, a
script-running loop. It calls `sub_000F37E0`, which is **`lua_pcall`**
(`sub_000F24F0` = `luaD_rawrunprotected` with setjmp, `sub_000F24C0` =
`luaD_throw` with longjmp), and treats any status other than 0 (or a
retryable 2) as fatal.

**The Lua error:** hand copies of both functions in `src/lua_probe.c`,
listed in `config/manual_functions.json`, log the error object at the throw:

```
[LUA] throw #1: errcode 1 ... message: ../Image/SessionDetails.lua:21: table index is NaN
```

**Root cause, a lifter bug** (fixed in `xboxrecomp/tools/recomp/lifter.py`):
Lua's `luaH_set` checks a numeric key with MSVC's P6 idiom
`fucomip; lahf; test ah, 44h; jnp`. `lahf` lifted to a comment, so AH held
stale eax, parity came out wrong, and **every number used as a table key was
reported as NaN**. `lahf` is now lifted from the tracked flag setter via the
same conditions the jcc use. The FPU compare conditions are also now
unordered-correct: `g_fp_cmp == 2` sets ZF, PF and CF as on hardware, where
before it read as not-equal, not-below and `jp` never taken. There is a new
regression test, `tools/recomp/test_lahf_fcomi.py`, which compiles the lifted
expressions and checks all four compare outcomes. Suite: 454 passed.

**After the `lahf` fix:** no Lua error, and `AvSetDisplayMode` (640×480,
`fb=0x0098C000`) is called. A worker thread then crashed in the allocator
`sub_000DC0F0`: TLS slot 0 pointed at a 64-byte scratch area while the
title reads TLS offset `0xA8`. Fixed in the toolkit (the slot now points
at the thread's own copy of the 272-byte template).

**First frame:** with `RECOMP_VBLANK=1 RECOMP_PB_EXEC=1 RECOMP_FB_WINDOW=1`
the title draws its **title splash** (two textured triangles) into the
framebuffer window. `RECOMP_FB_DUMP=diag\x.bmp` saves it. The main thread
then sits in `app->Run()`: `[0x003ACD2C]` vtable slot 1, called from
`sub_0002B740`. The image never changes and no flip is logged, so the next
problem is why the loop stalls after one frame. An XNet worker
(`sub_002BEE4D`) spins polling link status at raised IRQL; there is no NIC.

**After the splash**, three more blockers, all fixed:

1. **Deadlock on the global lock `0x0038C890`.** Network startup
   `sub_001BE680` holds it while looping on `XNetGetTitleXnAddr` until an
   address arrives. With no NIC that never happens. Fixed by forcing
   `sub_002BEE4D` to return `XNET_GET_XNADDR_NONE` (1),
   `config/force_return.txt`.
2. **Ke\* waits on inline-initialised events.** A toolkit fix in
   `kernel_bridge.c` (`ke_dispatcher_handle`, event-state mirroring).
   Before it, the movie worker and D3D's vblank wait spun through tens of
   millions of failed or instantly-satisfied waits.
3. **The intro movie never ends,** because XMV is paced by an audio clock
   the APU doesn't advance. Movies are skipped (`sub_00150E80` hand copy)
   unless `AMPED2_PLAY_MOVIES=1`.

The title then reaches its **front end**: 150 disc files, 6 threads,
continuous rendering. The UI is drawn **wrong**: squashed into the top-left
~320×256, textures sampled at a constant v, most triangles off-surface. That
is the next thing to fix, in the pushbuffer executor's vertex/viewport path.

**Title screen (2026-09-29).** Four toolkit changes made it render: a
vertex-program interpreter for the pushbuffer executor
(`src/kernel/nv2a_vp.c`), the viewport scale/offset constants
(`XFCTX_VPSCL`/`VPOFF` = c[58]/c[59]), general blend factors, and texture
× vertex colour. The front end now shows the copyright text, "PRESS START
TO BEGIN" and the ESRB notice correctly (`diag/title_screen_2026-09-29.png`).

**Input (works).** `main.c` calls `xbox_OhciInit()` and routes OHCI
register faults, which nothing did before. With the toolkit's bus-address
fix in `src/usb/ohci.c`, the pad enumerates: GET_DESCRIPTOR, SET_ADDRESS,
GET_DESCRIPTOR(config), SET_CONFIGURATION. Seeding the XPP class-driver
step `0x003306DF` and the report routine `0x0032FC8B` completes the XID
handshake (`C1 06`, `A1 01`) and the endpoint-1 polling. A PC controller,
or the keyboard with the game window focused (Enter = START, arrows = d-pad,
Z X A S = A B X Y, Backspace = BACK), is player 1. `RECOMP_PAD_PRESS=0x10`
pulses START for unattended runs, and `RECOMP_USB_TRACE=1` shows the USB
traffic.

**Menus (2026-09-29).** Pressing START walks the front end to the career
event select (`diag/menu_event_select_2026-09-29.png`: Millicent 1,
Breckenridge, Bear Mtn., Mt. Hood, Laax, Challenges To Do). The title
starts loading `LEVELS\ML1\ML1.gfx`. Rendering artefacts remain (doubled
text, grey streaks).

**Do not seed `0x002C8DAD`** (XNET). Making it callable enables the network
card's deferred-interrupt path, which crashes with no NIC. The seeder will
suggest it again from any log.

Default runtime switches now set in `main.c`: `RECOMP_AC97_READY`,
`RECOMP_DSP_ACK`, `RECOMP_FORCE_RETURN`, `RECOMP_VBLANK`, `RECOMP_PB_EXEC`,
`RECOMP_FB_WINDOW`, `RECOMP_USB`, `RECOMP_KEYBOARD`. A variable that is already set in the environment wins.

**Build time:** `sub_00148D80`, a one-shot render-state table setup, took
2,121 s of `recomp_0020.c`'s 2,133 s code generation (MSVC `/d2cgsummary`).
It is now compiled with `#pragma optimize("", off)`: `config/no_optimize.txt`,
applied by `regen.ps1`. **Full rebuild: ~7.5 min, was ~27.**

**Also noted:**
- The toolkit's "wrap" (`sub_X_gen`) rewrites direct callers *and* the
  dispatch entry to the generated body, so a wrapper only sees calls from
  hand code and from `recomp_lookup_manual`. That is surprising, and worth
  raising upstream. `lua_probe.c` uses full hand copies instead.
- `recomp_funcs.h` declares guest functions under Ghidra names like
  `flushall`, which collide with `<stdio.h>`. A file using the
  generated-code dialect must not include CRT headers.
- After the protected call returns, the error object at `L->top - 1` reads as
  nil (`0xFDFDFDFD` value), although the throw carried a string. Not
  blocking; possibly how this Lua build's `luaD_pcall` places the message.
- `Audio/SoundFX/{ConcreteCrash00,GlassWall Collide02,QuickRip2}.wav` are
  genuinely missing from the disc.

Build note: `recomp_0020.c` took ~30 min again (reproducible), 27 min of a
~27 min build at `/MP6`. To find the function, compile that file alone with
MSVC's `/d2cgsummary`.

**Why no window opens yet:** the framebuffer window needs `RECOMP_FB_WINDOW=1`,
and it only opens once the title calls `AvSetDisplayMode` or, with
`RECOMP_PB_EXEC=1`, clears a surface. Amped 2 has not reached either point yet.

Other things seen in those runs, not yet looked at:

- `NtFsControlFile(0x90020)` is a runtime stub and returns `0xC00000BB`
  (not supported) while the title checks a partition. The title carried on.
- One file open failed with `ERROR_PATH_NOT_FOUND` (`0xC000003A`).

### Known toolkit issue (for upstream)

The lifter emits immediate shift counts unmasked: `shl ecx, 0x32` becomes
`ecx << 0x32` (C4293, undefined behaviour), where x86 masks the count to 5 bits
(`0x12`). The 8 hits here are all in data decoded as code in the last chunk
(`recomp_0057.c`), so they are harmless for Amped 2. The same lift on real code
would be wrong.
