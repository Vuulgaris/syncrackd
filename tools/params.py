"""UI parameter descriptors from section 3 (main CPU): names, slots, ranges, defaults.

Pinned per OS: section 3 moves between builds. Records are 0x34 bytes:
    +0x00 machine type or page id   +0x04 slot   +0x08 min   +0x0c max
    +0x10 default (min, max, default are 8.8)    +0x28 long name
    +0x2c group tag                 +0x30 short name (the three are pointers)
"""
from dataclasses import dataclass

BASE = 0x40000400
RECORD = 0x34

# (first record, record count)
TABLES = {
    "1.42": [(0x4022e404, 204), (0x40230f14, 235)],
}

# section 7 machine type -> group tag in the descriptors
DIGITAL = {0: "BDMD", 1: "SDBA", 2: "CYAL", 3: "PCCA", 4: "SYTN", 5: "SYCH",
           6: "SDVN", 7: "CPVN", 36: "TOY", 37: "BITS", 38: "SSAW", 44: "SAMP"}


@dataclass(frozen=True)
class Param:
    type: int
    slot: int
    min: float
    max: float
    default: float
    short: str
    long: str
    tag: str


def _u32(d, addr):
    return int.from_bytes(d[addr - BASE:addr - BASE + 4], "big")


def _cstr(d, addr):
    o = addr - BASE
    if not 0 <= o < len(d):
        raise ValueError("name pointer %#x outside the section" % addr)
    s = d[o:d.index(b"\0", o)]
    if not s or len(s) > 40 or not all(32 <= c < 127 for c in s):
        raise ValueError("bad name at %#x" % addr)
    return s.decode("ascii")


def load(section3, version):
    """All descriptor records, in table order."""
    out = []
    for first, count in TABLES[version]:
        for k in range(count):
            r = first + RECORD * k
            out.append(Param(
                type=_u32(section3, r), slot=_u32(section3, r + 4),
                min=_u32(section3, r + 8) / 256, max=_u32(section3, r + 0xc) / 256,
                default=_u32(section3, r + 0x10) / 256,
                long=_cstr(section3, _u32(section3, r + 0x28)),
                tag=_cstr(section3, _u32(section3, r + 0x2c)),
                short=_cstr(section3, _u32(section3, r + 0x30))))
    return out


def machines(section3, version):
    """{machine type: [Param, ...]} for the machines the section 7 voice loop runs."""
    out = {}
    for p in load(section3, version):
        if DIGITAL.get(p.type) == p.tag:
            out.setdefault(p.type, []).append(p)
    return out
