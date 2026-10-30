# SynCrackd: notes for AI assistants working in this repository

A sampler for the Elektron Syntakt, as a patch to the official OS 1.42. Read `CONTRIBUTING.md` first: its rules
are this file's rules.

## Hard rules

1. **Never talk to a Syntakt.** No USB MIDI, no SysEx sending, no flash scripts. This repository builds and tests
   files; flashing is the user's own step.
2. **Never commit Elektron firmware** or anything made from it: no `.syx`, sections, listings, renders, byte runs.
   `firmware/`, `sections/` and `build/` are gitignored. Stock bytes in source are sealed: write the hex, then
   `python -m tools.seal FILE`. `python -m tools.public_check` must pass.
3. **Never modify sections 2 and 4** (bootstrap, updater). Only 3 and 7; `tools/fw.py` enforces it.
4. **Pin to exact OS builds** (`fw.KNOWN`, 1.42 only). Every patch site checks the stock bytes it expects.
5. **A built image may differ from the official one only inside declared regions.**
6. **Licenses:** copy only from the MIT sources in `third_party/`. Modded-Cycles has no license: read, never copy.
   digikit is GPL-2.0: an outside tool only.
7. **Verify, don't trust.** Confirm every address in our own tooling and log how in `docs/FINDINGS.md`.
8. **Style:** no em dash in any file. Terse.

## Where things are

| For | Read |
|---|---|
| What the machine does, image by image, knob by knob | `docs/SAMPLER.md` |
| Every verified fact: address, how confirmed | `docs/FINDINGS.md`; `grep -n "^## " docs/FINDINGS.md` |
| Audio CPU memory, the shared window, the pool | `docs/MEMORY_MAP.md` |
| The mix path and stereo | `docs/STEREO.md` |
| What is proven and what needs hardware | `docs/REPORT.md` |
| Section 7 and section 3 addresses | `tools/audiomap.py`, `tools/mainmap.py`; room: `python -m tools.deadcode 3` |
| The sampler and its reference model | `engine/sampler.c`, `engine/stub.S`, `emu/sampler_ref.py` |
| A page as the unit draws it, in emulation | `make screen PAGE=fltr2 IMAGE=x MACHINE=44` (PNG in `build/screens/`, never committed) |
| The user's patcher | `tools/patch.py`, `tools/bundle.py`, `tools/single.py`, `tests/test_patch.py` |

## How work is done

- Images are a chain, each `make image-X` built on the one before. A new feature is a new image on the newest
  one: its code under its own `#ifdef` or in a new file, the older images' text untouched, its own test file
  `tests/test_X.py`.
- A change: build the new image, run its own test file once (`make check IMAGE=X`). The whole suite (`make test`)
  only when asked.
- Where a stock routine can run in emulation, run it; a stand-in shares your mistake. A change to how a page looks:
  `make screen` it first.
- Emulation does not model the cache, real time, or the FPGAs. Instruction counts are a lower bound.

## Traps

- **The shared window stores 16-bit words.** Never access it a byte at a time.
- **Never believe free SDRAM across a start or a flash.** Make it again, or put its shape in its check.
- **Before wrapping a method, read the listing for short jumps into it.**
- **A lock is kept by knob slot, not by record.**
- **Only some knob slots cross to the audio CPU**: a track's type, slots 18 to 26, 27, 29, 37, 38, 40 to 44, 50,
  51. Test a new knob through `tests/stereo_rig.Rig`.
- **The block a trig's locks are written into (`0x800021b0`) is not the block the audio CPU is sent
  (`0x80006348`).**
- **Do not point a transfer (DMA) at SDRAM by its cached address.**
- **The same C in another order is other bytes.** New text under the new image's `#ifdef`.
- **When engine and model agree, both can be wrong.**
- In our listings an indexed operand's displacement is hex with no prefix.
- Capstone misses MVS, MVZ and FF1; Unicorn's EMAC is wrong in signed fractional mode (`emu/emac.py`).

## Toolchain

Python 3.11+ in `.venv` (`make setup`). ColdFire cross-compiler `m68k-elf-gcc` (macOS Homebrew) or
`gcc-m68k-linux-gnu`, with `-mcpu=54418`. Disassembly: `tools/disasm.py` (binutils). Clone with `--recursive`.
