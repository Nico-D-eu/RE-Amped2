"""Xbox (NV2A) texture resources as Amped 2 stores them.

Textures live in three kinds of container, all holding standard 20-byte
D3DTexture headers (Common, Data, Lock, Format, Size) followed by raw GPU data:

  XPR0   'XPR0', total size, header size, resource headers ..., data at
         header size.  Resource Data fields are offsets into that data.
  PGF    Indie Built model/level file (levels, characters, panoramas):
           u32 version (float 2.0/3.0), u32 0x0FFF0001, u32 file size,
           u32 geometry size, u32 texture-data size, u32 texture count,
           u32 tail size, u32 0x0FFF0001,
           texture count * 20-byte headers, texture data, geometry, tail.
         Texture Data fields are offsets into the texture data block.
  .trees Level tree billboards: an XPR0 embedded after a small header
         (read-only here; rebuilding it would need the outer layout).

DXT textures are stored as plain 4x4 blocks.  Other formats are swizzled
(Morton order, x bit lowest) unless they are one of the LIN_ formats.
"""
import io
import struct
import zlib

import numpy as np

XPR_MAGIC = b"XPR0"
PGF_MARKER = 0x0FFF0001
COMMON_TYPE_TEXTURE = 0x00040000
COMMON_TYPE_MASK = 0x00070000
TEXTURE_ALIGN = 128

# code: (name, bits per pixel, kind)   kind: dxt | swz | lin
FORMATS = {
    0x0C: ("DXT1", 4, "dxt"),
    0x0E: ("DXT3", 8, "dxt"),        # Xbox DXT2 and DXT3 share this code
    0x0F: ("DXT5", 8, "dxt"),        # Xbox DXT4 and DXT5 share this code
    0x00: ("L8", 8, "swz"),
    0x04: ("A4R4G4B4", 16, "swz"),
    0x05: ("R5G6B5", 16, "swz"),
    0x06: ("A8R8G8B8", 32, "swz"),
    0x07: ("X8R8G8B8", 32, "swz"),
    0x19: ("A8", 8, "swz"),
    0x1A: ("A8L8", 16, "swz"),
    0x3A: ("A8B8G8R8", 32, "swz"),
    0x13: ("LIN_L8", 8, "lin"),
    0x12: ("LIN_A8R8G8B8", 32, "lin"),
    0x1E: ("LIN_X8R8G8B8", 32, "lin"),
    0x1D: ("LIN_A4R4G4B4", 16, "lin"),
    0x11: ("LIN_R5G6B5", 16, "lin"),
    0x1F: ("LIN_A8", 8, "lin"),
}
DXT_FOURCC = {0x0C: b"DXT1", 0x0E: b"DXT3", 0x0F: b"DXT5"}
DXT_TEXCONV = {0x0C: "BC1_UNORM", 0x0E: "BC2_UNORM", 0x0F: "BC3_UNORM"}


