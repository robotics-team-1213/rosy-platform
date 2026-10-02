from __future__ import annotations

import yaml
import pytest

from fleet.server.goal_evidence_registry import (
    load_goal_evidence_registry,
)


def _source(**overrides):
    source = {
        "producer_id": "top-camera-evaluator",
        "token_env": "ROSY_TEST_GOAL_EVIDENCE_TOKEN",
        "workcell_id": "omx_01",
        "predicate_id": "red-block-in-green-tray",
        "object_id": "red-block-1",
        "destination_id": "green-tray-1",
        "evidence_source": "camera_observation",
        "max_age_s": 5.0,
        "grace_s": 10.0,
        "evaluator_revisions": ["placement-v1"],
        "valid_until": "2026-10-01T00:00:00+00:00",
    }
    source.update(overrides)
    return source


def _write_config(tmp_path, sources):
    config = tmp_path / "goal-evidence.yaml"
    config.write_text(yaml.safe_dump({"producers": sources}), encoding="utf-8")
    return config


def test_goal_evidence_registry_resolves_secret_from_environment_and_scopes_it(tmp_path):
    config = _write_config(tmp_path, [_source()])
    registry = load_goal_evidence_registry(
        config, environ={"ROSY_TEST_GOAL_EVIDENCE_TOKEN": "fixture-source-token"},
    )

    registration = registry.source_for_token("fixture-source-token", now=1790726400.0)

    assert registration is not None
    assert registration.producer_id == "top-camera-evaluator"
    assert registration.workcell_id == "omx_01"
    assert registration.predicate_id == "red-block-in-green-tray"
    assert registration.object_id == "red-block-1"
    assert registration.destination_id == "green-tray-1"
    assert registration.evidence_source == "camera_observation"
    assert registration.max_age_s == 5.0
    assert registration.grace_s == 10.0
    assert registration.evaluator_revisions == ("placement-v1",)
    assert registry.source_for_token("unknown-token", now=1790726400.0) is None
    assert "fixture-source-token" not in repr(registration)


@pytest.mark.parametrize("sources", [[], None])
def test_goal_evidence_registry_rejects_empty_or_missing_producer_list(tmp_path, sources):
    config = _write_config(tmp_path, sources)

    with pytest.raises(ValueError, match="at least one producer"):
        load_goal_evidence_registry(config, environ={})


def test_goal_evidence_registry_requires_secret_environment_value(tmp_path):
    config = _write_config(tmp_path, [_source()])

    with pytest.raises(ValueError, match="environment variable.*required"):
        load_goal_evidence_registry(config, environ={})


@pytest.mark.parametrize("invalid", [
    {"unknown": True},
    {"token_env": "lowercase"},
    {"max_age_s": 0},
    {"grace_s": float("inf")},
    {"evaluator_revisions": []},
    {"valid_until": "2026-10-01T00:00:00"},
    {"evidence_source": "model_summary"},
])
def test_goal_evidence_registry_rejects_incomplete_or_unsafe_registration(tmp_path, invalid):
    config = _write_config(tmp_path, [_source(**invalid)])

    with pytest.raises(ValueError):
        load_goal_evidence_registry(
            config, environ={"ROSY_TEST_GOAL_EVIDENCE_TOKEN": "fixture-source-token"},
        )


def test_goal_evidence_registry_rejects_duplicate_scope_and_secret(tmp_path):
    duplicate_scope = _write_config(tmp_path, [_source(), _source(
        producer_id="second-evaluator", token_env="ROSY_SECOND_TOKEN",
    )])
    with pytest.raises(ValueError, match="producer scopes must be unique"):
        load_goal_evidence_registry(duplicate_scope, environ={
            "ROSY_TEST_GOAL_EVIDENCE_TOKEN": "fixture-source-token",
            "ROSY_SECOND_TOKEN": "another-fixture-token",
        })

    duplicate_token = _write_config(tmp_path, [_source(
        producer_id="first-evaluator", token_env="ROSY_TEST_GOAL_EVIDENCE_TOKEN",
    ), _source(producer_id="second-evaluator", workcell_id="omx_02")])
    with pytest.raises(ValueError, match="tokens must be unique"):
        load_goal_evidence_registry(duplicate_token, environ={
            "ROSY_TEST_GOAL_EVIDENCE_TOKEN": "fixture-source-token",
        })


def test_goal_evidence_registry_refuses_expired_registration(tmp_path):
    config = _write_config(tmp_path, [_source()])
    registry = load_goal_evidence_registry(
        config, environ={"ROSY_TEST_GOAL_EVIDENCE_TOKEN": "fixture-source-token"},
    )

    assert registry.source_for_token("fixture-source-token", now=1790726400.0) is not None
    assert registry.source_for_token("fixture-source-token", now=1790812801.0) is None


def _sim_pose_source():
    return _source(producer_id="sim-model-pose", predicate_id="item_at_pose", object_id="cell-item",
                   destination_id="cell-place", evidence_source="sim_model_pose",
                   evaluator_revisions=["gz-model-pose-v1"])


def test_sim_model_pose_producer_is_accepted_only_in_simulation(tmp_path):
    """C4b G6, D-403 §5: sim_model_pose is a simulation-only goal evidence source."""
    config = _write_config(tmp_path, [_sim_pose_source()])
    env = {"ROSY_TEST_GOAL_EVIDENCE_TOKEN": "fixture-source-token"}
    with pytest.raises(ValueError, match="simulation"):
        load_goal_evidence_registry(config, environ=env)
    with pytest.raises(ValueError, match="simulation"):
        load_goal_evidence_registry(config, environ=env, deployment_profile="production")
    registry = load_goal_evidence_registry(config, environ=env, deployment_profile="simulation")
    assert registry.producers[0].evidence_source == "sim_model_pose"


def test_camera_producers_load_in_both_profiles(tmp_path):
    config = _write_config(tmp_path, [_source()])
    env = {"ROSY_TEST_GOAL_EVIDENCE_TOKEN": "fixture-source-token"}
    for profile in ("production", "simulation"):
        assert load_goal_evidence_registry(config, environ=env, deployment_profile=profile).producers
