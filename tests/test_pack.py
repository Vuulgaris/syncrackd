"""The "pack" image: mono samples in single slots at the back.

On request





.

So (engine/sampler.h, PACK):
  - SMPL's 64 numbers are 64 places. 1 to 32 are the stereo samples as they were, number n in Transfer's slots
    2n - 1 and 2n. 33 to 64 are the slots of those numbers, each a mono sample whatever the slot after it holds:
    the number says which kind a place is, and nothing is found out from what two slots hold;
  - a take lands in the place it is sent to. In a stereo place it is what MODE says, as on the mode image. In a
    single slot it is half of the source's two sides added, whatever MODE says, and nothing of the slot after it
    is written: not its frames, not its line of the table, not its mark;
  - DEST on the sampling page goes to 64, and SMPL past 32 reads the slot's own name.

What is held here, in emulation:
  - the 32 stereo places play the frames the cross image plays, and a single slot plays the frames the cross image
    plays of the same sample alone in a stereo place;
  - the engine is the reference model (emu/sampler_ref.py, pack=True);
  - the routine a take is made by, which is written by hand on this image: against the cross image's for a stereo
    place's takes, block for block through a stalled feed, a feed ahead, a ring overrun, a full buffer, a note let
    go and a new trig; and for a single slot's take against the stereo take of the same feed;
  - the page's DEST, the knob's text, and that the two programs differ from the cross image's only where meant.

Not held: anything on the unit.
"""
import shutil

import numpy as np
import pytest

import test_keep as K
import test_pagerec as P
import test_screen as S
from emu import sampler_ref as ref
from emu.engine import BLOCK
from test_cross import LOOPS, costs, cycle
from test_fade import LENGTH, LOOP, MODE, POOL, SAMPLE, START, tail
from test_gain import GainPage
from test_live import SCRIPTS, hold, state
from test_meter import src
from test_mode import ST, S_LINK, S_R, as_it_was, play
from test_page import PAGE
from test_quick import Folded
from tools import audiomap as m
from tools import build, build_engine, build_main, params
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

S_STEREO, S_REC, S_RK, S_RSEQ, S_RPOS = 48, 51, 52, 54, 56      # in a voice's sampler state
SINGLE = 0x80                           # what `link` holds while a single slot's take runs
SINGLES = 32                            # the first place that is a single slot
DEST_KNOB = 2                           # the sampling page's second knob, as a turn names it


@pytest.fixture(scope="module")
def stock(official):
    return official.section(7)


@pytest.fixture(scope="module")
def stock3(official):
    assert official.version == "1.42"
    return official.section(3)


@pytest.fixture(scope="module")
def pack(stock):
    return build_engine.patched_image(stock, pack=True)


@pytest.fixture(scope="module")
def cross(stock):
    return build_engine.patched_image(stock, cross=True)


@pytest.fixture(scope="module")
def main(stock3):
    return build_main.patched_image(stock3, pack=True)


@pytest.fixture(scope="module")
def before(stock3):
    """The mode image's main program, which the cross image has too."""
    return build_main.patched_image(stock3, auto=True)


@pytest.fixture(scope="module")
def factory(official):
    return {p.slot: p.default for p in params.load(official.section(3), official.version) if p.type in (47, 45)}


@pytest.fixture(autouse=True)
def folded(monkeypatch):
    monkeypatch.setattr(P, "HookEngine", Folded)


def knob_of(place, reverse=False):
    """SMPL's value for a place, 0 to 63, on either half of the knob."""
    return 63 - place if reverse else 64 + place


def model(e, pool, script, track=0, **knobs):
    p = ref.Player(pool, fade=True, live=True, floor=True, hq=12, xfade=True, pack=True)
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


def noise(n, seed):
    return np.random.default_rng(seed).integers(-30000, 30000, n).astype(np.int16)


# ---- the 32 stereo places are what they were -----------------------------------------------------------------------

@pytest.mark.parametrize("n", range(len(SCRIPTS)))
def test_a_stereo_place_plays_the_cross_images_frames(pack, cross, n):
    """Every script of STRT and LEN the live image is held to, a stereo sample or a mono one in a stereo place."""
    name = list(SCRIPTS)[n]
    knobs, script = SCRIPTS[name]
    note = (60, 53.3, 67)[n % 3]
    pool, mine, two = as_it_was(knobs)
    _, was_l, was_r = play(cross, pool, script, note=note, **mine)
    e, left, right = play(pack, pool, script, note=note, **mine)
    assert np.array_equal(left, was_l) and np.array_equal(right, was_r) and np.any(left) and np.any(right) == two


