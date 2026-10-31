"""The file protocol the phone speaks (tools/rpc.py), checked against the unit's own parser."""
import re
import struct
import zlib

import pytest

from tools import mainmap as mm
from tools import rpc

SKIP = {0x4010394c, 0x4016f43a, 0x4016dfac}  # allocate, and the shared pointer's two helpers


@pytest.fixture(scope="module")
def sec3(official):
    assert official.version == "1.42"
    return official.section(3)


def long_at(img, a):
    return struct.unpack(">I", img[mm.off(a):mm.off(a) + 4])[0]


def case_of(img, ident):
    """The parser's case for a message id (the table is indexed by id - 1)."""
    i = (ident - 1) & 0xFF
    rel = struct.unpack(">h", img[mm.off(mm.RPC_TABLE) + 2 * i:mm.off(mm.RPC_TABLE) + 2 * i + 2])[0]
    return mm.RPC_TABLE + rel


@pytest.fixture(scope="module")
def classes(sec3):
    """vtable + 8 -> class name, from the RTTI names in the section."""
    out = {}
    for m in re.finditer(rb"N8elektron\d+(MidiRpc\w+?)E\x00", sec3):
        name = m.group(1).decode()[len("MidiRpc"):]
        for t in re.finditer(re.escape(struct.pack(">I", mm.BASE + m.start())), sec3):
            info = mm.BASE + t.start() - 4
            for v in re.finditer(re.escape(struct.pack(">I", info)), sec3):
                out[mm.BASE + v.start() - 4 + 8] = name
    return out


def built_by(img, classes, a, depth=0):
    """The last class whose vtable a routine stores, following its calls two deep."""
    found = []
    for k in range(a, a + 0x200, 2):
        op = img[mm.off(k):mm.off(k) + 2]
        if op == b"\x4e\x75" or (depth == 0 and op == b"\x60\x00"):
            break
        w = long_at(img, k + 2)
        if w in classes and classes[w] != "Message":
            found.append(classes[w])
        if op == b"\x4e\xb9" and w not in SKIP and depth < 2:
            found += built_by(img, classes, w, depth + 1)
    return found


def test_the_parser_reads_ids_through_a_table(sec3):
    assert mm.BASE == 0x40000400
    at = mm.off(mm.RPC_PARSE + 0x26)
    assert sec3[at:at + 12] == bytes.fromhex("53807180 0c80000000de 6200")  # subql #1 ; mvzb ; cmpil #222 ; bhi


@pytest.mark.parametrize("ident,name", [
    (rpc.PING, "PingRequest"),
    (rpc.SOFTWARE_VERSION, "SoftwareVersionRequest"),
    (rpc.DEVICE_UID, "DeviceUIDRequest"),
    (rpc.DATA_LIST, "DataListRequest"),
    (rpc.DATA_READ_OPEN, "DataReadOpenRequest"),
    (rpc.DATA_READ_PARTIAL, "DataReadPartialRequest"),
    (rpc.DATA_READ_CLOSE, "DataReadCloseRequest"),
    (rpc.DATA_WRITE_OPEN, "DataWriteOpenRequest"),
    (rpc.DATA_WRITE_PARTIAL, "DataWritePartialRequest"),
    (rpc.DATA_WRITE_CLOSE, "DataWriteCloseRequest"),
    (rpc.DATA_MOVE, "DataMoveRequest"),
    (rpc.DATA_COPY, "DataCopyRequest"),
    (rpc.DATA_CLEAR, "DataClearRequest"),
    (rpc.DATA_SWAP, "DataSwapRequest"),
    (rpc.DATA_RENAME, "DataRenameRequest"),
])
def test_each_id_is_the_request_the_unit_builds_for_it(sec3, classes, ident, name):
    case = case_of(sec3, ident)
    assert case != mm.RPC_NONE
    assert name in built_by(sec3, classes, case)
    assert case_of(sec3, ident | 0x80) != mm.RPC_NONE  # and the unit knows the response


