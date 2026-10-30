/* Addresses in section 7 of Syntakt OS 1.41 / 1.42 (SHA-256 daf6451c...).
 * Each is checked against the pinned image by tests/test_audio_map.py. */
#ifndef SAMPLER_H
#define SAMPLER_H

typedef signed char s8;
typedef unsigned char u8;
typedef signed short s16;
typedef unsigned short u16;
typedef signed int s32;
typedef unsigned int u32;

#define N_TRACKS 8
#define BLOCK 32
#define ENGINE_ID 11                       /* Twinshot's place in the engine tables */

#define VOICE(i) ((s32 *)(0x80000000u + 1800u * (i)))
#define PARAMS_STRIDE 142
#define PARAM_TYPE 62                      /* machine type byte in a track's parameters */
#define PARAM_KNOBS 28                     /* slot s is the word at +28 + 2*s */
#define MACHINE_TYPE 44                    /* the UI's number for this machine */
#define OUT_BUF 0x80003840u
#define HOST_TRACK_LONG ((s32 *)0x80008188) /* one long per track, read by the filter stage */
#define HOST_TRACK_FLAGS ((u8 *)0x800081a8) /* one bit per track, read by the amp stage */
#define MIRROR_FROM 80                     /* track parameters the later stages read: */
#define MIRROR_TO 132                      /* slot 26 (OVER) and the filter and amp pages */
#define SCRATCH_L ((s32 *)0x80008c60)      /* Twinshot's own scratch buffers */
#define SCRATCH_R ((s32 *)0x80008d84)

struct slot {
    u32 frames;
    const s16 *data;
};
#define SLOT ((const struct slot *)0x4404f754)
#define N_SLOTS 64
/* Position is 20.12 in a signed long. Stock clamps a slot to 0x7ffff frames;
 * we stop 255 frames earlier so that position plus the largest pitch increment
 * (under 64 frames per frame) cannot overflow before the end is noticed. */
#define MAX_FRAMES 0x7ff00
#define MAX_EDGES 40        /* slot seams and loop turns one voice may take in a block */

/* Right channels wait here until every voice has rendered. Free SDRAM just
 * above BSS: never zeroed, so it is only read in a block that wrote it.
 * (Seven of them up to the save image, the last track having no next one; eight with ONETRACK.) */
#define STASH(i) ((s32 *)(0x44050000u + 128u * (i)))

/* stock routines we call */
#define stock_pitch ((void (*)(s32 pmod, s32 tune, void *player))0x40006704)   /* sets player+24 */
#define stock_env ((void (*)(s32 *voice))0x40003d42)
#define stock_amp ((void (*)(s32 *buf, s32 *voice))0x400045a0)
#define stock_mix ((void (*)(s32 *a, s32 *b, s32 *out, const s32 *idx, s32 *voice))0x400049f4)
#define DECAY_TABLE ((const s32 *)0x4003ec38)

/* voice fields the stock code owns */
#define V_ENGINE 0
#define V_GAIN_A 2          /* +8   target gain of buffer A */
#define V_GAIN_B 3          /* +12 */
#define V_CUR_A 6           /* +24  current gain, ramped by stock_mix */
#define V_CUR_B 7           /* +28 */
#define V_TRIG 13           /* +52  trig bit of this block */
#define V_START 14          /* +56  the note starts in this block */
#define V_ENV_CUR 245       /* +980 amp level, ramped by stock_amp */
#define V_ENV_A 250         /* +1000 */
#define V_HOLD 251          /* +1004 hidden slot 24, copied in by the voice loop */
#define V_ENV_DECAY 252     /* +1008 */

/* knob slots: word at p + 2 * slot, 8.8 */
#define K_TUNE 18
#define K_SAMPLE 19         /* 64..127 forward, 63..0 reversed: slot, or stereo sample (PAIRS) */
#define K_START 20
#define K_LENGTH 21
#define K_LOOP 22           /* 0 one-shot, 1 loop, 2 ping-pong (3 too): the low two bits */
#define K_MODE 23
#define K_REC 24            /* the "reclock" image: a step's own REC, see below. Stock: the envelope's hold flag */
#define K_DECAY 25

#define LOOP_PLAY 3
/* MODE, low two bits: 0 mono, 1 stereo, and on the recorder image 2 and 3 record. */
#define MODE_KIND 3
#define MODE_STEREO 1       /* slot n is left, slot n+1 is right, right goes to the next track */
#define MODE_REC 2          /* recorder image only: record into the slot, +1 = from the external input */
#ifdef PAGE
/* The page image: MODE's value is three switches, each with a knob of its own
 * (engine/recpage.c): 1 stereo, 2 in record, 4 record from the external input.
 * Chained slots are gone from it. The parameter is the same one, so each of the
 * three can be locked to a step as MODE always could. */
#define MODE_EXT 4
#define MODE_CHAIN 0
#define REC_EXT(m) ((m) & MODE_EXT)
#else
#define MODE_CHAIN 4        /* consecutive slots play as one long sample */
#define REC_EXT(m) ((m) & 1)
#endif
#define STEREO(m) (((m) & MODE_KIND) == MODE_STEREO)
#ifdef RECLOCK
/* The reclock image: a step's REC is a lock of its own and not a lock of MODE, which locked the
 * stereo switch and the source with it (on request
 * ). The unit keeps a lock for each of 71 knob slots of a track whether
 * a knob stands for the slot or not, and applies whatever a step has. Slot 24 has no knob on a
 * digital track: the voice loop copies it into the voice's "hold" flag, which our update clears
 * as Twinshot's does. A step's REC is a lock there at one of two values that nothing else puts
 * in the slot, the mark in the high byte and the low byte in the middle so the main CPU's
 * smoothing cannot carry it to the next number. With any other value there the track's own REC
 * stands: the bit of MODE, as before. */
#define REC_LOCK_ON 0x52u
#define REC_LOCK_OFF 0x29u
#define REC_WORD(mark) ((s32)(((mark) << 8) | 0x80))
#define REC_ON(m, r) ((r) == REC_LOCK_ON || ((r) != REC_LOCK_OFF && ((m) & MODE_REC)))
#else
#define REC_ON(m, r) ((m) & MODE_REC)
#endif
#ifdef HQ
/* The pitch image: a frame between two of the sample's is worked out from 16 of them, not 2.
 * The on request
 * . That sound is the line between two frames: played two octaves
 * down, a 6 kHz part of a sample came out with everything else it made only 30 dB under it.
 *
 * The frame at i + f/4096 is the sum of frames i - 7 to i + 8, each times a number from a table
 * of a windowed sinc (tools/sinctable.py): the row for the top 5 bits of f and the next row,
 * blended by the low 7. Every row adds up to the same, so a steady level stays put. On a frame
 * of the sample itself (f = 0) nothing is summed: it is that frame, as before, so a sample at
 * its own pitch plays bit for bit as it did. Past either end of the slot the end frame stands
 * in. The sum is held to 30 bits before it is doubled: a sinc can pass the frames it joins.
 *
 * Within reach of an end the sixteen are not all in the slot. The image's first build put them
 * together for every frame it made there, at more than twice the work of a frame elsewhere, and
 * a note far below its pitch stays there for blocks: on the unit, "its better but when pitchrf
 * low i still hear some clciks and pops". Now a note's start writes the frames around both ends
 * of its slot out once, the end frame standing in, 45 a side, into 256 bytes a voice of the same
 * free memory (HQ_PADS), and a frame near an end is summed from there like any other.
 *
 * The image stores rows 0 to 16; row 32 - r is row r backwards. The engine keeps all 33 in free
 * SDRAM under the takes.
 *
 * The first two builds made the table when a long beside it was not the one this table is built
 * with, and believed it otherwise. That memory is cleared by nothing, and memory that has been
 * without power for a moment comes back mostly as it was: the long can be whole and the table
 * not. On the unit, after it had been restarted: "they sound all fucked up, and there's a lot of
 * noise", with TUNE moved. So what says the table is made is now in memory stock clears at every
 * start: the long at + 80 of voice 0's sampler state, which stock's voice reset sets to 0 at boot
 * and whenever track 1's machine changes. The table is made on the first interrupt after either. */
#define HQ_TAPS 16
#define HQ_BEFORE 7
#define HQ_HALF 16          /* the last stored row */
#define HQ_MADE (*(volatile u32 *)0x80000700)   /* voice 0's state + 80: HQ_MAGIC once this start's table is made */
#define HQ_TABLE ((s16 *)0x44060004)
#define HQ_TOP 0x3fffffff
#define HQ_PADS ((s16 *)0x44060800)     /* a voice's: 128 words on from the one before */
#define HQ_PAD_END 22       /* words from the frames around a slot's start to those around its end */
#define HQ_PAD_SIDE 45      /* and from the left side's to the right's */
#define HQ_REACH (HQ_TAPS - HQ_BEFORE - 1)  /* frames past frame i in the sum: 8 */
extern const s16 hq_rows[];
#ifdef QUICK
/* The stereo image's second build: the same frames for less work. On the unit, eight stereo
 * tracks: "it works fine when they are all pitched normlly but when i pitch them it causes
 * major distortion". A pitched stereo voice summed sixteen frames twice a frame, each sum 32
 * multiplies and 121 instructions, inside a loop that looked after the walls and the fades at
 * every frame: with eight of them the interrupt was 1.37 of stock's heaviest, and no time left.
 *
 * Two things, and what comes out is what came out, bit for bit (tests/test_quick.py):
 *   - The sums are made in the multiply and accumulate unit, the way stock makes its own: a
 *     frame at the top of a long times a number of the table at the top of a long, less one
 *     bit, is their product whole with nothing rounded away, and a sum of sixteen is under 32
 *     bits at every step (the table's rows add up to under two). Both channels share the
 *     numbers. The table is 33 rows of longs for that (HQ_LONGS), made at every start as the
 *     rows of words were.
 *   - A run of frames with nothing to look after is made in one call (engine/stub.S, hq_run):
 *     up to the frame whose step would reach a wall or the place a fade out begins. The frames
 *     of a fade, and the one at a wall, are made one at a time as before, by the same routine. */
#define HQ_LONGS ((s32 *)0x44061000)        /* past the voices' frames around their slots' ends */
#define HQ_COEF(v) ((s32)(v) << 15)
#endif
#endif
#ifdef FLOOR
/* The floor image: LEN stops at 3. Below that a loop closes to a buzz (on request
 *
 *
 * ). The knob's range says so on the main CPU; this is for an LFO, a lock or a pattern
 * saved before, which can still ask for less. */
#define LEN_MIN (3u << 8)
#endif
/* SAMPLE counts single slots in mono and stereo samples otherwise: number n is
 * slots 2n and 2n + 1, so no value of the knob lands on a right channel. A take
 * is a stereo sample. Without the recorder its two modes play as mono. */
