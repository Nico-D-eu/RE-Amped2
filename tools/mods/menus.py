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
     lists only take $actions; a bare Name() there is ignored.
  3. Its own label and help text, MainMenu_Quit and MainMenu_Quit_Help,
     added to Base.rui's StringTables/<lang>/StringTable.dat for all three
     languages (tools/assets/string_table.py), in the fonts of the
     "Choose Boarder" item above it.
  4. Options -> Game Options gains WINDOW (windowed / full screen) and
     RESOLUTION (1x-4x) rows, read from and written to amped2.ini by
     src/recomp_manual.c (wrappers of 0x001EE6A0, which shows the values,
     and 0x001EE7E0, GameOptions_ComboChanged). Base.rui
     Scenes/Options_Game.scene gets the rows and their value lists, and
     .sceneData binds the free item slots Item5 and Item6 to them.

Run it with the Python that has the asset toolkit's packages (numpy,
pillow): `py -3.10 tools/mods/menus.py` here.
"""
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GAME = ROOT / "game"
sys.path.insert(0, str(ROOT / "tools" / "assets"))
import rui_actions  # noqa: E402
import string_table  # noqa: E402
ASSETS = ROOT / "tools" / "assets" / "amped_assets.py"
SOURCE = ROOT / "mods" / "source"
OVERRIDES = ROOT / "mods" / "overrides"

MAIN_SCENE = "GuiPackages/Shell.rui/Scenes/Main.scene"
DROP_FROM_MAIN = {'"$MutltiPlayer"', '"MainMenu_Mutliplayer"', '"MainMenu_Mutliplayer_Help"'}
# Appended after the last entry of each list (keyed by that entry).
QUIT_AFTER = {
    '"$ChangeBoarder"': '"$Quit"',                            # AButton, Start
    '"MainMenu_ChangeBoarder"': '"MainMenu_Quit"',
    '"MainMenu_ChangeBoarder_Help"': '"MainMenu_Quit_Help"',
}

# New strings: key -> (the entry whose font and scale it takes, text by language)
STRINGS = {
    "MainMenu_Quit": ("MainMenu_ChangeBoarder", {
        "eng": "QUIT GAME", "fre": "QUITTER LE JEU", "ger": "SPIEL BEENDEN"}),
    "MainMenu_Quit_Help": ("MainMenu_ChangeBoarder_Help", {
        "eng": "Close Amped 2.", "fre": "Fermer Amped 2.",
        "ger": "Amped 2 beenden."}),
    # Options -> Game Options: the PC settings (edit 4).
    "GameOptions_Window": ("GameOptions_Vibration", {
        "eng": "WINDOW", "fre": "FENÊTRE", "ger": "FENSTER"}),
    "GameOptions_Window_Help": ("GameOptions_Vibration_Help", {
        "eng": "Play in a window or full screen (F11 also switches).",
        "fre": "Jouer en fenêtre ou en plein écran (aussi avec F11).",
        "ger": "Im Fenster oder im Vollbild spielen (auch mit F11)."}),
    "GameOptions_Window_Windowed": ("GameOptions_Vibration_On", {
        "eng": "Windowed", "fre": "Fenêtre", "ger": "Fenster"}),
    "GameOptions_Window_Full": ("GameOptions_Vibration_On", {
        "eng": "Full screen", "fre": "Plein écran", "ger": "Vollbild"}),
    "GameOptions_Resolution": ("GameOptions_Vibration", {
        "eng": "RESOLUTION", "fre": "RÉSOLUTION", "ger": "AUFLÖSUNG"}),
    "GameOptions_Resolution_Help": ("GameOptions_Vibration_Help", {
        "eng": "Higher is sharper. Takes effect after a restart.",
        "fre": "Plus haut, plus net. Effectif au prochain lancement.",
        "ger": "Höher ist schärfer. Wirkt nach einem Neustart."}),
    **{f"GameOptions_Resolution_{n}x": ("GameOptions_Vibration_On", {
        "eng": f"{n}x", "fre": f"{n}x", "ger": f"{n}x"}) for n in (1, 2, 3, 4)},
}

# The rows added to Game Options, in order (rows 4 and 5 -- recomp_manual.c
# handles them), each with its value list. They take the two free item slots
# that are on screen, Item5 and Item6. A seventh row would scroll the list,
# and the value boxes stay with their slots when it scrolls (the game's own
# lists never scroll combo rows), so every value would show a row off. The
# picture format stays in amped2.ini (VideoModes).
GAME_OPTIONS_ROWS = [
    ("GameOptions_Window", ["GameOptions_Window_Windowed",
                            "GameOptions_Window_Full"]),
    ("GameOptions_Resolution", [f"GameOptions_Resolution_{n}x"
                                for n in (1, 2, 3, 4)]),
]
GAME_OPTIONS_SLOTS = ["Item5", "Item6"]


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


def lua_list_append(src, name, items, start=0, indent=None):
    """Append quoted items to the list `name = { ... }` found after start."""
    import re
    pat = rf"^({indent if indent is not None else '[ ]*'}){name} = \{{[ ]*\r?$"
    m = re.compile(pat, re.M).search(src, start)
    if not m:
        sys.exit(f"list {name} not found")
    ind = m.group(1)
    close = re.compile(rf"^{ind}\}}", re.M).search(src, m.end())
    body_end = src.rfind("\n", 0, close.start())       # end of the last entry
    last = src[:body_end].rstrip("\r")
    add = "".join(f',\r\n{ind}  "{it}"' for it in items)
    return last + add + src[body_end:], m.start()


def game_options_scene():
    """Options_Game.scene: two more rows in the main list, and their value
    lists as controls 6 and 7 (Lua indices; the item slots bind to them)."""
    entry = "GuiPackages/Base.rui/Scenes/Options_Game.scene"
    src = source_of(entry)
    if "GameOptions_Window" in src:
        sys.exit(f"{entry}: already modded")
    key = src.index("HelpTextIDs = {")
    at = src.rfind("\n", 0, key) + 1          # its line, where the lists start
    ind = src[at:key]
    names = [r for r, _ in GAME_OPTIONS_ROWS]
    src, _ = lua_list_append(src, "HelpTextIDs", [n + "_Help" for n in names], at, ind)
    src, _ = lua_list_append(src, "Left", ["$ListComboLeft"] * len(names), at, ind)
    src, _ = lua_list_append(src, "Right", ["$ListComboRight"] * len(names), at, ind)
    states = src[src.index("States = {", at):]
    have = states[:states.index("}")].count('"Grid"')
    src, _ = lua_list_append(src, "States", ["Grid"] * max(0, len(names) + 4 - have), at, ind)
    src, _ = lua_list_append(src, "TextIDs", names, at, ind)
    # Value lists, appended to Controls (closing "  }," before DefaultAction).
    end = src.index("\n  },", src.index("Controls = {"))
    lists = "".join(
        ",\r\n    {\r\n      Items = {\r\n        TextIDs = {\r\n"
        + ",\r\n".join(f'          "{v}"' for v in values)
        + "\r\n        }\r\n      }\r\n    }"
        for _, values in GAME_OPTIONS_ROWS)
    src = src[:end].rstrip("\r") + lists + src[end:]
    write_override(entry, src, "Game Options: Window and Resolution rows")


def game_options_scene_data():
    """Options_Game.sceneData: bind the free item slots' grids to the new
    value lists. ControlData is binary in a Lua string: per node a u16 name
    length, the name, the u16 control it shows (0xFFFF = none), a u16 node
    id, a u16 child count. Item1-4 show controls 4, 2, 1, 5; Item5, Item6
    and ItemLast none."""
    entry = "GuiPackages/Base.rui/Scenes/Options_Game.sceneData"
    src = source_of(entry)
    cd = src.index("ControlData = ")
    cd_end = src.index("\n", cd)
    data = src[cd:cd_end]
    markers = ["Item1\\", "Item2\\", "Item3\\", "Item4\\", "Item5\\",
               "Item6\\", "ItemLast\\", "TMP_Options_EntireListBox\\"]
    for i, slot in enumerate(GAME_OPTIONS_SLOTS):
        start = data.index(slot + "\\255\\255")
        end = min(p for p in (data.find(m, start + 1) for m in markers) if p > start)
        part = data[start:end]
        if part.count("grid\\255\\255") != 1:
            sys.exit(f"{entry}: {slot} has no free grid")
        part = part.replace("grid\\255\\255", f"grid\\{6 + i:03d}\\000")
        data = data[:start] + part + data[end:]
    src = src[:cd] + data + src[cd_end:]
    write_override(entry, src, "Game Options: item slots 5 and 6 bound to the new rows")


def strings():
    """The new keys in every language's StringTable.dat."""
    with zipfile.ZipFile(GAME / "GuiPackages" / "Base.rui") as z:
        for lang in ("eng", "fre", "ger"):
            name = f"StringTables/{lang}/StringTable.dat"
            table = string_table.read(z.read(name))
            for key, (like, texts) in STRINGS.items():
                table.set(key, texts[lang], like)
            path = OVERRIDES / "GuiPackages" / "Base.rui" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(string_table.write(table))
            print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main_menu()
    main_actions()
    game_options_scene()
    game_options_scene_data()
    strings()
    run("repack")
