r"""Developer challenges: a saved run of yours, raced as a Pro challenge.

    python tools/mods/dev_challenge.py list   [--udata DIR]
    python tools/mods/dev_challenge.py add    --save ID [--title TEXT] [--slot ProChalN]
    python tools/mods/dev_challenge.py remove DEV_ID
    python tools/mods/dev_challenge.py build
    (all take --project DIR and --pack NAME, default dev-challenges)

Record a run in the game and keep it with the replay VCR's Save Replay. The
game stores each saved replay as a save of its own in UDATA\4d530041\<id>\
(named like "Replay5 LX2 Brd <rider>"), holding the run in the same files the
game's Pro challenges play: Career.rpl (motion), Career.evt (tricks) and
Career.ActionMap, plus the rider's look (Career.parts, Career.boarder).

`add` copies those files (read only; saves are never written) into the pack's
recordings\ folder and lists the challenge in the pack's devchallenges.json.
`build` turns the list into loose archive entries (src/mod_loose.c) under
mods\packs\<pack>\loose\ and enables the pack in mods\mods.json:

- Levels\<L>\<L>.res\Pro\devN.{rpl,evt,ActionMap}: the recording;
- Characters\pro\pro.res\ProParts\DevN.{parts,boarder}: the rider's look;
- <L>_Challenges.lua: a challenge of its own, DevChal<n>, a copy of the
  level's Pro challenge of the same board (--slot, the template) with
  ProReplay = "Pro\devN", ProParts = "...\DevN.Parts", no rank and no
  reward. The career's Pro challenges stay as they are;
- <L>_DropPoints.lua, in <L>.res and again in Levels.res (the game keeps two
  identical copies): its own drop point Dev<n>, named after the challenge,
  where the recording starts, 20 m back up the slope, so the pro has the
  head start the disc's pros have (21-40 m). Type "Pro" is what makes the
  game start a Pro challenge there.
- the DEVELOPER CHALLENGES list (Career) with one item per challenge.

A on a list item starts the challenge straight away (start_statements): no
mountain list, no drop-point menu, and the mountain need not be unlocked.
The edited scripts come from the
decompiled sources in mods\source (tools/assets, amped_assets.py), so this
runs only where those exist. Nothing made from the game goes into git.

Replay format, as far as needed here: a .rpl starts with 02 00 00 00 00 and
then the first position as three little-endian int16 X, Y, Z in 1/20 m.
"""
import argparse
import json
import math
import re
import shutil
import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "assets"))
import rui_actions  # noqa: E402
import string_table  # noqa: E402

TITLE_ID = "4d530041"
LANGS = ("eng", "fre", "ger")
# The Career screen's DEVELOPER CHALLENGES list (menus.py edit 10). A scene is
# three entries named after it, but PushMenu only opens names default.xbe
# registers (a native object per screen, built at start-up): a new name, even
# a copy of Options, never opens. So the list takes the place of
# PlayerFeedback (Base.rui, always loaded), an Xbox Live screen nothing
# reaches without Live. Its native class overrides the same few slots as the
# Options_Online one the menu mod already reuses for MODS AND GRAPHICS.
SCENE_NAME = "PlayerFeedback"
SCENE = "Scenes/" + SCENE_NAME
SCENE_ARCHIVE = "GuiPackages/Base.rui"
SHELL = "GuiPackages/Shell.rui"
BASE = "GuiPackages/Base.rui"
# Mountain names as the menus show them (the levels' own LEVEL_NAMEs are
# internal: "LaaxII", "Bear2").
MOUNTAINS = {
    "ML1": "Millicent 1", "ML2": "Millicent 2", "LX1": "Laax 1", "LX2": "Laax 2",
    "BR1": "Bear Mountain 1", "BR2": "Bear Mountain 2", "BR3": "Bear Mountain 3",
    "BR4": "Bear Mountain 4", "BK1": "Breckenridge 1", "BK2": "Breckenridge 2",
    "AU1": "Mt. Buller 1", "AU2": "Mt. Buller 2", "HD1": "Mt. Hood 1",
    "HD2": "Mt. Hood 2", "NZ1": "New Zealand"}
RECORDING = ("rpl", "evt", "ActionMap")
LOOK = ("parts", "boarder")
HEAD_START = 20.0      # metres the player starts behind the pro
LIFT = 1.0             # metres above the slope, so the drop lands on snow
NEAR_START = 6.0       # a recording starts this close to its drop point
DROP_FIELDS = ("DropLoc", "CamLoc")
FLOAT = r"-?\d+(?:\.\d+)?"


