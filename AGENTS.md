# RE-Amped2: rules for AI coding agents

This file is for AI coding agents working on RE-Amped2: Claude Code, Codex,
Copilot, Cursor, Gemini and the like. Contributors who use one should point it
here (Claude Code reads it through `CLAUDE.md`). The same rules apply to
people; `CONTRIBUTING.md` has the rest.

## Never commit game data

RE-Amped2 is public only because it contains none of Amped 2. Keep it that way.

- **Never add, commit or paste** any of these:
  - files from the disc (`game/`, `default.xbe`, archives, textures, audio,
    movies, scripts);
  - code generated from the game (`src/recomp/gen/`);
  - anything extracted, decompiled or converted from the game (`mods/`,
    decompiled Lua, dumped textures, string tables);
  - Microsoft XDK headers, libraries or documentation.
  `.gitignore` covers the usual places. Never force-add past it.
- **Don't paste decompiler output** (Ghidra, IDA, the lifter's C) for game or
  XDK functions into tracked files. Hand-written overrides in
  `src/recomp_manual.c` describe what a function does, by address, and
  reimplement it in your own words.
- **Recipes, not results.** A mod that changes game data is a script in
  `tools/mods/` that edits the player's own copy at install time. Never a
  modified file.
- **Art in `branding/`** may only be the project's own art. Nothing with
  the game's pixels goes into `branding/pack/`.
- **Logs** (`amped2.log`, `install.log`, `stderr*.txt`) stay out of git.
  When you quote one, strip user names and paths.

## Licences

- The project is MIT (`LICENSE`). Only add code you may release under MIT:
  your own, or code under an MIT-compatible licence, credited in `NOTICE.md`.
- **Don't copy from GPL projects** into this repository. That includes the
  other Amped 2 recompilation (GPL-3.0). Read them for ideas and write your own.
- Don't add a dependency that the installer would have to ship without
  adding its licence to `NOTICE.md` and `licenses/`.

## How the project works

- The toolkit is [xboxrecomp](https://github.com/sp00nznet/xboxrecomp) in the
  sibling folder `../xboxrecomp`. Run the pipeline tools from inside it.
  `tools/regen.ps1` wraps pipeline steps 2–5.
- Build: `cmake --build build --config Release --parallel`. A full rebuild
  takes 20–40 minutes, so rebuild only what changed.
- Hand-written code in `src/recomp_manual.c` must use `g_eax`/`g_esp`. The
  bare `eax`/`esp` aliases exist only under `RECOMP_GENERATED_CODE`.
- New functions found at run time go into `config/seed_functions.json`
  through `tools.seed_from_log`. Edit that JSON with Python, not PowerShell
  5.1, which mangles arrays.
- Record bring-up findings (addresses, identified functions, overrides) in
  `README.md` under "Bring-up notes".
- Keep logging on hot paths opt-in. Printing changes the game's timing and
  has caused bugs of its own.
- Players see the port as **RE-Amped2**; "Amped 2" means the original game.
  Internal names stay as they are (`amped2/`, `amped2.ini`, `AMPED2_*`).

## Working style

- Match the surrounding code: naming, comment density, idiom.
- Keep changes focused, one concern per commit. Explain *why* in the
  message.
- Say what you verified and how (built, booted, played which level). Never
  claim a fix works without having run it. The person submitting a pull
  request is responsible for every line in it, including generated ones.
- Don't touch the player's saves (`game/UDATA`) or a running game instance
  in tests.