#ifdef AUTO
/* The mode image: a sample is what it is. On request
 *
 *
 *
 * 
 *
 * So MODE's lowest bit no longer says how a track plays. SAMPLE always counts the 32 samples,
 * number n in slots 2n and 2n + 1, and a sample is stereo when its second slot holds exactly as
 * many frames as its first, mono when it does not: a mono sample plays its first slot to both
 * sides at half the work, and its second slot is not played. The bit now says what a take is:
 * with it a take fills both slots, without it the take is the two sides of the source added and
 * halved (engine/recfeed.c) in the first slot, and the second is left with one frame, which is
 * kept on the drive like any take, so that what was in that slot before cannot come back as a
 * right channel. The knob is on the sampling page (engine/recpage.c) and is the track's alone.
 *
 * A note is in one slot and has been since the page image took chained slots away; here the code
 * that walked from slot to slot goes too, for room. */
#define PAIRS(m) 1
#define TAKE_ONE 1          /* frames a mono take leaves in its second slot */
#ifdef PACK
/* The pack image: mono samples in single slots at the back. The maintainer, 2026-10-12, told that a mono
 * sample leaves its second slot unused: "the stereo samples would fill up the first part of the bank
 * from 1 to whatever is available, and the mono samples would just get packed in the back of the
 * bank. That way, if I wanted to do 80/20 stereo versus mono samples, I could do it that much or do
 * 50/50. I don't need to have a set amount".
 *
 * SAMPLE's 64 values are 64 places. 0..31 are the 32 stereo samples as they were, number n in slots
 * 2n and 2n + 1. 32..63 are the slots 32..63 by their own number, each a mono sample whatever the
 * slot after it holds. So the knob's number says which kind a place is, and nothing has to be found
 * out about what two slots hold: two mono takes of a bar are one length, and length could not say
 * that they are no pair. Stereo samples used from 1 up and single slots from 64 down meet where they
 * meet: 32 and none, 24 and 16, 16 and 32.
 *
 * A take lands in the place it is sent to. In a stereo place it is what MODE says, as above. In a
 * single slot it is the two sides of the ring's block added and halved, whatever MODE says, and
 * nothing of the slot after it is written: not its frames, not its line of the table, not its mark. */
#define SINGLES (N_SLOTS / 2)   /* the first place that is a single slot */
#define TAKE_SINGLE 0x80        /* in a voice's `link` while it records: the take is a single slot's (a byte below nothing: engine/stub.S) */
#endif
#elif defined(RECORDER)
#define PAIRS(m) (((m) & MODE_KIND) != 0)
#else
#define PAIRS(m) STEREO(m)
#endif

/* The recorder (-DRECORDER, engine/recfeed.c on the main CPU). While a track's
 * MODE says record, the main CPU leaves one block of 32 stereo frames per mixer
 * call in the half of the shared window that only the boot sample loader uses,
 * in a ring of 8 blocks, then counts seq up. The audio CPU takes every block it
 * has not seen. Address 0x800 here, 0x10000800 on the main CPU. */
#define MB_BLOCKS 8
struct mailbox {
    u16 seq;                /* last block written, written after its samples */
    u16 pad;
    u32 rnd;                /* the main CPU's random number for dither, kept here between blocks */
    u16 pad2[4];
    s16 ring[MB_BLOCKS][2 * BLOCK];     /* left, right, left, ... */
};
#define MB_AUDIO ((const volatile struct mailbox *)0x800)
#define MB_MAIN ((volatile struct mailbox *)0x10000800)
/* A take goes to free SDRAM, one fixed buffer per slot, and the slot table is
 * pointed at it: slot k left, slot k + 1 right. Lost at power off. */
#define REC_MAX 0x78000     /* frames: 10.24 s */
#define REC_STRIDE (2 * REC_MAX)    /* bytes from one slot's buffer to the next */
#define REC_BUF(k) ((s16 *)(0x44080000u + REC_STRIDE * (k)))
/* Keeping a take (-DKEEP, engine/keeptakes.c on the main CPU). When a project
 * is saved the main CPU asks for each take that is not on the +Drive yet, 512
 * bytes at a time, through the window just past the recorder's ring, and writes
 * it to the take's slots. Each side writes its own fields only, and the word
 * that says "done" last. Address 0xc10 here, 0x10000c10 on the main CPU.
 *
 * The window is never touched a byte at a time: stock uses words and longs on it
 * from the main CPU and longs only from the audio CPU, and a first build that
 * moved the take across in bytes kept takes that came back distorted
 * (docs/FINDINGS.md). So the audio CPU writes longs, the main CPU words and longs. */
struct keepbox {
    u16 req;                /* main CPU: changed when the rest of a request is in place */
    u16 slot;               /* main CPU */
    u32 off;                /* main CPU: byte offset in the take, or KEEP_DONE: the slot is on the drive now */
    u32 ack;                /* audio CPU: the request it has answered, written last */
    u32 frames;             /* audio CPU: the take's length; 0 when the slot holds no take that has yet to be kept */
    u32 data[128];          /* audio CPU: 512 bytes of the take from off on, zeros past its end */
};
#define KEEP_AUDIO ((volatile struct keepbox *)0xc10)
#define KEEP_MAIN ((volatile struct keepbox *)0x10000c10)
#define KEEP_DONE 0xffffffffu
/* Loading (-DLOAD, the load half of engine/keeptakes.c): the other way through
 * the same box, for a slot the drive should be heard from again. With KEEP_PUT in
 * slot the main CPU has put up to 512 bytes of the slot's samples in data, for
 * the slot's take buffer at off; with KEEP_DONE as off, data[0] is the length in
 * frames, the slot plays the buffer from then on, and it counts as kept. The
 * audio CPU answers with ack alone. */
#define KEEP_PUT 0x8000u
/* With BIGPUT (the bank image, which loads all 64 slots at once) a put can carry three sectors:
 * KEEP_BIG in slot too, and the 1024 bytes after data's 512 are in the recorder's ring, which the
 * main CPU keeps its feed out of meanwhile (BANK_BUSY). */
#define KEEP_BIG 0x4000u
/* Per slot, in free SDRAM under the takes: the take's length with this mark once
 * it is on the drive. Never zeroed, so a new take clears its own two, and it only
 * counts for a slot the table points at its take buffer. */
#define KEEP_MARK 0x4b454550u
#define KEPT ((u32 *)0x4407ff00)

/* The sampling page (-DPAGE, engine/recpage.c on the main CPU). Record and its
 * source are bits of MODE there and need nothing here. What MODE has no room for
 * is where a take goes: the page keeps a destination for each of the eight
 * tracks in the window just past the keep box, and the audio CPU reads it when a
 * take starts. Address 0xe20 here, 0x10000e20 on the main CPU.
 *
 * That part of the window holds whatever the boot loader's last chunk left in it
 * until the page first writes there, so the box is not believed before both marks
 * read right. Words and longs only, as everywhere in the window. */
struct recbox {
    u32 mark;               /* main CPU: REC_MARK, written after the rest */
    u32 mark2;              /* main CPU: ~REC_MARK */
    u16 dest[8];            /* main CPU: track t's takes go to this stereo sample, from 0, or DEST_SMPL: the one SMPL is on. The pack image: this place, 0..63 */
};
#define REC_AUDIO ((const volatile struct recbox *)0xe20)
#define REC_MAIN ((volatile struct recbox *)0x10000e20)
#define REC_MARK 0x52454321u
#define DEST_SMPL 0xffffu

/* Three sample banks (-DBANKS, engine/banks.c on the main CPU; the audio CPU knows
 * nothing of it). The +Drive holds three sets of 64 slots one after the other, the
 * first where the samples always were, and every access to the first set's sectors
 * is moved to the set that is loaded. Which one that is, and which each project
 * asks for, is kept in one sector of ours after the third set.
 *
 * The numbers below are in main CPU memory, at the start of the run of code
 * engine/banks.c lives in: the bank that is loaded (past 2: not read from the
 * drive yet), the bank the project in memory is to be saved with, and a flag. */
#define BANKS_N 3u
#define BANK_FIRST 8192u                    /* the first sample sector */
#define BANK_SECTORS (64u * 2048u)          /* a set: 64 slots of 1 MB */
#define BANK_MARK_SECTOR (BANK_FIRST + BANKS_N * BANK_SECTORS)   /* 401,408: at 196 MB, in the part nothing uses */
#define BANK_MAGIC 0x42414e4bu              /* BANK */
struct bankmark {
    u32 magic, magic2;                      /* BANK_MAGIC and its complement */
    u32 now;                                /* the bank that is loaded, and that the boot loads */
    u8 of[128];                             /* the bank of each project, 0..2; anything else: never saved here, bank 0 */
};
#define BANK_NOW (*(volatile u32 *)0x40196aba)
#define BANK_WANT (*(volatile u32 *)0x40196abe)
#ifdef PHONE
/* The phone image (engine/phone.c): the slots the phone says it changed, two longs, bit n of word n / 32
 * for slot n (0 to 63). Alone at the start of the phone's run (mainmap.CAVE_PHONE); the loader reads it. */
#define PHONE_MASK ((volatile u32 *)0x40126f08)
#endif
#define BANK_BUSY (*(volatile u32 *)0x40196ac2)    /* not 0 while slots are being loaded: the ring carries samples */

#ifdef METER
/* The meter image (main CPU only; the audio CPU's code is the pitch image's).
 *
 * More sources. The the maintainer's report.
 * The source is a number in MODE's value now, where "from the external input" was a
 * switch: bits 2..6, so a value saved by an earlier build still means what it did
 * (0 the main mix, 1 the external input). The audio CPU reads MODE's two low bits and
 * nothing above them. Numbers 2..13 are tracks 1..12, which is also where a track is
 * in the main CPU's frame of 20 channels; a track is one channel and goes to both
 * sides of a take.
 *
 * A level meter. The the maintainer's report, "with just a line
 * tracking the volume, like Electron does on their compressor UI", "should be on the
 * bottom line". The feed (engine/recfeed.c) keeps the level of the source the page is
 * showing and asks for the page to be drawn again; the page (engine/recpage.c) draws
 * it as a bar on the two lowest rows of the screen. The four numbers below are in main
 * CPU memory, at the start of the run of code the feed's new part lives in, as the
 * bank image's are in its own. */
