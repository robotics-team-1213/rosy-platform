"""D-168: ROS package structure standard (P2 layout, P3/P4 coupling, P6 size).

Every exception list below is checked by set equality (P5): a new violation
fails, and so does an entry whose violation has since disappeared. Update the
list in the same change that creates or removes the violation.

Honest holes, not oversights:
- Launch coupling is found only through literal
  ``get_package_share_directory("x")`` / ``FindPackageShare("x")`` calls,
  ``$(find-pkg-share x)``, ``package://x/…`` URIs, and, inside launch files,
  ``package="x"`` and ``<node pkg="x">``. A package name built at runtime is
  invisible here.
- ``src/sim/isaac_sim`` ships Isaac assets with no ``package.xml``, so this
  scan never sees it at all.
- Dynamic imports (``importlib.import_module``, entry points) are invisible.
  The one intended case is core loading ``rosy.sensor_provider`` (D-126).
- P6 budgets are per code type (D-362): 600 for production ``.py``/``.cpp``/``.hpp``/``.sh``
  across ``src/`` packages and the ``deploy``/``tools``/``firmware`` roots, 800 for web
  assets (``.js``/``.html``/``.css``) inside ``src/`` packages, zero growth allowance above
  1000. Test code and data files are exempt. Line counts are physical lines, blank
  lines and comments included.
"""

import ast
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"

DOMAINS = {"contracts", "runtime", "drivers", "products", "hmi", "site", "sim"}

#: P2 library/contract tier: no process of their own (runtime gates N/A).
LIBRARY_PACKAGES = {"core_common", "core_events", "core_features", "core_api_web", "web_common"}

#: P4: core contracts every domain may consume.
CORE_CONTRACTS = {"interfaces", "core_common", "web_common"}

#: P2(d) exceptions: packages without their own test/test_*.py.
KNOWN_WITHOUT_OWN_TESTS = {
    "navigation": "launch/params contracts live in the repository test/ suite",
}

#: P3/P4 exceptions as (source package, target package).
KNOWN_UNDECLARED = {
    ("navigation", "control"): "hardware.launch.py includes control/line_follow.launch.py",
}

#: P4 core-row exceptions: back-edges against the one-way core chain.
KNOWN_CHAIN_BACK_EDGES = {
}
KNOWN_DIRECTION = {
    ("control", "imu_bno055"): "runtime/sensing -> drivers/imu_bno055; declared exec_depend. Legacy launches start the IMU driver; the long-term fix is bringup assembly, not a sensing launch",
    ("rosy_vision", "games"): "Rosy Vision reuses the ROS-free four-point homography helper for camera calibration",
    ("bringup", "control"): "products/bringup -> runtime/sensing: bringup_robot.launch.py starts control's ir_adc_node for the rosy-io graph (enable_ir, D-344 §12) — bringup assembling the robot graph is the direction the imu_bno055 row names",
}

#: P6 budgets.
FILE_BUDGET = 600
PACKAGE_BUDGET = 10_000
REGROWTH_ALLOWANCE = 150

#: P6 per-type budgets and coverage (D-362), docs/plans/2026-09-30-file-size-budget-and-refactor-queue.md
FILE_BUDGET_WEB = 800
WEB_SUFFIXES = {".js", ".html", ".css"}
OPS_SUFFIXES = {".py", ".sh"}
OPS_ROOTS = ("deploy", "tools", "firmware")
HARD_TIER = 1_000  # a file above this gets zero growth allowance

CONTROL_SPLIT = "docs/plans/2026-09-22-control-package-split-design.md"

