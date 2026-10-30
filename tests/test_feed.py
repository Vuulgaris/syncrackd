"""The feed image: the ptn image with the record feed made cheap on the main CPU.

The fault it is for: on the unit the screen, the lights and the keys drag with REC on, and only then. What REC on
adds on the main CPU is the feed (engine/recfeed.c), inside the per-block interrupt. The feed image writes a block
of a take with a routine of its own (engine/feed.S): no call a sample, no divide a sample, and what a take is chosen
before the loop. What it has to be, and what is held here: the ptn image's feed to the bit. Both programs are run
from their built images on the same blocks, one after another, and after every block the whole window, the meter's
numbers, the page object stock's redraw request marks and the answer are compared; for the take itself also with
the rule worked out here (tests/test_recorder.py, tests/test_gain.py). Then what a block costs, before and after.

The page: a drawing asks which step is held once where it asked three times, and draws what the ptn image draws but
FAIL, which is gone.

Emulation only. The main CPU's load has never been measured on the unit: that the drag goes is not shown here.
"""
import numpy as np
import pytest
from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE

from emu.engine import BLOCK
from emu.machine import boundaries
from test_gain import GAIN_KNOB, TABLE, TOP, GainFeed, gained
from test_keep import Takes, noise
from test_meter import ALL, FEED_PAGE, OWNER, PLACE, REC, STEREO, src
from test_mode import TAKE_KNOB
from test_pack import DEST_KNOB
from test_page import PAGE
from test_ptn import MGR, PtnRig, on_drive, page
from test_reclock import REC_KNOB, SRC_KNOB
from test_recorder import P_MODE, P_TYPE, STRIDE, WINDOW, frames, junk, make_block, ring_at, rnd_of, to16
from test_save import BUSY, DONE, FAIL, IDLE, SAVE_KNOB
from tools import audiomap as m
from tools import build, build_engine, build_main
from tools import mainmap as mm

SOURCES = range(len(PLACE))
P_REC = m.PARAM_KNOBS + 2 * m.K_REC
BANK_BUSY = mm.CAVE_BANK[0] + 8
FIFTH = (33, 12)                            # where the fifth place's value goes
TOP32, LOW32 = 0x7fffffff, -0x80000000


@pytest.fixture(scope="module")
def stock3(official):
    assert official.version == "1.42"
    return official.section(3)


@pytest.fixture(scope="module")
def main(stock3):
    return build_main.patched_image(stock3, feed=True)


@pytest.fixture(scope="module")
def before(stock3):
    return build_main.patched_image(stock3, ptn=True)


# ---- the two feeds, side by side ------------------------------------------------------------------------

class Feed(GainFeed):
    """The feed's rig, with the feed image's run loaded when the image has one, every access of the window noted, and
    the divides that run counted (in the feed's runs: both images' whole feed)."""

    def __init__(self, image, syms):
        super().__init__(image, syms)
        mc = self.mc
        self.new = "gained" not in syms
        runs = [mm.CAVE_REC, mm.CAVE_AMUTE, (mm.CAVE_METER[0] + mm.GAIN_VARS + 2 * (TOP + 1), mm.CAVE_METER[1])]
        if self.new:
            lo, hi = mm.CAVE_FEED
            mc.load_code(lo, image[mm.off(lo):mm.off(hi)])
            runs.append(mm.CAVE_FEED)
        self.window, self.divides = [], 0
        mc.uc.hook_add(UC_HOOK_MEM_READ | UC_HOOK_MEM_WRITE, self._window, begin=mm.SHARED, end=mm.SHARED + 0x1fff)
        for lo, hi in runs:
            for at, raw, text in boundaries(image[mm.off(lo):mm.off(hi)], lo):
                op = text.split()[0]
                if op[:4] in ("divs", "divu", "rems", "remu"):
                    mc.uc.hook_add(UC_HOOK_CODE, self._divide, begin=at, end=at)
        mc.uc.ctl_flush_tb()

    def _window(self, uc, access, address, size, value, user):
        write = access == 17 or access & 1                      # UC_MEM_WRITE is 17, UC_MEM_READ 16
        self.window.append((bool(write), address - mm.SHARED, size, value & (256 ** size - 1) if write else None))

    def _divide(self, uc, address, size, user):
        self.divides += 1

    def marks(self):
        """Everything the feed keeps or leaves outside the window: the meter's numbers and the gain's, the page object
        and its maintainer as stock's redraw request left them."""
        mc = self.mc
        return (bytes(mc.read(mm.METER_PAGE, mm.GAIN_VARS)), bytes(mc.read(FEED_PAGE, 0x200)), bytes(mc.read(OWNER, 0x100)))


@pytest.fixture(scope="module")
def pair(main, before):
    new, old = Feed(*main), Feed(*before)
    assert new.new and not old.new
    return new, old


