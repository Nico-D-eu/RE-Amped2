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
  2. A QUIT item at the end of the main menu. It runs a new action, Quit,
     added to Scenes/Main.actions (tools/assets/rui_actions.py): $FlyButton
     -- the select sound and button animation every item plays -- then
     QuitGame(), a shell command src/recomp_manual.c registers (wrapper of
     0x00218140), which closes the window as the close button does. Item
     lists only take $actions; a bare Name() there is ignored. Its label
     reuses the pause menu's "QUIT" text until the string table can take
     new entries.
"""
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GAME = ROOT / "game"
sys.path.insert(0, str(ROOT / "tools" / "assets"))
import rui_actions  # noqa: E402
ASSETS = ROOT / "tools" / "assets" / "amped_assets.py"
SOURCE = ROOT / "mods" / "source"
OVERRIDES = ROOT / "mods" / "overrides"

MAIN_SCENE = "GuiPackages/Shell.rui/Scenes/Main.scene"
DROP_FROM_MAIN = {'"$MutltiPlayer"', '"MainMenu_Mutliplayer"', '"MainMenu_Mutliplayer_Help"'}
# Appended after the last entry of each list (keyed by that entry).
QUIT_AFTER = {
    '"$ChangeBoarder"': '"$Quit"',                            # AButton, Start
    '"MainMenu_ChangeBoarder"': '"PauseMenu_QuitToMainMenu_TextNormal"',
    '"MainMenu_ChangeBoarder_Help"': '"PauseMenu_QuitToMainMenu_TextNormal"',
}


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
    kept, dropped, added = [], 0, 0
    for line in src.splitlines():
        item = line.strip().rstrip(",")
        if item in DROP_FROM_MAIN:
            dropped += 1
            continue
        if item in QUIT_AFTER and not line.rstrip().endswith(","):
            indent = line[:len(line) - len(line.lstrip())]
            kept.append(line.rstrip() + ",")
            kept.append(indent + QUIT_AFTER[item])
            added += 1
            continue
        kept.append(line)
    if dropped != 4 or added != 4:
        sys.exit(f"{MAIN_SCENE}: expected 4 Multiplayer lines and 4 list ends,"
                 f" found {dropped} and {added}")
    write_override(MAIN_SCENE, "\r\n".join(kept) + "\r\n",
                   "main menu without Multiplayer, with QUIT at the end")


def main_actions():
    """Scenes/Main.actions plus the Quit action ($FlyButton; QuitGame())."""
    entry = "GuiPackages/Shell.rui/Scenes/Main.actions"
    with zipfile.ZipFile(GAME / "GuiPackages" / "Shell.rui") as z:
        f = rui_actions.read(z.read("Scenes/Main.actions"))
    if f.find("Quit"):
        sys.exit(f"{entry}: already has a Quit action")
    stmts = [b"$" + f.ref("FlyButton"), f.ref("QuitGame") + b"()"]
    # Sorted by name, as every shipped file is: appended at the end, the
    # game's lookup (a binary search, by the look of it) never found it.
    f.actions.append(rui_actions.Action("Quit", [], [(b"", stmts)]))
    f.actions.sort(key=lambda a: a.name)
    path = OVERRIDES / entry
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(rui_actions.write(f))
    print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main_menu()
    main_actions()
    run("repack")
