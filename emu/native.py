"""Build and load emu/emac_native.c. Returns None when there is no host compiler."""
import ctypes
import hashlib
import os
import shutil
import subprocess
import sys

from unicorn import UC_HOOK_CODE
from unicorn.m68k_const import UC_M68K_REG_A0, UC_M68K_REG_D0
from unicorn.unicorn_py3.unicorn import uclib

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "emac_native.c")
OUT = os.path.join(HERE, "..", "build", "native")

KINDS = {"mac": 0, "store": 1, "load": 2, "to_macsr": 3, "from_macsr": 4}


class State(ctypes.Structure):
    _fields_ = [("acc", ctypes.c_int64 * 4), ("macsr", ctypes.c_uint32),
                ("overflows", ctypes.c_uint32), ("fault", ctypes.c_uint32),
                ("pad", ctypes.c_uint32), ("ops", ctypes.c_uint64), ("insns", ctypes.c_uint64)]


class Insn(ctypes.Structure):
    _fields_ = [("st", ctypes.POINTER(State)), ("imm", ctypes.c_uint32), ("d16", ctypes.c_int16)] + [
        (n, ctypes.c_uint8) for n in ("kind", "acc", "rx", "ry", "rw", "sub", "clear",
                                      "mode", "areg", "src_imm", "src_reg")]


class Region(ctypes.Structure):
    _fields_ = [("st", ctypes.POINTER(State)), ("table", ctypes.POINTER(ctypes.c_void_p)),
                ("base", ctypes.c_uint32), ("n", ctypes.c_uint32)]


SKIP = 1


class Api(ctypes.Structure):
    _fields_ = [("reg_read", ctypes.c_void_p), ("reg_write", ctypes.c_void_p),
                ("mem_read", ctypes.c_void_p), ("hook_add", ctypes.c_void_p),
                ("regid", ctypes.c_int * 16), ("hook_code", ctypes.c_int)]


_lib = False


def lib():
    """The loaded helper, or None."""
    global _lib
    if _lib is not False:
        return _lib
    _lib = None
    cc = shutil.which("cc") or shutil.which("gcc")
    if not cc:
        return None
    with open(SRC, "rb") as f:
        tag = hashlib.sha256(f.read()).hexdigest()[:12]
    ext = "dylib" if sys.platform == "darwin" else "so"
    path = os.path.join(OUT, "emac_native_%s.%s" % (tag, ext))
    if not os.path.exists(path):
        os.makedirs(OUT, exist_ok=True)
        part = "%s.%d" % (path, os.getpid())  # built aside and moved in whole: test workers start together
        subprocess.run([cc, "-O2", "-shared", "-fPIC", "-Wall", "-Werror", "-o", part, SRC],
                       check=True, capture_output=True)
        os.replace(part, path)
    dll = ctypes.CDLL(path)
    api = Api()
    for name in ("reg_read", "reg_write", "mem_read", "hook_add"):
        setattr(api, name, ctypes.cast(getattr(uclib, "uc_" + name), ctypes.c_void_p).value)
    for i in range(8):
        api.regid[i] = UC_M68K_REG_D0 + i
        api.regid[8 + i] = UC_M68K_REG_A0 + i
    api.hook_code = UC_HOOK_CODE
    dll.emac_setup(ctypes.byref(api))
    dll.emac_install.argtypes = [ctypes.c_void_p, ctypes.POINTER(Region)]
    _lib = dll
    return dll


def pack(insn, state):
    """emu.emac.Insn -> native Insn."""
    n = Insn()
    n.st = ctypes.pointer(state)
    n.kind = KINDS[insn.kind]
    n.acc, n.rx, n.ry, n.rw = insn.acc, insn.rx, insn.ry, insn.rw
    n.sub, n.clear = insn.sub, insn.clear
    if insn.mem is not None:
        n.mode, n.areg, n.d16 = insn.mem
    if insn.src is not None:
        if insn.src[0] == "imm":
            n.src_imm, n.imm = 1, insn.src[1]
        else:
            n.src_reg = insn.src[1]
    return n
