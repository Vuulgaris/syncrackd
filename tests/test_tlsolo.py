"""The tlsolo image: the fltr image with a held step's SOLO always locked to what it is turned to.


The fltr image locks a step only where
it differs from the track's own solo, and drops the lock where it is the same: with the track's own off, turning a held
step to off made no lock, so an earlier trigless step's ON held until the track's next trig. Here a held step always takes
the lock it is turned to (engine/recpage.c, TLSOLO). Only the unit can show that a trigless OFF ends the solo.
"""
import shutil

import pytest

import test_gear as G
import test_trig as T
from test_reclock import NONE
from tools import build_main
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

SLOT, ON, OFF = mm.SOLO_SLOT, mm.SOLO_LOCK_ON << 8 | 0x80, mm.SOLO_LOCK_OFF << 8 | 0x80


@pytest.fixture(scope="module")
def main(official):
    return build_main.patched_image(official.section(3), xfade=29)


@pytest.fixture(scope="module")
def fltr(official):
    return build_main.patched_image(official.section(3), xfade=28)


def scene(built, held, answers, own=0):
    """Turns of the TRIG page's E with steps held. -> the steps' solo locks and the solos' long after."""
    r = T.trig(built, 1)
    r.mc.w32(mm.SOLO_WORD, own << 1)
    G.geared(r, list(answers))
    r.hold(*held)
    for _ in answers:
        G.twist(r, T.E, 1)
    return {s: r.lock_at(s, SLOT) for s in range(64) if r.lock_at(s, SLOT) != NONE}, int.from_bytes(r.mc.read(mm.SOLO_WORD, 4), "big")


def test_turning_a_held_step_off_locks_it_off_where_the_tracks_own_is_off(main, fltr):
    assert scene(main, (3, 9), (-256,)) == ({3: OFF, 9: OFF}, 0)
    assert scene(fltr, (3, 9), (-256,)) == ({}, 0)


def test_turning_on_then_off_leaves_an_off_lock_where_the_fltr_image_left_none(main, fltr):
    assert scene(main, (0,), (256, -256)) == ({0: OFF}, 0)
    assert scene(fltr, (0,), (256, -256)) == ({}, 0)


def test_on_a_soloed_track_off_and_on_are_both_locks(main, fltr):
    assert scene(main, (5,), (-256,), own=1) == scene(fltr, (5,), (-256,), own=1) == ({5: OFF}, 2)
    assert scene(main, (5,), (-256, 256), own=1) == ({5: ON}, 2)
    assert scene(fltr, (5,), (-256, 256), own=1) == ({}, 2)


@pytest.mark.parametrize("answers", [(256,), (256, 256), (-256,)])
@pytest.mark.parametrize("held", [(), (0,), (3, 9)])
def test_turning_on_and_no_step_held_are_the_fltr_images(main, fltr, held, answers):
    if held and answers == (-256,):
        return
    assert scene(main, held, answers) == scene(fltr, held, answers)
