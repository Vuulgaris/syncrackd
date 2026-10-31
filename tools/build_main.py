"""Patches for section 3, the main CPU program. **OS 1.42 only.**

Three things, all optional on top of the audio CPU sampler:

1. The UI descriptors of machine type 44 get the sampler's names, ranges and
defaults. Data only: eight table records, and five name strings that only
those records point at.
2. How four of those knobs are shown. START, LENGTH, LOOP and MODE were a
filter, a mix, a tune and a sample selector, and would read -64..+63,
-24..+24 and slot numbers. Ten operands in the start-up routine that
fills the display table (tools/uitable.py) are pointed at the function
objects plain knobs use, so each reads as its number.
3. The mixer link (engine/mixlink.c): code in an unreferenced function, and
the operand of the one call to the mixer. In front of it, the analog mute
(engine/amute.c) in a second unreferenced function.

4. Recorder image only (engine/recfeed.c): the call to the mixer goes through
a second piece of code, in three mix kernel variants nothing calls, that
copies audio to the audio CPU while a track records (MODE 2 and 3).

The mixer link is checked in the emulator with the mixer itself stubbed out; the descriptors are checked by reading
them back.
"""
import os

from . import build_engine, fw
from . import mainmap as mm
from . import params, uitable

REC = 0x34
F_MIN, F_MAX, F_DEFAULT, F_BIPOLAR, F_LONG, F_SHORT = 8, 0xc, 0x10, 0x14, 0x28, 0x30


def be32(v):
    return v.to_bytes(4, "big")


# strings that already exist in the image and are pointed at as they are: (address, text). Several are the tails of
# longer strings.
EXISTING = {
    "Tune": 0x4025432f, "TUNE": 0x402626b9, "Decay": 0x40254368, "DEC": 0x4025455f,
    "Length": 0x40253b79, "LEN": 0x40258893, "LOOP": 0x40258979,
    "Mode": 0x40253d94, "MODE": 0x4024bd51,
}
# strings only Twinshot's records point at, rewritten in place: (address, old, new)
REWRITE = [
    (0x402545c9, "Sample 1", "Sample"),
    (0x402545d2, "SMP1", "SMPL"),
    (0x402545d7, "Filter 1", "Start"),
    (0x402545e0, "FLT1", "STRT"),
    (0x402545e5, "Tune 2", "Loop"),
]
# LOOP: 0 off, 1 loop, 2 ping-pong. MODE: 0 mono, 1 stereo, 2 and 3 record (they play as mono on an image without the
# recorder), 4 and 5 chained mono and stereo. Same on both images.
LOOP_MAX, MODE_MAX = 0x0200, 0x0500
# The page image: MODE is three switches (engine/sampler.h), 0..7.
MODE_MAX_PAGE = 0x0700
# The meter image: the source is a number above the two switches (engine/sampler.h, MODE_SRC), 0..15.
MODE_MAX_METER = 0x3f00
# The floor image: LEN stops at 3 (engine/sampler.h, LEN_MIN). Under that a loop is a buzz.
LEN_MIN_FLOOR = 0x0300
# record index -> {field offset: (stock, new)}; records are slots 18, 19, 20, 21, 22, 23, 26, 25
RECORDS = {
    0: {F_LONG: (0x402545bd, EXISTING["Tune"]), F_SHORT: (0x40254315, EXISTING["TUNE"])},
    2: {F_DEFAULT: (0x4000, 0)},
    3: {F_DEFAULT: (0x4000, 0x7f00), F_LONG: (0x4025407f, EXISTING["Length"]),
        F_SHORT: (0x4024ec84, EXISTING["LEN"])},
    4: {F_MIN: (0x2800, 0), F_MAX: (0x5800, LOOP_MAX), F_DEFAULT: (0x4000, 0), F_BIPOLAR: (1, 0),
        F_SHORT: (0x40254324, EXISTING["LOOP"])},
    5: {F_MAX: (0x7f00, MODE_MAX), F_DEFAULT: (0x4100, 0), F_LONG: (0x402545ec, EXISTING["Mode"]),
        F_SHORT: (0x402545f5, EXISTING["MODE"])},
    7: {F_LONG: (0x402545fa, EXISTING["Decay"]), F_SHORT: (0x4025436e, EXISTING["DEC"])},
}


def _expect(image, addr, data, what):
    if image[mm.off(addr):mm.off(addr) + len(data)] != data:
        raise fw.GuardError("%s: unexpected bytes at %#x" % (what, addr))


# The mode image: MODE's lowest bit is what a take is, and a new track's takes are stereo, as every take was.
MODE_DEFAULT_AUTO = 0x0100


# The srr image: MODE's record is the reduction. Its two names are stock's own strings for it, which only that record
# points at, rewritten in place; 0 to 127 as stock has it, and 0, off, on a new track.
REWRITE_SRR = [
    (0x402545ec, "Sample 2", "Rate Red"),
    (0x402545f5, "SMP2", "SRR"),
]


# The xknob image: knob D (record 504, DEC's) is the crossfade. Its two names are ours, after the erasers in the box
# image's data run (XKNOB_NAMES); the record's range and default are DEC's, 0 to 127 and 127, which is a crossfade of
# 0.
XKNOB_SHORT, XKNOB_LONG = mm.CAVE_TRIG4[0] + 52, mm.CAVE_TRIG4[0] + 58
XKNOB_NAMES = b"XFADE\0" + b"Crossfade\0"


def descriptor_patches(image, page=False, floor=False, meter=False, auto=False, srr=False, xknob=False):
    out = []
    for text, addr in EXISTING.items():
        _expect(image, addr, text.encode() + b"\0", "string %r" % text)
    for addr, old, new in REWRITE + (REWRITE_SRR if srr else []):
        if image.count(be32(addr)) != 1:
            raise fw.GuardError("string at %#x is not used by exactly one record" % addr)
        stock = old.encode() + b"\0"
        out.append(fw.Patch(3, mm.off(addr), stock, new.encode().ljust(len(stock), b"\0"),
                            "name %r -> %r" % (old, new)))
    for k, fields in sorted(RECORDS.items()):
        rec = mm.SAMP_RECORDS + REC * k
        _expect(image, rec, be32(44), "descriptor record %d" % k)
        for field, (stock, new) in sorted(fields.items()):
            if srr and k == 5:  # the srr image: MODE's record keeps stock's names' places and stock's 127, and starts at 0
                if field != F_DEFAULT:
                    continue
                out.append(fw.Patch(3, mm.off(rec + field), be32(stock), be32(0), "descriptor 5: the reduction starts off"))
                continue
            if page and (k, field) == (5, F_MAX):
                new = MODE_MAX_METER if meter else MODE_MAX_PAGE
            if auto and (k, field) == (5, F_DEFAULT):
                new = MODE_DEFAULT_AUTO
            if xknob and k == 7:  # the xknob image: knob D's names are the crossfade's
                new = {F_LONG: XKNOB_LONG, F_SHORT: XKNOB_SHORT}[field]
            out.append(fw.Patch(3, mm.off(rec + field), be32(stock), be32(new),
                                "descriptor %d field %#x" % (k, field)))
    if floor:  # LEN's record: its least value
        out.append(fw.Patch(3, mm.off(mm.SAMP_RECORDS + REC * 3 + F_MIN), be32(0), be32(LEN_MIN_FLOOR), "descriptor 3: LEN stops at 3"))
    return out


# (instruction, its opcode, stock object, new object, what)
PEA, MOVE_TOP = b"\x48\x79", b"\x2e\xbc"  # pea abs.l ; movel #imm,%sp@
DISPLAY = [
    (0x401942b8, MOVE_TOP, 0x41b9ef70, mm.OBJ_TEXT_PLAIN, "START text"),
    (0x401942c6, PEA, 0x41b9e690, mm.OBJ_GFX_PLAIN, "START graphic"),
    (0x4019430a, PEA, 0x41b9ef70, mm.OBJ_TEXT_PLAIN, "LENGTH text"),
    (0x40194318, PEA, 0x41b9ec80, mm.OBJ_GFX_PLAIN, "LENGTH graphic"),
    (0x4019435e, PEA, 0x41b9ef90, mm.OBJ_TEXT_PLAIN, "LOOP text"),
    (0x4019436c, PEA, 0x41b9ec60, mm.OBJ_GFX_PLAIN, "LOOP graphic"),
    (0x4019437e, MOVE_TOP, 0x41b9e620, mm.OBJ_STEP_PLAIN, "LOOP step"),
    (0x401943a8, PEA, 0x41b9ece0, mm.OBJ_TEXT_PLAIN, "MODE text"),
    (0x401943b6, PEA, 0x41b9eb10, mm.OBJ_GFX_PLAIN, "MODE graphic"),
    (0x401943d8, PEA, 0x41b9e590, mm.OBJ_STEP_PLAIN, "MODE step"),
]


# Stock's start-up routine copies sixteen bytes of knob behaviour into a record's entry of the display table from a
# template. A plain 0 to 127 knob's (LEN's, the record before MODE's two, and the two after) is {1, 4, 0, an object};
# MODE's, Twinshot's sample picker, is {1, 8, 0, another}: MODE's entry is given the plain one: the register LEN's
# entry pushes, which still holds it there (the record after MODE's pushes it again).
KNOB_PLAIN, KNOB_PICKER = 0x401d6b44, 0x401d6b74
SRR_KNOB = 0x40194396  # movel %d4,%sp@- : the template for MODE's entry
SRR_KNOB_CONTEXT = [
    (KNOB_PLAIN, fw.sx("e0b8ff4e6983ae6a11aacdfb5d77170ed6472d81"), "the plain knob's sixteen bytes"),
    (KNOB_PICKER, fw.sx("cf583646fee76d78bdd20def7e1f1ffc7c936571"), "the sample picker's sixteen bytes"),
    (0x40193514, fw.sx("e6b6ff8999aeb02319cf"), "the plain knob's sixteen bytes are in a5"),
    (0x40193f38, fw.sx("4ccb72773d247f274382"), "the sample picker's are in d4"),
    (0x401942f6, fw.sx("6c0d6015e08e4a1f869d21bdf46e04bc"), "LEN's entry is given a5's sixteen bytes"),
    (0x40194392, fw.sx("b3cc69b35c7d5e0e71983516f993b992"), "MODE's entry is given d4's"),
    (0x401943e6, fw.sx("b3d4afeb1617fc376c653eea03af1b35"), "the record after MODE's is given a5's: a5 is the plain knob's on both sides"),
]


XKNOB_DISPLAY = [
    (0x40194442, PEA, 0x41b9edb0, mm.OBJ_TEXT_SLOT, "DEC text: engine/knobtext.c writes XF and the crossfade"),
    (0x40194454, MOVE_TOP, 0x41b9e7a0, mm.OBJ_GFX_PLAIN, "DEC graphic: a plain knob's, drawn again the right way up by engine/recpage.c"),
]


def display_patches(image, words=False, srr=False, xknob=False):
    out = []
    for addr, opcode, stock, new, note in XKNOB_DISPLAY if xknob else []:
        _expect(image, addr, opcode + be32(stock), "display %s" % note)
        out.append(fw.Patch(3, mm.off(addr + 2), be32(stock), be32(new), "the xknob image: display: %s" % note))
    if srr:
        for addr, stock, what in SRR_KNOB_CONTEXT:
            _expect(image, addr, bytes.fromhex(stock), "SRR's knob, " + what)
        out.append(fw.Patch(3, mm.off(SRR_KNOB), bytes.fromhex("2f04"), bytes.fromhex("2f0d"), "display: SRR turns as a plain knob does"))
    for addr, opcode, stock, new, note in DISPLAY:
        if words and note in (("LOOP text",) if srr else ("LOOP text", "MODE text")):  # the srr image: MODE's record is a plain number
            new = mm.OBJ_TEXT_SLOT  # engine/knobtext.c writes these; MODE has that object in stock
            if new == stock:
                _expect(image, addr, opcode + be32(stock), "display %s" % note)
                continue
        _expect(image, addr, opcode + be32(stock), "display %s" % note)
        out.append(fw.Patch(3, mm.off(addr + 2), be32(stock), be32(new), "display: %s" % note))
    return out


# The mute image: a muted track's trigs still fire (engine/mutetrig.c). Stock code it leans on:
MUTE_CONTEXT = [
    (mm.TRIG_EVENT, fw.sx("b1f3eda3f881647babac876696f25e8162d7c6da"), "an event's kind in d0, where it came from in d1"),
    (mm.TRIG_SOURCE, fw.sx("e27cb7f476916d438eb6"), "the mute tests are for an event from the sequencer, and d7 is 1 for them"),
    (mm.TRIG_MUTE + 6, fw.sx("478ef726d220b007807a8c4e78af39ae5c09"), "the track's bit of the mask, then the pattern's mutes, then not muted"),
    (mm.TRIG_MUTE + 0x14, fw.sx("85406428a2a2ac2b7a97f7ef4ac373c0ea1409424023ecffe609"),
     "muted: the event is dropped, and the UI is told of a trig, by which mute in d1"),
    (mm.TRIG_UNMUTED - 2, fw.sx("b5ff8a336c7ef56bf06f26f35d5be6dd3040d8803eb4"), "not muted: d0, d1, a0 and a1 are given to a call"),
    (mm.TRIG_TESTED, fw.sx("543bac642a9d324e7133"), "after the tests: the kit, into a0"),
    (mm.TRIG_TESTED + 0x24, fw.sx("cdbd214f5e1f8bef4068"), "after the tests: an event is dropped when d4 is not 0"),
    (mm.KIT_MIDI_UI - 4, fw.sx("ceb0bf3e1cc4544a557a2006caabf4d3"), "the UI: a track is a MIDI track by its bit in the kit's word"),
    (mm.KIT_MIDI_LOOP - 0x1c, fw.sx("543bac642a9d324e7133"), "the event loop: the kit"),
    (mm.KIT_MIDI_LOOP, fw.sx("c6a18b566eb4672ed37b"), "the event loop: the same word of it, a bit a track"),
    (0x400a3c2c, fw.sx("23abc38d89835a90be745bd87a5b0450b1a5a0063eed"), "the kit is set by the event that brings one"),
]


# The feed image: the routine that writes a block of a take (engine/feed.S) is in a run of its own. Stock code it
# leans on:
FEED_CONTEXT = [
    (mm.CAVE_FEED[0] - 2, "4e75", "its run starts a routine"),
    (mm.CAVE_FEED[1] - 2, "4e75", "its run ends one"),
    (0x4008f50c, fw.sx("f0d31e67dbfa708f"), "stock's mixer holds a sum to 32 bits as it does: addl, satsl"),
]


# The soloknob image: the solo image's code is not built and none of its seven places is changed (SOLO_CONTEXT is what
# they hold); a solo is a bit a track in a long of ours at the start of the run that code was in. Stock code it leans
# on:
SOLOKNOB_CONTEXT = [
    (mm.CAVE_SOLO[0] - 2, "4e75", "the run its long is in starts a routine, which nothing reaches"),
    (mm.CAVE_SOLO[1] - 2, "4e75", "and ends one"),
    (0x400a3408, fw.sx("cf1f9487c77836518ab57dd2def51c58ff3e7478"), "stock's own solos: project settings + 40, copied a long after the global mutes"),
    (mm.MUTE_READ, fw.sx("d59154fd12ba6b66ea2132c05fcd9225cd8a"), "and read by the per-block routine alone, which ours no longer follows"),
]


# The xfade image: a crossfade a sampler track, a byte a track after the solos' long. Stock code it leans on:
XFADE_CONTEXT = [
    (0x4008ffea, fw.sx("9e7174bc305ed2c4"), "the routine that makes an analog voice's level words, 0x4008ffc0: a3 is the track's parameters + 106"),
    (0x40090060, fw.sx("ae3f50d192f99209"), "it takes the volume word, + 124"),
    (0x4009007e, fw.sx("16a836353e64a533332d6eaa00caf608"), "times the track's level word, doubled and squared: a level word goes by the volume's square"),
    (mm.HOLD_WRITE, fw.sx("dc51e2da2e3bc5c575281d33"), "the store of the hold flag in the block that is sent: a0 is the track's 142 bytes, MODE at + 74"),
    (mm.HOLD_LOOP + 6, "204a", "that loop's block is a2"),
    (0x400a5032, "2f0a", "and a2 is what the mixer call is handed last, so the feed reads MODE as it is sent"),
]


# The prof image: stock code the profile leans on.
PROF_CONTEXT = [
    (0x400a38ce, fw.sx("2dc81c803c724c2a1644eadec02403e102d9"), "the per-block routine's first three instructions"),
    (0x400a5520, "4e73", "its one rte"),
    (0x400a2f30, fw.sx("3454a4d469420d1c364d9b7d185490b2"), "its address into vector 191"),
    (0x400a3764, fw.sx("1532b02946fbcb40c019db93fa0e14a3"), "the vector's long compared with it: the long is left alone"),
    (0x40000410, fw.sx("48e9c2b281b2d2841d667f2cc3e10d136407af06588fd8f7"), "the task switch saves the registers through the running task's long"),
    (0x4000044a, fw.sx("fb4643dc323abf8b98294070a5352c73a3e4cb4a"), "and stores the next task's there and takes its registers"),
    (0x400a596a, fw.sx("baa32c0db0aea8b4ba3f"), "the first timer's count read"),
    (0x400a5992, fw.sx("a9eb6fadc969dcb1cbcd450f91b111f6068b"), "and read again, the difference against a wait: it counts"),
]


