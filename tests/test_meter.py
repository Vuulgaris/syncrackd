"""The meter image: the sampling page's level meter, and every track as a source. Builds and"""
import shutil

import numpy as np
import pytest
from unicorn import UC_HOOK_MEM_WRITE

import test_screen
from emu.engine import BLOCK
from tools import audiomap as m
from tools import build, build_engine, build_main, deadcode
from tools import mainmap as mm
from test_page import EVENT, HEAP, KEYS, PAGE, SURFACE
from test_reclock import LockRig, MODE_KNOB, REC_KNOB, SRC_KNOB
from test_recorder import MainRig, STRIDE, frames, junk, make_block, ring_at, rnd_of, to16

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

SAMPLER = 44
STEREO, REC = m.MODE_STEREO, m.MODE_REC
ALL = [SAMPLER] * 8 + [8, 9, 10, 11]
NAMES = m.SRC_NAMES
SOURCES = range(len(NAMES))
# where each source is in the frame: (left, right)
PLACE = [(mm.F_MAIN_L, mm.F_MAIN_R), (mm.F_EXT_L, mm.F_EXT_R)] + [(mm.F_T1 + t, mm.F_T1 + t) for t in range(12)] \
    + [(mm.F_FX_L, mm.F_FX_R), (mm.F_SENDS_L, mm.F_SENDS_R)]
DOTS = HEAP + 0x8100  # the surface's dots: 128 columns of two longs
W, H = 128, 64
VARS = (mm.METER_PAGE, mm.METER_SRC, mm.METER_QUIET, mm.METER_LEVEL)
FEED_PAGE, OWNER = 0x40700000, 0x40700100  # a page object for the feed's rig, and the object at its + 44


def src(n):
    return n << m.SRC_SHIFT


@pytest.fixture(scope="module")
def stock(official):
    return official.section(7)


@pytest.fixture(scope="module")
def stock3(official):
    assert official.version == "1.42"
    return official.section(3)


@pytest.fixture(scope="module")
def main(stock3):
    return build_main.patched_image(stock3, meter=True)


@pytest.fixture(scope="module")
def before(stock3):
    return build_main.patched_image(stock3, reclock=True)


# ---- the page ------------------------------------------------------------------------------------

class MeterRig(LockRig):
    """The page rig with a surface stock's rectangle routine can draw on, and the meter's four numbers."""

    def __init__(self, built, machines, track=0, **kw):
        self.meter_writes = []
        super().__init__(built, machines, track=track, **kw)
        mc = self.mc
        mc.w32(SURFACE + mm.SURFACE_W, W)
        mc.w32(SURFACE + mm.SURFACE_H, H)
        mc.w32(SURFACE + mm.SURFACE_STRIDE, 2)
        mc.w32(SURFACE + mm.SURFACE_DATA, DOTS)
        self.paint(np.zeros((W, H), bool))

    def wrote(self, uc, access, address, size, value, user):
        if mm.METER_PAGE <= address < mm.METER_PAGE + mm.METER_VARS:
            self.meter_writes.append(address)
        elif not DOTS <= address < DOTS + 8 * W:
            super().wrote(uc, access, address, size, value, user)

    def paint(self, dots):
        """Set the surface: dots[x, y], a column two longs, y 0 the first long's highest bit."""
        bits = np.packbits(np.asarray(dots, bool), axis=1)
        self.mc.write(DOTS, bits.tobytes())

    @property
    def dots(self):
        raw = np.frombuffer(bytes(self.mc.read(DOTS, 8 * W)), np.uint8).reshape(W, 8)
        return np.unpackbits(raw, axis=1).astype(bool)

    @property
    def vars(self):
        return tuple(self.mc.r32(a) for a in VARS)

    def set(self, page=0, source=0, quiet=0, level=0):
        for a, v in zip(VARS, (page, source, quiet, level)):
            self.mc.w32(a, v)

    def src(self):
        got = self.places()
        return got[got.index("SRC") + 1]


