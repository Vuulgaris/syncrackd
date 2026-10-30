# The stereo question

Syntakt OS 1.42. Section 7 facts hold for 1.41 too; section 3 addresses are 1.42 only.

## Verdict

**The track mix is code, not FPGA. But it is code on the main CPU (section 3), not on the audio CPU (section 7).**

- The audio CPU renders each digital track to a **mono** 32-frame buffer, runs four mono in-place stages on it, and hands the 8 mono buffers to the main CPU through shared memory. It is never told a track's PAN, VOL or send levels.
- The main CPU copies the 8 buffers out of the shared window by DMA and mixes them itself: volume, an equal-power style pan law, sum to an interleaved stereo bus, sends.
- So a section 7 patch alone cannot place two channels inside one track. Model-TG's mid/side trick needs its hook in the mixer, and on the Syntakt the mixer lives in the other CPU.

## Signal path

```
audio CPU (section 7), once per 32 frames, interrupt 0x40000934
  copy 0x1b0 bytes of parameters in from the shared window (address 0)
  0x40004324  voice loop          8 tracks -> 8 mono buffers at 0x80003840
  0x4000112c  gain                in place, per track
  0x40002320  drive               in place, per track
  0x400019d6  filter              in place, called once per track
  0x4000168e  amp envelope        in place, calls 0x40001476 once per track
  eDMA ch 47  0x80003840 -> shared window + 0x1b0, 64 x 16 = 1024 bytes

main CPU (section 3)
  eDMA ch 47  window (0x100001b0) -> 0x80003d50, 1024 bytes      (set up at 0x400a47fa)
  0x4008f242  mixer, per track:
                volume from params+124 (VOL)
                0x400a1792(params+122 = PAN) -> left gain, right gain
                send gains from params+118, +120 (DEL, REV)
  14 kernel passes a block (corrected 2026-10-09, tests/test_mixer_whole.py), among them:
  0x4008f0b6  8 inputs, twice:  8 tracks x pan gains x delay send -> 0x8000dbd0 / dbd4 (stride 8)
  0x4008f024  9 inputs, twice:  the same for the reverb send, into the same two places
  0x4008ef8c  10 inputs, twice: 8 tracks and the two returns x pan gains -> the dry mix 0x8000dad0 / dad4
              and twice more for tracks routed to the FX block -> 0x8000dfd0 / dfd4
  the dry mix goes to slots 7 and 2 of the output frame
```

The shared window is `0x0` on the audio CPU and `0x10000000` on the main CPU: `0x000..0x1b0` parameters in, `0x1b0..0x5b0` audio out, `0x800..0x1000` the boot-time sample chunk. What sits behind it (FPGA block RAM is the likely candidate) is not identified.

## Evidence

Audio CPU, by running the real interrupt in the emulator (`tests/test_stereo_path.py`):

| Claim | How it was shown |
|---|---|
| The audio CPU receives no PAN, VOL or sends | The incoming block was filled with a marker byte; only type, slots 18..27, 29, 37, 38, 40..44, 50, 51 arrive in a track's parameters. Slots 45..48 stay untouched. |
| What leaves is exactly the 8 mono buffers | The interrupt programs channel 47 with source `0x80003840`, destination window `+0x1b0`, 64 x 16 bytes. Init clears `0x5b0` bytes of window: `0x1b0` in plus `0x400` out, nothing more. |
| The stages after the voice loop are per track | Track 0 is bit-identical after every stage, amp included, whether or not track 1 plays; tracks 2..7 stay silent. |

Main CPU, static plus running its real code in the emulator:

| Claim | How it was shown |
|---|---|
| It copies the same 1024 bytes into its own SRAM | Operands at `0x400a47fa..0x400a482c`: source `0x100001b0`, destination `0x80003d50`, count word `0xDE40`, start channel 47. |
| The mixer reads PAN and VOL from its own track parameters | `mvs.w 122(a3)` then `jsr 0x400a1792` at `0x4008f2f8`; `mvs.w 124(a3)` at `0x4008f2b6`. Offsets 122 and 124 are slots 47 and 48, which the descriptors name PAN and VOL. |
| Every sum is a left pass and a right pass of a kernel over the copied buffers | `0x4008f7ea..0x4008f818`: `(bus L, tracks, left gains)` then `(bus R, tracks, right gains)`. The kernel was run in the emulator and matches `-sum(gain * track)` exactly. **Corrected 2026-10-09:** these two passes are the delay send's sum, not the main mix. The dry mix is another pair, of a 10-input kernel into `0x8000dad0`, with the same pan gains: "One-track stereo" below. |
| Hard pans isolate | The real pan law run for all 128 values: pan 0 gives left 1.0, right exactly 0. Pan 127 gives right 1.0, left 4 lsb of 32 bits (about -174 dB). Centre is 0.75 each side (a parabolic sine, not 0.707). |
| Two hard-panned tracks are a clean stereo pair | Pan-law gains fed to the real kernel: track 0 on the left bus and track 1 on the right bus, each within 1 lsb of its input, no trace of the other. |

