# Contributing to RE-Amped2

Thanks for helping. RE-Amped2 is a free fan project, and bug reports,
testing, fixes and documentation all move it forward.

## The one rule: no game data

This repository contains none of Amped 2, and it has to stay that way. Never
submit, attach or paste:

- files from the disc, or anything extracted, converted or decompiled from
  them: textures, audio, movies, scripts, string tables, `default.xbe`;
- code generated from the game (`src/recomp/gen/`), or decompiler output for
  game or XDK functions;
- Microsoft XDK headers, libraries or documentation;
- modified game files. Mods are recipes: scripts in `tools/mods/` that edit
  the player's own copy on their PC.

A pull request that contains any of these is closed, and the content is
removed from the history.

## Reporting a bug

Open an issue with:

- what you did and what happened, and how often;
- `amped2.log` from the install folder. It is rewritten on every start, so
  copy it before starting the game again;
- for install problems, `install.log`;
- your disc (USA or Europe), Windows version, GPU, and whether you use a
  controller or the keyboard.

Remove your user name from paths in logs if you prefer.

## Sending a change

1. Fork, branch, and keep the change focused on one thing.
2. Build it and test it in the game. Say in the pull request what you
   tested: which mode, level or menu, and for how long.
3. Match the surrounding code: naming, comments, idiom. `AGENTS.md`
   describes the project's conventions.
4. Toolkit changes (recompiler, kernel, graphics, audio) belong in
   [xboxrecomp](https://github.com/sp00nznet/xboxrecomp). Changes that help
   every game should go upstream there, too.

## Licensing of contributions

RE-Amped2 is MIT licensed (`LICENSE`). By submitting a contribution, you
agree that it is released under the same licence, and you confirm that you
have the right to do so. No CLA is needed.

Only contribute code that is your own, or that comes under an
MIT-compatible licence; credit it in `NOTICE.md`. Don't copy code from GPL
projects, including the other Amped 2 recompilation. Reading them for ideas
is fine.

## Using AI tools

AI coding assistants are welcome. The person who submits the change is
responsible for it, though:

- **Point your agent at `AGENTS.md`.** Claude Code reads it through
  `CLAUDE.md`. Keep your own agent rules in untracked files
  (`CLAUDE.local.md`, `.claude/settings.local.json`, or your tool's
  equivalent), and don't commit agent configuration that only you use.
- **Review and understand every line** before you submit it. Don't send
  bulk output you haven't read, run and tested.
- **Say so in the pull request** when a significant part was written by
  an AI tool. It helps reviewers know where to look harder.
- **Never let an agent commit game data.** That includes decompiled code,
  extracted assets and logs with personal paths. The one rule above applies
  to whatever your tools produce.
- Don't present AI-generated test results or "verified" claims you didn't
  check yourself.

## Be kind

Treat everyone with respect. Help newcomers, assume good intent, and keep
criticism about the code. Harassment of any kind isn't tolerated.