#: P6 verdicts: path (relative to src/) or package name -> (lines at verdict, verdict).
SIZE_VERDICTS = {
    "fleet": (
        19_468,
        "split: server HTTP boundary, console, signals and the mission-control stores are separate owners "
        "today; group them into subpackages rather than one flat server/ tree (B2); owner fleet, unscheduled "
        "(re-judged 2026-09-29 at 11164 after mission_store joined the server tree; re-judged 2026-09-30 at "
        "12419 after the D-361 enrollment register, roster and service joined as their own modules, and "
        "at 12574 after the D-361 review fixes; re-judged 2026-09-30 at 13187 after main's goal-evidence "
        "contracts and stores merged in; re-judged 2026-09-30 at 14260 after D-357/D-358 feedback "
        "contracts, dispatcher, stateless adapter and bounded outbox modules/tests were added; re-judged "
        "at 14616 after atomic candidate fencing and linked-successor regression tests; re-judged at 15000 "
        "after the injected outbox consumer, trusted post-action Vision reader, and deadline/egress fence "
        "coverage joined; re-judged 2026-09-30 at 18967 under D-362 — the package total now counts web "
        "assets (server/web console js/css/html); re-judged 2026-09-30 at 19243 after D-362 P0-1 "
        "executed the app.py router split (app.py 1556 -> 476 plus mission/task_dispatch/intent/"
        "console/ingest/static route modules and site_auth) — the flat server/ tree still wants the "
        "B2 subpackage regroup; re-judged 2026-10-01 at 19468 after the same-host OMX phase receipt "
        "projection joined the existing Fleet mission journal and read-only status surface. The phase "
        "events share the Mission SQLite transaction and owner; B2 regroup remains unscheduled. Split remains "
        "unscheduled (docs/plans/2026-09-30-er2-mission-feedback-loop.md)",
    ),
    "site/fleet/fleet/server/enrollment.py": (
        610,
        "accept: one owner (D-361 robot enrollment — exchange, binding, pinned-address gate, unenroll and "
        "pending logout share one state machine over the register), ROS-free, host-testable (X5)",
    ),
    "site/fleet/fleet/server/mission_store.py": (
        887,
        "accept: one owner (the Fleet Mission SQLite ledger — missions, attempts, progress snapshots, "
        "fenced device phase snapshots, and their transitions in one transactional store), ROS-free, "
        "host-testable; correlated task evidence stays in task_store/task_results (X5). Re-judged "
        "2026-10-01 at 887 after idempotent per-attempt phase projection joined the Mission event transaction",
    ),
    "contracts/foundation/core_common/protocol/schemas.py": (
        1_067,
        "accept: the D-18 single contract source — every envelope, event and capability model in one "
        "importable place; per-domain schema files would fork the version pin that "
        "test_protocol_version_alignment guards. Re-judged 2026-09-30 at 1000 lines after the bounded "
        "Mission feedback scope/context/tool-result contracts were added; re-judged 2026-09-30 at 1001 "
        "under the D-362 zero-allowance tier; re-judged 2026-09-30 at 1002 when the pilot branch added "
        "LineFollowStatus.clearance_m (D-344 §11, one field); re-judged 2026-10-01 at 1067 for the "
        "bounded UDS v2 phase receipt and read-only Mission phase progress schemas, which remain in the "
        "single contract source guarded by protocol alignment. The hard-tier zero-growth rule prevents "
        "silent expansion. ROS-free, host-testable (X5)",
    ),
    "site/fleet/fleet/server/task_store.py": (
        1060,
        "accept: keep SQLite task, history, lease, reservation, and dispatch-claim transactions together; "
        "correlated CORE event projection lives in task_results.py. Re-judged 2026-09-29 at 1014 lines after "
        "durable dispatch resource claims moved into the same store owner (docs/plans/"
        "2026-09-29-fleet-mission-control-arbitration-implementation.md); re-judged 2026-09-30 at 1060 "
        "under the D-362 zero-allowance tier — verdict unchanged",
    ),
    "runtime/sensing/control/safety/node.py": (
        795,
        "accept: legacy comparison-graph publisher pinned by test_module_separation; no new work (X3)",
    ),
    "site/fleet/fleet/server/console.py": (
        1021,
        "accept: one owner (FleetConsole gather/scatter), host-testable (X5). Re-judged 2026-09-30 at 1013: "
        "D-361 roster mutation and pinned-address holds change the gather/traffic tables in place, so they "
        "stay with their owner; the roster policy itself lives in roster.py; re-judged 2026-09-30 at 1021 "
        "under the D-362 zero-allowance tier — verdict unchanged",
    ),
    "runtime/sensing/control/sensing/perception/lane.py": (
        765,
        "accept: one concern (lane/IR line detection), ROS-free pure functions and trackers, host-testable (X5); "
        "the ground-geometry lane keeper already lives apart in lane_keep.py (D-364)",
    ),
    "runtime/gateway/core/bridge/ros_bridge.py": (
        606,
        "accept: one CORE ROS executor integration point for publishers, subscriptions, lifecycle wiring, and "
        "service/action clients; extracted policy and callback logic lives in core/bridge modules, and "
        "timer/bridge behavior is covered by test_bridge_timers.py and test_bridge_reconcile.py. Re-judged "
        "2026-10-01 at 606 after D-385 mode-to-emotion handoff wiring",
    ),
    "runtime/sensing/control/sensing/perception/lane_bev.py": (
        611,
        "accept: one owner (LaneEdgeFollower + its bird's-eye helpers), ROS-free, host-testable (X5)",
    ),
    "runtime/events/core_events/events/audit.py": (
        745,
        "accept: one owner (svc.audit / FileAuditLog), ROS-free, covered by src/runtime/events/test/test_audit.py; "
        "about half the lines are the rationale comments the append/compaction/quarantine rules rest on (X5)",
    ),
    "runtime/services/core_features/docking/manager.py": (
        663,
        "accept: 930 -> 663 after the parking-only phases moved to docking/parking_phases.py and the phase/"
        "executor/config definitions to docking/model.py (user decision 2026-09-24: split, not a size exception); "
        "what remains is the one lock owner (state, RLock, take/release_mode seams, fail/retry/release, the "
        "default-dock phases, battery return, public API), ROS-free, covered by core_features/test/test_docking*.py "
        "and core/test/test_docking_*.py (X5)",
    ),
    "runtime/services/core_features/traffic_policy/manager.py": (
        609,
        "accept: one owner (the TrafficPolicyManager verdict state machine with its evidence contracts "
        "RoadEvidence/SignalHeadEvidence/config/decision), ROS-free, host-testable via core/test/test_traffic_policy.py; "
        "the D-337 measured-light fusion grew the dwell-complete branch (2026-09-29) and the observer transport "
        "already lives in traffic_policy/observer_source.py (X5)",
    ),
    "sim/gz_sim/scripts/lane_live_view.py": (
        709,
        "accept: sim-only read-only viewer server (HTTP handler + ROS subscriptions); the pure logic already lives in live_view_model.py and the page in lane_live_view.html, covered by test_lane_live_view*.py and test_live_view_model.py (X5)",
    ),
    "control": (
        37_732,
        f"split: deploy closure needs only sensing + safety provider (P1a); {CONTROL_SPLIT} "
        "(re-judged 2026-09-30 at 33090 after D-356 added the ROS-free learned perception backend "
        "(sensing/perception/learned), the shadow node and the recording CLI; the learned backend sits "
        "inside sensing/perception and moves with it — verdict unchanged; re-judged 2026-09-30 at 35197 "
        "under D-362 — web/diagnostic.html and the sensing web assets now count toward the package total; "
        "re-judged 2026-09-30 at 36091 when the pilot branch merged the ROS-free lane keepers "
        "(lane_keep.py 'keep', lane.py 'between') and the NOMINAL ground inside sensing/perception — verdict unchanged; "
        "re-judged again at 36677 with the ROS-free IR line calibration (perception/ir_calibration.py), its read-only "
        "device CLI and the camera-launch overlay validator (control/ir_overlay.py) — verdict unchanged; "
        "re-judged again at 36861 with keep v2 (boundary tracking, wall-base tape, corner-mode holds) and its "
        "front end split into lane_keep_lines.py — verdict unchanged; re-judged 2026-10-01 at 37732 "
        "when the D-47 addendum added the ROS-free calibration fits (sensing/odometry_fit.py, "
        "sensing/perception/camera_extrinsic.py), the stationary camera step mixin "
        "(calibration_camera.py) and the store reader (calibrated_values.py) — each its own module, "
        "verdict unchanged)",
    ),
    # --- D-362 newly-covered files (web assets in src/ packages, ops roots). ---
    "runtime/sensing/web/diagnostic.html": (
        1857,
        "accept: re-judged 2026-09-30 (D-362 P1) — the single HTML file with one IIFE is the "
        "recorded design, not an accident (web/AGENTS.md: dependency-free on purpose, no build "
        "step, served straight from the share dir); it is a debug-only surface excluded from "
        "operational launch and deploy (D-150, ports pinned out by test_control_launch_boundary), "
        "with one owner (web_node). Splitting it into css/js partials would break that contract "
        "to shorten a dev-only file. Zero growth allowance applies (>1000)",
    ),
    # hmi/dashboard/app.js (1338 -> 745) and styles.css (1119 -> 492): the P1
    # extraction landed — telemetry/teleop/state-socket modules and the
    # console-detail.css tail split — so these entries left with it.
    "sim/gz_sim/scripts/lane_live_view.html": (
        856,
        "accept: same owner as the accepted lane_live_view.py — the pure logic already lives in "
        "live_view_model.py and this is the read-only page it renders, covered by test_lane_live_view*.py "
        "and test_live_view_model.py (X5)",
    ),
    "deploy/robot/pinky_pro/image/first-boot/rosy-first-boot.py": (
        799,
        "accept: single-entry first-boot provisioning that runs once on the card — one state machine, "
        "covered by test/test_first_boot_provisioning.py (X5)",
    ),
    "deploy/robot/pinky_pro/sd/verify-media-readback.py": (
        788,
        "accept: standalone Windows readback script the operator runs from one file; covered by "
        "test/test_media_readback.py (X5)",
    ),
    "tools/harness/rosy_harness.py": (
        693,
        "accept: the harness gate itself (lint/generate) — one CLI owner pinned by "
        "test/test_harness_contracts.py (X5)",
    ),
    "deploy/robot/pinky_pro/native/rosy-boot-display.py": (
        688,
        "accept: single-entry boot status display (T0 indicator) — one render loop, covered by "
        "test/test_boot_display.py (X5)",
    ),
    "deploy/robot/pinky_pro/release/updater.py": (
        686,
        "accept: activate/rollback atomicity is one transactional script; covered by "
        "test/test_release_updater.py (X5)",
    ),
    "deploy/robot/pinky_pro/release/secret_scan.py": (
        670,
        "accept: one scan entry over the release tree — the rules and the walker are the same concern (X5)",
    ),
    "deploy/robot/pinky_pro/native/rosy-hw-probe.py": (
        641,
        "accept: single-entry hardware probe CLI the commissioning runbook drives top-to-bottom — "
        "splitting probe sequence from reporting would sever one diagnostic narrative (X5)",
    ),
    "products/omx/adapter/omx_adapter/action_store.py": (
        1_176,
        "accept: one owner for the durable local Action, per-attempt ROS phase journal, and semantic "
        "workflow terminal gate; they share SQLite transactions, identity fences, and restart-to-UNKNOWN "
        "recovery. ROS-free and host-testable. Re-judged 2026-10-01 at 1109 after the durable gripper "
        "evidence gate and restart-to-HOLD journal recovery; recovery updates share the same SQLite "
        "transaction so the Action, phase, and possible-held-object state cannot split. Re-judged "
        "2026-10-01 at 1176 for late ROS UUID and exact-cancel intent journaling after UNKNOWN/HOLD "
        "without reopening phase state (D-386). The hard-tier "
        "zero-growth rule prevents silent expansion",
    ),
}