def test_an_id_past_the_unit_s_last_goes_nowhere(sec3):
    assert all(case_of(sec3, i) == mm.RPC_NONE for i in (0x60, 0x6f, 0x7f))


def test_the_data_file_magics_are_the_unit_s(sec3):
    assert sec3[mm.off(mm.RPC_FILE_MAGIC_AT):mm.off(mm.RPC_FILE_MAGIC_AT) + 6] == b"\x20\x3c" + struct.pack(">I", rpc.FILE_MAGIC)
    assert sec3[mm.off(mm.RPC_FILE_TAIL_AT):mm.off(mm.RPC_FILE_TAIL_AT) + 6] == b"\x20\x7c" + struct.pack(">I", rpc.FILE_TAIL)


def test_pack7_round_trips_and_stays_7_bit():
    data = bytes(range(256)) + b"\xff" * 13
    p = rpc.pack7(data)
    assert all(b < 0x80 for b in p)
    assert len(p) == len(data) + -(-len(data) // 7)
    assert rpc.unpack7(p) == data


def test_a_frame_and_its_parse():
    raw = rpc.frame(0x1234, *rpc.read_partial(7, 3))
    assert raw[:6] == rpc.HEADER and raw[-1] == rpc.END
    seq, req, cmd, status, msg = rpc.parse(raw)
    assert (seq, req, cmd) == (0x1234, 0, rpc.DATA_READ_PARTIAL)
    assert msg[5:] == struct.pack(">II", 7, 3)


def test_a_ping_frame_is_these_bytes():
    assert rpc.frame(1, *rpc.ping()).hex() == "f000203c1000" + "000001000001" + "f7"  # the high bits, then 0 1 0 0 1


def test_a_write_block_carries_its_crc():
    chunk = bytes(range(200))
    cmd, args = rpc.write_partial(5, 2, chunk)
    job, n, crc, size = struct.unpack(">IIII", args[:16])
    assert (cmd, job, n, size, crc) == (rpc.DATA_WRITE_PARTIAL, 5, 2, 200, zlib.crc32(chunk, 0xFFFFFFFF))
    assert args[16:] == chunk


def test_a_sample_file_holds_the_unit_s_slot_format():
    frames = [0, 1, -1, 32767, -32768] * 10
    blob = rpc.sample_file(frames, "KICK", 3)
    top = struct.calcsize(rpc.FILE_HEADER)
    assert top == 31
    slot = blob[top:top + rpc.SAMPLE_HEADER]
    assert rpc.SAMPLE_HEADER == mm.SAMPLE_HEADER
    assert slot[:4] == b"SAMP"
    assert struct.unpack(">I", slot[8:12])[0] == len(frames)  # frames at + 8, as the store reads
    assert slot[12:16] == b"KICK"  # name at + 12
    assert len(blob) == top + mm.SAMPLE_HEADER + 2 * len(frames) + 12
    payload = mm.SAMPLE_HEADER + 2 * len(frames)
    assert struct.unpack(">III", blob[-12:]) == (zlib.crc32(blob[top:-12], 0xFFFFFFFF), payload, rpc.FILE_TAIL)
    assert rpc.sample_of_file(blob) == ("KICK", frames)


def test_a_damaged_sample_file_is_refused():
    blob = bytearray(rpc.sample_file([1, 2, 3], "X", 1))
    blob[31 + 64] ^= 1
    with pytest.raises(ValueError):
        rpc.sample_of_file(bytes(blob))


def test_a_list_response_reads_entries():
    entry = b"1\0" + bytes((0, 2)) + struct.pack(">iI", 1, 4096) + b"\0\0\1\0"
    folder = b"A\0" + bytes((1, 1)) + struct.pack(">I", 3)
    msg = bytes(rpc.LIST_START) + entry + folder
    assert rpc.list_entries(msg) == [("1", False, 1, 4096), ("A", True, -1, 0)]
