# The sampler machine

A sampler for the Syntakt's digital tracks, in Twinshot's place (machine type 44; the machine list still calls it SP TWINSHOT). It runs on the maintainer's unit: what was seen there, and with which build of which image, is in `docs/FINDINGS.md`, hardware log.

Source: `engine/sampler.c`, `engine/stub.S`. Specification: `emu/sampler_ref.py`. The compiled engine is held bit-identical to that model by `tests/test_sampler.py`.

## Thirty-seven images

| Image | Built by | Changes | Screen | Stereo right-hand track |
|---|---|---|---|---|
| audio only | `make image` | audio CPU program only | Twinshot's names and defaults | set pan, volume and sends by hand |
| full | `make image-full` | plus the main CPU program, OS 1.42 only | the sampler's own names, ranges and defaults | follows the left track by itself |
| recorder | `make image-rec` | full, plus the recorder on both CPUs | as full | as full |
| big | `make image-big` | recorder, plus sample slots of 1 MB on the +Drive | as full | as full |
| keep | `make image-keep` | big, plus takes written to the +Drive when a project is saved | as full | as full |
| double | `make image-double` | keep, plus twice the samples loaded at boot | as full | as full |
| screen | `make image-screen` | double, plus what SMPL, LOOP and MODE read | names and words, see "Names and words on screen" | as full |
| page | `make image-page` | screen, plus the sampling page: a second page behind SYN on a sampler track, where REC puts the track in record | as screen, but MODE reads MONO or STEREO, and SYN pressed again shows SRC, DEST and REC | as full |
| load | `make image-load` | page, plus the drive's samples put back in the slots recorded over when a project is loaded | as page | as full |
| bank | `make image-bank` | load, plus three sample banks on the drive, one a project | as load, and BANK on the sampling page | as full |
| fade | `make image-fade` | bank, plus fades in the sound engine where a sample is cut into | as bank | as full |
| mute | `make image-mute` | fade, plus a mute that only silences: a muted track's trigs still fire | as bank | as full |
| len | `make image-len` | mute, plus LEN that acts while a note plays | as bank | as full |
| live | `make image-live` | len, plus STRT: a loop's next pass begins where the knob is | as bank | as full |
| floor | `make image-floor` | live, plus LEN that stops at 3 | as bank, LEN reads 3 to 127 | as full |
| reclock | `make image-reclock` | floor, plus a step's REC as a lock of its own | as floor | as full |
| pitch | `make image-pitch` | reclock, plus a clean sound at any pitch: sixteen frames and a table where two frames and a line were | as floor | as full |
| meter | `make image-meter` | pitch, plus the sampling page's level meter and sixteen sources. Main CPU only | as floor, and SRC reads MAIN, EXT, T1 to T12, FX, DELRV | as full |
| save | `make image-save` | meter, plus SAVE on the sampling page: the takes written to the drive, without the project. Main CPU only | as meter, and the fifth box reads SAVE | as full |
| safe | `make image-safe` | the save image's main program on the reclock image's sound engine: no pitch change | as save | as full |
| stereo | `make image-stereo` | the save image, plus **a stereo sample on one track**: its right channel no longer takes the next track. Both CPUs. Its first build on the unit (2026-10-11): fine with every sample at its own pitch, "major distortion" with them pitched. The second build, the same day, makes a pitched note cost half as much and works on the unit by ear, pitched too; its meter then read eight pitched stereo tracks at 99 of a block and over. **The third build** makes the interrupt shorter with no change to the sound; not on the unit yet | as save | there is none: the track after a stereo one is its own |
| time | `make image-time` | **a tool, not one to keep:** the stereo image with the audio CPU's load on the sampling page, measured on the unit by a timer of its own. Both CPUs. On the unit 2026-10-11 with the stereo image's second build in it; rebuilt since with the third | as stereo, and two numbers in the lower row: C and P | as stereo |
| time12 | `make image-time12` | **a tool:** the time image with a pitched frame summed from twelve frames, not sixteen: less work, a little less clean. To hear and to read beside the time image | as time | as stereo |
| gain | `make image-gain` | the stereo image with a pitched frame summed from twelve frames (what the maintainer ran before it: peak never above 85 on the unit's meter), plus **a record gain** on the sampling page. Main CPU only on top of that. **On the unit 2026-10-12, and the gain works there** | as stereo, and the lower row's second box reads the gain | as stereo |
| mode | `make image-mode` | gain, plus **a sample that is mono or stereo by itself**: MODE no longer says how a track plays, it says what a take is, and its knob is on the sampling page. Both CPUs. And, while the images are being built, the time image's routine with the audio CPU's peak in the page's last box. **On the unit 2026-10-12 inside the cross image: its checks marked passed** | as gain; the first page's sixth place is empty; the sampling page's lower row reads SAVE, the gain, MONO or STER, and P with three figures | as stereo |
| cross | `make image-cross` | mode, plus **a crossfade at a loop's seam** in place of the dip, wherever there is sound before the loop's start or after its end to blend with. Audio CPU only. **On the unit 2026-10-12: three checks marked passed** (samples as what they are, the seam, a mono take kept through a power cycle) | as mode | as stereo |
| pack | `make image-pack` | cross, plus **mono samples in single slots at the back**: SMPL 1 to 32 are the stereo samples as before, 33 to 64 the slots of those numbers, each a mono sample. A take sent to one is mono and touches that slot alone. Both CPUs. Not on the unit | as mode; SMPL past 32 reads a slot's own name, and DEST goes to 64 | as stereo |
| stops | `make image-stops` | pack, plus **a SMPL knob that stops only on samples**: the stereo samples, the lowest free stereo place, the highest free single slot, the mono samples, and nothing between. A slot's length says which kind it holds: odd is a single slot's mono sample. Both CPUs. Not on the unit | as pack | as stereo |
| solo | `make image-solo` | stops, plus **the purple pattern mutes as solos**: a track whose key is on in the pattern is heard, and while any is the others are silenced as a mute silences them. Several at once; a green mute still mutes; the FX key is a mute as it was. Main CPU only. Not on the unit | as stops; in the pattern's mute mode a key is lit for a track that is heard | as stereo |
| ptn | `make image-ptn` | solo, plus **the takes written when a whole pattern is saved to the project** (SAVE TO PROJ, WHOLE PATTERN), in the background after the pop-up. The SAVE box is gone. Main CPU only. Not on the unit | as solo, but the sampling page's fifth place is empty: FAIL there after a save that did not get every take onto the drive | as stereo |
| feed | `make image-feed` | ptn, with **the record feed made cheap on the main CPU**, for the screen, lights and keys that drag with REC on: a block of a take in a third of the instructions or less, and the take what it was, to the bit. The sampling page asks which step is held once a drawing. Main CPU only. Not on the unit, and that the drag goes is not shown | as ptn, but the sampling page's fifth place is empty always: no FAIL | as stereo |
| once | `make image-once` | feed, plus **REC's third setting, ONCE**: a step locked to it records the next time it plays and its lock is then taken off (the trig stays); the track's own records from the next step the sequencer plays on it, once, and reads OFF after. Three places of stock's are changed: two in the routine that plays a step, one in the main task's loop. Main CPU only. Not on the unit | as feed, but REC reads OFF, ON or ONCE | as stereo |
| soloknob | `make image-soloknob` | once, with **the purple keys stock's pattern mutes again** (the solo image's seven places are stock's bytes) **and a solo on the sampling page's knob E**: while any track's solo is on, every track with none is silenced as a mute silences, and a soloed track is heard whatever is muted. Off at every start, not saved. Main CPU only. Not on the unit | as once, but the sampling page's fifth place reads SOLO or S OFF | as stereo |
| xfade | `make image-xfade` | soloknob, plus **a crossfade on the sampling page's knob G** (where MODE was): as it goes up every other track goes down, silent at 127. A take at a stereo place is always stereo. Main CPU only. Not on the unit | as soloknob; knob G reads XF0 to XF127 | as stereo |
| gfade | `make image-gfade` | xfade, with **one crossfade for the whole unit**: every sampling page shows and turns the same number, and the track that last turned it is the one that stays. Main CPU only. Not on the unit | as xfade | as stereo |
| dma | `make image-dma` | gfade, with **the right channels of stereo samples brought out of the window by the transfer controller**, as stock brings the left ones, and not read by the CPU inside the per-block interrupt: for the screen and knobs that lag when stereo samples play. Checked against the CPU's reads for a second after every start, and given up if they differ. Main CPU only. Not on the unit, and nothing of the transfer can be run in emulation | as gfade; the letter before the load in the sampling page's last box says how the right channels come: C checked, H by hardware, X given up | as stereo |
| apage | `make image-apage` | dma, plus **a second page behind SYN on the analog tracks** (9 to 12): SOLO on knob E and the unit's one crossfade on knob G, the other six places empty. An analog track can be soloed and can hold the crossfade. Main CPU only. Not on the unit. The solo is not lockable yet | as dma; SYN again on an analog track opens the page | as stereo |
| slock | `make image-slock` | apage, plus **a sampler track's solo lockable to a step**: hold a trig, turn knob E on the sampling page. Main CPU only. Not on the unit. Not on the analog tracks | as apage; with a step held the fifth place says the step's solo | as stereo |
| alock | `make image-alock` | slock, plus **an analog track's solo lockable to a step**: hold a trig on an analog track, SYN twice, knob E. Main CPU only. Not on the unit, and **built on a thing only the unit can show**: that the spare word the lock is kept in changes nothing of an analog voice | as slock | as stereo |
| multi | `make image-multi` | alock, plus **several tracks recording at once, each from its own SRC into its own DEST**: every sampler track with REC on is fed its own source, where the first one picked for all. Both CPUs. Not on the unit, and **only the unit can show** that takes have no clicks and that the screen and keys do not drag with several recording | as slock, the feed a block a track | as stereo, the take before the voices |
| srr | `make image-srr` | multi, plus **sample rate reduction**: SRR on the first page's sixth knob (MODE's parameter, freed), 0 off to 127, every 16 halving the rate; it locks to a step. REC and SRC are the track's own word on knob slot 24, made from an old pattern the first block it plays, one way. **SY SWARM is its room and plays nothing.** Both CPUs. Not on the unit. |
| prof | `make image-prof` | stay, plus **a profile of the main CPU, kept in every image after it and off until asked for**: the sampling page's last knob to the right (its box reads PROF), and a track whose SRC is the last source takes the profile in place of the sends. Off, the last source is the sends as always. Main CPU only. Not on the unit. |
| soft | `make image-soft` | prof, plus **no click at the start of a take**: a note whose first frame is loud is faded in over 1.3 ms, as a note that starts inside the sample is; a sample that begins near silence is not touched. Read "Fades". Audio CPU only. Not on the unit. |
| pre | `make image-pre` | soft, plus **muted sources still recorded**: a digital track or the FX track's return as SRC is read before the mixer, so it records and shows on the meter while it is muted or soloed out; a track's take no longer follows its LEVEL and AMP VOL (the record gain sets it); and the FX track's mute silences its return. Main CPU only. Not on the unit. |
| tail | `make image-tail` | pre, plus **no click at the end of a take**: a one-shot fades out over the 2.7 ms before its far end at full LEN too, as it did with LEN short of all. Read "Fades". Audio CPU only. Not on the unit. |
| lap | `make image-lap` | tail, plus **a finer profile**: five more readings of the timer on the way to the mixer, and the reader gives that stretch in six parts. A tool. Main CPU only. Not on the unit. |
| hitui | `make image-hitui` | hits, plus **the filter pages saying what DEL is on a sampler track**: HITS under its knob on FLTR2 and in its pop-up, and no delay in FLTR1's picture of the envelope. Main CPU only. Not on the unit. |
| trim | `make image-trim` | hitui, plus **pitched notes, fades and loops for less of the audio CPU's time**: a pitched frame's sum in 22 fewer instructions (off by under a tenth of a 16-bit step), the fade the same to the bit in fewer, and a loop's crossfade kept from note to note while its sample is as it was. Eight pitched stereo loops: about 6,100 fewer instructions a block, the heaviest 8,224 fewer. Audio CPU only. Not on the unit. |
| slim | `make image-slim` | trim, plus **the pitched sum's two tests worked out once a run** for two channels: the same sound to the bit, about 1,400 fewer instructions a block with eight pitched stereo tracks. Hits off where DEL is 0 was asked and not built: DEL does not reach the audio CPU. Audio CPU only. |
| six | `make image-six` | slim, plus **a pitched frame summed from six frames, not twelve**: about 6,200 fewer instructions a block with eight pitched stereo tracks, 4,600 mono. At a sample's own pitch or octaves up nothing changes. Pitched either way, a sine at 10 kHz is 60 dB clean where it was 78, at 15 kHz 26 where it was 53. Audio CPU only. |
| eight | `make image-eight` | slim, plus **a pitched frame summed from eight frames, not twelve**, in six's place ("too much filtering"): about 4,100 fewer instructions a block with eight pitched stereo tracks, 4,600 mono; own pitch and octaves up unchanged; a tone at 15 kHz pitched is 44 dB clean where twelve is 53 and six was 26. Audio CPU only. |
| phone | `make image-phone` | six, plus **the unit asks the phone at LOAD PROJECT** which of the project's bank's slots it changed, waits for its answer (2 s, then 4 s after each sign of work; no phone or no answer and the load is as before), and loads those slots into the audio CPU as well as the takes. Main CPU only; `engine/phone.c`, `tests/test_phone.py` (11). |
| trig | `make image-trig` | phone, plus four of his fixes: **the first page reads TUNE SMPL LOOP DEC / STRT LEN SRR OVER** (STRT and LOOP, LEN and SRR changed over; locks stay with their knobs); **the track holding the crossfade is heard through a global mute** as it goes up (not a pattern mute, not with a solo on); **a hit's loudness in 2 dB steps from -31 to -3 dB** (were 3 dB from -45), so DEL is finer and a hit under -31 dB is none; **on a sampler track the TRIG page's E and F are SOLO and REC** (LFO.T and FLT.T keep what a trig holds, on, and are not shown), turning and locking as on the sampling page, whose E is empty now. Both CPUs; `tests/test_trig.py` (39). Not on the unit |
| switch | `make image-switch` | trig, plus **a hit's steps counted from each sample's own loudest frame** (2 dB a step, DEL 1 the hits within 3 dB of it, so a quiet take triggers as a loud one; a first pass finds the peak, about a second for a long take), and **SOLO and REC on the TRIG page drawn as stock's switch**, a ball in an oval (REC's ONCE as the word). Both CPUs; `tests/test_switch.py` (10). Not on the unit |
| box | `make image-box` | switch, plus **no dotted boxes around SOLO and REC on the TRIG page**, and **REC only OFF or ONCE** on the TRIG page and the sampling page (right ONCE, left OFF; the switch is on at ONCE). Main CPU only; `tests/test_box.py` (7). Not on the unit |
| xknob | `make image-xknob` | box, plus **the crossfade on the first page's knob D (XF0 to XF127) in DEC's place and slot: kept with the pattern, lockable, LFO-able, one track's at a time** (turning one zeroes the other tracks', analog ones too). DEC is gone, a note always holds; an old project comes up with no crossfade. The sampling page's knob G is empty. Both CPUs; `tests/test_xknob.py` (23). Not on the unit |
| xshare | `make image-xshare` | xknob, plus **knob D is the pattern's one crossfade on every sampler track**: each track's D shows it, and turning it on any track carries the amount over and makes that track the holder; with a step held it only locks the step. Main CPU only; `tests/test_xshare.py` (6). Not on the unit |
| fltr | `make image-fltr` | xshare, plus **LFO.T and FLT.T on FLTR2's G and H** on a sampler track (stock's records and turn, drawn as switches as FENR is; SOLO and REC stay on the TRIG page), **the audio CPU's peak back in the sampling page's last place** (gone since xknob), and **the phone's load query**: 0x63 answered by 0x64 with the last project loaded (the one it started with, before any load), its bank, the loads since the start and the start's id. Main CPU only; `tests/test_fltr.py` (24). Not on the unit |
| tlsolo | `make image-tlsolo` | fltr, plus **a held step's SOLO always locked to what it is turned to**, OFF too where the track's own is off, so a trigless step can end a solo an earlier one began. Main CPU only; `tests/test_tlsolo.py` (12). Not on the unit |
| long | `make image-long` | tlsolo, plus **patterns 1..64 long, 65..128 their tails**: a cue of pattern n puts n + 64 after it in stock's play queue with n's kit, so the two play as 128 steps with one sound, and the UI's kit stays n's while the tail plays. A tail cued by hand plays alone with its own kit. Live record across the seam: a hit just before step 65 goes to the tail's first step, one just before the loop's start to the head's (second build). A clear, a copy and a paste of a head carry its tail (third build). The tail's length, swing and mutes are its own; the pages still show 64 steps (the tail's while it plays). Main CPU only; `tests/test_long.py` (17). Not on the unit |
| slice | `make image-slice` | tlsolo (not long), plus **the keys play a sample's slices**: the sampling page's knob H is KEYS, CHRO (stock, the keys play pitch) or SLCE. On SLCE a key's note less 60 picks a slice (wrapping both ways) and the slice plays at its own pitch and TUNE; the slices are the scan's transients, the first from frame 0, 16 even ones where the scan has none or is not through yet; STRT and LEN work inside the slice. P and PROF move to knob G. Read "Slices from a sample's transients, and the keys' switch". Both CPUs. Not on the unit. |
| ring | `make image-ring` | slice, plus **LEN on a slice reaches to the sample's end**: the share of what is left from the slice's start, as on a whole sample, so at LEN 127 a slice rings on past the next and turning LEN down shortens it; STRT stays inside the slice. Audio CPU only; `tests/test_ring.py` (6). Not on the unit |
| mixtime | `make image-mixtime` | ring, a tool kept in the chain: **the profile splits the mixer stretch** into our links before stock's mixer, stock's mixer, and our links after it (`make prof-read`). Off until PROF is on, as before; with it off, one more call a block. Main CPU only; `tests/test_mixtime.py` (4). Not on the unit |
| fast | `make image-fast` | mixtime, plus **a block with nothing to change goes straight to stock's mixer**: no solo or solo mark, no mute (global or the pattern's), knob D at XF0 on every sampler track and the analog tracks' crossfades 0. 258 instructions where it was 945; any of those on, the full work as before (one solos' pass a little cheaper). Main CPU only; `tests/test_fast.py` (20). Not on the unit |
| evtime | `make image-evtime` | a tool, not to keep: fast, with the profile cutting the events and knobs stretch in five (`make prof-read`); its record gives up the PC, the stack and the task, and the mixer is not timed. Main CPU only; `tests/test_evtime.py` (6). Not on the unit |
| rxoff | `make image-rxoff` | fast, plus **stock's receive of the host's USB audio not run while the unit sends its own USB audio** (a capture): USB audio in is silence then, back after. About 3 hundredths of a block back with USB audio streaming (measured: the receive is 3.9 streaming, 0.9 not). Main CPU only; `tests/test_rxoff.py` (4). Not on the unit |
| rxcap | `make image-rxcap` | rxoff, plus **the receive off only while the phone has said a capture is on** (0x65, 0x66 off) and the unit sends; cleared when the unit's stream stops. USB audio in works with Ableton and any other host. Main CPU only; `tests/test_rxcap.py` (10). Not on the unit |
| copy | `make image-copy` | rxcap, plus **every mono track's right buffer copied eight longs a move** (movem) before the mixer: 269 instructions a block with eight mono tracks where it was 816. Main CPU only; `tests/test_copy.py` (23). On the unit: still lags |
| nodiv | `make image-nodiv` | copy, plus **the mixer link's crossfade shares without the CPU's divide**, exactly (twelve divides by 127 a block with a crossfade up, about 35 cycles each); the link in a run of its own. The analog mute keeps its eight. Main CPU only; `tests/test_nodiv.py` (64). Not on the unit |
| allright | `make image-allright` | nodiv, plus **the audio CPU sends every track's right half** (a mono track its own buffer), so the main CPU's transfers bring all eight and it copies none: the main CPU's 1 KB a block that tipped the capture's lag. Audio CPU only, +462 instructions there; `tests/test_allright.py` (6). Not on the unit |
| evrx | `make image-evrx` | a tool, not to keep: the evtime tool's profile on the rxoff image (the receive's own lap left out: its call is the gate's) |
| hits | `make image-hits` | lap, plus **hits inside a sample start the filter's envelope again**: on a sampler track the Filter page's DEL is the hits' threshold (0 off, 1 the loudest only, 127 every hit), and each hit it lets through is a trig of the envelope's alone, not the amp's or an LFO's. FENR on: from nothing; off: from where it is. Played backward, a hit fires where its sound comes up out of the quiet. The audio CPU goes over each slot once (128 frames a block) and keeps its hits for the slices to come; the main CPU's envelope is handed the trigs. **SY TOY and SY BITS are gone** (their code is the room): a track on either plays nothing. Read "Hits that start the filter's envelope". Both CPUs. Not on the unit. |
| gear | `make image-gear` | srr (its second build), plus **the sampling page's knobs and SMPL turning as stock's own knobs do**: a turn goes through stock's knob routines (the plain knob's feel; SMPL the sample picker's), where every tick was a whole step. The crossfade's knob is as it was. Main CPU only. Not on the unit. |
| stay | `make image-stay` | gear (its second build), plus **a ONCE that is used up only where the sequencer plays its step**: REC locks to ONCE on the first step too, and a track's own ONCE is not lost to an edit. Also the srr image's old locks of MODE taken off at once. Main CPU only. Not on the unit. |
| scan | `make image-scan` | xcarry, plus **hits found by their attack and ranked**: a window's loudest frame and its loudest step from the frame before, each against its own follower (3.5 dB, 42 dB under the slot's loudest), a hit's step its place among the slot's by how sharp it is, so DEL takes even shares and the slices land on attacks over held sounds and in quiet takes. SD BASIC is gone (its room). Audio CPU only. |
| scratch | `make image-scratch` | scan, plus **every take held on the drive till a save**: once the feed stops, a job writes each take the drive does not have into one of 47 places after the banks (196 to 244 MB), so a power off keeps it; at the next start it is back in its slot, still unsaved. SAVE copies it into the bank, LOAD PROJECT drops it. Read "The scratch image". Main CPU only. Not on the unit. |
| soloend | `make image-soloend` | scratch, plus **a step's solo lock ends with its note**: at the note's release (the trig's LEN, or the key let go) the track's own solo decides again, till its next trig or a new mark. Tracks 1 to 8; an analog track's lock is as it was. Read "The soloend image". Main CPU only. Not on the unit. |
| eucl | `make image-eucl` | soloend, plus **SOLO and REC only on the TRIG page's first page**: its second, the euclidean one, has its own E and F back. Read "The eucl image". Main CPU only. Not on the unit. |
| norm | `make image-norm` | eucl, plus **every take normalized to -1 dB once it ends**: scaled up (at most 30 dB, never down) in the background, 256 frames a block; the drive, Transfer and the phone get it as it stays. Always on. Read "The norm image". Audio CPU only. Not on the unit. |
| atrig | `make image-atrig` | norm, plus **on the analog tracks SOLO on the TRIG page in LFO.T's place** (F stays NOT2; a held step locks it) **and LFO.T on FLTR2's G**, as on a sampler track; the second SYN page keeps the crossfade alone. Read "The atrig image". Main CPU only. Not on the unit. |
| trans | `make image-trans` | spread, plus **DEL on a sampler track's FLTR2 drawn as a knob named TRANS** (TRANSIENT in its pop-up), not stock's delay picture. Main CPU only. Not on the unit. |
| next | `make image-next` | trans, plus **DEST SMPL or NEXT, and knob C of the sampling page the track's KIND, STER or MONO** (REC is the TRIG page's): on NEXT a take goes to the next free place of its kind and the track's SMPL follows it. Main CPU only. Not on the unit. |
| pbank | `make image-pbank` | next, plus **BANK in the PROJECT menu**: a fourth entry under MANAGE PROJECTS, SAMPLE BANK and the loaded bank (A>B with another chosen), the next bank each time it is chosen; the bank still loads only with a project, as before. Knob D of the sampling page is empty. Main CPU only; `engine/pbank.c`, `tests/test_pbank.py` (9). Not on the unit |
| kind | `make image-kind` | pbank, plus **SMPL stopping only at samples of the track's KIND**: STER the stereo samples and the next free stereo place, MONO the mono ones and the next free single slot. Main CPU only. Not on the unit. |
| mirror | `make image-mirror` | kind, plus **the screen sent to a viewer over USB** as SysEx, up to 15 frames a second, only while a viewer asks: for video. Main CPU only. Its second build (`2bbc45b9...`) sends the panel's frame (`0x402d7114`); the first sent the next frame's buffer, dotted dials on the unit. |
| trap | `make image-trap` | mirror, plus **a stretched note for less**: the two heads overlap over 128 frames, one alone the rest, and the place moves a block at once with no loop wall in it. Eight stretched voices about 10,000 fewer instructions at the peak. **CY ALLOY plays nothing** (its code is the room). Audio CPU only. Not on the unit. |
| shadow | `make image-shadow` | trap, plus **the viewer's frame copied from what reaches the panel**, column by column, in place of the panel's buffer: for the strokes the mirror image's frames had at the dials. Main CPU only. Not on the unit. |
| sink | `make image-sink` | shadow, plus **the viewer's frames whole**: no write into the unit's SysEx sink crosses one of its 144-byte sends, where stock's put copied the rest of a write from its start again (the strokes at the dials). Main CPU only. On the phone, not on the unit. |
| tune | `make image-tune` | sink, plus **a pushed turn of every machine's TUNE by 1**, analog too, as an unpushed turn moves (stock: 4, 8 or 12 times as far), as on the Digitakt. Main CPU only. On the phone, not on the unit. |
| letgo | `make image-letgo` | tune, plus **a stereo note that is over letting go of its right channel** once both sides are under -120 dB of full scale: stock's four stages no longer run on its silence (about 2,700 instructions a block a silent stereo track, 16,000 more once none sounds), and **the normalizer by what each take was**: a mono take beside one being scaled no longer stops it part done, a take cut short by the next on its track is scaled, a single slot's neighbour (and slot 0's first two frames) left alone. Audio CPU only. On the phone, not on the unit. |
| ask | `make image-ask` | letgo, plus **LOAD PROJECT asking the phone only once the phone app has said hello** (0x63, or a capture's 0x65 or 0x66) since the start: Transfer, slink or the screen viewer no longer make every load wait 2 s for a phone that is not there. Main CPU only. Inside axf. |
| axf | `make image-axf` | ask, plus **the analog tracks' second SYN page drawn clean**: G the crossfade alone, the peak (P) in H. Since the slice image the two were drawn over each other in G. Main CPU only. Inside gainup. |
| gainup | `make image-gainup` | axf, plus **the sampling page's places moved**: the record gain in D (top right, empty since pbank), the peak and its PROF switch in E, STRC in G, F empty. Main CPU only. Inside onedest. |
| onedest | `make image-onedest` | gainup, plus **DEST only SMPL**: NEXT is gone, every take goes to the track's SMPL place (KIND, C, still says stereo or mono, and SMPL's stops by it pick the place). B reads DEST SMPL; a turn of it only clears a NEXT left from before. Main CPU only. Inside destnum, not on the unit. |
| destnum | `make image-destnum` | onedest, plus **DEST's numbers back**: B is SMPL or a place's number, its stops SMPL's by the track's KIND (STER the stereo samples and the lowest free place, MONO the highest free single slot and the mono samples); a KIND turned puts a DEST of the other kind back to SMPL. Main CPU only. Inside fresh, not on the unit. |
| fresh | `make image-fresh` | destnum, plus **a new project asks the phone**: LOAD PROJECT of an empty slot makes and saves a project without stock's load, so the phone was never asked; now, after the save, it is asked as a load asks, marked new, and the phone empties A, keeping every sample it had. Main CPU only. On the unit: asks at an empty slot's load; NEW PROJECT does not ask. |
| newproj | `make image-newproj` | fresh, plus **NEW PROJECT asks the phone**: stock's Project Init job makes a project of no number and neither saves nor loads; now it asks as a load does (project 0x3fff, marked new), and every ask says the project it leaves, so the phone files A under the right project and empties A for a new one. Main CPU only. On the unit: asks at NEW PROJECT; the phone's clear left it stuck. |
| wipe | `make image-wipe` | newproj, plus **the unit empties the slots the phone names**: the phone's writes and clears go unanswered while a load waits, so the phone answers 0x6A with the slots to empty, and the unit writes their headers with zeros itself, in its job, and loads them empty. Main CPU only. On the unit: NEW PROJECT empty; LOAD PROJECT keeps what A holds. |
| stream | `make image-stream` | wipe, plus **LOAD PROJECT brings the project's own samples back**: the unit empties every wrong slot at the load, says when the load is done (0x6C), and loads each slot the phone names as it writes it (0x6B), a job a burst; a slot holding a take not saved keeps it. Main CPU only. On the phone, not on the unit. |
| evict | `make image-evict` | stream, plus **a slot the phone sends is loaded over a take not saved** (0x6B, a Send, a restore or a load's stream), and its held copy is dropped from the scratch table, so a SAVE or a start cannot bring the take back. Main CPU only. On the phone, not on the unit. |
| handrec | `make image-handrec` | evict, plus **with the sequencer stopped, a track whose REC is at ONCE records a note played by hand for the TRIG page's LEN**, and REC reads OFF after (a pressed key's release no longer ends it). Both CPUs. On the unit, works. (Level 80, playrec, PLAY recording a ONCE on the first step on the first pass: dropped after three builds.) |
| firstrec | `make image-firstrec` | handrec, plus **PLAY records a ONCE on the first step on the first pass, and only then**: a start spends the ONCE of the step it queues, and the next pass's play of it has the spent lock taken off. Main CPU only. On the unit: "seems like it works ok" (once "Still lap 2"). Kept. |

The sound engine is identical in the first ten (the keep, double, screen, page, load and bank images play a loaded sample 6 dB louder); the fade image's and the mute image's fades where a sample is cut into: read "Fades". **The reclock image's first build is the one on the maintainer's unit (2026-10-10) and everything in it works there**; it has LEN's floor at 6, and the files here have it at 3 as he then asked. The live image ran there before it. The mute image's main program runs on the unit inside it and its checks passed: read "Mute". The len and live images' engines also follow LEN, and STRT, while a note plays: read "STRT and LEN while a note plays". For the next two read "LEN's floor" and "A step's REC", and for the last, which is not flashed, "Pitch". The recorder is in the last thirteen. The bank image runs on the maintainer's unit and the banks work there: read "Sample banks". The load image's loader works on the unit: read "Loading a project". The page image's last build runs on the maintainer's unit inside the load image: REC and SRC are bits of MODE, they move, recording works, and a held trig locks REC to its step. Read "The sampling page". The screen image ran there before it: read "Names and words on screen". The double and keep images ran there before it: read "Twice the samples" and "Keeping takes". The big image changes how the +Drive is laid out: read "Larger slots" before flashing it. It ran on the maintainer's unit on 2026-10-07.

## Knobs

| Slot | Knob | Range | Default | Audio-only image shows |
|---|---|---|---|---|
| 18 | TUNE | 40..88, 64 = original pitch | 64 | TUN1 |
| 19 | SMPL (sample) | right half of the knob plays forward, left half **reversed**. Mono: 64 slots. Stereo and record: 32 stereo samples, see Stereo | first, forward | SMP1 |
| 20 | STRT (start) | 0..127, fraction of the whole sample | 0 | FLT1, default 64: set it to 0 |
| 21 | LEN (length) | 0..127, fraction of what is left after the start; 127 = to the end | 127 | MIX, default 64: set it to 127 |
| 22 | LOOP | 0 off, 1 loop, 2 ping-pong | 0 | TUN2: 0 is off, +1 loop, +2 ping-pong |
| 23 | MODE | 0..5, see below | 0 | SMP2, default 65, which is stereo: set it to 0 (shown as -64) |
| 25 | DEC (decay) | 127 = hold | 127 | DEC1 |
| 26 | OVER | overdrive, applied after the machine | 0 | OVER |

All knobs except TUNE and DECAY are read when the note starts. Turning START mid-note changes the next note, not this one. **On the live image STRT and LEN are read all the time**: read "STRT and LEN while a note plays".

Two knobs say how a sample plays, one thing each.

LOOP is how it runs through the region that STRT and LEN set:

| LOOP | Meaning |
|---|---|
| 0 | off: play the region once |
| 1 | loop: at the end of the region, start it again |
| 2 | ping-pong: bounce between the two ends of the region |

MODE is what the track does:

| MODE | Meaning |
|---|---|
| 0 | mono: play the slot |
| 1 | **stereo**: SMPL picks a stereo sample (two slots, left and right); the right channel goes to the next track. On the stereo image it stays on this track: read "Stereo on one track" |
| 2 | record the main mix (recorder image only, see Recording) |
| 3 | record the external input (recorder image only) |
| 4 | mono, **chained**: consecutive non-empty slots play as one long sample |
| 5 | stereo, chained |

On an image without the recorder 2 and 3 play like 0.

**On the mode image MODE is none of this**: a sample plays as what it is, and MODE says what a take is. Read "A sample is mono or stereo by itself". **On the pack image SMPL's 33 to 64 are single slots, each a mono sample**: read "Mono samples at the back". **On the stops image the knob skips every number that is no sample**: read "SMPL stops only on samples".

There is no loop point any more: a loop is the whole region. Until 2026-10-07 LOOP was a loop point (0..127) and MODE held everything else as a sum (1 loop, 2 ping-pong, +4 stereo, +8 chain, 16 and 17 record). **Sounds and patterns saved under an older image keep the old numbers and read wrong now** (the old stereo, 4, is chained mono today): set MODE and LOOP again on those tracks.

Gated playback needs no mode: the track's AMP envelope already follows the note length.

## Stereo

A stereo sample is two slots next to each other: left in an odd slot, right in the even one after it. Put the machine on track N and set MODE to 1.

**In stereo SMPL counts stereo samples, not slots.** One click is the next stereo sample, and no value of the knob lands on a right channel:

| SMPL reads | Transfer slots |
|---|---|
| 1 | 1 (left) and 2 (right) |
| 2 | 3 and 4 |
| n | 2n-1 and 2n |
| 32 | 63 and 64 |

Past 32 there is no stereo sample and the track is silent. The reversed half of the knob counts the same way. In mono (MODE 0) SMPL counts single slots, 1 to 64, as before, so a stereo sample's two halves are mono slots 2n-1 and 2n. Record (MODE 2 and 3) counts like stereo, so a take lands where MODE 1 plays it with the knob left alone. So a stereo sample has to start on an odd slot: `make samples` sees to that, leaving a slot empty after a mono sample where it has to.

The screen shows a sample's name next to SMPL, and up to the double image it does not follow MODE: in stereo it shows the name of the single slot with the stereo sample's number, which is some other sample or NO SAMPLE. The screen image shows the stereo sample's own name: read "Names and words on screen".

- Track N is the instrument. Sequence it, lock it, modulate it.
- Track N+1 becomes the right channel while MODE says stereo. Its own machine, trigs and settings are ignored and it is silent whenever track N is. The audio CPU makes its overdrive, filter and amp envelope copy track N's every block, trigs and note-offs included.
- Pan, volume, delay send and reverb send live on the main CPU. With the **full** image the mixer takes them from track N for both tracks and pans the pair hard left and right itself, p-locks and LFOs included; track N+1's own values are ignored and left as they were. With the **audio-only** image, set them by hand on track N+1: pan hard right (track N hard left), same volume, same sends.
- On track 8 there is no next track: stereo mode plays the left slot only.
- Mute (full image): muting track N silences both sides. Track N+1's own mute is ignored while the pair is linked.

### Stereo on one track (stereo image only)

Built 2026-10-10. **On the unit in its first build, 2026-10-11: "it works fine when they are all pitched normlly but when i pitch them it causes major distortion".** The second build (`99e56954...`, the same day) is the answer to that, and **on the unit it works**: eight pitched stereo tracks, left and right apart on every track (his marks; "seems like it works"). Read "What it costs". The the maintainer's report. On the stereo image a stereo sample plays on the one track its machine is on, so eight tracks can hold eight stereo samples. `docs/STEREO.md`, "One-track stereo", has how.

- MODE on STEREO and the sample is stereo on that track. SMPL counts stereo samples as before.
- **PAN is balance.** In the middle the left channel is on the left and the right on the right, each at the level a mono track has in the middle. Hard left is the left channel alone, hard right the right alone.
- VOL, the delay send and the reverb send are the track's own and act on both channels; the sends are stereo. OVER, the filter and the amp envelope act on both channels alike.
- **The next track is its own again**: its machine, its trigs, its pan. A project made for two-track stereo has a track after each stereo one that was silent whatever was on it. Here it sounds: clear it or use it.
- Track 8 can be stereo.
- Mute and solo act on the one track.
- A stereo sample whose right slot is shorter than its left, and a note that started with MODE on MONO, have no right channel: they play the same on both sides.
- Turn MODE to MONO while a stereo note plays and it is its left channel on both sides at once; back to STEREO and the right channel is back.
- A track's own output (the USB track outs, and T1 to T8 as a source on the sampling page) is a stereo track's left channel. MAIN has both.
- What it costs, as the unit's own meter has it (the time image, 2026-10-11, the second build): eight stereo samples at their own pitch take 72 hundredths of a block, the same pitched 99 and at times over 100, where the unit's heaviest machine on all eight tracks takes about 88. So pitched stereo on all eight was at the edge. The third build takes about 7 off both without changing a frame, by the bench's count; a sum of twelve frames in place of sixteen would take about 5 more off a pitched note and is a little less clean (the time12 image, to hear). Read "What it costs".
- If every stereo sample plays as one channel on both sides, the two stretches of shared memory the right channels cross in are not memory: nothing else is wrong, and say so.

### The right channels by a hardware transfer (dma image)

Nothing to hear and nothing to set: a stereo sample sounds as it did. What changes is who carries its right channel from the sound engine to the mixer. Up to the gfade image the main CPU read it itself, 64 slow reads a track a block, in the interrupt that everything on the screen waits for; with stereo samples playing the screen and knobs lagged. Here the unit's transfer controller carries it, as it carries the left channels for stock, while the CPU does the block's other work.

- No transfer can be run in emulation, so the image proves its own on the unit. For a second after every start the CPU reads the right channels too and the two are compared: **C** before the load in the sampling page's last box. If they agree the transfers are used: **H**. If they differ, or one does not end: **X**, and the CPU reads as before until the next start.
- H is what it should read a second after the unit is up. X is no harm: the unit is the gfade image then, lag and all. Tell which it reads.
- Not shown: any of it. `docs/FINDINGS.md`, "The right channels by a hardware transfer".

### A sample is mono or stereo by itself (mode image)

Built 2026-10-12. **On the unit the same day, inside the cross image: stereo and mono samples play as what they are, and a mono take is still mono after SAVE and a power cycle (his marks).** The maintainer's idea, from his list: "instead of changing the playback of the track in real time, just set the recording to either mono or stereo and just have it automatically manage whether a channel or a sample is mono or stereo. If I recorded a mono sample, it just becomes a mono sample, and if I recorded a stereo sample, it just is a stereo sample."

- **SMPL always counts the 32 samples**, as it did in stereo: number n is Transfer's slots 2n-1 and 2n. There is no MONO or STEREO to set on a track.
- **A sample is stereo when its second slot holds exactly as many frames as its first.** Anything else in the second slot (nothing, or something of another length) and it is a mono sample: the first slot, on both sides, at a mono track's cost, and PAN is its pan.
- **MODE is on the sampling page and says what a take is**: MONO or STER, knob G, the lower row's third box. It is the track's: it cannot be locked to a step. A new track's is STER, as every take was.
- **A stereo take** fills both slots, as before. **A mono take** is the two sides of its source added and halved, in the first slot; the second is left holding one frame, and that is written to the drive with the take, so that what was in that slot cannot come back as a right channel. Transfer shows it as a second take of no length.
- A track as source (T1 to T12) is one channel either way.
- What it gives up: a single slot can no longer be played by its own number. A sample is one of 32, and a mono one leaves its second slot unused. To load a mono sample, send it to an odd slot of Transfer and leave the next one empty, which `make samples` already does.
- **A project made before this**: a track that was on STEREO plays as it did. A track that was on MONO now reads its SMPL number as a sample and not as a slot (SMPL 3 was slot 3, and is slots 5 and 6 now), and its takes are mono. Set SMPL again on those.
- The name next to SMPL is the first slot's, without its side, for either kind.

How it works: the audio CPU always took a stereo sample's right channel from the slot after its left, and only when that slot was as long. Here it does so for every sample and asks for exactly as long (`engine/sampler.c`, built with AUTO), and what MODE's lowest bit says is read where a take starts and by the feed (`engine/recfeed.c`). The code that walked from one slot to the next for chained samples, which the page image had left without a use, is gone, and that is the room the next image's crossfade is in.

### Mono samples at the back (pack image)

Built 2026-10-12, not on the unit. On request.

| SMPL reads | Plays | Transfer slots |
|---|---|---|
| 1 to 32 | a stereo sample, as on the mode image (or a mono one whose second slot is not as long) | 2n-1 and 2n |
| 33 to 64 | **the one slot of that number, mono**, whatever the slot after it holds | n |

- **Stereo samples go in from 1 up, mono ones from 64 down, and they meet where they meet.** 32 stereo and no mono; 28 and 8; 24 and 16; 20 and 24; 16 and 32. There is no amount to set.
- **The knob's number says which kind a place is.** Nothing is found out from what the slots hold: two mono takes of a bar, side by side, are as long as each other, and each still plays alone at its own number.
- A number never moves. Recording, loading or losing a sample somewhere else changes no other place.
- **A take lands where SMPL (or DEST) points.** At 33 to 64 it is a mono take in that one slot, whatever MODE says, and the slots either side are not touched. At 1 to 32 it is what MODE says, as on the mode image. So for a mono take: SMPL to a free number from 64 down (the name next to it reads NO SAMPLE on an empty one), REC on, trig, REC off, play.
- DEST on the sampling page goes to 64.
- The name next to SMPL at 33 to 64 is the slot's own, whole. A kept mono take is named after the pair its slot belongs to (slot 64 reads `TAKE 32 R`).
- **What it does not do.** No more than 32 mono samples by their own numbers: slots 1 to 32 are stereo places only (a lone sample in an odd slot there still plays as mono, wasting the next one). And the unit does not find a free place: you turn SMPL to one.
- **Where the two kinds meet, the knob has numbers that mean little.** With 20 stereo samples (slots 1 to 40), SMPL 33 to 40 are single halves of those. With mono samples in slots 41 to 64, SMPL 21 to 32 are two of those at a time. Nothing breaks; they are not what you want to play.
- **Do not record over the other kind by mistake**: a mono take at SMPL 40 is slot 40, which is the right half of stereo sample 20 if there is one. The unit does not check.
- `make samples PACK=1` lays a set of files out this way: read "Preparing samples".

How it works: SMPL always had 64 values each way, and the 32 stereo samples used half. A note's start takes a value past 32 as a slot and marks the note as having no right channel to look for. A take in such a place is half of the two sides added, written to its slot's buffer alone. The routine that makes a take is written by hand on this image: the compiler's did not fit its run by 60 bytes (`engine/stub.S`, `rec_step`; `docs/FINDINGS.md`, "Mono samples in single slots at the back").

### SMPL stops only on samples (stops image)

Built 2026-10-12, not on the unit. On request.

Turning SMPL on the first page, to the right from the middle, goes through:

1. every stereo sample, in order;
2. **the first stereo place that is free**;
3. **the last single slot that is free**;
4. every mono sample, in slot order up to 64.

And nothing else. The left half of the knob, which plays reversed, is the same list the other way.

- **The free spot is where the next take of that kind goes.** A stereo take: one click past your last stereo sample, REC on, trig. A mono take: one click further, on the free slot before your mono samples. When it is recorded the spot is a sample, and the next free one appears beside it. A step that records every bar goes over the same spot: nothing is eaten.
- A click is a stop. Turn fast and it is as many stops as clicks. **Pushed in while turned it is eight stops a click**, as stock's knob is eight numbers.
- **FUNC and a turn is left to stock.** By its code, read and not tried here, that takes a sample to the same number on the other half of the knob: forward to reversed, or back. (The key stock asks about is its key 1; that it is FUNC is not proven.)
- A number keeps its meaning. A pattern or a lock on a number the knob no longer stops at still plays that number; turn the knob and it goes to the nearest stop that way. An LFO on SMPL still sweeps every number. DEST still reaches all 64.
- Hold a trig and turn SMPL to lock it, as before: the first click makes the lock where the track is, the next ones move it by stops.
- With a hole in either stack (a sample deleted, a place skipped) the free spot is the hole: the first free stereo place from 1 up, the last free slot from 64 down.

**What a slot holds is told by its length, and that is the one thing to know.**

| A slot's length | It is |
|---|---|
| nothing | empty |
| an odd number of frames | a mono sample of that single slot (33 to 64) |
| an even number of frames | its stereo place's: one side of a stereo sample, or a mono sample in a stereo place |

- A take is made the right kind by itself: a single slot's take is one frame short of its blocks, and a mono take in a stereo place leaves two frames in its second slot (the mode image left one: such a take from before still reads right).
- **Files have to be made the right kind: `make samples PACK=1`** leaves the last frame out of a mono file that is even and of a stereo one that is odd. Read "Preparing samples".
- **Samples already on the drive.** A stereo sample in slots 33 to 64 whose two files are an odd number of frames shows as two mono samples, and a mono file of an even number of frames at the back does not show, or shows as a stereo place. Send those again from `make samples PACK=1`. Slots 1 to 32 are stereo places only, whatever their lengths. Takes of every image before are whole blocks, so even, and read right.
- Stereo places 17 to 32 and single slots 33 to 64 are the same slots. An odd first slot there is a mono sample; an even one is its stereo place's, and the slot after it is then no free single slot.

Until the sound engine has said what the slots hold (four blocks after it starts, 3 ms), and while it is down, the knob is stock's and stops everywhere. If SMPL ever stops on every number, that is what it is saying.

How it works: the audio CPU writes two bits a slot into the window shared with the main CPU, sixteen slots a block, and the page reads them when the knob is turned and works the stops out (`engine/stub.S`, `stops_say`; `engine/recpage.c`, `stops`). `docs/FINDINGS.md`, "SMPL stops only on real samples".

### How hard the audio CPU is working (time image only)

On request. On the time image the sampling page's lower row has two numbers after SAVE:

- **C**, the most of a block's time the audio CPU spent on one block in the last sixth of a second, in hundredths. C062 is 62 in 100.
- **P**, the most C has been in the last 5 to 11 seconds: play a pattern, then look.
- **100 is everything.** At 100 a block's work has taken the whole block and the next one starts late, which is where the sound should break up. How near 100 is still safe is one of the things this is for.
- C000 that never moves: the unit's timer does not count, and the image has nothing to say. Tell me.
- For a few seconds after the unit starts P may read 999. It is what was in memory, and it goes.

**On the mode and cross images P alone is kept, in the sampling page's last box**. It reads as here. It is there while the images are being built and comes out when he says.

**Pitch is what P mostly is** (the maintainer, 2026-10-14: 85 with nothing pitched, 100 pitched). A note at its own pitch or octaves up plays the sample's frames as they are; any other pitch sums twelve frames for each one played, about 22 of P with eight stereo tracks. The trim image takes about 5 of that back, and about 7 off the heaviest block (`docs/FINDINGS.md`, "Pitched notes and loops for less").

It measures every machine, not only the sampler: eight SY SWARMs is what Elektron's own heaviest patch costs, and worth reading first as the mark to hold the rest against. Everything else on the image is the stereo image. `docs/FINDINGS.md`, "The audio CPU's two timers".

### Checking stereo on the unit

On request. `make stereo-sample` writes eight stereo check samples, one for each track, as 16 files for Transfer (`build/samples/stereo_check/`, slots 49 to 64, so SMPL 25 to 32; `FIRST=1` for slots 1 to 16) and a sheet, `HOW_TO_CHECK.txt`, with the steps. Made by `tools/stereo_check.py`, nothing of Elektron's in them. Each is 4 seconds: a low tone on the left only and a high tone on the right only for two seconds, sixteen different tones over the eight, then one burst of hiss that is the same on both sides, each sample's at its own moment.

By ear, a track alone, MODE on STEREO, PAN in the middle, on headphones: the low tone in the left ear and the high one in the right, then a blip of hiss dead centre. PAN hard left is the low tone alone, hard right the high one alone. A steady tone is where a click or grit is plainest. The low tone on both sides and the high one nowhere means that track's right channel is not reaching the main CPU.

Measured: record the unit playing them and hand the recording back. A track that records does not play, so seven play while the eighth records the main mix (the sampling page: SRC on MAIN, DEST on a spare stereo sample, REC on, a trig that lasts the 4 seconds, REC off, SAVE), the take's two files come off with Transfer into `samples/check/`, and `make stereo-check` reads them; then the same with another track recording. A stereo recording of the unit's USB audio holds all eight at once. From the recording alone it says, for every sample it hears: whether its left tone is on the left and its right tone on the right, and how far under each the other side's is; whether its hiss lines up on the two sides to the frame (a right channel a block out of step is 32 frames off, which no tone shows). And for each side: how far under the tones their harmonics are, what else is there, and its largest jump (a block read while it was being written is a click the size of a tone). It goes by the recording's own pitch, all eight moved together. `tests/test_stereo_check.py` gives it recordings with each of those wrong, on one track among eight, and the built image's own voice playing a sample.

What it cannot say is how many stereo tracks the unit carries: that is the crackle, and the ear.

## Mute

Stock mute only stops new trigs: a sound that is already playing rings out. With the **full** image, muting a track also fades its audio out in the mixer within one block (0.7 ms), dry signal and sends, and unmuting fades it back in. Delay and reverb tails ring out. It follows global mutes, pattern mutes and solo, the same rule the trig code uses. Trigs still do not fire on a muted track.

- Digital tracks (1..8): on the maintainer's unit the global mute key cuts the audio (2026-10-06). A voice keeps running while muted, so a loop comes back where it would have been.
- Analog tracks (9..12): works on the maintainer's unit, with no click (2026-10-07). The dry sound of an analog voice does not pass the mixer (a first build that only acted there failed). It goes to the outputs through a left and a right level circuit that the main CPU steers, with values it works out from the track's volume and pan every block. The mute sets those two values to 0 for a muted track, which is what the track's own volume at 0 gives, and also shows the mixer 0 so the sends go too. The voice keeps sounding underneath.
- The FX track is left alone.

**Mute image: a mute that only silences. On the maintainer's unit since 2026-10-10 (inside the live image), and its eight checks passed there.** On every image before it a muted track's trigs do not fire, so a track comes back empty until its next trig. On the mute image they fire:
- A muted track plays on, unheard: notes start, locks are applied, a loop runs. Take the mute off and the sound is there, wherever it would have been.
- **A take is made on a muted track.** REC on, or locked to a step, records as it does unmuted. So a track can be recorded to with the mute on, and the old take in it is not heard meanwhile.
- The same for solo (every other track is muted by it) and for the pattern's own mutes.
- A muted track still cuts the tracks its trigs are set to cut, and its trig key lights as a playing track's does.
- A MIDI track's mute is stock's: its notes stop. There is no audio of its to mute.
- The FX track's mute is stock's.
- How: stock drops a muted track's events in one place in the routine that runs every block. On this image that test is only made for a MIDI track (`engine/mutetrig.c`).

Both channels come from one position counter, so they cannot drift.

### The pattern's mutes as solos (solo image)

The maintainer's wish (2026-10-12). Built, not on the unit. The purple mutes, the ones a pattern keeps, are solos on this image:
- A purple key adds or removes one track's solo. **While any of the twelve is on, the tracks that are not are silenced**, as a mute silences them here: faded out in the mixer within a block, the analog tracks by their level words, trigs still firing, a take still made. With none on, everything is heard.
- Several at once: each key is its own.
- **A green mute still mutes.** A track that is green-muted and purple-soloed is silent.
- A MIDI track's notes stop while another track is soloed, as they stop under a mute.
- **The keys: purple for a track that is heard, dark for one a solo silences.** All twelve lit with no solo, the soloed ones alone with one.
- The FX key is what it was: it mutes the FX track's trigs, is no solo and is never silenced by one. A silenced track's sends go with it, as under a mute; delay and reverb tails ring out.
- A song row's mutes are solos the same way, and its keys too.
- Saved with the pattern as the mutes were: it is the same word. **A pattern from before that holds purple mutes plays the other way round**, its muted tracks the only ones heard.
- The pop-up still reads as stock's. What the screen draws of the tracks goes by the solo for a pattern; for a song row it is stock's, so there the screen and the keys can differ. Not seen.
- How: the pattern's own word is not touched. The four places that hand a copy of it to the two engines hand over the tracks its solos silence (`engine/solo.S`, 94 bytes, main CPU), so everything that reads a copy, stock's or ours, is as it was. `docs/FINDINGS.md`, "The pattern's mutes as solos".
- Not known before the unit: that a key press reaches the sound at once, and on a pattern change, a project's load and in song mode; what the keys and the screen show; MIDI (a soloed track still goes out as a pattern mute); clicks when eleven tracks fade in one block.

### A solo on the sampling page (soloknob image)

The maintainer's choice (2026-10-12), after the solo image ran on on the unit Built, not on the unit.
- **The purple keys are pattern mutes again, stock's.** What was a purple solo in a pattern is that track's pattern mute.
- **From the trig image on, SOLO is knob E of a sampler track's TRIG page (LFO.T's place) and REC is also knob F there (FLT.T's); the sampling page's E is empty.** Up to it:
- **Knob E on a sampler track's sampling page: right is SOLO, left is S OFF.** Each sampler track has its own; several can be on.
- **While any is on, every track with no solo is silenced**, all twelve, the analog four among them, the way a mute silences here: trigs fire, and a take is made on a silenced track. **A soloed track is heard whether it is green-muted or purple-muted.** With all solos off the mutes are what they were.
- The FX track is left alone. A MIDI track has no sound to silence and its notes go on.
- **Off at power on, and not saved** with a pattern or a project. Only a sampler track can be soloed; a track changed to another machine loses its solo.
- How: a bit a track in one long of main CPU memory, which the mixer link and the analog mute read in the place of stock's own solo word (`engine/mixlink.c`, `engine/amute.c`, `engine/recpage.c`). Stock has a solo word of its own with a setter nothing reaches; why it is not used: `docs/FINDINGS.md`, "A solo on the sampling page".

### The solo and the crossfade on the analog tracks (apage image)

SYN pressed again on an analog track (9 to 12) opens a second page, as on a sampler. Two things are on it, where they are on a sampler's: knob E reads SOLO or S OFF, knob G the crossfade, XF0 to XF127. The other six places are empty and their knobs turn nothing; LEVEL is LEVEL.
- The solo is the same solo: with any track's on, every track with none is silent, and an analog track's own can be on.
- The crossfade is the unit's one: an analog track that turns it holds it, and every other track goes down, the other analog voices too.
- Off and 0 at every start, not saved. **Not lockable**: a lock on an analog track has no place found for it yet.

### A step's solo (slock image)

On a sampler track: hold a trig, open the sampling page, turn knob E. To the right the step is locked to SOLO, to the left to S OFF; the place reads the held step's. A step is only locked where it differs from the track: turned to what the track's own solo says, its lock is taken off.
- A step locked to SOLO solos its track from when it plays until the track's next trig, as any lock lasts. The track's own solo is not changed by it.
- On a track whose solo is on, a step locked to S OFF takes the track out of the solos for as long.
- Saved with the pattern, as a lock is. The track's own solo is still off at every start.
- Not on the analog tracks: knob E there is the track's alone, a held step or not.
- **From the alock image on, on the analog tracks too**, the same way, on a track that holds an analog machine. Not proven: if an analog voice sounds different on a step whose solo is locked, that is this, say so.

## Recording (recorder image only)

Resampling into a slot, in memory. **A take is lost at power off** unless the image is the keep one and a project is saved (Keeping takes, below).

1. Put the sampler on a spare digital track. Set MODE to 2 (main mix) or 3 (external input).
2. SMPL picks the stereo sample it goes into, counted as in stereo: number n is slots 2n-1 (left) and 2n (right).
3. Give the track a trig. The take runs for as long as the note does, so the trig's LEN on the TRIG page is the length of the take: 16 steps is one bar. With LEN at INF it runs to the limit, 10.24 seconds.
4. Turn MODE to 1 on that track or any other, same SMPL: the take plays as a stereo pair. LOOP at 1 loops it; LOOP is left alone by recording, so it can be set beforehand.

What to know:
- A recording track makes no sound, so it never ends up in its own take. It is not a stereo pair: the next track stays its own.
- A take replaces what the slot plays until the next power cycle. The +Drive sample is untouched and comes back at boot.
- A new trig starts the take again from the beginning. Turning MODE away from 2 and 3 ends it.
- SMPL past 32 names no stereo sample: nothing is recorded there.
- If two tracks say record, the lower numbered one picks the source for both. **From the multi image on, each records its own:** every sampler track with REC on takes its own SRC into its own DEST, up to all eight at once. A take then begins a block later than before (the block written while its note started), and still before the sound of a trig on the same step. What it costs the main CPU, and what only the unit can show: `docs/FINDINGS.md`, "Several tracks recording at once".
- Takes are whole blocks of 32 frames (0.67 ms). A take is as long as its note to within one block.
- The main mix is taken where the unit builds its own main pair for USB audio; the external input is the raw input, before the EXTERNAL MIXER levels.
- A pressed trig key ends its note when it is let go, whatever the trig LEN says: hold the key for as long as the take should run, and again to listen. A trig placed in the sequencer follows its LEN.
- Level: a take plays 6 dB louder than a loaded sample would, at full scale where a sample plays at half (keep image: both at full scale). For the level of the original mix, turn the playback track's LEVEL and AMP VOL all the way up and leave OVER at 0: those two knobs only ever turn down. OVER adds level by clipping, so it is not the way to make a take louder.
- Quality: 48 kHz in and out, nothing resampled. Each 32-bit sample is rounded to 16 bits with triangular dither of one step, so what is lost comes out as a steady hiss about 96 dB down and not as distortion of quiet sounds. Played at the original pitch a take is the stored samples exactly.

How it works: after every mixer call the main CPU puts 32 stereo frames, reduced to 16 bits, into a ring of 8 blocks in the half of the shared window that is otherwise used only while booting, then counts a counter up. It does nothing until the audio CPU has finished booting, because the boot loader uses that same half of the window to load the sample pool. The audio CPU takes every block it has not seen, in order, into a fixed buffer per slot in free SDRAM, and points the slot table at it. The sampler then plays it like any other slot.

On the feed image the routine that writes a block is hand-written (`engine/feed.S`): there is no call a sample, a gain's limit is worked out once a block and not once a sample (64 hardware divides a block before), and what a take is, stereo or mono, with a gain or without, is chosen before the loop. A sample and its dither are added in 32 bits and held there (`sats`, as stock's mixer holds its own sums), which gives the 16 bits the older routine gave by holding them after. What a take holds, the dither's numbers and the meter are the ptn image's to the bit (`tests/test_feed.py`, both images run side by side). A block of a take adds 1,126 to 1,515 instructions to the main CPU's per-block interrupt where it added 3,993 to 5,017. Why: that interrupt runs above the tasks the screen and the keys are served in, and with REC on the maintainer's unit dragged there. **The main CPU's load is not measured: whether this is the cure is his to say.**

