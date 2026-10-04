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


FLEET_PKG = Path(__file__).resolve().parents[1] / "fleet"
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
