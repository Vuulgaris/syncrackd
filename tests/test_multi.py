"""The multi image: the alock image with several tracks recording at once, each from its own source.

The ring is no ring: its eight blocks are a block a track. The main CPU feeds every track that says record its own
source's block, and writes the count and the bits of the blocks it wrote as one long, last. The audio CPU takes a
track's block before the voice loop (engine/stub.S, rec_all), where the stops image took the ring's after it.

What is held here: a take is what the stops image's take of the same blocks is; eight tracks take eight blocks, each
its own; a block the main CPU writes while the voices run is taken whole, by the next interrupt, once; the feed's
blocks are the alock image's by the rule (tests/test_feed.py, spec), a track each; what a block of two, four and
eight takes costs the main CPU; and both programs differ from the images before only in their declared places.

Not held, and only the unit can show it: that the main CPU never writes a block while the audio CPU reads it. The
order is read from stock, not timed, and the emulator has no time.
"""
import shutil

import numpy as np
import pytest
from unicorn import UC_HOOK_CODE

import test_feed as F
import test_pack as PK
import test_pagerec as P
from emu.engine import BLOCK
from test_meter import ALL, REC, STEREO, src
from test_mode import ST
from test_quick import Folded
from test_recorder import P_MODE, STRIDE, frames, junk, make_block, ring_at
from tools import audiomap as m
from tools import build, build_engine, build_main
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

LANE = m.MAILBOX + m.MAILBOX_RING       # track t's block: 128 bytes on from the track's before
BITS = m.MAILBOX + 2                    # the blocks written with the count, a bit a track
RND = m.MAILBOX + 4
S_REC, S_RK, S_RPOS = PK.S_REC, PK.S_RK, PK.S_RPOS


@pytest.fixture(scope="module")
def stock(official):
    return official.section(7)


@pytest.fixture(scope="module")
def stock3(official):
    assert official.version == "1.42"
    return official.section(3)


@pytest.fixture(scope="module")
def multi(stock):
    return build_engine.patched_image(stock, multi=True)


@pytest.fixture(scope="module")
def stops(stock):
    return build_engine.patched_image(stock, stops=True)


@pytest.fixture(scope="module")
def main(stock3):
    return build_main.patched_image(stock3, xfade=7)


@pytest.fixture(scope="module")
def before(stock3):
    return build_main.patched_image(stock3, xfade=6)


@pytest.fixture(autouse=True)
def folded(monkeypatch):
    monkeypatch.setattr(P, "HookEngine", Folded)


# ---- the audio CPU: a block a track, before the voices --------------------------------------------------------------

def recorder(built, places, mode=P.REC | P.STEREO):
    """{track: place}: those tracks' SMPL on their places and REC on. mode: one for all, or {track: mode}."""
    e = P.engine(built)
    P.box(e)
    for t, place in places.items():
        e.set_slot(t, P.SAMPLE, PK.knob_of(place))
        e.set_slot(t, P.MODE, mode[t] if isinstance(mode, dict) else mode)
    return e


def write(e, count, blocks):
    """The window as the main CPU leaves it after a mixer call: a block a track that records, then count and bits."""
    bits = 0
    for t, x in blocks.items():
        e.mc.write(LANE + 4 * BLOCK * t, np.asarray(x).astype(">i2").tobytes())
        bits |= 1 << t
    e.mc.write(m.MAILBOX, (count & 0xffff).to_bytes(2, "big") + bits.to_bytes(2, "big"))


def taken(e, k, n):
    return np.frombuffer(bytes(e.mc.read(PK.buf(k), 2 * n)), dtype=">i2").astype(np.int16)


def state(e, t):
    at = e.voice(t) + ST
    return e.mc.read(at + S_REC, 1)[0], e.mc.read(at + S_RK, 1)[0], e.mc.r32(at + S_RPOS)


def noise(shape, seed):
    return np.random.default_rng(seed).integers(-32768, 32768, shape).astype(np.int16)