@pytest.mark.parametrize("note", [60, 53.3])
@pytest.mark.parametrize("name", list(LOOPS))
def test_a_loops_seam_is_the_cross_images(pack, cross, name, note):
    pool, knobs, _ = LOOPS[name]
    script = hold(knobs.get("start", 0), knobs.get("length", 127), 70)
    _, was_l, was_r = play(cross, pool, script, note=note, **knobs)
    e, left, right = play(pack, pool, script, note=note, **knobs)
    assert np.array_equal(left, was_l) and np.array_equal(right, was_r) and np.any(left)


# ---- a single slot is a mono sample ---------------------------------------------------------------------------------

@pytest.mark.parametrize("after", ["as long", "longer", "nothing"])
@pytest.mark.parametrize("place", [32, 33, 40, 47, 62, 63])
def test_a_single_slot_is_a_mono_sample_whatever_the_slot_after_it_holds(pack, cross, place, after):
    """A slot of the back half by its own number: the frames the cross image plays of the same sample alone in a
    stereo place, no right channel made, and the reference model's. With a slot after it that is as long to the
    frame, which in a stereo place is a right channel."""
    if place == 63 and after != "nothing":
        pytest.skip("there is no slot after the last")
    data = noise(1500, place)
    pool = {place: data}
    if after != "nothing":
        pool[place + 1] = noise(1500 if after == "as long" else 1700, place + 100)
    knobs = dict(loop=1, start=20, length=60)
    script = hold(20, 60, 60)
    e, left, right = play(pack, pool, script, note=55.25, sample=knob_of(place), **knobs)
    assert np.any(left) and not np.any(right) and e.mc.r32(e.voice(0) + ST + S_R) == 0
    _, was_l, was_r = play(cross, {0: data}, script, note=55.25, **knobs)
    assert np.array_equal(left, was_l) and not np.any(was_r)
    want_l, want_r, p = model(e, pool, script, sample=knob_of(place), **knobs)
    assert np.array_equal(left, want_l) and not np.any(want_r) and p.r is None
    got = state(e)
    assert bool(got["playing"]) == p.playing and (got["frame"], got["a"], got["b"], got["c"]) == (p.pos >> 12, p.pa, p.pb, p.pc)


@pytest.mark.parametrize("knobs", [dict(), dict(loop=2, start=40, length=50), dict(loop=1, start=0, length=127), dict(start=64, length=20)])
@pytest.mark.parametrize("place, reverse", [(35, False), (35, True), (63, True), (32, False)])
def test_the_engine_is_the_reference_model_in_a_single_slot(pack, place, reverse, knobs):
    pool = {k: noise(1300, k) for k in (place - 1, place, place + 1) if k < 64}
    script = hold(knobs.get("start", 0), knobs.get("length", 127), 40)
    e, left, right = play(pack, pool, script, note=62.5, sample=knob_of(place, reverse), **knobs)
    want_l, want_r, _ = model(e, pool, script, sample=knob_of(place, reverse), **knobs)
    assert np.array_equal(left, want_l) and np.any(left) and not np.any(right) and not np.any(want_r)


@pytest.mark.parametrize("reverse", [False, True])
def test_every_number_of_the_knob_is_its_own_place(pack, reverse):
    """All 64 slots hold a sample of one length, the worst there is for telling a pair from two. 1 to 32: the two
    slots 2n - 1 and 2n. 33 to 64: the slot of that number and no right channel."""
    pool = {k: noise(600, k) for k in range(64)}
    e = P.engine(pack, pool=pool)
    table = [P.slot_entry(e, k)[1] for k in range(64)]
    seen = {}
    for first in range(0, 64, 8):
        for t in range(8):
            e.set_slot(t, SAMPLE, knob_of(first + t, reverse))
        e.block(trig=0xff)
        e.block()
        for t in range(8):
            at = e.voice(t) + ST
            seen[first + t] = (e.mc.r32(at), e.mc.r32(at + S_R))
    assert seen == {p: (table[2 * p], table[2 * p + 1]) if p < SINGLES else (table[p], 0) for p in range(64)}


