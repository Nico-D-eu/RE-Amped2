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

**Menu rendering status.** Near-plane clipping in the toolkit removed the
streaks from background layers rotating past the camera, and boarder
creation renders cleanly (`diag/menu_create_boarder_2026-09-29.png`). The
menus still stack over earlier screens: the title redraws a 3D background
each frame instead of clearing colour, and the executor has no depth
buffer or fixed-function T&L to draw it. That's the next rendering work
(see PLAN.md, Phase 2).

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

### 3D rendering and the menu camera (2026-09-29)

**Executor:** the toolkit's software rasteriser (`nv2a_pb_exec.c`) now has
a host-side depth buffer per zeta offset, Gouraud colour, colour and UVs
that are perspective-correct through 1/w, and alpha test. Vertex-program
vertices carry `oPos.z/w` and `oD0` through the near clip. In the menus
none of this changes the picture, because every menu batch runs vertex
program mode `0x6` with **depth test off** and SRC_ALPHA/INV_SRC_ALPHA
blending (see `RECOMP_BATCH_TRACE`).

**USB:** the OHCI thread gave up after 30 s if the driver had not yet
started the controller. Amped 2 starts it at 28–33 s, so the pad was
missing on roughly half of all runs. It now waits indefinitely.

**Why the menus stack:** the menu sprites' composite matrix `c[96..99]`
has an x row of (0,0,s,0). Every vertex lands on screen x = 320.5 and
most get w < 0, so the near clip drops them. Tracing it back:

- The heap holds the matrix stack at `0x015D9CF0`: world, **view**
  (`0x015D9D30`), projection (RH, x scale 1.9445, y scale 2.5927, zn 0.5),
  then the composites.
- The view is written by `sub_0002DFFA` (LookAtRH: eye in edi, at and up
  on the stack, out in esi), called from the camera method `sub_00247DE0`
  and that from `sub_000B5030` (camera update). Three GUI cameras run
  every frame:
  - `0x017CF790`: identity node
  - `0x01861350`: correct; eye (0.5,−0.5,623.25), at (0.5,−0.5,0)
  - `0x017D17A0`: at (1,−1,623.25), a view along (1,−1,0)
- Camera 3's local target is (0.0143,−0.0143,0) = world (0.5,−0.5,0)/35.
  `sub_000B4F50` (camera init from script: reads `target`, inverts the
  node matrix built by `sub_000BE610`, transforms the target) ran while
  the node's translation at `this+0x44` was still 0.
- The translation (z = 623.252 at `this+0x4C`) is written later by
  `0x000BDFDB` from the scene-graph animation pass (`0x002FCD65`,
  recursive `0x000BD6C9`), after a 747-byte ZIP member is read.
- Checked and correct: the lifted inverse `sub_0002D884` (against a
  double-precision reference, including this exact matrix), LookAt,
  cross product `sub_0002D4D3` (computes ecx × eax), normalize
  `sub_0002D68C`, subtract `sub_0002D51C`, TransformCoord `sub_0002D6FC`
  and `SetVertexShaderConstant` `sub_00323C40`.

So the remaining bug is ordering in title logic: the animation pass runs
after the camera init. It still has to be found why that order differs
from hardware.

**Tools used** (all opt-in):

- `RECOMP_BATCH_TRACE=<n>[,<from>[,<stride>]]` prints per-batch state and
  `c[96..99]`.
- `RECOMP_FIND_FLOAT=<v>` (with `RECOMP_FIND_FLOAT_CTX=<rows>`) finds
  matrices in guest RAM by value.
- `RECOMP_WATCH=<va>` (toolkit, page-protection) gives the writer's guest
  call chain.
- `amped2_diag()` in `recomp_manual.c` is a stderr printf for probes
  pasted temporarily into generated code, which cannot include
  `stdio.h`.
- `tools/check_lifted_inverse.py` runs a lifted function over a copy of
  the XBE and compares it against a reference.

### Menus fixed, level-load crash fixed, in game (2026-09-29, midday)

