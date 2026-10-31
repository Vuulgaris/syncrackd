"""A measured check of one-track stereo on the unit, all eight tracks. Files only: it never talks to a Syntakt.

    make stereo-sample              # eight stereo check samples as 16 files for Transfer, slots 49 to 64
    make stereo-sample FIRST=1      # or from any odd slot up to 49
    make stereo-check               # reads a recording from samples/check/ and says what it shows





Eight samples, one for each track, 4 seconds each, made here with nothing of Elektron's in them:
    0.00 to 2.00 s   a low tone on the left only and a high tone on the right only. Sixteen
                     different tones in all, so every track's two channels can be told apart in one
                     recording of all of them
    after 2.25 s     one burst of hiss, the same on both sides, each sample's at its own moment
By ear, one track alone: a low tone in the left ear, a high one in the right, then a blip of hiss
dead centre. All eight together: two chords, then eight blips one after another.

The measured part: play them on the unit, record the main mix (a take on another sampler track with
SRC on MAIN, saved and pulled off with Transfer; or the unit's USB audio), and give the recording to
check(). From the recording alone it says, for each sample it hears:
  - whether its left tone is on the left and its right tone on the right, and how far under each
    the other side's is. A sample's left tone on both sides and its right tone nowhere is the main
    CPU playing that track's left channel twice: the right channel did not cross;
  - whether its two sides are a block of the same sound: its hiss is the same on both, so the two
    sides line up to the frame, and a right channel a block early or late is 32 frames off, which
    no tone shows;
and for each side of the whole recording: how far under the tones their harmonics are (distortion),
what else is there, and its largest jump (a block read while it was being written is a click the
size of a tone).
Every sample has to play at the same pitch (any one: TUNE and the note may be moved together).
"""
import argparse
import os
import sys

import numpy as np

from . import split_sample

RATE = 48000
SECONDS = 4.0
N = 8
# no tone's 2nd to 7th harmonic comes within 25 Hz of another tone, and no two are closer than 45 Hz
F_LEFT = (300, 345, 390, 435, 480, 525, 625, 715)
F_RIGHT = (1130, 1225, 1330, 1405, 1465, 1525, 1600, 1660)
LEVEL = 8192                            # a tone: a quarter of full scale
TONES = (0.0, 2.0)
HISS_AT, HISS_EVERY, HISS_LONG = 2.25, 0.18, 0.13      # sample k's burst starts at HISS_AT + k * HISS_EVERY
NAME = "STCHECK"
BLOCK = 32                              # frames the two CPUs hand over at a time
STEP = 240                              # the loudness of a recording is followed 5 ms at a time
HARMONICS = (2, 3, 4, 5)


def _fade(n, edge):
    env = np.ones(n)
    ramp = 0.5 - 0.5 * np.cos(np.pi * np.arange(edge) / edge)
    env[:edge], env[-edge:] = ramp, ramp[::-1]
    return env


