"""Amped 2 asset toolkit: unpack, decompile, upscale and repack game data.

Run from anywhere:  python amped2/tools/assets/amped_assets.py <command> [options]

  unpack       extract every .gfx/.res archive into mods/extracted/
  decompile    turn the compiled Lua scripts into editable source in mods/source/
  tex-export   write every texture as PNG to mods/textures/original/ (+ manifest.json)
  tex-upscale  AI-upscale the exported textures with Upscayl into mods/textures/upscaled/
  tex-pack     compress upscaled / hand-edited textures into a replacement pack (mods/texture_pack/)
  tex-inject   put PNGs from mods/textures/inject/ back into the game's own .xpr/.pgf files
  repack       rebuild archives that have files in mods/overrides/ into mods/build/game/
  install      copy mods/build/game/ over game/, backing the originals up to mods/backup/
  restore      put the backed-up original archives back

The game directory itself is only written by `install` and `restore`.
"""
import argparse
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import archive                          # noqa: E402
import lua50beta                        # noqa: E402
import xboxtex as xt                    # noqa: E402

ROOT = Path(__file__).resolve().parents[2]          # amped2/
GAME = ROOT / "game"
MODS = ROOT / "mods"
BIN = ROOT / "tools" / "bin"
UPSCAYL = ROOT.parent / "upscayl-2.15.0-win" / "resources"

TEX = MODS / "textures"
MANIFEST = TEX / "manifest.json"
UI_DIRS = ("gui/", "guipackages/", "xprmedia/", "saveimages/", "media/")


def log(msg):
    print(msg, flush=True)


def slug(text, limit=90):
    s = re.sub(r"[^A-Za-z0-9_-]+", "_", text).strip("_")
    return s[-limit:]


def game_sources():
    """Yield (archive rel path or '', entry name, bytes) for all archives and loose .xpr files."""
    for rel in archive.find_archives(GAME):
        for info, data in archive.iter_entries(GAME / rel):
            yield rel, info.filename, data
    for p in sorted(GAME.glob("*.xpr")):
        yield "", p.name, p.read_bytes()


def entry_bytes(arc, entry):
    """Current bytes of an entry: the override if one exists, else the shipped file."""
    ov = MODS / "overrides" / arc / entry if arc else MODS / "overrides" / entry
    if ov.exists():
        return ov.read_bytes()
    if not arc:
        return (GAME / entry).read_bytes()
    import zipfile
    with zipfile.ZipFile(GAME / arc) as z:
        return z.read(entry)


# --------------------------------------------------------------------------- unpack / decompile

def cmd_unpack(a):
    out = MODS / "extracted"
    n = 0
    for rel in archive.find_archives(GAME):
        if a.filter and a.filter.lower() not in rel.lower():
            continue
        for info, data in archive.iter_entries(GAME / rel):
            dest = out / rel / info.filename
            if dest.exists() and not a.force:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            n += 1
    log(f"extracted {n} files into {out}")


def _decompile_one(job):
    rel, name, data, dest = job
    with tempfile.NamedTemporaryFile(suffix=".luac", delete=False) as f:
        f.write(lua50beta.beta_to_final(data))
        tmp = f.name
    try:
        r = subprocess.run(["java", "-jar", str(BIN / "unluac.jar"), tmp],
                           capture_output=True, text=True, encoding="latin-1")
    finally:
        os.unlink(tmp)
    if r.returncode:
        return rel, name, (r.stderr.strip().splitlines() or ["unluac failed"])[0]
    source = r.stdout if r.stdout.strip() else "-- (empty script)\n"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(lua50beta.restore_wide_literals(source), encoding="latin-1", newline="\r\n")
    return None


def cmd_decompile(a):
    out = MODS / "source"
    jobs = []
    for rel, name, data in game_sources():
        if not rel or not lua50beta.is_beta_chunk(data):
            continue
        if a.filter and a.filter.lower() not in (rel + "/" + name).lower():
            continue
        dest = out / rel / name
        if dest.exists() and not a.force:
            continue
        jobs.append((rel, name, data, dest))
    log(f"decompiling {len(jobs)} scripts ...")
    with ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
        failures = [r for r in pool.map(_decompile_one, jobs) if r]
    for rel, name, err in failures:
        log(f"  FAILED {rel}/{name}: {err}")
    log(f"wrote {len(jobs) - len(failures)} source files into {out}")


