"""The "time" image, a tool: the stereo image with the audio CPU's load on the sampling page (TIMED)."""
import shutil

import numpy as np
import pytest
from unicorn import UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE
from unicorn.m68k_const import UC_M68K_REG_PC

import test_stereo as T
from stereo_rig import Rig
from test_meter import page_rig
from tools import audiomap as m
from tools import build, build_engine, build_main, deadcode
from tools import mainmap as mm
from tools import fw

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

STATE, BOX = m.TIMED_STATE, m.TIMED_BOX
START, LONGEST, GAPS, BLOCKS, MOST, BEFORE = (STATE + 4 * k for k in range(6))
PERIOD = 200000  # a block, in the counts the test's timer makes: an instruction a count


@pytest.fixture(scope="module")
def stock(official):
    return official.section(7)


@pytest.fixture(scope="module")
def stereo(stock):
    return build_engine.patched_image(stock, stereo=True)


@pytest.fixture(scope="module")
def timed(stock):
    return build_engine.patched_image(stock, timed=True)


@pytest.fixture(scope="module")
def stock3(official):
    return official.section(3)


@pytest.fixture(scope="module")
def main(stock3):
    return build_main.patched_image(stock3, timed=True)


@pytest.fixture(scope="module")
def main_stereo(stock3):
    return build_main.patched_image(stock3, stereo=True)


class Clock:
    """The second timer on the bench. Read where the interrupt calls the voice loop it says `period` more than it said
    there the last time (or what `gaps` gives for this block); read after the last stage it says that, plus an
    instruction a count since. `stuck`: it does not count at all.
    """

    def __init__(self, rig, syms, period=PERIOD, first=0, gaps=None, stuck=False):
        self.mc, self.syms, self.period, self.gaps, self.stuck = rig.mc, syms, period, gaps, stuck
        self.entry, self.at, self.k = first, 0, 0
        self.starts, self.stretches, self.heads, self.tails = [], [], [], []
        rig.mc.uc.hook_add(UC_HOOK_MEM_READ, self.read, begin=m.TIMER1_COUNT, end=m.TIMER1_COUNT + 3)
        rig.mc.uc.ctl_flush_tb()

    def read(self, uc, access, address, size, value, user):
        assert size == 4 and address == m.TIMER1_COUNT
        pc = uc.reg_read(UC_M68K_REG_PC)
        if self.syms["timed_hook"] <= pc < self.syms["timed_hook"] + 28:
            gap = self.gaps[self.k] if self.gaps else self.period
            self.entry = (self.entry + (0 if self.stuck else gap)) & 0xffffffff
            self.at, self.k = self.mc.insns, self.k + 1
            self.starts.append(self.entry)
            v = self.entry
        else:
            assert self.syms["timed_amp"] <= pc < m.TIMED_CAVES["m"][1]
            self.stretches.append(0 if self.stuck else self.mc.insns - self.at)
            v = (self.entry + self.stretches[-1]) & 0xffffffff
        self.mc.w32(m.TIMER1_COUNT, v)


def rig_of(built, state=None, **clock):
    """A board with the time image, eight sampler tracks on empty slots, and the test's timer. state: the six longs of
    the routine's memory as a start finds them (None: all 0).
    """
    image, syms = built
    r = Rig(image)
    r.load_pool(T.pool())
    r.mc.write(STATE, bytes(24) if state is None else b"".join((v & 0xffffffff).to_bytes(4, "big") for v in state))
    r.mc.write(BOX, b"\xee" * 8)
    return r, Clock(r, syms, **clock)


def said(r):
    """What the window holds for the page: -> (the first long's text, the second's)."""
    return r.mc.read(BOX, 4).decode("latin1"), r.mc.read(BOX + 4, 4).decode("latin1")


def text(letter, v):
    return "%s%03d" % (letter, min(v, 999))


# ---- the sound engine is the stereo image's ---------------------------------------------------------------