def sample(k=0):
    """Check sample k of 0..7 -> (left, right), int16, 4 s at 48 kHz."""
    n = int(SECONDS * RATE)
    t = np.arange(n) / RATE
    left, right = np.zeros(n), np.zeros(n)
    a, b = (int(x * RATE) for x in TONES)
    env = _fade(b - a, RATE // 100)
    left[a:b] = LEVEL * np.sin(2 * np.pi * F_LEFT[k] * t[:b - a]) * env
    right[a:b] = LEVEL * np.sin(2 * np.pi * F_RIGHT[k] * t[:b - a]) * env
    m = int(HISS_LONG * RATE)
    spec = np.fft.rfft(np.random.default_rng(2026 + k).standard_normal(m))
    hz = np.fft.rfftfreq(m, 1 / RATE)
    spec[(hz < 200) | (hz > 6000)] = 0                  # hiss the unit's filters pass whole
    hiss = np.fft.irfft(spec, m)
    hiss *= 1.5 * LEVEL / np.abs(hiss).max()
    at = int((HISS_AT + k * HISS_EVERY) * RATE)
    left[at:at + m] = right[at:at + m] = hiss * _fade(m, RATE // 200)
    return np.round(left).astype(np.int16), np.round(right).astype(np.int16)


def write_samples(outdir, first=49):
    """Sixteen files Transfer takes, named by slot, and a sheet. first: the first left's slot, odd, 1 to 49."""
    if not 1 <= first <= 65 - 2 * N or first % 2 == 0:
        raise SystemExit("the eight samples take 16 slots from an odd one: 1 to %d" % (65 - 2 * N))
    os.makedirs(outdir, exist_ok=True)
    for f in os.listdir(outdir):                        # a run from another slot is not left beside this one
        if NAME in f and f.endswith(".wav"):
            os.remove(os.path.join(outdir, f))
    paths, rows = [], []
    for k in range(N):
        left, right = sample(k)
        paths += split_sample.write([("L", left), ("R", right)], "%s%d" % (NAME, k + 1), outdir, slot=first + 2 * k)
        rows.append("  track %d   SMPL %2d   slots %2d and %2d   left ear %4d Hz, right ear %4d Hz"
                    % (k + 1, (first + 2 * k + 1) // 2, first + 2 * k, first + 2 * k + 1, F_LEFT[k], F_RIGHT[k]))
    sheet = os.path.join(outdir, "HOW_TO_CHECK.txt")
    with open(sheet, "w") as f:
        f.write(SHEET % "\n".join(rows))
    return paths, sheet


SHEET = """Stereo check samples: eight stereo samples, one for each of tracks 1 to 8.

Send all 16 files with Transfer, each to the slot its name starts with. They replace what is in those
slots of the bank that is loaded, so use a bank or slots you can spare. Then on the unit, a new pattern:

%s

On each of those tracks: the sampler, MODE on STEREO, SMPL as listed, TUNE and the note left alone,
LOOP off, PAN in the middle, VOL the same on all, OVER 0, filter open, delay and reverb sends at 0.
A trig on step 1. Nothing else playing.

1. BY EAR, headphones. Solo one track at a time: a low tone in the left ear, a high one in the right,
   then a blip of hiss dead centre. PAN hard left: the low tone alone. Hard right: the high tone alone.
   The low tone in both ears and never the high one means that track's right channel is not arriving.
   A steady tone is where a click or grit is plainest: note which tracks have it, and in which ear.

2. MEASURED. A track that records does not play, so all eight take two passes.
   Pass A: track 8 records, tracks 1 to 7 play. On track 8, the sampling page: SRC on MAIN, DEST on a
           stereo sample you can spare that is not one of the eight above, REC on, and its trig on
           step 1 made long enough to last 4 seconds. Play the pattern once. REC off, SAVE (fifth knob).
           Pull that take's two files (TAKE nn L and R) off with Transfer into the project's
           samples/check folder, with nothing else in it, and run:   make stereo-check
   Pass B: the same with track 1 recording and tracks 2 to 8 playing.
   It names every sample it hears and says for each whether left and right are each on their own
   side and in step, and for each side how clean it is: distortion, noise and clicks, in numbers.
   STEREO WORKS means what it says.
   A stereo recording of the unit's USB audio does as well as a take, and holds all eight in one go.

3. HOW MANY AT ONCE. LOOP on FWD on all of them, the pattern running. Then turn TUNE on each so they
   are pitched. Note how many stereo tracks play before it crackles, pitched and not.
"""


# ---- reading a recording -------------------------------------------------------------------------

def _loudness(left, right):
    """The recording's loudness, both sides together, a value every STEP frames."""
    n = len(left) // STEP * STEP
    p = (left[:n] ** 2 + right[:n] ** 2).reshape(-1, STEP).mean(axis=1)
    return np.sqrt(np.convolve(p, np.ones(4) / 4, mode="same"))


def _runs(mask):
    """Every run of True in mask -> [(first, one past the last)]."""
    out, at = [], None
    for k, v in enumerate(list(mask) + [False]):
        if v and at is None:
            at = k
        elif not v and at is not None:
            out.append((at, k))
            at = None
    return out


def _strength(x, y, freqs):
    """How much of the tones of freqs is in x and y together."""
    t = np.arange(len(x)) / RATE
    win = np.hanning(len(x))
    return sum(abs(np.dot(z * win, np.exp(-2j * np.pi * f * t))) for f in freqs for z in (x, y))


def _speed(x, y):
    """What the recording's pitch is to the samples' own: the one number that puts all sixteen tones where the most sound is."""
    spec = np.abs(np.fft.rfft((x + y) * np.hanning(len(x))))
    peak = (int(spec[20:].argmax()) + 20) * RATE / len(x)
    every = F_LEFT + F_RIGHT
    tries = [peak / f for f in every if 0.4 <= peak / f <= 2.5]
    best = max(tries, key=lambda s: _strength(x, y, [s * f for f in every]))
    step = 0.002
    for _ in range(6):
        best = max(best + step * np.linspace(-1, 1, 9), key=lambda s: _strength(x, y, [s * f for f in every]))
        step /= 3
    return float(best)


def _fit(x, freqs, twice=False):
    """Least squares of x on sines and cosines of freqs. -> (amplitude of each, what is left).
    twice: fitted again without the frames that stand far out of what was left, so that a click does not bend the fit."""
    t = np.arange(len(x)) / RATE
    cols = [np.ones(len(x))]
    for f in freqs:
        cols += [np.sin(2 * np.pi * f * t), np.cos(2 * np.pi * f * t)]
    A = np.stack(cols, axis=1)
    coef = np.linalg.lstsq(A, x, rcond=None)[0]
    if twice:
        rest = np.abs(x - A @ coef)
        out = np.convolve(rest > 6 * 1.4826 * np.median(rest) + 1e-9, np.ones(4 * BLOCK + 1), mode="same") > 0
        if out.any() and out.sum() < len(x) // 2:
            coef = np.linalg.lstsq(A[~out], x[~out], rcond=None)[0]
    return [float(np.hypot(coef[1 + 2 * k], coef[2 + 2 * k])) for k in range(len(freqs))], x - A @ coef


def _under(x):
    """A level in dB as words."""
    return "%.0f dB under" % -x if x < 0 else "%.0f dB over" % x


def db(a, b):
    return 20 * np.log10(max(a, 1e-9) / max(b, 1e-9))


def _step(x, y, lo, hi):
    """Two stretches that should be the same sound: how many frames y is behind x, and how alike they are there."""
    x, y = x[lo:hi] - x[lo:hi].mean(), y[lo:hi] - y[lo:hi].mean()
    if len(x) < 8 * BLOCK or np.dot(x, x) < len(x) or np.dot(y, y) < len(y):
        return None
    size = 1 << int(np.ceil(np.log2(2 * len(x))))
    cc = np.fft.irfft(np.fft.rfft(y, size) * np.conj(np.fft.rfft(x, size)), size)
    lags = np.arange(-4 * BLOCK, 4 * BLOCK + 1)
    vals = cc[lags % size] / np.sqrt(np.dot(x, x) * np.dot(y, y))
    return int(lags[int(vals.argmax())]), float(vals.max())


def check(left, right):
    """A recording of the check samples -> (verdict, lines). 'stereo': every sample heard is right on both sides and
    the recording is clean. 'mono': every one is its left on both sides. 'fault': anything else."""
    left, right = np.asarray(left, dtype=float), np.asarray(right, dtype=float)
    n = min(len(left), len(right))
    left, right = left[:n], right[:n]
    if n < RATE:
        return "fault", ["The recording is under a second long."]
    loud = _loudness(left, right)
    if loud.max() < 100:
        return "fault", ["The recording is silent, or nearly."]
    # the tones: a loud stretch of half a second or more (a burst of hiss is short). In a recording of a loop, the
    # longest one that has the two seconds after it in the recording, where the hiss is
    runs = [(a, b) for a, b in _runs(loud > loud.max() / 4) if (b - a) * STEP >= RATE // 2]
    if not runs:
        return "fault", ["No steady tones were found: is this a recording of the check samples, with at least half a second of their tones?"]
    whole = [r for r in runs if r[1] * STEP + 2 * RATE <= n]
    a, b = max(whole or runs, key=lambda r: r[1] - r[0])
    lo, hi = a * STEP + RATE // 10, b * STEP - RATE // 10
    L, R = left[lo:hi], right[lo:hi]
    speed = _speed(L, R)
    fl, fr = [speed * f for f in F_LEFT], [speed * f for f in F_RIGHT]
    harm = [h * f for f in fl + fr for h in HARMONICS]
    use = [f for f in harm if f < RATE / 2 - 100]
    al, rest_l = _fit(L, fl + fr + use, twice=True)
    ar, rest_r = _fit(R, fl + fr + use, twice=True)
    top = max(al[:2 * N] + ar[:2 * N])
    if top < 30:
        return "fault", ["None of the eight samples' tones are in the recording."]
    lines = ["The recording plays the samples at %.3f of their own pitch." % speed] if abs(speed - 1) > 0.002 else []
    good, mono, bad, unheard, faults = [], [], [], [], []
    for k in range(N):
        own_l, leak_l, own_r, leak_r = al[k], ar[k], ar[N + k], al[N + k]
        name = "Sample %d" % (k + 1)
        if max(own_l, leak_l, own_r, leak_r) < top / 30:
            unheard.append(k + 1)
            continue
        if own_l > 10 * leak_l and own_r > 10 * leak_r and min(own_l, own_r) > top / 30:
            apart = min(db(own_l, leak_l), db(own_r, leak_r))
            text = "%s: %d Hz on the left, %d Hz on the right, each on its own side (the other side's %.0f dB under)" % (
                name, round(fl[k]), round(fr[k]), apart)
            ok = True
            if apart < 50:
                ok = False
                faults.append("%s: its two channels leak into each other, only %.0f dB apart." % (name, apart))
            # its hiss: one burst, the same on both sides, at its own moment after the tones end
            at = b * STEP + int((HISS_AT - TONES[1] + k * HISS_EVERY + 0.02) * RATE / speed)
            got = _step(left, right, at, at + int((HISS_LONG - 0.04) * RATE / speed)) if at + RATE // 8 < n else None
            if got is None or got[1] < 0.5:
                ok = False
                text += ". Its hiss is not in the recording, so whether its sides are in step was not measured"
                faults.append("%s: no hiss after its tones. Record the whole 4 seconds." % name)
            else:
                lag, alike = got
                if lag:
                    ok = False
                    faults.append("%s: its right side is %d frames %s its left. A block is %d: the two sides are not a block of the same sound."
                                  % (name, abs(lag), "behind" if lag > 0 else "ahead of", BLOCK))
                elif alike < 0.97:
                    ok = False
                    faults.append("%s: its hiss differs between the sides (alike to %.3f): noise on one side, or blocks of it out of place." % (name, alike))
                else:
                    text += ", in step (0 frames, alike to %.3f)" % alike
            lines.append(text + ".")
            (good if ok else bad).append(k + 1)
        elif abs(db(own_l, leak_l)) < 3 and max(own_r, leak_r) < own_l / 30:
            mono.append(k + 1)
            lines.append("%s: ITS LEFT TONE (%d Hz) IS ON BOTH SIDES and its right tone (%d Hz) is nowhere. Its right channel did not cross."
                         % (name, round(fl[k]), round(fr[k])))
        elif leak_l > 10 * own_l and leak_r > 10 * own_r:
            bad.append(k + 1)
            faults.append("%s: its sides are swapped, the right channel's tone is on the left." % name)
        else:
            bad.append(k + 1)
            faults.append("%s: neither stereo nor its left twice. Left tone %.0f on the left and %.0f on the right; right tone %.0f on the right and %.0f on the left."
                          % (name, own_l, leak_l, own_r, leak_r))
    # each side: the tones' harmonics, what else is there, and the largest jump in it
    place = {f: 2 * N + k for k, f in enumerate(use)}
    for side, rest, amps, tones in (("left", rest_l, al, fl), ("right", rest_r, ar, fr)):
        base = 0 if side == "left" else N
        heard = [k for k in range(N) if amps[base + k] > top / 30]
        if not heard:
            if good or bad:
                faults.append("The %s side of the recording has no tone at all: is PAN in the middle, and is this the main mix?" % side)
            continue
        own = np.sqrt(sum(amps[base + k] ** 2 for k in heard))         # the tones of this side together
        worst = max(db(amps[place[h * tones[k]]], amps[base + k]) for k in heard for h in HARMONICS if h * tones[k] in place)
        rest = rest[RATE // 20:-RATE // 20]
        rms = np.sqrt(np.mean(rest ** 2))
        quiet = 1.4826 * np.median(np.abs(rest))                        # what is left, the clicks apart
        floor, peak = db(quiet, own / np.sqrt(2)), db(np.abs(rest).max(), own)
        lines.append("The %s side: harmonics %s their tones, everything else %s the tones, its largest jump %s."
                     % (side, _under(worst), _under(floor), _under(peak)))
        if worst > -40:
            faults.append("Distortion on the %s side: a harmonic only %s its tone." % (side, _under(worst)))
        if peak > -30 and np.abs(rest).max() > 8 * quiet:               # large jumps in little else: clicks, not noise
            at = np.nonzero(np.abs(rest) > max(10 ** (-30 / 20) * own, 8 * quiet))[0]
            faults.append("Clicks on the %s side: %d in %.1f s, the largest %s the tones."
                          % (side, 1 + int(np.count_nonzero(np.diff(at) > 4 * BLOCK)), len(rest) / RATE, _under(peak)))
        elif db(rms, own / np.sqrt(2)) > -40:                           # a take is 16 bits: its own noise is 60 dB and more under these tones
            faults.append("Noise on the %s side: only %s the tones." % (side, _under(db(rms, own / np.sqrt(2)))))
    if unheard and len(unheard) < N:
        lines.append("Not in the recording: sample%s %s." % ("s" if len(unheard) > 1 else "", ", ".join(map(str, unheard))))
    verdict = "stereo" if good and not mono and not bad and not faults else "mono" if mono and not good and not bad else "fault"
    said = {"stereo": "STEREO WORKS on %s: each side carries its own channel, in step, with nothing added.",
            "mono": "NOT STEREO on %s: the right channel is not arriving. Nothing else is wrong with the unit: report it.",
            "fault": "SOMETHING IS OFF (heard: %s): read the lines above."}[verdict]
    heard = sorted(good + mono + bad)
    which = "all eight samples" if len(heard) == N else "sample%s %s" % ("s" if len(heard) > 1 else "", ", ".join(map(str, heard)))
    return verdict, lines + faults + ["", said % which]


def read(paths):
    """One stereo file, or a left and a right. -> (left, right)"""
    if len(paths) == 1:
        x = split_sample.load(paths[0])
        if x.shape[1] != 2:
            raise SystemExit("%s is mono: give the left file and the right file" % paths[0])
        return x[:, 0], x[:, 1]
    left, right = (split_sample.load(p) for p in paths[:2])
    return left[:, 0], right[:, 0]


def find(folder):
    """The recording in a folder: one stereo file, or two files whose names end in L and R."""
    files = sorted(os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(split_sample.AUDIO)) if os.path.isdir(folder) else []
    if len(files) == 1:
        return files
    pair = {os.path.splitext(f)[0].rstrip().upper()[-1]: f for f in files}
    if len(files) == 2 and set(pair) == {"L", "R"}:
        return [pair["L"], pair["R"]]
    raise SystemExit("put one recording in %s: one stereo file, or a take's two files, their names ending in L and R (%d audio files there now)"
                     % (folder, len(files)))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("what", choices=("sample", "check"))
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--out", default=os.path.join("build", "samples", "stereo_check"))
    ap.add_argument("--first", type=int, default=65 - 2 * N)
    args = ap.parse_args(argv)
    if args.what == "sample":
        paths, sheet = write_samples(args.out, args.first)
        print("%d files in %s, and %s:\n" % (len(paths), args.out, os.path.basename(sheet)))
        print(open(sheet).read())
        return 0
    paths = args.paths if args.paths and not os.path.isdir(args.paths[0]) else find(args.paths[0] if args.paths else os.path.join("samples", "check"))
    verdict, lines = check(*read(paths))
    print("\n".join(lines))
    return 0 if verdict == "stereo" else 1


if __name__ == "__main__":
    sys.exit(main())
