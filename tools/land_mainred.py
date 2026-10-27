"""Main-red carry-over for tools/land.py (D-889 addendum 2, user approval 2026-10-27, robot-56's conditions).

On 2026-10-27 main was red in 7 of 10 main checks (00:00-05:40) and every landing in that window threw away its
pretest. A NEW failure now does not stop a landing when every condition holds; anything else stops as before:

1. A D-790 main run on the exact main the candidate merged (``merge-base HEAD main``) failed the id with the same
   fingerprint (exception type, location, first ``E`` line). ``land_checks.main_red`` records it here.
2. The branch's own selection (merged main..candidate) does not reach the id's test file and is not FULL (gate
   tools, conftest and fixtures escalate to FULL).
3. Never a collection or setup error: only a failed test call carries.
4. Never a safety id (``safety_review.is_safety``) or an OMX one (any path naming omx: the arm owner's tests
   live in many folders).
5. The red is at most ``MAX_AGE_S`` old, carried at most ``MAX_CARRIES`` times, and has an owner
   (``python tools/land_mainred.py own <id> <owner>``).
6. A carrying landing writes no land record and saves ``land_full`` as ``carried``: pre-push, publish_main and a
   restarted run never count it green. A carry stays with its invocation until a later round passes that
   invocation cleanly (``passed``). Carries and closes are written only after the fast-forward (``landed``), against
   the commit that landed: a stopped landing leaves neither. Every later selection runs the open ids (``extra``); a clean pass on a
   candidate closes the carried landings in that candidate's history, and the red once its main is there too.
7. Each event is one JSON line in ``<git-common-dir>/rosy-main-red.jsonl``:
     red    id, main, fp, env, by     the main run failed ``id`` on ``main``
     own    id, owner
     carry  id, main, sha, branch, why
     close  id, sha, covers           a clean pass at ``sha``; ``covers`` the carries in its history

``ROSY_LAND_MAINRED_CARRY=0`` turns carrying off (the records and the extra runs stay). Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

FILE = "rosy-main-red.jsonl"
SWITCH = "ROSY_LAND_MAINRED_CARRY"
MAX_AGE_S, MAX_CARRIES = 6 * 3600, 5
SECTION = re.compile(r"^_{3,} (.+?) _{3,}$", re.M)
LOCATION = re.compile(r"^(\S+\.py):(\d+): (\w[\w.]*)$", re.M)
CARRIED: list[tuple[str, str, str, tuple[str, ...]]] = []  # (id, main, why, invocation): no land record while set
PASSES: list[tuple[str, str]] = []  # (id, tested head) PASSED in a -rA run: closed after the fast-forward


def _git(wt: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(wt), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace")


def path(wt: Path) -> Path:
    common = _git(wt, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
    return Path(common) / FILE


def read(wt: Path) -> list[dict]:
    try:
        lines = path(wt).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and isinstance(row.get("id"), str):
            rows.append(row)
    return rows


def write(wt: Path, event: str, **fields) -> None:
    line = json.dumps({"t": round(time.time(), 3), "event": event, **fields}, ensure_ascii=False) + "\n"
    with open(path(wt), "a", encoding="utf-8") as out:
        out.write(line)


def fingerprint(text: str, nodeid: str) -> str | None:
    """``exception|path:line|first E line`` of ``nodeid``'s one failure section; None when absent or ambiguous."""
    if "::" not in nodeid:
        return None
    title = nodeid.split("::", 1)[1].replace("::", ".")
    heads = list(SECTION.finditer(text))
    blocks = [text[h.end():(heads[i + 1].start() if i + 1 < len(heads) else len(text))]
              for i, h in enumerate(heads) if h.group(1) == title]
    if len(blocks) != 1:
        return None
    block = blocks[0].split("\n=====", 1)[0]
    first = next((ln.strip() for ln in block.splitlines() if ln.startswith("E ")), None)
    where = LOCATION.findall(block)
    if not first or not where:
        return None
    file, line, exc = where[-1]
    return f"{exc}|{file}:{line}|{first}"


def merged_main(wt: Path, head: str = "HEAD") -> str:
    return _git(wt, "merge-base", head, "main").stdout.strip()


def red(wt: Path, main: str, ids: list[str], text: str, env: list[str], by: str) -> None:
    """Record ids a main run failed (land_checks.main_red), each with its fingerprint (None: never carries)."""
    for nodeid in ids:
        write(wt, "red", id=nodeid, main=main, fp=fingerprint(text, nodeid), env=env, by=by)


def known(wt: Path, main: str, ids: list[str]) -> bool:
    """Every id already has a red record with a fingerprint on ``main``: the main run need not repeat."""
    have = {r["id"] for r in read(wt) if r["event"] == "red" and r.get("main") == main and r.get("fp")}
    return bool(ids) and set(ids) <= have


def _ancestor(wt: Path, a: str, b: str) -> bool:
    return _git(wt, "merge-base", "--is-ancestor", a, b).returncode == 0


def state(wt: Path, rows: list[dict] | None = None) -> dict[str, dict]:
    """Open ids: first red time, owner, env, red mains, carries not yet covered by a close."""
    rows = read(wt) if rows is None else rows
    out: dict[str, dict] = {}
    for r in rows:
        s = out.setdefault(r["id"], {"since": None, "owner": None, "env": [], "mains": [], "carries": [],
                                     "closes": []})
        if r["event"] == "red":
            s["since"] = s["since"] or r["t"]
            s["mains"].append(r.get("main"))
            s["env"] = r.get("env") or s["env"]
        elif r["event"] == "own":
            s["owner"] = r.get("owner")
        elif r["event"] == "carry":
            s["carries"].append(r)
        elif r["event"] == "close":
            s["closes"].append(r)
            if s["mains"] and _ancestor(wt, s["mains"][-1], r["sha"]):  # healed: a later red starts a new clock
                s["since"], s["mains"] = None, []
    for nodeid, s in list(out.items()):
        covered = {sha for c in s["closes"] for sha in c.get("covers", [])}
        s["carries"] = [c for c in s["carries"] if c["sha"] not in covered]
        if not s["mains"] and not s["carries"]:
            del out[nodeid]
    return out


