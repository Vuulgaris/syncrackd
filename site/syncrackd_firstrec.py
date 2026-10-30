#!/usr/bin/env python3
"""SynCrackd, the firstrec image: a sampler for the Elektron Syntakt, made from Elektron's own OS 1.42 file.

    python3 syncrackd_firstrec.py Syntakt_OS1.42.syx
    python3 syncrackd_firstrec.py Syntakt_OS1.42.syx -o somewhere/mod.syx

SynCrackd for Syntakt OS 1.42: a sample player in Twinshot's place and a sampling page. Unofficial.

Python 3.9 or later, nothing to install. It takes only the exact official 1.42 file, puts the mod's bytes in,
checks the result differs from Elektron's file only where the mod goes, and that its SHA-256 is this release's:
60ea94c0df0d9a829321aae07496408b043bf74d6cd421f493a0150c16df46cb

Unofficial, not made or supported by Elektron. At your own risk, no warranty. Back up your +Drive with Transfer
before you flash. This file holds none of Elektron's firmware; the file it makes does, so do not share that one.
https://github.com/Vuulgaris/syncrackd

----
MIT License

Copyright (c) 2026 Vuulgaris and contributors

This license covers the project's own code and documentation only. It grants
nothing in Elektron's firmware, which is not part of this repository.

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
c-q{($*wdxaxVBPiQM!?5I7ID?FZ<^?Oru{;ZCPZ1xZ;#RSCj{aNoV{Gb5d(N5naCPX3vx?!S-~ae{+$a-)r({nyXuU;g@U+uwiw
lm3UF|NL*;Kh>ZA^z-@Wzy9s-f34-`fB5-7{~2XJ|BwIq%m4n@t^CXJ6IK6-{`&j&FMt2(|M(w2>3?+QPd{xx{cZcVfB)C|)4%`g
_CM=ifBN$;KmDKo`R8B$_RoL$`~UVg{8;Kw+b>72_vc^!>8F3ENB!eZ|JN^nInO_rKX3o~kMyv={EZ%k9_jm^fBE<Sz>|-9*y8hf
>{;cy=W2?zD(+ToE(PaJN#_=_i@P>OyQ)gHe$y%L@wBmMbo(EFm%f6kTXsbqr#kYMOtwaETUF8J;8fa`v-=s{5z66=K3%q((q0uE
j?;y*Q(u3p<?ny~%P%z0|N7bD|Ngc9@=t&N=b!&%oijcLs`2-~lz*XzrCMXkN2ZRf55Z>}qw&rfA9O87X=m+byfI-{+ot@MD?MAA
<kFc6ufbpc0}uMY|LbS$fm1HofB5;A`kz>&P+V|7|F3_z%Ceu!{8Z**xZ0_dvMyIyNH(~uto?J_o}KcCQ`Lo_XefK0Tf}^|(CVb}
dQyFAr%R!>+j-VN?ZW)KQRbwtiIybcn>pogSMe;Z{T`B6>2x)E`cMC!|4nmqV{X&$TB{V(ZJ9#<^wt|^X`0S?`tFuyV^`eaw9Br}
#aXGV*!$#ZwWu%8z0rYlfj=w#YTe-#om_l7U2!MAnX4AnGt_-``_jF=22HDNj0(KwwDw8SnU}R!`lMsWdqU+)bAK&{R>twBp<&xJ
rOuFzJ1aUZ(U`JRF>QQ`RH@K&Xh^)FQJrT{XF^^2=j1SG=h6{XQ7$@Vi%WFe5*_@LW~nz7l92^A+HL5Umc>Ps?Q(cDO@x}!$ZFWD
36Z|jL-vE-lbEK7XnHxW%`?<=<JCZ8XOG?3b{gr;t3(m#`_edEjqUP8JVmLcY8u;_!iHse_N1lBbU@r%aP6HdbAcXb25YC3O|l1c
{%EbUFI!Msf8m@@Nv)66##}wiM$*omhAN(h_CXGy(Z&{fz3E@2uITse*tfkLb^4tjxODAf?;4$j^|?V0Dzp|{<cS_{=^P)H&Ni)P
NOA=9MrVr-0eyz3H#!j--yQ!(R9ilm_0wZvac~{KBQ#&4PFs?>>WELKIPGBafpoNM4sVK9F`TDya#(S0xP3jiJrOMBL($PHO)sL3
)L}L$MO$?BMEDI6b$Sno<ZH|Y^+V7b4R)IcYR37>7^snlxwTS^<5hG;M%iDzMrWNX-nk7=%__v|@EY#)8U}yV-e&I9s_V%~jm|)T
Jx#nSUJlxNT7rtQrLkGwDX!26!%}UKAhjnqRiuRssXx^a4Fi>+;aXfdsJC=8-(c;|*h?*&>}23h(E-gr@%)2v+*#BC@8Hr|)(@Q#
2SJynlFsJJM4G0`SMNltO08HNEY#9KUt8rXR#S#?nsx4VeTu!Fvc+D}Y^r)XY=&-PI-RP$t@J|E1&{)cY`E&;s%TRwv=SiHRmoku
JO~_0zY?VBQk<@(>CY;gY?3afZes$+VPw-3{kVb7;SE`+fgk6qZP*z=dOcB2>LAf^z+^#A(P3TAm!Hm;yYHYM%e9^px__UXle0RR
0}gTmg~!^dhhDv3CU3T)*9sE_vqIVDbFZ!55>A_Klj5fzUc0e^$y~d*<#MZQb>6QF6}S3%5_`t9>EKHhFC;MmjXu$B67Xs0^)YhW
&}sE_OU;80?iw_m5{K8pZQS^zH-s94G@#SAM5&Pzi_N9M?Xo+@@vBC+Uwcn$h{r}R#4hB<ZZts0<R+R*b&di8X_KYfo6i4A&!P(B
+M}CM6H{@!w4)v`o?8nR%D(Pl)Z^H!Pc&oi_UonJ;wE=PzeH)TeEaNE3pV&j`?js?8vWIwxfQsH>)P59%30VBUgo8Gh~qw=_hP9O
uQ{7_mBz&oJ+5h4PDkwN?$*c4j)KM!^-|+<@Whr_x?brRCt@fnHdo;m0`Eot`Q?Gh3`zwifanZyZgljNI@XHQJG!B_Wg*mFWF#hy
Gv@HU(o41MT)MNNQSZcLGF9j_&zfy_`beOAZjcnE`mRpPKm^+`w?j*y<t@W0kU`E5&Vzmtxo@n}wy%6f9^}4HL%Hi(a}Hu2z4pq{
>#`h^JdvszgHeMS^MN=M86q(i#5m9{fp#V0b&?Jd7by+aCoKP9Oo}iz#Qmk?I13XQ;^v4|3c{;`W0q+~oz|(&+|sybw%TW+3vn+B
)a}~LI&CP)Z#fOhHFZsA^5R!%q0QXEAbWo6<c^q4E@z&fgv%HdSW!#$h-gG5^+?h|dF1a20_s|BtIr$rzx=nbsy|Lpq-haLHYCNj
8#()4qi>ID+~03h&R-nO+}LRQ_4yl<fBgI(9ui(WWT_P6`y*KzjyL7|L$vzI5SI$ZzrT;x#xGQM`3H<Y+E2zG-`E42zB2CoR5L>i
Pd0Z2*8Fd-I`i^R3gZWbT7OjNUyop^Xzmr8d>g`2%}y%0t<1vdQf&|um5CQOBz4jyc#?!$HiJu@dIyOFQ<s@Unj_jE(h@EOvs0a=
%XmFmIwHp2Xs`f8#}h={ruGUIq=p|Le>-|$c6L9KrJLR2mcs9TqkiNvNp!<)mIV_jbJVvwh#_fp9o=wJe)Z*St7{!ZY^qPZ?nz8a
&WDERO_u<P+tf(QLdFxKw>(qVOtKdiLW4=6`OH)GgHjUP(Iz94wr$d-Pg=9|tW{owWZsrqSV#^kM#t=uDGCa#RB6EK&}YFG2b)L`
C3d99hEpZl^FU0~Jfz^R)t64_(r=wWw_}}c0w|aXPm9x5Hpdk0uCa3TfVL7O8%9UB>AaE__uw^1`W_EonAOAI^HAb=Q?f!O;)*xy
Y}A#7hdvWeT`dg<o2`rWv4p)~|I`?5q8mT)Xs6#G-e~Lre)q%_(%*^s)4&Xx<1L_NzS#69isEG;F@N`RqsBRZ^>TA`RQxjv6>U!b
uH|(*RKX7VUhAPZHcNx?cy~Yn>`sw%ng$nI_MCWG_k?XGW(c3GU!<Su?T=SEA0?unmoklBUQ0I+Xb*AIczIaS3NDg%mA^as&blh}
d+LprpSB_yV%x8NaWt`MmL?9JAh^Ke*xjY{bvvCgC?-VuW(@}9R~8mnzm|x(qp`Antq@m_7uA8ocg0!OgUKfm1_fm|HIw5#Etb=E
=x6B#hCo8358H7<@un($TFg(gZcQD+IePqYs<3nw!i_#3tNw(lOgA4Z&v$P&;jU?sMUAZ7akjEdf=CYS_cC+%tAs~;H?AMZo*1Ip
SfFE}W8*GZadJ{^d7!x-NDpzPLXs`aJc}s5jGP4co21AibXK&**Mo=?KitwV*k|WDX%}bnf*l8Rsg#DKPh=V=j&}WYB-CJsMdhD_
?$gfEDJhTxAvWNIg3o93fMN-psHTJL$ESc!yl6{F0Htz^zM=h~KDTzNrN3oB-i=WQERsCC26+(V4Lpq1yRnd@1kEbZB_k?fZI{l5
I!z1V(onOqm=<!yyI?{$f<W4=bW=i-s-`blwj~o;=gzU`(GXR{g^dGsz3*~~g+OmM^@q!k2k7R(1RKT<(@W#9WbMWc8iP~Ifat;W
kbKafmu`lZ>u}U4M_MGBQKkz^wb6&ygpfK&FAhvdPbnl_ziOByX3`dxN?J`PNnr}z$YDT$n5iMoS%LN~4NV#pf@EjdFN8|a5hG5<
Fo&ckBB%!uJX|ewI~hI|w1I_)CqFcFlO}T{{9vbr{sc#N_BD%WkLzBxth0r+j5nF@-l`Lwf0@uA($L_Xrg1VLtchPA6N_FZXU61U
sd1YItKp(%Mj_Jspsa=EL?t<$e67+Z*KL^QYGqZCLg&rmW5ia-EA8h&K-f>bfM7cC33kuY_9}S>@c{G;HU&c6>Cca^>O^;u|LSc^
jjVotmaKht`iv%qVDRu}Ef}0XQAAzm!Zh?dWw1yj22T1dBK+q*b?Gb}&DF-H&EfQ5K#9H4CM?ET(c(x|pV=5L3a&TSgSzu(u<oqD
#h@k+0aO|Ep;fW^aPC!)d5C9y26jx+(iJ)xrL^&7DkRFBhSrYCrYnUC!(edKZp^XGg=z4fkKLxR?dpvAoZK8dak}Ag4R8fd6Z3{h
;}~}irMjswg`pHd;W75yTM*wtf`}_>in36hm`}k55wCr+Bg)5)40E@WA@29}eE1SyjDe<KslS>#n`G*5G`9MSGy{!X{QmHlj-vg2
Hf(;VH_s>@$q!zSS09XF8Y<jCJnz~MRURiiC%MEz0gJ<&f(D<im{X4>5(6JgJJLQ!_VA!C6F70#+%wqr2*VKlW_$ab!7I=p^uC`Y
I5zv>KKZ}UQ2azDA^w@lRsmu3bh}}RgMm8<U7ZL0m36_bs32AzFsswO92{%M!3Y}?Kok8|gIAS4EtPH1C|8q?YPLgXD9M>sOP($*
VyM%;@rCH1U!X#b`p_63^gGSC1{wnWtx49kJFHpsJo@hK77G~6O!M1I+K4;bsNcP@fIH2h^aaMve)7L<(}PZc1MrY-vDm`4)5?Oi
amtG>n>b}+1~Qo1OFV;0fjAH+Y!CisqeqH<V}ndICCv*RhtJ2@3DMkJOB8V0DU$Y07qWxO^<wRvl{yZ`pX#>>^g&^NyeYy45uJ{j
IC7MPu9Da`T1?_jRBDzR_);+8bepp5*r8-X)K{emL%!Ur-ZsO|NvSWIpV`>Pk)|K_s?o6s_E#!N(MkHMg@77m^^s<kE95torl@T6
C%u{Y>nEE12ef#p7~UY-OM~d&>^b=__WY5CXQ~JR>FxEVcU^y?_U1}|z-_+_;K$wKbSHiF7XQ{m-aKJOhj%N+Z!;g%IDhRN6B+a$
zK6zqWfhl(<_pKuIQ_{mK4OrTivH`gjkss~%}M5OuFjVk>!q>DU!S9OpX{{t`uz>FukN9xQv3mL;M^f`1<x2wA4uB2*tNxDa;c<;
Tq|l`b-7SFs5e3pKjP5+h;iwK;mkqe*=aZMfvo>G;@AgI5zoBl=^_nr$M<-$It(5X#6+<xCXGmgJ0P|Y#t2qHGw+~18YifI;JL(V
<p)Q~=tUh(oQBy%0RrCeP~D$ae4LA7<>g>M&P}|cq)muUHPzj+G}G(#xB!!j#@QSs#)4df)QjZ>4}zCpB;lYtUr(xCwLE;f@jUT^
nH$g-Gy4Zq#p$JiT6HPXv#nLLf=3+rFK6=I`{tC{ELWH9Pv3@T3$$tYdwIloKiI>Qc+e7>L#i_eY?oS%lLu))yg!>W;YKH>iti0R
HH4MQzIW0#QQPK%c~lWLHXLOqhQ=*5&&pCsj+m4(>{ZE185;4`=A><d;Bh#}J&q2*)Ys%MMiX<x@XqdsZs|PkN<3q_TmI5C3>}|8
FFzaT_LgcxA0J|X2MxU;HkBZQVn4i~ctNlTvJ)&G(!#<P#h>i?1(#D^!~<^Zq3{C3;guE~8$laVp<<aI?<dtvfvY|Zo0c7~M_x{m
AJ>qq1Rs4(Ybj?a?t3-YZ`jr$(P}#9-JO!gzH~c`*MY>Z$KiIzW)dRk>}W{0{p`e(&I3(<YiEbIBEaM|%c~^M4dswp3nmpJzs=Wa
#L%<7Ji^467i7iZ?d_*+>CA;$dAJr0t=e@Wn-@Wbry{**9<SZfC`?YV{ay4#hP#yj2A4*^_+$i;yqDDtDL>JkqF_?1`sqyXhxWDa
6gC43&WqnRgJ!RTI?`l4<FnRwnwF~4^yWuJyDB<_TFPN2DfN+BQYVFt;%hg<p|F$DxRTKr%0(eV*jNdEncObN!|jAZyg!J>F7|4V
x8H~-tjAjz!lB)V13v5MNAZCG8EUJ770s4OPdhwNvQPfBG^I3rPHCsY{k2_}{*>h<`iFti+gZdm1#Qr}x048)-CD2`vvoQtHZ=}g
tisbNrz4FzeR=p0Jk-tSwk_sT8bF?$Uudrs_Kg<afXd-Bi7H`f;xF>ZrZBOmK5WX;WN@r~r?##fQI~dReM(m2DRi{dQM*>dWYEGR
yvc_}rN1GZFCEzLv%f@I-j^(*`VJ4ebnuxk;#^sOB2L8*h0>*>(LX{X>|t?x$}>l6(p&CnsA}^ICo>ef@KHZ(5!d>}9lkUh5(JS1
onhUMP|_-64`Qh;UG;FT*c34e%F-1;Tm+F_t32LJchb%}6;ERQ>!#rGy%X0_a)gmkokwo0S-N6{f)$@0kNf%hp4byfz6&S9EK<32
nizaohVJGW7j_CVh(&50(o26bfo{s*CpRe!O%HC(r`L6}29bn@uTQ$F<>eQ?sDN`d;4VmfbWO{gH4%&rf6v|f5yb!_dbUaLJJiQo
(Wm0kSrHYktCjlbWL%8IONWyM9}yQeWm+p3-iamY>nEP#OEW)+;imC=fB`o`(>O3R5hJ7u9O!V-WsxBwtD{+w-0bK0W!k9HoUFG<
ThC4s+s0gHrfX%Mo%sJqn@Bf`D^44ZBxadpo2dEaeJ}A-^E8NQ8lK`c4W{k+D;NBG%E37CKOa<z_WQIl<j>`F;xWE#vZ6-M?trC&
`GKaWrQ>g?cw&t2EJXUg?hQi0`xiyhA8XU8LjIB_FDCnidn!5qExlFzvi)IcoZi@jl=VB6^5>PZia+KG&GwVc%Jz$!mHitlu^1($
f~56>WBFPfU*6X6bGx@~0aq@7u3GpR*L08sZs6|Ne1@T?>i)v)U)g+ym#)LbV4AWP*vY}~>`}||xl|l4=~`)gUhz(8Pg@U-gZJ^d
bTrOKfX-vPsgly9_m<#mg?M@xF8RALL2nRGp^dXOvuvsW5pmFUb!e7|Tx>p_a%nByj|+o&?VzgF!{u09irv~|P&JhTRjM50njUu0
jIcb9kjC(|(iE1LsS+e>9U@zOB_!Fnz!#<02J>>n<fud|%=T-|lAJd!tkxh}ikOyqAfjD<yREn#{Hn*z47X_(MM?ap>F6row=FD3
d5XfO3%;_zB_maMs?$|eWzR-c`(e6te8fU-ieuVD(x+LTrJIwFqa=2tuh5j~1ZJUmv2E!<&zXNis8-j0NhpArbD5QBaRgleG}(!3
euYy(rj?RD=P5cjd3PBSo@r$=DuZ7M0Sa2Rtcjc02Y=rFy=2nU6e4jicwo@!Kt$Soyz(uypwe&W+1M(mUae*y*|jULu4fFYVPsh$
#e)&$FbdjliT4Qbp2lwyK(9^vokJ>Ik8G%ZqZi9*-e#pg^vlCA!smAcRmyKvieKj?lF#-zVWwpr76wNB*i1GBLO`^6VY}hwv9Ic|
6sMCy4T;o-I%x-4G0M)H@zC50V0=V|r(I6YR<k9znN+($B+2aF;P=#=NKgEa=(v{f9?Sn5dcP@DktwDv9?pBG3s;?Vseo7@X}S^D
1eNj-xKEQxc5&8gzUN*0);Q@N4RR#YT=F-T+nlq_CEqueU#mr{k<vKzo0tFXYVR|r<EMD}IeeKqlLvby9xa}lJxNVz9;S)WVYa5Y
0p$)-Ha|2ErxhaXG-f*PaA8fl#%-x+&E(Qelxf?mPn#yf*S)fvi%&ru3znq$sfrX6ND>aVTr&&P%)*An%6zzJ<ML5zjM<0?>o@SD
BpsbQ?SQ8V&~vJHh}TI_YQZ|-BFTk#&2f$4Tr@>Ibo6?s+0X{#pi;X;{SgsPsY2wVla}ENLrmw1XVc-<Y>tW~zHaP_r14BVtCJBh
*Ypga0I>KNH+}BVHHX?mXPp=Z;8o730o+G7osqBxbtgW9)T1{bv4;_iMYyvw2xK3-13*?7?fW=*oQxesb5%RM-sg8XPf;5uHUh5k
sBA<Pxj|&ymIjlIYha{X3#Z_TZgu1#&^roQ|75{dC6eWHbn)CBD-OVXC02<LN5;Pu%^C*i{^cep3SbNK!;G5j97KzagtQ$6Ui+ZE
?48v7o+HONiO;+!9WXs`eQ@wD#^<GLJNpFhQ8l<ChIwH7DbH+IfF@9MIKAo`_obT&r{XfmiPAW+&G15r3HAzJSvnZ*G@8M4d|HY}
$Ylsu_)EHQju1(B>2uX$MH9q@<+{rgQ!}gwh4!VxW;B05w=^0A4=@%2nIlFaf12QzEwf&&j=?y*XI-nr=~fWDpmNt)beI4Bj0->L
@%qZ|N4KK#)96-DB*Naono`PBv>08#Y3Q||SBXmyPOp-t;1N_AcvAsJ<`SpnA&z8mAT)?W==bh?Q&2@a<K+nJPLm}mu>*wBv)IT;
9J`dKy4$mLXPrb12s5bp-O@yPBlSU49B+~bctt!jhhrQa{fPBmxQ$0#9MoM1*a}1@z2ZPqV!mb1q>VFS6Fpf;l{n&$oVMplY8(Ii
I&6PW{wAj1+8-gvQ%C;kVWu4!cI*W@&BKs6ips5MpsL+l`KVsCBIaWhrKKngwe7vbV4puL_?(BT=vWKJt1%-hqF?~QY}19sMR7o$
k+gDhh;wCk=fn_6@|y12i-)X9O`8fY+0*%@vmwb)XD4vK&<S+cmg8o1IU7r6RXh3#xMt%)BnzI^i7ReuG1nXX4jS&?HK25A;(tZQ
&u>4;&wRbWIXs2E{caU-=%&9NOUJ|vG(YX`8^V1s*G_L~@DVP;TlcqaOj^Sgtgc-qO_fYcbfhIykp**0!~o-E+(Ci#>Fyf9_0m&(
4nm42Y8T-5rofBpngPnR2@Dc*S^yWp|A?+>4j+Ysw<At1(SdVxOCdxIi|yI?@z&zgT9XJI5mhD3cuKAZy%D8mE)8RH*1)(Cz%gJL
ibFM{i3lAt2xHS}o|Mi*G`-@@5M94Zko@dvL)Fa;cz}wffcsgh=vj@0gD0;31<VUEPzCYB90D9#nX{UsZZ{h8*2DAIC%>6$B1D0X
3E*k(HC5R-&dGla&Pl_G&*BFIT&F(7fcVhx7GUKb%qTM-Cou=Nho=c5N8bwK6NOv|c>*GV&(b8^;BI=nwNE{H48e0J->R?%Wm^Zf
M2l;7<(LYc^@{~tYhNXh_STD=RL(#-v0*8kg1P9en|uKRF_A+NdaMOzqR#XZlnT+9kGX+$tU#pJ#4@V`!k;Z9?pk83(n8D8(Xa%v
AiUSK6c3lN1ic#!nz@OYF75>poqlN$W*iRP04cQPIMUcuKy<i0iBcMvX^?D)&($QE`M`)5nV52|iTGI}TzjYy1ndY9e-RjxSgFf3
4`4x<_3v(z196=P7KaNJRe_!hLH8z=gQ%k`L_L$URuv))R&Rxkd2Il0lL5Fo4`Ath0vh{tR7~|g7{FoArXw-fjzsSPBi4b(f-K!v
F_4sjzc1_oU=l9ndsxf2N}{5s|8v(Q>DoBpEJ>4{CzOVmgB1uyR)FY1TLC&{_PuRbx*cS6tioJjLhYTGX00-$leS^N=X@N>(rEAt
uSYlOI=;R~xxuvnyK(Hn(*1-+TKmQ<72@>n(C!9#Cp^CopU!ZG8T;yy>&M~U7whZGLktUS;V+Kg`={xhxja7(KV}|zfb=HiB)Y6K
A*TEh5Zj+aZ)ds@pWW_Jli;s^=V(hjG=0U`2$Wg%U7IZ$8~ghSl*@y^6_bI6`PX=SQ3qDrU)h0uabE0?kj|G5!w(YomrkFmd?LVI
u6a%2?OZUqlIbEY#tlh*f(9mX)ul5*5pWl_GW@}VSfw@z@bn~@1+A}0jpvaW4eVB}o<}q!?<cF<9HkJA^)RjWAOjKsHu(<uOa={c
2Wq`3V&MR>S{^XmDd#AS2*WXh5M50Zk~=g|E)EW`kY)rRSD7FH?-O_`bsmNkjt~{I^VIV>P?qQT4DsmRnIzZj1WIcx^@3lE&L_xf
-8wI8g#{j29G+nt@Gx`E{;sGzd}cI^3yK|Qqs1*HA+tVR_C`-v$*4o)rW?)e4e?>q&DWdc>@ex>=phq$SJ=gW*sx6pOL-|{C;#F8
aDa^jRq!B&59%2EFFb<HWBK9@Y$omTQm=agi;uoM`xI;}+Z?l7{p=e8zm{0%yu3+igm!5LX$4#QD_`iC!mp!<uN`-uR?bhUpYd*J
-^Sq-oo(n5O)$8rrP1K(GF=IiX2R^Vk0PoLT{4@NJNDkmc5Pz+VKK6o-bbE>NF6q2RW@q5tpdAmuOUH1-C=l&o&-%I67robxzU-z
f0I<eSbt3w%)h}7YdA+h3onNnxo8AIP*K`XQ9l>BuaY=8o<qdwdX8>Jwgjwz%%C{t(pfPk-SoE_-wlHh%*!%K!H#|DTVR-5Dw%g&
7E$r}-A1DE5Keq%gqVFUp1k9Fij48OR2&}Cx>Ng;gyy;u9vpzl+O-y}ngu#tCb7b76KJkz0<BVnEi@MoTI@|j>gBpiXH!(<tzf7n
h~tgDH2@`mqoCz)OQbKXD=|FMwYtrH9CqBCSqb>jt$msT3{Z*vT6^G8vjfcom>W+~{4f-)Mc3=otw&3-*1xZ1VR?9Xn*ae8%>USt
PMv4<t$1iOG*7uIpix|MGhp6sL3Ui>;;z!x<9*`!BpmYs#-5v-Icl;6k){>_#};9Dk+8>z_)0TzTsp8z>V>sv7!uggWg<zF-^$X&
O}D^*LuZzFcV-#!qvE$RPsX~*2-;j(B>Tcz%|GPzkmN?<4o}m96NaN>9u@OI-OPyhKOzdkwFF6wL7oxA%PCxTFmHt&uF4dp2?whr
DDCIj+*qoZp;ZGuJFl2nd7fVe?54x&ue?Muh|+?l)%w6Z+47gJd>94|ZCV}~)kaf>OF|nFgU@ouV9b;OC@GW$SNa&$<OI$c@mYVI
dWKh%F$Vp$s-I7YPR!z*pu%uYcxN8WY)<HDZ2NWV!SLy>NZ${iM~t8VgI=8rWPDywOOa}+xnU5?f~{;W8OH3b4?QAB+vIwtAjft)
Gc9hX5QS(FF#5ExG@P7cpNAf%Yb-Sv2f@NE$_@XnCbE<SA<PNSWIG$}hGWJp%?3Rnsx{BbgSW<%L1CNyAy}Qyq)a(xlqO(ae<bl#
Vxt{a=pvv9n(Rbi9mu4f-qwO!8kvezS62`oy@E5;|LN8H_k~5Q)2{@;K_|ZjqRaAt@c$EkgI5#GA^#vq8g!Q9Qyzfi4m&xW!CKjZ
*5Jzs=f1G*8{){@`6oUz^Lr{Xzg%`_^=`Gu`@(Lh#|CUF@cq_^2IPblLfpS$Z3oCK@qco$GBPa~g9cK;-s%VY!GNDsd?6Q=bt8)o
PS0RL>Dlbk%FnZ~KbIulh%F(Wj6*f~I2e(E%^1HK$-aure-IK;4bO|F)31p_r4EdG%8~*5+THPkNix$dJ77o9C|zCDeD)ZmL2%9#
V!JlZk0M67(l`=G2n@ooJZ>o5G9m`e6e$V!%E{>(Syy=5Vqw0aAQ(g-c!^A5yQ~fDSgJ}u=!S|lZY1+DT)b~irG=q=v9+{qoc@i5
jsBL$4gn|WwP4B%^v=@}$(@3X0BCJ(6i$LB<xrvDmQ4kJBU-Z^I9l(ko`W-;<+Z<lGiiXXNm@^x4nEYr!VxP$#n(JHaTT&do@#e@
x~|u&y|&o2-<Qr1->;vN2InV5CS!t5qHa)r3S&8!f=P;2OTi?zy15_>0o~3m^yG56JVQ^4_T?F2N@I6JDh1atTpAt={aRS(5zc`x
4=vLK4fN15PmsL#HH7xszv>o*>lGqvj4sC4-MX0U>z2uX(Cvh6a32uO#Jjhmwox_s7ja-*cnj(FHt2v%1|=Ynm)>9cn{O9Mx!41T
;FT!p97H#)>19o}e}{83nCAm<6D4s{D9`GuCS9UV)2lOt?iF(^pS3H_4}&b4hg$|cA=T6}I`KUKp?@m*to--V!Pv3dg~c8q6l&33
7;G`ywc*;|vK6AEyhb(b2eFR#sD`<L*Y8G$qVhXNx23_`iFQ!geHIvlO8z@(h|n;86*C)+^0QD!E_fDdlVAijv-xE$8fGfB7NntE
C%(m>*9mr!zwd6NJ!d-$c&>tcD~9hGQ5?$&CsI^=Hq3kR_i_4BH?dS@;j*Lq_15xG@YOaCDF?IQHq(E%mnALLXPD>fsc9%LRhhmg
No2RHsV-pB;p23Tn4{?B@-@8<yeGs%a2DnMIOF`Z1V-iWgf3G<{gGLBsc1e6&P65r?)!|&?)fREf@j)v+T}D{i(is>u9jz?c0|^l
?$E`+uN`cd=8TE{Y*{SW9!C_pBBT}gVCwR3vYeSVvN0sono^qDfKNwKqYM^zr1EjZh)#YqG@v|tytRLHV@wtau9TOAA6NdTYc#ed
L?bVaX7?V}6Pj#s6}jTq-qU>TNk$GJ9~n$)%qjNV7ksj1-dm6~2UB-Z&7P)diONMM@Cc5*GY!KeCtAgVWn3DOJ#}n-2+~E@6YyGr
TBOJKNtA%uB!R=yB)G}LOR<>NwybB1SgOa#v+gm4gsP_Q7f^FU>jD4@UCSA=#%YW{v3-5`cJ|7m2k0q7!t0PtR5boKK!ZTX{<GT*
mBPFCBPz%I^rehT4#Sbz0n0Zfcb&w=wa&y!z7QcvS{mZxF5+W!m#}sTe?dJ6e{_K{U=~S3)-@5#H4)5j&&01JlIAP~+HJ<gUPeFh
FYgI`H<2?<3e)^3bm87%Jj^Dv<tjp3VWDju$>3a9QEsg@o&0hu8SUp0?5+v|)>=Ei1K6b5LG-IAD%?tcE8QbQF?<DCnp?R1oe>8A
{M4JA)<hva2F>)`Kzyc3G;=GG-Y=GCzn2WGxM(YJC5OBhPR{!YfQX{kv_R~%J)Dy{usUlX3L!R_LunP_gsCUGQw$L0pm<Q-F%f~5
6=4qz;ldtXb@Pi=5*I0Pr-zfjwWYHO*aZP(;?#qM0Z)0fLA(1iqFQNzoisj)FEf5}@#v{UBoK6-)gHZv>c<EjOY3|3Hr2!kw6|YB
3s#5UJWZ-XLbd#Zz1p}}_jU$a)b{pkZ<jUisKVD4>DTz>pa-iyV^z79ev^h-Yu>JDU)+VrwlQp4@6UzaB>SqzU&}kJy?y88BhSTq
D}x-3KOkBWJ!$nt3QtVOw{uIPwf$iu5B|;7(sy;itu(*?&N}_>UG0o|b$Y+-Ed8zZG0y(FH{Y30q2svLx16ZC<+qUS(bB4~?AhBC
$GxIB+L{Tn!L23E%#O*ovKgA;T+94o+y+lC-fBG&8uEr+R(iI#DF*8mU`espU0}QZYS-;{Eyv>e%!i;lOKiZE=YF#EA>gDmV+noN
-H?Ls$(vqBi_r;AZVAxuW->xKcu_cD%rCww7>6Cv4(r_K1e2&YMA7DHcBP36XRgjH5(L$clOK}4^kEhdTjDsN^a6PQE8Z|f%-KKI
Fujf@{oZN0@KkTVE|E~Hr+~3kk|*4`9ze@Het|95mbI?2a}4i!B03na3bZhjcOpj(BY|Z<5o<4FEcO_=tx1%u+qu^CvvhriTWOe_
)Wz{cJZ9EfQQh9aQ0d(<x4z;%K31o~ZlB^sa_+r%#SZ?bNJEVDFW(v2d3dEXqhqq$|971xmKB<kG5oi6?ci}f&-%)?{K@9&Vx3QA
QZ_!fJxJN$ev{BNvz{QTGnocmb3RLqX%y7<j1sbr6m&dVcv_gO8eRA7Oc3~%fhZb!#KH1BXQp(>cDOxDXiYg1;&PIOFL8e=5P+Vn
8B(r(IVCCwJL@09SyE3qew)Kh%Ija%+CHa@D9O)D^aS`_)vaU#MS#c6tu#*&K)h3?X;xT=k=EK%c(%H-PzL}a9EjgP=qzgfEH&Yi
<7X0WIDKDx8gvv^;9lEZwfXz?d$`SMXx)14z*stKt?}N`hT58MrIT)?O1|k0{z@DU6L#?p8eyaAB@{DyGrtO|o_qL;RJ69d+fdii
@V-8RYTr5eTWS367@tP#Xk=e>uiOw&>eVaX2OzCY{=-uk2ul1Ey>KoiDZKKDAie|WtRp&MEt%p#_N64vS$6^J8amDiY*L+D)xKU>
P1z@S%8IXPWSCckz{+hdFtA;3uM!(z6mdE_<Yq!~?K}IB3Wk(c639c(q%!y$;6Khc8LD7{DHamWiN8@JhmaLqLS$<JNR5Y$Z&z2O
VpI~8q>B|C8>NoaFwi~x|0F+Uhm0GJw<wUZD1e~N4>lX%$gKAoO)*c&RJhk!tIOqKXmyhdh+OL_!-M<ax$b)Il|2aH|HxjU<|iPz
(QJroxx8%%S?)}y7jMD-l(i2(Ln8-9buc}#7Mmw{ttx<8Ro#VC#j-)BgSOWyW>eu<lGdK{Y{+M~GRv$ce2_ITde)Ilx*eF{aXQ2X
C#`f~SRMI(#T7(Hk7*Gc&qj+8&h0pfyC=p%%L!gbFbrp~M{Va?It7W6_$WcSYMt}MFT=sPJ=L|(GOb<h8uk0RqJuL$Ut8uZ@nI0n
HzbVxf(8{d6!1ACbfihyEp5Z;rce=1Vh`vgB(jHq908213xj;(40*!_VAbM(+4oYk?#md>kaXj5D;X4K>toi49q!nJMc!EI0w-L4
JNPZ5>#@6f^mg!;UHYH&yP^4}8+MwP8J2aNQ@VOv(!DHAQAUbKRqd^gnPM$l2AXm`t=`{MPMuK%npCN7IXqALGgeg(+}y~vkk~ee
QzUhfZVgyJ5+%#XpKWF_fOi#Z$bxdlqZ=n>%>P<tj%uiBN`bQ>n+VWA0lX!_o(FREnbo!l|DIu)J#Qrgb&X-drZwR)ZcfeXGxisw
*~1lcj)XpdEVIR4=lV&CzaJ~%(D=Rnk_H(qzMNZ<Te;_41WMwIk~lmWS802sRGZ{#2?JGijThy9VtyJ=$z_wIb@h7auszVBnCF^X
OP9zev~G*uZDfKzn^%|U;27{(G=IooGxTxGbJDQdKGV@LHM;5PghEB8?GwlW_cmc;J$Qf3A+6*4>@B9<+FRE5z*#7SCQTi@-x5%N
>7BiFeSm;boC^IcOMltS_rp!+M}M4q;cHq}3s37b4sXi(CgzD7#f&&Ap@rRAjU<Iv@8*JoHwV)H#A_}WOnhYecD0>WYF&{jV1s(2
gD|aK*T!<_Qu|JPYkBF7cO@&BT|?P}!@iT;mTS6i@%d;OUc8}U#xLGi-kOfDeJKN&FyV48ygXfYZqm2i`gAY7!%;f>r$3YuqkDtP
rC0f!Tzp9|2~(<~2D*_1bVD`J4Fr4(A1b;R<2r(d%WF@QbLNG+k)1%7xR%BeIg}gFBW&^;qUam~ZLHb65)UrASpl15#Zim)+k;hr
wuTd3spY9bt8p8#$Ce!)TlBziBCYHekgy3O0B-?=rX75_R|gm`!#>nXAP+a-c_(0RcR(hL)HYOftjl~dX(3`^1l!6wDPN1Z5J(=f
!VUlt$tOACh4g#P;r6A;#u&z(fA|^pqXlHzPf$7Ro2VT287ha=IZuu_nnMk-=5d0Ro_cx2>gZS_*#7}mg3yw%!l<CvG;|NTJg)VG
R&uS&mOldgSbO*O2Z9N4kLjre9{w(A0a<SAOH_QTZ1L*Q{rpBaBRu(n&w*a-1aEtQ3$(<H#lfu`iA%4Vbv`L-q)jL~nR`D&+Xa03
#>3OOZ#+DE$_>66H%!r;?;89BUwM*|OtB|r4-U2?&w`R5UNhv4RW@mmw3_2(!J?}nn<&+Ex<wFMC9Ry{<f0rD1`j8bbxGU~Y$#M~
!mT0{e6zH+kf6NImEWOFH%^wtJPoMSQD<N1V02U1stNmPdddl=CL|kzA8x5A)Fg#qCT7<ix^3-qLZ?M`He!QsdoyPUIdr;}#j$S^
7?(<?o_ISsNSihVW84kLBNJ;uuMtMsq6@h$Lf%8|SsFMOKtqt9a%8Y3q0MX^$1KkwNvBpVNFJW>cKBV%T1<aKqFf}D{++$X#>rwa
etBjX+TP*$$Vs{lBT<e~r*%Kna5wfx3B;1ZTYv3)`1S2Y)?=UYl#X)_l-@<24jXeQ{SBPH7x-ZQAUVXwsNeFQK~0mtB(YEn_nc}0
VEv-%72d8|vMcMs2bjoMlLyoW6JnOYNCUH$D3Y%`9Jt~8xAs148Zf-jo5}aPixCMqIGaae6%vX5MLY))z;xP-IQ$HM#HGKarsOdW
@nfD^CyviZdTZaIf`aWHw^@|liJMMNA6ecFbJA;;vy(n__L|-sw559EcltkF6U{tJnZdh4oUAI`CkaRr|Dnr-3bJsp5%A*Nmnkwf
9+R$iLw;@0F*o^4Zk*np*kgLBGR@wmjdk~9o&g9T(mrw9J+!vqMbxzhblbu&_>Z?BGVFHzvb5}sGT-vbLCg1j7*X4Q`#DiRf2Zse
n9{gwC5d|UEVZ^g^Ldhg9Bbw--x%G0xBCumGb~S8B*(Nyy>mo+mPm32A<Zr7oPGlz9L_-G?nFKuCt!l5eWv!=BELi`16$jIT%f51
982v{?*cueYNh+Q&>f-6I?74s%eRjK4ojt5X|_Xf{`xCN5#$WV{c=RS%!7GTmZ3TCI;*Ir$as1IOuA_-sMjHVabmOz;y`OzVIx~w
6D^Xwrfr{QyV>MVA%66N9y0q#G!Ps>qPW?Ep?!A}QVlLl53awq7`l?eXQ$0+W550ut=@`Li6`oF_t2<y8pl*O<n(bC<eRRL>QCvt
=M2Xm{-e7EDb}j2HbO;dCkpO$tSW6-v}V<FGiqzOXS7;IlE<k+HYk<42AZRXf(CclK;k(0otnOPk1_hbGo^QzWMUX6#U0REC&``V
my<_N_A}%o-5Yo(uk2Y^XJSk_Z30k>dl?dC(Wr3GAZHCdKJO6-R3)R?fQP9{)+NxLvX>9?Usb1@9@-xB+CcmmBcwTQsnsk^*M#4S
{AQ+g*^zcdFlDZK$X*vFC{w+wBW%J=L7t51o3{tj0Dk@4!&LMwdo)^_=epP&^+?0$4kDv;Qg0`p>NtOo823a;y>b3o?b*`Cbx5kB
zO~D)-s_I+D^hbUoxE+3e6LY!2bk%ny`?APG)sMIeY(J~JjyYw3fEJM{wE^>>3T9$__QjxQ>ho?_FY-)nkCUgvlBa!XoO}GnbS-;
b>hz(Ru=c-Ca|p2h#m7uB0=1kNLe9Ko^t=Gd(Ob2Q^)<nWS%*+bJ4L=r<diG?;pwKLi6!zu1_<{oPC6tT-Lpa^a3Qw?QXRu_Sba_
b+=RQm2O>6W8uWI04(QE)$po12v<VdmX?POL%ISdF%Cd@HncIr7`_~D({HCxB8PF)8l}kQ(BKg)L%#(?#qGrtTe+<F6t@>FTM<dF
2H+jhhK&_yp3$=mtplfmMFPFsd2_?Zc=qApl40SXc3O;N=CX?urPhkE)wlLMw(!!dY#><=&qO;`|E-p6q>5Yc8>|vXFPtuSt2xC8
>t~koX@x@|P6PNrEJb>+*nURiX|aSG?DF889B~{iqHhKNn)(*BvVGn`56dWc9qi6B$|<F%VVX=rvNDYG%RHKrr>5E>{u0Rm#PL`G
kM^ELqm1v0b1WHR#;kzEnT`Dw0@S3kn9B~()feFgu&!Dd?{jY@Q25SDm;gdT)?U{36Q2-h##zoI(ya2XN)~$a;G;k-ryO~$Z+Zzm
zb(3DO5ARK9YBmGd1>uuMCZ{O7`B1SPL;k>9T2C_#4=*BtnUrNE$%C&iW9vHx00dtJTdc{!R^x7;go4CGOTtwYU5`8qHeT_o|!I=
5*i*l7ujt{%yQmFGkGf@3#*}%AgJC2XRv~xF$Ii}Z2(L~Cxv5P1Imv;oG;32v<L)c0A7+z{mIgBRCTQN0YFapr6p+#Oh1KG#YoFo
<;-vOH<CDWOyS!RK4_i3ZrvqmUHKp3y@{Ue9|a=IPk*7`M#)p_7_xu*2l;>m3>|i$<Nz}#BG;w568jWMQZ2lt3YPfD_B)a)vp&0(
G1of#<QM>!nkh!Y*`6$;CCP%G5lLS5uBW4?K^H8kNmYQCr09ohy?`#wlD(Fn;^wDxUL^^ye`@{>?oLH`l%2hQkks?MAT${j=qL@&
{+zUm>yt*VyII2Lk^$D8B+Aw>?pv+skNa*gI*asQ6jJR9Nb7Ny_L<tJW1AXLK7LgJ4#B@yPDvo1I36AZ@>}!5f$Q`#w#l*rUTEKt
xS*{!boouYaVh|5P)~FZ(UyR{HLzZ6o84$ex&UEF)2Nhqv+-R9Xj8NAXm<iV1A>uh2@}>)rOu0S9g^v;Juku=;gPm<ew5LSKv_w&
BfcDv0v?!6=o8e+aKMsEJf;e*H?mC9>Qvfvwgob$<Jza<?2{Nz5}z`<KgvOe1eDMS*lv5K9v;VH<6wLzZ<_2Yb=<tdw8n!c0qjAQ
z1l6#9Q5&g?pP-euP_EYh8(uD_c43dl#TZkI8E4h*yp+yrNvj>wI?j=ZJp*<wT@`S;>x_29$c=Sho1N8LfuXdXdaxJ9%b~#@F&&-
en7;m7P%P?WKuj{?lt7)<o1U1+I+|oW)x)B{yyu_XH6@H_uYR!^HAMh55;loJSL_suJk-t;4t9lvS40ejf@U65TVeGwZ@c;wMji!
7Hy=jGD*-@Mt1G(?m^4xmW77FjTrff-9!a)gdT<0LJ0&SGN2JvUB@x`1R0;tZJ<%#_T9|f@mg~ChCx3_2GBiC@b~9PW(-ia(7xHv
Zlyd_5<dqxTU!i`u)v<(N{0oc^|6+Z^uuqXp&fSi$$AQW)-kXfsPfJC6we*_2d1?YX_Pp{HR6%uDq%vo?LINE(sR#+Ol68;5*BN&
q#}6CIIzZk!4o9B$WJgvc9<(>i$_JYw5AsGWrJb&(i?6*_niG750Sf!=u6mcpZE5PccPN`q9hHCPltb|L!i4Rb*(!|y5_NTiYKs7
O5>F1@}YF{X*ZWB_gHI|pIa7j*7`o`eZyTNy!4dKs+kJ6(iM@hJ&VoB+~Zo?EmETH<JY%Zw?5ZWzv{Bhtu!vBb}e0{)O*h_p(mv@
Ki9dhwPJjy)?M58k^Ua_^8-IWm(%v!*CV$|#g9t0{(QuC=6zn)G2x@<SoQH7Z20^MPwW`#qfz_t@iW64b9Y%kjC|-*!LK^A)*qH3
M_dc+pSC*l*spz>W*1<L9*i$+eQ^SB=Qi%e`C410^r>}6@;q%EW2BCD2hsgg>KO}Lu-grpmaG^^iQ8^m(aOkey9?%M4$LKv8+ku1
B0BnS<EHK2Rs$!TomPge75+T#Dz79aI`MXpzp<(kt3<2oICqRdD~G*`ZPqYi2CL*2Z58|t^KzOU;<y)D;HO9z?(@9-fJ0GDiwvYM
Fmsx<ddAj3>-cnDYMK{wk@LJb4*mMOCFwRj!Lw_AHNBjXYU}A(+pQwv2db<CXF5-FPJw>2i^jVc@D;+H`)(J)lbcORmCL6YR;rd$
VA8_lS*3j@`8=F_mIuDuPx&X^y=02kTuY|+@g$M8+)CrDZPjrtjnlh)E3t!1x|R56cxzmer;(^+*3vYi1^IV44sV~Mw-}ZYKcZ4m
`6pCwt#PMgw^ILMY5u4*+7C<PN2TdDs#C1WH_c8|d8My<W=a588P795rC>X77+7C4C&m(#2TqXn1iK;Ku^Z^O3^2?h@nSt*<{>@S
lF|y})^kp*skeQONgt_JfJu4pAy4sY5>0vN*)HW6k#1>2BI)2l=Ligv7at-pV2y|u?OAkELH42}wulB@l@^&+Mau(OQDR5eF-)54
+GLKVdzfa<el8=bfHOpVG16m>T#!*|N5UIiRyx4G#IDTxgXTFh$#W8EbxOPoZFF3y-Koon>{#Y$CyxJVj0fsO{}|)3)|e2}et6`^
)%G6e(Y)Tqel9Cl`^qgNop2JKt!Llom5N3eCp*af9-z{2i<lz0>8vl~O^E++j65Q~9ZO$+@VQzrCY%!M#koqx(d(yLb7M_b?gMIz
@)vx*CsvPmj_U1Nf5wctm5kLi7q3MFpD~z#Rm<8m_#4pMzxFUmLS-$P?u2_uTr%z1_GTw}`fQu>@wUQtmS3>KhweTBlFGK{a*;$}
Ys<Vq9k+;cY1O$Bb%qf!9gTtCukyrfMwlmEn!LLXCv=>>?Zrn_6Q{#8@q~X(_o;CUZ)b_;zfL2p>(J=k$_F|R9B4CVm81Ir934VW
4Dmz9A(>+iN8{Wx(gB#A;{*hEyxMKkB@2=|aR=}ZS`j1gqzNw*eoaX{g$|ApFy%I`33CIfF?l@39kt$SU44337Hg*?@cNDH9a|B7
v#yD@^WLx@x=louIOT2Jcs>XGGVGb0-r!#0!TR~;AxPX%(WWX3TMZG)!YWvw3hvgLHdsv0l2VLSow>qqA~|Af!#avda{=!u;QFe*
a_~C_LWuD0yLzA`fO%Z#%&lySA{H2HK0Q6>Fv<3tYra#%kANc`)_&aZ6fJVr=0xudOwKlgwbhU_EuD&L(&k-C*gedPJ%QQk-y$@F
zCCrkbq%3P@|_6>FZL8cO0R4Wmjp1%OjtV-U%&XBSdkuVi*tm0b)--@x=X<;Qt*&P61=pMKxzm}a_DvB?M_w8+i&gQ2rzQ-+#k7?
w(~yXTd(VzGv#8r?ei2*eILQVa)3p9dj3W$$M=ia(cJnhr(aM~D)BEy;q*dde+}vzdUJ2#PNJrNuC-jeddEHGvV+{d`2HXUY}OWC
-YCJ$5ouEjK%y<aj1#d5#kP&^5RElGZJ}{x{+`?hoj|F`(C19dxB5}(y=Mh<9e3&~3%grKot{f^C>hkPX~0LqN)n_c_HjDpux5?9
MR$*8UwYT(TbPpOrLQlMR&6Gp2sY`nKmvgUj&0VClV;Yn&12S1*1f<6dD#%J9A%j6t^Mq6(m64N{ZG_TFwYT($tTF|yVzRWTg+Mn
j(ysXz3#MoyJjn>V=KD~Jo*FP<a$fZUMrdmUx8Xuq3P)ScUBj-+B3#6|4focy>r3KOw23~BW+gKb3h7+N{J=M+|!<kKWy_tL^P+-
l32md@zdykl1J%&7Y~|zf(HO)Z+7fDq^+g3)eHK<ZRhQXsETw$Htg;Ckz4|Qq-`Cc9iFd~9HHhIEnxXe7EIXRmh5cYL%2o>Z#i=>
y++CYM%3F6Oxk8<yngXA`5n@+owJ87+(f5H!%q{lwWMsD;QR0JB3#epWG`cUe|;-m&>o&9a8vnU3iKnaWnOvr!_cSETeL4ISs31;
@L2Yyc^x7i)r<&pype0Wo8^+IPu75=@A&&x5Q8dou{|DroEgNUN8w%^crx)+X_4n<M4mH3q4JfZZc+>Y%}Vw#S+o8a(ebny2v>w}
okdr3oZ}pufN<g~S3rw=hTNm#RmT-}Xk}XmaWz+RlWA-tj|rTwyZ+^{oOb1s@ek{IV&@yD3l20sNnj@>OJ>)R{Q2^k73PrE`AE~V
p|=h#E~>~q92<rSk{UOuKQ#-ppb#_!Nd7f64-R)ly3YtP*v|ur2a@T?Iq*{yzcN~na?jg=nT+@4fRpT$y=TktzbNqNh3o~tX<uNP
HIifz<8nbTOzGlheFX<ICBdkSWyLV1(Vm;>2{YGd6xZ@vvY*pz@n=*8#zHbcNorV35HYqZd1l*P>_YQBU`=`VkHM;4x~YYhXf^oG
br0vW+0uHtPtT%jXOWjAsp%}L@t)*RL)wG^!!4h068tk11;!k(lUK#G?~R){fLt}_YvSD;zSXjuh(~E2JaJkz*M1B29U7%yrqp??
`P=7%pr`!md=P7IHvWb=k@*SnxoqKyaU9(0P9jM5NP1$|I>R!Hg!OD8EzUaDB1dAuCBj=X9avkgwhO(t6Vj-KE}X=?OBME1v$P=@
T;!e!79qhBYZ9F);C_}T#YuaZqOEDKk$8qkLVC)~D|tot4s4(CB)&!O^lCwhrlI7nqv+B6#Hs}5Kdwj@>)wfSnGhRVI`__}5?_0W
k9JS-enqu>k}lpT)|PQLba+V8ySptjpD;a$cL(%ISt%}}(XO?rQ*Ls45B+vaDPR4;Xb;%W3L$QcXYnGUUMGEWxRnf41#>GIx7aq#
3MiI{L4Ps+ae6mks1@j3K0NPldzF9tjmjqe2oH4h<bOjX_Vr1>rQg^5B%|z?qtK22Zge<WK93G3VKS@5{tBG1J4a%({=j2r*fnQQ
s^FgaU7YdW^U(1R*|_DSEzq~gt*u!KZT_&PV=%5g#Ra9!v<Tkf)>>0M!G+u!*(Fu7mkWodQ=?2hCay@NS@+>~272R5f@YGKT$7b|
;zQgHpL3Gcq6vPt?8V@_brN(;^#1eMoEn~;;L96|gI4GB-0HWdA|k>O{VWIwTM+6HDI@6(?G$4!64w<)I3#eQZ?;L{q1b99vX2q0
Pv*DcQBCH!Dr_}_F}A#^s4pS)P$R%T!O;zBv2rw-o$4OMdov<M*F`K;a?Ue@3|os<-_Lnw%Eq`uDcC*now2Po2dx7;xM*9cbm&z1
o^gGxTclN4qpDzoJlJZm?&!zsy*zP3r(SpAjw{GM-HuLi-GHBp&w!i*#7Eb*E9N5{Mz&kBM{djb;3gczWM|7b`XmlL_M8vMyty^M
0bnR9{++mlk`lxrtFQbe7QO_oeYaB^256yv5cvoj3A)_TH{=(LW%w-62^j5s&pV;7d?_|e<zSQ1S*HGIn#mWH{8XOwh4Dy|C3eFg
l9;*nC~`>SJ~%!WJDZho863xGVTDzK841l<>eg71R}M|r=h?Jv%kAx4m~Ea@UYU!k46KI!ouBe?&Y6)#X3Z|MJlpF9IUD5jS-zRI
ja_o)thziZeeNHGlF3dglIMjjk(g={Pc&z>f!qd(aqVUBzURn6^TuuFe0-r>_G+MzTs-DYhd_1W1HvdV%s#Ltm9Y*S<61?U1vq1X
az~^Xbjj?Ny$CphuuF-WCa)zrTrYNEMB`rL=|~APzX)D;tv~rjmq>DhP7R_#)uyG`-SCZp1<6w%PVzwq1#dswHH#Cj9<kzTvZoQr
E*QI4538fc-ujM61zd?B=zZ;p#0MV-t%~63!Nw6TER&**SP#YKwe~)AX};Owomj-^9t&y*J{$MuHXF{QNFF-E+QZ<{fD7PN_H9fs
9lXg8dGr0OYiRx4wn6WOwP87brXgu8USFs;G?eoR;F365Dn5wsTU*W8-*eR8s(VDuIAJnhk!Z_4p;nr)<K2i)yVV-8_$@w?sPM5d
st@1u@|~f(S+)ZelHY*Swz2Pv{M{qkIA*#d4NQ@2bWtX~M6zA|9};oCpik52-0TgH4B9=$ZLKx?2Tpyu2>jk_d~=i}T8;GqCJ@!|
YOY<z_d5Mv-Sj<8->3TLRR5gnpHuy_tXg)^YBzh+@olD9n=g7Klh%l_ZCwQ)?28la!^>=cT$=y*NSTLG1^a3?O9tLsN&GB3A8NTj
ATnqjLH=?)IPPoxeBQ}N``~{ok`p554Cg24nZrbLxwfA4jwu+u)tC^?AB%WBB)qi;;%XO5AzIGao}u9&UO3Yolf1<}d8Ru;N#nn@
P2OENW}q2Ka?6OMX24BqAbT=e9zb?Ei*R6$a~VOhv+fOUGKfnIw{fOH>uEK%j(%c5ui#tmfChRHnLmgR)pYU@eGo~8A`Z2hN`!~T
K+Jin$A;K~lepiIXpuB^of2btrkw!}YtuUeRo|Y-$uehez*t5k4472_Pl|<7Z3nih+X;xlC)W3A)*a+mMhNHage0G>{ZSfQ^cJ4#
8(daT;z=Go5xL&*9}6yiRP!;m=9x}nZ8P1!x#=6|yu0p242<e+Z81)|6JL>$-BH=>jl_^#Haw1KrFZ9uS`fF8QA7)t5ZmsM<$?~g
>YU@Xdv1O%BDF_6eod_VSl^|**i1Mer1|QmK9eaLSKF+&hPK;f_PWMhc66Q`Zt<GPw$o6a8NCN6uBm-5g6KL+uzEvG%VpW;Y_Evt
r&<~SD0z!OV7849XgYz*pW&)+Q9pP6Lh!XtW1rgAI`1C1^cGXYe~U~m`CZz4Vy=2?u|JXHS-8IJ*|NfV-1jxS@di+f=UJMF>$L-6
p>gyV(kZksjWc(GXxh+C*^~u;I*Zt!Ok`KZjf58Q%1qrW^X`$!euebIURd^U-3ErR;g*3V47AXWqS}x{H!dfkHo+yKL;y7j+8q(p
ZYcy*_%%*CaC>jBrtc&##LBeVEGyxsywi=6295-VSBg`IKQA1uNTNKbui!H4603@Pg_Vs)c4QqZtwsgh6nu3c3aO3prHM9jb|cFv
cQmjZBry|o>YRJNWqV3Mfh=OngntY0QR%+lu31p$hIV<Z0;BZ>_=JwtsN2Ta(5fd=ifq`|^g=NL5Z4FI27=Udg9IhHY@Ej~N8pA5
WdV8!U={3mxA4}|Es_znNH>cvHPLlbuqKgZCK!}N^n-h~k+pKw((PIl`>;Z9ax$dV37TrKj<wb;$4X1FIo)qjx=#+ymc?2yQ$**o
<$E3IVKA0@Qooyvc`rKCwNK+nOw}$F9+Hh~th{IbG?pXC!Y1ns{LAD85fNA&9^M0N$OghVV{;%9hWH5dZ(#Ci7T(`tPCTC~^NAJd
#Zsh~<H(G$&+|H#c^R6Qx#o2sLh3qGRmr(zOD}U$EoQ{K{@G>p6OIM&nkD)C(g`+HV(a}53-RttWrU3))S}7I>6IVm^1fyJJ94k<
lav3hyzNQGSD$9iMlEgMsrAaE@m4FpQ|oh?0kzy)qyNaZv(|hrt9cbCq+hCMK8g=U?QA}aC;p^|Jmtf@mxQnP{ocQ3KOlMsh(P9X
@V&5yI0-GYm!;|X-1sh3xEEWdH9(_q7J`;(jgd?^OXq<XQSzawRwg;Tbk7QGuIy|~MReEc+E!n)=SllsB#OhbH?jk+8ux8EBNdN5
vS@{Tfcz-8tYlJ4#y0U+XZb7^j)0|4iB9(Hy(D>l*fPFZBE!pS%`0>L&iMO4SpsH@y-+YMRudVykQPPLol`XaLktA)nx{zS*!7^q
Q9w<|eh63gxaIyl4Gr+RKiMly^1YG#v&>qL>=oC|>b8tXm4RGzuwIF7*9sptunmV5{{%~YSdm&c8a=HnZbbY)sIuD77n@M%7P8DQ
LsuuGfx`gMo=Hk-GHBtI_2A8BPgUmAZo4(b1|DsFZF!OpPc=?8hpiYNhII_`GjVRr>47&0bQR4$9k4D%%h?KRBpFnGgGyHc$10O#
sT-PEYCKKq-l%OaNW@0$3p}NlvD<-U+G?e7TRGJ~dnOU>X<azR!yTOG5*wQ3<fUT|%UUttZBw%=M$RwUBcV3Vcz77j4wqVn4zLcI
Jz{AFC%B8Uj@Hd+hA9e`anA}7x*W%P=>TZRla{b?{R)7y#PyRL?tP0hnj&x{%AL7i)-~paliVWo!AFJ!jU=yg(@=8O6P#NG>uJM)
OKSMcd0%m7%PH!biU+@EtW3N6ty|_hXNCviN}|_8mYg75;*@pG>x%d&bBO;9J)J!R`Avdv&Qv#@nkY$4s>ckq&m=2$<<CjoNA0)Z
4^sFl%HZ1Czj3Eit^7`{5Z|d4{X4aieWzA_YxMb@(Z|oS8?3eUTYWyqpr)H3d9zBghw4)76Pgzu(IHyo_GI-0&1+cy@jR-$DOa8<
`mK77cpxrc^zINkB^Q|M*lYuXuMm|UIDkfQ^CFdpmZJ~phhX!gdx@q0fJ=C<E%y(cPB*5nv<T*G_-8C?fNr$kSaWxkbH8a@)+vve
3c#Z`?7`5m2M<P5gpRbyB}C7Bi)29}Q@>}4!ISk$?)iLu-3#yr=O<@1BKoibx3b9=*F2f8ybV?(cVM$^I7YY-oVwWd26~7}qWy)h
g|)H96FUK)WXbukNzMmN%U76pNmG=LZZY$A@s<vPK_Iw&V~)+b7&&)Xmwi~H(9XrNH(AJb@0i$Pqe1)2<9Z!sVD*i8j``~}|4tq5
Ez7hWXVIv2{yW`(aJRoO`B>)n@YBZrUTd=KgBke@T=VXGzEbz6b{|QEqn@GB=idm&md3eYc>IpiBR$#cw`3!#`CRV|i*-yZt=f|0
bO4Td%-t7->CYiCDG6M>gVsrpthExQ5Q;s6c=zOvV1wT{x`*>6ESNe-a53<XQ18Ow;9J?aEBbJ;;d6w6?a#S#_@1ii4uYCaMu3CR
$c<uCLpgeAuS%-}B@-gD)fsiikRDNxS37<WE?*tau2&fA0%!#V6tg2Pgm?51E@bb2WF9>9_$%}aP#Qhg)e;q$(H+?1XJ@I0HFMe!
_1@WQjP1rrs2xa<pmPfaf0i}oipQM2(dc=TU&6EaM6YK2SiVbJ&r~LwSou3OAM!YR&7uDhs|`~XLcG`V@&33w^8E?zaYyOBW(AY7
oYx?k*7}*7u^6AsB`(jM;s(VNL~Vy-i<W7Q@YMYxBL-_1go%d?ZD+F*9_bPB7(9u8hQf9Cz+w;VJMYmfJZ8l@@w}jy)anLq6@btO
w?Yia<r5M?aEfKW4#Xl8uMl>{!8f2H4&2F(%v#~Hb8vr>nex>QXi}5T;lt`%p6!O4ta=Vi3(p$ZC!G;7TJ*-?i4f+5pBexzZa!PA
jM>b$bGTN9IJN6$4V!`N%oza;tiLVO6UR-QtPwFelTfZ#yO$CaZ1yL;veRgm=`FRd1yQ!AhJBUoM{NzE4Q;-1@#%QjlM;9g?JNOy
n<n=SIs-q%xAOj?<_oSlg2cb88ymRgkn#dzqvzk~z|({F?_rrQW3pz_TeKFRV41J&M<gW1a4Q>@{+GDt4Pnn+Sji1J7wQ*8b6<C`
X$awGLl8$MEG}2A-iYrWSjwP79evMUeCd<OalOX6J)^;9Yc$w;;_QS5Z;b|Pmg%>$m+jbgwpud($l0FijD$C}BU&UlFW0!P{Ak<A
k4EMFnXL6}b(fX)bEM1Vdy1@7ZA7ePXir^RPEk&6#24~2?-;PKW{GPWp#^<9!@RPOE85XDM&_D#kt3FI2K82)8*1vOK6*asIA>t@
hpJ0y9!N9~rO@GqTQ+Mrj7;}ZfQ8*JcqU~aZ`0QPaExt1$X@RvjACdNMAM7=p~bzDI2P&)>}x8^b;hn{9~}Pdc+^#O<Y{vV>H){j
et<&V-^|ZYsMj01#WA$8Bf=E3>}UxM+gsf*C2@;~iyo$BO{^X=z|}L}FJ#bBH=Z5!2hWarU1v_;J5pIZYPmgQP`j(P>$T705LEcn
^ZgW{Vh|q%?v>-`;(gTdu}8k)_v_{d4LL)9N`xU%JS1*UFXf#)oXgXl$$x~@hbPCk-gVSWPv7-`xPa+xc6s*dpykSwCq})MOuBHr
9jTPHJU^8)17ZO5xJlQN=mt{!t!(n%yq63w)>}y!I4ZT&TbX+`ib)F^ZY2}y=dqN;k>|FaxBjAjJ*zmdJ!`l<EqV8H^l3<4w>|?g
-~(&P-Ab<UZ)GW&ZjJp`GCZgDw3ZBCyR-efb7%bq@S93=o=E*5Ys4iVDv^l7p++W=z%`@+$QnJi?c(&=<KDo#s(S~*@1N0W8D*d4
b=P8C_`c8s2^aYGH4SYM_a%NUcd7M>luG?=jnnt9<+xz(l8GKZhfX}Xl&t}Np_&m+nirB?);o;|#gntz^=z(U!w`&<LhNUgF`9*k
){R60M4Wlppx`YbnMV}MIP7&1wg5~3(VDh+22+Q8Abri5T3}TLE=1$HMA~L<ZW(hP5qrY_#qGHa&a61HfS)eCFIRVzYOMeI+`M32
JlmCy4C&nyIeG({9W-5w+~<H=C%$Gt`oU_W3;66mk^Ndumu-^!<ar&DQl#(#JCu7V2gVQOK=%zf&^0*_nO7ETzzH(bwPPX!hG$tX
ZfF<!2<Nl>7PaTFNPzdcc-(oPaPX&FBuB=AX>p|sz8~t2n+jted3opD81pk(QlkIXUIy=p7_c+-ypKF-twYD#IfF)MT)qB|XQIEu
+S}liTP+Xir=jh+q<V&=hG`+_fKI1J%x}i?W@JA!ht(7|`$KOxS(Kh?^<?S%*aro*jeSR&UfbC8TY0Cv_x!AX@8^GEbk655ujs_v
{2^oZCjK{GQJ?*nS2Sq#hpuP{_P_CpMytQPqS1vvbVXy%-+#VgUo0h2!IFQMIGm;bWM`SB$-*Hmamc_nd5)L(v9?~k#26WIedgfC
-M*^~{3q5jTo{RJ+gN|Wh+oiaxb5P73`2aK#GYvO9Sdig+ZxtF2^OP~B+|}ER#l0Em?CL~+sIqXZ)|3L;xghXGUb_;QI%)w^Frg8
Zufo8^A527aV`&P#^AX$l4?SnRBL^`?&x6@>k-YgzMc0z*w3QjRAQYi-T$Tz49Z1IMcqs`ReviPUMtjxetKfo7Q<&|zqpIlM$KrB
6Hjm+jVCDHE;&AU2bbQpnlU@B{pARiZO#rd_d?4gGTCun@zU(EXD;2Y*mxLjb+H3gNT3o4A%6=xDNy9C5pOH@Com5ja6`3gXB)W}
&*Ok^ALED?L4ef6QWF1LyXV&2*D298Eqa<)&@@e{K@`R=dAkoms&l}1lR2eN=0uc0*J(~$!v>J~nF!yNN}QWS)D`Jlp1<f!LYQ*w
^-)zPGhwc_&17j~N1Vr4D>}xhuN4VciPs8__`FszC!iF%mU%i!HW(6UE&Wc_c04)m^+M^GMsVdr=8>?MaGlObov5L4w~;2byul<-
4nEwp9NAet(Lzz%&muFI+D<>$AjJhAw^=YbdqlHhK6+5ya$CIcm>OPD8+%zn^Kj|&{qX96O%nOU>E7Vno=^_3T@ua$-iIb*UH&LX
6^vm}a`AwQ3fB(2fQb6+W}~g!hE&U$Ea^Q(yb@7Scv3|;O>o9}6Lz|KAiE!&^Jvmaj2xkPr7gjB9L6R4C&skeP_tS6Xbwh53F1)!
dui<bV@%Bpi*KowmTl>>zpnOH+i&P~k9>I8ANOj1pvjqR#mE<7*e)!dt?<A=)JjOXVQbnsKO}=N437mw!b0bw7&%tYniTdGwi!s_
dAGAA=TH+$(6vg7ef|4d-3VX&KSZBQhtj;|MTDC6>AQ(A<PmH7fZa_T$l`OG5E}`%N7{eGl-0gM>&fcMfqVVt&#lh6G8%$S_Xv85
H`=i!!_L-7^Rmr3w1Uu^4SiWD?AdsELg%o|-?%9Pxz81eHoa+cH9v5!@uRs4#^yE0`2HLZb(`ZRm`}5RB-OV51<w6iD}3q+j9Skz
gd>t0UMngQxFF9B0Z}xT+cVr%u@jndm2HVJnzCV5O;_m0I8s7Kjz&gE<;Z51kRzexb!r*WM(!e}h^>CBr$*hZ=DM;AyJYK@EJ1BY
LTC{#`)PCYDra0;HRWhM*|YPZUH6Y~w6dM*2oJN9GsczvcSnH5cb@wRCSYrxAOmHeed*|$>(Rwiv~yp>Ga&RrB820GPkZ^pExBc>
ZlGo5oLN>Pi!VfAHO3$0cHmfy?B)!0Ve9^Q#&vwIp%aEGxMh*}2EBc83ZZv@%X<Yi^Hc8?M55%EdI^cFaz&!8?1gkIIahcUIg8;y
m0o(L(t-S|w}rkMpqJt3CAJ-y(<2JhbZl&n>ZB`*o}7V?{W12mO~jF-p4_F!b(b=50B~xqIB9m5OuC2jqP@fmg-Q$*_u&{J%x(B2
naoJ!RD|TEXS^+rU>@i|uu?Dz>+XQSI<()&^rzkU+hopv(x@5@4i*aH(CBwiIpS3ii!#uyA^r_bdi&k3zdL@jkf&g;TU-!|!&>i#
RvfTWVh!6lV`f#$YMs145~0<6>@Ay`xZc&5$$}GY*h7+Y>R=buz@MHm`Dx{BG;1C$RqK9^Fl+i`ir4p1ojekYltw@mDsqM{s@0;S
9&=vMv)ps66soDLd3yUhSO!F|zt(sDdCu&PD?51Rpk~B)!Gi~Ai89rt+*c?vIQ2NIgJJ~E3Ci_}w1{Z9j75*kU-Y7o2#Odzhh*gD
HG;g^44{L9->kD7Zw&-_gzh1BZ`m*9mOPPoqF2wNL%C#$Jmt3vIjD-P<>Dbk3meo?I?i!h9gYxd5q`8vUiB54SHv0_^Giw)03QIf
Z^UqUwdO$|SyUc&D_FK@^|;5#k==6dzD60hoGrDMln%y;vjs>EVE7TM4=N*fHeY9Hj-MR#5&%vzPqVJ*<UiYMM|(2%c~Cpwm}~vT
YNBBcJMJ~|^S6MmGc(02(Cf0(fy+~V8FR~-h&E=;@l@ux59V<M;bS|pWs@Z5#0c<Y+&30j4J0EYc#Xc<-7EB883-6v;^ax(^djT<
Q*&Mx@G?>c{A{-g+BEz0)4jW~e^uDn0bd!31Z}9*7z=cgd%CdH6v;-!M>3`)0QGjS%t34?ogquYvh|0;=<TjqM0Oq*mZiG^UUv}@
>IzB4yhl<A5;^Jd{v@#)*rlqJU^PM#6EUO-2JTRD2}dn~_$ayp3cyzA@<OH%7wbj>2Aw9K=tPmIc!YAJWYm%RH2w^=w0>7_f!gM+
K3_;sk&gI{hHgrtYb`kcbHpz&_t)bb(vT?Vec=S1#2ZPRhCU8PP+>3Y3k!YIm8dF7o7wbSdm;ETWZQxH*id^&G6?k6a2BH2urpwS
_CTZ}f(dOvjGI39jWHpwnB85o4_U?UfhbngMZ>!3HaaXo?he{r?TCe^vmOz@8F%HgroXp&h0LV&Jpo`9U1@l-)5s-~$qQo0wnnce
=v1vluzG_GH!U{ENxo*Fo3Q>mk}Onb<Uc%pWc{3_sY2Yw(A^d0u!y;aW<s;q8i@;i-p}R=3qP%)<~3~dW(;LbFBeD}o2m^X)5$20
BJr{v^*D6wdz$_1b4O#=?$ek})cP#yWUU?E>hpQt0J_UUzMXT?+1~058oMA*FSVwaPQl9M#J(%OCkZ)TvY4mK!{2eHk&R=+afUr>
@K`0sSSw)9BG&_K&^crC;HhJ^2FB|>i^$qyU;zp;zxIb@*>(2Vb?mW4uE~>rX!KZ9u!Svdy=T88W|{GRV2a%M+*P<sK?`tJX}df>
nI%@|l8lYnrklpDZR}#Xkj&wN{|n3+@mC){<jq>c^FfA=4JelIa;Yt*aGSi07MXp{AkgOR9!Hbc(QL$Wq`*<C#5vHdz<CEqille$
!iJ(zY>X<j{-)-hi6L}z&b3?F_0%jF5_snzLvyUB%;ECjMQVYNtjGXGNsd)wjGa^K3CeNk(lz@F@8_-DFSBKg+BGLDYAso!JDN31
7RP0WTUtyxf(HNA<C4~zdbL|wvxV|7f;7b$mGN}&p<7*R&WOoP*IpafxP^7q(`=32iM0t&W-=^sUgPb#m9F`jH9(NUt<KO+0dGiU
!Mbko5_E4=hBI2*q!~lmKd#!tz7<oi*u;QzqsbF5yTePW&kLEX#2b7+`#aKfPw5(c8(*gZEvH_(W#6T)PR4JzVo0JDFEj97U3;j{
ep|+Uujcv<&t7*TPm!Th-bBgb6)wMZ(Pjz!0gZ@d|EV8HO?FwA0zc1=y~x;KrB=LK=b6i}{<bG1&ij`nQof`5?`O+EbbFFpcc7RS
@3gM=wW^oqZe8JanhRvl(T-$3(N=Au8I-o0Yo3Vh1dUZ5w(yLYB)^uS%~h^0jaT9*QoZJBgt@~lc^b3jSvlA5G<u6NxP)7)$zv(?
6>ED*XHzf*n?Gc|PW=@%)FRvK{WK#>BcEiFy!NuJ(W!bA{%x)*-`+vsgb(^UtpX4=a`Aa<Id2=ST`~lrwfn)jkJjGPQ@u2oe5%(*
t^Bh6bNoXt`7LK;?W+-4`_7E4d)eN-n31-Aik@=XWgwH|E%nJaX~vPHv9^gf4<@2tV3>`E?G{kcEq~PA&eZrs&QyT2zVzxQiEqhP
-g7}Tp3lG?N^&4bFZVp<VrMXtX_B$Con?RZCmGQ?-}#w^Y8~l{|LYAjgbhIhjucrWwqe6sTaPpJ-0HK`_ET2-yS*#){8HTp^w@f`
`H8peR+25R>(5BsYgQ;O9V0gq8D^#&tt~PPKD3aqXqa?}S}s#Y25G2+r-P{0Q4n!tT4wSf+AR3ivKC`6b>kePoSDHgewGq$Q~_t1
E^OoI!UM9r!;MP)=5A|ttWQVU47vaqlYN;>uxZYnGBQ+J3=6WI<mPidD=YM|HLrb48PMph5d3$R{$~8=B3@;p<0k1+T}W2&3<(l}
z<(FFzMGSbr5nl;*K<>wBr&nbl5v$QpmK`OlJwg(dlCNchS??{n1TIIHEb(?XY?HVLM#*e{xk2v8Pm>)Jmc-Ym(Mua&@`^8MD5nK
iX%ctEKJZKV!scPyh)B`<zd&Xtu4p<LX4R|+e${{d=1bboVdM_q?ma7bzIm#jx7<L*)+y(=bCU}(v3@nXVN(Dy~p-W0~5CQ7HjWq
Z5?j%8Lu1Uv!ZS_<21wBFQY|BPMUhT#{q-g;uOP_@0;H3Zjn^yoj=ieL=bYWIT#{nr)E5@q`EDe^L(0aF@elfBeZr2@ss#XNnSv|
zEyd$JL_d+M7e21+npDF*zFu=dN;UaHV@#rbY5xxV23529S~{f9zYNWeZ7?o>ehU{toVI#lp&-o6K=fnHuGbHD~3LyR_qDyPmck;
;l4L-S19<-btGZVUgI80C;de~ckPV1$Gl8vF|FFPi&GwNBwUiL%0yL*<9jr^I{B#~)0Lh)KoI<+>32iFgYDIzi@ly>tfa)h!>^60
JbjTYR*JK$j8%1l^>Y0!_%8SNZPr^Ub1ND18$Jcvxv?7!Y5#Vf=;fLur08W0B)2Pg*k@;QmCp`@ef2i$c#WCzk&H9L*=$wIUR%1?
fH?!7r7KUDyXWU>=j#(Lkyvv5oR_1L7yO@@ynA~FsFp>FS8vAJ1IC`S>nhTnICiG_t#WPE@w<rY+3B9hntdA8#`)15TLBrgA2~(g
(9sYa%5vXIo4wb=a#^}DgJS`1xtHNb*-%h%N3$0hOLmEkXPy4r?z1uMV2{~&dwda4$pa0kjcsRNRiV7)@{pQ+RU80ZZ1I5R7HZh$
D=9}~pplRH3b<TI%Z}Jd``TtFJ#lUs^a7rRbJQitDFcvJxah7cQZ%D+%TvnWe~v=yfYs!~_YsHF?vbsnpq{cE*VU3Z<)jAfqg9dE
d7*vF>`Z)HUya%+K0miql0TPw?1xg>Qq!tePqOc!Goa=(<iWLu@voj@;v4gMD($T`+zT2&)codw+i#;`=Wn-CTH_1Qc8c{ex02<4
fnIni_mhQw#_0)an>;e%@+>(EOhYC^))LQN&^=nTYrZUcY1(J|tiD*ibXc>1VJs6yM!A*Ds7t52&0*Xz+Fc{2XR;orNjgHg*LG=H
@t))ItJ1#<`qiEW{erH;O#0lb<5p|Iju<w1qR-9lXf!c+aB(G8Wp~@TwolW_aAuuxceoEE@MgJ$yg%}r6TeR{+g>8$#L6dZffsTd
34D)s!NPgN7;rgWG85-#c;<Prj6O&E-ka_7D~*z0Fxuu4ct}sN_Nn<m-u2;BZ_;KzdNVdpM&X!q$0)h=FztfX$11ahIZhAJ@*MLM
4v1~ySqV?8y~P4SyPey2@s<p7ctkI#?|Q&6*~BlMcj}|P^IT!dDbCbJVwLEgSZh6x;^C4P`;bDObJPhB6Yf46fGJZq@1<w<#^J%F
p*e6Z(>ZQY$$Ad6ZGZ+<o3(eRm%OV=c)t4>Mt<P#e=fE~Rd?}`fiy+GudODZ+>R_&%&pFX>}Q^1ND(_joXG7rp8FgT-YB){*sp8O
J)}z+9%V~U+X*)h@n+di5X!=7g~08nIcM(L+oWGolYB7QS6d_-ozJypm~+5)P2l0GoY`e;d_%P}J*<BtZh_@w=<J$h%{;Ni5$B=u
%~qt!HfBlu--LbM<e5vpY4f=>^=r>#6*^C4a63zUp1dztj9u5VuRV-YB0E4d+kN%MN%@^j>T`>%?p`^!(&yY2G4s~Vxg|MC@sbA;
b=;J<acEZnqX3<c-q=o?!nU>=8V8++*LG5Oujl5i-A`N@UeD$>j=_zZ)N4I*!SH>yS8pMhu6c<MV|04b@7zlAjZU>J39#JonOb=?
3)lW@m7=o8cB8&jW2_^num98!du<)`m(B#Wc;QEal2_*;rX}Y7R+e6ujR-!iAIhdawSLleieYZP{fVUZnkzyUm%8blOmAFox|1JE
hkig`>D=y5h7{?b$v_rP3$13f5&m2{IK;@!J?cE(qcux_>gX8w!+n%h<JlhS9O73qGosZCehDSN0ws6u36AK$P0ZE$6tBNNf1|>S
^NsA>uS$MY4B67_9A|tl`8K*RS{wg0YGAZ|HFNDg%@x44K9;WS>I*lOMC(VUJ7P%oT$j=*v#Q*eOKJ3WZo61KfpIzaTxLA5gj6Pe
=FIn{t)Dz$z<-^~bA2BBL#2y9CDi<8E_HK68%p!sv!8l4ma+CPT4AR<PRho;6HJ)2$td+xeiF5ogz!YS&LsmyC9co%1C7k?aeY#l
_;iSwYo9@<7vl)i2+ge|ylOM!ZmcE48!6@c2;-|Uq%n3-^nF`PwOvZ5y`c+w#;coe4K5qB)0JDv$Zu{V-P95GY4zB{r0umH$8&vp
92OGdTu!=i9{Y$Rcc(XN$&7ampePUN_VxrlwU)fq|Ih#Who9rmfBLVV|F!<|Pk;aCpZ{dDWss@A{rxZHU)cFSZ`B`h-%~#Ifiy@Z
>^`3RPDHGl9LlNf0VNvJL|PSmwWrzkXx#SymiHz*)9gx;*t^ua7o38FUPaI%#$_)gXj$(rHzy-$&dl%JzNJP(fKYYu{U^zoI5>SY
+hl9}xBvJ*|L_0)fBnb*_P>8HPd|%<(+11rEXehu{nldrS0yrtI9uX-!h`n%O&kFj=kBK-%FKcMM}$!{*7?9AyE%~x#Uma7n$JrM
J!(^CpGyCITBNPUDYx21mBe1`*UgyNp~*DZLQ1HdqK&){s>@R2EMD^sz;T^K2YI0g@>4NRaE2pZE3>;VsPpgOl5<otzWD)k@l@4E
*QCMR^Xz#UL5C(Cy%17^wt2USwwQy`gQ(yglb;8Ppqt^htM)>@`C#v8fBV{_@^NINgkJspMrlTkpN_s}UdB-w8Q(~b{8iSX)T2E5
?>c!9Lg(JlPw|?0r}vA;8;g)--Uey`!q{4q8oD=QT*t58*5WY`XrA0*N|NbCks0xvWYTZU&4fAi-WZiR#+nFW8ZOdQ9)PhUm%gWG
v*CpLmRX}ku}aF6o{THg-$yr?$0R%cu3d-6jRbQs8{f?`emnbbbfcLA+V@b>#QV-DP2HMtopM8*_TSK)<(m(4y8bIwCYX4_=jTXY
*#|wsDZ*DWf+%O-D+^H0BhMZJfG)8nlhT=?=%m~Sidl<C5#sBPg?G#iz#~wzBF+8|O7`lM&a5I5G=AT#3ttAJDe%JMx2)HpkCt-i
vpQ*;x^Ii71F7p)0b6uKxIs=ffO*Ddc{d1e9J5(o*Y4Se!ORykZ2C0n;KuEJ`rLlo+`H$ZNA+Y2CjKm^&79M@ZA)@**Y4;WzqjBf
n1}zAS!rqZz0cC@0zPIWYIVZKp3F%Poon?G;eD674?&n76cA=b+>A0AjV_wuuITgOD~O#GzN2dcH64#=Q<}YYsiO}JE+y?fS+k&^
B4$xUi$X~Pr^kaVtD$`OiU_M$hriMX*+L@5MZj&x38#eDRHl6kIB4Xz|7wx<{2br@ix$zmMfh3vDmv0Utv(p$1({Ua-K(@T^DhKV
kE-A=Ji>u2v$_HMNVy8V@&s$G6f(?wrK4tK=A30@z-g{Ds$6M`QzVzC0+0qOXxtL9T%lI_OzhVHCi5p13niA=nW)~V8r&Xbe;~4k
_sxkimtYq>N`#@#aajb_J*~<LNSlvZe;GsAk<a5w;5V59F?+Fia@yrDa*mO`=d%y*zn%QMf{nWE5Hb%?g!MPMW$k^*&$W?x#LJj*
4-wU=$A*eA0CkXdB8zoGi03W=K1n#|Sj}6O(=|F&mp{GKWp^>U>(I9R?ElUxrAPn7=9aDh`T6e3goxu(9@McQ2e)?03jLdoeBf`@
zydOYP;9TjsFafTIKF-Qbv9pO+4wUmOUA(2a-5BX9L1^_y{V-5(CrG}t}0kA5+pSNEGWux-2qT5qh9GU#(n(Yr3|@rMCGIf6OE#_
wRkq<u3!L=XMkJLDi%dQksg6df~Ng-5ats#&fu%;sS6Hgh}`VauoY-O<PF;$chn!}fP&n!2W)We=rvL0UlQqyvq`~=>EXrTYvKqL
jnkh^Pt-A{qss6^U<ftYVDixohW#wBnP8jC88Swp08yJXf|jPiGpG?<hkI*IPFnd&7yzz8wLj?H($uF#*t*Wrt(PV_ce7R&<3QZO
jnZ8An>R3F9`aid8{-uT{k#C1XXrJPvM%cQzti2a7;h3gtrAcd7gb5aT--E+H4^k7|4cOx{BtJSlrvnZYN#=XK}7b3W;9WU@3&DD
lQ2g_dLP!)-6*}%YY~VEn6^5jz8Y8IZ=VaIU*%PL`U@}|4arR++OnpZqM#FYh@uPtqCgIQ`Tr53DQ%xNRwMR}EsN|(oey3_!zoMq
tYW{G?5naeZ5>-Oh{W<$b`yT<8RH^hfs<Gcw2L-|G<>Zi+^XVCV#lFY_jIAx@h30BUjJM3;onzNLTAmIK<Z^YIu|6(C<TA?EI50T
g&c$X?#oew9D4vdtlO#SeqQWyP4&}PEHQrqRXavVZ1s}xsUD#<sD(PR9+=u`>nU6D?n#r_+qa`KA`C_9uy_i34y^}J18o$(oV}!3
6Ds?CWf-Sn3`_X47Vcc+RbXMoF$K_Ib=aZziE<=LW<HNkpbhYxbT2=pdpM=7aocq2q_IlmEZw+Apuj;$<Gnv))q(Osi!73A!&qWk
0_wjalJEIWiAraA+(2A{d-Z_lcE2WyoZsiW4@57he6JazL4oC2+06*F0+L<(J9jCl`XdwAixqoNvTw&!&)k9EFb2pl<gzA5fZ&f-
&0q(O1pO1h`0q0Y$vKKX&(CjqG=`)wm|?89+=1EqddT~4_puAVDHI*Ke(%%#o|$5li|ZWGP;k)BQF4P*FCb)X2;CON(c910w3kiu
?t`3OU{Om*`55PHKSV3$9?%fb6oMP@9s_b8&>&hg&|`{Ok9JvX*z)Cb1j*6l-=is=c%Kfe(hp$w!a}6r0X^y5PYVjH+|8O$<6TT2
R!efa5j2yXq-z*7viVg%P?+Uj?jK}|4qbH|ojjI>-JnM=*uY#vo%N8$uTlXeGjy>107iH9(Y(X}ZorADWvPsHo*_n1_GW^4@@Xj|
%SN6V)dTf(@b{*cm)w7ETHFaM&+VU*0|n{_8Awep^x)^(d?ejhWUzy|U4wKoS9sH0!e0F6zpoBs^!aa-<N>O(>1Z>ltk9U!N}}o%
RDV7TM1B3=sPQhJHJ3Yurhn&0*4eIfJMTN{hk`_D-phmJr~msIX(F=gz(u7=_(*>UDCWRqx7?v*u-9McMy2W)*ZZXUG3YzO``t(*
A9`~=H0|0U#az=W=-LaWmvxBBRfQA!{>3<n*Z@~33T~nE;@tpUgMH@D4wxwlS5)bPVw(QkN@IbvUd5%u81j3NvfSA-qsl3z&2{eG
i)Veuv{Q}H9lWng5+PA!UBhMh==sN2anUvsNbqV=i=)Hd&zf+S#%HBi`kq2RkK1R-?ujczB~70(j9cu`47Yl2<lF=v5Z`T{9RT}O
cm}ym*(2aKkWq-j=AL4-IcOLGu%75AdWHLx5NF`{$$WP`p~E~}IO=L-@9)-fF9&?DqhOjSPt&6(XP0TAgtY!%>6T|j?lXa%3ha(@
#`P|<R5xm#h?b>!F52=TlWzvQU}!$-Tf^6J-zohN)0k2n;3S|^hWtMebh~^SL~Q!iJ@GyANs!+Dswv1y(N!}vtn!>#kPuL1WPmHB
1(NJF(H71QvA;wMguCfba$o#oSD0&*`hiS5!6{-3n0=&@jqzUoes@-%O)>QP-|N-;$6p@XNTE#l8?$LMyIj-$>g!z-%OKg)%o9AZ
e_?iI=ij^O)5ytNhGP(AMk6KcQ^1WqG}19KetZv3W-GT6b)tUYR!CnU#c8Q_FKffSF8udPKX-;VWglhhL-TPN*QiZ<s^*(NcJYNe
cDn}XT{ePezsF8>ic2Abz1>>C6FALM#6UF#c_#7CZ-LAw^ZUj{?n6q{x}+h=(r3wJ*UT0vnLPS#U*X`#j#MX_Pv%Xh&m0J?M*a}R
7$9r$-5ZF@^G8D1J-3x;if`vPlr0aCAh}0^^^g^SMote9-P8TH0juy?gLHpN;&yIHOLSh0$DT|+%J^`&_Px=mhdTdy=vr>N6>m%C
Za62fJ~q_I3@!Qs91=g9(%aKZbu(gO>Zk<qJfKRUg`TOC;A~g-2FZ!!w5;*GJc0|-%j<vFOX2G}?4YlzIVk|Z9kx@ok6lzUdGE_Z
MT5)(rRIm|exx`4v(r@nrVfF*CBQh)cM<8O7&&`W2!uN$O`-b}ZUE4U5ez8JODSaKb~yi#;3~7)fRzKTy}jG{GWt9A!-rN^bd`dH
DbS{?#tiJf&0pK;yY-?D%5Xtj$m(LzN=QBFx+co!P)&XTsC!H+0cpNv!O#S^U6xYV>I2ka)tr$OF5f0wzvkFM`T$HK<Fp;pH~!hz
Ys5>wqE->Q5kOa>q3*xDr|;TyAbRz08X1N_YoGD&?RuawKkHg=q<uLH)90HRgBC??zv@^U`!{r@Z@-gz!j?a$a)d5*vt}=?6j9y+
s0f4a{x&G2+_RVn83T{YkOxyD2-4Z>*pKtN4|h~~CP=IYq%T0gvASThf_Sut6#xPNU_H7k(ep*edhMGsOgmx*_!OeaWw<mniZ@QC
bciy7pdTznlp~5A*kE76;a5uZT7n@0r0s{gfdCXBchNXNQGDVmtHHx=*_!CS)z@x+!mWVFosusPYB&0d;u0rKYWg$Y4=^aQ{9k(#
?=7oRo^%{<j27NXtIPhsO>_&K98bST?>H?1VX%imSR?suTzw&3-%>>NX`LM>_rCe637&w%8g{;j<c4hlN$_+2MrqXtf_cmz^j6gZ
2HeE(16_#M0N00~N`>;NKszhlji+ut7@r8XJTRbCH>suQ7~ex1?2h0~3;#~Ba}L&#WqahQ!^%`5%8Qyp_@E%t235^C_4ZC#<Bi|o
ozM6A3esu6A<(G|yZ9{@IzL5*V=S~>I5R<Mq<F>WdrbRGI#nH9?~lSqlWZdWNTW;|xf<l*iSHIC<$%tA?)&nyuRY#Z)^^mtH|G5V
1&r$Z2e{Db)$(sE1#y;8a?snW%Uy*pf~#|o!mOp^Z+TT3Y3v)aFP_u^s)Hig@{{JMgq?I)EyZHLR*W-E8gv=Xyl?xJ?B;PKey&kH
*DGAV>A^vk*S@ITzKHT!ID^64VcshN2(21G*hmTP7zL-<Ufe#@8Zl0$g(3p{`{qo!OrP7@DMbNx7BPo_x*wp+m~Zuc-qC1}krLYD
-L<z)XT^OeeGh=#fWQvPe8J4=@yq?EA3@<e0ips85sF{xR#e(vND`DFn<sBXxfBp2{?~NL|9|=)ja2@vZDazz>|SV`>?r0|P;mE2
6mUALXAjo92{bN?LKL+R+zS(P%wYH30a|;`hU;E-h2+wE_h*10P5MN($#U7)w(z5DRw3Lyq9-jg-BHOi<|@+h1Ipgt@%1k2e}9sk
)bsPN=}6jd%4$w!-p%jR(&RU!fY|_2{@6**eQ0Geq^btZkc<Ow`X`n0lgKgbfTUq*@4TK`C~mDycKIN2Q%{%EYebVLQnn6Aiog%*
IimKjy?uZM{0|h-th5=wi+SZdnPl0g`F(0Iu+pHGwMRWn<<h_K%w*MD0GKHs3Sy$y|12+AyI=ch-2r(>d#cG0b~s9nuC8Z+?d@qB
@b1rU9mSYSk);NB>Bx}q1O*2;K-UR|IMx8)dDeT>VxW==r8FQ7AG%4*9V$e<XzF%`9F|oYKQRzFKj8O|N-Zt+r2%>=<UI@KSu+-h
>?n7~+^$&KwP}fMJ&xl9T^}rNnX?Uc)P-~X2IxKtjeC3OL!|T%b-owF?a!<RF*0Qb_wfr6UW_=c{&MYd?_2)&sP$YrO!tf_@IASl
II9&M7E0=Whc@GP*|ONedFHw~Ka-=>4>P>58{B>jR!s2Oh_<Ml5)Ibx-G>p9+Q(xr4xd#XZ9OYTWfnBXXYtDvqIO5+WyQ?#xR7td
UYCugdGB40>c4sQW+F#3P{z_iATF=g<(Ds~va>7VY~67@YotJPq`T*HD;5rWMv~K}=LJ%rgO2YuqT&{kdA`XF&>)Q{4o##qhy1)&
iuz&!wv)snNJt=19ldJ@V*0tJ@Mu8h|3p$dDk4A2j+<D!PR9*Jtsqg+h=2d8)SpwX6IlX43eO!_$jcbt%YEz2jMb6p(cbRk5(~I%
(HWMKo?B|o1X)80%B{H-`p&*0wMEy^qd8%2W)PU!BZ#heGW-J0yr#PK?f%zj6*5D=%fVduE?R%-7d%H8D#f!jh2*8F2kDEhf)6ZF
-tNyxAvMw2`((;fkSE>ne%W|Or9w2|DfSUI?ekq^g@``-&YqmeefMt#U=Y{{*!6tv^w=vEQqT15GmdD00b8EC1p8-56(r}6)!RhP
g$pz!z|X3Y1TL2lwSCi*9l_R*7AEUbY|6^CZ{SzO^{=;0<CM~2#Bh67!TmXZ`hPzS0QBc2uYQ*uxm);K2cW&PE5A}Ae$rIZkG5e-
;N9wVpOFmFf8G_GQSGI)uvhqp0@T1BxS}KTugH8WWuSA929Tn&h(#_(7)oE%-@(_dpr5Ag2T8OkH8&p7us?g=#F9M41g_5w=)drF
P5Yw7HpR8!&mv)d7r#f*j1CcAP<85Ki}Ru<y=1*l`1^Ya;O9phmv)I1dbZ~(r|1UvE+_c~hpOqH;@|g5<?ps_rI8NXB??9>yDUba
Y8`i18UN&EmN^f{Q%c)Kcm?p-$vW_V6+5@T-z7PI7o>{%dX{vEeZCz}yAa1Lf7~~PUv${viH~cS=*1TbKA(DCe9c_<_dl)mw2mJ#
CvVwf`8wek-Jf#ES?R9zy8QS2ru>TvJIYb`lsmUmhV+b2-ZxENSgx(@@B6m+4{g@FQsD^7N>xI=wyD)UTjww2R`35|Kaua?yKTvz
2@jr+T<b07T?DKsY<>^l*TwqxJyZA^#c;{YlnvagD9(B!?t5+D*XHm~Uy|234~NXn1=TAiFMBXF<o>kpD{KCz`?jzB)<A@lHvhm)
a6bM3$Ie05WY_*tE>etO`JKNZ<l}K-p`Y!P|LMQ++j=jqGcdnzoKF5{>2>}M5#6}d7RfKj@I1wWIbFP9k0&H6u%DvkNQ6n|_c<Er
liCce6*79$9E1-mTBnn}>R<ok`_7o|-~HEX=1#m2`S64I4c1;z8a?%w&=n>U;y?nI^u2G5itvaPZ=?q-yiq6PZ+?do$foIWRe0?t
M8m(Qf41_|tEF+N>D7u&PTfw?{Yfr|2L%z_sveNb?<2Q#c!loLNqmB6*r19+yud?0^IFTYx%W3sr}u6<hUMW-QwoDROj_3nqiMdW
`q;hcN07f%cIW*(XFO4!iQ4=Dd3JFDdk&mib)hPb`f)GvZvcMf(7tlCT?3}+Lu+R0{9w!d9QFKFCE|di8rxe5hwLlvPuBHI#)(L{
=@ZGi3g@8ee0pr9(}F34)jr|O<7s9fZxcYI-BfXR{H(Ye<kZ_s`SKQaeta9b-nM$u=SC1E`Zj~u+}`OEcRt@5-T{m1xTvMaoZaE~
Wz<XjJ?aFA_lei`yfkDv+^`ckPS(AN9bkOe51N6cd6C_V+y7f9gJZU%HvB}UMI6}_T$M}NHQlG69?MTDVlSZilmTxj_8753jK7Bq
wDzd_$kf1Z3V>d^hth){Y)f^I%6G3LhEWEM6==L%FJ+PS8|QNYl{$QOo9qAWn9i<K(Diaxv7tuBfJ=tf@T=BUM*5fK3)o&i^R9bj
D}G|6rp$P*>)rewxyGZ{CydzX3HWa@kRZ#0sRuxYF!^gVhAPYZErGzW`wl31gWgOw8DC4e>n~7mJeLaL;Fo-9)Y&z}XWa#~5M;rO
-2MV@bmD6xgSsd4-jt^pj7J>#_V{k@OTYt~arc!wyLFF{hy$e;47aJ0=DM(*v!Htao(=W!LEu;%UU=-E*YmFXC+Yr4nx}tj9Xz1$
H;wFVEMo)PP2gBV?JnG_NIc+gi!(1@@A?E}*qa_SQiy%joLkQ#gVTHK(975<d=2>+-LT^K@BA-3&!4~Eo~+nWiGY$T`(CwirN!mo
?|Y-^aZ9{A$ZCo=^16_Z1kr+#MZ8qWLkBGCORW7tqOhwW1=g*4R`|#P^KKGYuYX;5>48*2fKG?Tq*cll(rBsId@saQ_}MfrFbk4a
K*0A)v6EK{B2N{S2%CC0?m?A&o}c_QM%PdV*O{+?@^@~VmScoJdN*wpNmb&qQ2~VH>)|o$MOTj!G$!-i<vM5l$&D(aZAYaOKVw>n
@QQ6AYDR=+=Om|IS!A9k=_n@6=6Vih2(^=us4x6X4V25$>v(fe@7iNlAOQ{cOCF24`Q-TSAgI!u-x&K?#z9;d^Laa)dlywg-4E{2
kZ+I>RaTH|J)gJGp-3=>`uE0oz23CWhMeS0Tz8SknzU^|^ToT=DLE!=|4UfPlBY}wYsRw>WKLb?vk-(HNJUfASc4&MlU~!)+K_F(
gEY{AzP5kY9YH=Vr}>6)0600aN6s*c>Ez$}Pbt^61XNEU53qJ0ybG`$dfcO&W$>G5MvB;)<>}*!%r&oM;&SjjMg|awPy}s9ku8&D
=^^h}i@`+z!<W649VH{R7xG<uK4jvtqYx!R&7#sbb&sMSUgm?JlZ>=)X*tmdq)PTk&-U*m*gm8$0=f{W`qCXg<p=aOWQz^m4iUV=
X+?m8Mn!8)L4&{6PIf&1jWW3AshB&W!V9PSzDK9$c15A1`&g7^JP3kwj)&@;x+g?tUw!W68}etZ%cP1{^{6g;$`@YG{BF2gYJD}T
4QC0+Q^Hxteg#xD@{(hOZoc+S*VBI=*Sy-!yMKD7mahH#FhEoj5-{Ile8pX@f)4Du8z?TK^hV(+pi}p0H6Z_Z%X3~rvghM-eyGUg
%F(tzXRpYZGV92&VKsk2bC<7PIimN6)tL8@=dgU2rn!jT3ogZ~5Xy28ie@8%$DEsys$OtzYCl}t<A!pkVD9zz>#1hlT~F@)pYsL!
(HQTEXvkLh8PlVE935Wqt%%t^)=w(#&Gd7>{?h#dft0uvfC(sl1l5*4L<QYe3INny??;ex18&Dps|*It2jo}I;OceW&Rx&HttpiD
HXyaPl#>Eih^(u9T_U<4`nuOFH^8jR-c(v{m5w6E^69U=@t6@<e>J~PZTx!4;#_M`ogDZ!cy8mYW7zT$I`pkrZpqXT0E9mhfn-oP
V2|Wy`L??gpLosI+wM0X`~j^(2AIcv)iz)Xvez7%Bv$;*z;EPTPa3i|ZN|S-5M^pI#(=eza~{=NU?6M_D6}H3ci;p6&-%URP@giD
r`zM{725ko2CICFENFZ)PzG|HYqquRMzZ>-o(&69QA)q^d5}W-k@1gGN_}z@KXkuTWoV$j5S5$jQ$(q0BY>kW>2HPLQkuz?7zNZ@
nmFnVqy!4H%P(NQji?G_S)g{N_8Hdv*$p@*z+7VcbK9oJPBg=&HOKyqgd_fV#6f$QPULbZftHd{_v(sK@A-`U0VHnc?wc_h>qgZo
(Y-#hs*!hpn(}<<JL3!>&qbd&!0+YX@#^&O{da{Zhp(WTJ2c}b*9d>StKw6@=O*`n4_8qc<lmv{UsTvc{1tmv?B5!1(JDK!Ccs^S
CA1UWcKV&EY6rhh301)gFZbEr{3JawLH2ZqUezGF*dAH~_skCDwSjSif6Jl>SB2lMrt7T0dnsAY+FnEXEVlVZ@QEW|rj2J_P|5xI
PtVz11HJ~e(VfeTgJ}Q!>%BxZgBF>_Smt2vKy`@r_i3$E<oAEZXjkj+B$_}u#rIB_`T$9zbaaa8Sxf8bvK6XtXwS#nCij+;jr+~@
(#m;=juiA8S|`x{yw_E=*7+-*5jG+vR)W-*AmShYerh{qWiE3`S}RU~-@fan7%MxEXXQ$$98v$?v;DT7WjV5!w4OP1pVp|e*kbzs
RIX~+h*FJzM{&i>?;M^^Ig2`>z2XTB2u7Ab^0}TXA$k?V66=s&v+@BHoLW%y=8uMg{O|msGz>jz05S!oK2(GPwDJA2<IF>3H7K%!
=I5M)F7a~u+bc;e#9aV3)-Q~^w+5Cf-L+7TD(gvaD3oo|bJoJCICt=u19&u0HeP^GC47Q?VB$ps{NMdMUh|yp?j1*VX0I|<1Q6s3
=i@vau!eFHy}OB#hLBT6#WS#j_?gAgZbiS^`^W&aC;HvHi2vS|e5--PrNZ0i^xXgflo3mU7YWtbc#gld4S^68?khJT-bJr}wzFLQ
zWU!6+ubG1h(mRwUaccih-&?!J3#VX(gaVlays(7g^jSEIs#G$(p1ETqP4j^LxIU^v^|Jnl<|JBwO?$(fe`6CGRQV+2$h2q;4zU;
2ZYSA&H+=E`Q4%qGuv{*n#x*V$yH|3YwnqI$G4UWS3cBESMFWC?1{(bgL=`wvqCK$wT?3C(K|&pRez9!r(V88KC_()t>#+gI!UiU
rM*7#CF|*@r`gw3KdtFlT??^$pZ$%)CS{$vPz^^1HN8aM!lzN<u0Bk7+i%f2K}q)R|DG6MI}EXT+VtUGq1&XW<`-E33<wVth`8(D
aBgB|A7?uK6Y=}m^e<qew)?EG6zk=?FY7{Jve!Ir>hFcEQq@PZcW*T4?z&DTcB!Iw^f9}E0FnE;h^7WIC~m$+E6JNws0O;*L7(sc
d^`94{@w<KX?wg3UyyIZU#D4Qu<uj<CcXpV3!vs8jPI&Qx3=GLB4@J>dYC%sy*r*(RuqUqko=*5kA%6^Vn^iJWq_MrKae9zJl(7l
uowYR$tZgLPR~XhR24sJ@w>lRsh@6nMpRq&>i*C{bAsq+r#txr%_vsQ9PIDBTw|z&LLsuB|9X|7J#|Zo|1KedT(iZ011vvq4({K5
{)tGB`~8m+F3>gA`Jb9a{YfSuLU?1^Asdz8XavNy#oGY(&DlMCoWm+=nR<Z`a}rDalke&ktpT2inbWyJ>rhNRuK+W>UIo{g3Jvzq
M^R`w!Xg$(CyrjLP56qri@Ue$I!h;YuH<Q!ezS^OqckIfUTY`^8Fm=N)gR);ZteL+Qp&w1bUt*|qV<u;V2=Lp>tV;=Ak$-VA;qEo
VHM-|WHhjR-d+2;h7Akr{(cZOP)AYgr!?Pz@+0crhV}=9yfb%rY^PELo_i&S9I-%+JIYb{^mccum+nUO6W^Vxm7Y<Vvk&5?L9W!b
t8_NGpT@TJR7~zFJ#$DD1iu5|R8PNzNK~FVEEnow{B=OAf}(y%tmC=$+Redz<Gc4%WaZI|?mix|svfa4Jz~c4LBw}rsA(<kFE1PS
&qS;B&rcGw^oQ?l$o6D@-@8w)TcSH~7q@o=>Dh$poiH0^*bg$Rpc<X4VCYWuQ?CjbA2)sMZ?*i0d)y=MUVVBW-yMH7>2~Txp0j`u
M;?AUL>KhiV6EzZ1JvmzLUFm%tdwM5o+6t1&-lSN*S#!zP~ci6=WBXCA|qF3MO6B__YXq3WZSFCm%3+VmhQiw8r;X1RWZoXACJ06
f1Gb}t@iJ~_x|$xcFy~IH}4<ZyuWwv{ptHC+g3Ev&ogC;$1|yKBE-V<z6ZBY?-rKG`)--O-6wiC`gZyK^X<9rDXBz~ze<s`pSAz@
*(sBL_$1TflS~>jfJXyRQlj_m<?YXJOgTj69@J->lJ0Zg8w`eGhkW(`R$18xw#wf3%(uUo@5;C}uMfGeOCT&FYiHZDd5^jCdt4zu
rj;>S-jiXFi2|=yY;{ET8vhUV;9Dos&iL;YH{<Ipm*=#9rAtI6TlqJ1A>iP||M?V5eE;nKYwuNlLhOrG{Y$R_E7kOaLF#OT2nCMW
YFbk^t%NPsudUolq`PR1G4oz7oRnskM>N<rYGZLFjdmcgq#K~WVM8Do4B3pbjjprC4YfA5DVp>U<jjh?U)DR&2*Le%P8-$K`%6~}
Tvx2p`-4iGs)ffx=b1016<x?QFb}T5q*C;fFH<6jPLb)>u@^LEe>p|n|7fJ~G#70KU)`9^+Dvgd1$)lbEnk{R7^PsFsIqyvaiKIa
F|E%MX}M{KLd2R`Q<vb-Od0|1(9>Qt0`Raj*yg}LJO@ULIVniB^R{7P$D@jHnZY)lAIo)q>Z1j@Wnyv-+(VGa8Y**ipBrbnPo!m!
n9AO4^PF?_yS$3LhLd%AoAQ&c>!48u6Y4zg7loxLw)D(0G#3%Ob6s~KQ3R`Fe`%yr$-s$*XylwQO-EUuOKg(v23A%Gwu7M?*_Yc>
kn2LRv=~v%9R1Gb!J%GW{gJ3#Q^JBBD=Atl0Y80~M&1E&ZtoiS)XKJL&UUU=4T<D~(p;p?hn^YP{8#7c+Sden+eln60PpRwK?DGh
+nU@uM~RsDWRy23NXg!jaNn-4s|)dS!og&M!RSzVeZZ?~M|0AzAVte7eqsaWuKSrl3YE-7n?ZUlQ$UVtF{PlJjzl>?-6*f4g1Olb
A-cY}E^=vXROnonMvCIWTVvma3OeBU)rt?(VaBz9WGM^K%BV!FenHtp)Loub$Q5;QWf*c39N93Q;07d4&wPqKRG$YyI@^iZIK#e0
Zx2&ZB<H$r$eFZ_bkYLIz%(|B+{x!>+c?9z;W&((Pt3%0Dq7xdhn~2YI_3-fnut@0iE@~Z6kSWliC6{p*A|bmJkl_0h-59tZXZb}
so3GADat5@$B8!H&eNbv;sQz^Lv%%{c;Xs-MMsKor$I^~XY^iy<9s8UENZx^dd5YxIV%+Yur$y5ja-9f^O*4u6dLkK@?Wl}iQPNm
lxc2!HMFBs6Bk935Niuz-Ah)dDjVTR7hg(QDB(WDlF1>-*xC7|@Ij2WAsXz|WE&}AFAO#~(}Cv@bC$pkaGj_l5aY^pP4hr^wxLWS
>Lb}%;R4enrV>Ewy`~?g`@1vivCGq^Y`#Ldoj+~`<wxk>?6JrPZI7Xt<{8FD&`st=45fYlx=Zt%f&IYi<gdFPz~8{hsM%%6XgXz#
Pmqaw>9Y4?*+a9>TE4LWbSr|8<6b-{V*k#E-0DJ6umer6I-#_Mb18npMQIXYYPO;kqKRNm_xV!GgELi10P7Lt*ogIM9%}}rlj%NP
iwMsuG$Q!7Zzm^7Eyr1b42<;9j8E0sjhzUr50hvsGE5%Bbo&lLbMJKwQ_RnmkF599pxY`onBu1eZ<J@iU$7cyo91iZ3Jsy0RQd{M
1Yt|kSE=1$W-guKMjd2LP3mtAYoCUz>P|PJfJjW`xi`}4mlrd9UFR?OKhwRj-cXHYl86^oEt8}GMa$>pi5HO0)T5hOI~q~KOsRnW
u{vfV3*Or-dTpfBU42t9Mr33`4EDk;nUsHAL??a)vc2dGhwU)6jYS^kjmTSTvQ34;&5KARKLLzb+cYKIX&XK_JUW!&qM775<!i&V
>7lLyq(H76Na-nP92@j~@mwyP?5o9RJ1EVNByv-61U=@RK2nxM8*G|OQV%Ye728_t@gNWT&B?8&B0$Ew_P<CC+IRWyuLHX<Tl_l9
l$V5AMtO=0KVF6Q98`Y$fQ=C^j#>L>IuZQUQ_|N<7OwkTUvh@XkRUh8IX1g?*a1>a#g{e~14MTGc)>=W*fH_n>JW`Zp|oImuj(2P
o<fS5cdF!<{dy;6mLKG<eegKJ9uir}P)}=+RH`v^>tI$cof>WwXT=;jO*;FItR2Lh%fA0Thn41V&*6_wg{njI{`GD|2!e7I;Mh`G
MGHpaew+EJQHAiS*>gE89mv*$7%hsze!^jWXpxY7sQkW}izd>SidW>$<zo;$nU2$^v1g>!bLme|q*Y~?ka3x;z-hPgvCTXH@Clfv
sb(E_PusW6pDPbk8ZMHF0*#sssih*OLuI7Q?X%449@d#^1cz|;fj~;@_`=1Nm3BZfYr>L!<IPQ*X3t-5491A>H~#80{Y<?A#Wp5G
psUW?o?>IVQ9TGnhfSBcDUcO8M8NtzbMEGZn+`MZ2cBr#^pTW6zgoVd1SW*BO`8!FzutZ7&bgdH0TS~aI+3zbOExBzKfi{lF(Ggd
3kD6eYB?WwCDP?CLtdWQ2j_4k>blKb#$Z{tq5d@hJ~H9M*T?%A({B}c1wfuP9VQsb@(qd9XSF2#(!mJIFbdxDl8TLvGX&5VvTaOX
+s<A+a{{;H-th&?dlZ5VMA?7>pPfHmxKhV$<N(zCg+6Q@ONjDvBJSEqB6ShS8<$g~7^NZY8+_!*%!Ded<CQ(Y`{4wFzXWg#vUw0p
I00UtvKkmDi0yD(%9@3K(r2`%5Y1yL<N`E1sw=SFngx`2OI1xLs+86`wiKGdvNxTl_BRH#8o)t>7+o~n7>{jaUBv2AVlj~(v}lmh
NF_lfkBCgC3vfN1%yc)7T(d}GBwf@tBz7CeKKwwDKMgJ)x~A=KF%nZ_7LgC8LeDZ>M<f#w+q*zZ{tA_Ckr2vGc|TMxE***u#+pXr
5KIWLHPIE2EnquQnYDWJLC3Cev`S~X+tVP;nXb6!?yXyKqtLy-()L&-a7&(YyzQGLat59$KE4?#p60=s!2MehUctCMwj0^t<q+w3
6o8$$HvX<|d*&n7GH%g<H$YN1e4gnzflNiuQ35>V3>AO5(jJp8CY|TWhdg4$;h-EfG1%1|-xqRSo-n<B%M*e;AuLar+w$iV7@0?7
`V*8;>C8>z^!jZeEsn~B(5-=>*;{`|8}fJzY4atY2{Q|HwBM-kVaYC_MY}i{q%pID0lQpP=>~CNOcCi>xtPE-k?mDinX|F#@rU2Q
4lHjVyIIItaw|!L?C}Qr-&H(iih1>50#F%~L3NQMX4Bk!`5gh9bZnRJXq7Swz|yE%UmcM;-$U2t5mOyhJsx4TumnC)t4z}=i^>Gk
rFo8Nc6z?uvK4R8Zpg?S$pn0m%g9dqD|~mL9gh;gB^J05lC6(o(>C>WU*McZE{VKgHr*SgFdnxO=jcY0BQDEH1D{{@^3MAqTLrWt
9%XOJLi@lmsC~}isl;|_tLP?_9uX11Q&PMe(`D*jpx-LXMkLnBuxP}^!20_SslfUUj4XU9?&oqJO2xw=8JFyZtxVN>uzVpC(F38w
vKg3*W=ybC94v1|QQxy;FxT*x+^DvAcqHSQ%~QFO0kAj~%3lQHL+E-|8cJcu%gTxs6xP?O(P$q_Be{y)62pO%q}W@sO`oCIKm?@G
Xc1SzbfWVj_tm7pueQ@vlpTtiAA6cr%9VKl?P?k+$W+t?d}{%6Tg6MAK|<f1JgA&qJ2mQbODCARN(!Y+tKOo|IxCnP0mQ*ct-87<
)(6mC*yY(c?^YxHIL3q0J!3<9JJ@X|D&3+@fQn1jA}W9op#U{chs}t9=tR1jYad`UJ#2RMt%x}LQpDO6_IfBTjRc9bE{?{MsiSsO
)$|eSEF!l3hD^ezbLZwq%O^DsbIGZGnI~m}*6-}|CGOday@gc0<2v=5mjgXh_Oe$yPWck9paFV(?6T+J*Q2K>#8X~6Onl_Clmi4^
_on&jQ7MHmH~y&}|5j}^EjO5}bvxneE%H(xp>a9NOh<BxJ-DlMEKW&_9@~))*JsI95=rpcJ7A6~a!jMt6=4VXDub5y9HG~g+=^-j
JYv!9uGiUipf;MfK_+Wm*~f|}8d}paGB=6u98snN0fNe%;v}WLKeUmnU7Y<qV)J#}%v4*$t``x5?Cs}Gtp@=Z>c&fCpE5;xxaGXs
<F5~#r|F;(+!RK{DJim(1@a;K?L^Hc!E*ZYN9I?A0`<k1jIQJck%@WBe>#2Shh(`EOh>y1IEdd_(cNdfYG+MTe5M~?7p8BwQ;`FT
`%WJU_w>1uf>@bL302i*mCj*RdRW->$#kGB;DGq(v&(#n?)G`u1^Ni(F^l02lT$by=`-BmDf?ql8awx;QnejSVvmvHIVMV$v<;L$
cernsR?~SSEo@ITB`Jhn!iBjVaiC2#9TY#>Clb2>v=PAljD@$#wa9+k%j+hAaJX$O)19llV^ekY@`$*N2Gnk8B&T7tal%aS&s$oY
_0mZCV+cNIR;mmzJoWN-Ke92HMQvyE0#k&t*sZO_ESWGb6lY~0VW0gu4y~>?*g3d>N}5pEc4}dqX!5`wH65p(v892Z_;tD@b~a!K
^$&9S>w_9w1ts@59zF;Gh0P?nWg>y?t0(Ptus3!$<Wm=t$0}J&o4om7<SJ;GeuV}O!_cplg>zVWzR}*=lD#?Q*jIzGr;QW=TE})v
G`2Kri@@GyfI0e0?4;X{!bZ#nnCm4oHgBY6qVO#4!7h=gE?A`qlBqykN?{(6hv<&;N4j+0S~j;-clnt=mA=8Qwrn=rd#pL7W$n7z
2T0ajM$U6vKaa*4CW&Xc4G@_&Z@eVsGq3v=+hn~<qJtcE4SZx3fVmY!?)diVv^3vLYtEF>xrMFR#(Ab;?6w0b=YYyPwa{yxYh`(v
N}=`^dj6|BJF`*C8kpGkTVt0QlXm(gMI{qSi(5TCnGor!zKQ6fcdtHIRH*=r)WuB7CD7a{Pz7R6_b9I~5!9JY5oGVCG*<z_WINJd
swi2ogR`|RPs|iZ2I;VEq%gEr>!P|U54>Nz8r%`<BgqERd|E&i$oVAdkC;`-F4n?m&BG#|{9SVR0qgN|IxGIeu_tezSP7USU5FR@
PWG!wgyzVsQ?vji{J3Qvo`Unisq;d%MYHK?nSew9ZM!sXbOg!zPT&F#;Cy4;Cv+s>dBmd&A{AP?2d_@t9x<Qoo6fL|2zL9>!Y36_
OW}Jt6p+GpoJ#$c+6n#+zz`*wHHW0F2;MA%Gb8Ox#U_ioLXgT{+K-mi#|ZFi)PO|=5lS#w5p3a`YU;Mg7vulUWL}#3O=$>}sHFEk
PPq@V%S7MZ0JrE(+H59dlT^R>q0_T^J98tL;59aq$vTaiHY00d@8ZMmmc{@<7XYCbt)rO?LhwGrYXoW~yVG%alK!|E2fZ|IByP*v
I5*`zYMLV=<k*^8G^_4+R~Mgd;q-gBa*;W$EYzkG8CyV)R^XeOx}uCgnlh2YuEVFrvZIDp6D6Y<Y9PT0=600W;cNq$Ul97syO#9F
b#q&kY#XY<4#$@z(_z|a_=<Ad#`!wlXF$Hn|6+{Eehy`8pV8I{6wjEv-5>Xr<XlW{{_w{k{~@E27_*4j<SlyISJbUg6k86;tU*pV
P=9xxn@u}Q51F&lBc6BYuBAVpl->Fyy7*q=mh$q>#x3`?Y`9P&?{*r;T!}M44d?p{=39`!=8|7J&t!x}?_|Qd;o9H!#x|{1_on1~
-hqd~RF>4KLY9i^0{*K5`QMPfRcs>_5ipXj=``I*n~JW*KPboKtfxo{apzSMnJG#{l8#JMjSoO?*Mepw0wocgV#b+^D8v3#HhLg;
v`bMAqy5gzj#pF-b}$A&_FAD>Qla9I!(T8)PB|#;{i<~!0HD!!pxhBCLN^Kr7WH4o%0N(+(+Y=;7_veyCk$5MC<NCR&&7Z!WV$H3
r+qf1+@Dcq-pSgM!_lk&PE1B#-eDVQ?WE8E5^m;aBQJSS<Y7GG4)!h_01pPVLK-)di)2a;3PT8rF1CDLCQYU^;1`}nI@!-7zhe&T
9SY_3%3={K5w1|U9ZffalmnH4y~otbk0dHDXzF3U+qxIgYH1czd$wvuAy3ZfBc7tOdf5zc6=TBeo$~Yu+YOMJ_r1wl0X(GbVDb%3
Q=o{7=rN+Dm!g6PD?67XpX!tpP4+E&MX>TfF8zDRin29up5l@18YaR^cx8~lYfmC#yo@j2q=-9&Kd=41D<qrf^Cpg4sPq}Y6Z$GR
km@?m#Aw;Evuq<})GnU%LOINe5n>w4^gyKZyOB!%4wS2$`q^gt5_wK?2Ebn%DKoM>w{4^(cd={M#%ZJEu!Bb4?#L3^ce0EYp#eqU
mKAWWm=2T<pKJqRE(5{DHWC=!aoYt#XhPx4w@8rXpdzyn-a6zd*~L(@Ip&r(CbQ72JI=KZvg2;sNKOK2%(ijPPCgcyO$pdZKF5de
4upP{JLctK(8O!g+`aX}O3UipfDmcsjv}K_tnDVR)A9bOYu^qM8KqwaN2!Ls>9{Z3Xt*Y<46m#l9EeIoMDEFdJ%af_dd%!Alw8Ps
g@i+`<>UNryG&R6akgycl)#z*)xF%DbiQmt&ZQOti9}BG^6nHZOkW>H>P9{96A3ARU@I~TK<JO<_7959MVk6`XVfWyM7kL*woUo-
0PORzjkJpk3{<ytn8yWfjI+~t4y6NE5&}=yY@Ie&#HGo<3XJ(I_aH%Y%50S79@GB`*AfsxYEj3QR-`Q%+oerc=iDddOK>*Ip^I?M
l;?<ER6;GLl+#C<d*#37c)Qi1Fv_diS)F`ne(iYq_uc;ureP$_*LuJ=#M4k6F^wY&&l(byBDkrOg`E0rVd)k)!Gq+0Pd(AYZFqj$
f!Ta+`dYhF1j?WQq3%+&Z(kL2Y8;0)X|NJB=_1q(i*B+F45aUD)6Czx50Tnnp}~1!4iqNWRnJdD36&UFs#3sW0<P&$9bUDf`%<!7
r9}0P(1RN^g>fM-n+@@9^Qr`HD%K4OOhH&v+i_k?$4HuxJHN_B5aK3P$$e$D)g_PG+vL1T)!{y(92~H2ei<@P-lF5U*CppOy=2O|
IAka;S2tN4G7JToC-Bv^cV~thPyjB;0(n5K4f{xjtYp}j_+9%#D(fz+Je-T@kb`1MJ7;z@&{k>qtds-|!ms_SZeiJO*k(&?fJuLW
;j%PN>qEX}eHbevW5?fq*_^}=oDR)r*i3XqI`C{c*<^ly280<LS7k}d0b;`p1<Bl=zAk|sLlC?xMUUL;yVGCFx}3JOmd}yuRL>5q
${mR}7~p2@I&XWYNM#H6y>lAGSNa3aVw3)m!J+db(kuu5golGX@K1H87Y+Tu-`aQo%n%suLC=r*`=u-JQYdV+Cnc)P%R80da4>)p
n(_9}J+V~=OrGgXIS=K@i?;|7L+dTNR%dM`G}&l#y#Q{(4j`(BYKx1N*?~h({$4qvv{NHBEidmub@IsFUvX$E#f&xB0v!riN;2|G
M^n;jPJ}d%;rpuleagWZ6fDJlI0X>=>6TbjWzqySnUxgO-k~t+_imdQqhY-@b94cXXO+R^+X2K$vQOot0co_u(l+BRskU(n3$b2P
SigCr+(!T1NKyLIIqGc(&sm4THdV98AX<$m*k)1R-LUcif?~g$JwbBrHNTYVp`?II^~$~g_*9Bmr!5!UC8e@EA8j#cC8tls5O20|
J_fblvT~kH5jzzJGigrUQh{CBmE-d6MeyuP2U^cXtA%yhhR$3l_GB(%PH9=c5e}OP_<7^KLVn&4jstC&_IX|kA&}%YGdmFwUIHIT
5SvTEHq2l`w2Ln@O=C|}(Bf^lOrLVQ^X%Y$dhCL+wJ6Y^xdn%{7DS3lv2frE=&)U;!<^K8mmVD@emPIGsc$*Eh+7=apf|KdyJcgR
Nzoa0ohy{dAyAvQt%gyYx0j%8-bef7LY`Rg)goaHiFx6xBXNgoZt*G_3ll#S-#ipbgixzeS;?UlzEI(6iF8uI#a5lg5w4Z0)06wk
dWMIaswHfFNTvL6K%avEZ*iBw-AMsFIZ~tSu5jCxN44oPN;}X%Whuz`n@&?MAG=k_3c;Fygm%Y+0JaIh^W~K*qdg$E1~~FYY88^U
ei@BMiY9<SS2eskQp3}Y_#eVSo!(HaO&h-hN6zmpR|A3FUb*NNlEn=M1n|b$&TKtwBfs=Oa`|n#C3d>M_*QxC#93QuY20jC-EJG{
a9ky2%?6^$HqjadBFHjC<O4~zVdf}^mOZSpyu`aOIwp-ARU(L2nax#+&Gz(H3eR&}54d!hhaK2>VI`WCMIeEyM4sJ44dO;QjSv;A
2Rz&6*lDER`u)U(+kF;5=h|-Uh`csrgCU{0XwiFr-@2rt)kgJ!mu4GOJDrV7o651DwviJ9UE0b~gMNUSy~gzdds5vTYJfu9n2xM8
mmK!x3(2!tad7BRJf|`}SV7R5qpGya_#&k-u`lvkG||?Y0TbL{fWVsp`K1Xo<K@AmYXJR3d#1>Fgo0<igh&{iUs(5ErnVet%|&7g
G7fZUnwnM?!L?pFL)FVfHY%+Lj7ha(TAF8}Os&dUqkOqN8TNc^XWFS=bQW(LH^%rwEnq+JeM1thal<udQ5|7InzNxfhD;6CJZem2
k1OqaSZD-r7A*T!x)5e2Ofb=2mq(CS2b2+J_cY2tfa|%6OznVGB51aB0&me6f6X%j&~gwrN=h(Nta&n9MTcCZU!$b{^}4wlZAzV}
&~sZu-_S$QD2mdBBEWVnc@_%omNO^q3iTYK363<+B7He28iB9-w3t!SNYYGEqQTl}<H*eyi-+g6D$YJ+rZRweFjZx#?y*p>8#*r+
kg0?s12fcN%5N-ckqFH;Gg?eB)<X--t1FKVwsG!*?ZAOo%8i(=$%KbpPRaUB>+w-t*%?F}f`oR#5n%G?!{JL?ziUqD0cjeIG?ivT
gK!x{ucq0|axaHST4SgR{jMqVqkJTdzhGPqKX1nFCA#n&f2%woseiWrt+>&mr#D6fgmbU+mh7Fkq;vPms;VRH9w`+4-=cPa55pD1
bBP<W^b|v^*hZQ>6lOqaf_C*5W*oLcs6}!>L=*}lE^lWf{-M%H!%Y2_8NC%P-e_6Uh4;?-Y(i<&XLrg%(}frd?X#(P$?3DL3%Zd*
>bY%0pnPS}!-g*hb|Z%rIAW3ixpv6Z;RY)4(t(}nC4Zk>OwjI^Ya{z4bziL=*n@lmr~iikViAss+48ieG+L>ZxL{ctH`_>8E4W|j
`f5KzfeUjs1PLy!Ib0r12)bz%`Q&>F%0IifETzMgUgba``SX&S;n11H+E#RJGs?8;9PBv4;cbK^)$c>OGMZ&0!g&u22=k)EI4_cE
X-Z5brWCr_qz|`^B7esL!cW-*I0=p<qn)=pIE=T6GxwygVlh#DEBUPyuUJXdvMM>J(xDs%cdl&=uv+{U5f=ICL^UbycZXt71nr17
hR<;DuALBk_73KV`!Pi91{y=;>Zrk0D0+Z5Y~AZ^mbL*gv@=6>53*|!3aq)qeab#O(kgH>3taiiY8%<}bz4m~lX6l;DLa-MZ-p@h
c6%-1dRiw(qeP%~-&;Kp-#^Tv%>)j0D*Cb=RT9hX00XRjKqb`6!~J;kM#6R9zecRFI<+q&#&o=zP-dQ8$R%;N)hp17*~isbWsRyc
lt+ANq@xk^Q*xqT9Y1gB$Y9AA40q*GRjvJeV{*Y?D^^{j)E*U>S3W`fvwXnDtI7INn{huaXqT;IM!Z&*>gCo<vHa3$CjWR-gU||x
edHxC_dUwwg+QkGmo`ngIUdD=vazEw!nXYYYV;d%-mvjESaB&L!^?vY7iI|@?3V&x9BF-eWh(P^8aa<<Gd6o;$I`9PDE7+8D!Rq-
X$)n6gn@nYBV7KBEQ>|FF;4_a>%g4{8I4*&QG=|QqokScDj4|<eq01J$`1Ol99s-MppxGt(8(AQ2?;5=cQ|b~&VapA8Oo~$X4fOF
c{<WmEe^YGfgfsf{L%i=j?unuk!H|4>X$a0jJv$GOlnv=kNZ`VZKq0|(&%(9od^%@s<Jk8hXTbqDb)D`CA{wW)=Yu@0CH2GqYV<)
?&9XCmP5?Wy)HW$gi^eoo{3pG5IYOUB*DE%fN%dw(n$Bnr%qVjjR9OkT;3}&wn=0OgU0rkItXekCMXE(s6u05d0?7&4naZyZ0F<d
Zr|p9dv@hAQXm)4t~6GQHF>~s@HIyUzQ6J*B#q5f#x7S9$wsx&;pV6y#G{BXSepkOC^o0r!Ehf2TQ@1)rUe0zN)&=O^NN&?(?3zG
#bdRdrY^G~^U9c5XeRh%<vaY?geauzHX*R$vj!qN;PfG*B{q!{qiSCV)o1JH=-ALpD786)A5_TCeRCbM)^w_Ap^vOx9-edYBd=^(
{KTK2ETT?#%MuEbZj@8tQFve*sS*j|N*NB!`~<2$ysS?Mjm(E~uZ@)U8ZHr{&xsfH5RNt;3@<EwjUDTd*h9NG(9imHC)$I4a4nXP
tKwNYX9Kur3#OZ+44o|Y!{mxx?oy+1x47<V_`2J);`MIpgf`ylV>*Ia$I%f=aHzJa7&;BeCjI1&2xx~idX@?5jX9kn0~%!kes6MI
Y|1^{2l9EYm!eiS(bXxZ&DxLCTM6uj@sz4TK7bhM>z!30z_R{(ERG9`N4)Fa6%Qkt3D5xm1LLOYkIv*ZiMgu2rBAL%nebQAr>6eY
8>d|OeWOGv6EWSLe)kYTh8tYTZa9Jty!PHzG(03hWz%gg_<LYjYuBM-A7}r2*6|mDLv{7<bw%Y&`M$r_Rk9>b<E|pJE?Kvtn3gV9
%_X&RTze%1kPgHR61H8DMNCd`b5zb$6&X~_)&^uydoFGypMcA-tW-*5`96a-&SU75T&Sy)F$b*|Ky)FH%~TSDf|bHVQ$0rf9MZUH
(LcZemw{!F!Ow<W_vOab2zC%RO3ef}W<_YH#!UlRDOo3=bf1R_{DgAOiOwc!A1b34k-1fSa@#jzkAzr&fkzE`+3%4f#sxca*}FeR
?n8iWy3dHqnbsjCcZFD7sK*9fmc5=iFqGH>*3;hg_;b;^C==zmOQn5=f9I}&b{Vo<m^m|dkl&aNCd>bRy>Xy~?+X2yt|&&%K6bBL
6`wq%lcIC?h=H=}mavkffbcDIfwRp?kmgy<;q7&F#G@u(EYxf7q8ByJ{j|D3odtNM^!3<iAKRnW(2+zA?!h|ArTfe+Szco%0>YPo
6bps!>9G>X-x?h-jm<?<u*DGd_&NOzvml=lf3E;+Go_6WU1}!#I@2)p_Re$gBaq(o6^@Fh*zH@VoBY&jKY0ax^t~e`K_2bLaR7p*
Y@br6>Z<Qqkn|B#)YP9U8x8+97tGOqKQJoVe>XWl9}lc>oW)-sFH6zhaOUXX$;-FRB~0HG@l8LzWmYy`r=END{iYxvWYzK7NU!Y2
8r1R*t8{1t#4fWog-bneXXRvL3`bpbV@r)~CLeO?QH;Fxv9$H?b=pl$H6-nRb%*br*-|w-GmYng>U-CnX#``l=oebAyzfyVn|J4L
w{NQ`Z>9d;CQLK{o-Orn)o8mIq=TWwAo?JyT^3<`wg&QXkH2)Gr{WX%#&zM;&%!Zz3(|S2JT~L7dEy>0FYn2EmzRuqlg+-tw9;e=
OCt(X`trDrzBI0?3lL78oa`G-(LxI_bwJ(IeXS`^)aiXq)%)LBI;s_AbHll+ACaK}71$<cv3atJLB*qYwg-nN{D09w&v_)h$0ozn
NcZ3u3kCLIO6$?-8SEb@q`PgTd|=cj!D4@XqliCWU&BWb{(TpC@URCXU_Aj18rkAKQ~PShB`o(_)^zl?BOxSw-=4C%m#e0>hH6CH
I5!alcK5q_*D*A&peV;yVe+1HwY`B4Ln9*}SZ&H11^~NW0#|z-;1uw{NBTY7R1NbP?tL8($~Lg$!RUwoINV`|On=;dCiO12pC<VC
a0dfptHa&V6s}|eCZsEs$XGkT2U3QQcE3Uwfz@tjid_REZC5l{2;t3KPC;~~H?#8_j1$ZnxjrznM>lfQ2Bj#d4|(5?eX$6Aobi|E
j5&5$W|bk?kiVt8r}CI?24C)stFR;<g0l=|XPnM5R^3EY@qHsd#2ZDzlkttwl8;FJJn0uKXNr&Z2vdA)`@Pdoa%N~r3E%6M?=63Q
@7$2kad0#x`>mDqo-@9B4GsZ&EXBrWSX1G@x)gnK$!sO$nVP#$T0`F{pkY}Qd{1~MP&w>+N=#8Ht<5$Tv!38l*o<=oHR7LF+}CkT
>9-OMfAbv2v2Og6?7B%r$Fs+Tg?SzyWqH$MfBzi&n;qX&I6EojnDe@-(_gckXqKTf#3$KVPBhB}jV}DDZ~8Pd0aeikbbYDb=$W1~
9aztNb)r{Kc*YS=`lq=~WLo8Ho5+BCKJJtIK%MPyJ{`)HP=*5GtX!k41bOnkCZ9_Owlw`$6{&P6j<eH84d1xaKGNCu`{TfMR(5Y~
;n{_RTfDrU5)f<&VUv54mqNAg-8Pe}!6r~5+0dj_ZP9`dphKms;Ev{MQVOL@*vwY5PiOz+*VAMA7f(;_Up_sRKL=*x<fzqiCC&Wa
)rts0IZ<xZp8vbZk!*tu**040zvW7%pHR#Q(I=21qCPl4M=Q>zN1mH+@9+1M6k=`BjR?EMsm)iCM&-?5a3u^dVyXsWmo8IJKsCMl
^7i>+<{Gu?%a9ZULA0-p{MFs_|NS+Izea)S?Ti-#L9|}IS-D?rqnWRzG28iC8qIvAtnTz%mPxD;Np+fcmP7t}pM}2B-nFiIZ;Q1;
WD9-=8081P)0~9l19@5v>pN8Ux3dxT>Z~5`*3IS_XQY+18b8$<KTRPT)<r|95MM50Pmm(|e9=13yN~Xn|EA7?!Yk%zlZHGSM4-B3
^Dwxu9{sfeUtP4wN7TY1T2S!udgQQvfJ84R$mX~GR5Gu;`<}?Zi&7H6A9&05YrdUXCP0j~`|w8vt+4#xvCFLwZ{Khp7APx%BBcRE
Qyts@v~QN_(rDsLOCu$_DVLW;RY3=4!a(LNl6N1UUtmI%gQ7mW86*JYJ)5+kHj+PpAUS9jfXsm0nDZ8Sr75XkNO)5P!ulqpLwN_v
YTL*${AC1^No7OD$5P)YU5G>_Emu<pfF^OO4Q+BTr4waf*JB+DW>(3_(8<dq3QN-nCc|Pd?9io>wiRAzi%WSdmb+1w67<oA&-M0h
#LkBNQluvhq7DVD{eX~O$j>=H1?S6@a2{w~7v&ZRJ<FD=qmi&{EI*kvMqbV^%HUHAODBpT*F_1EMjG)WK5w~`(<=Wk%b!Hq{j`Nl
`6}{;7FJwt%Cu=HNq?T|j=dwh$u_{Yv~ST2r?BSn*5xb+oC|u&oo?h8zvZu>C0QIlfxz4bZ>{dg`$mCX5fd8U@xh6deRvrL7&Nco
l0_+7+I{Vcq$oXNL=aEzf8=J$E9G+Hrq%@Scg#vLXF(u+#^0adPBvYp;&R>V$WXebzwGiMil-~D!=C9J?CdG_^NC+8EJvg?8frXc
Xo*0~15u2x;3D&n&dO=jh(I*domU3S<3iN9<qiH#(|OwZ#tI5$dQ7igfF8SFCoJ6v=m7!$yU011?C=w1ln3VJmq0bhY6W2GVkq1v
K;f)#EfW9;vh%i&p;<;joO8Ch`~h-`CMG!t({ojYJef|FR79gp1ga7S+2^8xg~Dzg5y{Oq8VFBrs#HSpl(1e&Bvea)7gTDLVGSyH
d!@I$WHs2UJ^R%nkmAHhh+K-QlAqG+0TASL#~Q7nMkWk#3KAsB<x$RM1ysf(LJDB?ZqS{{I+uwSz5UvkVXu_g_QcZ;I@Jjy?svm5
0LRuDp&W@7umf=4es`hFXt9e#QLAzwK~yVVvsk}pl_MZ&vewv=7QnKF#*`1By!w!3n`hb3(rrJiF$f+Ckq~LV_YWZm+~;}_`h^rk
E{)q?q#$T)f1i?#pzXetFUlL$lU&xg2Yv#uei63vcJL{06h#MVX-vimmV?3reZ>$1)c{}79zBhVMZv%XGZs-9h*9Ma?*@feXYkp_
YB|56a|`E(M$SOJ;&$Mw$r8FS&290MMZ!Td>UyLIl|`CClZj^|Mk@k58r>=qH}<)qQA4c(uCwfp%#1K#QCj9Vx{Z0K^V-Oke_a|g
Pksvat&Ctb6(kLY$CvFJR!Z;&t;SM<BN;K+Q8gvJ&+-^k!h1aXqZWvdVw`R3#Ci^mB!m8dMp`;bVrr<Tqywupzh2avB(~*6eK1(T
Ya=Uezur9B((L_8yM1<Se^IqaW8$P*nFoujfDWYMSr{>CB=f?5HyYc`?gxT;bM}RZM|-`Y^)W3sEI-Q*(eU>TnT-<=+%~aZI&iWi
WP%crtrO4|neZR~`G5T9fBxtH15Gl`qW
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
    sys.exit(patch.main(sys.argv[1:], bundle, prog='syncrackd_firstrec.py'))
