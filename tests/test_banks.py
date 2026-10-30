"""The "bank" image: three sample banks on the +Drive, one a project (engine/banks.c). OS 1.42 only.

The drive holds three runs of 64 slots. Every place in the program that names one of the three
routines that touch the drive names a routine of ours for it, which moves a sector of the first
run to the bank that is loaded and jumps to stock's. One sector of ours after the third run says
which bank is loaded and which each project was saved with.

Emulated here: our three ways in with the stock routines behind them played by the test; the
stock store's read, write, scan and sample readers and our boot pool builder, run as they are,
through them, against a drive that is a Python dictionary; the save and load hooks with the
project routines played by the test and the audio CPU's side as tests/test_load.py shows it, and
once joined to the real audio program; the sampling page's BANK place.

Nothing here says the part of the drive after the samples behaves like the rest on a unit, how
long 64 slots take to load, or what the unit shows meanwhile: see docs/FINDINGS.md.
"""
import shutil

import numpy as np
import pytest
from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE
from unicorn.m68k_const import UC_M68K_REG_A7, UC_M68K_REG_D0

from emu.machine import Machine
from tools import audiomap as m
from tools import build_engine, build_main, deadcode
from tools import mainmap as mm
from test_keep import STORE, Takes, header, noise, sector_of
from test_load import PUT, Audio, LoadRig, ask, engine, heard, sample, slot_entry, buffer_of, take
from test_pagerec import ALL, MODE, REC
from test_recorder import MainRig, frames, junk, make_block
from test_sample_store import operands
import test_page

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

NOW, WANT, BUSY = mm.CAVE_BANK[0], mm.CAVE_BANK[0] + 4, mm.CAVE_BANK[0] + 8
BIG = m.KEEP_BIG
RING = m.MAILBOX + m.MAILBOX_RING                   # the recorder's ring in the window: 1024 bytes, two sectors of a big put
SLOT_AT = mm.POOL_STAGE + 0x100000                  # where a slot is read to: a megabyte into the boot's block
FIRST, RUN, MARK = mm.BANK_FIRST, mm.BANK_SECTORS, mm.BANK_MARK_SECTOR
UNKNOWN = 0xFFFFFFFF
SLOTS = 64
BOX = m.KEEP_BOX
PROGRESS = 0x41090000                               # the progress object the Project Load job hands on
STACK = (0x407f0000, 0x407ff000)


@pytest.fixture(scope="module")
def stock3(official):
    assert official.version == "1.42"
    return official.section(3)


@pytest.fixture(scope="module")
def main(stock3):
    return build_main.patched_image(stock3, bank=True)


@pytest.fixture(scope="module")
def audio(official):
    return build_engine.patched_image(official.section(7), bank=True)


def marker(now=0, of=None, magic=mm.BANK_MAGIC, magic2=None):
    """Our sector as engine/banks.c writes it."""
    table = bytearray(b"\xff" * 128)
    for project, bank in (of or {}).items():
        table[project] = bank
    magic2 = magic ^ 0xFFFFFFFF if magic2 is None else magic2
    return (magic.to_bytes(4, "big") + magic2.to_bytes(4, "big") + now.to_bytes(4, "big") + bytes(table)).ljust(512, b"\xff")


# ---- the three ways in ---------------------------------------------------------------------------

class Ways:
    """Our three routines with stock's three behind them played by the test."""

    def __init__(self, built, bank=0, mark=None, fails=False):
        image, self.syms = built
        mc = self.mc = Machine()
        mc.map(0x40000000, 0x800000)
        mc.write(mm.BASE, image)
        mc.set_stack(STACK[1], 0x40000100)
        self.calls, self.mark, self.fails = [], mark, fails
        for name, addr in (("read", mm.DRIVE_READ), ("write", mm.DRIVE_WRITE), ("erase", mm.DRIVE_ERASE)):
            self.stub(addr, name)
        mc.w32(NOW, bank)
        mc.uc.ctl_flush_tb()

    def stub(self, addr, name):
        mc = self.mc
        mc.write(addr, b"\x4e\x75")

        def hook(uc, address, size, user):
            sp = uc.reg_read(UC_M68K_REG_A7)
            args = tuple(mc.r32(sp + 4 + 4 * k) for k in range(5))
            self.calls.append((name,) + args)
            answer = 0x600D0000 + len(self.calls)                   # stock's answer comes back untouched
            if name == "read" and args[0] == MARK and args[2] == self.syms["bank_buf"]:      # ours, of our sector
                answer = 5 if self.fails else 0
                if not self.fails:
                    mc.write(args[2], self.mark if self.mark is not None else bytes(512))
            uc.reg_write(UC_M68K_REG_D0, answer)
        mc.uc.hook_add(UC_HOOK_CODE, hook, begin=addr, end=addr)

    def go(self, way, sector, *rest):
        """Call one of ours as a caller of the stock routine would. -> (the sector stock got, the answer)."""
        self.calls = []
        rest = rest or (0x1234, 0x40700000, 0xAAAA5555, 0x0BADF00D)
        answer = self.mc.call(self.syms["bank_" + way], sector, *rest)
        last = self.calls[-1]
        assert last[0] == way and last[2:2 + len(rest)] == tuple(rest)[:4]     # only the sector is ever touched
        return last[1], answer

    @property
    def now(self):
        return self.mc.r32(NOW)

    @property
    def want(self):
        return self.mc.r32(WANT)


EDGES = (0, 1, 2048, 4096, FIRST - 1, FIRST, FIRST + 1, FIRST + 2048 * 63, FIRST + RUN - 1, FIRST + RUN, FIRST + RUN + 1,
         FIRST + 2 * RUN - 1, FIRST + 2 * RUN, MARK - 1, MARK, MARK + 1, 499712, 516096, 524288, 1572863, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF)