def page_rig(main, track=0, **kw):
    r = MeterRig(main, {track: SAMPLER}, track=track, index=1, **kw)
    r.mc.w32(0x40196aba, 0), r.mc.w32(0x40196abe, 0)  # the bank numbers the page also draws
    return r


def bar_dots(level):
    """The bar's length for a level, as specified: 16 places to a halving (the highest bit and the four under it), 104
    dots at the largest sample, 5 dots to every 8 places.
    """
    v = level & 0x7fff
    e = max(v.bit_length() - 1, 0)
    u = 16 * e + ((v << 4 >> e) & 15)
    return max(0, int((5 * u - 363) / 8))


def bar_picture(level, under=None):
    """The surface after a drawing: the strip cleared, the bar, the mark past its end."""
    want = np.zeros((W, H), bool) if under is None else under.copy()
    want[m.BAR_X:m.BAR_X + m.BAR_W, 0:2] = False
    want[m.BAR_X:m.BAR_X + bar_dots(level), 0:2] = True
    want[m.BAR_X + m.BAR_W + 1, 0:3] = True
    return want


def test_the_bars_scale():
    assert bar_dots(32767) == m.BAR_W and bar_dots(0) == 0 and bar_dots(1) == 0
    for k in range(1, 10):  # ten dots to a halving
        assert bar_dots(32767 >> k) == m.BAR_W - 10 * k
    assert bar_dots(26) == 0 and bar_dots(27) == 1  # the first dot: 62 dB under the largest sample
    lengths = [bar_dots(v) for v in range(32768)]
    assert lengths == sorted(lengths) and set(lengths) == set(range(m.BAR_W + 1))


@pytest.mark.parametrize("track", [0, 7])
def test_src_goes_through_every_source_and_stops_at_both_ends(main, track):
    r = page_rig(main, track=track, mode=STEREO)
    assert r.src() == "MAIN"
    for n in list(SOURCES)[1:]:
        assert r.twist(SRC_KNOB, 1) == 1
        assert r.mode == STEREO | src(n) and r.src() == NAMES[n] and r.popped[-1] == ("SRC", NAMES[n])
    shown = len(r.popped)
    r.twist(SRC_KNOB, 1), r.twist(SRC_KNOB, 5)
    assert r.mode == STEREO | src(15) and len(r.popped) == shown  # the last one: nothing moves, nothing pops up
    for n in reversed(list(SOURCES)[:-1]):
        r.twist(SRC_KNOB, -1)
        assert r.mode == STEREO | src(n) and r.src() == NAMES[n] and r.popped[-1] == ("SRC", NAMES[n])
    r.twist(SRC_KNOB, -1), r.twist(SRC_KNOB, -9)
    assert r.mode == STEREO and r.changes == [4] * 15 + [-4] * 15
    assert not r.stray and not r.locked and not r.rec_locks and r.redrawn


def test_a_fast_turn_goes_several_sources_and_no_further_than_the_end(main):
    r = page_rig(main, mode=REC | src(3))
    r.twist(SRC_KNOB, 4)
    assert r.mode == REC | src(7) and r.src() == "T6"
    r.twist(SRC_KNOB, 40)
    assert r.mode == REC | src(15)
    r.twist(SRC_KNOB, -200)
    assert r.mode == REC


@pytest.mark.parametrize("mode", [0, STEREO, REC, REC | STEREO])
def test_the_source_and_the_two_switches_leave_each_other_alone(main, mode):
    r = page_rig(main, mode=mode | src(9))
    r.twist(SRC_KNOB, 2)
    assert r.mode == mode | src(11)
    r.twist(REC_KNOB, -1 if mode & REC else 1)
    assert r.mode == (mode ^ REC) | src(11) and r.src() == "T10"
    r = MeterRig(main, {0: SAMPLER}, index=0, mode=mode | src(9))  # the first page: MODE is the stereo switch
    r.twist(MODE_KNOB, -1 if mode & STEREO else 1)
    assert r.mode == (mode ^ STEREO) | src(9)


