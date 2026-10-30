"""Compile engine/ and turn it into patches for section 7. Builds files only.

    python -m tools.build_engine            # sizes and symbols

The code is linked at the addresses of the caves in tools/audiomap.py. Each
cave becomes one patch whose stock side is the original dead code and whose
new side is our code padded with NOPs. Three pointer patches hook it in:
the update and render table entries of engine 11 and the interrupt's call
to the voice loop.
"""
import os
import shutil
import subprocess

from . import audiomap as m
from . import fw

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
NOP = b"\x4e\x71"
TAIL = b""          # the back image: what follows section 7's end (m.FAR's code), set by patches()
SRC = os.path.join(ROOT, "engine")
OUT = os.path.join(ROOT, "build", "engine")
SOURCES = ("sampler.c", "stub.S")
CFLAGS = ["-mcpu=54418", "-Os", "-ffreestanding", "-fno-builtin", "-fomit-frame-pointer",
          "-fno-pic", "-Wall", "-Wextra", "-Werror",
          "--param=min-pagesize=0"]      # the shared window is at address 0: not a null pointer here


def _tool(name):
    exe = shutil.which("m68k-elf-" + name) or shutil.which("m68k-linux-gnu-" + name)
    if not exe:
        raise RuntimeError("no ColdFire %s on PATH" % name)
    return exe


def _run(*cmd):
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


def compile_code(sources, caves, name, defines=(), flags=()):
    """Compile and link sources into caves {cave: (start, end)}.

    defines: extra -D options. flags: extra compiler options.
    Returns ({cave: code bytes}, {symbol: address}).
    """
    os.makedirs(OUT, exist_ok=True)
    objs = []
    for src in sources:                 # a name in engine/, or the whole path of a source the build made
        obj = os.path.join(OUT, "%s_%s.o" % (name, os.path.splitext(os.path.basename(src))[0]))
        _run(_tool("gcc"), *CFLAGS, *flags, *("-D" + d for d in defines), "-c", os.path.join(SRC, src), "-o", obj)
        objs.append(obj)
    script = os.path.join(OUT, name + ".ld")
    with open(script, "w") as f:
        f.write("SECTIONS {\n")
        for cave, (start, _) in sorted(caves.items()):
            f.write("  .cave_%s %#x : { *(.cave.%s) }\n" % (cave, start, cave))
        f.write("  /DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) }\n")
        f.write("  .stray : { *(*) }\n")
        f.write("  ASSERT(SIZEOF(.stray) == 0, \"code or data outside the caves\")\n}\n")
    elf = os.path.join(OUT, name + ".elf")
    _run(_tool("ld"), "-T", script, "-o", elf, *objs)
    code = {}
    for cave, (start, end) in caves.items():
        binf = os.path.join(OUT, "%s_cave_%s.bin" % (name, cave))
        _run(_tool("objcopy"), "-O", "binary", "-j", ".cave_" + cave, elf, binf)
        with open(binf, "rb") as f:
            code[cave] = f.read()
        if len(code[cave]) > end - start:
            raise fw.GuardError("cave %s: %d bytes of code, %d available"
                                % (cave, len(code[cave]), end - start))
        if len(code[cave]) % 2:
            raise fw.GuardError("cave %s: odd code size" % cave)
    syms = {}
    for line in _run(_tool("nm"), elf).splitlines():
        addr, kind, sym = line.split()
        if kind in "Tt":
            syms[sym] = int(addr, 16)
    return code, syms


