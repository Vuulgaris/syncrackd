"""Section 7 (audio CPU) map for Syntakt OS 1.41 and 1.42 (identical section).

Every number here was read from our own objdump listing of the pinned
section; tests/test_audio_map.py re-checks each one against the image.
"""
BASE = 0x40000400            # address of section byte 0
SIZE = 383760
IMAGE_END = BASE + SIZE      # 0x4005df10
ENTRY = 0x40001070
CODE_END = 0x40009f88       # last function ends here; tables follow
STACK_TOP = 0x48000000       # initial SP: SDRAM is 0x40000000..0x48000000

# boot copies (0x400004bc), then BSS clear (0x40000512)
SRAM = 0x80000000
SRAM_END = 0x80010000
SRAM_LO_SRC = (0x4004f6e0, 0x40057670)   # -> 0x80000000
SRAM_HI_SRC = (0x40057670, 0x4005df10)   # -> 0x80008000
SRAM_HI = 0x80008000
BSS = (0x4004f6e0, 0x4404f980)

# voice loop
VOICE_LOOP = 0x40004324      # (out, params, trig_mask, release_mask), 32 frames
N_VOICES = 8
VOICE_SIZE = 1800
VOICES = SRAM
PARAM_STRIDE = 142
PARAM_TYPE = 0x3e            # machine type byte, 0..45
PARAM_KNOBS = 0x1c           # slot s is the 8.8 word at +0x1c + 2*s
OUT_STRIDE = 128             # 32 frames of int32, mono, per track
OUT_BUF = 0x80003840         # as passed by the audio interrupt
PARAM_BUF = 0x80003c40
PMOD = 0x80008150            # int32 per track, semitones << 16
TYPE_TO_ENGINE = 0x40014950  # 46 bytes
UPDATE_TABLE = 0x40014920    # 12 pointers
RENDER_TABLE = 0x400148f0
N_ENGINES = 12
VOICE_RESET = 0x40003ee0
VOICE_PRE = 0x4000255e       # per voice, per block, before update
ENVELOPE = 0x40003d42
NOISE_SEED = 0x40002544
VOICE_INIT = 0x40000fd6      # mid-function in main init
VOICE_TMP = 0x80008a60       # voice+0x56c = VOICE_TMP + 0x30*i

ENGINES = ["BD MODERN", "SD BASIC", "CY ALLOY", "PC CARBON", "SY TONE", "SY CHORD",
           "SD VINTAGE", "CP VINTAGE", "SY TOY", "SY BITS", "SY SWARM", "SP TWINSHOT"]
TYPE_OF_ENGINE = [0, 1, 2, 3, 4, 5, 6, 7, 36, 37, 38, 44]

# Twinshot (engine 11)
TWIN_UPDATE = 0x400097dc
TWIN_RENDER = 0x40009a8a
SAMPLE_PITCH = 0x40006704    # (pmod, tune, player): sets player+24
SAMPLE_PLAY = 0x40006764     # (buf, player): 32 frames, linear interpolation
TWIN_FILTER = 0x400068ea
TWIN_MIX = 0x400049f4
TWIN_PLAYER_A = 1712         # offsets in the voice
TWIN_PLAYER_B = 1748
TWIN_FILTER_STATE = 1784
TWIN_BUF_A = 0x80008c60
TWIN_BUF_B = 0x80008d84

# sample pool
POOL = 0x4004f750
POOL_SIZE = 0x04000000       # 64 MB
POOL_LOAD = 0x40000cda       # SPI reader for the pool; nothing calls it (dead code)
POOL_CHUNK_COPY = 0x40000fa8 # init: copies a 2 KB chunk from the shared window at 0x800
POOL_CHUNK = 0x800
POOL_CLEAR = 0x40000d7e
SLOT_BUILD = 0x40000d06      # walks the pool, fills the slot table
SLOTS = 64
SLOT_LEN = 0x4404f754        # +8*slot: frames
SLOT_PTR = 0x4404f758        # +8*slot: pointer to int16 frames
SLOT_MAX_FRAMES = 0x7ffff    # engine clamp, 20.12 position

