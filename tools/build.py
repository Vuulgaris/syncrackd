"""Build the patched OS image into build/images/.

python -m tools.build firmware/path/to/Syntakt_OS1.42.syx          # audio CPU only
python -m tools.build firmware/path/to/Syntakt_OS1.42.syx full     # plus the main CPU patches
python -m tools.build firmware/path/to/Syntakt_OS1.42.syx rec      # full, plus the recorder
python -m tools.build firmware/path/to/Syntakt_OS1.42.syx big      # rec, plus sample slots of 1 MB
python -m tools.build firmware/path/to/Syntakt_OS1.42.syx keep     # big, plus takes kept on the +Drive
python -m tools.build firmware/path/to/Syntakt_OS1.42.syx double   # keep, plus twice the samples loaded
python -m tools.build firmware/path/to/Syntakt_OS1.42.syx screen   # double, plus names and words on screen
python -m tools.build firmware/path/to/Syntakt_OS1.42.syx page     # screen, plus a second page behind SYN
python -m tools.build firmware/path/to/Syntakt_OS1.42.syx load     # page, plus samples put back when a project is loaded
python -m tools.build firmware/path/to/Syntakt_OS1.42.syx bank     # load, plus three sample banks, one a project
python -m tools.build firmware/path/to/Syntakt_OS1.42.syx fade     # bank, plus fades where a sample is cut into
python -m tools.build firmware/path/to/Syntakt_OS1.42.syx mute     # fade, plus a mute that leaves a track's trigs running
python -m tools.build firmware/path/to/Syntakt_OS1.42.syx len      # mute, plus LEN that acts while a note plays
python -m tools.build firmware/path/to/Syntakt_OS1.42.syx live     # len, plus STRT: a loop's next pass begins where the knob is
python -m tools.build firmware/path/to/Syntakt_OS1.42.syx floor    # live, plus LEN that stops at 3
python -m tools.build firmware/path/to/Syntakt_OS1.42.syx reclock  # floor, plus a step's REC as a lock of its own
python -m tools.build firmware/path/to/Syntakt_OS1.42.syx pitch    # reclock, plus a clean sound at any pitch
python -m tools.build firmware/path/to/Syntakt_OS1.42.syx meter    # pitch, plus more sources and a level meter on the sampling page
python -m tools.build firmware/path/to/Syntakt_OS1.42.syx save     # meter, plus SAVE on the sampling page: the takes to the drive
python -m tools.build firmware/path/to/Syntakt_OS1.42.syx safe     # save's main program on the reclock image's sound engine
python -m tools.build firmware/path/to/Syntakt_OS1.42.syx stereo   # save, plus a stereo sample on one track
python -m tools.build firmware/path/to/Syntakt_OS1.42.syx gain     # stereo with the sum of twelve, plus a record gain
python -m tools.build firmware/path/to/Syntakt_OS1.42.syx mode     # gain, plus a sample that is mono or stereo by itself
python -m tools.build firmware/path/to/Syntakt_OS1.42.syx cross    # mode, plus a loop's end blended into its start
python -m tools.build firmware/path/to/Syntakt_OS1.42.syx pack     # cross, plus mono samples in single slots at the back
python -m tools.build firmware/path/to/Syntakt_OS1.42.syx stops    # pack, plus SMPL that stops only on real samples
python -m tools.build firmware/path/to/Syntakt_OS1.42.syx solo     # stops, plus the pattern's mutes as solos
python -m tools.build firmware/path/to/Syntakt_OS1.42.syx multi    # alock, plus several tracks recording at once
python -m tools.build firmware/path/to/Syntakt_OS1.42.syx srr      # multi, plus sample rate reduction; SY SWARM is its room
python -m tools.build firmware/path/to/Syntakt_OS1.42.syx gear     # srr, plus the sampling page's knobs and SMPL turning as stock's do
python -m tools.build firmware/path/to/Syntakt_OS1.42.syx ptn      # solo, plus the takes written with a whole pattern's save
python -m tools.build firmware/path/to/Syntakt_OS1.42.syx feed     # ptn, with the record feed made cheap on the main CPU
python -m tools.build firmware/path/to/Syntakt_OS1.42.syx once     # feed, plus REC's third setting: ONCE
python -m tools.build firmware/path/to/Syntakt_OS1.42.syx soloknob # once, with the purple keys stock's again and a solo on the sampling page
python -m tools.build firmware/path/to/Syntakt_OS1.42.syx xfade    # soloknob, with a crossfade on the sampling page in MODE's place

"full" adds, in section 3 (OS 1.42 only): the sampler's knob names, ranges and defaults, and the mixer link that makes
a stereo pair's right-hand track follow the left one's volume, sends and pan. See tools/build_main.py.

"rec" is "full" plus the recorder: MODE 2 and 3 record the main mix or the external input into a slot. More code on
both CPUs (engine/recfeed.c, and engine/sampler.c built with RECORDER). The other two variants do not contain it.

"big" is "rec" with larger sample slots: 10.9 s where stock has 5.46 s, on a part of the +Drive stock leaves unused.
It changes the code that finds a slot on the drive and the code that builds the sample pool at boot
(tools/build_main.py, engine/poolstage.c). Samples on the drive have to be loaded again after it, and after going
back.

"keep" is "big" plus takes that last: saving a project also writes every take that is not on the +Drive yet into its
two sample slots (engine/keeptakes.c, and engine/sampler.c built with KEEP). The other variants do not contain it.

"double" is "keep" plus twice the samples in memory: the pool goes to the audio CPU in two halves through the one 32
MB block (engine/poolhalves.c, and one call in the task that sends it). Up to 64 MB loads where the others stop at 32.
It changes code the unit boots through.

"screen" is "double" plus what three knobs read: SMPL shows the stereo sample's name when MODE counts stereo samples,
and LOOP and MODE show words (engine/knobtext.c). Main CPU only.

"page" is "screen" plus the sampling page: a second page behind the SYN key on a sampler track that starts and stops a
take (engine/recpage.c on the main CPU, with a few lines more in the feed and in the audio CPU's recorder, built with
PAGE).

"load" is "page" plus the first sample loading while the unit runs: after LOAD PROJECT, every slot that holds a take
the +Drive does not have gets the drive's samples back (the load half of engine/keeptakes.c, and engine/sampler.c
built with LOAD). The drive is only read.

"bank" is "load" plus three sample banks: the drive holds three sets of 64 slots, every access to a sample's sector
goes to the set that is loaded, a project is saved with a bank and loading it loads that bank (engine/banks.c). Main
CPU only. It changes where every read, write and erase of the drive passes, and writes one sector of its own at 196
MB.

"fade" is "bank" plus fades in the sound engine: a note that starts or ends inside its sample fades in or out, and a
forward loop fades out and in around its seam (engine/sampler.c built with FADE). Audio CPU only, and the first image
whose engine does not sound as the others'.

"mute" is "fade" plus a mute that only silences: a muted track's trigs still fire, so its notes run, its locks are
applied and its takes are recorded, unheard, and the sound is there the moment the mute comes off (engine/mutetrig.c).
Main CPU only, in the routine that runs every block.

"len" is "mute" plus LEN that acts while a note plays: the pass that is playing ends as far from where it began as the
knob says, from the block the knob moves in (engine/sampler.c built with LIVE). STRT stays the note's own. Audio CPU
only, in two more runs of code nothing reaches.

"live" is "len" plus STRT: a loop's next pass begins where the knob has the start by then (LIVE_STRT). Nothing is done
to the pass that is playing. Audio CPU only.

"floor" is "live" plus a least LEN of 3: the knob stops there and the engine takes no less from an LFO, a lock or an
older pattern (FLOOR). One number in LEN's descriptor and two tests in the engine.

"reclock" is "floor" plus a step's REC as a lock of its own, on a knob slot no knob uses, where it was a lock of MODE
and locked the stereo switch and the source with it (engine/recpage.c, engine/recfeed.c and engine/sampler.c built
with RECLOCK). Both CPUs.

Audio CPU only, in five more runs of code nothing reaches, and a copy of the table in free memory.

"meter" is "pitch" plus the sampling page's level meter and more sources: SRC is a number in MODE's value (the main
mix, the external input, each of the twelve tracks, the FX track's return, the delay and reverb), and a bar along the
bottom of the screen follows the level of the source (engine/recfeed.c, engine/recpage.c and engine/knobtext.c built
with METER). Main CPU only, in two more runs of code nothing reaches; the audio CPU's code is the pitch image's.

"save" is "meter" plus SAVE on the sampling page: a turn of its fifth knob writes the takes that are not on the +Drive
yet, and not the project, in a job of ours on stock's own runner of jobs (engine/keeptakes.c and engine/recpage.c
built with SAVE). Main CPU only, in the runs it has.

"safe" is the save image's main program with the reclock image's audio program: the meter, the sources and SAVE
without the pitch change. The meter and save images change nothing on the audio CPU, which reads MODE's two low bits
and nothing above them, so the two halves are each as tested.

"stereo" is "save" plus one-track stereo: a stereo sample's right channel stays with its track, goes through the audio
CPU's four stages after the left ones (engine/sampler.c built with ONETRACK, in four more runs of code nothing reaches
and one more call of the interrupt's), crosses in two unused stretches of the window, and is handed to the mixer's
right-hand passes in a second set of buffers (engine/rightfill.c, seven operands of the mixer and one call of the
routine that runs every block). The next track is its own again. Both CPUs.

"gain" is "stereo" with a pitched frame summed from twelve frames, plus a record gain: knob F of the sampling page, 0
to 24 dB, put on before a take is made 16 bits (engine/recfeed.c and engine/recpage.c built with GAIN).

"mode" is "gain" plus a sample that is what it is: MODE's stereo switch no longer says how a track plays. SMPL always
counts the 32 samples, and one is stereo when its second slot is as long as its first, mono when not (engine/sampler.c
and engine/knobtext.c built with AUTO). The switch says what a take is and sits on the sampling page, knob G; a mono
take is the source's two sides added and halved (engine/recfeed.c). While the images are being built it also carries
the time image's routine, and shows the audio CPU's peak load in the sampling page's last place. Both CPUs.

"cross" is "mode" plus a crossfade at a loop's seam: the pass's last 256 frames go down as the 256 before the loop's
start come up, or, with nothing before the start, the same a little later on both sides. The blended frames are
written out ahead in free memory, eight a block (engine/sampler.c built with XFADE). Audio CPU only.

"pack" is "cross" plus single slots at the back: SMPL 1 to 32 are the stereo samples as they were, and 33 to 64 are
the slots of those numbers, each a mono sample whatever its neighbour holds. A take sent to one is the source's two
sides added and halved, in that slot alone. Stereo samples from 1 up and mono ones from 64 down meet where they meet
(engine/sampler.c built with PACK). Both CPUs.

"stops" is "pack" plus a SMPL knob that stops only on real samples and one free spot of each kind: the stereo places
that hold a sample, the lowest free one, the highest free single slot, and the single slots that hold a mono sample. A
slot's length says which kind it holds (odd: a single slot's mono sample), so a single slot's take is a frame short of
its blocks and a mono take leaves two frames in its second slot; the audio CPU says two bits a slot in the window,
sixteen slots a block (engine/stub.S), and the page reads them when the knob is turned (engine/recpage.c built with
STOPS). A number keeps its meaning: only the knob's travel skips. Both CPUs.

"solo" is "stops" plus the purple pattern mutes as solos: a track whose key is on in the pattern is heard and, while
any is, the other eleven are silenced, as a mute silences them (trigs still fire). The pattern's own word is what it
was; the four places that store the two engines' copies of it store the tracks its solos silence, and the keys are lit
for a track that is heard (engine/solo.S). The FX track's bit is a mute as it was. A song row's mutes go the same way.
Main CPU only: section 7 is the stops image's.

"ptn" is "solo" plus the takes written when a whole pattern is saved to the project: the two calls of stock's pattern
save behind the pattern menu's SAVE TO PROJ, WHOLE PATTERN go to a routine of ours that calls stock's and then starts
the job the save image's SAVE box started (engine/keeptakes.c, ptn_keep). The box is gone: the sampling page's fifth
place is empty and its knob turns nothing; FAIL is written there after a save that did not get every take onto the
drive, until one does. A take that changed while it was written no longer ends the run. The temp area's save and the
kit's and sequence's own are stock's. Main CPU only: section 7 is the stops image's.

"feed" is "ptn" with the record feed made cheap: the routine that writes a block of a take into the ring, which runs
in the main CPU's per-block interrupt while a track has REC on, is hand-written (engine/feed.S) with no call a sample
and no divide a sample. What a take holds is the ptn image's to the bit. The sampling page asks which step is held
once a drawing, and FAIL is gone from its fifth place. Main CPU only: section 7 is the stops image's.

"once" is "feed" with a third setting of REC on the sampling page: OFF, ON, ONCE. A step locked to ONCE records as a
step locked on does and is spent where the sequencer plays it; the main task then takes its lock off with stock's
routine. The track's own REC at ONCE records from the next step the sequencer plays on it, once. Three places of
stock's are changed (engine/once.S). Main CPU only: section 7 is the stops image's.

"soloknob" is "once" with the solo image taken out and a solo put on the sampling page: the purple keys are stock's
pattern mutes again (none of the solo image's seven places is changed), and knob E is the track's solo, a bit a track
in a long of ours, off at every start. With any solo on, every track with none is silenced as a mute of ours silences,
and no mute counts. Main CPU only: section 7 is the stops image's.

"xfade" is "soloknob" with a crossfade on the sampling page's knob G, where MODE was: 0 to 127, the track's own, 0 at
every start. Every other track is turned down by it, its volume as the mixer is shown it times (127 - x) / 127 and an
analog voice's level words by the square of that, and is silent at 127. A take at a stereo place is always stereo:
MODE's lowest bit is set in the block that is sent. Main CPU only: section 7 is the stops image's.

"gfade" is "xfade" with one crossfade for the whole unit: every sampling page shows and turns the same number, held in
the place of the track that last turned it. Main CPU only, the page's code alone.

"dma" is "gfade" with the right channels of stereo tracks brought out of the window by the transfer controller, as
stock brings the left ones, and not by the CPU's own reads inside the per-block interrupt: two channels of group 0,
started at the per-block routine's first call and waited for before the mixer, into a second set of buffers that is in
on-chip memory. From a start the transfers are checked against the CPU's reads for a second and are given up if they
differ or do not end; the letter before the load on the sampling page says which (C, H, X). Main CPU only: section 7
is the stops image's (engine/rightdma.c).

"apage" is "dma" with the sampling page's solo and crossfade on the analog tracks: SYN again on tracks 9 to 12 opens a
second page with SOLO on knob E and the crossfade on knob G, the other places empty. The solos' long keeps twelve bits
and the crossfade is twelve numbers; the mixer link and the analog mute go by all twelve. Main CPU only.

"slock" is "apage" with a sampler track's solo lockable to a step: knob E with a step held makes a lock on knob slot
17 at one of two marks, there only where the step is not to do as the track does. The analog mute works out each
block's solos from the knobs' long and the marks where a trig's locks are written, and the mixer link goes by them.
The analog tracks' solo is not lockable. Main CPU only.

"alock" is "slock" with an analog track's solo lockable to a step as well: its lock is on knob slot 26, the last of
the ten words that are a track's machine, which no analog machine has a knob on. The same two marks, counted only on a
track that holds an analog machine. Main CPU only.

"multi" is "alock" with several tracks recording at once, each from its own SRC into its own DEST: the ring's eight
blocks are a block a track, every track that says record is fed its own, and the audio CPU takes them before the voice
loop (engine/sampler.h, MULTI). Both CPUs: the first change to section 7 since the stops image.

"srr" is "multi" with sample rate reduction: the sampler's own frames held, before every stage of stock's, by a knob
in the first page's sixth place that locks and takes an LFO. It is MODE's parameter, freed: a track's REC and SRC are
the track's own word on knob slot 24, signed, made from an old pattern's MODE the first block it plays (one way). SY
SWARM's code is the room, and a track left on it plays nothing (engine/sampler.h, SRR). Both CPUs.

"gear" is "srr" with the sampling page's knobs, and SMPL, turning as stock's own do: a turn goes through stock's three
knob routines, by the plain knob's feel (SMPL: the sample picker's), where every tick was a whole step. The
crossfade's knob is as it was. Main CPU only (engine/recpage.c, GEAR).

"stay" is "gear" with a step's ONCE, and a track's, spent only where the sequencer plays a step: stock also runs the
routine that plays a step to bring a changed track up to date, on the step the sequencer is on, and that used a ONCE
up, the first step's as it was made while the sequencer stood. Main CPU only (engine/once.S, STAY).

"eight" is "slim" with a pitched frame summed from eight frames, in "six"'s place: six was too much ("too much
filtering"). Audio CPU only (engine/sampler.h, EIGHT).

"six" is "slim" with a pitched frame summed from six frames, not twelve. Audio CPU only (engine/sampler.h, SIX).

"slim" is "trim" for less again, the sound the same to the bit: the pitched sum's two tests worked out once a run.
Audio CPU only (engine/sampler.h, SLIM).

"fltr" is "xshare" with LFO.T and FLT.T on FLTR2's G and H on a sampler track (FLTRPAGE in engine/recpage.c; SOLO and
REC stay on the TRIG page), and the phone's load query, 0x63 answered by 0x64 (KNOWS in engine/phone.c). Main CPU
only. "xshare" is "xknob" with knob D the pattern's one crossfade on every track: it shows it, and a turn on any track
carries the amount over (XSHARE in engine/recpage.c, knobtext.c). Main CPU only. "xknob" is "box" with the crossfade
on the first page's knob D in DEC's place and slot, kept with the pattern, one track's at a time, and DEC no longer
read (XKNOB in engine/sampler.c, amute.c, recpage.c, knobtext.c). Both CPUs. "box" is "switch" with the dotted boxes
around SOLO and REC on the TRIG page wiped, and REC OFF or ONCE on both pages (engine/recpage.c, BOX). Main CPU only.
"switch" is "trig" with a hit's steps from the slot's own loudest frame (engine/sampler.c, HITPEAK) and SOLO and REC
drawn as stock's switch on the TRIG page (engine/recpage.c, SWITCH). Both CPUs. "trig" is "phone" with STRT and LOOP,
LEN and SRR changed over on the first page, the track holding the crossfade heard through a global mute, a hit's
loudness in finer steps (engine/sampler.c, HITCURVE), and SOLO and REC on a sampler track's TRIG page in LFO.T's and
FLT.T's places, SOLO off the sampling page. Both CPUs. "phone" is "six" with the unit asking the phone at LOAD PROJECT
which of the project's bank's slots it changed, waiting for its answer (a timeout and stock's load as the fallback),
and loading only those slots into the audio CPU as well as the takes the load restores. Main CPU only (engine/phone.c,
PHONE). "trim" is "hitui" with a pitched note, a fade and a loop's blend for less of the audio CPU's block: the
pitched sum's frames taken with the next in their low half, the fade a frame in fewer steps, and a loop's blend kept
from note to note while its frames are as they were. Audio CPU only (engine/sampler.h, TRIM).

"hitui" is "hits" with the filter pages saying what DEL is on a sampler track: HITS by its knob and in the pop-up, and
no delay in FLTR1's picture of the envelope. Main CPU only (engine/hits.c, HITUI).

"hits" is "lap" with a long sample's hits starting the filter's envelope again, as a trig of its own, through DEL on a
sampler track: the audio CPU finds them and says which tracks reach one, the main CPU hands the envelope the trig.
Both CPUs (engine/sampler.h, HITS; engine/hits.c).

"lap" is "tail" with five more readings of the timer in the profile's record, on the way to the mixer: a tool, to say
what the half of a block before the mixer is spent on. Main CPU only (engine/rightdma.c, LAP).

"tail" is "pre" with a one-shot faded out before its far end wherever that is: a take played to its own end clicked
there. Audio CPU only (engine/sampler.h, TAIL).

"pre" is "soft" with a take's sources read before the mixer: a digital track and the FX track's return record, and
show on the meter, while they are muted, and a track's take no longer follows its LEVEL and AMP VOL. And the FX
track's mute silences its return. Main CPU only (engine/recfeed.c, PRE).

"soft" is "prof" with a note that starts on a loud frame faded in, as one that starts inside the sample is: a take
begins wherever its source was, and at STRT 0 it clicked. Audio CPU only, in SY SWARM's room (engine/sampler.h, SOFT).

"prof" is "stay" with a profile of the main CPU, kept in every image after it: the per-block interrupt's start and end
and three places in it by the chip's first timer, and what the interrupt stopped (its PC, SR, stack pointer and seven
longs of its stack), a record of 32 words a block. It is off at every start. The sampling page's last knob turns it
on, and then a sampler track whose SRC is SENDS takes the record in place of sound; tools/prof_read.py reads the
take's file. Main CPU only (engine/prof.S).

Checks, all of which must pass before a file is written:
1. the input is a pinned official file, every section hash known
2. every patch site holds the stock bytes it expects
3. no patch targets the bootstrap or the updater, or any section but 3 and 7
4. the built file decodes cleanly: packet checksums, content checksum, layout
5. it differs from the official file only inside the declared regions,
and the bootstrap and updater are stored byte for byte as before
6. the sections decoded back out of the built file are exactly what was intended

"""
import os
import sys