def compile_engine(rec=False, keep=False, page=False, load=False, bank=False, fade=False, live=False, len_live=False,
                   floor=False, reclock=False, pitch=False, stereo=False, timed=False, twelve=False, auto=False, cross=False, pack=False,
                   stops=False, multi=False, srr=False, soft=False, tail=False, hits=False, trim=False, slim=False, six=False, eight=False, curve=False, peak=False, xknob=False, slice=False, ring=False, allright=False, scan=False, norm=False, back=False, stretch=False, lock=False, scrub=False, slscrub=False, grain=False, spread=False, trap=False, letgo=False, handrec=False):
    """The audio CPU sampler, with the recorder if asked, with the recorder's half of keeping
    takes if asked, with the sampling page's take if asked, and with slots loaded while the unit
    runs if asked. Returns ({cave: code bytes}, {symbol: address})."""
    if pitch or stereo:                     # a frame between two is worked out from sixteen: the table is made here
        from . import sinctable
        os.makedirs(OUT, exist_ok=True)
        table = os.path.join(OUT, "hqtab8n.S" if eight else "hqtab6n.S" if six else "hqtab12n.S" if auto else "hqtab12.S" if twelve else "hqtab.S")
        with open(table, "w") as f:
            f.write(sinctable.source("z", twelve, narrow=auto, six=six, eight=eight) if six or eight else sinctable.source("z", twelve, narrow=auto))     # the mode image on: a row's twelve numbers and not its four noughts, for room
        caves = dict(m.CAVES, **m.REC_CAVES, **m.FADE_CAVES, **m.LIVE_CAVES, **m.PITCH_CAVES)
        defines = ("RECORDER", "KEEP", "PAGE", "LOAD", "BIGPUT", "FADE", "LIVE", "LIVE_STRT", "FLOOR", "RECLOCK", "HQ",
                   "HQ_MAGIC=%#x" % (sinctable.magic(twelve, six, eight) if six or eight else sinctable.magic(twelve))) + (("TWELVE",) if twelve else ())
        if stereo:                          # one-track stereo: the right channel through stock's stages, in four more runs,
            #                                 and the sums of sixteen frames made stock's way, in Twinshot's own run
            caves = dict(caves, **m.ONE_CAVES, **m.QUICK_CAVES, **m.LEAN_CAVES)
            if auto:                        # the mode image: a sample is mono or stereo by what its slots hold. And the cross
                #                             image: a loop's end blended into its start. Both with the time image's routine
                #                             And the pack image: single slots at the back. And the stops image: what every
                #                             slot holds, said to the main CPU
                return compile_code(SOURCES + (table,), dict(dict(caves, **m.TIMED_CAVES, **(m.CROSS_CAVES if cross else {}), **(m.SRR_CAVES if srr else {}),
                                                             **(m.HITS_CAVES if hits else {}), **(m.SCAN_CAVES if scan else {}), **(m.TRAP_CAVES if trap else {})), **(dict(m.BACK_CAVES, **(m.GRAIN_CAVES if grain else m.STRETCH_CAVES)) if stretch else m.BACK_CAVES if back else {})),
                                    "sampler_handrec" if handrec else "sampler_letgo" if letgo else "sampler_trap" if trap else "sampler_spread" if spread else "sampler_grain" if grain else "sampler_slscrub" if slscrub else "sampler_scrub" if scrub else "sampler_lock" if lock else "sampler_stretch" if stretch else "sampler_back" if back else "sampler_norm" if norm else "sampler_scan" if scan else "sampler_allright" if allright else "sampler_ring" if ring else "sampler_slice" if slice else "sampler_xknob" if xknob else "sampler_peak" if peak else "sampler_curve" if curve else "sampler_eight" if eight else "sampler_six" if six else "sampler_slim" if slim else "sampler_trim" if trim else "sampler_hits" if hits else "sampler_tail" if tail else "sampler_soft" if soft else "sampler_srr" if srr else "sampler_multi" if multi else "sampler_stops" if stops else "sampler_pack" if pack else "sampler_cross" if cross else "sampler_mode",
                                    defines + ("ONETRACK", "QUICK", "LEAN", "TIMED", "AUTO", "NARROW") + (("XFADE",) if cross else ())
                                    + (("PACK",) if pack else ()) + (("STOPS",) if stops else ())
                                    + (("MULTI",) if multi else ())       # the multi image: a block a track, taken before the voice loop
                                    + (("SRR",) if srr else ())           # the srr image: sample rate reduction, in SY SWARM's room
                                    + (("SOFT",) if soft else ())         # the soft image: a note that starts on a loud frame is faded in
                                    + (("TAIL",) if tail else ())         # the tail image: a one-shot is faded out before its end wherever that is
                                    + (("HITS",) if hits else ())        # the hits image: a sample's hits, said to the main CPU for the filter's envelope
                                    + (("TRIM",) if trim else ())       # the trim image: the pitched sum, the fade and a loop's blend for less
                                    + (("SLIM",) if slim else ())
                                    + (("SIX",) if six else ())
                                    + (("EIGHT",) if eight else ())     # the eight image: a pitched frame summed from eight         # the six image: a pitched frame summed from six       # the slim image: hits off where unasked, the pitched sum's tests once a run
                                    + (("HITCURVE",) if curve else ())
                                    + (("HITPEAK",) if peak else ())
                                    + (("XKNOB",) if xknob else ())
                                    + (("SLICE",) if slice else ()) + (("RING",) if ring else ()) + (("ALLRIGHT",) if allright else ()) + (("HITSCAN",) if scan else ()) + (("NORM",) if norm else ())
                                    + (("BACK", "FAR_SRC=%#x" % m.IMAGE_END, "FAR_DST=%#x" % m.FAR,
                                        "FAR_LONGS=%d" % ((m.FAR_BYTES_GRAIN if grain else m.FAR_BYTES_LOCK if lock else m.FAR_BYTES_STR if stretch else m.FAR_BYTES) // 4)) if back else ())
                                    + (("STRETCH", "STR_BASE=%#x" % m.STR_BASE) if stretch else ()) + (("LOCK",) if lock else ()) + (("SCRUB",) if scrub else ()) + (("SLSCRUB",) if slscrub else ()) + (("GRAIN",) if grain else ()) + (("SPREAD",) if spread else ()) + (("TRAP",) if trap else ()) + (("LETGO",) if letgo else ()) + (("HANDREC",) if handrec else ()))     # the slice image: the keys play slices where KEYS says     # the xknob image: DEC's slot is the crossfade's, and a note holds     # the switch image: a hit's steps from the slot's loudest frame     # the trig image: the six image's engine, a hit's loudness in finer steps
            if timed:                       # the time image: the stereo image's engine, and two calls of the interrupt's timed
                return compile_code(SOURCES + (table,), dict(caves, **m.TIMED_CAVES), "sampler_time12" if twelve else "sampler_time",
                                    defines + ("ONETRACK", "QUICK", "LEAN", "TIMED"))
            return compile_code(SOURCES + (table,), caves, "sampler_stereo12" if twelve else "sampler_stereo",
                                defines + ("ONETRACK", "QUICK", "LEAN"))
        return compile_code(SOURCES + (table,), caves, "sampler_pitch", defines)
    if floor or reclock:                    # LEN stops at 3; and a step's REC is a lock of its own
        return compile_code(SOURCES, dict(m.CAVES, **m.REC_CAVES, **m.FADE_CAVES, **m.LIVE_CAVES),
                            "sampler_reclock" if reclock else "sampler_floor",
                            ("RECORDER", "KEEP", "PAGE", "LOAD", "BIGPUT", "FADE", "LIVE", "LIVE_STRT", "FLOOR") + (("RECLOCK",) if reclock else ()))
    if live:                                # LEN and STRT while a note plays
        return compile_code(SOURCES, dict(m.CAVES, **m.REC_CAVES, **m.FADE_CAVES, **m.LIVE_CAVES), "sampler_live",
                            ("RECORDER", "KEEP", "PAGE", "LOAD", "BIGPUT", "FADE", "LIVE", "LIVE_STRT"))
    if len_live:                            # LEN alone
        return compile_code(SOURCES, dict(m.CAVES, **m.REC_CAVES, **m.FADE_CAVES, **m.LIVE_CAVES), "sampler_len",
                            ("RECORDER", "KEEP", "PAGE", "LOAD", "BIGPUT", "FADE", "LIVE"))
    if fade:
        return compile_code(SOURCES, dict(m.CAVES, **m.REC_CAVES, **m.FADE_CAVES), "sampler_fade",
                            ("RECORDER", "KEEP", "PAGE", "LOAD", "BIGPUT", "FADE"))
    if bank:
        return compile_code(SOURCES, dict(m.CAVES, **m.REC_CAVES), "sampler_bank", ("RECORDER", "KEEP", "PAGE", "LOAD", "BIGPUT"))
    if load:
        return compile_code(SOURCES, dict(m.CAVES, **m.REC_CAVES), "sampler_load", ("RECORDER", "KEEP", "PAGE", "LOAD"))
    if page:
        return compile_code(SOURCES, dict(m.CAVES, **m.REC_CAVES), "sampler_page", ("RECORDER", "KEEP", "PAGE"))
    if keep:
        return compile_code(SOURCES, dict(m.CAVES, **m.REC_CAVES), "sampler_keep", ("RECORDER", "KEEP"))
    if rec:
        return compile_code(SOURCES, dict(m.CAVES, **m.REC_CAVES), "sampler_rec", ("RECORDER",))
    return compile_code(SOURCES, m.CAVES, "sampler")


def patches(image, rec=False, keep=False, page=False, load=False, bank=False, fade=False, live=False, len_live=False,
            floor=False, reclock=False, pitch=False, stereo=False, timed=False, twelve=False, auto=False, cross=False, pack=False,
            stops=False, multi=False, srr=False, soft=False, tail=False, hits=False, trim=False, slim=False, six=False, eight=False, curve=False, peak=False, xknob=False, slice=False, ring=False, allright=False, scan=False, norm=False, back=False, stretch=False, lock=False, scrub=False, slscrub=False, grain=False, spread=False, trap=False, letgo=False, handrec=False):
    """fw.Patch list that installs the sampler in the given stock section 7. The back image's code past the section's
    end is left in TAIL."""
    global TAIL
    TAIL = b""
    letgo = letgo or handrec                # the handrec image: the letgo image's engine, a held take's release let be
    trap = trap or letgo                    # the letgo image: the trap image's engine, a stereo note's right let go when over
    spread = spread or trap                 # the trap image: the spread image's engine, a stretched note for less
    grain = grain or spread                 # the spread image: the grain image's engine with its look in slices
    slscrub = slscrub or grain              # the grain image: the slscrub image's engine with a stretch that holds together
    scrub = scrub or slscrub                # the slscrub image: the scrub image's engine with a slice's knobs followed
    lock = lock or scrub                    # the scrub image: the lock image's engine with STRT and LEN followed when stretched
    stretch = stretch or lock               # the lock image: the stretch image's engine with a stretch locked to the tempo
    back = back or stretch                  # the stretch image: the back image's engine with a note's speed apart from its pitch
    norm = norm or back                     # the back image: the norm image's engine, caves d, e and g past the section's end
    scan = scan or norm                     # the norm image: the scan image's engine with every take normalized
    ring = ring or allright or scan         # the scan image: the ring image's engine with its own hits scan, in SD BASIC's room. And
    # the allright image: the ring image's engine with every track's right half sent
    slice = slice or ring                   # the ring image: the slice image's engine with LEN to the sample's end
    xknob = xknob or slice                  # the slice image: the xknob image's engine with the keys playing slices
    peak = peak or xknob                    # the xknob image: the switch image's engine with DEC no longer read
    curve = curve or peak                   # the switch image: the trig image's engine with the steps from a slot's loudest frame
    six = six or curve                      # the trig image: the six image's engine with a hit's loudness in finer steps
    slim = slim or six or eight             # the eight image: the slim image's engine with a sum of eight, in six's place
    slim = slim or six                      # the six image is the slim image's engine with a sum of six
    trim = trim or slim                     # the slim image is the trim image's engine for less again
    hits = hits or trim                     # the trim image is the hits image's engine with pitched notes and loops for less
    tail = tail or hits                     # the hits image is the tail image's engine with a sample's hits said to the main CPU
    soft = soft or tail                     # the tail image is the soft image's engine with a one-shot's end faded out
    srr = srr or soft                       # the soft image is the srr image's engine with a loud start faded in
    multi = multi or srr                    # the srr image is the multi image's engine with sample rate reduction
    stops = stops or multi                  # the multi image is the stops image's engine with a block a track for the takes
    pack = pack or stops                    # the stops image is the pack image's engine, saying what every slot holds
    cross = cross or pack                   # the pack image is the cross image's engine with single slots at the back
    auto = auto or cross                    # the cross image is the mode image's engine with the crossfade
    timed = timed or auto                   # and both carry the time image's routine: the maintainer, 2026-10-12, "keep cpu Peak
    twelve = twelve or auto                 # in the last box of smapling page for now whiel we're building"
    if twelve and not (stereo or timed):
        raise ValueError("the sum of twelve is the stereo image's engine with another table")
    stereo = stereo or timed
    pitch = pitch or stereo
    reclock = reclock or pitch
    floor = floor or reclock
    live = live or floor
    len_live = len_live or live
    fade = fade or len_live
    bank = bank or fade
    load = load or bank
    page = page or load
    keep = keep or page
    rec = rec or keep
    code, syms = compile_engine(rec, keep, page, load, bank, fade, live, len_live, floor, reclock, pitch, stereo, timed, twelve, auto, cross, pack,
                                stops, multi, srr, soft, tail, hits, trim, slim, six, eight, curve, peak, xknob, slice, ring, allright, scan, norm, back, stretch, lock, scrub, slscrub, grain, spread, trap, letgo, handrec)
    out = []
    used = dict(m.CAVES, **(m.REC_CAVES if rec else {}), **(m.FADE_CAVES if fade else {}), **(m.LIVE_CAVES if len_live else {}),
                **(m.PITCH_CAVES if pitch else {}))
    for more in ((m.ONE_CAVES, m.QUICK_CAVES, m.LEAN_CAVES) if stereo else ()) + ((m.TIMED_CAVES,) if timed else ()) + ((m.CROSS_CAVES,) if cross else ()) + ((m.SRR_CAVES,) if srr else ()) + ((m.HITS_CAVES,) if hits else ()) + ((m.SCAN_CAVES,) if scan else ()) + ((m.TRAP_CAVES,) if trap else ()):
        used.update(more)
    if back:                                # the back image: d, e and g are past the section's end, their runs stock's
        tail = bytearray(m.FAR_BYTES_GRAIN if grain else m.FAR_BYTES_LOCK if lock else m.FAR_BYTES_STR if stretch else m.FAR_BYTES)
        for name, (start, end) in dict(m.BACK_CAVES, **((m.GRAIN_CAVES if grain else m.STRETCH_CAVES) if stretch else {})).items():
            used.pop(name, None)
            tail[start - m.FAR:start - m.FAR + len(code[name])] = code[name]
        TAIL = bytes(tail)
        srr = hits = scan = False           # their engines' table entries stay stock's
    for name, (start, end) in sorted(used.items()):
        stock = image[m.off(start):m.off(end)]
        new = code[name] + NOP * ((end - start - len(code[name])) // 2)
        out.append(fw.Patch(7, m.off(start), stock, new, "sampler code, cave " + name))

    def pointer(addr, old, sym, note):
        out.append(fw.Patch(7, m.off(addr), old.to_bytes(4, "big"), syms[sym].to_bytes(4, "big"), note))

    pointer(m.UPDATE_TABLE + 4 * m.TWIN_ENGINE, m.TWIN_UPDATE, "sampler_update", "engine 11 update")
    pointer(m.RENDER_TABLE + 4 * m.TWIN_ENGINE, m.TWIN_RENDER, "sampler_render", "engine 11 render")
    if srr:                                 # the srr image: SY SWARM's code is room, and a track left on it plays nothing
        for addr in (m.SWARM_UPDATE, m.SWARM_RENDER):
            if image.count(addr.to_bytes(4, "big")) != 1:
                raise fw.GuardError("SY SWARM's code at %#x is named more than once" % addr)
        pointer(m.UPDATE_TABLE + 4 * m.SWARM_ENGINE, m.SWARM_UPDATE, "swarm_update", "engine 10 update: nothing")
        pointer(m.RENDER_TABLE + 4 * m.SWARM_ENGINE, m.SWARM_RENDER, "swarm_render", "engine 10 render: nothing")
    if hits:                                # the hits image: SY TOY's and SY BITS's code is room, and a track on either plays nothing
        for engine, update, render in ((m.TOY_ENGINE, m.TOY_UPDATE, m.TOY_RENDER), (m.BITS_ENGINE, m.BITS_UPDATE, m.BITS_RENDER)):
            for table, addr in ((m.UPDATE_TABLE, update), (m.RENDER_TABLE, render)):
                if image.count(addr.to_bytes(4, "big")) != 1 or m.u32(image, table + 4 * engine) != addr:
                    raise fw.GuardError("engine %d's code at %#x is not named once, by its table" % (engine, addr))
            pointer(m.UPDATE_TABLE + 4 * engine, update, "swarm_update", "engine %d update: nothing" % engine)
            pointer(m.RENDER_TABLE + 4 * engine, render, "swarm_render", "engine %d render: nothing" % engine)
    if scan:                                # the scan image: SD BASIC's code is room, and a track on it plays nothing
        for table, addr in ((m.UPDATE_TABLE, m.SDB_UPDATE), (m.RENDER_TABLE, m.SDB_RENDER)):
            if image.count(addr.to_bytes(4, "big")) != 1 or m.u32(image, table + 4 * m.SDB_ENGINE) != addr:
                raise fw.GuardError("engine %d's code at %#x is not named once, by its table" % (m.SDB_ENGINE, addr))
        pointer(m.UPDATE_TABLE + 4 * m.SDB_ENGINE, m.SDB_UPDATE, "swarm_update", "engine 1 update: nothing")
        pointer(m.RENDER_TABLE + 4 * m.SDB_ENGINE, m.SDB_RENDER, "swarm_render", "engine 1 render: nothing")
    if trap:                                # the trap image: CY ALLOY's code is room, and a track on it plays nothing
        lo, hi = m.TRAP_CAVES["al"]
        table = [t + 4 * m.ALLOY_ENGINE for t in (m.UPDATE_TABLE, m.RENDER_TABLE)]
        twin = m.TWIN_ROOM["update and render"]
        named = [m.BASE + k for k in range(0, len(image) - 3, 2) if lo <= m.u32(image, m.BASE + k) < hi]
        if sorted(named) != sorted(table + [a for a in named if twin[0] <= a < twin[1]]) or len(named) != 3:
            raise fw.GuardError("CY ALLOY's code is named other than by its table and the long in Twinshot's room: %s"
                                % [hex(a) for a in named])
        if [m.u32(image, a) for a in table] != [m.ALLOY_UPDATE, m.ALLOY_RENDER]:
            raise fw.GuardError("engine 2's table entries are not CY ALLOY's code")
        pointer(m.UPDATE_TABLE + 4 * m.ALLOY_ENGINE, m.ALLOY_UPDATE, "swarm_update", "engine 2 update: nothing")
        pointer(m.RENDER_TABLE + 4 * m.ALLOY_ENGINE, m.ALLOY_RENDER, "swarm_render", "engine 2 render: nothing")
    if back:                                # the copy, between the start's two calls: jsr far_load ; nop
        out.append(fw.Patch(7, m.off(m.START_CALLS), bytes.fromhex(fw.sx("313de459f85fa891d09dc73e")),
                            b"\x4e\xb9" + syms["far_load"].to_bytes(4, "big") + NOP, "the back image: the far code copied at the start"))
    if timed:                               # the time image: stock starts the timer that is read, and names it nowhere else
        # moveq #29,%d0 ; moveq #3,%d1 ; moveb %d0,0xfc04002d (the timer's clock on) ; movew %d1,TIMER1_MODE
        if image[m.off(m.TIMER1_START) - 10:m.off(m.TIMER1_START) + 6] != bytes.fromhex(fw.sx("53136258fd1c0c7dd6cc135cdeccc685")) + m.TIMER1_MODE.to_bytes(4, "big"):
            raise fw.GuardError("stock does not start its second timer the way it did")
    pointer(m.ISR_VOICE_LOOP_CALL + 2, m.VOICE_LOOP, "timed_hook" if timed else "sampler_hook", "interrupt: voice loop call")
    if stereo:                              # the left's last stage, then the right channels through all four
        if image[m.off(m.ISR_AMP_CALL):m.off(m.ISR_AMP_CALL) + 2] != b"\x4e\xb9":
            raise fw.GuardError("the interrupt does not call its last stage the way it did")
        pointer(m.ISR_AMP_CALL + 2, m.STAGE_AMPS, "timed_amp" if timed else "sampler_amp", "interrupt: last stage call")
    return out, syms


def patched_image(image, rec=False, keep=False, page=False, load=False, bank=False, fade=False, live=False, len_live=False,
                  floor=False, reclock=False, pitch=False, stereo=False, timed=False, twelve=False, auto=False, cross=False, pack=False,
                  stops=False, multi=False, srr=False, soft=False, tail=False, hits=False, trim=False, slim=False, six=False, eight=False, curve=False, peak=False, xknob=False, slice=False, ring=False, allright=False, scan=False, norm=False, back=False, stretch=False, lock=False, scrub=False, slscrub=False, grain=False, spread=False, trap=False, letgo=False, handrec=False):
    """Stock section 7 bytes -> section 7 with the sampler installed (and the back image's code past its end)."""
    ps, syms = patches(image, rec, keep, page, load, bank, fade, live, len_live, floor, reclock, pitch, stereo, timed, twelve, auto, cross, pack,
                       stops, multi, srr, soft, tail, hits, trim, slim, six, eight, curve, peak, xknob, slice, ring, allright, scan, norm, back, stretch, lock, scrub, slscrub, grain, spread, trap, letgo, handrec)
    buf = bytearray(image)
    for p in ps:
        if bytes(buf[p.offset:p.offset + len(p.stock)]) != p.stock:
            raise fw.GuardError("stock bytes differ at %#x" % (m.BASE + p.offset))
        buf[p.offset:p.offset + len(p.new)] = p.new
    return bytes(buf) + TAIL, syms


if __name__ == "__main__":
    import sys
    keep = sys.argv[1:] == ["keep"]
    rec = keep or sys.argv[1:] == ["rec"]
    code, syms = compile_engine(rec, keep)
    for name, (start, end) in sorted(dict(m.CAVES, **(m.REC_CAVES if rec else {})).items()):
        print("cave %s  %#x..%#x  %4d of %4d bytes used" % (name, start, end, len(code[name]), end - start))
    for name, addr in sorted(syms.items(), key=lambda kv: kv[1]):
        print("  %#x  %s" % (addr, name))
