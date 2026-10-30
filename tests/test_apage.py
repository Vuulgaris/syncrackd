"""The apage image: the dma image with the sampling page's solo and crossfade on the analog tracks.

On request
. Built here: the page. Not built: the lock (an analog machine uses both knob slots a digital track
leaves free, so a lock on an analog track has no known place yet).

SYN again on tracks 9 to 12 opens a second page: SOLO on knob E, the unit's one crossfade on knob G, the other six
places empty. The solos' long keeps twelve bits and the crossfade is twelve numbers; the mixer link and the analog
mute go by all twelve.
"""
import shutil

import pytest
from unicorn import UC_HOOK_MEM_WRITE

import test_soloknob as K
import test_xfade as X
from test_page import PAGE
from test_xfade import stock3  # noqa: F401  (a fixture)
from tools import build, build_main
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

E, G = K.SOLO_KNOB, X.XF_KNOB
ANALOG = [8, 9, 10, 11]


@pytest.fixture(scope="module")
def main(stock3):  # noqa: F811
    return build_main.patched_image(stock3, xfade=4)


@pytest.fixture(scope="module")
def before(stock3):  # noqa: F811
    return build_main.patched_image(stock3, xfade=3)


def page(built, track, index=1, machine=None, xf=None, word=0):
    """The page rig with the class's three methods going where this image sends them."""
    image, syms = built
    if "apage_knob" in syms:
        syms = dict(syms, syn_knob=syms["apage_knob"], syn_draw=syms["apage_draw"])
    r = X.Page((image, syms), track=track, word=word)
    if "apage_turn" in syms:
        r.entry = syms["apage_turn_side"], syms["apage_turn"]
    if track >= 8 or machine is not None:
        r.machines = {track: track if machine is None else machine}     # an analog track's machine: any that is not the sampler
    r.mc.map(0x80007000, 0x1000)                                    # on-chip memory: the dma image's letter is read there
    r.xf_all = []                                                   # every write to the twelve numbers, in order: (offset, size)
    r.mc.uc.hook_add(UC_HOOK_MEM_WRITE, lambda uc, t, a, n, v, u: r.xf_all.append((a - mm.XFADES, n)), begin=mm.XFADES, end=mm.XFADES + 11)
    r.mc.write(mm.XFADES, bytes(xf or [0] * 12))
    r.mc.w32(PAGE + mm.PAGE_INDEX, index)
    return r


def xf12(r):
    return list(r.mc.read(mm.XFADES, 12))


@pytest.mark.parametrize("track", ANALOG)
def test_an_analog_track_has_two_pages_and_the_second_holds_the_solo_and_the_crossfade(main, track):
    r = page(main, track)
    assert [r.ask(k) for k in range(8)] == [0] * 8 and r.pages == 2 and r.index == 1       # no knob there is stock's
    assert r.fifth() == ["", "S OFF"] and r.third() == ["", "XF0"]
    ours = [t[2] for t in r.show() if t[2]]
    assert sorted(ours) == sorted(["S OFF", "XF0", "C047"])         # and nothing else is written: the six other places are empty
    assert r.twist(E, 1) == 1 and r.solos == 1 << track and r.fifth() == ["", "SOLO"]
    assert r.twist(E, -1) == 1 and r.solos == 0
    assert r.twist(G, 40) == 1 and xf12(r) == [40 if t == track else 0 for t in range(12)] and r.third() == ["", "XF40"]
    for k in range(1, 9):                                           # the six others turn nothing
        if k not in (E, G):
            assert r.twist(k, 3) == 1
    assert r.solos == 0 and xf12(r) == [40 if t == track else 0 for t in range(12)]
    assert not r.locks and not r.locked and not r.changes and not r.popped


@pytest.mark.parametrize("track", ANALOG)
def test_an_analog_tracks_first_page_is_stocks(main, before, track):
    a, b = page(main, track, index=0), page(before, track, index=0, machine=track)
    assert [a.ask(k) for k in range(9)] == [b.ask(k) for k in range(9)] and a.show() == b.show() == []
    assert a.pages == 2 and b.pages == 1
    for k in range(1, 9):
        assert a.twist(k, 2) == b.twist(k, 2)
    assert a.solos == 0 and xf12(a) == [0] * 12


def test_one_crossfade_for_twelve_tracks_and_the_track_that_turns_it_stays(main):
    r = page(main, 10, xf=[0, 0, 90, 0, 0, 0, 0, 0, 0, 0, 0, 0])
    assert r.third() == ["", "XF90"]                                # a sampler's, shown on an analog track's page
    r.twist(G, 1)
    assert xf12(r) == [91 if t == 10 else 0 for t in range(12)]
    assert r.xf_all == [(8, 4), (0, 4), (4, 4)]                     # the track's own long first: never all twelve at 0 on the way
    s = page(main, 5, xf=xf12(r))                                   # and a sampler takes it from the analog track
    assert s.third() == ["", "XF91"]
    s.twist(G, -1)
    assert xf12(s) == [90 if t == 5 else 0 for t in range(12)] and s.xf_all == [(4, 4), (0, 4), (8, 4)]


@pytest.mark.parametrize("track", [0, 3, 7])
def test_a_samplers_page_is_the_dma_images(main, before, track):
    for index in (0, 1):
        a, b = page(main, track, index=index), page(before, track, index=index)
        assert [a.ask(k) for k in range(9)] == [b.ask(k) for k in range(9)] and a.show() == b.show() and a.pages == b.pages == 2
        for k in range(1, 9):
            assert a.twist(k, 2) == b.twist(k, 2), (index, k)
        assert a.solos == b.solos and xf12(a)[:8] == xf12(b)[:8] and a.show() == b.show()
        assert a.locks == b.locks and a.changes == b.changes