def test_what_an_earlier_build_saved_still_means_what_it_did(main):
    for mode, name in ((0, "MAIN"), (STEREO, "MAIN"), (REC, "MAIN"), (4, "EXT"), (4 | REC | STEREO, "EXT")):
        assert page_rig(main, mode=mode).src() == name


def test_src_is_still_the_tracks_alone_and_goes_into_every_lock_of_mode(main):
    r = page_rig(main, mode=STEREO | src(2))
    r.locks = {3: src(2), 9: REC | STEREO | src(5), 40: STEREO | src(2)}
    r.hold(3)  # a held step changes nothing: no lock of SRC
    r.twist(SRC_KNOB, 3)
    assert r.mode == STEREO | src(5) and not r.rec_locks
    # a lock of MODE carries the track's source and record, as on the reclock image: its stereo switch is its own
    assert r.locks == {3: src(5), 9: STEREO | src(5), 40: STEREO | src(5)}
    r.hold()
    r.twist(REC_KNOB, 1)
    assert r.locks == {3: REC | src(5), 9: REC | STEREO | src(5), 40: REC | STEREO | src(5)}


@pytest.mark.parametrize("level", [0, 1, 25, 26, 200, 4095, 4096, 16383, 16384, 30000, 32767])
def test_the_page_draws_the_bar_along_the_bottom_with_stocks_rectangle_routine(main, level):
    r = page_rig(main, mode=src(4))
    under = np.random.default_rng(level).integers(0, 2, (W, H)).astype(bool)
    r.paint(under)
    r.set(level=level)
    r.show()
    assert (r.dots == bar_picture(level, under)).all()
    assert r.order[0] == "stock" and not r.stray  # after stock's own drawing, over it


def test_a_drawing_tells_the_feed_what_to_watch_and_that_the_page_is_on_show(main):
    r = page_rig(main, mode=REC | STEREO | src(6))
    r.set(page=0, source=99, quiet=m.METER_STOP - 1, level=12345)
    r.show()
    assert r.vars == (PAGE, 6, 0, 12345)
    assert (r.dots == bar_picture(12345)).all()
    r.twist(SRC_KNOB, -5)
    r.show()
    assert r.vars == (PAGE, 1, 0, 12345)
    assert set(r.meter_writes) <= set(VARS)


def test_back_on_show_after_a_while_the_bar_starts_from_nothing(main):
    r = page_rig(main)
    for quiet in (m.METER_STOP, m.METER_STOP + 1, 0xffffffff):
        r.set(page=PAGE, quiet=quiet, level=30000)
        r.show()
        assert r.vars == (PAGE, 0, 0, 0) and (r.dots == bar_picture(0)).all()


def test_a_held_steps_drawing_watches_the_tracks_source(main):
    r = page_rig(main, mode=src(8))
    r.locks = {5: STEREO | src(8)}
    r.hold(5)
    r.show()
    assert r.vars[1] == 8 and r.src() == "T7"


@pytest.mark.parametrize("index, machine", [(0, SAMPLER), (1, 4), (0, 4)])
def test_no_bar_and_no_word_to_the_feed_on_any_other_page(main, index, machine):
    r = MeterRig(main, {0: machine}, index=index, mode=src(3))
    under = np.random.default_rng(1).integers(0, 2, (W, H)).astype(bool)
    r.paint(under)
    r.set(page=0x1234, source=7, quiet=55, level=999)
    r.show()
    assert (r.dots == under).all() and r.vars == (0x1234, 7, 55, 999) and not r.meter_writes and not r.texts


# ---- the feed --------------------------------------------------------------------------------------