# --------------------------------------------------------------------------- textures

def texture_kind(arc, entry, name):
    low = (arc + "/" + entry).lower()
    if "font" in entry.lower():
        return "font"
    if "lightmap" in low:
        return "lightmap"
    if "normal" in name.lower():
        return "normal"
    if not arc or low.startswith(UI_DIRS):
        return "ui"
    return "world"


TMAP_BLOCK = re.compile(r'\{([^{}]*\bName = "[^"]*"[^{}]*)\}')


def tmap_path(arc, entry):
    """Decompiled .tmap that describes a .pgf's textures (same name), or None."""
    if not entry.lower().endswith(".pgf"):
        return None
    for p in (MODS / "overrides" / arc, MODS / "source" / arc):
        stem = (p / entry).with_suffix("")
        for cand in stem.parent.glob(stem.name + ".*") if stem.parent.exists() else []:
            if cand.suffix.lower() == ".tmap":
                return cand
    return None


def tmap_names(arc, entry):
    """Texture names in pgf order, from the matching .tmap (needs `decompile` first)."""
    p = tmap_path(arc, entry)
    if not p:
        return []
    return [re.search(r'\bName = "([^"]*)"', b).group(1) for b in TMAP_BLOCK.findall(p.read_text(encoding="latin-1"))]


def load_manifest():
    if not MANIFEST.exists():
        sys.exit("no texture manifest yet - run tex-export first")
    return json.loads(MANIFEST.read_text())


def cmd_tex_export(a):
    out = TEX / "original"
    out.mkdir(parents=True, exist_ok=True)
    manifest = {}
    skipped = {}
    if not (MODS / "source").exists():
        log("note: run `decompile` first to name character/object textures from their .tmap files")
    for rel, name, data in game_sources():
        c = xt.open_container(name, data)
        if not c:
            continue
        names = tmap_names(rel, name) if c.kind == "pgf" else []
        for t in c.textures:
            if not t.supported:
                label = t.format_name + (" cube" if t.cube else "")
                skipped[label] = skipped.get(label, 0) + 1
                continue
            level0 = c.level0(t)
            key = t.key(level0)
            use = {"archive": rel, "entry": name, "index": t.index, "container": c.kind}
            if key in manifest:
                manifest[key]["uses"].append(use)
                continue
            label = names[t.index] if t.index < len(names) else Path(name).with_suffix("").as_posix() + f"_{t.index}"
            base = f"{key}__{slug((Path(rel).stem + '_' if rel else '') + label)}"
            rgba = xt.decode_rgba(t, level0)
            path = out / (base + ".png")
            if not path.exists() or a.force:
                Image.fromarray(rgba, "RGBA").save(path, optimize=False)
            manifest[key] = {
                "name": base, "width": t.width, "height": t.height,
                "format": t.format_name, "mips": t.mips,
                "alpha": bool((rgba[..., 3] < 255).any()),
                "kind": texture_kind(rel, name, label), "uses": [use],
            }
    if MANIFEST.exists():                  # keep what tex-misses added
        for key, m in json.loads(MANIFEST.read_text()).items():
            if m.get("runtime") and key not in manifest:
                manifest[key] = m
    MANIFEST.write_text(json.dumps(manifest, indent=1))
    kinds = {}
    for m in manifest.values():
        kinds[m["kind"]] = kinds.get(m["kind"], 0) + 1
    log(f"exported {len(manifest)} unique textures to {out}  {kinds}")
    if skipped:
        log(f"not exported (unsupported layouts): {skipped}")