**Menu camera: a lifter bug, not ordering.** `ucomiss x, 0; lahf; test
ah, 44h; jp` ("is this float non-zero") lifted `lahf` to a comment,
because the comiss branch of the lifter's condition table had no `js`.
`sub_000BD8E0` (scene-graph node transform) uses the idiom for
position, rotation and scale, so camera `0x017D17A0` randomly lost its
translation. Fixed in toolkit `392a0a2`; 60 of 61 sites are lifted now.

**Level-load crash: page 0.**
- XAPI's USB driver keeps its device extensions in physical page 0,
  with no allocation. Its private pool, `sub_0033195B`, returns
  `0x80001000` minus what it has used. The KDPC was at `0x80000D04`.
- The toolkit's contiguous allocator started at physical 0, so the
  title's first 14 MB pool began on that page.
- Loading ML1, the title draws a depth-only pass with colour offset 0
  and colour mask 0, which the executor rasterised anyway into page 0.
- The results: a DPC routine pointer of `0x00200020` (UTF-16 spaces), a
  CString crash inside the USB DPC, `XInputGetState` reading garbage,
  and OHCI giving up.
- Fixed by reserving the bottom 64 KB of the window (`d41338a`) and by
  honouring `SET_COLOR_MASK` (`e4bd3bf`). Both allocators are locked
  now too.
- Because every contiguous block moved up by 0x10000, the DSP mailbox
  default in `main.c` is now `0x8106C810`.

**How it was found:** a raw stack dump in the crash handler, the current
DPC routine (`g_xbox_current_dpc`), `RECOMP_DPC_TRACE`, `RECOMP_WATCH` on
the KDPC's routine field (which now names a host writer by exe offset),
dbghelp on that offset (`put_pixel`), `RECOMP_CONTIG_TRACE`, and
disassembling the driver's pool routine.

**Seeds:** `0x00103840` and `0x00014760` (level load). `0x001C8C20` is
still unresolved in game.

**Unattended walks:** `tools\diag.ps1 -FreshSave` moves the saved
profiles (`game\UDATA\4d530041\<id>`) aside, so a walk creates a player
instead of looping on "That player already exists. Overwrite?"
(default No).

### Register combiners (2026-09-29, afternoon)

The black terrain was the executor's pixel model. It did texture 0 ×
diffuse, and ML1's terrain has a 2048×2048 lightmap in stage 0 (found by
dumping textures with `RECOMP_TEX_DUMP`), with its snow detail in another
stage. `RECOMP_TEX_STATE` showed all four stages enabled, and the top
unhandled methods had been the combiner registers all along.

Toolkit `c5300e9` adds a software register combiner
(`src/kernel/nv2a_combiner.c`, using Xbox D3D's `PS_*` encodings),
per-stage texture state, and oD1 plus oT0–oT3 carried per vertex. The
menus now match the game, including the rider portraits that used to be
dark, and ML1 renders snow, forest, lifts, sky and the HUD.
`RECOMP_NO_COMBINERS=1` switches back to the old path.

### GPU backend (2026-09-29, evening)

Toolkit `bb4b030` draws on D3D11. It's on by default (`main.c` sets
`RECOMP_GPU=d3d11`; `RECOMP_GPU=software` gets the software path back).
The executor still decodes the pushbuffer; only draws, clears and flips
change. Vertex programs and combiners become HLSL (`nv2a_hlsl.c`), and
textures and surfaces are cached on the GPU by guest address. Finished
frames are read back into the same window, so `RECOMP_FB_DUMP` and
`RECOMP_FB_WINDOW_DUMP_EVERY` still work. The front end runs at 60–90 fps
and ML1 at about 46 fps on the RTX 2070 (`diag/gpu3`, `diag/prof2`).