def test_eight_tracks_take_eight_blocks_each_its_own(multi):
    places = {t: 1 + 3 * t for t in range(8)}
    e = recorder(multi, places)
    feed = noise((12, 8, BLOCK, 2), 31)
    write(e, 7, {t: feed[0, t] for t in range(8)})
    e.block(0xff, 0)                                # the trigs; the notes start in the interrupt after, and the takes
    for b in range(1, 12):                          # begin with the one after that: the block written while they started
        write(e, 7 + b, {t: feed[b, t] for t in range(8)})
        e.block(0, 0)
    n = 10 * BLOCK
    for t, p in places.items():
        assert state(e, t) == (1, 2 * p, n)
        assert np.array_equal(taken(e, 2 * p, n), feed[2:, t, :, 0].ravel())
        assert np.array_equal(taken(e, 2 * p + 1, n), feed[2:, t, :, 1].ravel())
        assert [P.slot_entry(e, 2 * p + k) for k in (0, 1)] == [(n, PK.buf(2 * p)), (n, PK.buf(2 * p + 1))]


@pytest.mark.parametrize("track, place, mode", [(0, 3, P.REC | P.STEREO), (4, 20, P.REC), (7, 40, P.REC), (2, 63, P.REC | P.STEREO)])
def test_a_take_is_the_stops_images_take_of_the_same_blocks(multi, stops, track, place, mode):
    """A stereo place's take, a mono one's and a single slot's, nine blocks and the note let go: the table's every line,
    the marks of what is kept, the frames and the voice's own count."""
    feed = noise((9, BLOCK, 2), 40 + place)
    old = recorder(stops, {track: place}, mode)
    for b, x in enumerate(feed):
        P.fed(old, x, trig=(1 << track) if b == 0 else 0, release=(1 << track) if b == 8 else 0)
    new = recorder(multi, {track: place}, mode)
    new.block(1 << track, 0)
    for b, x in enumerate(feed):
        write(new, 100 + b, {track: x})
        new.block(0, (1 << track) if b == 8 else 0)
    assert [P.slot_entry(new, k) for k in range(64)] == [P.slot_entry(old, k) for k in range(64)]
    assert new.mc.read(m.KEPT, 4 * 64) == old.mc.read(m.KEPT, 4 * 64)
    assert state(new, track) == state(old, track) and state(new, track)[0] == 0
    k = place if place >= PK.SINGLES else 2 * place
    for s in (k, k + 1) if k < 63 else (k,):
        assert np.array_equal(taken(new, s, 10 * BLOCK), taken(old, s, 10 * BLOCK))


def test_a_block_written_while_the_voices_run_is_taken_whole_by_the_next_interrupt_and_once(multi):
    """The main CPU's place in a block: it writes after its mixer, while the audio CPU is at its voices or past them.
    Here every block is written as the voice loop is entered. On some blocks nothing is written: nothing is taken."""
    track, place = 5, 9
    e = recorder(multi, {track: place})
    feed = noise((14, BLOCK, 2), 52)
    skip, now = {4, 5, 9}, {"b": 0, "count": 300}

    def at_the_voices(uc, address, size, user):
        if now["b"] not in skip:
            now["count"] += 1
            write(e, now["count"], {track: feed[now["b"]]})

    e.mc.uc.hook_add(UC_HOOK_CODE, at_the_voices, begin=m.VOICE_LOOP, end=m.VOICE_LOOP)
    e.mc.uc.ctl_flush_tb()
    want = []
    for b in range(14):
        now["b"] = b
        e.block((1 << track) if b == 0 else 0, 0)
        if b >= 2 and b - 1 not in skip:            # the note started in the second interrupt
            want.append(feed[b - 1])                # the block before's, as it was when this interrupt began
        got = taken(e, 2 * place, BLOCK * len(want))
        assert state(e, track) == ((1, 2 * place, BLOCK * len(want)) if b else (0, 0, 0))
        assert np.array_equal(got, np.array(want)[:, :, 0].ravel() if want else got)
    assert len(want) == 9
    assert np.array_equal(taken(e, 2 * place + 1, BLOCK * 9), np.array(want)[:, :, 1].ravel())


def test_a_track_whose_bit_is_not_set_takes_nothing_while_another_is_fed(multi):
    e = recorder(multi, {1: 4, 6: 11})
    feed = noise((6, 8, BLOCK, 2), 60)
    write(e, 1, {})
    e.block(0b01000010, 0)
    e.block(0, 0)                                   # the notes start
    for b in range(6):
        write(e, 2 + b, {6: feed[b, 6]} if b % 2 else {1: feed[b, 1], 6: feed[b, 6]})
        e.block(0, 0)
    assert state(e, 1) == (1, 8, 3 * BLOCK) and state(e, 6) == (1, 22, 6 * BLOCK)
    assert np.array_equal(taken(e, 8, 3 * BLOCK), feed[0::2, 1, :, 0].ravel())
    assert np.array_equal(taken(e, 22, 6 * BLOCK), feed[:, 6, :, 0].ravel())


