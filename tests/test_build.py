"""Phase 6: the built image, checked as a file."""
import glob
import shutil
import subprocess

import numpy as np
import pytest

from emu import sampler_ref as ref
from emu.engine import BLOCK, Engine
from tools import audiomap as m
from tools import build, build_engine, fw

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")


@pytest.fixture(scope="module")
def result(official_path):
    return build.build(official_path, log=lambda s: None)


def test_only_section_7_changes_and_only_in_declared_regions(result, official):
    raw, _, built, regions, _ = result
    assert sorted(regions) == [7]
    for sid in official.ids:
        if sid != 7:
            assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
    declared = set()
    for start, end in regions[7]:
        declared |= set(range(start, end))
    a, b = official.section(7), built.section(7)
    changed = {i for i in range(len(a)) if a[i] != b[i]}
    assert changed and changed <= declared
    assert len(regions[7]) == 5  # two caves, three pointers
    assert sum(e - s for s, e in regions[7]) == 1326 + 1292 + 12


def test_bootstrap_and_updater_are_untouched(result, official):
    _, _, built, _, _ = result
    for sid in (2, 4):
        assert built.container.by_id(sid).stored == official.container.by_id(sid).stored
        assert fw.sha256(built.section(sid)) == fw.SECTION_SHA256[official.version][sid]


def test_file_is_well_formed_and_the_same_shape(result, official):
    raw, _, built, _, _ = result
    assert len(raw) == len(official.raw)
    assert built.transport == official.transport  # same packet count: section 7 is stored raw
    assert built.container.blob[:0x20 + 16 * 8] == official.container.blob[:0x20 + 16 * 8]  # header and table
    assert fw.sha256(raw) != fw.sha256(official.raw)
    again = fw.Image(raw)  # decodes from scratch, all checksums verified
    assert again.section(7) == built.section(7)


def test_build_is_reproducible(result, official_path):
    assert build.build(official_path, log=lambda s: None)[0] == result[0]


def test_built_file_is_not_accepted_as_official(result, tmp_path):
    p = tmp_path / "built.syx"
    p.write_bytes(result[0])
    with pytest.raises(fw.GuardError, match="unknown file hash"):
        fw.load(str(p))


def test_a_patch_with_wrong_stock_bytes_stops_the_build(official, monkeypatch):
    real = build_engine.patches

    def bad(image):
        ps, syms = real(image)
        ps[0] = fw.Patch(7, ps[0].offset, b"\x00" * len(ps[0].stock), ps[0].new, ps[0].note)
        return ps, syms
    monkeypatch.setattr(build_engine, "patches", bad)
    with pytest.raises(fw.GuardError, match="stock bytes"):
        build.build(glob.glob("firmware/**/*.syx", recursive=True)[0], log=lambda s: None)


def test_the_built_file_itself_plays_like_the_reference(result):
    """Take section 7 back out of the built file and run it."""
    raw, _, built, _, syms = result
    image = built.section(7)
    rng = np.random.default_rng(5)
    pool = {3: rng.integers(-32768, 32768, 900).astype(np.int16)}
    e = Engine(image, loop_entry=syms["sampler_hook"])
    e.load_pool(pool)
    for t in range(m.N_VOICES):
        e.set_machine(t, 44)
        e.set_note(t, 65)
        for slot, v in ((18, 64), (19, 64 + 3), (20, 10), (21, 90), (22, 2), (23, 0), (25, 127)):
            e.set_slot(t, slot, v if t == 0 else (127 if slot == 19 else v))
    x = e.render(121, trig=1)[0][BLOCK:]
    p = ref.Player(pool)
    p.inc = e.player(0, 0)["inc"]
    p.note_on(sample=67, start=10, length=90, loop=2, mode=0)
    want = []
    for _ in range(120):
        want += ref.tail(p.block()[0])
    assert np.array_equal(x, np.array(want)) and x.any()


def test_independent_tool_accepts_the_built_file(result, tmp_path):
    cc = shutil.which("cc")
    if not cc:
        pytest.skip("no host C compiler")
    exe = tmp_path / "eft"
    subprocess.run([cc, "-O2", "-o", str(exe)] + sorted(glob.glob("third_party/elektron-firmware-tool/*.c")),
                   check=True, capture_output=True)
    p = tmp_path / "built.syx"
    p.write_bytes(result[0])
    report = subprocess.run([str(exe), "-i", str(p), "-v"], check=True, capture_output=True, text=True).stdout
    assert "MISMATCH" not in report and "20094/20094  [ok]" in report
    subprocess.run([str(exe), "-i", str(p), "-o", str(tmp_path / "secs")], check=True, capture_output=True)
    got = {int(f.name.split("_")[1]): f.read_bytes() for f in (tmp_path / "secs").iterdir()}
    assert got[7] == result[2].section(7)
    for sid in (1, 2, 3, 4, 5, 6, 8):
        assert fw.sha256(got[sid]) == fw.SECTION_SHA256["1.42"][sid]
