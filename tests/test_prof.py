"""The prof image, a tool: the gear image with a profile of the main CPU, a record of 32 words a block that a sampler"""
import hashlib
import wave

import numpy as np
import pytest
from unicorn import UC_HOOK_MEM_READ
from unicorn.m68k_const import UC_M68K_REG_SR

import test_apage as A
import test_gear as G
import test_multi as M
import test_srr as S
from emu.engine import BLOCK
from tools import build, build_main, prof_read
from tools import mainmap as mm
from tools import fw

ON, OFF = S.ON, S.OFF
SENDS = 15
THIRD = mm.BLOCK_IRQ + 8  # the routine's third instruction


@pytest.fixture(scope="module")
def stock3(official):
    return official.section(3)


@pytest.fixture(scope="module")
def main(stock3):
    return build_main.patched_image(stock3, xfade=11)  # the stay image with the profile: it is kept from here on


@pytest.fixture(scope="module")
def gear(stock3):
    return build_main.patched_image(stock3, xfade=10)  # the image before: the stay image (the profile was first built on the gear image)


class Rig(M.Feed):
    """The feed's rig with the profile's run loaded and a timer whose every reading is the next of `counts`."""

    def __init__(self, image, syms):
        super().__init__(image, syms)
        mc = self.mc
        self.syms = syms
        lo, hi = syms["prof_irq"], mm.CAVE_PROF[1]
        mc.load_code(lo, image[mm.off(lo):mm.off(hi)])
        mc.map(mm.TIMER0_COUNT & ~0xfff, 0x1000)
        mc.map(mm.RUNNING_TASK & ~0xfff, 0x1000)
        self.counts, self.read = [], 0
        mc.uc.hook_add(UC_HOOK_MEM_READ, self._timer, begin=mm.TIMER0_COUNT, end=mm.TIMER0_COUNT + 3)
        at = mm.off(syms["prof_exit"])
        self.our_rte = syms["prof_exit"] + image[at:at + 64].index(b"\x4e\x73")
        assert self.our_rte % 2 == 0
        mc.set_exits([mc.ret, THIRD, self.our_rte])

    def rte(self, at):
        """The chip's rte, by its manual, the instruction at `at`: the emulator has none. The long on the stack is the
        format (4 and the bytes the stack was off a long by) and the SR, the next one the PC. -> the PC.
        """
        mc = self.mc
        assert mc.read(at, 2) == b"\x4e\x73"
        sp = mc.reg(15)
        top, pc = mc.r32(sp), mc.r32(sp + 4)
        assert top >> 30 == 1
        mc.set_reg(15, sp + 8 + (top >> 28 & 3))
        mc.uc.reg_write(UC_M68K_REG_SR, top & 0xffff)
        return pc

    def _timer(self, uc, access, address, size, value, user):
        assert size == 4 and address == mm.TIMER0_COUNT
        self.mc.w32(mm.TIMER0_COUNT, self.counts[self.read])
        self.read += 1

    def record(self):
        return bytes(self.mc.read(mm.CAVE_PROF[0], mm.PROF_RECORD))

    def clock(self, *counts):
        self.counts, self.read = list(counts), 0


@pytest.fixture(scope="module")
def rig(main):
    return Rig(*main)


@pytest.fixture(scope="module")
def was(gear):
    return M.Feed(*gear)


def long_at(b, k):
    return int.from_bytes(b[4 * k:4 * k + 4], "big")


# ---- the interrupt
# ------------------------------------------------------------------------------------------------------

REGS = [0x1000 * (k + 1) + k for k in range(15)]  # d0..d7, a0..a6
STACK = [0x400a1234, 0x11, 0x40001652, 0x22, 0x33, 0x4008b8fe, 0x44]
TASK = 0x4551aa00


