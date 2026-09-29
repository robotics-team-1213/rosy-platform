"""Laptop match board. No OpenCV, no CORE dashboard."""

from datetime import datetime, timezone
import pytest

from games.field import Field, Pose2D
from games.game import Observation, Phase
from games.game.state import MatchState
from games.host.preview import overlay_payload


def test_preview_board_clears_jpeg_when_the_frame_is_lost():
    from games.host.preview import PreviewBoard

    board = PreviewBoard()
    board.publish({"phase": "play"}, jpeg=b"jpeg-bytes")
    _, jpeg = board.snapshot()
    assert jpeg == b"jpeg-bytes"
    board.publish({"phase": "hold"}, jpeg=None)
    _, jpeg = board.snapshot()
    assert jpeg is None


def test_preview_board_judges_age_without_refreshing_generation_time():
    from games.host.preview import PreviewBoard

    now = [100.0]
    board = PreviewBoard(clock=lambda: now[0],
                         utcnow=lambda: datetime(2026, 9, 27, tzinfo=timezone.utc))
    assert board.snapshot()[0]["evidence"] == "unavailable"
    board.publish({"phase": "play"})
    initial = board.snapshot()[0]
    assert initial["evidence"] == "fresh"
    assert initial["age_s"] == 0.0
    assert initial["generated_at"] == "2026-09-27T00:00:00Z"
    now[0] += 2.1
    delayed = board.snapshot()[0]
    assert delayed["evidence"] == "delayed"
    assert delayed["age_s"] == pytest.approx(2.1)
    assert delayed["generated_at"] == initial["generated_at"]
    board.publish({"phase": "hold"})
    assert board.snapshot()[0]["evidence"] == "fresh"


def test_overlay_payload_is_field_metres_not_pixels():
    field = Field(length_m=2.0, width_m=1.4)
    obs = Observation(
        t=0.0,
        ball=Pose2D(0.1, -0.2, 0.0),
        robots={"rosy_01": Pose2D(-0.4, 0.0, 0.0), "rosy_02": Pose2D(0.4, 0.0, 3.14)},
        lost_ball=False,
        lost_robots=frozenset(),
        home_goal=((-1.0, -0.1), (-1.2, -0.1), (-1.2, 0.1), (-1.0, 0.1)),
        away_goal=None,
    )
    state = MatchState(phase=Phase.PLAY, score={"rosy_01": 1, "rosy_02": 0}, reason="")
    payload = overlay_payload(field, obs, state, markers=(10, 11, 12, 13, 1, 20))
    assert payload["ball"] == {"x": 0.1, "y": -0.2}
    assert payload["robots"]["rosy_01"]["x"] == -0.4
    assert payload["score"]["rosy_01"] == 1
    assert payload["phase"] == "play"
    assert 20 in payload["markers"]
    assert 21 not in payload["markers"]
    assert payload["home_goal"] is not None
    assert payload["away_goal"] is None
    assert payload["field"]["length_m"] == 2.0
    assert payload["has_frame"] is False
    assert payload["reason"] == ""
    assert payload["visibility"]["ready"] is False
    assert "not FIELD GO" in payload["visibility"]["note"]


def test_preview_server_serves_the_board():
    from urllib.request import urlopen

    from games.host.preview import PreviewBoard, PreviewServer

    board = PreviewBoard()
    board.publish({"phase": "play", "field": {"length_m": 2.0}})
    server = PreviewServer(board, port=0)
    url = server.start()
    try:
        html = urlopen(url, timeout=2).read().decode("utf-8")
        assert "1v1 피치" in html
        assert "stair1" in html or "계단 1" in html
        overlay = urlopen(url + "overlay.json", timeout=2).read().decode("utf-8")
        assert "play" in overlay
        css = urlopen(url + "styles.css", timeout=2).read().decode("utf-8")
        assert "tokens.css" not in css
        from urllib.request import Request

        req = Request(url + "stop", method="POST", data=b"")
        stop = urlopen(req, timeout=2).read().decode("utf-8")
        assert board.stop is True
        assert "ok" in stop
        html = urlopen(url, timeout=2).read().decode("utf-8")
        assert "정지" in html
    finally:
        server.close()


def test_preview_module_does_not_import_cv2():
    import ast
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "games" / "host" / "preview.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    assert "cv2" not in names
    assert "core" not in names


def test_preview_server_serves_the_web_common_manifest_assets():
    from urllib.error import HTTPError
    from urllib.request import urlopen

    from games.host.preview import PreviewBoard, PreviewServer

    server = PreviewServer(PreviewBoard(), port=0)
    url = server.start()
    try:
        ticker = urlopen(url + "common/hold-ticker.js", timeout=2)
        assert ticker.headers["Content-Type"].startswith("text/javascript")
        assert b"createHoldTicker" in ticker.read()
        with pytest.raises(HTTPError) as error:
            urlopen(url + "common/manifest.json", timeout=2)
        assert error.value.code == 404
    finally:
        server.close()


def test_board_page_has_csp_and_stop_refuses_foreign_origins():
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen

    from games.host.preview import PreviewBoard, PreviewServer

    board = PreviewBoard()
    server = PreviewServer(board, port=0)
    url = server.start()
    try:
        page = urlopen(url, timeout=2)
        csp = page.headers["Content-Security-Policy"]
        assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
        foreign = Request(url + "stop", method="POST", data=b"",
                          headers={"Origin": "http://evil.example"})
        with pytest.raises(HTTPError) as error:
            urlopen(foreign, timeout=2)
        assert error.value.code == 403
        assert board.stop is False
        own = Request(url + "stop", method="POST", data=b"", headers={"Origin": url.rstrip("/")})
        assert b"ok" in urlopen(own, timeout=2).read()
        assert board.stop is True
    finally:
        server.close()
