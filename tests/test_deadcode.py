"""tools/deadcode.py: code that nothing reaches, in both programs.

The audio program is the check on the method: its unreached runs were found by hand first
and never run while every stock machine plays (tests/test_sampler.py). The main program's
result is static evidence only.
"""
import pytest

from tools import audiomap as am
from tools import build_main, deadcode
from tools import mainmap as mm
from tools import fw


@pytest.fixture(scope="module")
def audio(official):
    return deadcode.survey(official.section(7), am.BASE, am.CODE_END, am.ENTRY)


@pytest.fixture(scope="module")
def main(official):
    return deadcode.survey(official.section(3), mm.BASE, mm.CODE_END, mm.ENTRY,
                           [official.section(k) for k in (2, 4, 6, 8)])


def holds(runs, a):
    return [(lo, hi) for lo, hi, *_ in runs if lo <= a < hi]


def test_main_map_marks_where_the_code_ends(official):
    stock = official.section(3)
    assert int.from_bytes(stock[:4], "big") == mm.ENTRY
    assert stock[mm.off(mm.CODE_END) - 2:mm.off(mm.CODE_END)] == b"\x4e\x75"
    assert stock[mm.off(mm.CODE_END):mm.off(mm.CODE_END) + 14] == bytes(14)
    # past it: tables, and one island of code that is copied elsewhere to run. No function entry (linkw) until then
    assert stock[mm.off(mm.CODE_END):mm.off(0x401c8000)].count(fw.sb("6f96a319c26a2aff")) == 0


def test_audio_survey_finds_the_runs_the_sampler_lives_in(audio):
    """Found by hand first; the survey has to agree."""
    usable = deadcode.usable(audio, least=64)
    for cave in list(am.CAVES.values()) + list(am.REC_CAVES.values()):
        assert tuple(cave) in usable
    assert (len(audio), sum(hi - lo for lo, hi, *_ in audio)) == (18, 6668)
    assert sum(hi - lo for lo, hi in usable) == 6216
    # nothing the map names as live sits in a run
    for name in ("VOICE_LOOP", "ENVELOPE", "VOICE_RESET", "VOICE_PRE", "NOISE_SEED"):
        assert not holds(audio, getattr(am, name)), name


def test_main_survey_agrees_with_what_is_known(main, official):
    usable = deadcode.usable(main, least=64)
    # the two runs our main CPU code already sits in, found by hand before this tool
    assert mm.CAVE in usable and mm.CAVE_AMUTE in usable
    # a routine found dead on its own while tracing the sample store
    assert holds(main, mm.SAMPLE_ERASE)
    # no other code address in the map is in a run
    known = {mm.CAVE[0], mm.CAVE_AMUTE[0], mm.SAMPLE_ERASE, mm.CAVE_KEEP[0], mm.CAVE_HALVES[0], mm.CAVE_TEXT[0], mm.CAVE_PAGE[0], mm.CAVE_PAGE2[0], mm.CAVE_BANK[0],    # the last six: chosen from this survey
             mm.CAVE_METER[0], mm.CAVE_PAGE3[0], mm.METER_SRC, mm.METER_QUIET, mm.METER_LEVEL,   # the meter image's two, and its numbers in the first
             mm.CAVE_RIGHT[0],                                                                  # the stereo image's
             mm.CAVE_PAGE4[0], mm.METER_GAIN, mm.REC_GAINS,                                     # the gain image's: the page's fourth run, and its numbers after the meter's
             mm.CAVE_PAGE5[0], mm.CAVE_PAGE6[0],                                                # the stops image's: the page's fifth and sixth
             mm.CAVE_SOLO[0],                                                                   # the solo image's
             mm.CAVE_FEED[0],                                                                   # the feed image's: the routine that writes a block of a take
             mm.CAVE_ONCE[0], mm.ONCE_DIRTY}                                                    # the once image's: its sixteen bytes (the second eight) and its code
    for name in dir(mm):
        v = getattr(mm, name)
        for a in (v if isinstance(v, tuple) else (v,)):
            if isinstance(a, int) and mm.BASE <= a < mm.CODE_END and a not in known:
                assert not holds(main, a), name
    # every place the images patch that is not one of our own runs is live code:
    # those patches run on the unit (mixer link, mute, knob display, recorder feed, big slots)
    ours = (mm.CAVE, mm.CAVE_AMUTE, mm.CAVE_REC)
    stock = official.section(3)
    for p in build_main.patches(stock, mixer=True, rec=True, big=True)[0]:
        a = mm.BASE + p.offset
        if p.section == 3 and a < mm.CODE_END and not any(lo <= a < hi for lo, hi in ours):
            assert not holds(main, a), hex(a)


def test_main_survey_numbers(main):
    """The room there is, pinned so a change in the method shows."""
    assert (len(main), sum(hi - lo for lo, hi, *_ in main)) == (391, 57250)
    sizes = {least: deadcode.usable(main, least) for least in (64, 256, 512, 1024)}
    assert {k: (len(v), sum(hi - lo for lo, hi in v)) for k, v in sizes.items()} == {
        64: (180, 45086), 256: (55, 28274), 512: (17, 14724), 1024: (3, 4276)}
    taken = sum(hi - lo for lo, hi in (mm.CAVE, mm.CAVE_AMUTE))
    assert sum(hi - lo for lo, hi in sizes[256]) - taken == 27518


def test_usable_runs_are_whole_functions(main, official):
    """Each starts right after a return and ends on one, and nothing at all names an address inside."""
    stock = official.section(3)
    for lo, hi in deadcode.usable(main, least=64):
        assert stock[mm.off(lo) - 2:mm.off(lo)] in (b"\x4e\x75", b"\x4e\x73")
        assert stock[mm.off(hi) - 2:mm.off(hi)] in (b"\x4e\x75", b"\x4e\x73")
        assert lo % 2 == 0 and mm.ENTRY < lo and hi <= mm.CODE_END
