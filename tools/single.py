"""The single-file patcher: one .py a release, the patcher, its container code and the bundle in it.

python -m tools.single stream          # build/bundle/stream.json -> build/dist/syncrackd_stream.py
python -m tools.single stream --bundle X.json -o Y.py
python -m tools.single stream --site   # and into site/ with its release.json, for the browser patcher

What the user runs: `python3 syncrackd_stream.py Syntakt_OS1.42.syx`. The bundle is checked for Elektron's code when
it is made (tools/bundle.py); nothing here adds any.
"""
import argparse
import base64
import json
import os
import sys
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TWEAKS = os.path.join(ROOT, "third_party", "elektron-model-tweaks")
MODULES = [
    ("mtlib.aplib", os.path.join(TWEAKS, "mtlib", "aplib.py")),
    ("syncrackd.syx", os.path.join(ROOT, "tools", "syx.py")),
    ("syncrackd.ele3", os.path.join(ROOT, "tools", "ele3.py")),
    ("syncrackd.fw", os.path.join(ROOT, "tools", "fw.py")),
    ("syncrackd.patch", os.path.join(ROOT, "tools", "patch.py")),
]
OUT = os.path.join("build", "dist")

HEAD = '''#!/usr/bin/env python3
"""SynCrackd, the %(image)s image: a sampler for the Elektron Syntakt, made from Elektron's own OS 1.42 file.

    python3 %(name)s Syntakt_OS1.42.syx
    python3 %(name)s Syntakt_OS1.42.syx -o somewhere/mod.syx

%(what)s

Python 3.9 or later, nothing to install. It takes only the exact official 1.42 file, puts the mod's bytes in,
checks the result differs from Elektron's file only where the mod goes, and that its SHA-256 is this release's:
%(output)s

Unofficial, not made or supported by Elektron. At your own risk, no warranty. Back up your +Drive with Transfer
before you flash. This file holds none of Elektron's firmware; the file it makes does, so do not share that one.
https://github.com/Vuulgaris/syncrackd

----
%(ours)s
----
The aplib codec in this file is from elektron-model-tweaks:

%(theirs)s"""
import base64
import json
import sys
import types
import zlib

_SOURCES = %(sources)s

_BUNDLE = """
%(bundle)s
"""


def _install():
    for pkg in ("syncrackd", "mtlib"):
        m = types.ModuleType(pkg)
        m.__path__ = []
        sys.modules[pkg] = m
    for full, src in _SOURCES:
        parent, _, short = full.rpartition(".")
        m = types.ModuleType(full)
        m.__package__, m.__file__ = parent, __file__
        sys.modules[full] = m
        exec(compile(src, "<%%s>" %% full, "exec"), m.__dict__)
        setattr(sys.modules[parent], short, m)
    return sys.modules["syncrackd.patch"]


if __name__ == "__main__":
    patch = _install()
    bundle = json.loads(zlib.decompress(base64.b85decode("".join(_BUNDLE.split()))))
    sys.exit(patch.main(sys.argv[1:], bundle, prog=%(prog)r))
'''


def make(bundle, name):
    def read(p):
        with open(p) as f:
            return f.read()
    packed = base64.b85encode(zlib.compress(json.dumps(bundle, separators=(",", ":")).encode(), 9)).decode()
    sources = "[\n" + "".join("    (%r, %r),\n" % (full, read(p)) for full, p in MODULES) + "]"
    text = HEAD % {
        "image": bundle["image"], "name": name, "prog": name, "output": bundle["output"],
        "what": bundle.get("what") or "The %s image." % bundle["image"],
        "ours": read(os.path.join(ROOT, "LICENSE")).strip(), "theirs": read(os.path.join(TWEAKS, "LICENSE")).strip(),
        "sources": sources, "bundle": "\n".join(packed[i:i + 100] for i in range(0, len(packed), 100)),
    }
    if "\u2014" in text:
        raise ValueError("an em dash in the single-file patcher")
    return text


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("image")
    ap.add_argument("--bundle", help="default: build/bundle/<image>.json")
    ap.add_argument("-o", "--out")
    ap.add_argument("--site", action="store_true", help="also into site/, the browser patcher's release")
    a = ap.parse_args(argv)
    with open(a.bundle or os.path.join("build", "bundle", "%s.json" % a.image)) as f:
        bundle = json.load(f)
    out = a.out or os.path.join(OUT, "syncrackd_%s.py" % a.image)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w") as f:
        f.write(make(bundle, os.path.basename(out)))
    os.chmod(out, 0o755)
    print("%s: %d KB, makes %s" % (out, os.path.getsize(out) // 1024, bundle["output"]))
    if a.site:
        site = os.path.join(ROOT, "site")
        name = os.path.basename(out)
        with open(os.path.join(site, name), "w") as f:
            f.write(make(bundle, name))
        with open(os.path.join(site, "release.json"), "w") as f:
            json.dump({"file": name, "image": bundle["image"], "output": bundle["output"],
                       "what": bundle.get("what") or "The %s image." % bundle["image"]}, f, indent=1)
            f.write("\n")
        print("site/%s and site/release.json" % name)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