def pieces(syms):
    """Where the routine's code is: after the stereo image's own in two of its runs, and in two small runs nothing
    reaches.
    """
    return [(syms["timed_amp"], m.TIMED_CAVES["m"][1]), (syms["timed_hook"], m.CAVES["x"][1]), m.TIMED_CAVES["n"], m.TIMED_CAVES["i"]]


def test_section_7_is_the_stereo_images_but_for_the_routine_and_two_calls(stock, stereo, timed):
    """The routine is in four pieces, for want of one place with room: after the stereo image's code in Twinshot's player
    and filter and in the render's run, and in two of the small runs of stock's that nothing reaches.
    """
    image, syms = timed
    lo, hi = m.TIMED_CAVES["m"]
    assert (lo, hi) == m.TWIN_ROOM["player and filter"] and [m.TIMED_CAVES["n"], m.TIMED_CAVES["i"]] == [m.SPARE_RUNS[0], m.SPARE_RUNS[2]]
    spans = pieces(syms) + [(m.ISR_VOICE_LOOP_CALL + 2, m.ISR_VOICE_LOOP_CALL + 6), (m.ISR_AMP_CALL + 2, m.ISR_AMP_CALL + 6)]
    diff = [m.BASE + k for k in range(len(image)) if image[k] != stereo[0][k]]
    assert diff and all(any(a <= d < b for a, b in spans) for d in diff)
    assert m.u32(image, m.ISR_VOICE_LOOP_CALL + 2) == syms["timed_hook"] and m.u32(image, m.ISR_AMP_CALL + 2) == syms["timed_amp"]
    assert lo < syms["timed_amp"] < hi and m.CAVES["x"][0] < syms["timed_hook"] < m.CAVES["x"][1]
    assert syms["timed_lot"] == m.TIMED_CAVES["n"][0] and syms["timed_say"] == m.TIMED_CAVES["i"][0] < syms["timed_text"] < m.TIMED_CAVES["i"][1]
    assert {n: a for n, a in syms.items() if not n.startswith("timed_")} == stereo[1]  # everything else is where it was
    # what the stereo image has there: its build's padding after its own code, and in the two small runs stock's bytes
    for at, end in pieces(syms)[:2]:
        assert set(stereo[0][m.off(at):m.off(end)].hex(" ", 2).split()) == {"4e71"}
    for at, end in pieces(syms)[2:]:
        assert stereo[0][m.off(at):m.off(end)] == stock[m.off(at):m.off(end)] and stock[m.off(end) - 2:m.off(end)] == b"\x4e\x75"
    # the two calls go on to what the stereo image calls: a jump, and a call with the five arguments again
    at = m.off(syms["timed_hook"]) + 22
    assert image[at:at + 6] == b"\x4e\xf9" + syms["sampler_hook"].to_bytes(4, "big")
    assert b"\x4e\xb9" + syms["sampler_amp"].to_bytes(4, "big") in image[m.off(syms["timed_amp"]):m.off(syms["timed_amp"]) + 32]


def test_the_two_small_runs_are_reached_by_nothing(stock, stereo):
    """Two of the four runs of unreferenced functions the map lists as spare (the fourth is named four times in stock and
    is left alone): no long of stock's or of the stereo image's names an address in them, no instruction outside them
    does, no far branch goes there. tests/test_stereo.py holds them never run or read while every machine plays.
    """
    runs = [m.TIMED_CAVES["n"], m.TIMED_CAVES["i"]]
    assert [hi - lo for lo, hi in runs] == [108, 118]
    T.reached_by_nothing(stock, runs)
    T.reached_by_nothing(stereo[0], runs)
    unreached = {(lo, hi): named for lo, hi, named, clean in deadcode.survey(stock, m.BASE, m.CODE_END, m.BASE + 4) if clean}
    assert [unreached[r] for r in runs] == [0, 0] and unreached[m.SPARE_RUNS[3]] == 4


