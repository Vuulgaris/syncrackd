"""Pinned Syntakt OS images: load, patch, build, verify.

Safety rules enforced here:
- only official files with a known SHA-256 load
- only sections in PATCHABLE can be replaced; bootstrap and updater hard-fail
- every patch asserts the stock bytes at its site
- verify() checks a built image differs from the official one only inside
the declared regions

"""
import glob
import hashlib
import os
from dataclasses import dataclass

from . import ele3, syx

# SHA-256 of official files we have held and decoded ourselves.
KNOWN = {
    "ded3c59fdb909eb9e2c3307b30a486452c8fa6947b12c14e0ce35a187b7f37c1": "1.42",
}

NAMES = {1: "fpga", 2: "bootstrap", 3: "main", 4: "updater",
         5: "meta", 6: "boot", 7: "audio", 8: "usb_mcu"}
PROTECTED = {2: "bootstrap", 4: "updater"}
PATCHABLE = {3, 7}
# A section that may grow, and how far: section 7 is read by the main CPU at its own length and taken while length + 5
# <= 393,216 (0x40082d66; docs/FINDINGS.md, "Room past section 7's end"). Kept a multiple of 4. Only past its end.
GROW = {7: 393208}

# Decoded section hashes per OS, checked on load.
SECTION_SHA256 = {
    "1.42": {
        1: "c920a4cbcc53bec448f990674541246d3028ebcc3a8acc5849abb01b0dd76e67",
        2: "9fa34a8334548f70ec9fa62491e495bf768323e24608f4f3661115a6757b0f7d",
        3: "1a9723b19fb54d0566c1f690379d2e6dfe43227f77e170ad731dd029430eb3e7",
        4: "6e78d72b32fb1847ab33a00d8088f1259e0b52c235621bc8cfd1702a105f7ebb",
        5: "7d97057d13e4630489f3d7aa22dcbcac36281f945ba8fd17082ecd5d43c50455",
        6: "eec1379d7d3cee2633635636af84a19ca5907ce8a07ed4591fff22cb023482a0",
        7: "daf6451cf9587c0b628e901b7bb6b25f4e2633d448c534c0c181dd35ec783bc2",
        8: "6943b2f27773f40f1e7857ea6fa7a121269e930bd403098e6b6c00002327dc20",
    },
}


class GuardError(Exception):
    """A safety rule was about to be broken. Never catch this to continue."""


@dataclass(frozen=True)
class Patch:
    section: int
    offset: int  # offset in the decoded section
    stock: bytes  # bytes the official OS must have here
    new: bytes
    note: str = ""


def sha256(b):
    return hashlib.sha256(b).hexdigest()


# Stock bytes in our source are sealed: XORed with a keystream only the official file gives, so the repository holds
# none of Elektron's bytes. sx gives a sealed hex string back, sb sealed bytes. `python -m tools.seal` makes them.
_seal = []


def seal_key():
    if not _seal:
        root = os.environ.get("SYNTAKT_FIRMWARE") or os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "firmware")
        for p in sorted(glob.glob(os.path.join(root, "**", "*.syx"), recursive=True)):
            with open(p, "rb") as f:
                raw = f.read()
            if sha256(raw) in KNOWN:
                _seal.append(hashlib.sha256(b"syntaktmod seal 1\0" + raw).digest())
                break
        else:
            raise GuardError("sealed stock bytes need the official 1.42 file in firmware/ (or SYNTAKT_FIRMWARE)")
    return _seal[0]


def _stream(key, nonce, n):
    return hashlib.shake_256(key + nonce).digest(n)


def seal(data):
    key = seal_key()
    nonce = hashlib.sha256(key + data).digest()[:4]
    return (nonce + bytes(a ^ b for a, b in zip(data, _stream(key, nonce, len(data))))).hex()


def sb(token):
    key, raw = seal_key(), bytes.fromhex(token)
    nonce, body = raw[:4], raw[4:]
    data = bytes(a ^ b for a, b in zip(body, _stream(key, nonce, len(body))))
    if hashlib.sha256(key + data).digest()[:4] != nonce:
        raise GuardError("a sealed run does not open with this file's key")
    return data


def sx(token):
    return sb(token).hex()


