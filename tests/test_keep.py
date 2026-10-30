"""The "keep" image: saving a project writes the takes that are not on the +Drive yet.

Audio CPU side (engine/sampler.c built with KEEP) runs inside the real voice loop
hook and answers requests through the bytes of the shared window. Main CPU side
(engine/keeptakes.c) runs with the project save routine and the drive replaced by
stubs, against a drive that is a Python dictionary. One test joins the two by
carrying the window's bytes across, and then lets the pool builder read the drive.

Nothing here says the audio CPU can write that part of the window while the unit
runs, how long the drive takes, or what the unit does while the save job waits:
see docs/FINDINGS.md.
"""
import shutil

import numpy as np
import pytest
from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE
from unicorn.m68k_const import UC_M68K_REG_A7, UC_M68K_REG_D0

from emu.engine import BLOCK, Engine
from emu.machine import Machine
from tools import audiomap as m
from tools import build_engine, build_main, deadcode
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

SAMPLER = 44
TUNE, SAMPLE, LENGTH, MODE, DECAY = 18, 19, 21, 23, 25
STEREO, REC_MAIN = 1, 2
SLOTS = 64
SECTORS = build_main.BIG_SLOT_SECTORS
BOX = m.KEEP_BOX
STORE = 0x41000000
STACK = (0x407f0000, 0x407ff000)


@pytest.fixture(scope="module")
def stock(official):
    return official.section(7)


@pytest.fixture(scope="module")
def stock3(official):
    assert official.version == "1.42"
    return official.section(3)


@pytest.fixture(scope="module")
def audio(stock):
    return build_engine.patched_image(stock, keep=True)


@pytest.fixture(scope="module")
def main(stock3):
    return build_main.patched_image(stock3, keep=True)


# ---- audio CPU ----------------------------------------------------------------------------------

class HookEngine(Engine):
    """The voice loop hook called directly, trig and release masks where the interrupt keeps them."""

    def block(self, trig=0, release=0):
        self.mc.set_reg(2, trig)
        self.mc.set_reg(4, release)
        return super().block(trig, release)


def engine(built, pool=None):
    """Every track a sampler in record mode, track t on stereo sample t + 1 (slots 2t, 2t + 1)."""
    image, syms = built
    e = HookEngine(image, loop_entry=syms["sampler_hook"])
    e.mc.map(0, 0x2000)                                    # the shared window
    e.load_pool(pool or {})
    for t in range(m.N_VOICES):
        e.set_machine(t, SAMPLER)
        e.set_note(t, 60)
        for s in range(18, 27):
            e.set_slot(t, s, 0)
        for s, v in ((TUNE, 64), (SAMPLE, 64 + t), (LENGTH, 127), (DECAY, 127), (MODE, REC_MAIN)):
            e.set_slot(t, s, v)
    e.seq = 0
    return e


def record(e, track, n, seed):
    """A take of about n blocks on the track's stereo sample. Returns its two slots' samples."""
    data = np.random.default_rng(seed).integers(-32768, 32768, (n + 3, BLOCK, 2)).astype(np.int16)
    for b in range(n + 3):
        e.seq = (e.seq + 1) & 0xFFFF
        e.mc.write(m.MAILBOX + m.MAILBOX_RING + 4 * BLOCK * (e.seq % m.MAILBOX_BLOCKS), data[b].astype(">i2").tobytes())
        e.mc.write(m.MAILBOX, e.seq.to_bytes(2, "big"))
        e.block(trig=1 << track if b == 0 else 0, release=1 << track if b == n else 0)
    return taken(e, 2 * track), taken(e, 2 * track + 1)


def slot_entry(e, k):
    return e.mc.r32(m.SLOT_LEN + 8 * k), e.mc.r32(m.SLOT_PTR + 8 * k)


def taken(e, k):
    frames, ptr = slot_entry(e, k)
    assert ptr == m.REC_BASE + m.REC_STRIDE * k and frames
    return bytes(e.mc.read(ptr, 2 * frames))


