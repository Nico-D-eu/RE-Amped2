# RE-Amped2

**Amped 2 for Windows, rebuilt from your own disc.**

RE-Amped2 brings **Amped 2** (Microsoft Game Studios / Indie Built, 2003, for
the original Xbox) to Windows as a native PC game. It isn't an emulator. The
game's own code is translated to C and compiled into a Windows program, on
your PC, from your own disc. It runs at a steady 60 fps, in widescreen, at
up to 4K and beyond, with controller and keyboard support.

> **Early access.** RE-Amped2 is a work in progress. The whole game is
> playable, but expect bugs and rough edges. Reports help a lot; see
> [Reporting problems](#reporting-problems).

**No game files are included or downloaded.** You need your own legally
owned copy of Amped 2.

---

## Status

✅ works · 🟡 partly working, or still being checked · ⬜ planned · ➖ not planned

| | Feature | Status |
|---|---|---|
| **Install** | One installer that builds the game from your USA or European disc image | ✅ |
| | No game files in any download | ✅ |
| **Gameplay** | Career, Free Ride and Tutorials | ✅ |
| | Pro challenges, snowskate runs | ✅ |
| | Saves | ✅ |
| | A full career to the end | 🟡 being checked |
| | Legend challenges (they unlock after the career) | 🟡 not tested yet |
| | Split-screen multiplayer | ⬜ hidden for now |
| | Xbox Live | ➖ the service is gone |
| **Graphics** | DirectX 11 renderer, steady 60 fps | ✅ |
| | Higher resolutions: up to 8× (4K and beyond) | ✅ |
| | Anisotropic filtering, optional FXAA | ✅ |
| | Widescreen 16:9, with text at its own proportions | ✅ (menu pictures are still stretched 🟡) |
| | Rider shadows | ✅ |
| | Texture packs (replacement textures) | ✅ |
| | HD texture pack and sharper fonts out of the box | ⬜ planned |
| **Sound and video** | Sound effects, the soundtrack, rumble | ✅ |
| | Intro and in-game movies | ✅ (at their original resolution) |
| | Sharper movies | ⬜ planned |
| **Controls** | Xbox-style controllers | ✅ |
| | Keyboard: two layouts, fully remappable | ✅ |
| **Comfort** | Window or borderless full screen (F11), window size and resolution in the menus, Quit Game in the main menu | ✅ |
| **Mods** | Mod packs, single-file replacements, script mods | ✅ |
| | New characters and remixed levels | ⬜ planned |
| **Platforms** | Windows 10 and 11 (64-bit) | ✅ |
| | Xbox Series X\|S (Dev Mode) | ⬜ planned |
| | Linux and Steam Deck | ⬜ planned |
| | PlayStation 5 (homebrew) | ⬜ being explored |

The roadmap, including the console plans, is in [PLAN.md](PLAN.md).

---

## Getting started

### What you need

- **Windows 10 or 11, 64-bit**, and a graphics card with DirectX 11.
- **Your own Amped 2 disc image** (`.iso` or `.xiso`), made from your own
  disc. The USA and the European/Australian releases both work.
- **About 6 GB of free space** for the game. If the free build tools are
  missing (see below), they need up to 7 GB more on drive C:.
- **An internet connection** during the install, for the build tools.

### Install

1. Download **`RE-Amped2-Setup.exe`** from the
   [Releases page](../../releases) (the newest release is at the top).
2. Run it. The installer isn't code-signed yet, so Windows may show a
   SmartScreen warning ("Windows protected your PC"). If you want to check
   the file first, compare its SHA-256 with the one on the release page.
   Then choose **More info → Run anyway**.
3. **Disc:** pick your disc image, or drag it onto the window.
4. **Location:** choose a folder you own (for example `C:\Games\RE-Amped2`)
   and the options: a desktop shortcut, the RE-Amped2 menus, and the
   RE-Amped2 look.
5. **Build tools:** the game is compiled on your PC, which takes Microsoft's
   free C++ Build Tools and Python (plus Java, only for the RE-Amped2 menus).
   If any are missing, the installer lists each one with its licence terms
   and **installs nothing unless you agree**.
6. **Wait.** Installing takes about 10 to 35 minutes, depending on your PC
   and on which tools it has to fetch. Most of it is compiling.
7. **Play** with the desktop shortcut or `RE-Amped2.exe` in the install
   folder.

**Updating:** run a newer installer and pick the same folder. Your saves and
settings are kept.

**Uninstalling:** back up your saves (`game\UDATA` in the install folder),
then delete the folder. The build tools are normal programs you can remove in
Settings › Apps if you don't need them.

---

## Playing

**Controller:** an Xbox-style controller works out of the box, with rumble.

**Keyboard** (`KeyboardPreset` in `amped2.ini`; a controller works alongside
either):

| Action | `default` | `wasd` |
|---|---|---|
| Steer (left stick) | number pad | W A S D |
| D-pad | arrow keys | number pad |
| A / B / X / Y | Z / X / A / S | Space / J / K / L |
| White / Black | Q / E | U / O |
| Left / right trigger | 1 / 3 | Q / E |
| Right stick | I J K L | arrow keys |
| Start | Enter | Enter or Esc |
| Back | Backspace | Backspace or Tab |

**Keys:** **F11** or **Alt+Enter** switches between a window and full
screen. **F3** shows the frame rate and the active mods.

**Saves** are in `game\UDATA` in the install folder.

### Settings

With the RE-Amped2 menus, **Options and Mods › Game Options** has *Window*
and *Resolution*, and **Options and Mods › Mods** turns mod packs and texture
packs on or off.

Every setting is in **`amped2.ini`**, next to `RE-Amped2.exe`. The game
writes it the first time it starts, with each line commented out. Remove the
`;` in front of a line to use it, then restart.

| Section | Setting | Values |
|---|---|---|
| `[Display]` | `WindowSize` | `1280x960`, `1920x1080`, … |
| | `WindowMode` | `windowed` or `borderless` |
| | `RenderScale` | `1` to `8`, or `720p`, `1080p`, `1440p`, `4k` |
| | `VideoModes` | which of `480p`, `720p`, `1080i`, `widescreen` the game may use, or `none` |
| | `Anisotropic` | `1` (off) to `16` (default) |
| | `FXAA` | `1` on, `0` off (default) |
| | `TextAspect` | `1` (default) draws text at its own proportions in 16:9 |
| `[Input]` | `KeyboardPreset` | `default` or `wasd` |
| | `KeyMap` | your own key bindings, e.g. `A=SPACE\|Z,START=RETURN` |
| | `DeadZone` | `0` to `0.9` |
| | `Rumble` | `1` or `0` |
| `[Audio]` | `Volume` | `0` to `100` |
| `[Game]` | `PlayMovies` | `1` (default), `0` skips the intro movies |
| | `Mods` | `1` (default), `0` plays the original game data |
| | `ModPacks`, `TexturePack` | `1` (default) or `0` |

### Mods and texture packs

Mods live in the install folder's `mods` folder and never touch your game
files. `mods\mods.json` lists the packs to use, and each pack is a folder in
`mods\packs\`. The RE-Amped2 look (logo, splash and loading screen) is
one of them, `re-amped2`. To make your own, see the modding sections of the
[developer guide](docs/DEVELOPING.md#settings-amped2ini).

---

## Reporting problems

Open an [issue](../../issues) and include:

- what you were doing, what happened, and how often;
- **`amped2.log`** from the install folder. The game rewrites it on every
  start, so copy it before starting again;
- for install problems, **`install.log`**, and the step that failed;
- your disc (USA or Europe), Windows version, graphics card, and whether you
  play with a controller or the keyboard.

---

## FAQ

**Is this an emulator?** No. The game's code is translated into C once and
compiled into a normal Windows program, which is why it runs so well.

**Why does the installer compile the game?** So that none of the game is
ever distributed. The translation happens on your PC, from your own disc,
and the result stays there.

**Can I get the game files here?** No. You need your own copy of Amped 2.

**Which disc works?** The USA and the European/Australian releases.

**Online play?** No. Xbox Live for the original Xbox shut down long ago.

**Steam Deck, Linux, Xbox, PlayStation?** Planned or being explored; see
[PLAN.md](PLAN.md), Part C.

---

## For developers

- [Developer guide](docs/DEVELOPING.md): the recompilation pipeline,
  building from source, the installer, and the bring-up notes.
- [Nico-D-eu/xboxrecomp](https://github.com/Nico-D-eu/xboxrecomp), branch
  `amped2-fixes`: the toolkit fork with RE-Amped2's changes. The build
  expects it in a sibling folder, `../xboxrecomp`.
- [CONTRIBUTING.md](CONTRIBUTING.md): how to help. The one rule is never to
  submit game files or anything made from them.
- [AGENTS.md](AGENTS.md): rules for AI coding agents.

## Credits

- **Amped 2** was made by Indie Built and published by Microsoft Game
  Studios.
- **[xboxrecomp](https://github.com/sp00nznet/xboxrecomp)** by sp00nznet and
  its contributors is the toolkit RE-Amped2 is built on. Its audio core comes
  from **[xemu](https://github.com/xemu-project/xemu)**.
- **[xdvdfs](https://github.com/antangelo/xdvdfs)** extracts the disc image.
  **[unluac](https://sourceforge.net/projects/unluac/)** decompiles the menu
  scripts for the RE-Amped2 menus. **[Capstone](https://www.capstone-engine.org/)**
  disassembles the game's code.

## Legal

- RE-Amped2 is an **unofficial, free fan project**, not affiliated with or
  endorsed by Microsoft. Amped, Amped 2 and Xbox are trademarks of Microsoft
  Corporation. Amped 2 © Microsoft Corporation.
- **No game code or data** is in this repository or in its releases. The
  installer builds the game on the player's PC, from the player's own disc.
- This project's own code is under the **MIT licence** ([LICENSE](LICENSE)).
  Third-party components and their licences are listed in
  [NOTICE.md](NOTICE.md).
- RE-Amped2's art was created under Microsoft's
  ["Game Content Usage Rules"](https://www.xbox.com/en-US/developers/rules)
  using assets from Amped 2, and it is not endorsed by or affiliated with
  Microsoft.