def test_a_single_slot_costs_a_mono_voices_work(pack):
    """Instructions of the voice loop's call with one voice playing three octaves down: a single slot's, a mono
    sample's in a stereo place, and a stereo sample's."""
    def cost(pool, place):
        e = P.engine(pack, pool=pool)
        for t in range(1, m.N_VOICES):
            e.set_slot(t, SAMPLE, 64 + 31)
        for slot, v in ((SAMPLE, knob_of(place)), (LOOP, 1)):
            e.set_slot(0, slot, v)
        e.set_note(0, 24)
        e.block(trig=1)
        for _ in range(3):
            e.block()
        n = e.mc.insns
        e.block()
        return e.mc.insns - n
    data = noise(4000, 3)
    single, alone, two = cost({40: data, 41: data}, 40), cost({0: data}, 0), cost({0: data, 1: data}, 0)
    assert abs(single - alone) < 40 and two - single > 1000


# ---- a take lands in its place ---------------------------------------------------------------------------------------

def half(data, n):
    """What a single slot's take holds of n blocks fed: half of the two sides added."""
    return ((data[:n + 1, :, 0].astype(np.int64) + data[:n + 1, :, 1]) >> 1).ravel()


def is_half(got, data, n):
    want = half(data, n)
    return (n - 2) * BLOCK <= len(got) <= (n + 1) * BLOCK and np.array_equal(got, want[len(want) - len(got):])


def buf(k):
    return m.REC_BASE + m.REC_STRIDE * k


def fence(e, k, frames=777):
    """Slot k as a kept sample of its own in its buffer, the buffer's ends marked. -> what must still be there."""
    e.mc.w32(m.SLOT_LEN + 8 * k, frames)
    e.mc.w32(m.SLOT_PTR + 8 * k, buf(k))
    e.mc.w32(m.KEPT + 4 * k, frames ^ m.KEEP_MARK)
    for at in (buf(k), buf(k) + m.REC_STRIDE - 0x1000):
        e.mc.write(at, bytes(range(256)) * 16)
    return lambda: (P.slot_entry(e, k) == (frames, buf(k)) and e.mc.r32(m.KEPT + 4 * k) == frames ^ m.KEEP_MARK
                    and all(bytes(e.mc.read(at, 0x1000)) == bytes(range(256)) * 16 for at in (buf(k), buf(k) + m.REC_STRIDE - 0x1000)))


@pytest.mark.parametrize("mode", [P.REC, P.REC | P.STEREO | src(3)])
@pytest.mark.parametrize("place", [32, 41, 62, 63])
def test_a_take_in_a_single_slot_is_half_of_the_two_sides_and_touches_that_slot_alone(pack, place, mode):
    """Whatever MODE says. The slots either side hold samples of their own, kept, with their buffers marked: their
    lines of the table, their marks and their buffers are as they were. Past the last slot's buffer too."""
    e = P.engine(pack)
    P.box(e)
    track = 3
    e.set_slot(track, SAMPLE, knob_of(place))
    kept = [fence(e, k) for k in (place - 1, place + 1) if k < 64]
    past = buf(64)
    e.mc.write(past, b"\xa5" * 0x1000)
    e.mc.w32(m.KEPT + 4 * place, 0x1234 ^ m.KEEP_MARK)
    e.set_slot(track, MODE, mode)
    data = P.hold(e, track=track, n=20)
    assert is_half(P.taken(e, place), data, 20) and all(ok() for ok in kept)
    assert P.untouched(e, but=(place - 1, place, place + 1)) and bytes(e.mc.read(past, 0x1000)) == b"\xa5" * 0x1000
    assert e.mc.r32(m.KEPT + 4 * place) == 0                                # the take is not on the drive
    assert e.mc.read(e.voice(track) + ST + S_LINK, 1)[0] == SINGLE