def extra(wt: Path) -> list[list[str]]:
    """Ids a landing carried and no pass has covered yet, as invocations grouped by opt-in env, with ``-rA`` so
    each one's PASSED line is in the log (a skipped or deselected id closes nothing). Every selection runs them."""
    if os.environ.get(SWITCH) == "0":
        return []
    groups: dict[tuple[str, ...], list[str]] = {}
    for nodeid, s in sorted(state(wt).items()):
        if s["carries"]:
            groups.setdefault(tuple(s["env"]), []).append(nodeid)
    return [[*env, "-rA", *ids] for env, ids in groups.items()]


def close(wt: Path, text: str, head: str) -> list[str]:
    """Open ids a clean log at ``head`` reports PASSED; ``landed`` closes them once this landing is on main."""
    done = [nodeid for nodeid in state(wt) if re.search(rf"^PASSED {re.escape(nodeid)}\s*$", text, re.M)]
    PASSES.extend((nodeid, head) for nodeid in done if (nodeid, head) not in PASSES)
    return done


def passed(inv: list[str]) -> None:
    """A later round passed this invocation cleanly: its earlier carry no longer holds this landing back."""
    CARRIED[:] = [c for c in CARRIED if c[3] != tuple(inv)]


def carry(wt: Path, new: list[str], text: str, candidate: str, branch: str, *, safety, select,
          now: float | None = None, inv: list[str] = ()) -> tuple[list[str], str]:
    """(ids, why) when every NEW id may be carried under conditions 1-5, else ([], why not).

    ``safety(ids)`` returns the safety ids; ``select(base, head)`` the selector's JSON for base..head."""
    if os.environ.get(SWITCH) == "0":
        return [], f"main-red carry-over is off ({SWITCH}=0)"
    if not new:
        return [], "no NEW id to carry"
    now, main, rows = time.time() if now is None else now, merged_main(wt, candidate), read(wt)
    if [i for i in new if "::" not in i or f"ERROR {i}" in text]:
        return [], "a collection or setup error never carries"
    if safety(new) or [i for i in new if "omx" in i.split("::", 1)[0].lower()]:
        return [], "a safety or OMX arm id never carries"
    sel = select(main, candidate)
    if sel.get("mode") == "full":
        return [], "this branch's own selection is FULL (gate tools, conftest, fixtures): it may own the red"
    reach = [p.split("::", 1)[0].rstrip("/") for run in sel.get("invocations", []) for p in run if not p.startswith("-")]
    opened = state(wt, rows)
    for nodeid in new:
        file = nodeid.split("::", 1)[0]
        fp = fingerprint(text, nodeid)
        recorded = {r.get("fp") for r in rows if r["event"] == "red" and r["id"] == nodeid and r.get("main") == main}
        if not fp or fp not in recorded:
            return [], f"{nodeid}: no main run on {main[:10]} with this failure's fingerprint"
        if any(file == p or file.startswith(p + "/") for p in reach):
            return [], f"{nodeid}: this branch's own selection reaches {file}"
        s = opened.get(nodeid, {})
        if now - (s.get("since") or now) > MAX_AGE_S or len(s.get("carries", [])) >= MAX_CARRIES:
            return [], f"{nodeid}: red over {MAX_AGE_S // 3600} h or carried {MAX_CARRIES} times: fix main"
        if not s.get("owner"):
            return [], f"{nodeid}: no owner (python tools/land_mainred.py own '{nodeid}' <owner>)"
    why = f"main {main[:10]} fails them alike; selection does not reach them; owners {sorted({opened[i]['owner'] for i in new})}"
    CARRIED.extend((nodeid, main, why, tuple(inv)) for nodeid in new)
    return list(new), why


def landed(wt: Path, sha: str, branch: str) -> list[str]:
    """After the fast-forward only, ``sha`` being the commit main now holds: this run's closes, then its carries.

    A close names the tree that passed (its ``sha``, which also heals a red main in that tree's history) and covers
    only carries in both that tree and the landed one: a carry that reached main after the pass, or a run of the fix
    alone, covers nothing. Returns the carried ids."""
    for nodeid, head in PASSES:
        opened = state(wt)
        if nodeid in opened and _ancestor(wt, head, sha):
            write(wt, "close", id=nodeid, sha=head, landed=sha, covers=[
                c["sha"] for c in opened[nodeid]["carries"] if _ancestor(wt, c["sha"], head) and _ancestor(wt, c["sha"], sha)])
    first = {nodeid: (main, why) for nodeid, main, why, _ in reversed(CARRIED)}  # one carry per id per landing
    for nodeid, (main, why) in sorted(first.items()):
        write(wt, "carry", id=nodeid, main=main, sha=sha, branch=branch, why=why)
    return sorted(first)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    own = sub.add_parser("own", help="name who fixes a red id (condition 5)")
    own.add_argument("id")
    own.add_argument("owner")
    sub.add_parser("status", help="open red ids")
    args = parser.parse_args(argv)
    wt = Path.cwd()
    if args.cmd == "own":
        write(wt, "own", id=args.id, owner=args.owner)
        return 0
    for nodeid, s in sorted(state(wt).items()):
        print(f"{nodeid}  owner {s['owner'] or '-'}  carried {len(s['carries'])}  since "
              f"{time.strftime('%m-%d %H:%M', time.localtime(s['since']))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
