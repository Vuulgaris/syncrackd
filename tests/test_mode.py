"""The "mode" image: a sample is mono or stereo by what its slots hold, and MODE says what a take is.







So (engine/sampler.h, AUTO):
  - SMPL always counts the 32 samples, number n in slots 2n and 2n + 1. A sample is stereo when its second slot
    holds exactly as many frames as its first, mono when not, and a mono one plays its first slot at a mono voice's
    cost. MODE's lowest bit plays no part in it;
  - that bit is what a take is. With it a take fills both slots. Without it the take is the source's two sides
    added and halved, in the first slot, and the second is left with one frame, which is kept on the drive like any
    take: what was in that slot cannot come back as a right channel;
  - its knob is on the sampling page, the lower row's third place (knob G), MONO or STER, and the first page's
    sixth place is empty. It is the track's alone;
  - the page's last place reads the audio CPU's peak load, as the time image measures it.

What is held here, in emulation:
  - a sample plays as it did: the gain image's engine with MODE on MONO and a sample in a slot, or on STEREO and one
    in two, and this engine with the same sample found for what it is, are the same frames;
  - the engine is the reference model (emu/sampler_ref.py, auto=True);
  - a mono take and a stereo take, on the audio CPU and in the feed, and what the keep's requests are answered;
  - the page, the knob's text, the descriptor, and that the two programs differ from the gain image's and the time12
    image's only where they are meant to.

Not held: anything on the unit. How the words read on its screen, and that a take of one frame is to the drive's
own code a sample like another, are the unit's to show.
"""
import shutil

import numpy as np
import pytest

import test_keep as K
import test_pagerec as P
from emu import sampler_ref as ref
from emu.engine import BLOCK
from test_fade import CASES, DECAY, LENGTH, LOOP, MODE, POOL, SAMPLE, START, TUNE, tail
from test_gain import GAIN_KNOB, GainFeed, GainPage, take_of, words
from test_live import SCRIPTS, hold, state
from test_meter import ALL, PLACE, REC, STEREO, MeterRig, src
from test_page import PAGE
from test_quick import Folded
from test_recorder import frames, junk, make_block, ring_at, rnd_of, to16
from test_reclock import REC_KNOB, SRC_KNOB
from tools import audiomap as m
from tools import build, build_engine, build_main, params, sinctable
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

SAMPLER = 44
ST = 1712
S_R, S_LINK, S_RVALID = 4, 49, 50       # in a voice's sampler state: the right channel's frames, what a take is, a right channel this block
TAKE_KNOB = 7                           # knob G, as a turn names it
FIRST_MODE = 6                          # knob F: where MODE was on the first page
PEAK_AT = mm.SHARED + m.TIMED_BOX + 4   # the window's long the audio CPU says its peak with
SEQ = 0x0106
KNOBS = dict(tune=TUNE, sample=SAMPLE, start=START, length=LENGTH, loop=LOOP, mode=MODE, decay=DECAY)
# Every sample of the fade image's pool as a mono sample: in the first slot of a pair, the second empty.
ALONE = {2 * k: v for k, v in POOL.items()}


@pytest.fixture(scope="module")
def stock(official):
    return official.section(7)


@pytest.fixture(scope="module")
def stock3(official):
    assert official.version == "1.42"
    return official.section(3)


@pytest.fixture(scope="module")
def auto(stock):
    return build_engine.patched_image(stock, auto=True)


@pytest.fixture(scope="module")
def gain7(stock):
    """The gain image's engine: the stereo image's with the sum of twelve."""
    return build_engine.patched_image(stock, stereo=True, twelve=True)


@pytest.fixture(scope="module")
def time12(stock):
    return build_engine.patched_image(stock, timed=True, twelve=True)


@pytest.fixture(scope="module")
def main(stock3):
    return build_main.patched_image(stock3, auto=True)


@pytest.fixture(scope="module")
def before(stock3):
    return build_main.patched_image(stock3, gain=True)


@pytest.fixture(autouse=True)
def folded(monkeypatch):
    monkeypatch.setattr(P, "HookEngine", Folded)