@pytest.mark.parametrize("seed", [2, 7])
def test_every_block_is_the_stereo_images(stereo, timed, seed):
    """Left, right, the voices, what waits and what the window is told, with the knobs, trigs and machines moving."""
    script = T.scenario(seed, 40)
    _, a = T.played(stereo[0], script)
    r = Rig(timed[0])
    r.load_pool(T.pool())
    Clock(r, timed[1])
    for (prepare, trig, release), want in zip(script, a):
        prepare(r)
        voices, waiting, left = r.block(trig, release)
        mask = r.mask()
        assert mask == want["mask"] and np.array_equal(voices, want["voices"]) and np.array_equal(left, want["left"])
        assert np.array_equal(waiting, want["waiting"])
        assert all(np.array_equal(r.right(t), want["right"][t]) for t in want["right"])
    assert any(b["mask"] for b in a)


# ---- the timer ----------------------------------------------------------------------------------------------

def test_stock_starts_that_timer_and_names_it_nowhere_else(stock, timed):
    """Its clock on (slot 29 of the chip's switches), then its mode word 3: count the bus clock, run free, no interrupt,
    no capture. The first timer, whose capture is the audio interrupt, is set not to count at all, which is why it is
    not the one read. Nothing else in stock names an address of the second.
    """
    at = m.off(m.TIMER1_START)
    assert stock[at - 10:at + 6] == bytes.fromhex(fw.sx("d4b8a46317ad1ad5a8229dd698012746dda2e2f9"))
    assert stock[m.off(0x40000e36):m.off(0x40000e46)] == bytes.fromhex(fw.sx("a14ecaa2392c48338653b3b52afc9ded67f622b2"))  # the first: 0xc1
    assert 0xc1 >> 1 & 3 == 0 and 3 >> 1 & 3 == 1 and 3 & 1 and not 3 & 0x18  # clock: stopped, and the bus clock; on; free, no interrupt
    code_end = m.off(m.CODE_END)
    named = [m.BASE + o for o in range(0, code_end - 3, 2) if stock[o:o + 3] == bytes.fromhex("fc0740")]
    assert named == [m.TIMER1_START + 2]
    image, syms = timed
    ours = [m.BASE + o for o in range(0, code_end - 3, 2) if image[o:o + 4] == m.TIMER1_COUNT.to_bytes(4, "big")]
    assert sorted(ours) == sorted([syms["timed_hook"] + 2, syms["timed_amp"] + 32]) and m.TIMER1_COUNT == m.TIMER1_MODE + 12


# ---- the two numbers ------------------------------------------------------------------------------------------

def test_from_a_clean_start_256_blocks_then_the_longest_as_hundredths_of_a_block(timed):
    """Nothing is said before the 256th block. Then: the longest stretch of them over the 256th part of what the 256 gaps
    come to, and that again as the most there has been.
    """
    r, c = rig_of(timed, state=[0xfffe0000, 0, 0, 0, 0, 0], first=0xfffe0000)  # the timer's count goes round on the way: nothing to it
    heavy = {40: 0x0f, 41: 0}  # four notes start in one block and play on
    for n in range(256):
        if n == 39:
            T.samplers(r, T_factory(r), loop=1, mode=1)
            for t in range(4):
                r.set_slot(t, T.SAMPLE, 64 + t % 3)
                r.set_note(t, 55.25)
        assert said(r) == ("\xee" * 4, "\xee" * 4)
        r.block(heavy.get(n, 0), 0)
    longest = max(c.stretches)
    assert len(c.stretches) == 256 and longest > 1.2 * min(c.stretches)
    want = longest * 100 // PERIOD
    assert 10 < want < 100 and said(r) == (text("C", want), text("P", want))
    assert [r.mc.r32(a) for a in (LONGEST, GAPS, BLOCKS, MOST, BEFORE)] == [0, 0, 256, want, 0]
    for n in range(256):  # the next lot: quieter now, and the most is still the first lot's
        r.block(0, 0)
    now = max(c.stretches[256:]) * 100 // PERIOD
    assert now <= want and said(r) == (text("C", now), text("P", want))


