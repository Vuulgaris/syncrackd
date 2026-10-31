"""Turn audio files into the mono pieces the sampler expects. Writes files only.

    make samples                                              # everything in samples/ -> build/samples/transfer/
    python -m tools.split_sample pad.wav hits/ --out build/samples/set1 --first 9

Elektron Transfer trims anything over 5 seconds and stores 16-bit 48 kHz mono.
So a stereo sample goes in as two files, left and right, in neighbouring slots
(MODE 1, "stereo"). 64 slots hold 32 stereo samples of up to 5 seconds.

In stereo the SMPL knob counts stereo samples, not slots: number n is slots
2n-1 and 2n. So a stereo sample always starts on an odd slot here, and a slot
is left empty where a mono sample would otherwise put it on an even one.

Every input becomes 16-bit 48 kHz, so Transfer has nothing left to convert.
The slot each file belongs in is the number at the front of its name:
    stereo, up to 5 s     07_name_L.wav, 08_name_R.wav
    mono, up to 5 s       09_name.wav
    longer                cut into 5 s samples: 10_name_01L.wav, 11_name_01R.wav, 12_name_02L.wav, ...
Nothing is resampled down or packed. Folders are read with their subfolders,
in name order.

Next to the output folder a text file lists which slot holds what, and the
MODE and SMPL to dial in. Pieces of a longer file are samples of their own;
MODE 5 ("chain") plays them as one, up to the first empty slot.
"""
import argparse
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import wave

import numpy as np

RATE = 48000
MAX_SLOTS = 64
MAX_SECONDS = 5.0
# The "big" image (tools/build_main.py): slots of 1 MB, filled by the changed copy of Transfer
# (tools/patch_transfer.py), which cuts at 10 s. At boot the unit still loads no more than stock
# could in all: 64 x 524,224 bytes of samples.
BIG_SECONDS = 10.0
SINGLE_FIRST = 33           # the pack image: slots 33 to 64 are also places of their own, each a mono sample
# The stops image (engine/sampler.h, STOPS) tells what a slot holds by its length: an odd number of frames is a single
# slot's mono sample, an even number belongs to a stereo place. So with --pack a mono file is made odd and a stereo one
# even on both sides, by leaving its last frame out where it has to be. On the pack image the length says nothing.
BIG_POOL_FRAMES = 64 * 0x7ffc0 // 2
# the "double" image sends the pool in two halves of 16382 chunks of 2 KB; each slot's count is 4 bytes of it
DOUBLE_POOL_FRAMES = (2 * 16382 * 2048 - 4 * 64) // 2
AUDIO = (".wav", ".aif", ".aiff", ".mp3", ".m4a", ".flac", ".caf")
MARKER = ".made_by_split_sample"          # in an output folder: its numbered files are ours to replace


def read_wav(path):
    """16-bit PCM WAV -> (int16 array of shape (frames, channels), rate)."""
    with wave.open(path, "rb") as w:
        if w.getsampwidth() != 2:
            raise ValueError("%s is not 16-bit PCM" % path)
        rate, ch = w.getframerate(), w.getnchannels()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    return x.reshape(-1, ch), rate


def load(path):
    """Any audio file -> 16-bit 48 kHz, via macOS afconvert when a conversion is needed."""
    try:
        x, rate = read_wav(path)
        if rate == RATE:
            return x
    except (wave.Error, ValueError, EOFError):
        pass
    afconvert = shutil.which("afconvert")
    if not afconvert:
        raise SystemExit("%s is not a 16-bit 48 kHz WAV and afconvert is not available to convert it" % path)
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "converted.wav")
        subprocess.run([afconvert, "-f", "WAVE", "-d", "LEI16@%d" % RATE, "--src-complexity", "bats",
                        path, out], check=True, capture_output=True)
        x, rate = read_wav(out)
    if rate != RATE:
        raise SystemExit("conversion did not give %d Hz" % RATE)
    return x


