"""The "big" image: sample slots of 1 MB. Section 3, OS 1.42."""
import shutil

import numpy as np
import pytest
from unicorn import UC_HOOK_CODE
from unicorn.m68k_const import UC_M68K_REG_A7, UC_M68K_REG_D0

from emu.machine import Machine
from tools import build, build_main
from tools import mainmap as mm
from tools import fw

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

SLOTS = 64
SECTORS = build_main.BIG_SLOT_SECTORS  # 2048 a slot
MAX_FRAMES = build_main.BIG_SLOT_MAX_BYTES // 2  # 524,256
FIRST, END = mm.SAMPLE_SECTOR0, mm.SAMPLE_SECTOR0 + SLOTS * SECTORS
STORE, SCRATCH = 0x41000000, 0x41080000
HEADER_READ, RENAME = 0x401132ec, 0x40111ed4
ROOM = SLOTS * (4 + 2 * mm.SAMPLE_MAX_FRAMES)  # what stock could stage after marker and length
# where the arithmetic of the routines we cannot run whole is run by itself: (start, stop)
SNIP_RENAME = (0x40111f52, 0x40111f64)
SNIP_ROUTE = (0x400b9ed0, 0x400b9f20)  # right after its moveq #8,d1: that address ends the snippet below
SNIP_ROUTE_SIZE = (0x400b9eb6, 0x400b9ece)
SNIP_LIST_SIZE = (0x400ba1c2, 0x400ba1dc)


@pytest.fixture(scope="module")
def stock3(official):
    assert official.version == "1.42"
    return official.section(3)


@pytest.fixture(scope="module")
def big(stock3):
    return build_main.patched_image(stock3, rec=True, big=True)


def sector_of(slot):
    return FIRST + SECTORS * slot


def header(frames, name=b"take"):
    return b"SAMP" + bytes(4) + frames.to_bytes(4, "big") + name.ljust(16, b"\0") + bytes(36)