def test_the_layout_is_three_runs_and_a_sector_in_the_part_nothing_uses():
    assert (FIRST, RUN) == (mm.SAMPLE_SECTOR0, SLOTS * build_main.BIG_SLOT_SECTORS)
    assert MARK == FIRST + 3 * RUN == 401408 and MARK * 512 == 196 * 2 ** 20
    free = dict((name, (lo, hi)) for name, lo, hi in mm.DRIVE_MAP)
    work = min(lo for name, (lo, hi) in free.items() if lo > FIRST + RUN)      # the next thing stock keeps on the drive
    assert work == 499712 and MARK + 1 <= work                                 # 244 MB: the three runs and our sector end well before


@pytest.mark.parametrize("way", ["read", "write", "erase"])
@pytest.mark.parametrize("bank", [0, 1, 2])
def test_a_samples_sector_goes_to_the_loaded_bank_and_every_other_sector_is_left(main, way, bank):
    w = Ways(main, bank=bank)
    for sector in EDGES:
        got, answer = w.go(way, sector)
        inside = FIRST <= sector < FIRST + RUN
        assert got == (sector + bank * RUN if inside else sector), hex(sector)
        assert answer == 0x600D0001 and len(w.calls) == 1          # one call of stock's, its answer handed back
    assert w.now == bank                                            # and nothing settled or read on the way


def test_no_sector_can_be_sent_outside_the_three_runs(main):
    """Whatever the number that says which bank: a sample's sector lands in one of the three runs, in the place
    it had in the first, and nothing else moves at all."""
    rng = np.random.default_rng(1)
    for bank in (0, 1, 2, 3, 4, 255, 0x10000, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFE, UNKNOWN):
        for mark in (None, marker(now=2), marker(now=7), bytes(rng.integers(0, 256, 512, dtype=np.uint8))):
            w = Ways(main, bank=bank, mark=mark)
            sectors = list(EDGES) + [int(x) for x in rng.integers(FIRST, FIRST + RUN, 6)] + [int(x) for x in rng.integers(0, 2 ** 32, 6)]
            for sector in sectors:
                got, _ = w.go("write", sector)
                if FIRST <= sector < FIRST + RUN:
                    assert got < MARK and (got - sector) % RUN == 0 and (got - sector) // RUN in (0, 1, 2), (bank, hex(sector))
                else:
                    assert got == sector, (bank, hex(sector))


def test_the_first_sample_sector_asked_for_reads_which_bank_is_loaded(main):
    """The image starts with "not known". Our sector is read once, by stock's own read, and then the sector is moved."""
    assert int.from_bytes(main[0][mm.off(NOW):mm.off(NOW) + 8], "big") == UNKNOWN << 32
    for now in (0, 1, 2):
        w = Ways(main, bank=UNKNOWN, mark=marker(now=now))
        assert w.go("read", 4096)[0] == 4096 and w.now == UNKNOWN and len(w.calls) == 1      # not a sample's: nothing is looked up
        assert w.go("read", FIRST + 5)[0] == FIRST + 5 + now * RUN
        assert w.calls[0][:3] == ("read", MARK, 512) and w.calls[0][3] == w.syms["bank_buf"] and len(w.calls) == 2
        assert (w.now, w.want) == (now, now)
        assert w.go("write", FIRST)[0] == FIRST + now * RUN and len(w.calls) == 1            # known from here on


@pytest.mark.parametrize("mark", [None, bytes(512), b"\xff" * 512, marker(now=3), marker(now=0xFFFFFFFF), marker(now=1, magic=0x42414e4a),
                                  marker(now=1, magic2=0), marker(now=2)[:4] + bytes(508)])
def test_a_drive_without_our_sector_is_on_the_first_bank(main, mark):
    w = Ways(main, bank=UNKNOWN, mark=mark)
    assert w.go("read", FIRST + 100)[0] == FIRST + 100
    assert (w.now, w.want) == (0, 0)


def test_a_drive_that_does_not_read_is_asked_three_times_and_no_more(main):
    w = Ways(main, bank=UNKNOWN, mark=marker(now=2), fails=True)
    assert w.go("read", FIRST)[0] == FIRST and w.now > 2            # the first bank for this once, and nothing settled
    w.fails = False
    assert w.go("read", FIRST)[0] == FIRST + 2 * RUN and w.now == 2     # asked again, and answered
    w = Ways(main, bank=UNKNOWN, mark=marker(now=2), fails=True)    # a sector that never reads
    for k in range(3):
        assert w.go("read", FIRST + k)[0] == FIRST + k and len(w.calls) == 2
    assert w.now == 0                                               # the first bank it is: no failed read before every other read
    assert w.go("read", FIRST)[0] == FIRST and len(w.calls) == 1