#define MODE_SRC 0x7cu
#define SRC_OF(m) (((m) & MODE_SRC) >> 2)
#define SRC_MAIN 0u
#define SRC_EXT 1u
#define SRC_T1 2u
#define SRC_FX 14u                          /* the FX track's return */
#define SRC_SENDS 15u                       /* delay and reverb */
#define SRC_TOP SRC_SENDS
#define METER_PAGE (*(void *volatile *)0x40088510)  /* the SYN page object once it has drawn our page; 0 until then */
#define METER_SRC (*(volatile u32 *)0x40088514)     /* page: the source to watch */
#define METER_QUIET (*(volatile u32 *)0x40088518)   /* page: 0 at every drawing. Feed: blocks since */
#define METER_LEVEL (*(volatile u32 *)0x4008851c)   /* feed: the level, 0..32767, the top 16 bits of a sample's size */
#define METER_EVERY 96u                     /* blocks between drawings: 64 ms */
#define METER_STOP (3u * METER_EVERY)       /* not drawn for this long: the page is not on show, and nothing is asked */
#define METER_FALL 10                       /* the level loses a 1024th of itself a block: 13 dB a second */
/* The bar: 104 dots for 62 dB, ten to every halving. */
#define BAR_X 21
#define BAR_W 104
#endif

#ifdef GAIN
/* The gain image (main CPU only; the sound engine is the stereo image's with the sum of twelve).
 * The on request, and earlier of where: "rec gain
 * and threshold may as well just go on the two knobs you were using for the nunber read out on
 * the sampling page". So: the lower row's second place, knob F.
 *
 * A track's record gain, 0 to 24 dB a decibel a step. The feed (engine/recfeed.c) multiplies the
 * source by it before the 32 bits are made 16, so a quiet source is brought up out of the bits
 * a take would have thrown away, and not out of its own noise afterwards. Past what a take can
 * hold it stops there, as the feed always has. At 0 the feed is what it was, bit for bit.
 * The meter shows the level with the gain on: it is what the take will hold.
 *
 * It is the page's own, like DEST: a number a track in main CPU memory after the meter's four,
 * 0 at every start, not saved with a project and not to be locked to a step. The page writes
 * it and says which is on show; the feed reads the recording track's. */
#define GAIN_TOP 24u
#define METER_GAIN (*(volatile u32 *)0x40088520)    /* page: the gain of the track it shows, for the meter */
#define REC_GAINS ((volatile u8 *)0x40088524)       /* a track's record gain in decibels: eight bytes */
#endif

#ifdef SAVE
/* The save image (main CPU only): takes are written to the +Drive from the sampling page,
 * without the project. The the maintainer's report, and of what it
 * is to write: "SAVE on the page write just the takes".
 *
 * The drive may be written from a job. Stock has a runner of jobs with a worker of its own, the
 * one SAVE PROJECT's job runs in, and a job is started with a name and two function objects: what
 * to do, and what to call when it is done (engine/keeptakes.c). Ours does what a project save's
 * second half does, keep_takes, and nothing of its first.
 *
 * One number says how it is going, in main CPU memory at the start of the run of code
 * engine/keeptakes.c lives in. The fifth place of the sampling page shows it and a turn to the
 * right starts a save (engine/recpage.c). */
#define SAVE_STATE (*(volatile u32 *)0x401259fa)
#define SAVE_IDLE 0u
#define SAVE_BUSY 1u
#define SAVE_DONE 2u
#define SAVE_FAIL 3u
#endif

#ifdef ONCE
/* The once image (main CPU only). On request
 *
 * 
 *
 * REC has a third setting, ONCE. On a step it is a lock on slot 24 at ONCE_WORD: the high byte is
 * REC_LOCK_ON's, so the audio CPU, the feed and recword.S take it for a step locked on and none of
 * them is touched. Where the sequencer plays the step (engine/once.S) the word in the pattern becomes
 * ONCE_SPENT once the event has its copy: no mark, so on the next pass the track's own REC decides.
 * The main task then takes the spent lock off with stock's own routine (engine/onceclean.c), which is what
 * a lock removed by hand goes through.
 *
 * The track's own REC at ONCE is a byte a track in main CPU memory, at the start of the run of code
 * engine/once.S lives in: 0 at every start, not saved, the bit of MODE off. The next step the
 * sequencer plays on the track gets (slot 24, on) added to its event's locks, so it records as a
 * step locked on does, to the track's next event; and the byte is cleared there. */
#define ONCE_WORD 0x52c0u
#define ONCE_SPENT 0x6bc0u
#define ONCE_ARM ((volatile u8 *)0x40088820)        /* eight bytes: a track's own REC is ONCE */
#define ONCE_DIRTY ((volatile u8 *)0x40088828)      /* eight more: a spent lock is in the track's table */
#endif

#ifdef SOLOKNOB
/* The soloknob image (main CPU only). On request
 *
 *
 *
 *
 * 
 *
 * A solo is a bit a track in one long of ours, in main CPU memory at the start of the run the solo
 * image's code was in (that code is not built here: the purple keys are stock's pattern mutes
 * again). 0 in the image, so off at every start; not saved. Knob E of the sampling page sets and
 * clears the track's bit (engine/recpage.c). While any bit is set the mixer link and the analog
 * mute silence every track whose bit is clear, and no mute counts, global or the pattern's
 * (engine/mixlink.c, engine/amute.c). Stock's own solo word (project settings + 40, 0x8000304c
 * a block) is not written and no longer read by ours. */
#define SOLO_WORD (*(volatile u32 *)0x400a2928)
#endif

#ifdef XFADE
/* The xfade image (main CPU only). On request
 *  Asked which track that is:
 * "Whichever track the knib is in should work as the current crossfade". And where: "the
 * cordsaffe and solos hould be on the second page".
 *
 * A number a sampler track, 0 to 127, in main CPU memory after the solos' long: 0 in the image,
 * so 0 at every start; not saved, not to be locked. Knob G of the sampling page turns the
 * track's (engine/recpage.c), where MODE was. Every other one of the twelve tracks is turned
 * down by the largest number among the other tracks' x: the mixer is shown its volume word
 * times (127 - x) / 127 (engine/mixlink.c), and an analog voice's two level words are made that
 * squared of what they were (engine/amute.c), which is what stock makes of such a volume. At
 * 127 both are 0. A track a mute or a solo silences is silent whatever these say.
 *
 * MODE has no knob on this image, so a take at a stereo place is always stereo: MODE's lowest
 * bit is set in the block the audio CPU is sent and the feed reads, every block, on a sampler
 * track (engine/recword.S). */
#define XFADES ((volatile u8 *)0x400a292c)          /* eight bytes */
#ifdef SLOCK
/* The slock image: a sampler track's solo can be locked to a step. The lock is on knob slot 17, which no
 * record of a machine the audio CPU runs names, at one of two marks in its high byte, as REC's is on slot
 * 24 (REC_WORD): SOLO_LOCK_ON, the step solos its track; SOLO_LOCK_OFF, it does not; anything else there
 * and the track's own solo decides. The marks are read where a trig's locks are written, WORDS_BACK bytes
 * before the block the mixer is given: there slot 17's word is the machine's type.
 * SOLO_NOW: this block's solos, a step's own among them. The analog mute works them out, the mixer link,
 * which runs after it, goes by them. */
#define K_SOLO 17
#define SOLO_LOCK_ON 0x35u
#define SOLO_LOCK_OFF 0x1au
#define WORDS_BACK 0x4198
#define SOLO_NOW (*(volatile u32 *)0x400a2938)
#endif
#ifdef SOLOEND
/* The soloend image: a bit a track whose step's solo lock is over, first in the hits' run (engine/hits.c, SOLOEND;
 * mainmap.SOLO_GONE). Only tracks 1 to 8 have one. */
#define SOLO_GONE (*(volatile u32 *)SOLOEND_AT)
#endif
#ifdef ALOCK
/* The alock image: an analog track's solo can be locked to a step too. Its lock is on knob slot 26: the
 * last of the ten words that are a track's machine (17 to 26), which no analog machine has a knob on
 * (tools/params.py: theirs are 17 to 24, and 25 on one). The same two marks. Not believed on a track
 * that holds no analog machine (TRACK_TYPES, stock's byte a track): there the slot may be a knob. */
#define K_SOLO_ANALOG 26
#define TRACK_TYPES ((const volatile u8 *)0x80002f50)
#define ANALOG_MACHINE(type) ((u32)(type) - 8u < 26u || (u32)(type) - 39u < 5u)     /* 8 to 33 and 39 to 43: not 35, the MIDI machine */
#endif
#ifdef APAGE        /* the apage image: twelve bytes, an analog track's after the eight (engine/recpage.c, APAGE) */
#define XFADE_ANY (((volatile u32 *)0x400a292c)[0] | ((volatile u32 *)0x400a292c)[1] | ((volatile u32 *)0x400a292c)[2])
#else
#define XFADE_ANY (((volatile u32 *)0x400a292c)[0] | ((volatile u32 *)0x400a292c)[1])
#endif
#define XFADE_TOP 127u
/* A share of XFADE_TOP, and of its square, as the crossfades take them. The nodiv image (-DNODIV): without the CPU's divide
 * (about 35 cycles; about 20 of them a block with a crossfade up), exactly: a first quotient from p / 128 (1 + 1/128 +
 * 1/128^2 + 1/128^3), which is never more than p / 127, then up while what is left is 127 or more (twice at most for p
 * under 2^30); p / 127^2 is the quotient of the quotient. tests/test_nodiv.py holds it against the divide. */
#ifdef NODIV
static inline __attribute__((always_inline)) u32 div127(u32 p)
{
    u32 q = (p + (p >> 7) + (p >> 14) + (p >> 21)) >> 7, r = p - q * 127u;

    while (r >= 127u) {
        q++;
        r -= 127u;
    }
    return q;
}
#define BY_TOP(p) div127(p)
#define BY_TOP2(p) div127(div127(p))
#else
#define BY_TOP(p) ((p) / XFADE_TOP)
#define BY_TOP2(p) ((p) / (XFADE_TOP * XFADE_TOP))
#endif
#endif