class FeedRig(MainRig):
    """The feed's rig with the meter's run loaded, and a page object stock's redraw request can mark."""

    def __init__(self, image, syms):
        super().__init__(image, syms)
        lo, hi = mm.CAVE_METER
        self.mc.load_code(lo + mm.METER_VARS, image[mm.off(lo) + mm.METER_VARS:mm.off(hi)])
        self.mc.uc.ctl_flush_tb()
        self.reset()

    def reset(self, page=0, source=0, quiet=0, level=0):
        mc = self.mc
        mc.write(FEED_PAGE, bytes(0x200))
        mc.w32(FEED_PAGE + 44, OWNER)
        for a, v in zip(VARS, (page, source, quiet, level)):
            mc.w32(a, v)

    @property
    def vars(self):
        return tuple(self.mc.r32(a) for a in VARS)

    @property
    def asked(self):
        """Stock's redraw request has run on the page object since reset(): its flag and its owner's."""
        page, owner = bytes(self.mc.read(FEED_PAGE, 0x100)), bytes(self.mc.read(OWNER, 0x100))
        marks = (page[20], owner[32])
        assert marks in ((0, 0), (1, 1)) and not any(page[:20] + page[21:44] + page[48:]) and not any(owner[:32] + owner[33:])
        return marks == (1, 1)


@pytest.fixture(scope="module")
def rig(main):
    return FeedRig(*main)


def fed_pair(before, frame, left, right):
    want = bytearray(before)
    want[m.MAILBOX:m.MAILBOX + 2] = (0x0106).to_bytes(2, "big")
    pair, rnd = to16(np.stack([frame[:, left], frame[:, right]], axis=1), rnd_of(before))
    want[ring_at(0x0106):ring_at(0x0106) + 4 * BLOCK] = pair.astype(">i2").tobytes()
    want[m.MAILBOX + 4:m.MAILBOX + 8] = rnd.to_bytes(4, "big")
    return bytes(want)


@pytest.mark.parametrize("n", SOURCES)
@pytest.mark.parametrize("track, switches", [(0, REC), (7, REC | STEREO)])
def test_the_feed_takes_a_takes_two_sides_from_where_the_source_is_in_the_frame(rig, n, track, switches):
    rig.reset()
    frame = frames()
    window = junk(0x0105)
    ret, after = rig.run(make_block(ALL, [0] * track + [switches | src(n)] + [0] * (11 - track)), frame, window)
    assert ret == 0x8000DBD0 and after == fed_pair(window, frame, *PLACE[n])
    assert rig.vars == (0, 0, 0, 0) and not rig.asked  # no page has been drawn: no meter


def test_the_places_are_the_frames_own(rig):
    """A track is where its number says, and the rest are stock's channels as tools/mainmap.py has them."""
    assert [PLACE[n] for n in (0, 1, 2, 9, 10, 13, 14, 15)] == [(0, 1), (18, 19), (2, 2), (9, 9), (10, 10), (13, 13), (14, 15), (16, 17)]
    assert all(PLACE[n][0] == n for n in range(m.SRC_T1, m.SRC_FX))


def test_a_step_locked_on_records_the_tracks_source_and_the_first_track_in_record_picks(rig):
    rig.reset()
    frame, window = frames(), junk(0x0105)
    b = bytearray(make_block(ALL, [src(5), REC | src(12), 0, 0, REC | src(3)] + [0] * 7))
    p_rec = m.PARAM_KNOBS + 2 * m.K_REC
    for t in range(12):
        b[STRIDE * t + p_rec:STRIDE * t + p_rec + 2] = bytes(2)
    b[p_rec:p_rec + 2] = m.REC_WORD_ON.to_bytes(2, "big")
    _, after = rig.run(bytes(b), frame, window)
    assert after == fed_pair(window, frame, *PLACE[5])
    b[p_rec:p_rec + 2] = bytes(2)
    _, after = rig.run(bytes(b), frame, window)
    assert after == fed_pair(window, frame, *PLACE[12])


def level_after(level, frame, n):
    """The meter's level after a block, as specified: it falls by a 1024th of itself and one more, and is never under the
    block's largest sample, a negative one counted one less, top 16 bits.
    """
    l, r = PLACE[n]
    x = np.asarray(frame)[:, [l, r]].astype(np.int64)
    top = int(np.where(x < 0, ~x, x).max()) >> 16
    if level:
        level -= (level >> m.METER_FALL) + 1
    return max(level, top)


