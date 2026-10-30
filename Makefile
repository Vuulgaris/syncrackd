PY ?= .venv/bin/python

.PHONY: test setup render engine image image-phone image-full image-rec image-big image-keep image-double image-screen image-page image-load image-bank image-fade image-mute image-len image-live image-floor image-reclock image-pitch image-meter image-save image-safe image-probe image-stereo image-time image-time12 image-gain image-mode image-cross image-pack image-stops image-solo image-ptn image-feed image-once image-soloknob image-xfade image-gfade image-dma image-apage image-slock image-alock image-multi image-srr image-gear image-stay image-soft image-pre image-tail image-lap image-hits image-hitui image-trim image-slim image-six image-eight image-trig image-switch image-box image-xknob image-xshare image-fltr image-probe17 image-tlsolo image-long image-slice image-ring image-mixtime image-fast image-evtime image-rxoff image-evrx image-rxcap image-copy image-nodiv image-allright image-prewas image-cut image-nofx image-xfix image-xcont image-xcarry image-scan image-scratch image-soloend image-eucl image-norm image-atrig image-pad7 image-back image-stretch image-lock image-scrub image-slscrub image-grain image-stsw image-spread image-trans image-next image-pbank image-kind image-mirror image-trap image-shadow image-sink image-tune image-letgo image-ask image-axf image-gainup image-onedest image-destnum image-fresh image-newproj image-wipe image-stream image-evict image-handrec image-firstrec image-slotprobe samples stereo-sample stereo-check image-prof prof-read story check bundle single site

# every core, a test file to a worker (a long file in hundreds: tests/conftest.py). JOBS=0 runs them one after another.
JOBS ?= auto
test:
	$(PY) -m pytest -q -n $(JOBS) --dist loadgroup tests

# renders every stock machine to build/renders/ and prints the CPU budget
render:
	$(PY) -m emu.render "$$(find firmware -name '*.syx' | head -1)"

# compiles engine/ for ColdFire and shows where it lands
engine:
	$(PY) -m tools.build_engine

# builds the patched OS file into build/images/. It does not flash anything.
image:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)"

# the same, plus the main CPU patches (knob names, stereo mixer link). OS 1.42 only.
image-full:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" full

# image-full plus the recorder (MODE 2 and 3). OS 1.42 only.
image-rec:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" rec

# image-rec plus sample slots of 1 MB (10.9 s). Changes how the +Drive is laid out: read docs/SAMPLER.md first.
image-big:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" big

# image-big plus takes that last: saving a project writes new takes to the +Drive. OS 1.42 only.
image-keep:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" keep

# image-keep plus twice the samples loaded: the pool goes to the audio CPU in two halves. Changes boot code.
image-double:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" double

# image-double plus the screen: SMPL shows the stereo sample's name, LOOP and MODE show words. Main CPU only.
image-screen:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" screen

# image-screen plus the sampling page behind a second press of SYN on a sampler track. Both CPUs.
image-page:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" page

# image-page plus samples loaded while the unit runs: LOAD PROJECT puts the drive's samples back in slots recorded over.
image-load:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" load

# image-load plus three sample banks on the drive, one a project. Every drive access passes through it. Main CPU only.
image-bank:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" bank

# image-bank plus fades in the sound engine: a cut start, a cut end and a loop's seam do not click. Audio CPU only.
image-fade:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" fade

# image-fade plus a mute that only silences: a muted track's trigs still fire. Main CPU only, in the per-block routine.
image-mute:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" mute

# image-mute plus LEN that acts while a note plays. STRT is still a note's own. Audio CPU only.
image-len:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" len

# image-len plus STRT: a loop's next pass begins where the knob is. Audio CPU only.
image-live:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" live

# image-live plus LEN that stops at 3: a loop cannot close to a buzz. One descriptor number and the audio CPU.
image-floor:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" floor

# image-floor plus a step's REC as a lock of its own: locking REC no longer locks MODE. Both CPUs.
image-reclock:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" reclock

# image-reclock plus a sample that stays clean when it is pitched. Audio CPU only.
image-pitch:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" pitch

