"""The recorder image: MODE 2 and 3 record the main mix or the external input into a slot.

Audio CPU side (engine/sampler.c built with RECORDER) runs inside the real voice
loop hook. Main CPU side (engine/recfeed.c) runs with the mixer stubbed, as the
mixer link does. The last test joins the two through the bytes of the shared
window. Nothing here says the window can be written while the unit runs, or
what the frame buffer holds on hardware: see docs/FINDINGS.md.
"""
import shutil

import numpy as np
import pytest
from unicorn import UC_HOOK_CODE
from unicorn.m68k_const import UC_M68K_REG_A7

from emu.engine import BLOCK, Board, Engine
from emu.machine import Machine
from tools import audiomap as m
from tools import build, build_engine, build_main, params
from tools import mainmap as mm
from tools import fw

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

SAMPLER = 44
TUNE, SAMPLE, START, LENGTH, LOOP, MODE, DECAY = 18, 19, 20, 21, 22, 23, 25
REC_MAIN, REC_EXT = 2, 3
ST = 1712                       # the sampler's state in a voice
ST_REC, ST_RPOS = ST + 51, ST + 56


@pytest.fixture(scope="module")
def stock(official):
    return official.section(7)


@pytest.fixture(scope="module")
def stock3(official):
    assert official.version == "1.42"
    return official.section(3)


@pytest.fixture(scope="module")
def plain(stock):
    return build_engine.patched_image(stock)


@pytest.fixture(scope="module")
def rec(stock):
    return build_engine.patched_image(stock, rec=True)


@pytest.fixture(scope="module")
def descs(official):
    return params.machines(official.section(3), official.version)


# ---- audio CPU -----------------------------------------------------------------------

class HookEngine(Engine):
    """The voice loop hook called directly. The interrupt keeps the trig mask in d2 and the
    release mask in d4 for its later stages, and the hook's post step reads them there."""

    def block(self, trig=0, release=0):
        self.mc.set_reg(2, trig)
        self.mc.set_reg(4, release)
        return super().block(trig, release)


def knob(slot, mode):
    """The SAMPLE value that names this slot: the slot itself in mono, its stereo sample when
    the mode is stereo or record (number n is slots 2n and 2n + 1)."""
    if mode & 3:
        assert slot % 2 == 0, "a stereo sample starts on an even slot"
        return 64 + slot // 2
    return 64 + slot


def samplers(e, track, slot, mode):
    for t in range(m.N_VOICES):
        e.set_machine(t, SAMPLER)
        e.set_note(t, 60)
        for s in range(18, 27):
            e.set_slot(t, s, 0)
        for s, v in ((TUNE, 64), (SAMPLE, 127), (LENGTH, 127), (DECAY, 127)):
            e.set_slot(t, s, v)
    e.set_slot(track, SAMPLE, knob(slot, mode))
    e.set_slot(track, MODE, mode)
    return e


def engine(built, track=2, slot=10, mode=REC_MAIN, pool=None):
    """Every track a sampler on an empty slot; one track on (slot, mode)."""
    image, syms = built
    e = HookEngine(image, loop_entry=syms["sampler_hook"])
    e.mc.map(0, 0x2000)                                  # the shared window
    e.load_pool(pool or {})
    return samplers(e, track, slot, mode)


class Feed:
    """What the main CPU does: a block into the ring, then the counter."""

    def __init__(self, e, seq=0):
        self.e, self.seq = e, seq
        e.mc.write(m.MAILBOX, seq.to_bytes(2, "big"))

    def push(self, block):
        self.seq = (self.seq + 1) & 0xFFFF
        at = m.MAILBOX + m.MAILBOX_RING + 4 * BLOCK * (self.seq % m.MAILBOX_BLOCKS)
        self.e.mc.write(at, np.asarray(block).astype(">i2").tobytes())
        self.e.mc.write(m.MAILBOX, self.seq.to_bytes(2, "big"))


def blocks(n, seed=3):
    return np.random.default_rng(seed).integers(-32768, 32768, (n, BLOCK, 2)).astype(np.int16)


def table(e):
    return [(e.mc.r32(m.SLOT_LEN + 8 * k), e.mc.r32(m.SLOT_PTR + 8 * k)) for k in range(m.SLOTS)]


def buf(k):
    return m.REC_BASE + m.REC_STRIDE * k


def taken(e, k):
    frames, ptr = table(e)[k]
    assert ptr == buf(k)
    return np.frombuffer(e.mc.read(ptr, 2 * frames), dtype=">i2").astype(np.int16)


