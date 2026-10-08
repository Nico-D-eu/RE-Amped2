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
  5. OPTIONS becomes OPTIONS AND MODS (the MainMenu_Options string, which
     is also the Options screen's title). Its list (Shell.rui
     Scenes/Options.scene) loses XBOX LIVE OPTIONS and CREDITS and gains
     MODS at the end.
  6. MODS opens the Xbox Live options screen, rewritten as the Mods screen
     (Base.rui Scenes/Options_Online.scene, which already has Game
     Options' combo-row layout): rows MOD PACKS and TEXTURE PACK, each
     OFF / ON. MODS keeps the old item's action, $Options_Online, so
     Options.actions stays as it is. src/recomp_manual.c shows and saves
     the values ([Game] ModPacks and TexturePack in amped2.ini; wrappers of
     0x001ED950 and 0x001EDF30).
  7. The loading screen before a level shows the RE-Amped2 splash art from
     the texture pack, so its controller labels (the Loading_Controller_*,
     LoadingMenu_* and Loading_Control*_TextNormal strings) are blanked.
     "LOADING ..." stays. With the texture pack off, the original controller
     picture shows without its labels.

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
        "eng": "Close RE-Amped2.", "fre": "Fermer RE-Amped2.",
        "ger": "RE-Amped2 beenden."}),
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
    # Options and Mods (edits 5 and 6).
    "MainMenu_Options": ("MainMenu_Options", {
        "eng": "OPTIONS AND MODS", "fre": "OPTIONS ET MODS",
        "ger": "OPTIONEN UND MODS"}),
    "MainMenu_Options_Help": ("MainMenu_Options_Help", {
        "eng": "Customize your game settings and mods.",
        "fre": "Personnaliser les paramètres et les mods.",
        "ger": "Spieleinstellungen und Mods anpassen."}),
    "Options_Mods": ("Options_Cheats", {
        "eng": "MODS", "fre": "MODS", "ger": "MODS"}),
    "Options_Mods_Help": ("Options_Cheats_Help", {
        "eng": "Turn the mod packs and the texture pack on or off.",
        "fre": "Activer ou désactiver les packs de mods et de textures.",
        "ger": "Mod-Pakete und Texturpaket ein- oder ausschalten."}),
    "ModsOptions_Packs": ("LiveOptions_LiveVoice", {
        "eng": "MOD PACKS", "fre": "PACKS DE MODS", "ger": "MOD-PAKETE"}),
    "ModsOptions_Packs_Help": ("LiveOptions_LiveVoice_Help", {
        "eng": "Mod packs and loose files. Takes effect after a restart.",
        "fre": "Packs et fichiers de mods. Effectif au prochain lancement.",
        "ger": "Mod-Pakete und lose Dateien. Wirkt nach einem Neustart."}),
    "ModsOptions_Textures": ("LiveOptions_LiveVoice", {
        "eng": "TEXTURE PACK", "fre": "TEXTURES HD", "ger": "TEXTURPAKET"}),
    "ModsOptions_Textures_Help": ("LiveOptions_LiveVoice_Help", {
        "eng": "The HD texture pack. Takes effect after a restart.",
        "fre": "Le pack de textures HD. Effectif au prochain lancement.",
        "ger": "Das HD-Texturpaket. Wirkt nach einem Neustart."}),
}

# The loading screen before a level (edit 7): the controller labels are
# blanked (one space, in their own font) because the texture pack draws the
# RE-Amped2 splash art there instead of the controller pictures
# (Loading_Background, LoadingScreen2, Loading_Controller, Loading_Controls).
# "LOADING ..." and the tip screens' text stay.
BLANK = [f"Loading_Controller_{n}" for n in (
    "Accelerate", "Butter", "FlipSpin", "Grabs", "JibGrind", "LipTrick", "Pause",
    "ResetBoarder", "Turn", "andJump")] + [
    "LoadingMenu_JibSlideRail", "LoadingMenu_LipTrick"] + [
    f"Loading_Control{n}_TextNormal" for n in (
        "A", "AA", "B", "Back", "Pad", "RightPad", "Start", "Stick", "Stick2",
        "White", "X", "Y")]

# Options list (edit 5): the items dropped, and the one added at the end,
# per list of Scenes/Options.scene.
OPTIONS_SCENE = "GuiPackages/Shell.rui/Scenes/Options.scene"
OPTIONS_DROP = {"$Options_Online", "$PlayCreditsMovie", "Options_Online",
                "Options_Online_Help", "Options_Credits", "Options_Credits_Help"}
