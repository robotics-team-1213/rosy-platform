"""작업 상태 view (S8): the screen section reads GET /api/calibration/{status,jobs}; these tests pin the response
format app.js renders (browser-less format assertions — the DOM conversion lives in app.js by design, D-1035)."""
import json
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(ROOT / "applications/calibration"))
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import calibration_web as web  # noqa: E402
from test_calibration_web import Account, call  # noqa: E402
from test_calibration_jobs_api import screen, cell  # noqa: E402  # fixtures: configured cell + running server on it


def test_off_without_cells_the_screen_says_so(tmp_path):
    server = web.make_server(tmp_path, 0, Account())
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_port}"
        assert call(url, "/api/calibration/status", cookie="valid")[0] == 404  # 「--cells 미설정」
        assert call(url, "/api/calibration/jobs", cookie="valid")[0] == 404
    finally:
        server.shutdown()
        server.server_close()


def test_reading_needs_a_session(screen):
    url, _, _, _, _ = screen
    assert call(url, "/api/calibration/status")[0] == 401
    assert call(url, "/api/calibration/jobs")[0] == 401


def test_status_carries_the_lease_fields_the_screen_prints(screen):
    url, _, _, jobs, _ = screen
    status = json.loads(call(url, "/api/calibration/status", cookie="valid")[1])
    assert status["arms"]["arm_b"]["lease"] is None and status["leases_error"] is None  # 「비어 있음」
    jobs.lease().claim("arm_b", "someone@elsewhere", "hand work", 600, None, None)
    lease = json.loads(call(url, "/api/calibration/status", cookie="valid")[1])["arms"]["arm_b"]["lease"]
    # leaseText(): 점유 중/만료됨 · owner · purpose · 만료(expires, unix s)
    assert (lease["owner"], lease["purpose"], lease["live"]) == ("someone@elsewhere", "hand work", True)
    assert isinstance(lease["expires"], (int, float)) and lease["expires"] > 0


def test_jobs_newest_first_with_kind_result_time(screen):
    url, _, _, jobs, _ = screen
    (jobs.work / "jobs").mkdir(parents=True, exist_ok=True)
    jobs.write({"id": "20261119T000000-000001", "arm": "arm_b", "step": "check", "status": "done",
                "started": "2026-11-19T00:00:00Z", "ended": "2026-11-19T00:01:00Z"})
    jobs.write({"id": "20261119T000100-000002", "arm": "arm_b", "step": "pivot-near", "status": "failed",
                "started": "2026-11-19T00:01:00Z", "ended": "2026-11-19T00:02:00Z"})
    rows = json.loads(call(url, "/api/calibration/jobs", cookie="valid")[1])["jobs"]
    assert rows[0]["id"] == "20261119T000100-000002"  # newest first: the screen takes the first three
    for row in rows:  # 팔 · 종류 · 결과 · 시각
        assert {"arm", "step", "status", "started"} <= set(row)


def test_calibration_status_logic_node_unit_tests(tmp_path):
    import shutil
    import subprocess
    import pytest
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is unavailable")
    result = subprocess.run(
        [node, "--test", "--test-reporter=spec", str(ROOT / "applications/calibration/test/status-logic.test.mjs")],
        cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