def mixer_patches(image, rec=False, page=False, bank=False, mute=False, reclock=False, meter=False, stereo=False, gain=False, auto=False, feed=False,
                  soloknob=False, xfade=False, prof=False):
    # its code space is full to within 2 bytes, and the compiler's block reordering costs 4
    if xfade >= 41:  # the cut image: stock's mixer called straight, untimed (the mixtime image's split left out)
        code, syms = build_engine.compile_code(("mixlink.c",), {"m": mm.CAVE_LINK2}, "mixlink_cut",
                                               ("ONETRACK", "SOLOKNOB", "XFADE", "APAGE", "SLOCK", "XMUTE", "NODIV"), flags=("-fno-reorder-blocks",))
    elif xfade >= 33 and not EVLAP:  # the mixtime image, a tool: stock's mixer timed in the profile's record
        code, syms = build_engine.compile_code(("mixlink.c",), {"m": mm.CAVE_LINK2 if xfade >= 38 else mm.CAVE, "n": mm.CAVE_SPLIT},
                                               "mixlink_nodiv" if xfade >= 38 else "mixlink_mixtime",
                                               ("ONETRACK", "SOLOKNOB", "XFADE", "APAGE", "SLOCK", "XMUTE", "MIXSPLIT",
                                                "PROF_STR=\"%#x\"" % mm.CAVE_PROF[0]) + (("NODIV",) if xfade >= 38 else ()),  # 38: the nodiv image
                                               flags=("-fno-reorder-blocks",))
    elif xfade >= 23:  # the trig image: the track holding the crossfade is heard through a global mute
        code, syms = build_engine.compile_code(("mixlink.c",), {"m": mm.CAVE}, "mixlink_trig", ("ONETRACK", "SOLOKNOB", "XFADE", "APAGE", "SLOCK", "XMUTE"),
                                               flags=("-fno-reorder-blocks",))
    elif xfade >= 5:  # the slock image: a sampler track's solo may be a step's own
        code, syms = build_engine.compile_code(("mixlink.c",), {"m": mm.CAVE}, "mixlink_slock", ("ONETRACK", "SOLOKNOB", "XFADE", "APAGE", "SLOCK"),
                                               flags=("-fno-reorder-blocks",))
    elif xfade == 4:  # the apage image: the solo and the crossfade are the analog tracks' too, twelve of each
        code, syms = build_engine.compile_code(("mixlink.c",), {"m": mm.CAVE}, "mixlink_apage", ("ONETRACK", "SOLOKNOB", "XFADE", "APAGE"),
                                               flags=("-fno-reorder-blocks",))
    elif xfade:  # the xfade image: every other track is turned down by a track's crossfade
        code, syms = build_engine.compile_code(("mixlink.c",), {"m": mm.CAVE}, "mixlink_xfade", ("ONETRACK", "SOLOKNOB", "XFADE"),
                                               flags=("-fno-reorder-blocks",))
    elif soloknob:  # the soloknob image: a solo is the sampling page's, and with any no mute counts
        code, syms = build_engine.compile_code(("mixlink.c",), {"m": mm.CAVE}, "mixlink_soloknob", ("ONETRACK", "SOLOKNOB"),
                                               flags=("-fno-reorder-blocks",))
    elif stereo:  # the stereo image: a stereo sample keeps to its track, and no track follows another
        code, syms = build_engine.compile_code(("mixlink.c",), {"m": mm.CAVE}, "mixlink_one", ("ONETRACK",), flags=("-fno-reorder-blocks",))
    else:
        code, syms = build_engine.compile_code(("mixlink.c",), {"m": mm.CAVE}, "mixlink", flags=("-fno-reorder-blocks",))
    start, end = mm.CAVE_LINK2 if xfade >= 38 and not EVLAP else mm.CAVE  # the nodiv image: the link in a run of its own
    if (start, end) == mm.CAVE_LINK2:
        for addr in (start - 2, end - 2):
            _expect(image, addr, bytes.fromhex("4e75"), "the nodiv image's run for the link starts and ends a routine")
        if any(image.count(be32(a)) for a in range(start, end, 2)):
            raise fw.GuardError("an address in the nodiv image's run for the link is named in the main program")
    stock = image[mm.off(start):mm.off(end)]
    new = code["m"] + build_engine.NOP * ((end - start - len(code["m"])) // 2)
    _expect(image, mm.MIX_CALL, b"\x4e\xb9", "mixer call")
    # where the stock code reads the mute state the link also reads
    _expect(image, mm.MUTE_READ, b"\x26\x39" + be32(mm.MUTES) + fw.sb("54f91cc7650ee3e8") + be32(mm.SOLOS), "mute and solo masks")
    _expect(image, mm.MUTE_TEST, b"\x7f\xf9" + be32(mm.PATTERN_MUTES), "pattern mutes")
    _expect(image, 0x400a3408, b"\x23\xd0" + be32(mm.MUTES), "global mutes copied in")
    _expect(image, 0x400a30b6, b"\x33\xd0" + be32(mm.PATTERN_MUTES), "pattern mutes stored")
    out = [fw.Patch(3, mm.off(start), stock, new, "mixer link code")]
    if 33 <= xfade < 41 and not EVLAP:  # the mixtime image: the timed call of stock's mixer, in a run of its own
        lo, hi = mm.CAVE_SPLIT
        for addr in (lo - 2, hi - 2):
            _expect(image, addr, bytes.fromhex("4e75"), "the mixtime image's run starts and ends a routine")
        if any(image.count(be32(a)) for a in range(lo, hi, 2)):
            raise fw.GuardError("an address in the mixtime image's run is named in the main program")
        out.append(fw.Patch(3, mm.off(lo), image[mm.off(lo):mm.off(hi)],
                            code["n"] + build_engine.NOP * ((hi - lo - len(code["n"])) // 2), "the mixtime image: stock's mixer, timed"))

    # the analog tracks' dry sound: zeroed in the control block between its last fill and its send
    _expect(image, mm.CONTROL_FILL, b"\x48\x79" + be32(mm.CONTROL), "control block: last fill")
    _expect(image, mm.CONTROL_SEND, b"\x48\x79" + be32(mm.CONTROL), "control block: send")
    _expect(image, mm.CONTROL_SEND + 14, b"\x4e\xb9" + be32(0x401021b4), "control block: send call")
    _expect(image, 0x40090060, fw.sb("857da3fa8395f7c7ebe4ea7c"), "voice level from volume; right = block + 10")
    _expect(image, mm.VOICE_TRACK, bytes((8, 9, 10, 11)), "voice to track table")
    # full image: the analog mute alone. Recorder image: the feed is linked with it, and the feed's 16-bit conversion
    # goes in the room left after the analog mute.
    caves = {"a": mm.CAVE_AMUTE}
    sources, name = ("amute.c",), "amute"
    if rec:
        # where the stock code fills the frame buffer the feed reads, and its last channel
        _expect(image, 0x4008fea6, b"\x41\xf9" + be32(mm.FRAME), "frame fill")
        _expect(image, 0x400962e4, fw.sb("f5cfef6b772736ce"), "receive unpack")
        _expect(image, 0x40082fe8, b"\x2f\x3c" + be32(mm.MAILBOX), "boot chunk window")
        # the flag that keeps the feed out of that window while the boot loader uses it
        _expect(image, mm.AUDIO_UP_SET, b"\x23\xc0" + be32(mm.AUDIO_UP), "audio CPU up: set")
        _expect(image, mm.AUDIO_UP_CLEAR, b"\x42\xb9" + be32(mm.AUDIO_UP), "audio CPU up: clear")
        _expect(image, mm.AUDIO_UP_TEST, b"\x4a\xb9" + be32(mm.AUDIO_UP), "audio CPU up: test")
        caves["r"] = mm.CAVE_REC
        sources, name = ("amute.c", "recfeed.c"), "recfeed_bank" if bank else "recfeed_page" if page else "recfeed"
    if mute:  # the mute image: the routine in front of stock's trig test, in the feed's run
        for addr, stock, what in MUTE_CONTEXT:
            _expect(image, addr, bytes.fromhex(stock), "a muted track's trigs, " + what)
        sources, name = sources + ("mutetrig.c",), ("recfeed_mode" if auto else "recfeed_gain" if gain else "recfeed_stereo" if stereo else "recfeed_meter" if meter
                                                    else "recfeed_reclock" if reclock else "recfeed_mute")
    defines = ("MIX_NEXT=%#x" % syms["mix_link"],)
    if meter:  # the meter image: the feed's routines move to a run of their own, behind four numbers
        for addr, stock, what in METER_CONTEXT:
            _expect(image, addr, bytes.fromhex(stock), "the meter, " + what)
        caves["n"] = mm.CAVE_METER
        defines += ("METER",)
        for addr, stock, what in HOLD_CONTEXT:  # and a step's REC gets past stock's hold flag, in the room the feed left
            _expect(image, addr, bytes.fromhex(stock), "a step's REC, " + what)
        sources += ("recword.S",)
    if reclock:  # the reclock image: a step's REC is a lock on knob slot 24
        defines += ("RECLOCK",)
    if rec and page:  # the page image: "from the external input" is a bit of MODE of its own
        defines += ("PAGE",)
    if rec and bank:  # the bank image: no feed while slots are loaded
        defines += ("BANKS",)
    if gain:  # the gain image: a track's record gain, before the 32 bits are made 16
        defines += ("GAIN",)
    if auto:  # the mode image: a mono take is the source's two sides added and halved
        defines += ("AUTO",)
    if feed:  # the feed image: a block of a take is written by feed.S, in a run of its own
        for addr, stock, what in FEED_CONTEXT:
            _expect(image, addr, bytes.fromhex(stock), "the feed's block, " + what)
        caves["f"] = mm.CAVE_FEED
        defines += ("FEED",)
        sources, name = sources + ("feed.S",), "recfeed_feed"
    if soloknob:  # the soloknob image: the analog mute goes by the page's solos too, and the long they are in
        for addr, stock, what in SOLOKNOB_CONTEXT:
            _expect(image, addr, bytes.fromhex(stock), "the solo knob, " + what)
        if image.count(be32(mm.SOLO_WORD)):
            raise fw.GuardError("the address of the solo knob's long is named in the main program")
        out.append(fw.Patch(3, mm.off(mm.SOLO_WORD), image[mm.off(mm.SOLO_WORD):mm.off(mm.SOLO_WORD) + 4], bytes(4),
                            "the solo knob: a bit a track, none at a start"))
        defines += ("SOLOKNOB",)
        name = "recfeed_soloknob"
    if xfade:  # the xfade image: the analog voices go down too, MODE is sent as stereo, and the eight bytes
        for addr, stock, what in XFADE_CONTEXT:
            _expect(image, addr, bytes.fromhex(stock), "the crossfade, " + what)
        many = 16 if xfade >= 5 else 12 if xfade == 4 else 8  # the apage image: twelve, the analog tracks' after the eight. The slock image: and a long, this block's solos
        if any(image.count(be32(mm.XFADES + k)) for k in range(many)):
            raise fw.GuardError("an address of the crossfades' eight bytes is named in the main program")
        if not mm.SOLO_WORD + 4 == mm.XFADES < mm.XFADES + many <= mm.CAVE_SOLO[1]:
            raise fw.GuardError("the crossfades' eight bytes must follow the solos' long in its run")
        out.append(fw.Patch(3, mm.off(mm.XFADES), image[mm.off(mm.XFADES):mm.off(mm.XFADES) + many], bytes(many),
                            "the crossfade: a number a track, 0 at a start"))
        defines += ("XFADE", "APAGE", "SLOCK") if xfade >= 5 else ("XFADE", "APAGE") if xfade == 4 else ("XFADE",)
        name = "recfeed_slock" if xfade == 5 else "recfeed_apage" if xfade == 4 else "recfeed_xfade"
        if xfade >= 6:  # the alock image: the solos are worked out for all twelve tracks, in a run of their own
            for addr in (mm.CAVE_ALOCK[0] - 2, mm.CAVE_ALOCK[1] - 2):
                _expect(image, addr, bytes.fromhex("4e75"), "the solos' run starts and ends a routine")
            _expect(image, 0x40097a7e, bytes.fromhex(fw.sx("157c1490f580f65dba783903f5cf39b504d0")), "stock reads the analog tracks' machines after the eight")
            caves["t"] = mm.CAVE_ALOCK
            defines += ("ALOCK",)
            name = "recfeed_alock"
        if xfade >= 7:  # the multi image: every track that says record is fed, a block of the window a track
            defines += ("MULTI",)
            name = "recfeed_multi"
        if xfade >= 8:  # the srr image: REC and SRC are the track's own word on slot 24, read by the per-block routine in a run of its own
            for addr, stock, what in SRR_CONTEXT:
                _expect(image, addr, bytes.fromhex(stock), "the track's word on slot 24, " + what)
            for addr in (mm.CAVE_SRR[0] - 2, mm.CAVE_SRR[1] - 2):
                _expect(image, addr, bytes.fromhex("4e75"), "the per-block routine's run starts and ends a routine")
            if any(image.count(be32(mm.CAVE_SRR[0] + k)) for k in range(0, 12, 2)):
                raise fw.GuardError("an address at the start of the per-block routine's run is named in the main program")
            caves["w"] = mm.CAVE_SRR
            defines += ("SRR",)
            name = "recfeed_srr"
        if prof:  # the prof image, a tool: the per-block interrupt timed, and the record a source of a take
            for addr, stock, what in PROF_CONTEXT:
                _expect(image, addr, bytes.fromhex(stock), "the profile, " + what)
            for addr in (mm.CAVE_PROF[0] - 2, mm.CAVE_PROF[1] - 2):
                _expect(image, addr, bytes.fromhex("4e75"), "the profile's run starts and ends a routine")
            if any(image.count(be32(a)) for a in range(mm.CAVE_PROF[0], mm.CAVE_PROF[1], 2)):
                raise fw.GuardError("an address in the profile's run is named in the main program")
            if [mm.BASE + o for o in range(0, mm.CODE_END - mm.BASE, 2) if image[o:o + 4] == be32(mm.BLOCK_IRQ)] != [0x400a2f32, mm.BLOCK_IRQ_TEST + 2]:
                raise fw.GuardError("the per-block routine's address must be named twice: where its vector is set and where it is compared")
            caves["y"] = mm.CAVE_PROF
            defines += ("PROF",)
            sources, name = ("prof.S",) + sources, "recfeed_prof"  # first: its record is first in the run
            if xfade >= 13:  # the pre image: a take's sources and the meter's are taken before the mixer, and the FX track's mute is one
                for addr in (mm.CAVE_PRE[0] - 2, mm.CAVE_PRE[1] - 2):
                    _expect(image, addr, bytes.fromhex("4e75"), "the copies' run starts and ends a routine")
                if any(image.count(be32(a)) for a in range(mm.CAVE_PRE[0], mm.CAVE_PRE[1], 2)):
                    raise fw.GuardError("an address in the copies' run is named in the main program")
                caves["p"] = mm.CAVE_PRE
                defines += ("PRE",)
                name = "recfeed_pre"
        if xfade >= 23:  # the trig image: the analog mute hears the crossfade's track through a global mute too
            defines += ("XMUTE",)
            name = "recfeed_trig"
        if xfade >= 26:  # the xknob image: a sampler track's crossfade is read from its knob on slot 25 every block
            defines += ("XKNOB",)
            name = "recfeed_xknob"
        if xfade >= 31:  # the slice image: KEYS, bit 1 of the track's word, sent as bit 7 of slot 24's low byte
            defines += ("SLICE",)
            name = "recfeed_slice"
        if xfade >= 41:  # the cut image: the interrupt's hook to the profile only with it on
            defines += ("CUT",)
        if xfade >= 42:  # the nofx image: no FX track mute, no frame of ours: a take reads the buffers
            defines += ("NOFX",)
        if xfade >= 48:  # the soloend image: a sampler step's solo lock over when its note is
            for addr in (mm.CAVE_SOLOEND[0] - 2, mm.CAVE_SOLOEND[1] - 2):
                _expect(image, addr, bytes.fromhex("4e75"), "the soloend image's run starts and ends a routine")
            if any(image.count(be32(a)) for a in range(mm.CAVE_SOLOEND[0], mm.CAVE_SOLOEND[1], 2)):
                raise fw.GuardError("an address in the soloend image's run is named in the main program")
            caves["e"] = mm.CAVE_SOLOEND
            defines += ("SOLOEND", "SOLOEND_AT=%#x" % mm.SOLO_GONE)
        if xfade >= 40:  # the prewas image: the pre frame's flag on-chip, so nothing is stored at 0x4556b000 with no take or meter
            defines += ("PREWAS",)
        if xfade >= 34:  # the fast image: a block with nothing to change goes straight to stock's mixer (timed)
            defines += ("FAST", "MIX_FAST=%#x" % (mm.MIX if EVLAP or xfade >= 41 else syms["mix_timed"]))  # the evtime tool: stock's mixer, untimed
            name = "recfeed_soloend" if xfade >= 48 else "recfeed_nofx" if xfade >= 42 else "recfeed_cut" if xfade >= 41 else "recfeed_prewas" if xfade >= 40 else "recfeed_fast"
            for addr in (mm.CAVE_FAST[0] - 2, mm.CAVE_FAST[1] - 2):
                _expect(image, addr, bytes.fromhex("4e75"), "the fast image's run starts and ends a routine")
            if any(image.count(be32(a)) for a in range(mm.CAVE_FAST[0], mm.CAVE_FAST[1], 2)):
                raise fw.GuardError("an address in the fast image's run is named in the main program")
            caves["k"] = mm.CAVE_FAST
    if xfade >= 53:  # the stretch image: KEYS's stretch, bit 3 of the track's word, sent as bit 6 of slot 24's low byte; SPD (PTIM's slot 52) copied into the block
        defines += ("STRETCH",)
        name = "recfeed_stretch"
    if xfade >= 54:  # the lock image: KEYS's tempo lock, bit 4; SPD, the tempo and the lock sent in turn
        run = mm.CAVE_LOCK
        for addr in (run[0] - 2, run[1] - 2):
            _expect(image, addr, bytes.fromhex("4e75"), "the lock image's run starts and ends a routine")
        if any(image.count(be32(a)) for a in range(run[0], run[1], 2)):
            raise fw.GuardError("an address in the lock image's run is named in the main program")
        caves["m"] = run
        defines += ("LOCK",)
        name = "recfeed_lock"
    if xfade >= 58:  # the stsw image: a step's stretch, slot 17's low byte, over the track's bit
        defines += ("STSW",)
        name = "recfeed_stsw"
    if xfade >= 61:  # the next image: bit 6 of the track's word is KIND, and a word with it is signed too
        defines += ("NEXT",)
        name = "recfeed_next"
    if xfade >= 81:  # the handrec image: stopped, a track at ONCE records a note played by hand
        defines += ("HANDREC", "HAND_REC=%#x" % mm.HAND_REC, "HAND_HOLD=%#x" % mm.HAND_HOLD)
        name = "recfeed_handrec"
    code, more = build_engine.compile_code(sources, caves, name, defines)
    if feed and not (mm.CAVE_FEED[0] == more["feed_block"] and "gained" not in more and len(code["f"]) > 0):
        raise fw.GuardError("the feed's block routine must be feed.S's, first in its run")
    notes = {"a": "analog mute code" + (" and the feed's 16-bit conversion" if rec else ""), "r": "recorder feed code",
             "n": "the meter's numbers, the feed and the meter's level", "f": "the feed's block routine", "t": "a step's solo: this block's solos", "e": "the soloend image: this block's solos, a lock over when its note is",
             "w": "a sampler track's REC and SRC: eight bytes, and the per-block routine",
             "p": "a take's sources copied before the mixer, and the FX track's mute",
             "k": "the fast image: a block with nothing to change, straight to stock's mixer",
             "y": "the profile: its record, the interrupt's two ends, the record as a take's block, and the feed",
             "m": "the lock image: a stretched track's blocks, and SPD, the tempo and the lock sent in turn"}
    if prof and not (more["prof_vars"] == mm.CAVE_PROF[0] and code["y"][:mm.PROF_RECORD + 8] == bytes.fromhex("5052") + bytes(mm.PROF_RECORD + 6)):
        raise fw.GuardError("the profile's record must be first in its run, its mark and nothing else")
    if xfade >= 8 and not (more["srr_dirty"] == mm.SRR_DIRTY and code["w"][:8] == bytes(8)):
        raise fw.GuardError("the srr image's eight bytes must be first in the routine's run, and 0")
    for cave, (start, end) in sorted(caves.items()):
        new = code[cave] + build_engine.NOP * ((end - start - len(code[cave])) // 2)
        out.append(fw.Patch(3, mm.off(start), image[mm.off(start):mm.off(end)], new, notes[cave]))
    syms = dict(syms, **more)
    if syms["mix_amute"] != mm.CAVE_AMUTE[0]:
        raise fw.GuardError("the analog mute must come first in its code space")
    if meter and [more[k] for k in ("meter_vars",)] != [mm.METER_PAGE]:
        raise fw.GuardError("the meter's numbers must come first in their code space")
    entry = "mix_rec" if rec else "mix_amute"
    out.append(fw.Patch(3, mm.off(mm.MIX_CALL + 2), be32(mm.MIX), be32(syms[entry]), "mixer call"))
    if xfade >= 54:  # the lock image: stock's portamento off on a stretched sampler track (engine/recword.S, port_gate)
        out.append(fw.Patch(3, mm.off(mm.PORT_CHECK), bytes.fromhex(fw.sx("fc2d2f4e244807905501279c5d7c")),
                            b"\x4e\xb9" + be32(syms["port_gate"]) + build_engine.NOP * 2, "the pitch routine's PORT: off on a stretched sampler track"))
    if prof:  # linkw %fp,#-164 ; moveml %d0-%a5,%sp@ -> jmp prof_irq ; nop
        out.append(fw.Patch(3, mm.off(mm.BLOCK_IRQ), bytes.fromhex(fw.sx("10ab4ee62deaa1067ce5e67c")), b"\x4e\xf9" + be32(syms["prof_gate" if xfade >= 41 else "prof_irq"]) + build_engine.NOP,
                            "the per-block interrupt's first two instructions: to the profile's routine, which does them"))
    if mute:  # movel %fp@(-56),%d1 ; asrl %d2,%d1 -> jsr mute_trig
        out.append(fw.Patch(3, mm.off(mm.TRIG_MUTE), bytes.fromhex(fw.sx("31865c926081b3cb53e2")), b"\x4e\xb9" + be32(syms["mute_trig"]),
                            "a muted track's trigs: stock's test only for a MIDI track"))
    if meter:  # movew %d0,%a0@(76) ; lea %a0@(142),%a0 -> jsr rec_word ; nop
        out.append(fw.Patch(3, mm.off(mm.HOLD_WRITE), bytes.fromhex(fw.sx("dc51e2da2e3bc5c575281d33")), b"\x4e\xb9" + be32(syms["rec_word"]) + build_engine.NOP,
                            "slot 24 of a sampler track: REC's mark in place of stock's hold flag"))
    return out, syms


# ---- larger sample slots (the "big" image) ---------------------------------------------------
#
# Stock gives each of the 64 sample slots 1024 sectors of the +Drive, from sector 8192: 512 KB, 5.46 s. Here a slot is
# 2048 sectors from the same place: 1 MB, 10.9 s, so the samples run from 4 MB to 68 MB where stock stops at 36 MB.
# Nothing in OS 1.42 uses 36 MB to 244 MB (docs/FINDINGS.md, tests/test_sample_store.py). The slot count stays 64.
#
# Every live place that turns a slot into a place on the drive, or holds a length to a slot's size, is changed; the
# three stock routines that write or erase a slot by themselves are not, because nothing in the image reaches them.
# The routine that builds the audio CPU's pool at boot is replaced (engine/poolstage.c): what is loaded stays within
# the stock 32 MB.
BIG_SLOT_SECTORS = 2048
BIG_SLOT_MAX_BYTES = BIG_SLOT_SECTORS * 512 - 64  # of sample data: 524,256 frames
POOL_STAGE = (0x40082334, 0x4008242a)  # the stock pool builder, all of it
# (address, stock bytes, new bytes, what)
BIG_SLOTS = [
    # the scan: sector = (slot << 10) + 8192, and twice the frame count held to 524,224
    (0x401114dc, "720a", "720b", "scan: slot << 11"),
    (0x40111574, fw.sx("9ef2be803952fdf302ba"), "263c000fffc0", "scan: a slot holds 1,048,512 bytes"),
    # the header reader: sector = (slot + 8) << 10, same limit
    (0x40113306, fw.sx("6a83e08fadd1373ea710"), "123c000b5880", "header: (slot + 4) << 11"),
    (0x40113356, fw.sx("edb9448ed5784bd2867b"), "0c80000fffc0", "header: a slot holds 1,048,512 bytes"),
    # the data reader: byte address = (slot + 8) << 19
    (0x40113428, fw.sx("10c23b7fbc828a30"), "72145884", "data: (slot + 4) << 20"),
    # rename: the header's sector again, (slot + 8) << 10
    (0x40111f52, "5086", "5886", "rename: slot + 4"),
    (0x40111f60, "700a", "700b", "rename: << 11"),
    # the /samples/<slot> route, slot from 1: address = (slot << 19) + 0x380000, size held to 0x80000
    (0x400b9eb6, fw.sx("3226fb605cf2cdbd2076"), fw.sx("02b14e3cf63706b894f6"), "route: size held to 1 MB"),
    (0x400b9ebe, "7008", "7010", "route: size held to 1 MB"),
    (0x400b9ee6, fw.sx("de78779083472bff"), fw.sx("d36b9ddcafc9ef3b"), "route: slot << 20"),
    (0x400b9f16, fw.sx("f1961b71fe0c291856e4"), "068600300000", "route: + 3 MB"),
    # the slot list for the computer: size held to 0x80000
    (0x400ba1c2, fw.sx("3226fb605cf2cdbd2076"), fw.sx("02b14e3cf63706b894f6"), "list: size held to 1 MB"),
    (0x400ba1ca, "7008", "7010", "list: size held to 1 MB"),
]
# stock code the above relies on, and the dead routines left as they are
BIG_CONTEXT = [
    (0x401114fa, "e3a8", "scan: the shift"), (0x4011150e, fw.sx("d8b00c938932e717651b"), "scan: + 8192"),
    (0x40113316, "e3a8", "header: the shift"), (0x4011331c, fw.sx("54d30cccca4093c7e1f1"), "header: sector mask"),
    (0x4011342c, "e3ac", "data: the shift"), (0x40113438, fw.sx("5161258b3923d60bd88b"), "data: bytes to sectors"),
    (0x40111f62, "e1ae", "rename: the shift"),
    (0x400b9ec0, "4840", "route: swap"), (0x400b9ef4, "e3ae", "route: the shift"),
    (0x400ba1cc, "4840", "list: swap"),
    (0x4008287a, fw.sx("1c8d04e33b82f02f"), "the one call to the pool builder"),
    (0x40082332, "4e75", "pool builder: starts a routine"), (0x40082428, "4e75", "pool builder: its end"),
    (0x400823f8, fw.sx("3cc887720049ca252444"), "pool builder: stock frees its buffer"),
]


# The "double" image sends the pool in two halves (engine/poolhalves.c): the builder fills the block with one half at
# a time and the sender asks it where each chunk is. Stock code it leans on:
HALVES_CONTEXT = [
    (0x40082fb6, fw.sx("e89bba9dbbbfdd6b378be1ba6809acdcba9b661d"), "sender: chunks from the length in the block"),
    (0x40082fc6, fw.sx("d3dd39f327baab1e694f"), "sender: command 2"),
    (0x40082fce, fw.sx("b135bc3e70b81a690f841d7503170034"), "sender: the chunk index, to the window as a word"),
    (0x40082fe6, fw.sx("88e547baddc82b59030575eef422"), "sender: copy 2 KB from the address in d0 to the window"),
    (0x40082ff4, fw.sx("d9f3f40ff878899f8886ba599022"), "sender: the index goes up after the copy"),
    (0x4008301e, fw.sx("24a7746ae05e19cc1cc8"), "sender: done when the index reaches the chunk count"),
    (0x40083158, fw.sx("95bbecfeef0b2e558780"), "exchange: the index starts again from 0"),
    (0x40083174, fw.sx("1fef241c9b0c8e66a353642a8c423cf5"), "exchange: one wake of the sender a chunk"),
    (0x400828e4, fw.sx("8749e5a925b1172b76dd"), "watcher: progress is the index going up"),
    (0x400828f8, fw.sx("7379a85c440ee0dd6f75"), "watcher: progress clears the stall count"),
    (0x40082970, fw.sx("6cc802e0d242261ce222087e664d"), "watcher: a timeout past 18 ticks"),
    (0x40082e68, fw.sx("ad573c2fcaddda9224bc5892"), "watcher: started every 0x20"),
    (0x40082a48, fw.sx("0d4ec4c986e9cb2a97ad3ae8"), "the block's address, for the stock builder only"),
    (0x401132ec, fw.sx("d95c8c71fa394939"), "the header reader's first instruction"),
]
POOL_CHUNK_STOCK = fw.sx("ebd4d917a20049744385bc200f411adc")  # lsll %d1,%d0 ; pea 0x800 ; addil #block + 5,%d0


def bigslot_patches(image, halves=False):
    out = []
    for addr, stock, what in BIG_CONTEXT:
        _expect(image, addr, bytes.fromhex(stock), "larger slots, " + what)
    for addr, stock, new, what in BIG_SLOTS:
        out.append(fw.Patch(3, mm.off(addr), bytes.fromhex(stock), bytes.fromhex(new), "larger slots, " + what))
    start, end = POOL_STAGE
    if halves:
        for addr, stock, what in HALVES_CONTEXT:
            _expect(image, addr, bytes.fromhex(stock), "pool in two halves, " + what)
        code, syms = build_engine.compile_code(("poolhalves.c",), {"p": POOL_STAGE, "h": mm.CAVE_HALVES}, "poolhalves")
        lo, hi = mm.CAVE_HALVES
        more = code["h"] + build_engine.NOP * ((hi - lo - len(code["h"])) // 2)
        out.append(fw.Patch(3, mm.off(lo), image[mm.off(lo):mm.off(hi)], more, "pool in two halves: code"))
        # the sender: pea 0x800 ; jsr pool_chunk ; nop. The address comes back in d0, where stock had it.
        site = bytes.fromhex(fw.sx("828b8ef615a3a450")) + b"\x4e\xb9" + be32(syms["pool_chunk"]) + build_engine.NOP
        out.append(fw.Patch(3, mm.off(mm.POOL_CHUNK_SITE), bytes.fromhex(POOL_CHUNK_STOCK), site, "pool in two halves: the sender asks where a chunk is"))
    else:
        code, syms = build_engine.compile_code(("poolstage.c",), {"p": POOL_STAGE}, "poolstage")
    if syms["pool_stage"] != start:
        raise fw.GuardError("the pool builder must start where the stock one does")
    new = code["p"] + build_engine.NOP * ((end - start - len(code["p"])) // 2)
    out.append(fw.Patch(3, mm.off(start), image[mm.off(start):mm.off(end)], new, "larger slots, pool builder"))
    return out, syms


# ---- keeping takes (the "keep" image) ----------------------------------------------------------
#
# Saving a project also writes every take that is not on the +Drive yet into its two sample slots
# (engine/keeptakes.c). The two calls to the routine that saves a project are pointed at our routine, which calls the
# stock one first. It needs the larger slots: a take is up to 10.24 s. stock code it calls or leans on: (address,
# stock bytes, what)
KEEP_CONTEXT = [
    (mm.PROJECT_SAVE - 2, fw.sx("7b66f4ea524ccf23329f"), "the project save routine starts here"),
    (0x4005baca, fw.sx("280b4c95ff1c71cea69070ba3fc07dd5"), "first call: progress, project, manager"),
    (0x4005badc, fw.sx("b1ddeee3f4bedfaa"), "first call: the result is a byte"),
    (0x4005bc26, fw.sx("c961fc8c205dba3851b0"), "second call: three arguments"),
    (0x4005b662, fw.sx("9fb4d982cb47513f2390"), "the Project Save job runs the first caller"),
    (0x4005b688, fw.sx("f90092cb7954d7912986"), "the job's name"),
    (0x4005b4f6, fw.sx("b2f349e6dbbc6f66a687"), "its screen says SAVING"),
    (mm.SAMPLE_STORE, fw.sx("22e5b81f68be607e"), "the store's accessor"),
    (mm.STORE_WRITE, fw.sx("18e89bbef125e463098e1ad4"), "the store's write"),
    (0x401116a8, fw.sx("ccaa057bd4da6e0ba79b"), "the store's write: no progress callback when its third long is 0"),
    (0x401116c0, fw.sx("66bbf9333ae70d6cc6e386cf"), "the store's write: (sector, bytes, data) to the drive"),
    (mm.SAMPLE_SCAN - 2, fw.sx("40b0409fb5571521c06a"), "the scan starts a routine"),
]


# The load image: loading a project puts the drive's samples back in the slots that hold a take the drive does not
# have (the load half of engine/keeptakes.c, in the same run of code). The one call to the routine that loads a
# project for the Project Load job goes to ours.
LOAD_CONTEXT = [
    (mm.PROJECT_LOAD - 2, fw.sx("3384ac7d04f620519f4709cb5b13"), "the project load routine starts here"),
    (mm.PROJECT_LOAD_CALL - 12, fw.sx("5dd98d04bc6cc541f06756c17c9bcba2"), "the call: progress, project, manager"),
    (mm.PROJECT_LOAD_CALL + 6, fw.sx("d14a395d4a3c33f7"), "the call: the result is a byte"),
    (0x4005bb64, fw.sx("19d23083713726a7e9efbc584ec9950875421dd09e94c859"), "the caller first asks the store whether the project is there"),
    (0x4005d9dc, fw.sx("05fe51daad9834bd6088"), "the Project Load job runs the caller"),
    (0x4005da0c, fw.sx("09f154d11f114fe8ed0d"), "the job's name"),
    (0x4005d8c4, fw.sx("982f6d729e8f3243a3f8"), "its screen says LOADING"),
    (mm.STORE_READ, fw.sx("b6d9bf12331bc74d483c54d7c552f4ed"), "the store's read"),
    (mm.STORE_READ + 0x26, fw.sx("1c1fc3a9674434ec24339cee84eccd90"), "the store's read: its lock, then the drive's read"),
    (mm.STORE_READ + 0x4a, fw.sx("c5f6cc4cff20e574b06afbc0"), "the store's read: (sector, bytes, where to) to the drive"),
]


# The bank image: three sample banks (engine/banks.c, with the save and load hooks of engine/keeptakes.c built for
# it). Every place that names one of the three drive routines names ours for it instead, which moves a sample's sector
# to the loaded bank and jumps to stock's.
BANK_CONTEXT = [
    (mm.DRIVE_READ, fw.sx("80371ac315a7d6cbb04ed0c6ccc21f30117df467930d3ceb"), "the drive's read: (sector, bytes, where to)"),
    (mm.DRIVE_WRITE, fw.sx("80371ac315a7d6cbb04ed0c6ccc21f30117df467930d3ceb"), "the drive's write: (sector, bytes, from where)"),
    (mm.DRIVE_ERASE, fw.sx("aecba973aa331f7dd595c9846d3ab923"), "the drive's erase: the sector is its first argument"),
    (mm.SCAN_ALL, fw.sx("78b83bd270602281953612cd36ab9ce6c05a6f55c4663fcda445e5f1bff85929"), "the scan of all 64 slots: (store)"),
    (mm.STORE_READ + 0x4a, fw.sx("521166fb15bffaaeb0b86fc501b8637cd0c88ee5"), "the store's read: the drive's read answers 0 when it went well"),
    (0x40110526, fw.sx("0c3a9ae3d5b4844f9c675a42"), "a project is a number up to 128"),
    (0x4005bb9c + 6, fw.sx("372192b59941de9d3c9a2960"), "the Project Load job hands the project's number to the load"),
    (0x4001a6fa, fw.sx("9fc8897a17a6d7994620629eeaf8fa5425b697091e52d304bb9c"), "stock's load moves the bar: (the progress object, done, of how many), if its third long is set"),
]


# The save image: the takes are written from the sampling page in a job of ours (engine/keeptakes.c, save_start).
# Stock code it calls or leans on:
SAVE_CONTEXT = [
    (mm.JOB_RUNNER, fw.sx("641e44358b45f955cbcc375478ed24b48932"), "the runner of jobs: made once, then handed out"),
    (mm.JOB_START, fw.sx("6dc71f9317459189cdc2b0854c208d09ad06"), "a job is started: the runner is its first argument"),
    (mm.JOB_START + 0x30, fw.sx("21806844c5ddc4b75c23"), "a job is started: the name is a string, its second"),
    (mm.JOB_START + 0x6c, fw.sx("302bdaf0712f286ebe2e5aaf19c79c8d31298786"), "a job is started: its fourth and third arguments are copied as function objects"),
    (mm.JOB_START + 0x3e, fw.sx("2a64abe448478696f73d"), "a job is started: the fourth by this routine"),
    (mm.JOB_START + 0x4c, fw.sx("b7ad60c27cb175477665"), "a job is started: the third by this one"),
    (mm.FN_COPY, fw.sx("0e005a67c092bf864dfedbeb7dc4e0dd9529c7258c6f5dbe123d4aac5b92e0634975371489a16e32a6007bbc6d590ef8"),
     "a function object is copied: the routine at + 8 is called with (to, from, 2), and + 8 and + 12 go across"),
    (mm.FN_COPY_DONE, fw.sx("0e005a67c092bf864dfedbeb7dc4e0dd9529c7258c6f5dbe123d4aac5b92e0634975371489a16e32a6007bbc6d590ef8"),
     "and the other kind the same way"),
    (mm.FN_END, fw.sx("b8ef09e1fa8af3df817b5ea3f80d8639ffccc49bf4d6aead0f22"), "a function object is ended: the routine at + 8 with (it, it, 3)"),
    # Project Save's own job, the one this follows
    (0x4005b662, fw.sx("85006d0299ab09b1a5f7b3d19d4d9e6bb8619c4549fab13f479d61031f51408a97741ca3c989d92c8bd1e9ed6db83f642f25547270f091a9"),
     "Project Save: (the runner, its name, what to do, what to call after)"),
    (0x4005a326 + 0x1a, fw.sx("89c6c3e77f0315367e12fc4dcea83430"), "a stock storage routine: 0 asks for the type"),
    (0x4005a326 + 0x38, "2490", "a stock storage routine: 1 asks where it is"),
    (0x4005ba50 + 0x86, fw.sx("ebed3a6f49fa915414a29b8f113e"), "what Project Save's job does: the project save, its answer a byte"),
    (0x4005ba50 + 0x9a, fw.sx("9d53ca62bf91a2a1"), "what Project Save's job does: it answers 0 when that went well"),
    (0x4005cbc0, fw.sx("cf47b80b798fdf99f29bde9df391aec6e3cd6b9e"), "what Project Save's job calls after: (its storage, the answer)"),
]


# The ptn image: the takes are written when a whole pattern is saved to the project (engine/keeptakes.c, ptn_keep).
# Stock has one pattern save and five calls of it; the two behind the pattern menu's SAVE TO PROJ, WHOLE PATTERN go to
# ours, which calls stock's and then starts the save image's job. Stock code it calls or leans on:
PTN_CONTEXT = [
    (mm.PATTERN_SAVE - 2, fw.sx("22e8f96d1dcf3adb3518977455a5e0d09ebc6834efb14b7883dd"),
     "the pattern save starts a routine: (manager, to the temp area, pattern, ...)"),
    (mm.PATTERN_SAVE + 0x14, fw.sx("1344a85f4177fed0a26d4f1128939556e293"), "the pattern save: sequence and kit are its fourth and fifth, each a byte"),
    (mm.PATTERN_SAVE + 0x22, fw.sx("af8d6d8fc1d21419075ed4777f5f6953"), "the pattern save: to a project with no number is its first failure"),
    (mm.PATTERN_SAVE + 0x10a, fw.sx("d57a8bec977d00a0e9580a5470f766a9030cafc0"), "the pattern save: a failure is a message and a byte of 0"),
    (mm.PATTERN_SAVE + 0x1be, fw.sx("58c7802814dcfc37"), "the pattern save: 1 when it went well"),
    (mm.PATTERN_SAVE + 0x1ce, fw.sx("a87b7677de32be65d65008708753"), "the pattern save: both end here"),
    # the two calls that go to ours
    (mm.PATTERN_SAVE_CALLS[0] - 0x2c, fw.sx("83d1e240481480d9f8a05791"), "the Y/N's callback: nothing on a no"),
    (mm.PATTERN_SAVE_CALLS[0] - 14, fw.sx("38614552eb950b588ce0923da831eb768456"), "after the Y/N: (manager, 0, pattern, 1, 1)"),
    (mm.PATTERN_SAVE_CALLS[0] + 6, fw.sx("dd379213c56b9079bd2b1e9b31d70357"), "after the Y/N: the answer is not read"),
    (mm.PATTERN_SAVE_CALLS[1] - 14, fw.sx("38614552eb950b588ce0923da831eb768456"), "after the naming screen: (manager, 0, pattern, 1, 1)"),
    (mm.PATTERN_SAVE_CALLS[1] + 6, fw.sx("21888f3429644f650d7e8a4c507c3c8bf2e1"), "after the naming screen: the answer is not read"),
    (0x40182688, fw.sx("1086b604189a5405eaa03bbf9995611451d49ad225174f3b"), "before it the kit is named, and the pattern before that"),
    (0x401826fa, fw.sx("7a0f8158055aae3a816a"), "the naming screen's callback calls that routine"),
    # when stock takes which
    (mm.PATTERN_MENU_WHOLE + 0x52, fw.sx("a776c84adbc4a35ec205fc34aafd98613f9c1b4d76ece88267430fe9cc37aec38276e3adaaed"),
     "WHOLE PATTERN: a pattern with a name gets the Y/N, and so does one in a project with no place; else the naming screen"),
    (mm.PATTERN_MENU_WHOLE + 0xfa, fw.sx("e92e94664b341ec3a2fd"), "the Y/N's callback"),
    (mm.PATTERN_MENU_WHOLE + 0x192, fw.sx("7492067f0d29557c8cd4"), "the naming screen's callback"),
    (mm.PATTERN_NAMED + 0x20, fw.sx("1d7b6bab1398d12e006bfe4ce2d06828aa71d7cdd8c95b8436cc7d15"), "a pattern is named when its name is not this string"),
    (0x4025006d, "00", "which is the empty one"),
    (mm.PROJECT_PLACED, fw.sx("bf6b8b7c58449b6727d344af9b6a1250e87fca6cc2d5a534"), "a project has a place when its number is not negative"),
    # the three that stay stock's
    (mm.PATTERN_SAVE_OTHERS[0] - 18, fw.sx("6b7f01fe092c7816bd34d86c46844912deea75e7828c"), "the main screen's save: to the temp area"),
    (mm.PATTERN_SAVE_OTHERS[1] - 12, fw.sx("b05c6a69114c4b9a2ff6592746ec0a23"), "KIT DATA: no sequence"),
    (mm.PATTERN_SAVE_OTHERS[2] - 12, fw.sx("1ee10232663cfcb37791555f98dd820f"), "SEQUENCE DATA: no kit"),
]


def keep_patches(image, load=False, bank=False, save=False, ptn=False, phone=False, knows=False, capture=False, scratch=False, mirror=False, seen=False, fresh=False, newproj=False, wipe=False, stream=False, evict=False):
    out = []
    for addr, stock, what in KEEP_CONTEXT:
        _expect(image, addr, bytes.fromhex(stock), "keeping takes, " + what)
    for addr, stock, what in SAVE_CONTEXT if save else ():
        _expect(image, addr, bytes.fromhex(stock), "a save from the page, " + what)
    for addr, stock, what in PTN_CONTEXT if ptn else ():
        _expect(image, addr, bytes.fromhex(stock), "a pattern's save, " + what)
    start, end = mm.CAVE_KEEP
    if bank:
        for addr, stock, what in LOAD_CONTEXT + BANK_CONTEXT:
            _expect(image, addr, bytes.fromhex(stock), "banks, " + what)
        lo, hi = mm.CAVE_BANK
        caves = {"k": mm.CAVE_KEEP, "v": (lo, lo + mm.BANK_VARS), "b": (lo + mm.BANK_VARS, hi)}
        if scratch:  # the scratch image: takes held on the drive, in two runs of their own (engine/scratch.c)
            runs = dict(zip("stuwxy", (mm.CAVE_SCRATCH, mm.CAVE_SCRATCH2, mm.CAVE_SCRATCH3, mm.CAVE_SCRATCH4, mm.CAVE_SCRATCH5, mm.CAVE_SCRATCH6)))
            for run in runs.values():
                for addr in (run[0] - 2, run[1] - 2):
                    _expect(image, addr, bytes.fromhex("4e75"), "the scratch image's runs start and end a routine")
                if any(image.count(be32(a)) for a in range(run[0], run[1], 2)):
                    raise fw.GuardError("an address in the scratch image's runs is named in the main program")
            caves.update(runs)
        if stream:  # the stream image: the reload of the slots the phone writes after a load, in two runs of its own
            for run in (mm.CAVE_STREAM, mm.CAVE_STREAM3):
                for addr in (run[0] - 2, run[1] - 2):
                    _expect(image, addr, bytes.fromhex("4e75"), "the stream image's runs start and end a routine")
                if any(image.count(be32(a)) for a in range(*run, 2)):
                    raise fw.GuardError("an address in the stream image's runs is named in the main program")
            caves["a"] = mm.CAVE_STREAM
            caves["c"] = mm.CAVE_STREAM3
        if evict:  # the evict image: a reload's slots out of the scratch table, in a run of its own
            for addr in (mm.CAVE_EVICT[0] - 2, mm.CAVE_EVICT[1] - 2):
                _expect(image, addr, bytes.fromhex("4e75"), "the evict image's run starts and ends a routine")
            if any(image.count(be32(a)) for a in range(*mm.CAVE_EVICT, 2)):
                raise fw.GuardError("an address in the evict image's run is named in the main program")
            caves["e"] = mm.CAVE_EVICT
        code, syms = build_engine.compile_code(("keeptakes.c", "banks.c") + (("scratch.c",) if scratch else ()), caves,
                                               "keeptakes_evict" if evict else "keeptakes_stream" if stream else "keeptakes_newproj" if newproj else "keeptakes_scratch" if scratch else "keeptakes_phone" if phone else "keeptakes_ptn" if ptn else "keeptakes_save" if save else "keeptakes_bank",
                                               (("LOAD", "BANKS", "SAVE", "PTN") if ptn else ("LOAD", "BANKS", "SAVE") if save else ("LOAD", "BANKS"))
                                               + (("PHONE",) if phone else ()) + (("SCRATCH",) if scratch else ()) + (("NEWPROJ",) if newproj else ()) + (("STREAM",) if stream else ()) + (("EVICT",) if evict else ()))
        if scratch and syms["scr_vars"] != mm.CAVE_SCRATCH[0]:
            raise fw.GuardError("the scratch image's numbers are not first in its run")
        if save and syms["save_state"] != mm.SAVE_STATE:
            raise fw.GuardError("the save's number is not where engine/sampler.h says")
        if (syms["bank_now"], syms["bank_want"], syms["bank_busy"]) != (lo, lo + 4, lo + 8):
            raise fw.GuardError("the banks' two numbers are not where engine/sampler.h says")
        new = code["v"] + code["b"] + build_engine.NOP * ((hi - lo - len(code["v"]) - len(code["b"])) // 2)
        out.append(fw.Patch(3, mm.off(lo), image[mm.off(lo):mm.off(hi)], new, "banks: code"))
        for cave in "stuwxy" if scratch else ():
            slo, shi = caves[cave]
            out.append(fw.Patch(3, mm.off(slo), image[mm.off(slo):mm.off(shi)], code[cave] + build_engine.NOP * ((shi - slo - len(code[cave])) // 2),
                                "the scratch image: code"))
        for cave, (slo, shi) in (("a", mm.CAVE_STREAM), ("c", mm.CAVE_STREAM3)) if stream else ():
            out.append(fw.Patch(3, mm.off(slo), image[mm.off(slo):mm.off(shi)], code[cave] + build_engine.NOP * ((shi - slo - len(code[cave])) // 2),
                                "the stream image: the reload"))
        for cave, (slo, shi) in (("e", mm.CAVE_EVICT),) if evict else ():
            out.append(fw.Patch(3, mm.off(slo), image[mm.off(slo):mm.off(shi)], code[cave] + build_engine.NOP * ((shi - slo - len(code[cave])) // 2),
                                "the evict image: a reload's slots out of the scratch table"))
        for uses, routine, sym in ((mm.DRIVE_READ_USES, mm.DRIVE_READ, "bank_read"), (mm.DRIVE_WRITE_USES, mm.DRIVE_WRITE, "bank_write"),
                                   (mm.DRIVE_ERASE_USES, mm.DRIVE_ERASE, "bank_erase")):
            for site in uses:
                if image[mm.off(site):mm.off(site) + 2] not in (b"\x4e\xb9", b"\x45\xf9", b"\x49\xf9", b"\x4b\xf9"):  # jsr, lea a2, a4, a5
                    raise fw.GuardError("banks: %#x does not name a drive routine the way it did" % site)
                _expect(image, site + 2, be32(routine), "banks, a place that names a drive routine")
                out.append(fw.Patch(3, mm.off(site + 2), be32(routine), be32(syms[sym]), "banks: a drive routine named"))
    elif load:
        for addr, stock, what in LOAD_CONTEXT:
            _expect(image, addr, bytes.fromhex(stock), "loading, " + what)
        code, syms = build_engine.compile_code(("keeptakes.c",), {"k": mm.CAVE_KEEP}, "keeptakes_load", ("LOAD",))
    else:
        code, syms = build_engine.compile_code(("keeptakes.c",), {"k": mm.CAVE_KEEP}, "keeptakes")
    new = code["k"] + build_engine.NOP * ((end - start - len(code["k"])) // 2)
    out.append(fw.Patch(3, mm.off(start), image[mm.off(start):mm.off(end)], new, "keeping takes: code"))
    for call in mm.PROJECT_SAVE_CALLS:
        _expect(image, call, b"\x4e\xb9" + be32(mm.PROJECT_SAVE), "keeping takes, a call to the project save routine")
        if fresh and call == mm.PROJECT_SAVE_CALLS[1]:
            continue  # the fresh image: a new project's save goes by the phone's code, below
        out.append(fw.Patch(3, mm.off(call + 2), be32(mm.PROJECT_SAVE), be32(syms["save_keep"]), "keeping takes: project save call"))
    if load:
        call = mm.PROJECT_LOAD_CALL
        _expect(image, call, b"\x4e\xb9" + be32(mm.PROJECT_LOAD), "loading, the call to the project load routine")
        target = syms["load_keep"]
        if phone:  # the phone image: the call goes to ours, which asks the phone and then calls load_keep
            pcaves = {"v": (mm.CAVE_PHONE[0], mm.CAVE_PHONE[0] + mm.PHONE_VARS), "p": (mm.CAVE_PHONE[0] + mm.PHONE_VARS, mm.CAVE_PHONE[1]),
                      "q": mm.CAVE_PHONE2}
            if knows:  # the fltr image: the load query, in a third run
                pcaves["r"] = mm.CAVE_PHONE3
            if fresh:  # the fresh image: a new project's save and ask, in a fourth
                pcaves["f"] = mm.CAVE_FRESH
            if newproj:  # the newproj image: the maker's two calls, in a fifth and a sixth
                pcaves["g"] = mm.CAVE_NEWPROJ
                pcaves["h"] = mm.CAVE_NEWPROJ2
            if wipe:  # the wipe image: the empty slots, in a seventh and an eighth
                pcaves["i"] = mm.CAVE_WIPE
                pcaves["j"] = mm.CAVE_WIPE2
            if stream:  # the stream image: 0x6B and the load's 0x6C, in a ninth
                pcaves["l"] = mm.CAVE_STREAM2
                pcaves["m"] = mm.CAVE_STREAM4
            pcode, psyms = build_engine.compile_code(("phone.c",), pcaves,
                                                     "phone_stream" if stream else "phone_wipe" if wipe else "phone_newproj" if newproj else "phone_fresh" if fresh else "phone_seen" if seen else "phone_mirror" if mirror else "phone_capture" if capture else "phone_knows" if knows else "phone",
                                                     ("PHONE", "LOAD_KEEP_AT=%#x" % target) + (("KNOWS",) if knows else ())
                                                     + (("CAPTURE", "CAPTURE_AT=%#x" % mm.CAVE_RXGATE[0]) if capture else ())  # the rxcap image
                                                     + (("MIRROR", "MIRROR_AT=%#x" % mm.CAVE_MIRROR[0]) if mirror else ())  # the mirror image: the viewer's on and off
                                                     + (("SEEN",) if seen else ())  # the ask image: the phone asked only once it has said 0x63
                                                     + (("FRESH", "SAVE_KEEP_AT=%#x" % syms["save_keep"]) if fresh else ())  # the fresh image: a new project asks too
                                                     + (("NEWPROJ", "NEW_SLOTS_AT=%#x" % syms["new_slots"]) if newproj else ())  # the newproj image: NEW PROJECT too
                                                     + (("WIPE",) if wipe else ())  # the wipe image: the unit empties the slots the phone names
                                                     + (("STREAM", "STREAM_ADD_AT=%#x" % syms["stream_add"]) if stream else ()))  # the stream image
            if psyms.get("phone_mask") is None:
                psyms["phone_mask"] = mm.CAVE_PHONE[0]
            pnew = pcode["v"] + bytes(mm.PHONE_VARS - len(pcode["v"])) + pcode["p"]
            pnew += build_engine.NOP * ((mm.CAVE_PHONE[1] - mm.CAVE_PHONE[0] - len(pnew)) // 2)
            out.append(fw.Patch(3, mm.off(mm.CAVE_PHONE[0]), image[mm.off(mm.CAVE_PHONE[0]):mm.off(mm.CAVE_PHONE[1])], pnew, "the phone: code"))
            qnew = pcode["q"] + build_engine.NOP * ((mm.CAVE_PHONE2[1] - mm.CAVE_PHONE2[0] - len(pcode["q"])) // 2)
            out.append(fw.Patch(3, mm.off(mm.CAVE_PHONE2[0]), image[mm.off(mm.CAVE_PHONE2[0]):mm.off(mm.CAVE_PHONE2[1])], qnew, "the phone: code, the second run"))
            if knows:
                lo, hi = mm.CAVE_PHONE3
                for addr in (lo - 2, hi - 2):
                    _expect(image, addr, bytes.fromhex("4e75"), "the load query's run starts and ends a routine")
                if any(image.count(be32(a)) for a in range(lo, hi, 2)):
                    raise fw.GuardError("an address in the load query's run is named in the main program")
                rnew = pcode["r"] + build_engine.NOP * ((hi - lo - len(pcode["r"])) // 2)
                out.append(fw.Patch(3, mm.off(lo), image[mm.off(lo):mm.off(hi)], rnew, "the fltr image: the load query"))
            _expect(image, mm.SYSEX_IN_JMP, b"\x4e\xf9" + be32(0x40109d0c), "the phone, the SysEx entry's jump to the handler")
            out.append(fw.Patch(3, mm.off(mm.SYSEX_IN_JMP + 2), be32(0x40109d0c), be32(psyms["stream_sysex" if stream else "wipe_sysex" if wipe else "knows_sysex" if knows else "phone_sysex"]), "the phone: SysEx entry"))
            if fresh:  # the fresh image: stock's new project, saved, then asks the phone as a load does
                lo, hi = mm.CAVE_FRESH
                for addr in (lo - 2, hi - 2):
                    _expect(image, addr, bytes.fromhex("4e75"), "the fresh image's run starts and ends a routine")
                if any(image.count(be32(a)) for a in range(lo, hi, 2)):
                    raise fw.GuardError("an address in the fresh image's run is named in the main program")
                fnew = pcode["f"] + build_engine.NOP * ((hi - lo - len(pcode["f"])) // 2)
                out.append(fw.Patch(3, mm.off(lo), image[mm.off(lo):mm.off(hi)], fnew, "the fresh image: a new project's save and ask"))
            if newproj:  # the newproj image: both calls of the project maker, NEW PROJECT's and an empty slot's
                for cave, (lo, hi) in (("g", mm.CAVE_NEWPROJ), ("h", mm.CAVE_NEWPROJ2)) + ((("i", mm.CAVE_WIPE), ("j", mm.CAVE_WIPE2)) if wipe else ()) + ((("l", mm.CAVE_STREAM2), ("m", mm.CAVE_STREAM4)) if stream else ()):
                    for addr in (lo - 2, hi - 2):
                        _expect(image, addr, bytes.fromhex("4e75"), "the newproj image's runs start and end a routine")
                    if any(image.count(be32(a)) for a in range(lo, hi, 2)):
                        raise fw.GuardError("an address in the newproj image's runs is named in the main program")
                    gnew = pcode[cave] + build_engine.NOP * ((hi - lo - len(pcode[cave])) // 2)
                    out.append(fw.Patch(3, mm.off(lo), image[mm.off(lo):mm.off(hi)], gnew, "the newproj image: NEW PROJECT asks the phone"))
                if image.count(be32(mm.PROJECT_MAKE)) != 3:
                    raise fw.GuardError("the project maker is not named three times")
                for call in mm.PROJECT_MAKE_CALLS:
                    _expect(image, call, b"\x4e\xb9" + be32(mm.PROJECT_MAKE), "the newproj image, a call of the project maker")
                    out.append(fw.Patch(3, mm.off(call + 2), be32(mm.PROJECT_MAKE), be32(psyms["fresh_make"]), "the newproj image: the project maker's call"))
            if fresh:
                call = mm.PROJECT_SAVE_CALLS[1]
                out.append(fw.Patch(3, mm.off(call + 2), be32(mm.PROJECT_SAVE), be32(psyms["fresh_save"]), "the fresh image: a new project's save, then the phone"))
                call = mm.PROJECT_LOAD_CALL
            syms = dict(syms, **psyms)
            target = psyms["stream_load" if stream else "fresh_load" if newproj else "knows_load" if knows else "phone_load"]  # (the newproj image: the project left first)
        out.append(fw.Patch(3, mm.off(call + 2), be32(mm.PROJECT_LOAD), be32(target), "loading: project load call"))
    if ptn:
        calls = mm.PATTERN_SAVE_CALLS + mm.PATTERN_SAVE_OTHERS
        # five calls, and nothing else in the program names the routine: a sixth would be a save not looked at
        if image.count(be32(mm.PATTERN_SAVE)) != len(calls):
            raise fw.GuardError("the pattern save is not named %d times" % len(calls))
        for addr, n in ((0x40182728, 1), (0x401826da, 1), (0x40182632, 2), (mm.PATTERN_MENU_WHOLE, 1), (mm.PROJECT_PLACED, 1)):
            if image.count(be32(addr)) != n:
                raise fw.GuardError("the routine at %#x is not named %d times" % (addr, n))
        for call in calls:
            _expect(image, call, b"\x4e\xb9" + be32(mm.PATTERN_SAVE), "a pattern's save, a call to the pattern save routine")
        for call in mm.PATTERN_SAVE_CALLS:
            out.append(fw.Patch(3, mm.off(call + 2), be32(mm.PATTERN_SAVE), be32(syms["ptn_keep"]), "a pattern's save: a whole pattern to the project"))
    return out, syms


# ---- names and words on screen (the "screen" image) --------------------------------------------
#
# SMPL shows the stereo sample's name when MODE counts stereo samples, and LOOP and MODE show words
# (engine/knobtext.c). Our routine takes the place of the stock slot text function in its function object; LOOP's text
# is pointed at that object too (display_patches). stock code it calls or leans on: (address, stock bytes, what)
SCREEN_CONTEXT = [
    (mm.TEXT_SLOT - 2, fw.sx("3d99d2e73d2acd05c81d"), "the slot text function starts here"),
    (mm.TEXT_SLOT + 4, fw.sx("2c1478325720f9ded6a9"), "the slot text function: the value is its second argument, 8.8"),
    (0x4007bbac, fw.sx("e8705512d28ee1e3419b5595eaad"), "the slot text function: writes the name as a string at its third argument"),
    (mm.TEXT_SLOT_SITE + 6, fw.sx("908a1abbb025058c773eabb62dce"), "the function goes to the slot text object, + 12"),
    (mm.TEXT_CALL, fw.sx("1fe9457740277ac5bde7a0f63e9b0be0"), "the call of a text object: (object, value, out)"),
    (mm.TEXT_CALL + 0x20, fw.sx("d61728c67e73bce7370df75a842e"), "the call of a text object: the object is passed on, the function is at + 12"),
    (mm.TEXT_FOR + 0x1a, fw.sx("94286def8159a1e69796bc0b053d1a7d"), "a record's text object is the table + 0x14 + 84 x record"),
    (mm.UI_MANAGER - 2, fw.sx("61b40ee97ca771ec215f"), "the manager's accessor"),
    (mm.KNOB_HOLDER, fw.sx("61299195dc1eb28251f1"), "the holder routine: a track past 13"),
    (mm.KNOB_HOLDER + 0x1a, fw.sx("4e448a67ef9b3f97782ebf606848508078dad7a45f4b2ef4"), "the holder routine: is the active one"),
    (0x40037d70, fw.sx("afcfee3bf32e861d0145343d92695cf546113bf3"), "a page asks the holder routine with its manager"),
    (0x40037f40, fw.sx("6ac48278228419507aae5f3ff33eb2a8c3650feb"), "the page's getter: the holder for (record, -1)"),
    (0x40037f62, fw.sx("c1dbfb6ae4aae61b7b816dd2c3d6"), "the page's getter: the value is the holder's method at + 40"),
]


def screen_patches(image, page=False, meter=False, auto=False, pack=False, xknob=False):
    out = []
    for addr, stock, what in SCREEN_CONTEXT:
        _expect(image, addr, bytes.fromhex(stock), "names on screen, " + what)
    start, end = mm.CAVE_TEXT
    code, syms = build_engine.compile_code(("knobtext.c",), {"t": mm.CAVE_TEXT},
                                           "knobtext_xshare" if xknob == 2 else "knobtext_xknob" if xknob else "knobtext_pack" if pack else "knobtext_mode" if auto else "knobtext_meter" if meter else "knobtext_page" if page else "knobtext",
                                           ("PAGE", "METER", "AUTO", "PACK", "XKNOB", "XSHARE") if xknob == 2 else ("PAGE", "METER", "AUTO", "PACK", "XKNOB") if xknob else ("PAGE", "METER", "AUTO", "PACK") if pack else ("PAGE", "METER", "AUTO") if auto else ("PAGE", "METER") if meter
                                           else ("PAGE",) if page else ())
    new = code["t"] + build_engine.NOP * ((end - start - len(code["t"])) // 2)
    out.append(fw.Patch(3, mm.off(start), image[mm.off(start):mm.off(end)], new, "names on screen: code"))
    _expect(image, mm.TEXT_SLOT_SITE, b"\x22\x3c" + be32(mm.TEXT_SLOT), "names on screen, the slot text object's function")
    out.append(fw.Patch(3, mm.off(mm.TEXT_SLOT_SITE + 2), be32(mm.TEXT_SLOT), be32(syms["knob_text"]), "names on screen: the slot text object calls our routine"))
    return out, syms


# ---- a second page behind SYN (the "page" image) ------------------------------------------------
#
# First step toward the sampling page: on a sampler track a second press of SYN shows a second, empty page
# (engine/recpage.c). The SYN page object is built with a list of two page numbers and our routine stands in front of
# the class's "which record is behind this knob" method. stock code it calls or leans on: (address, stock bytes, what)
PAGE_CONTEXT = [
    (mm.SYN_BUILD + 10, fw.sx("a27f5d12b42d94a124a8864ff87e"), "the list and the count go to the routine that makes a vector"),
    (mm.SYN_BUILD + 0x18, fw.sx("6eec0f663919c58485b7cb9b45294da41266aaf0a9b923f57931"), "an object of 0x1ac bytes for key 0x14, built by the SYN class"),
    (mm.SYN_LIST - 8, fw.sx("6be52778c4bedb3991f92c76e6bb78b1e50bbe8065faa499"), "the lists: FLTR's two pages, SYN's one, TRIG's two"),
    (mm.SYN_KNOB - 2, fw.sx("01433d021fb2f5f02af6"), "the SYN class's knob method starts here"),
    (mm.SYN_KNOB + 0x54, fw.sx("19de2203d5ec38a9cccad3dea596e8723ad82bc5"), "the knob method: the active track from + 116, the kit at + 120"),
    (mm.PAGE_STEP, fw.sx("c18a9751259cceac3093fa6ad9b19798345b820f"), "a key press: the count is (end - begin) / 4, and one page does not step"),
    (mm.PAGE_STEP + 0x10, fw.sx("aaaadd185a13849555ecd1d73fc7011c6f89"), "a key press: index = (index + 1) mod count"),
    (mm.PAGE_ENTRY, fw.sx("b87e3490b45456829fdb"), "the page table's accessor"),
    (0x40037d9e, fw.sx("b1927335cc7d8bb301af46604356119d5586fc619579af543adf5cc0"), "the base class's knob method: the list at + 124, the index at + 144"),
    (mm.ACTIVE_TRACK - 2, fw.sx("1a157fa718db8cf04e852c83"), "the active track's accessor"),
    (mm.MACHINE_OF, fw.sx("19d787a93c3bf0a5583bcff14586629a1472"), "a track's machine: (kit, track)"),
    (mm.MACHINE_OF + 0x4c, fw.sx("7fc772174960f3dd9d22"), "a track's machine: -1 for track 12, 35 for a MIDI track"),
    (mm.SYN_DRAW - 2, fw.sx("5f83cd7dbf388a543fd1e8bede1914cba6d1f9a3b608"), "the SYN class's draw: (page object, surface)"),
    (mm.SYN_TURN, fw.sx("1af7b21fd429a7dbaddd45cb1669cd135d4da552"), "the SYN class's knob routine: (page object, event)"),
    (mm.SYN_TURN + 0x3e, fw.sx("bb7d696156d4da702d38"), "the SYN class's knob routine goes on to the base one"),
    (mm.SYN_TURN_THUNK, fw.sx("24f7b5f466fb1a7d8a24"), "a turn's way in: 4 off the object's address, then the SYN class's knob routine"),
    (0x40044b3e, fw.sx("60337498bd14fb5031fb759b2d4318de2bb70d06"), "the SYN object's + 4 is given the second base's method table"),
    (0x40037d9e, fw.sx("e74fd6a42f5aa35c"), "the base knob method: knob 8 is LEVEL's"),
    (0x4003bada, "7001", "the base knob routine answers 1 for a knob it has dealt with"),
    (0x400f67f6, fw.sx("0ba5d196a7301a9a0aa8f8ec545546eacff8"), "a knob event: the knob is the long at + 12, less 1, up to 7"),
    (0x400f6866, fw.sx("43401da917d4401b6149a5fe"), "a knob event: the steps are the long at + 16"),
    (mm.PAGE_DRAW + 0xc, "7419", "the base draw: the first place is at x 25"),
    (mm.PAGE_DRAW + 0x32, fw.sx("26e86353d7b7977c"), "the base draw: knobs 0..3 at y 34"),
    (mm.PAGE_DRAW + 0x4e, fw.sx("fd7d7b54dd6ff930360e75c95e139c71"), "the base draw asks the method at + 188 for each knob"),
    (mm.PAGE_DRAW + 0x10e, fw.sx("b4d8e56f6d700b4c"), "the base draw: knobs 4..7 are 27 higher"),
    (mm.PAGE_DRAW + 0x11c, fw.sx("4b844d328f1d76586958"), "the base draw: places are 26 apart"),
    (mm.PAGE_DRAW + 0xea, fw.sx("c0470e22c7f33cc396c8ab7a74793e30f62c89d5d42668c9264a7b9385047b352ca9"),
     "the base draw writes a name: (surface, the font, x, y, 2, \"%.5s\", the name)"),
    (mm.FMT_NAME, fw.sx("2b0e43cf81e22b6b6c"), "the format of a knob's name"),
    (mm.DRAW_TEXT, fw.sx("492efb4e152351e0f6367c28"), "the text routine"),
    (mm.DRAW_TEXT + 0x14, fw.sx("b2ad12627a6c9a30"), "the text routine: the format is its sixth argument"),
    (mm.DRAW_TEXT + 0x1a, fw.sx("a2cb9bc57312e1fa1be6ab2389b04d6d5bcb813cb4e3f8c8"), "the text routine: surface, font, x, y, mode"),
    (mm.PAGE_REDRAW, fw.sx("04fe4bd2351ac604a64906392a801f0086ffdb96"), "the redraw request: a flag in the page object"),
    # a turn's two ways to a parameter, which flip() in engine/recpage.c follows
    (mm.KNOB_TURN + 0x2d8, fw.sx("d84e4b55720d07cb1b4897f70055"), "the knob routine asks whether steps are held, of the object at + 108"),
    (mm.KNOB_TURN + 0x2e4, fw.sx("dc0691bca0f14116a033bcfe06ba3216d3b55e4e4e6077b5635bc5453e2d"),
     "they are: the method at + 156, (page, record, change, flag, a byte)"),
    (mm.KNOB_TURN + 0x33e, fw.sx("027fe141b8365dbeaf9fe3fdd731aa91e851453528b1330f"),
     "they are not: the method at + 88, (page, record, change, flag, a byte)"),
    (mm.KNOB_TURN + 0x352, fw.sx("f3eb5b08f3b837547fe6be87124df639692594a0b9074fe6"), "then the pop-up, unless this answers 1"),
    (mm.KNOB_TURN + 0x37c, fw.sx("6a30b0bfc45172ca99b22f0e61b452fadb8fdebce22a893625b0"), "the pop-up: record 502's name comes from this routine"),
    (mm.KNOB_TURN + 0x3ba, fw.sx("913d570e285985125254a261bafafe51af76ca6126b014da5b5ea8815291f1b8ef7f2cf415e89eb839f49a39b3f73dfc1bb6909f"),
     "the pop-up: (the object at + 108, \"%s=%s\", the name, the text of the value from + 84)"),
    (mm.POPUP_FORMAT, fw.sx("1a8f347f0d4a7b08ab2e"), "the pop-up's format"),
    (mm.RECORD_NAME, fw.sx("ae3347a7c7b983fd695361ba5a17ceb4476db9c8beff"), "a record's name"),
    (mm.RECORD_NAME + 0x16, fw.sx("cf7bbb2ba2d17e89776382eeaf5352f0"), "a record's name: the long at + 30 of its 52 bytes"),
    (mm.POPUPS, fw.sx("9341993c7d65e101b19b486b"), "the pop-up's gate: (the object at + 116)"),
    (mm.POPUP, fw.sx("e659208242a7ea201595d235c5e1c4fd"), "the pop-up routine"),
    (mm.SYN_CLASS + mm.GET_METHOD, fw.sx("8b1537df827cb6cb"), "the SYN class's + 84"),
    (mm.SYN_CLASS + mm.PLAIN_METHOD, fw.sx("adba4418b22e2b76"), "the SYN class's + 88"),
    (mm.SYN_CLASS + mm.STEP_LOCK_METHOD, fw.sx("1f348a37c04d58fa23c4462787d6aaec19a29293"), "the SYN class's + 144, + 148, + 152 and + 156"),
    (mm.SYN_CLASS + mm.STEP_ARG_METHOD, fw.sx("79c1276e9aec7c1e"), "the SYN class's + 164"),
    (mm.PAGE_PLAIN, fw.sx("02260f617e75651168672a30e3fe5034"), "the plain change"),
    (mm.PAGE_PLAIN + 0xd8, fw.sx("3a7b3fb69c7f70c0c473bd6044dfff2e1aba"), "the plain change: the holder for (record, -1)"),
    (mm.PAGE_PLAIN + 0xee, fw.sx("03216dce0ad38db246e505da01029b4445f46d227672afff81905e39cfa5"),
     "the plain change: the holder's + 44, (holder, record, change, track, flag, a byte, 1, 1)"),
    # what stock's + 156 does, which flip() does for itself
    (mm.PAGE_HELD + 0x26, fw.sx("185e3410ef05ff5a3fb139cc672b0a0272c5"), "held steps: the keys object is told a turn has gone to them"),
    (mm.PAGE_HELD + 0x58, fw.sx("353567f51b23d9bbf4be"), "held steps: the routine for each"),
    (mm.PAGE_HELD + 0x72, fw.sx("da67d52a7d9093e64545bc30a32a6dedc3294ab1c42d427daacd8ff8a05ac6c8d5f2bdf9597100d2694d789c"),
     "held steps: each in turn, then the keys object is told it is done"),
    (mm.KEYS_EACH + 0x26, fw.sx("487a87bbb0fa9b35e8eb60259f7586f33d18d1672e3726f98baa"), "each held step: up to the length of the manager's steps"),
    (mm.KEYS_EACH + 0x64, fw.sx("b4a681bb82a802b48225f7342003decd5b07"), "each held step: bit n of the 64 at + 344, the low long at + 348"),
    (mm.KEYS_EDITING, fw.sx("0332929aa55872686b4a325526f336367e3b212d"), "the keys object is told: with 1 it only keeps the byte"),
    (mm.KEYS_EDITING + 0x3c, fw.sx("e57b9bf47bdfb8c9"), "the keys object is told: the byte at + 352"),
    (mm.KEYS_EDITED, fw.sx("6b67bce06c956a05dc5acc93e706eeced65b0f8ef69e"), "the keys object is told it is done"),
    (mm.PAGE_EACH + 0x10, fw.sx("a4bd67ac22914e3ecfb0d6d6a507fdf804cdb1decf9065ece79049f2efdae35f"),
     "for each: + 144 with (page, step, record), not negative when the step has a lock"),
    (mm.PAGE_EACH + 0x2c, fw.sx("c623d1eed9240af3ea2c61ad8b71d811b8c33b03b80d43fe0cdccac70a85443a"),
     "for each, no lock: the value from + 84 with (page, record, what + 164 gives for the step)"),
    (mm.PAGE_EACH + 0x48, fw.sx("0bdcea0ca21887c1681f50220b38ce761e61678047709bbb"), "for each, no lock: + 148 with (page, step, record, that value)"),
    (mm.PAGE_EACH + 0x92, fw.sx("56f78e5b5aeecb5c5ff5774fb5fb746adb4fc531946208356c7c0f3abd3a6b94421dbd3138c43398"),
     "for each, a lock: + 152 with (page, step, record, change, flag, a byte)"),
    (mm.PAGE_STEP_LOCK + 0x26, fw.sx("6ac48278228419507aae5f3ff33eb2a8c3650feb"), "a step's lock: the holder for (record, -1)"),
    (mm.PAGE_STEP_LOCK + 0x50, fw.sx("18352a55be6b07f7f49e"), "a step's lock: the holder's + 64"),
    (mm.PAGE_STEP_MAKE + 0x2a, fw.sx("74b8534f4341b04e952f5a5ae72eb20276b905fb53dba8e113fc"), "a new lock: is there a trig on the step"),
    (mm.PAGE_STEP_MAKE + 0x8c, fw.sx("6f54fb9e01f17084babd90f24c955b7bb876"), "a new lock: a step without one gets one first"),
    (mm.PAGE_STEP_MAKE + 0x86, fw.sx("8db6ceeca7981445a0e7"), "a new lock: the holder's + 68"),
    (mm.PAGE_STEP_MOVE + 0x66, fw.sx("8269c24e2fe439c07b86f419595e"), "a lock moves: the holder's + 76"),
    (mm.PAGE_STEP_ARG, fw.sx("54e1eac218ed710dd130dddba7be8bded287cd9b0d5e2cf96dab77e70221"), "what the getter is asked with for a step"),
    (mm.DESCRIPTORS_BY_RECORD + 52 * mm.R_MODE, fw.sx("b3aa0c31942114bd"), "MODE's record belongs to machine 44"),
]


# The reclock image: a step's REC is a lock on knob slot 24, made through the routines of the steps object that the
# holder's lock methods end in (engine/recpage.c). Stock code it calls or leans on:
RECLOCK_CONTEXT = [
    (mm.HOLDER_CLASS + mm.HOLDER_LOCK, fw.sx("97d5b4cbbdcb1cfeac587a0f1beb09d8"), "the holder's + 64, + 68 and + 72"),
    (mm.HOLDER_CLASS + mm.KNOB_VALUE, fw.sx("4c9aeabcf4fe471a"), "the holder's + 40"),
    (0x4001340a, fw.sx("bb6ccea904b645835158300b90e71b1e"), "the holder's lock read: the record's slot"),
    (0x40013416, fw.sx("25f4a47193bf10135d0c8b8a948fc3401cceedae5b2a6192"), "the holder's lock read: the steps object of the active track"),
    (0x4001342a, fw.sx("14f47f083071be83169f898dab269b52a21bb9c7a0fcf17ab49049f145bd7407"), "the holder's lock read: (steps, step, slot)"),
    (0x40013492, "2f44003c" "2f430038" "2f420034" "4cef043c0018" "2f400030" "4fef002c" "4ef940027fa2",
     "the holder's lock make: (steps, step, slot, value)"),
    (0x400134fa, fw.sx("30ac00b5f19b50adf079a1c2397275a21e536a2a47f5b9d406143081b7a48b1f"), "the holder's lock remove: (steps, step, slot)"),
    (mm.SLOT_OF, fw.sx("b3e43a2cba2fabb5cefc345e0bbcacfd474af512e2c0"), "a record's slot"),
    (mm.SLOT_OF + 0x16, fw.sx("abee2dae5ae46e0c42344ab2c45dbd7a"), "a record's slot: the long at + 4 of its 52 bytes"),
    (mm.PATTERN, fw.sx("4e22d9a51af87c6daf714f0b3520769bfa9bd4914441a96a98012bffdc800293489bb464fb3d5e07"),
     "the manager's steps: the same object, for the active track"),
    (mm.LOCK_READ, fw.sx("cec2817db8dfd84bc3566f6f36a85020d4ffb9531a34db63898936211e0313ff665a08c56d64"),
     "a lock by slot: the pattern at + 44, the track at + 56, then (pattern, track, step, slot)"),
    (0x4001725e, fw.sx("48b1bba90b61f222d822a414"), "a lock by slot: any of 71"),
    (0x40017272, fw.sx("2c277b25f0c871284d7b1f7848f68655efb208023cac5ac388b056d5e399214e302d"),
     "a lock by slot: a word a slot, 72 a step, 9287 bytes a track"),
    (mm.LOCK_MAKE, fw.sx("a2098281757c35f812c6129256a1f629334605d17ffec2728932d7be"), "a lock is made: not past the pattern's length"),
    (mm.LOCK_MAKE + 0x24, fw.sx("56a3d38b12ec5ff9582823a51caf1d2a816a170ab920cf3f"), "a lock is made: (pattern, track, step, slot, value)"),
    (0x4001763e, fw.sx("56239cf54e2ce18e5a1468f32bba3a72"), "a lock is made: any of 71 slots, a value that is not negative"),
    (mm.LOCK_DROP + 0x24, fw.sx("e11bef6cc200f522aada9ea063c2b29d98e58ca1"), "a lock is removed: (pattern, track, step, slot)"),
    (mm.STEP_A, fw.sx("f64469b1f75557d5c9c142b1aef1f855745943c6a0d178ca"), "stock's first question of a step before a lock: (steps, step)"),
    (mm.STEP_B, fw.sx("f64469b1f75557d5c9c142b1aef1f855745943c6a0d178ca"), "and its second"),
    (mm.STEP_TRIG, fw.sx("bc64499d834459f7968464f5f568e6058c28a22db3eb71e6"), "a step is given a trig: (steps, step, 1)"),
    # that a lock on a slot with no record is played like any other
    (0x4008b8c8, fw.sx("1df0d42922c42fc39a156bed5f879e45c0471c40be295baa357e30a224e067dce2ce54e36376e3eb"),
     "an event is given every lock of its step: 71 slots, (slot, value) from + 20"),
    (mm.LOCKS_APPLY + 0x48, fw.sx("688620ecbee6f1a0e213ee888f2b"), "an event's locks are applied: as many as it has, by slot"),
    (mm.LOCKS_APPLY + 0x82, fw.sx("f9552819f302fb5d573262cde11c0f39f1ed9e97"), "an event's locks are applied: into the word and into the filter's state"),
]


# The meter image: the sampling page draws a bar with stock's rectangle routine, and the feed asks for the page to be
# drawn again with stock's request. Stock code they call or lean on: Stock's loop that writes the hold flag over slot
# 24 of every digital track in the block that is sent (engine/recword.S): everything of it but the two instructions
# that are replaced.
HOLD_CONTEXT = [
    (mm.HOLD_LOOP, fw.sx("0f7b4db70af377bfd1e5803e7d9b665c89d54ecd7a13660b7dce8a2cf48fc9c8289614772e0ad0ab72b7e2ea01ce35cc"),
     "a track's machine at + 62, and the flag in d0: + 128 not 0, or + 110 past 0x7eff"),
    (mm.HOLD_WRITE + 8, fw.sx("352be334506834d531cdd5de"), "eight tracks, and d0 is loaded again at the top"),
    (mm.HOLD_END, fw.sx("77b762ddf99537c9c065be54"), "after the loop d0 is loaded again"),
    (0x400a4a78, fw.sx("3a9a80c05a3b9937facb34854a2c2f97"), "the block is built from the one a trig's locks are written into"),
    (0x400979ea, fw.sx("0ec4d2a68f132b503841"), "and built here"),
]

METER_CONTEXT = [
    (mm.FILL_RECT, "4fefffd4" "48d77cfc" "246f0030" "262f0034" "242f0038" "222f003c" "202f0040" "286f0044",
     "the rectangle routine: (surface, x0, y0, x1, y1, colour)"),
    (mm.FILL_RECT + 0x20, fw.sx("fa419bb8e5246110"), "the rectangle routine: longs a column at + 12 of the surface"),
    (mm.FILL_RECT + 0x3e, fw.sx("17a8198b7ae12092"), "the rectangle routine: the surface's width at + 4"),
    (mm.FILL_RECT + 0x4e, fw.sx("a5c22f5c73857525"), "the rectangle routine: its height at + 8"),
    (mm.FILL_RECT + 0xca, fw.sx("cfe8a184247b30a1"), "the rectangle routine: its dots at + 16"),
    (mm.FILL_RECT + 0xd2, fw.sx("e283e6936a5c678d1595"), "the rectangle routine: a negative colour inverts"),
    (mm.FILL_RECT + 0xe4, fw.sx("8dabe449ba1a9baf2ba2"), "the rectangle routine: an odd one sets"),
    (mm.FILL_RECT + 0xf6, fw.sx("9cc1503afc96efb0"), "the rectangle routine: any other clears"),
    (mm.PAGE_REDRAW, fw.sx("a1350ee68f84f54d8291259a7fa4489f90863e2fe04e31aa93177355d1cdc5f2597ab525bea0"),
     "the redraw request: a flag in the page object, then its owner's"),
    (0x40100966, fw.sx("de0cc8185a5e38c7b719dd9f4a57636f"), "the redraw request: a flag in the owner, and no more"),
    (mm.CAVE_METER[0] - 2, "4e75", "the feed's new run starts a routine"),
    (mm.CAVE_METER[1] - 2, "4e75", "the feed's new run ends one"),
    (mm.CAVE_PAGE3[0] - 2, "4e75", "the page's third run starts a routine"),
    (mm.CAVE_PAGE3[1] - 2, "4e75", "the page's third run ends one"),
]


# The stereo image: one-track stereo on the main CPU (engine/rightfill.c). The mixer's four right-hand passes are
# handed a second set of buffers, which our routine fills where stock waits for the first set to arrive. Stock code it
# changes an operand of, calls or leans on:
RIGHT_CONTEXT = [
    # the delay send's two sums: (increments, gains, the tracks, the bus), left then right, one kernel
    (0x4008f7e6, fw.sx("56b3039a3847bc56c310150d7463ce55c587ff4a2943fd8f3759d788fe341af4"), "the delay send's left pass"),
    (0x4008f802, fw.sx("473eb29147e94ea77e2c47b4ae0b704b39faf30a07ba26e68e32cdc9"), "the delay send's right pass"),
    # the reverb send's: the delay's return is copied in after the tracks before each
    (0x4008f8ee, fw.sx("e5afceb7968b65d93a921246718f8a5a"), "the reverb send: the delay's left return goes after the tracks"),
    (0x4008f910, fw.sx("c679ce84b35fab3f9854a1461d2673d843011bc8605619b4c4017eae"), "the reverb send's left pass"),
    (0x4008f928, fw.sx("3c7cdb2bb67e658f307f1a9c73a5c8e0c567"), "the reverb send: the delay's right return goes after the tracks"),
    (0x4008f93a, fw.sx("3919c6d0fbed951fb447e7dac3fee089dea6763082f8a91c0fdd6526"), "the reverb send's right pass"),
    # the dry mix and the FX block's: both returns after the tracks, then two left passes, then the same for the right
    (0x4008faca, fw.sx("1bd8c40ec19f9a32e2b6"), "the dry mix: the delay's left return"),
    (0x4008fad6, fw.sx("073d7f827afb94c7fa3e30f03282"), "the dry mix: it goes after the tracks, and the kernel of ten is named"),
    (0x4008fae6, fw.sx("bbfe91c6117589399a47f63a8a7628e6c598"), "the dry mix: the reverb's left return goes after it"),
    (0x4008faf4, fw.sx("b30045bc7a425d7d7e14a1c191d786928b8c9179f632f4b206718ed7"), "the dry mix's left pass"),
    (0x4008fb10, fw.sx("8956d323ba8ac405dec1086b9367858aab4248fc33103269aab9f282"), "the FX block's left pass"),
    (0x4008fb28, fw.sx("3eceac403b6924fabdcc0fa1524ad67bf00cfb0cd7e4b49adaf42f268c94fb69"), "the two right returns go where the left ones were"),
    (0x4008fb48, fw.sx("d698031ef3342d15ae50b02ea81a9e4f502dcb66a378433b8d551f4e"), "the dry mix's right pass"),
    (0x4008fb60, fw.sx("41cce3056ada1c5b5657ef19a4823e22ea17bc1f666c5ad3cf23d1c7"), "the FX block's right pass"),
    # the kernels read their inputs 128 bytes apart from the one address, and the copy takes one side of a pair
    (mm.MIX_KERNEL9 + 0x1e, fw.sx("a48b5acd97e3b87aa3af4419ab96cb243eb6310a363441b8b265fb4ff23b2e3c211d93eb94b3b12fe8753cfe9efe4a04b2815d0d78ddaf1e912f"),
     "the kernel of nine: eight tracks and a ninth buffer, 128 bytes apart from the one address"),
    (mm.MIX_KERNEL10 + 0x18, fw.sx("9289882aa18544404abc24856247d98385493ad6abf81d27cc6536750a4d6f588a1e7c79e014971bb766d29668b20873c89ad333b70e0a89b711b0ec5047991d"),
     "the kernel of ten: and a tenth"),
    (mm.MIX_COPY, fw.sx("35a400ffa464c891a5a39fd9c9b0b308b053104716fc17d054cb"), "the copy: 32 longs out of a stride of 8, (to, from)"),
    # the mixer's two other uses of the tracks, which stay the left's: each track's level, and the frame's channels
    (mm.TRACK_OUTS[0], fw.sx("a50147f11f0e3db21414"), "a track's level is put on its one buffer"),
    (mm.TRACK_OUTS[1], fw.sx("a870e15c0aa29b319204"), "and the frame's channels 2..9 are the eight buffers"),
    # where the first set arrives, and the place our routine takes
    (mm.TRACKS_IN[1] - 8, fw.sx("f8e40b6e2d5201e62feef27f33e7b92bfadcd3fa7a477f5ee9a2da642890696737f827a2e4ebd089b7f7ea0f"),
     "before the mixer: 64 x 16 bytes from the window to the tracks, if the audio CPU is up"),
    (mm.TRACKS_CLEAR, fw.sx("9a27a23d9d108b1dc7cabed2041edb23ebc81d4e"), "or the tracks and the two returns are cleared"),
    (mm.DMA_WAIT, fw.sx("598dac6a6da4431159153dc0b04b2b51f604aad702a4a4574e293825bde35635eb37717b859b"), "the wait for a transfer that was started"),
    (mm.RIGHT_HOOK - 6, fw.sx("92047029582662fb805c"), "the knobs for the audio CPU are complete"),
    (mm.RIGHT_HOOK + 10, fw.sx("07d2a66a87649b4ad08e56eeddaf1801415f38c7"), "then: unless the audio CPU is down, 27 x 16 bytes of knobs to the window"),
    (mm.RIGHT_HOOK + 0x44, fw.sx("aa242927f709aeed31dba01b3b24"), "and on, with nothing kept in d0, d1, a0 or a1"),
    (mm.CAVE_RIGHT[0] - 2, "4e75", "our run starts a routine"),
    (mm.CAVE_RIGHT[1] - 2, "4e75", "our run ends one"),
    # the effects' memory, which is what lies after the gap the second set is in
    (0x40096c80, fw.sx("d3eb46d7f163a0470e10c9b58549ac9da2c1"), "the effects' memory: 9 x 64 KB at 0x4d570000 are cleared"),
    (0x400004ba, fw.sx("e4c5a6f7c3f9337c9de5c139fef85414"), "the program's data ends at 0x45566490"),
]
RIGHT_HOOK_STOCK = fw.sx("9d0eaea3035952cd35f722cf8345")  # jsr %pc@(DMA_WAIT) ; tstl AUDIO_UP


# The dma image: the second set is in on-chip memory and the right channels are brought to it by two channels of the
# transfer controller, set as stock sets its own (engine/rightdma.c). Stock code it calls, copies the ways of or leans
# on:
DMA_CONTEXT = [
    (mm.DMA_CONTROL_SET, fw.sx("76eaf5b9fa85366debb7c94be57b4298c131"), "the controller: round robin inside a group, the groups in fixed order"),
    (mm.DMA_47_SET, fw.sx("ba6f6ee5498d7c3560a4766a39a0f405397e1e9ed183a3ddfceb8ed11fffaa9c2ddb410e76a7815cf98df54e56955b0e27889027b031a734"),
     "channel 47's standing words, which ours are a copy of"),
    (mm.TRACKS_IN[1] + 0x20, fw.sx("16d5c33f2525ab73e73595a82cd93d00a64fa3cf4dc34bc59b2f04a3"), "a transfer of stock's: the turns twice, its mark, the start"),
    (mm.BLOCK_FIRST_CALL - 6, fw.sx("225c83888d1f28b6eac499ff") + "%08x" % mm.BLOCK_FIRST + fw.sx("d5bea54d324ea924ba69"), "the per-block routine's first call, its answer not used"),
    (mm.BLOCK_FIRST, fw.sx("b00ad03593f6ae9cb56c242695ac6c77a056e4b25552fee5"), "what it calls: no arguments"),
    (mm.PRE_MIX_CALL - 8, fw.sx("ed8a447ee4bab94e68b0f70681b7") + "%08x" % mm.PRE_MIX + fw.sx("86d828a56bad11a7"), "the last call before the mixer's"),
    (mm.PRE_MIX, "4fefFFF4" "48d7001c" "206f0014", "what it calls: its arguments on the stack"),
    (mm.SRAM_COPY, fw.sx("92a1cec49bb10aeba8a0494ab71feeb50e4837deb65f6b014ad1e4e671a2725e087191746a5dd74f54fa955904a3"),
     "the startup: on-chip memory's first half is copied to 0x80007330 and cleared from there to 0x80008000"),
    (mm.CAVE_DMA[0] - 2, "4e75", "our run starts a routine"),
    (mm.CAVE_DMA[1] - 2, "4e75", "our run ends one"),
    (mm.CAVE_DMA2[0] - 2, "4e75", "our second run starts a routine"),
    (mm.CAVE_DMA2[1] - 2, "4e75", "our second run ends one"),
]


# The srr image: a sampler track's REC and SRC are the track's own word on knob slot 24, read where the sound engine's
# side reads the kit (engine/recword.S, engine/recpage.c). Stock code it leans on: (address, stock bytes, what)
SRR_CONTEXT = [
    (mm.HOLD_WRITE - 0x2c, fw.sx("855d393d2dad928aceb468b58040"), "the per-block loop goes over the eight machines at 0x80002f50, one past the track's at the call"),
    (0x400a4642, fw.sx("211795366de36bd7ee7ea6b9562a"), "a track's sound is 291 bytes of the kit"),
    (0x400a46f8, fw.sx("40323593ebafd53f195f3915b09c27ab5e06"), "a track's sound is loaded from the kit at 0x800030b8, 42 in"),
    (0x40097834, fw.sx("cca520fa8f1deed34f2fe9562cdd63f9ca40a92a40aed971"), "a lock's slot is put back from the sound's word at 20 + 2 x slot"),
    (0x40097a62, fw.sx("d9cb1857a26ba283780158affc9fe90a"), "machine 44's words of slots 19 and 23 are sent as they are"),
    (0x400a4b40, fw.sx("cb5b711a995dc4487667"), "the modulation is put on the block after it is built"),
    (mm.DESCRIPTORS_BY_RECORD + 52 * mm.R_MODE + 4, fw.sx("f08eaea73864aa0c"), "MODE's record is knob slot 23"),
]


# The gear image: the sampling page's knobs, and SMPL, turn through stock's own three routines, as a stock page whose
# knobs are whole numbers does. Stock code it calls or leans on: (address, stock bytes, what)
GEAR_CONTEXT = [
    (mm.KNOB_STEPS, fw.sx("dfccc16c53b83e0cf1bac1d56f0b1d9e20735c2a72665c530dc8a2d29eeed967997a"),
     "the steps: the event's long at + 16, times the third argument while its byte at + 20 is set, else the second"),
    (mm.KNOB_PUSHED, fw.sx("6d93fb3b35469f35c34981cce3ce"), "pushed in: the event's byte at + 20"),
    (mm.KNOB_CHANGE, fw.sx("ed6e6b83fb4b841bee6cea2b7fe3a8dd"), "the change: its fifth argument's low byte is pushed in"),
    (0x400f6a7e, fw.sx("4862e1058030b6748ac86be2d6ea385b"), "a knob's ticks: 20 bytes a knob, from + 32 of the object it is handed"),
    (0x4003b972, fw.sx("df5ad24d0ae3c849d3401aa86c09d6e1"), "stock's knob routine: the page's ticks are its + 148"),
    (0x4003b9b4, fw.sx("033a24731d7c2e48378a186a"), "stock's knob routine hands them to the change"),
    (0x40049730, fw.sx("fedc6fa94145be799c72da1919b1d769d8ae4bf82c50cb1e7741c5f9fb88ff4f76655fa132ac117df123c2fb1cbad25614a2c9aa30740eaeb499a8b0025dbf467abdede4"),
     "a stock page of whole numbers: pushed, steps, knob, then the change by the plain feel"),
    (0x40049770, fw.sx("b8962abde90e81e8191abcd426fbe5eb"), "a stock page of whole numbers takes the change's whole part, towards nought"),
    (0x401aa6ce, fw.sx("b567e71455b4e220ce81"), "the plain feel is built at a start"),
    (0x401aa732, fw.sx("2fdc6a8468ebd5652a2e"), "the sample picker's feel is built at a start"),
    (0x400f6390, "7001" "206f0008" "10bc0001" "11400001" "11400002" "7002" "21400004" "103c0003" "21400008",
     "the plain feel: 3 ticks a step, speeding up by 2"),
    (0x400f63f0, fw.sx("1d238d42e0b7696bb5dd997ce5c8051e41e337c4108d337acdbbeba1a477"),
     "the picker's feel: 6 ticks a step, no speeding up, and its first byte clear: a pause after a step"),
]


def _dma_free(image):
    """Our two channels and our part of on-chip memory are named by nothing in the main program."""
    for ch in mm.DMA_RIGHT:
        if ch in mm.DMA_STOCK or not ch < 16:
            raise fw.GuardError("channel %d is not a free one of group 0" % ch)
    lo, hi = mm.RIGHT_SCRATCH, mm.RIGHT_STATE + 32
    if not (mm.SRAM_LOW[0] <= lo and hi <= mm.SRAM_LOW[1] and lo + 1024 <= mm.RIGHT_SRAM and mm.RIGHT_SRAM + 1280 <= mm.RIGHT_STATE):
        raise fw.GuardError("the dma image's memory is not inside the first half's free end")
    for i in range(0, len(image) - 3, 2):
        v = int.from_bytes(image[i:i + 4], "big")
        if 0xfc045000 <= v < 0xfc045800 and (v - 0xfc045000) // 32 not in mm.DMA_STOCK:
            raise fw.GuardError("a word of channel %d is named at %#x" % ((v - 0xfc045000) // 32, mm.BASE + i))
        if lo <= v < hi and (mm.BASE + i, v) not in DMA_MEMORY_SEEN:
            raise fw.GuardError("%#x at %#x: the dma image's memory may be named" % (v, mm.BASE + i))


# Every long at an even place of the main program that reads as an address inside our part of on-chip memory, and what
# it is: none is an instruction's operand (docs/FINDINGS.md, "The right channels by a hardware transfer").
DMA_MEMORY_SEEN = {
    (0x40102602, 0x80007403), (0x400935ec, 0x80007603), (0x40092070, 0x80007c1f),  # the end of one instruction and the start of the next
    (0x401dafc4, 0x800076da), (0x401dafc0, 0x80007a82),  # a table of numbers that fall
    (0x4021d288, 0x80007429), (0x4021d28c, 0x80007734), (0x4021d290, 0x80007a53),  # another
    (0x4022296c, 0x80007802), (0x40222970, 0x80007d07),  # another
    (0x402e0d12, 0x80007804), (0x402f4fa6, 0x80007805), (0x402f326e, 0x80007c00), (0x4031d0fa, 0x80007c00), (0x4031bae6, 0x80007c1f),  # the program's data
}


def right_patches(image, stops=False, dma=False, lap=False, movem=False):
    out = []
    for addr, stock, what in RIGHT_CONTEXT + (DMA_CONTEXT if dma else []):
        _expect(image, addr, bytes.fromhex(stock), "one-track stereo, " + what)
    if dma:
        _dma_free(image)
        caves = {"o": mm.CAVE_DMA, "p": mm.CAVE_DMA2}
        if lap:
            for addr in (mm.CAVE_LAP[0] - 2, mm.CAVE_LAP[1] - 2):
                _expect(image, addr, bytes.fromhex("4e75"), "the readings' run starts and ends a routine")
            if any(image.count(be32(a)) for a in range(mm.CAVE_LAP[0], mm.CAVE_LAP[1], 2)):
                raise fw.GuardError("an address in the readings' run is named in the main program")
            caves["q"] = mm.CAVE_LAP
        if movem:  # the copy image: the mono tracks' copies by movem, in a run of its own
            for addr in (mm.CAVE_COPY[0] - 2, mm.CAVE_COPY[1] - 2):
                _expect(image, addr, bytes.fromhex("4e75"), "the copy image's run starts and ends a routine")
            if any(image.count(be32(a)) for a in range(mm.CAVE_COPY[0], mm.CAVE_COPY[1], 2)):
                raise fw.GuardError("an address in the copy image's run is named in the main program")
            caves["c"] = mm.CAVE_COPY
        code, syms = build_engine.compile_code(("rightdma.c",), caves, ("rightdma_copy" if lap else "rightdma_cut") if movem else "rightdma_lap" if lap else "rightdma",
                                               ("ONETRACK", "STOPS", "DMA") + (("LAP", "PROF_AT=%#x" % mm.CAVE_PROF[0]) if lap else ())
                                               + (("MOVEM",) if movem else ()))  # the lap image, a tool: five more readings of the profile's timer
        for cave, (start, end) in sorted(caves.items()):
            new = code[cave] + build_engine.NOP * ((end - start - len(code[cave])) // 2)
            out.append(fw.Patch(3, mm.off(start), image[mm.off(start):mm.off(end)], new, "the right channels by a transfer: the code"))
        for site in mm.RIGHT_PASSES:
            _expect(image, site, PEA + be32(mm.TRACKS), "one-track stereo, a right-hand pass")
            out.append(fw.Patch(3, mm.off(site + 2), be32(mm.TRACKS), be32(mm.RIGHT_SRAM), "the right channels by a transfer: a right-hand pass reads the second set"))
        for site, ret in mm.RIGHT_RETURNS:
            _expect(image, site, PEA + be32(ret), "one-track stereo, a return copied before a right-hand pass")
            out.append(fw.Patch(3, mm.off(site + 2), be32(ret), be32(mm.RIGHT_SRAM + ret - mm.TRACKS),
                                "the right channels by a transfer: a right return goes after the second set"))
        # the place stock waits for the first set: jsr right_mid ; tstl %d0 ; nop, as the images before have it with
        # their routine.
        out.append(fw.Patch(3, mm.off(mm.RIGHT_HOOK), bytes.fromhex(RIGHT_HOOK_STOCK), b"\x4e\xb9" + be32(syms["right_mid_lap" if lap else "right_mid"]) + b"\x4a\x80" + build_engine.NOP,
                            "the right channels by a transfer: stock's wait, and the CPU's reads there if the transfers were given up"))
        # two calls go to ours, which go on to what stock called.
        out.append(fw.Patch(3, mm.off(mm.BLOCK_FIRST_CALL + 2), be32(mm.BLOCK_FIRST), be32(syms["right_start"]),
                            "the right channels by a transfer: they are started at the per-block routine's first call"))
        out.append(fw.Patch(3, mm.off(mm.PRE_MIX_CALL + 2), be32(mm.PRE_MIX), be32(syms["right_ready_lap" if lap else "right_ready"]),
                            "the right channels by a transfer: the second set is whole before the mixer"))
        return out, syms
    lo, hi = mm.MAIN_BSS_END, mm.EFFECTS_MEMORY[0] - mm.UNCACHED
    if not lo + 0x1000 <= mm.RIGHT_SET and mm.RIGHT_SET + 1280 + 0x1000 <= hi:
        raise fw.GuardError("the second set of buffers is not inside the gap after the program's data")
    start, end = mm.CAVE_RIGHT
    # (the stops image: the routine also clears the mark of what the audio CPU says the slots hold, while it is down)
    code, syms = build_engine.compile_code(("rightfill.c",), {"o": mm.CAVE_RIGHT}, "rightfill_stops" if stops else "rightfill",
                                           ("ONETRACK", "STOPS") if stops else ("ONETRACK",))
    new = code["o"] + build_engine.NOP * ((end - start - len(code["o"])) // 2)
    out.append(fw.Patch(3, mm.off(start), image[mm.off(start):mm.off(end)], new, "one-track stereo: the second set's code"))
    for site in mm.RIGHT_PASSES:
        _expect(image, site, PEA + be32(mm.TRACKS), "one-track stereo, a right-hand pass")
        out.append(fw.Patch(3, mm.off(site + 2), be32(mm.TRACKS), be32(mm.RIGHT_SET), "one-track stereo: a right-hand pass reads the second set"))
    for site, ret in mm.RIGHT_RETURNS:
        _expect(image, site, PEA + be32(ret), "one-track stereo, a return copied before a right-hand pass")
        out.append(fw.Patch(3, mm.off(site + 2), be32(ret), be32(mm.RIGHT_SET + ret - mm.TRACKS),
                            "one-track stereo: a right return goes after the second set"))
    # jsr right_fill ; tstl %d0 ; nop. The routine waits as stock did and answers what stock tested.
    out.append(fw.Patch(3, mm.off(mm.RIGHT_HOOK), bytes.fromhex(RIGHT_HOOK_STOCK), b"\x4e\xb9" + be32(syms["right_fill"]) + b"\x4a\x80" + build_engine.NOP,
                        "one-track stereo: the second set is filled where stock waits for the first"))
    return out, syms


EXTRA_DEFS = ()  # set by a tool image (tools/build.py, probe17): more defines for the page, under its own object's name
EVLAP = False  # set by a tool image (tools/build.py, evtime): four laps in the events and knobs stretch, the mixer not timed


def page_patches(image, bank=False, reclock=False, meter=False, save_start=None, probe=False, timed=False, gain=False, auto=False, peak=False,
                 pack=False, stops=False, ptn=False, feed=False, once=False, soloknob=False, xfade=False, prof_on=None):
    out = []
    for addr, stock, what in PAGE_CONTEXT:
        _expect(image, addr, bytes.fromhex(stock), "second SYN page, " + what)
    for addr, stock, what in RECLOCK_CONTEXT if reclock else ():
        _expect(image, addr, bytes.fromhex(stock), "a step's REC, " + what)
    start, end = mm.CAVE_PAGE
    caves = {"g": mm.CAVE_PAGE, "j": mm.CAVE_PAGE2}
    if meter:
        caves["k"] = mm.CAVE_PAGE3
    if gain:  # the gain image: a fourth run, the first three being full
        for addr, stock in ((mm.CAVE_PAGE4[0] - 2, "4e75"), (mm.CAVE_PAGE4[1] - 2, "4e75")):
            _expect(image, addr, bytes.fromhex(stock), "the page's fourth run starts and ends a routine")
        caves["l"] = mm.CAVE_PAGE4
    if stops:  # the stops image: a fifth and a sixth, for what a turn of SMPL stops at
        for lo, hi in (mm.CAVE_PAGE5, mm.CAVE_PAGE6):
            for addr in (lo - 2, hi - 2):
                _expect(image, addr, bytes.fromhex("4e75"), "the page's fifth and sixth runs start and end a routine")
        caves["n"], caves["q"] = mm.CAVE_PAGE5, mm.CAVE_PAGE6
    if xfade >= 4:  # the apage image: a seventh, for the analog tracks' page
        for addr in (mm.CAVE_PAGE7[0] - 2, mm.CAVE_PAGE7[1] - 2):
            _expect(image, addr, bytes.fromhex("4e75"), "the page's seventh run starts and ends a routine")
        caves["r"] = mm.CAVE_PAGE7
    if xfade >= 5:  # the slock image: an eighth, for a step's solo
        for addr in (mm.CAVE_PAGE8[0] - 2, mm.CAVE_PAGE8[1] - 2):
            _expect(image, addr, bytes.fromhex("4e75"), "the page's eighth run starts and ends a routine")
        caves["s"] = mm.CAVE_PAGE8
    if xfade >= 9:  # the gear image: the page's knobs turn through stock's routines, from a tenth run
        for addr, stock, what in GEAR_CONTEXT:
            _expect(image, addr, bytes.fromhex(stock), "the page's knobs, " + what)
        for addr in (mm.CAVE_PAGE10[0] - 2, mm.CAVE_PAGE10[1] - 2):
            _expect(image, addr, bytes.fromhex("4e75"), "the page's tenth run starts and ends a routine")
        if image.count(be32(mm.CAVE_PAGE10[0])):
            raise fw.GuardError("the page's tenth run is named in the main program")
        caves["v"] = mm.CAVE_PAGE10
    if xfade >= 8:  # the srr image: a ninth, for the track's own word on slot 24
        for addr in (mm.CAVE_PAGE9[0] - 2, mm.CAVE_PAGE9[1] - 2):
            _expect(image, addr, bytes.fromhex("4e75"), "the page's ninth run starts and ends a routine")
        if image.count(be32(mm.CAVE_PAGE9[0])):
            raise fw.GuardError("the page's ninth run is named in the main program")
        caves["u"] = mm.CAVE_PAGE9
    if xfade >= 23:  # the trig image: SOLO and REC on a sampler track's TRIG page, from an eleventh run
        for addr in (mm.CAVE_TRIG[0] - 2, mm.CAVE_TRIG[1] - 2, mm.CAVE_TRIG2[0] - 2, mm.CAVE_TRIG2[1] - 2):
            _expect(image, addr, bytes.fromhex("4e75"), "the TRIG page's runs start and end a routine")
        if any(image.count(be32(a)) for a in range(mm.CAVE_TRIG2[0], mm.CAVE_TRIG2[1], 2)):
            raise fw.GuardError("an address in the TRIG page's second run is named in the main program")
        caves["x"], caves["z"] = mm.CAVE_TRIG, mm.CAVE_TRIG2
        if xfade >= 24:  # the switch image: a third, for drawing a switch
            for addr in (mm.CAVE_TRIG3[0] - 2, mm.CAVE_TRIG3[1] - 2):
                _expect(image, addr, bytes.fromhex("4e75"), "the TRIG page's third run starts and ends a routine")
            if any(image.count(be32(a)) for a in range(mm.CAVE_TRIG3[0], mm.CAVE_TRIG3[1], 2)):
                raise fw.GuardError("an address in the TRIG page's third run is named in the main program")
            caves["y"] = mm.CAVE_TRIG3
    if xfade >= 26:  # the xknob image: two more runs for knob D's crossfade
        for run in (mm.CAVE_XKNOB, mm.CAVE_XKNOB2):
            for addr in (run[0] - 2, run[1] - 2):
                _expect(image, addr, bytes.fromhex("4e75"), "the xknob image's runs start and end a routine")
            if any(image.count(be32(a)) for a in range(run[0], run[1], 2)):
                raise fw.GuardError("an address in the xknob image's runs is named in the main program")
        caves["w"], caves["f"] = mm.CAVE_XKNOB, mm.CAVE_XKNOB2
        if xfade >= 27:  # the xshare image: one more
            run = mm.CAVE_XSHARE
            for addr in (run[0] - 2, run[1] - 2):
                _expect(image, addr, bytes.fromhex("4e75"), "the xshare image's run starts and ends a routine")
            if any(image.count(be32(a)) for a in range(run[0], run[1], 2)):
                raise fw.GuardError("an address in the xshare image's run is named in the main program")
            caves["h"] = run
            if xfade >= 28:  # the fltr image: one more, for FLTR2's G and H
                run = mm.CAVE_FLTR
                for addr in (run[0] - 2, run[1] - 2):
                    _expect(image, addr, bytes.fromhex("4e75"), "the fltr image's run starts and ends a routine")
                if any(image.count(be32(a)) for a in range(run[0], run[1], 2)):
                    raise fw.GuardError("an address in the fltr image's run is named in the main program")
                caves["d"] = run
                if xfade >= 53:  # the stretch image: KEYS's four settings, in a run of their own
                    run = mm.CAVE_STRETCH
                    for addr in (run[0] - 2, run[1] - 2):
                        _expect(image, addr, bytes.fromhex("4e75"), "the stretch image's run starts and ends a routine")
                    if any(image.count(be32(a)) for a in range(run[0], run[1], 2)):
                        raise fw.GuardError("an address in the stretch image's run is named in the main program")
                    caves["i"] = run
                    if xfade >= 54:  # the lock image: KEYS's six names in another
                        run = mm.CAVE_LOCK2
                        for addr in (run[0] - 2, run[1] - 2):
                            _expect(image, addr, bytes.fromhex("4e75"), "the lock image's second run starts and ends a routine")
                        if any(image.count(be32(a)) for a in range(run[0], run[1], 2)):
                            raise fw.GuardError("an address in the lock image's second run is named in the main program")
                        caves["o"] = run
                        if xfade >= 58:  # the stsw image: the stretch's switch and its lock
                            run = mm.CAVE_STSW
                            for addr in (run[0] - 2, run[1] - 2):
                                _expect(image, addr, bytes.fromhex("4e75"), "the stsw image's run starts and ends a routine")
                            if any(image.count(be32(a)) for a in range(run[0], run[1], 2)):
                                raise fw.GuardError("an address in the stsw image's run is named in the main program")
                            caves["e"] = run
                            run = mm.CAVE_STSW2
                            for addr in (run[0] - 2, run[1] - 2):
                                _expect(image, addr, bytes.fromhex("4e75"), "the stsw image's second run starts and ends a routine")
                            if any(image.count(be32(a)) for a in range(run[0], run[1], 2)):
                                raise fw.GuardError("an address in the stsw image's second run is named in the main program")
                            caves["m"] = run
                            if xfade >= 61:  # the next image: DEST's NEXT and the KIND switch, in five runs of their own
                                for letter, run in (("nx1", mm.CAVE_NEXT), ("nx2", mm.CAVE_NEXT2), ("nx3", mm.CAVE_NEXT3), ("nx4", mm.CAVE_NEXT4), ("nx5", mm.CAVE_NEXT5)):
                                    for addr in (run[0] - 2, run[1] - 2):
                                        _expect(image, addr, bytes.fromhex("4e75"), "the next image's runs start and end a routine")
                                    if any(image.count(be32(a)) for a in range(run[0], run[1], 2)):
                                        raise fw.GuardError("an address in the next image's runs is named in the main program")
                                    caves[letter] = run
                                if xfade >= 63:  # the kind image: SMPL's stops by the track's KIND, in a run of its own
                                    run = mm.CAVE_KIND
                                    for addr in (run[0] - 2, run[1] - 2):
                                        _expect(image, addr, bytes.fromhex("4e75"), "the kind image's run starts and ends a routine")
                                    if any(image.count(be32(a)) for a in range(run[0], run[1], 2)):
                                        raise fw.GuardError("an address in the kind image's run is named in the main program")
                                    caves["ks"] = run
                    if "SLOTPROBE" in EXTRA_DEFS or "TUNEPROBE" in EXTRA_DEFS:  # the slotprobe tool (and the tuneprobe tool's place): the long image's run, which nothing of this chain uses
                        run = mm.CAVE_LONG
                        for addr in (run[0] - 2, run[1] - 2):
                            _expect(image, addr, bytes.fromhex("4e75"), "the slotprobe tool's run starts and ends a routine")
                        if any(image.count(be32(a)) for a in range(run[0], run[1], 2)):
                            raise fw.GuardError("an address in the slotprobe tool's run is named in the main program")
                        caves["b"] = run
                        run = mm.CAVE_EDIT2  # and the long image's last run, for its places
                        for addr in (run[0] - 2, run[1] - 2):
                            _expect(image, addr, bytes.fromhex("4e75"), "the slotprobe tool's second run starts and ends a routine")
                        if any(image.count(be32(a)) for a in range(run[0], run[1], 2)):
                            raise fw.GuardError("an address in the slotprobe tool's second run is named in the main program")
                        caves["a"] = run
    if save_start:  # the save image: the page's fifth place starts a save, in the keep code
        code, syms = build_engine.compile_code(("recpage.c",), caves,
                                               "recpage_" + EXTRA_DEFS[0].lower() if EXTRA_DEFS else "recpage_probe" if probe else "recpage_time" if timed
                                               else "recpage_destnum" if xfade >= 74 and peak  # 74: the destnum image, DEST's numbers back
                                               else "recpage_onedest" if xfade >= 73 and peak  # 73: the onedest image, DEST SMPL only
                                               else "recpage_gainup" if xfade >= 72 and peak  # 72: the gainup image, the gain in D, the peak in E, STRC in G
                                               else "recpage_axf" if xfade >= 71 and peak  # 71: the axf image, P off the analog page's G
                                               else "recpage_kind" if xfade >= 63 and peak  # 63: the kind image, SMPL's stops by KIND
                                               else "recpage_pbank" if xfade >= 62 and peak  # 62: the pbank image, BANK off the page
                                               else "recpage_next" if xfade >= 61 and peak  # 61: the next image, DEST SMPL or NEXT, C the KIND
                                               else "recpage_stsw" if xfade >= 58 and peak  # 58: the stsw image, KEYS's two and the stretch's switch
                                               else "recpage_lock" if xfade >= 54 and peak  # 54: the lock image, KEYS's six settings
                                               else "recpage_stretch" if xfade >= 53 and peak  # 53: the stretch image, KEYS's four settings
                                               else "recpage_atrig" if xfade >= 51 and peak  # 51: the atrig image, an analog track's SOLO on TRIG, LFO.T on FLTR2
                                               else "recpage_eucl" if xfade >= 49 and peak  # 49: the eucl image, SOLO and REC off TRIG's euclidean page
                                               else "recpage_xcarry" if xfade >= 45 and peak  # 45: the xcarry image, the amount through the page
                                               else "recpage_xcont" if xfade >= 44 and peak  # 44: the xcont image, a turn takes the live amount
                                               else "recpage_xfix" if xfade >= 43 and peak  # 43: the xfix image, the others' live crossfade cleared too
                                               else "recpage_slice" if xfade >= 31 and peak  # 31: the slice image, KEYS on H, P on G
                                               else "recpage_tlsolo" if xfade >= 29 and peak  # 29: the tlsolo image, a held step's solo always locked
                                               else "recpage_fltr" if xfade >= 28 and peak  # 28: the fltr image, LFO.T and FLT.T on FLTR2's G and H
                                               else "recpage_xshare" if xfade >= 27 and peak  # 27: the xshare image, D the pattern's one crossfade
                                               else "recpage_xknob" if xfade >= 26 and peak  # 26: the xknob image, the crossfade on the first page's D
                                               else "recpage_box" if xfade >= 25 and peak  # 25: the box image, no dotted box, REC OFF or ONCE
                                               else "recpage_switch" if xfade >= 24 and peak  # 24: the switch image, SOLO and REC as stock's switch
                                               else "recpage_trig" if xfade >= 23 and peak  # 23: the trig image, SOLO and REC on the TRIG page
                                               else ("recpage_prof" if peak else "recpage_prof0") if prof_on  # the prof image: the last knob switches the profile
                                               else ("recpage_gear" if peak else "recpage_gear0") if xfade >= 9  # 9: the gear image, the page's knobs as stock's turn
                                               else ("recpage_srr" if peak else "recpage_srr0") if xfade == 8  # 8: the srr image, REC and SRC from the track's own word
                                               else ("recpage_alock" if peak else "recpage_alock0") if xfade >= 6  # 6: the alock image, an analog track's solo as a lock too
                                               else ("recpage_slock" if peak else "recpage_slock0") if xfade == 5  # 5: the slock image, a sampler track's solo as a lock
                                               else ("recpage_apage" if peak else "recpage_apage0") if xfade == 4  # 4: the apage image, the page on the analog tracks too
                                               else ("recpage_dma" if peak else "recpage_dma0") if xfade == 3  # 3: the dma image, the gfade image's page with a letter
                                               else ("recpage_gfade" if peak else "recpage_gfade0") if xfade == 2
                                               else ("recpage_xfade" if peak else "recpage_xfade0") if xfade
                                               else ("recpage_soloknob" if peak else "recpage_soloknob0") if soloknob
                                               else ("recpage_once" if peak else "recpage_once0") if once
                                               else ("recpage_feed" if peak else "recpage_feed0") if feed
                                               else ("recpage_ptn" if peak else "recpage_ptn0") if ptn
                                               else ("recpage_stops" if peak else "recpage_stops0") if stops
                                               else ("recpage_pack" if peak else "recpage_pack0") if pack
                                               else ("recpage_mode" if peak else "recpage_mode0") if auto
                                               else "recpage_gain" if gain else "recpage_save",
                                               ("BANKS", "RECLOCK", "METER", "SAVE", "SAVE_START=%#x" % save_start) + (("PROBE",) if probe else ())
                                               + (("TIMED",) if timed else ()) + (("GAIN",) if gain else ()) + (("AUTO",) if auto else ())
                                               + (("PEAK",) if peak else ()) + (("PACK",) if pack else ()) + (("STOPS",) if stops else ())
                                               + (("PTN",) if ptn else ())  # the ptn image: no SAVE box, and FAIL alone in its place
                                               + (("FEED",) if feed else ())  # the feed image: no FAIL, and the held step asked for once a drawing
                                               + (("ONCE",) if once else ())  # the once image: REC's third setting
                                               + (("SOLOKNOB",) if soloknob else ())  # the soloknob image: knob E is the track's solo
                                               + (("XFADE",) if xfade else ())
                                               + (("GFADE",) if xfade >= 2 else ())  # the xfade image: knob G is the track's crossfade
                                               + (("DMA",) if xfade >= 3 else ())  # the dma image: the load's letter says how the right channels come
                                               + (("APAGE",) if xfade >= 4 else ())  # the apage image: the analog tracks have the second page
                                               + (("SLOCK",) if xfade >= 5 else ())  # the slock image: knob E with a step held locks the step's solo
                                               + (("ALOCK",) if xfade >= 6 else ())  # the alock image: on an analog track too
                                               + (("SRR",) if xfade >= 8 else ())  # the srr image: the first page's sixth knob is back, the reduction
                                               + (("GEAR",) if xfade >= 9 else ())  # the gear image: the page's knobs, and SMPL, turn as stock's do
                                               + (("PROF", "PROF_ON_AT=%#x" % prof_on) if prof_on else ())  # the prof image: knob H is the profile's switch
                                               + (("TRIGPAGE",) if xfade >= 23 else ())
                                               + (("SWITCH",) if xfade >= 24 else ())
                                               + (("BOX", "ERASER=%#x" % mm.CAVE_TRIG4[0]) if xfade >= 25 else ())
                                               + (("XKNOB", "ERASER2=%#x" % (mm.CAVE_TRIG4[0] + 28)) if xfade >= 26 else ())
                                               + (("XSHARE",) if xfade >= 27 else ())
                                               + (("FLTRPAGE",) if xfade >= 28 else ())
                                               + (("TLSOLO",) if xfade >= 29 else ())
                                               + (("SLICE",) if xfade >= 31 else ())
                                               + (("XFIX",) if xfade >= 43 else ())
                                               + (("XCONT",) if xfade >= 44 else ())
                                               + (("XCARRY",) if xfade >= 45 else ())
                                               + (("EUCL",) if xfade >= 49 else ())
                                               + (("ATRIG",) if xfade >= 51 else ()) + (("STRETCH",) if xfade >= 53 else ()) + (("LOCK",) if xfade >= 54 else ()) + (("STSW",) if xfade >= 58 else ()) + (("NEXT",) if xfade >= 61 else ()) + (("PBANK",) if xfade >= 62 else ()) + (("SKIND",) if xfade >= 63 else ()) + (("AXF",) if xfade >= 71 else ()) + (("GAINUP",) if xfade >= 72 else ()) + (("ONEDEST",) if xfade >= 73 else ()) + (("DESTNUM",) if xfade >= 74 else ()) + EXTRA_DEFS)
    else:
        code, syms = build_engine.compile_code(("recpage.c",), caves,
                                               "recpage_meter" if meter else "recpage_reclock" if reclock else "recpage_bank" if bank else "recpage",
                                               ("BANKS", "RECLOCK", "METER") if meter else ("BANKS", "RECLOCK") if reclock else ("BANKS",) if bank else ())
    for cave, (start, end) in sorted(caves.items()):
        new = code[cave] + build_engine.NOP * ((end - start - len(code[cave])) // 2)
        out.append(fw.Patch(3, mm.off(start), image[mm.off(start):mm.off(end)], new, "second SYN page: code"))
    if "TUNEPROBE" in EXTRA_DEFS:  # the tuneprobe tool: stock's page knob routine's change through ours, kept
        _expect(image, 0x4003b9b6, b"\x4e\xb9" + be32(0x400f6a96), "the page knob routine's call of the change routine")
        out.append(fw.Patch(3, mm.off(0x4003b9b8), be32(0x400f6a96), be32(syms["tp_change"]), "the tuneprobe tool: the change kept"))
    # the builder: a list of two, ours
    _expect(image, mm.SYN_BUILD, bytes.fromhex(fw.sx("67284a9172fb7a1f5b07")) + be32(mm.SYN_LIST), "second SYN page, SYN's list of one")
    out.append(fw.Patch(3, mm.off(mm.SYN_BUILD), b"\x72\x01", b"\x72\x02", "second SYN page: SYN's object gets two pages"))
    out.append(fw.Patch(3, mm.off(mm.SYN_BUILD + 6), be32(mm.SYN_LIST), be32(syms["syn_pages"]), "second SYN page: its list is ours"))
    # the object: SYN_ROOM bytes longer, for the page's own state
    _expect(image, mm.SYN_BUILD + 0x18, b"\x48\x78" + mm.SYN_SIZE.to_bytes(2, "big"), "second SYN page, the size of SYN's object")
    out.append(fw.Patch(3, mm.off(mm.SYN_BUILD + 0x1a), mm.SYN_SIZE.to_bytes(2, "big"), (mm.SYN_SIZE + mm.SYN_ROOM).to_bytes(2, "big"),
                        "second SYN page: room after SYN's object for our state"))
    apage = xfade >= 4  # the apage image: the three methods go to the analog tracks' routines first
    for method, stock, ours, what in ((mm.PAGE_KNOB_METHOD, mm.SYN_KNOB, "apage_knob" if apage else "syn_knob", "which record is behind a knob"),
                                      (mm.PAGE_DRAW_METHOD, mm.SYN_DRAW, "apage_draw" if apage else "syn_draw", "the draw"),
                                      (mm.PAGE_TURN_METHOD, mm.SYN_TURN, "apage_turn" if apage else "stops_turn" if stops else "syn_turn", "a turn of a knob")):
        slot = mm.SYN_CLASS + method
        _expect(image, slot, be32(stock), "second SYN page, the SYN class's method: " + what)
        out.append(fw.Patch(3, mm.off(slot), be32(stock), be32(syms[ours]), "second SYN page: %s goes to our routine first" % what))
    # a turn of a knob arrives through the second base's table, not the class's own
    slot = mm.SYN_SIDE + mm.SYN_SIDE_TURN
    _expect(image, slot, be32(mm.SYN_TURN_THUNK), "second SYN page, the second base's entry for a turn")
    out.append(fw.Patch(3, mm.off(slot), be32(mm.SYN_TURN_THUNK), be32(syms["apage_turn_side" if apage else "stops_turn_side" if stops else "syn_turn_side"]),
                        "second SYN page: a turn of a knob goes to our routine first"))
    if xfade >= 25:  # the box image: the eraser, a picture of stock's dotted box's size, its bits 0 under its mask
        lo, hi = mm.CAVE_TRIG4
        for addr in (lo - 2, hi - 2):
            _expect(image, addr, bytes.fromhex("4e75"), "the eraser's run starts and ends a routine")
        if any(image.count(be32(a)) for a in range(lo, hi, 2)):
            raise fw.GuardError("an address in the eraser's run is named in the main program")
        _expect(image, mm.DOTTED_MASK, bytes.fromhex(fw.sx("dcc37a7f54180919")) * 17, "the dotted box's mask")
        eraser = be32(0) + be32(17) + be32(17) + be32(0) + be32(lo + 24) + be32(mm.DOTTED_MASK) + be32(0)  # a row stride of 0: one row read for all 17
        if xfade >= 26:  # the xknob image: a second, 19 by 17, a plain knob's picture's size; then knob D's two names
            eraser += be32(0) + be32(19) + be32(17) + be32(0) + be32(lo + 24) + be32(mm.DOTTED_MASK) + XKNOB_NAMES
            assert lo + 52 == XKNOB_SHORT and len(eraser) <= hi - lo
        out.append(fw.Patch(3, mm.off(lo), image[mm.off(lo):mm.off(lo) + len(eraser)], eraser, "the box image: the eraser of the dotted box"))
    if xfade >= 28:  # the fltr image: the filter class's + 188 to ours first, LFO.T and FLT.T on FLTR2's G and H
        slot = mm.FILTER_CLASS + mm.PAGE_KNOB_METHOD
        _expect(image, slot, be32(mm.FILTER_KNOB), "the filter class's method: which record is behind a knob")
        out.append(fw.Patch(3, mm.off(slot), be32(mm.FILTER_KNOB), be32(syms["fltr_knob"]), "the fltr image: FLTR2's G and H are LFO.T and FLT.T"))
        stock = bytes.fromhex(fw.sx("2c289bcc5317b0346dbdd35918e8c206"))
        _expect(image, mm.FLTR2_FLAT, stock, "FLTR2's loop: FENR's test for the record's own picture")
        out.append(fw.Patch(3, mm.off(mm.FLTR2_FLAT), stock, b"\x4e\xf9" + be32(syms["fltr_flat"]) + bytes.fromhex("4e71") * 3,
                            "the fltr image: LFO.T and FLT.T drawn as their switches on FLTR2, as FENR is"))
    if xfade >= 23:  # the trig image: the TRIG class's three methods, and its second base's turn, to ours first
        for method, stock, ours, what in ((mm.PAGE_KNOB_METHOD, mm.TRIG_KNOB, "trig_knob", "which record is behind a knob"),
                                          (mm.PAGE_DRAW_METHOD, mm.TRIG_DRAW, "trig_draw", "the draw"),
                                          (mm.PAGE_TURN_METHOD, mm.TRIG_TURN, "trig_turn", "a turn of a knob")):
            slot = mm.TRIG_CLASS + method
            _expect(image, slot, be32(stock), "the TRIG class's method: " + what)
            out.append(fw.Patch(3, mm.off(slot), be32(stock), be32(syms[ours]), "the trig image: the TRIG page's %s goes to our routine first" % what))
        slot = mm.TRIG_SIDE + mm.SYN_SIDE_TURN
        _expect(image, slot, be32(mm.TRIG_TURN_THUNK), "the TRIG page's second base's entry for a turn")
        out.append(fw.Patch(3, mm.off(slot), be32(mm.TRIG_TURN_THUNK), be32(syms["trig_turn_side"]),
                            "the trig image: a turn on the TRIG page goes to our routine first"))
    return out, syms


# ---- the pattern's mutes as solos (the "solo" image) ---------------------------------------------
#
# engine/solo.S. The four places that store a copy of the pattern's word of mutes for the two engines store the tracks
# its solos silence; the keys' colours, and the one draw that asks the same of a pattern, ask "silenced by a solo"
# where they asked for the track's bit. Stock code it leans on:
SOLO_CONTEXT = [
    (mm.PATTERN_MUTES_SET, fw.sx("2b5d57b2035058ffa1b4a3d47d31a31b"), "the routine that stores the per-block routine's copy, all of it"),
    (mm.MIDI_MUTES_SET, fw.sx("522efd33dd9a2a3151418772b77236cc"), "the routine that stores the MIDI engine's copy, all of it"),
    (mm.PATTERN_MUTES_MSG - 8, fw.sx("f8b6c1f60b9da1d27f9be1a0189f6cfbb4bd7577f1bd"), "the store in the per-block routine; d0 is loaded right after"),
    (mm.MIDI_MUTES_MSG - 10, fw.sx("3f77416123a26b7e18841485022d136994a754d45fd2e19d"), "the store in the MIDI engine's loop, and on to 0x4010e528"),
    (0x4010e528, fw.sx("ed707bccbe10d82bea57421c62b09a48f3d8a2e129d0"), "from there: a call, and back to the loop's top with d0 not read"),
    (0x4010d68e, fw.sx("e8c8a90fd127ec2f"), "that call loads d0 before it reads it"),
    (0x4010dc52, fw.sx("d30be99865ab861a0747b4d85652"), "the loop's top loads d0"),
    (0x4010e53a, fw.sx("28d045c377ac2456"), "and so does its end"),
    # the six calls of the two routines: d0 is loaded again or not read after each
    (0x40019bf4, fw.sx("1c949e50db8b8c74137df87cf2052f401484be84c7fd30618dea39e096fdfd2e"), "the playing pattern's settings changed: both copies"),
    (0x40023328, fw.sx("63a08606aef396be2a29c4ea8c6aaae9f40fc3a42910f57f0f20"), "the playing song row's mutes changed: both copies"),
    (0x4008c454, fw.sx("d6f4cd95b027e61be5d9"), "a load: the MIDI engine's routine, into a3"),
    (0x4008c4aa, fw.sx("cc4632ff8e4704877f7f4fabafea6fdad7d2d6b277d80bab89dc956e200748949c4dc14e93fb0b866dbc6ebf0b83a64e05267c415bee695d"), "a load: both copies, by either way"),
    # the readers, which are left as they are (the per-block routine's track test is in mixer_patches)
    (0x400a3d6a, fw.sx("8011944f4e5c5a8054bf1ef174e006cc"), "the FX track's test: bit 12"),
    (0x400a4250, fw.sx("000cf813e1d257c96f096c0c"), "a dropped trig, told to the UI by the pattern's mutes"),
    (0x4010de7e, fw.sx("7262f0ba873c9e53513d38cc0fa2"), "the MIDI engine's track test"),
    (0x4010deb2, fw.sx("d9a16c96fc1c9db3ddcccaf8"), "the MIDI engine's dropped trig"),
    # the keys
    (mm.PATTERN_MUTED, fw.sx("7e161eee2d6b27a895aa31ace0c13cd652cf8938ffd063a51dbb"), "a pattern's bit: its settings by its method at + 40, 0 with none"),
    (mm.PATTERN_MUTED + 0x20, fw.sx("9d4bf60ba068d1e6f91513bbc8b9925cf68cc261bb593654bb1c74acc6f5"), "and the word at settings + 16"),
    (mm.KEY_COLOURS + 0x66, fw.sx("d2a4ddb1ea764918"), "the keys' colours: twelve tracks, the track in d2"),
    (mm.KEY_ROW_BIT - 12, fw.sx("9d4530989527eabec1812c1e76ec7b20e850141b8992939b"), "a song row's word, and the track's bit of it"),
    (mm.KEY_PATTERN_CALL - 4, fw.sx("af59069a720abd8f4bf4aa119c139492d1409b8f5f09437f7f29"), "the pattern's bit; d1 is loaded right after both"),
    (mm.KEY_COLOURS + 0x134, fw.sx("6425e6faad128697484fc8f1f7c1"), "the bit set: colour 2. Clear: the lit colour"),
    (mm.SCREEN_MUTED, fw.sx("1af7b21fd429a7dbaddd45cb1669cd135d4da552"), "the draw's question: (view, track)"),
    (mm.SCREEN_PATTERN_JUMP - 18, fw.sx("08ddcdf4d294658da66ad63c4c85d0f7fe717481a35eb22d31bf27af"), "for a pattern: (pattern, track) left on the stack"),
    (0x4003cc78, fw.sx("2d812c77bb65fa1e79dd73e8add5ab105fcaf7dc715fac45"), "its one call, in a draw"),
    # a key press: the bit itself, as it was
    (0x40037330, fw.sx("bae1317c344f1f25fe1661f6415eb12524de017678dbe520d313ea108a6e"), "a key press turns the pattern's own bit over"),
    (mm.CAVE_SOLO[0] - 2, "4e75", "the run starts after a routine"),
    (mm.CAVE_SOLO[1] - 2, "4e75", "the run ends a routine"),
]
JMP, JSR = b"\x4e\xf9", b"\x4e\xb9"


def solo_patches(image):
    for addr, stock, what in SOLO_CONTEXT:
        _expect(image, addr, bytes.fromhex(stock), "the pattern's mutes as solos, " + what)
    # each copy: two writers and the readers above, by its address. Anything else that names one would be a place not
    # looked at
    for addr, n in ((mm.PATTERN_MUTES, 6), (mm.MIDI_PATTERN_MUTES, 4)):
        if image.count(be32(addr)) != n:
            raise fw.GuardError("the copy of the pattern's mutes at %#x is not named %d times" % (addr, n))
    for addr, n in ((mm.PATTERN_MUTES_SET, 3), (mm.MIDI_MUTES_SET, 3), (mm.SCREEN_MUTED, 1)):
        if image.count(be32(addr)) != n:
            raise fw.GuardError("the routine at %#x is not named %d times" % (addr, n))
    code, syms = build_engine.compile_code(("solo.S",), {"s": mm.CAVE_SOLO}, "solo",
                                           ("PATTERN_MUTES=%#x" % mm.PATTERN_MUTES, "MIDI_PATTERN_MUTES=%#x" % mm.MIDI_PATTERN_MUTES,
                                            "PATTERN_SETTINGS=%d" % mm.PATTERN_SETTINGS))
    start, end = mm.CAVE_SOLO
    new = code["s"] + build_engine.NOP * ((end - start - len(code["s"])) // 2)
    out = [fw.Patch(3, mm.off(start), image[mm.off(start):mm.off(end)], new, "the pattern's mutes as solos: the code")]
    # lea %sp@(6),%a0 ; movew %a0@,(the copy) -> jmp (the routine): its first six bytes. The six after them are never
    # run
    for site, copy, ours in ((mm.PATTERN_MUTES_SET, mm.PATTERN_MUTES, "solo_set"), (mm.MIDI_MUTES_SET, mm.MIDI_PATTERN_MUTES, "solo_set_midi")):
        out.append(fw.Patch(3, mm.off(site), bytes.fromhex(fw.sx("251af8a6ba5f6fcd4bd2")), JMP + be32(syms[ours]),
                            "the pattern's mutes as solos: the routine that stores the copy at %#x" % copy))
    # movew %a0@,(the copy) -> jsr (the store)
    for site, copy, ours in ((mm.PATTERN_MUTES_MSG, mm.PATTERN_MUTES, "solo_msg"), (mm.MIDI_MUTES_MSG, mm.MIDI_PATTERN_MUTES, "solo_msg_midi")):
        out.append(fw.Patch(3, mm.off(site), b"\x33\xd0" + be32(copy), JSR + be32(syms[ours]),
                            "the pattern's mutes as solos: the message's store of the copy at %#x" % copy))
    # the keys: jsr (a pattern's bit) -> jsr solo_key ; mvzw %d0,%d0 ; asrl %d2,%d0 ; andl %d1,%d0 -> jsr solo_key_row
    out.append(fw.Patch(3, mm.off(mm.KEY_PATTERN_CALL + 2), be32(mm.PATTERN_MUTED), be32(syms["solo_key"]),
                        "the pattern's mutes as solos: a key is dark for a track a solo silences"))
    out.append(fw.Patch(3, mm.off(mm.KEY_ROW_BIT), bytes.fromhex(fw.sx("ad57dbea59bc30ab2293")), JSR + be32(syms["solo_key_row"]),
                        "the pattern's mutes as solos: the same for a song row's"))
    # and the draw's question, for a pattern: jmp (a pattern's bit) -> jmp solo_key
    out.append(fw.Patch(3, mm.off(mm.SCREEN_PATTERN_JUMP + 2), be32(mm.PATTERN_MUTED), be32(syms["solo_key"]),
                        "the pattern's mutes as solos: the draw's question for a pattern"))
    return out, syms


# ---- REC's third setting, ONCE (the "once" image) --------------------------------------------------
#
# engine/once.S and engine/onceclean.c, in a run of their own. Three places of stock's are changed: the two ways
# through the routine that plays a step, and the main task's wait. Stock code it leans on:
ONCE_CONTEXT = [
    (mm.CAVE_ONCE[0] - 2, "4e75", "its run starts a routine"),
    (mm.CAVE_ONCE[1] - 2, "4e75", "its run ends one"),
    (mm.STEP_PLAY, fw.sx("00b152bdf5460fa047409502263b7445"), "the routine that plays a step: the track is its first argument, kept in d4"),
    (0x4008b91c, fw.sx("ef4dcc31f0e58a7c"), "and the step its fourth, kept in d3"),
    (0x4008bc18, fw.sx("4c93adb0bed7312b785f93398bac77532c15519d2dcc4d1b45c69a1bf93f86b471fc8364cfe9e70d"),
     "with an event in fp: the step's row, 144 bytes a step and 9,287 a track, and its count of locks tested"),
    (0x4008bc3c, fw.sx("b164dc741da1926a522321d2ae54f9240cdd26ae607f432b55373468d00918b412ad6f550824"),
     "five of the six arguments pushed: 0, the step twice, and the track's table last"),
    (mm.STEP_LOCKS_PUSH, fw.sx("80362f9434c75a27c9075e5708bcc936"), "the event pushed, the routine that gathers the locks called, six longs popped, on"),
    (mm.STEP_NO_LOCKS, fw.sx("55797405b7ed80d5"), "no locks: the event's count is cleared"),
    (mm.STEP_JOINED, fw.sx("5cee8851fdcd48c2d937"), "where both go on, d0 is loaded"),
    (mm.STEP_LOCKS, "4feffff4" "202f001c" "2200" "e989" "48d7040c" "ef88" "226f0010" "2041" "4281" "d1c0" "d1ef0014",
     "the routine that gathers: the event its first argument, the table its second, the step its fourth"),
    (mm.STEP_LOCKS + 0x30, fw.sx("fd0b0eddeeb3433a4cb527d7d4d9"), "a lock into the event: (slot, value) words from + 20, 8 bytes a lock"),
    (mm.STEP_LOCKS + 0x44, fw.sx("119868b5f2c45906"), "and the count at + 8"),
    (mm.MAIN_LOOP, "4879" + "%08x" % mm.MAIN_QUEUE + "4eb9" + "%08x" % mm.MAIN_WAIT + fw.sx("1f9ab58976ddbc058e4642e7"),
     "the main task's wait for a message: d0 alone is read after it"),
    (mm.NOW_PATTERN, fw.sx("670f85e82f784f848670148317c6a0bf7acc2733"), "the selected pattern's object, by its number"),
    (mm.NOW_PATTERN + 0x20, fw.sx("e2a35252cbb2e4deb86fbb1e2ac74ce01e8cad066d9c092e7ee4"), "1,664 bytes a pattern from the manager + 13204"),
    (mm.STEPS_OF + 0x12, fw.sx("9ead5840c9e54d8308a45b5d705a880efe3f7d4a"), "a track's steps object: 112 bytes a track, one in"),
    (mm.PATTERN, fw.sx("4e22d9a51af87c6daf714f0b3520769bfa9bd4914441a96a98012bffdc800293489bb464fb3d5e07"),
     "the active track's steps are those two routines' answer"),
    (mm.LOCK_DROP, fw.sx("a8291eca1719bc334cb3f48127ac56f2"), "stock's routine for a lock removed by hand"),
]


# The stay image: a ONCE is spent, and a track's own used up, only where the sequencer plays a step. Stock code it
# leans on: (address, stock bytes, what)
STAY_CONTEXT = [
    (0x4008b920, fw.sx("c42f2dba6b49c99f"), "the step routine's fifth argument, a place for the event, is 76 above its frame"),
    (0x4008cf78, fw.sx("0ff3fa2b1f7c396da4295b86e62bf9b237370da8"), "the sequencer's call hands it 0 for the event's place"),
    (0x4008c274, fw.sx("4be3c1c8cd4e0a5d9f058c879e91b47d365573422544d3005d59"), "the other call hands it a place"),
    (0x400179ee, fw.sx("fb4ccad24b59d26cdfcbe6adef1a"), "a listener jumps to the routine that plays the step the sequencer is on"),
    (0x40018fee, fw.sx("56c831034f7ae9fdf0ca264441de2900d799"), "and another, for a track of the selected pattern"),
]

# The firstrec image: what a start queues for the first step (docs/FINDINGS.md, the recprobe tool's readings).
FIRSTREC_CONTEXT = [
    (0x4008b52a, fw.sx("0979ec055bc98c9ffde6"), "a start walks the tracks' records the other caller built, from + 4"),
    (0x4008b56c, fw.sx("b88b1c6ddfe3da179723bfc9"), "and copies 80 bytes of each with a trig"),
    (0x4008b0ea, fw.sx("b6a54f913495dcf09d2b"), "and the start's other way, the same"),
    (0x4008c198, fw.sx("3f203bbf377e5b688375"), "the other caller's record: 0x444e3438 + 80 a track"),
    (0x4008bbf6, fw.sx("fc6f9350859ce3ad"), "with a record given, the step routine's lock buffer is the record's + 68"),
]

# The handrec image: the step routine's LEN, as a hand take reads it, and the tempo's use (engine/once.S, hand_rec).
HANDREC_CONTEXT = [
    (0x4008ba7e, fw.sx("267fe7cf336729c8ce6614577ade635403e96ec3c743e5a90130"), "a step's LEN at + 192 + step, 0xff for the track's at + 961"),
    (0x4008bc9e, fw.sx("d2d1cf5d828ddb299207"), "and its length from stock's table"),
    (0x4008bca6, fw.sx("cb2a258976de4cdb71900836"), "indexed by it, a long each from + 4"),
]


def mirror_patches(image, shadow=False, pieces=False):
    """The mirror image (engine/mirror.c): the UI's send to the panel and its asking whether to draw go through ours,
    which sends the frame shown to a viewer that asked. shadow: the shadow image, the frame sent copied from what
    stock's column sender gives the panel. pieces: the sink image, no write into the sink crossing one of its sends.
    """
    caves = {"m": mm.CAVE_MIRROR, "n": mm.CAVE_MIRROR2, "o": mm.CAVE_MIRROR3}
    if pieces:
        caves["p"] = mm.CAVE_MIRROR4
    for lo, hi in caves.values():
        for addr in (lo - 2, hi - 2):
            _expect(image, addr, bytes.fromhex("4e75"), "the mirror image's runs start and end a routine")
        if any(image.count(be32(a)) for a in range(lo, hi, 2)):
            raise fw.GuardError("an address in the mirror image's runs is named in the main program")
    code, syms = build_engine.compile_code(("mirror.c",), caves, "mirror", ("MIRROR",) + (("SHADOW",) if shadow else ()) + (("PIECES",) if pieces else ()))
    if syms["mirror_vars"] != mm.CAVE_MIRROR[0] or code["m"][:24] != bytes(8) + be32(8800000) + bytes(12):
        raise fw.GuardError("the mirror image's numbers must be first in its run")
    out = []
    for cave, (lo, hi) in sorted(caves.items()):
        out.append(fw.Patch(3, mm.off(lo), image[mm.off(lo):mm.off(hi)], code[cave] + build_engine.NOP * ((hi - lo - len(code[cave])) // 2),
                            "the mirror image: code"))
    # leal 0x4011391a,%a4 -> leal mirror_paint,%a4 ; jsr 0x4010095c -> jsr mirror_tick
    _expect(image, mm.UI_PAINT_LEA, bytes.fromhex("49f9") + be32(mm.PANEL_PAINT), "the UI's send to the panel, through a4")
    out.append(fw.Patch(3, mm.off(mm.UI_PAINT_LEA + 2), be32(mm.PANEL_PAINT), be32(syms["mirror_paint"]), "the mirror image: the UI's send to the panel through ours"))
    _expect(image, mm.UI_DIRTY_CALL, b"\x4e\xb9" + be32(mm.UI_DIRTY), "the UI's asking whether to draw")
    out.append(fw.Patch(3, mm.off(mm.UI_DIRTY_CALL + 2), be32(mm.UI_DIRTY), be32(syms["mirror_tick"]), "the mirror image: the UI's asking through ours"))
    if shadow:  # leal -16(%sp),%sp ; movem.l ... -> jmp mirror_cols (which does the two and goes on at + 8)
        stock = bytes.fromhex(fw.sx("aed6f6419d57131cf17b1835"))
        _expect(image, mm.PANEL_COLUMNS, stock, "the panel's column sender, its first two instructions")
        if mm.PANEL_COLUMNS_ON != mm.PANEL_COLUMNS + len(stock):
            raise fw.GuardError("the column sender goes on after its first two")
        out.append(fw.Patch(3, mm.off(mm.PANEL_COLUMNS), stock, b"\x4e\xf9" + be32(syms["mirror_cols"]) + stock[6:],
                            "the shadow image: the panel's column sender through ours"))
    return out, syms


TUNE_RECORDS = [100, 108, 116, 124, 132, 140, 148, 156, 164, 172, 180, 204, 212, 220, 228, 236, 244, 258, 260, 268, 276,
                290, 294, 295, 302, 318, 322, 325, 331, 335, 339, 343, 349, 352, 361, 386, 399, 407, 415, 431]


# The three feels the TUNE records have, as stock's start-up builds them (0x400f66e0, after the display table is
# filled): three flags and a byte, then a plain turn's {speed raised by, ticks a step, step} and a pushed one's. Held
# against the start-up run in emulation by tests/test_tune.py; the copies take a pushed step of 1.
TUNE_FEELS = {
    0x443db178: (0x01010100, 2, 3, 1, 2, 3, 4),  # the plain knob's
    0x443db140: (0x00010100, 0, 6, 1, 0, 6, 4),  # the sample picker's
    0x443db194: (0x01000100, 18, 1, 1, 2, 3, 1),
}


def tune_patches(image):
    """The tune image (engine/tunepush.S): every machine's TUNE (short name TUNE, TUN1 or TUN2, but the sampler's TUN2,
    our LOOP), its pushed turn's multiplier its unpushed one's, after record 431's entry is filled.
    """
    recs = [k for k, p in enumerate(params.load(image, "1.42")) if p.short in ("TUNE", "TUN1", "TUN2") and k != 435]
    if recs != TUNE_RECORDS:
        raise fw.GuardError("the tune image: the TUNE records are %s" % recs)
    sites = {}
    for a, tgt, args in uitable.walk(image)[1]:
        if args and args[0][0] is not None and mm.UI_TABLE <= args[0][0] < mm.UI_TABLE + mm.UI_STRIDE * mm.UI_COUNT:
            k, o = divmod(args[0][0] - mm.UI_TABLE, mm.UI_STRIDE)
            if o == 4:
                sites[k] = a
    if any(sites[k] >= mm.TUNE_COPY for k in TUNE_RECORDS[:-1]) or sites[431] != mm.TUNE_COPY + 6:
        raise fw.GuardError("the tune image: a TUNE entry filled after record 431's")
    listing = os.path.join(build_engine.OUT, "tune_list.S")
    os.makedirs(build_engine.OUT, exist_ok=True)
    with open(listing, "w") as f:
        f.write("        .section .cave.t,\"ax\"\n        .globl tune_list, tune_end\ntune_list:\n")
        f.write("".join("        .short %d\n" % (mm.UI_STRIDE * k) for k in TUNE_RECORDS))
        f.write("tune_end:\n")
        f.write("        .section .cave.u,\"ax\"\n        .globl tune_feels, tune_feels_end\ntune_feels:\n")
        for addr, longs in TUNE_FEELS.items():
            f.write("        .long %#x\n" % addr + "".join("        .long %#x\n" % v for v in longs[:6] + (1,)))
        f.write("tune_feels_end:\n")
    lo, hi = mm.CAVE_TUNE
    for a, b in (mm.CAVE_TUNE, mm.CAVE_TUNE2):
        for addr in (a - 2, b - 2):
            _expect(image, addr, bytes.fromhex("4e75"), "the tune image's runs start and end a routine")
        if any(image.count(be32(x)) for x in range(a, b, 2)):
            raise fw.GuardError("an address in the tune image's runs is named in the main program")
    if mm.TUNE_ENTRY != mm.UI_TABLE + mm.UI_STRIDE * 431:
        raise fw.GuardError("the tune image: record 431's entry")
    _expect(image, mm.TUNE_COPY - 12, bytes.fromhex(fw.sx("824bfec04cc901bd5ec8")) + bytes.fromhex("4879") + be32(mm.TUNE_ENTRY + 4)
            + bytes.fromhex("42b9") + be32(mm.TUNE_ENTRY) + bytes.fromhex("4e93"), "record 431's entry: 16 bytes from fp, its flags cleared, a3's copy")
    _expect(image, 0x401d6b44, bytes.fromhex(fw.sx("e0b8ff4e6983ae6a11aacdfb5d77170ed6472d81")), "the plain knob's sixteen bytes")
    code, syms = build_engine.compile_code(("tunepush.S", listing), {"t": mm.CAVE_TUNE, "u": mm.CAVE_TUNE2}, "tune")
    lo2, hi2 = mm.CAVE_TUNE2
    out = [fw.Patch(3, mm.off(lo), image[mm.off(lo):mm.off(hi)], code["t"] + build_engine.NOP * ((hi - lo - len(code["t"])) // 2),
                    "the tune image: code"),
           fw.Patch(3, mm.off(lo2), image[mm.off(lo2):mm.off(hi2)], code["u"] + bytes(hi2 - lo2 - len(code["u"])),
                    "the tune image: the feels' copies"),
           fw.Patch(3, mm.off(mm.TUNE_COPY), bytes.fromhex("42b9") + be32(mm.TUNE_ENTRY) + bytes.fromhex("4e93"),
                    b"\x4e\xb9" + be32(syms["tune_entry"]) + build_engine.NOP, "the tune image: record 431's entry through ours")]
    return out, syms


def once_patches(image, srr=False, stay=False, scratch=None, nxt=None, handrec=False, firstrec=False):
    for addr, stock, what in ONCE_CONTEXT + (STAY_CONTEXT if stay else []):
        _expect(image, addr, bytes.fromhex(stock), "REC's ONCE, " + what)
    if stay and image.count(be32(mm.STEP_PLAY)):  # its two callers are by calls relative to the pc: no third by a long
        raise fw.GuardError("the routine that plays a step is named by a long in the main program")
    # no address of a changed place, and none inside one, is named anywhere: a branch to it would leave no long, so
    # the listing was searched too (docs/FINDINGS.md)
    for addr in (mm.STEP_LOCKS_PUSH, mm.STEP_LOCKS_PUSH + 2, mm.STEP_LOCKS_PUSH + 6, mm.STEP_NO_LOCKS, mm.MAIN_LOOP_WAIT, mm.MAIN_LOOP_WAIT + 6,
                 mm.CAVE_ONCE[0]):
        if image.count(be32(addr)):
            raise fw.GuardError("the address %#x is named in the main program" % addr)
    caves = {"o": mm.CAVE_ONCE}
    if stay:  # the stay image: the main task's routine in a run of its own
        for addr in (mm.CAVE_STAY[0] - 2, mm.CAVE_STAY[1] - 2):
            _expect(image, addr, bytes.fromhex("4e75"), "the stay image's run starts and ends a routine")
        if image.count(be32(mm.CAVE_STAY[0])):
            raise fw.GuardError("the stay image's run is named in the main program")
        caves["e"] = mm.CAVE_STAY
    if handrec:  # the handrec image: a start's two stores of the state, through ours; its own in the long image's run
        for addr in (mm.CAVE_LONG[0] - 2, mm.CAVE_LONG[1] - 2):
            _expect(image, addr, bytes.fromhex("4e75"), "the handrec image's run starts and ends a routine")
        if any(image.count(be32(a)) for a in range(mm.CAVE_LONG[0], mm.CAVE_LONG[1], 2)):
            raise fw.GuardError("an address in the handrec image's run is named in the main program")
        caves["b"] = mm.CAVE_LONG
        for at in mm.SEQ_STARTS:
            if image.count(be32(at)):
                raise fw.GuardError("a start's store of the state is named in the main program")
        _expect(image, 0x4008ad40, bytes.fromhex(fw.sx("f3d1e43732840933")), "the handrec image: MIDI start sent before the first store of state 1")
        for addr, stock, what in HANDREC_CONTEXT:
            _expect(image, addr, bytes.fromhex(stock), "the handrec image: " + what)
    if firstrec:  # the firstrec image: what a start queues for the first step
        for addr, stock, what in FIRSTREC_CONTEXT:
            _expect(image, addr, bytes.fromhex(stock), "the firstrec image: " + what)
    code, syms = build_engine.compile_code(("once.S", "onceclean.c"), caves, "once_firstrec" if firstrec else "once_handrec" if handrec else "once_next" if nxt else "once_scratch" if scratch else "once_stay" if stay else "once_srr" if srr else "once",
                                           ("STEP_LOCKS=%#x" % mm.STEP_LOCKS, "MAIN_WAIT=%#x" % mm.MAIN_WAIT, "PARAM_SENT=%#x" % mm.PARAM_SENT,
                                            "LOCK_ONCE=%#x" % mm.ONCE_WORD, "LOCK_SPENT=%#x" % mm.ONCE_SPENT)
                                           + (("SRR",) if srr else ())  # the srr image: an old pattern's locks of MODE are taken off there too
                                           + (("STAY", "SRR_DIRTY_AT=%#x" % mm.SRR_DIRTY) if stay else ())
                                           + (("SCRATCH", "SCRATCH_POLL_AT=%#x" % scratch) if scratch else ())
                                           + (("NEXT", "NEXT_POLL_AT=%#x" % nxt) if nxt else ())
                                           + (("HANDREC", "SEQ_STATE=%#x" % mm.SEQ_STATE, "TEMPO=%#x" % mm.TEMPO, "PATTERN_DATA=%#x" % mm.PATTERN_DATA,
                                               "LEN_TABLE=%#x" % mm.LEN_TABLE) if handrec else ())
                                           + (("FIRSTREC", "PLACES=%#x" % mm.SEQ_PLACES) if firstrec else ()))  # the next image: DEST's NEXT kept at each message     # the scratch image: the poll at each message    # the stay image: nothing is spent where a step is only brought up to date
    start, end = mm.CAVE_ONCE
    if handrec and (syms["hand_hold"], syms["hand_left"], syms["hand_rec"]) != (mm.HAND_HOLD, mm.HAND_LEFT, mm.HAND_REC):
        raise fw.GuardError("the handrec image's numbers and hand_rec must be first in the long image's run")
    if syms["once_vars"] != mm.ONCE_ARM or code["o"][:mm.ONCE_VARS] != bytes(mm.ONCE_VARS):
        raise fw.GuardError("the once image's sixteen bytes must be first in its run, and 0")
    new = code["o"] + build_engine.NOP * ((end - start - len(code["o"])) // 2)
    out = [fw.Patch(3, mm.off(start), image[mm.off(start):mm.off(end)], new, "REC's ONCE: the code")]
    if stay:
        lo, hi = mm.CAVE_STAY
        out.append(fw.Patch(3, mm.off(lo), image[mm.off(lo):mm.off(hi)], code["e"] + build_engine.NOP * ((hi - lo - len(code["e"])) // 2),
                            "REC's ONCE: the main task's routine"))
    # movel %fp,%sp@- ; jsr %pc@(the routine that gathers) -> jsr once_seq
    out.append(fw.Patch(3, mm.off(mm.STEP_LOCKS_PUSH), bytes.fromhex(fw.sx("0ee11b0bb6ee28351aab")), JSR + be32(syms["once_seq"]),
                        "REC's ONCE: a step with locks is played through our routine"))
    # clrl %fp@(8) -> bsr.w once_none
    reach = syms["once_none"] - (mm.STEP_NO_LOCKS + 2)
    if not -0x8000 <= reach < 0:
        raise fw.GuardError("the once image's run is out of a word's reach of the step routine")
    out.append(fw.Patch(3, mm.off(mm.STEP_NO_LOCKS), bytes.fromhex(fw.sx("55797405b7ed80d5")), b"\x61\x00" + (reach & 0xFFFF).to_bytes(2, "big"),
                        "REC's ONCE: a step with no locks is played through our routine"))
    # jsr (the wait) -> jsr once_loop
    out.append(fw.Patch(3, mm.off(mm.MAIN_LOOP_WAIT), JSR + be32(mm.MAIN_WAIT), JSR + be32(syms["once_loop"]),
                        "REC's ONCE: the main task takes a spent lock off when a message has come"))
    if handrec:  # the handrec image: its run
        lo, hi = mm.CAVE_LONG
        out.append(fw.Patch(3, mm.off(lo), image[mm.off(lo):mm.off(hi)], code["b"] + build_engine.NOP * ((hi - lo - len(code["b"])) // 2),
                            "REC's ONCE: a take played by hand, held for the TRIG page's LEN"))
    if handrec:  # movel %d0,SEQ_STATE -> jsr hand_start
        for at in mm.SEQ_STARTS:
            out.append(fw.Patch(3, mm.off(at), b"\x23\xc0" + be32(mm.SEQ_STATE), JSR + be32(syms["hand_start"]),
                                "REC's ONCE: a start takes every track's ONCE back"))
    return out, syms


# The hits image: the per-block routine's call of the filter's envelope comes to ours, which hands it a trig of its
# own for each hit DEL lets through on a sampler track and DEL at 0 there (engine/hits.c). Stock code it leans on:
HITS_CONTEXT = [
    (mm.FILTER_ENV_CALL - 14, fw.sx("0ea2ff69e7a987f6acd0b0a3dd64294eed2d81d6") + "%08x" % mm.FILTER_ENV + fw.sx("36f1f38d930cad77"),
     "the per-block routine hands the envelope (the block, the trigs, the releases, the tracks it skips)"),
    (mm.FILTER_ENV, fw.sx("2c53c18c04422a47f8de2b03c7ab30b4a557"), "the envelope: its arguments on the stack, the block first"),
    (mm.FILTER_ENV + 0x4a, fw.sx("3e075b85ab0c7930814b"), "a trig: the delay's state if DEL's word is not 0"),
    (mm.FILTER_ENV + 0x5a, fw.sx("2af60ea991ae13b1"), "and the value from nothing if FENR's word is not 0"),
    (mm.FILTER_ENV + 0x10e, fw.sx("9fe8a9d4548e7988"), "a track's params 142 bytes on"),
    (0x400a4c4a, fw.sx("6d55aeb745e67fad"), "the machine's type, a byte up, into the block at + 62 before the call"),
    (mm.CAVE_HITS[0] - 2, "4e75", "our run starts a routine"),
    (mm.CAVE_HITS[1] - 2, "4e75", "our run ends one"),
]


# The hitui image: on a sampler track DEL is named HITS on FLTR2 and in the pop-up, and FLTR1's picture of the
# envelope has no delay in it (engine/hits.c, HITUI). Stock code it changes or leans on:
HITUI_CONTEXT = [
    (mm.FILTER_CLASS + mm.PAGE_DRAW_METHOD, "%08x" % mm.FILTER_DRAW, "the filter page's draw"),
    (mm.FILTER_DRAW + 0x10, fw.sx("691f41fa760c46f523e2db9c225e6ace024899e01595f3208e375fc0b48b5865"),
     "it asks the page's number: 7, 9 or 11 its FLTR1 loop"),
    (mm.FILTER_DRAW + 0x40, fw.sx("13cbc03227b6314e599f91cc62f3382b6ccc9a3b2457a53f0b174824344a"), "and 10 its FLTR2 loop"),
    (mm.FLTR2_NAME, fw.sx("1e9b6656da333fb20c3f74989115b21c289a5dbac8d73be023eb882a8f94205bc750bd05c0a6"),
     "FLTR2's loop: a knob's name from the descriptors, the record in d2, the page in a2"),
    (mm.FLTR1_DEL - 0x44, fw.sx("f2c6b00fe2fbd850ca61"), "FLTR1's loop: a3 is the routine that gives a record's value"),
    (mm.FLTR1_DEL - 0x0a, fw.sx("e6ecb332e683cb6f2a337cdde380f2563b646b3d"), "FLTR1's picture: DEL's value, ATK's before it, 24 bytes"),
    (mm.POPUP_NAME - 0x0e, fw.sx("75e04cf7d632d1709f58f943e41908cfbea5bfae0700057569eb4b1a"),
     "the pop-up: the name from the holder's method at + 88, record 498's and 502's joining here"),
    (mm.FILTER_CLASS + mm.PAGE_TURN_METHOD, "%08x" % mm.KNOB_TURN, "the filter page turns a knob through the base routine"),
]


def hits_patches(image, ui=False, soloend=False, trans=False):
    for addr, stock, what in HITS_CONTEXT + (HITUI_CONTEXT if ui else []):
        _expect(image, addr, bytes.fromhex(stock), "the hits image, " + what)
    if any(image.count(be32(a)) for a in range(mm.CAVE_HITS[0], mm.CAVE_HITS[1], 2)):
        raise fw.GuardError("an address in the hits' run is named in the main program")
    start, end = mm.CAVE_HITS
    code, syms = build_engine.compile_code(("hits.c",), dict({"o": mm.CAVE_HITS}, **({"t": mm.CAVE_TRANS} if trans else {})), "trans" if trans else "soloend" if soloend else "hitui" if ui else "hits",
                                           (("HITUI",) if ui else ()) + (("SOLOEND",) if soloend else ()) + (("TRANS",) if trans else ()))
    if soloend and not (syms["solo_gone"] == mm.SOLO_GONE and code["o"][:12] == bytes(12)):
        raise fw.GuardError("the soloend image's twelve bytes must be first in the hits' run, and 0")
    new = code["o"] + build_engine.NOP * ((end - start - len(code["o"])) // 2)
    out = [fw.Patch(3, mm.off(start), image[mm.off(start):mm.off(end)], new, "the hits image: the call of the filter's envelope"),
           fw.Patch(3, mm.off(mm.FILTER_ENV_CALL + 2), be32(mm.FILTER_ENV), be32(syms["hits_env"]),
                    "the hits image: the filter's envelope is called through ours")]
    if ui:
        out.append(fw.Patch(3, mm.off(mm.FLTR2_NAME), image[mm.off(mm.FLTR2_NAME):mm.off(mm.FLTR2_NAME) + 28],
                            bytes.fromhex(fw.sx("667fc4a591f6269c699c")) + be32(syms["hit_short"]) + bytes.fromhex(fw.sx("2bd6dddd538bea8e")) + build_engine.NOP * 7,
                            "the hitui image: FLTR2's names through ours"))
        out.append(fw.Patch(3, mm.off(mm.FLTR1_DEL), bytes.fromhex(fw.sx("26144ebed5cdcdfd6e7c")), b"\x4e\xb9" + be32(syms["hit_deldraw"]),
                            "the hitui image: FLTR1's picture is handed DEL through ours"))
        out.append(fw.Patch(3, mm.off(mm.POPUP_NAME), bytes.fromhex(fw.sx("89f24dd00698da0dbd04")), b"\x4e\xb9" + be32(syms["hit_popname"]),
                            "the hitui image: the pop-up's name through ours"))
    if trans:  # the trans image: FLTR2 draws DEL as a knob on a sampler track
        a, b = mm.CAVE_TRANS
        for addr in (a - 2, b - 2):
            _expect(image, addr, bytes.fromhex("4e75"), "the trans image's run starts and ends a routine")
        if any(image.count(be32(x)) for x in range(a, b, 2)):
            raise fw.GuardError("an address in the trans image's run is named in the main program")
        out.append(fw.Patch(3, mm.off(a), image[mm.off(a):mm.off(b)], code["t"] + build_engine.NOP * ((b - a - len(code["t"])) // 2),
                            "the trans image: FLTR2's DEL as a knob"))
        out.append(fw.Patch(3, mm.off(mm.FLTR2_DEL), bytes.fromhex(fw.sx("22bef79fb292776dd6d4")), b"\x4e\xf9" + be32(syms["del_knob"]),
                            "the trans image: FLTR2's test of DEL through ours"))
        out.append(fw.Patch(3, mm.off(mm.DEL_GFX), bytes.fromhex("4fef fff4 48d7 001c".replace(" ", "")),
                            b"\x4e\xf9" + be32(syms["del_gfx"]) + build_engine.NOP, "the trans image: the delay's graphic through ours"))
        out.append(fw.Patch(3, mm.off(mm.KNOB_LABEL), bytes.fromhex(fw.sx("3ed55d71aee7fb48de1a")), b"\x4e\xb9" + be32(syms["trans_label"]),
                            "the trans image: a knob's name through ours"))
    return out, syms


def patches(image, mixer=True, rec=False, big=False, keep=False, double=False, screen=False, page=False, load=False, bank=False,
            mute=False, floor=False, reclock=False, meter=False, save=False, probe=False, stereo=False, timed=False, gain=False,
            auto=False, peak=True, pack=False, stops=False, solo=False, ptn=False, feed=False, once=False, soloknob=False, xfade=False, prof=False):
    soloknob = soloknob or xfade  # the xfade image: the soloknob image's main program, with a crossfade on the sampling page's knob G
    once = once or soloknob  # the soloknob image: the once image's main program, with a solo on the sampling page's knob E
    feed = feed or once  # the once image: the feed image's main program, with REC's third setting
    ptn = ptn or feed  # the feed image: the ptn image's main program, with a block of a take written in a third of the instructions or less
    solo = solo or ptn  # the ptn image: the solo image's main program, with the takes written when a whole pattern is saved
    stops = stops or solo  # the solo image: the stops image's main program, with the pattern's mutes as solos
    pack = pack or stops  # the stops image: the pack image's main program, with a turn of SMPL that skips what is no sample
    auto = auto or pack  # the pack image: the mode image's main program, with SMPL and DEST reading 33 to 64 as single slots
    gain = gain or auto  # the mode image: the gain image's main program, with what a take is on the sampling page,
    # MODE gone from the first, and (peak) the audio CPU's load in the page's last place
    stereo = stereo or timed or gain  # the time image: the stereo image's main program with the audio CPU's load on the page.
    # The gain image: the stereo image's with a record gain on the page and in the feed
    save = save or probe or stereo  # the probe image: the save image's main program with three numbers on the page
    meter = meter or save
    reclock = reclock or meter
    floor = floor or reclock
    mute = mute or floor
    bank = bank or mute
    load = load or bank
    page = page or load
    screen = screen or page
    double = double or screen
    keep = keep or double
    rec, big = rec or keep, big or keep
    srr = xfade >= 8  # the srr image: the multi image with sample rate reduction in MODE's parameter
    prof = prof or xfade >= 11  # the prof image: the stay image with the profile of the main CPU, kept from here on
    out = descriptor_patches(image, page, floor, meter, auto, srr, xknob=xfade >= 26) + display_patches(image, words=screen, srr=srr, xknob=xfade >= 26)
    syms = {}
    if mixer or rec:
        more, syms = mixer_patches(image, rec, page, bank, mute, reclock, meter, stereo, gain, auto, feed, soloknob, xfade, prof)
        out += more
    if big:
        more, big_syms = bigslot_patches(image, halves=double)
        out += more
        syms = dict(syms, **big_syms)
    if keep:
        more, keep_syms = keep_patches(image, load, bank, save, ptn, phone=xfade >= 22, knows=xfade >= 28, capture=xfade >= 36, scratch=xfade >= 47, mirror=xfade >= 64, seen=xfade >= 70, fresh=xfade >= 75, newproj=xfade >= 76, wipe=xfade >= 77, stream=xfade >= 78, evict=xfade >= 79)
        out += more
        syms = dict(syms, **keep_syms)
    if screen:
        more, screen_syms = screen_patches(image, page, meter, auto, pack, xknob=2 if xfade >= 27 else xfade >= 26)
        out += more
        syms = dict(syms, **screen_syms)
    if page:
        more, page_syms = page_patches(image, bank, reclock, meter, syms["save_start"] if save else None, probe, timed, gain, auto, auto and peak, pack,
                                       stops, ptn, feed, once, soloknob, xfade, syms["prof_on"] if prof else None)
        out += more
        syms = dict(syms, **page_syms)
    if stereo:
        more, right_syms = right_patches(image, stops, dma=xfade >= 3, lap=15 <= xfade < 41, movem=xfade >= 37)  # 41: the cut image, no laps      # 3: the dma image, the gfade image with the right channels by a transfer
        out += more
        syms = dict(syms, **right_syms)
    if solo and not soloknob:  # (the soloknob image: the purple keys are stock's pattern mutes again)
        more, solo_syms = solo_patches(image)
        out += more
        syms = dict(syms, **solo_syms)
    if once:
        more, once_syms = once_patches(image, srr, stay=xfade >= 10, scratch=syms["scratch_poll"] if xfade >= 47 else None,
                                       nxt=syms["next_poll"] if xfade >= 61 else None, handrec=xfade >= 81, firstrec=xfade >= 82)
        out += more
        syms = dict(syms, **once_syms)
    if xfade >= 16:  # the hits image: a long sample's hits start the filter's envelope again, by DEL
        more, hit_syms = hits_patches(image, ui=xfade >= 17, soloend=xfade >= 48, trans=xfade >= 60)  # 17: the hitui image, DEL named HITS and no delay drawn
        out += more
        syms = dict(syms, **hit_syms)
    if xfade >= 64:  # the mirror image: the screen to a viewer over USB
        more, mirror_syms = mirror_patches(image, shadow=xfade >= 66, pieces=xfade >= 67)  # 66: the shadow image. 67: the sink image
        out += more
        syms = dict(syms, **mirror_syms)
    if xfade >= 68:  # the tune image: a pushed turn of the sampler's TUNE by 1
        more, tune_syms = tune_patches(image)
        out += more
        syms = dict(syms, **tune_syms)
    if xfade >= 23:  # the trig image: STRT and LOOP, LEN and SRR changed over on the first page
        out += first_page_patches(image)
    if xfade == 30:  # the long image: patterns 1..64 long, 65..128 their tails
        more, long_syms = long_patches(image)
        out += more
        syms = dict(syms, **long_syms)
    if xfade >= 35:  # the rxoff image: stock's USB audio receive not run while the unit sends its own
        lo, hi = mm.CAVE_RXGATE
        for addr in (lo - 2, hi - 2):
            _expect(image, addr, bytes.fromhex("4e75"), "the rxoff image's run starts and ends a routine")
        if any(image.count(be32(a)) for a in range(lo, hi, 2)):
            raise fw.GuardError("an address in the rxoff image's run is named in the main program")
        code, rx_syms = build_engine.compile_code(("rxgate.S",), {"x": mm.CAVE_RXGATE}, "rxgate_cap" if xfade >= 36 else "rxgate",
                                                  ("CAPTURE",) if xfade >= 36 else ())  # the rxcap image: and the phone has said a capture is on
        if xfade >= 36 and rx_syms["rx_capture"] != mm.CAVE_RXGATE[0]:
            raise fw.GuardError("the rxcap image's word must be first in the gate's run, where the phone's code finds it")
        out.append(fw.Patch(3, mm.off(lo), image[mm.off(lo):mm.off(hi)], code["x"] + build_engine.NOP * ((hi - lo - len(code["x"])) // 2),
                            "the rxoff image: the gate"))
        _expect(image, mm.RX_CALL, b"\x4e\xb9" + be32(0x400041cc), "the per-block routine's call of the USB audio receive")
        _expect(image, mm.RX_CALL - 10, bytes.fromhex("4878002048794551200040"[:20]) , "its two arguments, 32 and 0x45512000")
        out.append(fw.Patch(3, mm.off(mm.RX_CALL + 2), be32(0x400041cc), be32(rx_syms["rx_gate"]), "the rxoff image: the receive through the gate"))
        syms = dict(syms, **rx_syms)
    if xfade >= 62:  # the pbank image: the sample bank in the PROJECT menu, off the sampling page
        more, pb_syms = pbank_patches(image)
        out += more
        syms = dict(syms, **pb_syms)
    if EVLAP:  # the evtime tool: four laps in the events and knobs stretch
        more, ev_syms = evlap_patches(image, skip=(mm.RX_CALL,) if xfade >= 35 else ())  # the evrx tool: the receive's call is the gate's
        out += more
        syms = dict(syms, **ev_syms)
    return out, syms


def pbank_patches(image):
    """The pbank image (engine/pbank.c): the PROJECT menu's constructor ends in ours, which adds a fourth entry, SAMPLE
    BANK, that moves BANK_WANT on when chosen.
    """
    lo, hi = mm.CAVE_PBANK
    for addr in (lo - 2, hi - 2):
        _expect(image, addr, bytes.fromhex("4e75"), "the pbank image's run starts and ends a routine")
    if any(image.count(be32(a)) for a in range(lo, hi, 2)):
        raise fw.GuardError("an address in the pbank image's run is named in the main program")
    code, syms = build_engine.compile_code(("pbank.c",), {"pb": mm.CAVE_PBANK}, "pbank")
    out = [fw.Patch(3, mm.off(lo), image[mm.off(lo):mm.off(hi)], code["pb"] + build_engine.NOP * ((hi - lo - len(code["pb"])) // 2),
                    "the pbank image: the menu entry")]
    at = mm.PROJECT_MENU_END
    _expect(image, at, bytes.fromhex(fw.sx("285f2cd4d1cf3131d4a20c869449b4b2")), "the PROJECT menu constructor's restore and return")
    out.append(fw.Patch(3, mm.off(at), image[mm.off(at):mm.off(at) + 6], b"\x4e\xf9" + be32(syms["bank_hook"]),
                        "the pbank image: the PROJECT menu's end to ours"))
    return out, syms


def evlap_patches(image, skip=()):
    """The evtime tool (engine/evlap.S): each of four of stock's calls in the events and knobs stretch goes to a stub
    that reads the profile's timer into the record and jumps on to the routine.
    """
    lo, hi = mm.CAVE_EVLAP
    for addr in (lo - 2, hi - 2):
        _expect(image, addr, bytes.fromhex("4e75"), "the evtime tool's run starts and ends a routine")
    if any(image.count(be32(a)) for a in range(lo, hi, 2)):
        raise fw.GuardError("an address in the evtime tool's run is named in the main program")
    code, syms = build_engine.compile_code(("evlap.S",), {"e": mm.CAVE_EVLAP}, "evlap", ("PROF_AT=%#x" % mm.CAVE_PROF[0],))
    out = [fw.Patch(3, mm.off(lo), image[mm.off(lo):mm.off(hi)], code["e"] + build_engine.NOP * ((hi - lo - len(code["e"])) // 2),
                    "the evtime tool: four laps")]
    for k, (site, target) in enumerate(mm.EV_LAPS):
        if site in skip:  # a call another patch of this image takes: its lap is not reached
            continue
        _expect(image, site, b"\x4e\xb9" + be32(target), "the evtime tool: a call in the events stretch")
        out.append(fw.Patch(3, mm.off(site + 2), be32(target), be32(syms["ev_lap%d" % (k + 1)]), "the evtime tool: lap %d" % (k + 1)))
    return out, syms


# The long image: every cue of a pattern sets stock's play queue (mm.QUEUE_SET, thirteen calls); ours sets it and puts
# each head's tail after it with the head's kit. The UI's kit follows the playing pattern's number
# (mm.KIT_FOLLOW_CALL): ours gives the head's while a tail plays with the head's kit.
def long_patches(image):
    lo, hi = mm.CAVE_LONG
    for addr in (lo - 2, hi - 2):
        _expect(image, addr, bytes.fromhex("4e75"), "the long image's run starts and ends a routine")
    if any(image.count(be32(a)) for a in range(lo, hi, 2)):
        raise fw.GuardError("an address in the long image's run is named in the main program")
    if image.count(be32(mm.QUEUE_SET)) != len(mm.QUEUE_SET_CALLS):
        raise fw.GuardError("the queue's routine is named somewhere other than its thirteen calls")
    slo, shi = mm.CAVE_SEAM
    for addr in (slo - 2, shi - 2):
        _expect(image, addr, bytes.fromhex("4e75"), "the seam's run starts and ends a routine")
    if any(image.count(be32(a)) for a in range(slo, shi, 2)):
        raise fw.GuardError("an address in the seam's run is named in the main program")
    if image.count(be32(mm.LIVE_WRITE)) != 1:
        raise fw.GuardError("the live trig's writer is named somewhere other than its one call")
    elo, ehi = mm.CAVE_EDIT
    for addr in (elo - 2, ehi - 2):
        _expect(image, addr, bytes.fromhex("4e75"), "the edit run starts and ends a routine")
    named = lambda a: [i for i in range(len(image)) if image.startswith(be32(a), i) and i % 2 == 0]  # 0x40018d20's one match is at an odd place
    if any(image.count(be32(a)) and named(a) for a in range(elo, ehi, 2)):
        raise fw.GuardError("an address in the edit run is named in the main program")
    rlo, rhi = mm.CAVE_EDIT2
    for addr in (rlo - 2, rhi - 2):
        _expect(image, addr, bytes.fromhex("4e75"), "the paste's run starts and ends a routine")
    if any(named(a) for a in range(rlo, rhi, 2) if image.count(be32(a))):
        raise fw.GuardError("an address in the paste's run is named in the main program")
    code, syms = build_engine.compile_code(("longpat.c",), {"l": mm.CAVE_LONG, "m": (slo, shi - 4), "n": (shi - 4, shi),
                                                            "p": (elo, ehi - 8), "q": (ehi - 8, ehi), "r": mm.CAVE_EDIT2}, "longpat")
    out = [fw.Patch(3, mm.off(lo), image[mm.off(lo):mm.off(hi)], code["l"] + build_engine.NOP * ((hi - lo - len(code["l"])) // 2),
                    "the long image: code"),
           fw.Patch(3, mm.off(slo), image[mm.off(slo):mm.off(shi)],
                    code["m"] + build_engine.NOP * ((shi - 4 - slo - len(code["m"])) // 2) + code["n"], "the long image: the seam's code and its long"),
           fw.Patch(3, mm.off(elo), image[mm.off(elo):mm.off(ehi)],
                    code["p"] + build_engine.NOP * ((ehi - 8 - elo - len(code["p"])) // 2) + code["q"], "the long image: clear, copy and paste, and the kept tail"),
           fw.Patch(3, mm.off(rlo), image[mm.off(rlo):mm.off(rhi)], code["r"] + build_engine.NOP * ((rhi - rlo - len(code["r"])) // 2),
                    "the long image: the paste")]
    for at, stock, ours, what in ((mm.HIT_STEP_CALL, mm.HIT_STEP, "long_when", "a live hit carries its half"),
                                  (mm.LIVE_WRITE_CALL, mm.LIVE_WRITE, "long_rec", "the live trig's writer is told the half"),
                                  (mm.LIVE_NUMBER_CALL, mm.PLAYING_NUMBER, "long_num", "the writer's pattern number is the half's")):
        _expect(image, at, b"\x4e\xb9" + be32(stock), "the long image, " + what)
        out.append(fw.Patch(3, mm.off(at + 2), be32(stock), be32(syms[ours]), "the long image: " + what))
    for stock, calls, ours, what in ((mm.PATTERN_CLEAR, mm.PATTERN_CLEAR_CALLS, "long_clear", "a clear of a head clears its tail"),
                                     (mm.PATTERN_PASTE, mm.PATTERN_PASTE_CALLS, "long_paste", "a paste on a head pastes its tail"),
                                     (mm.PATTERN_COPY, mm.PATTERN_COPY_CALLS, "long_copy", "a copy of a head keeps its tail")):
        if image.count(be32(stock)) != len(calls):
            raise fw.GuardError("the long image: %#x is named somewhere other than its calls" % stock)
        for at in calls:
            _expect(image, at, b"\x4e\xb9" + be32(stock), "the long image, " + what)
            out.append(fw.Patch(3, mm.off(at + 2), be32(stock), be32(syms[ours]), "the long image: " + what))
    for at, op in ((mm.LIVE_NOW_CALL, b"\x4e\xba"), (mm.LIVE_NOW_LEA, b"\x47\xfa")):
        stock = (mm.NOW_PATTERN - (at + 2)).to_bytes(2, "big", signed=True)
        _expect(image, at, op + stock, "the long image, the live writer's selected pattern")
        out.append(fw.Patch(3, mm.off(at + 2), stock, (syms["long_now"] - (at + 2)).to_bytes(2, "big", signed=True),
                            "the long image: the live writer's pattern is the half's"))
    for call in mm.QUEUE_SET_CALLS:
        _expect(image, call, b"\x4e\xb9" + be32(mm.QUEUE_SET), "the long image, a call to the queue's routine")
        out.append(fw.Patch(3, mm.off(call + 2), be32(mm.QUEUE_SET), be32(syms["long_queue"]), "the long image: a cue adds the tails"))
    _expect(image, mm.KIT_FOLLOW_CALL, b"\x4e\xb9" + be32(mm.PLAYING_NUMBER), "the long image, the UI's kit follows the playing pattern")
    out.append(fw.Patch(3, mm.off(mm.KIT_FOLLOW_CALL + 2), be32(mm.PLAYING_NUMBER), be32(syms["long_kitnum"]),
                        "the long image: the UI's kit is the head's while its tail plays"))
    return out, {k: syms[k] for k in ("long_queue", "long_kitnum", "long_when", "long_rec", "long_now", "long_num", "long_clear", "long_copy", "long_paste")}


# The trig image: the sampler's own page has STRT and LOOP changed over, and LEN and SRR. The start-up routine stores
# each knob's record into machine 44's page entry (mm.PAGE_TABLE - 44, the record of knob k at + 8 + 4 k) with a movel
# of a register to an absolute long: the four stores change places, nothing else. A lock is kept by knob slot, so a
# project's locks stay with their knobs. (instruction, the record it stores, the knob it is stored for)
FIRST_PAGE = mm.PAGE_TABLE - mm.PAGE_STRIDE + 8
FIRST_SWAP = [
    (0x40196a42, "23c8", 499, 2, 4),  # STRT: C -> E
    (0x40196a48, "23c1", 501, 4, 2),  # LOOP: E -> C
    (0x40196a5c, "23c2", 502, 5, 6),  # SRR: F -> G
    (0x40196a62, "23c8", 500, 6, 5),  # LEN: G -> F
]


def first_page_patches(image):
    out = []
    for addr, op, record, was, now in FIRST_SWAP:
        _expect(image, addr, bytes.fromhex(op) + be32(FIRST_PAGE + 4 * was), "the first page's knob %d" % was)
        out.append(fw.Patch(3, mm.off(addr + 2), be32(FIRST_PAGE + 4 * was), be32(FIRST_PAGE + 4 * now),
                            "the trig image: record %d to the first page's knob %s" % (record, "ABCDEFGH"[now])))
    return out


def patched_image(image, mixer=True, rec=False, big=False, keep=False, double=False, screen=False, page=False, load=False, bank=False,
                  mute=False, floor=False, reclock=False, meter=False, save=False, probe=False, stereo=False, timed=False, gain=False,
                  auto=False, peak=True, pack=False, stops=False, solo=False, ptn=False, feed=False, once=False, soloknob=False, xfade=False, prof=False):
    ps, syms = patches(image, mixer, rec, big, keep, double, screen, page, load, bank, mute, floor, reclock, meter, save, probe, stereo, timed, gain,
                       auto, peak, pack, stops, solo, ptn, feed, once, soloknob, xfade, prof)
    buf = bytearray(image)
    for p in ps:
        if bytes(buf[p.offset:p.offset + len(p.stock)]) != p.stock:
            raise fw.GuardError("stock bytes differ at %#x (%s)" % (mm.BASE + p.offset, p.note))
        buf[p.offset:p.offset + len(p.new)] = p.new
    return bytes(buf), syms