def test_a_full_buffer_ends_the_take_and_nothing_goes_past_its_end(multi):
    track, place = 3, 6
    e = recorder(multi, {track: place})
    feed = noise((3, BLOCK, 2), 70)
    e.block(1 << track, 0)
    e.block(0, 0)                                   # the note starts
    at = e.voice(track) + ST
    e.mc.w32(at + S_RPOS, m.REC_MAX - BLOCK)        # test only
    write(e, 9, {track: feed[0]})
    e.block(0, 0)
    assert state(e, track) == (0, 12, m.REC_MAX)
    last = np.frombuffer(bytes(e.mc.read(PK.buf(12) + 2 * (m.REC_MAX - BLOCK), 2 * BLOCK)), dtype=">i2")
    assert np.array_equal(last, feed[0, :, 0])
    e.mc.write(at + S_REC, b"\x01")                 # test only: a take that says it runs with no room left
    marks = [bytes(e.mc.read(PK.buf(k), 4 * BLOCK)) for k in (13, 14)]
    write(e, 10, {track: feed[1]})
    e.block(0, 0)
    assert state(e, track) == (0, 12, m.REC_MAX)
    assert [bytes(e.mc.read(PK.buf(k), 4 * BLOCK)) for k in (13, 14)] == marks


def playing(built, takes=()):
    """Eight samplers, 0 to 5 playing a sample each and looping, every track in `takes` recording. -> the engine, trigged."""
    e = P.engine(built, pool={k: noise(3000 + 500 * k, 80 + k) for k in range(8)})
    P.box(e)
    for t in range(8):
        e.set_slot(t, P.SAMPLE, PK.knob_of(20 + t) if t in takes else 64 + t % 4)
        e.set_slot(t, P.MODE, P.REC | P.STEREO if t in takes else P.STEREO)
    return e


def test_with_no_take_the_sound_is_the_stops_images_and_the_interrupt_no_longer(multi, stops):
    new, old = playing(multi), playing(stops)
    spent = []
    for b in range(24):
        outs = []
        for e in (new, old):
            was = e.mc.insns
            outs.append(e.block(0xff if b in (0, 9) else 0, 0xff if b == 20 else 0))
            spent.append(e.mc.insns - was)
        assert np.array_equal(*outs)
    more = [a - b for a, b in zip(spent[0::2], spent[1::2])]
    assert sorted(set(more)) == AUDIO_IDLE, more


AUDIO_IDLE = [-35, -19]         # instructions more an interrupt with no take: fewer, the eight voices looked at in one routine
AUDIO_TAKES = (12924, 18243)    # an interrupt with eight stereo takes running and fed: this image, the stops image


def test_what_eight_takes_cost_the_audio_cpu(multi, stops):
    """Counted as the interrupt, not as a voice. A track that records does not play."""
    feed = noise((6, 8, BLOCK, 2), 90)
    new, old = playing(multi, range(8)), playing(stops, range(8))
    new.block(0xff, 0)
    spent = {}
    for b in range(6):
        write(new, 50 + b, {t: feed[b, t] for t in range(8)})
        was = new.mc.insns
        new.block(0, 0)
        spent.setdefault("new", []).append(new.mc.insns - was)
        old.seq = (old.seq + 1) & 0xffff
        old.mc.write(LANE + 4 * BLOCK * (old.seq % 8), feed[b, 0].astype(">i2").tobytes())
        old.mc.write(m.MAILBOX, old.seq.to_bytes(2, "big"))
        was = old.mc.insns
        old.block(0xff if b == 0 else 0, 0)
        spent.setdefault("old", []).append(old.mc.insns - was)
    assert (max(spent["new"][1:]), max(spent["old"][1:])) == AUDIO_TAKES
    assert AUDIO_TAKES[0] <= AUDIO_TAKES[1]


# ---- the main CPU: every track that says record is fed its own --------------------------------------------------------

