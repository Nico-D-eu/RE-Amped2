"""Convert Amped 2's compiled Lua scripts into standard Lua 5.0 bytecode.

The game embeds a pre-release Lua 5.0 (beta).  Its chunks differ from Lua 5.0
final in three ways, which is why stock decompilers reject them:

  * the header's test number is 3.14159265358979323846e8 (final uses ...e7);
  * each function dumps its local-variable table *before* its line table
    (final: lines, then locals);
  * there is no upvalue-name table (final writes one, which may be empty);
  * an extra constant type 9 holds a wide (UTF-16) string, written in the
    game's Lua source as L"text".  Stock Lua has no equivalent, so it is
    turned into an ordinary string carrying WIDE_MARKER, which decompile
    output then rewrites back to L"...".

Everything else (instruction encoding, constants, nested prototypes) matches,
so a chunk can be rewritten losslessly for unluac / LuaDec.
"""
import struct

SIGNATURE = b"\x1bLuaP"
HEADER_LEN = 22                     # signature .. test number, inclusive
BETA_TEST_NUMBER = struct.pack("<d", 3.14159265358979323846e8)
FINAL_TEST_NUMBER = struct.pack("<d", 3.14159265358979323846e7)

LUA_TNIL, LUA_TBOOLEAN, LUA_TNUMBER, LUA_TSTRING = 0, 1, 3, 4
LUA_TWSTRING = 9                    # Amped 2 extension
WIDE_MARKER = b"@@L@@"


def is_beta_chunk(data: bytes) -> bool:
    return data[:5] == SIGNATURE and data[14:22] == BETA_TEST_NUMBER


class _Reader:
    def __init__(self, data, pos):
        self.d, self.p = data, pos

    def take(self, n):
        if self.p + n > len(self.d):
            raise ValueError("truncated chunk")
        b = self.d[self.p:self.p + n]
        self.p += n
        return b

    def int(self):
        return struct.unpack("<I", self.take(4))[0]

    def string(self):
        n = self.int()
        return self.take(n) if n else None


def _put_int(out, v):
    out += struct.pack("<I", v)


def _put_string(out, s):
    if s is None:
        _put_int(out, 0)
    else:
        _put_int(out, len(s))
        out += s


def _convert_function(r: _Reader, out: bytearray):
    _put_string(out, r.string())            # source
    out += r.take(4)                        # lineDefined
    out += r.take(4)                        # nups, numparams, is_vararg, maxstacksize

    # beta: locals first
    locals_ = []
    for _ in range(r.int()):
        name = r.string()
        locals_.append((name, r.take(8)))   # startpc, endpc
    lines = r.take(4 * r.int())

    _put_int(out, len(lines) // 4)
    out += lines
    _put_int(out, len(locals_))
    for name, pcs in locals_:
        _put_string(out, name)
        out += pcs
    _put_int(out, 0)                        # upvalue names: none recorded

    nk = r.int()
    _put_int(out, nk)
    for _ in range(nk):
        t = r.take(1)[0]
        out.append(t)
        if t == LUA_TNUMBER:
            out += r.take(8)
        elif t == LUA_TSTRING:
            _put_string(out, r.string())
        elif t == LUA_TWSTRING:
            n = r.int()                     # UTF-16 code units, incl. NUL
            text = r.take(2 * n).decode("utf-16-le").rstrip("\0")
            try:
                raw = text.encode("latin-1")
            except UnicodeEncodeError:
                raw = text.encode("utf-8")
            out[-1] = LUA_TSTRING
            _put_string(out, WIDE_MARKER + raw + b"\0")
        elif t == LUA_TBOOLEAN:
            out += r.take(1)
        elif t != LUA_TNIL:
            raise ValueError(f"unknown constant type {t}")
    nprotos = r.int()
    _put_int(out, nprotos)
    for _ in range(nprotos):
        _convert_function(r, out)

    ncode = r.int()
    _put_int(out, ncode)
    out += r.take(4 * ncode)


def beta_to_final(data: bytes) -> bytes:
    """Return the chunk rewritten as Lua 5.0 final bytecode."""
    if not is_beta_chunk(data):
        raise ValueError("not an Amped 2 (Lua 5.0 beta) chunk")
    out = bytearray(data[:14])
    out += FINAL_TEST_NUMBER
    r = _Reader(data, HEADER_LEN)
    _convert_function(r, out)
    if r.p != len(data):
        raise ValueError(f"{len(data) - r.p} trailing bytes after main function")
    return bytes(out)


def restore_wide_literals(source: str) -> str:
    """Turn decompiled "@@L@@text" strings back into the game's L"text"."""
    return source.replace('"' + WIDE_MARKER.decode(), 'L"')