# Runs of stock functions with no reference anywhere in the image: no call,
# branch, lea, immediate or table entry names their start, and the code has no
# computed jumps. tests/test_engine_build.py checks this and that they never run.
CAVES = {
    "x": (0x40002d86, 0x400032b4),       # two functions, 1,326 bytes
    "y": (0x40005a8e, 0x40005f9a),       # three functions, 1,292 bytes
}
# The recorder image also takes this one: three functions, 620 bytes, right after TWIN_MIX.
REC_CAVES = {
    "z": (0x40004a6a, 0x40004cd6),
}
# The fade image also takes this one: 550 bytes, after the second of the four mono stages.
# The pitch image: five more runs nothing reaches (tools/deadcode.py). The interpolation table takes the
# recorder's run whole; the recorder's two steps, the step after the voice loop and the interpolator move here.
PITCH_CAVES = {
    "p": (0x40001708, 0x40001860),       # 344 bytes
    "q": (0x400027f6, 0x4000290e),       # 280
    "r": (0x40004708, 0x400047ea),       # 226
    "s": (0x40001900, 0x400019d6),       # 214
    "t": (0x40003512, 0x400035de),       # 204
}
HQ_MARK, HQ_TABLE = 0x44060000, 0x44060004     # free SDRAM under the takes: a long the first two builds believed, then the table's 33 rows
HQ_MADE = 0x80000700                           # voice 0's sampler state + 80, which stock's voice reset clears: the table is made since
HQ_PADS, HQ_PAD_BYTES = 0x44060800, 256        # and, a voice, the frames around its slot's two ends: 45 words a side
HQ_PAD_END, HQ_PAD_SIDE = 22, 45               # words in from a side's start to the frames around the slot's end; words a side
FADE_CAVES = {
    "w": (0x40003732, 0x40003958),
}
FADE_ONE, FADE_IN, FADE_OUT = 4096, 64, 128     # the gain that is "all of it"; frames a fade in and a fade out last
# The len and live images also take these two: 302 bytes before TWIN_MIX, and 436 bytes, two functions, before the
# sampler's first run. Both ran on the unit in the live image's first build.
LIVE_CAVES = {
    "u": (0x400048c6, 0x400049f4),
    "v": (0x40002a62, 0x40002c16),
}
ISR_VOICE_LOOP_CALL = 0x40000a34         # jsr VOICE_LOOP in the audio interrupt
# Stock Twinshot's own routines. Engine 11's two table entries are the sampler's in every image of ours, so nothing
# reaches these: and to keep the room for later.
# 1,344 bytes (tests/test_stereo.py holds them unreached in an image that leaves them alone). The stereo image's
# second build is the first to use any: the update and render, QUICK_CAVES below. The player and filter are free.
# Not in this: the stock routines the sampler calls, which Twinshot called too (SAMPLE_PITCH, ENVELOPE, the amp
# at 0x400045a0, TWIN_MIX). tools/deadcode.py does not list the first run by itself: the routine before it ends in a
# jump, not an rts, and the tool cuts code at rts.
TWIN_ROOM = {
    "update and render": (0x400097dc, 0x40009b1a),      # 830 bytes: TWIN_UPDATE, then TWIN_RENDER
    "player and filter": (0x40006764, 0x40006966),      # 514: SAMPLE_PLAY, then TWIN_FILTER
}
SPARE_RUNS = ((0x40004534, 0x400045a0), (0x40004608, 0x40004674), (0x40005624, 0x4000569a), (0x40009f1c, 0x40009f88))   # 442 more, unused
# The stereo image: one-track stereo (engine/sampler.h, ONETRACK; docs/STEREO.md). Four more runs nothing reaches.
# The first lies before the entry point, where tools/deadcode.py takes everything for live: surveyed with the
# entry's own piece as the one root, it is reached by nothing (tests/test_stereo.py).
ONE_CAVES = {
    "h": (0x40000b92, 0x40000d06),       # 372 bytes: stock's reader of a sample pool from a flash chip, which nothing calls
    "a": (0x40005964, 0x40005a0c),       # 168
    "b": (0x400050a6, 0x4000512c),       # 134
    "c": (0x40005866, 0x400058e8),       # 130
}
# The stereo image's second build (engine/sampler.h, QUICK): the sums of sixteen frames made in the multiply and
# accumulate unit, a run of frames a call. In Twinshot's update and render, the first use of that room.
QUICK_CAVES = {
    "k": TWIN_ROOM["update and render"],
}
HQ_LONGS = 0x44061000        # the table as 33 rows of 16 longs, each number shifted up 15: past the eight voices' pads
# The stereo image's third build (engine/sampler.h, LEAN): a voice's level and gain in one pass for both channels,
# in Twinshot's other run. The time image, a tool (TIMED), puts its routine after it there: the audio CPU's load
# measured on the unit, through two calls of the interrupt's.
LEAN_CAVES = {
    "m": TWIN_ROOM["player and filter"],
}
TIMED_CAVES = {                          # the time image's routine: what there is room for after the stereo image's in Twinshot's
    "m": TWIN_ROOM["player and filter"],     # run, and the rest in two of the small runs nothing reaches
    "n": SPARE_RUNS[0],
    "i": SPARE_RUNS[2],
}
# The cross image (engine/sampler.h, XFADE): the one small run nothing has taken, for the crossfade's code.
CROSS_CAVES = {
    "o": SPARE_RUNS[1],                      # 108 bytes
}
XF, XF_STRIDE = 0x44062000, 0x800         # a voice's blend: wall, target, where a pass goes in, the first frame's position; then
XF_W, XF_NEAR, XF_FAR, XF_STEP = 256, 16, 80, 8     # 352 frames a channel: 80 of the pass, 256 blended, 16 of what the seam leads to
TAKE_ONE = 1                               # the mode image: frames a mono take leaves in its second slot
# The stops image (engine/sampler.h, STOPS): what every slot holds, said to the main CPU. Two bits a slot (the length's
# lowest bit, then whether the rest is anything), sixteen slots a long with the first slot's bits the highest, a long a
# block; the mark is moved up a byte a block with 0xa5 under it. A mono take leaves two frames in its second slot.
STOPS_LONGS = (0x808, 0x80c, 0xe38, 0xe3c)  # the window: after the recorder's count and random number, and after the sampling page's box
STOPS_MARK, STOPS_OK = 0x5bc, 0xa5a5a5a5   # the window: after the right channels' long and the time image's two
STOPS_COUNT = 0x44050a18                   # free memory after the time image's: a count of blocks, any number at a start
# The srr image (engine/sampler.h, SRR): sample rate reduction. SY SWARM's code is the room: engine 10's update, then
# its render, one run that ends where Twinshot's update begins (docs/FINDINGS.md, "What SY SWARM's code would free").
# Each is named once in the section, by its table. Engine 10's two entries are a stand-in that plays nothing.
SWARM_ENGINE = 10
SWARM_UPDATE = 0x400092ec
SWARM_RENDER = 0x400096e8
SRR_CAVES = {
    "d": (SWARM_UPDATE, TWIN_UPDATE),        # 1,264 bytes
}
SRR_STATE = 0x44050a40                     # free memory after the stops image's count: a voice's hold, sixteen bytes a voice
# The hits image (engine/sampler.h, HITS): a slot's hits, a voice's place among them, the window's long that says them
HITS_STORE, HITS_BYTES = 0x44070000, 512     # a slot's: its place, frames, print, frames gone over, follower, gap, count, then 123 longs
HITS_VOICE, HITS_RR = 0x44078000, 0x44078080  # a voice's, 16 bytes: how far said, its frame a block ago, the slot, the next hit; then the slot in turn
HIT_BOX = 0x5b4                            # four bits a track, every block, where the time image's C was
# and its code, in SY TOY's and SY BITS's (engines 8 and 9): their updates and renders, one run that ends where SY
# SWARM's update begins, named by nothing once their table entries are gone (tools/deadcode.survey). Each is named
# once in the section, by its table; the two engines are handed SWARM's stand-ins, which play nothing.
TOY_ENGINE, BITS_ENGINE = 8, 9
TOY_UPDATE, TOY_RENDER, BITS_UPDATE, BITS_RENDER = 0x40008ae8, 0x40008d58, 0x40008e0c, 0x400091e0
HITS_CAVES = {
    "e": (TOY_UPDATE, SWARM_UPDATE),         # 2,052 bytes
}
# The scan image (engine/sampler.h, HITSCAN): SD BASIC's code is the room (engine 1, the maintainer's pick, 2026-10-20): its
# update, then its render, one run that ends where SD VINTAGE's update begins, named by nothing once its table entries
# are gone (tools/deadcode.survey, docs/MEMORY_MAP.md). Each is named once in the section, by its table; engine 1 is
# handed SWARM's stand-ins, which play nothing.
SDB_ENGINE = 1
SDB_UPDATE, SDB_RENDER = 0x40007c68, 0x40007f9e
SDV_UPDATE = 0x40008074
SCAN_CAVES = {
    "g": (SDB_UPDATE, SDV_UPDATE),           # 1,036 bytes
}
HITX_STORE, HITX_BYTES = 0x44066000, 256    # a slot's: the loudest step, the steps' follower, both followers at the last hit, a bin a hit
# The back image (engine/stub.S, BACK): section 7 grown past its end (docs/FINDINGS.md, "Room past section 7's end"; the pad7
# tool on the unit). Our code that was in SY SWARM's, SY TOY's and SY BITS's and SD BASIC's runs (caves d, e, g) is linked
# at FAR and carried after IMAGE_END; a copy of ours between the start's two calls (START_CALLS: jsr 0x400004bc, the SRAM
# data ; jsr 0x40000512, the BSS clear) puts it there before the clear and before the cache is on. Their runs are stock's
# again, their engines too. FAR: past the take buffers with one to spare (a take's second slot is REC_BUF(k + 1), and a
# mono take writes two frames there, so slot 63's reaches REC_BUF(64), 0x47c80000), under the stack's megabyte.
FAR = 0x44080000 + 65 * 0xf0000            # 0x47d70000
BACK_CAVES = {
    "d": (FAR, FAR + 1264),
    "e": (FAR + 0x500, FAR + 0x500 + 2052),
    "g": (FAR + 0xd10, FAR + 0xd10 + 1036),
}
FAR_BYTES = 0x1120                         # the three, 16-byte aligned: what is copied, a long at a time
START_CALLS = 0x400010b4                   # 4eba f406 4eba f458
# The stretch image (engine/sampler.h, STRETCH): its code after the back image's three (cave f), then a track's 32
# bytes of state in zeros the start's copy writes every start (STR_BASE).
STRETCH_CAVES = {                          # and the update and render in cave d have grown with it: d, e, g laid out again
    "d": (FAR, FAR + 0x600),
    "e": (FAR + 0x600, FAR + 0x600 + 2052),
    "g": (FAR + 0xe10, FAR + 0xe10 + 1036),
    "f": (FAR + 0x1220, FAR + 0x2020),
}
STR_BASE = FAR + 0x2020
FAR_BYTES_STR = 0x2120
FAR_BYTES_LOCK = 0x2160                    # the lock image: and a track's four bytes of the tempo after them (engine/sampler.h, LOCK)
GRAIN_CAVES = dict(STRETCH_CAVES, j=(FAR + 0x2160, FAR + 0x24e0))    # the grain image: grain_birth after the lock image's state,
FAR_BYTES_GRAIN = 0x24e0                   # to 9,440 bytes past section 7's end, of the 9,451 the main CPU's check lets through
# The trap image (engine/sampler.h, TRAP): CY ALLOY's code is the room (engine 2, the maintainer's pick, 2026-10-26): its
# update, then its render, one run that ends where SY TONE's update begins. In stock a long in Twinshot's code
# (0x400098b0, 0x40006f2e) reads as naming it; that code is ours (cave k) by then, so its two table entries are all that
# name it (tools/deadcode.survey on the spread image, both entries handed elsewhere: this one run, 800 bytes, appears).
ALLOY_ENGINE = 2
ALLOY_UPDATE, ALLOY_RENDER = 0x40006d7c, 0x40006ff2
TONE_UPDATE = 0x4000709c
TRAP_CAVES = {
    "al": (ALLOY_UPDATE, TONE_UPDATE),       # 800 bytes
}
STOPS_TAKE_ONE = 2
TIMER1_MODE, TIMER1_COUNT = 0xfc074000, 0xfc07400c     # the chip's second timer: stock sets its mode word to 3 at its start (0x40000dec) and names it nowhere else
TIMER1_START = 0x40000dec    # movew %d1,TIMER1_MODE, with 3 in d1; its clock is switched on two instructions before
TIMED_STATE = 0x44050a00     # free memory after the right channels': this interrupt's start, the longest, the gaps' sum, blocks
TIMED_BOX = 0x5b4            # the window, after the right channels' long: the longest stretch of 256 blocks, then the sum of their gaps
# The four stages the interrupt runs on the track buffers after the voice loop, and its calls of them
STAGE_GAIN = 0x4000112c      # (out, params): all eight tracks, in pairs. Its state is ramps made from the knobs
STAGE_DRIVE = 0x40002320     # (out, params, trig): all eight, in pairs. The base and width filter: two sums a track
STAGE_FILTER = 0x400019d6    # (params + 82, buffer, the track's long, track, trig, params + 130's word): one track
STAGE_AMPS = 0x4000168e      # (out, params, trig, release, flags): calls STAGE_AMP1 for each track
STAGE_AMP1 = 0x40001476      # (buffer, state, params + 106, trig bit, release bit, track, flag bit): one track
ISR_AMP_CALL = 0x40000abc    # jsr STAGE_AMPS in the audio interrupt
GAIN_STATE = (0x800083b0, 0x80008450)       # what STAGE_GAIN keeps: 40 longs
AMP_STATE = (0x800049e0, 0x80004a40)        # what STAGE_AMP1 keeps: 12 bytes a track
FILTER_STATE = ((0x80008550, 0x800085a0), (0x80008740, 0x80008900), (0x80008920, 0x80008960))   # the two filters'
# a track's own part of FILTER_STATE: (the first track's address, bytes a track)
FILTER_PIECES = ((0x80008550, 1), (0x80008558, 1), (0x80008560, 4), (0x80008580, 4), (0x80008740, 32),
                 (0x80008840, 12), (0x800088a0, 8), (0x800088e0, 4), (0x80008920, 8))
