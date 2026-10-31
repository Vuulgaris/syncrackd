"""Section 3 (main CPU) addresses used by the audio path. **OS 1.42 only.**

Section 3 differs between 1.41 and 1.42, so nothing here carries over. Every number was read from our objdump listing
of the pinned section; tests/test_stereo_path.py re-checks each against the image.
"""
BASE = 0x40000400
ENTRY = 0x400004e8  # the section's first long; the vectors and their stubs sit before it
CODE_END = 0x401c1062  # the last function ends here (rts at 0x401c1060); tables follow, to the section's end

SHARED = 0x10000000  # the window shared with the audio CPU, main CPU view
SHARED_AUDIO = SHARED + 0x1b0  # 8 track buffers from the audio CPU
SHARED_CHUNK = SHARED + 0x800  # 2 KB sample chunk window used at boot

# eDMA channel 47 setup at 0x400a47fa: window -> main CPU SRAM, 64 x 16 bytes
DMA_SETUP = 0x400a47fa
TRACKS = 0x80003d50  # 8 digital track buffers, 128 bytes each, after the DMA
ANALOG_TRACKS = 0x80003950  # the other track buffers the mixer reads
INPUTS = ANALOG_TRACKS  # 8 buffers of 32 longs: tracks 9..12, ext in L, R, FX block return L, R
IN_T9, IN_EXT_L, IN_EXT_R, IN_FX_L, IN_FX_R = 0, 4, 5, 6, 7  # buffer numbers in INPUTS

# The converters reach the main CPU on a serial audio port, 8 slots of 32 bits a frame. eDMA channel 52 (set up at
# 0x4000101a..0x4000108c) writes them to a ring of two 32-frame halves.
RX_RING = 0x80001800  # 2 x 1024 bytes
RX_TCD = 0xfc045680  # channel 52: source RX_PORT, destination RX_RING, 64 x 32 bytes, wraps
RX_PORT = 0xfc0c8008
RX_UNPACK = 0x400962ac  # (half, frame): one half of the ring -> the input channels of FRAME
RX_UNPACK_END = 0x40096360
FRAME = 0x80004760  # 32 frames of 20 longs. Inputs before the mixer, all 20 channels after it
FRAME_CH = 20
# channel numbers in FRAME once the mixer has returned (0x4008fbec..0x4008ff1a)
F_MAIN_L, F_MAIN_R, F_T1, F_T9, F_FX_L, F_FX_R, F_SENDS_L, F_SENDS_R, F_EXT_L, F_EXT_R = 0, 1, 2, 10, 14, 15, 16, 17, 18, 19
FRAME_TO_INPUTS = 0x4008ee86  # (inputs, frame): the 8 input channels of FRAME -> INPUTS, called just before the mixer
FRAME_TO_INPUTS_END = 0x4008eecc
# Names the factory test gives the 8 receive slots, in slot order (accessor 0x400a5840)
ADC_NAMES = 0x401e9568

# the mixer, one call per 32-frame block. It makes 14 kernel passes a block (tests/test_mixer_whole.py): 8 of
# MIX_KERNEL (the sends of the tracks and of the inputs, the inputs' dry sum), 2 of MIX_KERNEL9 (the reverb send, the
# delay's return its ninth input), 4 of MIX_KERNEL10 (the dry sums, the two returns their ninth and tenth). A kernel
# replaces what is at its destination and writes its ramped gains back.
MIX = 0x4008f242
MIX_END = 0x4008ff32
MIX_KERNEL = 0x4008f0b6  # (dest, tracks, gains[8], increments[8]): dest is interleaved, stride 8
MIX_KERNEL_END = 0x4008f13e
MIX_KERNEL9, MIX_KERNEL10 = 0x4008f024, 0x4008ef8c  # the same with 9 and 10 inputs, buffers 128 bytes apart
PAN_LAW = 0x400a1792  # (pan 8.8) -> D0 = left gain, D1 = right gain, both negated
PAN_HELPER = 0x400a1734
PAN_END = 0x400a17f2
BUS_L = 0x8000dbd0  # left samples at +8*n
BUS_R = 0x8000dbd4
GAIN_L = 0x80006328  # current gain per digital track into BUS_L: pan left x volume x the delay send
GAIN_R = 0x80006308
# The digital tracks' dry mix, which goes to slots 7 (left) and 2 (right) of the output frame
BUS_DRY_L, BUS_DRY_R = 0x8000dad0, 0x8000dad4
GAIN_DRY_L, GAIN_DRY_R = 0x8000e188, 0x8000e160  # 10 longs each: 8 tracks, delay return, reverb return
BUS_FX_L, BUS_FX_R = 0x8000dfd0, 0x8000dfd4  # the tracks routed to the FX block (gains 0x8000e138, 0x8000e110)
RETURN_DELAY, RETURN_REVERB = 0x80004150, 0x800041d0  # right after TRACKS: one side of each return, copied in before a dry pass
MIX_DRY_DONE = 0x4008fb78  # the four dry passes are over; the first reader of BUS_DRY is the scale call at 0x4008fc5a
# The mixer's helpers that work on the effects' own state (delay, reverb, their set-up): not run anywhere here
MIX_EFFECTS = (0x4009748c, 0x40096908, 0x40096eb4, 0x40096e32, 0x4009687a)
MIX_COPY = 0x4008f22c  # (to, from): 32 longs out of a stride of 8
MIX_GAIN2 = 0x4008eef8  # (to, from, gains[2], increments[2]): a stereo pair times ramped gains
MIX_SCALE = 0x4008ef42  # (buffer, n): 64 longs times n; runs the EMAC in integer mode, which emu/ does not model
MIX_LEVEL = 0x4008ff34  # (buffer, gain before, gain now): 32 frames in place; ends at 0x4008ff8a

MIX_CALL = 0x400a5046  # the one call to the mixer: jsr MIX, arguments (?, ?, params)
LEVEL2 = 0x80004670  # a word per track, read by the mixer next to the level word at params + 2*track

