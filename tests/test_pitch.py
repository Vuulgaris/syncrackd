"""The "pitch" image: a sample stays clean when it is pitched (engine/sampler.c built with HQ)."""
import shutil

import numpy as np
import pytest
from unicorn import UC_HOOK_MEM_WRITE

from emu import sampler_ref as ref
from emu.engine import BLOCK
from tools import audiomap as m
from tools import build, build_engine, sinctable
from test_fade import BUDGET, CASES, DECAY, LENGTH, LOOP, MODE, POOL, SAMPLE, START, TUNE, start, tail
from test_live import SCRIPTS, hold, model, play, same
from test_pagerec import engine
from tools import fw

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

NOTES = [48, 36, 67, 72.5, 84, 55.25, 59]  # an octave and two down, up, between semitones, a semitone down
ROWS = sinctable.rows()
TABLE_BYTES = 33 * 16 * 2


@pytest.fixture(scope="module")
def stock(official):
    return official.section(7)


@pytest.fixture(scope="module")
def pitch(stock):
    return build_engine.patched_image(stock, pitch=True)


@pytest.fixture(scope="module")
def reclock(stock):
    return build_engine.patched_image(stock, reclock=True)


# ---- the engine is the model -----------------------------------------------------------------------

@pytest.mark.parametrize("note", NOTES)
@pytest.mark.parametrize("case", range(len(CASES)))
def test_the_engine_is_the_reference_model_bit_for_bit(pitch, case, note):
    """Whole samples, cut ones, loops, backwards, stereo, the short slot: every way a frame is read, at seven pitches.
    """
    knobs = CASES[case]
    script = hold(knobs.get("start", 0), knobs.get("length", 127), 40)
    e, left, right = play(pitch, script, note=note, **knobs)
    same(e, left, right, *model(e, script, floor=True, hq=True, **knobs), knobs)


@pytest.mark.parametrize("note", [48, 67])
@pytest.mark.parametrize("name", ["a walk, looped", "stereo, backwards", "ping-pong, leaps", "LEN down to a buzz and back", "the short slot",
                                  "a short loop, STRT turned up", "a one-shot, LEN pulled in behind it"])
def test_with_the_knobs_moving_too(pitch, name, note):
    knobs, script = SCRIPTS[name]
    e, left, right = play(pitch, script, note=note, **knobs)
    same(e, left, right, *model(e, script, floor=True, hq=True, **knobs), knobs)


@pytest.mark.parametrize("case", range(len(CASES)))
def test_at_its_own_pitch_a_sample_plays_as_it_did(pitch, reclock, case):
    """No frame falls between two: nothing is summed, and it is the reclock image's engine bit for bit."""
    knobs = CASES[case]
    script = hold(knobs.get("start", 0), knobs.get("length", 127), 40)
    _, a, ar = play(pitch, script, **knobs)
    _, b, br = play(reclock, script, **knobs)
    assert np.array_equal(a, b) and np.array_equal(ar, br) and np.any(a)


# ---- what it is for ---------------------------------------------------------------------------------

def tone_pool(hz, n=12000, level=20000):
    return {0: np.round(level * np.sin(2 * np.pi * hz / 48000 * np.arange(n))).astype(np.int16)}


def played(built, pool, note, blocks):
    e = engine(built, pool=pool)
    for t in range(m.N_VOICES):
        e.set_slot(t, SAMPLE, 64 + 63)
    for slot, v in ((TUNE, 64), (SAMPLE, 64), (START, 0), (LENGTH, 127), (LOOP, 0), (MODE, 0), (DECAY, 127)):
        e.set_slot(0, slot, v)
    e.set_note(0, note)
    out = np.array([e.block(trig=1 if b == 0 else 0) for b in range(blocks + 1)])
    return out[1:, 0, :].ravel().astype(float), e.player(0, 0)["inc"] / 4096  # and the speed stock's pitch table gave it


def clean(y, ratio, hz):
    """dB from the tone to everything else in y."""
    y = y[2048:2048 + 16384]
    spec = np.abs(np.fft.rfft(y * np.blackman(len(y)) ** 2)) ** 2
    k = int(round(hz * ratio / 48000 * len(y)))
    tone = spec[k - 12:k + 13].sum()
    return 10 * np.log10(tone / (spec.sum() - tone))


