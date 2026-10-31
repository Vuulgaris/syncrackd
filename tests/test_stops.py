"""The "stops" image: SMPL stops only on real samples and one free spot of each kind."""
import shutil

import numpy as np
import pytest
from unicorn import UC_HOOK_MEM_WRITE

import test_banks as B
import test_keep as K
import test_load as L
import test_pagerec as P
import test_stereo as T
from emu.engine import BLOCK
from test_cross import costs, cycle
from test_fade import LOOP, MODE, SAMPLE
from test_gain import GAIN_KNOB, GainPage
from test_meter import MeterRig, src
from test_mode import FIRST_MODE, PEAK_AT, ST, S_LINK, S_R, TAKE_KNOB
from test_pack import DEST_KNOB, RUNNING, SINGLE, STORY, WHERE, buf, fence, frames_of, knob_of, noise, takes
from test_page import EVENT, HOLDER, KEYS, PAGE, TEXT
from test_quick import Folded
from test_reclock import REC_KNOB, SRC_KNOB
from tools import audiomap as m
from tools import build, build_engine, build_main, deadcode, params, uitable
from tools import mainmap as mm
from tools import fw

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

SAMPLER = 44
SMPL_KNOB = mm.SMPL_KNOB  # the first page's second knob, as a turn names it
OK = m.STOPS_OK
TWO = m.STOPS_TAKE_ONE  # frames a mono take leaves in its second slot here
ROUND = 4  # blocks in which every slot is said once
ST_COUNT = m.STOPS_COUNT
EVENT_PUSHED = 20  # in a knob's event: the knob is pushed in while it is turned
KEY_JUMP = 1  # the key that makes stock's knob routine jump a value: FUNC, by what it does with it
SMPL_TEMPLATE = 0x401d6b74  # how SMPL's knob steps, in the display table's entry for its record (tools/uitable.py)


@pytest.fixture(scope="module")
def stock(official):
    return official.section(7)


@pytest.fixture(scope="module")
def stock3(official):
    assert official.version == "1.42"
    return official.section(3)


@pytest.fixture(scope="module")
def stops(stock):
    return build_engine.patched_image(stock, stops=True)


@pytest.fixture(scope="module")
def pack(stock):
    return build_engine.patched_image(stock, pack=True)


@pytest.fixture(scope="module")
def main(stock3):
    return build_main.patched_image(stock3, stops=True)


@pytest.fixture(scope="module")
def before(stock3):
    """The pack image's main program."""
    return build_main.patched_image(stock3, pack=True)


@pytest.fixture(scope="module")
def factory(official):
    return {p.slot: p.default for p in params.load(official.section(3), official.version) if p.type in (47, 45)}


@pytest.fixture(autouse=True)
def folded(monkeypatch):
    monkeypatch.setattr(P, "HookEngine", Folded)


# ---- the rule, as it is written
# ---------------------------------------------------------------------------------------

def kind(frames):
    """A slot's two bits: its length's lowest, then whether anything is left without it."""
    return (frames & 1) << 1 | (frames >> 1 != 0)


def said(frames):
    """The four longs for 64 lengths: sixteen slots a long, the first slot's two bits the highest."""
    return [sum(kind(frames[16 * g + j]) << (30 - 2 * j) for j in range(16)) for g in range(4)]


def stops_of(frames):
    """The numbers SMPL stops at, 1 to 64, for the 64 slots' lengths."""
    f = lambda k: frames[k - 1]  # slots from 1, as the rule is written
    holds = [n for n in range(1, 33) if f(2 * n - 1) > 0 and (n <= 16 or f(2 * n - 1) % 2 == 0)]
    free = [n for n in range(1, 33) if f(2 * n - 1) == 0 and f(2 * n) == 0]
    mono = [k for k in range(33, 65) if f(k) % 2 == 1 and f(k) > 1]  # one frame: the mode image's mono take, its second slot
    first = lambda k: k - 1 + k % 2  # the first slot of k's pair
    spare = [k for k in range(33, 65) if f(k) == 0 and not (f(first(k)) > 0 and f(first(k)) % 2 == 0)]
    return sorted(set(holds) | set(free[:1]) | set(mono) | set(spare[-1:]))


def values_of(numbers):
    """The knob's values for those numbers: 64 up forward, 63 down reversed."""
    return sorted({64 - n for n in numbers} | {63 + n for n in numbers})


def travelled(numbers, value, steps):
    """Where a turn of so many steps takes the knob from a value: that many stops on, or as many as there are."""
    on = [v for v in values_of(numbers) if v > value] if steps > 0 else [v for v in values_of(numbers) if v < value][::-1]
    n = min(abs(steps), len(on))
    return on[n - 1] if n else value


def bank(stereo=(), mono=(), odd=(), even=(), lone=()):
    """64 lengths. stereo: places 1 to 32 with a stereo sample. mono: single slots with a mono sample (odd). odd, even:
    slots with any sample of that kind of length. lone: places with a mono take, its second slot of two frames.
    """
    f = [0] * 64
    for n in stereo:
        f[2 * n - 2] = f[2 * n - 1] = 9600 + 2 * n
    for n in lone:
        f[2 * n - 2], f[2 * n - 1] = 6400, TWO
    for k in mono:
        f[k - 1] = 4799 + 2 * k
    for k in odd:
        f[k - 1] = 1001 + 2 * k
    for k in even:
        f[k - 1] = 2000 + 2 * k
    return f


LAYOUTS = {
    "an empty bank": (bank(), [1, 64]),
    "32 stereo": (bank(stereo=range(1, 33)), list(range(1, 33))),
    "20 stereo and 10 mono, a gap between": (bank(stereo=range(1, 21), mono=range(55, 65)), list(range(1, 22)) + list(range(54, 65))),
    "the two stacks touching": (bank(stereo=range(1, 21), mono=range(41, 65)), list(range(1, 21)) + list(range(41, 65))),
    "a hole in each stack": (bank(stereo=[1, 2, 4, 5, 7], mono=[64, 63, 61, 58]), [1, 2, 3, 4, 5, 7, 58, 61, 62, 63, 64]),
    "16 stereo and 32 mono": (bank(stereo=range(1, 17), mono=range(33, 65)), list(range(1, 17)) + list(range(33, 65))),
    "one free slot between the stacks": (bank(stereo=range(1, 21), mono=range(42, 65)), list(range(1, 21)) + list(range(41, 65))),
    "one free pair between the stacks": (bank(stereo=range(1, 21), mono=range(43, 65)), list(range(1, 22)) + list(range(42, 65))),
    # an even file in an odd slot of the back half is its stereo place's sample, as on the mode image; in an even slot
    # it is nothing the knob stops at; and the slot after an even one is no free single slot
    "old even mono files at the back": (bank(stereo=[1], even=[63, 61, 62, 58], mono=[59]), [1, 2, 31, 32, 59, 60]),
    "mono takes in stereo places": (bank(stereo=[1, 3], lone=[2, 20, 32], mono=[60]), [1, 2, 3, 4, 20, 32, 60, 62]),
    # slots 1 to 32 have no single reading: a first slot there makes its place a stop whatever its length
    "odd lengths in the front half": (bank(odd=[1, 4, 31, 32], even=[7]), [1, 3, 4, 16, 64]),
    "only second slots filled in front": (bank(even=[2, 4, 6], odd=[8]), [5, 64]),
    "a bank with nothing free": (bank(stereo=range(1, 17), even=range(33, 65)), list(range(1, 33))),
    "single frames": ([1] * 64, list(range(1, 17))),
    "three frames": ([3] * 64, list(range(1, 17)) + list(range(33, 65))),
    # mono takes kept by the mode or cross image, one frame in their second slots: those are no stops and not free
    "mono takes of the image before": ([6400, 1] * 2 + [0] * 34 + [6400, 1] + [0] * 20 + [6400, 1, 6400, 1], [1, 2, 3, 20, 31, 32, 60]),
    "two frames everywhere": ([2] * 64, list(range(1, 33))),
}