# Mute state as the per-block routine (0x400a38ce, the mixer's caller) reads it. A bit per track, 0..11 and 12 = FX.
MUTES = 0x80003048  # global mutes: project settings + 36, copied here at 0x400a3408
SOLOS = 0x8000304c  # solos: project settings + 40. When not zero the routine uses ~SOLOS in place of MUTES
PATTERN_MUTES = 0x43bdd828  # word: the pattern's mutes, stored by 0x400a30b2
MUTE_READ = 0x400a39a0  # movel MUTES,%d3 ; addql #4,%sp ; movel SOLOS,%d0
MUTE_TEST = 0x400a4224  # mvzw PATTERN_MUTES,%d7, right after the test of the mask above
# The trig half of mute, in the same routine's event loop (engine/mutetrig.c). An event has its kind at + 4 (1: a note
# starts), its track at + 8, where it came from at + 12 (1: the sequencer) and flags at + 36.
TRIG_EVENT = 0x400a41f8  # an event for a track other than the FX track: d0 its kind, d1 where from, d2 its track
TRIG_SOURCE = 0x400a4214  # moveq #1,%d7 ; cmpl %d1,%d7 ; bnes TRIG_TESTED: the mute tests are for the sequencer's events
HOLD_LOOP = 0x400a4c3e  # after the block is built: for each digital track, its machine at + 62 and the hold flag over slot 24
HOLD_WRITE = 0x400a4c6a  # movew %d0,%a0@(76) ; lea %a0@(142),%a0: the flag is stored, on to the next track
HOLD_END = 0x400a4c7a  # past that loop
PARAM_WORDS = 0x800021b0  # the block a trig's locks are written into: 142 bytes a track, slot s at + 28 + 2s
PARAM_SENT = 0x80006348  # the block 0x400979ca builds from it: what the mixer, the feed and the audio CPU are given
MACHINE_BYTES = 0x80002f50  # a track's machine, a byte each: the eight digital tracks', then the analog ones' (0x40097a7e reads + 8 on)
TRIG_MUTE = 0x400a421a  # movel %fp@(-56),%d1 ; asrl %d2,%d1: the track's bit of the mask MUTE_READ made
TRIG_UNMUTED = 0x400a426a  # where both tests go when the track is not muted
TRIG_TESTED = 0x400a427a  # after them: d4 is not 0 when the event is to be dropped
TRIG_KEPT = 0x400a42a4  # an event that was not dropped goes on here
TRIG_NEXT = 0x400a4796  # and one that was: on to the next event
TRIG_OWNER = 0x400a1b8c  # (event): the last check before TRIG_TESTED, not about mutes
KIT_NOW = 0x800030b8  # the kit the per-block routine plays from, set by the event that brings a kit
KIT_MIDI = 5456  # in a kit: a word, a bit per track that is a MIDI track
TRACK_IS_MIDI = 0x4000f5ae  # (kit object, track) -> its bit of that word; MACHINE_OF answers 35 for such a track
KIT_MIDI_UI = 0x4000f5e0  # mvsw %a0@(KIT_MIDI),%d0 ; asrl %d2,%d0 ; andl %d1,%d0: how the UI asks
KIT_MIDI_LOOP = 0x400a432a  # mvsw %a0@(KIT_MIDI),%d1 ; btst %d0,%d1: the event loop asks too, with a0 from KIT_NOW
# The solo image (engine/solo.S): the pattern's mutes as solos. The pattern's own word (its settings + 16: bits 0..11
# the tracks, bit 12 the FX track) is left as it is; what the two engines are given of it is changed where it is
# stored.
MIDI_PATTERN_MUTES = 0x444b5ae0  # word: the MIDI engine's copy (its loop 0x4010dbf8 tests it at 0x4010de7e and 0x4010deb2)
PATTERN_MUTES_SET = 0x400a30b2  # (word): lea %sp@(6),%a0 ; movew %a0@,PATTERN_MUTES ; rts. Called at 0x40019bfa, 0x4002332c, 0x4008c4be, 0x4008c4d0
PATTERN_MUTES_MSG = 0x400a3c26  # movew %a0@,PATTERN_MUTES: the same store in the per-block routine, from a kind-2 message's pointer at + 12
MIDI_MUTES_SET = 0x4010d4b8  # (word): the same routine for the MIDI engine's copy. Called at 0x40019c06, 0x40023334, 0x4008c4d8
MIDI_MUTES_MSG = 0x4010dc76  # movew %a0@,MIDI_PATTERN_MUTES: in the MIDI engine's loop, from a kind-2 message's pointer at + 8
PATTERN_MUTED = 0x40015ec0  # (pattern, track) -> the track's bit of the pattern's word, 0 for a pattern with no settings
PATTERN_SETTINGS = 40  # in a pattern's method table: () -> its settings, or 0. The word is at settings + 16
ROW_MUTES = 0x400232a0  # (song, row) -> a song row's own word of mutes
KEY_COLOURS = 0x400375dc  # (view): the twelve track keys' colours in mute mode, a track a pass, the track in d2
KEY_ROW_BIT = 0x400376a8  # mvzw %d0,%d0 ; asrl %d2,%d0 ; andl %d1,%d0: a song row's word to the track's bit, d1 = 1
KEY_PATTERN_CALL = 0x400376c2  # jsr PATTERN_MUTED, (pattern, track) pushed: the pattern's bit. Both go on at + 10 with the bit in d0
SCREEN_MUTED = 0x4003737a  # (view, track) -> muted, by the mode the keys are in: asked once, by the draw at 0x4003cc7e
SCREEN_PATTERN_JUMP = 0x400373fe  # jmp PATTERN_MUTED, with (pattern, track) left on the stack: its answer for a pattern
CAVE_SOLO = (0x400a2928, 0x400a29ce)  # 166 bytes nothing reaches, named by nothing (tools/deadcode.py): the solo image's routines
# The feed image: the routine that writes a block of a take into the ring (engine/feed.S), in one more run nothing
# reaches and nothing names (tools/deadcode.py). 642 bytes.
CAVE_FEED = (0x400a8db6, 0x400a9038)
# The once image: REC's third setting, ONCE (engine/once.S, engine/onceclean.c). A step's lock at ONCE_WORD records as
# a lock at 0x5280 does (the audio CPU, the feed and recword.S take the high byte) and is spent where the sequencer
# plays it.
CAVE_ONCE = (0x40088820, 0x40088a02)  # 482 bytes nothing reaches and nothing names (tools/deadcode.py): 16 bytes of ours, then code
ONCE_VARS = 16
ONCE_ARM, ONCE_DIRTY = CAVE_ONCE[0], CAVE_ONCE[0] + 8  # a byte a digital track: its own REC is ONCE; a spent lock is in its table
HAND_HOLD = 0x40022868  # CAVE_LONG[0], below; the handrec image: once.S's, first in the long image's run: a bit a track whose take runs past its release
HAND_LEFT = HAND_HOLD + 4  # 8 longs: what is left of a take held by hand, in the tempo's units
HAND_REC = HAND_LEFT + 32  # once.S's hand_rec, called by recword.S
TEMPO = 0x402d7360  # BPM x 120, added to a phase every block (0x400a0250)
PATTERN_DATA = 0x43bd8430  # the pattern's data: a track's trig settings 1177 bytes a track, a step's at + 64 k + step, the track's own after
LEN_TABLE = 0x401e95ac  # stock's lengths of a trig's LEN, a long each from + 4 (LEN k at + 4 + 4 k), in the tempo's units: 1 step is 2,700,000, LEN 14's
TRIG_LEN_OWN = 961  # in a track's 1177 bytes: the TRIG page's LEN, which a step with none (0xff at + 192 + step) takes
ONCE_WORD, ONCE_SPENT = 0x52c0, 0x6bc0  # a step's REC at ONCE; what it is once played: no mark, so the track's REC decides, and the UI's side takes it off
STEP_PLAY = 0x4008b8fa  # (track, pattern data, ?, step, ...): the routine that plays a step (4008b8fa..), d4 the track and d3 the step
SEQ_NOW = 0x4008c128  # (track or -1): plays the step the sequencer is on, with a place for the event (the stay image's other caller)
START_NOW = 0x4008c3fe  # in 0x4008c300, the counts cleared, state 2: jsr %pc@(SEQ_NOW) with -1, its last act. The playrec image took it for the start; it is STOP (MIDI 0xFC sent at 0x4008c358)
SEQ_STATE = 0x43bd83bc  # the sequencer's state: 1 at a start, 2 at STOP
SEQ_STARTS = (0x4008ad50, 0x4008b602)  # movel %d0,SEQ_STATE with 1: the start (after MIDI 0xFA at 0x4008ad40), and another way in
SEQ_PLACES = 0x444e3438  # 80 bytes a track: the record the other caller of the step routine fills (its + 68 the lock buffer), which a start copies and queues
STEP_LOCKS_PUSH = 0x4008bc5e  # in it, for a step whose count of locks is not 0: movel %fp,%sp@- ; jsr STEP_LOCKS, the event in fp
STEP_NO_LOCKS = 0x4008bc6a  # and for one with none: clrl %fp@(8), the event's count. Only 0x4008bc3a branches here
STEP_JOINED = 0x4008bc6e  # where both go on
MAIN_WAIT = 0x40001ca0  # (queue) -> the next message, waiting for one
MAIN_LOOP = 0x4000b2d2  # the main task's loop (entry 0x4000abd6, priority 6, 160 KB of stack): pea MAIN_QUEUE ; jsr MAIN_WAIT,
MAIN_LOOP_WAIT = 0x4000b2d8  # its one wait, then a jump by the message's first byte, 0..36 (20..23 are handed to a UI object, 0x400e220c)
MAIN_QUEUE = 0x405d4a7c
NOW_PATTERN = 0x40019000  # (manager) -> the selected pattern's object: manager + 13204 + 1664 a pattern
STEPS_OF = 0x40015fae  # (that, track) -> the track's steps object, 112 bytes a track: PATTERN is the two of them for the active track
# The soloknob image: the purple keys are stock's pattern mutes again (none of the solo image's seven places is
# changed and engine/solo.S is not built), and a solo is the sampling page's knob E: a bit a track in a long of ours,
# the first four bytes of the run the solo image's code was in. The rest of that run is stock's bytes, which nothing
# reaches.
SOLO_WORD = CAVE_SOLO[0]
# The xfade image: a crossfade a sampler track, the sampling page's knob G, 0 to 127: a byte a digital track after the
# solos' long, in the same run, which nothing reaches. Every other track is turned down by the largest of the others'
# numbers.
XFADES, XFADE_TOP = CAVE_SOLO[0] + 4, 127
SOLO_NOW = CAVE_SOLO[0] + 16  # the slock image: this block's solos, a step's own among them (engine/sampler.h, SLOCK)
SOLO_SLOT_ANALOG = 26  # the alock image: an analog track's, the last of the machine's ten words
CAVE_ALOCK = (0x400f51ea, 0x400f5344)  # 346 bytes nothing reaches and nothing names (tools/deadcode.py): the alock image's solos, worked out
# The srr image (engine/sampler.h, SRR): sample rate reduction in MODE's parameter, and a sampler track's REC and SRC
# in the track's own word on knob slot 24. The per-block routine that reads that word (engine/recword.S), behind eight
# bytes of ours, in one more run nothing reaches and nothing names (tools/deadcode.py). 326 bytes.
CAVE_SRR = (0x401a8d52, 0x401a8e98)
SRR_DIRTY = CAVE_SRR[0]  # a byte a track: its word was just made from MODE's bits, and its old locks of MODE are to go
KIT_POINTER = 0x800030b8  # the kit the sound engine's side reads: stock stores its address here (0x400a34ca, 0x400a359a, 0x400a3c38)
KIT_TRACK, KIT_WORDS = 291, 62  # a track's sound is 291 bytes, from + 42; its 71 words from + 20 of that, slot s at 2 s
SRR_SIG, SRR_SIG_MASK = 0x40a4, 0xf0fe  # a signed word: these bits, with REC in bit 0 and the source in bits 8 to 11
MODE_SLOT = 23
# The gear image: the sampling page's knobs and SMPL turn through stock's own routines (engine/recpage.c, GEAR).
KNOB_STEPS = 0x400f6866  # (event, fine, coarse) -> the event's steps, times coarse while the knob is pushed in
KNOB_PUSHED = 0x400f6884  # (event) -> its byte at + 20
KNOB_CHANGE = 0x400f6a96  # (a page's ticks, knob, steps, a feel, pushed) -> the change, 8.8: a step every so many ticks, a fast turn further
TURN_STATE = 148  # a SYN page object's ticks, 20 bytes a knob: what stock's knob routine hands KNOB_CHANGE
FEEL_PLAIN, FEEL_PICKER = 0x443db178, 0x443db140  # built at a start (0x401aa6ce, 0x401aa732): a plain knob's, and Twinshot's sample picker's
# A feel's numbers are set by a routine of its own: the plain one's (0x400f6390) 3 ticks a step, speeding up
# by 2; the picker's (0x400f63f0) 6 ticks a step, no speeding up, and a pause after each step
# The prof image, a tool: where the main CPU's time goes, as a take (engine/prof.S).
BLOCK_IRQ = 0x400a38ce  # the per-block interrupt's routine (vector 191), to its rte at BLOCK_IRQ_END
BLOCK_IRQ_END = 0x400a5520
BLOCK_IRQ_TEST = 0x400a376a  # stock compares the vector's long with the routine's address: the long is left alone
TIMER0_COUNT = 0xfc07000c  # the first timer's count: stock reads it twice for a wait (0x400a596a, 0x400a5992), so it counts
CAVE_PROF = (0x40170628, 0x40170978)  # 848 bytes, the profile's record and routines (named by nothing)
RUNNING_TASK = 0x454e49a8  # the running task's control block: the task switch (0x40000410) saves through it and stores the next one's
PROF_RECORD = 64  # the record's bytes, first in the run
FEEL_SLOW = 0x443db15c  # one more of stock's (0x400f63c2): 24 ticks a step, no speeding up. Not used
CAVE_STAY = (0x401a04c2, 0x401a05b6)  # 244 bytes nothing reaches and nothing names (tools/deadcode.py): from the stay image on, the main task's part of ONCE
CAVE_PAGE10 = (0x401a69c4, 0x401a6afa)  # 310 bytes, a tenth run for the page, from the gear image on: a turn through stock's routines (named by nothing)
CAVE_PAGE9 = (0x401ac7b0, 0x401ac8da)  # 298 bytes, a ninth run for the page, from the srr image on: the track's word read and written (named by nothing)
SOLO_SLOT, SOLO_LOCK_ON, SOLO_LOCK_OFF = 17, 0x35, 0x1a  # a step's solo: a lock on this slot at one of two marks, in the high byte
MIX_GAIN = 0x4008edc0  # (level, level2, vol, curve) -> gain; (4008edc0..4008ee30)
MIX_GAIN_END = 0x4008ee30