def cmd_tex_misses(a):
    """Textures the recomp drew that the pack lacks: the runtime dumps their
    top mips (RECOMP_TEXTURE_PACK_DUMP=<dir>, one <key>.raw each, the key
    being the pack's own), and this decodes them into textures/original with
    manifest entries, so tex-upscale and tex-pack treat them like the rest."""
    src = Path(a.dir)
    out = TEX / "original"
    out.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest() if MANIFEST.exists() else {}
    added, skipped = 0, []
    for raw in sorted(src.glob("*.raw")):
        key = raw.stem
        m = re.fullmatch(r"([0-9a-f]{8})_(\d+)x(\d+)_([0-9a-f]{2})", key)
        if not m:
            continue
        w, h, code = int(m[2]), int(m[3]), int(m[4], 16)
        if key in manifest and not a.force:
            continue
        if min(w, h) < 4 or w & (w - 1) or h & (h - 1):
            skipped.append(key)            # 1x1 fills, non-power-of-two
            continue
        fmt = (code << 8) | (1 << 16) | ((w.bit_length() - 1) << 20) | ((h.bit_length() - 1) << 24)
        t = xt.Texture(struct.pack("<5I", xt.COMMON_TYPE_TEXTURE, 0, 0, fmt, 0), 0)
        if not t.supported or t.kind == "lin":
            skipped.append(key)
            continue
        data = raw.read_bytes()
        if len(data) != t.level_size(0) or t.key(data) != key:
            skipped.append(key)
            continue
        rgba = xt.decode_rgba(t, data)
        name = f"{key}__runtime"
        Image.fromarray(rgba, "RGBA").save(out / (name + ".png"))
        manifest[key] = {
            "name": name, "width": w, "height": h, "format": t.format_name,
            "mips": 1, "alpha": bool((rgba[..., 3] < 255).any()),
            "kind": a.kind, "uses": [], "runtime": True,
        }
        added += 1
    MANIFEST.write_text(json.dumps(manifest, indent=1))
    log(f"added {added} runtime textures to {out} as <key>__runtime.png")
    if skipped:
        log(f"skipped (blank, unsupported format or changed): {', '.join(skipped)}")


def bleed_transparent(rgba):
    """Fill RGB under fully transparent pixels from their neighbours, so the
    upscaler does not smear dark fringes into cut-out edges."""
    rgb = rgba[..., :3].astype(np.float32)
    filled = rgba[..., 3] > 0
    if filled.all() or not filled.any():
        return rgba[..., :3].copy()
    acc = rgb * filled[..., None]
    for _ in range(64):
        s = np.zeros_like(rgb)
        n = np.zeros(filled.shape, np.float32)
        for shift in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            s += np.roll(acc * filled[..., None], shift, (0, 1))
            n += np.roll(filled, shift, (0, 1))
        new = ~filled & (n > 0)
        if not new.any():
            break
        acc[new] = s[new] / n[new][:, None]
        filled |= new
    acc[~filled] = rgb[rgba[..., 3] > 0].mean(0)
    return np.clip(acc + 0.5, 0, 255).astype(np.uint8)


def _fit(img, max_size):
    w, h = img.size
    if max(w, h) <= max_size:
        return img
    s = max_size / max(w, h)
    return img.resize((max(1, round(w * s)), max(1, round(h * s))), Image.LANCZOS)