def test_a_note_starts_a_take_and_the_note_off_ends_it(rec):
    e = engine(rec, track=2, slot=10)
    before = table(e)
    f = Feed(e, seq=0xFFF9)                              # the counter wraps during the take
    data = blocks(40)
    for b in range(40):
        f.push(data[b])
        e.block(trig=4 if b == 5 else 0, release=4 if b == 30 else 0)
        if b <= 5:
            assert table(e) == before                    # nothing happens until the note starts, one block after its trig
    # trig in block 5, note-off in block 30: 25 blocks, the note's own length
    want = data[6:31]
    after = table(e)
    assert after[10] == (BLOCK * 25, buf(10)) and after[11] == (BLOCK * 25, buf(11))
    assert np.array_equal(taken(e, 10), want[:, :, 0].ravel())
    assert np.array_equal(taken(e, 11), want[:, :, 1].ravel())
    assert [after[k] for k in range(m.SLOTS) if k not in (10, 11)] == [before[k] for k in range(m.SLOTS) if k not in (10, 11)]
    assert not any(e.mc.read(buf(k), 256).strip(b"\0") for k in (9, 12))   # the neighbours' buffers
    assert e.mc.read(e.voice(2) + ST_REC, 1) == b"\0"


def test_no_block_is_lost_or_doubled_when_the_two_sides_drift(rec):
    e = engine(rec, track=0, slot=4)
    f = Feed(e)
    data = blocks(60, seed=4)
    pattern = [1, 0, 2, 1, 1, 3, 0, 0, 1, 8, 0, 1, 2, 0, 4]
    e.block(trig=1)
    sent = 0
    for n in pattern * 2:
        for _ in range(n):
            f.push(data[sent])
            sent += 1
        e.block()
        assert table(e)[4][0] == BLOCK * sent
    assert sent == 48
    assert np.array_equal(taken(e, 4), data[:sent, :, 0].ravel())
    assert np.array_equal(taken(e, 5), data[:sent, :, 1].ravel())


def test_take_ends_instead_of_skipping_when_the_ring_was_overrun(rec):
    e = engine(rec, track=0, slot=4)
    f = Feed(e)
    data = blocks(30, seed=5)
    e.block(trig=1)
    for b in range(4):
        f.push(data[b])
        e.block()
    for b in range(4, 13):                               # nine blocks with no interrupt in between
        f.push(data[b])
    e.block()
    for b in range(13, 20):
        f.push(data[b])
        e.block()
    assert table(e)[4][0] == BLOCK * 4
    assert np.array_equal(taken(e, 4), data[:4, :, 0].ravel())
    assert e.mc.read(e.voice(0) + ST_REC, 1) == b"\0"


def test_a_stalled_feed_adds_nothing(rec):
    e = engine(rec, track=0, slot=4)
    Feed(e, seq=77)
    e.block(trig=1)
    for _ in range(20):
        e.block()
    assert table(e)[4] == (BLOCK, buf(4)) and table(e)[5] == (BLOCK, buf(5))   # the one block that was waiting


def test_take_stops_at_the_end_of_its_buffer(rec):
    e = engine(rec, track=1, slot=20)
    f = Feed(e)
    data = blocks(6, seed=6)
    e.block(trig=2)
    f.push(data[0])
    e.block()
    e.mc.w32(e.voice(1) + ST_RPOS, m.REC_MAX - 2 * BLOCK)     # test only: jump to just before the end
    for b in range(1, 6):
        f.push(data[b])
        e.block()
    assert table(e)[20] == (m.REC_MAX, buf(20)) and table(e)[21] == (m.REC_MAX, buf(21))
    assert m.REC_MAX * 2 == m.REC_STRIDE and m.REC_MAX <= 0x7ff00       # fills its buffer exactly; the player's limit
    for k, ch in ((20, 0), (21, 1)):
        tail = np.frombuffer(e.mc.read(buf(k) + m.REC_STRIDE - 4 * BLOCK, 4 * BLOCK), dtype=">i2")
        assert np.array_equal(tail, data[1:3, :, ch].ravel())
    assert not e.mc.read(buf(22), 256).strip(b"\0")                     # nothing past the right buffer
    assert e.mc.read(e.voice(1) + ST_REC, 1) == b"\0"


def test_buffers_sit_in_free_memory_below_the_stack():
    assert m.FREE_SDRAM[0] <= m.STASH and m.STASH + 7 * 128 <= m.REC_BASE
    assert buf(m.SLOTS) <= m.STACK_TOP - 0x100000
    assert m.MAILBOX == m.POOL_CHUNK and m.MAILBOX_SIZE <= 0x800        # inside the boot chunk half of the window


@pytest.mark.parametrize("mode", [REC_MAIN, REC_EXT])
def test_the_last_stereo_sample_is_the_last_two_slots_and_past_it_nothing_records(rec, mode):
    data = blocks(5, seed=7)
    past_table = []
    for number in (31, 32, 63, None):                    # None: nobody records, what stock leaves there
        e = engine(rec, track=7, slot=62, mode=0 if number is None else mode)
        if number is not None:
            e.set_slot(7, SAMPLE, 64 + number)
        e.mc.write(e.voice(7) + ST, bytes([0xA5]) * 88)  # whatever another machine left in the voice
        before = table(e)
        f = Feed(e)
        e.block(trig=0x80)
        for b in range(5):
            f.push(data[b])
            e.block()
        past_table.append(e.mc.read(m.SLOT_LEN + 8 * m.SLOTS, m.BSS[1] - m.SLOT_LEN - 8 * m.SLOTS))
        if number == 31:
            assert table(e)[62] == (BLOCK * 5, buf(62)) and table(e)[63] == (BLOCK * 5, buf(63))
            assert np.array_equal(taken(e, 62), data[:, :, 0].ravel())
            assert np.array_equal(taken(e, 63), data[:, :, 1].ravel())
            assert table(e)[:62] == before[:62]
        else:
            assert table(e) == before
            assert e.mc.read(e.voice(7) + ST_REC, 1) == b"\0"
            assert not e.mc.read(buf(62), 8 * BLOCK * 5).strip(b"\0")
        assert not e.mc.read(buf(64), 4 * BLOCK * 5).strip(b"\0")
    assert len(set(past_table)) == 1                     # no slot 64: the memory after the table is the engine's own