# An unreferenced function, 396 bytes (it looks like the unused twin of the constructor right after it). Static
# evidence only: no call, branch, address operand, 32-bit value or jump-table entry in the image points into it.
CAVE = (0x401011e4, 0x40101370)
CAVE_EVLAP = (0x40002684, 0x4000271e)  # 154 bytes nothing reaches and nothing names (a whole routine): the evtime tool's four laps
EV_LAPS = ((0x400a3a42, 0x40115b68), (0x400a3a52, 0x400041cc), (0x400a3b3c, 0x4010d7a2), (0x400a4a72, 0x4011a4c0))
CAVE_LINK2 = (0x4016f880, 0x4016fb28)  # 680 bytes nothing reaches and nothing names (a whole routine): the nodiv image's mixer link, which outgrew CAVE
CAVE_COPY = (0x40108314, 0x401083d0)  # 188 bytes nothing reaches and nothing names (a whole routine): the copy image's mono copies by movem
CAVE_RXGATE = (0x40010f0c, 0x40010f80)  # 116 bytes nothing reaches and nothing names (a whole routine): the rxoff image's gate on the USB receive
RX_CALL = 0x400a3a52  # the per-block routine's call of stock's USB audio receive, 0x400041cc(0x45512000, 32)
CAVE_FAST = (0x400b15d2, 0x400b1684)  # 178 bytes nothing reaches and nothing names (a whole routine): the fast image's quick scan
CAVE_SPLIT = (0x40101010, 0x40101068)  # 88 bytes nothing reaches and nothing names (a whole routine): the mixtime image's timed call of the mixer

# The recorder image's second cave: three mix kernel variants nothing calls, between the kernel the mixer uses and the
# frame copy helper it uses. 238 bytes. Static evidence only.
CAVE_REC = (0x4008f13e, 0x4008f22c)
MAILBOX = SHARED + 0x800  # the recorder's ring, in the boot chunk window (engine/sampler.h)
# "The audio CPU is running": cleared at 0x40082da4 when it is restarted, set at 0x400831b0 when the boot handshake
# (sample chunks included) is over. The per-block routine tests it before every exchange.
AUDIO_UP = 0x43bdd824
AUDIO_UP_SET, AUDIO_UP_CLEAR, AUDIO_UP_TEST = 0x400a37c2, 0x400a37ca, 0x400a4e34

# The analog voices' dry sound. The per-block routine fills a control block and sends it to the hardware after the
# mixer call; its first words are each voice's left and right level.
CONTROL = 0x80003160  # words 0..3 left of voice 1..4, 4 ext in left, 5..8 right, 9 ext in right
CONTROL_FILL = 0x400a4fbe  # pea CONTROL for the last routine that fills it (0x40090442), before the mixer call
CONTROL_SEND = 0x400a537c  # pea CONTROL ; ... ; jsr 0x401021b4, after it
VOICE_CONTROL = 0x4008ffc0  # (block, params, voice, track): level and pan -> left at block + 2 v, right at + 10 + 2 v
VOICE_TRACK = 0x402a2138  # 4 bytes: the track of each analog voice (8, 9, 10, 11)
# A third piece of code space: one function nothing references, right before the pan helper. 360 bytes.
CAVE_AMUTE = (0x400a15cc, 0x400a1734)

# Keeping takes (engine/keeptakes.c). The routine that saves a project to the drive, and its two callers: the bodies
# of the two jobs the project screens start (the first is named "Project Save" and is started by the routine that
# shows SAVING '%.16s').
PROJECT_SAVE = 0x4001a82e  # (manager, project, progress callback) -> true in the low byte when saved
PROJECT_SAVE_CALLS = (0x4005bad6, 0x4005bc2c)
KEEP_BOX = SHARED + 0xc10  # struct keepbox, engine/sampler.h
REC_BOX = SHARED + 0xe20  # struct recbox, engine/sampler.h: the sampling page's take
# A fourth piece of code space: one stock function nothing reaches, 930 bytes (tools/deadcode.py).
CAVE_KEEP = (0x401259fa, 0x40125d9c)
# Loading (the load half of engine/keeptakes.c). The routine that loads a project from the drive for the Project Load
# job, and its one caller, the body of that job (it is also the body that makes a new project in an empty place: that
# path saves, and is one of the two calls above). Same arguments and answer as the save. Another loader, 0x4001b168,
# is the one the boot and three confirmations call: not hooked.
PROJECT_LOAD = 0x4001d6fe  # (manager, project, progress callback) -> true in the low byte when loaded
PROJECT_LOAD_CALL = 0x4005bba8
KEEP_PUT = 0x8000  # in a request's slot: engine/sampler.h

# The pool in two halves (engine/poolhalves.c, the "double" image). The sender task computes each chunk's address at
# POOL_CHUNK_SITE; there it now calls our routine.
POOL_CHUNK_SITE = 0x40082fda  # lsll #11 ; pea 0x800 ; addil #block + 5: 12 bytes
POOL_HALF_CHUNKS = 16382  # chunks of 2 KB in what stock could stage: 64 x (4 + 524,224) bytes
POOL_MARK = 0xaa  # the block's first byte; 0xab while it holds the second half
BOOT_STALL_LIMIT = 18  # ticks of the watcher (0x400828cc, every 0x20) without progress before a timeout
AUDIO_POOL = 0x4004f750  # the audio CPU's pool, 64 MB, as its boot loop names it (section 7, 0x40000fba)
AUDIO_POOL_BYTES = 0x4000000
# A fifth piece of code space: one stock function nothing reaches, 912 bytes (tools/deadcode.py).
CAVE_HALVES = (0x40086e42, 0x400871d2)

