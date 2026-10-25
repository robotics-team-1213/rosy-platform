"""설계 §Architecture: `fleet.formation` 은 숫자만 다룬다. 전송·ROS·swarm 을
import 하면 순수 함수가 아니게 되고 Windows pytest 도 깨진다."""

import ast
from pathlib import Path

import pytest

FORMATION_DIR = Path(__file__).resolve().parents[1] / "fleet" / "formation"
SWARM_DIR = Path(__file__).resolve().parents[1] / "fleet" / "swarm"
FORBIDDEN = ("httpx", "websockets", "rclpy", "fleet.swarm", "asyncio")
#: `arming` 은 `swarm` 안에 있으므로 형제를 import 해도 되지만, 전송과 스케줄링은
#: 안 된다. 순수해야 세션이 릴레이를 만지기 **전에** 부를 수 있다.
ARMING_FORBIDDEN = ("httpx", "websockets", "rclpy", "asyncio")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


@pytest.mark.parametrize("module", sorted(p.name for p in FORMATION_DIR.glob("*.py")))
def test_formation_modules_import_no_transport(module):
    names = _imports(FORMATION_DIR / module)
    for name in names:
        assert not name.startswith(FORBIDDEN), f"{module} imports {name}"


def test_arming_stays_pure_so_the_plan_can_run_before_the_relay_is_touched():
    """사전 점검이 전송이나 태스크를 알기 시작하면 릴레이보다 먼저 돌 수 없게 된다 —
    그러면 거절되는 reform 이 다시 멀쩡한 대형을 멈춘 채로 남긴다."""
    names = _imports(SWARM_DIR / "arming.py")
    for name in names:
        assert not name.startswith(ARMING_FORBIDDEN), f"arming.py imports {name}"


REPO = Path(__file__).resolve().parents[3]
FLEET_PKG = Path(__file__).resolve().parents[1] / "fleet"
WORLD_PROJECTION = REPO / "operations/world/src/rosy/world/state/projections/map_pose.py"
HUB_DIR = FLEET_PKG / "hub"
CORE_FORBIDDEN_PREFIXES = (
    "rclpy",
    "core.command",
    "core.bridge",
    "core.safety",
    "core.navigation",
    "core.api",
)


def _py_files(root: Path):
    return sorted(p for p in root.rglob("*.py") if p.name != "__pycache__")


def test_fleet_package_never_imports_rclpy():
    for path in _py_files(FLEET_PKG):
        for name in _imports(path):
            assert name != "rclpy" and not name.startswith("rclpy."), f"{path.name} imports {name}"


def test_fleet_package_never_imports_games():
    """D-106: 매치 시작이 생겨도 지금은 games를 모른다."""
    for path in _py_files(FLEET_PKG):
        for name in _imports(path):
            assert name != "games" and not name.startswith("games."), path.name


def test_hub_may_import_only_protocol_schemas_from_core():
    if not HUB_DIR.exists():
        pytest.fail("hub package missing — Task 4 creates it; this test should fail until then")
    for path in _py_files(HUB_DIR):
        for name in _imports(path):
            if name == "core" or name.startswith("core."):
                assert name == "core_common.protocol.schemas", f"{path.name} imports {name}"
            for banned in CORE_FORBIDDEN_PREFIXES:
                assert name != banned and not name.startswith(banned + "."), path.name


LOCALIZATION_DIR = Path(__file__).resolve().parents[1] / "fleet" / "localization"
#: D-395: the arbiter is scoring only. The service loop that talks to robots lives
#: in server/ (Phase 2) and calls in; the arbiter never calls out.
LOCALIZATION_FORBIDDEN = FORBIDDEN + ("fleet.server", "fastapi")


@pytest.mark.parametrize("module", sorted(p.name for p in LOCALIZATION_DIR.glob("*.py")))
def test_localization_arbiter_modules_import_no_transport(module):
    for name in _imports(LOCALIZATION_DIR / module):
        assert not name.startswith(LOCALIZATION_FORBIDDEN), f"{module} imports {name}"


#: D-457 5: overhead tracking is display only. Besides its own modules, only the app wiring,
#: the console state route (which hands it robot states) and the CLI may name it.
#: tracking_drift.py is one of its own modules (the server-side calibration-drift watch).
TRACKING_IMPORTERS = {"server/app.py", "server/console/console_routes.py", "server/tracking/tracking.py",
                      "server/tracking/tracking_routes.py", "server/tracking/tracking_drift.py",
                      "server/tracking/measured_calibration.py", "cli.py"}


