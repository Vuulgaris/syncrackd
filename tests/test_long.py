"""The long image: the tlsolo image with patterns 1..64 long and 65..128 their tails.


Every cue of a pattern sets stock's play queue
(mm.QUEUE_SET, thirteen calls); engine/longpat.c sets it with stock's own routine and then puts each head's tail after
it with the head's kit. The UI's kit object follows the playing pattern's number (mm.KIT_FOLLOW_CALL): ours gives the
head's while a tail plays with the head's kit. Stock's queue routine runs here; the sequencer's hop and the main task's
message that re-points the UI's kit do not: only the unit can show that the hop is clean and a knob turn in the second
half is heard.
"""
import shutil

import pytest

from unicorn.m68k_const import UC_M68K_REG_SR

from emu.machine import Machine
from tools import build_main
from tools import mainmap as mm
from tools import fw

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

PATTERNS, PATTERN_DATA, NUMBER = 0x40a39b34, 136076, 136072
KITS, KIT = 0x41ad6134, 5656
QUEUE, COUNT, INDEX = 0x43bcc3bc, 0x43bcc3b8, 0x43bcc3b4
PLAYING, PLAYING_KIT, RUNNING, HANDOFF = 0x43bd8430, 0x43bd843c, 0x43bd83bc, 0x43bd8520
LIST = 0x43a00000


def data(n):
    return PATTERNS + PATTERN_DATA * n


def kit(n):
    return KITS + KIT * n


@pytest.fixture(scope="module")
def built(official):
    return build_main.patched_image(official.section(3), xfade=30)


@pytest.fixture(scope="module")
def tlsolo(official):
    return build_main.patched_image(official.section(3), xfade=29)


def rig(built, numbered=range(128)):
    image, syms = built
    mc = Machine()
    mc.map(0x40000000, 0x800000)
    mc.map(0x40800000, 0x1400000)
    mc.map(0x43a00000, 0x400000)
    mc.write(mm.BASE, image)
    mc.set_stack(0x43df0000, 0x43dffff0)
    mc.uc.reg_write(UC_M68K_REG_SR, 0x2000)  # a task runs as the supervisor: stock's own tasks mask with move to SR (0x4008b4e8)
    for n in numbered:
        mc.w32(data(n) + NUMBER, n)
    mc.w32(RUNNING, 1)              # playing, so stock's routine only fills the queue
    mc.w32(HANDOFF, 0)
    return mc, syms


def cue(built, entries, numbered=range(128)):
    """entries: (pattern, kit, mark). -> the queue after the cue, as (pattern, kit, mark), and the index."""
    mc, syms = rig(built, numbered)
    for i, (p, k, mark) in enumerate(entries):
        e = LIST + 24 * i
        mc.w32(e, data(p))
        mc.w32(e + 4, kit(k))
        for w in range(2, 6):
            mc.w32(e + 4 * w, mark + w)
    mc.call(syms["long_queue"], LIST, len(entries))
    out = []
    for i in range(mc.r32(COUNT)):
        e = QUEUE + 24 * i
        p = (mc.r32(e) - PATTERNS) // PATTERN_DATA
        assert mc.r32(e) == data(p)
        k = (mc.r32(e + 4) - KITS) // KIT
        marks = [mc.r32(e + 4 * w) - w for w in range(2, 6)]
        assert len(set(marks)) == 1
        out.append((p, k, marks[0]))
    return out, mc.r32(INDEX)


def test_a_head_plays_then_its_tail_with_the_heads_kit(built):
    assert cue(built, [(3, 3, 0x100)]) == ([(3, 3, 0x100), (67, 3, 0x100)], 0xffffffff)
    assert cue(built, [(0, 0, 7)])[0] == [(0, 0, 7), (64, 0, 7)]
    assert cue(built, [(63, 63, 7)])[0] == [(63, 63, 7), (127, 63, 7)]


def test_a_chain_of_heads_gets_each_tail_after_its_head(built):
    assert cue(built, [(1, 1, 10), (2, 2, 20), (5, 5, 30)])[0] == \
        [(1, 1, 10), (65, 1, 10), (2, 2, 20), (66, 2, 20), (5, 5, 30), (69, 5, 30)]


def test_a_tail_cued_by_itself_plays_alone_with_its_own_kit(built):
    assert cue(built, [(70, 70, 1)])[0] == [(70, 70, 1)]
    assert cue(built, [(3, 3, 1), (70, 70, 2)])[0] == [(3, 3, 1), (67, 3, 1), (70, 70, 2)]


