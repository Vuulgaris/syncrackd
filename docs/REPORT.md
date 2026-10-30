# Build report

Two files, both built from the official OS 1.42 file. Building writes files. It does not flash, and nothing in this project talks to a Syntakt.

| | `make image` | `make image-full` |
|---|---|---|
| File | `build/images/Syntakt_OS1.42_sampler.syx` | `build/images/Syntakt_OS1.42_sampler_full.syx` |
| Audio CPU program (section 7) | 2,544 bytes changed in 5 places | the same |
| Main CPU program (section 3) | untouched | 799 bytes changed in 35 places |
| Everything else, bootstrap and updater included | byte for byte Elektron's | byte for byte Elektron's |
| Size | same as the official file | 1,152 bytes longer: section 3 is compressed and repacks larger |
| Blast radius if wrong | digital tracks misbehave; the UI and the update path are not involved | the UI, sequencer and mixer run this program |

**Flash the audio-only image first.** It is the smaller risk and it is a complete sampler. The full image adds comfort, not capability.

## What is in the files

Section 7, both images:

| Where | Size | What |
|---|---|---|
| `0x40002d86` | 1,326 B | sampler code, over stock functions nothing references |
| `0x40005a8e` | 1,292 B | sampler code, same |
| `0x4001494c`, `0x4001491c` | 4 B each | engine 11 (Twinshot's slot): update and render now point at the sampler |
| `0x40000a36` | 4 B | the audio interrupt's voice loop call goes through a stub that runs one extra step |

Section 3, full image only:

| Where | Size | What |
|---|---|---|
| `0x40233d58..0x40233ed0` | 17 x 4 B | knob descriptor fields of machine 44: ranges, defaults, name pointers |
| `0x402545c9..0x402545ec` | 5 strings | names that only those records use, rewritten in place |
| `0x401942ba..0x401943de` | 10 x 4 B | start-up code that sets how each knob is shown: START, LENGTH, LOOP and MODE get the plain number text, picture and step that most knobs use (screen image: LOOP and MODE read as words, see "The screen image") |
| `0x401011e4` | 396 B | mixer link and audio mute code (tracks 1..12), over one unreferenced function (394 B used) |
| `0x400a15cc` | 360 B | analog mute code, over one unreferenced function (142 B used) |
| `0x400a5048` | 4 B | the one call to the mixer goes through the analog mute, then the link |

## Checked on every build

The build stops unless all of these hold (`tools/build.py`, `tests/test_build.py`):

1. The input is the pinned official file and all eight section hashes match.
2. Every patch site holds the stock bytes it expects.
3. No patch targets the bootstrap or updater. Only sections 3 and 7 can be patched at all.
4. The built file decodes cleanly: 20,094 packet checksums, the content checksum, the container layout.
5. It differs from the official file only inside the declared regions.
6. The sections taken back out of the built file are exactly the intended bytes, and section 7 plays like the reference model.
7. An independent tool (elektron-firmware-tool) reads the built file with all checksums ok and extracts the same sections.

## Proven in emulation

With the real section 7 code running in an emulator (`docs/FINDINGS.md`, Phases 3 to 5):

- The sampler is bit-identical to its reference model in 44 cases covering every LOOP and MODE setting, pitch, reverse, regions and loops across chained slots, and stereo.
- The 11 other digital machines produce bit-identical audio with the patch installed.
- Stereo through the real audio interrupt: the right-hand track follows the left through overdrive, filter and amp envelope.
- The overwritten code is unreferenced anywhere in the image and never runs or is read while all 12 stock machines play.
- CPU: 2,176 instructions per voice per block mono, 2,904 stereo, 9,079 in the worst single block found, against 3,883 for stock Twinshot and a 10,506 ceiling. A voice is held to 40 seams and loop turns a block; before 2026-10-07 a loop of a few frames played octaves up could reach 15,600.

Main CPU patches (Phase 7), weaker evidence:

- The knob descriptors read back with the intended names, ranges and defaults, and every other descriptor is unchanged. What the screen does with them is not testable here.
- The mixer link was run in the emulator **with the mixer itself replaced by a stub**: what the mixer would be handed is right (sends, volume, routing and level words copied, pans forced), the main CPU's data is restored byte for byte afterwards, overlapping pairs included, and the forced pans give hard left and hard right through the main CPU's real pan law. The real mixer was not run with it.
- The code's home is unreferenced by a static scan of the whole image (calls, branches, address operands, 32-bit values, switch tables). There is no way here to watch the main CPU run, so that is all the evidence there is.

## First hardware result (2026-10-04)

The maintainer flashed the audio-only image onto their Syntakt (after upgrading it to official 1.42). It was accepted, booted, plays samples one-shot and looped, and the rest of the machine sounds normal. Details in the hardware log at the end of `docs/FINDINGS.md`. The table below is what remains.

## Second hardware result (2026-10-06)

The maintainer flashed again and, following the full image's steps (MODE 4, pan untouched), reported that stereo works. So the full image boots and a stereo pair plays as stereo with the mixer link doing the panning. The rows below about the screen, volume, sends, mute and old sounds are still open: none of them was reported on.

The full image with audio mute for the digital tracks (SHA-256 `9180bda1...a5bb`) was flashed later the same day: the maintainer reports the green mute key now cuts a digital track's audio ("works perfect"). Clicks, solo, pattern mutes and stereo pairs were not reported on.

A full image meant to mute the analog tracks (9..12) through the mixer (`6c02aa05...a9b4`) was flashed the same day: **it does not.** A muted analog voice rings out; the maintainer's own volume control does silence it. The dry analog sound does not go through the mixer.

The full image `112077ebdd6b9e1a6c759e65c383510d9c5c28914e4b99011fa29ba15c3990e6` (now `build/images/old/full_old_knobs_known_good_112077eb.syx`) mutes the analog tracks where their dry level is set instead. Flashed 2026-10-07: the maintainer reports it works with no clicks ("no clicks sounds good"). Older images are in `build/images/old/`, named by what they do and their hash; `full_digital_mute_only_9180bda1.syx` is the one before it that was known good on the unit. Older images are in `build/images/old/`: `full_digital_mute_only_9180bda1.syx` (the one known good on the unit) and `full_no_mute_7043772c.syx`.

## The recorder image

A third file, `make image-rec`: `build/images/Syntakt_OS1.42_sampler_rec.syx`, SHA-256 `f6b57f5082083bf52a528475723b3fbf98192318a83fd799bd18c36cd1619234`. It is the full image plus the recorder (`docs/SAMPLER.md`, Recording). The other two files build byte for byte as before.

On the unit (2026-10-07, first cut `5284426f...5927`, kept in `build/images/old/`): takes of several seconds record and play back, so the hand-over through the shared window works while the unit runs. The current file adds dither, 6 dB of playback level for takes, the new LOOP and MODE layout and SMPL counting stereo samples, and has **not** been flashed. Neither has the one before it (dither and level, old knobs: `build/images/old/rec_dither_gain_old_knobs_67164f3e.syx`).

What it adds to the full image:

| Where | Size | What |
|---|---|---|
| section 7, `0x40004a6a` | 620 B | a third run of unreferenced functions: one block of a take (206 B used) |
| section 7, the two sampler runs | 146 B more code | a note in MODE 2 or 3 starts a take; the step after the voice loop runs it |
| section 3, `0x4008f13e` | 238 B | three mix kernel variants nothing calls: the feed (156 B used) |
| section 3, `0x400a15cc` | 360 B | after the analog mute: the feed's 16-bit conversion with dither (168 B) |
| section 3, `0x400a5048` | 4 B | the mixer call goes to the feed, which calls the mixer link |

Shown in emulation (`tests/test_recorder.py`, 61 tests): a take is exactly the blocks the main CPU's code wrote, in order, left and right apart, for the length of the note; no block is lost or doubled when the two sides drift by up to a ring; the take ends at its buffer's end, at an overrun, at a new trig or when MODE moves; a take plays back identically to the same audio loaded as slots; a recording track is silent; sampler playback and the 11 other machines are bit-identical to the images without the recorder; the main CPU's own data and the rest of the window are left untouched, and nothing is written at all until the stock flag says the audio CPU is up (so never while the boot loader pushes samples through that window). The note-off was checked through the real audio interrupt. The 16-bit conversion matches a model of it sample for sample; its error has no offset, is half a step in size, and carries levels below one step on average; it stops at the ends of the range. A take plays at twice the level of the same audio loaded as a sample, a full-scale take does not wrap, and an ordinary sample played after a take is back at its own level to the bit. Cost: 125 instructions per block while nobody records, 573 during a take.

Not shown, needs the unit:

| Unknown | Why | What to check first |
|---|---|---|
| Can the window at `+0x800` be written and read while the unit runs | answered on the unit: yes, takes record and play back | nothing open |
| What the main pair in the frame buffer is | read from the listing as post-FX bus plus FX return, never heard | does a take sound like the main out: analog tracks, effects and all |
| Level of a take | the maintainer found takes too quiet and used the overdrive to make it up. Measured in emulation: a sample left the voice at half scale, the mixer's own gain is -6.6 dB at its default level and volume and 0 dB at their maximum. Takes now leave the voice at full scale. The filter stage's gain could not be measured: its cutoff word comes from the main CPU | LEVEL and AMP VOL at maximum, OVER at 0: is a take as loud as the mix it came from |
| Main CPU load | the feed is 65 writes through the window per block, timing unknown | any crackle or UI lag while a track says record |
| The feed's code space | static scan only, like the mixer link's | covered by "does it boot and mix" |
| Does a trig's LEN end the take | a held trig key does (its note-off comes on release). A sequenced trig with a LEN was not reported on | a 16 step trig with the condition 1ST: is the take one bar |

## Not proven. Needs a real unit.

| Unknown | Why emulation cannot answer it | What to check first |
|---|---|---|
| Does the unit accept and boot the file | nothing here models the update path, either FPGA, or the main CPU handing section 7 to the audio CPU. Others report flashing modified section 7 on 1.41; that is their result, not ours | does it boot, do the analog tracks and stock digital machines sound normal |
| Real CPU load | the emulator counts instructions; it has no cache or bus timing, and a sampler streams from SDRAM | eight sampler tracks at once, long samples, high pitch: any crackle or UI lag |
| The scratch memory at `0x44050000` | free by static analysis only; physical RAM size is inferred, not measured | a stereo note: is the right channel clean |
| The dead-code claim for boot and handshake paths | those paths cannot be run here | covered by "does it boot" |
| Mute, solo and velocity on the right-hand track of a stereo pair | not traced | mute the left track, mute the right track, play soft and hard |
| Full image: the screen | the UI cannot be run here. The display table was read out of the start-up code and agrees with what stock shows on hardware (FLT1 and MIX as -64..+63); the patch is read back the same way | do the knobs read TUNE, SMPL, STRT, LEN, LOOP, MODE, DEC; do STRT, LEN and LOOP show 0..127 and MODE 0..15; do new sounds start at STRT 0, LEN 127 |
| Full image: audio mute, digital tracks | the global mute key is confirmed on the unit. Not reported: clicks, pattern mutes, solo, stereo pairs | a pattern mute, a solo, and the left track of a stereo pair |
| Full image: audio mute, analog tracks | confirmed on the unit by the maintainer's report (2026-10-07): no click, solo and pattern mutes, the sends, unmuting mid-decay | nothing open |
| Full image: the mixer link | the real mixer was stubbed; two of the values it copies ("level words") are understood only as inputs to the gain, not by name | a stereo pair with nothing set on the right track: centred image, both sides follow volume, sends, velocity and a volume p-lock |
| Full image: sound import | the knob table is also used when sounds are loaded or converted | load an old Twinshot sound and a project saved before the patch |
| Anything analog, the mixer, the effects | on the main CPU and beyond, untouched and unmodelled | listen |

Recovery if it goes wrong: the bootstrap is untouched, and on Elektron boxes its startup menu can take an OS update independently of the main OS. That is from the Digitakt II notes and the bootstrap's own strings; it has not been verified on a Syntakt by this project. Have the official 1.42 file ready before trying anything.

## The big image

A fourth file, `make image-big`: `build/images/Syntakt_OS1.42_sampler_big.syx`, SHA-256 `abf15db216ffea983e749dc3cf2eedee49724a05ad1a69ea3e1f92f1b193fcd5`. It is the recorder image with sample slots of 1 MB (10.9 s) where stock has 512 KB (5.46 s). **Flashed by the maintainer on 2026-10-07, and all ten checks of its first step passed on the unit** (hardware log in `docs/FINDINGS.md`): boot, 10 s mono and stereo, the high slots, a power cycle, a pull back to the computer, older projects. The pulled file was not compared byte for byte. The other three files build byte for byte as before.

| Where (section 3) | Size | What |
|---|---|---|
| 13 places from `0x400b9eb6` to `0x40113428` | 2 to 6 B each, 50 B | a shift, an offset or a limit in the routines that find a slot on the +Drive or hold a length to a slot's size |
| `0x40082334` | 246 B | the routine that builds the audio CPU's pool at boot, rewritten in place (124 B used) |

Section 7 is the recorder image's.

Why it is possible: every slot is a fixed run of sectors from 4 MB on, and nothing in OS 1.42 uses the drive between the samples' end at 36 MB and 244 MB. That was shown by reading every call of the three routines that touch the drive (`tests/test_sample_store.py`, 14 tests).

Shown in emulation (`tests/test_bigslots.py`, 15 tests, the drive a dictionary of sectors): the scan, the header reader, the data reader, rename and the `/samples` route all put slot n at sector 8192 + 2048 n; a slot is accepted up to 524,256 frames; the pool builder stages exactly what is in the slots, reads no sector outside the slot it is reading and none outside 4 MB to 68 MB, and with more audio on the drive than fits it stops at what stock could stage and writes nothing past it; a drive still laid out by stock boots without reading outside the samples.

The computer's half: `tools/patch_transfer.py` makes `build/Transfer10s.app`, a copy of Elektron Transfer 1.10.3 for macOS that cuts at 10 s where Elektron's cuts at 5.000 s: 4 bytes, one instruction in each half of the program, the installed program untouched (`tests/test_transfer_patch.py`). The copy is signed locally. It has not been started by this project, and it does not exist for Windows.

Not shown, needs the unit:

| Question | Why it is open |
|---|---|
| Does the part of the drive from 36 MB to 68 MB read and write like the rest | the unit has never written there |
| Does the unit boot with the new pool builder | the boot exchange between the two CPUs cannot be run here. The builder reads slots straight into the pool's block where stock went through a buffer |
| Does the changed Transfer start, connect and send 10 s | never started here |
| Does Elektron's Transfer still list, send and read back against the changed unit | not run |
| Boot time with long samples | the same bytes as a full stock pool at the most, so it should not be longer |

What it does not do: load more audio in all. The main CPU stages the whole pool in a fixed 32 MB, so 5:49 of mono (2:54 of stereo) is what a boot loads, as on stock. Twice that needs the pool sent in two halves: new code in the boot path, described in `docs/FINDINGS.md`, not built.

If it goes wrong: a unit that does not finish booting is brought back through the bootstrap's start-up menu (hold FUNC while switching on, OS upgrade). The bootstrap is not touched by any image here, but this project has never used that menu: check it is there before flashing.

## Using the audio-only image

The screen still shows Twinshot's names and defaults. On a new sound set FLT1 (start) to 0, MIX (length) to 127 and SMP2 (mode) to 0. TUN2 is LOOP: 0 off, +1 loop, +2 ping-pong. For stereo, set pan, volume and sends by hand on the right-hand track. The full image removes all of that. Details in `docs/SAMPLER.md`.

## The keep image

A fifth file, `make image-keep`: `build/images/Syntakt_OS1.42_sampler_keep.syx`, SHA-256 `638fedf12fb67376cab4e121cbbaae6c0b2a8b0cf4a40eb2951d349513c84c05`. It is the big image plus takes that last: saving a project writes every take not yet on the +Drive into its two slots, and a loaded sample plays at a take's level. **Flashed by the maintainer on 2026-10-08 and all seven of its checks passed on the unit** (hardware log in `docs/FINDINGS.md`): a take is there after a save and a power cycle, comes off with Transfer as ordinary audio, a full take keeps, a second save writes nothing more, a save works while a pattern plays. Its first build moved the take across in bytes and kept takes distorted; this one moves it in longs. The other four files build byte for byte as before.

| Where | Size | What |
|---|---|---|
| section 3, `0x401259fa` | 930 B | a stock function nothing reaches (found by `tools/deadcode.py`): our routine, 564 B used |
| section 3, `0x4005bad8`, `0x4005bc2e` | 4 B each | the two calls to the routine that saves a project (`0x4001a82e`) now go to ours |
| section 7, the recorder's run | 212 B more | answers a request a block; a new take clears its two marks |
| section 7, the sampler's update | one constant | a loaded sample's gain is a take's: full scale, 6 dB over the other images |

Shown in emulation (`tests/test_keep.py`, 25 tests):
- Audio CPU, in the real voice loop hook: a take is handed over 512 bytes at a time, exactly, zeros past its end; a slot that plays a loaded sample, an empty slot, a slot number or an offset out of range get nothing; with no request the window is not written at all, and with one only the answer's fields are; a kept take is not offered again, a new take on the same slot is, even at the same length; marks left in memory from before a restart do not count. Recording, and a take played back, are bit for bit the recorder image's. A loaded sample plays bit for bit like the same audio as a take (in the recorder image the take is 6 dB louder), and a full-scale sample does not wrap. It writes the window in longs only and reads it in words and longs, and so does the main CPU's side: no access of one byte, which stock never makes there. Cost: 11 instructions a block with nothing asked, 1,827 in a block that answers.
- Main CPU, the project save routine and the drive replaced by stubs, the drive a dictionary of sectors: the stock save runs first and its answer is passed on; a failed save, or an audio CPU that is not up, and nothing is asked or written; each take lands in its slot with the header Transfer expects (`SAMP`, 0, frames, a name), zeros after the last sample, the stock scan puts it in the store's table; only those slots' sectors are written, each once, the first sector last; a full take of 10.24 s takes 1,921 sectors of its slot's 2,048; a second save writes nothing; a drive error or a take that changes while it is read stops it with the old header in place, and the next save does it all; an audio CPU that never answers ends it after one wait. The code writes nothing but its stack and its three fields of the window.
- Both sides joined by carrying the window's bytes across: takes recorded on the emulated audio CPU are on the drive after one save, and the pool builder then stages them for the next boot exactly.

Needs the unit:

| Question | What was assumed | Check |
|---|---|---|
| Can the audio CPU write the window at `0xc18..0xe20` and the main CPU read it while the unit runs | answered on the unit with the first build: yes, a take reached the drive and was loaded at the next boot. But it was distorted. Cause, read from the two slots pulled back: that build moved the take's bytes one at a time, and a byte written to the window lands in both halves of its 16-bit word | record a take, save the project, power cycle: does the take play clean |
| Is the job that saves a project a place where our code may wait and write the drive | stock writes the project from it; ours spins while it waits for the audio CPU, up to one audio block a sector | does the unit stay alive during a save with a take; how long does it take; does audio keep playing |
| Stack: about 560 bytes more than stock uses at that point | the job's stack size was not read | same check: a crash on saving would be this |
| Speed of 3,842 single-sector writes | not known | time a save with one full take |
| Does Transfer read a kept take | the header is what Transfer itself sends, read from its code | pull `TAKE nn L` to the computer |

## The double image

A sixth file, `make image-double`: `build/images/Syntakt_OS1.42_sampler_double.syx`, SHA-256 `af6df5e4a42250a2e72673eaef10e3234dee06424b0a139721367b00f0c43232`. It is the keep image with the sample pool sent to the audio CPU in two halves, so up to 64 MB loads at boot where the others stop at 32. **It is the image on the maintainer's unit since 2026-10-08 and its six checks passed there** (`docs/FINDINGS.md`, hardware log). The other five files build byte for byte as before. Section 7 is the keep image's.

| Where (section 3) | Size | What |
|---|---|---|
| `0x40082334` | 246 B | the pool builder's place: now 18 B that call the new routine |
| `0x40086e42` | 912 B | a stock function nothing reaches (`tools/deadcode.py`): the routine that fills the block with one half, and the one the sender asks, 338 B used |
| `0x40082fda` | 12 B | in the task that sends the pool: its "block + 5 + (index << 11)" becomes a call |

Shown in emulation (`tests/test_double.py`, 16 tests, the stock header and data readers real, the drive a table of slots, the sender played by the test):
- a pool of one half or less is built to the same bytes as the keep image builds, every chunk comes from where stock took it, and the drive is not read again;
- a full set, 64 slots of 10 s, 61.4 MB, reaches the audio CPU's side bit for bit, each fill reading about its own half from the drive;
- a slot lying across the halves with the cut in its count, at its start, or anywhere in its samples;
- an exchange that starts again from the first chunk at any point gets the right chunk every time;
- what does not fit in two halves is left out and nothing is written past the block's half;
- the stall count is cleared at least every 16 KB and a few sectors read, and is 0 when the fill ends;
- the sender's own instructions, run around the call, copy 2 KB from the address they are given and still send command 2 and the index.

Seen on the unit (2026-10-08, by the maintainer's marks; by ear, not bit for bit):

| Question | What was assumed | Result |
|---|---|---|
| Does the exchange survive standing still for the seconds a refill takes | the audio CPU waits for each chunk with no limit of its own; the main CPU's watcher is the only timer, and its count is cleared | yes: the unit boots with 61.4 MB on the drive |
| Does the audio CPU's pool work past 32 MB | its boot clears all 64 MB and its slot table routine has no limit | yes: SMPL 18, 19 and 32 of the test set say their numbers, and slot 64 in mono |
| Does a slot across the two halves play whole | the two fills meet to the byte | yes by ear: SMPL 18 |
| Is the refill safe in the sender's task | 16 KB of stack as the builder's task has; the drive read takes its own lock | yes: same boot |
| Does a take still keep with every slot full | the cap leaves room for 64 takes of 10.24 s | yes: a take on SMPL 20 after a save and a power cycle |

Still open:

| Question | What was assumed | Check |
|---|---|---|
| How long is a tick of the watcher | 0x20 units a call, a timeout past 18 calls; the unit was not found | not needed while the count is cleared; unmeasured |
| Boot time with a full set | about twice a full set's before | time it (asked) |
| Are the samples of the second half right to the bit | emulation says so | pull a high slot with Transfer and compare with the file sent |

## The screen image

A seventh file, `make image-screen`: `build/images/Syntakt_OS1.42_sampler_screen.syx`, SHA-256 `2a793e926cd20e9ecbde6fda68a432532a68096638b8563b25873468561a202c`. It is the double image with SMPL showing the stereo sample's name when MODE counts stereo samples, and LOOP and MODE showing words. **On the maintainer's unit since 2026-10-08: the words, the stereo names and each track following its own MODE were seen there; a kept take did not show its TAKE name, not explained yet** (`docs/FINDINGS.md`, hardware log). The other six files build byte for byte as before. Section 7 is the double image's.

| Where (section 3) | Size | What |
|---|---|---|
| `0x40124852` | 848 B | a stock function nothing reaches (`tools/deadcode.py`): the words and the routine, 564 B used |
| `0x40188f3e` | 4 B | start-up code: the function of the slot text object is now our routine |
| `0x40194360` | 4 B | start-up code: LOOP's text is that object (the earlier images give it the plain number) |
| `0x401943aa` | 4 B | start-up code: MODE's text is that object again, as in stock (the earlier images give it the plain number) |

Shown in emulation (`tests/test_screen.py`, 30 tests; the manager, the object holding a track's values and, in most tests, the stock slot text function are played by the test):
- the display table as the start-up code builds it: records 498, 501 and 502 and no others get their text from our routine, and every other field of every entry is the double image's;
- in MODE 0 and 4 SMPL hands the value to the stock function as it came, for all 128 values;
- in MODE 1, 2, 3 and 5 the stock function is asked for slot 2n-1 on either half of the knob, the side is cut from the name, a name without a side is left whole, and past 32 it reads NO SAMPLE without asking;
- MODE is asked for as (the manager, record 502, track -1) and read through the method at + 40, which is what the page's own getter does;
- the words, for every value the two knobs can have, and the number for a value they cannot;
- through the stock code that turns a record into its text (`0x4007bbe2` and `0x4018837a`, run as they are): record to table entry to our routine;
- the stock slot text function run for real up to the name it asks the sample store for: it asks for slot 2n-2, counted from 0;
- nothing is written but the text.

Seen on the unit (2026-10-08, by the maintainer's marks):

| Question | What was assumed | Result |
|---|---|---|
| Is the routine given the table's own copy of the object wherever a knob is drawn | read from the one routine that turns a record into text | yes: MODE and LOOP read as words |
| Does the manager's routine give the open track's MODE | the page's getter calls it the same way | yes: a stereo and a mono sampler track each read by their own MODE |
| Is it safe where the text is drawn | the stock slot text function already calls into the sample store from there | yes: the pages open and the unit keeps running |
| Do the words fit | stock put names of up to 15 characters where MODE is | no complaint |
| What SMPL reads while a trig is held | the track's MODE decides | nothing to see: the name is not shown while a trig is held |

Still open:

| Question | What is known | Check |
|---|---|---|
| Why a take kept on SMPL 5 did not read TAKE 05 after the save and after a restart | the screen's name is the 16 bytes at + 12 of the slot's first sector, which is where our header puts `TAKE nn L` | what SMPL 5 reads, whether the take plays after the restart, what Transfer calls slot 9 |

## The page image

An eighth file, `make image-page`: `build/images/Syntakt_OS1.42_sampler_page.syx`, SHA-256 `2aed5118d78735ca3c5d9e93819ed184b38f799610895dfe8b0f66cfbdbce9d3`. It is the screen image with the sampling page: a second page behind SYN on a sampler track with SRC, DEST and REC for that track. REC and SRC are bits of the track's MODE parameter, so they are saved and can be locked to a step; MODE itself reads MONO or STEREO. **This build runs on the maintainer's unit, inside the load image (2026-10-09): a held trig locks REC to its step, a retrig on that step records, and the pop-up is back.** Seven builds before it ran there the same day (`docs/FINDINGS.md`, hardware log). The fifth (`eb899c8903a742a41a823756962326da4d1f1a5f155f6649c5aa20c728e5365b`, kept in `build/images/old/`) is the last whose REC worked there: kept in memory of ours, it records and plays back, and cannot be locked. The sixth and seventh, with REC and SRC as bits of MODE, went on inside the load image. On the sixth SRC, REC and MODE did not move (it changed MODE through a stock method that never touches the track's value). On the seventh they move and recording works, but a held trig locks nothing, because held steps go through a method it left alone. This build takes that method's way for held steps (`docs/FINDINGS.md`, "Held steps go through + 156"). The other seven files build byte for byte as before.

| Where | Size | What |
|---|---|---|
| section 3, `0x4001b51e` | 1,522 B | a stock function nothing reaches (`tools/deadcode.py`): the page's list, words and routines, 926 B used |
| section 3, `0x4008804c` | 1,040 B | a second such function: the switch of MODE's bits, locks and the pop-up, 664 B used |
| section 3, `0x400356bf`, `0x400356c4`, `0x400356d8` | 1, 4, 2 B | the routine that builds the page objects: SYN's object gets two pages, our list, and 32 bytes more for the page's state |
| section 3, `0x401ca38c`, `0x401ca3c0`, `0x401ca438` | 4 B each | the SYN page class's method table: the draw, a turn of a knob and "which record is behind this knob" |
| section 3, `0x401ca47c` | 4 B | the method table of the object's second base: a turn of a knob, the way one really arrives |
| section 3, `0x40233e40` | 4 B | MODE's descriptor: its range is 0..7 |
| section 3, `0x40124852` | 848 B | the knob text code built for this image: MODE reads MONO or STEREO (566 B used) |
| section 3, `0x4008f13e` | 238 B | the recorder's feed: the source is MODE's third bit (154 B used) |
| section 7, the sampler's three code spaces | | the sampler built for this image: the source bit, no chained slots, and the page's destination read when a take starts |

Seen on the unit (2026-10-09, by the maintainer's marks, over the seven builds): the second page opens on a sampler and only there; our text shows, a value inside its knob's box and the name under it; our knobs move our settings; LEVEL works on the page; with the box and its marks nothing records by itself after a restart; the box reaches the audio CPU and its answers come back; **a track put in record from the page records on a trig and plays the take back**; each track keeps its own settings; with REC and SRC as bits of MODE, REC, SRC and MODE move through stock's + 88, recording works, and MODE and REC do not disturb each other.

Shown in emulation for this build (`tests/test_pagerec.py`, 38 tests, and `tests/test_page.py`, 81, which run stock's own page methods for a value, a change and a step's lock as they are):
- the audio CPU, in the real voice loop hook: with MODE's record bit a trig starts a take and the note's end ends it, whatever the other two bits say; it goes to the stereo sample SMPL is on, or to the page's numbered one; a destination is for takes only and for its own track only; a box without both marks is not believed; switching the bit off ends the take; the bit that was CHAIN no longer chains; the box is read in words and longs and never written; the take plays back; playing is the keep image's, sample for sample;
- the feed, with the mixer stubbed: it runs for a track whose record bit is set, from the main mix or the input as its source bit says, the first such track deciding; never without the record bit; never while the boot loader has the window; it does not touch the box;
- the page: SRC and REC are read out of MODE; with no step's key held each switches its own bit of the track's value and no other, by exactly the difference, through stock's + 88, and stock's pop-up follows, with MODE's own name and text on the first page; with keys held each held step's own lock is switched and the track's value is left: a step without a lock gets one at the value wanted, in one click, and a trig if it had none; a step that already has the value gets no lock; keys past the pattern's length do not count; more clicks of the same turn change nothing more; the keys object is told before and after as stock's + 156 tells it; the page shows the first held step's settings while a key is held; stock's own + 156, run whole, does the same in two clicks; stock's + 96 with no trig about changes nothing, which is what the unit showed two builds ago; stock's own test says MODE's record can be locked; DEST is kept a track and written to the box in words, the marks last; on the first page MODE's knob switches the stereo bit and nothing else, on the track or on held steps, and the other knobs are stock's; MODE reads MONO or STEREO for all eight.

Needs the unit:

| Question | What was assumed | Check |
|---|---|---|
| Can a lock be switched back | the lock is read, not the track | hold the locked trig, turn REC to OFF |
| Is REC saved with the pattern | it is part of MODE | change pattern and come back; save, restart |
| Does the source bit reach the feed | bit 2 of MODE in the track's parameters | SRC on EXT |

## The load image

A ninth file, `make image-load`: `build/images/Syntakt_OS1.42_sampler_load.syx`, SHA-256 `c1f24701fbd6515070cde6ab9041120688afcaddcc3b4dbaf3cac321fc2ccc8f`. It is the page image, and LOAD PROJECT puts the drive's samples back in the slots that hold a take the drive does not have. **The load works on the maintainer's unit (2026-10-09, with the build before this one, `850d6e8c...61de`, which is on the unit), all five checks: record, save, record again, load, and the saved take is back; a sample from the computer that was recorded over is back too; the wait is fine, also with a pattern playing; the other samples are untouched; a save right after writes nothing.** This build differs from that one in the page code only and is on the unit now. It is the first code of ours that changes what a slot plays from the drive while the unit runs; stock has none (`docs/FINDINGS.md`).

| Where | Size | What |
|---|---|---|
| section 3, `0x401259fa` | 930 B | the keep image's run of code, now with the load: 914 B used where the page image uses 564 |
| section 3, `0x4005bbaa` | 4 B | the one call to the routine that loads a project for the Project Load job goes to ours |
| section 7, the sampler's three code spaces | | the sampler built for this image: a request with `KEEP_PUT` brings a slot's samples from the main CPU (208 B more) |

No new memory, no new part of the shared window, no new part of the drive, and no write to the drive.

Shown in emulation (`tests/test_load.py`, 33 tests):
- the audio CPU, in the real voice loop hook: pieces land in the slot's take buffer and the last request makes them the slot, at the length given, marked kept; such a slot sounds exactly as the same sample loaded at boot; a take is silent while it is replaced and its other half is untouched; a slot with nothing on the drive ends empty; a length is held to a buffer, a piece stops at a buffer's end, and requests that name no slot, no place in a buffer or an odd offset are answered and write nothing; the window is read in words and longs and only the answer is written; requests of a save are answered as in the page image, and with nothing asked the image runs as the page image, at the same count of instructions;
- the main CPU, with the project routines and the drive stubbed and the store's own read running: the stock load runs first and its answer is passed on; a failed load changes nothing; every slot is asked once and only slots with a take are read, in order, a sector a request, the last word last; samples of 1 frame to a full slot arrive whole; a slot is never read past its end whatever its header says; the drive is never written; nothing before the audio CPU is up; an audio CPU that does not answer and a drive error both end it; saving still keeps takes;
- both together: record, save, record again into the same place, load: the slot holds the saved take again, sounds like it, and neither a save nor a load has anything more to do. A sample from the drive that was recorded over is back after a load, and a take where the drive has nothing is gone.

Needs the unit:

| Question | What was assumed | Check |
|---|---|---|
| How long does the wait take | a sector a block, about 2.6 s for a full stereo sample | the maintainer marked the wait as fine; no time given |

## The bank image

A tenth file, `make image-bank`: `build/images/Syntakt_OS1.42_sampler_bank.syx`, SHA-256 `fe071f75561321cde45f6a78b50e32f7599aca1a22795fa92cf03785dc73a75f`. It is the load image with three sample banks: three sets of 64 slots on the drive, one loaded at a time, each project saved with one and loading it. **It runs on the maintainer's unit (2026-10-10) and the banks work there, a full bank coming in included.** Its first build (`6db70567...74ac`, kept in `build/images/old/`) took so long over a full bank, with a still screen, that it was taken for a hang; this one sends three sectors a request and moves the bar. The maintainer's design (2026-10-09): three banks, a project loads one, Transfer fills them, a bank changes on a project load only.

| Where | Size | What |
|---|---|---|
| section 3, `0x40196aba` | 1,714 B | a stock function nothing reaches: three numbers (the loaded bank, the project's bank, a flag while slots are loaded), then the banks' code and the load's, 1,624 B used |
| section 3, `0x4008f13e` | 238 B | the recorder's feed built for this image: nothing is fed while slots are loaded |
| section 7, the sampler's code | | the sampler built for this image: a load request can carry three sectors (58 B more) |
| section 3, 21 places | 4 B each | every `jsr` or `lea` that names the drive's read, write or erase names ours for it |
| section 3, `0x401259fa` | 930 B | the save hook built for this image: it also has the project's bank written down (576 B used; the load's code moved out) |
| section 3, `0x4001b51e` | 1,522 B | the page's code built for this image: the BANK place (1,108 B used) |

The other nine files build byte for byte as before.

**What is new for the drive:** every read, write and erase now passes through a routine of ours, and one sector at 196 MB, in the part nothing used, is written. A sample's sector can only be moved into one of the three runs, which end at that sector; projects, sounds and the rest of the drive start at 244 MB and below 4 MB and are never moved (`tests/test_banks.py`, for every edge of the layout and any number in the place of the bank).

Shown in emulation (`tests/test_banks.py`, 44 tests): see `docs/FINDINGS.md`, "Three sample banks, built" and "A bank loaded three sectors a request".

Seen on the unit with the first build (2026-10-10): it boots and works as before on bank A, so the drive's routines go through ours; BANK chooses and loads nothing; a save and a load bring bank B in; Transfer fills the loaded bank; the unit starts on the bank it was on; a take stays in its bank. Loading a full bank was not seen to end with the first build, and ends with this one (2026-10-10). How long it takes was not reported.

Needs the unit:

| Question | What was assumed | Check |
|---|---|---|
| Does a full bank load end, and how long does it take | 40,000 requests of three sectors, a slot read in two reads: 27 s and the drive's time for 61 MB | on B, load a project that is on A; watch the bar; time it |
| Does the bar move | stock's routine for it, called with our counts | the same load |
| Is the bank whole after it | three sectors a request land as one did | play SMPL 1, 17, 18, 32 all the way through |
| Is a recording track in the way | the feed keeps out while slots are loaded | leave a track with REC on, load a project on another bank, play the samples |

## The fade image

An eleventh file, `make image-fade`: `build/images/Syntakt_OS1.42_sampler_fade.syx`, SHA-256 `02495c021ac8ef7637ff8c15748ed28f3cfc059dcc921402678c4e4fa5582b2d`. It is the bank image with fades in the sound engine: a note that starts or ends inside its sample fades in or out, and a forward loop fades out before its seam and in after it. **It ran on the maintainer's unit on 2026-10-10 and its seven checks passed there.** Audio CPU only: section 3 is the bank image's, byte for byte.

| Where | Size | What |
|---|---|---|
| section 7, the sampler's three code spaces | | the sampler built for this image |
| section 7, `0x40003732` | 550 B | a fourth stock function nothing reaches: the fades' routines and two that moved for room, 244 B used |

Shown in emulation (`tests/test_fade.py`, 115 tests): the engine is the reference model bit for bit over 16 kinds of note at 5 pitches; where nothing is cut into it is the bank image's engine bit for bit; a cut start fades in from nothing over 64 frames and is the old frames after that; a cut end fades to all but nothing by the old last frame; a loop of a ramp, which jumped once a pass, has no jump a twentieth as large anywhere, differs from the old output only in the fade out before each seam and the fade in after it, and passes are as long as they were; backwards and in stereo the same; a ping-pong turn is untouched; fades are as long at any pitch; a new trig starts clean; the cost.

Asked of the unit and the maintainer's ears, and all answered well on 2026-10-10 (he marked each passed and wrote nothing of a dip):

| Question | What was assumed | Check |
|---|---|---|
| Is the click gone at a cut start | a fade in of 1.3 ms | a sustained sample, STRT off 0, play it |
| Is the click gone at a cut end | a fade out of 2.7 ms | the same sample, LEN short of all |
| Does a loop's seam still click | fades either side of it | a recorded bar on LOOP FWD; a sustained sound on LOOP FWD |
| Is the dip at the seam worse than the click was | 4 ms down and up, a pass | the same two loops: is it heard, on which |
| Does a drum lose its attack | a note from the sample's start is not faded; a loop's first hit is, after the first pass | a drum loop on LOOP FWD |
| Does a loop stay in time | the seam is where it was | a bar looped against the pattern for a minute |

## The mute image

A twelfth file, `make image-mute`: `build/images/Syntakt_OS1.42_sampler_mute.syx`, SHA-256 `b2e572600ef0368fccf279622d2d319258c767299e8a4467e7f42d3777cc467f`. It is the fade image with a mute that only silences: a muted track's trigs still fire. **Not flashed.** Main CPU only: section 7 is the fade image's, byte for byte.

| Where | Size | What |
|---|---|---|
| section 3, `0x400a421a` | 6 B | the per-block routine's test of a track's mute for an event: its first two instructions call our routine |
| section 3, `0x4008f1e4` | 34 B | in the room after the recorder's feed: stock's test for a MIDI track, none for a track that makes sound |

Shown in emulation (`tests/test_mutetrig.py`, 70 tests): stock's event loop, run from the image, keeps every event of a muted track that makes sound exactly as the bank image keeps an unmuted track's, and treats a MIDI track exactly as before, over 12 tracks, 72 events and 6 mixes of global mutes, solos and pattern mutes; the stack and stock's registers are untouched; stock's own "is a MIDI track" agrees with ours on every track; the FX track's test is as it was; nothing in the program points into the six bytes; the recorder's feed runs for a track that is muted and in record while the mixer is shown none of it.

Needs the unit:

| Question | What was assumed | Check |
|---|---|---|
| Does a muted track's trig run | the one test in the event loop is all that held it back | mute a track with a long sample, wait past its next trig, unmute: the sound is there mid-sample |
| Is a note started under a mute silent | the mixer's gain is at 0 before the note starts | mute, let trigs pass, listen: nothing, dry or in the delay and reverb |
| The analog tracks | their level words are at 0 before the voice is trigged | the same on 9..12 |
| Is a take made on a muted track | the feed and the audio CPU never look at mutes | mute a track with a REC lock on a step, let the pattern pass it, turn REC off, unmute, play |
| Solo and pattern mutes | they go through the same test | solo another track; mute in the pattern's own mutes |
| A MIDI track | stock's test is kept for it | if one is in use: its mute still stops its notes |
| What the trig keys show for a muted track | the UI is told of a trig, not of a muted trig | look |

## The len and live images

Two files on the mute image, both the audio CPU only (section 3 is the mute image's, byte for byte):
- `make image-len`: `build/images/Syntakt_OS1.42_sampler_len.syx`, SHA-256 `e00ce18f121863ef014e42d5a94a8d46daa85f1d32f0e0b8192351f19ce42617`. LEN acts while a note plays. STRT is the note's own, taken at its trig.
- `make image-live`: `build/images/Syntakt_OS1.42_sampler_live.syx`, SHA-256 `aecab772963a8cf10581f40a0d12ce76ad3b473b1ef6e29dac27bad1a6bf4a64`. The same, and a loop's next pass begins where STRT is by then.

**The live image runs on the maintainer's unit since 2026-10-10: a short loop with STRT turned up and down "sounds great", and LEN is as before. The len image was not needed and is not flashed.** Two earlier builds of the live image ran there the same day (kept in `build/images/old/`). LEN on a running loop and locks were right in both. STRT was not: in the first the note followed the knob and fluttered, in the second the region moved under the note and a short loop ripped. Then the maintainer offered to leave the start alone, which is the len image.

| Where | Size | What |
|---|---|---|
| section 7, the sampler's four code spaces | | the sampler built for these images |
| section 7, `0x400048c6` | 302 B | a stock function nothing reaches: where a pass begins and ends, 278 B used. Our code ran here on the unit in the first build |
| section 7, `0x40002a62` | 436 B | two more: the routine that looks at the knobs every block, 412 B used (live), 418 B (len). The same |

Shown in emulation (`tests/test_live.py`): both engines are the reference model bit for bit while the knobs are moved under them, 29 scripts, with the knob moved the way the unit is read to send it among them; with the knobs at rest both are the fade image's engine bit for bit; a loop of 7 ms keeps looping while STRT is turned 40 steps, every pass a pass long and the level never moved; on a long loop STRT changes no frame before the loop comes round; on the len image STRT changes no frame of a note that is playing at all, and the next note takes it; LEN is the same on both; LEN down to a buzz and back never stops the loop; backwards LEN is how long a pass is too; a ping-pong caught by its far end turns where it is, and takes a new start when it is back where its pass began; nothing is read from outside the slot; a new note takes the knobs as they are; a track in record and the other tracks are not touched; the cost.

Needs the unit:

| Question | What was assumed | Check |
|---|---|---|
| Is the rip gone (live) | it was the note left outside a region that had moved; a pass is not moved now | a short loop, turn STRT up and down |
| What a short loop does while STRT turns (live) | it steps through the sample a pass at a time | the same: is that the sound wanted |
| A long loop (live) | the new start at the next pass, through the seam's fades | turn STRT, wait for the turn |
| LEN, on either | as the two builds that passed | down to a buzz and back; pulled in behind the note |
| Backwards LEN, on either | a pass begins at the new top next time, and ends the new length from where it began | SMPL on the left half, turn LEN |
| STRT on the len image | nothing until the next trig | turn it while a note plays |

## The floor and reclock images

Two files on the live image, which runs on the maintainer's unit since 2026-10-10 ("this works well now the start bug is fixed"):
- `make image-floor`: `build/images/Syntakt_OS1.42_sampler_floor.syx`, SHA-256 `574a8d88f5f0ce5e8d76ad7b91e497d813c2ce1eaed0863cce0de4279953e96f`. LEN stops at 3.
- `make image-reclock`: `build/images/Syntakt_OS1.42_sampler_reclock.syx`, SHA-256 `1e5ca5f44024a840fb2f5e62d13fc2f995cd08cfd52881e1b8c39ca186f48056`. The same, and a step's REC is a lock of its own.

**The reclock image's first build, with LEN's floor at 6 (`8db3d658...0292`, kept in `build/images/old/`), runs on the maintainer's unit since 2026-10-10 and its three checks passed there.** He then asked for the floor at 3. The two files above differ from that build in five bytes, each a 6 that is now a 3, and are not flashed.

| Where | Size | What |
|---|---|---|
| section 3, LEN's descriptor | 1 B | its least value, 0 to 3 (floor) |
| section 7, the sampler's code spaces | | built with `FLOOR`: 16 B more in two of them; with `RECLOCK`: 40 B more in the third and 6 in the first |
| section 3, the page's two runs | 1,506 of 1,522 B, 1,012 of 1,040 B | built with `RECLOCK`: REC on held steps, the track's bits into MODE's locks, a changed machine's stray locks (reclock) |
| section 3, the feed's run | | built with `RECLOCK`: the same test of slot 24 as the audio CPU's (reclock) |

Shown in emulation: `tests/test_floor.py` (126) and `tests/test_reclock.py` (129), listed in `docs/FINDINGS.md`. In short: the floor engine is the reference model bit for bit and the live image's engine from 3 up; the page's REC lock is made by stock's own lock routines, found by stock's own routine that gathers a step's locks and put by stock's own routine that applies them at the word the audio CPU's voice loop reads; the engine and the feed record on the mark, do not on the other, and leave everything else to the track's REC.

Proven on the unit by the first build: a REC lock records and leaves MODE alone; it is saved and survives a power cycle; no track records by itself; LEN's knob stops at its floor.

Needs the unit:

| Question | What was assumed | Check |
|---|---|---|
| Is 3 the right floor | his number, after 6 | LEN all the way down on a loop |
| Old REC locks | a turn of the track's REC and back clears them | on a step locked with the live image |
| A track changed to another machine | its REC locks go when its SYN page is drawn | lock REC, change the machine, change it back |

The way back from either: the build on the unit, `build/images/old/reclock_step1_len_floor_6_on_unit_8db3d658.syx`, or the live image, `build/images/Syntakt_OS1.42_sampler_live.syx`, through the normal OS upgrade.

## The pitch image

A seventeenth file, `make image-pitch`: `build/images/Syntakt_OS1.42_sampler_pitch.syx`, SHA-256 `f364e2aec35e9b7f85e7f0a9ae4dd82bab17cf5b849b1da3e17cef0472e2c15b` (its third build. The first, `c271e2f1...5eb5`, ran on the maintainer's unit: "its better but when pitchrf low i still hear some clciks and pops", and later, of it or of the second: "they sound all fucked up, and there's a lot of noise" with TUNE moved. The first two believed a table left in memory by an earlier start; the third makes it at every start). It is the reclock image with a sound engine that works a frame between two of the sample's out from sixteen of them and a table, where it was the line between two. The main CPU's program is the reclock image's, byte for byte. **Not flashed.**

| Where | Size | What |
|---|---|---|
| section 7, `0x40004a6a` | 620 B | the recorder's run, now the table: 17 rows of 16, 544 B |
| section 7, `0x40005a8e` | 1,292 B | the second run: the sum of sixteen frames in the room the step after the loop left, 1,252 B used |
| section 7, `0x40001708`, `0x400027f6`, `0x40004708`, `0x40001900`, `0x40003512` | 344, 280, 226, 214, 204 B | five more stock routines nothing reaches: the step after the loop, the keep and load step, the recorder's step, the table's copy and the slot-end case, two small routines |
| audio CPU memory, `0x44060000` | 1,060 B | free SDRAM under the takes: a long and the table's 33 rows, made on the first interrupt |

Shown in emulation (`tests/test_pitch.py`, 240; a table an earlier start left with bits changed is made again; the second build's 73: within reach of a slot's ends it is the model too, the frames around the ends are written out once a note, and a low note's first and last blocks cost what its middle does but for about 450 instructions mono and 1,150 stereo at its start): bit for bit the reference model at seven pitches and with the knobs moving; bit for bit the reclock image's engine at a sample's own pitch; a 6 kHz tone played two octaves down has everything else 86 dB under it where it had 32, and 76 at 14 kHz where it had 15; a steady level stays put at any pitch; full scale does not wrap; the table is made once, from the image, and again for another build. Eight mono voices all pitched cost 56,583 instructions a block in the whole loop, against 84,048 for eight SY SWARMs.

Needs the unit:

| Question | What was assumed | Check |
|---|---|---|
| Is the grit gone | it was the line between two frames | a bright sample one and two octaves down |
| Time | instruction counts, no cache model | every sampler track pitched and playing at once |
| The table's memory and the five runs | free, and reached by nothing | the unit boots, and a pitched note is a note |

The way back: the build on the unit, `build/images/old/reclock_step1_len_floor_6_on_unit_8db3d658.syx`, or the reclock image, through the normal OS upgrade.

## The meter image

An eighteenth file, `make image-meter`: `build/images/Syntakt_OS1.42_sampler_meter.syx`, SHA-256 `f20da37b19b960119c6cb10008f7b6d82886dbb8fc3e4edaaa875296e0f2f622`. It is the pitch image with a main program that gives the sampling page a level meter and sixteen sources. The audio CPU's program is the pitch image's third build, byte for byte.

| Where | Size | What |
|---|---|---|
| section 3, `0x40088510` | 634 B | a stock routine nothing reaches: four numbers, then the feed and the meter's level, 496 B used |
| section 3, `0x401bceac` | 918 B | another: the sources' names, a turn of SRC, the bar, 566 B used |
| section 3, the page's two runs, the feed's two and the text's | as before | rebuilt: SRC as a number, the feed's conversion from two channels, MODE's word up to 63 |
| section 3, MODE's descriptor | 4 B | its largest value, 63 |

Shown in emulation (`tests/test_meter.py`, 90): SRC goes through MAIN, EXT, T1 to T12, FX and DELRV and stops at both ends, leaving the stereo and record switches alone, and a value an earlier build saved reads as it did; a take's two sides come from the source's place in the frame for all sixteen; the level is the source's largest sample and falls 13 dB a second; a drawing is asked for every 96 blocks through stock's own request, run as it is, and no more once the page stops being drawn; the bar is drawn by stock's own rectangle routine, run as it is, on rows 0 and 1 from x 21, ten dots to a halving, and nothing else on the surface changes; no bar and no word to the feed on any other page. The 17 earlier images are byte for byte as they were.

Needs the unit:

| Question | What was assumed | Check |
|---|---|---|
| Where the bar is | y 0 is the bottom row, from stock's own drawing of a knob's place and our text on the unit | open the sampling page and play something |
| Does it move well | 16 drawings a second, 13 dB a second down | watch it against a loop |
| The main CPU's time | 641 instructions a block and 16 drawings a second are little | the screen and keys feel as before, no crackle |
| A track as a source | a track's channel of the frame is its sound | SRC on a track, record, play |
| The two runs and the four numbers | free, and reached by nothing | the unit boots and the page opens |

The way back: the build on the unit, `build/images/old/pitch_step1_slow_ends_on_unit_c271e2f1.syx`, through the normal OS upgrade.

## The save image

A nineteenth file, `make image-save`: `build/images/Syntakt_OS1.42_sampler_save.syx`, SHA-256 `0787d6610e404188891988cc3219ddd637a4f0f2f568be7f7a40fa797a3fbaa5`. It is the meter image with SAVE on the sampling page: the takes that are not on the +Drive yet are written there, and the project is not. Main CPU only, in the runs it already has; the audio CPU's program is the meter image's.

| Where | What |
|---|---|
| section 3, the keep code's run `0x401259fa` | a long that says how a save is going, the job's name, and `save_start` with its three small routines: 780 of 930 B used |
| section 3, the page's three runs | the fifth place's word and its turn; one routine moved to the third run |
| section 3, six pointers | the two project save calls, the project load call and three of SYN's methods, to routines that moved |

Shown in emulation (`tests/test_save.py`, 18): a save hands stock's runner a job with a name and two function objects of ours, and says BUSY before the runner has it; the job, called as the worker would call it, writes the takes to their slots in the loaded bank with the store's own write running, calls no project save and leaves our sector of the banks alone; it says DONE, or FAIL after a drive error or with the audio CPU down, and a save after a failed one finishes; stock's own routines that copy and end a function object run on ours and leave them whole; the page's fifth box reads SAVE, BUSY, DONE or FAIL, a turn to the right starts a save and one to the left puts SAVE back. The runner itself is not run: it needs the unit's heap and locks.

Needs the unit:

| Question | What was assumed | Check |
|---|---|---|
| Does the runner take our job | it takes any two function objects, from the task a turn arrives in | record a take, SAVE, the box goes BUSY then DONE |
| Is the take on the drive | the job runs where Project Save's does | power off and on without saving the project: the take is there |
| Does the unit carry on meanwhile | a job needs no screen of its own | the sequencer plays and the page works while it reads BUSY |

The way back: the build on the unit, or the meter image, through the normal OS upgrade.

## The safe image

`make image-safe`: `build/images/Syntakt_OS1.42_sampler_safe.syx`, SHA-256 `bbc49790d72a0ac4474e1dc7050ce66f6b20b6ad0664922f321c593b809d2795`. The save image's main program and the reclock image's audio program, each byte for byte: the level meter, the sources and SAVE, without the pitch change. **The pitch image's sound engine was noisy on the maintainer's unit, pitched and, with a take, at its own pitch, and the cause is not found**: in emulation that engine records a take exactly and plays it bit for bit. This is the file to flash until it is.

Needs the unit: that the noise is gone with it. If it is not, the noise is not the sound engine's.


## The stereo image

A twenty-first file, `make image-stereo`: `build/images/Syntakt_OS1.42_sampler_stereo.syx`, SHA-256 `a81afad2d67d7b590055a993571c5d704011757677ad628413fa2e72b37b0051` (its third build, second step, 2026-10-11; the first build was `83777a0d...`, the second `99e56954...`). It is the save image with a stereo sample on one track where it took two. Both CPUs, and the first image in which something new crosses between them every block. The first build ran on the unit: fine with every sample at its own pitch, "major distortion" with eight stereo samples pitched. The second makes a pitched frame for less than half the work and passes on the unit (2026-10-11): "The stereo image, second build" below.

| Where | Size | What |
|---|---|---|
| section 7, `0x40000b92` | 372 B | a stock routine nothing reaches, before the entry point: the right channels through stock's stages, 362 B used |
| section 7, `0x40005964`, `0x400050a6`, `0x40005866` | 168, 134, 130 B | three more: the exchange of the filters' memory, a right channel's start, the window, the routine the interrupt calls; 390 B used |
| section 7, `0x40001708` | 344 B | the step after the voice loop: it no longer lends the next track, and says which tracks have a right channel |
| section 7, `0x40002d86` | 1,326 B | the render: every track may hold a right channel |
| section 7, `0x40000abe` | 4 B | the interrupt's call of its last stage goes to our routine, which calls it |
| section 3, `0x401bcb6c` | 346 B | a stock routine nothing reaches: the second set of buffers is filled, 270 B used |
| section 3, `0x4008f80e`, `0x4008f946`, `0x4008fb54`, `0x4008fb6c` | 4 B each | the mixer's four right-hand passes read the second set |
| section 3, `0x4008f930`, `0x4008fb30`, `0x4008fb3e` | 4 B each | the copies of the two returns made before a right-hand pass go after it |
| section 3, `0x400a4e30` | 10 B | where the per-block routine waits for the track buffers: our routine, which waits and then fills the second set |
| section 3, `0x401011e4` | 396 B | the mixer link, without the link: the mute is what is left |

Memory it uses that stock does not: on the audio CPU, `0x44050000..0x44050960` of free SDRAM (the right channels, a mask, two copies of state, the shape of stock's filter memory); on the main CPU, 1,280 bytes at `0x4556a000`, between the program's data and the effects' memory; in the window, `0x5b0..0x800` and `0xe38..0x1000`.

Shown in emulation (`tests/test_stereo.py`, 71): a right channel leaves the audio CPU exactly as a stock track would have made it, fed that signal, with the stage knobs, the trigs, MODE and the machines moving, and with all eight tracks stereo; the left channels, every stock machine and a mono sampler are bit for bit what they were; nothing in free memory or in the window is believed from before a start; our routines write nothing but their own; the main CPU's routine fills the second set from the window, or with the left buffers when the window's long does not agree with itself or the audio CPU is down; the real mixer with the second set a copy of the first is stock bit for bit, and with stereo tracks its left sums are stock's of the left buffers and its right sums stock's of the right ones; the two programs together from the voices to the mixer's sums; the place the routine is called from goes on as stock does, with nothing branching into it. The 21 images before it build to the same hashes.

Needs the unit:

| Question | What was assumed | Check |
|---|---|---|
| Are the window's two stretches shared memory | it is one memory from 0 to `0x1000` | a stereo sample on one track is stereo: pan it left and right and hear two different channels |
| Does the main CPU read a right channel in time | stock's own order, the right channels written last and read first | no clicks on the right side of a stereo track, with the sequencer busy |
| How many at once | nothing | eight stereo tracks at their own pitch, then pitched: where it crackles |
| The track after a stereo one | the link is gone | it plays its own machine, panned where its own knob is |
| The new runs and the second set's place | reached and named by nothing | the unit starts, and a stereo note plays |

If the first fails, every stereo sample plays as its left on both sides and nothing else is wrong. The way back: the save image, `031e1a0e...`, through the normal OS upgrade.

## The stereo image, second build

2026-10-11, after the unit's word on the first: "it works fine when they are all pitched normlly but when i pitch them it causes major distortion". Section 7 only; the main CPU's program is the first build's.

| Where | Size | What |
|---|---|---|
| section 7, `0x400097dc` | 830 B | stock Twinshot's update and render, which nothing reaches: the sums of sixteen frames for two channels and the routine's ends, 790 B used |
| section 7, `0x40005a8e` | 1,292 B | the sampler's second run: the player asks for a run of frames; the old sum is gone and the one-channel sum is in its place, 1,178 B used |
| section 7, `0x40003512` | 204 B | the table is made as longs |
| audio CPU memory, `0x44061000` | 2,112 B | free SDRAM: the table as 33 rows of 16 longs, made on the first interrupt after a start |

Shown in emulation (`tests/test_quick.py`, 342; `tests/test_stereo.py`, 74): every frame is the one the first build made, bit for bit, against the reference model, against the old arithmetic at every fraction of a frame, and against the pitch image's engine with eight tracks and stock machines between them; the multiply and accumulate unit is left as it was found, and asked nothing stock's code does not ask of it; eight pitched stereo tracks are 116,679 instructions an interrupt where they were 160,319, against 117,348 for stock's heaviest machine on all eight. The 21 images before it are byte for byte what they were.

Needs the unit:

| Question | What was assumed | Check |
|---|---|---|
| Do eight pitched stereo tracks fit the audio CPU's time now | that what stock's heaviest machine asks on all eight tracks fits, and that a count of instructions is near enough to time | the third check of the stereo set: pitch them all, listen; if it breaks up, how many it takes |
| Is a pitched note the same sound | bit for bit in emulation | a pitched sample sounds as it did on the save image |

On the unit, 2026-10-11 (`docs/FINDINGS.md`, hardware log): both pass, and so does the first build's own first question, left and right on their own sides on every track. Marks without notes and "seems like it works"; no recording was measured.

## The time image

A tool, `make image-time`: `build/images/Syntakt_OS1.42_sampler_time.syx`, SHA-256 `37a5061e39c4dadb5d41191366139d3f195c1933a5df65e57596279b40af34a7` (with the stereo image's third build in it; `bcd06158...`, with the second, is the one that ran on the unit on 2026-10-11 and read 72, 99 and over, and 81: hardware log). The stereo image with the audio CPU's load on the sampling page, for the question the bench cannot answer: how near its time the audio CPU is. Not one to keep. Not on the unit.

| Where | Size | What |
|---|---|---|
| section 7, `0x40006764` | 514 B | stock Twinshot's player and filter, which nothing reaches: a timer read where the interrupt calls the voice loop and where its last stage comes back, and the two numbers worked out, 272 B used |
| section 7, `0x40000a36`, `0x40000abe` | 4 B each | those two calls of the interrupt's go there first |
| section 3, the page's runs | 106 B | the page writes the two numbers in its lower row |
| audio CPU memory, `0x44050a00` | 24 B | free SDRAM: what is counted |
| the window, `0x5b4` | 8 B | the two numbers, as text |

Shown in emulation (`tests/test_time.py`, 32), with a count supplied in the timer's place: the sound is the stereo image's block for block; the numbers are the longest stretch of an interrupt over a block, and the most of late; a timer that does not count is not divided by. Read from the listing: stock starts the timer and never reads it.

Needs the unit:

| Question | What was assumed | Check |
|---|---|---|
| Does the second timer count | stock switches its clock on and sets it to run free on the bus clock | C is not 000 and moves with what plays |
| What does the unit carry | nothing | C and P with eight SY SWARMs, then with eight pitched stereo samples |

## The stereo image, third build, and the time12 image

2026-10-11, after the time image's readings: the second build's eight pitched stereo tracks take 99 hundredths of a block and at times more, stock's heaviest about 88. Section 7 only.

| Where | Size | What |
|---|---|---|
| section 7, `0x40006764` | 514 B | stock Twinshot's player and filter, which nothing reaches: a voice's level and gain for both channels in one pass, 280 B used |
| section 7, `0x40002d86` | 1,326 B | the render calls that pass where it called two of stock's routines a channel, 1,178 B used |
| section 7, `0x400097dc`, `0x40005a8e`, `0x400050a6`, `0x40005964`, `0x40001708` | | the right channels' three copies moved and made shorter |

The time12 image, `make image-time12`: `build/images/Syntakt_OS1.42_sampler_time12.syx`, SHA-256 `bb2c9253041f7e43cd0b5898f32bc1b6d93ce4c96c1cb624777aa485d5812979` (its first step, `423b867b...`, ran on the unit: P near 90). The time image with a pitched frame summed from twelve frames: the same routine with the outer two frames at each end left out, and a table of twelve in the image.

Shown in emulation (`tests/test_lean.py`, 173): the pass is stock's two routines to the bit on any voice; the copies move what they have to; the engine is still the reference model and the pitch image's engine (`tests/test_quick.py`); the engine of twelve is the model with the table of twelve, and a tone two octaves down has everything else 71 to 88 dB under it where sixteen have 76 to 89. Eight pitched stereo tracks are 108,774 instructions an interrupt, and 102,615 with twelve.

Needs the unit:

| Question | What was assumed | Check |
|---|---|---|
| What do eight pitched stereo tracks read now | about 92 with sixteen, 87 with twelve, by counts that were a sixth out before | P on the time image, then on the time12 image |
| Is twelve heard | 5 dB less clean at the very top, 1 to 3 elsewhere | the same pitched samples on both |

## The gain image

`make image-gain`: `build/images/Syntakt_OS1.42_sampler_gain.syx`, SHA-256 `461e4f4d072a31b74d0a928f34e4995d673c0580d60677e57ce4bac9f8fe7816`. The stereo image with the sum of twelve frames in its sound engine, and a record gain. **On the unit 2026-10-12: both checks below passed** ("verything looks good with rec gain").

| Where | Size | What |
|---|---|---|
| section 7 | | the stereo image's third build with the table of twelve: what ran on the unit as the time12 image, without that image's meter |
| section 3, `0x40088510` | 634 B | the feed's run: seven numbers where there were four, a table of 25, and the meter's level times the gain |
| section 3, `0x400a15cc`, `0x4008f13e` | 360, 238 B | the feed's conversion calls the multiplication, which is in the run of REC's mark |
| section 3, the page's three runs, and `0x401bd514` | 346 B | the page: knob F and the lower row's second place. A fourth run, which nothing reaches, 136 B used |

Shown in emulation (`tests/test_gain.py`, 55): at 0 dB the feed is the stereo image's bit for bit; with a gain every sample is the source's top 24 bits times it, held to 32 bits, before it is made 16; a quiet tone recorded with 24 dB of gain is 21 to 27 dB cleaner than the same take turned up afterwards; the meter shows the level with the gain on; the page's knob, place and stops.

Needs the unit:

| Question | What was assumed | Check |
|---|---|---|
| Does knob F on the sampling page turn the gain, and does the box read it | the page's other knobs' turns arrive the same way | turn it: `0dB` to `+24dB` |
| Does a quiet source come up clean | the arithmetic, in emulation | record something quiet at 0 and at +18, play both at the same loudness |

## The mode image

`make image-mode`: `build/images/Syntakt_OS1.42_sampler_mode.syx`, SHA-256 `2871f7f16088c5cc9c8486e350040bbf3998265438be607653d775fcbd777a22`. The gain image with a sample that is mono or stereo by what its slots hold, MODE on the sampling page as what a take is, and the audio CPU's peak in the page's last box. Not on the unit.

| Where | Size | What |
|---|---|---|
| section 7, the runs it had | | the time12 image's engine, with SMPL always counting samples, the rule of the second slot, a mono take, and without the chained slots' code. The table is held as twelve numbers a row |
| section 3, the feed's three runs | 628, 360, 232 B | a mono take's half sum, in the routine that multiplies |
| section 3, the page's four runs | 258 of 346 B in the fourth | knob G and the lower row's third place; the first page's sixth place empty; the peak in the last place |
| section 3, `0x40124852` | 464 B | SMPL's text without a look at MODE |
| section 3, MODE's descriptor | 4 B | its default: 1 |

Shown in emulation (`tests/test_mode.py`, 151): a sample plays as it did, frame for frame, found for what it is; the engine is the model; a mono and a stereo take on both CPUs, and what the keep is answered; the page; both sections against the images before.

Needs the unit:

| Question | What was assumed | Check |
|---|---|---|
| Does a stereo sample play in stereo and a mono one in mono with nothing set | the rule, in emulation | SMPL through samples of both kinds |
| Does the first page draw with its sixth place empty, and knob G turn MODE on the second | the second page's empty places draw so | look, and turn |
| Is a mono take mono after a save and a restart | a take of one frame is a sample like another to the drive's code | record one over a stereo take, SAVE, power cycle, play |
| Does P read in the last box as it did on the time image | the same long, drawn in another place | play, and read it |

## The cross image

`make image-cross`: `build/images/Syntakt_OS1.42_sampler_cross.syx`, SHA-256 `246245d15ce8901ec987496ae42e4cb90ace0d79979b103bc0a79f2961bbf31a`. The mode image with a crossfade at a loop's seam. Audio CPU only. **On the unit, 2026-10-12: its three checks marked passed, no notes** (`docs/FINDINGS.md`, hardware log). The number in the last box was not given.

| Where | Size | What |
|---|---|---|
| section 7, `0x40004608` | 90 of 108 B | a pass goes into its blend. The last small run nothing had taken |
| section 7, the runs it had | 510 B | the seam worked out, the blend written (172 B of them), the turn given, the wrap |
| audio CPU memory, `0x44062000` | 8 x 2 KB | a voice's blend: the seam, then 352 frames a channel |

Shown in emulation (`tests/test_cross.py`, 137): the engine is the model for every kind of loop, pitch and knob script; a steady level does not move through a seam; a loop is as long as it was; where there is nothing to blend with it is the mode image; a block in a seam costs less than a block of the dip.

Needs the unit:

| Question | What was assumed | Check |
|---|---|---|
| Is the dip gone from a loop cut out of a sample | the arithmetic | something steady, LOOP FWD, STRT and LEN in the middle: listen to the seam |
| Does a recorded bar still loop in time | the loop's length is not touched | a bar against its pattern for a minute |
| What does P read with eight pitched stereo loops | 600 instructions a steady block more, 2,100 for 30 ms after a note starts | the meter in the last box, against 85 |

## The pack image

`make image-pack`: `build/images/Syntakt_OS1.42_sampler_pack.syx`, SHA-256 `64d124bf5b3e00265b209094632039b0ab418ca6e1f6329c58e7944a41fe7cd8`. The cross image with mono samples in single slots at the back: SMPL 1 to 32 are the stereo samples as they were, 33 to 64 the slots of those numbers, each a mono sample. Both CPUs. Not on the unit.

| Where | Size | What |
|---|---|---|
| section 7, a note's start and the slot's look-up | 34 B more | a value past 32 is a slot, and no right channel is sought for it |
| section 7, `0x40004708` | 208 of 226 B | the take's routine, written by hand: a single slot's take is half of the two sides, in its own buffer alone |
| section 7, `0x40005624` | 28 B | the time image's hook, moved for room |
| section 3, the page and the knob's text | a number, a call | DEST goes to 64; SMPL past 32 reads the slot's own name |

Shown in emulation (`tests/test_pack.py`, 131): the 32 stereo places are the cross image's frames; a single slot is the model and plays alone whatever its neighbour holds, with all 64 slots of one length too; a take in a single slot touches that slot and nothing else; the hand-written routine is the cross image's block for block through every way a take ends; an interrupt costs what it did (112 instructions more in the block eight notes start in).

Needs the unit:

| Question | What was assumed | Check |
|---|---|---|
| Does a mono sample sent to slot 64 play at SMPL 64, and a stereo one at 1 | the pool holds 64 slots as it always did | `make samples PACK=1`, send, restart, turn SMPL |
| Does a mono take at SMPL 64 survive SAVE and a power cycle, with slot 63 as it was | the keep's requests are a slot each, and the take's routine writes one slot | record at 64 over a set that has something in 63, SAVE, power cycle, play both |
| Is the cross image's seam there | the stereo places are its frames | a loop cut out of a sample, by ear |

## The stops image

`make image-stops`: `build/images/Syntakt_OS1.42_sampler_stops.syx`, SHA-256 `188cecb8c2940e17af348f79c2a2f257540dcac0ac87789e10fb5f47ba4ca59c`. The pack image with a SMPL knob that stops only on samples: the stereo samples, the lowest free stereo place, the highest free single slot, the mono samples. A slot's length says which kind it holds. Both CPUs. Not on the unit. In `build/flash_this/`.

| Where | Size | What |
|---|---|---|
| section 7, `0x400028e6` and `0x40001834` | 40 and 32 B | what every slot holds, said to the main CPU: sixteen slots a block into one of four longs of the window, and a mark |
| section 7, the hook's end (`0x40005ec6`) | 2 B more | its return goes on to that routine |
| section 7, `0x40004708` | 216 of 226 B | the take's routine: a single slot's take a frame short of its blocks, a mono take's second slot two frames |
| section 3, `0x401bc860` and `0x40088a80` | 472 of 602 B, 514 of 680 B | a turn of SMPL on a sampler's first page: the stops worked out from the window, the change through stock's methods. Two more runs nothing reaches |
| section 3, `0x401ca3c0` and `0x401ca47c` | 4 B each | a turn's two entries go to ours first, which hands on to what was there |
| section 3, `0x401bcb6c` | 280 of 346 B | the right channels' routine also sets the mark to 0 while the audio CPU is down |

The page's first four runs and every other patch of section 3 are the pack image's to the byte.

Shown in emulation (`tests/test_stops.py`, 116, and `tests/test_split.py`, 18): what the audio CPU says is right four blocks after a start with anything in memory, and follows takes, loads and emptied slots; a take's length is its kind from its first block and everything else of a take is the pack image's; the knob goes by the rule for 17 banks worked by hand and 10 at random from every value, on stock's own methods for a value and a lock; a held step, a pushed turn, FUNC, a missing mark, the audio CPU down; every other knob of both pages is the pack image's; an odd length goes from the drive's header to the audio CPU's table; an interrupt costs the pack image's and 128 instructions. The 28 images before build to the same hashes.

Needs the unit:

| Question | What was assumed | Check |
|---|---|---|
| Does a mono file of an odd number of frames arrive as a slot of an odd number of frames | Transfer sends a file's own frames (read in its program), and the unit keeps the header's count | `make samples PACK=1` with a few mono files, send, restart: SMPL stops on each of them at its slot's number and skips the empty slots |
| Does the knob stop only on samples, and one free spot of each kind | the two CPUs see the three places in the window | turn SMPL end to end on a bank with stereo samples in front and mono ones at the back |
| Is a take one click past the last sample of its kind, and a sample once recorded | a take's length is its kind from its first block | record a stereo take on the free place and a mono one on the free slot: each becomes a stop and the next free one appears beside it |
| Do old projects still play what they played | a number keeps its meaning | a pattern from before, untouched |
| What does P read | 128 instructions a block more | the meter in the page's last box, against 85 |

If SMPL stops on every number, the page is not being told what the slots hold (the mark does not read right): everything else is the pack image's and works as it did. Say so and it can be looked at.

## The solo image

`make image-solo`: `build/images/Syntakt_OS1.42_sampler_solo.syx`, SHA-256 `b92d6268f3098b3085831ab359d50b5aebb8a2fbd8ca3d38db4424b724ad6b21`. The stops image with the purple pattern mutes as solos. Main CPU only: section 7 is the stops image's byte for byte. Not on the unit, and not in `build/flash_this/`: the stops image is there and has not been run yet.

| Where | Size | What |
|---|---|---|
| section 3, `0x400a2928` | 94 of 166 B | one more run nothing reaches (`tools/deadcode.py`): the word's rule, the four stores, the keys' question |
| section 3, `0x400a30b2` and `0x4010d4b8` | 6 B each | stock's two routines that store an engine's copy of the pattern's mutes: a jump to ours |
| section 3, `0x400a3c26` and `0x4010dc76` | 6 B each | the same store in each engine's message loop: a call to ours |
| section 3, `0x400376c4` and `0x400376a8` | 4 and 6 B | the keys' colours: "silenced by a solo" where a pattern's bit was asked, and where a song row's was shifted out |
| section 3, `0x40037400` | 4 B | the one draw that asks the same of a pattern |

Every other byte of section 3 is the stops image's. Nothing that reads either copy is changed, stock's or ours, and no C of ours.

Shown in emulation (`tests/test_solo.py`, 80), from the built image: stock's two routines for every word, and the two stores, hold the tracks the solos silence and touch nothing else; stock's track test in both engines' loops with that word keeps a soloed MIDI track's event and drops the others', and a track that makes sound keeps its events; our mixer link and analog mute show the mixer volume 0 and set the analog level words 0 for exactly the tracks not soloed, with global mutes on top; the keys' question next to stock's own routine for thirteen tracks, and stock's colouring from it: lit for a heard track, dark for a silenced one; a pattern with no settings; the program against the stops image's. The 29 images before build to the same hashes.

Needs the unit:

| Question | What was assumed | Check |
|---|---|---|
| Does a purple key solo at once | the playing pattern's change comes through one of the four stores | pattern mute mode, a pattern playing on several tracks: press one track's key, then a second |
| Are the keys lit for what is heard | mode 1 is the purple one, colour 28 lit and 2 dark (read, never seen) | all twelve purple with no solo, the soloed ones alone with one |
| Does a green mute still win, and the FX key still mute | they are other words and another bit | green-mute a soloed track; the FX key in the purple mode |
| A pattern change, a project's load, song mode | the same four stores | a second pattern with other solos; power off and on; a song row |
| What does the screen draw | the draw's question for a pattern is the keys' | the boxes in the purple mode, and with keys prepared |
| Eleven tracks silenced in one block | each fades within the block, as one does | listen for a click at the key |

Main CPU room after it: 165 of the 180 runs of 64 bytes and up that nothing reaches are untouched, 33,672 bytes, the largest 848; and 72 bytes of this run.

## The ptn image

`make image-ptn`: `build/images/Syntakt_OS1.42_sampler_ptn.syx`, SHA-256 `62432c21667705184f024bc3c08cb06ffe011076c5d85b1d18cbf9462bfeed91`. The solo image with the takes written when a whole pattern is saved to the project, and no SAVE box on the sampling page. Main CPU only: section 7 is the solo image's byte for byte, which is the stops image's. Not on the unit, and not in `build/flash_this/`: the solo image is there and has not been run yet.

| Where | Size | What |
|---|---|---|
| section 3, `0x40182756` and `0x401826c2` | 4 B each | the two calls of stock's pattern save that save a whole pattern to the project, after the Y/N and after the naming screen: ours in its place |
| section 3, `0x401259fa` | 824 of 930 B | the keep code's run: 48 bytes more for ours, which calls stock's and starts the job; a take that changed no longer ends the run. No new run |
| section 3, `0x4005bad8` and `0x4005bc2e` | 4 B each | the project save's two calls: their routine of ours moved four bytes |
| section 3, `0x4001b51e` and `0x401bceac` | 1,488 of 1,522 and 758 of 918 B | the page's first and third runs: no routine for a turn of the fifth knob, and FAIL alone where the box's word was |

Every other byte of section 3 is the solo image's. The other three calls of stock's pattern save are stock's: the main screen's save to the temp area, KIT DATA, SEQUENCE DATA.

Shown in emulation (`tests/test_ptn.py`, 53), from the built image: which calls go where; ours passes five longs and stock's answer through and goes by the answer's low byte; stock's pattern save run as it is under ours, a good save and seven kinds of failed one; the job's takes in the loaded bank through the store's own write; two saves in a row and one while the job has not run; a failed write and the save after it; a take that changes while it is written, from a pattern's save and from a project's; a project's save as it was; stock's four callbacks of the menu run as they are; the page's fifth place and its knob next to the solo image's; the main program against the solo image's; section 7. The 30 images before build to the same hashes.

Needs the unit:

| Question | What was assumed | Check |
|---|---|---|
| Does a whole pattern's save keep a take | the runner takes a job from the task the menu's callback runs in, as it does from a knob's turn | record a take, pattern menu, SAVE TO PROJ, WHOLE PATTERN, yes; wait five seconds; power off and on; play it |
| Does the unit carry on meanwhile | the job shows nothing and the pop-up is stock's | the same with a pattern running and a take of several seconds: the pop-up at once, no stall, keys and screen alive |
| Is the fifth place empty and its knob dead | read FAIL only with the long at 3 | the sampling page before, during and after a save; turn knob E |
| A pattern with no name | stock opens the naming screen and its callback saves; ours is under it | a new pattern in a saved project, record, SAVE TO PROJ, WHOLE PATTERN: name it, confirm, power off and on |
| The other saves | stock's, not touched | FUNC+YES, KIT DATA, SEQUENCE DATA: the pattern is saved as before, no take is written |

Main CPU room after it: as after the solo image (no new run), and 106 bytes of the keep code's run. FAIL on the page is 74 bytes of the page's runs, should it go.

## The srr image

Proven in emulation (`tests/test_srr.py`, 94): the hold against its model frame for frame; the sound at 0 the multi image's to the bit; a take by the mark alone; SWARM's stand-in; the per-block routine's every case; the feed by its word; both programs changed only where declared, the multi image still `eceba3b3`.

Needs hardware:

| check | why |
|---|---|
| SRR crushes, locks to a step, takes an LFO | the knob is stock's own of record 502; that the record is in the LFO's list is not confirmed |
| REC and SRC read as before on an old project; SRC and SRR there after a save and a power cycle | that the kit is saved slot for slot is inferred: if slot 24 is not saved, SRC comes back wrong and SRR at 0 |
| P with eight tracks crushed | a count is not time: counted at 2.2 hundredths of stock's heaviest |

## The gear image

Proven in emulation (`tests/test_gear.py`, 13), stock's change routine played by the test: every sampling page knob but the crossfade's, and SMPL, goes through stock's three knob routines with the right feel and moves by the whole part of what comes back; the crossfade's knob as it was; REC and SRC as the track's word in the kit; section 3 changed only in the page's runs, section 7 the srr image's.

Needs hardware:

| check | why |
|---|---|
| the page's knobs and SMPL feel right, and still reach both ends | stock's change routine and its feels do not run in emulation; a plain knob's ticks a step were not read |

## The prof image

Kept in every image from here on, on the stay image, off until the sampling page's last knob turns it on (the first build was a tool on the gear image). Proven in emulation (`tests/test_prof.py`, 10: with it off the last source is the sends, and the knob switches it): the per-block interrupt's first two instructions go to our routine, which keeps what was stopped and goes on as stock does; stock's rte comes to our end and ours returns to what was stopped; a track on SENDS is fed the record and every other track the gear image's block; with no track on SENDS the window is the gear image's; the reader gives back a made-up take; the image is the gear image but for the profile.

Needs the unit, all of it: a real interrupt through the hook (a hang at the first block if the frame is not as read), the timer counting, a take coming off the +Drive word for word. One check: record five seconds on SENDS, `make prof-read`, and the reader says how many blocks it could time.

## The stay image

Proven in emulation (`tests/test_stay.py`, 8), stock's fragment of the step routine run as it is: a ONCE stays where a track is only brought up to date and is spent where the sequencer plays the step; a track's own ONCE the same; old locks of MODE go at the next message; section 3 changed only in the two runs and three operands.

Needs hardware:

| check | why |
|---|---|
| REC locks to ONCE on the first step with the sequencer stopped, and records once after a start | which of the step routine's two callers plays the first step at a start was not traced |

