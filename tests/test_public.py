"""The public tree (tools/export_public.py) and its guard (tools/public_check.py). Needs no firmware.

The export holds nothing the guard fails on, none of the private files, no Makefile target of the private
workflow, the docs without the hardware log or "the maintainer"; the guard fails on what it is for.
"""
import os

from tools import export_public, public_check


def test_the_export_passes_the_guard(tmp_path):
    dest = str(tmp_path / "pub")
    export_public.export(dest)
    fails, _ = public_check.check(dest)
    assert fails == []
    for p in ("tools/pick.py", "tools/claim.py", "tools/patch_transfer.py", "push.command", "docs/PUBLIC_RELEASE.md",
              "pascalproject"):
        assert not os.path.exists(os.path.join(dest, p))
    assert os.path.exists(os.path.join(dest, "CLAUDE.md")) and os.path.exists(os.path.join(dest, "site/index.html"))
    with open(os.path.join(dest, "CLAUDE.md")) as f:
        assert "syntaktphone" not in f.read()
    with open(os.path.join(dest, "Makefile")) as f:
        make = f.read()
    assert "tools.pick" not in make and "tools.claim" not in make and "push.command" not in make
    with open(os.path.join(dest, "docs/FINDINGS.md")) as f:
        findings = f.read()
    assert "the maintainer" not in findings and findings.count("## Hardware log") == 1


def test_the_guard_fails_on_what_it_is_for(tmp_path):
    (tmp_path / "a.syx").write_bytes(b"\xf0")
    (tmp_path / "b.md").write_text("x\n/" + "Users/someone/x\n" + "ab" * 20 + "\n" + "\u2014\n" + "c" * 64 + "\n")
    (tmp_path / "c.py").write_text('fw.sx("%s")\n' % ("0f" * 30))
    fails, _ = public_check.check(str(tmp_path))
    assert sorted((rel, what) for rel, _, what in fails) == [
        ("a.syx", "a file that is never published"),
        ("b.md", "a hex run of 40 characters"), ("b.md", "a home folder's path"), ("b.md", "an em dash")]
