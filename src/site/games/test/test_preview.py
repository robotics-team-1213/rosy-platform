"""Laptop match board. No OpenCV, no CORE dashboard."""

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
