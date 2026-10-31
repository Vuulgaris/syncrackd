"""The "gain" image: a record gain on the sampling page (engine/recfeed.c and engine/recpage.c built with GAIN).




A track's record gain, 0 to 24 dB a decibel a step, on knob F of the sampling page. The feed multiplies the
source by it before the 32 bits are made 16, so a quiet source is brought up out of the bits a take would have
thrown away. It is the page's own, like DEST: 0 at every start, not saved, not to be locked to a step.

What is held here, in emulation:
  - at 0 dB the feed is the stereo image's, bit for bit; with a gain every sample of a take is the source's top
    24 bits times the gain, held to what 32 bits hold, then made 16 as it always was;
  - what that buys: a quiet tone recorded with the gain on is as clean as a loud one, where the same gain put
    on afterwards brings the take's own noise up with it;
  - the meter shows the level with the gain on;
  - the page: the value in the lower row's second place, a turn of knob F a decibel, a number a track;
  - the sound engine is the stereo image's with the sum of twelve (tests/test_lean.py), which ran on
    the unit through two builds and marked passed.

Not held: how it reads on the unit's screen, and that the place in main CPU memory it is kept in is as free as
the meter's four numbers before it, which have run there.
"""
import shutil

import numpy as np
import pytest
from unicorn import UC_HOOK_MEM_WRITE

from emu.engine import BLOCK
from test_meter import ALL, FEED_PAGE, PLACE, REC, STEREO, FeedRig, MeterRig, src
from test_page import PAGE
from test_recorder import frames, junk, make_block, ring_at, rnd_of, to16
from test_reclock import SRC_KNOB
from tools import audiomap as m
from tools import build, build_engine, build_main, deadcode
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

SAMPLER = 44
TOP = mm.GAIN_TOP
TABLE = [round(256 * 10 ** (db / 20)) for db in range(TOP + 1)]
GAIN_KNOB = 6                           # knob F, as a turn names it
SEQ = 0x0106


@pytest.fixture(scope="module")
def stock3(official):
    assert official.version == "1.42"
    return official.section(3)


@pytest.fixture(scope="module")
def main(stock3):
    return build_main.patched_image(stock3, gain=True)


@pytest.fixture(scope="module")
def before(stock3):
    return build_main.patched_image(stock3, stereo=True)


class GainFeed(FeedRig):
    """The feed's rig for an image with the gain's numbers after the meter's four."""

    def reset(self, page=0, source=0, quiet=0, level=0, shown=0, gains=(0,) * 8):
        super().reset(page, source, quiet, level)
        self.mc.w32(mm.METER_GAIN, shown)
        self.mc.write(mm.REC_GAINS, bytes(gains))


@pytest.fixture(scope="module")
def rig(main):
    return GainFeed(*main)


def gained(x, db):
    """A sample with the gain on, as specified: its top 24 bits times the 256ths, held to 32 bits. 0 dB: itself."""
    g = TABLE[min(db, TOP)]
    if g == 256:
        return int(x)
    lim, v = 0x7fffffff // g, int(x) >> 8
    return 0x7fffffff if v > lim else -0x80000000 if v < -lim else v * g


def take_of(window, frame, left, right, db):
    """The window after a block of the feed: the ring's next block and the two numbers beside it."""
    want = bytearray(window)
    want[m.MAILBOX:m.MAILBOX + 2] = SEQ.to_bytes(2, "big")
    x = np.array([[gained(v, db) for v in row] for row in np.stack([frame[:, left], frame[:, right]], axis=1)], dtype=np.int64)
    pair, rnd = to16(x, rnd_of(window))
    want[ring_at(SEQ):ring_at(SEQ) + 4 * BLOCK] = pair.astype(">i2").tobytes()
    want[m.MAILBOX + 4:m.MAILBOX + 8] = rnd.to_bytes(4, "big")
    return bytes(want)


# ---- the feed -------------------------------------------------------------------------------------------------

def test_a_decibel_is_a_number_of_256ths(main):
    image, syms = main
    at = mm.off(syms["gain_table"])
    assert [int.from_bytes(image[at + 2 * k:at + 2 * k + 2], "big") for k in range(TOP + 1)] == TABLE
    assert TABLE[0] == 256 and TABLE[6] == 511 and TABLE[12] == 1019 and TABLE[24] == 4057 and TOP == 24
    assert mm.CAVE_METER[0] + mm.GAIN_VARS == syms["gain_table"] and image[mm.off(mm.CAVE_METER[0]):at] == bytes(mm.GAIN_VARS)