from . import audiomap as m
from . import build_engine, build_main, fw
from . import mainmap as mm

OUT = os.path.join("build", "images", "Syntakt_OS%s_sampler%s.syx")
LAST_PATCHES = []


PAD7 = False  # the pad7 tool (main): section 7 grown to fw.GROW[7] with zeros, past its end only


def build(path, log=print, full=False, rec=False, big=False, keep=False, double=False, screen=False, page=False, load=False,
          bank=False, fade=False, mute=False, live=False, len_live=False, floor=False, reclock=False, pitch=False, meter=False, save=False, safe=False, probe=False,
          stereo=False, timed=False, twelve=False, gain=False, auto=False, cross=False, peak=True, pack=False, stops=False, solo=False, ptn=False,
          feed=False, once=False, soloknob=False, xfade=False, prof=False):
    official = fw.load(path)  # 1
    stock7 = official.section(7)
    soloknob = soloknob or xfade  # xfade: the soloknob image with a crossfade on the sampling page (main CPU only)
    once = once or soloknob  # soloknob: the once image with a solo on the sampling page (main CPU only)
    feed = feed or once  # once: the feed image with REC's third setting (main CPU only)
    ptn = ptn or feed  # feed: the ptn image with the record feed made cheap (main CPU only)
    solo = solo or ptn  # ptn: the solo image with the takes written when a whole pattern is saved (main CPU only)
    stops = stops or solo  # solo: the stops image with the pattern's mutes as solos (main CPU only)
    pack = pack or stops  # stops: the pack image with a SMPL knob that skips what is no sample
    cross = cross or pack  # pack: the cross image with single slots at the back
    auto = auto or cross  # cross: the mode image with a loop's end blended into its start
    gain = gain or auto  # mode: the gain image with a sample mono or stereo by itself
    twelve = twelve or gain  # gain: the stereo image with the sum of twelve, and a record gain
    stereo = stereo or timed or gain  # time: the stereo image with the audio CPU's load on the sampling page
    safe = safe or probe  # probe: the safe image with three numbers on the sampling page
    save = save or safe or stereo  # stereo: the save image with a stereo sample on one track
    meter = meter or save
    pitch = (pitch or meter) and not safe  # safe: the sound engine stays the reclock image's
    reclock = reclock or safe
    reclock = reclock or pitch
    floor = floor or reclock
    live = live or floor
    len_live = len_live or live
    mute = mute or len_live
    fade = fade or mute
    bank = bank or fade
    load = load or bank
    page = page or load
    screen = screen or page
    double = double or screen
    keep = keep or double
    big = big or keep
    rec = rec or big
    full = full or rec
    patches, syms = build_engine.patches(stock7, rec=True, keep=keep, page=page, load=load, bank=bank, fade=fade, live=live, len_live=len_live,
                                         floor=floor, reclock=reclock, pitch=pitch, stereo=stereo, timed=timed, twelve=twelve,
                                         auto=auto, cross=cross, pack=pack, stops=stops, multi=xfade >= 7, srr=xfade >= 8, soft=xfade >= 12, tail=xfade >= 14, hits=xfade >= 16, trim=xfade >= 18, slim=xfade >= 19, six=xfade in (20, 22), eight=xfade == 21, curve=xfade >= 23, peak=xfade >= 24, xknob=xfade >= 26, slice=xfade >= 31, ring=xfade >= 32, allright=39 <= xfade <= 40, scan=xfade >= 46, norm=xfade >= 50, back=xfade >= 52, stretch=xfade >= 53, lock=xfade >= 54, scrub=xfade >= 55, slscrub=xfade >= 56, grain=xfade >= 57, spread=xfade >= 59, trap=xfade >= 65, letgo=xfade >= 69, handrec=xfade >= 81) if rec else build_engine.patches(stock7)
    if full:
        if official.version != "1.42":
            raise fw.GuardError("the main CPU patches exist for OS 1.42 only")
        more, main_syms = build_main.patches(official.section(3), rec=rec, big=big, keep=keep, double=double, screen=screen, page=page, load=load,
                                                 bank=bank, mute=mute, floor=floor, reclock=reclock, meter=meter, save=save, probe=probe, stereo=stereo,
                                                 timed=timed and not auto, gain=gain, auto=auto, peak=peak, pack=pack, stops=stops, solo=solo, ptn=ptn, feed=feed,
                                                 once=once, soloknob=soloknob, xfade=xfade, prof=prof)
        patches += more
        syms = dict(syms, **main_syms)
    global LAST_PATCHES
    LAST_PATCHES = patches  # for the story's trace, never the image
    sections, regions = fw.apply(official, patches)  # 2, 3
    if build_engine.TAIL:  # the back image: code past section 7's end
        grown = sections.get(7, stock7)
        sections[7] = grown + build_engine.TAIL
        regions.setdefault(7, []).append((len(grown), len(sections[7])))
    if PAD7:  # the pad7 tool: section 7 grown to its most with zeros
        grown = sections.get(7, stock7)
        sections[7] = grown + bytes(fw.GROW[7] - len(grown))
        regions.setdefault(7, []).append((len(grown), fw.GROW[7]))
    raw = official.build(sections)  # 3 again, at the container
    built = fw.verify(official, raw, regions)  # 4, 5
    for sid, data in sections.items():  # 6
        if built.section(sid) != data:
            raise fw.GuardError("section %d did not survive the round trip" % sid)
    if not full and len(raw) != len(official.raw):  # section 7 is stored raw
        raise fw.GuardError("file size changed")

    log("official  Syntakt OS %s  %s" % (official.version, fw.sha256(official.raw)))
    log("built     %d bytes  %s" % (len(raw), fw.sha256(raw)))
    for sid in official.ids:
        same = built.container.by_id(sid).stored == official.container.by_id(sid).stored
        note = "identical" if same else "CHANGED: %d bytes in %d regions" % (
            sum(a != b for a, b in zip(official.section(sid), built.section(sid))), len(regions[sid]))
        log("  section %d %-9s %s" % (sid, fw.NAMES[sid], note))
    for p in patches:
        log("  patch  section %d  %#010x  %4d bytes  %s" % (
            p.section, (m.BASE if p.section == 7 else mm.BASE) + p.offset, len(p.new), p.note))
    return raw, official, built, regions, syms


