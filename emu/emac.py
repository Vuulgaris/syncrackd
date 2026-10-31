"""ColdFire EMAC, the part the Syntakt audio engine uses.

Unicorn's own EMAC multiplies unsigned in signed fractional mode, which is the mode this engine runs in, so every EMAC
instruction is executed here.

Source: ColdFire Family Programmer's Reference Manual rev 3, chapter 6 (instruction formats, MOVCLR and MOVE from ACC
pseudocode, MOVE to ACC text).

Supported: signed fractional mode (MACSR F/I = 1, S/U = 0, R/T = 0), longword MAC and MSAC with and without load, MOVE
to and from ACC, MOVCLR, MOVE to and from MACSR. Anything else raises: section 7 code never does it, and an unverified
mode must not run silently.

Accumulator in fractional mode, 48 bits: [47:40] extension, [39:8] the 32-bit value (Q31), [7:0] extra fraction. Kept
here as a signed Python int.
"""
from dataclasses import dataclass

OMC, SU, FI, RT = 0x80, 0x40, 0x20, 0x10
N, Z, V, EV = 0x8, 0x4, 0x2, 0x1
PAV0 = 0x100

ACC_MIN, ACC_MAX = -(1 << 47), (1 << 47) - 1


def s32(v):
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v & 0x80000000 else v


class Emac:
    def __init__(self):
        self.acc = [0, 0, 0, 0]
        self.macsr = 0
        self.overflows = 0  # 48-bit accumulation overflows seen

    def _need_fractional(self):
        if (self.macsr & (FI | SU | RT)) != FI:
            raise NotImplementedError("EMAC mode MACSR=%#x is not modelled" % self.macsr)

    def _flags(self, n):
        a = self.acc[n]
        f = self.macsr & ~(N | Z | V | EV)
        if a < 0:
            f |= N
        if a == 0:
            f |= Z
        if not -(1 << 39) <= a < (1 << 39):
            f |= EV
        if f & (PAV0 << n):
            f |= V
        self.macsr = f

    def mac(self, n, x, y, sub=False):
        """ACCn +/- x * y, 32-bit signed fractions."""
        self._need_fractional()
        pav = PAV0 << n
        if self.macsr & OMC and self.macsr & pav:
            self.macsr |= V  # a saturated accumulator ignores MAC
            return
        # Q31 * Q31 << 1 is Q63; the accumulator takes the top 40 bits, truncated. -1 * -1 gives exactly +1.0 (2**39).
        p = (s32(x) * s32(y)) >> 23
        r = self.acc[n] - p if sub else self.acc[n] + p
        if not ACC_MIN <= r <= ACC_MAX:
            # Constants from memory of the device manual, not from the chapter cited above. `overflows` lets callers
            # prove this path never ran.
            self.overflows += 1
            self.macsr |= pav
            if self.macsr & OMC:
                r = 0x007FFFFFFF00 if r > 0 else -0x008000000000
            else:
                r = ((r - ACC_MIN) % (1 << 48)) + ACC_MIN
        self.acc[n] = r
        self._flags(n)

    def load(self, n, value):
        """MOVE.L Ry,ACCn."""
        self._need_fractional()
        self.acc[n] = s32(value) << 8
        self.macsr &= ~(PAV0 << n)
        self._flags(n)

    def store(self, n, clear=False):
        """MOVE.L ACCn,Rx or MOVCLR.L ACCn,Rx. Returns the 32-bit value."""
        self._need_fractional()
        a = self.acc[n]
        v = (a >> 8) & 0xFFFFFFFF
        if self.macsr & OMC:
            top = a >> 39  # ACC[47:39] must be all 0 or all 1
            if top not in (0, -1):
                v = 0x7FFFFFFF if a >= 0 else 0x80000000
        if clear:
            self.acc[n] = 0
            self.macsr &= ~(PAV0 << n)
        return v


@dataclass(frozen=True)
class Insn:
    kind: str  # mac, load, store, to_macsr, from_macsr
    size: int  # bytes
    acc: int = 0
    rx: int = 0  # register numbers: 0..7 = D0..D7, 8..15 = A0..A7
    ry: int = 0
    rw: int = 0
    sub: bool = False
    clear: bool = False
    mem: tuple = None  # (mode, areg, d16) for MAC with load
    src: tuple = None  # ("reg", n) or ("imm", value)


