"""D-168: ROS package structure standard (P2 layout, P3/P4 coupling, P6 size).

Every exception list below is checked by set equality (P5): a new violation
fails, and so does an entry whose violation has since disappeared. Update the
list in the same change that creates or removes the violation.

Honest holes, not oversights:
- Launch coupling is found only through literal
  ``get_package_share_directory("x")`` / ``FindPackageShare("x")`` calls,
  ``$(find-pkg-share x)``, and, inside launch files, ``package="x"`` and
  ``<node pkg="x">``. A package name built at runtime is invisible here.
- Dynamic imports (``importlib.import_module``, entry points) are invisible.
  The one intended case is core loading ``rosy.sensor_provider`` (D-126).
- Line counts are physical lines, blank lines and comments included.
"""

import ast
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"

DOMAINS = {"contracts", "runtime", "devices", "products", "hmi", "site", "sim"}

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
    ("core_common", "core"): "config._find_default_config reads the core share (same edge as below)",
    ("control", "imu_bno055"): "legacy robot/wander launches start the IMU driver",
    ("navigation", "core"): "web_nav2/web_slam(+gz_) launch XML starts the core node",
}

#: P4 core-row exceptions: back-edges against the one-way core chain.
KNOWN_CHAIN_BACK_EDGES = {
    "core_common -> core": "default config file lives in core/config; resolve by moving it to a "
    "core_common share or by having core pass the path in",
}
KNOWN_DIRECTION = {
    ("core_common", "core"): "default config file lives in the core package share; the lookup stayed when core_common moved to contracts",
    ("control", "imu_bno055"): "runtime/sensing -> devices/common/imu_bno055; the IMU belongs in bringup/deploy assembly, not a sensing launch",
    ("overhead", "games"): "site overhead reuses the ROS-free four-point homography helper for camera calibration",
}

#: P6 budgets.
FILE_BUDGET = 600
PACKAGE_BUDGET = 10_000
REGROWTH_ALLOWANCE = 150

CONTROL_SPLIT = "docs/plans/2026-09-22-control-package-split-design.md"

