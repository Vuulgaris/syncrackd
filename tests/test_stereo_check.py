"""tools/stereo_check.py."""
import os
import shutil
import wave

import numpy as np
import pytest

from tools import audiomap as m
from tools import build_engine, stereo_check as sc

RATE = sc.RATE
ALL = range(sc.N)


def recorded(left, right, gain=0.2, lead=7000, tail=9000, seed=1):
    """As a take of the main mix holds it: quieter, silence before and after, 16 bits with dither."""
    rng = np.random.default_rng(seed)
    out = []
    for x in (left, right):
        x = np.concatenate([np.zeros(lead), np.asarray(x, dtype=float) * gain, np.zeros(tail)])
        x = x + rng.random(len(x)) - rng.random(len(x))
        out.append(np.clip(np.round(x), -32768, 32767))
    return out


def mix(ks=ALL, change=None):
    """The samples ks playing together. change: {k: f(left, right) -> (left, right)}, what the unit got wrong for one.
    """
    left, right = np.zeros(4 * RATE), np.zeros(4 * RATE)
    for k in ks:
        l, r = (x.astype(float) for x in sc.sample(k))
        if change and k in change:
            l, r = change[k](l, r)
        left, right = left + l, right + r
    return left, right


@pytest.mark.parametrize("k", ALL)
def test_a_sample_is_a_low_tone_left_a_high_tone_right_then_hiss_that_is_the_same_on_both(k):
    left, right = sc.sample(k)
    assert len(left) == len(right) == 4 * RATE and left.dtype == np.int16
    assert max(np.abs(left).max(), np.abs(right).max()) <= 1.5 * sc.LEVEL + 1  # far from full scale
    a, b = RATE // 4, 7 * RATE // 4  # inside the tones
    for x, own, other in ((left, sc.F_LEFT[k], sc.F_RIGHT[k]), (right, sc.F_RIGHT[k], sc.F_LEFT[k])):
        (got, leak), rest = sc._fit(x[a:b].astype(float), [own, other])
        assert abs(got - sc.LEVEL) < 2 and leak < 0.1 and np.abs(rest).max() < 1.5  # one tone a side, and nothing else
    h = 2 * RATE
    at = int((sc.HISS_AT + k * sc.HISS_EVERY) * RATE)
    assert np.array_equal(left[h:], right[h:]) and left[at:at + int(sc.HISS_LONG * RATE)].any()
    quiet = np.r_[left[h:at], left[at + int(sc.HISS_LONG * RATE):]]
    assert not quiet.any()  # its own moment, and silence around it


def test_the_sixteen_tones_and_the_eight_bursts_keep_out_of_each_others_way():
    tones = sc.F_LEFT + sc.F_RIGHT
    assert len(set(tones)) == 16 and max(sc.F_LEFT) < min(sc.F_RIGHT)  # every left tone is under every right one
    for f in tones:
        for g in tones:
            assert f == g or abs(f - g) >= 45
            assert all(abs(h * f - g) >= 25 for h in range(2, 8))  # no harmonic of one lands on another
    assert sc.HISS_EVERY - sc.HISS_LONG > 0.049 and sc.HISS_AT + 7 * sc.HISS_EVERY + sc.HISS_LONG < sc.SECONDS  # 50 ms between bursts


def test_the_files_are_what_transfer_takes(tmp_path):
    paths, sheet = sc.write_samples(str(tmp_path))
    names = [os.path.basename(p) for p in paths]
    assert names[:2] == ["49_STCHECK1_L.wav", "50_STCHECK1_R.wav"] and names[-2:] == ["63_STCHECK8_L.wav", "64_STCHECK8_R.wav"] and len(names) == 16
    for k in ALL:
        for p, want in zip(paths[2 * k:2 * k + 2], sc.sample(k)):
            with wave.open(p, "rb") as w:
                assert (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()) == (1, 2, RATE, 4 * RATE)
                assert np.array_equal(np.frombuffer(w.readframes(4 * RATE), dtype="<i2"), want)
    text = open(sheet).read()
    assert "track 1   SMPL 25   slots 49 and 50" in text and "track 8   SMPL 32   slots 63 and 64" in text
    again, _ = sc.write_samples(str(tmp_path), first=1)  # another run replaces the files of the last
    assert sorted(f for f in os.listdir(tmp_path) if f.endswith(".wav")) == sorted(os.path.basename(p) for p in again)
    assert os.path.basename(again[0]) == "01_STCHECK1_L.wav" and "track 8   SMPL  8   slots 15 and 16" in open(sheet).read()
    for bad in (2, 0, 51, 63):
        with pytest.raises(SystemExit):
            sc.write_samples(str(tmp_path), first=bad)
    assert sc.read(again[:2])[0].shape == (4 * RATE,)


