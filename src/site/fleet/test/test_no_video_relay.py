"""D-136 T1: Fleet은 영상을 중계하지 않는다.

- gather/scatter 경로에 이미지 바이트 혼입 금지: fleet 패키지 생산 코드가
  영상 라이브러리·ROS 이미지 메시지를 import하지 않는다.
- 서버에 영상 프록시/중계 라우트 없음: 라우트 표를 열거해 비디오·스트림·
  카메라·프리뷰·프록시·릴레이 경로가 없음을 단언한다.
"""

import ast
import re
from pathlib import Path

from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.swarm.robots import RobotEndpoint

SRC = Path(__file__).resolve().parents[1]

FORBIDDEN_IMPORTS = frozenset({"cv2", "sensor_msgs", "ffmpeg", "av", "picamera2", "PIL"})

FORBIDDEN_ROUTE = re.compile(r"video|stream|camera|preview|proxy|relay|mjpeg|jpeg|image",
                             re.IGNORECASE)


def _prod_files():
    root = SRC / "fleet"
    for path in sorted(root.rglob("*.py")):
        if "test" in path.parts:
            continue
        yield path


def _imported_top_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_fleet_production_imports_no_video_libraries():
    """D-136 T1: gather/scatter 경로에 이미지 바이트의 입구가 없다."""
    violations = {}
    for path in _prod_files():
        hit = _imported_top_names(path) & FORBIDDEN_IMPORTS
        if hit:
            violations[str(path.relative_to(SRC))] = sorted(hit)
    assert not violations, f"fleet production imports video libraries: {violations}"


def test_fleet_server_has_no_video_relay_routes():
    """D-136 T1: 풀영상은 dashboard→로봇 직결. Fleet은 시그널링만 한다."""
    endpoints = [RobotEndpoint(robot_id="rosy_01", base_url="http://127.0.0.1:8080", token="t")]
    app = create_app(FleetConsole(endpoints, [FakeRobot("rosy_01")]))
    paths = sorted({route.path for route in app.routes if hasattr(route, "path")})
    assert paths, "no routes enumerated — the guard is vacuous"
    hit = [path for path in paths if FORBIDDEN_ROUTE.search(path)]
    assert not hit, f"fleet server exposes video relay routes: {hit}"


def test_pairing_enabled_fleet_still_has_no_video_relay_routes(tmp_path):
    """D-341 2: the camera pairing routes keep the role out of the path (body/query only)."""
    from fleet.server.pairing import PairingService
    from fleet.server.pairing_store import PairingStore
    from pairing_fixtures import LEAF_SHA256, SITE_CA_PEM, TLS_HOST

    endpoints = [RobotEndpoint(robot_id="rosy_01", base_url="http://127.0.0.1:8080", token="t")]
    pairing = PairingService(PairingStore(tmp_path / "fleet.sqlite3"), leaf_cert_sha256=LEAF_SHA256,
                             site_ca_pem=SITE_CA_PEM, tls_host=TLS_HOST, site_name="Rosy Lab",
                             sources={"ceiling_north": "paired"})
    app = create_app(FleetConsole(endpoints, [FakeRobot("rosy_01")]), pairing=pairing,
                     pairing_sync_token="sync-" + "secret-1")
    paths = sorted({route.path for route in app.routes if hasattr(route, "path")})
    assert any(path.startswith("/api/fleet/pairing/v1/") for path in paths)
    hit = [path for path in paths if FORBIDDEN_ROUTE.search(path)]
    assert not hit, f"fleet server exposes video relay routes: {hit}"
