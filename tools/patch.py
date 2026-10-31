"""Make the modded OS from Elektron's own file. Python 3.11 or later, the standard library alone.

python -m tools.patch Syntakt_OS1.42.syx stream.json
python -m tools.patch Syntakt_OS1.42.syx stream.json -o somewhere/mod.syx

It takes only the exact official file (its SHA-256, and every section's), puts the bundle's bytes in where the
official bytes under them, a section's all in order, hash as the bundle says, packs the file, decodes it again and
checks that it differs from the official one only inside the bundle's runs, and that its SHA-256 is the release's.
Anything off, and nothing is written.
"""
import argparse
import json
import os
import sys

from . import fw

FORMAT = 1


def apply(official, bundle):
    if bundle.get("format") != FORMAT:
        raise fw.GuardError("bundle format %r, this patcher reads %d" % (bundle.get("format"), FORMAT))
    if fw.sha256(official.raw) != bundle["input"]:
        raise fw.GuardError("this bundle is for another file: %s" % bundle["input"])
    new, regions = {}, {}
    for key, s in bundle["sections"].items():
        sid = int(key)
        old = official.section(sid)
        if s["length"] < len(old):
            raise fw.GuardError("section %d: the bundle would shrink it" % sid)
        buf = bytearray(old + bytes(s["length"] - len(old)))
        if s["length"] > len(old):
            regions.setdefault(sid, []).append((len(old), s["length"]))  # a grown section's tail is ours, zeros too
        under = []
        for r in s["runs"]:
            data, at = bytes.fromhex(r["new"]), r["at"]
            if at < 0 or at + len(data) > len(buf):
                raise fw.GuardError("section %d: a run at %#x is out of range" % (sid, at))
            under.append(bytes(buf[at:at + len(data)]))
            buf[at:at + len(data)] = data
            regions.setdefault(sid, []).append((at, at + len(data)))
        if fw.sha256(b"".join(under)) != s["stock"]:
            raise fw.GuardError("section %d: not the bytes the bundle expects under its runs" % sid)
        new[sid] = bytes(buf)
    raw = official.build(new)
    fw.verify(official, raw, regions)
    out = fw.Image(raw)
    for sid in official.ids:
        if out.section(sid) != new.get(sid, official.section(sid)):
            raise fw.GuardError("section %d did not come back as patched" % sid)
    if fw.sha256(raw) != bundle["output"]:
        raise fw.GuardError("the result is not the release's build: %s" % fw.sha256(raw))
    return raw


def main(argv, bundle=None, prog=None):
    """bundle given: the single-file patcher's own (tools/single.py), and no bundle argument."""
    ap = argparse.ArgumentParser(prog=prog, description=__doc__.split("\n")[0])
    ap.add_argument("official", help="Syntakt OS 1.42 .syx, from Elektron")
    if bundle is None:
        ap.add_argument("bundle", help="the release's .json")
    ap.add_argument("-o", "--out")
    a = ap.parse_args(argv)
    if bundle is None:
        with open(a.bundle) as f:
            bundle = json.load(f)
    try:
        official = fw.load(a.official)
        raw = apply(official, bundle)
    except fw.GuardError as e:
        print("refused: %s. Nothing written." % e)
        return 1
    out = a.out or os.path.splitext(a.official)[0] + "_syncrackd_%s.syx" % bundle["image"]
    if os.path.abspath(out) == os.path.abspath(a.official):
        print("refused: the output would overwrite Elektron's file. Nothing written.")
        return 1
    with open(out, "wb") as f:
        f.write(raw)
    print("%s\n  %s\n  SHA-256 %s\nCompare that hash with the release notes before you flash. Back up your +Drive first."
          % (out, bundle.get("what") or bundle["image"], fw.sha256(raw)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
