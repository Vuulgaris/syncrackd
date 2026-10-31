"""The gfade image: the xfade image with one crossfade for the whole unit.




)

The eight numbers of the xfade image hold the one crossfade in the place of the track that last turned it, the rest 0,
so the mixer's rule and the analog voices' are the xfade image's own code, tested there.
"""
import pytest

import test_xfade as X
from test_xfade import stock3  # noqa: F401  (a fixture)
from tools import build, build_main
from tools import mainmap as mm

G = X.XF_KNOB


@pytest.fixture(scope="module")
def main(stock3):  # noqa: F811
    return build_main.patched_image(stock3, xfade=2)


@pytest.fixture(scope="module")
def before(stock3):  # noqa: F811
    return build_main.patched_image(stock3, xfade=True)


@pytest.mark.parametrize("track", [0, 3, 4, 7])
def test_every_track_shows_the_one_crossfade(main, track):
    for holder in range(8):
        xf = [40 if t == holder else 0 for t in range(8)]
        assert X.Page(main, track=track, xf=xf).third() == ["", "XF40"]
    assert X.Page(main, track=track).third() == ["", "XF0"]


@pytest.mark.parametrize("track", [0, 2, 5, 7])
@pytest.mark.parametrize("holder", [0, 3, 6])
def test_the_track_that_turns_it_takes_it_and_is_the_one_that_stays(main, track, holder):
    r = X.Page(main, track=track, xf=[40 if t == holder else 0 for t in range(8)])
    assert r.twist(G, 3) == 1
    assert r.xf == [43 if t == track else 0 for t in range(8)] and r.third() == ["", "XF43"]
    for steps, want in ((300, 127), (1, 127), (-27, 100), (-300, 0), (-1, 0), (5, 5)):
        r.twist(G, steps)
        assert r.xf == [want if t == track else 0 for t in range(8)] and r.third() == ["", "XF%d" % want]
    assert not r.locks and not r.locked and not r.changes and not r.popped and r.redrawn


def test_a_turn_never_leaves_all_eight_at_0_on_the_way(main):
    """The per-block routine may run between two instructions of a turn: the track's own long is written first."""
    r = X.Page(main, track=6, xf=[0, 90, 0, 0, 0, 0, 0, 0])
    r.twist(G, 1)
    assert r.xf == [0, 0, 0, 0, 0, 0, 91, 0]
    first = r.xf_writes[0]
    assert first[0] in (4, 6), r.xf_writes          # the long that holds track 7's byte (or the byte itself) comes first


def test_the_other_knobs_and_the_image(official_path, official, main, before):
    for k in range(1, 9):
        if k != G:
            a, b = X.Page(main, track=3), X.Page(before, track=3)
            assert a.twist(k, 2) == b.twist(k, 2) and a.xf == b.xf == [0] * 8
    quiet = lambda s: None
    built = build.build(official_path, log=quiet, xfade=2)[2]
    was = build.build(official_path, log=quiet, xfade=True)[2]
    assert built.section(3) == main[0] != was.section(3) and built.section(7) == was.section(7)
    new, old = built.section(3), was.section(3)
    assert len(new) == len(old)
    diff = [k for k in range(len(new)) if new[k] != old[k]]
    runs = [mm.CAVE_PAGE, mm.CAVE_PAGE2, mm.CAVE_PAGE3, mm.CAVE_PAGE4, mm.CAVE_PAGE5, mm.CAVE_PAGE6]
    stray = [k for k in diff if not any(mm.off(lo) <= k < mm.off(hi) for lo, hi in runs)]
    assert len(stray) <= 64, len(stray)             # outside the page's runs only operands that name a routine that moved
    for sid in official.ids:
        if sid not in (3, 7):
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
