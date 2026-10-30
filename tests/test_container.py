"""Phase 1: transport, ELE3 container, round trip, guards. Needs the official file."""
import shutil
import subprocess

import pytest

from tools import ele3, fw, syx

ROOT_SRC = "third_party/elektron-firmware-tool"


def _flip(data, off):
    b = bytearray(data)
    b[off] ^= 0x01
    return bytes(b)


def _diff(a, b):
    return [i for i in range(len(a)) if a[i] != b[i]]


def test_pinned_layout(official):
    assert official.version == "1.42"
    assert official.transport == syx.Transport(product=0x16, base=0x11, start_seq=242, count=20094)
    assert official.ids == [5, 2, 1, 3, 4, 6, 7, 8]
    c = official.container
    assert (c.model, c.version, len(c.blob)) == ("J0097", "1.42", 2029392)
    assert [s.id for s in c.sections if s.compressed] == [2, 1, 3, 8]
    assert c.by_id(3).dest == 0x40000400
    assert len(official.section(3)) == 3442576
    assert len(official.section(7)) == 383760
    # audio image starts with its entry point
    assert official.section(7)[:4] == bytes.fromhex(fw.sx("354f240bf90bbdbd"))


def test_protected_sections_are_what_we_think(official):
    boot = official.section(2)
    for s in (b"BOOTSTRAP UPGRADE", b"OS UPGRADE", b"STARTUP MENU"):
        assert s in boot
    upd = official.container.by_id(4)
    assert not upd.compressed and upd.dest == 0x80000400 and upd.size == 32776


def test_round_trip_is_byte_identical(official):
    assert official.build() == official.raw


def test_unchanged_sections_repack_identical(official):
    same = {sid: official.section(sid) for sid in fw.PATCHABLE}
    assert official.build(same) == official.raw


def test_codec_reproduces_every_compressed_section(official):
    for s in official.container.sections:
        if s.compressed:
            data, ops = ele3.depack(s.stored)
            assert ele3.repack(data, ops, bytearray(len(data))) == s.stored, s.id


@pytest.mark.parametrize("sid,off", [(7, 0x1234), (7, 383759), (3, 0x200000), (3, 0)])
def test_one_byte_change(official, sid, off):
    new = _flip(official.section(sid), off)
    raw = official.build({sid: new})
    assert raw != official.raw
    built = fw.verify(official, raw, {sid: [(off, off + 1)]})
    assert _diff(official.section(sid), built.section(sid)) == [off]
    for other in official.ids:
        if other != sid:
            assert built.section(other) == official.section(other)
            assert built.container.by_id(other).stored == official.container.by_id(other).stored


def test_patch_asserts_stock_bytes(official):
    off = 0x1234
    stock = official.section(7)[off:off + 2]
    new = bytes(b ^ 0xFF for b in stock)
    secs, regions = fw.apply(official, [fw.Patch(7, off, stock, new)])
    assert regions == {7: [(off, off + 2)]}
    fw.verify(official, official.build(secs), regions)
    with pytest.raises(fw.GuardError, match="stock bytes"):
        fw.apply(official, [fw.Patch(7, off, new, stock)])
    with pytest.raises(fw.GuardError, match="overlaps"):
        fw.apply(official, [fw.Patch(7, off, stock, new), fw.Patch(7, off + 1, stock[1:], new[1:])])


@pytest.mark.parametrize("sid", [2, 4])
def test_bootstrap_and_updater_hard_fail(official, sid):
    data = official.section(sid)
    with pytest.raises(fw.GuardError, match="refusing"):
        official.build({sid: data})
    with pytest.raises(fw.GuardError, match="targets section"):
        fw.apply(official, [fw.Patch(sid, 0, data[:1], b"\x00")])


@pytest.mark.parametrize("sid", [1, 5, 6, 8])
def test_other_sections_not_patchable(official, sid):
    with pytest.raises(fw.GuardError, match="not patchable"):
        official.build({sid: official.section(sid)})


