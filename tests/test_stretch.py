"""The stretch image (engine/sampler.h, STRETCH): the back image with a note's speed apart from its pitch.


the way back is the back image (git tag
pre-stretch), and a note on CHRO or SLCE plays as on the back image, to the bit. Here:
  - KEYS off: the back image's sound and hits to the bit;
  - stretched at its own speed and pitch: the note as it plays unstretched, near enough;
  - SPD 32, 96: twice and half as long; up an octave at SPD 64: as long, and twice the crossings;
  - what eight stretched stereo voices cost;
  - the main CPU: KEYS's four settings, REC and SRC leaving them, the bit and SPD sent.
Emulation only."""

import shutil

import numpy as np
import pytest

import test_apage as A
import test_gear as G
import test_hits as H
import test_pagerec as P
import test_slim as S
import test_srr as R
from stereo_rig import Rig
from test_fade import LENGTH, SAMPLE, START
from test_quick import ST, Folded
from tools import build, build_engine, build_main
from tools import audiomap as m
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

STR_ON = 0x40 / 256                     # slot 24 as the main CPU sends it: no REC mark, source 0, stretched
SPEED = 52


def sent24(speed):
    """Slot 24 as the main CPU sends a stretched track with REC off: 0x80 and SPD over the stretch bit."""
    return ((0x80 | speed) << 8 | 0x40) / 256
N = 24000


@pytest.fixture(scope="module")
def back(official):
    return build_engine.patched_image(official.section(7), back=True)


@pytest.fixture(scope="module")
def engine(official):
    return build_engine.patched_image(official.section(7), stretch=True)


@pytest.fixture(scope="module")
def main(official):
    return build_main.patched_image(official.section(3), xfade=53)


@pytest.fixture(autouse=True)
def folded(monkeypatch):
    monkeypatch.setattr(P, "HookEngine", Folded)


def tone(hz=500.0, n=N):
    t = np.arange(n)
    return np.round(12000 * np.sin(2 * np.pi * hz * t / 48000) * np.minimum(1, (n - t) / 2000)).astype(np.int16)


