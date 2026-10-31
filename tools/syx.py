"""Elektron OS-update SysEx transport, as used by the Syntakt.

File = start marker, N data packets, end marker. Nothing else.

Marker (16 bytes): F0 00 20 3C <product> 00 7F <01 start | 02 end>
<base> <start seq, 3x7 bit> <packet count, 3x7 bit> F7
Packet (128 bytes): F0 00 20 3C <product> 00 7E <seq, 3x7 bit>
<116 bytes 8-in-7> <checksum> F7

Each packet carries 101 plain bytes. The checksum covers bytes 7..125. Layout and checksum follow
syntakt-firmware-workbench (MIT) and were confirmed against the official 1.42 file, see docs/FINDINGS.md.
"""
from dataclasses import dataclass

ELEKTRON = b"\x00\x20\x3c"
PRODUCT_SYNTAKT = 0x16
MSG_LEN = 128
MARKER_LEN = 16
PACKED_OFF, PACKED_END = 10, 126
PLAIN_PER_MSG = 101
CK_FROM, CK_OFF = 7, 126


@dataclass(frozen=True)
class Transport:
    product: int
    base: int  # checksum seed, from the start marker
    start_seq: int
    count: int


def _u21(b):
    return (b[0] << 14) | (b[1] << 7) | b[2]


def _p21(v):
    return bytes(((v >> 14) & 0x7F, (v >> 7) & 0x7F, v & 0x7F))


def unpack7(p):
    out = bytearray()
    for i in range(0, len(p), 8):
        hi = p[i]
        for k, v in enumerate(p[i + 1:i + 8]):
            out.append(((hi << (k + 1)) & 0x80) | v)
    return bytes(out)


def pack7(b):
    out = bytearray()
    for i in range(0, len(b), 7):
        chunk = b[i:i + 7]
        hi = 0
        for k, v in enumerate(chunk):
            hi |= (v >> 7) << (6 - k)
        out.append(hi)
        out.extend(v & 0x7F for v in chunk)
    return bytes(out)


def checksum(msg, base):
    acc = 0
    for i in range(CK_OFF - CK_FROM):
        acc += msg[CK_FROM + i] ^ ((base + i) & 0xFF)
    return (base + acc) & 0x7F


def _split(raw):
    msgs, i = [], 0
    while i < len(raw):
        if raw[i] != 0xF0:
            raise ValueError("byte %d: expected F0" % i)
        e = raw.find(0xF7, i)
        if e < 0:
            raise ValueError("unterminated SysEx message")
        msgs.append(raw[i:e + 1])
        i = e + 1
    return msgs


def decode(raw):
    """File bytes -> (plain stream, Transport). Verifies every packet."""
    msgs = _split(raw)
    if len(msgs) < 3:
        raise ValueError("too few SysEx messages")
    head, tail, data = msgs[0], msgs[-1], msgs[1:-1]
    for m, kind in ((head, 1), (tail, 2)):
        if len(m) != MARKER_LEN or m[1:4] != ELEKTRON or m[5:8] != bytes((0, 0x7F, kind)):
            raise ValueError("bad start/end marker")
    if head[8:15] != tail[8:15] or head[4] != tail[4]:
        raise ValueError("start and end markers disagree")
    t = Transport(product=head[4], base=head[8], start_seq=_u21(head[9:12]), count=_u21(head[12:15]))
    if t.count != len(data):
        raise ValueError("marker declares %d packets, found %d" % (t.count, len(data)))
    pre = b"\xf0" + ELEKTRON + bytes((t.product, 0x00, 0x7E))
    body = bytearray()
    for n, m in enumerate(data):
        if len(m) != MSG_LEN or m[:7] != pre:
            raise ValueError("packet %d: bad framing" % n)
        if _u21(m[7:10]) != t.start_seq + n:
            raise ValueError("packet %d: sequence break" % n)
        if m[CK_OFF] != checksum(m, t.base):
            raise ValueError("packet %d: checksum mismatch" % n)
        body += unpack7(m[PACKED_OFF:PACKED_END])
    return bytes(body), t


def encode(stream, t):
    """Inverse of decode. len(stream) must be a whole number of packets."""
    if len(stream) % PLAIN_PER_MSG:
        raise ValueError("stream length must be a multiple of %d" % PLAIN_PER_MSG)
    count = len(stream) // PLAIN_PER_MSG
    pre = b"\xf0" + ELEKTRON + bytes((t.product, 0x00))
    info = bytes((t.base,)) + _p21(t.start_seq) + _p21(count)
    out = bytearray(pre + b"\x7f\x01" + info + b"\xf7")
    for n in range(count):
        m = bytearray(pre + b"\x7e" + _p21(t.start_seq + n))
        m += pack7(stream[n * PLAIN_PER_MSG:(n + 1) * PLAIN_PER_MSG])
        m.append(0)
        m.append(0xF7)
        m[CK_OFF] = checksum(m, t.base)
        out += m
    out += pre + b"\x7f\x02" + info + b"\xf7"
    return bytes(out)