OPTIONS_ADD = {
    "AButton": "$Options_Online",       # the Mods screen keeps the scene name
    "Start": "$Options_Online",
    "HelpTextIDs": "Options_Mods_Help",
    "TextIDs": "Options_Mods",
}

# The Mods screen (edit 6): its rows, each with its value list (Lua controls
# 1 and 2, bound to item slots 1 and 2 by the original .sceneData). The row
# order is the one src/recomp_manual.c handles.
MODS_SCENE = "GuiPackages/Base.rui/Scenes/Options_Online.scene"
OFF_ON = ["GameOptions_Vibration_Off", "GameOptions_Vibration_On"]
MODS_ROWS = [("ModsOptions_Packs", OFF_ON), ("ModsOptions_Textures", OFF_ON)]

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


def edit_lists(src, edit):
    """Rewrite the one-line quoted items of every list `name = { ... }`:
    edit(name, items) returns the new items (or None to keep the list)."""
    import re
    lines, out, i = src.splitlines(), [], 0
    while i < len(lines):
        m = re.match(r"^( *)(\w+) = \{$", lines[i])
        if not m:
            out.append(lines[i])
            i += 1
            continue
        ind, name = m.groups()
        j = i + 1
        while lines[j].strip().startswith('"'):
            j += 1
        if lines[j] not in (ind + "}", ind + "},"):
            out.append(lines[i])            # a list of tables, not of items
            i += 1
            continue
        items = [ln.strip().rstrip(",")[1:-1] for ln in lines[i + 1:j]]
        new = edit(name, items)
        if new is None:
            out.extend(lines[i:j + 1])
        else:
            out.append(lines[i])
            out.extend(f'{ind}  "{it}"' + ("," if k < len(new) - 1 else "")
                       for k, it in enumerate(new))
            out.append(lines[j])
        i = j + 1
    return "\r\n".join(out) + "\r\n"


def options_scene():
    """Options: without XBOX LIVE OPTIONS and CREDITS, MODS at the end."""
    src = source_of(OPTIONS_SCENE)
    done = []

    def edit(name, items):
        if name not in OPTIONS_ADD:
            return None
        kept = [it for it in items if it not in OPTIONS_DROP]
        if len(kept) != len(items) - 2:
            sys.exit(f"{OPTIONS_SCENE}: {name} lacks the Live or Credits item")
        done.append(name)
        return kept + [OPTIONS_ADD[name]]

    src = edit_lists(src, edit)
    if sorted(done) != sorted(OPTIONS_ADD):
        sys.exit(f"{OPTIONS_SCENE}: lists edited: {done}")
    write_override(OPTIONS_SCENE, src,
                   "Options without Xbox Live and Credits, with Mods")


def mods_scene():
    """The Xbox Live options scene as the Mods screen: its two rows and
    their value lists replaced, and the Mods title."""
    src = source_of(MODS_SCENE)
    names = [r for r, _ in MODS_ROWS]
    value_lists = iter([v for _, v in MODS_ROWS])
    done = []

    def edit(name, items):
        if name == "TextIDs" and items and items[0].startswith("LiveOptions_LiveVoice_"):
            done.append("voice")
            return next(value_lists)
        if name == "TextIDs" and items and items[0].startswith("LiveOptions_Appear_"):
            done.append("appear")
            return next(value_lists)
        if name == "TextIDs" and items == ["LiveOptions_LiveVoice", "LiveOptions_Appear"]:
            done.append("rows")
            return names
        if name == "HelpTextIDs":
            done.append("help")
            return [n + "_Help" for n in names]
        return None

    src = edit_lists(src, edit)
    if sorted(done) != ["appear", "help", "rows", "voice"]:
        sys.exit(f"{MODS_SCENE}: lists edited: {done}")
    if src.count('TitleID = "Options_Online"') != 1:
        sys.exit(f"{MODS_SCENE}: no Options_Online title")
    src = src.replace('TitleID = "Options_Online"', 'TitleID = "Options_Mods"')
    write_override(MODS_SCENE, src, "the Xbox Live options as the Mods screen")


def strings():
    """The new keys in every language's StringTable.dat."""
    with zipfile.ZipFile(GAME / "GuiPackages" / "Base.rui") as z:
        for lang in ("eng", "fre", "ger"):
            name = f"StringTables/{lang}/StringTable.dat"
            table = string_table.read(z.read(name))
            for key, (like, texts) in STRINGS.items():
                table.set(key, texts[lang], like)
            for key in BLANK:
                table.set(key, " ", key)
            path = OVERRIDES / "GuiPackages" / "Base.rui" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(string_table.write(table))
            print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main_menu()
    main_actions()
    game_options_scene()
    game_options_scene_data()
    options_scene()
    mods_scene()
    strings()
    run("repack")