def ask(e, slot, off, blocks=1):
    """Write a request as the main CPU does, run blocks, return (answered, frames, data)."""
    req = (e.mc.r32(BOX + m.KEEP_ACK) + 1) & 0xFFFF
    e.mc.write(BOX + m.KEEP_SLOT, slot.to_bytes(2, "big") + off.to_bytes(4, "big"))
    e.mc.write(BOX + m.KEEP_REQ, req.to_bytes(2, "big"))
    for _ in range(blocks):
        e.block()
    box = bytes(e.mc.read(BOX, m.KEEP_SIZE))
    return box[m.KEEP_ACK:m.KEEP_ACK + 4] == req.to_bytes(4, "big"), int.from_bytes(box[12:16], "big"), box[16:]


def test_the_box_and_the_marks_are_where_nothing_else_is():
    assert BOX == m.MAILBOX + m.MAILBOX_SIZE == 0xc10 and BOX + m.KEEP_SIZE <= 0x1000   # past the ring, inside the window
    assert mm.KEEP_BOX == mm.SHARED + BOX
    assert m.STASH + 7 * 128 <= m.KEPT and m.KEPT + 4 * SLOTS == m.REC_BASE             # between the right channels and the takes
    assert m.FREE_SDRAM[0] <= m.KEPT


def test_a_take_is_handed_over_a_sector_at_a_time(audio):
    e = engine(audio)
    left, right = record(e, track=5, n=20, seed=1)
    assert len(left) == len(right) == 2 * 20 * BLOCK
    for slot, want in ((10, left), (11, right)):
        for off in (0, 448, 960, len(want) - 100, len(want) - 512, 0):
            ok, frames, data = ask(e, slot, off)
            assert ok and frames == len(want) // 2
            assert data == want[off:off + 512].ljust(512, b"\0"), (slot, off)


def test_the_audio_cpu_touches_the_window_in_longs_only_when_it_writes(audio):
    """Stock's audio program reads and writes the window in longs and nothing else. A first build wrote
    the take's bytes one at a time and the kept take came back distorted on the unit."""
    e = engine(audio)
    left, _ = record(e, track=5, n=20, seed=13)
    for t in range(m.N_VOICES):
        e.set_slot(t, MODE, 0)
    seen = []
    e.mc.uc.hook_add(UC_HOOK_MEM_WRITE, lambda uc, a, addr, size, v, u: seen.append(("w", addr, size)), begin=0, end=0x1fff)
    e.mc.uc.hook_add(UC_HOOK_MEM_READ, lambda uc, a, addr, size, v, u: seen.append(("r", addr, size)), begin=0, end=0x1fff)
    e.mc.uc.ctl_flush_tb()
    for off in (0, 448, len(left) - 512, len(left) - 2, m.KEEP_DONE):
        assert ask(e, 10, off)[0]
    writes = [(addr, size) for kind, addr, size in seen if kind == "w"]
    assert writes and all(size == 4 and addr % 4 == 0 and BOX + m.KEEP_ACK <= addr < BOX + m.KEEP_SIZE for addr, size in writes)
    assert all(size in (2, 4) for kind, addr, size in seen if kind == "r")


def test_an_odd_request_still_gets_exactly_the_takes_bytes(audio):
    """Not what the main CPU sends, but nothing is read as if it were more of the take."""
    e = engine(audio)
    left, _ = record(e, track=5, n=20, seed=14)
    for off in (1, 2, 3, 449, len(left) - 1, len(left) - 3, len(left) - 5):
        ok, frames, data = ask(e, 10, off)
        assert ok and data == left[off:off + 512].ljust(512, b"\0"), off


