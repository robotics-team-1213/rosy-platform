"""Unit tests for ACT backtrack-prefix trimming in cell_policy_shape and paced mode."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx"))
import cell_policy_drive as drive  # noqa: E402
import cell_policy_shape as shape  # noqa: E402


LOW = [-30.0, -60.0, 0.0, 20.0, -35.0, 40.0]
HIGH = [30.0, 20.0, 60.0, 60.0, 50.0, 65.0]
FASTEST = 0.5


def test_trim_backtrack_reduces_arm_a_chunk1_yo_yo():
    start = [-18.9, -19.3, 28.1, 38.4, 33.3, 53.5]
    chunk = [
        [-16.0, -46.2, 44.5, 46.2, 43.3, 52.3],
        [-17.5, -33.0, 36.0, 42.0, 38.0, 53.0],
        [-19.0, -19.5, 28.0, 38.2, 33.2, 54.0],
        [-19.6, -1.1, 17.1, 33.3, 32.5, 55.7],
    ]
    untrimmed = shape.shape_chunk(chunk, start, LOW, HIGH, FASTEST)
    trimmed = shape.shape_chunk(chunk, start, LOW, HIGH, FASTEST, trim_backtrack=True)
    assert len(trimmed) < len(untrimmed) / 2
    assert trimmed[-1] == pytest.approx(chunk[-1])
    assert max(abs(b[j] - a[j]) for a, b in zip([start] + trimmed, trimmed) for j in range(6)) <= FASTEST + 1e-9


def test_trim_backtrack_when_closest_is_last_row_never_empties():
    start = [20.9, 10.8, 7.8, 31.6, -28.5, 55.8]
    chunk = [
        [21.0, 1.3, 12.7, 35.2, -20.9, 55.4],
        [21.0, 6.0, 10.0, 33.0, -25.0, 55.6],
        [20.9, 11.1, 7.6, 31.5, -28.8, 55.8],
    ]
    trimmed_arr = shape.trim_backtrack_prefix(chunk, start)
    assert len(trimmed_arr) == 1 and trimmed_arr[0].tolist() == chunk[-1]
    out = shape.shape_chunk(chunk, start, LOW, HIGH, FASTEST, trim_backtrack=True)
    assert len(out) == 1 and out[-1] == pytest.approx(chunk[-1])


def test_forward_chunk_is_unchanged_with_trim_backtrack():
    start = [0.0, -50.0, 45.0, 45.0, 0.0, 50.0]
    chunk = [
        [1.0, -45.0, 42.0, 44.0, 2.0, 50.0],
        [2.0, -35.0, 36.0, 42.0, 4.0, 50.0],
        [3.0, -25.0, 30.0, 40.0, 6.0, 50.0],
    ]
    assert shape.shape_chunk(chunk, start, LOW, HIGH, FASTEST, trim_backtrack=True) == shape.shape_chunk(
        chunk, start, LOW, HIGH, FASTEST, trim_backtrack=False
    )


def test_genuine_departure_near_start_not_trimmed():
    start = [0.0, -20.0, 30.0, 40.0, 10.0, 50.0]
    chunk = [
        [0.5, -21.0, 30.5, 40.0, 10.5, 50.0],
        [0.2, -20.2, 30.1, 40.0, 10.1, 50.0],
        [-5.0, -30.0, 35.0, 42.0, 12.0, 50.0],
    ]
    assert shape.trim_backtrack_prefix(chunk, start).tolist() == chunk


def test_out_of_envelope_prefix_still_refused_before_trim():
    start = [-18.9, -19.3, 28.1, 38.4, 33.3, 53.5]
    chunk = [
        [-16.0, -90.0, 44.5, 46.2, 43.3, 52.3],
        [-19.0, -19.5, 28.0, 38.2, 33.2, 54.0],
        [-19.6, -1.1, 17.1, 33.3, 32.5, 55.7],
    ]
    with pytest.raises(ValueError, match="shoulder_lift"):
        shape.shape_chunk(chunk, start, LOW, HIGH, FASTEST, trim_backtrack=True)


def test_default_shape_chunk_preserves_non_paced_behavior():
    start = [-18.9, -19.3, 28.1, 38.4, 33.3, 53.5]
    chunk = [
        [-16.0, -46.2, 44.5, 46.2, 43.3, 52.3],
        [-19.0, -19.5, 28.0, 38.2, 33.2, 54.0],
        [-19.6, -1.1, 17.1, 33.3, 32.5, 55.7],
    ]
    assert shape.shape_chunk(chunk, start, LOW, HIGH, FASTEST) == shape.shape_chunk(
        chunk, start, LOW, HIGH, FASTEST, trim_backtrack=False
    )


def test_paced_dry_run_logs_trimmed_frames_and_raw_proposed_first(tmp_path):
    start = [-18.9, -19.3, 28.1, 38.4, 33.3, 53.5]
    chunk = [
        [-16.0, -46.2, 44.5, 46.2, 43.3, 52.3],
        [-19.0, -19.5, 28.0, 38.2, 33.2, 54.0],
        [-19.6, -1.1, 17.1, 33.3, 32.5, 55.7],
    ]
    lib = {
        "fps": 30,
        "gripper_closed": 46.6,
        "chunks": {
            "home": [LOW, HIGH],
            "reach": [LOW, [LOW[0] + FASTEST] + LOW[1:]],
        },
    }
    lib_path = tmp_path / "lib.json"
    lib_path.write_text(json.dumps(lib), encoding="utf-8")

    class StubPolicy:
        image_views = {"top": (4, 4), "wrist": (4, 4)}

        def inputs(self, state, frames):
            return {"state": state}, {}

        def infer(self, obs):
            return SimpleNamespace(chunk=chunk)

    class StubCell:
        def frame(self, view):
            return np.zeros((4, 4, 3), np.uint8)

        def act(self, command):
            return {"ok": True, "state": start, "holding": False, "settled": True, "command": command}

    rows = []
    res = drive.run_episode(
        StubCell(), StubPolicy(), lib_path, tmp_path,
        offset=[0] * 6, max_chunks=1, dry_run=True, paced_chunks=True, log=rows.append,
    )
    assert res == {"result": "dry_run", "chunks": 1}
    assert len(rows) == 1
    assert rows[0]["envelope"] == {"ok": True}
    assert rows[0]["proposed_first"] == pytest.approx(chunk[0])
    low, high, fastest = shape.envelope(lib)
    untrimmed = shape.shape_chunk(chunk, start, low, high, min(fastest, 15.0 / 30.0), trim_backtrack=False)
    assert rows[0]["frames"] < len(untrimmed)


def test_trim_backtrack_short_chunk_unchanged():
    start = [-18.9, -19.3, 28.1, 38.4, 33.3, 53.5]
    one = [[-16.0, -46.2, 44.5, 46.2, 43.3, 52.3]]
    assert shape.trim_backtrack_prefix(one, start).tolist() == one
    assert shape.trim_backtrack_prefix(np.zeros((0, 6)), start).shape == (0, 6)


def test_trim_backtrack_tie_keeps_earliest_minimum():
    start = [0.0, -20.0, 30.0, 40.0, 10.0, 50.0]
    chunk = [
        [0.0, -40.0, 40.0, 40.0, 10.0, 50.0],
        [0.0, -20.5, 30.0, 40.0, 10.0, 50.0],
        [0.0, -20.5, 30.0, 40.0, 10.0, 50.0],
        [0.0, -5.0, 20.0, 35.0, 10.0, 50.0],
    ]
    assert shape.trim_backtrack_prefix(chunk, start).tolist() == chunk[1:]


def test_trim_backtrack_non_finite_direct_call_unchanged():
    start = [0.0, -20.0, 30.0, 40.0, 10.0, 50.0]
    chunk_inf = [
        [np.inf, -40.0, 40.0, 40.0, 10.0, 50.0],
        [0.0, -20.0, 30.0, 40.0, 10.0, 50.0],
    ]
    assert shape.trim_backtrack_prefix(chunk_inf, start).shape == (2, 6)
    assert np.isinf(shape.trim_backtrack_prefix(chunk_inf, start)[0, 0])
    assert shape.trim_backtrack_prefix(chunk_inf[1:], [np.nan] + start[1:]).shape == (1, 6)


REAL5_STATE = [-16.3, -4.2, 15.4, 37.2, 32.6, 56.2]  # real5 2026-11-27 arm_a chunk 1: measured pose
REAL5_LEAD = [-21.4, 10.5, 5.3, 34.2, 28.6, 56.2]  # its first action, shoulder_lift +14.7 ahead


def _real5_chunk(rows=16):
    first, step = np.asarray(REAL5_LEAD), np.array([-0.1, 0.3, -0.2, -0.05, -0.05, 0.0])
    return [(first + k * step).tolist() for k in range(rows)]


def test_ease_starts_policy_chunk_from_rest_at_measured_pose():
    low, high = [-40.0, -70.0, -10.0, 10.0, 0.0, 40.0], [10.0, 40.0, 60.0, 60.0, 50.0, 65.0]
    chunk = _real5_chunk()
    raw = shape.shape_chunk(chunk, REAL5_STATE, low, high, FASTEST)
    eased = shape.shape_chunk(chunk, REAL5_STATE, low, high, FASTEST, ease=True)
    def steps(frames):
        path = np.vstack([REAL5_STATE, frames])
        return np.abs(np.diff(path, axis=0))[:, :5].max(axis=1)

    assert (steps(raw) > 0.9 * FASTEST).sum() >= 25  # the old shape sprints the whole 14.7-unit lead at full speed
    assert (steps(eased) > 0.9 * FASTEST).sum() <= 3
    assert steps(eased).max() <= FASTEST + 1e-9
    assert eased[-1] == pytest.approx(chunk[-1])


def test_ease_keeps_jaw_and_short_chunks():
    chunk = [[0.0, -50.0, 45.0, 45.0, 0.0, 60.0], [1.0, -45.0, 42.0, 44.0, 2.0, 45.0]]
    eased = shape.ease_start(chunk, [0.0, -55.0, 45.0, 45.0, 0.0, 50.0])
    assert eased.tolist() == [chunk[1]]
    one = [[0.0, -50.0, 45.0, 45.0, 0.0, 60.0]]
    assert shape.ease_start(one, [0.0] * 6).tolist() == one


def test_ease_refuses_eased_frame_outside_envelope():
    low, high = [-30.0, -60.0, 0.0, 20.0, -35.0, 40.0], [30.0, 20.0, 60.0, 60.0, 50.0, 65.0]
    start = [0.0, -50.0, 45.0, 45.0, 0.0, 50.0]
    chunk = [[0.0, -50.0, 62.0, 45.0, 0.0, 50.0], [0.0, -50.0, 62.0, 45.0, 0.0, 50.0], [0.0, -50.0, 40.0, 45.0, 0.0, 50.0]]
    # the start is never envelope-checked; easing toward a start far below it moves elbow row 1 to 62 - 0.5 * 162 = -19
    far = [0.0, -50.0, -100.0, 45.0, 0.0, 50.0]
    assert shape.shape_chunk(chunk, far, low, high, FASTEST)[-1] == pytest.approx(chunk[-1])
    with pytest.raises(ValueError, match="outside reviewed"):
        shape.shape_chunk(chunk, far, low, high, FASTEST, ease=True)
    assert shape.shape_chunk(chunk, start, low, high, FASTEST, ease=True)[-1] == pytest.approx(chunk[-1])