# ---- saves ------------------------------------------------------------------

def save_name(folder: Path) -> str:
    meta = folder / "SaveMeta.xbx"
    if not meta.exists():
        return ""
    text = meta.read_bytes().decode("utf-16-le", "ignore")
    m = re.search(r"Name=([^\r\n\x00]*)", text)
    return m.group(1).strip() if m else ""


def rpl_start(data: bytes):
    if len(data) < 11 or data[:5] != b"\x02\x00\x00\x00\x00":
        raise ValueError("not a replay this tool knows (header %s)" % data[:5].hex())
    return [v / 20.0 for v in struct.unpack_from("<3h", data, 5)]


def board_kind(parts_text: str) -> str:
    m = re.search(r'MeshType\s*=\s*"([^"]+)"', parts_text)
    return "skate" if m and "skate" in m.group(1).lower() else "board"


def saved_runs(udata: Path, levels):
    """Yield one dict per saved replay in UDATA (photo-shoot replays too)."""
    for folder in sorted((udata / TITLE_ID).glob("*")):
        if not (folder / "Career.rpl").exists():
            continue
        name = save_name(folder)
        words = name.split()
        level = next((w for w in words[1:3] if w.upper() in levels), "")
        try:
            start = rpl_start((folder / "Career.rpl").read_bytes())
        except ValueError:
            start = None
        parts = folder / "Career.parts"
        kind = board_kind(parts.read_text("latin-1")) if parts.exists() else "board"
        yield {"save": folder.name, "name": name, "level": level.upper(),
               "kind": kind, "start": start, "folder": folder}


# ---- the level scripts ------------------------------------------------------

def tables(text: str):
    """(start, end) of each top-level table, "\n  {" ... "\n  }"."""
    spans, pos = [], 0
    while True:
        i = text.find("\n  {", pos)
        if i < 0:
            return spans
        j = text.find("\n  }", i)
        spans.append((i, j))
        pos = j + 4


def table_with(text: str, ident: str):
    for i, j in tables(text):
        if re.search(r'\bID = "%s"' % re.escape(ident), text[i:j]):
            return i, j
    raise KeyError(ident)


def numbers(block: str):
    return {k: float(v) for k, v in re.findall(r"(\w+) = (%s)" % FLOAT, block)}


def set_number(block: str, key: str, value) -> str:
    """Set key = value: a float (written with 2 decimals) or a string as is."""
    text = value if isinstance(value, str) else "%.2f" % value
    out, n = re.subn(r"(\b%s = )%s" % (key, FLOAT), lambda m: m.group(1) + text, block)
    if n != 1:
        raise ValueError("%s found %d times" % (key, n))
    return out


def pro_slots(chal: str, drops: str):
    """{challenge ID: (drop point ID, 'board'/'skate')} for CHAL_PRO challenges."""
    slots = {}
    for i, j in tables(chal):
        block = chal[i:j]
        if 'ChalType = "CHAL_PRO"' not in block:
            continue
        cid = re.search(r'\bID = "([^"]+)"', block).group(1)
        dp = re.search(r'DropPoints = \{"([^"]+)"\}', block)
        if not dp:
            continue
        a, b = table_with(drops, dp.group(1))
        skate = re.search(r"SnowSkate = true", drops[a:b]) is not None
        slots[cid] = (dp.group(1), "skate" if skate else "board")
    return slots


def nearest_drop(drops: str, pos):
    best = None
    for i, j in tables(drops):
        v = numbers(drops[i:j])
        if "DropLocX" not in v:
            continue
        d = math.dist(pos, (v["DropLocX"], v["DropLocY"], v["DropLocZ"]))
        if best is None or d < best[0]:
            raw = dict(re.findall(r"(\w+) = (%s)" % FLOAT, drops[i:j]))
            best = (d, re.search(r'\bID = "([^"]+)"', drops[i:j]).group(1), v, raw)
    return best


def dev_ids(dev: dict):
    """The challenge's own IDs in the level's scripts: drop point Dev<n>,
    challenge DevChal<n>, from the pack ID dev<n>."""
    n = dev["id"][3:]
    return "Dev" + n, "DevChal" + n


def append_table(text: str, block: str) -> str:
    """Add a top-level table ("  {" ... "  }") after the last one."""
    end = tables(text)[-1][1] + 4
    return text[:end] + ",\r\n" + block + text[end:]