def test_a_digital_track_that_is_no_sampler_has_one_page_as_before(main, before):
    a, b = page(main, 5, machine=4), page(before, 5, machine=4)
    assert [a.ask(k) for k in range(9)] == [b.ask(k) for k in range(9)] and a.pages == b.pages == 1 and a.index == b.index == 0
    assert a.show() == b.show() == [] and a.twist(E, 1) == b.twist(E, 1) and a.solos == 0


# ---- the mixer link and the analog mute --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def rig(main):
    return X.Rig(*main, entry="mix_amute")


@pytest.mark.parametrize("track", ANALOG)
def test_an_analog_tracks_solo_silences_the_other_eleven_and_is_kept(rig, track):
    for mutes in (0, 1 << track, 0x0fff):
        quiet, voices = K.heard(rig, knob=1 << track, mutes=mutes, pattern=mutes)
        assert quiet == [t for t in range(12) if t != track] and voices == [v for v in range(4) if 8 + v != track]
        assert rig.left == 1 << track                               # an analog track is never without its knob: the bit stays
    quiet, voices = K.heard(rig, knob=1 << track | 1 << 2)
    assert quiet == [t for t in range(12) if t not in (2, track)] and rig.left == 1 << track | 1 << 2


@pytest.mark.parametrize("xf", [[0] * 8 + [127, 0, 0, 0], [0] * 9 + [64, 0, 0], [30, 0, 0, 0, 0, 0, 0, 0, 0, 0, 100, 0], [0] * 11 + [1],
                                [5, 9, 0, 0, 0, 0, 0, 77, 77, 0, 3, 0]])
def test_an_analog_track_that_holds_the_crossfade_stays_and_the_rest_follow_the_law(rig, xf):
    shown, levels, vols, was = X.mixed(rig, xf=xf)
    assert (shown, levels) == X.law(vols, was, xf)
    assert list(rig.mc.read(mm.XFADES, 12)) == xf                   # the analog tracks' numbers are not taken away
    top = max(range(12), key=lambda t: xf[t])
    if xf.count(xf[top]) == 1 and top >= 8:                         # the holder's own voice is as stock made it when no other is up
        others = max(x for t, x in enumerate(xf) if t != top)
        if not others:
            assert levels[top - 8] == was[top - 8] and levels[top - 4] == was[top - 4]


def test_with_no_analog_number_it_is_the_dma_images_mixer(rig, before):
    old = X.Rig(*before, entry="mix_amute")
    for xf in ([0] * 8, [40, 0, 0, 0, 0, 0, 0, 0], [3, 127, 0, 9, 0, 0, 0, 50]):
        assert X.mixed(rig, xf=xf + [0] * 4) == X.mixed(old, xf=xf)
    assert K.heard(rig, knob=0x21) == K.heard(old, knob=0x21)


# ---- the image ------------------------------------------------------------------------------------------------------

def test_the_image(official_path, official, stock3, main):  # noqa: F811
    """The dma image's but for: the page's runs and a seventh, the mixer link's run, the analog mute's, four more
    bytes of 0 after the eight, and the class's pointers to the three methods."""
    quiet = lambda s: None
    built = build.build(official_path, log=quiet, xfade=4)[2]
    was = build.build(official_path, log=quiet, xfade=3)[2]
    new, old = built.section(3), was.section(3)
    assert new == main[0] != old and built.section(7) == was.section(7) and len(new) == len(old)
    syms = main[1]
    assert new[mm.off(mm.SOLO_WORD):mm.off(mm.XFADES) + 12] == bytes(16) and old[mm.off(mm.XFADES) + 8:mm.off(mm.XFADES) + 12] == stock3[mm.off(mm.XFADES) + 8:mm.off(mm.XFADES) + 12]
    assert not any(stock3.count((mm.XFADES + k).to_bytes(4, "big")) for k in range(12))
    lo, hi = mm.CAVE_PAGE7
    assert old[mm.off(lo):mm.off(hi)] == stock3[mm.off(lo):mm.off(hi)] and all(lo <= syms[s] < hi for s in ("apage_knob", "apage_draw", "apage_turn", "apage_turn_side"))
    for method, name in ((mm.PAGE_KNOB_METHOD, "apage_knob"), (mm.PAGE_DRAW_METHOD, "apage_draw"), (mm.PAGE_TURN_METHOD, "apage_turn")):
        assert mm.u32(new, mm.SYN_CLASS + method) == syms[name]
    assert mm.u32(new, mm.SYN_SIDE + mm.SYN_SIDE_TURN) == syms["apage_turn_side"]
    spans = [mm.CAVE_PAGE, mm.CAVE_PAGE2, mm.CAVE_PAGE3, mm.CAVE_PAGE4, mm.CAVE_PAGE5, mm.CAVE_PAGE6, mm.CAVE_PAGE7, mm.CAVE, mm.CAVE_AMUTE, mm.CAVE_REC,
             mm.CAVE_METER, mm.CAVE_FEED, (mm.XFADES, mm.XFADES + 12), (mm.SYN_CLASS, mm.SYN_CLASS + 0x100), (mm.SYN_SIDE, mm.SYN_SIDE + 0x40)]
    diff = [k for k in range(len(new)) if new[k] != old[k]]
    stray = [k for k in diff if not any(mm.off(a) <= k < mm.off(b) for a, b in spans)]
    assert len(stray) <= 64, [hex(mm.BASE + k) for k in stray[:20]]       # operands that name a routine that moved
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