def test_a_tail_whose_number_does_not_read_right_is_not_added(built):
    assert cue(built, [(3, 3, 1)], numbered=[n for n in range(128) if n != 67])[0] == [(3, 3, 1)]


def test_a_queue_with_no_room_for_the_tails_is_stocks(built):
    entries = [(n % 64, n % 64, n) for n in range(1100)]
    q, _ = cue(built, entries)
    assert q == entries


def kitnum(built, playing, playing_kit):
    mc, syms = rig(built)
    mc.w32(PLAYING, data(playing))
    mc.w32(PLAYING_KIT, kit(playing_kit))
    return mc.call(syms["long_kitnum"], 0)


def test_the_uis_kit_is_the_heads_while_its_tail_plays_with_it(built):
    assert kitnum(built, 67, 3) == 3
    assert kitnum(built, 64, 0) == 0
    assert kitnum(built, 127, 63) == 63


def test_otherwise_the_uis_kit_is_the_playing_patterns(built):
    assert kitnum(built, 67, 67) == 67
    assert kitnum(built, 3, 3) == 3
    assert kitnum(built, 70, 3) == 70


def test_the_image_differs_from_the_tlsolo_image_only_where_declared(built, tlsolo):
    a, b = built[0], tlsolo[0]
    assert len(a) == len(b)
    allowed = set(range(*(mm.off(x) for x in mm.CAVE_LONG)))
    allowed |= set(range(*(mm.off(x) for x in mm.CAVE_SEAM)))
    allowed |= set(range(*(mm.off(x) for x in mm.CAVE_EDIT))) | set(range(*(mm.off(x) for x in mm.CAVE_EDIT2)))
    for call in mm.PATTERN_CLEAR_CALLS + mm.PATTERN_PASTE_CALLS + mm.PATTERN_COPY_CALLS:
        allowed |= set(range(mm.off(call + 2), mm.off(call + 6)))
    for call in mm.QUEUE_SET_CALLS + (mm.KIT_FOLLOW_CALL, mm.HIT_STEP_CALL, mm.LIVE_WRITE_CALL, mm.LIVE_NUMBER_CALL):
        allowed |= set(range(mm.off(call + 2), mm.off(call + 6)))
    for at in (mm.LIVE_NOW_CALL, mm.LIVE_NOW_LEA):
        allowed |= set(range(mm.off(at + 2), mm.off(at + 4)))
    assert all(a[i] == b[i] for i in range(len(a)) if i not in allowed)
    assert a[mm.off(mm.KIT_FOLLOW_CALL) + 2:mm.off(mm.KIT_FOLLOW_CALL) + 6] == built[1]["long_kitnum"].to_bytes(4, "big")


# The seam (the long image's second build). Stand-ins: the sequencer's routine that gives a hit's step
# (mm.HIT_STEP) answers what a test says, and the live trig's writer (mm.LIVE_WRITE) keeps the step it is given and
# the half it is told. Neither stock routine runs here: what the step routine answers at a pattern's end, and the
# writer's going into another pattern than the playing one, only the unit shows.
SCRATCH = 0x43a10000
TARGET = mm.CAVE_SEAM[1] - 4


def hit(built, playing, step, micro, pattern):
    mc, syms = rig(built)
    mc.w32(PLAYING, data(playing))
    mc.write(mm.HIT_STEP, bytes.fromhex(fw.sx("f8d7680f7ec326c0")) + bytes([0x10, 0xbc, 0, step & 0xff, 0x11, 0x7c, 0, micro & 0xff, 0, 1,
                                                            0x11, 0x7c, 0, pattern, 0, 2]) + bytes.fromhex("4e75"))
    out = SCRATCH
    mc.call(syms["long_when"], 0, 1, out)
    return tuple(mc.read(out, 3))


def test_a_hit_carries_its_half_when_its_step_is_of_the_playing_pair(built):
    assert hit(built, 3, 0, -5, 67) == (0xc0, 0xfb, 67)     # early for step 65: the tail's step 1
    assert hit(built, 67, 0, -5, 3) == (0x40, 0xfb, 3)      # early for the loop's start: the head's step 1
    assert hit(built, 3, 10, 2, 3) == (0x4a, 2, 3)
    assert hit(built, 67, 63, 0, 67) == (0xff, 0, 67)