def clock(seconds):
    return "%d:%02d" % (seconds // 60, seconds % 60)


def split(x, chunk_seconds=None, mono=False, limit=MAX_SECONDS):
    """(frames, channels) int16 -> list of (name suffix, mono int16 array), in slot order.
    limit: the longest a slot may be, 5 s, or 10 s for the big image."""
    chunk_seconds = limit if chunk_seconds is None else chunk_seconds
    if not 0 < chunk_seconds <= limit:
        raise ValueError("chunk must be at most %g seconds" % limit)
    if x.shape[1] > 2:
        raise ValueError("more than two channels")
    if mono and x.shape[1] == 2:
        x = ((x[:, 0].astype(np.int32) + x[:, 1]) // 2).astype(np.int16).reshape(-1, 1)
    frames, channels = x.shape
    if frames < 2:
        raise ValueError("nothing to split")
    pieces = max(1, math.ceil(frames / int(chunk_seconds * RATE)))
    if pieces * channels > MAX_SLOTS:
        raise ValueError("%s of %s needs %d slots, the Syntakt has %d: room for %s of stereo or %s of mono" % (
            clock(frames / RATE), "stereo" if channels == 2 else "mono", pieces * channels, MAX_SLOTS,
            clock(MAX_SLOTS // 2 * limit), clock(MAX_SLOTS * limit)))
    size = math.ceil(frames / pieces)                 # equal pieces, the last one no longer than the rest
    out = []
    for k in range(pieces):
        part = x[k * size:(k + 1) * size]
        for c in range(channels):
            suffix = ("%02d" % (k + 1) if pieces > 1 else "") + ("LR"[c] if channels == 2 else "")
            out.append((suffix, part[:, c].copy()))
    return out


def write(pieces, stem, outdir, slot=None):
    """slot: the slot of the first piece, counted from 1. Then every name starts with its slot number."""
    os.makedirs(outdir, exist_ok=True)
    paths = []
    for k, (suffix, data) in enumerate(pieces):
        name = "%s%s.wav" % (stem, "_" + suffix if suffix else "")
        if slot is not None:
            name = "%02d_%s" % (slot + k, name)
        path = os.path.join(outdir, name)
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(data.astype("<i2").tobytes())
        paths.append(path)
    return paths


def mode_hint(stereo, chain=False):
    """The MODE value, and what the stock screen shows for it."""
    mode = (1 if stereo else 0) + (4 if chain else 0)
    return mode, mode - 64


def inputs(paths):
    """The files to convert: files as given, and the audio files inside any folder given, subfolders too."""
    out = []
    for p in paths:
        if os.path.isdir(p):
            for root, dirs, names in os.walk(p):
                dirs.sort(key=str.lower)
                out += [os.path.join(root, f) for f in sorted(names, key=str.lower)
                        if f.lower().endswith(AUDIO) and not f.startswith(".")]
        else:
            out.append(p)
    return out


def kinded(pieces, stereo):
    """The pieces with lengths that say what they are (the stops image): a mono sample an odd number of frames, a stereo
    one an even number on both sides. The last frame is left out where the length is the other kind; never more."""
    return [(suffix, data[:len(data) - (len(data) % 2 != (0 if stereo else 1))]) for suffix, data in pieces]


def convert(files, chunk_seconds=None, mono=False, first=1, limit=MAX_SECONDS, pool=BIG_POOL_FRAMES, pack=False):
    """-> [(stem, stereo, pieces)] for every file. ValueError if they do not fit from slot `first` on.
    pool: with slots longer than stock's, the frames the unit loads at boot in all.
    pack: for the pack image, where the mono ones go in the single slots from 64 down (place), and for the stops
    image, which goes by a length's kind (kinded)."""
    if not 1 <= first <= MAX_SLOTS:
        raise ValueError("the first slot must be 1 to %d" % MAX_SLOTS)
    jobs = []
    for path in files:
        stem = os.path.splitext(os.path.basename(path))[0].replace(" ", "_")
        x = load(path)
        try:
            pieces = split(x, chunk_seconds, mono, limit)
        except ValueError as err:
            raise ValueError("%s: %s" % (path, err))
        stereo = x.shape[1] == 2 and not mono
        jobs.append((stem, stereo, kinded(pieces, stereo) if pack else pieces))
    end, low = first, MAX_SLOTS + 1
    for slot, _, stereo, pieces in place(jobs, first, pack):
        if pack and not stereo:
            low = slot
        else:
            end = slot + len(pieces)
    if low < SINGLE_FIRST:
        raise ValueError("%d mono samples, and the pack image plays %d by their own numbers: slots %d to %d" % (
            MAX_SLOTS + 1 - low, MAX_SLOTS + 1 - SINGLE_FIRST, SINGLE_FIRST, MAX_SLOTS))
    if pack and end > low:
        raise ValueError("the stereo samples reach slot %d and the mono ones come down to slot %d: %d slots too many" % (
            end - 1, low, end - low))
    room = MAX_SLOTS - first + 1
    if end - first > room:
        raise ValueError("these need %d slots and there are %d from slot %d on: room for %d stereo samples or %d mono" % (
            end - first, room, first, (MAX_SLOTS - first + first % 2) // 2, room))
    frames = sum(len(data) for _, _, pieces in jobs for _, data in pieces)
    if limit > MAX_SECONDS and frames > pool:
        raise ValueError("this set is %s of mono in all and the unit loads %s at boot, whatever the slots hold" % (
            clock(frames / RATE), clock(pool / RATE)))
    return jobs


def place(jobs, first=1, pack=False):
    """-> [(slot, stem, stereo, pieces)]: the slot of each file's first piece, counted from 1.
    A stereo file starts on an odd slot; the slot before it is left empty if it has to be.
    pack: for the pack image (
    ). The
    stereo files as before; the mono ones from slot 64 down, the first file given in the highest slots."""
    out, slot, top = [], first, MAX_SLOTS
    for stem, stereo, pieces in jobs:
        if pack and not stereo:
            top -= len(pieces)
            out.append((top + 1, stem, stereo, pieces))
            continue
        if stereo and slot % 2 == 0:
            slot += 1
        out.append((slot, stem, stereo, pieces))
        slot += len(pieces)
    return out


def layout(jobs, first=1, pack=False):
    """-> rows (first slot, slots, name, seconds, MODE, SMPL), one per sample, in slot order. SMPL is the
    number to dial in: the slot for a mono sample, the stereo sample's number for a pair."""
    rows = []
    for slot, stem, stereo, pieces in sorted(place(jobs, first, pack), key=lambda job: job[0]):
        step = 2 if stereo else 1
        count = len(pieces) // step
        for k in range(count):
            name = stem + (" %d/%d" % (k + 1, count) if count > 1 else "")
            rows.append((slot, step, name, len(pieces[k * step][1]) / RATE, mode_hint(stereo)[0],
                         (slot + 1) // 2 if stereo else slot))
            slot += step
    return rows


def sheet(rows, big=False, pool=BIG_POOL_FRAMES, pack=False):
    """The slot list as text: what to dial in on the Syntakt."""
    used = sum(n for _, n, _, _, _, _ in rows)
    first, last = rows[0][0], rows[-1][0] + rows[-1][1] - 1
    out = ["slot   sample                            length  %s  SMPL" % ("    " if pack else "MODE")]
    for slot, n, name, seconds, mode, smpl in rows:
        where = "%2d-%-2d" % (slot, slot + 1) if n == 2 else "%2d   " % slot
        out.append("%s  %-32s %5.2f s  %s     %-3d%s" % (where, name, seconds, " " if pack else "%d" % mode, smpl,
                                                           " stereo" if n == 2 else " mono" if pack else ""))
    out.append("")
    out.append("%d slots used, %d to %d." % (used, first, last))
    if pack:
        out.append("Pack image only: the stereo samples from slot %d up, the mono ones from slot %d down, and %d left between." % (
            first, MAX_SLOTS, last - first + 1 - used))
        out.append("Each file name starts with its slot number. In Transfer, check each file sits in that slot.")
        out.append("Turn SMPL to the number listed. 1 to 32 are the stereo samples (number n is slots 2n-1 and 2n), 33 to 64")
        out.append("the single slots of those numbers, each a mono sample. There is no MODE to set for playing.")
        out.append("A mono file here is an odd number of frames and a stereo one an even number, its last frame left out where")
        out.append("it has to be: on the stops image that is what says which a slot holds, and SMPL stops only at samples.")
        out.append("LOOP: OFF, FWD, PING.")
        return "\n".join(out) + "\n"
    if last - first + 1 > used:
        out.append("%d left empty in between, so that every stereo sample starts on an odd slot." % (last - first + 1 - used))
    out.append("Each file name starts with its slot number. In Transfer, check each file sits in that slot.")
    out.append("MODE: 0 mono, 1 stereo. LOOP: 0 off, 1 loop, 2 ping-pong.")
    if big:
        out.append("Big image only: samples of up to %g s. Send them with build/Transfer10s.app; Elektron's own" % BIG_SECONDS)
        out.append("Transfer cuts at 5 s. At boot the unit loads %s of mono in all (%s of stereo), the slots" % (
            clock(pool / RATE), clock(pool / RATE / 2)))
        out.append("in order; a sample that no longer fits stays on the drive and is silent.")
    if any(n == 2 for _, n, _, _, _, _ in rows):
        out.append("Stereo: MODE 1, and SMPL as listed. In stereo SMPL counts stereo samples: number n is slots 2n-1 and 2n.")
        out.append("The next track is the right channel.")
        out.append("Audio-only image: MODE is the SMP2 knob and reads 64 less (1 shows as -63, 0 as -64), LOOP is TUN2")
        out.append("(0 off, +1 loop, +2 ping-pong); pan this track hard left and the next hard right, same volume and")
        out.append("sends. The full image does that itself.")
    return "\n".join(out) + "\n"


def prepare(outdir):
    """An output folder is empty, or one of ours: then its numbered files are replaced."""
    if not os.path.isdir(outdir) or not [f for f in os.listdir(outdir) if not f.startswith(".")]:
        os.makedirs(outdir, exist_ok=True)
    elif not os.path.exists(os.path.join(outdir, MARKER)):
        raise ValueError("%s is not empty and was not made by this tool: empty it or pick another --out" % outdir)
    else:
        for f in os.listdir(outdir):
            if re.fullmatch(r"\d\d_.*\.wav", f):
                os.remove(os.path.join(outdir, f))
    open(os.path.join(outdir, MARKER), "w").close()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("input", nargs="+", help="audio files, or folders of them")
    ap.add_argument("--out", help="output folder (default build/samples/<name of the first input>)")
    ap.add_argument("--first", type=int, default=1, help="slot the first file goes in (default 1)")
    ap.add_argument("--chunk", type=float, help="longest piece in seconds (default and limit 5, or 10 with --big)")
    ap.add_argument("--big", action="store_true", help="for a unit with the big image: slots of up to 10 seconds")
    ap.add_argument("--double", action="store_true", help="for a unit with the double image: as --big, and twice as much loads at boot")
    ap.add_argument("--mono", action="store_true", help="mix stereo files down to mono")
    ap.add_argument("--pack", action="store_true", help="for a unit with the pack image: mono samples in the single slots, from 64 down")
    a = ap.parse_args(argv)

    files = inputs(a.input)
    if not files:
        raise SystemExit("no audio files in %s" % ", ".join(a.input))
    name = os.path.splitext(os.path.basename(os.path.normpath(a.input[0])))[0].replace(" ", "_")
    outdir = a.out or os.path.join("build", "samples", name)
    if any(os.path.isdir(p) and os.path.abspath(p) == os.path.abspath(outdir) for p in a.input):
        outdir += "_syntakt"                          # never write the pieces in among the sources
    try:
        pool = DOUBLE_POOL_FRAMES if a.double else BIG_POOL_FRAMES
        big = a.big or a.double
        jobs = convert(files, a.chunk, a.mono, a.first, BIG_SECONDS if big else MAX_SECONDS, pool, a.pack)
        prepare(outdir)
    except ValueError as err:
        raise SystemExit(str(err))

    count = 0
    for slot, stem, _, pieces in place(jobs, a.first, a.pack):
        write(pieces, stem, outdir, slot)
        count += len(pieces)
    text = sheet(layout(jobs, a.first, a.pack), big, pool, a.pack)
    with open(os.path.normpath(outdir) + "_slots.txt", "w") as f:
        f.write(text)
    print(text, end="")
    print("wrote %d files to %s" % (count, outdir))


if __name__ == "__main__":
    main(sys.argv[1:])
