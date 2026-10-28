# RE-Amped2: project plan

**Goal:** a native Windows build of *Amped 2* (USA disc since 2026-10-07; the EU
one works too; `0x4D530041`) that plays
the whole game at least as well as the original Xbox. Once that works, it
becomes a moddable base: higher-resolution rendering, AI-upscaled textures,
and new content.

**The one rule of this plan:** no mod work (Phases 6–9) starts before
milestone **M4 "Playable"** is met. The only exception is keeping the
already-written asset toolkit (`tools/assets/`) and the texture-pack
format consistent. Mod features on a runtime that can't draw a frame
can't be tested, and they grow the surface area we have to debug.

**Update (2026-10-28): Phase 15 done; the toolkit sync next.**
- Test runs are isolated and safe to run next to the player's game.
- Every run keeps a coverage list of reached guesses.
- A crash leaves a report (minidump, guest chain, log).
- The log and F3 name the build.

At the user's request the toolkit sync (Phase 17) comes before the suite
(Phase 16).

**Update (2026-10-26): next phases.** v0.2.0 is released. The user is
testing a full career to the end and the Legend challenges. The work next
to that is Part D (Phases 15–20):
1. test isolation and coverage logs;
2. a regression suite;
3. the toolkit sync to upstream v0.16.0;
4. v0.3.0;
5. split-screen (optional);
6. offline content tooling.

Bugs from the testing come first.

**Update (2026-10-07): USA disc, HD widescreen, in-game PC settings.**
- **Source.** The USA disc is the source now; the EU one still works.
  Both XBEs are the same build apart from the EU rip's media patch.
- **HD.** The game's own 1280x720 16:9 mode is on by default (toolkit
  video-flag fixes, `RECOMP_VIDEO_MODES`), with 16x anisotropic filtering.
  21:9 dropped.
- **Mods.** The string table is decoded, so mods can add text. The main
  menu has "QUIT GAME", and Options → Game Options has WINDOW and
  RESOLUTION, saved to `amped2.ini`.
- **M4.** The clean-checkout build is ticked.
- **Evening.** Done: the texture-pack runtime hook (7.3), FXAA (7.4),
  `mods.json` mod packs, and the F3 debug overlay. The full AI-upscaled
  pack is being built.
- **Next:** ~~more guest memory~~ (done 2026-10-08, `[Game] Memory=128`);
  the free camera; ~~loose-entry overlays~~ and ~~gameplay-script
  overrides~~ (done 2026-10-08).

**Update (2026-10-03): M4 "Playable" reached; Part B (mods) starts.**
The user called M4 after playing every unlocked level, Career, Free Ride,
the sponsor, photo and Pro challenges and sk8 runs, with movies and
sound. Legend runs unlock only once the whole game is completed, so
they are a long-term check. Hiccups found later get fixed as they come. Still open
from the M4 list, kept as follow-ups: a full career to the end, long play
with the dead-voice fix (`c79483a`), in-game movies, and the
clean-checkout build check. First mod work: the menu changes below
(Phase 6).

**Update (2026-10-02, afternoon): the movies play.**
- **FMV.** The boot movies (MGS, XSN, Intro) play with sound and lead to
  the title screen, on by default (`PlayMovies=0` skips them). XMV needed
  D3D's vblank count to move, the TV field pin at port 0x80C0 (the lifter
  now lifts port I/O), the PVIDEO overlay drawn, and PVIDEO_STOP honoured
  (toolkit `1c3c3d4`, `c260dd4`). In-game movies are untested.
- **Sound after long play.** Dead voices left linked in the APU's voice
  lists slowed the APU to a third of real time, and the game with it. DPCs
  now hold the dispatch lock, and traps are serviced at once (`c79483a`).
  Under test; [HEALTH] counts "idle voices linked".

**Update (2026-10-01, overnight): menu rider, in-game state and crackle fixed.**
- **Renderer.** The menu rider is drawn with cube maps and the dot-product
  texture modes (`856bc12`). The pushbuffer walker finishes methods split
  at PUT (`1265dee`). It now runs the ring from a GET pointer and follows
  every jump, wraps included (`58ef72d`), which ends the garbage state and
  the terrain without ground. 240 s in ML1 with pause/resume: no bad state,
  no crash, 58 fps.
- **Sound.** Voices are resampled to their pitch (`0970b90`), so the
  crackle on APU frame boundaries is down 99%.
- **Soak.** 60 minutes in ML1 at 2x internal resolution with constant
  pause/resume: no crash, no bad state, 59.2 fps, memory flat (`soak7`).
- **Settings.** `amped2.ini` beside the exe: window size, borderless (F11),
  render scale 1-8x, WASD or custom key bindings, dead zone, volume.
