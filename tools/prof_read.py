"""Reads a profile take (the prof image, engine/prof.S) and says where the main CPU's time went.

    python -m tools.prof_read the_take.wav [more.wav ...]

The file is a take recorded on a sampler track whose SRC was SENDS, saved, and brought off with Transfer: 16-bit
samples, each a word of the record, 32 words a block. It reads files and the official firmware file for names; it
does not talk to the unit.

Two things come out. The interrupt's time is exact: its start and end by the chip's timer, every block. What it
stopped is a sample, once a block and always at the same point of a block: code that runs right after the interrupt
and is done before the next one is never seen, so the tasks' shares lean to what runs long.
"""
import glob
import hashlib
import os
import sys
import wave

import numpy as np

from tools import fw
from tools import mainmap as mm

MAGIC = 0x5052
WORDS = 32
NAMES = ("mark count entry entry_ frame frame_ pc pc_ sp sp_ mix_in mix_in_ mix_out mix_out_ fed fed_ exit exit_ "
         "s0 s0_ s1 s1_ s2 s2_ s3 s3_ s4 s4_ s5 s5_ task task_").split()
LONGS = [n for n in NAMES[2:] if not n.endswith("_")]


def words(path):
    """A take's file as 16-bit words (a stereo file's left side)."""
    with wave.open(path, "rb") as f:
        if f.getsampwidth() != 2:
            raise SystemExit("%s: %d-bit samples, a take is 16" % (path, 8 * f.getsampwidth()))
        x = np.frombuffer(f.readframes(f.getnframes()), dtype="<i2").reshape(-1, f.getnchannels())
    return x[:, 0].astype(np.uint16)


