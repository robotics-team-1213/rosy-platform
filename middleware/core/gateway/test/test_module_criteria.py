"""Criterion C6 as a test, not a rule someone has to remember to re-read.

C6 (`docs/plans/2026-09-06-module-split-criteria.md`) says a dependency reached
through `hasattr`/`getattr` instead of a declared member is a seam lie. A grep
in a document finds those once; this finds them on every run.

The assertion is **set equality against a literal allowlist**, not a count and
not a subset. A count passes when one reach replaces another. A subset passes
when a reach is added. Only equality forces the triage table in the criteria
doc to stay true — every entry below has a verdict recorded there.

Reaches are keyed by (file, kind, receiver, attribute), never by line number.
`ros_bridge.py` and `navigation/manager.py` have drifted in every revision of
the plan that produced this file; a line-keyed allowlist would fail on a
comment edit and teach people to update it without reading it.

ROS-free by construction: this reads source text and imports nothing from the
package, so it runs on the Windows dev host where rclpy is unavailable.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "core"

#: C6's finder. The receiver pattern deliberately excludes `(` so a nested
#: `getattr(getattr(x, "a"), "b")` is recorded as the inner reach on `x` — the
#: one that crosses the boundary — rather than as an unreadable outer match.
REACH = re.compile(
    r"\b(hasattr|getattr)\("
    r"\s*([A-Za-z_][\w.\[\]]*)\s*,"
    r"\s*(\"[^\"]*\"|'[^']*'|[A-Za-z_][\w.\[\]]*)"
)

#: Every reach in the package, with the verdict it carries in the criteria doc.
#: Adding a reach fails this test. That is the point: the next one gets a
#: verdict before it lands, not after someone notices it in review.
ALLOWED = Counter({
    # NOTE (D-125/D-126): this test scans only the `core` entry package.
    # Reaches that moved out with their files (api/v1/*, docking/, power/,
    # safety/) keep their verdicts in the criteria doc, but no per-package
    # C6 scan covers them yet — recorded gap, not a verdict.

    # Accepted: optional ControlSensorAdapter diagnostics/lifecycle probes on
    # injected ROS/test doubles. These do not cross into private ownership.
    ("bridge/control_sensor_adapter.py", "getattr", "node", '"_sensor_only"'): 1,
    ("bridge/control_sensor_adapter.py", "getattr", "node", '"bind_policy_handoff"'): 1,
    ("bridge/control_sensor_adapter.py", "getattr", "node", '"destroy_node"'): 1,
    ("bridge/control_sensor_adapter.py", "getattr", "node", '"observations"'): 1,
    ("bridge/control_sensor_adapter.py", "getattr", "node", '"profile"'): 1,
    ("bridge/control_sensor_adapter.py", "getattr", "node", '"refresh_profile"'): 1,
    ("bridge/control_sensor_adapter.py", "getattr", "node", "name"): 1,
    # Accepted (D-126 S1): entry-point provider dispatch. The attribute name
    # selects which of the provider's three factories (make_node, make_policy,
    # load_snapshot) to load; a missing provider or factory fails closed with
    # an install hint instead of an ImportError. No private field is reached.
    ("bridge/control_sensor_adapter.py", "getattr", "provider", "attr"): 1,
    # D-468 optional provider capability: absent/error/non-boolean results
    # deny return motion; the control package owns the hook.
    ("bridge/control_sensor_adapter.py", "getattr", "self.policy", "'local_return_allowed'"): 1,
    ("bridge/control_sensor_adapter.py", "hasattr", "observations", '"max_age"'): 1,
    ("node.py", "getattr", "self", '"get_namespace"'): 1,
    # Accepted (core-shutdown 2026-09-23): rclpy Jazzy's MultiThreadedExecutor never
    # drains its ThreadPoolExecutor; teardown does it. isinstance-guarded, see doc.
    ("node.py", "getattr", "executor", '"_executor"'): 1,
    # Accepted: readiness service injection and ROS TransitionEvent state
    # compatibility. All fields are public and remain inside the bridge.
    ("bridge/ros_bridge.py", "getattr", "services", '"readiness"'): 1,
    ("bridge/ros_bridge.py", "getattr", "msg", '"goal_state"'): 1,
    ("bridge/ros_bridge.py", "getattr", "goal", '"id"'): 1,
    ("bridge/ros_bridge.py", "getattr", "goal", '"label"'): 1,
    # Accepted (D-468): preserve public LaserScan angular resolution and source stamp;
    # missing source time becomes zero and therefore cannot pass the freshness gate.
    ("bridge/translate.py", "getattr", "msg", '"angle_increment"'): 1,
    ("bridge/translate.py", "getattr", "msg.header", '"stamp"'): 1,
    # Accepted: nav path metadata is optional on injected state/message doubles;
    # absent values stay None and do not authorize motion.
    ("bridge/observation.py", "getattr", "services.state", '"map_id"'): 1,
    ("bridge/observation.py", "getattr", "msg", '"header"'): 1,
    # Accepted (D-573): line-follow doubles without the crosswalk-gate property read as not
    # asking (gate default off); the probe only gates scan forwarding, never motion.
    # Accepted (D-555): optional public link state on the injected FleetAgent; a double without
    # the fields reads as armed / never relinked (boot behaviour). Decides only when SAF-003
    # counts the link, never motion.
    ("fleet_loss_wiring.py", "getattr", "fleet_agent", '"armed"'): 1,
    ("fleet_loss_wiring.py", "getattr", "fleet_agent", '"relinked_at"'): 1,
})


def _reaches() -> Counter:
    found: Counter = Counter()
    for path in sorted(PACKAGE.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        relative = path.relative_to(PACKAGE).as_posix()
        # Whole-file, not line-by-line: at --max-line-length=120 a long reach
        # gets wrapped after the opening paren, and a per-line scan would miss
        # exactly the reaches most worth catching. `\s*` in REACH spans the
        # newline.
        for kind, receiver, attribute in REACH.findall(path.read_text(encoding="utf-8")):
            found[(relative, kind, receiver, attribute)] += 1
    return found


def test_c6_seam_reaches_match_the_published_triage():
    found = _reaches()

    added = found - ALLOWED
    removed = ALLOWED - found
    assert not added and not removed, (
        "C6 (docs/plans/2026-09-06-module-split-criteria.md): the set of "
        "hasattr/getattr reaches no longer matches the published triage.\n"
        f"  new, needs a verdict in the doc: {sorted(added.elements())}\n"
        f"  gone, remove it from the doc:    {sorted(removed.elements())}\n"
        "A reach is a seam lie until the doc says otherwise. Give it a verdict "
        "there and update ALLOWED in the same commit."
    )