@pytest.mark.parametrize("n", SOURCES)
def test_the_level_is_the_sources_largest_sample_and_falls_by_itself(rig, n):
    rng = np.random.default_rng(n)
    rig.reset(page=FEED_PAGE, source=n)
    level, block = 0, make_block(ALL, [0] * 12)
    for k in range(40):
        frame = rng.integers(-2 ** 31, 2 ** 31, (BLOCK, mm.FRAME_CH)) >> int(rng.integers(0, 20)) if k % 5 == 0 else frames() >> 30
        window = junk(0x0105)
        _, after = rig.run(block, frame, window)
        level = level_after(level, frame, n)
        assert after == window and rig.vars == (FEED_PAGE, n, k + 1, level)


def test_the_largest_sample_either_way_fills_the_bar(rig):
    for value, want in ((0x7fffffff, 32767), (-0x80000000, 32767), (0x7fff0000, 32767), (-0x7fff0001, 32767), (0x00010000, 1), (0xffff, 0), (-1, 0)):
        for side in (0, 1):
            frame = np.zeros((BLOCK, mm.FRAME_CH), np.int64)
            frame[17, side] = value
            rig.reset(page=FEED_PAGE)
            rig.run(make_block(ALL, [0] * 12), frame)
            assert rig.vars[3] == want


def test_a_silent_source_lets_the_bar_fall_to_nothing(rig):
    rig.reset(page=FEED_PAGE, level=32767)
    block, frame, level, blocks = make_block(ALL, [0] * 12), np.zeros((BLOCK, mm.FRAME_CH), np.int64), 32767, 0
    seen = []
    while level and blocks < 200:
        rig.reset(page=FEED_PAGE, level=level)
        rig.run(block, frame)
        level = level_after(level, frame, 0)
        assert rig.vars[3] == level
        seen.append(level)
        blocks += 1
    # 13 dB a second: a halving in about 0.47 s, 710 blocks. Followed here for its first 200 blocks, then by the rule
    # alone.
    while level:
        level = level_after(level, frame, 0)
        seen.append(level)
    half = next(k for k, v in enumerate(seen) if v <= 16383)
    assert 650 < half < 760 and len(seen) < 9000


def test_it_watches_what_the_page_shows_not_what_a_track_records(rig):
    frame, window = frames(), junk(0x0105)
    rig.reset(page=FEED_PAGE, source=4)
    _, after = rig.run(make_block(ALL, [REC | src(1)] + [0] * 11), frame, window)
    assert after == fed_pair(window, frame, *PLACE[1]) and rig.vars[3] == level_after(0, frame, 4)


def test_a_source_that_is_no_source_is_watched_as_the_main_mix(rig):
    frame = frames()
    for bad in (16, 17, 31, 0x80000000, 0xffffffff):
        rig.reset(page=FEED_PAGE, source=bad)
        rig.run(make_block(ALL, [0] * 12), frame)
        assert rig.vars[3] == level_after(0, frame, 0)


def test_a_drawing_is_asked_for_every_96_blocks_with_stocks_own_request(rig):
    block, frame = make_block(ALL, [0] * 12), frames() >> 8
    rig.reset(page=FEED_PAGE)
    asked = []
    for k in range(1, m.METER_STOP + 40):
        rig.mc.write(FEED_PAGE + 20, b"\0"), rig.mc.write(OWNER + 32, b"\0")
        rig.run(block, frame)
        if rig.asked:
            asked.append(k)
    assert asked == [m.METER_EVERY, 2 * m.METER_EVERY, 3 * m.METER_EVERY]  # the last as it stops
    assert rig.vars[2] == m.METER_STOP