#ifdef ONETRACK
/* One-track stereo (the stereo image, both CPUs). On request
 * : a stereo sample on one track, eight at once where a pair of tracks gave four,
 * and nothing given up in the sound. docs/STEREO.md, "One-track stereo".
 *
 * Audio CPU (engine/sampler.c). A stereo note's right channel no longer takes the next track's
 * buffer. It waits in STASH until stock's four stages have done the eight left buffers, then
 * goes through the same four routines itself, with the track's own knobs and trigs:
 *   - the first stage's state is ramps made from the knobs, and the last's is a level that
 *     follows the trigs: neither hears the sound. The right channel starts each block from a
 *     copy of what the left started from (R_GAIN, R_AMP), and keeps nothing of its own;
 *   - the second and third (two filters) remember the sound. Theirs is kept apart: before the
 *     right channels are done, stock's memory for the eight tracks is exchanged with a copy of
 *     its own shape in free memory (SHADOW), and exchanged back after. A track's right channel
 *     starts from the left's memory in the block it comes on (rlive), so nothing jumps there;
 *   - the third leaves two numbers behind (LEFTOVER) that three of its eight types take as
 *     they find them, from whichever track was done before. A right channel is handed the two
 *     its left was.
 * The first two stages do all eight tracks a call, the last two a track. Only the tracks of
 * the mask are done by those, and only they are sent.
 *
 * Across. Nothing new is asked of the transfer stock makes: the right channels are written to
 * the window by the audio CPU and read from it by the main CPU, a long at a time, in the two
 * stretches of it nothing uses (0x5b0 to 0x800, and from the end of our boxes to 0x1000). A
 * track's 32 frames are two halves of 16 (RW_HALF), since a whole one does not fit eight
 * times. One long says which tracks have one this block, and is not believed unless its two
 * halves agree (RW_WORD): that part of the window has never been tried as shared memory.
 *
 * Main CPU (engine/rightfill.c). The mixer makes its left and right sums in separate passes,
 * each handed the eight track buffers. The right-hand passes are pointed at a second set
 * (RSET): a track's right channel from the window, or a copy of its left when it has none.
 * Pan is balance for a stereo track, and its sends are stereo. */
#define R_MASK (*(volatile u32 *)0x44050400)    /* tracks with a right channel this block: made after the voice loop */
#define R_GAIN ((u32 *)0x44050410)              /* the first stage's state as the left found it */
#define R_AMP ((u32 *)0x440504b0)               /* the last stage's */
#define GAIN_STATE ((u32 *)0x800083b0)
#define GAIN_LONGS 40
#define AMP_STATE ((u32 *)0x800049e0)           /* three longs a track */
#define AMP_LONGS 24
/* stock's memory of the two filters: flags, types and one sum a track; then coefficients, levels,
 * the first filter's two sums, one more number; then the second filter's two sums a track */
#define FILT_A ((u32 *)0x80008550)
#define FILT_A_LONGS 20
#define FILT_B ((u32 *)0x80008740)
#define FILT_B_LONGS 112
#define FILT_C ((u32 *)0x80008920)
#define FILT_C_LONGS 16
#define SHADOW(a) ((u32 *)((u32)(a) + 0xc4048000u))     /* 0x8000xxxx -> 0x4405xxxx: 0x44050550 to 0x44050960 */
#define LEFTOVER ((u32 *)0x80008918)
#define stock_gain ((void (*)(s32 *out, u8 *params))0x4000112c)
#define stock_drive ((void (*)(s32 *out, u8 *params, u32 trig))0x40002320)
#define stock_filter ((void (*)(u8 *p82, s32 *buf, s32 host, u32 track, u32 trig, s32 reset))0x400019d6)
#define stock_amps ((void (*)(s32 *out, u8 *params, u32 trig, u32 release, u32 flags))0x4000168e)
#define stock_amp1 ((void (*)(s32 *buf, u32 *state, u8 *p106, u32 trig, u32 release, u32 track, u32 flag))0x40001476)
#define RW_HEAD_AUDIO ((volatile u32 *)0x5b0)
#define RW_HEAD_MAIN ((volatile u32 *)0x100005b0)
#define RW_WORD(mask) (0x52570000u | ((~(u32)(mask) & 0xffu) << 8) | ((mask) & 0xffu))
/* half h of 16: nine in the first stretch, seven in the second. Track t has halves 2t and 2t + 1. */
#define RW_HALF(window, h) ((volatile u32 *)((window) + ((h) < 9 ? 0x5c0u + 64u * (h) : 0xe40u + 64u * ((h) - 9))))
/* The second set of buffers, in main CPU memory nothing names: between the end of the program's
 * data (0x45566490) and the effects' own memory (0x45570000, which the code names 0x08000000
 * higher). Eight tracks, then one side of the delay's and the reverb's return, as stock has
 * them after its own eight. Written every block before it is read. */
#define RSET ((s32 *)0x4556a000)
void sampler_amp(s32 *out, u8 *params, u32 trig, u32 release, u32 flags);   /* replaces the interrupt's call of the last stage */
#endif

#ifdef LEAN
/* The stereo image's third build: the same sound for less of a block. The unit, through the time
 * image, 2026-10-11: eight stereo samples at their own pitch 72 hundredths of a block, the same
 * pitched 99 and "peaks ovewr a 100 at times", seven SY SWARMs and a sampler 81. An instruction
 * of ours costs more time than one of SWARM's, so matching stock's heaviest by count was not
 * matching it. What is done here changes no frame:
 *   - a voice's level and gain, which went through two of stock's routines a channel (four
 *     passes over a stereo note's block, the second of them adding a second layer that is
 *     nothing), are one pass for both channels (engine/stub.S, voice_out);
 *   - the right channels' copies, to the window and to and from the copy of stock's filter
 *     memory, move more longs a turn (longs, send, swap there).
 * In Twinshot's other run, with the time image's routine when that is built. */
void voice_out(s32 *voice, s32 *out, s32 *right);
/* With TWELVE too (the time12 image, for the maintainer to hear and to read beside the other): a frame
 * between two is summed from twelve frames, not sixteen. The table keeps its shape with a sinc of
 * twelve in its middle twelve places (tools/sinctable.py, rows12), and the sums leave the outer
 * two frames at each end out (engine/stub.S, HQ_SKIP). Less work for a pitched note, and 1 to 5
 * dB less clean: docs/FINDINGS.md, "The interrupt made shorter". */
#endif

#ifdef XFADE
/* The cross image: a loop's end blended into its start, where the fade image dipped. The maintainer, 2026-10-12:
 * "True crossfade at the loop seam. In place of the 4 ms dip. The loop's end blends into its start."
 *
 * A blend needs something to blend with that leads to the place the next pass begins, and a loop that
 * keeps its length has only what lies outside it:
 *   - the XF_W frames before the start, when there are that many (STRT up from 0). The pass's last XF_W
 *     frames go down as those come up, so the pass ends on the very frame the next begins after;
 *   - or else the XF_W frames after the end, when there are (LEN down from the top). The seam is then
 *     XF_W frames later on both sides: the pass runs on past its end as the frames after the start come
 *     up under it, and the next pass begins XF_W frames in. The loop is as long as it was;
 *   - a loop of the whole sample has neither, and keeps the dip.
 * Played backwards the same, the other way round. A ping-pong has no seam and a one-shot no next pass.
 *
 * Two sums a frame for the length of a blend would be twice the work in the blocks every loop that
 * was started together is in its seam together, and the meter has no such room (pitched, eight stereo
 * tracks: 85 of 100). So the blended frames are made of the sample's own, before it is pitched, and
 * written out ahead: XF_N frames a voice in free memory, XF_STEP of them a block (xstep, and bake in
 * engine/stub.S) from the block after the note starts or the seam's two places last moved, 44 blocks
 * in all, and none in a block a fade is on in, which is work enough. A pass that comes within reach
 * of its wall with all of them written (xuse 1, then 2 inside) is played from there by the same
 * routine that plays a sample: the note is pointed at them, with its place and its wall counted from
 * the first of them, until its wrap points it back at its slot. That wrap is no cut: no fade before
 * or after. A seam reached sooner dips as it did. Inside its blend a pass is left alone by the knobs.
 *
 * The frames: XF_FAR of the pass, XF_W blended, XF_NEAR of what the seam leads to. Every sum made in
 * the blend has its sixteen there, and a pass cannot step over the place it goes in at (a frame's step
 * is under 64 frames). Before them the seam they were made for. Never cleared: believed while the
 * count in the voice says so, which a note's start sets to 0. */
#define XF_W 256
#define XF_NEAR 16
#define XF_FAR 80
#define XF_N (XF_FAR + XF_W + XF_NEAR)
#define XF_STEP 8
#define XF_REACH (XF_W + XF_FAR - 8)        /* frames before its wall a pass goes into its blend */
struct xf {
    s32 wall, to;           /* the seam: where the pass ends, and where the next begins, as positions (20.12) */
    s32 zone;               /* a pass is in the blend from here on: forward at or past it, backwards under it (the frame
                             * at it is the last outside) */
    s32 off;                /* the position of the first frame below */
    s16 l[XF_N], r[XF_N];
#ifdef TRIM
    u32 key;                /* the trim image: what the blend was made from, once it is all written; 0 while it is not */
#endif
};
/* A voice's: 0x800 bytes a voice from 0x44062000. Its number is read off the pointer to its frames around a
 * slot's ends, which a note's start sets: 256 bytes a voice from HQ_PADS, so 8 times that is 0x800 a voice. */
#define XF(s) ((struct xf *)(((u32)(s)->pad << 3) + 0x23d5e000u))
_Static_assert(((0x44060800u << 3) + 0x23d5e000u) == 0x44062000u && sizeof(struct xf) <= 0x800, "XF: a voice's blend, from its pad");

#ifdef TRIM
/* The trim image: a pitched note, a fade and a loop's blend for less of the block. The maintainer, 2026-10-14: P "up to 100
 * at times", "its when i pitch things", "and loops to actually just not as much". Three things, each in its own place:
 *
 *   - The pitched sum (engine/stub.S, HQ_TAP): a frame of each side is fetched as a long, the frame after it in the
 *     low half, and that half is no longer cleared. A product's low half is that frame unsigned times the table's
 *     number, 2^-16 of the sum's units: the sum is off by at most what the row's numbers add up to, about one step of
 *     a 16-bit frame (the numbers are 16 bits, shifted up 15). 22 instructions fewer a stereo frame, 2 a mono one.
 *     Every form of instruction is the one it was.
 *   - The fade (fade_run, engine/stub.S): a frame in 5 steps a side where it was 7 and two tests, the gain held only
 *     where it can reach 4096 or 0, worked out once a run. The same frames to the bit.
 *   - A loop's blend: a note's start no longer throws it away. Once all of it is written its voice's key is made
 *     (blend_key): the slot's two places, its length, the way it plays, the build's mark, and 8 frames of each
 *     place the blend is read from on each side. A note whose seam is the one written, and whose slot still gives
 *     that key, has it at once, where it was written again over 44 blocks. A take into the slot, a sample loaded
 *     over it, or a start with other samples changes the key, and the blend is written again. The key is not
 *     believed across a change of how a blend is made: TRIM_FORMAT is in it. */
#define TRIM_FORMAT 0x5452494du     /* "TRIM": the blend's shape; change it with the blend */
#endif

#ifdef EIGHT
/* The eight image: the slim image with a pitched frame summed from eight frames, i - 3 to i + 4, where it was twelve,
 * in the six image's place. On request. Its own window, Kaiser
 * beta 5.0 (tools/sinctable.py, rows8). The table, the copy and the room as the six image's; both channels sum the
 * eight places 4 to 11 (HQ_SKIP1, HQ_SKIP2). */