def T_factory(r):
    """The stage knobs as a new project has them are not needed for a count: every one at 0 is a setting too."""
    return {}


@pytest.mark.parametrize("gap, stretch, want", [(PERIOD, 0, None), (150000, 148499, 98), (150000, 150000, 100), (150000, 190000, 126),
                                                (60000, 700000, 999), (0x800000, 5, 1)])
def test_the_number_is_the_longest_stretch_over_a_block_as_the_gaps_have_it(timed, gap, stretch, want):
    """The 250 blocks before told in the routine's memory, the last six run: any length of block, and a stretch that is
    longer than a block reads over 100. Past 999 it says 999.
    """
    r, c = rig_of(timed, state=[0, stretch, 250 * gap, 250, 0, 0], period=gap)
    for n in range(6):
        r.block(0, 0)
    longest = max([stretch] + c.stretches)
    block = (250 * gap + 6 * gap & 0xffffffff) >> 8
    got = longest * 100 // block
    assert said(r) == (text("C", got), text("P", got)) and (want is None or min(got, 999) == want)


def test_a_block_is_what_the_gaps_come_to_whatever_each_one_is(timed):
    """An interrupt that comes late and the next that comes early for it: the sum is what it was."""
    gaps = [PERIOD + d for d in (0, 90000, -90000, 500, -500, 0)]
    r, c = rig_of(timed, state=[0, 0, 250 * PERIOD, 250, 0, 0], gaps=gaps)
    for n in range(6):
        r.block(0, 0)
    got = max(c.stretches) * 100 // PERIOD
    assert said(r) == (text("C", got), text("P", got)) and c.starts[-1] == 6 * PERIOD