def test_requests_that_name_nothing_get_nothing(audio):
    pool = {3: np.arange(500, dtype=np.int16)}
    e = engine(audio, pool)
    left, _ = record(e, track=5, n=4, seed=2)
    for slot, off in ((3, 0),                               # a loaded sample: it is on the drive already
                      (12, 0),                              # an empty slot
                      (64, 0), (0xFFFF, 0),                 # no such slot
                      (10, len(left)), (10, len(left) + 512), (10, 0x7FFFFFF0)):   # past the take's end
        ok, frames, data = ask(e, slot, off)
        assert ok and data == bytes(512), (slot, off)
        assert frames == (len(left) // 2 if slot == 10 else 0)


def test_no_request_no_work_and_nothing_else_is_written(audio):
    e = engine(audio)
    record(e, track=5, n=4, seed=3)
    junk = bytes(np.random.default_rng(4).integers(0, 256, 0x2000, dtype=np.uint8))
    box = bytearray(junk[BOX:BOX + m.KEEP_SIZE])
    box[m.KEEP_ACK:m.KEEP_ACK + 4] = bytes(2) + box[m.KEEP_REQ:m.KEEP_REQ + 2]      # nothing asked
    window = junk[:BOX] + bytes(box) + junk[BOX + m.KEEP_SIZE:]
    e.mc.write(0, window)
    marks = bytes(e.mc.read(m.KEPT - 256, 256 + 4 * SLOTS))
    for t in range(m.N_VOICES):
        e.set_slot(t, MODE, 0)                              # nobody records: the ring is not read either
    for _ in range(3):
        e.block()
    assert bytes(e.mc.read(0, 0x2000)) == window
    # a request: only the answer's fields change, and no mark
    ok, frames, _ = ask(e, 10, 0)
    after = bytes(e.mc.read(0, 0x2000))
    assert ok and frames
    assert after[:BOX + m.KEEP_ACK] == window[:BOX] + after[BOX:BOX + m.KEEP_ACK]       # the main CPU's fields are ours to write
    assert after[BOX + m.KEEP_SIZE:] == window[BOX + m.KEEP_SIZE:]
    assert bytes(e.mc.read(m.KEPT - 256, 256 + 4 * SLOTS)) == marks


def test_a_kept_take_is_not_offered_again_until_it_is_taken_again(audio):
    e = engine(audio)
    left, _ = record(e, track=5, n=6, seed=5)
    assert ask(e, 10, 0)[1] and ask(e, 11, 0)[1]
    assert ask(e, 10, m.KEEP_DONE)[0]
    assert e.mc.r32(m.KEPT + 4 * 10) == (len(left) // 2) ^ m.KEEP_MARK
    assert ask(e, 10, 0)[1:] == (0, bytes(512))             # kept: nothing to hand over
    assert ask(e, 11, 0)[1] == len(left) // 2               # the right slot has its own mark
    assert ask(e, 11, m.KEEP_DONE)[0] and ask(e, 11, 0)[1] == 0
    again, _ = record(e, track=5, n=6, seed=6)              # the same length: the mark alone cannot tell
    assert len(again) == len(left) and again != left
    ok, frames, data = ask(e, 10, 0)
    assert frames == len(again) // 2 and data == again[:512].ljust(512, b"\0")
    assert ask(e, 11, 0)[1] == len(again) // 2


def test_a_mark_left_from_before_a_restart_does_not_count(audio):
    """The marks are never zeroed. After a boot the table points at the pool, so no mark is looked at;
    a first take clears its own."""
    e = engine(audio)
    for k in range(SLOTS):
        e.mc.w32(m.KEPT + 4 * k, (6 * BLOCK) ^ m.KEEP_MARK)                 # as if every slot had been kept at this length
    assert ask(e, 10, 0)[1] == 0
    left, _ = record(e, track=5, n=6, seed=7)
    assert len(left) == 2 * 6 * BLOCK and ask(e, 10, 0)[1] == 6 * BLOCK


def heard(e, track, blocks=8):
    """The track in stereo on its own stereo sample: what the voice loop puts out, every track."""
    e.set_slot(track, MODE, STEREO)
    return np.array([e.block(trig=1 << track if b == 0 else 0) for b in range(blocks)])


def test_recording_and_a_take_played_back_are_what_they_were(stock, audio):
    """The same blocks through the recorder image and this one: same take, same sound from it."""
    outs = []
    for built in (build_engine.patched_image(stock, rec=True), audio):
        e = engine(built)
        e.mc.write(BOX, bytes(m.KEEP_SIZE))
        left, right = record(e, track=5, n=5, seed=8)
        outs.append((left, right, heard(e, 5)))
    assert outs[0][0] == outs[1][0] and outs[0][1] == outs[1][1]
    assert np.array_equal(outs[0][2], outs[1][2]) and np.any(outs[1][2])


def test_a_loaded_sample_plays_at_a_takes_level(stock, audio):
    """What a kept take is after the next boot: the same audio as a loaded sample. In this image the
    two sound the same, to the bit. In the recorder image the take is the louder one."""
    def both(built):
        e = engine(built)
        left, right = record(e, track=5, n=6, seed=9)
        as_take = heard(e, 5)
        pool = {10: np.frombuffer(left, dtype=">i2").astype(np.int16), 11: np.frombuffer(right, dtype=">i2").astype(np.int16)}
        return as_take, heard(engine(built, pool), 5)
    as_take, as_sample = both(audio)
    assert np.array_equal(as_take, as_sample) and np.any(as_sample)
    as_take, as_sample = both(build_engine.patched_image(stock, rec=True))
    loud, soft = np.abs(as_take.astype(np.int64)).sum(), np.abs(as_sample.astype(np.int64)).sum()
    assert 1.99 < loud / soft < 2.01                        # there: 6 dB apart


def test_a_full_scale_sample_does_not_wrap(audio):
    for value in (32767, -32768):
        pool = {10: np.full(600, value, dtype=np.int16), 11: np.full(600, value, dtype=np.int16)}
        out = heard(engine(audio, pool), 5, blocks=6).astype(np.int64)
        on = out[np.nonzero(out)]
        assert len(on) and np.all(np.sign(on) == np.sign(value))


def test_cost_on_the_audio_cpu(stock, audio):
    def count(built, request):
        e = engine(built)
        e.mc.write(BOX, bytes(m.KEEP_SIZE))
        for t in range(m.N_VOICES):
            e.set_slot(t, MODE, 0)
        e.block()
        if request:
            e.mc.write(BOX + m.KEEP_REQ, b"\0\1")
        n0 = e.mc.insns
        e.block()
        return e.mc.insns - n0
    base = count(build_engine.patched_image(stock, rec=True), False)
    idle, answering = count(audio, False) - base, count(audio, True) - base
    assert 0 < idle <= 16                                   # two reads of the window and a compare
    assert answering < 6000                                 # one block in a save: 512 bytes copied
    assert (idle, answering) == COST


COST = (11, 1827)           # a block: nothing asked, and one request answered. Budget: 10,506 a voice


# ---- main CPU -----------------------------------------------------------------------------------

def sector_of(slot):
    return mm.SAMPLE_SECTOR0 + SECTORS * slot


class Rig:
    """The patched main program with the project save routine and the drive replaced by stubs."""

    def __init__(self, built):
        image, self.syms = built
        mc = self.mc = Machine()
        mc.map(0x40000000, 0x800000)
        mc.map(STORE, 0x100000)
        mc.map(mm.SHARED, 0x2000)
        mc.map(mm.AUDIO_UP & ~0xFFF, 0x1000)
        mc.map(0x4d800000, 0x2200000)                      # the pool's block, for the boot after
        mc.write(mm.BASE, image)
        mc.set_stack(STACK[1], 0x40000100)
        self.drive, self.writes, self.saves, self.stray = {}, [], [], []
        self.saved, self.fail_at = 1, None
        self.stub(mm.DRIVE_READ, lambda sector, n, dest: self.read(sector, n, dest))
        self.stub(mm.STORE_READ, lambda store, sector, n, dest, ctx: self.read(sector, n, dest))
        self.stub(mm.DRIVE_WRITE, lambda sector, n, src: self.write(sector, n, src))
        self.stub(mm.SAMPLE_STORE, lambda: STORE)
        self.stub(mm.PROJECT_SAVE, lambda a, b, c: self.save(a, b, c))
        for addr in (0x4016e92e, 0x4016e954, 0x4016dc10, 0x40111216, 0x401758e8):   # lock, unlock, a callback's end, a notice, progress
            self.stub(addr, None)
        mc.w32(mm.AUDIO_UP, 1)
        self.window = []                                   # (read or write, size) of every access to the shared window
        mc.uc.hook_add(UC_HOOK_MEM_WRITE, lambda uc, a, addr, size, v, u: self.window.append(("w", size)), begin=mm.SHARED, end=mm.SHARED + 0x1fff)
        mc.uc.hook_add(UC_HOOK_MEM_READ, lambda uc, a, addr, size, v, u: self.window.append(("r", size)), begin=mm.SHARED, end=mm.SHARED + 0x1fff)
        mc.uc.hook_add(UC_HOOK_MEM_WRITE, self.wrote)
        mc.uc.ctl_flush_tb()

    def stub(self, addr, fn):
        mc = self.mc
        mc.write(addr, b"\x4e\x75")

        def hook(uc, address, size, user):
            if fn is not None:
                sp = uc.reg_read(UC_M68K_REG_A7)
                args = [mc.r32(sp + 4 + 4 * k) for k in range(fn.__code__.co_argcount)]
                uc.reg_write(UC_M68K_REG_D0, fn(*args) & 0xFFFFFFFF)
        mc.uc.hook_add(UC_HOOK_CODE, hook, begin=addr, end=addr)

    def wrote(self, uc, access, address, size, value, user):
        if not (STACK[0] <= address < STACK[1] or mm.KEEP_BOX <= address < mm.KEEP_BOX + m.KEEP_ACK
                or STORE <= address < STORE + 0x20000 or 0x4d800000 <= address):
            self.stray.append(address)

    def read(self, sector, n, dest):
        self.mc.write(dest, b"".join(self.drive.get(sector + k, bytes(512)) for k in range((n + 511) // 512))[:n])
        return 0

    def write(self, sector, n, src):
        if self.fail_at is not None and len(self.writes) >= self.fail_at:
            return 5
        assert n == 512
        self.writes.append(sector)
        self.drive[sector] = bytes(self.mc.read(src, n))
        return 0

    def save(self, a, b, c):
        self.saves.append((a, b, c, len(self.writes)))
        return self.saved

    def serve(self, fn):
        """Call fn whenever the main CPU is waiting on a request, as the audio CPU's next block would."""
        def hook(uc, address, size, user):
            box = self.mc.read(mm.KEEP_BOX, m.KEEP_ACK + 4)
            if bytes(2) + box[m.KEEP_REQ:m.KEEP_REQ + 2] != box[m.KEEP_ACK:m.KEEP_ACK + 4]:
                fn()
        self.mc.uc.hook_add(UC_HOOK_CODE, hook, begin=self.syms["ask"], end=self.syms["take"] - 1)
        self.mc.uc.ctl_flush_tb()

    def keep(self, args=(0x1111, 0x2222, 0x3333)):
        return self.mc.call(self.syms["save_keep"], *args)

    def slot(self, k):
        """(header, the slot's samples as bytes) as the drive holds them."""
        first = self.drive.get(sector_of(k), bytes(512))
        frames = int.from_bytes(first[8:12], "big")
        body = first[64:] + b"".join(self.drive.get(sector_of(k) + j, bytes(512)) for j in range(1, (64 + 2 * frames + 511) // 512))
        return first[:64], body[:2 * frames]


class Takes:
    """The audio CPU's side as the tests above show it, for takes too long to emulate."""

    def __init__(self, rig, takes):
        self.rig, self.takes, self.kept, self.asked = rig, dict(takes), set(), []

    def __call__(self):
        mc = self.rig.mc
        box = bytes(mc.read(mm.KEEP_BOX, 8))
        slot, off = int.from_bytes(box[2:4], "big"), int.from_bytes(box[4:8], "big")
        self.asked.append((slot, off))
        frames, data = 0, b""
        if slot in self.takes:
            frames = len(self.takes[slot]) // 2
            if off == m.KEEP_DONE:
                self.kept.add(slot)
            elif slot in self.kept:
                frames = 0
            else:
                data = self.takes[slot][off:off + 512]
        mc.write(mm.KEEP_BOX + m.KEEP_FRAMES, frames.to_bytes(4, "big") + data.ljust(512, b"\0"))
        mc.write(mm.KEEP_BOX + m.KEEP_ACK, bytes(2) + box[:2])


def noise(n, seed):
    return np.random.default_rng(seed).integers(-32768, 32768, n).astype(">i2").tobytes()


def header(frames, slot):
    return b"SAMP" + bytes(4) + frames.to_bytes(4, "big") + (b"TAKE %02d %s" % (slot // 2 + 1, b"LR"[slot % 2:][:1])).ljust(16, b"\0") + bytes(36)


@pytest.fixture()
def rig(main):
    return Rig(main)


def test_code_space_is_a_run_nothing_reaches(stock3, official, main):
    runs = deadcode.survey(stock3, mm.BASE, mm.CODE_END, mm.ENTRY, [official.section(k) for k in (2, 4, 6, 8)])
    assert mm.CAVE_KEEP in deadcode.usable(runs)
    lo, hi = mm.CAVE_KEEP
    assert stock3[mm.off(lo) - 2:mm.off(lo)] == b"\x4e\x75" and stock3[mm.off(hi) - 2:mm.off(hi)] == b"\x4e\x75"
    assert not any(lo < b and a < hi for a, b in (mm.CAVE, mm.CAVE_REC, mm.CAVE_AMUTE, build_main.POOL_STAGE))
    assert all(lo <= main[1][s] < hi for s in ("ask", "take", "keep_takes", "save_keep"))
    # the two calls, and nothing else in the program, now go to it
    image = main[0]
    for call in mm.PROJECT_SAVE_CALLS:
        assert image[mm.off(call):mm.off(call) + 6] == b"\x4e\xb9" + main[1]["save_keep"].to_bytes(4, "big")
    assert stock3.count(b"\x4e\xb9" + mm.PROJECT_SAVE.to_bytes(4, "big")) == 2
    assert stock3.count(mm.PROJECT_SAVE.to_bytes(4, "big")) == 2


def test_the_stock_save_runs_first_and_its_answer_is_passed_on(rig):
    rig.serve(Takes(rig, {}))
    for answer in (1, 0x12345601, 0xFFFFFFFF):
        rig.saved = answer
        assert rig.keep((7, 8, 9)) == answer
        assert rig.saves[-1][:3] == (7, 8, 9)
    assert not rig.writes and not rig.stray


def test_a_failed_project_save_keeps_nothing(rig):
    takes = Takes(rig, {10: noise(960, 1), 11: noise(960, 2)})
    rig.serve(takes)
    box = bytes(rig.mc.read(mm.KEEP_BOX, m.KEEP_SIZE))
    for answer in (0, 0x100, 0xABCDEF00):                   # the low byte is the answer
        rig.saved = answer
        assert rig.keep() == answer
    assert not rig.writes and not takes.asked and bytes(rig.mc.read(mm.KEEP_BOX, m.KEEP_SIZE)) == box


def test_takes_go_to_their_slots_and_are_marked_kept(rig):
    takes = {10: noise(960, 1), 11: noise(960, 2), 62: noise(4000, 3), 63: noise(4000, 4), 0: noise(1, 5), 1: noise(1, 6),
             30: noise(224, 7), 31: noise(224, 8), 32: noise(225, 9), 33: noise(225, 10)}     # 224 frames: exactly one sector
    old = {k: bytes([k % 251]) * 512 for k in range(sector_of(0), sector_of(SLOTS))}
    rig.drive.update(old)
    audio = Takes(rig, takes)
    rig.serve(audio)
    assert rig.keep() == 1
    for slot, x in takes.items():
        assert rig.slot(slot) == (header(len(x) // 2, slot), x), slot
        tail = rig.drive[sector_of(slot) + (64 + len(x) - 1) // 512][(64 + len(x) - 1) % 512 + 1:]
        assert tail == bytes(len(tail))                     # zeros after the last sample, as stock leaves a slot
        # the store's table has it, by the stock scan
        entry = bytes(rig.mc.read(STORE + mm.SAMPLE_TABLE + 24 * slot, 24))
        assert entry[:9] == header(0, slot)[12:21] and int.from_bytes(entry[20:], "big") == len(x) // 2
    # only those slots' sectors, each once, and a slot's first sector last
    want = {sector_of(s) + j for s, x in takes.items() for j in range((64 + len(x) + 511) // 512)}
    assert set(rig.writes) == want and len(rig.writes) == len(want)
    for s, x in takes.items():
        mine = [w for w in rig.writes if sector_of(s) <= w < sector_of(s) + SECTORS]
        assert mine[-1] == sector_of(s) and mine[:-1] == sorted(mine[:-1])
    assert {k: v for k, v in rig.drive.items() if k not in want} == {k: v for k, v in old.items() if k not in want}
    assert audio.kept == set(takes) and not rig.stray
    assert rig.window and {size for _, size in rig.window} == {2, 4}       # words and longs, never a byte: as stock uses the window
    assert rig.saves[0][3] == 0                             # the project was saved before any of it
    # saving again writes nothing
    n = len(rig.writes)
    assert rig.keep() == 1 and len(rig.writes) == n


def test_a_full_take_fits_its_slot(rig):
    full = 2 * m.REC_MAX                                    # 10.24 s: 983,040 bytes
    rig.serve(Takes(rig, {20: noise(m.REC_MAX, 1), 21: noise(m.REC_MAX, 2)}))
    assert rig.keep() == 1
    for slot, seed in ((20, 1), (21, 2)):
        assert rig.slot(slot) == (header(m.REC_MAX, slot), noise(m.REC_MAX, seed))
    per = (64 + full + 511) // 512
    assert per == 1921 <= SECTORS and len(rig.writes) == 2 * per
    assert all(sector_of(20) <= w < sector_of(22) for w in rig.writes) and not rig.stray


def test_nothing_is_done_until_the_audio_cpu_is_up(rig):
    takes = Takes(rig, {10: noise(960, 1)})
    rig.serve(takes)
    rig.mc.w32(mm.AUDIO_UP, 0)
    assert rig.keep() == 1 and not rig.writes and not takes.asked and not rig.stray


def test_an_audio_cpu_that_does_not_answer_ends_it(rig):
    assert rig.keep() == 1                                  # nobody serves: the first request runs out of patience
    assert not rig.writes and not rig.stray
    assert bytes(rig.mc.read(mm.KEEP_BOX + m.KEEP_ACK, m.KEEP_SIZE - m.KEEP_ACK)) == bytes(m.KEEP_SIZE - m.KEEP_ACK)


@pytest.mark.parametrize("fail_at", [0, 1, 3])
def test_a_drive_error_stops_and_the_take_stays_unkept(rig, fail_at):
    audio = Takes(rig, {10: noise(960, 1), 11: noise(960, 2)})
    rig.serve(audio)
    rig.fail_at = fail_at
    assert rig.keep() == 1
    assert len(rig.writes) == fail_at and not audio.kept
    assert sector_of(10) not in rig.writes                  # the header goes last: the old one is still there
    rig.fail_at = None                                      # the next save does it all
    assert rig.keep() == 1 and audio.kept == {10, 11}
    assert rig.slot(10) == (header(960, 10), noise(960, 1))


def test_a_take_that_changes_while_it_is_read_gets_no_header(rig):
    class Growing(Takes):
        def __call__(self):
            box = bytes(self.rig.mc.read(mm.KEEP_BOX, 8))
            if box[2:] == (10).to_bytes(2, "big") + (960).to_bytes(4, "big"):          # while its third sector is fetched
                self.takes[10] = self.takes[10] + bytes(64)
            super().__call__()
    audio = Growing(rig, {10: noise(960, 1), 11: noise(960, 2)})
    rig.serve(audio)
    assert rig.keep() == 1
    assert sector_of(10) not in rig.writes and not audio.kept


# ---- both sides ---------------------------------------------------------------------------------

def test_a_take_recorded_on_the_audio_cpu_is_on_the_drive_after_a_save_and_in_the_pool_after_a_boot(audio, rig):
    e = engine(audio)
    left, right = record(e, track=5, n=30, seed=11)         # stereo sample 6: slots 10 and 11
    other, _ = record(e, track=0, n=3, seed=12)             # and a short one on slots 0 and 1
    e.mc.write(BOX, bytes(np.random.default_rng(1).integers(0, 256, m.KEEP_SIZE, dtype=np.uint8)))   # as the boot loader leaves it
    for t in range(m.N_VOICES):
        e.set_slot(t, MODE, 0)
    e.block()                                               # the audio CPU's first block settles the box
    rig.mc.write(mm.KEEP_BOX, bytes(e.mc.read(BOX, m.KEEP_SIZE)))
    blocks = []

    def audio_block():
        e.mc.write(BOX, bytes(rig.mc.read(mm.KEEP_BOX, m.KEEP_ACK)))               # the main CPU's fields
        e.block()
        blocks.append(1)
        rig.mc.write(mm.KEEP_BOX + m.KEEP_ACK, bytes(e.mc.read(BOX + m.KEEP_ACK, m.KEEP_SIZE - m.KEEP_ACK)))
    rig.serve(audio_block)
    assert rig.keep() == 1
    assert rig.slot(10) == (header(len(left) // 2, 10), left)
    assert rig.slot(11) == (header(len(right) // 2, 11), right)
    assert rig.slot(0)[1] == other
    sectors = sum((64 + len(x) + 511) // 512 for x in (left, right, other, other))
    assert len(rig.writes) == sectors
    assert len(blocks) == SLOTS + sectors + 4               # a question a slot, a sector a block, and one more for each of the 4 kept
    for k in (0, 1, 10, 11):
        assert e.mc.r32(m.KEPT + 4 * k) == slot_entry(e, k)[0] ^ m.KEEP_MARK
    n = len(rig.writes)
    assert rig.keep() == 1 and len(rig.writes) == n         # kept: a second save writes nothing
    assert not rig.stray
    # the next boot: the stock reader and our pool builder find them
    rig.mc.call(build_main.POOL_STAGE[0])
    mc = rig.mc
    assert mc.read(mm.POOL_STAGE, 1) == b"\xaa"
    at, got = mm.POOL_STAGE + 5, {}
    for k in range(SLOTS):
        frames = mc.r32(at)
        got[k] = bytes(mc.read(at + 4, 2 * frames))
        at += 4 + 2 * frames
    assert got[10] == left and got[11] == right and got[0] == other
    assert all(not got[k] for k in range(SLOTS) if k not in (0, 1, 10, 11))


# ---- the image ----------------------------------------------------------------------------------

def test_keep_image_builds_and_the_others_do_not_contain_it(official_path, official, stock3, audio, main):
    from tools import build
    quiet = lambda s: None
    raw, _, built, regions, syms = build.build(official_path, log=quiet, keep=True)
    assert sorted(regions) == [3, 7] and built.section(3) == main[0] and built.section(7) == audio[0]
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
    big = build.build(official_path, log=quiet, big=True)[2]
    lo, hi = mm.CAVE_KEEP
    assert big.section(3)[mm.off(lo):mm.off(hi)] == stock3[mm.off(lo):mm.off(hi)]
    for call in mm.PROJECT_SAVE_CALLS:
        assert big.section(3)[mm.off(call):mm.off(call) + 6] == b"\x4e\xb9" + mm.PROJECT_SAVE.to_bytes(4, "big")
    # apart from its own code and the two calls, section 3 is the big image's
    a, b = bytearray(big.section(3)), bytearray(built.section(3))
    for start, end in [mm.CAVE_KEEP] + [(c + 2, c + 6) for c in mm.PROJECT_SAVE_CALLS]:
        a[mm.off(start):mm.off(end)] = b[mm.off(start):mm.off(end)] = bytes(end - start)
    assert a == b
    # the stock routines that write a sample by themselves are still not reached, and not touched
    for dead in (mm.SAMPLE_ERASE, 0x4011222c, 0x40112376):
        assert built.section(3)[mm.off(dead):mm.off(dead) + 64] == stock3[mm.off(dead):mm.off(dead) + 64]
    # the audio CPU: the recorder image's, plus the answering step in the recorder's own run
    rec7 = build.build(official_path, log=quiet, rec=True)[2].section(7)
    assert "keep_step" in syms and m.REC_CAVES["z"][0] <= syms["keep_step"] < m.REC_CAVES["z"][1]
    diff = [k for k in range(len(rec7)) if rec7[k] != built.section(7)[k]]
    ours = list(m.CAVES.values()) + list(m.REC_CAVES.values())            # our code, and the three pointers to it
    ours += [(a, a + 4) for a in (m.UPDATE_TABLE + 4 * m.TWIN_ENGINE, m.RENDER_TABLE + 4 * m.TWIN_ENGINE, m.ISR_VOICE_LOOP_CALL + 2)]
    assert diff and all(any(m.off(s) <= k < m.off(e) for s, e in ours) for k in diff)
