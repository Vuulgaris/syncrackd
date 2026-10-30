"""The tune image (engine/tunepush.S): the sink image with a pushed turn of every machine's TUNE as an unpushed one.

On request. A pushed turn's steps are multiplied by the second
long of the sixteen bytes the start-up copies into a record's entry of the display table (0x400f6866); the sampler's
TUNE (record 431, TUN1 of machine 44) is given the plain knob's {1, 4, 0, its feel}. Here, the main CPU only, with stock's
start-up run as it is (the screen rig: the 136 constructors and the UI's getter):
  - every machine's TUNE (build_main.TUNE_RECORDS, 40, analog ones too) has its unpushed multiplier for the pushed one;
    every other byte of the 505 entries as on the sink image (the sampler's TUN2, our LOOP, too);
  - stock's routine of a turn's steps gives a pushed turn of 3 ticks 3, unpushed 3, where the sink image gives 12, 24, 36;
  - section 7 the sink image's, and only our places differ from it in section 3.
Only the unit can show: how a pushed turn of TUNE feels (the feel's pushed longs are stock's, not read)."""

import hashlib
import shutil

import pytest

from emu.screen import Screen
from tools import build, build_main
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

STEPS = 0x400f6866                      # (event, fine, coarse): the event's steps (+ 16) times coarse if pushed (+ 20)
EVENT = 0x47fe0000


@pytest.fixture(scope="module")
def tune(official):
    return build_main.patched_image(official.section(3), xfade=68)


@pytest.fixture(scope="module")
def sink(official):
    return build_main.patched_image(official.section(3), xfade=67)


def table(image):
    s = Screen(image)
    return s, bytes(s.mc.read(mm.UI_TABLE, mm.UI_STRIDE * mm.UI_COUNT))


def turn(s, entry, pushed):
    mc = s.mc
    mc.w32(EVENT + 16, 3)
    mc.write(EVENT + 20, bytes([pushed]))
    s.run(STEPS, EVENT, mc.r32(entry + 4), mc.r32(entry + 8))
    return mc.uc.reg_read(__import__("unicorn").m68k_const.UC_M68K_REG_D0)


CHANGE = 0x400f6a96                     # (ticks, knob, steps, feel, pushed) -> the change, 8.8: stock's, run as it is
TICKS = 0x47fd0000


def clicks(s, entry, pushed, n=6):
    """n clicks of a knob on a record, one tick each (a detent), through stock's two routines as its turn goes: the moves."""
    mc = s.mc
    mc.write(TICKS, bytes(0x100))
    out = []
    for _ in range(n):
        mc.w32(EVENT + 16, 1)
        mc.write(EVENT + 20, bytes([pushed]))
        s.run(STEPS, EVENT, mc.r32(entry + 4), mc.r32(entry + 8))
        steps = mc.uc.reg_read(__import__("unicorn").m68k_const.UC_M68K_REG_D0)
        s.run(CHANGE, TICKS, 0, steps if steps >> 31 == 0 else steps - (1 << 32), mc.r32(entry + 16), pushed)
        v = mc.uc.reg_read(__import__("unicorn").m68k_const.UC_M68K_REG_D0)
        out.append((v - (1 << 32) if v >> 31 else v) / 256)
    return out


def test_the_entries(tune, sink):
    """Every TUNE record: its feel a copy of stock's with a pushed step of 1, its pushed multiplier that feel's ticks a step
    (negative where the record turns the other way); every other byte of the 505 entries as on the sink image."""
    s, new = table(tune[0])
    t, old = table(sink[0])
    mc, feels, changed = s.mc, {}, []
    for r in build_main.TUNE_RECORDS:
        k = mm.UI_STRIDE * r
        unpushed = int.from_bytes(old[k + 4:k + 8], "big", signed=True)
        stock_feel, ours = int.from_bytes(old[k + 16:k + 20], "big"), int.from_bytes(new[k + 16:k + 20], "big")
        feels.setdefault(stock_feel, ours)
        assert feels[stock_feel] == ours and mm.CAVE_TUNE2[0] <= ours < mm.CAVE_TUNE2[1]
        copy, stock = bytes(mc.read(ours, 28)), bytes(t.mc.read(stock_feel, 28))
        assert copy == stock[:24] + (1).to_bytes(4, "big")
        ticks = int.from_bytes(copy[20:24], "big")
        assert int.from_bytes(new[k + 8:k + 12], "big", signed=True) == (ticks if unpushed > 0 else -ticks)
        assert new[k + 4:k + 8] == old[k + 4:k + 8] and new[k + 12:k + 16] == old[k + 12:k + 16]
        changed += [i for i in list(range(k + 8, k + 12)) + list(range(k + 16, k + 20)) if new[i] != old[i]]
    assert len(feels) == len(build_main.TUNE_FEELS) == 3
    assert [i for i in range(len(new)) if new[i] != old[i]] == changed
    assert new[mm.UI_STRIDE * 435 + 4:mm.UI_STRIDE * 435 + 20] == old[mm.UI_STRIDE * 435 + 4:mm.UI_STRIDE * 435 + 20]   # LOOP


@pytest.mark.parametrize("record", [431, 204, 100, 108, 132])   # the sampler, BD HARD (analog), BD MD (the picker's), SD BA, the reversed one
def test_a_pushed_click_moves_1(tune, sink, record):
    """Stock's own routines, a click at a time: pushed, every click 1 (the sink image: 4 every few clicks); unpushed as the
    sink image's."""
    s, _ = table(tune[0])
    t, _ = table(sink[0])
    entry = mm.UI_TABLE + mm.UI_STRIDE * record
    now, was = clicks(s, entry, 1), clicks(t, entry, 1)
    print(record, "pushed, a click at a time:", now, "was", was)
    assert {abs(v) for v in now} <= {0, 1} and any(now) and {abs(v) for v in was} - {0} == {4}
    assert sum(abs(v) for v in now) >= len(now) // 3            # the picker's feel waits after a step: 1 every 2 or 3 clicks
    assert clicks(s, entry, 0, 9) == clicks(t, entry, 0, 9)


def test_the_image(official_path, official, tune):
    quiet = lambda s: None
    raw, _, built, _, _ = build.build(official_path, log=quiet, xfade=68, prof=True)
    was_raw, _, was, _, _ = build.build(official_path, log=quiet, xfade=67, prof=True)
    print("sink image", hashlib.sha256(was_raw).hexdigest())      # on trap's third build: not a8c3f8f0, the unit's (trap 256)
    print("tune image", hashlib.sha256(raw).hexdigest())
    new, old = built.section(3), was.section(3)
    assert new == tune[0]
    spans = [mm.CAVE_TUNE, mm.CAVE_TUNE2, (mm.TUNE_COPY, mm.TUNE_COPY + 8)]
    assert not [hex(mm.BASE + k) for k in range(len(new)) if new[k] != old[k] and not any(mm.off(a) <= k < mm.off(b) for a, b in spans)]
    assert built.section(7) == was.section(7)
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
