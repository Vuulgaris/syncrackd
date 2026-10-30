"""Find code that nothing in a decoded section can reach: the room there is for patches.

    python -m tools.deadcode 3          # main CPU program, OS 1.42
    python -m tools.deadcode 7          # audio CPU program

Static evidence only. The code is cut into pieces at every rts and rte, and a piece is
live when something that is itself live names an address inside it:
  - an address in the operand of a decoded instruction (calls, branches, lea, pea);
  - any 32-bit value at an even offset of the image (pointer tables, immediates,
    literal pools, absolute calls), wherever it sits; past the code, at odd offsets
    too, in case a table is packed;
  - a branch, call, lea or pea with a 16 or 32-bit pc-relative reach read at every
    even offset, decoded or not, so that a listing knocked out of step by data in
    the code cannot hide one;
  - the 16-bit entries of a switch table.
Everything named from outside the code (data, and the other sections of the file) is a
root, and so is everything before the entry point. What no root reaches is reported.

Each of these errs towards calling code live. What it cannot see: an address worked
out by arithmetic at run time. Neither program does that for calls as far as the
listing shows (indirect calls load whole pointers), but nothing here proves it.
"""
import bisect
import os
import re
import sys
import tempfile

import numpy as np

from tools import disasm

LINE = re.compile(r"\s*([0-9a-f]+):\t([0-9a-f ]+?)\s*\t(.*)")
HEX = re.compile(r"0x([0-9a-f]{8})\b")
TABLE = re.compile(r"jmp %pc@\(0x([0-9a-f]{8}),%d[0-7]")
# pc-relative with a 16-bit reach: jsr, jmp, pea, lea (8 registers), and a 16 or 32-bit branch
PC16 = (0x4eba, 0x4efa, 0x487a) + tuple(0x41fa | n << 9 for n in range(8))


def listing(code, base):
    """[(address, text)] for a block of code, by objdump."""
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
        f.write(code)
    try:
        text = disasm.disasm(f.name, base)
    finally:
        os.unlink(f.name)
    out = []
    for line in text.splitlines():
        m = LINE.match(line)
        if m:
            out.append((int(m.group(1), 16), m.group(3)))
    return out


def _values(image, base, shifts=(0, 2)):
    """(source address, value) for every 32-bit value at an even offset (or at the offsets asked for)."""
    n = (len(image) - 4) // 4 * 4
    for shift in shifts:
        v = np.frombuffer(image[shift:shift + n], dtype=">u4")
        yield base + shift + 4 * np.arange(len(v), dtype=np.int64), v.astype(np.int64)


