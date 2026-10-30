"""The switch image: the trig image with the hits' steps from each sample's own loudest frame, and SOLO and REC on the
TRIG page drawn as stock's switch.

On request

.

The trig image counted a hit's fifteen steps from full scale, 2 dB each from -31 dB: a take that sits low reached few
steps or none, and a hit under -31 dB was none. Here a first pass over a slot finds its loudest frame and the steps go
from there: 1 past 31 dB under it, 15 past 3 dB under it, nothing under -45 dB of full scale. DEL's mapping is the
same, so DEL 1 takes the hits within 3 dB of the sample's loudest, however loud the sample is.

The switch: LFO.T's and FLT.T's picture is one routine of stock's (0x400703da), frame value >> 8 of a strip, so ours
calls it with the solo's and REC's own value. REC's ONCE is the word. Not held: where on the screen stock's draw puts
a place's picture (read from 0x4003a244 and 0x4003842c, not run on stock), and how it looks; the unit shows that.
"""
import shutil

import numpy as np
import pytest

import test_gear as G
import test_hits as H
import test_trig as T
from tools import build, build_engine, build_main
from tools import audiomap as m
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

SWITCH, STRIP, FRAME, BLIT = 0x400703da, 0x444df64c, 0x400f941c, 0x400f8f70


@pytest.fixture(scope="module")
def stock3(official):
    return official.section(3)


@pytest.fixture(scope="module")
def main(stock3):
    return build_main.patched_image(stock3, xfade=24)


# ---- the switch -----------------------------------------------------------------------------------------------------

def rig(built, track):
    """test_trig's rig, with stock's switch run as it is and the two calls it makes played."""
    r = T.trig(built, track)
    r.blits = []
    r.stub(FRAME, lambda strip, frame, phase: 0x55000000 | strip & 0xffff | frame << 20 if (strip, phase) == (STRIP, 0) else 0)
    r.stub(BLIT, lambda surface, pic, x, y, mode: r.blits.append((pic >> 20 & 15, x, y)) or 0)
    r.mc.uc.ctl_flush_tb()
    return r


def drawn(r):
    texts = r.show()
    return texts, list(r.blits)


def test_solo_and_rec_are_drawn_as_stocks_switch_with_their_names(main):
    r = rig(main, 2)
    r.blits = []
    texts, blits = drawn(r)
    assert r.trig_stock == [("draw", T.PAGE)]
    assert [t for t in texts if t[2]] == [(33, 0, "SOLO"), (59, 0, "REC")]
    assert blits == [(0, 25, 11), (0, 51, 11)]                  # frame 0, off; at the places' x + 1 and y + 4


def test_a_turn_moves_the_switch(main):
    track = 4
    r = rig(main, track)
    G.geared(r, [256, 256, -256, -256])
    G.twist(r, T.E, 1)
    r.blits = []
    assert drawn(r)[1] == [(1, 25, 11), (0, 51, 11)]
    G.twist(r, T.F, 1)
    r.blits = []
    assert drawn(r)[1] == [(1, 25, 11), (1, 51, 11)]
    G.twist(r, T.E, -1)
    G.twist(r, T.F, -1)
    r.blits = []
    assert drawn(r)[1] == [(0, 25, 11), (0, 51, 11)]


def test_rec_at_once_is_the_word(main):
    track = 1
    r = rig(main, track)
    G.geared(r, [256, 256])
    G.twist(r, T.F, 1)
    G.twist(r, T.F, 1)                                          # OFF, ON, ONCE
    r.blits = []
    texts, blits = drawn(r)
    assert (59, 12, "ONCE") in texts and blits == [(0, 25, 11)]


def test_off_a_sampler_the_page_is_stocks(main):
    r = rig(main, 9)
    r.blits = []
    assert drawn(r) == ([], [])


# ---- the hits' steps from a sample's loudest frame ------------------------------------------------------------------

def rel(peak):
    def loud(p):
        if p <= 181:
            return 0
        s, t, p = 0, peak * 925 >> 7, p << 8
        while s < 15 and p > t:
            s, t = s + 1, t + (t * 33 >> 7)
        return s
    return loud