@pytest.mark.parametrize("hz, least, was", [(1000, 85, 65), (3000, 80, 45), (6000, 80, 33), (10000, 75, 23), (14000, 72, 16)])
def test_a_tone_two_octaves_down_comes_out_clean(pitch, reclock, hz, least, was):
    """The reclock image's engine on the same sample is the "sample rate reduction" heard: at 6 kHz everything else the
    line lets through is 32 dB under the tone, at 14 kHz 15 dB. Here it is 76 to 88 dB under.
    """
    pool = tone_pool(hz)
    now = clean(*played(pitch, pool, 36, 620), hz=hz)
    before = clean(*played(reclock, pool, 36, 620), hz=hz)
    assert now >= least and before <= was


@pytest.mark.parametrize("note", [48, 55, 59, 67])
def test_and_at_other_pitches(pitch, reclock, note):
    """An octave down, five semitones, one, and seven up: the same table at every speed."""
    pool = tone_pool(6000, n=30000)  # long enough to last the measure at the fastest of them
    blocks = int(18500 / BLOCK) + 1
    now = clean(*played(pitch, pool, note, blocks), hz=6000)
    before = clean(*played(reclock, pool, note, blocks), hz=6000)
    assert now >= 75 and before <= 35


def test_the_model_of_the_table_says_the_same(pitch):
    """tools/sinctable.py's own measure, on its own arithmetic: the number the docs quote."""
    assert sinctable.clean(6000, 0.25, lambda x, i, f: sinctable.interp(x, i, f, ROWS)) > 85
    assert sinctable.clean(6000, 0.25, sinctable.line) < 31