def apply_challenge(chal: str, drops: str, dev: dict):
    """Add one developer challenge to a level's two scripts.

    It gets its own drop point and its own CHAL_PRO challenge (copies of the
    template Pro challenge of the same board, dev["slot"]), so the career's
    Pro challenges stay as they are. No rank and no reward: wins are counted
    by the mod, not the career."""
    drop_id, chal_id = dev_ids(dev)
    slot_drop, _ = pro_slots(chal, drops)[dev["slot"]]
    i, j = table_with(chal, dev["slot"])
    block = chal[i + 1:j + 4]
    subs = [(r'\bID = "[^"]*"', 'ID = "%s"' % chal_id),
            (r'RankIncrease = \d+', "RankIncrease = 0"),
            (r'RewardType = "[^"]*"', 'RewardType = "REWARD_NONE"'),
            (r'RewardIndex = \d+', "RewardIndex = 0"),
            (r'RewardInfo = "[^"]*"', 'RewardInfo = "Empty"'),
            (r'ProReplay = "[^"]*"', 'ProReplay = "Pro\\\\%s"' % dev["id"]),
            (r'ProParts = "[^"]*"',
             'ProParts = "Characters\\\\Pro\\\\ProParts\\\\%s.Parts"' % dev["id"].capitalize()),
            (r'DropPoints = \{"[^"]*"\}', 'DropPoints = {"%s"}' % drop_id)]
    for pat, rep in subs:
        block, n = re.subn(pat, lambda m, rep=rep: rep, block, count=1)
        if n != 1:
            raise ValueError("%s: %s not found" % (dev["slot"], pat))
    chal = append_table(chal, block)

    # Start point: the drop point the recording began at gives the facing
    # and the camera; the new drop point sits HEAD_START m behind it, so the
    # pro starts ahead of the player.
    near = nearest_drop(drops, dev["start"])
    if near is None or near[0] > NEAR_START:
        raise ValueError("%s: no drop point within %.0f m of the recording's start %s"
                         % (dev["id"], NEAR_START, dev["start"]))
    src, raw = near[2], near[3]
    a, b = table_with(drops, slot_drop)
    pro = drops[a + 1:b + 4]
    index = max(int(x) for x in re.findall(r"\bIndex = (\d+)", drops)) + 1
    for pat, rep in [(r'\bID = "[^"]*"', 'ID = "%s"' % drop_id),
                     (r'\bIndex = \d+', "Index = %d" % index),
                     (r'DisplayName = L"[^"]*"', 'DisplayName = L"%s"' % dev["title"]),
                     # Kept out of the level's drop-point menu, as the disc's
                     # own debug drop points are (parsed to byte +0xA of the
                     # drop point, sub_000A5xxx): only the DEVELOPER
                     # CHALLENGES list starts it (PLAN Phase 25).
                     (r'IsDebugOnly = (true|false)', "IsDebugOnly = true")]:
        pro, n = re.subn(pat, lambda m, rep=rep: rep, pro, count=1)
        if n != 1:
            raise ValueError("%s: %s not found" % (slot_drop, pat))
    for axis in "XYZ":
        back = HEAD_START * src["DropDir" + axis]
        lift = LIFT if axis == "Y" else 0.0
        for field in DROP_FIELDS:
            pro = set_number(pro, field + axis, src[field + axis] - back + lift)
        pro = set_number(pro, "CamDir" + axis, raw["CamDir" + axis])
        pro = set_number(pro, "DropDir" + axis, raw["DropDir" + axis])
    return chal, append_table(drops, pro)


# ---- the menu screen --------------------------------------------------------

def lua_list(name, items, indent="        "):
    body = (",\r\n" + indent + "  ").join('"%s"' % i for i in items)
    return "%s%s = {\r\n%s  %s\r\n%s}" % (indent, name, indent, body, indent)