FILTER_LEFTOVER = 0x80008918                # two longs STAGE_FILTER leaves for its next call: types 0, 1 and 7 take them as they are
FILTER_SCRATCH = ((0x80008720, 0x80008740), (0x80008900, 0x80008920), (0x80008960, 0x80008a60))
HOST_TRACK_LONG, HOST_TRACK_FLAGS = 0x80008188, 0x800081a8
R_MASK, R_GAIN, R_AMP = 0x44050400, 0x44050410, 0x440504b0   # free SDRAM after the eight right channels (engine/sampler.h)
R_SHADOW = 0xc4048000        # added to an address of FILTER_STATE: where the right channels' copy of it is
RLIVE = 53                   # in a voice's sampler state: the right channel's filters carry on
# the right channels in the window: a long that says which tracks have one, then sixteen halves of 16 longs
RW_HEAD = 0x5b0
RW_MAGIC = 0x52570000


def rw_word(mask):
    return RW_MAGIC | (~mask & 0xff) << 8 | mask


def rw_half(h):
    """Where half h of 16 is in the window: nine before the recorder's ring, seven after the sampling page's box."""
    return 0x5c0 + 64 * h if h < 9 else 0xe40 + 64 * (h - 9)


TWIN_ENGINE = 11

FREE_SDRAM = (BSS[1], STACK_TOP)   # nothing in section 7 references it; stack grows down from the top
STASH = 0x44050000           # the sampler's right channels: 7 x 128 bytes
# the recorder (engine/sampler.h): one buffer per slot, and the main CPU's ring in the shared window
REC_BASE, REC_STRIDE, REC_MAX = 0x44080000, 0xf0000, 0x78000
MAILBOX = 0x800              # u16 seq, then 8 blocks of 32 stereo int16 frames at +16
MAILBOX_RING, MAILBOX_BLOCKS, MAILBOX_SIZE = 16, 8, 16 + 8 * 128
# keeping takes (engine/sampler.h, struct keepbox): requests from the main CPU, right after the ring
KEEP_BOX = MAILBOX + MAILBOX_SIZE    # 0xc10: req (word), slot (word), off | ack, frames, 128 longs: 512 bytes of the take
KEEP_REQ, KEEP_SLOT, KEEP_OFF, KEEP_ACK, KEEP_FRAMES, KEEP_DATA, KEEP_SIZE = 0, 2, 4, 8, 12, 16, 528
KEEP_DONE = 0xFFFFFFFF
KEEP_PUT = 0x8000            # in a request's slot: the main CPU sends a slot's samples (the load image)
KEEP_BIG = 0x4000            # with it: three sectors, the second and third in the recorder's ring (the bank image)
KEEP_MARK = 0x4B454550
KEPT = 0x4407FF00            # a long per slot, free SDRAM under the takes
# the sampling page's take (engine/sampler.h, struct recbox): the page's settings in the window, past the keep box
REC_BOX = KEEP_BOX + KEEP_SIZE       # 0xe20: mark, ~mark | dest (8 words, one a track)
REC_MARK1, REC_MARK2, REC_DEST, REC_SIZE = 0, 4, 8, 24
REC_MARK = 0x52454321
DEST_SMPL = 0xFFFF           # in dest: the stereo sample the track's SMPL is on
MODE_STEREO, MODE_REC, MODE_EXT = 1, 2, 4    # the page image's MODE: three switches in one value
# The reclock image: a step's REC is a lock on knob slot 24, at one of two marks in its high byte (engine/sampler.h).
K_REC, REC_LOCK_ON, REC_LOCK_OFF = 24, 0x52, 0x29
REC_WORD_ON, REC_WORD_OFF = 0x5280, 0x2980
LEN_MIN = 3                                  # the floor image: the least LEN (6 in its first build)
# The meter image (engine/sampler.h): the source is a number in MODE's value, above the two switches.
MODE_SRC, SRC_SHIFT = 0x7c, 2
SRC_MAIN, SRC_EXT, SRC_T1, SRC_FX, SRC_SENDS = 0, 1, 2, 14, 15
SRC_NAMES = ["MAIN", "EXT"] + ["T%d" % t for t in range(1, 13)] + ["FX", "DELRV"]
METER_EVERY, METER_STOP, METER_FALL = 96, 288, 10    # blocks between drawings; blocks undrawn before it stops; the fall's shift
BAR_X, BAR_W = 21, 104                               # the bar: from this column, this many dots at the largest sample


def off(addr):
    return addr - BASE


def u32(image, addr):
    return int.from_bytes(image[off(addr):off(addr) + 4], "big")
