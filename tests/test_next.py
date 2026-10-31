"""The next image (engine/recpage.c, NEXT): the trans image with DEST SMPL or NEXT and knob C the track's KIND.




Here, the main CPU only:
  - B is DEST, SMPL or NEXT; C is KIND, STER or MONO, bit 6 of the track's word on slot 24, kept by a turn of SRC;
  - at a message the main task gives each NEXT track a free place of its KIND, none another holds, and the box sends its
    takes there; once the stops say the place holds something, the track's SMPL is on it, the way it was turned;
  - while the audio CPU is down nothing held is believed, and with no track on NEXT the poll reads two longs;
  - the word with bit 6 is signed in the per-block routine too;
  - section 7 the spread image's.
Emulation only."""

import hashlib
import shutil

import pytest
from unicorn import UC_HOOK_CODE

import test_gear as G
import test_srr as R
import test_stretch as X
from test_stops import bank, said
from tools import build, build_main
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

A_, B_, C_ = 1, 2, 3                    # knobs SRC, DEST, KIND
KIND = 0x40
SENT = 0x80006348                       # the block the audio CPU is sent: a track's machine at + 62
BOX = 0x10000e20 + 8                    # struct recbox's dest[8]
DEST_SMPL = 0xffff


@pytest.fixture(scope="module")
def main(official):
    return build_main.patched_image(official.section(3), xfade=61)


def says(r):
    return [s for _, _, s in r.show()]


def rig(main, t, frames=None, up=1, mark=mm.STOPS_OK):
    r = X.keyed(main, t)
    mc = r.mc
    for base in (mm.AUDIO_UP & ~0xfff, SENT & ~0xfff):
        try:
            mc.map(base, 0x1000)
        except Exception:
            pass
    mc.w32(mm.AUDIO_UP, up)
    for u in range(8):
        mc.write(SENT + 142 * u + 62, bytes([44]))
        mc.write(G.KIT + mm.KIT_TRACK * u + mm.KIT_WORDS + 2 * mm.REC_SLOT, R.signed(4, 0).to_bytes(2, "big"))
    put(r, frames or [0] * 64, mark)
    return r


def turns(r, *steps):
    """What stock's change routine answers for each turn of the page's knobs, in order: a step each way."""
    r.answers[:] = [256 * x for x in steps]


def put(r, frames, mark=mm.STOPS_OK):
    for a, w in zip(mm.STOPS_LONGS, said(frames)):
        r.mc.w32(mm.SHARED + a, w)
    r.mc.w32(mm.SHARED + mm.STOPS_MARK, mark)


def word(r, t):
    return int.from_bytes(r.mc.read(G.KIT + mm.KIT_TRACK * t + mm.KIT_WORDS + 2 * mm.REC_SLOT, 2), "big")


def smpl(r, t):
    return int.from_bytes(r.mc.read(G.KIT + mm.KIT_TRACK * t + mm.KIT_WORDS + 2 * 19, 2), "big") >> 8


def set_smpl(r, t, v):
    r.mc.write(G.KIT + mm.KIT_TRACK * t + mm.KIT_WORDS + 2 * 19, (v << 8).to_bytes(2, "big"))


def dest(r, t):
    return int.from_bytes(r.mc.read(BOX + 2 * t, 2), "big")


def poll(r, main):
    r.mc.call(main[1]["next_poll"])


def on(r, main, t, mono=False):
    """Track t's KIND, and its DEST to NEXT as the page's turn leaves it (next_tell): on, and the slots to go over."""
    r.mc.write(G.KIT + mm.KIT_TRACK * t + mm.KIT_WORDS + 2 * mm.REC_SLOT, (R.signed(4, 0) | (KIND if mono else 0)).to_bytes(2, "big"))
    nx = main[1]["next_vars"]
    r.mc.write(nx + 20 + t, b"\x01")
    r.mc.w32(nx + 16, 1)


def test_dest_is_smpl_or_next_and_c_the_tracks_kind(main):
    t = 2
    r = rig(main, t)
    turns(r, 1, 1, -1, 1, 1, -1)
    assert "SMPL" in says(r) and "STER" in says(r) and "KIND" in says(r) and "REC" not in says(r)
    G.twist(r, B_, 1)
    assert "NEXT" in says(r) and dest(r, t) == DEST_SMPL      # no place yet: the poll gives it
    G.twist(r, B_, 1)
    assert "NEXT" in says(r)
    G.twist(r, B_, -1)
    assert "SMPL" in says(r) and dest(r, t) == DEST_SMPL
    G.twist(r, C_, 1)
    assert word(r, t) == R.signed(4, 0) | KIND and "MONO" in says(r)
    G.twist(r, A_, 1)                                           # SRC turned: KIND stays
    assert word(r, t) & KIND and word(r, t) >> 8 & 15 != 4
    G.twist(r, C_, -1)
    assert not word(r, t) & KIND and "STER" in says(r)
    assert not r.locks and not r.locked


def test_a_next_track_holds_the_first_free_place_of_its_kind(main):
    frames = bank(stereo=(1, 2, 3), mono=(64, 63))
    r = rig(main, 0, frames)
    on(r, main, 0)
    poll(r, main)
    assert dest(r, 0) == 3                                      # places from 0: stereo place 4
    r2 = rig(main, 5, frames)
    on(r2, main, 5, mono=True)
    poll(r2, main)
    assert dest(r2, 5) == 61                                    # single slot 62


def test_two_tracks_of_a_kind_hold_two_places(main):
    r = rig(main, 1, bank(stereo=(1,)))
    on(r, main, 1)
    on(r, main, 4)
    poll(r, main)
    assert (dest(r, 1), dest(r, 4)) == (1, 2)
    on(r, main, 6, mono=True)                                   # and a single slot is never inside a held stereo place
    poll(r, main)
    assert dest(r, 6) == 63 and (dest(r, 1), dest(r, 4)) == (1, 2)


