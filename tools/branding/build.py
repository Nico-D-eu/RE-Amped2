"""RE-Amped2 branding: build the game's replacement textures, the player pack and the
installer art from the art masters.

The masters are local (branding/drafts/, git-ignored: the user's art and 4x
upscales): reamped2_wordmark_full.png and reamped2_wordmark_noglow_full.png
(the logo with and without glow, transparent), and work/banner_4x.png,
work/badge_4x.png, work/course_banner_clean.png. Edit a master, then from amped2/:

    py -3.10 tools/branding/build.py
    py -3.10 tools/assets/amped_assets.py tex-pack

It writes PNGs into mods/textures/edit/ under the original texture names
(title logo ampedLogo, Logo_Amped2, course banner Banneramped2, the four boot
splashes, the level loading screen) and previews plus reamped2.ico into
branding/drafts/. branding/RE-Amped2.ico (tracked) is a copy of that .ico.
"""
import numpy as np, cv2
from pathlib import Path
from PIL import Image

AMP = Path(__file__).resolve().parents[2]
OUT = AMP / "branding" / "drafts"
EDIT = AMP / "mods" / "textures" / "edit"
OUT.mkdir(parents=True, exist_ok=True)
WORK = OUT / "work"           # 4x upscales of the source art, the cleaned course banner
EDIT.mkdir(parents=True, exist_ok=True)

wm = Image.open(OUT / "reamped2_wordmark_full.png")            # with synthetic glow
wm_ng = Image.open(OUT / "reamped2_wordmark_noglow_full.png")  # same bbox, no glow


def place(canvas, logo, box):
    """Fit logo into box (x0, y0, x1, y1), centred, keeping its aspect."""
    x0, y0, x1, y1 = box
    s = min((x1 - x0) / logo.width, (y1 - y0) / logo.height)
    lg = logo.resize((round(logo.width * s), round(logo.height * s)), Image.LANCZOS)
    pos = (round((x0 + x1 - lg.width) / 2), round((y0 + y1 - lg.height) / 2))
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    layer.paste(lg, pos)
    return Image.alpha_composite(canvas.convert("RGBA"), layer)


# 1. wordmark masters
place(Image.new("RGBA", (2048, 1024), (0, 0, 0, 0)), wm, (40, 40, 2008, 984)).save(OUT / "reamped2_wordmark.png")

# 2. ampedLogo (512x256, alpha). The old logo filled the full width at y 64-191 (4:1); ours is taller,
#    so keep "amped" at about the old width and let "RE-" rise above it.
logo = place(Image.new("RGBA", (2048, 1024), (0, 0, 0, 0)), wm, (0, 0, 2048, 790))
logo.save(EDIT / "11078467_512x256_0e__Textures_ampedLogo_0.png")
logo.save(OUT / "game_ampedLogo_2048x1024.png")

# 3. Logo_Amped2 (128x128, opaque white; the old logo sat at x 9-117, y 53-78)
small = place(Image.new("RGBA", (512, 512), (255, 255, 255, 255)), wm_ng, (36, 150, 476, 362)).convert("RGB")
small.save(EDIT / "2db08caa_128x128_0e__Textures_Logo_Amped2_0.png")
small.save(OUT / "game_Logo_Amped2_512.png")

# 4. course banner (256x256 world texture): old logo painted out by LaMa, new wordmark on top
cb = place(Image.open(WORK / "course_banner_clean.png"), wm, (262, 440, 772, 690)).convert("RGB")
cb.save(EDIT / "c66a31ba_256x256_0e__Objects_Banneramped2_0.png")
cb.save(OUT / "game_course_banner_1024.png")