def test_every_place_that_named_a_drive_routine_names_ours(stock3, official, main):
    image, syms = main
    for uses, stock, ours in ((mm.DRIVE_READ_USES, mm.DRIVE_READ, "bank_read"), (mm.DRIVE_WRITE_USES, mm.DRIVE_WRITE, "bank_write"),
                              (mm.DRIVE_ERASE_USES, mm.DRIVE_ERASE, "bank_erase")):
        assert operands(stock3, stock) == [a + 2 for a in uses]     # all of them, as tests/test_sample_store.py lists them
        for site in uses:
            assert image[mm.off(site):mm.off(site) + 2] == stock3[mm.off(site):mm.off(site) + 2]
            assert int.from_bytes(image[mm.off(site) + 2:mm.off(site) + 6], "big") == syms[ours]
    # what still names stock's three is ours alone: the three jumps, and the one read of our sector
    lo, hi = mm.CAVE_BANK
    left = [a for stock in (mm.DRIVE_READ, mm.DRIVE_WRITE, mm.DRIVE_ERASE) for a in operands(image, stock)]
    assert len(left) == 4 and all(lo <= a < hi for a in left)
    assert sorted(operands(image, mm.DRIVE_READ)) == sorted([syms["bank_read"] + 4] + [a for a in left if a > syms["bank_buf"]])
    # the code is in a run nothing reaches, and the two numbers are where engine/sampler.h says
    runs = deadcode.survey(stock3, mm.BASE, mm.CODE_END, mm.ENTRY, [official.section(k) for k in (2, 4, 6, 8)])
    assert mm.CAVE_BANK in deadcode.usable(runs)
    assert stock3[mm.off(lo) - 2:mm.off(lo)] == b"\x4e\x75" and stock3[mm.off(hi) - 2:mm.off(hi)] == b"\x4e\x75"
    others = (mm.CAVE, mm.CAVE_REC, mm.CAVE_AMUTE, mm.CAVE_KEEP, mm.CAVE_HALVES, mm.CAVE_TEXT, mm.CAVE_PAGE, mm.CAVE_PAGE2, build_main.POOL_STAGE)
    assert not any(lo < b and a < hi for a, b in others)
    assert (syms["bank_now"], syms["bank_want"], syms["bank_busy"]) == (NOW, WANT, BUSY) and mm.BANK_VARS == 12
    assert all(lo + mm.BANK_VARS <= syms[s] < hi for s in ("bank_read", "bank_write", "bank_erase", "bank_start", "bank_saved", "bank_loaded", "load_keep"))


# ---- stock's own code through them, and the hooks ----------------------------------------------------

