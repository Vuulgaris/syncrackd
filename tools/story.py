"""A build's story: its trace and a player that scrubs through it like a video.

`python -m tools.build ... X` writes build/trace/X.json and build/story/X.html after the image; `python -m tools.story
X [BASE]` renders the player again (after `make check`, to take the tests). Both are under build/, gitignored: the
trace holds stock bytes and their listing (rule 2). Never publish the player: it shows Elektron code.
"""

import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

from . import fw
from . import disasm as dis

TRACE = os.path.join("build", "trace")
STORY = os.path.join("build", "story")
BASE = 0x40000400  # both sections load here (audiomap.BASE, mainmap.BASE)
LIST_MAX = 192  # bytes of a patch put through objdump
# what an image does, in plain words, for the story's headline
ABOUT = {
    "norm": {
        "line": "every recording gets turned up to just under full volume when it ends",
        "asked": "",
        "how": ["While a take records, the audio CPU watches each block and remembers the loudest moment.",
                "When the take stops, it works out how much it can turn the whole take up so that peak sits at -1 dB, at most 30 dB.",
                "It rewrites the take in place, 256 frames at the end of every audio block, about 1.25 s for a 10 s stereo take.",
                "If the main CPU asks to save the take before it is done, the answer waits, so a save always gets the louder version."],
        "unit": "How it sounds on your own takes, and that saving straight after a take saves the louder one.",
    },
    "eucl": {
        "line": "SOLO and REC stop covering the euclidean page",
        "asked": "",
        "how": ["The TRIG page has a second page, page 3, which holds the euclidean sequencer's knobs.",
                "Since the trig image, our code put SOLO and REC on knobs E and F of the TRIG page, asking only whether the track is a sampler, never which page was showing.",
                "A new check, trig_sampler, looks at which page is up first. On page 3 everything is handed back to stock."],
        "unit": "That the euclidean page's E and F are back, and SOLO and REC still sit on the first page.",
    },
    "soloend": "a step's solo lets go when its note ends",
    "scratch": "unsaved recordings survive a power-off",
    "scan": "slices and hits find the attacks in quiet takes too",
    "xcarry": "the crossfade knob picks up where it was instead of snapping back",
    "xcont": "the crossfade hand-over keeps its amount",
    "xfix": "the crossfade stops sticking on another track",
    "nofx": "no FX track mute, and recording stops writing to slow memory",
    "cut": "the lean build: the extra right-channel sends undone",
    "atrig": "analog tracks get SOLO on the TRIG page, LFO trig moves to the filter page",
    "slice": "the keys play slices of a sample",
    "ring": "a slice can ring out past its end",
}
PARENT = {"eight": "slim", "phone": "six", "long": "tlsolo", "slice": "tlsolo", "safe": "save",
          "probe17": "fltr", "slotprobe": "spread", "evtime": "fast", "evrx": "rxoff", "time": "stereo", "time12": "stereo"}


def _listing(data, addr):
    """Our objdump's listing of a few bytes at addr, as [(addr, words, text)]."""
    data = data[:LIST_MAX]
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
        f.write(data)
    try:
        out = dis.disasm(f.name, addr)
    except Exception:
        return []
    finally:
        os.unlink(f.name)
    rows = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and parts[0].strip().endswith(":"):
            rows.append([int(parts[0].strip()[:-1], 16), parts[1].strip(), " ".join(p.strip() for p in parts[2:])])
    return rows


# the chain's last stretch, oldest first (the newest images)
CHAIN = ["fast", "rxoff", "rxcap", "copy", "nodiv", "allright", "prewas", "cut", "nofx", "xfix", "xcont", "xcarry",
         "scan", "scratch", "soloend", "eucl", "norm", "atrig"]


def _engine_index():
    """Which of our source files defines each name (C functions, asm labels)."""
    out = {}
    for path in sorted(glob.glob(os.path.join("engine", "*.[cSh]"))):
        with open(path, errors="replace") as f:
            for line in f:
                bare = re.sub(r"^(CAVE\(\w+\)|__attribute__\(\(.*?\)\))\s*", "", line)
                m = re.match(r"^(\w+):", line) or re.match(r"^[A-Za-z_][\w \t\*]*?\b(\w+)\s*\([^;]*$", bare)
                if m and m.group(1) not in out and m.group(1) not in ("if", "while", "for", "switch", "return"):
                    out[m.group(1)] = path
    return out


