# Memory map: audio CPU (section 7)

Syntakt OS 1.41 and 1.42 (section 7 is identical, SHA-256 `daf6451c.783bc2`).
Source: our objdump listing of the pinned section. Constants live in `tools/audiomap.py`, each re-checked by `tests/test_audio_map.py`.

CPU: ColdFire ISA C with EMAC. The code uses FF1 (not in ISA B) and the peripheral addresses (`0xFC04xxxx` eDMA and interrupt controller, `0xFC05C000` SPI, `0xEC09xxxx` pin control) fit the MCF5441x family. Compile with `-mcpu=54418`, disassemble with `-m m68k:isa-c:emac`. The exact part number is not proven.

## SDRAM `0x40000000.0x48000000` (128 MB)

Size evidence: initial SP is `0x48000000` (entry `0x40001070`), and ACR0 is set to cover `0x40000000.0x47FFFFFF`. Not measured on hardware.

| Range | Size | What |
|---|---|---|
| `0x40000000.0x40000400` | 1 KB | below the image, not used by section 7 code |

## Shared window `0x0.0x1000` (audio CPU) = `0x10000000.` (main CPU)

| Range | What |
|---|---|
| `0x000.0x1b0` | parameter block from the main CPU, copied to `0x80008000` every block. During the boot handshake the first words are status. |
| `0x1b0.0x5b0` | the 8 mono track buffers, sent by eDMA channel 47 at the end of every block |
| `0x5b0.0x800` | no use found. The stereo image: a long at `0x5b0` that says which tracks have a right channel, and nine halves of a right channel, 64 bytes each, from `0x5c0` (on the unit, 2026-10-11: the right channels cross, by the maintainer's ear) |
| `0x5b4`, `0x5b8` | *(the time image, a tool)* two longs the audio CPU writes every 256 blocks, a letter and three figures each: the longest it worked on a block in hundredths of one, and the most of late |
| `0x5bc` | *(the stops image)* the mark of what the audio CPU says the slots hold: moved up a byte a block with `0xa5` under it, so `0xa5a5a5a5` after four blocks. The main CPU sets it to 0 while the audio CPU is down |
| `0x808`, `0x80c`, `0xe38`, `0xe3c` | *(the stops image)* four longs the audio CPU writes, one a block: two bits a slot, sixteen slots a long, the first slot's bits the highest (the length's lowest bit, then whether anything is left without it). In the recorder's header after its count and random number, and after the sampling page's box: the window's last free bytes but two at `0x802` |
| `0x800.0xc10` | *(the multi image)* the ring is no ring: the long at `0x800` is the main CPU's count and, in the word under it (`0x802`, the window's last two free bytes), a bit a track whose block it wrote with that count; track t's block of 32 stereo frames is at `0x810 + 128 t`. Read by the audio CPU before the voice loop |
| `0x800.0x1000` | 2 KB sample chunk, boot only. The recorder image uses `0x800.0xc10` after boot: a counter and a ring of 8 blocks of 32 stereo frames, written by the main CPU. The keep box is at `0xc10`, the sampling page's at `0xe20`. The stereo image: seven more halves of a right channel in `0xe40.0x1000` |

What is behind the window is not identified. It is chip select 0 of both CPUs, set up as a 16-bit port with one wait state (`docs/FINDINGS.md`, "One-track stereo: the stereo image"). Layout of the parameter block: `docs/FINDINGS.md`, Phase 4.

