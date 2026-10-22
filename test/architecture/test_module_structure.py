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
- Packages are found under every ``colcon_roots`` entry and placed relative to
  their root: ``learning/envs/isaac`` (``isaac_sim``, D-427 wave 1) is domain ``envs``.
- Dynamic imports (``importlib.import_module``, entry points) are invisible.
  The one intended case is core loading ``rosy.sensor_provider`` (D-126).
- P6 limits are absolute (D-766, replacing D-362's 1000-line tier): 600 for production
  ``.py``/``.cpp``/``.hpp``/``.sh``/``.kt``, 800 for web assets (``.js``/``.mjs``/``.ts``/``.html``/``.css``),
  across the colcon-root packages, the ``STANDALONE`` roots and the ``OPS_ROOTS``, 10,000 per size
  unit. Every tracked code file under those roots is measured (``SIZE_UNMEASURED`` is the exception). What is already over is
  frozen in ``size_ratchet.txt``. Test code and data files are exempt. Line counts are physical
  lines, blank lines and comments included.
"""

import ast
import datetime as dt
import importlib.util
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "harness"))  # also when run as a script
import size_limits  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"

#: ``envs`` is the first folder under the ``learning`` colcon root (D-427 wave 1);
#: ``apps``, ``vision`` and ``processes`` are under the ``operations`` root (D-427 wave 3b).
DOMAINS = {"contracts", "runtime", "drivers", "products", "hmi", "site", "sim", "envs",
           "apps", "vision", "processes", "fleet", "ui", "web", "core", "simulation",
           "foundation", "ros_idl", "perception", "devices", "drive", "robot_ui", "site_ui", "overhead", "signal_observation"}

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

#: P6 size limits (D-766: absolute 600/800/10,000 lines, over-limit frozen by a down-only ratchet).
#: The counting rule lives in tools/harness/size_limits.py, shared with the per-commit range
#: check (tools/harness/size_range.py). The units and the ratchet are data files beside this test,
#: so registering a unit or lowering a row is not a FULL landing (affected_tests NOT_TRIGGERS).
SIZE_UNITS, SMALL_UNITS = size_limits.parse_units((ROOT / size_limits.UNITS).read_text(encoding="utf-8"))
RATCHET, SAFETY_ROWS = size_limits.parse_ratchet((ROOT / size_limits.RATCHET).read_text(encoding="utf-8"))

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


#: D-427 wave 0 item 5: every colcon root in the platform manifest.
COLCON_ROOTS = tuple(ROOT / root for root in yaml.safe_load(
    (ROOT / "tools" / "harness" / "platform_parts.yaml").read_text(encoding="utf-8"))["colcon_roots"])
#: An empty walk passes every per-package rule; today the roots hold 27 packages.
MIN_PACKAGES = 27


def _rel(path: Path) -> Path:
    """``path`` relative to the colcon root that holds it (``src``, ``learning`` or ``operations``)."""
    return path.relative_to(next(root for root in COLCON_ROOTS if path.is_relative_to(root)))


def _is_prod(path: Path) -> bool:
    parts = _rel(path).parts
    return not any(p in ("test", "tests", "build", "install", "log") or p.startswith(".") for p in parts)


def _packages():
    found = {}
    for package_xml in sorted(xml for base in COLCON_ROOTS for xml in base.rglob("package.xml")):
        if not _is_prod(package_xml):
            continue
        root = ET.parse(package_xml).getroot()
        found[root.findtext("name")] = {"dir": package_xml.parent, "xml": root}
    assert len(found) >= MIN_PACKAGES, sorted(found)
    return found


PACKAGES = _packages()


#: D-427: packages leave the D-310 src/ domains for the D-427 parts, but the P4 direction
#: table still judges each package by the D-310 role it had there (name -> (domain, family)).
#: Package names are frozen (D-231), so this table does not move with the folders.
D310_ROLE = {
    "core": ("runtime", None), "core_events": ("runtime", None), "core_features": ("runtime", None),
    "core_api_web": ("runtime", None), "control": ("runtime", None), "navigation": ("runtime", None),
    "core_common": ("contracts", None), "interfaces": ("contracts", None),
    "web_common": ("hmi", None), "emotion": ("hmi", None), "dashboard": ("hmi", None), "pilot": ("hmi", None),
    "pinky_pro": ("products", "pinky_pro"), "bringup": ("products", "pinky_pro"),
    "sensor_adc": ("products", "pinky_pro"), "lamp_control": ("products", "pinky_pro"),
    "led": ("products", "pinky_pro"), "omx": ("products", "omx"), "omx_adapter": ("products", "omx"),
    "imu_bno055": ("drivers", None), "description": ("sim", None), "gz_sim": ("sim", None),
}


def _domain(name: str) -> str:
    if name in D310_ROLE:
        return D310_ROLE[name][0]
    return _rel(PACKAGES[name]["dir"]).parts[0]


def _family(name: str):
    if name in D310_ROLE:
        return D310_ROLE[name][1]
    parts = _rel(PACKAGES[name]["dir"]).parts
    return parts[1] if len(parts) == 3 and parts[0] == "products" else None


# D-241 and D-242: the ROS package name stays. These directories use the role name.
ROLE_DIR = {
    # D-427 wave 4d: middleware/core/<role>, contracts/foundation, contracts/ros_idl.
    "core": ("core", "gateway"),
    "core_events": ("core", "events"),
    "core_features": ("core", "services"),
    "core_api_web": ("core", "api"),  # D-626 holder; package identity stays core_api_web
    "core_common": ("foundation",),
    "interfaces": ("ros_idl",),
    "control": ("perception",),  # middleware/perception (D-427 wave 4e)
    "web_common": ("web",),  # shared/web (D-427 wave 4b)
    "emotion": ("robot_ui", "face"),  # middleware/robot_ui/face (D-427 wave 4b)
    "dashboard": ("robot_ui", "robot"),  # middleware/robot_ui/robot (D-427 wave 4b)
    # D-427 wave 4c: middleware/apps/device/<robot>/<role>, middleware/drivers/<robot>_<role>.
    "pinky_pro": ("devices", "pinky", "profile"),
    "bringup": ("devices", "pinky", "bringup"),
    "description": ("devices", "pinky", "description"),
    "sensor_adc": ("drivers", "pinky_adc"),
    "lamp_control": ("drivers", "pinky_lamp"),
    "led": ("drivers", "pinky_led"),
    "omx": ("devices", "omx", "profile"),
    "omx_adapter": ("devices", "omx", "adapter"),
    "imu_bno055": ("drivers", "imu_bno055"),
    "navigation": ("drive", "planning", "nav2"),
    "gz_sim": ("simulation", "gazebo"),
    "isaac_sim": ("envs", "isaac"),  # learning/envs/isaac (D-427 wave 1)
    "rosy_vision": ("overhead",),  # operations/overhead (D-427 wave 3b)
    "fleet": ("fleet",),  # operations/fleet (D-427 wave 3c)
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
    holders = (ROOT / holder for holder in size_limits.PACKAGE_HOLDERS.get(name, ()))
    for directory in (PACKAGES[name]["dir"], *holders):
        for path in directory.rglob("*"):
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
                used.setdefault(top, f"{_rel(path).as_posix()} imports {top}")
    for path in _files(name, {".py", ".xml", ".cpp", ".hpp", ".yaml",
                               ".urdf", ".xacro", ".sdf", ".world", ".rviz"}):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in WORKSPACE_REF_PATTERNS:
            for match in pattern.finditer(text):
                used.setdefault(match.group(1), f"{_rel(path).as_posix()} references {match.group(1)}")
        if "launch" in _rel(path).parts or ".launch." in path.name:
            for pattern in LAUNCH_EXEC_PATTERNS:
                for match in pattern.finditer(text):
                    used.setdefault(match.group(1), f"{_rel(path).as_posix()} runs {match.group(1)}")
        if path.suffix in {".cpp", ".hpp"}:
            for match in re.finditer(r"#include\s*[<\"](\w+)/", text):
                used.setdefault(match.group(1), f"{_rel(path).as_posix()} includes {match.group(1)}")
    return {top: site for top, site in used.items() if top in PACKAGES and top != name}


def edge_allowed(src_domain, src_family, dst_domain, dst_family, target) -> bool:
    """P4 direction table (D-168, D-310). Pure, so rows are testable."""
    if target in CORE_CONTRACTS:
        return True
    if src_domain == "core":
        return dst_domain == "core"
    if src_domain in ("sim", "envs"):  # envs: Isaac moved out of sim (D-427 wave 1)
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
        rel = _rel(info["dir"]).parts
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


def _measure() -> tuple[dict, dict, dict]:
    dirs = {**{name: _relpath(info["dir"]) for name, info in PACKAGES.items()}, **size_limits.STANDALONE}
    files, scripts = {}, {}
    for folder in {*dirs.values(), *(h for hs in size_limits.PACKAGE_HOLDERS.values() for h in hs),
                   *size_limits.OPS_ROOTS, "test"}:  # test: the root suite (revision 2 test limit)
        for path in (ROOT / folder).rglob("*"):
            if path.is_file() and path.suffix in size_limits.CODE_SUFFIXES | size_limits.WEB_SUFFIXES:
                files[_relpath(path)] = _lines(path)
                if path.suffix == ".html":
                    scripts[_relpath(path)] = size_limits.inline_script_lines(
                        path.read_text(encoding="utf-8", errors="replace"))
    return size_limits.measure(files, dirs, [_relpath(root) for root in COLCON_ROOTS], SIZE_UNITS, scripts)


def _relpath(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _git(*args: str) -> str | None:
    try:
        done = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    except OSError:
        return None
    return done.stdout if done.returncode == 0 else None


def _base() -> str | None:
    """D-766 4 base: the newest of ``ROSY_SIZE_BASE`` and the merge-bases with main and origin/main
    whose tree has the ratchet, else the nearest first-parent ancestor that has it. None only when
    no ancestor has it (the landing commit itself). No git history fails, never skips."""
    if _git("rev-parse", "HEAD") is None:
        pytest.fail("the D-766 size ratchet needs git and the repository history")
    candidates = {os.environ.get("ROSY_SIZE_BASE", "").strip(),
                  *((_git("merge-base", "HEAD", ref) or "").strip() for ref in ("main", "origin/main"))} - {""}
    found = [sha for sha in candidates if _git("cat-file", "-e", f"{sha}:{size_limits.RATCHET}") is not None]
    if found:
        return max(found, key=lambda sha: int(_git("log", "-1", "--format=%ct", sha)))
    # Nearest first-parent ancestor with the ratchet. A merge of pre-D-766 history (a parent
    # without it) is the transition: it is the base for later commits and has no base itself.
    for index, sha in enumerate((_git("rev-list", "--first-parent", "HEAD") or "").split()):
        if _git("cat-file", "-e", f"{sha}:{size_limits.RATCHET}") is None:
            return None
        parents = _git("rev-list", "--parents", "-n", "1", sha).split()[1:]
        if len(parents) > 1 and any(_git("cat-file", "-e", f"{p}:{size_limits.RATCHET}") is None for p in parents):
            return sha if index else None
        if index:
            return sha
    return None


def _base_text(path: str) -> str | None:
    base = _base()
    return _git("show", f"{base}:{path}") if base else None


def _safety_commit(key: str):
    """(date, has trailer) of the commit that added ``key``'s safety row."""
    allowed, expiry = SAFETY_ROWS[key]
    row = f"safety {allowed} {key} {expiry.isoformat()}"
    sha = (_git("log", "-1", "--format=%H", "-S", row, "--", size_limits.RATCHET) or "").strip()
    if not sha:
        return None
    date, _, message = (_git("log", "-1", "--format=%cs%n%B", sha) or "").partition("\n")
    return dt.date.fromisoformat(date), bool(re.search(r"^Safety-Review:[ \t]*\S", message, re.M))


def test_ratchet_rows_are_the_measured_counts_and_only_go_down():
    """D-766 1/4/8: over-limit set == ratchet keys, rows == measured, never above the base, no new rows."""
    _, over, _ = _measure()
    base = _base_text(size_limits.RATCHET)
    base_rows, base_safety = size_limits.parse_ratchet(base) if base is not None else (None, None)
    bad = size_limits.ratchet_problems(over, RATCHET, SAFETY_ROWS, base_rows, dt.date.today(), _safety_commit,
                                       base_safety=base_safety)
    assert bad == [], "\n".join(bad)


def _holders() -> set[str]:
    """D-766 7(a): folders that count as a unit without ``__init__.py`` (repo-relative)."""
    found = set()
    for layout, names in (("operations/fleet/fleet/_source_layout.py", ("SERVER_HOLDERS",)),
                          ("middleware/perception/control/_source_layout.py",
                           ("PACKAGE_DIRS", "FLAT_ROOTS", "CONTROL_ROOTS", "RUNTIME_ROOT"))):
        spec = importlib.util.spec_from_file_location(f"_size_layout_{len(found)}", ROOT / layout)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for name in names:
            value = getattr(module, name)
            for item in (value.values() if isinstance(value, dict) else value if isinstance(value, tuple) else (value,)):
                path = (ROOT / layout).parent / "server" / item if isinstance(item, str) else Path(item)
                found.add(_relpath(path.resolve()))
    found.update(h for hs in size_limits.PACKAGE_HOLDERS.values() for h in hs)
    for info in PACKAGES.values():  # CMake install(DIRECTORY ...) folders ship as a unit
        cmake = info["dir"] / "CMakeLists.txt"
        if cmake.is_file():
            for block in re.findall(r"install\(\s*DIRECTORY\s+(.*?)\s+DESTINATION", cmake.read_text(encoding="utf-8-sig"), re.S):
                found.update(_relpath(info["dir"] / folder) for folder in block.split())
    return found


def _kotlin_package(directory: Path) -> bool:
    source_root = next((p for p in directory.parents if p.name in ("java", "kotlin")
                        and p.parent.name == "main" and p.parent.parent.name == "src"), None)
    if source_root is None:
        return False
    package = ".".join(directory.relative_to(source_root).parts)
    files = list(directory.glob("*.kt"))
    declaration = re.compile(r"^package[ \t]+" + re.escape(package) + r"[ \t]*;?[ \t]*$", re.M)
    return bool(files) and all(declaration.search(p.read_text(encoding="utf-8")) for p in files)


@pytest.mark.parametrize("source_root, package, expected", [
    ("src/main/java", "io.example.cam.ui", True),
    ("src/main/kotlin", "io.example.cam.ui", True),
    ("src/main/java", "io.example.cam", False),
    ("src/androidTest/java", "io.example.cam.ui", False),
    ("other", "io.example.cam.ui", False),
    ("src/main/java", None, False),
])
def test_kotlin_size_unit_requires_its_production_package_path(tmp_path, source_root, package, expected):
    directory = tmp_path / source_root / "io/example/cam/ui"
    directory.mkdir(parents=True)
    if package is not None:
        (directory / "Screen.kt").write_text(f"package {package}\n\nfun screen() = Unit\n", encoding="utf-8")
    assert _kotlin_package(directory) is expected


def test_size_units_are_real_and_meet_the_floor():
    """D-766 3/7(a): a unit is a subpackage or declared holder that counts lines; a new unit is
    1,000 lines or more when its parent was 2,000 or more; SMALL_UNITS only shrink."""
    counts, _, owner = _measure()
    holders = _holders()
    base = _base_text(size_limits.UNITS)
    base_small = size_limits.parse_units(base)[1] if base is not None else SMALL_UNITS
    bad = []
    for unit in SIZE_UNITS:
        dirs = [root / unit for root in COLCON_ROOTS if (root / unit).is_dir()]
        if not any((d / "__init__.py").is_file() or _kotlin_package(d) or _relpath(d) in holders for d in dirs):
            bad.append(f"{unit}: neither a Python/Kotlin subpackage nor a declared holder under a colcon root")
    bad += size_limits.unit_problems(counts, owner, SIZE_UNITS, SMALL_UNITS, base_small)
    assert bad == [], bad


#: Tracked code under the product roots that no unit, package or ops root measures, with the reason.
SIZE_UNMEASURED = {}


def test_every_product_code_file_is_measured():
    """D-766 coverage addendum: each tracked code file under a colcon or ops root is counted."""
    assert {".py", ".js", ".ts", ".mjs", ".html", ".css", ".sh", ".kt"} <= size_limits.CODE_SUFFIXES | size_limits.WEB_SUFFIXES
    _, _, owner = _measure()
    roots = (*(_relpath(root) for root in COLCON_ROOTS), *size_limits.OPS_ROOTS)
    tracked = (_git("ls-files", *roots) or "").splitlines()
    unmeasured = {path for path in tracked
                  if PurePosixPath(path).suffix in size_limits.CODE_SUFFIXES | size_limits.WEB_SUFFIXES
                  and size_limits.is_prod(PurePosixPath(path).parts[1:]) and path not in owner}
    assert unmeasured == set(SIZE_UNMEASURED), (
        f"unmeasured (register a unit, STANDALONE or OPS_ROOTS): {sorted(unmeasured - set(SIZE_UNMEASURED))}, "
        f"stale: {sorted(set(SIZE_UNMEASURED) - unmeasured)}")


def test_fleet_holders_are_its_source_roots():
    """fleet's PACKAGE_HOLDERS are the folders fleet/_source_layout.py loads (SOURCE_ROOTS)."""
    spec = importlib.util.spec_from_file_location("_fleet_layout", ROOT / "operations/fleet/fleet/_source_layout.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert {_relpath(Path(path).resolve()) for path in module.SOURCE_ROOTS.values()} == set(
        size_limits.PACKAGE_HOLDERS["fleet"])


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
        (("devices", "pinky", "bringup"), "bringup", True),
        (("devices", "pinky", "profile"), "pinky_pro", True),
        (("apps", "device", "pinky", "bringup"), "bringup", False),
        (("devices", "omx", "adapter"), "omx_adapter", True),
        (("drive", "planning", "nav2"), "navigation", True),
        (("control", "drive", "planning", "nav2"), "navigation", False),
        (("core", "navigation"), "navigation", False),
        (("apps", "device", "omx", "adapter"), "omx_adapter", False),
        (("drivers", "imu_bno055"), "imu_bno055", True),
        (("devices", "pinky_pro", "bringup"), "bringup", False),
        (("devices", "bringup"), "bringup", False),
        (("products", "pinky_pro"), "pinky_pro", False),
        (("products", "omx", "bringup"), "bringup", False),
        (("perception",), "control", True),
        (("runtime", "control"), "control", False),
        (("core", "control"), "control", False),
        (("apps", "x", "control"), "control", False),
    ],
)
def test_layout_rule_allows_declared_product_packages_and_standalone_drivers(rel, name, ok):
    """P2(a) + D-310: product packages require explicit family ownership."""
    assert layout_ok(rel, name) is ok


if __name__ == "__main__":  # rewrite the measured rows: never above a row, safety keys keep theirs
    path = ROOT / size_limits.RATCHET
    path.write_text(size_limits.regenerate(path.read_text(encoding="utf-8"), _measure()[1]),
                    encoding="utf-8", newline="\n")