#endif

#ifdef SIX
/* The six image: the slim image with a pitched frame summed from six frames, i - 2 to i + 3, where it was twelve. The
 * on request, told it is every pitched frame's cost (not at a sample's own pitch or octaves up),
 * a little off the very top of anything pitched, and more aliasing on bright material pitched up. The table is the
 * same 16 places with five noughts at each end (tools/sinctable.py, rows6), so its rows, the copy made at a start and
 * the reads around a slot's ends are as they were; two channels sum the six (HQ_SKIP2), one channel eight places,
 * the six and a nought each side, for its loop of four (HQ_SKIP1). */
#endif

#ifdef SLIM
/* The slim image: the trim image for less again, the sound the same to the bit. The maintainer, 2026-10-14, after the trim
 * image on the maintainer's unit ("def tell it sbetter ... but still cant trend to max at the wrong times"): "do hits off when
 * unused, and tightening the pitched sum". The second only: the pitched sum (hq_run and hq_safe, engine/stub.S).
 * Once a run, by two divides, how many frames on are inside its bounds and have all sixteen in the slot; those are
 * made with neither of the two tests a frame had, and two channels' next frame is begun where the last ended, not by
 * a branch. The frames after them are tested as before. 7 instructions fewer a pitched frame of two channels, 1 a
 * frame of the sample's own; one channel's frames are the trim image's, in the same steps (no room in their run).
 *
 * Hits off where DEL is 0 was not built: DEL does not reach the audio CPU. What crosses is packed, a track's type,
 * its machine's ten words and eleven words of the stages (emu/engine.py, HOST_FIELDS, as stock's interrupt unpacks
 * it), and slot 31 is not among them. Read here as built, every track would have had its hits off. */
#endif
#endif

#ifdef TIMED
/* The time image, a tool and not one to keep: the stereo image with the audio CPU's load on the
 * sampling page. On request. The bench
 * counts instructions and knows nothing of time; on the unit eight pitched stereo tracks at 160,319
 * instructions an interrupt were "major distortion" and 116,679 passed, and nothing said how near
 * the edge either was.
 *
 * Audio CPU (engine/stub.S): a timer stock starts and never reads is read where the interrupt
 * calls the voice loop and where its last stage comes back. Every 256 blocks (171 ms) the longest
 * such stretch, as hundredths of a block, and the most that has been in the last 5 to 11 seconds
 * go to two longs of the window, after the long that says which tracks have a right channel. A
 * block is what the gaps between interrupts come to, measured by the same timer. The sound engine
 * is the stereo image's, byte for byte: two calls of the interrupt's go through a run of Twinshot's.
 *
 * Main CPU (engine/recpage.c): the page's lower row, second and third places, where a value goes:
 * C and the first number, P and the second. 100 is a block's whole time: the next interrupt is
 * late. Not in it: what the interrupt does before the voice loop and after the last stage. */
#define TIMED_BOX ((const volatile u32 *)0x100005b4)
#endif
#if defined(PEAK) && !defined(TIMED_BOX)
#define TIMED_BOX ((const volatile u32 *)0x100005b4)    /* the page of an image that shows the second number alone */
#endif

#ifdef STOPS
/* The stops image: SMPL stops only on real samples and one free spot of each kind. The maintainer, 2026-10-12,
 * told that on the pack image the knob has numbers that mean little where the two kinds share slots: "yea i
 * dont ant junk numbers like this ... dealing with the junk numbers somehow so the stereo to mono sample
 * switching reads cleanly". Turning SMPL on the first page stops at the stereo places that hold a sample, the
 * lowest stereo place that is free, the highest single slot that is free, and the single slots that hold a
 * mono sample, and at nothing else. A number keeps its meaning and the sound engine plays whatever number it
 * is given: only the knob's travel skips (engine/recpage.c).
 *
 * What says which kind a slot holds is its length in frames, since a number that is skipped cannot:
 *   0     empty;
 *   odd   a mono sample of a single slot;
 *   even  it belongs to its stereo place (a stereo sample's side, or a mono sample in a stereo place).
 * So a single slot's take is one frame short of its whole blocks, from its first block on, and a mono take in
 * a stereo place leaves two frames in its second slot where the mode image left one (TAKE_ONE): that slot is
 * no right channel and no single slot's sample either. `make samples PACK=1` makes files the same way.
 * One frame exactly is taken for what the mode and cross images left in a mono take's second slot, since such
 * takes are kept on the drive: no sample, and not free.
 *
 * Only the audio CPU knows a take that is not on the drive yet. So it says, in the window, two bits a slot:
 * the length's lowest bit, and whether anything is left of it without that bit. Sixteen slots a long, the
 * first slot's two bits the highest, the odd bit the higher of the two. A long a block (engine/stub.S,
 * stops_say), so every slot is said again every four blocks. The four longs are where the window has eight
 * bytes nothing uses, twice: after the recorder's count and random number (0x808) and after the sampling
 * page's box (0xe38).
 *
 * The mark is a fifth long, at 0x5bc, after the right channels' long and the time image's two. The audio CPU
 * moves it up a byte every block and puts 0xa5 under it, so it reads STOPS_OK when four blocks have gone by
 * since it last did not, and all four longs are written by then. The main CPU sets it to 0 for as long as the
 * audio CPU is down (engine/rightfill.c, as it does the right channels' long): at a start, and when the audio
 * CPU starts again after samples are sent to the unit, nothing of before is believed. It is outside the 2 KB
 * the boot's loader sends samples through, which the main CPU must not write to meanwhile. (The audio CPU's
 * interrupt, which writes the four longs inside those 2 KB, is not running then: its start puts the interrupt
 * in place last, after the pool is in.)
 * Words and longs only, as everywhere in the window: the audio CPU longs. */
#undef TAKE_ONE
#define TAKE_ONE 2
#define STOPS_OK 0xa5a5a5a5u
#define STOPS_LONG(window, g) ((volatile u32 *)((window) + ((g) < 2 ? 0x808u + 4u * (g) : 0xe30u + 4u * (g))))
#define STOPS_MARK(window) ((volatile u32 *)((window) + 0x5bcu))
#define STOPS_COUNT ((u32 *)0x44050a18)     /* audio CPU, free memory after the time image's: a count of blocks. Any number will do at a start */
#endif

/* A sample plays at half scale, as one of Twinshot's two layers did. A take
 * plays at full scale: 6 dB more, and still nothing the later stages have not
 * been handed by stock (both layers at once).
 * With KEEP a take becomes a loaded sample at the next boot, so there both play
 * at a take's level: a kept take sounds the same before and after. */
#define GAIN_TAKE 0x7fffffff
#ifdef KEEP
#define GAIN_SAMPLE GAIN_TAKE
#else
#define GAIN_SAMPLE 0x40000000
#endif

/* Our state: the 88 bytes at voice+1712 that Twinshot used. */
struct st {
    const s16 *l;           /* +0  current slot, left */
    const s16 *r;           /* +4  current slot, right, or 0 */
    s32 pos;                /* +8  position in the current slot, 20.12 */
    s32 frames;             /* +12 frames in the current slot */
    s32 bound;              /* +16 where travel in this slot ends, 20.12 */
    s32 playing;            /* +20 */
    s32 inc;                /* +24 written by stock_pitch */
    s8 dir;                 /* +28 +1 or -1 */
    s8 dir0;                /* direction the note started in */
    u8 mode;                /* 0 one-shot, 1 loop, 2 ping-pong */
    u8 stride;              /* 1, or 2 for stereo */
    u8 k;                   /* current slot */
    u8 ka, kb, kc;          /* slots of region start, region end, and the end a loop goes back to */
    s32 pa, pb, pc;         /* frame in ka, frame in kb (exclusive), frame in kc */
    u8 stereo;              /* this note plays a stereo pair. The pack image: its place is one, and not a single slot */
    u8 link;                /* the MODE knob says stereo right now: the next track is ours. The mode image on: what the running take is */
    u8 rvalid;              /* STASH holds this block's right channel */
    u8 rec;                 /* recorder: a take is running */
    u8 rk;                  /* its left slot */
    u8 rlive;               /* one-track stereo: the right channel's filters carry on from the block before */
    u16 rseq;               /* last mailbox block taken */
    s32 rpos;               /* frames written */
#ifdef FADE
    s16 fade;               /* gain of what the player puts out, 0..FADE_ONE */
    s16 fstep;              /* what it moves by a frame: 0, up or down */
    s32 span;               /* frames in the region */
    u8 fwall;               /* the wall is a cut: a loop's seam, or a one-shot's end inside the sample */
#ifdef LIVE
    u8 duck;                /* the far end has come in behind the place played from: down first, then the next pass */
    u16 strt;               /* STRT as the note took it: what it stays, when the knob is not followed */
#endif
#endif
#ifdef HQ
    const s16 *pad;         /* +72 the frames around the slot's two ends, written out at the note's start */
    u32 reset76;            /* +76 stock's voice reset puts a number of its own here */
    u32 made;               /* +80 voice 0's is HQ_MADE; stock's voice reset clears it */
#endif
#ifdef XFADE
    union {
        struct {
            u16 xn;         /* +84 frames of the seam's blend written out; XF_N: all of them */
            u8 xuse;        /* 1: this block's pass may go into the blend. 2: it is in it, to its wall */
            u8 xnew;        /* the pass or the knobs have moved since the seam was last worked out */
        };
        u32 xall;           /* the three at once: 1 is a note's start */
    };
#endif
};

/* Fades (-DFADE, the fade image; needs PAGE: a region is in one slot). Where the
 * sound is cut into, it is not switched on or off but faded, so that a cut does
 * not click:
 *   - a note that starts inside the sample fades in;
 *   - a one-shot that ends inside the sample fades out up to its end;
 *   - a forward loop fades out up to its seam and in again after it. The seam's
 *     place and the loop's length do not move: a loop stays in time.
 * A note that starts at the sample's own start, a sample that plays to its own
 * end and a ping-pong turn are left exactly as they were, and so is a region too
 * short to hold the fades (under eight fade-outs long at the pitch it plays at):
 * a loop of a few milliseconds is a tone, and a dip a pass would change it.
 * Lengths are in frames put out, so they do not change with pitch. */