| `0x40000400.0x40000404` | 4 | entry pointer (`0x40001070`) |
| `0x40000404.0x40009f88` | 39.8 KB | **all the code**: boot, audio interrupt, voice loop, 12 engines, sample loader |
| `0x40009f88.0x4004f6e0` | 284 KB | tables and initialised data (engine tables at `0x400148f0`, wave tables, writable variables from `0x40040050`) |
| `0x40040060.0x40041060` | 4 KB | drive-stage table, 1,024 longs, the upper half zeros. Not free. |
| `0x40041060.0x40041e67` | 3.6 KB | packed bitstream for the audio CPU's own FPGA |
| `0x40042000.0x4004f588` | 53.4 KB | where that bitstream is unpacked at init (54,664 bytes). Zeros in the file. |
| `0x4004f588.0x4004f6e0` | 344 B | unused tail of that buffer |
| `0x4004f6e0.0x40057670` | 32.6 KB | boot image of SRAM `0x80000000`; **reused as BSS after the copy** |
| `0x40057670.0x4005df10` | 26.8 KB | boot image of SRAM `0x80008000`; reused as BSS |
| `0x4004f6e0.0x4404f980` | 64 MB + 672 B | **BSS**, zeroed at boot (`0x40000512`) |
| `0x4004f6e0.0x4004f750` | 112 B | BSS variables. `0x4004f6e0` holds the pointer to the status block shared with the main CPU |
| `0x4004f750.0x4404f750` | **64 MB** | **sample pool** |
| `0x4404f750` | 4 | pool reload flag |
| `0x4404f754.0x4404f954` | 512 B | **slot table**, 64 entries of `{u32 frames, u32 pointer}` |
| `0x4404f954.0x4404f980` | 44 B | noise seeds and small state |
| `0x44050000.0x44050380` | 896 B | *(with the sampler installed)* right-channel buffers waiting for the end of the voice loop |
| `0x44050000.0x44050960` | 2.4 KB | *(the stereo image)* eight of them, then a mask (`0x44050400`), the overdrive's state as the left found it (`0x44050410`), the amp envelope's (`0x440504b0`), and the right channels' copy of stock's filter memory, in its shape (`0x44050550`, which is `0x80008550`) |
| `0x44050a00.0x44050a18` | 24 B | *(the time image, a tool)* the count at this interrupt's start, the longest stretch, the gaps' sum, blocks, the most of this stretch of lots and of the one before |
| `0x44050a18` | 4 B | *(the stops image)* a count of blocks: its two lowest bits say which sixteen slots are said this block. Any number will do at a start |
| `0x44061000.0x44061840` | 2.1 KB | *(the stereo image, second build)* the interpolation table as 33 rows of 16 longs, each number shifted up 15, made at every start. The pitch image's rows of words are at `0x44060004` and the voices' frames around their slots' ends at `0x44060800.0x44061000`; this build makes the longs and not the words |
| `0x44062000.0x44066000` | 16 KB | *(the cross image)* a voice's blend for its loop's seam, 2 KB a voice: four longs (the seam's wall, the place it leads to, where a pass goes in, the position of the first frame), then 352 frames of 16 bits for the left and 352 for the right. Believed only while the count in the voice's state says they are written |
| `0x44066000.0x4406a000` | 16 KB | *(the scan image)* a slot's scan state, 256 bytes a slot: both followers in 256ths, the loudest step from frame to frame, the followers where the last hit began, a bin a hit of how sharp it is. Believed only with the slot's hits |
| `0x44070000.0x44078000` | 32 KB | *(the hits image)* a slot's hits, 512 bytes a slot: its place, frames, a print of 16 frames, frames gone over, the follower, a gap, a count, then up to 123 longs (frame << 8, how loud). Believed only while place, frames and print are the slot's |
| `0x44078000.0x44078084` | 132 B | *(the hits image)* a voice's place among its slot's hits, 16 bytes a voice, then the slot gone over in turn. Any number will do at a start |
| `0x4404f980.0x48000000` | **63.7 MB** | **free**. No instruction in section 7 references it. The stack grows down from the top; its depth is not measured, so leave the top megabyte alone. |

Audio CPU code room, the mode and cross images (2026-10-12): the mode image does not compile the chained slots' code (300 bytes) and holds the table's twelve numbers a row (136). The cross image takes 600, the last small run `0x40004608.0x40004674` among them (the time image's routine has the first and third; the fourth is not room). 318 bytes are left, in 20 pieces, the largest 44. **The pack image (2026-10-12) leaves 300 bytes in 18 pieces, the largest 44**: a note's start grew by 28 bytes and the time image's hook (28) moved from its run to the last 28 free bytes of run `i` (`0x40005624`); the take's routine, written by hand, is 208 bytes where the compiler's was 224 (run `r`, `0x40004708`); the routine that looks a slot up grew by 6. **The stops image (2026-10-12) leaves 218 bytes in 17 pieces, the largest 30**: what every slot holds is said by 72 bytes in the last 40 of run `q` (`0x400028e6`) and 32 of run `p`'s last 44 (`0x40001834`), the hook's return became a branch to it (2 bytes, run `y`), and the take's routine grew by 8 (run `r`). **The multi image (2026-10-13) leaves 268 bytes in 17 pieces, the largest 52**: the take's routine is 200 bytes where it was 216 (run `r`, 26 left), the post step lost its loop and the table's lines are written from its run (run `p`, 52 left), and the hook grew by a call (run `y`, 4 left). SWARM is not used: its 1,360 bytes are still stock's.

Main CPU, the gain image: after the meter's four numbers at `0x40088510`, the gain the page shows (`0x40088520`, a long) and a record gain a track (`0x40088524`, eight bytes), in the feed's own run of code: loaded with the program, so 0 at every start. The page's fourth run of code is `0x401bd514.0x401bd66e`. The stops image: a fifth and a sixth, `0x401bc860.0x401bcaba` (602 bytes, 472 used) and `0x40088a80.0x40088d28` (680, 514 used). The main program has 45 KB of such runs in pieces of 64 bytes and up (`python -m tools.deadcode 3`), none left of over 848.

## SRAM `0x80000000.0x80010000` (64 KB, on chip)

| Range | What |
|---|---|
| `0x80000000.0x80003840` | 8 voices, 1,800 bytes each |
| `0x80003840.0x80003c40` | 8 output buffers, 128 bytes each (32 frames of int32, **mono**) |
| `0x80003c40.0x800040b0` | 8 parameter blocks, 142 bytes each |
| `0x80004a40`, `0x80004a48` | machine types and the sorted voice order, 8 bytes each |
| `0x80004b74` | 257-point Q31 sine (boot copy of file offset `0x53e54`) |
| `0x800049e0.0x80004a40` | the amp envelope's state, 12 bytes a track |
| `0x80008150` | `pmod`, int32 per track (note, semitones << 16) |
| `0x80008180.0x80008182` | trig and release masks read by the audio interrupt |
| `0x800083b0.0x80008450` | the overdrive stage's state: ramps made from the knobs |
| `0x80008550.0x80008a60` | the two filters after the voice loop: flags, types and coefficients a track, their sums, and scratch (`tools/audiomap.py`, `FILTER_STATE`, `FILTER_PIECES`, `FILTER_SCRATCH`) |
| `0x80008a60` | 8 small per-voice buffers, 48 bytes each |
| `0x80008c60`, `0x80008d84` | Twinshot scratch buffers A and B |
| `0x8000a888` | pitch table used by the sample player |
| up to `0x8000f670` | highest static reference found. Treat SRAM as full. |

## Sample pool format

Built by `0x40000d06`, which walks the pool once:

```
repeat 64 times:
    u32 big-endian frames
    int16[frames] mono samples, read big-endian by the player
```

- Slot i: `SLOT_LEN + 8*i` = frames, `SLOT_PTR + 8*i` = address of the first sample. An empty slot has frames 0.
- The pool is filled during init (`0x40000f8e.0x40000fd4`) by the main CPU, 2 KB at a time: each chunk is copied from the shared window at address `0x800` to `POOL + index * 0x800`. The index is 16 bits and unchecked. This is the slow boot the manual warns about.
- `0x40000cda` is an SPI flash-style reader for the pool (up to 64 MB). Nothing calls it: dead code in this build.
- `0x40000d7e` clears the pool and the slot table.

Limits:

| | Value | Where it comes from |
|---|---|---|
| Pool | 64 MB, about 699 s of 48 kHz mono | loader and BSS size |
| Slots | 64 | table size and the `0.63` clamp in the Twinshot update |
| Frames per slot | 524,287 (10.9 s) | clamp at `0x40009986`: position is 20.12 fixed point in a signed 32-bit word |
| Stock UI limit | 5 s per slot, "32 MB" | manual; enforced by the main CPU, not by section 7 |

## Twinshot (engine 11, machine type 44)

`update` `0x400097dc(pmod, voice, p)`, `render` `0x40009a8a(out, voice)`, with `p = params + 0x1c + 142*track` and slot s the 8.8 word at `p + 2*s`.

| Slot | Read as | Effect in the code |
|---|---|---|
| 18 | word | pitch of sample 1 (64 = original speed at note 60) |
| 19 | high byte | sample 1 select, centred on 64: `v-64 >= 0` plays slot `v-64` forward, below plays slot `63-v` **in reverse** |
| 20 | word | filter, centred on `0x4000`; two coefficient tables at `0x40014980` |
| 21 | word | balance between sample 1 and sample 2 |
| 22 | word | pitch of sample 2 |
| 23 | high byte | sample 2 select, same coding as slot 19 |
| 24 | word | copied to `voice+1004` by the voice loop; Twinshot moves it into sample 2's loop flag |
| 25 | high byte | amp decay, table at `0x4003ec38`; 127 = hold |

Names from the section 3 descriptors: TUN1, SMP1, FLT1, MIX, TUN2, SMP2 are slots 18.23, DEC1 is 25, OVER is 26 (not read by the voice loop). Behaviour confirmed in the emulator (Phase 3).

Voice fields used by Twinshot (last 88 bytes of the 1,800): two players at `+1712` and `+1748`, filter at `+1784`.

Player, 36 bytes, used by `0x40006764(buf, player)`:

| Offset | Field |
|---|---|
| +0 | sample pointer |
| +4 | pointer to switch to when the sample ends (loop or queued slot) |
| +8 | position, 20.12 |
| +12 | length << 12 |
| +16 | length to switch to |
| +20 | playing flag |
| +24 | increment, 20.12, set by `0x40006704(pmod, tune, player)` |
| +28 | reverse flag |
| +32 | loop flag |

The player does linear interpolation, forward or reverse, with optional loop. Render is: play A, play B, filter A, envelope, amp, then mix A and B with ramped gains into one **mono** 32-frame buffer.

## Dead code in section 7

32 functions, 6,830 bytes, are referenced by nothing: no call, branch, address operand or 32-bit value in the image names them, and the code has no computed jumps. The sampler lives in two runs of them (`tools/audiomap.py`, `CAVES`):

| Range | Size | Used by the sampler |
|---|---|---|
| `0x40002d86.0x400032b4` | 1,326 B | 996 B: note start, update, render |
| `0x40005a8e.0x40005f9a` | 1,292 B | 996 B: player, the step after the voice loop, the interrupt stub |

The recorder image takes a third run, `0x40004a6a.0x40004cd6` (620 B, 226 B used: one block of a take), and free SDRAM `0x44080000.0x47c80000` for the takes, `0xf0000` bytes per slot. The sampler's right channels wait at `0x44050000`.

Also dead: the SPI pool reader `0x40000b92.0x40000d06` and its byte helper at `0x40000406`. The stereo image takes the reader's 372 bytes and three more runs (`0x40005964`, `0x400050a6`, `0x40005866`: 168, 134 and 130 bytes). After it 442 bytes of unreferenced functions remain unused, in four runs of 108 to 118 (`tools/audiomap.py`, `SPARE_RUNS`).

**Stock Twinshot's own code is room too** (2026-10-10: the sampler takes Twinshot's place, and keeps what it leaves). Engine 11's two table entries are the sampler's in every image of ours, so nothing reaches it (`TWIN_ROOM`). The stereo image's second build (2026-10-11) is the first to use any: the larger run holds the sums of sixteen frames, 790 of its 830 bytes (`QUICK_CAVES`). The smaller holds the third build's pass of a voice's level and gain, 280 of its 514 bytes (`LEAN_CAVES`), and in the time image, a tool, that image's routine after it:

| Range | Size | What it was |
|---|---|---|
| `0x400097dc.0x40009b1a` | 830 B | Twinshot's update (686) and render (144) |
| `0x40006764.0x40006966` | 514 B | its sample player and its one-knob filter |

Held unreached, in an image that leaves them alone (the pitch image) and for the smaller run in the stereo image too, by `tests/test_stereo.py`: no even 32-bit value and no instruction outside them names an address in them, no far branch goes there, and they are neither run nor read while all twelve machines play through the whole interrupt. `tools/deadcode.py` lists the second run and not the first: the routine before the update ends in a jump (`jmp 0x400045a0`), and the tool cuts code at `rts`. The stock routines the sampler calls that Twinshot called too (the pitch routine `0x40006704`, the envelope, the amp at `0x400045a0`, the mix at `0x400049f4`) are not part of it. With the 442: 1,786 bytes. After the stereo image's third build about 100 are left in the smaller run, and of the four small runs the time image's routine uses the first and third (108 and 118 bytes); the fourth, `0x40009f1c`, is named four times in stock and is not room.

Audio CPU, the srr image (2026-10-13): SY SWARM's update and render, `0x400092ec.0x400097dc`, 1,264 bytes, are ours: 638 used (the sampler's update and render, the hold, the stand-in), **626 free there**. The first run has 382 free, those two having left it. `0x44050a40.0x44050ac0`: a voice's hold, sixteen bytes a voice (step, phase, the two frames held); nothing clears it at a start, a note's start does. Main CPU: `0x401a8d52.0x401a8e98` (eight bytes, then the per-block routine) and `0x401ac7b0.0x401ac8da` (the page's ninth run).

Audio CPU, the hits image (2026-10-14): SY TOY's and SY BITS's update and render, `0x40008ae8.0x400092ec`, 2,052 bytes, are ours (named by nothing once their table entries are gone; the two engines are handed SWARM's stand-ins): 1,300 used by the hits, **752 free there**. SY SWARM's run and the first run are as the lap image left them (546 and 382 free); the time image's routine gave 6 back in its run (4 free). The first build, never on the unit, took SWARM's and the first run's instead. The window's long at `0x5b4`, the time image's C, is the hits' (P at `0x5b8` stays). Main CPU: `0x4012d408.0x4012d630` (552 bytes, 164 used), the call of the filter's envelope.


Audio CPU, what each stock engine left would free (2026-10-20, `tools.deadcode.survey` on stock section 7 with engines 8 to 11 zeroed in both tables, then each of 0 to 7 as well; the count is the unreached bytes it adds): SY CHORD (5) 1,422; SD BASIC (1) 1,126; BD MODERN (0) 1,090; SD VINTAGE (6) 404; CY ALLOY (2) 324; PC CARBON (3) 136; SY TONE (4) and CP VINTAGE (7) 0 (their code is shared with live engines). Engine 0 is also what every type with no engine maps to (8.35, 39.43, 45): not a candidate without reading that first. **Dropping the multi image frees nothing here**: its `rec_all` is 200 bytes in run `r` where the stops image's `rec_step` was 216, plus one `jsr` in the hook.