# Where the samples live on the +Drive, as the main CPU's sample store reads, sizes and erases it
# (tests/test_sample_store.py). The drive is addressed in sectors of 512 bytes. Every slot owns a fixed run of them,
# so a slot cannot hold more than SAMPLE_MAX_FRAMES whatever sends the file.
SAMPLE_STORE = 0x4016f292  # () -> the store object
SAMPLE_SECTOR0 = 8192  # slot 0 starts 4 MB into the drive
SAMPLE_SECTORS = 1024  # sectors a slot: 512 KB
SAMPLE_HEADER = 64  # bytes: 'SAMP' at +0, frames at +8, name at +12, then 16-bit samples
SAMPLE_MAX_FRAMES = 262112  # (512 KB - 64) / 2: 5.4607 s at 48 kHz
SAMPLE_SCAN = 0x4011149e  # (store, slot): a slot's header into the table, or the slot is left empty
SAMPLE_ERASE = 0x40111254  # (store, slot): erases the slot's SAMPLE_SECTORS
SAMPLE_SIZE = 0x40111434  # (store, slot) -> SAMPLE_HEADER + 2 * frames, 0 for an empty slot
SAMPLE_TABLE = 77352  # offset in the store: 24 bytes a slot, the name, then frames at +20
SAMPLE_ROUTE = 0x400b9dfe  # the handler behind "/samples/<slot>", slot 1..64
# The file protocol over USB MIDI (tools/rpc.py). The parser that makes a message object from its id: subql #1 ; mvzb
# ; cmpil #222 ; a word table of 223 offsets from RPC_TABLE, RPC_NONE for an unknown id.
RPC_PARSE = 0x4011ac50
RPC_TABLE = 0x4011ac8e
RPC_NONE = 0x4011d918
RPC_SYSEX_IN = 0x40104014  # (?, data, len, iface): incoming SysEx; iface 2 or 4 -> header and f7 off -> RPC_HANDLE
RPC_HANDLE = 0x40109d0c  # decodes, dispatches and answers in the same call, on the task that delivers MIDI in
RPC_DISPATCH = 0x40108fbe  # (dispatcher 0x4449c734, ...): calls RPC_PARSE, builds the response
RPC_SEND = 0x401086fc  # (sink, message): sink's vtable + 16 write(sink, bytes, n), + 12 commit(sink);
RPC_SEND_CALL = 0x40109e06  # the one call of it in RPC_HANDLE, with the sink 0x4449c51c (made at 0x40109da2, iface 2)
RPC_SINK = 0x4449c51c
RPC_SINK_GUARD = 0x4449c808  # its static guard: not 0 once the first message has made it
RPC_FILE_MAGIC_AT = 0x400b52f0  # movel #0xac11d303,%d0: a data file's header magic, in the code
RPC_FILE_TAIL_AT = 0x400b5322  # moveal #0xaaa1daaa,%a0: its footer's
STORE_WRITE = 0x40111628  # (store, sector, bytes, data, ...): writes anywhere on the drive, 64 KB at a time
STORE_READ = 0x401100d4  # (store, sector, bytes, buffer, ...)
STORE_ERASE = 0x4011015e  # (store, sector, sectors, ...)
DRIVE_BYTES = 0x30000000  # 768 MB
# The three routines under the store that touch the drive itself. Every use of them in the image is a call or a lea
# that tests/test_sample_store.py lists: no table holds their addresses.
DRIVE_READ, DRIVE_WRITE, DRIVE_ERASE = 0x4010f612, 0x4010f7f8, 0x4010f52a
# What the main CPU keeps where, in sectors (first, one past the last). Nothing in the image names a sector between
# the end of the samples and the first work area: 36 MB to 244 MB.
SOUND_SECTOR = 0x40110c3a  # (store, n) -> 2 * (2048 + n), n held to 0..2047
PROJECT_SECTOR = 0x40110746  # (store, n) -> (n + 64) << 13, n held to 0..127; 516096 for n = 128
DRIVE_MAP = (
    ("header", 0, 1),
    ("table", 2048, 2049),
    ("sounds", 4096, 8192),  # 2048 of 2 sectors
    ("samples", 8192, 73728),  # 64 of 1024 sectors
    ("work area", 499712, 507904),  # 4 MB, written by 0x400bd4.. to 0x400bd7..
    ("work area 2", 507904, 516096),
    ("project 128", 516096, 524288),
    ("projects", 524288, 1572864),  # 128 of 8192 sectors
)
DRIVE_FREE = (73728, 499712)
# At boot the main CPU builds the whole pool in its own memory, then hands it over in 2 KB chunks: a marker byte, 4
# bytes of length, then per slot 4 bytes of frame count and the samples.
POOL_STAGE_BUILD = 0x40082334  # reads each of the 64 slots through SAMPLE_READ into the block
POOL_STAGE = 0x4d84f2c0  # the block, a fixed address (0x40082a48 returns it)
POOL_STAGE_BYTES = 0x2000001  # to where the audio CPU's program is staged, AUDIO_IMAGE_STAGE
AUDIO_IMAGE_STAGE = 0x4f84f2c1
SAMPLE_READ = 0x401133ce  # (slot, header out, buffer, offset, most) -> 0 or a negative error
# The main CPU's memory, from its startup code. One 128 MB of RAM seen twice: cached from 0x40000000, and again
# 0x08000000 higher where the cache is off (INFERRED from where things are placed).
MAIN_STACK_TOP = 0x48000000
MAIN_BSS_END = 0x45566490  # the startup code clears up to here
MAIN_HEAP = (0x444e48c0, 0x454e48c0)  # the allocator's 16 MB, inside that
UNCACHED = 0x08000000
UPPER_STATICS = (0x4d5cf088, 0x4f8af2cb)  # first and last address the code names above the stack top, but for EFFECTS_MEMORY below it
# 0x4d64f088, a buffer named whole elsewhere; 0x4d5ef088 is added to an offset the same way at 0x4008080c. Both
# numbers lie inside EFFECTS_MEMORY, which is the lowest block the code really names up there.)
# The loop that hands the staged pool to the audio CPU, a chunk of 2 KB per exchange
POOL_SEND = 0x40082f90
POOL_SEND_INDEX = 0x41bbf424  # chunks sent so far; goes out as 16 bits
BOOT_STALL = 0x41bbf3bc  # counted up by 0x400828cc while nothing moves; past 18 it is a timeout

# UI descriptors of machine type 44, second table (tools/params.py)
SAMP_RECORDS = 0x40233d30  # 8 records of 0x34 bytes: slots 18, 19, 20, 21, 22, 23, 26, 25

# How knob values are shown (tools/uitable.py). A start-up routine fills a RAM table, one 84-byte entry per descriptor
# record, from function objects it builds first.
UI_INIT = (0x40188796, 0x40196ab8)  # the routine, first instruction to its rts
UI_RECORDS = 0x4022d83c  # all 505 descriptor records as one array (tools/params.py reads two runs of it)
UI_COUNT = 505
UI_TABLE = 0x41ba0a24
UI_STRIDE = 84
UI_ENTRY = 0x4007ba2a  # (record index) -> UI_TABLE + 84 * index, index 0 when out of range
SAMP_FIRST = 497  # machine 44's records are 497..504: slots 18, 19, 20, 21, 22, 23, 26, 25
# The pages a track key shows (tools/uitable.pages). The same start-up routine fills a RAM table of 44-byte entries: a
# short name, a long name, the record behind each of the 8 knobs, and the record of the LEVEL knob. 37 numbered pages
# end where the display table starts; the machines' own SYN pages, one per machine type 0..44, lie right before them,
# so the entry before page 0 is machine 44's. PAGE_ENTRY gives that same entry for any page number past 36.
PAGE_TABLE = 0x41ba03c8
PAGE_STRIDE = 44
PAGE_COUNT = 37
PAGE_ENTRY = 0x4007ba48  # (page number) -> PAGE_TABLE + 44 * number, number -1 when past 36
PAGE_SYN = 6  # 'SYN': no records of its own, a machine's page stands in for it