def test_the_most_is_of_this_stretch_of_32_lots_and_the_one_before(timed):
    """P holds for 5 to 11 seconds: the most of the 32 lots running and of the 32 before them."""
    long_block = 1000000  # so that the bench's own blocks are a tenth of one

    def lot(blocks, most, before, longest):
        r, c = rig_of(timed, state=[0, longest, 255 * long_block, blocks, most, before], period=long_block)
        r.block(0, 0)
        return said(r), [r.mc.r32(a) for a in (BLOCKS, MOST, BEFORE)], max(longest, c.stretches[0]) * 100 // long_block
    got, state, now = lot(0x04ff, 37, 80, 0)  # a lot in the middle of a stretch: the one before's is still the most
    assert got == (text("C", now), "P080") and state == [0x0500, 37, 80] and now < 37
    got, state, now = lot(0x04ff, 37, 20, 0)
    assert got == (text("C", now), "P037") and state == [0x0500, 37, 20]
    got, state, now = lot(0x04ff, 37, 20, long_block * 55 // 100 + 1)  # this lot is more than both
    assert now == 55 and got == ("C055", "P055") and state == [0x0500, 55, 20]
    got, state, now = lot(0x1fff, 37, 80, 0)  # the 32nd: said as before, then this stretch becomes the one before
    assert got == (text("C", now), "P080") and state == [0x2000, 0, 37]
    got, state, now = lot(0x3fff, 12, 3, 0)
    assert got[1] == text("P", max(12, now)) and state == [0x4000, 0, max(12, now)]


@pytest.mark.parametrize("seed", range(6))
def test_whatever_the_memory_holds_at_a_start_what_is_said_is_a_letter_and_three_figures(timed, seed):
    """That memory is cleared by nothing. The first lot is of as many blocks as the count's low byte leaves and may say
    anything up to 999; from the second on C is right, and P is within 64 lots.
    """
    rng = np.random.default_rng(seed)
    state = [int(v) for v in rng.integers(0, 1 << 32, 6)]
    state[3] = state[3] & ~0xff | 0xfd  # three blocks to the first lot's end
    r, c = rig_of(timed, state=state)
    for n in range(3):
        r.block(0, 0)
    first = said(r)
    for word, letter in zip(first, "CP"):
        assert word[0] == letter and word[1:].isdigit() and len(word) == 4
    for n in range(256):
        r.block(0, 0)
    now = max(c.stretches[3:]) * 100 // PERIOD
    assert said(r)[0] == text("C", now) and said(r)[1][0] == "P" and said(r)[1][1:].isdigit()
    r.mc.w32(BLOCKS, 0x1fff)  # two stretches' ends on: what the start left is gone from P too
    r.block(0, 0)
    r.mc.w32(BLOCKS, 0x3fff)
    r.block(0, 0)
    assert r.mc.r32(BEFORE) <= 999 and r.mc.r32(MOST) == 0


def test_a_timer_that_does_not_count_is_not_divided_by(timed):
    """If the unit's does not: every stretch and every gap is nothing, C000 is said, and the unit goes on."""
    r, c = rig_of(timed, state=[0, 0, 0, 250, 0, 0], stuck=True)
    for n in range(6):
        r.block(0, 0)
    assert said(r) == ("C000", "P000") and c.k == 6


# ---- what it leaves alone, and what is not in the stretch ---------------------------------------------------

def test_it_writes_its_own_memory_and_two_longs_of_the_window(timed):
    image, syms = timed
    r, c = rig_of(timed, state=[0, 0, 0, 0xfe, 0, 0])
    T.samplers(r, {}, loop=1, mode=1)
    spans = pieces(syms)
    wrote = []

    def on_write(uc, access, address, size, value, user):
        if any(lo <= uc.reg_read(UC_M68K_REG_PC) < hi for lo, hi in spans):
            wrote.append((address, size))
    r.mc.uc.hook_add(UC_HOOK_MEM_WRITE, on_write)
    r.mc.uc.ctl_flush_tb()
    for n in range(4):
        r.block(0xff if n == 0 else 0, 0)
    ok = [(STATE, STATE + 24), (BOX, BOX + 8), (m.STACK_TOP - 0x400, m.STACK_TOP)]
    assert wrote and all(any(a <= w and w + s <= b for a, b in ok) for w, s in wrote)
    assert sorted(w for w, s in wrote if w < 0x1000) == [BOX, BOX + 4] and all(s == 4 for w, s in wrote if w < 0x1000)
    # that memory and those longs are no one's: past the right channels' in free memory, and between the long that
    # says which tracks have a right channel and the first of their halves
    assert m.STASH + 0xa00 == STATE and STATE + 24 <= m.HQ_MARK
    assert m.RW_HEAD + 4 == BOX and BOX + 8 <= min(m.rw_half(h) for h in range(16))


def test_what_it_adds_to_an_interrupt_and_what_of_one_is_not_in_the_stretch(stereo, timed):
    """Instructions: 24 a block and about 60 more when a lot is said. Before the voice loop's call the interrupt takes in
    the knobs the main CPU sent, and after the last stage it starts the tracks on their way.
    """
    r, c = rig_of(timed, state=[0, 0, 0, 0xf0, 0, 0])
    plain = Rig(stereo[0])
    plain.load_pool(T.pool())
    costs, heads, tails = [], [], []
    for n in range(20):
        before = r.mc.insns
        r.block(0, 0)
        plain.block(0, 0)
        costs.append(sum(r.cost.values()) - sum(plain.cost.values()))
        heads.append(c.at - before)
        tails.append(r.mc.insns - c.at - c.stretches[-1])
    assert set(costs[:15] + costs[16:]) <= {23, 24}  # (one more when a stretch is the longest so far)
    assert 55 <= costs[15] - 24 <= 70
    assert 600 < min(heads) and max(heads) < 700 and max(tails) < 100  # some 650 before and 30 after, of an interrupt's 88,000 here


# ---- the page -----------------------------------------------------------------------------------------------------

def window(r, first, second):
    r.mc.write(mm.SHARED + BOX, first + second)


@pytest.mark.parametrize("first, second", [(b"C062", b"P131"), (b"C000", b"P000"), (b"C999", b"P999")])
def test_the_page_writes_the_two_longs_where_a_value_goes_in_the_lower_row(main, first, second):
    r = page_rig(main)
    window(r, first, second)
    got = r.show()
    assert (59, 12, first.decode()) in got and (85, 12, second.decode()) in got
    assert (59, 0, "") in got and (85, 0, "") in got  # no name over them: the bar is there
    assert not r.stray and r.order[0] == "stock"
    assert [t for t in got if t[2] in ("SRC", "DEST", "REC")]  # the rest of the page as it was


@pytest.mark.parametrize("seed", range(4))
def test_whatever_the_window_holds_the_page_writes_a_letter_and_three_figures(main, seed):
    """Before the audio CPU's first lot, and while it is down, those longs are whatever they were."""
    raw = bytes(np.random.default_rng(seed).integers(0, 256, 8, dtype=np.uint8))
    r = page_rig(main)
    window(r, raw[:4], raw[4:])
    got = {x: s for x, y, s in r.show() if y == 12 and x in (59, 85)}
    for s in got.values():
        assert len(s) == 4 and 0x40 <= ord(s[0]) < 0x60 and all(0x30 <= ord(ch) < 0x40 for ch in s[1:])
    assert len(got) == 2 and not r.stray


def test_no_figures_on_any_other_page(main):
    r = page_rig(main)
    r.mc.w32(0x41001000 + mm.PAGE_INDEX, 0)  # SYN's first page
    window(r, b"C062", b"P131")
    assert not [t for t in r.show() if t[2] in ("C062", "P131")]


def test_section_3_is_the_stereo_images_but_for_the_pages_code(main, main_stereo):
    image, syms = main
    spans = [mm.CAVE_PAGE, mm.CAVE_PAGE2, mm.CAVE_PAGE3]
    # and where the page's three methods and its turn are named: they have moved in their run
    spans += [(mm.SYN_CLASS + k, mm.SYN_CLASS + k + 4) for k in (mm.PAGE_KNOB_METHOD, mm.PAGE_DRAW_METHOD, mm.PAGE_TURN_METHOD)]
    spans += [(mm.SYN_SIDE + mm.SYN_SIDE_TURN, mm.SYN_SIDE + mm.SYN_SIDE_TURN + 4)]
    diff = [mm.BASE + k for k in range(len(image)) if image[k] != main_stereo[0][k]]
    assert diff and all(any(a <= d < b for a, b in spans) for d in diff)
    assert image[mm.off(mm.SYN_BUILD):mm.off(mm.SYN_BUILD) + 0x20] == main_stereo[0][mm.off(mm.SYN_BUILD):mm.off(mm.SYN_BUILD) + 0x20]
    assert mm.SHARED + BOX == 0x100005b4 and mm.SHARED.to_bytes(4, "big")[:2] + BOX.to_bytes(2, "big") in image[mm.off(mm.CAVE_PAGE[0]):mm.off(mm.CAVE_PAGE[1])]


def test_the_image(official_path, official, timed, main):
    quiet = lambda s: None
    raw, _, built, regions, syms = build.build(official_path, log=quiet, timed=True)
    assert sorted(regions) == [3, 7] and built.section(7) == timed[0] and built.section(3) == main[0]
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
    assert syms["timed_amp"] == timed[1]["timed_amp"] and "timed" in main[1]


def test_the_time12_image_is_this_one_with_the_sum_of_twelve(official_path, official, stock, timed, main):
    """For a person to hear and to read beside the other: the same main program, and the sound engine built with the
    table of twelve (tests/test_lean.py holds that engine to its model).
    """
    quiet = lambda s: None
    raw, _, built, regions, syms = build.build(official_path, log=quiet, timed=True, twelve=True)
    twelve = build_engine.patched_image(stock, timed=True, twelve=True)
    assert sorted(regions) == [3, 7] and built.section(3) == main[0] and built.section(7) == twelve[0] != timed[0]
    assert syms["timed_amp"] == timed[1]["timed_amp"] and syms["voice_out"] == timed[1]["voice_out"]