def scene_files(game: Path, items):
    """The DEVELOPER CHALLENGES scene: {entry in SCENE_ARCHIVE: bytes}.

    items: (action, text ID, help ID, statements), statements as GUI action
    text, e.g. ['$FlyButton', 'PushMenu("LevelSelect")']. The list looks
    and behaves like Career's (same layout file, same list actions), with
    its own items, so Career's help texts don't show here."""
    lists = [lua_list("AButton", [a for a, _, _, _ in items]),
             lua_list("HelpTextIDs", [h for _, _, h, _ in items]),
             lua_list("Start", [a for a, _, _, _ in items]),
             lua_list("TextIDs", [t for _, t, _, _ in items])]
    scene = ("Scenes." + SCENE_NAME + " = {\r\n"
             '  ButtonLegendID = "ButtonLegend_AB",\r\n'
             "  Controls = {\r\n"
             "    [1] = {\r\n"
             '      BButton = "$Back",\r\n'
             '      Back = "$Back",\r\n'
             '      DefaultInput = "ListProcessInput",\r\n'
             '      Down = "ListSelNext()",\r\n'
             "      Items = {\r\n" + ",\r\n".join(lists) + "\r\n      },\r\n"
             '      Up = "ListSelPrevious()"\r\n'
             "    }\r\n"
             "  },\r\n"
             '  DefaultAction = "$SetupMenu"\r\n'
             "}\r\n")
    with zipfile.ZipFile(game / SHELL) as z:
        layout = z.read("Scenes/MainCareer.sceneData")
        f = rui_actions.read(z.read("Scenes/MainCareer.actions"))
    for action, _, _, stmts in items:
        f.actions.append(rui_actions.Action(action.lstrip("$"), [], [(b"", [
            action_tokens(f, s) for s in stmts])]))
    f.actions.sort(key=lambda a: a.name)      # the game looks them up sorted
    return {SCENE + ".scene": ("-- RE-Amped2 developer challenges (tools/mods/dev_challenge.py)\r\n"
                               + scene).encode("latin-1"),
            SCENE + ".sceneData": layout,
            SCENE + ".actions": rui_actions.write(f)}


def action_tokens(f, stmt: str) -> bytes:
    """GUI action text -> tokens: names and quoted strings become string refs."""
    out, i = b"", 0
    for m in re.finditer(r"[A-Za-z_][A-Za-z_0-9]*", stmt):
        out += stmt[i:m.start()].encode("ascii") + f.ref(m.group())
        i = m.end()
    return out + stmt[i:].encode("ascii")


def string_tables(base_rui: Path, strings):
    """Base.rui's string tables with strings = {key: (like, text)} added."""
    out = {}
    with zipfile.ZipFile(base_rui) as z:
        for lang in LANGS:
            entry = "StringTables/%s/StringTable.dat" % lang
            table = string_table.read(z.read(entry))
            for key, (like, text) in strings.items():
                table.set(key, text[lang] if isinstance(text, dict) else text, like)
            out[entry] = string_table.write(table)
    return out


def challenge_strings(devs, drops_name):
    """{key: (like, text)} for the list's items, and the list's header when
    the shell comes back to it after a run (DevChal_Title, short enough for
    the native code to put in place of FreeRide_PlayLevel)."""
    s = {"DevChal_Title": ("Career_ChangeGear", "DEVELOPER CHALLENGES")}
    for d in devs:
        mountain = MOUNTAINS.get(d["level"], d["level"])
        board = "snowskate" if d["kind"] == "skate" else "snowboard"
        s["DevChal_" + d["id"]] = ("Career_ChangeGear", d["title"].upper())
        s["DevChal_%s_Help" % d["id"]] = ("Career_ChangeGear_Help", (
            "%s, %s. Beat the run with at most three misses. Press A to start."
            % (mountain, board)))   # two lines, as Career's
    return s


# ---- the pack ---------------------------------------------------------------

class Project:
    def __init__(self, root: Path, pack: str):
        self.root = root
        self.game = root / "game"
        self.source = root / "mods" / "source"
        self.pack = root / "mods" / "packs" / pack
        self.pack_name = pack
        self.manifest = self.pack / "devchallenges.json"

    def levels(self):
        return {p.name.upper() for p in (self.game / "Levels").iterdir()
                if (p / (p.name + ".res")).exists()}

    def load(self):
        if self.manifest.exists():
            return json.loads(self.manifest.read_text("utf-8"))
        return {"challenges": []}

    def store(self, data):
        self.pack.mkdir(parents=True, exist_ok=True)
        self.manifest.write_text(json.dumps(data, indent=2) + "\n", "utf-8")

    def entry(self, archive: Path, wanted: str) -> str:
        """The archive's own spelling of an entry name (case differs by level)."""
        names = zipfile.ZipFile(archive).namelist()
        for n in names:
            if n.lower() == wanted.lower():
                return n
        raise KeyError("%s has no %s" % (archive, wanted))

    def level_source(self, level: str, kind: str) -> Path:
        p = self.source / "Levels" / level / (level + ".res") / ("%s_%s.lua" % (level, kind))
        if not p.exists():
            sys.exit("missing %s: decompile the game's scripts first "
                     "(tools/assets/amped_assets.py)" % p)
        return p