# 5. boot splash (512x512, drawn 4:3 pillarboxed). Composed at 4:3 from the banner art, stored square.
ban = Image.open(WORK / "banner_4x.png").convert("RGB")       # 8000x1984
h = ban.height; w = round(h * 4 / 3); cx = 962 * 4
splash43 = ban.crop((cx - w // 2, 0, cx - w // 2 + w, h))
splash43.save(OUT / "reamped2_splash_4x3.png")
sq = splash43.resize((2048, 2048), Image.LANCZOS)
sq.save(OUT / "game_splash_2048_stored.png")
for name in ("2c4ed89d_512x512_0c__splash_eng_0", "4550032c_512x512_0c__splash_fre_0",
             "2907e9d5_512x512_0c__splash_ger_0", "437650b8_512x512_0c__splash_jan_0"):
    sq.save(EDIT / (name + ".png"))

# 5b. loading screen before a level: Loading_Background is drawn stretched to the full 16:9 screen,
#     so it gets a 16:9 crop of the banner; the controller pictures on top of it are blanked so only
#     the game's own "LOADING ..." text is drawn over the art.
#     The art is shown at 82% and anchored to the top, so the game's "LOADING ..." (lower centre)
#     falls below the logo; the strip under the art is the banner's dark base, mirrored and darkened.
fh = round(h / 0.82); w = round(fh * 16 / 9)
loading169 = Image.new("RGB", (w, fh))
loading169.paste(ban.crop((cx - w // 2, 0, cx - w // 2 + w, h)), (0, 0))
ext = fh - h
base = np.asarray(ban.crop((cx - w // 2, h - ext, cx - w // 2 + w, h)))[::-1].astype(np.float32)
base *= np.linspace(0.85, 0.35, ext)[:, None, None]
loading169.paste(Image.fromarray(base.astype(np.uint8)), (0, h))
loading169.save(OUT / "reamped2_loading_16x9.png")
loading169.resize((2048, 2048), Image.LANCZOS).save(EDIT / "5e30a78c_512x512_0e__Textures_Loading_Background_0.png")
for name in ("49571dfc_512x512_0e__Textures_LoadingScreen2_0", "2ca17dab_512x512_0e__Textures_Loading_Controller_0",
             "7556167a_512x512_0e__Textures_Loading_Controls_0"):
    Image.new("RGBA", (64, 64), (0, 0, 0, 0)).save(EDIT / (name + ".png"))

# 6. badge: cut the circle out of the 4x upscale (the JPG's checkerboard is baked in)
bd = np.asarray(Image.open(WORK / "badge_4x.png").convert("RGB"))
yy, xx = np.mgrid[:bd.shape[0], :bd.shape[1]].astype(np.float32)
cx = cy = (511.5 + 0.5) * 4 - 0.5
r = np.hypot(xx - cx, yy - cy)
a = np.clip((497.5 * 4 - r) / 3 + 0.5, 0, 1)
badge = Image.fromarray(np.dstack([bd, (a * 255).astype(np.uint8)]))
badge = badge.crop((round(cx - 2000), round(cy - 2000), round(cx + 2000), round(cy + 2000)))
badge.resize((2048, 2048), Image.LANCZOS).save(OUT / "reamped2_badge_2048.png")
b1k = badge.resize((1024, 1024), Image.LANCZOS)
b1k.save(OUT / "reamped2_badge_1024.png")
b1k.save(OUT / "reamped2.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])

# 7. preview sheet
sheet = Image.new("RGB", (2400, 1500), (24, 26, 32))
def put(img, x, y, w, bg=None):
    img = img.convert("RGBA"); im = img.resize((w, round(img.height * w / img.width)), Image.LANCZOS)
    if bg:
        base = Image.new("RGBA", im.size, bg); im = Image.alpha_composite(base, im)
    sheet.paste(im.convert("RGB"), (x, y))
put(wm, 40, 40, 1100, (12, 14, 24, 255))
put(wm, 1260, 40, 1100, (235, 235, 235, 255))
put(splash43, 40, 520, 1100)
put(cb, 1260, 520, 480)
put(small, 1780, 520, 300)
put(b1k, 1780, 860, 300, (60, 60, 70, 255))
put(b1k, 2100, 860, 64, (60, 60, 70, 255))
put(b1k.resize((32, 32), Image.LANCZOS).resize((128, 128), Image.NEAREST), 2100, 960, 128)
sheet.save(OUT / "_preview_sheet.png")


# 8. the player pack, branding/pack/ (tracked; the installer puts it in mods\packs\re-amped2):
#    only textures made from the RE-Amped2 art, nothing derived from the game's own pixels. So
#    the course banner is drawn from scratch here (the local one above is the original with its
#    logo painted out), and the sharp fonts stay local. Keys are hashes of the originals.
def course_banner_drawn(size=1024):
    """Banneramped2's layout (black strips top and bottom, blue field, two white
    chevrons each side pointing inwards, logo in the middle), drawn."""
    from PIL import ImageDraw
    s = size / 1024
    yy = np.linspace(0, 1, size)[:, None, None]
    field = (np.array([10, 30, 120]) * (1 - yy) + np.array([40, 90, 190]) * yy) * np.ones((1, size, 1))
    img = Image.fromarray(field.astype(np.uint8)).convert("RGBA")
    def chevron(points):
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).polygon([(x * s, y * s) for x, y in points], fill=255)
        xs = np.linspace(0, 1, size)[None, :, None]
        grad = (np.array([255, 255, 255]) * (1 - xs) + np.array([150, 185, 230]) * xs) * np.ones((size, 1, 1))
        if points[0][0] > 512:
            grad = grad[:, ::-1]
        layer = Image.fromarray(grad.astype(np.uint8)).convert("RGBA")
        layer.putalpha(mask)
        return layer
    for dx in (0, 135):
        img = Image.alpha_composite(img, chevron([(dx - 10, 160), (dx + 135, 515), (dx - 10, 870), (dx + 30, 870), (dx + 175, 515), (dx + 30, 160)]))
        img = Image.alpha_composite(img, chevron([(1034 - dx, 160), (889 - dx, 515), (1034 - dx, 870), (994 - dx, 870), (849 - dx, 515), (994 - dx, 160)]))
    img = place(img, wm, (262 * s, 400 * s, 772 * s, 640 * s))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, size, 135 * s), fill=(0, 0, 0, 255))
    d.rectangle((0, 992 * s, size, size), fill=(0, 0, 0, 255))
    return img.convert("RGB")


import shutil, subprocess, tempfile
PACK = AMP / "branding" / "pack"
blank = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
pack = {   # key -> (image, top size)
    "11078467_512x256_0e": (logo, (2048, 1024)),
    "2db08caa_128x128_0e": (small, (512, 512)),
    "c66a31ba_256x256_0e": (course_banner_drawn(), (1024, 1024)),
    "5e30a78c_512x512_0e": (loading169, (2048, 2048)),
    "d81012da_16x16_0e": (blank, (64, 64)),
    **{k: (splash43, (1024, 1024)) for k in ("2c4ed89d_512x512_0c", "4550032c_512x512_0c",
                                              "2907e9d5_512x512_0c", "437650b8_512x512_0c")},
    # the loading screen's controller pictures; their labels are blanked by the menu mod, so the
    # installer leaves these out without it (menu-mod-only.txt)
    **{k: (blank, (64, 64)) for k in ("49571dfc_512x512_0e", "2ca17dab_512x512_0e", "7556167a_512x512_0e")},
}
course_banner_drawn().save(OUT / "pack_course_banner_1024.png")
shutil.rmtree(PACK / "textures", ignore_errors=True)
(PACK / "textures").mkdir(parents=True)
with tempfile.TemporaryDirectory() as d:
    d = Path(d)
    for key, (img, size) in pack.items():
        img.convert("RGBA").resize(size, Image.LANCZOS).save(d / f"{key}.png")
    subprocess.run([str(AMP / "tools" / "bin" / "texconv.exe"), "-nologo", "-y", "--ignore-srgb", "-f", "BC7_UNORM",
                    "-m", "0", "-o", str(PACK / "textures"), *[str(p) for p in sorted(d.glob("*.png"))]],
                   check=True, stdout=subprocess.DEVNULL)
tails = (AMP / "mods" / "texture_pack" / "tails.txt").read_text().splitlines()
(PACK / "textures" / "tails.txt").write_text("\n".join(l for l in tails if l.split()[-1] in pack) + "\n")
(PACK / "menu-mod-only.txt").write_text("49571dfc_512x512_0e\n2ca17dab_512x512_0e\n7556167a_512x512_0e\n")
mb = sum(p.stat().st_size for p in (PACK / "textures").glob("*.dds")) / 2**20
print(f"pack: {len(pack)} textures, {mb:.1f} MB in {PACK}")

# 9. installer art (installer/assets/, tracked): the wizard's header, 1600x280 for 800x140 at
#    200% scaling: the banner with its own logo painted out (work/banner_nologo.png), darkened
#    towards the edges, the wordmark on the left; and the badge for the Done page.
ASSETS = AMP / "installer" / "assets"
ASSETS.mkdir(parents=True, exist_ok=True)
nl = Image.open(WORK / "banner_nologo.png").convert("RGB")
HW, HH, sc = 1600, 280, 0.95
nl = nl.resize((round(nl.width * sc), round(nl.height * sc)), Image.LANCZOS)
x0 = round(nl.width * 0.481 - HW * 0.47)                  # the rider a little left of centre
a = np.asarray(nl.crop((x0, 0, x0 + HW, HH))).astype(np.float32)
xs = np.linspace(0, 1, HW)[None, :, None]
keep = 1 - 0.8 * np.clip((0.36 - xs) / 0.36, 0, 1) ** 0.7 - 0.6 * np.clip((xs - 0.64) / 0.36, 0, 1) ** 0.8
a = a * keep + np.array([6, 18, 40], np.float32) * (1 - keep)   # the wizard's Navy
header = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).convert("RGBA")
s = 150 / wm.height
header.alpha_composite(wm.resize((round(wm.width * s), 150), Image.LANCZOS), (40, 18))
header.convert("RGB").save(ASSETS / "header.jpg", quality=92)
b1k.resize((192, 192), Image.LANCZOS).save(ASSETS / "badge.png", optimize=True)
print("done")