def main(path, variant="audio"):
    suffix = {"audio": "", "full": "_full", "rec": "_rec", "big": "_big", "keep": "_keep", "double": "_double",
              "screen": "_screen", "page": "_page", "load": "_load", "bank": "_bank", "fade": "_fade", "mute": "_mute",
              "len": "_len", "live": "_live", "floor": "_floor", "reclock": "_reclock", "pitch": "_pitch", "meter": "_meter", "save": "_save", "safe": "_safe", "probe": "_probe",
              "stereo": "_stereo", "time": "_time", "time12": "_time12", "gain": "_gain", "mode": "_mode", "cross": "_cross", "pack": "_pack",
              "stops": "_stops", "solo": "_solo", "ptn": "_ptn", "feed": "_feed", "once": "_once", "soloknob": "_soloknob", "xfade": "_xfade", "gfade": "_gfade", "dma": "_dma", "apage": "_apage", "slock": "_slock", "alock": "_alock", "multi": "_multi", "srr": "_srr", "gear": "_gear", "prof": "_prof", "stay": "_stay", "soft": "_soft", "pre": "_pre", "tail": "_tail", "lap": "_lap", "hits": "_hits", "hitui": "_hitui", "trim": "_trim", "slim": "_slim", "six": "_six", "eight": "_eight", "phone": "_phone", "trig": "_trig", "switch": "_switch", "box": "_box", "xknob": "_xknob", "xshare": "_xshare", "fltr": "_fltr", "tlsolo": "_tlsolo", "long": "_long", "slice": "_slice", "ring": "_ring", "mixtime": "_mixtime", "fast": "_fast", "rxoff": "_rxoff", "rxcap": "_rxcap", "copy": "_copy", "nodiv": "_nodiv", "allright": "_allright", "prewas": "_prewas", "cut": "_cut", "nofx": "_nofx", "xfix": "_xfix", "xcont": "_xcont", "xcarry": "_xcarry", "scan": "_scan", "scratch": "_scratch", "soloend": "_soloend", "eucl": "_eucl", "norm": "_norm", "atrig": "_atrig", "back": "_back", "stretch": "_stretch", "lock": "_lock", "scrub": "_scrub", "slscrub": "_slscrub", "grain": "_grain", "stsw": "_stsw", "spread": "_spread", "trans": "_trans", "next": "_next", "pbank": "_pbank", "kind": "_kind", "mirror": "_mirror", "trap": "_trap", "shadow": "_shadow", "sink": "_sink", "tune": "_tune", "letgo": "_letgo", "ask": "_ask", "axf": "_axf", "gainup": "_gainup", "onedest": "_onedest", "destnum": "_destnum", "fresh": "_fresh", "newproj": "_newproj", "wipe": "_wipe", "stream": "_stream", "evict": "_evict", "handrec": "_handrec", "firstrec": "_firstrec"}
    suffix["probe17"] = "_probe17"
    suffix["evtime"] = "_evtime"
    suffix["evrx"] = "_evrx"  # the same tool on the rxoff image
    suffix["tuneprobe"] = "_tuneprobe"
    suffix["slotprobe"] = "_slotprobe"
    suffix["pad7"] = "_pad7"
    if variant not in suffix:
        raise SystemExit("variant must be one of: %s" % ", ".join(suffix))
    named = variant
    if variant == "probe17":
        build_main.EXTRA_DEFS, variant = ("PROBE17",), "fltr"
    if variant == "tuneprobe":
        build_main.EXTRA_DEFS, variant = ("TUNEPROBE",), "tune"
    if variant == "slotprobe":
        build_main.EXTRA_DEFS, variant = ("SLOTPROBE",), "spread"
    if variant == "evtime":
        build_main.EVLAP, variant = True, "fast"
    if variant == "evrx":
        build_main.EVLAP, variant = True, "rxoff"
    if variant == "pad7":
        global PAD7
        PAD7, variant = True, "atrig"
    raw, official, _, _, _syms = build(path, full=variant == "full", rec=variant == "rec", big=variant == "big",
                                   keep=variant == "keep", double=variant == "double", screen=variant == "screen", page=variant == "page",
                                   load=variant == "load", bank=variant == "bank", fade=variant == "fade", mute=variant == "mute",
                                   live=variant == "live", len_live=variant == "len", floor=variant == "floor",
                                   reclock=variant == "reclock", pitch=variant == "pitch", meter=variant == "meter", save=variant == "save", safe=variant == "safe", probe=variant == "probe",
                                   stereo=variant == "stereo", timed=variant in ("time", "time12"), twelve=variant == "time12", gain=variant == "gain",
                                   auto=variant == "mode", cross=variant == "cross", pack=variant == "pack", stops=variant == "stops",
                                   solo=variant == "solo", ptn=variant == "ptn", feed=variant == "feed", once=variant == "once",
                                   soloknob=variant == "soloknob", xfade=(variant == "xfade") + 2 * (variant == "gfade") + 3 * (variant == "dma") + 4 * (variant == "apage") + 5 * (variant == "slock") + 6 * (variant == "alock") + 7 * (variant == "multi") + 8 * (variant == "srr") + 9 * (variant == "gear") + 10 * (variant == "stay") + 11 * (variant == "prof") + 12 * (variant == "soft") + 13 * (variant == "pre") + 14 * (variant == "tail") + 15 * (variant == "lap") + 16 * (variant == "hits") + 17 * (variant == "hitui") + 18 * (variant == "trim") + 19 * (variant == "slim") + 20 * (variant == "six") + 21 * (variant == "eight") + 22 * (variant == "phone") + 23 * (variant == "trig") + 24 * (variant == "switch") + 25 * (variant == "box") + 26 * (variant == "xknob") + 27 * (variant == "xshare") + 28 * (variant == "fltr") + 29 * (variant == "tlsolo") + 30 * (variant == "long") + 31 * (variant == "slice") + 32 * (variant == "ring") + 33 * (variant == "mixtime") + 34 * (variant == "fast") + 35 * (variant == "rxoff") + 36 * (variant == "rxcap") + 37 * (variant == "copy") + 38 * (variant == "nodiv") + 39 * (variant == "allright") + 40 * (variant == "prewas") + 41 * (variant == "cut") + 42 * (variant == "nofx") + 43 * (variant == "xfix") + 44 * (variant == "xcont") + 45 * (variant == "xcarry") + 46 * (variant == "scan") + 47 * (variant == "scratch") + 48 * (variant == "soloend") + 49 * (variant == "eucl") + 50 * (variant == "norm") + 51 * (variant == "atrig") + 52 * (variant == "back") + 53 * (variant == "stretch") + 54 * (variant == "lock") + 55 * (variant == "scrub") + 56 * (variant == "slscrub") + 57 * (variant == "grain") + 58 * (variant == "stsw") + 59 * (variant == "spread") + 60 * (variant == "trans") + 61 * (variant == "next") + 62 * (variant == "pbank") + 63 * (variant == "kind") + 64 * (variant == "mirror") + 65 * (variant == "trap") + 66 * (variant == "shadow") + 67 * (variant == "sink") + 68 * (variant == "tune") + 69 * (variant == "letgo") + 70 * (variant == "ask") + 71 * (variant == "axf") + 72 * (variant == "gainup") + 73 * (variant == "onedest") + 74 * (variant == "destnum") + 75 * (variant == "fresh") + 76 * (variant == "newproj") + 77 * (variant == "wipe") + 78 * (variant == "stream") + 79 * (variant == "evict") + 81 * (variant == "handrec") + 82 * (variant == "firstrec"), prof=variant in ("prof", "soft", "pre", "tail", "lap", "hits", "hitui", "trim", "slim", "six", "eight", "phone", "trig", "switch", "box", "xknob", "xshare", "fltr", "tlsolo", "long", "slice", "ring", "mixtime", "fast", "rxoff", "rxcap", "copy", "nodiv", "allright", "prewas", "cut", "nofx", "xfix", "xcont", "xcarry", "scan", "scratch", "soloend", "eucl", "norm", "atrig", "back", "stretch", "lock", "scrub", "slscrub", "grain", "stsw", "spread", "trans", "next", "pbank", "kind", "mirror", "trap", "shadow", "sink", "tune", "letgo", "ask", "axf", "gainup", "onedest", "destnum", "fresh", "newproj", "wipe", "stream", "evict", "handrec", "firstrec"))  # 3: dma, gfade with the right channels by a transfer
    out = OUT % (official.version, suffix[named])
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "wb") as f:
        f.write(raw)
    print("wrote %s" % out)
    try:  # the story: a trace and its player, under build/, never a gate
        from . import story
        print("story: %s" % story.record(named, official, raw, LAST_PATCHES, _syms, parent=list(suffix)))
    except Exception as err:
        print("story: skipped (%s)" % err)
    print("This file has only been tested in emulation. Flashing it is your decision and your step.")


if __name__ == "__main__":
    main(*sys.argv[1:3])
