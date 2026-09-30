"""D-379 review fixes: session identity, pitch-fit fallback, determinism, clock rule."""
import json

import pytest

pytest.importorskip("cv2")

import autolabel  # noqa: E402
import build  # noqa: E402
import labels as L  # noqa: E402
from test_d379_catalog_and_store import _labels_dir  # noqa: E402


# --- 1. a session never spans splits or overwrites another -------------------

def test_video_session_comes_from_the_video_metadata(tmp_path):
    video = tmp_path / "teleop_rosy-pinky-8kcn_20260930T133221Z.mp4"
    video.write_bytes(b"")
    assert autolabel.video_session(video) == (None, None)
    video.with_suffix(".json").write_text(json.dumps({
        "source": {"session": "20260930T133221Z_rosy-pinky-8kcn"},
        "session": {"device": "rosy-pinky-8kcn"}}), encoding="utf-8")
    assert autolabel.video_session(video) == ("20260930T133221Z_rosy-pinky-8kcn",
                                              {"device": "rosy-pinky-8kcn"})


def test_video_without_a_session_name_is_refused(tmp_path):
    video = tmp_path / "x.mp4"
    video.write_bytes(b"")
    (tmp_path / "x.jsonl").write_text("", encoding="utf-8")
    with pytest.raises(SystemExit):
        autolabel.main(["--video", str(video), "--out", str(tmp_path / "out")])


def test_existing_labels_are_never_silently_replaced(tmp_path):
    d = _labels_dir(tmp_path, "s1", [(L.FLOOR, False)])
    assert autolabel.check_out(tmp_path / "empty", "s1", False) is None
    assert "use --force" in autolabel.check_out(d, "s1", False)
    assert autolabel.check_out(d, "s1", True) is None
    assert "not 's2'" in autolabel.check_out(d, "s2", True)


def test_auto_build_refuses_one_session_in_two_label_folders(tmp_path):
    a = _labels_dir(tmp_path / "a", "s1", [(L.FLOOR, False)])
    b = _labels_dir(tmp_path / "b", "s1", [(L.FLOOR, False)])
    c = _labels_dir(tmp_path / "c", "s2", [(L.FLOOR, False)])
    with pytest.raises(build.BuildError, match="one label folder per session"):
        build.build_auto_dataset([a, b, c], tmp_path / "store", "n")
    assert not (tmp_path / "store").exists()
