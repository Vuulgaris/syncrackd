"""push.command: add, commit and push everything, and never Elektron firmware."""
import os
import shutil
import subprocess

import pytest
from tools import fw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
pytestmark = pytest.mark.skipif(not shutil.which("git"), reason="no git")


def git(cwd, *args):
    return subprocess.run(("git",) + args, cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture()
def repo(tmp_path):
    """A clone of an empty origin with the script in it and one commit pushed."""
    origin, work = tmp_path / "origin.git", tmp_path / "work"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    git(tmp_path, "clone", "-q", str(origin), str(work))
    for k, v in (("user.name", "t"), ("user.email", "t@example.invalid"), ("commit.gpgsign", "false")):
        git(work, "config", k, v)
    shutil.copy(os.path.join(ROOT, "push.command"), work / "push.command")
    git(work, "checkout", "-q", "-b", "main")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "first")
    git(work, "push", "-q", "-u", "origin", "main")
    return work, origin


def run(work, *args):
    return subprocess.run(("./push.command",) + args, cwd=work, capture_output=True, text=True, stdin=subprocess.DEVNULL)


def test_it_commits_what_is_new_and_pushes(repo):
    work, origin = repo
    (work / "notes.md").write_text("a finding\n")
    (work / "sub").mkdir()
    (work / "sub" / "code.py").write_text("x = 1\n")
    done = run(work)
    assert done.returncode == 0 and "Pushed" in done.stdout
    assert git(work, "status", "--porcelain") == ""
    assert git(origin, "rev-parse", "main") == git(work, "rev-parse", "HEAD")
    assert set(git(origin, "ls-tree", "-r", "--name-only", "main").split()) == {"notes.md", "push.command", "sub/code.py"}
    assert git(work, "log", "-1", "--format=%s").startswith("Snapshot ")
    assert "Co-Authored" not in git(work, "log", "-1", "--format=%B")
    again = run(work)  # nothing new: no empty commit
    assert again.returncode == 0 and "Nothing new" in again.stdout
    assert git(work, "rev-list", "--count", "HEAD") == "2"


@pytest.mark.parametrize("name", ["Syntakt_OS1.42.syx", "x.SYX", "sections/sec3.bin", "firmware/readme.txt", "build/a.txt",
                                  "dis.lst", "take.wav", "ref/notes.md"])
def test_it_refuses_firmware_and_what_is_made_from_it(repo, name):
    work, origin = repo
    (work / "fine.md").write_text("ok\n")
    path = work / name
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(fw.sb("c0e310a82f54172c"))
    before = git(origin, "rev-parse", "main")
    done = run(work)
    assert done.returncode == 1 and "Refused" in done.stdout and name in done.stdout
    assert git(origin, "rev-parse", "main") == before == git(work, "rev-parse", "HEAD")  # no commit, no push
    assert git(work, "diff", "--cached", "--name-only") == ""  # and nothing left staged


def test_check_changes_nothing(repo):
    work, origin = repo
    (work / "notes.md").write_text("a finding\n")
    before = git(work, "rev-parse", "HEAD")
    done = run(work, "--check")
    assert done.returncode == 0 and "Would commit" in done.stdout and "notes.md" in done.stdout
    assert git(work, "rev-parse", "HEAD") == before == git(origin, "rev-parse", "main")
    assert git(work, "diff", "--cached", "--name-only") == ""


def test_it_only_pushes_main(repo):
    work, origin = repo
    git(work, "checkout", "-q", "-b", "side")
    (work / "notes.md").write_text("a finding\n")
    done = run(work)
    assert done.returncode == 1 and "not main" in done.stdout
    assert git(work, "status", "--porcelain") != ""