WORKSPACE_REF_PATTERNS = (
    re.compile(r"get_package_share_directory\(\s*['\"](\w+)['\"]"),
    re.compile(r"FindPackageShare\(\s*['\"](\w+)['\"]"),
    re.compile(r"\$\(find-pkg-share\s+(\w+)\)"),
    #: ``package://x/…`` URIs — mesh/world/map refs in urdf/xacro/sdf/world/rviz/yaml.
    re.compile(r"package://(\w+)/"),
)
#: Executable references, scanned in launch files only (``setup.py`` also says ``package``).
LAUNCH_EXEC_PATTERNS = (
    re.compile(r"\bpackage\s*=\s*['\"](\w+)['\"]"),
    re.compile(r"<node\b[^>]*\bpkg\s*=\s*['\"](\w+)['\"]"),
)
CODE_SUFFIXES = {".py", ".cpp", ".hpp"}
DECLARING_TAGS = {"depend", "exec_depend", "build_depend", "build_export_depend"}


def _is_prod(path: Path) -> bool:
    parts = path.relative_to(SRC).parts
    return not any(p in ("test", "tests", "build", "install", "log") or p.startswith(".") for p in parts)


def _packages():
    found = {}
    for package_xml in sorted(SRC.rglob("package.xml")):
        if not _is_prod(package_xml):
            continue
        root = ET.parse(package_xml).getroot()
        found[root.findtext("name")] = {"dir": package_xml.parent, "xml": root}
    return found


