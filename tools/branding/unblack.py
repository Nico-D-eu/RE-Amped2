# Turn a logo rendered on black (e.g. reamped2_wordmark_full_reconstructed.jpg, 2x-upscaled first)
# into RGBA: the body solid, the glow keeping its brightness as alpha. Usage:
#   py -3.10 tools/branding/unblack.py <in.png> <out_glow.png> <out_noglow.png> <body threshold, 70>
import sys, numpy as np, cv2
from PIL import Image
from scipy import ndimage as ndi
src, out_glow, out_noglow, thr = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
u = np.asarray(Image.open(src).convert('RGB')).astype(np.float32)
mx = u.max(-1)
body = mx > thr
body = ndi.binary_closing(body, iterations=2)
body = ndi.binary_fill_holes(body)
lab, n = ndi.label(body); sz = ndi.sum(body, lab, range(1, n + 1))
body = np.isin(lab, [i + 1 for i in range(n) if sz[i] > 0.002 * body.size])
body = ndi.binary_fill_holes(body)
bs = cv2.GaussianBlur(body.astype(np.float32), (0, 0), 1.2)
bs = np.clip((bs - 0.5) * 2.5 + 0.5, 0, 1)
glow = np.clip((mx - 8) / (255 - 8), 0, 1)
A = np.maximum(bs, glow)
C = np.clip(u / np.maximum(A, 1e-3)[..., None], 0, 255)
def save(alpha, path):
    rgba = np.dstack([C, alpha * 255]).astype(np.uint8)
    ys, xs = np.where(A > 0.02)
    Image.fromarray(rgba[ys.min():ys.max() + 1, xs.min():xs.max() + 1]).save(path)
save(A, out_glow)
save(bs, out_noglow)