def _bodies():
    """Each function of ours and the text of its body, from the source (C defs, asm labels): rough, for who calls whom.
    """
    out = {}
    for path in sorted(glob.glob(os.path.join("engine", "*.[cS]"))):
        with open(path, errors="replace") as f:
            name, body = None, []
            for line in f:
                bare = re.sub(r"^(CAVE\(\w+\)|__attribute__\(\(.*?\)\))\s*", "", line)
                m = re.match(r"^(\w+):", line) or re.match(r"^[A-Za-z_][\w \t\*]*?\b(\w+)\s*\([^;]*$", bare)
                if m and m.group(1) not in ("if", "while", "for", "switch", "return"):
                    if name:
                        out.setdefault(name, []).append("".join(body))
                    name, body = m.group(1), []
                elif name:
                    body.append(line)
            if name:
                out.setdefault(name, []).append("".join(body))
    return {n: "\n".join(b) for n, b in out.items()}


def _paths(t, bodies):
    """For each function new in this image, the way stock reaches it: a hook, then our calls."""
    entries = {}
    for p in t["patches"]:
        for c in p.get("calls") or []:
            entries.setdefault(c.split(".")[0], p)
    callers = {}
    for n, body in bodies.items():
        for m in set(re.findall(r"\b([A-Za-z_]\w*)\b", body)):
            if m in bodies and m != n:
                callers.setdefault(m, set()).add(n)
    out = []
    for f in t.get("newsyms", []):
        f = f.split(".")[0]
        if f not in bodies or any(o["fn"] == f for o in out) or len(out) >= 3:
            continue
        seen, queue, found = {f: None}, [f], []
        while queue and len(found) < 3:
            n = queue.pop(0)
            if n in entries:
                found.append(n)
                continue
            for c in sorted(callers.get(n, ())):
                if c not in seen and len(seen) < 400:
                    seen[c] = n
                    queue.append(c)
        for e in found or [None]:
            chain, n = [], e
            while n:
                chain.append(n)
                n = seen[n]
            hook = entries.get(e) if e else None
            out.append({"fn": f, "chain": chain if e else [f],
                        "hook": {"addr": hook["addr"], "len": hook["len"], "section": hook["section"], "status": hook["status"]} if hook else None})
    keep = [o for o in out if not any(o is not q and q["chain"][:len(o["chain"])] == o["chain"] for q in out)]
    return keep[:3]


def _wiring(t):
    """For each small patch (a hook), the functions of ours it sends stock's code to."""
    syms = sorted((a, n) for n, a in t["syms"])
    caves = [(p["addr"], p["addr"] + p["len"]) for p in t["patches"]
             if any(p["addr"] <= a < p["addr"] + p["len"] for a, _ in syms)]

    def owner(a):
        if not any(lo <= a < hi for lo, hi in caves):
            return None
        best = None
        for sa, n in syms:
            if sa <= a:
                best = n
            else:
                break
        return best

    for p in t["patches"] + t.get("dropped", []):
        p["holds"] = [n for a, n in syms if p["addr"] <= a < p["addr"] + p["len"]]
        if p["len"] > 8:
            continue
        rows = p.get("ours") or []
        found = {int(x, 16) for r in rows for x in re.findall(r"0x(40[0-9a-f]{6})", r[2])}
        words = "".join(r[1].replace(" ", "") for r in rows)
        if p["len"] == 4 and len(words) >= 8:
            found.add(int(words[:8], 16))
        p["calls"] = sorted({o for o in map(owner, found) if o})


def _key(p):
    return "%d:%x" % (p["section"], p["offset"])


def record(name, official, raw, patches, syms, parent=None):
    """Write the trace of one built image and render its player. Returns the player's path."""
    built = fw.Image(raw)
    order = parent if isinstance(parent, list) else None
    if order is not None:
        parent = PARENT.get(name) or (order[order.index(name) - 1] if name in order and order.index(name) > 0 else None)
    secs = []
    for sid in official.ids:
        o, b = official.section(sid), built.section(sid)
        secs.append({"id": sid, "name": fw.NAMES.get(sid, "?"), "size": len(o),
                     "locked": sid in fw.PROTECTED, "patchable": sid in fw.PATCHABLE,
                     "changed": sum(x != y for x, y in zip(o, b)),
                     "sha_official": fw.sha256(o), "sha_built": fw.sha256(b)})
    pl = []
    for p in patches:
        addr = BASE + p.offset
        pl.append({"section": p.section, "offset": p.offset, "addr": addr, "len": len(p.new), "note": p.note,
                   "hash": hashlib.sha1(p.new).hexdigest()[:12],
                   "stock": _listing(p.stock, addr), "ours": _listing(p.new, addr)})
    sym = sorted(([k, v] for k, v in (syms or {}).items() if isinstance(v, int)), key=lambda kv: kv[1])
    trace = {"name": name, "parent": parent, "version": official.version,
             "sha_official": fw.sha256(official.raw), "sha_built": fw.sha256(raw), "size": len(raw),
             "sections": secs, "patches": pl, "syms": sym}
    os.makedirs(TRACE, exist_ok=True)
    with open(os.path.join(TRACE, name + ".json"), "w") as f:
        json.dump(trace, f)
    return render(name)


