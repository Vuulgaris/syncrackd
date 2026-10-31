"""The lock image (engine/sampler.h, LOCK): the stretch image with a stretched note locked to the tempo."""

import shutil

import numpy as np
import pytest
from unicorn import UC_HOOK_CODE

import test_slim as S
import test_srr as R
import test_stretch as X
from stereo_rig import Rig
from test_fade import LENGTH, SAMPLE, START
from test_quick import ST, Folded
from tools import build, build_engine, build_main
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

TEMPO = 0x402d7360


@pytest.fixture(scope="module")
def engine(official):
    return build_engine.patched_image(official.section(7), lock=True)


@pytest.fixture(scope="module")
def main(official):
    return build_main.patched_image(official.section(3), xfade=54)


@pytest.fixture(autouse=True)
def folded(monkeypatch):
    monkeypatch.setattr(X.P, "HookEngine", Folded)


class Word(R.Word):
    """The per-block routine with the lock's run and the tempo."""

    def __init__(self, image, syms, tempo):
        super().__init__(image, syms)
        lo, hi = mm.CAVE_LOCK
        self.mc.map(lo & ~0xfff, 0x2000)
        self.mc.load_code(lo, image[mm.off(lo):mm.off(hi)])
        self.mc.map(TEMPO & ~0xfff, 0x1000)
        self.mc.w32(TEMPO, tempo)
        self.spd = None  # a word put in track 3's slot 52 as the routine starts (run fills the kit afresh)
        self.mc.uc.hook_add(UC_HOOK_CODE, self._put, None, begin=self.entry, end=self.entry)
        self.mc.uc.ctl_flush_tb()

    def _put(self, uc, address, size, user):
        if self.spd is not None:
            uc.mem_write(R.KIT + mm.KIT_TRACK * 3 + mm.KIT_WORDS + 104, self.spd.to_bytes(2, "big"))


@pytest.mark.parametrize("bpm", [120, 100, 87.5])
def test_the_routine_sends_spd_the_step_and_the_lock_in_turn(main, bpm):
    w = Word(*main, int(bpm * 120))
    half = 43200000 // int(bpm * 120)
    got = {}
    for _ in range(8):
        r = w.run(3, R.signed(9, 0) | 8 | 16)
        v = int.from_bytes(w.mc.read(R.KIT + mm.KIT_TRACK * 3 + mm.KIT_WORDS + 104, 2), "big")
        spd = min((v + 0x80) >> 8, 127)  # to the nearest: the knob shown at 64 sends 64
        tag = r["sent"] >> 4 & 3
        assert r["sent"] & 0x80cf == 0x8049 and r["own"] == R.signed(9, 0) | 24
        got[tag] = r["sent"] >> 8 & 0x7f
        if tag == 0:
            assert got[0] == spd
    port = w.mc.read(R.KIT + mm.KIT_TRACK * 3 + mm.KIT_WORDS + 106, 1)[0] >= 64  # as the rig left slot 53
    assert sorted(got) == [0, 1, 2, 3]
    assert got[1] | got[2] << 7 == half and got[3] == 1 | (2 if port else 0)
    r = w.run(3, R.signed(9, 1) | 8 | 16)  # REC on: the mark, untouched
    assert r["sent"] >> 8 == R.ON


@pytest.mark.parametrize("v, want", [(0x3f80, 64), (0x3fff, 64), (0x4000, 64), (0x407f, 64), (0x3f7f, 63), (0x7fc0, 127), (0xff00, 127)])
def test_spd_is_sent_to_the_nearest_whole_number(main, v, want):
    w = Word(*main, 14400)
    w.spd = v
    for _ in range(4):
        r = w.run(3, R.signed(9, 0) | 8 | 16)
        if r["sent"] >> 4 & 3 == 0:
            assert r["sent"] >> 8 & 0x7f == want
            return
    raise AssertionError("no block sent SPD")


def word(tag, payload):
    return ((0x80 | payload) << 8 | 0x40 | tag << 4) / 256