# The "page" image: a second page behind SYN on a sampler track (engine/recpage.c). A routine builds one page object
# per track key and kind of track, each from a list of page numbers in the program's data. One object of the SYN class
# serves every audio track.
PAGES_BUILD = (0x400351fa, 0x400365be)
SYN_BUILD = 0x400356be  # moveq #1,%d1 ; push ; movel #SYN_LIST,%d0 ; push: the count and the list for SYN's object
SYN_LIST = 0x401c8268  # one page number: 6
SYN_CLASS = 0x401ca37c  # the SYN page class's method table, 60 methods
SYN_KNOB = 0x40044c54  # its method at + 188: (page object, knob 0..7) -> the record behind the knob
PAGE_KNOB_METHOD = 188
PAGE_LIST, PAGE_LIST_END, PAGE_INDEX = 124, 128, 144  # in a page object: the list's begin and end, the index showing
PAGE_STEP = 0x4003c50a  # in the class's event method: with more than one page, index = (index + 1) mod count, then redraw
ACTIVE_TRACK = 0x4001ff74  # (page object + 116's value) -> the active track
MACHINE_OF = 0x4000f692  # (page object + 120's value, track) -> its machine type
VECTOR_FROM = 0x4017dbfe  # (vector, first, count, allocator): a vector of longs from an array
SYN_SIZE = 0x1ac  # bytes of a SYN page object; the page image asks for SYN_ROOM more, for its own state
SYN_ROOM = 32
SYN_DRAW = 0x40030b84  # its method at + 16: (page object, surface) draws the page
SYN_TURN = 0x40030070  # its method at + 68: (page object, event) a knob was turned; 1 when dealt with
PAGE_DRAW_METHOD, PAGE_TURN_METHOD = 16, 68
SYN_SIDE = 0x401ca474  # the method table of the SYN object's second base (the object's + 4): turns of a knob come through it
SYN_SIDE_TURN = 8  # its third entry: SYN_TURN_THUNK
SYN_TURN_THUNK = 0x400300c0  # subql #4 from the object's address ; branch to SYN_TURN
PAGE_DRAW = 0x4003a244  # the base class's draw: for each knob, the record from + 188, then its name and picture
PAGE_REDRAW = 0x400ffe22  # (page object): marks it to be drawn again
DRAW_TEXT = 0x400f8bd0  # (surface, font, x, y, mode, format, ...): formats and draws; mode 2 centres on x
FONT_NAMES = 0x443db230  # the font object stock draws a knob's name with
FMT_NAME = 0x4024e6be  # "%.5s"
EVENT_ID, EVENT_STEPS = 12, 16  # in a knob event: 1..8 the knobs and 9 LEVEL; the signed steps turned
# A seventh piece of code space: one stock function nothing reaches, 1,522 bytes (tools/deadcode.py).
CAVE_PAGE = (0x4001b51e, 0x4001bb10)
CAVE_BANK = (0x40196aba, 0x4019716c)  # the banks: 12 bytes of three numbers, then code, 1,714 bytes in all (engine/banks.c)
BANK_VARS = 12
BANK_FIRST, BANK_SECTORS, BANKS = 8192, 64 * 2048, 3
BANK_MARK_SECTOR = BANK_FIRST + BANKS * BANK_SECTORS  # 401,408: our one sector, at 196 MB
BANK_MAGIC = 0x42414e4b
SCAN_ALL = 0x401115ea  # (store): every slot's header into the store's table
PROGRESS_STEP = 0x401758e8  # (a job's progress object, done, of how many): moves the bar on the job's screen
# every place the three drive routines are named: the operand of a jsr or a lea (tests/test_sample_store.py)
DRIVE_READ_USES = (0x40081532, 0x400bb5b4, 0x400bb8c8, 0x400bbd08, 0x400bca9e, 0x400bd6e4, 0x40110100, 0x40113324, 0x40113458, 0x40113496)
DRIVE_WRITE_USES = (0x400806e0, 0x400bba58, 0x400bbd8e, 0x400bcaf0, 0x400bd67c, 0x400bd6c6, 0x40111690)
DRIVE_ERASE_USES = (0x400b644c, 0x400bc130, 0x400bd670, 0x4011019a)
CAVE_PAGE2 = (0x4008804c, 0x4008845c)  # a second run for the page, 1,040 bytes: the switch of MODE's bits, locks and the pop-up
# The meter image: two more runs nothing reaches (tools/deadcode.py). The feed's new part, behind 16 bytes of four
# numbers (engine/sampler.h, METER_PAGE on), and the page's third run.
CAVE_METER = (0x40088510, 0x4008878a)  # 634 bytes
METER_VARS = 16
METER_PAGE, METER_SRC, METER_QUIET, METER_LEVEL = (CAVE_METER[0] + 4 * k for k in range(4))
CAVE_PAGE3 = (0x401bceac, 0x401bd242)  # 918 bytes
CAVE_PAGE4 = (0x401bd514, 0x401bd66e)  # 346 bytes: a fourth run for the page, from the gain image on (tools/deadcode.py: named by nothing)
CAVE_PAGE5 = (0x401bc860, 0x401bcaba)  # 602 bytes: a fifth and a sixth, from the stops image on, for SMPL's stops (tools/deadcode.py:
CAVE_PAGE7 = (0x400b439c, 0x400b46ce)  # 818 bytes, a seventh, from the apage image on: the analog tracks' page (named by nothing)
CAVE_PAGE8 = (0x400af6aa, 0x400af848)  # 414 bytes, an eighth, from the slock image on: a step's solo (named by nothing)
CAVE_PAGE6 = (0x40088a80, 0x40088d28)  # 680 bytes   named by nothing). No one run that is left holds the 930 bytes of it
# The stops image (engine/sampler.h, STOPS): what the audio CPU says every slot holds, in the window. Four longs of
# two bits a slot, sixteen slots a long, in the two places the window has eight bytes nothing uses; and a mark at
# 0x5bc.
STOPS_LONGS = (0x808, 0x80c, 0xe38, 0xe3c)
STOPS_MARK, STOPS_OK = 0x5bc, 0xa5a5a5a5
SMPL_KNOB = 2  # the sampler's first page: SMPL's knob, as a turn names it
# The gain image (engine/sampler.h, GAIN): after the meter's four numbers, the gain the page shows and a gain a track
GAIN_VARS = 28
METER_GAIN, REC_GAINS, GAIN_TOP = CAVE_METER[0] + 16, CAVE_METER[0] + 20, 24
# The save image: takes written from the sampling page, in a job of ours (engine/keeptakes.c).
JOB_RUNNER = 0x4016ec18  # () -> stock's runner of jobs
JOB_START = 0x400bdc48  # (runner, name, what to do, what to call after): the last two are function objects of 16 bytes
FN_COPY, FN_COPY_DONE = 0x4019e90c, 0x401849aa  # (to, from): a function object is copied by its own second routine, with 2
FN_END = 0x4016dc10  # (it): and ended by it, with 3
SAVE_STATE = CAVE_KEEP[0]  # ours: how a save from the page is going, the first long of the keep code's run
# The ptn image: the takes are written when a whole pattern is saved to the project (engine/keeptakes.c, ptn_keep).
PATTERN_SAVE = 0x4001a8d2  # (manager, to the temp area, pattern, sequence, kit) -> true in the low byte when saved (4001a8d2..4001aaaa).
# A failure is clrb %d0: the rest of the long is whatever its message routine left
PATTERN_SAVE_CALLS = (0x40182754, 0x401826c0)  # (manager, 0, pattern, 1, 1): WHOLE PATTERN to the project. After the Y/N (callback 0x40182728),
# and after the naming screen (0x40182632, callback 0x401826da), which 0x401834f8 opens in its place
# for a pattern with no name in a project that has a place on the drive
PATTERN_SAVE_OTHERS = (0x400341dc, 0x40182794, 0x401827d4)  # left as they are: (1, n, 1, 1) from the main screen's keys, to the temp area;
# KIT DATA (0, n, 0, 1) and SEQUENCE DATA (0, n, 1, 0) to the project
PATTERN_MENU_WHOLE = 0x401834f8  # the menu's WHOLE PATTERN: the naming screen or the Y/N. Its two tests:
PATTERN_NAMED = 0x40015d62  # (pattern) -> its settings' name is not the empty string
PROJECT_PLACED = 0x40018c4a  # (manager) -> the project's number on the drive (PROJECT_NUMBER) is not negative
PROJECT_NUMBER = 0x40018c2c  # (manager) -> the project's number, -1 for one never saved. The pattern save asks it too
FILL_RECT = 0x400f7fb6  # (surface, x0, y0, x1, y1, colour): 0 clears, an odd number sets, a negative one inverts
SURFACE_W, SURFACE_H, SURFACE_STRIDE, SURFACE_DATA = 4, 8, 12, 16  # a surface: a column is `stride` longs, y 0 its highest bit
# How a turn of a knob changes a parameter (read for the page's REC, SRC and MODE, which switch bits
# of MODE). The base knob routine, KNOB_TURN, from + 0x1d2 on:
# UI_STATE(0x12) and KEYS_HOLDING(page + 108) and a record that can be locked: the page's method at
# + 96, PAGE_LOCK, which is + 116, PAGE_LOCKS, over every step with a trig among the sixteen on show.
# What sets that state was not found. Not used.
# else KEYS_SELECTED(page + 108), true while the key of a step inside the pattern is held: the method
# at + 156, PAGE_HELD. It calls KEYS_EDITING(keys, 1), then PAGE_EACH for each held step through
# KEYS_EACH, then KEYS_EDITED(keys).
# else the method at + 88, PAGE_PLAIN: the track's own value. Then the pop-up.
KNOB_TURN = 0x4003b870
UI_STATE = 0x40102f40  # (state) -> 0 or 1
STATE_TRIGS = 0x12
KEYS_HOLDING = 0x400c2dd6  # (page + 108's object) -> its byte at + 352: a turn has gone to held steps
KEYS_SELECTED = 0x400c3582  # (the same object) -> a byte: a held step inside the pattern
KEYS_EDITING = 0x400c2de0  # (the same object, 1): sets that byte
KEYS_EDITED = 0x400c2ede  # (the same object)
KEYS_EACH = 0x400c371c  # (the same object, a routine, 0): the routine for each held step
KEYS_HELD = 344  # in that object: 64 bits, the high long first; bit n set while step n's key is held
PAGE_KEYS, PAGE_MANAGER = 108, 104
PAGE_GET = 0x40037e50  # method + 84: (page, record, what + 164 gave or -1) -> the value in 8.8, locks apart
PAGE_PLAIN = 0x40037f9a  # method + 88: (page, record, change in 8.8, flag, a byte for an answer): the track's value
PAGE_LOCK = 0x4003820e  # method + 96: (page, record, knob, change, flag, a byte)
PAGE_LOCKS = 0x4003831a  # method + 116: (page, record, change, first step, one past the last, flag, a byte)
PAGE_LOCKABLE = 0x40038bee  # method + 140: (page, record) -> a byte, from the record's display flags
PAGE_STEP_LOCK = 0x40037942  # method + 144: (page, step, record) -> the step's lock, -1: none
PAGE_STEP_MAKE = 0x400387b4  # method + 148: (page, step, record, value): a lock at that value, and a trig if the step has none
PAGE_STEP_MOVE = 0x40038738  # method + 152: (page, step, record, change, flag, a byte): the lock moves
PAGE_HELD = 0x40038ed4  # method + 156: (page, record, change, flag, a byte)
PAGE_STEP_ARG = 0x400383e4  # method + 164: (page, step) -> what + 84 is asked with for that step
PAGE_EACH = 0x40038c3a  # what PAGE_HELD does for one step
PAGE_HOLDER = 0x40037d70  # method + 196: (page, record, track) -> KNOB_HOLDER(page + 104, record, track)
GET_METHOD, PLAIN_METHOD, LOCK_METHOD, LOCKS_METHOD, HOLDER_METHOD = 84, 88, 96, 116, 196
LOCKABLE_METHOD, STEP_LOCK_METHOD, STEP_MAKE_METHOD, STEP_MOVE_METHOD, HELD_METHOD, STEP_ARG_METHOD = 140, 144, 148, 152, 156, 164
PATTERN = 0x40019036  # (manager) -> the steps
PATTERN_LENGTH = 0x40027f3a  # (steps) -> how many
STEP_A, STEP_B = 0x4002787c, 0x400278d8  # (steps, step) -> a byte: the step has a trig, of one kind or the other
STEP_TRIG = 0x40029faa  # (steps, step, 1): a trig for a step that gets a lock and has none
STEP_SOUND = 0x40027484  # (steps, step) -> a byte, -1 mostly: what PAGE_STEP_ARG answers
# in a holder's method table, as the page's methods call them
HOLDER_PLAIN = 44  # (holder, record, change, track, flag, a byte, 1, 1)
HOLDER_LOCK = 64  # (holder, record, step) -> the lock, negative when the step has none
HOLDER_MAKE = 68  # (holder, record, value, step): a lock at that value
HOLDER_MOVE = 76  # (holder, record, change, step, flag, a byte): the lock moves
HOLDER_CLASS = 0x401c3d4c  # the method table of a track's holder (built at 0x40015110, 20 bytes a track at kit + 11628)
# a lock is kept by knob slot, 0..70, with or without a record: what the holder's lock methods end in
SLOT_OF = 0x400a5cc2  # (record) -> its knob slot
LOCK_READ = 0x4002740c  # (steps, step, slot) -> the lock, a word, -1: none
LOCK_MAKE = 0x40027fa2  # (steps, step, slot, value) -> a byte
LOCK_DROP = 0x40027fe8  # (steps, step, slot) -> a byte: no lock
LOCK_TABLE_READ, LOCK_TABLE_MAKE, LOCK_TABLE_DROP = 0x4001722a, 0x40017602, 0x4001741e  # (pattern, track, step, slot[, value])
LOCK_TRACK, LOCK_STEP = 9287, 144  # the table: 64 steps of 72 words a track (71 slots and a count), then a byte a slot
STEP_LOCKS = 0x4008b8a8  # (event, the step's row, ...): every lock of the step into the event, (slot, value) from + 20
LOCKS_APPLY = 0x4009792c  # (track, event, words): an event's locks into the words and the filter's state
REC_SLOT = 24  # the reclock image: a step's REC is a lock here (engine/sampler.h)
KIT_OF = 0x4001fdfe  # (page + 116's object) -> what PAGE_PLAIN asks about a record first
KIT_HAS = 0x4000d870  # (that, record, track) -> a byte: records up to 157 of some kinds; never machine 44's
# the pop-up a plain turn gets
POPUPS = 0x400205f8  # (page + 116's object) -> 1: none
RECORD_NAME = 0x40012b24  # (anything, record) -> the record's short name
POPUP = 0x400c347c  # (page + 108's object, format, ...)
POPUP_FORMAT = 0x4024e714  # "%s=%s"
DESCRIPTORS_BY_RECORD = 0x4022d83c  # 52 bytes a record, the machine first
# function objects most plain 0..127 knobs use
OBJ_TEXT_PLAIN = 0x41b9efd0  # calls 0x4006f930: the value as "%d"
OBJ_GFX_PLAIN = 0x41b9ecd0  # calls 0x400701b4: the knob picture, 59 plain knobs use it
OBJ_STEP_PLAIN = 0x41b9e660  # calls 0x4006f78e: FUNC + turn goes to min, middle, max
TEXT_PLAIN, TEXT_MINUS_64, TEXT_TUNE, TEXT_SLOT = 0x4006f930, 0x4007bc8a, 0x4007bc50, 0x4007ba80