def both(pair, block, frame, window=None, gains=None):
    """One block through both programs. Everything each leaves is the other's; -> the window after."""
    out = []
    for r in pair:
        if gains is not None:
            r.mc.write(mm.REC_GAINS, bytes(gains))
        r.window = []
        ret, after = r.run(block, frame, window)
        out.append((ret, after, r.marks(), r.window))
    (ret, after, marks, access), was = out
    assert after == was[1], "the window"
    assert access == was[3], "what is read and written in the window, in order"
    assert (ret, marks) == (was[0], was[2])
    assert all(size in (2, 4) for _, _, size, _ in access)      # the window stores words: never a byte
    return after


def start(pair, seq=0x0105, **kw):
    for r in pair:
        r.reset(**kw)
    return junk(seq)


def block_of(track, mode, n=12):
    return make_block(ALL, [0] * track + [mode] + [0] * (n - 1 - track))


def picks(block):
    """The track whose take a block of parameters makes, by the rule: the first sampler track that says record."""
    for t in range(8):
        mode, rec = block[STRIDE * t + P_MODE], block[STRIDE * t + P_REC]
        if block[STRIDE * t + P_TYPE] == ALL[0] and (rec == m.REC_LOCK_ON or (rec != m.REC_LOCK_OFF and mode & REC)):
            return t
    return None


def spec(window, frame, n, db, stereo):
    """The window after a block of a take, by the rule and not by either program: a mono take is half of the one
    channel and half of the other on both sides, the gain is put on, each sample is made 16 bits with its own dither."""
    left, right = PLACE[n]
    one, two = frame[:, left].astype(np.int64), frame[:, right].astype(np.int64)
    if not stereo:
        one = two = (one >> 1) + (two >> 1)
    x = np.array([[gained(a, db), gained(b, db)] for a, b in zip(one, two)], dtype=np.int64)
    seq = (int.from_bytes(window[m.MAILBOX:m.MAILBOX + 2], "big") + 1) & 0xffff
    words, rnd = to16(x, rnd_of(window))
    want = bytearray(window)
    want[m.MAILBOX:m.MAILBOX + 2] = seq.to_bytes(2, "big")
    want[ring_at(seq):ring_at(seq) + 4 * BLOCK] = words.astype(">i2").tobytes()
    want[m.MAILBOX + 4:m.MAILBOX + 8] = rnd.to_bytes(4, "big")
    return bytes(want)


def edges(db):
    """Samples at every edge there is: nothing, the ends of 32 bits, the ends of 16 bits' halves, and the last
    sample a gain takes whole and the first it does not, on both sides."""
    lim = 0x7fffffff // TABLE[db]
    out = [0, 1, -1, 255, 256, -256, -257, 0x7fff, 0x8000, 0xffff, 0x10000, -0x8000, -0x8001, -0x10000, -0x10001,
           TOP32, TOP32 - 1, TOP32 - 0x7fff, TOP32 - 0x8000, TOP32 - 0xffff, TOP32 - 0x10000, 0x7ffe8000, 0x7fff0000, 0x40000000, 0x3fffffff,
           LOW32, LOW32 + 1, LOW32 + 0x7fff, LOW32 + 0x8000, LOW32 + 0xffff, LOW32 + 0x10000, LOW32 + 0x17fff, LOW32 + 0x18000, -0x40000000, -0x40000001]
    for v in (lim - 1, lim, lim + 1, -lim + 1, -lim, -lim - 1):
        out += [v * 256, v * 256 + 255, v * 256 + 128]
        out += [2 * v * 256, 2 * v * 256 + 511]                 # twice it: a mono take's half is at the edge
    return np.array([v for v in out if LOW32 <= v <= TOP32], dtype=np.int64)


def edge_frames(db, seed):
    """A block whose every sample is at an edge, drawn anew for every channel."""
    pool = edges(db)
    return pool[np.random.default_rng(seed).integers(0, len(pool), (BLOCK, mm.FRAME_CH))].astype(np.int32)


def kinds(db, seed):
    """Blocks of every kind for one gain: noise at full scale, noise well under it, noise that just clips at this gain,
    silence, each end of 32 bits on every sample, and samples at the edges."""
    full = frames(seed=seed)
    yield full
    yield full >> 6
    yield (full >> 8) * 256 // max(1, TABLE[db] // 256 - 1) if db else full >> 1
    yield np.zeros_like(full)
    yield np.full_like(full, TOP32)
    yield np.full_like(full, LOW32)
    yield edge_frames(db, seed)
    yield edge_frames(db, seed + 100)


