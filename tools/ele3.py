"""ELE3 container as found in Syntakt OS files.

Plain stream = [u32 container length][u32 content checksum][container][zero pad].
Container    = 0x20 byte header ("ELE3", model, version, section count at 0x1C),
               16-byte table entries [id][offset][stored size][dest],
               sections, each 16-byte aligned, zero pad to 16 at the end.

The Syntakt container has no HMAC trailer (confirmed on 1.42). A container
with bytes past the aligned end of its sections is refused.

A compressed section is stored as [u32 stream length][u32 byte sum][aPLib
stream][zero pad to 4]. Raw sections have no header.
"""
import array
import os
import sys
from dataclasses import dataclass

try:
    import numpy as np
except ImportError:  # the user's patcher runs on the standard library alone
    np = None

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "third_party", "elektron-model-tweaks"))
from mtlib import aplib  # noqa: E402  (MIT, vendored as a submodule)

PREAMBLE = 8
MAGIC = b"ELE3"
COUNT_OFF = 0x1C
TABLE_OFF = 0x20
ENTRY = 16
ALIGN = 16
SECT_HDR = 8


@dataclass(frozen=True)
class Section:
    index: int       # slot in the table
    id: int
    off: int
    size: int        # stored size
    dest: int
    stored: bytes

    @property
    def compressed(self):
        s = self.stored
        if len(s) < SECT_HDR:
            return False
        n = int.from_bytes(s[:4], "big")
        if _align(n + SECT_HDR, 4) != len(s):
            return False
        return int.from_bytes(s[4:8], "big") == sum(s[SECT_HDR:]) & 0xFFFFFFFF


@dataclass(frozen=True)
class Container:
    blob: bytes
    model: str
    version: str
    sections: tuple

    def by_id(self, sid):
        for s in self.sections:
            if s.id == sid:
                return s
        raise KeyError("no section %d" % sid)


def _align(v, a):
    return (v + a - 1) // a * a


def _be32(b, o):
    return int.from_bytes(b[o:o + 4], "big")


def content_checksum(blob):
    """Sum over big-endian words of (index + 1) XOR word, mod 2^32."""
    n = len(blob) // 4
    if np is None:
        words = array.array("I", blob[:4 * n])
        if sys.byteorder == "little":
            words.byteswap()
        return sum(w ^ k for k, w in enumerate(words, 1)) & 0xFFFFFFFF
    w = np.frombuffer(blob, dtype=">u4", count=n).astype(np.uint64)
    k = np.arange(1, n + 1, dtype=np.uint64)
    return int((w ^ k).sum() & 0xFFFFFFFF)


def parse(stream):
    """Plain stream -> Container. Verifies length, checksum, layout, padding."""
    declared = _be32(stream, 0)
    if PREAMBLE + declared > len(stream):
        raise ValueError("declared container size exceeds the stream")
    if any(stream[PREAMBLE + declared:]):
        raise ValueError("non-zero bytes after the container")
    blob = bytes(stream[PREAMBLE:PREAMBLE + declared])
    if blob[:4] != MAGIC:
        raise ValueError("no ELE3 magic")
    if content_checksum(blob) != _be32(stream, 4):
        raise ValueError("content checksum mismatch")
    n = _be32(blob, COUNT_OFF)
    if not 1 <= n <= 16:
        raise ValueError("implausible section count %d" % n)
    secs = []
    for i in range(n):
        e = TABLE_OFF + i * ENTRY
        sid, off, size, dest = (_be32(blob, e + 4 * k) for k in range(4))
        if off % ALIGN or off + size > len(blob):
            raise ValueError("section %d: bad offset or size" % sid)
        secs.append(Section(i, sid, off, size, dest, blob[off:off + size]))
    if len({s.id for s in secs}) != n:
        raise ValueError("duplicate section id")
    end = max(s.off + s.size for s in secs)
    if len(blob) != _align(end, ALIGN):
        raise ValueError("container has a trailer; this layout is not supported")
    return Container(blob, blob[7:20].decode("latin1").strip(),
                     blob[20:28].decode("latin1").strip("\0 "), tuple(secs))


def build(c, replacements=None):
    """Container blob with stored bytes replaced per {section id: bytes}."""
    replacements = replacements or {}
    first = min(s.off for s in c.sections)
    out = bytearray(c.blob[:first])
    pos = first
    for s in sorted(c.sections, key=lambda s: s.off):
        data = replacements.get(s.id, s.stored)
        pos = _align(pos, ALIGN)
        out += b"\0" * (pos - len(out))
        out += data
        e = TABLE_OFF + s.index * ENTRY
        out[e + 4:e + 8] = pos.to_bytes(4, "big")
        out[e + 8:e + 12] = len(data).to_bytes(4, "big")
        pos += len(data)
    out += b"\0" * (_align(pos, ALIGN) - len(out))
    return bytes(out)


def to_stream(blob, per_packet):
    """Always one packet more than strictly needed, like the official file."""
    n = (PREAMBLE + len(blob)) // per_packet + 1
    stream = bytearray(n * per_packet)
    stream[0:4] = len(blob).to_bytes(4, "big")
    stream[4:8] = content_checksum(blob).to_bytes(4, "big")
    stream[PREAMBLE:PREAMBLE + len(blob)] = blob
    return bytes(stream)


def depack(stored):
    """Stored compressed section -> (data, ops). ops feed repack()."""
    n = int.from_bytes(stored[:4], "big")
    return aplib.depack(stored[:SECT_HDR + n])


def repack(data, ops, dirty):
    """Re-encode a same-length section. dirty marks changed bytes.

    Untouched ops are emitted as they came in, so an unchanged section
    repacks to its original stored bytes.
    """
    body = aplib.repack(data, ops, dirty)
    return body + b"\0" * (_align(len(body), 4) - len(body))