## Keeping takes (keep image only)

**Works on the maintainer's unit (2026-10-08, `docs/FINDINGS.md`, hardware log).** Saving a project also writes every take that is not on the +Drive yet into its two sample slots. From then on it is a sample like any other: there after a power cycle, and Transfer reads it.

- The move is the unit's own SAVE PROJECT, either way into it. Nothing else writes a take: not recording, not saving a pattern or a sound, not switching off. **From the ptn image on a whole pattern saved to the project writes them too**: read "Saving the takes with a pattern".
- A take on stereo sample n goes to slots 2n-1 and 2n and **replaces what the drive had there, for good**. A take that should not be kept: record over it, or restart before saving a project. Recording over it leaves the new take there, not the sample that was loaded before; only a restart brings that back.
- Each take is written once. Saving again writes only the takes made since.
- The slots are named `TAKE nn L` and `TAKE nn R`, nn the stereo sample.
- Sample slots are not part of a project: a kept take is there in every project.
- Loading a project does not bring a kept take back. Record over it after the save and the new take plays until a restart, whichever project is loaded; the restart brings back what the drive has. Save the project again before that and the new take replaces the kept one on the drive (seen on the unit, 2026-10-09, the first half).
- It takes time after the unit's own save. A 10 s stereo take is 3,842 sectors: about 2.5 s to fetch, plus the drive's writing. Not measured on the unit. The unit plays on meanwhile.
- **In this image a loaded sample plays at a take's level**, 6 dB over the other four images, so a kept take sounds the same before and after a power cycle. Projects made on another image will find their samplers 6 dB louder.
- Sending any sample from the computer may restart the audio CPU (not traced). If it does, takes that were not kept are gone. Save the project first.

