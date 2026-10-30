"""The norm image: the eucl image with every take normalized to -1 dB once it ends.

On request
, and his choices: the take itself rewritten, always on, -1 dB. A take's loudest frame is followed while it runs;
at its end its slot (a stereo take's two) is scaled up, NORM_STEP frames a block, by at most 30 dB and never down; a
request of the keep box for a part not yet scaled is not answered till it is (engine/sampler.c, norm_block, norm_keep).
The hook's harness runs the voice loop's hook alone; norm_block is called after it, as the interrupt's end calls it.
"""
import shutil

import numpy as np
import pytest

import test_pack as PK
import test_pagerec as P
from emu.engine import BLOCK
from test_mode import ST
from test_multi import recorder, taken, write
from test_quick import Folded
from tools import audiomap as m
from tools import build

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

TOP, MOST, STEP = 29204, 32 << 14, 256
KEPT = 0x4407ff00


@pytest.fixture(autouse=True)
def folded(monkeypatch):
    monkeypatch.setattr(P, "HookEngine", Folded)


@pytest.fixture(scope="module")
def built(official_path):
    _, _, b, _, syms = build.build(official_path, log=lambda s: None, xfade=50)
    return b.section(7), syms


def tick(e, built, trig=0, release=0):
    e.block(trig, release)
    e.mc.call(built[1]["norm_block"])


def rec(built, track, place):
    """A track recording to a place: REC's mark in slot 24, as from the srr image on (tests/test_srr.py)."""
    e = recorder(built, {track: place}, 0)
    e.set_slot(track, 24, 0x52 + 7 / 256)
    return e


def take(e, built, track, blocks, count=100):
    """A take of the blocks (n, BLOCK, 2) on a track, let go on the last. -> its slot, frames, and its two buffers as
    the take left them, before anything is scaled."""
    tick(e, built, 1 << track)
    for b, x in enumerate(blocks[:-1]):
        write(e, count + b, {track: x})
        tick(e, built)
    write(e, count + len(blocks) - 1, {track: blocks[-1]})
    e.block(0, 1 << track)
    k = e.mc.read(e.voice(track) + ST + PK.S_RK, 1)[0]
    n = P.slot_entry(e, k)[0]
    was = taken(e, k, n).copy(), taken(e, k + 1, n).copy()
    e.mc.call(built[1]["norm_block"])
    return k, n, was


