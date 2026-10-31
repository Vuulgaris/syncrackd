"""The "double" image: the sample pool goes to the audio CPU in two halves. Section 3, OS 1.42."""
import shutil

import numpy as np
import pytest
from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn.m68k_const import UC_M68K_REG_A7, UC_M68K_REG_D0

from emu.machine import Machine
from tools import audiomap as m
from tools import build_main, deadcode
from tools import mainmap as mm
from tools import fw

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

SLOTS = 64
SECTORS = build_main.BIG_SLOT_SECTORS
MAX_BYTES = build_main.BIG_SLOT_MAX_BYTES  # of samples in a slot: 1,048,512
FIRST, END = mm.SAMPLE_SECTOR0, mm.SAMPLE_SECTOR0 + SLOTS * SECTORS
CHUNK = 2048
HALF = mm.POOL_HALF_CHUNKS * CHUNK  # 33,550,336
CAP = 2 * HALF
STAGE, DATA = mm.POOL_STAGE, mm.POOL_STAGE + 5
INDEX, STALL = mm.POOL_SEND_INDEX, mm.BOOT_STALL
STACK = (0x407f0000, 0x407ff000)
MEMCPY = 0x4011613c
SENDER = (0x40082fb4, 0x40082ff0)  # from "command 2" to just after the copy to the window


@pytest.fixture(scope="module")
def stock3(official):
    assert official.version == "1.42"
    return official.section(3)


@pytest.fixture(scope="module")
def double(stock3):
    return build_main.patched_image(stock3, double=True)


@pytest.fixture(scope="module")
def keep(stock3):
    return build_main.patched_image(stock3, keep=True)


def sector_of(slot):
    return FIRST + SECTORS * slot


def header(frames):
    return b"SAMP" + bytes(4) + frames.to_bytes(4, "big") + b"take".ljust(16, b"\0") + bytes(36)