@pytest.mark.parametrize("track, place", [(0, 0), (5, 16), (7, 31)])
def test_a_take_in_a_stereo_place_is_what_mode_says_as_it_was(pack, track, place):
    """In the back half's slots too: place 17 is slots 33 and 34 of Transfer, a stereo sample when it is used as one."""
    k = 2 * place
    for mode, second in ((P.REC | P.STEREO, None), (P.REC | src(1), 1)):
        e = P.engine(pack)
        P.box(e)
        e.set_slot(track, SAMPLE, knob_of(place))
        e.set_slot(track, MODE, mode)
        data = P.hold(e, track=track, n=20)
        assert P.is_take(P.taken(e, k), data, 0, 20) and P.untouched(e, but=(k, k + 1))
        if second:
            assert P.slot_entry(e, k + 1) == (1, buf(k + 1))
        else:
            assert P.is_take(P.taken(e, k + 1), data, 1, 20)
        assert e.mc.read(e.voice(track) + ST + S_LINK, 1)[0] == (0 if second else 1)
        assert e.mc.r32(m.KEPT + 4 * k) == 0 and e.mc.r32(m.KEPT + 4 * k + 4) == 0


@pytest.mark.parametrize("dest, slots", [(0, (0, 1)), (31, (62, 63)), (32, (32,)), (40, (40,)), (63, (63,))])
def test_dest_names_a_place(pack, dest, slots):
    e = P.engine(pack)
    P.box(e, {2: dest})
    e.set_slot(2, MODE, P.REC | P.STEREO)
    data = P.hold(e, track=2, n=12)
    if len(slots) == 2:
        assert P.is_take(P.taken(e, slots[0]), data, 0, 12) and P.is_take(P.taken(e, slots[1]), data, 1, 12)
    else:
        assert is_half(P.taken(e, slots[0]), data, 12)
    assert P.untouched(e, but=slots)


@pytest.mark.parametrize("dest", [64, 65, 200, 0xfffe])
def test_a_number_that_is_no_place_means_smpl(pack, dest):
    e = P.engine(pack)
    P.box(e, {2: dest})
    e.set_slot(2, MODE, P.REC | P.STEREO)
    P.hold(e, track=2, n=8)
    assert P.slot_entry(e, 4)[0] and P.slot_entry(e, 5)[0] and P.untouched(e, but=(4, 5))


def test_two_single_takes_of_one_length_side_by_side_are_two_mono_samples(pack):
    """What length could not tell from a stereo pair. Each plays alone at its own number; and the stereo place
    those two slots are, 21, takes them for a stereo sample: the knob's number says which."""
    e = P.engine(pack)
    P.box(e)
    for place, seed in ((40, 1), (41, 2)):
        e.set_slot(1, SAMPLE, knob_of(place))
        e.set_slot(1, MODE, P.REC)
        P.hold(e, track=1, n=16, seed=seed)
    assert P.slot_entry(e, 40)[0] == P.slot_entry(e, 41)[0] > 0
    e.set_slot(1, MODE, 0)
    at = e.voice(1) + ST
    for place in (40, 41):
        e.set_slot(1, SAMPLE, knob_of(place))
        e.block(trig=2)
        out = np.array([e.block() for _ in range(4)])
        assert (e.mc.r32(at), e.mc.r32(at + S_R)) == (buf(place), 0) and out[:, 1].any() and not out[:, 2].any()
    e.set_slot(1, SAMPLE, knob_of(20))
    e.block(trig=2)
    e.block()
    assert (e.mc.r32(at), e.mc.r32(at + S_R)) == (buf(40), buf(41))


def test_a_single_slots_take_is_handed_to_the_drive_alone(pack):
    """The keep's requests (engine/keeptakes.c), a slot each: the take's slot has a take, the slot after it has
    none to give."""
    e = P.engine(pack)
    P.box(e)
    e.set_slot(5, SAMPLE, knob_of(50))
    e.set_slot(5, MODE, P.REC | P.STEREO)
    P.hold(e, track=5, n=20)
    took = P.taken(e, 50)
    ok, n, got = K.ask(e, 50, 0)
    assert ok and n == len(took) and got == took.astype(">i2").tobytes()[:512]
    assert K.ask(e, 51, 0)[1] == 0 and K.ask(e, 49, 0)[1] == 0
    K.ask(e, 50, m.KEEP_DONE)
    assert K.ask(e, 50, 0)[1] == 0 and e.mc.r32(m.KEPT + 4 * 50) == len(took) ^ m.KEEP_MARK


# ---- the routine a take is made by, written by hand here ---------------------------------------------------------------

