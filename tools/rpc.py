"""The unit's file protocol over USB MIDI SysEx, as bytes only. Nothing here opens a port.

The reference the phone app is checked against (its golden frames come from here). Facts and how
each was confirmed: docs/FINDINGS.md, "The file protocol, for the phone". Written from the facts,
not from any source: Elektroid (GPL) was read, not copied.

A frame is HEADER, the message packed 7 bits to a byte, 0xf7. A message is the sender's sequence
number (2 bytes), 2 bytes (0 in a request; in a response the request's sequence number), the
command, then its arguments. A response's command is the request's | 0x80, then a status byte
(1 is good). Every number is big-endian.
"""
import struct
import zlib

HEADER = bytes((0xF0, 0x00, 0x20, 0x3C, 0x10, 0x00))
END = 0xF7

# Request ids, as the parser's jump table at mainmap.RPC_SWITCH reads them (tests/test_rpc.py).
PING = 0x01
SOFTWARE_VERSION = 0x02
DEVICE_UID = 0x03
STORAGE_SPACE = 0x05
DATA_LIST = 0x53
DATA_READ_OPEN = 0x54
DATA_READ_PARTIAL = 0x55
DATA_READ_CLOSE = 0x56
DATA_WRITE_OPEN = 0x57
DATA_WRITE_PARTIAL = 0x58
DATA_WRITE_CLOSE = 0x59
DATA_MOVE = 0x5A
DATA_COPY = 0x5B
DATA_CLEAR = 0x5C
DATA_SWAP = 0x5D
DATA_RENAME = 0x5E

BLOCK = 0x2000         # bytes a partial read or write asks for
LIST_START = 18        # a list response's first entry, in the unpacked message

# A data file (a project, a sound, a sample) is a header, its payload and a footer.
FILE_MAGIC = 0xAC11D303     # in the unit's code: mainmap.RPC_FILE_MAGIC_AT
FILE_TAIL = 0xAAA1DAAA      # mainmap.RPC_FILE_TAIL_AT
FILE_HEADER = ">IBHHIIiiIBB"    # magic, version 2, family, device, os, type, version, index, size, packed, footer
FILE_FOOTER = ">III"            # crc() of the payload, the payload's size, FILE_TAIL (read off the unit)
SYNTAKT_FAMILY, SYNTAKT_DEVICE = 8, 13
TYPE_SAMPLE = 8
SAMPLE_HEADER = 64          # 'SAMP', version, 3 pad, frames, name of 16, 36 reserved: mainmap.SAMPLE_HEADER


def crc(data):
    """zlib's crc32 begun at 0xffffffff: a file's footer and each written block (read off the unit 2026-10-14)."""
    return zlib.crc32(data, 0xFFFFFFFF)


def pack7(data):
    """8-bit bytes to 7-bit: each 7 bytes become their 7 high bits (first byte's the highest), then the 7 low parts."""
    out = bytearray()
    for i in range(0, len(data), 7):
        chunk = data[i:i + 7]
        hi = 0
        for k, b in enumerate(chunk):
            hi |= (b >> 7) << (6 - k)
        out.append(hi)
        out.extend(b & 0x7F for b in chunk)
    return bytes(out)


def unpack7(data):
    out = bytearray()
    for i in range(0, len(data), 8):
        hi, low = data[i], data[i + 1:i + 8]
        out.extend(b | (((hi >> (6 - k)) & 1) << 7) for k, b in enumerate(low))
    return bytes(out)


def frame(seq, cmd, args=b""):
    msg = struct.pack(">HHB", seq & 0xFFFF, 0, cmd) + bytes(args)
    return HEADER + pack7(msg) + bytes((END,))


def parse(raw):
    """A frame from the unit -> (its seq, the request's seq, command, status, the message)."""
    if raw[:len(HEADER)] != HEADER or raw[-1] != END:
        raise ValueError("not a frame of this protocol")
    msg = unpack7(raw[len(HEADER):-1])
    seq, req, cmd = struct.unpack(">HHB", msg[:5])
    return seq, req, cmd, msg[5] if len(msg) > 5 else None, msg


