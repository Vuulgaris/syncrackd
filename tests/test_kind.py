"""The kind image (engine/recpage.c, SKIND): the pbank image with SMPL stopping only at samples of the track's KIND.

On a STER track SMPL stops at the
stereo places that hold a sample and the lowest free one; on a MONO track at the single slots that hold one and the
highest free one. A value of the other kind (a pattern's, a lock's) turns to the nearest stop of the track's. Main CPU
only; section 7 the spread image's. Emulation only."""

import hashlib
import shutil

import pytest

import test_gear as G
import test_srr as R
import test_stops as S
from tools import build, build_main
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

KIND = 0x40


@pytest.fixture(scope="module")
def main(official):
    return build_main.patched_image(official.section(3), xfade=63)


def page(main, frames, mono, smpl=64, track=0):
    r = S.StopsPage(main, frames, smpl=smpl, track=track)
    G.geared(r)
    r.mc.write(G.KIT + mm.KIT_TRACK * track + mm.KIT_WORDS + 2 * mm.REC_SLOT, (R.signed(4, 0) | (KIND if mono else 0)).to_bytes(2, "big"))
    return r


def walk(r, start, step):
    r.answers[:] = [256 * step] * 200
    return S.walk(r, start, step)


def kind_of(numbers, mono):
    return [n for n in numbers if (n > 32) == mono]


@pytest.mark.parametrize("name", list(S.LAYOUTS))
@pytest.mark.parametrize("mono", [False, True])
def test_the_knob_stops_only_at_the_tracks_kind(main, name, mono):
    frames, numbers = S.LAYOUTS[name]
    want = S.values_of(kind_of(numbers, mono))
    if not want:
        return
    r = page(main, frames, mono)
    assert walk(r, 0, 1) == [v for v in want if v > 0] and walk(r, 127, -1) == [v for v in want if v < 127][::-1]
    assert not r.stray and not r.turned and not r.locked and not r.changes


def test_kind_flipped_changes_the_stops(main):
    frames = S.bank(stereo=(1, 2), mono=(64, 63))
    r = page(main, frames, False)
    assert walk(r, 63, 1) == [64 + n - 1 for n in (1, 2, 3)]               # 1, 2 and the free place 3
    r = page(main, frames, True)
    assert walk(r, 63, 1) == [64 + n - 1 for n in (62, 63, 64)]            # the free slot 62, then 63 and 64


def test_a_value_of_the_other_kind_turns_to_the_nearest_of_the_tracks(main):
    frames = S.bank(stereo=(1, 2), mono=(64, 63))
    r = page(main, frames, False, smpl=64 + 63 - 1)                         # on mono 63, a STER track
    r.answers[:] = [-256]
    assert r.turn_smpl(-1) == 64 + 3 - 1                                    # down to the free stereo place 3
    r = page(main, frames, True, smpl=64 + 1 - 1)                           # on stereo 1, a MONO track
    r.answers[:] = [256]
    assert r.turn_smpl(1) == 64 + 62 - 1


def test_the_image(official_path, official, main):
    quiet = lambda s: None
    raw, _, built, _, _ = build.build(official_path, log=quiet, xfade=63, prof=True)
    was_raw, _, was, _, _ = build.build(official_path, log=quiet, xfade=62, prof=True)
    print("kind image", hashlib.sha256(raw).hexdigest(), "on", hashlib.sha256(was_raw).hexdigest())
    new, old = built.section(3), was.section(3)
    assert new == main[0]
    spans = [mm.CAVE_PAGE, mm.CAVE_PAGE4, mm.CAVE_PAGE5, mm.CAVE_PAGE6, mm.CAVE_PAGE7, mm.CAVE_PAGE9, mm.CAVE_TRIG3,
             mm.CAVE_STSW, mm.CAVE_STSW2, mm.CAVE_PBANK, mm.CAVE_NEXT, mm.CAVE_NEXT2, mm.CAVE_NEXT3, mm.CAVE_NEXT4,
             mm.CAVE_NEXT5, mm.CAVE_KIND]
    assert not [hex(mm.BASE + k) for k in range(len(new)) if new[k] != old[k] and not any(mm.off(a) <= k < mm.off(b) for a, b in spans)]
    assert built.section(7) == was.section(7)
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
