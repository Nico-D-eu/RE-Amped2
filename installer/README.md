# RE-Amped2 installer

`RE-Amped2-Setup.exe` is the player-facing way to get the recomp: a four-step
wizard that builds the game on the player's PC from their own disc image.
No game code or data is in it; it carries this project's sources, the
xboxrecomp toolkit, xdvdfs and the RE-Amped2 look (15 MB in all).

Version 0.3.1 is an **early-access** build (0.2.0 was the first public one,
0.1.0 the testers'): the header carries an
EARLY ACCESS tag, the footer says `v0.3.1 · Early Access`, and the first and
last pages and `README.txt` ask testers to report problems on GitHub Issues
(`Links.Issues` in `Shortcut.cs`) with their `amped2.log`. The footer's **Licences** link
opens the licence texts (see below).

## What the player sees

1. **Disc.** Pick the `.iso`/`.xiso` (or drop it on the window or on the
   `.exe`). The image is checked with `xdvdfs`: it must list, and its
   `default.xbe` must carry title ID `0x4D530041`. USA and Europe both pass.
2. **Location.** Install folder (default `C:\Games\RE-Amped2`, or the last
   one used), and four checkboxes: desktop shortcut, the RE-Amped2 menus
   (the menu mod), the RE-Amped2 look (the branding pack and sharp fonts) and, unticked by
   default, HD movies (below). HD movies add 6.5 GB to the space needed.
   The page lists the build tools: found, missing but installable (winget),
   or missing with a download link. Folders under Program Files or Windows are
   refused, since the game writes its saves and `amped2.ini` beside itself.
   **Nothing is installed without consent:** if any tool would be installed,
   Install first opens a dialog (`ConsentDialog.cs`) listing each tool with
   its publisher, size, purpose and a link to its licence terms, plus the
   Python packages fetched into the temporary folder. Only after the player
   ticks "I accept ..." and clicks *Agree and install* does the install
   start. With HD movies ticked, the same dialog (or one of its own, *Agree
   and download*, when no build tool is missing) lists FFmpeg and
   Real-ESRGAN. The approved tool names go into `InstallOptions.ApprovedTools`, and
   `Toolchain.InstallMissing` refuses any tool not in that set (for example
   CMake, if the build tools turn up without it): the install stops and asks
   the player to go back. winget's `--accept-package-agreements` is passed
   only for approved tools.
3. **Install.** The stages below, with a progress bar, elapsed time and a
   "Show details" log. Cancel kills the running tool's process tree.
4. **Done.** What was installed and where, short play tips (controls, F11,
   Game Options, where saves live), and a box with a "Report a problem"
   button that opens GitHub Issues. On failure: the step that failed, a plain
   explanation and advice, and the install log.

## What it does

All work happens in `<install>\_install_temp`, removed at the end.

| Stage | Work |
|---|---|
| Build tools | Finds Python 3.10+ (64-bit, with venv), Visual Studio C++ tools + Windows SDK (vswhere), a CMake that knows that Visual Studio's generator (VS-bundled first), Java (only for the menu mod). Missing ones the player approved are installed with winget: `Microsoft.VisualStudio.2022.BuildTools` (VCTools workload + CMake), `Python.Python.3.13` (user scope), `Kitware.CMake`, `Microsoft.OpenJDK.21`. |
| Disc | `xdvdfs unpack` straight into `<install>\game`. Existing files are overwritten, so a reinstall keeps `game\UDATA` (saves). |
| Recompiler | Unpacks the payload to `_install_temp\src\amped2` and `\xboxrecomp`, makes `src\amped2\game` a junction to `<install>\game`, creates a venv and installs `capstone>=5,<6` (plus `numpy pillow` for the menu mod). |
| Translate | `tools\regen.ps1 -Python <venv python>` (steps 2–5; no Ghidra, so no FidDb names, which the build does not need). |
| Compile | `cmake -G "<that VS>" -A x64 -DCMAKE_GENERATOR_INSTANCE=... -DAMPED2_MP_JOBS=<cores, RAM/3 GB, 2..8>`, then `cmake --build --config Release --parallel`. |
| Menu mod | `tools\mods\menus.py` with Java on PATH; `mods\build\game` is copied to `<install>\mods\build\game`. A failure here only skips the mod. |
| HD movie tools | Only with HD movies ticked and both tools approved (`MovieTools.cs`). Downloads FFmpeg (BtbN's LGPL shared build, month-end autobuild 2026-10-31) and Real-ESRGAN ncnn-vulkan v0.2.5.0 from GitHub, checks each zip's SHA-256, and unpacks only what the recipe uses into `<install>\tools\bin\ffmpeg` (`bin\` without ffplay, and `LICENSE.txt`) and `tools\bin\realesrgan` (the program, `vcomp140.dll` and the realesr-animevideov3 models). A `.sha256` stamp skips the download on an update. Then it copies `tools\mods\movie_pack.py` to `<install>\tools\mods\` and writes `Convert HD movies.cmd`, which runs it with the Python the install used (`py -3` if that one is gone). A failure here only skips the HD movies. |
| Look | After Finish: `branding\pack\textures` (from `tools/branding/build.py`) goes to `<install>\mods\packs\re-amped2\textures`, with `re-amped2` first in `mods\mods.json` (other packs are kept). Without the menu mod, the loading screen's controller pictures stay, since their labels do (`menu-mod-only.txt`). Then `tools\mods\font_pack.py` (venv Python with NumPy and Pillow, a few seconds) scales the player's font atlases 4x into `<install>\mods\packs\fonts`, listed after `re-amped2`; if it fails, only the fonts are left out. If unticked, an update removes both packs. |
| Finish | `RE-Amped2.exe` (+ `RE-Amped2.pdb` for the crash handler), `RE-Amped2.ico`, `README.txt` (with the unofficial-project and Game Content Usage Rules notices), `install-info.txt` (sources' commits), `licenses\` (the licence texts, as below), desktop shortcut. An install from before the rename to RE-Amped2 loses its `Amped2.exe`, `Amped2.ico`, `amped2_recomp.pdb` and `Amped 2` desktop shortcut. |

Cleanup removes the junction on its own first and checks it is gone before
deleting the work folder, so the delete can never reach `game\`.

After a successful install with HD movies, the installer starts
`Convert HD movies.cmd` minimised, below normal priority (its children
inherit that), and the Done page says so. The recipe converts the start-up
movies first. Each copy is written as `.mp4.part` and renamed when it is
complete, so the game, which looks for a copy each time a movie starts,
uses finished ones straight away. On the RTX 2070 Max-Q all 50 took 4 h 48
min. Closing the window stops it; running the `.cmd` again skips the
finished movies. Without Vulkan, Real-ESRGAN fails and the recipe switches
to a plain Lanczos resize. An update leaves existing copies and tools alone,
ticked or not.

The full log is `<install>\install.log`. The install folder is remembered in
`HKCU\Software\REAmped2\Amped 2` (`InstallDir`) for the next run.

## Building the installer

Needs the .NET SDK (any recent one; the target is .NET Framework 4.8, which
Windows 10 and 11 have built in) and git.

```powershell
.\installer\build.ps1
```

It packs `obj\payload.zip` from the working trees of `amped2` (minus
`installer\`, `.claude\` and `screenshots\`) and `..\xboxrecomp` (git-tracked plus untracked,
not ignored, so never `game\`, `mods\`, generated code or build output),
`tools\bin\unluac.jar` and `..\xdvdfs.exe`, then builds
`installer\dist\RE-Amped2-Setup.exe`. Uncommitted changes are included;
`manifest.txt` in the payload (and `install-info.txt` after an install)
records the commits with `+modified`. Commit both repos first for a release.

### Release builds on GitHub

`.github/workflows/installer.yml` builds the same installer from the public
repositories, on every `v*` tag or by hand (Actions › Installer › Run
workflow), so anyone can check where a release comes from:

- this repository at the tag;
- the toolkit fork at the full commit in `toolkit.ref`. Push that commit
  to `Nico-D-eu/xboxrecomp` and update the file before tagging;
- xdvdfs and unluac from `fetch-tools.ps1`, which downloads fixed versions
  and checks their SHA-256 (also handy locally:
  `.\installer\fetch-tools.ps1 -OutDir ..\tools`, then pass `-Xdvdfs` and
  `-Unluac` to `build.ps1`).

The installer comes out as a workflow artifact, with its SHA-256 in the run's
summary. `.github/workflows/linux.yml` packs the Linux tarball
(`tools/linux/package.sh`, see DEVELOPING "Linux release") from the same two
commits on the same triggers; the toolkit commit must include the Linux back
end for that tarball to build. Signing through [SignPath Foundation](https://signpath.org/) is
wired in and switches on when the repository variable
`SIGNPATH_ORGANIZATION_ID` and the secret `SIGNPATH_API_TOKEN` are set; the
project slug `RE-Amped2` and signing policy `release-signing` must match the
SignPath project. Publishing the release stays manual.

The icon (the installer, its window, the installed `RE-Amped2.ico` and the
desktop shortcut) is `..\branding\RE-Amped2.ico`, the same file
`RE-Amped2.exe` embeds. `tools/branding/build.py` also makes the header art
(`assets\header.jpg`, 1600x280 for the 800x140 header at 200% scaling) and
the Done page's badge (`assets\badge.png`). The colours in `WizardForm.cs`
are taken from that art.

## Third-party pieces in the payload

- [xdvdfs](https://github.com/antangelo/xdvdfs) (MIT), disc extraction.
  Licence text: `../licenses/xdvdfs-LICENSE.txt`.
- [unluac](https://sourceforge.net/projects/unluac/) (MIT), Lua decompiling
  for the menu mod. Licence text: `../licenses/unluac-LICENSE.txt`.
- [xboxrecomp](https://github.com/sp00nznet/xboxrecomp) (MIT, with
  LGPL-2.1-or-later files from xemu), the toolkit, as source. Its `LICENSE`,
  `NOTICE` and `LICENSES/` travel with it.
- Downloaded on the player's PC, under their own terms and only with the
  player's consent: Visual Studio Build Tools, Python, CMake, OpenJDK; with
  HD movies, FFmpeg and Real-ESRGAN (into the install folder, see
  `../NOTICE.md`); and into the temporary folder, the pip packages
  (capstone, numpy, pillow).

The HD movie tools are downloaded rather than shipped. Packing them would
make the installer about 8 times bigger (16 MB now; the two zips are 122
MB) for an option most players leave off. It would also make RE-Amped2
the distributor of an LGPL FFmpeg build, which brings source-offer duties.
Downloading pinned, hash-checked releases gives the player the same files
without either cost.

`Payload.LicenseFiles` lists the licence texts: RE-Amped2's `LICENSE` and
`NOTICE.md`, xboxrecomp's `LICENSE`, `NOTICE` and `LGPL-2.1.txt`, and the
xdvdfs and unluac licences. The footer's Licences link extracts them to the
temp folder and opens it, and every install writes them to
`<install>\licenses\`. They come from the payload's `amped2/` and
`xboxrecomp/` trees, so keep the paths in `LicenseFiles` in step if a file
moves. See `../NOTICE.md` for the full picture.
