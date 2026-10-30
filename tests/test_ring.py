"""The ring image: the slice image with LEN on a slice reaching to the sample's end, so a slice rings on past the next.

On request
. On the slice image a slice ends at the next hit and LEN is a share of that. Here (engine/sampler.c, RING,
in slice_cut) LEN is the share of what is left from the slice's start to the sample's end, the rule a whole sample has
(LEN 127 to the end); STRT stays inside the slice. Audio CPU only: the main CPU is the slice image's.

Held here by running the engine as tests/test_slice.py does; not held: how it sounds.
"""
import hashlib
import shutil

import pytest

import test_slice as SL
import test_hits as H
from tools import build, build_engine
from tools import audiomap as m

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")


@pytest.fixture(scope="module")
def engine(official):
    return build_engine.patched_image(official.section(7), xknob=True, slice=True, ring=True)


@pytest.fixture(scope="module")
def before(official):
    return build_engine.patched_image(official.section(7), xknob=True, slice=True)


def test_at_len_127_each_slice_rings_from_its_hit_to_the_sample_s_end(engine):
    x = SL.x4()
    hits = SL.note(engine, x, 60)[3]
    starts = [0] + [a for a, _, _ in hits[1:]]
    for n in range(56, 70):
        a, b, inc, _ = SL.note(engine, x, n)
        assert (a, b) == (starts[(n - 60) % 4], len(x)), n
        assert inc == 4096


def test_len_is_the_share_of_what_is_left_to_the_end_as_on_a_whole_sample(engine):
    x = SL.x4()
    hits = SL.note(engine, x, 60)[3]
    for ln in (1, 32, 64, 100):
        assert SL.note(engine, x, 60, knobs={H.P.LENGTH: ln})[1] == SL.note(engine, x, 60, keys=False, knobs={H.P.LENGTH: ln})[1], ln
    ends = [SL.note(engine, x, 61, knobs={H.P.LENGTH: ln})[1] for ln in (16, 32, 64, 100, 127)]
    assert ends == sorted(ends) and ends[-1] == len(x)
    assert ends[2] > hits[2][0]                 # slice 1 at LEN 64 rings on past slice 2's start


def test_strt_stays_inside_the_slice(engine, before):
    for n in (61, 63):
        assert SL.note(engine, SL.x4(), n, knobs={20: 64, H.P.LENGTH: 64})[0] == SL.note(before, SL.x4(), n, knobs={20: 64, H.P.LENGTH: 64})[0]


def test_no_list_yet_rings_from_the_even_slice_to_the_end(engine):
    x = SL.x4()
    for n, i in ((60, 0), (63, 3), (75, 15)):
        assert SL.note(engine, x, n, scan=False)[:2] == (len(x) * i >> 4, len(x)), n


def test_keys_off_is_the_whole_sample_as_before(engine, before):
    assert SL.note(engine, SL.x4(), 72, keys=False)[:3] == SL.note(before, SL.x4(), 72, keys=False)[:3] == (0, 24000, 8192)


def test_the_image(official_path):
    quiet = lambda s: None
    raw, _, built, _, _ = build.build(official_path, log=quiet, xfade=32, prof=True)
    was_raw, _, was, _, _ = build.build(official_path, log=quiet, xfade=31, prof=True)
    assert hashlib.sha256(was_raw).hexdigest().startswith("49d08141")      # the slice image, as it is
    assert built.section(3) == was.section(3)
    a7, b7 = built.section(7), was.section(7)
    runs = [r for d in (m.CAVES, m.REC_CAVES, m.PITCH_CAVES, m.FADE_CAVES, m.LIVE_CAVES, m.ONE_CAVES, m.QUICK_CAVES, m.LEAN_CAVES,
                         m.TIMED_CAVES, m.CROSS_CAVES, m.SRR_CAVES, m.HITS_CAVES) for r in d.values()]
    into = lambda b, j: any(lo <= int.from_bytes(b[j:j + 4], "big") < hi for lo, hi in runs)
    moved = lambda k: any(into(a7, j) and into(b7, j) for j in range(k - 3, k + 1))
    stray7 = [hex(m.BASE + k) for k in range(len(a7)) if a7[k] != b7[k] and not any(m.off(lo) <= k < m.off(hi) for lo, hi in runs) and not moved(k)]
    assert stray7 == [] and a7 != b7
    print("ring image", hashlib.sha256(raw).hexdigest())
