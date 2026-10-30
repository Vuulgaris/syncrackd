# Findings

Every verified fact: what, OS version, how it was confirmed. Unconfirmed items are marked OPEN.

## Phase 0: setup (2026-10-03)

Host: macOS 14.5 arm64.

| Item | Value | How confirmed |
|---|---|---|
| Python | 3.13.3, venv at `.venv/` | `make test` |
| unicorn / capstone / numpy | 2.1.4 / 5.0.7 / 2.5.3 | `tests/test_toolchain.py` runs m68k code in Unicorn |
| Cross-compiler | Homebrew `m68k-elf-gcc` 16.2.0, `m68k-elf-binutils` 2.47 | `tests/test_toolchain.py` compiles C and assembles EMAC for `-mcpu=5475` |
| EMAC assembles | `mac.l`, `move.l to %macsr / %acc0`, `mvs`, `mvz` | same test, checked in objdump output |
| MIT submodules | Model-TG `70b39dd` (v1.1.0), elektron-model-tweaks `40bc9c1`, elektron-firmware-tool `a5bce9a`, syntakt-firmware-workbench `49a7a1e` | LICENSE file in each reads MIT |
| Reference clones | `ref/Modded-Cycles`, `ref/digikit` (gitignored, read only) | cloned |
| No firmware in clones | no `.syx` under `third_party/` or `ref/` | `find` |

Notes:
- Homebrew on macOS 14 will not build from source (Command Line Tools too old). The toolchain was poured from bottles with `brew install --ignore-dependencies --force-bottle m68k-elf-binutils m68k-elf-gcc`.
- gas rejects `ff1` for `-mcpu=5475` (ISA B). CLAUDE.md lists FF1 as an instruction Capstone misses. OPEN for Phase 2: if section 3 or 7 contains FF1, the CPUs are not 547x class and `-mcpu` must change. Do not assume 5475 until checked against the real code.

## Phase 1: container (2026-10-03, OS 1.42)

All confirmed on the official 1.42 file with `tools/` and `tests/test_container.py` (28 tests), and independently with elektron-firmware-tool (built from `third_party/`, same results).

Official file:

| OS | SHA-256 | Size | Status |
|---|---|---|---|
| 1.42 | `ded3c59fdb909eb9e2c3307b30a486452c8fa6947b12c14e0ce35a187b7f37c1` | 2,572,064 | held, pinned in `tools/fw.py` |
| 1.41 | `8e2488f462c4a5656396a895f113bcd415e9900fa8709340dccf45d4cb9ed19e` (from syntakt-firmware-workbench) | ? | NOT held, not pinned. Elektron's page only offers 1.42 now. |

Transport:
- Product `0x16`. One start marker, 20,094 data packets of 128 bytes, one end marker. 101 plain bytes per packet (116 bytes 8-in-7).
- **Correction to CLAUDE.md: there is one packet stream, not two.** Bytes 7..9 of a packet are a 21-bit sequence counter (3 x 7 bit), starting at 242. Byte 7 going `0x00` to `0x01` at packet 16,142 is that counter carrying, nothing more.
- Checksum covers bytes 7..125: `(base + sum(msg[7+i] ^ (base+i))) & 0x7f`, `base = 0x11` from the start marker. 20,094 of 20,094 verify.
- The CLAUDE.md form (`V = 0x35`, `C0 = 0x2C`, sum over bytes 8..125) also verifies on all packets once `C0` is reduced by byte 7. Same sum written two ways: the "second stream uses `C0 - 1`" is byte 7 leaving the summed range.

Container:
- ELE3, model `J0097`, version `1.42`, 2,029,392 bytes (1.41 reported as 2,028,880). Stream is `[u32 length][u32 content checksum][container][zero pad]`. Content checksum verifies.
- **Correction to CLAUDE.md: no HMAC-SHA256 trailer on the Syntakt.** The container ends at the 16-byte aligned end of the last section. elektron-firmware-tool reports `trailer: none`; syntakt-firmware-workbench says the same and has flashed on hardware. Integrity is packet checksums, content checksum, and per-section stream sums only. `tools/ele3.py` refuses any container that does have a trailer.
- Compressed sections are stored as `[u32 stream length][u32 byte sum][aPLib-variant stream][zero pad to 4]`. Raw sections have no header.

Sections (table order), decoded SHA-256 pinned in `tools/fw.py`:

| id | role | dest field | stored | decoded | SHA-256 (decoded) | how the role was confirmed |
|---|---|---|---|---|---|---|
| 5 | meta | 0 | 15 raw | 15 | `7d97057d...` | ASCII build timestamp |
| 2 | **bootstrap** | `0x04000000` | 15,408 aPLib | 30,782 | `9fa34a83...` | names itself in its own strings (bootstrap upgrade, OS upgrade, startup menu); ColdFire code |
| 1 | FPGA | 0 | 49,252 aPLib | 149,516 | `c920a4cb...` | Xilinx bitstream sync word after `FF` padding |
| 3 | main CPU | `0x40000400` | 1,442,812 aPLib | 3,442,576 | `1a9723b1...` | dest matches known load address; UI symbols |
| 4 | **updater** | `0x80000400` | 32,776 raw | 32,776 | `6e78d72b...` | INFERRED: ColdFire code linked for SRAM, raw, same shape as digikit's Digitakt II updater and elektron-firmware-tool's label. No self-naming strings. |
| 6 | boot stub | 0 | 1,744 raw | 1,744 | `eec1379d...` | INFERRED from elektron-firmware-tool label |
| 7 | audio CPU | 0 | 383,760 raw | 383,760 | `daf6451c...783bc2` | matches the 1.41 hash in CLAUDE.md and the workbench: **section 7 is identical in 1.41 and 1.42**. First word is `0x40001070`, the known entry. |
| 8 | USB MCU | 0 | 103,416 aPLib | 159,948 | `6943b2f2...` | ARM Thumb code with USB PD task strings. Not in CLAUDE.md. Not a second FPGA bitstream. |

- Bootstrap and updater are sections **2 and 4**, same numbering as the Digitakt II.
- Section 3 on 1.42 is 4,096 bytes longer than the 1.41 size in CLAUDE.md (3,438,480). **Every section 3 address in CLAUDE.md is 1.41 and must be re-found on 1.42 before use.**

Round trip and repack:
- Unpack then repack with nothing changed is byte-identical to the official file. Also identical when sections 3 and 7 are passed back through the patch path, and the codec reproduces all four compressed sections exactly.
- A one-byte change in section 7 (raw) or section 3 (compressed) builds an image that decodes back to exactly that byte, every other section's stored bytes unchanged. elektron-firmware-tool reads our built images with all checksums ok and extracts the same sections.

Guards (`tools/fw.py`), each with a test:
- `load()` accepts only pinned file hashes and checks all eight section hashes.
- `build()` and `apply()` raise `GuardError` for sections 2 and 4. Only 3 and 7 are patchable; 1, 5, 6, 8 are refused too.
- `Patch` asserts stock bytes; overlapping patches are refused; section length may not change.
- `verify()` re-decodes a built image and fails on any change outside declared regions, and on any change to the stored bytes of 2 or 4 even if a region is declared.

OPEN:
- 1.41 file not held. Section 7 work is unaffected. Section 3 (UI) work has to be done on 1.42, or the maintainer finds a 1.41 file.
- Section 4 and 6 roles are inferred, not proven. They are protected or unpatchable either way.
- Which CPU reads section 8, and whether sections 5, 6, 7, 8 dest `0` means "not loaded by the bootstrap directly" (likely pushed by the main CPU). Not needed yet.
- Does anything on the device check section 7 beyond the container checksums? The workbench flashed modified section 7 on 1.41 hardware, so presumably not, but that is their claim, not ours.

## Phase 2: audio engine map (2026-10-03, section 7 of OS 1.42, identical in 1.41)

Method: `tools/disasm.py` (objdump, `m68k:isa-c:emac`) listing of the pinned section, read by hand. Every address below is asserted against the image by `tests/test_audio_map.py`, which reads the operand at the instruction that uses it. Map in `docs/MEMORY_MAP.md`, constants in `tools/audiomap.py`.

Known facts from CLAUDE.md, all **confirmed**:

| Fact | Confirmed at |
|---|---|
| Loads at `0x40000400`, entry `0x40001070` | first word of the image; absolute `jsr` targets land on function starts |
| Boot `0x400004bc` copies `0x4004f6e0..0x40057670` to `0x80000000` and `0x40057670..0x4005df10` to `0x80008000`, zeroes the rest of each half | operands at `0x400004be..0x40000506` |
| BSS runs to `0x4404f980` | `0x40000512` zeroes `0x4004f6e0..0x4404f980` |
| Voice loop `0x40004324(out, params, trig_mask, release_mask)` | called from the audio interrupt at `0x40000a34` with `out = 0x80003840`, `params = 0x80003c40` |
| 8 voices of 1,800 bytes at `0x80000000`, params stride 142, type at `+0x3e` clamped to 0..45 | `0x400043aa..0x40004404` |
| Type to engine table `0x40014950`, update `0x40014920`, render `0x400148f0`, 12 entries | `0x40004406`, `0x400043b0`, `0x400044aa`; table contents match the notes exactly |
| `update(pmod, voice, params + 0x1c + 142*i)`, `render(out + 128*i, voice)`, `pmod` at `0x80008150 + 4*i` | `0x40004466..0x400044b4` |
| `MACSR = 0xA0` in the loop, `0x20` after | `0x4000433c`, `0x400044d2` |
| Voice init `0x40000fd6`, reset `0x40003ee0`, envelope `0x40003d42` (tests `voice+1004`) | read |
| SD VINTAGE is engine 6 at `0x40008074` / `0x4000847a` | table |

Corrections and additions:

- **The audio CPU has 128 MB of SDRAM, not 64.** Initial SP is `0x48000000` and ACR0 covers `0x40000000..0x47FFFFFF`. The 64 MB in the notes is the size of BSS.
- **The CPU is MCF5441x class (ISA C + EMAC), not 547x.** The code contains 36 FF1 instructions, which ISA B lacks, and the peripheral map fits. Phase 0's open question is closed: use `-mcpu=54418`. The 547x objdump decoder silently prints FF1 as `.short`.
- Machine types with no engine (8..35, 39..43, 45) map to engine 0 in the table. Whether such a type ever reaches the loop is not known.
- Real code is only `0x40000404..0x40009f88` (39.8 KB). Everything after is tables and data.
- Each track renders **32 frames of mono int32** into its own 128-byte buffer. There is no stereo inside the voice loop.

Twinshot and the sample pool (details in `docs/MEMORY_MAP.md`):

- Twinshot is engine 11: update `0x400097dc`, render `0x40009a8a`. It plays **two samples per voice** (players at `voice+1712` and `voice+1748`), each with its own pitch and slot, mixed to mono with a balance control. Reverse and loop already exist in the stock player `0x40006764`.
- **Sample pool: 64 MB at `0x4004f750..0x4404f750`**, a packed run of 64 records `{u32 frames, int16 samples}`. Slot table (64 x 8 bytes) at `0x4404f754`.
- Samples are **16-bit, read big-endian**. (An earlier version of this entry said the pool is read over SPI by `0x40000cda`. Wrong: see the Phase 3 correction.)
- Engine limit per slot is **524,287 frames (10.9 s)**, from the 20.12 position format. The 5 s and 32 MB limits in the manual are not in section 7; they must be enforced by the main CPU.
- **Free SDRAM: `0x4404f980..0x48000000`, 66,782,848 bytes (63.7 MB)**, minus the stack at the top. No instruction references it (test: `test_free_sdram_is_unreferenced`).

What this means for the mod:

- Memory is not the constraint. The stock pool is twice what the UI uses, and as much again is free.
- Samples up to 10.9 s need no new DSP, only whatever sets the length on the main CPU side. Longer than that needs a player with a wider position.
- Stereo cannot be done inside one voice's render as the buffers stand. That is Phase 4.

OPEN:
- How the main CPU decides what to send into the pool, and when. Per-project sample sets depend on it. (Reworded after the Phase 3 correction.)
- Stack depth, to size the safe part of free SDRAM.
- Twinshot parameter names (section 3). Slot behaviour is read from code only; Phase 3 will run it.
- Physical SDRAM size is inferred from SP and ACR0, not measured.

## Phase 3: the real engine in emulation (2026-10-03, OS 1.42)

Harness: `emu/machine.py` (Unicorn + EMAC takeover), `emu/emac.py` (EMAC model and decoder), `emu/emac_native.c` (the same model in C), `emu/engine.py` (boot, voice init, voice loop), `emu/render.py` (`make render`). Tests: `tests/test_emac.py`, `tests/test_emu_engine.py`. `make test` is 81 tests, about 40 s.

Emulator:
- Unicorn CPU model `ANY`. `CFV4E` has no FF1 and stops on it. Checked on MVS, MVZ, SATS, MOV3Q, FF1, REMS.
- Unicorn's own EMAC is not used at all. Modded-Cycles found it wrong in signed fractional mode (unsigned multiply), which is the mode of this engine. All **839** EMAC instructions in section 7 code are replaced by NOPs and executed by our model. Our decoder renders every one of the 839 to exactly objdump's text.
- EMAC model source: ColdFire Family Programmer's Reference Manual rev 3, chapter 6 (formats, MOVCLR and MOVE from ACC pseudocode, MOVE to ACC). Section 7 only uses longword MAC and MSAC (with and without load), MOVE to and from ACC, MOVCLR, MOVE to and from MACSR, always in signed fractional mode without rounding. Anything else raises instead of running.
- OPEN: the saturation value on a 48-bit accumulation overflow is from memory, not from that chapter. It needs a sum past +/-256.0 between two MOVCLRs. The model counts such overflows; every render so far has zero, and a test asserts it for all 12 machines.
- The C hook and the Python model give **bit-identical** audio, accumulators, MACSR and instruction counts (test, three machines).
- Speed: one Unicorn hook per EMAC site cost 150 ms per block, because Unicorn walks its whole hook list on every hooked instruction. One hook per code region with a lookup table: 2 ms per block with 8 heavy voices.
- Python replay of the boot copies equals what the real `0x400004bc` leaves in SRAM (test).

What the voice loop reads (memory-read trace over all 12 machines): the type byte at `params+0x3e`, knob slots 18..25 (`+0x40..+0x4f`), and `pmod`. Nothing else. Slot 26 (OVER) is not read here; overdrive is downstream.

Timing: a note starts on the block **after** its trig bit. A machine type change is applied on that block too, with a voice reset.

UI descriptors on 1.42 (`tools/params.py`): two tables of `0x34`-byte records, `0x4022e404` (204 records) and `0x40230f14` (235). The 1.41 addresses in CLAUDE.md do not apply. SD VINTAGE's slots, ranges and defaults equal the ones Modded-Cycles published for 1.41 (test).

Renders, factory defaults, note 60, 1 s, track output before filter, overdrive and mixer (`build/renders/`):

| Machine | Type | Peak dBFS | Strongest partial | Below -60 dB after |
|---|---|---|---|---|
| BD MODERN | 0 | -6.9 | 65.4 Hz | > 1 s |
| SD BASIC | 1 | -4.1 | 784.7 Hz | 361 ms |
| CY ALLOY | 2 | -9.8 | 4018.6 Hz | 124 ms |
| PC CARBON | 3 | -8.6 | 139.2 Hz | 584 ms |
| SY TONE | 4 | -12.1 | 130.8 Hz | > 1 s |
| SY CHORD | 5 | -12.0 | 311.0 Hz | > 1 s |
| SD VINTAGE | 6 | -3.0 | 264.8 Hz | 185 ms |
| CP VINTAGE | 7 | 0.0 | 981.7 Hz | 331 ms |
| SY TOY | 36 | -11.6 | 261.6 Hz | 667 ms |
| SY BITS | 37 | -12.2 | 261.6 Hz | > 1 s |
| SY SWARM | 38 | -12.0 | 261.6 Hz | > 1 s |
| SP TWINSHOT | 44 | -8.8 | test samples | 531 ms (0.5 s samples) |

Evidence the emulation is right, beyond "it makes sound":
- SY TOY, SY BITS and SY SWARM at note 60 give 261.6 Hz, which is C4. SY TOY follows notes 48, 60, 72 within 0.3 % (test).
- SD VINTAGE body at notes 48, 60, 72 is 133, 264, 529 Hz, the numbers Modded-Cycles published from their own bench (test). Same engine, two independent harnesses.
- Twinshot at note 60 with TUN 64 has a playback increment of exactly 4096 (1.0), and its output is the pool sample times 2^15 with under 1 % residual (test).
- None of this is a hardware comparison. Nobody here has captured audio from a real unit.

**CPU budget** (original instructions per 32-frame voice-loop block, same machine on all 8 tracks, all trigged, factory defaults):

| Machine | Steady state, 8 voices | Per voice |
|---|---|---|
| **SY SWARM** | **84,044** | **10,506** |
| CP VINTAGE | 68,180 | 8,523 |
| SD VINTAGE | 65,156 | 8,145 |
| SY CHORD | about 59,600 | 7,450 |
| SY BITS | about 58,700 | 7,340 |
| BD MODERN | 55,276 | 6,910 |
| SY TOY | about 53,900 | 6,730 |
| SD BASIC | about 53,300 | 6,660 |
| CY ALLOY | about 47,600 | 5,950 |
| PC CARBON | about 44,800 | 5,600 |
| SY TONE | 42,708 | 5,339 |
| **SP TWINSHOT**, both samples playing | **31,060** | **3,883** |

- **Heaviest stock machine: SY SWARM.** That is the budget: a sampler voice must stay under **10,506 instructions per block** (328 per frame) to be no worse than stock on all 8 tracks.
- Spikes with SY SWARM on 8 tracks: a retrig of all 8 costs 86,508; a machine change plus note-on on all 8 costs 93,436.
- Twinshot is the cheapest machine by a wide margin: a sampler voice may cost 2.7 times stock Twinshot before it passes SY SWARM.
- Counts are a lower bound on real cost. The emulator has no cache model, and a sampler streams from SDRAM while the stock machines read small tables.

Twinshot, confirmed by running it:
- Knob names from section 3: TUN1 (18), SMP1 (19), FLT1 (20), MIX (21), TUN2 (22), SMP2 (23), DEC1 (25), OVER (26). Defaults 64, 64, 64, 64, 64, 65, 127, 0: sample 1 is slot 0, sample 2 is slot 1.
- MIX 0 is sample 1 only, 127 is sample 2 only, 64 is both.
- SMP 64 and up plays slot `v-64` forward; SMP 63 and down sets the reverse flag (test with a ramp).
- Pitch increment is 20.12: 4096 at note 60, 8192 at note 72, 2047 at note 48, 6136 at note 67 (ideal 6137.07). So stock pitch resolution is 1/4096 of the sample rate ratio.
- The filter and the decay act on sample 1 only (hence FLT1, DEC1).

Correction to Phase 2:
- **The pool is not loaded over SPI.** `0x40000cda` (the SPI reader) has no caller and no pointer to it anywhere in the image: dead code in this build. The pool is filled during init at `0x40000f8e..0x40000fd4`: the main CPU hands over **2 KB chunks** through a shared window, and the audio CPU copies each from address `0x800` to `POOL + index * 0x800`, acknowledges, and repeats until told to stop. Then it builds the slot table once (`0x40000d06`).
- The audio interrupt reads its per-block parameter block from the same window (0x1b0 bytes from address 0 to `0x80008000`).
- The chunk index is 16 bits and is not range checked, so the main CPU can write up to 128 MB from the pool base. What limits the pool to "32 MB" is the main CPU.
- So samples are pushed by the main CPU **at every boot**, and the slot table is built once. There is no runtime reload path in section 7. Per-project sample sets need either a new reload path here plus main CPU cooperation, or all projects' samples living in the one pool.

OPEN:
- Machine types 8..35, 39..43 and 45 map to engine 0 in the type table. The ones named in the descriptors are analog-track machines, plus `SCHP` (40), which we cannot place. Whether such a type ever reaches this loop is unknown.
- What `0x4000112c`, `0x40002320`, `0x400019d6` and `0x4000168e` do with the track buffers after the voice loop. That is Phase 4.
- No hardware reference for any render.

## Phase 4: the stereo question (2026-10-04, OS 1.42)

Full write-up and decision in `docs/STEREO.md`. Tests: `tests/test_stereo_path.py` (10 tests). Constants: `tools/mainmap.py` (section 3, 1.42 only), `emu/engine.py` (`Board`).

Answer: **the mix (pan, level, sum to stereo, sends) is code on the main CPU, section 3.** Not FPGA, and not the audio CPU.

Audio CPU (section 7), per 32-frame block, interrupt `0x40000934`:
- Copies a `0x1b0`-byte parameter block from the shared window at address 0 to `0x80008000`, and unpacks parts of it into the track parameters.
- Block layout: `0..160` 8 x 20 bytes (type, one more byte, slots 18..26); `160..224` 8 x 4 words (slots 27, 29, 37, 38); `224..336` 8 x 7 words (slots 40..44, 50, 51); `0x150` `pmod` x 8; `0x180` trig mask, `0x181` release mask, `0x182` a word that masks trigs and forces releases; `0x184` a long; `0x188` a long per track, passed to the filter stage; `0x1a8` a per-track flag byte for the amp stage.
- **PAN (47), VOL (48), DEL (45) and REV (46) are not in the block.** Shown by filling the block with a marker and looking at what arrives (test).
- After the voice loop the track buffers go through `0x4000112c`, `0x40002320`, `0x400019d6` (once per track) and `0x4000168e` (calls `0x40001476` once per track), all in place and mono. The names gain, drive, filter, amp are our reading of them; only filter and amp are backed by which parameters they read.
- Then eDMA channel 47 sends `0x80003840` to the window at `+0x1b0`: 64 x 16 = 1024 bytes, the 8 mono buffers and nothing else (test, from the registers the real interrupt writes).
- The shared area init clears is `0x5b0` bytes: `0x1b0` in plus `0x400` out.
- Emulator note: Unicorn cannot execute RTE, so the interrupt is run up to its RTE at `0x40000b1e`. Unicorn also bakes stop addresses into translated code; `Machine.set_exits` declares them once.

Main CPU (section 3, 1.42):
- Sees the window at `0x10000000`: status words at `+0..+0xc` during the boot handshake, sample chunks at `+0x800`, track audio at `+0x1b0`.
- `0x400a47fa`: eDMA channel 47 from `0x100001b0` to its own SRAM `0x80003d50`, 1024 bytes.
- Mixer `0x4008f242`: per track, volume from its own `params+124`, pan law `0x400a1792(params+122)` returning left and right gains, send gains from `params+118` and `+120`. Its track parameter block is 142 bytes with the same slot layout as the audio CPU's.
- Mix kernel `0x4008f0b6(dest, tracks, gains, increments)`: sums 8 tracks times ramped gains into one side of an interleaved stereo bus (`0x8000dbd0` left, `0x8000dbd4` right). Run in the emulator against a Python model: exact. **Corrected 2026-10-09: that bus is the delay send's sum, one of 14 kernel passes; the dry mix is `0x8000dad0`. See "The mixer run whole".**
- Pan law, run for all 128 values: pan 0 is left 1.0 and right exactly 0; pan 127 is right 1.0 and left 4 lsb (-174 dB); centre is 0.75 each. Two hard-panned tracks through the real kernel come out as left and right within 1 lsb.
- Both CPUs have 128 MB SDRAM by the same evidence (initial SP `0x48000000`).

FPGA: the bitstream in section 1 is 149,516 bytes, which is the bitstream size of a Xilinx Spartan-3A XC3S200A. Too small to hold delay and reverb memory, which fits the mixer and effects being main CPU code. INFERRED from size alone.

Consequences:
- Stereo inside one track would need a patch in both CPUs and a wider data path between them. Rejected for now.
- **Decision: two-track stereo, section 7 only** (left on track N, right on track N+1, user pans them hard). The stock mixer already turns that into clean left and right. Mono sampler first.

OPEN:
- What `0x4000112c` and `0x40002320` really are. (An earlier version of this entry said the amp stage outputs silence with our parameter block. That was a bug in our harness, fixed in Phase 5: see there.)
- Size and nature of the shared window.
- Nothing here is verified on hardware.

## Phase 5: the sampler engine (2026-10-04, section 7 of OS 1.42, identical in 1.41)

What was built and how to use it: `docs/SAMPLER.md`. Source `engine/`, build `tools/build_engine.py` (`make engine`), reference model `emu/sampler_ref.py`, tests `tests/test_sampler.py` (65 tests). `make test` is 156 tests, about a minute.

Proven, all in emulation, with the compiled ColdFire code running inside the real voice loop and the real interrupt:
- **Bit-identical to the Python reference** in 23 mono cases and 15 stereo cases: one-shot, pitch up and down, reverse, start and length, loop, ping-pong, reverse loops, chains across three slots with regions, loops and ping-pong crossing the seams, stereo on tracks 1, 4 and 7. Not "within tolerance": equal.
- At original pitch the output is the sample itself, shifted left 15 bits, exactly.
- **Every other stock machine is bit-identical** with the patch installed, and costs the same instruction count (11 machines, test).
- A 600,000-frame sample across three chained slots plays to its end: longer than any single slot can be.
- A slot at the length limit, at the fastest pitch, ends cleanly (the engine clamps a slot 255 frames below stock's limit so the position cannot overflow).
- A retrigger fades the old note out over the trig block and starts the new one on the next, matching the reference including the stock stages' ramps.
- Stereo through the real interrupt, with identical left and right data: the next track is bit-identical to this one after the voice loop and after each of the gain, drive, filter and amp stages, with the next track deliberately set to a different machine, filter, drive, amp settings and cutoff. A mono note leaves the next track's settings alone.
- CPU: 2,204 instructions per voice per block mono, 2,932 stereo, 5,150 worst case found. Stock Twinshot is 3,883, the budget is 10,506. The post step adds 156 per block to an interrupt that costs 117,348 with SY SWARM on all eight tracks.

Where the code lives:
- Section 7 has **32 functions that nothing references**, 6,830 bytes: no call, branch, address operand or 32-bit value anywhere in the image names them, and the code has no computed jumps. Found by scanning the listing and the whole image; they look like unused library routines.
- The engine uses two runs of them: `0x40002d86..0x400032b4` (1,326 bytes) and `0x40005a8e..0x40005f9a` (1,292 bytes), 996 bytes of code in each, the rest filled with NOPs.
- Tests: nothing points into those ranges, and in the stock image they are never executed or read while all 12 machines run through the full interrupt.
- So the patch overwrites only dead code, plus three pointers. Stock Twinshot stays in the image, unreached.
- OPEN: "unreferenced" is a static result for the whole image, plus a dynamic one for the audio path only. Boot and handshake code cannot be run here, so for those it rests on the static scan alone.

New facts about section 7:
- **The audio CPU configures a second FPGA.** `0x400005a2` unpacks 54,664 bytes from `0x40041060` to `0x40042000` at init, and `0x40000706` clocks them out through GPIO. 54,664 bytes is the bitstream size of a Spartan-3A XC3S50A, and the data starts with the Xilinx sync word. So there are two FPGAs after all: one loaded by the main CPU (section 1), one by the audio CPU. INFERRED part: the device type, from size alone.
- `0x40040060..0x40041060` is a 1,024-entry table used by the drive stage, half of it zeros. It looked like free space and is not.
- `0x4004f588..0x4004f6e0` (344 bytes) is the unused tail of the bitstream buffer.
- The stock amp and mix stages both ramp to zero in a block that carries a trig. That is the declick on retrigger.
- The long per track at parameter block offset `0x188` is the filter cutoff: raising it lets more signal through.

Corrections:
- **Phase 4 said the amp stage outputs silence with our parameter block. That was our bug**: the harness built the block with a slice assignment that wrote into a temporary, so the filter and amp words and the cutoff were always zero. Fixed. With factory values the whole stock chain passes audio, and the Phase 4 tests now check the amp stage too. The Phase 4 conclusions do not change.
- Unicorn bakes the stop address into translated code. Stops are now declared once (`Machine.set_exits`); varying them per call silently ran past the stop.

Design decisions worth knowing:
- The stereo link follows the knobs, not the playing note. The stock stages act on a trig one block before the note starts, and before a newly chosen machine is running, so a link that waited for the note would miss the first trig on the right track.
- Knobs other than TUNE and DECAY are latched at note start.
- No EMAC in our code. The stock envelope, amp and mix routines are called as they are, so level and retrigger behaviour match Twinshot's.

OPEN:
- Nothing has run on hardware. Real timing, cache behaviour when streaming from SDRAM, and whether the free SDRAM at `0x44050000` is really usable are unverified.
- How mute and solo on the right-hand track behave, and where velocity is applied.
- The UI still shows Twinshot's knob names, ranges and defaults.

## Phase 6: the built image (2026-10-04, OS 1.42)

`make image` writes `build/Syntakt_OS1.42_sampler.syx`. Report: `docs/REPORT.md`. Tool `tools/build.py`, tests `tests/test_build.py` (8 tests).

- Only section 7 changes: 2,540 bytes inside 5 declared regions (two caves, three pointers). File size, transport parameters, container header and table are unchanged; sections 1, 2, 3, 4, 5, 6, 8 are stored byte for byte as in the official file.
- The build is reproducible on this machine (same bytes twice). The hash depends on the compiler version, so it is not pinned.
- A patch with wrong stock bytes stops the build. The built file is refused by `fw.load` as unofficial.
- Section 7 decoded back out of the built file plays bit-identically to the reference model.
- elektron-firmware-tool reads the built file with every checksum ok and extracts the intended section 7 and the stock others.

OPEN: everything in the "needs a real unit" table of `docs/REPORT.md`.

## Phase 7: main CPU patches (2026-10-04, section 3 of OS 1.42 only)

`make image-full` writes `build/Syntakt_OS1.42_sampler_full.syx`. Code `engine/mixlink.c`, builder `tools/build_main.py`, tests `tests/test_mainpatch.py` (12 tests). `make test` is 176 tests.

Knob descriptors (data only):
- Record fields, by comparing machines: `+0x08` min, `+0x0c` max, `+0x10` default (8.8), `+0x14` is 1 only on the 40..88 tune-style knobs (taken to be "show as bipolar"), `+0x18` high byte counts the knob position, `+0x1c` and `+0x20` are per-parameter ids, `+0x28` long name, `+0x2c` machine tag, `+0x30` short name. INFERRED from the table alone.
- A second table at `0x4022ccbc` maps parameter id (0..735) to its record; no code compares against the sampler's ids directly.
- Machine 44's records are at `0x40233d30`. Patched: ranges and defaults of slots 20..23, the bipolar flag of slot 22, and the names. New names reuse strings already in the image where one exists (several are the tails of longer strings) and overwrite five strings that only these records point at. Strings shared with other records are not touched.
- Read back through `tools/params.py`: TUNE, SMPL, STRT (default 0), LEN (default 127), LOOP (0..127), MODE (0..15), OVER, DEC. Every other descriptor is identical to stock.

Where new main CPU code can live:
- **The blank area syntakt-firmware-workbench uses for its main CPU code is not free on 1.42.** `0x402b9e3c..0x402bbc3c` is 7,680 zero bytes, but it is the tail of a 128 x 128 table of longs at `0x402abc3c`, indexed as `(a << 7) + b` by the sound conversion code at `0x400ad524`. The zeros are the table's rows 113..127, real data. Their cave on 1.41 sits at the matching place. We did not use it. Whether this bites them depends on whether those rows are ever looked up; we have not established that.
- Instead: a scan of section 3 for functions nothing references, counting calls, branches, address operands, every 32-bit value in the image, and the targets of all 127 switch tables. 110 candidates, 6,224 bytes. The largest, `0x401011e4..0x40101370` (396 bytes, two functions that look like the unused twins of a constructor), holds the mixer link.
- This is static evidence only. Unlike section 7, nothing here can be run to watch it stay untouched.

Mixer link:
- The mixer `0x4008f242` has exactly one caller, `0x400a5046`, with arguments `(?, ?, params)`. It reads the track parameters only through that pointer and never writes through it.
- Besides PAN and VOL it reads per track: sends at `+118` and `+120`, a routing word at `+126`, a level word at `params + 2*track`, and another at `0x80004670 + 2*track`. The two level words feed the gain function `0x4008edc0`; what they are called in the UI is not known (velocity and track level are the candidates).
- `mix_link` replaces the call. For each track with machine 44 and the stereo bit in MODE, it copies bytes 118..127 and both level words to the next track, forces the pans to 0 and 127, calls the real mixer, and restores everything in reverse order. 284 bytes.
- Emulated with the mixer stubbed: the mixer is handed exactly that, the return value and arguments pass through, the data is byte-identical afterwards (also with every track linked to the next), tracks 9..12 are never touched, and the forced pans give (1.0, 0) and (under 1e-8, 1.0) through the real pan law.

Container: section 3 is compressed, and repacking 429 changed bytes grows it by 616 bytes, so the file gains six packets. `fw.verify` now lets the packet count follow the container; product, checksum seed and start sequence must still match. The audio-only build still requires an identical file size.

OPEN:
- The whole main CPU side is unverified beyond the above: no run of the real mixer with the link, no UI.
- The meaning of the two level words, and a per-track curve selector (byte 205 of a 291-byte structure) that is not linked.
- Whether the MODE knob, formerly Twinshot's second sample selector, has display code of its own. ANSWERED in Phase 8: it has, and the full image now replaces it.
- Mute and solo of the right-hand track.

## Phase 8: how knob values are shown (2026-10-05, section 3 of OS 1.42 only)

Tool `tools/uitable.py`, patches in `tools/build_main.py` (`DISPLAY`), tests in `tests/test_mainpatch.py` (16 tests).

- The descriptor records hold no display format. All 505 records are one array at `0x4022d83c` (`tools/params.py` reads two runs of it); the table at `0x4022ccbc` maps a parameter id to an index in it. Machine 44's records are 497..504.
- A start-up routine, `0x40188796..0x40196ab8`, builds about 170 function objects in RAM and then fills a display table at `0x41ba0a24`: one 84-byte entry per record. `+0x00` flags, `+0x04` 16 bytes of knob behaviour copied from a template, `+0x14` text, `+0x24` graphic, `+0x34` not named, `+0x44` the FUNC + turn step. The accessor `0x4007ba2a` returns `table + 84 * index` for index < 505, and `0x4007bbe2` calls the text function. CONFIRMED by reading the routine as straight-line code: 2,559 calls, every target resolved, 502 entries with a text function.
- Text functions: `0x4006f930` prints the value as a plain number (the most common), `0x4007bc8a` subtracts 64 first, `0x4007bc50` is the tune text, `0x4007ba80` is the sample slot text (slot number, counted back from 64 below the middle).
- **This matches the hardware log**: stock FLT1 and MIX use the minus-64 text (the maintainer read -64 and +63), SMP2 uses the slot text (read -64 at the left end).
- Flags value 4 is on 32 entries, all stepped choices (NOTE, MODE, MULT, DEST, the two sample selectors). INFERRED: "do not sweep this". Left as it is on MODE.

Patch: ten operands inside that routine, each the address of a function object, swapped for the object plain 0..127 knobs use in the same field: text, graphic and step of START, LENGTH, LOOP and MODE (START and LENGTH already had the plain step). Tests: read back, only entries 499..502 differ; each new object is used by 40 or more stock knobs in that field, is copied by the same routine, and is built before the patched instruction runs.

This closes the Phase 7 question about MODE's display. Without this patch the full image would have shown START and LENGTH as -64..+63, LOOP as a tune value and MODE as slot numbers.

NOT CONFIRMED: nothing here has run. The knob behaviour template of LOOP is still the tune one (FUNC + turn step of 12 in the template; its role next to the step function is not known).

Mixer link, looked at again the same day (static only, no new test):
- The real mixer could not be run here in reasonable time: its first helper (`0x4009748c`) and its effect stages work on state and buffers set up elsewhere. (2026-10-09: it runs whole with those made returns, `tests/test_mixer_whole.py`.) The link is still tested against a stand-in for the mixer only.
- The mixer's per-track loop also reads two things the link does not copy: a bit per track from a mask word at `0x80003148` or `0x8000314c` (used only when the routing word at `+126` is non-zero), and byte 205 of a 291-byte per-track structure reached through `0x800030b8`, passed to the gain function as its fourth argument. If the two tracks of a pair differ in either, left and right gain can differ. Whether either is mute is NOT CONFIRMED.
- The link changes the parameter block only for the length of the mixer call and restores what it saved. If something else writes one of those twelve bytes in that window, that write is lost. Whether anything can (the call's context was not established) is NOT CONFIRMED.

Full image after Phase 8: `build/Syntakt_OS1.42_sampler_full.syx`, 2,572,960 bytes, SHA-256 `7043772c78587e0a48c24f9e2f4be080537b7a59ee5546926d582ace421338dc`. `make test` is 184 tests. The audio-only image is unchanged (`2cca1fdf...e833`).

## Sample limits on the main CPU: not located (2026-10-05, section 3 of OS 1.42)

Located on 2026-10-07: see "The 5 second limit is the +Drive's slot size" below. The constants listed here were the wrong ones to look for; the limit is a count of sectors.

The manual gives 5 s per slot and 32 MB in total. Where these are enforced is **unknown**. Constants that looked like the limits were checked and are something else:

- `0x4008eb24` (480,000): entry 127 of a 128-entry time table at `0x401dac7c`, compared with a running counter. An envelope or timer stage, not a sample length.
- 240,000 at `0x401dc078`, `0x401dc67c`, `0x401e8264`: all inside data tables of the same kind.
- 32 MB at `0x40005476` and `0x400054a2`: sizes of memory regions set up at boot (32 MB or 4 MB by a flag), next to hardware register writes. Not shown to be the sample pool.
- 32 MB at `0x4008af0a`: a bit set in a hardware register at the end of an interrupt handler.
- 32 MB at `0x4015fc12`: inside a soft-float conversion routine.

So nothing here supports "patch the main CPU to lift the caps". The limits may sit in the sample file code (class names `SampleHandler`, `MidiRpcFsSample*`, route `/samples`), or in Elektron Transfer on the computer. Not traced. The section also holds directory and "list, assign, clear RAM" message types from Elektron's shared file-transfer library; whether the Syntakt uses them is not traced either.

What is known on the audio side stands: the pool is 64 MB and the engine plays up to 10.9 s per slot.

Cheap check for the maintainer, no patch needed: drop one mono 48 kHz WAV of 10 s into Transfer and listen to how much of it the unit plays.

## Sample prep and real slot sizes (2026-10-05, section 7 of OS 1.42)

The maintainer's use is plain stereo samples of up to 5 s: one L slot and one R slot each, MODE 4, no chain. 64 slots hold 32 of them. Chain stays in the engine as an option.

- `tools/split_sample.py` takes files and folders. Up to 5 s: `name_L.wav` and `name_R.wav` (or `name.wav` for mono), nothing cut. Longer: cut into 5 s samples. A set over 64 slots is refused with a plain message. Sample rate conversion uses afconvert's best setting. Always 16-bit 48 kHz.
- Every engine test so far used slots of at most 1,500 frames. Now, with the real section 7 code in emulation:
  - a stereo pair of 240,000 frames a side in the last two slots, MODE 4: both channels equal the source sample for sample, then silence. The pair before it stops at its own end and nothing of the next pair is heard (`tests/test_split.py`).
  - one run by hand, not in the suite (5.7 minutes): a 2:29.7 stereo file as 60 slots of 239,533 frames, slots 4..63, MODE 12. 7,187,232 frames compared on both channels, 0 differ. So positions near the top of the 20.12 range, 29 seams and a chain that ends on the last slot all behave.
- Not known: whether Transfer keeps a file of exactly 240,000 frames whole. For samples that are not chained, a few frames lost at the end would not be heard.
- `samples/stereo_test.wav`: a check sample for the unit. Bass line on the left only, high plucks on the right only, a voice saying "left" (left), "right" (right) and at the end "both" (both sides). 5 s, 8 beats, loops.
- 2026-10-06: `make samples` turns whatever is in `samples/` into `build/samples/transfer/`, every file name starting with its slot number (`01_name_L.wav`, `02_name_R.wav`), plus a slot list. The numbering is the idea of sinedied/sympakt (MIT, a sample pack builder for stock Twinshot; it does not talk to the unit and holds no facts about the 5 s limit). No code taken. Not checked: whether Transfer assigns slots in name order.

## Audio mute (2026-10-06, section 3 of OS 1.42 only)

Maintainer's request: the mute button should cut the audio, not only stop new trigs.

Where mute lives. All read from our listing; none of it run:
- Global mutes: a 32-bit mask at project settings + 36, one bit per track (0..11, 12 = FX). Set and cleared at `0x400203c8..0x400203f8`; that routine then sends `ProjectSettingsTrackMuteChangedInfo`. Copied to `0x80003048` at `0x400a3408`. The long at + 40 goes to `0x8000304c`.
- The per-block routine `0x400a38ce`, which holds the one call to the mixer, reads both at `0x400a39a0`: the mask it uses is `0x80003048`, or the complement of `0x8000304c` when that is not zero. So `0x8000304c` is solo. INFERRED from that use and from descriptor records 7 "Solo", 8 "Mute", 9 "Pattern Mute".
- Pattern mutes: a word at `0x43bdd828`, stored by `0x400a30b2`. The listener for `PatternSettingsTrackMutedInfo` (`0x40019b66`) calls it with the word at pattern settings + 16.
- At `0x400a421a` the routine tests the track's bit in the mask above, then in `0x43bdd828`. Either one takes the muted path. That is the stock mute: it acts on trig events, and the mixer is not told.
- The words the mixer does read (`0x80003148..0x8000314e`) are **not** the mute buttons. They come from kit + 5452/5454, or project settings + 250/254 when the kit's are switched off, and switch each track's FX block feed and delay/reverb sends. This answers the question left open in Phases 7 and 8.
- The mixer's gain function `0x4008edc0(level, level2, vol, curve)` is curve[level2] times (vol times level) squared. Run in emulation: volume 0 gives exactly 0. Pan and send gains are multiples of it, and the mixer ramps every gain over the 32-frame block.

Change: `mix_link` now also shows the mixer a volume of 0 for every muted digital track (1..8) for the length of the call, then puts the word back. Muted means the rule above. The right-hand track of a stereo pair takes its left track's state and ignores its own. The code is now 396 bytes: the cave is full. The build asserts the four stock instructions that read or write the three addresses.

Tests (`tests/test_mainpatch.py`, 21 in all): against the stand-in mixer, as for the link. Global mutes, pattern mutes, solo, pairs, analog and FX bits ignored, everything put back.

NOT CONFIRMED, needs the unit: that these three addresses are the mute buttons at all (static reading only); that a 0.7 ms fade does not click; what the MIDI setting MUTE DEST = EXT does to it. Unchanged and expected to stay: trigs do not fire on a muted track, analog tracks mute the stock way.

Full image with audio mute: SHA-256 `9180bda1d333e85961aa40d5de8b3ae929c36083d4c268f61364f88c36d3a5bb`. The one flashed on 2026-10-06 is kept as `build/Syntakt_OS1.42_sampler_full_no_audio_mute.syx` (`7043772c...38dc`). `make test` is 193 tests.

## Where the analog tracks and the external input are (2026-10-06, section 3 of OS 1.42 only)

Maintainer's question: could a recorder take the analog tracks and the external input, not only the 8 digital tracks. A trace, nothing built. Constants in `tools/mainmap.py`, tests in `tests/test_inputs.py` (8).

Answer: **the audio is there.** Tracks 9..12, the external input and the FX block return all reach the main CPU as plain samples, every 32-frame block, in buffers our mixer hook already sits next to. The audio CPU never sees any of it.

Path, in order:
- eDMA channel 52 (TCD `0xfc045680`, set up at `0x4000101a..0x4000108c`) copies a serial audio port's receive register (`0xfc0c8008`) into a ring at `0x80001800`: 8 slots of 32 bits a frame, 2 x 32 frames, wrapping. The per-block routine `0x400a38ce` reads the channel's write address to pick the fresh half.
- `0x400962ac(half, frame)` unpacks that half into a 20-channel frame buffer at `0x80004760` (32 frames x 20 longs). Every slot is negated and moved from 24 to 32 bits; slots 0..3 also get one fixed trim gain (about 1.68).
- `0x4008ee86(inputs, frame)` copies the 8 input channels to 8 mono buffers at `0x80003950` (128 bytes each, same shape as the digital track buffers right after them at `0x80003d50`). Then `0x4008ec34` and `0x4009580c` work on them in place, then the mixer is called.
- Slot to buffer: slots 0..3 are buffers 0..3 (tracks 9..12), slots 4, 5 are buffers 6, 7 (FX block return L, R), slots 6, 7 are buffers 4, 5 (external input L, R).
- The mixer's last step (`0x4008fbec..0x4008ff1a`) fills the same 20-channel frame for output: 0, 1 the main bus; 2..9 tracks 1..8; 10..13 tracks 9..12; 14, 15 FX return; 16, 17 the two send buses summed; 18, 19 still the external input as unpacked. So after the mixer returns, `0x80004760` holds every signal in the unit at once.

How each was shown:
- DMA setup, the call order before the mixer, and the frame fill: read from the listing, operands asserted by the tests.
- The slot mapping, sign and the 24 to 32 bit shift: both copy routines **run in the emulator** on a ring where every slot of every frame carries its own number.
- Tracks 9..12 are buffers 0..3: the mixer's 12-track gain loop takes track i from `0x80003d50 + 128 i` for i < 8 and from `0x80003550 + 128 i` for i >= 8.
- Buffers 6, 7 are the FX return: `0x4008ec34` runs four voices with the parameters of tracks 9..12, then one stereo pair at +768 and +896 with the parameters of track 13 (params + 12 x 142).
- The slot names: the factory test's own table of 8 names at `0x401e9568` reads voice 1..4, FX L, R, ext in L, R, in that order. The external input pair is then the one left over, and the table agrees.

INFERRED, not confirmed:
- That `0xfc0c8008` is a serial audio (SSI) receive register: by its address in the MCF5441x family only.
- That the 20-channel frame is what goes to USB audio. It matches an Overbridge channel list in size and order; the USB side was not traced.
- That channels 0, 1 are exactly what the main outputs play. The main out and FX send leave on the transmit side (ring at `0x80000000`), with dither, and part of the path is analog.
- What tracks 9..12 sound like at this tap (before volume and pan, after `0x4008ec34`). Not rendered: no converter data exists in emulation.

What a recorder would still need (none of it started):
- More main CPU code space. The cave at `0x401011e4` is full.
- A way to carry the audio to the pool on the audio CPU. The boot loader writes its 2 KB chunks straight into the shared window at `+0x800` and the audio CPU copies them out from there, so that half of the window is real memory on both sides and idle after boot. Whether it can be written while the per-block DMA runs is not known. One block of stereo 16-bit is 128 bytes.
- A way to keep a recording: the path back to the +Drive is not traced, so it would be lost at power off.
- Something to start and stop it. No screen code has been read.

## The recorder, first cut (2026-10-06, sections 3 and 7 of OS 1.42)

Maintainer's request: resample into a slot, the main mix or the external input, started from a knob, in memory only. Built as a third image so the two that exist stay byte for byte what they were (`make image-rec`, SHA-256 `032788df...5c8c`; audio `2cca1fdf...` and full `9180bda1...` rebuilt and compared). Use: `docs/SAMPLER.md`, Recording. Tests: `tests/test_recorder.py` (48). **Emulation and static reading only. Not flashed.**

Design, and why:
- The source audio only exists on the main CPU (entry above), the pool only on the audio CPU. So the main CPU has to send it across. It goes through the shared window at `+0x800`, the 2 KB the boot loader pushes sample chunks through: the one part of the window known to be memory on both sides and idle after boot.
- Main CPU (`engine/recfeed.c`, 172 bytes): wraps the mixer link. After the mixer returns it looks for a digital track whose knobs say sampler and MODE 16 or 17, and copies channels 0, 1 (main) or 18, 19 (external input) of the 20-channel frame, top 16 bits, into the next of 8 ring blocks, then writes the counter. The counter is read back from the window, so the code keeps no state. No track recording: no write at all.
- Audio CPU (`engine/sampler.c` with `RECORDER`, 344 bytes more): a note that starts in MODE 16 or 17 starts a take instead of playing. The step after the voice loop appends every ring block not yet seen to `0x44080000 + 0xf0000 * slot` (left) and the next slot's buffer (right), and writes length and pointer into the slot table. Note-off, 491,520 frames, a new trig, MODE moving, or falling more than a ring behind ends it.
- The feed stays out of that window while the boot loader owns it. `0x43bdd824` is the main CPU's "audio CPU is running" flag: one routine sets it (`0x400a37c0`, called at `0x400831b0`, the last state of the boot handshake, after the sample chunks) and one clears it (`0x400a37ca`, called at `0x40082da4`, where the audio CPU is restarted). The per-block routine tests it before each of its own three exchanges (`0x400a47f0`, `0x400a4ae4`, `0x400a4e34`). The feed tests it too. Without that, a project that boots with a track in MODE 16 could have had feed blocks land in sample chunks on their way to the pool. Read from the listing; the build asserts the three instructions.
- The ring and counter make the hand-over safe whichever side runs first: the counter is written after the samples, and a block is not overwritten for 8 mixer calls.

Code space:
- Main CPU: `0x4008f13e..0x4008f22c`, 238 bytes, three functions. They are mix kernel variants (6 and 4 sources, and an interleave) between the kernel the mixer calls (`0x4008f0b6`) and the copy helper it calls (`0x4008f22c`). Nothing references them: same static scan as the first cave, now one test for both (`tests/test_mainpatch.py`). A scan of the whole of section 3 for runs like this finds 380 of them, 51 KB, the first cave among them at its known size.
- Audio CPU: `0x40004a6a..0x40004cd6`, 620 bytes, three functions right after the stock mix routine. Held to the same two tests as the sampler's runs: unreferenced, and never run or read while every stock machine plays through the real interrupt.

Shown in emulation:
- A take is exactly what was fed, in order, left and right apart, and as long as its note: trig in block T, note-off in block R, R - T blocks. Through the hook, and once through the real audio interrupt for the note-off.
- Nothing lost or doubled with the feed running 0 to 8 blocks ahead. Nine ahead ends the take.
- Ends exactly at the buffer's end; nothing written past the right-hand buffer. Slot 64 takes left only and nothing is written past the slot table.
- Other machines and MODE 0..15 never record. A recording track renders silence.
- A take played back in MODE 5 is bit-identical to the same audio loaded as two slots in the image without the recorder.
- Playback in nine modes and all 11 other machines: bit-identical with and without the recorder.
- Main CPU feed, mixer stubbed: one ring block and the counter change in the window and nothing else; the frame, the parameters and the mixer link's work are untouched; the first recording track picks the source; the counter wraps; no write while the audio CPU flag is clear.
- Both sides joined by carrying the window's bytes across: frames given to the main CPU's code come out of the audio CPU's slot.
- Cost on the audio CPU: 122 instructions per block with the recorder present and idle, 570 while taking, against 10,506 per voice.

Found on the way:
- A voice only takes its machine's engine in the block after a trig. A take is therefore started by the note start (the sampler's own note-on path), not by the trig bit: the first trig after choosing the machine would otherwise be missed.
- The voice loop hook reads the trig and release masks from d2 and d4, where the interrupt keeps them, not from its arguments. The emulator harness for the hook now sets them (`HookEngine`).
- `--param=min-pagesize=0` is now a compiler flag: without it GCC 16 treats the window at address 0 as a null pointer. The sampler's and the mixer link's code came out byte-identical with it.

NOT CONFIRMED, needs the unit:
- That the window at `+0x800` can be written by the main CPU and read by the audio CPU while the unit runs. Only its use at boot is seen.
- That channels 0, 1 of the frame are the main mix as heard. Read as: post-FX bus plus a mix of the inputs (`0x4008fb7c..0x4008fbe6`), scaled by 8. Not rendered.
- Level and polarity of a take against the original.
- That a trig's length reaches this machine as a release bit.
- Main CPU time for 65 window writes a block.
- That free SDRAM up to `0x47c80000` is all there. The top of it is the stack, and `0x44050000` is known good from the stereo test.

## Audio mute on the analog tracks (2026-10-06, section 3 of OS 1.42 only)

Maintainer's request, after the digital mute worked on the unit. The mute loops in `engine/mixlink.c` now run over 12 tracks. Same 396 bytes.

Why it should work, read from the listing: the mixer's level loop (`0x4008f296..0x4008f4ec`) runs 12 times at 142 bytes a track and reads `params + 124` once per pass (`0x4008f2b6`), and the mute mask has a bit per track for all 12. Tracks 9..12 are the first four input buffers (entry on the inputs above). The test asserts the loop's bound and step.

Tests (`tests/test_mainpatch.py`): global and pattern mutes on tracks 9..12, solo of a digital or an analog track muting the other 11, the FX bit (12) ignored as a mute and counted as a solo, everything put back.

NOT CONFIRMED, needs the unit:
- That a muted analog track is silent. The maintainer reports that with a third-party looper app switched to its loop, the analog tracks are still heard while the rest is not. Not explained. If some analog sound reaches the outputs around the mixer, this patch cannot mute it. AMP VOL at 0 sets the same word and is the same test without flashing.
- Clicks: an analog voice is muted mid-decay over 32 frames.

Images: full `6c02aa05...a9b4`, recorder `b901468a...fe52` (it shares the code; still never flashed). Audio-only unchanged. Older full images moved to `build/old/` under their hashes: `9180bda1` (digital mute only, known good on the unit) and `7043772c` (no mute). Earlier entries name them by their old paths.

## Analog mute, second build: the dry level controls (2026-10-06, section 3 of OS 1.42 only)

After the mixer version failed on the unit (hardware log). `engine/amute.c`, 142 bytes, in front of the mixer link. Tests in `tests/test_mainpatch.py`. **Not flashed.**

Where an analog track's dry level is set, read from the listing:
- The per-block routine keeps a control block at `0x80003160` and sends it to the hardware after the mixer call (`0x400a537c`: `0x401021b4(block)`). It is filled before the mixer call, last at `0x400a4fbe`. Nothing between the mixer call and the send names the block.
- Its first words are the level controls: words 0..3 left of voice 1..4, 4 external input left, 5..8 right of voice 1..4, 9 external input right. The layout is the service view's table of named controls (`0x443dac54`, one word each, "left" and "right" per voice), which that mode copies over its own block in the same order.
- `0x4008ffc0(block, params, voice, track)` makes the two values: a level built from the track's volume word (`params + 124`), times the pan law's left and right gains for `params + 122`, each capped at 65535 and stored at `block + 2 voice` and `block + 10 + 2 voice`. So 0 is shut and the values are made fresh every block.
- Voice v is track 8 + v (byte table at `0x402a2138`).

The patch: with the mute rule of the mixer link (global mutes, or all but the solos, or the pattern's mutes), set both words of each muted analog voice to 0. Nothing is saved or restored, since the OS makes the block again next time. The mixer link still shows the mixer a volume of 0 for these tracks, which cuts the digitised copy: sends and USB channels.

Code space: `0x400a15cc..0x400a1734`, 360 bytes, one function nothing references, ending where the pan helper starts. Held to the same static test as the other two.

Shown in emulation, mixer stubbed: the right two words go to 0 for global and pattern mutes and for solo, of digital and analog tracks; digital and FX track mutes touch nothing in the block; the external input's words and the rest of the block are untouched; the mixer link is handed exactly what it was before.

NOT CONFIRMED, needs the unit:
- That 0 in those two words silences the voice. Read from the code and consistent with the maintainer's volume control silencing the track; not seen.
- That the block is not changed again between the mixer call and the send by something that does not name it directly.
- Clicks: the level is shut within one block (0.7 ms), with no ramp of ours.

Images: full `112077eb...90e6`, recorder `5284426f...5927` (still never flashed). Audio-only unchanged. The mixer-only analog mute image is kept as `build/old/full_analog_mute_sends_only_6c02aa05.syx`.

## Recorder: dither and take level (2026-10-07, sections 3 and 7 of OS 1.42)

Maintainer, with the first cut running: takes come back too quiet, "i have to add all the overdrive and all the track and sample volume to get good levels", and asked for dither and "a bit more gain on the resample without sacrificing a control for it". Recorder image only. **Not flashed.** Image `67164f3e...aa74`. Tests: `tests/test_recorder.py` (56), 262 in all.

Where the level goes, measured by running the real code:
- The sampler voice hands on a sample at half scale (gain `0x40000000`, as one of Twinshot's two layers). Exact.
- The stage after the voice loop (`0x4000112c`, tied to OVER) takes a full-scale 1 kHz sine down another 6 dB at OVER 0. At OVER 127 it gives 2 dB back, by clipping: the overdrive is a gain in front of a limiter. That is the "low quality" in the maintainer's takes: the level was being made up with distortion.
- The mixer's gain function (`0x4008edc0`): -6.6 dB at the default track level (100) and AMP VOL (110), 0 dB at 127 and 127. Then the fixed times 8 at the end of the mixer.
- NOT MEASURED: the track filter and amp stages. Their gain depends on a cutoff word the main CPU works out, which our harness does not know how to set. So the whole chain's gain at any setting is not known here.

Change 1, level: a take plays at full scale (`0x7fffffff`), a loaded sample at half as before. Decided per note from where the slot's data lives. Full scale is still inside what stock hands the later stages (two layers at once), and it cannot clip: a 16-bit sample times one fits. With LEVEL and AMP VOL at maximum that is 12.6 dB more than a take at default settings had, without the overdrive. More than that (twice full scale) would clip any take that peaks above -6 dB, so it was left out.

Change 2, dither: the main CPU's copy rounds each 32-bit sample to 16 bits and adds triangular dither of one step (the difference of two 16-bit numbers from a 32-bit linear congruential generator), with the result held inside the 16-bit range. The generator's state is a long in the window next to the counter, so the feed still has no memory of its own. The conversion loop is 168 bytes and sits in the room left after the analog mute (`0x400a165a`), which the unit already runs with our bytes in it; the rest of the feed stays where it was (156 bytes). The two are linked together for this image.

Shown in emulation: the compiled conversion equals a Python model of it for every sample, with the generator carried from block to block; the error stays within 1.5 steps, has no offset (cutting off sat at half a step) and a size of half a step, which is what rounding plus this dither gives in theory; constant inputs of 0.25, 0.5, -0.6 and 3.1 steps come out averaging to themselves; full scale either way never wraps. A take plays at twice the level of the same samples loaded as slots, to within the stock mixing routine's rounding; a full-scale take reaches the top and does not pass it; a sample played after a take by the same voice is bit-identical to the image without the recorder. The audio-only and full images build to their known hashes.

Order of things in the voice changed, recorder image only: the note is started before the gain is set, since the gain now depends on which slot the note plays. Playback of loaded samples stays bit-identical to the other images (nine modes).

NOT CONFIRMED, needs the unit: that takes are now loud enough; that the dither is inaudible in practice; main CPU time (the conversion is two multiplies and a clamp per sample, 64 samples a block).

## LOOP and MODE: one job each (2026-10-07, sections 3 and 7 of OS 1.42)

On request. All three images change. **Not flashed.** Tests: 272 in all, `tests/test_recorder.py` 59.

What the knobs mean now (`docs/SAMPLER.md`):
- LOOP (slot 22): 0 off, 1 loop, 2 ping-pong. The engine reads its low two bits (3 is ping-pong too). On the audio-only image that knob is TUN2, 40..88 with 64 as default: off at the default, loop and ping-pong one and two steps up.
- MODE (slot 23), low two bits: 0 mono, 1 stereo, 2 record the main mix, 3 record the external input. Bit 2 is chain, so 4 and 5 are chained mono and stereo. Built without the recorder, 2 and 3 play as mono.
- The loop point is gone. A loop goes back to where the note started: the start of the region, or its end when reversed. The state keeps its loop fields, set from the region's ends.
- Full and recorder image show LOOP 0..2 and MODE 0..5. The descriptor table is now the same on both; the recorder image no longer has its own MODE limit.

Why this order: the maintainer's use is 0..3 (mono, stereo, the two record sources), next to each other, and chain, which is not the maintainer's use, sits above them. Record to play is one step of the knob, and LOOP keeps its setting through a take.

Cost of that order: "stereo" is one value of two bits, no longer one bit, and the test for it is 2 bytes longer. The mixer link's code space had none to give (396 of 396). Compiled with `-fno-reorder-blocks` it is 394; without, 398. The option is given for that one source in `tools/build_main.py`. A function attribute was tried first and is not usable: it drops `-fno-builtin` for the function, and a call to `memcpy` appeared.

Record is not stereo, on either CPU: the track after a recording track keeps its own sound, parameters and trigs (audio CPU test), and the mixer link leaves it alone (main CPU test, with the higher bits of MODE set too).

**Sounds saved under the older images read wrong now.** Old MODE 4 (stereo) is chained mono today, old 1 (loop) is stereo, old 16 and 17 are outside the knob's range. LOOP and MODE have to be set again on those tracks. Nothing converts them.

Found on the way, in the images flashed so far: **a loop of a few frames played octaves up could cost more than the budget.** The old worst case test leaned on the loop point, so it had to be made again, and a search around it found worse than it ever reported:

| committed engine (old knobs) | per voice per block |
|---|---|
| the test's worst case (stereo chain, ping-pong, loop point 124, 3 octaves up) | 5,150 |
| the same with the loop point at 127 | 13,404 |
| a 6 frame region around a slot seam, ping-pong, 3 octaves up | 15,594 |
| budget (SY SWARM) | 10,506 |

A seam or a turn costs about 135 instructions, and the old limit was 8 of them per frame. Now a voice gets 40 per block (`MAX_EDGES`) and the note stops past that. It takes a loop shorter than 0.8 of what the pitch travels in a frame to get there: under 7 frames at 3 octaves up. After the change the worst that keeps playing is 7,848 and the worst single block 9,075 (a sweep of 14 cases in `test_instruction_budget`, some that play on and some that stop). Whether the unit ever had trouble from this is not known; it would have taken that patch on several tracks at once.

Other numbers after the change: idle 1,153, mono 2,176, stereo 2,904 per voice per block; the step after the voice loop 196 per block (177 before, measured the same way; the 156 in older entries was an earlier count). Code: 1,932 bytes on the audio CPU (1,992 before), 142 more and 226 in the third run with the recorder.

Images:
- audio only `5d9d47598850ea59c4ee725b6f87e5e58ddd1c0389d0a7080eec4e88d58c188c`
- full `284821f050f38f5ce703df08931a4e16ae6473c54ad834c3e45e9d63d7e3d1c8`
- recorder `2c122e2ea8ba9f4899ebf73b19001f4d5842aa2b380da69f1bad12927a12012b`

elektron-firmware-tool reads all three with every checksum ok and extracts the 8 sections we intended. The images they replace are in `build/old/`: `full_old_knobs_known_good_112077eb.syx` (the one confirmed on the unit), `rec_dither_gain_old_knobs_67164f3e.syx` (never flashed), `rec_first_cut_5284426f.syx` (on the unit when this was written), `audio_only_old_knobs_2cca1fdf.syx`.

NOT CONFIRMED, needs the unit: that LOOP and MODE read 0..2 and 0..5 as plain numbers and turn one value a click; everything listed under the dither entry above, which is in this recorder image too and was never flashed by itself.

## SMPL counts stereo samples (2026-10-07, section 7 of OS 1.42)

On request Offered two ways (count stereo samples, or keep slot numbers and skip the right-hand ones at two clicks a sample); the maintainer took the first. All three images change, audio CPU only: section 3 is the same bytes as in the entry above. **Not flashed.** Tests: 275 in all.

- In stereo (MODE 1 and 5) and record (2 and 3) the number SMPL gives is doubled: number n, counted from 0, is slots 2n and 2n + 1. On screen and in Transfer, counted from 1: SMPL n is slots 2n-1 and 2n. The reversed half of the knob the same. Mono (0 and 4) counts single slots as before.
- Past 31 (from 0) there is no stereo sample: a note there plays nothing and reads no slot, and a record note starts no take. `rec` is now set from that test at every record note, so a take cannot start from whatever another machine left in the voice (test: the voice state filled with a pattern first).
- A take's left slot is always even now, so the checks for "no next slot" came out of the copy loop: a recording block costs 411 instructions, 573 before.
- Built without the recorder, MODE 2 and 3 still play as mono and count single slots.
- The screen: stock text routine `0x4007ba80` shows the knob's value as value - 63 from 64 up and 64 - value below, so 1..64 either way (read from the listing: `moveq #63`, `addil #-63`, `moveq #64 ; subl`). It does not know MODE. In stereo the number shown is the stereo sample, 1..32, and 33..64 are dead.
- `tools/split_sample.py`: a stereo file starts on an odd slot, a slot left empty before it where needed (`place`), and the slot list has a SMPL column. **The maintainer's check set moves**: it was a mono file in slot 1 and pairs on 2-3 and 4-5; it is now 1, then 3-4 (SMPL 2) and 5-6 (SMPL 3), with slot 2 empty. With this image the old arrangement cannot be played in stereo.

Code: 1,940 bytes on the audio CPU, 146 more and 206 in the third run with the recorder. Worst single block 9,079 (9,075 before), mono and stereo unchanged.

Images:
- audio only `616b0b48a4946939724f5a73251f53ee65607d9338618581d32a18bc74c00734`
- full `298db27b86978f46294b23246951bac559d7923faf5f947d5bab9ce7352c7b63`
- recorder `f6b57f5082083bf52a528475723b3fbf98192318a83fd799bd18c36cd1619234`

elektron-firmware-tool: checksums ok and all 8 sections as intended, for each. They replace the three of the entry above, which were never flashed and are not kept.

NOT CONFIRMED, needs the unit: everything, as above. Also not known: whether the SMPL screen marks the reversed half (the maintainer saw SMP2 read -64 at the left end on the audio-only image).

## The 5 second limit is the +Drive's slot size (2026-10-07, section 3 of OS 1.42)

On request, and asked for a way round Transfer's cut, looking at both Transfer and the OS. Static reading only; nothing was run and nothing built. Tests: `tests/test_sample_store.py` (6), addresses in `tools/mainmap.py`.

**The limit is the unit's own storage layout, not Transfer.** The main CPU's sample store (object from `0x4016f292`) addresses the +Drive in sectors of 512 bytes and gives every slot a fixed run of them:

- Slot s (0..63) is sectors `8192 + 1024 s`: 512 KB each, from 4 MB to 36 MB on a drive of 768 MB (the write routine `0x40111628` refuses a sector past `0x17ffff` or bytes past `0x30000000`).
- Erasing a slot (`0x40111254`) erases exactly those 1024 sectors.
- A slot starts with 64 bytes of header: `SAMP` at +0, the frame count at +8, the name at +12 (16 bytes). The samples follow, 16 bits each.
- At scan time (`0x4011149e`) the header is read, and **the slot is left empty when twice its frame count is more than 524,224**, by the same exit as a wrong magic. So a slot holds at most 262,112 frames: 5.4607 s. A full slot is exactly its 512 KB.
- The store's table is 24 bytes a slot (name, frames at +20). A slot's size as reported to the computer (`0x40111434`) is 64 + 2 x frames.
- The handler behind the route `/samples/<slot>` (`0x400b9dfe`) takes slots 1..64 ("sample slot out of range" otherwise), holds the reported size to `0x80000`, and names the slot's place on the drive as `(slot + 7) << 19`, which is the same 4 MB + 512 KB a slot.
- The boot loader that pushes the pool to the audio CPU steps through it in 524,288s (`0x40082342`, `0x40082390`, `0x40082d32`).

So the manual's "5 s per slot, 32 MB" is this: 64 x 512 KB. The 262,144 frames guessed in the hardware log (32 MB / 64) was right but for the header.

Transfer (the maintainer's copy, 1.10.3, strings only): it asks the unit for `sample_file.mono_support`, `sample_file.interleaved_stereo_support`, `sample_file.sample_rates` and `midi.rpc_file_chunk_size_max`, and the OS holds exactly those `sample_file.` keys. No key carries a length. Its own messages include "Invalid sample header." and "Sample data is truncated." next to its download code, so it reads this header format back. NOT LOCATED: where Transfer decides the length it sends, and whether it cuts at 5.000 s (240,000 frames) or at the slot's 262,112. Byte searches for those numbers in its program found nothing that stands up (the hits for 262,112 are an unrelated `and` with `0x3ff`).

What follows:
- **Bypassing Transfer buys at most 0.46 s a slot.** A longer file cannot be stored in a slot whoever sends it, and a header that claims more makes the unit drop the slot.
- A longer slot would mean a different layout of the drive: the sector arithmetic at every site above, the slot count, the write path (not traced), and samples already on the drive unreadable either way round. And Transfer would still be the only sender. Not recommended, not started.
- **A take of 10.24 s, as the recorder makes today, has no home on the drive.** For a take to go on and off the unit it has to be pieces of at most one slot each. The audio CPU already plays consecutive slots as one sample.
- For saving takes, this is most of the map: where a slot's bytes go, the header to write, the erase and write routines. NOT TRACED: how the stock write path reaches them, what context may write flash (not the per-block routine), and the way back from the audio CPU's memory to the main CPU.

To ask the maintainer: on the 10 s counting file loaded through Transfer, is the start of "six" (5.05 s on) heard? That tells 5.000 from 5.46. (Answered the same day from Transfer's own code, next entry: 5.000.)

## Transfer cuts at 5.000 s by its own constant (2026-10-07, Elektron Transfer 1.10.3, not our code)

On request So the question was whether Transfer would carry a longer slot. Read from the maintainer's installed copy (Intel half of the program, `otool` listing, nothing run, nothing changed, nothing of it kept in this repository). **It would not: the slot size stays as it is.**

- Sending (the routine that writes the `SAMP` magic, at `0x100059887` in that build): the length is `floor(min(seconds, 5.0) x 48000 + 0.5)` frames. The three numbers are constants in the program (5.0 at `0x1006093c8`, 48000.0, 0.5), read out as doubles. Nothing from the unit enters it. So **Transfer cuts every file at exactly 240,000 frames**, 22,112 short of what a slot holds. This closes the open question in the entry above and the one in the hardware log of 2026-10-05.
- The file it sends is the unit's own slot format: `SAMP`, the frame count at +8 high byte first, a name of up to 16 bytes at +12, 64 bytes of header, then the samples high byte first. Size `0x40 + 2 x frames`. That agrees with what the main CPU reads (`tests/test_sample_store.py`).
- Receiving (`0x100069d30`): checks the magic ("Invalid sample header." otherwise), takes the frame count from the header and reads that many samples, "Sample data is truncated." if the data ends first. No upper limit of its own.

So a slot longer than 5 s could at best come off the unit through Transfer, and would be cut to 5.000 s the next time it went back on. That fails the maintainer's condition, whatever the unit's layout. The ways round it are not reliable ones: changing the constant in Transfer (breaks its signature, comes back with every update, and the same pooled 5.0 may serve other code), or another sender.

Another sender exists in part: Elektroid (GPL, GNU/Linux) has an unreleased branch `feat-add-syntakt-samples`; its author wrote on 2026-03-28 that uploads work and that the maximum length was not known to them yet (elektronauts.com, the Elektroid thread, page 15). Not tried, not vendored, and this project does not talk to the unit.

What does carry both ways today: samples of at most 5.000 s a slot, which is what `tools/split_sample.py` already makes, and consecutive slots played as one.

Later the same day the maintainer asked whether that constant could simply be changed. Looked at, nothing changed:
- The maintainer's computer runs the ARM half of the program. There the 5.0 is an immediate in one instruction (`fmov d2, #5.0` at `0x100052740`, followed by the compare and select that make the minimum, then 48000.0 and 0.5). The only other 5.0 of that kind (`0x1002ec950`) is a wait in the message resend loop. So on that half the cut can be changed without touching anything shared; 10.0 is a value that instruction can hold.
- In the Intel half the two share one stored number, so there the instruction would have to be pointed at another one.
- It would be done on a copy, signed again locally, the installed program left alone. The copy would stay at 1.10.3.
- **Changed alone it does harm, not good:** the unit as it is drops a slot whose header claims more than 262,112 frames, and where its write path stops a longer file is NOT TRACED. It only makes sense together with a unit whose slots are larger, and that is a change to the code that writes the +Drive. Not started. What the drive holds past the sample area is still NOT KNOWN (a short look at the storage code found the flash driver, not a map).

Also worth knowing for capacity: what can be loaded from the computer is 64 slots of 5.000 s, 5:20 of mono or 2:40 of stereo. A longer slot would not add to it. More slots might; whether Transfer takes the slot count from the unit, and what the drive holds past 36 MB, are NOT KNOWN.

## The +Drive's map, and room after the samples (2026-10-07, section 3 of OS 1.42)

On request, after being told the drive would be mapped and the write path traced first, read-only. Nothing built. Tests: `tests/test_sample_store.py` (10), map in `tools/mainmap.py` (`DRIVE_MAP`, `DRIVE_FREE`).

How the search was made complete: three routines touch the drive itself (read `0x4010f612`, write `0x4010f7f8`, erase `0x4010f52a`). Their addresses stand in the image only as the operands of 21 calls and `lea`s, all read; no table of pointers holds them. Above them the store has its own read, erase and write (`0x401100d4`, `0x4011015e`, `0x40111628`), reached only by 23 pc-relative calls inside the store, all read. Each call's sector comes from one of the following.

| Sectors (512 B) | Bytes | What | How it is addressed |
|---|---|---|---|
| 0 | 0 | header, 8 bytes | constant |
| 2048 | 1 MB | a table of 272 bytes | constant |
| 4096..8191 | 2 MB..4 MB | sounds, 2048 of 2 sectors | `0x40110c3a`: 2 x (2048 + n) |
| 8192..73,727 | 4 MB..36 MB | samples, 64 of 1024 sectors | (slot << 10) + 8192, (slot + 8) << 10, (slot + 7) << 19 as bytes |
| **73,728..499,711** | **36 MB..244 MB** | **nothing found** | |
| 499,712..507,903 | 244 MB..248 MB | a work area of one project's size | constants at `0x400bd494`.. `0x400bd7b8` |
| 507,904..516,095 | 248 MB..252 MB | a second one | constants there too |
| 516,096..524,287 | 252 MB..256 MB | project number 128 | `0x40110746` |
| 524,288..1,572,863 | 256 MB..768 MB | projects 0..127, 8192 sectors each | `0x40110746`: (n + 64) << 13 |

Also: the factory test console reads and writes a sector typed at it (`0x400806e0`, `0x40081532`), and the file routes (`/projects`, `/soundbanks`, `/samples`) read, write and erase at an address their handler gives, which for samples is the slot's.

**So the 208 MB after the samples is not used by this OS**, as far as its code shows. A second 32 MB of samples would be sectors 73,728..139,263. NOT KNOWN, and not knowable from the image: whether that part of the chip has ever been written on the maintainer's unit and behaves like the rest; what a later OS might put there.

The way a file from the computer reaches a slot: the route's handler gives the slot's byte address; a buffered stream writer (`0x400bbb16` sets it up, `0x400bba38` writes) puts each piece at the current position, 512 bytes to a sector, and moves on. Nothing on that path holds a slot's worth of data or compares against a slot's size. When the file is in, the slot is scanned again (`0x400b9c36` jumps to the scan). The only checks on length are that scan and the sender's own cut. The incoming header is checked for its type alone (`0x400b9d7c`). So today a file longer than a slot would run on into the next slot's sectors and then be dropped by the scan: more reason not to change Transfer's cut alone.

The way a slot reaches the audio CPU at boot: `0x40082334` allocates 524,288 bytes, reads one slot into it through the store (`0x401133ce`, up to 524,288), and feeds it out in chunks. With larger slots that buffer and that read have to grow with them, or the slot be read in parts. NOT TRACED: the timeouts of that exchange (the image has FAILURE_TIMEOUT, FAILURE_BUFSIZE, FAILURE_CF_MEM and FAILURE_DSP_MEM as its outcomes), and whether 1 MB can be allocated at that point.

What a unit with 64 slots of 1 MB would take, as known now: the sample sector arithmetic at its sites (erase, scan, the header read at `0x40113306`, the store's reads at `0x40113436` on and its write at `0x4011246a`, the route's address and its hold at `0x80000`), the scan's limit, the boot loader's buffer and read; on the audio CPU nothing found yet (its pool is 64 MB, and 64 x 480,000 frames is 61.4 MB); on the computer, Transfer's cut at 10.0 s. The slot count stays 64, so nothing that counts slots changes. Samples on the drive would have to be loaded again after the change, and again after going back.

## The pool is staged in a fixed 32 MB at boot: twice the samples needs more than the drive (2026-10-07, section 3 of OS 1.42)

Traced before building larger slots, as agreed with the maintainer. Nothing built. Tests: `tests/test_sample_store.py` (11).

- `0x40082334` builds the whole pool in main CPU memory before the audio CPU gets any of it: a marker byte `0xAA`, 4 bytes of total length, then for each of the 64 slots its frame count (4 bytes) and its samples. It is the audio CPU's pool format. Each slot is first read into a 512 KB buffer from the allocator through `0x401133ce`, the only reader of sample data in the image, which works out the slot's byte address as (slot + 8) << 19 and takes an offset and a most.
- The block it builds in is at a fixed address, `0x4d84f2c0`, and the audio CPU's program is staged at `0x4f84f2c1`: 32 MB and one byte further on. Just under the block is the drive code's 64 KB buffer (`0x4d83f280`). These read as fixed places in the program's own data, not allocations.
- Stock cannot overrun it: 64 full slots are 5 + 64 x (4 + 524,224) bytes, under 32 MB. The loop has no check on the total.

What this changes:
- **Twice the samples does not follow from room on the drive.** 64 slots of 10 s are 61.4 MB to stage, and the block is 32 MB with the audio CPU's program behind it. It would take a second place in main CPU memory of 64 MB that nothing uses (not known: the layout of that memory is not mapped), or a staging loop that fills, sends and fills again (new code in the boot path on the main CPU, and the sender at `0x40082b64` with it).
- Larger slots with the total held at 32 MB are still possible, but the loop would need a check it does not have, or a full set of long samples overruns the block into the audio CPU's program.
- So the earlier line "the audio CPU already has the memory" was true and not enough: the audio CPU's pool is 64 MB, the main CPU's staging of it is 32.

Where that leaves the three ways to longer samples:
- larger slots, same total: a patch to the drive code and the boot loader, a changed Transfer, and no more time than now;
- larger slots and twice the total: all of that, plus new boot staging. Not small, and in the path the unit boots through;
- consecutive 5 s slots played as one: nothing on the main CPU, nothing in Transfer, the same total as now. It is the only one of the three that can be shared as firmware alone.

## Twice the pool: no spare memory, but the sender could go round twice (2026-10-07, sections 3 and 7 of OS 1.42)

Maintainer asked to look further into whether twice the sample time is realistic. Read-only. Tests: `tests/test_sample_store.py` (14).

**The main CPU has no second 32 MB.**
- Startup (`0x400004e8`): stack top `0x48000000`; data cleared up to `0x45566490`; the cache is switched on for `0x40000000..0x47ffffff` only. The allocator's arena is 16 MB inside that data (`0x444e48c0`, from the descriptor at `0x402d5328`).
- The blocks named above the stack top (drive buffer, the pool's 32 MB, the audio CPU's program, 77 addresses in all, `0x4d5cf088..0x4f8af2ca`) fit exactly between the end of the data and the stack once `0x08000000` is taken off: `0x455cf088..0x478af2ca`. No code names an address in that stretch by its lower address. INFERRED: one 128 MB of RAM seen twice, the upper view uncached, and those blocks are what fills the 42 MB after the data. NOT CONFIRMED: the memory controller is set up by the bootstrap, which was not read.
- So the memory is spoken for: 85 MB of program and data, 35 MB of those blocks, 7 MB with the stack in it. A staging block of 64 MB has nowhere to go.

**But the pool does not have to be staged whole.**
- The sender (`0x40082f90`) is a loop: wait for the audio CPU, write command 2 and the chunk's index into the window, copy 2 KB from block + 5 + (index << 11) to the window at `+0x800`, count, signal. It ends when the count reaches (length + 2047) >> 11. The index goes out as 16 bits: 128 MB of chunks can be numbered.
- The audio CPU's end (`0x40000f8e..0x40000fd4` in section 7) copies each chunk to pool + (index << 11) and loops until command 3. No count, no limit, no timeout: it waits as long as it is made to. It would also write past its 64 MB, onto its slot table, if sent more.
- So a pool could go over in two halves through the same block: fill it with the first 32 MB, send, fill it with the rest, send. The reader of sample data already takes an offset and a most, so a slot that straddles the halves can be read in two parts.

What that would take on top of larger slots: a builder that fills one half at a time and holds the total under 64 MB (stock has no check and needs none), and the sender made to refill at the half and take its chunk from index minus the half. New code on the main CPU, in the boot path.

One thing in its way, found: `0x400828cc`, called over and over while the unit boots, counts up `0x41bbf3bc` whenever neither the state nor the chunk count has moved, and past 18 calls sets a timeout status and tries again. Stock builds the pool before the count is watched. A refill in the middle of sending would have to clear that count as it goes. How often the routine is called was not traced.

What cannot be shown here: the exchange between the two CPUs as it runs, how long a refill takes (the drive's read speed), and the unit's behaviour if the upload stops half way. The failure to plan for is a unit that waits at its sample loading screen; the way back is the bootstrap's own OS upgrade from the start-up menu, which this project has never had to use.

Verdict: realistic, as a second step after larger slots are proven on the unit, not as one change.

## Larger slots, step one: built, not flashed (2026-10-07, section 3 of OS 1.42)

Maintainer agreed to two steps: larger slots first with the total left as it is, then the pool in two halves. This is the first. A fourth image, `make image-big`, so the three that exist stay what they were (checked: same hashes). Tests: `tests/test_bigslots.py` (15), `tests/test_transfer_patch.py` (5), 310 in all.

What turned out to be live. Of the store's routines that deal with one slot, three have no reference anywhere in the image, by address or relative: the slot erase (`0x40111254`) and the two that write a sample (`0x4011222c`, `0x40112376`). They are left as they are and a test holds that the big image does not reach them either. The live places are:

| Routine | Stock | Big image |
|---|---|---|
| scan `0x4011149e` | sector (slot << 10) + 8192; 2 x frames up to 524,224 | slot << 11; up to 1,048,512 |
| header reader `0x401132ec` | sector (slot + 8) << 10; same limit | (slot + 4) << 11; 1,048,512 |
| data reader `0x401133ce` | byte address (slot + 8) << 19 | (slot + 4) << 20 |
| rename `0x40111ed4` | sector (slot + 8) << 10 | (slot + 4) << 11 |
| route `/samples/<slot>` `0x400b9dfe`, slot from 1 | address (slot << 19) + 0x380000; size held to 0x80000 | (slot << 20) + 0x300000; 0x100000 |
| slot list `0x400ba11c` | size held to 0x80000 | 0x100000 |
| pool builder `0x40082334` | a 512 KB buffer per slot, no check on the total | `engine/poolstage.c`, below |

13 byte patches, 50 bytes, each with its stock bytes asserted, and 14 more stock sites asserted that the patches lean on (the shifts themselves, the one call to the builder).

A file from the computer needs nothing more: the route gives the address and the stream writer goes on from there. The drive takes writes without a slot being erased first: the only erase on that path is one sector at the start.

The pool builder, rewritten into the stock routine's own 246 bytes (124 used): for each slot it calls the stock data reader with the slot's place in the pool's block as the buffer and the room left as the most, and keeps the slot only if all of it fits; otherwise the slot gets a count of 0, as stock gives an empty one. The room is what 64 full stock slots come to, 64 x (4 + 524,224) bytes after the marker and the length: it never uses more of the block than stock could. Whether the 3,836 bytes between that and the audio CPU's program are the block's or something else's is not known, so they are left alone.
- The stock reader hands whole sectors to the drive routine with the destination as given. That routine reads straight into a destination that is 16-byte aligned and through its own 64 KB buffer otherwise (`0x4010f6ac`..). Stock's buffer came from the allocator; ours is wherever the slot falls in the block. Both paths are stock's own; which one a slot takes now depends on where it lands.

Shown against a drive that is a dictionary of sectors, the three drive routines replaced by stubs that read and record: see `docs/REPORT.md`, "The big image". The arithmetic of rename and of the route is run as the few instructions it is, for all 64 slots, since the routines around it need more of the system than is here.

The computer's half, `tools/patch_transfer.py`: accepts Transfer 1.10.3 for macOS by the SHA-256 of its program, checks the bytes at both places, and writes a copy with the cut at 10.0 s: the ARM half's `fmov d2, #5.0` becomes `#10.0` (1 byte), the Intel half's load of the stored 5.0 is pointed at a stored 10.0 the program already has (3 bytes; the 5.0 itself is shared with other code and left alone). The copy is signed locally, in a temporary folder, because a synced folder puts Finder attributes on a bundle and signing refuses one that has them. `build/Transfer10s.app` was made that way; the installed program's hash is unchanged. NOT DONE: the copy has never been started.

`tools/split_sample.py --big` (`make samples BIG=1`): pieces of up to 10 s, and a set that is more than the unit loads at boot is refused with the two numbers.

Image: `abf15db216ffea983e749dc3cf2eedee49724a05ad1a69ea3e1f92f1b193fcd5`. elektron-firmware-tool: checksums ok, 8 sections as intended, bootstrap and updater the official bytes.

NOT CONFIRMED, needs the unit: everything in the table of `docs/REPORT.md`. Before flashing: projects backed up, and the start-up menu seen to offer an OS upgrade.

## Room in the main program: 27 KB nothing reaches (2026-10-07, section 3 of OS 1.42)

Maintainer asked how much more can be added. Our main CPU code sat in about 1 KB found by hand. A survey of the whole program: `tools/deadcode.py`, `tests/test_deadcode.py` (5). **Static evidence only.**

Method. The code (`0x40000400..0x401c1062`; tables after that, and one island of code at `0x40336550` that is copied elsewhere to run) is cut into pieces at every return. A piece is live when something live names an address in it: an operand of a decoded instruction, any 32-bit value at an even offset anywhere in the image, a far pc-relative branch, call, lea or pea read at every even offset whether the listing decodes it or not, a switch table entry. Roots: all code before the entry point, everything named from the tables (odd offsets too) and everything named from sections 2, 4, 6 and 8. Each rule errs towards live.

Why that is enough here: of 55,426 calls in the program 23,823 are to an absolute address and 31,589 go through a register or a pointer in memory. 14 are pc-relative. An absolute address is a 32-bit value in the image, so the scan of values sees every one, in step or not. What it cannot see is an address made by arithmetic at run time. None was found for calls (the 541 jumps through a register load a whole pointer first), but that is a reading of the listing, not a proof.

Checks on the method:
- On the audio program it finds the three runs the sampler and recorder live in, exactly, among 18 runs and 6,668 bytes. Those were found by hand and never run while every stock machine plays.
- On the main program it finds the mixer link's run and the mute's run exactly, and the slot erase routine that the sample store trace had already found dead. It calls the recorder's run (`0x4008f13e`) live: a word inside an EMAC instruction of the mix kernel reads as a branch into it. That is the method erring towards live, as meant.
- No other code address in `tools/mainmap.py` is in a run, and no place the images patch: the mixer call, the mute read, the display table routine, the sample store and the pool builder all count as live, and they do run on the unit.

Result: 391 runs, 57,250 bytes unreached. Usable (named by nothing at all, every word an instruction, whole functions):

| At least | Runs | Bytes |
|---|---|---|
| 64 B | 180 | 45,086 |
| 256 B | 55 | 28,274 |
| 512 B | 17 | 14,724 |
| 1,024 B | 3 | 4,276 |

Less the two we use, **27,518 bytes in 53 runs of 256 B and up.** The largest: `0x40196aba` (1,714 B), `0x4001b51e` (1,522), `0x4008804c` (1,040), `0x401259fa` (930), `0x401bceac` (918), `0x40086e42` (912). The full list: `python -m tools.deadcode 3`.

What it does not say:
- That any one run is safe. Before code goes into one it gets what the present ones have: its own test that nothing names it, and a run in emulation where that can be had. The main program cannot be run whole here.
- Room in one piece. The largest run is 1.7 KB. Larger code has to be split over runs, as ours already is.
- Anything about memory. The main CPU's RAM is full ("Twice the pool", above).

## The boot staging block is named by the boot loader only (2026-10-07, section 3 of OS 1.42)

Maintainer asked what a menu would cost: a few bytes of main CPU memory for its state, and that memory has no free part on paper. The 32 MB staging block (`0x4d84f2c0`, "The pool is staged in a fixed 32 MB") is a candidate once the unit is up.

Read from the listing: every decoded operand and immediate in the code that falls in the block, through the uncached alias or the plain address. Through the alias, four places name it, all in the boot loader (`0x40082a48`, `0x40082b64`, `0x40082fb6`, `0x40082fe0`), and the audio program's copy right after it is named at `0x40082d16..0x40083202`. Everything else in range is a number or a tag, not an address: the floats 2^27 and 2^31, 32512.0, `0x46666666`, the text `GNUC`. The scan of raw 32-bit values is no use for this range: `0x4e..` and `0x4f..` are opcodes.

So nothing outside the boot loader names the block. **Not shown:** that none of those routines runs again once the unit is up, and that no pointer into the block is kept in a variable for later. Both have to be settled before anything is stored there.

## Saving takes: first trace, nothing built (2026-10-08, section 3 of OS 1.42)

Maintainer picked saving takes to the +Drive as the next build ("recordings survive power off and come off with Transfer"). Read-only so far. Static reading of the listing; no test yet.

What a save needs: the take is in the audio CPU's memory, the drive is the main CPU's, and the drive may only be written from a task, not from the per-block audio path our main CPU code runs in.

Read so far:
- The main program runs tasks. One routine creates them (`0x40001640`, 16 calls: control block, entry, priority, stack, stack size). There is a lock and unlock pair (`0x40001980`, `0x40001aa2`; 41 and 32 users), a wait and a give (`0x40001792`, `0x400018d4`; 21 and 28 users), and a table of 32 timers of 12 bytes with its own task (`0x40002d8a`, stack 2 KB; cancel is `0x40002ea4`).
- **The audio CPU has a manager task**: entry `0x40082c04`, priority 5, stack 16 KB. It is the one that stages the pool, so it already reads sample slots through the store, and it runs the boot exchange with the audio CPU through the window. It waits on `0x41bbf438`.
- What wakes it: its boot timer's routine (`0x400828cc`, at `0x400829d0`) and its own start-up. That routine cancels its timer when the boot is over or has failed (`0x4008295a`, `0x400829e4`). A four-instruction routine that would wake it from elsewhere (`0x40082f5a`) is unreached. So after boot the manager sleeps for good, as far as found.
- The task at `0x40113652`, next to the store's code, is the display: it paints 8 pages of 128 columns. Not the store.
- The store's write (`0x40111628`) has 9 callers, all inside the store. The two stock routines that write a whole sample (`0x4011222c`, `0x40112376`) are unreached, as the earlier trace and the survey both say: they are not a path to lean on without reading them through.
- Saving a project reaches the drive through `0x40111c0c` and the routines around `0x4001a36a..0x4001b168`, called from handlers near `0x40182700` and `0x40033ed8`. Which task that is was not traced.
- The window: `0x5b0..0x800` has no use found, and `0xc10..0x1000` is past the recorder's ring and idle after boot.

Shape of a design, not settled:
- Audio CPU: answer requests through the window. The main side names a slot and a byte offset, the audio side puts 512 bytes of the take and the slot's length there and echoes the request. One sector an audio block: a 10 s stereo take is 3,750 sectors, about 2.5 s plus the drive's own time.
- Main CPU: a routine that runs in a task pulls a take a sector at a time and writes the slot (64-byte header, then the samples), then has the store scan the slot again. No large buffer.
- The open part is the task: either one of ours, or the manager's, woken by a timer left running after boot; or the routine that saves a project, where stock itself writes the drive.

NOT KNOWN:
- Whether the audio CPU can write the window outside the track buffers and have the main CPU read it while the unit runs. Only the other direction is proven there (the recorder).
- The arguments and the lock rules of the store's write, and how the store is told to scan a slot again.
- What a write of 2 MB does to audio and to the screen while it runs.
- Whether sending a sample with Transfer restarts the audio CPU. If it does, it ends every unsaved take. The maintainer played samples right after sending them, which suggests a path at run time that was not found here.

## Keeping takes: built, not flashed (2026-10-08, sections 3 and 7 of OS 1.42)

Maintainer chose the move: takes are written when a project is saved, no control of their own ("We can keep it like that for now"), with a menu and a save to a chosen slot wanted later, once the screen code is understood. A fifth image, `make image-keep`, on top of the big one; the four that exist build to the same hashes. Tests: `tests/test_keep.py` (25 after the fix below in the hardware log), 340 in all. Use: `docs/SAMPLER.md`, Keeping takes. What is shown and what needs the unit: `docs/REPORT.md`, The keep image.

Where it hooks, read from the listing:
- The routine that shows `SAVING '%.16s'` (`0x4005b4ba`) starts a job named "Project Save" whose body is `0x4005ba50`; that body calls `0x4001a82e` (manager, project, progress) and returns the opposite of its low byte. A second job body (`0x4005bafa`) calls it the same way. Those are the only two references to `0x4001a82e` in the image, as calls or as values. The routine returns its answer with a byte move, so only the low byte counts.
- `0x4001a8d2`, which looked like the project save at first, is the save of a pattern into a project (its texts are "Ptn saved to", "Kit saved to"). It is left alone, so saving a pattern keeps no take.
- The program's texts carry its own names: `ProjectManager::interactiveSave`, `saveProjectToMmc`. The drive is an MMC to the program.
- So our code runs in the job that stock uses to write a project to the drive. That settles the question of the task without a task of our own or a timer.

How a slot is written, from the stock routine that writes a whole sample and that nothing calls (`0x40112376`), used as a reference only: lock at store + 87424; `0x40111628`(store, sector, bytes, data, progress, 0) with the sector (slot << 10) + 8192; the progress argument is 12 bytes and is skipped when its third long is 0; then the table entry (name, frames at +20). Ours calls the write a sector at a time with an empty progress, and the stock scan (`0x4011149e`) for the table, with the big image's sector arithmetic.

The header: Transfer's upload code stores `SAMP` and four zero bytes, then the frame count, big-endian, at +8; its download code checks `SAMP` and reads the count at +8. Ours writes that, and a name at +12.

Choices made here, not the maintainer's:
- One sector a request, 512 bytes on the stack. A larger piece would be faster on the drive but the job's stack size is not known.
- The wait for the audio CPU is a spin with a limit (4,000,000 reads of the window), not a sleep: the program's sleep was not identified.
- The marks of what has been kept are on the audio CPU (`0x4407ff00`, a long a slot: the take's length with a mark), in memory that is never cleared. They only count for a slot whose table entry points at its take buffer, which is never so after a boot, and a new take clears its own two.
- Header last. A save that stops half way leaves the old header over partly new data. The take is still in memory and the next save writes it whole.

A kept take is a loaded sample after the next power cycle, and in the other images a sample plays 6 dB under a take. Put to the maintainer, who answered "make all loaded samples play at take level". So in this image, and only this one, a loaded sample's gain is a take's (`GAIN_SAMPLE` under `KEEP`): full scale, which is what stock hands the later stages with both of Twinshot's layers up. Held by two tests: a loaded sample plays bit for bit like the same audio as a take, and a full-scale sample does not wrap. First build of this image, before that change: `3da2db9b...0bc3`, never flashed. Image now: `1ed4d08aaefb85f8a0529ed1ce6f9d0914fdf3eced9bf1ec1f1d9b1910cee96b`.

NOT CONFIRMED, needs the unit: the table in `docs/REPORT.md`. The first is the one everything rests on: the audio CPU writing that part of the window.

## Twice the pool, built: two halves through one block (2026-10-08, section 3 of OS 1.42)

On request. The second step agreed on 2026-10-07. A sixth image, `make image-double`, on top of the keep image; the five that exist build to the same hashes. Tests: `tests/test_double.py` (16), 371 in all. Use: `docs/SAMPLER.md`, Twice the samples. What is shown and what needs the unit: `docs/REPORT.md`, The double image. **Not flashed** when this was written; it ran on the unit later the same day (hardware log).

Read for this, beyond the entry "Twice the pool" above:
- The sender (`0x40082f90`) is a task. Each pass: wait on `0x41bbf428`; chunk count from the length at block + 1; command 2 and the index (a word) into the window; copy 2 KB from block + 5 + (index << 11) to the window; index up; every 128 chunks a progress call; state 4 when the index reaches the count; signal the audio CPU. It is woken once a chunk by the interrupt from the audio CPU (`0x40083034`, state 3), which is also where the index is set to 0 when sending starts (state 2).
- The audio CPU (section 7, `0x40000fa8`) takes the index as an unsigned word, times 2 KB, from its pool at `0x4004f750`, copies, signals and waits. Its slot table routine (`0x40000d06`) walks 64 records with no limit on where they end. The pool is 64 MB to the byte before the slot table.
- The watcher (`0x400828cc`) is a timer routine started every 0x20 units (`0x40082e68`). In state 3 progress is the index going up. Past 18 calls without progress it sets a timeout; the next call counts a try, wakes the manager, and after two tries gives up. The unit of the timer was not found.
- The drive read (`0x4010f612`) takes its own lock, so the refill may run in the sender's task while other tasks use the drive.
- The block's first byte, stock's `0xaa`: the routine that returns the block's address (`0x40082a48`) was called by the stock builder alone, and the one other instruction that names the address is in a run nothing reaches. So nothing reads the byte.

Choices made here:
- A half is 16,382 chunks: no more of the block than stock could fill (64 x (4 + 524,224) bytes), in whole chunks. 1,792 bytes more would fit before the audio CPU's staged program, but whether those are the block's is not known. Cost: a set of 64 slots filled to the last byte is 4,352 bytes over, which nothing sends.
- The block's first byte says which half it holds (`0xaa`, `0xab`). No memory of our own.
- The stall count is cleared after every 16 KB read, not the timer stopped: it uses nothing of the kernel that the code does not already use. The risk left is one read of 16 KB taking longer than 19 calls of the watcher.
- A pool of one half or less takes the old path exactly, so the new image can be flashed and booted on the present samples before anything new is asked of it.

NOT CONFIRMED, needs the unit: the table in `docs/REPORT.md`.

## How a knob's text is made, and the screen image built (2026-10-08, section 3 of OS 1.42)

Maintainer, asked what comes next: the stereo label first, "and also menu for the sample mode", then the playback fixes, then sample banks. A seventh image, `make image-screen`, on top of the double image; the six that exist build to the same hashes. Tests: `tests/test_screen.py` (30), 401 in all. Use: `docs/SAMPLER.md`, Names and words on screen. What is shown and what needs the unit: `docs/REPORT.md`, The screen image. **Not flashed.**

Read from the listing, short stretches at a time:

- **Correction to Phase 8.** The slot text function `0x4007ba80` does not show a slot number. It turns the value into one (1..64, either half of the knob), asks the sample store for that slot's name (`0x401113b6(store, slot - 1, a string object)`) and writes up to 15 characters of it, or the words at `0x40251d2f`, NO SAMPLE. So what the maintainer answered on SMPL 2 was NO SAMPLE for slot 2, and in stereo the screen has been showing the name of the wrong slot all along.
- A text function is called as (its object, the value in 8.8, where to write). `0x4007bbe2(record, value)` takes the object at the display table + 0x14 + 84 x record and calls `0x4018837a`, which jumps to the function at object + 12 with those three arguments; the text lands at `0x41b9fbcc`. **No track is passed.** The object given is the table's copy, so the record can be had from its address.
- The slot text function's address is in the program once, at `0x40188f3e`, where the start-up routine builds its object, `0x41b9ece0`. Stock gives that object to records 498 and 502 only (SMP1 and SMP2).
- Where a page gets the track. The class with the method table at `0x401c9034` (constructor `0x4003a472`) keeps the manager, `0x4016e9c8()`, at + 104. Its getter for a knob's value (`0x40037e50`, method + 84) does, for a machine's records: holder = `0x4001c422(manager, record, -1)` (through method + 196), value = the holder's method at + 40, called as (holder, record). In `0x4001c422` a track past 13 is replaced by `0x4001ff74(manager + 48)`, the active track, and a record of a machine goes on to `0x4000f642(manager + 304, track)`. Stock calls `0x4001c422` with -1 from one more place (`0x4001c5a6`).
- That class's knob routine (`0x4003b870`, method + 68) has a case of its own for records 498 and 502. Not read further.

Built (`engine/knobtext.c`, 564 bytes in an unreached run of 848 at `0x40124852`, the sixth piece of code space):

- One routine takes the slot text function's place in its object. LOOP's text is pointed at the same object, and MODE's is left on it as in stock, so three records reach the routine and it tells them apart by the object's address.
- SMPL: it asks for record 502's value the way the getter above does. When MODE counts stereo samples it calls the stock function with the value that stands for slot 2n-1 in mono, and cuts a last ` L`, `_L`, `-L` or `.L` from what comes back. Past 32: NO SAMPLE. In mono the value goes to the stock function as it came.
- LOOP reads OFF, FWD, PING; MODE reads MONO, STEREO, REC MAIN, REC EXT, CHAIN, ST CHAIN. A value neither knob can have reads as its number.
- "Menu for the sample mode" was taken to mean these words. A menu of its own, a new page, is not started.
- Image: `2a793e926cd20e9ecbde6fda68a432532a68096638b8563b25873468561a202c`. elektron-firmware-tool: every checksum ok, sections 3 and 7 as intended, the other six stock.

INFERRED, not confirmed: that track -1 is the track whose page is drawn in every place a sampler's SMPL text is asked for; that every caller hands over the table's copy of the object (the routine treats any other object as SMPL, so LOOP or MODE would then read as a sample name); that the page with the method table above is the one that draws a track's SRC page (it is the one that handles records 498 and 502).

NOT CONFIRMED, needs the unit: the table in `docs/REPORT.md`. Known and left: a take that has not been kept has no name on the drive, so SMPL reads NO SAMPLE on it (or the name of what it was recorded over) until the project is saved.

Toward a page of our own, seen in passing and not understood: two list screens that write `(EMPTY)` draw through `0x400f95e0` (given one of two objects, `0x402aa114` and `0x402a2144`, perhaps fonts), `0x400f8bd0` and `0x400f945c`.

## A sampling page: what the maintainer wants, and a first read of the menu code (2026-10-08, section 3 of OS 1.42)

Asked what "menu for the sample mode" meant, the maintainer answered. So the words on MODE in the screen image are not it. Nothing is built for this yet. This entry is the first read, to size the work.

Read from the listing, short stretches:

- The SETTINGS menu is not a table. A routine (`0x4005ed72`, about 1 KB) builds it at run time: for each entry it allocates 0x54 bytes from the heap (`0x4010394c`, the allocator; `0x40103958` frees), constructs an item with `0x400fa998(item, name, a function object, an address in RAM, a second function object)` and hands it to the menu through the menu's method at + 8. MIDI CONFIG, GLOBAL FX/MIX and PERSONALIZE are added there by name.
- The function objects are of the same make as the display table's: 16 bytes, a manager at + 8 that copies and frees what the object holds, the function to call at + 12. An entry's first one is what runs when it is chosen. For the first entry that function takes a page the settings object keeps (a counted pointer at + 456 of it) and passes it to `0x400ff292`, which looks like "show this page". `0x4016dc10` ends a function object's life.
- So the stock menus are heap objects of a class library with counted pointers and function objects. A page of ours has to be built the same way, by code of ours calling the stock constructors, not by adding a row to a table.

What this means for the work, as it looks now:

- An entry SAMPLING in the SETTINGS menu is the nearest thing: one call added to the routine above, and a list page of our own behind it built from the stock item classes. It needs no key of its own.
- Not read yet: the class of a list page and how one is made; the items that hold a value (a name, a range, a text) as the metronome and MIDI menus have; how a page is closed; where our settings would live (the heap gives room, so main CPU memory is not the obstacle it was thought to be); how a value reaches the audio CPU (the shared window has 480 bytes free past the keep box).
- Not looked for: a way to open a page from a key combination, and a second page behind a track's SRC key.

NOT CONFIRMED: everything above is static reading of a few routines. `0x400ff292` as "show this page" is a guess from its one use here.

## The sampling page behind SYN: how a track page holds its pages, and why its knobs cannot be stock knobs (2026-10-08, section 3 of OS 1.42)

On request So not the SETTINGS menu of the entry above. Nothing built. Read from the listing and from the record table:

- A track page object (method table `0x401c9034`, the class of the entry before last) keeps a list of page numbers at + 124 (start) and + 128 (end), four bytes each, and the one it is showing as an index at + 144. Its method at + 136 gives the current page number, + 128 sets the index (kept inside the list) and + 188 turns a knob 0..7 into a record: `0x4007ba48(page number)` gives a 44-byte entry of a RAM table at `0x41ba1248`, 37 entries, and the knob's record is the long at + 8 + 4 x knob. A page number past 36 gets the entry before the table.
- **A second press of a page's key already moves to its next page.** In the object's event method (+ 256, `0x4003bc6c`): when the list holds more than one page, the index becomes (index + 1) modulo the count and the page is drawn again (`0x400ffe22`). So "hit SYN again" is stock behaviour for a page with two entries in its list. Not read: where the SYN page's list is filled and whether it depends on the machine.
- **Every knob of such a page has to be one of the 505 records, and none is spare.** Read from the whole table: 0..18 are not knobs (machine type, solo, mute, track level, the active track, and a dozen named Error that carry MIDI controller numbers), 19..157 are the track, trig, filter, amp, LFO, FX and input pages, 158..504 are the machines' own pages, eight or fewer each, with no gaps. Types 34 and 35 have no records at all.
- Making the table longer is not a small patch: 54 places in the code name its start, 67 compare a record against 505 or 504, and the display table in RAM is sized by it.
- In a track's sound, the machines' knobs use slots 18..23, 25 and 26 on a digital track. Slots 17 and 24 are named by no record that a digital track uses (analog machines and the MIDI machine use them). NOT CONFIRMED that they are stored, saved and sent for a digital track. The audio CPU's voice loop reads knob slots 18..25, so slot 24 would reach it as things are.

What follows: a sampling page behind SYN cannot be eight more stock knobs. It has to be a page our code draws and whose knobs our code handles: a 38th page number with an entry of its own, put in the SYN page's list on a sampler track, with the object's draw and knob methods going to ours while that page shows and to stock otherwise. Still to read before any of it can be built: the object's draw method and what it calls to put a knob, a name and a value on screen; its knob method (`0x4003b870`, + 68) far enough to step aside; where the SYN page's list is made; and where the page's values live.

## The page table, and what goes on the sampling page (2026-10-08, section 3 of OS 1.42)

Maintainer's list for the page behind SYN, from the nine offered: source (main mix or external input), destination shown by name, record start and stop from the page, save to the drive now, more sources (a single track, analog tracks on their own), length (free or a fixed 1, 2 or 4 bars), threshold, monitor, a level meter, normalize and a waveform view. "all these but undo should go on second page": read as everything but undo, on the second SYN page. He turned undo down once before. Whether the record values leave MODE is not answered.

`tools/uitable.pages` now reads the page table out of the start-up routine (one test in `tests/test_screen.py`):

- 37 numbered pages at `0x41ba03c8`, 44 bytes each, ending where the display table starts: a short name, a long name, the record behind each of the 8 knobs, the LEVEL knob's record.
- The machines' own SYN pages lie right before it, one per machine type. Page 6, SYN, has no records of its own. The entry before page 0 is machine 44's: TUN1, SMP1, FLT1, DEC1, then TUN2, SMP2, MIX, OVER, which is the knob order on the unit.
- Stock already has keys with two pages: FLTR1 and FLTR2, AMP1 and AMP2, LFO1 and LFO2. The second filter and amp pages hold two or three knobs and leave the other places empty.
- Pages 0 (NONE) and 25 (OB8, "Outbox 8") hold no knob at all.
- This confirms the entry before: a page is a list of records and nothing else. Record 19 (None, type 62, slot 0) is the only record that is not some page's knob or a MIDI controller's, and one is not a page.

So the page stands as planned: drawn and handled by our code. A place for it in the table costs nothing (a page number past 36 needs `0x4007ba48` to know it; page 25 is there and empty). The work is the drawing and the knobs.

## A second page behind SYN, built: the page objects, the SYN class and one method (2026-10-09, section 3 of OS 1.42)

On request. An eighth image, `make image-page`, on top of the screen image; the seven that exist build to the same hashes. Tests: `tests/test_page.py` (24), 426 in all. Use: `docs/SAMPLER.md`, A second page behind SYN. What is shown and what needs the unit: `docs/REPORT.md`, The page image. **Not flashed.** It is the first step of the sampling page and does nothing but exist: a second, empty page on a sampler track.

Read from the listing and the program's data:

- One routine (`0x400351fa`, 5 KB) builds every track page object: 21 of them, each from a list of page numbers in the data at `0x401c81e0..0x401c8274` and a key number (0x13 TRIG, 0x14 SYN, 0x15 FLTR, 0x16 AMP, 0x17 LFO). Audio tracks, analog tracks, MIDI tracks and the FX track have their own sets where their pages differ.
- **One object serves SYN for every audio track**, digital and analog: list `0x401c8268`, one page, number 6; 0x1ac bytes; class constructor `0x40044a92`, method table `0x401ca37c`. That list's address is in the program once.
- The list goes through `0x4017dbfe(vector, first, count, allocator)`, which makes a vector of longs; the object keeps its begin and end at + 124 and + 128.
- Classes: the table at `0x401c9034` is the base, 60 methods. FLTR (`0x401c9da0`), LFO (`0x402403ec`) and SYN each replace the method at + 188, "which record is behind knob k". SYN's (`0x40044c54`) ignores the page number: it takes the active track (`0x4001ff74` on the object's + 116), that track's machine (`0x4000f692(the object's + 120, track)`: -1 for track 12, 35 for a MIDI track), and the knob's record from the machine's own page entry (`0x4007ba62(machine type)`, 44 bytes each from `0x41b9fc0c`). Its address is in the program once, in the class's table.
- Machine type 34's entry has a name and no record: no machine has that type.

Built (`engine/recpage.c`, 122 bytes in an unreached run of 1,522 at `0x4001b51e`, the seventh piece of code space):

- The builder hands SYN's object a list of two: page 6 twice, in our code space. Two operands change. Page 6 twice and not a new number, so nothing that reads the page number meets one stock does not know.
- Our routine takes the place of SYN's + 188 method in the class's table. It sets the list's end from the active track's machine, two pages on a sampler and one on anything else, puts the index back to 0 off a sampler, answers "no record" for every knob of a sampler's second page, and otherwise goes to the stock method with the same arguments.
- Shown with stock code run as it is: the vector routine on our list gives begin and end 8 bytes apart holding 6 and 6; the key-press instructions step 0, 1, 0 on a page object our routine has seen on a sampler, and do not step on any other machine.

INFERRED, not confirmed: that the method at + 188 runs for the page before a key press can step (it does if drawing asks it for each knob, which the knob routines read do); that a knob with no record is left empty on screen and does nothing when turned, as FLTR2's six empty places are; that nothing else in the SYN class minds a list of two (its methods at + 8, + 16, + 68, + 76 and + 212 to + 228 were not read).

NOT CONFIRMED, needs the unit: the table in `docs/REPORT.md`.

Read after the build, for the next step (drawing on that page):

- The method at + 16 is the draw, called as (page object, a drawing surface). The base one (`0x4003a244`) goes through the eight knobs and asks the method at + 188 for each, every time it draws: so the first thing inferred above is read, not guessed. For a knob with no record it draws one stock picture, the object at `0x444e00b4`, through `0x400f8f70(surface, picture, x, y, 0)`, the first at x 25, y 34. So the empty page will show eight of those.
- SYN's own draw (`0x40030b84`, + 16 of its class) calls the base draw and adds the words ANALOG or DIGITAL and more. It and the base both write text through `0x400f8bd0`.
- So the place to draw the sampling page is in front of SYN's + 16: let stock draw, then draw ours on the same surface when a sampler's second page is showing. Not read yet: the arguments of `0x400f8bd0`, the fonts, and SYN's knob routine (`0x40030070`, + 68).

## The sampling page, second step: two settings drawn and turned (2026-10-09, section 3 of OS 1.42)

After the empty page ran on the unit (hardware log). The page image is built again with SRC and DEST on its second page: `c577e13e...d03e`. The empty-page build, the one on the unit, is kept as `build/images/old/page_step1_empty_page_14401122.syx`. Tests: `tests/test_page.py` (41), 443 in all. The seven other images build to the same hashes. **Not flashed.**

Read from the listing:

- The draw (+ 16) lays the eight places out four across, 26 apart, from x 25: knobs 0..3 at y 34 and 4..7 at y 7. A place's name is written 7 above that, centred 8 right of the place's x, through `0x400f8bd0(surface, font, x, y, mode, format, ...)`: it formats like printf into a buffer of its own, then draws. Stock passes the font object at `0x443db230`, mode 2 and `"%.5s"`.
- A knob's picture and value are drawn by the method at + 180, which marks a place with `0x400f7fb6(surface, x0, y0, x1, y1, -1)`: the name's box is 7 high and the picture's 18 high below it, both 26 wide. Not used yet.
- A turn of a knob reaches the method at + 68 as (page object, event): the event's long at + 12 is 1..8 for the eight knobs and 9 for LEVEL, the long at + 16 the signed steps. SYN's (`0x40030070`) goes on to the base routine (`0x4003b870`), which answers 1 for a knob it has dealt with, a knob with no record included.
- `0x400ffe22(page object)` asks for the page to be drawn again: it sets a flag in the object and tells the object's maintainer.
- SYN's draw and knob routine are shared: two other classes' tables hold them too. Only the SYN class's own table is changed.

Built (`engine/recpage.c`, 654 bytes of the 1,522):

- SYN's draw and knob routine go through ours as its "which record" method already did. Ours lets stock draw, then on a sampler's second page writes SRC with MAIN or EXT under it in the first knob's place, and DEST with 01..32 in the second's. Turning those two knobs changes them, stops at their ends, and asks for a redraw. The other six knobs of that page are swallowed. LEVEL and every knob of every other page go to stock.
- The two settings sit in 32 bytes added to the end of SYN's page object (the builder asks for 0x1cc bytes where it asked for 0x1ac). One set for the unit, not saved, and marked so that whatever the memory held at first is replaced by MAIN and 01.
- **They do nothing yet.** Recording still starts from MODE. This build is to see our own text on the screen and our own knobs move it.

INFERRED, not confirmed: that the place of a knob with no record is left blank, so our text is not drawn over a picture (the maintainer passed the empty page without describing it); that text at 12 below the name's line sits well in the picture's box; that asking for a redraw from the knob routine is enough to see the new value; that the 32 added bytes are ours alone (nothing was found that sizes or copies the object).

NOT CONFIRMED, needs the unit: all of the above, and which row of knobs the unit shows on top.

## The sampling page, third step: it records (2026-10-09, sections 3 and 7 of OS 1.42)

After SRC, DEST, their knobs and LEVEL ran on the unit (hardware log). The page image is built again with a third place, REC: `04125edf...e258`. The build on the unit is kept as `build/images/old/page_step2_src_dest_knobs_0abb2f96.syx`. Tests: `tests/test_pagerec.py` (27) and `tests/test_page.py` (47), 476 in all. The seven other images build to the same hashes. **Not flashed.** This is the first page build that changes the audio CPU's program.

How it is made, three small pieces around one box:

- **The box** (`struct recbox`, `engine/sampler.h`): 24 bytes of the shared window at `0xe20`, just past the keep box. The page writes run, the stereo sample and the source, then two marks. The audio CPU writes back whether a take is running and how many frames it has. Words and longs only.
- **The page** (`engine/recpage.c`): the third knob is REC, OFF or ON. Every change of the three settings is written to the box, the marks last. A knob stands in for a key: how a key press reaches a page has not been read.
- **The feed** (`engine/recfeed.c`, built with PAGE): when the box says run it sends the page's source to the ring every block, before it looks at any track's MODE. 218 bytes of its 238.
- **The audio CPU** (`page_step` in `engine/sampler.c`, built with PAGE): each block it reads the box. Run going to 1 starts a take into the named stereo sample with the same routine a voice's take uses; run going to 0, or a full buffer (10.24 s), ends it. A take that ended by itself does not start again until run has been 0. Its state is shaped like a voice's and sits in free memory under the kept marks.
- The take then is what a track's take is: the slot table points at it, MODE STEREO with SMPL on the same number plays it, and saving the project keeps it.

Two things that had to be guarded:

- That part of the window holds the boot loader's last chunk until the page first writes there, which is sample data of any value. So neither the feed nor the audio CPU obeys the box unless both marks read right (a long and its complement). Without that, a restart could start a take by itself over a loaded sample, and the next project save would write it to the drive.
- The audio CPU's memory for the take's state is never zeroed, so it carries a mark of its own.

It starts from the ring's present block, not one back as a voice's take does: the feed is switched on by the same run, so the block before it is stale.

Cost on the audio CPU, a block: 7 instructions with no box, 27 with the box set up and off, 316 while a take runs (a voice's budget is 10,506). Its code went in the first sampler code space, which had 298 bytes free and now has 68; the recorder's own space was 26 bytes short.

NOT CONFIRMED, needs the unit: that a turn of REC starts and ends a take that plays back; both sources; the end at 10.24 s; that nothing records by itself after a restart; that the old way, MODE and a trig, still works beside it; that a page take is kept by a project save.

## The sampling page, REC in MODE's place (2026-10-09, sections 3 and 7 of OS 1.42)

After the build whose REC ran a take by itself was flashed (hardware log). The the maintainer's report. So REC on the page is to do what MODE's two record values do: put the track in record, where a trig starts a take and the note's end ends it. Built again: `eb899c89...365b`. The build on the unit is kept as `build/images/old/page_step3_rec_runs_alone_04125edf.syx`. Tests: `tests/test_pagerec.py` (35) and `tests/test_page.py` (56), 493 in all. The seven other images build to the same hashes. **Not flashed.**

What changed from the entry before:

- **The box** now holds, for the eight tracks: a bit a track for "in record", a bit a track for "from the external input", and a word a track for the stereo sample the take goes to, or `0xffff` for "the one SMPL is on". The audio CPU writes back the record bits as it last read them, with a flag, and the length of the take that is running or the last one.
- **The audio CPU** (`armed()` in `engine/sampler.c`): each block, for each sampler voice, it asks the box about the voice's track. A track in record is treated as MODE on a record value was: the note starts a take and plays nothing, and REC going off ends the take as turning MODE away did. The free-running take of the build before, and its state in free memory, are gone.
- **The feed** asks the page's code which tracks are in record (`page_tracks` in `engine/recpage.c`, whose address the build hands it: the feed's own room is full) and treats such a track as it treats one whose MODE says record, with the page's source.
- **The page** keeps the three settings for each of the eight tracks and shows the open track's: SRC, DEST (SMPL, or 01..32), REC. A fourth place, TAKE, shows the audio CPU's answer: the take's length in seconds, or `--` while its copy of the record bits is not the page's.
- MODE's own record values still work. Taking them off the knob, so that MODE is MONO and STEREO as he asked, waits until the page's REC has been seen to work: until then it is the only proven way to record.

**Why the build before recorded nothing on the unit is not known.** His note does not say whether the destination was silent or still held its old sample, which would tell the feed from the box. The same box, marks and feed are used here, so the same fault would show again. TAKE is there to tell: `--` after REC is turned on means the audio CPU did not see the page's settings; a length of 0.0 after a held trig means it saw them and got no audio from the feed.

Cost on the audio CPU, a block with all eight tracks samplers: 116 instructions more than the keep image with no box, 172 with the box set up (a voice's budget is 10,506).

NOT CONFIRMED, needs the unit: everything in the table in `docs/REPORT.md`.

## The sampling page: REC and SRC as bits of MODE, so they can be locked (2026-10-09, sections 3 and 7 of OS 1.42)

After REC on the page was seen to work on the unit (hardware log), the the maintainer's report. Built again: `f6f90e67...bdcf`. The build on the unit, the first with a working REC, is kept as `build/images/old/page_step4_rec_arms_track_eb899c89.syx`. Tests: `tests/test_pagerec.py` (38) and `tests/test_page.py` (70), 510 in all. The seven other images build to the same hashes. **Not flashed.**

Why it had to change: a lock to a step exists only for one of the unit's own parameters. The build before kept REC in memory of ours, which no lock can reach. The one parameter the sampler has that already means "record" is MODE. So:

- **MODE's value is three switches on this image**: 1 stereo, 2 in record, 4 record from the external input (`engine/sampler.h`). Its range goes from 0..5 to 0..7. The engine, the mixer link and the feed already read bit 0 as stereo-when-playing and bit 1 as record, so the audio CPU and the feed change by one test each: the source is bit 2 where it was bit 0. Chained slots, which were MODE 4 and 5, are gone from this image.
- **The page's REC and SRC switch bits 2 and 4 of it**, and the first page's MODE knob, which our routine now takes over too, switches bit 1 and nothing else. All three read the value the way a page reads any knob (the holder and its method at + 40, as `engine/knobtext.c` does on the unit) and change it through the page object's own method at + 96.
- Read from the listing for this: the stock knob routine (`0x4003b870`) turns the steps of a knob into a change in the value's own 8.8 units (`0x400f6a96`: for a stepped knob, steps shifted up by 8) and hands it to the method at + 96 as (page, record, knob, change, flag, a byte for its answer). That method (`0x4003820e`) finds the record again from the knob's place on the machine's page, so MODE's place, 5, is what has to be passed; works out which steps of the pattern page are in view; and calls the method at + 116, which applies the change to the track or to the trigs that are held. So a change made through + 96 is locked to a held trig by stock, with nothing of ours involved.
- **DEST stays the page's own**, a number for each of the eight tracks, not saved and not lockable: there is no bit left for it. It reaches the audio CPU through the box, which now holds nothing else. The audio CPU reads it when a take starts and writes nothing back. The feed no longer reads the box at all.
- MODE reads MONO or STEREO from its lowest bit (`engine/knobtext.c` built with PAGE for this image).
- TAKE is gone from the page. It did its other job: on the unit it showed numbers, so the box reaches the audio CPU and the audio CPU's answers reach the page.

Patterns made before: a track left on REC MAIN (2) is in record here as there. REC EXT (3) reads as in record from the main mix with the stereo switch on. CHAIN and ST CHAIN (4, 5) read as MONO and STEREO with the source switch on EXT, which matters only once REC is turned on.

Cost on the audio CPU: nothing while notes run, 16 instructions for each note that starts.

INFERRED, not confirmed: that the method at + 96 may be called from our routine as the stock knob routine calls it, with a change we worked out ourselves; that the value read through the holder is the one the change is applied to when no trig is held (with a trig held it is the track's value that is read, so REC can be locked on but a lock cannot be turned back off from the page if the track itself is off: not looked into); that taking the MODE knob away from the stock routine on the first page costs nothing but the line of text stock shows while a knob is turned.

**Wrong in one thing, found on the unit: the method at + 96 is not how a turn changes the track's own value. Read "A turn of a knob has two ways to a parameter" below before leaning on this entry.**

NOT CONFIRMED, needs the unit: the table in `docs/REPORT.md`.

## Samples loaded while the unit runs: the load image (2026-10-09, sections 3 and 7 of OS 1.42)

On request. Built: a ninth image, `make image-load`, `9e99672e...1479`. Tests: `tests/test_load.py` (33). Emulation only.

Read from the listing first:
- **Nothing in stock loads a sample after the boot.** The one reader of sample data (`0x401133ce`) is named once, by the pool builder (`0x40082334`), which is called once (`0x4008287a`). So a sample sent from the computer is not heard before a restart either, as far as the code shows, and anything that changes what a slot plays while the unit runs has to be ours.
- **LOAD PROJECT goes through one routine, `0x4001d6fe`**, called once (`0x4005bba8`) from the body of the job named "Project Load" (`0x4005bafa`, the function the job is made with at `0x4005d9dc`). Same arguments as the save routine, (manager, project, progress), and the same answer: a byte, not zero when it went well. That body first asks the store whether the project exists (`0x401104fe`); when it does not and a flag is set, it makes a new project and saves it, which is the second of the two save calls the keep image already takes. So loading an existing project never ran our save code.
- A second loader, `0x4001b168` (manager, 0, project, 1, 1), is called at boot (`0x40034242`) and by three small routines at `0x401827ea`, `0x4018282c`, `0x4018286c`, each given a yes or no and named from code near `0x40182d86`. Not traced what asks them. Not hooked.
- The store's read (`0x401100d4`) takes (store, sector, bytes, where to): its lock, then the drive's read in pieces of 64 KB at the most, 0 when it went well. A fifth argument its callers push is not read.

What the image does (step one of samples a project, and the part every later step needs):
- The call at `0x4005bba8` goes to `load_keep` (the load half of `engine/keeptakes.c`, in the keep image's run of code, 914 of its 930 bytes used). It calls the stock routine. When that went well and the audio CPU is up, it asks each of the 64 slots what a save asks: do you hold a take the drive does not have. For each that does, it reads the slot from the drive a sector at a time through the store's read and sends each sector's samples to the audio CPU, then one last request with the length from the slot's header.
- The samples go through the keep box the other way: bit 15 in the request's slot (`KEEP_PUT`) says the box's 512 bytes are from the main CPU, for the slot's take buffer at the offset given. The last request, offset all ones, gives the length in the first long: the audio CPU points the slot at its take buffer with that length and marks it kept, so the next save writes nothing for it (`load_step` in `engine/sampler.c`, built with LOAD; 180 bytes more in the first of the sampler's code spaces and 28 in the recorder's).
- While pieces come, a slot that was playing its take buffer has no frames, so a new note on it is silent and not half old, half new. A slot that was playing the boot's pool goes on doing that until the last request.
- A slot with no sample on the drive (no SAMP at its start) is loaded as empty: the take is gone, as after a restart.
- A length over a take buffer (491,520 frames) is cut to it, on both sides, and the audio CPU writes nothing past a buffer's end or for a slot past 63.
- The drive is only read. No new place in memory, in the window or on the drive is used: the box, the take buffers and the marks are the keep image's.

So on this image: record, save the project, record again into the same place, load the project, and the saved take plays again. A take that was never saved is gone when a project is loaded.

What it is not: a sample set for each project. The slots are still the unit's 64, shared by every project, so a take kept by one project is replaced when another keeps one in the same place. That needs a place on the drive for each project's own (176 MB after the samples is unused, `DRIVE_FREE`), a table of which project owns what, and this loader to carry it. Not designed.

Cost: nothing on the audio CPU while no request stands, 1,062 instructions in a block that takes a piece. A sector a block is 768 KB a second at the most: a 10 s stereo sample is 3,842 requests, about 2.6 s, plus the drive's reads.

INFERRED, not confirmed:
- that the audio CPU goes on running its blocks while the Project Load job is in that call, as it does during a save;
- that waiting there for seconds does no harm (the job's screen says LOADING; the save job waits the same way on the unit);
- that the store's read may be called from that job (stock reads the project there through the same routine).

Not done: voices that are sounding a slot when it is loaded keep reading its buffer with the length they started with, so a held or looping note plays the new samples until its next trig. The three confirmations and the boot's loader are not hooked: after whatever asks those, takes stay as they are.

## A turn of a knob has two ways to a parameter (2026-10-09, section 3 of OS 1.42)

Found on the unit: on the first build that made REC and SRC bits of MODE, SRC, REC and the first page's MODE did not move, while DEST, which is ours alone, did (hardware log). Read again, the stock knob routine and the three methods it can hand a turn to. Built again: page image `769bb5f3...1635`, load image `850d6e8c...61de`. Tests: `tests/test_page.py` (80). Emulation only.

**What stock does with a turn** (`0x4003b870`; the record and the change in 8.8 are worked out first):
- From `0x4003ba42` it asks three things: `0x40102f40(0x12)`, a state of the keys; `0x400c2dd6` of the object at page + 108, a byte at that object's + 352; and `0x400a6272(record)`, false for a record that can be locked (it is true for machines 49 to 54 only; MODE's record belongs to machine 44).
- **All three: the page's method at + 96** (`0x4003820e`, (page, record, knob, change, flag, a byte)). It finds the record behind the knob again through + 112, takes the sixteen steps on show (`0x40020172` of page + 116, times 16) held to the pattern's length (`0x40027f3a` of `0x40019036(manager)`), and calls + 116.
- **+ 116** (`0x4003831a`, (page, record, change, first step, one past the last, flag, a byte)) goes over those steps. A step that passes either of two tests (`0x4002787c`, `0x400278d8`, each (steps, step)) is a held one. For it the holder's method at + 64, (holder, record, step), gives a word: not negative, and the holder's + 76 moves that lock by the change; negative, and the holder's + 68 makes a lock **at the track's value, and the change is not applied that time**. A step that passes neither test is skipped. **So with no step held this method does nothing at all.**
- Otherwise it asks `0x400c3582` of the same object (steps selected within the pattern's length) and hands the turn to + 156, which runs the change over the selected steps.
- **Otherwise: the method at + 88** (`0x40037f9a`, (page, record, change, flag, a byte)), the track's own value. For a record like MODE's it is the holder's + 44, (holder, record, change, track, flag, the byte, 1, 1).
- Two more ways hang off another key state (2: the methods at + 92 and + 100). Not followed.

**What was wrong.** The build before called + 96 for every turn, on a reading that it was the one method for a change, locks included. With no trig held that is a call that does nothing: exactly what the unit showed. Its tests passed because the stand-in they ran against changed the track's value too: the test held the same wrong idea as the code. And with a trig held it would have counted: every further click of the same turn added the bit's worth again to the lock, since the change was worked out from the track's value and not from the lock's.

**What the code does now** (`flip` in `engine/recpage.c`): it asks stock's first two questions (the third is settled for MODE's record, and the build checks the record's machine). Steps held: each held step in the pattern is taken alone. Its lock is read through the holder's + 64, or the track's value stands in; the bit is switched in that; and + 116 is called over that one step, twice when there was no lock, since the first call only makes it. A step that already has the value wanted is left with no lock made. No step held: + 88, unless steps are selected, in which case nothing (stock would give the turn to + 156, which was not read far enough to use). The page shows the first held step's MODE while steps are held, the track's otherwise.

**The tests now run stock's + 88, + 96 and + 116 as they are**, on a page object of the test's, with the holder's methods, the two step tests and the key states played one level under them. One test calls stock's + 96 with no step held and sees nothing change: the unit's result, in emulation. The rule this leaves: a stand-in for a stock routine proves what it is handed, not what it does; where the stock routine can run, run it.

**Half wrong, found on the unit: held steps do not go through + 96. The first question stock asks is not "are steps held". Read "Held steps go through + 156" below; what this entry says of + 88 stands and works on the unit.**

INFERRED, not confirmed:
- that the holder's + 64 gives the lock's value (it is tested as a word, negative for none, and + 68 is handed a value as a word in its place);
- that + 116 may be called over one step from our routine, and twice in a row;
- that state `0x12` and the byte at + 352 mean "trigs are held to lock" (they are what stock asks; what sets them was not read);
- that leaving a turn alone while steps are selected is right.

Code room: `engine/recpage.c` is 1,512 of the 1,522 bytes of its run. The next thing on the page needs another run.

## Held steps go through + 156 (2026-10-09, section 3 of OS 1.42)

Found on the unit with the build of the entry above: SRC, REC and MODE move with nothing held, and with a trig held REC does not move at all and nothing is locked (hardware log). Read again. Built again: page image `2aed5118...e9d3`, load image `c1f24701...cc8f`. Tests: `tests/test_page.py` (81). Emulation only.

**What stock's knob routine really asks** (`0x4003b870`, from `0x4003ba42`), in order:
1. State `0x12`, and the byte at + 352 of the object at page + 108 (the "keys" object), and a record that can be locked: the method at + 96, which is + 116 over the sixteen steps on show. The two tests + 116 makes of a step (`0x4002787c`, `0x400278d8`) read the step's word in the pattern (`0x400272c4`: word & mask): **they say the step has a trig, not that its key is held.** So this way changes every trig on show. The byte at + 352 is written by `0x400c2de0(keys, value)` and nowhere read as "held": the way below sets it to 1. What state `0x12` is was not found. This is not the way of a held trig.
2. `0x400c3582(keys)`: the keys object holds **64 bits at + 344, the high long first, one a step, set while the step's key is held**; this asks whether any is set inside the pattern's length. Yes: **the method at + 156** (`0x40038ed4`, (page, record, change, flag, a byte)). It asks + 140 whether the record can be locked, calls `0x400c2de0(keys, 1)`, then `0x400c371c(keys, a routine, 0)`, which calls the routine for each set bit under the pattern's length, then `0x400c2ede(keys)`, which clears 256 bytes of the keys object from + 88 and sets its byte at + 56.
3. Otherwise + 88, the track's value, and after it the pop-up: unless `0x400205f8` of page + 116 answers 1, `0x400c347c(keys, "%s=%s", the record's name, the text of the value)`, the name from `0x40012b24` for records 498 and 502 and the text from `0x4007bbe2`.

**The routine for one held step** (`0x40038c3a`): the page's + 144, (page, step, record), is the holder's + 64 and gives the step's lock or -1. Not negative, and a change that is not 0: + 152, (page, step, record, change, flag, a byte), the holder's + 76. Negative: the value from + 84 with (page, record, what + 164 gives for the step), and + 148, (page, step, record, that value), which gives a step without a trig one (`0x40029faa`) and is the holder's + 68. **A new lock is made at the track's value and the change is not applied that time.**

+ 140 (`0x40038bee`) reads the record's flags in the display table: bit 0 says no, bit 3 says no except on track 13. MODE's are 4 (`tools/uitable.py`): it can be locked.

**What was wrong in the build before.** It took question 1 for "steps are held" and, with steps selected and question 1 false, left the turn alone, because + 156 had not been read. On the unit a held trig is exactly that case: question 1 false, question 2 true. So nothing happened, and since nothing set the byte at + 352 it stayed that way.

**What the code does now** (`flip` in `engine/recpage.c`, in a second run of code): no held step inside the pattern: + 88 and stock's pop-up (MODE's own name and text for the first page's knob; REC or SRC and our word on the sampling page). Held steps: `0x400c2de0(keys, 1)`, then for each held step under the pattern's length its lock from + 144, or with none its value from + 84 as stock asks it; the bit switched in that; + 152 by the difference, or + 148 **at the value wanted**, so one click is enough; then `0x400c2ede(keys)`. A step that has the value wanted already is left, with no lock made. Question 1 is not asked: whatever sends a turn to every trig on show, a switch of ours is for held steps or for the track. The page shows the first held step's MODE while a key is held.

**The tests run stock's + 84, + 88, + 140, + 144, + 148, + 152 and + 164 as they are**, under ours, and stock's own + 156 with its routine for a step and its walk over the 64 bits in one test, as the thing ours is modelled on: it makes the lock at the track's value and moves it the second time. Played by the test: the holder's five methods, the pattern's length and trigs, the keys object's memory.

Code room: the page's first run was full (1,512 of 1,522 bytes). A second, `0x4008804c..0x4008845c` (1,040 bytes, `CAVE_PAGE2`, from the survey, nothing reaches it), holds the switch and what it needs: 664 bytes. The first is back to 926.

INFERRED, not confirmed:
- that the holder's + 64 gives the lock's **value** when it is not negative. Stock only tests its sign. The switch and what the page shows while a key is held both lean on it;
- that + 148 may be handed a value other than the track's, and + 152 a change worked out by us;
- that `0x400c2de0` and `0x400c2ede` are all the bookkeeping a turn on held steps needs (they are all + 156 does);
- that the 64 bits are what they look like. What sets them was not read.

## Three sample banks, built: the bank image (2026-10-09, section 3 of OS 1.42)

The maintainer's decision of the same day, after the drive's room was laid out for him: "we'll have 3 sample banks is the idea and each project will load one of them and then when i want to swap the 3 sample banks illl use transfer", and "bank swap sould only happen on project load". Built once the loader it rides on had run on the unit (hardware log): a tenth image, `make image-bank`, `6db70567...74ac`. Tests: `tests/test_banks.py` (36). Emulation only.

Read for it:
- The three drive routines (read `0x4010f612`, write `0x4010f7f8`, both (sector, bytes, memory); erase `0x4010f52a`, sector first) are named in 21 places, each the operand of a `jsr` or a `lea` (10, 7 and 4; `DRIVE_READ_USES` and its two fellows in `tools/mainmap.py`, the list `tests/test_sample_store.py` already held to be complete).
- The main program writes inside its own image: 336 stores to absolute addresses past the code, the first at `0x4029a778`. Its one access control register is `0x4007e020`: `0x40000000..0x47ffffff`, not write-protected. So memory inside a run of our code can hold a number.
- `0x401115ea(store)` scans all 64 slots into the store's name table. It is called at start-up (`0x4000a884`, `0x4000a984`) and from `0x40112052`.
- A project, as the save and load routines are handed it, is a number: the store holds it to 128 (`0x40110526`).

What the image does (`engine/banks.c`, with the save and load hooks of `engine/keeptakes.c` built for it):
- **The drive.** Three runs of 64 slots of 1 MB: sectors 8192, 139,264 and 270,336, to 196 MB. The 21 places name three routines of ours, a few instructions each: a sector of the first run is moved to the same place in the run of the loaded bank, every other sector is left, and the stock routine is jumped to with its arguments as they came. Nothing in the program reaches the drive another way, so the scan, the boot's pool builder, Transfer's route, keeping takes and the loader all work on the loaded bank without a change. A number that is not 0, 1 or 2 never moves a sector past the third run.
- **Which bank.** One sector of ours at 196 MB (401,408, in the part of the drive nothing uses, after the third run): a mark, the bank that is loaded, and a byte for each of the 128 projects. The loaded bank is a number in memory at the start of the code's run, "not known" in the image. The first time a sample's sector is asked for, our sector is read with stock's read and the number set; a drive without the mark is on the first bank. If that read fails it is tried twice more and then the first bank it is.
- **A project.** A second number is the bank the project in memory is to have. The sampling page's fourth place, BANK, turns it and nothing else, and reads the loaded bank, or both when they differ: `A>B`. A save that went well writes it down for that project, if it is news. A load that went well looks the project up; a project our sector does not know is on the first bank, where every project made before this image has its samples. If that is not the loaded bank: our sector is written with the new one first, the number set, stock's scan of all slots called, and the loader told to load every slot, the empty ones as empty. **A bank is changed at no other moment.**
- A take is kept in the loaded bank, and Transfer reads and fills the loaded bank, by the first point alone.

Shown in emulation: the three ways in, for every edge of the layout and each bank, with only the sector ever touched; no number sends a sample's sector outside the three runs or moves any other; the first sample sector reads our sector once; stock's own store read, write and scan and our boot pool builder with stock's readers under it work on the loaded bank; the hooks write and read our sector as said, the new bank written before any slot is loaded; and with the real audio program a project set to bank B, saved and loaded plays bank B's sample, and a take saved there lands in bank B and leaves bank A's slot as it was.

Cost: the code is 1,540 of the 1,714 bytes of a third run from the survey (`0x40196aba`); the page's first run goes from 926 to 1,108 bytes for the BANK place. The audio CPU's program is the load image's.

INFERRED, not confirmed:
- that memory inside a run of code can be written on the unit as the rest of the image is (the register says so; nothing of ours has done it there);
- that the drive between 68 and 196 MB reads and writes like the part before it (the big image went from 36 to 68 MB on the unit without trouble);
- that stock's scan of all slots may be called from the Project Load job;
- that the unit is content to sit in that job for as long as 64 slots take: at a sector an audio block, 87 s for a bank that is full, before the drive's own time.

Not done:
- **A project copied, pasted or cleared in the project manager** keeps or loses nothing in our sector: the copy is on the first bank until it is saved with another.
- A sample sent with Transfer is on the drive in the loaded bank and, as with stock, is heard after the next start. A load of the same project does not fetch it.

## A bank loaded three sectors a request, with the bar moving (2026-10-10, sections 3 and 7 of OS 1.42)

Found on the unit with the first bank image: everything of the banks works, and a project load that brings in a full bank sits on the LOADING screen until the maintainer gives up and switches off (hardware log). Bank A there is the full 64-file test set, 61 MB. Built again: `fe071f75...a75f`. Tests: `tests/test_banks.py` (44). Emulation only.

**Read as slow, not stuck.** Nothing in that load waits without an end: a request the audio CPU does not answer gives up after 4,000,000 looks at the window, and a drive error ends it. But it read a sector through the store and sent a sector through the keep box, one an audio block: 61 MB is 119,900 of each. The requests alone are 80 s, the reads are 119,900 calls of the store's read with its lock, and the screen shows a bar stock's own load has already filled. After a power cycle the unit came up on the bank it was going to, which is what writing our sector first is for. NOT CONFIRMED that it would have ended: nobody waited.

What changed (the bank image only; the load image, whose loader is on the unit and works for the takes it is for, is the same file as before):
- **Three sectors a request.** A put with `KEEP_BIG` in its slot carries 1,536 bytes: 512 in the keep box's data, 1,024 in the recorder's ring (`0x810..0xc10` of the window), which is ours and idle unless a track is recording. The audio CPU copies both into the slot's take buffer, in longs, and stops at the buffer's end as before (`load_step` in `engine/sampler.c`, built with BIGPUT: 58 bytes more). A block with such a put in it costs 3,247 instructions.
- **The feed keeps out of the ring meanwhile.** A third number beside the two of the banks, `BANK_BUSY`, is set for the length of a load, and `engine/recfeed.c` built with BANKS feeds nothing while it is: a track left in record would otherwise write a block of audio over the samples in flight at every mixer call.
- **A slot is read in two reads**: its first sector, then the rest in one call of the store's read, which hands the drive 64 KB at a time. They go to the block the boot stages the pool in (`0x4d84f2c0`, 32 MB, named by the boot loader only, `docs/FINDINGS.md`, "The boot staging block"), a megabyte in so that the boot's length is left, and the block's mark is cleared so that a boot exchange that ever ran again would stage afresh.
- **The bar moves.** Stock's load moves the LOADING bar with `0x401758e8(the job's progress object, done, of how many)` when the object's third long is set (`0x4001a6fa` on). Ours calls it a slot at a time, 1 to 64 of 64, with the object the job handed the load.

So a full slot is 2 reads and 641 requests where it was 1,921 of each; 61 MB is 40,000 requests, 27 s, plus the drive's reading, which the boot also pays. About as long as the boot's own loading. A bank with less in it is quicker in proportion.

INFERRED, not confirmed: that the boot's block may be written while the unit runs; that stock's bar routine may be called after stock's load has returned, with our counts; that the audio CPU keeps answering through 40,000 requests in a row.

## Fades where a sample is cut into: the fade image (2026-10-10, section 7 of OS 1.42)

The first of the playback fixes the maintainer listed on 2026-10-07 ("click-free loops", "fade at start and end"), begun once the banks worked on the unit. An eleventh image, `make image-fade`, `02495c02...2b2d`. Tests: `tests/test_fade.py` (115). It is the first image whose engine does not sound as the others': the reference model has the fades behind a switch (`emu/sampler_ref.py`, `Player(pool, fade=True)`), and the compiled engine is held bit-identical to it over 16 kinds of note at 5 pitches.

What it does (`engine/sampler.c` built with FADE):
- **A note that starts inside the sample fades in**, 64 frames (1.3 ms): forward with STRT off 0, backward with LEN short of all.
- **A one-shot that ends inside the sample fades out** over the 128 frames (2.7 ms) before its end.
- **A forward loop fades out before its seam and in after it**: down over the 128 frames before the wall, up over 64 after.
- **Nothing else moves.** A note from the sample's own start (a drum keeps its attack), a sample played to its own end, a ping-pong turn, and a region too short for the fades (under 8 fade-outs long at the pitch it plays at: 1,024 frames put out a pass) come out bit for bit as the bank image's engine puts them out. A frame at full gain is the frame it was. Lengths are in frames put out, so they are the same at any pitch.

**Why a fade at the seam and not a crossfade.** A crossfade needs sound from past the loop's ends to blend with: before its start, or after its end. A loop of a whole sample, which is what a recorded bar is, has neither. The crossfades that do without (overlap the loop's tail with its head) make the loop shorter by the overlap, and a bar that is 5 ms short drifts against the pattern. So here the seam stays exactly where it was and the loop exactly as long: the sound is down at the jump, and the price is a dip of about 4 ms a pass, which a test shows on a steady level. A true crossfade for takes would want the recorder to keep a little of what came after the note's end. Not built.

How: a gain of 0..4096 on what the player puts out, moved a frame at a time, in the 28 free bytes of the voice's state. At a note's start it is set by where the region's ends are. In a block where no fade is on the player does one test a frame. The fade out begins when the wall is a cut and the distance to it is 128 frames at the block's pitch; the loop's wrap turns it round. Two small routines moved to a fourth run of unreached stock code (`0x40003732`, 550 bytes, 244 used) to make room in the first.

Cost, the whole voice loop over the bank image's engine: 313 instructions a block with a voice playing and no fade on, 921 more in the dearest block of a stereo loop at its seam. The budget is 10,506 a voice.

The fourth run and one number: the rule the other three runs are held to is that no 32-bit value at any even place in the image is an address inside them. One is, for this run: `0x40003851` at `0x4001c7f2`. It is the low half of one entry of a table of rising longs and the high half of the next, read across their join, and it is odd, which no code address is. The test names that one place and checks the table round it; the survey (`tools/deadcode.py`) never counted it. Like the other three, the run is not run or read while every stock machine plays in the emulator.

It ran on the maintainer's unit on 2026-10-10 and its seven checks passed there (hardware log): the fourth run runs, the cuts are clean, and he had nothing to say against the dip or the lengths.

Needs PAGE (a region is in one slot: there are no chained slots on this image).

## A muted track's trigs still fire: the mute image (2026-10-10, section 3 of OS 1.42)

Maintainer's request, after the fade image passed: "currently, the audio mutes work, but they also mute the trig. If I mute something on and off, the trig is stopped, and the audio doesn't keep playing. I want it to be a true audio mute. That way, when I hit the mute button, it mutes the audio, but the trig is still playing in the background. That way, when I unmute it, the sound comes back without having to wait for the next trig. I also want the record function to work and respect rexording trigs even if a track is muted." A twelfth image, `make image-mute`, `b2e57260...467f`. Tests: `tests/test_mutetrig.py` (70).

What was read, from the listing:
- The per-block routine (`0x400a38ce`) takes events off a list in a loop. An event has its kind at + 4 (1: a note starts), its track at + 8, where it came from at + 12, flags at + 36. For a track other than the FX track the loop comes to `0x400a41f8` with the kind in d0, where-from in d1, the track in d2.
- Mutes are tested only when where-from is 1 (`0x400a4214`): the track's bit of the mask made at `MUTE_READ` (the global mutes, or all but the solos), then its bit of the pattern's mutes. Either one and the event is dropped (d4 = 1, and at `0x400a429e` on to the next event). If it was a note's start with flag `0x80`, the track's bit goes into one of two words that are sent to the UI with the block's trigs (message 29 at `0x400a49c2`: trigs, trigs muted globally, trigs muted by the pattern). INFERRED: 1 is the sequencer. A track's last where-from is kept at `0x45511fc8` and an event from a lower one is dropped, so the numbers are an order. Keys and MIDI in were not traced.
- Every kind of event is dropped under a mute, not only a note's start. A note's end is not an event: it is a count a track at `0x80003050` and `0x80003084` that the routine counts down every block.
- Nothing else acts on a mute. Setting one (`0x400226c0`, `0x40020386`) writes the bit, tells the listeners and sends MIDI; it does not release the track. The routine that releases a track (`0x400a5780`) is called from six places: for a machine set to MIDI (`0x4000f7e6`), a play mode change (`0x400199a6`), in a project job (`0x4005bc4e`), for all tracks at `0x40059fc4` (not traced), and from MIDI in (`0x40106492`). None of them is a mute. A loop over the 13 tracks that would release each muted one (`0x4002077c`) is named nowhere in the image. The copies at `0x80003048` are read at `MUTE_READ` and nowhere else (entry "Audio mute").
- A MIDI track is a bit in a word of the kit, at + 5456. The UI's "a track's machine" answers 35 from it (`0x4000f5ae`, `0x4000f5e0`), and the event loop reads the same word of the kit it plays from (`0x800030b8`) at `0x400a432a`.

The change (`engine/mutetrig.c`): the first two instructions of the test (`movel %fp@(-56),%d1 ; asrl %d2,%d1`, 6 bytes at `0x400a421a`) become a call to a routine of 34 bytes in the room after the recorder's feed (`0x4008f1e4`). For a MIDI track, or before there is a kit, it does what the two instructions did and returns: a MIDI track has no audio to mute. For any other track it drops its return address and jumps to `0x400a426a`, where both tests go when a track is not muted. So for a track that makes sound an event runs as on an unmuted track, and the silence is all ours: the mixer shown a volume of 0, the analog voices' level words at 0 (entries "Audio mute", "Analog mute, second build"). The FX track's own test (`0x400a3d5e`) is left.

What comes with it: a muted track's locks are applied and its envelopes and LFOs start again with each trig; it cuts the tracks its trigs are set to cut; the UI is told of its trigs as of any track's, and of no muted trig; a take is made on a muted track, since the feed looks at MODE and not at mutes.

Shown in emulation: stock's own loop from `0x400a41f8` to where it keeps or drops the event, run from the image with our call in it, next to the same code of the bank image. 12 tracks, 72 events (kind, where from, flags, the two other things that drop an event), 6 mixes of mutes. A track that makes sound: what the bank image does with nothing muted, every time. A MIDI track: what the bank image does, every time. The stack and the registers stock has in use come out as they went in. Stock's `0x4000f5ae` run on a kit object over the same kit agrees with the routine for every track. No kit: stock. The main program differs from the bank image's in the 6 bytes and the 34. The feed runs for a track that is muted and in record, and the mixer is shown none of that track.

It ran on the maintainer's unit on 2026-10-10, inside the live image, and its eight checks passed there (hardware log): a muted track's trigs run, it is silent, a take is made on it, analog tracks, solo and pattern mutes the same. Not reported: what the trig keys show for a muted track, a MIDI track.

Also read on the way, for scrubbing, and not run: the parameter block the mixer and the audio CPU are given is built once a block by `0x400979ca` at `0x80006348`, from the words at `0x800021b0`. Every word goes through a one-pole filter (0.97 of what it was and 0.03 of the new value: `0x7c29`, `0x03d7`), then two words a track are copied as they are (+ 36, + 52), and for machine 44 the words of slots 19 and 23: SMPL and MODE, stock's SMP1 and SMP2. A track's machine is a byte at `0x80002f50`. So STRT, LEN, LOOP and TUNE reach the engine smoothed over about 60 ms. Six routines write the filter's state (`0x4009778a` to `0x4009794c`); the event loop calls one (`0x4009792c`) for an event with a long at + 68, INFERRED to put a trig's locked values in at once.

## STRT and LEN while a note plays: the live image (2026-10-10, section 7 of OS 1.42)

Maintainer's request, the same day as the mute: "I want start and length to be adjusted right when they move. Currently, you have to hit a trigger again for them to respect their new positions, but you should be able to move it and just have it change in real time", for a loop, and "should also be the same for reversing a sample". He asked whether it goes with scrubbing: it is the same work (the list of 2026-10-07: STRT read while the note plays). A thirteenth image, `make image-live`, first build `bf7be9f3...1dd1`. **This build ran on the unit and its glide was not wanted (hardware log); the entry after this one is what the image is now.** What follows is the first build.

What it does (`engine/sampler.c` built with LIVE, `engine/sampler.h`): every block in which no note starts, the engine works the region out from STRT and LEN again, as a note's start does. When it has moved:
- **The place played from moves with the end the note started from**: STRT forwards, the region's top backwards (which LEN sets, and STRT too when LEN is short of all). So a turn is heard in the block it arrives in, not at the next pass or the next trig. After it the note is where a note started at the new value would be: to the bit, in the tests.
- **What is read glides there over the block's 32 frames.** The position and the walls change at once; the place read from starts where it was and catches up a frame at a time. A jump would click at every step of a turning knob; a glide is tape pulled past a head, and the pitch bends while the knob moves.
- **LEN moves the far end.** A loop wraps there, a one-shot ends there, from that block on.
- **A move of more than 1,024 frames in a block is not glided through** (32 times the speed the sample was recorded at): the sound fades out (128 frames), the move is made at nothing, and for as long as the knob is still going that fast nothing is heard; then it fades in (64 frames).
- **The far end come in behind the place played from**: the same fade out, then a loop is back at its start and a one-shot is over.
- LOOP and the direction stay a note's own, taken at its start. A track in record is left alone. With the knobs at rest every frame is the fade image's.

How: 10 more bytes of the voice's state (88 are there, 78 are used now). Two routines in two more runs of stock code nothing reaches: `0x400048c6` (302 bytes, 244 used, up to the routine the engine calls for its mix) and `0x40002a62` (436 bytes, 344 used). No 32-bit value at an even place in the image is an address in either, and both pass the checks the other four runs pass (`tests/test_sampler.py`). One older routine moved to the fourth run to make room in the second.

Cost, the whole voice loop over the fade image's engine, a stereo voice: 143 instructions a block with the knobs at rest, 516 in a block that glides. The budget is 10,506 a voice.

What a unit's knobs send, read further (not run: the emulator's EMAC does not do the word-size multiply the routine uses):
- The audio CPU is sent 20 bytes a track from + 62 of the block `0x400979ca` builds (`0x400a4cf2`: the machine type, then slots 18 to 26). So STRT and LEN reach the engine through that routine's one-pole filter: a turn of the knob arrives spread over about 60 ms, 3% of what is left each block.
- A trig's locked values do not: `0x4009792c`, called from the event loop for an event with locks, writes each locked value into the words and into the filter's state, so it is there at once. `0x400977d8` puts the track's own values back the same way, and is called from the event loop too: a lock holds until the track's next event.
- So on the unit a hand's turn should glide, and a lock is seen only by the note it belongs to. If the filter is not what was read, a turn arrives in steps, and steps of more than 1,024 frames (a quarter of a step of STRT on a 10 s sample) are made at nothing: clean, but a stutter and not a glide.

INFERRED, not confirmed: all of the last paragraph; that a glide is what the maintainer means by "real time" (he may want the note left where it is and only the loop's ends moved); that 32 times the speed is the right place to stop gliding; that the two new runs are as dead on the unit as in emulation.

## STRT moves the loop's start and not the note: the live image, second build (2026-10-10, section 7 of OS 1.42)

After the first build on the unit: LEN on a running loop is right, and a turn of STRT is "a tape fluttery noise that moves as fast as i move the knob" (hardware log). That build was `b6f497b3...4927`. **It ran on the unit and ripped on short loops (hardware log); the entry after this one is what the images are now.** What follows is the second build.

What changed: **the place played from is never moved for a knob.** The region is still worked out from STRT and LEN every block and is the note's from then on, as LEN already had it.
- The end a note started from (STRT forwards, the top backwards) moved: nothing is heard of the turn itself. A loop turns at the new place when it next comes round. A one-shot has left that end behind, and with LEN at all of it STRT changes nothing it will reach.
- That end moved past the place played from: the note is short of its region and plays on into it. Nothing is cut.
- The far end moved in behind the place played from: as before, and as passed on the unit. Fade out, a loop back at its start and a one-shot over, fade in. STRT can do this too when LEN is short of all, since LEN is a share of what STRT leaves.
- A ping-pong outside the region at either end turns where it is.

The glide is gone with its 10 bytes of state (one byte is left) and its lines in the frame loop: the run the frame loop is in is the fade image's to the byte. One routine of 432 bytes in `0x40002a62` and a helper in the fourth run. The first build's other run, `0x400048c6`, is stock's again.

Shown in emulation: the engine is the model bit for bit over 23 scripts at 4 pitches; a turn of STRT on a loop, slow, fast, in leaps or at random, changes no frame before the frame the loop turns at, and the same backwards for LEN; a one-shot is untouched by its start; STRT turned up past the note costs no dip and no jump; the far end as in the first build; a knob put back while the sound is going down lets it up where it was; a ping-pong turns in place with no step in a ramp.

Cost, the whole voice loop over the fade image's engine, a stereo voice: 82 instructions a block with the knobs at rest, 151 with both turning.

What the first build told us about a unit: knobs do reach the engine every block; an LFO on STRT does too; a lock is seen by its own note only; and a knob's 127 steps come through as separate moves, so nothing that moves the note with the knob will be smooth without a much slower filter of our own. Scrubbing in that sense is not built, and was not liked in the form it took.

INFERRED, not confirmed: that hearing a turn of STRT only when the loop comes round is what he means by "in real time" for a long loop (for a short one it is at once to the ear).

## A note is a row of passes: the len and live images (2026-10-10, section 7 of OS 1.42)

After the second build on the unit: "better in a sense but now there's just a more abrupt ripping on smaller values/loops", then "we could leave that one alone potentially- the start length tracking if its fgonna be clicky" (hardware log). Two images now: `make image-len` (`e00ce18f...2617`), LEN while a note plays and STRT the note's own, and `make image-live` (`aecab772...4a64`), which follows STRT as well. The second build is kept as `build/images/old/live_step2_strt_moves_region_rips_b6f497b3.syx`. Tests: `tests/test_live.py`. Emulation only.

What the rip was, counted in the reference model of the second build with a knob as the unit is read to send it (a step of 1.0 at a time, each through 3% a block), on a 10 s sample with a loop of 13 ms and STRT turned 20 steps in two seconds:
- Turned down: the region slid away below the note, its far end came in behind the place played from, and the note was faded out and sent back to the start **89 times**, with the gain short of full in 518 of 3,000 blocks.
- Turned up: the region slid away ahead of the note and the note played straight on after it. The longest stretch without the loop turning was **75,456 frames**, 117 passes' worth: for as long as the knob moved it was not a loop.
- With the loop 54 ms long: 27 cuts turned down, 77,000 frames straight turned up. With it a second long: none, and nothing heard until it came round. So "better in a sense" and "on smaller loops" both.
The cause is one: the region's two ends were the knobs', and with LEN short of all both move with STRT, while the note was left where it was.

The change: a note is a row of passes. A pass begins at a place and is as long as the knobs have the region, counted from where it began (`engine/sampler.h`).
- **LEN**: every block the playing pass's far end is put that far from its own beginning. As before to the ear when STRT is at rest, and as passed on the unit twice.
- **STRT** (live image): a loop's next pass begins where the knobs have the start by then. Nothing is done to the pass that is playing. A short loop steps through the sample a pass at a time; a long one takes the new start when it comes round, through its seam's fades. A ping-pong takes it when it is back where its pass began.
- A region the knobs have run to the sample's end: a forward pass runs to the sample's end, wherever it began.
- The far end come in behind the place played from: a loop's next pass begins now, a one-shot is over. Through a fade out and a fade in when the region is long enough to have fades at its seam (1,024 frames put out), and at once when it is shorter: there a turn is already a pass of the tone. A ping-pong turns where it is.
- **len image**: the start in all of this is the one the note took at its trig. Played backwards LEN still moves where a pass begins, and that goes the same way.

The same count on this model: no cut in any of the eight cases, the 13 ms loop turns 128 to 173 times in the two seconds, and no stretch is longer than two passes at the block-sized grain the count has.

How: `pa` and `pb` are the pass that is playing, `pc` where the next begins, `span` how long. The routine that turns at a wall (`edge`) starts a pass from `pc`; the way back in a ping-pong goes to where the pass began and not to `pc`. Three routines in the two runs the first build already ran on the unit (`0x400048c6`: 278 of 302 bytes; `0x40002a62`: 412 or 418 of 436), a helper and one older routine in the fourth. 72 of the 88 bytes of state.

Cost, the whole voice loop over the fade image's engine, a stereo voice: 80 instructions a block with the knobs at rest and 179 with both turning (live); 82 and 183 (len).

INFERRED, not confirmed: that the rip he heard is this one and no other; that a short loop stepping through the sample a pass at a time is what a turn of STRT should sound like; that the knob is sent as read.

## A lock is kept by knob slot, and slot 24 has no knob on a digital track (2026-10-10, sections 3 and 7 of OS 1.42)

On request. Not a bug in the page's code: REC, SRC and the stereo switch are three bits of the one MODE parameter, and a lock holds a parameter's whole value. Locking REC on a step froze that step's stereo switch and source as they stood, and the first page showed MODE locked on it.

Read in the listing, to find REC a place of its own. Run where it says so, in `tests/test_reclock.py`.

- The object `0x4001c422` gives for a machine's record (the "holder") is one of 20 bytes a track at kit + 11628, built by `0x40015110`, method table `0x401c3d4c`, with the track's sound data behind its + 16. Its methods take a record, turn it into the record's knob slot with `0x400a5cc2` (the long at + 4 of the record's 52 bytes) and go on by slot: + 40 the track's own value, a word at the sound data + 20 + 2 x slot, slots 0 to 70.
- Its lock methods, + 64, + 68 and + 72, end in three routines of the steps object (`0x40019036(manager)`, the active track's): `0x4002740c(steps, step, slot)` reads, `0x40027fa2(steps, step, slot, value)` makes, `0x40027fe8(steps, step, slot)` removes. Those end in `0x4001722a`, `0x40017602` and `0x4001741e`, (pattern, track, step, slot). **No record is asked for: any slot 0 to 70 of any track can hold a lock.**
- The table they index: 9,287 bytes a track. 64 steps of 72 words, a word a slot, -1 for no lock, the 72nd the count of the step's locks (`0x4001729e` counts it again after every change); then a byte a slot, "this slot has a lock somewhere on the track" (`0x400175c2` sets it, `0x40017376` works all 71 out again). A lock's word is its value, 8.8.
- **So the holder's + 64 gives the lock's value.** "Held steps go through + 156" had that as INFERRED, and the page has leaned on it since. Read now, and run.
- How a lock is played. The sequencer tests the step's count and calls `0x4008b8a8`, which goes over all 71 slots of the step's row and puts every one that is not -1 into the event: a count at + 8, (slot, value) pairs from + 20. `0x4009792c`, the routine "What a knob sends" had as INFERRED, takes that list: each value into the track's word for the slot (71 words a track, slot s at 28 + 2 s of the track's 142 bytes), into the smoothing's state (`0x8000e9b0`, a long a word) so it is there at once, and the slot marked in 96 bits a track at `0x4550f1cc`. `0x400977d8` puts the track's own value back for every marked slot. Both run here on a lock the page made. Generic: nothing in them knows which slots have knobs.
- A track's own value is changed by the holder's + 44, which ends in + 120 (`0x40013304`): the word into the sound data, then either a note to the kit's listeners or `0x400a30ca(value, track, slot)`, which writes the word the block is built from. Not used by what was built.
- **Slot 24.** No record of any machine the audio CPU runs has it (`tools/params.py`: their knobs are 18 to 23, 25 and 26). The analog machines and the MIDI machine do. It is inside the 20 bytes a track the audio CPU is sent. There the voice loop copies the word into the voice at + 1004 (`0x4000444c`), and four places test that long for zero and nothing else: the shared envelope after its attack (`0x40003d8e`: hold, or go on to decay) and three machines' own code (`0x400073ac`, `0x40008288`, `0x40008912`). A flag, "hold". Twinshot's update clears it (`0x40009916`), and ours always has.
- A trap in our own listings: binutils prints the displacement of an indexed operand in hex with no prefix. `%a0@(14,%d2:l:2)` is + 20. Three numbers above were first read as 14 and 14 less.

INFERRED, not confirmed: that every way a step is played gathers its locks with `0x4008b8a8` (two callers: the sequencer at `0x4008bc60`, read, and `0x40104fc4`, not read); that a kit is saved slot for slot. **A pattern is: a lock on slot 24 of a digital track was there after a save and a power cycle on the maintainer's unit (2026-10-10).**

NOT FOUND: what slot 24 holds on a digital track nothing has written to (what a new kit or a change of machine puts there). Nothing built depends on it but for two values, see the reclock image. On the maintainer's unit it is neither of the two on the sampler tracks of the project he played (2026-10-10).

## LEN stops at 3, at 6 in its first build: the floor image (2026-10-10, sections 3 and 7 of OS 1.42)

On request.

- First built with 6. That ran on the unit inside the reclock image: "ok yea it works but i actually want it to go down to 3 instead". Now 3: five bytes of the image, each a 6 that is a 3 (one in the descriptor, four in the engine's two tests).
- The knob: LEN's descriptor gets a least value of 3 (one long, the fourth of machine 44's records). Stock's own knob routine holds a turn to it, **seen on the unit with 6**.
- The engine, built with `FLOOR`: LEN is taken as no less than 3 where a note starts and where the knob is followed while it plays. For what does not pass the knob's range: an LFO, a lock, a pattern saved with less.
- `make image-floor`, on the live image. 16 bytes more in each of two of the sampler's runs.

Shown in emulation (`tests/test_floor.py`, 126): the engine is the reference model (`Player(..., floor=True)`) bit for bit over all 29 of the live image's scripts, several of which take LEN under 3 and to nothing; a note started with LEN at 0, 0.5, 1, 2 or just under 3 is the note at 3, sample for sample, as a loop, once, backwards, ping-pong and in stereo; LEN turned all the way down under a running loop leaves a loop of 3; with LEN at 3 or more, at rest or moving, it is the live image's engine bit for bit; LEN's record reads 3 to 127 and no other descriptor moved; the main program differs from the live image's in that one byte.

What 3 is: 3/127 of what the sample has left after STRT. 0.13 s of a 5.46 s sample from its start; less on a shorter sample or with STRT further in. NOT CONFIRMED, needs the unit: that 3 is where he wants it.

## A step's REC is a lock of its own: the reclock image (2026-10-10, sections 3 and 7 of OS 1.42)

On the floor image. `make image-reclock`. **Its first build runs on the maintainer's unit since 2026-10-10 and its three checks passed there** (hardware log): a step locked to record records, MODE is not locked with it, the lock is there after a save and a power cycle, and no track records unasked. The file in `build/images/` differs from that build in LEN's floor only.

What was built, and why this and not REC and SRC moved out of MODE altogether:
- **A step's REC is a lock on slot 24**, made, read and removed by the page with the three routines of the steps object, at one of two values: `0x5280` on, `0x2980` off. The sound engine and the feed (`REC_ON`, `engine/sampler.h`) take the high byte: `0x52` is record, `0x29` is not, and anything else leaves the track's own REC to decide. The low byte is in the middle so the smoothing on the way to the audio CPU, whose arithmetic does not run here, cannot carry the mark to the next number.
- **The track's own REC and SRC stay bits of MODE.** A known place, saved with the kit, copied to the audio CPU and not smoothed, and the maintainer's saved settings go on working. Their own values on slot 24 were not built: it would have meant knowing what the slot holds on every track of the unit (a value read as "record" would put every sampler track in record after the flash), and a value left there would be another machine's hold flag once the track's machine was changed.
- A lock is there only where a step differs: REC turned with a step held makes the lock when the step is not to do as the track does, and removes it when it is. So a step is never left with a lock that says what the track says.
- SRC is the track's alone: with a step held it changes the track's.
- MODE on the first page can still be locked. Its lock carries the track's REC and SRC bits, so a turn of the track's REC or SRC writes them into every lock of MODE the track has (`sync`). A lock of MODE the build before made for REC is therefore a lock of the stereo switch after one turn of the track's REC and back.
- A digital track that holds another machine now loses the REC locks it was left with, when its SYN page is next drawn (`strays`): there the slot is the hold flag. Only the two marks are removed. A MIDI machine and the analog tracks are left alone: slot 24 is a knob of theirs.
- Found by the first test of the engine: a take that only a step asks for has to count SMPL as a stereo sample, as a take the track asks for does. One more test in `note_on`.

Code: 398 bytes more in the page's first run (1,506 of 1,522), 348 in its second (1,012 of 1,040); 14 instructions a voice a block on the audio CPU and 12 more where a note starts.

Shown in emulation (`tests/test_reclock.py`, 129):
- The page, **with stock's lock routines run as they are** on a table laid out the way they index it: REC with a step held puts `0x5280` in slot 24 of that step of the active track and nowhere else, with no lock of MODE and no change to the track, on tracks 1 and 8 and for every MODE; stock's count of the step's locks goes to 1 and its listeners are told; stock's own read gives it back; **stock's routine that gathers a step's locks puts (24, `0x5280`) in the event, and stock's routine that applies them puts the word at + 0x4c of the track's 142 bytes and in the smoothing's state**, the word the audio CPU's voice loop reads. Turned back, the lock is removed and the count is 0. A step that is to do as the track does gets nothing. On a track in record a step can be locked off. Every held step gets its own; a held step with no trig gets one first; steps past the pattern's length are not held steps. With no step held REC is the track's, with its pop-up. The page shows a held step's REC, the track's otherwise, and the track's for a value that is not a mark. SRC with a step held changes the track. MODE can still be locked and it is all its turn locks. A turn of the track's REC or SRC goes into every lock of MODE; the stereo switch does not. A track that is no sampler loses the two marks and keeps any other value and any other slot; a MIDI track, an analog track and a sampler keep everything.
- The sound engine: a step locked on starts a take though the track's REC is off, in the stereo sample SMPL names, for every MODE; a step locked off plays though the track's REC is on, and nothing is taped over; ten other values of the slot leave the track's REC to decide, both ways; the mark holds through the whole low byte; the take ends when the lock is put back, and a take the track started ends at a step locked off; playing is the floor image's engine bit for bit whatever else the slot holds, knobs moving or not.
- The feed: it runs for a step locked on, from the track's source; not for a step locked off; other values leave it to the track's REC; the first track in record by either way picks the source; a mark on a track that is no sampler feeds nothing.
- The image: it differs from the floor image in our runs of code and the pointers into them; the stock lock routines are byte for byte stock's; no knob of a machine the audio CPU runs is on slot 24.

Played by the test, not run: the holder's methods for MODE, the steps' trigs (stock's two questions and the routine that gives a step a trig, called as stock's own + 148 calls them), the keys object.

INFERRED, not confirmed:
- that slot 24's word comes through the block builder as it went in when a lock put it there (the lock is written into the smoothing's state too, and the mark has half a number to spare either way);
- that removing a lock from the routine that draws the page is safe (stock changes locks from a turn of a knob; ours does it there only for a track whose machine was changed with REC locks on it);
- that nothing else writes slot 24's word of a digital track while a lock is in force.

Confirmed on the unit, 2026-10-10 (first build): a lock on slot 24 is played like any other, so the mark comes through the block builder as it went in; no lock of MODE is made; the lock is saved with the pattern and is there after a power cycle; no sampler track of his project has either mark in the slot unasked.

NOT CONFIRMED, not asked of the unit yet: a turn of the track's REC and back clearing the REC locks an earlier image made; a track changed to another machine losing its REC locks, and the lock removed from the draw doing no harm.

## The mixer run whole: 14 kernel passes, and the dry mix is at `0x8000dad0` (2026-10-09, sections 3 and 7 of OS 1.42)

Asked: what one-track stereo would cost the main CPU. Tests in `tests/test_mixer_whole.py` (4), addresses in `tools/mainmap.py`. What is wanted and what is left of the idea: `docs/STEREO.md`, "One-track stereo". Nothing is built.

- The real mixer `0x4008f242` runs whole in the emulator once five helpers are made returns: `0x4009748c`, `0x40096908`, `0x40096eb4`, `0x40096e32`, `0x4009687a` (the delay, the reverb and their set-up, on state made elsewhere). The scale routine `0x4008ef42` is a return there too: it runs the EMAC in integer mode, which `emu/` does not model. The rig maps `0x43bd0000`, `0x454e0000`, `0x45540000` and the peripherals, points `0x800030b8` at 12 x 291 zero bytes and fills 16 longs at `0x454e4c18` with `0x7fffffff`. This replaces Phase 8's "could not be run": the body runs, the effects do not.
- CONFIRMED by counting calls in that run: 8 passes of `0x4008f0b6` (8 inputs), 2 of `0x4008f024` (9 inputs), 4 of `0x4008ef8c` (10 inputs), 6 copies (`0x4008f22c`), 24 calls of the gain function, 14 of the pan law, 12 of the per-track level `0x4008ff34`, 3 of the scale.
- CONFIRMED on a marked track panned hard left, sends at 0: after the first two kernel calls `0x8000dbd0` and `0x8000dbd4` are silent; after the four 10-input passes (`0x4008fb78`) `0x8000dad0` carries the track and `0x8000dad4` is exactly empty; slot 7 of the output frame moves, slot 2 for a track panned hard right. With the delay send at 127 `0x8000dbd0` carries the track and the dry mix is the same to the bit. With the reverb send at 127 it is silent at that point (its sum is made later, in the same place). **So `mm.BUS_L`, `mm.BUS_R`, `mm.GAIN_L`, `mm.GAIN_R` and Phase 4's "stereo bus" are the delay send, and the dry mix is `0x8000dad0` / `0x8000dad4` with gains at `0x8000e188` / `0x8000e160`.** Phase 4's conclusion is not touched: the pan gains are the same ones.
- Read in the listing: the 10-input kernel's ninth and tenth inputs are `0x80004150` and `0x800041d0`, right after the tracks, filled before each dry pass with one side of the delay's and the reverb's return. Tracks routed to the FX block are summed into `0x8000dfd0` / `0x8000dfd4` with gains at `0x8000e138` / `0x8000e110`, and go to slots 5 and 3 of the output frame.
- CONFIRMED by running it: a kernel replaces what is at its destination, leaves the other side of the stride alone, and writes its ramped gains back. One call is 686 instructions with or without ramps (the 9-input one 750 and the 10-input one 812, counted the same day and not in the test).
- Counted: the mixer without its effects is 20,820 instructions a block, the same for silence, for 8 tracks of noise and with the sends up (within 2). The three scale calls would add 187 each by the listing: 21,381. Its parts: per-track gains 2,600, FX track and return gains 334, delay send sums 3,154, reverb send sums 3,528, dry sums 5,474, per-track levels 2,949, output loops 1,467, the rest 1,314.
- Counted from scripts that were not kept (2026-10-09): the receive unpack `0x400962ac` 1,484 and the frame copy `0x4008ee86` 388; our hooks around the mixer call in the load image, mixer stubbed, 571 with no sampler track, 637 with 8 mono samplers, 1,261 with 4 stereo pairs, 3,433 while a track records.
- Audio CPU, the four stages after the voice loop (real interrupt, 8 Twinshot tracks, 40 blocks) (`measure_stages.py`: no longer in the repo, in git's history before `1cb0b36`; the maintainer keeps a copy under `firmware/`): 3,819 instructions a track a block, 4,035 at worst. A track: `0x4000112c` 1,013, `0x40002320` 330, filter 2,373, amp 103. The counts hold with the knobs moved, and the knobs do reach the stages: OVER at 127 changes the sound from `0x4000112c` on; every filter page knob at its end leaves `0x4000112c`'s output the same and changes `0x40002320`'s; each of eight values of the per-track word at block offset `0x188` changes the filter's output. That is part of Phase 4's open question: OVER acts in `0x4000112c`, and a filter page knob (which one was not found) acts in `0x40002320`.
- Measured: a half-scale sample on factory Twinshot peaks at 777,926,440 after the voice loop and 92,288,553 after the amp stage.

NOT CONFIRMED:
- What the five effect helpers cost, so the mixer's total. The main CPU's clock and load: never measured, so there is no budget for it. A build that times the mixer hook with a hardware timer, or one that burns a number of instructions set by a knob until the sound breaks, would give one; both need the unit.
- How the digital tracks' dry mix reaches frame channels 0 and 1, which the recorder's MAIN source reads. In the rig, with only digital tracks sounding, channels 2 and 3 move and 0 and 1 do not; the rig's state is mostly zeros and its effects are returns, so this says little. Worth a look before the meter or the recorder lean on those channels.
- Whether the track buffers are all in `0x80003d50` when a hook in front of the mixer call runs (the transfer is started before it; its end was not looked for).

## A frame between two is worked out from sixteen: the pitch image (2026-10-10, section 7 of OS 1.42)

On request.

What he hears, measured. Up to the reclock image a frame between two of the sample's is on the line between them. A tone in a sample played two octaves down, against everything else that then comes out (a model of that line, `python -m tools.sinctable`):

| tone | 1 kHz | 3 kHz | 6 kHz | 10 kHz | 14 kHz |
|---|---|---|---|---|---|
| the line, dB from the tone to the rest | 62 | 43 | 30 | 21 | 14 |

The rest is the sound folded around the sample's own rate, which the line only turns down by so much: the sound of a low sample rate. The same at every pitch that is not the sample's own.

Tried in the model before anything was built, at 6 and 10 kHz: four frames and a cubic through them, 44 and 29 dB; four frames and a B-spline, 67 and 46, with the top of the sound 8 dB down; a windowed sinc of 8 frames, 66 and 68; of 12, 78 and 81; of 16, 90 and 83. A table of more rows with no blending between them does not get there: 64 rows of 8 frames, 49 and 45.

**Built: 16 frames, 32 rows a frame, the row for the place and the next one blended** (`tools/sinctable.py`, `engine/sampler.h` under `HQ`).
- The frame at i + f/4096 is the sum of frames i - 7 to i + 8, each times a number of a row. A row is the sinc for that fraction of a frame under a Kaiser window (beta 8), in 15 bits, made to add up to exactly 32,767 so a steady level stays where it is. Row f >> 7 and the next give two sums, d0 and d1; the frame is d0 + ((d1 - d0) >> 7) x (f & 127), held to 30 bits either way (a sinc can pass the frames it joins) and doubled.
- **f = 0, a frame of the sample itself, is that frame.** Nothing is summed. So a sample at its own pitch plays bit for bit as it did, and costs less than it did.
- Past either end of the slot the end frame stands in.
- The image holds rows 0 to 16 (544 bytes): row 32 - r is row r backwards, but for the middle one, which adds up to an odd number and is used as it is. The engine keeps all 33 in free SDRAM at `0x44060004`, with a long at `0x44060000` that is worked out from the table: the hook looks at the long on every interrupt and makes the copy when it is not this build's. First seen wrong in the first run against the model: the middle row had been written twice, the second time backwards.
- The sum is in assembly (`hq_mid`, `engine/stub.S`): sixteen frames unrolled, six instructions each. Near a slot's end sixteen frames are copied out first, in C.

Where it went. The table takes the recorder's run (`0x40004a6a`) whole. What was there and the step after the voice loop moved to five more runs nothing reaches: `0x40001708` (344 B, the step after the loop), `0x400027f6` (280 B, the keep and load step), `0x40004708` (226 B, the recorder's step), `0x40001900` (214 B, the copy of the table and the slot-end case), `0x40003512` (204 B, two small routines). The sum itself is in the second run, in the room the step after the loop left. All five pass the rules the earlier runs are held to (`tests/test_sampler.py`): no long and no instruction outside our runs names an address in them, each begins and ends on a routine's edge, and none is run or read by any stock machine or by the whole interrupt.

Measured on the compiled engine's own output (`tests/test_pitch.py`), a tone two octaves down:

| tone | 1 kHz | 3 kHz | 6 kHz | 10 kHz | 14 kHz |
|---|---|---|---|---|---|
| reclock image | 64 | 45 | 32 | 22 | 15 |
| pitch image | 89 | 85 | 86 | 80 | 76 |

And 75 dB or better at 6 kHz an octave down, five semitones down, one down and seven up.

Cost, instructions a block: a stereo voice at its own pitch 413 fewer than before; a mono voice pitched 4,006 more; a stereo voice pitched 7,848 more. The whole loop with eight mono voices all pitched: 56,583, against 84,048 for eight SY SWARMs. With four stereo voices all pitched the rig counts 76,901, of which about 23,000 is the four right-hand tracks as the rig leaves them (a voice that never had a note costs 6,900 there, 1,153 on a voice the unit has set up).

Shown in emulation (163 tests, and the 73 of `tests/test_sampler.py` with the five runs added): the engine is the reference model (`Player(..., hq=True)`) bit for bit at seven pitches over all sixteen cases (whole, cut, looped, backwards, ping-pong, stereo, the short slot) and with the knobs moving; at its own pitch it is the reclock image's engine bit for bit; a steady level stays within 4 parts in 100,000 at five pitches; full scale switching every few frames reaches the stops both ways and does not wrap; the table is made on the first block from the image's rows whatever the memory held, is left alone after, and is made again when the long is another build's; nothing in stock's program names its memory; the main CPU's program is the reclock image's byte for byte.

Seen on the way: stock's pitch table makes an octave down a step of 2047/4096, not 2048. So an octave down no frame but the first falls on the sample's own.

Not done: played above its own pitch a sample still folds what goes past the output's rate, as before. The table's edge is the sample's own; a second table for upward pitch would be 544 bytes more.

NOT CONFIRMED, needs the unit:

| Question | What was assumed | Check |
|---|---|---|
| Is the grit gone | it was the line's folding, 30 dB under a 6 kHz part and now 86 | a bright sample played one and two octaves down |
| Time | counts are instructions; sixteen frames are read a frame where two were, and nothing here models the cache | eight sampler tracks all pitched and playing at once: no crackle, the screen and keys as quick as before |
| The table's memory | SDRAM at `0x44060000` is free and keeps what is written: the takes' buffers above it and the marks just under them do | the first check: a table that is not there would be noise or silence on every pitched note |
| The five new runs | nothing on the unit reaches them | the unit boots and every other machine sounds as it did |

## The pitch image, second build: a low note's first and last blocks (2026-10-10, section 7 of OS 1.42)

Maintainer, with the first build on on the unit.

Looked for in the reference model, which the compiled engine matches bit for bit:

- **A steady note is clean at any pitch.** A sine in, and every frame put out against the sine it should be, from 100 frames into the sample: 200 Hz, 1 kHz and 5 kHz, at speeds from an octave down to seven octaves down (steps of 2047, 1024, 777, 512, 256 and 37 in 4096). The largest error of any single frame is 75 to 86 dB under the tone, and no step from one frame to the next is larger than the sine's own by more than 1.5%. So nothing clicks between a note's ends.
- **Within reach of a slot's ends the first build was slow.** There the sixteen frames are not all in the slot, and it put them together afresh for every frame it made, at more than twice the work of a frame elsewhere. That is the first 7 frames of a sample and its last 8, and a note two octaves down is on each of them four times, four octaves down sixteen times. Measured in the real voice loop, a block over the reclock image's: 4,006 mono and 7,848 stereo in the middle of a note, but 9,411 and 18,897 in the first block two octaves down, the first two blocks three octaves down, the first four at four. The tests of the first build timed a note from its third block, 7 semitones down, and never saw it.
- With one sampler track that is still under what the unit's heaviest machine asks on all eight. With several low notes starting on the same step it is not: eight mono voices in that first block are about 93,000 instructions against 84,048 for eight SY SWARMs. **What the audio CPU does when a block's work does not fit its time is not known**; a click at the notes' start is what it would be.

The second build (`4f62d8ea...de98`): a note's start writes the frames around both ends of its slot out once, the end frame standing in for what is past it, 45 a side (frames -7 to 14, and n - 15 to n + 7), into 256 bytes a voice of free SDRAM at `0x44060800`, and keeps the address in the voice's state (+ 72 of our 88 bytes; 12 are left). A frame within reach of an end is then summed from there by the same routine as any other. The sound is the first build's to the bit: the reference model did not change.

- A low note's first block is now 1,401 to 1,480 instructions over one of its middle, mono, and 2,089 to 2,195 stereo, of which 975 and 998 are a note's start as it always was. No other block of the note costs more than its middle, to its last frame.
- `hq_edge` is gone; `hq_pads` has its run (`0x40001900`), and `hq_init` moved to `0x40003512`.
- Tests: `tests/test_pitch.py` (236): 63 more that play slots of 3 to 300 frames three octaves down, forwards, backwards, stereo, looped and cut, bit for bit the model; the frames written out, once, for the right voice; every block of a note two, three and four octaves down counted from its first frame to its last.

**Not known: whether this is what he hears.** If it is one track alone it is not this. What else there is at a low pitch, read and not changed: the fades where a sample is cut into are 64 and 128 frames put out whatever the pitch (1.3 and 2.7 ms), so against a sound played four times slower they are four times shorter than at the sample's own pitch; a take begins and ends wherever the mix was, and a note that plays from a sample's own first frame or to its own last gets no fade; and stock's amp stage takes a note that is cut by the next trig to nothing over the 32 frames of the trig's block. He has been asked where the clicks are.

## The pitch image, third build: the table is made at every start (2026-10-10, section 7 of OS 1.42)

On request Which of the two builds was on the unit then is not known; both have what follows.

**The fault, read from our own code.** The table's 33 rows are in free SDRAM, and the first two builds made them only when a long beside them (`0x44060000`) was not the number the table is built with. Nothing clears that memory. Memory that is without power for a moment comes back mostly as it was, so after the unit has been off and on the long can be whole and bits of the table's 1,056 bytes not. Then every frame between two of the sample's is summed with wrong numbers, and a frame of the sample itself, which uses no table, is right. That is what he describes: wrong and noisy with TUNE moved, and it would be right on the first start after a flash from an older image and worse after later ones. The clicks and pops of the first report may have been the same thing with fewer bits gone. **Not proven: nothing here can show what the unit's memory held.** A check that needs no flash: off for a few minutes, on, and a pitched sample is clean again.

Looked for and not found, in the audio CPU's whole interrupt run in emulation (`emu.engine.Board`, the filter and amp stages with it) on the second build: no code but ours writes the table, the frames around a slot's ends, or the bytes of a voice's state that we use, but for stock's voice reset.

**Stock's voice reset** (`0x40003ee0`), read and run: it clears a voice's + 1712 to + 1780 and its + 1792 and + 1796, and puts numbers of its own at + 1784 and + 1788 (from `0x40014b7c` and `0x40014980`). The init calls it for every voice (`0x40000fe8`), and the voice loop calls it in the block a note starts in when the track's machine is on another engine than the voice last ran (`0x4000441c` on): a track's first note after its machine changed, and not otherwise.

The third build (`f364e2ae...c15b`): what says the table is made is the long at + 80 of voice 0's sampler state, `0x80000700`, which that reset clears. The interrupt's first block after a start finds it clear and makes the table from the rows in the image, whatever the memory holds; so does the block after track 1's first note on a new machine. The long at `0x44060000` is no longer read or written. Same sound to the bit.

- Tests: `tests/test_pitch.py` (240). A table left with the old long whole and 1, 8 or 400 of its bits changed is made again at a start; it is made once, not again by other voices' resets, and again after voice 0's, with stock's reset run as it is; the init is the one place that names the reset.
- The cost tests now play a voice's first note before they count, since that note has the reset in it.
- The pitch, meter and save images change; the 16 before them build to the same hashes.

## The pitch image's noise is not explained, and the safe image (2026-10-10)

On request.

**So the table is not it, or not all of it.** A take at its own pitch is read a frame at a time and no table is used; and with no restart the table is the one the start made. What is left of the entry above is a fault that was real and is fixed, not the cause of what he hears.

Tried since, in emulation, and clean:

- A take recorded and played back on the pitch image, which the recorder's own tests never ran on: the take is what was fed, to the sample, and at its own pitch it plays bit for bit as on the reclock image. With MODE holding a source number too, as the meter image has it.
- The audio CPU's whole interrupt, its filter and amp stages with it (above).

Not known, and each would give noise on the unit and none here: that the unit's speed at a pitch is exactly 4096 at "normal pitch" (the main CPU smooths TUNE's word, and one step off puts every frame between two, so the sum of sixteen would run on what he calls normal pitch); what the audio CPU does when a block's work does not fit its time, and how long sixteen multiplies a frame take it (instruction counts say eight pitched voices fit; the processor's multiply and its cache are not modelled); that the five runs of code the pitch image added are reached by nothing (static evidence only).

**Read since, the same day, and one of the three answered: "normal pitch" on the unit is exactly normal.**

- The knob filter (`0x400979fe` on, section 3) keeps a long a word, adds `0x03d7` of the new word to `0x7c29` of the long, and sends `(long + 0x8000) >> 16`. The two numbers add up to 1 exactly and what is sent is rounded, so a word at rest is the knob's own value. Worked by hand from the listing, from below and from above, with the accumulator read truncated and rounded: `0x4000` every time. Not run.
- Stock's pitch routine (`0x40006704`), worked from its listing with its own table (`0x8000a888`, first entry `0x40000000`), note 60: TUNE words `0x4000` and `0x4001` give a step of 4096, `0x3fff` 4095, `0x4002` 4097.
- So a take played with TUNE in the middle is read a frame at a time on the unit as it is here: no table, no sum, the same arithmetic as the reclock image. **What he heard on a take at its own pitch was not made by the sum of sixteen.** It was in the take as recorded, or it is the audio CPU's time, or the five runs.
- The sum (`hq_mid`, `engine/stub.S`) is `muls.w` and `muls.l`, no EMAC: the emulator's EMAC model has no part in it.
- The audio CPU's caches are on and its SDRAM is cached: `CACR = 0xa50ce100`, `ACR0 = 0x4007e020` (`0x40000000..0x47ffffff`, copyback), set at `0x400010d0`. The table in free SDRAM is not read at bus speed.
- Voice + 1792, where the third build keeps its mark: stock names it in the voice reset and in Twinshot's update (`0x40009a10`, which our images do not reach), nowhere else by that offset.

Still open, and the maintainer's answers choose between them: which file was on the unit (if the meter image's first build, its new feed on the main CPU made the take, and the safe image has the same feed); one track, a loaded sample, TUNE untouched; a steady hiss or bursts.

**The safe image** (`make image-safe`, `bbc49790...2795`): the save image's main program with the reclock image's audio program, each byte for byte (`tests/test_save.py`). The meter, the sources and SAVE are main CPU only, and the audio CPU reads MODE's two low bits and nothing above them. The reclock image's sound engine ran clean on the maintainer's unit. It is what he is given, and it answers one question for certain: with it, is the noise gone.

## A level meter and every track as a source: the meter image (2026-10-10, section 3 of OS 1.42)

On request.

Read, and run where it says so:

- **The rectangle routine, `0x400f7fb6(surface, x0, y0, x1, y1, colour)`.** Run as it is on a surface of the test's (`tests/test_meter.py`). A surface's + 4 and + 8 are its width and height, + 12 the longs a column, + 16 its dots. The dots are kept a column at a time: column x is `stride` longs, and y 0 is the highest bit of the column's first long. Colour 0 clears, an odd one sets, a negative one inverts. It swaps the ends of either pair that come the wrong way round and cuts the rectangle to the surface.
- **Which way y runs.** Stock's own drawing of a knob's place (the method at + 180, `0x4003842c`) calls the same routine twice with the place's (x, y): the name's box is `(x - 4, y - 1)` to `(x + 22, y + 5)` and the picture's `(x - 4, y + 6)` to `(x + 22, y + 24)`. So the picture is at the larger y, and on the unit the picture is above the name (our own text there, 2026-10-09: "a value inside the knob's box, the name under it"). The glyph routine (`0x400f8f70`) indexes a surface the same way as the rectangle routine. y 0 is the bottom row of dots, and a place's box is x 21 to 125 over the four places.
- **The redraw request, `0x400ffe22(page)`,** is two bytes and nothing else: unless the page's byte at + 23 is set, its byte at + 20 becomes 1, and so does the byte at + 32 of the object at its + 44 (`0x40100966`). Run as it is on an object of the test's. So it can be asked from the per-block path, where our feed runs.
- **The pop-up routine (`0x400c347c`) formats at once** into a buffer it allocates, so a name built on the stack can be handed to it.
- **Numbers of ours in a run of code.** The bank image keeps three longs at the start of its run of code and writes them while the unit runs, and it works on the unit. The meter image does the same with four.
- **Two more runs nothing reaches** (`python -m tools.deadcode 3`): `0x40088510..0x4008878a` (634 B) and `0x401bceac..0x401bd242` (918 B). Each starts after a return and ends in one.

Built (`make image-meter`), `f20da37b...f622` with the pitch image's third build under it; `6c6d508d...` with the second (`2e6e2bfb...` with the first):

- **SRC is a number.** Bits 2..6 of MODE's value, where "from the external input" was bit 2: 0 the main mix, 1 the external input, 2..13 tracks 1..12, 14 the FX track's return, 15 the delay and reverb. A value an earlier build saved means what it did. MODE's range goes to 63; its knob still reads MONO or STEREO (`engine/knobtext.c`). The audio CPU reads MODE's two low bits only: its program is the pitch image's, byte for byte.
- **The feed** (`engine/recfeed.c`) takes a take's two sides from where the number says in the frame of 20 channels. A track is one channel, the one its number names (tracks 1..12 are channels 2..13), and goes to both sides.
- **The level.** The feed keeps one number: the largest sample this block of the source the page is showing, top 16 bits, or what it was less a 1024th of itself and one, whichever is more. That is 13 dB a second down. It runs only while the page keeps being drawn: each drawing sets a count to 0, the feed counts blocks, asks for a drawing every 96 (64 ms) and stops at 288.
- **The bar** (`engine/recpage.c`): rows 0 and 1, from x 21, 104 dots at the largest sample a take can hold and ten dots to every halving, so 62 dB in all. A dot three high at x 126 marks the full length. The lower row of places is empty on this page, so nothing else is drawn there.
- Cost on the main CPU, instructions a block: 12 with the page never opened, 641 while the meter runs, 223 more for a block of a take (two channels picked apart, where it was a pair side by side). The mixer without its effects is about 21,400.

Tests: `tests/test_meter.py` (90). The 17 earlier images build to the same hashes. An independent unpacker (elektron-firmware-tool) gives the same eight sections. **Not flashed.**

Not known without the unit: where the bar lands and whether anything of stock's is drawn over it; what sixteen drawings a second cost the main CPU; what a track's channel of the frame holds (before or after its volume and pan; for tracks 9..12 it is the copy the sends and USB get); that one request after the page is left does nothing to the page shown then.

## Saving a take from the page: what has been read so far (2026-10-10, section 3 of OS 1.42)

On request. Nothing is built. Read from the listing, none of it run:

- A job is started with `0x400bdc48(runner, name, done, body)`, the runner from `0x4016ec18()`. Project Save's call is at `0x4005b690` with the name at `0x402500d4`. `done` and `body` are function objects of 16 bytes: 8 of storage (here a pointer to a block from `0x4010394c` and nothing), then a manager routine, then the routine that is called. Project Save's body object has `0x4005a326` and `0x4005ba50`, its done object `0x4005b41e` and `0x4005cbc0`.
- `0x4005b4ba`, which shows SAVING and starts that job, is itself the called routine of such an object (made at `0x4005cd0e`, manager `0x4005afcc`): (the object's storage, a string, a project number, negative for the one in memory). It builds the SAVING screen (an object of 0x88 bytes, `0x400fe4c4`) and hands it to the done object.
- The routine that makes that object starts at `0x4005cc8a`: four callers (`0x4005cfd4`, `0x4005d0a2`, `0x4005e262`, `0x4005e564`) and three places that hold its address (`0x400332e8`, `0x4003382a`, `0x40185e46`). Its arguments are not worked out.
- Our code may write the drive from that job (the keep image, on the unit). Whether it may from the task a knob's turn arrives in is not known.

What it is to write, the maintainer's choice the same day: "SAVE on the page write just the takes", not the project. Two ways to it, neither read through: start a job of our own (needs the done object's screen handling understood), or go in through stock's own save with a flag of ours that makes the hooked save call keep the takes and leave the project alone (needs `0x4005cc8a`'s arguments). Stop here until one of the two is read through.

## A save from the page: the save image (2026-10-10, section 3 of OS 1.42)

On request. Read through since the entry above, from the listing; the three small routines are also run:

- **A job is started with `0x400bdc48(runner, name, what to do, what to call after)`.** It locks the runner (its + 4), makes a string of the name, copies its fourth argument with `0x401849aa` and its third with `0x4019e90c`, and puts the three in the runner's queue. The runner has a worker of its own: Project Save's job runs there, and so does our take writer inside it, on the unit. Nothing in the start draws a screen: SAVING is drawn by the routine that starts Project Save, and handed to its "after" object to take down.
- **A function object is 16 bytes**: 8 of storage, a routine for the storage, the routine to call. The two copy routines are the same: the storage routine is called with (to, from, 2) and the two routines go across. `0x4016dc10(object)` ends one: the storage routine with (it, it, 3). Stock's own storage routine for Project Save's job (`0x4005a326`) answers 0 always, gives the type for 0 and the place of the storage for 1. So an object that keeps nothing in its storage needs only to copy 8 bytes for 2.
- **What a job does is called with the object alone and answers 0 when it went well** (Project Save's, `0x4005ba50`: the project save's byte, turned over). What is called after gets (the object, that answer) (`0x4005cbc0`).

Built (`make image-save`, `0787d661...baa5`), on the meter image, main CPU only:

- `save_start` in the keep code's run (`engine/keeptakes.c`) hands the runner a job named "Take Save" whose two objects are ours. What it does is `keep_takes`, the second half of a project save, which now answers whether every take that was not on the drive is; the project's own save and our sector of the banks are not touched.
- One long at the start of that run, `0x401259fa`, says how it is going: 0 nothing, 1 running, 2 done, 3 failed. It is set to 1 before the runner has the job and by the job itself when it ends, so it does not hang on the "after" object being called. A second start while it reads 1 does nothing.
- The sampling page's fifth place, the first of the lower row, shows it: SAVE, BUSY, DONE, FAIL, in the box, with no name under it, where the meter's bar is. A turn to the right starts a save; a turn to the left puts SAVE back unless one is running. The meter's sixteen drawings a second bring the word up to date.
- The routine that takes REC locks off a track that is no sampler moved to the page's third run, for room.

Tests: `tests/test_save.py` (18). The job as the worker would call it, with the store's write running under it: the takes go to their slots in the loaded bank, nothing else on the drive changes, the project save is not called; a drive error says FAIL and the next save finishes. Stock's two copy routines and its end routine run on our objects. The 18 earlier images build to the same hashes; the independent unpacker gives the same eight sections. **Not flashed.**

Not known without the unit: that the runner takes a job from the task a knob's turn arrives in (stock starts Project Save from a routine called when a name has been entered, which is not shown to be the same task); that nothing else needs to hold while a job runs with no screen over the page (the sequencer plays on during a project save); how long a take takes (a sector an audio block at the least: 2.5 s for 10 s of stereo before the drive's own time).

## One-track stereo: the stereo image (2026-10-10, sections 3 and 7 of OS 1.42)

The maintainer made it the next build ("stereo.md/one travck stereo is noumber one"). Built: `make image-stereo`, SHA-256 `83777a0d4bf2052de86a0f42a632b8465398ddc0ae2f87ae6313486bfb323aa8`. Not on the unit. The design and what the unit has to answer: `docs/STEREO.md`, "One-track stereo". Tests: `tests/test_stereo.py` (71), rigs in `tests/stereo_rig.py`. Constants: `tools/audiomap.py` (`ONE_CAVES`, `STAGE_*`, `FILTER_*`, `RW_*`), `tools/mainmap.py` (`RIGHT_*`, `EFFECTS_MEMORY`). Emulation only.

**The audio CPU's four stages after the voice loop, read and run.**
- `0x4000112c` (out, params): OVER. It reads the word at params + 80 (slot 26) and a level at + 50, does all eight tracks a call, two at a time. What it keeps (`0x800083b0..0x80008450`, 40 longs) is ramps made from the knobs: CONFIRMED by running it on two different signals from the same start and comparing that memory. It does not hear the sound.
- `0x40002320` (out, params, trig): the BASE and WIDTH filter. It reads params + 102 and + 104 (slots 37 and 38), tables from `0x40040060`, all eight tracks a call in pairs. It keeps two sums a track at `0x800088a0` and clears them when the next stage has left a flag for the track at `0x80008550` and params + 130 is not 0. This answers Phase 4's open question: the two were called gain and drive, and are the overdrive and a filter.
- `0x400019d6` (params + 82, buffer, the track's long from `0x80008188`, track, trig, the word at params + 130): the multimode filter, one track a call. A track's own memory: a flag at `0x80008550 + t` and one at `0x80008558 + t`, its type at `0x80008560 + 4t`, a sum at `0x80008580 + 4t`, eight coefficients at `0x80008740 + 32t`, three levels at `0x80008840 + 12t`, a number at `0x800088e0 + 4t`, two sums at `0x80008920 + 8t`. Scratch: `0x80008720..0x80008740`, `0x80008900..0x80008920`, two buffers at `0x80008960`.
- `0x4000168e` (out, params, trig, release, flags) calls `0x40001476` (buffer, state, params + 106, trig bit, release bit, track, flag bit) for each track: the amp envelope. The state is handed in, 12 bytes a track at `0x800049e0`, and follows the trigs, not the sound.
- **The filter leaves two numbers for its next call.** For types 2 to 6 it works out all eight coefficient targets in its scratch; for types 0, 1 and 7 it works out six and takes the last two (`0x80008918`, `0x8000891c`) as it finds them, from whichever track it was called for before. CONFIRMED: the first prototype of the right channel differed from stock in exactly those two coefficients on a type 7 track, and nowhere once the right channel was handed the two its left had found.
- Counted again in this rig (eight sampler tracks, a steady block): the three stages before the last 29,739 instructions, the last 773.

**Stock's four stages can be run on a second set of buffers with a second set of state.** CONFIRMED twice, bit for bit against the stock interrupt fed the same signal on a track: first driven from Python with nothing of ours in the image (the stock routines called on the right buffers, the two filters' memory exchanged by hand; that script was not kept), then as built. Six runs of 80 blocks with every stage knob, the trigs, MODE and the machines moving: the left channels are stock's of what the voices made, and every right channel is stock's of it from the block it comes on. A right channel that comes on mid-flight starts from the left's memory and nothing jumps: the reference for it is a stock track fed the left up to that block and the right after.

**How the two CPUs take turns** (read; none of it run or timed).
- The audio CPU's interrupt is its timer 0 set to capture any edge of a pin (`movew #0x00c1,0xfc070000` at `0x40000e40`, the event cleared at the interrupt's start). The main CPU makes the edge: `0x40082f6a` flips a pin through `0xec094018` and `0xec094024`. During boot the pool sender calls it a chunk; while the unit runs, the routine at `0x400a2058` does, once a block: it ends in `rte`, clears the interrupt request of channel 54 of the main CPU's own transfer controller (`0xfc04401c`), calls the flip if the audio CPU is up, and sets bit 31 of `0xfc04c010`, which the per-block routine `0x400a38ce` clears as its first act.
- So a block: the edge starts the audio CPU's interrupt; it copies the knobs out of the window itself (`0x400010e4`, `0x1b0` bytes from address 0), runs the voices and the stages, and starts the transfer of the eight buffers into the window as its last act. The main CPU's routine, started by the same event, works through the sequencer's events, starts its own transfer of the eight buffers out of the window (`0x400a4aec`; a second place, `0x400a47fa`, on a path that skips the mixer), builds the next knobs, waits for that transfer (`0x400a20ae`, called at `0x400a4e30`), and sends the knobs (`0x400a4e3c`, 27 x 16 bytes from `0x80002000`). **Both CPUs use channel 47 of their own controller for it, and the main CPU uses it for both directions.**
- What the main CPU reads at the start of a block is therefore what the audio CPU wrote at the end of the block before, and stock leans on the main CPU reading it before the audio CPU is done with the next. INFERRED from the order; no timing is known.
- The window is chip select 0 of both CPUs: base `0x10000000` (main, `0x40082516`) and 0 (audio, `0x40000566`), mask `0x00010001`, control `0x00100780`. By that family's register layout as remembered, not checked against a manual here: 128 KB decoded, a 16-bit port, one wait state. INFERRED. It fits "the window stores 16-bit words".
- Both CPUs: `ACR0 = 0x4007e020`, `CACR = 0xa50ce100` (`0x400010ca`, `0x40000554`). Read the same way: the first 128 MB of SDRAM cached with copy-back, everything else uncached. INFERRED. If so, a transfer may not be pointed at SDRAM by its cached address, which is why stock's buffers on both sides are in on-chip SRAM, and why ours cross by the CPUs' own reads and writes.
- The audio CPU's own FPGA bitstream unpacks to 54,664 bytes, the size of a Spartan-3A XC3S50A's. INFERRED from size alone, like the other one.

**Main CPU memory after the program's data** (a correction).
- The delay and reverb helpers name `0x4d570000` three times (`0x40096c86`, `0x40096e86`, `0x400975a4`) and clear `0x90000` bytes there: 9 x 64 KB, the effects' own memory, to `0x4d600000`.
- The entry of 2026-10-07 ("77 addresses in all, `0x4d5cf088..0x4f8af2ca`") took `0x4d5cf088` for the lowest block. It is not an address: at `0x40080882` it is added to `0x80000` (`0x4d64f088`), and `0x4d5ef088` is added to an offset the same way. Both lie inside the effects' memory.
- So, taken `0x08000000` lower, what nothing names after the data is `0x45566490..0x45570000`: 39,792 bytes, not 428 KB. The second set of buffers is in it, at `0x4556a000`, a page clear of both ends. CONFIRMED by scan: no 32-bit value at any offset of sections 2, 3, 4, 6 or 8 is an address within 4 KB of it, as it is or `0x08000000` higher. NOT CONFIRMED: that the upper addresses are the same memory seen twice (2026-10-07). If they are another 128 MB, the place is free all the same.

**The mixer's right-hand passes on a second set of buffers.** CONFIRMED by running the whole mixer (the rig of `tests/test_mixer_whole.py`, with the delay's and the reverb's outputs given numbers and their levels up, so the two returns sound):
- Seven operands: the `pea 0x80003d50` of the four right-hand passes (`0x4008f80c`, `0x4008f944`, `0x4008fb52`, `0x4008fb6a`) to the second set, and the `pea` of the three copies of a return made before a right-hand pass (`0x4008f92e`, `0x4008fb2e`, `0x4008fb3c`) to after it.
- With the second set a copy of the first: every sum, both output frames and the gains left for the next block are stock's, bit for bit, in the same number of instructions.
- With some tracks' right buffers different: the left side of the delay send's sum, the dry mix and the FX block's sum is stock's with the left buffers, the right side stock's with every track holding its right buffer. Pan hard left is the left channel alone, hard right the right alone, the middle 0.75 of each on its side.
- Every place the code names the eight buffers or the two returns is one of 21: the mixer's eight passes, six copies and two last uses (a track's level, and the frame's channels 2..9), and the three places of the per-block routine that fill or clear them. So a track's own channel of the frame, which the USB track outs and the recorder's T1..T8 sources read, is its left.

**Room.**
- Audio CPU: four more runs nothing reaches, 804 bytes, 752 used, and 222 in the run of the step after the voice loop, which gave up as much when it stopped lending the next track. One of the four, `0x40000b92..0x40000d06` (372 bytes), is stock's reader of a pool from a flash chip, before the entry point, where `tools/deadcode.py` takes everything for live. Surveyed with the entry's own piece as the only root it is reached by nothing; its one caller (`0x40000cda`) is in it and is called by nothing.
- Main CPU: one more run, `0x401bcb6c..0x401bccc6`, 270 of 346 bytes.
- **A restart of the audio CPU.** Its start clears `0x5b0` bytes of the window (`0x40000e98`), which is stock's part and none of ours, and the boot's chunks then pass through `0x800..0x1000`, where seven of our halves are. So the long of the last block before a restart would still be there, with halves that are no longer sound, when the main CPU first reads it again: one block, before the audio CPU's first interrupt has written its own. The main CPU's routine therefore sets the long to 0 in every block in which the audio CPU is down. The boot's exchange does not use that place (its words are at 0 to `0xc`, its chunks from `0x800`). Run in the rig; that the main CPU can write there while the audio CPU boots is as the recorder's ring and the boot's own chunks do.
- The window: `0x5b0..0x800` (592 bytes) and `0xe38..0x1000` (456). A track's 32 frames do not fit eight times in either or in both as wholes, so they go as sixteen halves of 64 bytes: nine from `0x5c0`, seven from `0xe40`. The long at `0x5b0` says which tracks have a right channel.

**Cost, instructions a block** (lower bounds: no cache, no window timing).
- Audio CPU, the right channels: 16,041 for the first (the two stages that do all eight tracks a call, one track of the other two, the exchanges, the window), 2,703 for each more, 34,962 for eight. With no right channel anywhere: 23 more than the save image in the last stage's call, 116 fewer after the voices.
- Whole interrupts, eight sampler tracks, against stock's heaviest machine on all eight (117,348): eight stereo at their own pitch 94,251. Pitched, where a stereo voice sums sixteen frames twice a frame: one 67,964, four 107,544, five 120,739, eight 160,319. The save image with all eight tracks set to stereo and pitched is 124,364 already.
- Main CPU: 732 with no stereo track (eight copies), 979 with eight from the window. The mixer without its effects is 21,381.

NOT CONFIRMED, all of it for the unit:
- That `0x5b0..0x800` and `0xe38..0x1000` of the window are memory both CPUs see. Nothing of stock's touches the first after the audio CPU's start, and the second only at boot. If they are not, the long does not agree with itself, the main CPU reads no half, and every track is its left on both sides.
- Whether the main CPU has always read a right channel before the audio CPU writes the next. The audio CPU writes them last, just before it sends the left ones; the main CPU reads them first, where it waits for the left ones. That is stock's own order, a little tighter on the main CPU's side.
- What the audio CPU can do in a block. Past 117,348 there is nothing to go by. (2026-10-11, the unit: 94,251 is fine and 160,319 is not. "Pitched stereo was past the audio CPU's time", below.)
- Whether the gap after the main program's data is as free as the scan says.

## Stock Twinshot's code is room (2026-10-10, section 7 of OS 1.42)

The the maintainer's report. Taken as: count its code as free, and use none of it now. Nothing in any image changes: the stereo image in `build/flash_this/` is the file it was (`83777a0d...`), so that what the unit says of it is said of one-track stereo alone.

- Twinshot's update `0x400097dc..0x40009a8a` (686 bytes), its render `0x40009a8a..0x40009b1a` (144), its sample player `0x40006764..0x400068ea` and its filter `0x400068ea..0x40006966` (514 together). `tools/audiomap.py`, `TWIN_ROOM`.
- CONFIRMED in the built stereo image (`tests/test_stereo.py`): in stock the first two are named by engine 11's table entries alone, and the last two by the render alone; with those entries the sampler's, no even 32-bit value and no instruction outside the four names an address inside them, no far branch goes there, and none of it is run or read while all twelve machines play through the whole interrupt, the sampler in stereo on eight tracks among them.
- `tools/deadcode.py` finds the player and filter unreached in the built image and does not list the update and render: the routine before the update ends in `jmp 0x400045a0`, and the tool cuts code at `rts`, so it takes them for part of that routine. Worth knowing of the tool: a routine that ends in a jump hides what follows it.
- Two numbers in stock read as addresses in these runs and are not: `0x400068a9` at `0x40017e3a` is odd, the low half of one entry of a table of longs and the high half of the next.
- Still live, and called by the sampler: `0x40006704` (pitch), `0x40003d42` (envelope), `0x400045a0` (amp), `0x400049f4` (mix), and the decay table.
- Room on the audio CPU now: these 1,344 bytes and 442 in four small runs. (2026-10-11: the stereo image's second build uses the update and render, 790 of 830 bytes. Left: the player and filter, 514, and the 442.)

NOT CONFIRMED: anything on the unit. It is the same kind of evidence the runs our code is in had before they ran there.

## Pitched stereo was past the audio CPU's time: the stereo image, second build (2026-10-11, section 7 of OS 1.42)

On request (hardware log). That is the one thing the first build's numbers said could happen: at its own pitch a sample is read a frame at a time and nothing is worked out; pitched, a stereo voice summed sixteen frames twice a frame.

**What the unit has said about its time, the first numbers there are.** Instructions an interrupt, eight sampler tracks: 94,251 (eight stereo at their own pitch) is fine. 160,319 (eight stereo pitched), 1.37 of SY SWARM on all eight, is "major distortion", on everything by the maintainer's word. Where between the two it gives way is not known, and neither is what the audio CPU does when it does: the sound says the main CPU is handed blocks that are not whole.

**Where the 160,319 went** (counted by routine, one steady block): the sums of sixteen frames 61,963 (`hq_mid`, 16 a frame for 16 channels, 121 instructions and 32 multiplies each), the loop around them 20,152 (63 instructions a frame at a sample's own pitch, 79 pitched: it asked after the walls and the fades at every frame), the right channels' stages about 35,000, stock's stages on the left 29,739.

**The second build** (`engine/sampler.h`, QUICK; `engine/stub.S`, `hq_run`): the same frames for less work.
- The sums are made in the multiply and accumulate unit, as stock makes all of its own. A frame is put at the top of a long (`mvz.w`, `swap`, or fetched as a long and its low half cleared), a table number is held shifted up 15, and the unit's product of two signed fractions is then the two multiplied, times 2^8, with nothing under the 40 bits the unit keeps: read back, an accumulator is the integer sum the old routine made. The rows add up to 63,807 in size at most, so sixteen full-scale frames times them stay under 2^31 at every step: neither the 48 bits the unit sums in nor any holding to 32 is met, whichever the unit does. The blend of the two rows and the hold to 30 bits are done as before, on those sums.
- A run of frames is made in one call: as many as end with nothing to look after (the step does not reach the wall, nor the place a fade out before a cut begins; no fade is on). A frame of a fade and the one at a wall are made one at a time by the same routine, and what follows them is the code it was.
- Two channels share the table's numbers: four products a frame of the sixteen, each fetching what the next needs (the next frame of a side into the other of two registers, the next number of a row), and two clears. Sixteen times over without a loop.
- The table is 33 rows of 16 longs at `0x44061000` (2,112 bytes, past the eight voices' frames around their slots' ends), made at every start from the same 17 rows in the image, by the same mark. The rows of words at `0x44060004` are not made or read by this build.
- Room: the two-channel sum and the routine's ends are in Twinshot's update and render (`0x400097dc`, 790 of 830 bytes: the first use of that room); the one-channel sum is in the sampler's second run, where the old routine was (1,178 of 1,292 there now).

CONFIRMED in emulation (`tests/test_quick.py`, 342):
- What comes out is what came out, bit for bit: the engine against the reference model at seven pitches for sixteen kinds of note, with STRT and LEN moving, and in slots of 3 to 300 frames three octaves down; the routine alone against the old arithmetic at all 4,096 fractions of a frame, both ways through a slot, at both stops, on both of the bench's models of the unit; and next to the pitch image's engine with eight tracks at once, stock machines between them.
- It leaves the unit as it finds it. The mode word is saved, set to the voice loop's (`0xa0`) and put back, as stock's routine at `0x40001914` does. At every one of its calls in the real interrupt all four accumulators hold 0, and it leaves them at 0. Every form of instruction in it is one stock's code has (a product of two registers with or without a fetch, the place by register, by register and step, or by a number past a register, into a data or an address register that may be one of the two multiplied; the clearing read; the mode word).
- Cost, instructions an interrupt, against 117,348:

| Eight sampler tracks | first build | second |
|---|---|---|
| stereo, at their own pitch | 94,251 | 84,579 |
| stereo, one pitched | 67,964 | 62,108 |
| stereo, four pitched | 107,544 | 85,492 |
| stereo, all eight pitched | 160,319 (1.37) | **116,679 (0.99)** |
| mono, all eight pitched | 87,732 | 67,975 |
| mono, at their own pitch | 52,906 | 43,861 |

  A pitched stereo frame is about 150 instructions where it was 321. A low note within reach of its slot's end costs what the rest of it does.
- The 21 images before it build to the same hashes. The stereo image is `99e56954...`.

Not taken:
- The unit's whole-number mode would save a frame's `swap` (32 instructions a stereo frame). Stock never uses it and the bench's model was made for stock's code: not on a guess.
- A table with a row for every fraction, and no blend, halves the products: 131 KB or more, read all over. What that costs in the cache the bench cannot say.
- The on request. A machine costs time only while it plays, so giving one up buys room and no time, and this fits in Twinshot's. Kept for when room is short (time stretch).

NOT CONFIRMED: time. The counts say eight pitched stereo tracks now ask what stock's heaviest machine asks on all eight, and less of the costly kind of instruction than before (the old sum's 32 multiplies a channel a frame are gone). Whether the unit carries it is the unit's to say. And between 94,251 and 160,319 there is still no number for where it gives way.

## The audio CPU's two timers, and its load measured on the unit: the time image (2026-10-11, sections 3 and 7 of OS 1.42)

On request. The bench cannot: it counts instructions and has no clock (the first build was clean in emulation at 1.37 of stock's heaviest interrupt). So the unit is asked.

CONFIRMED by reading (section 7; nothing here was run on a unit):
- **The first timer (`0xfc070000`) is the audio interrupt and does not count.** Its mode word is set to `0x00c1` at `0x40000e40`: capture on either edge, clock stopped. The interrupt's first act is to clear its capture flag (`0x40000960`, a 1 to `0xfc070003`). So the main CPU's line makes the interrupt through this timer's capture, and its count and capture registers say nothing of time.
- **The second timer (`0xfc074000`) counts and nothing reads it.** At `0x40000de2`: its clock is switched on (29 to the chip's switch register `0xfc04002d`), then its mode word is set to 3, which is count the bus clock undivided, run free, no interrupt, no capture. No other instruction of section 7 names an address of it: `fc0740` appears once in the code, in that write. A counter left running: whatever it was for is not in this build.
- Division is something the audio CPU's code already does: stock's own (`0x4000681a` and on) and two of ours since the pitch image (a voice's number from its address).

**The time image** (`make image-time`, `bcd06158...`; `engine/sampler.h`, TIMED; a tool, not one to keep): the stereo image, and the second timer read at two places.
- Audio CPU, 272 bytes in Twinshot's other run (`0x40006764`, its player and filter, 514 bytes): the interrupt's call of the voice loop and its call of the last stage go there first. The count is read at each. Kept in 24 bytes of free memory at `0x44050a00`: this interrupt's count, the longest stretch between the two readings, the sum of the gaps from one interrupt to the next, and the blocks counted. Every 256 blocks (171 ms) the longest stretch is worked out as hundredths of a block, a block being the 256th part of the gaps' sum, and held with the most of the last 32 to 64 such lots (5 to 11 seconds). Both are written to the window as text, a letter and three figures in a long: `0x5b4` and `0x5b8`, after the long that says which tracks have a right channel.
- Main CPU, 106 bytes in the page's runs: the sampling page writes those two longs where a value goes in the second and third places of its lower row, with any byte that is not a letter or a figure made one.
- **C** is the longest the interrupt worked in the last 171 ms, **P** the most C has been in the last 5 to 11 seconds. 100 is all of a block: the next interrupt starts late. Not in the stretch: about 650 instructions before the voice loop's call (the knobs the main CPU sent are taken in) and about 30 after the last stage (the tracks are sent), under 1 in 100 of a block at full load.
- The sound engine is the stereo image's byte for byte; the image differs from it in that run, two calls of the interrupt's, and the page's code. It adds 24 instructions a block.

CONFIRMED in emulation (`tests/test_time.py`, 32), with a count the test supplies in the timer's place: every block is the stereo image's; the two numbers are what they are said to be, from a clean start, with interrupts early and late, with the count going round, and from memory as a start leaves it (the first lots may say up to 999, and P is right within 11 seconds); a timer that does not count says C000 and nothing is divided by nothing; the routine writes its own memory and those two longs; the page writes a letter and three figures whatever the window holds. The other 22 images build to the same hashes.

NOT CONFIRMED:
- That the second timer counts on the unit. Stock sets it going and never looks. If it does not, the page says C000 and nothing else is different.
- What the count's unit is. It is not needed: both numbers are one count over another.
- What C reads when the sound breaks up. 100 is where the arithmetic puts it; the first build of the stereo image, which did break up, is the thing to try it on, if that is ever wanted.

## The interrupt made shorter, and a sum of twelve to try: the stereo image, third build (2026-10-11, section 7 of OS 1.42)

The time image's readings on the unit (hardware log): eight stereo samples at their own pitch 72 hundredths of a block, the same pitched 99 and "peaks ovewr a 100 at times", seven SY SWARMs and a sampler 81, so eight SWARMs about 88. The second build matched stock's heaviest by count and is 11 over it in time. The the maintainer's report.

**What the readings say of the bench's counts.** 84,579 instructions read 72; about 106,000 (seven SWARMs and an idle sampler) read 81; 116,679 read 99 and over. An instruction of ours costs about a sixth more time than one of the SWARM patch's, on the average of an interrupt. The pitched frames themselves (32,100 instructions, 27 points) run at about an instruction a count of what a block has; it is the rest of what is ours that is slower than it counts. From here on a count is a guide and the meter is the measure.

**Looked for and not there:** a setting at which stock's four stages leave a signal as it was, so that a right channel could go round them. At a new project's settings none of the eight tracks comes out of the stages as it went in, on either side, in any block, and moving any one of the 25 knobs of the filter and amp pages does not change that (run in the rig). The stages are half of an interrupt of eight stereo tracks and are not ours to shorten.

**The third build** (`engine/sampler.h`, LEAN; `3a511030...`), which changes no frame:
- **A voice's level and gain in one pass.** The sampler sent each channel through two of stock's routines: the amp's (`0x400045a0`: a frame times the level, read back, the level moved a step) and Twinshot's mixer of two layers (`0x400049f4`: times the gain, plus the second layer, read back, the gains moved a step), with the second layer at nothing. Four passes over a stereo note's block, each with its own call. `voice_out` (`engine/stub.S`) does both channels in one: the two products a frame of a channel are stock's, in stock's order, read back between as stock reads them, and the two ramps are made once. Where Twinshot's second layer is not at nothing (what another machine left, before a voice's first note) stock's two routines are called as before. 280 bytes in Twinshot's player and filter (`0x40006764`): both of Twinshot's runs are used now.
- Read on the way: stock's amp does not clear its accumulator before its first product. It counts on the one before having been read with the clearing read, as every one of stock's is; ours are too.
- **The right channels' copies**: to the window sixteen longs at a go, the exchange with the copy of stock's filter memory six longs a turn, the two copies of state four.
- Instructions an interrupt, eight sampler tracks: stereo at their own pitch 76,674 (84,579), stereo pitched 108,774 (116,679), mono pitched 66,423 (67,975). 7,905 off a stereo interrupt, pitched or not: about 7 of the meter's points, if they cost what the rest of ours costs.

**The sum of twelve** (TWELVE; built only as the time12 image, `423b867b...`): a frame between two summed from twelve frames, not sixteen, the outer two at each end left out and the table a sinc of twelve under the same window. 6,144 fewer instructions with eight pitched stereo tracks (102,615): about 5 more points. It is another sound, a little. A tone two octaves down, everything else against it, the engine's own output:

| Tone | sixteen | twelve | the line the pitch image replaced |
|---|---|---|---|
| 1 kHz | 88.6 dB | 87.5 | 63.9 |
| 3 kHz | 84.7 | 83.2 | 44.7 |
| 6 kHz | 86.1 | 83.5 | 32.1 |
| 10 kHz | 80.2 | 79.5 | 22.2 |
| 14 kHz | 76.1 | 71.3 | 14.8 |

It is the maintainer's to choose, by ear and by the meter: the two files are the same but for that.

CONFIRMED in emulation (`tests/test_lean.py`, 173; and `tests/test_quick.py`, `tests/test_stereo.py`, `tests/test_time.py` on the new build): the pass of the level and the gain against stock's two routines themselves, on 480 voices of anything and on steady ones, both channels, the voice left as they leave it and the accumulators too; the three copies against what they have to move; the whole engine against the reference model and the pitch image's engine as before; the engine of twelve against the model with the table of twelve; the figures above. The 21 images before the stereo image build to the same hashes; the time image is `5edff07d...` with the third build's engine.

NOT CONFIRMED: what either reads on the unit. By the counts, sixteen should read about 92 pitched and twelve about 87, and 65 at a sample's own pitch. The counts were a sixth out before.

Not done, and what each would be worth by count: the run of frames without its asking after its stretch at every frame (a division a run in its place, about 1 point); a pass that leaves the right channel out above some load, which would trade stereo for time on the newest voice and needs the maintainer's word.

## A fade and a note's start: the blocks that stood out (the third build's second step, 2026-10-11, section 7 of OS 1.42)

On request (hardware log). The meter's P holds the most of ten seconds, so one heavy block shows for that long.

**The bench had the answer and had not been asked.** Every count so far was of a steady block. Counted a block at a time, eight stereo tracks pitched and trigged together (the first step of this build, sixteen frames; instructions an interrupt):

| Block | first step | second step |
|---|---|---|
| a steady one | 108,700 | 108,700 |
| the one a trig is in | 112,000 | 112,000 |
| the one the notes start in | 123,500 | 114,000 |
| the same, with a cut start (a fade in begins) | 129,800, then 115,200 | 120,200, then 115,200 |
| a block wholly inside a fade (second build's way) | 170,000 | 119,400 |
| a voice's very first note after a start | 132,400 | 122,800 |

- **Every frame of a fade was made alone**: the second build's run of frames stopped for a fade, and a frame made alone cost 390 instructions where one in a run costs 146. A cut start, a cut end and a loop's seam are all fades, 64 and 128 frames long. Now a fade is a run too: the frames are made at full level in one call and taken through the gain after (`fade_run`, `engine/stub.S`), up to the frame whose step reaches the wall and no further than a fade in lasts. A frame of a fade is about 170.
- **A note's start wrote out the 45 frames a side around its slot's ends a word at a time, asking of each where it lay**: 1,300 instructions a stereo note. The same words in stretches (`hq_pads`, now in `engine/stub.S`): about 110.
- Left as it is: stock's own work in the block of a trig and the next (about 3,300 and 4,000 for eight stereo tracks, its stages starting their envelopes for both channels), and a voice's first note after a start, when stock resets the voice and the table is made again: 8,900 more, once.
- Room: the time image's routine did not fit beside all this. Its code is in four pieces now, two of them in two of the small runs of unreferenced functions (`0x40004534`, 108 bytes, and `0x40005624`, 118): held reached by nothing (`tests/test_time.py`). The fourth such run (`0x40009f1c`) is named four times in stock and is not used. The stereo image itself does not use the small runs.

CONFIRMED in emulation (`tests/test_lean.py`, 205): the run under a fade against the engine's own two routines a frame at a time; a note's start against the words the pitch image's routine writes, for slots of 1 to 300 frames; the counts above; and the whole engine still bit for bit the reference model with fades of every kind (`tests/test_quick.py`, 342, and `tests/test_lean.py` with the table of twelve). Files: stereo `a81afad2...`, time `37a5061e...`, time12 `bb2c9253...`. The 21 images before the stereo image build to the same hashes.

NOT CONFIRMED: the unit's reading. By count the heaviest block of a pattern is now within 5 in 100 of a steady one where it was 14 (and 56 in a fade): with a steady reading near 90 on the sum of twelve, the peaks should stay under 100.

## A record gain: the gain image (2026-10-12, section 3 of OS 1.42)

The the maintainer's report. The threshold is not in the new order and is not built.

**The gain image** (`make image-gain`, `461e4f4d...`): the stereo image with the sum of twelve frames (which he ran on the unit through two builds: "cpu peak neevr above 85"), and on the main CPU:
- **The feed** (`engine/recfeed.c`). A source is 32 bits a sample and a take 16. Before the 32 are made 16 the sample is multiplied by the recording track's gain: its top 24 bits times a number of 256ths (a table of 25, 0 to 24 dB, `round(256 * 10^(dB/20))`), held to what 32 bits hold. Then the rounding, the dither and the stops, as they were. At 0 dB the sample is not touched and the feed is the stereo image's bit for bit.
- **What it buys**, measured on the feed's own output: a tone 66 dB under full scale recorded as it is and turned up 24 dB afterwards has everything else 20 to 30 dB under it; recorded with 24 dB of gain, 44 to 54. The gain is taken out of the 16 bits a take would have thrown away.
- **The meter** shows the level with the gain on: the largest sample times the gain of the track the page shows, no more than a take holds.
- **The page** (`engine/recpage.c`): the lower row's second place, knob F, reads `0dB`, `+1dB` to `+24dB` with no name under it (the meter's bar is there). A turn is a decibel and it stops at both ends.
- **Where it is kept**: a byte a track in main CPU memory after the meter's four numbers (`0x40088524`; the gain the page shows, for the meter, at `0x40088520`), in the feed's own run, which is loaded with the program: 0 at every start. The page's own, like DEST: not saved with a project, not to be locked to a step.
- Room: the page's three runs and the feed's two were full. The page has a fourth, `0x401bd514..0x401bd66e`, 346 bytes that nothing reaches (`tools/deadcode.py`: named by nothing; no long of stock's names an address in it), 136 used. The multiplication itself is in the run of REC's mark.

CONFIRMED in emulation (`tests/test_gain.py`, 55): the feed against the arithmetic above for every gain, any source, any track, with the first track in record picking its own; at 0 dB against the stereo image's feed; full scale with the most gain stops at the ends; the tone above; the meter's level; the page's place, its knob and its stops, a number a track, the other knobs as they were; section 3 the stereo image's but for the feed and the page. Every image before it builds to the same hash.

NOT CONFIRMED: anything on the unit. How the value reads in its box, and that a turn of knob F on that page reaches us as the other knobs' turns do (it is knob 6 of the same eight).

## A sample is mono or stereo by itself: the mode image (2026-10-12, sections 3 and 7 of OS 1.42)

The maintainer's order of 2026-10-12 had "move the mono/stereo mode knob to the same page", and then: "MODE moves to the sampling page, but check my idea for mono/ stereo in scratch pad". The idea, on request

Checked, and it holds. What made it cheap: the engine already took a stereo sample's right channel from the slot after its left only when that slot was as long, and a note without one already played as one channel at a mono voice's cost, with the main CPU copying it to the right. So "what a sample is" was already read from the slots; MODE only said whether to look. **The mode image** (`make image-mode`, `2871f7f1...`):
- **Audio CPU** (`engine/sampler.c`, AUTO). SMPL always counts the 32 samples, slots 2n and 2n + 1. A sample is stereo when its second slot holds exactly as many frames as its first (it was "at least as many": two samples that share a pair by chance are two samples now). MODE's lowest bit is read where a take starts: with it a take fills both slots; without it the second slot is left with one frame.
- **Why one frame and not none.** A take's slot is written to the drive by the keep's requests, and a slot of no frames is "nothing to keep": the drive would hold on to what it had there, and a stereo take of a bar re-recorded as a mono take of a bar would come back after a restart with the old take's right channel, as long to the frame. One frame is a take like any other to that code, on both CPUs, and is no right channel. Not known: what stock's own code makes of a header that says 0 frames, which is why that was not tried.
- **The feed** (`engine/recfeed.c`): a mono take is the source's two sides added and halved, on both sides of the ring. The gain's number carries a bit above it that says so (`take_gain`), and the sample is fetched in the routine that multiplies: the feed's own runs had 4 bytes left.
- **The page** (`engine/recpage.c`): the lower row's third place, knob G, MONO or STER; the first page's sixth place answers "no record", as the second page's places do, and a turn of that knob is nothing. The bit is the track's alone and is written into every lock of MODE the track has, with REC and SRC. SMPL's text no longer asks for MODE (`engine/knobtext.c`). MODE's descriptor default is 1: a new track's takes are stereo.
- **The peak.** The the maintainer's report. The image's sound engine carries the time image's routine, and the page writes its second long (P and three figures) where a value goes in the lower row's last place.
- **Room.** The code that walked from slot to slot for chained samples, without a use since the page image, is not compiled: `locate`, a branch of `edge`, half of `enter`. And the image holds the table's twelve numbers a row and not its sixteen, the four noughts being read by no sum of twelve. 300 and 136 bytes, which is what the cross image is built in.

CONFIRMED in emulation (`tests/test_mode.py`, 151): every script of STRT and LEN the live image is held to gives the same frames here as on the gain image's engine with MODE saying what the sample is; the engine is the model (`auto=True`) at three pitches; MODE's value changes no frame; the rule of the second slot, to the frame; a stereo take and a mono take on the audio CPU, a step's REC, one kind over the other, and the keep's answers for a mono take's two slots; the feed with the bit is the gain image's bit for bit, without it the half sum, for every kind of source; the page, the knob, the locks, the first page's empty place; SMPL's text; the default; both sections against the images before. Every image before it builds to the same hash.

NOT CONFIRMED: anything on the unit. That a place on the first page with no record behind it draws empty there as the second page's do; that a take of one frame is a sample like another to the drive's own code, to Transfer and at a boot; how STER reads in its box.

What it changes for a project made before: a track on STEREO plays as it did. A track on MONO read SMPL as a slot and reads it as a sample now, and its takes are mono.

## A loop's end blended into its start: the cross image (2026-10-12, section 7 of OS 1.42)

The the maintainer's report

**What there is to blend with.** A blend at a seam needs sound that leads to the place the next pass begins. A loop that keeps its length has only what lies outside it: before its start, or after its end. A loop of the whole sample has neither. (Blending the end into the loop's own start shortens the loop by the blend, and a recorded bar would drift; blending it into the start played early leaves a jump where the early start ends.) So:
- 256 frames before the start: the pass's last 256 go down as those come up, a 256th a frame, and the pass ends on the frame the next begins after.
- Else 256 frames after the end: the seam is 256 frames later on both sides. The wall is the end plus 256, the next pass begins 256 in, and the blend is the same arithmetic.
- Else the dip, as it was.
Backwards the same with the ends changed. The loop is as long as it was in every case.

**Why not two sums a frame.** A blend made while it plays is a second sum of twelve a frame a channel for its length, and loops started together are in their seams together: the blocks of a seam would cost twice their pitched frames, where the unit's meter has eight pitched stereo tracks at 85 of 100. So the blended frames are made of the sample's own frames, before pitch: 352 a voice (80 of the pass, 256 blended, 16 of what the seam leads to), 16 bits, in free memory at `0x44062000 + 0x800 * voice`, behind four longs that say which seam they are for. Eight frames a block are written (`bake`, `engine/stub.S`), 44 blocks in all, and none in a block a fade is on in: the block notes start in and the blocks of a fade in are the heaviest there are.

**Playing them.** A pass with its blend all written, no fade on, and still short of the blend (`xuse` 1) has no dip before its wall, and a run of frames stops short of the blend. The frame that reaches it is always one made by itself, and before it the note is pointed at the blend's frames in the sample's place: its place and its wall counted from the first of them, and its count of frames set past any slot's, so that the routine that makes a sum never takes one for a frame near a slot's end (`into`). It stays so to the wrap (`xuse` 2), which is no cut: no fade after. Meanwhile the knobs are not looked at (`live`), so the blend a pass is in cannot be another seam's.
- The 80 frames before the blend: 8 for the sums, and 72 because a frame's step can be up to 64 frames, and with the seam 256 later a pass must be in its blend before it can step over its old end.
- **Free memory is not believed.** What says a blend is written is a count in the voice's own state, which a note's start sets to 0.

**Three things the tests found**, each wrong in the model too, so that engine and model agreed:
- A pass that came to its blend with the last frame of a block lost its turn: "may go in" asked at each block's start whether the pass was short of the blend, and it no longer was. It asks that only when the turn is first given.
- A blend whose seam had moved while a fade was on stayed "all written" for the blocks of that fade, and a pass could have gone into it. No turn is given while a fade is on.
- (Layout.) The same C in another order is other bytes: rewording `edge` and `play` for the new build changed thirteen older images. The old text stays as it was, and the new is under the new image's name.

What it costs, instructions an interrupt, eight pitched stereo loops cut out of their samples (`docs/SAMPLER.md`, "What it costs"): a steady block 600 more than the mode image's, a block the blend is written in 2,100 over that for 44 blocks, a block in a seam 3,800 over steady where a block of the dip was 9,400 over, the block the notes start in 300 more. The seam is worked out again only when the pass or the knobs have moved.

Room: 600 bytes, in the last small run nothing had taken (`0x40004608`, 108 bytes: held reached by nothing, and never run or read while every machine plays) and in what the mode image freed. 318 bytes are left on the audio CPU, the largest piece 44.

CONFIRMED in emulation (`tests/test_cross.py`, 137): the engine is the model (`xfade=True`) for 14 kinds of loop at five pitches, with the knobs moving through every script the live image is held to, and with them walking all the while; where there is nothing to blend with, and for a one-shot and a ping-pong, it is the mode image's engine frame for frame; a steady level does not move through a seam (the dip took it to a 128th); a ramp's jump of 10,700 is 36 a frame for 256 frames; outside the frames at a seam a loop is the frames it was for eight passes, so it is as long as it was; how the blend is written and what it holds; a seam reached before it is written; a pass in its blend and the knobs; what is written and where; the costs; the layout. Every image before the mode image builds to the same hash.

NOT CONFIRMED: how it sounds, and time on the unit. The count says a seam is lighter than it was and a steady block half a hundredth heavier; the meter in the page's last box is there to read it.

## Mono samples in single slots at the back: the pack image (2026-10-12, sections 3 and 7 of OS 1.42)

On request. Asked what back to front is, and what should happen to the numbers after a sample that changes kind: "I was thinking that the stereo samples would fill up the first part of the bank from 1 to whatever is available, and the mono samples would just get packed in the back of the bank. That way, if I wanted to do 80/20 stereo versus mono samples, I could do it that much or do 50/50. I don't need to have a set amount".

**What says which kind a place is.** Two stacks that grow towards each other answer the second question by themselves: nothing in one moves when the other grows. What is left is how the unit knows where one ends and the other begins, and length cannot say it (two mono takes of a bar, side by side, are as long as each other to the frame, and so is a stereo pair). Three ways were looked at:
- the border found from what the slots hold (the run of filled pairs from the front, the run of filled slots from the back): wrong as soon as the bank is full, or has a hole;
- the names on the drive (`KICK L` and `KICK R`): main CPU work, a table for the audio CPU, and a take has no name until it is kept;
- **the knob's number**: SMPL has 64 values each way (`(s8)value - 64`, below nothing for reverse), and the 32 stereo samples use the first 32. The other 32 are given to the slots 33 to 64 by their own number, each a mono sample whatever the slot after it holds. Nothing is found out and nothing is stored; a number never moves; and it is the number Transfer shows for that slot.

Built the third way. So: stereo samples at SMPL 1, 2, 3 and up (slots 1 and 2, 3 and 4, ...), mono ones at 64, 63, 62 and down, and they meet where they meet: 32 and none, 28 and 8, 24 and 16, 16 and 32. **What it does not give:** more than 32 mono samples by their own numbers (slots 1 to 32 are reached as stereo places only, where a lone sample in an odd slot still plays as mono, the mode image's way), and it does not find a free place by itself: a take goes where SMPL or DEST says. Where the two kinds share slots the knob has numbers that mean little: with 20 stereo samples in slots 1 to 40, SMPL 33 to 40 are those samples' halves alone, and with mono samples in slots 41 to 64, SMPL 21 to 32 are two of those at a time.

**The audio CPU** (`engine/sampler.c` and `engine/stub.S`, built with PACK):
- A note's start: a value under 32 is doubled as before; one from 32 on is the slot. Which it was is kept in the voice's `stereo` byte (unused since the mode image), and where a note's slot is looked up the right channel is sought only with it set. 28 bytes and 14 instructions a note's start; 6 bytes where the slot is looked up.
- A take: DEST may name any of the 64 places (`dest < 64`, where it was `< 32`). A single slot's take is marked in `link` (0x80: 0 and 1 are the mode image's mono and stereo). Its frames are half of the ring's two sides added (so MODE plays no part: with it on MONO the feed has already made both sides that, and half of twice a number is the number), written to its own buffer alone; the next slot's buffer, its line of the table and its mark are not written, and for slot 64 there is no next slot to write.
- **The routine a take is made by is written by hand here** (`rec_step`, 208 bytes). The compiler's, with a single slot's take added, was 280 to 288 bytes whichever way it was put (it ran out of registers), and the run holds 226. It does what the C does for the images before, and is held to that block for block (below).
- The time image's small hook moves from the run a note starts in to the last 28 free bytes of the run its text is in. Nothing else moves, and no new run is used. **300 bytes are left, in 18 pieces, the largest 44.**

**The main CPU:** DEST on the sampling page goes to 64 (`engine/recpage.c`, one number), and SMPL past 32 reads the slot's own name, whole, where it read NO SAMPLE (`engine/knobtext.c`: the value handed to stock's routine is the one that stands for that slot). The feed is the mode image's. A kept take is still named by the pair its slot is in (`TAKE 32 R` for slot 64): `engine/keeptakes.c` is not changed, and the name is what SMPL 64 reads.

`make samples PACK=1` lays a set out for it (`tools/split_sample.py`): stereo files from slot 1 up, mono files from slot 64 down, and a plain refusal if they meet or if there are more than 32 mono ones.

What it costs: a steady block is the cross image's to the instruction (103,367 with eight pitched stereo loops); the block eight notes start in is 112 more (113,852).

CONFIRMED in emulation (`tests/test_pack.py`, 131): the 32 stereo places play the cross image's frames through every script the live image is held to and every kind of loop the crossfade is held to; a single slot plays the frames the cross image plays of the same sample alone in a stereo place, with nothing, something longer, or something exactly as long in the slot after it, and is the model (`pack=True`); with all 64 slots holding samples of one length every number of the knob, on both halves, points at its own slots and no others; a single slot costs a mono voice's work. A take in a single slot is half of the two sides and leaves the slots either side, kept samples with marked buffers, exactly as they were, and the memory past the last buffer; a take in a stereo place is what MODE says, in the back half's slots too; two single takes of one length side by side play as two mono samples. **The hand-written routine against the cross image's**, through a script of 36 blocks that goes through a stalled feed, a feed three and eight blocks ahead, a ring overrun (the take ends, nothing skipped), a buffer that fills, a note let go and a trig over a running take: the whole table, every mark and the voice's count after every block, and the frames at both ends of both buffers, are the same; and a single slot's take through the same script is the stereo take's line of the table and count after every block, with half of its two buffers' frames added. The page's DEST and the box, SMPL's text for all 64 numbers on both halves, and both programs differing from the cross image's only in our own runs. The 27 images before build to the same hashes.

NOT CONFIRMED: anything on the unit. Whether the unit's own code that loads, sends and keeps samples cares that a slot of the back half holds a sample whose pair-mate is another sample: it should not (slots were single things to stock all along, and on the big image samples played in mono by their own slot on the unit, slots 63 and 64 included, 2026-10-07), and it is not tried on this image.

## SMPL stops only on real samples: the stops image (2026-10-12, sections 3 and 7 of OS 1.42)

On request. Of three ways put to him he chose the knob that skips, with one free spot of each kind. **The stops image** (`make image-stops`, `188cecb8...`).

**The rule**, slots counted from 1 as Transfer counts them (stereo place n is slots 2n - 1 and 2n; single slot k, 33 to 64, is slot k). Turning SMPL on the first page stops at, and only at:
- a stereo place that holds a sample: its first slot is not empty, and for places 17 to 32, whose slots can be single ones, not odd;
- the lowest stereo place that is free: both its slots empty;
- a single slot that holds a mono sample: its length is odd and more than one frame;
- the highest single slot that is free: empty, and the first slot of its pair holds no even sample.
Sorted by number, so a free spot in a hole is met where the hole is. The reversed half of the knob is the same list mirrored. A click is a stop; a value that is no stop goes to the nearest one in the turned direction; at the last stop the knob stays. Nothing else changes: a number keeps its meaning, the sound engine plays whatever number it is given, DEST reaches all 64.

**What says which kind a slot holds: its length.** 0 empty, odd a single slot's mono sample, even its stereo place's. Checked, and it holds everywhere our own code and stock's that was run carry a length:
- a single slot's take is a frame short of its whole blocks from its first block on (`rec_step`, `engine/stub.S`: the table's line alone; the voice's own count is as it was), so 31, 63, 95 frames and on. A mono take in a stereo place leaves **two** frames in its second slot, not one;
- the keep's requests hand a take over by the table's length, a long cut where it ends (`keep_step`), and the main CPU writes that length in the header (`engine/keeptakes.c`, not changed);
- at a start the pool is the header's frames and that many frames a slot (`engine/poolhalves.c`), and stock's routine that makes the audio CPU's table of it walks odd counts right (`0x40000d06`, run);
- a slot loaded while the unit runs is the header's frames (`engine/keeptakes.c`, `bytes / 2` of twice the frames);
- Transfer sends `floor(min(seconds, 5.0) x 48000 + 0.5)` frames (the entry of 2026-10-07, read in its program and not run): a file of n frames at 48 kHz is n frames. **Not shown on the unit.**
- `make samples PACK=1` makes a mono file odd and a stereo one even on both sides, the last frame left out where it has to be (`tools/split_sample.py`, `kinded`).

**One departure from the rule as it was put: a slot of exactly one frame is no mono sample.** The mode and cross images left one frame in a mono take's second slot, and the cross image is on the unit with such a take kept through a power cycle (hardware log). In slots 34 to 64 that frame would be a stop of its own. The audio CPU's two bits tell one frame from three, so the page takes one frame for that mark: no sample, and not free.

**The audio CPU says, the main CPU reads.** Only the audio CPU's table knows a take that is not kept yet.
- Two bits a slot: the length's lowest bit, then whether anything is left without it (0 empty, 1 even, 2 one frame, 3 odd and more). Sixteen slots a long, the first slot's bits the highest. Four longs, one a block by a count of blocks in free memory that may be any number at a start (`0x44050a18`): every slot is said again every four blocks.
- **Where.** The window has no 16 free bytes in one piece. It has 8 twice, with memory in use on the unit on both sides of each: `0x808` and `0x80c`, between the recorder's count and random number and its ring, and `0xe38` and `0xe3c`, between the sampling page's box and the right channels' second stretch. The mark is at `0x5bc`, between the time image's two longs and the right channels' first stretch. A search of both stock programs for the five addresses found nothing (absolute short operands in section 7's code, the longs themselves, the longs with `0x10000000` in section 3): a search for names, not for every way an address can be reached. What it rests on is the survey of the window made for the stereo image: stock clears and uses its first `0x5b0` bytes, and the boot's 2 KB at `0x800`.
- **The mark.** Each block the audio CPU reads it, moves it up a byte and puts `0xa5` under it: it reads `0xa5a5a5a5` when four blocks have gone by since it last did not, and by then all four longs are written, whatever the count began at. What it cannot tell is a mark that read right before it started: the main CPU sets the long to 0 every block the audio CPU is down, where it already clears the right channels' long (`engine/rightfill.c`), so a start, and the restart after samples are sent to the unit, begin from 0. The mark is outside the 2 KB the boot's loader sends the pool through, which the main CPU must not write to meanwhile; the four longs are inside it and are only ever written by the audio CPU's interrupt. That interrupt is not running while a pool is sent: stock's start names its routine once (`0x40001064`), in its last step, after the loop that takes the chunks (`0x40000f8e..0x40000fd4`), and then stays in a loop of one instruction, so a pool sent again is a start again (read in the listing, and held by a test).
- **The routine** (`stops_say`, `engine/stub.S`): 72 bytes in the ends of two runs, reached by the hook's last instruction, which was its return. Seven instructions a slot: the length's lowest bit out by a shift and in by an add with carry, the rest out by a negate and in the same way, and a bit set at the start falls out of the long's top after the sixteenth slot. One form of instruction in it the audio program has nowhere of its own: a word fetched by the program counter and an index (`%pc@(d8,%d0:l:2)`). Stock's main program, the same family of chip, runs that form in its switch tables.
- **The page** (`engine/recpage.c`, STOPS; two more runs of code nothing reaches, `0x401bc860` and `0x40088a80`, 602 and 680 bytes: no one run left holds its 930). A turn's two entries are the image's own and hand everything but SMPL on a sampler's first page to the routines that were, which are the pack image's to the byte. SMPL's change goes the way MODE's bits always went: stock's method for the track's value and stock's pop-up, or with steps held stock's methods for one step's lock, made at the track's value the first time and moved after, as stock's own routine for a held step has it.
- **While the mark does not read right, or stock's word says the audio CPU is down, or nothing in the bank is a stop, the turn is stock's**, as it came.

**Two things stock's knob routine does with a turn, read for this and kept** (`0x4003b870`):
- A knob pushed in while it is turned: the event's byte at + 20 picks the second of two numbers of the record's template (`0x400f6866`: steps times the first number, or the second), and SMPL's are 1 and 8 (`0x401d6b74`). So pushed in, a click is eight stops.
- Key 1 held (`0x40102f40(1)`, a bit of the key matrix; FUNC by what the routine does with it, not proven): the change is the record's own jump, and SMPL's (`0x4006f8e4`, read and not run) takes a value to 127 less it, forward to reversed or back. That turn is left to stock: the mirror of a stop is a stop.

What it costs: 128 instructions a block on the audio CPU, every block. Eight pitched stereo loops: a steady block 103,495 where the pack image's is 103,367, the block eight notes start in 113,980 where it is 113,852.

Room: 82 bytes on the audio CPU (72 the routine, 2 the hook's end, 8 the take's). **218 bytes are left, in 17 pieces, the largest 30.**

CONFIRMED in emulation (`tests/test_stops.py`, 116; `tests/test_split.py`, 18):
- the four longs and the mark from a start with anything in the count, the longs and the mark: one more long right a block, the mark right after the fourth and not before; through a pool with odd lengths as stock's routine builds the table; through takes of each kind while they run; through a slot loaded and a slot emptied by the keep's requests. Only those five longs of the window and the count are written beyond what the pack image writes;
- the take's routine against the pack image's through every way a take goes and ends: a stereo take the same block for block; a mono take the same but for two frames in its second slot; a single slot's take the same but for a line of the table one frame less, odd whenever there is anything. It plays as the pack image's take told it is a frame shorter, at three pitches; it is handed to the drive at that length; a second slot of two frames is no right channel and is kept as a take;
- the knob against the rule, on stock's own methods for a value and a lock: 17 banks worked by hand (empty, 32 stereo, 20 and 10 with a gap, the stacks touching, a free slot and a free pair between them, holes, old even files at the back, mono takes of this image and of the one before, odd lengths in front), every stop from either end, and 10 banks of every kind of length from every value with turns of 1, 2, 3, several and 200 either way; a held step's lock; a pushed turn; key 1; the mark missing in six ways; the audio CPU down; a bank with no stop; another machine; every other knob of both pages against the pack image's page; which longs are read;
- the two halves against each other: the audio CPU's window handed to the page as it is, for six banks and for takes placed one after another by hand;
- an odd length from the drive's header through this image's pool builder and stock's table builder;
- the main CPU's clearing of the mark; both programs against the pack image's; the image. The 28 images before build to the same hashes.

NOT CONFIRMED, all of it the unit's to say:
- **that a file of an odd number of frames sent with Transfer is a slot of an odd number of frames.** Everything rests on it for samples that are not takes. If the unit or Transfer rounds, mono files at the back read as nothing or as stereo places, and it shows at once: SMPL does not stop on them;
- that the three places in the window are memory both CPUs see (their neighbours on every side are in use on the unit);
- that the main CPU's routine runs while the audio CPU is down (the stereo image leans on the same);
- that key 1 is FUNC, and what a pushed turn feels like at eight stops;
- that the first page draws SMPL's new value and name after our change as it does after stock's (MODE's knob went this way on the first page from the page image to the gain image, on the unit);
- time: 128 instructions is a tenth of a hundredth of a block by count.

**What is on the drive from before.** A stereo sample in slots 33 to 64 whose files are an odd number of frames reads as two mono samples here, and a mono file of an even number at the back as nothing or as a stereo place: send them again from `make samples PACK=1`. Takes are whole blocks, so even: a stereo or mono take of any image before reads right. A take made in a single slot on the pack image (which has not been on the unit) is even too, and would have to be recorded again.

## The pattern's mutes as solos: the solo image (2026-10-12, section 3 of OS 1.42)

The maintainer's wish of 2026-10-12, first in his dragged order: the purple pattern mutes as solos. Put to him as six picks, "this is all fine": several solos at once, each purple key adding or removing one; a green mute beats a purple solo; trigs keep firing on a track a solo silences and it can still record, a MIDI track goes quiet; a key purple for a track that is heard and dark for a silenced one; the FX key left alone; a song row's mutes go the same way. He was told that a pattern which already holds purple mutes turns over. **The solo image** (`make image-solo`, `b92d6268...`): the stops image with it. Main CPU only: section 7 is the stops image's byte for byte.

A scout read the program for it first; what follows is what was confirmed again here, in our own tooling (`tools/disasm.py` on the official section 3, a raw search of the section for each address, and the emulator).

**Where the pattern's mutes are.**
- The pattern's own word: its settings + 16, the settings by the pattern's method at + 40. Bits 0..11 the tracks, bit 12 the FX track. `0x40015ec0(pattern, track)` answers a track's bit, 0 for a pattern with no settings (run on a stand-in object). A key press (`0x400372ae`, its pattern half `0x4003731e`) reads the bit there and calls `0x400167a0` with it turned over; the FX key the same at `0x4003ceaa` (read, not run). **That word is not changed by this image, nor anything that reads or writes it but two questions asked for drawing.**
- **Two copies for the engines**, each a word named by absolute address and by nothing else (raw search: six times and four):
  - `0x43bdd828`, the per-block routine's (`0x400a38ce`). Written by the routine `0x400a30b2(word)`, 12 bytes, and by a store at `0x400a3c26` in that routine's own message loop (a kind-2 message's pointer at + 12). Read at `0x400a4224` (the track test), `0x400a4250` (a dropped trig told to the UI), `0x400a3d6a` and `0x400a3d9e` (the FX track, bit 12), and by our mixer link and analog mute.
  - `0x444b5ae0`, the MIDI engine's (its loop `0x4010dbf8`). **New here.** Written by `0x4010d4b8(word)` and a store at `0x4010dc76` (the message's pointer at + 8); read at `0x4010de7e` and `0x4010deb2`. That engine keeps its own copies of the global mutes and solos too (`0x444b62b0`, `0x444b62b4`).
- Who calls the two routines, three places each, every one by a long of the address (raw search: three each): the playing pattern's settings changed (`0x40019bfa`, `0x40019c06`), the playing song row's mutes changed (`0x4002332c`, `0x40023334`, in the row's setter `0x400233aa`), and a load (`0x4008c4be` or `0x4008c4d0`, then `0x4008c4d8`, through a0 and a3). Read, not run. Who sends the kind-2 message was not traced.
- Stock silences nothing by a mute: it drops events. What silences is ours (`engine/mixlink.c`, `engine/amute.c`): global mutes, or with a solo of stock's everything but it, OR the word at `0x43bdd828`.

**What is changed: what the four writers store.** In place of the word, the tracks its solos silence: with any of bits 0..11 set, those twelve turned over; with none, the word as it is. Bit 12 and the three above it are stored as they come and never count. So every reader is as it was and none of our C is touched (no older image's bytes move): a track with its bit set in the pattern is the one heard, a global mute is a word of its own and still mutes, a MIDI track's notes are dropped by stock's test while another track is soloed, the FX track's bit is its mute. The pattern's word stays what the keys set and what is saved.
- The two routines: their first six bytes are a jump to ours (`solo_set`, `solo_set_midi`). Ours begins with stock's own first instruction and uses d0 beyond it. **d0 after the six calls: loaded again or not read**, read at each (`0x40019c00`, `0x40019c0c`; `0x40023332` on to the method call at `0x40023352`; `0x4008c4c0`, `0x4008c4d2`, `0x4008c4da`). The build asserts those bytes.
- The two stores: six bytes each, a call in their place (`solo_msg`, `solo_msg_midi`), d0 alone, a0 as it was. After the first, the next instruction loads d0 (`0x400a3c2c`). After the second the loop goes to `0x4010e528`, calls `0x4010d68e`, which loads d0 before reading it, and back to its top (`0x4010dc52`), which loads d0 on both ways. **d1 is not used at either**, so it did not have to be shown dead.
- No branch and no address goes inside any of the six-byte places, nor into the rest of the two routines (the whole listing searched for each address as an operand, the section for each as a long; `tests/test_solo.py` does the same over the routines around them).

**The keys.** `0x400375dc` colours the twelve track keys, a track a pass (the track in d2). In the pattern mode it asks `0x40015ec0` at `0x400376c2`, or for a song row takes the row's word (`0x400232a0`) and shifts the track's bit out at `0x400376a8`; both go on at `0x400376cc` with the bit in d0: set, colour 2; clear, 28 (26 with a flag), where the global mode has 11 (9). **Both are given "is this track silenced by a solo" in the bit's place**: the call's operand (`solo_key`, which asks for the settings as stock's routine does and answers 0 with none), and the three instructions of the shift, six bytes, a call (`solo_key_row`). d1 is loaded right after both. So a key is lit for a track that is heard: all twelve with no solo, the soloed ones alone with one. The song mode keys were one small site, and are done.
- **One more question, the same one:** `0x4003737a(view, track)`, called once, by a draw (`0x4003cc7e`, a loop over the tracks that draws by its answer and by the prepared keys' word at view + 136). For a pattern it ends in a jump to `0x40015ec0` with (pattern, track) left on the stack (`0x400373fe`): that operand goes to `solo_key`, so what is drawn there agrees with the keys. **For a song row it calls the row's own bit (`0x4002335e`) and is left as it was**: a routine of its own, about 24 bytes, not built. What that draw is on the screen (the scout took it for the PREP MUTES boxes) was not traced.
- The FX key's colour, the trig flashes (`0x400371f0`) and the pop-up's text are stock's.

**Where the code is.** `engine/solo.S`, 94 bytes, in a run nothing reaches: `0x400a2928..0x400a29ce`, 166 bytes, named by nothing (`python -m tools.deadcode 3`), after a return and ending on one, no branch into it from outside (listing). 72 bytes of it are left. Not the scout's 76 to 90: the key routine asks for the settings itself, since stock's word routine (`0x40015e8e`) answers `0xff` for a pattern with none, which would read as eight solos.

CONFIRMED in emulation (`tests/test_solo.py`, 80), all from the built image:
- stock's two routines, called as stock calls them, for every word from 0 to `0x1fff` and eight above: each stores what the rule says in its own copy and leaves the other; d1..d7, a1..a6 and the stack as they were; the long's upper half is not read;
- the two stores, run from stock's instructions that take the pointer out of the message to the ones after: the same, for 229 words; a message with no pointer stores nothing;
- stock's track test in the per-block routine's loop with the word as stored: a MIDI track's event kept with no solo, with its own, with all twelve and with the FX track's mute alone, dropped with another's (and the UI told by the pattern's), dropped by a global mute though soloed; a track that makes sound keeps its events whatever is soloed;
- the MIDI engine's own test, from `0x4010de58`, by its copy: the same, next to the stops image's, where the word is a mute;
- our analog mute and mixer link (`tests/test_mainpatch.py`'s rig, the word put through stock's routine first): the mixer shown volume 0 and the analog voices' level words 0 for exactly the tracks not soloed, each of the twelve alone, nine mixes of several solos and global mutes, nothing with none or with the FX track's bit alone;
- the keys: `solo_key` for thirteen tracks and thirteen words next to stock's routine asked of a pattern that holds what the solos silence, and of a pattern with no settings; stock's colouring from the call to the colour it settles on, 28 heard and 2 silenced, from a pattern and from a song row's word, next to the stops image's given the silenced word; the draw's jump;
- the main program against the stops image's: the seven places and the run, every symbol where it was, the readers and our two mute routines to the byte; section 7 the stops image's; the 29 images before build to the same hashes.

READ, NOT RUN: the key press, the listener, the row's setter, the load, the whole of the colouring routine before its question (which mode asks what), the draw.

NOT CONFIRMED, the unit's to say:
- **that a purple key reaches the sound at once on the playing pattern**, and that a pattern change, a project's load and song mode bring the word through one of the four places (nothing else names either copy by address; a copy made some other way would be a mute as before);
- what the keys show: that mode 1 is the purple one and 28 its colour is taken from the pairing (the pop-up reads "Pattern mutes" there), the colours were never seen;
- what the draw shows, and PREP MUTES: a prepared key goes by the same answer (3 or 31);
- MIDI: a purple key still sends stock's pattern mute message, so a soloed track goes out as muted; a mute message coming in sets a solo;
- eleven tracks fading within one block (one mute passed on the unit);
- **projects from before: a pattern that holds purple mutes plays the other way round**, its muted tracks the only ones heard.

## Takes written with a whole pattern's save: the ptn image (2026-10-12, section 3 of OS 1.42)

The maintainer's wish, on his dragged order: takes written when a pattern or the project is saved, in the SAVE box's place. A project's save has written them since the keep image. Put to him as five questions, his answers of 2026-10-12: "the save project for sving samples wasnt broken you just misunderstood me before"; **"only SAVE TO PROJ in the menu"** (not the main screen's save to the temp area); **"only whole pattern. for this"** (not KIT DATA, not SEQUENCE DATA); the takes written behind the pop-up for a few seconds while the unit plays on: "yea fine"; and **"no word just have it save with the pattern nd it doesnt have to show anytign if it works"**. The main session's reading of the last, not the maintainer's words: FAIL may show when a write failed, and only then.

A scout read the program for it first; what follows is what was confirmed again here, in our own tooling (`tools/disasm.py` on the official section 3, a raw search of the section for each address, and the emulator).

**Stock has one pattern save.** `0x4001a8d2(manager, to the temp area, pattern, sequence, kit)`, to `0x4001aaaa`; to the temp area, sequence and kit are each read as a byte. Run in emulation as it is, with the routines under it played:
- to a project (second argument 0) it asks the project's number (`0x40018c2c(manager)`, -1 for a project never saved: "N/A: Unsaved Project"), whether it is write-protected (`0x40110584`: "N/A: Write-protected") and `0x4011067e`, which has to answer 13 ("Prj must be re-saved!"); to the temp area it asks none of the three;
- then the sequence (`0x4001a36a(manager, to the temp area, pattern)`) and the kit (`0x4001a458`, the same three), each if asked for, **to the project and then again to the temp area**; one that answers 0: "Save Error";
- its message when it went well: "Ptn saved to ", "Seq. saved to " or "Kit saved to ", and "Project" or "Temp Area";
- **its answer is a byte**: `moveq #1,%d0` at `0x4001aa90`, and for every failure `clrb %d0` at `0x4001a9e6` right after the call that shows the message, so the rest of the long is what that call left. Run: the answer was `0xdeadbe00` with the message routine played to leave `0xdeadbeef`.

**Five calls, all `jsr` of the long, and nothing else in the program names it** (raw search: five):

| Call | In | Given | What |
|---|---|---|---|
| `0x400341dc` | the main screen's key routine (`0x40033ee0`) | (view + 152, 1, n, 1, 1) | the save to the temp area. Taken as FUNC+YES; the key codes were not traced. **Left as it is** |
| `0x40182754` | `0x40182728`, a callback (named once, at `0x401835f4`) | (manager, 0, n, 1, 1) | after "SAVE PATTERN TO / PROJECT? CONFIRM Y/N"; nothing on a no (`tstb %sp@(15)`). **Ours** |
| `0x401826c0` | `0x40182632`, called by the callback `0x401826da` (named once, at `0x4018368c`) | (manager, 0, n, 1, 1) | after a naming screen: it names the pattern (`0x40015d04`) and the kit (`0x4000ee62`) with the text it is handed, then saves. **Ours** |
| `0x40182794` | `0x4018276a`, a callback (`0x40182aea`) | (manager, 0, n, 0, 1) | KIT DATA. **Left** |
| `0x401827d4` | `0x401827aa`, a callback (`0x4018340c`) | (manager, 0, n, 1, 0) | SEQUENCE DATA. **Left** |

Each callback asks `0x4016eb0a` and `0x400c2154` for the pattern's number and `0x4016e9c8` for the manager, and ends in `0x4004a4c6`. All four ran in emulation as they are, with those played. `0x40182632` is also called from `0x40182712`, which nothing names.

**When stock takes the third: a pattern with no name, in a project that has a place on the drive.** The menu's WHOLE PATTERN is `0x401834f8` (its entry's text routine `0x40180ad2` names "WHOLE PATTERN", its action is the thunk `0x401837c4`, both set at `0x40181d46..0x40181d62`). It asks:
- `0x40015d62(pattern)`: the pattern's settings (its method at + 40) are there and their first bytes, the name, are not the empty string (`0x4025006d`, compared by `0x4016558c`). Run as it is, the compare too: "" 0, "A" 1, no settings 0;
- and if that is 0, `0x40018c4a(manager)`: the project's number is not negative. Run: 0, 5 and 127 answer 1, -1 answers 0.

No name and a number: the naming screen (an object of 176 bytes, the title "SAVE PATTERN TO PROJECT?", the text it starts with from `0x40015da2`: the name, or "UNTITLED"), callback `0x401826da`. Otherwise the Y/N, callback `0x40182728`; a pattern with no name in a project never saved gets the Y/N and then stock's "N/A: Unsaved Project". **So both are a whole pattern saved to the project, and both go to ours.** Read, not traced: the naming screen's class, and when it calls its callback (the callback has no test of an answer: taken as on its confirm only).

**What is changed: two operands.** The calls at `0x40182754` and `0x401826c0` name `ptn_keep` (`engine/keeptakes.c`, built with PTN), 48 bytes at `0x40125d02`, the last routine in the keep code's run: stock's routine with the five longs it was given, and when the answer's low byte is set, `save_start()`, the save image's start of the job that writes the takes; stock's answer is handed back. Nothing is written where the pattern is saved: a full stereo take is 3,842 sectors at an audio block each, and that is the task the keys and the screen are served in.
- Neither caller reads the answer (`lea`, a pop and a jump to `0x4004a4c6`; `lea` and a call of it). No branch of the routines around them, and none of the main screen's key routine, lands in a call's pushes or in the call, and no long in the section points there (`tests/test_ptn.py`).
- `save_start()` is as it was: it does nothing while a job of ours is running (the long at `0x401259fa`), so a second pattern saved in that time is saved and starts no second job. A take made after the job passed its slot waits for the next save.
- The job runs on stock's runner of jobs, whose worker is one task, so it cannot run beside a project's save or load. That is the scout's reading of `0x400bdda8` and `0x400bd904`, not run here; on the unit a job of ours has run from a knob's turn since the save image.

**A take that changed while it was written** (its length is not what it was when its last sector has gone): on this image it gets no header, as before, and **the run goes on to the next slot**, where it ended. The run still answers that not every take is on the drive. A project's save goes through the same routine, so it goes on too; nothing else of it changes, and it neither sets nor clears the page's word. On the solo image and before, the text is as it was (`tests/test_ptn.py` runs the solo image's: the run ends).

**The page.** `engine/recpage.c` built with PTN: no routine for a turn of the fifth knob (it answers as an empty place's does, a redraw and 1), no SAVE, BUSY or DONE. Where the box's word went, FAIL is written while the keep code's long reads 3, which is after a job that did not get every take onto the drive (a write that failed, the audio CPU down or not answering, a take that changed) and until a job does. **FAIL costs 74 bytes** (54 the routine, 6 the word, 14 its call in the draw); without it the place is always empty.

**Room.** No new run. The keep code's run (`0x401259fa`, 930 bytes): 824 used, **106 left**. The page's first run 1,488 of 1,522 (18 fewer than the solo image), its third 758 of 918 (56 fewer); the other four as they were, to the byte.

CONFIRMED in emulation (`tests/test_ptn.py`, 53), all from the built image:
- the two calls name ours and the other three stock's routine, and each call's pushes are what the table says;
- ours with stock's routine played: five longs through as they came, the answer through whole, a job for an answer with its low byte set and none for 0, `0x100` and `0xabcdef00`; nothing asked of the audio CPU and nothing written before it answers;
- ours over stock's routine as it is: a whole pattern to the project is the project's number, both halves to the project, both to the temp area, the message, and one job; each of seven failures (no project, write-protected, the wrong answer from `0x4011067e`, each of the four writes) is its message, a byte of 0 and no job;
- the job, through the store's own write: the takes' sectors in the loaded bank and nothing else on the drive, bank A and bank C; a second save before the job has run starts none; one after it starts a job that writes nothing; a take made since is written by the next;
- a write that fails at the first, fourth or ninth sector: 3 in the long, and the next save writes it all;
- a take that grows while its third sector is fetched: no header for it, the three slots after it written and marked, 3 in the long, and the next save writes it at its new length; the same from a project's save;
- a project's save: the takes as before, stock's answer back, the long left at 0, 2 or 3 as it was, no job; a failed one keeps nothing;
- stock's four callbacks as they are: the yes and the naming screen's (the pattern named, the kit named, then the save) start the job, and the job writes the takes; a no does nothing; KIT DATA and SEQUENCE DATA save what stock saves and start nothing; a save to the temp area by stock's routine starts nothing;
- the page next to the solo image's: the fifth place holds nothing with the long at 0, 1 or 2 and FAIL at 3, every other text and the meter's dots the same; knob E five ways from both of a turn's entries changes nothing and stock is not asked; the other knobs turn for turn;
- the main program against the solo image's: the keep run, the page's first and third runs and four operands (the two calls, and the project save's two, whose routine moved four bytes); section 7 the solo image's, which is the stops image's; the 30 images before build to the same hashes.

READ, NOT RUN: the menu's builder, the routine `0x401834f8` beyond its two tests, the naming screen, the main screen's key routine, stock's runner.

NOT CONFIRMED, the unit's to say:
- **that the runner takes a job from the task the menu's callbacks run in.** Stock names its start of a job 43 times, a Y/N callback's among them by the scout's reading; ours has only ever been started from a knob's turn;
- what is on the screen meanwhile: the pop-up is stock's and the job shows nothing, as SAVE's did not;
- how the unit plays while a long take is written behind a pattern that is running (SAVE's job did the same work, from the page);
- a pattern saved twice quickly, and SAVE PROJECT right after a pattern's save: one worker, so one after the other, by reading;
- that the naming screen calls its callback on a confirm only.

## The record feed made cheap: the feed image (2026-10-12, section 3 of OS 1.42)

For the fault in the hardware log, "mono files through Transfer, and the UI drags with REC on": the screen, the lights and the keys lag with REC on, not the sound, not with REC off. **Nothing here shows that this cures it. The main CPU's load has never been measured; the emulator counts instructions, not time.** It is the one thing REC on adds on the main CPU, made a third of what it was, with the take unchanged.

A scout read and counted for it first (stops image, the same feed). What was confirmed again here, in our own tooling:

- **The feed runs in an interrupt.** The one call to the mixer (`0x400a5046`), which goes to `mix_rec`, is inside the routine `0x400a38ce..0x400a5520`: it starts after an `rts`, ends in `rte`, and has no `rts` between (`build/dis/sec3.lst`, `tools/disasm.py`). At `0x400a2f2a` stock stores that address in `0x400002fc` (vector 191) and the byte 5 in `0xfc04c07f`. That the byte is the interrupt's level is the family's register layout from memory, not checked against a manual. So everything of ours behind the mixer call runs above the tasks; which task draws and reads keys was not traced.
- **What a block of a take adds** (both images run in the emulator, `tests/test_feed.py`; the first track records the main mix, noise no gain here clips; instructions more than a block with no take, the page not on show): 3,993 at 0 dB STER, 4,441 at 0 dB MONO, 4,569 at +12 dB STER, 5,017 at +12 dB MONO. The scout's: 3,998, 4,446, 4,595, 5,036. **64 hardware divides a block above 0 dB, none at 0 dB**: counted as they run. 70 word cycles in the window (64 samples, the counter read and written, the dither's long read and written). A block with no take: 421, and 1,041 with the page on show (the scout's 423 and 1,043).
- **A drawing of the sampling page asked which step is held three times**: stock's pattern length is asked for three times a drawing on the ptn image. Ours a drawing, 64 steps and no key held: 4,376 instructions (the scout's 5,280 has stock's rectangle in it).

Not confirmed, the scout's reading only: the window's bus timing and its guess of 8 to 10 percent of a block, that redraw requests coalesce, the save job as a second cause.

**What is built.** `engine/feed.S`, `feed_block`, 564 bytes, in the place of `recfeed.c`'s `feed_block` and `gained` (not built on this image; `mix_rec`, `chan`, `take_gain`, `gain_of` and the meter are the same C):
- no call a sample, and what a take is chosen before the loop: four loops (stereo or mono, with a gain or at 0 dB), a frame a pass;
- a gain's limit, `0x7fffffff / g`, worked out once a block: one divide, none at 0 dB;
- a sample and its dither are added in 32 bits and held to 32 bits (`sats`), and the top half is the word. The older routine added the two halves apart and held the sum to 16 bits after. The same number: the top half never turns two numbers around, so holding before or after is one thing, and the ends of 32 bits have the ends of 16 as their top halves. Stock's mixer holds its own sums this way (`addl`, `satsl` at `0x4008f50c`; 100 `satsl` in section 3), so the unit has the instruction;
- the window is written a word a sample in the same order, the dither's number one long read and one long written: the accesses of the window are the ptn image's, one for one and in order (compared).

| a block of a take adds | ptn | feed |
|---|---|---|
| 0 dB STER | 3,993 | 1,126 |
| 0 dB MONO | 4,441 | 1,285 |
| +12 dB STER | 4,569 and 64 divides | 1,515 and 1 |
| +12 dB MONO | 5,017 and 64 divides | 1,483 and 1 |
| the heaviest found (the last track, +1 dB STER, every sample past the limit below nought) | 4,768 | 1,722 |

The ceiling the test holds: 1,800.

**To the bit.** Both images' feeds run side by side on the same blocks, the window carried from one block to the next, and after every block the whole window, the meter's numbers, the gains, the page object stock's redraw request marks, the answer and the list of window accesses are compared; the take is also compared with the rule worked out in Python. Every gain 0 to 24 dB, STER and MONO, every source, noise at full scale and under it, silence, both ends of 32 bits, samples at a gain's limit and one past it on both sides, the counter through nought; REC off, a step's REC locked on and off, two tracks with REC on, a gain and MODE changed between blocks, the audio CPU down, a bank loading, 600 blocks of the meter. No case differs.

**Where.** A new run, `0x400a8db6..0x400a9038`, 642 bytes (`mm.CAVE_FEED`): `tools/deadcode.py` has it unreached and named by nothing; it starts after an `rts` and ends on one; no line of the listing outside it names an address in it; a raw search of the section for every long that points into it finds one, at the odd address `0x40223e63` in the data after the code, with an odd value: chance. 194 bytes of the analog mute's run and 122 of the feed's first run are room again.

**The page** (`engine/recpage.c`, under FEED): the held step is asked for once a drawing and MODE read once; the drawing is the ptn image's dot for dot and word for word (ten cases of held steps and locks, four tracks). Ours a drawing: 4,376 to 1,861. **And FAIL is gone**, the maintainer the same day: "dont need fail shown id ont think at all". The fifth place is empty whatever a save did; its routine, word and call are not built (the page is 108 bytes shorter in all). The keep code is the ptn image's byte for byte: a save that could not write every take still leaves them for the next save, and its number still says so, to no one.

Main CPU only: section 7 is the ptn image's byte for byte. Section 3 differs from the ptn image's in the feed's three runs and the new one, the page's first three runs, one operand in its sixth (the page's turn is ten bytes down), and the operands of the two calls into the feed's first run (a muted track's trigs, a step's REC: both routines are 116 bytes up). The image: `51e69422...`. The 31 images before build to the same hashes. `tests/test_feed.py`, 167.

**Only the unit can show:** that the drag goes, or gets less. The feed is still 70 word cycles in the window a block by the CPU's own writes, which stall the core and are as they were; if the drag stays, that, the right channels' reads (up to 512 a block with eight stereo tracks, REC or not) and feeding only while a take runs are what is left to look at, and a load readout for the main CPU before guessing again.

## REC's third setting, ONCE: the once image (2026-10-12, section 3 of OS 1.42)

The the maintainer's report `make image-once`, on the feed image. Main CPU only: section 7 is the feed image's byte for byte. **Not on the unit.**

**What it is.** REC on the sampling page reads OFF, ON, ONCE.
- **A step's ONCE** (a trig held, REC turned to ONCE) is a lock on slot 24 at `0x52c0`. The high byte is the mark of a step locked on (`0x52`), so stock plays it, `engine/recword.S` sends it, and the audio CPU and the feed take it, as a step locked on: none of the three is changed. Where the sequencer plays the step, the word in the pattern's table is made `0x6bc0` after the event has its copy: no mark, so the track's own REC decides from then on. That one store is all that makes it once; the pass it is made in records to the track's next event, as a step locked on does, because the lock in force is the event's copy and not the table's. **The main task then takes the spent lock off with stock's routine for a lock removed by hand** (`0x40027fe8`, the one the page calls when REC is turned back), when its next message comes: the step's count of locks, the track's "this slot has a lock" byte and the pattern's listeners go as they do by hand. The trig stays.
- **The track's ONCE** (no trig held) is a byte a track at the start of our new run (`0x40088820`, eight; 0 in the image, so 0 at every start; not saved), with the track's bit of MODE off. The next step the sequencer plays on the track gets (slot 24, `0x5280`) added to its event's locks and the byte is cleared there: it records as a step locked on does, to the track's next event, and REC reads OFF after. A step locked off leaves the byte for the next step; a step locked on or to ONCE uses it up. Nothing of the kit or the pattern is written.
- A step's lock is there only where it differs from the track, as before, but ONCE on a step is always its own lock. A step whose slot holds no mark reads as the track does. A turn goes a setting a click, and a fast one from OFF to ONCE without the bit of MODE ever set.

**Read in the listing (`build/dis/sec3.lst`), and how each was confirmed.**
- **The routine that plays a step: `0x4008b8fa`** (track, the pattern's data, ?, step, a place for the event or 0, ...), the track kept in d4 and the step in d3. Two callers, both by a call relative to the pc (no long of its address in the section): `0x4008cf86` in `0x4008c99c`, with 0 for the event's place, a routine whose address `0x4008c5d8` takes (`0x4008c6de`), and that one is called by the task of entry `0x40082578` (priority 1); and `0x4008c288` in `0x4008c128`, which routines of the UI's classes call (`0x4003f622`, four places; `0x40046b68` through `0x4008c300`) and `0x4010423e` jumps to. Read, not run. **What the first is run in, a task or an interrupt, and who the second is on the panel, were not traced: ours there stores words and bytes and calls nothing but stock's own next routine.** Trig conditions are tested inside it before the event (`0x40118398`), so a step that does not play is not spent.
- With an event (fp), the step's row is 144 bytes a step in 9,287 a track from the data + 15301, and its count of locks (the row's 72nd word) is tested at `0x4008bc36`. Not 0: five arguments pushed, then `movel %fp,%sp@-` and the call of the routine that gathers (`0x4008b8a8`: the event its first argument, the track's table its second, the step its fourth; a lock is a (slot, value) pair of words from event + 20, 8 bytes a lock, the count at + 8), six longs popped at `0x4008bc64`. 0: `clrl %fp@(8)` at `0x4008bc6a`. Both go on at `0x4008bc6e`, which loads d0. **Run here as it is**, `0x4008bc18` to `0x4008bc6e`, with the gathering routine under it and stock's routine that applies an event's locks after it.
- **The main task: entry `0x4000abd6`**, priority 6, 160 KB of stack (made at `0x4000a68a` by `0x40001640`, as the others are). Its loop is at `0x4000b2d2`: `pea 0x405d4a7c ; jsr 0x40001ca0`, then a jump by the message's first byte, 0 to 36, every way back to `0x4000b2d2`. Messages 20 to 23 are handed to a UI object (`0x400e220c`, after a walk of a list and a cast), 34 to `0x40033ab6`, and 6 is a function object to run. **That this is the task a knob's turn is dealt with in is read from that and not shown**: a turn reaches a page through method tables, which the listing does not follow.
- The selected pattern's steps for a track: `0x40019000(manager)` (manager + 13204 + 1,664 a pattern, by `0x400c2154(0x4016eb0a())`) and `0x40015fae(that, track)` (112 bytes a track, one in). `0x40019036`, which the page has used since the reclock image, is those two for the active track; stock calls it with `0x4016e9c8()`'s answer at one place. **Both run here as they are.**

**What is changed: three places of stock's.** The build asserts the bytes at and around each (`tools/build_main.py`, `ONCE_CONTEXT`).
- `0x4008bc5e`, six bytes (`movel %fp,%sp@-` and the call): `jsr once_seq`. Ours pushes the six arguments again, calls stock's routine, then looks at the row. It goes back by a jump with the return address left on the stack, since stock pops six longs and pushed five.
- `0x4008bc6a`, four bytes (`clrl %fp@(8)`): `bsr.w once_none`, which clears the count first. Four bytes is a call within 32 KB: the new run is 13 KB below.
- `0x4000b2d8`, six bytes (the main task's wait): `jsr once_loop`, which waits as stock did and, with a message in hand and before it is dealt with, takes the spent locks off; d0 alone is read after it.
- No branch goes into any of them: no long of an address inside one is in the section (the build refuses otherwise), the listing was searched for each as an operand (one hit, the `beqs` at `0x4008bc3a` to `0x4008bc6a`, a place's first byte), and `tests/test_once.py` goes over every branch of the step routine by its own bytes. d0, d1, a0 and a1 hold nothing of stock's at either place of the step routine: one way to `0x4008bc6e` is through a call.
- Only a sampler's track is touched: tracks 0 to 7 whose machine in the block the audio CPU is sent (`0x80006348` + 142 a track + 62) is type 44, the test `engine/recword.S` makes. On the others slot 24 is a knob or the hold flag.

**Where the code is.** `engine/once.S` and `engine/onceclean.c`: 370 bytes in one more run nothing reaches and nothing names, `0x40088820..0x40088a02`, 482 bytes, after a return and ending on one (`python -m tools.deadcode 3`); its first 16 bytes are the two rows of eight. The page (`engine/recpage.c`, under `ONCE`): the old routine for a step's REC is not built, and its first three runs now have 172, 2 and 0 bytes left. 112 bytes are left in the new run.

**Cost** (counted here). A step played: 36 to 39 instructions more with locks, 18 with none, 22 where the track's ONCE is used. A message of the main task with nothing spent: 9 over stock's wait. One spent lock taken off: 95,831, of which **91,482 are stock's routine for a lock removed by hand** (it works every slot's "has a lock" byte out again over the track's 64 steps) and 4,344 our look over the track's 64 steps. It is what a knob turned back with a trig held costs, once a ONCE step, in the main task.

CONFIRMED in emulation (`tests/test_once.py`, 57), all from the built image:
- the knob: the track's three settings and their words, both tracks tried, the pop-up, a fast turn; a held step's three settings with **stock's lock routines run as they are**, its count of locks, the listeners told; no lock of MODE, no change of the track, no other slot, no other track; on a track in record; several held steps, one with no trig; a slot that holds no mark;
- **a step locked ONCE is played as one locked on**: the event stock gathers has (24, `0x52c0`), stock's applying routine puts it in slot 24's word, stock's per-block loop with `engine/recword.S` in it sends it, and **the audio CPU's engine makes the take a step locked on makes, every slot's entry and both takes to the byte**, for four MODEs; the table differs in that one word after it, the step's count is as it was;
- **the lock is gone after the main task's next message, by stock's routine**: the slot reads none, another lock of the step and a lock of another track stay, the listeners are told, the trig is not touched; **the second pass plays and makes no take**, before the main task has come by (the spent word is sent as stock's hold flag) and after; a step locked ON gathers the same pair every pass and nothing is taken off;
- the track's ONCE: the next step played gets the pair, after its own locks or as its one; the byte is cleared and REC reads OFF; no step after it gets one; a step locked off leaves it, one locked on or to ONCE uses it up; an event with 71 locks is left as it is; another track's steps do not use it;
- a track that is no sampler, an analog track and the FX track are played as stock plays them with the same word in the slot;
- with nothing at ONCE the stretch of the step routine leaves what the feed image's leaves: 40 rounds of random tracks, steps and locks, the event, the registers, the stack, the table;
- **a project the feed image saved reads and turns the same**: steps locked on and off, tracks on and off, the page's words, and every turn that stays between OFF and ON and of every other knob, against the feed image's page side by side;
- the image: section 3 differs from the feed image's in the new run, the page's runs, the three places and the five pointers to page routines that moved; section 7 and every other section are the feed image's; the 32 images before build to the same hashes.

INFERRED, not confirmed:
- that the main task is the one a lock is changed in by hand (above). If it is not, a lock is taken off from another task than the UI's: one word, a count and three bytes, through stock's own routine;
- that messages come often enough: nothing is taken off between two messages. Until then the spent lock says nothing and the step shows as one that holds a lock;
- that a store of one word into the pattern's table from where a step is played is safe. Stock writes that table from the UI's task while the sequencer reads it;
- which ways of playing a step from the panel go through the step routine. If a held trig's preview or a track's key does, it spends a step's ONCE or the track's as the sequencer does.

NOT CONFIRMED, only the unit can show:
- that the take of a ONCE step is not cut short when its lock is taken off under it. In emulation the lock in force is the event's copy and stock's removal writes the table only; what the pattern's listeners do on the unit is not known;
- that the unit plays on as it did with a call in the step routine and one in the main task's loop.

Known and left:
- a spent lock in a pattern that is not the selected one when the main task comes by is not taken off. It says nothing; a turn of REC with its step held removes it.
- the feed image reads a step's ONCE as ON (it records every pass there), and a spent lock as nothing.
- the track's ONCE is the track's, by number: it is not cleared by another pattern, kit or project, and the first step of any kind uses it, a trig with no note too.

## A solo on the sampling page, and the purple keys stock's again: the soloknob image (2026-10-12, section 3 of OS 1.42)

On request He was told that page exists only on sampler tracks, so only those can be soloed. `make image-soloknob`, on the once image. Main CPU only: section 7 is the once image's byte for byte. **Not on the unit.**

**What it is.**
- **The purple keys are stock's pattern mutes.** None of the solo image's seven places is changed and `engine/solo.S` is not built: the two routines that store the copies of the pattern's word, the two stores in the engines' loops, the two questions the keys ask and the draw's hold stock's bytes (tested against the official section). The pattern's own word was never changed by the solo image, so nothing is converted: a key that was purple for a soloed track is that track's pattern mute now.
- **Knob E of the sampling page is the track's solo**, on to the right and off to the left. Its place, the lower row's first, reads `SOLO` or `S OFF` (the value says what it is: the lower row has no room for names). No pop-up, no lock, nothing of the kit or the pattern.
- **While any track's solo is on, every one of the twelve tracks whose solo is off is silenced the way a mute of ours silences**: the mixer is shown a volume of 0 for it and an analog voice's two level words are 0, so its trigs fire and a take is made on it. **A soloed track is heard whatever is muted, green or purple.** Several at once. The FX track is not touched: neither rule goes past the twelve.
- **Off at every start, not saved**: a bit a track in one long of ours, 0 in the image.
- A track that is no sampler any more has no sampling page and so no knob: its bit is cleared by the mixer link, the block after for the analog voices.

**Stock's own solo word was looked at first, and is not used.** Read in the listing, not run:
- It is project settings + 40, a bit a track, beside the global mutes at + 36. `0x400a33fe(settings)` copies both for the per-block routine (`0x80003048`, `0x8000304c`) and `0x4010d4d0(settings)` for the MIDI engine (`0x444b62b0`, `0x444b62b4`, read at `0x4010de5c`). Both are called from four places, one of them the manager's listener for the settings' notes (`0x4001dc4a`, registered at `0x4001bd28`), which calls them first thing whatever the note.
- **Stock has a setter and a toggle for it, in a run nothing reaches** (`0x40022868(settings object, track, on, send)` and `0x400229bc`, in `0x40022868..0x40022a10`, 424 bytes; `python -m tools.deadcode 3`). The setter is the mute setter's twin (`0x400226c0`): it leaves the word alone when the settings' long at + 212 is 2, else sets or clears the bit, tells the settings' listeners (method + 16) with a note of its own type, and with `send` calls `0x40106878` with 93 or `0x401068c0` with 230, by a test of the track: taken for MIDI out, a controller 93, as the mute setter's calls are; not traced. Its getter (`0x40020482`) is called by the toggle alone.
- **So nothing of stock's shows a solo** (no key reads it), the per-block routine's mask and the MIDI engine follow it, and nothing is sent unless asked.
- **Why not driven:** (1) whether + 40 is written to the drive with the project was not established, and if it is a solo left on comes back at power on with nothing but a sampler's page to show it; (2) stock's mask with a solo is every bit but the solos, the FX track's among them, and what the FX track's own test (`0x400a3d5e`) makes of that was not read; (3) the setter has never run on this unit. A long of ours has none of the three, and lets a solo win over a pattern's mute, which stock's rule in our two routines did not (`(solos ? ~solos : globals) | the pattern's word`).

**What is changed.**
- The two rules, under `SOLOKNOB`: `engine/mixlink.c` and `engine/amute.c` take `solos ? ~solos : globals | the pattern's word`, with the solos our long (`0x400a2928`). Stock's solo word is not read by either any more. The mixer link clears the bit of a digital track that is no sampler and any bit past the eight, and writes the long only then.
- The page (`engine/recpage.c`, under `SOLOKNOB`): the place and the turn. 106 bytes in its first run (66 left).
- The long: the first four bytes of the run the solo image's code was in (`0x400a2928..0x400a29ce`, which nothing reaches), 0. The rest of that run is stock's bytes again. No long of that address is in the section (the build refuses otherwise).
- The mixer link is 48 bytes longer (222 left in its run); the analog mute's size did not change, so nothing behind it moved.

CONFIRMED in emulation (`tests/test_soloknob.py`, 43), from the built image:
- the knob: on, off, on stays on, three tracks tried, each its own bit, the others' kept; the place's two words and its empty name; no lock, no change of MODE, no pop-up; the rest of the page and every other knob, REC's three settings among them, the once image's turn for turn;
- our two routines around a stand-in for the mixer: with no solo, the once image's answer for 24 random pairs of mutes; one solo, each of the eight: the other eleven at volume 0 and all four analog voices' level words 0, with the soloed track green-muted, purple-muted, everything muted, the FX track's bit set in both words; five sets of several solos against three sets of mutes; nothing else of the block, the level words or the control block moves; stock's solo word no longer followed; a solo on a track that is no sampler cleared;
- the seven places, the two routines and the keys' routine are the official section's bytes, and stock's routine stores the pattern's word as it is;
- the image: section 3 differs from the once image's in the mixer link's run, the analog mute's, the page's, the solo image's run and its seven places; section 7 and the other sections are the once image's; the 33 images before build to the same hashes.

NOT CONFIRMED, only the unit can show: all of it there. In particular that a purple key mutes again as stock's did.

Known and left:
- **A MIDI track is not silenced by a solo**: it has no sound here, and its notes go on. On the solo image stock's test dropped them.
- Only a sampler's track can be soloed, and only from its sampling page.
- It is the unit's and no project's: a solo left on stays on through a pattern's or a project's load, until it is turned off or the power goes. Nothing but that track's sampling page shows it.
- A project that holds purple "solos" from the solo image holds pattern mutes of those tracks.

## A crossfade on the sampling page: the xfade image (2026-10-12)

The the maintainer's report.

- Knob G of the sampling page, where MODE was, is the track's crossfade, `XF0` to `XF127`: a byte a sampler track in main CPU memory after the solos' long (`0x400a292c`, eight bytes), 0 at every start, not saved, not lockable (`engine/recpage.c`).
- Every other one of the twelve tracks is turned down by the largest number among the OTHER tracks' crossfades. The mixer is shown that track's volume word times (127 - x) / 127 (`engine/mixlink.c`); an analog voice's two level words are made that squared of what they were (`engine/amute.c`), which is what stock makes of such a volume. Through the mixer's own gain routine, run in emulation: the gain is the square, 12.2 dB down at 64, nothing at 127. A track a mute or a solo silences is silent whatever the crossfade says.
- MODE has no knob on this image, so a take at a stereo place is always stereo: MODE's lowest bit is set in the block the audio CPU is sent, every block, on a sampler track (`engine/recword.S`, one instruction). A take at a single slot is mono as it was.
- Cost on the main CPU's per-block interrupt, counted: 88 instructions a block more than the soloknob image with no crossfade up, 425 with one up, 484 with all eight.
- Main CPU only: section 7 is the soloknob image's. The 34 older images hash as before. `tests/test_xfade.py`, 89.
- How it was made: begun by an agent the maintainer stopped mid-build, finished in the main conversation. Five of its test checks were unfinished figures (the cost table, two take lengths, the gain read as a negative fraction, a branch six bytes longer over the new instruction) and were set from what the image does; no engine text was changed after the stop.
- **Not shown on the unit: any of it.** Above all how the fade sounds over the knob's travel, and whether the volume words stepping once a block can be heard as steps.

## One crossfade for the whole unit: the gfade image (2026-10-12)

On request.

- The xfade image's eight numbers hold the one crossfade in the place of the track that last turned it, the rest 0. So the mixer's rule and the analog voices' (`engine/mixlink.c`, `engine/amute.c`) are the xfade image's code, not touched: every other track goes down by it and the track that holds it stays.
- `engine/recpage.c`, under GFADE: every sampling page shows the largest of the eight (`xfade_now`), and a turn of knob G writes the new number into the track's own long first, which clears its three neighbours with it, and then clears the other long: the per-block routine never finds all eight at 0 on the way.
- A track that stops being a sampler loses its number (the xfade image's rule), so the crossfade is 0 again if the track that held it changes machine.
- Main CPU only, the page's code alone: section 7 is the xfade image's. The xfade and soloknob images rebuilt to their hashes; the other older images were not rebuilt (no file they are built from was changed but `engine/recpage.c`, under the new define, and the build's own lists). `tests/test_gfade.py`, 18. The whole suite not run.
- Not built: the solo as a lock, and a page for the two on the analog tracks. Not on the unit.

## The right channels by a hardware transfer: the dma image (2026-10-12, section 3 of OS 1.42)

The maintainer, with the gfade image on the maintainer's unit: the screen and knobs lag with stereo samples playing and not with mono ones; "i def need all 8 move it the way stock does. we sould do the full fix like ewlektorn would do". `engine/rightdma.c`, `tests/test_dma.py` (47), `make image-dma` (`bc792be5...`). **Emulation has no transfer controller: that a transfer of ours ends on the unit, and what it brings, is not shown. The image checks that itself, below.**

How stock moves its own buffers (read in the listing; stock's code run in emulation for the words it writes):
- The controller's control word gets 6 or'ed in at the startup (`0x40000546`): round robin among the channels of a group, the four groups in fixed order. By the family's layout as remembered (not checked against a manual): the groups' order is the reset one, 48 to 63 first and 0 to 15 last. INFERRED.
- Channel 47, its words at `0xfc0455e0`. Written once (`0x400a2ee4`): nothing added to either address at the end, 16 bytes a turn read and written as 16 (`0x0404`), each address 16 on a turn, the last word 0. A transfer (`0x400a4aec` in, `0x400a4e3c` out): to, from, the turns twice as `0x8000 | 47 << 9 | n` (every turn starts the next by the channel's own number), a mark at `0x43bde73c`, and 47 written to the start register `0xfc04401e`. 64 turns in, 27 out.
- The wait (`0x400a20ae`): if the mark is set, bit 7 of the channel's last word (`0xfc0455fe`) is read until it is set. No limit. Called twice: `0x400a4e30`, and `0x400a54f8` before the routine's `rte`, so no transfer of 47 is running when a block begins.
- Every channel the main program names a word of: 15, 29, 30, 34, 35, 36, 37, 42, 47, 52, 54, 59 (a scan of every long at an even place). No word of any other, and no base of the table with a computed channel.
- **Stock itself points transfers at the program's memory, by an address 0x08000000 up**: channel 42 writes the delay's memory at `0x4fc00000` on (`0x4009687a`: 16 turns of 16 bytes, the address taken round in 4 MB, the next words loaded from on-chip memory at `0x8000c6a0`). The cached range ends at `0x47ffffff`, so that address is the same memory not cached. That is the way round the trap, and it is no use to the mixer, which would read the second set uncached four passes a block. So the second set is in on-chip memory.

What was found for ours:
- **On-chip memory has room.** The startup (`0x4000045c`) copies its first half from the image up to `0x80007330` and clears from there to `0x80008000`; the second half is copied to `0x8000f860` and cleared to `0x80010000`. The last thing named in the first half is 48 bytes at `0x80007300`, and a loop's end at `0x8000733c` is that array's. No instruction names an address from `0x80007330` to `0x80008000`: the fifteen longs at even places that read as one inside our part are the end of one instruction and the start of the next (three, all odd) or numbers in tables (`tools/build_main.py`, `DMA_MEMORY_SEEN`; the build fails on any other). Neither place the stack pointer is set to is there (`0x48000000`, `0x405d376c`). Ours: `0x80007400` 1024 bytes of scratch, `0x80007800` the second set (1280), `0x80007d00` eight longs. Cleared at every start by stock.
- **Two channels, 12 and 13**, of the lowest group: a transfer of stock's waits one turn of ours at most (16 bytes), and ours wait for all of stock's. The window's right channels are two stretches, nine halves from `0x5c0` and seven from `0xe40`: 36 turns and 28.
- Three places in the per-block routine `0x400a38ce`. Its first call (`0x400a3940`, to a routine that waits for a flag and takes no arguments): the long is read and the transfers started. The audio CPU wrote the right channels at the end of the block before, ahead of sending the left ones, and is a block's work from the next. Where stock waits for the left buffers (`0x400a4e30`): stock's wait, as the images before. The last call before the mixer's (`0x400a502c`): the transfers are waited for and the mono tracks get their copies. Every way to the mixer's call runs straight from `0x400a4ae4` through both (no branch into that stretch from outside it, none out).
- A channel's last word is written 0 before each start, as at its setting: the controller takes "done" away when the channel's turn comes, and ours come after stock's. INFERRED from the family's description; stock does not need it.

What the image does about not being provable here:
- From a start, for 1500 blocks with the audio CPU up (a second), the CPU reads all sixteen halves as well, a mark is left where a transfer has to write, and the two are compared. The sound is the CPU's. The sampling page's last box reads **C** before the load.
- 1500 blocks that agree: the transfers alone are used, and only for the stretch a stereo track needs (none, with none). **H**.
- 16 blocks that differ, or a wait of 20,000 turns that does not end: given up until the next start. **X**. Then the long and the right channels are read by the CPU where and as the gfade image reads them (its routine run beside ours: the same second set, the same reads).
- A block's count, the transfers believed: 770 instructions with no stereo track, 200 with eight, and 2 of the window's words read by the CPU. The gfade image: 732 and 979, and 2 or 514 words.

**Only the unit can show**: that the box reads H after a second; that stereo samples sound as before on both sides (`make stereo-check` measures it); and whether the lag is gone. If it reads X, which of the three reasons is in the eighth long (`0x80007d1c`: 1 a wait while checking, 2 a wait after, 3 a difference), not on the screen. The main CPU's load is still not measured: if H is read and the lag stays, the cause is not the crossing.

## The solo and the crossfade on the analog tracks: the apage image (2026-10-12, section 3 of OS 1.42)

On request. Built: the page. **Not built: the lock.** `engine/recpage.c` under APAGE, `engine/mixlink.c`, `engine/amute.c`; `tests/test_apage.py` (24); `make image-apage` (`44c612e8...`).

- One object serves SYN for every audio track, analog ones too (above, "the second SYN page"), so the page is the same class's. Its three methods go to routines of ours in a seventh run (`0x400b439c`, 818 bytes, named by nothing): on an analog track (the active track 8 to 11) the list is two pages, and on the second no knob is stock's, knob E is the track's solo and knob G the crossfade. Every other track goes on to the sampler's routines as before.
- The solos' long keeps twelve bits: the mixer link cleared all but eight every block. An analog track is never without its knob, so its bit is not taken away as a digital track's is when it stops being a sampler. The analog mute already went by the long's bits 8 to 11.
- The crossfade is twelve numbers, three longs (`0x400a292c` on; the four new bytes are 0 at a start, in the solo image's old run). A turn writes the track's own long first and clears the two others after. The mixer link goes by the largest of the other eleven for each track; the analog mute does the same for each voice, where it took the largest of the eight for all four.
- Shown in emulation: an analog track's second page reads S OFF or SOLO and XF and the load, the two knobs turn them and the six others nothing; its first page and a sampler's two are the dma image's; a digital track that is no sampler has one page; an analog track's solo silences the other eleven and stays; an analog track that holds the crossfade is as stock made it and the rest follow the xfade image's law; with no analog number the mixer is shown what the dma image shows.
- Main CPU only: section 7 is the dma image's. The dma image rebuilt to its hash; the older ones were not rebuilt (hard rule 9).
- **Only the unit can show**: that SYN pressed again on an analog track opens the page (the active track read as 8 to 11 there), and that the analog machines' own first page is untouched.
- **The lock, not built.** A digital track's solo could be locked in knob slot 17, which no record names. An analog machine uses 17 and 24 both: where a lock on an analog track could be kept is not known, and nothing is built on a guess.

## A sampler track's solo as a lock: the slock image (2026-10-12, section 3 of OS 1.42)

The the maintainer's report. `engine/recpage.c`, `engine/amute.c`, `engine/mixlink.c` under SLOCK; `tests/test_slock.py` (23); `make image-slock` (`79ec3a85...`).

- **A step's solo is a lock on knob slot 17**, at one of two marks in its high byte: `0x35` the step solos its track, `0x1a` it does not (`0x3580`, `0x1a80`); anything else and the track's own solo decides. As REC's on slot 24 ("A step's REC is a lock of its own"): made, read and removed with stock's three routines of the steps object, and there only where a step is not to do as the track does.
- Slot 17: no record of the twelve machines the audio CPU runs names it (`tools/params.py`, asserted by the test). In the block the mixer is given its word is the machine's type, written by stock every block; where a trig's locks are written (`0x800021b0`, `0x4198` bytes before) it is the lock's value while a locked step is in force, and the track's own after its next trig.
- Knob E on a sampler's sampling page: with a step held, the step's (a step with no trig gets one first, as REC's); with none, the track's own bit as before. The place says the first held step's.
- Each block the analog mute, which runs first, works the solos out: the knobs' long, without a digital track that is no sampler, and each sampler track as its mark says. It keeps them in a long of ours (`0x400a2938`, 0 at a start) and the mixer link goes by that. The knobs' long is not written by a lock.
- Shown in emulation, stock's lock routines run as they are: the lock made and removed, its count, no lock of MODE or REC with it, every held step its own; a mark solos its track and silences the other eleven, a mark off takes a soloed track out, nine other values of the slot (REC's two marks among them) leave the track's own to decide, a mark on another machine is nothing; with no mark the mixer is shown what the apage image shows. An analog track's solo is not locked by a held step.
- Main CPU only. The apage image rebuilt to its hash; the older ones not rebuilt (hard rule 9).
- INFERRED, as it was for slot 24 before the unit showed it: that a lock on slot 17 is played like any other and comes back out at the track's next trig; that it is saved with the pattern.
- **Only the unit can show**: that no sampler track of his has either mark in slot 17 unasked (it would be soloed, or could not be soloed, with nothing on the page saying why: "a track soloed by itself" is what to listen for); and what a locked step leaves when the sequencer stops before the track's next trig.
- Not built: a lock on an analog track's solo. No place for one is found.

## An analog track's solo as a lock, on slot 26: the alock image (2026-10-13, section 3 of OS 1.42)

The the maintainer's report. `engine/recpage.c`, `engine/amute.c` under ALOCK; `tests/test_alock.py` (21); `make image-alock` (`f4d77560...`). **Built on one thing that is not confirmed, the first line below. In `build/images/`, not in `build/flash_this/`.**

- **NOT CONFIRMED: that nothing of an analog voice reads slot 26's word.** What is known, from the records (`tools/params.py`, asserted by the test): every machine's knobs are among slots 17 to 26; the 31 analog machines (types 8 to 33 and 39 to 43) have theirs on 17 to 24, one of them (28) on 25 too, and none on 26. Stock copies a machine from one track to another as those ten words (`0x400a9c2e` to `0x400a9c64`). So slot 26 is a machine's word, and for an analog machine a word no knob is on. The code that makes an analog voice's control words out of its track was not read through: a routine that took all ten would be heard as a change in the voice while a locked step is in force. Only the unit can say.
- Looked at and left: slots 0 and 55, which no record of any kind names (they may be stock's own); slots past 56, which are outside a track's 142 bytes (a lock there would be written into the next track); keeping the lock out of the track's words by taking it from the event as it is played (two of stock's routines to wrap).
- A track's machine is a byte a track at `0x80002f50`, the analog tracks' after the eight (stock reads + 8 on at `0x40097a7e`, in the routine that builds the block that is sent; that routine carries every word of every track across through its smoothing, so a mark is read where the locks are written, as a sampler's is). 35 is the MIDI machine, where slot 26 may be a knob: a mark counts only on a track that holds an analog machine, and the page makes no lock on any other.
- The same two marks as slot 17's. The solos are worked out for all twelve tracks in a routine of its own (`0x400f51ea`, a run named by nothing: the analog mute's is full).
- Shown in emulation, stock's lock routines run as they are: knob E on an analog track's second page with a step held makes and removes the lock on slot 26 and nothing else; a mark solos its analog track and silences the other eleven, a mark off takes it out; other values, the MIDI machine and other machines leave the track's own; slot 26 of a digital track and slot 17 of an analog one are not looked at; with no analog mark the mixer is shown what the slock image shows. The slock image rebuilt to its hash.
- **Only the unit can show**: the first line; that no analog track of his has a mark in slot 26 unasked; that the lock is played and saved as a sampler's is.

## What SY SWARM's code would free (2026-10-13, section 7)

Measured for the sample rate reduction the maintainer asked for, after the maintainer's word that SWARM may go. Static only, nothing built. `tools.deadcode.survey` run on stock section 7 twice: with Twinshot's two table entries zeroed (as our images have it), then with SWARM's (engine 10) zeroed too, and the two compared.

- SWARM's update is `0x400092ec`, its render `0x400096e8` (the tables at `0x40014920` and `0x400148f0`). Each is named once in the whole section, by its table.
- **Update: `0x400092ea..0x400096e8`, 1,022 bytes**, named by nothing once the entry is gone. It holds words that are not instructions (constants in line).
- **Render: `0x400096e8..0x400097dc`, 244 bytes**, by the two addresses and not by the survey: no `rts` parts it from Twinshot's update, so the survey takes both as one piece to `0x40009a8a`, and keeps that piece for one odd-offset value in the data (`0x40018997` read as `0x40009a7a`, inside Twinshot's update, which the stereo image already uses).
- A helper only SWARM's code names: `0x40006014..0x40006074`, 96 bytes.
- **So about 1,360 bytes, 1,266 of them one run that ends where Twinshot's update begins.**
- NOT LOOKED AT: SWARM's data, if it has any of its own; what a track left on SY SWARM is to be given (a render that fills its buffer with nothing has to stand in both tables).

## Several tracks recording at once: the multi image (2026-10-13, sections 3 and 7 of OS 1.42)

The the maintainer's report `engine/recfeed.c`, `engine/stub.S` (`rec_all`, `rec_line`), `engine/sampler.c` under MULTI; `tests/test_multi.py` (28); `make image-multi` (`eceba3b3...`), on the alock image. **In `build/flash_this/`. Emulation only. Two things only the unit can show, the last two lines.**

- **There was one pipe.** CONFIRMED in the source and by test: the feed wrote one ring at `0x800` and its loop left at the first track that said record (`engine/recfeed.c`, `mix_rec`), and every voice with a take running took that ring (`rec_step`).
- **The plan the session before left was the right channels' places in the window. Not built.** A track's place there is two halves, and the fifth track's two are apart (`0x7c0` and `0xe40`); the main CPU's two transfers read all sixteen halves every block; and a block of a take read as a right channel is noise at full scale. Looked at and left.
- **Built: the ring's own room, a block a track.** It is eight blocks of 32 stereo frames (`0x810..0xc10`): track t's is `0x810 + 128 t`. Nothing of the right channels or their transfers is near it. The word under the count (`0x802`, the window's last two free bytes) holds a bit a track whose block was written with that count; count and bits are one long, written last. `engine/feed.S` is as it was: it is handed where to write.
- **The price is the ring's slack, so the take moved.** With one block a track, a block is there for one mixer call. The stops image took the ring after the voice loop, which is early in a light block and late in a heavy one; the main CPU writes after its mixer. Taken there, a block would sometimes be read while it is written, or twice, or not at all. `rec_all` is called by the hook before the voice loop. By the order read in "How the two CPUs take turns": the main CPU's edge starts the audio CPU's interrupt once a block; the main CPU then waits for the audio CPU's eight buffers (and, since the dma image, for our two transfers) before its mixer, and feeds after it; so it cannot write this block's until long after the audio CPU has taken the last one's, and it has written the last one's before it makes the next edge. That is the order stock leans on for its own knobs. **INFERRED: read, not timed.**
- **A take begins a block later than it did**: its note starts in the interrupt after the trig's (as before), and its first block is the one written while the note started. The sound of a trig on the same step reaches the mixer a block after it is made, so it is in that block or the next: nothing of it is lost.
- **SWARM is not used.** Measured again for this, the same way: 1,360 bytes, as the section above. The take's routine is 200 bytes where it was 216 (no ring to walk), and the post step lost its loop: 268 bytes are free on the audio CPU after it, where 218 were.
- **What it costs the main CPU**, counted in emulation as the feed image's were (instructions a block of takes adds, and word cycles of the window, a long two), sources the tracks, a take a track:

| takes | 0 dB stereo | +12 dB mono | word cycles |
|---|---|---|---|
| 1 | 1,274 | 1,631 | 71 |
| 2 | 2,542 | 3,256 | 139 |
| 4 | 5,078 | 6,506 | 275 |
| 8 | 10,150 | 13,006 | 547 |

  One take on the first track is 141 instructions and one word cycle more than the alock image's: the loop goes on to the other seven tracks. For scale: the right channels read by the CPU, which were the lag, were up to 512 word cycles a block; the feed that dragged before the feed image was 3,993 to 5,017 instructions and 70. **So two takes are under anything that has dragged, four are about what the ptn image's one was, and eight are past both.** The main CPU's load has never been measured: this is a count, not time.
- The audio CPU: an interrupt with no take is 19 to 35 instructions shorter than the stops image's, and one with eight takes fed is 12,924 where the stops image's is 18,243. A track that records does not play.
- Shown in emulation, from the built images: eight tracks take eight blocks, each its own, into their own places; a stereo place's take, a mono one's and a single slot's are the stops image's take of the same blocks, the table's every line, the marks and the frames; a block written while the voices run is taken whole by the next interrupt and once, and a block with nothing written takes nothing; a track whose bit is not set takes nothing while another is fed; a full buffer ends the take and nothing goes past its end. The feed: every track that says record is fed its own source's block, by the rule the one block was made by, one to eight tracks, every kind of take, the count through nought; one track alone is fed the alock image's block to the bit; a step's REC counts a track as its knob does; with REC off, the audio CPU down or a bank loading nothing is read or written; never a byte. Section 3 is the alock image's but for the meter's run and the solos' run; section 7 is the stops image's but for three runs and two operands. The alock image rebuilt to its hash.
- If it drags: the eight blocks are one stretch, so one transfer channel could carry them from on-chip memory, as the right channels are carried the other way.
- **Only the unit can show: that a take has no click or gap** (the order above), with one track and with several, at a light load and a heavy one.
- **Only the unit can show: that the screen, the lights and the keys do not drag** with two, four and eight tracks recording. On request

## Sample rate reduction, and REC and SRC out of MODE: the srr image (2026-10-13, sections 3 and 7 of OS 1.42)

The the maintainer's report, and a brief with the plan in it. `engine/sampler.h` (SRR), `engine/sampler.c`, `engine/stub.S` (`crush`, the stand-in), `engine/recword.S`, `engine/recfeed.c`, `engine/recpage.c`, `engine/onceclean.c`; `emu/sampler_ref.py` (`Hold`); `tests/test_srr.py` (94); `make image-srr` (`fcd013ae...`), on the multi image. **In `build/flash_this/`. Emulation only.**

- **The sound.** Every frame the player makes is held: a phase goes up by a step a frame and only a frame at which it runs over is let through. Done to what the player made, before the voice's level and gain and so before all of stock's stages; both sides of a stereo sample by one phase; a note's start, and the knob at 0, set the phase so the next frame is let through. Put before the level and not after it by choice: a trig's fade and the envelope stay smooth.
- **The knob**: MODE's record, 0 to 127, plain, named SRR (long name "Rate Red"), in the first page's sixth place, stock's own knob again (its turn, its pop-up, its locks). Every 16 halves the rate: 16 is 24 kHz, 32 is 12, 48 is 6, 64 is 3, 80 is 1.5 kHz, 96 is 750 Hz, 112 is 375, 127 about 190. Between two halvings the hold's length goes up evenly: length in 256ths of a frame `(256 + f) << n`, step `2^32 / length`. 0 is off: nothing is run.
- **Where modulation lands. CONFIRMED in the listing:** the block is built from `0x800021b0` by `0x400979ca`, which copies machine 44's slots 19 and 23 as they are, and the modulation routine (`0x40097b74`, called at `0x400a4b40`) is run on the block that is sent after that. So an LFO's move of slot 23 reaches the audio CPU unsmoothed. **NOT CONFIRMED: that MODE's record is offered in the LFO's list of destinations.** Only the unit can show it.
- **Where a track's own values are. CONFIRMED in the listing:** stock keeps the kit's address at `0x800030b8` (written at `0x400a34ca`, `0x400a359a`, `0x400a3c38`, from a message's long); a track's sound is 291 bytes of it from + 42 (`0x400a4642`, `0x400a46f8`); the routine that puts a lock's slot back (`0x400977d8`, called at `0x400a470e`) reads slot s as the word at sound + 20 + 2 s. The UI's holder reads the same shape: its value method (`0x40012986`) and its store (`0x40013304`) take a record's slot (`0x400a5cc2`, the descriptor's long at + 4) and use the word at + 20 + 2 slot of what the sound object's method + 40 gives. **INFERRED: that the two are one memory, and that a pattern's save writes it slot for slot.**
- **REC and SRC.** The track's own word on slot 24: `0x40a4` with REC in bit 0 and SRC in bits 8 to 11, so its high byte is `0x40..0x4f`, never a step's mark. Read and written by the page straight in the kit where the sound engine's side reads it (not through the holder: no listener of stock's is told of a slot the machine has no record for). `engine/recword.S`, in a run of its own (`0x401a8d52`, 326 bytes, 8 of them a byte a track), reads it there every block and leaves in slot 24 of the block that is sent REC's mark in the high byte (a step's lock where the locks are written, else the track's) and the source in the low byte. The audio CPU takes the mark and nothing of MODE; the feed takes the mark and the source. A take at a stereo place is stereo.
- **An old pattern.** A word that is not signed: the routine makes it from MODE's old bits, signs it, and puts MODE at 0 in the kit, in the block and where the locks are written, the first block the track is a sampler's. One way, as the maintainer accepted. **Old locks of MODE** would be played as amounts of the reduction: the routine sets the track's byte and the main task (`engine/onceclean.c`, at its next message) takes every lock on slot 23 of that track off in the selected pattern. A lock in a pattern that is not selected then stays until that pattern is played with its kit unsigned, which is when its own tracks are made.
- **A machine changed.** Stock writes over slot 24 of every digital track in the block that is sent (the hold flag: Hardware log, 2026-10-10, the probe image), so a signed word left behind is not another machine's hold flag after all. It is cleared all the same, with the REC locks, when the track's SYN page is next drawn (`strays`), so a sampler put back starts with REC off. A MIDI machine's track is left alone: slot 24 is a knob of its.
- **SY SWARM.** Its update and render (`0x400092ec..0x400097dc`, 1,264 bytes) are the room: 638 used. Engine 10's two table entries are a stand-in, an update that does nothing and a render that clears the block. The machine is still in the unit's list and plays nothing.
- **Counted, audio CPU** (an interrupt of eight stereo voices, emulation): with the knob at 0, 336 instructions more than the multi image's (42 a voice: the step worked out); with every frame let through, the most it can ask, 2,600 more. Against stock's heaviest (117,348) that is 2.2 hundredths: about 2 on P, as the maintainer estimated. The hold is 5 instructions a frame held and 6 let through, 6 and 8 with a right channel. **A count, not time.**
- **Counted, main CPU:** the per-block routine is 38 instructions a sampler track at most, 6 for another machine, 52 once for an old pattern's track.
- Shown in emulation, from the built images: the hold is the model's frame for frame, twelve cases (a hold to the frame at every sixteen, between numbers, the top, a knob that moves, off in the middle, one channel); at 0 the sound is the multi image's to the bit, both sides of eight tracks; a take is made by the mark alone and is the multi image's take; a track on SWARM is silent and the others are untouched; the routine's every case, registers kept; the feed by the routine's word whatever MODE holds; section 3 differs from the multi image's in the page's runs, the feed's, the two new runs, MODE's record, its two names and three operands; section 7 in our runs and four table entries. The multi image rebuilt to its hash (`eceba3b3`).
- **Only the unit can show:** that SRC and REC are there after a save and a power cycle (the kit saved slot for slot); that SRR is in the LFO's destinations; that stock's turn of record 502 is right (it ran on the early images, as MODE); what P reads.
- Not handled: a sampler sound saved to the sound pool on an older image, played by a sound lock, has its old MODE read as an amount.

## How a knob turns, and the sampling page's knobs through it: the gear image (2026-10-13, section 3 of OS 1.42)

On request. `engine/recpage.c` (GEAR); `tests/test_gear.py` (13); `make image-gear` (`c0a62001...`), on the srr image's second build. **In `build/flash_this/`. Emulation only. Main CPU only: section 7 is the srr image's.**

- **Why they were quick.** Every knob of the sampling page, and SMPL since the stops image, took the event's steps as they came: a tick, a whole step. Stock's knobs do not.
- **How stock turns a knob. CONFIRMED in the listing**, `0x4003b870` and three routines it calls:
  - `0x400f6866(event, fine, coarse)`: the event's steps (its long at + 16), times `coarse` while the knob is pushed in (its byte at + 20), else times `fine`. The two numbers are the first two longs of the sixteen bytes a record's entry of the display table is given: 1 and 4 for a plain knob, 1 and 8 for Twinshot's sample picker. **So the 4 and the 8 are what a pushed turn is multiplied by, not how far a plain turn goes: the hardware log's entry for the srr image's second build inferred that wrong.** The second build is right all the same: it gives SRR all sixteen bytes of a plain knob.
  - `0x400f6884(event)`: pushed in.
  - `0x400f6a96(the page's ticks, knob, steps, a feel, pushed)` -> the change, 8.8. The ticks are 20 bytes a knob from + 32 of an object in the page (+ 148 of the SYN class's). The feel is 28 bytes built at a start (`0x401aa658` on, by `0x400f66e0`): three flags, then three longs for a plain turn and three for a pushed one. The routine adds the steps to the knob's count, divides by the feel's second long, and gives back that many steps of the third long, times a speed it keeps for the knob, which a fast turn raises by the first long; the count is cleared when a step is given. **So a feel's second long is the ticks a step.** The fourth long of a record's sixteen bytes is its feel: `0x443db178` a plain knob's, `0x443db140` the picker's.
  - **The feels' numbers, read the same day** (the routines the start-up code hands over; the build holds their bytes): the plain feel (`0x400f6390`) is 3 ticks a step, the speed raised by 2, and no pause; the picker's (`0x400f63f0`) is 6 ticks a step, the speed never raised, and its first byte clear, which has the routine swallow ticks for a while after each step. One more of stock's (`0x443db15c`, `0x400f63c2`): 24 ticks a step, no speeding up. NOT UNDERSTOOD: a pushed turn's three longs. The plain feel sets only the third (4), and the first two are what the constructor copies in, which read -1 in the image.
- **A stock page of whole numbers does the same by hand** (`0x40049730`, a page whose knobs are no records): pushed, steps (1, 8), knob, then the change with the plain feel's address and its own ticks, and it takes the change's whole part, towards nought (`0x40049770`). That is the precedent followed.
- **Built.** A turn of a knob on the sampling page (A to F and H; G, the crossfade, is left as it was, a tick a step) goes through those three routines with the page's own ticks, the plain feel, and 4 for a pushed turn; SMPL on the first page with the picker's feel and 8, which is what stock gave that knob. The knob moves by the whole part. The analog tracks' solo the same. In a tenth run of the page's (`0x401a69c4`).
- When the audio CPU has not said what the slots hold, SMPL's turn is handed on to stock after its ticks were counted here, so stock counts them again: a turn then goes twice as far. Only while the unit starts or a bank loads.
- Shown in emulation, stock's change routine played by the test: each knob's turn reaches it with the page's + 148, the knob's number, the steps, the right feel and the pushed byte, a pushed turn's steps times 4 (SMPL: 8); DEST, the gain, the solo, SRC, REC and SMPL move by the whole part of what comes back and by nothing while it is under a step; the crossfade's knob does not ask and moves a tick a step. **And the srr image's page, run here for the first time: REC and SRC are read and written as the track's own word in the kit.** Section 3 differs from the srr image's second build in the page's runs and a few operands; section 7 not at all; the srr image rebuilt to `69f0fd04`.
- **Only the unit can show: how the knobs feel.** Stock's change routine and its feels do not run in emulation. If a plain knob's feel is still too quick for REC, SRC and BANK, the picker's is the slower one stock has.

## The main CPU's time, asked of the unit: the prof image (2026-10-13, section 3 of OS 1.42 only)

The the maintainer's report. `engine/prof.S`, `engine/recfeed.c` (PROF), `tools/prof_read.py`; `tests/test_prof.py` (8); `make image-prof` (`bb417da0...`), on the gear image's second build. **A tool, not one to keep. Emulation only. Main CPU only: section 7 is the gear image's.**

CONFIRMED by reading (`build/dis/sec3.lst`; each is asserted by the build, `PROF_CONTEXT`):
- **The main CPU has a clock stock itself reads.** The first timer's count, `0xfc07000c`: read at `0x400a596a` and again at `0x400a5992`, the difference compared with 1,319,999,999 for a wait. So it counts and goes round at 32 bits. If that wait is ten seconds the rate is 132 MHz, 88,000 counts a block: inferred, and not needed. All four of these timers and all four of the other kind are named in the code: none is free to make an interrupt of our own.
- **The per-block routine's address is compared with its vector's long** (`0x400a3764`: the long at `0x400002fc` against `0x400a38ce`). Seven other places write that long, some keeping what was there and putting it back. So the long is left alone and the routine's first two instructions (`linkw %fp,#-164`, `moveml %d0-%a5,%sp@`, 8 bytes, nothing jumps into them) are the hook.
- **The routine has one rte**, its last instruction (`0x400a5520`), and names nothing of its own frame.
- **The running task is a long**, `0x454e49a8`: the task switch (`0x40000410`) saves the registers through it, stores the next task's there (`0x4000044a`) and takes its registers.
- **Nothing runs in user mode**: every instruction that names the other stack pointer is past the code's end (data read as code). So what the interrupt stops has its stack where the frame is.

Built:
- A record of 32 words, first in a run nothing reaches (`0x40170628`, 848 bytes), made afresh every block: a mark and a count of interrupts; the timer at the interrupt's start; the frame's first long (format, vector, the stopped code's SR) and its PC; its stack pointer; the timer at the mixer's call, at the mixer's return and after the takes and the meter; the timer at the interrupt's end; six longs of the stopped code's stack; the running task.
- The start: 30 instructions before stock's third. The end: the start leaves a second frame under stock's routine, format 4 and the SR the routine runs with (read, not assumed), so stock's rte comes to five instructions of ours at the same level, which read the timer and do the real rte.
- The last source, SENDS, is the record on this image: a sampler track on it is fed the record's words, each to both sides, no gain and no dither, so a take of either kind holds them word for word. Every other source is fed as on the gear image.
- `tools/prof_read.py`: the interrupt's time and its parts in hundredths of a block, what was stopped by level and by task, the routine (the address after the rts before it: a guess from the bytes) and its caller (the first of the stack's longs that comes after a call instruction).

CONFIRMED in emulation: the start keeps every field and reaches stock's third instruction with the registers, a6 and the stack as stock's two instructions leave them, our frame under; stock's rte comes to our end, which reads the timer, and ours returns to what was stopped with its SR and stack. A track on SENDS is fed the record, the others the gear image's blocks, the count and the bits as the multi image has them; with no track on SENDS the window is the gear image's, read and written in the same order. The reader gives back a made-up take. The image differs from the gear image in the profile's run, the feed's run, the routine's first 8 bytes and the mixer call's operand; the gear image rebuilds to `5ef3a04c`.

NOT CONFIRMED, and only the unit can:
- **Nothing of a real interrupt runs in emulation.** The rte in the test is the test's, by the chip's manual from memory: the emulator has none. If the frame is not what the manual says, the unit hangs at its first block. The official file flashed from the boot menu brings it back: sections 2 and 4 are not touched.
- That the timer counts on the unit as the wait says.
- That six longs above the stopped code's stack pointer can always be read. A task stopped in its first instructions with its stack at the very end of a memory would be read past: not looked for.
- That a take goes to the +Drive and comes off with Transfer word for word. The reader drops any block without the mark and times only blocks in a row, so a file that was changed says so by how little is left.
- **The sample's lean**: once a block, at the same point of a block. Said in the reader's own first lines.

## A ONCE used up where no step was played: the stay image (2026-10-13, section 3 of OS 1.42)

The maintainer, with the gear image's second build on on the unit `engine/once.S`, `engine/onceclean.c` (STAY); `tests/test_stay.py` (8); `make image-stay` (`01d7363b...`), on the gear image's second build. **In `build/images/`, not in `build/flash_this/`** (another session's prof image is there). Emulation only. Main CPU only.

- **The cause. CONFIRMED in the listing.** The routine that plays a step (`0x4008b8fa`) has two callers. The sequencer's (`0x4008cf86`) hands it 0 as its fifth argument, the event's place. The other (`0x4008c288`, in `0x4008c128`) works out the step the sequencer is on from its count of ticks, for one track or all thirteen, and hands the step routine a place for the event. `0x4008c128` is reached from two listeners that jump to it (`0x400179f2`, for a change's track; `0x40018ff6`, for a track of the selected pattern), from four places of a UI class (`0x40040106` on), and from the routine at `0x4008c300`, which clears the sequencer's counts first. **INFERRED from that: it brings a track's held parameters up to date after a change, and at a start.** With the sequencer stopped the count is 0 and the step is the first.
- So `lock_make` of `0x52c0` on the first step told the pattern's listeners, a listener played the first step that way, `once_seq` found the lock at ONCE and spent it, and the main task took it off: a lock at ONCE on the first step lasted until the next message. ON and OFF are never spent, so they held. On any other step nothing played it. **And a track's own ONCE was used up by any change to the track**, a trig put down for it to record on among them: not reported, read.
- **Built.** In `once_seq` and `once_none`, the step routine's fifth argument is read from the stack (76 above its frame of 56, under the return and what stock has pushed): not 0, and nothing of ours is done. A ONCE is spent, and a track's used up, only by the sequencer's caller.
- **And a fault of the srr image's, found on the way.** `once_loop` called `once_clean` only when a ONCE had been spent, and the srr image had put its own work there: taking off a made track's old locks of MODE. So those locks stayed until the first ONCE was spent, and then every lock on slot 23 of the track went, **any lock of the reduction made since among them**. On the unit since the srr image's first build; not reported. The stay image looks at both sets of bytes at every message, and `once_clean` is in a run of its own (`0x401a04c2`, 244 bytes) for room.
- Shown in emulation, stock's fragment of the step routine run as it is with each caller's fifth argument: a ONCE on the first step, and on another, stays through three passes of the caller that brings a track up to date and its event still holds the lock; the sequencer's pass spends it and the main task takes it off; ON and OFF are as they were either way; a track's ONCE waits for the sequencer, on a step with locks and on one with none; registers and stack kept; old locks of MODE go at the next message with no ONCE spent, and a lock of the reduction made after stays. Section 3 differs from the gear image's second build in the two runs and three operands; section 7 not at all; the gear image rebuilt to `5ef3a04c` with the other session's uncommitted prof work in the tree.
- **Only the unit can show: which caller plays the first step when the sequencer is started.** If the start's own pass is the only play of that step, a ONCE on the first step records at the start and is spent a pattern later: two takes.

## A take that sounds thin and pops: what was read (2026-10-13, section 3 of OS 1.42)

The maintainer: takes of a track or of the main mix are "a little bit thin", have "occasional pops", less bass "especially out of the analog tracks", "almost like there's some filtering", heard right after a take (so not the save). Read only, nothing built, nothing run.

- **No filter of ours.** `engine/feed.S` is a gain (none at 0 dB), rounding to 16 bits and dither. Nothing in it depends on frequency.
- **An analog track's channel of the frame is not its analog output.** CONFIRMED by reading: `0x4008ec34` calls `0x4008e9f0` on each of the four voice buffers at `0x80003950` with twelve bytes of state a voice (`0x43bd863c`) and the track's parameters: a state machine of an attack, a hold (480,000 frames at 127), a decay and a short ramp on a trig. That is the amp envelope made again in numbers, so the converter's tap is before the analog amplifier. The frame's channels 10..13 are those buffers as they are (`0x4008feee`): SRC on an analog track takes that copy, before level and pan.
- **The main pair of the frame is a sum made in numbers.** `0x4008fb7c` adds the eight input buffers into `0x8000ded0` with gains a block (`0x8000e0d0`, `0x8000e0f0`, made in the 12-track loop at `0x4008f3ac`), and `0x4008fbf2` copies that to channels 0, 1. INFERRED: the converter's own stream is made after it from other buffers (`0x8000dad0`, `0x8000dfd0`, `0x4008fc4e` on). So SRC on the main mix holds the analog tracks as their copies at the mixer's gains, never the analog sum that is heard. Whether a copy is as loud and as full as the analog path cannot be known here: no converter data in emulation.
- **The pops: the multi image gave up the ring's slack.** A block of a take is there for one mixer call. INFERRED from "How the two CPUs take turns": the edge is made by an interrupt of its own (`0x400a2058`), the feed by the per-block routine after its mixer. If that routine runs late twice between two of the audio CPU's interrupts, a block is written over before it is taken: 32 frames gone, a step in the wave, loudest on a low steady note. Up to the alock image eight blocks could wait.
- Not known: whether he heard pops before the multi image. Not measured: anything. A take of a steady tone pulled off with Transfer would show both (a step every lost block at a multiple of 32 frames; the level of the low end against the source).

## The profile kept, behind a switch: the prof image on the stay image (2026-10-13, section 3 of OS 1.42)

On request `engine/prof.S`, `engine/recfeed.c`, `engine/recpage.c` (PROF); `tests/test_prof.py` (10); `make image-prof` (`f0a8d804...`), on the stay image. **In `build/flash_this/`. Emulation only. Main CPU only.** The prof image another session built on the gear image (`bb417da0...`) is not kept.

- **A level of the chain now**: the stay image with the profile, and every image after has it (`tools/build_main.py`: from level 11 on).
- **Off until asked for.** As a tool it took SRC's last source for good. Kept, it would have cost the sends as a source, so a long after the record (`prof_on`, 0 in the image, so 0 at every start) says whether the last source is the record: the sampling page's last knob sets it to the right and clears it to the left, through stock's knob routines as the page's others, and the page's last box reads PROF while it is set. Off, the feed's block for a track on the last source is the stay image's, to the bit.
- **What is always there, on or off**: the per-block interrupt goes through the profile's two ends and three readings of the timer are taken in the mixer's call, about 40 instructions a block, and the record is made afresh. That is the price of having it in every image.
- Shown in emulation: the eight things the tool's test held, on the stay image (a track on the last source takes the record with the profile on; the others their sound); with it off, the window is the stay image's and is read and written the same; the last knob switches the long and the box says so; section 3 differs from the stay image's in the profile's run, the feed's, the interrupt's first two instructions, the mixer's call and the page's runs; the stay image rebuilt to `01d7363b`.
- **Only the unit can show, and it is the first flash to carry it: that the interrupt runs through the hook** (a hang at the first block if the chip's frame is not as read). The way back is the stay image, `build/images/Syntakt_OS1.42_sampler_stay.syx`, the same without the profile.
- **The on request.** So the lost block is not the cause: a take of the external input crosses the same way and is clean. The fault is in what a track's channel holds. Read after it: `0x4008ef42` multiplies the main pair by 8 (`0x4008fbd8`) and nothing does that to channels 2..13, so a track's take is 18 dB under the same track in the main pair before its level: about 13 of a take's 16 bits at 0 dB of record gain. The clicks are not explained. Suspected for an analog track: the envelope made in numbers starts again at a trig on a wave that never stopped. Asked whether a digital track's take clicks too: "seems like only the analog ones sound bad". So it is stock's copy of an analog voice, in a track's channel and in the main pair alike, and nothing of ours. And of stock over USB, from memory, not tried again: "I feel like I tried it with overbridge, and it sounded like shit." It fits the frame being what USB carries; still not traced. For an analog track or a main mix with one in it: the phones' output into the external input, SRC on the external input.

## A take's start faded in: the soft image (2026-10-13, section 7 of OS 1.42)

On request.

- **The cause, read:** `fade_on` fades a note in only when it starts inside the sample (STRT off 0, or LEN short of all backwards). A take begins with the block that is waiting when its note starts, wherever the source's wave is, so a note at STRT 0 goes from nothing to that frame at once. INFERRED that this is his click: no take of his was looked at.
- **Built** (`make image-soft`, `20f3d6b6...`, on the prof image; audio CPU only, section 3 the prof image's): `soft` (`engine/sampler.c`, under SOFT), called at a note's start after its slot is entered. If the note's first frame is past `SOFT_MIN` (128 of 32,768) on either side and no fade in is on, the gain starts at nothing and goes up a 64th a frame, the same two fields `fade_on` sets for a cut. 80 bytes in SY SWARM's room (718 of 1,264 used).
- **128** is my number: a step under it is 48 dB under full scale. A hit recorded from its start begins in the source's noise, far under it.
- CONFIRMED in emulation (`tests/test_soft.py`, 9): a sample that begins at or under the limit is the srr image's sound to the bit; one that begins loud, on the left, the right or both, is nothing at its first frame, a line of a 64th a frame, and the srr image's sound from frame 64 on; section 7 differs from the prof image's only in the sampler's runs, section 3 not at all, the prof image still `f0a8d804...`.
- Not done: the reference model (`emu/sampler_ref.py`) does not have it. The test holds the engine to the srr image's engine, not to the model.
- **Only the unit can show:** that the click is gone, and that nothing that should hit hard is dulled (a loop cut tight on a drum that starts loud is faded 1.3 ms now: STRT cannot switch it off).

## A take's sources read before the mixer: the pre image (2026-10-13, section 3 of OS 1.42)

On request (recorded and not heard). Offered: taps before the mixer for the digital tracks and the FX track's return, the FX track's mute made one, a track's take no longer following its LEVEL and AMP VOL. "yes do this".

- **A correction.** The entry "A take that sounds thin and pops" has the frame's channels 2..9 as the tracks' buffers "as they are". They are copied from those buffers at the mixer's end (`0x4008febc`), but his meter going dark under a mute, which is only a volume of 0 shown to the mixer (`engine/mixlink.c`), says the mixer has put each track's level into its buffer by then. INFERRED from the unit: where in the mixer was not read.
- **Built** (`make image-pre`, `ddb8ae7a...`, on the soft image; main CPU only, section 7 the soft image's). `mix_rec` (`engine/recfeed.c`, under PRE), before it calls down to the mixer: which tracks record is worked out first; the buffer of each digital track that is a take's source or the meter's (`0x80003d50 + 128 t`), and the return's two (`0x80003950`, buffers 6 and 7), are copied into a frame of ours (`PRE_FRAME`, `0x4556b000`, 32 x 20 longs in the memory nothing names, a channel where stock's frame has it, so `engine/feed.S` is as it was); `chan` hands those sources from there. Only what is asked for is copied.
- **The FX track's mute.** Bit 12 of the global mutes or of the pattern's: after the copy, the return's two buffers are taken down over a block (a 32nd a frame), are nothing while it lasts, and come up over a block. Whether it was muted the block before is the first long of the frame of ours. That memory is not cleared at a start: whatever it holds costs one block coming up.
- **The return is copied after its level** (`0x4009580c`, which runs before the mixer link), not before as first offered: the mute was what he asked for, and how loud the return is before that routine was not known.
- Room: the copy and the mute, 222 bytes, are a run of their own, `0x401bf7fe..0x401bf8dc` (named by nothing; a first choice, `0x401beb58`, was refused by the build: four bytes of the program read as an address in it). The rest is in the profile's run.
- CONFIRMED in emulation, the mixer a stand-in (`tests/test_pre.py`, 17): a take of a track or of the return is made from the buffers as they were before the mixer, whatever the frame holds; every other source is the frame's and the window the prof image's to the bit, with the same reads and writes; only the channels asked for are copied, none with the page shut and no take; the return under a mute, global or the pattern's, goes down, is nothing and comes up, the other inputs not touched, its take whole all the while; the meter reads the copy; section 3 differs from the soft image's only in the feed's runs, the copies' run and the mixer's call; the soft image still `20f3d6b6...`.
- Not counted: what the copies cost a block (32 longs a channel asked for; 64 more multiplies while the return is muted).
- **Only the unit can show:** that a muted track now meters and records; how loud a track's take is (it is before LEVEL and AMP VOL now, so lower at his settings or higher, the record gain sets it); that the FX track's mute is heard (it is if the return reaches the outputs through the mixer alone); that muting it does not click.

## A one-shot's end faded out at full LEN: the tail image (2026-10-13, section 7 of OS 1.42)

On request

- **So the click is at the take's end, not its start**, heard at the bar's next trig. Read: `fade_on` and `walls` call a one-shot's far end a cut (`fwall`) only when it is inside the sample; at LEN full the note stops on the sample's last frame at once, and a take's last frame is wherever its source was. LEN one value down puts the end inside the sample, and the fade out that was always there runs. The soft image's guess (the start) is not shown to have been wrong or right by this.
- **Built** (`make image-tail`, `651975f3...`, on the pre image; audio CPU only, section 3 the pre image's): under TAIL a one-shot's far end is a cut wherever it is, in both places. Two lines; the code is shorter.
- Not asked of the last frame whether it is loud, as the soft image asks of the first: a fade over frames that are near nothing changes nothing to hear, and the end of a sample is a stop either way.
- CONFIRMED in emulation (`tests/test_tail.py`, 3): a one-shot at full LEN of a sample that ends loud is the soft image's sound up to the 128 frames before its end, a line down from there, nothing at the end; with LEN short of all, and in a loop, the soft image's to the bit; section 7 differs from the pre image's only in the sampler's runs; the pre image still `ddb8ae7a...`.
- The model (`emu/sampler_ref.py`) does not have it.
- **Only the unit can show:** that this was his click.

## The profile made finer before the mixer: the lap image (2026-10-13, section 3 of OS 1.42)

The first profile from the unit (the hardware log, the same day) has the per-block interrupt at 93.1 hundredths of a block and 49.7 of them before the mixer. P read 72 on that pattern; with the pattern made lighter, to a P of 50, "the lag still seems to be there". So the wait for the audio CPU's buffers is not shown to be that half, and nothing else says what is.

- **Built** (`make image-lap`, `0d5e8cf6...`, on the tail image; main CPU only; a tool). Five readings of the profile's timer into the record's places for the first five longs of the stopped stack (+ 36 to + 52), which the interrupt's start has filled by then: at the per-block routine's first call (`right_begin`), on either side of stock's wait (`0x400a20ae`, called in a stub of ours in front of `right_mid`, which calls it again with nothing left to wait for), and on either side of our last call before the mixer (`right_end`). The stubs are a run of their own, `0x401be95c..0x401bea14` (named by nothing).
- **The reader** (`tools/prof_read.py`) tells such a record by the five being in order between the interrupt's start and the mixer's call in nine blocks of ten, gives the six parts under "before the mixer", and looks for a caller in the one stack long left.
- CONFIRMED in emulation (`tests/test_lap.py`, 6): the readings land in their places in order and the rest of the record is not touched; the right channels, the state and the answer stock tests are the tail image's; the reader's parts add up to the whole and a plain record is read as before; section 3 differs from the tail image's only in the transfers' runs, the readings' run and three calls; the tail image still `651975f3...`.
- Nothing of the real interrupt or the real wait runs here.

## The filter's envelope is the main CPU's (2026-10-14, sections 3 and 7 of OS 1.42)

Checked for the transient trigs before anything was built, by his two checks. **The first fails as it was put: the multimode filter stage on the audio CPU has no envelope.** Nothing built.

- **The audio CPU never has the envelope's knobs.** Its interrupt copies the window into `0x80008000` (`0x40000934`, `0x1b0` bytes) and from it fills each track's params (142 bytes a track at `0x80003c40`): + 62 to + 81 (a machine's ten words), + 82 (TYPE), + 86 (RESO), + 102 and + 104 (BASE, WDTH), + 108 to + 116, + 128, + 130. Slot s of the Filter record is at params + 62 + 2 (s - 17): FREQ + 84, ENV + 88, DEL + 90, ATK + 92 to REL + 98, FENR + 100. None of ENV to FENR is written, and nothing in section 7 reads them. READ.
- **The trig `STAGE_FILTER` is handed** (`0x4000219a`) only sets the track's flags at `0x80008550` (1) and `0x80008558` (0), the filter's memory to be cleared. READ.
- **The cutoff crosses as one long a track** (window `0x188 + 4t`, `0x80008188` on the audio CPU), made on the main CPU each block by `0x40095734` (params + 82, ..., track) from FREQ, ENV and the envelope's value (`0x400966c6`, the long at `0x43bdd0a0 + 12t`), and written at `0x400a4de0`. READ.
- **The envelope runs on the main CPU: `0x400965a4` (params, trig mask, release mask, a mask of tracks to skip in its low byte), called once a block at `0x400a4ccc`**, eight tracks, 12 bytes a track at `0x43bdd09c` (state, value, a delay count). On a trig: state 3 (the delay) if DEL is not 0, else 2 (the attack), the count cleared; FENR not 0 also clears the value. Its own code, no calls. **CONFIRMED in emulation** (the routine run alone, MACSR 0x20 as the code before it leaves it; ATK 10, DEC 64, SUS 0, REL 64): a second trig 40 blocks after the first puts the track back in its attack **with FENR off**, from the value it had (33,266 of 65,535 by the top half); with FENR on, from 0; with DEL 20, into the delay, its count up by 32 a block. Track 1 with no trig is not touched. **So FENR does not have to be on for a hit to start the envelope again; on, the hit starts it from nothing.**
- **The trig mask handed to it (`a5`) is the one the loop just before uses** (`0x400a4c88`, 13 entries of 32 bytes, not read further). A hit is to be ORed into the argument at `0x400a4cc8` alone (the jsr at `0x400a4ccc` taken by a routine of ours), not into `a5`.
- **DEL on the main CPU** is read by `0x400965a4` at a trig and in the delay state, from the params it is handed. Taking it over on a sampler track means our routine reads it there and puts 0 in its place for the call. NOT LOOKED AT: whether anything else on the main CPU reads params + 90, and whether that block is made again every block (if not, the word is put back after the call).
- **What this changes in the plan.** The hits are passed where the sample plays (the audio CPU) and the envelope is restarted where it runs (the main CPU), a block or two later (0.7 to 1.3 ms). That needs 8 bits a block from the audio CPU to the main CPU, and DEL's value a track the other way for the scan's threshold. The window has no room known for either. Not designed further. **Since (the same day, the next section): the window's long at `0x5b4`, and how loud each hit is crosses in it, so DEL is applied on the main CPU and nothing crosses the other way.**

## Hits that start the filter's envelope: the hits image (2026-10-14, sections 3 and 7 of OS 1.42)

By on request (P's neighbour in the window, the time image's C, was taken; P stays). Built: `make image-hits`, on the lap image. Both CPUs. Emulation only. **First build** `34f583f1...` (never on the unit): forward only, in SY SWARM's run and the first run. **Second build** `addd69788ab15fc3a0317dc1fb575d432903d434e3909bf43db760c71a37cc08`, by on request: in SY TOY's and SY BITS's code, and a hit played backward is said at its end. **On the unit after the first build, it said no hit at all** (Hardware log, 2026-10-14). **Third build** `27af79e29017f981a5a43c09d2b5c5c371d98ab66af7219ce9a25d71aee920e4`: a list another build left is not believed. `tests/test_hits.py` (16). The design: `docs/SAMPLER.md`, "Hits that start the filter's envelope"; `engine/sampler.h`, HITS; `engine/hits.c`.

- **The window's long at `0x5b4` is free on every image after the time image.** The time image's routine writes C there and P at `0x5b8` every 256 blocks; the sampling page reads C only on the time image (`engine/recpage.c`, `timed`, under TIMED), P on every image with PEAK. READ. On the hits image the routine no longer writes C (`engine/stub.S`, `timed_say`), and the sound engine writes four bits a track there at the end of every interrupt, after the right channels' long (`hits_block`, called from `sampler_amp` in place of that long's write). Held: in 270 interrupts the long never reads C, and P is said at `0x5b8`.
- **The main CPU's call of the envelope at `0x400a4ccc` goes to ours** (`hits_env`, `0x4012d408`, in a run of 552 bytes nothing reaches and nothing names). The trigs it hands on are the call's argument alone: what the loop before it, the amp and the sound engine are handed is not touched. On a sampler track (the type word at + 62, which stock writes into the block at `0x400a4c4a` before the call) DEL's word is put at 0 for the call and back after it. **CONFIRMED in emulation, stock's envelope run under ours:** a hit DEL lets through leaves all eight envelopes as stock's own trig on that track with DEL at 0 does, to the bit; a stock trig on a sampler track with DEL at 40 goes to the attack, on another machine's to the delay; a hit with a stock trig is the trig; the block is as it was after the call. 252 instructions more than stock's call with six sampler tracks on DEL.
- **SY TOY's and SY BITS's code is free** (engines 8 and 9: updates `0x40008ae8` and `0x40008e0c`, renders `0x40008d58` and `0x400091e0`, each named once in the section, by its table). `tools.deadcode.survey` on stock section 7 with entries 10 and 11 zeroed, then 8 to 11: one more run, `0x40008ae6..0x400096e8`, named by nothing, holding words that are not instructions; with SWARM's render after it, all of `0x40008ae8..0x400097dc`. Ours from `0x40008ae8` to SWARM's update, 2,052 bytes; the two engines are handed SWARM's stand-ins. Held: a track on either plays nothing on this image and sounds on the lap image. Three smaller runs grew too (helpers only these machines name, merged with ours): not counted, not used.
- **The scan** keeps, of a sum of kicks, hats and a bass at -21 dB, the hits a model of it keeps, to the frame, the step and the end (kicks 14, hats 13 and 12; the first kick ends at 4,032, the others where the next begins, the bass keeping them within 24 dB), of a 30 Hz sine its start alone, and of two hits that die away in silence their ends at 288 and 5,088 frames. A slot whose frames change in place, same address and length, is gone over again by its print. CONFIRMED in emulation. **Found on the way:** a hit's end taken as the first window 24 dB under its loudest ended a kick at 480 frames, where a window of its low body sat on a crossing; the end is now the last window within 24 dB, found once a follower falling 0.56 dB a window is under that.
- **The pass**: at a sample's own pitch, 12 up and 7 down, a voice says every hit but the one its note starts on once, in the block where its frame plus two blocks of its travel first reaches it, and nothing on the tracks that play nothing. Backward (SMPL's reversed half), at its own pitch and 12 up, it says each hit at its end, the last hit first, in the block where its place less two blocks of travel first reaches the end. A loop of the whole sample says its start in the block each turn begins in, and its middle once a pass. CONFIRMED in emulation.
- **Nothing of the sound changes**: eight stereo voices looping through the whole interrupt, at two pitches, both sides of every track are the lap image's to the bit.
- **What it costs the audio CPU's interrupt, eight stereo voices** (against the lap image's, the same blocks): at their own pitch at most 3,243 more, 882 once every slot is gone over; pitched at most 3,145, 2,102 while a slot is gone over; the heaviest interrupt 80,559, stock's heaviest machine 117,348. The first build was about 300 less at the most (forward only). Room left: 752 bytes in SY TOY's and SY BITS's run; SY SWARM's run and the first run as the lap image left them (546 and 382); 4 in the time image's.
- **INFERRED, not timed, and only the unit can show it:** that a hit said two blocks before the playhead reaches it is played on it (the main CPU reads the long a block after it is written, and its cutoff is the audio CPU's the block after that, by the order the two CPUs run in: "One-track stereo: the stereo image", how the two CPUs take turns). And that DEL, a lock of it and an LFO on it reach the block the envelope is handed as any knob's do: the block is made by stock, not run here.
- **Not done:** the knob still reads DEL (its name is every machine's); the slices and their switch; the FX track's mute of the pre image, still in.
- **On request.** On this image it is: stock's envelope is handed DEL at 0 on a sampler track every block (held above: a stock trig there goes to the attack, not the delay). On the lap image, which the status page has on the maintainer's unit, DEL is stock's. Asked which file he heard it on.

## The filter pages on a sampler track: the hitui image (2026-10-14, section 3 of OS 1.42)

By on request (the delay he took to be still there was stock's picture, which reads DEL; the hits image does not wait). Built: `make image-hitui`, SHA-256 `79615c016b6916d234ae460310b40954b4b00f0b716b26afe67f3d10533b9be3`, on the hits image's third build. Main CPU only. Emulation only. `tests/test_hitui.py` (21). `engine/hits.c`, HITUI.

- **The filter page's class is `0x401c9da0`** (installed by its constructor `0x4004217c`, called for a page object of `0x1a0` bytes with key `0x15` at `0x40035a5e`, for the list of pages 9 and 10 at `0x401c821c`). Its draw (`0x4004291c`) asks the page's number (method + 136): 7, 9 or 11 go to a FLTR1 loop of its own (`0x400424fe`), 10 to a FLTR2 loop (`0x40042264`), the rest to the base draw (`0x4003a244`). Its turn is the base turn routine (`0x4003b870`). READ.
- **A knob's name**: the base draw and both loops take it the same way, the record from method + 188 and its short name at + `0x30` of its 52 bytes in the descriptors (`0x4022d83c`), drawn by `"%.5s"`. DEL is record `0x3f`, the first knob of FLTR2, shared by every machine. In FLTR2's loop the 28 bytes at `0x4004232e` go to `hit_short`. READ; run in emulation.
- **The pop-up's name**: the base turn routine takes it from the knob's holder (its method + 88), or for records 498 and 502 from `0x40012b24`; both ways join at `0x4003bc28`, which goes to `hit_popname`. READ; run in emulation.
- **FLTR1's picture of the envelope**: its loop asks the values of ATK (`0x40`) and DEL (`0x3f`) of the routine in a3 (`0x40039160`, page, record, a flag), the analog page's of `0x8a` and `0x89`, and hands both to `0x40039cf4`, which draws the first segments. The call of DEL's value at `0x4004268a` goes to `hit_deldraw`. READ; run in emulation.
- **Held in emulation**, stock's instructions run around each place from where it sets its stack up to past the call: on a sampler track DEL's record is named HITS in both places and its value for the picture is 0; any other machine, any other record and the analog page are stock's; the stack and d2 to d7 and a2 to a6 are as stock leaves them. Stand-ins: the active track and its machine (as `tests/test_page.py` has them), the holder's name method, the value routine.
- **Only the unit can show**: that the pages look right. NOT LOOKED AT: the LFO's list of destinations, which may still name it DEL; a lock's pop-up, which is taken to be the same pop-up.

## The file protocol, for the phone (2026-10-14, section 3 of OS 1.42)

On request, for an iPhone app that is the library of projects and sample banks: a project loaded with the phone connected brings its bank from the phone, else from the drive; a save goes to both. The first piece: the protocol Transfer speaks, so a program of ours can speak it. `tools/rpc.py` (bytes only, no port), `tests/test_rpc.py` (25). The app's code is in `the phone app's repository`, outside this repository, checked against frames made by `tools/rpc.py`.

- **The parser** (`mm.RPC_PARSE`): an id byte, less 1, through a table of 223 word offsets (`mm.RPC_TABLE`); an unknown id goes to `mm.RPC_NONE`. Each case builds the request's object. CONFIRMED by the RTTI names (`N8elektron..MidiRpc<Name>RequestE`), their type records and vtables, the case's constructor storing the vtable: 0x01 ping, 0x02 software version, 0x03 device UID, 0x53 to 0x5e the data files (list, read open, read partial, read close, write open, write partial, write close, move, copy, clear, swap, rename), each with its response at id | 0x80. 0x5f sets a file's tags; 0x60, 0x6f and 0x7f go nowhere (tried). Between 0x10 and 0x47 are the sample and raw filesystems' ids, mixed: not used for the Syntakt by any sender known.
- **A data file** (a project, a sound, a sample) is a header of 31 bytes (magic `0xac11d303`, version 2, family 8, device 13, the OS (`"0097"` on 1.42), the type, -1, the index, the payload's size, packed or not, the footer's size), the payload, and a footer of 12 (the crc of the payload, **the payload's size**, `0xaaa1daaa`). The crc is zlib's crc32 begun at `0xffffffff`, the same for each written block. Elektroid writes 12 for the size: what the unit writes was read off it (below). The two magics are immediates in the unit's code (`mm.RPC_FILE_MAGIC_AT`, `mm.RPC_FILE_TAIL_AT`). A sample's payload is the slot's own format, 'SAMP' and the frames at + 8 and the name at + 12, which is what the store reads (`tests/test_sample_store.py`). CONFIRMED for the magics and the layout; the rest of the header's fields as Elektroid writes them, not traced in the unit.
- **The frame and the message**: `f0 00 20 3c 10 00`, the message 7 bits to a byte (the 7 high bits of 7 bytes first), `f7`. A message is the sender's number (2 bytes), 2 bytes (in a response the request's number), the id, the arguments; a response's fifth byte is its status, 1 good. Blocks of 8 KB, each written block with its crc32. FROM Elektroid (GPL, read in `ref/elektroid`, not copied), which has done this with Syntakts since its Syntakt samples were merged; the framing itself is not traced in the unit.
- **On the unit (2026-10-14, the lap image, by `slink` from his Mac, run by Claude with on request, read-only):** a ping answers in 2.2 ms with the device id 30, the 22 ids it answers (`01 02 03 04 06 07 09 50 52 51 53 54 55 56 57 58 59 5a 5b 5c 5d 5e`) and "Syntakt"; a ping's response has no status byte. `/` lists `projects/ soundbanks/ samples/`; `/projects` his nine; `/samples` the loaded bank's slots by name and size. **A sample is read at 188 KB/s** with no rest between blocks (a slot of 384 KB in 2.0 s; a small one 151 KB/s); a project, packed by the unit, 86 KB in 2.3 s (36 KB/s). A slot's file read back and made again by `tools/rpc.py` from its name and frames is the unit's to the byte: so the file a write sends is the unit's own form.
- **A write, on the unit (2026-10-14, the hits image, on request)**: a 3 s tone, 144,001 frames, into the empty slot 53 at 179 KB/s, read back at 272 KB/s, the WAV the same to the byte. **The footer goes as a block of its own after the rest**: sent inside the last block, every block is taken and the close is refused, "Footer was not processed", leaving 43 bytes (the header and the footer) in the slot until the next good write. Elektroid does the same, a block a part. Slot 53 holds SLINKTEST until he clears it.
- **What that makes a bank from the phone:** his loaded bank, 36 slots and 9.3 MB, about 51 s at that rate; a full one of 64 MB about 6 minutes. So a bank at a project's load is a wait when the drive does not have it, and the drive's copy is what makes the next load quick.
- **The drive caches three banks, not more.** Banks are 64 slots of 1 MB since the big image: A, B and C run to 196 MB, and the room found free ends at 244 MB (48 MB). Said otherwise in chat the same day ("about 7"): wrong.
- **How the unit answers (2026-10-14, READ):** incoming SysEx comes to `mm.RPC_SYSEX_IN` (interface 2 or 4), which takes the header and the `f7` off and jumps to `mm.RPC_HANDLE`. That decodes, dispatches (`mm.RPC_DISPATCH`, which calls the parser) and sends the response (`mm.RPC_SEND`) **in the same call**: no queue, on whatever task delivers MIDI in (not traced). The send writes `f0 00 20 3c 10 00` from `0x40242725` through the sink's vtable + 16, the packed message, `f7` from `0x40242724`, then commits through + 12. The sink (`mm.RPC_SINK`) is a static made at the first message (guard `mm.RPC_SINK_GUARD`). **So a frame of ours can follow any response through the same sink, on the same task**: the way the unit can tell the phone of a load or a save, the phone pinging while it is open. Not built.
- **The project list does not mark the loaded project** (read off the unit, `slink raw-ls /projects`): each entry is name, 0, 2, its number, size `0x400000`, operations `0x007e` (PRESETS `0x0012`), 1, 1, the same for all eight others. So the unit has to say which one it loaded.
- **What `/samples/<slot>` writes is the loaded bank's slot** (the bank image's three routines, as Transfer's always was), heard after the next start as before. The load image's loader does it at a project's load.

## Pitched notes and loops for less: the trim image (2026-10-14, section 7 of OS 1.42)

The maintainer, 2026-10-14: P "up to 100 at times", "its when i pitch things", "and loops to actually just not as much"; a pattern at 85 with nothing pitched reads 100 pitched. By on request (of the ways offered). Built: `make image-trim`, SHA-256 `c2698c82145a0cabcfb6ec86dfd85f525ddf7f4a7c0a346d5971dea0fc067f56`, on the hitui image: section 7 alone differs from it (compared section by section). Emulation only. `tests/test_trim.py` (8). `engine/sampler.h`, TRIM.

- **What pitch costs, from the counts already kept:** a frame at a sample's own pitch (or octaves up) is the sample's own; any other is the sum of twelve, 102,615 against 76,674 instructions for eight stereo tracks (`tests/test_lean.py`), about 22 of P. The sum was already the MAC unit's (`hq_run`, four multiply-accumulates a tap for both sides and both rows, the loads in them), so nothing was there for the taking but its two clears a tap. And the images since the time image's 85 (srr, hits, soft, tail) took about 6 of P between them.
- **The sum's frames with the next in their low half** (`engine/stub.S`, HQ_TAP and the first two loads): a frame is fetched as a long and its low half, the frame after it, is no longer cleared. The low half times the table's number is 2^-16 of the sum's units: off by at most what a row's numbers add up to, about a step of a 16-bit frame. **The 16-bit multiply offered was not built:** the word forms of the MAC unit are not run by stock and the emulator does not model them (`emu/emac.py` raises on them), so a model of ours would be the only check. This is the same count with every instruction one stock runs. Measured, eight pitched stereo loops for two notes: 91,586 of 92,160 frames off, the most 0.093 of a step, the mean 0.028, after the stages.
- **The fade** (`fade_run`, `engine/stub.S`): (x >> 13) times twice the gain with its low four bits cleared is (x >> 13) times the gain, 3 dropped and 4 put back, to the bit modulo 2^32; and the gain is held only after the frame worked out once a run ((4095 - gain) / step going up, gain / -step going down, one divide). 13 instructions a stereo frame where it was 23, 8 a mono one where it was 14. **The hits image's frames, gain and step to the bit**, 200 runs of each kind, a gain already at 4096 too (never handed it by play, held anyway).
- **A loop's blend kept from note to note** (`blend_key`, `xset`, in the hits image's run): the key, made once the blend is all written, is the slot's two places, its length, the way it plays, `TRIM_FORMAT`, and 8 frames of each place the blend is read from, each side. A note's start still sets the count to 0; the first block its seam is worked out, a seam that is the one written with the slot giving the same key has the count at once. A blend begun again has its key at 0 until it is whole. **CONFIRMED in emulation:** at a sample's own pitch, eight stereo loops cut three ways, trigged every 90 blocks, the sound is the hits image's to the bit; with every slot's frames made new before the second and third notes, still, and the blends are written again; the second and third notes have their blends the block their fade in ends, and they are the hits image's to the byte. **INFERRED:** that no take, load or start leaves a slot with those 32 frames, its places and its length as they were and the rest changed.
- **What it costs, eight stereo loops cut out of their samples, the second note** (instructions, the hits image's less this one's): pitched, its trig's block 6,120, the fade in's two 8,224 and 8,424 (the heaviest block, 117,008, is 108,784), the block the blend is taken back 5,696, the 43 it was written in 8,272, a steady one 6,144. At its own pitch: the fade in's two 2,272 and 2,280, the written ones 2,114, and the block the key is made 448 more (56 a voice), the one block that is. By the meter's old reading (116,679 read 99), 6,144 is about 5 of P steady and 8,224 about 7 at the heaviest. **A count, not time: only P on the unit says.**
- **Room:** the hits image's run (SY TOY's and SY BITS's) has about 140 bytes left of 752: `xset` moved there from the fourth run, and the fade from Twinshot's. Their old places are not counted.

## The pitched sum's tests once a run, and DEL does not reach the audio CPU: the slim image (2026-10-14, section 7 of OS 1.42)

The maintainer, 2026-10-14, after the trim image on on the unit, and of the ways offered, "do hits off when unused, and tightening the pitched sum". Built: `make image-slim`, SHA-256 `c8f8744269a8b1e27970f94fea344e696ec50f062824690f644660510ee8b425`, on the trim image. Emulation only. `tests/test_slim.py` (10). `engine/sampler.h`, SLIM.

- **DEL does not reach the audio CPU. CONFIRMED** from the rig's packing of what crosses (`emu/engine.py`, `host_block` and `HOST_FIELDS`, as stock's interrupt unpacks it): a track's type and its machine's ten words (slots 17 to 26), and of the rest only the words at + 82, 86, 102, 104, 108, 110, 112, 114, 116, 128 and 130. DEL is slot 31, + 90. A first build read it there and every track's hits were off: the test with bursts as samples said none where the trim image said four. **So "hits off where DEL is 0" was not built.** The way left: a bit a track from the main CPU in slot 24's word, whose low byte the feed and the audio CPU's take read as the source; every reader would have to mask it. About 600 to 900 instructions a block once the slots are gone over, and up to 1,500 while one is. The maintainer's word wanted before that path is touched.
- **"Every word of every track" in the block built at `0x400979ca`** (an earlier section) is the main CPU's block; what crosses is packed from it. Read that line so.
- **The pitched sum, two channels** (`hq_run`, `hq_safe`, `hq_rearm`, `engine/stub.S`): once a run, by two unsigned divides, the frames on from this one inside lo and span and with all sixteen in the slot (going up (span - past - 1) / step and ((whole + 7) << 12 - pos - 1) / step, going down past / -step and (pos - (7 << 12)) / -step, the least, and this one), kept in the run's n. Those frames are made with neither test, a decrement and a branch in their place, and the next frame is begun at the end of the sum, not by a branch. A frame found inside the slot by the tests (a run begun within reach of the slot's start) counts again from the frame after it. A step that lands on the sample's own frames only (its own pitch, octaves up) is bounded by lo and span alone. Runs of one or two frames are not counted. Fewer than the true count is no harm: the rest are tested as before.
- **One channel is the trim image's**, step for step: its run (`.cave.y`) has no room for the count's entry, and the stub tried in Twinshot's other run cost a note's first block more than it saved (the start zone, with no room for the recount).
- **CONFIRMED in emulation:** the sound is the trim image's to the bit, eight tracks a few steps apart in pitch, stereo and mono, up and down, forward and backward, one-shot, loop and ping-pong, cut and not, own pitch (9 cases, two notes each).
- **What it costs** (the trim image's less this one's, the second note): pitched stereo, a steady block 1,432, the trig's 1,432, the note's first 624 from the sample's start and 1,384 cut out of it; at its own pitch 40 a block; mono 0. No block of any case is heavier. About 1.2 of P steady by the meter's old reading; a count, not time.
- **Room:** SY TOY's and SY BITS's run full (the count and the recount, 0 bytes left); Twinshot's other run as the trim image left it.

## A pitched frame summed from six: the six image (2026-10-14, section 7 of OS 1.42)

On request, told the cost is every pitched frame's (not at a sample's own pitch or octaves up) and the loss the very top of anything pitched and aliasing of bright material pitched up. Built: `make image-six`, SHA-256 `d7bd3348b0f3c127f06db339300592c91c83a63772ddddbafc6374ae8a7ce0dc`, on the slim image. Emulation only. `tests/test_six.py` (8). `engine/sampler.h`, SIX.

- **The table** (`tools/sinctable.py`, `rows6`): a sinc of six frames, i - 2 to i + 3, in places 5 to 10 of the sixteen, five noughts at each end, 32 phases, each row adding up to ONE. Stored as the twelve's were (the middle twelve numbers), so the copy made at a start, the frames around a slot's ends and the room are as they were; its magic is its own, so a start after the flash makes the copy again.
- **The window: Kaiser beta 5.0, not the sixteen's 8.0.** By the table alone, a sine pitched a fifth up, what is left beside it (dB under it), twelve then six: 1 kHz -92, -89; 5 kHz -77, -71; 10 kHz -78, -60; 15 kHz -53, -26. A fifth down: 1 kHz -87, -63; 5 kHz -78, -59; 10 kHz -74, -55; 15 kHz -53, -26. With the sixteen's window six taps left 10 kHz at -34 and 15 kHz at -20. Swept 1.5 to 8: 5.0 is the best at 5 and 10 kHz together.
- **The sums:** two channels take HQ_TAP 5 to 9 and the last (HQ_SKIP2 5); one channel eight places, the six and a nought each side, for its loop of four (HQ_SKIP1 4). **CONFIRMED in emulation:** at a sample's own pitch the sound is the slim image's to the bit (stereo, mono, backward ping-pong); pitched, eight tracks of noise are 34 dB from the slim image's.
- **What it costs** (the slim image's less this one's, eight tracks cut loops a few steps apart in pitch, the second note): stereo, a steady block 6,164, the heaviest 107,415 to 101,438, no block saving under 5,977; mono, 4,613 steady, the heaviest 71,234 to 66,760. About 5 of P steady by the meter's old reading; a count, not time.

## A pitched frame summed from eight, in six's place: the eight image (2026-10-14, section 7 of OS 1.42)

The maintainer, 2026-10-14, of the six image on on the unit. Built: `make image-eight`, SHA-256 `2970c773c2404f7ffb46a47d6015df1d8ae54a4b1049060dfb672cdba86ef24e`, on the slim image (not on six). Emulation only. `tests/test_eight.py` (8). `engine/sampler.h`, EIGHT.

- **The table** (`rows8`): a sinc of eight frames, i - 3 to i + 4, places 4 to 11, Kaiser beta 5.0, swept 4 to 8 for it. The gain of every table here (twelve, six, eight) is within 1.5 dB to 18 kHz, so what he heard of six is taken to be what is left beside a tone near the top, not a loss of level (INFERRED: the maintainer's word is "filtering").
- **By the table, a sine a fifth up then down, dB of what is not it, twelve and eight:** 1 kHz -92 -78, -87 -65; 5 kHz -77 -61, -78 -64; 10 kHz -78 -95, -74 -65; 15 kHz -53 -44, -53 -43. Pitched noise is 44 dB from the slim image's (six: 34).
- **CONFIRMED in emulation:** own pitch the slim image's to the bit. **What it costs** (the slim image's less this one's): stereo 4,101 a steady block, the heaviest 107,415 to 103,432, no block under 3,983; mono 4,608. About 3.5 of P steady by the old reading.

## A trigless step's solo, and the probe17 image (2026-10-16, section 3 of OS 1.42)

The maintainer: a trigless step's SOLO lock "doesnt work currentlty" (REC on one not wanted: "dont need trigless eec just trigless solo onoff"). Read, not run:

- **Stock's event loop writes a trigless step's locks where the solo is read.** Its per-track event code (`0x400a4414` on) calls the lock writer `0x4009792c` with `0x800021b0` for any event with a lock list at + 68, on the path that starts no note (no `0x400977d8` put-back, no `0x400a321a` load) as on the note's (`0x400a4774`). The writer copies every (slot, value) with no filter. So by the listing slot 17 of a trigless step reaches the word the analog mute reads (`engine/amute.c`, `solo_now`). What d7 at `0x400a42c4` (the event's + 36 & `0x81`) says of the event was not traced: which path a trigless step takes is INFERRED.
- So the cause is not seen. **The probe17 image** (`make image-probe17`, `303fcef0...`; main CPU only; a tool on the fltr image): the sampling page's fifth place reads S17 and the track's slot 17 in `0x800021b0`, the sixth NOW and this block's solos (`0x400a2938`, track 1 the lowest bit). `PROBE17` in `engine/recpage.c`, `tests/test_probe17.py` (2). What to look for on a trigless step locked to SOLO: S17 not 3580 (the lock never reaches the block), or 3580 and NOW without the track's bit (the mute's read), or both right and still not heard (the mixer link).

## The probe17 image on the unit, and the tlsolo image (2026-10-16, section 3 of OS 1.42)

On request.

- **So the lock is played and read as it should be: the fault was the page's.** `solo_steps` (slock image on) made a lock only where the step differs from the track's own solo and dropped it where it is the same. With the track's own off a step turned off got no lock, and a trigless step's ON holds until the track's next trig, so nothing could end it.
- **The tlsolo image** (`make image-tlsolo`, `8de0ec13...`; main CPU only; on the fltr image): a held step always takes the lock it is turned to, OFF (`1A80`) as well as ON (`3580`), on both kinds of track (`TLSOLO` in `engine/recpage.c`). A lock is no longer taken off by turning it back to the track's own; stock's ways of clearing a step's locks still do. `tests/test_tlsolo.py` (12), stock's lock routines run as they are. Only the unit can show that a trigless OFF ends the solo.

## Time stretch priced (2026-10-16, emulation, not built)

On request. Nothing of it is in an image. Counted two ways:
- The six image's whole interrupt, eight tracks trigged together (`tests/test_slim.py`, `render`): the heaviest block 101,438 stereo pitched, 89,613 stereo at its own pitch, 66,760 mono pitched; steady 92,529, 80,421, 60,927.
- Kernels in C (`-mcpu=54418 -O2`, no EMAC), a block of 32 frames, run by `emu.machine.Machine`: today's one head against two grain heads half a grain apart (1,024 frames, a window table summing to one), read raw, by two taps or by six; WSOLA a search of +-32 frames by twos over 64 frames by twos, left only, once a grain a head. The pitched case is +3 semitones, the stretch 0.8.

A voice a block, C: one head raw 270 mono / 367 stereo, two taps 592 / 880, six 1,197 / 2,192; two heads raw 953 / 1,212, two taps 1,947 / 2,688, six 3,388 / 5,469; WSOLA two heads raw stereo 1,868, two taps 2,688 to 3,115, six 3,784 / 6,345. C's six-tap stereo less raw is 1,825 a voice where the engine's pitched less own is 1,513: taken as one to one.

Eight voices stretched, added to the heaviest block, and the share of SY SWARM's 117,348 (0.99 of it read 99 on the unit, so about P):
- stereo at own pitch: 96.4k, 82; WSOLA 101.7k, 87;
- stereo pitched, both heads six taps: 127.6k, 109; WSOLA 134.6k, 115. **Does not fit**;
- stereo pitched, both heads two taps (a stretched voice only): 105.4k, 90; WSOLA 108.8k, 93;
- stereo pitched six taps on four tracks of eight: 114.5k, 98; WSOLA about 118k, 100. Does not fit;
- mono pitched six taps: 84.3k, 72.
Today's heaviest stereo pitched block reads 86 this way. Not counted: the cache, hand-written code (likely less than C), the knob's own reading. Code, in C: a two-head stereo voice 692 bytes by two taps, 1,284 by six, 1,890 by six with WSOLA; no room on the audio CPU without a machine's (SAMPLER.md, "Wanted, not built").

## The soloend image: a step's solo lock ends with its note (2026-10-20, section 3 of OS 1.42)

- **On request. Until now a step's solo lock (slot 17, the slock image) stayed where a trig's locks are written till the track's next trig.
- **Built**: `make image-soloend`, on the scratch image (level 48). Image `5fe05eab...`. Main CPU only, section 7 the scratch image's.
- **The call of the filter's envelope** (`engine/hits.c`, SOLOEND), handed the block's trigs and releases: `solo_gone` (first in the hits' run, `mm.SOLO_GONE`, twelve bytes, 0 in the image) gets a track's bit at its release and loses it at its next trig, a release and a trig in one block counting as the new note's. A mark in the lock block's slot 17 (`0x800021b0`, high byte) not there the block before clears the bit too: a trigless step's lock counts till the next release. Bits 0 to 7 only.
- **The solos** (`engine/amute.c`, `solo_now`, SOLOEND): a track whose bit is set is passed over, so its own solo (knob E) decides. `solo_now` is moved for this image into a run of its own (`mm.CAVE_SOLOEND`, `0x40116fe4`, 340 bytes nothing reaches or names, clean by `tools.deadcode.survey`): the alock image's run was 10 bytes short. **Its first build (`b147a7c1...`, and the eucl image's `1e15516e...` on it) used `0x40131954`, which survey calls not clean (a word that is no instruction, the scratch image's note): rebuilt the next day before either went on the unit.**
- **CONFIRMED in emulation** (`tests/test_soloend.py`, 10): the long through a release, a trig, both at once, a new mark with no trig; the solos with the bit set and not, ON and OFF locks, an analog track's lock untouched.
- **INFERRED**: that a trig's LEN reaches this call as a release bit (a take ends there on the unit, the recorder's `rec_step` reads the same mask on the audio CPU; this one is the main CPU's). LEN at INF sends no release: the lock holds till the next trig, as before. A trigless lock with the same mark as the note before it is not seen as new.
- **Only the unit can show**: the solo ending where the note does, a key held past LEN.

## The eucl image: SOLO and REC off the TRIG page's euclidean page (2026-10-20, section 3 of OS 1.42)

- **On request. A fault since the trig image.
- **Read**: the TRIG object shows two pages, 1 (or 2) and 3 (`tools/uitable.pages`): page 3 is the euclidean one, records 457 to 464 (E and F 460 and 461). The trig image's three methods (`trig_knob`, `trig_draw`, `trig_turn`) asked only whether the track is a sampler, never which page shows.
- **Built**: `make image-eucl`, on the soloend image (level 49). Image `26b1b67e...`. Main CPU only. `trig_sampler` (`engine/recpage.c`, EUCL, in the TRIG page's run): -1 when the page showing (+ 124 list, + 144 index, as FLTR2's test reads them) is 3, else `sampler`. The three methods go by it, so on page 3 every knob, the draw and every turn are stock's. A function, not a macro: the turn's run had 14 bytes too few for the test inline.
- **CONFIRMED in emulation** (`tests/test_eucl.py`, 8): page 3 every knob, the draw and every turn stock's, the solo untouched; page 1 E and F still SOLO and REC.
- **INFERRED**: that the TRIG object's page list is at + 124 and + 144 as the base page class's (FLTR2's on the unit). **Only the unit can show: the euclidean page's E and F back, SOLO and REC still on the first.**

## The norm image: every take normalized to -1 dB (2026-10-21, section 7 of OS 1.42)

- **On request; his choices: the take itself rewritten (not a playback gain), always on, -1 dB.
- **Built**: `make image-norm`, on the eucl image (level 50). Image `57a61c08...`. Audio CPU only: section 3 is the eucl image's.
- **How** (`engine/sampler.c`, NORM): `norm_block`, at the start of `hits_block` (the end of every interrupt), follows each running take's loudest frame from the block `rec_all` has just written (the block's two sides on a stereo place, the one buffer of a single slot or a mono take). A take that has stopped (its voice's `rec` gone) waits its turn; one at a time, its slot (and the next on a stereo place) is scaled by 2.14 gain `(29204 << 14) / peak`, at most 32 (30 dB), nothing done if it is not over 1, rounded, 256 frames a block from its start (`norm_scale`, ColdFire assembly). Once scaled, its KEPT marks are cleared, so a take kept before it was scaled is written again by the next save. Stopped: a take started over the slots (what is done stays), a slot that is no longer the take (a load).
- **The keep box** (`norm_keep`, in `sampler_post`'s place of `keep_step`): a request for the take being scaled, past what is scaled, gets no answer that block; the main CPU's `ask` waits (PATIENCE). A take that waits its turn is not held so: its KEPT clear covers it.
- **State**: `0x44078200` (free SDRAM after the slices' voices), believed only while voice 1's state + 80 holds `NORM_MAGIC`: stock's voice reset clears it at a start and when track 2's machine changes, which drops a job half done (the take keeps the level jump; INFERRED rare).
- **Room**: `norm_block` and `norm_scale` in SY TOY's and SY BITS's run (cave e), the peaks (`norm_peaks`) in the first run (cave x, 300 free before), `norm_keep` in SD BASIC's (cave g, 4 bytes left).
- **Cost, counted**: 3,758 instructions a block while a stereo take is scaled (2,420 the last), 99 a block idle; while recording, 64 frames' compare a take. About 3 of P while it runs: a 10 s stereo take is 1,875 blocks, 1.25 s.
- **CONFIRMED in emulation** (`tests/test_norm.py`, 10): stereo takes at three levels to the frame (30 dB cap at the quiet ones), a single slot's take alone, a loud take left, the keep box held till the part is scaled, a new take over it stopping it, the call from `hits_block`, section 3 the eucl image's.
- **Only the unit can show**: how it sounds, P while it runs, that the scratch job and a save never wait long enough to give up.

## The atrig image: an analog track's SOLO on TRIG, LFO.T on FLTR2 (2026-10-21, section 3 of OS 1.42)

- **On request.
- **Read** (`tools/uitable.pages`, the page lists at `0x401c81e0`): an analog track's TRIG object shows pages 26 and 3 (list `0x401c8214`, built at `0x40035ada`) by the same constructor as a digital track's (`0x40040ef2`), so the same class and our three methods: page 26 is NOTE VEL LEN PROB LFO.T NOT2 NOT3 NOT4. Its filter object shows pages 11 and 12 (list `0x401c81f0`, built at `0x40035d6c`) by the digital one's constructor (`0x4004217c`): page 12, FLTR2, is DEL - FENR - FPAN - - -, and FLTR2's draw loop already gives the analog DEL and FENR (`0x89`, `0x8e`) their own picture, as `fltr_flat` gives LFO.T.
- **Built**: `make image-atrig`, on the norm image (level 51). Image `27f31cc6...`. Main CPU only. `engine/recpage.c`, ATRIG: `trig_sampler` (in the apage image's run, `.cave.r`, for room) gives the analog track on page 26; `TRIG_OURS` keeps F stock's there; the draw puts SOLO's switch at E and no REC; a turn of E goes to the solo as on a sampler track, a held step's lock on slot 26 (the alock image's). `fltr_knob` gives record 28 for G on page 12. The analog tracks' second SYN page draws no SOLO and its E turns nothing; its crossfade on G as it was.
- **CONFIRMED in emulation** (`tests/test_atrig.py`, 21): page 26's knobs, turns and the solo; locks with steps held as the second SYN page made them; the euclidean page stock's; a sampler's TRIG page as it was; the second SYN page's E doing nothing; page 12's G LFO.T and page 11 stock's.
- **Not run**: the draw on page 26 (the rig's surface does not hold the box image's eraser). **Only the unit can show**: the SOLO switch at E on an analog TRIG page, LFO.T's switch on its FLTR2.
- **On the unit, the first build (2026-10-21, `27f31cc6...`): stock's pages, "it's still showing LFO.T on the trig page for the analog and not showing it on the filter page".** Page 26 was never an analog track's. Key 0x13 builds three TRIG and filter sets in one routine: lists `0x401c826c` (1, 3) and `0x401c8260` (7, 8) at `0x4003566e` and `0x40035732`, `0x401c8224` (2, 3) and `0x401c821c` (9, 10), `0x401c8214` (26, 3) and `0x401c81f0` (11, 12). The analog tracks' is the first: FLTR2 page 8 is DEL - FENR with no base and width (page 10, the digital tracks', has them, CONFIRMED on the unit by the fltr image). The unit agrees: on page 26 our code would have emptied E, and it showed stock's. INFERRED, not from a name: what the third set is for. **Second build** (`bbf715c9...`): `trig_sampler` takes the analog track on any TRIG page but 3 (page 1; F stays FLT.T), `fltr_knob` G on page 8; page 8 is drawn by the base's draw (`0x4003a244`, by the filter class's draw `0x4004291c`: 7, 9, 11 FLTR1's loop, 10 FLTR2's, the rest the base's), which draws a record's own picture, so LFO.T is a switch with no `fltr_flat`. `tests/test_atrig.py` (21) on pages 1 and 8. **Only the unit can show: SOLO at E on the analog TRIG page, LFO.T on its FLTR2.**

## Room past section 7's end: how the audio program reaches the audio CPU (2026-10-21, sections 3 and 7 of OS 1.42; read only, nothing built)

For time stretch, the the maintainer's report. Read in the listing, not run.

- **The main CPU reads section 7 at its real length.** The audio CPU's manager task (`0x40082c04`) reads store item 7 (`0x40116246(7, ...)`, at `0x40082d4e`), checks length + 5 <= 393,216 (`0x40082d66`, else error 3), and copies it to `0x4f84f2c6` behind a mark `0xAA` (`0x4f84f2c1`) and the length (`0x4f84f2c2`, `0x40082d84`). The staging area is 384 KB, `0x4f84f2c1..0x4f8af2c1`. Stock section 7 is 383,760 bytes: **a section 7 up to 393,211 bytes passes the check, 9,451 more, with no change to section 3.** The push that follows is sized from the same length (`d2`, `0x40082d96`).
- **The audio program's start** (its entry `0x40001070`): `0x400004bc` copies `0x4004f6e0..0x40057670` to SRAM `0x80000000` and `0x40057670..0x4005df10` to `0x80008000` (the image's tail is SRAM's initial data), then `0x40000512` zeroes `0x4004f6e0..0x4404f980` (BSS, the pool among it), then the cache is set (`movec cacr` `0xa50ce100` at `0x400010d0`, `acr0` `0x4007e020`).
- **So bytes added past `0x4005df10` arrive in memory and are zeroed by the BSS clear before anything runs.** To keep them, a copy of ours goes between the two calls (`jsr 0x400004bc` at `0x400010b4`), into free SDRAM (`0x4404f980..0x48000000`, MEMORY_MAP; above our tables, under the stack's megabyte). **That copy runs before the cache is turned on**, so nothing has to be flushed: code copied there is fetched as the program itself is. The same `acr0` covers `0x40000000..0x47ffffff`, so it runs as cached as stock's.
- **Not read: the updater (section 4)** taking a longer section 7 and the place it keeps item 7 having room; **and the audio CPU's end of the push** (the program arrives through the window at boot in chunks, `+0x800`; INFERRED that it goes by the length behind the mark). Both are shown by one flash that is otherwise inert: the image before, with section 7 padded to its end with zeros. They land in BSS and are cleared. If it boots and plays, the route holds; if not, the boot menu and the image before.
- **The push-code route from section 3's own room is not needed** while 9,451 bytes do. Past that the main CPU's check and its 384 KB are section 3's to change, with what lies after `0x4f8af2c9` read first.
- **Built: the pad7 tool** (`b56e5f97...`, 2026-10-21; `make image-pad7`), the atrig image's second build with section 7 grown by 9,448 zero bytes to 393,208 (`fw.GROW`; `fw` now lets section 7, and only it, grow past its end, the tail a declared region). Section 8 moves along in the container, its bytes the same. `tests/test_pad7.py` (5). **Only the unit can show: that the update goes through, the unit boots and plays, and USB (section 8) still works.** If not: the official file from the boot menu, then the atrig image.

## The back image: SY SWARM, SY TOY, SY BITS and SD BASIC back (2026-10-21, section 7 of OS 1.42)

- **On request.
- **Built**: `make image-back`, on the atrig image (level 52). Image `3d93c05c...`. Audio CPU only; section 3 the atrig image's. Our code that was in the three machines' runs, caves d (SRR, the hold, the stand-ins), e (the hits) and g (the scan), is linked at `m.FAR` (`0x47d70000`) and carried past section 7's end (4,384 bytes, `m.FAR_BYTES`; section 7 388,144 bytes). `far_load` (cave x, 40 bytes) takes the place of the start's two calls at `0x400010b4` (`jsr 0x400004bc ; jsr 0x40000512` -> `jsr far_load ; nop`): stock's SRAM copy, then `far_copy`, then stock's BSS clear, all before the cache is set. The three runs are stock's to the byte and engines 1, 8, 9 and 10's table entries stock's. Nothing in the C or the assembly moved: the linker places d, e and g at the far address, and refuses any branch that cannot reach.
- **Where**: `0x47d70000` is past the take buffers with one to spare (`REC_BUF(k)` is `0x44080000 + 0xf0000 k`; a mono take writes two frames into `REC_BUF(k + 1)`, so slot 63's reaches `REC_BUF(64)`, `0x47c80000`), under the stack's top megabyte, outside the BSS clear, inside `acr0`'s cached `0x40000000..0x47ffffff`.
- **CONFIRMED in emulation** (`tests/test_back.py`, 13): the three runs and four engines' entries stock's; the start calls `far_load`, which calls stock's two; `far_copy` run puts the carried bytes at `m.FAR`; the sampler's sound and hits word the norm engine's to the bit (stereo, mono, backward, cut short), SRR's too, and a normalized take; SWARM, TOY, BITS and SD BASIC play as on stock (the emulator loads the far code where the copy puts it: a stand-in for the start, which does not run here). Section 3 the atrig image's.
- **Only the unit can show**: that it boots (the copy is the start's first code of ours), that the sampler, hits, slices, SRR and normalize are as on atrig, that the four machines play, and P (the far code is fetched through the same cache).
- **Room after it**: about 5,060 bytes past section 7's end (393,208 less 388,144); the machines' runs are no longer ours.

## The stretch image: a note's speed apart from its pitch (2026-10-22, sections 3 and 7 of OS 1.42)

- **The maintainer's word**: KEYS's four settings and a speed knob in PTIM's place, with WSOLA; "i may not use if i dont like it after so make sure we can revert back to ths point easily". The way back: the back image (on the unit, passed), git tag `pre-stretch`; and a note on CHRO or SLCE is the back image's to the bit.
- **Built**: `make image-stretch`, on the back image (level 53). Image `663215f1...`. **Audio CPU** (`engine/sampler.c`, STRETCH; cave f past section 7's end, `m.STRETCH_CAVES`, the far room laid out again since the update and render in cave d grew; section 7 392,240 bytes): KEYS's stretch latched at a note's start from bit 6 of slot 24's low byte (`STR_BIT`); then the note's place moves at SPD's speed through the same walls, loops and edges (`edge`), and two heads read the sample at the note's pitch (what `stock_pitch` gave), 1,024 frames each, triangles half a grain apart, two taps a frame. A head starts again only at a block's start, at the place moved by up to 32 frames (in fours, sixteen frames every four) to the least summed difference from the other head (WSOLA). Each track's heads are skewed by 64 frames so tracks trigged together do not look in one block. The note's first 16 frames come up from nothing; when the place stops the next block goes down to nothing. State 32 bytes a track in zeros the start's copy writes (`m.STR_BASE`). **Main CPU**: KEYS (sampling page H) CHRO, SLCE, CHST, SLST (bit 3 of the track's own word on slot 24, `SRR_STR`, the signature's mask `0xf0f4`; in a run of its own, `mm.CAVE_STRETCH`, `0x400f55e6`, checked as the others are); REC and SRC leave both bits; `engine/recword.S` sends bit 3 as bit 6 and copies slot 52 (PTIM, a track parameter, lockable) from where a step's locks are written into the block that is sent. SPD: 64 the note's own speed, each 32 a doubling (0 a quarter, 127 about four times). On the TRIG page it still reads PTIM.
- **First build's two faults, found in emulation and fixed before this one**: the search maximized the plain product, which a loud stretch wins, so the heads sat a few frames off (35 % error at its own speed; now 0); and every frame was its own work through memory, 145,180 instructions in the heaviest block of eight stretched stereo voices (now 115,705).
- **CONFIRMED in emulation** (`tests/test_stretch.py`, 11): KEYS off the back image's sound and hits to the bit; at its own speed and pitch the stretched note is the note (error 0); SPD 32 1.99 times as long, 96 0.50, 0 3.99; an octave up as long with 2.017 times the crossings; the heaviest block of eight stretched stereo voices 115,705 instructions where the back image's is 114,696 (SWARM's eight 117,348); KEYS's four settings turn and are shown, REC and SRC leave them; the bit and SPD sent.
- **Only the unit can show**: how it sounds (grain 21 ms, two taps), that slot 52 as a step's lock and an LFO reach the sound (copied from where the locks are written: an LFO on PTIM is not shown to be there), P, that a project saved with CHST or SLST opened on an older image reads its word as an old pattern's (bit 3 outside the old signature: SRC and REC made again from MODE, which is 0).
- **On the unit, the first build (2026-10-22, `663215f1...`): "right when I turn on time stretch, the stretch effect occurs ... portamento time doesn't really do anything at all".** So slot 52 is not where a step's locks are written (or not filled there): the speed was whatever that word held. INFERRED, not read: that stock keeps portamento out of the sound's block. **Second build** (`d142b8a6...`, main CPU only, section 7 the first build's): SPD is the track's own kit word on slot 52 (`OWN_WORDS(t)[52]`, where REC, SRC and KEYS are read, on the unit since the srr image), and KEYS going into CHST or SLST from CHRO or SLCE puts it at 64, so a stretch begins at the note's own speed (on request). **A step's lock of PTIM is not followed now** (the kit's word is the track's): only the unit can show whether the locks block has it after all. `tests/test_stretch.py`, its main CPU tests.
- **On the unit, the second build (2026-10-22, `d142b8a6...`): "Portamento still doesn't seem to have any effect ... it just instantly stretches ... I can't affect it in any way except using the tune knob".** The cause, read: **slot 52 never crosses to the audio CPU.** Per track only the machine's slots 18 to 26 (with the type) and slots 27, 29, 37, 38, 40 to 44, 50, 51 are packed into the window's block (this file, "Phase 4"; `emu/engine.py`, HOST_FIELDS); the audio CPU's slot 52 was whatever it held. The tests had fed the audio CPU's parameters straight (`test_pagerec.engine`), which no packing stands between. **Third build** (`8f08fb05...`, both CPUs): with REC off on a stretched track `engine/recword.S` sends 0x80 and SPD (the kit's slot 52) in slot 24's high byte, where REC's mark is (only `REC_LOCK_ON` is ever asked of it, here and on the audio CPU); the audio CPU takes SPD from there and keeps the last while REC is on (`g->spd`). Slot 25, the other free-looking word, is the crossfade's, read from the very block that crosses. `tests/test_stretch.py` (12): SPD through the rig that packs the block (`stereo_rig.Rig`), the note's place stopping at 24,000 frames at 64, 48,000 at 32, 12,000 at 96, 96,000 at 0; slot 24 seen by the update as sent (0xE040 for 96).

## The lock image: a stretch locked to the tempo (2026-10-22, sections 3 and 7 of OS 1.42)

- **On request to auto-snap. On KEYS and not on PORT: PORT turns stock's portamento on, which would glide the pitch.
- **The tempo, read** (not run on stock): the long at `0x402d7360`, BPM times 120 (14,400 in the image, 120 BPM). The per-block code adds it to a phase every block (`0x400a0250`), the block builder hands it on (`0x400a4b48`), and the tempo read of the MIDI RPC reports it (`0x4010c4fa`); the pattern's own tempo has the same unit (its getter `0x4001fe0a` gives 14,400 for none).
- **Built**: `make image-lock`, on the stretch image's third build (level 54). Image `b182efaf...`. **Main CPU**: KEYS CHRO, SLCE, CHST, SLST, CHLK, SLLK (bit 4 of the track's word, `SRR_LOCK`, mask `0xf0e4`; turn in `mm.CAVE_STRETCH`, its names and drawing in `mm.CAVE_LOCK2`); `lock_byte` (`engine/recword.S`, in `mm.CAVE_LOCK`), from the per-block routine with REC off on a stretched track, sends in slot 24's high byte, a track's own count of blocks choosing: 0 SPD, 1 and 2 a step's frames over 2 (43,200,000 over the tempo) in two halves of seven bits, 3 the lock; bits 4 and 5 of the low byte say which (`LOCK_TAG`). **Audio CPU** (`engine/sampler.c` LOCK): keeps the four (`struct lck`, after the tracks' state, in the zeros the start writes); a locked note's region (`s->span`) is stretched to the power of two of steps nearest its length (the boundary at the square root of two), and SPD is a ratio on that. The four are taken only while a stretched note plays, so a note's first three blocks after a start run unlocked.
- **CONFIRMED in emulation** (`tests/test_lock.py`, 12): the routine sends SPD, the step and the lock in turn at 120, 100 and 87.5 BPM, REC on leaves the mark; through the packed block a locked note's place stops at 24,032 frames for 26,000 at 120 BPM (four steps, 24,000), 28,800 at 100, 12,000 for 9,000 frames (two steps), 12,064 at SPD 96 and 47,936 at SPD 32; unlocked, the stretch image's; KEYS off, the back image's to the bit; KEYS's six settings.
- **Only the unit can show**: that `0x402d7360` is the tempo the pattern plays at (pattern or global), that the lock holds by ear, a tempo change followed.

## Where stock's portamento is made, and how to switch it off on sampler tracks (2026-10-22, section 3 of OS 1.42; read only, nothing built)

On request (PORT is the lock image's snap switch, and with it on stock glides a sampler track's pitch between notes). Read in the listing, not run.

- **The routine**: `0x4011a1ac`, a track's pitch every block, called from one place only, the block builder's loop over the twelve tracks (`0x400a4b8a`); what it gives is summed into the pitches that cross (`0x80004688`, `0x400a4bb0`). Its argument at + 60 is the block's base (142 bytes a track, the type at + 62, as `engine/recword.S` reads it); a0 is the track's glide state (`0x45566328 + 8 t`: + 0 where the glide is, + 4 how far it has to go).
- **PORT**: `mvsw %a4@(134),%d0 ; cmpil #16383,%d0 ; bgts` at `0x4011a280` (slot 53 as 8.8: 63 off is 16,128, 64 on is 16,384). Off, the glide's place is put at `0x80000000` (`0x4011a28c`): no glide. On, it is left to run. **PTIM**: `mvsb %a1@(132),%d3` at `0x4011a300` (slot 52, a byte), through the table at `0x40245f70`, is the glide's rate.
- Nothing in the section names an address from `0x4011a1ae` to the routine's end but four other routines' entries past it (`0x4011a3a0`, `0x4011a3a8`, `0x4011a3ca`), and no branch lands in `0x4011a280..0x4011a28a`.
- **Built, the lock image's fourth build** (`ad481219...`, 2026-10-22, on request): `port_gate` (`engine/recword.S`, in `mm.CAVE_LOCK`) at `0x4011a280` puts PORT at 0 only on a sampler track whose own word has KEYS's stretch (bit 3, signed); CHRO and SLCE, and every other machine, glide as stock. Run in emulation behind a caller that does what stock does (`jsr ; bgts`), `tests/test_lock.py` (38). The pitch routine itself is not run here. **Only the unit can show: no glide on a stretched track with PORT on, the glide back on CHRO.**
- **Fifth build** (`8eaa6033...`, 2026-10-22, on request): on a sampler track `port_gate` gives PORT on when KEYS is not a stretch and off when it is, whatever the switch says (PTIM is the glide's time there; 0 is stock's fastest, `0x80000000` in the table, no glide to hear). Other machines as stock. `tests/test_lock.py` (40).
- **The way to switch it off on sampler tracks** (as first read): the ten bytes at `0x4011a280` (`716c0086 0c8000003fff`) become `jsr port_gate ; nop ; nop`, and stock's `bgts` after them stays. `port_gate` loads the word as stock did, puts 0 in its place on a track whose type (+ 62) is 44, compares with 16,383 as stock did and returns, its flags for the `bgts`. A sampler track then never glides, whatever PORT says; every other track as stock. The lock image's snap reads PORT from the kit (`lock_byte`), not from this block, so it is not touched. About 20 bytes, in `mm.CAVE_LOCK`.
- **Sixth build** (`69d1b481...`, 2026-10-22, on request): KEYS is CHRO, SLCE, CHST, SLST again; PORT is the lock (snap). A word with the old lock bit reads as its stretch and loses the bit at the next turn. The audio CPU's lock from KEYS (bit 0 of the lock's send) stays in the code, never set from the page now. `tests/test_lock.py` (40).

## The scrub image: STRT and LEN followed on a stretched note (2026-10-23, section 7 of OS 1.42)

- **On request.
- **The fault, read and run**: `live()` follows the knobs a block at a time. A turn that leaves the place past the region's new far end (caught) sets `duck` and a fade down, and waits for `s->fade` to reach nothing before it starts the next pass. That fade is moved by `play()` only; a stretched note is made by `str_play`, which has none. So once caught, `live()` returned every block until the next trig: no LEN, no STRT, and the place ran on to the old end. A note started at STRT 0 on a quiet first frame kept `s->fade` at its full value and stuck; one started inside the sample had it at 0 and got through, so it came and went. On the lock image in emulation: LEN down at a place of about 3,200 left the place at 4,800 and then 8,288, `duck` 1, STRT ignored.
- **Built**: `make image-scrub`, on the lock image's sixth build (level 55; audio CPU only, section 3 the lock image's to the byte). `str_update`, when a stretched note's `duck` is set, puts `s->fade` at 0 and the next block's `live()` goes on: a loop's next pass begins where the knobs say, the heads crossing into it by their own windows (a block later than unstretched, 0.67 ms); a one-shot so stopped takes its tail and goes down over a block, as at its end. Image `647a4621...`.
- **Tested** (`tests/test_scrub.py`, 7): a stretched loop back inside a short region after LEN (place 1,600) and then at STRT's new start (pc 12,000); the lock image stuck on the same moves; a stretched one-shot cut by LEN down to 2.6% of its peak in its last frames, then nothing; a note not stretched (with the same moves) and stretched notes at rest the lock image's to the bit; the main CPU the lock image's.
- **Only the unit can show**: that scrubbing a stretched loop sounds as it does unstretched (the heads take up to half a grain, about 11 ms, to reach a new place).

## The slscrub image: STRT and LEN followed on a slice (2026-10-23, section 7 of OS 1.42)

- **On request.
- **The cause, read**: the slice image left a slice's knobs alone while it played (`sampler_update`, `if (!c->on)` before `live()`), on SLCE and SLST both, since `live()` knew only the whole sample's region. Not the duck: a slice never reached `live()` at all.
- **Built**: `make image-slscrub`, on the scrub image (level 56; audio CPU only, section 3 the lock image's to the byte). `live()` takes its region from `slice_region` (cave f), which is `slice_cut`'s at a note's start (STRT inside the slice, LEN to the sample's end, RING) for a slice and `region()`'s otherwise; the gate is gone. On SLCE too, not only SLST. Image `edaf9bd2...`.
- **Tested** (`tests/test_slscrub.py`, 7): slice 2 of a tone looping, LEN to 10 and then STRT to 64: on the scrub image it stays at 3,000 and runs on to 11,288; here its pass is 3,750 to 5,332, what a trig with those knobs gives, the place inside it, stretched and not; whole-sample notes with the knobs moved and slices at rest the scrub image's to the bit; the main CPU the lock image's.
- **Only the unit can show**: that it sounds as a whole sample's scrub does. If the scan finishes a take's list while a slice plays, the slice's bounds move to the hits' at the next block (they were even until then).

## The grain image: a stretch that holds together (2026-10-23, section 7 of OS 1.42)

- **On request (this adds none).
- **Why it broke apart, read**: the stretch image's look for where a new grain lines up was 32 frames either side (0.67 ms), on 16 frames 4 apart (1.3 ms) of the left channel. A wave under about 750 Hz could not be lined up, so two grains out of step crossed at the grain's rate (94 Hz), the level going down and up. And no grain knew where an attack was: slowed, every grain that passed over a hit read it, the first ones before the place reached it.
- **Built**: `make image-grain`, on the slscrub image (level 57; audio CPU only, section 3 the lock image's to the byte). `grain_birth` in `str_birth`'s place: STR_GW (384) frames either side on 16 frames STR_GS (16) apart, each a sum of four STR_K apart (a low-pass), then STR_GF (8) either side of the best a frame at a time; the place itself first and kept on a tie (silence ties every candidate, and the first build's coarse look took the farthest back: a burst at its own speed came out 1.32 wrong). STR_WIDE (1) wide look a block for all tracks, the rest a fine look around the place. `grain_look`, every block: the next hit of the slot's list past the place (the scan's, `HITS_AT`) or a loop's wall, whichever first, is c->lim; reached more than a block and at most two from now, a lock: `grain_lock` takes the two heads down over the block and brings a third up from where it meets that frame with the place, which then plays alone at the top of its triangle for STR_HOLD (512) frames. Before a lock no head starts where it would read up to it first, after it none before STR_FLOOR (128) frames past it. Not going backward. State at `0x47d73000` (in `REC_BUF(65)`, not copied); `grain_look`, `grain_lock` and three helpers in cave j (`FAR + 0x2160`, 826 of 896 bytes), the far room now 9,440 bytes past section 7's end of the 9,451 the main CPU's check lets through (`m.FAR_BYTES_GRAIN`). Cave f 3,290 of 3,584. Image `7292c531...`.
- **Tested** (`tests/test_grain.py`, 8): 70 and 140 Hz stretched to half and to twice: the level's spread over its period 0.128 and 0.101 on the slscrub image, 0.000 here; five decaying bursts stretched to half: on the slscrub image what came in the 10 ms before each burst's time was 1.27 to 1.37 times what followed (the attack early), here 0.00, each at its frame; at its own speed a stretched tone and the bursts are the note (0.00002); eight stretched stereo pitched voices, the heaviest block 116,616 (slscrub 115,805, SWARM's eight 117,348; with 24 coarse frames it was 117,743, over); a note not stretched the slscrub image's to the bit; the main CPU the lock image's.
- **Only the unit can show**: how it sounds, P with eight stretched voices (0.994 of SWARM's count, 0.987 before), that a hit's lock lands on the maintainer's takes (the scan's list, as the slices do).
- **Room after it**: past section 7's end, 11 bytes; cave j 70; cave f 294. More code on the audio CPU needs a stock machine's room: ask which.

## The stsw image: KEYS back to two, and the stretch a lockable switch (2026-10-23, section 3 of OS 1.42)

- **On request (asked first: it adds to the main CPU's per-block work) and of REC on the sampling page "It doesn't need to be on the second sampling page if that frees anything up": it would free a place, not a slot, and E was free; REC stays.
- **Where the lock is kept**: every word of a sampler track's machine is taken (17 the solo's lock, 18 to 25 the sampler's, 26 OVER). Everything that reads the solo's lock reads slot 17's high byte only (`engine/amute.c`, `solo_says`, the soloend image), so a step's stretch is a lock on slot 17's low byte: `0xd5` on, `0xa9` off (`STR_LOCK_ON`, `STR_LOCK_OFF`), the high byte the solo's mark or `0x00` (`STR_NO_SOLO`). Slot 24 with REC was looked at and left: a spent ONCE takes the whole lock off.
- **Built**: `make image-stsw`, on the grain image (level 58; main CPU only, section 7 the grain image's to the byte). KEYS (H) CHRO or SLCE, leaving bit 3 (a word with the lock image's bit 4 loses it); knob E STRC ON or OFF, the track's bit 3 (SPD put at 64 going into it, as KEYS did), or with steps held each one's lock, a held step always taking the lock it is turned to; the place says the first held step's. The TRIG page's SOLO keeps a stretch's mark in the low byte (`stsw_lock`), E keeps the solo's high byte. `engine/recword.S`: slot 17's low byte where the locks are written, a mark over the track's bit, into STR_BIT: 7 to 9 instructions a sampler track a block. The audio CPU latches it at the note's start, as it did. Code in two runs nothing reaches, `mm.CAVE_STSW` (`0x40131954`, 632 bytes) and `mm.CAVE_STSW2` (`0x40115b98`, 348). Projects with CHST or SLST read as CHRO or SLCE with STRC ON. Image `adac40a8...`.
- **Tested** (`tests/test_stsw.py`, 13): KEYS's two settings with and without the stretch; E the track's, SPD at 64 into it and left within it; with steps held E's locks, the TRIG page's SOLO turned on and off over them and E again, each keeping the other's byte, a step with no stretch's mark the solo's alone (`0x3580`); the per-block routine for nine words of slot 17, REC on and off, the track stretched and not; section 7 the grain image's. Stock's lock routines run as they are.
- **Not done**: `port_gate` (the lock image's portamento) still goes by the track's own bit, so a step locked to a stretch the track does not have keeps the track's portamento for that note.
- **Only the unit can show**: that a step's lock on slot 17's low byte is played and saved as the solo's high byte is, the page's E as drawn.

## The spread image: the stretch's look in slices, for a lower peak (2026-10-23, section 7 of OS 1.42)

- **The maintainer's word**: of the grain image (or stsw) on the maintainer's unit, "It seems like now CPU is peaking at 105, which is very high"; then "How much will each cut peak?", and "build the spread search and also shrink it to 256, i want the lowest peak".
- **Why, measured**: the same pattern block by block (eight stereo pitched tracks looping, the first one or eight stretched, all trigged every 90 blocks; `tests/test_spread.py`, `blocks`). The grain image's wide look is about 7,500 instructions in the one block a grain starts in: the heaviest 1 % of blocks 101,150 to 108,769 with one stretched track (slscrub to grain), 103,748 to 113,196 with eight, where the middle block moved 0.1 % and 4 %. P reads the peak. Measured before building (the constants changed and put back): 256 frames and 12 coarse frames cut it to 105,383 and 109,305, the 70 Hz spread 0.054, 50 Hz 0.119; 192 and 8 to 103,766 and 107,358; no wide look 101,323 and 105,606 (what is left: the per-block look for hits and the fine look).
- **Built**: `make image-spread`, on the stsw image (level 59; audio CPU only, section 3 the stsw image's to the byte). `grain_step` in place of the wide look: up to STR_LEAD (8) blocks before a head's birth (its age, or the lock's hold) the place and the other head are foreseen where they will be then, the bounds made and the low-passed frames written (`struct grs`, `GRAIN_BASE + 0x400`, 512 bytes a track, not copied); then 9 candidates a block, STR_SW (256) frames either side every 16 on STR_SN (12) frames, then the fine look, 17 frames around the best, 9 a block. One look begins a block for all tracks (notes trigged together begin theirs a block apart: without it four tracks began in the block after a trig, 116,512). `grain_born` (cave d) starts the head where the look has it, moved as far as the other head is from where it was foreseen (within 32 frames, the place within 64), its best yet if the birth cut it short, at the place if neither. Foreseen at the other head's own place (a note at its own speed) or the other head reading nothing, no look. `str_steps` moved to cave j for room. Cave f 3,570 of 3,584, d 1,468 of 1,536, j 890 of 896. Image `05d83e5b...`.
- **Two faults of the first build, found in emulation**: the coarse look ran with the fine one's flag left on (the fine metric over 32 frames far back: 70 Hz at half speed 0.171, worse than before the grain image); the other head's frames were written after the grid and read from a fixed place.
- **Tested** (`tests/test_spread.py`, 9): the heaviest 1 % and the heaviest block, slscrub, grain and now: one stretched 101,150 / 106,822, 108,769 / 109,631, 102,013 / 107,056; eight 103,748 / 107,516, 113,196 / 113,575, 108,561 / 110,963 (SWARM's eight 117,348). 70 and 140 Hz: the level's spread at half speed 0.055, twice 0.001 (0.128 and 0.101 before the grain image, 0.000 on it); bursts at half speed as on the grain image (nothing early, each on its frame); at its own speed the note; a note not stretched the grain image's to the bit; the main CPU the stsw image's.
- **Only the unit can show**: P on the maintainer's pattern (by about 1,170 of our instructions a point: about 5.8 off the heaviest 1 % with one stretched track, 4 with eight; the heaviest block 2.2 off either way), and the bass under 90 Hz, which lines up less well than on the grain image.

## The trans image: DEL drawn as a knob named TRANS on a sampler track (2026-10-24, section 3 of OS 1.42)

- **On request.
- **How a FLTR2 knob is drawn** (READ, `0x40042264` to `0x400424fc`, `0x4003842c` to `0x400385da`): the loop calls the page's + 180 (`0x4003842c`) for each knob with a last argument that FLTR2 sets 1 for most records and 0 for DEL (63, by its test at `0x400424bc`), FENR (69) and the analog page's 137 and 142. **1 means no picture at all**, 0 the record's graphic from the display table through the knob's holder's + 96. DEL's graphic object (`0x41b9e940`, shared with 0x89, the analog page's DEL) calls `0x400706ac`, the delay's picture; a plain knob's (`mm.OBJ_GFX_PLAIN`) calls `0x400701b4`, same arguments (object, value 8.8, surface, x, y). The name under it is the descriptor's short name, by `0x40012b24` at `0x400385c6`, inside the + 180. **The hitui image's FLTR2 name place (`0x4004232e`) is the way for a greyed knob** (the holder's + 236 false and no flag): so HITS was never seen under the knob, only in the pop-up.
- **The first build** (`72f87db5...`) sent a sampler's DEL the way of 1: **on the unit, "It just shows Dell, still and now there's no graphic at all"**, as the reading above says it would.
- **The second build**: `make image-trans`, SHA-256 `b41bad57167bcc66c9234cb499d379db2db3db1ac78727b65b906c16be28097e`, on the spread image (level 60; main CPU only, section 7 the spread image's to the byte). In `mm.CAVE_TRANS` (`0x4012ff58`, 148 bytes, rts before and at its end, named by nothing; `engine/hits.c` TRANS): FLTR2's test of DEL jumps to `del_knob`, which keeps stock's 0 and sets `trans_mark` on a sampler track (cleared on any other); the delay's graphic starts at `del_gfx` (its first 8 bytes), which on the mark clears it and goes to the plain knob's; the name's call at `0x400385c6` goes to `trans_label`: TRANS on a sampler track's DEL (stock's `"%.5s"` box: 5 at most). The pop-up reads TRANSIENT (`hit_long`). No branch into the 8 or the 6 bytes replaced (listing).
- **Held in emulation** (`tests/test_trans.py`, 18): stock's instructions from each place to where it leaves: DEL takes its own picture on every machine, marked on a sampler only; the delay graphic marked is the plain knob's with the call as it came, unmarked stock's frame; the name TRANS on a sampler's DEL, DEL and ATK otherwise; registers as stock leaves them; the image differs from the spread image only in the hits' run, the new run and the three places.
- **Only the unit can show**: the knob drawn where the delay was and its arc at DEL's value, TRANSIENT fitting the pop-up. INFERRED: the holder's + 96 always calls the graphic when FLTR2 draws DEL (else the mark waits for the next delay picture: one knob drawn on an analog track's DEL once). NOT LOOKED AT still: the LFO's list of destinations.

## The next image: DEST SMPL or NEXT, and knob C the track's KIND (2026-10-24, section 3 of OS 1.42)

- **On request.
- **The build**: `make image-next`, SHA-256 `8da5c8f4b5b0e595f6663012f2fb1057badc87aa34da1625f746df16d49f0a9a`, on the trans image (level 61; main CPU only, section 7 the spread image's to the byte, compared). `engine/recpage.c` NEXT, in five runs nothing reaches and nothing names (`mm.CAVE_NEXT` to `mm.CAVE_NEXT5`, 300, 280, 294, 232, 208 bytes, rts before and at each end, checked by the build); the page's own runs moved with it; `engine/once.S` NEXT; `engine/recword.S` NEXT.
- **The page**: B is DEST, SMPL or NEXT (the page's own, as DEST was: not saved, SMPL after a start). C is KIND, STER or MONO, where REC was (REC is the TRIG page's F since the trig image). KIND is bit 6 of the track's own word on slot 24, the only bit left: `SRR_SIG_MASK` is `0xf0a4` here, in C and in the per-block routine's two tests (`rec_word`, `port_gate`), and a turn of SRC keeps it. No lock. **One way: a word with bit 6 reads as unsigned on an older image, which makes it again from MODE (now SRR) and zeroes SRR.** Set KIND to STER before flashing back.
- **NEXT**: at each message of the main task (`once_loop`, after the scratch poll) `next_poll` reads two longs and leaves when no track is on NEXT (8 instructions); else the stops' four longs and their mark (`engine/sampler.h`, STOPS) and leaves when nothing changed (76). When they changed, or a DEST or KIND did (2,487 with one track): a track still holding a free place keeps it; one whose place now holds something gets its kit SMPL put there (`OWN_WORDS(t)[19]`, forward 64 + p or reversed 63 - p as it was), and then holds the next free place of its KIND, none another track holds (STER the lowest free stereo place, MONO the highest free single slot, by the stops' rule: a slot taken when not empty or the second half of an even one). The box's `dest[t]` is that place, or `DEST_SMPL` with none free. While the audio CPU is down (`0x43bdd824`, or the mark not `STOPS_OK`) nothing held is believed: a load is never taken for a take.
- **INFERRED, not confirmed**: that a message reaches the main task between a take's end and the next trig of a NEXT track (else that take goes over the one before); that the kit's SMPL word is what is saved and what the next trig plays (the srr image's word on slot 24 was built on the same; stock's `0x400a321a` copies the kit's into the live block at a trig). The track's machine is read in the block the audio CPU is sent (`0x80006348 + 142 t + 62`, where `rec_word` reads it).
- **What it does not know**: a take by another track (DEST SMPL) onto a NEXT track's free place is taken for the NEXT track's: its SMPL moves there.
- **Held in emulation** (`tests/test_next.py`, 15): the two switches and their words; the first free place of each kind; two tracks two places, a single slot never inside a held stereo place; the take landing moving SMPL both ways and the next place held; a mono take; KIND turned drops the place, SMPL unmoved; SMPL again sends SMPL; none free is SMPL; the audio CPU down; another machine; the costs above; the poll's call in the main task's loop; the image against the trans image (only our runs differ).
- **Only the unit can show**: a NEXT take landing and SMPL following it, the page's two switches, KIND kept after a save and a power cycle.

## The slotprobe tool: locks on knob slots 0, 55 and 70 (2026-10-24, section 3 of OS 1.42)

On request, for the substep hits (above). `make image-slotprobe` (`15ee79e5...`); a tool, not to keep: the spread image with only section 3 changed (sections 1, 2, 4 to 8 the spread image's to the byte, compared).

- **What it does.** On a sampler track's sampling page, with steps held, knob G to the right makes a lock on slots 0, 55 and 70 of each (1080, 1180, 1280; a trigless step is given a lock trig as stock does) through stock's own make, read and remove (`0x40027fa2`, `0x4002740c`, `0x40027fe8`), between stock's `editing` and `edited`; to the left takes them off. D, F and G show L00, L55, L70 and the held step's three (FFFF none); with no step held B00, B55, B70 and the words at those slots' places in the block a trig's locks are written into (`0x800021b0`, + 28 + 2 slot; slot 70's is 168 on, past the track's 142, in the next track's words). BANK, GAIN and P are not drawn (D and F still turn); G with no step held is the profile's switch as before.
- **In the long image's last two runs** (`mm.CAVE_LONG`, `mm.CAVE_EDIT2`; the long image is sidelined and nothing of this chain uses them), the hex in run d. `engine/recpage.c` SLOTPROBE.
- **Shown in emulation** (`tests/test_slotprobe.py`, 3): the three locks made on two held steps and taken off by stock's routines, nothing on slots 17 or 24 of the step; the readouts.
- **Only the unit can show, and what to look for:** (1) L00, L55, L70 read 1080, 1180, 1280 after the turn (stock's make takes the slot); (2) after a save and a power cycle, the same (saved); (3) a copy and paste of the step carries them, a clear takes them off; (4) while the step plays, B00, B55 and B70 change or not (whether stock writes the lock anywhere), and whether anything is heard or changes on that track or the next one (slot 70's place is the next track's).

## A page drawn by stock's own code: the screen rig (2026-10-24, section 3 of OS 1.42)

On request. `emu/screen.py`, `make screen PAGE=fltr2 IMAGE=trans MACHINE=44`, a PNG in `build/screens/` (made from Elektron code: never committed). About 3 s a screen.

- **The static constructors**: a count (136) at `0x4033950c` and the list at `0x40339510`, run in order by `0x40082578` (CONFIRMED: UI_INIT, `0x40188796`, is entry 61). All 136 run in emulation in supervisor mode (SR `0x2700`; user mode faults at the kernel's `move %sr` in `0x40001980`), with the hot code first copied on-chip as the start does (`0x4000045c`). They build the fonts (`mm.FONT_NAMES`), the pictures and the knobs' display table.
- **The UI object**: `0x4016f060` (a0 where to put a shared pointer) builds it at its first call (0x288 bytes, `0x400351fa`, vtable `0x401c849c`), every page and its managers with it. It runs once a divide by 0 is let through: the sequencer's (`0x4008c222`, `0x43bd845c` 0 with no pattern; set at `0x4008c3f8`). The filter objects are three, pages 7 and 8, 9 and 10, 11 and 12 (their + 124 list); + 144 picks the one shown.
- **The surface**: stock's constructor `0x400f7242` (surface, w, h): + 4 w, + 8 h, + 12 longs a column ((h + 31) / 32), + 16 the dots (allocated 4 times what 1 bit a dot needs; only the first quarter is drawn), + 20 a second buffer of bookkeeping, not dots; the UI fills a new one with `0x400f8508` (surface, 0, 0). **Stock's y 0 is the panel's bottom row**: a column's first bit is the bottom (READ: text drawn at y 0 by `0x400f8bd0` fills the last five rows, a fill of (0, 0)-(1, 1) the bottom left corner), and the picture is upright only read that way.
- **Stand-ins, and only these**: memory nobody mapped reads 0 (no project: every value 0, every lock off); a divide by 0 leaves its register; the machine of every track is the one asked for (`0x4000f692` made `moveq #m,%d0 ; rts`). Not run: the RTOS, the tasks, the screen's driver.
- **Seen with it**: the trans image's second build on a sampler track draws a knob named TRANS where the delay was, LFO.T and FLT.T as switches; on another machine stock's DEL and its delay picture, and dotted boxes for G and H. The first build's blank is what the reading of + 180's argument said.
- **Pages** (`emu/screen.PAGES`: a name, the class, the first page of the object's list, which of its pages shows): syn and sampling (the SYN object's list is 6, 6 in our images: the second is the sampling page), trig and eucl (the digital tracks' TRIG object, pages 1 and 3; objects with lists 2, 26 and 31 also exist), atrig (page 26, the analog tracks'), fltr1 and fltr2 (pages 9 and 10). On the trans image with a sampler: SYN reads TUNE SMPL LOOP XFADE / STRT LEN SRR OVER; the sampling page SRC DEST REC BANK / STRC, the gain (no name), the load box (no name, "000" and the transfer letter, C before the check, which this font draws near a G), KEYS; TRIG NOTE VEL LEN PROB / SOLO REC PTIM PORT, SOLO and REC switches; eucl stock's. Every value 0 (no project).

## The bank in the PROJECT menu: the pbank image (2026-10-26, section 3 of OS 1.42)

On request: one entry that moves to the next bank each time it is chosen (not a value page), and the bank still loads only with a project (not at once).

Read from the listing, and run in emulation (`emu/screen.py` builds the UI, this menu with it):

- **The PROJECT menu is built once by the UI, `0x401855d4(menu)`**, method table `0x401d0bcc` (one object in the heap after the UI's getter, run). Its base is stock's list page (`0x400fed6c`, title PROJECT), **its page at + 56**. Three entries, each 0x54 bytes from the heap (`0x4010394c`), made by `0x400fa84c(entry, name, action, icon, last, -1, 8)` and added by `0x400fa082(menu, entry)`. Its end is `0x401858b2`: `movem (24,sp),d2-d6/a2-a6; lea (128,sp),sp; rts`, a2 the menu; nothing in the routine branches there (listing).
- **An entry is four of stock's function objects**, 16 bytes each (data, a long, manager at + 8, call at + 12), kept at + 12, + 28, + 44, + 60 of the entry; + 4 and + 8 are -1, + 76 the last argument doubled. The name is a call that makes a string through a0 (LOAD PROJECT's, `0x401851d8`: `0x401bf31e(string, text, allocator)`); **the list asks for it each time it draws** (`0x400fa5d2`, called from the list's draws `0x400fea92`, `0x400ff154`, `0x400ffb94`). The action is called by `0x400fa638(entry)`, from the list's key routine (`0x400ff5b6`), only if its manager is not 0. The icon is a blit of a picture (`0x400f8f70(surface, picture, x, y, centred)`; LOAD's `0x444dff38`), left out when its manager is 0 (`0x400fa610`). The last is empty on all three.
- **Stock's manager `0x401852d4`** (LOAD PROJECT's name) answers 0 its type, 1 the data, 2 a copy as a new byte from the heap whatever the source holds, 3 frees the data: any call that keeps nothing can use it.
- **The list redraws by `0x400ffe22(menu + 56)`** (`PAGE_REDRAW`), as its own scroll does (`0x400ff42a`).

The build: `make image-pbank`, SHA-256 `32cd7c73dd19f4859ff049e654dd329d052545b07eb4a4eb6e2895583f0bae00`, on the next image (level 62; main CPU only, section 7 the spread image's to the byte, compared). `engine/pbank.c` in a run nothing reaches and nothing names (`mm.CAVE_PBANK`, `0x401266ae..0x40126836`, 392 bytes, rts before and at its end, checked by the build; the first two tried, `0x4007f4e8` and `0x401125c2`, were named by themselves and too small). The constructor's restore jumps to `bank_hook`, which adds a fourth entry and does the restore and return as stock's. The entry: the name SAMPLE BANK and the loaded bank, A>B with another chosen (its text in the run, its last three places made again before each drawing), the action BANK_WANT to the next bank, after C to A, and the menu marked for a redraw; no icon. `engine/recpage.c` PBANK: knob D of the sampling page shows and turns nothing.

Run in emulation (`tests/test_pbank.py`, 9): the menu drawn by stock's own draw, rows above 40 as stock's and the fourth entry under them, its text changing with the banks; stock's own action call moves BANK_WANT A, B, C, A from each start and leaves BANK_NOW, and sets the page's redraw byte; D of the sampling page empty and a turn of it nothing; the image differs from the next image only in its runs.

**Only the unit can show:** that the list's keys reach the fourth entry and choose it, and that the redraw shows the new letter at once (if not, it shows at the next scroll or the next opening).

## The kind image: SMPL stops only at the track's KIND (2026-10-26, section 3 of OS 1.42)

- **On request; told that a sample of the other kind is reached by flipping KIND.
- **The build**: `make image-kind`, SHA-256 `d542b1fe5340f300be66913fce83c11e00ef082c80a428faea4cb37fbd171756`, on the pbank image (`32cd7c73...`, level 63; main CPU only, section 7 the spread image's to the byte, compared). `engine/recpage.c` SKIND: `kind_stops`, in `mm.CAVE_KIND` (`0x40132a6c`, 220 bytes, rts before and at its end, named by nothing, checked by the build), called from `smpl_turn` after `stops()`.
- **What it does**: of `stops()`'s 64 (0..31 the stereo places, 32..63 the single slots) only the track's KIND's are kept: STER the stereo samples and the lowest free stereo place, MONO the mono samples and the highest free single slot. None of that kind: the turn is stock's, as with no stop at all. A number keeps its meaning: a pattern, a lock or an LFO on the other kind plays it, and a turn goes from there to the nearest stop of the track's kind. A held step's lock moves by the same stops. Costs only at a turn of SMPL.
- **Held in emulation** (`tests/test_kind.py`, 37): every layout of the stops tests walked both ways for each kind; the stops change with KIND; a value of the other kind to the nearest; the image against the pbank image (only our runs differ).
- **Only the unit can show**: the knob's feel with the stops halved, nothing else new.

## The mirror image: the screen to a viewer over USB (2026-10-26, section 3 of OS 1.42)

- **The maintainer's word**, of a video with an Elektron unit's screen drawn clean above the footage: "Can we try option one?" (the screen's frames streamed off the unit and drawn by a viewer on the computer, put over the camera in OBS).
- **The panel, READ** (`0x4011389c` to `0x401139b6`, `0x4000a1xx`): two 1,024-byte frames (pointers `0x402d7110`, `0x402d7114`; `0x444bf638`, `0x444bf238` at the start), a column of 64 dots in 8 bytes, 128 columns. `0x4011391a` (`mm.PANEL_PAINT`) sends the panel, 8 columns at a time through `0x4011384c`, the bytes of `*0x402d7110` that differ from `*0x402d7114`, swaps the two pointers and returns the new `*0x402d7110`, which the UI draws its next frame in (it keeps it at `0x405d4a18`). **After it the frame on the panel is `*0x402d7114`** (`mm.PANEL_SHOWN`; first written here the other way round, which was wrong: see the second build below). `0x4011389c` sends a whole frame the same way. The UI's draw (the routine round `0x4000a220`) asks `0x4010095c` whether anything is to be drawn and, only then, draws onto a surface over the buffer and sends it through a4, loaded at `0x4000a22c`. The boot's own picture task (`0x40113652`, the one called "the display" above) uses the same routines.
- **The build**: `make image-mirror`, SHA-256 `3791efe6f0096f4e43e60c1b6f07ec012ada98de0b7f7437cb9a76cdecafff6b`, on the kind image (level 64; main CPU only, section 7 the spread image's to the byte, compared). `engine/mirror.c` in three runs nothing reaches and nothing names (`mm.CAVE_MIRROR` 286 bytes, its numbers first; `CAVE_MIRROR2` 228; `CAVE_MIRROR3` 224); the lea at `0x4000a22c` to `mirror_paint` (stock's send, then the frame marked new) and the call at `0x4000a220` to `mirror_tick` (stock's asking, passed on, then the frame shown sent if new, asked for and due); `engine/phone.c` MIRROR: the SysEx entry takes 0x67 (on, renewed; a byte, frames a second, 0 for 15) and 0x68 (off), nothing answered, the sink made first if the unit has had no message.
- **The frame** (0x69): `f0 00 20 3c 10 00`, `00 00 01 00 00`, `69`, a count of 7 bits, the 1,024 bytes 7 to a group (a byte of their high bits, bit 6 the first's, then their low 7 bits; the last group 2), `f7`: 1,185 bytes, written into the unit's SysEx sink as stock's answers are (its + 16 in pieces of 64 bytes at most, then + 12). Byte 8 c + p is column c's dots 8 p to 8 p + 7, most significant bit first: dot y (0 the panel's bottom row) is bit 7 - y % 8 of byte 8 c + y / 8, as `emu/screen.py` reads the surface (first written here as bit 0 the lowest: wrong; the viewer reads it right). Sent only while the viewer's last 0x67 is under 3 s old (by the first timer).
- **Cost, counted**: 18,407 instructions a frame, the sink's own work not counted (played by the test); an asking with nothing to send 11. In the UI's task, not the per-block interrupt.
- **INFERRED, not confirmed**: that the UI's draw is called often (else a frame waits for the next asking); that the sink takes a frame from the UI's task while the MIDI task may be writing an answer (they can mix: the viewer does no file transfers while it mirrors); that the host keeps up at 15 frames a second (18 KB/s; reads run at 188 KB/s).
- **Held in emulation** (`tests/test_mirror.py`, 5): no frame without a viewer, stock's answer passed on; a frame decoded back to the panel's bytes; at most the rate, the held frame at the next asking, none when nothing is new; a viewer gone 3 s or off; the costs; the image against the kind image (only our places differ).
- **Only the unit can show**: frames reaching the viewer, the UI's feel while it mirrors. **The viewer is not built**: it is the phone side's (`the phone app's repository`), not the bench's.

### The mirror image's second build: the panel's frame, not the next one (2026-10-26)

- **On the unit, the first build** (`3791efe6...`, flashed from the phone, frames reach the viewer; read by the viewer's session from four frames kept by `mirror --dump`, track 4, sampler, SYN page, the screen still): the four frames byte for byte the same; against stock's draw in emulation (`make screen PAGE=syn MACHINE=44`) the labels the same to the byte but in the dials' columns (c30 to 34, c62, c78 to 83, c109 to 111): strokes through TUNE/STRT, LOOP/SRR, XFADE/OVER, the rings dotted. **The maintainer's word: the panel itself is clean.**
- **READ**: `0x4011391a` sends `*0x402d7110` and then swaps, so after it the panel's frame is `*0x402d7114` and `*0x402d7110` is the buffer the UI draws the next frame in (it is what the send returns: `0x4000a24c`, `0x4000a28c` keep it at `0x405d4a18`, and the UI's surface is made over it, `0x400f72be` at `0x4000a27c`). Stock's own getter of the panel's frame, `0x40113a20`, reads `0x402d7114`, and its two callers copy 1,024 bytes from it (`0x40107914`, `0x401083e0`). The first build sent `*0x402d7110` at the asking: the next frame's buffer, holding the frame of two sends before.
- **INFERRED, not read**: why that buffer differs from the panel only at the dials with the screen still (the UI's draw over its buffer at the dials not read). Not needed for the fix.
- **The build**: `make image-mirror`, the same level (64) and place, one constant (`SHOWN` in `engine/mirror.c`, now `0x402d7114`). SHA-256 `2bbc45b931e6be16309041131ef7b89c7a3919865a52eb4f617b2051539f5500` (the first build's `3791efe6...` gone). `tests/test_mirror.py` (6): a new test runs stock's send to the panel as it is, the panel played column by column through `0x4011384c`, over four frames with a few columns changed each: the frame sent is the panel's every time, and the buffer the first build sent is not.
- **Only the unit can show**: the viewer's picture matching the panel at the dials.

## The trap image: a stretched note for less, in CY ALLOY's room (2026-10-26, section 7 of OS 1.42)

- **On request.
- **Where a stretched block went, measured** (`tests/test_spread.py`, `blocks`: eight stereo pitched loops, all stretched, the heaviest 1 %; each part taken out alone in a throwaway build): the second head's reads 8,516, the right channel 6,228, the place moved a frame at a time 4,224, the spread look 3,567, `grain_look`'s search of the hits 1,678. The look's slices are a steady cost now, not a peak.
- **Options counted and not built**: the look trimmed (8 coarse frames, 8 fine, the fine look 4 either side) 2,194, the 70 Hz level's spread at SPD 32 0.055 to 0.057, highs lined up less exactly; the look narrowed to 192 frames 20, SPD 96's spread 0.001 to 0.114; the overlap 256 frames, with the place a block at once, 7,904.
- **CY ALLOY's room, read**: on stock, with engines 8 to 11 and 2 handed nothing, `tools/deadcode.survey` gives 324 bytes, because a long in Twinshot's code (`0x400098b0`, `0x40006f2e`) reads as naming CY ALLOY's update. That code is ours (cave k) on every image since the pitch image, and on the spread image the same survey gives one run, `0x40006d7c` to `0x4000709c` (SY TONE's update), 800 bytes, named by its two table entries alone (`m.TRAP_CAVES`, cave al). The build checks stock names it only there and in Twinshot's room.
- **Built**: `make image-trap`, on the mirror image (level 65; audio CPU only, section 3 the mirror image's to the byte). `engine/sampler.h`, TRAP; `engine/sampler.c`: a head's weight a trapezoid (`str_w`): up over STR_X (128) frames from its birth, flat to half a grain, down over 128, then nothing until its next birth; births where they were, the two summing to 128 (STR_SH 3 where it was 1). A block where one head is nothing is made by the other alone (`str_one`). The place moves a block at once when no wall comes in it (unsigned going forward), a frame at a time when one does. `str_w`, `str_one` and `slice_region` in cave al (574 of 800); cave f 3,444 of 3,584. Engine 2 is handed SWARM's stand-ins: **a track on CY ALLOY plays nothing.** Image `5cc09429...`.
- **Tested** (`tests/test_trap.py`, 9): the heaviest 1 %, the heaviest and the middle, spread then now: one stretched 102,013 / 107,056 / 96,716, 100,542 / 106,651 / 95,177; eight 108,561 / 110,963 / 104,812, **98,512 / 100,907 / 94,767** (eight not stretched, on the spread image: 100,657 / 106,805 / 94,936). 70 and 140 Hz: the level's spread at half speed 0.042 (0.055), at twice 0.003 (0.001); bursts once and on time; at its own speed the note (0.00001); a note not stretched the spread image's to the bit; section 7 the spread image's but for our runs and engine 2's entries. The place a block at once was the spread image's sound to the bit in the throwaway build that had it alone.
- **Only the unit can show**: P on the maintainer's pattern (about 1,170 of ours a point: about 8.6 off with eight stretched, 1.3 with one); how a 2.7 ms seam sounds on chords, pads and noise, where no look lines everything up (the spread image smeared those over the whole grain).
- **The second build** (`cf9ad4b28ada87c6...`, on request, asked what 256 costs: about 2,000, 1.8 of P, for a fade twice as long at each seam): STR_X 256, STR_SH 2, nothing else. Spread then now: one stretched 102,013 / 107,056 / 96,716, 100,540 / 106,649 / 95,190; eight 108,561 / 110,963 / 104,812, **100,768 / 103,163 / 97,020**. 70 and 140 Hz at half speed 0.042, at twice 0.002. `tests/test_trap.py` (9; eight stretched at least 6,000 down). The shadow image (66) rebuilt on it: `4e82f6eb...`, section 7 the trap image's.
- **The third build, 128 again** (`5cc09429...`, the first build to the byte): the maintainer's word on the 256 build, "the lower one is necesarry cuz zcpu is too high with 256". STR_X 128, STR_SH 3; `tests/test_trap.py` back to eight stretched at least 8,000 down (9 passed). The images above it (shadow, sink, tune) carry 128 once rebuilt.

## The shadow image: the viewer's frame copied from what reaches the panel (2026-10-26, section 3 of OS 1.42)

- **On the unit after the mirror image's second build** (his screenshot from the viewer, 2026-10-26, "mirror still aint eifht"; the file flashed not said: the trap image, on the phone, carries the second build): track 4, SYN page, still strokes, and now through the header and the labels too, dials with more than one pointer. So the frame shown (`*0x402d7114` at the asking) is not the panel's picture on the unit either, though stock's own getter (`0x40113a20`) and its screen dump (`0x4000a2de`, a SysEx answer whose header is at `0x401c21b0`) read it.
- **READ**: the panel's bytes reach it by one way only, `0x4011384c` (column, page, 8 bytes: `0x10 | page`, the column, then the 8 by `0x40002550`), called by the send (`0x4011391a`), the whole frame's (`0x4011389c`) and the clear (`0x401139b6`, both frames 0 and every column sent). The other writers of that bus (`0x40002550`, `0x4000271e` at `0x40082624`, `0x40102f72`, `0x40113a70`, `0x40113d24`, `0x40113dee`) send commands of other kinds (the LEDs' `0xb0`, `0xb5` and the like), no column. The UI's draw clears its surface and draws every layer when it draws (`0x40100992`: `0x400f8508(surface, 0, 1)` clears the dots, sets the second plane `0x405d4618`). Nothing names `0x4011384e` to `0x40113853`.
- **Not known**: what puts the strokes in the buffers on the unit while the panel stays clean. In emulation four draws of the page are the same and stock's send keeps the frame shown equal to the panel. Not chased: the copy below does not depend on it.
- **The build**: `make image-shadow`, SHA-256 `c06542699fd27fe850523fd9581ced276a7ac1bd3626051f331055883193fa01`, on the trap image (level 66; main CPU only, section 7 the trap image's to the byte, compared). `engine/mirror.c` SHADOW, in the mirror image's three runs (m 272 of 286, n 170 of 228, o 192 of 224): the column sender's first two instructions are a jmp to `mirror_cols`, which copies the 8 bytes into `mirror_frame` (byte 8 c + p, as the frame) when there is one, does the two and goes on at `0x40113854` (`mm.PANEL_COLUMNS_ON`). At a viewer's first asking `mirror_prime` takes 1,024 bytes from stock's heap (`0x40103952`, where the UI's surfaces take theirs), copies the frame shown into them, turns over every byte of the frame shown (the one paint compares the next against) and sets the UI's mark to draw (`ui + 64 + 32`, as stock's `0x40100966`): the next send rewrites every column of the panel, so the copy is whole from there. Frames are sent from the copy; the 0x69 format as it was. The heap's bytes are kept.
- **Cost, counted**: a column send 73 instructions with stock's own and the bus played (our part about 40: 8 bytes, a guard). 128 sends at most a frame, in the UI's task as before. Priming once: 1,024 bytes copied and turned over.
- **Held in emulation** (`tests/test_shadow.py`, 3): nothing taken with no viewer; taken once; after it the whole panel sent, the frame sent the panel's as played from the bus over five frames, with strokes written into the frame shown after each send; a column send's cost; only our places differ from the trap image.
- **Only the unit can show**: that the viewer's picture is the panel's now. If it still is not, the bytes were changed on their way (the sink, USB, the viewer), not in the unit's frames.

## The sink image: the viewer's frame put into the SysEx sink whole (2026-10-26, section 3 of OS 1.42)

- **On the unit, the shadow image** (flashed 02:22, read by the viewer's session from the frames as received, `~/Desktop/frames2/`, and the first build's, `~/Desktop/frames/`): still the strokes, in the same places on every page (SYN, sampling, trig) and in both builds: only in 56-byte pieces 2, 4, 8, 11, 13, 15 and 17 of the frame, from 3, 16, 32 or 48 bytes in to the piece's end; every other piece exact; 1,185 bytes a frame. So the frame was right in the unit and changed on its way out. The shadow image's "Not known" above is this, and its copy of the panel was not needed.
- **READ**: the sink (`0x4449c51c`, made by `0x40105fbe(sink, 0, 2)`: vtable `0x40242594`, + 8 how many bytes it has, + 20 its bytes, + 532 its size, 144). Its put (vtable + 16, `0x40105f24`) copies min(asked, room) bytes into it, and when it is full calls + 12 (`0x40105eb4`: sends the bytes, `0x40106976(bytes, n, + 16, + 12)`, and empties it) and goes on with what is left of the write, **copied from the write's start again**: the source it passes is its argument each time round (`movel %sp@(32),%sp@-` at `0x40105f56`), never moved on. A write that crosses a send of 144 comes out with its rest as its own start again. Stock's own answers either fit or are not written that way (not looked at).
- **Our writes**: the header (12), the count (1), then a 64-byte write a 56-byte piece: the stream's byte 144 k falls in pieces 2, 4, 6, 8, 11, 13, 15, 17 at 3, 19, 35, 51 packed bytes in, the places the viewer saw (piece 6 not reported by it; damaged in emulation). **Confirmed in emulation** with the sink's own code run (only `0x40106976` played): the shadow image's frame is damaged in exactly those pieces.
- **The build**: `make image-sink`, SHA-256 `a8c3f8f015c89a36de067242f873f8f6721a1767a6785e71680696c8b1d8aaf0`, on the shadow image (level 67; main CPU only, section 7 the shadow image's to the byte). `engine/mirror.c` PIECES: `mirror_put` writes at most the sink's room (+ 532 less + 8) at a time, so no write crosses a send; in a run of its own, `mm.CAVE_MIRROR4` (`0x40108034`, 168 bytes, rts before and at its end, named by nothing), only in this image. The 0x69 frame as it was: the viewer needs nothing.
- **Held in emulation** (`tests/test_sink.py`, 3): the shadow image's frame damaged where a write crosses a send; the sink image's frame the panel's to the byte, sent as eight 144-byte sends and the rest; only our places differ from the shadow image.
- **On the unit, works (2026-10-26, on request)**: the viewer's picture is the panel's.
- **Not looked at**: engine/phone.c's answers through the same sink (`ask`), whether any of their writes cross a send.

## The tune image: a pushed turn of every TUNE by 1 (2026-10-26, section 3 of OS 1.42)

- **The maintainer's word** (a wish on the status page, 2026-10-15, then "fixing this would be nice"): "When you hold down the encoder on the tune knob, the stock has it set up so that it jumps by 4s, but on the Digitakt ... it just jumps by 1".
- **READ**: a pushed turn's steps are multiplied by the second long of the sixteen bytes the start-up copies into a record's entry of the display table (`0x400f6866`; "How a knob turns" above). The sampler's TUNE is record 431 (TUN1 of machine 44), entry `0x41ba9790` (`mm.TUNE_ENTRY`), given the plain knob's `{1, 4, 0, 0x443db178}` from fp at `0x40192d4c` (`pea 0x10`, `movel %fp,%sp@-`, `pea` the entry's + 4, `clrl` its flags, `jsr %a3@`). Other machines' TUNEs have their own: BD MD's `{1, 8}` (the picker's), SD BA's `{1, 12, 6}`, SY TN's `{-1, -8}`; not changed. A template with 1 for a pushed turn exists (`0x401d6b84`) but with another feel (`0x41bab1d8`), not used. Nothing branches into `0x40192d58` to `0x40192d5f`.
- **The build**: `make image-tune`, SHA-256 `f1e605678c21c5720f8b343922dc1c2f1683bbab53ee4de8cf3ccd1969768f69`, on the sink image (level 68; main CPU only, section 7 the sink image's). The clear and the copy (`0x40192d58`, 8 bytes, `mm.TUNE_COPY`) are `jsr tune_entry` and a nop; `engine/tunepush.S` clears the flags, calls a3 with stock's three arguments, then makes the entry's + 8 1. In a run of its own, `mm.CAVE_TUNE` (`0x40016558`, 110 bytes, named by nothing). Runs once, at the start.
- **Held in emulation** (`tests/test_tune.py`, 2), stock's start-up run as it is (the screen rig): record 431's entry `{1, 1, 0, the plain feel}`, the only byte of the 505 entries that differs from the sink image's; stock's `0x400f6866` gives a pushed turn of 3 steps 3 (the sink image 12), unpushed 3 both; only our places differ.
- **Only the unit can show**: how it feels. A pushed turn also takes the feel's pushed longs, which are stock's and not understood ("How a knob turns").
- **Its second build** (`5ca40375b2e75e7a6392124f6c29562519801b70553154403d0a688bccfefe7f`, on the sink image as rebuilt on the trap image's third build, `a0c94ce5...`; the first, `f1e60567...`, the sampler's only, never on the unit), on request: every record whose short name is TUNE, TUN1 or TUN2 but the sampler's TUN2 (our LOOP): 40 (`build_main.TUNE_RECORDS`, checked against the descriptors at build), digital and analog, RS CL's two oscillators, DUAL's first. **READ**: every one of their entries is filled before record 431's (its copy at `0x40192d5e` the last; checked at build from the start-up's listing), so `tune_entry`, after 431's copy, gives each its unpushed multiplier for the pushed one (a list of the entries' offsets made by the build, `tune_list.S`; the run moved to `0x400171a0`, 138 bytes). SY TN's TUNE is `{-1, -8}`: so `{-1, -1}`, a pushed turn as its unpushed one, whatever -1 means there (not read). Held in emulation, stock's start-up run: the 40 entries' + 8 their + 4, no other byte of the table changed (LOOP's not); a pushed turn of 3 ticks 3 for the sampler, BD HARD, BD MD and SD BA, where the sink image gives 12, 12, 24 and 36.
- **On the unit, the second build: "still only increments by 4 instead of by 1".** The record's second long only multiplies the ticks. **How far a step moves is the feel's** (RUN in emulation for the first time: stock's `0x400f6a96` on the start-up's feels): a feel is three flags and a byte, a plain turn's {speed raised by, ticks a step, step} and a pushed one's; the plain knob's (`0x443db178`) `{2, 3, 1}` and `{2, 3, 4}`, the picker's (`0x443db140`) `{0, 6, 1}` and `{0, 6, 4}`, `0x443db194` `{18, 1, 1}` and `{2, 3, 1}`; the TUNE records have these three. **Stock builds the feels after the display table is filled** (a copy made at record 431's entry is all 0: tried). **The third build** (`4d990e4ef9f9f1f3...`, on the phone): `tune_feels` (`mm.CAVE_TUNE2`), the three feels with a pushed step of 1, written by the build from `build_main.TUNE_FEELS` (held against the start-up's own in `tests/test_tune.py`); `tune_entry` gives each TUNE record its feel's copy and, for a pushed turn's multiplier, that feel's pushed ticks a step (negative for a record turned the other way). Run a detent a tick: a pushed detent moves 1 where stock moved 4 (the sampler, BD HARD, SD BA every detent; the picker's feel, BD MD and the reversed one, 1 every 2 or 3 detents, as stock's 4 did); unpushed as stock's. `tests/test_tune.py` (7). Code in `mm.CAVE_TUNE` moved to `0x401ad8cc`.

## Loose ends and cheap wins, read and counted (2026-10-26, section 7 the trap image's, section 3 the tune image's; nothing built)

On request.

- **A stereo note that has ended keeps its right channel, COUNTED.** `sampler_render` sets `rvalid` from `s->r`, which only a note's start changes, so a track whose stereo note is over is in `R_MASK` till a mono note plays: its right channel goes through stock's four stages on silence every block, and the main CPU still starts its transfers. Eight sampler tracks, stereo notes over, the rig's count (the trap image, `stereo_rig.Rig`): 77,285 a block; with `s->r` cleared on four of them 66,477, on all eight 43,792. So about 2,700 a silent stereo track while any right channel runs, and the 16,000 of the two all-eight stages once none does (about 1,170 a point of P). Going in and out of the mask is a path the unit already takes (a track that turns from a stereo sample to a mono one): `seed` starts the right's filters from the left's when it comes back, and its amp and gain state are the left's every block. Not built: let a track go once its note is over and its right channel's last block is near nothing (a filter left ringing keeps it).
- **Not a way: stock's OVER and BASE/WIDTH are not pass-throughs at a track's defaults**, RUN (both stages alone, random blocks, factory knobs, then slot 26 at 0, then 37 at 0 and 38 at 127): OVER moves a sample by up to 67,105,017 (it carries the track's gain ramps), BASE/WIDTH by up to 1,745,421. The right pass cannot skip them.
- **Where a block goes, eight pitched stereo loops not stretched** (a code hook a instruction; its total runs about a quarter over the rig's own count, so shares only): stock's four stages about 57 % (the multimode filter the most), the pitched sum (`hq_table2`'s run) 20 %, `voice_two` 4 %, `hit_scan` 3 %. Stretched, the stretch's routines about 16 %.
- **The normalizer stops a take part done when a mono take starts in the slot next to it, READ (not run).** `norm_peaks` takes any running take whose slot is within one of the one being scaled (`k <= n->k + 1 && k + 1 >= n->k`) as one over it, and leaves what is scaled as it is. Two mono takes are two single slots side by side, and NEXT on a MONO track puts the next take in the next slot down: recorded back to back, each take but the last keeps its first few blocks' worth (256 frames a block) up to 30 dB louder than the rest. The exact test: the new take's slots (`k`, and `k + 1` if `s->link == 1`) meet the scaled take's (`n->k`, and `n->k + 1` if `n->two`).
- **The normalizer's end clears the next slot's mark for a mono take too, READ.** `KEPT[k] = KEPT[k + 1] = 0` whatever `n->two`: a mono take's neighbour (another mono sample) is marked not kept, so the scratch job and the next save write it again for nothing; and a mono take in slot 63 (the first a MONO track's NEXT takes) writes `KEPT[64]`, which is `0x44080000`, the first long of slot 0's buffer: two frames of slot 0 made 0 in memory, the drive not.
- **A take that ends while another is being scaled is never scaled if its track starts a take before its turn, READ.** `wait` is a bit a track, cleared while the track records (`& ~now`), and the slot and peak are the track's running take's. Only a take shorter than an eighth of the one before it, back to back, gets there.
- **LOAD PROJECT waits 2 s for a phone whenever any host has sent SysEx since the start, READ.** `phone_load` asks whenever `SINK_MADE`, which any message makes: Transfer, slink, the mirror viewer, or a phone unplugged since. No answer: `FIRST_WAIT`, then stock's load. The phone app sends 0x63 at every connect (its `backUpAll`, `whichProject`), so asking only after a 0x63 since the start, and not again after a wait that timed out until the next 0x63, would keep the phone's load and drop the wait elsewhere.
- **The phone's own writes into the sink never cross a send, READ** (closes the sink image's "Not looked at"): `ask` writes 17 bytes and `knows_sysex` 23, each into a sink its last writer emptied, each then sent. Only another task's write half done could be split, as the mirror's frames could be by the load job's ask (one frame spoilt, no more).
- **The mirror's column copy runs on after the viewer has gone, READ**: `mirror_cols` copies whenever `mirror_frame` is set, and nothing unsets it till a start. About 40 instructions a column sent, in the UI's task. Copying only while a viewer asks needs `mirror_prime` to prime again when one comes back.
- **The main CPU**: ours a block is about 2 to 3 hundredths (the busy mixer link about 1,000 to 1,500 instructions, `rec_word` about 30 a sampler track, the hits 252, the transfers 0.6 to 0.9 with stereo), stock's about 85 to 90. A path for mutes alone (no solo, no crossfade) would pass the solos' pass and the crossfade's reads, about 500 instructions, under 1 hundredth. Nothing larger of ours is there.

## The letgo image: a stereo note's right channel let go when over, and the normalizer by each take (2026-10-26, section 7 of OS 1.42)

On request).

- **The build**: `make image-letgo`, SHA-256 `dd1eb617bf092e40f772044c2780a17e07e7721c2cb2f2e63d24b23bed4d9b33`, on the tune image (level 69; audio CPU only, section 3 the tune image's, compared). `engine/sampler.h` and `engine/sampler.c`, LETGO.
- **The right let go**: `sampler_render` takes a voice that is not playing as mono when its track's right channel last block and its left are both under `LETGO_QUIET` (2^11, -120 dB of full scale 2^31), `heard` in cave k. So `rvalid` drops, the track leaves `R_MASK` at `right_mask`, and the main CPU takes the left for both sides, as for a mono note; a new note brings it back through `seed`. A slow tail that crosses nought over a whole block can let go a little louder.
- **The normalizer**: `norm_peaks` (cave al) keeps, a track, its running take's slot, link and frames (`struct pend`, `0x44078240`, free SDRAM after `struct norm`); a take is over when its track stops recording or its frames go back (a new take on the track), and its slot, link and peak wait for its turn. `norm_pick` (cave x) stops the take being scaled, or passes over a waiting one, only when a running take is in its own slots (`norm_over`, cave m: a stereo place is two slots). The end clears `KEPT[k + 1]` only for a stereo take. `norm_block` stays in cave e.
- **Held in emulation** (`tests/test_letgo.py`, 13): two scenes of eight stereo one-shots, every stage knob anywhere, track 0's sample all left: the left after the last stage the trap image's to the bit, the right as the main CPU takes it (the window's for a track in the mask, else the left) within -100 dB of full scale of the trap image's (8,327 the most, -108 dB); every track in the mask while it plays, out when quiet (a slow filter tail keeps one), back at its next note. Cost, by tracks let go: about 2,500 to 3,000 a block each, 14,600 to 20,700 a block with five to seven out; while playing at most 135 more. **Each normalizer fault first shown on the trap image's section 7, CONFIRMED**: two mono takes side by side, the second begun as the first ended, the first left part scaled; a mono take in slot 63 made the first long of slot 0's buffer 0 and cleared slot 62's mark; a stereo take cut short by the track's next trig into another place never scaled. On this image each is scaled whole, slot 0 and the mark left. The image: section 3 the tune image's, every other section but 7 the official file's.
- **Only the unit can show**: P on the maintainer's patterns (lower wherever a stereo track is silent in the heaviest blocks); nothing heard different.

## The ask image: the phone asked at LOAD PROJECT only once it has said hello (2026-10-26, section 3 of OS 1.42)

On request, of LOAD PROJECT waiting 2 s whenever any host had sent SysEx since the start (above, "Loose ends and cheap wins").

- **The build**: `make image-ask`, SHA-256 `c0326e027bde787b9a920e949d6b9e061e10b75a9cd6b01486ea7147c97210c6`, on the letgo image (level 70; main CPU only, section 7 the letgo image's, compared). `engine/phone.c` SEEN: `phone_seen`, a long in the phone's numbers' run (`mm.PHONE_VARS` had 10 bytes spare), 0 at every start (the run is loaded with the image); set by 0x63 and by a capture's 0x65 or 0x66 in `knows_sysex`; `phone_load` asks only when the sink is made and it is set. The viewer's 0x67 and 0x68, and every other host's message, leave it.
- **Held in emulation** (`tests/test_ask.py`, 8): the letgo image asks and waits with only another host's message; this one goes to stock's load straight away; after 0x63, 0x65 or 0x66 it asks and waits as the phone image does, the same 0x60 frame; 0x63 still answered; only the phone's three runs differ from the letgo image's.
- **Not looked at**: whether the phone app says 0x63 in every way it connects. Its backup at a connect does (`backUpAll`, `whichProject`); an app that only listens and never backs up would have its load come off the drive. The phone app's own `listen` saying 0x63 would close that (the phone app's side).

## The axf image: the analog tracks' second SYN page, the crossfade and the peak drawn over each other (2026-10-26, section 3 of OS 1.42)

On request.

- **The cause, CONFIRMED by stock's page drawn in emulation** (`emu/screen.py`, the active track made 8): `xfade_place` (cave l) draws the peak by `load_place`, then XF in G's place. `load_place` has put the peak in G's place since the slice image (H became KEYS on the sampling page), so on the analog tracks' page, the only caller of `xfade_place` since the xknob image, both are drawn in G. On the ask image G's dots are exactly the crossfade's and the peak's together.
- **The build**: `make image-axf`, SHA-256 `7680d3bfc3676807ee00d68ce48ce409fc8eba4bfdaf8639140a193dd16ad798`, on the ask image (level 71; main CPU only, section 7 the ask image's). `engine/recpage.c` AXF: `xfade_place` draws no peak; `apage_draw` puts it in H's place, empty on that page, by `peak_h` (cave r; cave l had 40 bytes too few for it). As the apage image had it, before the slice image.
- **Held in emulation** (`tests/test_axf.py`, 3): the analog page's G as the crossfade alone and H as the peak, the two together the ask image's G, the upper row unchanged; a sampler track's sampling page the ask image's to the dot; outside the page's two runs only addresses of routines in them that moved.
- **Only the unit can show**: that it reads clean there.

## The gainup image: the sampling page's gain in D, the peak in E, STRC in G (2026-10-26, section 3 of OS 1.42)

On request.

- **The build**: `make image-gainup`, SHA-256 `3a576090cc7c99a139baeeacd37f9935051cfb8b6e27be7183b76405ff70a897`, on the axf image (level 72; main CPU only, section 7 the axf image's). `engine/recpage.c` GAINUP: the places of the gain, STRC and the peak are named (`GAIN_AT`, `STRC_AT`, `PEAK_AT`; on older images 5, 4 and 6, the same bytes) and are 3, 6 and 4 here, in the drawing and in the turn. The peak's knob is still the one not geared (its PROF switch turns on a whole step, as on G); the gain keeps stock's plain feel, STRC too. F is empty.
- **Held in emulation** (`tests/test_gainup.py`, 3): stock's page drawn: D is the axf image's F, E its G, G its E, F the empty box D was, A to C and H unchanged; D turns the gain by the plain feel, E the profile with no gear call, G the stretch, F nothing; eight bytes differ from the axf image, the four place numbers and two branches' offsets swapped.
- **Only the unit can show**: that it reads as wanted.

## The file protocol's clear, for a new project's empty bank (2026-10-26, section 3 of OS 1.42; read only, nothing sent)

The maintainer's word, after a new project loaded with the phone came up with the old project's samples: "a neew project loaded should load n empty bank". The phone app (syntaktphone `dafb401`) now takes samples off A, so the clear request was read.

- **DataClearRequest (id 0x5C) reads a byte, then a path only when the byte is 0**: its constructor (`0x401b9c18`, built by the parser's case for 0x5C) calls the stream's byte reader (`0x401b4fba`, the one that reads DataReadOpen's last byte, its packed flag) into + 56 and branches past the string read (`0x401b5460`, into + 60) when it is not 0. READ. So a clear of one file is `00` and the path, as a C string. What a byte not 0 clears is not read: the app never sends one.
- **What a cleared slot loads as**: the bank image's loader (`engine/keeptakes.c`, `load_slots`) takes a slot whose first long is not `SAMP` as empty, and a slot the phone's answer names is read again. INFERRED that the unit's clear of `/samples/N` erases the slot's header (the sample route's erase is at the slot's address): **only the unit can show it**. If a cleared slot still plays after the load, it does not.
- Not run on the unit before his next LOAD PROJECT with the phone in.

## The onedest image: DEST only SMPL, NEXT gone (2026-10-26, section 3 of OS 1.42)

On request.

- **The build**: `make image-onedest`, SHA-256 `d426ff745710481a7fb7cba67483c2d4bea96adac72c2e8326cdd867ab0b5e5a`, on the gainup image (level 73; main CPU only, section 7 the gainup image's). `engine/recpage.c` ONEDEST: B is drawn DEST SMPL always, and a turn of it sets every track's DEST to SMPL and tells the box (`next_tell`), so no track is NEXT. The NEXT poll stays in the main task's loop and returns at once with no NEXT track (`next_vars` is in the image, 0 at every start). The page's own DEST numbers are after the page object and are not cleared by a start: a NEXT left in them is not shown, and goes at the first turn of B.
- **Held in emulation** (`tests/test_onedest.py`, 4): B reads SMPL at every turn, the box DEST_SMPL for every track, the poll holds nothing; a NEXT left from before held a place, then a turn of B dropped it and the box is SMPL; C turns KIND; only the page's runs differ from the gainup image's, and outside them addresses into them.
- **Only the unit can show**: that takes land in the SMPL place, take after take.

## The destnum image: DEST's numbers back (2026-10-26, section 3 of OS 1.42)

The maintainer's word on the onedest image: "Shouldn't Dest still have the option to record to individual slots, like numbered slots, besides just having sample? Otherwise, what's the point of having Dest sample there?", then "numbers back".

- **The build**: `make image-destnum`, SHA-256 `2fa46f4fd22d415149fb4426dbd89eb09c642d0cf10f7a163b94c098275c2fa3`, on the onedest image (level 74; main CPU only, section 7 the onedest image's). `engine/recpage.c` DESTNUM: B is SMPL (0) or a place's number, 1 to 32 the stereo places, 33 to 64 the single slots, as up to the next image. A turn steps through SMPL and then SMPL's own stops by the track's KIND (`dest_moved` in the kind image's run: `stops`, then `kind_stops`): STER the stereo places with a sample and the lowest free one, MONO the highest free single slot and those with a sample. With no word from the audio CPU yet it does not move. The box gets the number less 1 (`next_tell`, which no longer makes a track NEXT); a turn of KIND puts a DEST of the other kind back to SMPL. Not saved, not lockable, SMPL after a start, as DEST always was.
- **Held in emulation** (`tests/test_destnum.py`, 5): on a bank of stereo places 1 to 3 and singles 63 and 64, a STER track's B reads 01, 02, 03, 04 and no further, the box 0 to 3, and back to SMPL; a MONO track's 62, 63, 64; KIND turned drops 02 to SMPL and keeps 62; the poll holds nothing and leaves the number; only the page's runs differ from the onedest image's, and outside them addresses into them.
- **Only the unit can show**: that a take lands in the place DEST names while SMPL stays where it is.

## A new project never asked the phone, and the fresh image (2026-10-26, section 3 of OS 1.42; read from the listing)

The maintainer's word, with the phone app's empty bank for a new project (syntaktphone `dafb401`) on his phone: "when im starting a new project sitll and im on sample bank a its ust carrying over the full bank still from the last project it should give me a fresh empty bank eith evrything tracked on pohne".

- **Read from stock's listing**: the Project Load job's body (`0x4005bafa`) asks the store whether the project is there (`0x401104fe`). When it is, it loads it at `0x4005bba8`, the call our load and the phone's ask hang on. When it is not (`beq 0x4005bbfa`) and the job's flag at + 12 is set, it makes a new project (`0x4001d16a`, (manager, project)), starts the progress (`0x4016fe9e`) and saves it (`0x4005bc2c`, the second of the two save calls the keep image takes), and never calls the load. **So a new project made by loading an empty slot never asked the phone**: the samples stayed as they were, and the phone's next look filed all of A under the new project as its own.
- **The build**: `make image-fresh`, SHA-256 `f11be87e9fc486ceb6b16583c55554174c4b46cf3aa13512dba9e792a47a2a7f`, on the destnum image (level 75; main CPU only, section 7 the destnum image's). The second save call goes to `fresh_save` (`engine/phone.c` FRESH, in a run of its own, `mm.CAVE_FRESH`, 312 bytes nothing reaches or names): the keep image's save as before; then, once it went well, with the phone's hello since the start (the ask image's `phone_seen`) the new project is a load (`knows_load`: counted, the phone asked and waited for, then stock's load of the project just saved and the slots the phone names); the ask's bank byte has 128 added (its bit in the high-bits byte before it, `phone_frame[14]`), which says the project is new. With no hello the project is counted (0x64 says it) and nothing is asked or loaded. A save that failed is all there is.
- **Held in emulation** (`tests/test_fresh.py`, 4, with test_phone's rig: stock's routines around it played): after a hello, save, then the ask with the mark, then the load, and the next ordinary ask has no mark; with none, save and count only, 0x64 then says project 5, bank 2, one load; a failed save is all; the image is the destnum image's but for the new run and the call's address.
- **The phone** (syntaktphone `777beab`): an ask with the mark is a new project whatever its lists say. A bank under the project's number (a project gone from the unit) is kept by another name and unlinked; A's samples no bank has yet go into a bank of their own first ("kept before project N, date"), then A is emptied. Store tests `swap-marked` and `swap-lost`.
- **Only the unit can show**: that stock's load of a project just made and saved is harmless there (the same call, arguments and progress as an existing project's load), and that the cleared slots come up empty.

## NEW PROJECT never asked the phone either, and the newproj image (2026-10-27, section 3 of OS 1.42; read from the listing)

The maintainer's word on the fresh image: "i satrt a new project and it stil has the odl samples, ive made. abunch of new projects check the aoppo". The phone app's files (devicectl, read only): no load since the fresh image's one ask for project 13 but one more of 13, and the unit lists projects 1 to 13 only, so his new projects were never slots.

- **Read from stock's listing**: the project job maker (`0x4005d702`, called from `0x4005d4a2`) goes by the project's number (+ 4): 0 or more makes the "Project Load" job (`0x4005bafa`, the fresh image's way); below 0 the "Project Init" job (name `0x40250258`, its screen INITIALIZING PROJECT), whose body (`0x40059f9e`) calls the project maker (`0x4001d16a`) with -1 and neither saves nor loads. **That is NEW PROJECT**: a project of no number (`0x40018c2c` reads -1) till it is saved. The maker is named three times: Project Init's call (`0x40059fd6`), Project Load's for a slot that is empty (`0x4005bc10`) and `0x400c1a58` (not looked at, not hooked).
- **The build**: `make image-newproj`, SHA-256 `eacab261c7404a284ddba4f6e71bb7c6a2a43bf19612944ba08026e67e56769c`, on the fresh image (level 76; main CPU only, section 7 the fresh image's). `engine/phone.c` NEWPROJ, in two runs nothing reaches or names (`mm.CAVE_NEWPROJ`, `mm.CAVE_NEWPROJ2`), and `new_slots` in the banks' run (`engine/keeptakes.c`):
  - both calls of the maker go to `fresh_make`: the project left read first, then the maker; for -1 (NEW PROJECT), counted as a load of no project (0x64 says 0x3fff) and, after the phone's hello, an ask of project 0x3fff marked new, the wait, and the slots the phone names loaded as LOAD PROJECT loads them, the held takes dropped as a load drops them (`new_slots`: `scratch_drop`, `load_slots` with no progress);
  - an empty slot's new project asks after its save, as on the fresh image, `fresh_save` now counting it itself so the project left stays `fresh_make`'s;
  - LOAD PROJECT's call goes to `fresh_load`: the project left, then the fltr image's `knows_load`;
  - **the ask is two bytes longer: the project the load leaves**, 2 x 7 bits, 7f 7f for one never saved (`left_is`, bytes 16 and 17 of a 19-byte frame). An app that reads three bytes is not troubled by them.
- **Held in emulation** (`tests/test_newproj.py`, 7, test_phone's rig): NEW PROJECT after a hello is made, asked for as 0x3fff marked new saying project 9 left, waited for, its slots loaded, counted as no project, the mark gone after; with no hello made and counted only; an empty slot's asks only after its save, saying the project left; LOAD PROJECT says 9, 130, or 7f 7f for one never saved; the image is the fresh image's but for the phone's runs, the banks' run, the new runs, the three calls and addresses into them. **The fresh image built again from this source is `f11be87e...` to the byte** (a slip in this change had dropped its save call's patch, caught by this test).
- **The phone** (syntaktphone `68e42bb`): the project left is the unit's word when it says it; A all goes into its bank when the phone filled A for it and no load went by, else only what no bank has; a project of no number is no project on A after; with no project known left, what no bank has goes into a bank of its own first. Store tests `swap-newproj`, `swap-saved`.
- **Only the unit can show**: that the Project Init job may wait on the phone as the Project Load job does, that `new_slots` with no progress object runs there, the clear (the app falls back to an empty sample, and logs each slot in Documents/loads.log).

## The phone's writes go unanswered during a load, and the wipe image (2026-10-27, section 3 of OS 1.42)

The maintainer's word on the newproj image: "it gets stuck on intizlifin project and says loading th eprjoect, tkaing off slot 1 on the app", then "it gave an error that said, Could not take slots 1 through 64 off the Syntakt. Now the Syntakt is still stuck on Initializing project", and "cant it just clear the space instead of having to take off the old ones cuz its already backed up?".

- **On the unit (the phone app's Documents/loads.log, devicectl, read only)**: NEW PROJECT asked the phone (the newproj image works so far); the phone read all of A while the Project Init job waited (its backup before the load holds 64 slots); then its clear of slot 1 went unanswered for 20 s, and its write of an empty sample in each slot after it unanswered too (3 s each); the job stayed on INITIALIZING PROJECT after the phone's done frame. **So while a project job waits on the phone the unit serves the phone's reads and not its clears or writes, and a clear sent then can leave the unit stuck.** Not read: what holds them (INFERRED: the writes wait on the job that waits on us). The fresh image's first try (2026-10-26) was the same clear, unanswered in 3 s.
- **The build**: `make image-wipe`, SHA-256 `c1821141711fab8f2ff99b475cc9184dbba991c5d37c3801a73fb124b49eb3a9`, on the newproj image (level 77; main CPU only, section 7 the newproj image's). `engine/phone.c` WIPE, in two runs nothing reaches or names (`mm.CAVE_WIPE`, `mm.CAVE_WIPE2`): the SysEx entry goes to `wipe_sysex`, which takes **0x6A** (ten bytes of 7 bits, the slots to empty, as the done frame's) while a job waits, as the wait's answer; after the wait, in the job, `wipe_now` writes each named slot's first sector with zeros (its header: the loader, the scan and the boot take it as empty) with the store's write (`0x40111628`, as engine/scratch.c and engine/banks.c write on the unit), only when the drive is on the bank the phone was asked about, reads the headers again (`scan_all`), and the slots are loaded as the phone's are (NEW PROJECT's `new_slots`, LOAD PROJECT's load through `wipe_load`).
- **Held in emulation** (`tests/test_wipe.py`, 7): 0x6A while a job waits gives the wait the slots and marks them, with none waiting it is stock's; NEW PROJECT zeroes slots 0, 2, 33 and 63's headers (512 bytes of zeros at 8,192 + 2,048 a slot), reads the headers, loads them; with none named nothing is written; LOAD PROJECT the same before the load, and nothing when the wait was on another bank; the image is the newproj image's but for the phone's runs, the new runs and the SysEx entry.
- **The phone** (syntaktphone `1d18fdd`): a load never writes or clears. The slots to empty (the samples the project has none of, each in a bank of the phone) go as 0x6A, then the done frame as before (older images take that and ignore 0x6A); a project whose own samples would have to be written leaves A whole, and the log says so. **Putting a project's own samples on A at its load is not done on the unit**: the writes would have to come after the load, with a word to the unit to load those slots then (not built).
- **Only the unit can show**: the store's write from inside the project job, the slots then empty, nothing stuck.

## A project's samples written after its load, and the stream image (2026-10-27, section 3 of OS 1.42)

The maintainer's word on the wipe image: NEW PROJECT came up empty, then "I recorded into that and saved the project with one sample recorded. Then I went back and tried to load another project ... That sample that I recorded carried over". The phone app's log: LOAD PROJECT 8 asked, 38 of its samples not on A, none written (no write is served while the load waits), A left as it was. The maintainer's word on the way out: "build the stream-in: wipe the wrong slots at the load, phone pushes the project's samples right after".

- **The build**: `make image-stream`, SHA-256 `67a3dfed80b0c4142d9193cbfffbd5776159e84430bfa9dd49ac24ba1c3a58da`, on the wipe image (level 78; main CPU only, section 7 the wipe image's). `engine/phone.c` and `engine/keeptakes.c` STREAM, in four runs nothing reaches or names (`mm.CAVE_STREAM` to `CAVE_STREAM4`), and one test more in the bank loader (`load_slots`, cave b, 1,712 bytes did not fit: the take check went to the job).
- **LOAD PROJECT's end** (`stream_load`, the load call's target): the load as before (`fresh_load`), then, when the phone answered it and it loaded, the ask frame once more with **0x6C** in its id's place (project and bank as asked), from the load job, through the sink the ask uses.
- **0x6B** (`stream_sysex`, the SysEx entry's target; any other frame to `wipe_sysex` as before), at any time: ten bytes of 7 bits, slots. They are ORed into a mask of ours by one `or.l` each (one instruction: no task switch inside it), and a job "Sample Load" is handed to stock's runner (`0x400bdc48`, from the SysEx entry's task: it takes its own lock) unless one is queued or running (`stream_add`).
- **The job** (`stream_body`, on the runner's one worker, so never beside a load, a save or a take's hold): takes the mask (read, then cleared by one `and.l` of what was read, so a 0x6B meanwhile is kept), asks the audio CPU of each slot (`put(slot, 0)`) and drops any holding a take the drive does not have, puts the rest in the phone's mask (no load waits on it while the worker is ours) and runs the bank loader with `stream_now` set: the named slots read from the drive and sent as a load sends them, every other slot passed over (no take dropped, as a load drops them). Again while more came, then it lets go and looks once more. While it runs the feed is kept out (`BANK_BUSY`), as in any load: a take running then has a gap.
- **Held in emulation** (`tests/test_stream.py`, 8): an answered LOAD PROJECT ends with the 0x6C frame, the ask's byte back to 0x60 after; not answered, nothing; 0x6B sets the mask and starts one job, a second while it is queued joins it; 0x6A and other frames go on as before; the job keeps slot 33 (a take not saved), loads 0, 2 and 63, then slot 5 named while it ran, and ends with everything 0; the loader with `stream_now` reads and sends slots 2 and 33 alone, and without it asks every other slot as the wipe image did; the image differs from the wipe image's only in the runs, addresses into them, the SysEx entry and the load call.
- **The phone** (syntaktphone `e51184b`, installed): at LOAD PROJECT on A every slot that is to get the project's sample and holds another (in a bank of the phone) is emptied with the rest (0x6A); after the answer it waits up to 60 s for 0x6C, then writes each sample and names its slot (0x6B). A slot that is not empty when its turn comes (recorded into and saved since the load) is left; a new ask stops it. No 0x6C (an older image): the samples are written and named at the next load's answer. The fake unit refuses writes during the wait as the maintainer's unit does (store test `swap-stream`).
- **Only the unit can show**: that a write after the job is answered, that a job started from the SysEx entry's task runs, how long a project's samples take (about 180 KB/s by slink), and that a sample loaded while the sequencer plays does not click or stop a note.

## A phone reload loads over a take not saved, and the evict image (2026-10-28, section 3 of OS 1.42)

- **The maintainer's word** (2026-10-28), of the stream image's reload keeping a slot that holds a take not saved: "the reload should just wipe that take and put what should be there in place". The phone app (`6c42687`) now names each slot it writes on a Send or a restore too, so the rule reaches every write.
- **A load drops a take by itself**: the audio CPU's `load_step` sets `KEPT[k]` from the frames loaded (`engine/sampler.c`), so the slot reads as one the drive has, as LOAD PROJECT's reload of a take's slot always did. The stream image's skip was the only thing keeping it.
- **A fault of the stream image, read in the source, not seen on the unit**: the scratch image holds a take not saved in a place on the drive and marks it kept, so the stream image's skip passed over it, the slot was loaded, and the place stayed in the table. A save (`scratch_commit`) would then copy the old take into the bank over the phone's sample, and a start (`back_body`) would send it back to the slot. LOAD PROJECT's own stream was safe: `scratch_drop` empties the table first.
- **The evict image** (`93071f53...`; main CPU only; on the stream image; level 79): `stream_body` loads every slot named, and first `scratch_forget` (`engine/scratch.c` EVICT, `mm.CAVE_EVICT`, 170 bytes named by nothing, rts at both ends) empties the places of the slots in the phone's mask, on the loaded bank's table only, writing the table only when one went.
- **Held in emulation** (`tests/test_evict.py`, 5): the job hands every slot named to the loader, after their places are dropped, with a take in each; the places of the named slots emptied and the rest kept; nothing written when none is theirs or the table is another bank's; the image is the stream image's but for the reload's runs and the new one.
- **Only the unit can show**: a Send over a take not saved heard at once, and after a SAVE and a power cycle the phone's sample still there, not the take.

## The first step's ONCE on the first pass after a start, and the playrec image (2026-10-30, section 3 of OS 1.42)

- **The maintainer's word** (2026-10-30): "the first time the sequence plays (if you hit play and there is a record trigger on the first step), it doesn't trigger till the next time. If it did trigger right away, then I could just use the play button as the record button." This answers the stay image's open question (which caller plays the first step at a start): not the sequencer's.
- **WRONG, found 2026-10-30 on the unit (below): `0x4008c300` is STOP, not the start.** It sends MIDI `0xFC` (`pea 0xfc` at `0x4008c358`) and sets state 2; the start is where state 1 is stored after MIDI `0xFA` (`0x4008ad40`, `0x4008ad50`; and `0x4008b602`). So STOP brings every track's held parameters back to the first step, and the playrec image's hook makes that a play: a ONCE on the first step is spent at STOP with no take. **The playrec image is not to be kept.** What follows is as written then.
- **The start, read in the listing**: `0x4008c300` runs only when `0x400a2f54` says the sequencer is not running (`bnew 0x4008c404`), masks interrupts, clears the counts (`0x43bd84dc`, `0x43bd850c`), sets state 2 for the sequencer and the 13 tracks (`0x43bd83bc`, `0x43bd83c8` on), stores the tick count (`0x43bd845c`), and its last act is `jsr %pc@(0x4008c128)` with -1 at `0x4008c3fe`: the step the sequencer is on, played for every track by the stay image's other caller. Reached from the UI (`0x40046ed8`) and by a jump at `0x4010423e`. **INFERRED, with his report: on the first pass that is the first step's only play**; the sequencer's own caller (`0x4008cf86`) plays it from the second pass on.
- So since the stay image nothing of ours ran for the first step at a start: a ONCE there was not spent (the stay image's guard), a track's own ONCE waited for the step after, and no mark of ours was put where the block's slot 24 is made from. **Not known: why stock's own apply of the event (which has the lock, gathered as ever) did not make the first note record.** Read, not run: the sequencer's start does not run in emulation.
- **The playrec image** (`19cabd13...`; main CPU only; on the evict image; level 80): the start's call at `0x4008c3fe` goes to `once_start` (`mm.START_NOW`, four bytes, `jsr %pc@`), which sets `once_go` around stock's call. While it is set the stay image's other caller is a play: a ONCE is spent, a track's own ONCE used up, and a step that records has `0x5280` written at slot 24 of its track in `PARAM_WORDS` (`once_mark`, `engine/once.S` PLAYREC), where recword.S makes the block's slot 24 from. Outside the start the stay image is as it was. Cost: nothing a block; at a press of PLAY, the start's pass and 3 instructions a recording step.
- **Held in emulation** (`tests/test_playrec.py`, 10), stock's step routine run as it is: in the start's pass a ONCE on the first step (and on step 10) is spent, its track's byte for the main task set, the mark at its track's slot 24 and no other; outside it a change spends nothing and marks nothing; the sequencer's own play marks nothing; a track's own ONCE is used up on a step with locks and one without; a step locked off marks nothing; `once_start` has the flag set in the call and clear after; section 3 differs from the evict image's only in the once run, the start's operand and the two operands into the run that moved; section 7 not at all.
- **Only the unit can show**: a take from the first note after PLAY with a ONCE on the first step, one take only (not a second on the next pass), and the same with REC at ONCE on the page and no lock. If there is still no take on the first pass, the mark is not what the first note is sent with, and the cause is elsewhere. The way back is the evict image.
- **The second build** (`c9712b9b...`, 2026-10-30), from the recprobe tool's readings (the hardware log of 2026-10-30): a start queues, for each track whose record has a trig, the record the other caller built last (`0x4008b52a`, `0x4008b0ea`: 80 bytes from `mm.SEQ_PLACES` + 80 t, its lock buffer at + 68), and the step routine first plays the second step. That record held the ONCE and `PARAM_WORDS` had `52C0` after the first step: **the first pass recorded, and the second recorded over it**, the ONCE never spent where the first was played (the stay image's own warning: two takes). Now the other caller's step and table are kept a track (`once_keep`; 0 for a step with no locks), a start's store of state 1 (`mm.SEQ_STARTS`) goes through `once_atstart`, which on each sampler track with a trig queued spends a ONCE on that step (the record's buffer keeps its copy, so this pass records), and the sequencer's next play on the track sets the byte the main task takes it off by (`once_late`: not at the start, where taking it off would have a listener rebuild the buffer the queued record points at). STOP is stock's again. Its own in the long image's run (`mm.CAVE_LONG`, nothing of this chain uses it). Cost: the start, 8 tracks once; the other caller and the sequencer's plays with an event, a few instructions. `tests/test_playrec.py` (8). **Only the unit can show: one take, the first pass's.** A track's own ONCE (REC at ONCE on the page) is as before: it records from the next step the sequencer plays with a trig, not the first.
- **The third build** (`446ce1a6...`, 2026-10-30), for the maintainer's word on the second (below): the first pass records and the ONCE is spent at the start, and the second pass still records over it. **INFERRED: the mark the queued record brings is held, not taken back at the track's next trig** as a played step's lock is, so each later trig on the track starts a take again. The sequencer's first play on the track after such a start (`once_late`) now gets a lock of slot 24 at `LOCK_SPENT` (no mark) unless the event has a lock of slot 24 of its own or the track's own ONCE is armed: the take ends there, at the track's next event, as a step locked on's does, and stock's own apply puts the word back. A step locked ON (an old pattern's) at the start's step gets the same, nothing spent. `tests/test_playrec.py` (11). **Only the unit can show: one take, from the first step to the track's next trig on the first pass.**

## A note played by hand while stopped records, and the handrec image (2026-10-30, section 3 of OS 1.42)

- **The maintainer's word**, after the playrec image's third build still kept the second pass's take: "this is too complicared, couldnt we just make it so if i trig the trig when the seq is stopped but rec is armed it starts rec". Tried on the unit before it (on request): with REC at ONCE on the sampling page, a note played by hand while stopped records nothing. **The playrec image (level 80) is dropped**, never kept; why the second pass still recorded on its third build is not known.
- **Why, read in the source**: the track's own ONCE (its byte of `once_vars`, `mm.ONCE_ARM`) was only ever used where the sequencer plays a step (`engine/once.S`); recword.S, which makes slot 24 of the block the audio CPU is sent every block, gives a step's lock's mark or else the track's REC bit (bit 0 of its word), never the ONCE. A note played by hand is a note like any (the audio CPU's `note_on` reads slot 24 of that block), so it never recorded.
- **The handrec image** (`d451f958...`; main CPU only; on the evict image; level 81): where slot 24 holds no lock's mark, recword.S calls `hand_rec` (`mm.HAND_REC`, first in the once run after its sixteen bytes, so recword.S is built to it before once.S is): the track's REC, or, with the sequencer not playing (`mm.SEQ_STATE` not 1: 2 after STOP, 0 before any start), its ONCE byte. A start's two stores of state 1 (`mm.SEQ_STARTS`) go through `hand_start`, which clears the eight ONCE bytes: armed while stopped is for a note played by hand. Cost: the per-block routine, 6 instructions more a sampler track with no lock's mark and REC off (12 when stopped); the feed runs while a track is stopped and armed, as for REC on.
- **Held in emulation** (`tests/test_handrec.py`, 13), recword.S run as it is with the once run beside it: stopped (or never started) and at ONCE the mark is REC's; another track's ONCE is not; playing it is the track's REC as before; REC on is on either way; a step's own lock still decides; only slot 24 of the block changes; `hand_start` stores the state and clears the eight bytes (the spent bytes after them kept), registers kept; section 3 differs from the evict image's only in the once run, recword's run, the two stores of the state and the three calls into the once run (it moved); section 7 not at all.
- **Only the unit can show**: that a note played by hand (keys, or the preview) records while stopped and armed, and how long its take is: a note's release ends a take (`rec_step`), so a held key may be the take's length. Every hit while stopped and armed records again into the same place, the last one kept; PLAY takes the ONCE back. Once after one hit is not built: it needs the hit seen in the block. The way back is the evict image.
- **On the unit, the first build** (`d451f958...`): a note played by hand "recs a short blip" and REC stays at ONCE; the maintainer's word: the take "should run the length of the trig length", the TRIG page's.
- **The trig's LEN, read in the listing.** The TRIG page's records are 20 to 28 and 33 (`0x4022d83c` + 52 a record; record 23 "Trig Length", type `0x3d`, trig setting 2, 0 to 127, 14 by default). A track's trig settings are 1,177 bytes a track from the pattern's data (`*0x43bd8430`, the step routine's second argument): a step's own at + 64 k + step, 0xff for none, the track's own after them. The step routine (`0x4008ba7e`) reads a step's LEN at + 192 + step and, at 0xff, the track's at **+ 961** (the TRIG page's), and takes its length from stock's table at `0x401e95ac` + 4 + 4 LEN (`0x4008bc9e`): 168,750 a unit at the low end, **LEN 14 (the default) 2,700,000**, which is one step at 120 BPM in the tempo's units (`0x402d7360`, BPM x 120, added to a phase every block: 21,600,000 a second, 2,700,000 an eighth of one). So a length counted down by the tempo every block follows a tempo change. INFERRED: + 961 is what the TRIG page turns with no step held.
- **A take ends at its note's release** on the audio CPU (`rec_all`, the release mask), and a stock trig's mask and release mask are the per-block routine's `a5` and `d4` where recword.S is called (`0x400a4c6a`; the loop before `0x400a4c88`, which hands them to the envelope; a block with `0x43bdd4c8` at 2 is every track let go and none trigged). The release that reaches the audio CPU is packed before that loop, so the main CPU cannot hold it back there.
- **The second build** (`432feaa2...`; both CPUs; level 81): `hand_rec` (`mm.HAND_REC`, in the long image's run with its numbers, `mm.HAND_HOLD`, `mm.HAND_LEFT`): stopped and at ONCE the mark waits for the note; the block whose `a5` has the track takes the ONCE (REC reads OFF), sets the track's hold bit and what is left of the take, the TRIG page's LEN's length; each block takes the tempo off it, and at nothing the mark goes and the feed with it, which ends the take (no more blocks). The feed puts the hold bits in the high byte of the window's word at `0x802` (`engine/recfeed.c` HANDREC); `rec_all` ignores a release on a held track (`engine/stub.S` HANDREC, 8 bytes in its run, 18 left). A start clears it all. Cost: the main CPU, about 20 instructions a sampler track a block while one is held or armed, fewer otherwise; the audio CPU, 4 instructions a block.
- **Held in emulation** (`tests/test_handrec.py`, 11): the table's LEN 14 is 2,700,000; for LEN 0, 14 and 30, the mark waits, the note takes the ONCE and holds the take as many blocks as its length takes at the tempo, then the mark and the hold go; another track's ONCE and note are its own; playing it is the sequencer's as before; a step's own lock still decides; a start clears the ONCE bytes and the held takes, the spent bytes kept, registers kept; on the audio CPU (its emulation, `rec_all` as built), a held take goes on past its release block by block and an unheld one ends there; section 3 differs from the evict image's only in its runs and the places that call into them, section 7 only in `rec_all`'s run.
- **Only the unit can show**: that a note played by hand is in stock's trig mask as a sequencer's is (else the take is held from the next note, or never), that + 961 is the TRIG page's LEN, the length by ear. A second note while a take is held starts it again from that note, and it ends when the first one's length is over.

## The first step's ONCE on the first pass, again: the firstrec image (2026-10-30, section 3 of OS 1.42)

- **The maintainer's word** on the handrec image's second build: "yes it works now, still not surte why it cant work on the first pass", then "Yes, build it".
- **Why the playrec image's three builds kept the second pass's take, INFERRED**: on the handrec image's first build "the record button switches off right when I start the sequence" (`hand_start` clearing the track's own ONCE), so the page's REC was at ONCE as well as the step's lock. The track's own ONCE is used up at the first step the sequencer plays itself with an event, which on a track with one trig is the second pass's first; no playrec build touched it. The step's ONCE was spent at the start by the second build (the maintainer's word: the lock gone by step 8, "half lap take seesms to record").
- **The firstrec image** (`60ea94c0...`; main CPU only; on the handrec image, so one flash carries handrec, evict and stream; level 82): the other caller's step is kept a track (`first_keep`, 0xff for a step with no locks; in the once run with `first_late` and their 24 bytes); `hand_start` calls `first_spend` (in the long image's run), which on each sampler track whose record a start queues has a trig (`mm.SEQ_PLACES` + 80 t + 4) spends a ONCE on that step's row (`*mm.PATTERN_DATA` + 15301 + 9287 t + 144 step, as the step routine has it); `first_late`, at the sequencer's own play of that same step, has the main task take the spent lock off: that event has it, no mark, so nothing records and nothing held from the first pass goes on. The handrec image's taking of the page's ONCE at a start stays. Cost: a start, 8 tracks once; a step played, a few instructions.
- **Held in emulation** (`tests/test_firstrec.py`, 9), stock's step routine run as it is: a ONCE on the first step (and step 10) stays through STOP's and a listener's passes; a start spends it and marks it; the sequencer's next step leaves it; its own play of the step a pass on gathers the spent word and has it taken off; nothing where no trig is queued, the step is locked on or off, has no locks, or the track holds no sampler; a start still clears the page's ONCE and a held hand take; the sequencer's own play spends as before; section 3 differs from the handrec image's only in its runs and the calls into them; section 7 not at all.
- **Only the unit can show**: one take with a ONCE on the first step and PLAY, the first pass's. If the second pass still records, the inference above is wrong. The way back is the handrec image.
- **On the unit (2026-10-30): "Still lap 2". The inference is wrong**: with the step's ONCE spent at the start and the page's ONCE taken at the start, the second pass still records. What starts that take is not known; nothing on the main CPU read so far explains it, and no reading of the audio CPU's take starts was ever made. **Then, on request: kept.** The way back is the handrec image. Six builds and three probes went to this; the next step, if any, is a probe of the audio CPU's own take starts (which note, which pass), not another fix.

## Hardware log

Kept privately. What each image did on a unit is summed up with it in `docs/SAMPLER.md` and `docs/REPORT.md`.