def sound(built, x, note=60, stretched=True, speed=64, blocks=None):
    """Track 0 playing x once from its start. -> what it puts out, a frame a sample."""
    e = P.engine(built, pool={0: x, 1: x})
    for slot, v in {SAMPLE: H.PK.knob_of(0), P.MODE: 0, P.TUNE: 64, LENGTH: 127, START: 0,
                    24: sent24(speed) if stretched else 0}.items():
        e.set_slot(0, slot, v)
    e.set_note(0, note)
    rows = [e.block(1 if b == 0 else 0, 0)[0] for b in range(blocks or (3 * len(x)) // 32 + 40)]
    return np.concatenate(rows).astype(np.int64)


def length(y):
    loud = np.flatnonzero(np.abs(y) > 200)
    return int(loud[-1] - loud[0]) if len(loud) else 0


def crossings(y):
    y = y[np.abs(y) > 0]
    return int(np.count_nonzero(np.diff(np.sign(y)) != 0))


def test_keys_off_is_the_back_images_to_the_bit(back, engine, official):
    factory = S.factory.__wrapped__(official)
    for case in (dict(note=55.25), dict(note=58.5, back=True, length=90)):
        a = S.render(back[0], factory, blocks=160, **case)
        b = S.render(engine[0], factory, blocks=160, **case)
        assert np.array_equal(a[1], b[1]) and np.array_equal(a[2], b[2]) and a[1].any()


def test_at_its_own_speed_and_pitch_it_is_the_note(engine):
    x = tone()
    plain, stretched = sound(engine, x, stretched=False), sound(engine, x)
    a, b = plain[64 + 64:N - 4000], stretched[64 + 64:N - 4000]
    err = np.sqrt(np.mean((a - b) ** 2)) / np.sqrt(np.mean(a ** 2))
    print("own speed: error %.5f of the note's level" % err)
    assert err < 0.01


def packed(image, factory, x, word, blocks):
    """Track 0 through the block the main CPU packs (only what crosses reaches the audio CPU). -> the frame its note
    stops at (the place's last block), or None."""
    r = Rig(image[0])
    r.load_pool({k: x for k in range(8)})
    S.T.samplers(r, factory, loop=0)
    r.set_slot(0, SAMPLE, 64)
    r.set_slot(0, START, 0)
    r.set_slot(0, LENGTH, 127)
    r.set_slot(0, 24, word)
    r.set_note(0, 60)
    r.block(0, 0)
    st = r.voice(0) + ST
    for b in range(blocks):
        r.block(1 if b == 0 else 0, 0)
        if b and not r.mc.r32(st + 20):
            return 32 * b
    return None


@pytest.mark.parametrize("speed, times", [(32, 2.0), (96, 0.5), (0, 4.0), (64, 1.0)])
def test_spd_makes_it_longer_or_shorter(engine, official, speed, times):
    factory = S.factory.__wrapped__(official)
    x = tone()
    plain = packed(engine, factory, x, 0, (2 * N) // 32)
    stretched = packed(engine, factory, x, sent24(speed), (5 * N) // 32)
    print("SPD %d: %d frames, the note %d" % (speed, stretched, plain))
    assert abs(stretched / plain - times) < 0.05


def test_an_octave_up_is_as_long_with_twice_the_crossings(engine):
    x = tone(400.0)
    own, up = sound(engine, x), sound(engine, x, note=72)
    assert abs(length(up) / length(own) - 1) < 0.05
    n = min(length(own), length(up)) - 2000
    ratio = crossings(up[100:n]) / crossings(own[100:n])
    print("an octave up: crossings x%.3f" % ratio)
    assert abs(ratio - 2) < 0.05


def test_what_eight_stretched_stereo_voices_cost(back, engine, official):
    factory = S.factory.__wrapped__(official)
    worst = []
    for image, on in ((back, False), (engine, True)):
        r = Rig(image[0])
        rng = np.random.default_rng(11)
        r.load_pool({k: rng.integers(-30000, 30000, 9000).astype(np.int16) for k in range(8)})
        S.T.samplers(r, factory, loop=1)
        for t in range(8):
            r.set_slot(t, SAMPLE, 64 + t % 3)
            r.set_slot(t, START, 0)
            r.set_slot(t, LENGTH, 127)
            r.set_slot(t, 24, sent24(40 + 9 * t) if on else 0)
            r.set_note(t, 55.25 + (t % 4) * 3.1)
        r.block(0, 0)
        cost = []
        for b in range(400):
            r.block(0xff if b % 90 == 0 else 0, 0)
            cost.append(sum(r.cost.values()))
        worst.append(max(cost))
    print("eight stereo voices, the heaviest block: back %d, stretched %d (SWARM's eight 117,348)" % tuple(worst))
    assert worst[1] <= worst[0] + 2000 and worst[1] < 117348      # about what the back image asks, and under SWARM's eight


# ---- the main CPU ---------------------------------------------------------------------------------------------------

def test_stretch_reaches_the_audio_cpu_as_bit_6_and_spd_in_the_marks_place(main):
    w = R.Word(*main)
    for rec in (1, 0):
        for keys in (0, 2, 8, 10):
            got = w.run(3, R.signed(9, rec) | keys)
            spd = w.mc.read(R.KIT + mm.KIT_TRACK * 3 + mm.KIT_WORDS + 104, 1)[0]     # the track's own SPD, as the rig left it
            mark = 0x80 | spd & 0x7f if keys & 8 and not rec else R.ON if rec else R.OFF
            assert got["sent"] == mark << 8 | (0x80 if keys & 2 else 0) | (0x40 if keys & 8 else 0) | 9
            assert got["own"] == R.signed(9, rec) | keys


def keyed(built, t):
    r = A.page(built, t)
    G.geared(r, [256] * 4 + [-256] * 4)
    r.mc.write(G.KIT + mm.KIT_TRACK * t + mm.KIT_WORDS + 2 * mm.REC_SLOT, R.signed(4, 0).to_bytes(2, "big"))
    return r


def test_h_turns_keys_through_its_four_settings(main):
    t = 2
    r = keyed(main, t)
    says = lambda: [s for _, _, s in r.show()]
    assert "CHRO" in says()
    spd = G.KIT + mm.KIT_TRACK * t + mm.KIT_WORDS + 104
    r.mc.write(spd, (39 << 8).to_bytes(2, "big"))     # PTIM as stock leaves it
    for bits, name, want in ((2, "SLCE", 39), (8, "CHST", 64), (10, "SLST", 80), (10, "SLST", 80)):
        if name == "SLST":
            r.mc.write(spd, (80 << 8).to_bytes(2, "big"))     # turned since: within a stretch it is left alone
        G.twist(r, 8, 1)
        assert G.own(r, t) == R.signed(4, 0) | bits and name in says()
        assert r.mc.read(spd, 2)[0] == want             # into a stretch: SPD at 64
    for bits, name in ((8, "CHST"), (2, "SLCE"), (0, "CHRO"), (0, "CHRO")):
        G.twist(r, 8, -1)
        assert G.own(r, t) == R.signed(4, 0) | bits and name in says()


def test_rec_and_src_leave_keys_as_it_is(main):
    t = 5
    r = keyed(main, t)
    for _ in range(3):
        G.twist(r, 8, 1)                        # SLST
    G.twist(r, 3, 1)                            # REC
    G.twist(r, 1, 1)                            # SRC
    assert G.own(r, t) & 10 == 10 and G.own(r, t) != R.signed(4, 0) | 10


def test_the_image(official_path, engine, main):
    quiet = lambda s: None
    raw, _, built, _, _ = build.build(official_path, log=quiet, xfade=53, prof=True)
    assert built.section(7) == engine[0]
    print("stretch image", __import__("hashlib").sha256(raw).hexdigest())