def records(w):
    """The words as records: {name: array}. A record starts with the mark; rows without it are dropped."""
    w = np.asarray(w, dtype=np.uint16)
    best = max(range(WORDS), key=lambda o: int(np.count_nonzero(w[o::WORDS] == MAGIC)))
    rows = w[best:best + WORDS * ((len(w) - best) // WORDS)].reshape(-1, WORDS)
    rows = rows[rows[:, 0] == MAGIC].astype(np.uint32)
    out = {"count": rows[:, 1], "rows": len(rows)}
    for n in LONGS:
        k = NAMES.index(n)
        out[n] = (rows[:, k] << 16 | rows[:, k + 1]).astype(np.uint32)
    return out


def _stats(x, period):
    x = 100.0 * np.asarray(x, dtype=np.float64) / period
    return "mean %5.1f  half under %5.1f  99 in 100 under %5.1f  most %5.1f" % (x.mean(), np.median(x), np.percentile(x, 99), x.max())


def times(r):
    """The interrupt's parts in timer counts, for every block whose next block is in the take too. -> (period, {part: counts})."""
    a = np.nonzero((r["count"][1:] - r["count"][:-1]) & 0xffff == 1)[0]
    if not len(a):
        raise SystemExit("no two blocks in a row: not a profile take")
    b = a + 1
    d = lambda x, y: (x - y).astype(np.uint32)
    period = float(np.median(d(r["entry"][b], r["entry"][a])))
    parts = {"whole": d(r["exit"][b], r["entry"][a]), "before the mixer": d(r["mix_in"][a], r["entry"][a]),
             "the mixer and our links": d(r["mix_out"][a], r["mix_in"][a]), "the takes and the meter": d(r["fed"][b], r["mix_out"][a]),
             "after": d(r["exit"][b], r["fed"][b])}
    if split(r):                                # the mixtime image: the first lap is stock's mixer's start, the sixth stack long its end
        s = [r["s%d" % k][a] for k in range(6)]
        for name, x, y in (("  to the wait: the first call, events and knobs", s[1], r["entry"][a]),
                           ("  the wait for the audio CPU", s[2], s[1]), ("  inputs, to our last call", s[3], s[2]),
                           ("  our transfers made whole", s[4], s[3]), ("  the FX level, to the mixer", r["mix_in"][a], s[4]),
                           ("  our links before stock's mixer", s[0], r["mix_in"][a]), ("  stock's mixer", s[5], s[0]),
                           ("  our links after it", r["mix_out"][a], s[5])):
            parts[name] = d(x, y)
    elif laps(r):                               # the lap image: the way to the mixer in six parts
        s = [r["s%d" % k][a] for k in range(5)]
        for name, x, y in (("  to the routine's first call", s[0], r["entry"][a]), ("  events and knobs, to the wait", s[1], s[0]),
                           ("  the wait for the audio CPU", s[2], s[1]), ("  inputs, to our last call", s[3], s[2]),
                           ("  our transfers made whole", s[4], s[3]), ("  the FX level, to the mixer", r["mix_in"][a], s[4])):
            parts[name] = d(x, y)
    if laps(r) and evlap(r):                    # the evtime tool: events and knobs in five, a lap not reached taken as the one before
        dd = lambda x, y: (x - y).astype(np.uint32).astype(np.int64)
        lo, hi = r["s0"][a], r["s1"][a]
        width = dd(hi, lo)
        at = [lo]
        for n in EV_FIELDS:
            x = r[n][a]
            inside = (dd(x, lo) >= 0) & (dd(x, lo) <= width)
            at.append(np.where(inside & (dd(x, at[-1]) >= 0), x, at[-1]))
        at.append(hi)
        for k, name in enumerate(EV_NAMES):
            parts["    " + name] = d(at[k + 1], at[k])
    ok = parts["whole"] < 4 * period            # a block the mixer was not called in leaves old counts: left out
    for k in list(parts):
        ok &= parts[k] <= parts["whole"]
    return period, {k: v[ok] for k, v in parts.items()}, int(ok.sum()), len(a)


def split(r):
    """Is this the mixtime image's record: the lap image's second to fifth readings before the mixer's call, the first
    after it and the sixth stack long after that, both before the mixer stretch's end, in nine blocks of ten or more."""
    d = lambda x, y: (x - y).astype(np.uint32).astype(np.int64)
    span, out = d(r["mix_in"], r["entry"]), d(r["mix_out"], r["entry"])
    at = [d(r["s%d" % k], r["entry"]) for k in range(6)]
    good = ((at[1] <= at[2]) & (at[2] <= at[3]) & (at[3] <= at[4]) & (at[4] <= span) & (span <= at[0]) & (at[0] <= at[5])
            & (at[5] <= out) & (out < 1 << 24))
    return r["rows"] > 0 and np.count_nonzero(good) >= 0.9 * r["rows"]


EV_FIELDS = ("sp", "pc", "s5", "task")         # the evtime tool's four laps, in order
EV_NAMES = ("head, to the USB receive's clear", "the clear of 0x400 bytes", "the packets' read and after, to 0x4010d7a2",
            "the tracks' events, to 0x4011a4c0", "the sent block, the envelope, to the wait")


def evlap(r):
    """Is this the evtime tool's record: in nine blocks of ten or more at least one of the four laps lies between the
    events stretch's two ends, and none of them anywhere else but where the interrupt's start left a PC, a stack
    pointer, a stack long or a task."""
    d = lambda x, y: (x - y).astype(np.uint32).astype(np.int64)
    width = d(r["s1"], r["s0"])
    inside = [(d(r[n], r["s0"]) >= 0) & (d(r[n], r["s0"]) <= width) & (width < 1 << 24) for n in EV_FIELDS]
    return r["rows"] > 0 and np.count_nonzero(np.any(inside, axis=0)) >= 0.9 * r["rows"]


def ev_hits(r):
    """How often each of the four calls was made: the share of blocks its lap lies inside the stretch."""
    d = lambda x, y: (x - y).astype(np.uint32).astype(np.int64)
    width = d(r["s1"], r["s0"])
    return [100.0 * np.count_nonzero((d(r[n], r["s0"]) >= 0) & (d(r[n], r["s0"]) <= width)) / r["rows"] for n in EV_FIELDS]


def laps(r):
    """Is this the lap image's record: the first five stack longs are readings of the timer, in order, between the
    interrupt's start and the mixer's call, in nine blocks of ten or more."""
    d = lambda x, y: (x - y).astype(np.uint32).astype(np.int64)
    span = d(r["mix_in"], r["entry"])
    at = [d(r["s%d" % k], r["entry"]) for k in range(5)]
    good = (at[0] <= at[1]) & (at[1] <= at[2]) & (at[2] <= at[3]) & (at[3] <= at[4]) & (at[4] <= span) & (span < 1 << 24)
    return r["rows"] > 0 and np.count_nonzero(good) >= 0.9 * r["rows"]


class Code:
    """The official main program, for a name to an address. Without the firmware file addresses are given bare."""

    def __init__(self):
        self.image = None
        for p in sorted(glob.glob(os.path.join("firmware", "**", "*.syx"), recursive=True)):
            if hashlib.sha256(open(p, "rb").read()).hexdigest() in fw.KNOWN:
                self.image = fw.load(p).section(3)
                break
        self.ours = sorted((v, n) for n, v in vars(mm).items() if n.startswith("CAVE") and isinstance(v, tuple) and len(v) == 2)
        self.named = {v: n for n, v in vars(mm).items() if isinstance(v, int) and mm.BASE <= v < mm.CODE_END and n.isupper()}

    def word(self, a):
        o = mm.off(a)
        return int.from_bytes(self.image[o:o + 2], "big")

    def start(self, pc):
        """About where the routine pc is in begins: after the rts or rte before it. A guess from the bytes."""
        for (lo, hi), n in self.ours:
            if lo <= pc < hi:
                return lo, "ours, " + n
        if self.image is None or not mm.BASE <= pc < mm.CODE_END:
            return pc, "" if mm.BASE <= pc < mm.CODE_END else "not in the code"
        a = pc & ~1
        while a > mm.BASE and self.word(a - 2) not in (0x4e75, 0x4e73):
            a -= 2
        return a, self.named.get(a, "")

    def caller(self, longs):
        """The first of a stack's longs that comes after a call instruction, or None."""
        if self.image is None:
            return None
        for v in longs:
            v = int(v)
            if v & 1 or not mm.BASE + 6 <= v < mm.CODE_END:
                continue
            w6, w4, w2 = self.word(v - 6), self.word(v - 4), self.word(v - 2)
            if w6 in (0x4eb9, 0x61ff) or w4 in (0x4eba, 0x6100) or 0x4ea8 <= w4 <= 0x4eaf or 0x4e90 <= w2 <= 0x4e97 \
                    or (w2 >> 8 == 0x61 and w2 & 0xff not in (0, 0xff)):
                return v
        return None


def report(r, code=None, top=12):
    code = code or Code()
    period, parts, used, pairs = times(r)
    out = ["%d blocks, %d of them in a row (%.2f s). %d timed." % (r["rows"], pairs + 1, r["rows"] * 32 / 48000.0, used),
           "A block is %.0f counts of the timer: it counts at %.1f MHz." % (period, period * 1500 / 1e6), "",
           "The per-block interrupt, in hundredths of a block:"]
    for k, v in parts.items():
        out.append("  %-26s %s" % (k, _stats(v, period)))
    out += ["  left for everything else   mean %5.1f" % (100 - 100.0 * parts["whole"].mean() / period), ""]
    level = (r["frame"] >> 8) & 7
    out.append("What the interrupt stopped, by its level (0: a task): " + ", ".join(
        "%d: %.1f%%" % (k, 100.0 * np.count_nonzero(level == k) / r["rows"]) for k in sorted(set(level.tolist()))))
    out.append("")
    if laps(r) and evlap(r):                    # the evtime tool: its record has no PC, stack or task to report
        out.append("The evtime tool: each lap's call made in %s of the blocks; no PC, stack or task in its record." %
                   ", ".join("%.0f%%" % h for h in ev_hits(r)))
        return "\n".join(out)
    stacks = (np.zeros((r["rows"], 1), dtype=np.uint32) if split(r)       # the mixtime image: no stack long is left
              else np.stack([r["s%d" % k] for k in (range(5, 6) if laps(r) else range(6))], axis=1))
    tasks = sorted(set(r["task"].tolist()), key=lambda t: -np.count_nonzero(r["task"] == t))
    out.append("By task (the running task's block), then the routines it was in and who called them:")
    for t in tasks:
        rows = np.nonzero(r["task"] == t)[0]
        out.append("  task %#010x  %5.1f%%  stack %#010x to %#010x" % (t, 100.0 * len(rows) / r["rows"], r["sp"][rows].min(), r["sp"][rows].max()))
        seen = {}
        for i in rows:
            at, name = code.start(int(r["pc"][i]))
            key = (at, name, code.caller(stacks[i]))
            seen[key] = seen.get(key, 0) + 1
        for (at, name, caller), n in sorted(seen.items(), key=lambda kv: -kv[1])[:top]:
            line = "    %5.1f%%  %#010x %s" % (100.0 * n / r["rows"], at, name)
            if caller is not None:
                line += "  <- %#010x (in %#010x %s)" % ((caller,) + code.start(caller))
            out.append(line.rstrip())
    return "\n".join(out)


def main(argv):
    if not argv:
        raise SystemExit(__doc__)
    w = np.concatenate([words(p) for p in argv])
    r = records(w)
    if r["rows"] < 2:
        raise SystemExit("no records: not a profile take (was SRC on SENDS, on the prof image?)")
    print(report(r))


if __name__ == "__main__":
    main(sys.argv[1:])