class Image:
    """A decoded .syx. Not pinned: use load() for official files."""

    def __init__(self, raw):
        self.raw = bytes(raw)
        stream, self.transport = syx.decode(self.raw)
        if self.transport.product != syx.PRODUCT_SYNTAKT:
            raise ValueError("not a Syntakt file (product 0x%02x)" % self.transport.product)
        self.container = ele3.parse(stream)
        self._cache = {}

    @property
    def ids(self):
        return [s.id for s in self.container.sections]

    def _decoded(self, sid):
        if sid not in self._cache:
            s = self.container.by_id(sid)
            self._cache[sid] = ele3.depack(s.stored) if s.compressed else (s.stored, None)
        return self._cache[sid]

    def section(self, sid):
        """Section contents as the device sees them."""
        return self._decoded(sid)[0]

    def build(self, new_sections=None):
        """New .syx bytes with decoded sections replaced per {id: bytes}."""
        stored = {}
        for sid, data in (new_sections or {}).items():
            if sid in PROTECTED:
                raise GuardError("refusing to touch section %d (%s)" % (sid, PROTECTED[sid]))
            if sid not in PATCHABLE:
                raise GuardError("section %d is not patchable" % sid)
            old, ops = self._decoded(sid)
            if len(data) != len(old) and not (sid in GROW and ops is None and len(old) < len(data) <= GROW[sid]):
                raise GuardError("section %d: length change %d -> %d" % (sid, len(old), len(data)))
            if ops is None:
                stored[sid] = bytes(data)
            else:
                dirty = bytearray(a != b for a, b in zip(old, data))
                stored[sid] = ele3.repack(bytes(data), ops, dirty)
        blob = ele3.build(self.container, stored)
        return syx.encode(ele3.to_stream(blob, syx.PLAIN_PER_MSG), self.transport)


def load(path):
    """Load an official file. Fails unless file and section hashes are pinned."""
    with open(path, "rb") as f:
        raw = f.read()
    h = sha256(raw)
    if h not in KNOWN:
        raise GuardError("unknown file hash %s: not a pinned official OS" % h)
    img = Image(raw)
    img.version = KNOWN[h]
    if img.container.version != img.version:
        raise GuardError("container says %s, pin says %s" % (img.container.version, img.version))
    want = SECTION_SHA256[img.version]
    if sorted(img.ids) != sorted(want):
        raise GuardError("unexpected section set %s" % img.ids)
    for sid in img.ids:
        if sha256(img.section(sid)) != want[sid]:
            raise GuardError("section %d hash mismatch" % sid)
    return img


def apply(img, patches):
    """Apply patches. Returns ({id: new bytes}, {id: [(start, end), ...]})."""
    out, regions = {}, {}
    for p in patches:
        if p.section in PROTECTED:
            raise GuardError("patch targets section %d (%s)" % (p.section, PROTECTED[p.section]))
        if p.section not in PATCHABLE:
            raise GuardError("patch targets unpatchable section %d" % p.section)
        if len(p.stock) != len(p.new) or not p.new:
            raise GuardError("patch at %d:%#x: stock and new must be the same non-zero length"
                             % (p.section, p.offset))
        buf = out.setdefault(p.section, bytearray(img.section(p.section)))
        end = p.offset + len(p.new)
        if p.offset < 0 or end > len(buf):
            raise GuardError("patch at %d:%#x is out of range" % (p.section, p.offset))
        if any(a < end and p.offset < b for a, b in regions.get(p.section, [])):
            raise GuardError("patch at %d:%#x overlaps another patch" % (p.section, p.offset))
        if img.section(p.section)[p.offset:end] != p.stock:
            raise GuardError("patch at %d:%#x: stock bytes do not match this OS" % (p.section, p.offset))
        buf[p.offset:end] = p.new
        regions.setdefault(p.section, []).append((p.offset, end))
    return {k: bytes(v) for k, v in out.items()}, regions


def verify(official, built_raw, regions):
    """Check a built file against the official image. Raises GuardError.

    The built file must decode cleanly (packet checksums, content checksum, layout), keep every section's length, and
    differ from the official sections only inside regions = {id: [(start, end), ...]}.
    """
    built = Image(built_raw)
    # the packet count follows the container size, which moves when a compressed section is repacked; decode() has
    # already checked it against the packets present
    for field in ("product", "base", "start_seq"):
        if getattr(built.transport, field) != getattr(official.transport, field):
            raise GuardError("transport parameter %s changed" % field)
    if built.ids != official.ids:
        raise GuardError("section table changed")
    hdr_end = ele3.TABLE_OFF
    if built.container.blob[:hdr_end] != official.container.blob[:hdr_end]:
        raise GuardError("container header changed")
    for sid in official.ids:
        a, b = official.section(sid), built.section(sid)
        o, n = official.container.by_id(sid), built.container.by_id(sid)
        if o.dest != n.dest or o.index != n.index or o.compressed != n.compressed:
            raise GuardError("section %d: table entry changed" % sid)
        if sid in PROTECTED and o.stored != n.stored:
            raise GuardError("section %d (%s) changed" % (sid, PROTECTED[sid]))
        if len(a) != len(b) and not (sid in GROW and len(a) < len(b) <= GROW[sid]):
            raise GuardError("section %d: length changed" % sid)
        if a == b:
            continue
        if sid not in regions:
            raise GuardError("section %d changed but declares no region" % sid)
        mask = bytearray(len(b))
        for start, end in regions[sid]:
            mask[start:end] = b"\x01" * (end - start)
        if not all(mask[len(a):]):
            raise GuardError("section %d: grown past its end outside declared regions" % sid)
        for i in range(len(a)):
            if a[i] != b[i] and not mask[i]:
                raise GuardError("section %d: byte %#x changed outside declared regions" % (sid, i))
    return built
