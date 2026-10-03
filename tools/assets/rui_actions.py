"""Amped 2 GUI `.actions` files (inside GuiPackages/*.rui): read and write.

Layout, all little-endian:

    u16 count                 actions
    u32 body_len
    u32 offset[count]         each action's start, relative to the body
    body:
      per action:
        u32 0
        u16 name_len, name, u8 0
        u8  param_count, u16 params_len, params (u8 len + chars each)
        u8  block_count
        per block:
          u16 cond_len, cond   (tokens; empty = unconditional)
          statements           (u8 len + tokens each), ended by u8 0
    u16 string_count
    u32 string_offset[string_count]   relative to the string blob
    string blob: u8 len + chars per string

Tokens are bytes: below 0x80 a literal character ('(', ')', '"', '$',
'.', '|', '@', ',' ...), and 0x80 or more starts a two-byte little-endian
reference to string (value - 0x80). So `$FlyButton` is b'$' + ref(FlyButton)
and `PushMenu("MainCareer")` is ref(PushMenu) + b'("' + ref(MainCareer) +
b'")'. An action's statements run top to bottom; `$Name` runs another
action, `Name(...)` a native command (see src/recomp_manual.c for one the
menu mod adds).

The parser keeps every byte it does not interpret, so write(read(x)) == x;
tools/assets/test_rui_actions.py checks that on every file in the game.
"""
import struct


class Action:
    def __init__(self, name, params, blocks, lead=b"\0\0\0\0"):
        self.name = name          # str
        self.params = params      # list of str
        self.blocks = blocks      # list of (cond bytes, [statement bytes])
        self.lead = lead


class ActionsFile:
    def __init__(self, actions, strings):
        self.actions = actions    # list of Action, in file order
        self.strings = strings    # list of str (index 0 = token 0x80)

    # ---- tokens
    def ref(self, s):
        """The token bytes for string s, adding it to the table if new."""
        if s not in self.strings:
            self.strings.append(s)
        return struct.pack("<H", 0x80 + self.strings.index(s))

    def text(self, tokens):
        """Tokens as readable text (string refs expanded)."""
        out, i = [], 0
        while i < len(tokens):
            b = tokens[i]
            if b >= 0x80:
                out.append(self.strings[struct.unpack_from("<H", tokens, i)[0] - 0x80])
                i += 2
            else:
                out.append(chr(b))
                i += 1
        return "".join(out)

    def find(self, name):
        for a in self.actions:
            if a.name == name:
                return a
        return None


def read(data):
    count, body_len = struct.unpack_from("<HI", data, 0)
    offs = struct.unpack_from("<%dI" % count, data, 6)
    body0 = 6 + 4 * count
    actions = []
    for k, off in enumerate(offs):
        p = body0 + off
        end = body0 + (offs[k + 1] if k + 1 < count else body_len)
        lead = data[p:p + 4]; p += 4
        nlen = struct.unpack_from("<H", data, p)[0]; p += 2
        name = data[p:p + nlen].decode("latin-1"); p += nlen
        assert data[p] == 0, (name, "name terminator"); p += 1
        nparams = data[p]; p += 1
        plen = struct.unpack_from("<H", data, p)[0]; p += 2
        params, q = [], p
        for _ in range(nparams):
            l = data[q]; params.append(data[q + 1:q + 1 + l].decode("latin-1")); q += 1 + l
        assert q == p + plen, (name, "params length")
        p += plen
        nblocks = data[p]; p += 1
        blocks = []
        for _ in range(nblocks):
            clen = struct.unpack_from("<H", data, p)[0]; p += 2
            cond = data[p:p + clen]; p += clen
            stmts = []
            while data[p] != 0:
                l = data[p]; stmts.append(data[p + 1:p + 1 + l]); p += 1 + l
            p += 1
            blocks.append((cond, stmts))
        assert p == end, (name, "action length", p, end)
        actions.append(Action(name, params, blocks, lead))
    s0 = body0 + body_len
    n = struct.unpack_from("<H", data, s0)[0]
    soffs = struct.unpack_from("<%dI" % n, data, s0 + 2)
    blob = s0 + 2 + 4 * n
    strings = []
    for o in soffs:
        l = data[blob + o]
        strings.append(data[blob + o + 1:blob + o + 1 + l].decode("latin-1"))
    return ActionsFile(actions, strings)


def write(f):
    bodies = []
    for a in f.actions:
        b = bytearray(a.lead)
        name = a.name.encode("latin-1")
        b += struct.pack("<H", len(name)) + name + b"\0"
        pb = b"".join(bytes([len(s)]) + s.encode("latin-1") for s in a.params)
        b += bytes([len(a.params)]) + struct.pack("<H", len(pb)) + pb
        b += bytes([len(a.blocks)])
        for cond, stmts in a.blocks:
            b += struct.pack("<H", len(cond)) + cond
            for s in stmts:
                assert len(s) < 256
                b += bytes([len(s)]) + s
            b += b"\0"
        bodies.append(bytes(b))
    offs, o = [], 0
    for b in bodies:
        offs.append(o); o += len(b)
    out = bytearray(struct.pack("<HI", len(bodies), o))
    out += struct.pack("<%dI" % len(offs), *offs)
    out += b"".join(bodies)
    blob, soffs = bytearray(), []
    for s in f.strings:
        soffs.append(len(blob)); e = s.encode("latin-1"); blob += bytes([len(e)]) + e
    out += struct.pack("<H", len(f.strings)) + struct.pack("<%dI" % len(soffs), *soffs) + blob
    return bytes(out)
