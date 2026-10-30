"""The interpolation table of the "pitch" image: a windowed sinc, 16 taps, 32 phases.

    python -m tools.sinctable            # what it does to a pitched sine, against the two-point line it replaces

The engine reads a sample between frames i and i + 1, f/4096 of the way along, as the sum of 16
frames around it, each times a number from this table: row f >> 7 and the next row, blended by
the low 7 bits of f. A row is the sinc for that fraction of a frame under a Kaiser window, held
to 15 bits and made to add up to exactly ONE, so a steady level stays where it is at every
fraction. Row 0 is one frame alone; row 32 is the next frame alone.

Only rows 0 to 16 are stored in the image: row 32 - r is row r backwards.
"""
import numpy as np

TAPS, PHASES = 16, 32
BEFORE = TAPS // 2 - 1          # the first tap is this many frames before frame i
ONE = 32767
BETA = 8.0


def rows(taps=TAPS, phases=PHASES, beta=BETA, one=ONE):
    """All phases + 1 rows, as lists of ints."""
    half = []
    for p in range(phases // 2 + 1):
        n = np.arange(taps) - (taps // 2 - 1) - p / phases
        h = np.sinc(n) * np.i0(beta * np.sqrt(np.clip(1 - (n / (taps / 2)) ** 2, 0, 1))) / np.i0(beta)
        q = np.round(h / h.sum() * one).astype(int)
        q[int(np.argmax(q))] += one - int(q.sum())      # what rounding left over goes to the largest
        half.append([int(v) for v in q])
    # the middle row is used as it is: ONE is odd, so its two halves cannot be the same
    return half + [half[phases - p][::-1] for p in range(phases // 2 + 1, phases + 1)]


TWELVE, SKIP = 12, 2            # the table of twelve: a sinc of 12 frames in the middle 12 places of the 16, SKIP noughts at each end


def rows12():
    """The table of twelve, in the shape of the table of sixteen: the engine built with TWELVE leaves the outer two
    frames at each end out of the sum, which is what a nought there does."""
    return [[0] * SKIP + r + [0] * SKIP for r in rows(taps=TWELVE)]


SIX, BETA6 = 6, 5.0              # the six image: a sinc of 6 frames in places 5 to 10 of the 16, a window of its own
#   (the sixteen's, 8.0, left a sine at 10 kHz pitched a fifth only 34 dB clean; 5.0 makes it 60, and 71 at 5 kHz)


def rows6():
    """The table of six, in the shape of the table of sixteen: five noughts at each end."""
    return [[0] * 5 + r + [0] * 5 for r in rows(taps=SIX, beta=BETA6)]


EIGHT, BETA8 = 8, 5.0            # the eight image: a sinc of 8 frames in places 4 to 11 of the 16, a window of its own
#   (a fifth up, 15 kHz 44 dB clean where the sixteen's 8.0 left 27, 10 kHz 96, 5 kHz 61; the gain within 0.7 dB to 18 kHz)


def rows8():
    """The table of eight, in the shape of the table of sixteen: four noughts at each end."""
    return [[0] * 4 + r + [0] * 4 for r in rows(taps=EIGHT, beta=BETA8)]


def stored(twelve=False, six=False, eight=False):
    """The rows the image holds: 0 to PHASES / 2."""
    return (rows8() if eight else rows6() if six else rows12() if twelve else rows())[:PHASES // 2 + 1]


def magic(twelve=False, six=False, eight=False):
    """A long that changes when the table does: the engine builds its copy again when this is not beside it."""
    h = 0x48510000
    for row in stored(twelve, six, eight):
        for v in row:
            h = (h * 31 + (v & 0xFFFF)) & 0xFFFFFFFF
    return h | 1


def source(cave="z", twelve=False, narrow=False, six=False, eight=False):
    """The stored rows as assembler, for the engine's build: in the run of code the build names.
    narrow: the table of twelve without the two numbers at each end of a row, which are 0 and which no sum reads."""
    out = ["| made by tools/sinctable.py: rows 0 to %d of the interpolation table, %d taps each" % (PHASES // 2, EIGHT if eight else SIX if six else TWELVE if twelve else TAPS),
           "    .section .cave.%s,\"ax\"" % cave, "    .globl  hq_rows", "hq_rows:"]
    for row in stored(twelve, six, eight):
        if narrow:
            assert twelve and not any(row[:SKIP] + row[-SKIP:])
            row = row[SKIP:-SKIP]
        out.append("    .word   " + ", ".join(str(v) for v in row))
    return "\n".join(out) + "\n"


def interp(x, i, f, table=None):
    """What the engine computes for frame i + f/4096 of x (ints), before it is scaled: see emu/sampler_ref.py."""
    table = table or rows()
    r0, r1 = table[f >> 7], table[(f >> 7) + 1]
    n = len(x)
    d0 = d1 = 0
    for k in range(TAPS):
        v = x[min(max(i + k - BEFORE, 0), n - 1)]
        d0 += v * r0[k]
        d1 += v * r1[k]
    return d0 + ((d1 - d0) >> 7) * (f & 127)


def clean(f0, ratio, method, n=1 << 14, fs=48000):
    """dB from a sine at f0 played at `ratio` of its speed to everything else that comes out."""
    m = int(n * ratio) + 64
    x = [int(round(30000 * np.sin(2 * np.pi * f0 / fs * k))) for k in range(m + 64)]
    pos = [(32 << 12) + int(round(k * ratio * 4096)) for k in range(n)]
    y = np.array([method(x, p >> 12, p & 0xFFF) for p in pos], dtype=float)
    w = np.blackman(n) ** 2
    Y = np.abs(np.fft.rfft(y * w)) ** 2
    k0 = int(round(f0 * ratio / fs * n))
    sig = Y[max(0, k0 - 12):k0 + 13].sum()
    return 10 * np.log10(sig / max(Y.sum() - sig, 1e-30))


def line(x, i, f):
    return x[i] * (4096 - f) + x[i + 1] * f


if __name__ == "__main__":
    t = rows()
    assert all(sum(r) == ONE for r in t) and t[0][BEFORE] == ONE and t[PHASES][BEFORE + 1] == ONE
    print("largest sum of sizes in a row: %d (%.2f x ONE)" % (max(sum(abs(v) for v in r) for r in t), max(sum(abs(v) for v in r) for r in t) / ONE))
    freqs = (220, 1000, 3000, 6000, 10000, 14000, 16000, 18000)
    for ratio, name in ((0.25, "2 octaves down"), (0.5, "1 octave down"), (0.749, "5 semitones down"), (0.9439, "1 semitone down"), (1.4983, "7 semitones up")):
        print("%s: dB from the tone to everything else" % name)
        print("%-10s" % "" + "".join("%8d" % f for f in freqs))
        print("%-10s" % "line" + "".join("%8.1f" % clean(f, ratio, line) for f in freqs if f * ratio < 23000))
        print("%-10s" % "table" + "".join("%8.1f" % clean(f, ratio, lambda x, i, fr: interp(x, i, fr, t)) for f in freqs if f * ratio < 23000))