def test_every_value_of_the_knob_records_into_a_left_slot(rec):
    """Number n is slots 2n and 2n + 1, forward or reversed half of the knob: a take never starts on a right slot."""
    for value, left in ((64, 0), (65, 2), (64 + 17, 34), (63, 0), (62, 2), (63 - 17, 34)):
        e = engine(rec, track=3, slot=0)
        e.set_slot(3, SAMPLE, value)
        before = table(e)
        f = Feed(e)
        e.block(trig=8)
        f.push(blocks(1, seed=value)[0])
        e.block()
        after = table(e)
        assert after[left] == (BLOCK, buf(left)) and after[left + 1] == (BLOCK, buf(left + 1))
        assert [k for k in range(m.SLOTS) if after[k] != before[k]] == [left, left + 1]


def test_reversed_half_of_the_sample_knob_names_the_same_slots(rec):
    e = engine(rec, track=0, slot=0)
    e.set_slot(0, SAMPLE, 63 - 5)                        # plays stereo sample 5 backwards; records into it
    f = Feed(e)
    e.block(trig=1)
    f.push(blocks(1)[0])
    e.block()
    assert table(e)[10] == (BLOCK, buf(10)) and table(e)[11] == (BLOCK, buf(11))


def test_a_new_trig_starts_the_take_again(rec):
    e = engine(rec, track=0, slot=8)
    f = Feed(e)
    data = blocks(20, seed=8)
    for b in range(20):
        f.push(data[b])
        e.block(trig=1 if b in (0, 12) else 0)
    assert table(e)[8][0] == BLOCK * 7
    assert np.array_equal(taken(e, 8), data[13:, :, 0].ravel())


def test_turning_mode_away_ends_the_take(rec):
    e = engine(rec, track=0, slot=8)
    f = Feed(e)
    data = blocks(12, seed=9)
    e.block(trig=1)
    for b in range(12):
        if b == 4:
            e.set_slot(0, MODE, 0)
        if b == 6:
            e.set_slot(0, MODE, REC_MAIN)                # back, with no trig: nothing resumes
        f.push(data[b])
        e.block()
    assert table(e)[8][0] == BLOCK * 4
    assert np.array_equal(taken(e, 8), data[:4, :, 0].ravel())


def test_other_machines_and_modes_never_record(rec):
    for mode, machine in ((0, SAMPLER), (1, SAMPLER), (4, SAMPLER), (5, SAMPLER), (REC_MAIN, 4), (REC_EXT, 38)):
        e = engine(rec, track=0, slot=8, mode=mode)
        e.set_machine(0, machine)
        before = table(e)
        f = Feed(e)
        for b in range(6):
            f.push(blocks(1, seed=b)[0])
            e.block(trig=1 if b == 1 else 0)
        assert table(e) == before
        assert not e.mc.read(buf(8), 512).strip(b"\0")


def test_note_off_arrives_through_the_real_interrupt(rec):
    """The whole audio interrupt, not the hook alone: the masks come from the parameter block."""
    b = samplers(Board(rec[0]), 2, 10, REC_MAIN)
    f = Feed(b)
    data = blocks(20, seed=12)
    for k in range(20):
        f.push(data[k])
        b.interrupt(trig=4 if k == 3 else 0, release=4 if k == 15 else 0)
    assert table(b)[10] == (BLOCK * 12, buf(10)) and table(b)[11] == (BLOCK * 12, buf(11))
    assert np.array_equal(taken(b, 10), data[4:16, :, 0].ravel())
    assert np.array_equal(taken(b, 11), data[4:16, :, 1].ravel())


def test_a_recording_track_is_silent(rec):
    noise = np.random.default_rng(1).integers(-30000, 30000, 4000).astype(np.int16)
    loud = engine(rec, track=2, slot=10, mode=0, pool={10: noise})
    assert loud.render(12, trig=4)[2].any()
    e = engine(rec, track=2, slot=10, mode=REC_MAIN, pool={10: noise})
    Feed(e)
    assert not e.render(12, trig=4).any()


