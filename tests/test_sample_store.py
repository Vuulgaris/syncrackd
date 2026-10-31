"""Where the 5 second limit lives: the main CPU's sample store. Section 3, OS 1.42."""
import pytest

from tools import mainmap as mm


@pytest.fixture(scope="module")
def sec3(official):
    assert official.version == "1.42"
    return official.section(3)


def code(image, addr, text):
    data = bytes.fromhex(text)
    return image[mm.off(addr):mm.off(addr) + len(data)] == data


def test_a_slot_is_1024_sectors_from_sector_8192(sec3):
    # erase: sector = (slot << 10) + 8192, count 1024
    assert code(sec3, 0x4011128a, "720a 2002 e3a8")  # moveq #10,d1 ; move.l d2,d0 ; lsl.l d1,d0
    assert code(sec3, 0x401112a0, "4878 0400") and mm.SAMPLE_SECTORS == 0x400
    assert code(sec3, 0x401112a4, "2040 4868 2000") and mm.SAMPLE_SECTOR0 == 0x2000
    assert mm.SAMPLE_ERASE < 0x4011128a < mm.SAMPLE_SIZE
    # scan: one sector from the same place, for the header
    assert code(sec3, 0x4011150a, "4878 0200") and code(sec3, 0x4011150e, "2040 4868 2000")
    assert mm.SAMPLE_SECTORS * 512 == 0x80000 and mm.SAMPLE_SECTOR0 * 512 == 0x400000


def test_a_slot_whose_header_claims_more_than_fits_is_left_empty(sec3):
    assert code(sec3, 0x4011154e, "203c 5341 4d50 b0af 0030 667c")  # 'SAMP' against header + 0, or out
    assert code(sec3, 0x4011155a, "206f 0038")  # frames: header + 8
    assert code(sec3, 0x40111574, "263c 0007 ffc0")  # 2 * frames against 524,224
    assert code(sec3, 0x4011157e, "6256")  # higher: out, by the same exit as a bad magic
    assert 0x40111558 + 2 + 0x7c == 0x4011157e + 2 + 0x56 == 0x401115d6
    assert 2 * mm.SAMPLE_MAX_FRAMES == 0x7ffc0 == mm.SAMPLE_SECTORS * 512 - mm.SAMPLE_HEADER
    assert code(sec3, 0x40111584, "43e9 000c")  # name: header + 12
    assert code(sec3, 0x401115b8, "d3fc 0001 2e3c 2288")  # frames into the table, entry + 20
    assert mm.SAMPLE_TABLE + 20 == 0x12e3c


def test_a_slots_size_is_its_header_and_two_bytes_a_frame(sec3):
    assert code(sec3, 0x40111472, "d1fc 0001 2e3c 2410")  # frames from the table
    assert code(sec3, 0x4011147c, "d482 0682 0000 0040")  # times 2, plus 64
    assert mm.SAMPLE_HEADER + 2 * mm.SAMPLE_MAX_FRAMES == 0x80000  # a full slot is exactly its 512 KB


def test_the_samples_route_takes_slots_1_to_64_and_never_reports_more_than_a_slot(sec3):
    def cstr(addr):
        o = mm.off(addr)
        return sec3[o:sec3.index(b"\0", o)].decode("ascii")
    assert cstr(0x40256700) == "invalid sample slot" and cstr(0x40256714) == "sample slot out of range"
    assert cstr(0x4025672d) == "/samples" and cstr(0x40256736) == "/samples/*"
    assert mm.u32(sec3, 0x400b9e3c + 2) == 0x40256700 and mm.u32(sec3, 0x400b9e54 + 2) == 0x40256714
    assert code(sec3, 0x400b9e48, "703f 2a06 5385 b085")  # slot - 1 against 63
    assert mm.u32(sec3, 0x400b9eae + 2) == mm.SAMPLE_SIZE
    assert code(sec3, 0x400b9eb6, "0c80 0007 ffff 6f04 7008 4840")  # size held to 0x80000
    assert code(sec3, 0x400b9ee6, "123c 0013") and code(sec3, 0x400b9ef4, "e3ae")
    assert code(sec3, 0x400b9f16, "0686 0038 0000")  # (slot + 7) << 19: the slot's byte offset on the drive
    assert (1 + 7) << 19 == mm.SAMPLE_SECTOR0 * 512


