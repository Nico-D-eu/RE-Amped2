RE-AMPED2: Amped 2 for Linux (early access)
===========================================

Start the game with ./RE-Amped2 in this folder (or "RE-Amped2" in your
applications menu).

Early access
  The Linux build is newer than the Windows one: expect bugs and rough
  edges. Report problems on GitHub (link below). Say what you were doing,
  which distribution and graphics card you use, and attach amped2.log from
  this folder; it is rewritten on every start, so copy it before starting
  the game again.

  Mod packs, texture packs and loose files work as on Windows. The game
  draws with OpenGL 3.3 or newer; packs made of BC7 textures (the
  RE-Amped2 look is) need OpenGL 4.2.

Controls
  An Xbox-style controller works out of the box.
  Keyboard: arrow keys = d-pad, Z X A S = A B X Y, Enter = Start,
  Backspace = Back, Q/E = white/black, 1/3 = triggers,
  number pad = left stick, I J K L = right stick.
  F11 or Alt+Enter switches between window and full screen.
  F3 shows the frame rate.

Settings
  Options and Mods > Game Options has WINDOW and RESOLUTION (with the
  RE-Amped2 menus), and Options and Mods > Mods turns the mod packs and
  textures on or off. The RE-Amped2 menus are built into mods/build/game
  (they need Java while installing; --no-menus leaves them out).
  amped2.ini in this folder holds every setting; it is created the first
  time the game starts. Remove the ; in front of a line to use it.
  The RE-Amped2 look (logo, splash, loading screen) is the mod pack in
  mods/packs/re-amped2, listed in mods/mods.json. Install with --no-look
  to leave it out.

Your saves
  Career progress is saved in game/UDATA in this folder. Back it up before
  deleting the folder. Running the installer again keeps it.

Report a problem
  https://github.com/Nico-D-eu/RE-Amped2/issues

New versions
  https://github.com/Nico-D-eu/RE-Amped2/releases

About
  RE-Amped2 is an unofficial, free fan project. It is not affiliated with or
  endorsed by Microsoft. Amped, Amped 2 and Xbox are trademarks of Microsoft.
  Amped 2 (c) Microsoft Corporation. This folder holds the game built on this
  PC from your own disc; none of it was downloaded.
  RE-Amped2's art was created under Microsoft's "Game Content Usage Rules"
  using assets from Amped 2, and it is not endorsed by or affiliated with
  Microsoft: https://www.xbox.com/en-US/developers/rules
  The licences of RE-Amped2 (MIT) and the software it is built with are in
  the licenses folder.