class Texture:
    """One D3DTexture header plus where its data lives in the container."""

    def __init__(self, raw_header: bytes, index: int):
        self.common, self.data, self.lock, self.format, self.size = struct.unpack("<5I", raw_header)
        self.index = index
        f = self.format
        self.cube = bool(f & 0x4)
        self.code = (f >> 8) & 0xFF
        self.mips = max((f >> 16) & 0xF, 1)
        name, self.bpp, self.kind = FORMATS.get(self.code, (f"0x{self.code:02X}", 0, "unknown"))
        self.format_name = name
        if self.size:                      # linear / non power of two
            self.width = (self.size & 0xFFF) + 1
            self.height = ((self.size >> 12) & 0xFFF) + 1
            self.pitch = (((self.size >> 24) & 0xFF) + 1) * 64
            self.mips = 1
        else:
            self.width = 1 << ((f >> 20) & 0xF)
            self.height = 1 << ((f >> 24) & 0xF)
            self.pitch = None

    @property
    def is_texture(self):
        return (self.common & COMMON_TYPE_MASK) == COMMON_TYPE_TEXTURE

    @property
    def supported(self):
        return self.is_texture and self.kind != "unknown" and not self.cube

    def level_dims(self, level):
        w, h = max(self.width >> level, 1), max(self.height >> level, 1)
        return w, h

    def level_size(self, level):
        w, h = self.level_dims(level)
        if self.kind == "dxt":
            return ((w + 3) // 4) * ((h + 3) // 4) * (8 if self.code == 0x0C else 16)
        if self.kind == "lin":
            return self.pitch * h
        return w * h * self.bpp // 8

    def total_size(self):
        faces = 6 if self.cube else 1
        return faces * sum(self.level_size(l) for l in range(self.mips))

    def header_bytes(self):
        return struct.pack("<5I", self.common, self.data, self.lock, self.format, self.size)

    def key(self, level0: bytes) -> str:
        """Stable id for texture packs: crc32 of the top mip as stored in guest memory."""
        return f"{zlib.crc32(level0) & 0xFFFFFFFF:08x}_{self.width}x{self.height}_{self.code:02x}"


class Container:
    """Textures inside one archive entry, with enough layout to rebuild it."""

    kind = None
    rebuildable = False

    def __init__(self, data: bytes):
        self.raw = data
        self.textures = []
        self.data_base = 0

    def level0(self, tex: Texture) -> bytes:
        start = self.data_base + tex.data
        return self.raw[start:start + tex.level_size(0)]

    def texture_data(self, tex: Texture) -> bytes:
        start = self.data_base + tex.data
        return self.raw[start:start + tex.total_size()]


class XprContainer(Container):
    kind = "xpr"
    rebuildable = True

    def __init__(self, data: bytes, offset: int = 0):
        super().__init__(data)
        self.offset = offset
        magic, self.total, self.header_size = struct.unpack_from("<4sII", data, offset)
        self.data_base = offset + self.header_size
        pos = offset + 12
        i = 0
        while pos + 4 <= offset + self.header_size:
            common = struct.unpack_from("<I", data, pos)[0]
            if common == 0xFFFFFFFF:
                break
            if (common & COMMON_TYPE_MASK) != COMMON_TYPE_TEXTURE:
                break                         # palettes / vertex data: stop, keep as-is
            self.textures.append(Texture(data[pos:pos + 20], i))
            pos += 20
            i += 1

    def rebuild(self, replacements: dict) -> bytes:
        """replacements: texture index -> (new format dword, new data bytes)."""
        return _relayout(self, replacements, self._emit)

    def _emit(self, headers: bytes, blob: bytes) -> bytes:
        hdr_region = self.raw[self.offset + 12 + len(headers):self.offset + self.header_size]
        out = struct.pack("<4sII", XPR_MAGIC, self.header_size + len(blob), self.header_size)
        return out + headers + hdr_region + blob


class PgfContainer(Container):
    kind = "pgf"
    rebuildable = True

    def __init__(self, data: bytes):
        super().__init__(data)
        (self.version, m1, self.file_size, self.geom_size, self.tex_size,
         count, self.tail_size, m2) = struct.unpack_from("<8I", data, 0)
        self.data_base = 32 + 20 * count
        for i in range(count):
            self.textures.append(Texture(data[32 + 20 * i:52 + 20 * i], i))

    @staticmethod
    def detect(data: bytes) -> bool:
        if len(data) < 32:
            return False
        v = struct.unpack_from("<8I", data, 0)
        return v[1] == PGF_MARKER and v[7] == PGF_MARKER and v[2] == len(data) and v[5] < 4096

    def rebuild(self, replacements: dict) -> bytes:
        return _relayout(self, replacements, self._emit)

    def _emit(self, headers: bytes, blob: bytes) -> bytes:
        rest = self.raw[self.data_base + self.tex_size:]          # geometry + tail, untouched
        hdr = struct.pack("<8I", self.version, PGF_MARKER, 32 + len(headers) + len(blob) + len(rest),
                          self.geom_size, len(blob), len(self.textures), self.tail_size, PGF_MARKER)
        return hdr + headers + blob + rest


def _relayout(c: Container, replacements: dict, emit) -> bytes:
    """Re-pack texture data (original order, 128-byte aligned) and patch headers.

    The shipped files align textures to 16 bytes or more and leave stale bytes
    in the gaps, so a rebuild without replacements matches the original in
    every texture and in the geometry, but not necessarily in the padding.
    """
    blob = bytearray()
    headers = bytearray()
    order = sorted(c.textures, key=lambda t: t.data)
    new_offsets = {}
    for tex in order:
        if len(blob) % TEXTURE_ALIGN:
            blob += bytes(TEXTURE_ALIGN - len(blob) % TEXTURE_ALIGN)
        new_offsets[tex.index] = len(blob)
        blob += replacements[tex.index][1] if tex.index in replacements else c.texture_data(tex)
    for tex in c.textures:
        fmt = replacements[tex.index][0] if tex.index in replacements else tex.format
        headers += struct.pack("<5I", tex.common, new_offsets[tex.index], tex.lock, fmt, tex.size)
    return emit(bytes(headers), bytes(blob))      # originals carry no trailing padding


def open_container(name: str, data: bytes):
    """Return a Container for an archive entry, or None if it holds no textures."""
    if data[:4] == XPR_MAGIC:
        c = XprContainer(data)
        return c if c.textures else None
    if PgfContainer.detect(data):
        c = PgfContainer(data)
        return c if c.textures else None
    if name.lower().endswith(".trees"):
        at = data.find(XPR_MAGIC)
        if at >= 0:
            c = XprContainer(data, at)
            c.rebuildable = False
            c.kind = "trees"
            return c if c.textures else None
    return None


# --------------------------------------------------------------------------- decoding

def _swizzle_map(w, h):
    """Index into swizzled storage for every (y, x) of a w*h power-of-two image."""
    xs = np.arange(w, dtype=np.int64)
    ys = np.arange(h, dtype=np.int64)
    sx = np.zeros(w, np.int64)
    sy = np.zeros(h, np.int64)
    bit = 0
    for i in range(max(w.bit_length(), h.bit_length())):
        if (1 << i) < w:
            sx |= ((xs >> i) & 1) << bit
            bit += 1
        if (1 << i) < h:
            sy |= ((ys >> i) & 1) << bit
            bit += 1
    return sy[:, None] | sx[None, :]


def swizzle(linear: np.ndarray) -> np.ndarray:
    """(h, w, ...) array -> flat swizzled array of the same elements."""
    h, w = linear.shape[:2]
    out = np.empty((h * w,) + linear.shape[2:], linear.dtype)
    out[_swizzle_map(w, h).ravel()] = linear.reshape((h * w,) + linear.shape[2:])
    return out


def unswizzle(flat: np.ndarray, w, h) -> np.ndarray:
    return flat[_swizzle_map(w, h)]


def dds_bytes(tex: Texture, level0: bytes) -> bytes:
    """Wrap a DXT top mip in a minimal DDS file."""
    w, h = tex.width, tex.height
    flags = 0x1 | 0x2 | 0x4 | 0x1000 | 0x80000
    header = struct.pack("<4sIIIIIII44x", b"DDS ", 124, flags, h, w, len(level0), 0, 1)
    pf = struct.pack("<II4s20x", 32, 0x4, DXT_FOURCC[tex.code])
    caps = struct.pack("<I16x", 0x1000)
    return header + pf + caps + level0


def decode_rgba(tex: Texture, level0: bytes) -> np.ndarray:
    """Top mip as an (h, w, 4) uint8 RGBA array."""
    from PIL import Image
    w, h = tex.width, tex.height
    if tex.kind == "dxt":
        return np.asarray(Image.open(io.BytesIO(dds_bytes(tex, level0))).convert("RGBA"))
    if tex.kind == "lin":
        rows = np.frombuffer(level0, np.uint8).reshape(h, tex.pitch)[:, :w * tex.bpp // 8]
        px = rows.reshape(h, w, tex.bpp // 8)
    else:
        px = unswizzle(np.frombuffer(level0, np.uint8).reshape(w * h, tex.bpp // 8), w, h)
    name = tex.format_name.replace("LIN_", "")
    out = np.empty((h, w, 4), np.uint8)
    if name in ("A8R8G8B8", "X8R8G8B8"):
        out[..., 0], out[..., 1], out[..., 2], out[..., 3] = px[..., 2], px[..., 1], px[..., 0], px[..., 3]
        if name == "X8R8G8B8":
            out[..., 3] = 255
    elif name == "A8B8G8R8":
        out[...] = px
    elif name == "A4R4G4B4":
        v = px[..., 0].astype(np.uint16) | (px[..., 1].astype(np.uint16) << 8)
        for ch, shift in ((2, 0), (1, 4), (0, 8), (3, 12)):
            out[..., ch] = ((v >> shift) & 0xF) * 17
    elif name == "R5G6B5":
        v = px[..., 0].astype(np.uint16) | (px[..., 1].astype(np.uint16) << 8)
        out[..., 0] = ((v >> 11) & 0x1F) * 255 // 31
        out[..., 1] = ((v >> 5) & 0x3F) * 255 // 63
        out[..., 2] = (v & 0x1F) * 255 // 31
        out[..., 3] = 255
    elif name == "L8":
        out[..., :3] = px[..., :1]
        out[..., 3] = 255
    elif name == "A8":
        out[..., :3] = 255
        out[..., 3] = px[..., 0]
    elif name == "A8L8":
        out[..., :3] = px[..., :1]
        out[..., 3] = px[..., 1]
    else:
        raise ValueError(f"no decoder for {tex.format_name}")
    return out