How it works: the take is in the audio CPU's memory and the drive is the main CPU's. The two calls to the routine that saves a project (the jobs behind the project screens) go to ours, which calls the stock routine and, if that went well, asks the audio CPU for each slot in turn. Requests and answers go through the shared window right after the recorder's ring: the main CPU names a slot and a byte offset, the audio CPU answers in its next block with the take's length and 512 bytes. One request is one sector of the drive. A slot's first sector, with its header, is written last and only if the take still has the length it had, so a save cut short leaves the old header. Then the stock scan reads the slot into the store's table, and the audio CPU is told to mark the take as kept. The marks live on the audio CPU; the main CPU's code keeps nothing between saves.

## Larger slots (big image only)

**The riskiest change in this project: it alters the code that finds samples on the +Drive, and the code that loads them at boot.** Shown in emulation (`tests/test_bigslots.py`, against a drive that is a Python dictionary) and then on the maintainer's unit (2026-10-07, `docs/FINDINGS.md`, hardware log): 10 s samples sent by the changed Transfer play in mono and stereo, slots 63 and 64 included, are still there after a power cycle, and one was pulled back to the computer at 10 s by the maintainer's account. Older projects and sounds still load.

What it is: stock gives each of the 64 slots 512 KB of the +Drive, 5.46 s. The big image gives each slot 1 MB, **10.9 s**, by using a stretch of the drive right after the samples that OS 1.42 never touches (36 MB to 68 MB; `docs/FINDINGS.md`). The slot count stays 64.

