"""slam_toolbox reports success as 0. A truthiness test here is backwards.

The bridge has always had this right. It has never had a test saying so, and CI's
SaveMap guard checks the request type rather than how the reply is read — so an
inversion introduced during a refactor would ship, and the symptom is a robot
reporting a map it never wrote.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.bridge.save_map import SaveMapFailed, await_call, check_result


class _DoneFuture:
    """Like rclpy's: an already-finished future invokes the callback at once."""

    def __init__(self, result) -> None:
        self._result = result

    def add_done_callback(self, callback) -> None:
        callback(self)

    def result(self):
        return self._result


class _NeverFinishes:
    def add_done_callback(self, callback) -> None:
        pass

    def result(self):
        raise AssertionError("a future that never finished has no result")


def test_a_finished_future_is_returned_as_is():
    response = SimpleNamespace(result=0)

    assert await_call(_DoneFuture(response), timeout=0.0) is response


def test_a_future_that_never_finishes_times_out_with_the_documented_message():
    with pytest.raises(RuntimeError, match="save_map service timeout"):
        await_call(_NeverFinishes(), timeout=0.0)


def test_a_missing_response_is_not_a_success():
    """"no answer" and "service down" are different things to an operator."""
    with pytest.raises(RuntimeError, match="save_map service failed"):
        await_call(_DoneFuture(None), timeout=0.0)


def test_zero_is_success():
    check_result(0)          # must not raise


@pytest.mark.parametrize("code", [1, 255])
def test_the_documented_failures_raise(code):
    """1 = no map to save, 255 = write failed."""
    with pytest.raises(SaveMapFailed) as raised:
        check_result(code)
    assert str(code) in str(raised.value)


def test_a_truthiness_test_would_invert_this():
    """Pins the trap directly: the only falsy code is the successful one."""
    assert bool(0) is False          # success, and falsy
    assert bool(1) is True           # failure, and truthy
    check_result(0)
    with pytest.raises(SaveMapFailed):
        check_result(1)


@pytest.mark.parametrize("code", [-1, 2, 3, 256])
def test_any_unknown_code_is_a_failure_not_a_success(code):
    with pytest.raises(SaveMapFailed):
        check_result(code)


# --- D-13 map id ------------------------------------------------------------

from core.bridge.save_map import map_id, resolve_output_stem, saved_bytes  # noqa: E402


def test_map_output_stem_is_confined_to_the_shared_map_directory(tmp_path):
    assert resolve_output_stem("survey_01", tmp_path) == str(tmp_path / "survey_01")


@pytest.mark.parametrize(
    "name", ["", ".", "..", "../escape", "nested/map", r"nested\\map", "/tmp/map"]
)
def test_map_output_stem_rejects_empty_or_path_like_names(tmp_path, name):
    with pytest.raises(ValueError, match="map name"):
        resolve_output_stem(name, tmp_path)


def test_map_id_is_the_name_plus_a_short_content_checksum():
    result = map_id("survey", b"grid-bytes", now=1000.0)

    assert result.startswith("survey:")
    assert len(result.split(":", 1)[1]) == 8


def test_the_same_content_always_gives_the_same_id():
    """MAP-002 compares ids — a re-save of an unchanged map must still match."""
    assert map_id("survey", b"same", 1.0) == map_id("survey", b"same", 999.0)


def test_different_content_gives_a_different_id():
    """The whole point: a changed map must not answer to the old id."""
    assert map_id("survey", b"before", 1.0) != map_id("survey", b"after", 1.0)


def test_the_name_is_part_of_the_id_not_just_the_hash():
    assert map_id("bay_a", b"same", 1.0) != map_id("bay_b", b"same", 1.0)


def test_a_missing_file_falls_back_to_a_distinct_id_not_a_stable_one():
    """Deliberate: two different maps sharing an id would let MAP-002 wave
    through a goal from the wrong survey. A changing id only costs a re-teach."""
    first = map_id("survey", None, now=1000.0)
    second = map_id("survey", None, now=1000.5)

    assert first != second
    assert first.startswith("survey:")


def test_empty_content_is_content_not_absence():
    """An empty file is a real (bad) map; it must not take the timestamp path."""
    assert map_id("survey", b"", 1.0) == map_id("survey", b"", 2.0)


def test_saved_bytes_prefers_the_pgm_slam_toolbox_writes(tmp_path):
    (tmp_path / "m.pgm").write_bytes(b"pgm-content")
    (tmp_path / "m").write_bytes(b"bare-content")

    assert saved_bytes(str(tmp_path / "m")) == b"pgm-content"


def test_saved_bytes_falls_back_to_the_bare_name(tmp_path):
    (tmp_path / "m").write_bytes(b"bare-content")

    assert saved_bytes(str(tmp_path / "m")) == b"bare-content"


def test_saved_bytes_returns_none_rather_than_raising(tmp_path):
    """The save already succeeded — not finding the file afterwards must not
    turn a good save into an error."""
    assert saved_bytes(str(tmp_path / "absent")) is None


def test_saved_bytes_ignores_a_directory_with_the_right_name(tmp_path):
    (tmp_path / "m").mkdir()

    assert saved_bytes(str(tmp_path / "m")) is None
