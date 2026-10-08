# RE-Amped2: working rules for Claude

## Git

- **Commit locally whenever it helps. Never push.** No `git push` in any
  form, no pushing tags, no `gh repo sync`, no PRs. The settings deny these
  as well.
- **No attribution.** Commit messages and any PR text carry no
  `Co-Authored-By`, "Generated with Claude Code" or session-link lines.
- Don't commit anything that `.gitignore` excludes: game data, generated
  code, build output, logs, `CHANGELOG.md`.

## Changelog

- `CHANGELOG.md` is **local-only** (git-ignored) and **detailed**. Update it
  in the same step as every change: code, seeds, overrides, config, toolkit
  patches in `../xboxrecomp`, and diagnostics runs that taught us something.
- Each entry needs a date, a category (`Added`/`Changed`/`Fixed`/`Removed`/
  `Diagnostics`/`Build`/`Toolkit`/`Assets/Mods`/`Docs`/`Config`), what
  changed and why, the files and addresses involved, and the result. Newest
  first, under `[Unreleased]`.

## Plan

- `PLAN.md` is the roadmap. Mod work (Phases 6–9) starts only once
  milestone **M4 "Playable"** is met. Until then, the only mod-related work
  allowed is keeping `tools/assets/` and the texture-pack format
  consistent.
- Tick off exit criteria in `PLAN.md` as they are met, and update the
  "Current status" line.

## Conventions

- Run the pipeline tools from inside `../xboxrecomp`. `tools/regen.ps1`
  wraps pipeline steps 2–5.
- Build: `cmake --build build --config Release --parallel`. A full rebuild
  takes 20–40 min, so rebuild only the chunks that changed.
- Hand-written code in `src/recomp_manual.c` must use `g_eax`/`g_esp`. The
  bare `eax`/`esp` aliases exist only under `RECOMP_GENERATED_CODE`.
- New functions found at runtime go into `config/seed_functions.json`
  through `tools.seed_from_log`.
- Record bring-up findings (addresses, identified functions, overrides) in
  `README.md` under "Bring-up notes".
- `game/`, `mods/` and `src/recomp/gen/` hold copyrighted or generated data.
  Never commit them.
