# SynCrackd

A sampler for the Elektron Syntakt, built as a patch to the official OS 1.42.

**Unofficial. Not made, endorsed or supported by Elektron.** Read [DISCLAIMER.md](DISCLAIMER.md) before you flash anything.

## What it does

The mod replaces the Twinshot machine with a sample player and adds a sampling page. Everything else is the Syntakt you know.

- **A sample machine** on any digital track: 64 slots, 16-bit 48 kHz, mono or stereo, from a 64 MB pool. A stereo sample takes two slots.
- **Playback**: start and length that follow the knobs live, loops with a crossfaded seam, sample rate reduction, a pushed TUNE that steps finer.
- **Slices**: KEYS on SLCE plays the sample's transients across the keyboard.
- **Time stretch**: STRC on, the sample follows the tempo, SPD sets the ratio. Lockable per step.
- **Transient triggers**: on a sampler track, the filter page's DEL becomes TRANS: each hit in the sample can restart the filter envelope.
- **A sampling page**: record from 16 sources into any slot, REC OFF or ONCE (lockable), mono or stereo, input gain, takes normalized to -1 dB.
- **Takes survive**: written with the pattern's save, and kept across a power-off even unsaved.
- **Per-project sample banks**, loaded with the project, while the unit runs.
- **Solo and crossfade**: a solo per track (lockable), and one crossfade across the whole unit, on the analog tracks too.

The full list, knob by knob: [docs/SAMPLER.md](docs/SAMPLER.md).

**What it costs**: Twinshot and CY ALLOY are gone (a track set to either plays nothing). The rest of stock's machines are untouched.

## Status

Alpha. Every image is tested in emulation and on one unit. Expect rough edges, and expect sample banks and project data formats to change between releases.

Only **OS 1.42** is supported. The patcher refuses any other file.

## Flashing it

You never download a modded OS from here. You make one from Elektron's own file, on your own machine.

1. **Back up your +Drive** with Elektron Transfer: projects and samples. The mod writes to the drive.
2. **Get Syntakt OS 1.42** from Elektron's website.
3. **Patch it**, in your browser at the project's page (your file never leaves it), or with Python: download the release's one file (`syncrackd_firstrec.py` for v0.1), put it next to Elektron's, and run it. Python 3.9 or later, which a Mac already has; nothing to install.
   ```bash
   python3 syncrackd_firstrec.py Syntakt_OS1.42.syx
   ```
   It checks your file is the exact official 1.42, applies the mod, checks nothing changed outside the mod's own regions, and prints a SHA-256. Compare it with the one in the release notes. If they differ, do not flash.
4. **Flash it** the way you would any OS update: with Transfer, or as SysEx from the unit's boot menu (see Elektron's manual).
5. **To go back**, flash Elektron's 1.42 the same way. The mod never touches the bootloader or the updater, so the boot menu stays available.

## Building from source

Clone with `--recursive` (the aplib codec is a submodule). `make bundle IMAGE=x` then `make single IMAGE=x` make a release's file in `build/dist/`.

You need the official 1.42 file in `firmware/`, Python 3.11+, and a ColdFire cross-compiler (`brew install m68k-elf-gcc` on macOS, `gcc-m68k-linux-gnu` on Linux).

```bash
make setup
make image-firstrec
make check IMAGE=firstrec
```

Each feature is an image in a chain, each built on the one before, each with its own test file in `tests/`. The emulator (`emu/`) runs the patched code against stock's own routines before anything reaches a unit.

How the machine works inside: [docs/MEMORY_MAP.md](docs/MEMORY_MAP.md), [docs/STEREO.md](docs/STEREO.md), and what each image does, [docs/SAMPLER.md](docs/SAMPLER.md).

## Contributing

Welcome, on the maintainer's terms. Read [CONTRIBUTING.md](CONTRIBUTING.md) first. The short version: one change per PR, signed off, no Elektron bytes ever, and nothing is "working" until it ran on a unit.

## Thanks

Built on what others worked out first: [Model-TG](https://github.com/TinyGregAudio/Model-TG), [elektron-model-tweaks](https://github.com/drumkilla/elektron-model-tweaks), [elektron-firmware-tool](https://github.com/mischa85/elektron-firmware-tool), [syntakt-firmware-workbench](https://github.com/Bezronczek/syntakt-firmware-workbench).

## License

The mod's own code: MIT, see [LICENSE](LICENSE). Elektron's firmware is Elektron's and is not part of this repository or its releases.