Switches: `RECOMP_GPU_DEBUG` (D3D11 debug layer), `RECOMP_GPU_ADAPTER=default`
(don't pick the high-performance GPU), `RECOMP_GPU_CULL` (backface culling;
off until the winding has been checked on screen), `RECOMP_FLIP_INTERVAL=<n>`
and `RECOMP_FLIP_NOWAIT` (flip pacing), `RECOMP_DVD_SPEED=<KB/s>` (reads take
disc time), and `RECOMP_GUEST_CPU=<n>` (all guest threads on one CPU).

In game, the main thread spends about 40% of its time in `sub_0031EC30`. That
function sets PFIFO `0x100410` bit 16 and spins until the executor clears it,
which is D3D's CPU/GPU sync point. So frame time is roughly game time plus
executor time. Per frame in ML1: about 800 draws, 2.9 MB of vertex copies,
3.3 MB of texture hashing, and 5 ms inside `nv2a_d3d11_draw`.

**Level-load race (fixed, toolkit `e8ca4b3`).** With the GPU backend the ML1
load failed about half the time, and every time at disc speed. The title's
out-of-memory handler (`0x0002B6C0`, reached from `0x000DC1D6`) launched
`d:\Boom.xbe` when the boarder's 41,000-byte `"SkeletonData"` sub-heap
(created at `0x0017C83A` by `sub_000DBE50(parent, 0xA028, 1, 0)`) ran out.

Timestamped probes (`amped2_race`, pasted into the generated code) showed
the order. The loader thread starts loading the front-end preview boarder
(`sub_0017C780`), creates its heaps, and is still loading 11 s later. By
then leaving the menu has run the teardown (`sub_0017BF20` at
`0x0017BFAD`, called from `0x0017BFE0`), which destroys those heaps under
it. The native profile of the loader explained the 11 s: 71% `WriteFile`.
`bridge_NtReadFile` printed and flushed a `[READ]` line per read, and the
skeleton loader (`0x0015D710`, recursive) reads a node at a time. The
software rasteriser's slow menus had always left the load enough time.
With the per-read trace opt-in (`RECOMP_READ_TRACE=1`), 4/4 loads reach the
level, disc speed included (`diag/fx1`–`fx4`).

Ruled out on the way: flips at 30 fps, one guest CPU
(`RECOMP_GUEST_CPU`, which also hangs), and priority boosts. Found on the
way: new threads copied the main thread's live TLS block (current-heap
stack included). They now copy a snapshot taken at load (`2fcc6f4`).
**Lesson:** per-call logging on the file path changes the title's timing
enough to lose its races. Keep hot-path traces opt-in.

To trace allocations again, paste
`amped2_alloc_probe(edi, MEM32(esp + 0x28), eax, MEM32(esp + 0x24))` into
the generated `sub_000DC0F0` at `loc_000DC1B8`. The out-of-memory wrapper
then prints callers by heap and thread, and `RECOMP_AP_HEAP=<object>` logs
one heap's allocations.

### Missing rider torso (fixed, toolkit `44a58ec`)

In game only the rider's legs, board and hair rendered, on both draw
paths. `RECOMP_VP_BAD` (toolkit `db5116f`) found the torso batches
collapsed to one point with w ≈ −974. `tools/vp_disasm.py` shows their
program is 4-bone skinning:
- `a0 = v3*c[168].x`, with `c[168].x` = 256;
- the rows are `c[a0+0..2]`;
- oPos = `r5·c[164..167]`, the view-projection.

At the draw, the palette rows in the executor's constant memory were
identity, so the vertices stayed in model space and ended up behind the
camera.

The CPU was right. Probes in the palette upload (`sub_0014D5D0`: it
multiplies inverse-bind `[obj+0x30]` by bone world `bone+0x30` with
`sub_0002D786`, transposes with SSE, and uploads with `sub_00323C40`
starting at register −96) showed world-placed rows, for example bone 2
translated to (1214.45, 459.5, 0.75). **The upload never reached the
executor.** `nv2a_pb_scan` ended a segment at any jump and skipped calls,
so pushbuffers D3D runs from outside the ring (`RunPushBuffer`, recorded
buffers) were never executed. It now follows jumps out of the ring until
one lands back in it, plus one level of call/return: about 23,500 per
140 s run. The rider renders whole (`diag/fb_jmp1.bmp`).

