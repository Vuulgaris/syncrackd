"""The patch bundle a user's patcher applies: our bytes, where they go, and hashes. None of Elektron's bytes.

    python -m tools.bundle stream                          # build/images/..._stream.syx -> build/bundle/stream.json
    python -m tools.bundle stream --file X.syx --what "..."

The built image is compared with the official one section by section. Every run of bytes that differs becomes
{at, new: our bytes}; a section that grew is compared with the official one padded with zeros. The official
bytes under the runs are checked by one SHA-256 a section, all of them in order: a hash a run would give a run of
a few bytes away to anyone who tries them all. Runs are never joined across a byte that did not change: that byte is
Elektron's. Before the bundle is written, every 32-byte window of our bytes is looked for in the official
sections 3 and 7 (windows of four byte values or fewer, padding and NOP runs, not counted): one found is code
of theirs we carried, and the bundle is refused.
16 was tried first: it caught only idioms, 20 runs of 16 to 27 bytes on the stream image
(prologues and epilogues, NOP runs, calls to the same stock routines in stock's order, one 21-byte run on the
audio CPU at 0x400067e2 that reads like instructions moved aside at a hook).
"""
import argparse
import json
import os
import sys

from . import fw

FORMAT = 1
WINDOW = 32
IMAGES = os.path.join("build", "images")
OUT = os.path.join("build", "bundle")


def runs(old, new):
    out, i, n = [], 0, len(new)
    while i < n:
        if old[i] == new[i]:
            i += 1
            continue
        j = i
        while j < n and old[j] != new[j]:
            j += 1
        out.append((i, j))
        i = j
    return out


def stock_windows(official, sections):
    """Windows of our new bytes found in the official sections 3 and 7, as (section, at)."""
    ours = {}
    for sid, s in sections.items():
        for r in s["runs"]:
            new = bytes.fromhex(r["new"])
            for k in range(len(new) - WINDOW + 1):
                w = new[k:k + WINDOW]
                if len(set(w)) > 4:
                    ours.setdefault(w, (int(sid), r["at"] + k))
    found = []
    for sid in sorted(fw.PATCHABLE):
        text = official.section(sid)
        for k in range(len(text) - WINDOW + 1):
            hit = ours.get(text[k:k + WINDOW])
            if hit:
                found.append(hit)
    return sorted(set(found))


def make(official, built_raw, name, what=""):
    built = fw.Image(built_raw)
    for sid in official.ids:
        if sid not in fw.PATCHABLE and built.section(sid) != official.section(sid):
            raise fw.GuardError("section %d differs and is not patchable" % sid)
    sections = {}
    for sid in sorted(fw.PATCHABLE):
        a, b = official.section(sid), built.section(sid)
        if len(b) < len(a):
            raise fw.GuardError("section %d shrank" % sid)
        pad = a + bytes(len(b) - len(a))
        rr = runs(pad, b)
        if rr or len(b) != len(a):
            sections[str(sid)] = {"length": len(b), "stock": fw.sha256(b"".join(pad[s:e] for s, e in rr)),
                                  "runs": [{"at": s, "new": b[s:e].hex()} for s, e in rr]}
    bundle = {"format": FORMAT, "image": name, "what": what, "os": official.version,
              "input": fw.sha256(official.raw), "output": fw.sha256(built_raw), "sections": sections}
    found = stock_windows(official, sections)
    if found:
        raise fw.GuardError("%d windows of the bundle are Elektron's bytes, the first at section %d, %#x"
                            % (len(found), found[0][0], found[0][1]))
    return bundle


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("image")
    ap.add_argument("--file", help="the built .syx (default: build/images/Syntakt_OS1.42_sampler_<image>.syx)")
    ap.add_argument("--what", default="", help="one line for the user")
    ap.add_argument("-o", "--out")
    a = ap.parse_args(argv)
    from tests.conftest import _official_path
    official = fw.load(_official_path())
    path = a.file or os.path.join(IMAGES, "Syntakt_OS1.42_sampler_%s.syx" % a.image)
    with open(path, "rb") as f:
        bundle = make(official, f.read(), a.image, a.what)
    out = a.out or os.path.join(OUT, "%s.json" % a.image)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w") as f:
        json.dump(bundle, f, indent=1)
    n = sum(len(r["new"]) // 2 for s in bundle["sections"].values() for r in s["runs"])
    print("%s: %d runs, %d bytes of ours, output %s" % (out, sum(len(s["runs"]) for s in bundle["sections"].values()),
                                                       n, bundle["output"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