def cstr(s):
    return s.encode("cp1252") + b"\0"


def u32(*v):
    return struct.pack(">%dI" % len(v), *v)


# Requests, as (command, arguments).
def ping():
    return PING, b""


def data_list(path, start=0, end=0, all_=1):
    return DATA_LIST, cstr(path) + struct.pack(">iiB", start, end, all_)


def read_open(path, packed):
    """packed: 1 asks for a project or sound as the unit packs it; samples are read unpacked (0)."""
    return DATA_READ_OPEN, cstr(path) + u32(BLOCK) + bytes((packed,))


def read_partial(job, n):
    return DATA_READ_PARTIAL, u32(job, n)


def read_close(job):
    return DATA_READ_CLOSE, u32(job)


def write_open(path, size):
    return DATA_WRITE_OPEN, u32(size) + cstr(path)


def write_partial(job, n, chunk):
    """A data file's last 12 bytes (its footer) go in a block of their own, or the close is refused."""
    return DATA_WRITE_PARTIAL, u32(job, n, crc(chunk), len(chunk)) + bytes(chunk)


def write_close(job, size):
    return DATA_WRITE_CLOSE, u32(job, size)


# Responses: the fields after the status byte.
def job_of(msg):
    return struct.unpack(">I", msg[6:10])[0]


def read_part(msg):
    """A partial read's response -> (job, n, progress in thousandths, last, crc, data)."""
    job, n, status = struct.unpack(">III", msg[6:18])
    last = msg[18]
    crc, size = struct.unpack(">II", msg[19:27])
    return job, n, status, last, crc, msg[27:27 + size]


def list_entries(msg):
    """A list response -> [(name, is_dir, id, size)]."""
    out, pos = [], LIST_START
    while pos < len(msg):
        end = msg.index(0, pos)
        name = msg[pos:end].decode("cp1252")
        children, kind = msg[end + 1], msg[end + 2]
        pos = end + 3
        if kind == 1:
            out.append((name, True, -1, 0))
            pos += 4
        else:
            ident, size = struct.unpack(">iI", msg[pos:pos + 8])
            out.append((name, bool(children), -1 if children else ident, size))
            pos += 12
    return out


def sample_file(frames, name, slot, os_version=0x30303937):     # "0097", as the unit on 1.42 writes it
    """A slot's sample (int16 mono, 48 kHz) as the data file /samples/<slot> takes."""
    pcm = struct.pack(">%dh" % len(frames), *frames)
    head = struct.pack(">4sB3xI16s36x", b"SAMP", 0, len(frames), name.encode("cp1252")[:16])
    payload = head + pcm
    top = struct.pack(FILE_HEADER, FILE_MAGIC, 2, SYNTAKT_FAMILY, SYNTAKT_DEVICE, os_version,
                      TYPE_SAMPLE, -1, slot, len(payload), 0, struct.calcsize(FILE_FOOTER))
    foot = struct.pack(FILE_FOOTER, crc(payload), len(payload), FILE_TAIL)
    return top + payload + foot


def sample_of_file(blob):
    """A data file from /samples/<slot> -> (name, frames). Checks both magics and the crc."""
    h = struct.unpack(FILE_HEADER, blob[:struct.calcsize(FILE_HEADER)])
    if h[0] != FILE_MAGIC:
        raise ValueError("no file header")
    body = blob[struct.calcsize(FILE_HEADER):]
    payload, foot = body[:h[8]], body[h[8]:h[8] + struct.calcsize(FILE_FOOTER)]
    sum_, _, tail = struct.unpack(FILE_FOOTER, foot)
    if tail != FILE_TAIL or sum_ != crc(payload):
        raise ValueError("bad footer")
    if payload[:4] != b"SAMP":
        raise ValueError("not a sample")
    n = struct.unpack(">I", payload[8:12])[0]
    name = payload[12:28].split(b"\0")[0].decode("cp1252")
    return name, list(struct.unpack(">%dh" % n, payload[SAMPLE_HEADER:SAMPLE_HEADER + 2 * n]))
