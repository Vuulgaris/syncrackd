"""The stsw image (engine/sampler.h, STSW): the grain image with KEYS back to two and the stretch a switch of its own.



(with the main CPU's few instructions a block). Here, the main CPU only:
  - KEYS (H) turns between CHRO and SLCE and leaves the stretch;
  - E is the track's stretch, STRC ON or OFF, SPD at 64 going into it;
  - with a step held E locks the step's, in slot 17's low byte; the TRIG page's SOLO keeps it, and it keeps the solo's;
  - the per-block routine sends a step's mark over the track's bit, as bit 6 of slot 24's low byte;
  - section 7 the grain image's.
Emulation only."""

import shutil

import pytest
from unicorn import UC_HOOK_CODE

import test_gear as G
import test_lock as L
import test_srr as R
import test_stretch as X
import test_trig as T
from test_reclock import NONE
from tools import build, build_engine, build_main
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

E, H = 5, 8
ON, OFF, NO_SOLO = 0xd5, 0xa9, 0x00     # engine/sampler.h, STSW
SLOT = 17


@pytest.fixture(scope="module")
def main(official):
    return build_main.patched_image(official.section(3), xfade=58)


@pytest.fixture(scope="module")
def engine(official):
    return build_engine.patched_image(official.section(7), grain=True)


def says(r):
    return [s for _, _, s in r.show()]


def test_keys_turns_between_chro_and_slce_and_leaves_the_stretch(main):
    t = 2
    r = X.keyed(main, t)
    for stretch in (0, 8):
        G.geared(r, [256, 256, -256, -256])     # (a kit afresh: the word after it)
        r.mc.write(G.KIT + mm.KIT_TRACK * t + mm.KIT_WORDS + 2 * mm.REC_SLOT, (R.signed(4, 0) | stretch | 16).to_bytes(2, "big"))
        for bits, name in ((2, "SLCE"), (2, "SLCE"), (0, "CHRO"), (0, "CHRO")):
            G.twist(r, H, 1)
            assert G.own(r, t) == R.signed(4, 0) | stretch | bits and name in says(r)      # bit 4, the old lock, goes


def test_e_is_the_tracks_stretch(main):
    t = 5
    r = X.keyed(main, t)
    G.geared(r, [256, 256, -256, 256])
    r.mc.write(G.KIT + mm.KIT_TRACK * t + mm.KIT_WORDS + 2 * mm.REC_SLOT, R.signed(4, 0).to_bytes(2, "big"))
    spd = G.KIT + mm.KIT_TRACK * t + mm.KIT_WORDS + 104
    r.mc.write(spd, (39 << 8).to_bytes(2, "big"))
    assert r.fifth() == ["STRC", "OFF"]
    G.twist(r, E, 1)
    assert G.own(r, t) == R.signed(4, 0) | 8 and r.fifth() == ["STRC", "ON"] and r.mc.read(spd, 1)[0] == 64
    r.mc.write(spd, (80 << 8).to_bytes(2, "big"))
    G.twist(r, E, 1)
    assert G.own(r, t) == R.signed(4, 0) | 8 and r.mc.read(spd, 1)[0] == 80          # within a stretch SPD is left alone
    G.twist(r, E, -1)
    assert G.own(r, t) == R.signed(4, 0) and r.fifth() == ["STRC", "OFF"]
    G.twist(r, H, 1)
    assert G.own(r, t) == R.signed(4, 0) | 2 and r.fifth() == ["STRC", "OFF"]       # KEYS leaves it


def sampling(r, built):
    """The rig's page as the sampling page again (T.trig made it the TRIG page)."""
    syms = built[1]
    r.syms = dict(r.syms, syn_knob=syms.get("apage_knob", syms["syn_knob"]), syn_draw=syms.get("apage_draw", syms["syn_draw"]))
    r.entry = (syms["apage_turn_side"], syms["apage_turn"]) if "apage_turn" in syms else (syms["syn_turn_side"], syms["syn_turn"])


def trigpage(r, built):
    syms = built[1]
    r.syms = dict(r.syms, syn_knob=syms["trig_knob"], syn_draw=syms["trig_draw"])
    r.entry = syms["trig_turn_side"], syms["trig_turn"]