@pytest.mark.parametrize("name", list(LAYOUTS))
def test_the_rule_gives_these_stops(name):
    """The examples, worked by hand, against the rule as the functions above have it."""
    frames, want = LAYOUTS[name]
    assert stops_of(frames) == want


def test_the_rule_gives_one_free_spot_of_each_kind_at_most():
    """And at least one stop, unless every first slot of the back half is filled with what is neither kind."""
    rng = np.random.default_rng(0)
    for _ in range(2000):
        frames = [int(v) for v in rng.choice([0, 0, 0, 1, 2, 3, 640, 641, 4800, 4801], 64)]
        got = stops_of(frames)
        assert got and sum(1 for n in got if n <= 32 and not frames[2 * n - 2]) <= 1
        assert sum(1 for k in got if k > 32 and not frames[k - 1]) <= 1


# ---- the audio CPU says what every slot holds
# -----------------------------------------------------------------------------

def window(e):
    return [e.mc.r32(a) for a in m.STOPS_LONGS], e.mc.r32(m.STOPS_MARK)


def table(e):
    return [P.slot_entry(e, k)[0] for k in range(64)]


def junk(e, seed, mark=None):
    """A start: the count of blocks, the four longs and the mark hold anything."""
    rng = np.random.default_rng(seed)
    for a in (ST_COUNT, m.STOPS_MARK) + m.STOPS_LONGS:
        e.mc.w32(a, int(rng.integers(0, 2 ** 32)))
    if mark is not None:
        e.mc.w32(m.STOPS_MARK, mark)
    return [e.mc.r32(a) for a in m.STOPS_LONGS]


def settle(e):
    for _ in range(ROUND):
        e.block()
    return window(e)


def lengths(seed):
    """64 lengths of every kind: none, one frame, two, odd, even, and a few as long as a slot can be."""
    rng = np.random.default_rng(seed)
    return [int(v) for v in rng.choice([0, 0, 1, 2, 3, 64, 65, 6400, 6401, 12801, m.REC_MAX, m.REC_MAX - 1, 0x7ffff, 0x7fffe], 64)]


def put(e, frames):
    """The table's lengths, as a load or a take leaves them (test only: the samples themselves are not there)."""
    for k, n in enumerate(frames):
        e.mc.w32(m.SLOT_LEN + 8 * k, n)


@pytest.mark.parametrize("seed", range(12))
def test_every_slot_is_said_within_four_blocks_of_a_start_with_anything_in_memory(stops, seed):
    """Whatever the count of blocks, the longs and the mark hold: after each block one more long is right and the others
    are as they were, and the mark reads right after the fourth block and not before.
    """
    frames = lengths(seed)
    e = P.engine(stops)
    put(e, frames)
    was = junk(e, seed)
    want, right = said(frames), set()
    for b in range(1, 3 * ROUND + 1):
        e.block()
        longs, mark = window(e)
        right.add(e.mc.r32(ST_COUNT) & 3)
        assert longs == [want[g] if g in right else was[g] for g in range(4)]
        assert (mark == OK) == (b >= ROUND) and (b < ROUND) == (len(right) < 4)
    assert longs == want


def test_a_mark_left_reading_right_is_the_one_case_the_main_cpu_has_to_close(stops):
    """The audio CPU cannot tell a mark that was right before it started from one it made. The main CPU sets it to 0
    while the audio CPU is down (engine/rightfill.c: the test of that is below); from 0 it is four blocks.
    """
    e = P.engine(stops)
    put(e, lengths(3))
    junk(e, 1, mark=OK)
    e.block()
    assert window(e)[1] == OK and window(e)[0] != said(lengths(3))
    junk(e, 1, mark=0)
    assert [(e.block(), window(e)[1])[1] for _ in range(5)] == [0xa5, 0xa5a5, 0xa5a5a5, OK, OK]
    assert window(e)[0] == said(lengths(3))


def test_the_slots_as_stock_builds_them_from_a_pool_with_odd_lengths(stops):
    """Stock's own routine walks the pool, a count and then that many frames a slot: an odd count is a slot of an odd
    number of frames, and the slot after it begins where it should.
    """
    rng = np.random.default_rng(7)
    frames = [int(v) for v in rng.choice([0, 1, 2, 3, 333, 334, 1001], 64)]
    pool = {k: noise(n, k) for k, n in enumerate(frames) if n}
    e = P.engine(stops, pool=pool)
    assert table(e) == frames
    for k, n in enumerate(frames):
        assert not n or np.array_equal(np.frombuffer(bytes(e.mc.read(P.slot_entry(e, k)[1], 2 * n)), dtype=">i2"), pool[k])
    junk(e, 2)
    assert settle(e) == (said(frames), OK)


def test_what_is_said_follows_takes_of_each_kind(stops):
    """A stereo take in a stereo place, a mono take in one, and a single slot's: each is said for what it is while it
    runs, from its first block on, and after.
    """
    e = P.engine(stops)
    P.box(e)
    junk(e, 4)
    assert settle(e) == (said([0] * 64), OK)
    for place, mode, kinds in ((2, P.REC | P.STEREO, {4: 1, 5: 1}), (9, P.REC, {18: 1, 19: 1}), (40, P.REC | P.STEREO, {40: 3}), (63, P.REC, {63: 3})):
        e.set_slot(1, SAMPLE, knob_of(place))
        e.set_slot(1, MODE, mode)
        feed = noise(64 * 14, place).reshape(14, BLOCK, 2)
        for b in range(14):
            P.fed(e, feed[b], trig=2 if b == 0 else 0, release=2 if b == 9 else 0)
            if b >= ROUND + 1:
                frames = table(e)
                assert window(e) == (said(frames), OK) and {k: kind(frames[k]) for k in kinds} == kinds
        e.set_slot(1, MODE, 0)
    frames = table(e)
    assert [k for k in range(64) if frames[k]] == [4, 5, 18, 19, 40, 63] and frames[19] == TWO
    assert stops_of(frames) == [1, 3, 10, 41, 63, 64]
    assert frames[4] == frames[5] and frames[4] % BLOCK == 0 and frames[40] % BLOCK == BLOCK - 1 and frames[63] % BLOCK == BLOCK - 1


def test_what_is_said_follows_a_slot_that_is_loaded_and_one_that_is_emptied(stops):
    """The drive's samples put into a slot while the unit runs (engine/keeptakes.c), and a slot loaded as empty."""
    e = P.engine(stops, pool={50: noise(801, 1), 2: noise(400, 2), 3: noise(400, 3)})
    junk(e, 5)
    assert settle(e)[0] == said([0, 0, 400, 400] + [0] * 46 + [801] + [0] * 13)
    L.send(e, 63, L.sample(1235, 4))
    L.send(e, 10, L.sample(640, 5))
    L.send(e, 50, b"")
    L.send(e, 3, L.sample(7, 6))
    frames = table(e)
    assert {k: n for k, n in enumerate(frames) if n} == {2: 400, 3: 7, 10: 640, 63: 1235}
    assert settle(e) == (said(frames), OK) and stops_of(frames) == [1, 2, 6, 63, 64]


