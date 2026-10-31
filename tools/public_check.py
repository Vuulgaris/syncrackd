"""The public repository's guard: fails on anything that must never be published. Needs no firmware.

    python -m tools.public_check              # the files git tracks here
    python -m tools.public_check DIR          # every file under DIR (an export, tools/export_public.py)

Fails on: firmware, audio, projects and listings by name; the folders that hold them; a home folder's path; an em
dash; a hex run of 32 characters or more that is not a SHA-256 or a sealed run (fw.sx, fw.sb). A maintainer may keep
more patterns of their own in tools/private_check.py (FAIL, a list like the one here, and WARN, a pattern to count):
that file is never published.
"""
import os
import re
import subprocess
import sys

BAD_EXT = (".syx", ".bin", ".wav", ".aif", ".aiff", ".stprj", ".lst", ".elf", ".o", ".map")
BAD_DIRS = ("firmware/", "sections/", "build/", "ref/", "pascalproject/", "profiler/", "samples/")
FAIL = [
    ("a home folder's path", re.compile(r"/Users/[A-Za-z]|~/(?:Library|Documents)/|Mobile Docu[m]ents")),
    ("an em dash", re.compile("\u2014")),
]
HEXRUN = re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{32,}(?![0-9A-Fa-f])")
SEALED = re.compile(r'fw\.s[xb]\("[0-9a-f]+"\)')
WARN = IGNORE = None
try:
    from . import private_check
    FAIL = FAIL + private_check.FAIL
    WARN, IGNORE = private_check.WARN, getattr(private_check, "IGNORE", None)
except ImportError:
    pass
TEXT = (".py", ".md", ".c", ".h", ".S", ".s", ".txt", ".html", ".json", ".yml", ".yaml", ".toml", ".cfg", "Makefile",
        ".gitignore", ".gitmodules", ".sh")


def files(root):
    if root is None:
        out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True).stdout.split("\n")
        return [(p, p) for p in out if p]
    found = []
    for d, dirs, names in os.walk(root):
        dirs[:] = [x for x in dirs if x != ".git"]
        for n in names:
            p = os.path.join(d, n)
            found.append((os.path.relpath(p, root).replace(os.sep, "/"), p))
    return sorted(found)


def check(root=None):
    fails, warns = [], []
    for rel, path in files(root):
        if rel.lower().endswith(BAD_EXT) or rel.startswith(BAD_DIRS):
            fails.append((rel, 0, "a file that is never published"))
            continue
        if not rel.endswith(TEXT) or os.path.islink(path):
            continue
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.read().split("\n")
        n_warn = 0
        for i, line in enumerate(lines, 1):
            for what, rx in FAIL:
                if rx.search(line):
                    fails.append((rel, i, what))
            for m in HEXRUN.finditer(SEALED.sub("", line)):
                if len(m.group(0)) != 64:
                    fails.append((rel, i, "a hex run of %d characters" % len(m.group(0))))
            n_warn += len(WARN.findall(line)) if WARN and not (IGNORE and IGNORE.search(line)) else 0
        if n_warn:
            warns.append((rel, n_warn))
    return fails, warns


def main(argv):
    fails, warns = check(argv[0] if argv else None)
    for rel, n in warns:
        print("warn  %4d  %s: to reword" % (n, rel))
    for rel, i, what in fails:
        print("FAIL  %s:%d: %s" % (rel, i, what))
    print("%d failures, %d files to reword" % (len(fails), len(warns)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
