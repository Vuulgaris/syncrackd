#!/usr/bin/env python3
"""SynCrackd, the sleep image: a sampler for the Elektron Syntakt, made from Elektron's own OS 1.42 file.

    python3 syncrackd_sleep.py Syntakt_OS1.42.syx
    python3 syncrackd_sleep.py Syntakt_OS1.42.syx -o somewhere/mod.syx

SynCrackd for Syntakt OS 1.42: a sample player in Twinshot's place and a sampling page. Unofficial.

Python 3.9 or later, nothing to install. It takes only the exact official 1.42 file, puts the mod's bytes in,
checks the result differs from Elektron's file only where the mod goes, and that its SHA-256 is this release's:
cc4f48b561c01860cdcee41009bec77ff37ec8713215c561d97f518949da12f8

Unofficial, not made or supported by Elektron. At your own risk, no warranty. Back up your +Drive with Transfer
before you flash. This file holds none of Elektron's firmware; the file it makes does, so do not share that one.
https://github.com/Vuulgaris/syncrackd

----
MIT License

Copyright (c) 2026 Vuulgaris and contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
----
The aplib codec in this file is from elektron-model-tweaks:

MIT License

Copyright (c) 2026 drumkilla

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE."""
import base64
import json
import sys
import types
import zlib

_SOURCES = [
    ('mtlib.aplib', '"""aPLib-variant codec, only as much as patching needs.\n\nThe section stream is an interlaced Elias-gamma bit stream of two op kinds:\na literal byte, or a match copying `n` bytes from `off` back in the output.\n\nRecompressing 1.7 MB from scratch in Python would be slow and would gain\nnothing, so instead the original stream is decoded into its op list and then\nre-encoded verbatim. Only ops whose output - or, for a match, whose source -\ntouches a patched byte are replaced by literals. Everything else is emitted\nexactly as it came in, so the result stays as tight as the vendor\'s own\npacker and takes a couple of seconds.\n"""\n\nSECT_HDR = 8\nOFFSET_BIAS = 767\nREUSE_GAMMA = 2\nFAR_THRESHOLD = 3328\nEND_GAMMA = 0x1000002          # (END_GAMMA << 8) + 0xFF wraps to OFFSET_BIAS\n\nLITERAL, MATCH = 1, 0\n\n\nclass _Reader:\n    def __init__(self, src, pos):\n        self.src, self.ip, self.tag = src, pos, 0\n\n    def bit(self):\n        self.tag <<= 1\n        if (self.tag & 0xFF) == 0:\n            by = self.src[self.ip]\n            self.ip += 1\n            self.tag = (by << 1) | 1\n            return (by >> 7) & 1\n        return (self.tag >> 8) & 1\n\n    def gamma(self):\n        v = 1\n        while True:\n            v = (v << 1) + self.bit()\n            if self.bit():\n                return v\n            if v > 0x02000000:\n                raise ValueError(\'corrupt stream: gamma overflowed\')\n\n\ndef depack(stream):\n    """stream = section bytes including the 8-byte header.\n\n    Returns (data, ops) where ops is a list of (kind, out_pos, off, n).\n    """\n    if len(stream) < SECT_HDR:\n        raise ValueError(\'section shorter than its header\')\n    r = _Reader(stream, SECT_HDR)\n    out = bytearray()\n    ops = []\n    last_off = 1\n    while True:\n        if r.bit():\n            ops.append((LITERAL, len(out), 0, 1))\n            out.append(stream[r.ip])\n            r.ip += 1\n            continue\n        g = r.gamma()\n        if g == REUSE_GAMMA:\n            off = last_off\n        else:\n            off = ((g << 8) + stream[r.ip]) & 0xFFFFFFFF\n            r.ip += 1\n            if off == OFFSET_BIAS:\n                break\n            off -= OFFSET_BIAS\n            last_off = off\n        sl = 2 * r.bit() + r.bit()\n        L = sl if sl else r.gamma() + 2\n        if off > FAR_THRESHOLD:\n            L += 1\n        n = L + 1\n        if off == 0 or off > len(out):\n            raise ValueError(\'corrupt stream: offset past the output\')\n        ops.append((MATCH, len(out), off, n))\n        src = len(out) - off\n        if off >= n:\n            out += out[src:src + n]\n        else:                                   # overlapping run\n            for k in range(n):\n                out.append(out[src + k])\n    return bytes(out), ops\n\n\nclass _Writer:\n    __slots__ = (\'o\', \'tagpos\', \'tagbits\')\n\n    def __init__(self):\n        self.o = bytearray(SECT_HDR)\n        self.tagpos = -1\n        self.tagbits = 0\n\n    def bit(self, v):\n        if self.tagbits == 0:\n            self.tagpos = len(self.o)\n            self.o.append(0)\n            self.tagbits = 8\n        if v:\n            self.o[self.tagpos] |= 1 << (self.tagbits - 1)\n        self.tagbits -= 1\n\n    def gamma(self, v):\n        for i in range(v.bit_length() - 2, -1, -1):\n            self.bit((v >> i) & 1)\n            self.bit(1 if i == 0 else 0)\n\n    def literal(self, b):\n        self.bit(1)\n        self.o.append(b)\n\n    def match(self, off, n, last_off):\n        self.bit(0)\n        if off == last_off:\n            self.gamma(REUSE_GAMMA)\n        else:\n            raw = off + OFFSET_BIAS\n            self.gamma(raw >> 8)\n            self.o.append(raw & 0xFF)\n        base = n - 1 - (1 if off > FAR_THRESHOLD else 0)\n        if base <= 3:\n            self.bit(base >> 1)\n            self.bit(base & 1)\n        else:\n            self.bit(0)\n            self.bit(0)\n            self.gamma(base - 2)\n\n    def end(self):\n        self.bit(0)\n        self.gamma(END_GAMMA)\n        self.o.append(0xFF)\n\n\ndef repack(data, ops, dirty):\n    """Re-encode `ops` against patched `data`.\n\n    `dirty` is a bytearray of len(data), 1 where a byte was changed. Ops that\n    read or write a changed byte become literals; the rest are copied through.\n    """\n    w = _Writer()\n    last_off = 1\n    lo = dirty.find(b\'\\x01\')\n    hi = dirty.rfind(b\'\\x01\')\n    if lo < 0:\n        lo = hi = -1\n    for kind, pos, off, n in ops:\n        if kind == LITERAL:\n            w.literal(data[pos])\n            continue\n        end = pos + n\n        src = pos - off\n        touched = False\n        if lo >= 0 and src <= hi and end > lo:\n            touched = (dirty.find(b\'\\x01\', pos, end) >= 0 or\n                       dirty.find(b\'\\x01\', src, src + n) >= 0)\n        if touched:\n            for k in range(pos, end):\n                w.literal(data[k])\n        else:\n            w.match(off, n, last_off)\n            last_off = off\n    w.end()\n    body = w.o\n    stream_len = len(body) - SECT_HDR\n    body[0:4] = stream_len.to_bytes(4, \'big\')\n    body[4:8] = (sum(body[SECT_HDR:]) & 0xFFFFFFFF).to_bytes(4, \'big\')\n    return bytes(body)\n'),
    ('syncrackd.syx', '"""Elektron OS-update SysEx transport, as used by the Syntakt.\n\nFile = start marker, N data packets, end marker. Nothing else.\n\nMarker (16 bytes): F0 00 20 3C <product> 00 7F <01 start | 02 end>\n                   <base> <start seq, 3x7 bit> <packet count, 3x7 bit> F7\nPacket (128 bytes): F0 00 20 3C <product> 00 7E <seq, 3x7 bit>\n                    <116 bytes 8-in-7> <checksum> F7\n\nEach packet carries 101 plain bytes. The checksum covers bytes 7..125.\nLayout and checksum follow syntakt-firmware-workbench (MIT) and were\nconfirmed against the official 1.42 file, see docs/FINDINGS.md.\n"""\nfrom dataclasses import dataclass\n\nELEKTRON = b"\\x00\\x20\\x3c"\nPRODUCT_SYNTAKT = 0x16\nMSG_LEN = 128\nMARKER_LEN = 16\nPACKED_OFF, PACKED_END = 10, 126\nPLAIN_PER_MSG = 101\nCK_FROM, CK_OFF = 7, 126\n\n\n@dataclass(frozen=True)\nclass Transport:\n    product: int\n    base: int        # checksum seed, from the start marker\n    start_seq: int\n    count: int\n\n\ndef _u21(b):\n    return (b[0] << 14) | (b[1] << 7) | b[2]\n\n\ndef _p21(v):\n    return bytes(((v >> 14) & 0x7F, (v >> 7) & 0x7F, v & 0x7F))\n\n\ndef unpack7(p):\n    out = bytearray()\n    for i in range(0, len(p), 8):\n        hi = p[i]\n        for k, v in enumerate(p[i + 1:i + 8]):\n            out.append(((hi << (k + 1)) & 0x80) | v)\n    return bytes(out)\n\n\ndef pack7(b):\n    out = bytearray()\n    for i in range(0, len(b), 7):\n        chunk = b[i:i + 7]\n        hi = 0\n        for k, v in enumerate(chunk):\n            hi |= (v >> 7) << (6 - k)\n        out.append(hi)\n        out.extend(v & 0x7F for v in chunk)\n    return bytes(out)\n\n\ndef checksum(msg, base):\n    acc = 0\n    for i in range(CK_OFF - CK_FROM):\n        acc += msg[CK_FROM + i] ^ ((base + i) & 0xFF)\n    return (base + acc) & 0x7F\n\n\ndef _split(raw):\n    msgs, i = [], 0\n    while i < len(raw):\n        if raw[i] != 0xF0:\n            raise ValueError("byte %d: expected F0" % i)\n        e = raw.find(0xF7, i)\n        if e < 0:\n            raise ValueError("unterminated SysEx message")\n        msgs.append(raw[i:e + 1])\n        i = e + 1\n    return msgs\n\n\ndef decode(raw):\n    """File bytes -> (plain stream, Transport). Verifies every packet."""\n    msgs = _split(raw)\n    if len(msgs) < 3:\n        raise ValueError("too few SysEx messages")\n    head, tail, data = msgs[0], msgs[-1], msgs[1:-1]\n    for m, kind in ((head, 1), (tail, 2)):\n        if len(m) != MARKER_LEN or m[1:4] != ELEKTRON or m[5:8] != bytes((0, 0x7F, kind)):\n            raise ValueError("bad start/end marker")\n    if head[8:15] != tail[8:15] or head[4] != tail[4]:\n        raise ValueError("start and end markers disagree")\n    t = Transport(product=head[4], base=head[8], start_seq=_u21(head[9:12]), count=_u21(head[12:15]))\n    if t.count != len(data):\n        raise ValueError("marker declares %d packets, found %d" % (t.count, len(data)))\n    pre = b"\\xf0" + ELEKTRON + bytes((t.product, 0x00, 0x7E))\n    body = bytearray()\n    for n, m in enumerate(data):\n        if len(m) != MSG_LEN or m[:7] != pre:\n            raise ValueError("packet %d: bad framing" % n)\n        if _u21(m[7:10]) != t.start_seq + n:\n            raise ValueError("packet %d: sequence break" % n)\n        if m[CK_OFF] != checksum(m, t.base):\n            raise ValueError("packet %d: checksum mismatch" % n)\n        body += unpack7(m[PACKED_OFF:PACKED_END])\n    return bytes(body), t\n\n\ndef encode(stream, t):\n    """Inverse of decode. len(stream) must be a whole number of packets."""\n    if len(stream) % PLAIN_PER_MSG:\n        raise ValueError("stream length must be a multiple of %d" % PLAIN_PER_MSG)\n    count = len(stream) // PLAIN_PER_MSG\n    pre = b"\\xf0" + ELEKTRON + bytes((t.product, 0x00))\n    info = bytes((t.base,)) + _p21(t.start_seq) + _p21(count)\n    out = bytearray(pre + b"\\x7f\\x01" + info + b"\\xf7")\n    for n in range(count):\n        m = bytearray(pre + b"\\x7e" + _p21(t.start_seq + n))\n        m += pack7(stream[n * PLAIN_PER_MSG:(n + 1) * PLAIN_PER_MSG])\n        m.append(0)\n        m.append(0xF7)\n        m[CK_OFF] = checksum(m, t.base)\n        out += m\n    out += pre + b"\\x7f\\x02" + info + b"\\xf7"\n    return bytes(out)\n'),
    ('syncrackd.ele3', '"""ELE3 container as found in Syntakt OS files.\n\nPlain stream = [u32 container length][u32 content checksum][container][zero pad].\nContainer    = 0x20 byte header ("ELE3", model, version, section count at 0x1C),\n               16-byte table entries [id][offset][stored size][dest],\n               sections, each 16-byte aligned, zero pad to 16 at the end.\n\nThe Syntakt container has no HMAC trailer (confirmed on 1.42). A container\nwith bytes past the aligned end of its sections is refused.\n\nA compressed section is stored as [u32 stream length][u32 byte sum][aPLib\nstream][zero pad to 4]. Raw sections have no header.\n"""\nimport array\nimport os\nimport sys\nfrom dataclasses import dataclass\n\ntry:\n    import numpy as np\nexcept ImportError:  # the user\'s patcher runs on the standard library alone\n    np = None\n\nsys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),\n                                "..", "third_party", "elektron-model-tweaks"))\nfrom mtlib import aplib  # noqa: E402  (MIT, vendored as a submodule)\n\nPREAMBLE = 8\nMAGIC = b"ELE3"\nCOUNT_OFF = 0x1C\nTABLE_OFF = 0x20\nENTRY = 16\nALIGN = 16\nSECT_HDR = 8\n\n\n@dataclass(frozen=True)\nclass Section:\n    index: int       # slot in the table\n    id: int\n    off: int\n    size: int        # stored size\n    dest: int\n    stored: bytes\n\n    @property\n    def compressed(self):\n        s = self.stored\n        if len(s) < SECT_HDR:\n            return False\n        n = int.from_bytes(s[:4], "big")\n        if _align(n + SECT_HDR, 4) != len(s):\n            return False\n        return int.from_bytes(s[4:8], "big") == sum(s[SECT_HDR:]) & 0xFFFFFFFF\n\n\n@dataclass(frozen=True)\nclass Container:\n    blob: bytes\n    model: str\n    version: str\n    sections: tuple\n\n    def by_id(self, sid):\n        for s in self.sections:\n            if s.id == sid:\n                return s\n        raise KeyError("no section %d" % sid)\n\n\ndef _align(v, a):\n    return (v + a - 1) // a * a\n\n\ndef _be32(b, o):\n    return int.from_bytes(b[o:o + 4], "big")\n\n\ndef content_checksum(blob):\n    """Sum over big-endian words of (index + 1) XOR word, mod 2^32."""\n    n = len(blob) // 4\n    if np is None:\n        words = array.array("I", blob[:4 * n])\n        if sys.byteorder == "little":\n            words.byteswap()\n        return sum(w ^ k for k, w in enumerate(words, 1)) & 0xFFFFFFFF\n    w = np.frombuffer(blob, dtype=">u4", count=n).astype(np.uint64)\n    k = np.arange(1, n + 1, dtype=np.uint64)\n    return int((w ^ k).sum() & 0xFFFFFFFF)\n\n\ndef parse(stream):\n    """Plain stream -> Container. Verifies length, checksum, layout, padding."""\n    declared = _be32(stream, 0)\n    if PREAMBLE + declared > len(stream):\n        raise ValueError("declared container size exceeds the stream")\n    if any(stream[PREAMBLE + declared:]):\n        raise ValueError("non-zero bytes after the container")\n    blob = bytes(stream[PREAMBLE:PREAMBLE + declared])\n    if blob[:4] != MAGIC:\n        raise ValueError("no ELE3 magic")\n    if content_checksum(blob) != _be32(stream, 4):\n        raise ValueError("content checksum mismatch")\n    n = _be32(blob, COUNT_OFF)\n    if not 1 <= n <= 16:\n        raise ValueError("implausible section count %d" % n)\n    secs = []\n    for i in range(n):\n        e = TABLE_OFF + i * ENTRY\n        sid, off, size, dest = (_be32(blob, e + 4 * k) for k in range(4))\n        if off % ALIGN or off + size > len(blob):\n            raise ValueError("section %d: bad offset or size" % sid)\n        secs.append(Section(i, sid, off, size, dest, blob[off:off + size]))\n    if len({s.id for s in secs}) != n:\n        raise ValueError("duplicate section id")\n    end = max(s.off + s.size for s in secs)\n    if len(blob) != _align(end, ALIGN):\n        raise ValueError("container has a trailer; this layout is not supported")\n    return Container(blob, blob[7:20].decode("latin1").strip(),\n                     blob[20:28].decode("latin1").strip("\\0 "), tuple(secs))\n\n\ndef build(c, replacements=None):\n    """Container blob with stored bytes replaced per {section id: bytes}."""\n    replacements = replacements or {}\n    first = min(s.off for s in c.sections)\n    out = bytearray(c.blob[:first])\n    pos = first\n    for s in sorted(c.sections, key=lambda s: s.off):\n        data = replacements.get(s.id, s.stored)\n        pos = _align(pos, ALIGN)\n        out += b"\\0" * (pos - len(out))\n        out += data\n        e = TABLE_OFF + s.index * ENTRY\n        out[e + 4:e + 8] = pos.to_bytes(4, "big")\n        out[e + 8:e + 12] = len(data).to_bytes(4, "big")\n        pos += len(data)\n    out += b"\\0" * (_align(pos, ALIGN) - len(out))\n    return bytes(out)\n\n\ndef to_stream(blob, per_packet):\n    """Always one packet more than strictly needed, like the official file."""\n    n = (PREAMBLE + len(blob)) // per_packet + 1\n    stream = bytearray(n * per_packet)\n    stream[0:4] = len(blob).to_bytes(4, "big")\n    stream[4:8] = content_checksum(blob).to_bytes(4, "big")\n    stream[PREAMBLE:PREAMBLE + len(blob)] = blob\n    return bytes(stream)\n\n\ndef depack(stored):\n    """Stored compressed section -> (data, ops). ops feed repack()."""\n    n = int.from_bytes(stored[:4], "big")\n    return aplib.depack(stored[:SECT_HDR + n])\n\n\ndef repack(data, ops, dirty):\n    """Re-encode a same-length section. dirty marks changed bytes.\n\n    Untouched ops are emitted as they came in, so an unchanged section\n    repacks to its original stored bytes.\n    """\n    body = aplib.repack(data, ops, dirty)\n    return body + b"\\0" * (_align(len(body), 4) - len(body))\n'),
    ('syncrackd.fw', '"""Pinned Syntakt OS images: load, patch, build, verify. Never flashes anything.\n\nSafety rules enforced here:\n- only official files with a known SHA-256 load\n- only sections in PATCHABLE can be replaced; bootstrap and updater hard-fail\n- every patch asserts the stock bytes at its site\n- verify() checks a built image differs from the official one only inside\n  the declared regions\n"""\nimport glob\nimport hashlib\nimport os\nfrom dataclasses import dataclass\n\nfrom . import ele3, syx\n\n# SHA-256 of official files we have held and decoded ourselves.\nKNOWN = {\n    "ded3c59fdb909eb9e2c3307b30a486452c8fa6947b12c14e0ce35a187b7f37c1": "1.42",\n}\n\nNAMES = {1: "fpga", 2: "bootstrap", 3: "main", 4: "updater",\n         5: "meta", 6: "boot", 7: "audio", 8: "usb_mcu"}\nPROTECTED = {2: "bootstrap", 4: "updater"}\nPATCHABLE = {3, 7}\n# A section that may grow, and how far: section 7 is read by the main CPU at its own length and taken while length + 5\n# <= 393,216 (0x40082d66; docs/FINDINGS.md, "Room past section 7\'s end"). Kept a multiple of 4. Only past its end.\nGROW = {7: 393208}\n\n# Decoded section hashes per OS, checked on load.\nSECTION_SHA256 = {\n    "1.42": {\n        1: "c920a4cbcc53bec448f990674541246d3028ebcc3a8acc5849abb01b0dd76e67",\n        2: "9fa34a8334548f70ec9fa62491e495bf768323e24608f4f3661115a6757b0f7d",\n        3: "1a9723b19fb54d0566c1f690379d2e6dfe43227f77e170ad731dd029430eb3e7",\n        4: "6e78d72b32fb1847ab33a00d8088f1259e0b52c235621bc8cfd1702a105f7ebb",\n        5: "7d97057d13e4630489f3d7aa22dcbcac36281f945ba8fd17082ecd5d43c50455",\n        6: "eec1379d7d3cee2633635636af84a19ca5907ce8a07ed4591fff22cb023482a0",\n        7: "daf6451cf9587c0b628e901b7bb6b25f4e2633d448c534c0c181dd35ec783bc2",\n        8: "6943b2f27773f40f1e7857ea6fa7a121269e930bd403098e6b6c00002327dc20",\n    },\n}\n\n\nclass GuardError(Exception):\n    """A safety rule was about to be broken. Never catch this to continue."""\n\n\n@dataclass(frozen=True)\nclass Patch:\n    section: int\n    offset: int      # offset in the decoded section\n    stock: bytes     # bytes the official OS must have here\n    new: bytes\n    note: str = ""\n\n\ndef sha256(b):\n    return hashlib.sha256(b).hexdigest()\n\n\n# Stock bytes in our source are sealed: XORed with a keystream only the official file gives, so the repository holds\n# none of Elektron\'s bytes. sx gives a sealed hex string back, sb sealed bytes. `python -m tools.seal` makes them.\n_seal = []\n\n\ndef seal_key():\n    if not _seal:\n        root = os.environ.get("SYNTAKT_FIRMWARE") or os.path.join(os.path.dirname(os.path.dirname(\n            os.path.abspath(__file__))), "firmware")\n        for p in sorted(glob.glob(os.path.join(root, "**", "*.syx"), recursive=True)):\n            with open(p, "rb") as f:\n                raw = f.read()\n            if sha256(raw) in KNOWN:\n                _seal.append(hashlib.sha256(b"syntaktmod seal 1\\0" + raw).digest())\n                break\n        else:\n            raise GuardError("sealed stock bytes need the official 1.42 file in firmware/ (or SYNTAKT_FIRMWARE)")\n    return _seal[0]\n\n\ndef _stream(key, nonce, n):\n    return hashlib.shake_256(key + nonce).digest(n)\n\n\ndef seal(data):\n    key = seal_key()\n    nonce = hashlib.sha256(key + data).digest()[:4]\n    return (nonce + bytes(a ^ b for a, b in zip(data, _stream(key, nonce, len(data))))).hex()\n\n\ndef sb(token):\n    key, raw = seal_key(), bytes.fromhex(token)\n    nonce, body = raw[:4], raw[4:]\n    data = bytes(a ^ b for a, b in zip(body, _stream(key, nonce, len(body))))\n    if hashlib.sha256(key + data).digest()[:4] != nonce:\n        raise GuardError("a sealed run does not open with this file\'s key")\n    return data\n\n\ndef sx(token):\n    return sb(token).hex()\n\n\nclass Image:\n    """A decoded .syx. Not pinned: use load() for official files."""\n\n    def __init__(self, raw):\n        self.raw = bytes(raw)\n        stream, self.transport = syx.decode(self.raw)\n        if self.transport.product != syx.PRODUCT_SYNTAKT:\n            raise ValueError("not a Syntakt file (product 0x%02x)" % self.transport.product)\n        self.container = ele3.parse(stream)\n        self._cache = {}\n\n    @property\n    def ids(self):\n        return [s.id for s in self.container.sections]\n\n    def _decoded(self, sid):\n        if sid not in self._cache:\n            s = self.container.by_id(sid)\n            self._cache[sid] = ele3.depack(s.stored) if s.compressed else (s.stored, None)\n        return self._cache[sid]\n\n    def section(self, sid):\n        """Section contents as the device sees them."""\n        return self._decoded(sid)[0]\n\n    def build(self, new_sections=None):\n        """New .syx bytes with decoded sections replaced per {id: bytes}."""\n        stored = {}\n        for sid, data in (new_sections or {}).items():\n            if sid in PROTECTED:\n                raise GuardError("refusing to touch section %d (%s)" % (sid, PROTECTED[sid]))\n            if sid not in PATCHABLE:\n                raise GuardError("section %d is not patchable" % sid)\n            old, ops = self._decoded(sid)\n            if len(data) != len(old) and not (sid in GROW and ops is None and len(old) < len(data) <= GROW[sid]):\n                raise GuardError("section %d: length change %d -> %d" % (sid, len(old), len(data)))\n            if ops is None:\n                stored[sid] = bytes(data)\n            else:\n                dirty = bytearray(a != b for a, b in zip(old, data))\n                stored[sid] = ele3.repack(bytes(data), ops, dirty)\n        blob = ele3.build(self.container, stored)\n        return syx.encode(ele3.to_stream(blob, syx.PLAIN_PER_MSG), self.transport)\n\n\ndef load(path):\n    """Load an official file. Fails unless file and section hashes are pinned."""\n    with open(path, "rb") as f:\n        raw = f.read()\n    h = sha256(raw)\n    if h not in KNOWN:\n        raise GuardError("unknown file hash %s: not a pinned official OS" % h)\n    img = Image(raw)\n    img.version = KNOWN[h]\n    if img.container.version != img.version:\n        raise GuardError("container says %s, pin says %s" % (img.container.version, img.version))\n    want = SECTION_SHA256[img.version]\n    if sorted(img.ids) != sorted(want):\n        raise GuardError("unexpected section set %s" % img.ids)\n    for sid in img.ids:\n        if sha256(img.section(sid)) != want[sid]:\n            raise GuardError("section %d hash mismatch" % sid)\n    return img\n\n\ndef apply(img, patches):\n    """Apply patches. Returns ({id: new bytes}, {id: [(start, end), ...]})."""\n    out, regions = {}, {}\n    for p in patches:\n        if p.section in PROTECTED:\n            raise GuardError("patch targets section %d (%s)" % (p.section, PROTECTED[p.section]))\n        if p.section not in PATCHABLE:\n            raise GuardError("patch targets unpatchable section %d" % p.section)\n        if len(p.stock) != len(p.new) or not p.new:\n            raise GuardError("patch at %d:%#x: stock and new must be the same non-zero length"\n                             % (p.section, p.offset))\n        buf = out.setdefault(p.section, bytearray(img.section(p.section)))\n        end = p.offset + len(p.new)\n        if p.offset < 0 or end > len(buf):\n            raise GuardError("patch at %d:%#x is out of range" % (p.section, p.offset))\n        if any(a < end and p.offset < b for a, b in regions.get(p.section, [])):\n            raise GuardError("patch at %d:%#x overlaps another patch" % (p.section, p.offset))\n        if img.section(p.section)[p.offset:end] != p.stock:\n            raise GuardError("patch at %d:%#x: stock bytes do not match this OS" % (p.section, p.offset))\n        buf[p.offset:end] = p.new\n        regions.setdefault(p.section, []).append((p.offset, end))\n    return {k: bytes(v) for k, v in out.items()}, regions\n\n\ndef verify(official, built_raw, regions):\n    """Check a built file against the official image. Raises GuardError.\n\n    The built file must decode cleanly (packet checksums, content checksum,\n    layout), keep every section\'s length, and differ from the official\n    sections only inside regions = {id: [(start, end), ...]}.\n    """\n    built = Image(built_raw)\n    # the packet count follows the container size, which moves when a compressed\n    # section is repacked; decode() has already checked it against the packets present\n    for field in ("product", "base", "start_seq"):\n        if getattr(built.transport, field) != getattr(official.transport, field):\n            raise GuardError("transport parameter %s changed" % field)\n    if built.ids != official.ids:\n        raise GuardError("section table changed")\n    hdr_end = ele3.TABLE_OFF\n    if built.container.blob[:hdr_end] != official.container.blob[:hdr_end]:\n        raise GuardError("container header changed")\n    for sid in official.ids:\n        a, b = official.section(sid), built.section(sid)\n        o, n = official.container.by_id(sid), built.container.by_id(sid)\n        if o.dest != n.dest or o.index != n.index or o.compressed != n.compressed:\n            raise GuardError("section %d: table entry changed" % sid)\n        if sid in PROTECTED and o.stored != n.stored:\n            raise GuardError("section %d (%s) changed" % (sid, PROTECTED[sid]))\n        if len(a) != len(b) and not (sid in GROW and len(a) < len(b) <= GROW[sid]):\n            raise GuardError("section %d: length changed" % sid)\n        if a == b:\n            continue\n        if sid not in regions:\n            raise GuardError("section %d changed but declares no region" % sid)\n        mask = bytearray(len(b))\n        for start, end in regions[sid]:\n            mask[start:end] = b"\\x01" * (end - start)\n        if not all(mask[len(a):]):\n            raise GuardError("section %d: grown past its end outside declared regions" % sid)\n        for i in range(len(a)):\n            if a[i] != b[i] and not mask[i]:\n                raise GuardError("section %d: byte %#x changed outside declared regions" % (sid, i))\n    return built\n'),
    ('syncrackd.patch', '"""Make the modded OS from Elektron\'s own file. Python 3.11 or later, the standard library alone.\n\n    python -m tools.patch Syntakt_OS1.42.syx stream.json\n    python -m tools.patch Syntakt_OS1.42.syx stream.json -o somewhere/mod.syx\n\nIt takes only the exact official file (its SHA-256, and every section\'s), puts the bundle\'s bytes in where the\nofficial bytes under them, a section\'s all in order, hash as the bundle says, packs the file, decodes it again and checks that it differs\nfrom the official one only inside the bundle\'s runs, and that its SHA-256 is the release\'s. Anything off, and\nnothing is written. It never talks to a unit: flashing is your step.\n"""\nimport argparse\nimport json\nimport os\nimport sys\n\nfrom . import fw\n\nFORMAT = 1\n\n\ndef apply(official, bundle):\n    if bundle.get("format") != FORMAT:\n        raise fw.GuardError("bundle format %r, this patcher reads %d" % (bundle.get("format"), FORMAT))\n    if fw.sha256(official.raw) != bundle["input"]:\n        raise fw.GuardError("this bundle is for another file: %s" % bundle["input"])\n    new, regions = {}, {}\n    for key, s in bundle["sections"].items():\n        sid = int(key)\n        old = official.section(sid)\n        if s["length"] < len(old):\n            raise fw.GuardError("section %d: the bundle would shrink it" % sid)\n        buf = bytearray(old + bytes(s["length"] - len(old)))\n        if s["length"] > len(old):\n            regions.setdefault(sid, []).append((len(old), s["length"]))  # a grown section\'s tail is ours, zeros too\n        under = []\n        for r in s["runs"]:\n            data, at = bytes.fromhex(r["new"]), r["at"]\n            if at < 0 or at + len(data) > len(buf):\n                raise fw.GuardError("section %d: a run at %#x is out of range" % (sid, at))\n            under.append(bytes(buf[at:at + len(data)]))\n            buf[at:at + len(data)] = data\n            regions.setdefault(sid, []).append((at, at + len(data)))\n        if fw.sha256(b"".join(under)) != s["stock"]:\n            raise fw.GuardError("section %d: not the bytes the bundle expects under its runs" % sid)\n        new[sid] = bytes(buf)\n    raw = official.build(new)\n    fw.verify(official, raw, regions)\n    out = fw.Image(raw)\n    for sid in official.ids:\n        if out.section(sid) != new.get(sid, official.section(sid)):\n            raise fw.GuardError("section %d did not come back as patched" % sid)\n    if fw.sha256(raw) != bundle["output"]:\n        raise fw.GuardError("the result is not the release\'s build: %s" % fw.sha256(raw))\n    return raw\n\n\ndef main(argv, bundle=None, prog=None):\n    """bundle given: the single-file patcher\'s own (tools/single.py), and no bundle argument."""\n    ap = argparse.ArgumentParser(prog=prog, description=__doc__.split("\\n")[0])\n    ap.add_argument("official", help="Syntakt OS 1.42 .syx, from Elektron")\n    if bundle is None:\n        ap.add_argument("bundle", help="the release\'s .json")\n    ap.add_argument("-o", "--out")\n    a = ap.parse_args(argv)\n    if bundle is None:\n        with open(a.bundle) as f:\n            bundle = json.load(f)\n    try:\n        official = fw.load(a.official)\n        raw = apply(official, bundle)\n    except fw.GuardError as e:\n        print("refused: %s. Nothing written." % e)\n        return 1\n    out = a.out or os.path.splitext(a.official)[0] + "_syncrackd_%s.syx" % bundle["image"]\n    if os.path.abspath(out) == os.path.abspath(a.official):\n        print("refused: the output would overwrite Elektron\'s file. Nothing written.")\n        return 1\n    with open(out, "wb") as f:\n        f.write(raw)\n    print("%s\\n  %s\\n  SHA-256 %s\\nCompare that hash with the release notes before you flash. Back up your +Drive first."\n          % (out, bundle.get("what") or bundle["image"], fw.sha256(raw)))\n    return 0\n\n\nif __name__ == "__main__":\n    sys.exit(main(sys.argv[1:]))\n'),
]

