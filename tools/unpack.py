"""Unpack a pinned official Syntakt OS file into sections/<version>/.

    python -m tools.unpack firmware/path/to/Syntakt_OSx.yz.syx

Output is Elektron code: sections/ is gitignored, keep it that way.
"""
import os
import sys

from . import fw


def main(path):
    img = fw.load(path)
    out = os.path.join("sections", img.version)
    os.makedirs(out, exist_ok=True)
    print("Syntakt OS %s  %s" % (img.version, fw.sha256(img.raw)))
    for s in img.container.sections:
        data = img.section(s.id)
        name = "sec%d_%s.bin" % (s.id, fw.NAMES.get(s.id, "unknown"))
        with open(os.path.join(out, name), "wb") as f:
            f.write(data)
        print("  id %d %-9s dest %#010x stored %8d %s decoded %8d  %s" % (
            s.id, fw.NAMES.get(s.id, "?"), s.dest, s.size,
            "aplib" if s.compressed else "raw  ", len(data), fw.sha256(data)[:16]))


if __name__ == "__main__":
    main(sys.argv[1])