def _reaches(image, base):
    """(source, target) of every word that could be a far pc-relative branch, call, lea or pea."""
    w = np.frombuffer(image[:len(image) // 2 * 2], dtype=">u2").astype(np.int64)
    at = base + 2 * np.arange(len(w), dtype=np.int64)
    d16 = np.zeros(len(w), dtype=np.int64)
    d16[:-1] = np.frombuffer(image[2:len(w) * 2], dtype=">i2")
    d32 = np.zeros(len(w), dtype=np.int64)
    d32[:-2] = (w[1:-1] << 16 | w[2:])
    d32 = (d32 ^ 0x80000000) - 0x80000000
    branch = (w >> 12) == 6
    far16 = np.isin(w, PC16) | (branch & (w & 0xff == 0))
    far32 = branch & (w & 0xff == 0xff)
    return np.concatenate([at[far16], at[far32]]), np.concatenate([(at + 2 + d16)[far16], (at + 2 + d32)[far32]])


def survey(image, base, code_end, entry, others=()):
    """Pieces of [base, code_end) that no root reaches.

    others: the file's other sections, whose 32-bit values count as roots too.
    Returns [(start, end, named, clean)]: runs of unreached pieces that lie next to each
    other. named = how many times something outside the run (unreached itself) names an
    address inside it. clean = every word of the run decodes as an instruction.
    """
    ins = listing(image[:code_end - base], base)
    starts = [base] + [ins[k + 1][0] for k in range(len(ins) - 1) if ins[k][1].startswith(("rts", "rte"))]
    n = len(starts)

    def piece(a):
        return bisect.bisect_right(starts, a) - 1

    src, dst = [], []
    for a, text in ins:
        for x in HEX.findall(text):
            src.append(a)
            dst.append(int(x, 16))
        t = TABLE.match(text)
        if t:                                   # a switch: 16-bit offsets from the table's own address
            tb = int(t.group(1), 16)
            for k in range(1024):
                o = tb - base + 2 * k
                target = tb + int.from_bytes(image[o:o + 2], "big", signed=True)
                if not tb - 0x4000 <= target < tb + 0x8000 or target & 1:
                    break
                src.append(a)
                dst.append(target)
    src, dst = [np.array(src, dtype=np.int64)], [np.array(dst, dtype=np.int64)]
    for s, v in _values(image, base):
        src.append(s)
        dst.append(v)
    for s, v in _values(image, base, (1, 3)):   # a packed table would sit past the code
        src.append(s[s >= code_end])
        dst.append(v[s >= code_end])
    s, v = _reaches(image, base)
    src.append(s)
    dst.append(v)
    src, dst = np.concatenate(src), np.concatenate(dst)
    keep = (dst >= base) & (dst < code_end) & (dst % 2 == 0)
    src, dst = src[keep], dst[keep]

    st = np.array(starts, dtype=np.int64)
    to = np.searchsorted(st, dst, side="right") - 1
    in_code = src < code_end
    frm = np.where(in_code, np.searchsorted(st, src, side="right") - 1, -1)

    live = np.zeros(n, dtype=bool)
    live[:piece(entry) + 1] = True              # the vectors and stubs before the entry, and the entry
    live[to[~in_code]] = True                   # named from data
    for sec in others:
        for _, v in _values(sec, 0, range(4)):
            v = v[(v >= base) & (v < code_end) & (v % 2 == 0)]
            live[np.searchsorted(st, v, side="right") - 1] = True
    edges = {}
    for f, t in zip(frm[in_code].tolist(), to[in_code].tolist()):
        if f != t:
            edges.setdefault(f, set()).add(t)
    stack = list(np.nonzero(live)[0])
    while stack:
        for t in edges.get(stack.pop(), ()):
            if not live[t]:
                live[t] = True
                stack.append(t)

    ends = starts[1:] + [code_end]
    where = [a for a, _ in ins]
    runs, k = [], 0
    while k < n:
        if live[k]:
            k += 1
            continue
        j = k
        while j < n and not live[j]:
            j += 1
        lo, hi = starts[k], ends[j - 1]
        named = int(np.count_nonzero((dst >= lo) & (dst < hi) & ((src < lo) | (src >= hi))))
        a, b = bisect.bisect_left(where, lo), bisect.bisect_left(where, hi)
        runs.append((lo, hi, named, not any(t.startswith(".short") for _, t in ins[a:b])))
        k = j
    return runs


def usable(runs, least=256):
    """The runs a patch could sit in: named by nothing, every word an instruction, at least `least` bytes."""
    return [(lo, hi) for lo, hi, named, clean in runs if not named and clean and hi - lo >= least]


def main(argv):
    from tools import audiomap, fw, mainmap
    import glob
    import hashlib
    number = int(argv[0]) if argv else 3
    path = next(p for p in sorted(glob.glob(os.path.join("firmware", "**", "*.syx"), recursive=True))
                if hashlib.sha256(open(p, "rb").read()).hexdigest() in fw.KNOWN)
    official = fw.load(path)
    image = official.section(number)
    if number == 3:
        base, code_end, entry = mainmap.BASE, mainmap.CODE_END, mainmap.ENTRY
        others = [official.section(k) for k in (2, 4, 6, 8)]
    else:
        base, code_end, entry, others = audiomap.BASE, audiomap.CODE_END, audiomap.ENTRY, []
    runs = survey(image, base, code_end, entry, others)
    for lo, hi, named, clean in runs:
        print("%#x..%#x  %5d bytes  %s%s" % (lo, hi, hi - lo, "named by other unreached code" if named else "named by nothing",
                                             "" if clean else ", holds words that are not instructions"))
    print("%d runs, %d bytes unreached" % (len(runs), sum(r[1] - r[0] for r in runs)))
    for least in (64, 256, 512, 1024):
        u = usable(runs, least)
        print("usable, %4d bytes and up: %3d runs, %5d bytes" % (least, len(u), sum(hi - lo for lo, hi in u)))


if __name__ == "__main__":
    main(sys.argv[1:])
