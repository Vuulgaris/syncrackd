"""The main CPU's knob display table, read out of its start-up code. **OS 1.42 only.**

How a knob's value is shown is not in the descriptor records (tools/params.py).
A start-up routine (mainmap.UI_INIT) first builds about 170 small function
objects, then fills a table in RAM with one 84-byte entry per descriptor record:

    +0x00 flags   +0x04 16 bytes of knob behaviour, copied from a template
    +0x14 text    +0x24 graphic    +0x34 (not named)    +0x44 FUNC+turn step

The last four are copies of function objects. This module reads the routine as
straight-line code (objdump listing, constant registers, the outgoing argument
stack) and returns the table without running anything.

Entry k belongs to record k of the array at mainmap.UI_RECORDS; the accessor at
mainmap.UI_ENTRY returns UI_TABLE + 84 * k for k < 505.
"""
import os
import re
import tempfile

from . import disasm
from . import mainmap as mm

M = 0xffffffff
FIELDS = {0x14: "text", 0x24: "graphic", 0x34: "f3", 0x44: "step"}
R = r"([ad]\d|fp)"
SCRATCH = ("d0", "d1", "a0", "a1")


def _listing(image):
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "sec3.bin")
        with open(path, "wb") as f:
            f.write(image)
        text = disasm.disasm(path, mm.BASE, mm.UI_INIT[0], mm.UI_INIT[1] + 2)
    out = []
    for line in text.split("\n"):
        parts = line.split("\t")
        if len(parts) >= 3 and parts[0].endswith(":"):
            out.append((int(parts[0][:-1], 16), parts[-1].strip()))
    return out


