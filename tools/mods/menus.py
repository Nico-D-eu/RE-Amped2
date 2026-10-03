"""The menu mod: build its overrides from the original game data and repack.

    python tools/mods/menus.py

Game data is never committed, so this mod is kept as a recipe: decompile the
original scene (tools/assets), apply the edits below, write the result as
plain Lua source into mods/overrides/, then run the asset toolkit's repack.
The game's Lua loads source as readily as bytecode. The runtime reads
mods/build/game/ over game/ (RECOMP_OVERLAY_DIR, on by default in main.c;
ini [Game] Mods=0 turns it off), so nothing in game/ changes.

Edits:
  1. Main menu without "Multiplayer" (Shell.rui Scenes/Main.scene: the
     $MutltiPlayer entries -- the game's own spelling -- of the AButton and
     Start action lists, and their text and help IDs).
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "tools" / "assets" / "amped_assets.py"
SOURCE = ROOT / "mods" / "source"
OVERRIDES = ROOT / "mods" / "overrides"

MAIN_SCENE = "GuiPackages/Shell.rui/Scenes/Main.scene"
DROP_FROM_MAIN = {'"$MutltiPlayer"', '"MainMenu_Mutliplayer"', '"MainMenu_Mutliplayer_Help"'}


def run(*args):
    r = subprocess.run([sys.executable, str(ASSETS), *args])
    if r.returncode:
        sys.exit(f"amped_assets {' '.join(args)} failed")


def source_of(entry):
    """The decompiled original of an archive entry (decompiled on demand)."""
    path = SOURCE / entry
    if not path.exists():
        run("decompile", "--filter", entry)
    if not path.exists():
        sys.exit(f"could not decompile {entry}")
    return path.read_text(encoding="latin-1")


def write_override(entry, text, what):
    path = OVERRIDES / entry
    path.parent.mkdir(parents=True, exist_ok=True)
    body = f"-- Amped 2 menu mod (tools/mods/menus.py): {what}\r\n" + text
    path.write_text(body, encoding="latin-1", newline="")
    print(f"wrote {path.relative_to(ROOT)}")


def main_menu():
    src = source_of(MAIN_SCENE)
    kept, dropped = [], 0
    for line in src.splitlines():
        if line.strip().rstrip(",") in DROP_FROM_MAIN:
            dropped += 1
            continue
        kept.append(line)
    if dropped != 4:
        sys.exit(f"{MAIN_SCENE}: expected 4 Multiplayer lines, found {dropped}")
    write_override(MAIN_SCENE, "\r\n".join(kept) + "\r\n", "main menu without Multiplayer")


if __name__ == "__main__":
    main_menu()
    run("repack")