# image-pitch plus the sampling page's level meter and more sources (each track, the FX track, delay and reverb). Main CPU only.
image-meter:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" meter

# image-meter plus SAVE on the sampling page: the takes written to the drive, without the project. Main CPU only.
image-save:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" save

# image-save's main program on image-reclock's sound engine: the meter, the sources and SAVE without the pitch change.
image-safe:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" safe

# image-safe with three numbers on the sampling page that show where a step's REC lock gets to. A tool, not an image to keep.
image-probe:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" probe

# image-save plus a stereo sample on one track: its right channel no longer takes the next track. Both CPUs.
image-stereo:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" stereo

# image-stereo with the audio CPU's load on the sampling page, measured on the unit. A tool, not one to keep.
image-time:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" time

# image-time with a pitched frame summed from twelve frames, not sixteen: to hear and to read beside it. A tool.
image-time12:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" time12

# image-stereo with the sum of twelve frames, plus a record gain on the sampling page (knob F). Main CPU only on top of it.
image-gain:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" gain

# image-gain plus a sample that is mono or stereo by itself: MODE moves to the sampling page and says what a take is. Both CPUs.
# With the audio CPU's peak load in the page's last box while the images are being built.
image-mode:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" mode

# image-mode plus a crossfade at a loop's seam, in place of the dip. Audio CPU only.
image-cross:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" cross

# image-cross plus mono samples in single slots at the back: SMPL 33 to 64 are the slots of those numbers. Both CPUs.
image-pack:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" pack

# image-pack plus a SMPL knob that stops only on real samples and one free spot of each kind. Both CPUs.
image-stops:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" stops

# image-stops plus the purple pattern mutes as solos: the tracks whose keys are on are heard, the others silenced. Main CPU only.
image-solo:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" solo

# image-solo plus the takes written when a whole pattern is saved to the project, and no SAVE box on the sampling page. Main CPU only.
image-ptn:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" ptn

# image-ptn with the record feed made cheap on the main CPU (the same take, to the bit), and no FAIL on the sampling page. Main CPU only.
image-feed:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" feed

# image-feed with a third setting of REC on the sampling page, ONCE: a step locked to it records the next time it plays and
# the lock is then taken off; the track's own records from its next step, once. Main CPU only.
image-once:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" once

# image-once with the purple keys stock's pattern mutes again, and a solo on the sampling page's knob E. Main CPU only.
image-soloknob:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" soloknob

# image-soloknob with a crossfade on the sampling page's knob G, where MODE was: every other track goes down as it goes up.
# A take at a stereo place is always stereo. Main CPU only.
image-xfade:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" xfade

# image-xfade with one crossfade for the whole unit: the track that last turned it stays. Main CPU only.
image-gfade:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" gfade

# image-gfade with the right channels of stereo tracks moved by the transfer controller, not read by the CPU. Main CPU only.
image-dma:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" dma

# image-dma with a second page on the analog tracks: the solo and the crossfade. Main CPU only.
image-apage:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" apage

# image-apage with a sampler track's solo lockable to a step. Main CPU only.
image-slock:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" slock

# image-slock with an analog track's solo lockable to a step too. Main CPU only.
image-alock:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" alock

# image-alock with several tracks recording at once, each from its own SRC into its own DEST. Both CPUs.
image-multi:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" multi

# image-multi with sample rate reduction on the first page's sixth knob (MODE's parameter, freed). SY SWARM is its room. Both CPUs.
image-srr:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" srr

# image-srr with the sampling page's knobs, and SMPL, turning as stock's own knobs do. The crossfade's is as it was. Main CPU only.
image-gear:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" gear

# image-gear with a step's ONCE spent only where the sequencer plays the step: REC locks to ONCE on the first step too. Main CPU only.
image-stay:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" stay

# image-stay with a profile of the main CPU built in, off until the sampling page's last knob turns it on: then SRC SENDS records it. Main CPU only.
image-prof:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" prof

