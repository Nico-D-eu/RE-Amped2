# RE-Amped2: notices

## What this project is

RE-Amped2 is an unofficial fan project. It is **not affiliated with,
endorsed by or sponsored by Microsoft** or Indie Built. Amped, Amped 2, Xbox
and Microsoft are trademarks of Microsoft Corporation. They are used here
only to say which game this project works with.

Amped 2 © Microsoft Corporation.

## What the MIT licence covers

`LICENSE` (MIT) covers this repository's own work: the host program and
hand-written code in `src/`, the tools in `tools/`, the installer in
`installer/`, the configuration in `config/`, and the documentation.

It does **not** cover, and this repository contains none of:

- **the game.** That means its executable (`default.xbe`), its data, music,
  movies and art. Players need their own legally owned copy of Amped 2.
- **the code generated from the game.** `tools/regen.ps1` writes it to
  `src/recomp/gen/` on the player's PC, from the player's own disc. It is
  never committed or distributed.
- **anything built from the game on the player's PC.** That covers the
  compiled `RE-Amped2.exe` and the edited archives the mod recipes write to
  `mods/`. They stay on that PC.

## RE-Amped2 art

The RE-Amped2 logo, start-up splash, loading screen, installer art and icon
(`branding/` and `installer/assets/`) are fan art. They were composed with
the help of AI image tools, using screenshots of the original game as
reference.

> RE-Amped2's art was created under Microsoft's "Game Content Usage Rules"
> using assets from Amped 2, and it is not endorsed by or affiliated with
> Microsoft. Game Content Usage Rules:
> https://www.xbox.com/en-US/developers/rules

RE-Amped2 is free. Nothing in it is sold, and nothing is put behind a paid
subscription.

## Third-party components

| Component | Licence | Where | How it is used |
|---|---|---|---|
| [xboxrecomp](https://github.com/sp00nznet/xboxrecomp) | MIT, with some files under LGPL-2.1-or-later (from [xemu](https://github.com/xemu-project/xemu)) | `../xboxrecomp`, in the installer as source | The recompiler and runtime. See its `LICENSE`, `NOTICE` and `LICENSES/`. |
| [xdvdfs](https://github.com/antangelo/xdvdfs) | MIT | In the installer as `xdvdfs.exe` | Extracts the player's disc image. Text: `licenses/xdvdfs-LICENSE.txt`. |
| [unluac](https://sourceforge.net/projects/unluac/) | MIT | In the installer as `unluac.jar` | Decompiles the game's menu scripts for the menu mod, on the player's PC. Text: `licenses/unluac-LICENSE.txt`. |
| [Capstone](https://www.capstone-engine.org/) | BSD-3-Clause | Downloaded from PyPI during an install, into a temporary folder that is removed afterwards | The recompiler's disassembler. Not redistributed. |
| [NumPy](https://numpy.org/), [Pillow](https://python-pillow.org/) | BSD-3-Clause, MIT-CMU | Same as Capstone | Used by the menu mod. Not redistributed. |

### Build tools the installer can install

The installer can install these only after the player agrees on the
installer's Location page. They come from their publishers through Windows'
package manager (winget), under the publishers' own terms:

| Tool | Licence |
|---|---|
| Visual Studio 2022 Build Tools (Microsoft) | https://visualstudio.microsoft.com/license-terms/ |
| Python 3.13 (Python Software Foundation) | https://docs.python.org/3/license.html |
| CMake (Kitware) | https://cmake.org/licensing/ |
| Microsoft Build of OpenJDK 21 (only for the menu mod) | https://openjdk.org/legal/gplv2+ce.html |