def start(built, pool, track=0, note=60, **knobs):
    e = P.engine(built, pool=pool)
    for t in range(m.N_VOICES):
        e.set_slot(t, SAMPLE, 64 + 63)                  # the other tracks point at an empty slot
    values = {TUNE: 64, SAMPLE: 64, START: 0, LENGTH: 127, LOOP: 0, MODE: 0, DECAY: 127}
    values.update({KNOBS[k]: v for k, v in knobs.items()})
    for slot, v in values.items():
        e.set_slot(track, slot, v)
    e.set_note(track, note)
    return e


def play(built, pool, script, track=0, note=60, **knobs):
    """A note, then one block for each (STRT, LEN) of the script, the knobs set before it.
    -> (engine, left, right) from the block the note starts in."""
    e = start(built, pool, track, note, **knobs)
    out = [e.block(trig=1 << track), e.block()]
    for st, ln in script:
        e.set_slot(track, START, st)
        e.set_slot(track, LENGTH, ln)
        out.append(e.block())
    out = np.array(out)
    assert not out[0].any()
    return e, out[1:, track, :].ravel(), out[1:, track + 1, :].ravel()


def model(e, pool, script, track=0, xfade=False, **knobs):
    p = ref.Player(pool, fade=True, live=True, floor=True, hq=12, auto=True, xfade=xfade)
    p.inc = e.player(track, 0)["inc"]
    p.note_on(sample=knobs.get("sample", 64), start=knobs.get("start", 0), length=knobs.get("length", 127), loop=knobs.get("loop", 0),
              mode=knobs.get("mode", 0))
    left, right = [], []
    for step in [None] + list(script):
        if step:
            p.move(*step)
        l, r = p.block()
        left += tail(l)
        right += tail(r) if r is not None else [0] * BLOCK
    return np.array(left), np.array(right), p


def as_it_was(knobs):
    """A case written for the images before: (the pool it means here, its knobs without MODE, whether it is stereo)."""
    two = knobs.get("mode") == 1
    return (POOL if two else ALONE), {k: v for k, v in knobs.items() if k != "mode"}, two


# ---- a sample plays as it did -----------------------------------------------------------------------------------

@pytest.mark.parametrize("n", range(len(SCRIPTS)))
def test_a_sample_plays_as_it_did(auto, gain7, n):
    """Every script of STRT and LEN the live image is held to, on the gain image's engine with MODE saying what the
    sample is, and here with MODE at nothing and the sample found for what it is. The same frames, both sides."""
    name = list(SCRIPTS)[n]
    knobs, script = SCRIPTS[name]
    note = (60, 53.3, 67)[n % 3]
    pool, mine, two = as_it_was(knobs)
    _, was_l, was_r = play(gain7, POOL, script, note=note, **knobs)
    e, left, right = play(auto, pool, script, note=note, **mine)
    assert np.array_equal(left, was_l) and np.array_equal(right, was_r) and np.any(left) and np.any(right) == two


@pytest.mark.parametrize("note", [60, 55.25, 31.5])
@pytest.mark.parametrize("case", range(len(CASES)))
def test_the_engine_is_the_reference_model_bit_for_bit(auto, case, note):
    pool, knobs, two = as_it_was(CASES[case])
    script = hold(knobs.get("start", 0), knobs.get("length", 127), 44)
    e, left, right = play(auto, pool, script, note=note, **knobs)
    want_l, want_r, p = model(e, pool, script, **knobs)
    assert np.array_equal(left, want_l) and np.array_equal(right, want_r) and np.any(left) and np.any(right) == two
    got = state(e)
    assert bool(got["playing"]) == p.playing and (not p.playing or (got["frame"], got["a"], got["b"], got["c"]) == (p.pos >> 12, p.pa, p.pb, p.pc))