def stopped(rig, sr=0x2004, pc=None, counts=(0x01000000, 0x0100f000)):
    """An interrupt taken with the stack and registers set, run to stock's third instruction. -> the stack pointer it
    came in with.
    """
    mc = rig.mc
    sp = 0x407fe000
    frame = (0x42fc0000 | sr).to_bytes(4, "big") + (pc or mc.ret).to_bytes(4, "big")
    mc.write(sp, frame + b"".join(v.to_bytes(4, "big") for v in STACK))
    mc.uc.reg_write(UC_M68K_REG_SR, 0x2500)  # first: the emulator has a stack pointer a mode
    for k, v in enumerate(REGS):
        mc.set_reg(k, v)
    mc.set_reg(15, sp)
    mc.w32(mm.RUNNING_TASK, TASK)
    rig.clock(*counts)
    mc.run(mm.BLOCK_IRQ, THIRD)
    return sp


def test_the_start_keeps_what_was_stopped_and_goes_on_as_stock_does(rig):
    mc = rig.mc
    before = long_at(rig.record(), 0) & 0xffff
    sp = stopped(rig)
    r = rig.record()
    assert long_at(r, 0) == 0x50520000 | (before + 1) & 0xffff  # the mark, and one more interrupt counted
    assert long_at(r, 1) == 0x01000000  # the count at the start
    assert long_at(r, 2) == 0x42fc2004 and long_at(r, 3) == mc.ret  # the frame's top, and where it was stopped
    assert long_at(r, 4) == sp + 8  # its stack pointer
    assert [long_at(r, 9 + k) for k in range(6)] == STACK[:6]
    assert long_at(r, 15) == TASK
    assert rig.read == 1
    # stock's two instructions, done: a6 linked, 164 bytes below it, the fourteen registers there. Under it our frame
    fp = sp - 8 - 4
    assert mc.reg(14) == fp and mc.reg(15) == fp - 164 and mc.r32(fp) == REGS[14]
    assert [mc.reg(k) for k in range(14)] == REGS[:14]
    assert [mc.r32(fp - 164 + 4 * k) for k in range(14)] == REGS[:14]
    assert mc.r32(fp + 4) >> 16 == 0x4000 and mc.r32(fp + 4) & 0x2700 == 0x2500 and mc.r32(fp + 8) == rig.syms["prof_exit"]
    assert mc.read(sp, 8 + 28) == (0x42fc2004).to_bytes(4, "big") + mc.ret.to_bytes(4, "big") + b"".join(v.to_bytes(4, "big") for v in STACK)


def test_stocks_rte_comes_to_our_end_which_reads_the_count_and_returns(rig):
    mc = rig.mc
    sp = stopped(rig)
    fp = mc.reg(14)
    for k, v in enumerate(REGS[:14]):
        mc.set_reg(k, v ^ 0x5a5a)  # what stock would have put back: anything
    mc.set_reg(14, mc.r32(fp))  # unlk
    mc.set_reg(15, fp + 4)
    to = rig.rte(mm.BLOCK_IRQ_END)  # stock's rte
    assert to == rig.syms["prof_exit"] and mc.uc.reg_read(UC_M68K_REG_SR) & 0x2700 == 0x2500  # our end, at the interrupt's level
    mc.run(to, rig.our_rte)
    assert rig.read == 2 and long_at(rig.record(), 8) == 0x0100f000
    assert [mc.reg(k) for k in range(15)] == [v ^ 0x5a5a for v in REGS[:14]] + [REGS[14]]
    assert rig.rte(rig.our_rte) == mc.ret and mc.reg(15) == sp + 8  # ours: what was stopped, its stack as it was
    assert mc.uc.reg_read(UC_M68K_REG_SR) & 0xffff == 0x2004  # and its own SR


# ---- the feed
# -----------------------------------------------------------------------------------------------------------

def doubled(record):
    return b"".join(record[k:k + 2] * 2 for k in range(0, len(record), 2))