def walk(image):
    """-> (stores {address: (value or None, instruction address)},
           calls [(instruction address, target, [(argument, address of the push)], first first)])."""
    reg, stack, stores, calls = {}, [], {}, []

    def top(v, a):
        if stack:
            stack[-1] = (v, a)
        else:
            stack.append((v, a))

    for a, t in _listing(image):
        m = re.fullmatch(r"(?:movel|moveal|moveq|moveaw) #(-?\d+),%" + R, t)
        if m:
            reg[m.group(2)] = int(m.group(1)) & M
            continue
        m = re.fullmatch(r"move([bw]) #(-?\d+),%(d\d)", t)
        if m:
            keep = 0xffffff00 if m.group(1) == "b" else 0xffff0000
            old = reg.get(m.group(3))
            reg[m.group(3)] = None if old is None else (old & keep) | (int(m.group(2)) & ~keep & M)
            continue
        m = re.fullmatch(r"clrl %(d\d)", t)
        if m:
            reg[m.group(1)] = 0
            continue
        m = re.fullmatch(r"lea (?:%pc@\()?0x([0-9a-f]+)\)?,%" + R, t)
        if m:
            reg[m.group(2)] = int(m.group(1), 16)
            continue
        m = re.fullmatch(r"movea?l %" + R + ",%" + R, t)
        if m:
            reg[m.group(2)] = reg.get(m.group(1))
            continue
        m = re.fullmatch(r"movel %" + R + r",0x([0-9a-f]+)", t)
        if m:
            stores[int(m.group(2), 16)] = (reg.get(m.group(1)), a)
            continue
        m = re.fullmatch(r"movel #(-?\d+),0x([0-9a-f]+)", t)
        if m:
            stores[int(m.group(2), 16)] = (int(m.group(1)) & M, a)
            continue
        m = re.fullmatch(r"clrl 0x([0-9a-f]+)", t)
        if m:
            stores[int(m.group(1), 16)] = (0, a)
            continue
        m = re.fullmatch(r"movel #(-?\d+),%" + R + "@", t)
        if m:
            if reg.get(m.group(2)) is not None:
                stores[reg[m.group(2)]] = (int(m.group(1)) & M, a)
            continue
        m = re.fullmatch(r"clrl %" + R + "@", t)
        if m:
            if reg.get(m.group(1)) is not None:
                stores[reg[m.group(1)]] = (0, a)
            continue
        m = re.fullmatch(r"pea 0x([0-9a-f]+)", t)
        if m:
            stack.append((int(m.group(1), 16), a))
            continue
        m = re.fullmatch(r"movel %" + R + r",%sp@-", t)
        if m:
            stack.append((reg.get(m.group(1)), a))
            continue
        if t == "clrl %sp@-":
            stack.append((0, a))
            continue
        m = re.fullmatch(r"movel #(-?\d+),%sp@", t)
        if m:
            top(int(m.group(1)) & M, a)
            continue
        m = re.fullmatch(r"movel %" + R + r",%sp@", t)
        if m:
            top(reg.get(m.group(1)), a)
            continue
        if t == "clrl %sp@":
            top(0, a)
            continue
        m = re.fullmatch(r"lea %sp@\((\d+)\),%sp", t) or re.fullmatch(r"addql #(\d+),%sp", t)
        if m:
            n = min(int(m.group(1)) // 4, len(stack))
            del stack[len(stack) - n:]
            continue
        m = re.fullmatch(r"jsr %" + R + "@", t)
        k = re.fullmatch(r"jsr (?:%pc@\()?0x([0-9a-f]+)\)?", t)
        if m or k:
            target = reg.get(m.group(1)) if m else int(k.group(1), 16)
            calls.append((a, target, list(reversed(stack))))
            for r in SCRATCH:
                reg[r] = None
            continue
        m = re.search(r",%" + R + "$", t)                 # anything else that writes a register
        if m and not t.startswith(("cmp", "tst", "btst")):
            reg[m.group(1)] = None
    return stores, calls


def table(image):
    """-> list of mm.UI_COUNT dicts: flags, template, and per function field
    {"object": address of the function object copied in (None if built in place),
     "target": the function it calls, "site": address of the instruction that names the object,
     "copy": the routine that copies it}."""
    stores, calls = walk(image)
    end = mm.UI_TABLE + mm.UI_STRIDE * mm.UI_COUNT
    out = [{} for _ in range(mm.UI_COUNT)]

    def target(obj):
        v = stores.get(obj + 0xc) if obj is not None else None
        return v[0] if v else None

    for a, tgt, args in calls:
        if len(args) < 2 or args[0][0] is None or not mm.UI_TABLE <= args[0][0] < end:
            continue
        k, o = divmod(args[0][0] - mm.UI_TABLE, mm.UI_STRIDE)
        src, site = args[1]
        if o == 4:
            out[k]["template"] = src
        elif o in FIELDS:
            out[k][FIELDS[o]] = {"object": src, "target": target(src), "site": site, "copy": tgt}
    for addr, (v, a) in stores.items():
        if mm.UI_TABLE <= addr < end and (addr - mm.UI_TABLE) % mm.UI_STRIDE == 0:
            out[(addr - mm.UI_TABLE) // mm.UI_STRIDE]["flags"] = v
    return out


def pages(image):
    """-> {page number: {"name": address of its short name, "long": address of its long name,
    "knobs": the record behind each of the 8 knobs (0: none), "level": the LEVEL knob's record}}
    for -1 (the entry before the table: machine 44's own page) to mm.PAGE_COUNT - 1."""
    stores, calls = walk(image)
    first = mm.PAGE_TABLE - mm.PAGE_STRIDE
    end = mm.PAGE_TABLE + mm.PAGE_STRIDE * mm.PAGE_COUNT
    names = {args[0][0]: args[1][0] for _, _, args in calls
             if len(args) > 1 and args[0][0] is not None and first <= args[0][0] < end}
    out = {}
    for k in range(-1, mm.PAGE_COUNT):
        e = mm.PAGE_TABLE + mm.PAGE_STRIDE * k
        vals = [stores[e + 8 + 4 * i][0] for i in range(9)]            # KeyError: the routine is not what was read
        out[k] = {"name": names[e], "long": names[e + 4], "knobs": vals[:8], "level": vals[8]}
    return out