Two halves, and it needs both:
- the unit: `make image-big`;
- the computer: Elektron's Transfer cuts every sample it sends at 5.000 s, by a number of its own. `python -m tools.patch_transfer` makes a copy, `build/Transfer10s.app`, that cuts at 10 s. The installed Transfer is not changed. The copy is for a unit with the big image only: a stock unit drops a slot that claims more than 5.46 s.

What you get in this first step, and what you do not:
- one sample can be 10 s (10.9 s if something other than Transfer puts it there);
- **the total the unit loads at boot is what it was: 5:49 of mono, 2:54 of stereo.** The main CPU builds the whole pool in a fixed 32 MB of its memory before handing it over, and that is not changed here. The slots are loaded in order; one that no longer fits is left out, stays on the drive, and is silent. Twice the total is a second step (`docs/FINDINGS.md`, "Twice the pool").

Before flashing:
1. Back up your projects and sounds with Elektron's own Transfer.
2. Check that the unit's start-up menu is there (hold FUNC while switching on) and offers an OS upgrade. Do not run it, leave the menu. It is the way back if the unit will not boot.
3. Have the official 1.42 file and the image you run now at hand.

After flashing:
- **Every sample has to be loaded again.** On the first boot the unit shows stock's slots 1, 3, 5, ... as its slots 1, 2, 3, ..., up to 32, and nothing after: the left halves of your stereo pairs. That is expected.
- Make the files with `make samples BIG=1` (pieces of up to 10 s) and send them with `build/Transfer10s.app`.
- Elektron's own Transfer still works with the unit. It sends 5 s at the most and reads back whatever is there.