#define FADE_ONE 4096
#define FADE_IN 64          /* frames: 1.3 ms */
#define FADE_OUT 128        /* frames: 2.7 ms */
/* LEN, and with -DLIVE_STRT also STRT, while a note plays (-DLIVE; needs FADE).
 * Two builds of this ran on the unit and both were wrong for STRT
 * (docs/FINDINGS.md): one moved the place played from with the knob, a flutter;
 * one moved the region's two ends under it, so that a short loop was either
 * left behind by its region and played straight on, or caught by it and cut,
 * a step of the knob at a time.
 *
 * Here a note is a row of passes. A pass begins at a place and is as long as
 * the knobs say the region is, counted from where it began. pa and pb are the
 * pass that is playing; pc is where the knobs have the next one begin; span is
 * how long they have it.
 *   - Every block the length is worked out again and the playing pass ends
 *     that far from its own beginning: LEN acts at once.
 *   - A loop's next pass begins where the knobs have the start by then. Nothing
 *     is done to the pass that is playing: a short loop steps through the
 *     sample a pass at a time, a long one takes the new start when it comes
 *     round. A ping-pong takes it when it is back where its pass began.
 *   - The far end come in behind the place played from: a loop's next pass
 *     begins now and a one-shot is over, through a fade out and a fade in when
 *     the region is long enough to have fades at its seam; a ping-pong turns
 *     where it is.
 * Without LIVE_STRT the start is the one the note took, and only the length
 * moves (played backwards that is still the place a pass begins).
 * A block in which the knobs have not moved is the fade image's, bit for bit.
 * LOOP and the direction are a note's own, taken at its start. */
#define ST(v) ((struct st *)((u8 *)(v) + 1712))
#ifdef HQ
_Static_assert(__builtin_offsetof(struct st, made) == 80 && 0x80000000u + 1712 + 80 == 0x80000700u, "HQ_MADE is voice 0's state + 80");
#ifdef QUICK
_Static_assert(__builtin_offsetof(struct st, r) == 4 && __builtin_offsetof(struct st, pos) == 8 && __builtin_offsetof(struct st, frames) == 12 &&
               __builtin_offsetof(struct st, dir) == 28 && __builtin_offsetof(struct st, pad) == 72, "engine/stub.S, hq_run, reads these");
#endif
#endif
_Static_assert(sizeof(struct st) <= 88, "state must fit in Twinshot's 88 bytes");
_Static_assert(__builtin_offsetof(struct st, inc) == 24, "stock_pitch writes player+24");
_Static_assert(__builtin_offsetof(struct st, rec) == 51 && __builtin_offsetof(struct st, rpos) == 56,
               "tests/test_recorder.py reads these");

/* The multi image (-DMULTI): several tracks record at once, each from its own source. The ring is no ring: its eight
 * blocks are a block a track, track t's at MB's ring[t], and every track that says record is fed its own source's
 * block every mixer call. The word under the count (0x802, the window's last two free bytes) says which blocks were
 * written with that count: a bit a track, the first track's the lowest. Count and bits are one long, written last.
 * A block is there for one call only, so the audio CPU takes it before the voice loop and not after: the main CPU
 * writes after its mixer, which comes after it has waited for the audio CPU's eight buffers, and the next edge comes
 * after that. The order is stock's own for its knobs (docs/FINDINGS.md, "How the two CPUs take turns"); it is read,
 * not timed. engine/stub.S, rec_all; engine/recfeed.c. */
#define MB_FED(window) (*(volatile u32 *)((window) + 0x800u))

#ifdef SRR
/* The srr image (-DSRR): sample rate reduction, in MODE's parameter (knob slot 23), which is freed for it. The maintainer,
 * 2026-10-13: "kill swarm, yes freeing mode if possible".
 *
 * The sound. Every frame the player makes is held for a while: a phase goes up by a step a frame, and only a frame
 * at which it runs over is let through; the frames between are that one again. No smoothing: what the hold folds
 * down is the sound. Both sides of a stereo sample are held by the one phase. It is done to what the player made,
 * before the voice's own level and gain and so before every stage of stock's, and a note's start sets the phase so
 * that its first frame is let through: a hit is the same hit every time.
 * The knob is 0 to 127 and every 16 of it halves the rate: 0 is off (nothing is run), 16 is 24 kHz, 32 is 12, 48 is
 * 6, 64 is 3, 80 is 1.5 kHz, 96 is 750 Hz, 112 is 375, 127 is about 190. Between two halvings the hold's length
 * goes up evenly, so a lock or an LFO between two numbers is a rate between. The hold's length in frames, in 256ths:
 * (256 + f) << n, with n the knob's sixteens and f sixteen times what is left of it, and the step is 2^32 / length.
 * A length of one frame is off.
 * Its state is a voice's sixteen bytes of free memory (nothing clears it at a start: a note's start does).
 *
 * MODE's parameter held three things: the dead stereo bit, the track's REC in bit 1 and its SRC in bits 2 to 6. They
 * are now the track's own word on knob slot 24, which no knob of a digital machine uses: SRR_SIG with the track's
 * REC in bit 0 and its SRC in bits 8 to 11. The high byte is never one of a step's two marks (REC_LOCK_ON,
 * REC_LOCK_OFF). A word that is not signed is an old pattern's: the main CPU's per-block routine
 * (engine/recword.S) makes it from MODE's bits, signs it, and puts MODE at 0, so the reduction starts off. One way:
 * an older image reads such a pattern's MODE as mono, REC off, the main mix.
 * The audio CPU no longer reads MODE's bits. The main CPU sends it, in slot 24 of the block every block, what the
 * track is to do: REC_LOCK_ON or REC_LOCK_OFF in the high byte (the step's lock if it has one, or the track's own),
 * and the track's SRC in the low byte, which the feed reads there (engine/recfeed.c). A take at a stereo place is
 * stereo, as it has been since MODE lost its knob.
 *
 * SY SWARM's code is the room (tools/audiomap.py, SRR_CAVES): engine 10's two table entries are a stand-in that
 * plays nothing (engine/stub.S). */
#undef REC_ON
#define REC_ON(m, r) ((r) == REC_LOCK_ON)
#define SRR_SIG 0x40a4u
#ifdef LOCK
#if defined(NEXT)
#define SRR_SIG_MASK 0xf0a4u    /* the next image: and bit 6 is the track's KIND, MONO when set (engine/recpage.c, NEXT) */
#define SRR_KIND 0x40u
#else
#define SRR_SIG_MASK 0xf0e4u    /* the lock image: and bit 4 is KEYS's tempo lock */
#endif
#define SRR_KEYS 2u
#define SRR_STR 8u
#define SRR_LOCK 16u
#elif defined(STRETCH)
#define SRR_SIG_MASK 0xf0f4u    /* the stretch image: bit 3 of the track's word is KEYS's stretch, signed either way too */
#define SRR_KEYS 2u
#define SRR_STR 8u
#elif defined(SLICE)
#define SRR_SIG_MASK 0xf0fcu    /* the slice image: bit 1 of the track's word is its KEYS, and a word with it is signed too */
#define SRR_KEYS 2u
#else
#define SRR_SIG_MASK 0xf0feu
#endif
#define SRR_SIGNED(w) (((w) & SRR_SIG_MASK) == SRR_SIG)
#define SRR_REC(w) ((w) & 1u)
#define SRR_SRC(w) ((w) >> 8 & 15u)
#define SRR_WORD(src, rec) (SRR_SIG | (src) << 8 | (rec))
/* main CPU: the kit the sound engine's side reads (stock keeps its address at 0x800030b8), and a track's own 71
 * words in it, slot s the word at 2 s: 291 bytes a track, the first track's words 62 in */
#define KIT (*(u8 *volatile *)0x800030b8)
#define OWN_WORDS(t) ((volatile u16 *)(KIT + 291u * (t) + 62u))
#define SRR_DIRTY ((volatile u8 *)0x401a8d52)       /* eight bytes at the start of the routine's run: track t's word was just made from MODE */
/* audio CPU */
struct srr {
    u32 step;               /* what the phase goes up by a frame; 0: off */
    u32 phase;
    s32 l, r;               /* the frame that is held */
};
#define SRR_ST(t) ((struct srr *)(0x44050a40u + 16u * (t)))
void crush(struct srr *h, s32 *l, s32 *r);          /* engine/stub.S: a block held. r: 0 for one channel */
#endif

#ifdef SOFT
/* The soft image (-DSOFT): a take begins wherever its source was, so its first frame is seldom near nothing, and
 * a note at STRT 0 began on it at once: a click, by the maintainer's ear worst on one low sound alone. A note whose
 * first frame, on either side, is past SOFT_MIN of a sample's 32,768 is faded in over FADE_IN frames, as a note
 * that starts inside the sample always was. A sample that begins near nothing (a hit taken from its start, any
 * trimmed file) is not touched. In SY SWARM's room. */
#define SOFT_MIN 128
#endif

/* The tail image (-DTAIL): a one-shot that plays to the sample's own end stopped on its last frame at once, and a
 * take of a bar, which ends wherever its source was, clicked there, by the maintainer's ear at the bar's next trig
 * ("it goes away if I turn down the length 1 value"). A one-shot is faded out over the FADE_OUT frames before its
 * far end wherever that is, as one with LEN short of all always was. */

#ifdef HITS
/* The hits image (-DHITS): a long sample's hits start the filter's envelope again, as a trig of the filter's own. The
 * envelope is the main CPU's (docs/FINDINGS.md, "The filter's envelope is the main CPU's"), so this side says which
 * tracks reach a hit and how loud it is, and the main CPU hands the envelope a trig for each one that DEL lets
 * through (engine/hits.c). In the code of SY TOY and SY BITS, which the maintainer gave up ("get rid of either or both of
 * those machines"): a track left on either plays nothing, as one on SY SWARM.
 *
 * The scan: every slot that holds frames is gone over once, HIT_SCAN frames a block, a slot a playing voice is on
 * first, the others in turn; what it finds stays with the slot, for the slices to come. A hit is a window of HIT_WIN
 * frames whose loudest is more than twice the follower (the loudest so far, down by a 64th a window), HIT_GAP windows
 * or more after the last. It is kept as its window, how loud it is (the loudest of that window and the HIT_RISE
 * after it: 1 at -45 dB to 15 at -3 dB and up, 3 dB a step), and how long it is: to the end of its last window that is
 * within HIT_TAIL of its own loudest, found once a follower that falls a 16th a window is under that (a dip at a low
 * note's crossing does not end it), and never past the next hit. A slot is gone over again when its place, its frames or
 * a print of 16 of its frames change. The print has HIT_FORMAT in it: the lists outlive a flash (memory under the takes
 * is not cleared at a start), and the first build's, believed by the second, said no hit at all on the unit.
 *
 * The pass: a voice says the loudest hit its playhead will reach two blocks on that it has not said; the main CPU
 * hears of it a block later and the cutoff it makes is played the block after (INFERRED from the order the two CPUs
 * run in, not timed). Going forward a hit is reached at its start; going backward at its end, where its sound comes
 * up out of the quiet. Not the
 * hits a note starts on: stock's own trig has those. A loop says its start again after each turn, a block late.
 *
 * The word: four bits a track, track t's at bit 4t, written to the window every block at HIT_BOX, where the time
 * image's C was (no image after it shows that one; the time image's routine no longer writes it). */
