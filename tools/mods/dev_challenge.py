r"""Developer challenges: a saved run of yours, raced as a Pro challenge.

    python tools/mods/dev_challenge.py list   [--udata DIR]
    python tools/mods/dev_challenge.py add    --save ID [--title TEXT] [--slot ProChalN]
                                              (--slot: the Pro challenge to copy, same board)
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


def rpl_records(data: bytes):
    """The replay's records: [(offset, length, (x, y, z) in m, time s)].

    After the 5-byte header, each record is the position (three int16, 1/20
    m), the orientation (three int16), more state whose size depends on its
    flags (20-22 bytes in all), and ends with the run's time as a float32.
    The fields between are not needed: records are told apart by the time
    climbing and two of the three coordinates moving at most 3 m from one
    to the next. A coordinate is kept modulo 1000 m (20000 units): ML1's
    pros are recorded 1000 m short of their drop points in X, and a run
    there went from 1 to 19994 crossing X = 1000 m. Positions here are
    unwrapped along the run; level_offset() finds the run's own 1000 m.
    A short trailer (18 bytes in the ones seen) follows the last."""
    rpl_start(data)
    out, o, t = [], 5, 0.0
    prev, wrap = None, [0, 0, 0]
    while o < len(data) - 10:
        found = None
        for n in range(16, 48):
            if o + n > len(data):
                break
            tv = struct.unpack_from("<f", data, o + n - 4)[0]
            if not t <= tv < t + 0.5:
                continue
            if o + n + 6 > len(data):
                found = n
                break
            here = struct.unpack_from("<3h", data, o)
            nxt = struct.unpack_from("<3h", data, o + n)
            if sum(abs(a - b) < 60 for a, b in zip(here, nxt)) >= 2:
                found = n
                break
        if found is None:
            break
        raw = struct.unpack_from("<3h", data, o)
        if prev is not None:
            for k in range(3):
                d = raw[k] + wrap[k] - prev[k]
                if d > 10000:
                    wrap[k] -= 20000
                elif d < -10000:
                    wrap[k] += 20000
        prev = [raw[k] + wrap[k] for k in range(3)]
        t = struct.unpack_from("<f", data, o + found - 4)[0]
        out.append((o, found, tuple(v / 20.0 for v in prev), t))
        o += found
    if not out:
        raise ValueError("no replay records found")
    return out


EVT_HEADER = 0x53
# Bytes after an event's time and kind (kind 10, the pad, has a uint16
# length instead). Found on all the saved replays at hand; any other kind
# carries 4.
EVT_SIZES = {22: 20, 23: 20, 6: 2, 17: 0}


def evt_events(data: bytes):
    """The event file's events after its 0x53-byte header: [(offset, size,
    time s)]. An event is float32 time, uint32 kind, then for kind 10 (the
    pad) a uint16 length and that many bytes, for kinds 22 and 23 (jumps:
    positions) 20, kind 6 2, kind 17 none, the others (0-3, 7, 11-13: tricks
    and states) 4 (EVT_SIZES)."""
    out, o = [], EVT_HEADER
    while o + 8 <= len(data):
        t, kind = struct.unpack_from("<fI", data, o)
        if kind == 10:
            n = 10 + struct.unpack_from("<H", data, o + 8)[0]
        else:
            n = 8 + EVT_SIZES.get(kind, 4)
        out.append((o, n, t))
        o += n
    if o != len(data):
        raise ValueError("event file not understood (stopped at %d of %d)" % (o, len(data)))
    return out


def level_offset(drops: str, rpl: bytes):
    """The whole 1000 m per axis a replay's positions are short of where they
    are (rpl_records): a run starts at a drop point, so the offset that puts
    its first position on one of the level's drop points (none on LX2, X +1000
    m on ML1)."""
    first = rpl_records(rpl)[0][2]
    best = None
    for dx in (-1000.0, 0.0, 1000.0, 2000.0):
        for dy in (-1000.0, 0.0, 1000.0):
            for dz in (-1000.0, 0.0, 1000.0, 2000.0):
                near = nearest_drop(drops, [first[0] + dx, first[1] + dy, first[2] + dz])
                if near and (best is None or near[0] < best[0]):
                    best = (near[0], (dx, dy, dz))
    return best[1] if best and best[0] < 50.0 else (0.0, 0.0, 0.0)


HOLD = 2.35            # seconds a run stands still at its start (the countdown)


def cut_recording(rpl: bytes, evt: bytes, t0: float, t1: float):
    """The section t0..t1 (seconds of the run) of a replay and its events,
    with times moved so the section starts where the run did.

    A run stands still for its first HOLD s while the countdown runs (the
    disc's pros and LX2's dev1 move at 2.35 s); a section starts at speed.
    So its first record is held that long first: otherwise the pro rides
    off during the countdown (user's BR2 line test, 2026-11-11: the pro far
    ahead, 2 of 3 misses from the start, with the player 20 m behind)."""
    recs = rpl_records(rpl)
    keep = [r for r in recs if t0 <= r[3] <= t1]
    if len(keep) < 60:
        raise ValueError("cut %.1f-%.1f s keeps %d records (run is %.1f s)"
                         % (t0, t1, len(keep), recs[-1][3]))
    shift = keep[0][3] - recs[0][3] - HOLD
    out = bytearray(rpl[:5])
    o, n, _, t = keep[0]
    step = (keep[-1][3] - keep[0][3]) / (len(keep) - 1)
    k = 0
    while recs[0][3] + k * step < keep[0][3] - shift - step / 2:
        rec = bytearray(rpl[o:o + n])
        struct.pack_into("<f", rec, n - 4, recs[0][3] + k * step)
        out += rec
        k += 1
    for o, n, _, t in keep:
        rec = bytearray(rpl[o:o + n])
        struct.pack_into("<f", rec, n - 4, t - shift)
        out += rec
    last = recs[-1]
    out += rpl[last[0] + last[1]:]               # the trailer
    ev = bytearray(evt[:EVT_HEADER])
    for o, n, t in evt_events(evt):
        if keep[0][3] <= t <= keep[-1][3]:
            e = bytearray(evt[o:o + n])
            struct.pack_into("<f", e, 0, t - shift)
            ev += e
    return bytes(out), bytes(ev), keep


def cut_start(rpl: bytes, t0: float):
    """Where a section starting at t0 puts the player and the pro.

    The player starts where the rider was at t0 (a place on the line, on the
    snow), facing the way the rider went; the pro's recording starts once
    the rider had covered HEAD_START m along the line from there (at most 4
    s later), which gives the head start the disc's pros have. Returns
    (position, unit direction, the pro's start time)."""
    recs = rpl_records(rpl)
    i = next(k for k, r in enumerate(recs) if r[3] >= t0)
    a, path, j = recs[i], 0.0, i
    while j + 1 < len(recs) and path < HEAD_START and recs[j + 1][3] < a[3] + 4.0:
        path += math.dist(recs[j][2], recs[j + 1][2])
        j += 1
    b = recs[j]
    d = [q - p for p, q in zip(a[2], b[2])]
    n = math.sqrt(sum(v * v for v in d)) or 1.0
    return a[2], [v / n for v in d], b[3]


RUNUP = 40.0           # metres of the line the player rides before a section


def runup_start(rpl: bytes, t0: float, metres: float = RUNUP):
    """Where the player starts for a section beginning at t0: `metres` back
    up the recorded line (user, 2026-11-11: a section needs a run-up to be
    ridden). Where the run started closer than that, the rest goes straight
    back from the run's start, against the way the rider set off (user's
    BR2 photo test: a 45 m run-up gave too little speed for the first
    jump). Returns (position, unit direction the rider went from there, the
    run's time at the line's point)."""
    recs = rpl_records(rpl)
    i = next((k for k, r in enumerate(recs) if r[3] >= t0), len(recs) - 1)
    j, path = i, 0.0
    while j > 0 and path < metres:
        path += math.dist(recs[j - 1][2], recs[j][2])
        j -= 1
    a = recs[j]
    k, ahead = j, 0.0
    while k + 1 < len(recs) and ahead < 20.0:
        ahead += math.dist(recs[k][2], recs[k + 1][2])
        k += 1
    d = [q - p for p, q in zip(a[2], recs[k][2])]
    n = math.sqrt(sum(v * v for v in d)) or 1.0
    d = [v / n for v in d]
    short = max(0.0, metres - path)
    return [p - short * v for p, v in zip(a[2], d)], d, a[3]


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


def photo_slots(chal: str, drops: str):
    """{challenge ID: (drop point ID, 'board'/'skate')} for the level's photo
    shoots (CHAL_MEDIASEQ, Sequence drop points)."""
    slots = {}
    for i, j in tables(chal):
        block = chal[i:j]
        if 'ChalType = "CHAL_MEDIASEQ"' not in block:
            continue
        cid = re.search(r'\bID = "([^"]+)"', block).group(1)
        dp = re.search(r'DropPoints = \{\s*"([^"]+)"\s*\}', block)
        if not dp:
            continue
        a, b = table_with(drops, dp.group(1))
        skate = re.search(r"SnowSkate = true", drops[a:b]) is not None
        slots[cid] = (dp.group(1), "skate" if skate else "board")
    return slots


def dev_slots(chal: str, drops: str, dev: dict):
    return photo_slots(chal, drops) if dev.get("photo") else pro_slots(chal, drops)


RING_STEP = 17.0       # metres between a photo shoot's rings (the disc's: 12-22)


def ring_points(rpl: bytes, t0: float, t1: float, off):
    """Rings along the recorded line from t0 to t1, RING_STEP m apart along
    the path (positions unwrapped, plus the run's whole 1000 m)."""
    recs = [r for r in rpl_records(rpl) if t0 <= r[3] <= t1]
    pts, path, last = [], 0.0, None
    for r in recs:
        if last is not None:
            path += math.dist(last, r[2])
        last = r[2]
        if path >= RING_STEP * (len(pts) + 1) - RING_STEP / 2:
            pts.append([round(v + o, 2) for v, o in zip(r[2], off)])
    return pts


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


def prepend_table(text: str, block: str) -> str:
    """Add a top-level table before the first one."""
    start = tables(text)[0][0] + 1
    return text[:start] + block + ",\r\n" + text[start:]


def apply_challenge(chal: str, drops: str, dev: dict, pro_dir: str = "Pro",
                    photo_dir: str = "photoshoot"):
    """Add one developer challenge to a level's two scripts.

    It gets its own drop point and its own CHAL_PRO challenge (copies of the
    template Pro challenge of the same board, dev["slot"]), so the career's
    Pro challenges stay as they are. No rank and no reward: wins are counted
    by the mod, not the career."""
    drop_id, chal_id = dev_ids(dev)
    slot_drop, _ = dev_slots(chal, drops, dev)[dev["slot"]]
    i, j = table_with(chal, dev["slot"])
    block = chal[i + 1:j + 4]
    if dev.get("photo"):
        # A photo shoot: the level's own (CHAL_MEDIASEQ) with its rings along
        # the developer's line and the developer's score to beat.
        subs = [(r'\bID = "[^"]*"', 'ID = "%s"' % chal_id),
                (r'RankIncrease = \d+', "RankIncrease = 0"),
                (r'RewardType = "[^"]*"', 'RewardType = "REWARD_NONE"'),
                (r'RewardIndex = \d+', "RewardIndex = 0"),
                (r'RewardInfo = "[^"]*"', 'RewardInfo = "Empty"'),
                (r'Value = \d+', "Value = %d" % dev["score"]),
                (r'RingArrayFile = "[^"]*"', 'RingArrayFile = "Levels\\\\%s\\\\%s\\\\%s.lua"'
                 % (dev["level"], photo_dir, dev["id"])),
                (r'DropPoints = \{[^}]*\}', 'DropPoints = {"%s"}' % drop_id)]
        for pat, rep in subs:
            block, n = re.subn(pat, lambda m, rep=rep: rep, block, count=1)
            if n != 1:
                raise ValueError("%s: %s not found" % (dev["slot"], pat))
        return _add_drop(append_table(chal, block), drops, dev, slot_drop, drop_id)
    subs = [(r'\bID = "[^"]*"', 'ID = "%s"' % chal_id),
            (r'RankIncrease = \d+', "RankIncrease = 0"),
            (r'RewardType = "[^"]*"', 'RewardType = "REWARD_NONE"'),
            (r'RewardIndex = \d+', "RewardIndex = 0"),
            (r'RewardInfo = "[^"]*"', 'RewardInfo = "Empty"'),
            (r'ProReplay = "[^"]*"', 'ProReplay = "%s\\\\%s"' % (pro_dir, dev["id"])),
            (r'ProParts = "[^"]*"',
             'ProParts = "Characters\\\\Pro\\\\ProParts\\\\%s.Parts"' % dev["id"].capitalize()),
            (r'DropPoints = \{"[^"]*"\}', 'DropPoints = {"%s"}' % drop_id)]
    for pat, rep in subs:
        block, n = re.subn(pat, lambda m, rep=rep: rep, block, count=1)
        if n != 1:
            raise ValueError("%s: %s not found" % (dev["slot"], pat))
    return _add_drop(append_table(chal, block), drops, dev, slot_drop, drop_id)


def _add_drop(chal: str, drops: str, dev: dict, slot_drop: str, drop_id: str):
    """The challenge's own drop point, a copy of its template's."""
    # Start point: the drop point the recording began at gives the facing
    # and the camera; the new drop point sits HEAD_START m behind it, so the
    # pro starts ahead of the player.
    if dev.get("cut"):
        # A section from the middle of a run: the drop point is where the
        # section starts, facing the way the rider went (cut_start), and the
        # camera is 15 m behind it and 6 m up, looking at it.
        pos, d = dev["cut_start"], dev["cut_dir"]
        src = {}
        for i, axis in enumerate("XYZ"):
            src["DropLoc" + axis] = pos[i]
            src["DropDir" + axis] = d[i]
            src["CamLoc" + axis] = pos[i] - 15.0 * d[i] + (6.0 if axis == "Y" else 0.0)
        c = [pos[i] - src["CamLoc" + a] for i, a in enumerate("XYZ")]
        cn = math.sqrt(sum(v * v for v in c)) or 1.0
        raw = {"CamDir" + a: round(c[i] / cn, 3) for i, a in enumerate("XYZ")}
        raw.update({"DropDir" + a: round(d[i], 3) for i, a in enumerate("XYZ")})
    else:
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
        # A cut puts the player on the line itself and the pro ahead
        # (cut_start); a whole run steps the drop point back instead.
        back = 0.0 if dev.get("cut") else HEAD_START * src["DropDir" + axis]
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
        if d.get("photo"):
            text = ("%s, %s. Photo shoot: score %d points through the rings. Press A to start."
                    % (mountain, board, d["score"]))
        else:
            text = ("%s, %s. Beat the run with at most three misses. Press A to start."
                    % (mountain, board))
        s["DevChal_%s_Help" % d["id"]] = ("Career_ChangeGear_Help", text)   # two lines
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


def marks_for(proj: Project, args, level: str, saved=None):
    """The last complete L3+R3 section marked on `level` before the replay
    was saved (`saved`, a file time) (devchal-marks.json, written by the
    game beside amped2.ini with AMPED2_DEVCHAL_RECORD=1)."""
    folder = Path(args.ini) if args.ini else proj.root / "test" / "runs" / "devchal-play"
    path = folder / "devchal-marks.json"
    if not path.exists():
        sys.exit("no %s: mark a section with L3+R3 in test\\devchal-play.cmd first" % path)
    marks = [m for m in json.loads(path.read_text("utf-8"))["marks"]
             if m.get("level") == level and m.get("end") is not None]
    if saved is not None:
        import time
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(saved + 1))
        marks = [m for m in marks if m.get("when", "") <= stamp]
    if not marks:
        sys.exit("no complete section marked on %s in %s before the replay was saved" % (level, path))
    m = marks[-1]
    print("marks: %s, %s, %.1f-%.1f s" % (m.get("when", "?"), level, m["start"], m["end"]))
    return m["start"], m["end"]


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
    slots = photo_slots(chal, drops) if args.photo else pro_slots(chal, drops)
    # The slot is only the template (a Pro challenge of the same board) the
    # challenge and its drop point are copied from; any number of developer
    # challenges can share one.
    if args.slot:
        if args.slot not in slots:
            sys.exit("%s has no Pro challenge %s (has %s)" % (level, args.slot, ", ".join(slots)))
        slot = args.slot
    else:
        # The level's own Pro challenges first: a Legend challenge is CHAL_PRO
        # too, but its drop point is Type "Legend" and starts no Pro run.
        same = sorted((s for s, (_, k) in slots.items() if k == run["kind"]),
                      key=lambda s: (not s.startswith("ProChal"), s))
        if not same:
            sys.exit("%s has no %s %s challenge to copy"
                     % (level, run["kind"], "photo-shoot" if args.photo else "Pro"))
        slot = next((x for x in reversed(same) if x.startswith("ProChal")), same[-1])
    if slots[slot][1] != run["kind"]:
        sys.exit("%s is a %s challenge, the recording is a %s run"
                 % (slot, slots[slot][1], run["kind"]))
    used = {c["id"] for c in data["challenges"]}
    dev_id = next("dev%d" % n for n in range(1, 1000) if "dev%d" % n not in used)
    rec = proj.pack / "recordings" / dev_id
    rec.mkdir(parents=True, exist_ok=True)
    for ext in RECORDING + LOOK:
        shutil.copyfile(run["folder"] / ("Career." + ext), rec / ("Career." + ext))
    off = level_offset(drops, (run["folder"] / "Career.rpl").read_bytes())
    start = [round(v + d, 2) for v, d in zip(run["start"], off)]
    if any(off):
        print("positions are short by %s m on %s; corrected" % (off, level))
    entry = {
        "id": dev_id, "title": args.title or default_title(data, level, args.photo), "level": level,
        "slot": slot, "kind": run["kind"], "start": start,
        "save": run["save"], "save_name": run["name"]}
    t0, t1 = args.from_, args.to
    if args.marks and t0 is None:
        t0, t1 = marks_for(proj, args, level, (run["folder"] / "Career.rpl").stat().st_mtime)
    if args.photo:
        # A photo shoot: rings along the section, the developer's score to
        # beat; the player starts where the section starts (no pro, no head
        # start).
        rpl = (run["folder"] / "Career.rpl").read_bytes()
        recs = rpl_records(rpl)
        t0 = t0 if t0 is not None else recs[0][3]
        t1 = t1 if t1 is not None else recs[-1][3]
        pos, d, _ = runup_start(rpl, t0, args.runup)
        rings = ring_points(rpl, t0, t1, off)
        if len(rings) < 3:
            sys.exit("section %.1f-%.1f s gives only %d ring(s)" % (t0, t1, len(rings)))
        entry.update({"photo": True, "score": args.score, "rings": rings,
                      "cut": [round(t0, 2), round(t1, 2)],
                      "cut_start": [round(v + o, 2) for v, o in zip(pos, off)],
                      "cut_dir": [round(v, 3) for v in d]})
        print("photo shoot %.1f-%.1f s: %d rings, %d points to beat, starts at (%.1f, %.1f, %.1f)"
              % (t0, t1, len(rings), args.score, *entry["cut_start"]))
        t0 = None
    if t0 is not None:
        rpl = (run["folder"] / "Career.rpl").read_bytes()
        evt = (run["folder"] / "Career.evt").read_bytes()
        t1 = t1 if t1 is not None else rpl_records(rpl)[-1][3]
        # The pro starts `--runup` m back up the line from the section (user,
        # 2026-11-11: with the pro starting at the section and the player 40
        # m behind, the run began with 2 misses and the pro out of sight);
        # the player starts HEAD_START m behind the pro, as on the disc.
        # Both starts must lie in the same 1000 m block (positions are kept
        # modulo 1000 m, see rpl_records): BR2 line with the player at X
        # 1004.5 and the pro's start at 997.3 had no pro and "Slow Down"
        # from the start (user, 2026-11-11), as if the pro were 1000 m off.
        # So the pro starts later along the line until they share it.
        _, _, t_pro = runup_start(rpl, t0, args.runup)
        times = [r[3] for r in rpl_records(rpl)]
        while True:
            pro_at, _, _ = runup_start(rpl, t_pro, 0.0)
            pos, d, _ = runup_start(rpl, t_pro, HEAD_START)
            pos = [v + o for v, o in zip(pos, off)]
            pro_at = [v + o for v, o in zip(pro_at, off)]
            later = [t for t in times if t > t_pro]
            # 2 m clear of the block's edge.
            if all(math.floor((a - 2) / 1000) == math.floor((a + 2) / 1000) == math.floor(b / 1000)
                   for a, b in zip(pos, pro_at)) \
                    or not later or later[0] >= t0:
                break
            t_pro = later[0]
        _, _, keep = cut_recording(rpl, evt, t_pro, t1)
        tricks = sum(1 for o, n, t in evt_events(evt)
                     if keep[0][3] <= t <= keep[-1][3] and struct.unpack_from("<I", evt, o + 4)[0] == 12)
        entry.update({"cut": [round(t_pro, 3), round(t1, 2)], "cut_start": [round(v, 2) for v in pos],
                      "cut_dir": [round(v, 3) for v in d]})
        print("section %.1f-%.1f s of %.1f s (the pro from %.1f s, %.0f m back; the player %.0f m"
              " behind), %d trick(s), starts at (%.1f, %.1f, %.1f)"
              % (t0, t1, rpl_records(rpl)[-1][3], t_pro, args.runup, HEAD_START, tricks, *pos))
    data["challenges"].append(entry)
    proj.store(data)
    print("added %s: %s, %s, template %s (%s)" % (dev_id, level, run["kind"], slot, slots[slot][0]))
    cmd_build(proj, args)


