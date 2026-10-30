"""The stream image (engine/phone.c and engine/keeptakes.c, STREAM): the wipe image with a project's own samples back at
its load, written by the phone once the load is done and loaded slot by slot.

On the unit (2026-10-27, the phone app's log) the phone's writes go unanswered while a load waits on it, so LOAD PROJECT
left A as it was: "That sample that I recorded carried over". Here, with stock's routines around it played (test_phone's
rig):
  - LOAD PROJECT the phone answered ends by saying so, the ask frame with 0x6C in its id's place; not answered, nothing;
  - 0x6B, at any time, ORs its slots into the reload's and starts one job on stock's runner, none while one is queued;
  - the job takes the slots, drops any holding a take the drive does not have, and loads the rest as the load loads the
    phone's, again while more come, then lets go;
  - the loader in a reload reads the named slots alone, and as the wipe image's otherwise;
  - the image: the wipe image's but for the phone's and the banks' runs, the new runs, the SysEx entry and the load call.
Emulation only."""
import shutil

import pytest

import test_fltr as F
import test_newproj as N
import test_phone as P
from tools import build, build_main
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

JOB_RUNNER, JOB_START, STORE_READ = 0x4016ec18, 0x400bdc48, 0x401100d4
AUDIO_UP, KEEP_FRAMES = 0x43bdd824, 0x10000c1c
KEEP_PUT, KEEP_DONE = 0x8000, 0xffffffff
SLOTS = (0, 2, 33, 63)
MASK = sum(1 << s for s in SLOTS)


@pytest.fixture(scope="module")
def stream(official):
    return build_main.patched_image(official.section(3), xfade=78)


def put_of(r, built):
    """keeptakes.c's put, the one call by address in the job (a name other runs have too)."""
    lo = r.syms["stream_body"] - mm.BASE
    body = built[0][lo:lo + 200]
    at = body.index(b"\x4e\xb9")
    return int.from_bytes(body[at + 2:at + 6], "big")


def rig(built, answer=True):
    r = F.rig(built, now_project=9, project_bank=0, now=0)
    mc = r.mc
    mc.map(0x10000000, 0x10000)                 # the shared window: the keep box
    mc.map(0x43bd0000, 0x10000)                 # the audio CPU's up mark
    mc.map(0x4d800000, 0x200000)                # the loader's staging
    mc.w32(AUDIO_UP, 1)
    r.stub(mm.PROJECT_MAKE, lambda m, p: r.log.append(("make",)))
    r.stub(JOB_RUNNER, lambda: 0x5555)
    r.stub(JOB_START, lambda run, name, what, done: r.log.append(("job", mc.read(name, 11), mc.r32(what + 12), run)))

    def wait(sem):                              # (the rig's own hook on the wait logs it)
        if answer:
            mc.w32(r.syms["phone_answer"], 1)
    r.stub(P.KERNEL_WAIT, wait)
    mc.w32(r.syms["phone_seen"], 1)
    mc.uc.ctl_flush_tb()
    return r


def masks(r, at):
    return r.mc.r32(at), r.mc.r32(at + 4)


def test_load_project_answered_says_so_after_the_load(stream):
    r = rig(stream)
    r.log.clear()
    assert r.mc.call(r.syms["stream_load"], 0x1234, 5, 0x5678) == 7
    kinds = [e[0] for e in r.log]
    assert kinds[-3:] == ["load", "write", "commit"]
    said = bytearray(N.frame(5, 0, 9))
    said[11] = 0x6c
    assert r.log[-2][1] == bytes(said)
    assert r.var("phone_answer") == 0 and r.mc.read(r.syms["phone_frame"] + 11, 1) == b"\x60"


def test_load_project_not_answered_says_nothing(stream):
    r = rig(stream, answer=False)
    r.log.clear()
    assert r.mc.call(r.syms["stream_load"], 0x1234, 5, 0x5678) == 7
    assert r.log[-1][0] == "load" and [e[1][11] for e in r.log if e[0] == "write"] == [0x60]


def test_0x6b_names_slots_and_starts_one_job(stream):
    r = rig(stream)
    data, n = r.frame(0x6b, MASK, 18)
    r.log.clear()
    r.mc.call(r.syms["stream_sysex"], data, n, 2)
    assert r.log == [("job", b"Sample Load", r.syms["stream_body"], 0x5555)]
    assert masks(r, r.syms["stream_bits"]) == (MASK & 0xffffffff, MASK >> 32) and r.var("stream_busy") == 1
    data, n = r.frame(0x6b, 1 << 40, 18)
    r.log.clear()
    r.mc.call(r.syms["stream_sysex"], data, n, 4)
    assert r.log == []                          # one queued already: the slot joins it
    assert masks(r, r.syms["stream_bits"]) == (MASK & 0xffffffff, (MASK >> 32) | 1 << 8)


def test_other_frames_go_on_as_before(stream):
    r = rig(stream)
    data, n = r.frame(0x6a, MASK, 18)
    r.mc.w32(r.syms["phone_state"], 1)
    r.log.clear()
    r.mc.call(r.syms["stream_sysex"], data, n, 2)
    assert r.log == [("give",)] and r.var("wipe_on") == 1
    data, n = r.frame(0x70, 0, 6)
    r.log.clear()
    r.mc.call(r.syms["stream_sysex"], data, n, 2)
    assert [e[0] for e in r.log] == ["handle"] and r.var("stream_busy") == 0