def test_all_eight_at_once_says_stereo_for_every_one():
    verdict, lines = sc.check(*recorded(*mix()))
    assert verdict == "stereo", lines
    assert lines[-1].startswith("STEREO WORKS on all eight samples")
    for k in ALL:
        assert lines[k].startswith("Sample %d: %d Hz on the left, %d Hz on the right, each on its own side" % (k + 1, sc.F_LEFT[k], sc.F_RIGHT[k]))
        assert "in step (0 frames" in lines[k]


@pytest.mark.parametrize("ks", [[0], [7], range(7), range(1, 8), [2, 5]])
def test_any_of_them_alone_or_seven_while_the_eighth_records(ks):
    verdict, lines = sc.check(*recorded(*mix(ks)))
    assert verdict == "stereo", lines
    heard = [int(s.split(":")[0].split()[1]) for s in lines if s.startswith("Sample ")]
    assert heard == [k + 1 for k in ks] and any(s.startswith("Not in the recording") for s in lines)


def test_the_left_on_both_sides_says_the_right_channels_did_not_cross():
    """What the main CPU does when the window's long does not answer: every track its left twice."""
    left, _ = mix()
    verdict, lines = sc.check(*recorded(left, left))
    assert verdict == "mono" and lines[-1].startswith("NOT STEREO on all eight samples")
    assert sum("IS ON BOTH SIDES" in s for s in lines) == 8


def test_one_track_whose_right_channel_did_not_cross_is_named_among_the_others():
    verdict, lines = sc.check(*recorded(*mix(change={4: lambda l, r: (l, l)})))
    assert verdict == "fault" and "Sample 5: ITS LEFT TONE (480 Hz) IS ON BOTH SIDES" in " ".join(lines)
    assert sum("each on its own side" in s for s in lines) == 7


@pytest.mark.parametrize("k, shift, word", [(0, 32, "behind"), (5, -32, "ahead of"), (7, 64, "behind")])
def test_a_right_side_a_block_out_of_step_is_named_and_only_that_track(k, shift, word):
    """Its tones are as clean as ever: only its hiss, which is on both sides, shows it."""
    verdict, lines = sc.check(*recorded(*mix(change={k: lambda l, r: (l, np.roll(r, shift))})))
    faults = [s for s in lines if "frames %s its left" % word in s]
    assert verdict == "fault" and len(faults) == 1 and faults[0].startswith("Sample %d: its right side is %d frames" % (k + 1, abs(shift)))
    assert sum("in step (0 frames" in s for s in lines) == 7


def test_a_block_out_of_place_now_and_then_is_a_click_and_is_counted():
    """A block read while it was being written: here every 700th block of the right side is the one after it."""
    left, right = mix()
    torn = right.copy()
    for at in range(700 * 32, len(torn) - 64, 700 * 32):
        torn[at:at + 32] = right[at + 32:at + 64]
    verdict, lines = sc.check(*recorded(left, torn))
    assert verdict == "fault" and any(s.startswith("Clicks on the right side: 3 ") for s in lines), lines
    assert not any("on the left side" in s for s in lines)


def test_noise_and_distortion_on_one_side_are_named():
    left, right = mix()
    verdict, lines = sc.check(*recorded(left, right + np.random.default_rng(5).normal(0, 1500, len(right))))
    assert verdict == "fault" and any(s.startswith("Noise on the right side") for s in lines)
    bent = mix(change={3: lambda l, r: (l, 6000 * np.tanh(r / 6000))})  # one track's right channel pushed into a curve
    verdict, lines = sc.check(*recorded(*bent))
    assert verdict == "fault" and any(s.startswith("Distortion on the right side") for s in lines)
    assert not any("on the left side" in s for s in lines)