@pytest.mark.parametrize("mode", [REC_MAIN, REC_EXT])
def test_a_recording_track_leaves_the_next_track_alone(rec, mode):
    """Record is not stereo: the track after a recording one keeps its own sound, parameters and trigs."""
    noise = np.random.default_rng(2).integers(-30000, 30000, 4000).astype(np.int16)
    out = []
    for m2 in (0, mode):
        e = engine(rec, track=2, slot=10, mode=m2, pool={20: noise})
        e.set_slot(3, SAMPLE, 64 + 20)
        e.set_slot(3, 26, 55)                            # its own OVER, which a stereo link would overwrite
        Feed(e)
        out.append((e.render(12, trig=8)[3], e.mc.read(e.params(3), m.PARAM_STRIDE)))
    assert out[0][0].any() and np.array_equal(out[0][0], out[1][0])
    assert out[0][1] == out[1][1]


def take_and_twin(rec, plain, data, track=2, slot=10):
    """An engine holding `data` as a take in (slot, slot + 1), and one without the recorder
    holding the same samples as ordinary slots."""
    e = engine(rec, track=track, slot=slot)
    f = Feed(e)
    e.block(trig=1 << track)
    for block in data:
        f.push(block)
        e.block()
    e.block(release=1 << track)
    twin = engine(plain, track=track, slot=63, mode=0,
                  pool={slot: data[:, :, 0].ravel(), slot + 1: data[:, :, 1].ravel()})
    return e, twin


def test_a_take_plays_back_as_the_stereo_pair_it_is_at_twice_the_level(rec, plain):
    data = blocks(50, seed=10) // 2                      # half scale, so nothing is near the top
    out = []
    for x in take_and_twin(rec, plain, data):
        for s, v in ((SAMPLE, 64 + 5), (MODE, 1), (LENGTH, 100), (LOOP, 1)):       # stereo loop, sample 5: slots 10 and 11
            x.set_slot(5, s, v)
        x.set_note(5, 63)
        out.append(x.render(40, trig=0x20).astype(np.int64))
    take, sample = out
    assert sample[5].any() and sample[6].any()
    # a take plays at full scale, a sample at half: 6 dB, to within the mixing routine's rounding
    assert abs(take - 2 * sample).max() <= 16
    assert not take[[0, 1, 2, 3, 4, 7]].any()