def _server_imports(source: str, stem: str) -> list[str]:
    """Every import in ``source`` that names a fleet.server module starting with ``stem``, in any spelling."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [alias.name for alias in node.names
                      if alias.name.startswith("fleet.server.")
                      and alias.name.rsplit(".", 1)[-1].startswith(stem)]
        elif isinstance(node, ast.ImportFrom):
            module = node.module
            # An absolute module outside fleet (core_common.identity) is another package.
            if (module is not None and module.rsplit(".", 1)[-1].startswith(stem)
                    and (node.level > 0 or module.startswith(("fleet.", "server.")))):
                found.append(module)
            elif module in (None, "fleet.server", "server"):
                found += [f"{module or '.'}:{alias.name}" for alias in node.names
                          if alias.name.startswith(stem)]
    return found


def _tracking_imports(source: str) -> list[str]:
    return _server_imports(source, "tracking")


@pytest.mark.parametrize("snippet", [
    "from fleet.server import tracking",
    "from . import tracking",
    "from .server.tracking import TrackingService",
    "from .tracking_match import match",
    "import fleet.server.tracking_calibration",
])
def test_tracking_import_guard_sees_every_spelling(snippet):
    assert _tracking_imports(snippet) != []


def test_tracking_import_guard_ignores_unrelated_names():
    assert _tracking_imports("from fleet.server import traffic\nfrom . import bays\nimport json") == []


def test_traffic_bays_missions_and_localization_never_read_overhead_tracking():
    offenders = []
    for path in _py_files(FLEET_PKG):
        rel = path.relative_to(FLEET_PKG).as_posix()
        if rel in TRACKING_IMPORTERS:
            continue
        offenders += [f"{rel} imports {name}"
                      for name in _tracking_imports(path.read_text(encoding="utf-8"))]
    assert offenders == []


#: D-472 addendum 3: a LED-confirmed track feeds D-511 lane compliance and the console only.
#: Map pose arbitration, trips, initialpose, routes, bays, formations and commands never read it,
#: neither by import nor through the wiring attributes ``tracking.identity`` / ``app.state.identity``.
IDENTITY_READERS = {"server/app.py", "server/console/console_routes.py", "server/recognition/identity.py",
                    "server/tracking/tracking.py", "server/tracking/tracking_routes.py", "server/recognition/sightings_config.py",
                    "server/pose/lane_compliance_service.py"}
#: Never on that list: the D-494 map pose arbitration and the trip loop (addendum 3).
IDENTITY_NEVER = ("server/pose/map_pose_service.py", "server/trips/trip_*.py", "server/trip_checks/trip_*.py", "server/trip_progress/trip_*.py",
                  "routing/execute.py")


def _identity_reads(source: str) -> list[str]:
    found = _server_imports(source, "identity")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute) and node.attr == "identity":
            owner = node.value
            name = owner.attr if isinstance(owner, ast.Attribute) else getattr(owner, "id", None)
            if isinstance(name, str) and name.lstrip("_") in ("tracking", "state"):
                found.append(f"{name}.identity")
        elif (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "getattr"
              and len(node.args) >= 2 and getattr(node.args[1], "value", None) == "identity"):
            found.append("getattr(..., 'identity')")
    return found


@pytest.mark.parametrize("snippet", [
    "from fleet.server.identity import IdentityService",
    "from .identity import IdentityService",
    "from . import identity",
    "from fleet.server import identity",
    "import fleet.server.identity",
    "pose = tracking.identity.confirmed_track_pose('rosy_26')",
    "pose = self._tracking.identity",
    "service = app.state.identity",
    "service = getattr(app.state, 'identity', None)",
])
def test_identity_guard_sees_relative_imports_and_attribute_reads(snippet):
    assert _identity_reads(snippet) != []


def test_identity_guard_ignores_unrelated_identities():
    assert _identity_reads("from core_common.identity import ROBOT_ID_PATTERN\n"
                           "key = self.identity.fingerprint\nrid = svc.identity_id") == []


def test_only_the_wiring_and_lane_compliance_read_the_led_identity_binding():
    offenders = []
    for path in _py_files(FLEET_PKG):
        rel = path.relative_to(FLEET_PKG).as_posix()
        if rel in IDENTITY_READERS:
            continue
        offenders += [f"{rel} reads {name}" for name in _identity_reads(path.read_text(encoding="utf-8"))]
    assert offenders == []


def test_map_pose_and_trip_modules_never_read_the_led_identity_binding():
    """D-511 lane compliance may judge a LED-confirmed track; MapPoseService and trips may not."""
    paths = sorted({p for pattern in IDENTITY_NEVER for p in FLEET_PKG.glob(pattern)})
    assert len(paths) >= 5                                   # the globs still find the modules
    assert WORLD_PROJECTION.is_file()
    paths.append(WORLD_PROJECTION)
    offenders = []
    for path in paths:
        rel = (path.relative_to(FLEET_PKG) if path.is_relative_to(FLEET_PKG)
               else path.relative_to(REPO)).as_posix()
        assert rel not in IDENTITY_READERS, rel
        text = path.read_text(encoding="utf-8")
        offenders += [f"{rel} reads {name}" for name in _identity_reads(text)]
        offenders += [f"{rel} imports {name}" for name in _tracking_imports(text)]
        if "confirmed_track_pose" in text:
            offenders.append(f"{rel} reads confirmed_track_pose")
    assert offenders == []


@pytest.fixture
def formation_api_tree(tmp_path, monkeypatch):
    root = tmp_path / "fleet"
    files = {
        "__init__.py": "",
        "formation/__init__.py": "",
        "formation/geometry.py": "import math\n",
        "swarm/__init__.py": "",
        "swarm/api/__init__.py": "",
        "swarm/api/types.py": "class Point: pass\n",
        "swarm/api/ports.py": "from .types import Point\nclass RobotClient: pass\n",
    }
    for relative, source in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    monkeypatch.setitem(globals(), "FORMATION_DIR", root / "formation")
    return root


@pytest.mark.parametrize("source", [
    "from fleet.swarm.api.types import Point as Position\n",
    "import fleet.swarm.api.ports as contracts\n",
    "from fleet.swarm.api import types as data, ports as contracts\n",
    "from ..swarm.api.types import Point\n",
    "from ..swarm.api import ports as contracts\n",
    "from fleet.swarm.api.ports import RobotClient\n",
])
def test_formation_boundary_accepts_only_neutral_api_leaves(formation_api_tree, source):
    (formation_api_tree / "formation/geometry.py").write_text(source, encoding="utf-8")
    test_formation_modules_import_no_transport("geometry.py")


@pytest.mark.parametrize("relative", [
    "formation/geometry.py", "swarm/api/types.py", "swarm/api/ports.py",
    "__init__.py", "swarm/__init__.py", "swarm/api/__init__.py",
])
@pytest.mark.parametrize("source", [
    "import httpx as client\n",
    "from websockets import connect as connect_socket\n",
    "import rclpy as ros\n",
    "from asyncio import create_task as schedule\n",
    "from fleet.swarm import relay as delivery\n",
])
def test_formation_boundary_rejects_forbidden_imports_in_each_fixed_file(
        formation_api_tree, relative, source):
    (formation_api_tree / relative).write_text(source, encoding="utf-8")
    with pytest.raises(AssertionError):
        test_formation_modules_import_no_transport("geometry.py")


@pytest.mark.parametrize("relative, source", [
    ("formation/geometry.py", "from fleet import swarm as network\n"),
    ("formation/geometry.py", "from fleet.swarm import transport as wire\n"),
    ("formation/geometry.py", "from ..swarm import transport as wire\n"),
    ("formation/geometry.py", "import fleet.swarm.api_extra as extra\n"),
    ("formation/geometry.py", "from fleet.swarm.api_extra import types\n"),
    ("formation/geometry.py", "import fleet.swarm.api\n"),
    ("formation/geometry.py", "from fleet.swarm import api\n"),
    ("formation/geometry.py", "from fleet.swarm.api import *\n"),
    ("swarm/api/types.py", "from .. import relay as delivery\n"),
    ("swarm/api/ports.py", "from . import relay as delivery\n"),
    ("__init__.py", "from .swarm import transport as wire\n"),
    ("swarm/__init__.py", "from . import transport as wire\n"),
    ("swarm/api/__init__.py", "from .. import transport as wire\n"),
])
def test_formation_boundary_resolves_members_relatives_and_exact_leaf_names(
        formation_api_tree, relative, source):
    (formation_api_tree / relative).write_text(source, encoding="utf-8")
    with pytest.raises(AssertionError):
        test_formation_modules_import_no_transport("geometry.py")


@pytest.mark.parametrize("relative", [
    "swarm/api/types.py", "swarm/api/ports.py", "__init__.py",
    "swarm/__init__.py", "swarm/api/__init__.py",
])
def test_formation_boundary_requires_every_fixed_api_file(formation_api_tree, relative):
    (formation_api_tree / relative).unlink()
    with pytest.raises(OSError):
        test_formation_modules_import_no_transport("geometry.py")