def test_swapped_sides_a_silent_side_and_no_samples_at_all():
    left, right = mix()
    verdict, lines = sc.check(*recorded(right, left))
    assert verdict == "fault" and sum("sides are swapped" in s for s in lines) == 8
    verdict, lines = sc.check(*recorded(left, np.zeros(len(left))))
    assert verdict == "fault"
    noise = np.random.default_rng(3).integers(-3000, 3000, 3 * RATE)
    assert sc.check(noise, noise)[0] == "fault" and sc.check(np.zeros(2 * RATE), np.zeros(2 * RATE))[0] == "fault"
    assert sc.check(np.zeros(100), np.zeros(100))[0] == "fault"


def test_a_recording_of_a_loop_that_starts_anywhere():
    left, right = (np.tile(x, 4) for x in mix())
    for start in (int(1.3 * RATE), int(2.9 * RATE), int(3.9 * RATE)):
        got = recorded(left[start:start + 9 * RATE], right[start:start + 9 * RATE], lead=0, tail=0)
        verdict, lines = sc.check(*got)
        assert verdict == "stereo" and lines[-1].startswith("STEREO WORKS on all eight"), (start, lines)


@pytest.mark.parametrize("speed", [0.7579, 1.4983])
def test_it_goes_by_the_recordings_own_pitch(speed):
    """TUNE or the note moved on all of them together: the tones are elsewhere and still the same apart."""
    def at(x):
        return np.interp(np.arange(0, len(x) - 1, speed), np.arange(len(x)), x)
    left, right = mix()
    verdict, lines = sc.check(*recorded(at(left), at(right)))
    assert verdict == "stereo" and lines[0] == "The recording plays the samples at %.3f of their own pitch." % speed, lines


def test_without_the_hiss_the_timing_is_not_called_good():
    left, right = mix()
    verdict, lines = sc.check(*recorded(left[:2 * RATE], right[:2 * RATE]))
    assert verdict == "fault" and sum("no hiss after its tones" in s for s in lines) == 8


def test_the_folder_a_recording_is_dropped_in(tmp_path):
    paths, _ = sc.write_samples(str(tmp_path), first=1)
    with pytest.raises(SystemExit):
        sc.find(str(tmp_path))  # sixteen files are not one recording
    for p in paths[2:]:
        os.remove(p)
    assert sc.find(str(tmp_path)) == paths[:2]


@pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")
def test_the_built_engines_own_voice_playing_one(official):
    """The stereo image's sampler playing the first sample from slots 1 and 2 on the last track: the left out of the
    track's buffer, the right out of where it waits for the stages. Cut to 16 bits as a take is.
    """
    from test_pagerec import HookEngine
    image, syms = build_engine.patched_image(official.section(7), stereo=True)
    e = HookEngine(image, loop_entry=syms["sampler_hook"])
    e.mc.map(0, 0x2000)
    left, right = sc.sample(0)
    keep = np.r_[0:int(1.5 * RATE), int(2.0 * RATE):int(2.6 * RATE)]  # less to play: most of the tones, the silence, the hiss
    e.load_pool({0: left[keep], 1: right[keep]})
    for t in range(8):
        e.set_machine(t, 44)
        e.set_note(t, 60)
        for s in range(18, 27):
            e.set_slot(t, s, 0)
        for s, v in ((18, 64), (19, 64 + 63), (21, 127), (25, 127)):
            e.set_slot(t, s, v)
    e.set_slot(7, 19, 64)
    e.set_slot(7, 23, 1)
    got_l, got_r = [], []
    for n in range(len(keep) // 32 + 40):
        got_l.append(e.block(trig=0x80 if n == 0 else 0)[7])
        got_r.append(np.frombuffer(e.mc.read(m.STASH + 128 * 7, 128), dtype=">i4").astype(np.int32))
    take = [np.concatenate(x).astype(np.int64) >> 16 for x in (got_l, got_r)]
    verdict, lines = sc.check(*take)
    assert verdict == "stereo" and lines[-1].startswith("STEREO WORKS on sample 1"), lines