Going back to another image: flash it, then load every sample again with Elektron's Transfer. A stock unit reads this layout as garbage in half the slots and drops what it cannot use.

What is changed on the main CPU: 13 small places, each a number (a shift, an offset or a limit) in a routine that turns a slot into a place on the drive, and the routine that builds the pool at boot, rewritten in its own 246 bytes (`engine/poolstage.c`, 124 used). The audio CPU is the recorder image's, byte for byte.

## Twice the samples (double image only)

**On the maintainer's unit since 2026-10-08: a full set of 64 files boots and plays there.** The other images load 32 MB of samples at boot, whatever the slots hold: 2:54 of stereo. This one loads up to 64 MB: **all 64 slots at 10 s each, 32 stereo samples, 5:20 of stereo.**

- Nothing changes on the drive or in how samples are sent: the slots are the big image's, the sender is `build/Transfer10s.app`.
- A set of no more than 32 MB loads exactly as it does on the keep image, by the same steps.
- Past that, the unit loads the first 32 MB, then reads the rest from the drive and loads that. The loading screen stands still for a few seconds in the middle. A full set should take about twice as long to boot as a full set did before (not timed on the unit yet).
- The cap is 67,100,672 bytes of pool. 64 slots of 10.0 s fit, and so do 64 kept takes of 10.24 s. 64 slots filled to their last byte (10.92 s, which Transfer does not send) are 4,352 bytes too many: the last one is left out.
- `make samples BIG=1 DOUBLE=1` prepares a set for it and refuses one that is too large. `build/samples/double_test/` is a set that fills every slot: each stereo sample says its number, then "left", "right" and, in the last second, "end".

How it works: the main CPU builds the pool in a block of 32 MB and a task hands it to the audio CPU in numbered chunks of 2 KB; the audio CPU puts each chunk where its number says, in a pool of 64 MB. There is no second block. So the block holds one half of the pool at a time (`engine/poolhalves.c`): the builder fills it with the first half and writes the whole pool's length, and the sender, which now asks our routine where each chunk is, gets the second half's chunks from the same block after it has been filled again. A slot may lie across the two halves anywhere. The block's first byte says which half it holds, so an exchange that starts again from the first chunk gets the first half back. While the block is filled again the exchange stands still, and a stock timer that watches for that is kept quiet: its count is cleared after every 16 KB read.

It has not gone wrong on the unit. If it does, the likely way is a unit that stops at its loading screen once more than 32 MB is on the drive. The way back is the start-up menu (hold FUNC while switching on, OS UPGRADE) and the keep image, `build/images/Syntakt_OS1.42_sampler_keep.syx`, which loads the first 32 MB of the same drive. That menu's upgrade has not been used by this project.

## Names and words on screen (screen image only)

**On the maintainer's unit since 2026-10-08: the names and the words read as below there.** The double image with three knobs reading differently. Nothing else changes: the audio CPU's program is the double image's byte for byte, and so is the +Drive.

| Knob | Reads |
|---|---|
| SMPL, MODE 0 and 4 | the slot's name, or NO SAMPLE, as before |
| SMPL, MODE 1, 2, 3 and 5 | the **stereo sample's** name: the name of its left slot, 2n-1, without a last ` L`, `_L`, `-L` or `.L`. `KICK L` and `KICK R` on slots 3 and 4 read KICK at SMPL 2. A kept take reads TAKE 05. Past 32: NO SAMPLE |
| LOOP | OFF, FWD, PING |
| MODE | MONO, STEREO, REC MAIN, REC EXT, CHAIN, ST CHAIN |

- A name that does not end in a side is shown whole.
- The name comes from the +Drive. A take that has not been kept yet has none: SMPL reads NO SAMPLE on it, or the name of the sample it was recorded over, until the project is saved.
- SMPL reads MODE from the active track, which is the one whose page is open (seen on the unit with a stereo and a mono sampler track). The name is not shown while a trig is held.
- Seen on the unit and not explained: a take kept on SMPL 5 did not read TAKE 05 after the save or after a restart (`docs/FINDINGS.md`, hardware log).

How it works: a knob's value is turned into text by a small routine the display table names for it. Stock has one for the two sample selectors that looks the slot's name up. `engine/knobtext.c` takes its place (one address in the start-up code), and LOOP's and MODE's text are pointed at the same entry. Our routine sees which knob it is asked about from where the table's copy of the entry lies. For SMPL it asks for the open track's MODE the way the page itself asks for any knob it draws, and in stereo hands the stock routine the value that stands for slot 2n-1 in mono, then cuts the side off the name.

None of the ways it could have gone wrong showed on the unit (words where a name should be, a name where a word should be, a unit that stops when a sampler track's page is drawn). The way back is the double image, `build/images/Syntakt_OS1.42_sampler_double.syx`, through the normal OS upgrade, or through the start-up menu (hold FUNC while switching on) if the unit does not get that far. That menu's upgrade has not been used by this project.

## The sampling page (page image only)

On a track that holds the sampler, pressing SYN again shows a second page, and pressing it once more goes back, the way FLTR, AMP and LFO step through their two pages. On any other machine SYN has one page, as before. **This much ran on the maintainer's unit on 2026-10-09, with the page empty.**

The page is where the recorder's settings are going (the maintainer's list: source, destination, record, save, more sources, length, threshold, monitor, a level meter, normalize, a waveform). **Recording from the page ran on the maintainer's unit on 2026-10-09**: REC on, hold a trig, REC off, play. He then asked for REC to be lockable to a step. Two builds for that ran on the unit the same day: on the first SRC, REC and MODE did not move, on the second they did and a held trig locked nothing (each time a stock method read wrong, `docs/FINDINGS.md`). The image now in `build/images/` is the build after those, **and its lock works on the unit (2026-10-09): hold a trig, turn REC, that step records, and a retrig on it records too:**

| Knob | Reads | Does |
|---|---|---|
| first | SRC: MAIN or EXT | what this track's takes record: the main mix or the external input |
| second | DEST: SMPL, or 01 to 32 | where they go: the stereo sample the track's SMPL knob is on, or a numbered one |
| third | REC: OFF or ON (the once image: OFF, ON or ONCE) | ON puts the track in record: a trig starts a take, the end of the note ends it, and the track plays nothing meanwhile. OFF and it plays again. ONCE: "A step's REC", below |
| the other five | nothing | nothing |
| fifth, on the soloknob image | SOLO or S OFF | this track's solo: "A solo on the sampling page", below |

- **REC and SRC are part of the track's MODE parameter**, so they behave like any knob of the unit: saved with the pattern, and lockable. Hold a trig and turn REC to ON, and that step records while the track's other trigs play. While a trig is held the page shows that step's settings; turn REC back to OFF with it held to undo.
- **MODE on the first page now reads MONO or STEREO and nothing else.** Its record values moved here, and CHAIN is gone from this image.
- With DEST on SMPL the take lands on the stereo sample the track's own SMPL names, so the way to hear it is: REC to OFF, MODE on STEREO, play.
- DEST is the page's own: one a track, not saved, not lockable. After a restart every DEST reads SMPL.
- REC is saved now. A track left in record is still in record after a restart, as one left on MODE's record values used to be.
- LEVEL sets the track's level on that page as on any other.
- In a pattern made on an earlier image, a track that was on REC EXT comes up in record from the main mix, and one on CHAIN or ST CHAIN as MONO or STEREO.

How it works: one page object serves SYN for every audio track. It holds a list of page numbers and steps through it on each press of its key. Stock gives it a list of one; this image gives it two, and three of the object's methods go through routines of ours first (`engine/recpage.c`): "which parameter is behind this knob" (it shortens the list back to one off a sampler, and answers "none" for the eight knobs of the second page), the draw (stock draws, then ours writes on top) and a turn of a knob (the second page's eight are ours). REC and SRC are read from MODE's value and changed through the page object's own method for changing a parameter, the one the stock knob routine uses, which is what lets a held trig lock them. The first page's MODE knob goes through the same routine of ours, to switch MONO and STEREO only. DEST lives in 32 bytes added to the end of the object and is copied to a small box in the memory the two processors share, where the audio CPU reads it when a take starts (`docs/FINDINGS.md`, "REC and SRC as bits of MODE").

**Before flashing, leave the unit on a page that is not SYN** (FLTR, say): the change is in what SYN's page does on every audio track. If SYN misbehaves, the way back is the build that is on the unit, where everything but the lock works, `build/images/old/load_step2_plain_turn_works_lock_dead_850d6e8c.syx`, or the screen image, through the normal OS upgrade, or through the start-up menu (hold FUNC while switching on) if the unit does not get that far. That menu's upgrade has not been used by this project.

### Sources and the meter (meter image)

**Not flashed.** The the maintainer's report.