def test_a_hit_of_another_pattern_is_stocks(built):
    assert hit(built, 3, 0, -5, 9) == (0, 0xfb, 9)          # a chain to another pattern
    assert hit(built, 3, 0, -5, 200) == (0, 0xfb, 200)


def write(built, playing, step):
    mc, syms = rig(built)
    mc.w32(PLAYING, data(playing))
    stub = (bytes.fromhex(fw.sx("052956b0aee643ed")) + b"\x23\xc0" + SCRATCH.to_bytes(4, "big")           # the step it is given
            + b"\x20\x39" + TARGET.to_bytes(4, "big") + b"\x23\xc0" + (SCRATCH + 4).to_bytes(4, "big")   # the half
            + bytes.fromhex("4e75"))
    mc.write(mm.LIVE_WRITE, stub)
    mc.call(syms["long_rec"], 0x41000000, 2, 0, 0, 0, step, 0, 0, 0, 0)
    told = mc.r32(SCRATCH + 4)
    return mc.r32(SCRATCH), told if told < 0x80000000 else told - (1 << 32), mc.r32(TARGET)


def test_the_writer_is_told_the_half_and_the_plain_step(built):
    assert write(built, 3, -64) == (0, 67, 0xffffffff)      # 0xc0 sign-extended: the tail, step 1
    assert write(built, 67, 0x40) == (0, 3, 0xffffffff)
    assert write(built, 70, -1) == (63, 70, 0xffffffff)     # a tail cued by itself: its own last step
    assert write(built, 3, 10) == (10, -1, 0xffffffff)      # a step with no half given: stock's


def test_the_writers_pattern_and_number_are_the_halfs_while_it_runs(built):
    mc, syms = rig(built)
    mc.w32(TARGET, 67)
    assert mc.call(syms["long_now"], 0x41000000) == 0x41000000 + 13204 + 1664 * 67
    assert mc.call(syms["long_num"], 0) == 67


def test_the_seams_five_places_point_at_ours(built):
    image, syms = built
    at = lambda a: image[mm.off(a):mm.off(a) + 6]
    assert at(mm.HIT_STEP_CALL) == b"\x4e\xb9" + syms["long_when"].to_bytes(4, "big")
    assert at(mm.LIVE_WRITE_CALL) == b"\x4e\xb9" + syms["long_rec"].to_bytes(4, "big")
    assert at(mm.LIVE_NUMBER_CALL) == b"\x4e\xb9" + syms["long_num"].to_bytes(4, "big")
    for a, op in ((mm.LIVE_NOW_CALL, b"\x4e\xba"), (mm.LIVE_NOW_LEA, b"\x47\xfa")):
        assert at(a)[:4] == op + (syms["long_now"] - (a + 2)).to_bytes(2, "big", signed=True)
    assert image[mm.off(TARGET):mm.off(TARGET) + 4] == b"\xff\xff\xff\xff"


# The third build: clear, copy and paste of a head carry its tail. Stand-ins, assembled here, for stock's clear, paste,
# copy and allocator, keeping what they are given; stock's copy of bytes (0x4011613c) runs. That stock's own routines
# take the longer list as they take a list of the grid's, and the undo of both, only the unit shows.
import subprocess
import tempfile

MANAGER, LISTED, KEPT_BUF, NOTES = 0x43c00000, 0x43a20000, 0x43b00000, 0x43a1fff0
EDIT_DATA = mm.CAVE_EDIT[1] - 8


def asm(text, at):
    with tempfile.TemporaryDirectory() as d:
        subprocess.run(["m68k-elf-as", "-mcpu=54418", "-o", d + "/s.o", "-"], input=text.encode(), check=True)
        subprocess.run(["m68k-elf-ld", "-Ttext=%#x" % at, "-o", d + "/s.elf", d + "/s.o"], check=True, capture_output=True)
        subprocess.run(["m68k-elf-objcopy", "-O", "binary", "-j", ".text", d + "/s.elf", d + "/s.bin"], check=True)
        return open(d + "/s.bin", "rb").read()


KEEP_LIST = """
    move.l 8(%%sp),%%a0
    move.l (%%a0),%%a1
    move.l 4(%%a0),%%d1
    lea %#x,%%a0
1:  cmp.l %%a1,%%d1
    beq 2f
    move.l (%%a1)+,(%%a0)+
    bra 1b
2:  moveq #-99,%%d0
    move.l %%d0,(%%a0)
    rts
""" % LISTED


