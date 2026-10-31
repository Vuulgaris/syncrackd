"""The lap image, a tool: the tail image with five more readings of the timer in the profile's record."""
import hashlib
import shutil

import numpy as np
import pytest
from unicorn import UC_HOOK_MEM_READ

import test_dma as D
from test_stereo import some_tracks, stock3, window_of  # noqa: F401  (stock3 is a fixture)
from tools import build, build_main, prof_read
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

TIMER, RECORD = 0xfc07000c, mm.CAVE_PROF[0]


@pytest.fixture(scope="module")
def lap(stock3):  # noqa: F811
    return build_main.patched_image(stock3, xfade=15)


@pytest.fixture(scope="module")
def tail(stock3):  # noqa: F811
    return build_main.patched_image(stock3, xfade=14)


class Rig(D.Rig):
    """The transfers' rig with the readings' run and a timer that reads 0x1000 more each time."""

    def __init__(self, built):
        super().__init__(built)
        image, mc = built[0], self.mc
        if "right_mid_lap" in self.syms:
            lo, hi = mm.CAVE_LAP
            mc.load_code(lo, image[mm.off(lo):mm.off(hi)])
        mc.load_code(mm.PRE_MIX, b"\x4e\x75")  # test only: stock's routine there is not run, it returns at once
        mc.set_exits([0x40000100])
        self.now = 0
        mc.uc.hook_add(UC_HOOK_MEM_READ, self._timer, begin=TIMER, end=TIMER + 3)
        mc.uc.ctl_flush_tb()

    def _timer(self, uc, access, address, size, value, user):
        self.now += 0x1000
        self.mc.w32(TIMER, self.now)

    def block(self, tracks, window, up=1):
        mc, s = self.mc, self.syms
        lapped = "right_mid_lap" in s
        mc.write(mm.SHARED, window)
        mc.w32(mm.AUDIO_UP, up)
        mc.write(D.S.DMA_FLAG, b"\0")
        self.reads, self.writes, self.model.started, self.model.log = [], [], [], []
        mc.call(s["right_begin"])
        mc.write(mm.TRACKS, np.asarray(tracks).astype(">i4").tobytes())
        self.answer = mc.call(s["right_mid_lap" if lapped else "right_mid"])
        mc.call(s["right_ready_lap" if lapped else "right_ready"])
        return bytes(mc.read(D.RIGHT, 1024)), bytes(mc.read(D.STATE, 32))


@pytest.mark.parametrize("mask, up", [(0, 1), (0x5a, 1), (0xff, 1), (0x0f, 0)])
def test_the_readings_are_left_in_order_and_the_routines_do_what_the_tail_images_do(lap, tail, mask, up):
    new, old = Rig(lap), Rig(tail)
    tracks, right = some_tracks(), D.rights()
    window = window_of(right, mask)
    new.mc.write(RECORD, b"\x77" * 64)
    for block in range(3):
        was = new.now
        got, kept = new.block(tracks, window, up), old.block(tracks, window, up)
        assert got == kept and new.answer == old.answer == up
        assert [new.mc.r32(RECORD + 36 + 4 * k) for k in range(5)] == [was + 0x1000 * (k + 1) for k in range(5)]
        assert new.mc.read(RECORD, 36) == b"\x77" * 36 and new.mc.read(RECORD + 56, 8) == b"\x77" * 8  # the rest of the record is the profile's
    assert old.now == 0  # the tail image reads no timer there


def record(rows, lapped, seed=1):
    """Rows of a take as the reader's own table: every block 88,000 counts, the interrupt 80,000 of them."""
    rng = np.random.default_rng(seed)
    n = np.arange(rows, dtype=np.int64)
    entry = 5000 + 88000 * n
    r = {"rows": rows, "count": (n & 0xffff).astype(np.uint32), "entry": entry, "mix_in": entry + 44000, "mix_out": entry + 75000,
         "fed": entry + 76000 - 88000, "exit": entry + 80000 - 88000, "frame": np.zeros(rows, np.int64), "pc": np.full(rows, mm.BASE + 0x100),
         "sp": np.full(rows, 0x405fd000), "task": np.full(rows, 0x405d4a28)}
    for k in range(6):
        r["s%d" % k] = entry + (1000, 20000, 30000, 41000, 43000, 0)[k] if lapped and k < 5 else rng.integers(0x40000000, 0x46000000, rows)
    return {k: (np.asarray(v) & 0xffffffff).astype(np.uint32) if k != "rows" else v for k, v in r.items()}


def test_the_reader_tells_a_lap_record_and_its_parts_add_up():
    plain, lapped = record(200, False), record(200, True)
    assert not prof_read.laps(plain) and prof_read.laps(lapped)
    period, parts, used, pairs = prof_read.times(lapped)
    assert period == 88000 and used == pairs == 199
    six = [k for k in parts if k.startswith("  ")]
    assert [int(parts[k][0]) for k in six] == [1000, 19000, 10000, 11000, 2000, 1000]
    assert (sum(parts[k] for k in six) == parts["before the mixer"]).all()
    assert [k for k in prof_read.times(plain)[1] if k.startswith("  ")] == []
    assert "the wait for the audio CPU" in prof_read.report(lapped) and "the wait" not in prof_read.report(plain)


def test_the_image(official_path, official, lap, tail):
    quiet = lambda s: None
    raw, _, built, _, syms = build.build(official_path, log=quiet, xfade=15)
    was_raw, _, was, _, _ = build.build(official_path, log=quiet, xfade=14)
    assert hashlib.sha256(was_raw).hexdigest().startswith("651975f3")  # the tail image, as it is
    new, old = built.section(3), was.section(3)
    assert new == lap[0] != old == tail[0] and len(new) == len(old)
    assert built.section(7) == was.section(7)
    spans = [mm.CAVE_DMA, mm.CAVE_DMA2, mm.CAVE_LAP, (mm.RIGHT_HOOK + 2, mm.RIGHT_HOOK + 6), (mm.PRE_MIX_CALL + 2, mm.PRE_MIX_CALL + 6),
             (mm.BLOCK_FIRST_CALL + 2, mm.BLOCK_FIRST_CALL + 6)]
    stray = [mm.BASE + k for k in range(len(new)) if new[k] != old[k] and not any(mm.off(a) <= k < mm.off(b) for a, b in spans)]
    assert not stray, [hex(a) for a in stray[:24]]
    assert new[mm.off(mm.RIGHT_HOOK):][:6] == b"\x4e\xb9" + syms["right_mid_lap"].to_bytes(4, "big")
    assert new[mm.off(mm.PRE_MIX_CALL):][:6] == b"\x4e\xb9" + syms["right_ready_lap"].to_bytes(4, "big")
    assert all(mm.CAVE_LAP[0] <= syms[n] < mm.CAVE_LAP[1] for n in ("right_mid_lap", "right_ready_lap"))
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