def scaled(x, peak):
    g = min((TOP << 14) // (peak | 1), MOST)
    return ((x.astype(np.int64) * g + 0x2000) >> 14).astype(np.int16) if g > 1 << 14 else x


def sine(n, amp, seed=0):
    rng = np.random.default_rng(seed)
    x = amp * np.sin(np.arange(n * BLOCK * 2) * 0.05 + rng.random()) * (0.5 + 0.5 * rng.random(n * BLOCK * 2))
    return np.round(x).astype(np.int16).reshape(n, BLOCK, 2)


def settle(e, built, blocks):
    for _ in range(blocks):
        tick(e, built)


def loudest(*xs):
    return int(max(np.abs(x.astype(int)).max() for x in xs))


@pytest.mark.parametrize("amp", [3000, 800, 20])
def test_a_stereo_take_is_scaled_to_minus_1_db_both_sides_by_one_gain(built, amp):
    e = rec(built, 2, 5)
    k, n, (left, right) = take(e, built, 2, sine(20, amp, amp))
    peak = loudest(left, right)
    settle(e, built, n // STEP + 2)
    assert n > 15 * BLOCK and peak
    assert np.array_equal(taken(e, k, n), scaled(left, peak)) and np.array_equal(taken(e, k + 1, n), scaled(right, peak))
    got = loudest(taken(e, k, n), taken(e, k + 1, n))
    assert got <= TOP and (got >= TOP - 2 or peak * 32 < TOP)        # 30 dB up at most
    assert P.slot_entry(e, k) == (n, PK.buf(k)) and e.mc.r32(KEPT + 4 * k) == e.mc.r32(KEPT + 4 * k + 4) == 0


def test_a_single_slots_take_scales_its_slot_alone(built):
    e = rec(built, 4, 40)
    k, n, (left, _) = take(e, built, 4, sine(12, 2000, 3))
    nxt = taken(e, k + 1, 64).copy()
    settle(e, built, 4)
    assert np.array_equal(taken(e, k, n), scaled(left, loudest(left)))
    assert np.array_equal(taken(e, k + 1, 64), nxt) and n % 2 == 1


def test_a_loud_take_is_left_as_it_is(built):
    e = rec(built, 1, 3)
    k, n, (left, right) = take(e, built, 1, sine(8, 32000, 4))
    settle(e, built, 3)
    assert loudest(left, right) > TOP
    assert np.array_equal(taken(e, k, n), left) and np.array_equal(taken(e, k + 1, n), right)


def ask(e, slot, off, req):
    e.mc.write(m.KEEP_BOX, req.to_bytes(2, "big") + slot.to_bytes(2, "big") + off.to_bytes(4, "big"))


def test_the_keep_box_waits_for_a_part_not_yet_scaled(built):
    e = rec(built, 3, 7)
    k, n, (left, right) = take(e, built, 3, sine(40, 1500, 5))
    want = scaled(left, loudest(left, right))
    assert n >= 1024
    ack = e.mc.r32(m.KEEP_BOX + 8)
    ask(e, k, 2 * 768, (ack + 1) & 0xffff)                           # frames 768 to 1,024: scaled by the fourth block
    for b in range(3):
        e.block()
        assert e.mc.r32(m.KEEP_BOX + 8) == ack, b                    # no answer while that part is not scaled
        e.mc.call(built[1]["norm_block"])
    e.block()
    assert e.mc.r32(m.KEEP_BOX + 8) == (ack + 1) & 0xffff
    data = np.frombuffer(bytes(e.mc.read(m.KEEP_BOX + 16, 512)), dtype=">i2").astype(np.int16)
    assert np.array_equal(data, want[768:1024]) and not np.array_equal(data, left[768:1024])


def test_a_new_take_in_the_slot_stops_the_scaling(built):
    e = rec(built, 3, 7)
    k, n, _ = take(e, built, 3, sine(40, 1500, 6))
    settle(e, built, 1)
    _, n2, (left, right) = take(e, built, 3, sine(6, 30000, 7), count=300)
    settle(e, built, 8)
    assert np.array_equal(taken(e, k, n2), left) and np.array_equal(taken(e, k + 1, n2), right)     # loud: as it is


def test_the_interrupt_calls_it(built):
    image, syms = built
    at = m.off(syms["hits_block"])
    calls = [syms["hits_block"] + j + 2 + int.from_bytes(image[at + j + 2:at + j + 4], "big", signed=True)
             for j in range(0, 0x60, 2) if image[at + j:at + j + 2] == b"\x4e\xba"]
    assert syms["norm_block"] in calls


def test_what_a_block_costs(built):
    e = rec(built, 2, 5)
    take(e, built, 2, sine(30, 1000, 9))
    counts = []
    for _ in range(3):
        e.block()
        n0 = e.mc.insns
        e.mc.call(built[1]["norm_block"])
        counts.append(e.mc.insns - n0)
    for _ in range(10):
        tick(e, built)
    n0 = e.mc.insns
    e.mc.call(built[1]["norm_block"])
    idle = e.mc.insns - n0
    print("norm_block, a stereo take's block of scaling:", counts, "idle:", idle)
    assert max(counts) < 4000 and idle < 200


def test_the_image(official_path, official, built):
    quiet = lambda s: None
    new = build.build(official_path, log=quiet, xfade=50)[2]
    was = build.build(official_path, log=quiet, xfade=49)[2]
    assert new.section(3) == was.section(3) and new.section(7) == built[0] != was.section(7)
    for sid in official.ids:
        if sid not in (3, 7):
            assert new.container.by_id(sid).stored == official.container.by_id(sid).stored
