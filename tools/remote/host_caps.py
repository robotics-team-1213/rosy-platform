"""Host capabilities: a test declares what its host must have, the probe measures it, placement routes on it.

A test module declares ``HOST_CAPABILITIES = ("learner_venv",)`` on one line. ``PROBE`` prints a ``ROSYCAPS`` line with the names
this host has (CAPABILITIES: name -> a path that must be executable there). An invocation whose paths declare a
capability only runs on hosts that have it. 2026-11-09: the pinned-learner browser test was placed on the site PC,
which had no learner venv, and stopped seven landings. Standard library only.
"""

from __future__ import annotations

import functools
import re
import subprocess
from pathlib import Path

LOST_EXIT = 255  # remote_job.LOST_EXIT: what land.py sees for an invocation that did not run
CAPABILITIES = {"learner_venv": "~/.local/share/rosy-learning-center/venv-cpu/bin/python"}  # provision: tools/remote/provision_learner_venv.sh
PROBE_LINE = "cap=; " + " ".join(f'[ -x {path} ] && cap="$cap {name}";' for name, path in CAPABILITIES.items()) + ' echo "ROSYCAPS$cap"\n'


def parse(out: str) -> frozenset[str]:
    """The capability names of PROBE output's ROSYCAPS line; empty when the host printed none (an older probe)."""
    lines = [ln.split()[1:] for ln in out.splitlines() if ln.split()[:1] == ["ROSYCAPS"]]
    return frozenset(lines[-1]) if lines else frozenset()


@functools.lru_cache(maxsize=None)
def _declared(repo: str, sha: str, paths: tuple[str, ...]) -> frozenset[str]:
    text = subprocess.run(["git", "-C", repo, "grep", "-h", "-E", r"^HOST_CAPABILITIES\s*=", sha, "--", *paths],
                          capture_output=True, text=True, errors="replace").stdout
    return frozenset(re.findall(r"""['"]([a-z_]+)['"]""", text.split("=", 1)[1] if "=" in text else ""))


def needs(repo: Path, sha: str, invocations: list[list[str]]) -> list[frozenset[str]]:
    """Per invocation, the capabilities declared by the test files or folders it names (as committed at sha)."""
    result = []
    for inv in invocations:
        paths = tuple(sorted({w.split("::")[0] for w in inv if re.fullmatch(r"[\w./-]+(::.*)?", w)}))
        result.append(_declared(str(repo), sha, paths) if paths else frozenset())
    return result


KNOWN: dict[str, frozenset[str]] = {}  # host -> the capabilities of its last reachable probe (host_probe.placed_hosts)


def room(host: str, headroom: dict) -> dict:
    """The host's placed headroom, or only its probed capabilities when it is a below-the-floor fallback host.

    2026-11-14: place() records capabilities with the headroom, and a fallback host has none. A FULL ran 100 min on
    two fallback hosts that both had the learner venv, then stopped: "no working host has it: not run"."""
    return headroom.get(host) or {"caps": KNOWN.get(host, ())}


def has(room: dict | None, need: frozenset[str]) -> bool:
    return need <= frozenset((room or {}).get("caps", ()))


def route(pick, room: dict | None, wants: list[frozenset[str]]):
    """Work.take filter ``pick`` narrowed to the invocations this host's capabilities cover."""
    return lambda i: (pick is None or pick(i)) and has(room, wants[i])


def served(wants: list[frozenset[str]], rooms: list[dict]) -> bool:
    """True when every invocation's capabilities are covered by at least one of the placed hosts."""
    return all(not need or any(has(room, need) for room in rooms) for need in wants)


def cover(plan: list[tuple[str, str]], hosts: list[str], wants: list[frozenset[str]], rooms: dict) -> list[tuple[str, str]]:
    """plan plus, for each needed capability set no planned host covers, the first placed host that does."""
    plan = list(plan)
    for need in wants:
        if not any(has(rooms.get(h), need) for h, _ in plan):
            plan += [(h, "any") for h in hosts if has(rooms.get(h), need) and h not in {p for p, _ in plan}][:1]
    return plan


def strand(work, wants: list[frozenset[str]], rooms: list[dict]) -> None:
    """Queued invocations no working host can take end as LOST_EXIT (did not run) instead of looping forever."""
    for i in [i for i in work.todo if rooms and not any(has(room, wants[i]) for room in rooms)]:
        print(f"[remote-pytest] invocation {i} needs {sorted(wants[i])}; no working host has it: not run", flush=True)
        work.todo.remove(i)
        work.codes[i] = LOST_EXIT