def noise(n, seed):
    """n bytes of samples (n even)."""
    return np.random.default_rng(seed).integers(-32768, 32768, n // 2).astype(">i2").tobytes()


def stream(samples):
    """The pool as the audio CPU is to have it: for each slot its frame count and its samples. A slot that does not fit
    under the cap, with a count left for every slot after it, is empty.
    """
    out = bytearray()
    for slot in range(SLOTS):
        x = samples.get(slot, b"")
        if len(x) > CAP - len(out) - 4 * (SLOTS - slot):
            x = b""
        out += (len(x) // 2).to_bytes(4, "big") + x
    return bytes(out)


class Rig:
    def __init__(self, built):
        image, self.syms = built
        mc = self.mc = Machine()
        mc.map(0x40000000, 0x800000)
        mc.map(0x41bb0000, 0x10000)  # the exchange's variables
        mc.map(mm.SHARED, 0x2000)
        mc.map(0x4d800000, 0x2200000)  # the pool's block and its neighbours
        mc.write(mm.BASE, image)
        mc.set_stack(STACK[1], 0x40000100)
        mc.set_exits([0x40000100, SENDER[1]])
        self.slots, self.reads, self.copies = {}, [], []
        self.since, self.longest, self.clears, self.stray = 0, 0, 0, []
        self.stub(mm.DRIVE_READ, lambda sector, n, dest: self.read(sector, n, dest))
        self.stub(mm.STORE_READ, lambda store, sector, n, dest, ctx: self.read(sector, n, dest))
        self.stub(MEMCPY, None)
        for addr in (0x4016e92e, 0x4016e954, 0x4016dc10, 0x40111216):
            self.stub(addr, None)
        mc.uc.hook_add(UC_HOOK_MEM_WRITE, self.wrote)
        mc.uc.ctl_flush_tb()

    def stub(self, addr, fn):
        mc = self.mc
        stock = bytes(mc.read(addr, 2))
        mc.write(addr, b"\x4e\x75")

        def hook(uc, address, size, user):
            sp = uc.reg_read(UC_M68K_REG_A7)
            if addr == MEMCPY:  # the reader's own copies are done for it; the sender's is recorded
                dst, src, n = (mc.r32(sp + 4 + 4 * k) for k in range(3))
                self.copies.append((dst, src, n))
                if dst < mm.SHARED or dst >= mm.SHARED + 0x2000:
                    self.place(dst, bytes(mc.read(src, n)))
            elif fn is not None:
                args = [mc.r32(sp + 4 + 4 * k) for k in range(fn.__code__.co_argcount)]
                uc.reg_write(UC_M68K_REG_D0, fn(*args) & 0xFFFFFFFF)
        mc.uc.hook_add(UC_HOOK_CODE, hook, begin=addr, end=addr)
        return stock

    def allowed(self, address, n=1):
        return (STACK[0] <= address and address + n <= STACK[1]) or (DATA <= address and address + n <= DATA + HALF)

    def place(self, dest, data):
        """Bytes put into memory on the program's behalf: only its stack and the block's half."""
        if not self.allowed(dest, len(data)):
            self.stray.append((dest, len(data)))
        self.mc.write(dest, data)

    def wrote(self, uc, access, address, size, value, user):
        if address == STALL:
            self.clears += 1
            self.longest, self.since = max(self.longest, self.since), 0
        elif not (self.allowed(address, size) or STAGE <= address < DATA):
            self.stray.append((address, size))

    def read(self, sector, n, dest):
        slot, s = divmod(sector - FIRST, SECTORS)
        assert 0 <= slot < SLOTS and 512 * s + n <= 512 * SECTORS, "a read outside a slot"
        self.reads.append((slot, s, n))
        self.since += n
        self.place(dest, self.slots.get(slot, b"")[512 * s:512 * s + n].ljust(n, b"\0"))
        return 0

    def put(self, slot, samples, frames=None):
        self.slots[slot] = header(len(samples) // 2 if frames is None else frames) + samples

    def boot(self):
        """What stock does before the exchange: the one call to the pool builder."""
        self.mc.call(build_main.POOL_STAGE[0])
        return self.mc.r32(STAGE + 1)

    def chunk(self, i):
        """The sender, patched: the index is set, our routine says where the chunk is."""
        self.mc.w32(INDEX, i)
        return self.mc.call(self.syms["pool_chunk"])

    def send(self, order=None):
        """Every chunk, put where its number says, as the audio CPU does. Returns its pool."""
        total = self.mc.r32(STAGE + 1)
        count = (total + CHUNK - 1) // CHUNK
        pool = bytearray(count * CHUNK)
        for i in (range(count) if order is None else order):
            at = self.chunk(i)
            pool[i * CHUNK:(i + 1) * CHUNK] = self.mc.read(at, CHUNK)
        return bytes(pool[:total])


@pytest.fixture()
def rig(double):
    return Rig(double)


def big_set(seed=0, per=960000, slots=SLOTS):
    """Slots of 10 s each: 61.4 MB of pool with all 64, as a full set sent by the changed Transfer."""
    return {k: noise(per, seed + k) for k in range(slots)}


# ---- the numbers ----------------------------------------------------------------------------------

def test_two_halves_fit_what_stock_used_and_what_the_audio_cpu_has(official):
    assert HALF == 33550336 and HALF % CHUNK == 0
    assert HALF <= SLOTS * (4 + 2 * mm.SAMPLE_MAX_FRAMES)  # a half is no more of the block than stock could fill
    assert 5 + HALF <= mm.POOL_STAGE_BYTES and mm.POOL_STAGE + mm.POOL_STAGE_BYTES == mm.AUDIO_IMAGE_STAGE
    assert CAP <= mm.AUDIO_POOL_BYTES and CAP // CHUNK < 0x8000  # under the audio CPU's 64 MB; the index is a word
    assert SLOTS * (4 + 960000) <= CAP  # 64 slots of 10 s, what the changed Transfer sends
    assert SLOTS * (4 + 2 * m.REC_MAX) <= CAP  # 64 kept takes of 10.24 s
    # the audio CPU's end, as stock has it: the index is a word, taken as unsigned, times 2 KB, from its pool's base
    audio = official.section(7)
    at = m.off(0x40000fa8)
    assert audio[at:at + 24] == bytes.fromhex(fw.sx("c7b16a8677043d4f6fc531bc2815f97609064e357b8966c4") + "%08x" % mm.AUDIO_POOL)
    assert mm.AUDIO_POOL + mm.AUDIO_POOL_BYTES == m.SLOT_LEN - 4  # its slot table sits right after the 64 MB


def test_code_space_is_a_run_nothing_reaches(stock3, official, double):
    runs = deadcode.survey(stock3, mm.BASE, mm.CODE_END, mm.ENTRY, [official.section(k) for k in (2, 4, 6, 8)])
    assert mm.CAVE_HALVES in deadcode.usable(runs)
    lo, hi = mm.CAVE_HALVES
    others = (mm.CAVE, mm.CAVE_REC, mm.CAVE_AMUTE, mm.CAVE_KEEP, build_main.POOL_STAGE)
    assert not any(lo < b and a < hi for a, b in others)
    image, syms = double
    assert syms["pool_stage"] == build_main.POOL_STAGE[0] and lo <= syms["stage"] < hi and lo <= syms["pool_chunk"] < hi
    # the block's first byte is ours to use: the one routine that returns the block's address is called by the stock
    # builder alone, which is gone, and the one other place that names it is in a run nothing reaches
    assert stock3.count(mm.POOL_STAGE.to_bytes(4, "big")) == 2
    assert any(a <= 0x40082b64 < b for a, b, *_ in runs)


# ---- a pool of one half or less: as before -----------------------------------------------------

def test_a_pool_that_fits_one_half_is_built_and_sent_as_the_keep_image_does(double, keep):
    samples = {0: noise(200, 1), 1: noise(MAX_BYTES, 2), 5: noise(2 * mm.SAMPLE_MAX_FRAMES + 2, 3), 17: noise(65536, 4),
               18: noise(2, 5), 62: noise(480000, 6), 63: noise(960000, 7)}
    blocks = []
    for built in (double, keep):
        r = Rig(built)
        for slot, x in samples.items():
            r.put(slot, x)
        r.put(30, b"", frames=MAX_BYTES // 2 + 1)  # a header that claims too much
        r.slots[31] = b"JUNK" + bytes(60)
        total = r.boot()
        blocks.append(bytes(r.mc.read(STAGE, 5 + total)))
        if built is double:
            assert not r.stray
            reads = len(r.reads)
            for i in range((total + CHUNK - 1) // CHUNK):  # every chunk is where stock took it from, and no drive
                assert r.chunk(i) == DATA + (i << 11)
            assert len(r.reads) == reads and r.mc.read(STAGE, 1) == b"\xaa"
    assert blocks[0] == blocks[1]
    assert blocks[0][5:] == stream(samples) and blocks[0][0] == mm.POOL_MARK


def test_a_pool_of_exactly_one_half_never_fills_the_block_twice(rig):
    samples = big_set(per=1048000, slots=32)
    used = len(stream(samples))
    samples[32] = noise(HALF - used, 99)  # the last sample ends on the half's last byte
    assert len(stream(samples)) == HALF
    for slot, x in samples.items():
        rig.put(slot, x)
    assert rig.boot() == HALF
    reads = len(rig.reads)
    assert rig.send() == stream(samples)
    assert len(rig.reads) == reads and rig.mc.read(STAGE, 1) == b"\xaa" and not rig.stray


# ---- more than one half ----------------------------------------------------------------------------

def test_a_full_set_of_10_s_samples_reaches_the_audio_cpu_whole(rig):
    samples = big_set()
    for slot, x in samples.items():
        rig.put(slot, x)
    want = stream(samples)
    assert rig.boot() == len(want) == SLOTS * (4 + 960000)  # 61.4 MB: the keep image stops at half of this
    assert bytes(rig.mc.read(DATA, HALF)) == want[:HALF]  # the block: the first half, to its last byte
    first = len(rig.reads)
    got = rig.send()
    assert got == want
    assert rig.mc.read(STAGE, 1) == bytes([mm.POOL_MARK + 1]) and rig.mc.r32(STAGE + 1) == len(want)
    assert not rig.stray
    # each fill read about its own half of the samples from the drive, not the whole pool
    for part, reads in ((0, rig.reads[:first]), (1, rig.reads[first:])):
        data = sum(n for slot, s, n in reads)
        assert min(HALF, len(want) - part * HALF) <= data < min(HALF, len(want) - part * HALF) + 0x400000, part


@pytest.mark.parametrize("shift", [-4, -2, 0, 2, 100, -100])
def test_a_slot_may_lie_across_the_two_halves_anywhere(rig, shift):
    """shift: where slot 32's record starts against the half's end. -2 and -4 cut its count in two or put it whole in the
    first half, 0 starts it with the second, above 0 the cut is in slot 31's samples.
    """
    samples = {k: noise(MAX_BYTES - 64, k) for k in range(31)}
    used = len(stream(samples)) - 4 * (SLOTS - 31)  # after slot 30
    samples[31] = noise(HALF + shift - used - 4, 31)  # slot 31's record ends at HALF + shift
    samples[32] = noise(300000, 32)
    samples[40] = noise(MAX_BYTES, 40)
    samples[63] = noise(2, 63)
    for slot, x in samples.items():
        rig.put(slot, x)
    want = stream(samples)
    at = sum(4 + len(samples.get(k, b"")) for k in range(32))
    assert at == HALF + shift and want[at:at + 4] == (150000).to_bytes(4, "big")
    assert rig.boot() == len(want) > HALF
    assert rig.send() == want and not rig.stray


def test_the_exchange_may_start_again_at_any_point(rig):
    """A timeout makes stock send from chunk 0 again. Whatever the block held then, each chunk is right."""
    samples = big_set(seed=7, per=700000)
    for slot, x in samples.items():
        rig.put(slot, x)
    want = stream(samples)
    rig.boot()
    count = (len(want) + CHUNK - 1) // CHUNK
    h = mm.POOL_HALF_CHUNKS
    order = [0, 1, h - 1, h, h + 1, 0, 5, h + 7, h - 1, count - 1, 0, count - 1]
    padded = want.ljust(count * CHUNK, b"\0")
    for i in order:
        at = rig.chunk(i)
        assert rig.mc.read(STAGE, 1) == bytes([mm.POOL_MARK + (i >= h)])
        got = bytes(rig.mc.read(at, CHUNK))
        if (i + 1) * CHUNK <= len(want):
            assert got == padded[i * CHUNK:(i + 1) * CHUNK], i
        else:
            assert got[:len(want) - i * CHUNK] == want[i * CHUNK:], i
    assert not rig.stray


def test_what_does_not_fit_in_two_halves_is_left_out(rig):
    samples = {k: noise(MAX_BYTES, 100 + k) for k in range(SLOTS)}  # every slot as full as a slot gets: 4,352 bytes too many
    for slot, x in samples.items():
        rig.put(slot, x)
    want = stream(samples)
    assert SLOTS * (4 + MAX_BYTES) == CAP + 4352 and want[-4:] == bytes(4)
    total = rig.boot()
    assert total == len(want) <= CAP
    got = rig.send()
    assert got == want and not rig.stray
    assert len(got) == 63 * (4 + MAX_BYTES) + 4  # 63 loaded, the last one empty


# ---- the stall count ---------------------------------------------------------------------------------

def test_the_stall_count_is_cleared_all_through_a_fill(rig):
    samples = big_set(seed=3)
    for slot, x in samples.items():
        rig.put(slot, x)
    rig.boot()
    rig.clears = rig.longest = rig.since = 0
    rig.chunk(mm.POOL_HALF_CHUNKS)  # the block is filled again here
    assert rig.mc.read(STAGE, 1) == bytes([mm.POOL_MARK + 1])
    assert rig.clears >= (len(stream(samples)) - HALF) // 0x4000 + SLOTS and rig.mc.r32(STALL) == 0  # a slot, and a piece
    assert rig.longest <= 0x4000 + 3 * 512  # never more than 16 KB and a few sectors without clearing it
    assert rig.since == 0  # and the last thing it does is clear it


# ---- the sender's own instructions ----------------------------------------------------------------

def test_the_sender_copies_from_the_address_it_is_given(rig, stock3):
    """Stock's instructions from "command 2" to the copy into the window, with ours in the middle."""
    samples = big_set(seed=5)
    for slot, x in samples.items():
        rig.put(slot, x)
    total = rig.boot()
    mc = rig.mc
    assert bytes(mc.read(mm.POOL_CHUNK_SITE, 12)) == bytes.fromhex("48780800" "4eb9") + rig.syms["pool_chunk"].to_bytes(4, "big") + b"\x4e\x71"
    assert stock3[mm.off(mm.POOL_CHUNK_SITE):mm.off(mm.POOL_CHUNK_SITE) + 12] == bytes.fromhex(build_main.POOL_CHUNK_STOCK)
    h = mm.POOL_HALF_CHUNKS
    for i in (0, 3, h - 1, h, h + 9, (total - 1) // CHUNK):
        mc.w32(INDEX, i)
        mc.set_reg(8 + 4, MEMCPY)  # a4, as the task sets it up
        mc.uc.reg_write(UC_M68K_REG_A7, STACK[1] - 64)
        rig.copies.clear()
        mc.run(*SENDER)
        assert mc.uc.reg_read(UC_M68K_REG_A7) == STACK[1] - 64 - 12  # three arguments, as stock pushed them
        assert rig.copies[-1] == (mm.SHARED + 0x800, DATA + ((i - (h if i >= h else 0)) << 11), 0x800)
        assert int.from_bytes(mc.read(mm.SHARED + 2, 2), "big") == 2 and int.from_bytes(mc.read(mm.SHARED + 0xc, 2), "big") == i
        assert mc.reg(2) == (total + 2047) >> 11  # the chunk count stock goes on to compare with


# ---- the image ---------------------------------------------------------------------------------------

def test_double_image_builds_and_the_others_do_not_contain_it(official_path, official, stock3, double):
    from tools import build
    quiet = lambda s: None
    raw, _, built, regions, syms = build.build(official_path, log=quiet, double=True)
    assert sorted(regions) == [3, 7] and built.section(3) == double[0]
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
    kept = build.build(official_path, log=quiet, keep=True)[2]
    assert built.section(7) == kept.section(7)  # nothing changes on the audio CPU
    lo, hi = mm.CAVE_HALVES
    assert kept.section(3)[mm.off(lo):mm.off(hi)] == stock3[mm.off(lo):mm.off(hi)]
    assert kept.section(3)[mm.off(mm.POOL_CHUNK_SITE):mm.off(mm.POOL_CHUNK_SITE) + 12] == bytes.fromhex(build_main.POOL_CHUNK_STOCK)
    # apart from the builder, its new code and the one call in the sender, section 3 is the keep image's
    a, b = bytearray(kept.section(3)), bytearray(built.section(3))
    for start, end in (mm.CAVE_HALVES, build_main.POOL_STAGE, (mm.POOL_CHUNK_SITE, mm.POOL_CHUNK_SITE + 12)):
        a[mm.off(start):mm.off(end)] = b[mm.off(start):mm.off(end)] = bytes(end - start)
    assert a == b