PACKAGES = _packages()


def _domain(name: str) -> str:
    return PACKAGES[name]["dir"].relative_to(SRC).parts[0]


def _family(name: str):
    parts = PACKAGES[name]["dir"].relative_to(SRC).parts
    return parts[1] if len(parts) == 3 and parts[0] == "products" else None


# D-241 and D-242: the ROS package name stays. These directories use the role name.
ROLE_DIR = {
    "core": ("runtime", "gateway"),
    "core_events": ("runtime", "events"),
    "core_features": ("runtime", "services"),
    "core_api_web": ("runtime", "api_web"),
    "core_common": ("contracts", "foundation"),
    "control": ("runtime", "sensing"),
    "web_common": ("hmi", "web_common"),
    "emotion": ("hmi", "face"),
    "pinky_pro": ("products", "pinky_pro", "profile"),
    "bringup": ("products", "pinky_pro", "bringup"),
    "sensor_adc": ("products", "pinky_pro", "adc"),
    "lamp_control": ("products", "pinky_pro", "lamp"),
    "led": ("products", "pinky_pro", "led"),
    "omx": ("products", "omx", "profile"),
    "omx_adapter": ("products", "omx", "adapter"),
    "imu_bno055": ("drivers", "imu_bno055"),
}


def layout_ok(rel: tuple, name: str) -> bool:
    """P2(a) + D-310: declared product packages and independent drivers."""
    if not rel or rel[0] not in DOMAINS:
        return False
    if name in ROLE_DIR:
        return rel == ROLE_DIR[name]
    if rel[0] == "products":
        return False  # Product packages require an explicit family/role declaration.
    # D-377: an app package is `rosy_<word>` in folder `<domain>/<word>`.
    return len(rel) == 2 and name in (rel[1], f"rosy_{rel[1]}")