# The "screen" image: SMPL, LOOP and MODE get their text from engine/knobtext.c. A text function is called as (its
# object, the value in 8.8, where to write) by TEXT_CALL, and the object it is given is the copy in the table's entry,
# so the record can be read from it.
OBJ_TEXT_SLOT = 0x41b9ece0  # the object that calls TEXT_SLOT; stock uses it for records 498 and 502 only
TEXT_SLOT_SITE = 0x40188f3c  # in UI_INIT: movel #TEXT_SLOT,%d1, stored as that object's function
TEXT_CALL = 0x4018837a  # (object, value, out): jumps to the function at object + 12
TEXT_FOR = 0x4007bbe2  # (record, value) -> the text, in TEXT_OUT, through the table's entry
TEXT_OUT = 0x41b9fbcc
UI_MANAGER = 0x4016e9c8  # () -> the manager object every page keeps
KNOB_HOLDER = 0x4001c422  # (manager, record, track) -> the object holding that knob's value; a track past 13 is the active one
KNOB_VALUE = 40  # in the holder's method table: (holder, record) -> the value, 8.8
R_SMPL, R_LOOP, R_MODE = SAMP_FIRST + 1, SAMP_FIRST + 4, SAMP_FIRST + 5
# A sixth piece of code space: one stock function nothing reaches, 848 bytes (tools/deadcode.py).
CAVE_TEXT = (0x40124852, 0x40124ba2)

