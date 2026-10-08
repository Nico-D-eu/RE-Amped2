"""RE-Amped2 branding: build the game's replacement textures from the art masters.

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
print("done")