@pytest.mark.parametrize("knobs", [dict(loop=1, start=10, length=70), dict(sample=63), dict(loop=2, start=20)])
def test_mode_no_longer_says_how_a_track_plays(auto, knobs):
    """The knob's two lowest values, and the source's bits above them: the same frames, whatever it says."""
    script = hold(knobs.get("start", 0), knobs.get("length", 127), 30)
    for pool, two in ((POOL, True), (ALONE, False)):
        got = [play(auto, pool, script, note=57.5, mode=mode, **knobs)[1:] for mode in (0, 1, 1 | src(9), src(15))]
        assert all(np.array_equal(g[0], got[0][0]) and np.array_equal(g[1], got[0][1]) for g in got)
        assert np.any(got[0][0]) and np.any(got[0][1]) == two


@pytest.mark.parametrize("second, two", [(1000, True), (999, False), (1001, False), (1, False), (0, False), (2000, False)])
def test_a_sample_is_stereo_when_its_second_slot_is_as_long_as_its_first(auto, second, two):
    """As long to the frame. A second slot that is shorter was no right channel before; one that is longer was,
    and is not now: two samples that happen to share a pair are two samples."""
    rng = np.random.default_rng(second)
    pool = {8: rng.integers(-30000, 30000, 1000).astype(np.int16), 9: rng.integers(-30000, 30000, second).astype(np.int16)}
    e, left, right = play(auto, pool, hold(0, 127, 12), track=2, note=60, sample=68)
    at = e.voice(2) + ST
    assert np.any(left) and np.any(right) == two and bool(e.mc.r32(at + S_R)) == two
    want_l, want_r, _ = model(e, pool, hold(0, 127, 12), track=2, sample=68)
    assert np.array_equal(left, want_l) and np.array_equal(right, want_r)


def test_past_the_32nd_sample_there_is_none(auto):
    for sample in (64 + 32, 127, 31, 0):
        e, left, right = play(auto, {k: POOL[0] for k in range(64)}, hold(0, 127, 6), sample=sample)
        assert not np.any(left) and not np.any(right) and not state(e)["playing"]
    for sample in (64 + 31, 32):                                            # the 32nd, forward and backwards
        assert np.any(play(auto, {k: POOL[0] for k in range(64)}, hold(0, 127, 6), sample=sample)[1])


def test_a_mono_sample_is_a_mono_voices_work(auto, gain7):
    """Instructions of the voice loop's call, eight voices and one of them playing three octaves down: the pair
    found mono costs what a track on MONO did, and less than the stereo one."""
    def cost(built, pool, **knobs):
        e = start(built, pool, note=24, **knobs)
        e.block(trig=1)
        for _ in range(3):
            e.block()
        n = e.mc.insns
        e.block()
        return e.mc.insns - n
    mono, two = cost(auto, ALONE, loop=1), cost(auto, POOL, loop=1)
    assert abs(mono - cost(gain7, POOL, loop=1, mode=0)) < 40 and abs(two - cost(gain7, POOL, loop=1, mode=1)) < 40
    assert two - mono > 1000                    # (the voice's own part. The right channel's four stages are the rest: none for a mono one)


# ---- a take is what MODE says -------------------------------------------------------------------------------------

@pytest.mark.parametrize("track", [0, 5, 7])
def test_with_the_bit_a_take_is_a_stereo_sample_as_every_take_was(auto, track):
    e = P.engine(auto)
    P.box(e)
    e.set_slot(track, MODE, P.REC | P.STEREO | src(3))
    data = P.hold(e, track=track, n=20)
    k = 2 * track
    assert P.is_take(P.taken(e, k), data, 0, 20) and P.is_take(P.taken(e, k + 1), data, 1, 20)
    assert P.untouched(e, but=(k, k + 1)) and e.mc.read(e.voice(track) + ST + S_LINK, 1)[0]