def locks(r):
    return {s: r.lock_at(s, SLOT) for s in range(64) if r.lock_at(s, SLOT) != NONE}


def test_e_with_a_step_held_locks_the_steps_and_the_solo_keeps_it(main):
    t = 3
    r = T.trig(main, t)
    sampling(r, main)
    G.geared(r, [256, -256, 256, 256, -256, 256])
    r.mc.write(G.KIT + mm.KIT_TRACK * t + mm.KIT_WORDS + 2 * mm.REC_SLOT, R.signed(4, 0).to_bytes(2, "big"))
    r.hold(5, 9)
    G.twist(r, E, 1)
    assert locks(r) == {5: NO_SOLO << 8 | ON, 9: NO_SOLO << 8 | ON} and r.fifth() == ["STRC", "ON"]
    assert G.own(r, t) == R.signed(4, 0)                                   # the track's own is as it was
    G.twist(r, E, -1)
    assert locks(r) == {5: OFF, 9: OFF} and r.fifth() == ["STRC", "OFF"]
    trigpage(r, main)
    G.twist(r, T.E, 1)                                                     # the TRIG page's SOLO, the same steps held
    assert locks(r) == {5: mm.SOLO_LOCK_ON << 8 | OFF, 9: mm.SOLO_LOCK_ON << 8 | OFF}
    sampling(r, main)
    G.twist(r, E, 1)
    assert locks(r) == {5: mm.SOLO_LOCK_ON << 8 | ON, 9: mm.SOLO_LOCK_ON << 8 | ON}
    trigpage(r, main)
    G.twist(r, T.E, -1)
    assert locks(r) == {5: mm.SOLO_LOCK_OFF << 8 | ON, 9: mm.SOLO_LOCK_OFF << 8 | ON}
    r.hold(12)
    G.twist(r, T.E, 1)                                                     # a step with no stretch's mark: the solo's alone
    assert locks(r)[12] == mm.SOLO_LOCK_ON << 8 | 0x80


class Word(L.Word):
    """The per-block routine, and slot 17 where the locks are written put in as it starts."""

    def __init__(self, image, syms):
        super().__init__(image, syms, 14400)
        self.s17 = None
        self.mc.uc.hook_add(UC_HOOK_CODE, self._put17, None, begin=self.entry, end=self.entry)
        self.mc.uc.ctl_flush_tb()

    def _put17(self, uc, address, size, user):
        if self.s17 is not None:
            uc.mem_write(R.WRITTEN + 142 * 3 + 76 - 2 * (24 - SLOT), self.s17.to_bytes(2, "big"))     # slot 24 is at + 76


@pytest.mark.parametrize("s17", [0x0000, 0x3580, 0x1a80, NO_SOLO << 8 | ON, 0x3500 | ON, NO_SOLO << 8 | OFF, 0x1a00 | OFF, 0x40d4, 0x40aa])
def test_the_routine_sends_a_steps_mark_over_the_tracks_bit(main, s17):
    w = Word(*main)
    w.s17 = s17
    for rec in (0, 1):
        for own in (0, 8):
            got = w.run(3, R.signed(9, rec) | own)
            want = s17 & 0xff == ON or (s17 & 0xff != OFF and own != 0)
            assert bool(got["sent"] & 0x40) == want and got["own"] == R.signed(9, rec) | own, (rec, own, hex(got["sent"]))
            if not want or rec:
                assert got["sent"] >> 8 == (R.ON if rec else R.OFF)              # no stretch, or REC on: the mark
            else:
                assert got["sent"] & 0x80cf == 0x8049                           # stretched, REC off: SPD and the rest in turn
            assert got["sent"] & 0x0f == 9                                       # the source (bits 4 and 5: the lock image's tag)


def test_the_image(official_path, engine):
    quiet = lambda s: None
    raw, _, built, _, _ = build.build(official_path, log=quiet, xfade=58, prof=True)
    assert built.section(7) == engine[0]
    print("stsw image", __import__("hashlib").sha256(raw).hexdigest())
