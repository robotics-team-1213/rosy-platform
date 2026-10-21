"""Latest-only physical arm evidence stays source-bound and expires independently."""
import json
from types import SimpleNamespace

import pytest

from core_common.protocol.workcell_observations import ArmObservation, WorkcellObservationManifest
from fleet.server.workcell_observations import WorkcellObservations


@pytest.fixture
def setup():
    arms = [{"source_id": f"feedback_{side}", "arm_id": f"arm_{side}", "label": f"Arm {side}",
             "board_id": f"EXAMPLE-BOARD-{side}", "joint_topic": f"/omx_commissioning/arm_{side}/joint_states",
             "joint_names": [f"joint{i}" for i in range(6)], "token_env": f"EXAMPLE_ARM_{side.upper()}"}
            for side in ("a", "b")]
    cameras = [{"source_id": "top", "label": "Top", "role": "overhead", "arm_id": None,
                "image_topic": "/top_camera/image_raw", "device_path": "/dev/v4l/by-id/example-top",
                "token_env": "EXAMPLE_TOP"}]
    cameras += [{"source_id": f"wrist_{side}", "label": f"Wrist {side}", "role": "wrist",
                 "arm_id": f"arm_{side}", "image_topic": f"/wrist_{side}/image_raw",
                 "device_path": f"/dev/v4l/by-path/example-{side}", "token_env": f"EXAMPLE_WRIST_{side.upper()}"}
                for side in ("a", "b")]
    manifest = WorkcellObservationManifest.model_validate({"schema": "rosy.workcell-observations/1", "workcells": [
        {"workcell_id": "example_cell", "label": "Example", "arms": arms, "cameras": cameras}]})
    clock = SimpleNamespace(wall=100.0, monotonic=10.0)
    tokens = {"feedback_a": "arm-a-secret", "feedback_b": "arm-b-secret"}
    service = WorkcellObservations(manifest, tokens, wall=lambda: clock.wall, monotonic=lambda: clock.monotonic)
    return service, clock, manifest, tokens


def sample(*, epoch="a" * 32, sequence=1, captured_at=100.0, position=0.25):
    return ArmObservation(epoch=epoch, sequence=sequence, captured_at=captured_at,
                          positions={f"joint{i}": position for i in range(6)})


def arms(service):
    return {arm["source_id"]: arm for arm in service.snapshot()["workcells"][0]["arms"]}


def test_registered_sources_are_visible_before_any_samples_without_private_bindings(setup):
    service, _, _, _ = setup
    state = service.snapshot()
    assert state["read_only"] is True and state["physical_acceptance"] is False
    for arm in arms(service).values():
        assert arm["units"] == "encoder_rad" and arm["fresh"] is False
        assert arm["sequence"] == 0
        assert all(arm[key] is None for key in ("epoch", "captured_at", "source_age_s", "receipt_age_s", "positions"))
    cameras = state["workcells"][0]["cameras"]
    assert cameras == [{"source_id": "top", "label": "Top", "role": "overhead", "arm_id": None},
                       {"source_id": "wrist_a", "label": "Wrist a", "role": "wrist", "arm_id": "arm_a"},
                       {"source_id": "wrist_b", "label": "Wrist b", "role": "wrist", "arm_id": "arm_b"}]
    rendered = json.dumps(state)
    assert not any(private in rendered for private in ("secret", "token_env", "board_id", "device_path", "/dev/"))


@pytest.mark.parametrize("tokens", [{}, {"feedback_a": "a"}, {"feedback_a": "", "feedback_b": "b"},
    {"feedback_a": "same", "feedback_b": "same"}, {"feedback_a": "a", "feedback_b": "b", "top": "c"}])
def test_constructor_requires_exact_distinct_arm_credentials(setup, tokens):
    _, clock, manifest, _ = setup
    with pytest.raises(ValueError):
        WorkcellObservations(manifest, tokens, wall=lambda: clock.wall, monotonic=lambda: clock.monotonic)