def _declared(name: str) -> set:
    return {
        (e.text or "").strip()
        for e in PACKAGES[name]["xml"]
        if e.tag in DECLARING_TAGS and (e.text or "").strip() in PACKAGES
    }


def _files(name: str, suffixes):
    for path in PACKAGES[name]["dir"].rglob("*"):
        if path.is_file() and path.suffix in suffixes and _is_prod(path):
            yield path


def _used(name: str) -> dict:
    """Workspace packages this package reaches, mapped to one example site."""
    used = {}
    for path in _files(name, {".py"}):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                tops = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                tops = [node.module.split(".")[0]]
            else:
                continue
            for top in tops:
                used.setdefault(top, f"{path.relative_to(SRC).as_posix()} imports {top}")
    for path in _files(name, {".py", ".xml", ".cpp", ".hpp", ".yaml",
                               ".urdf", ".xacro", ".sdf", ".world", ".rviz"}):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in WORKSPACE_REF_PATTERNS:
            for match in pattern.finditer(text):
                used.setdefault(match.group(1), f"{path.relative_to(SRC).as_posix()} references {match.group(1)}")
        if "launch" in path.relative_to(PACKAGES[name]["dir"]).parts or ".launch." in path.name:
            for pattern in LAUNCH_EXEC_PATTERNS:
                for match in pattern.finditer(text):
                    used.setdefault(match.group(1), f"{path.relative_to(SRC).as_posix()} runs {match.group(1)}")
        if path.suffix in {".cpp", ".hpp"}:
            for match in re.finditer(r"#include\s*[<\"](\w+)/", text):
                used.setdefault(match.group(1), f"{path.relative_to(SRC).as_posix()} includes {match.group(1)}")
    return {top: site for top, site in used.items() if top in PACKAGES and top != name}