def test_only_its_five_longs_of_the_window_are_written_and_one_long_of_free_memory(stops, pack):
    """Against the pack image's engine through the same blocks, a take among them: the same writes to the window and to
    free memory, and the four longs, the mark and the count of blocks besides. A long at a time.
    """
    def run(built):
        e = P.engine(built)
        P.box(e)
        wrote = []
        e.mc.uc.hook_add(UC_HOOK_MEM_WRITE, lambda uc, t, a, s, v, u: wrote.append((a, s)) if a < 0x2000 or m.FREE_SDRAM[0] <= a < m.REC_BASE else None)
        e.set_slot(0, SAMPLE, knob_of(45))
        e.set_slot(0, MODE, P.REC)
        feed = noise(64 * 12, 3).reshape(12, BLOCK, 2)
        for b in range(12):
            P.fed(e, feed[b], trig=1 if b == 0 else 0, release=1 if b == 8 else 0)
        return set(wrote)
    ours = {(a, 4) for a in m.STOPS_LONGS + (m.STOPS_MARK, ST_COUNT)}
    now, was = run(stops), run(pack)
    assert now - was == ours and was - now == set() and not ours & was


# ---- a take's length says what it is
# -------------------------------------------------------------------------------------

TRACK = 4


@pytest.mark.parametrize("place", [3, 20, 31])
def test_a_stereo_take_is_the_pack_images_block_for_block(stops, pack, place):
    """The table, the marks and the voice's own count after every block, and the frames in both buffers."""
    was, old = takes(pack, place, P.REC | P.STEREO)
    now, e = takes(stops, place, P.REC | P.STEREO)
    assert now == was
    for k in (2 * place, 2 * place + 1):
        assert all(np.array_equal(a, b) for a, b in zip(frames_of(e, k, WHERE), frames_of(old, k, WHERE)))
    assert [t[2 * place][0] // BLOCK for t, *_ in now] == STORY and [rec for _, _, rec, _, _ in now] == RUNNING


@pytest.mark.parametrize("place", [3, 20, 31])
def test_a_mono_take_in_a_stereo_place_is_the_pack_images_with_two_frames_in_its_second_slot(stops, pack, place):
    """Two where the mode image left one: not as long as the first, so no right channel, and not odd, so no single slot's
    sample. Everything else after every block is the pack image's.
    """
    was, old = takes(pack, place, P.REC)
    now, e = takes(stops, place, P.REC)
    k = 2 * place
    for (t1, *rest1), (t0, *rest0) in zip(now, was):
        assert rest1 == rest0 and t1[:k + 1] == t0[:k + 1] and t1[k + 2:] == t0[k + 2:]
        assert t1[k + 1] == ((TWO, buf(k + 1)) if t0[k + 1] == (1, buf(k + 1)) else t0[k + 1])
    assert now[-1][0][k + 1] == (TWO, buf(k + 1)) and was[-1][0][k + 1] == (1, buf(k + 1))
    assert all(np.array_equal(a, b) for a, b in zip(frames_of(e, k, WHERE), frames_of(old, k, WHERE)))


@pytest.mark.parametrize("mode", [P.REC | P.STEREO, P.REC])
@pytest.mark.parametrize("place", [40, 41, 63])
def test_a_single_slots_take_is_a_frame_short_of_its_blocks_from_the_first_on(stops, pack, place, mode):
    """Through every way a take goes and ends: after every block the slot's length is the pack image's less one frame
    (and none where that is none), so odd whenever there is anything; the frames in its buffer, the voice's own count,
    the marks and every other line of the table are the pack image's; and the slots either side, kept samples with
    marked buffers, are as they were.
    """
    fenced = [k for k in (place - 1, place + 1) if k < 64]
    was, old = takes(pack, place, mode, fenced=fenced)
    now, e = takes(stops, place, mode, fenced=fenced)
    for (t1, *rest1), (t0, *rest0) in zip(now, was):
        n = t0[place][0]
        assert rest1 == rest0 and t1[:place] == t0[:place] and t1[place + 1:] == t0[place + 1:]
        assert t1[place] == (max(n - 1, 0), t0[place][1]) and (not n or t1[place][0] % 2 == 1)
    assert all(np.array_equal(a, b) for a, b in zip(frames_of(e, place, WHERE), frames_of(old, place, WHERE)))
    assert [(t[place][0] + 1) // BLOCK for t, *_ in now] == STORY and [rec for _, _, rec, _, _ in now] == RUNNING
    assert {t[place][0] % BLOCK for t, *_ in now} == {0, BLOCK - 1}  # nothing yet, or a frame short


def single_take(built, place, n=20, seed=1):
    e = P.engine(built)
    P.box(e)
    e.set_slot(2, SAMPLE, knob_of(place))
    e.set_slot(2, MODE, P.REC)
    P.hold(e, track=2, n=n, seed=seed)
    e.set_slot(2, MODE, 0)
    return e


@pytest.mark.parametrize("note", [60, 55.25, 67])
@pytest.mark.parametrize("place", [41, 62])
def test_it_plays_as_the_pack_images_take_less_its_last_frame(stops, pack, place, note):
    """The same take on both, the pack image's told it is a frame shorter (test only): the same sound to its end, at its
    own pitch and at others, where the frames around its end are summed.
    """
    e, old = single_take(stops, place), single_take(pack, place)
    n = P.slot_entry(old, place)[0]
    assert P.slot_entry(e, place) == (n - 1, buf(place)) and n % BLOCK == 0 and n > 400
    old.mc.w32(m.SLOT_LEN + 8 * place, n - 1)
    out = []
    for x in (e, old):
        x.set_note(2, note)
        out.append(np.array([x.block(trig=4 if b == 0 else 0) for b in range(40)]))
    assert np.array_equal(out[0], out[1]) and out[0][:, 2].any() and not out[0][-1].any()
    assert e.mc.r32(e.voice(2) + ST + S_R) == 0


def test_it_is_handed_to_the_drive_at_that_length(stops):
    """The keep's requests (engine/keeptakes.c): an odd number of frames, its last sector's last long cut where the take
    ends, and the mark that it is kept made of that length.
    """
    e = single_take(stops, 50, n=30)
    took = P.taken(e, 50)
    n = len(took)
    assert n % 2 == 1 and n % BLOCK == BLOCK - 1
    raw = took.astype(">i2").tobytes()
    ok, frames, got = K.ask(e, 50, 0)
    assert ok and frames == n and got == raw[:512]
    last = 448 + 512 * ((2 * n - 448) // 512)  # the last piece the main CPU asks for
    ok, frames, got = K.ask(e, 50, last)
    assert ok and frames == n and got == raw[last:].ljust(512, b"\0") and 0 < 2 * n - last < 512
    assert K.ask(e, 51, 0)[1] == 0 and K.ask(e, 49, 0)[1] == 0
    K.ask(e, 50, m.KEEP_DONE)
    assert K.ask(e, 50, 0)[1] == 0 and e.mc.r32(m.KEPT + 4 * 50) == n ^ m.KEEP_MARK


@pytest.mark.parametrize("place", [5, 30])
def test_a_mono_takes_second_slot_of_two_frames_is_no_right_channel_and_is_kept_as_a_take(stops, place):
    """It plays as one channel, and the keep is handed the second slot as a take of two frames, so that what the drive
    had there cannot come back as a right channel (the mode image's reason for one frame).
    """
    e = P.engine(stops)
    P.box(e)
    k = 2 * place
    e.set_slot(1, SAMPLE, knob_of(place))
    e.set_slot(1, MODE, P.REC | src(3))
    P.hold(e, track=1, n=16)
    assert P.slot_entry(e, k + 1) == (TWO, buf(k + 1)) and P.slot_entry(e, k)[0] > 300
    e.set_slot(1, MODE, 0)
    e.block(trig=2)
    out = np.array([e.block() for _ in range(4)])
    assert (e.mc.r32(e.voice(1) + ST), e.mc.r32(e.voice(1) + ST + S_R)) == (buf(k), 0) and out[:, 1].any() and not out[:, 2].any()
    ok, frames, got = K.ask(e, k + 1, 0)
    assert ok and frames == TWO and got[4:] == bytes(508)
    assert stops_of(table(e)) == [1, place + 1, 64]  # its place is a stop, and its second slot is none


def test_two_single_takes_side_by_side_are_two_mono_samples_and_no_stereo_place(stops):
    """Two takes of one length in slots 41 and 42 of Transfer: on the pack image the stereo place they are, 21, took them
    for a stereo sample. Here each is odd, so each is a stop of its own and 21 is none.
    """
    e = P.engine(stops)
    P.box(e)
    for place, seed in ((40, 1), (41, 2)):
        e.set_slot(1, SAMPLE, knob_of(place))
        e.set_slot(1, MODE, P.REC)
        P.hold(e, track=1, n=16, seed=seed)
    frames = table(e)
    assert frames[40] == frames[41] and frames[40] % 2 == 1
    assert stops_of(frames) == [1, 41, 42, 64]


# ---- what it costs
# ----------------------------------------------------------------------------------------------------------

SAYING = 128  # instructions a block for sixteen slots said: seven a slot, sixteen around them


def test_an_interrupt_is_the_pack_images_and_sixteen_slots_said(stops, pack, factory):
    """Eight pitched stereo loops, instructions an interrupt: every block is the pack image's and 128, the steady one,
    the one eight notes start in, and the two after it.
    """
    was = costs(pack[0], factory, 55.25, 80, start=30, length=40)
    now = costs(stops[0], factory, 55.25, 80, start=30, length=40)
    assert {b - a for a, b in zip(was, now)} == {SAYING}
    a, b = cycle(pack[0], factory, start=30, length=40), cycle(stops[0], factory, start=30, length=40)
    assert [y - x for x, y in zip(a, b)] == [SAYING] * 3
    assert int(np.median(now[60:])) < 103700 and b[0] < 114200  # of 117,348 for stock's heaviest


# ---- the knob
# ---------------------------------------------------------------------------------------------------------------

class StopsPage(GainPage):
    """The page rig on the sampler's first page, with SMPL's value and its locks beside MODE's: stock's methods for a
    parameter run as they are (tests/test_page.py), and what they ask of the holder for SMPL's record is played here.
    The window holds what the audio CPU says of a bank, and stock's word that the audio CPU is up.
    """

    def __init__(self, built, frames=None, smpl=64, track=0, up=1, mark=OK, **kw):
        self.smpl, self.smpl_locks, self.did, self.keys_down = smpl, {}, [], set()
        super().__init__(built, track=track, **kw)
        mc = self.mc
        self.stub(mm.UI_STATE, lambda key: key in self.keys_down)  # stock's "is this key held", after the rig's own "none is"
        mc.uc.ctl_flush_tb()
        mc.map(mm.AUDIO_UP & ~0xfff, 0x1000)
        mc.w32(mm.AUDIO_UP, up)
        mc.w32(mm.UI_TABLE + mm.UI_STRIDE * mm.R_SMPL, 4)  # SMPL's flags, as the start-up code leaves them (tools/uitable.py)
        mc.w32(PAGE + mm.PAGE_INDEX, 0)
        mc.write(PEAK_AT, b"P047")
        self.bank(frames or [0] * 64, mark)
        self.entry = self.syms.get("stops_turn_side", self.syms["syn_turn_side"]), self.syms.get("stops_turn", self.syms["syn_turn"])

    def bank(self, frames, mark=OK):
        for a, w in zip(mm.STOPS_LONGS, said(frames)):
            self.mc.w32(mm.SHARED + a, w)
        self.mc.w32(mm.SHARED + mm.STOPS_MARK, mark)

    def value(self, holder, record):
        if record != mm.R_SMPL:
            return super().value(holder, record)
        assert holder == HOLDER
        return self.smpl << 8

    def plain(self, holder, record, change, track, flag, answer, a, b):
        if record != mm.R_SMPL:
            return super().plain(holder, record, change, track, flag, answer, a, b)
        change -= (change & 0x80000000) << 1
        assert (holder, track, flag, a, b) == (HOLDER, self.track, 0, 1, 1) and change % 256 == 0 and change
        self.smpl += change // 256
        self.did.append(("plain", change // 256))
        return 0

    def lock(self, holder, record, step):
        if record != mm.R_SMPL:
            return super().lock(holder, record, step)
        return self.smpl_locks[step] << 8 if step in self.smpl_locks else 0xFFFFFFFF

    def make(self, holder, record, value, step):
        if record != mm.R_SMPL:
            return super().make(holder, record, value, step)
        assert step in self.trigs and step not in self.smpl_locks and value % 256 == 0
        self.smpl_locks[step] = value >> 8
        self.did.append(("make", step, value >> 8))
        return 1

    def move(self, holder, record, change, step, flag, answer):
        if record != mm.R_SMPL:
            return super().move(holder, record, change, step, flag, answer)
        change -= (change & 0x80000000) << 1
        assert flag == 0 and step in self.smpl_locks and change % 256 == 0 and change
        self.smpl_locks[step] += change // 256
        self.did.append(("move", step, change // 256))
        return 0

    def text_for(self, record, value):
        if record != mm.R_SMPL:
            return super().text_for(record, value)
        assert value % 256 == 0
        self.mc.write(TEXT, b"smpl %d\0" % (value >> 8))
        return TEXT

    def twist(self, knob_id, steps, side=True, pushed=False):
        self.mc.w32(EVENT + mm.EVENT_ID, knob_id)
        self.mc.w32(EVENT + mm.EVENT_STEPS, steps & 0xFFFFFFFF)
        self.mc.write(EVENT + EVENT_PUSHED, bytes([pushed]))
        if side:
            return self.mc.call(self.entry[0], PAGE + 4, EVENT)
        return self.mc.call(self.entry[1], PAGE, EVENT)

    def turn_smpl(self, steps, side=True, pushed=False):
        """A turn of SMPL that ours takes: -> the value after."""
        assert self.twist(SMPL_KNOB, steps, side, pushed) == 1 and not self.turned and self.redrawn[-1] == PAGE
        return self.smpl


def walk(r, start, step):
    """The values the knob stops at from a value on, a step at a time, to where it stays."""
    r.smpl, out = start, []
    while r.turn_smpl(step) != (out[-1] if out else start):
        out.append(r.smpl)
    return out


@pytest.mark.parametrize("name", list(LAYOUTS))
def test_the_knob_stops_at_the_banks_samples_and_one_free_spot_of_each_kind(main, name):
    """Turned a step at a time from either end: every stop in order, both halves of the knob, and no other value."""
    frames, numbers = LAYOUTS[name]
    r = StopsPage(main, frames)
    want = values_of(numbers)
    assert walk(r, 0, 1) == [v for v in want if v > 0] and walk(r, 127, -1) == [v for v in want if v < 127][::-1]
    forward = [v - 63 for v in want if v > 63]
    assert forward == numbers and [64 - v for v in want if v < 64][::-1] == numbers  # the reversed half is the same list, mirrored
    assert not r.stray and not r.turned and not r.locked and not r.changes


@pytest.mark.parametrize("seed", range(10))
def test_any_bank_any_value_any_turn(main, seed):
    """Lengths of every kind in every slot. From every value the knob can have, a stop or not, turns of one step and of
    several either way land where the rule says, and a turn of none is nothing.
    """
    rng = np.random.default_rng(seed)
    frames = [int(v) for v in rng.choice([0, 0, 0, 1, 2, 3, 640, 641, 4800, 4801], 64)]
    numbers = stops_of(frames)
    r = StopsPage(main, frames)
    for value in range(128):
        for steps in (1, -1, 2, -3, int(rng.integers(4, 20)), -int(rng.integers(4, 20)), 200, -200, 0):
            r.smpl = value
            del r.did[:]
            want = travelled(numbers, value, steps)
            assert r.turn_smpl(steps) == want, (value, steps)
            assert r.did == ([("plain", want - value)] if want != value else [])
    assert not r.stray and not r.locked and not r.changes


def test_a_fast_turn_is_that_many_stops_and_a_value_that_is_no_stop_goes_to_the_nearest(main):
    """20 stereo samples and 10 mono ones: 1 to 20, the free place 21, the free slot 54, 55 to 64."""
    r = StopsPage(main, LAYOUTS["20 stereo and 10 mono, a gap between"][0], smpl=knob_of(0))
    assert [r.turn_smpl(n) for n in (1, 3, 15, 1, 1, 1, 9, 1, 5)] == [63 + n for n in (2, 5, 20, 21, 54, 55, 64, 64, 64)]
    assert [r.turn_smpl(n) for n in (-1, -9, -1, -2, -30)] == [63 + n for n in (63, 54, 21, 19)] + [64 - 12]  # through the middle: 18 forward, 12 reversed
    # a pattern made before, or a lock, on a number the knob no longer stops at
    for value, steps, want in ((63 + 30, 1, 63 + 54), (63 + 30, -1, 63 + 21), (63 + 40, 2, 63 + 55), (64 - 30, -1, 64 - 54), (64 - 30, 1, 64 - 21),
                               (64 - 22, 3, 64 - 19), (63 + 53, -25, 64 - 4)):
        r.smpl = value
        assert r.turn_smpl(steps) == want
    assert r.popped[-1] == ("SMPL", "smpl %d" % (64 - 4)) and len(r.popped) == 21  # stock's pop-up, at every turn


def test_a_plain_turn_is_the_tracks_value_through_stocks_method_and_stocks_pop_up(main):
    r = StopsPage(main, bank(stereo=[1, 2, 3]), smpl=knob_of(0))
    assert r.turn_smpl(1) == knob_of(1) and r.did == [("plain", 1)] and r.popped == [("SMPL", "smpl %d" % knob_of(1))]
    assert r.turn_smpl(-3) == knob_of(1, reverse=True) and r.did[-1] == ("plain", -3)  # through the middle, to the reversed half
    assert r.turn_smpl(-7) == knob_of(63, reverse=True) and r.turn_smpl(-1) == knob_of(63, reverse=True)
    assert len(r.did) == 3 and len(r.popped) == 4  # at the knob's end nothing moves, and the pop-up says where it is
    r.popups = False
    assert r.turn_smpl(1) == knob_of(3, reverse=True) and len(r.popped) == 4
    assert r.turn_smpl(1, side=False) == knob_of(2, reverse=True)  # and by the class's own entry
    assert r.mode == 0 and not r.changes and not r.locked and not r.edited and not r.stray


def test_a_held_step_gets_a_lock_as_a_turn_of_any_knob_gives_one(main):
    """Stock's routine for a held step: the first turn makes a lock at the track's value and moves nothing, the next ones
    move the lock. Ours the same, by stops; the track's own value stays.
    """
    frames = bank(stereo=range(1, 6), mono=[64, 63])
    r = StopsPage(main, frames, smpl=knob_of(1))
    r.hold(3, 9, trigs=False)
    r.trigs.add(9)
    assert r.turn_smpl(2) == knob_of(1) and r.smpl_locks == {3: knob_of(1), 9: knob_of(1)}
    assert r.did == [("make", 3, knob_of(1)), ("make", 9, knob_of(1))] and r.locked == [("trig", 3, 0)] and r.edited and r.done
    r.hold(3)
    assert r.turn_smpl(2) == knob_of(1) and r.smpl_locks == {3: knob_of(3), 9: knob_of(1)}
    r.hold(3, 9)
    assert r.turn_smpl(3) == knob_of(1) and r.smpl_locks == {3: knob_of(61), 9: knob_of(4)}  # each from where it is
    assert r.turn_smpl(1) == knob_of(1) and r.smpl_locks == {3: knob_of(62), 9: knob_of(5)}
    assert r.turn_smpl(5) == knob_of(1) and r.smpl_locks == {3: knob_of(63), 9: knob_of(63)}
    assert r.did[-2:] == [("move", 3, 1), ("move", 9, 58)] and len(r.did) == 9
    assert r.turn_smpl(1) == knob_of(1) and len(r.did) == 9  # at the end no lock is moved
    assert not r.popped and not r.changes and not r.locks and not r.stray and r.done
    r.hold()
    assert r.turn_smpl(-1) == knob_of(0) and r.smpl_locks == {3: knob_of(63), 9: knob_of(63)} and r.popped


def test_pushed_in_a_click_is_eight_stops_as_stocks_is_eight_numbers(main, stock3):
    """Stock counts a knob's coarse step for a click while the knob is pushed in: the event's byte at + 20 picks the
    second of two numbers of the record's template (0x400f6866), and SMPL's are 1 and 8.
    """
    at = mm.off(SMPL_TEMPLATE)
    assert stock3[at:at + 8] == (1).to_bytes(4, "big") + (8).to_bytes(4, "big")
    assert stock3[mm.off(0x400f686e):mm.off(0x400f686e) + 4] == bytes.fromhex(fw.sx("68db5d181c11995d"))  # tstb the event's + 20
    assert stock3[mm.off(0x400f687e):mm.off(0x400f687e) + 6] == bytes.fromhex(fw.sx("c6c08076ca22cd34897a"))
    assert uitable.table(stock3)[mm.R_SMPL]["template"] == SMPL_TEMPLATE
    r = StopsPage(main, LAYOUTS["the two stacks touching"][0], smpl=knob_of(0))
    assert r.turn_smpl(1, pushed=True) == knob_of(8) and r.turn_smpl(2, pushed=True) == knob_of(44)  # 9 to 20, then 41 to 45
    assert r.turn_smpl(-1, pushed=True) == knob_of(16) and r.turn_smpl(-1) == knob_of(15)
    assert r.turn_smpl(-3, pushed=True) == knob_of(8, reverse=True) and r.did[-1] == ("plain", -24)  # 15 forward, 9 reversed
    r.hold(2)
    assert r.turn_smpl(1, pushed=True) == r.smpl and r.turn_smpl(1, pushed=True) == r.smpl  # a held step's lock too
    assert r.smpl_locks == {2: knob_of(0, reverse=True)}


def test_with_stocks_jump_key_held_the_turn_is_stocks(main, stock3):
    """Stock's knob routine asks whether key 1 is held and, with it, changes a value by the record's own jump, which for
    a sample is to the same number on the knob's other half (read in the listing, 0x4003b9c6 and 0x4006f8e4: not run
    here). That turn is not taken: the mirror of a stop is a stop.
    """
    at = mm.off(0x4003b9c6)
    assert stock3[at:at + 12] == bytes.fromhex(fw.sx("97216e699742a7125ba2") + "%08x" % mm.UI_STATE + "4e95")  # pea 1 ; lea the key test ; jsr
    r = StopsPage(main, LAYOUTS["the two stacks touching"][0], smpl=knob_of(3))
    r.keys_down = {KEY_JUMP}
    assert r.twist(SMPL_KNOB, 1) == r.turn_answer and r.twist(SMPL_KNOB, -1, pushed=True) == r.turn_answer
    assert len(r.turned) == 2 and r.smpl == knob_of(3) and not r.did and not r.redrawn
    r.keys_down = {0x12, 2, 7}  # any other key: ours
    del r.turned[:]
    assert r.turn_smpl(1) == knob_of(4)


def test_a_step_held_past_the_patterns_end_is_no_held_step(main):
    r = StopsPage(main, bank(stereo=[1, 2]), smpl=knob_of(0))
    r.length = 16
    r.hold(20)
    assert r.turn_smpl(1) == knob_of(1) and not r.smpl_locks and r.popped


@pytest.mark.parametrize("mark", [0, 0xa5a5a5, 0xa5a5a500, 0x5a5a5a5a, 0xffffffff, 0x52454321])
def test_while_the_mark_does_not_read_right_the_turn_is_stocks(main, mark):
    """The audio CPU has not said what the slots hold, or has not for four blocks: stock's own routine gets the turn as
    it came, and ours does nothing.
    """
    r = StopsPage(main, LAYOUTS["the two stacks touching"][0], smpl=knob_of(25), mark=mark)
    assert r.twist(SMPL_KNOB, 1) == r.turn_answer and r.twist(SMPL_KNOB, -3, side=False) == r.turn_answer
    assert len(r.turned) == 2 and r.smpl == knob_of(25) and not r.did and not r.popped and not r.redrawn and not r.stray
    r.hold(4)
    assert r.twist(SMPL_KNOB, 1) == r.turn_answer and not r.smpl_locks and not r.edited
    r.bank(LAYOUTS["the two stacks touching"][0])
    r.hold()
    del r.turned[:]
    assert r.turn_smpl(1) == knob_of(40)  # and with the mark there it is ours


def test_a_bank_with_no_stop_at_all_leaves_the_knob_to_stock(main):
    """It takes a bank made for it: second slots alone in front, and at the back one frame in every first slot. The rule
    has nothing to stop at, and the knob is not to be stuck.
    """
    frames = [0, 640] * 16 + [1, 640] * 16
    assert stops_of(frames) == []
    r = StopsPage(main, frames, smpl=knob_of(5))
    assert r.twist(SMPL_KNOB, 1) == r.turn_answer and r.twist(SMPL_KNOB, -2) == r.turn_answer and len(r.turned) == 2 and not r.did


def test_while_the_audio_cpu_is_down_the_turn_is_stocks(main):
    r = StopsPage(main, LAYOUTS["the two stacks touching"][0], smpl=knob_of(25), up=0)
    assert r.twist(SMPL_KNOB, 1) == r.turn_answer and len(r.turned) == 1 and not r.did
    r.mc.w32(mm.AUDIO_UP, 1)
    del r.turned[:]
    assert r.turn_smpl(1) == knob_of(40)


def test_only_the_five_longs_and_stocks_word_are_read(main):
    from unicorn import UC_HOOK_MEM_READ
    r = StopsPage(main, LAYOUTS["a hole in each stack"][0])
    reads = []
    r.mc.uc.hook_add(UC_HOOK_MEM_READ, lambda uc, t, a, s, v, u: reads.append((a, s)) if mm.SHARED <= a < mm.SHARED + 0x2000 or a >> 16 == mm.AUDIO_UP >> 16 else None)
    r.turn_smpl(2)
    assert reads[0] == (mm.AUDIO_UP, 4) and reads[1] == reads[-1] == (mm.SHARED + mm.STOPS_MARK, 4)
    assert reads[2:-1] == [(mm.SHARED + a, 4) for a in mm.STOPS_LONGS]


def test_every_other_knob_of_the_samplers_two_pages_is_what_it_was(main, before):
    """The first page's other knobs go to stock as they came; the sampling page's are the pack image's, turn for turn.
    """
    r = StopsPage(main, LAYOUTS["a hole in each stack"][0], track=6)
    for knob in (1, 3, 4, 5, 7, 8, 9):
        assert r.twist(knob, 2) == r.turn_answer and r.twist(knob, -1, side=False) == r.turn_answer
    assert len(r.turned) == 14 and r.smpl == 64 and not r.did and not r.redrawn
    assert r.twist(FIRST_MODE, 3) == 1 and not r.changes  # the empty sixth place: a turn of it is nothing, as it was
    assert [r.ask(k) for k in range(9)] == [400 + k if k != FIRST_MODE - 1 else 0 for k in range(9)]
    old = GainPage(before, track=6)
    old.mc.write(PEAK_AT, b"P047")
    r.mc.w32(PAGE + mm.PAGE_INDEX, 1)
    for knob, steps in ((SRC_KNOB, 3), (DEST_KNOB, 40), (REC_KNOB, 1), (GAIN_KNOB, 9), (TAKE_KNOB, -1), (SRC_KNOB, -1), (4, 1), (SMPL_KNOB, -3),
                        (REC_KNOB, -1), (TAKE_KNOB, 1), (8, 2)):
        assert r.twist(knob, steps) == old.twist(knob, steps) and (r.mode, r.dest, r.gains, r.box) == (old.mode, old.dest, old.gains, old.box)
        assert r.show() == old.show()
    assert r.smpl == 64 and not r.did and r.changes == old.changes and r.dest == 37
    assert r.stray == old.stray == [0x40196abe]  # (the bank the project is to be saved with, which knob D writes)


def test_another_machine_has_its_own_knobs(main):
    """A track that holds no sampler: one page, and every turn is stock's, the second knob's too."""
    other = MeterRig(main, {1: 4}, track=1, index=0)
    other.mc.map(mm.AUDIO_UP & ~0xfff, 0x1000)
    other.mc.w32(mm.AUDIO_UP, 1)
    for a, w in zip(mm.STOPS_LONGS, said(LAYOUTS["32 stereo"][0])):
        other.mc.w32(mm.SHARED + a, w)
    other.mc.w32(mm.SHARED + mm.STOPS_MARK, OK)
    for knob in range(1, 10):
        other.mc.w32(EVENT + mm.EVENT_ID, knob)
        other.mc.w32(EVENT + mm.EVENT_STEPS, 2)
        assert other.mc.call(main[1]["stops_turn_side"], PAGE + 4, EVENT) == other.turn_answer
    assert len(other.turned) == 9 and not other.changes and not other.stray
    assert [other.ask(k) for k in range(9)] == [400 + k for k in range(9)] and other.pages == 1


# ---- the two CPUs' halves against each other
# -----------------------------------------------------------------------------------

@pytest.mark.parametrize("seed", range(6))
def test_what_the_audio_cpu_says_is_what_the_knob_goes_by(stops, main, seed):
    """A bank in the audio CPU's table, its window handed to the main CPU's page as it is, and the knob walked."""
    frames = lengths(seed + 20)
    e = P.engine(stops)
    put(e, frames)
    junk(e, seed, mark=0)
    settle(e)
    r = StopsPage(main, mark=0)
    r.mc.write(mm.SHARED, e.mc.read(0, 0x1000))
    want = values_of(stops_of(frames))
    assert walk(r, 0, 1) == [v for v in want if v > 0] and walk(r, 127, -1) == [v for v in want if v < 127][::-1]


def test_takes_placed_by_hand_one_click_past_the_last_sample(stops, main):
    """What it is for. An empty bank: the knob has stereo place 1 and single slot 64. A stereo take at 1, and 2 is the
    free place; a mono take at 64, and 63 is the free slot; and so on, each take one click past the last of its kind.
    """
    e = P.engine(stops)
    P.box(e)
    junk(e, 9, mark=0)
    r = StopsPage(main, mark=0)

    def knob():
        settle(e)
        r.mc.write(mm.SHARED, e.mc.read(0, 0x1000))
        return [v - 63 for v in walk(r, 63, 1)]

    def take(number, mode, seed):
        e.set_slot(0, SAMPLE, 63 + number)
        e.set_slot(0, MODE, mode)
        P.hold(e, track=0, n=10, seed=seed)
        e.set_slot(0, MODE, 0)

    assert knob() == [1, 64]
    take(1, P.REC | P.STEREO, 1)
    assert knob() == [1, 2, 64]
    take(64, P.REC | P.STEREO, 2)
    assert knob() == [1, 2, 63, 64]
    take(2, P.REC, 3)  # a mono take in a stereo place
    take(63, P.REC, 4)
    assert knob() == [1, 2, 3, 62, 63, 64]
    take(3, P.REC | P.STEREO, 5)
    take(3, P.REC | P.STEREO, 6)  # again over the same spot: nothing is eaten
    assert knob() == [1, 2, 3, 4, 62, 63, 64]
    assert [k + 1 for k, n in enumerate(table(e)) if n] == [1, 2, 3, 4, 5, 6, 63, 64]


# ---- an odd length, from the drive to the audio CPU
# ------------------------------------------------------------------------------

def test_an_odd_length_on_the_drive_is_an_odd_length_in_the_audio_cpus_table(main, stops):
    """The pool as this image's main program stages it at a start (engine/poolhalves.c, and stock's readers under it as
    they are, the drive played by the test), handed to stock's own routine on the audio CPU that makes the slot table
    of it. A slot's header says its frames, and that many reach the table.
    """
    r = B.BankRig(main, bank=B.UNKNOWN)
    frames = {0: 4800, 1: 4800, 2: 3001, 5: 1, 40: 2400, 41: 2400, 57: 2399, 62: 4801, 63: 1235}
    for k, n in frames.items():
        r.put(k, L.sample(n, k))
    r.mc.call(build_main.POOL_STAGE[0])
    pool = bytes(r.mc.read(mm.POOL_STAGE + 5, r.mc.r32(mm.POOL_STAGE + 1)))
    assert len(pool) == 4 * 64 + 2 * sum(frames.values()) and not r.writes and not r.stray
    e = P.engine(stops)
    e.mc.write(m.POOL, pool)
    e.mc.call(m.SLOT_BUILD)
    assert {k: n for k, n in enumerate(table(e)) if n} == frames
    for k, n in frames.items():
        assert bytes(e.mc.read(P.slot_entry(e, k)[1], 2 * n)) == L.sample(n, k)
    junk(e, 1, mark=0)
    assert settle(e) == (said(table(e)), OK) and stops_of(table(e)) == [1, 2, 4, 21, 58, 62, 63, 64]


# ---- the main CPU clears the mark while the audio CPU is down
# ----------------------------------------------------------------------

def test_with_the_audio_cpu_down_the_mark_is_set_to_0_and_with_it_up_it_is_left(main, before):
    """Where the right channels' long is cleared, every block (engine/rightfill.c): the audio CPU starting again, as it
    does after samples are sent to the unit, finds no mark of before, and makes its own in four blocks. The mark is
    outside the 2 KB the boot's loader sends the samples through, which nothing of ours writes meanwhile.
    """
    r = T.FillRig(*main)
    tracks = np.zeros((8, 32), dtype=np.int32)
    win = bytearray(T.window_of({t: T.some_tracks(40)[t] for t in range(8)}, 0xff))
    win[m.STOPS_MARK:m.STOPS_MARK + 4] = OK.to_bytes(4, "big")
    r.set(tracks, bytes(win), up=0)
    assert r.mc.call(r.fill) == 0 and r.window_reads() == []
    wrote = [(a - mm.SHARED, s) for a, s in r.writes if mm.SHARED <= a < mm.SHARED + 0x2000]
    assert wrote == [(m.RW_HEAD, 4), (m.STOPS_MARK, 4)]
    want = bytearray(win)
    want[m.RW_HEAD:m.RW_HEAD + 4] = want[m.STOPS_MARK:m.STOPS_MARK + 4] = bytes(4)
    assert r.mc.read(mm.SHARED, 0x1000) == bytes(want)
    assert m.STOPS_MARK + 4 <= m.POOL_CHUNK and m.STOPS_MARK >= m.TIMED_BOX + 8 and m.STOPS_MARK + 4 <= m.rw_half(0)
    # up: nothing of ours in the window is written or read but the right channels', and it costs what it did
    counts = []
    for built in (main, before):
        r = T.FillRig(*built)
        r.set(T.some_tracks(), bytes(win))
        was = r.mc.insns
        assert r.mc.call(r.fill) == 1 and r.mc.read(mm.SHARED, 0x1000) == bytes(win)
        counts.append(r.mc.insns - was)
        assert not [a for a, s in r.reads + r.writes if a - mm.SHARED in (m.STOPS_MARK,) + m.STOPS_LONGS]
    assert counts[0] == counts[1]
    old = T.FillRig(*before)  # (the pack image's leaves that long alone)
    old.set(tracks, bytes(win), up=0)
    old.mc.call(old.fill)
    assert old.mc.r32(mm.SHARED + m.STOPS_MARK) == OK


# ---- the window, the programs, and the image
# ------------------------------------------------------------------------------------

def test_the_five_longs_are_where_the_window_has_nothing(stock, stock3):
    """Neither stock program names an address there."""
    a, b, c, d = m.STOPS_LONGS
    assert (a, b) == (m.MAILBOX + 8, m.MAILBOX + 12) and b + 4 == m.MAILBOX + m.MAILBOX_RING
    assert (c, d) == (m.REC_BOX + m.REC_SIZE, m.REC_BOX + m.REC_SIZE + 4) and d + 4 == m.rw_half(9)
    assert m.STOPS_MARK == m.TIMED_BOX + 8 == m.RW_HEAD + 12 and m.STOPS_MARK + 4 == m.rw_half(0)
    assert mm.STOPS_LONGS == m.STOPS_LONGS and (mm.STOPS_MARK, mm.STOPS_OK) == (m.STOPS_MARK, m.STOPS_OK)
    assert m.TIMED_STATE + 24 == ST_COUNT and ST_COUNT + 4 <= m.HQ_MARK and m.FREE_SDRAM[0] <= ST_COUNT
    # the audio program: no instruction's absolute short address, and no long, is one of the five
    words = np.frombuffer(stock[:m.off(m.CODE_END) & ~1], dtype=">u2")
    for addr in m.STOPS_LONGS + (m.STOPS_MARK,):
        at = np.flatnonzero(words == addr)
        assert not [k for k in at if words[k - 1] in (0x21c0, 0x21c1, 0x2038, 0x2238, 0x41f8, 0x43f8, 0x4878, 0x42b8, 0x4ab8)]
        assert (addr | mm.SHARED).to_bytes(4, "big") not in stock3 and addr.to_bytes(4, "big") not in stock[:m.off(m.CODE_END)]


def test_the_audio_cpus_interrupt_is_put_in_place_after_the_pool_is_in(stock):
    """The four longs are inside the 2 KB the boot's loader sends the pool through, and the routine that writes them runs
    in the interrupt, every block. Stock's start names the interrupt's routine once, in its last step, after the loop
    that takes the pool's chunks, and then stays in a loop of one instruction: there is no pool sent while the
    interrupt runs, and one sent again is a start again.
    """
    from emu.engine import ISR
    code = stock[:m.off(m.CODE_END)]
    named = [m.BASE + k for k in range(0, len(code) - 3, 2) if code[k:k + 4] == ISR.to_bytes(4, "big")]
    assert named == [0x40001066] and named[0] > m.POOL_CHUNK_COPY + 0x2c > m.POOL_CHUNK_COPY
    at = m.off(0x40001064)
    assert stock[at:at + 12] == bytes.fromhex("223c" + "%08x" % ISR + fw.sx("2fc3d129e0f90e58eeb8"))  # the routine into the table of them ; and round
    assert m.POOL_CHUNK == 0x800 and all(m.POOL_CHUNK <= a < m.POOL_CHUNK + 0x800 for a in m.STOPS_LONGS) and m.STOPS_MARK < m.POOL_CHUNK


def test_section_7_is_the_pack_images_but_for_our_code(stock, stops, pack):
    """The same runs and the same pointers into them: no new run, no new hook. The hook's last instruction goes on to the
    new routine, which is in two of the runs' ends; the take's routine is in the run it was in.
    """
    image, syms = stops
    runs = dict(m.CAVES, **m.REC_CAVES, **m.FADE_CAVES, **m.LIVE_CAVES, **m.PITCH_CAVES, **m.ONE_CAVES, **m.QUICK_CAVES)
    runs.update(m.LEAN_CAVES, **{k: v for k, v in m.TIMED_CAVES.items() if k != "m"}, **m.CROSS_CAVES)
    spans = list(runs.values()) + [(a, a + 4) for a in (m.UPDATE_TABLE + 4 * m.TWIN_ENGINE, m.RENDER_TABLE + 4 * m.TWIN_ENGINE,
                                                         m.ISR_VOICE_LOOP_CALL + 2, m.ISR_AMP_CALL + 2)]
    diff = [m.BASE + k for k in range(len(image)) if image[k] != stock[k]]
    assert diff and all(any(a <= d < b for a, b in spans) for d in diff)
    changed = {name for name, (a, b) in runs.items() if image[m.off(a):m.off(b)] != pack[0][m.off(a):m.off(b)]}
    # the hook; the routine's two parts; the take's; and one jump to what lies after the hook, two bytes on (hq_one)
    assert changed == {"y", "q", "p", "r", "k"} and syms["hq_one"] == pack[1]["hq_one"] + 2
    diff = [m.BASE + k for k in range(len(image)) if image[k] != pack[0][k]]
    assert all(any(a <= d < b for a, b in (runs[n] for n in changed)) for d in diff)
    for name in ("sampler_hook", "sampler_post", "sampler_update", "sampler_render", "sampler_amp", "rec_step", "timed_hook", "timed_amp"):
        assert syms[name] == pack[1][name], name
    q, p = runs["q"], runs["p"]
    assert q[0] <= syms["stops_say"] < syms["stops_at"] == q[1] - 8 and p[0] <= syms["stops_bits"] < p[1]
    assert image[m.off(q[1]) - 8:m.off(q[1])] == b"".join(a.to_bytes(2, "big") for a in m.STOPS_LONGS)
    # the room left: 218 bytes in 17 pieces, the largest 30 (the pack image: 300 in 18, the largest 44)
    left = sorted(len(image[m.off(a):m.off(b)]) - len(image[m.off(a):m.off(b)].rstrip(b"\x4e\x71")) for a, b in runs.values())
    assert sum(left) == 218 and max(left) == 30 and len([n for n in left if n]) == 17


def test_section_3_is_the_pack_images_but_for_the_page_and_the_right_channels_routine(main, before, stock3, official):
    image, syms = main
    spans = [mm.CAVE_PAGE, mm.CAVE_PAGE2, mm.CAVE_PAGE3, mm.CAVE_PAGE4, mm.CAVE_PAGE5, mm.CAVE_PAGE6, mm.CAVE_RIGHT]
    spans += [(mm.SYN_CLASS + mm.PAGE_TURN_METHOD, mm.SYN_CLASS + mm.PAGE_TURN_METHOD + 4), (mm.SYN_SIDE + mm.SYN_SIDE_TURN, mm.SYN_SIDE + mm.SYN_SIDE_TURN + 4)]
    diff = [mm.BASE + k for k in range(len(image)) if image[k] != before[0][k]]
    assert diff and all(any(a <= d < b for a, b in spans) for d in diff), [hex(d) for d in diff if not any(a <= d < b for a, b in spans)][:8]
    # the page's four runs are the pack image's to the byte: what is new is in the two new ones
    for lo, hi in (mm.CAVE_PAGE, mm.CAVE_PAGE2, mm.CAVE_PAGE3, mm.CAVE_PAGE4):
        assert image[mm.off(lo):mm.off(hi)] == before[0][mm.off(lo):mm.off(hi)]
    assert all(syms[s] == before[1][s] for s in ("syn_turn", "syn_turn_side", "syn_knob", "syn_draw", "flip", "held"))
    # a turn's two entries are the image's own, and go on to the ones that were
    assert mm.u32(image, mm.SYN_SIDE + mm.SYN_SIDE_TURN) == syms["stops_turn_side"] and mm.u32(image, mm.SYN_CLASS + mm.PAGE_TURN_METHOD) == syms["stops_turn"]
    assert mm.u32(before[0], mm.SYN_SIDE + mm.SYN_SIDE_TURN) == syms["syn_turn_side"]
    # the two new runs: nothing reaches them, each begins after a return and ends on one, and no other run of ours is
    # there
    runs = deadcode.survey(stock3, mm.BASE, mm.CODE_END, mm.ENTRY, [official.section(k) for k in (2, 4, 6, 8)])
    ours = [v for k, v in vars(mm).items() if k.startswith("CAVE") and isinstance(v, tuple) and v not in (mm.CAVE_PAGE5, mm.CAVE_PAGE6)]
    for (lo, hi), size, names in ((mm.CAVE_PAGE5, 602, ("smpl_turn", "stops_turn_side")), (mm.CAVE_PAGE6, 680, ("stops", "travel", "stops_turn"))):
        assert (lo, hi) in deadcode.usable(runs, 256) and hi - lo == size
        assert stock3[mm.off(lo) - 2:mm.off(lo)] == b"\x4e\x75" and stock3[mm.off(hi) - 2:mm.off(hi)] == b"\x4e\x75"
        assert not any(lo < b and a < hi for a, b in ours) and all(lo <= syms[s] < hi for s in names)


def test_the_image(official_path, official, stops, main):
    quiet = lambda s: None
    raw, _, built, regions, _ = build.build(official_path, log=quiet, stops=True)
    assert sorted(regions) == [3, 7] and built.section(7) == stops[0] and built.section(3) == main[0]
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
    was = build.build(official_path, log=quiet, pack=True)[2]
    assert was.section(7) != stops[0] and was.section(3) != main[0]