# The stereo image: one-track stereo (engine/rightfill.c, engine/sampler.h ONETRACK; docs/STEREO.md). The mixer's four
# right-hand passes are handed a second set of buffers, and the copies of the two returns made before a right-hand
# pass go after that set as stock's go after its own. Each is the operand of a pea.
RIGHT_SET = 0x4556a000  # ours: 8 tracks and 2 returns, 1280 bytes, in memory nothing names (see EFFECTS_MEMORY)
CAVE_LAP = (0x401be95c, 0x401bea14)  # 184 bytes nothing reaches and nothing names: the lap image's four readings of the timer
CAVE_TRIG = (0x401beb58, 0x401bec90)  # 312 bytes nothing reaches and nothing names but itself (tools/deadcode.py): the trig image's TRIG page
CAVE_TRIG2 = (0x401bb4a4, 0x401bb592)  # 238 more nothing reaches and nothing names: the TRIG page's turn
CAVE_TRIG3 = (0x401bf1be, 0x401bf24e)  # 144 more nothing reaches and nothing names: the switch image's drawing of a switch
CAVE_TRIG4 = (0x401bf380, 0x401bf406)  # 134 more nothing reaches and nothing names: the box image's eraser, data
DOTTED_MASK = 0x402e9e74  # the mask of stock's dotted box (0x444e00b4, 17 x 17, built at 0x4014925a): 17 bits a row
CAVE_XKNOB = (0x401bdadc, 0x401bdb66)  # 138 bytes nothing reaches and nothing names: the xknob image's turn of knob D
CAVE_XKNOB2 = (0x401be044, 0x401be0c2)  # 126 more: its clearing of the other crossfades
CAVE_XSHARE = (0x401be2fa, 0x401be35e)  # 100 bytes nothing reaches and nothing names: the xshare image's taking of the crossfade
TRIG_CLASS = 0x401c9a9c  # the TRIG page class's method table (its constructor 0x40040ef2 stores it); both TRIG objects of the audio tracks
TRIG_KNOB = 0x40040eb8  # its + 188: which record is behind a knob
TRIG_DRAW = 0x40041076  # its + 16: the draw
TRIG_TURN = 0x400415d0  # its + 68: a turn of a knob
TRIG_SIDE = 0x401c9b94  # its second base's table (the object's + 4): turns come through its + 8
TRIG_TURN_THUNK = 0x400416d2  # subql #4 from the object's address ; branch to TRIG_TURN
CAVE_PRE = (0x401bf7fe, 0x401bf8dc)  # 222 bytes nothing reaches and nothing names (tools/deadcode.py): the pre image's copies
CAVE_HITS = (0x4012d408, 0x4012d630)  # 552 bytes nothing reaches and nothing names (tools/deadcode.py): the hits image's call of the filter's envelope
SOLO_GONE = CAVE_HITS[0]  # the soloend image: twelve bytes first in the hits' run, a bit a track whose note has ended, and the eight tracks' last marks
FILTER_ENV = 0x400965a4  # the filter's envelope, once a block: (the block's params, trigs, releases, tracks it skips), eight tracks
FILTER_ENV_CALL = 0x400a4ccc  # the per-block routine's call of it: jsr FILTER_ENV, after pushing d6, d4, a5 and a2
HIT_BOX_MAIN = 0x100005b4  # the window's long the hits image's sound engine says the hits in (engine/sampler.h, HITS)
# The hitui image (engine/hits.c, HITUI): the filter page
FILTER_CLASS = 0x401c9da0  # its method table (installed at 0x40042250 by its constructor 0x4004217c, key 0x15)
FILTER_DRAW = 0x4004291c  # its draw: by the page's number, FLTR1's loop (0x400424fe), FLTR2's (0x40042264) or the base's
FILTER_KNOB = 0x400420d4  # its + 188: which record is behind a knob (FLTR2's G and H: none; the fltr image's are LFO.T and FLT.T)
FLTR2_FLAT = 0x400424c8  # in FLTR2's loop, 12 bytes: FENR's test, which sends it to the record's own picture (the last argument of + 180 0)
FLTR2_DEL = 0x400424bc  # in FLTR2's loop, 6 bytes: DEL's test, which sends it to the record's own picture (the trans image: a knob on a sampler track)
CAVE_TRANS = (0x4012ff58, 0x4012ffec)  # 148 bytes nothing reaches and nothing names (rts before and at its end; tools.deadcode): the trans image's DEL knob
CAVE_NEXT = (0x4011dda4, 0x4011ded0)  # 300 bytes nothing reaches and nothing names (tools.deadcode; rts before and at its end): the next image's poll
CAVE_NEXT2 = (0x4002aba0, 0x4002acb8)  # 280 more: its two places and KIND's turn
CAVE_NEXT3 = (0x401b0d6a, 0x401b0e90)  # 294 more: its pass over the places
CAVE_NEXT4 = (0x4002cb56, 0x4002cc3e)  # 232 more: DEST to the box, and a track's KIND
CAVE_NEXT5 = (0x4002c8e6, 0x4002c9b6)  # 208 more: the slots taken
CAVE_NEWPROJ = (0x401125c2, 0x401126fa)  # 312 bytes nothing reaches and nothing names (tools.deadcode; rts before and at its end): the newproj image's NEW PROJECT
CAVE_NEWPROJ2 = (0x400f90e8, 0x400f91fa)  # 274 more: its project left, and LOAD PROJECT's way in
PROJECT_MAKE = 0x4001d16a  # (manager, project): a project made afresh, -1 one of no number (NEW PROJECT)
PROJECT_MAKE_CALLS = (0x40059fd6, 0x4005bc10)  # Project Init's (NEW PROJECT) and Project Load's for a slot that is empty
CAVE_WIPE = (0x40117848, 0x4011794c)  # 260 bytes nothing reaches and nothing names (tools.deadcode; rts before and at its end): the wipe image
CAVE_WIPE2 = (0x400b4ed6, 0x400b4fde)  # 264 more: its SysEx entry
CAVE_STREAM = (0x400d2ac4, 0x400d2bc2)  # 254 bytes nothing reaches and nothing names (tools.deadcode; rts before and at its end): the stream image's reload job
CAVE_STREAM2 = (0x400f47e2, 0x400f48da)  # 248 more: its 0x6B entry and LOAD PROJECT's 0x6C
CAVE_STREAM3 = (0x400c1f0a, 0x400c1ffa)  # 240 more: its numbers and the reload's start
CAVE_STREAM4 = (0x400b22da, 0x400b23c6)  # 236 more: LOAD PROJECT's way in
CAVE_EVICT = (0x400b4ae0, 0x400b4b8a)  # 170 bytes, named by nothing: the evict image, a reload's slots out of the scratch table
CAVE_FRESH = (0x400f79f4, 0x400f7b2c)  # 312 bytes nothing reaches and nothing names (tools.deadcode; rts before and at its end): the fresh image's new project
CAVE_KIND = (0x40132a6c, 0x40132b48)  # 220 bytes nothing reaches and nothing names (tools.deadcode; rts before and at its end): the kind image's stops by KIND
CAVE_MIRROR = (0x4016c3de, 0x4016c4fc)  # 286 bytes nothing reaches and nothing names (tools.deadcode; rts before and at its end): the mirror image's numbers, its hooks
CAVE_MIRROR2 = (0x40179e1a, 0x40179efe)  # 228 more: a frame sent
CAVE_MIRROR3 = (0x4016afaa, 0x4016b08a)  # 224 more: its bytes packed 7 to a group
CAVE_MIRROR4 = (0x40108034, 0x401080dc)  # 168 more (tools.deadcode; rts before and at its end): the sink image's writes into the sink
CAVE_TUNE = (0x401ad8cc, 0x401ad9a8)
CAVE_TUNE2 = (0x40125eb4, 0x40125f7c)
TUNE_COPY = 0x40192d58  # in UI_INIT: clrl the flags and jsr %a3@ (the copy) of record 431's entry, the sampler's TUNE
TUNE_ENTRY = 0x41ba9790  # UI_TABLE + 84 * 431: + 4 the sixteen bytes, + 8 a pushed turn's multiplier
PANEL_PAINT = 0x4011391a  # stock's: the frame drawn sent to the panel (what changed), its two pointers swapped; -> the buffer to draw next in
PANEL_COLUMNS = 0x4011384c  # stock's: (column, page, 8 bytes) -> the panel, 8 columns' bytes of one page; PANEL_PAINT's only way there
PANEL_COLUMNS_ON = 0x40113854  # PANEL_COLUMNS after its first two instructions (lea, movem: 8 bytes), where the shadow image's copy goes on
UI_DRAW_MARK = 32  # the UI's + 64: its byte here, not 0, asks for a draw (stock's setter 0x40100966)
PANEL_BRACKET = 0x40113834  # stock's: the end of a send to the panel (after the column sends)
PANEL_SHOWN = 0x402d7114  # -> the frame on the panel, after PANEL_PAINT (stock's getter 0x40113a20 reads it); 0x402d7110 the one to draw next
UI_PAINT_LEA = 0x4000a22c  # leal PANEL_PAINT,%a4 in the UI's draw: both its sends go through a4
UI_DIRTY = 0x4010095c  # stock's: (the UI's + 64) -> anything to draw
UI_DIRTY_CALL = 0x4000a220  # its call in the UI's draw, before the drawing
CAVE_PBANK = (0x401266ae, 0x40126836)  # 392 bytes nothing reaches and nothing names (tools.deadcode; rts before and at its end): the pbank image's menu entry
PROJECT_MENU_NEW = 0x401855d4  # (menu): the PROJECT menu, built once by the UI: LOAD, SAVE, MANAGE (0x400fa84c each, 0x400fa082 to add)
PROJECT_MENU_END = 0x401858b2  # its restore (movem 24 up, lea 128, rts): the pbank image jumps from here to ours
PROJECT_MENU_CLASS = 0x401d0bcc  # its method table, first long of the object; its page at + 56
DEL_GFX = 0x400706ac  # the display table's graphic of DEL and 0x89, the delay's picture: (object, value 8.8, surface, x, y)
KNOB_LABEL = 0x400385c6  # in the page's + 180 (0x4003842c): jsr 0x40012b24, the name under a knob from its descriptor
FILTER_TURN = 0x4003b870  # its + 68: the base class's turn
FILTER_SIDE = 0x401c9e98  # its second base's table (the object's + 4; named only by its constructor and 0x4017f50c): turns through its + 8
FILTER_TURN_THUNK = 0x4003bc6c  # subql #4 from the object's address ; branch to FILTER_TURN
FLTR2_NAME = 0x4004232e  # in FLTR2's loop: 28 bytes that push a knob's short name from the descriptors, the record in d2
FLTR1_DEL = 0x4004268a  # in FLTR1's loop: jsr (%a3) ; lea 24(%sp),%sp: DEL's value for the envelope's picture
POPUP_NAME = 0x4003bc28  # in the base turn routine: addq.l #8,%sp ; movea.l (%a2),%a0 ; move.l %d0,%d4, the pop-up's name in d0
DEL_RECORD = 0x3f  # the Filter record DEL (slot 31), shared by every machine
FEED_STRIDE = 0x80007d24  # ours, the nofx image: a take's or the meter's source, its step a frame in bytes (80 or 4), on-chip
PRE_WAS_SRAM = 0x80007d20  # ours, the prewas image: the frame's first long, whether the return was muted the block before, on-chip
PRE_FRAME = 0x4556b000  # ours, the pre image: a frame of 32 x 20 longs, 2,560 bytes, in the same memory nothing names (engine/recfeed.c, PRE)
RIGHT_PASSES = (0x4008f80c, 0x4008f944, 0x4008fb52, 0x4008fb6a)  # pea TRACKS: the delay send's, the reverb send's, the dry mix's, the FX block's
LEFT_PASSES = (0x4008f7f0, 0x4008f91a, 0x4008fafe, 0x4008fb1a)  # the same four for the left: left as they are
RIGHT_RETURNS = ((0x4008f92e, RETURN_DELAY), (0x4008fb2e, RETURN_DELAY), (0x4008fb3c, RETURN_REVERB))  # pea RETURN_x, the copy's "to"
LEFT_RETURNS = ((0x4008f8f4, RETURN_DELAY), (0x4008fad6, RETURN_DELAY), (0x4008faec, RETURN_REVERB))
TRACK_OUTS = (0x4008fe7a, 0x4008feac)  # the two other places the mixer names TRACKS: each track's level, and the frame's channels 2..9
DMA_WAIT = 0x400a20ae  # () waits for the transfer the per-block routine started, if one is running
# Where the routine waits for the track buffers and tests AUDIO_UP before it sends the knobs:
# jsr %pc@(DMA_WAIT) ; tstl AUDIO_UP ; beqs past the send. Ours: jsr right_fill ; tstl %d0 ; nop.
RIGHT_HOOK = 0x400a4e30
TRACKS_IN = (0x400a47fa, 0x400a4aec)  # the two places the transfer of the track buffers is started; the second is the one before the mixer
TRACKS_CLEAR = 0x400a4b26  # with the audio CPU down: pea 0x500 ; pea TRACKS: the eight buffers and the two returns are cleared
CAVE_RIGHT = (0x401bcb6c, 0x401bccc6)  # one more run nothing reaches, 346 bytes (tools/deadcode.py)
# The dma image: the right channels come out of the window by the transfer controller (engine/rightdma.c;
# docs/FINDINGS.md, "The right channels by a hardware transfer"). Stock's own channel is 47, in group 2; ours are two
# of group 0, which every other group goes before, so no transfer of stock's waits for ours.
DMA_CONTROL_SET = 0x40000546  # the startup: or 6 into the controller's control word (round robin inside a group, groups in fixed order)
DMA_47_SET = 0x400a2ee4  # channel 47's standing words, written once: 16 bytes a turn, both sides 16 on, nothing after
DMA_RIGHT = (12, 13)  # ours: the window's first stretch of nine halves, and its second of seven
DMA_STOCK = (15, 29, 30, 34, 35, 36, 37, 42, 47, 52, 54, 59)  # every channel the main program names a word of
BLOCK_FIRST_CALL = 0x400a3940  # the per-block routine's first call: jsr BLOCK_FIRST. Ours: the transfers are started, then it
BLOCK_FIRST = 0x4010222a
PRE_MIX_CALL = 0x400a502c  # its last call before the mixer's: jsr PRE_MIX. Ours: the second set is made whole, then it
PRE_MIX = 0x4009580c
SRAM_COPY = 0x4000045c  # the startup: on-chip memory's two halves are copied from the image and cleared to their ends
SRAM_LOW = (0x80007330, 0x80008000)  # the first half after what is copied to it: cleared at every start, named by nothing
RIGHT_SCRATCH = 0x80007400  # ours, while the transfers are being checked: the sixteen halves as the CPU read them
RIGHT_SRAM = 0x80007800  # ours: the second set (8 tracks and 2 returns, 1280 bytes), where a transfer may land
RIGHT_STATE = 0x80007d00  # ours: eight longs (engine/rightdma.c)
CAVE_DMA = (0x4011222c, 0x401124f4)  # 712 bytes nothing reaches and nothing names (tools/deadcode.py)
CAVE_DMA2 = (0x40115e82, 0x40116050)  # 462 more, the same: the routine before the mixer
# The effects' own memory: 9 x 64 KB the delay and reverb helpers name at 0x4d570000 (0x40096c86, 0x40096e86,
# 0x400975a4). Taken 0x08000000 lower, as the blocks of UPPER_STATICS are, it begins 39,792 bytes after the end of the
# program's data: that gap is what nothing names (tests/test_stereo.py).
EFFECTS_MEMORY = (0x4d570000, 0x4d600000)