#define HIT_WIN 32
#define HIT_SCAN 128
#define HIT_GAP 32
#define HIT_RISE 3          /* windows after a hit's own that its loudness is taken from too */
#define HIT_TAIL 4          /* a hit lasts while a window's loudest is its own loudest shifted down no further: 24 dB */
#define HIT_FALL 4          /* the follower that says it is done falls by this shift a window: 0.56 dB */
#ifdef HITPEAK
#define HIT_MAX 121         /* the switch image: a long of the 122 for the slot's loudest frame */
#define HIT_PEAK_SCAN 256   /* frames a block of the first pass, which finds it: about a normal scan block's cost */
#else
#define HIT_MAX 122
#endif
#if defined(HITSCAN)
#define HIT_FORMAT 0x48495435u  /* "HIT5": the scan image's hits and steps */
#elif defined(HITPEAK)
#define HIT_FORMAT 0x48495434u  /* "HIT4": a slot's steps go from its own loudest frame (the switch image) */
#elif defined(HITCURVE)
#define HIT_FORMAT 0x48495433u  /* "HIT3": the trig image's steps of loudness. A list another build left is not believed */
#else
#define HIT_FORMAT 0x48495432u  /* "HIT2": the shape of a list. A list another build left is not believed */
#endif
/* A hit's long: its window (frame / HIT_WIN) from bit 18, its length in windows from bit 4, how loud in bits 0 to 3 */
#define HIT_AT(w) ((s32)((w) >> 18) * HIT_WIN)
#define HIT_LEN(w) ((s32)((w) >> 4 & 0x3fff) * HIT_WIN)
struct hits {               /* a slot's, 512 bytes */
    const s16 *data;        /* the slot as it was gone over */
    s32 frames;
    u32 print;
    s32 done;               /* frames gone over */
    u16 env;                /* the follower */
    u8 gap;                 /* windows since the last hit, up to HIT_GAP */
    u8 n;
    u16 top;                /* the last hit's loudest so far; 0 when it is done */
    u16 fall;               /* the follower that says it is done */
    u32 hit[HIT_MAX];
#ifdef HITPEAK
    u16 peak;               /* the switch image: the slot's loudest frame, found by a first pass while done < 0 */
    u16 spare;
#endif
};
struct hitv {               /* a voice's, 16 bytes */
    s32 ahead;              /* how far on its hits have been said, on its line of travel */
    s32 was;                /* its frame a block ago, on that line */
    u8 k;                   /* the slot they were said of; 0xff: none */
    u8 cur;                 /* the next hit on that line not said */
    s8 dir;                 /* the line: +1 forward, -1 backward */
};
#ifdef HITSCAN
/* The scan image (-DHITSCAN): on request
 *
 * . The switch image's scan wanted a window's loudest past twice a follower (6 dB over
 * whatever was held, so a hit on a held bass or a pad was none), nothing at or under -45 dB of full scale (a take
 * that peaks at -30 kept only what was within 15 dB of it), and a hit's step was its loudness in 2 dB steps.
 *
 * Here a window is looked at twice: its loudest frame, and its loudest step from one frame to the next (a high pass
 * of one subtraction, put on the frames' scale by the slot's own loudest of each, from the first pass), each with its
 * own follower, falling a 128th a window (a 15 Hz wave's halves do not read as hits), kept in 256ths so a quiet take's
 * falls too. A hit is either past its
 * follower by half again (3.5 dB), by more than HITX_FLOOR under the slot's loudest frame, HIT_GAP windows after the
 * last. How sharp it is: the larger rise over the two followers as they were where it began, in its own window and
 * the HIT_RISE after it, kept in 1.5 dB bins. When the slot is gone over, its step is its place among the slot's
 * hits by that: the sharpest fifteenth 15, down to 1, so DEL takes the same share more of them each step whatever
 * the sample. A hit's length is found as before. In SD BASIC's code, which the maintainer gave up for it: a track on SD
 * BASIC plays nothing. */
#define HITX_FLOOR 7        /* a rise of more than the slot's loudest shifted down this far: 42 dB under it */
#define HITX_MIN 8          /* and of more than this, whatever the slot: -72 dB of full scale */
#define HITX_DECAY 7        /* the followers fall by this shift a window */
struct hitx {               /* a slot's, 256 bytes */
    u32 env, envd;          /* the followers of the loudest frames and of the steps (on the frames' scale), in 256ths */
    u16 dpk;                /* its loudest step from one frame to the next, by the first pass */
    u16 base, based;        /* the two followers where the last hit began, whole */
    u8 bin[HIT_MAX];        /* how sharp each hit is, in 1.5 dB bins, until its step is made */
};
#define HITX(k) ((struct hitx *)(0x44066000u + 256u * (k)))       /* free SDRAM after the cross image's: 16 KB */
_Static_assert(sizeof(struct hitx) <= 256, "the scan's memory");
#endif
#define HITS_AT(k) ((struct hits *)(0x44070000u + 512u * (k)))     /* free SDRAM under KEPT: 32 KB */
#define HITV(t) ((struct hitv *)(0x44078000u + 16u * (t)))
#define HIT_RR (*(u32 *)0x44078080u)        /* the slot gone over when no voice asks for one */
#define HIT_BOX ((volatile u32 *)0x5b4)
#define HIT_PARAMS ((const u8 *)0x80003c40)     /* the knobs, where the interrupt hands its stages them (0x40000a28) */
_Static_assert(sizeof(struct hits) == 512 && sizeof(struct hitv) <= 16, "the hits' memory");
void hits_block(void);                          /* the end of the interrupt: the right channels' long, then the hits */
#endif

#ifdef SLICE
/* The slice image (-DSLICE): a sampler track's keys play its sample's slices where they played its pitch. The maintainer,
 * 2026-10-16: "keys switc will switch between slices or chormatic which is stock". KEYS, the sampling page's knob H,
 * is bit 1 of the track's own word on slot 24 (SRR_KEYS), and the main CPU sends it as bit 7 of slot 24's low byte
 * (SLICE_BIT), under the source (engine/recword.S). At a note's start on such a track the note is latched: n, its
 * number less 60 (60 is the sample's own pitch, a trig's note when none is locked), picks the slice, and the note is
 * taken off the pitch for as long as the note plays, so a slice plays at its own pitch and TUNE; what the note is
 * moved by after (an LFO) still moves it. The slices are the scan's hits (HITS_AT): slice i from hit i's window to
 * hit i + 1's, the first from frame 0, the last to the sample's end. No list, or the scan not through the sample yet:
 * SLICE_EVEN even slices. n is taken round the count both ways, so every key plays one. STRT and LEN are the slice's
 * as they are the sample's on a plain note; while a slice plays they are not followed. */
#define SLICE_BIT 0x80u
#define SLICE_EVEN 16
struct slc {
    s32 off;                /* semitones taken off the note's pitch: the note's number less 60, or 0 */
    u32 on;                 /* the note plays a slice */
};
#define SLC(t) ((struct slc *)(0x44078100u + 8u * (t)))   /* free SDRAM after the hits' voices; any number will do at a start */
#ifdef NORM
/* The norm image: every take normalized to -1 dB once it ends (engine/sampler.c, norm_block). The maintainer, 2026-10-21:
 * "could we also add noramlize to the recorder? i notice i have to turn up db often on the sampling page", and his
 * choices: the take itself rewritten, always on, -1 dB. A take is scaled up by at most NORM_MOST (30 dB), never down.
 * In free SDRAM after the slices' voices, believed only while NORM_UP, voice 1's state + 80, which stock's voice reset
 * clears at a start and when track 2's machine changes, says so. */
struct norm {
    u32 gain;               /* 2.14, 0: no take being scaled */
    u32 pos;                /* frames scaled */
    u32 frames;             /* the take's, as its line had them at its end */
    u8 k;                   /* its slot */
    u8 two;                 /* and the next one's too: a stereo take */
    u8 was;                 /* a bit a track whose take ran the block before */
    u8 wait;                /* a bit a track whose take has ended and is not scaled yet */
    u16 peak[8];            /* a track's take's loudest frame so far */
};
#define NORM_AT ((struct norm *)0x44078200u)
#define NORM_UP (*(volatile u32 *)(0x80000000u + 1800u + 1712u + 80u))
#define NORM_MAGIC 0x4e4f524du
#define NORM_TOP 29204u         /* -1 dB of full scale */
#define NORM_MOST (32u << 14)
#define NORM_STEP 256           /* frames a block, the two sides together: what the keep box reads a request */
#endif
#endif

#ifdef QUICK
/* Frames n to end - 1 of the block, as long as the position is at or past lo and less than span
 * past it; the position is moved on a step after each. -> the first frame not made. r: 0 for one channel. */
int hq_run(struct st *s, s32 *l, s32 *r, int n, int end, s32 lo, u32 span);
#endif
void sampler_update(s32 pmod, s32 *voice, const u8 *p);    /* engine table entry */
void sampler_render(s32 *out, s32 *voice);                 /* engine table entry */
void sampler_post(s32 *out, u8 *params, u32 *masks);       /* after the voice loop */
void sampler_hook(void);                                   /* stub.S: replaces the voice loop call */

#ifdef STRETCH
/* The stretch image (-DSTRETCH): a note's speed apart from its pitch. The maintainer, 2026-10-22: KEYS's four settings and
 * "a speed knob" in PTIM's place, with WSOLA. KEYS on CHST or SLST (bit 3 of the track's own word, SRR_STR, sent as
 * STR_BIT of slot 24's low byte by engine/recword.S) latches a note as stretched at its start. Such a note's place
 * (s->pos) moves at SPD's speed (slot 52, PTIM's, the track's own word in the kit; slot 52 does not cross to the audio
 * CPU, so recword sends it as 0x80 and SPD in slot 24's high byte while REC is off: the third build. The first two put
 * it in the block's slot 52, which is not sent), through the same
 * walls, loops and edges as any note; what is heard is two heads that read the sample at the note's pitch, each for
 * STR_G frames from where the place was at its start, faded in and out as triangles half a grain apart, so their
 * sum is the sound at a steady level. A head that starts again looks up to STR_W frames either side of the place
 * for where it lines up best with the other head (WSOLA: the least summed difference, the left channel, every STR_K frames). A frame between two
 * is made from the two (two taps, as priced). SPD: 64 the note's own speed, every 32 a doubling: 0 a quarter, 127
 * about four times. Each track's heads begin out of step with the others' by STR_SKEW frames, so tracks trigged
 * together do not all look in the one block. Not stretched, a note plays as it did, by play(). */