@pytest.mark.parametrize("stereo", [True, False])
@pytest.mark.parametrize("db", range(TOP + 1))
def test_every_gain_and_both_kinds_of_take_leave_what_the_ptn_images_feed_leaves(pair, db, stereo):
    """Eight kinds of block, the window going from one to the next as on the unit: so the dither's number is each
    block's own, and the ring goes round. A source and a track a block."""
    window = start(pair, seq=(0xfffc + db) & 0xffff)                    # the counter goes through nought on the way
    for k, frame in enumerate(kinds(db, 7 * db + stereo)):
        n, track = (5 * db + 3 * k + stereo) % len(PLACE), (db + k) % 8
        gains = [db if t == track else (db + 5 + t) % (TOP + 1) for t in range(8)]
        was = window
        window = both(pair, block_of(track, REC | src(n) | (STEREO if stereo else 0)), frame, window, gains)
        assert window == spec(was, frame, n, db, stereo), (k, n, track)


@pytest.mark.parametrize("stereo", [True, False])
@pytest.mark.parametrize("n", SOURCES)
def test_every_source(pair, n, stereo):
    """The main mix, the input, each track (one channel), the FX track, the delay and reverb: at 0 dB, at a gain that
    clips some, and at the most."""
    window = start(pair)
    for k, db in enumerate((0, 9, TOP, 0, 17)):
        frame = frames(seed=20 + n + k) >> (k % 3) if k < 3 else edge_frames(db, n + k)
        was = window
        window = both(pair, block_of(n % 8, REC | src(n) | (STEREO if stereo else 0)), frame, window, [db] * 8)
        assert window == spec(was, frame, n, db, stereo)


@pytest.mark.parametrize("db", [1, 6, 12, 13, 24])
def test_a_sample_at_a_gains_limit_and_one_past_it(pair, db):
    """The edge by itself, on a track's one channel: what the gain takes whole is the 24 bits times it, the next one
    is the end of 32 bits, on either side of nought. Stereo, and mono with twice it so that its half is there."""
    g, lim = TABLE[db], 0x7fffffff // TABLE[db]
    assert lim * g <= TOP32 < (lim + 1) * g
    vals = [lim * 256, lim * 256 + 255, (lim + 1) * 256, -lim * 256, -lim * 256 - 1, (-lim - 1) * 256, -lim * 256 + 255]
    assert [gained(v, db) for v in vals] == [lim * g, lim * g, TOP32, -lim * g, LOW32, LOW32, -lim * g]
    frame = np.zeros((BLOCK, mm.FRAME_CH), dtype=np.int32)
    frame[:, 4] = (vals * 5)[:BLOCK]
    window = start(pair)
    after = both(pair, block_of(2, REC | STEREO | src(4)), frame, window, [db] * 8)
    assert after == spec(window, frame, 4, db, True)
    frame[:, 4] = [v for v in (2 * np.array(vals * 5, dtype=np.int64))[:BLOCK].clip(LOW32, TOP32)]
    assert both(pair, block_of(2, REC | src(4)), frame, after, [db] * 8) == spec(after, frame, 4, db, False)


def test_the_ends_of_32_bits_come_out_as_the_ends_of_16_whatever_the_dither(pair):
    """Where the sum of a sample and its dither does not fit 32 bits: the new routine holds the sum, the old one held
    the 16 bits after. 400 blocks of each end and of the samples next to them, every random number its own."""
    for value, least, most in ((TOP32, 32767, 32767), (LOW32, -32768, -32767), (TOP32 - 0x10000, 32766, 32767), (LOW32 + 0x7fff, -32768, -32767)):
        frame = np.full((BLOCK, mm.FRAME_CH), value, dtype=np.int64).astype(np.int32)
        window, seen = start(pair), set()
        for k in range(100):
            was = window
            window = both(pair, block_of(0, REC | STEREO), frame, window, [0] * 8)
            if k % 25 == 0:
                assert window == spec(was, frame, 0, 0, True)
            seen |= set(np.frombuffer(window[ring_at(0x0106 + k):ring_at(0x0106 + k) + 4 * BLOCK], dtype=">i2").tolist())
        assert seen == set(range(least, most + 1))


def test_with_rec_off_nothing_is_written_by_either(pair):
    window = start(pair)
    frame = frames(seed=3)
    b = bytearray(make_block(ALL, [src(3) | STEREO] * 12))
    for t in range(12):
        b[STRIDE * t + P_REC:STRIDE * t + P_REC + 2] = bytes(2)
    assert picks(b) is None and both(pair, bytes(b), frame, window, [12] * 8) == window
    assert not [a for a in pair[0].window if a[0]]              # no write at all
    b[STRIDE * 3 + P_REC] = m.REC_LOCK_OFF                      # a step locked off on a track with REC on
    b[STRIDE * 3 + P_MODE] |= REC
    assert picks(b) is None and both(pair, bytes(b), frame, window, [12] * 8) == window
    other = bytearray(make_block([8] * 12, [REC] * 12))         # REC's bit on tracks that are not the sampler
    assert both(pair, bytes(other), frame, window, [12] * 8) == window