def test_it_stops_when_the_page_is_not_drawn_any_more_and_starts_when_it_is(rig):
    block, frame = make_block(ALL, [0] * 12), frames()
    for quiet in (m.METER_STOP, m.METER_STOP + 1, 0xffffffff):
        rig.reset(page=FEED_PAGE, source=3, quiet=quiet, level=777)
        rig.run(block, frame)
        assert rig.vars == (FEED_PAGE, 3, quiet, 777) and not rig.asked
    rig.reset(page=FEED_PAGE, source=3, quiet=0, level=777)  # what a drawing leaves
    rig.run(block, frame)
    assert rig.vars == (FEED_PAGE, 3, 1, level_after(777, frame, 3))


def test_stocks_request_is_not_made_of_a_page_that_says_no(rig):
    """Stock's own rule, run as it is: a page whose byte at + 23 is set is not marked."""
    block, frame = make_block(ALL, [0] * 12), frames()
    rig.reset(page=FEED_PAGE, quiet=m.METER_EVERY - 1)
    rig.mc.write(FEED_PAGE + 23, b"\x01")
    rig.run(block, frame)
    page, owner = bytes(rig.mc.read(FEED_PAGE, 0x30)), bytes(rig.mc.read(OWNER, 0x30))
    assert page[20] == 0 and owner[32] == 0 and rig.vars[2] == m.METER_EVERY


def test_the_meter_runs_while_the_audio_cpu_is_not_up_and_the_window_is_left(rig):
    frame, window = frames(), junk(0x0105)
    rig.reset(page=FEED_PAGE, source=2)
    rig.mc.w32(mm.AUDIO_UP, 0)
    try:
        _, after = rig.run(make_block(ALL, [REC | src(2)] * 12), frame, window)
    finally:
        rig.mc.w32(mm.AUDIO_UP, 1)
    assert after == window and rig.vars[3] == level_after(0, frame, 2)


def test_what_it_costs_the_main_cpu_a_block(rig, before):
    block, frame = make_block(ALL, [0] * 12), frames()
    taking = make_block(ALL, [REC | src(1)] + [0] * 11)
    old = MainRig(*before)

    def count(r, b=block, **kw):
        if kw or r is rig:
            r.reset(**kw)
        was = r.mc.insns
        r.run(b, frame, junk(0x0105))
        return r.mc.insns - was

    was, off, on = count(old), count(rig), count(rig, page=FEED_PAGE, source=0)
    stopped = count(rig, page=FEED_PAGE, quiet=m.METER_STOP)
    assert (off - was, stopped - off, on - off, count(rig, taking) - count(old, taking)) == COST


# more than the image before a block: with no page drawn yet; with the page gone; with the meter running; and a block
# of a take
COST = (12, 3, 641, 223)


# ---- MODE's range and its word -----------------------------------------------------------------------

def test_modes_knob_can_hold_every_source_and_still_reads_mono_or_stereo(stock3, main):
    at = mm.off(mm.SAMP_RECORDS + 0x34 * 5 + 0xc)
    assert main[0][at:at + 4] == (0x3f00).to_bytes(4, "big") and (m.MODE_SRC | 3) << 8 == 0x7f00 & 0x7f00
    assert (m.SRC_SENDS << m.SRC_SHIFT | 3) << 8 == 0x3f00
    s = test_screen.Screen(main)
    for n in SOURCES:
        for switches, word in ((0, "MONO"), (STEREO, "STEREO"), (REC, "MONO"), (REC | STEREO, "STEREO")):
            assert s.text(test_screen.MODE, (switches | src(n)) << 8) == word
    assert s.text(test_screen.MODE, 64 << 8) == "64" and not s.stray


# ---- the image -------------------------------------------------------------------------------------