Not shown: anything about timing on hardware, the FPGAs, or the analog tracks.

## Options for stereo samples

### A. Two-track stereo, section 7 only (recommended)

Left in track N's buffer, right in track N+1's buffer. The user pans N hard left and N+1 hard right with equal volume and sends. The main CPU needs no patch: the test above shows the stock mixer turns that into exact left and right.

What the patch has to do inside section 7:
- One sampler voice on track N renders both channels and writes the right one into track N+1's buffer, after track N+1's own voice would have rendered (the voice loop orders voices by machine type, so "after" has to be forced, or the neighbour's render skipped).
- Mirror track N's filter and amp parameters onto track N+1 in the audio CPU's local copy, and its trig and release bits, so both channels go through identical filter and amp stages.
- Nothing else. Pool, slots and playback are the mono path twice.

Cost: a stereo voice uses two of the 8 digital tracks. Mono samples stay one track each.

Risk: low. No section 3 change, no DMA change, nothing new crosses between the CPUs. Everything except the user's pan setting is testable in the emulator.

The stock fallback from CLAUDE.md is the same idea with no mod at all: L and R as two mono slots on two Twinshot tracks, panned hard, given the same trigs (Track Relations or copied trigs). It works today; it just costs two slots and manual upkeep.

### B. Stereo inside one track (mid/side, as Model-TG does)

Needs all of:
- a second buffer per track across the shared window: the DMA count raised on both CPUs, window space past `0x5b0` (it overlaps the boot chunk window, free at run time if the window is at least `0x9b0` bytes: unproven), and 1024 more bytes of main CPU SRAM after `0x80004150` (unproven free; **not free, 2026-10-09:** `0x80004150` and `0x800041d0` hold the effect returns the dry kernel reads);
- new code in section 3 at the mixer (`0x4008f242`): extra kernel passes adding the side to left and subtracting it from right;
- section 3 patched on 1.42 only, with its own free-space and CPU-budget questions, none of which have been looked at.

It keeps 8 stereo tracks, and pan would act as balance. It is also a two-CPU patch whose new data path cannot be proven without hardware. Not now. Looked at again on 2026-10-09: "One-track stereo" below.

### C. Mono only

Everything else in the goal list (longer samples, per-project sets, playback modes) is independent of stereo.

## Decision

Build the sampler mono first (Phase 5 as written), then add **A**. Leave **B** documented as the upgrade path if two-track stereo proves too costly in tracks.

## Status

Option A is built (Phase 5): `docs/SAMPLER.md`. The audio CPU links the right track's overdrive, filter and amp envelope. It is what every image up to the save image does. **The stereo image (2026-10-10) has one-track stereo in its place: the last section.**

Pan, volume and sends are linked by a small main CPU patch (Phase 7, full image only): not option B's second data path, just the stock mixer being handed the left track's values for the right track, with the pans forced. It needs no change to what crosses between the CPUs. Without it (audio-only image) those four are set by hand on the right-hand track.

## One-track stereo (built 2026-10-10: the stereo image. Works on the unit, 2026-10-11, second build)

**The maintainer made it the next build on 2026-10-10** ("stereo.md/one travck stereo is noumber one"). It is built: `make image-stereo`. What was weighed on 2026-10-09 is kept below as it was written; "How it is built" and what follows are new.

**What is wanted.** A stereo sample on one track, so 8 stereo samples at once where option A gives 4. The maintainer asked whether it can be had "with no compromise on quality" (2026-10-09), and had already ruled out lossy packing (2026-10-05). Two-track stereo (A) is what every image up to the save image does.

**Corrections found on the way** (`tests/test_mixer_whole.py`, the real mixer run whole with its five effect helpers and its scale routine made returns):
- The mixer makes 14 kernel passes a block, not 2: 8 of the 8-input kernel `0x4008f0b6`, 2 of a 9-input one `0x4008f024`, 4 of a 10-input one `0x4008ef8c`.
- `0x8000dbd0` / `0x8000dbd4` is **not** the main bus. It is the delay send's sum (the two passes Phase 4 found), used again for the reverb send's. With a track's sends at 0 it stays silent.
- The digital tracks' dry mix is `0x8000dad0` (left) / `0x8000dad4` (right), from the 10-input kernel (8 tracks, delay return, reverb return; gains at `0x8000e188` / `0x8000e160`). It goes to slots 7 and 2 of the output frame. Tracks routed to the FX block go to `0x8000dfd0` / `0x8000dfd4`.
- A kernel replaces what is at its destination and writes its ramped gains back. One more pass cannot add to a bus: it needs a buffer of its own and its own copy of the gains.
- The first reader of the dry mix after the sums (done at `0x4008fb78`) is a scale call at `0x4008fc5a`. Anything added to the dry mix has to be in between those, so from inside the mixer and not from around its call, where our hooks are.
- Phase 4's conclusion stands: the same pan gains feed the dry passes, and hard pans isolate.

**Looked at first, and out: mid and side as two 16-bit halves of a track's word.** The voice renders left and right, each goes through the four stages, (L + R) / 2 goes in the high half of the track's buffer and (L - R) / 2 in the low half, so nothing new crosses the window; the stock mixer handles mid, new main CPU code adds the side to left and takes it from right.
- It is lossy. Measured: a half-scale sample at factory settings peaks at 92,288,553 after the amp stage (2^26.5), so the top 16 bits of the word hold about 12 bits of a full-scale sample. Shifted up before packing, with room left for the filter and OVER, about 13 to 14 bits (an estimate, not measured), where that path is 32 bits today. Out by the maintainer's rule.
- A mono machine's low half is sound, not side. Both CPUs would have to agree every block on which tracks are packed, or a block of a mono track is decoded as a burst at full level.
- Its main CPU cost was counted anyway (2026-10-09, from C sketches built with `-mcpu=54418` and run in `emu/machine.py`; the sketches were not kept). Instructions a block, all 8 tracks packed: unpacking 2,437 (`-O2`) or 2,687 (`-Os`), two passes of the stock kernel 1,372 (686 each), folding the two sums into the bus 296 or 261, gated copies of the gains 409 or 418. Together 4,514 or 4,738; with one pass 3,592 or 3,810.

For scale, what the main CPU does a block that could be counted: the mixer without its effects 21,381 (20,820 run, plus 3 x 187 read from the listing for the scale routine, which `emu/` cannot run), the two routines before it 1,872 (`0x400962ac` 1,484, `0x4008ee86` 388), our hooks around the mixer call in the load image 571 with no sampler track, 1,261 with 4 stereo pairs, 3,433 while a track records. The effects (delay, reverb, their set-up) are not counted and the main CPU's clock and load have never been measured, so there is no budget.

**What was left on 2026-10-09: the right channel as its own 32-bit buffer a track.** That is what is built, with two changes to how it was pictured then: nothing new is asked of the transfer between the CPUs (the right channels cross by the CPUs' own reads and writes of the window), and the second set of buffers is not in the main CPU's SRAM.

### How it is built

Audio CPU (`engine/sampler.c` with `ONETRACK`; `engine/sampler.h` has the whole account):
- A stereo note's right channel waits in free memory until stock's four stages have done the eight left buffers. The interrupt's call of the last stage goes to a routine of ours, which calls stock's and then runs the same four stock routines on the right channels.
- The overdrive's and the amp envelope's state do not hear the sound, so the right channel starts each block from a copy of what the left started from and keeps nothing.
- The two filters remember the sound. Stock's memory of them is exchanged with a copy of its shape in free memory before the right channels are done and exchanged back after. A track's right channel starts from the left's memory in the block it comes on.
- The multimode filter takes two coefficients as an earlier call left them for three of its types. A right channel is handed the two its left found.
- The overdrive and the base and width filter do all eight tracks a call, so the first stereo track costs both; the other two are called for the stereo tracks only.
- A track has a right channel when its machine is the sampler, MODE says stereo and the note that is playing has one. A note that started mono, or a stereo sample whose right slot is the shorter, has none, and plays on both sides.

Across:
- Sixteen halves of 16 longs in the two stretches of the window nothing uses (`0x5c0..0x800`, `0xe40..0x1000`), written by the audio CPU at the end of its interrupt, just before it sends the left buffers, and one long (`0x5b0`) that says which tracks have a right channel this block. The long's low two bytes have to agree with each other and its high two are a mark.
- The main CPU reads them where stock waits for the left buffers to arrive (`0x400a4e30`), a long at a time. While the audio CPU is down it reads nothing and sets the long to 0, so that a restart of the audio CPU (which clears stock's part of the window and none of ours) does not leave it the long of the block before.

Main CPU (`engine/rightfill.c`, and seven operands of the mixer):
- The mixer's four right-hand passes read a second set of buffers at `0x4556a000` (cached SDRAM nothing names): for each track its right channel from the window, or a copy of its left buffer.
- Pan is a stereo track's balance, with the pan law's 0.75 a side in the middle. Its delay and reverb sends are stereo. The effect returns are as they were.
- The mixer link is gone: the track after a stereo one is its own again, with its own pan, volume and sends. The mute is as it was.

### Shown in emulation

`tests/test_stereo.py`, 71 tests; `docs/FINDINGS.md`, "One-track stereo: the stereo image", has the numbers.
- A right channel comes out of the audio CPU exactly as a stock track would have made it, fed that signal with those knobs and trigs: the built interrupt against the stock one, bit for bit, with the stage knobs, the trigs, MODE and the machines moving, and with all eight tracks stereo.
- The left channels, every stock machine and a mono sampler are what they were. The voice makes the two channels it made.
- Nothing in free memory or in the window's two stretches is believed from before a start.
- The main CPU's routine puts in the second set what the audio CPU left, or the left buffers when the long does not agree with itself, when the audio CPU is down, and for every track without a right channel.
- The real mixer: with the second set a copy of the first it is stock bit for bit; with stereo tracks its left sums are stock's of the left buffers and its right sums stock's of the right ones.
- The two programs together, from the voices to the mixer's sums, against stock's stages and stock's mixer.

### Needs the unit

| Question | What was assumed | What it looks like if wrong |
|---|---|---|
| Are the window's two stretches real shared memory | the window is one memory from 0 to `0x1000`; stock uses the rest of it | every stereo sample plays as its left on both sides, and nothing else is wrong |
| Does the main CPU read a right channel before the next is written | stock's own order for the left buffers, and the right ones are written last and read first | clicks in the right side of stereo tracks only |
| How many stereo tracks the audio CPU can carry | nothing: counts are instructions | crackle on everything when too many pitched stereo notes sound at once |
| Is the place of the second set free | nothing in the file names it | noise on the right side, or the unit misbehaves |
| The four new runs on the audio CPU, the one on the main CPU | reached by nothing | the unit does not start, or stops when a stereo note plays |

The cost in instructions, against 117,348 for stock's heaviest machine on all eight tracks. The first build: eight stereo tracks at their own pitch 94,251; pitched, four 107,544, five 120,739, eight 160,319. The pitch work was most of it: a stereo voice off its own pitch summed sixteen frames twice a frame, 121 instructions a sum. **The unit, 2026-10-11: "it works fine when they are all pitched normlly but when i pitch them it causes major distortion".** So the first is inside the audio CPU's time and the last is not, which is the second row of the table above answered, and by the maintainer's word the others have not shown. The second build makes those sums in the unit's multiply and accumulate unit, the same frames bit for bit: eight at their own pitch 84,579, eight pitched 116,679, which is what stock's heaviest asks. `docs/FINDINGS.md`, "Pitched stereo was past the audio CPU's time". **On the unit, 2026-10-11: eight pitched pass, and left and right are on their own sides on every track**, so the two stretches of the window are shared memory (the table's first row). Not measured: whether a right channel is ever a block out of step, which no ear would say of a tone.

### What it does not do

- A track's own output (USB track outs, and T1 to T8 as the recorder's source) carries a stereo track's left channel.
- A project saved for two-track stereo has a right-hand track after each stereo one, which was silent whatever was on it. Here that track plays its own machine: clear it or use it.
- Audio-only and full images, and everything up to the save image, are two-track stereo still.

### From the mode image on: the sample says

Built 2026-10-12, not on the unit. A track has no MONO or STEREO to set. SMPL counts the 32 samples, and a sample has a right channel when its second slot holds exactly as many frames as its first; it had one before when that slot held at least as many and MODE said stereo. Everything above is as it was for a sample that has one, and a sample without is a mono voice with no right channel made, sent or paid for. MODE's bit says what a take is, on the sampling page. `docs/SAMPLER.md`, "A sample is mono or stereo by itself".