def test_of_two_tracks_with_rec_on_the_first_picks_the_source_the_gain_and_the_kind(pair):
    window = start(pair)
    frame = frames(seed=4) >> 3
    b = bytearray(make_block(ALL, [0, 0, REC | src(9), 0, 0, REC | STEREO | src(1), 0, 0] + [0] * 4))
    for t in range(12):
        b[STRIDE * t + P_REC:STRIDE * t + P_REC + 2] = bytes(2)
    gains = [3, 3, 7, 3, 3, 19, 3, 3]
    assert picks(b) == 2
    after = both(pair, bytes(b), frame, window, gains)
    assert after == spec(window, frame, 9, 7, False)
    b[STRIDE * 2 + P_MODE] = src(9)       # the first one's REC off: the second's take
    assert picks(b) == 5 and both(pair, bytes(b), frame, after, gains) == spec(after, frame, 1, 19, True)
    b[STRIDE * 7 + P_REC:STRIDE * 7 + P_REC + 2] = m.REC_WORD_ON.to_bytes(2, "big")
    b[STRIDE * 5 + P_REC] = m.REC_LOCK_OFF                      # a step's REC: off on the one, on on a track whose REC is off
    assert picks(b) == 7 and both(pair, bytes(b), frame, after, gains) == spec(after, frame, 0, 3, False)


def test_a_gain_changed_from_one_block_to_the_next(pair):
    window = start(pair)
    rng = np.random.default_rng(11)
    for k, db in enumerate([0, 24, 0, 1, 23, 12, 12, 0, 0, 6, 5, 24, 13, 0, 18, 2]):
        frame = frames(seed=40 + k) >> int(rng.integers(0, 8))
        stereo = k % 4 < 2
        was = window
        window = both(pair, block_of(1, REC | src(k % 2) | (STEREO if stereo else 0)), frame, window, [0, db] + [9] * 6)
        assert window == spec(was, frame, k % 2, db, stereo)


def test_mode_changed_from_one_block_to_the_next(pair):
    """What a take is, its source, REC itself and the track that records, each changed between two blocks."""
    window = start(pair)
    plan = [(0, 0, True, 0), (0, 0, False, 0), (0, 1, False, 7), (0, 1, True, 7), (0, 14, True, 7), (0, 6, False, 7), (None,) * 4, (5, 6, False, 20),
            (5, 15, True, 20), (None,) * 4, (5, 15, True, 0), (5, 2, False, 0), (7, 2, False, 0), (7, 13, True, 24), (0, 0, True, 24), (0, 0, False, 24)]
    for k, (track, n, stereo, db) in enumerate(plan):
        frame = frames(seed=60 + k) >> (k % 5)
        was = window
        if track is None:
            window = both(pair, make_block(ALL, [src(3)] * 12, seed=5), frame, window)
            assert window == was or picks(make_block(ALL, [src(3)] * 12, seed=5)) is not None
            continue
        window = both(pair, block_of(track, REC | src(n) | (STEREO if stereo else 0)), frame, window, [db] * 8)
        assert window == spec(was, frame, n, db, stereo)


def test_no_feed_while_the_audio_cpu_is_down_or_a_bank_is_loaded(pair):
    window = start(pair)
    frame, block = frames(seed=8), block_of(0, REC | STEREO)
    for at in (mm.AUDIO_UP, BANK_BUSY):
        was = [r.mc.r32(at) for r in pair]
        for r in pair:
            r.mc.w32(at, at == BANK_BUSY)
        try:
            assert both(pair, block, frame, window, [5] * 8) == window
        finally:
            for r, v in zip(pair, was):
                r.mc.w32(at, v)
    assert both(pair, block, frame, window, [5] * 8) == spec(window, frame, 0, 5, True)


@pytest.mark.parametrize("shown", [0, 12, 24])
def test_the_meter_goes_as_it_did_with_a_take_running_and_without(pair, shown):
    """300 blocks with the page on show: the level, the count of blocks, the drawings asked for, with the feed running
    for some of them. And 300 more after its last drawing, where it stops."""
    window = start(pair, page=FEED_PAGE, source=1, shown=shown)
    loud = frames(seed=9)
    asked = 0
    for k in range(600):
        frame = (loud >> (k % 13)) if k % 50 < 30 else np.zeros_like(loud)
        block = block_of(4, (REC if 40 <= k < 200 else 0) | src(1) | STEREO)
        window = both(pair, block, frame, window, [shown] * 8 if k == 0 else None)
        if pair[0].asked:
            asked += 1
            for r in pair:                                      # the page is drawn: its mark and its maintainer's are taken down
                r.mc.write(FEED_PAGE + 20, bytes(1)), r.mc.write(OWNER + 32, bytes(1))
            if k < 300:
                for r in pair:
                    r.mc.w32(mm.METER_QUIET, 0)
    assert asked == 3 + 3 and pair[0].vars[2] == m.METER_STOP   # every 96 blocks while it is drawn, and three more after


# ---- what a block costs ---------------------------------------------------------------------------------