@pytest.mark.parametrize("note", [36, 48, 59, 67, 79])
def test_a_steady_level_stays_where_it_is_at_any_pitch(pitch, note):
    """Every row of the table adds up to the same: no ripple at the rate the frames are crossed."""
    script = hold(0, 127, 60)
    _, a, _ = play(pitch, script, note=note, sample=66)  # the pool's steady slot
    inside = a[40 * 1:len(a) // 2]
    assert inside.max() - inside.min() <= abs(inside.mean()) * 4e-5
    assert all(sum(r) == sinctable.ONE for r in ROWS)


def test_the_loudest_sample_there_can_be_does_not_wrap(pitch):
    """A sinc passes the frames it joins: full scale, switching every few frames, is where it passes them most. The sum
    is held, and the model agrees to the bit.
    """
    rng = np.random.default_rng(3)
    square = np.repeat(rng.choice([-32768, 32767], 800), rng.integers(1, 5, 800))[:2000].astype(np.int16)
    e = engine(pitch, pool={0: square})
    for t in range(m.N_VOICES):
        e.set_slot(t, SAMPLE, 64 + 63)
    for slot, v in ((TUNE, 64), (SAMPLE, 64), (START, 0), (LENGTH, 127), (LOOP, 0), (MODE, 0), (DECAY, 127)):
        e.set_slot(0, slot, v)
    e.set_note(0, 49.3)
    out = np.array([e.block(trig=1 if b == 0 else 0) for b in range(100)])[1:, 0, :].ravel()
    p = ref.Player({0: square}, fade=True, live=True, floor=True, hq=True)
    p.inc = e.player(0, 0)["inc"]
    p.note_on(sample=64)
    raw = [x for _ in range(99) for x in p.block()[0]]
    assert np.array_equal(out, np.array(tail(raw)))
    assert max(raw) == 2 * ref.HQ_TOP and min(raw) == -2 * ref.HQ_TOP - 2  # it did reach the stops, both ways
    held = [k for k, x in enumerate(raw) if x in (2 * ref.HQ_TOP, -2 * ref.HQ_TOP - 2)]
    assert all((raw[k] > 0) == (raw[k - 1] > 0) or abs(raw[k - 1]) < 2 ** 30 for k in held)  # held, not wrapped to the other side


# ---- the table ----------------------------------------------------------------------------------------

def table_of(e):
    raw = bytes(e.mc.read(m.HQ_TABLE, TABLE_BYTES))
    return [[int.from_bytes(raw[32 * r + 2 * k:32 * r + 2 * k + 2], "big", signed=True) for k in range(16)] for r in range(33)]


def test_the_engine_makes_its_table_on_the_first_block_from_the_rows_in_the_image(pitch):
    image, syms = pitch
    lo, hi = m.REC_CAVES["z"]
    stored = sinctable.stored()
    raw = image[m.off(syms["hq_rows"]):m.off(syms["hq_rows"]) + 17 * 32]
    assert lo == syms["hq_rows"] and syms["hq_rows"] + 17 * 32 <= hi
    assert raw == b"".join(v.to_bytes(2, "big", signed=True) for row in stored for v in row)
    e = engine(pitch)
    assert e.mc.r32(m.HQ_MADE) == 0 and m.HQ_MADE == e.voice(0) + 1712 + 80  # as a start leaves it
    e.mc.write(m.HQ_MARK, b"\xa5" * (4 + TABLE_BYTES))  # the memory comes as it is
    e.block()
    assert e.mc.r32(m.HQ_MADE) == sinctable.magic() and table_of(e) == ROWS
    assert ROWS[0] == [0] * 7 + [sinctable.ONE] + [0] * 8 and ROWS[32] == [0] * 8 + [sinctable.ONE] + [0] * 7
    assert all(ROWS[32 - r] == ROWS[r][::-1] for r in range(16))


@pytest.mark.parametrize("flips", [1, 8, 400])
def test_a_table_an_earlier_start_left_is_not_believed(pitch, flips):
    """The first two builds kept a long beside the table and made the table only when the long was not theirs. Memory
    that was without power for a moment comes back mostly as it was: the long whole, and bits of the table not. Now
    nothing in that memory is asked: a start makes the table.
    """
    rng = np.random.default_rng(flips)
    left = bytearray(b"".join(v.to_bytes(2, "big", signed=True) for row in ROWS for v in row))
    for bit in rng.choice(8 * TABLE_BYTES, flips, replace=False):
        left[bit // 8] ^= 1 << (bit % 8)
    e = engine(pitch)
    e.mc.w32(m.HQ_MARK, sinctable.magic())  # the long the earlier builds believed, whole
    e.mc.write(m.HQ_TABLE, bytes(left))
    e.block()
    assert table_of(e) == ROWS and e.mc.r32(m.HQ_MADE) == sinctable.magic()
    assert e.mc.r32(m.HQ_MARK) == sinctable.magic()  # (and that long is no longer written or read)


def test_it_is_made_once_a_start_and_again_after_stocks_voice_reset(pitch):
    e = engine(pitch)
    e.block()
    e.block(trig=0xff)  # each track's first note on a machine new to its voice:
    e.block()  # in the block the note starts in, the voice loop resets the voice, voice 0's too
    assert e.mc.r32(m.HQ_MADE) == 0
    e.block()  # and the table is made again, the same
    assert e.mc.r32(m.HQ_MADE) == sinctable.magic() and table_of(e) == ROWS
    wrote = []
    e.mc.uc.hook_add(UC_HOOK_MEM_WRITE, lambda uc, t, a, s, v, u: wrote.append(a), begin=m.HQ_MARK, end=m.HQ_MARK + 4 + TABLE_BYTES - 1)
    e.mc.uc.ctl_flush_tb()
    for b in range(6):
        e.block(trig=0xff if b % 2 == 0 else 0)
    assert not wrote  # there already: left alone, notes or not
    e.mc.call(m.VOICE_RESET, e.voice(3))  # stock's own, as the voice loop calls it when a track's machine changes
    e.mc.write(m.HQ_TABLE + 40, b"\x12\x34")
    e.block()
    assert not wrote and e.mc.r32(m.HQ_MADE) == sinctable.magic()  # another voice's: nothing to do with it
    e.mc.call(m.VOICE_RESET, e.voice(0))  # voice 0's, as at every start: the mark is gone
    assert e.mc.r32(m.HQ_MADE) == 0
    e.block()
    assert e.mc.r32(m.HQ_MADE) == sinctable.magic() and table_of(e) == ROWS
    assert set(wrote) == set(range(m.HQ_TABLE, m.HQ_TABLE + TABLE_BYTES, 2))


def test_the_units_start_clears_the_mark(stock):
    """Stock's init calls the voice reset for every voice (the one place that names it), and the reset clears + 1792 of
    the voice.
    """
    at = m.off(0x40000fe8)
    assert int.from_bytes(stock[at:at + 4], "big") == m.VOICE_RESET
    assert stock[m.off(0x40004312):m.off(0x40004316)] == bytes.fromhex(fw.sx("f11e7b9ce219ddb7"))  # clrl %a2@(1792)
    assert 1712 + 80 == 1792 and m.HQ_MADE == 0x80000000 + 1792


def test_the_tables_memory_is_no_one_elses(stock, pitch):
    """Free SDRAM past the program's own, under the takes' buffers and the marks beside them, clear of the right
    channels' stash.
    """
    end = m.HQ_MARK + 4 + TABLE_BYTES
    assert m.BSS[1] <= m.HQ_MARK and end <= m.KEPT < m.REC_BASE
    assert not (m.STASH <= m.HQ_MARK < m.STASH + 8 * 128) and m.STASH + 8 * 128 <= m.HQ_MARK
    ours = list(dict(m.CAVES, **m.REC_CAVES, **m.FADE_CAVES, **m.LIVE_CAVES, **m.PITCH_CAVES).values())
    for image in (stock, pitch[0]):  # nothing in either program names an address in it but our own code
        named = [o for o in range(0, len(image) - 3, 2) if m.HQ_MARK <= int.from_bytes(image[o:o + 4], "big") < end]
        assert all(any(m.off(lo) <= o < m.off(hi) for lo, hi in ours) for o in named) and (named or image is stock)


# ---- within reach of a slot's ends ------------------------------------------------------------------------
#
# The sixteen frames are not all in the slot there. Now a note's start writes the frames around both ends of its slot
# out once, and a frame there is summed like any other.

def ends_pool(n):
    rng = np.random.default_rng(n)
    return {0: rng.integers(-30000, 30000, n).astype(np.int16), 1: rng.integers(-30000, 30000, n + 3).astype(np.int16)}


def low(built, pool, note, blocks, warm=False, **knobs):
    """A note on track 0 from a pool of the test's: -> (engine, left, right, instructions a block), from the block it
    starts in. warm: a note on an empty slot first, so that the voice's reset at its first note, and the table made
    again after it, are over.
    """
    e = engine(built, pool=pool)
    for t in range(m.N_VOICES):
        e.set_slot(t, SAMPLE, 64 + 63)
    if warm:
        for trig in (1, 0, 0, 0):
            e.block(trig=trig)
    values = {TUNE: 64, SAMPLE: 64, START: 0, LENGTH: 127, LOOP: 0, MODE: 0, DECAY: 127}
    values.update({globals()[k.upper()]: v for k, v in knobs.items()})
    for slot, v in values.items():
        e.set_slot(0, slot, v)
    e.set_note(0, note)
    out, counts = [e.block(trig=1)], []
    for _ in range(blocks):
        n0 = e.mc.insns
        out.append(e.block())
        counts.append(e.mc.insns - n0)
    out = np.array(out)
    assert not out[0].any()
    return e, out[1:, 0, :].ravel(), out[1:, 1, :].ravel(), counts


def low_model(e, pool, blocks, **knobs):
    p = ref.Player(pool, fade=True, live=True, floor=True, hq=True)
    p.inc = e.player(0, 0)["inc"]
    p.note_on(sample=knobs.get("sample", 64), start=knobs.get("start", 0), length=knobs.get("length", 127),
              loop=knobs.get("loop", 0), mode=knobs.get("mode", 0))
    left, right = [], []
    for b in range(blocks):
        if b:
            p.move(knobs.get("start", 0), knobs.get("length", 127))
        l, r = p.block()
        left += tail(l)
        right += tail(r) if r is not None else [0] * BLOCK
    return np.array(left), np.array(right)


@pytest.mark.parametrize("knobs", [dict(), dict(mode=1), dict(sample=63), dict(sample=63, mode=1), dict(loop=1, mode=1), dict(loop=2),
                                   dict(start=30, length=60, mode=1)])
@pytest.mark.parametrize("n", [3, 8, 15, 16, 17, 23, 24, 40, 300])
def test_within_reach_of_a_slots_ends_it_is_the_model_too(pitch, n, knobs):
    """Slots of a few frames and of many, three octaves down, so that every place within reach of either end is played
    from many times: forwards, backwards, stereo, looped, cut.
    """
    pool = ends_pool(n)
    blocks = 14 if n < 100 else 90
    e, left, right, _ = low(pitch, pool, 24, blocks, **knobs)
    want_l, want_r = low_model(e, pool, blocks, **knobs)
    assert np.array_equal(left, want_l) and (np.any(left) or n < 8)  # (a cut out of three frames is no note)
    if knobs.get("mode") == 1:
        assert np.array_equal(right, want_r) and (np.any(right) or n < 8)


@pytest.mark.parametrize("voice", [0, 3, 7])
def test_a_notes_start_writes_out_the_frames_around_both_ends_of_its_slot(pitch, voice):
    n = 40
    pool = ends_pool(n)
    e = engine(pitch, pool=pool)
    for t in range(m.N_VOICES):
        e.set_slot(t, SAMPLE, 64 + 63)
    for slot, v in ((TUNE, 64), (SAMPLE, 64), (START, 0), (LENGTH, 127), (LOOP, 0), (MODE, 1 if voice < 7 else 0), (DECAY, 127)):
        e.set_slot(voice, slot, v)
    e.set_note(voice, 24)
    e.block()
    e.mc.write(m.HQ_PADS, b"\xa5" * (8 * m.HQ_PAD_BYTES))
    wrote = []
    e.mc.uc.hook_add(UC_HOOK_MEM_WRITE, lambda uc, t, a, s, v, u: wrote.append(a), begin=m.HQ_TABLE + TABLE_BYTES, end=m.HQ_PADS + 8 * m.HQ_PAD_BYTES + 0x400)
    e.mc.uc.ctl_flush_tb()
    e.block(trig=1 << voice)
    e.block()
    at = m.HQ_PADS + m.HQ_PAD_BYTES * voice
    sides = 2 if voice < 7 else 1
    assert e.mc.r32(e.voice(voice) + 1712 + 72) == at  # the voice's own 256 bytes
    assert sorted(set(wrote)) == list(range(at, at + 2 * m.HQ_PAD_SIDE * sides, 2))  # and nothing else, once
    got = np.frombuffer(bytes(e.mc.read(at, 2 * m.HQ_PAD_SIDE * sides)), ">i2").reshape(sides, m.HQ_PAD_SIDE)
    for side in range(sides):
        x = pool[side]
        want = [x[min(max(j, 0), n - 1)] for j in list(range(-7, 15)) + list(range(n - 15, n + 8))]
        assert list(got[side]) == [int(v) for v in want]
    for _ in range(6):  # the note goes on: nothing more is written there
        e.block()
    assert len(wrote) == m.HQ_PAD_SIDE * sides


def test_that_memory_is_no_one_elses(stock, pitch):
    end = m.HQ_PADS + 8 * m.HQ_PAD_BYTES
    assert m.HQ_MARK + 4 + TABLE_BYTES <= m.HQ_PADS and end <= m.KEPT < m.REC_BASE
    ours = list(dict(m.CAVES, **m.REC_CAVES, **m.FADE_CAVES, **m.LIVE_CAVES, **m.PITCH_CAVES).values())
    for image in (stock, pitch[0]):
        named = [o for o in range(0, len(image) - 3, 2) if m.HQ_PADS <= int.from_bytes(image[o:o + 4], "big") < end]
        assert all(any(m.off(lo) <= o < m.off(hi) for lo, hi in ours) for o in named) and (named or image is stock)


@pytest.mark.parametrize("note", [36, 24, 12])
@pytest.mark.parametrize("mode", [0, 1])
def test_a_low_notes_first_and_last_blocks_cost_what_the_rest_do(pitch, note, mode):
    """Every block of a note from its first frame to its last, two to four octaves down."""
    n = {36: 1000, 24: 500, 12: 250}[note]
    _, left, _, counts = low(pitch, ends_pool(n), note, 150, warm=True, mode=mode)
    sounding = [k for k in range(150) if left[32 * k:32 * k + 32].any()]
    assert 100 < len(sounding) < 140 and sounding == list(range(len(sounding)))  # it plays to the slot's end inside the run
    body = counts[2:len(sounding) - 2]
    steady = max(body)
    assert steady - min(body) < 300  # (a frame of the sample itself is less work)
    assert 305 < counts[0] - steady < START_COST[mode]  # the note's start: the frames written out, once
    assert max(counts[1:len(sounding)]) - steady < 100  # and no other block of it costs more


# a note's first block over one of its middle, at most: mono, stereo. The reclock image's is 305 and 328 over: a
# note's start. Measured 731 to 810 and 1,419 to 1,525: writing the frames out is about 450 and 1,150 instructions,
# once a note. (A voice's first note on a machine is 670 more in any image: stock resets the voice. The block after
# voice 0's, the table is made again.)
START_COST = (850, 1600)

# ---- what it costs --------------------------------------------------------------------------------------

def test_cost_on_the_audio_cpu(pitch, reclock):
    """Instructions in a block of the whole voice loop. One voice against the reclock image's: at its own pitch, and
    pitched, mono and stereo. Then the most there can be at once: eight mono voices pitched, and four stereo ones.
    """
    def count(built, note, tracks=(0,), **knobs):
        e = start(built, note=note, **knobs)
        for t in tracks[1:]:
            for slot, v in ((TUNE, 64), (SAMPLE, 64), (START, 0), (LENGTH, 127), (LOOP, 1), (MODE, knobs.get("mode", 0)), (DECAY, 127)):
                e.set_slot(t, slot, v)
            e.set_note(t, note)
        for t in tracks:  # each voice's first note, on an empty slot: its reset, and the table made again after voice 0's
            e.set_slot(t, SAMPLE, 64 + 63)
        for trig in (sum(1 << t for t in tracks), 0, 0, 0):
            e.block(trig=trig)
        for t in tracks:
            e.set_slot(t, SAMPLE, knobs.get("sample", 64))
        e.block(trig=sum(1 << t for t in tracks))
        e.block()
        worst = 0
        for _ in range(6):
            n0 = e.mc.insns
            e.block()
            worst = max(worst, e.mc.insns - n0)
        return worst
    own = count(pitch, 60, sample=64, mode=1) - count(reclock, 60, sample=64, mode=1)
    mono = count(pitch, 53, sample=64) - count(reclock, 53, sample=64)
    stereo = count(pitch, 53, sample=64, mode=1) - count(reclock, 53, sample=64, mode=1)
    full = (count(pitch, 53, tracks=tuple(range(8)), sample=64, loop=1), count(pitch, 53, tracks=(0, 2, 4, 6), sample=64, loop=1, mode=1))
    assert (own, mono, stereo) == COST and full == FULL
    assert max(full) < 8 * BUDGET  # under eight SY SWARMs, the most stock asks of the loop


COST = (-413, 4006, 7848)  # against the reclock image's: a stereo voice at its own pitch (less: nothing is worked out), a mono voice pitched, a stereo voice pitched
FULL = (56583, 76901)  # the whole loop: eight mono voices pitched; four stereo voices pitched, whose four right-hand


# ---- the image -------------------------------------------------------------------------------------------

def test_the_image_is_the_reclock_image_but_for_the_sound_engine(official_path, official, stock, pitch, reclock):
    quiet = lambda s: None
    was = build.build(official_path, log=quiet, reclock=True)[2]
    raw, _, built, regions, syms = build.build(official_path, log=quiet, pitch=True)
    assert sorted(regions) == [3, 7] and built.section(7) == pitch[0] and was.section(7) == reclock[0]
    assert built.section(3) == was.section(3)  # the main CPU's program is the reclock image's
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
    caves = dict(m.CAVES, **m.REC_CAVES, **m.FADE_CAVES, **m.LIVE_CAVES, **m.PITCH_CAVES)
    spans = list(caves.values())
    assert not any(a < d and c < b for k, (a, b) in enumerate(spans) for c, d in spans[k + 1:])
    spans += [(x, x + 4) for x in (m.UPDATE_TABLE + 4 * m.TWIN_ENGINE, m.RENDER_TABLE + 4 * m.TWIN_ENGINE, m.ISR_VOICE_LOOP_CALL + 2)]
    diff = [k for k in range(len(stock)) if stock[k] != pitch[0][k]]
    assert diff and all(any(m.off(s) <= k < m.off(e) for s, e in spans) for k in diff)
    for lo, hi in m.PITCH_CAVES.values():  # the five new runs are stock's own in the image before
        assert reclock[0][m.off(lo):m.off(hi)] == stock[m.off(lo):m.off(hi)]
        assert stock[m.off(lo) - 2:m.off(lo)] == b"\x4e\x75" and stock[m.off(hi) - 2:m.off(hi)] == b"\x4e\x75"
    where = {"sampler_post": "p", "keep_step": "q", "rec_step": "r", "hq_pads": "s", "hq_init": "t", "dest_of": "t", "rec_on": "t"}
    for name, cave in where.items():
        lo, hi = m.PITCH_CAVES[cave]
        assert lo <= next(a for n, a in pitch[1].items() if n.split(".")[0] == name) < hi
    lo, hi = m.CAVES["y"]
    assert lo <= pitch[1]["hq_mid"] < hi and lo <= pitch[1]["sampler_hook"] < hi
