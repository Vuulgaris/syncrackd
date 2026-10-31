"""The slice image: the tlsolo image with a sampler track's keys playing its sample's slices.





KEYS is the sampling page's knob H, CHRO or SLCE, bit 1 of the track's own word on slot 24; the main CPU sends it as
bit 7 of slot 24's low byte (engine/recword.S). On a note's start with it on, the note less 60 picks a slice, round
the count both ways, and is taken off the pitch. The slices are the scan's hits, the first from frame 0; with no list
yet, 16 even ones. STRT and LEN are the slice's. The peak and the profile's switch are knob G's.

Not held here: that the key's note reaches the audio CPU in pmod as the rig puts it there (a note number in 16.16, 60
the sample's own pitch: the pitch image's reading, and every pitched note on the unit since), and how it plays.
"""
import shutil

import numpy as np
import pytest

import test_apage as A
import test_gear as G
import test_hits as H
import test_srr as S
from test_quick import ST
from tools import build, build_engine, build_main
from tools import audiomap as m
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

KEYS_ON = 0x80 / 256                    # slot 24 as the main CPU sends it: no REC mark, source 0, KEYS


@pytest.fixture(scope="module")
def engine(official):
    return build_engine.patched_image(official.section(7), xknob=True, slice=True)


@pytest.fixture(scope="module")
def main(official):
    return build_main.patched_image(official.section(3), xfade=31)


def x4():
    return H.bursts(24000, ((0, 20000), (6000, 12000), (12000, 16000), (18000, 9000)))