def test_a_full_scale_take_does_not_wrap(rec, plain):
    square = np.where((np.arange(40 * BLOCK) // 24) % 2, 32767, -32768).astype(np.int16)
    data = np.stack([square, -1 - square], axis=1).reshape(40, BLOCK, 2)
    take, twin = take_and_twin(rec, plain, data)
    out = []
    for x in (take, twin):
        x.set_slot(5, SAMPLE, 64 + 5)
        x.set_slot(5, MODE, 1)
        out.append(x.render(30, trig=0x20).astype(np.int64))
    loud, half = out
    assert abs(half[5]).max() > 2 ** 29
    assert np.array_equal(np.sign(loud[5]), np.sign(half[5])) and np.array_equal(np.sign(loud[6]), np.sign(half[6]))
    assert abs(loud).max() <= 2 ** 31 - 1 and abs(loud[5]).max() > 2 ** 31 - 2 ** 17    # all the way up, no further
    assert abs(loud - 2 * half).max() <= 2 ** 16


def test_a_sample_after_a_take_is_back_at_its_own_level(rec, plain):
    """One voice plays a take and then an ordinary sample: the second note is what the image
    without the recorder plays, to the bit. The gain belongs to the note, not to the voice."""
    data = blocks(20, seed=11) // 2
    sample = np.random.default_rng(31).integers(-32768, 32768, 3000).astype(np.int16)
    ptr = m.REC_BASE - 0x20000                           # free memory below the take buffers
    out = []
    for x in take_and_twin(rec, plain, data):
        x.mc.write(ptr, sample.astype(">i2").tobytes())  # slot 20 by hand: loading a pool would rebuild the table
        x.mc.w32(m.SLOT_LEN + 8 * 20, len(sample))
        x.mc.w32(m.SLOT_PTR + 8 * 20, ptr)
        x.set_slot(5, SAMPLE, 64 + 10)
        x.render(8, trig=0x20)                           # the take, or its twin
        x.set_slot(5, SAMPLE, 64 + 20)
        out.append(x.render(20, trig=0x20)[:, 2 * BLOCK:])   # then the sample, from its second block on
    assert out[0][5].any() and np.array_equal(out[0], out[1])


@pytest.mark.parametrize("mode,loop", [(0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2), (4, 0), (4, 1), (5, 0), (5, 2)])
def test_playing_is_identical_to_the_image_without_the_recorder(rec, plain, mode, loop):
    rng = np.random.default_rng(4 * mode + loop)
    pool = {k: rng.integers(-32768, 32768, 700 + 13 * k).astype(np.int16) for k in (10, 11, 12, 13)}
    out = []
    for built in (plain, rec):
        e = engine(built, track=3, slot=10, mode=mode, pool=pool)
        e.set_slot(3, START, 9)
        e.set_slot(3, LENGTH, 99)
        e.set_slot(3, LOOP, loop)
        e.set_note(3, 66)
        e.set_slot(6, SAMPLE, 63 - 12)                   # a second voice, reversed
        out.append((e.render(30, trig=0x48), e.mc.insns))
    assert out[0][0].any()
    assert np.array_equal(out[0][0], out[1][0])


@pytest.mark.parametrize("mtype", [t for t in m.TYPE_OF_ENGINE if t != SAMPLER])
def test_stock_machines_stay_bit_identical(stock, rec, descs, mtype):
    image, syms = rec
    out = []
    for img, entry in ((stock, m.VOICE_LOOP), (image, m.VOICE_LOOP), (image, syms["sampler_hook"])):
        e = Engine(img, loop_entry=entry)
        e.mc.map(0, 0x2000)
        for t in range(m.N_VOICES):
            e.set_defaults(t, mtype, descs)
            e.set_note(t, 55 + 3 * t)
        out.append((e.render(24, trig=0xFF), e.mc.insns))
    assert out[0][0].any()
    assert np.array_equal(out[0][0], out[1][0]) and np.array_equal(out[0][0], out[2][0])
    assert out[0][1] == out[1][1]


def test_patch_touches_only_the_three_caves_and_three_pointers(stock, rec):
    image, syms = rec
    caves = dict(m.CAVES, **m.REC_CAVES)
    diff = {m.BASE + i for i in range(len(stock)) if stock[i] != image[i]}
    allowed = set()
    for start, end in caves.values():
        allowed |= set(range(start, end))
    for site in (m.UPDATE_TABLE + 4 * m.TWIN_ENGINE, m.RENDER_TABLE + 4 * m.TWIN_ENGINE, m.ISR_VOICE_LOOP_CALL + 2):
        allowed |= set(range(site, site + 4))
    assert diff <= allowed
    for name, addr in syms.items():
        assert any(s <= addr < e for s, e in caves.values()), name
    lo, hi = m.REC_CAVES["z"]
    assert lo <= syms["rec_step"] < hi
    e = Engine(image)
    assert not [a for a in e.mc.emac_sites if any(s <= a < e_ for s, e_ in caves.values())]
    # the cave is whole functions: one ends right before it, one ends at its end
    assert stock[m.off(lo) - 2:m.off(lo)] == b"\x4e\x75" and stock[m.off(hi) - 2:m.off(hi)] == b"\x4e\x75"
    assert lo == 0x40004a6a and m.TWIN_MIX < lo


def test_what_the_recorder_costs(rec, plain):
    """Instructions per 32-frame block, all 8 tracks idle samplers."""
    def per_block(built, mode, feed):
        e = engine(built, track=0, slot=8, mode=mode)
        f = Feed(e)
        e.block(trig=1)
        e.block()
        start = e.mc.insns
        for b in range(10):
            if feed:
                f.push(blocks(1, seed=b)[0])
            e.block()
        return (e.mc.insns - start) / 10
    base = per_block(plain, 0, False)
    idle = per_block(rec, 0, False) - base               # the image carries the recorder, nobody records
    armed = per_block(rec, REC_MAIN, False) - base       # a track says record, no audio arrives
    taking = per_block(rec, REC_MAIN, True) - base       # one block a block
    assert 0 < idle < 150
    assert armed < 250
    assert taking < 900
    assert (round(idle), round(taking)) == COST


COST = (125, 411)            # against a budget of 10,506 per voice (Phase 3)


# ---- main CPU: the feed, with the mixer stubbed --------------------------------------

STRIDE, TRACKS = 142, 12
P_TYPE, P_MODE = 62, 28 + 2 * MODE
PARAMS = 0x80002000
STUB = bytes.fromhex("203c8000dbd04e75")                 # move.l #0x8000dbd0,d0 ; rts
WINDOW = 0x1000


@pytest.fixture(scope="module")
def main(stock3):
    return build_main.patched_image(stock3, rec=True)


class MainRig:
    def __init__(self, image, syms, entry="mix_rec"):
        mc = self.mc = Machine()
        mc.map(0x40000000, 0x800000)
        mc.map(0x80000000, 0x10000)
        mc.map(mm.PATTERN_MUTES & ~0xffff, 0x10000)
        mc.map(mm.SHARED, 0x2000)
        mc.write(mm.BASE, image)
        mc.write(mm.MIX, STUB)                           # test only: the real mixer is not run
        for a, b in (mm.CAVE, mm.CAVE_REC, mm.CAVE_AMUTE):
            mc.load_code(a, image[mm.off(a):mm.off(b)])
        mc.set_stack(0x407ff000, 0x40000100)
        self.entry = syms[entry]
        self.seen = None
        mc.uc.hook_add(UC_HOOK_CODE, self._at_mixer, begin=mm.MIX, end=mm.MIX)
        mc.uc.ctl_flush_tb()
        mc.write(mm.LEVEL2, bytes(32))
        mc.write(mm.MUTES, bytes(8))
        mc.write(mm.PATTERN_MUTES, bytes(2))
        mc.w32(mm.AUDIO_UP, 1)

    def _at_mixer(self, uc, address, size, user):
        sp = uc.reg_read(UC_M68K_REG_A7)
        self.seen = dict(args=[self.mc.r32(sp + 4 * k) for k in (1, 2, 3)], params=self.mc.read(PARAMS, 0x800))

    def run(self, block, frame, window=None):
        """One mixer call. frame: (32, 20) int32. Returns (result, window after)."""
        mc = self.mc
        mc.write(PARAMS, block)
        mc.write(mm.FRAME, np.asarray(frame).astype(">i4").tobytes())
        if window is not None:
            mc.write(mm.SHARED, window)
        ret = mc.call(self.entry, 0x11111111, 0x22222222, PARAMS)
        assert mc.read(PARAMS, 0x800) == block           # the main CPU's own data is left as it was
        assert mc.read(mm.FRAME, 4 * BLOCK * mm.FRAME_CH) == np.asarray(frame).astype(">i4").tobytes()
        return ret, mc.read(mm.SHARED, WINDOW)


def make_block(machines, modes, seed=1):
    rng = np.random.default_rng(seed)
    b = bytearray(rng.integers(0, 256, 0x800, dtype=np.uint8).tobytes())
    for t in range(TRACKS):
        b[STRIDE * t + P_TYPE] = machines[t]
        b[STRIDE * t + P_MODE] = modes[t]
    return bytes(b)


def frames(n=1, seed=2):
    x = np.random.default_rng(seed).integers(-2 ** 31, 2 ** 31, (n, BLOCK, mm.FRAME_CH)).astype(np.int32)
    return x if n > 1 else x[0]


def junk(seq):
    w = bytearray(np.random.default_rng(9).integers(0, 256, WINDOW, dtype=np.uint8).tobytes())
    w[m.MAILBOX:m.MAILBOX + 2] = seq.to_bytes(2, "big")
    return bytes(w)


RND = m.MAILBOX + 4              # the dither's random number, a long in the window


def to16(pair, rnd):
    """The feed's conversion, as specified: (32, 2) int32 and the random number in ->
    (32, 2) int16 and the random number out. Half a step of rounding plus the difference
    of two 16-bit random numbers, top half kept, clamped."""
    out = []
    for x in np.asarray(pair).astype(np.int64).ravel():
        x = int(x)
        a = (rnd * 1664525 + 1013904223) & 0xFFFFFFFF
        rnd = (a * 1664525 + 1013904223) & 0xFFFFFFFF
        y = (x >> 16) + (((x & 0xFFFF) + 0x8000 + (a >> 16) - (rnd >> 16)) >> 16)
        out.append(max(-32768, min(32767, y)))
    return np.array(out, dtype=np.int16).reshape(-1, 2), rnd


def rnd_of(window):
    return int.from_bytes(window[RND:RND + 4], "big")


def ring_at(seq):
    return m.MAILBOX + m.MAILBOX_RING + 4 * BLOCK * (seq % m.MAILBOX_BLOCKS)


@pytest.fixture(scope="module")
def rig(main):
    return MainRig(*main)


@pytest.mark.parametrize("mode,left", [(REC_MAIN, mm.F_MAIN_L), (REC_EXT, mm.F_EXT_L)])
def test_feed_copies_one_stereo_pair_and_counts_up(rig, mode, left):
    machines = [0, 1, 2, SAMPLER, 4, 5, 6, 7, 8, 9, 10, 11]
    block = make_block(machines, [0, 0, 0, mode] + [0] * 8)
    frame = frames()
    before = junk(0x0105)
    ret, after = rig.run(block, frame, before)
    assert ret == 0x8000DBD0 and rig.seen["args"] == [0x11111111, 0x22222222, PARAMS]
    want = bytearray(before)
    want[m.MAILBOX:m.MAILBOX + 2] = (0x0106).to_bytes(2, "big")
    pair, rnd = to16(frame[:, left:left + 2], rnd_of(before))
    want[ring_at(0x0106):ring_at(0x0106) + 4 * BLOCK] = pair.astype(">i2").tobytes()
    want[RND:RND + 4] = rnd.to_bytes(4, "big")
    assert after == bytes(want)                          # that block, the counter and the random number: nothing else
    assert rnd != rnd_of(before)


def converted(rig, values, seed=0):
    """Feed the main pair with the given 32-bit values (flat, any length that fills whole blocks)
    and return what lands in the ring, as a flat int64 array of 16-bit numbers."""
    block = make_block([SAMPLER] * 12, [REC_MAIN] + [0] * 11)
    values = np.asarray(values, dtype=np.int64).reshape(-1, BLOCK, 2)
    window = junk(seed)
    out = []
    for k, pair in enumerate(values):
        frame = np.zeros((BLOCK, mm.FRAME_CH), dtype=np.int64)
        frame[:, 0:2] = pair
        _, window = rig.run(block, frame.astype(np.int32), window)
        at = ring_at(seed + k + 1)
        out.append(np.frombuffer(window[at:at + 4 * BLOCK], dtype=">i2").astype(np.int64))
    return np.concatenate(out)


def test_conversion_error_is_small_and_has_no_offset(rig):
    x = np.random.default_rng(21).integers(-2 ** 30, 2 ** 30, 64 * 400)
    y = converted(rig, x)
    err = (y * 65536 - x) / 65536                        # in 16-bit steps
    assert abs(err).max() <= 1.5                         # half a step of rounding, one step of dither
    assert abs(err.mean()) < 0.02                        # cutting the low half off would sit at -0.5
    assert 0.45 < err.std() < 0.55                       # rounding plus triangular dither: half a step, as theory says


@pytest.mark.parametrize("steps", [0.25, -0.6, 0.5, 3.1])
def test_a_level_below_one_step_survives_on_average(rig, steps):
    """What dither is for: a value between two 16-bit numbers comes out as noise around the right
    value. Cut off, 0.25 and 0.5 would read 0 every time and -0.6 would read -1."""
    y = converted(rig, np.full(64 * 500, int(steps * 65536)), seed=3)
    assert abs(y.mean() - steps) < 0.03
    assert set(np.unique(y)) <= {int(np.floor(steps)) + d for d in (-1, 0, 1, 2)}


def test_conversion_stops_at_the_ends_of_the_range(rig):
    y = converted(rig, [2 ** 31 - 1] * (64 * 20) + [-2 ** 31] * (64 * 20), seed=4)
    assert set(y[:64 * 20]) <= {32766, 32767} and set(y[64 * 20:]) <= {-32768, -32767}   # never wraps round
    assert (y[:64 * 20] == 32767).mean() > 0.8


def test_no_recording_track_no_write(rig):
    before = junk(5)
    for machines, modes in (([SAMPLER] * 12, [0, 1, 4, 5, 8, 9, 12, 13, REC_MAIN, REC_EXT, REC_MAIN, REC_EXT]),  # record only on 9..12
                            ([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11], [REC_MAIN] * 12)):                          # not the sampler
        ret, after = rig.run(make_block(machines, modes), frames(), before)
        assert ret == 0x8000DBD0 and after == before


def test_no_feed_until_the_audio_cpu_is_up(rig, stock3):
    """While the boot loader pushes sample chunks through this half of the window, it is not ours."""
    block = make_block([SAMPLER] * 12, [REC_MAIN] * 12)
    before = junk(9)
    rig.mc.w32(mm.AUDIO_UP, 0)
    try:
        ret, after = rig.run(block, frames(), before)
    finally:
        rig.mc.w32(mm.AUDIO_UP, 1)
    assert ret == 0x8000DBD0 and after == before
    assert rig.run(block, frames(), before)[1] != before
    # the flag: one routine sets it, one clears it, and the handshake calls them after and before the chunks
    assert stock3[mm.off(mm.AUDIO_UP_SET) - 2:mm.off(mm.AUDIO_UP_SET) + 8] == bytes.fromhex(fw.sx("7284aabc04a39e5edf03741a6b9f"))
    assert stock3[mm.off(mm.AUDIO_UP_CLEAR):mm.off(mm.AUDIO_UP_CLEAR) + 8] == bytes.fromhex(fw.sx("cc11433f83c124b1b730d4cd"))
    assert mm.u32(stock3, 0x400831b0 + 2) == mm.AUDIO_UP_SET - 2         # last state of the handshake
    assert mm.u32(stock3, 0x40082da4 + 2) == mm.AUDIO_UP_CLEAR           # where the audio CPU is restarted
    assert [a for a in (0x400a47f0, 0x400a4ae4, mm.AUDIO_UP_TEST) if mm.u32(stock3, a + 2) != mm.AUDIO_UP] == []


def test_first_recording_track_picks_the_source(rig):
    frame = frames(seed=3)
    block = make_block([SAMPLER] * 12, [0, 0, REC_EXT, 0, 0, REC_MAIN, 0, 0, 0, 0, 0, 0])
    _, after = rig.run(block, frame, junk(0))
    want, _ = to16(frame[:, mm.F_EXT_L:mm.F_EXT_L + 2], rnd_of(junk(0)))
    assert after[ring_at(1):ring_at(1) + 4 * BLOCK] == want.astype(">i2").tobytes()
    assert after[m.MAILBOX:m.MAILBOX + 2] == b"\0\1"     # one block, not one per recording track


def test_counter_wraps_and_the_ring_goes_round(rig):
    block = make_block([SAMPLER] * 12, [REC_MAIN] + [0] * 11)
    fs = frames(20, seed=4)
    window = junk(0xFFF8)
    rnd, want = rnd_of(window), []
    for k in range(20):
        _, window = rig.run(block, fs[k], window)
        seq = (0xFFF9 + k) & 0xFFFF
        assert window[m.MAILBOX:m.MAILBOX + 2] == seq.to_bytes(2, "big")
        pair, rnd = to16(fs[k][:, 0:2], rnd)             # the random number carries on from block to block
        want.append(pair)
        assert rnd_of(window) == rnd
    for k in range(12, 20):                              # the last eight are all still there
        at = ring_at(0xFFF9 + k)
        assert window[at:at + 4 * BLOCK] == want[k].astype(">i2").tobytes()


def test_mixer_link_still_does_its_work_underneath(main):
    """The mixer is shown exactly what the mixer link alone shows it."""
    image, syms = main
    machines = [SAMPLER, 0, 4, SAMPLER, 6, SAMPLER, 38, SAMPLER, 9, 10, 11, 12]
    modes = [1, 0, 1, 5, 0, REC_MAIN, 1, 1, 0, 0, 0, 0]
    block = make_block(machines, modes, seed=6)
    seen = []
    for entry in ("mix_link", "mix_rec"):
        r = MainRig(image, syms, entry)
        r.mc.write(mm.MUTES, (0b0100_0010).to_bytes(4, "big") + bytes(4))
        r.run(block, frames(seed=5), junk(0))
        seen.append(r.seen)
    assert seen[0] == seen[1]
    assert seen[0]["params"] != block                    # and that was not nothing: a pair is linked, a track muted


def test_main_cpu_patch_adds_only_the_feed(stock3, main):
    image, syms = main
    full, full_syms = build_main.patched_image(stock3)
    diff = [mm.BASE + i for i in range(len(full)) if full[i] != image[i]]
    lo, hi = mm.CAVE_REC
    a_lo, a_hi = mm.CAVE_AMUTE
    block_fn = syms["feed_block"]                        # the conversion, in the room after the analog mute
    assert a_lo < block_fn < a_hi
    allowed = set(range(lo, hi)) | set(range(mm.MIX_CALL + 2, mm.MIX_CALL + 6)) | set(range(block_fn, a_hi))
    assert diff and set(diff) <= allowed
    assert full[mm.off(a_lo):mm.off(block_fn)] == image[mm.off(a_lo):mm.off(block_fn)]     # the analog mute itself: the same code
    assert set(full[mm.off(block_fn):mm.off(a_hi)]) == {0x4e, 0x71}                          # and only padding after it there
    assert full[mm.off(lo):mm.off(hi)] == stock3[mm.off(lo):mm.off(hi)]      # the other images leave the cave alone
    assert mm.u32(image, mm.MIX_CALL + 2) == syms["mix_rec"] == lo
    assert mm.u32(full, mm.MIX_CALL + 2) == full_syms["mix_amute"] == syms["mix_amute"]
    assert full_syms["mix_link"] == syms["mix_link"]
    # the knobs are the same on both: MODE reaches the record values on an image that cannot record too
    assert params.load(image, "1.42") == params.load(full, "1.42")
    got = {p.slot: (p.short, p.min, p.max) for p in params.load(image, "1.42") if p.type == SAMPLER}
    assert got[MODE] == ("MODE", 0, 5) and got[LOOP] == ("LOOP", 0, 2)


def test_feed_reads_what_the_stock_code_writes(stock3):
    # the frame buffer and its channels: see tests/test_inputs.py. The ring is where boot sample chunks go.
    assert mm.MAILBOX == mm.SHARED_CHUNK == mm.SHARED + m.MAILBOX
    assert mm.u32(stock3, 0x40082fe8 + 2) == mm.MAILBOX
    assert mm.u16(stock3, 0x40082fdc + 2) == 0x800       # 2 KB a chunk: the ring fits


# ---- both sides ----------------------------------------------------------------------

@pytest.mark.parametrize("mode,left", [(REC_MAIN, mm.F_MAIN_L), (REC_EXT, mm.F_EXT_L)])
def test_main_cpu_frames_end_up_in_the_slot(rec, rig, mode, left):
    """Frames into the main CPU's feed, the window's bytes carried over, a take out of the audio CPU."""
    e = engine(rec, track=4, slot=30, mode=mode)
    block = make_block([SAMPLER] * 12, [0, 0, 0, 0, mode] + [0] * 7)
    fs = frames(26, seed=7)
    window = bytes(WINDOW)
    rnd, sent = 0, []
    for k in range(26):
        _, window = rig.run(block, fs[k], window)
        pair, rnd = to16(fs[k][:, left:left + 2], rnd)
        sent.append(pair)
        e.mc.write(m.MAILBOX, window[m.MAILBOX:m.MAILBOX + m.MAILBOX_SIZE])
        e.block(trig=0x10 if k == 2 else 0, release=0x10 if k == 23 else 0)
    want = np.array(sent[3:24])
    assert table(e)[30][0] == table(e)[31][0] == BLOCK * 21
    assert np.array_equal(taken(e, 30), want[:, :, 0].ravel())
    assert np.array_equal(taken(e, 31), want[:, :, 1].ravel())


# ---- the image ------------------------------------------------------------------------

def test_recorder_image_builds_and_the_other_two_do_not_contain_it(official_path, official, rec, main):
    quiet = lambda s: None
    raw, _, built, regions, syms = build.build(official_path, log=quiet, rec=True)
    assert sorted(regions) == [3, 7]
    assert built.section(7) == rec[0] and built.section(3) == main[0]
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
    assert {"rec_step", "mix_rec", "mix_link", "sampler_hook"} <= set(syms)
    lo, hi = m.REC_CAVES["z"]
    for variant in (dict(), dict(full=True)):
        other = build.build(official_path, log=quiet, **variant)[2]
        assert other.section(7)[m.off(lo):m.off(hi)] == official.section(7)[m.off(lo):m.off(hi)]
        a, b = mm.CAVE_REC
        assert other.section(3)[mm.off(a):mm.off(b)] == official.section(3)[mm.off(a):mm.off(b)]