- **SRC has sixteen values**: MAIN, EXT, T1 to T12, FX (the FX track's return), DELRV (the delay and reverb). A track is one channel, so a take of one has the same sound on both sides. Tracks 9 to 12 are the copies the sends and USB get.
- SRC is still part of MODE's value and still the track's alone. What an earlier build saved reads as it did.
- **A bar along the bottom of the screen** follows the level of the track's source, whether REC is on or not. Full length is the largest sample a take can hold; every ten dots less is half of it; a dot at the right marks full length. It jumps up at once and falls 13 dB a second.
- It is drawn only while the sampling page is on show, 16 times a second.

How it works: the feed (`engine/recfeed.c`) already reads the main CPU's 20 channels once a block. It now also keeps the largest sample of the source the page last drew for, and asks for the page to be drawn again every 96 blocks, with the request stock's own code uses. The page (`engine/recpage.c`) draws the bar with stock's rectangle routine after stock has drawn the page.

### Record gain (gain image)

Knob F on the sampling page, the second box of the lower row: `0dB`, then `+1dB` to `+24dB`, a decibel a click. It is the track's: what a take recorded on that track is turned up by.

- The gain is put on before the take is made 16 bits, so a quiet source comes up clean: a tone 66 dB under full scale recorded with 24 dB of gain is as clean as one 42 under, where turning the take up afterwards would bring its noise up too.
- The meter shows the level with the gain on. Set the gain so the bar gets near its mark and no further: past it the take clips, as it always has.
- It is not saved with the project and cannot be locked to a step, like DEST. It is 0 after a power cycle.
- At `0dB` a take is exactly what it was before this image.

### What a take is (mode image)

Knob G, the lower row's third box: `MONO` or `STER`. Read "A sample is mono or stereo by itself". **On the pack image it is for takes at SMPL 1 to 32 only**: a take at 33 to 64 is mono whatever it reads. A turn shows MODE=MONO or MODE=STEREO as a knob's turn does. The first page's sixth place, where MODE was, is empty there and its knob does nothing. The lower row's last box reads the audio CPU's peak load for now.

### Saving the takes from the page (save image to solo image)

**On the unit since the save image, and it passed there (2026-10-10). Gone from the ptn image**: read the next section. The the maintainer's report.

- **The first box of the lower row reads SAVE.** Turn its knob (the fifth) to the right and every take that is not on the +Drive yet is written to its slots. The project is not saved.
- The box reads BUSY while it writes, then DONE, or FAIL if the drive or the audio CPU did not go along. A turn to the left puts SAVE back.
- The unit carries on meanwhile: there is no SAVING screen. A long take takes a few seconds.
- A take that is recorded over while it is being written is left for the next save.
- SAVE PROJECT still writes the takes too, as before.

How it works: stock runs a project save as a job on a worker of its own, and that is where the drive may be written. SAVE starts a job of ours on the same runner, which does the second half of what a project save does on this image (`engine/keeptakes.c`).

### Saving the takes with a pattern (ptn image)

**Not on the unit.** The on request.

- **The pattern menu's SAVE TO PROJ, WHOLE PATTERN writes the takes too.** Answer its Y/N with yes, or for a pattern that has no name yet confirm the name it asks for, and after the unit's own "Ptn saved to Project" every take that is not on the +Drive yet is written to its slots.
- It is written in the background: the pop-up comes at once and the unit plays on. A long stereo take takes a few seconds. **Switched off in that time, that take is not kept.**
- Not by the other saves of a pattern: the save to the temp area from the main screen (FUNC+YES), KIT DATA and SEQUENCE DATA are the unit's own and write no take.
- The project has to have been saved once. For a project never saved the unit says "N/A: Unsaved Project", saves no pattern, and no take is written.
- **There is no SAVE box.** The sampling page's fifth place is empty and its knob turns nothing, while the takes are written and after. Only a save that did not get every take onto the drive is said: the place reads FAIL until a pattern's save does get them all there. (A project's save writes the takes and leaves that word as it is.)
- A take that is recorded over while it is being written is left for the next save, and the takes after it are still written, where on the images before the save stopped there. The place reads FAIL after that too: not every take is on the drive.
- **On the feed image the place says nothing at all**, FAIL neither. A save that could not write every take still leaves them to be written by the next one; nothing on the page says so.
- A pattern saved again while the takes of the save before are still being written is saved, and writes no takes of its own: what was recorded in between waits for the next save.
- SAVE PROJECT writes the takes as it always did.
- A written take replaces what the drive had in its slots, for good, as with SAVE PROJECT. Reloading the pattern from the project does not undo it.

How it works: stock has one routine that saves a pattern and five calls of it. The two that save a whole pattern to the project, after the Y/N and after the naming screen, go to a routine of ours that calls stock's and, when it answers that it went well, starts the job SAVE started. Nothing is written where the pattern is saved: that is the task the keys and the screen are served in (`engine/keeptakes.c`, `ptn_keep`; `docs/FINDINGS.md`, "Takes written with a whole pattern's save").

### DEST NEXT and KIND (next image)

Built 2026-10-24, not on the unit. The maintainer: no more dialling to find a free mono or stereo place.

- **DEST (B) is SMPL or NEXT.** SMPL: a take goes where SMPL is, as before. NEXT: it goes to the next free place, and once it is there the track's SMPL is on it (reversed if SMPL was), so REC off and play is the new take. The next take goes to the next free place again. DEST is the page's own, SMPL after a start.
- **KIND (C, where REC was) is STER or MONO**, the track's own, kept with the kit, not lockable. STER: the lowest free stereo place (from 1 up). MONO: the highest free single slot (from 64 down). It only matters on NEXT: on SMPL the number says the kind, as always.
- Two tracks on NEXT never get the same place. None free: the take goes where SMPL is.
- **From the kind image on, SMPL follows KIND too**: a STER track's SMPL stops only at stereo samples and the next free stereo place, a MONO track's only at mono samples and the next free single slot. Flip KIND to reach the other kind; a pattern or lock on the other kind still plays it.
- **Going back to an older image: set KIND to STER first.** A track left on MONO reads as an old pattern there, and its SRR goes to 0.
- How it works: `docs/FINDINGS.md`, "The next image".

## Loading a project (load image only)

**Works on the maintainer's unit (2026-10-09).** LOAD PROJECT also puts the drive's samples back in every slot that holds a take the drive does not have. So a project comes up with the samples as they were at the last save, without a restart.

- Record, save the project, record again into the same place, load the project: the saved take plays. Without this image the second take stays until a restart.
- **A take that was never saved is gone when a project is loaded**, whichever project. On the earlier images it stayed until power off. Save the project first if the take matters.
- A slot whose take was recorded over a sample from the computer gets that sample back. A slot the drive has nothing for is empty again.
- It is the Project Load screen's load that does it. The load at power on has nothing to do: takes do not outlive power.
- It takes time after the unit's own load, while the screen says LOADING: a sector of the drive an audio block, so about 2.6 s for a full 10 s stereo sample plus the drive's reading, and nothing when no slot holds an unsaved take. Not measured on the unit.
- A note that is sounding a slot while it is loaded goes on with the new samples until its next trig. Stop the sequencer first if that matters.
- **Samples are still not part of a project.** The 64 slots are shared: a take one project keeps is replaced when another project keeps one in the same place. A set of takes for each project is the step after this one, and is not designed.

How it works: the one call to the routine that loads a project for that screen goes to ours (the load half of `engine/keeptakes.c`), which calls the stock routine and, if that went well, asks the audio CPU for each slot what a save asks: is there a take the drive does not have. Such a slot is read from the drive a sector at a time and sent through the box that keeping takes uses, the other way: the main CPU puts 512 bytes in it, names the slot and the offset, and the audio CPU copies them into the slot's take buffer. A last request gives the length; the audio CPU then plays the slot from that buffer and marks it kept. The drive is only read.

## Sample banks (bank image only)

**Works on the maintainer's unit (2026-10-10).** Three banks, A, B and C, each a whole set of 64 slots: 32 stereo samples of 10 s. One is loaded at a time. Every project is saved with a bank and brings it in when it is loaded.

- **BANK on the sampling page** (SYN twice on a sampler track, the fourth place) reads the loaded bank. Turn it and it reads both, the loaded one and the one chosen: `A>B`. **Turning it loads nothing.** It is the project's, not a track's.
- **SAVE PROJECT writes the choice down** for that project. **LOAD PROJECT loads the project's bank**, if it is not the one loaded already: every slot, while the screen says LOADING. A bank changes at no other moment. So to put a project on bank B: BANK to B, save the project, load the project.
- A project that was never saved on this image is on bank A, where its samples are.
- **Transfer reads and fills the bank that is loaded**, its 64 slots, with nothing new on the computer's side. To fill bank B, load a project that is on B and send. As always, a sample that was sent is heard after the next start.
- **A take is kept in the bank that is loaded.** Two projects on the same bank share its samples and takes; projects on different banks cannot touch each other's.
- The unit starts on the bank that was loaded when it was switched off.
- Loading a bank takes as long as there is sample in it: under half a second for each megabyte, plus the drive's own reading. A bank that is full, 61 MB, is about what the unit takes to load its samples when it is switched on. The LOADING bar starts again and climbs, a slot at a time. A project on the loaded bank costs nothing more than before. (The first build took three times as long for the requests and read the drive a sector at a time: a full bank looked like a hang.) Not measured on the unit.
- Nothing is recorded while a bank loads: the recorder's room in the shared window carries the samples.
- BANK turned and the project loaded again without a save: the turn is forgotten, like any change that was not saved.
- A project copied in the project manager is on bank A until it is saved with another: the copy does not take the bank along.
- Going back to an earlier image: bank A is where the samples always were, and all of it is there. Banks B and C stay on the drive, unseen.

How it works: the drive has three runs of 64 slots one after the other, the first where the samples always were. Everything in the program that reads, writes or erases the drive does it through three routines, named in 21 places; those places name three routines of ours instead (`engine/banks.c`), which move a sector of the first run to the bank that is loaded and jump to stock's. So nothing else had to learn about banks. One sector of ours after the third run holds the loaded bank and each project's. The save and load hooks of `engine/keeptakes.c` write and read it, and a load that changes the bank has stock scan the slots again and the load image's loader load all 64.

## Fades (fade image only)

**On the maintainer's unit since 2026-10-10, and its seven listening checks passed there.** Where the sound is cut into, it is faded and not switched, so that a cut does not click.

- **STRT off 0** (or, played backwards, LEN short of all): the note fades in over 1.3 ms.
- **The soft image on: a note whose first frame is loud** (past 128 of 32,768, about 48 dB under full, on either side) fades in the same way wherever STRT is. A take begins wherever its source was, so most takes do; a hit taken from its start, or a file trimmed to silence, begins as it did. Not on the unit yet.
- **LEN short of all** on a one-shot (or, backwards, STRT off 0): it fades out over the 2.7 ms before its end.
- **The tail image on: any one-shot** fades out over the 2.7 ms before its far end, at full LEN too. A take ends wherever its source was. Not on the unit yet.
- **LOOP on FWD**: the loop fades out over the 2.7 ms before its seam and in over the 1.3 ms after it. The seam does not move and the loop is exactly as long as it was, so a recorded bar stays in time.
- **Left alone:** a note from the sample's own start (a drum keeps its attack), a sample played to its own end, LOOP on PING (a turn is no jump), and a loop under about 21 ms a pass at the pitch it plays at (that short it is a tone, and a dip a pass would change it).
- The fades are as long at any pitch.
- What it costs: a loop dips to silence for about 4 ms a pass. On a loop that used to click that is the cure. On a loop that did not, it is a small notch that was not there; a drum loop's first hit is faded in from the second pass on.
- It is a fade and not a crossfade: a crossfade needs sound from past the loop's ends, and a loop of a whole take has none (`docs/FINDINGS.md`).

### A crossfade at the seam (cross image)

Built 2026-10-12, not on the unit. The the maintainer's report

A blend needs sound that leads to the place the next pass begins, and a loop that keeps its length has only what lies outside it. So, for LOOP on FWD:

- **STRT up from 0** (at least 256 frames of sample before the loop's start, 5 ms at its own pitch): the pass's last 256 frames go down as the 256 before the start come up. The pass ends on the very frame the next begins after. The loop's start is untouched: a hit there keeps its attack every pass.
- **STRT at 0 and LEN short of all** (256 frames after the loop's end): the seam is 256 frames later on both sides. The pass runs on past its end as the frames after the start come up under it, and the next pass begins 256 frames in. From the second pass on, the loop's first 5 ms are a blend of what follows its end into what follows its start.
- **A loop of the whole sample has neither, and keeps the dip.** That is a recorded bar looped as it is. To have it blend, record a little more than the bar and pull LEN in, or set STRT a touch above 0.
- Played backwards the same, the other way round. PING has no seam. A loop under about 21 ms a pass is left alone, as before.
- **The loop is exactly as long as it was** either way: it stays in time.
- The blend is 256 frames of the sample, so 5 ms at its own pitch, 11 an octave down, 2.7 an octave up.
- **It is not there at once.** The blended frames are written out ahead, eight a block, from the block after the note starts (after the fade in, if STRT is off 0): 44 blocks, 30 ms. A seam that comes sooner than that dips as it did, and the ones after it blend. The same after STRT or LEN has moved: the blend is written again for the new seam. While they are moving, every seam dips.
- A pass that has gone into its blend (the last 7 ms before its seam, at its own pitch) is not moved by the knobs until it is through: STRT and LEN turned there are taken a pass later.

How it works: two sums a frame for the length of a blend would have been twice the work in blocks where every loop started together is in its seam together, and there is no such room. The blended frames are made of the sample's own frames, before it is pitched, into 352 frames a voice of free memory, and a pass that reaches them is played from there by the routine that plays a sample (`engine/sampler.c` built with XFADE, `docs/FINDINGS.md`). A block in a seam costs less than a block of the dip did.

## STRT and LEN while a note plays (len and live images)

On every image before these STRT and LEN are a note's own from its start: a turn is heard at the next trig. **The live image runs on the maintainer's unit since 2026-10-10 and is right there** (a short loop with STRT turned: "sounds great"). Two earlier builds ran there the same day: LEN was right both times, STRT fluttered in the first and ripped on short loops in the second. The len image, STRT left alone, was the fallback and was not needed.

**Both images: LEN.**
- Turn LEN while a loop runs and the loop is that long from then on. Shorten it down to a buzz and open it again.
- Pull the end in behind where the sound is: a loop starts its next pass, a one-shot ends. Through a short fade when the loop is longer than about 21 ms, at once when it is shorter.
- Played backwards a pass begins at the region's top, and LEN is how far down it goes: turned, the pass that is playing ends that much sooner or later, and the next begins at the new top.
- A lock on LEN or STRT belongs to its own note as before.

**The len image: STRT is the note's own.** Turn it while a note plays and nothing happens to that note. The next trig takes it. This is the unit as it always was, for that knob.

**The live image: STRT too.**
- A loop's next pass begins where the knob is by then. The pass that is playing is left alone, so the turn itself makes no sound.
- A short loop therefore steps through the sample as you turn, a pass at a time, and never stops being a loop. A long one takes the new start when it comes round.
- With LEN at all of it a loop runs to the sample's end whatever STRT does.
- A one-shot is one pass: STRT does nothing to it once it has started.
- LOOP on PING: the new start is taken when the sound is back where its pass began.

LOOP, SMPL and MODE are a note's own from its start on both. A track in record is left alone.

## LEN's floor (floor image)

LEN stops at 3: the knob reads 3 to 127, and the engine takes no less from an LFO, a lock or a pattern saved with less. Under that a loop closed to a buzz. 3 is 3/127 of what the sample has left after STRT: an eighth of a second of a full 5 s sample from its start, less on a short sample or with STRT far in. The first build stopped at 6 and ran on the maintainer's unit on 2026-10-10: "it works but i actually want it to go down to 3 instead". **The build with 3 is not flashed.**

## A step's REC (reclock image)

**It records on the unit from the meter image on only.** On the reclock and pitch images the lock is made and shown and never reaches the sound engine: stock writes its hold flag over slot 24 of the block that is sent (`docs/FINDINGS.md`, hardware log, "the probe image, and the cause"). `engine/recword.S` puts the mark back for a sampler track.

**Works on the maintainer's unit (2026-10-10): the step records, MODE is left alone, and the lock is there after a save and a power cycle.** Up to the floor image, holding a trig and turning REC locked MODE, because REC, SRC and the stereo switch are three bits of that one parameter: the step kept its stereo switch and source as they stood, and the first page showed MODE locked on it.

- Hold a trig on the sampling page and turn REC: that step records, or does not, whatever the track's REC says. Nothing else of the step is locked. While the trig is held the page shows the step's REC.
- Turn it back with the trig held and the lock is gone: a lock is there only where a step differs from the track.
- SRC is the track's. With a trig held it still changes the track's.
- MODE on the first page can be locked as before, and locks the stereo switch only.
- REC locks made with an earlier image were locks of MODE. Turn the track's REC on and off once: they stop recording. Then lock REC again on the steps that should.
- Change a sampler track to another machine and its REC locks are removed the next time its SYN page is shown.

How it works: the unit keeps a lock for every knob slot of a track, used or not. Slot 24 has no knob on a digital track, and the sampler ignores what the stock engines use it for. A step's REC is a lock there (`engine/recpage.c`), which the sound engine and the feed read ahead of MODE's bit (`engine/sampler.h`, `REC_ON`).

**ONCE (the once image; not on the unit).** The the maintainer's report REC turns through OFF, ON, ONCE, a setting a click.
- **A trig held, REC to ONCE:** the step records the next time it plays, as a step locked ON does and for as long (to the track's next trig), and then its REC lock is gone. The trig stays: on the pass after, it plays, the take if SMPL points at it. Nothing else of the step is locked. While the trig is held the page reads ONCE for it until it has played.
- **No trig held, REC to ONCE:** the track is armed. The next step the sequencer plays on it records one take, to the track's next trig, and REC reads OFF from there. It is not saved and is OFF at power on. A step locked OFF does not use it up; a step locked ON or to ONCE does.
- A step locked ON records every pass, as before. What an earlier image saved reads as it did. The feed image reads a step's ONCE as ON.
- Not known until the unit says: whether a held trig's preview or a track's key spends a ONCE as the sequencer does.

How it works: a step's ONCE is the same lock at a second value with the same mark, so the audio CPU, the feed and `engine/recword.S` take it for a step locked on and are not changed. Where the sequencer plays the step (`engine/once.S`, two places in stock's routine) the word in the pattern becomes one that says nothing, and the main task takes the lock off with stock's routine for a lock removed by hand when its next message comes (`engine/onceclean.c`). The track's ONCE is a byte a track of ours: the next step played on the track gets "REC on" added to its locks. `docs/FINDINGS.md`, "REC's third setting, ONCE".

## Pitch (pitch image)

**Its first build ran on the maintainer's unit on 2026-10-10: "its better but when pitchrf low i still hear some clciks and pops".** Then, of that build or the next: "they sound all fucked up, and there's a lot of noise" with TUNE moved. **The first two builds believed a table of numbers left in memory by an earlier start, and memory that has been off for a moment comes back with bits changed.** The third build, which is the one here, makes the table at every start; it also has the second's change, a low note's first and last blocks at the cost of the rest (`docs/FINDINGS.md`). **He then said it was noisy with no restart too, and on a take at normal pitch, which the table does not explain. The cause is not found. Until it is, flash the safe image (`make image-safe`): the meter, the sources and SAVE on the sound engine from before the pitch change.** A sample played away from its own pitch has to be read between its frames. Up to the reclock image that was the line between the two nearest, which is what a pitched-down sample's grit is: the sound folded around the sample's rate comes through, 30 dB under a 6 kHz part of it and 15 dB under a 14 kHz part. The the maintainer's report.

On the pitch image the frame is worked out from the sixteen around it. The same parts now have everything else 86 and 76 dB under them, at any pitch below the sample's own.

- At a sample's own pitch nothing changes, to the bit.
- Pitched, a sample is also a little brighter than it was: the line dulled the top of the sound, by 4 dB at 18 kHz.
- Played above its own pitch, what goes past the top of the range still folds back, as before.
- It costs time: a pitched voice is about three times the work it was. Eight pitched sampler tracks at once are two thirds of what the unit's heaviest machine asks on all eight. Not timed on the unit.

## Sample rate reduction (srr image)

- **SRR**, the first page's sixth knob, 0 to 127, turning as LEN and DEC do (the second build: the first was geared as stock's sample picker, half as fast). 0 is off. Every 16 halves the rate the sample's frames are let through at: 16 is 24 kHz, 32 is 12, 48 is 6, 64 is 3, 80 is 1.5 kHz, 96 is 750 Hz, 112 is 375 Hz, 127 about 190. Nothing is smoothed.
- It acts on the sample as it is played, before the track's level, overdrive and filters, on both sides of a stereo sample. A note's start lets its first frame through, so a hit is the same every time.
- It is a parameter like any other: hold a trig and turn it for a lock. An LFO's move reaches it unsmoothed (read in the listing); whether it is in the LFO's list is for the unit to show.
- It is MODE's old parameter. The track's REC and SRC moved to a place of their own (knob slot 24, signed) the first block an old pattern plays, and the pattern's old locks of MODE are taken off. One way: a pattern saved on this image reads wrong on an older one.
- SY SWARM is gone: its code is this image's room. A track left on it plays nothing.
- Cost, counted: about 2 on P with eight stereo tracks at their worst, under half a hundredth at 0.

## Long samples

Optional. Load a long sample as consecutive slots, each within the UI's 5 second limit, and set MODE to 4 (mono) or 5 (stereo). The engine plays them as one sample, seamlessly, up to the first empty slot or the last slot of all. START, LENGTH and LOOP then act on the whole chain. In stereo the chain is left, right, left, right. In MODE 0 and 1 every slot (or pair) is a sample of its own.

One slot can hold 524,032 frames (10.9 s) as far as the engine cares. Where the 5 s limit is enforced is not located (`docs/FINDINGS.md`).

## Preparing samples

Elektron Transfer trims anything over 5 seconds and stores mono. So a stereo sample has to go in as two files, left and right. 64 slots hold **32 stereo samples of up to 5 seconds**.

Drop audio files, or folders of them, into `samples/` and run:

```
make samples            # slots from 1
make samples FIRST=9    # slots from 9, to keep what is in 1..8
make samples BIG=1      # for a unit with the big image: pieces of up to 10 s
```

That fills `build/samples/transfer/` (replacing the last run) and opens it. `tools/split_sample.py` does the work and also takes files and an output folder directly. Input can be WAV, AIFF, MP3, M4A or FLAC; output is 16-bit 48 kHz mono, so Transfer has nothing left to convert. Nothing is resampled down or packed.

Every file name starts with the slot it belongs in:

| Input | Output | MODE |
|---|---|---|
| stereo, up to 5 s | `07_name_L.wav`, `08_name_R.wav` | 1, SMPL 4 |
| mono, up to 5 s | `09_name.wav` | 0, SMPL 9 |
| longer | cut into 5 s samples: `11_name_01L.wav`, `12_name_01R.wav`, `13_name_02L.wav`, ... | 1 each, or 5 to play them as one |

**For the pack image: `make samples PACK=1`.** Stereo files go in from slot 1 up as above, mono files from slot 64 down (`64_kick.wav`, `63_snare.wav`, ...), each to be played at the SMPL number of its slot. A set whose two kinds would meet, or with more than 32 mono files, is refused with a plain message. **And for the stops image, which tells the two kinds apart by length:** a mono file comes out an odd number of frames and a stereo one an even number on both sides, the last frame left out where it has to be (a 48,000th of a second) and nothing else changed.

`build/samples/transfer_slots.txt` lists which slot holds what, and the MODE and SMPL to dial in. A stereo sample always starts on an odd slot (slot 10 is left empty in the table above). A set that does not fit the slots left is refused with a plain message. In Transfer, check that each file sits in the slot its name says: a pair only works with L in the slot right before R. Whether Transfer fills slots in name order by itself has not been checked by this project.

Tests play a full-size 5 s stereo pair (240,000 frames a side) through the engine in MODE 1 and get the original left and right, sample for sample, with no leak from the neighbouring pair. A chained stereo file is tested the same way.

`samples/stereo_test.wav` (made by hand, not by the build) is a check sample for the unit: a bass line on the left only and high plucks on the right only for the whole 5 s, a voice saying "left" on the left and "right" on the right, and "both" on both sides at the end. It is 8 beats long, so it loops. Two more sit beside it to make a five slot check set: `count.wav` (mono, a voice counting one to five, one number a second) and `stereo_sweep.wav` (a chord moving from hard left to hard right over the 5 s, ticks alternating left and right).

## What it costs

Instructions per voice per 32-frame block, against the Phase 3 budget:

| | per voice |
|---|---|
| idle (nothing playing) | 1,153 |
| mono | 2,176 |
| stereo | 2,904 |
| worst that keeps playing (stereo, chained, a loop of a few frames around a slot seam, octaves up) | 7,848 |
| worst single block (the same, in the block where such a note is stopped) | 9,079 |
| pitch image: mono, played off its own pitch | 6,180 |
| pitch image: stereo, played off its own pitch | 10,750 |
| stereo image: a track's right channel through the unit's overdrive, filters and envelope | 2,703, and 16,041 for the first |
| stock Twinshot, for comparison | 3,883 |
| budget (SY SWARM, the heaviest stock machine) | 10,506 |

A voice may take 40 slot seams and loop turns in one block. Past that the note stops. Only a loop of a few frames played octaves up gets there: the loop has to be shorter than 0.8 of what the pitch travels in one frame, so under 7 frames at 3 octaves up and under 1 frame at the original pitch. That is a pitch above what 48 kHz can carry, so nothing musical is lost. Without the limit such a loop cost up to 15,600 a block, past the budget; the images built before 2026-10-07 have no limit (theirs was 8 per frame) and the old worst case in this table, 5,150, had not found it.

The extra step after the voice loop costs 196 instructions per block in total. Counts are a lower bound on real cost: no cache model.

The stereo image, the audio CPU's whole interrupt with eight sampler tracks, in instructions, against 117,348 for SY SWARM on all eight (`tests/test_lean.py`, `tests/test_quick.py`, `tests/test_stereo.py`):

| Eight tracks | first build | second | third | third, sum of twelve |
|---|---|---|---|---|
| stereo, at their own pitch | 94,251 | 84,579 | 76,674 | 76,674 |
| stereo, pitched | 160,319 | 116,679 | 108,774 | 102,615 |
| mono, pitched | 87,732 | 67,975 | 66,423 | 61,815 |
| on the unit's meter, stereo: own pitch, pitched | fine, "major distortion" | 72, 99 and over | not read yet | not read yet |

The mode and cross images, eight pitched stereo loops cut out of their samples and trigged together, the sum of twelve (`tests/test_cross.py`):

| A block | mode image | cross image |
|---|---|---|
| steady | 102,750 | 103,360 |
| the notes start in | 113,440 | 113,740 |
| of the fade in after | 109,070 | 109,550 |
| the blend's frames are written in (44 of them) | | 105,500 |
| in a seam | 112,160 (the dip) | 107,140 |

A mono sample on the mode image costs what a track on MONO did. A loop of the whole sample is 500 more a block on the cross image, a note that does not loop 400. **The pack image is the cross image's count in a steady block (103,367), and 112 more in the block eight notes start in** (`tests/test_pack.py`). **The stops image is 128 more in every block**, for the sixteen slots it says: 103,495 steady, 113,980 in the block eight notes start in (`tests/test_stops.py`).

**A count is not time.** The unit's meter read the second build's 84,579 as 72 hundredths of a block and its 116,679 as 99, and seven SWARMs with a sampler (about 106,000) as 81: an instruction of ours costs about a sixth more than one of SWARM's. `docs/FINDINGS.md`, "The interrupt made shorter". On the main CPU: 732 instructions a block with no stereo track, 979 with eight, beside a mixer of 21,381.

## How it is installed

Audio CPU (both images):
- 1,940 bytes of code in two runs of stock functions that nothing in the image references (`tools/audiomap.py`, `CAVES`). Stock Twinshot's own code is left untouched and simply never reached.
- Three pointers changed: engine 11's update and render table entries, and the audio interrupt's call to the voice loop (so a step can run after it).
- Its state is the 88 bytes of the voice that Twinshot used. Right channels wait in 896 bytes of free SDRAM at `0x44050000`.
- No EMAC, no library code, no data sections.

Audio CPU, recorder image only: 146 bytes more in those two runs, and 206 bytes in a third run of unreferenced functions at `0x40004a6a` (`REC_CAVES`). Takes live at `0x44080000 + 0xf0000 * slot`, 60 MB of free SDRAM in all. The state of a take is 9 spare bytes of the voice.

Main CPU (full image only, `tools/build_main.py`):
- Knob descriptors of machine type 44: 17 table fields and five name strings, 45 bytes in all. Data only.
- Knob display: ten operands in the start-up routine that fills the display table (`tools/uitable.py`), so START and LENGTH read 0..127, LOOP 0..2 and MODE 0..5. Stock would show them as -64..+63, a tune value and a slot number.
- The mixer link (`engine/mixlink.c`): 394 of the 396 bytes of one unreferenced function, plus the operand of the one call to the mixer. For the length of each mixer call it makes the right-hand track's sends, volume, routing and level words equal the left's and forces the pans, shows muted digital tracks a volume of 0, then puts everything back.

- The analog mute (`engine/amute.c`): 142 bytes in a second unreferenced function, right before the pan routines. The call to the mixer goes to it first, then on to the mixer link.

Main CPU, recorder image only: the feed (`engine/recfeed.c`), 156 bytes over three mix kernel variants that nothing calls, right next to the kernel the mixer does use, and its 16-bit conversion, 168 bytes in the room left after the analog mute. The call to the mixer goes to the feed, which calls the analog mute and the mixer link first.

Main CPU, feed image only: the routine that writes a block of a take (`engine/feed.S`), 564 bytes in one more run nothing reaches (`0x400a8db6`, 642 bytes). The older routine and its gain routine are not built there: 194 bytes of the analog mute's run and 122 of the feed's first run are room again.

## Known limits

- Sound quality is linear interpolation, like stock. At a slot seam in a chain the interpolation holds the last sample instead of looking into the next slot.
- Pitch steps are 1/4096, like stock.
- A loop is the whole region, as it was when the note started. No loop point. A crossfade at the loop on the cross image, where there is sound outside the loop to blend with; a loop of the whole sample dips. A loop too short for its pitch stops the note (What it costs).
- Stereo costs two tracks up to the save image, one on the stereo image. See `docs/STEREO.md`.
- With the audio-only image the screen still shows these knobs Twinshot's way: FLT1 (start) and MIX (length) as -64..+63, TUN2 (loop) as a tune value, SMP2 (mode) as a slot number that reads 64 less than MODE. The full image shows plain numbers; that part has not been seen on hardware.
- Twinshot's second sample layer, its one-knob filter and its mix knob are gone.

## Where the main CPU's time goes

From the prof image on (`make image-prof`), in every image: the maintainer, 2026-10-13, "Can't you just build the profiler into the latest image so it's there moving forward?". It is off at every start, and then SRC's last source records the sends as it always did. It was first built as a tool. On request.

What to do:
1. On a sampler track's sampling page turn **the last knob to the right: its box reads PROF**. Set **SRC to SENDS**, DEST to a free place, REC on. Record a take as always, while the unit does what is to be measured (the pattern that drags, the knobs turned). About five seconds is 7,500 blocks.
2. **The take is numbers, not sound: played, it is a loud buzz.** Keep the track down.
3. Save the takes (the pattern menu, SAVE TO PROJ, WHOLE PATTERN), bring the sample off with Transfer.
4. `make prof-read FILE=path/to/the.wav`. Several files: `FILE="a.wav b.wav"`.
5. Turn the last knob back to the left when done: the box reads the load again and SENDS is the sends.

What it says:
- **The per-block interrupt's time, exact, every block**, in hundredths of a block: the whole of it, and its four parts (before the mixer, the mixer with our links, the takes and the meter, after). What is left is all the tasks have.
- **What the interrupt stopped**, a sample a block: at what level (0 is a task), which task, the routine it was in and the routine that called it.
- The timer's rate, worked out from the block's length (stock's own wait says 132 MHz).

What it cannot say: the sample is taken at the same point of every block, so code that runs right after the interrupt and is done before the next one is never seen. The shares lean to what runs long. The interrupt's own time has no such lean.

The take's own cost is in what it measures: the record is 64 words written to the window a block, where a take of sound is 64 words and the feed's arithmetic.

## Hits that start the filter's envelope (hits image)

On a sampler track, a long sample's hits start the filter's envelope again, as if each were a trig of its own: the maintainer, 2026-10-13, "the hits inside the audio retrigger the FILTER envelope ... Filter only, not the LFO". The amp is not touched, nor are the LFOs, nor the sound itself.

- **The control is DEL**, the Filter page's envelope delay, on a sampler track only: 0 off, 1 lets only the loudest hits through (-3 dB and up), 127 every hit the scan found (-45 dB and up), a step every 8 or 9. It is stock's own parameter, so it locks to a step, takes an LFO and is saved with the pattern. On a sampler track the envelope never waits: stock is handed DEL at 0. The knob still reads DEL on the hits image; **on the hitui image it reads HITS**, in its pop-up too, and FLTR1's picture of the envelope has no delay in it. **On the trans image it is a knob named TRANS** (stock drew DEL's own delay picture), TRANSIENT in its pop-up. Every other machine's DEL is stock's.
- **FENR** (the envelope's reset, beside it) is stock's: on, a hit starts the envelope from nothing (the sharper of the two); off, from where it is.
- **What a hit is**: a window of 32 frames (0.67 ms) whose loudest is more than twice where the sound has been (the loudest so far, falling 0.14 dB a window), at least 21 ms after the last. How loud it is: the loudest of its window and the three after, in 15 steps of 3 dB. Where it ends: the end of its last window within 24 dB of its own loudest, found once a follower falling 0.56 dB a window is under that (so a low note's crossing does not end it), and never past the next hit. A bass line has its start and nothing else; a kick and a hat each have theirs; over a steady bass a hit lasts to the next one.
- **The scan**: every slot that holds frames is gone over once, 128 frames a block (four times as fast as it plays), a slot a playing voice is on first and the others in turn. A 5 s sample takes 1.25 s; until the scan has passed a place, a hit there says nothing. What it finds stays with the slot (up to 123 hits a slot), for the slices to come. A slot is gone over again when its place, its length or a print of 16 of its frames change: after a take, a load, a bank.
- **When**: a hit is said two blocks before the playhead reaches it, at the pitch it plays at, so that the cutoff it makes is played on it (the order the two CPUs run in, INFERRED, not timed: a block either way is 0.67 ms). Forward, at its start. **Backward, at its end, where its sound comes up out of the quiet**; so a ping-pong loop says them both ways. The hit a note starts on is left to the note's own trig. A loop's start is said again after each turn, a block late.
- **What it costs**: the audio CPU's interrupt with eight stereo voices, about 880 instructions more once every slot is gone over, 2,100 while one is, 3,250 at the most (its heaviest here 80,559 of stock's heaviest machine's 117,348). The main CPU's call of the envelope, 252 instructions more with six sampler tracks on DEL.
- **Where**: the audio CPU in SY TOY's and SY BITS's code, 1,300 of its 2,052 bytes; SY SWARM's run and the first run are as the lap image left them. The hits in free memory (`0x44070000`, 32 KB); they cross in the window's long at `0x5b4`, where the time image's C was (P is where it was). The main CPU in a run of its own (`engine/hits.c`).
- **SY TOY and SY BITS are gone**, as SY SWARM is: a track left on either plays nothing. The machines are still in the list.

## Hits found by their attack (scan image)

On the scan image a slot's hits are found by two things a window: its loudest frame, and its loudest step from one frame to the next (a high pass of one subtraction, scaled by the slot's own loudest of each). Each has a follower that falls a 128th a window; a hit is either past its follower by half again (3.5 dB), the rise more than 42 dB under the slot's loudest frame (and over -72 dB of full scale). So a hat on a held bass or a pad is a hit, and a quiet take has a loud one's hits. A hit's step is its place among the slot's hits by how sharp its rise is: the sharpest fifteenth 15, down to 1. DEL's mapping is the same, so each step of DEL takes about the same share more of the hits, whatever the sample. The slices are the same list. The code is in SD BASIC's room: **a track on SD BASIC plays nothing**.

## Wanted, not built

**128 steps, as two patterns played as one.** Pattern n (1..64) plays its 64 steps, then pattern n + 64's, by stock's chain queue, with n's kit through both halves; 65..128 are not picked by themselves. Pages 5 to 8 are the tail's steps, their lights blinking another way. Read in the listing: `docs/FINDINGS.md`, "128 steps as two patterns played as one". **Sidelined (2026-10-16, on request), after he asked how it differs from one true long pattern: tracks shorter than 64 restart at the seam, a cue lands at step 64, two sets of settings, likely the trig conditions that count loops.** The play side is built: the long image (above), in `build/images/`, never on the unit. Still to do: the tail's swing, length and mutes from n; the step pages by page, the page lights and keys (not read).

**The right channels moved the way stock moves its own: built, the dma image, not on the unit.** Read "The right channels by a hardware transfer" under Stereo, and `docs/FINDINGS.md` of the same name. Still open if it works: the feed's 70 word cycles a block could go the same way.


Asked for by the maintainer on 2026-10-07 ("definitely gonna want to add this"), picked from a list of what the audio CPU's spare code room could hold. None is designed yet; the sizes are guesses. Audio CPU room: about 4 KB (`python -m tools.deadcode 7`), so all five fit together. **That was 2026-10-07. After the stereo image 442 bytes of those are left, in four runs of 108 to 118. Stock Twinshot's own code, which nothing reaches in our images, is 1,344 more, 830 of them in one run: the maintainer gave it up on 2026-10-10 ("we dont need teinshot anymore do we"). 1,786 bytes in all (`docs/MEMORY_MAP.md`). 2026-10-11: the stereo image's second build takes Twinshot's larger run for its sums (790 of 830 bytes). The third build takes the other run too (412 of 514 bytes). Left for an image that is kept: three small runs of 108, 108 and 118 bytes, about 100 in that run and 70 in the render's. Time stretch will not fit without the other machine. The maintainer offered another machine's room the same day ("we cqn sratch another machine as well"): not needed yet, and worth asking for when time stretch is built.**

| What | Guess | Needs a control | Open questions |
|---|---|---|---|
| Crossfade at the loop seam | 200 B | no, if the length is fixed | **built as fades either side of the seam (the fade image), and as a true crossfade (the cross image, 2026-10-12, 600 bytes)** wherever there is sound before the loop's start or after its end. A loop of a whole take still dips: for that the recorder would have to keep a little after the note, and the drive would have to carry it |
| Fade at start and end | 100 B | no | **built (the fade image)**: only where the region's end is inside the sample |
| Scrubbing: STRT read while the note plays | 150 B | no | **LEN acts while a note plays (the len image), and a loop's next pass begins where STRT is (the live image)**. The sound following STRT fluttered on the unit, the region moving under the sound ripped short loops: both taken out |
| Cleaner pitch shifting | 1.4 KB with its table | no | **Built (the pitch image), 16 frames and 32 rows blended. Asked for (on request.** Measured in a model of the present linear interpolation: a 6 kHz part of a sample pitched down has everything else 30 dB under it, 20 dB at 10 kHz. 4-point interpolation gets 44 and 29, not enough. A windowed sinc of 12 or 16 taps with 32 phases blended gets 78 to 95 and 81 to 86. Costs instructions per frame: measure against the 10,506 budget |
| Time stretch: speed apart from pitch (**built: the stretch image, 2026-10-22**, KEYS CHST/SLST and SPD in PTIM's place) | 800 to 1,200 B | **yes** | the heaviest in instructions. **The maintainer's word (2026-10-16): two taps on a stretched voice** (priced: P about 90, 93 with WSOLA, eight stereo pitched; FINDINGS, "Time stretch priced"); six stays for every other voice. All eight knobs are taken, so it needs a place on the sampling page (slot 24 is REC's lock now) |

The sampling page, as the maintainer cut the list on 2026-10-10: "level meter is the only essential", and not in a knob's place: "either on the bottom or the right side of the screen, with just a line tracking the volume, like Electron does on their compressor UI". Length in bars is dropped ("we can record with the trig length"), monitor needs no control ("prollty fine always on for now"), normalize is a maybe, the waveform is "a nice to have but back of the list". Save from the page, more sources and threshold were not spoken of. For the meter, read in the listing and not run: a filled rectangle is `0x400f7fb6(surface, x0, y0, x1, y1, colour)` (0 clears, 1 sets, negative inverts; the text routine uses it), the redraw request `0x400ffe22` is two flag bytes and nothing else, so the feed can ask for one, and the feed already reads the frame buffer the level comes from. **The meter and more sources are built (the meter image, not flashed). He then asked for saving a take to the drive from the page, the takes alone and not the project: built (the save image, not flashed).**

REC gain and a record threshold (on request. So: the lower row's second and third places, knobs F and G, where the probe image drew its two numbers. Not built. Both look like main CPU work only: the feed already turns the source into 16 bits a block and already measures its level for the meter, so a gain goes in before the conversion, and a threshold can hold the feed's blocks back until the level is there (the sound engine's take waits for blocks). Not proven. Like DEST they would be the page's own settings unless they are made parameters: not saved with the project and not lockable. A lower-row place has no room for a name under it (the meter's bar is there), so the value has to say what it is. Normalize is still a maybe.

On the maintainer's list since 2026-10-12, wishes and not orders, not looked into: **trigs from a long sample's transients** ("so that when a long sample is playing that only has one trig ... the transients from the audio file generate trigs for the filter and LFO to use"). The pattern mutes (purple) as solos, on that list too, are **built: the solo image**, read "The pattern's mutes as solos". **Takes written when a pattern is saved**, on the maintainer's order the same day ("in the SAVE box's place"), are **built: the ptn image**, for a whole pattern saved to the project and for nothing less, as he then chose; read "Saving the takes with a pattern". Also possible and not asked for: the right-hand slots played as mono samples of their own at SMPL 33 to 64, which would give back the 64 single slots the mode image gave up.

**Slices from a sample's transients, and the keys' switch** (maintainer, 2026-10-13; **the filter's half built: the hits image, read "Hits that start the filter's envelope"; the slices and the switch built 2026-10-16, the slice image: `docs/FINDINGS.md`, "The slice image"**. Answered by it: STRT is the slice's, P sits on G):
- The transient trigs may go to the filter alone: "wwhata bout transitent trigs just hitting the filter no the lfo".
- The transients are found by a scan ahead of the note, so they are slices too: "yea id wanr the scan i thihnk so we could use them as slices with the keyboard for sample chop".
- The switch, in P's place, knob H of the sampling page: "the last slot on the sample page where the cpu meter is now could be the elektron setup where its a keyboard or a numberd slice, so i can sewitch that way between pitch and chopped samples being played on the keyboard for tht track". The keys play the sample's pitch, or its slices by number. A plain knob a track; a step's slice is its note, so it locks as a note does.
- Read for it and not built on: the multimode filter is handed a trig of its own, a track a call (`tools/audiomap.py`, `STAGE_FILTER`), apart from the amp's, so a trig for the filter alone has a place. **Wrong (2026-10-14): that trig only clears the filter's memory; the envelope runs on the main CPU (`0x400965a4`, once a block), and a trig handed to it alone starts it again with FENR off, CONFIRMED in emulation** (`docs/FINDINGS.md`, "The filter's envelope is the main CPU's"). A track's word in the sampling page's box (`engine/sampler.h`, `dest[8]`: 16 bits for a number to 63) has bits to spare, so the switch needs no new place in the window; what `DEST_SMPL` takes of the word is not looked at.
- Guesses: the scan 200 to 250 bytes, the keys 100 to 150, the filter's trig about 100; a scan about 2 of the meter's points for about a second a long sample, nothing after.
- His answers, the same day: where a scan finds nothing the keys play 16 even slices ("1 yes"); "len should shorten slice"; and the filter trigs' control: "filtter transirtent trigs should go on the second paeh of the filter which has empty boxes there", "could replace env delay if it needs to i dont like tht contorl".
- The filter's envelope delay is the Filter record DEL, knob slot 31, 0 to 127 (`tools/params.py`; a track's word at params + 90, inside what `STAGE_FILTER` is handed from params + 82). A real parameter: taken over on a sampler track it locks, takes an LFO and is saved with the pattern, where a knob of ours in an empty box does none of the three and stock's filter page has never been hooked. The plan, not built: 0 is off, higher lets softer hits through (so a scan keeps each marker's strength), and the engine puts 0 where stock's filter reads the delay. Read since (2026-10-14): the audio CPU never has DEL; the main CPU's envelope reads it, so it is put to 0 there, around that call. Not looked at: the knob's name, which is every machine's (it may still read DEL on a sampler track). A pattern saved with DEL above 0 on a sampler track would have the trigs on.
- Beside it in the records: FENR, slot 36, 0 or 1, the filter envelope's reset: it need not be on for a trig to start the envelope again; on, the envelope starts from nothing (CONFIRMED in emulation, 2026-10-14).
- Open: what STRT does to a slice; where P is shown once its box is the switch's.
- After sample rate reduction, by the maintainer's order. Time stretch after these is advice, not the maintainer's word.

**Mono and stereo samples sharing the slots** (maintainer, 2026-10-12): **built, the pack image**, read "Mono samples at the back". On request. What the image does of that: the two kinds share the 64 slots from opposite ends, in any split down to 16 stereo and 32 mono. **What it does not, and he may have meant:** the unit choosing the place (a mono take going to the next free slot from the back and a stereo one to the next free pair from the front, by what MODE says). Not built because a trig that records again, or a step's REC that comes round every bar, would take a new place each time and fill the bank: it needs a rule for when a take is a new one, which is his to say. Also not: more than 32 mono samples by their own numbers.

**SMPL that stops only on real samples** (on request. Put to him as three ways, he chose: **the knob skips, with one free spot of each kind**, and **first, before the rest of the maintainer's order**. **Built, the stops image (2026-10-12, not on the unit): read "SMPL stops only on samples".** What it was to be, as written before it was built:
- Turning SMPL on the first page stops at: the stereo places that hold a sample, then the lowest stereo place that is free, then the highest single slot that is free, then the single slots that hold a mono sample. Nothing else. The reversed half of the knob the same, mirrored.
- The free spot is where the next take of that kind goes, so he places takes himself and the place is one click past his last sample. A step that records every bar goes over the same spot: nothing is eaten.
- A number keeps its meaning. The sound engine plays whatever number it is given (an old pattern, a lock, an LFO): only the knob's travel skips. DEST still reaches every number.
- **What says which kind a slot holds** (the number said it on the pack image, and a number that is skipped cannot): the plan is the slot's length. Odd: a mono sample of a single slot. Even: it belongs to its stereo place. Empty: free. A single slot's take would be one frame short of its whole blocks, a mono take in a stereo place would leave two frames in its second slot and not one, and `make samples PACK=1` would make mono files odd and stereo files even. Lengths came off the maintainer's unit exact (a kept take pulled with Transfer, 250,400 frames, hardware log 2026-10-08); for files sent to the unit it is not shown. Names were the other way, and a kept take's name did not read right on the unit that day, unexplained: not built on.
- The sound engine alone knows a take that is not saved, so it would say what each slot holds (filled, odd) in the shared window, and the main CPU would read that when the knob is turned. Not designed further, and nothing of it is proven.
- **As built:** all of the above, and one thing more: a slot of exactly one frame is taken for the mode image's mono take, its second slot, and is no stop. Not shown on the unit: that a file of an odd number of frames sent with Transfer is a slot of an odd number of frames.

**A crossfade for a loop of a whole take** (the recorder keeping a little after the note): the maintainer, 2026-10-12, "doesnt seem necesrry for bar length blend for now". Not to be built.

Room on the audio CPU after the stops image (2026-10-12): **218 bytes in 17 pieces, the largest 30.** After the pack image: 300 bytes in 18 pieces, the largest 44 (318 after the cross image). The mode image made 300 by dropping the chained slots' code and 136 by holding the table's twelve numbers a row and not its sixteen; the crossfade took 600; the pack image took 18, with the take's routine written by hand. Nothing more of any size fits without another machine's room. **The maintainer again, 2026-10-12, while the pack image was being fitted: "if we need more room we can scrap a stock machine".** Not needed for it. It will be for time stretch: which machine is his to say, and what each would give has not been measured.

One-track stereo (a stereo sample on one track, 8 at once): **built (the stereo image, 2026-10-10). Its first build on the unit, 2026-10-11: fine at a sample's own pitch, distorted with eight pitched; the second build, cheaper when pitched, works on the unit (2026-10-11).** The maintainer asked on 2026-10-09 whether it can be had "with no compromise on quality": each channel goes through the unit's own stages at full width, as a track of its own would. Read "Stereo on one track" and `docs/STEREO.md`.

Two limits that are not code room:
- Controls. The page has eight knobs and they are in use. A feature that needs its own knob waits for a second page (main CPU screen work) or takes a value of MODE or LOOP, which the maintainer does not want stacked.
- Instructions per block. The worst case of the present engine is already near the budget (What it costs). Interpolation and stretch both add per-frame work.