def read(p: Path) -> str:
    with open(p, encoding="latin-1", newline="") as f:   # keep CRLF as it is
        return f.read()


def write(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="latin-1", newline="") as f:
        f.write(text)


def cmd_list(proj: Project, args):
    udata = Path(args.udata) if args.udata else proj.game / "UDATA"
    runs = list(saved_runs(udata, proj.levels()))
    if not runs:
        print("no saved replays in", udata)
    for r in runs:
        start = "(%.1f, %.1f, %.1f)" % tuple(r["start"]) if r["start"] else "?"
        print("%-14s %-5s %-6s %-30s start %s" % (r["save"], r["level"] or "?",
                                                  r["kind"], r["name"], start))


def cmd_add(proj: Project, args):
    udata = Path(args.udata) if args.udata else proj.game / "UDATA"
    runs = {r["save"]: r for r in saved_runs(udata, proj.levels())}
    run = runs.get(args.save)
    if not run:
        sys.exit("no saved replay %s in %s (see `list`)" % (args.save, udata))
    if not run["level"] or not run["start"]:
        sys.exit("can't tell the level or start of %s (%s)" % (args.save, run["name"]))
    data = proj.load()
    level = run["level"]
    chal = read(proj.level_source(level, "Challenges"))
    drops = read(proj.level_source(level, "DropPoints"))
    slots = pro_slots(chal, drops)
    taken = {c["slot"] for c in data["challenges"] if c["level"] == level}
    if args.slot:
        if args.slot not in slots:
            sys.exit("%s has no Pro challenge %s (has %s)" % (level, args.slot, ", ".join(slots)))
        slot = args.slot
    else:
        free = [s for s, (_, k) in slots.items() if k == run["kind"] and s not in taken]
        if not free:
            sys.exit("%s has no free %s Pro challenge slot" % (level, run["kind"]))
        slot = free[-1]
    if slots[slot][1] != run["kind"]:
        sys.exit("%s is a %s challenge, the recording is a %s run"
                 % (slot, slots[slot][1], run["kind"]))
    used = {c["id"] for c in data["challenges"]}
    dev_id = next("dev%d" % n for n in range(1, 1000) if "dev%d" % n not in used)
    rec = proj.pack / "recordings" / dev_id
    rec.mkdir(parents=True, exist_ok=True)
    for ext in RECORDING + LOOK:
        shutil.copyfile(run["folder"] / ("Career." + ext), rec / ("Career." + ext))
    data["challenges"].append({
        "id": dev_id, "title": args.title or run["name"], "level": level,
        "slot": slot, "kind": run["kind"], "start": run["start"],
        "save": run["save"], "save_name": run["name"]})
    proj.store(data)
    print("added %s: %s, %s, replaces %s (%s)" % (dev_id, level, run["kind"], slot, slots[slot][0]))
    cmd_build(proj, args)


def cmd_remove(proj: Project, args):
    data = proj.load()
    keep = [c for c in data["challenges"] if c["id"] != args.dev_id]
    if len(keep) == len(data["challenges"]):
        sys.exit("no %s in %s" % (args.dev_id, proj.manifest))
    data["challenges"] = keep
    proj.store(data)
    shutil.rmtree(proj.pack / "recordings" / args.dev_id, ignore_errors=True)
    print("removed", args.dev_id)
    cmd_build(proj, args)


