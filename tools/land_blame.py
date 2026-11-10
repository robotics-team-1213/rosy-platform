"""Which landings could have turned a MAIN-RED id red (2026-11-09 landing panel). Read-only and advisory.

Nobody named the landing that broke main: a red id stopped up to 7 branches while the culprit was found by hand
from "the last green night..main". Here the anchor is the newest landing on the red main whose own passing run
covered the id's test file (a ``tests`` event with verdict ``pass`` in ``rosy-land-events.jsonl``, with the red's
opt-in env words) or a ``close`` of the id in ``rosy-main-red.jsonl``. Every landing after it on that main is a
suspect; the ones whose own main move touched the test file or its folder come first. ``land_mainred.red`` stores
the suspects with each red record; ``python tools/land_mainred.py blame <id>`` prints them. It never stops a landing.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path, PurePosixPath

EVENTS = "rosy-land-events.jsonl"
DEPTH = 5000  # main commits searched; shortcut: older landings are not suspects, raise it if a red sat that long
MAX_SUSPECTS = 15
SCAN = 200  # landings after the anchor whose files are read; shortcut: a red older than that names only these


def _git(wt: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(wt), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace").stdout.strip()


def covers(argv: list[str], nodeid: str, env: list[str]) -> bool:
    """``argv`` ran ``nodeid``: it names the id, its file or a folder above it, carries ``env`` and ignores neither."""
    words = [w for w in argv if not w.startswith("-")]
    if not set(env) <= set(words):
        return False
    file = nodeid.split("::", 1)[0]

    def under(p: str) -> bool:
        p = p.rstrip("/")
        return file == p or file.startswith(p + "/")
    if any(w.startswith("--ignore=") and under(w[9:]) for w in argv):
        return False
    return any(w == nodeid or ("::" not in w and "=" not in w and under(w)) for w in words)


def suspects(wt: Path, nodeid: str, red_main: str, env: list[str] = (), closes: list[str] = ()) -> dict:
    """{"green": sha or None, "green_branch", "suspects": [{branch, sha, touches}]}: file touchers, folder, rest."""
    common = Path(_git(wt, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    on_main = _git(wt, "rev-list", f"--max-count={DEPTH}", red_main).split()
    if not on_main:
        raise ValueError(f"red main {red_main!r} is not a commit here")
    order = {sha: i for i, sha in enumerate(reversed(on_main))}  # oldest first
    landed, passed = [], set()
    try:
        with open(common / EVENTS, encoding="utf-8", errors="replace") as lines:
            for line in lines:
                if '"landed"' not in line and '"pass"' not in line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get("event") == "landed" and row.get("sha") in order:
                    landed.append(row)
                elif row.get("event") == "tests" and row.get("verdict") == "pass" \
                        and covers(row.get("argv") or [], nodeid, list(env)):
                    passed.add(row.get("branch"))
    except OSError:
        pass
    landed.sort(key=lambda r: order[r["sha"]])
    marks = {order[s]: None for s in closes if s in order}
    marks.update({order[r["sha"]]: r.get("branch") for r in landed if r.get("branch") in passed})
    floor = max(marks, default=None)
    file = nodeid.split("::", 1)[0]
    folder = str(PurePosixPath(file).parent)
    rows = []
    # No anchor: only the newest landings are worth naming. With one: every landing after it, the touchers kept
    # first when the list is cut (review 2026-11-09: cutting by age dropped the likeliest culprit).
    keep = len(landed) - (MAX_SUSPECTS if floor is None else SCAN)
    for i, r in enumerate(landed):
        if floor is not None and order[r["sha"]] <= floor or i < keep:
            continue
        changed = _git(wt, "diff", "--name-only", landed[i - 1]["sha"], r["sha"]).splitlines() if i else []
        touches = "file" if file in changed else "folder" if any(c.startswith(folder + "/") for c in changed) else ""
        rows.append({"branch": r.get("branch"), "sha": r["sha"], "touches": touches})
    rows.sort(key=lambda r: ("file", "folder", "").index(r["touches"]))  # stable: time order within each group
    rows = rows[:MAX_SUSPECTS]
    oldest_first = on_main[::-1]
    return {"green": oldest_first[floor] if floor is not None else None, "green_branch": marks.get(floor),
            "suspects": rows}


def line(nodeid: str, found: dict) -> str:
    """One line for a stop message or the CLI."""
    since = f"since {found['green'][:10]}" if found.get("green") else "no passing run in the log"
    names = [f"{s['branch']}{'*' if s['touches'] == 'file' else '+' if s['touches'] else ''}" for s in found["suspects"]]
    return f"MAIN-RED {nodeid} suspects ({since}; * touched the file, + its folder): {', '.join(names) or 'none'}"
