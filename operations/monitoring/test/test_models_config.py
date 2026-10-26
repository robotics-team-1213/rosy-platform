"""D-876: bounded read-only scopes and independent source/report lifetimes."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from rosy.monitoring.config import MonitoringConfig, load_config, load_credentials
from rosy.monitoring.models import MonitoringLink, MonitoringNode, MonitoringSnapshot


STAMP = "2026-10-25T00:00:00Z"


def observation(**changes):
    return {"site_id": "site-a", "origin_collector": "collector-a", "origin_source": "robot-a",
            "sample_id": "sample-1", "sampled_at": STAMP, "age_s": 0.0,
            "valid_for_s": 15, "remaining_s": 15.0, "report_remaining_s": 15.0,
            "freshness": "fresh", "reason_code": None} | changes


def node(**changes):
    return observation() | {"id": "site-a:robot:robot-a", "kind": "robot", "label": "로봇 A",
                            "reported_health": "OK"} | changes


def snapshot(**changes):
    return {"schema_version": 1, "collector_id": "collector-a", "generation": "a" * 32,
            "sequence": 1, "produced_at": STAMP, "remaining_s": 15.0, "scope_sites": ["site-a"],
            "nodes": [node()], "links": []} | changes


def configuration(**changes):
    return {"collector_id": "collector-a", "site_id": "site-a",
            "readers": [{"principal_id": "operator-a", "token_env": "MONITOR_READ", "sites": ["site-a"]}],
            "sources": [{"id": "robot-a", "site_id": "site-a", "kind": "core",
                         "url": "https://robot-a.example.invalid", "token_env": "CORE_READ"}]} | changes


def test_source_validity_does_not_imply_recent_collection_path():
    value = MonitoringNode.model_validate(node(id="site-a:host:pc-a", kind="host", age_s=100.0,
                                               valid_for_s=900, remaining_s=800.0,
                                               report_remaining_s=0.0, freshness="stale"))
    assert value.reported_health == "OK" and value.freshness == "stale"
    assert value.remaining_s == 800 and value.report_remaining_s == 0


def test_existing_host_guard_connection_reports_keep_their_source_window():
    value = observation(age_s=100.0, valid_for_s=900, remaining_s=800.0)
    value.update(id="site-a:reported:pc-a", source_id="site-a:collector:collector-a",
                 target_id="site-a:host:pc-a", kind="reported", expected=True,
                 reachable=True, failure_stage="none", duration_ms=None)
    assert MonitoringLink.model_validate(value).remaining_s == 800


@pytest.mark.parametrize("changes", [
    {"age_s": float("nan")}, {"age_s": True}, {"remaining_s": float("inf")},
    {"report_remaining_s": 16.0}, {"remaining_s": -1.0}, {"age_s": 10.0},
    {"valid_for_s": 15.0},
    {"sampled_at": "2026-10-25T00:00:00"}, {"sampled_at": 1},
    {"freshness": "fresh", "report_remaining_s": 0.0},
    {"id": "site-b:robot:robot-a"}, {"access_token": "must-not-cross"},
    {"label": "line\nbreak"}, {"reason_code": "ARBITRARY_PRIVATE_MESSAGE"},
])
def test_invalid_or_incoherent_observations_are_rejected(changes):
    with pytest.raises(ValidationError):
        MonitoringNode.model_validate(node(**changes))


def test_unobserved_inventory_cannot_claim_a_healthy_measurement():
    unknown = node(sample_id=None, sampled_at=None, age_s=None, remaining_s=0.0,
                   report_remaining_s=0.0, freshness="unknown", reported_health="UNKNOWN")
    MonitoringNode.model_validate(unknown)
    with pytest.raises(ValidationError):
        MonitoringNode.model_validate(unknown | {"reported_health": "OK"})


def test_graph_rejects_duplicates_outside_scopes_and_dangling_links():
    MonitoringSnapshot.model_validate(snapshot())
    for changes in ({"nodes": [node(), node()]}, {"scope_sites": ["site-b"]}, {"generation": "bad"},
                    {"schema_version": True}, {"sequence": -1}):
        with pytest.raises(ValidationError):
            MonitoringSnapshot.model_validate(snapshot(**changes))
    link = observation() | {"id": "site-a:probe:robot-a", "source_id": "site-a:collector:collector-a",
                            "target_id": "site-a:robot:robot-a", "kind": "probe", "expected": True,
                            "reachable": True, "failure_stage": "none", "duration_ms": 10.0}
    with pytest.raises(ValidationError):
        MonitoringSnapshot.model_validate(snapshot(links=[link]))


def test_peer_snapshots_must_declare_their_schema_version():
    value = snapshot()
    del value["schema_version"]
    with pytest.raises(ValidationError):
        MonitoringSnapshot.model_validate(value)


@pytest.mark.parametrize("url", ["http://remote.example.invalid", "ftp://robot.example.invalid",
                                  "https://user:private@robot.example.invalid",
                                  "https://robot.example.invalid/?token=private",
                                  "https://robot.example.invalid/#private",
                                  "https://@robot.example.invalid",
                                  "https://robot.example.invalid/\x00"])
def test_sources_are_registered_read_targets_with_tls_or_literal_loopback(url):
    value = configuration()
    value["sources"][0]["url"] = url
    with pytest.raises(ValidationError):
        MonitoringConfig.model_validate(value)


def test_generic_health_url_rejects_control_characters():
    value = configuration()
    value["sources"][0].update(kind="http", url="https://service.example.invalid/health\x00")
    with pytest.raises(ValidationError):
        MonitoringConfig.model_validate(value)


def test_reader_and_source_credentials_are_isolated_and_not_printable():
    cfg = MonitoringConfig.model_validate(configuration())
    reader_token, source_token = "r" * 40, "u" * 40
    credentials = load_credentials(cfg, {"MONITOR_READ": reader_token, "CORE_READ": source_token})
    assert credentials.authorize(reader_token).sites == frozenset({"site-a"})
    assert credentials.authorize("wrong") is None
    assert credentials.source_token("robot-a") == source_token
    assert reader_token not in repr(credentials) and source_token not in repr(credentials)
    with pytest.raises(ValueError):
        load_credentials(cfg, {"MONITOR_READ": reader_token, "CORE_READ": reader_token})
    missing_upstream = load_credentials(cfg, {"MONITOR_READ": reader_token})
    assert missing_upstream.authorize(reader_token) is not None
    with pytest.raises(ValueError):
        missing_upstream.source_token("robot-a")


def test_unknown_reader_sites_duplicate_sources_and_repair_configuration_are_rejected():
    base = configuration()
    cases = [deepcopy(base) for _ in range(3)]
    cases[0]["readers"][0]["sites"] = ["unregistered-site"]
    cases[1]["sources"].append(deepcopy(base["sources"][0]))
    cases[2]["sources"][0]["repair_command"] = "restart"
    for value in cases:
        with pytest.raises(ValidationError):
            MonitoringConfig.model_validate(value)


def test_peer_scope_cannot_overlap_another_owner():
    value = configuration()
    value["sources"].append({"id": "peer-a", "site_id": "site-a", "kind": "peer",
                              "url": "https://peer.example.invalid", "peer_sites": ["site-a"]})
    with pytest.raises(ValidationError):
        MonitoringConfig.model_validate(value)


def test_duplicate_yaml_keys_are_not_silently_accepted(tmp_path):
    source = tmp_path / "config.yaml"
    source.write_text("site_id: site-a\nsite_id: private-value\n", encoding="utf-8")
    with pytest.raises(ValueError) as failure:
        load_config(source)
    assert "private-value" not in str(failure.value)
