"""The xshare image: the xknob image with knob D the pattern's one crossfade on every track.

On request


The crossfade the pattern has is the largest of the twelve numbers the analog mute makes every block (the sampler
tracks' knob D, 127 less slot 25, and the analog tracks' own). Every sampler track's D shows it, unless a held step has
a lock of its own; a turn of D with no step held first gives the turning track that amount, then goes to stock's routine
the other way round, then takes the others' away. With a step held it locks the step and leaves the holder alone.
"""
import shutil

import pytest

import test_apage as A
import test_gear as G
import test_xknob as XK
from tools import build, build_main
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

D, DEC, TOP, R_DEC = XK.D, XK.DEC, XK.TOP, XK.R_DEC
TEXT0 = 0x41ba0a38


@pytest.fixture(scope="module")
def stock3(official):
    return official.section(3)


@pytest.fixture(scope="module")
def main(stock3):
    return build_main.patched_image(stock3, xfade=27)


def first(built, track, holder=2, x=60, analog=None):
    """The first page on `track`, every digital track a sampler, `holder` with a crossfade of x in its kit and in the
    twelve numbers as the analog mute leaves them."""
    r = XK.first(built, track, {t: 44 for t in range(8)})
    for t in range(8):
        r.mc.write(G.KIT + mm.KIT_TRACK * t + mm.KIT_WORDS + 2 * DEC, ((TOP - (x if t == holder else 0)) << 8).to_bytes(2, "big"))
    xf = [x if t == holder else 0 for t in range(8)] + (analog or [0, 0, 0, 0])
    r.mc.write(mm.XFADES, bytes(xf))
    return r


def text(r, value):
    out = 0x41000100
    r.mc.call(r.syms["knob_text"], TEXT0 + 84 * R_DEC, value, out)
    raw = bytes(r.mc.read(out, 8))
    return raw[:raw.index(0)].decode()


def test_every_tracks_d_shows_the_patterns_crossfade(main):
    for track in (2, 5):
        r = first(main, track)
        own = XK.kit_dec(r, track)
        r.value = lambda holder, record, own=own: own if record == R_DEC else r.mode << 8
        assert text(r, own) == "XF60"
        r.show()
        assert r.arcs == [(60 << 8, 102, 34)]                  # the picture is drawn with the crossfade itself


def test_a_held_steps_lock_shows_its_own(main):
    r = first(main, 5)
    r.value = lambda holder, record: (TOP << 8) if record == R_DEC else r.mode << 8
    assert text(r, 27 << 8) == "XF100"                          # not the track's own value: a lock


def test_a_turn_on_another_track_carries_the_amount_and_takes_it(main):
    r = first(main, 5)
    assert G.twist(r, D, 3) == 0x77 and r.seen_steps == [-3 & 0xffffffff]
    assert [XK.kit_dec(r, t) >> 8 for t in range(8)] == [TOP - 60 if t == 5 else TOP for t in range(8)]


def test_an_analog_holders_amount_is_carried_to_a_sampler(main):
    r = first(main, 1, holder=None, x=0, analog=[0, 50, 0, 0])
    G.twist(r, D, 1)
    assert XK.kit_dec(r, 1) >> 8 == TOP - 50 and list(r.mc.read(mm.XFADES + 8, 4)) == [0, 0, 0, 0]


def test_with_a_step_held_d_locks_and_the_holder_stays(main):
    r = first(main, 5)
    r.hold(4)
    G.twist(r, D, 2)
    assert r.seen_steps == [-2 & 0xffffffff]
    assert [XK.kit_dec(r, t) >> 8 for t in range(8)] == [TOP - 60 if t == 2 else TOP for t in range(8)]


def test_the_image(official_path, main):
    quiet = lambda s: None
    raw, _, built, _, syms = build.build(official_path, log=quiet, xfade=27)
    was = build.build(official_path, log=quiet, xfade=26)[2]
    new, old = built.section(3), was.section(3)
    assert new == main[0] and built.section(7) == was.section(7)
    spans = [mm.CAVE_PAGE, mm.CAVE_PAGE2, mm.CAVE_PAGE3, mm.CAVE_PAGE4, mm.CAVE_PAGE5, mm.CAVE_PAGE6, mm.CAVE_PAGE7, mm.CAVE_PAGE8,
             mm.CAVE_PAGE9, mm.CAVE_PAGE10, mm.CAVE_TRIG, mm.CAVE_TRIG2, mm.CAVE_TRIG3, mm.CAVE_XKNOB, mm.CAVE_XKNOB2, mm.CAVE_XSHARE,
             mm.CAVE_TEXT, (mm.TEXT_SLOT_SITE + 2, mm.TEXT_SLOT_SITE + 6),
             (mm.TRIG_CLASS, mm.TRIG_CLASS + 0x100), (mm.TRIG_SIDE + 8, mm.TRIG_SIDE + 12), (mm.SYN_CLASS, mm.SYN_CLASS + 0x100),
             (mm.SYN_SIDE + 8, mm.SYN_SIDE + 12), (mm.SYN_BUILD, mm.SYN_BUILD + 0x20)]
    stray = [hex(mm.BASE + k) for k in range(len(new)) if new[k] != old[k] and not any(mm.off(a) <= k < mm.off(b) for a, b in spans)]
    assert stray == []
    print("xshare image", __import__("hashlib").sha256(raw).hexdigest())