#: P6 verdicts: path (relative to src/) or package name -> (lines at verdict, verdict).
SIZE_VERDICTS = {
    "site/fleet/fleet/server/app.py": (
        622,
        "accept: compose Fleet routes and shared authentication/audit dependencies in one HTTP boundary; split by route group only when an independent auth and lifecycle boundary exists",
    ),
    "site/fleet/fleet/server/task_store.py": (
        620,
        "accept: keep SQLite task, history, lease, and reservation transactions together; split only if this cohesive store grows further",
    ),
    "runtime/sensing/control/startup_calibration_node.py": (
        954,
        f"split: extract the ROS-free calibration state machine (C1); {CONTROL_SPLIT}",
    ),
    "runtime/sensing/control/calib_node.py": (
        640,
        f"split: same calibration cluster as startup_calibration_node (C1); {CONTROL_SPLIT}",
    ),
    "site/fleet/fleet/server/signals.py": (
        621,
        "split: file store, HTTP client and observer are separate roles today (B2); owner fleet, unscheduled",
    ),
    "runtime/sensing/control/safety/node.py": (
        795,
        "accept: legacy comparison-graph publisher pinned by test_module_separation; no new work (X3)",
    ),
    "site/fleet/fleet/server/console.py": (
        767,
        "accept: one owner (FleetConsole gather/scatter), host-testable (X5)",
    ),
    "runtime/sensing/control/sensing/perception/lane.py": (
        611,
        "accept: one concern (lane/IR line detection), ROS-free pure functions and trackers, host-testable (X5)",
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
    "sim/gz_sim/scripts/lane_live_view.py": (
        709,
        "accept: sim-only read-only viewer server (HTTP handler + ROS subscriptions); the pure logic already lives in live_view_model.py and the page in lane_live_view.html, covered by test_lane_live_view*.py and test_live_view_model.py (X5)",
    ),
    "control": (
        32_106,
        f"split: deploy closure needs only sensing + safety provider (P1a); {CONTROL_SPLIT}",
    ),
}

WORKSPACE_REF_PATTERNS = (
    re.compile(r"get_package_share_directory\(\s*['\"](\w+)['\"]"),
    re.compile(r"FindPackageShare\(\s*['\"](\w+)['\"]"),
    re.compile(r"\$\(find-pkg-share\s+(\w+)\)"),
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
    return parts[1] if len(parts) == 3 and parts[0] == "devices" else None


# D-241 and D-242: the ROS package name stays. These directories use the role name.
ROLE_DIR = {
    "core": ("runtime", "gateway"),
    "core_events": ("runtime", "events"),
    "core_features": ("runtime", "services"),
    "core_api_web": ("runtime", "api_web"),
    "core_common": ("contracts", "foundation"),
    "control": ("runtime", "sensing"),
    "web_common": ("hmi", "web"),
    "emotion": ("hmi", "face"),
    "omx_adapter": ("devices", "omx", "adapter"),
    "lamp_control": ("devices", "pinky_pro", "lamp"),
    "sensor_adc": ("devices", "pinky_pro", "adc"),
}


def layout_ok(rel: tuple, name: str) -> bool:
    """P2(a) + D-196 + D-241: role folders for the core packages, family folders for devices."""
    if not rel or rel[0] not in DOMAINS:
        return False
    if name in ROLE_DIR:
        return rel == ROLE_DIR[name]
    if rel[0] == "devices":
        return len(rel) == 3 and rel[2] == name
    return len(rel) == 2 and rel[1] == name


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
    for path in _files(name, {".py", ".xml", ".cpp", ".hpp"}):
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
    """P4 direction table (D-168, D-196). Pure, so rows are testable before packages move."""
    if target in CORE_CONTRACTS:
        return True
    if src_domain == "core":
        return dst_domain == "core"
    if src_domain == "sim":
        return True
    if src_domain == "devices":
        if dst_domain == "sim" and target == "description":
            return True
        return bool(src_family) and dst_domain == "devices" and dst_family in (src_family, "common")
    if src_domain == "navigation":
        return dst_domain == "devices"
    return False


def _allowed(source: str, target: str) -> bool:
    src_domain, dst_domain = _domain(source), _domain(target)
    if source == "navigation" and dst_domain == "devices":
        return True
    if src_domain == "runtime" and dst_domain == "runtime":
        return True
    # D-243: the API package serves the operator screens and nothing else in runtime does.
    if source == "core_api_web" and target == "dashboard":
        return True
    return edge_allowed(src_domain, _family(source), dst_domain, _family(target), target)


def _lines(path: Path) -> int:
    with path.open("rb") as handle:
        return sum(1 for _ in handle)


def test_the_scan_sees_the_whole_tree():
    assert len(PACKAGES) >= 20, sorted(PACKAGES)


def test_every_package_sits_in_a_domain_group_under_its_own_name():
    """P2(a) + D-147 + D-196: src/<domain>/<package>/, directory name = package name.

    devices nest one level deeper: src/devices/<family>/<package>/.
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


def _over_budget() -> dict:
    over = {}
    for name in PACKAGES:
        total = 0
        for path in _files(name, CODE_SUFFIXES):
            count = _lines(path)
            total += count
            if count > FILE_BUDGET:
                over[path.relative_to(SRC).as_posix()] = count
        if total > PACKAGE_BUDGET:
            over[name] = total
    return over


def test_over_budget_code_has_a_recorded_verdict():
    """P6: every file > 600 lines and package > 10k lines has a verdict, and no stale ones."""
    over = _over_budget()
    assert set(over) == set(SIZE_VERDICTS), (
        f"needs a verdict: {sorted((k, over[k]) for k in set(over) - set(SIZE_VERDICTS))}, "
        f"stale: {sorted(set(SIZE_VERDICTS) - set(over))}"
    )


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
        if key in over and over[key] > at_verdict + REGROWTH_ALLOWANCE:
            bad.append(f"{key}: {over[key]} lines, grew past {at_verdict}+{REGROWTH_ALLOWANCE}; re-judge")
    assert bad == [], bad


@pytest.mark.parametrize(
    "src_domain, src_family, dst_domain, dst_family, target, ok",
    [
        ("devices", "pinky_pro", "devices", "pinky_pro", "description", True),
        ("devices", "pinky_pro", "devices", "common", "imu_bno055", True),
        ("devices", "pinky_pro", "devices", "omx", "omx_adapter", False),
        ("devices", "omx", "devices", "pinky_pro", "description", False),
        ("devices", "omx", "core", None, "core_common", True),
        ("devices", "omx", "core", None, "core", False),
        ("navigation", None, "devices", "pinky_pro", "bringup", True),
        ("navigation", None, "hardware", None, "bringup", False),
        ("navigation", None, "apps", None, "control", False),
        ("apps", None, "devices", "common", "imu_bno055", False),
    ],
)
def test_direction_table_rows_for_devices_and_robots(src_domain, src_family, dst_domain, dst_family, target, ok):
    """D-196 P4 rows, checked before any package moves into them."""
    assert edge_allowed(src_domain, src_family, dst_domain, dst_family, target) is ok


@pytest.mark.parametrize(
    "rel, name, ok",
    [
        (("devices", "pinky_pro", "bringup"), "bringup", True),
        (("devices", "bringup"), "bringup", False),
        (("products", "pinky_pro"), "pinky_pro", True),
        (("runtime", "sensing"), "control", True),
        (("runtime", "control"), "control", False),
        (("core", "control"), "control", False),
        (("apps", "x", "control"), "control", False),
    ],
)
def test_layout_rule_allows_a_family_level_only_under_devices(rel, name, ok):
    """P2(a) + D-196: src/<domain>/<package>, except src/devices/<family>/<package>."""
    assert layout_ok(rel, name) is ok