def note(built, x, n, keys=True, scan=True, knobs=None):
    """A note n on track 0 of a slot holding x, gone over first if scan. -> (first frame, end, pitch step)."""
    image, syms = built
    e = H.P.engine(built, pool={0: x, 1: x})
    ks = {H.P.SAMPLE: H.PK.knob_of(0), H.P.MODE: 0, H.P.TUNE: 64, H.P.LENGTH: 127, 24: KEYS_ON if keys else 0, **(knobs or {})}
    for slot, v in ks.items():
        e.set_slot(0, slot, v)
    e.set_note(0, n)
    if scan:
        for _ in range(len(x) // 128 + len(x) // 256 + 8):
            e.mc.call(syms["hits_block"])
    e.block(1, 0)
    e.block(0, 0)                               # the note starts a block after its trig
    st = e.voice(0) + ST
    return H.s32(e.mc.r32(st + 36)), H.s32(e.mc.r32(st + 40)), e.mc.r32(st + 24), H.kept(e, 0)[0]


# ---- the audio CPU --------------------------------------------------------------------------------------------------

def test_each_key_plays_its_hit_to_the_next_the_first_from_0_and_round_both_ways(engine):
    x = x4()
    hits = note(engine, x, 60)[3]
    starts = [0] + [a for a, _, _ in hits[1:]] + [len(x)]
    assert len(hits) == 4 and [a for a, _, _ in hits] == [f // 32 * 32 for f in (0, 6000, 12000, 18000)]    # a hit's window
    for n in range(56, 70):
        i = (n - 60) % 4
        a, b, inc, _ = note(engine, x, n)
        assert (a, b) == (starts[i], starts[i + 1]), n
        assert inc == 4096                      # a slice at its own pitch, whatever the key


def test_keys_off_is_stocks_whole_sample_at_the_keys_pitch(engine):
    a, b, inc, _ = note(engine, x4(), 72, keys=False)
    assert (a, b, inc) == (0, 24000, 8192)


def test_no_list_yet_is_16_even_slices(engine):
    x = x4()
    for n, i in ((60, 0), (63, 3), (75, 15), (76, 0), (59, 15)):
        a, b, _, _ = note(engine, x, n, scan=False)
        assert (a, b) == (len(x) * i >> 4, len(x) * (i + 1) >> 4), n


def test_strt_and_len_are_the_slices(engine):
    a, b, _, _ = note(engine, x4(), 61, knobs={20: 64, H.P.LENGTH: 64})
    assert 8900 <= a <= 9100 and 10400 <= b <= 10600          # half way into 5984..12000, and half of what is left


# ---- the main CPU ---------------------------------------------------------------------------------------------------

def test_keys_reaches_the_audio_cpu_as_bit_7_under_the_source(main):
    w = S.Word(*main)
    for src in (0, 9, 15):
        for rec in (0, 1):
            for keys in (0, 2):
                got = w.run(3, S.signed(src, rec) | keys)
                assert got["sent"] == (S.ON if rec else S.OFF) << 8 | (0x80 if keys else 0) | src
                assert got["own"] == S.signed(src, rec) | keys        # signed with it, so nothing is made again from MODE


def keyed(built, t):
    r = A.page(built, t)
    G.geared(r, [256, -256, 256, 256])
    r.mc.write(G.KIT + mm.KIT_TRACK * t + mm.KIT_WORDS + 2 * mm.REC_SLOT, S.signed(4, 0).to_bytes(2, "big"))
    return r


def test_h_turns_keys_and_the_last_place_says_it(main):
    t = 2
    r = keyed(main, t)
    texts = r.show()
    assert ("KEYS" in [s for _, _, s in texts]) and "CHRO" in [s for _, _, s in texts]
    G.twist(r, 8, 1)
    assert G.own(r, t) == S.signed(4, 0) | 2 and "SLCE" in [s for _, _, s in r.show()]
    G.twist(r, 8, -1)
    assert G.own(r, t) == S.signed(4, 0) and "CHRO" in [s for _, _, s in r.show()]


def test_rec_and_src_leave_keys_as_it_is(main):
    t = 5
    r = keyed(main, t)
    G.twist(r, 8, 1)                            # KEYS on
    G.twist(r, 3, 1)                            # REC
    G.twist(r, 1, 1)                            # SRC
    assert G.own(r, t) & 2 and G.own(r, t) != S.signed(4, 0) | 2


def test_the_peak_is_in_gs_place_and_keys_in_hs(main, official):
    r, old = A.page(main, 2), A.page(build_main.patched_image(official.section(3), xfade=29), 2)
    for q in (r, old):
        q.mc.map(0x80003000, 0x1000)
        q.mc.write(0x100005b4, b"\x00\x00\x00\x00" + b"P085")
    new, was = r.show(), old.show()
    p_new = [t for t in new if len(t[2]) == 4 and t[2][1:].isdigit()]
    p_was = [t for t in was if len(t[2]) == 4 and t[2][1:].isdigit()]
    keys = [t for t in new if t[2] in ("KEYS", "CHRO")]
    assert len(p_new) == len(p_was) == 1 and p_new[0][0] < p_was[0][0]
    assert [t[0] for t in keys] == [p_was[0][0]] * 2
    print("slice: peak", p_new, "was", p_was, "keys", keys)


# ---- the image ------------------------------------------------------------------------------------------------------

def test_the_image(official_path, main):
    quiet = lambda s: None
    raw, _, built, _, _ = build.build(official_path, log=quiet, xfade=31, prof=True)
    was_raw, _, was, _, _ = build.build(official_path, log=quiet, xfade=29, prof=True)
    assert __import__("hashlib").sha256(was_raw).hexdigest().startswith("ffae2495")      # the tlsolo image, as it is with the fltr image's fourth build under it (8de0ec13 on the third)
    new, old = built.section(3), was.section(3)
    assert new == main[0]
    spans = [mm.CAVE_FLTR, mm.CAVE_PAGE, mm.CAVE_PAGE2, mm.CAVE_PAGE3, mm.CAVE_PAGE4, mm.CAVE_PAGE5, mm.CAVE_PAGE6,
             mm.CAVE_PAGE7, mm.CAVE_PAGE8, mm.CAVE_PAGE9, mm.CAVE_PAGE10, mm.CAVE_TRIG, mm.CAVE_TRIG2, mm.CAVE_TRIG3,
             mm.CAVE_XKNOB, mm.CAVE_XKNOB2, mm.CAVE_XSHARE, mm.CAVE_SRR, mm.CAVE_METER]
    ours = lambda b, j: any(lo <= int.from_bytes(b[j:j + 4], "big") < hi for lo, hi in spans)
    moved3 = lambda k: any(ours(new, j) and ours(old, j) for j in range(k - 3, k + 1))     # a pointer to one of our routines, moved
    stray = [hex(mm.BASE + k) for k in range(len(new)) if new[k] != old[k] and not any(mm.off(a) <= k < mm.off(b) for a, b in spans)
             and not moved3(k)]
    assert stray == []
    a7, b7 = built.section(7), was.section(7)
    runs = [r for d in (m.CAVES, m.REC_CAVES, m.PITCH_CAVES, m.FADE_CAVES, m.LIVE_CAVES, m.ONE_CAVES, m.QUICK_CAVES, m.LEAN_CAVES,
                         m.TIMED_CAVES, m.CROSS_CAVES, m.SRR_CAVES, m.HITS_CAVES) for r in d.values()]
    into = lambda b, j: any(lo <= int.from_bytes(b[j:j + 4], "big") < hi for lo, hi in runs)
    moved = lambda k: any(into(a7, j) and into(b7, j) for j in range(k - 3, k + 1))
    stray7 = [hex(m.BASE + k) for k in range(len(a7)) if a7[k] != b7[k] and not any(m.off(lo) <= k < m.off(hi) for lo, hi in runs) and not moved(k)]
    assert stray7 == [] and a7 != b7
    print("slice image", __import__("hashlib").sha256(raw).hexdigest())