def stops(image, factory, x, bpm, spd=64, locked=True, blocks=1500, port=False):
    """A note through the packed block, the main CPU's four sends in turn. -> the frame its place stops at."""
    half = 43200000 // int(bpm * 120)
    sends = [(0, spd), (1, half & 0x7f), (2, half >> 7 & 0x7f), (3, (1 if locked else 0) | (2 if port else 0))]
    r = Rig(image[0])
    r.load_pool({k: x for k in range(8)})
    S.T.samplers(r, factory, loop=0)
    r.set_slot(0, SAMPLE, 64)
    r.set_slot(0, START, 0)
    r.set_slot(0, LENGTH, 127)
    r.set_note(0, 60)
    st = r.voice(0) + ST
    for b in range(blocks):
        r.set_slot(0, 24, word(*sends[b % 4]))
        r.block(1 if b == 0 else 0, 0)
        if b and not r.mc.r32(st + 20):
            return 32 * b
    return None


@pytest.mark.parametrize("bpm, spd, frames, want", [
    (120, 64, 26000, 24000),  # 4.33 steps: four, 6,000 frames a step
    (100, 64, 26000, 28800),  # 3.61 steps: four, 7,200
    (120, 64, 9000, 12000),  # 1.5 steps: two
    (120, 96, 26000, 12000),  # and SPD doubles it
    (120, 32, 26000, 48000),  # or halves it
])
def test_a_locked_note_takes_the_snapped_length(engine, official, bpm, spd, frames, want):
    factory = S.factory.__wrapped__(official)
    got = stops(engine, factory, X.tone(n=frames), bpm, spd)
    print("%g BPM, SPD %d, %d frames: stops at %d, the snap %d" % (bpm, spd, frames, got, want))
    assert abs(got / want - 1) < 0.01


@pytest.mark.parametrize("spd", [20, 64, 96, 127])
@pytest.mark.parametrize("keys_lock", [False, True])
def test_port_snaps_it_to_the_tempo_whatever_spd_says(engine, official, spd, keys_lock):
    factory = S.factory.__wrapped__(official)
    got = stops(engine, factory, X.tone(n=26000), 120, spd, locked=keys_lock, port=True)
    assert abs(got / 24000 - 1) < 0.01


def test_port_off_spd_is_heard_again(engine, official):
    factory = S.factory.__wrapped__(official)
    assert abs(stops(engine, factory, X.tone(n=26000), 120, 96, locked=False) - 13000) <= 64


def test_unlocked_it_is_the_stretch_images(engine, official):
    factory = S.factory.__wrapped__(official)
    assert abs(stops(engine, factory, X.tone(n=26000), 120, 96, locked=False) - 13000) <= 64  # half the sample, to the block


def test_keys_off_is_the_back_images_to_the_bit(engine, official):
    back = build_engine.patched_image(official.section(7), back=True)
    factory = S.factory.__wrapped__(official)
    a = S.render(back[0], factory, blocks=160, note=55.25)
    b = S.render(engine[0], factory, blocks=160, note=55.25)
    assert np.array_equal(a[1], b[1]) and np.array_equal(a[2], b[2]) and a[1].any()


def test_h_turns_keys_through_four_settings_and_drops_an_old_lock(main):
    t = 2
    r = X.A.page(main, t)
    X.G.geared(r, [256] * 4 + [-256] * 4)
    r.mc.write(X.G.KIT + mm.KIT_TRACK * t + mm.KIT_WORDS + 2 * mm.REC_SLOT, R.signed(4, 0).to_bytes(2, "big"))
    says = lambda: [s for _, _, s in r.show()]
    assert "CHRO" in says()
    for bits, name in ((2, "SLCE"), (8, "CHST"), (10, "SLST"), (10, "SLST")):
        X.G.twist(r, 8, 1)
        assert X.G.own(r, t) == R.signed(4, 0) | bits and name in says()
    r.mc.write(X.G.KIT + mm.KIT_TRACK * t + mm.KIT_WORDS + 2 * mm.REC_SLOT, (R.signed(4, 0) | 26).to_bytes(2, "big"))
    assert "SLST" in says() and not {"CHLK", "SLLK"} & set(says())  # a word from the first builds reads as its stretch
    for bits, name in ((8, "CHST"), (2, "SLCE"), (0, "CHRO"), (0, "CHRO")):
        X.G.twist(r, 8, -1)
        assert X.G.own(r, t) == R.signed(4, 0) | bits and name in says()