### Render thread and pacing (2026-09-29, night)

D3D11 calls run on a render thread (toolkit `05d62ed`). The executor queues
packets, and the display paces at 60 Hz with up to
`RECOMP_GPU_FRAMES_AHEAD` (2) frames queued. ML1 runs at about 50–55 fps
paced and about 70 unpaced (`RECOMP_FLIP_NOWAIT=1`).

### Sound heap out of memory and the APU freeze (fixed, 2026-09-29/30)

**The out-of-memory was a lifter bug.** XACT's track state machine
`sub_00316595` joins a 16-bit `cmp word [esi+30h],7` and a 32-bit
`cmp eax,7` at one `jne` (`0x003165E3`).
- The translator refused to merge compares of different widths, so the
  `jne` became the `_flags` fallback, which is always false.
- As a result, every transition into track states 3–6 was "illegal". The
  track start `0x0031449F` returned E_FAIL, and every SoundBank Play
  (`0x00310369`) failed.
- Play's error path (`0x00310343`) stops the cue. That frees the track's
  reference but not the cue's own, so each sound the game played leaked a
  64-byte cue (refcount 1, flags 4, no tracks) plus a chunk of the size-class
  pool (`0x0001304D`). The pool never returns chunks to the heap.

The fix is toolkit `a5335eb`: mixed-width joins merge into a marker that
answers only the width-independent conditions.

How it was found:
- A free probe showed 0 heap frees of the chunks.
- Object tracking at `operator new`/`delete` (`sub_0002CFD0`/`sub_0002D040`)
  found 4,091 cues and 30 deletes.
- A cue lifecycle trace showed play → new → stop from the error path.
- `setst 1→5` returned 0, which the original code allows.

The probes are kept in `src/recomp_manual.c`: `amped2_new_probe`/
`amped2_delete_probe`, and `amped2_cue_event` with
`RECOMP_CUE_TRACE=<lines>`. Paste them into gen as the comments say.

**With sounds playing, the game then froze after 1–4 min.** The APU frame
thread spun forever in `voice_process`:
- A persist stream voice with no SSLs left makes `voice_get_samples`
  answer -1 with a notification. `voice_resample` turned that into 0, and
  the caller loops until it gets a negative count. The frame thread spun
  with `d->lock` held and wrote tens of millions of notifications.
- The next DirectSound `VOICE_LOCK` write (`sub_0029694E`, through the MMIO
  VEH) then waited on `d->lock` while holding the title's DirectSound lock.

The fix is toolkit `db6b76c`, which also makes the frame thread hand the
lock to queued writers. `RECOMP_APU_STATS=1` prints voice, notification and
frame-rate counters every 5 s.

Now the default: the APU reads the contiguous window (`AMPED2_APU_PHYS=0`
restores the old silent base). In-game audio plays throughout
(`diag/audio_fixed.wav`). `soak4` ran 15 min in ML1 at about 51 fps.

### Locked 60 fps in ML1 (2026-09-30, night)

Paced ML1 ran at 53–55 fps, though the game can do 80 unpaced
(`RECOMP_FLIP_NOWAIT=1`). A deeper frame queue (`RECOMP_GPU_FRAMES_AHEAD`
3 or 4) made no difference. `RECOMP_PACE_TRACE=1` shows the cause: steady
state was fine, with the render thread waiting about 12 ms per flip, and
the rate was lost in hitches.

- **Every 2 s, about 100 ms:** the kernel-call summary. It is now opt-in
  with `RECOMP_KERNEL_SUMMARY`.
- **Every 10 s, about 430 ms:** the GPU report on the executor thread. Each
  `fprintf(stderr)` cost 12–15 ms with stderr redirected to a file by
  `diag.ps1`. `main.c` now sends stderr through a 1 MB pipe drained by a
  writer thread. `RECOMP_SYNC_STDERR=1` restores the synchronous stderr;
  the pipe is drained at exit, in the crash reporter, and through the
  toolkit's `g_xbox_flush_logs` before ExitProcess and `_exit`.