# offsets in the main CPU's own 142-byte track parameters (slot s at 0x1c + 2*s)
P_DELAY_SEND, P_REVERB_SEND, P_PAN, P_VOL = 118, 120, 122, 124


def off(addr):
    return addr - BASE


def u32(image, addr):
    return int.from_bytes(image[off(addr):off(addr) + 4], "big")


def u16(image, addr):
    return int.from_bytes(image[off(addr):off(addr) + 2], "big")

# The phone image (engine/phone.c): one run nothing reaches and nothing names, 466 bytes after the first long's
# alignment (tools/deadcode.py, against every CAVE_ above): its numbers (PHONE_VARS bytes) and then its code.
CAVE_PHONE = (0x40126f08, 0x401270da)
PHONE_VARS = 64
CAVE_PHONE2 = (0x4013174e, 0x4013190e)  # 448 more nothing reaches and nothing names: the phone's jump, timer and bank reading
PORT_CHECK = 0x4011a280  # in the pitch routine 0x4011a1ac: mvsw %a4@(134),%d0 ; cmpil #16383,%d0 (PORT, slot 53), then bgts
CAVE_LOCK2 = (0x400af16c, 0x400af270)  # 260 bytes nothing reaches and nothing names (rts before and at its end; tools.deadcode): the lock image's KEYS names
CAVE_LOCK = (0x400eebf0, 0x400eed1e)  # 302 bytes nothing reaches and nothing names (rts before and at its end; tools.deadcode): the lock image's sends
CAVE_STRETCH = (0x400f55e6, 0x400f572c)  # 326 bytes nothing reaches and nothing names (rts before and at its end; tools.deadcode): the stretch image's KEYS
CAVE_STSW = (0x40131954, 0x40131bcc)  # 632 bytes nothing reaches and nothing names (rts before and at its end; tools.deadcode): the stsw image's stretch switch
CAVE_STSW2 = (0x40115b98, 0x40115cf4)  # 348 bytes nothing reaches and nothing names (rts before and at its end; tools.deadcode): its turn
CAVE_FLTR = (0x40131d34, 0x40131ee8)  # 436 more nothing reaches and nothing names (a whole routine, rts before and at its end): the fltr image's FLTR2 record
CAVE_PHONE3 = (0x40132614, 0x401328b4)  # 672 more nothing reaches and nothing names (a whole routine, rts before and at its end): the fltr image's load query
CAVE_SOLOEND = (0x40116fe4, 0x40117138)  # 340 bytes nothing reaches and nothing names, every word an instruction (tools/deadcode.survey): the soloend image's solos, worked out (solo_now out of the alock image's run). Not 0x40131954: not clean (the scratch image's note)
CAVE_SCRATCH = (0x4017fdbc, 0x4017ff24)  # 360 bytes nothing reaches and nothing names, every word an instruction (tools/deadcode.py): the scratch image's numbers and the drive's table
CAVE_SCRATCH2 = (0x40177f24, 0x40178122)  # 510 more, the same: the writer's job
CAVE_SCRATCH3 = (0x4017de24, 0x4017dfec)  # 456 more, the same: the start's job
CAVE_SCRATCH4 = (0x40197fee, 0x40198184)  # 406 more, the same: the save's copy and the load's drop
CAVE_SCRATCH5 = (0x40163118, 0x40163294)  # 380 more, the same: a take's first sector
CAVE_SCRATCH6 = (0x4018726e, 0x401873d2)  # 356 more, the same: the poll and its jobs' start
SCRATCH_TABLE = 401409  # the scratch image: our table, the sector after the banks' one
SCRATCH_FIRST, SCRATCH_PLACES = 401410, 47  # then 47 places of a slot's 2,048 sectors, to 497,666, under DRIVE_FREE's end
SYSEX_IN_JMP = 0x40104042  # RPC_SYSEX_IN's last instruction: jmp RPC_HANDLE, with its arguments in place

# The long image (engine/longpat.c): patterns 1..64 long, 65..128 their tails, by stock's play queue.
CAVE_LONG = (0x40022868, 0x40022a10)  # 424 bytes nothing reaches and nothing names (tools/deadcode.py; rts before and at its end)
QUEUE_SET = 0x4008c51c  # (list, count): the play queue, up to 2048 entries of 24 bytes at 0x43bcc3bc
QUEUE_SET_CALLS = (0x400097f6, 0x4000b714, 0x4001a18c, 0x4001d2ca, 0x4001d5ca, 0x4001e078, 0x4001e242, 0x4008172c, 0x40089a64,
                   0x400c431e, 0x400c466e, 0x400c5332, 0x400c54c6)
PLAYING_NUMBER = 0x400c2154  # (ignored) -> the playing pattern's number, 0..127
KIT_FOLLOW_CALL = 0x40019cb2  # in 0x40019c84: jsr PLAYING_NUMBER, the kit the UI's kit object is pointed at
CAVE_SEAM = (0x4001895a, 0x40018a4e)  # 244 bytes nothing reaches and nothing names (tools/deadcode.py; rts before and at its end)
HIT_STEP = 0x4008dae6  # (time, track, out): out[0] the nearer step, out[1] micro, out[2] that step's pattern number
HIT_STEP_CALL = 0x401050e4  # jsr HIT_STEP, in the builder of a live trig's record (kind 12, subtype 0)
LIVE_WRITE = 0x4001ecb6  # (manager, track, ..., step at arg 5, micro at arg 6, ...): writes the trig, called once
LIVE_WRITE_CALL = 0x400088c6  # jsr LIVE_WRITE, in the main task's handler of that record
LIVE_NOW_CALL = 0x4001ed02  # jsr %pc@(NOW_PATTERN), in LIVE_WRITE
LIVE_NOW_LEA = 0x4001eefa  # lea %pc@(NOW_PATTERN),%a3, in LIVE_WRITE
LIVE_NUMBER_CALL = 0x4001ef62  # jsr PLAYING_NUMBER, in LIVE_WRITE
CAVE_EDIT = (0x40018cc6, 0x40018e48)  # 386 bytes nothing reaches and nothing names (tools/deadcode.py; rts before and at its end)
PATTERN_CLEAR = 0x4001f7c0  # (manager, list, sequence, kit, undo): "Cleared %d pattern%s!"
PATTERN_CLEAR_CALLS = (0x4003368c, 0x400c5e8c, 0x4018292e, 0x401829a2, 0x40182a16)
PATTERN_PASTE = 0x4001fa0e  # (manager, list, undo): "Pasted %d Pattern%s"
PATTERN_PASTE_CALLS = (0x400335dc, 0x400c5f2a)
PATTERN_COPY = 0x4001e2a8  # (manager, n) -> a byte: "Copy Pattern %c%02d", one pattern and its kit kept
PATTERN_COPY_CALLS = (0x4003180c, 0x400c5f5a)
CAVE_EDIT2 = (0x40029b2c, 0x40029c68)  # 316 more nothing reaches and nothing names (tools/deadcode.py): the paste