@pytest.mark.parametrize("n", [0, 1, 5, 14])
@pytest.mark.parametrize("track", [0, 7])
def test_at_0_db_the_feed_is_the_stereo_images(rig, before, n, track):
    """The same block through both programs: the same window after, to the bit."""
    old = FeedRig(*before)
    frame, window = frames(), junk(SEQ - 1)
    block = make_block(ALL, [0] * track + [REC | src(n)] + [0] * (11 - track))
    rig.reset(gains=[0] * 8)
    old.reset()
    _, after = rig.run(block, frame, window)
    assert after == old.run(block, frame, window)[1] == take_of(window, frame, *PLACE[n], 0)


@pytest.mark.parametrize("db", [1, 6, 7, 12, 18, 23, 24])
@pytest.mark.parametrize("track, n", [(0, 0), (3, 1), (7, 9)])
def test_with_a_gain_every_sample_is_the_source_times_it_before_it_is_made_16_bits(rig, db, track, n):
    """Noise at every level a source can have: what does not fit stops at the ends, as the feed always has it."""
    rng = np.random.default_rng(db)
    frame = frames(seed=db) >> rng.integers(0, 14, (BLOCK, mm.FRAME_CH))
    window = junk(SEQ - 1)
    gains = [int(v) for v in rng.integers(0, TOP + 1, 8)]
    gains[track] = db
    rig.reset(gains=gains)
    _, after = rig.run(make_block(ALL, [0] * track + [REC | STEREO | src(n)] + [0] * (11 - track)), frame, window)
    assert after == take_of(window, frame, *PLACE[n], db) != take_of(window, frame, *PLACE[n], 0)
    assert rig.mc.read(mm.REC_GAINS, 8) == bytes(gains) and rig.mc.r32(mm.METER_GAIN) == 0       # the feed reads them and no more


def test_the_first_track_in_record_records_with_its_own_gain(rig):
    frame, window = frames() >> 9, junk(SEQ - 1)
    rig.reset(gains=[3, 20, 9, 0, 0, 0, 0, 0])
    _, after = rig.run(make_block(ALL, [0, REC | src(4), REC | src(6)] + [0] * 9), frame, window)
    assert after == take_of(window, frame, *PLACE[4], 20)