_BUNDLE = """
c-q{($*wd<axVBP1UJ1A1fK_O`vH1!?_KpO!ox!<sKgRfB?uQnzkAzf<{s`InR!m0!=GezlOQus`aIkC*?<3h{^dXZZTs8L|D^xn
=Rf`1_Rsa_fBN~af3Ef4fBuJ`|Lb3n@bmxp-@p8y|FM;SJ$|CRKha-*+y3=$KmA|-<0t)(&ivC)+fRSp{_WrYTz~raKX3oL{>M*$
`sJtp`Cotf<*)zpm%sfVf5nfb{<Qsa^n8E%<)450cWUP!fBIj){N+6VRQ|O6`5&pVzx<V&LXGtOPrv;8f1>519=7;=9(z`~?zx&`
t%|!<n@hoYQ_{JG?BcFX(XOget>1KtdpvC{8rA;i-=wZm-09NpgDy&^pvqBdby}&s*AnAN1!_rATcdrUTt|+l*D1SvY}%ZO>iTOf
fBVy4exZ*3_s<sp`*Z!}pa1qRKmU_;&iEK8$KU=^{uSe}dCOFzb2%SD@Ab6iIBRfwv}%tg?pvt2rbC@^JEJx3sID9}_+6bw?bO(R
{3javzyJGZtbtQ5*?;)?m-=6*JQNq)&;QRqTxr?QX?{v`F<j+TO4+0<EhHP<mDc`o+n$~Bhf~!Bnj~lTJeP?1DxuX$>Gh=iR8G_U
Zu@r9AgNrKe>cjU^flF(626&J{&p2@Y3=uryh^95(bIqW_xx`fn;T=Be%D&1m~PV)`lq+vI7`EH&eM0d6dSAJ4yRpqbxzJoUCG`j
PqRgJd9LlG^$q-4=~wFxuUz48r=x9*Z|2HH`3zNG-M&<BuTIl!8>0fxIn8}iiuNVXz0&6y9j^(cFU9>e8Cn^~i-v-2(UdwvHtwvb
v_xadPRX?JDN?3F?NFC^L8Cg)pw5K6^pBIxpq)!cR7JVylr1jNc1wwdMx)f53dzU>8|^mKOVi>a(stQAng&9}sAo0o)r3gjsgeDl
a}v`u5KV{UT0BEVH=Yd?cJ|nfZM)IXz_P{nrEs_k+oeUcqSTT#jpa;X!?ZkWX(=*o5Vs~=Yv;<GpvRuU+$m*~tO4ymn(OS#7Sz@c
obxHEwMlKvRkJK4t=wrSBi%Z5)$#^3+E}_HG5?jSqTjb;-*&p5rr){2rD`90)u=42?FKz=p*7*Uo~U_C`}nZ5w`n#*k}aS&+FP^<
=rcsU(T>pg?)bM|wa;b#^q5#|T*qgG#!I);mSn6t;*)QjwlR4_I$AY{lcH4&=V_d5R_q%tUk@%%7nbs&Xu8Zb9Yh_eLb_U0v_)5+
@?o|O=fHS8Fi9bQ2zsN=ZgWS?*k2hPHPV<{GsQTLB0Un^%YO9QJ?mWY&TVKls}QThG2H1G2G0)*mzgWI>S{TuQ5h~^PXn)tr-PQB
rl2BiDQuQA#TnYguw)xoklK@*GSWnb)LS)lhvAl>?pi!K$hTB8zhLdn*h?*&tYqLyQ2~uV@%V#rTv^lsXK<-3>xasSf}lrJNo8|p
x|*iUSM79H5$S-*!9*<u^tDvJVm754r&-5d*H-M+$`*S@v#IK7vl)7cX?Lo2TIoR31CRo?Y`F5`sc1tX3P$0gu1en8r6Eu#{Yj9b
OLDrVrngl#StMOd-Npcp!^om3`f<ZOhZC~g27c_XwqR$#)$8fzqzV#k2MiY1DJrbX{_@lQa`zSVW4hLTLhtXBeR5VOW57mExZyE(
>Y-Nem%*E@=rzN1gIT%R=Y6lO-V%13ZG+<053k*r!DOyg+;X|)wL0(DgNj$32+|;T)4`7_4kQr)?S7)yB;eD~@iFq+&~EkgO3j@P
?&>t{5{Kj9HZFY938BKc8c=DQqSUSvi^ZkR?Xo(?@lm7KubtBx;<3?z*yXyh8+Fj}brVgcJV(I=X_KYboA&>DpG6hMvqvwZCZgi@
XcHAaHo%&&-0bTbMm@I8+M*e2w_k^Ti<`U+{Sl?L^6j$^E!f~At=qQFYxGxz=9b_ls%vXgD0^W$c$$~&A&&QaUW+ADyvA(SSsD*R
^mwLaIvtUxyIY%=6~!G#x0f1^gD0}Y((_8&I1xcnvA7Da5NI#@&o2!oGj1vn0d&t0<wjdisbkGJozV@oEfb;kB0Vu_>@kP$l@8Ui
a_LTnM!ge}$+tqk^Q_r+r;mht&y6cZslKYyG|+`@nA)K!&~nPK3#5~C!+G3ablo>nY1>yiBaiF84@0@@S##7kBBp4T937Wso8;-L
sxcTfh%q0CGLbG4Q9*<QtrG68M6^!QA>tvW&iaJuAB0H}!iK27bR1{lONOX9B9(&Bs-T!<m{F&7s57-R-kGiTk?2Cyi^A=8EoPk-
l=!!t#?3WVO?&d9S81ZnT*0{Z{MN5KA~rdlX?|iZV^APPE#;$2BPz*9oDR|>e@|dg*K}Kb-kAR7zlBu&af~7ji%7D;DZX9E+4l;4
yI14=ej{`KVsGZcM%%BC-<bU4$N$hsc+tp`DaQAEvJ@OA<@;T<`big;4935|j@HI6WOn%n^gr59`XAp|1Dn3m@BCCULj+GYcLCP?
&zyCp<)0+R4-&QhDAB*}!IIJ3GdBJ<ge9AuL~>i1nbRfPxJ*<gTHFxVNsr)39B$bR9(Af6S0sqK%vYp2q7A|=;ZZO<<yoqXSIbfn
5%xxd1fY97fyHfNuTXK-a0BwUqXx6H`;jcY>=v&Se)k*IBaca<7jCo6m`IwVy467hNz3c#g_HEFE@xX_>%d}Dexh|xB2scbG+1wX
1c=?HLRuy=o?yMDO<gnbUYH0CB8A2?57m#GlE{uW7#Xx}gD!p0nz?7K^1>wZved#%a!@fkCYMZ65MZTB9ae`v3zj(8M2skrBSjXR
GSQj`BAVtd1$WK9R6>t_s|2zg>uh5{K}>j>oHnyLZPD%;Ge-@ynIPUUI(kj#nY4HZuTIkUc=*Dk9{!%Y630o&3Ymy1-mtP!S7sji
NIX@w6dYu>F4o5q_JZ|Oqqmu!j>Ns4egpTQu?G0v6H!QiC#FvW6KIZ?fTsB()1L^6myX2z-N%gz=ls>j&Cyoz&u*w_bMkj7uiGIC
c98d454o{f3XJC60RgZ(h0|#gTu9k-;%VIzmYIkle6oCzex}nOuXNr@bbnsLG&;PNULf2(L`~!Hu%H!GB&{lccl4cQRjBvW8%;kg
MKVOTU-e>ZV$m!O95O*rfyc4COX%x%+G7w*2=~nr4DheaEU<hn5phR-W%*hmsvZZ`fx>siS(byzCtVB*!fq-i+k2WUr|po>(g6lT
LRTM_<AmT%Rr<6TpJv&bI)rlc_~TSzsVaoq{d}zQ6Us8Zd@MZQz1f7irb!ktvU11S(lRk3Ikex)OyRE_9<AMYe!zR8i)Lenj+u^)
t6;&&Nx7v#b2UhfxKhE%7ABsBm0x;J4E&8#<Q_UJ(&DQjqQnok6b$y+zE0Z3S-oJ#23<0x!RgaAjU7j;emY`mu)-qpPjc_m%F!+<
-~+)nV26UvXZ3($4xDaH2i}i&0quB^mJ$O>=@xZE`ayMWZC6WuONYE0y$+ZpX}bn#2>b>bWASb*#3@0tO81fxk+8N)WkZ~%<>Jy1
vof0&a>ZFNp({baZB}|I!AVuqr!3o&>00N?vF6dxt%wI38|pgm@`!~%C!6ZS<HsFzb7z7LV}<F^I80f4af3$Z)Y2hpm>S6kb$Y30
NVyJ2g>s}xq7h|!uvF`PczqF41?k0x3F+w#NzbnuDv9}O3ri-grk$iPgs$W;xPX|bA<9|d?pq3)G;RpuouR*wTY|P2Q8I=pBt2b%
dR&5st0g560R@W+?J{3jDs+`5QzYE5({ld=M{o8uifE7PUA8Q<g|>_rncv>36YYN)(72=_!8uK%WN@)2K0YQEy$sHb!9i2wHVsn4
Ma_glr1PMxh2}&h*`55X(jwPwsOD;AQISIBP2*!kSI9H%=T3mxPdtGjI`9c{&(iWLX@h70YJ*jQ5O@0X<EJ{&Tjam`+EO8_pYJ7W
pY1-Qi69s>yjc?l<xe-Fu5)4<@|`kBBw_<6`4(OL=RQ^GEN#tI$EMBU^dLZqywN5s%2|=(NLHc;SQo(pt~cg`s`F-$?kvDXrzQ&l
WEuBE%VPE6+^ZV%V9)vp>=>k_Cv;LuY2(Y3NH=pDQaehUo)k(9gTPU{F~>G1ra^l?R-4AMt25?vGIQ`m>4wKSz!N+T3^O}KH#&z>
-ISQZ5Q-r27;Ek=F5htl5mnR#WuZDzpMne`TKi-}l#dM==4vNJ-0y4o@Flt!9ZkPdel=G%@zmcaZ1orK3>0$l``uqEiuU(eu(?rh
p51uFKX^TkJ_y4!M7V)y-nAaeJa%|a@`!~35{D@T4LV&hr5;Np0zQ_urG1WU;Xzd<P~xtcXRz)OiXr;V_VPJ{R-jJkeLsnDZ2G}{
vVWnj`01Ji`)4X^1%%Mk?S&-@2IeI6bRP6q)&;Mk0$X`NtxoT9a4a1MA#8{NP4rt0URC<El(s>lTunNv*$$l{Bxh1Bd3v;npicY7
52Ay7ff6<HLt=c;?=<2Xs0;MBCSKR>&}LD4^xfMn77&=3#<!QW5p}jvy?Y}8cN#<K6O5Pr<bSqJk9z_XfCq1j$riGmW)`H4Q(k1*
L@5(7kU`X5>={G~M1eRVd+;|aJyP@=D`cW6X`bjfY(B<Hh~(Z{x&fz^B5vPwCOfEHFVfyw$>Xs7DSsP4?-bU@n<8Wo-P2JMMUIrv
MH1UalS$NxN=<VETME87-KH!Xb|@JT)m3T0;4k;8x6QC|QtFfDXEL@?r0K^UHQE-z{z@S!DoJ0}5Ky74K9a0*hWw_`6q$|wq&5?O
{Xnz-;4WS=hBq$lr9kv=)|~toYyL>WGi3yW^!9wyS=XP4y*bk#@Y*jO_;If|y-8nv#lO|an>)<t@NUNVZQ_Fp=dbN!x(5A+=g^q1
%;Hked|`VUr$6b&M+DN6(SQAJBkI|HbCCI)v-4%bdMRx3*T-nxCo65eet*I2t9NM06o0@8oGT=%;2ELm19AHoxwcqLE}8V;Yemef
E)z-z@kS_OM;y8xF&@1zj5&xsJM9KKkmdhI4Etay;+fVwU8FAV_#RIdhrvREh$uG2q#kKd2SgS^8NniGrX93L;RLY{ESFfU{9s5K
y@;cU(lDC{KtLNFs@v0wjdM{fyd31mxrtSjlnK$PCc0auW;$Mv6EK-*oXtRDOvu$qy=Y$05Ul(nF$dlFdJ^rbrSa*-^F$A3E<j(*
Y#&S+r$Ym=>XM{qU8`mRj~Mb_#^k&A%_y^Jt}fl5zID$QNYn85(!@9)Y~e{XXbH_A)tLjjORdJv12-VnpUs$Xqa9Pl_6DCC%t~e3
J1Lu}Y%{?;sxTWHwz3mN<CdCbWvRqROhOs9s$`)I_4q1t(z1c^I2`yMM;l<OYqA%kfw`f0XY)h1R33LFmNDHde<>P<jL)B!oegAr
OSU184>7=khE9l0B}k{(4lgL45KMxs1ha=UvCu{FCtH5O<di4zfEjxzJi#z{r3uGE(1KKmSmx&aB$_EO)u(RLwBvZ>Wf%GJ49QIJ
*4H$bvWMcnS9AS_WgQ%?rhVScDXH&EwL^Iwi2Zu(ZZ~WuCW7{k26x-{PCRKp(D1jmcX%lRR9-W`O8ndq4yiR^5+U+wzIG$Jp6z83
Cbqn|Rvb=m-)&1}F3iHiHEBrIt{vH|2r?`c>7aQWyQNT=jAHv)^mGk(EddlR?f&AO5rp$zW;dk#M0$#ZNv!IpJ-r{=*S=C%3`{sr
ep?J0y$<R~llF}FT3czFs!GF~n~HW7bjWQfo0+)O$J>%BDXbJ<s~HA`{ThwyH5x;?ZpaWe7J^?Yx6ANwJ0TG74N>1kU+r=Fjab5Z
oWc+e?LO@ASw}sJHw3PsHY=FXZ29VGn+HPn$)1*ml!nbItyH)l+jZ(snO?g8&`~;_MRZe;2CZv5v9Q^#3F~FH4kyJX#$k<Bcsk^C
q>-mj4{w5py!qU=MO{iA$dmC4t(C&M(Zn0va`;RlN?3~c>w08WnCMd<7G)_iDAvAGTNjR~OFFZ*lGSL1ww5|-mui@dyYL8a(qU2Q
Z!qUe1@`;oFI_F~a~4s3hX!3L_{<h@&a6LSr{af9>5|dtA0ZL;(6~LNnWHu7E%P*FwfTjS84_Lis2<jcYklGkUy2P5g02Leq1}!U
(kf#QBB?Ds^)Rm36cGx_(i1>b1YNsUd7Mml(#kp&Pa^&6reN{C6V*|2gpyF5M{cB9x_pI#6`LN9_xbvs*b+&;3njuNQn_TB=zLhZ
?&c8}HVQKEMQRn&p+EV8Zo=OuFDVpF4`$7$*LAZ7o`i;<PkO55@C#j3K)D)F7sNigCS}f=E{qL-&(-_k#Q-IGwn^_h#K&6Er{dmO
VHK{YmFno%xG0I23MUOdJT7d?G*?i(6G_tNPb|fkVt!nPo5t|~0dC|@W5>`$gpevQpu<C#g@=eNj%Gn})1Tv)X`xCpvfd&sJsU}E
8&jQ`o|SoYV*ev$BE2ZCIBnRIn0b<Iy3H@^d-0!|he1TsuoSOp5N*$oT=4G+2jfKle2^*H@86Xnf6k{9jqzob6%~5+1}quO4^%}h
6@Np-6Jva5BGUI|Z(s`Ee<+gvSei~5@|PreG1)J?Q_1;n$*tm-^$$zo^u`*btl!C$KhKm^{4q~xwx29kwqIPV?BAG)MJX{QB&{C|
%h%-i^0kJY+r4aaxN-sas)e0#O$Tw{2Ih{<W*Bm+ZZFLCmCa^&sXAN)rYUQJoeccW?zJqROU7|X*G%K{@^?ym+PZ68cXLFC;rTZc
<Y^Ld2gpCRZkq*0i5~Y7ps(cbrUv-;2M-~ft(jTUWsGKQg+$L}QHN&k$VFY#l5wyBt4%UIbgdTi<E6m3)vOYmW0rKJKqOCPf7fn-
<>AQ~#@{B>-{75fh^*JGOU1KOG4UaR-$ze_r32}Rwo!>Dmetmp88~m6H?4t_6wxa6fFt|rl1mj&t{`ppeR`Pv$>_=B#ZFPJ$!U@(
z(KqQ*k1DYT?LJI*%)TTWPA$Ua=MBL?dtYYX`DEn?it*7-Xc6m_U2YhMChj2D^7M4P1sqwLi#vLVnh5|=@94ya--S7ZRx<&W&RD$
UR{1B&IF<mW@4myB6Jqg(EqR9OZ!gh->M^?jQ(r&Q$FIlX;)<Y4nik{lP%Lx?|J*@@zhVYt}kf(<nrUiVCZ5nd@-zE3a}L)musbr
=h-MSNNufV^IA3$^W%0gGI`+kL9nvB1ueDsg#=hxyJdg*L1v5hy*4c~`(wE77Ev8eqSL$=)N)h$$>Zu3xt4tVIz5qmw$CqTnzW&1
VC0X@WK+NhM4K1V8<rmXDiTX^h#*mruG>&22_Xwd*?==1nrop`oQ03aGCNz%mSAd9?FP0avx$S>Q!^wz@h{!wT3mcA|2t%Vle;3{
l(u*n@SQGPdD0~YVy2|YM_gl8%7gPh4Jz5iV6WMqcL`jhrn^VTkxVno-<WrE&Nj1r-^hNg7Rg3RL%zCs`FB@)A31F;#naC&%v6~)
?D<Y;KGkeZYD%**O^gt;HQ^0z>>z1#qj?yv(1lKYrmYM!)}(7(PD-|BGV7+hW!o!Vl$tJ|ZkgT8d<uM7FeS}aRXCYI+;Fhv8d;b|
7B);)=FLS5myc3o%tqK)zkwzt4(Z%!1w0La+Ns{bXD30h1r33VbOqwP!aNxJq6y<6r`J1;h87qbmC7Zmk1pJlD%d{SX&Lq~M0lQP
n>M#*l~g1ac4KoSjW*F%zYjoQQyV}6U=}iN`rILJ4z;__I#CY5vYe3vxQ?zqBZdtkPkaW+M<*b$l@Sz13Qmx?0DIpZz3CkZW$p*}
lkuZytZIkl`+SD;<hgNTAz&Vl%tpkK8`#EeDKPQ528y~hadM#Onn&&eol)@nCo{Jy5kH@!i|6iGcmM({u~>wtGXAY-mNG#8FE@Qr
09=?GGiuUx&^>F!t?ekV+{YEl7D~<bIkKOV*v*UJ0mB332P5xdd|s-yvt95WRf8;Is0Y@e^2l}tcmhS6)2l9ZU#gj~DlVm*2#yo$
4KJjaU@r%jrGjBnqZvTQrzLr~U50SEz@!W72;PL3Ojj+MG(lZh-bFgS(}jEichI_Y=!|9)=$1m`!UL3rz~+cz$e$+oWy!2pt8p+k
?^)L@ae5U5GpO9<7TxT>w{c+zJw9LgeGgY;e(K@s>58y-z^0V4pL!l()A(_gxH#hUENOBeL6(6z1(L839X67Q7Fmo44SW&$yF0%W
l+n(ZIpUH<gC$O}gM?9AtY{=kUD8wC?b)icPCN&MoYQ=^G~K+B>Y!U3C&>fABA%IDGLDXb#Ii5E#=|!bA}=^?1-d4^VrNsL#AVH-
j5A>qSy@SysNatax934>8~=Wdw!g=N6M=8-k6`AhBL8$V(~1mT_5z>gq0Agf<(4#%)$XPIU_<Vui1-*uX-Nu0bbGHb*yn8ppYsqG
9c#ik8oI0r0}N)H9xP58tY{&|<77AI$|lc=VUpyS?%Io$tVvCx3QO73`K7WU45i9WV1J<!$geH?&gybDlFX{M^%JnoMnlB+5s@$E
xT*PFZ?HXR*nd}t(y5956*)hje&U<?d4Yj=3VZwADqzt~e>>)%i5O_M+TA{c>tL##PHFHFX2M&yxo$*S!xpTrJtj?@Ohj~~DN~WT
bW4{3`pejZ0_)RFHh}G=Cm$WS6;HQafbE+CEvjn<Fw-VbNK9z~U<City{6fP6h_{TD78cz&e1CcH!)1MX9dVxlTUL^Ol*W_l@Q}8
x$gKzH#Jjf=##Ss3XTAZ0o_pSt{F{)`<Q_%n@;nf^u%9YK4<W--^EdWwzi?{W(GY##!^82ELrr-v0~$ixqkuiLIhM{o*Hhzp`|&i
+4FXzE?;6Gw##qong~{);{teEdret3VProB=%nt%XFh}h=2IWyKzyit3(#~AVw8!GlZb;`<7tA)(YJ*7L?{<Rp1??8w=^*~c$*$y
?Nd)yL$Kb-w=66J+18FN9^;zLIi^Hs{i4Oz+E;O=z189-u``fPY*-Q}hb}sGlRZEnB60{rk2S$ew=*4rQo$PYHaF0a6|mHrNM?0_
`Ll)CT}y;jTJCaGG{h9l2=9|15Xr-AjP91Ipw!Hb&2(`u@aptSfiPon=mtumE&GzjCgP#Z?TMArz)b^ZLv*et&ddi!y~sqAYfYD*
rHgA1HR1w00@z<Tha?v4a?S&I5N7?m>*a8{&K--xjEb^AIt9mjlgdH2qbqcKCTFcGbTL@H6;|lA4!BJ^;Og9grSb`E?9*QHt@l9(
4tq8kiNSItItPqe2O0~!bf3jQTn7HW@CSfPxTNo4P2Vc9ikklCu0hhXall}b20ITZ4K@ce5RA+K-3M(3XqVadmSL%OT%%(a<_r^Z
?>seYmcgC01p`LsV^@|!gI;*uyGhpZ^)<>3vIY2!V-1$-Cq&ZP7iP&2r?W$=8{|xQJ`bOcaE2QD>Xz%<;oXDv_30sk1^Vz8+wc9|
^v+nGZ-*Z<jy!;RlXBu=)`<{P{s@@u&*8T-y@=0V_o#{S*T1vJB^pg%Q8)r=R()4*i^9hKehlT(@VERjP%!@*t1qg+YWpiIurKzD
{Sn;xQepT(?EX^eQ;|;uz{@qR$;F)$CUY`f#LT#%sZa30bX|4sjLj?=HdAn0VG|xi=d_8FrzgfNXnlEWJonCMfVXP3KB6vpKjA9O
o(j=e50z?nG$0mWlkecqq|;z`Al93_77koiO9R8Ca`x1qJ`;zr&khfCch{`}bFqVf1veugxyl3qd7l7Osq!$maJZ?Morj*!fwVmP
Xoyw!&R25HPT;i0R4*8|sC<I0)~)igW>_GS#poHj0bh$+Y+jLhXi+tk3yO_rqs1#FZnHjJ+C)!J$;d<frWeia4fSEu&EA{%>@dmh
sF4Z4E9_!JY*?p*sl0@-lMQii9DpN16*R;ULLF!Sg;lV5OkXU5%_Kcu@^x!qvD25fPr=8s%{aT|&%UAXYw>r^%SlSZy-PDtE6CDc
d7xtozwSnSZM^d|bAEdJ8SjSlZEQ}F*@o`b1cjSg3Jt0*(~~esCd@wDDI)8TC9{UO<L{lUpeFJk8Y6qjeWW#b>##DbvQo=!75II7
4GApj4#iXS#AwnbA>Ub(8=WcqH*p1w_t!+h{2TPJhT{Y@7juY_i-scvC8hlo@pFL*E3t#49lDIJc63v+CEx{Q2F5X$%qp?=fBdb+
cf&vg^R!G{uw#4r<{ajhOy(W4MPz*bwh?PQm=m8FC1#(KCkweACS!aq8Hbg0x9w3UG0k<oc(4H`ZP%KxN)~8$nZyFKP2jnr2{cO)
y3kxa?qY8mS}*5aDw{kbZwW&zK@@N7r2#4dECnrpTe|wfIupYxU8~#J$7aXNnUw$_-O8uQ$pD$ywzWGSH9gSWfw}PH$qz-*nsgnX
u02|kwf=oI3rpkS?F$IdVE)JUbgDe7Z}~){pm|DF0g>Y3n*sH9bF||O7j>1k?(-ARCoY*6IQCrJ%$}3Yku)_gIMxWmii9mj#9o>&
$E5<h*h#HPLy^FSF4L7X*{v)^-1G|k9U8O5yD`h~Ar-roc`(*ZO3-G?A`uwYZ2lp(hXgnhlXw~yj4&K+^Qf2x>S{)u{|HYA*McN5
4ta(jFNbm2LA(_<rYe)CChVk=Ahn-oGh?ZuhE@&y?7aM9r9HoN*iD<&U$Kd#6Qwy$tF^&A>GGGVd>9H1ZCWfD)p}EgNkZ!p1JH8C
Ak35jFe!uuR|px^_ymp{@mYNweuih0aR&W0tDg^ucFba&pu#XtcxN0;Y)%MjtowEA#_;JbNZ${iho7K;gI<*jY<ymjOA&6VnPCvg
f~9OG8OH3b4n4d_+u(Y%Ajf(;Gfi&4Aqw3^!0FRM(r|!|eeQagp0U(S90U)yC^zi88p~1=m@p?alkH@*8-^LTP#e@hRBNo22WyQf
io!PAL$ElXuQKJBP@2Gb{gK2{iIsMkq3Z&L<7B@C){ac#>1|E8g_5ZVcXc`9(Gi^C{!g#oe=jWjoqi<<4l4OAP+gV=!v9a~4PFf}
hx~(JX;4{?PiX++JM3h125n_?T!SqmjQhg2Z}25=`=98{%;!{ietGQ9>fNf5_l3<+j}7=#p!=;63CIa8gxG>Z+YX>vqW|P!Wpr8)
1`Vi!4bl&`g8@CM_(3iz>vk<Vm@0z=rMB6mmD{t>KbIudh%G3d^g}iNI2hr9&FH@w0l$ije_SLY8lERjr(ffVN);IOlq3WGwYy^o
6KAGdgusrXQM$OO+3Yb;gJ7L0_;+m_BSn;QrBNi{5EzJIX>JJIGQ0-O<ShyFN;M2d5P5}{Ef%I53LHWNhL^4>ESI%`4NFxCaNkg|
#*KJBhK%>ksI)M=FP4^;jYGguw^85H>|k(`UK6I+K<~5;Z|)SN2S99Vy>Q|<DVqxQwumbD8y=f&!_j<S`5cVtEYJP*n@IzBO+tI>
bnvG36^2*|BEDw1iKmba@>F}f)AhVw<+a74{l51M(f#`A)!_Uj$Yfm5iPa6tk4HkCOTxrOt0iG#Tiu)x27_+r5_&SZT-wl+pnYj0
Orh*<Xr-VUhDpO?qF)p1+(XESUzSW0JkUeQJi+qb=Md6s|EgMCT(3}BV{|dTuGYn5Uzbe&gK8&ygL{W)B;LK{xs9yBzwia)#G6~U
w?PL)GbjPhymWr)Z+=}Q>>^x?n0+vUMnaS!OItM^)@1v47&n7>J^(pU5(kFzEUs$YCGs@6I>YE*e#i1zyWspVh@^SArPC8yO)aAm
-yIP8r;^Xge=ik`6|0?D>@Gf`7TuY_=C@rNw*4()Au7tNSHpe~>3H{Qm<xFQu7@ZxzoT?p3cMX`2btYx4wT5`zY~fG1>;w7vr#BN
b9dx~XRbC0N>DSaU)H3drc!G{8p3s=Tl{(LU>EuO?lxL;*0X@-Du}sa_?;2KvFvcVii*#MX)pdhc0cka=Bg}Ac65K<S}Y2F+U73h
U>59V`tNpF(vp3KdcImsLwKpm^gT&1yIoCr0hJCLr>n>8NiUDD>3Lv1Ar^u&EBD7K=cg$!Du2g)nF{KU)VfPX^O=J#GTC>}Gcvp9
yO<K5Nz-YS(=aW5dBt<KJlnLxLGE;iE(Uh(Aj33AP4s7rWWoA4x{)jVTY(Wa97!!lr;V%(3ALt_rZS+@5!fh$#2w*$91)_E9SwCT
&lYdpMU@WGxn{~s(2pwy)YThX6FicaLbG`f%Lz@kc#2%{Ywc-%_9Q9?(2ooTHO3Ts{0s3^<Z*97LLE%iMKxQRrkgiz1W<*Ey)q5O
BnMl?gk?M$ku7y>?PZp#C-Aibu}Jst6E6X?Nf3vnNN|&dmtr=pEm@Bkv1E^vW!+;K2~|zqFR<o@*aZ+2dX_VIjnf!^V)=Ua?QE4r
4d^LK!s~Df$Y}g;fCzz#{b#QkGKF{FM`Vuq>7k5E9K#Xa0n;}Hc%9hAHP1v!zF;AVTN>=+F6?7;7qfOTe?dJkfAoMcXclop@EvCs
%rzFwZ_n7TB%J2V1ln!J#$I|q(J${YeK(dfO#;*W$aLY|VNA@%wB;&HTVbYc?a82AS5|J#HSPRzOBv<o9_+3P3f7uCzXRH&*+BHG
NGe=Pe=Fo8!!djXU7Aa{{GA>K|9sb*oYr6=-3QI|_&~g;N;GpR;@&TkXTPTmytrs9Q6-0*3n%;i1V}{DYiJ-g+8)Nq>{y*OP=(+d
%&xQwe!^4}y(tE$au7VIZkPy1%L=!LhH_yKue$ohD)EaHzth9X-`djN1O|hEGI999!l0+z+o0XOji}bUz)ljM#E%)bTs&$j5kUl<
XR$}Gq59E7$K3j!zI|(=2in`O?**&FZyqXDA*fpZ!B%Ztt9v^NEpmJNwbNzIJEHKlMEW&$IjF&^&q!6yrQf{6tTk`vv@hO5MBErU
t@p=5C&|95@z>H0Yi-}z`G|G#-pn9Q;}7swL`_<K@rEa&<J<8iQQH2no(KQtZ0WnW;Fg--KeJB1`&K)nUhUp58%uv{evGrf?&Lf3
DSRB~`j!zjm;4sGJxW^jl{I_&#&NH19Bs`6+2Ga`XJ*6XTiOiGaIR^7QEr2#H#682#}2!+^sH}F4A?8+lA^D>0C)XWuIueuoW-@x
2d6qqWWW{ce$w>8;iNQW34PaHk%I5Zo1RCD(g{Xx3GnY`QbIXcQ8?htFSaV^haKJy>)7WYlgKw%(Pn9Og^CMjuFfnR1m%yD9g@D}
VHS8>VmP4m0($=|P8dAq>>sO`UVD>%@6cRm)!VOgBvk4tXe_1V3489sQQJ81Kv-OOIj^y^5AS)xI~Yd=Qkcm)k-dfy#Io;*wU*Hr
dyM$j#7frfTyy%FyFSA$HB3h8Vt67JGi$D>ZYMBQIy>f8SG@bj>Qvb5Q>;kNz1ObT!2c9(h|&J#JEJ=ftCXg6Om_SKuF=FYLsLM8
zgyD|?&tH!uTcJ&&&98j?-e*Qr%s3?&r;)8UBf@>$z9p^y;@TKN-ay-sM2R;*Zh<Hc9Rp+0iqr-LX|zWhFc@fyx>x90ti?uG0$3L
-AT#-kP8mc{0^^e3|LA?HB~-PbH3$?vzI!YchSzFxE+xZ?}B27Uhe4lHsfY~2`dvVP5`hR^<Fh2kq{Ymv6-DVm_r8q+hf=bV<-YL
B5}AGiKS~EYj?{UTFAa9k+t3g<5B?E5|L{G@nslZdaY+5tMTYu&H%lH3j?mRsCR9XYBKw^WS*$5^Mo}8_m;69(&J9Z6Q6TJ($Rnw
YxcY9F}Ecebx3Q;>6K|#cCNuFp4-FT;C*CF2bSdBfc@2Kh9*q%=mtKiuRS1n;FAXXDcTPVjo9+nQ}zsfUioJWO`~DXC+*iN?bD~q
4b)O#AKB9uqwgb@d<WxtL<ISP2<SM(Hj3(;HFH#k>e%7lV3zmF<r%;Rlb_i=tHURnK1&D7%(Ti(KZ-skRJ}0}CHFiP=~0$hv1g0F
+fGbP4l^3~ATw^9V~CW5P(?sc)1Sm#roL+XJ${8sdi`zAmrBRyyafy(ChHd$>r9`}j*ic@(2_RfAW5iOv(gfjXEG9T%?vp)x?P~X
^@Jwoa|?=|RuG7SSv3mZvsqbSegi_u(0$LA_T0ez7t`D303%M8<w)?*Ocq`xy;WerJ()8E;Qn%eY=*tiKSahrHRbs26;I0RUsc*Z
r;(A8pQq?4{6kf@lnEXOwwJfmJo$q1N|`2OXK8j?b5B4WUHb{mE^ZAVxf}pY<<CO*c)~MB7eJx~r|)Y`gQA8#P|xkI-2DCeJ>14L
^e;VkU{tj=*Py@>UY2}IouuT|z&%85cn{ezGVF2_4gdl55||&gnO_ySglqVUd~7Xwx29QB!~2qH%6*sV+*0Fr`}ovvQzI6ydu5P@
RIgrH!2xq~@+6rY0+He;Kels8N#T`s9Fa#_&wgra%0yA_OG=t!umkNobi^xICv>@m_Vq&T%Ra$pLc9(l1APMwLHIgB2k#nOl~@%|
&$-bdH)XnO-&3RI*hN%aI;l-cgXJ0i<LJYo3Ob}>anboeL2yJlD+slS-37QZ4@zZMm(O}s;-0FD6+|<oj?^Mzcvyl<wBimPI$SW2
AZby6pPNTSHh9C=ca4UaCroj!b=L23`hac*l>{H=(5TPgK4{ln?Ow6u5DEsdjMUr$Lfy?K8PsEV^V<-zyqQjyl{S)A);j#meFet%
F+I#8E2?>}D$uu8-9=`BX@hhR)Us79uz-nST5Ha;Nf%SdmW2-RM$tfPTYEA|`9a`gcZfBHl+u9#*5v!;VHSzj>b`u>dW#;;<&dX(
A}qA*;I#+CgaVcc+qtGrZ~;W?3p|5b$2>_+K!mqeUHdH4+|{mIz3(g9IKu~`#ZeS%Hqn7X*0f(B(SnNwI%hZ$HhF6c;&ZymX;5)s
Oq!!gw+lq2(I*4*w#3s1+<P_!QVj`$t?)(vy7bWunP)t1DdUFOdY?5=BsvOhkrPW*V28_Z2cI%}9=p+BF9*MgrT$6N7n+xnVfQH+
VOjfW^#r__?rCZAH&xuLYHxYW<aOWTk(H~pdOxWgNT~=&HIx5rLvo(<XRN9oc)1aKC$W_Xc9G;o@J*n;30?woZ*646xLdTx^O0`n
-;SL!#(&K+`?u9J1w`8rTMD?)fM682{{xX*&B}?w(sS78oVOG^NfL~j=Y;#XIW^DESYPyJ4;T7~VkrxB`}W$`PXfOFSXmeK-|H{w
5>evIk%qaHdrn0lCB8_B!=`<eyN&>xlY~_O0aRU)1Gt`;pL*7F+QeyHwGy|wJ={Yv&pEdiJePN9-4+c@i=YSTcC+slZ45*Iiw+3!
%!X!WX(tW)ooCt_zKw1g8@Zt(-|Z9J4c9iIBtF;y&)^2*`)oI?-CA4LcL)Wj1}2@&$)dA_u@9{ez`*d>0@Q1%FE8@coA!tPIQPQO
w9FP->vtSZ%6by>M2%uZ?4Q;E7_3If+N*Zc;fItt5DYF}W9h%^$oJb-cABYmMkd!is*N_nG<RJu$4;#6JJGG>rCs(2T{Afeuq~f`
C)7FTbl;-$Q8K(Zp<za{-&fk2wy%B31DG%&G%vI~J$7!=yxi(^Fa3m&I(sTTq!OWf15T%-d``|D#F&IBa9x96N&>&68vGKVKZFhy
*^6-<OUdQ6rpZkILSV{HK&)H~Y78lAgZzbc)&_rS2bW80Hm}5%mtIx?=vgt@rS<k86(FtQu!m}CHE1<nBevbO!*-V%3@3t&Zvo-^
&;!sG!0OvUmwN??o;B=EqXhhRLu7}9C=4B%4?VRlJ_hDx-kCHJu`rf-Wto((#avia4>7_Al$1mlo{*#ZyXNrv(qLl@<IO+(3;@+!
^X(`2O!iHDCi@JZN%EX0`<~8D=a}<21sIrWc|>jMs8d+~0b2zp!>|Hsq1H5H54t?g^@Lk>&C8ZQf__?S_x1<E%5jb9sVx>PAJYQ2
-{zNY@vXA$Ll5G@C&C$_$rq$1)M6)~^8-|%C1NZNYTXDzN!2X#Nl_z!PSMHS>lxB6NSqrDPy4>n@N6?Z=xV$$MR&Su&=dURNqkDh
HuW7Q!j6bLO5hyK;5Sy@q=A!bMos{Ut_E+SRFmlz!S0qIqlQCGv*ri3t|se}xE#n(h}MK!1t`d7X>P$md7Uetp-neRmf1WF(Cm?C
U+%%^CIABy_S5v>LwuVMZwPw01tn4w7lM(PU3U=Away8r9I-ly48E<6pWK!Yoo;Dytea@RQt7uR>q^+U!6fu?H;hc-pjE(I-~G%v
FKf?gkJrOdVOlJaDOwUs657bte$4zFLN;sF;8NfdWrqc>%*FIKILd`X>EGFYc<d}@<CiwWkoFE6cp`z(dxmzodY#twn6!BQD1k^)
_-(Cq58dBhWIpyOYW3LXz-wRl>98?{(of*@y}%m(2k{{`M*Wr@C32elC60wkxaYSPLTy~PdWGME1|6U;7)JUukx_>ahz%y}L<uM$
S}y174p$ynfv>d>ody&ybTavUcQGO~6UTK*EJ7mIzlaSvTv<<>fyk0!nZDGQ)D%X{!IRiiY1U5y$FO~e2ntqQc+H~JPSkXA`p9xN
%t^;AXD4;&>@}Sml%;&*clw{MiAJ6!&ETvMCEGN2#2|?$pe_?W)Iz~V1e)NwOp(5EpLDgfr-)Q2xXg$3{07k(qDax9$~1bLHkRFw
aRy*PN%_QO_t46M7E#w6&}$11kw4y+gaa_dFLTSzDDy3SCrZ9=&5qpu+wDBpj1mbuxhOX3T1m(@J#(!hsRICp8NcBby{sg4|J}mM
f_B`}%ECFO75{{>O|oE$FdTJm_#^Zi=-_Y$y6#RyMsoryTiR!8pUnqYxH6En%|-%}T386wj(;K`WU5wrj|;sKx~#pNWWN0R7$9<0
SPIPfKrvs@>cD3>u9vY<WE@PJG7s%oP{clc10#hFfJrxr1=TvZFOK3_aXHXjR_Mr<(sUO|l<T%mv)*j7tP_ta!I7G+<r*9sz_HwH
%htX-0oMQ(rU%tun>Tey;j`W5w6R}5MXTNVl;Y|3x!da1I`w198*(yVuwO!cXCLzG&n%|cPUEaqW*eXZv=RmHI%bs?ELyY5xf#E^
++!OqJ;`HNAugawT>{O1q(OtaY;d6*$W%?=yX`Q2-}$C@7iVG^G0PonX(dq<{j&3@Wj}-e(z}5(dBsu0JQHEc0d#<0-_sB>k$Q!9
2GPr?`MgJ95tfW%11PL2nHSjR?B#<<h}G#PhqlK&H()<T4{3~BYB@`jHQ~1+znN)Xb_C!Obg?TRVw8pn)LQTA2%At-;3s4H=Iepj
u3z8xP!)YkAB~dcxhytEJq6`G=o+P+dfWMw$N4*Uh^L#>8|R<po;7Wphqx-LTf6M)J@1IaB{|pB$=Zfv#5ON<1RQu;TYAz@v*f4J
rweR4rW^xoaXz)ke=_Xyu9hLfr&+<9O0^KR@5-9jEFpiIp4bUTBX=fUbDD2Xo%r*Hn#i@d2{!RGqQ`s^QWh^Jf)|Ouzr26y9zAx*
)bYOXHO~~<xyab5(o6Ho?~g?FqVae&=cf^6jzdL6F3VnodjY2KcGp@H`Rlrdy6Y+TO0TY`zHpdvgs$LE)sPE29AiQNuNILMUAkQ8
(GP$*H{40XXzuKJ*<YtnA_IER9Hq$W(BR=VNxud7NAJZGS-H&j<iQ;*YY~aB2J|W24I2y4JmV-Dng@;$j!>$%{pN<Z$!x>JDMQ0S
<+Lct%%vBnn_4T5vaz-HSi?)BvVnL#w25*o{#!NK2pYQDdnz&X!tQdnoRf90ex@m(W;g_*G=LPxT%`Ak^=H(d=2gByFAvJe5yjDb
yH^;<scylo+~*ba(2RoC!Rjo%^urp)@SRLdGF!>AqBbNYt)|+1zZ3BQMDbV&Bj7!=Mj77~N82+*j9GyTH5=P21c*sxGM5#gr!T?`
V4bxv&T}s%K~bC)hcP$@uC=V?Cpsa}h_mcRM9$__)kaJX%)`otpl>TnJ6d}_ExK8|Za2FQ#10^SX{~4YY114S)`81PmA+CP8m*7S
GIqVp?+wf|?(0nzr~5A4Qijy?#K>y~wM%=4gJ&|!u<GfkjGN_)y4_9GX1XX!NO)*pWVazi*LmyBWUYXB+=h07#CIrcb&Cs)Z@>uN
1`vg`QyBdqu(fS~i86W?Eg%6Hik&!9e=;{5RULDE0Gb(gX-Ucg-Blq#Jp%Mr+4EcdjX2I6Q~0*8CrYQUYj=rTSN=y>Z=xpqN5P46
>o4TnNO`IqLmX)Tz#kBUp~DWmG@z$NL_Jnlh_}MLm=fAj1xs{f`yDpdEYEIfOtsE7IR?<xX7ZMEwuen>;SwQdgeCXh<#f~<+u6&_
5MU)K^5I%9$YZm_G3Qp?+)AfalF<66=HFoMRD?#^+4=|JozDwQnepL{(gK^DlT>kSX+%ApIebnTVH=X*Ef_`strhig-3?G};r@$4
&~<_9KF-oUQ~PwRQ=^-Yk1Ak-`1i`eX~Yu8!-7D5YgRZgonHDjX;wfB?HfYawE2cCzezVv1xO{TslrzT!Z2V|RK0C>qY>!>tT|1+
Qew@<Zy7+Y&Ay}Dsl>OWnie`|?N#cu80R6L?ppIAv=N%LrPHH~YloYaSUaN20WRa=Rf0NkTN!p;Rf+plA@xSQVVa#vi_W@0rgU8U
R2+vG{Yhd|M(;;CXp`V3Gy=Qc+SJ41SackW^yf|EeI<{ZXPD-A&?ErBsj^nP#h!yap7$Ng<Y5)Y(D&fOcD6od>zcChngX#8>kj=~
m!dRJ+q?9HdA+UQ`Bkkw8mJ61?xhBoYp0>-b-Lm&BnMn4>b2}PIx+l-`G6e|5vxUBh66EmkC$r=emS|lA$~U-vV;)@8MVKUI`mP~
jN!cd&qp4r+v}ki!G!z7cZ(}M;vpyu*tsm|hnORy!wg9)_r{uI3d`NNo~BtL`Xn))k?5FNZ^Igwy9I4fwFOv*%pMT}tDA0t93e;H
xljUzi&&U+tFHZ+Y=Vr>=QiRJ+}7R9)bW~fw}wGI2n*9KP4M^Un3fDxx!irTo!xr#P)ht9>T)eHB*FrKc}pD{kXFZ<J_6Cdjf;8M
*(U2L1ZIzh(BSoNwx?)!AmNx+Qn*o~6j$GO_OOQv<+l28hB{4?HMTTyq*}DO5|rjK_RQ)93`>ykB2vxh*<mj4UG5d#r8PD0UmFaY
m);_%aLw8O@nGpokG_QR`FU-xXeUaEFH+Kw`1C*kv<Y;Vq^@}<PS-r9PW}Y;Not%z9zUc`HtptO<sNg*{4@8~iPZN|?i=nB;iaZ*
R>@SjrLJDMtu0n3bB$|mw{VHN_g~*~-RfLZ{VK~gx75{B*{-Q8mwK=HB?z&kzVJ6*bH(^huH@gB-y?s1py%gwT7LVw=T@osQL5IT
_t?&~&&xa}eAJFrACJL?&s%t+$50>j+J}$Z3~!9xW&P0eAx{Op>dcydXoeh7Ezp13>da%k_G!R%!18(!zR>l>DU1h~aWD4QS}LVa
wL22=Z(|=Lb+k8#-k(y>SXhJIUdXh>M?!G)_Tq|EMqb-p(5G`?DsjBX`)T3P(SI8+ZMU`>5hK`WW$0RA&*QH2N^GJNYX|uovnswy
G`o(YhzZDk*sJJf4Pz&<NN$l<!QL=0yV(KJW4R0b<mtk7o|hePD5^=3f%ynxPP0_c*cxaapN>mS<6<gu9v35$Tz`A91QSZriDg)$
-8h{w%j@Y_+N~n|2dd12g}f@w(PjF}E)wrzKvxKL?z>(HEjOK#Dwj<&v{Ws+%p`?JTcv#_`8=F_mIu1qPmze-J!SINTvMj=coNH6
ZmDsWw(7X1#_25IQtY6TZYlm5@+PO`sV6F#H8st+asC~O!`tULUWR$Zk8Y``{F7U6&2hiSZmIsm)cjFuv>&F%k5bdESEp!|Z<3v;
@_N7OnJ58paXioX^ak63$iwoYIYgr1{cxznCn!GYj^abVWxygA@fYj<G7o_gm*9rzx1OUTPPOf`Px=VD1$5$j4SDic6K~2x&w44x
*rZDtqb4eJ_P`*1@xcQF+K71FJ&Q~#$XaylE|H+C(md0uNO{03itp&!he>i>8_&^X57Wrm&SiKNaIBy&dV0*B3(_m?h<Ss_N)NRn
zALl*pjnPg{G51No#O983muo+?$l*?b}Zwx6UG13#{+qyfAsNKb4=KoKiu=<Dtq_yXjX4yJ(roQedd;)PB;nA=CiN!dW%LECq2mh
9iY^3^Oz#O31}WK{7s1daEw7EwjE1de$csEFeaQ5?Zvrr#?kAiQgdSg5%R%pi}V+Cz9&+TXpZXbntw(QyQPfTG#9O<W1Z3XfLhMd
G}s%^>0fJ@IH9tpOmD(HB`z^nZ9CaXTDK$iGrhyN8MZV3f*C$^w+WD-<~^#HgoIp6<^}Y=d7MkBPL-%L43Ft(4D5cDk3i^A5^Vdj
?mC>@e<y5dy8Vn}9PmcDD1U6GpdI214j>Rg&Ir36yuGj!t!_meG8PCzcRVBO=zucLj6IXnn=aj=6P5}NvQC$p)x56pDB4tIp|ubs
B?TOyidUwV4Q?oBsVU%M-b;dt)1|yEvur2ZF$+0%qhwQ!Riz!M;sMBPI7_zl&$WgjBl{@Vbe@U3-CVOCx}Pk{IcNl}W>gofK$FJu
iQ^y*A~mOLBtxgTc_2B_3amAb{Xn-5Y++gN-Fy@SqBJ&KKDnDY%45?VNPLJ|)*8(ufs|la%1mf8;$gm6URa@@ZS(X4hjFA(;NP^?
Jcav)r!w0Q3Wsz_>wsVo`rchjPsp#nk8;g1@%u?aa!zBfB}`+7#B(ieC$IZ!%xjJbHQC?hIjwDNb6Z<OuQH-xdYsj@l~=e$w_N%8
&1-GYFH`J~M$tyC*}u_Wr(V1il;VGDd|kBS-ohV7PXAnHx!ClMSIT7vu6?omfd|+uE4pk^f|>o%rckij9Ddj{VBg@rwvBo@&tQ7^
TI0(6J-H1Mfl?8v)tQ)Y`J>W%j}GfP>eQ7+_uty<^qhx7%5=8cUccnu#72wf<8+px%Nk=FlKY3aji_ClZ($3YmzKWtoM<yqM9@f|
1^fr}Z>+I)96Y(MWgeq9v*ZOD$V-EG#j3<uZ{=rOlTL@h>HpG#Y%TT$yfAqOxqTN+YrB<LhQOXr`?1%ZR&Up=19hxpSAlzfz?NKZ
scCCPj^QgXODg0Xo%+t|qE&n3P^O-V@2Gbgco~VAxnYD)>{1T!08uH?<CuH+OR<J+Hi+=$G!5X-&)(Chf8s_%GGafIPgrN+t!rBB
I(V(6wABmt!foa4@TZC{m==Sfe#Di)8fja5XoubF#6_stLklroBpUMRZc#e9hJiH+TRC%2y?V*kMpWAm4BlzxxGiF1@;ij(JZJk{
7>Q1F;HLpPTX4=z;=JszAzb(5q%Gq(FZ!0cU_Cqy<f-z(H_(rGQ@rx-heaVkZPC8C$-=M|g}t&j&E^o^sAl+=<3z6IZhA|)eX>Sa
k{*Y}3SLl!B({5_k39o#^e8l%13fBsD$VcQ48L>6Cse+&&kd2{fXqtvFj=$o7{2ke7;sjEWt~M;vzO!SnE+?vD`rgddj{8|;+4l0
HfLo`2T@*EkgKV0Bc2sZue<c+upEBt;_wgKtVdM5@!Fui<C8$9lCnhjrq|UETaQM$bFV`@($qGj)}eVt6?unaLoh*b`^NL9re78e
f`<RdzlLVN;VwV-86O7gc_08yG95PuR*GU(M)Ohb@tZJ`abAv&2&*qobGU=To)^&!VKwaw6thNx?V?{U2$nTH{4A|tSEeKgm9eZ?
*3?^oueQL+t1pUc@r~KaY1a2MrUD}&8DJzeBqp#|+Z9B)tu9ufSst*Qyj#bpFiEDCyF{yjezUIOyf<5TXZPt|bZsy4lq5CnMK#Vz
4mG4r2r#_z`NqFL!%$$v0Xx}LOzYmLi37M*bKE{&&0$$Bs|jzEX1^1sS##~TP~W+u^vlp{k2!z)xIom(uZ|0})@FZ$(DiEz@i}kd
iEtd$>P{?3_6UAu*E~ZnOK-r*`qAR7V;OQJ5?uVdHQxhk$yIZq_qIdYZJ}X}7A~&Bo@(YcB$AiBGeEKKo+i<m0_taJDNeG(6m3m=
jYKoVTIs@JTFEPVccA%<C($i>r=tZ40(B*K`AqlaCsHLa{c-uZSoe;P%Y@gkaqnHHQ;DuU#6nwqOL|N)ZKh~++eJCBMQfW0g?^X~
aLKTbq_ev%BcBjGh;|3?Nm*}P_@Z5NQwQ&dbLd(2D_%b=GpPPxtOvu=FogNL`m@LjsMbmP6mBU4Q^DL)#w)f>qXLE{JkVeCf9&23
2x<lLrVsb~+cxFjK2h1kA7Ouvn*47Vkz;M?x3v12TQbUi*$3VD@A`(L<a6I}VkYw%3jio#cZ$Sj{eivC&}z<hRKY#7x_};Yt$9fJ
2XEZsk{3t{<<-{Ag*Izg(-9cgn&N`dW}5$Qaci#0o8ZE2jckw#`p7nvDV^HQ)IH*g_?dMJZfD{K0Yc-T`AST#@ya{VA#R7oIq_=I
1ixFhVenlyiF-_>{&U})8g`wa%NvG+R?rX?>D_{ry0!{`2uJs4fjiiOPX|9433F>F4|CzTE+4|dfz$nF8y6mmtw#L%7{B^tdMh5)
WcI4UQZp1|i=U1B;!qDU0yGxv+n^R5N8{Nk??JRT<56^3#Bxi{@x~BoanWS>Io?>=7<DKG%eebdZ)?tR*MS^dG-Z@JbkO|HxIWj-
&#J6GRnR~l4y(Ve=*RQDv^Zf?ud8rJ6=aKUXC>l5;Lm{AGek$%wkqZ$6h_usvOR8#{NpAR#AIi^IO-${J@(i?h`_uxs{tS=D*m0Q
gpv~2A*-)ARu+~7u6?&t8HQ(}df@j6pE6Xrqi*mo=*zHJpdB#E`5u2rUvaZ+n9@Neqq0o((J+%QD)}ir=?meJI7_UCfgdqb?NRuU
Mt!h%ELJuvp)%Nu(Lx8S1Thklv($C5!mk{fp3k#M+m_ecxiD)yr}$#mtul}r`gd;S<Je;(n%Ej;Y-!u;1veYl=d-wDYZ<%5PFrPp
l=|E{2q}}6R5;HISt9YRNi@+M-3)viIL5V>LHnK~7TFuGne*|5Y}u=UL2}WUHyHxui4XXqL@;~N3^CGyV^ph1qX1<LNbZPGvo4w4
vJC<I4|Xn5)8MuEhU-Nu3}4)<KOHAwrWZl$uK6d+=n{!<(5V45sM@3yyBn4<Ez$|Sj4b^N3buZ>OBN?oJtD=G8JaJ;vRQNN)x+%Q
v9`YBQ2|vV2zFnOt)l92(5wiW9&{YxLNY1Zh~`vuX>096mgbvQ#TAj*60fUv=$W}Tx7lzeMf}ha)*1$l22=pAvTuEY>flX!$eZs+
-$d!>x(zxP)`n&OnTDgW*nA=1kWkJ$fK%e6srbOVZ!I+=f6qRDtLzau<Alh3`JpZAgj{Jxj(5X5?UrkJ;y3R|x`mI8F@5-*m+uVR
&Ac6MA^8m`Z5vy@$lu+cjXkD2&cNiyMh|7uiyzxn{~`Y73-&bi&ds*)A^O@q+}2#Pb>LK|i$L$a`ZxPXqSTllAOcYiujbrke6Q2*
)lJ{i^nJ>IPWjI%|2gG9%PM8ZUF~LDI)2R*OY=pJWYX#{wym?^gMG21eRvu5l~eN{?<e!nt6*P^W{JdpONpOp%aP0d0e(Si5Av72
!SP<}=i^R3+6U`f;hf+%XOcu46AOxa{4kWB<c=vAz15iD%O8so3k;lE#3D0`rVu43+gWHz>2MSKO%Ii~cqh+v$0up@x3<Z<3&jj~
Mv}-f!l@ZhlNz|5jFkt7U5+LnnBrV|knAjbLm&}&C5Br+)41ztHnxs^VsKx<vfKd+^q_10AUagj&V%nkBp!+=)M_eSJk$pw&Qm>L
9YvIFNFmWAX{tIUM)FKM!yDEncLt_D2i03*H=r-W4+g|4U?)XGskQ@4)%65K;1lWlH0BP?3<GD}c1ZHs+8-scMQzV*U0haAyh$GI
5INt7C=^`$DCeVR%`=(AT4s8GbCWmFes|r57zowdT4L;UC$=IZ%CEB78}T5yba?E~%F)@h;B6tEh!!LviE$Ue;mCJTj@RnBxn1~a
4{!XMSoX1=rM&1&*d3%<>ZU%D$ro4Ktha`>+j;i7dR=yGo*Zu8nuxX2FrFE^2N<rYeJ_INI&-jkgGbAy+2^R=@aCsn8t^B1i@;yD
jSgrsfy<uZ%5RZBclko_wN8DX%GNrs9;o!@QNw==PcG42+IV8FdTX9Pk-b?szpU9Z!+N~;HN0^GsKoOaO+@wDfv?ag`U~e2QkX`W
JHaz;*ru$?f{mwz=TD|<SH+E(7M4Sc?!Q`EXJ`fK*<Wlb>4&{A@8P-*3{Jx>{z@2Fp&diD;f8LUPE2irNkWN$X%ehEx=_2O5J2Hq
KWW45y}X*f6Tc8E-_>TB2|uu<`%TI*3E`CQoI3n@p=d>7<#GE8Dzh%Js<>BZ*{Ekn*0IuTRDeyvRtKz*+8AA$?naJnWI5oD29kq>
Wr9rIF^;lez^2ME5LuTA`xc<1(tE#MqoB$St@4-!#_9{OgB`O`w~djZRS%;SS+TF_Kr#Lg=f|B5{HW;#2}&Z_IFD71Kn(-N0$cY2
T>xhbr<Puk44*}MS#+t1o|}R>iOe%Wp(LyyjH`{zm8+Is*P_^N7jl!60j*BlsRr{{Yu$3JG!>iE{S~G6<ltCYECn+~WG-92=Ybps
eW@qaySbS6qBA}F)Q`ls+J(VGym5_{*UX>Bvj14vWS)V3nY`d30;$8pdVm$#z!zs^4*0<k9fA4{R6b3^`&*2O$5UlIu_CxwigY-R
%n18Du45UOp>dgOTnGH4u02(i>`T`4G9}eKM!f5voku@mSO80I;?FOcV8bM~-tW*5@4i&V*C=vZG#)y=^21urTeiO=^}4p4{CD|n
PdvW*)RGmsw0$R+(QoC-@8tTNXFx9ZR_{O3?W{SU^J-qj3FnvcnUB1Kkvp5O$Dv+o$Wt`TdrJ6q5wkz=+!g6A-FE;8WEuzGi^Q4U
!fa(}dNenF3l-kQ7H18>C>(>J#aUw<6OPe&;2=sgG}Y21f|u^m;msABjc*a%WxBTI*KB#xz8CgPg`X*%PX|;ruG?}vD(-t^)(X)8
xhc2IWKv7KHnGZQ{wx;uf2B|HP4;ZPBvF1?Grn26hL_ozXXg5y(f5I|1jH75VPJA}WyIq`P!vsXPSN;}V_b(bOn%I<%RzU<yM|Sq
5lgaeMK<2g(?mPoPqs>vXm7;-ETh&VcE$Cwx-G+Rao`pmELWn}wZeuCWW!;_KEYBQR=C!UdQUTp7ZLx*t*kcG#VQnfg)Gy{kkv_V
U@!ozXX26?4_bI;J!rGpQkChn+iFdofk&HPTb@M2Q;ky1VJpUmp&bMNEb+wQGY>>{U1ysPXqTepScNqb4=TSwq^p2pm5H;|4a+Pw
nkIE?)V3DHV#D7DmeNb#?Z7c@xzc#8oa&!Fj)?X&FYI^Z4vun(1<kVa(y@nSu9)t&sp%CXN0;n=P#ecPJPgN%>z+m+9W-0S(g+Z)
`z&j3-Hc_Jq97Ufm=K}!aV(b(0ERqi3LDk0qIla7AMQPR&7%MoH_a7$129cxF{!p=#Idg$Q@V)Yl^~Jid2SL)j(LK8tDrq?2yjUa
n>p_*-fY=LT~hI2_l%ioZ@+cRcqd&A$GJ};*F%gP@d2A-u6bR7yJ!xvzoFLIGLTOaY;&f(>C|+S)TD0yR!L^;ik_3YjoNQPAEaRQ
_vr(=bl!N=DOY|cSBUTAivFEk$-a{-zt#KvPVeJqu?^PT`mH*jBT&;zK-+5NWDnK3*e7>hc*KTie%q7Q6L(%i`j6*P<)mCus_3`s
+2etze383@>6A!dt|PMz1inJI^gsbLf|?g8J+ugYaN~o{kKQHb{sSIi_CRb=OPPlXm;`e+^fP8PaBsBVSaNrzbG>O><|z-K3V@?G
<iXI82M@+lgp9QDC3K(p=E;IErhd=je<<^n-1G7Jx)-1g&MjxUQzq2Na!Z?Zam|wXirQc`A_q3zhGTpSL8*&vZ6JrJ#M)ozT9_Ma
JdqQyNtTEYn?!ujG<}6>mo$0l=;kqR7i;Mt2n2%KH^$hsi;*LTb>4?13T<B;d*g*{w~mR;Ga7e)d7Q7K45Yp>&M|(S=HIEpy~UWe
V=o%Dj(?{Y5a#w5A|Lbo9(LMT-)l~mbuc5Efos-%&u8l1YPXSu3+@@({rnrD*it_i1drd5d!&}Vev3DvoX_RX&{)T`-c?(Yhz>w8
kGb2T@cna$Pf7w6?;v&3BWA65DTHFrAl5y(<JaIf_U_?m2@9eQ!dncqBjmeKIQUgI?(#ldbolIHV0$}P1m9CN*+Ed#&Im9N8j(?K
Y8Xck<yC2UAY=*$JsM}!9YK0{L0;wf99*_K99yq2(gm;z3U17fw-DZuL%5K=|B+GfP~)$VFF<JYTvkiBz>Mv{7C$?4JuI2ihHmej
t;SeyoaDB{6(rc)a)UpM8FTq#&emwu-ei~X%s<hq89kQY(pEF2i6mD3PR)iq&Q^1%e;|TERR#C<HGP~PcgMXyAwBLGz1OIqQkMN1
B+gpjb2Ad-ld;65-N|oIEJ4(EIM!&HW(ZH!FFazfcEOi;h|hL5E#Z+K@s2^0_-7bgcMB}Gz`oNSO~YeWq!Z5*dU368pjH6}eNZbz
fLt~q5f@IeY}Wx_WTF+quGskow}=CEvLmimxbz%cpTwnn^#YpIxO3RB`W9uop(d*y0n@^=2Kq^7gpC%tF=!&VIpL=Ue~XvT7At)=
^XnY0nITH;dRfC}z&mq100ZrBi}S>O6DLbVOwPoV>s9Zi1OuDxNw3&6nt6Il<!gbL?Wv((W&Kf`Lr6oLtz3NCAGV|nrsFx|X(ocM
eB+*h9pYP2f06SA)f{ofzbhLXsO8}D0(_(A-)O^AL;LrT%$Gh{Gs!JliBFKs*Yd*?5`DO(4Nd<`)boa~=Psn=hMNoV3%t3nH`p|M
@U!8EBMug)tCny0cMl|G+(R9E&t7!t6VGwI`no;4gU#0NVC#vplRJ28cd%xjek*&~j%{bHCDV@_>#5E-cvCsLi#Vq0=+_k;Z5z?i
D80AIQqPumnQ1?Jx?HxWh)LCY#8QUV>RNL0a%w%kaG!a_fP^)3TvHD%?x!=%Gy6EB9YbWqt@#K!?!~Es2i04CZpf*h+UWVD;~an8
AF3{?d0>e=q(X)pZn3OkFfzSM0UGuNn})4h29D4VN7xp8?DZ`|FNRb>B)xban%^t2W1+r4zNWNXXXI+O!Qs!2MqO3Moi>M{9<cB1
2N=}-WPXN0y}r=RkD>J)9;O&&M@wkP-s*-ZiB~*a_hDM*#OlEVTs7l-A%2d!(d@`SXm;f5GIRRgamwOR%dL%Z+g-U`&wU<;V8WlC
-=_c(gV-o=t?WM+@4b$XHS!C;UoSuIkTdjFA{2>YA#rQHly{<VF0DJ0{|K%REyuUcI&!9`XFb3#U^>k%&sH5YU3s#^sJE0!7OuA=
m9nPir+j9B4}cyo>6#MVz=^-5P1c+DlwrksO9=x<rIvb2bFX?aNkPLcWy1VCmXtW6+}86}U(~Nh6$i3s4Y$^kcQ1RN2G@0~GY|o8
heiD@<?8=dmXzt$*l#Jra%xX&%CNON+dp^etiJ$$Q)!M8sULWaxI{yxE26Ngkx9gG4Q>FuM)z&ID1ElLH?Xei)`775XKY%=*k^v-
H6Is#FZ95{1-gArLt4ajiCxQ`Ykk6{Qhi&a^!;l-E|@!KqKD0)6H6{-Yk*y-W`vVwg=ClcPQyd-<d}9nmaFJ61mmO-`Pq1krs1J^
BbERjXC68zSW8IU5yd<XTU~@L024r@rp=$h)WIJ}U2~ikXjOp=(Woxrwwan+`kaTyp3r}Bd(MM1DUKN6r%Uhi)g7Z6^S`#67p#kC
tI}~Hy?eq(Z$R*aq-){(sB6Ucv8@@9elXjp0yg_kc)u3WWt;duX|Ll^3Kw3WhjK6Z!1y5_=)S=Ry2b}0?#iMK0G{3@9TOffJd1g8
L%YyNIG;tgs6B#30=(Bn<Id}ZjX%92IWiVZ^DA9&LXmg8ROtJN$~#BKnA>DdiT+z_8MG&Sz|Pd8KJuWo4jpgj3>vO+_4+%WiT)02
ZG%#7xjeX^hBWAs>hX~priCCQI-MR7zZuP&G5Am%T2tuk553)ZQEGKT^ZVEa1-XrVhnrr@*z{Xjr@YsG*1vcAU+A6l`O7mp(Kdfb
pS_8H$201)|MH9mt^Uv%4Z;2$&uFyz%QG5X_(Nwj=KTHk4clTV@d}pcyF}qE^(Q;?ER7cqY4Jk_w#jq6#E+%*VkO4Nh-;gJ8h87y
GVq^R%5Y&Ms%>NW1tWezuHm+e_Aw0cbrN}^*>)_PX)bG63ME*KMnXtCBQaIQ4`TA96>1}IExNIp<%vs=C(o2;Qbtvt&Cd&oW4gWf
InOJ=^2a$ns2PLjl1QovaZ;`M^}3>mQ7lI^)BJYY`(QhZhEs`ow)Fm+Ixr{~DHT;S=~VqKWmv6H9s22xSxXF?nf;<JRvk5?IZiae
c{G}!c)LXS;1yhI*J{S>xYn0FRJJ)b$Xp9elkjB6dHGAT#h$rjyQ1S^xYb1uRKbCYCxrYh=%m1qw??e3*q*>VP{0k<uI+6^UObNj
wtb8vS_A=76G=(*Z|#;_b6ux+*EH{Go<Y+jr3PLYyF~3i1gXve-%ZApJ{c3;1iDUR+8Q>1jL$^au2iDj#G|fA-O~OdGYMgeu-AK4
os5L3+BTA<j2(U+W3Ff$r#@H2U?rX_7~=C>#mq?NuEm{B5(|bHT1&rEwjC|Uy<R9CQxC3a$lMdQ60Xx8sncy}+^wfcEhm`x$w7yk
79l&UCsHUX`<Z9vlH2L$5~R4`<2DT@$Bt-P%ts5VTV#tD7E{A2YGW%aNFFYEz8_XS&`BbiIK3Mj*%QJ6)=R=z!28g6tjiwdsDd$!
n_MiQqQbKSD<HakcC*paZG)@jIF@uy;jcuuC@iTWj3zkVya_u!J>cCBj(9XlB}RnMyxuLrb{xhf_9yzZ>QJ*;?Pv~0NC{$50exxg
^`lSC3X5N<^)B1erGH)Zt+v0=>l*p+us-h9`aqI1>5368!mwUgEL&lL0k4&ia>LfNb96`sVHg$*@PviTMKN-$o+T-4D{Ql(mh*0B
P0pbvl%Q*t7XAA7rMeNe_<x8znKq?)%Zdm&?bEXfH{{`K`heX{6v$$8o8TJ>vqxHg!#Asah1QeR6#@79&7a#6DWf6Sbc>*;c%vO#
GVH94G%w4XLn;Wl*^rl&!j_GfC3FtU_>G%9ko#B>X49KCR`UbL8b2DVU~FDvjPH-}P`5E|g84MtM^bLPMiLqOe$5p=wFE}4=NQ5f
p$)GY6%Slo&kX@lB$nGV+*Q#NnsTLWi7}e8VNy+3$j8`ILPz#ShD+s$WtI>hqD6IT@z6%(BEAt@{+3UTyjjh8WfgXb)h#iC+KPnG
JY4qE=4MsSxU_1D(0a0E=R>(}AK&iEwyPs7%ubFMSNh)_0T$nR>?eqTtyzK$lzq0Pqi3#r7f;^KeGbn6*9-9wju$@dWe>MRmZiLb
rj;XRS@A5s5P{X`e~{OKeKE3|<I{z$+v6G6@wtXf7^2{$uK0C7<OakhNN-uMAZLDRy#h~^{8BC<o>i`hx0St+ZY9nP&mzY#9H`Pu
&6GNjfAzN9uLkI4*m{X|2j=wf0yP~Qo4q>eiK3P>@UcI}p0<f7a^#b@^tj$q1`YsD&E+S}=8{QwcV3hif1yx`fZ{qFBZRpPpTv_H
@tlg_y!4E>#U9K99SB+qMq%9@5Lk!w8*%=$8-JV35n<Y`MxBF(f+#fl9k(3OD)2=a=+<EWh9tfHZr9%(pDe^F*y|P-gyOK~yP*{a
%#>)uc8-@>)iPTrua9_WH5+@&swU2N)n&5aL>sn{<TyfDMK$oJXH0&YIUCIyMN8GXpTo_XKKaJ$>!?od3GGPD2vbG&&~<Ay@2JO^
7u1$}j+H_=l{HUae+SKg$o1F!Ym}m)Q|P#|gJuqDMvNCccz~8DQ(ek^h9ZMgkG(o>jKC2=IX_)3!Wu4p(If5`9TZ|g;iKmeirl<L
kT;tFba3#Sb(a0DfglgpJ^1b|>!sWhB@!)q^~^hzQx?xtK2@~mc$MZCp7~xnSL!Go=eW%ddx$j;Kbj@4`V7r8VvY3q<xLO(9{{v(
$8oOKDCi@K%EM{}>m<^aywj0AyXD<|jWTXIR%$IN9gGua3y>N>@WWRhw~V~m{G6rPe{$TH0C19Vnsr7e``Mm5+LN)*gWCDUT=Oql
6Af+HanF&Tp8|T$%;c{?$7QDtm#6qL_XtfWGvxFA%^iLpOydZ`$981PDoKus5n#!<Z_Kb7a7IS(8hz8dSIECI5HPCv$rHQjg~#!y
=C~}NWh4#w*=`fGX}0O7cXwm^s<5#EzB1wo+EA;}7sw>{bYZC};*E%oWK2l_>g`^cgUC+WLkLr4{h`o%yK82VoyUV^>1}}3U4(}^
QCeH_9zi9D<)r5QNo+N+OI0bsYPcjOB1jVy+@a(Wj#>iIQS<~9fUVHug-9VT){Php+D$&ujv`j^2<3K@QAO%g|1;#$`dzsNa+|m6
e8E9Q+Tyo6bW`G8YeD&+!+(LPzwYOd21h~Xg~M|aZ6tmg`ZyRtg{`bFEc8uRx>bqW%%(@$3&EGc+YZdfhT21%L7-E^QHWy0&VUNq
1Cfd@Oh^M_-1NC`j0t)9?CzRv$SQshbYn$bG_;#;qs;>3?x5XOj!1ag>k<B&aaTTT`g@ya$V^h-6987xm4+uf^;|reydZ{btM_Vx
Ox219t2c;n(|m)RL~91R3Cph|@j`V*{zK~{=I6{!6{0qV?5;3{MZ`5E6Pm5oh+XL8el}KU_-PI`&tV%kV<>AnT)5I$Rc#oVPI`G1
@t5tW$Dw22)97cLJL<D`pZaVf*JoZQYwqw?ozLS2&|4PrZJ&$G_LgVdu?zC_l56tm6s%kh>$~E65|iU4hIzUy{2fOc+1NK6d)TuC
k418fwF2@iaz4NYoijEMS{<`BFkbIbMAi}m3s8{xwLc`ruCvFkWA`m`ji2;GqQ{bgEo^b?HTxYt%Z&E}RpiF|uEJajQh>8c*`@tt
7GIr<Gd5<MUK+cWv5V$H;)V<UFED4sUVYe*H*F1%2N60ppjg7nr8b|!ZL%_2c=kDhKpVGv>`h*Kvk}RW0(+?v<v_0j#~mOplFr<P
4Mn}!7*%NfP0ckELFnd~Yqzwk)hrkiICJ2k+1FFXa9Qvov_ME!cz~iL!YUEQ&Z%_=<v3*Nn(c-6^Oo+H(K1Hu8krNhmKf0;&6+uj
<I=+|C8iibgMRCNNo!8M>aDEVLV4&xn*5B)XdQIuR@a;}VsewU*G4sNVV(6fYom7}ZNih03{9NZI6b%2H9E5f2vWG^8PX}>4XG?x
*Uevo-i^v|Mr)ZgV<`K_S$kNw(xV6>LXuLMh!~<}cUVdFaUqhGScC6pKO;@{l&;>l{`EVc#nel;*t=BK$@mSI4@tCQWd_=-OAqzg
U(2}f)m*=!?R6#c<QY1}O_V5J;j&v7X_mkrP>-1RpXveEWS4m<u=DKLi;VqMYQ@<)&s>J~x3!Qs?q3p5`Ht$ppDhB>ttGdvKrzkV
X`StBRxiojI>T)@7x12=9PxZ2t=dE~C}lU-ED_rd8nZlf;Tb+jeoaG}D_va@uf$%YdX3Wvb%$HxG-k`Aa<0E=bc!;lgj=b}Vkz|*
Yimh+Q!oXaJ!HLh{pB^(JlpGiHzP_T?_}b<_Oi^;sk#^bZLBKa&LD8Y$Nf6Z0uVKF@p)^}Y1>`9L<mA@_k&{}t+l78a%oQaRIZI&
`DOX%_=lYGTaL)uS3R=!oe^30vb=jSB5nQTJ>|5^Kqkj2^~pDG#u2BnmWekDCc3{sFdGluEuf-X{HVL0snLlXsQ`O@sdbL#yTmH*
u^<}FXJ8H`F%YDddz5m~GZ=|9$=KP>vc39~h-jVe{7gf&_H@Pn^#&5chM)mMiYy%4&|$5m#~ymF^;vTJDW?5h-xYd%sjdThEIsM`
#9DSM$(GmoXC&@5Dio)Vo*VHDGgFM#<{1VXT5wp@P1-~)mMJ5HG}OV<fmQ1$h}beM8ha3F7Hn%-im{ivag0%p%wQQmO9?fqfU`^w
wsG{}0a@PRMWuRk*EKtqrz30zqM^G5I~^csHqEh9MubX>Zh^Ox*nF->WraMp=CzI~0veqP!GCA&Z^nNvVpS$GZsIQ0g=7WGkRToi
{C9Ed*_?PR-B6Y|pPR}g@rgy0j4NFMl~Zh%q~0#si?Dw;Of~_*4CH^RVO!}tqi5e2BAM9spJ@+{n07`)Q*ZCRe8x$KrtwTAD!0y6
93DENVS)q^>wOUCO?)&954&V-Eji8$5oZ2uGZ_){H9&%J;`K(5VxsNWeqsICw?t%SQy;sYYr=s^H!2mDNn^kF8rzu$CTy=Q)?V9M
I^6g(o;UDkMcs17X@s*~M)Q!IB=z!+0|vYKDTXQDH=XUSkyPiMKGAu25OS<JC?aU3W<0H=x-OgJe44H?0nbz;q;?7ZllV<ZTtL5`
syykP_0luCxv59nofdvr?HuR(Zcxdr9zeUaUupaxhb5jJ5NYQca3PNS^_DVjw`S{Q#qNu}48d)gaHEyCnI0QdG2{ugVoi8`x)10L
_q|!WLcn*fJqdI48uySo$uIi8YkSN+#$`f@Y1XDyoZ@&R;F3gDrdzc*en+FLlbsqOUFpdJ1kOL2emC?x$X<<mvFCG)m6Z5**tPL3
PhTX8mE!0sV^*DDy<C3_zRUf*&2lScZYg7Y!=^wxH&&w|?ceqj9j=K(ieBbGV!MKdeYPi8{_KF;S1+^n*O)0D$=EX-%~rMOwWV7P
m^1KRy5e-Xdwj08zdoT7i6qz0X*o)HLI0V_y0=GwYEh(k_GYX-VC*@&&LX{uV`ZA%D(6-mzl*4zo!*J8*``r#93S1W7LY;v5mOWf
9Sy;uEbpz9*?T@rm!%goIA-9McNun+4Fwf%G+U7|XO~!c*6)AYZ8nA;>@gZ|_b&n}d7v(}zU^$QDmQPrETm>z6$bzpTRfn-<u+{N
m5`$`P|wGB1zawqWku{HeQl$YnmD!$Y5~o{G3t`UlmSR9Omx>7DVou^rIj-1pQF$`U^aR4eMI53cVufbsHZ5$b=4$JF{yF)(X5E?
yxe`u=uCWDUX9!-KHs;Ll0WBr?1x<0lGCbJE!p?b8IbcC^5B}o_*bo%_{Mmia(inI_u>wq+x%vM+h3!h=Wnl4TKx-9cJlQxx0L05
fn0b=_mhTx#_0)an=CS6@+>h6OhYC^)Dq8D(A`_KOTH{>Y0_u=EWc>IbXcQ+p)V6gM!BWTs7t52jbXeo+Fd=SHd&6-I32mU*K%o@
@gC#ytK7c}`qi2S{o-DSn)JC<$1T@_9WiwBbU!z}qtQg*!NiqFmECRUT0TuP!;y8y+u=Uoz?<e0{Qih<PV_z<w!K8giIq?20x#q^
V)!2Qf`#LTG2n8%cqWd|@XYdJ>3xp&y_4<pD~Xa{Fxuu6SV&L4_Nm!G-sRzxZ<1y|S~E6FMxmH<$0)hgFs*{s$I7#X*-sDN^6c{y
4zO)vSqV$4z4-z`x}Dp1v6c+7c|<O#?{dH}>BKLYcj~>p(_CSSDbBZz_$tvmvF3X2#ltBt)**#F$EXt;Cfsc{08^%J)=SUyjl+UT
Lvr9+q;tHY67?Kv+W-lwHf!xpFL76u(0unkjQGIa{#<m6s_tSV18$0bUrS9kxgA-mm|LC&+0Q)3kRo!1D3RN5Joecmyxr8MW52F3
_Yf{+Sd=X_Z70k;#F}M4aZwfyD+Fpk%`tP=+9vsun)riBzuG+6Xn(FH!yE&?O9Bs9WzQ~s;}@#!>7o4_ehbVeLuS`BYvzeAjwlb6
Z@MB?wlPYg|0eA7#?M^*O&iZ8sb6azv(RZOgV$O7^W?l-K6YKozSb~yiL3zK+3u?^PRj2@QlCp?b+^j7r9P*wh?uu-jxEVSikCQ$
$m6ECjYGNu7zN0D^u~JH6t=b0kT~c(thST7TRk^x?Y`s6uzEJPehg~Vq@L@M3Wn{oy=n`=bjeG6=%dq<eCL*uZ}(J-k^s#O@2QnW
voP(yW+^IrY`5E&a*TPz?dw0a!(K}V{iQuYC0^K(Am!D5h-vY;zon(uX~Tn0>xZ<dPOYDmoqU*^ZGR%Jz2*v+#U*cgC(;||o8IKd
)FB_xS2(wO%itm%BpHapX(82&Ho~4u2L~UyxkjDGIa;FxsE&?-Kio%AHJ+`Z&LMs^G9ya8pqG&HD^POhnqY|j+xT3qt$6+Q@f#Ih
>~BQpewFg0e8`qsXFub6%D2&lQQG*g-3CV6S0mT%(^vtV>tpWPuC{RhZ)@+iY(0-8hrLT*>w-8C2fd0z7bHm95q8KCmVD)ycXwq0
T*$&&yIZ4Cj9UBq7eJ5%fkGWKsU?SfGTn(na@O0l60>SQFHLLS17B+*p1`=|ksITI6;PS%teKzY+MP0CpnpB)zI&bDM_NrjCEWa;
TO(Jrp|$eJJB{pvV(ouqMW8dTx6N}W`9$7iwC==Dve}lDe)!h4WumBLd#`<>k%cqcJ0;T7VP@JflPiBbN1`Y6OH2Ce8phqQEi)Ub
)b$DTU(ZnHvqPevhi!Giw9>bc1Df&b_|(w0DLZ3ZS|-1F$Z}F=#HY9K5y;ycb}UbO_dFvcqPaYB;(U*hCwJ%WZ42XF11M^Tb-Ucb
(bb)|`oH|!fBHxM$AA9+{_%g^|Mh?W@Bha?{&T27L8kuOfB(PR|EYxb`MhqI?{<ghObJY^asalgIWMQy?fv0o6T?{`8nPUj?u4Tu
p7m*`Jjp-)(?9;7|M$QCw}1TS|Luc$`dK9PIBzapoV=vvq8(R5`Bz0Uh&jW7Mi)`G>A(|52xi;vr<}^ofec6lQZ(B6z$d$JA{Vkl
L;ysemzH{zs@y(>{<~SMt;$Ka+C|mGUhdZonb5(>G~7aJsGOsf{12+lQsXRNa~05Wokj<lp$PL+IgZ~9OT5-*cW+Q<;K3zr)H1#q
0(9|I)<@T<;oR1GW`@_PiDxf`)Ua(jY^p83LGEExFptU4gGO+h0l2I5QoVU&x6uxFrN`yN$Vc(L{`rm5j4D5!ea*cLqc$?Uu^joU
yhX9cdGz09G9mcRzM-$;H1|%&3+Ee+*y>RSZUF+>T9xX%KVw|Sk6zdEF;HkW?l5J^^rOfZahzt-2j*r%oq7jGZH}=gyq~6vH01|y
?8v6?3EFHrp~7WWX;HM2a-}Ed%Jlfr0P~<^*WY#M^lT%=Tnxu|vy9(b|BVKkS)hFnMNPf$oYK^-8s{lDglPc|-C5rGH0SHTQf9n~
D13en^p<_n1Kc8fC1Z$k{=M=5r8F|_ApqzSYcwgL8Ol!beWIK-JCq^54q5oewgGtra#keT-(KlnHzhPHhy{(`ck9HLiKq&_@VGtc
b?BqT9D1)#+olfOtO-Htyj92+-4NTLCmYZ_W3#*)gg1`aEU$C7^=UBQi#ax39F=fmco#pz@B8-dx!_PgS-pus?;92V%x#<F_IB;A
zVUnY+l2FQpF%4w&c2UXoSiQ@3=i1=owBi~bJ9)cT75)#-?<z^5XJ{3gh??sgM5ri7tMfIaOrdf)J_WE(e(j26d%#2G=J?<S06ZB
ay)vvW=2UxNTP~n1(O6)j{{v+MFH^@5Lho8{z@O@3yByP0k@wGZV9K!OvmnV(8zE9vt{1%bzJ?Qw29^r{%7H<Xi4+5`k<I+<WlW-
uhY`pKkqd`s(``p^e6Jn$`14+Wh->b6s*-!$T4$;j+&91)AGoH(`;$fxzZ<&ft;QSLF%cbagW4vg=*;**|Pyu=1(#fiY&1+QNK|%
ygds4KxGa8+a~H<gk|t36^6RUWf7F^sYO;m++ENL%pl4XGJ3Y``AMcgOipZ`6c71}tYhTwx#ax&?@j()z(-vV2$=^s!up#GS$bdc
bnRpy@iJ!QL&SB;xua$bP#vV5$YPx!;;Bo3PZ~}et9egyx`qw)<xekmIkphC>(sXN9RHqGO1J)r&MjO2^Yh)62@%IRKd59u7H;XJ
75X=x>BQfnp#|gwq1;}fQ7I|!*?9Q)>ukQnws9>ePsTvn+BhExS&BtbdSi~^q2V$QR}?N6DUzB3<`w6-9Dt~mSub=MBR_r+Q-)kR
gR;_si$-zVYG@VNE0_Re8ek||#iHs*(j#z**TlaL!`x8i493cyys+U6k-;7fT!HvQp0M8GKm~I0D9LR-WP@`@uL&yuqDWtyO$uL3
H_rxP6GxzEoUT<pQOBH)I>Uz05UR4l<)a%6`&k|{!aA2TWXwVarZ#B=HBOUfkRxmz@U3og(#l)H0N5&2`;(q6PJLR0?bdm^_0lNk
ZqnLf9Eb<lQR>z`=M`L-r~Kx{#&|_SKQF-N>3h|rtcx=KuWh$1#+$@WEd<rYWmVEJ7dL&u5(s>df2OJj{y7nGO7mAN8f;8{P?5dC
8BNvU@pg)166%OZ@6-CaD<xPuEdwzj(^_WSS0gL@?sGx(tDH(tcL9i_BE3mOThc^Rlyt%lQJevQ6v)9Z|8E3oay_PvRf&INPa->F
XM`8g&}3=1Qd7&x73F2xJG!J7iRFsyCj8cO#zn#cDKVdD7i|oQ_*zN07e$)HjzhI>+kCI&7ehGp|JIE7_tBKnS@R~4d>PKp21#F(
!asTzw4P=m$KY|ed=@Xq9-t1(-ZbIQoo7$>(?`r9eL__SW+*h2`+^P<!8NFbI<pR_+HvnmTjB0$li1t$MukL}ir9hi6!sii55NZM
D1B+Ys994g`?xZV(=di5{8<Zk%JL|%u)_ER&|r1iq4$Y$BuZv#=O@$#fKD3AP3i8Nv{i1KZk;$*iJYZ7_wW=t@Nqo%XRbO_K8TS;
Qtg;ad=`%iuz>V?9w}1sEYBOLOE6XsdG7aXqR9E(-hCi?LE*7xkOn1|t+1mJcm*W8j`!O|uj-F{z+SG{!;*bF#?n%Ue#0Cf$B+w~
Hi86yv~C7FXr$;jK;ysn7&PZ7`)r@z^l0=^fiV48Z>dAG_w|sD-wx!>|0Yq~$oYFW^Lt{FQ7*6Bh=_v2b{nNPZ0ZMuto6RzqBwf{
`5KSBYv#R|(+fOm5lJ88ob88b!M6uE1T+P|4S<gUx({#=EgR@j#iU2OEH-TU{5gW;Xman-6dRtWL#y-yczb~%qIUqF+_s+<6nMF-
HKE3{m_DqQz#}KdhU_F=!yuAPulj+~tnFq0L9Xb~RmaiEbD7x@diIhHd~2w)4$}BlDxhTg4!7^Y>8?JSml|LjfMRM{DrcQzkP#HV
nQ)%GS`5guk$VR9Ks_D)y{hFU;~!PaJ7MK*$EWB(q544wQsN6f__;QnQTG)Y?BH(KFr9oWJZZ}Q$nNvsR|his{I^N-09n~|w3%d9
XiRaXQQZ_)f8GmJef{64^3I<%mpX~2d%usYvqK4Y-e=So1&z`i%Yo*n|N9w<BC_kiMx|-^NPzGt=fKCVse{R2ufO1pO4c#1cTx3Y
5P10ay^%;h^yYGE;`N3kb4{$EYhg%l)*&iaWlrh)7xN@y18kuvxrNS)X9IW*_L*xPGE)?;pwb8BH2uDX<^qYmicE(&<mVt|x$|cR
l~YQbyKV1YY~`KPPBua#I9HZ5LL$k!hRgEN^N+9MvTdZ0;L(DXNBg6nHNNG_XQf#Bj)FhWcFdyPhATuRjh{ITd+6W{w|Z{m+yo*J
k2cQ^z<nw}gA9|80Kg686r!}bCmHP<Gz<@5PxKSLV*3;kCm{LB_wIT^2YR@0)Rn;A-@T?@5cpn4;WSa6rbkcCF4ICOY5lq4E%yrC
XF@w=*d4irb(C4G8#Gfy3)38zZ8@LFH-lX;G#~Y?;qAEZlzt(wR0li>2$doKPlVkr7Y7xazI9K14}22Dx4&u%vQl)_3=Jzk4GR(i
Dvum+CAC1By{6j2*&+6qXn}Ayol5VEe;f*QjbcC0iAOj^YzeaqRJ1Xk%iZtJ>R(d~z5e%l_5Sgf=QdC<6aL0z+RQH3#J}=-*Tgc2
_B3+@Q0!iyUD^5fVfs{Z^5)?fM4{103j36BV-JmlOw1pT!Rc)IR;o@^5Znst3#>RT*6xLE80*4+zXWv6ze)QjTpyaxmT-;Qv`sbN
^s$RCRI=MOK+m!hK>Iy*>ZZsPGTHmBB|M%JEkz6zQ<7&=|J?4$d@{f9T;@KcL@7%mk}Q3eOm@xefzru?>-H56e(XqfqPb|Ebo$JJ
(Q4!mk&FSf7Vo`-x;%X(gxzy{4yOEezC+&AfC-W@BCLm`5Hxanfa;#c+Xt}1XARQ$l*YYnOJd^Y#CYuK<fD)ehil&(oqVV>u=}p%
##<4$<l7DB1lGrnDw&~0UjRhndsBjYe93M`OiUe>pq>X<DYVcQI}Of$b#IWINShWmw#y;7AibRacexb6t^*IcqMDOJ0Nj3Ws(l=y
lF4&l4k{XC9!NDmRQDsn@t-?Q^>6GTn0o|}1HBi~UW$=(R0Tn}6A~4=Kj8)hofyFY)4Y^KR))j*hZI-&sugHCVB0&ooiDS0U_X3_
bwyXnNSOk0x@yco@7vwAH`lEfbx`^X+Cowni`GKwN!K+|K8H$l3q;*xS_w+?EewVxxF52V{9Yd54y)#jv~YPh+4?1g4$}u{5}Bv{
l)mB5zD^@v@)o6t&<%jP5)JkE<vo4Z<_4-)_a>5I3bgte|K6_$8uPQR^-9{;W`X)#HFHpdsO?u7YvcF^uXOcyT94n;=Tr{RrEb>j
rIjMey9XJecirCxg_L_{6Cq>hahY;&iUdJBd!5JGuKV21BKHK1^#Jt+3^-O7Y*tW@_OJqA006B=qY^=1*jTT9lZI(W%mAN)G;Ikk
4UOWBlPR8}j3DR-OA!T$Vh2{(mvH#y9Gn(mhyba_scs-Z1;{8G2gr(0Tx2yk*e!b%-M6^X?N7KB5V=$O<w5R7Z;`jiX_J}&jpqXp
iY))vp2Ty@s+2pO=NqGix6<me|It)8&*|~>dvF`4B_Is;Fbr!Tzs*)&P}jE@QGHsiBjw&VUp3(qa9G367m-}CEg%Vge!o#%^#NfX
-w%4LY5@aqV)%hB#A|@;!*``p`Iw=d<?hB)Hy?~o1X~^$P^z1hoOO=xp$&FN@UEqQP3)YLb!6EdY3i`@DG}vGRUv#(5NU&~W}JFQ
C#`YDZ}5K4_x=jgY2U%qsSLaLEf;E^GQ%+!S}>fLqBKyv;`2VHeWsnN4zA;)^wA`nNI%jjqeiX<eR$;2!XzEg@1Od<{OoIo=asb`
^zV)D{s99<{rv-E==f^+x0Ql8ODH+$?bYS30vN&7IcQ<l;_<h@Dvm_<9oZL8>=4ynv26KHb5{I8I;<9Bv0p2MnJ5jyjLkf6{gv+K
a3p@NQ9aiwV87|XL6+CPDBZpY@>)29!Q5e<D*_6w7)aPaDejmBfNe3bP@u#{%#&%Mhyee-Z>C_Tf7{YYMFDpf@C^ZWKVX;fz18=5
2cta(N@)*w*WNmz75AY8K0tB<1lvdR1~aF}E#pr=f&zE~Mg<xo6u;Q5sJOqNBq%~QcixF~$s<VIj_(ALFak=g!^uR&Cs0b255#rM
ZS<L$8`A&H!GW)5kOqMsLg`X=Xc=Ct0GuUq_JX?e6th#y{t7}HH^z!%tny2q0Pqypuqj_@WT=RBdEpoV5l9#So{--M0$++!Alp)u
lH)2J82sa(t}XUli}MHNO-R4Bjl|`%Hc1YAwcE@mwA8+ph)Yx>jhGsRxKZqekzTOrT4+7QzfFL0SxTbbePCjk&|`+k?+)zRGd;HM
n^!0=9lPHH#A?zfuqBuB&K8Lq<+cj_?htdSiD{B@nvq(OsUI-+{*13rTL1f#8m0cCe@$aje^Xs^3iM%qpY|y~A%)on0Q1MX+O`iJ
O@b`eP#aQs;Di4pV1Cj+hV>9NnC&*FXB~=SOBLBL$lugIw&^vZ{}Y*82Qo#t2z4Mq`<LE6KnDH?if>lBjo(GUatck7?Ph+TdJk+n
D0B5uzf`{TFZ?-4wH*L$%8P=~==EC5LzeChe`<GIp3)vmG(;a8rBs)#@64k<bq7v<>o!%8otkB-0hT&2lsrMm0Y-4^#6%pSfX6-Q
7$qBsrA&zsNZ*G>6H<p5QQw<7t0BE*m4;8`L{1$<3xZNoi&bg>Vlw&Myt&tmAR?z~yF;p1$o1N_G`F1R*+BCLJ6*on4(scJHgE&1
9|g+2-S;U{+K4iri(&d_E`*q-vV;5l`2gQXn7)F19WwSU|9jNt&K=%+Mk07jE<;Xgd;5jT`rkvh@w?nvEa)^d<Tf``s?>Wke78HC
g$!~`u-k~ysGJhL*B#yS;iFpBV=oR*R~l_Smq%q5^vq}R=47ITN5y8rm*aUMkBGf48U6G=x*XMi^Xg4Rs%9XNrG>y>UR}*CZ%*ZE
SHOvU;8552f@W5Cf9akrjP{H_$6e10Bu;ys-+jc=EtK<ok{gG)#vzCPlIw=7zM8XoZ~@X2#g2$bJ5bHO>l9)zZdGB`faw2;zjic5
zL%Xhv5_~OHx$Eyd`0sF`dh_*pL{js764&9bwDB~b9^u3mYGkhGt*<l-7_Y3bJx8S^cOw1)CTghh7`<OGcxp<U4dSpYv|ETvTf!a
n6F3BUZF8;1J1mv8oA~$Fu-`3C!<mg`co~&9T8xb$z>%JR-cFekI|3Gcl=#!w)yXp_?O(larB~4tW48W26#^brHrnX59m?a@6UW9
?Qyf?B+7x1JKgZC*;q=UGB=<#_U~ZY=d;K<61DLC#&T|V8L?+TO<=n~Ht@AG8lXf=J&U-n3q%?Wl=Iw6*kwcZAn|{!@fuKGf`0+r
Rt+#P#rUA@yPp3D<bHHDS-oPf7ABPgdn>MgJ$V`fl@235+%p#L&neaa`>BApZ<jp!oe$)N;cppm`J3Gzg_8WErm22(5>sHmtseau
B{|xM7B``mOi5=i|4+(WJ$v`E&dk4}3NDo0&OIt1kXjaNUk*By)u=CpuUjESP1_F&YE#H=ysiFtj<k!F+Qhsr&kbNf|8-6MBHcEn
yZ+A-WPTQR1ks;P5pht6%419af+Ou^9moIuz62liqm2v4L{>ffbLA!)#C^zlf5BO6`p5A1STX<Iwyz}Be!oNwsrit_2+XeY?uzA~
tk3ez{rTiv4-sA-EP1jH++U^C_3vki8$S!uP{jnz@f6#CKc9LbMw<T^H~L>>+x`j9Rxi<>FO-u$rCof@T=(}sTkCP1KV)Uzvd7ZZ
;B-Bne9DQsUF&t}@9!JaFQV-r2j-LSRGUm`3r{+BO^jHsE%onlYxpN^)^k(fWJ*eeLcR8>`#pPSN90!L{>gqKzr=UjlAGfn+#h+|
dq{@}SW)ZT;lHm7<?k`0|C&XA$(PAHm|ao$^#qK2?cdiX|Igket>4_A@@+0CXdyb;gT5lKsD58r(mxxwe(kpknw_}22hN1{xDyOM
CtZ`a`cLH|#UGa6`5k;ZpH1xeR-61!|Bc_)vABl8{JwLl`k#f}={Ep%<w9O0)*ySdiJjB7aKUPiNQ7W-Mood}n9T2UHsU938oDiH
^sf00AI`N-R(qAd{>S6ac=6x;*K6iZybx7!gH{eUp;wYV^{UVnCd#sbVlL`)-x_h@8OzQ{57>dD2FKm}4B3<A(_^;q2u=Wqf1mzY
^G}bN#=NHQD^xjkI|2A7aUFgZM2Cy|NiKJcyw%}5x^t%pf^!f=RER}5=x0vrWcKa-O;h#Vwx7d3*_tV{L5(M^YlP@DmsS1u&h#Td
VJhi!Zk{ua2-UVQA*8pkKuLSf+qzJ3NBy`Lc|ic~a%x{W+O7ct^&w3&HH5JEe$IOOszBL*(mH&*3hm6bnT~Dnm+BKycGD-24d&Y*
0)2Yirjw2-K-MwA(nB*}Annsasy9{hoj<Gj2KDv+63V<qqaP1QDz~l7bg2>miayPtO}8U`V%qJk4<4Ya8yC#<c=mR7QgpgY4!>ue
;PyVT;GXk_42m0e0>|LG&#}Xo5Bov0yENyr`+EC->&M`D@Tfa)$l?eiQ-dphDRZZL9@MY-DRb<_IiC{a9fc$#4vG19aFmuFu^(9=
_)X!}bN6F9_~Q3iju16X;L+j-*{85m@SeR)M%Hhb_XQB^@a*kd|L={-@;bp?FQpY5YGfm9(U2y7)zQjK|FV1m3hZW1caNHdPyE%C
Fwb>;nBN1}kM!Dy5tnTM7Z(EwvfP_m17shQS4ZQsvb^8&3QW7}aFsX6(`1wJwUihC!T^W1R3Ce{<YJ?SuOjxlUBDtihRvuO$naT5
zBVvqd^FEZIgsA?&5_HG_vXF?YM|MCUwOHE_Zx{gQ1U{5n+j~MIXgJRs`u}iRv#Y(j>X}t$NqW!^SXbc?w_bN0JqlI189HOsNv2s
*0bFN1~=3N!wHKZ5x-lQIsZE9<B`2@deBTELQ+zyJwpwy@x22(W2f*n<cZvd6@Pr^mf?P`{d#(`Vn>w&%DL=wmC98d*9NcP8>tU_
<lRA5Q@D{chFm9z7R)SSu}V!kKv!Sd?hnd^T@BH*Zq+l+M}C>xCO!80ck?g#kV*)U_0XKuLU~9UiFKMwhR6%wo8|>(LDcFBc!(*&
@=8JY<WS|Xt9Rob(a+XCxo?czq5QBj7XqdA+%_%80I&67+9*n^v}mKc2#MXpW7Z409;JVb=DqXPW|V3h6-xVoDk{Fmv=ZSJ+kMb%
3(fqAoBD2%)gGmzm^Ay=^E<sSo$5qA<}FqbI!mwf&2PO+k8FWr)ZZ^PExyesfA|3XmF5$N(C0D?TEvjrz1h6Jpc3kSFhWHxLqtSb
A++^;-hGET!5r$}8}s#g(>m93lqcD`i$vC>Z39*?o~2C5F-ZYlI#iZCc}iF_pP2x8%JMxk0rY{gG**pB7+N^#H9f5rnfwPR2{(}A
_V>C2sIBER-!Tt>K1XIs^P^Bt{+<4ma$QS6WfpP_OZU`o9=1b|j^vgHdx~beh^?8QKCj4%b4pb%2hU?<06`Q5kb-2{GD(&ma+<Z!
Tm&#Y-g`b!j#7G&;B}-^K0J05Vo9inRC1{9QFO!0eDZywk@ht%CmKOu$sXyI1f62r`S?X|=RH++Zs$+=0ln>V>DBEJ=Q}s8HrSw1
(OOeT;;*%nHvayVvcu-7m^xa+3)cHSM<@T@vI0~0xyZ|W5Wwf057jw!Pl(LE`nQv{o<3_`KB{O{kLt2b-tc<nd&AvQ%BxZBI7>jy
;#(Q}6+qa?c@6=(`Pw&LPyc;f^J+Wq{^?m@y7uqWz+6qh!E}r96%MruI&AD=fWC+@97U}FW<93WfZXOi&F|u)Js+R;Av%*QN89nV
UhOeu)|p_#YL<iMMPI!tMaPHLn2wPRvAmb2(1_j(rpBTG&2kWmW+Q^foST6vYH)69KU~|Ri*lym+w1SwQ_Q-%p49t4?FA9iNN__m
WY2t$>CryV4&L}y+w33fC+6+VBHVucrSUugplmC+6EFY?2<{UF7`BoJT<<y_0on~HA2+SC+~R}~mNU3G{ci2h^KY*T)V&YD?mecc
pco?SN?(`A0q}j@YX%)a++}Yn>9<Npkz=X3>!>_uL<LaH?^7GUUMjk+R;W%J*gW{#hFK%Ar_*;}U9sGvsZRjJe;|5FuVBLtiPiFM
cc)cxnhChyZ?5?R(uM?}koziiKp-TinKn_Z_?uzn$h#gjux;9me<vf#RAr6<nk(l#D#5^SSSv7YMO+_1AO2tUd(Y2q@+sSPgys}D
{6==Hyo)SoyfY9CQkiSE*8N5z{HV<J3kp(<zp{Rip8ApTj}lgW@*Y2A!c@U%V8jrWo9k0Vsc9qdq%P@ih4)et%awKo#9o?|x*50%
6n*Dkuzx!dA;_{oT~6s=SaWlCV59)giS5sQpB_8W46D{NyEk5r_~RJ{sbXx%_)vN-rMm8w8>5!=8CeEM3QyfPV>H&CDq+I*`pAmL
=Up?U|I&BH89>d8K4C!X%fG|b$>;m;3V;q@K`|p#<0scVfN&SZzJSk7#()o35g+8=zUW_6?*#l6dsgh<5^m8dJ8dU`W4xuy6Ww<D
ov9)SzfTEOz&S7D>~9v6o|vGLx_z&h5MAu>wSw8^0IJ)-&%wWCQTVICZ&%{g3b15ylC!qgXFiK<z7sg($f~L1o)=Vd*Z$dkj;#W_
gW721JmVnRKmB?xQO%%5#xa-4n-QqS(f&TIm4e!V&m0|U{WT&XlvDiZbgU0hI&w$8n4Yz`o-TW)+KKvnylpbJoNU~W&=_+&MMv`b
4z<&Bf1c|qT1WjA&+t1@9xMIoOF!{X|9<L5Wo0hklC)Nw0Ka|LRq<O6p3lNnRw<yizUKt)Jr{H2IBBi)$od#H9D9iWD<O>k!}Sz?
C&D)V9fcb+3v_ro<t);3a96B?0q@8XNM6@*l|`?RSYjR0YgSc&;8Tm0-Yip}kz1ZVgo(aK4M5eP#EOc3fHod4ZJeKotOiAm&@7%d
$QZ9pe|sgVh0pWA-TH-}_tw`^6}=YWQPn=_4Vkh{dS;t%ilGO8`FR%L?Qw60*@eBVeS@JD=>8q2*-&@)jw6S&S1>EO2r`P(+0G3(
Mk$KkUByU4$SI+k8n{G!&%DuYMZePf$OP0UxWjD$|9vR6R|Q2(fwyndX9K)YLM#bhBvgLmKJL~w1VR7`pv;GO7QO!2TfX|Z`rjAZ
-PzBGL)k_xTt~YQ)%rz_faJTR37%$UjO6d;cfytG=t>==Q_&!@*8TDq@=S%J?OqI{gy(~;{o)o5^hwuINA^*ls0^O~rU`sHAY_hp
4hXEo&la4YIhi}wRMOf_u3(d1bI-H`@0tr-`A|EzjBI$Xg*kI>K8PCqJqy&*QAa7W9^9s=sp=2f;Hj7Qkk_nDVcWJ^xCYZH2x_mr
e5ru?>1p;g)n;otR@Xx8-e-T~ut`~`&Qu@L0aGuLxA1A?aHtOx-u7FxP7t2G`@g5pmkx4l?lyh6m+v+ykOD+j0AIoZVImy**SB5F
?6bw@o`Bz5)xUtG+V56iDVEE1U)F`dWUr^()!z$SrKpeQ=-z0M>2;k->{3Mr>2r1iT_W{$5lnrhS5$tDR+2X<Q+;)}gFf&7d3Wyp
{k|0n)BZS_J}>Wvznf-}!M>0Eop=PoE<k01AMaI=lx^RmA+xg#@|iNo!#h@2QiO>?zx*MX4}|AcLr42LWP+<+KTs)hXxpqNu=oQ(
sV;hLP|rpjL>NEn{JXzciKTA2M^Ib#>i*C{qJrpWCsX+YDJc}q9PH1$Tw{oed?qTP|M?0=d+O#K{=IYya?Kw89Z>w9Gj;#&^UrAd
xZnRModaD{HuqDrC_kwRL<sLpYGk7l9F2guwpbphLu%c_$2qL1O!DgW!?85;U7aF9z%wy(I(KLtir429yrx&R;5t*s!5;b`3N1%i
!~*HG)N4%&Uom%a_jX+^cgpBOo@VJcE5tQQGxF@UK66lQ`$3ESp>^!mo?9fPj5V{7p{r)Cy+odKaDQJ9JN`bF%x1;7{$Um4_h>Y*
)b6f*UBiZjb$>sI8mObF_EVZip!|q()S>+WeXpesy}hXvf#+VSCr2z$<BoDvKD~Ww>ZQ9;BgLarP17^#caA{|HK?1qb`@Kd@iexr
r()c$+%tznL2w7aQ}y(Vh(x8C!*Zc&#$6}GYJ5HttJSF2?i<`Uu6s{KR-V0}@8c0G>Jf|6BW5fgM0_Vco7VaM^0IONM5JB+{7zz)
{_wpG*&faBNB7BfOY{Jy<NnSd-J1}@Bfdr+_Je#?5Sh+ZFm$K#sf7hZ&^CSSZzcYSd)y;CUwwKX-yOd->2~Tx{(J?*SN1ggbcinK
yTMx3{{~>xO?2fl(yYQ{U!J0+y3hQ<H`l!^hgVQsrT(jWJ|ZJmzKW>y<>)We5C}Mm%9nB^<*n|&Hx2IN&59W0=#N|7qd(3!xmNr4
-+O=geQ$Gox6SeWHph3{J3hT1W!s8I`njik;&D&v8wm|DzR$t!)4PQw@;+OlcXyGVjow{;|GaxDM~o_w<gXGi9j)~LZk>?nhfgvt
KFO#t19&t5Qzd%ek>CFO#FRs1#-Kj?lyskQZ}20E9rD=&SY`PbxGhKDGvEGV9+fe1ULSH_m#A1p*3Nz;^Bi;M_qalOOe^EPyeGq;
Dg_p<*y@PvRsJ7p&G$~zo$%j`$<e(gTbsB(SFfo2RC*$(q$9Y=d!F!`ycNC3wp8lxV{88rw1+QUB8dI+?*Itr>+(+sezA;y=_cT<
n!YSZj-3#rz(QM0YfPq<u*dqfg<Gkv7_A{B-jA6R%giSZ2Kz?sB(8?h4g{uj0~FZr2<C!An^CyYbyl;XUdA>Blj4EAS5evXIs(lQ
T$pXznFbF)x>E4DV5Qw3)Y@1qd>%T_oF}c_Lbiapaq%V{q8E3WVnB2XOvsKksBw2$!&N<+L#qtUT(lefbz}N!GsV^v3_6u<c~dG3
<Frq0q8jF9;7qAtVji~~Xt`;JOw^l6(~q##qDFB$G_{jc9Xu@+_BHSk+rV%!(w@{aXB#HAJn99PFIcAoW4X>voiZaoOw6W%iwK%o
Lw1htbK@-I1X}ipiyYN9&u^~2lUEt<A_<?jDud~|4k}e4p`!DCQ4q3XPtQz2a}n`Bmvt8siLg57mqsdz^qee+M$YTfl#=zn#5cL!
z|!*Gb})1#$1*$xsxFj8iy>6a@x9qxHdMx|PZ8B;N@#FkB?YVL<EPKkNCzO$?Wmqlo@ATm*G|Q%5`p|knoqPl-?JO5`|3R1^O^*2
8;L6h;J!V+hvNwOsc~DsQ6#QDndKcyPP8KuF5LBXbtVQ+IEhR^7aa<(4|qoHY)*O>q**z|SFFI~-F_y4Lao|@%>uoaPe9IQF^4`-
9}Ok8Rhb_Z?9ILi5&DI7kxOHxlIF5BQX~!@7yB$!lmX|hR&AILGd2aJOId(cMn&TN^U5}&F7K#9E~}d=!5Ew1$%YXH1CTgvsfkTf
o(F+8+llx({jmpU4^vSF=en-Qd$f&o(gL!;G**hf$?GTEI774kJdK=>%+%BrP4BQ%Ph3qM69&FX#G1s+I88^2kj1kh-hlnJhchp?
G|U?!S@U_=Thd7?wsfwFLW=3xM5C^)8T3h9Kq+8|kSJA8SOci&NKxuINGs%wJ_>N2Z$yMel{S^jxQI4qfzs}m=2?T0ir0)BGyk5#
I}VBZ%k}hOkB&%Xnk!!o?Wk$;p=c6fF(EX2$?8;P!$0xjODU7Y-=|n3qCm^s+3!msfDmj$FxaZmHd4}^A8c`^1Ajw&v#8KI4YdGb
AepXl9_X8G$dju2jP|Q=k!Tci2cY&&QwZbz-I?{+<?d59Uq0WPJ8uQ;NBG|CvA_pykAs-z8Hz^WOuma4JIC=gN_Ct?{lIhNuDhH-
+Q7-E8DhvvYBI+SbmLCC9KGQ6)C{tkZY%)ZiXiN`7cYp|u=6Ijx<M4yKvSd|ls4a%0w!D(Csn3q99kh72?q6;54GGlQMCiGAVHsv
c%9~=0^rDwIo*Sgf+ba`--mn!IY~-BTLE$~Qalr0RljcNL}7iJL|c(*a+s#ub+DQHC}WyJdaiUP9a95mtJq))pz57bo&j{hYMgDF
k9{i$gmPBtBeVcQm#B|Yy3@;CIzxs!$(ml&pBffBO;^#KZbSjmoXUM~q{c4~X863?FL*%Hy|Ug=jAasuIaMu_s8B@9>!expA6x7Z
%A_5QC}A#Dfc#h;Gg5t+vzhSPNT<8{mtc&@%z`-V1y(X?`?!cs`~u{A(HTzLVQL$TJWe~&yOwC1GKGv6kw|_57_qi#O1NelJ_DW|
>TuCa(){FW!?fw4t^#O4t{q6~(Q7Ok^nRf&7fycG?2?_7YDg5hDQ^Ta<~F^hEQvbUHkZU4TrjJywO->vF7=yNTbd$7hP(8?Nbflg
`R}g-J2RjB`jsiS2wxc`CY%59D75FG^4lBij9PKd`aRQ$fUce#zaBDk?dJNBGt7k~w^5R@+qJ_EkYcK~v@sjVvGd0RR(i#bng3RJ
Xgmq!0n2lht@7k4c$j&nLcZ0nXJYR8LH^n&kCWsfk(Dg9S%aido!GWcX5sRu;YQi4m?Ni2XXlZ%gSc@%j=#TQp>KF3|3{}x6`tw%
dNv{qLCFblZmBe)dLwba&HPxY%C~6-T=Gi?vh^TFv!b*&IGs-|^pO{p-*<D-#Pm|}iu|{94gx6Car!ilgw%L0-|>pXs_YXoFOxMm
9#%fq8OsOXfN7d))_M2Td)xfE@<g@ZBAF;ys0oc)?qNC<M$+6r%S=xA^-EQPG-!Pykd`{$aB*eD1CY&{bY!1+-=<A-q^~Ciqr~?U
e|4IErd~y28>4}IROf9^lQG?>rh_89rpw$E$ZQ-UV11wY?dAtJ9cJ(jJkqx5BPoG%wY*36Oc-OEb|Wf&J^R$1Q*K_N5Yz2D(XvrX
cBY+gU(-~XFt~^Iyar3PB#*liDRY-0FAwd5b2t#S-EJ;pz$@EO{+a+6m=NOY<=u?S*8<D|Ak&%-6HsJ%he+zPT9R(*U<9QfMeAuv
r$)ya0_Y3bHpZ`QXRn@lefxPIc!T9RG64i4^<N>*+K&e=)Nvni{F1)ViLGM^ky=isT^mWHE&_Syl4ul^RHSZ$uN>KxP-S(#k^{Iu
oIvoG05U-~4}u8|;Px@8fq|md4ymQATIeTzMtk(Z+?GNvz^$X&0NbrvP>8qO)O4b1XRSqxz8b81(|KxtV^WKO7DSkE3x+%6v5l;Y
SY1jiCeniz4N@AZtS6@tk?C{-TTcly-HjvHERqmN7qtzM-NvC$KTzhILEuBzxc@CiLafX(^1(&unS$$#BqC~i7idmjp|U*?%2<=<
L-pa(A=`keX(W!phyYs^T>%k)+lfl0)te8xb_JeQy3@m+262Arf-w(g-HJPf-`y4W$0~t)bd;xUpCpnqu*LAWYNU9a2WJE~a6xzl
^Y++oWP|5Zq~n<ZShCgecXit{U$K^Aiw?X4vby5+OvedXDte9*<RR}TyKBq!F)3ftd7ga81x6eW%25@AUET40A(!P2)9bg~!OI=|
a)-Gsf8K%7bu=zNfd!TB+%!(F-wsmapiBwf8t|Hd^@p?}kH?TUU-Fr7uRvG(jT-Nl3;|lSi-SQL6FV3bOB<tAhy!DaNYBCr0j7y;
ud>RVomG!N{04Snc>~$aLe7#~NgQO4SI`5m;we$gs|OQ+tQZY4iySe#=GV*b2-w7Pzg$P0lvw~CM$sDSfb{nsx;D3%>Y(cJ2&?%e
@QHe3`kb<;OfX%V=bWZZ&$nB);tg63nVB=1fDiH!*=c|I?+&!%QO38#0(Zi!bwO;}s=n^44K#Ooz+}2tN<%zvCDzf6CP!S7lLkJ&
;^di+Q??3dM;uDml%@88V^I6F;i<%Ss;lTGq#Y3vz(i8a8q;O!UZCg7%SI$tO225t*}(q059z@A42&UsDR$>F4yDuKkPJ)q!k(w<
Jy^hyP3VBKVc8DMMKdPYDG-*YqNs1{Xv@X_B{zyK03Hc-X7d!TMgX);f$|rC+TgpM6^ByTF|U&1{rL5<N-)~T(nzkNZHeJPN>c1C
+NRG`>>vu#XtancZ#vO=k@{*<@K)PtD#{xQlOKDU70Q))0MBX~Dae%71$=7}ab3krnL$F=ojj<1T{~6kbW10gx=I?QOsvi#$Zl3J
R|0v1lUj9kO^)}V!?4S<a_+1~_;HMTrGv(Xbat}qOjNo>n*ddptVLAuAVLA^o(_Ex0JDjdv#ox>$@H)})VCty>`M`=Q`qaFxHJ;1
(YiP)OQw#zQB>1Ms56V$b~~~GpU$ldG-VHz6|E?W@iKQx1ft*B>2o-e6MGBkcIVafotFbWQ3kS8J5HGqF0TQ4yzH{);Mb$OC`?mY
I!uh?mh%Y$uY1=V^PrSN_%`k-4*yndH7*0p)w(yhdb2!~Lug!%GSiWqVh=`@j(Jm3qsMln!}VEml|&MJ_70e(vK-SWS4G$XzDlnp
I;US5Zi!K(EOm7<C>iBihMgw0i2VPe82Oj#1LYq`B>QmMF9VSaS-C!JWBKV5NMu!i8O@2T>euWaB?8OLxak%HRJqYIrEv-`lnvSv
GXDadxgSf&F%lt`kOL2Z8Qss^t*q5c=HyAtv;82ryZ5~N*sFJL#gB`3gzMpYU7{zd(9KMEqQM4-Ty{hzY&u3}m~oxy%XFa7jf@l~
webBR|NQz8l)0U*^Jc!`;t#!ucz|y=2ep2lM3MR*cbVZde`n;e{&>MKQ{u*Y5VcASiB97z>-H)N;Ib*z^(Nc;L*Lx#x6NRIsuMNL
7@+ok@nEAXkpjwxdJC^QDd>kfyVHgTE4hNHM^^s!&-|6ng{R0^zuvY`<{}8@0fK(Vmo|0)N-FU&B9DA&{3EGQ8a{8L>mQz&XgW+y
1c4akwNjwu&&@6@b!Ddu{`Qk8I-c<}-C&>lW05l5(}y6}c1WC#WzOCdNn{+hfn22L_RYO(I#bz=^0v;I^u8C*;oFYr-LCp6WQM)t
T(PP{0%&P0yj7HtJ-W5a>8625zikA1YwIbs`@em2iS5z0n0AS>*`cwS=x!p4*F7#Fmb7z#$$RHDmss`y;w$p^IFoU6B!afU5)TSc
ha#9IMIsSCvm)FaBUmRZET~u1pcdf*a_XR@uxUx692-D=H61G-_Z_+NOQ7#{fo|+Cw59ch7`quE$sT>h3n2`&o76-(BOQCCK;&U3
n*#J;H_(OTuu2w#G%<K`H4RfKtYD_}{aRT#r<L!C_SPQl;5&0H?)C_!xc%1Fxuv-M9_gzs0z6G8cW{?jx3`@I(mo@;^^(t=QlWh2
{gHL%%@PsCR?ReoYvofQny3Jq$R6F!_9Mw12c;QOgB&e!jkW5I-mbbFjLT$In({o3L(8{+&qDxV0+rx{^J^~R0!sU32)h}zy91T?
xZ)>%=UVdpgw-QXr{lUbgeBJJ`gk)$plP?FtKF`Yymx5WvMG3i`TSH33dp%V+r~K_=6F9<56s>-EybJXU$zfYJTVzo-?N*yHWbRF
VW;D`H8L&Y8@Y>10#ah=y48=D%5<I;eG;)W?ylS^?pIgtjB4Q0Vic#6If(BD=<q!N5wga`t787%Rf}yrgwTHWqNCQKXnq+Wl@ox~
JhLggsdD-NsHkltB_C*=HR|HhKx)P#!U?tBl3;f<i&{UPY@saXVvBZ>SA(z8{UDQ{Eo+Ir|D5iM+;PGzvxBhH>q3;+bqZ)r9W_U8
o!cAm?&mGv=gBx<Hg#FaH>x%%F;VtBK#5HwWGHdeM5N9=vKtUpD#>)DItgSUWW=Ym=n}rXus<c3C(Xp!BL{=MDMPI$;LXD0b}E#J
?Z^jgZD3vjfK-&Pwjot7fEUdm1mPks7~5~9f0R8YD>$iV8L;K3-U|x<6yc~qh>Zu;gnbb`#_OL&%bd($w!u?+nvQ)o83#FqqA%|N
%5)}KT4pa(Ue(GP9-r06Esx{~*x0X)jDe}lQ2FR$CE1Sbio5{jotBXz=Z%659KJ$OXZdBMDK?NHYQi$oxRY$pYvbIM_ozk>u#2%Z
wcJ^QE?ZeV`I(GREJ0*dbZ&CfY07Ps>qLbtDzPit2%joHJ?uohTF3{gpEW%;B&YO6EYmYF37a4w-09Pt!(m{b)%*Czb#q(fWE+Y>
eaD+c(}4^vd5e78#`!qTC4lwH|AH82_H~#NEZFLh?02g5?_Sui)OP8#3gn*kl28MVuZW2BEqdNptTj^xyBwfNL)&nh|L#0Dn|78S
^38IObKkx@6#u$YaNBw(y7*qA)$;J0jaDCP!FQ(g?Y$XyYz|XnL&)WYVa`Zf+@f1LlX_<LRwg7I0iFG*Y!ho;c8soPn>ZL;c}bYd
kxiuBLCS0g^132vFWW{c9bpV)(`hQ=yNa&GD=f$4tfGkuPUt#`t?3k5-v?y~0<>Q9ZlTs!u@A&zjP@d`t3aN&s3{^y>!tXV!M<l=
cROlDJB$XvmKUKIGnE9L?t(GX<e;?U6<bXLXieLJGKP=~e4|`sF&|{E40u>>Rygd$ZRUFsskaJ8CZNU876U{Y>0tf3Hx*j6AYXoy
wIzq6Spl4mj%>`+HqzROz5?Fee4m|SBVIA1af{pAQ8?|v8@Lf^+)W0WDKyCp{wTWG@_KAv<qG7<mZg(@J@PguzmAY8n_Cu(SebBu
!`W=Q5f~syDC`*X_&KAfz72skQO|6(Q{F3m#aN%cm{~}ZiTn&rbXF&u0RaMhFgsG3&QZGo65&0UDr*J6p0<O@GBr(};%K7Bh_;@y
3LdQNl+V=E$$7+2u`@!{Cn_l3LspcnfzTDsWY;henyNQa6lZ%95u<5%kwQh>A?SS__gx^_M4va&`%DGzfDF+`!GToP?@WxP`?d;$
L|<l2h{%+=uIMhNG0%W}Y~PJk=y{?@sp)H*?Mt*raWm8l+DQ4Z`MGT)l{Sc7vo=l}CHX_NoMLxmCgQ8O&KBV~1t894u;rKzR0I)i
1EFODd&V{rjNp0O1wuGbzNK3v$Z}9oI2+zRWT)B1kdry)mM5N4z|^8;&an5g<8IqX4hCsVwsC%)bS^TR((a?Yj`QCg2)8VCw9?by
z?Z6_oAts%%c||b_B7v);^9!N?Itf%wS6>HU?-{kGlQcT;;r+(Y@=Zbu`;}{a&RIS0V48<?&}uJ<kBOhUkL=6oEMOAsIYxDci1jv
;*htR%r_;NEr6^qgOkpeOrk+9nczK<$-X>0d+EMjjMR<N?uIlZfahhI1#l~be7gq_10qe`x--g@KqB3Y7F(zMc>vS;*hbpL83yXM
beP8l2FBTGJdc@tDchk)&}Qq@xgsu2`Bq5NXBmS8O_Q&YmocWf-;h*z$rNODcxfHtlBb{RbOz3SlD`CJrOe3y*GzuS;6x?V5?VQZ
l$lxnTaLF|9SWnUuC}tti>B9(mw(^=-(ZqPsYEF!d_(*h%0^7`$i1|NM4`BS>@+V;-_0-GJg4=L9B|!z3%o12e?5S<-FAJfV^i!<
uh6dBr8w=bC|cM!4sEJvAyC;xs2l#{Xd9RUVY5v$YwtcqYJ)!r=Y=^?m=;+*KNW>@VqmFC0gDNUv_o}x)r#&*N!uzVirWbHxk6JI
7xJ>%k>y|>m0)Sbx<OensD?^C+qHBIqzP^9t4Iim4Wue<U%8BB$)0yMC9@DFfC~Tt03e@Rrp!&nH=gIcE;*OzA!E|TAyaW}WtYVv
(~yyG1Ycc!cc#Aq0I@|`AP=b1VIRqq<pdiOziVGeW!;5^r*jb<a!^cZx0xMX$V(#AXQd<vEPn0Z?vLLBw%HO>V7g`?_biRm`jB^7
Z^p{V*zvbpHYYJV$5XRdb`zZ`?EMhCUpARLo&i1w$5mdEv4GPtLrL;&n=4CT$WS{UO0FbheRujxS(nq6)^ZyOZl!fdT<%DW&w!<?
SG(;<fr?e``(U{6A8B%i-?`N7jS$!_WY9W=xi)d~!nyRiBBH-!%ikgvG<Qq}u8NvdwlDRj1fpV$om!Ba<F>eUuGOnr2(UNUR6Jmh
u&0K~)#~C4Wddg3bMsdkF6~rFpGwPf5R3szD^{2w6!dc$C45j3P*)-#myV|5*vxgD=jDBs<8E@odBw7^FHYpZu5C*&sW2~velO)+
wIgH(RzGYLLujl+GYuNRl2&0!P8cB2M0;1R#gj%mEp<13jba<;t`;*h`t_Z6N<DSojZ{4YvbwN#aGVtCZBsFe3^LH{*?szv?~0WN
j2ipi?6Q#qs=B3;5)~g@NturYU#U>4LflivC^6<^bHUc?7V^#nO!00T=WS4$FDvKS6%<vWMx&-YE(P+1eJ)!%oakT2(t*}<)?#j5
w!V`?is6^C2nI!6Fv4u-yfg2Nn+fTYKWHShVH(nDsZ&7?;!M0v2({Y?MM*PK?l#*nz5c;2zQjzJJs&}9>*3pc^1Zdz@e}oY1SxJ-
EJZU!^bGd6+3{!672qFq+Ah;!e$?ZT9vz5(Irx$(KWbgXEuLX8NZOj}yfcxf9PWpHD^xKeqMG)-_)$A~WUp<`1$*aAE>lnfBQp&d
dH$;-(X(sn_bM7Qb8BQ*9W+10I*YP}Z3*>GOY&jKfs!BK3oDz2YA%Jq1LF3Tlnz%k6|>m#okHpRK$i!{;NsVUUy>qiWotopm%r`G
Bj^B`r2~MgvJ_<gO{XcB&%^3YnNVlI^LyY%z%vD={PM_!!8nja1E_u@wK7Rtx6DQ*jSyI?tG-+|(wF0nKpo;Xok3E}LK|oU4bkr{
S3KbfUn%PrD$p!EY66#=vYIb4R})K5<o@5LTV(I}3qO|DPL<0Om&V;zJs!4^4#!nemShmLY!j_f0JbbsM9zw68)h<rsKdj2N=sl0
vtzRSQN)A5lG$8^2!oruqJN&-x~iqiJnTSt40Fz`EW&V9d!uz%GPp72G(z~UoNz&#W2bs@#T*S6?sv;TC$`<#V|eXI`$E2XR!oBa
yk*HbE0xMOFHH+5_H$OQJj>_NY$FBR<t6rf7OyX0zFy^Wjw5QS4b%Wd9x@#>ede6}vAiL<APWu-or<R^nT8bvbp}^OpS`SBU8~Wm
uSFBBwHmC)9hL&z4v=4(=`tQ3WW@$=QM6|YaR(@P)}laW;C#b!^eV#TK&x9IGA85cmZqs`B@tZfl`{cw`H+>64}daLteBSOS;th0
(gG<ZanE{fkL^r5)rrpHY~#)lj40LY2fnMwmNovex>?Xo*m~w{s2d~NdYeiJKrZ@Hb$JepTmf2$Wxq-nf;5F&LA2N97UX^bD~H)V
)p7pkc^8qX9ZyUI%^n-zFir5RItFN34&q8h7DkFyH-Rq@@mZu_CESDcy15!{PF$rd7zcer4?&|SN*A(h?OJjy6zVN!PCOJ%+XoZH
sE$SYa#B>nw|8+dqok3fnF4Wx7}W-RtIHOy&}q@4y~)fu0J&o<N(A16mQFWxS}x$^Uw_!C<~k0bj%8zmNi&1_WMe&4&(y_oYi}Fp
KG;tjcsbt)zM7QxO1U*!HudOxY=fj_Lp0AWIKs33yf~a*>wC=)dP158BTc25z&f@BE?v`XzH+a7h*|=w3jLwE@uO}ej=vza^*;w=
KM-Bm#@`}0i0Vk~e+vd$^z_Prjqtg2YM7%_!*qINSyg4^*CW@V|69}!P>yWbP>EtdmY!mWW!p#}4;2_tnxI|16&R;2;HrTf5CL_Z
2%y_968=zWq+v4f$rrs9kl$!o(uMcVdT#>J)O&YUNYjN#A?>}XwrtaTTVHV{htzZ12CfzX1F!$`G*@y+frb}}nrnwd9d3X|FCEzH
ozwTpMLw#{E!PHi9_qeYJFu&_fePV<|6&o2krQUM<TqHU6}g^V8h6`BS1a~n?)qv!Ljl{<D!loZmV_?1&RmJMh<x%rd8PPWvYMpB
lwSEno&WRl$KlYK+~rnu?UeVu2w!#_;qW%XlHe7fTp7($8mXSeEobsh-pD;IO_AB!l%+VCJm0!gi0(YWsVbWQC&3wIw$ok)P4qrt
0H63(6(*{0A-|QvNh@z%QYEJ;<IHJb0qf5Ax7qCh@r$ocT*~shLpC6fcE&5Cn{4o|H3&XCf;r-TOcA?*#uRO3lt?R60I)TXwXzse
)nH88FOvd6C?&+~#6ndxR@sMVTm^1ofh%uWY$JQVZmY>AQcj8}W#=;Ro*DAtu-6jos&#Ty%Gjy*y_XY#_|q)fMA%(T!LjYEl31=M
NOtWF3W1WI+m9!&BwUZ<YsM<8Q^zu6%y_JsU*_JKToQL(y#mtA3#J&WtY*jX7{}U3M<W=%<V3$Zyy4Q3v8*o`?n+gwT6=qgXWm^a
lwhSC92J;XYT#B{USQ|dWc{esxStj<(wY+kk}DDTGBmSTzl^2PJ<b#h)SOv!yP$u3jYM7uq;!92)09NxP!%W}J1FUHJx+jnzoFqB
8-Irt7XwnU94LojmcYS&DK5zw*Si;Hi(fw@C%o*&X0Pm6x)r&`UKv<Lw=heUktPt?KXy0b+RsRbSj1Z~B~WsKD1ngC;CB=?$cj12
Zt1Rqk%-{NMF0!!m>kQo#mEpU`Aw#q%pq~akdk}*X1j5!>J{@)UNwTc9%<Flk)~>~KXeQHP@BV#_K$Xq_H~O?1FllOwBcyn<+UbK
!)iP4S53B^3U!L3Q(HO_T-{Y<ZRidK$aqvF`UgsQInu2m{o@3%R{usjB&^-V70g9sb{=Kf$>8kb_4G_g(E+HMIVK5uOTy#(SCU4$
2R?QD@@$N+>%;O~k)dY-OBgiPztlmnk1>CQXGawpGs^?h#NQAc5rE!4Z>k#HxN30Lb0J@JVhyYq12Qn7=-(QEZ=-b1ly6sH8_zmx
5oGQuTXUO?h`*($#LTk$(e5>=YW{xdzP*&$8}0G#T8DWi@>H<(D-ARDaBiP5vDgOdpXoe}GVoV-lt6gN>-O6bE|=u|mm?gmK#QDu
!q2iUX-h^?_|TTd8Vrt|y|Qx2<6&0@kx@8QT6=3Eq6398HR~DPR&Q%WrQ0;P0J(|+`Dz}KGhFl)wTeCz+i9wPJ2J|QMT%wu16Kyl
j|q(e!EQo>`5<ZBw!^2NGFxH-ZeoKT>!kW*-9jDde2F~Qjo7>t!1ma;4!~?WmADX^mVSJ+DJzgKx5$dHF@mFBaJMybRyQi+L7h<a
wvj5VAl;R(!+al3P`RuN4UNq1bFYn*&g(BZbDo9=bvR3G_*^<OB9xtL;+#O3(Z(BE`5K8tmK*G!`QzDnmd?q*N1n@u4Ft|0=GJ5{
UPdXwc&E1RnfV%RIz4o>^@CR4>f>{GvyKT%!zL)8DI0Pah;n`9j&EtFlxmc=;k;^_;#?Zts&4GeXuGmu_lbO->m^N=O>}h<bhGw}
qXL)~<1R&GqJZSm$7@9a?UMd`ERG9$TDZ&6^)z#m#R)5ok2401e{?1%Q%FVCQ@t~4_~fop?;87EZzu)+_duLs65`znp-&NH7~qO_
!%-^9b@Z;H5aS$6rrTWb_dsOVuEQcZTmRe2_zS_Irp@=dBFM#b-(Tx$x0GaKRFPSiFYpiKE>_JYrEnU+N^en7AU!+mha#?+TxXyn
P$fTbZpF&4z`3<*L?ZbFyozO|Cb$262AQ;vPB4dhL78)q)BzG20@-}ZL<OLaZAeyAYi&s5s`d5ddt%uQ@Y%5IzD!(YVJ9(B$|=}d
3nF19>>Brr(fUk*&Xd@!D&I&{T+xzI@x6%5RP4!ZpNJheq9l2qHK?(_XD)B$_snIt{V{VNN_NwI2B=zGr<BWVqSl#%{LNm^j4n!3
17q{(W=~s`RL&c@bD@2Pf2XdncNwx=m^kBjP&t_nrh4IiotHTrTep8&yn@(-$Jo8ws`wB?ree+a0E_ZHXTMVZ)Qzw&U|HG}4$TSu
mBOKUpM)K{%NZT6ql;eDZuisb0udZwr{dRbgS~AJ@<T@wIe2&*Q&5-YACEEfCgFNPMv6ij_0SUJZwVU^y3IvXumvCV_-XEj6_r}R
-^&B3@7C0#E;XZloM}fpJMx_T0Ng@-gtOo-cKg;DRcKnpD374Gz7J$@$gSNt4nQ}S>|N?qUG+ILa%7Yg7aT{j(eQ6`!JO^)1%q-|
bPN6S@<6`FS^V|#vJ~xrGo=Z4UfyjkVS1;4clz-zvtsjVdhV6?oxHq|RmUm)VVr;wYI%p7IyGQqmYLh8a4GFJv})4Gh@`sc#+Dk}
OpdTik7DHGkEN}DFO%h69YJB#`_&!3cBZ351>Ko(+^=-bV#_oHK1ze?p>^2D5fp&@*xbDx3v8!cl7A*#Rq$97Gg(mFY|jW9=wc8Y
h8BZhO|AeUuFqZ%Y!v+E3*D3;2qoykDW8R7(mbT|RC#QIW_48eVISUkf=QH%<Vkk>1k*~BB`l37xarH|I{VVNiY`F-#8R|RG(`(7
z}VrT+xESt2(_`VsdE2&mX2ygW*xe@svnV|9+l-L#j`r5Xaon6dVI{m0eIeda9nL3N$;`A@H^6-3j{v)V2tb0>3p!5x`%C~^l8*w
!D4@1$q3h9U(@Gz%Y_o<ltT$fvz=&}m<A@Q)&x~p?zgPz;A}@ie)t}qlHixCrnZJEOWQa%5d?O3Q@gDr!d_l6yRE|HJg2rh1FMEc
Ms%>+lncyfVb@FGDz+0084h?*zo$F6@-^MZIv;^3P3%)pjmSTp?l2?FKZc(<(97`C1pl7yU_hC5x;sk56)kXvbfwZCYX>+=Sa{BQ
zd{#r=x%3<`VAxPP;6re;oV$LIR{GCXTNVSPB3fay1+a&-N=nQlp?P#_hUbg#UgYB5%RQ<LYHM$8FJD6A?4#tx9n!{wY9Jc%Q!!2
%R|{2r?XGPL{#y8Bb~+>MZ%HsjoFfyi2Xe27p!MWv`3htz1#Plev+1;B}KgNa;n9@PBpUHp;6*!iuPR#={+sHdJPT%dn_^ef+%q+
{8yJEI7-Y`LRzjFWp|r(DS}jJQScq%fI#K2>xpqd;6SOiF`M-SkHT)8BaTo&;9RuxxX0g0G`N=LJdSnao@m$2PUKQYh*+5I{3y%2
9{b1V*x&8^?wOOhVgl~+va0vLzA`ad0-#@3bhKZYa6O>GVhR1JZ#v?%R7D#^47oU?XNuvMe(IU8PW0*t&p6^q|1`q{CJ9fri44f+
<371h)DI8m)2YlKc_<K@m21S^Aa}mkTz%=lmZtlvj;)T+ERoDVY7@su$H@La?vDd^v$8wYg*6%yZt?Ou3f^yv(ww>CQMK>GHj}Ht
=9@~RGg)YRu+@j?P$-GIquiPdOzGlxv(@a~*+2Pp_YnWZ-Q)Hz?;i7?6SH$J+3LA+gr$kNixm-sy`fCMJzaW{BiRNSl5Mm^mdlk)
rlMFFqE8^BMtyLA*jD^eU{HdOeEfbtQK91&-KY@Bl-hhbY7&E)j6#J&z`iLOw_dtTJpm{I+n2Y`74xl8gTG8kG0;lK+Q@I+J^$Zt
6ZvhFX2E{(VxX1Qt9L8+i)}RDYiUgOdo7LTd&Q*g^jm~SC;>T$nx>b0`g)#)jMR==)-=JzS}8;-d;nzg16OKJLh^w;wfOZJ>h`y@
(NWd`)Z@dt*`#@j*P7#M{8VfFRE3^c7Y$dXtS(|lXc>Bc(K_4RXZO^9Q)eHxpQVRrNV8!V8~ohGLJm$ujC0ox9D1=59?|%-3)#DH
J)(j=;8nm;@Aji9HC;MfuX{K|De)rwj$58kp0XwR0AjS=r#lNsvgQBILxw(`eZqNIpb86$lm-+{F?9uPgjuFbqlq&ujg%Xx%yhP3
9UYk01&PYYb$(oW0T)p{3%6r62nR?LH(6A5<jMdUbC8AraRRAC?G|~Z8NA^8crz>f`XrGtW<kJi8#(1+nSp3B|4<;al!Hnag0GIt
)s!%yIj?F%o0L`QL<#HVT&IG0f)Wy%(sGN;(lmgVGaGC^bSb25`4_U|QdX8_G)n4%K3eg*&W=W0gGk3kHrJq?(Zr1pxax&;ruM1N
Up@(^&6agh?gX$JZDl_i36saN?MY+c<qV??J~h8|q6l(XlptxO89&4GR)=kxsNrX|m?*oSHlHZHN1o8at;?WH0*DI!=PBEHbi_K@
2H2MNDXL+}*0krcoCTg!XPb<4BOUv#76!@A;`s3dQa4zbbw}Pe>Jf7TVM>_zm$DBp!)Ju%6*My|0a3lLLlGjSM+gYw$@pigrW#c)
C#H4HhkxfRXLA;KVo-PYC%BVLm#Mg1_c}9_-Rds8e2B2@O6#;!G|Y7_Ap82n7U!2EQW_1>qw);}AOV8*$Q3Z_0bxVFN;7JNCsOs!
l7!`PA!=O3B#6fG;`6lijTPkc^q5|~UO#ldj$gVFE(QYrcb0Q7+UX}%)&a}&OQ0IWxC{yiF%<3wusbVU^8_}6?7Z!5=qsasaNBHi
{sX)fO_Zer?`kcokVn(0kcw!O2~S1UpsrmsFrV4YBO<xlMgvXCO@%5>p6u5viBfF|@PZhS64DQ6{Z4YkS(d%x?bVL`Y5@p%Vk88v
+*Qd>)d&DS+H}Vnt)UQeHR!Maek97}ncK1g3gavxi7mKokoU<tmk%v^`*keSUMLap3C&JAl~p6|cf&9MV_XYRj>HNO!}W>wy)z|}
i(Mp&T9E?@qFQmN#rkbUj)17iT4PIEU`|m9$!LinaQjfdn|oCgTDt9vv2qG8zDAnw<3p4J_qiT~ZXrvNOT+#bSqd8K-=}0H$i6S-
i;?nilFJ%*fSUk@F+#Y`PCljCqDCVwjnO#4l2_QHuNb1IlIbhhqo;ChE%?M>#v&>MF^bfnVNf`A2Dd&}%lQ>H&LmXCi%l8Cs+{t`
i<2dE;WO98PZkK@&8X{vxZW)=51LFoTNG79%7W3Y0x`X}9gP}l^>Cdj^#C#DfD2>!zJb8=zg9-rjOAaJ#>5{#dizvHu$qFK3d7^e
_Vp{leGL>}>;(5nM)Y=8O~v!G+{RQqpU?5A1>%AjXZ!kL9fwAu0n0!mEghxgH56Uafz_H{59&-3+w!2!8w}*NkrlUJPabR~`*Fp?
-aFL4C~TxLa#F2)2Ma@i4y58)cr<Aw^TK^M8r#k82TCvA>;n-i{5qiZF)ah;pH-S@_<KO+mIbu9twWFwoGb~MpmZ|p2dIlo_{YEf
mw)@WfBXLd6l?>B
"""


def _install():
    for pkg in ("syncrackd", "mtlib"):
        m = types.ModuleType(pkg)
        m.__path__ = []
        sys.modules[pkg] = m
    for full, src in _SOURCES:
        parent, _, short = full.rpartition(".")
        m = types.ModuleType(full)
        m.__package__, m.__file__ = parent, __file__
        sys.modules[full] = m
        exec(compile(src, "<%s>" % full, "exec"), m.__dict__)
        setattr(sys.modules[parent], short, m)
    return sys.modules["syncrackd.patch"]


if __name__ == "__main__":
    patch = _install()
    bundle = json.loads(zlib.decompress(base64.b85decode("".join(_BUNDLE.split()))))
    sys.exit(patch.main(sys.argv[1:], bundle, prog='syncrackd_sleep.py'))
