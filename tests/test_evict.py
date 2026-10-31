"""The evict image (engine/keeptakes.c and engine/scratch.c, EVICT): the stream image with the phone's reload (0x6B)
loading every slot it names, a take not saved there or not.


The load drops the take as LOAD PROJECT's always did (the audio CPU
counts a slot loaded from the drive as kept); and since the scratch image holds a take not saved in a place on the drive,
which a save copies into the bank and a start sends back to its slot, the slots named lose their places first.
  - the job loads the slots named, a take in one or not, after their places are dropped;
  - scratch_forget: the places of the slots in the phone's mask emptied on the drive, the rest kept; nothing written
    when none is theirs, nor for another bank's table;
  - the image: the stream image's but for the reload's runs and the new one.
Emulation only."""
import shutil

import pytest

import test_scratch as S
import test_stream as T
from tools import build, build_main
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")


@pytest.fixture(scope="module")
def evict(official):
    return build_main.patched_image(official.section(3), xfade=79)


def test_the_job_loads_every_slot_named_a_take_in_it_or_not(evict):
    r = T.rig(evict)
    mc = r.mc

    def load(all, progress):
        r.log.append(("load", T.masks(r, r.syms["phone_mask"]), r.var("stream_now"), all, progress))
    r.stub(r.syms["scratch_forget"], lambda: r.log.append(("forget", T.masks(r, r.syms["phone_mask"]))))
    r.stub(r.syms["load_slots"], load)
    mc.uc.ctl_flush_tb()
    mc.w32(T.KEEP_FRAMES, 900)                  # every slot holds a take the drive does not have
    mc.w32(r.syms["stream_bits"], T.MASK & 0xffffffff)
    mc.w32(r.syms["stream_bits"] + 4, T.MASK >> 32)
    mc.w32(r.syms["stream_busy"], 1)
    r.log.clear()
    assert mc.call(r.syms["stream_body"], 0) == 0
    named = (T.MASK & 0xffffffff, T.MASK >> 32)
    assert r.log == [("forget", named), ("load", named, 1, 0, 0)]
    assert T.masks(r, r.syms["stream_bits"]) == (0, 0) and T.masks(r, r.syms["phone_mask"]) == (0, 0)
    assert r.var("stream_busy") == 0 and r.var("stream_now") == 0


def forget(evict, drive_bank, places, slots, bank=0):
    r = S.Rig(evict, bank)
    r.drive[S.TABLE] = S.table(drive_bank, places)
    mask = sum(1 << s for s in slots)
    r.mc.w32(mm.CAVE_PHONE[0], mask & 0xffffffff)
    r.mc.w32(mm.CAVE_PHONE[0] + 4, mask >> 32)
    r.writes.clear()
    r.run("scratch_forget")
    return r


def test_the_slots_named_lose_their_places_the_rest_keep_theirs(evict):
    r = forget(evict, 0, {0: 33, 1: 7, 2: 5, 46: 63}, (5, 33, 63, 40))
    assert r.writes == [S.TABLE] and S.read_table(r) == (0, {1: 7}) and not r.stray


def test_nothing_written_when_no_place_is_theirs(evict):
    r = forget(evict, 0, {1: 7}, (5, 33))
    assert r.writes == [] and S.read_table(r) == (0, {1: 7})


def test_another_banks_table_is_left(evict):
    r = forget(evict, 1, {0: 33}, (33,))
    assert r.writes == [] and S.read_table(r) == (1, {0: 33})


def test_the_image(official_path, evict):
    quiet = lambda s: None
    new = build.build(official_path, log=quiet, xfade=79)[2]
    was = build.build(official_path, log=quiet, xfade=78)[2]
    assert new.section(7) == was.section(7) and new.section(3) == evict[0]
    spans = [mm.CAVE_STREAM, mm.CAVE_STREAM3, mm.CAVE_EVICT]
    n, o = new.section(3), was.section(3)
    moved = [hex(mm.BASE + k) for k in range(len(n)) if n[k] != o[k] and not any(lo <= mm.BASE + k < hi for lo, hi in spans)]
    assert moved == []
    assert n[mm.off(mm.CAVE_EVICT[0]):mm.off(mm.CAVE_EVICT[1])] != o[mm.off(mm.CAVE_EVICT[0]):mm.off(mm.CAVE_EVICT[1])]