def cost(r, block, frame, gains, idle=None):
    """The instructions a block of a take adds to a block with no take, the page not on show; and the divides run."""
    r.reset(gains=gains)
    counts = []
    for b in (idle if idle is not None else make_block(ALL, [0] * 12), block):
        was, r.divides = r.mc.insns, 0
        r.run(b, frame, junk(0x0105))
        counts.append(r.mc.insns - was)
    return counts[1] - counts[0], r.divides


CASES = {"0 dB STER": (0, True), "0 dB MONO": (0, False), "+12 dB STER": (12, True), "+12 dB MONO": (12, False)}
WAS = {"0 dB STER": (3993, 0), "0 dB MONO": (4441, 0), "+12 dB STER": (4569, 64), "+12 dB MONO": (5017, 64)}     # the ptn image
NOW = {"0 dB STER": (1126, 0), "0 dB MONO": (1285, 0), "+12 dB STER": (1515, 1), "+12 dB MONO": (1483, 1)}      # this one
CEILING = 1800                              # a block of a take, whatever it is and whatever is in it (the heaviest found: 1,722)


@pytest.mark.parametrize("case", CASES)
def test_what_a_block_of_a_take_costs_before_and_after(pair, case):
    """The first track records the main mix, noise that no gain here clips. Instructions the take adds, divides run."""
    db, stereo = CASES[case]
    new, old = pair
    block, frame = block_of(0, REC | (STEREO if stereo else 0)), frames(seed=2) >> 6
    assert cost(old, block, frame, [db] * 8) == WAS[case]
    assert cost(new, block, frame, [db] * 8) == NOW[case]
    assert NOW[case][0] <= CEILING and 2.5 * NOW[case][0] < WAS[case][0]


@pytest.mark.parametrize("stereo", [True, False])
@pytest.mark.parametrize("db", [0, 1, 12, 24])
def test_the_ceiling_holds_for_the_heaviest_block_there_is(pair, db, stereo):
    """The last track records (the longest look through the tracks), and every sample is past the gain's limit on the
    side that takes longest, or on the other, or noise at full scale."""
    new, old = pair
    block = block_of(7, REC | src(15) | (STEREO if stereo else 0))
    worst = 0
    for frame in (np.full((BLOCK, mm.FRAME_CH), LOW32, dtype=np.int64).astype(np.int32), np.full((BLOCK, mm.FRAME_CH), TOP32, dtype=np.int32), frames(seed=5),
                  edge_frames(db, 1)):
        n, divides = cost(new, block, frame, [db] * 8)
        assert divides == (1 if db else 0)
        worst = max(worst, n)
        assert n < cost(old, block, frame, [db] * 8)[0] / 2.5
    assert worst <= CEILING
    if (db, stereo) == (1, True):
        assert worst == 1722                                                # every sample past the limit below nought