class Feed(F.Feed):
    """test_feed's rig for an image with the solos' run, where the multi image's source lookup is."""

    def __init__(self, image, syms):
        super().__init__(image, syms)
        lo, hi = mm.CAVE_ALOCK
        self.mc.load_code(lo, image[mm.off(lo):mm.off(hi)])
        self.mc.map(0x7fffd000, 0x3000)
        self.mc.uc.ctl_flush_tb()


@pytest.fixture(scope="module")
def rig(main):
    return Feed(*main)


def knobs(modes, locks=None):
    """A block of parameters: every digital track a sampler, MODE as given, a step's REC as given and else not there."""
    b = bytearray(make_block(ALL, [modes.get(t, 0) for t in range(12)]))
    for t in range(8):
        b[STRIDE * t + F.P_REC] = (locks or {}).get(t, 0)
        assert b[STRIDE * t + P_MODE] == modes.get(t, 0)
    return bytes(b)


def want(window, frame, takes, gains):
    """The window after, by the rule: {track: (source, stereo)}, the tracks in order, each block made as the one
    block was (tests/test_feed.py, spec), the dither's number going from one to the next; then the count and the bits."""
    w = bytearray(window)
    count = (int.from_bytes(window[m.MAILBOX:m.MAILBOX + 2], "big") + 1) & 0xffff
    bits = 0
    for t in sorted(takes):
        n, stereo = takes[t]
        one = F.spec(bytes(w[:m.MAILBOX]) + window[m.MAILBOX:m.MAILBOX + 4] + bytes(w[RND:]), frame, n, gains[t], stereo)
        w[LANE + 4 * BLOCK * t:LANE + 4 * BLOCK * (t + 1)] = one[ring_at(count):ring_at(count) + 4 * BLOCK]
        w[RND:RND + 4] = one[RND:RND + 4]
        bits |= 1 << t
    if bits:
        w[m.MAILBOX:m.MAILBOX + 4] = count.to_bytes(2, "big") + bits.to_bytes(2, "big")
    return bytes(w)


def fed(rig, modes, gains, locks=None, seed=3, seq=0x0105):
    rig.reset(gains=gains)
    rig.window = []
    window, frame = junk(seq), frames(seed=seed)
    ret, after = rig.run(knobs(modes, locks), frame, window)
    assert all(size in (2, 4) for _, _, size, _ in rig.window)      # the window stores words: never a byte
    return window, frame, after


GAINS = [0, 3, 12, 0, 24, 6, 1, 7]
TAKES = [
    {0: (0, True)},
    {5: (9, False)},
    {0: (0, True), 2: (5, False), 3: (14, True), 7: (1, True)},
    {1: (15, True), 4: (4, False)},
    {t: (2 + t, t % 3 != 0) for t in range(8)},
]


@pytest.mark.parametrize("takes", TAKES)
def test_every_track_that_says_record_is_fed_its_own_sources_block_into_its_own(rig, takes):
    modes = {t: REC | (STEREO if stereo else 0) | src(n) for t, (n, stereo) in takes.items()}
    for seq in (0x0105, 0xffff):
        window, frame, after = fed(rig, modes, GAINS, seed=3 + len(takes), seq=seq)
        assert after == want(window, frame, takes, GAINS)


def test_one_track_alone_is_fed_the_alock_images_block_to_the_bit(rig, before):
    old = Feed(*before)
    for track, mode, db in [(0, REC | STEREO, 0), (6, REC | src(11), 12), (3, REC | STEREO | src(14), 24)]:
        gains = [db] * 8
        window, frame, after = fed(rig, {track: mode}, gains)
        old.reset(gains=gains)
        was = old.run(knobs({track: mode}), frame, window)[1]
        at = ring_at(0x0106)
        assert after[LANE + 4 * BLOCK * track:LANE + 4 * BLOCK * (track + 1)] == was[at:at + 4 * BLOCK]
        assert after[RND:RND + 4] == was[RND:RND + 4] and after[m.MAILBOX:m.MAILBOX + 2] == was[m.MAILBOX:m.MAILBOX + 2]


