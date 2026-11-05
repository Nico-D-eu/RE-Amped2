"""Sharp fonts: the game's font atlases, upscaled on the player's PC.

    python tools/mods/font_pack.py [--game DIR] [--out DIR] [--scale 4]

Game data is never committed, so the sharp fonts are a recipe too. This reads
every font atlas from the player's own copy of the game (the GUI fonts in
GuiPackages/*.ruirr Fonts/*.xpr, and the XDK fonts Media/font.xpr and
XprMedia/Font.xpr), scales it up without AI, and writes it as a texture pack:
<out>/textures/<key>.dds, the key being the original's (tools/assets,
`tex-pack`), so the runtime's RECOMP_TEXTURE_PACK swaps it in wherever the
game draws that atlas.

The glyphs are in the alpha channel. Plain Lanczos would blur their edges at
4x, so the alpha is scaled with Lanczos and then pulled to a sharp edge
(a smoothstep about the glyph outline, a little over one output pixel wide);
the colour is scaled with Lanczos after filling the transparent pixels from
their neighbours, so no dark fringes show at the glyph edges. The output is
uncompressed 32-bit DDS with a full mip chain: both renderers load it, and no
texture compressor is needed (about 90 MB for all fonts at 4x).

Needs numpy and pillow (the installer's menu-tool packages).
"""
import argparse
import struct
import sys
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "assets"))
import xboxtex as xt  # noqa: E402

LOOSE_FONTS = ("Media/Media.gfx", "XprMedia/XprMedia.gfx")


def font_atlases(game: Path):
    """Yield (where, Texture, top mip bytes) for every font atlas on the disc."""
    archives = sorted(game.glob("GuiPackages/*.ruirr")) + [game / a for a in LOOSE_FONTS]
    for arc in archives:
        if not arc.is_file():
            continue
        with zipfile.ZipFile(arc) as z:
            for name in z.namelist():
                if "font" not in name.lower() or not name.lower().endswith(".xpr"):
                    continue
                c = xt.open_container(name, z.read(name))
                for t in (c.textures if c else []):
                    if t.supported and not t.cube:
                        yield f"{arc.name}/{name}", t, c.level0(t)


def bleed(rgba):
    """RGB under transparent pixels filled from their neighbours."""
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


def sharpen_up(rgba, scale):
    h, w = rgba.shape[:2]
    size = (w * scale, h * scale)
    rgb = np.asarray(Image.fromarray(bleed(rgba)).resize(size, Image.LANCZOS))
    a = np.asarray(Image.fromarray(rgba[..., 3]).resize(size, Image.LANCZOS)).astype(np.float32) / 255
    # The outline sits at half coverage. Lanczos spreads it over about
    # `scale` output pixels; a smoothstep over +-0.6/scale of that brings it
    # back to a bit more than one, which stays smooth when the game scales
    # the text down again.
    edge = min(0.5, 1.2 / scale)
    t = np.clip((a - (0.5 - edge)) / (2 * edge), 0, 1)
    a = t * t * (3 - 2 * t)
    a[a < 0.02] = 0
    return np.dstack([rgb, (a * 255 + 0.5).astype(np.uint8)])


def dds_bgra(rgba):
    """Uncompressed 32-bit DDS (B8G8R8A8) with a full mip chain."""
    h, w = rgba.shape[:2]
    levels = [rgba]
    while levels[-1].shape[0] > 1 or levels[-1].shape[1] > 1:
        lh, lw = levels[-1].shape[:2]
        levels.append(np.asarray(Image.fromarray(levels[-1], "RGBA").resize(
            (max(1, lw // 2), max(1, lh // 2)), Image.BOX)))
    flags = 0x1 | 0x2 | 0x4 | 0x8 | 0x1000 | 0x20000      # caps, h, w, pitch, pixelformat, mips
    header = struct.pack("<4s7I44x", b"DDS ", 124, flags, h, w, w * 4, 0, len(levels))
    pf = struct.pack("<8I", 32, 0x41, 0, 32, 0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000)
    caps = struct.pack("<4I4x", 0x1000 | 0x8 | 0x400000, 0, 0, 0)
    body = b"".join(np.ascontiguousarray(l[..., [2, 1, 0, 3]]).tobytes() for l in levels)
    return header + pf + caps + body


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--game", type=Path, default=ROOT / "game", help="the game's files (default: game/)")
    ap.add_argument("--out", type=Path, default=ROOT / "mods" / "packs" / "fonts",
                    help="the pack folder to write (default: mods/packs/fonts)")
    ap.add_argument("--scale", type=int, default=4, choices=(2, 3, 4))
    a = ap.parse_args()

    tex = a.out / "textures"
    tex.mkdir(parents=True, exist_ok=True)
    done = set()
    for where, t, level0 in font_atlases(a.game):
        key = t.key(level0)
        if key in done:
            continue
        done.add(key)
        rgba = xt.decode_rgba(t, level0)
        (tex / f"{key}.dds").write_bytes(dds_bgra(sharpen_up(rgba, a.scale)))
        print(f"{key}  {t.width}x{t.height} {t.format_name} -> x{a.scale}  ({where})", flush=True)
    if not done:
        sys.exit(f"no font atlases found under {a.game}")
    print(f"{len(done)} fonts in {tex}", flush=True)


if __name__ == "__main__":
    main()