def _tests(name):
    path = os.path.join(TRACE, name + ".tests.xml")
    if not os.path.exists(path):
        return None
    cases = []
    for c in ET.parse(path).getroot().iter("testcase"):
        bad = c.find("failure") if c.find("failure") is not None else c.find("error")
        cases.append({"name": c.get("name"), "time": float(c.get("time") or 0),
                      "ok": bad is None and c.find("skipped") is None,
                      "skipped": c.find("skipped") is not None,
                      "msg": (bad.get("message") or "")[:300] if bad is not None else ""})
    return cases


def render(name, base=None, public=False):
    """public: no stock bytes or listing anywhere in it, the only story that may leave the machine (rule 2)."""
    with open(os.path.join(TRACE, name + ".json")) as f:
        t = json.load(f)
    base = base or t.get("parent")
    prev = None
    if base and os.path.exists(os.path.join(TRACE, base + ".json")):
        with open(os.path.join(TRACE, base + ".json")) as f:
            prev = json.load(f)
    t["base"] = base
    t["base_traced"] = prev is not None
    if prev is not None:
        had = {_key(p): p for p in prev["patches"]}
        now = {_key(p) for p in t["patches"]}
        for p in t["patches"]:
            k = _key(p)
            p["status"] = "kept" if k in had and had[k]["hash"] == p["hash"] else "changed" if k in had else "new"
            if p["status"] == "changed":
                p["was"] = had[k]["ours"]
        t["dropped"] = [dict(p, status="dropped") for p in prev["patches"] if _key(p) not in now]
    else:
        for p in t["patches"]:
            p["status"] = "new"
        t["dropped"] = []
    t["tests"] = _tests(name)
    about = ABOUT.get(name, "")
    t["about"] = about if isinstance(about, dict) else {"line": about} if about else {}
    _wiring(t)
    index = _engine_index()
    t["symfile"] = {n: index[n.split(".")[0]] for n, _ in t["syms"] if n.split(".")[0] in index}
    t["newsyms"] = [n for n, _ in t["syms"] if prev is not None and n not in {m for m, _ in prev["syms"]}]
    t["paths"] = _paths(t, _bodies())
    for path in t["paths"]:
        for n in path["chain"]:
            t["symfile"].setdefault(n, index.get(n, ""))
    if name in CHAIN:
        i = CHAIN.index(name)
        t["chain"] = [{"name": n, "line": (ABOUT.get(n) or {}).get("line", "") if isinstance(ABOUT.get(n), dict) else ABOUT.get(n, "")}
                      for n in CHAIN[max(0, i - 4):i + 2]]
    if public:
        for p in t["patches"] + t["dropped"]:
            p["stock"], p["ours"] = [], []  # ours too: a hook can carry stock's displaced instructions
            p.pop("was", None)
        t["public"] = True
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "story.html")) as f:
        page = f.read()
    page = page.replace("/*TRACE*/null", json.dumps(t).replace("</", "<\\/"))
    if public:  # the artifact's skeleton is its own
        for tag in ("<!doctype html>", '<html lang="en">', "<head>", "</head>", "<body>", "</body>", "</html>"):
            page = page.replace(tag, "", 1)
        page = page.replace("<title>Build Story</title>", "<title>Syntakt %s build</title>" % name, 1)
    os.makedirs(STORY, exist_ok=True)
    out = os.path.join(STORY, name + (".public" if public else "") + ".html")
    with open(out, "w") as f:
        f.write(page)
    return out


if __name__ == "__main__":
    pub = "--public" in sys.argv
    a = [x for x in sys.argv[1:] if x != "--public"]
    out = render(a[0], a[1] if len(a) > 1 else None, public=pub)
    print("story: %s" % out)
    if os.environ.get("OPEN") and sys.platform == "darwin":
        subprocess.run(["open", out])
