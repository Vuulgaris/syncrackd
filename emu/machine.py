"""ColdFire machine on Unicorn, with EMAC executed outside Unicorn.

Unicorn's EMAC is wrong in signed fractional mode. EMAC instructions are
found with objdump (the reference for instruction boundaries), overwritten
with NOPs in emulator memory, and run by one code hook per loaded region.

The hook is C (emu/emac_native.c) when a host compiler is available, else
Python on emu/emac.py. The Python model is the reference; a test holds the
two bit-identical.

The same hook counts original instructions (a replaced EMAC instruction
counts once). Unicorn models no cache or bus timing, so counts are a lower
bound on real cost.
"""
import ctypes
import os
import re
import subprocess
import tempfile

from unicorn import UC_ARCH_M68K, UC_HOOK_CODE, UC_MODE_BIG_ENDIAN, Uc
from unicorn.m68k_const import (UC_CPU_M68K_ANY, UC_M68K_REG_A0, UC_M68K_REG_A7,
                                UC_M68K_REG_D0, UC_M68K_REG_PC)

from tools import disasm

from . import emac, native

NOP = b"\x4e\x71"
REGS = [UC_M68K_REG_D0 + i for i in range(8)] + [UC_M68K_REG_A0 + i for i in range(8)]


def boundaries(code, base):
    """Instruction start addresses and raw bytes for a block of code, via objdump."""
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
        f.write(code)
    try:
        lst = disasm.disasm(f.name, base)
    finally:
        os.unlink(f.name)
    out = []
    for line in lst.splitlines():
        m = re.match(r"\s*([0-9a-f]+):\t([0-9a-f ]+?)\s*\t(.*)", line)
        if m:
            out.append((int(m.group(1), 16), bytes.fromhex(m.group(2).replace(" ", "")), m.group(3)))
    return out


class NativeEmac:
    """emu.emac.Emac's state, living in the C helper."""

    def __init__(self):
        self.state = native.State()

    acc = property(lambda self: list(self.state.acc))
    overflows = property(lambda self: self.state.overflows)

    @property
    def macsr(self):
        return self.state.macsr

    @macsr.setter
    def macsr(self, v):
        self.state.macsr = v