def _src(op, tail):
    mode, reg = (op >> 3) & 7, op & 7
    if mode == 0:
        return ("reg", reg), 2
    if mode == 1:
        return ("reg", 8 + reg), 2
    if mode == 7 and reg == 4:
        return ("imm", int.from_bytes(tail[:4], "big")), 6
    raise NotImplementedError("EMAC source ea %d/%d" % (mode, reg))


def decode(code):
    """Decode the instruction at code[0:]. None if it is not EMAC (MOV3Q)."""
    op = int.from_bytes(code[0:2], "big")
    if op >> 12 != 0xA:
        return None
    if (op & 0xF1C0) == 0xA140:
        return None  # MOV3Q
    if op & 0x0100:
        if (op & 0xF9F0) in (0xA180, 0xA1C0):
            return Insn("store", 2, acc=(op >> 9) & 3, rx=op & 0xF, clear=bool(op & 0x40))
        if (op & 0xF9C0) == 0xA100:
            src, size = _src(op, code[2:])
            return Insn("load", size, acc=(op >> 9) & 3, src=src)
        if (op & 0xFFC0) == 0xA900:
            src, size = _src(op, code[2:])
            return Insn("to_macsr", size, src=src)
        if (op & 0xFFF0) == 0xA980:
            return Insn("from_macsr", 2, rx=op & 0xF)
        raise NotImplementedError("EMAC opcode %04x" % op)
    ext = int.from_bytes(code[2:4], "big")
    if not ext & 0x0800:
        raise NotImplementedError("word-size MAC %04x %04x" % (op, ext))
    reg = ((op >> 6) & 1) << 3 | (op >> 9) & 7
    sub = bool(ext & 0x0100)
    mode = (op >> 3) & 7
    if mode in (0, 1):  # no load
        if ext & 0x0003:
            raise NotImplementedError("dual-accumulator MAC %04x %04x" % (op, ext))
        acc = ((ext >> 4) & 1) << 1 | (op >> 7) & 1
        return Insn("mac", 4, acc=acc, rx=reg, ry=op & 0xF, sub=sub)
    if mode not in (2, 3, 4, 5):
        raise NotImplementedError("MAC ea mode %d" % mode)
    if ext & 0x0020:
        raise NotImplementedError("MAC with MASK %04x %04x" % (op, ext))
    acc = ((ext >> 4) & 1) << 1 | (~op >> 7) & 1  # lsb is stored inverted
    d16 = int.from_bytes(code[4:6], "big", signed=True) if mode == 5 else 0
    return Insn("mac", 6 if mode == 5 else 4, acc=acc, rx=ext >> 12, ry=ext & 0xF,
                rw=reg, sub=sub, mem=(mode, op & 7, d16))


REG_NAMES = ["%d" + str(i) for i in range(8)] + ["%a" + str(i) for i in range(6)] + ["%fp", "%sp"]


def text(i):
    """Render like objdump, for cross-checking the decoder."""
    r = REG_NAMES
    if i.kind == "mac":
        name = "msacl" if i.sub else "macl"
        if i.mem is None:
            return "%s %s,%s,%%acc%d" % (name, r[i.ry], r[i.rx], i.acc)
        mode, a, d = i.mem
        ea = {2: "%s@", 3: "%s@+", 4: "%s@-"}.get(mode, "%s@(" + str(d) + ")") % r[8 + a]
        return "%s %s,%s,%s,%s,%%acc%d" % (name, r[i.ry], r[i.rx], ea, r[i.rw], i.acc)
    if i.kind == "store":
        return "%s %%acc%d,%s" % ("movclrl" if i.clear else "movel", i.acc, r[i.rx])
    s = r[i.src[1]] if i.src and i.src[0] == "reg" else None
    if i.kind == "load":
        return "movel %s,%%acc%d" % (s or "#%d" % s32(i.src[1]), i.acc)
    if i.kind == "to_macsr":
        return "movel %s,%%macsr" % (s or "#%d" % s32(i.src[1]))
    return "movel %%macsr,%s" % r[i.rx]