def test_full_scale_with_the_most_gain_stops_at_the_ends_and_a_number_past_24_is_24(rig):
    frame = np.zeros((BLOCK, mm.FRAME_CH), dtype=np.int32)
    frame[:, 0] = np.where(np.arange(BLOCK) % 2, 0x7fffffff, -0x80000000)
    frame[:, 1] = np.linspace(-(1 << 28), 1 << 28, BLOCK).astype(np.int32)
    window = junk(SEQ - 1)
    rig.reset(gains=[TOP] * 8)
    _, after = rig.run(make_block(ALL, [REC] + [0] * 11), frame, window)
    assert after == take_of(window, frame, 0, 1, TOP)
    got = np.frombuffer(after[ring_at(SEQ):ring_at(SEQ) + 4 * BLOCK], dtype=">i2").reshape(BLOCK, 2)
    # (the lowest end is a step of the dither short of itself now and then, as it is without a gain)
    assert {int(v) for v in got[:, 0]} <= {32767, -32768, -32767} and {32767, -32768} <= {int(v) for v in got[:, 0]}
    assert got[0, 1] <= -32767 and got[-1, 1] == 32767 and abs(int(got[BLOCK // 2, 1])) < 12000
    rig.reset(gains=[200] * 8)                                      # whatever that memory holds
    assert rig.run(make_block(ALL, [REC] + [0] * 11), frame, window)[1] == after


def test_a_quiet_source_comes_up_out_of_the_bits_a_take_would_have_thrown_away(rig):
    """What it is for. A tone 66 dB under full scale, 2,048 frames of it: recorded as it is and turned up 24 dB
    afterwards, it has the take's own noise turned up with it; recorded with 24 dB of gain it is as clean as a
    tone 42 dB under. The difference is the gain, near enough."""
    n = 64 * BLOCK
    tone = np.sin(2 * np.pi * 997 / 48000 * np.arange(n))
    quiet = np.round(tone * (2 ** 31) * 10 ** (-66 / 20)).astype(np.int64)

    def take(db):
        out, window = [], junk(SEQ - 1)
        rig.reset(gains=[db] * 8)
        for b in range(n // BLOCK):
            frame = np.zeros((BLOCK, mm.FRAME_CH), dtype=np.int32)
            frame[:, 0] = quiet[BLOCK * b:BLOCK * (b + 1)]
            _, window = rig.run(make_block(ALL, [REC] + [0] * 11), frame, window)
            seq = int.from_bytes(window[m.MAILBOX:m.MAILBOX + 2], "big")
            out.append(np.frombuffer(window[ring_at(seq):ring_at(seq) + 4 * BLOCK], dtype=">i2").reshape(BLOCK, 2)[:, 0])
        return np.concatenate(out).astype(float)

    def clean(y):                                                   # dB from the tone to everything else
        amp = 2 * np.dot(y, tone) / n
        rest = y - amp * tone
        return 10 * np.log10((amp ** 2 / 2) / np.mean(rest ** 2))
    plain, up = clean(take(0) * TABLE[TOP] / 256), clean(take(TOP))
    assert 20 < plain < 30 and 44 < up < 54 and 21 < up - plain < 27
    assert abs(np.abs(take(TOP)).max() - 32768 * 10 ** (-42 / 20)) < 40


@pytest.mark.parametrize("db", [0, 1, 6, 12, 24])
def test_the_meter_shows_the_level_with_the_gain_on(rig, db):
    """The largest sample of the source the page shows, times the gain the page shows, no more than a take holds."""
    rng = np.random.default_rng(db)
    for shift in (2, 6, 11):
        frame = frames(seed=shift) >> shift
        rig.reset(page=FEED_PAGE, source=0, shown=db, gains=[int(v) for v in rng.integers(0, TOP + 1, 8)])
        rig.run(make_block(ALL, [0] * 12), frame, junk(SEQ - 1))
        x = frame[:, [0, 1]].astype(np.int64)
        top = int(np.where(x < 0, ~x, x).max()) >> 16
        assert rig.vars[3] == min(32767, top * TABLE[db] >> 8) and (db == 0 or shift == 2 or rig.vars[3] > top)


# ---- the page ---------------------------------------------------------------------------------------------------

class GainPage(MeterRig):
    """The page rig, with the gain's numbers counted as the page's to write."""

    def __init__(self, built, track=0, **kw):
        self.gain_writes = []
        super().__init__(built, {track: SAMPLER}, track=track, index=1, **kw)
        self.mc.w32(0x40196aba, 0), self.mc.w32(0x40196abe, 0)
        self.mc.w32(mm.METER_GAIN, 0x55)
        self.mc.write(mm.REC_GAINS, bytes(8))

    def wrote(self, uc, access, address, size, value, user):
        if mm.METER_GAIN <= address < mm.REC_GAINS + 8:
            self.gain_writes.append((address, size, value & 0xffffffff))
        else:
            super().wrote(uc, access, address, size, value, user)

    @property
    def gains(self):
        return list(self.mc.read(mm.REC_GAINS, 8))


def words(db):
    return "0dB" if db == 0 else "+%ddB" % db


@pytest.mark.parametrize("db", [0, 1, 9, 10, 19, 24])
@pytest.mark.parametrize("track", [0, 5])
def test_the_page_shows_the_tracks_gain_in_the_lower_rows_second_place(main, db, track):
    r = GainPage(main, track=track)
    r.mc.write(mm.REC_GAINS, bytes([db if t == track else 13 for t in range(8)]))
    got = r.show()
    assert (59, 12, words(db)) in got and (59, 0, "") in got        # where a value goes; no name: the meter's bar is there
    assert [t for t in got if t[2] in ("SRC", "DEST", "REC")] and not r.stray
    assert r.gain_writes == [(mm.METER_GAIN, 4, db)]                # and the meter is told which gain to show the level with
    assert r.vars[1:3] == (0, 0)


def test_a_turn_of_knob_f_is_a_decibel_and_it_stops_at_both_ends(main):
    r = GainPage(main, track=2)
    for steps, want in ((1, 1), (1, 2), (4, 6), (-2, 4), (40, TOP), (1, TOP), (-3, TOP - 3), (-100, 0), (-1, 0), (0, 0)):
        del r.gain_writes[:]
        assert r.twist(GAIN_KNOB, steps) == 1 and r.gains == [0, 0, want, 0, 0, 0, 0, 0]
        assert [w[:2] for w in r.gain_writes] == [(mm.REC_GAINS + 2, 1)] and r.redrawn[-1] == PAGE and not r.stray
        assert (59, 12, words(want)) in r.show()


def test_each_track_has_its_own_and_the_other_knobs_are_what_they_were(main, before):
    r = GainPage(main, track=6)
    r.twist(GAIN_KNOB, 9)
    assert r.gains == [0, 0, 0, 0, 0, 0, 9, 0]
    old = MeterRig(before, {6: SAMPLER}, track=6, index=1)
    old.mc.w32(0x40196aba, 0), old.mc.w32(0x40196abe, 0)
    for knob, steps in ((SRC_KNOB, 3), (2, 5), (SRC_KNOB, -1), (3, 1)):
        assert r.twist(knob, steps) == old.twist(knob, steps)
        assert [t for t in r.show() if t[:2] != (59, 12) and t[2]] == [t for t in old.show() if t[2]]
    assert r.gains == [0, 0, 0, 0, 0, 0, 9, 0] and (59, 12, "+9dB") in r.show()


def test_on_the_first_page_and_on_another_machine_knob_f_is_stocks(main):
    r = GainPage(main, track=1)
    r.mc.w32(PAGE + mm.PAGE_INDEX, 0)                               # SYN's first page: knob F there is MODE, which is ours already
    r.twist(GAIN_KNOB, 5)
    assert r.gains == [0] * 8 and not [t for t in r.show() if t[2].endswith("dB")]
    other = MeterRig(main, {1: 4}, track=1, index=0)                # a drum machine: one page, stock's
    assert other.twist(GAIN_KNOB, 5) == other.turn_answer and len(other.turned) == 1
    assert list(other.mc.read(mm.REC_GAINS, 8)) == [0] * 8


# ---- the programs, and the image --------------------------------------------------------------------------------

def test_section_3_is_the_stereo_images_but_for_the_feed_and_the_page(stock3, main, before, official):
    image, syms = main
    spans = [mm.CAVE_PAGE, mm.CAVE_PAGE2, mm.CAVE_PAGE3, mm.CAVE_PAGE4, mm.CAVE_METER, mm.CAVE_AMUTE, mm.CAVE_REC]
    # and where routines that have moved in their runs are named: the page's methods, the mixer's call, the trig test, REC's mark
    spans += [(mm.SYN_CLASS + k, mm.SYN_CLASS + k + 4) for k in (mm.PAGE_KNOB_METHOD, mm.PAGE_DRAW_METHOD, mm.PAGE_TURN_METHOD)]
    spans += [(mm.SYN_SIDE + mm.SYN_SIDE_TURN, mm.SYN_SIDE + mm.SYN_SIDE_TURN + 4), (mm.MIX_CALL + 2, mm.MIX_CALL + 6),
              (mm.TRIG_MUTE + 2, mm.TRIG_MUTE + 6), (mm.HOLD_WRITE + 2, mm.HOLD_WRITE + 6), (mm.SYN_BUILD + 6, mm.SYN_BUILD + 10)]
    diff = [mm.BASE + k for k in range(len(image)) if image[k] != before[0][k]]
    assert diff and all(any(a <= d < b for a, b in spans) for d in diff), [hex(d) for d in diff if not any(a <= d < b for a, b in spans)][:8]
    assert syms["meter_vars"] == mm.METER_PAGE and (mm.METER_GAIN, mm.REC_GAINS) == (mm.METER_PAGE + 16, mm.METER_PAGE + 20)
    # the page's fourth run: code nothing reaches, clear of every run taken before it
    lo, hi = mm.CAVE_PAGE4
    runs = deadcode.survey(stock3, mm.BASE, mm.CODE_END, mm.ENTRY, [official.section(k) for k in (2, 4, 6, 8)])
    assert (lo, hi) in deadcode.usable(runs, 256) and hi - lo == 346
    assert stock3[mm.off(lo) - 2:mm.off(lo)] == b"\x4e\x75" and stock3[mm.off(hi) - 2:mm.off(hi)] == b"\x4e\x75"
    taken = [mm.CAVE, mm.CAVE_REC, mm.CAVE_AMUTE, mm.CAVE_KEEP, mm.CAVE_HALVES, mm.CAVE_TEXT, mm.CAVE_PAGE, mm.CAVE_BANK, mm.CAVE_PAGE2,
             mm.CAVE_METER, mm.CAVE_PAGE3, mm.CAVE_RIGHT, build_main.POOL_STAGE]
    assert not any(a < hi and lo < b for a, b in taken) and lo <= syms["gain_place"] < hi
    v = np.frombuffer(stock3[:len(stock3) // 4 * 4], dtype=">u4")
    w = np.frombuffer(stock3[2:2 + (len(stock3) - 2) // 4 * 4], dtype=">u4")
    assert not ((v >= lo) & (v < hi)).any() and not ((w >= lo) & (w < hi)).any()        # no long of stock's names an address in it


def test_the_image(official_path, official, main):
    """The stereo image's two programs, the sound engine with the sum of twelve, and the gain."""
    quiet = lambda s: None
    raw, _, built, regions, syms = build.build(official_path, log=quiet, gain=True)
    engine = build_engine.patched_image(official.section(7), stereo=True, twelve=True)
    assert sorted(regions) == [3, 7] and built.section(7) == engine[0] and built.section(3) == main[0]
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
    assert syms["gain_place"] == main[1]["gain_place"]