def test_the_image(official_path, engine, main):
    raw, _, built, _, _ = build.build(official_path, log=lambda s: None, xfade=54, prof=True)
    assert built.section(7) == engine[0]
    print("lock image", __import__("hashlib").sha256(raw).hexdigest())



def gate(main, mtype, own, port, kit=True, t=3):
    """port_gate as the pitch routine calls it. -> (d0, whether stock's bgts glides, d1, a1, a4 after)."""
    from emu.engine import RET
    from emu.machine import Machine
    image, syms = main
    mc = Machine()
    lo, hi = mm.CAVE_LOCK
    mc.map(lo & ~0xfff, 0x2000)
    mc.load_code(lo, image[mm.off(lo):mm.off(hi)])
    mc.map(0x80000000, 0x10000)
    mc.map(R.KIT, 0x1000)
    mc.set_stack(0x8000ff00, RET)
    block = mm.PARAM_SENT + 142 * t
    mc.write(block + 62, bytes((mtype, 0)))
    mc.write(block + 134, port.to_bytes(2, "big"))
    mc.w32(mm.KIT_POINTER, R.KIT if kit else 0)
    mc.write(R.KIT + mm.KIT_TRACK * t + mm.KIT_WORDS + 48, own.to_bytes(2, "big"))
    caller = 0x80008000  # as stock: jsr port_gate ; bgts, here to d2 = 1 (glides) or 0
    mc.load_code(caller, b"\x4e\xb9" + syms["port_gate"].to_bytes(4, "big") + bytes.fromhex("6e04" "7400" "4e75" "7401" "4e75"))
    for n, v in ((1, t), (2, 7), (9, 0x12345678), (12, block)):
        mc.set_reg(n, v)
    mc.call(caller)
    return mc.reg(0), mc.reg(2) == 1, mc.reg(1), mc.reg(9), mc.reg(12)


ON, OFF = 64 << 8, 63 << 8


@pytest.mark.parametrize("mtype, own, port, kit, glides", [
    (44, R.signed(4, 0) | 8, ON, True, False),  # a stretched sampler track: no glide, PORT on
    (44, R.signed(4, 0) | 24, ON, True, False),  # locked too
    (44, R.signed(4, 0) | 2, ON, True, True),  # SLCE: portamento on
    (44, R.signed(4, 0), ON, True, True),  # CHRO: portamento on
    (44, R.signed(4, 0) | 8, OFF, True, False),  # stretched: off, PORT either way
    (44, R.signed(4, 0), OFF, True, True),  # not stretched: on, whatever PORT says
    (44, R.signed(4, 0) | 2, OFF, True, True),
    (4, R.signed(4, 0), OFF, True, False),  # another machine, PORT off: stock's
    (4, R.signed(4, 0) | 8, ON, True, True),  # another machine: stock's
    (44, 0x0008, ON, True, True),  # a word not signed: stock's
    (44, R.signed(4, 0) | 8, ON, False, True),  # no kit yet: stock's
])
def test_portamento_follows_keys_on_a_sampler_track(main, mtype, own, port, kit, glides):
    d0, g, d1, a1, a4 = gate(main, mtype, own, port, kit)
    assert g == glides and (d1, a1, a4) == (3, 0x12345678, mm.PARAM_SENT + 142 * 3)
    ours = mtype == 44 and kit and own & 0xf0e4 == R.SIG
    assert d0 == ((0 if own & 8 else ON) if ours else port)


def test_the_pitch_routine_calls_the_gate(main):
    image, syms = main
    at = mm.off(mm.PORT_CHECK)
    assert image[at:at + 12] == b"\x4e\xb9" + syms["port_gate"].to_bytes(4, "big") + bytes.fromhex("4e714e71") + bytes.fromhex("6e06")
