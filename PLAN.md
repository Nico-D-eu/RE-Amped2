# Amped 2 recompilation: project plan

**Goal:** a native Windows build of *Amped 2* (EU, `0x4D530041`) that plays
the whole game at least as well as the original Xbox. Once that works, it
becomes a moddable base: higher-resolution rendering, AI-upscaled textures,
and new content.

**The one rule of this plan:** no mod work (Phases 6–9) starts before
milestone **M4 "Playable"** is met. The only exception is keeping the
already-written asset toolkit (`tools/assets/`) and the texture-pack
format consistent. Mod features on a runtime that can't draw a frame
can't be tested, and they grow the surface area we have to debug.

**Update (2026-09-30, night): sound works and ML1 holds 60 fps.**
- **Sound.** The sound-heap out-of-memory was a lifter flag-join bug in
  XACT (toolkit `a5335eb`). The freeze that followed was the APU spinning
  on a dry stream voice (`db6b76c`). The APU now reads the right memory by
  default, and in-game sound plays throughout. Front-end music (WMA) is
  still silent: the game never opens a song after its jukebox scan.
- **Frame rate.** Paced ML1 is a locked 60.0 fps, 600 flips in 10.00 s,
  even with a cold shader cache (`0e5554b`, and async stderr in `main.c`).
  The hitches came from logging on hot threads and from compiling shaders
  on the render thread.
- **Soak.** 15 minutes in ML1 with no crash, no out-of-memory and no freeze
  (`soak4`).

**Update (2026-09-29, evening): the D3D11 GPU backend is in** (toolkit
`bb4b030`, the default via `RECOMP_GPU=d3d11` in `main.c`). Vertex programs
and register combiners are compiled to HLSL; textures, render targets and
depth live on the GPU. The front end runs at 60–90 fps and level ML1 at
**about 46 fps** (was 1.6), on the RTX 2070. Flips now wait for a 60 Hz
vblank. **The level-load failure is fixed** (`e8ca4b3`). Per-read logging made a
front-end character take 11 s to load, and leaving the menu destroyed its
heaps mid-load; 4/4 loads now reach ML1. **The rider renders whole** (`44a58ec`): the pushbuffer walker now follows jumps and calls out of the ring, and **fog** is in (`f6c8405`). Next: shadows,
presenting to a swap chain with upscaling, and cheaper per-draw state.

**Update (2026-09-29, later afternoon):** lit models render (packed
normals, `7984c71`), and the executor is about twice as fast (`0afb035`),
at roughly 1.6 fps in game. That's the ceiling of the single-threaded
software renderer: the game waits on it. **Next decision: a GPU
backend.** Vertex programs → HLSL, combiners → pixel shaders, texture
upload/swizzle/DXT, render targets and depth on D3D11. The toolkit's
`src/nv2a/nv2a_pgraph_d3d11.c` is a 653-line 2D-menu prototype for
another title, not a base for this. The alternative is a multi-threaded
software path with predecoded vertex programs, which is cheaper but
probably tops out at a few fps.