@pytest.mark.parametrize("track", [0, 5, 7])
def test_without_it_a_take_is_a_mono_sample_and_its_second_slot_holds_one_frame(auto, track):
    """What the feed sends is kept from the left side: it sends a mono take's sample on both. The second slot
    is the take's too, with one frame in it: a sample of another length, so no right channel."""
    e = P.engine(auto)
    P.box(e)
    k = 2 * track
    e.mc.w32(m.KEPT + 4 * k, 0x1234 ^ m.KEEP_MARK), e.mc.w32(m.KEPT + 4 * k + 4, 0x1234 ^ m.KEEP_MARK)
    e.set_slot(track, MODE, P.REC | src(1))
    data = P.hold(e, track=track, n=20)
    assert P.is_take(P.taken(e, k), data, 0, 20) and P.untouched(e, but=(k, k + 1))
    assert P.slot_entry(e, k + 1) == (1, m.REC_BASE + m.REC_STRIDE * (k + 1))
    assert e.mc.r32(m.KEPT + 4 * k) == 0 and e.mc.r32(m.KEPT + 4 * k + 4) == 0     # neither slot is on the drive
    assert not e.mc.read(e.voice(track) + ST + S_LINK, 1)[0]
    # played back: one channel, and no right channel is made, sent or paid for
    e.set_slot(track, MODE, 0)
    e.block(trig=1 << track)
    out = np.array([e.block() for _ in range(6)])
    heard = out[:, track].ravel().astype(np.float64)
    want = P.taken(e, k).astype(np.float64)
    assert max(np.corrcoef(heard[j:j + 5 * BLOCK], want[:5 * BLOCK])[0, 1] for j in range(BLOCK + 1)) > 0.99
    assert e.mc.r32(e.voice(track) + ST + S_R) == 0 and not e.mc.read(e.voice(track) + ST + S_RVALID, 1)[0]
    assert not out[:, [t for t in range(8) if t != track]].any() and e.mc.r32(m.R_MASK) == 0


def test_a_step_that_says_record_takes_what_the_tracks_mode_says(auto):
    """REC locked on to a step, the track's own REC off: mono without the bit, stereo with it."""
    for mode, want in ((0, 1), (P.STEREO, None)):
        e = P.engine(auto)
        P.box(e)
        e.set_slot(4, MODE, mode)
        e.set_slot(4, m.K_REC, m.REC_WORD_ON / 256)
        data = P.hold(e, track=4, n=12)
        assert P.is_take(P.taken(e, 8), data, 0, 12)
        assert P.slot_entry(e, 9)[0] == (want or P.slot_entry(e, 8)[0])


def test_one_kind_of_take_over_the_other(auto):
    e = P.engine(auto)
    P.box(e)
    e.set_slot(3, MODE, P.REC | P.STEREO)
    P.hold(e, track=3, n=10)
    assert P.slot_entry(e, 6)[0] == P.slot_entry(e, 7)[0] > 0
    e.set_slot(3, MODE, P.REC)
    data = P.hold(e, track=3, n=24, seed=4)
    assert P.is_take(P.taken(e, 6), data, 0, 24) and P.slot_entry(e, 7)[0] == 1
    e.set_slot(3, MODE, P.REC | P.STEREO)
    data = P.hold(e, track=3, n=8, seed=5)
    assert P.is_take(P.taken(e, 6), data, 0, 8) and P.is_take(P.taken(e, 7), data, 1, 8)


def test_a_mono_takes_second_slot_is_handed_to_the_drive_as_a_take_of_one_frame(auto):
    """The keep's requests (engine/keeptakes.c), answered for both slots: so a save writes the second with a
    header that says one frame, over whatever the drive had there."""
    e = P.engine(auto)
    P.box(e)
    e.set_slot(5, MODE, P.REC)
    data = P.hold(e, track=5, n=20)
    left = P.taken(e, 10)
    ok, n, got = K.ask(e, 10, 0)
    assert ok and n == len(left) and got == left.astype(">i2").tobytes()[:512]
    ok, n, got = K.ask(e, 11, 0)
    first = bytes(e.mc.read(m.REC_BASE + m.REC_STRIDE * 11, 2))
    assert ok and n == 1 and got == first + bytes(510) and len(data)
    for slot in (10, 11):                                                   # written: neither is offered again
        K.ask(e, slot, m.KEEP_DONE)
        assert K.ask(e, slot, 0)[1] == 0
    assert e.mc.r32(m.KEPT + 44) == 1 ^ m.KEEP_MARK


# ---- the feed ---------------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def rig(main):
    return GainFeed(*main)