@pytest.mark.parametrize("was, now", [(70, 64 + 3), (10, 63 - 3)])
def test_the_take_landing_moves_smpl_to_it_and_the_next_free_place_is_held(main, was, now):
    frames = bank(stereo=(1, 2, 3))
    r = rig(main, 3, frames)
    set_smpl(r, 3, was)
    on(r, main, 3)
    poll(r, main)
    assert dest(r, 3) == 3 and smpl(r, 3) == was
    poll(r, main)                                               # nothing changed: nothing done
    assert smpl(r, 3) == was
    put(r, bank(stereo=(1, 2, 3, 4)))
    poll(r, main)
    assert smpl(r, 3) == now and dest(r, 3) == 4


def test_a_mono_take_lands_too(main):
    r = rig(main, 7)
    set_smpl(r, 7, 64)
    on(r, main, 7, mono=True)
    poll(r, main)
    assert dest(r, 7) == 63
    put(r, bank(mono=(64,)))
    poll(r, main)
    assert smpl(r, 7) == 64 + 63 and dest(r, 7) == 62


def test_a_kind_turned_drops_the_place_and_moves_nothing(main):
    r = rig(main, 2)
    set_smpl(r, 2, 64)
    on(r, main, 2)
    poll(r, main)
    assert dest(r, 2) == 0
    turns(r, 1)
    G.twist(r, C_, 1)
    assert word(r, 2) & KIND
    poll(r, main)
    assert dest(r, 2) == 63 and smpl(r, 2) == 64


def test_smpl_again_sends_smpl(main):
    r = rig(main, 2)
    turns(r, 1, -1)
    G.twist(r, B_, 1)
    poll(r, main)
    assert dest(r, 2) == 0
    G.twist(r, B_, -1)
    assert dest(r, 2) == DEST_SMPL
    poll(r, main)
    assert dest(r, 2) == DEST_SMPL


def test_no_free_place_is_smpl(main):
    r = rig(main, 0, bank(stereo=range(1, 33)))
    on(r, main, 0)
    poll(r, main)
    assert dest(r, 0) == DEST_SMPL


@pytest.mark.parametrize("up, mark", [(0, mm.STOPS_OK), (1, 0)])
def test_while_the_audio_cpu_is_down_nothing_held_is_believed(main, up, mark):
    r = rig(main, 3, bank(stereo=(1,)))
    set_smpl(r, 3, 64)
    on(r, main, 3)
    poll(r, main)
    assert dest(r, 3) == 1
    r.mc.w32(mm.AUDIO_UP, up)
    r.mc.w32(mm.SHARED + mm.STOPS_MARK, mark)
    put(r, bank(stereo=(1, 2)), mark)                           # samples loaded while it was down: no take of the track's
    poll(r, main)
    r.mc.w32(mm.AUDIO_UP, 1)
    put(r, bank(stereo=(1, 2)))
    poll(r, main)
    assert smpl(r, 3) == 64 and dest(r, 3) == 2


def test_another_machine_holds_nothing(main):
    r = rig(main, 3)
    on(r, main, 3)
    r.mc.write(SENT + 142 * 3 + 62, bytes([7]))
    poll(r, main)
    assert dest(r, 3) == DEST_SMPL


def counted(r, main):
    n = [0]
    h = r.mc.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, u: n.__setitem__(0, n[0] + 1))
    poll(r, main)
    r.mc.uc.hook_del(h)
    return n[0]


def test_what_a_message_costs(main):
    r = rig(main, 3, bank(stereo=(1,)))
    idle = counted(r, main)
    on(r, main, 3)
    counted(r, main)
    same = counted(r, main)
    put(r, bank(stereo=(1, 2)))
    full = counted(r, main)
    print("a message: no NEXT", idle, "nothing changed", same, "the slots changed", full)
    assert idle < 12 and same < 80 and full < 4000             # no track on NEXT: two longs; nothing changed: the five read


def test_the_main_task_polls_at_each_message(main):
    image, syms = main
    at = mm.off(mm.CAVE_ONCE[0])
    assert (b"\x4e\xb9" + syms["next_poll"].to_bytes(4, "big")) in image[at:mm.off(mm.CAVE_ONCE[1])]


def test_the_image(official_path, official, main):
    quiet = lambda s: None
    raw, _, built, _, _ = build.build(official_path, log=quiet, xfade=61, prof=True)
    was_raw, _, was, _, _ = build.build(official_path, log=quiet, xfade=60, prof=True)
    assert hashlib.sha256(was_raw).hexdigest().startswith("b41bad57")      # the trans image, as it is
    print("next image", hashlib.sha256(raw).hexdigest())
    new, old = built.section(3), was.section(3)
    assert new == main[0]
    spans = [mm.CAVE_PAGE, mm.CAVE_PAGE4, mm.CAVE_PAGE6, mm.CAVE_PAGE7, mm.CAVE_PAGE9, mm.CAVE_TRIG3, mm.CAVE_STSW, mm.CAVE_STSW2,
             mm.CAVE_ONCE, mm.CAVE_SRR, mm.CAVE_LOCK, mm.CAVE_NEXT, mm.CAVE_NEXT2, mm.CAVE_NEXT3, mm.CAVE_NEXT4, mm.CAVE_NEXT5]
    assert not [hex(mm.BASE + k) for k in range(len(new)) if new[k] != old[k] and not any(mm.off(a) <= k < mm.off(b) for a, b in spans)]
    assert built.section(7) == was.section(7)
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
