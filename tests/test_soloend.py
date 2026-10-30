"""The soloend image: the scratch image with a sampler step's solo lock over once its note is.

On request.

A step's solo lock (slot 17, the slock image) stays where a trig's locks are written till the track's next trig. The
filter envelope's call (engine/hits.c) is handed the block's trigs and releases: a track's bit of solo_gone is set at
its note's release and cleared at its next trig, or when the mark in slot 17 changes (a trigless lock); the solos
(engine/amute.c, solo_now, in a run of its own) pass over a lock whose bit is set, so the track's own solo decides.
That a trig's LEN reaches this routine as a release bit is INFERRED (a take ends there, docs/FINDINGS.md).
"""
import shutil

import pytest

import test_fast as F
from emu.machine import Machine
from test_slock import ON, OFF, marks
from tools import build, build_main
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

PARAMS, LOCKS = 0x80006348, 0x800021b0


@pytest.fixture(scope="module")
def main(official):
    return build_main.patched_image(official.section(3), xfade=48)


# ---- the call of the filter's envelope: the long --------------------------------------------------------------------

@pytest.fixture(scope="module")
def env(main):
    image, syms = main
    mc = Machine()
    mc.map(0x40000000, (len(image) + 0x400 + 0xffff) & ~0xffff)
    mc.write(mm.BASE, image)
    for lo, hi in (mm.CAVE_HITS, (mm.FILTER_ENV, mm.FILTER_ENV + 0x122)):
        mc.load_code(lo, image[mm.off(lo):mm.off(hi)])
    mc.map(0x10000000, 0x2000)
    mc.map(0x43bd0000, 0x10000)
    mc.map(0x80000000, 0x10000)
    mc.map(0x7ff00000, 0x10000)
    mc.set_stack(0x7ff0f000, 0x7ff00000)
    for t in range(8):
        mc.write(PARAMS + 142 * t + 62, (44 << 8).to_bytes(2, "big"))
    return mc, syms


def block(env, trig=0, release=0, locks=None):
    mc, syms = env
    for t in range(8):
        mc.write(LOCKS + 142 * t + 28 + 2 * mm.SOLO_SLOT, (locks or {}).get(t, 0x2c00).to_bytes(2, "big"))
    mc.emac.macsr = 0x20
    mc.call(syms["hits_env"], PARAMS, trig, release, 0)
    return mc.r32(mm.SOLO_GONE)


def test_a_release_ends_the_lock_and_the_next_trig_starts_it_again(env):
    assert block(env, locks={3: ON}) == 0
    assert block(env, locks={3: ON}) == 0
    assert block(env, release=1 << 3, locks={3: ON}) == 1 << 3        # the trig's LEN is done
    assert block(env, locks={3: ON}) == 1 << 3                         # and stays so till the next trig
    assert block(env, trig=1 << 3, locks={3: ON}) == 0                 # the next trig, the same lock: on again
    assert block(env, release=0xff, locks={3: ON}) == 0xff
    assert block(env, trig=1 << 5, locks={3: ON}) == 0xff & ~(1 << 5)
    block(env, trig=0xff)


def test_only_the_eight_digital_tracks_have_a_bit(env):
    assert block(env, release=0xffffffff) == 0xff
    block(env, trig=0xff)


def test_a_release_and_the_next_trig_in_one_block_are_the_new_notes(env):
    block(env, locks={2: ON})
    assert block(env, trig=1 << 2, release=1 << 2, locks={2: ON}) == 0


def test_a_new_mark_with_no_trig_is_a_new_lock(env):
    block(env, trig=0xff, locks={6: ON})
    assert block(env, release=1 << 6, locks={6: ON}) == 1 << 6
    assert block(env, locks={6: OFF}) == 0                             # a trigless step's lock
    assert block(env, release=1 << 6, locks={6: OFF}) == 1 << 6
    assert block(env, locks={}) == 0                                   # the lock gone: nothing to end
    block(env, trig=0xff)


# ---- the solos -------------------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def rig(main):
    return F.rig(main)


def solos(rig, bits, marks, knob=0):
    """One mixer call with solo_gone at bits. -> this block's solos (SOLO_NOW)."""
    rig.mc.write(mm.SOLO_GONE, bits.to_bytes(4, "big"))
    out = F.scene(rig, marks=marks, knob=knob)[0]
    assert out[0] == 0x8000DBD0 and out[1] and out[2]
    rig.mc.write(mm.SOLO_GONE, bytes(4))
    return out[8]


@pytest.mark.parametrize("track", [0, 4, 7])
def test_a_lock_solos_till_its_note_ends_then_the_tracks_own_solo_decides(rig, track):
    assert solos(rig, 0, {track: F.ON}) == 1 << track
    assert solos(rig, 1 << track, {track: F.ON}) == 0
    assert solos(rig, 1 << track, {track: F.ON}, knob=1 << track) == 1 << track
    assert solos(rig, 0xff & ~(1 << track), {track: F.ON}) == 1 << track      # another track's end changes nothing here


def test_a_lock_off_ends_too(rig):
    assert solos(rig, 0, {2: F.OFF}, knob=1 << 2 | 1 << 5) == 1 << 5
    assert solos(rig, 1 << 2, {2: F.OFF}, knob=1 << 2 | 1 << 5) == 1 << 2 | 1 << 5


def test_an_analog_tracks_lock_is_as_it_was(rig):
    rig.mc.write(0x80002f50, bytes([0] * 8 + [8, 9, 10, 11]))         # the tracks' machines, stock's byte a track: analog
    assert solos(rig, 0xff, {9: F.ON}) == 1 << 9
    rig.mc.write(0x80002f50, bytes(12))


# ---- the image -------------------------------------------------------------------------------------------------------

def test_the_image(official_path, official, main):
    quiet = lambda s: None
    built = build.build(official_path, log=quiet, xfade=48)[2]
    was = build.build(official_path, log=quiet, xfade=47)[2]
    new, old = built.section(3), was.section(3)
    assert new == main[0] != old and built.section(7) == was.section(7) and len(new) == len(old)
    assert new[mm.off(mm.SOLO_GONE):mm.off(mm.SOLO_GONE) + 12] == bytes(12)
    spans = [mm.CAVE_HITS, mm.CAVE_SOLOEND, mm.CAVE_ALOCK, mm.CAVE_AMUTE, mm.CAVE_REC, mm.CAVE_METER, mm.CAVE_FEED, mm.CAVE_PROF,
             mm.CAVE_FAST, mm.CAVE_PRE, mm.CAVE, mm.CAVE_SRR]
    diff = [k for k in range(len(new)) if new[k] != old[k]]
    stray = [k for k in diff if not any(mm.off(a) <= k < mm.off(b) for a, b in spans)]
    assert len(stray) <= 64, [hex(mm.BASE + k) for k in stray[:20]]   # operands that name a routine that moved
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