# image-prof with a note that starts on a loud frame faded in: no click at the start of a take. Audio CPU only.
image-soft:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" soft

# image-soft with a take's sources read before the mixer: a muted track records, and the FX track's mute silences it. Main CPU only.
image-pre:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" pre

# image-pre with a one-shot faded out before its end at full LEN too: no click at the end of a take. Audio CPU only.
image-tail:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" tail

# image-tail with five more readings of the timer in the profile's record, before the mixer: a tool. Main CPU only.
image-lap:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" lap

# image-lap with a long sample's hits starting the filter's envelope again, by DEL on a sampler track. Both CPUs.
image-hits:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" hits

# image-hits with DEL named HITS on a sampler track's filter page and in its pop-up, and no delay drawn. Main CPU only.
image-hitui:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" hitui

# image-hitui with a pitched note, a fade and a loop's blend for less of the audio CPU's block. Audio CPU only.
image-trim:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" trim

# image-trim with the pitched sum's tests worked out once a run. Audio CPU only.
image-slim:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" slim

# image-slim with a pitched frame summed from six frames. Audio CPU only.
image-six:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" six

# image-slim with a pitched frame summed from eight frames, in image-six's place. Audio CPU only.
image-eight:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" eight

# reads a profile take's file (FILE=the.wav, brought off with Transfer) and says where the main CPU's time went.
# It reads files: it does not talk to the unit.
prof-read:
	$(PY) -m tools.prof_read "$(FILE)"




# turns the audio in samples/ (subfolders too) into numbered files for Transfer. FIRST=9 starts at slot 9.
# BIG=1 is for a unit with the big image: samples of up to 10 s where it is 5. DOUBLE=1 for the double image: twice as much in all.
samples:
	$(PY) -m tools.split_sample samples --out build/samples/transfer $(if $(FIRST),--first $(FIRST)) $(if $(BIG),--big) $(if $(DOUBLE),--double) $(if $(PACK),--pack)
	@command -v open >/dev/null && open build/samples/transfer || true

# eight stereo check samples for one-track stereo, as 16 files for Transfer: slots 49 to 64, or FIRST=1 for 1 to 16.
# With them a sheet of what to do. Writes files only.
stereo-sample:
	$(PY) -m tools.stereo_check sample --first $(or $(FIRST),49)
	@command -v open >/dev/null && open build/samples/stereo_check || true

# reads a recording of them (one stereo file, or a take's L and R files) from samples/check/ and says what it shows.
# FILES="a.wav b.wav" names the files instead. It reads files: it does not talk to the unit.
stereo-check:
	$(PY) -m tools.stereo_check check $(FILES)

# the user's patch bundle of a built image (tools/bundle.py): our bytes only, refused if it carries Elektron's
bundle:
	$(PY) -m tools.bundle $(IMAGE)

# the single-file patcher of a bundle (tools/single.py): build/dist/syncrackd_$(IMAGE).py, what a release gives users
single:
	$(PY) -m tools.single $(IMAGE)

# the browser patcher's release: the single file and site/release.json (site/index.html, GitHub Pages)
site:
	$(PY) -m tools.single $(IMAGE) --site

setup:
	python3 -m venv .venv
	.venv/bin/pip install -q -r requirements.txt
	git submodule update --init

# image-six with the unit asking the phone at LOAD PROJECT (engine/phone.c). Main CPU only.
image-phone:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" phone

# image-phone with the first page's STRT/LOOP and LEN/SRR changed over, the crossfade heard through a global mute,
# finer steps of a hit's loudness, and SOLO and REC on a sampler track's TRIG page. Both CPUs.
image-trig:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" trig

# image-trig with a hit's steps from each sample's own loudest frame, and SOLO and REC drawn as stock's switch. Both CPUs.
image-switch:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" switch

# image-switch with the dotted boxes around SOLO and REC wiped, and REC OFF or ONCE only. Main CPU only.
image-box:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" box

# image-box with the crossfade on the first page's knob D, DEC's slot, kept with the pattern. Both CPUs.
image-xknob:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" xknob