def cmd_build(proj: Project, args):
    data = proj.load()
    loose = proj.pack / "loose"
    shutil.rmtree(loose, ignore_errors=True)
    by_level = {}
    for c in data["challenges"]:
        by_level.setdefault(c["level"], []).append(c)
    levels_res = proj.game / "Levels" / "Levels.res"
    drop_names = {}
    for level, devs in sorted(by_level.items()):
        res = proj.game / "Levels" / level / (level + ".res")
        chal = read(proj.level_source(level, "Challenges"))
        drops = read(proj.level_source(level, "DropPoints"))
        slots = pro_slots(chal, drops)
        for dev in devs:
            a, b = table_with(drops, slots[dev["slot"]][0])
            m = re.search(r'DisplayName = L"([^"]*)"', drops[a:b])
            drop_names[dev["id"]] = m.group(1) if m else dev["slot"]
        for dev in devs:
            chal, drops = apply_challenge(chal, drops, dev)
            rec = proj.pack / "recordings" / dev["id"]
            for ext in RECORDING:
                dst = loose / "Levels" / level / (level + ".res") / "Pro" / ("%s.%s" % (dev["id"], ext))
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(rec / ("Career." + ext), dst)
            for ext in LOOK:
                dst = (loose / "Characters" / "pro" / "pro.res" / "ProParts"
                       / ("%s.%s" % (dev["id"].capitalize(), ext)))
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(rec / ("Career." + ext), dst)
        write(loose / "Levels" / level / (level + ".res")
              / proj.entry(res, level + "_Challenges.lua"), chal)
        write(loose / "Levels" / level / (level + ".res")
              / proj.entry(res, level + "_DropPoints.lua"), drops)
        write(loose / "Levels" / "Levels.res"
              / proj.entry(levels_res, "%s/%s_droppoints.lua" % (level, level)), drops)
        print("built %s: %s" % (level, ", ".join("%s -> %s (template %s)"
                                                  % (d["id"], dev_ids(d)[1], d["slot"]) for d in devs)))
    if data["challenges"]:
        menu(proj, data["challenges"], drop_names, loose)
    enable(proj, bool(data["challenges"]))


def start_statements(dev: dict):
    """The list item's A action: start the challenge at once.

    StartDevChallenge(level, drop point) is a native command (src/
    recomp_manual.c): it sets the session's level as SelectLevel() does,
    without the mountain's locked check, and makes the level's drop-point
    screen start the hidden drop point Dev<n> without showing its menu. The
    rest is what Level Select's $SetupForLoadingScreen runs."""
    drop_id, _ = dev_ids(dev)
    return ["$FlyButton",
            'StartDevChallenge("%s", "%s")' % (dev["level"], drop_id),
            'SetActiveControl("")',
            "FlyEverythingOff()",
            "WaitForFlyEverythingOff()",
            "Yield()",
            "Yield()",
            "LaunchGame()"]


def menu(proj: Project, devs, drop_names, loose: Path):
    """Career -> DEVELOPER CHALLENGES lists this pack's challenges.

    Its strings go into Base.rui's string tables, starting from the menu
    mod's (mods\\build\\game) when it is there: rerun `build` after
    tools/mods/menus.py."""
    items = [("$DevChal_" + d["id"], "DevChal_" + d["id"], "DevChal_%s_Help" % d["id"],
              start_statements(d)) for d in devs]
    for entry, data in scene_files(proj.game, items).items():
        p = loose / SCENE_ARCHIVE / entry
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    built = proj.root / "mods" / "build" / "game" / BASE
    base = built if built.exists() else proj.game / BASE
    for entry, data in string_tables(base, challenge_strings(devs, drop_names)).items():
        p = loose / BASE / entry
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    print("built the DEVELOPER CHALLENGES list: %d item(s), strings from %s"
          % (len(items), base.relative_to(proj.root)))


def enable(proj: Project, on: bool):
    """List the pack first in mods\\mods.json (or take it out when empty)."""
    path = proj.root / "mods" / "mods.json"
    packs = json.loads(path.read_text("utf-8"))["packs"] if path.exists() else []
    packs = [p for p in packs if p != proj.pack_name]
    if on:
        packs.insert(0, proj.pack_name)
    path.write_text(json.dumps({"packs": packs}) + "\n", "utf-8")
    print("mods.json:", packs)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project", default=str(ROOT), help="RE-Amped2 folder (game\\, mods\\)")
    ap.add_argument("--pack", default="dev-challenges")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list", help="saved replays in UDATA")
    p.add_argument("--udata")
    p = sub.add_parser("add", help="make a developer challenge from a saved replay")
    p.add_argument("--save", required=True, help="save folder ID from `list`")
    p.add_argument("--title")
    p.add_argument("--slot", help="Pro challenge to stand in for, e.g. ProChal3")
    p.add_argument("--udata")
    p = sub.add_parser("remove", help="take a developer challenge out")
    p.add_argument("dev_id")
    sub.add_parser("build", help="rebuild the pack's loose entries")
    args = ap.parse_args()
    proj = Project(Path(args.project), args.pack)
    {"list": cmd_list, "add": cmd_add, "remove": cmd_remove, "build": cmd_build}[args.cmd](proj, args)


if __name__ == "__main__":
    main()