def edge_allowed(src_domain, src_family, dst_domain, dst_family, target) -> bool:
    """P4 direction table (D-168, D-310). Pure, so rows are testable."""
    if target in CORE_CONTRACTS:
        return True
    if src_domain == "core":
        return dst_domain == "core"
    if src_domain == "sim":
        return True
    if src_domain == "products":
        if dst_domain == "sim" and target == "description":
            return True
        if dst_domain == "drivers":
            return True
        return bool(src_family) and dst_domain == "products" and dst_family == src_family
    return False


def _allowed(source: str, target: str) -> bool:
    src_domain, dst_domain = _domain(source), _domain(target)
    if source == "navigation" and target == "bringup" and dst_domain == "products":
        return True
    if src_domain == "runtime" and dst_domain == "runtime":
        return True
    # D-243: the API package serves the operator screens and nothing else in runtime does.
    # D-323: the pilot teleop surface follows the same serving exception.
    if source == "core_api_web" and target in {"dashboard", "pilot"}:
        return True
    return edge_allowed(src_domain, _family(source), dst_domain, _family(target), target)


def _lines(path: Path) -> int:
    with path.open("rb") as handle:
        return sum(1 for _ in handle)


def test_the_scan_sees_the_whole_tree():
    assert len(PACKAGES) >= 20, sorted(PACKAGES)


def test_every_package_sits_in_a_domain_group_under_its_own_name():
    """P2(a) + D-147 + D-310: package names persist at declared source roots.

    Products nest under their family; standalone drivers stay under drivers/.
    """
    bad = []
    for name, info in PACKAGES.items():
        rel = info["dir"].relative_to(SRC).parts
        if not layout_ok(rel, name):
            bad.append(f"{name}: {'/'.join(rel)}")
    assert bad == [], bad


def test_every_package_has_agents_md():
    """P2(b)."""
    missing = [name for name, info in PACKAGES.items() if not (info["dir"] / "AGENTS.md").is_file()]
    assert missing == [], missing


def test_every_package_is_a_harness_module():
    """P2(c): registered in harness.yaml (the harness tests check the records)."""
    config = yaml.safe_load((ROOT / "tools" / "harness" / "harness.yaml").read_text(encoding="utf-8"))
    registered = {(ROOT / m["path"]).resolve() for m in config["modules"]}
    missing = [name for name, info in PACKAGES.items() if info["dir"].resolve() not in registered]
    assert missing == [], missing