# image-xknob with knob D the pattern's one crossfade on every track, the amount carried over a turn. Main CPU only.
image-xshare:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" xshare

# image-xshare with LFO.T and FLT.T on FLTR2's G and H, and the phone's load query. Main CPU only.
image-fltr:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" fltr

image-tlsolo:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" tlsolo

# image-tlsolo with patterns 1..64 long and 65..128 their tails, played as one with the head's kit. Main CPU only.
image-long:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" long

# image-tlsolo with a sampler track's keys playing its sample's slices (KEYS, knob H of the sampling page). Both CPUs.
image-slice:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" slice

# image-slice with LEN on a slice reaching to the sample's end, so a slice rings on past the next. Audio CPU only.
image-ring:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" ring

# image-ring with the profile splitting the mixer stretch into stock's mixer and our links. Main CPU only. A tool.
image-mixtime:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" mixtime

# image-mixtime with a block that has nothing to change going straight to stock's mixer. Main CPU only.
image-fast:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" fast

# a tool, not to keep: image-fast with the profile cutting the events and knobs stretch in five. Main CPU only.
image-evtime:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" evtime

# image-fast with stock's USB audio receive not run while the unit sends its own USB audio. Main CPU only.
image-rxoff:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" rxoff

# image-rxoff with the receive off only while the phone says it captures (0x65 on, 0x66 off). Main CPU only.
image-rxcap:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" rxcap

# image-rxcap with the mono tracks' right buffers copied by movem. Main CPU only.
image-copy:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" copy

# image-copy with the crossfades' shares made without the CPU's divide. Main CPU only.
image-nodiv:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" nodiv

# image-nodiv with every track's right half sent by the audio CPU, so the main CPU copies none. Audio CPU only.
image-allright:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" allright

# image-allright with the pre frame's flag on-chip: nothing stored at 0x4556b000 without a take or the meter. Main CPU only.
image-prewas:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" prewas

# image-prewas with the always-on costs that change nothing heard taken out (transfers only for stereo, no profile unless on).
image-cut:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" cut

# image-cut with no FX track mute and no frame of ours in SDRAM: takes and the meter read the on-chip buffers.
image-nofx:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" nofx

# image-nofx with the crossfade's hand-over fixed: the other tracks' live crossfade cleared with their kit's.
image-xfix:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" xfix

# image-xfix with the hand-over taking the crossfade from the unfiltered words: continuous, no snap to 0.
image-xcont:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" xcont

# image-xcont with the hand-over's amount set through the page's own method, so stock's turn goes on from it.
image-xcarry:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" xcarry

image-scan:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" scan

image-scratch:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" scratch

image-soloend:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" soloend

image-eucl:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" eucl

image-norm:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" norm

image-atrig:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" atrig

image-back:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" back

image-stretch:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" stretch

image-lock:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" lock

# image-lock with STRT and LEN followed on a stretched note as on one that is not. Audio CPU only.
image-scrub:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" scrub

# image-scrub with STRT and LEN followed on a slice as on a whole sample. Audio CPU only.
image-slscrub:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" slscrub

# image-slscrub with a stretch that holds together: a wide look for where a grain lines up, and heads locked onto hits. Audio CPU only.
image-grain:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" grain

# image-grain with KEYS back to two and the stretch its own lockable switch on the sampling page's knob E. Main CPU only.
image-stsw:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" stsw

# image-stsw with the stretch's look in slices over the blocks before a grain, and smaller: a lower peak. Audio CPU only.
image-spread:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" spread

# image-spread with FLTR2's DEL drawn as a knob named TRANS on a sampler track. Main CPU only.
image-trans:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" trans

# image-trans with DEST SMPL or NEXT (a free place, and SMPL to the take) and knob C the track's KIND, STER or MONO. Main CPU only.
image-next:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" next

# image-next with BANK off the sampling page and in the PROJECT menu: SAMPLE BANK, the next bank each time it is chosen. Main CPU only.
image-pbank:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" pbank

# image-pbank with SMPL stopping only at samples of the track's KIND. Main CPU only.
image-kind:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" kind

