"""The sample splitter, and its output played through the real engine."""
import os
import shutil
import wave

import numpy as np
import pytest

from emu.engine import BLOCK, Engine
from tools import audiomap as m
from tools import build_engine, split_sample


def wav_file(tmp_path, name, frames, channels=2, rate=48000, seed=9):
    rng = np.random.default_rng(seed)
    x = rng.integers(-30000, 30000, (frames, channels)).astype(np.int16)
    p = tmp_path / name
    with wave.open(str(p), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(x.astype("<i2").tobytes())
    return str(p), x


def stereo_file(tmp_path, frames=2500, rate=48000):
    return wav_file(tmp_path, "My Pad.wav", frames, rate=rate)


def sampler(official, pool, track, first, mode):
    image, syms = build_engine.patched_image(official.section(7))
    e = Engine(image, loop_entry=syms["sampler_hook"])
    e.load_pool(pool)
    for t in range(m.N_VOICES):
        e.set_machine(t, 44)
        e.set_note(t, 60)
        for slot, v in ((18, 64), (19, 127), (20, 0), (21, 127), (22, 0), (23, 0), (25, 127)):
            e.set_slot(t, slot, v)
    e.set_slot(track, 19, 64 + (first // 2 if mode & 1 else first))     # stereo: the knob counts stereo samples
    e.set_slot(track, 23, mode)
    return e


def test_pieces_are_mono_16_bit_48k_and_rejoin_exactly(tmp_path):
    path, x = stereo_file(tmp_path)
    pieces = split_sample.split(split_sample.load(path), chunk_seconds=0.02)       # 960 frames a piece
    paths = split_sample.write(pieces, "pad", str(tmp_path / "out"))
    names = [os.path.basename(p) for p in paths]
    assert names == ["pad_01L.wav", "pad_01R.wav", "pad_02L.wav", "pad_02R.wav", "pad_03L.wav", "pad_03R.wav"]
    assert names == sorted(names)                                 # alphabetical order is slot order
    got = []
    for p in paths:
        with wave.open(p, "rb") as w:
            assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 48000)
            got.append(np.frombuffer(w.readframes(w.getnframes()), dtype="<i2"))
    assert np.array_equal(np.concatenate(got[0::2]), x[:, 0])
    assert np.array_equal(np.concatenate(got[1::2]), x[:, 1])
    assert max(len(g) for g in got) <= 960 and len(got[4]) <= len(got[0])


def test_mono_mixdown_and_limits(tmp_path):
    path, x = stereo_file(tmp_path)
    pieces = split_sample.split(split_sample.load(path), mono=True)
    assert [s for s, _ in pieces] == [""] and len(pieces[0][1]) == len(x)
    with pytest.raises(ValueError, match="at most"):
        split_sample.split(x, chunk_seconds=6)
    with pytest.raises(ValueError, match="slots"):
        split_sample.split(np.zeros((48000 * 4 * 40, 2), dtype=np.int16), chunk_seconds=4)
    assert split_sample.mode_hint(False) == (0, -64)
    assert split_sample.mode_hint(True) == (1, -63)
    assert split_sample.mode_hint(True, chain=True) == (5, -59)


def test_a_sample_of_5_seconds_or_less_is_one_slot_per_channel(tmp_path):
    """The plain case: nothing is cut. Stereo is name_L and name_R, mono is name."""
    five = int(split_sample.MAX_SECONDS * split_sample.RATE)
    a, xa = wav_file(tmp_path, "pad.wav", five)
    b, xb = wav_file(tmp_path, "hit.wav", 900, channels=1, seed=3)
    c, xc = wav_file(tmp_path, "over.wav", five + 1, seed=4)
    jobs = split_sample.convert([a, b, c])
    assert [(stem, stereo, [s for s, _ in pieces]) for stem, stereo, pieces in jobs] == [
        ("pad", True, ["L", "R"]), ("hit", False, [""]), ("over", True, ["01L", "01R", "02L", "02R"])]
    assert np.array_equal(jobs[0][2][0][1], xa[:, 0]) and np.array_equal(jobs[0][2][1][1], xa[:, 1])
    assert np.array_equal(jobs[1][2][0][1], xb[:, 0])
    out = tmp_path / "out"
    names = [os.path.basename(p) for stem, _, pieces in jobs[:2] for p in split_sample.write(pieces, stem, str(out))]
    assert names == ["pad_L.wav", "pad_R.wav", "hit.wav"]
    # a stereo sample starts on an odd slot: slot 6 is left empty after the mono one. SMPL is the last number.
    assert split_sample.layout(jobs, first=3) == [
        (3, 2, "pad", 5.0, 1, 2), (5, 1, "hit", 900 / 48000, 0, 5), (7, 2, "over 1/2", 120001 / 48000, 1, 4),
        (9, 2, "over 2/2", 2.5, 1, 5)]
    assert [(slot, stem) for slot, stem, _, _ in split_sample.place(jobs, first=3)] == [(3, "pad"), (5, "hit"), (7, "over")]
    assert [slot for slot, _, _, _ in split_sample.place(jobs[:1], first=4)] == [5]       # an even first slot too
    text = split_sample.sheet(split_sample.layout(jobs, first=3))
    assert "6 slots used, 3 to 10." not in text and "7 slots used, 3 to 10." in text and "1 left empty" in text
    numbered = [os.path.basename(p) for p in split_sample.write(jobs[2][2], "over", str(out), slot=7)]
    assert numbered == ["07_over_01L.wav", "08_over_01R.wav", "09_over_02L.wav", "10_over_02R.wav"]


def test_a_folder_is_a_batch_and_every_name_starts_with_its_slot(tmp_path, capsys):
    src = tmp_path / "set"
    (src / "sub").mkdir(parents=True)
    for k in range(2):
        wav_file(src, "s%d.wav" % k, 1000 + k, seed=k)
    wav_file(src / "sub", "s0.wav", 700, channels=1, seed=5)             # the same name again, in a subfolder
    (src / "notes.txt").write_text("not audio")
    files = split_sample.inputs([str(src)])
    assert [os.path.relpath(f, src) for f in files] == ["s0.wav", "s1.wav", os.path.join("sub", "s0.wav")]

    out = tmp_path / "out"

    def wavs():
        return sorted(f for f in os.listdir(out) if f.endswith(".wav"))
    split_sample.main([str(src), "--out", str(out), "--first", "9"])
    assert wavs() == ["09_s0_L.wav", "10_s0_R.wav", "11_s1_L.wav", "12_s1_R.wav", "13_s0.wav"]
    text = (tmp_path / "out_slots.txt").read_text()
    assert text in capsys.readouterr().out
    assert " 9-10  s0" in text and "13     s0" in text and "5 slots used, 9 to 13." in text

    split_sample.main([str(src / "sub"), "--out", str(out)])             # a second run replaces the first
    assert wavs() == ["01_s0.wav"]
    mine = tmp_path / "mine"                                             # a folder it did not make is left alone
    mine.mkdir()
    (mine / "keep.wav").write_bytes(b"x")
    with pytest.raises(SystemExit, match="not made by this tool"):
        split_sample.main([str(src), "--out", str(mine)])
    assert os.listdir(mine) == ["keep.wav"]


def test_for_the_pack_image_mono_samples_go_in_the_single_slots_from_64_down(tmp_path, capsys):
    """The on request










    #



















    For the stops image, which tells a single slot's mono sample from a stereo place's by its length: a mono file
    comes out an odd number of frames and a stereo one an even number on both sides. Its last frame is left out where
    it has to be, and nothing else of it changes. Without --pack a file is every frame it was."""
    src = tmp_path / "set"
    src.mkdir()
    _, two = wav_file(src, "a_pad.wav", stereo_frames, seed=1)
    _, one = wav_file(src, "b_hit.wav", mono_frames, channels=1, seed=2)
    for flags, want_mono, want_stereo in (([], mono_frames, stereo_frames),
                                          (["--pack"], mono_frames - (mono_frames % 2 == 0), stereo_frames - stereo_frames % 2)):
        out = tmp_path / ("out" + "".join(flags))
        split_sample.main([str(src), "--out", str(out)] + flags)
        hit = frames_of(out / ("64_b_hit.wav" if flags else "03_b_hit.wav"))
        left, right = frames_of(out / "01_a_pad_L.wav"), frames_of(out / "02_a_pad_R.wav")
        assert (len(hit), len(left), len(right)) == (want_mono, want_stereo, want_stereo)
        assert np.array_equal(hit, one[:want_mono, 0]) and np.array_equal(left, two[:want_stereo, 0]) and np.array_equal(right, two[:want_stereo, 1])
        if flags:
            assert len(hit) % 2 == 1 and len(left) % 2 == 0 and mono_frames - len(hit) <= 1 and stereo_frames - len(left) <= 1
    assert "an odd number of frames" in (tmp_path / "out--pack_slots.txt").read_text()


def test_with_pack_every_piece_of_a_long_file_is_its_kind(tmp_path):
    """A file cut into pieces: each piece of a mono one odd, each pair of a stereo one even."""
    src = tmp_path / "set"
    src.mkdir()
    wav_file(src, "a_long.wav", 3 * 960 + 100, seed=1)
    wav_file(src, "b_line.wav", 2 * 960 + 250, channels=1, seed=2)
    jobs = split_sample.convert(split_sample.inputs([str(src)]), chunk_seconds=0.02, pack=True)
    for stem, stereo, pieces in jobs:
        assert len(pieces) == (8 if stereo else 3)
        assert all(len(data) % 2 == (0 if stereo else 1) for _, data in pieces)
    assert [(slot, stem) for slot, stem, _, _ in split_sample.place(jobs, pack=True)] == [(1, "a_long"), (62, "b_line")]


def test_a_pack_set_has_to_fit_too(tmp_path):
    mono = [wav_file(tmp_path, "m%02d.wav" % k, 300, channels=1, seed=k)[0] for k in range(33)]
    two = [wav_file(tmp_path, "s%02d.wav" % k, 300, seed=k)[0] for k in range(25)]
    assert len(split_sample.convert(mono[:32], pack=True)) == 32             # 33 to 64
    with pytest.raises(ValueError, match="33 mono samples, and the pack image plays 32"):
        split_sample.convert(mono, pack=True)
    assert len(split_sample.convert(two[:24] + mono[:16], pack=True)) == 40  # 48 slots of stereo and 16 single ones: all 64
    with pytest.raises(ValueError, match="reach slot 50 and the mono ones come down to slot 49: 2 slots too many"):
        split_sample.convert(two + mono[:16], pack=True)
    assert len(split_sample.convert(two[:16] + mono[:32], pack=True)) == 48  # 16 and 32


def test_a_set_has_to_fit_the_slots_that_are_left(tmp_path):
    files = [wav_file(tmp_path, "n%d.wav" % k, 500, seed=k)[0] for k in range(33)]
    assert len(split_sample.convert(files[:32])) == 32                   # 32 stereo samples: all 64 slots
    with pytest.raises(ValueError, match="room for 32 stereo"):
        split_sample.convert(files)
    assert len(split_sample.convert(files[:2], first=61)) == 2
    with pytest.raises(ValueError, match="4 from slot 61 on: room for 2 stereo"):
        split_sample.convert(files[:3], first=61)
    with pytest.raises(ValueError, match="first slot"):
        split_sample.convert(files[:1], first=0)
    with pytest.raises(SystemExit, match="slots"):                       # a plain message, no traceback
        split_sample.main([wav_file(tmp_path, "long.wav", 48000 * 5 * 33, seed=1)[0], "--out", str(tmp_path / "x")])
    assert not (tmp_path / "x").exists()


@pytest.mark.skipif(not shutil.which("afconvert"), reason="no afconvert")
def test_other_sample_rates_are_converted(tmp_path):
    path, x = stereo_file(tmp_path, frames=4410, rate=44100)
    y = split_sample.load(path)
    assert y.shape[1] == 2 and abs(len(y) - 4800) <= 2


@pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")
def test_split_file_plays_back_as_the_original_in_stereo(tmp_path, official):
    """File -> pieces -> slots -> the engine, stereo and chained: out comes the original."""
    path, x = stereo_file(tmp_path)
    pieces = split_sample.split(split_sample.load(path), chunk_seconds=0.02)
    first = 20
    mode, shown = split_sample.mode_hint(True, chain=True)
    e = sampler(official, {first + k: data for k, (_, data) in enumerate(pieces)}, 2, first, mode)
    out = e.render(2500 // BLOCK + 3, trig=1 << 2)[:, BLOCK:]
    assert np.array_equal(out[2][:2500], x[:, 0].astype(np.int64) << 15)        # left, on the track itself
    assert np.array_equal(out[3][:2500], x[:, 1].astype(np.int64) << 15)        # right, on the next track
    assert not out[2][2500:].any() and not out[3][2500:].any()


@pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")
def test_a_full_5_second_stereo_sample_at_its_real_size(tmp_path, official):
    """240,000 frames a side, MODE 1, in the last two slots: every frame of both channels, then silence.
    A second pair before it must not leak in (no chain)."""
    five = int(split_sample.MAX_SECONDS * split_sample.RATE)
    path, x = wav_file(tmp_path, "pad.wav", five)
    other, _ = wav_file(tmp_path, "other.wav", five, seed=5)
    jobs = split_sample.convert([other, path])
    data = [d for _, _, pieces in jobs for _, d in pieces]
    assert [len(d) for d in data] == [five] * 4
    mode, shown = split_sample.mode_hint(True)
    e = sampler(official, {60 + k: d for k, d in enumerate(data)}, 6, 62, mode)
    out = e.render(five // BLOCK + 4, trig=1 << 6)[:, BLOCK:]
    assert np.array_equal(out[6][:five], x[:, 0].astype(np.int64) << 15)
    assert np.array_equal(out[7][:five], x[:, 1].astype(np.int64) << 15)
    assert not out[6][five:].any() and not out[7][five:].any()
    e = sampler(official, {60 + k: d for k, d in enumerate(data)}, 0, 60, mode)     # the first pair stops at its end
    e.set_slot(0, 20, 126)                                                          # start 126/128 of the way in
    out = e.render(130, trig=1)[:, BLOCK:]
    tail = five - five * 126 // 128
    assert np.array_equal(out[0][:tail], data[0][-tail:].astype(np.int64) << 15)
    assert np.array_equal(out[1][:tail], data[1][-tail:].astype(np.int64) << 15)
    assert not out[0][tail:].any() and not out[1][tail:].any()


def test_big_image_takes_ten_seconds_a_slot_and_knows_what_the_unit_loads(tmp_path):
    ten = int(split_sample.BIG_SECONDS * split_sample.RATE)
    path, x = wav_file(tmp_path, "long.wav", ten)
    assert [len(d) for _, d in split_sample.split(split_sample.load(path))] == [ten // 2] * 4          # stock: two pieces a side
    pieces = split_sample.split(split_sample.load(path), limit=split_sample.BIG_SECONDS)
    assert [s for s, _ in pieces] == ["L", "R"] and [len(d) for _, d in pieces] == [ten, ten]
    assert np.array_equal(pieces[0][1], x[:, 0]) and np.array_equal(pieces[1][1], x[:, 1])
    with pytest.raises(ValueError, match="at most 10"):
        split_sample.split(x, chunk_seconds=11, limit=split_sample.BIG_SECONDS)
    # 17 stereo samples of 10 s fit the boot pool, 18 do not
    files = [wav_file(tmp_path, "n%d.wav" % k, ten, seed=k)[0] for k in range(18)]
    assert len(split_sample.convert(files[:17], limit=split_sample.BIG_SECONDS)) == 17
    with pytest.raises(ValueError, match="the unit loads 5:49 at boot"):
        split_sample.convert(files, limit=split_sample.BIG_SECONDS)
    text = split_sample.sheet(split_sample.layout(split_sample.convert(files[:2], limit=split_sample.BIG_SECONDS)), big=True)
    assert "Transfer10s.app" in text and "5:49 of mono" in text and "2:54 of stereo" in text
    assert "Transfer10s" not in split_sample.sheet(split_sample.layout(split_sample.convert(files[:2])))


def test_double_image_loads_twice_as_much(tmp_path):
    ten = int(split_sample.BIG_SECONDS * split_sample.RATE)
    files = [wav_file(tmp_path, "n%d.wav" % k, ten, seed=k)[0] for k in range(32)]
    with pytest.raises(ValueError, match="the unit loads 5:49 at boot"):
        split_sample.convert(files, limit=split_sample.BIG_SECONDS)
    jobs = split_sample.convert(files, limit=split_sample.BIG_SECONDS, pool=split_sample.DOUBLE_POOL_FRAMES)
    assert len(jobs) == 32                                  # 32 stereo samples of 10 s: every slot
    text = split_sample.sheet(split_sample.layout(jobs), big=True, pool=split_sample.DOUBLE_POOL_FRAMES)
    assert "11:38 of mono" in text and "5:49 of stereo" in text
    # the number is what the main CPU's code allows: two halves of 16382 chunks, less a count for each slot
    assert split_sample.DOUBLE_POOL_FRAMES == (2 * 16382 * 2048 - 4 * 64) // 2