def test_library_packages_leave_runtime_gates_to_their_consumer():
    """P2: library/contract packages write N/A for ROS-SIM..FIELD."""
    bad = []
    for name in sorted(LIBRARY_PACKAGES):
        text = (PACKAGES[name]["dir"] / "progress.md").read_text(encoding="utf-8")
        meta = yaml.safe_load(text.split("---", 2)[1])
        for gate in ("ROS-SIM", "ARTIFACT", "DEVICE", "FIELD"):
            state = meta["gates"][gate]["state"]
            if state != "N/A":
                bad.append(f"{name} {gate}={state}")
    assert bad == [], bad


def test_every_package_owns_tests():
    """P2(d), with the exception list checked both ways (P5)."""
    without = {
        name
        for name, info in PACKAGES.items()
        if not any((info["dir"] / "test").glob("test_*.py"))
    }
    assert without == set(KNOWN_WITHOUT_OWN_TESTS), (
        f"new: {sorted(without - set(KNOWN_WITHOUT_OWN_TESTS))}, "
        f"stale: {sorted(set(KNOWN_WITHOUT_OWN_TESTS) - without)}"
    )


def test_every_cross_package_use_is_declared():
    """P3: imports, includes and launch references all appear in package.xml."""
    undeclared = {}
    for name in PACKAGES:
        declared = _declared(name)
        for target, site in _used(name).items():
            if target not in declared:
                undeclared[(name, target)] = site
    assert set(undeclared) == set(KNOWN_UNDECLARED), (
        f"new: {[undeclared[k] for k in sorted(set(undeclared) - set(KNOWN_UNDECLARED))]}, "
        f"stale: {sorted(set(KNOWN_UNDECLARED) - set(undeclared))}"
    )


def test_cross_domain_edges_follow_the_direction_table():
    """P4: declared or used edges must be allowed for the source domain."""
    wrong = {}
    for name in PACKAGES:
        for target in _declared(name) | set(_used(name)):
            if target != name and not _allowed(name, target):
                wrong[(name, target)] = f"{_domain(name)}/{name} -> {_domain(target)}/{target}"
    assert set(wrong) == set(KNOWN_DIRECTION), (
        f"new: {[wrong[k] for k in sorted(set(wrong) - set(KNOWN_DIRECTION))]}, "
        f"stale: {sorted(set(KNOWN_DIRECTION) - set(wrong))}"
    )


def test_core_chain_stays_one_way():
    """P4 core row: common <- events <- features <- api_web <- core."""
    order = ["core_common", "core_events", "core_features", "core_api_web", "core"]
    back = [
        f"{order[i]} -> {order[j]}"
        for i in range(len(order))
        for j in range(i + 1, len(order))
        if order[j] in _declared(order[i]) | set(_used(order[i]))
    ]
    assert set(back) == set(KNOWN_CHAIN_BACK_EDGES), (
        f"new: {sorted(set(back) - set(KNOWN_CHAIN_BACK_EDGES))}, "
        f"stale: {sorted(set(KNOWN_CHAIN_BACK_EDGES) - set(back))}"
    )


def _is_prod_outside_src(path: Path) -> bool:
    """Prod filter for the deploy/tools/firmware roots (D-362), same rule as _is_prod."""
    return not any(
        p in ("test", "tests", "build", "install", "log") or p.startswith(".")
        for p in path.relative_to(ROOT).parts
    )


def _over_budget() -> dict:
    over = {}
    for name in PACKAGES:
        total = 0
        for path in _files(name, CODE_SUFFIXES | {".sh"} | WEB_SUFFIXES):
            count = _lines(path)
            total += count
            budget = FILE_BUDGET_WEB if path.suffix in WEB_SUFFIXES else FILE_BUDGET
            if count > budget:
                over[path.relative_to(SRC).as_posix()] = count
        if total > PACKAGE_BUDGET:
            over[name] = total
    for root_name in OPS_ROOTS:
        for path in (ROOT / root_name).rglob("*"):
            if not path.is_file() or path.suffix not in OPS_SUFFIXES:
                continue
            if not _is_prod_outside_src(path):
                continue
            count = _lines(path)
            if count > FILE_BUDGET:
                over[path.relative_to(ROOT).as_posix()] = count
    return over