def test_source_credentials_and_joint_set_cannot_change_an_existing_sample(setup):
    service, _, _, _ = setup
    service.ingest("feedback_a", "arm-a-secret", sample())
    before = service.snapshot()
    for source, token in (("feedback_a", "wrong"), ("feedback_a", "arm-b-secret"), ("unknown", "arm-a-secret")):
        with pytest.raises(PermissionError):
            service.ingest(source, token, sample(sequence=2, captured_at=100.1))
    invalid = sample(sequence=2, captured_at=100.1)
    invalid.positions = {"other_joint": 0.5}
    with pytest.raises(ValueError):
        service.ingest("feedback_a", "arm-a-secret", invalid)
    assert service.snapshot() == before


def test_restarts_require_sequence_one_and_newer_capture_and_retire_old_epochs(setup):
    service, _, _, _ = setup
    service.ingest("feedback_a", "arm-a-secret", sample(epoch="0" * 32, captured_at=99.5))
    service.ingest("feedback_a", "arm-a-secret", sample())
    before = service.snapshot()
    for observation in (sample(epoch="0" * 32, sequence=99, captured_at=100.1),
                        sample(sequence=1, captured_at=100.1), sample(sequence=2, captured_at=100),
                        sample(epoch="b" * 32, sequence=2, captured_at=100.1),
                        sample(epoch="b" * 32, captured_at=99.9)):
        with pytest.raises(ValueError):
            service.ingest("feedback_a", "arm-a-secret", observation)
        assert service.snapshot() == before


def test_late_delivery_and_future_capture_do_not_refresh_a_stale_sample(setup):
    service, clock, _, _ = setup
    service.ingest("feedback_a", "arm-a-secret", sample())
    clock.wall, clock.monotonic = 103.0, 13.0
    for captured_at in (100.5, 103.251):
        with pytest.raises(ValueError):
            service.ingest("feedback_a", "arm-a-secret", sample(sequence=2, captured_at=captured_at))
    arm = arms(service)["feedback_a"]
    assert not arm["fresh"] and arm["positions"] is None and arm["sequence"] == 1
    assert arm["captured_at"] == 100 and arm["receipt_age_s"] == 3


def test_two_followers_with_identical_joint_names_expire_independently(setup):
    service, clock, _, _ = setup
    service.ingest("feedback_a", "arm-a-secret", sample())
    service.ingest("feedback_b", "arm-b-secret", sample(position=0.75))
    clock.wall, clock.monotonic = 102.0, 12.0
    service.ingest("feedback_a", "arm-a-secret", sample(sequence=2, captured_at=102, position=0.5))
    clock.wall, clock.monotonic = 102.1, 12.1
    state = arms(service)
    assert state["feedback_a"]["fresh"] and state["feedback_a"]["positions"]["joint0"] == 0.5
    assert not state["feedback_b"]["fresh"] and state["feedback_b"]["positions"] is None
    assert state["feedback_b"]["sequence"] == 1


@pytest.mark.parametrize("wall,monotonic", [(100.1, 12.1), (102.1, 10.1), (99.5, 10.1), (100.1, 9.9)])
def test_both_clocks_must_remain_fresh_and_nonregressing(setup, wall, monotonic):
    service, clock, _, _ = setup
    service.ingest("feedback_a", "arm-a-secret", sample())
    clock.wall, clock.monotonic = wall, monotonic
    assert not arms(service)["feedback_a"]["fresh"]
    assert arms(service)["feedback_a"]["positions"] is None


def test_ingest_and_snapshot_own_their_data(setup):
    service, _, _, _ = setup
    observation = sample()
    service.ingest("feedback_a", "arm-a-secret", observation)
    observation.positions["joint0"] = 9
    state = service.snapshot()
    state["workcells"][0]["arms"][0]["positions"]["joint0"] = 8
    state["workcells"][0]["cameras"][0]["label"] = "changed"
    assert arms(service)["feedback_a"]["positions"]["joint0"] == 0.25
    assert service.snapshot()["workcells"][0]["cameras"][0]["label"] == "Top"