def cmd_tex_upscale(a):
    manifest = load_manifest()
    src_dir, out_dir = TEX / "original", TEX / "upscaled"
    out_dir.mkdir(parents=True, exist_ok=True)
    kinds = set(a.kinds.split(","))
    ai, plain = [], []
    for key, m in manifest.items():
        if m["kind"] not in kinds:
            continue
        if a.filter and a.filter.lower() not in m["name"].lower():
            continue
        if (out_dir / (m["name"] + ".png")).exists() and not a.force:
            continue
        small = min(m["width"], m["height"]) < a.min_size
        (plain if small or m["kind"] == "lightmap" else ai).append(m)
    log(f"{len(ai)} textures for {a.model}, {len(plain)} lightmaps/tiny textures for plain Lanczos")

    for m in plain:                                   # lightmaps are smooth gradients: AI adds noise
        img = Image.open(src_dir / (m["name"] + ".png"))
        img = img.resize((img.width * a.scale, img.height * a.scale), Image.LANCZOS)
        _fit(img, a.max_size).save(out_dir / (m["name"] + ".png"))

    if not ai:
        return
    exe = Path(a.upscayl) / "bin" / "upscayl-bin.exe"
    models = Path(a.upscayl) / "models"
    if not (models / f"{a.model}.param").exists():
        sys.exit(f"model {a.model} not in {models}: " + ", ".join(p.stem for p in models.glob("*.param")))
    work = TEX / "_work"
    for batch_start in range(0, len(ai), a.batch):
        batch = ai[batch_start:batch_start + a.batch]
        shutil.rmtree(work, ignore_errors=True)
        (work / "in").mkdir(parents=True)
        (work / "out").mkdir()
        pads = {}
        for m in batch:
            rgba = np.asarray(Image.open(src_dir / (m["name"] + ".png")).convert("RGBA"))
            rgb = bleed_transparent(rgba) if m["alpha"] else rgba[..., :3]
            # pad so tiling textures keep seamless edges and borders get context
            pad = max(2, min(16, rgb.shape[0] // 4, rgb.shape[1] // 4))
            mode = "edge" if m["kind"] == "ui" else "wrap"
            Image.fromarray(np.pad(rgb, ((pad, pad), (pad, pad), (0, 0)), mode=mode)).save(work / "in" / (m["name"] + ".png"))
            pads[m["name"]] = pad
        log(f"upscaling {batch_start + 1}-{batch_start + len(batch)} of {len(ai)} ...")
        cmd = [str(exe), "-i", str(work / "in"), "-o", str(work / "out"), "-m", str(models),
               "-n", a.model, "-s", str(a.scale), "-f", "png"]
        if a.tile:
            cmd += ["-t", str(a.tile)]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode:
            sys.exit(f"upscayl-bin failed ({r.returncode}):\n{r.stderr[-2000:]}")
        for m in batch:
            up = work / "out" / (m["name"] + ".png")
            if not up.exists():
                log(f"  no output for {m['name']}")
                continue
            p = pads[m["name"]] * a.scale
            rgb = np.asarray(Image.open(up).convert("RGB"))[p:-p, p:-p]
            src = Image.open(src_dir / (m["name"] + ".png")).convert("RGBA")
            size = (src.width * a.scale, src.height * a.scale)
            if rgb.shape[:2] != (size[1], size[0]):
                rgb = np.asarray(Image.fromarray(rgb).resize(size, Image.LANCZOS))
            if m["kind"] == "normal":                 # AI output drifts off unit length
                v = rgb.astype(np.float32) / 127.5 - 1.0
                v /= np.maximum(np.linalg.norm(v, axis=2, keepdims=True), 1e-6)
                rgb = np.clip((v + 1.0) * 127.5 + 0.5, 0, 255).astype(np.uint8)
            if m["alpha"]:
                alpha = np.asarray(src.getchannel("A").resize(size, Image.LANCZOS))
                img = Image.fromarray(np.dstack([rgb, alpha]), "RGBA")
            else:
                img = Image.fromarray(rgb, "RGB")
            _fit(img, a.max_size).save(out_dir / (m["name"] + ".png"))
    shutil.rmtree(work, ignore_errors=True)
    log(f"done: {out_dir}")


_gpu = None


def _texconv_gpu():
    """Adapter index for BC6H/BC7 compression: prefer a discrete GPU over Intel graphics."""
    global _gpu
    if _gpu is None:
        _gpu = []
        with tempfile.TemporaryDirectory() as d:
            probe = Path(d) / "probe.png"
            Image.new("RGBA", (4, 4)).save(probe)
            for i in range(4):
                r = subprocess.run([str(BIN / "texconv.exe"), "-nologo", "-y", "-gpu", str(i), "-f", "BC7_UNORM",
                                    "-o", d, str(probe)], capture_output=True, text=True, errors="replace")
                m = re.search(r'DirectCompute [\d.]+ on "([^"]+)"', r.stdout)
                if r.returncode or not m:
                    break
                if "intel" not in m.group(1).lower():
                    _gpu = ["-gpu", str(i)]
                    log(f"texconv: compressing on {m.group(1)}")
                    break
    return _gpu


def _texconv(files, out_dir, fmt, mips):
    """Run texconv over a list of files; returns nothing, raises on failure."""
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write("\n".join(str(p) for p in files))
        lst = f.name
    gpu = _texconv_gpu() if fmt.startswith(("BC6", "BC7")) else []
    try:
        subprocess.run([str(BIN / "texconv.exe"), "-nologo", "-y", "--ignore-srgb", *gpu, "-f", fmt, "-m", str(mips),
                        "-o", str(out_dir), "-flist", lst], check=True, stdout=subprocess.DEVNULL)
    finally:
        os.unlink(lst)


def _pack_source(m):
    for d in (TEX / "edit", TEX / "upscaled"):
        p = d / (m["name"] + ".png")
        if p.exists():
            return p
    return None


def cmd_tex_pack(a):
    manifest = load_manifest()
    pack = Path(a.out)
    pack.mkdir(parents=True, exist_ok=True)
    todo = []
    for key, m in manifest.items():
        src = _pack_source(m)
        dest = pack / f"{key}.dds"
        if src and (a.force or not dest.exists() or dest.stat().st_mtime < src.stat().st_mtime):
            todo.append((key, m, src))
    log(f"compressing {len(todo)} textures to {a.format} ...")
    tmp = TEX / "_pack"
    for i in range(0, len(todo), 200):
        chunk = todo[i:i + 200]
        shutil.rmtree(tmp, ignore_errors=True)
        _texconv([s for _, _, s in chunk], tmp, a.format, 0)
        for key, m, src in chunk:
            (tmp / (src.stem + ".dds")).replace(pack / f"{key}.dds")
        log(f"  {min(i + 200, len(todo))}/{len(todo)}")
    shutil.rmtree(tmp, ignore_errors=True)
    index = {}
    for key, m in manifest.items():
        src = _pack_source(m)
        if src and (pack / f"{key}.dds").exists():
            w, h = Image.open(src).size
            index[key] = {"name": m["name"], "original": [m["width"], m["height"], m["format"]], "replacement": [w, h],
                          "source": src.parent.name}
    (pack / "index.json").write_text(json.dumps(index, indent=1))
    mb = sum(p.stat().st_size for p in pack.glob("*.dds")) / 2**20
    log(f"pack: {len(index)} textures, {mb:.0f} MB in {pack}")
    _write_tails(pack, index)


def _write_tails(pack, index):
    """tails.txt: for each DXT texture in the pack, `<crc32 of its top mip
    past the first 16 bytes>_<w>x<h>_<fmt> <key>`. Amped 2 draws some menu
    and loading-screen textures after freeing them, and the pool's free-list
    header has then replaced their first block; the runtime finds the
    replacement through this instead (xboxrecomp nv2a_d3d11.c, pack_load)."""
    lines = []
    for rel, name, data in game_sources():
        c = xt.open_container(name, data)
        if not c:
            continue
        for t in c.textures:
            if not t.supported or t.kind != "dxt":
                continue
            level0 = c.level0(t)
            key = t.key(level0)
            if key in index and len(level0) > 64:
                tail = zlib.crc32(level0[16:]) & 0xFFFFFFFF
                lines.append(f"{tail:08x}_{t.width}x{t.height}_{t.code:02x} {key}")
    lines = sorted(set(lines))
    (pack / "tails.txt").write_text("\n".join(lines) + "\n")
    log(f"tails.txt: {len(lines)} DXT textures")


def _pow2(n):
    return 1 << max(0, round(np.log2(max(n, 1))))


def _encode_for(tex, img: Image.Image):
    """Encode an image in the texture's own Xbox format; returns (format dword, data)."""
    w, h = _pow2(img.width), _pow2(img.height)
    if (w, h) != img.size:
        log(f"    resizing {img.size} -> {(w, h)} (Xbox textures must be powers of two)")
        img = img.resize((w, h), Image.LANCZOS)
    if max(w, h) > 4096:
        raise SystemExit("textures larger than 4096 are not supported by the NV2A")
    # keep the original's smallest mip size, so distant surfaces filter the same way
    smallest = max(max(tex.width, tex.height) >> (tex.mips - 1), 1)
    mips = max(1, (max(w, h) // smallest).bit_length()) if max(w, h) >= smallest else 1
    fmt = tex.format & ~(0xFFF << 16)
    fmt |= (mips << 16) | ((w.bit_length() - 1) << 20) | ((h.bit_length() - 1) << 24)
    if tex.kind == "dxt":
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "in.png"
            img.convert("RGBA").save(src)
            _texconv([src], Path(d), xt.DXT_TEXCONV[tex.code], mips)
            dds = (Path(d) / "in.dds").read_bytes()
        return fmt, dds[128:]
    if tex.format_name in ("A8R8G8B8", "X8R8G8B8"):
        out = bytearray()
        level = img.convert("RGBA")
        for l in range(mips):
            lw, lh = max(w >> l, 1), max(h >> l, 1)
            px = np.asarray(level.resize((lw, lh), Image.LANCZOS) if l else level)
            bgra = px[..., [2, 1, 0, 3]]
            out += xt.swizzle(bgra).tobytes()
        return fmt, bytes(out)
    raise SystemExit(f"injecting {tex.format_name} textures is not supported")


def cmd_tex_inject(a):
    manifest = load_manifest()
    src_dir = TEX / "inject"
    pngs = sorted(src_dir.glob("*.png")) if src_dir.exists() else []
    if not pngs:
        sys.exit(f"put edited PNGs (keeping their exported file names) into {src_dir}")
    by_entry = {}
    if a.into:
        # explicit target (e.g. a copy you made in mods/overrides under a new name):
        # match the PNGs against the textures that entry holds right now
        m = re.match(r"(.+?\.(?:gfx|res))/(.+)$", a.into.replace("\\", "/"), re.I)
        if not m:
            sys.exit("--into takes <archive>/<entry>, e.g. Characters/boarder/LoResCharacter.gfx/skates/xpr/My_skates.xpr")
        arc, entry = m.groups()
        c = xt.open_container(entry, entry_bytes(arc, entry))
        keys = {t.key(c.level0(t)): t.index for t in c.textures if t.supported} if c else {}
        for p in pngs:
            if p.stem.split("__")[0] in keys:
                by_entry.setdefault((arc, entry), []).append((keys[p.stem.split("__")[0]], p))
    for p in pngs if not a.into else []:
        key = p.stem.split("__")[0]
        if key not in manifest:
            log(f"  {p.name}: unknown texture key, skipped")
            continue
        for use in manifest[key]["uses"]:
            if a.filter and a.filter.lower() not in (use["archive"] + "/" + use["entry"]).lower():
                continue
            by_entry.setdefault((use["archive"], use["entry"]), []).append((use["index"], p))
    if not by_entry:
        sys.exit("no PNG in the inject folder matches a texture in the target")
    for (arc, entry), items in sorted(by_entry.items()):
        data = entry_bytes(arc, entry)
        c = xt.open_container(entry, data)
        if not c or not c.rebuildable:
            log(f"  {arc}/{entry}: this container can't be rebuilt, skipped")
            continue
        repl = {}
        for index, png in items:
            tex = c.textures[index]
            repl[index] = _encode_for(tex, Image.open(png))
        new = c.rebuild(repl)
        dest = MODS / "overrides" / arc / entry if arc else MODS / "overrides" / entry
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(new)
        log(f"  {arc}/{entry}: {len(repl)} texture(s), {len(data) / 2**20:.2f} -> {len(new) / 2**20:.2f} MB")
        _sync_tmap(arc, entry, repl)
    log("now run: repack")


def _sync_tmap(arc, entry, repl):
    """Rewrite Width/Height/MipLevels in the .tmap that describes a rebuilt .pgf.

    The override is written as Lua source; the game's loader accepts source
    as well as bytecode (several shipped data files are plain text)."""
    p = tmap_path(arc, entry)
    if not p:
        if entry.lower().endswith(".pgf") and arc.lower().startswith(("characters/", "objects/")):
            log(f"    warning: no decompiled .tmap for {entry}; run `decompile` and inject again")
        return
    src_root = MODS / "overrides" / arc if str(p).startswith(str(MODS / "overrides")) else MODS / "source" / arc
    rel = p.relative_to(src_root)
    text = p.read_text(encoding="latin-1")
    blocks = list(TMAP_BLOCK.finditer(text))
    for index, (fmt, _) in sorted(repl.items(), reverse=True):   # back to front keeps offsets valid
        if index >= len(blocks):
            continue
        w, h, mips = 1 << ((fmt >> 20) & 0xF), 1 << ((fmt >> 24) & 0xF), (fmt >> 16) & 0xF
        b = blocks[index]
        body = re.sub(r"\bWidth = \d+", f"Width = {w}", b.group(1))
        body = re.sub(r"\bHeight = \d+", f"Height = {h}", body)
        body = re.sub(r"\bMipLevels = \d+", f"MipLevels = {mips}", body)
        text = text[:b.start(1)] + body + text[b.end(1):]
    out = MODS / "overrides" / arc / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="latin-1", newline="")
    log(f"    updated {rel.as_posix()}")


# --------------------------------------------------------------------------- repack / install

def cmd_repack(a):
    ov_root = MODS / "overrides"
    build = MODS / "build" / "game"
    if not ov_root.exists():
        sys.exit(f"nothing to do: {ov_root} does not exist")
    for rel in archive.find_archives(GAME):
        d = ov_root / rel
        if not d.is_dir():
            continue
        overrides = {p.relative_to(d).as_posix(): p.read_bytes() for p in d.rglob("*") if p.is_file()}
        replaced, added = archive.repack(GAME / rel, overrides, build / rel)
        log(f"{rel}: {len(replaced)} replaced, {len(added)} added")
        for name in added:
            log(f"    + {name}")
    for p in GAME.glob("*.xpr"):
        if (ov_root / p.name).is_file():
            (build / p.name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ov_root / p.name, build / p.name)
            log(f"{p.name}: replaced")
    log(f"built archives are in {build}; the game reads them from there (ini [Game] Mods=1,"
        " the default) - install is only for runtimes without the overlay")


def cmd_install(a):
    build = MODS / "build" / "game"
    backup = MODS / "backup" / "game"
    files = [p for p in build.rglob("*") if p.is_file()] if build.exists() else []
    if not files:
        sys.exit("nothing built - run repack first")
    for p in files:
        rel = p.relative_to(build)
        target, saved = GAME / rel, backup / rel
        if target.exists() and not saved.exists():
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, saved)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, target)
        log(f"installed {rel.as_posix()}")
    log(f"originals are backed up in {backup}")


def cmd_restore(a):
    backup = MODS / "backup" / "game"
    files = [p for p in backup.rglob("*") if p.is_file()] if backup.exists() else []
    for p in files:
        rel = p.relative_to(backup)
        shutil.copy2(p, GAME / rel)
        log(f"restored {rel.as_posix()}")
    if not files:
        log("no backups to restore")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("unpack"); p.set_defaults(fn=cmd_unpack)
    p.add_argument("--filter", help="only archives whose path contains this")
    p.add_argument("--force", action="store_true")

    p = sub.add_parser("decompile"); p.set_defaults(fn=cmd_decompile)
    p.add_argument("--filter", help="only scripts whose archive/entry path contains this")
    p.add_argument("--force", action="store_true")

    p = sub.add_parser("tex-export"); p.set_defaults(fn=cmd_tex_export)
    p.add_argument("--force", action="store_true", help="rewrite PNGs that already exist")

    p = sub.add_parser("tex-misses"); p.set_defaults(fn=cmd_tex_misses)
    p.add_argument("dir", help="the runtime's RECOMP_TEXTURE_PACK_DUMP folder of <key>.raw files")
    p.add_argument("--kind", default="world", help="kind for the new entries (world, ui, ...)")
    p.add_argument("--force", action="store_true", help="redo keys already in the manifest")

    p = sub.add_parser("tex-upscale"); p.set_defaults(fn=cmd_tex_upscale)
    p.add_argument("--model", default="ultrasharp-4x", help="Upscayl model name (see upscayl resources/models)")
    p.add_argument("--scale", type=int, default=4, choices=(2, 3, 4))
    p.add_argument("--kinds", default="world,ui,normal,lightmap", help="comma list of world, ui, normal, lightmap, font")
    p.add_argument("--min-size", type=int, default=16, help="smaller textures get plain Lanczos")
    p.add_argument("--max-size", type=int, default=4096, help="clamp the upscaled result to this")
    p.add_argument("--filter", help="only textures whose name contains this")
    p.add_argument("--batch", type=int, default=250, help="textures per Upscayl run")
    p.add_argument("--tile", type=int, default=0, help="Upscayl tile size (lower it if the GPU runs out of memory)")
    p.add_argument("--upscayl", default=str(UPSCAYL), help="Upscayl resources folder")
    p.add_argument("--force", action="store_true")

    p = sub.add_parser("tex-pack"); p.set_defaults(fn=cmd_tex_pack)
    p.add_argument("--format", default="BC7_UNORM", help="texconv format, e.g. BC7_UNORM, BC3_UNORM, BC1_UNORM")
    p.add_argument("--out", default=str(MODS / "texture_pack"))
    p.add_argument("--force", action="store_true")

    p = sub.add_parser("tex-inject"); p.set_defaults(fn=cmd_tex_inject)
    p.add_argument("--filter", help="only write into archive/entry paths containing this")
    p.add_argument("--into", help="write only into this <archive>/<entry> (e.g. a renamed copy in mods/overrides)")

    sub.add_parser("repack").set_defaults(fn=cmd_repack)
    sub.add_parser("install").set_defaults(fn=cmd_install)
    sub.add_parser("restore").set_defaults(fn=cmd_restore)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
