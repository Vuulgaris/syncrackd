"""Disassemble a decoded section with binutils objdump (ColdFire ISA C + EMAC).

python -m tools.disasm sections/1.42/sec7_audio.bin 0x40000400 > build/dis/sec7.lst
python -m tools.disasm sections/1.42/sec7_audio.bin 0x40000400 0x40004324 0x40004400

Capstone misses ColdFire instructions, so objdump is the reference listing. Output is Elektron code: keep it in build/
(gitignored).
"""
import shutil
import subprocess
import sys

# isa-c is needed: the code uses FF1, which the 547x decoder rejects.
MACHINE = "m68k:isa-c:emac"


def objdump():
    exe = shutil.which("m68k-elf-objdump") or shutil.which("m68k-linux-gnu-objdump")
    if not exe:
        raise RuntimeError("no m68k objdump on PATH")
    return exe


def disasm(path, base, start=None, stop=None):
    cmd = [objdump(), "-D", "-b", "binary", "-m", MACHINE, "--adjust-vma=%#x" % base]
    if start is not None:
        cmd.append("--start-address=%#x" % start)
    if stop is not None:
        cmd.append("--stop-address=%#x" % stop)
    out = subprocess.run(cmd + [path], check=True, capture_output=True, text=True).stdout
    return out.split("\n", 7)[-1]


if __name__ == "__main__":
    a = sys.argv[1:]
    sys.stdout.write(disasm(a[0], int(a[1], 0), *(int(x, 0) for x in a[2:4])))