- **Open:** the loading screen is black (its textures' memory is zero),
  FMV needs the NV2A video overlay, and resyncs come from the fence mirror
  being ahead of the walk (docs/DEVELOPING.md, Bring-up notes).

**Update (2026-09-30, night): sound works and ML1 holds 60 fps.**
- **Sound.** The sound-heap out-of-memory was a lifter flag-join bug in
  XACT (toolkit `59854f9`). The freeze that followed was the APU spinning
  on a dry stream voice (`3ec97f7`). The APU now reads the right memory by
  default, and in-game sound plays throughout. The soundtrack plays too:
  directory listing with an empty pattern was broken (`0bfd7ab`).
- **Frame rate.** Paced ML1 is a locked 60.0 fps, 600 flips in 10.00 s,
  even with a cold shader cache (`c6b2d5e`, and async stderr in `main.c`).
  The hitches came from logging on hot threads and from compiling shaders
  on the render thread.
- **Soak.** 45 minutes in ML1 with no crash, no out-of-memory and no
  freeze, at 60 fps with the soundtrack cycling (`soak6`). FMV is still
  black (docs/DEVELOPING.md, Bring-up notes).

**Update (2026-09-29, evening): the D3D11 GPU backend is in** (toolkit
`0894af8`, the default via `RECOMP_GPU=d3d11` in `main.c`). Vertex programs
and register combiners are compiled to HLSL; textures, render targets and
depth live on the GPU. The front end runs at 60–90 fps and level ML1 at
**about 46 fps** (was 1.6), on the RTX 2070. Flips now wait for a 60 Hz
vblank. **The level-load failure is fixed** (`8619c99`). Per-read logging made a
front-end character take 11 s to load, and leaving the menu destroyed its
heaps mid-load; 4/4 loads now reach ML1. **The rider renders whole** (`199e772`): the pushbuffer walker now follows jumps and calls out of the ring, and **fog** is in (`11b3279`). Next: shadows,
presenting to a swap chain with upscaling, and cheaper per-draw state.

**Update (2026-09-29, later afternoon):** lit models render (packed
normals, `e1950c6`), and the executor is about twice as fast (`6cc0668`),
at roughly 1.6 fps in game. That's the ceiling of the single-threaded
software renderer: the game waits on it. **Next decision: a GPU
backend.** Vertex programs → HLSL, combiners → pixel shaders, texture
upload/swizzle/DXT, render targets and depth on D3D11. The toolkit's
`src/nv2a/nv2a_pgraph_d3d11.c` is a 653-line 2D-menu prototype for
another title, not a base for this. The alternative is a multi-threaded
software path with predecoded vertex programs, which is cheaper but
probably tops out at a few fps.

**Update (2026-09-29, afternoon):** with register combiners and four
texture stages in the executor (toolkit `662ddaf`), **the front end and
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
| M8 | Release | Distributable patch or launcher, no game data | 9 (v0.2.0 tagged 2026-10-25) |
| M9 | Safety net | Isolated test runs, coverage logs, regression suite | 15–16 |
| M10 | Current toolkit | `amped2-fixes` on upstream v0.16.0, suite green | 17 |
| M11 | v0.3.0 | Sharp fonts and optional HD textures at install, unstretched menus | 18 |

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
- [x] At least one `Present` or flip reaches the host swap chain (D3D11 swap chain, 2026-09-29)
- [x] The window shows a guest-rendered image (the legal or splash screen)
      (2026-09-29: title splash, `RECOMP_FB_WINDOW`)
- [x] The finding is written up in the bring-up notes (docs/DEVELOPING.md)

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
  Skipping is acceptable for M2. *(2026-09-29: skipped by default.
  2026-10-02: XMV plays, on by default; see docs/DEVELOPING.md "FMV".)*
- ~~**Front-end rendering:** the executor drew the UI squashed into the
  top-left.~~ Done 2026-09-29: vertex-program interpreter
  (`src/kernel/nv2a_vp.c`), viewport constants, general blending, texture ×
  vertex colour. The title screen renders cleanly. Still missing:
  fixed-function T&L (some batches run in mode 0x4), per-vertex (Gouraud)
  colour, multi-texture, register combiners, depth.
- ~~**Input:**~~ Done 2026-09-29: USB wired in `main.c`, the toolkit's
  bus-address fix, and seeds for the XPP class-driver and report routines
  (`0x003306DF`, `0x0032FC8B`). START is read; the menus navigate.
- ~~**Menu camera.**~~ Done 2026-09-29 (toolkit `2cc2ee3`). It wasn't an
  ordering problem: `lahf` after `ucomiss` was never lifted, so
  `sub_000BD8E0` decided at random whether a node's position was set.
- ~~**Level-load crash.**~~ Done 2026-09-29 (toolkit `4d01c4d`,
  `94b15ac`). A depth-only pass painted physical page 0, where XAPI's
  USB driver keeps its structures.
- ~~**In-game rendering: black terrain.**~~ Done 2026-09-29 (toolkit
  `662ddaf`): register combiners and texture stages 0–3. `0x001C8C20`
  seeded.
- **In-game rendering (next):**
  - the rider draws black: check its combiner inputs, likely lighting
    in V0/V1 or a stage mode that isn't modelled;
  - fog (the FOG register is taken as factor 1);
  - shadows (the depth-only pass as a texture: shadow compare);
  - fixed-function mode `0x4` batches (the shadow pass);
  - speed.
- ~~**Depth, Gouraud, perspective, alpha test in the executor.**~~ Done
  2026-09-29 (toolkit `95eb12b`). Fixed-function T&L (mode `0x4`) and
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
- [x] All top-level menus open and close with a pad
      (2026-10-02: the user plays career, challenges and events from the menus)
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

- [x] One level (the first career level) loads and renders (ML1, 2026-09-29)
      (2026-09-29: ML1 loads, runs and renders on the GPU at about 46 fps;
      no fog or shadows yet)
- [x] The rider can be controlled, tricks register, the score works
      (2026-10-02: user play, styled tricks score extra points)
- [x] The run can be finished and exited back to the menu
      (2026-10-02: competitions won, challenges completed, menu and back)

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
- Record known issues in the README (player status table).

**M4 exit criteria (the gate for Part B)**

- [x] Every level and mode can be played start to finish
      (2026-10-03, by the user's call: every mode reached plays; a full
      career run to the end is still a follow-up)
- [x] Audio, music and FMV work
      (2026-10-02: audio and music work in play after the dispatch lock,
      toolkit `1ed18f9`. The boot movies play with sound, `c260dd4`.
      Still to confirm: in-game movies, and long play without the
      dead-voice slowdown, `c79483a`)
- [x] Saves persist across restarts
      (2026-10-02: career progress, level 4+ unlocks kept across many sessions)
- [x] 60 minutes of play with no crash (`soak7`, 2026-10-01: ML1 at 2x with scripted pause/resume, 59.2 fps, memory flat at ~500 MB)
- [x] The build reproduces from a clean checkout plus the user's own disc
      (2026-10-07: fresh clones of amped2 and xboxrecomp, the USA disc
      unpacked with xdvdfs, `regen.ps1`, configure, build, boot to the
      title. It first failed to link: `src/lua_probe.c` called a
      Ghidra-only name, which a checkout without the cached Ghidra export
      does not have; fixed by pinning the sub_ name. The menu mods are a
      separate, optional step, `py -3.10 tools/mods/menus.py`)

---

## Part B: Mods (only after M4)

### Phase 6: Mod framework (M5)

The base every later mod builds on. None of the later phases should need to
touch generated code directly.

- **More memory (user request, 2026-10-01).** The guest has the retail
  layout: 64 MB of low RAM (heap about 48 MB) plus a separate 64 MB
  contiguous window. Mods with bigger textures and new content will want
  more. The model to copy is the debug kit's 128 MB, which emulators such
  as xemu also offer (xboxdevwiki "Memory"), or 256/512 MB for CPU-only
  data placed above the hardware-visible range. Constraint: the GPU and APU
  get physical addresses from `MmGetPhysicalAddress`/the contiguous
  allocator, so anything they read must stay in the RAM range they map;
  `g_xbox_phys_lowram`, `guest_ok` in the D3D11 backend and
  `xbox_ContiguousAllocatedBytes` all assume 64 MB today. Not needed for
  M4: the level-2 out-of-memory was a leak (`fbf31f2`).
  **Done (2026-10-08), opt-in:** ini `[Game] Memory=128` (toolkit
  `RECOMP_GUEST_RAM_MB=128`, `db4b7bd`) gives a debug kit's layout: heap
  48 → 112 MB, contiguous window 64 → 128 MB. The game sizes its graphics
  pool by probing from 60 MB down in 8 KB steps (`0x0013A181`); at 64 MB it
  settles at ~48 MB after 1571 failed tries, at 128 MB it gets the full
  60 MB first time. More than 60 MB would need the pool code reversed.
  Verified in ML1 at 60.1 fps, and with `RECOMP_TEST_HIGH_MEM=1` (every
  guest allocation above 64 MB). That test found the fixed DSP-ack address
  (`0x8106C810`) moving with the allocation order; a hook on the mailbox
  (`sub_00292F33`) now registers it at runtime.
- **Virtual file system overlay. Done (archive level):** the path layer
  reads `mods\build\game\` over `game\` (toolkit `RECOMP_OVERLAY_DIR`,
  ini `Mods`), and recipes in `tools/mods/` rebuild whole archives from
  `mods/overrides/` with the asset toolkit's `repack`. ~~Still open: loose
  entries served without a repack.~~ **Done (2026-10-08):**
  `mods\loose\<archive>\<entry>` (and a pack's `loose\`) are merged at
  start-up into `mods\cache\loose\<archive>` over the archive the game would
  read, first in the overlay order, cached until a source changes
  (`src/mod_loose.c`). Verified with a loose `StringTable.dat` in `Base.rui`
  (main menu showed the new label), the cache reused, and removed when the
  loose folder went away.
- **Mod loader and config.** A `mods/mods.json` (or TOML) with enabled
  packs, load order and per-mod settings; a user-facing `amped2.ini`
  for graphics and input options. **`amped2.ini` done** (display, input,
  audio, game, advanced; Game Options writes back to it); `mods.json`
  with several packs and a load order is still open.
  **`mods.json` done (2026-10-07):** `{ "packs": ["a", "b"] }`, first
  wins; each pack is `mods\packs\<name>\` with `game\` (file
  overrides) and `textures\` (DDS), ahead of the tools' default
  folders. The toolkit takes `;`-separated lists in `RECOMP_OVERLAY_DIR`
  and `RECOMP_TEXTURE_PACK`.
- **Hook points. Done:** in `recomp_manual.c`, define `sub_X` and declare
  `extern void sub_X_gen(void);` to wrap a guest function. The recompiler
  then emits the original as `sub_X_gen`, so code runs before and after
  it (examples: the QuitGame registration, both Game Options wrappers,
  XInput). Add the address to `recomp_lookup_manual` when the function is
  reached through an indirect call. A function another file calls by name
  must be mentioned in `recomp_manual.c`, or the naming pass may rename it
  (see the clean-checkout fix, 2026-10-07).
- **Lua script overrides. Done for GUI scenes:** the game's Lua loads
  plain source as readily as bytecode, so decompiled and edited scenes go
  back through the overlay as source (the menu mod). **Gameplay scripts
  done (2026-10-08):** a decompiled `GameInfo.res` `TrickInfo.lua` as a
  loose entry is compiled from source (a marker error at its line 580 was
  reported from `D:\GameInfo\TrickInfo.lua`), and an edited one (flip base
  score 2500 → 25000) runs into ML1 with no Lua errors. The game caches
  `gameinfo.res` on its cache partition and re-copies it when it changes.
  The script Lua has no `error`. Not shown in game yet: the effect of a
  changed value (the scripted test run does no tricks).
- **Menu changes (user request, 2026-10-03)**, the first users of the
  overlay, script overrides and hook points:
  1. Hide "Multiplayer" from the main menu (`Shell.rui`
     `Scenes/Main.scene`: the `Items`/`TextIDs`/`HelpTextIDs` lists).
  2. A "Close game" item at the end of the main menu: a new action name
     caught by a native hook on the game's GUI action dispatcher.
  3. "Options" → "Game Options" (`Base.rui` `Scenes/Options_Game.scene`)
     gains the non-advanced `amped2.ini` settings, read from and written
     back to the ini, applied live where possible. **Done (2026-10-07)
     for WINDOW (live) and RESOLUTION (after a restart).** The screen has
     six visible rows; a seventh scrolls the list, and the value boxes
     stay bound to their slots, so further settings need a second page or
     a fix to the list's combo binding. Volume and rumble already have the
     game's own Audio and Vibration options; dead zone, movies and the
     picture format stay ini-only for now.
  1-2 done (2026-10-03); the QUIT item has its own label "QUIT GAME"
  since the string table was decoded (2026-10-07).
  4. **(user request, 2026-10-08)** "Options" renamed "Options and Mods";
     its CREDITS and XBOX LIVE OPTIONS items hidden; a MODS item added,
     the Xbox Live options screen reused with MOD PACKS and TEXTURE PACK
     rows (`[Game] ModPacks`, `TexturePack`). The mouse cursor hides over
     the game window until the mouse moves (toolkit `fb_present.c`).
  Scenes are compiled Lua 5.0 beta tables; the exe carries Lua's text
  parser, so replacements can likely be source. Strings: `Base.rui`
  `StringTables/<lang>/StringTable.dat`.
- **A debug overlay** (Dear ImGui): FPS, the loaded mods, texture-pack hit
  and miss counts, and a free camera. **Done without ImGui (2026-10-07):**
  F3 (or `RECOMP_GPU_HUD=1`) shows fps, the game's size and scale, FXAA
  and anisotropic flags, texture-pack hits and misses, and the active file
  overlays, drawn with GDI text over the presented frame. ImGui would be a
  third-party download, and the free camera needs game-side camera hooks;
  both are still open.

### Phase 7: Graphics upscaling (M6)

In order: the cheapest win first, and the ones that affect gameplay last.

1. **Internal resolution scaling. Done** (toolkit `RECOMP_GPU_SCALE`, ini
   `RenderScale` 1-8, in-game Game Options RESOLUTION 1x-4x): 3x of the
   720p mode is 3840x2160 at ~58 fps in ML1.
2. **Widescreen 16:9. Done (2026-10-07).** The game has its own 1280x720
   widescreen mode, with the HUD at the edges and the menus laid out for
   it. It was hidden because the toolkit reported the video flags in the
   wrong bits; `RECOMP_VIDEO_MODES` (default `480p,720p,widescreen`) turns
   it on. Verified in ML1 at 3840x2160 (RenderScale 3), 58.6 fps. Wider
   formats (21:9) are not wanted (user, 2026-10-07).
3. **AI-upscaled texture pack.** **Runtime hook done (2026-10-07):**
   toolkit `RECOMP_TEXTURE_PACK` loads `mods\texture_pack\<key>.dds`
   (any size, BC1-3/BC7/32-bit, own mips) in place of the original; the
   key the runtime computes matched the asset toolkit's for 32 of the 33
   textures up to the main menu (the other is built at run time), and a
   2048x2048 recoloured jacket showed up in game. `RECOMP_TEXTURE_PACK_MISSES`
   lists keys the pack lacks. **Pack built (2026-10-07):** 3376 textures
   (ultrasharp-4x, lightmaps/tiny ones Lanczos), BC7, 4.8 GB in
   `mods/texture_pack`, about an hour on the RTX 2070. In ML1: 229
   replaced, 22 not covered, 59.2 fps, no visible artifacts. **Misses
   resolved (2026-10-08):** they were not missing textures. The game draws
   menu and loading-screen textures after freeing them, when the pool's
   free-list header has replaced the first 16 bytes (a pointer, so a new
   key each run). The runtime now matches DXT textures by the rest of the
   top mip (toolkit `bd652ed`, `tails.txt` from `tex-pack`); the loading
   screen shows its upscaled art for the first time. Left: four fonts (by
   design), a 1x1 fill, one 0x3C texture, and a few textures drawn after
   their memory was reused. `RECOMP_TEXTURE_PACK_DUMP` + `tex-misses` add
   genuine run-time textures to a pack. Open: hand edits; a faint seam
   between the title screen's background tiles (also without the pack).
   Original plan: add the runtime hook the asset toolkit
   already targets: on texture create, key =
   `crc32(top mip)_WxH_fmt`, and load `mods/texture_pack/<key>.dds` (BC7,
   full mips) into host VRAM only. Pipeline: `tex-export` → `tex-upscale`
   (Upscayl, `ultrasharp-4x`) → hand edits in `mods/textures/edit/` →
   `tex-pack`. Needs a hit and miss report, plus a dump of missed keys to
   catch textures created at runtime.
4. **Anti-aliasing and filtering:** MSAA or SMAA and 16× anisotropic
   filtering. **Anisotropic done (2026-10-07):** `RECOMP_GPU_ANISO`, 16 by
   default (ini `Anisotropic`), on mipmapped, linearly filtered textures
   only; 58.3 fps with and without it in ML1. **FXAA done (2026-10-07):**
   `RECOMP_GPU_FXAA`, off by default (ini `FXAA=1`), in the final blit;
   `RenderScale` 2 and up already supersample. MSAA/SMAA not pursued:
   every render target would need multisampled copies and resolves.
5. **Optional extras:** higher-precision shadows, a higher LOD distance,
   60 fps or an uncapped framerate. Needs the game timestep to be
   separated from the frame rate first, so it goes last and needs its own
   physics check.

**Exit criteria:** 4K 16:9 with the full texture pack and no visual
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
  - [x] 2026-10-25: RE-Amped2 is MIT (`LICENSE`). `NOTICE.md` covers the
        disclaimer, the Game Content Usage Rules notice for the art and the
        third-party list. The xdvdfs and unluac licence texts are in
        `licenses/`, and every install writes them, the toolkit's licences
        and its LGPL text to `licenses\`. The installer's footer links them.
        texconv and the Upscayl models aren't shipped.
  - [x] 2026-10-25: the installer installs no build tool without consent.
        `ConsentDialog` lists each tool with its licence terms, and only the
        approved ones are installed.
  - [x] Wordmark (2026-10-25, user): a new design inspired by the original
        logo, with a similar but redrawn font, different colours and added
        effects. It is not the game's logo, which the Game Content Usage
        Rules forbid in a fan item's logo. Keep it that way: redraw rather
        than trace or cut letters from the original.
  - [x] 2026-10-25: Patreon removed everywhere (the user disabled it, to
        leave no grey area). Feedback goes to GitHub Issues
        (`Links.Issues`), and new versions to Releases.
- **RE-Amped2 branding** (docs/DEVELOPING.md "Branding"). In the pack: title logo
  `ampedLogo`, the 4 boot splashes, `Logo_Amped2`, course banner
  `Banneramped2`, `RegisteredTradeMark` (blanked), the level loading screen
  (splash art, controller pictures and labels blanked, "LOADING ..."
  stays), and the six font atlases. Masters in `branding/drafts/`, built by
  `tools/branding/build.py`.
  - [x] Final wordmark: the user's reconstruction of the R and E, made
        transparent by `tools/branding/unblack.py` (2026-10-08).
  - [x] Icon: `branding/RE-Amped2.ico` for the installer, the shortcut and
        `RE-Amped2.exe` (resource + window class icon, toolkit) (2026-10-08).
  - [x] Level loading screen with the splash art and "LOADING ..."
        (2026-10-08, `brand8`).
  - [x] Sharp text: the font atlases AI-upscaled, alpha included
        (2026-10-08, `brand7`).
  - [x] Text at its own proportions in the 16:9 mode (2026-10-08,
        `text1`): wrapper of Font2dStandardShader::Begin `0x00248FF0`
        narrows stretched text 0.75x about its alignment point (ini
        `TextAspect`). Images (menu titles, icons) stay stretched; that
        would need per-scene AspectCorrect anchors.
  - [ ] Check `Logo_Amped2` and the course banner in game (user; backlog).
  - [x] Boot splash for players (2026-10-08, `ea1`): without the big
        local pack, `main.c` loads packs in place, so the splash shows.
        With `mods\texture_pack` it still needs
        `RECOMP_TEXTURE_PACK_SYNC=1` (fine for now, user).
  - [x] Early-access installer 0.1.0: the art in the header, the "RE-Amped2
        look" option installs `branding/pack` as `mods\packs\re-amped2`
        (2026-10-08).
  - [ ] Sharp fonts for players: the pack can't carry them (upscaled from
        the game's own). Generate them on the player's PC instead, e.g.
        at install time with a run-time dump (`RECOMP_TEXTURE_PACK_DUMP`)
        and a non-AI upscale.
  - [ ] Intro video `Movies\Intro.xmv`: a sharper re-encode with the new
        logo (user's TODO).
  - [ ] Optional: simpler 16 and 32 px icon frames (the badge is busy
        there).

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
| **UWP: Windows Store, and Xbox One/Series in Dev Mode** | Still Windows and D3D11, so the renderer and audio carry over. Swap GDI for CoreWindow and a swap chain (Phase 7 needs one anyway), file mappings for `CreateFileMappingFromApp`/`MapViewOfFile3FromApp`, and XInput for `Windows.Gaming.Input`. Game data goes in app-local storage. Check that fixed-address mapping and a vectored exception handler are allowed inside the app container. On Xbox Dev Mode, a "Game" app gets enough memory (the game needs ~64 MB guest plus the host). | **Medium.** The most realistic port. Planned as **Phase 13**. |
| **PlayStation 5 (homebrew)** | Same x86-64 CPU (Zen 2), so the generated C compiles unchanged, but everything around it is new: a POSIX (FreeBSD) runtime, a GPU backend with no D3D or Vulkan to lean on, and Sony's audio, pad and file APIs, all through the community homebrew toolchain on exploitable firmware only. | **High**, mostly the renderer, with legal attention on top. Planned as **Phase 14**, after Phases 12 and 13. |
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

### Phase 12: Portable runtime (groundwork for the consoles)

Both consoles have x86-64 Zen 2 CPUs, so **the generated C compiles as it
is** on either, and needs no JIT, which neither console allows homebrew to
use freely. What ties the game to Windows is the toolkit runtime. This phase
puts interfaces between the runtime and the OS, with today's Win32 code as
the first implementation. It is toolkit work, so do it in xboxrecomp,
written to go upstream. Open it as a proposal with the toolkit's maintainer
first: upstream may already be partway there (`src/platform/win32_compat.*`,
`Dockerfile.gcc`).

1. **Platform interface** (`src/platform/`): guest memory (reserve and map
   at fixed host addresses, and the contiguous window), threads, events and
   TLS, file I/O, timers, and fault handling. The Win32 version is the code
   as it is now.
2. **Device registers without page faults.** The lifter emits calls for
   accesses to the device register ranges (NV2A, APU, OHCI, AC'97) instead
   of letting them fault. That retires the decoder for faulting x86-64 host
   instructions, the least portable piece, and works where a fault handler
   is restricted. Keep the fault path as a fallback while it settles.
3. **Renderer split.** Divide `nv2a_d3d11.c` into a front end (NV2A state
   to abstract draws and state) and a back end. D3D11 is the first back
   end. Later ones: D3D12 (if the Xbox caps D3D11), Vulkan (Linux, Steam
   Deck), and the PS5's native interface.
4. **Shaders.** The HLSL generator gets a back-end hook, and the shader
   cache can be filled ahead of time for platforms that have no run-time
   compiler (the PS5).
5. **Audio sink and input interfaces**: XAudio2 and XInput today;
   Windows.Gaming.Input, and the PS5's audio out and pad, later.
6. **Portability check of the generated code** with clang and GCC (no MSVC
   intrinsics or `__declspec` that the other compilers lack).

**Exit criteria:** the Windows build runs entirely through the interfaces
with no regression: ML1 at 60 fps, sound, pad and saves, and a 60-minute
soak with no crash.

### Phase 13: Xbox Series X|S (Dev Mode)

**Route.** Dev Mode is Microsoft's own route for running your own apps on a
retail console: a Partner Center developer account (one-time fee), the Dev
Mode Activation app, then sideloading through Device Portal. Nothing goes
to the Store. As on Windows, **the player builds their own package** from
their own disc, and nothing from the game is downloaded.

**Effort:** medium, about 3–6 weeks of focused work. It's the same Windows
and D3D11 stack, and most of it can be developed and tested as a UWP app on
a PC.

1. **Spike (go/no-go, 1–2 days).** A minimal UWP "Game" app on the console
   that:
   - maps the guest memory layout with `MapViewOfFile3FromApp`, at fixed
     addresses if allowed, through the offset otherwise;
   - installs a vectored exception handler and catches a guarded-page
     access;
   - creates a D3D11 device and reports its feature level (the backend asks
     for 11_0+);
   - plays an XAudio2 tone and reads a pad through Windows.Gaming.Input.

   One answer per item. Each "no" points to Phase 12 (fault-free device
   registers, D3D12 or D3D11On12).
2. **App shell.** CoreApplication entry and a swap chain for the
   CoreWindow. Suspend and resume: pause audio and rendering, and survive
   constrained mode. Title-safe area and 4K output.
3. **Platform layer for UWP.** File access under the package and
   `LocalState` (`CreateFile2FromApp`). No registry, GDI, console or
   process launch. `amped2.ini`, `amped2.log`, the saves and the shader
   cache live in `LocalState`.
4. **Graphics.** D3D11 as it is if the feature level allows, otherwise
   D3D11On12 or a D3D12 back end (Phase 12.3). `D3DCompile` at run time
   (ship `d3dcompiler_47.dll` in the package), with the shader cache kept
   on disk.
5. **Input and audio.** Windows.Gaming.Input feeds the emulated USB pads.
   Up to four pads are natural here, which opens up split-screen (Phase 10).
   Rumble works through the same API. XAudio2 stays.
6. **Game data.** Decide in the spike between packing the player's
   extracted `game/` into their own package (simple; it's their copy and
   never shared) and copying it to `LocalState` or a USB drive after
   install.
7. **Packaging.** A UWP build of the CMake project (`WindowsStore`), an
   `AppxManifest`, and an `.msix` signed with a certificate generated on
   the player's PC. The installer gets an "Xbox package" option, plus
   step-by-step instructions for Dev Mode and Device Portal, including
   setting the app type to Game.
8. **Tuning.** Default `RenderScale` per console (Series S at 1080p,
   Series X at 4K) and a check of the memory headroom.

**Exit criteria:** boot to the menus. ML1 at 60 fps, at 1080p on Series S
and 4K on Series X. Sound, pad and rumble work. Saves persist across app
restarts and suspends. A 60-minute soak with no crash. A package built by
the installer installs by following the written instructions.

### Phase 14: PlayStation 5 (homebrew)

**Status:** exploratory. Start only after Phase 12 is done and Phase 13
has shipped.

**Ground rules, written down before any code:**
- Use only the open community homebrew toolchain. Never use Sony's SDK,
  leaked SDK files, keys or Sony code.
- Put no exploit or jailbreak code in this project. Players use whatever
  their console's homebrew scene provides; RE-Amped2 only offers a
  homebrew build.
- Keep it a separate build target with its own notice, not in the default
  installer. Consider a separate repository.
- The distribution rule is unchanged: the player builds it on their own PC,
  by cross-compiling, from their own disc. Nothing from the game ships.

**Steps:**
1. **Research spike (go/no-go)**, written up in `docs/ps5.md`:
   - which firmware versions homebrew covers, and how homebrew runs (ELF
     payload loader or package);
   - which system libraries a homebrew app can use: video out, audio out,
     pad, files on internal or USB storage;
   - fixed-address memory mapping, signal handling and threads;
   - **graphics**: can homebrew drive the GPU, and how do shaders get built?
     This answer decides the phase.
2. **POSIX platform layer** (from Phase 12). Prove it on Linux and FreeBSD
   on a PC first, with `mmap`, pthreads, a SIGSEGV/SIGBUS handler (or the
   fault-free device registers) and `clock_gettime`. As a side effect, this
   gives a Linux and Steam Deck build (with a Vulkan back end).
3. **Cross-compile.** clang with the homebrew sysroot must build all ~78 MB
   of generated C plus the runtime (Phase 12.6).
4. **Bring-up on the software rasteriser.** The old software executor
   needs no GPU API, so it can prove boot, audio, input and saves on the
   console, even at low frame rates.
5. **GPU back end.** The big item: native command buffers through
   whatever interface homebrew can reach, and shaders compiled ahead of
   time for RDNA 2 (for example through LLVM's AMDGPU back end or Mesa's
   ACO), packed in the format the system expects. Expect months.
6. **Audio, pad, files and saves** through the system libraries.
7. **Packaging.** Whatever format the homebrew loaders take. The installer
   would need LLVM and the sysroot on the player's PC to cross-compile.

**Milestones:** P1, boot to the title screen with software rendering. P2,
the menus at full speed on the GPU back end. P3, ML1 playable at 60 fps.

**Effort:** high, months, with the renderer the bulk of it. The audience
is limited to players on exploitable firmware.

---

## Part D: Next phases (from 2026-10-26)

Written while the user tests a full career to the end and the Legend
challenges (the last two 🟡 gameplay rows in the README). These hours of
manual play need the game, its files and `game/UDATA` to themselves.
So the order puts first what makes those runs produce data and what keeps
test runs off the player's copy. Then come the work that needs a safety
net, the toolkit sync, and the player-facing polish for v0.3.0.

| # | Phase | Why now | Runs the game? |
|---|---|---|---|
| 15 | Test isolation and coverage telemetry ✅ (2026-10-28, one check left) | Makes the user's runs useful; unblocks the rest | Short checks only |
| 17 | Toolkit upstream sync (v0.16.0), **in progress** (merged on a branch; a kernel race left) | `amped2-fixes` is 101 ahead and 333 behind upstream: five releases | Yes, isolated runs |
| 16 | Automated regression suite | The safety net for 18 | Yes, in an isolated copy |
| 18 | v0.3.0 "out of the box" | Closes the README rows players see | Partly |
| 19 | Split-screen multiplayer (optional) | The last hidden game mode | Yes, with 2+ pads |
| 20 | Content tooling (Phase 8 prerequisites) | Offline format work | No |

- **Standing lane:** bugs from the user's testing come before any phase.
  For each one: reproduce it, fix it, add a suite case, and ship the fix in
  the next 0.2.x.
- Phase 20 never starts the game, so it can run while the user plays.
- **Order changed (user, 2026-10-28):** the toolkit sync (17) comes before
  the suite (16), since it is five releases behind. Its check is Phase 15's
  coverage list and isolated runs: one baseline before the sync, the same
  runs after it.
- Phases 12–14 (platforms) come after Phase 17, because upstream's POSIX
  work (e.g. the POSIX file backend) changes their starting point.

### Phase 15: Test isolation and coverage telemetry

The user's play sessions double as coverage runs, and test runs never
collide with them.

1. **Save redirect.** A switch in the toolkit's path layer (e.g.
   `RECOMP_UDATA_DIR`, ini `[Advanced]`) gives a run its own UDATA and TDATA
   folders. `diag.ps1 -FreshSave` uses it instead of moving the player's
   profile aside. The move-and-restore logic stays as a fallback.
2. **Isolated test install.** `tools/testenv.ps1` builds `test/` with a
   hard-linked `game/`, its own UDATA, cache partition and `amped2.ini`. Runs
   from there avoid the sharing violation. They still share the GPU and CPU,
   so the rule stays: no runs while the user plays, unless they ask.
3. **Coverage counters, off the hot path.** Keep three sets of unique
   addresses:
   - unresolved indirect-call targets;
   - `RECOMP_UNIMPL` hits;
   - lifter `_flags` fallbacks reached.

   They go to `amped2.log` at exit and every few minutes. They are on by
   default: the cost is one set insert per new address. This also feeds the
   Phase 2 exit criterion "no unresolved indirect calls" and the Phase 4
   `RECOMP_UNIMPL` audit.
4. **Crash report.** The unhandled-exception path writes a minidump plus
   the guest call chain (RIP → PDB → `loc_` label, as `sample_threads.py`
   does) to `crash\<time>\`. The bug-report form gets a "crash folder"
   field.
5. **Version line.** The build writes its commit pair (as `installer\build.ps1`
   computes it) to the log and the F3 overlay.

**Done (2026-10-28)**, as described in docs/DEVELOPING.md "Testing". It
differs from the steps above in these ways:
- The switches are the toolkit's `RECOMP_HDD_DIR` (E:, which holds UDATA
  and TDATA) and `RECOMP_SAVE_DIR` (storage: partition images and the cache
  partitions). Toolkit `52838f8`.
- Nothing of the player's is moved any more, so the move-and-restore
  fallback is gone.
- No hard-linked `game/`: hard links share Windows' sharing checks, so they
  would not have helped. The conflicts were elsewhere:
  - the storage both runs shared, `%LOCALAPPDATA%\xboxrecomp`;
  - disc files opened with no sharing, `shaders\shaders.res` even for
    writing.

  Disc files are now opened read-only and shared for reading.
- Coverage covers five kinds, not three:
  - unresolved stubs and `_flags` fallbacks, as generated markers
    (`RECOMP_REACHED`, toolkit `f461003`);
  - unimpl, icall-unresolved and icall-not-code.

  They are kept across sessions in `amped2-coverage.txt`.
- The crash test switch is `AMPED2_TEST_CRASH=1`.

**Exit criteria**

- [x] A `-FreshSave` run leaves `game/UDATA` byte-identical (hashed before
      and after) (2026-10-28: 239 files unchanged across 7 isolated runs. The
      check covered the dev tree's and the installed game's UDATA/TDATA, both
      ini files and `%LOCALAPPDATA%\xboxrecomp`)
- [x] A run from `test/` works while `game/` is open in another process
      (2026-10-28: two isolated instances reached ML1 at the same time, with
      no sharing violation. A run started next to another instance gets its
      own storage)
- [ ] One user play session yields a log with the coverage sets and the
      version line (needs a play session on this build; the installed
      0.2.0 predates it)
- [x] A forced crash (e.g. `RECOMP_TEST_CRASH=1`) leaves a minidump that
      opens in Visual Studio with symbols, plus a guest call chain
      (2026-10-28: `AMPED2_TEST_CRASH=1` writes `crash\<date-time>\`. Its
      `crash.txt` names `WinMain+0x954` through the PDB. The dump's module
      record matches the exe's PDB GUID and age, so a debugger loads the
      symbols. Not yet opened in Visual Studio itself)
- [x] docs/DEVELOPING.md has a "Testing" section

### Phase 16: Automated regression suite

One command that says "nothing regressed". It reuses `RECOMP_PAD_SCRIPT`,
`RECOMP_GPU_SHOT`, `[HEALTH]` and `RECOMP_PACE_TRACE`.

1. `tools/suite.ps1` runs named cases in `test/`. A case is a pad script, a
   time limit and pass checks read from the log.
2. Cases:
   - **boot:** title to main menu;
   - **ml1:** a career save into ML1 for 120 s, at ≥ 58 fps, with no
     resync storm;
   - **reload3:** three Leave Mountain/reload cycles;
   - **level2:** a second mountain, from a fixture save;
   - **movie:** the intro plays through to the title;
   - **mods:** a loose `StringTable.dat` entry shows its label;
   - **texpack:** hits > 0, with misses under a threshold;
   - **soak:** 60 min in ML1, for `soak7`'s numbers.
3. **Fixture saves.** Copies of the user's progressed profiles, taken only
   with their OK, kept in the git-ignored `test/fixtures/`. Later levels
   then load without a full career.
4. **Screenshot checks.** `RECOMP_GPU_SHOT` frames at fixed times are
   compared with git-ignored goldens (perceptual diff with a tolerance).
5. **Health checks.**
   - "idle voices linked" stays at 0;
   - memory stays flat (±5% over the run);
   - no unresolved-call addresses beyond the Phase 15 baseline.
6. **Report.** A summary table, plus logs and frames in
   `diag/suite-<date>/`.

**Exit criteria**

- [ ] `suite.ps1 -Quick` (boot, ml1) takes ≤ 5 min; the full suite without
      the soak takes ≤ 30 min, unattended
- [ ] Three passes in a row on the current build (no flaky cases)
- [ ] An injected regression (e.g. `RECOMP_GPU_NODEPTH=1`) fails the right
      case
- [ ] The soak case reproduces `soak7` (60 min, no crash, ~59 fps, memory
      flat)

### Phase 17: Toolkit upstream sync (xboxrecomp v0.16.0)

**Status (2026-10-28): merged on the local branch `amped2-sync-v0.16`, not
yet good enough to replace `amped2-fixes`.**
- All 30 conflicting files are resolved. The toolkit builds, and the
  recompiler and disassembler tests pass.
- Three findings so far (details in CHANGELOG):
  1. Upstream's stricter disassembler drops real function starts, such as
     `0x00282C0A`. For now the analysis runs with our tools.
  2. The merged APU leaks XACT's sound heap. The sync keeps our APU, which
     brings the walk back to the baseline's 57 fps.
  3. That tree still had an intermittent race in the merged kernel: of 5
     runs, 1 crashed in XACT and 2 deadlocked in ML1. **Found and fixed
     (sync `f9cb831`)**: device threads wrote their ISR's IRQL into the
     main thread's KPCR, so DirectSound skipped its lock. Since the fix, 6
     parallel runs have had no freeze in ML1 and no bug check. One run
     stalled before ML1, unexplained.

Next:
1. More runs of the fix, to see whether the before-ML1 stall repeats.
2. A play session.
3. Then `amped2-fixes` moves.
4. After that, upstream's APU changes one at a time, then its disassembler
   (seeding the real starts it drops).

1. **Survey** `amped2-fixes..upstream/main` (333 commits on 2026-10-26).
   Group them into lifter/disasm (changes the generated code), kernel/HLE,
   NV2A/APU, and platform/POSIX. Mark the ones that touch the same code as
   our commits.
2. **Rebase or merge** onto upstream on a new local branch
   (`amped2-sync-v0.16`), whichever conflicts less. Where both sides touch
   the same area, keep our behaviour.
3. **Regenerate** with `tools/regen.ps1`. Compare these with the current
   build, and explain every change:
   - the function count;
   - seed resolution;
   - the `_flags` fallback count;
   - the unresolved stubs.
4. **Full rebuild**, then the full Phase 16 suite and the soak.
5. **Upstream candidates.** List our generic toolkit fixes with a note each:
   contiguous free, `lahf` after `ucomiss`, the APU, OHCI, the D3D11 backend,
   texture packs, and so on. Whether and how to offer them upstream is the
   user's call.
6. Move `amped2-fixes` onto the sync branch only once the suite passes.

**Exit criteria**

- [ ] `amped2-fixes` contains `upstream/main` (0 behind) and builds from a
      fresh checkout
- [ ] The full suite and the soak pass
- [ ] The generated-code delta is written up in docs/DEVELOPING.md
- [ ] The list of upstream candidates is written

### Phase 18: v0.3.0, "out of the box"

1. **Fixes from the completion and Legend testing** (the standing lane),
   each with a suite case.
2. **Sharp fonts made on the player's PC** (Phase 9's open item). At the
   end of the install:
   - a headless run dumps the six font atlases (`RECOMP_TEXTURE_PACK_DUMP`);
   - a non-AI upscale (Lanczos with an alpha-preserving sharpen) packs
     them into `mods\packs\fonts`.

   No game pixels ship.
3. **Optional HD textures, built at install time.** An installer option,
   "Build HD textures (about an hour, needs a GPU)", runs `tex-export`, the
   upscale and `tex-pack` on the player's machine. The option asks for
   consent the way the build tools do, with the upscaler's licence in
   `ConsentDialog`. A cancelled build can be resumed.
4. **Menu pictures at 16:9.** Per-scene `AspectCorrect` anchors, or a
   wrapper like the text one at `0x00248FF0`, for menu titles and icons.
5. **Backlog checks:**
   - `Logo_Amped2` and the course banner in game;
   - the seam between the title screen's background tiles.
6. **Release.** Bump to 0.3.0 and build with `installer\build.ps1` from
   clean trees. Test-install on a clean Windows user account and write the
   release notes. The user publishes.

**Exit criteria**

- [ ] Every 🟡 row in the README is ✅, or is listed under known issues
- [ ] A fresh install shows sharp text with the font option. With the HD
      option, ML1 uses the upscaled pack at ≥ 58 fps
- [ ] Menu titles and icons are not stretched at 16:9 (a screenshot of
      each main menu)
- [ ] The suite passes on the release build; `v0.3.0` is tagged locally

### Phase 19: Split-screen multiplayer (optional; Phase 10, item 4)

1. An OHCI root hub with 2–4 ports, and one emulated Duke pad per host
   controller (XInput slots 0–3, with hot-plug).
2. Multiplayer back in the main menu (the menu mod, `Shell.rui`
   `Scenes/Main.scene`).
3. **Check split-screen rendering:**
   - per-viewport state;
   - shadows;
   - frame rate at `RenderScale` 2.
4. A suite case with two scripted pads.

**Exit criteria**

- [ ] 2-player and 4-player sessions run start to finish, each pad
      steering its own rider
- [ ] Split-screen holds 60 fps at 1080p
- [ ] The README's split-screen row is ✅

### Phase 20: Content tooling (Phase 8 prerequisites, offline)

1. Decode the `.pgf` **mesh** block in `tools/assets/`: vertex formats,
   index buffers and material references.
2. Decode `.ani` (skeleton tracks) and the level object placement format.
3. A **round-trip test** for each format: decode, re-encode and
   byte-compare, over every file on the disc.
4. glTF export for viewing, then import for edited meshes.
5. A first M7 proof: a new `NewCareerParts` combination (part and texture
   swap) as a mod-pack recipe in `tools/mods/`.

**Exit criteria**

- [ ] Every `.pgf`, `.ani` and placement file on the disc round-trips
      byte-identical
- [ ] glTF exports of a rider and a level chunk open correctly in Blender
- [ ] A recipe-built custom character shows up in career creation in game

---

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| The Phase 1 wait is a deep runtime gap (interrupt or DPC model) | Blocks everything | Fix it upstream in xboxrecomp and ask on the toolkit's Discord |
| Build times of 20–40 min | Slow iteration | Chunk-level rebuilds, fix the `recomp_0020` stall |
| D3D8LTCG's non-standard shapes | Many rendering bugs | Follow the D3D8LTCG device-context doc and compare frame captures with xemu |
| x87 precision drift in physics | Gameplay differs | Conformance tests against xemu traces |
| The texture hash changes if a texture is modified at runtime | Pack misses | Done: missed keys are dumped (`RECOMP_TEXTURE_PACK_DUMP`), and freed textures are matched past their first block (`tails.txt`) |
| Legal and distribution | Can't share the result | Never ship game data; the user brings their own disc. MIT licence, `NOTICE.md`, the Game Content Usage Rules notice for the art, and nothing paywalled |
| Microsoft changes the Dev Mode policy | The Xbox port (Phase 13) stops working | Keep the Xbox layer thin over Phase 12; the Windows build is unaffected |
| PS5 homebrew: firmware churn, toolchain changes, Sony's attention | Phase 14 breaks or draws a takedown | Exploratory only, separate target, open toolchain only, no exploit code, no Sony code |

## Working agreements

- The detailed log lives in `CHANGELOG.md` (local, git-ignored). This file
  records phases and exit criteria only.
- Contribution rules are in `CONTRIBUTING.md` and `AGENTS.md`. The
  maintainer's own workflow (local commits, publishing) is in the
  untracked `CLAUDE.local.md`.
- Toolkit fixes that aren't specific to Amped 2 go into `../xboxrecomp` on
  a local branch, written as upstreamable patches.