# image-kind with the screen sent to a viewer over USB as SysEx while one asks, for video. Main CPU only.
image-mirror:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" mirror

# the trap image (level 65, on mirror): a stretched note for less, trapezoid heads and the place a block at once; CY ALLOY's room.
image-trap:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" trap

# the shadow image (level 66, on trap): the viewer's frame copied from what stock's column sender gives the panel. Main CPU only.
image-shadow:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" shadow

# the sink image (level 67, on shadow): the viewer's frame put into the SysEx sink in writes that never cross one of its sends. Main CPU only.
image-sink:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" sink

# the tune image (level 68, on sink): a pushed turn of the sampler's TUNE by 1, not 4. Main CPU only.
image-tune:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" tune

# the letgo image (level 69, on tune): a stereo note over lets go of its right channel; the normalizer by what each take was. Audio CPU only.
image-letgo:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" letgo

# the ask image (level 70, on letgo): LOAD PROJECT asks the phone only once it has said 0x63 since the start. Main CPU only.
image-ask:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" ask

# the axf image (level 71, on ask): the analog tracks' second SYN page, P in H, so G is the crossfade's alone. Main CPU only.
image-axf:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" axf

# the gainup image (level 72, on axf): the sampling page's gain in D, the peak in E, STRC in G. Main CPU only.
image-gainup:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" gainup

# the onedest image (level 73, on gainup): DEST only SMPL, NEXT gone; KIND stays. Main CPU only.
image-onedest:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" onedest

# the destnum image (level 74, on onedest): DEST SMPL or a place's number, its stops SMPL's by KIND. Main CPU only.
image-destnum:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" destnum

# the fresh image (level 75, on destnum): a new project asks the phone as a load does. Main CPU only.
image-fresh:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" fresh

# the newproj image (level 76, on fresh): NEW PROJECT asks the phone; every ask says the project left. Main CPU only.
image-newproj:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" newproj

# the wipe image (level 77, on newproj): the unit empties the slots the phone names. Main CPU only.
image-wipe:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" wipe

# the stream image (level 78, on wipe): LOAD PROJECT's samples written by the phone after the load, each slot loaded. Main CPU only.
image-stream:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" stream

# the evict image (level 79, on stream): a slot the phone sends is loaded over a take not saved, its held copy dropped. Main CPU only.
image-evict:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" evict

# the handrec image (level 81, on evict; 80 was playrec, dropped): stopped, a track whose REC is at ONCE records a note played by hand. Main CPU only.
image-handrec:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" handrec

# the firstrec image (level 82, on handrec): PLAY records a ONCE on the first step on the first pass. Main CPU only.
image-firstrec:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" firstrec

# a tool, not to keep: the spread image with locks on knob slots 0, 55 and 70 made by G with a step held, shown in D, F and G.
image-tuneprobe:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" tuneprobe

image-slotprobe:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" slotprobe

# a tool, not to keep: the atrig image with section 7 grown to its most by zeros, for whether the updater and the boot take it.
image-pad7:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" pad7

# a tool, not to keep: image-rxoff with the evtime tool's profile.
image-evrx:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" evrx

image-probe17:
	$(PY) -m tools.build "$$(find firmware -name '*.syx' | head -1)" probe17

# the story of a built image: build/story/$(IMAGE).html, a player of what was patched where (local only, rule 2)
story:
	OPEN=1 $(PY) -m tools.story $(IMAGE) $(BASE)

# a page drawn by stock's own code, as a PNG in build/screens/: make screen PAGE=fltr2 IMAGE=trans MACHINE=44
screen:
	$(PY) -m emu.screen $(or $(PAGE),fltr2) $(or $(IMAGE),stock) --machine $(or $(MACHINE),44)


# an image's own test file, its results put in its story
check:
	$(PY) -m pytest -q tests/test_$(IMAGE).py --junitxml=build/trace/$(IMAGE).tests.xml; s=$$?; \
	OPEN=1 $(PY) -m tools.story $(IMAGE) $(BASE); exit $$s