def mono_of(window, frame, left, right, db):
    """The window after a block of a mono take's feed: both sides the two channels added and halved, then the gain."""
    half = (frame[:, left].astype(np.int64) >> 1) + (frame[:, right].astype(np.int64) >> 1)
    both = np.zeros_like(frame)
    both[:, left] = both[:, right] = half.astype(np.int32)
    return take_of(window, both, left, right, db)


@pytest.mark.parametrize("db", [0, 7, 24])
@pytest.mark.parametrize("track, n", [(0, 0), (3, 1), (7, 9), (2, 14), (5, 15)])
def test_with_the_bit_the_feed_is_the_gain_images_to_the_bit(rig, before, track, n, db):
    old = GainFeed(*before)
    frame, window = frames(seed=n) >> 5, junk(SEQ - 1)
    block = make_block(ALL, [0] * track + [REC | STEREO | src(n)] + [0] * (11 - track))
    gains = [db if t == track else 11 for t in range(8)]
    rig.reset(gains=gains)
    old.reset(gains=gains)
    _, after = rig.run(block, frame, window)
    assert after == old.run(block, frame, window)[1] == take_of(window, frame, *PLACE[n], db)


@pytest.mark.parametrize("db", [0, 7, 24])
@pytest.mark.parametrize("track, n", [(0, 0), (3, 1), (7, 9), (2, 14), (5, 15)])
def test_without_it_both_sides_are_the_two_added_and_halved(rig, track, n, db):
    """The main mix, the input, a track (one channel: itself, less its last bit), the FX track, the delay and reverb."""
    frame, window = frames(seed=n + 3) >> 4, junk(SEQ - 1)
    gains = [db if t == track else 2 for t in range(8)]
    rig.reset(gains=gains)
    _, after = rig.run(make_block(ALL, [0] * track + [REC | src(n)] + [0] * (11 - track)), frame, window)
    assert after == mono_of(window, frame, *PLACE[n], db)
    pair = np.frombuffer(after[ring_at(SEQ):ring_at(SEQ) + 4 * BLOCK], dtype=">i2").reshape(BLOCK, 2)
    assert np.abs(pair[:, 0].astype(int) - pair[:, 1]).max() <= 2           # the same on both sides (the dither is each side's own)
    if PLACE[n][0] != PLACE[n][1]:
        assert after != take_of(window, frame, *PLACE[n], db)


def test_a_mono_take_of_full_scale_on_both_sides_is_full_scale(rig):
    frame = np.zeros((BLOCK, mm.FRAME_CH), dtype=np.int32)
    frame[:, 0] = 0x7fffffff
    frame[:, 1] = 0x7fffffff
    window = junk(SEQ - 1)
    rig.reset(gains=[0] * 8)
    _, after = rig.run(make_block(ALL, [REC] + [0] * 11), frame, window)
    got = np.frombuffer(after[ring_at(SEQ):ring_at(SEQ) + 4 * BLOCK], dtype=">i2")
    assert got.min() >= 32766 and after == mono_of(window, frame, 0, 1, 0)
    frame[:, 1] = -0x80000000                                               # and two sides that are each other's opposite are nothing
    _, after = rig.run(make_block(ALL, [REC] + [0] * 11), frame, window)
    assert np.abs(np.frombuffer(after[ring_at(SEQ):ring_at(SEQ) + 4 * BLOCK], dtype=">i2").astype(int)).max() <= 1


# ---- the page ---------------------------------------------------------------------------------------------------

def page_of(main, track=0, mode=0, index=1):
    r = GainPage(main, track=track)
    r.mode = mode
    r.mc.w32(PAGE + mm.PAGE_INDEX, index)
    r.mc.write(PEAK_AT, b"P047")
    return r


@pytest.mark.parametrize("mode, word", [(0, "MONO"), (STEREO, "STER"), (REC | src(9), "MONO"), (REC | STEREO | src(15), "STER")])
def test_the_page_shows_what_a_take_is_in_the_lower_rows_third_place(main, mode, word):
    r = page_of(main, track=4, mode=mode)
    got = r.show()
    assert (85, 12, word) in got and (85, 0, "") in got                     # where a value goes; no name: the meter's bar is there
    assert (59, 12, "0dB") in got and [t for t in got if t[2] in ("SRC", "DEST", "REC", "BANK")] and not r.stray
    assert r.mode == mode and not r.changes


