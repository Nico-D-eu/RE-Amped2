"""Amped 2's compiled string table (GuiPackages/Base.rui StringTables/<lang>/StringTable.dat).

Layout, little-endian (decoded 2026-10-07; all three languages read and write
back byte for byte):

    u32   font count (9)
    0x004 a 0 byte, then the font names, each in a 44-byte NUL-padded slot
          (from 0x005)
    0x18D u32 n, the string count (2694 in every language), in the last
          slot's padding. The game trusts it: a table with more records
          than this blanks every string in the game.
    0x191 u32 offsets[n + 1]: record offsets from the first record; the
          last one is the size of the record block
    records, sorted by key (plain byte order, so the game can binary-search):
        u8    key length
        key   ASCII, then a NUL
        u16   text length in UTF-16 units
        text  UTF-16LE, no terminator
        u8    font index (into the font list)
        f32   scale (the .lua source's percentage / 100)


StringTable.lua beside it is the source the .dat was built from
({L"text", "Font_Name", percent} per key).
"""
import struct
from dataclasses import dataclass

COUNT = 0x18D
TABLE = 0x191


@dataclass
class Entry:
    key: str
    text: str
    font: int
    scale: float


@dataclass
class StringTable:
    header: bytes          # everything before the offset table, kept as is
    entries: list

    def get(self, key):
        for e in self.entries:
            if e.key == key:
                return e
        return None

    def set(self, key, text, like):
        """Add or replace key, with the font and scale of the entry `like`."""
        src = self.get(like)
        if src is None:
            raise KeyError(like)
        e = self.get(key)
        if e is None:
            self.entries.append(Entry(key, text, src.font, src.scale))
        else:
            e.text, e.font, e.scale = text, src.font, src.scale
        self.entries.sort(key=lambda x: x.key.encode("ascii"))


def read(data):
    n = struct.unpack_from("<I", data, COUNT)[0]
    offsets = struct.unpack_from("<%dI" % (n + 1), data, TABLE)
    base = TABLE + 4 * (n + 1)
    entries = []
    for i in range(n):
        p = base + offsets[i]
        kl = data[p]
        key = data[p + 1:p + 1 + kl].decode("ascii")
        if data[p + 1 + kl] != 0:
            raise ValueError(f"record {i}: key not NUL-terminated")
        q = p + 2 + kl
        tl = struct.unpack_from("<H", data, q)[0]
        q += 2
        text = data[q:q + 2 * tl].decode("utf-16le")
        q += 2 * tl
        font = data[q]
        scale = struct.unpack_from("<f", data, q + 1)[0]
        if q + 5 != base + offsets[i + 1]:
            raise ValueError(f"record {i} ({key}): size mismatch")
        entries.append(Entry(key, text, font, scale))
    if base + offsets[n] != len(data):
        raise ValueError("record block size does not match the last offset")
    return StringTable(data[:TABLE], entries)


def write(table):
    recs = []
    for e in table.entries:
        k = e.key.encode("ascii")
        t = e.text.encode("utf-16le")
        if len(k) > 255:
            raise ValueError(f"key too long: {e.key}")
        recs.append(bytes([len(k)]) + k + b"\0" + struct.pack("<H", len(t) // 2)
                    + t + bytes([e.font]) + struct.pack("<f", e.scale))
    offsets, pos = [], 0
    for r in recs:
        offsets.append(pos)
        pos += len(r)
    offsets.append(pos)
    header = (table.header[:COUNT] + struct.pack("<I", len(recs))
              + table.header[COUNT + 4:])
    return (header + struct.pack("<%dI" % len(offsets), *offsets)
            + b"".join(recs))


if __name__ == "__main__":
    import sys
    import zipfile
    rui = sys.argv[1] if len(sys.argv) > 1 else "game/GuiPackages/Base.rui"
    with zipfile.ZipFile(rui) as z:
        for name in z.namelist():
            if name.endswith("StringTable.dat"):
                data = z.read(name)
                t = read(data)
                same = write(t) == data
                print(f"{name}: {len(t.entries)} strings, round trip "
                      f"{'identical' if same else 'DIFFERS'}")