#define STR_BIT 0x40u
#define K_SPEED 52
#define STR_G 1024
#define STR_W 32
#define STR_K 4
#define STR_N 16
#define STR_SKEW 64
struct str {
    s32 hpos[2];            /* a head's place, 20.12 */
    u32 age[2];             /* frames since it started; STR_G: start again */
    s8 hdir[2];             /* the way it reads */
    u8 on;                  /* this note is stretched */
    u8 fin;                 /* frames of the note's fade in so far, to 16 */
    u8 spd;                 /* SPD as last sent (slot 24's high byte less 0x80); 64 at a note's start */
    u32 pinc;               /* the note's pitch as a step, what stock_pitch gave */
    u32 tail;               /* 1: the place stopped in the block before, so this one fades out */
};
#endif

#ifdef LOCK
/* The lock image (-DLOCK): a stretched note locked to the tempo. On request
 *  to auto-snap. KEYS's CHLK and
 * SLLK (bit 4 of the track's word, SRR_LOCK, with bit 3) stretch a note's region to the power of two of steps nearest
 * its length at the tempo, and SPD is then a ratio on that (64 locked, 32 half time, 96 double). The tempo is stock's
 * own, the long at 0x402d7360 that the clock adds every block (BPM times 120; 14,400 in the image, 120 BPM). Only slot
 * 24 of a track's knobs crosses that can carry it, so engine/recword.S sends four things in turn, a block each, in
 * its high byte with REC off (0x80 and seven bits) and says which in bits 4 and 5 of its low byte (LOCK_TAG): 0 SPD,
 * 1 and 2 the low and high seven bits of a step's frames over 2 (43,200,000 over the tempo), 3 the lock (bit 0) and
 * PORT (bit 1). The audio CPU keeps each (struct lck, after the tracks' struct str). PORT on (the third build, his
 * word: "move the p time around and then just nap it back to the bpm with a switch") locks a stretched note to the
 * tempo whatever KEYS says, and SPD is not heard: on the tempo exactly. PORT is still stock's portamento too. */
#define LOCK_TAG(lo) ((lo) >> 4 & 3u)
#ifdef STSW
/* The stsw image (-DSTSW, main CPU): KEYS is CHRO or SLCE, and the stretch is the sampling page's knob E, the track's
 * (bit 3, SRR_STR, as before) or a step's: a lock on slot 17's low byte, STR_LOCK_ON or STR_LOCK_OFF, beside the
 * solo's mark in its high byte (STR_NO_SOLO there when the step's solo is the track's). Everything that reads the
 * solo's lock reads its high byte only. engine/recword.S takes a step's mark where the locks are written over the
 * track's bit, into STR_BIT; the audio CPU latches it at the note's start, as it did. */
#define STR_LOCK_ON 0xd5u
#define STR_LOCK_OFF 0xa9u
#define STR_NO_SOLO 0x00u
#define STR_MARKED(w) (((w) & 0xff) == STR_LOCK_ON || ((w) & 0xff) == STR_LOCK_OFF)
#endif
struct lck {
    u8 lo, hi;              /* a step's frames over 2, its low and high seven bits */
    u8 on;                  /* bit 0: the track is locked (KEYS); bit 1: snapped, PORT on */
    u8 pad;
};
#endif

/* The scrub image (-DSCRUB): STRT and LEN followed on a stretched note as on one that is not. The maintainer, 2026-10-23:
 * "when you set it to a loop and then try to adjust the start and the length while the loop's continuously repeating,
 * it doesn't work the same way it does when stretch is off". A turn that left the place past the region's new end
 * (live(), caught) set duck and waited for play()'s fade to reach nothing before the next pass; a stretched note is
 * made by str_play, which runs no fade, so the wait never ended and no knob was followed again until the next trig.
 * str_update now lets it through the block after (its heads cross into the new place by themselves), and a one-shot
 * so stopped goes down over a block as at its end. Audio CPU only. */

/* The slscrub image (-DSLSCRUB): STRT and LEN followed on a slice as on a whole sample. On request
 * . The slice image left a slice's knobs alone while it played
 * (live() knew only the whole sample's region); live() now takes the region slice_cut gives at a note's start, STRT
 * inside the slice and LEN to the sample's end (RING), on SLCE and SLST both. Audio CPU only. */

#ifdef GRAIN
/* The grain image (-DGRAIN): a stretch that holds together. On request
 *  of two fixes. The stretch image's look for where a new
 * grain lines up was STR_W (32) frames either side, 0.67 ms: nothing under about 750 Hz could be lined up, and two
 * copies out of step went down and up at the grain's rate (94 Hz). And a drum's attack was read by every grain that
 * passed over it, early and twice. Here:
 *  - the wide look: STR_GW frames either side (62 Hz and up lined up), coarse on frames summed four STR_K apart (a
 *    low-pass) every STR_GS frames, STR_GN of them, then STR_GF either side of the best a frame at a time. STR_WIDE
 *    such looks a block for all tracks; past that a head looks as before;
 *  - locks: a hit of the slot's list (the scan's) or a loop's wall, reached by the place going forward more than a
 *    block and at most two from now, starts a head where it reaches that frame with the place; the two heads go down
 *    over the block, and it plays alone for STR_HOLD frames at the top of its triangle. Before it no head starts where
 *    it would read up to the lock point first, and after it none starts before STR_FLOOR frames past it.
 * Not going backward. A track's state past the far room's copy (GRAIN_BASE), made at each note's start. */
#define STR_GW 384
#define STR_GS 16
#define STR_GN 16
#define STR_GF 8
#define STR_WIDE 1
#define STR_HOLD 512
#define STR_FLOOR 128
#define GRAIN_BASE 0x47d73000u      /* m.FAR + 0x3000: in REC_BUF(65), which nothing writes; not copied */
struct grn {
    s32 floor;              /* going forward, no head starts before this frame: a lock's and STR_FLOOR */
    s32 lim;                /* the next lock point, 20.12; 0x7fffffff none */
    s32 newp;               /* a lock's new head's place, 20.12 */
    u8 hold;                /* blocks the lock's head plays alone */
#ifdef SPREAD
    u8 look;                /* the spread image: a look under way (struct grs) */
    u8 pad[2];
#else
    u8 pad[3];
#endif
};
#endif

#ifdef SPREAD
/* The spread image (-DSPREAD): the grain image's look in slices, for a lower peak. The maintainer, 2026-10-23, of P at 105
 * ("It seems like now CPU is peaking at 105"), then "build the spread search and also shrink it to 256, i want the
 * lowest peak". A head's birth is known blocks ahead (its age, or the hold), and so are where the place and the
 * other head will be then: STR_LEAD blocks before it those are foreseen and the low-passed frames written; then
 * STR_SK candidates a block, the coarse look's (STR_SW either side, STR_SN frames) and then the fine one's, so no
 * block has more than a slice of it. At the birth the result is moved as far as the other head is from where it was
 * foreseen; a look cut short by the birth gives its best yet (a note's first grains, a lock's hold), and with the
 * place gone elsewhere (a wrap, a knob) the head starts at the place. Foreseen at the other head's own place (a note at
 * its own speed), or the other head reading nothing, there is nothing to look for. STR_WIDE looks begin a block for
 * all tracks: notes trigged together begin theirs a block apart. */
#define STR_SW 256
#define STR_SN 12
#define STR_LEAD 8
#define STR_SK 9
struct grs {
    s32 at, q;              /* the place and the other head at the birth, foreseen, frames */
    s32 lo, hi;             /* the bounds a lock sets */
    s32 c0, n, j;           /* the candidates: c0, every STR_GS (fine: every frame), n + 1 of them; j the next */
    s32 best, least;        /* the look so far */
    u8 h, fine, pad[2];     /* the head it is for; the fine look's (struct grn's look: one under way) */
    s32 gr[2 * STR_SW / STR_GS + 2 * STR_SN];   /* the low-passed frames, then the other head's */
};
#endif

#ifdef TRAP
/* The trap image (-DTRAP): a stretched note for less. On request
 *  for the room. Two changes, the heads' births where they were:
 *  - a head's weight is a trapezoid, not a triangle: up over STR_X frames from its birth, flat to half a grain, down
 *    over STR_X, then nothing until its next birth. The two still sum to a constant, now STR_X, so a frame is scaled
 *    by STR_SH where it was 1. A block where one head is nothing is made by the other alone (str_one);
 *  - the place moves a block at once when no wall comes in it (the frame at a time only when one does).
 * CY ALLOY's code is the room (engine 2): its update and render, one run named only by its two table entries once
 * the code of ours that was Twinshot's is in (a long in Twinshot's code read as naming it in stock). A track on it
 * plays nothing. */
#define STR_X 128
#define STR_SH 3
#define CAVE_TRAP __attribute__((section(".cave.al"), noinline))
#endif
#ifndef STR_SH
#define STR_SH 1
#endif
#ifdef LETGO
/* The letgo image (-DLETGO). On request of the loose ends (docs/FINDINGS.md, "Loose ends and
 * cheap wins"). Two things:
 *  - a stereo note that is over lets go of its right channel once that channel's last block and the left's are under
 *    LETGO_QUIET (-120 dB of full scale, 2^31; a slow tail crossing nought over a whole block can let go a little
 *    louder, -108 dB the most seen in emulation): its track leaves R_MASK, so stock's four stages are not run on its silence again, and
 *    the main CPU copies the left as for a mono note. The way in and out of the mask is the one a track takes from a
 *    stereo sample to a mono one: seed() starts the right's filters from the left's when a note brings it back;
 *  - the normalizer goes by what each take was: a take is over when its track stops recording or begins another (its
 *    frames go back), its slot, its kind and its peak kept for its turn (struct pend); a take is dropped, or stops
 *    being scaled, only when a running take is in its own slots (norm_over); and the mark of the next slot is cleared
 *    only for a stereo take. */
#define LETGO_QUIET (1 << 11)
struct pend {
    u8 k[8];                /* a track's ended take's slot, waiting for its turn */
    u8 l[8];                /* and its link: 1 a stereo take, TAKE_SINGLE a single slot's */
    u8 ck[8], cl[8];        /* the same of the take it has running */
    u16 peak[8];            /* the ended take's loudest frame */
    u32 rp[8];              /* the running take's frames as the block before had them: a new take begins lower */
};
#define NORM_PEND ((struct pend *)0x44078240u)     /* free SDRAM after struct norm; believed only through its bits */
#define CAVE_LETGO __attribute__((section(".cave.al"), noinline))
#endif

#endif