@pytest.mark.parametrize("takes", [{0: SENDS}, {2: SENDS, 5: 3}, {1: 0, 4: SENDS, 7: 13}])
def test_a_track_on_sends_takes_the_record_and_the_others_their_sound(rig, takes):
    words = {t: ON << 8 | n for t, n in takes.items()}
    rig.mc.w32(rig.syms["prof_on"], 1)  # the sampling page's last knob has the profile on
    rig.clock(0x2000, 0x3000, 0x4000)
    kept = rig.record()
    window, frame, after = S.fed(rig, words, {}, M.GAINS, seed=5)
    assert rig.read == 3
    r = rig.record()
    assert [long_at(r, k) for k in (5, 6, 7)] == [0x2000, 0x3000, 0x4000]
    block = kept[:20] + (0x2000).to_bytes(4, "big") + (0x3000).to_bytes(4, "big") + kept[28:]  # as it was when the track was fed
    want = bytearray(M.want(window, frame, {t: (n, True) for t, n in takes.items() if n != SENDS}, M.GAINS))
    count = (int.from_bytes(window[M.m.MAILBOX:M.m.MAILBOX + 2], "big") + 1) & 0xffff
    bits = sum(1 << t for t in takes)
    want[M.m.MAILBOX:M.m.MAILBOX + 4] = count.to_bytes(2, "big") + bits.to_bytes(2, "big")
    for t, n in takes.items():
        if n == SENDS:
            want[M.LANE + 4 * BLOCK * t:M.LANE + 4 * BLOCK * (t + 1)] = doubled(block)
    assert after == bytes(want)


def test_with_no_track_on_sends_the_window_is_the_gear_images(rig, was):
    words = {t: ON << 8 | n for t, n in {0: 0, 3: 14, 6: 9}.items()}
    rig.mc.w32(rig.syms["prof_on"], 1)
    rig.clock(1, 2, 3)
    window, frame, after = S.fed(rig, words, {}, M.GAINS, seed=8)
    assert S.fed(was, words, {}, M.GAINS, seed=8)[2] == after  # the same window and frame in: the same window out
    assert rig.window == was.window  # and what is read and written there, in order


def test_with_the_profile_off_a_track_on_sends_takes_the_sends_as_before(rig, was):
    """Kept in every image from here on, so the last source is itself again until the knob says otherwise."""
    words = {t: ON << 8 | n for t, n in {1: SENDS, 4: 2, 6: SENDS}.items()}
    rig.mc.w32(rig.syms["prof_on"], 0)
    rig.clock(1, 2, 3)
    window, frame, after = S.fed(rig, words, {}, M.GAINS, seed=11)
    assert S.fed(was, words, {}, M.GAINS, seed=11)[2] == after
    assert rig.window == was.window


def test_the_sampling_pages_last_knob_switches_the_profile_and_its_box_says_so(main):
    r = A.page(main, 3)
    G.geared(r, [0, 256, 0, 256, -256, -256])
    at = main[1]["prof_on"]
    assert r.mc.r32(at) == 0 and "PROF" not in [t[2] for t in r.show()]  # off at a start
    got = []
    for steps in (1, 1, 1, 1, -1, -1):  # ticks stock's routine is still counting: nothing
        G.twist(r, 8, steps)
        got.append((r.mc.r32(at), "PROF" in [t[2] for t in r.show()]))
    assert got == [(0, False), (1, True), (1, True), (1, True), (0, False), (0, False)]


# ---- the reader
# ---------------------------------------------------------------------------------------------------------