def test_a_steps_rec_counts_a_track_as_its_knob_does(rig):
    modes = {0: REC | STEREO | src(3), 1: STEREO | src(6), 2: REC | STEREO | src(8), 3: 0}
    locks = {0: m.REC_LOCK_OFF, 1: m.REC_LOCK_ON, 3: 0x4000 >> 8}
    window, frame, after = fed(rig, modes, GAINS, locks)
    assert after == want(window, frame, {1: (6, True), 2: (8, True)}, GAINS)


def test_with_rec_off_the_audio_cpu_down_or_a_bank_loading_nothing_is_read_or_written(rig):
    window, frame, after = fed(rig, {0: STEREO | src(4), 5: src(2)}, GAINS)
    assert after == window and rig.window == []
    for where in (mm.AUDIO_UP, F.BANK_BUSY):
        was = rig.mc.r32(where)
        rig.mc.w32(where, 1 - bool(was) if where == mm.AUDIO_UP else 1)
        try:
            window, frame, after = fed(rig, {0: REC | STEREO, 5: REC | src(2)}, GAINS)
            assert after == window and rig.window == []
        finally:
            rig.mc.w32(where, was)


# What a block of takes adds to a block with none, the page not on show: instructions, and word cycles of the window
# (the slow ones: a long is two). Sources 2 up, a track each.
COST = {
    ("0 dB STER", 1): (1274, 71), ("0 dB STER", 2): (2542, 139), ("0 dB STER", 4): (5078, 275), ("0 dB STER", 8): (10150, 547),
    ("+12 dB MONO", 1): (1631, 71), ("+12 dB MONO", 2): (3256, 139), ("+12 dB MONO", 4): (6506, 275), ("+12 dB MONO", 8): (13006, 547),
}
ONE_MORE = {(141, 1)}       # one take on the first track, more than the alock image's: the loop goes on to the other seven, and the count is a long


def spent(rig, modes, frame, db):
    rig.reset(gains=[db] * 8)
    counts = []
    for block in (knobs({}), knobs(modes)):
        was, rig.window = rig.mc.insns, []
        rig.run(block, frame, junk(0x0105))
        counts.append(rig.mc.insns - was)
    return counts[1] - counts[0], sum(size // 2 for _, _, size, _ in rig.window)


def test_one_take_costs_what_the_alock_images_did(rig, before):
    old, frame = Feed(*before), frames(seed=2) >> 6
    more = set()
    for case, (db, stereo) in F.CASES.items():
        modes = {0: REC | (STEREO if stereo else 0) | src(2)}
        (a, x), (b, y) = spent(rig, modes, frame, db), spent(old, modes, frame, db)
        more.add((a - b, x - y))
    assert more == ONE_MORE


@pytest.mark.parametrize("case, many", COST)
def test_what_two_four_and_eight_takes_cost_the_main_cpu(rig, case, many):
    db, stereo = F.CASES[case]
    modes = {t: REC | (STEREO if stereo else 0) | src(2 + t) for t in range(many)}
    cost = spent(rig, modes, frames(seed=2) >> 6, db)
    assert cost == COST[case, many]
    assert cost[0] <= many * F.CEILING


# ---- the image ------------------------------------------------------------------------------------------------------

def test_the_image(official_path, official, stock3, main, multi, stops):
    quiet = lambda s: None
    built = build.build(official_path, log=quiet, xfade=7)[2]
    was = build.build(official_path, log=quiet, xfade=6)[2]
    new, old = built.section(3), was.section(3)
    assert new == main[0] != old and len(new) == len(old)
    spans = [mm.CAVE_METER, mm.CAVE_ALOCK]
    diff = [k for k in range(len(new)) if new[k] != old[k]]
    stray = [k for k in diff if not any(mm.off(a) <= k < mm.off(b) for a, b in spans)]
    assert len(stray) <= 64, [hex(mm.BASE + k) for k in stray[:20]]       # operands that name a routine that moved
    seven, last = built.section(7), was.section(7)
    assert seven == multi[0] != last == stops[0] and len(seven) == len(last)
    runs = [m.PITCH_CAVES["r"], m.PITCH_CAVES["p"], m.CAVES["y"]]         # the take, the post step, the hook
    diff = [k for k in range(len(seven)) if seven[k] != last[k]]
    stray = [m.BASE + k for k in diff if not any(m.off(a) <= k < m.off(b) for a, b in runs)]
    assert diff and stray == [0x40002905, 0x4000989b]                     # two operands that name a routine that moved
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