def default_title(data, level: str, photo: bool) -> str:
    """"Millicent Line 1", "Bear Mountain Photo 1" (user, 2026-11-11): the
    mountain's full name without its stage number, the kind, and a number
    counting that mountain's challenges of that kind."""
    def mountain(lv):
        return re.sub(r"\s*\d+$", "", MOUNTAINS.get(lv, lv))
    kind = "Photo" if photo else "Line"
    n = 1 + sum(1 for c in data["challenges"]
                if mountain(c["level"]) == mountain(level) and bool(c.get("photo")) == bool(photo))
    return "%s %s %d" % (mountain(level), kind, n)


def cmd_rename(proj: Project, args):
    data = proj.load()
    c = next((c for c in data["challenges"] if c["id"] == args.dev_id), None)
    if c is None:
        sys.exit("no %s in %s" % (args.dev_id, proj.manifest))
    c["title"] = args.title
    proj.store(data)
    print("renamed %s: %s" % (args.dev_id, args.title))
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
        # The level's own spelling of its pro folder ("pro/" in ML1.res,
        # "Pro/" in LX2.res): entries are matched by case, and with "Pro" on
        # ML1 the pro's recording was not found and the pro never moved
        # (user's test: "Ahead of the pro" at once, 2026-11-09).
        names = zipfile.ZipFile(res).namelist()
        pro_dir = next((n.split("/")[0] for n in names if n.lower().startswith("pro/")), "Pro")
        photo_dir = next((n.split("/")[0] for n in names
                          if n.lower().startswith("photoshoot/")), "photoshoot")
        for dev in devs:
            a, b = table_with(drops, dev_slots(chal, drops, dev)[dev["slot"]][0])
            m = re.search(r'DisplayName = L"([^"]*)"', drops[a:b])
            drop_names[dev["id"]] = m.group(1) if m else dev["slot"]
        for dev in devs:
            chal, drops = apply_challenge(chal, drops, dev, pro_dir, photo_dir)
            rec = proj.pack / "recordings" / dev["id"]
            if dev.get("photo"):
                # No pro: the rings along the line are the challenge.
                rings = ",\r\n".join("  {\r\n    %s,\r\n    %s,\r\n    %s\r\n  }" % tuple(r)
                                      for r in dev["rings"])
                write(loose / "Levels" / level / (level + ".res") / photo_dir / ("%s.lua" % dev["id"]),
                      "MediaRings = {\r\n" + rings + "\r\n}\r\n")
                continue
            files = {ext: (rec / ("Career." + ext)).read_bytes() for ext in RECORDING}
            if dev.get("cut"):
                files["rpl"], files["evt"], _ = cut_recording(files["rpl"], files["evt"], *dev["cut"])
            for ext in RECORDING:
                dst = loose / "Levels" / level / (level + ".res") / pro_dir / ("%s.%s" % (dev["id"], ext))
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(files[ext])
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
    p.add_argument("--slot", help="Pro challenge to copy, e.g. ProChal3")
    p.add_argument("--from", dest="from_", type=float,
                   help="start of the section, seconds into the run")
    p.add_argument("--to", type=float, help="end of the section, seconds into the run")
    p.add_argument("--runup", type=float, default=RUNUP,
                   help="metres before the section: the player (photo) or the pro (Pro) starts there,"
                        " straight back past the run's start if needed (default 40)")
    p.add_argument("--photo", action="store_true",
                   help="a photo shoot: rings along the section instead of a pro")
    p.add_argument("--score", type=int, default=10000,
                   help="photo shoot: points to beat (default 10000)")
    p.add_argument("--marks", action="store_true",
                   help="the section from the last L3+R3 marks (devchal-marks.json)")
    p.add_argument("--ini", help="folder of amped2.ini for --marks (default: test\\runs\\devchal-play)")
    p.add_argument("--udata")
    p = sub.add_parser("remove", help="take a developer challenge out")
    p.add_argument("dev_id")
    p = sub.add_parser("rename", help="give a developer challenge a new title")
    p.add_argument("dev_id")
    p.add_argument("title")
    sub.add_parser("build", help="rebuild the pack's loose entries")
    args = ap.parse_args()
    proj = Project(Path(args.project), args.pack)
    {"list": cmd_list, "add": cmd_add, "remove": cmd_remove, "rename": cmd_rename,
     "build": cmd_build}[args.cmd](proj, args)


if __name__ == "__main__":
    main()