class BankRig(LoadRig):
    """tests/test_load.py's rig on the bank image: the stock store runs as it is, and under it the three drive
    routines are the test's, behind ours."""

    def __init__(self, built, bank=0):
        self.erased, self.bar = [], []
        super().__init__(built)
        self.stub(mm.PROGRESS_STEP, lambda obj, done, total: self.bar.append((obj, done, total)) or 0)
        self.mc.write(PROGRESS, bytes(8) + b"\x40\x12\x34\x56")       # a job's progress object: its third long is set
        self.mc.map(0x41bbf000, 0x1000)                             # the boot's stall count and chunk index, for our pool builder
        self.stub(mm.DRIVE_ERASE, lambda sector, n: self.erased.append((sector, n)) or 0)
        self.mc.w32(NOW, bank)
        self.mc.w32(WANT, bank)

    def wrote(self, uc, access, address, size, value, user):
        lo, hi = mm.CAVE_BANK
        if not (lo <= address < lo + mm.BANK_VARS or self.syms["bank_buf"] <= address < self.syms["bank_buf"] + 512
                or 0x41bbf000 <= address < 0x41bc0000 or mm.SHARED + RING <= address < mm.SHARED + RING + 1024):
            super().wrote(uc, access, address, size, value, user)

    def put(self, slot, data, name=None, bank=0):
        """A sample in a bank's slot, as Transfer leaves it there."""
        raw = (name or header(len(data) // 2, slot)) + data
        raw = raw.ljust((len(raw) + 511) // 512 * 512, b"\0")
        for j in range(len(raw) // 512):
            self.drive[sector_of(slot) + bank * RUN + j] = raw[512 * j:512 * j + 512]

    @property
    def now(self):
        return self.mc.r32(NOW)

    @property
    def want(self):
        return self.mc.r32(WANT)

    @property
    def mark(self):
        """(the loaded bank, {project: bank}) as our sector on the drive says, or None."""
        raw = self.drive.get(MARK)
        if raw is None or raw[:8] != marker()[:8]:
            return None
        return int.from_bytes(raw[8:12], "big"), {k: raw[12 + k] for k in range(128) if raw[12 + k] != 0xFF}

    def name(self, slot):
        """The slot's name as the store's table holds it after a scan."""
        raw = bytes(self.mc.read(STORE + mm.SAMPLE_TABLE + 24 * slot, 16))
        return raw[:raw.index(0)].decode() if raw[0] else ""


class BankAudio(Audio):
    """The audio CPU's side as the tests of the audio program below show it: a put with KEEP_BIG is three
    sectors, the second and third from the ring."""

    def __call__(self):
        mc = self.rig.mc
        box = bytes(mc.read(mm.KEEP_BOX, m.KEEP_SIZE))
        slot, off = int.from_bytes(box[2:4], "big"), int.from_bytes(box[4:8], "big")
        if slot & PUT and slot & BIG and off != m.KEEP_DONE:
            self.asked.append((slot, off))
            self.busy.append(mc.r32(BUSY))
            buf = self.sent.setdefault(slot & ~(PUT | BIG), bytearray())
            buf[off:off + 1536] = box[16:] + bytes(mc.read(mm.SHARED + RING, 1024))
            mc.write(mm.KEEP_BOX + m.KEEP_ACK, bytes(2) + box[:2])
        else:
            assert not slot & BIG
            super().__call__()

    busy = []


def big_pieces(data):
    return list(range(0, len(data), 1536))


def named(text, frames):
    return b"SAMP" + bytes(4) + frames.to_bytes(4, "big") + text.encode().ljust(16, b"\0") + bytes(36)


@pytest.fixture()
def rig(main):
    return BankRig(main)


def test_the_store_reads_and_writes_the_loaded_bank(main):
    """Stock's own read and write of the store, as they are. A sample's sector comes from, and goes to, the bank."""
    for bank in (0, 1, 2):
        r = BankRig(main, bank=bank)
        r.drive[FIRST + 7 + bank * RUN] = bytes([bank + 1]) * 512
        r.drive[4100] = b"\x77" * 512                               # a sound's sector: no bank has it
        buf = 0x41080000
        assert r.mc.call(mm.STORE_READ, STORE, FIRST + 7, 512, buf) == 0 and bytes(r.mc.read(buf, 512)) == bytes([bank + 1]) * 512
        assert r.mc.call(mm.STORE_READ, STORE, 4100, 512, buf) == 0 and bytes(r.mc.read(buf, 512)) == b"\x77" * 512
        assert r.reads == [(FIRST + 7 + bank * RUN, 512), (4100, 512)]
        r.mc.write(buf, b"\x3c" * 512)
        none = 0x41081000
        r.mc.write(none, bytes(12))
        assert r.mc.call(mm.STORE_WRITE, STORE, FIRST + 9, 512, buf, none, 0) == 0
        assert r.writes == [FIRST + 9 + bank * RUN] and r.drive[FIRST + 9 + bank * RUN] == b"\x3c" * 512


def test_the_scan_names_the_slots_of_the_loaded_bank(main):
    r = BankRig(main, bank=1)
    r.put(0, sample(100, 1), name=named("KICK L", 100), bank=0)
    r.put(0, sample(200, 2), name=named("PAD L", 200), bank=1)
    r.put(5, sample(300, 3), name=named("ONLY IN B", 300), bank=1)
    r.put(9, sample(300, 4), name=named("ONLY IN A", 300), bank=0)
    r.mc.call(mm.SCAN_ALL, STORE)
    assert (r.name(0), r.name(5), r.name(9)) == ("PAD L", "ONLY IN B", "")
    r.mc.w32(NOW, 0)
    r.mc.call(mm.SCAN_ALL, STORE)
    assert (r.name(0), r.name(5), r.name(9)) == ("KICK L", "", "ONLY IN A")


def test_the_boot_builds_the_pool_from_the_bank_our_sector_names(main):
    """Our pool builder (engine/poolhalves.c) and stock's readers under it, as they are, on a unit just switched on."""
    for now in (None, 0, 2):
        r = BankRig(main, bank=UNKNOWN)
        a, c = sample(700, 1), sample(900, 2)
        r.put(3, a, bank=0)
        r.put(3, c, bank=2)
        r.put(40, c, bank=2)
        if now is not None:
            r.drive[MARK] = marker(now=now)
        r.mc.call(build_main.POOL_STAGE[0])
        at, got = mm.POOL_STAGE + 5, {}
        for k in range(SLOTS):
            frames = r.mc.r32(at)
            got[k] = bytes(r.mc.read(at + 4, 2 * frames))
            at += 4 + 2 * frames
        want = {3: c, 40: c} if now == 2 else {3: a}
        assert {k: v for k, v in got.items() if v} == want
        assert r.now == (now or 0) and not r.writes and not r.stray     # and the drive was only read
        assert r.reads[0] == (MARK, 512)                            # our sector first, before any slot


def test_saving_a_project_writes_down_its_bank_when_that_is_news(rig):
    rig.serve(Takes(rig, {}))
    rig.mc.w32(WANT, 1)
    assert rig.keep((7, 12, PROGRESS)) == 1                                # project 12, with BANK turned to B
    assert rig.mark == (0, {12: 1}) and rig.writes == [MARK]        # the loaded bank is still A: nothing is loaded by a save
    assert (rig.now, rig.want) == (0, 1)
    assert rig.keep((7, 12, PROGRESS)) == 1 and rig.writes == [MARK]       # the same again: nothing to write
    rig.mc.w32(WANT, 2)
    assert rig.keep((7, 40, PROGRESS)) == 1 and rig.mark == (0, {12: 1, 40: 2})
    rig.mc.w32(WANT, 0)
    assert rig.keep((7, 12, PROGRESS)) == 1 and rig.mark == (0, {12: 0, 40: 2})
    assert rig.writes == [MARK] * 3 and not rig.stray
    for project in (128, 129, 0xFFFFFFFF):                          # not one of the 128
        assert rig.keep((7, project, PROGRESS)) == 1
    rig.saved = 0                                                   # a save that failed
    rig.mc.w32(WANT, 2)
    assert rig.keep((7, 12, PROGRESS)) == 0
    assert rig.writes == [MARK] * 3 and rig.mark == (0, {12: 0, 40: 2})


def test_a_take_is_kept_in_the_loaded_bank(main):
    r = BankRig(main, bank=2)
    takes = Takes(r, {10: noise(960, 1), 11: noise(960, 2)})
    r.serve(takes)
    assert r.keep((7, 5, PROGRESS)) == 1 and takes.kept == {10, 11}
    per = (64 + 2 * 960 + 511) // 512
    assert sorted(r.writes) == sorted([sector_of(s) + 2 * RUN + j for s in (10, 11) for j in range(per)] + [MARK])
    assert r.drive[sector_of(10) + 2 * RUN][:16] == header(960, 10)[:16]
    assert not any(FIRST <= w < FIRST + 2 * RUN for w in r.writes)      # the other two banks are not written
    assert r.mark == (2, {5: 2}) and r.name(10).startswith("TAKE 06")


def test_loading_a_project_on_the_loaded_bank_is_the_load_images_load(rig):
    rig.drive[MARK] = marker(now=0, of={12: 0})
    rig.put(10, sample(500, 1))
    audio = BankAudio(rig, {10: 960})
    rig.serve(audio)
    assert rig.load((7, 12, PROGRESS)) == 1
    assert audio.done == {10: 500} and audio.got(10) == sample(500, 1)
    assert [s for s, off in audio.asked if not s & PUT] == list(range(SLOTS))      # asked which hold a take, as before
    assert not rig.writes and (rig.now, rig.want) == (0, 0) and not rig.stray
    assert rig.reads[-2:] == [(sector_of(10), 512), (sector_of(10) + 1, 1024)]     # the slot in two reads: its first sector, the rest


def test_a_slot_is_read_in_two_reads_and_sent_three_sectors_a_request(rig):
    """The first build of this image read and sent a sector at a time: 1,921 of each for a full slot, and on the
    unit a full bank sat on the LOADING screen for minutes. Here a full slot is 2 reads and 641 requests."""
    full, small, edge = sample(m.REC_MAX, 1), sample(100, 2), sample(992, 3)
    rig.put(20, full)
    rig.put(21, small)
    rig.put(22, edge)
    rig.put(23, full, name=header(0x7FFFFFFF, 23))                  # a length no slot holds
    rig.drive[MARK] = marker(now=1, of={12: 0})
    rig.mc.w32(NOW, 1), rig.mc.w32(WANT, 1)
    audio = BankAudio(rig, {})
    audio.busy = []
    rig.serve(audio)
    rig.mc.write(mm.POOL_STAGE, b"\xaa" + (0x01234567).to_bytes(4, "big"))        # the boot's mark and length, as it left them
    assert rig.load((7, 12, PROGRESS)) == 1
    assert audio.got(20) == full and audio.got(21) == small and audio.got(22) == edge and audio.got(23) == full
    assert audio.done[20] == m.REC_MAX and audio.done[23] == m.REC_MAX
    per = (64 + 2 * m.REC_MAX + 511) // 512
    mine = [(sector, n) for sector, n in rig.reads if sector_of(20) <= sector < sector_of(21)]
    # stock's scan reads the first sector for the name; then ours: the first sector, and the rest, which the store's
    # read hands the drive 64 KB at a time. 16 reads of the drive where the first build made 1,921, and never past the slot's end
    assert mine[:2] == [(sector_of(20), 512)] * 2 and per == 1921
    assert mine[2:] == [(sector_of(20) + 1 + 128 * k, 65536) for k in range(15)] and 15 * 65536 == 512 * (per - 1)
    assert [(sector, n) for sector, n in rig.reads if sector_of(21) <= sector < sector_of(22)] == [(sector_of(21), 512)] * 2
    assert [off for s, off in audio.asked if s == 20 | PUT | BIG] == big_pieces(full) and len(big_pieces(full)) == 640
    assert [off for s, off in audio.asked if s & ~BIG == 22 | PUT] == [0, 1536, m.KEEP_DONE]      # 1,984 bytes: two requests and the last word
    assert audio.busy and all(audio.busy) and rig.mc.r32(BUSY) == 0 # the feed is kept out for as long as it takes, and no longer
    assert bytes(rig.mc.read(mm.POOL_STAGE, 5)) == bytes(1) + (0x01234567).to_bytes(4, "big")      # the boot's mark is cleared, its length left
    assert {size for _, size in rig.window} == {2, 4} and not rig.stray


def test_the_loading_bar_moves_a_slot_at_a_time(rig):
    """A full bank is most of a minute. The bar stock's own load filled starts again and climbs, through stock's routine."""
    rig.put(10, sample(5000, 1))
    rig.drive[MARK] = marker(now=1, of={12: 0})
    rig.mc.w32(NOW, 1)
    rig.serve(BankAudio(rig, {}))
    assert rig.load((7, 12, PROGRESS)) == 1
    assert rig.bar == [(PROGRESS, k + 1, SLOTS) for k in range(SLOTS)]
    assert rig.loads[-1][:3] == (7, 12, PROGRESS)                   # the same object stock's load was handed
    rig.bar = []
    rig.mc.write(PROGRESS + 8, bytes(4))                            # an object with nothing behind it: stock does not call it, nor do we
    rig.drive[MARK] = marker(now=0, of={12: 1})
    assert rig.load((7, 12, PROGRESS)) == 1 and rig.now == 1 and not rig.bar
    assert rig.load((7, 12, 0)) == 1 and not rig.bar                # no object at all


def test_the_flag_comes_down_whatever_ends_a_load(rig):
    rig.put(10, sample(5000, 1))
    rig.drive[MARK] = marker(now=1, of={12: 0})
    rig.mc.w32(NOW, 1)
    assert rig.load((7, 12, PROGRESS)) == 1 and rig.mc.r32(BUSY) == 0     # nobody answers
    rig.mc.w32(NOW, 1)
    rig.drive[MARK] = marker(now=1, of={12: 0})
    rig.serve(BankAudio(rig, {}))
    rig.read_fails = len(rig.reads) + 4                             # the drive stops in the middle
    assert rig.load((7, 12, PROGRESS)) == 1 and rig.mc.r32(BUSY) == 0


def test_loading_a_project_on_another_bank_loads_every_slot_of_it(rig):
    a, b, b2 = sample(300, 1), sample(2000, 2), sample(1, 3)
    rig.put(10, a, name=named("IN A", 300), bank=0)
    rig.put(10, b, name=named("IN B", 2000), bank=1)
    rig.put(63, b2, name=named("LAST B", 1), bank=1)
    rig.drive[MARK] = marker(now=0, of={12: 1, 13: 0})
    audio = BankAudio(rig, {})
    rig.serve(audio)
    assert rig.load((7, 12, PROGRESS)) == 1
    assert (rig.now, rig.want) == (1, 1) and rig.mark == (1, {12: 1, 13: 0})
    assert audio.done == {**{k: 0 for k in range(SLOTS)}, 10: 2000, 63: 1}             # every slot, the empty ones as empty
    assert audio.got(10) == b and audio.got(63) == b2
    assert not [s for s, off in audio.asked if not s & PUT]         # nothing is asked: every slot goes
    assert (rig.name(10), rig.name(63), rig.name(0)) == ("IN B", "LAST B", "")     # stock's scan has read the new bank's names
    assert rig.writes == [MARK]                                     # the one write, our sector
    first = next(i for i, (sector, n) in enumerate(rig.reads) if FIRST <= sector < MARK)
    assert all(FIRST + RUN <= sector < FIRST + 2 * RUN for sector, n in rig.reads[first:])     # and only bank B is read
    assert not rig.stray
    # back again: project 13 is on A
    audio.done, audio.sent, audio.asked = {}, {}, []
    assert rig.load((7, 13, PROGRESS)) == 1
    assert (rig.now, rig.want) == (0, 0) and rig.mark == (0, {12: 1, 13: 0})
    assert audio.done[10] == 300 and audio.got(10) == a and audio.done[63] == 0 and rig.name(10) == "IN A"


def test_our_sector_says_the_new_bank_before_any_slot_is_loaded(rig):
    """A unit switched off in the middle boots on the bank it was going to."""
    rig.drive[MARK] = marker(now=0, of={12: 2})
    seen = []

    class Watching(BankAudio):
        def __call__(self):
            seen.append(rig.mark)
            super().__call__()
    rig.serve(Watching(rig, {}))
    assert rig.load((7, 12, PROGRESS)) == 1
    assert seen and all(m == (2, {12: 2}) for m in seen)


def test_a_project_our_sector_does_not_know_is_on_the_first_bank(main):
    """Every project made before this image: its samples are where they always were."""
    for mark in (None, marker(now=1, of={3: 1})):
        r = BankRig(main, bank=1 if mark else 0)
        if mark:
            r.drive[MARK] = mark
        audio = BankAudio(r, {})
        r.serve(audio)
        assert r.load((7, 20, PROGRESS)) == 1
        assert (r.now, r.want) == (0, 0)
        if mark:
            assert r.mark == (0, {3: 1}) and len(audio.done) == SLOTS       # came off B: all of A is loaded
        else:
            assert r.mark is None and not audio.done and not r.writes       # was on A: nothing to do, nothing written


def test_what_does_not_change_the_bank(rig):
    rig.drive[MARK] = marker(now=0, of={12: 1})
    audio = BankAudio(rig, {})
    rig.serve(audio)
    rig.loaded = 0                                                  # the project load failed
    assert rig.load((7, 12, PROGRESS)) == 0 and rig.now == 0 and not audio.asked and not rig.reads
    rig.loaded = 1
    for project in (128, 200, 0xFFFFFFFF):                          # not one of the 128
        assert rig.load((7, project, PROGRESS)) == 1 and rig.now == 0
    rig.mc.w32(WANT, 2)                                             # BANK turned and the project loaded again without a save
    assert rig.load((7, 30, PROGRESS)) == 1 and (rig.now, rig.want) == (0, 0)     # the turn is forgotten, like any unsaved change
    rig.read_fails = len(rig.reads)                                 # the drive stops reading
    assert rig.load((7, 12, PROGRESS)) == 1 and rig.now == 0
    assert not rig.writes and rig.mark == (0, {12: 1}) and not rig.stray


def joined(e, rig):
    """Every request of the main CPU answered by one block of the audio CPU, the box and the ring carried across."""
    def audio_block():
        box = bytes(rig.mc.read(mm.KEEP_BOX, m.KEEP_SIZE))
        e.mc.write(BOX, box[:m.KEEP_ACK])
        e.mc.write(BOX + m.KEEP_DATA, box[m.KEEP_DATA:])
        e.mc.write(RING, bytes(rig.mc.read(mm.SHARED + RING, 1024)))
        e.block()
        rig.mc.write(mm.KEEP_BOX + m.KEEP_ACK, bytes(e.mc.read(BOX + m.KEEP_ACK, m.KEEP_SIZE - m.KEEP_ACK)))
    e.block()
    rig.mc.write(mm.KEEP_BOX, bytes(e.mc.read(BOX, m.KEEP_SIZE)))
    rig.serve(audio_block)


def test_a_project_goes_to_another_bank_and_plays_that_banks_sample(audio, main):
    """Both sides: set BANK, save, load, and the audio CPU plays what the other bank holds in the slot."""
    left_a, right_a, left_b, right_b = sample(3000, 1), sample(3000, 2), sample(2500, 3), sample(2500, 4)
    r = BankRig(main)
    for slot, a, b in ((10, left_a, left_b), (11, right_a, right_b)):
        r.put(slot, a, bank=0)
        r.put(slot, b, bank=1)
    pool = {10: np.frombuffer(left_a, dtype=">i2").astype(np.int16), 11: np.frombuffer(right_a, dtype=">i2").astype(np.int16)}
    e = engine(audio, pool=pool)                                    # booted on bank A
    in_a = heard(e, 5)
    e.set_slot(5, 23, 0)
    table = [slot_entry(e, k) for k in range(SLOTS)]
    joined(e, r)
    r.mc.w32(WANT, 1)                                               # BANK to B on the sampling page
    assert r.keep((7, 12, PROGRESS)) == 1 and r.now == 0                   # SAVE PROJECT: nothing is loaded
    assert [slot_entry(e, k) for k in range(SLOTS)] == table
    assert r.load((7, 12, PROGRESS)) == 1 and r.now == 1                   # LOAD PROJECT: bank B comes in
    assert slot_entry(e, 10) == (2500, buffer_of(10)) and bytes(e.mc.read(buffer_of(10), 5000)) == left_b
    assert bytes(e.mc.read(buffer_of(11), 5000)) == right_b
    assert all(slot_entry(e, k)[0] == 0 for k in range(SLOTS) if k not in (10, 11))
    b_pool = {10: np.frombuffer(left_b, dtype=">i2").astype(np.int16), 11: np.frombuffer(right_b, dtype=">i2").astype(np.int16)}
    in_b = heard(e, 5)
    assert np.array_equal(in_b, heard(engine(audio, pool=b_pool), 5)) and not np.array_equal(in_b, in_a)
    over = take(e, 5, 6, seed=9)                                    # a take, on bank B
    assert r.keep((7, 12, PROGRESS)) == 1                                  # saved: it is bank B's now
    assert r.slot(10)[1] == left_a                                  # bank A's slot on the drive is what it was
    assert r.drive[sector_of(10) + RUN][64:64 + 16] == over[0][:16]
    assert not r.stray


# ---- the audio CPU: three sectors a put, and the feed kept out ----------------------------------------

def big(e, slot, off, data):
    """A big put as the main CPU makes it: a sector in the box, two in the ring."""
    data = data.ljust(1536, b"\xee")
    e.mc.write(RING, data[512:1536])
    return ask(e, slot | PUT | BIG, off, data[:512])[0]


def test_a_big_put_lands_three_sectors_in_the_slots_buffer(audio):
    e = engine(audio)
    x = sample(3000, 1)                                             # 6000 bytes: three big puts and part of a fourth
    for off in big_pieces(x):
        assert big(e, 10, off, x[off:off + 1536])
    assert bytes(e.mc.read(buffer_of(10), len(x))) == x and slot_entry(e, 10)[0] == 0
    assert ask(e, 10 | PUT, m.KEEP_DONE, (3000).to_bytes(4, "big"))[0]
    assert slot_entry(e, 10) == (3000, buffer_of(10))
    # and it sounds as the same sample loaded at boot does
    y = sample(3000, 2)
    for off in big_pieces(y):
        big(e, 11, off, y[off:off + 1536])
    ask(e, 11 | PUT, m.KEEP_DONE, (3000).to_bytes(4, "big"))
    pool = {10: np.frombuffer(x, dtype=">i2").astype(np.int16), 11: np.frombuffer(y, dtype=">i2").astype(np.int16)}
    got = heard(e, 5)
    assert np.array_equal(got, heard(engine(audio, pool=pool), 5)) and np.any(got)


def test_a_big_put_stops_at_the_buffers_end_and_names_a_real_slot(audio):
    e = engine(audio)
    e.mc.write(buffer_of(10) + m.REC_STRIDE - 2048, bytes(4096))
    piece = bytes(range(256)) * 6
    assert big(e, 10, m.REC_STRIDE - 1024, piece)                   # 1024 bytes of room for 1536
    assert bytes(e.mc.read(buffer_of(10) + m.REC_STRIDE - 2048, 4096)) == bytes(1024) + piece[:1024] + bytes(2048)
    assert big(e, 63, m.REC_STRIDE - 1536, piece)                   # the last buffer's last three sectors
    assert bytes(e.mc.read(buffer_of(64) - 1536, 1536)) == piece
    table = bytes(e.mc.read(m.SLOT_LEN, 8 * SLOTS))
    wrote = []
    e.mc.uc.hook_add(UC_HOOK_MEM_WRITE, lambda uc, a, addr, size, v, u: wrote.append(addr), begin=m.KEPT, end=m.STACK_TOP - 0x10000)
    e.mc.uc.ctl_flush_tb()
    for slot, off in ((64, 0), (0x3FFF, 0), (10, m.REC_STRIDE), (10, 2), (10, 0xFFFFFE00)):
        assert big(e, slot, off, piece)                             # answered, and nothing written
    assert not wrote and bytes(e.mc.read(m.SLOT_LEN, 8 * SLOTS)) == table


def test_the_ring_is_read_in_longs_and_a_plain_put_leaves_it_alone(audio):
    e = engine(audio)
    seen = []
    e.mc.uc.hook_add(UC_HOOK_MEM_READ, lambda uc, a, addr, size, v, u: seen.append((addr, size)), begin=RING, end=RING + 1023)
    e.mc.uc.ctl_flush_tb()
    x = sample(600, 3)
    assert ask(e, 10 | PUT, 0, x[:448])[0] and not seen             # the load image's put: a sector, from the box
    assert big(e, 10, 0, x)
    assert len(seen) == 256 and all(size == 4 and addr % 4 == 0 for addr, size in seen)


def test_cost_of_a_big_put_on_the_audio_cpu(official, audio):
    def count(built, slot):
        e = engine(built)
        e.block()
        if slot is not None:
            e.mc.write(BOX + m.KEEP_SLOT, slot.to_bytes(2, "big") + bytes(4))
            e.mc.write(BOX + m.KEEP_REQ, b"\0\1")
        n0 = e.mc.insns
        e.block()
        return e.mc.insns - n0
    load = build_engine.patched_image(official.section(7), load=True)
    assert count(audio, None) == count(load, None)                  # nothing asked: the load image's count
    cost = count(audio, 10 | PUT | BIG) - count(audio, None)
    assert cost < 6000 and cost == COST                             # one block of a bank load: 1,536 bytes copied


COST = 3247                 # a block with a big put in it, over one without. Budget: 10,506 a voice


def test_the_feed_keeps_out_of_the_ring_while_slots_are_loaded(main):
    """An armed track would have the feed write a block into the ring every mixer call: over the samples in flight."""
    r = MainRig(*main)
    before = junk(0x0105)
    block = make_block(ALL, [REC] * 12)
    r.mc.w32(BUSY, 1)
    ret, after = r.run(block, frames(), before)
    assert ret == 0x8000DBD0 and after == before                    # the mixer ran, the window is as it was
    r.mc.w32(BUSY, 0)
    ret, after = r.run(block, frames(), before)
    assert after != before and after[m.MAILBOX:m.MAILBOX + 2] == (0x0106).to_bytes(2, "big")       # and with the flag down it feeds


# ---- the page ------------------------------------------------------------------------------------

def places(r):
    return [t[2] for t in r.show()]


def test_the_sampling_page_has_a_bank_place_that_only_chooses(main):
    r = test_page.Rig(main, {0: 44}, index=1)
    r.mc.w32(NOW, 0), r.mc.w32(WANT, 0)
    assert places(r)[6:] == ["BANK", "A"] and r.show()[6][:2] == (33 + 3 * 26, 27)     # the fourth place
    r.told, r.stray = [], []
    for steps, want, reads in ((1, 1, "A>B"), (1, 2, "A>C"), (5, 2, "A>C"), (-1, 1, "A>B"), (-9, 0, "A"), (2, 2, "A>C")):
        assert r.twist(4, steps) == 1
        assert r.mc.r32(WANT) == want and r.mc.r32(NOW) == 0 and places(r)[7] == reads
    assert not r.changes and not r.locks and not r.told             # nothing of the track's, and nothing to the audio CPU
    assert set(r.stray) == {WANT}                                   # the one number is all that is written
    r.mc.w32(NOW, 2), r.mc.w32(WANT, 2)
    assert places(r)[7] == "C"
    r.mc.w32(NOW, UNKNOWN), r.mc.w32(WANT, 0)                       # before the drive has been asked: the first bank
    assert places(r)[7] == "A"


def test_the_rest_of_the_page_is_the_page_images(main):
    r = test_page.Rig(main, {0: 44}, index=1, mode=0)
    r.mc.w32(NOW, 0), r.mc.w32(WANT, 0)
    assert places(r)[:6] == ["SRC", "MAIN", "DEST", "SMPL", "REC", "OFF"]
    r.twist(3, 1), r.twist(1, 1), r.twist(2, 4)
    assert r.mode == 6 and r.dest == 4 and r.mc.r32(WANT) == 0
    r.hold(4)
    r.twist(3, -1)
    assert r.locks == {4: 4}
    for knob in range(5, 9):
        assert r.twist(knob, 3) == 1
    assert r.mode == 6 and r.mc.r32(WANT) == 0


# ---- the image -----------------------------------------------------------------------------------

def test_bank_image_builds_and_the_others_do_not_contain_it(official_path, official, stock3, main):
    from tools import build
    quiet = lambda s: None
    raw, _, built, regions, syms = build.build(official_path, log=quiet, bank=True)
    assert sorted(regions) == [3, 7] and built.section(3) == main[0]
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
    load = build.build(official_path, log=quiet, load=True)[2]
    diff7 = [k for k in range(len(load.section(7))) if load.section(7)[k] != built.section(7)[k]]      # the audio CPU: more in our code only
    ours = list(m.CAVES.values()) + list(m.REC_CAVES.values())
    ours += [(x, x + 4) for x in (m.UPDATE_TABLE + 4 * m.TWIN_ENGINE, m.RENDER_TABLE + 4 * m.TWIN_ENGINE, m.ISR_VOICE_LOOP_CALL + 2)]
    assert diff7 and all(any(m.off(lo7) <= k < m.off(hi7) for lo7, hi7 in ours) for k in diff7)
    lo, hi = mm.CAVE_BANK
    assert load.section(3)[mm.off(lo):mm.off(hi)] == stock3[mm.off(lo):mm.off(hi)]
    for uses, stock in ((mm.DRIVE_READ_USES, mm.DRIVE_READ), (mm.DRIVE_WRITE_USES, mm.DRIVE_WRITE), (mm.DRIVE_ERASE_USES, mm.DRIVE_ERASE)):
        for site in uses:
            assert int.from_bytes(load.section(3)[mm.off(site) + 2:mm.off(site) + 6], "big") == stock
    # apart from its code, the save and load code, the page's code, the feed's, the 21 names and the calls to the hooks,
    # section 3 is the load image's
    a, b = bytearray(load.section(3)), bytearray(built.section(3))
    sites = [(s + 2, s + 6) for s in mm.DRIVE_READ_USES + mm.DRIVE_WRITE_USES + mm.DRIVE_ERASE_USES]
    calls = [(c + 2, c + 6) for c in mm.PROJECT_SAVE_CALLS + (mm.PROJECT_LOAD_CALL,)]
    slots = [(mm.SYN_CLASS + k, mm.SYN_CLASS + k + 4) for k in (mm.PAGE_KNOB_METHOD, mm.PAGE_DRAW_METHOD, mm.PAGE_TURN_METHOD)]
    slots += [(mm.SYN_SIDE + mm.SYN_SIDE_TURN, mm.SYN_SIDE + mm.SYN_SIDE_TURN + 4), (mm.SYN_BUILD + 6, mm.SYN_BUILD + 10)]
    for start, end in [mm.CAVE_BANK, mm.CAVE_KEEP, mm.CAVE_PAGE, mm.CAVE_PAGE2, mm.CAVE_REC, mm.CAVE_AMUTE,
                       (mm.MIX_CALL + 2, mm.MIX_CALL + 6)] + sites + calls + slots:
        a[mm.off(start):mm.off(end)] = b[mm.off(start):mm.off(end)] = bytes(end - start)
    assert a == b