def edit_rig(built):
    mc, syms = rig(built)
    for at, text in ((mm.PATTERN_CLEAR, KEEP_LIST), (mm.PATTERN_PASTE, KEEP_LIST),
                     (mm.PATTERN_COPY, "    moveq #1,%d0\n    rts\n"),
                     (0x4010394c, "    move.l #%#x,%%d0\n    rts\n" % KEPT_BUF)):
        mc.write(at, asm(text, at))
    note = 0x43a1ff00
    mc.write(note, asm("    addq.l #1,%#x\n    rts\n" % NOTES, note))
    for t in range(128):            # each pattern object's method table: + 16, the "changed" stand-in
        obj = MANAGER + 13204 + 1664 * t
        mc.w32(obj, 0x43a1fe00)
    mc.w32(0x43a1fe00 + 16, note)
    return mc, syms


def listed(mc):
    out, a = [], LISTED
    while (v := mc.r32(a)) != (-99 & 0xffffffff):
        out.append(v)
        a += 4
    return out


def run_with_list(mc, syms, name, numbers, *rest):
    lst, vec = 0x43a30000, 0x43a30400
    for i, n in enumerate(numbers):
        mc.w32(lst + 4 * i, n)
    mc.w32(vec, lst)
    mc.w32(vec + 4, lst + 4 * len(numbers))
    mc.call(syms[name], MANAGER, vec, *rest)
    return listed(mc)


def test_a_clear_of_heads_clears_their_tails_too(built):
    mc, syms = edit_rig(built)
    assert run_with_list(mc, syms, "long_clear", [3], 1, 1, 1) == [3, 67]
    assert run_with_list(mc, syms, "long_clear", [3, 4, 67], 1, 0, 1) == [3, 4, 67, 68]
    assert run_with_list(mc, syms, "long_clear", [70], 1, 1, 1) == [70]


def fill(mc, n, byte):
    mc.write(data(n), bytes([byte]) * 64)
    mc.write(data(n) + NUMBER - 8, bytes([byte]) * 8)


def test_a_paste_on_a_head_puts_the_copied_tail_on_its_tail(built):
    mc, syms = edit_rig(built)
    fill(mc, 67, 0xab)
    assert mc.call(syms["long_copy"], MANAGER, 3) & 0xff == 1
    assert mc.r32(EDIT_DATA) == KEPT_BUF and mc.r32(EDIT_DATA + 4) == 3
    fill(mc, 67, 0x11)              # the tail changed after the copy: the paste is of what was copied
    assert run_with_list(mc, syms, "long_paste", [10, 70], 1) == [10, 70, 74]
    assert mc.read(data(74), 64) == bytes([0xab]) * 64
    assert mc.read(data(74) + NUMBER - 8, 8) == bytes([0xab]) * 8
    assert mc.r32(data(74) + NUMBER) == 74
    assert mc.r32(data(70) + NUMBER) == 70 and mc.read(data(70), 4) != bytes([0xab]) * 4
    assert mc.r32(NOTES) == 1


def test_a_copy_of_a_tail_forgets_the_kept_tail_and_its_paste_is_stocks(built):
    mc, syms = edit_rig(built)
    mc.call(syms["long_copy"], MANAGER, 3)
    mc.call(syms["long_copy"], MANAGER, 70)
    assert mc.r32(EDIT_DATA + 4) == 0xffffffff
    assert run_with_list(mc, syms, "long_paste", [10], 1) == [10]
    assert mc.r32(NOTES) == 0


def test_the_kept_tail_starts_empty_in_the_image(built):
    image = built[0]
    assert image[mm.off(EDIT_DATA):mm.off(EDIT_DATA) + 8] == bytes(4) + b"\xff" * 4
    for stock, calls, ours in ((mm.PATTERN_CLEAR, mm.PATTERN_CLEAR_CALLS, "long_clear"), (mm.PATTERN_PASTE, mm.PATTERN_PASTE_CALLS, "long_paste"),
                               (mm.PATTERN_COPY, mm.PATTERN_COPY_CALLS, "long_copy")):
        for at in calls:
            assert image[mm.off(at):mm.off(at) + 6] == b"\x4e\xb9" + built[1][ours].to_bytes(4, "big")