def test_over_budget_code_has_a_recorded_verdict():
    """P6: every file > 600 lines and package > 10k lines has a verdict, and no stale ones."""
    over = _over_budget()
    assert set(over) == set(SIZE_VERDICTS), (
        f"needs a verdict: {sorted((k, over[k]) for k in set(over) - set(SIZE_VERDICTS))}, "
        f"stale: {sorted(set(SIZE_VERDICTS) - set(over))}"
    )


def _allowance(key: str, at_verdict: int, now: int) -> int:
    """D-362: a file above HARD_TIER gets zero growth allowance (packages keep 150)."""
    if key not in PACKAGES and max(at_verdict, now) > HARD_TIER:
        return 0
    return REGROWTH_ALLOWANCE


def test_size_verdicts_are_well_formed_and_current():
    """P6: split/accept only, split plans exist, and no silent regrowth."""
    over = _over_budget()
    bad = []
    for key, (at_verdict, verdict) in SIZE_VERDICTS.items():
        kind, _, reason = verdict.partition(": ")
        if kind not in ("split", "accept") or not reason:
            bad.append(f"{key}: verdict must be 'split: ...' or 'accept: ...'")
        for plan in re.findall(r"docs/plans/\S+?\.md", verdict):
            if not (ROOT / plan).is_file():
                bad.append(f"{key}: plan not found {plan}")
        allowance = _allowance(key, at_verdict, over.get(key, 0))
        if key in over and over[key] > at_verdict + allowance:
            bad.append(f"{key}: {over[key]} lines, grew past {at_verdict}+{allowance}; re-judge")
    assert bad == [], bad


@pytest.mark.parametrize(
    "src_domain, src_family, dst_domain, dst_family, target, ok",
    [
        ("products", "pinky_pro", "sim", None, "description", True),
        ("products", "pinky_pro", "drivers", None, "imu_bno055", True),
        ("products", "pinky_pro", "products", "pinky_pro", "bringup", True),
        ("products", "pinky_pro", "products", "omx", "omx_adapter", False),
        ("products", "omx", "products", "pinky_pro", "bringup", False),
        ("products", "omx", "contracts", None, "core_common", True),
        ("products", "omx", "runtime", None, "core", False),
        ("runtime", None, "products", "pinky_pro", "bringup", False),
        ("drivers", None, "products", "pinky_pro", "bringup", False),
        ("site", None, "drivers", None, "imu_bno055", False),
    ],
)
def test_direction_table_rows_for_products_and_drivers(src_domain, src_family, dst_domain, dst_family, target, ok):
    """D-310 P4 rows retain separate product, driver, and runtime ownership."""
    assert edge_allowed(src_domain, src_family, dst_domain, dst_family, target) is ok


@pytest.mark.parametrize(
    "rel, name, ok",
    [
        (("products", "pinky_pro", "bringup"), "bringup", True),
        (("products", "pinky_pro", "profile"), "pinky_pro", True),
        (("products", "omx", "adapter"), "omx_adapter", True),
        (("drivers", "imu_bno055"), "imu_bno055", True),
        (("devices", "pinky_pro", "bringup"), "bringup", False),
        (("devices", "bringup"), "bringup", False),
        (("products", "pinky_pro"), "pinky_pro", False),
        (("products", "omx", "bringup"), "bringup", False),
        (("runtime", "sensing"), "control", True),
        (("runtime", "control"), "control", False),
        (("core", "control"), "control", False),
        (("apps", "x", "control"), "control", False),
    ],
)
def test_layout_rule_allows_declared_product_packages_and_standalone_drivers(rel, name, ok):
    """P2(a) + D-310: product packages require explicit family ownership."""
    assert layout_ok(rel, name) is ok