TRACK = 4
# a block of the audio CPU each: (blocks the feed puts in the ring before it, a trig, the note let go, frames taken to jump to)
TAKES = ([(1, 1, 0, None)] + [(1, 0, 0, None)] * 5                          # a take begins
         + [(0, 0, 0, None)] * 2 + [(3, 0, 0, None), (1, 0, 0, None)]       # the feed stalls, then is three ahead
         + [(8, 0, 0, None), (1, 0, 0, None)]                               # a whole ring ahead: still nothing lost
         + [(9, 0, 0, None), (1, 0, 0, None), (1, 0, 0, None)]              # more than a ring: the take ends
         + [(1, 1, 0, None), (1, 0, 0, None), (1, 0, 0, m.REC_MAX - 3 * BLOCK)]     # a new take, then nearly a full buffer
         + [(1, 0, 0, None)] * 5                                            # which fills, and the take ends
         + [(1, 1, 0, None)] + [(1, 0, 0, None)] * 3 + [(1, 0, 1, None)] + [(1, 0, 0, None)] * 2     # a new take, and the note let go
         + [(2, 1, 0, None), (1, 0, 0, None), (1, 1, 0, None), (2, 0, 0, None), (1, 0, 1, None), (1, 0, 0, None)])   # a trig over a take


# What that is, in blocks the take holds after each (a trig acts a block after it is set): five blocks; a stalled feed adds
# nothing; three at once; eight at once, the whole ring; nine, and the take ends where it was; a new one, jumped to two
# blocks short of full, fills and ends; a new one ends where its note is let go; a trig over a running take begins again.
FULL = m.REC_MAX // BLOCK
STORY = ([0, 1, 2, 3, 4, 5, 5, 5, 8, 9, 17, 18, 18, 18, 18, 18, 1, FULL - 2, FULL - 1] + [FULL] * 5
         + [1, 2, 3, 4, 4, 4, 4, 1, 2, 1, 2, 2])
RUNNING = [0] + [1] * 11 + [0] * 4 + [1] * 3 + [0] * 5 + [1] * 3 + [0] * 4 + [1] * 3 + [0] * 2


def takes(built, place, mode, fenced=()):
    """TAKES on a track with SMPL on a place. -> after every block the whole table, the marks, and the voice's take;
    then the engine."""
    e = P.engine(built)
    P.box(e)
    e.set_slot(TRACK, SAMPLE, knob_of(place))
    e.set_slot(TRACK, MODE, mode)
    kept = [fence(e, k) for k in fenced]
    feed = np.random.default_rng(21).integers(-32768, 32768, (sum(t[0] for t in TAKES), BLOCK, 2)).astype(np.int16)
    at, fed, seen = e.voice(TRACK) + ST, 0, []
    for blocks, trig, release, jump in TAKES:
        for _ in range(blocks):
            e.seq = (e.seq + 1) & 0xffff
            e.mc.write(m.MAILBOX + m.MAILBOX_RING + 4 * BLOCK * (e.seq % m.MAILBOX_BLOCKS), feed[fed].astype(">i2").tobytes())
            e.mc.write(m.MAILBOX, e.seq.to_bytes(2, "big"))
            fed += 1
        if jump is not None:
            e.mc.w32(at + S_RPOS, jump)                                     # test only
        e.block(trig << TRACK, release << TRACK)
        seen.append(([P.slot_entry(e, k) for k in range(64)], bytes(e.mc.read(m.KEPT, 4 * 64)),
                     e.mc.read(at + S_REC, 1)[0], e.mc.read(at + S_RK, 1)[0], bytes(e.mc.read(at + S_RSEQ, 6))))
        assert all(ok() for ok in kept)
    return seen, e


def frames_of(e, k, where):
    """Frames of slot k's buffer, a stretch at its start and one at its end."""
    return [np.frombuffer(bytes(e.mc.read(buf(k) + 2 * a, 2 * n)), dtype=">i2") for a, n in where]


WHERE = [(0, 40 * BLOCK), (m.REC_MAX - 4 * BLOCK, 4 * BLOCK)]