def test_the_drive_is_768_mb_and_the_boot_loader_walks_it_in_slot_steps(sec3):
    assert code(sec3, 0x4011166e, "0c82 0017 ffff")  # last sector
    assert code(sec3, 0x4011167c, "223c 3000 0000") and mm.DRIVE_BYTES == (0x17ffff + 1) * 512
    for addr, text in ((0x40082342, "2f3c 0008 0000"), (0x40082390, "2f3c 0008 0000"), (0x40082d32, "0680 0008 0000")):
        assert code(sec3, addr, text)
    assert mm.SAMPLE_SECTOR0 * 512 + 64 * 0x80000 <= mm.DRIVE_BYTES  # 4 MB to 36 MB


def test_the_unit_tells_the_computer_no_length_limit(sec3):
    """The capability keys Elektron Transfer asks for: formats and rates, nothing about length."""
    keys = set()
    at = 0
    while True:
        at = sec3.find(b"sample_file.", at)
        if at < 0:
            break
        keys.add(sec3[at:sec3.index(b"\0", at)].decode("ascii"))
        at += 1
    assert keys == {"sample_file.interleaved_stereo_support", "sample_file.mono_support", "sample_file.sample_rates"}


# ---- the rest of the drive: is there room after the samples ---------------------------------

STORE = (0x4010e000, 0x40113600)  # the store's own code


def operands(image, value):
    """Every place the 32-bit value stands in the image."""
    pat, at, out = value.to_bytes(4, "big"), 0, []
    while True:
        at = image.find(pat, at)
        if at < 0:
            return out
        out.append(mm.BASE + at)
        at += 1


def pc_calls(image, target, lo, hi):
    """jsr (d16,pc) instructions between lo and hi that land on target."""
    out = []
    for a in range(lo, hi, 2):
        if image[mm.off(a):mm.off(a) + 2] == b"\x4e\xba":
            d = int.from_bytes(image[mm.off(a) + 2:mm.off(a) + 4], "big", signed=True)
            if a + 2 + d == target:
                out.append(a)
    return out


def test_every_use_of_the_drive_routines_is_a_known_call(sec3):
    """No table of pointers: each address stands only as the operand of a jsr or lea we have read."""
    assert operands(sec3, mm.DRIVE_READ) == [a + 2 for a in (
        0x40081532, 0x400bb5b4, 0x400bb8c8, 0x400bbd08, 0x400bca9e, 0x400bd6e4, 0x40110100, 0x40113324, 0x40113458, 0x40113496)]
    assert operands(sec3, mm.DRIVE_WRITE) == [a + 2 for a in (
        0x400806e0, 0x400bba58, 0x400bbd8e, 0x400bcaf0, 0x400bd67c, 0x400bd6c6, 0x40111690)]
    assert operands(sec3, mm.DRIVE_ERASE) == [a + 2 for a in (0x400b644c, 0x400bc130, 0x400bd670, 0x4011019a)]
    for site in operands(sec3, mm.DRIVE_READ) + operands(sec3, mm.DRIVE_WRITE) + operands(sec3, mm.DRIVE_ERASE):
        assert sec3[mm.off(site) - 2:mm.off(site)] in (b"\x4e\xb9", b"\x45\xf9", b"\x49\xf9", b"\x4b\xf9")  # jsr, lea a2, a4, a5
    # the store's own entry points are reached by pc-relative calls only, all inside the store
    for fn in (mm.STORE_READ, mm.STORE_ERASE, mm.STORE_WRITE):
        assert operands(sec3, fn) == []
    assert pc_calls(sec3, mm.STORE_READ, *STORE) == [0x4011026c, 0x4011031c, 0x40110838, 0x4011091c, 0x401109d2,
                                                      0x40110ce8, 0x40110de4, 0x40111516, 0x40111e40, 0x40111f76]
    assert pc_calls(sec3, mm.STORE_ERASE, *STORE) == [0x401110da, 0x401112ac, 0x40111a46, 0x401129a8]
    assert pc_calls(sec3, mm.STORE_WRITE, *STORE) == [0x4011174e, 0x401117d0, 0x40111c94, 0x40111d4c, 0x40111ea6,
                                                       0x40111fd8, 0x401121e0, 0x4011246a, 0x40112d1e]


