# Testing the Linux release on a distro

A checklist for trying `RE-Amped2-<version>-linux.tar.gz` on a fresh
Linux install, real or virtual. Each pass gives one line in the table at the
end. The tarball is built with `tools/linux/package.sh` (DEVELOPING,
"Linux release").

## Before you start

- **Machine.** Bare metal tells the most. In a virtual machine the game
  needs OpenGL 4.2 or newer for the RE-Amped2 look (BC7 textures), so
  check `glxinfo -B` (package `mesa-utils`, `mesa-demos` or `glx-utils`)
  first. Mesa's software renderer, llvmpipe, starts the game but draws a
  few frames a second at most. VirtualBox and VMware without 3D
  acceleration fall into that case.
- **Copy over:** the tarball, its `.sha256` and your disc image. Check the
  tarball with `sha256sum -c RE-Amped2-*-linux.tar.gz.sha256`.
- **Note:** the distro and version, desktop (GNOME, KDE, ...), X11 or
  Wayland (`echo $XDG_SESSION_TYPE`), GPU and driver (`glxinfo -B`, the
  "OpenGL renderer" and "core profile version" lines) and the sound server
  (`pactl info | grep 'Server Name'`, PipeWire or PulseAudio).

## Install

```bash
tar xzf RE-Amped2-*-linux.tar.gz
cd RE-Amped2-*-linux
./install.sh "/path/to/Amped 2.iso"
```

On an image-based distro (Bazzite, Silverblue, Kinoite) `install.sh`
offers to create a Distrobox container, `re-amped2`, and builds inside it.
Answer `y`. The container's first start takes a few minutes. Then:

- [ ] the build-tools question appears again inside the container (answer
      `y`; no password is needed there);
- [ ] the menu entry starts the game through the container
      (`~/Games/RE-Amped2/RE-Amped2.sh`);
- [ ] sound and the controller work through the container, and with an
      NVIDIA card, the GPU too (`glxinfo -B` inside `distrobox enter re-amped2`).

- [ ] The build-tools check names what is missing and offers the right
      package command (apt, pacman or dnf). Answering `y` installs them.
      On other distros it lists what to install by hand.
- [ ] The Java question for the RE-Amped2 menus. Say yes once; on another
      distro, try no and check the install finishes without the menus.
- [ ] The disc is unpacked and its title ID accepted.
- [ ] Translating and compiling finish. Note the time, which `install.sh`
      prints.
- [ ] `~/Games/RE-Amped2` has `RE-Amped2`, `README.txt`, `licenses/` and
      `install-info.txt`, and the applications menu has an RE-Amped2 entry
      with the icon.
- [ ] If anything fails, `~/Games/RE-Amped2/install.log` has the details.

## Play

Start it from the menu entry, or from a terminal for the messages:
`cd ~/Games/RE-Amped2 && ./RE-Amped2`.

- [ ] The window opens; F11 switches full screen on and off.
- [ ] The boot movies (MGS, XSN, Intro) play with sound at normal speed:
      the intro takes about a minute. Start (Enter) skips it.
- [ ] Title and menus: the RE-Amped2 logo and splash, and Quit Game in the
      main menu (with the menus).
- [ ] A controller works (plugged in before or after starting), and the
      keyboard works (arrows, Z X A S, Enter).
- [ ] Ride a level for a few minutes. F3 shows the frame rate; note it.
      Listen for music dropping out or repeating.
- [ ] Options and Mods > Game Options: change the resolution and window
      size.
- [ ] Save in career mode, quit, start again: the save is there
      (`game/UDATA`).
- [ ] Run `./install.sh` again on the same folder: it updates, and the
      save is kept.

## Report

Per distro, attach `amped2.log` (rewritten on every start, so copy it right
after the session) and `install.log` when something goes wrong.

| Distro | Session, GPU, sound | Install | Time | Movies | Pad | Level fps | Saves | Notes |
|---|---|---|---|---|---|---|---|---|
| | | | | | | | | |