def scanned(built, x):
    e = H.P.engine(built, pool={0: x, 1: x})
    for _ in range(2 * (len(x) // 128 + len(x) // 256 + 3) + 8):
        e.mc.call(built[1]["hits_block"])
    return H.kept(e, 0)


@pytest.fixture(scope="module")
def engine(official):
    return build_engine.patched_image(official.section(7), peak=True)


@pytest.mark.parametrize("gain", [1.0, 0.25, 0.1])               # 0, -12 and -20 dB
def test_a_quiet_take_has_the_steps_a_loud_one_has(engine, monkeypatch, gain):
    """The same hits, each a step at most from where it is at full scale: a hit on a step's edge rounds either way."""
    x = (H.drums().astype(np.float64) * gain).astype(np.int16)
    peak = int(np.abs(x.astype(np.int32)).max())
    monkeypatch.setattr(H, "loud", rel(peak))
    got, done = scanned(engine, x)
    assert done == len(x) and got == H.model(x)
    loud = scanned(engine, H.drums())[0]
    assert [f for f, _, _ in got] == [f for f, _, _ in loud] and all(abs(a[1] - b[1]) <= 1 for a, b in zip(got, loud))
    assert got[0][1] == 15                                      # the loudest is the top step, however quiet the take
    print("switch: drums at %.0f dB, steps" % (20 * np.log10(gain)), [s for _, s, _ in got])


def test_under_minus_45_db_of_full_scale_is_no_hit(engine):
    x = (H.drums().astype(np.float64) * 0.004).astype(np.int16)   # -48 dB
    assert scanned(engine, x)[0] == []


def test_the_first_pass_says_nothing_until_it_is_done(engine):
    x = H.drums()
    e = H.P.engine(engine, pool={0: x, 1: x})
    for _ in range(len(x) // 256 // 2):
        e.mc.call(engine[1]["hits_block"])
    assert H.kept(e, 0)[0] == []


# ---- the image ------------------------------------------------------------------------------------------------------

def test_the_image(official_path, main):
    quiet = lambda s: None
    raw, _, built, _, syms = build.build(official_path, log=quiet, xfade=24)
    was = build.build(official_path, log=quiet, xfade=23)[2]
    new, old = built.section(3), was.section(3)
    assert new == main[0] and len(new) == len(old)
    assert mm.CAVE_TRIG[0] <= syms["trig_draw"] < mm.CAVE_TRIG[1]
    spans = [mm.CAVE_PAGE, mm.CAVE_PAGE2, mm.CAVE_PAGE3, mm.CAVE_PAGE4, mm.CAVE_PAGE5, mm.CAVE_PAGE6, mm.CAVE_PAGE7, mm.CAVE_PAGE8,
             mm.CAVE_PAGE9, mm.CAVE_PAGE10, mm.CAVE_TRIG, mm.CAVE_TRIG2, mm.CAVE_TRIG3,
             (mm.TRIG_CLASS, mm.TRIG_CLASS + 0x100), (mm.TRIG_SIDE + 8, mm.TRIG_SIDE + 12), (mm.SYN_CLASS, mm.SYN_CLASS + 0x100),
             (mm.SYN_SIDE + 8, mm.SYN_SIDE + 12), (mm.SYN_BUILD, mm.SYN_BUILD + 0x20)]
    stray = [hex(mm.BASE + k) for k in range(len(new)) if new[k] != old[k] and not any(mm.off(a) <= k < mm.off(b) for a, b in spans)]
    assert stray == []
    a7, b7 = built.section(7), was.section(7)
    runs = list(m.HITS_CAVES.values()) + list(m.SRR_CAVES.values())
    into = lambda b, j: any(lo <= int.from_bytes(b[j:j + 4], "big") < hi for lo, hi in runs)
    moved = lambda k: any(into(a7, j) and into(b7, j) for j in range(k - 3, k + 1))     # a pointer into the two runs, whose routines moved
    stray7 = [hex(m.BASE + k) for k in range(len(a7)) if a7[k] != b7[k] and not any(m.off(lo) <= k < m.off(hi) for lo, hi in runs) and not moved(k)]
    assert stray7 == [] and a7 != b7
    print("switch image", __import__("hashlib").sha256(raw).hexdigest())
