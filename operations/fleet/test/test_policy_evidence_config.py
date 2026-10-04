"""Policy-evidence source config loader tests (D-268 ladder step 1, T2)."""

from __future__ import annotations

import pytest

from fleet.server.policy_evidence_config import load_policy_evidence_sources

_ENV = {"POLICY_EVIDENCE_TOKEN": "site-secret-1"}


def _write(tmp_path, body: str):
    path = tmp_path / "policy-evidence.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def _valid_yaml() -> str:
    return """
sources:
  - source_id: ceiling-vision-1
    token_env: POLICY_EVIDENCE_TOKEN
    asset_kinds: [robot]
    task_kinds: [navigate]
    map_id: site-map-a
    calibration_revision: cal-2026-09-26
    model_revisions: [aruco-v3, aruco-v4]
"""


def test_loads_source_with_env_bound_token(tmp_path):
    sources = load_policy_evidence_sources(_write(tmp_path, _valid_yaml()), environ=_ENV)
    assert len(sources) == 1
    source = sources[0]
    assert source.source_id == "ceiling-vision-1"
    assert source.token == "site-secret-1"
    assert source.asset_kinds == ("robot",)
    assert source.model_revisions == ("aruco-v3", "aruco-v4")
    assert source.revoked is False


def test_rejects_secret_token_in_yaml(tmp_path):
    body = _valid_yaml() + "    token: should-not-be-here\n"
    with pytest.raises(ValueError, match="unknown fields: token"):
        load_policy_evidence_sources(_write(tmp_path, body), environ=_ENV)


def test_missing_token_env_is_an_error(tmp_path):
    with pytest.raises(ValueError, match="environment variable POLICY_EVIDENCE_TOKEN is required"):
        load_policy_evidence_sources(_write(tmp_path, _valid_yaml()), environ={})


def test_empty_sources_list_is_an_error(tmp_path):
    with pytest.raises(ValueError, match="at least one source"):
        load_policy_evidence_sources(_write(tmp_path, "sources: []\n"), environ=_ENV)


def test_unknown_top_level_key_is_an_error(tmp_path):
    with pytest.raises(ValueError, match="must contain only a sources list"):
        load_policy_evidence_sources(_write(tmp_path, "extra: 1\n" + _valid_yaml()), environ=_ENV)


def test_asset_kind_outside_dispatch_vocabulary_is_an_error(tmp_path):
    body = _valid_yaml().replace("asset_kinds: [robot]", "asset_kinds: [zone]")
    with pytest.raises(ValueError, match="asset_kinds must be a subset of"):
        load_policy_evidence_sources(_write(tmp_path, body), environ=_ENV)


def test_task_kind_outside_v1_set_is_an_error(tmp_path):
    body = _valid_yaml().replace("task_kinds: [navigate]", "task_kinds: [pick_place]")
    with pytest.raises(ValueError, match="task_kinds must be a subset of"):
        load_policy_evidence_sources(_write(tmp_path, body), environ=_ENV)


def test_empty_model_revisions_is_an_error(tmp_path):
    body = _valid_yaml().replace("model_revisions: [aruco-v3, aruco-v4]", "model_revisions: []")
    with pytest.raises(ValueError, match="model_revisions must be a non-empty string list"):
        load_policy_evidence_sources(_write(tmp_path, body), environ=_ENV)


def test_revoked_flag_is_carried(tmp_path):
    body = _valid_yaml() + "    revoked: true\n"
    sources = load_policy_evidence_sources(_write(tmp_path, body), environ=_ENV)
    assert sources[0].revoked is True


def test_revoked_must_be_boolean(tmp_path):
    body = _valid_yaml() + "    revoked: yes-please\n"
    with pytest.raises(ValueError, match="revoked must be a boolean"):
        load_policy_evidence_sources(_write(tmp_path, body), environ=_ENV)


def test_duplicate_source_ids_are_an_error(tmp_path):
    entry = _valid_yaml().split("sources:", 1)[1]
    body = "sources:" + entry + entry.replace("POLICY_EVIDENCE_TOKEN", "POLICY_EVIDENCE_TOKEN_2")
    with pytest.raises(ValueError, match="source ids must be unique"):
        load_policy_evidence_sources(_write(tmp_path, body),
                                     environ={**_ENV, "POLICY_EVIDENCE_TOKEN_2": "site-secret-2"})