- **80–300 ms whenever a vertex program is seen for the first time:**
  `D3DCompile` of the generated HLSL (500+ lines) on the render thread.
  Even with optimization skipped it takes about 110 ms. The game keeps
  meeting new programs for minutes into a level, as it builds them from
  material and light state. Shaders now compile on a worker thread, and the
  draws that need one are skipped for the frame or two until it's ready
  (`RECOMP_GPU_ASYNC_SHADERS=0` restores blocking). They're also cached on
  disk in `shader_cache/` (`RECOMP_SHADER_CACHE`).

Result: 600 flips in 10.00 s, repeatedly, with zero resyncs, from a cold
cache (`diag/async3`). Only level loading still hitches. A screenshot shows
nothing missing (`diag/async_game.png`).

**Lesson:** logging is not free here. Anything printed from the executor,
render, APU or guest threads has to be rare or go through the pipe.

### Soundtrack (fixed, toolkit `515a44d`, 2026-09-30)

The jukebox builds its playlist by listing `d:\Audio\Music`, then each
genre directory, with `NtQueryDirectoryFile` and an empty pattern (a
buffer of length 0). The Windows implementation searched `dir\` for that,
found nothing, and answered STATUS_NO_MORE_FILES straight away. The game
only ever opened the six hardcoded probe tracks (a 4-byte ASF check), and
music never played.

An empty pattern now means `*`. The menus open a song
(`HardCore\HEAVENS TO MURGATROID.wma`), and front-end audio starts at 20 s
instead of at level start (`diag/audio_music1.wav`). `RECOMP_DIR_TRACE=1`
logs each query.

### FMV (still open, 2026-09-30)

With `AMPED2_PLAY_MOVIES=1`, the first movie (`Movies\MGS.xmv`) stays
black.

- The player (`sub_00150FF0`) called `D3DDevice_BlockUntilVerticalBlank`
  (`sub_0031AE90`) whenever its decoder had no frame ready. That waits on a
  KEVENT which D3D's GPU interrupt handler sets, and nothing raises that
  interrupt here, so it waited forever. `recomp_manual.c` now replaces it
  with a wait for the kernel's 60 Hz vblank tick.
- The decoder still never has a frame (`sub_00329420` returns 0). XMV paces
  video on its audio stream. `RECOMP_APU_STATS` shows 7 voices started and
  0 notifications, with the APU active (SECTL 0x0F, FECTL 0x100F). So the
  movie's stream voices are never consumed.
- They are on the 2D list (top `0x47`). Voice `0x47` has format
  `A180E0E6` and state `0x00240000`, which is ACTIVE plus PAUSED, at
  offset 0 (`diag/fmv7`). The movie's audio stream starts paused and nothing
  resumes it, so the XMV clock never moves.
- The voice is not paused by DirectSound's pause helper `sub_002939AD`,
  the only writer of `VOICE_PAUSE` (`0xFE820140`). A probe there saw no
  write at all, and our `VOICE_ON` does not set the bit, so the stream was
  created paused. No resume ever comes either: XMV holds its audio back
  itself, probably until the first video frame decodes. The file is read
  twice at offset 0 (4 KB and 68 KB), then never again (`fmv8`).
- Next: follow `sub_00329420` (the frame-ready check) to see what the
  decoder waits for after that first read. `xbox_VideoPlayFile` is the
  host-side `.wmv` player (`RECOMP_FMV_HOST`) and is not involved.

### Known toolkit issue (for upstream)

The lifter emits immediate shift counts unmasked: `shl ecx, 0x32` becomes
`ecx << 0x32` (C4293, undefined behaviour), where x86 masks the count to 5 bits
(`0x12`). The 8 hits here are all in data decoded as code in the last chunk
(`recomp_0057.c`), so they are harmless for Amped 2. The same lift on real code
would be wrong.