def test_verify_rejects_undeclared_change(official):
    raw = official.build({7: _flip(official.section(7), 0x1234)})
    with pytest.raises(fw.GuardError, match="no region"):
        fw.verify(official, raw, {})
    with pytest.raises(fw.GuardError, match="outside declared"):
        fw.verify(official, raw, {7: [(0x2000, 0x2010)]})


def test_verify_rejects_touched_bootstrap(official):
    # Build around the guard on purpose, then check verify() still catches it.
    s = official.container.by_id(2)
    data, ops = ele3.depack(s.stored)
    new = _flip(data, 100)
    dirty = bytearray(len(data))
    dirty[100] = 1
    blob = ele3.build(official.container, {2: ele3.repack(new, ops, dirty)})
    raw = syx.encode(ele3.to_stream(blob, syx.PLAIN_PER_MSG), official.transport)
    with pytest.raises(fw.GuardError, match="bootstrap"):
        fw.verify(official, raw, {2: [(100, 101)]})


def test_load_refuses_unpinned_file(official, tmp_path):
    p = tmp_path / "modded.syx"
    p.write_bytes(official.build({7: _flip(official.section(7), 0x1234)}))
    with pytest.raises(fw.GuardError, match="unknown file hash"):
        fw.load(str(p))


def test_damaged_packet_is_rejected(official):
    raw = bytearray(official.raw)
    raw[16 + 128 * 500 + 40] ^= 0x01
    with pytest.raises(ValueError, match="packet 500: checksum"):
        syx.decode(bytes(raw))


def test_damaged_content_is_rejected(official):
    stream, t = syx.decode(official.raw)
    bad = bytearray(stream)
    bad[5000] ^= 0x01
    with pytest.raises(ValueError, match="content checksum"):
        ele3.parse(bytes(bad))


@pytest.fixture(scope="module")
def eft(tmp_path_factory):
    """elektron-firmware-tool (MIT, C), built as an independent cross-check."""
    cc = shutil.which("cc")
    if not cc:
        pytest.skip("no host C compiler")
    exe = tmp_path_factory.mktemp("eft") / "eft"
    import glob
    subprocess.run([cc, "-O2", "-o", str(exe)] + sorted(glob.glob(ROOT_SRC + "/*.c")),
                   check=True, capture_output=True)
    return str(exe)


def _eft_sections(eft, syx_path, outdir):
    subprocess.run([eft, "-i", str(syx_path), "-o", str(outdir)], check=True, capture_output=True)
    out = {}
    for f in outdir.iterdir():
        out[int(f.name.split("_")[1])] = f.read_bytes()
    return out


def test_cross_check_unpack_and_repack(official, official_path, eft, tmp_path):
    secs = _eft_sections(eft, official_path, tmp_path / "secs")
    assert sorted(secs) == sorted(official.ids)
    for sid, data in secs.items():
        assert data == official.section(sid), sid
    rep = tmp_path / "repack.syx"
    subprocess.run([eft, "-i", official_path, "-r", "-o", str(rep)], check=True, capture_output=True)
    assert rep.read_bytes() == official.raw


@pytest.mark.parametrize("sid,off", [(7, 0x1234), (3, 0x200000)])
def test_cross_check_reads_our_build(official, eft, tmp_path, sid, off):
    new = _flip(official.section(sid), off)
    p = tmp_path / "built.syx"
    p.write_bytes(official.build({sid: new}))
    report = subprocess.run([eft, "-i", str(p), "-v"], check=True, capture_output=True, text=True).stdout
    assert "20094/20094  [ok]" in report and "MISMATCH" not in report
    assert report.count("[ok]") == 7  # packets, packet count, content checksum, 4 stream sums
    secs = _eft_sections(eft, p, tmp_path / "secs")
    assert secs[sid] == new
    for other in official.ids:
        if other != sid:
            assert secs[other] == official.section(other)