def test_where_sounds_projects_and_the_work_areas_are(sec3):
    regions = dict((name, (a, b)) for name, a, b in mm.DRIVE_MAP)
    # sounds: 2 * (2048 + n), n up to 2047
    assert code(sec3, 0x40110c6c, "0c80 0000 07ff") and code(sec3, 0x40110c7a, "0680 0000 0800 d080")
    assert regions["sounds"] == (2 * 2048, 2 * (2048 + 2047) + 2)
    assert code(sec3, 0x401110d2, "4878 0002")  # a sound is erased as 2 sectors
    # projects: (n + 64) << 13, n up to 127, and 516096 for number 128
    assert code(sec3, 0x4011075c, "243c 0007 e000") and code(sec3, 0x40110776, "0c83 0000 0080")
    assert code(sec3, 0x40110786, "727f") and code(sec3, 0x40110790, "700d 0682 0000 0040 e1aa")
    assert regions["projects"] == (64 << 13, (127 + 64 + 1) << 13) and regions["project 128"][0] == 0x7e000
    assert regions["projects"][1] * 512 == mm.DRIVE_BYTES
    # the two work areas: the only other sector numbers written out in the image
    assert code(sec3, 0x400bd6c0, "2f3c 0007 a000") and code(sec3, 0x400bd6de, "2f3c 0007 c000")
    assert regions["work area"] == (0x7a000, 0x7c000) and regions["work area 2"] == (0x7c000, 0x7e000)
    # header and table
    assert code(sec3, 0x40111746, "4878 0008 42a7") and code(sec3, 0x401117c6, "4878 0110 4878 0800")
    # samples: three ways the same sector is worked out
    assert code(sec3, 0x40113306, "123c 000a 5080") and code(sec3, 0x40113316, "e3a8")  # (slot + 8) << 10
    assert code(sec3, 0x40112464, "4868 2000")  # the store's own sample write
    assert regions["samples"] == (mm.SAMPLE_SECTOR0, mm.SAMPLE_SECTOR0 + 64 * mm.SAMPLE_SECTORS)


def test_nothing_is_kept_between_the_samples_and_the_work_areas(sec3):
    """The regions do not overlap, and the gap after the samples is 208 MB that no fixed address in the image falls in. A
    second 32 MB of samples would be sectors 73728 to 139264.
    """
    spans = sorted((a, b) for _, a, b in mm.DRIVE_MAP)
    assert all(spans[k][1] <= spans[k + 1][0] for k in range(len(spans) - 1))
    lo, hi = mm.DRIVE_FREE
    assert all(b <= lo or a >= hi for a, b in spans)
    assert (hi - lo) * 512 == 208 << 20
    assert lo + 64 * mm.SAMPLE_SECTORS <= hi
    # How this was shown: every call site in the test above was read, and its sector comes from one of 0, 2048,
    # SOUND_SECTOR, PROJECT_SECTOR, the sample arithmetic, the two work areas, an address a file route hands over
    # (projects, sound banks, samples), or a number typed at the factory test console (0x400806e0, 0x40081532). That
    # reading is in docs/FINDINGS.md; it is not re-done here.


def test_the_boot_loader_reads_a_slot_into_a_buffer_of_one_slot(sec3):
    """Not a number to change alone: with larger slots this buffer and the read after it grow with them."""
    assert code(sec3, 0x40082342, "2f3c 0008 0000") and mm.u32(sec3, 0x40082354 + 2) == 0x401036d0  # allocate 512 KB
    assert code(sec3, 0x40082390, "2f3c 0008 0000 42a7") and mm.u32(sec3, 0x4008234c + 2) == mm.SAMPLE_READ  # read up to that
    assert operands(sec3, mm.SAMPLE_READ) == [0x4008234c + 2]  # the only reader of sample data there is
    # that reader: slot (0..63) to a byte address, (slot + 8) << 19, then 64 bytes of header and the offset
    assert code(sec3, 0x401133d2, "703f") and code(sec3, 0x40113428, "7213 5084 e3ac")


def test_the_whole_pool_is_staged_in_a_fixed_32_mb_of_main_cpu_memory(sec3):
    """Why twice the samples is more than a change to the drive: at boot all 64 slots are copied, one after the other,
    into one block at a fixed address, and the audio CPU's program is staged right behind it. Nothing checks the
    total: stock cannot overrun it, larger slots could.
    """
    assert code(sec3, 0x40082a48, "203c 4d84 f2c0 4e75") and mm.u32(sec3, 0x4008233c + 2) == 0x40082a48
    assert operands(sec3, mm.POOL_STAGE) == [0x40082a48 + 2, 0x40082b64 + 2]
    assert code(sec3, 0x4008235a, "14bc ffaa")  # the marker byte
    assert code(sec3, 0x400823ca, "4872 1800") and code(sec3, 0x400823da, "4872 2809")  # count at + 5, samples at + 9
    assert code(sec3, 0x400823d0, "202f 003c d080")  # 2 bytes a frame
    assert code(sec3, 0x400823ee, "5283 7240 b283 669a")  # 64 slots, no other end to the loop
    assert code(sec3, 0x40083202, "203c 4f84 f2c1")
    assert mm.AUDIO_IMAGE_STAGE - mm.POOL_STAGE == mm.POOL_STAGE_BYTES == (32 << 20) + 1
    assert 5 + 64 * (4 + 2 * mm.SAMPLE_MAX_FRAMES) <= mm.POOL_STAGE_BYTES  # stock: every slot full still fits
    assert 5 + 64 * (4 + 2 * 480000) > mm.POOL_STAGE_BYTES  # 64 slots of 10 s would not
    assert 5 + 32 * (4 + 2 * 480000) <= mm.POOL_STAGE_BYTES  # 32 would


