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

**Current status (2026-09-29, 02:00):** Phase 2, well along. A plain
double-click opens the window, shows the splash, skips the intro movie and
reaches the **title screen** (rendered correctly). **Input works**: the
emulated USB pad, fed by a PC controller or the keyboard (Enter = START), is
read by the title. Pressing START walks the front end to the **career event
select** (`diag/menu_event_select_2026-09-29.png`), and the title starts
loading level ML1. Menu rendering still has artefacts (doubled text, grey
streaks). Details in `CHANGELOG.md`.

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
- **Menu rendering (next): 3D in the executor.** The streaks are fixed
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

- [ ] Legal → splash → title → main menu with no manual steps
      (2026-09-29: splash → title automatic; START reaches the menus;
      rendering artefacts remain)
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
  stutter on the RTX 2070 laptop.
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
