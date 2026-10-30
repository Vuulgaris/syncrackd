"""Seal the stock bytes written in our source, so the repository holds none of Elektron's.

    python -m tools.seal tools/build_main.py tests/test_x.py ...   # rewrite in place
    python -m tools.seal --check FILE...                           # list what would be sealed, change nothing
    python -m tools.seal --show TOKEN                              # the hex a sealed run opens to

A hex string or bytes literal of 4 bytes or more whose bytes are found in the official sections 3 or 7 becomes
fw.sx("...") or fw.sb("..."), which opens to the same value with the official file's key (tools/fw.py). Shorter
runs (one instruction) and plain ASCII (magic words) are left as they are. The container, SysEx and file
protocol modules (ele3, syx, rpc) and the EMAC encoding tests hold facts of a format, not code: not sealed.
Needs the official file, as every build does.
"""
import ast
import re
import sys

from . import fw

HEX = re.compile(r"^(?:[0-9a-f]{2})+$")
MIN = 4


def _stock():
    from tests.conftest import _official_path
    img = fw.load(_official_path())
    return img.section(3) + b"\0" * 64 + img.section(7)


def _finds(src, stock):
    tree = ast.parse(src)
    skip = {id(v) for n in ast.walk(tree) if isinstance(n, ast.JoinedStr) for v in n.values}
    out = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Constant) or id(n) in skip:
            continue
        v = n.value
        if isinstance(v, str) and HEX.match(v) and len(v) != 64 and re.search(r"\d", v):
            data, fn = bytes.fromhex(v), "sx"
        elif isinstance(v, bytes):
            data, fn = v, "sb"
        else:
            continue
        if len(data) >= MIN and len(set(data)) > 1 and not (data.isascii() and data.decode().isprintable()) and data in stock:
            out.append((n, fn, data))
    return tree, out


def _binds_fw(tree):
    for n in tree.body:
        if isinstance(n, (ast.Import, ast.ImportFrom)) and any((a.asname or a.name) == "fw" for a in n.names):
            return True
    return False


def rewrite(path, stock, check=False):
    with open(path) as f:
        src = f.read()
    tree, finds = _finds(src, stock)
    if check or not finds:
        return len(finds)
    lines = src.splitlines(keepends=True)
    starts = [0]
    for ln in lines:
        starts.append(starts[-1] + len(ln))

    def at(line, col):
        return starts[line - 1] + len(lines[line - 1].encode()[:col].decode())

    edits = [(at(n.lineno, n.col_offset), at(n.end_lineno, n.end_col_offset), 'fw.%s("%s")' % (fn, fw.seal(data)))
             for n, fn, data in finds]
    if not _binds_fw(tree):
        block = []
        for n in tree.body[1 if ast.get_docstring(tree) is not None else 0:]:
            if not isinstance(n, (ast.Import, ast.ImportFrom)):
                break
            block.append(n)
        cut = starts[block[-1].end_lineno] if block else 0
        edits.append((cut, cut, "from tools import fw\n"))
    for a, b, text in sorted(edits, reverse=True):
        src = src[:a] + text + src[b:]
    with open(path, "w") as f:
        f.write(src)
    return len(finds)


def main(argv):
    if argv[:1] == ["--show"]:
        print(fw.sx(argv[1]))
        return 0
    check = argv[:1] == ["--check"]
    stock = _stock()
    total = 0
    for p in argv[1:] if check else argv:
        n = rewrite(p, stock, check)
        if n:
            print("%4d  %s" % (n, p))
        total += n
    print("%d %s" % (total, "to seal" if check else "sealed"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