def test_the_new_routine_has_no_call_and_one_divide_outside_its_loops(main):
    image, syms = main
    lo, hi = mm.CAVE_FEED
    code = image[mm.off(lo):mm.off(hi)]
    ops = [(at, text) for at, raw, text in boundaries(code, lo)]
    end = next(at for at, text in ops if text == "rts") + 2
    body = [(at, text.split()[0], text) for at, text in ops if at < end]
    assert syms["feed_block"] == lo and code[end - lo:] == b"\x4e\x71" * ((hi - end) // 2) and end - lo == 564
    names = [op for _, op, _ in body]
    assert not [op for op in names if op in ("jsr", "jmp", "trap") or op.startswith("bsr")] and names.count("rts") == 1
    divides = [at for at, op, _ in body if op[:4] in ("divs", "divu", "rems", "remu")]
    assert len(divides) == 1
    # every branch back is a loop's: four loops, and the divide is before the first of them
    back = [(at, int(text.split()[-1], 16)) for at, op, text in body if op[0] == "b" and op[1:3] in ("ne", "ra", "eq", "gt", "lt") and int(text.split()[-1], 16) < at]
    loops = sorted({(to, at) for at, to in back if code[at - lo] == 0x66})         # bne: a block's end
    assert len(loops) == 4 and divides[0] < loops[0][0]
    assert names.count("satsl") == 8 and names.count("mulul") == 16 and names.count("mulsl") == 3
    # the window: one long read and one long written (the dither's number), words otherwise
    assert [text for _, op, text in body if "10000804" in text] == ["movel 0x10000804,%d0", "movel %d0,0x10000804"]
    assert not [text for _, op, text in body if op in ("moveb", "clrb", "mvsb", "mvzb")]
    # and it is called from the feed's own routine alone
    assert image.count(lo.to_bytes(4, "big")) == 1
    at = image.find(lo.to_bytes(4, "big")) + mm.BASE
    assert mm.CAVE_METER[0] <= at - 2 < mm.CAVE_METER[1] and syms["mix_rec"] < at
    assert not [n for n in syms if n.split(".")[0] in ("gained",)]


# ---- the page -------------------------------------------------------------------------------------------

def counted(r):
    """Count what a drawing asks of stock and runs of ours: -> (passes over the steps, instructions of ours)."""
    r.passes, r.ours = 0, 0

    def a_pass(uc, address, size, user):
        r.passes += 1

    def one(uc, address, size, user):
        r.ours += 1

    r.mc.uc.hook_add(UC_HOOK_CODE, a_pass, begin=mm.PATTERN_LENGTH, end=mm.PATTERN_LENGTH)
    for lo, hi in (mm.CAVE_PAGE, mm.CAVE_PAGE2, mm.CAVE_PAGE3, mm.CAVE_PAGE4, mm.CAVE_PAGE5, mm.CAVE_PAGE6):
        r.mc.uc.hook_add(UC_HOOK_CODE, one, begin=lo, end=hi - 1)
    r.mc.uc.ctl_flush_tb()
    return r


def drawn(r):
    """One drawing, and everything it leaves."""
    r.told, r.meter_writes, r.gain_writes, r.read, r.passes, r.ours = [], [], [], [], 0, 0
    texts = r.show()
    return dict(texts=texts, order=list(r.order), dots=r.dots.tobytes(), vars=r.vars, gain=r.mc.r32(mm.METER_GAIN), told=list(r.told),
                meter=list(r.meter_writes), gains=list(r.gain_writes), stray=list(r.stray), stock=list(r.drawn))


def same_drawing(r, old):
    got, was = drawn(r), drawn(old)
    assert got == was and not got["stray"]
    return got


@pytest.mark.parametrize("state", [IDLE, BUSY, DONE, FAIL])
def test_the_fifth_place_is_blank_whatever_a_save_did(main, before, state):
    r, old = page(main, state), page(before, state)
    got, was = r.show(), old.show()
    assert not [t for t in got if t[:2] == FIFTH]                           # nothing at all, FAIL neither
    assert [t for t in was if t[:2] == FIFTH] == ([FIFTH + ("FAIL",)] if state == FAIL else [])
    assert got == [t for t in was if t[:2] != FIFTH]                        # the rest of the page as it was, in its order
    assert not [t for t in got if t[2] in ("SAVE", "BUSY", "DONE", "FAIL")]
    assert (r.dots == old.dots).all() and r.mc.r32(mm.SAVE_STATE) == state and not r.stray


def test_the_word_and_its_routine_are_not_in_the_image(main, before):
    image, syms = main
    old, was = before
    runs = (mm.CAVE_PAGE, mm.CAVE_PAGE2, mm.CAVE_PAGE3, mm.CAVE_PAGE4, mm.CAVE_PAGE5, mm.CAVE_PAGE6)
    assert not any(b"FAIL" in image[mm.off(lo):mm.off(hi)] for lo, hi in runs)
    assert any(b"FAIL" in old[mm.off(lo):mm.off(hi)] for lo, hi in runs)
    for name in ("save_place", "w_fail", "save_turn", "mode"):
        assert not [n for n in syms if n.split(".")[0] == name], name
    assert [n for n in was if n.split(".")[0] == "save_place"]
    # nothing of the page reads the save's number any more
    assert not any(mm.SAVE_STATE.to_bytes(4, "big") in image[mm.off(lo):mm.off(hi)] for lo, hi in runs)
    assert any(mm.SAVE_STATE.to_bytes(4, "big") in old[mm.off(lo):mm.off(hi)] for lo, hi in runs)
    used = lambda built: sum(len(built[0][mm.off(lo):mm.off(hi)].rstrip(b"\x4e\x71")) for lo, hi in runs)
    assert used(before) - used(main) >= 74                                  # FAIL's 74 bytes and more are room again


@pytest.mark.parametrize("state", [IDLE, BUSY, DONE, FAIL])
def test_knob_e_still_turns_nothing(main, state):
    r = page(main, state)
    was = (r.mode, r.dest, r.gains, r.box, r.smpl)
    for steps in (1, 3, -1, -5, 0):
        for side in (True, False):
            assert r.twist(SAVE_KNOB, steps, side) == 1
    assert r.mc.r32(mm.SAVE_STATE) == state and not r.saves and not r.turned
    assert (r.mode, r.dest, r.gains, r.box, r.smpl) == was and not r.changes and not r.locked and not r.did and not r.stray
    assert not [t for t in r.show() if t[:2] == FIFTH]


@pytest.mark.parametrize("fail_at", [0, 3, 8])
def test_a_write_that_fails_leaves_the_takes_for_the_next_save_and_the_page_says_nothing(main, fail_at):
    """The keep code is the ptn image's: its number still says the save failed. Only the page does not show it."""
    rig = PtnRig(main)
    takes = {4: noise(2000, 1), 5: noise(2000, 2)}
    audio = Takes(rig, takes)
    rig.serve(audio)
    rig.fail_at = fail_at
    assert rig.ptn(MGR, 0, 1, 1, 1) == 1                                    # the pattern is saved all the same
    assert rig.run() == 1 and rig.state == FAIL and audio.kept != set(takes)
    assert not [t for t in page(main, rig.state).show() if t[:2] == FIFTH]
    rig.fail_at = None
    assert rig.ptn(MGR, 0, 1, 1, 1) == 1 and len(rig.jobs) == 2 and rig.state == BUSY
    assert rig.run() == 0 and rig.state == DONE and audio.kept == set(takes) and rig.drive == on_drive(takes)


def test_the_keep_code_is_the_ptn_images(main, before):
    lo, hi = mm.CAVE_KEEP
    assert main[0][mm.off(lo):mm.off(hi)] == before[0][mm.off(lo):mm.off(hi)]
    for name in ("keep_takes", "save_start", "save_body", "save_done", "save_keep", "ptn_keep", "save_state"):
        assert main[1][name] == before[1][name]


SCENES = {
    "no step held": dict(),
    "a short pattern": dict(length=16),
    "a step held, no lock": dict(hold=(5,)),
    "a step held with a lock of MODE": dict(hold=(9, 30), locks={9: REC | src(6)}),
    "a lock of MODE on the second held step only": dict(hold=(2, 40), locks={40: STEREO | src(15)}),
    "a held step's REC locked on": dict(hold=(12,), rec={12: m.REC_WORD_ON}),
    "a held step's REC locked off on a track with REC on": dict(hold=(63,), rec={63: m.REC_WORD_OFF}, mode=REC | STEREO),
    "REC locked on a step that is not the first held": dict(hold=(3, 20), rec={20: m.REC_WORD_ON}, locks={3: src(1)}),
    "a held step past the pattern's end": dict(hold=(40,), length=32, locks={40: REC | STEREO}),
    "a key held and no trig": dict(hold=(7,), trigs=False),
}


@pytest.mark.parametrize("scene", SCENES)
@pytest.mark.parametrize("track, mode, db", [(0, 0, 0), (3, REC | STEREO | src(1), 12), (7, STEREO | src(14), 24), (5, REC | src(9), 7)])
def test_a_drawing_is_the_ptn_images_dot_for_dot_and_word_for_word(main, before, scene, track, mode, db):
    """The upper row's three, BANK, the gain, what a take is, the load, the bar: with steps held and without."""
    s = SCENES[scene]
    rigs = [counted(page(built, IDLE, track=track, mode=s.get("mode", mode))) for built in (main, before)]
    for r in rigs:
        r.mc.write(mm.REC_GAINS, bytes([db if t == track else 3 for t in range(8)]))
        r.length = s.get("length", 64)
        if "hold" in s:
            r.hold(*s["hold"], trigs=s.get("trigs", True))
        r.locks.update(s.get("locks", {}))
        for step, word in s.get("rec", {}).items():
            r.put(step, word)
        r.twist(DEST_KNOB, 5 + track)
    r, old = rigs
    first = same_drawing(r, old)
    assert (r.passes, old.passes) == (1, 3)                                 # which step is held: asked once, where it was thrice
    assert len(r.read) < len(old.read)                                      # and MODE read once where it was twice
    assert r.ours < old.ours
    for q in rigs:                                                          # the meter moves and a second drawing follows
        q.mc.w32(mm.METER_LEVEL, 20000)
    assert same_drawing(r, old)["dots"] != first["dots"]


def test_what_a_drawing_costs_of_ours_before_and_after(main, before):
    """A pattern of 64 steps and no key held: each pass looks at every step."""
    r, old = counted(page(main, IDLE)), counted(page(before, IDLE))
    same_drawing(r, old)
    assert (old.ours, r.ours) == DRAW and old.ours - r.ours > 1800


DRAW = (4376, 1861)                         # instructions of ours a drawing, the ptn image's and this one's


def test_the_pages_knobs_are_the_ptn_images_turn_for_turn(main, before):
    r, old = page(main, track=6), page(before, track=6)
    for knob, steps in ((SRC_KNOB, 3), (DEST_KNOB, 40), (REC_KNOB, 1), (GAIN_KNOB, 9), (TAKE_KNOB, -1), (SRC_KNOB, -1), (4, 1), (DEST_KNOB, -3), (REC_KNOB, -1),
                        (TAKE_KNOB, 1), (8, 2), (SAVE_KNOB, 1)):
        assert r.twist(knob, steps) == old.twist(knob, steps) and (r.mode, r.dest, r.gains, r.box) == (old.mode, old.dest, old.gains, old.box)
        assert r.show() == old.show()
    for q in (r, old):                                                      # and with steps held: locks made and moved
        q.hold(4, 17)
    for knob, steps in ((REC_KNOB, 1), (TAKE_KNOB, 1), (SRC_KNOB, 2), (REC_KNOB, -1), (GAIN_KNOB, 3)):
        assert r.twist(knob, steps) == old.twist(knob, steps) and (r.mode, r.locks, r.locked, r.rec_locks) == (old.mode, old.locks, old.locked, old.rec_locks)
        assert r.show() == old.show()
    assert r.changes == old.changes and r.stray == old.stray and not r.saves and not old.saves
    r.mc.w32(PAGE + mm.PAGE_INDEX, 0), old.mc.w32(PAGE + mm.PAGE_INDEX, 0)              # the first page is stock's and the stops image's
    assert r.twist(SAVE_KNOB, 1) == old.twist(SAVE_KNOB, 1) == r.turn_answer and r.show() == old.show()


# ---- the image ------------------------------------------------------------------------------------------

# the feed's three runs and its new one; the page's first three, and its sixth for one operand (the turn of SMPL goes on
# to the page's own turn, which is ten bytes down)
RUNS = [mm.CAVE_AMUTE, mm.CAVE_REC, mm.CAVE_METER, mm.CAVE_FEED, mm.CAVE_PAGE, mm.CAVE_PAGE2, mm.CAVE_PAGE3, mm.CAVE_PAGE6]
# the operands of the two calls that name a routine in the run the old feed's gain routine left: a muted track's trigs and a
# step's REC. Both routines are 116 bytes up
POINTERS = (mm.TRIG_MUTE, mm.HOLD_WRITE)


def test_the_main_program_is_the_ptn_images_but_for_its_declared_places(main, before, stock3):
    image, syms = main
    old, was = before
    diff = [k for k in range(len(stock3)) if image[k] != old[k]]
    spans = RUNS + [(a + 2, a + 6) for a in POINTERS]
    assert diff and all(any(mm.off(s) <= k < mm.off(e) for s, e in spans) for k in diff)
    for s, e in spans:                                                      # and each of them did change
        assert image[mm.off(s):mm.off(e)] != old[mm.off(s):mm.off(e)], hex(s)
    for lo, hi in (mm.CAVE, mm.CAVE_KEEP, mm.CAVE_BANK, mm.CAVE_PAGE4, mm.CAVE_PAGE5, mm.CAVE_SOLO, mm.CAVE_RIGHT, mm.CAVE_HALVES, mm.CAVE_TEXT):
        assert image[mm.off(lo):mm.off(hi)] == old[mm.off(lo):mm.off(hi)]
    # the new run was stock's own code, which nothing reaches, on the ptn image
    lo, hi = mm.CAVE_FEED
    assert old[mm.off(lo):mm.off(hi)] == stock3[mm.off(lo):mm.off(hi)] and stock3[mm.off(lo) - 2:mm.off(lo)] == stock3[mm.off(hi) - 2:mm.off(hi)] == b"\x4e\x75"
    # the meter's numbers, the gains and the table of decibels are where they were, and so is the feed's entry
    lo = mm.CAVE_METER[0]
    assert image[mm.off(lo):mm.off(syms["chan"])] == old[mm.off(lo):mm.off(was["chan"])] and syms["chan"] == was["chan"]
    assert (syms["mix_rec"], syms["meter"], syms["mix_amute"]) == (was["mix_rec"], was["meter"], was["mix_amute"])
    assert image[mm.off(mm.MIX_CALL):mm.off(mm.MIX_CALL) + 6] == old[mm.off(mm.MIX_CALL):mm.off(mm.MIX_CALL) + 6]
    # what the old feed's routines took in the two older runs is room again
    for (lo, hi), left in ((mm.CAVE_AMUTE, 194), (mm.CAVE_REC, 122)):
        assert image[mm.off(hi) - left:mm.off(hi)] == b"\x4e\x71" * (left // 2) and image[mm.off(hi) - left - 2:mm.off(hi) - left] != b"\x4e\x71"



def test_every_changed_pointer_names_the_routine_it_named(main, before):
    image, syms = main
    old, was = before
    named = {a: [n for n, v in was.items() if v == int.from_bytes(old[mm.off(a) + 2:mm.off(a) + 6], "big")] for a in POINTERS}
    for a, names in named.items():
        assert names, hex(a)
        assert int.from_bytes(image[mm.off(a) + 2:mm.off(a) + 6], "big") in [syms[n] for n in names]


def test_the_image(official_path, official, main):
    quiet = lambda s: None
    raw, _, built, regions, _ = build.build(official_path, log=quiet, feed=True)
    was = build.build(official_path, log=quiet, ptn=True)[2]
    assert sorted(regions) == [3, 7] and built.section(3) == main[0] != was.section(3)
    # section 7, the audio CPU's program, is the ptn image's byte for byte, which is the stops image's
    assert built.section(7) == was.section(7) == build_engine.patched_image(official.section(7), stops=True)[0]
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
        if sid != 3:
            assert built.container.by_id(sid).stored == was.container.by_id(sid).stored