**Update (2026-09-29, afternoon):** with register combiners and four
texture stages in the executor (toolkit `c5300e9`), **the front end and
level ML1 render like the game**: the logo and snow backdrop, the rider
portraits, and in game the snowy slopes, forest, lifts, sky, HUD and
CHALLENGES panel (`diag/comb_menu_sheet.png`,
`diag/comb_game_sheet.png`). Still open: the rider model draws black,
sky-strip tearing, fog, shadows (the depth-only pass isn't sampled yet),
and speed (software rasteriser).

**Status (2026-09-29, midday):** Phase 3 started. **The game is
in a level.** An unattended walk (START+A pulses, fresh save) goes from
the title through the front end, which renders correctly with no stacking,
to career save, RIDE!, the LOADING screen, and into **level ML1**. There
the 3D world renders: trees, lift towers, mountains, the in-game
CHALLENGES panel and the score HUD (`diag/ingame1_sheet.png`). It runs
10 minutes with no crash. What's still wrong in-game: the snow terrain
draws black, there are depth/alpha glitches, and one function
(`0x001C8C20`) is still unresolved. Details in `CHANGELOG.md`.

The three fixes that got here:
- the lifter's `lahf` after `ucomiss` (the menu camera),
- contiguous memory kept off physical page 0, where XAPI's USB driver
  lives,
- the executor honouring `SET_COLOR_MASK`, so a depth-only pass no
  longer paints page 0.

---

## Milestones

| # | Milestone | Meaning | Phase |
|---|---|---|---|
| M0 | Builds & boots | Exe builds and reaches guest code | 0 ✅ |
| M1 | First frame | Anything guest-rendered is presented to the window | 1 |
| M2 | Menus | Legal screens → title → main menu, navigable with a pad | 2 |
| M3 | On the mountain | One level loads and the rider can be controlled | 3 |
| **M4** | **Playable** | **Career run on every level, audio, saves, no crash** | 4–5 |
| M5 | Mod framework | Loader, asset overrides, hooks, config | 6 |
| M6 | HD | Resolution scaling, widescreen, texture pack in-game | 7 |
| M7 | New content | First custom character and remixed level | 8 |
| M8 | Release | Distributable patch or launcher, no game data | 9 |

---

## Part A: Get the game up and running

### Phase 0: Foundation ✅ (done 2026-09-28)

- Extract the disc; parse, disassemble, identify, ABI-analyse and name the
  functions (Ghidra FidDb); lift to C (14,714 functions, 59 chunks).
- CMake/MSVC build (VS 2026), `tools/regen.ps1`, `tools/diag.ps1`,
  watchdog and thread sampling.
- Fixes so far: 3 seeds (`0x00254825`, `0x00259939`, `0x0031CB60`) and a
  native `memmove`.

### Phase 1: First frame (M1)

**Problem:** after D3D init the main loop in `sub_001455C0` polls a shared
value under `RtlEnter/LeaveCriticalSection` and never moves on.

Work items, in order of likelihood:

1. **Find what the loop is waiting for.** Disassemble `sub_001455C0` in
   Ghidra and name the global it polls. Then find every writer of that
   global (Ghidra xrefs). The writer tells us which thread, ISR or
   callback is missing.
2. **GPU interrupts and vblank.** Check that the vector-3 ISR at
   `0x003220C0` (connected via `KeConnectInterrupt`) actually runs with
   `RECOMP_VBLANK`, and that its DPC runs as well. D3D8LTCG's `Present`,
   `BlockUntilIdle` and fence waits depend on it. Compare against
   `docs/technical/d3d8ltcg-device-context.md`.
3. **Threads.** Diff `sample_threads` against the expected set: main, the
   worker at `0x00259939`, and any audio, streaming or loader threads.
   Seed any start routine that never runs.
4. **Quiet probe failures.** Walk the D3D, DSOUND and XACT init return
   values. A failed `CreateDevice`-style call that the title ignores
   usually shows up later as a wait like this one.
5. **Pushbuffer execution.** With `RECOMP_PB_EXEC=1`, confirm the NV2A
   translator handles the methods in the first three submits (clear,
   surface setup) and that a `Present`/flip shows up.
6. ~~Look into the `recomp_0020.c` compile stall (31 min)~~. Done
   2026-09-29: `sub_00148D80` is compiled unoptimised through
   `config/no_optimize.txt`, and a full rebuild takes ~7.5 min.

**Exit criteria**

- [x] The main loop leaves `sub_001455C0` (2026-09-29: the stall was
      downstream failures, now fixed; boot reaches `app->Run()`)
- [ ] At least one `Present` or flip reaches the host swap chain
- [x] The window shows a guest-rendered image (the legal or splash screen)
      (2026-09-29: title splash, `RECOMP_FB_WINDOW`)
- [x] The finding is written up in the README's bring-up notes

### Phase 2: Frontend and menus (M2)

- **Rendering correctness:** the UI's NV2A combiner and vertex shader paths
  (`docs/technical/nv2a-shaders.md`), texture formats (DXT1/3, swizzled
  A8R8G8B8/L8/A8), alpha blending, and render-to-texture if the UI uses it.
- **Input:** XInput to Xbox pad mapping; the pad is detected at the "press
  Start" screen (`RECOMP_PAD_PRESS` for automated runs).
- **Storage:** `UDATA`/`TDATA` save paths, `TitleImage.xbx`, and a
  `NtFsControlFile(0x90020)` stub that returns success rather than
  `0xC00000BB` if the title needs it. Trace the one failed
  `ERROR_PATH_NOT_FOUND` open.
- **Online:** stub the Xbox Live paths (XONLINE, XNET, XVOICE) so the
  menus don't wait on a network sign-in. Force-return where needed.
  *(2026-09-29: `XNetGetTitleXnAddr` now reports NONE via
  `config/force_return.txt`, which removed the post-splash deadlock.)*
- **FMV:** decide whether XMV plays (`tools.xmv`) or is skipped for now.
  Skipping is acceptable for M2. *(2026-09-29: skipped by default,
  `AMPED2_PLAY_MOVIES=1` to play. XMV waits on an audio clock the APU
  doesn't advance.)*
- ~~**Front-end rendering:** the executor drew the UI squashed into the
  top-left.~~ Done 2026-09-29: vertex-program interpreter
  (`src/kernel/nv2a_vp.c`), viewport constants, general blending, texture ×
  vertex colour. The title screen renders cleanly. Still missing:
  fixed-function T&L (some batches run in mode 0x4), per-vertex (Gouraud)
  colour, multi-texture, register combiners, depth.
- ~~**Input:**~~ Done 2026-09-29: USB wired in `main.c`, the toolkit's
  bus-address fix, and seeds for the XPP class-driver and report routines
  (`0x003306DF`, `0x0032FC8B`). START is read; the menus navigate.
- ~~**Menu camera.**~~ Done 2026-09-29 (toolkit `392a0a2`). It wasn't an
  ordering problem: `lahf` after `ucomiss` was never lifted, so
  `sub_000BD8E0` decided at random whether a node's position was set.
- ~~**Level-load crash.**~~ Done 2026-09-29 (toolkit `d41338a`,
  `e4bd3bf`). A depth-only pass painted physical page 0, where XAPI's
  USB driver keeps its structures.
- ~~**In-game rendering: black terrain.**~~ Done 2026-09-29 (toolkit
  `c5300e9`): register combiners and texture stages 0–3. `0x001C8C20`
  seeded.
- **In-game rendering (next):**
  - the rider draws black: check its combiner inputs, likely lighting
    in V0/V1 or a stage mode that isn't modelled;
  - fog (the FOG register is taken as factor 1);
  - shadows (the depth-only pass as a texture: shadow compare);
  - fixed-function mode `0x4` batches (the shadow pass);
  - speed.
- ~~**Depth, Gouraud, perspective, alpha test in the executor.**~~ Done
  2026-09-29 (toolkit `963ef99`). Fixed-function T&L (mode `0x4`) and
  register combiners are still open.
- **Menu rendering: 3D in the executor.** The streaks are fixed
  (near-plane clipping). The remaining problem is menus stacking over one
  another. The title clears colour only a few times a run and relies on a
  3D background to cover each frame. It needs, in order: a depth buffer
  (NV097 zeta surface, depth test/func, Z clears), fixed-function T&L for
  execution mode `0x4` batches (composite matrix, `0x0680`), per-vertex
  (Gouraud) colour and perspective-correct UVs, then register combiners
  (`0x0A60`…) and multi-texture. The alternative is bringing up the
  toolkit's D3D11 PGRAPH translator (`src/nv2a/nv2a_pgraph_d3d11.c`) and
  feeding it the vertex-program interpreter's output. That's bigger, but
  it's the path to in-game rendering at speed.

**Exit criteria**

- [x] Legal → splash → title → main menu with no manual steps
      (2026-09-29: splash → title automatic; START reaches the menus,
      which render correctly since the lahf fix)
- [ ] All top-level menus open and close with a pad
- [ ] No unresolved indirect calls reached in the frontend
      (2026-09-29: only `0x002C8DAD`, XNET, deliberately left unseeded)

### Phase 3: In-game (M3)

- Level loading: `Levels/*/*.pgf` geometry, `.trees`, lightmaps, and the
  streaming thread, if there is one.
- Character loading (`Characters/**`), skeletons and `.ani` animations,
  including the skinning path in the vertex shaders.
- Physics and x87 precision: board and snow physics are float-heavy, so
  check the lifted x87 code against xemu for drift (conformance tests,
  `docs/technical/conformance-testing.md`).
- The Lua 5.0 beta VM runs game scripts. Confirm that script-driven events
  (challenges, photographers, sponsors) fire.
- Camera, the HUD (`GuiPackages` HUDs), and the replay system.

**Exit criteria**

- [ ] One level (the first career level) loads and renders
      (2026-09-29: ML1 loads, runs and renders on the GPU at about 46 fps;
      no fog or shadows yet)
- [ ] The rider can be controlled, tricks register, the score works
- [ ] The run can be finished and exited back to the menu

### Phase 4: Complete systems

- **Audio:** DSOUND and the APU/DSP, XACT (`XACTENG`), and WMA decode
  (`WMADEC`) for the soundtrack. Custom soundtrack support is optional.
- **FMV:** XMV playback of `Movies/`.
- **Saves:** career save and load round-trips, and profile handling.
- **Every level:** every mountain loads (`AU`, `BK`, `BR`, `HD`, `LX`,
  `ML`, `NZ`, …), along with every game mode, splitscreen multiplayer and
  character creation (`NewCareer*`).
- Hit every remaining `RECOMP_UNIMPL` in live code, and every unresolved
  call target (109 are stubbed now) that is reached.

### Phase 5: Stability and performance (M4, **Playable**)

- A full career playthrough with no crash and no soft-lock.
- A frame-pacing target of a locked 30 or 60 fps (as on Xbox) with no
  stutter on the RTX 2070 laptop. (2026-09-30: ML1 is locked at 60 after
  loading. Level loads still hitch, and other levels are unmeasured.)
- Faster builds: hot-rebuild a single chunk, and `/MP` tuning.
- Fix the lifter's unmasked immediate shift count (C4293) upstream if any
  real code turns out to hit it.
- Record known issues in the README.

**M4 exit criteria (the gate for Part B)**

- [ ] Every level and mode can be played start to finish
- [ ] Audio, music and FMV work
- [ ] Saves persist across restarts
- [ ] 60 minutes of play with no crash
- [ ] The build reproduces from a clean checkout plus the user's own disc

---

## Part B: Mods (only after M4)

### Phase 6: Mod framework (M5)

The base every later mod builds on. None of the later phases should need to
touch generated code directly.

- **Virtual file system overlay.** The kernel file layer checks
  `mods/<pack>/…` before `game/…`, which allows loose-file overrides of
  any archive entry without repacking. `.gfx`/`.res` are ZIPs, so this is
  an overlay on top of the archive, keyed by entry name.
- **Mod loader and config.** A `mods/mods.json` (or TOML) with enabled
  packs, load order and per-mod settings; a user-facing `amped2.ini`
  for graphics and input options.
- **Hook points.** A documented way to wrap a guest function from
  `recomp_manual.c` (pre/post hooks by address), so mods don't fork the
  generated code.
- **Lua script overrides.** Load replacement scripts, whether compiled or
  source recompiled to the 5.0 beta format, through the overlay. The
  scripts drive characters, levels and challenges, so this is the main
  content lever.
- **A debug overlay** (Dear ImGui): FPS, the loaded mods, texture-pack hit
  and miss counts, and a free camera.

### Phase 7: Graphics upscaling (M6)

In order: the cheapest win first, and the ones that affect gameplay last.

1. **Internal resolution scaling.** Render guest surfaces at N× (up to
   4K), which means scaling viewports, scissor, render targets and depth
   buffers in the D3D8→D3D11 layer. This isn't in xboxrecomp yet; build
   it upstream so every title gets it.
2. **Widescreen 16:9 / 21:9.** Patch the projection aspect and FOV in game
   code, and put the HUD in the 4:3 safe area or anchor it to the edges.
3. **AI-upscaled texture pack.** Add the runtime hook the asset toolkit
   already targets: on texture create, key =
   `crc32(top mip)_WxH_fmt`, and load `mods/texture_pack/<key>.dds` (BC7,
   full mips) into host VRAM only. Pipeline: `tex-export` → `tex-upscale`
   (Upscayl, `ultrasharp-4x`) → hand edits in `mods/textures/edit/` →
   `tex-pack`. Needs a hit and miss report, plus a dump of missed keys to
   catch textures created at runtime.
4. **Anti-aliasing and filtering:** MSAA or SMAA and 16× anisotropic
   filtering.
5. **Optional extras:** higher-precision shadows, a higher LOD distance,
   60 fps or an uncapped framerate. Needs the game timestep to be
   separated from the frame rate first, so it goes last and needs its own
   physics check.

**Exit criteria:** 4K widescreen with the full texture pack and no visual
regressions on any level, at a steady framerate.

### Phase 8: Additional content (M7)

Built from existing parts first, then new assets.

- **New characters.** Use the `NewCareerParts` system: new part and
  texture combinations, then new meshes once the `.pgf` mesh half is
  decoded. Then new `.tmap` and `.ani` entries, and a pro rider slot
  through the script overrides.
- **Level remixes.** Rearrange objects, rails, jumps and challenges using
  the level scripts and object placements on existing mountains. New
  lighting and time-of-day variants come after that.
- **New challenges and modes:** script-driven goals, photographer and
  sponsor tasks, score attack.
- **Music:** add tracks to the soundtrack list (WMA or a host decoder).
- **Tooling needed first:** decode the `.pgf` mesh block, the `.ani`
  format and the level object placement format. Add round-trip tests for
  each: decode, re-encode, then byte-compare the output with the input.

### Phase 9: Release (M8)

- Distribution **without any game data**: the user supplies their own disc
  image. The installer or launcher extracts it, verifies hashes, builds or
  applies the recomp, and drops in the mod packs.
- Mod pack format and docs for other modders.
- License check: xboxrecomp's license, third-party tools (texconv, unluac,
  Upscayl models) and their redistribution terms.

---

## Part C: Input and other platforms (options, after a stable M4)

Not on the critical path. Written down so the options stay open once the
Windows build is stable. The generated game code is plain C and doesn't
care what it runs on. What ties it to Windows is the toolkit runtime:
- guest memory mapped at fixed addresses (a file mapping, plus the
  contiguous window at `0x80000000`);
- **device registers emulated by page faults**, a vectored exception
  handler that decodes the faulting *x86-64* host instruction (APU, OHCI,
  AC'97);
- Win32 threads and events;
- the D3D11 renderer, XAudio2 or waveOut, the GDI window, and XInput.

### Phase 10: Input

- **Remappable keyboard → controller.** Today the keyboard mapping is
  fixed in `xboxrecomp/src/input` (Enter = START, arrows = d-pad,
  Z X A S = A B X Y, Backspace = BACK), with no analog sticks or triggers.
  Add a `config/input.ini` with per-key bindings, keys for stick
  directions (with a modifier for half-tilt), the triggers, and Black and
  White. **Effort: low.**
- **Any controller, including Bluetooth.** XInput covers Xbox pads, wired
  or Bluetooth. An SDL3 gamepad backend (HIDAPI) adds DualShock 4,
  DualSense, Switch Pro, 8BitDo and generic pads, with hot-plug. It maps
  to the emulated USB Duke pad the game already reads, analog buttons
  included. **Effort: low to medium.**
- **Rumble:** route the pad's USB output report (motor speeds) to
  XInput or SDL rumble. **Effort: low.**
- **Two to four players** for split-screen modes: one emulated USB pad
  per host controller, on the OHCI root-hub ports. **Effort: medium**; it
  needs the OHCI model to expose more than one port.

### Phase 11: Other platforms

| Target | What changes | Effort |
|---|---|---|
| **UWP: Windows Store, and Xbox One/Series in Dev Mode** | Still Windows and D3D11, so the renderer and audio carry over. Swap GDI for CoreWindow and a swap chain (Phase 7 needs one anyway), file mappings for `CreateFileMappingFromApp`/`MapViewOfFile3FromApp`, and XInput for `Windows.Gaming.Input`. Game data goes in app-local storage. Check that fixed-address mapping and a vectored exception handler are allowed inside the app container. On Xbox Dev Mode, a "Game" app gets enough memory (the game needs ~64 MB guest plus the host). | **Medium.** The most realistic port. |
| **Android (ARM64)** | The generated C compiles for ARM64 once the lifter's SSE helpers (`XMM_*`) have scalar or NEON versions. Device emulation needs a SIGSEGV handler that decodes *ARM64* loads and stores (or MMIO calls emitted by the lifter, which would be cleaner everywhere). Also needed: a Vulkan (or GLES) backend next to D3D11, AAudio audio, Android input, `mmap` for memory, and pthreads for the kernel's threads. | **High.** |
| **Nintendo Switch** | Same ARM64 work as Android, on either homebrew (libnx, deko3d or Mesa OpenGL) or the official SDK (licensed developers only, under NDA). There are 4 GB of RAM and tight virtual-memory control, so the fixed-address guest mapping needs checking first. | **Highest**, with distribution and legal constraints on top. |

What they'd share, in the order to do it:
1. A renderer interface under the executor, with D3D11 as one backend and
   Vulkan as the second (it covers Android, Linux and Steam Deck).
2. MMIO accesses emitted by the lifter as calls instead of trapped page
   faults. That removes the host-instruction decoder, the least portable
   piece.
3. An audio sink interface.
4. SDL3 for the window, input and audio on everything except UWP and
   Switch.

The same rule as Part B applies: none of this starts before M4, and no
game data ships with any build.

---

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| The Phase 1 wait is a deep runtime gap (interrupt or DPC model) | Blocks everything | Fix it upstream in xboxrecomp and ask on the toolkit's Discord |
| Build times of 20–40 min | Slow iteration | Chunk-level rebuilds, fix the `recomp_0020` stall |
| D3D8LTCG's non-standard shapes | Many rendering bugs | Follow the D3D8LTCG device-context doc and compare frame captures with xemu |
| x87 precision drift in physics | Gameplay differs | Conformance tests against xemu traces |
| The texture hash changes if a texture is modified at runtime | Pack misses | Dump missed keys, and allow alias keys in `index.json` |
| Legal and distribution | Can't share the result | Never ship game data; the user brings their own disc |

## Working agreements

- The detailed log lives in `CHANGELOG.md` (local, git-ignored). This file
  records phases and exit criteria only.
- Commit locally after each meaningful step, and never push (see
  `CLAUDE.md`).
- Toolkit fixes that aren't specific to Amped 2 go into `../xboxrecomp` on
  a local branch, written as upstreamable patches.