def take(tmp_path, blocks=400, period=88000, lead=7):
    """A made-up take's file: an interrupt of 30 hundredths, a tenth before the mixer, 12 in it, 5 fed, 3 after."""
    rows = []
    for n in range(blocks + 1):
        t = 0xfffe0000 + period * n  # the count goes round on the way
        last = t - period
        pc = 0x40001652 if n % 4 else 0x4008b8fe
        longs = [t, 0x42fc2000 | (0x0300 if n % 10 == 0 else 0), pc, 0x45010000 + 4 * (n % 5), t + period // 10, t + period * 22 // 100,
                 last + period * 27 // 100, last + period * 30 // 100, 0x400a5050, 1, 2, 3, 4, 5, 0x4551aa00 if n % 4 else 0x4551bb00]
        rows += [prof_read.MAGIC, (0xfff0 + n) & 0xffff] + [w for v in longs for w in ((v >> 16) & 0xffff, v & 0xffff)]
    x = np.array([0] * lead + rows, dtype=np.uint16).astype("<i2")
    path = str(tmp_path / "take.wav")
    with wave.open(path, "wb") as f:
        f.setnchannels(1), f.setsampwidth(2), f.setframerate(48000)
        f.writeframes(x.tobytes())
    return path


def test_the_reader_gives_back_what_a_take_holds(tmp_path):
    r = prof_read.records(prof_read.words(take(tmp_path)))
    assert r["rows"] == 401
    period, parts, used, pairs = prof_read.times(r)
    assert period == 88000 and used == pairs == 400
    share = {k: round(100.0 * float(v.mean()) / period, 3) for k, v in parts.items()}
    assert share == {"whole": 30.0, "before the mixer": 10.0, "the mixer and our links": 12.0, "the takes and the meter": 5.0, "after": 3.0}
    text = prof_read.report(r)
    assert "counts at 132.0 MHz" in text and "0: 89.8%, 3: 10.2%" in text
    assert "task 0x4551aa00   74.8%" in text and "task 0x4551bb00   25.2%" in text


# ---- the image
# ----------------------------------------------------------------------------------------------------------

def test_the_image(official_path, official, main, gear):
    quiet = lambda s: None
    raw, _, built, _, syms = build.build(official_path, log=quiet, xfade=11)
    was_raw, _, was, _, _ = build.build(official_path, log=quiet, xfade=10)
    assert hashlib.sha256(was_raw).hexdigest().startswith("01d7363b")  # the stay image, as it is
    new, old = built.section(3), was.section(3)
    assert new == main[0] != old == gear[0] and len(new) == len(old)
    assert built.section(7) == was.section(7)
    spans = [mm.CAVE_PROF, mm.CAVE_METER, (mm.BLOCK_IRQ, THIRD), (mm.MIX_CALL + 2, mm.MIX_CALL + 6),
             mm.CAVE_PAGE, mm.CAVE_PAGE2, mm.CAVE_PAGE3, mm.CAVE_PAGE4, mm.CAVE_PAGE5, mm.CAVE_PAGE6, mm.CAVE_PAGE7, mm.CAVE_PAGE8,
             mm.CAVE_PAGE9, mm.CAVE_PAGE10]  # the page: its last knob and its last box
    stray = [mm.BASE + k for k in range(len(new)) if new[k] != old[k] and not any(mm.off(a) <= k < mm.off(b) for a, b in spans)]
    assert len(stray) <= 24, [hex(a) for a in stray[:24]]  # operands that name a routine of the page's that moved
    assert new[mm.off(mm.BLOCK_IRQ):][:8] == b"\x4e\xf9" + syms["prof_irq"].to_bytes(4, "big") + b"\x4e\x71"
    assert new[mm.off(THIRD):][:6] == old[mm.off(THIRD):][:6] == bytes.fromhex(fw.sx("28f8def5828c130bce19"))
    assert new[mm.off(mm.MIX_CALL):][:6] == b"\x4e\xb9" + syms["mix_rec"].to_bytes(4, "big")
    assert mm.CAVE_PROF[0] <= syms["mix_rec"] < mm.CAVE_PROF[1] and syms["prof_vars"] == mm.CAVE_PROF[0]
    assert new[mm.off(0x400a2f32):][:4] == mm.BLOCK_IRQ.to_bytes(4, "big")  # the vector's long is stock's
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