@pytest.mark.parametrize("peak", [b"P047", b"P000", b"P131", b"P999"])
def test_the_last_place_reads_the_audio_cpus_peak(main, peak):
    r = page_of(main)
    r.mc.write(PEAK_AT - 4, b"C012")                                        # the first number is not shown
    r.mc.write(PEAK_AT, peak)
    got = r.show()
    assert (111, 12, peak.decode()) in got and (111, 0, "") in got and not [t for t in got if t[2].startswith("C0")]


@pytest.mark.parametrize("seed", range(4))
def test_whatever_the_window_holds_the_last_place_is_a_letter_and_three_figures(main, seed):
    r = page_of(main)
    r.mc.write(PEAK_AT, bytes(np.random.default_rng(seed).integers(0, 256, 4, dtype=np.uint8)))
    (s,) = [s for x, y, s in r.show() if (x, y) == (111, 12)]
    assert len(s) == 4 and 0x40 <= ord(s[0]) < 0x60 and all(0x30 <= ord(ch) < 0x40 for ch in s[1:]) and not r.stray


def test_a_turn_of_knob_g_switches_the_bit_and_nothing_else(main):
    r = page_of(main, track=2, mode=REC | src(6))
    for steps, want in ((1, STEREO), (1, STEREO), (3, STEREO), (-1, 0), (-5, 0), (0, 0), (2, STEREO)):
        assert r.twist(TAKE_KNOB, steps) == 1 and r.mode == REC | src(6) | want and r.redrawn[-1] == PAGE
        assert (85, 12, "STER" if want else "MONO") in r.show()
    assert r.changes == [1, -1, 1] and not r.stray and not r.turned         # only when it changes; and stock's routine is not asked
    assert r.popped == [("MODE", "mode %d" % v) for v in (REC | src(6) | STEREO, REC | src(6), REC | src(6) | STEREO)]


def test_it_is_the_tracks_alone_and_goes_into_every_lock_of_mode(main):
    """A held step changes nothing: there is no lock of it. A lock of MODE from an image before carries the track's
    three now, so that it does nothing a track does not."""
    r = page_of(main, mode=src(2))
    r.locks = {3: src(2), 9: REC | STEREO | src(5), 40: STEREO | src(2)}
    r.hold(3, 9)
    r.twist(TAKE_KNOB, 1)
    assert r.mode == STEREO | src(2) and r.locks == {3: STEREO | src(2), 9: STEREO | src(2), 40: STEREO | src(2)}
    assert not r.rec_locks and not r.edited
    r.hold()
    r.twist(TAKE_KNOB, -1)
    r.twist(SRC_KNOB, 2)
    r.twist(REC_KNOB, 1)
    assert r.mode == REC | src(4) and set(r.locks.values()) == {REC | src(4)}


def test_the_first_pages_sixth_place_is_empty_and_a_turn_of_it_is_nothing(main, before):
    r = page_of(main, mode=STEREO | src(3), index=0)
    assert [r.ask(k) for k in range(9)] == [400 + k if k != FIRST_MODE - 1 else 0 for k in range(9)]
    assert r.twist(FIRST_MODE, 3) == 1 and r.twist(FIRST_MODE, -3) == 1 and r.mode == STEREO | src(3) and not r.changes and not r.turned
    assert r.twist(3, 2) == r.turn_answer and len(r.turned) == 1            # every other knob there is stock's
    assert not [t for t in r.show() if t[2] in ("MONO", "STER", "P047")]    # and nothing of the sampling page is drawn
    old = GainPage(before)                                                  # (the gain image: MODE was that knob)
    old.mc.w32(PAGE + mm.PAGE_INDEX, 0)
    assert old.ask(FIRST_MODE - 1) == 400 + FIRST_MODE - 1 and old.twist(FIRST_MODE, 1) == 1 and old.mode == STEREO


