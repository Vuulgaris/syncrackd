"""The ask image (engine/phone.c, SEEN): the letgo image with LOAD PROJECT asking the phone only once it has said so.


The phone app says 0x63 at every connect (its backup's
whichProject), and 0x65 or 0x66 for a capture: either is the phone's hello. Here:
  - a host's message made the sink, no hello: a load is stock's straight away, where the letgo image asked and waited;
  - after 0x63, or a capture's frame, the load asks and waits as the phone image does; the viewer's 0x67 is no hello;
  - the image: only the phone's runs differ from the letgo image's, section 7 the letgo image's.
Emulation only."""
import shutil

import pytest

import test_fltr as F
import test_phone as P
from tools import build, build_main
from tools import mainmap as mm

pytestmark = pytest.mark.skipif(not shutil.which("m68k-elf-gcc"), reason="no ColdFire cross-compiler")

ASKED = ["scan", "write", "commit", "timer", "wait", "cancel", "scan", "load"]


@pytest.fixture(scope="module")
def ask(official):
    return build_main.patched_image(official.section(3), xfade=70)


@pytest.fixture(scope="module")
def letgo(official):
    return build_main.patched_image(official.section(3), xfade=69)


def load(r):
    r.log.clear()
    assert r.mc.call(r.syms["knows_load"], 0x1234, 5, 0x5678) == 7
    return [e[0] for e in r.log]


def hello(r, id):
    data, n = r.frame(id, 0, 6)
    r.mc.call(r.syms["knows_sysex"], data, n, 2)


def test_on_the_letgo_image_any_hosts_message_made_a_load_wait(letgo):
    r = F.rig(letgo, now_project=9, project_bank=2, now=0)
    r.mc.w32(P.SINK_MADE, 1)
    assert load(r) == ASKED


def test_with_no_hello_since_the_start_a_load_is_stocks_straight_away(ask):
    r = F.rig(ask, now_project=9, project_bank=2, now=0)
    r.mc.w32(P.SINK_MADE, 1)
    assert load(r) == ["load"] and r.log == [("load", 0, 0x1234, 5, 0x5678)]


@pytest.mark.parametrize("id", [0x63, 0x65, 0x66])
def test_after_the_phones_hello_a_load_asks_and_waits_as_before(ask, id):
    r = F.rig(ask, now_project=9, project_bank=2, now=0)
    r.mc.w32(P.SINK_MADE, 1)
    hello(r, id)
    assert r.var("phone_seen") == 1
    kinds = load(r)
    assert kinds == ASKED and r.log[1][1] == bytes([0xf0, 0, 0x20, 0x3c, 0x10, 0, 0, 0, 1, 0, 0, 0x60, 5, 0, 0, 2, 0xf7])


def test_the_viewers_frames_and_other_hosts_are_no_hello(ask):
    r = F.rig(ask, now_project=9, project_bank=2, now=0)
    r.mc.w32(P.SINK_MADE, 1)
    hello(r, 0x67)
    hello(r, 0x68)
    hello(r, 0x53)
    assert r.var("phone_seen") == 0 and load(r) == ["load"]


def test_0x63_is_still_answered(ask):
    r = F.rig(ask)
    r.mc.w32(P.CLOCK, 0x12345678)
    F.ask(r)
    assert r.log == [("write", F.reply(0x3fff, 0, 0, 0x145678)), ("commit",)]


def test_the_image(official_path, ask, letgo):
    quiet = lambda s: None
    new = build.build(official_path, log=quiet, xfade=70)[2]
    was = build.build(official_path, log=quiet, xfade=69)[2]
    assert new.section(7) == was.section(7) and new.section(3) == ask[0] and was.section(3) == letgo[0]
    spans = [mm.CAVE_PHONE, mm.CAVE_PHONE2, mm.CAVE_PHONE3]
    n, o = new.section(3), was.section(3)
    stray = [hex(mm.BASE + k) for k in range(len(n)) if n[k] != o[k] and not any(mm.off(a) <= k < mm.off(b) for a, b in spans)]
    assert stray == []
