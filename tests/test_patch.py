"""The user's patcher and its bundle (tools/patch.py, tools/bundle.py), on the stream image as built.

The bundle made from the built image, applied to the official file, gives the built image to the byte, with
numpy not there, and as the single file alone in a folder with no site-packages; it holds no 32-byte window of Elektron's code; and a bundle for another file, with other bytes
under its runs, touching a protected section, or giving another output, is refused.
"""
import copy
import json
import os
import shutil
import subprocess
import sys

import pytest

from tools import bundle as B
from tools import fw, patch, single

BUILT = os.path.join(B.IMAGES, "Syntakt_OS1.42_sampler_stream.syx")


@pytest.fixture(scope="module")
def built():
    if not os.path.exists(BUILT):
        pytest.skip("make image-stream first")
    with open(BUILT, "rb") as f:
        return f.read()


@pytest.fixture(scope="module")
def made(official, built):
    return json.loads(json.dumps(B.make(official, built, "stream")))


def test_the_bundle_gives_the_built_image_to_the_byte(official, built, made):
    assert patch.apply(official, made) == built


def test_without_numpy(official, built, made, monkeypatch):
    from tools import ele3
    monkeypatch.setattr(ele3, "np", None)
    assert patch.apply(official, made) == built


def test_no_window_of_elektrons_code(official, made):
    assert B.stock_windows(official, made["sections"]) == []
    assert set(made["sections"]) <= {"3", "7"}
    assert all("stock" not in r for s in made["sections"].values() for r in s["runs"])


def test_a_bundle_for_another_file(official, made):
    b = copy.deepcopy(made)
    b["input"] = "0" * 64
    with pytest.raises(fw.GuardError, match="another file"):
        patch.apply(official, b)


def test_other_bytes_under_a_run(official, made):
    b = copy.deepcopy(made)
    r = b["sections"]["3"]["runs"][0]
    r["at"] += 1
    with pytest.raises(fw.GuardError):
        patch.apply(official, b)


def test_a_protected_section(official, made):
    b = copy.deepcopy(made)
    b["sections"]["2"] = {"length": len(official.section(2)), "stock": fw.sha256(official.section(2)[:1]),
                          "runs": [{"at": 0, "new": "%02x" % (official.section(2)[0] ^ 1)}]}
    with pytest.raises(fw.GuardError, match="bootstrap|refusing"):
        patch.apply(official, b)


def test_another_output(official, made):
    b = copy.deepcopy(made)
    b["output"] = "0" * 64
    with pytest.raises(fw.GuardError, match="release's build"):
        patch.apply(official, b)


def test_never_writes_over_elektrons_file(official_path, made, tmp_path):
    p = tmp_path / "stream.json"
    p.write_text(json.dumps(made))
    assert patch.main([official_path, str(p), "-o", official_path]) == 1


def test_the_single_file_alone(official_path, built, made, tmp_path):
    (tmp_path / "p.py").write_text(single.make(made, "p.py"))
    shutil.copy(official_path, tmp_path / "os.syx")
    r = subprocess.run([sys.executable, "-I", "-S", "p.py", "os.syx", "-o", "mod.syx"], cwd=tmp_path,
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp_path / "mod.syx").read_bytes() == built