class Rig:
    """The patched program in memory, with the drive routines replaced by a dictionary of sectors."""

    def __init__(self, image):
        mc = self.mc = Machine()
        mc.map(0x40000000, 0x800000)
        mc.map(STORE, 0x100000)
        mc.map(0x4d800000, 0x2200000)  # the pool's block and its neighbours
        mc.write(mm.BASE, image)
        mc.set_stack(0x407ff000, 0x40000100)
        mc.set_exits([0x40000100] + [s[1] for s in (SNIP_RENAME, SNIP_ROUTE, SNIP_ROUTE_SIZE, SNIP_LIST_SIZE)])
        self.drive, self.reads = {}, []
        self.stub(mm.DRIVE_READ, lambda sector, n, dest: self.read(sector, n, dest))
        self.stub(mm.STORE_READ, lambda store, sector, n, dest, ctx: self.read(sector, n, dest))
        for addr in (0x4016e92e, 0x4016e954, 0x4016dc10, 0x40111216):  # the lock, a callback's end, a notice
            self.stub(addr, None)
        mc.uc.ctl_flush_tb()

    def stub(self, addr, fn):
        mc = self.mc
        mc.write(addr, b"\x4e\x75")  # rts

        def hook(uc, address, size, user):
            if fn is not None:
                sp = uc.reg_read(UC_M68K_REG_A7)
                args = [mc.r32(sp + 4 + 4 * k) for k in range(fn.__code__.co_argcount)]
                uc.reg_write(UC_M68K_REG_D0, fn(*args) & 0xFFFFFFFF)
        mc.uc.hook_add(UC_HOOK_CODE, hook, begin=addr, end=addr)

    def read(self, sector, n, dest):
        self.reads.append((sector, n))
        data = b"".join(self.drive.get(sector + k, bytes(512)) for k in range((n + 511) // 512))
        self.mc.write(dest, data[:n])
        return 0

    def put(self, sector, data):
        data = bytes(data) + bytes(-len(data) % 512)
        for k in range(len(data) // 512):
            self.drive[sector + k] = data[512 * k:512 * k + 512]

    def put_sample(self, slot, samples, name=b"take", frames=None):
        samples = np.asarray(samples, dtype=np.int16)
        self.put(sector_of(slot), header(len(samples) if frames is None else frames, name) + samples.astype(">i2").tobytes())

    def sectors_read(self):
        return {s + k for s, n in self.reads for k in range((n + 511) // 512)}


@pytest.fixture()
def rig(big):
    return Rig(big[0])


def noise(n, seed):
    return np.random.default_rng(seed).integers(-32768, 32768, n).astype(np.int16)


# ---- where each routine looks -----------------------------------------------------------------

def test_the_scan_finds_every_slot_at_its_megabyte(rig):
    for slot in range(SLOTS):
        rig.put_sample(slot, [], name=b"slot%02d" % slot, frames=1000 + slot)
    rig.mc.write(STORE, bytes(0x20000))
    for slot in range(SLOTS):
        rig.reads.clear()
        rig.mc.call(mm.SAMPLE_SCAN, STORE, slot)
        assert rig.reads == [(sector_of(slot), 512)], slot
        entry = rig.mc.read(STORE + mm.SAMPLE_TABLE + 24 * slot, 24)
        assert entry[:6] == b"slot%02d" % slot and int.from_bytes(entry[20:], "big") == 1000 + slot


@pytest.mark.parametrize("frames,kept", [(mm.SAMPLE_MAX_FRAMES, True), (mm.SAMPLE_MAX_FRAMES + 1, True),
                                         (480000, True), (MAX_FRAMES, True), (MAX_FRAMES + 1, False)])
def test_a_slot_now_holds_up_to_a_megabyte_less_its_header(rig, frames, kept):
    rig.put_sample(9, [], frames=frames)
    rig.mc.write(STORE, bytes(0x20000))
    rig.mc.call(mm.SAMPLE_SCAN, STORE, 9)
    assert rig.mc.r32(STORE + mm.SAMPLE_TABLE + 24 * 9 + 20) == (frames if kept else 0)
    hdr = SCRATCH
    assert (rig.mc.call(HEADER_READ, 9, hdr) == 0) == kept  # the reader's own check agrees
    assert rig.mc.r32(hdr + 8) == frames


def test_a_header_where_stock_kept_its_odd_slots_is_not_a_sample_any_more(rig):
    rig.put(mm.SAMPLE_SECTOR0 + mm.SAMPLE_SECTORS * 5, header(300))  # stock slot 5: the middle of our slot 2
    rig.mc.write(STORE, bytes(0x20000))
    for slot in range(SLOTS):
        rig.mc.call(mm.SAMPLE_SCAN, STORE, slot)
        assert rig.mc.r32(STORE + mm.SAMPLE_TABLE + 24 * slot + 20) == 0


def test_every_routine_agrees_on_where_a_slot_is(rig):
    mc = rig.mc
    for slot in range(SLOTS):
        want = sector_of(slot)
        rig.reads.clear()
        mc.call(HEADER_READ, slot, SCRATCH)  # the header reader
        assert rig.reads == [(want, 512)]
        mc.set_reg(6, slot)  # rename: its sector, in d6
        mc.uc.reg_write(UC_M68K_REG_A7, 0x407fe000)
        mc.run(*SNIP_RENAME)
        assert mc.reg(6) == want
        frame = SCRATCH + 0x1000  # the /samples/<slot> route: a byte address
        mc.w32(SCRATCH, SCRATCH + 0x2000)
        mc.w32(frame - 516, slot + 1)  # the route counts slots from 1
        mc.set_reg(6, slot + 1)
        mc.set_reg(1, 8)
        mc.set_reg(8 + 2, SCRATCH)
        mc.set_reg(8 + 6, frame)
        mc.run(*SNIP_ROUTE)
        assert mc.r32(frame - 500) == want * 512 and mc.r32(frame - 492) == slot + 1
    assert sector_of(0) == mm.SAMPLE_SECTOR0 and sector_of(SLOTS - 1) + SECTORS == END == 139264
    assert mm.DRIVE_FREE[0] <= mm.SAMPLE_SECTOR0 + 64 * mm.SAMPLE_SECTORS and END <= mm.DRIVE_FREE[1]  # the new half is in the unused stretch


@pytest.mark.parametrize("snip,reg", [(SNIP_ROUTE_SIZE, 0), (SNIP_LIST_SIZE, 4)])
def test_the_size_told_to_the_computer_is_held_to_a_megabyte(rig, snip, reg):
    mc = rig.mc
    for size, want in ((0x100, 0x100), (0x80000, 0x80000), (0x80001, 0x80001), (0xfffff, 0xfffff),
                       (0x100000, 0x100000), (0x100001, 0x100000), (64 + 2 * MAX_FRAMES, 0x100000)):
        mc.set_reg(0, size)
        mc.set_reg(4, 0x7fffffff)
        mc.uc.reg_write(UC_M68K_REG_A7, 0x407fe000)
        mc.run(*snip)
        assert mc.reg(reg) == want, hex(size)


# ---- the pool the audio CPU is given at boot ----------------------------------------------------

def staged(rig):
    mc = rig.mc
    assert mc.read(mm.POOL_STAGE, 1) == b"\xaa"
    total = mc.r32(mm.POOL_STAGE + 1)
    body = mc.read(mm.POOL_STAGE + 5, total)
    out, at = [], 0
    for _ in range(SLOTS):
        n = int.from_bytes(body[at:at + 4], "big")
        out.append(np.frombuffer(body[at + 4:at + 4 + 2 * n], dtype=">i2").astype(np.int16))
        at += 4 + 2 * n
    assert at == total
    return out, total


def test_pool_builder_stages_what_is_in_the_slots(rig):
    samples = {0: noise(100, 1), 1: noise(MAX_FRAMES, 2), 5: noise(mm.SAMPLE_MAX_FRAMES + 1, 3),
               17: noise(32768 - 32, 4), 18: noise(1, 5), 62: noise(240000, 6), 63: noise(480000, 7)}
    for slot, x in samples.items():
        rig.put_sample(slot, x)
    rig.put(sector_of(30), b"JUNK" + bytes(60))  # not a sample
    rig.put_sample(31, [], frames=MAX_FRAMES + 1)  # a header that claims too much
    rig.mc.call(build_main.POOL_STAGE[0])
    got, total = staged(rig)
    for slot in range(SLOTS):
        assert np.array_equal(got[slot], samples.get(slot, np.zeros(0, dtype=np.int16))), slot
    assert total == 4 * SLOTS + 2 * sum(len(x) for x in samples.values())
    # every read stayed inside the slot it was for, and inside the sample area
    for slot in range(SLOTS):
        mine = {s for s in rig.sectors_read() if sector_of(slot) <= s < sector_of(slot) + SECTORS}
        need = (64 + 2 * len(samples[slot]) + 511) // 512 if slot in samples else 1
        assert mine == set(range(sector_of(slot), sector_of(slot) + need)), slot
    assert all(FIRST <= s < END for s in rig.sectors_read())


def test_pool_builder_never_stages_more_than_stock_could(rig):
    """36 slots of 10 s are more than the block holds. The ones that fit are staged whole, in order; one that does not
    fit is left out, and a short one after it still goes in. Nothing past the room is written.
    """
    mc = rig.mc
    lengths = {slot: 480000 for slot in range(36)}
    lengths.update({40: 5000, 41: 480000, 63: 77})
    for slot, n in lengths.items():
        rig.put_sample(slot, noise(n, 100 + slot))
    end = mm.POOL_STAGE + 5 + ROOM
    mc.write(end, b"\x5a" * (mm.AUDIO_IMAGE_STAGE + 0x100 - end))  # what lies behind, the audio CPU's program included
    mc.call(build_main.POOL_STAGE[0])
    got, total = staged(rig)
    used, want = 0, {}
    for slot in range(SLOTS):
        n = lengths.get(slot, 0)
        room = ROOM - used - 4 * (SLOTS - slot)
        want[slot] = n if 2 * n <= room else 0
        used += 4 + 2 * want[slot]
    assert total == used <= ROOM
    assert [len(x) for x in got] == [want[s] for s in range(SLOTS)]
    assert sum(1 for s in range(36) if want[s]) == 34 and want[40] == 5000 and want[41] == 0 and want[63] == 77
    for slot in (0, 33, 40, 63):
        assert np.array_equal(got[slot], noise(lengths[slot], 100 + slot))
    assert mc.read(end, mm.AUDIO_IMAGE_STAGE + 0x100 - end) == b"\x5a" * (mm.AUDIO_IMAGE_STAGE + 0x100 - end)
    assert ROOM + 5 <= mm.POOL_STAGE_BYTES and ROOM == 64 * (4 + 0x7ffc0)


def test_a_drive_laid_out_by_stock_boots_without_reading_outside_the_samples(rig):
    """First boot after the change: stock's 64 slots are still on the drive, 512 KB apart."""
    for k in range(64):
        rig.put(mm.SAMPLE_SECTOR0 + mm.SAMPLE_SECTORS * k, header(mm.SAMPLE_MAX_FRAMES - k) + noise(mm.SAMPLE_MAX_FRAMES - k, k).astype(">i2").tobytes())
    rig.mc.call(build_main.POOL_STAGE[0])
    got, total = staged(rig)
    for slot in range(32):  # stock's even slots show up as our first 32
        assert np.array_equal(got[slot], noise(mm.SAMPLE_MAX_FRAMES - 2 * slot, 2 * slot))
    assert all(len(got[slot]) == 0 for slot in range(32, 64))
    assert total <= ROOM and all(FIRST <= s < END for s in rig.sectors_read())


# ---- the image ------------------------------------------------------------------------------------

def test_big_image_differs_from_the_recorder_image_only_at_the_listed_places(stock3, big):
    image, syms = big
    rec, _ = build_main.patched_image(stock3, rec=True)
    allowed = set(range(*build_main.POOL_STAGE))
    for addr, stock, new, _ in build_main.BIG_SLOTS:
        assert len(bytes.fromhex(stock)) == len(bytes.fromhex(new))
        allowed |= set(range(addr, addr + len(bytes.fromhex(new))))
    diff = {mm.BASE + i for i in range(len(rec)) if rec[i] != image[i]}
    assert diff and diff <= allowed
    assert syms["pool_stage"] == build_main.POOL_STAGE[0] == mm.POOL_STAGE_BUILD
    # the routines stock never reaches are left exactly as they were: nothing calls them here either
    for dead in (mm.SAMPLE_ERASE, 0x4011222c, 0x40112376):
        assert image[mm.off(dead):mm.off(dead) + 64] == stock3[mm.off(dead):mm.off(dead) + 64]
        assert dead.to_bytes(4, "big") not in image
    # the pool builder is still reached by the one stock call, and still reads through the stock reader
    assert image[mm.off(0x4008287a):mm.off(0x4008287e)] == bytes.fromhex(fw.sx("1c8d04e33b82f02f"))
    assert mm.SAMPLE_READ.to_bytes(4, "big") in image[mm.off(build_main.POOL_STAGE[0]):mm.off(build_main.POOL_STAGE[1])]


def test_big_image_builds_and_the_others_do_not_contain_it(official_path, official, big):
    quiet = lambda s: None
    raw, _, built, regions, syms = build.build(official_path, log=quiet, big=True)
    assert sorted(regions) == [3, 7] and built.section(3) == big[0]
    rec = build.build(official_path, log=quiet, rec=True)[2]
    assert built.section(7) == rec.section(7)  # nothing changes on the audio CPU
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
    for addr, stock, new, _ in build_main.BIG_SLOTS:
        o = mm.off(addr)
        assert rec.section(3)[o:o + len(stock) // 2] == bytes.fromhex(stock)
        assert built.section(3)[o:o + len(new) // 2] == bytes.fromhex(new)