@pytest.mark.parametrize("mode", [P.REC | P.STEREO, P.REC])
@pytest.mark.parametrize("place", [3, 20, 31])
def test_a_stereo_places_takes_are_the_cross_images_block_for_block(pack, cross, place, mode):
    """The table, the marks and the voice's own count after every block, and the frames in both buffers."""
    was, old = takes(cross, place, mode)
    now, e = takes(pack, place, mode)
    assert now == was
    for k in (2 * place, 2 * place + 1):
        assert all(np.array_equal(a, b) for a, b in zip(frames_of(e, k, WHERE), frames_of(old, k, WHERE)))
    assert [table[2 * place][0] // BLOCK for table, *_ in now] == STORY     # and every way a take ends was gone through
    assert [rec for _, _, rec, _, _ in now] == RUNNING


@pytest.mark.parametrize("mode", [P.REC | P.STEREO, P.REC])
@pytest.mark.parametrize("place", [40, 63])
def test_a_single_slots_take_is_the_stereo_take_of_the_same_feed_added_and_halved(pack, place, mode):
    """The same blocks of the ring taken at the same moments as a stereo take of the stereo place this slot is the
    left of (41 is slots 41 and 42 of Transfer; 64 has none, so 32's right is read against it). The slot's line of
    the table and the voice's count after every block are the stereo take's; its frames are half of the two; and
    the slots either side, kept samples with marked buffers, are as they were after every block."""
    left = place & ~1
    two, old = takes(pack, left // 2, P.REC | P.STEREO)
    one, e = takes(pack, place, mode, fenced=[k for k in (place - 1, place + 1) if k < 64])
    for (t2, _, rec2, _, count2), (t1, _, rec1, rk, count1) in zip(two, one):
        assert t1[place][0] == t2[left][0] and (rec1, count1) == (rec2, count2)
        assert not t1[place][0] or (t1[place][1], rk) == (buf(place), place)
    l, r = frames_of(old, left, WHERE), frames_of(old, left + 1, WHERE)
    for got, a, b in zip(frames_of(e, place, WHERE), l, r):
        assert np.array_equal(got, (a.astype(np.int64) + b) >> 1) and np.any(got)


def test_full_scale_on_both_sides_is_full_scale_in_a_single_slot(pack):
    for value in (32767, -32768):
        e = P.engine(pack)
        P.box(e)
        e.set_slot(0, SAMPLE, knob_of(63))
        e.set_slot(0, MODE, P.REC)
        for b in range(6):
            P.fed(e, np.full((BLOCK, 2), value), trig=1 if b == 0 else 0)
        assert set(P.taken(e, 63).tolist()) == {value}


# ---- what it costs ------------------------------------------------------------------------------------------------------

def test_an_interrupt_costs_what_the_cross_images_did(pack, cross, factory):
    """Eight pitched stereo loops: a steady block is the cross image's to a few instructions (a test more where a
    pass begins), and the block eight notes start in is under 200 over it."""
    was = costs(cross[0], factory, 55.25, 80, start=30, length=40)
    now = costs(pack[0], factory, 55.25, 80, start=30, length=40)
    assert abs(int(np.median(now[60:])) - int(np.median(was[60:]))) < 40 and abs(max(now) - max(was)) < 200
    a, b = cycle(cross[0], factory, start=30, length=40), cycle(pack[0], factory, start=30, length=40)
    assert 0 <= b[0] - a[0] < 200 and abs(b[1] - a[1]) < 40 and abs(b[2] - a[2]) < 40


# ---- the page and the knob's text ------------------------------------------------------------------------------------------

def test_dest_goes_to_64_and_the_box_holds_the_place(main, before):
    r = GainPage(main, track=0)
    r.mc.w32(PAGE + mm.PAGE_INDEX, 1)
    r.show()
    for steps, want in ((6, 6), (26, 32), (1, 33), (40, 64), (5, 64), (-31, 33), (-1, 32), (-40, 0), (-3, 0), (64, 64)):
        assert r.twist(DEST_KNOB, steps) == 1 and r.dest == want
        word = "SMPL" if not want else "%02d" % want
        assert (59, 39, word) in r.show() and r.box[0] == (want - 1 if want else m.DEST_SMPL) and not r.stray
    old = GainPage(before, track=0)                                         # (the mode image's stops at the last stereo sample)
    old.mc.w32(PAGE + mm.PAGE_INDEX, 1)
    old.show()
    assert old.twist(DEST_KNOB, 50) == 1 and old.dest == 32


def test_smpl_reads_a_single_slots_own_name_whole(main, before):
    """1 to 32 as on the mode image: the first slot's name without its side. 33 to 64: the slot of that number,
    its name as it is, on either half of the knob."""
    names = {1: "KICK L", 2: "KICK R", 3: "ALONE", 33: "HAT", 40: "TAKE 20 R", 41: "LOOP_L", 63: "PAD L", 64: "LAST"}
    shown = {1: "KICK", 2: "ALONE", 17: "HAT", 21: "LOOP", 32: "PAD"}
    s = S.Screen(main, 1, names)
    for n in range(1, 65):
        for reverse in (False, True):
            want = shown.get(n, S.NO_SAMPLE) if n <= 32 else names.get(n, S.NO_SAMPLE)
            assert s.text(S.SMPL, S.knob_value(n, reverse)) == want, (n, reverse)
    assert [S.stock_number(value) for _, value in s.slot_texts] == [2 * n - 1 if n <= 32 else n for n in range(1, 65) for _ in range(2)]
    assert not s.valued and not s.stray
    old = S.Screen(before, 1, names)                                        # (the mode image: past 32 there was nothing)
    assert old.text(S.SMPL, S.knob_value(64)) == S.NO_SAMPLE and old.text(S.SMPL, S.knob_value(2)) == "ALONE"


# ---- the programs, and the image -------------------------------------------------------------------------------------------

def test_section_7_is_the_cross_images_but_for_our_code(stock, pack, cross):
    """The same runs of code and the same pointers into them: no new run, and nothing of stock's touched that was
    not. The routine of a take is the hand-written one, in the run the compiler's was in."""
    image, syms = pack
    runs = dict(m.CAVES, **m.REC_CAVES, **m.FADE_CAVES, **m.LIVE_CAVES, **m.PITCH_CAVES, **m.ONE_CAVES, **m.QUICK_CAVES)
    runs.update(m.LEAN_CAVES, **{k: v for k, v in m.TIMED_CAVES.items() if k != "m"}, **m.CROSS_CAVES)
    spans = list(runs.values()) + [(a, a + 4) for a in (m.UPDATE_TABLE + 4 * m.TWIN_ENGINE, m.RENDER_TABLE + 4 * m.TWIN_ENGINE,
                                                         m.ISR_VOICE_LOOP_CALL + 2, m.ISR_AMP_CALL + 2)]
    for other in (stock, cross[0]):
        diff = [m.BASE + k for k in range(len(image)) if image[k] != other[k]]
        assert diff and all(any(a <= d < b for a, b in spans) for d in diff)
    lo, hi = m.PITCH_CAVES["r"]
    assert lo == syms["rec_step"] == cross[1]["rec_step"] and image[m.off(lo):m.off(hi)] != cross[0][m.off(lo):m.off(hi)]
    assert m.u32(image, m.ISR_VOICE_LOOP_CALL + 2) == syms["timed_hook"] != cross[1]["timed_hook"]


def test_section_3_is_the_mode_images_but_for_the_page_and_the_text(main, before):
    image, _ = main
    spans = [mm.CAVE_PAGE, mm.CAVE_PAGE2, mm.CAVE_PAGE3, mm.CAVE_PAGE4, mm.CAVE_TEXT]
    spans += [(mm.SYN_CLASS + k, mm.SYN_CLASS + k + 4) for k in (mm.PAGE_KNOB_METHOD, mm.PAGE_DRAW_METHOD, mm.PAGE_TURN_METHOD)]
    spans += [(mm.SYN_SIDE + mm.SYN_SIDE_TURN, mm.SYN_SIDE + mm.SYN_SIDE_TURN + 4), (mm.SYN_BUILD + 6, mm.SYN_BUILD + 10),
              (mm.TEXT_SLOT_SITE + 2, mm.TEXT_SLOT_SITE + 6)]
    diff = [mm.BASE + k for k in range(len(image)) if image[k] != before[0][k]]
    assert diff and all(any(a <= d < b for a, b in spans) for d in diff), [hex(d) for d in diff if not any(a <= d < b for a, b in spans)][:8]


def test_the_image(official_path, official, pack, main):
    quiet = lambda s: None
    raw, _, built, regions, _ = build.build(official_path, log=quiet, pack=True)
    assert sorted(regions) == [3, 7] and built.section(7) == pack[0] and built.section(3) == main[0]
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
    cross = build.build(official_path, log=quiet, cross=True)[2]
    assert cross.section(7) != pack[0] and cross.section(3) != main[0]
