import collections
import glob
import hashlib
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tools import build_engine, fw  # noqa: E402

# under pytest-xdist each worker compiles into a directory of its own: the object files have fixed names
_worker = os.environ.get("PYTEST_XDIST_WORKER")
if _worker:
    build_engine.OUT = os.path.join(build_engine.OUT, _worker)


CHUNK = 100     # tests of one file that go to a worker together


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config, items):
    """Under pytest-xdist (--dist loadgroup) a worker takes a group at a time: a file, or CHUNK tests
    of a long one in the order they are written. The files with the most tests are given out first."""
    if not hasattr(config, "workerinput"):
        return
    count = collections.Counter(item.path for item in items)
    items.sort(key=lambda item: -count[item.path])
    seen = collections.Counter()
    for item in items:
        item.add_marker(pytest.mark.xdist_group("%s.%d" % (item.path.name, seen[item.path] // CHUNK)))
        seen[item.path] += 1


def _official_path():
    for p in sorted(glob.glob(os.path.join(ROOT, "firmware", "**", "*.syx"), recursive=True)):
        with open(p, "rb") as f:
            if hashlib.sha256(f.read()).hexdigest() in fw.KNOWN:
                return p
    return None


@pytest.fixture(scope="session")
def official_path():
    p = _official_path()
    if p is None:
        pytest.skip("no pinned official .syx in firmware/")
    return p


@pytest.fixture(scope="session")
def official(official_path):
    return fw.load(official_path)