def test_the_job_keeps_a_take_not_saved_loads_the_rest_and_takes_what_comes_meanwhile(stream):
    r = rig(stream)
    mc = r.mc
    put = put_of(r, stream)
    late = [1 << 5]

    def asked(slot, off):
        r.log.append(("put", slot, off))
        mc.w32(KEEP_FRAMES, 900 if slot == 33 else 0)
        return 1

    def load(all, progress):
        r.log.append(("load", masks(r, r.syms["phone_mask"]), r.var("stream_now"), all, progress))
        if late:                                # a 0x6B while the first reload runs
            mc.w32(r.syms["stream_bits"], mc.r32(r.syms["stream_bits"]) | late.pop())
    r.stub(put, asked)
    r.stub(r.syms["load_slots"], load)
    mc.uc.ctl_flush_tb()
    mc.w32(r.syms["stream_bits"], MASK & 0xffffffff)
    mc.w32(r.syms["stream_bits"] + 4, MASK >> 32)
    mc.w32(r.syms["stream_busy"], 1)
    r.log.clear()
    assert mc.call(r.syms["stream_body"], 0) == 0
    kept = MASK & ~(1 << 33)
    assert r.log == [("put", s, 0) for s in SLOTS] + [("load", (kept & 0xffffffff, kept >> 32), 1, 0, 0),
                                                      ("put", 5, 0), ("load", (1 << 5, 0), 1, 0, 0)]
    assert masks(r, r.syms["stream_bits"]) == (0, 0) and masks(r, r.syms["phone_mask"]) == (0, 0)
    assert r.var("stream_busy") == 0 and r.var("stream_now") == 0


@pytest.mark.parametrize("now", [1, 0])
def test_the_loader_in_a_reload_reads_the_named_slots_alone(stream, now):
    r = rig(stream)
    mc = r.mc
    put = put_of(r, stream)
    r.stub(put, lambda slot, off: r.log.append(("put", slot, off)) or 1)
    r.stub(STORE_READ, lambda store, sector, nbytes, where: r.log.append(("read", sector)) or 0)
    mc.w32(KEEP_FRAMES, 0)
    mc.uc.ctl_flush_tb()
    mc.w32(r.syms["phone_mask"], 1 << 2)
    mc.w32(r.syms["phone_mask"] + 4, 1 << 1)
    mc.w32(r.syms["stream_now"], now)
    r.log.clear()
    mc.call(r.syms["load_slots"], 0, 0)
    named = [e for e in r.log if e[0] == "read" or e[1] & KEEP_PUT]
    assert named == [("read", 8192 + 2048 * 2), ("put", 2 | KEEP_PUT, KEEP_DONE), ("read", 8192 + 2048 * 33), ("put", 33 | KEEP_PUT, KEEP_DONE)]
    asked = [e[1] for e in r.log if e[0] == "put" and not e[1] & KEEP_PUT]
    assert asked == ([] if now else [s for s in range(64) if s not in (2, 33)])


def test_the_image(official_path, stream):
    quiet = lambda s: None
    new = build.build(official_path, log=quiet, xfade=78)[2]
    was = build.build(official_path, log=quiet, xfade=77)[2]
    assert new.section(7) == was.section(7) and new.section(3) == stream[0]
    spans = [mm.CAVE_PHONE, mm.CAVE_PHONE2, mm.CAVE_PHONE3, mm.CAVE_FRESH, mm.CAVE_NEWPROJ, mm.CAVE_NEWPROJ2, mm.CAVE_WIPE,
             mm.CAVE_WIPE2, mm.CAVE_BANK, mm.CAVE_KEEP, mm.CAVE_SCRATCH, mm.CAVE_SCRATCH2, mm.CAVE_SCRATCH3, mm.CAVE_SCRATCH4,
             mm.CAVE_SCRATCH5, mm.CAVE_SCRATCH6, mm.CAVE_STREAM, mm.CAVE_STREAM2, mm.CAVE_STREAM3, mm.CAVE_STREAM4]
    calls = [(a + 2, a + 6) for a in (mm.PROJECT_LOAD_CALL, mm.SYSEX_IN_JMP)]
    n, o = new.section(3), was.section(3)
    inside = lambda a: any(lo <= a < hi for lo, hi in spans)
    pointer = lambda k: any(inside(int.from_bytes(o[j:j + 4], "big")) and inside(int.from_bytes(n[j:j + 4], "big"))
                            for j in range(k - 3, k + 1))
    moved = [hex(mm.BASE + k) for k in range(len(n)) if n[k] != o[k] and not inside(mm.BASE + k)
             and not any(lo <= mm.BASE + k < hi for lo, hi in calls) and not pointer(k)]
    assert moved == []
    for a, sym in ((mm.PROJECT_LOAD_CALL, "stream_load"), (mm.SYSEX_IN_JMP, "stream_sysex")):
        assert n[mm.off(a + 2):mm.off(a + 6)] == stream[1][sym].to_bytes(4, "big")