# ---- could the pool be twice the size: memory, the sender, the audio CPU's end -----------------

def test_main_cpu_memory_has_no_second_32_mb(sec3):
    """128 MB, and it is spoken for: the program and its data to 85 MB, then the blocks that are addressed 0x08000000
    higher (the pool's 32 MB among them), then 7 MB with the stack in it.
    """
    assert code(sec3, 0x400004f2, "2e7c 4800 0000") and mm.MAIN_STACK_TOP == 0x48000000
    assert code(sec3, 0x400004ba, "207c 4033 a000 223c 4556 6490") and mm.MAIN_BSS_END == 0x45566490
    assert code(sec3, 0x4000055e, "203c 4007 e020 4e7b 0004")  # cache on for 0x40000000..0x47ffffff only
    assert (mm.u32(sec3, 0x402d5328), mm.u32(sec3, 0x402d5338) * 16) == (mm.MAIN_HEAP[0], mm.MAIN_HEAP[1] - mm.MAIN_HEAP[0])
    assert mm.MAIN_HEAP[1] < mm.MAIN_BSS_END and mm.MAIN_HEAP[1] - mm.MAIN_HEAP[0] == 16 << 20
    lo, hi = (a - mm.UNCACHED for a in mm.UPPER_STATICS)
    assert mm.MAIN_BSS_END <= lo < hi <= mm.MAIN_STACK_TOP  # they fit between the data and the stack
    assert mm.UPPER_STATICS[0] <= mm.POOL_STAGE and mm.AUDIO_IMAGE_STAGE < mm.UPPER_STATICS[1]
    assert lo - mm.MAIN_BSS_END < 1 << 20 and mm.MAIN_STACK_TOP - hi < 8 << 20  # and leave under 8 MB either side


def test_the_sender_could_go_round_the_block_twice(sec3):
    """What a pool sent in two halves would lean on: the sender takes each chunk from the block by its index, and the
    index goes out as 16 bits, so 128 MB of chunks can be numbered.
    """
    assert code(sec3, 0x40082fb6, "2439 4d84 f2c1 0682 0000 07ff 700b e0aa")  # chunks = (length + 2047) >> 11
    assert code(sec3, 0x40082fb4, "7202") and code(sec3, 0x40082fc6, "33c1 1000 0002")  # command 2: a chunk
    assert code(sec3, 0x40082fce, "2039 41bb f424 33c0 1000 000c")  # the index, as a word
    assert code(sec3, 0x40082fda, "e3a8 4878 0800 0680 4d84 f2c5 2f00 2f3c 1000 0800")  # block + 5 + (index << 11) to the window
    assert mm.u32(sec3, 0x40082fce + 2) == mm.POOL_SEND_INDEX and mm.POOL_STAGE + 5 == 0x4d84f2c5
    # the stall count the boot code keeps while it waits: more than 18 with nothing moving is a timeout
    assert code(sec3, 0x40082970, "2039 41bb f3bc") and code(sec3, 0x40082976, "7412") and code(sec3, 0x4008297a, "b480 6d08")
    assert mm.u32(sec3, 0x40082970 + 2) == mm.BOOT_STALL


def test_the_audio_cpu_puts_a_chunk_wherever_its_index_says(official):
    """Section 7: pool + (index << 11) with the index a word, in a loop with no count and no limit. So it will wait as
    long as it takes, and it will also write past its 64 MB if it is sent more.
    """
    from tools import audiomap as m
    sec7 = official.section(7)
    at = m.off(0x40000fa8)
    assert sec7[at:at + 28] == bytes.fromhex("302a000c 720b 48780800 48780800 71c0 e3a8 06804004f750 2f00 4e93")
    assert m.POOL == 0x4004f750 and m.POOL_SIZE == 64 << 20
    assert m.POOL + m.POOL_SIZE <= m.SLOT_LEN  # the slot table is what lies right after the pool
    assert sec7[m.off(0x40000fc6):m.off(0x40000fd6)] == bytes.fromhex("302a0002 4fef000c 7203 71c0 b280 66b8")  # until command 3
