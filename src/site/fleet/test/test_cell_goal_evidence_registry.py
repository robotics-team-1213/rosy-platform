"""Producer credentials come from environment and remain pinned to exact scopes."""

import yaml
import pytest

from fleet.server.cell_goal_evidence_registry import load_cell_goal_registry


def _config():
    return {"producers": [{"producer_id": "pose", "token_env": "CELL_POSE_TOKEN",
                           "workcell_id": "omx_01", "instance_id": "omx_01_control",
                           "recipe_sha256": "a" * 64, "cell_sha256": "b" * 64,
                           "evaluator_revisions": ["placement-v1"], "max_age_s": 5,
                           "valid_until": "2030-01-01T00:00:00Z"}]}


def _load(tmp_path, config, env=None):
    path = tmp_path / "producers.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return load_cell_goal_registry(path, environ=env if env is not None else {"CELL_POSE_TOKEN": "pose-secret"})


def test_registry_hides_environment_credential_and_enforces_expiry(tmp_path):
    registry = _load(tmp_path, _config(), {"CELL_POSE_TOKEN": "producer-\uad00\uce21"})
    producer = registry.producers[0]
    assert producer.token not in repr(registry)
    assert registry.source_for_token(producer.token, now=0) == producer
    assert registry.source_for_token(producer.token, now=producer.valid_until.timestamp()) is None
    assert registry.source_for_token("operator-token", now=0) is None
    assert registry.source_for_token("x" * 4097, now=0) is None


@pytest.mark.parametrize("mutation", ["literal_token", "missing_env", "extra", "duplicate", "unbounded_age",
                                      "boolean_age", "naive_expiry", "duplicate_revision", "unpinned_recipe"])
def test_invalid_registry_fails_closed(tmp_path, mutation):
    config = _config()
    row = config["producers"][0]
    env = {"CELL_POSE_TOKEN": "pose-secret"}
    if mutation == "literal_token":
        row["token"] = "embedded-secret"
    elif mutation == "missing_env":
        env = {}
    elif mutation == "extra":
        config["allow_any_cell"] = True
    elif mutation == "duplicate":
        config["producers"].append(dict(row))
    elif mutation == "unbounded_age":
        row["max_age_s"] = 61
    elif mutation == "boolean_age":
        row["max_age_s"] = True
    elif mutation == "naive_expiry":
        row["valid_until"] = "2030-01-01T00:00:00"
    elif mutation == "duplicate_revision":
        row["evaluator_revisions"] *= 2
    else:
        row["recipe_sha256"] = "latest"
    with pytest.raises(ValueError):
        _load(tmp_path, config, env)