class Machine:
    def __init__(self, use_native=True):
        # ANY is the only Unicorn model with ISA C (FF1) next to ISA B.
        self.uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
        self.uc.ctl_set_cpu_model(UC_CPU_M68K_ANY)
        self.native = native.lib() if use_native else None
        self.emac = NativeEmac() if self.native else emac.Emac()
        self.emac_sites = {}
        self._keep = []            # ctypes objects the C hook points into
        self._py_table = {}        # address -> Insn, or None inside a replaced instruction
        self._py_insns = 0
        self._py_ops = 0
        self.ret = None
        self.stack = None

    # memory
    def map(self, addr, size):
        self.uc.mem_map(addr, size)

    def write(self, addr, data):
        self.uc.mem_write(addr, bytes(data))

    def read(self, addr, n):
        return bytes(self.uc.mem_read(addr, n))

    def r32(self, addr):
        return int.from_bytes(self.uc.mem_read(addr, 4), "big")

    def w32(self, addr, v):
        self.uc.mem_write(addr, (v & 0xFFFFFFFF).to_bytes(4, "big"))

    def reg(self, n):
        return self.uc.reg_read(REGS[n]) & 0xFFFFFFFF

    def set_reg(self, n, v):
        self.uc.reg_write(REGS[n], v & 0xFFFFFFFF)

    # code
    def load_code(self, addr, code):
        """Write code, take over its EMAC instructions, count what runs in it."""
        if len(code) % 2 or addr % 2:
            raise ValueError("code must be word aligned")
        self.write(addr, code)
        sites = []
        for a, raw, _ in boundaries(code, addr):
            insn = emac.decode(raw) if raw[0] >> 4 == 0xA else None
            if insn is None:
                continue
            if insn.size != len(raw):
                raise ValueError("EMAC decode size mismatch at %#x" % a)
            sites.append((a, insn))
            self.emac_sites[a] = insn
            self.write(a, NOP * (insn.size // 2))
        if self.native:
            n = len(code) // 2
            table = (ctypes.c_void_p * n)()
            insns = (native.Insn * max(len(sites), 1))(*(native.pack(i, self.emac.state) for _, i in sites))
            for k, (a, i) in enumerate(sites):
                w = (a - addr) // 2
                table[w] = ctypes.addressof(insns[k])
                for j in range(1, i.size // 2):
                    table[w + j] = native.SKIP
            region = native.Region(ctypes.pointer(self.emac.state), table, addr, n)
            self._keep.append((table, insns, region))
            if self.native.emac_install(self.uc._uch, ctypes.byref(region)):
                raise RuntimeError("could not install the EMAC hook")
        else:
            for a, i in sites:
                self._py_table[a] = i
                for j in range(2, i.size, 2):
                    self._py_table[a + j] = None
            self.uc.hook_add(UC_HOOK_CODE, self._py_hook, begin=addr, end=addr + len(code) - 1)
        self.uc.ctl_flush_tb()

    def _py_hook(self, uc, address, size, user):
        i = self._py_table.get(address, False)
        if i is None:
            return
        self._py_insns += 1
        if i:
            self._py_ops += 1
            self._emac_hook(uc, address, size, i)

    def _emac_hook(self, uc, address, size, i):
        e = self.emac
        if i.kind == "mac":
            x, y = self.reg(i.rx), self.reg(i.ry)
            if i.mem is not None:
                mode, a, d16 = i.mem
                ea = self.reg(8 + a)
                if mode == 4:
                    ea = (ea - 4) & 0xFFFFFFFF
                    self.set_reg(8 + a, ea)
                elif mode == 5:
                    ea = (ea + d16) & 0xFFFFFFFF
                value = self.r32(ea)
                if mode == 3:
                    self.set_reg(8 + a, ea + 4)
                self.set_reg(i.rw, value)
            e.mac(i.acc, x, y, i.sub)
        elif i.kind == "store":
            self.set_reg(i.rx, e.store(i.acc, i.clear))
        elif i.kind == "load":
            e.load(i.acc, self.reg(i.src[1]) if i.src[0] == "reg" else i.src[1])
        elif i.kind == "to_macsr":
            e.macsr = (self.reg(i.src[1]) if i.src[0] == "reg" else i.src[1]) & 0xFFF
        elif i.kind == "from_macsr":
            self.set_reg(i.rx, e.macsr)

    # calls
    def set_stack(self, top, ret):
        """Stack top for calls and a mapped, never-executed return address."""
        self.stack, self.ret = top, ret
        self.set_exits([ret])

    def set_exits(self, addrs):
        """Addresses where emulation stops. Unicorn bakes the stop into translated
        code, so stops must be declared once, not varied per emu_start."""
        self.exits = list(addrs)
        self.uc.ctl_exits_enabled(True)
        self.uc.ctl_set_exits(self.exits)
        self.uc.ctl_flush_tb()

    def run(self, start, stop):
        """Run from start until stop, which must be a declared exit."""
        if stop not in self.exits:
            raise ValueError("%#x is not a declared exit" % stop)
        self.uc.emu_start(start, 0)
        pc = self.uc.reg_read(UC_M68K_REG_PC)
        if pc != stop:
            raise RuntimeError("run from %#x stopped at %#x, expected %#x" % (start, pc, stop))
        if self.native and self.emac.state.fault:
            raise NotImplementedError("EMAC mode MACSR=%#x is not modelled (insn at %#x)"
                                      % (self.emac.macsr, self.emac.state.fault))

    def call(self, addr, *args):
        """Call a C-convention function. Returns D0."""
        sp = self.stack
        for a in reversed(args):
            sp -= 4
            self.w32(sp, a)
        sp -= 4
        self.w32(sp, self.ret)
        self.uc.reg_write(UC_M68K_REG_A7, sp)
        self.run(addr, self.ret)
        return self.reg(0)

    # counters
    @property
    def insns(self):
        """Original instructions executed in loaded code so far."""
        return self.emac.state.insns if self.native else self._py_insns

    @property
    def emac_ops(self):
        return self.emac.state.ops if self.native else self._py_ops
