"""The pad7 tool."""
import pytest

from tools import build, ele3, fw
from tools import audiomap as m


@pytest.fixture(scope="module")
def images(official_path):
    quiet = lambda s: None
    was = build.build(official_path, log=quiet, xfade=51)
    build.PAD7 = True
    try:
        new = build.build(official_path, log=quiet, xfade=51)
    finally:
        build.PAD7 = False
    return was, new


def test_section_7_is_atrigs_then_zeros_to_its_most(images):
    (_, _, was, _, _), (_, _, new, _, _) = images
    a, b = was.section(7), new.section(7)
    assert len(b) == fw.GROW[7] == 393208 and len(b) + 5 <= 393216
    assert b[:len(a)] == a and not any(b[len(a):])


def test_every_other_section_is_atrigs(images):
    (_, _, was, _, _), (_, _, new, _, _) = images
    for sid in was.ids:
        if sid != 7:
            assert new.container.by_id(sid).stored == was.container.by_id(sid).stored
            assert new.container.by_id(sid).dest == was.container.by_id(sid).dest


def test_the_container_reads_back(images):
    _, (raw, _, _, _, _) = images
    c = fw.Image(raw).container
    assert [s.id for s in c.sections] == [5, 2, 1, 3, 4, 6, 7, 8]
    assert c.by_id(8).off == ele3._align(c.by_id(7).off + c.by_id(7).size, ele3.ALIGN)


def test_the_zeros_fall_in_what_the_start_up_clears(images):
    (_, _, was, _, _), _ = images
    start, end = m.BASE + len(was.section(7)), m.BASE + fw.GROW[7]
    assert 0x4004f6e0 <= start and end <= 0x4404f980


def test_a_grown_section_3_or_a_too_long_7_is_refused(official):
    with pytest.raises(fw.GuardError):
        official.build({7: official.section(7) + bytes(fw.GROW[7] + 4 - len(official.section(7)))})
    with pytest.raises(fw.GuardError):
        official.build({3: official.section(3) + bytes(4)})
