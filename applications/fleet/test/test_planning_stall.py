"""A plan that never ends is how the console sees a Nav2 send with no answer."""

import json
import subprocess
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"


def test_planning_turns_stalled_after_the_limit_and_resets_when_it_ends():
    script = f"""import {{planningStalled, PLANNING_SLOW_S}} from {json.dumps((WEB / 'planning-stall.js').as_uri())};
const since = new Map();
const at = s => s * 1000;
console.log(JSON.stringify([
  planningStalled(since, "r1", "PLANNING", at(0)),
  planningStalled(since, "r1", "PLANNING", at(PLANNING_SLOW_S - 1)),
  planningStalled(since, "r1", "PLANNING", at(PLANNING_SLOW_S)),
  planningStalled(since, "r2", "PLANNING", at(PLANNING_SLOW_S)),
  planningStalled(since, "r1", "NAVIGATING", at(PLANNING_SLOW_S + 1)),
  planningStalled(since, "r1", "PLANNING", at(PLANNING_SLOW_S + 2)),
]));"""
    out = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=True)
    assert json.loads(out.stdout) == [False, False, True, False, False, False]