def test_the_other_knobs_of_the_page_are_what_they_were(main, before):
    r, old = page_of(main, track=6), GainPage(before, track=6)
    old.mc.write(PEAK_AT, b"P047")
    for knob, steps in ((SRC_KNOB, 3), (2, 5), (REC_KNOB, 1), (GAIN_KNOB, 9), (SRC_KNOB, -1), (4, 1), (REC_KNOB, -1)):
        assert r.twist(knob, steps) == old.twist(knob, steps) and r.mode == old.mode and r.gains == old.gains
        assert [t for t in r.show() if t[0] < 85 or t[1] > 12] == [t for t in old.show() if t[0] < 85 or t[1] > 12]
    assert (59, 12, words(9)) in r.show()


def test_another_machine_has_one_page_and_all_its_knobs(main):
    other = MeterRig(main, {1: 4}, track=1, index=0)
    assert [other.ask(k) for k in range(9)] == [400 + k for k in range(9)] and other.pages == 1
    assert other.twist(TAKE_KNOB, 5) == other.turn_answer and other.twist(FIRST_MODE, 5) == other.turn_answer


# ---- what SMPL reads, and what a new track is ---------------------------------------------------------------------

def test_smpl_reads_the_samples_name_whatever_mode_says(main):
    """The first slot's name without its side, for a stereo sample and for a mono one, and MODE is not asked."""
    import test_screen as S
    names = {1: "KICK L", 2: "KICK R", 3: "ALONE", 5: "TAKE 03 L", 6: "TAKE 03 R", 8: "ONLY SECOND", 63: "LAST_L"}
    shown = {1: "KICK", 2: "ALONE", 3: "TAKE 03", 32: "LAST"}
    for mode in (0, 1, 2, 3 | 9 << 2, 15 << 2):
        s = S.Screen(main, mode, names)
        for n in range(1, 65):
            for reverse in (False, True):
                assert s.text(S.SMPL, S.knob_value(n, reverse)) == (shown.get(n, S.NO_SAMPLE) if n <= 32 else S.NO_SAMPLE), (mode, n, reverse)
        assert [S.stock_number(value) for _, value in s.slot_texts] == [2 * n - 1 for n in range(1, 33) for _ in range(2)]
        assert not s.valued and not s.stray


def test_a_new_tracks_takes_are_stereo(official, main, before):
    """MODE's descriptor: 0, MONO, was what a new sampler track had, when the word was how it played. Every take
    was a stereo sample then, and a new track's still is."""
    def default(image):
        return [p for p in params.load(image, "1.42") if p.type == SAMPLER and p.slot == MODE][0].default
    assert default(main[0]) == 1 and default(before[0]) == 0
    at = mm.off(mm.SAMP_RECORDS + build_main.REC * 5 + build_main.F_DEFAULT)
    assert main[0][at:at + 4] == (0x100).to_bytes(4, "big") and before[0][at:at + 4] == bytes(4)


# ---- the programs, and the image ----------------------------------------------------------------------------------

def test_section_7_is_the_time12_images_but_for_our_code(stock, auto, time12):
    """The same runs of code, the same pointers into them: no new run, and nothing of stock's touched that was not."""
    image, syms = auto
    runs = dict(m.CAVES, **m.REC_CAVES, **m.FADE_CAVES, **m.LIVE_CAVES, **m.PITCH_CAVES, **m.ONE_CAVES, **m.QUICK_CAVES)
    runs.update(m.LEAN_CAVES, **{k: v for k, v in m.TIMED_CAVES.items() if k != "m"})
    spans = list(runs.values()) + [(a, a + 4) for a in (m.UPDATE_TABLE + 4 * m.TWIN_ENGINE, m.RENDER_TABLE + 4 * m.TWIN_ENGINE,
                                                         m.ISR_VOICE_LOOP_CALL + 2, m.ISR_AMP_CALL + 2)]
    for other in (stock, time12[0]):
        diff = [m.BASE + k for k in range(len(image)) if image[k] != other[k]]
        assert diff and all(any(a <= d < b for a, b in spans) for d in diff)
    lo, hi = m.SPARE_RUNS[1]
    assert image[m.off(lo):m.off(hi)] == stock[m.off(lo):m.off(hi)]         # the one small run left is still stock's
    assert m.u32(image, m.ISR_VOICE_LOOP_CALL + 2) == syms["timed_hook"] and m.u32(image, m.ISR_AMP_CALL + 2) == syms["timed_amp"]
    assert "locate" not in syms and "locate" in time12[1]                   # the walk from slot to slot is gone, for room