def test_the_two_new_runs_are_code_nothing_reaches(stock3, official, main):
    runs = deadcode.survey(stock3, mm.BASE, mm.CODE_END, mm.ENTRY, [official.section(k) for k in (2, 4, 6, 8)])
    usable = deadcode.usable(runs)
    others = (mm.CAVE, mm.CAVE_REC, mm.CAVE_AMUTE, mm.CAVE_KEEP, mm.CAVE_HALVES, mm.CAVE_TEXT, mm.CAVE_PAGE, mm.CAVE_PAGE2, mm.CAVE_BANK,
              build_main.POOL_STAGE)
    for lo, hi in (mm.CAVE_METER, mm.CAVE_PAGE3):
        assert (lo, hi) in usable
        assert stock3[mm.off(lo) - 2:mm.off(lo)] == b"\x4e\x75" and stock3[mm.off(hi) - 2:mm.off(hi)] == b"\x4e\x75"
        assert not any(lo < b and a < hi for a, b in others)
    assert not (mm.CAVE_METER[0] < mm.CAVE_PAGE3[1] and mm.CAVE_PAGE3[0] < mm.CAVE_METER[1])
    image, syms = main
    lo, hi = mm.CAVE_METER
    assert syms["meter_vars"] == lo == mm.METER_PAGE and image[mm.off(lo):mm.off(lo) + mm.METER_VARS] == bytes(16)
    for name in ("chan", "meter", "mix_rec"):
        assert lo + mm.METER_VARS <= next(a for n, a in syms.items() if n.split(".")[0] == name) < hi
    lo, hi = mm.CAVE_PAGE3
    for name in ("src_name", "src_turn", "bar"):
        assert lo <= next(a for n, a in syms.items() if n.split(".")[0] == name) < hi
    lo, hi = mm.CAVE_AMUTE
    assert lo <= next(a for n, a in syms.items() if n.split(".")[0] == "feed_block") < hi


def test_the_image_is_the_pitch_image_but_for_the_main_cpus_page_feed_and_range(official_path, official, stock3, main, before):
    quiet = lambda s: None
    was = build.build(official_path, log=quiet, pitch=True)[2]
    raw, _, built, regions, syms = build.build(official_path, log=quiet, meter=True)
    assert sorted(regions) == [3, 7] and built.section(3) == main[0] and was.section(3) == before[0]
    assert built.section(7) == was.section(7)  # the audio CPU's program is the pitch image's
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
    mode_max = mm.SAMP_RECORDS + 0x34 * 5 + 0xc
    spans = [mm.CAVE_PAGE, mm.CAVE_PAGE2, mm.CAVE_PAGE3, mm.CAVE_METER, mm.CAVE_REC, mm.CAVE_AMUTE, mm.CAVE_TEXT, (mode_max, mode_max + 4)]
    spans += [(mm.SYN_CLASS + k, mm.SYN_CLASS + k + 4) for k in (mm.PAGE_KNOB_METHOD, mm.PAGE_DRAW_METHOD, mm.PAGE_TURN_METHOD)]
    spans += [(x, x + 4) for x in (mm.SYN_SIDE + mm.SYN_SIDE_TURN, mm.SYN_BUILD + 6, mm.MIX_CALL + 2, mm.TRIG_MUTE + 2, mm.TEXT_SLOT_SITE + 2)]
    spans += [(mm.HOLD_WRITE, mm.HOLD_WRITE + 8)]  # and a step's REC is put past stock's hold flag (tests/test_save.py)
    diff = [k for k in range(len(stock3)) if before[0][k] != main[0][k]]
    assert diff and all(any(mm.off(s) <= k < mm.off(e) for s, e in spans) for k in diff)
    for lo, hi in (mm.CAVE_METER, mm.CAVE_PAGE3):  # the two new runs are stock's own in the image before
        assert before[0][mm.off(lo):mm.off(hi)] == stock3[mm.off(lo):mm.off(hi)]


def test_the_stock_routines_it_calls_are_as_they_were(stock3, main):
    for lo, hi in ((mm.FILL_RECT, mm.FILL_RECT + 0x110), (mm.PAGE_REDRAW, mm.PAGE_REDRAW + 0x22), (0x40100966, 0x40100972)):
        assert main[0][mm.off(lo):mm.off(hi)] == stock3[mm.off(lo):mm.off(hi)]