def test_the_image_holds_a_rows_twelve_numbers_and_the_engine_makes_the_same_table_of_them(auto, time12):
    """The two numbers at each end of a row of twelve are 0 and no sum reads them: the image does not hold them,
    and the copy's are left as the memory has them."""
    image, syms = auto
    at = m.off(syms["hq_rows"])
    held = np.frombuffer(image[at:at + 2 * 17 * 12], dtype=">i2").reshape(17, 12)
    assert np.array_equal(held, np.array(sinctable.stored(True))[:, 2:14])
    e = P.engine(auto, pool=POOL)
    e.mc.write(m.HQ_LONGS, b"\x5a" * (33 * 64))
    e.block()
    got = np.frombuffer(bytes(e.mc.read(m.HQ_LONGS, 33 * 64)), dtype=">i4").reshape(33, 16)
    assert np.array_equal(got[:, 2:14], np.array(sinctable.rows12())[:, 2:14] << 15)
    assert np.all(got[:, :2] == 0x5a5a5a5a) and np.all(got[:, 14:] == 0x5a5a5a5a)
    assert e.mc.r32(m.HQ_MADE) == sinctable.magic(True)


def test_section_3_is_the_gain_images_but_for_the_feed_the_page_the_text_and_a_default(main, before):
    image, syms = main
    spans = [mm.CAVE_PAGE, mm.CAVE_PAGE2, mm.CAVE_PAGE3, mm.CAVE_PAGE4, mm.CAVE_METER, mm.CAVE_AMUTE, mm.CAVE_REC, mm.CAVE_TEXT]
    spans += [(mm.SYN_CLASS + k, mm.SYN_CLASS + k + 4) for k in (mm.PAGE_KNOB_METHOD, mm.PAGE_DRAW_METHOD, mm.PAGE_TURN_METHOD)]
    spans += [(mm.SYN_SIDE + mm.SYN_SIDE_TURN, mm.SYN_SIDE + mm.SYN_SIDE_TURN + 4), (mm.MIX_CALL + 2, mm.MIX_CALL + 6),
              (mm.TRIG_MUTE + 2, mm.TRIG_MUTE + 6), (mm.HOLD_WRITE + 2, mm.HOLD_WRITE + 6), (mm.SYN_BUILD + 6, mm.SYN_BUILD + 10),
              (mm.TEXT_SLOT_SITE + 2, mm.TEXT_SLOT_SITE + 6)]
    default = mm.SAMP_RECORDS + build_main.REC * 5 + build_main.F_DEFAULT
    spans.append((default, default + 4))
    diff = [mm.BASE + k for k in range(len(image)) if image[k] != before[0][k]]
    assert diff and all(any(a <= d < b for a, b in spans) for d in diff), [hex(d) for d in diff if not any(a <= d < b for a, b in spans)][:8]
    assert syms["meter_vars"] == mm.METER_PAGE and mm.CAVE_PAGE4[0] <= syms["take_place"] < mm.CAVE_PAGE4[1]
    assert "knob" not in syms or syms["knob"] != before[1].get("knob")


def test_the_images(official_path, official, auto, main):
    """The mode image: the two programs above. Its page without the peak is the same program less one place."""
    quiet = lambda s: None
    raw, _, built, regions, syms = build.build(official_path, log=quiet, auto=True)
    assert sorted(regions) == [3, 7] and built.section(7) == auto[0] and built.section(3) == main[0]
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
    plain = build_main.patched_image(official.section(3), auto=True, peak=False)
    r = page_of(plain, mode=STEREO)
    got = r.show()
    assert (85, 12, "STER") in got and not [t for t in got if t[0] == 111 and t[1] < 20]
