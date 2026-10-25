"""Forwarding and repeated reads cannot make old evidence young again."""

from datetime import datetime, timedelta, timezone

import pytest

from rosy.monitoring.cache import ObservationCache
from rosy.monitoring.config import MonitoringConfig
from rosy.monitoring.models import MonitoringNode, MonitoringSnapshot


BASE = datetime(2026, 10, 25, tzinfo=timezone.utc)


class Clock:
    t = 0.0

    def monotonic(self):
        return self.t

    def utcnow(self):
        return BASE + timedelta(seconds=self.t)

    def advance(self, seconds):
        self.t += seconds


def observed_node(*, site="site-a", collector="collector-a", source="pc-a", age=100.0,
                  kind="host", health="OK", sample="host-1", sampled_at=None):
    ttl = 900 if kind == "host" else 15
    return MonitoringNode.model_validate({
        "id": f"{site}:{kind}:{source}", "site_id": site, "kind": kind, "label": source,
        "origin_collector": collector, "origin_source": source, "sample_id": sample,
        "sampled_at": sampled_at or BASE - timedelta(seconds=100 if kind == "host" else 0),
        "age_s": age, "valid_for_s": ttl, "remaining_s": max(0.0, ttl - age),
        "report_remaining_s": 15.0, "freshness": "fresh" if age < ttl else "stale",
        "reported_health": health, "reason_code": None,
    })


@pytest.fixture
def runtime():
    cfg = MonitoringConfig.model_validate({
        "collector_id": "collector-a", "site_id": "site-a",
        "readers": [{"principal_id": "reader", "token_env": "READ", "sites": ["site-a", "site-b"]}],
        "sources": [
            {"id": "pc-a", "site_id": "site-a", "kind": "host_guard",
             "path": "/var/lib/rosy-host-guard/status.json", "selector": "pc-a"},
            {"id": "collector-b", "site_id": "site-a", "kind": "peer",
             "url": "https://peer.example.invalid", "peer_sites": ["site-b"]},
        ],
    })
    clock = Clock()
    return ObservationCache(cfg, monotonic=clock.monotonic, utcnow=clock.utcnow), clock


def find(cache, node_id, site="site-a"):
    return next(node for node in cache.snapshot(frozenset({site})).nodes if node.id == node_id)


def peer(clock, *, sequence=1, generation="b" * 32, health="OK"):
    owner = observed_node(site="site-b", collector="collector-b", source="collector-b",
                          kind="collector", age=0.0, sample=f"process-{sequence}",
                          sampled_at=clock.utcnow())
    host = observed_node(site="site-b", collector="collector-b", source="pc-b",
                         age=100.0 + clock.t, health=health)
    return MonitoringSnapshot.model_validate({
        "schema_version": 1, "collector_id": "collector-b", "generation": generation,
        "sequence": sequence, "produced_at": clock.utcnow(), "remaining_s": 15.0,
        "scope_sites": ["site-b"], "nodes": [owner, host], "links": [],
    })


def receive(cache, clock, value):
    cache.receive_peer("collector-b", value, request_started_at=clock.utcnow(), elapsed_s=0.0)


def test_rereading_host_report_renews_collection_but_never_source_evidence(runtime):
    cache, clock = runtime
    value = observed_node()
    cache.update_local("pc-a", nodes=(value,))
    clock.advance(16)
    old = find(cache, value.id)
    assert old.freshness == "stale" and old.reported_health == "OK" and old.remaining_s > 700
    cache.update_local("pc-a", nodes=(value,))
    refreshed = find(cache, value.id)
    assert refreshed.freshness == "fresh" and refreshed.age_s >= 116
    assert refreshed.remaining_s <= old.remaining_s and refreshed.report_remaining_s > 0
    clock.advance(801)
    cache.update_local("pc-a", nodes=(value,))
    expired = find(cache, value.id)
    assert expired.freshness == "stale" and expired.remaining_s == 0 and expired.reported_health == "OK"


def test_failed_refresh_preserves_last_verdict_without_renewing_its_report(runtime):
    cache, clock = runtime
    value = observed_node()
    cache.update_local("pc-a", nodes=(value,))
    clock.advance(10)
    cache.update_local("pc-a", complete=False)
    clock.advance(6)
    result = find(cache, value.id)
    assert result.reported_health == "OK" and result.freshness == "stale"


def test_peer_transit_and_collection_outage_consume_both_lifetimes(runtime):
    cache, clock = runtime
    value, started = peer(clock), clock.utcnow()
    clock.advance(2)
    cache.receive_peer("collector-b", value, request_started_at=started, elapsed_s=2.0)
    result = find(cache, "site-b:host:pc-b", "site-b")
    assert result.age_s >= 102 and result.remaining_s <= 798 and result.report_remaining_s <= 13
    clock.advance(14)
    result = find(cache, result.id, "site-b")
    assert result.freshness == "stale" and result.remaining_s > 700 and result.reported_health == "OK"


@pytest.mark.parametrize("sequence", [0, 1])
def test_duplicate_or_older_peer_sequence_cannot_extend_a_report(runtime, sequence):
    cache, clock = runtime
    receive(cache, clock, peer(clock))
    clock.advance(10)
    with pytest.raises(ValueError):
        receive(cache, clock, peer(clock, sequence=sequence))
    clock.advance(6)
    assert find(cache, "site-b:host:pc-b", "site-b").freshness == "stale"


def test_peer_restart_does_not_reset_original_facts_or_admit_retired_generation(runtime):
    cache, clock = runtime
    receive(cache, clock, peer(clock))
    clock.advance(10)
    before = find(cache, "site-b:host:pc-b", "site-b")
    receive(cache, clock, peer(clock, generation="c" * 32, sequence=0))
    result = find(cache, before.id, "site-b")
    assert result.remaining_s <= before.remaining_s and result.age_s >= before.age_s
    with pytest.raises(ValueError):
        receive(cache, clock, peer(clock, generation="b" * 32, sequence=100))


def test_changing_a_fact_under_the_same_sample_identity_is_rejected(runtime):
    cache, clock = runtime
    receive(cache, clock, peer(clock))
    clock.advance(1)
    with pytest.raises(ValueError):
        receive(cache, clock, peer(clock, sequence=2, health="ERROR"))
    assert find(cache, "site-b:host:pc-b", "site-b").reported_health == "OK"


def test_older_local_sample_cannot_replace_a_more_recent_error(runtime):
    cache, clock = runtime
    latest = observed_node(health="ERROR", sample="latest")
    cache.update_local("pc-a", nodes=(latest,))
    clock.advance(1)
    older = observed_node(health="OK", sample="older", age=201.0,
                          sampled_at=BASE - timedelta(seconds=200))
    with pytest.raises(ValueError):
        cache.update_local("pc-a", nodes=(older,))
    assert find(cache, latest.id).reported_health == "ERROR"


def test_newer_peer_envelope_cannot_make_an_older_source_fact_current(runtime):
    cache, clock = runtime
    latest = peer(clock, health="ERROR")
    receive(cache, clock, latest)
    clock.advance(1)
    value = peer(clock, sequence=2)
    older = value.nodes[1].model_copy(update={"sample_id": "older", "sampled_at": BASE - timedelta(seconds=200),
                                             "age_s": 201.0, "remaining_s": 699.0})
    with pytest.raises(ValueError):
        receive(cache, clock, value.model_copy(update={"nodes": (value.nodes[0], older)}))
    assert find(cache, "site-b:host:pc-b", "site-b").reported_health == "ERROR"


def test_new_sample_id_cannot_renew_unchanged_capture_time(runtime):
    cache, clock = runtime
    value = peer(clock)
    host = value.nodes[1].model_copy(update={"remaining_s": 10.0})
    receive(cache, clock, value.model_copy(update={"nodes": (value.nodes[0], host)}))
    first = find(cache, host.id, "site-b")
    clock.advance(2)
    value = peer(clock, sequence=2)
    renamed = value.nodes[1].model_copy(update={"sample_id": "another-name", "remaining_s": 10.0})
    receive(cache, clock, value.model_copy(update={"nodes": (value.nodes[0], renamed)}))
    assert find(cache, host.id, "site-b").remaining_s <= first.remaining_s - 2.0


@pytest.mark.parametrize("replacement", ["missing", "unknown"])
def test_disappearing_fact_cannot_reset_its_original_deadline(runtime, replacement):
    cache, clock = runtime
    initial = peer(clock)
    initial = initial.model_copy(update={"nodes": (initial.nodes[0],
                                                   initial.nodes[1].model_copy(update={"remaining_s": 10.0}))})
    receive(cache, clock, initial)
    first = find(cache, "site-b:host:pc-b", "site-b")
    clock.advance(1)
    value = peer(clock, sequence=2)
    nodes = (value.nodes[0],)
    if replacement == "unknown":
        unknown = value.nodes[1].model_copy(update={"sample_id": None, "sampled_at": None, "age_s": None,
                                                   "remaining_s": 0.0, "report_remaining_s": 0.0,
                                                   "freshness": "unknown", "reported_health": "UNKNOWN"})
        nodes += (unknown,)
    receive(cache, clock, value.model_copy(update={"nodes": nodes}))
    clock.advance(1)
    value = peer(clock, sequence=3)
    returned = value.nodes[1].model_copy(update={"remaining_s": 10.0})
    receive(cache, clock, value.model_copy(update={"nodes": (value.nodes[0], returned)}))
    result = find(cache, returned.id, "site-b")
    assert result.remaining_s <= first.remaining_s - 2.0
    clock.advance(8)
    assert find(cache, returned.id, "site-b").freshness == "stale"


def test_retained_fact_budget_rejects_new_identities_without_forgetting_old_ones(runtime, monkeypatch):
    cache, clock = runtime
    monkeypatch.setattr("rosy.monitoring.cache.MAX_REMEMBERED", 3, raising=False)
    receive(cache, clock, peer(clock))
    clock.advance(1)
    value = peer(clock, sequence=2)
    second = observed_node(site="site-b", collector="collector-b", source="pc-c", age=101.0)
    receive(cache, clock, value.model_copy(update={"nodes": (value.nodes[0], second)}))
    clock.advance(1)
    value = peer(clock, sequence=3)
    third = observed_node(site="site-b", collector="collector-b", source="pc-d", age=102.0)
    with pytest.raises(ValueError):
        receive(cache, clock, value.model_copy(update={"nodes": (value.nodes[0], third)}))
    assert find(cache, second.id, "site-b").reported_health == "OK"
    value = peer(clock, sequence=4)
    receive(cache, clock, value.model_copy(update={"nodes": (value.nodes[0], second)}))


@pytest.mark.parametrize("change", [
    {"collector_id": "impostor"}, {"scope_sites": ("site-c",)},
    {"produced_at": BASE + timedelta(seconds=60)},
])
def test_peer_identity_scope_and_clock_mismatch_are_rejected(runtime, change):
    cache, clock = runtime
    value = peer(clock).model_copy(update=change)
    with pytest.raises(ValueError):
        receive(cache, clock, value)


def test_aggregation_cycle_and_unregistered_local_source_cannot_publish(runtime):
    cache, clock = runtime
    value = peer(clock)
    loop = observed_node(site="site-b", collector="collector-a", source="collector-a",
                         kind="collector", age=0.0)
    with pytest.raises(ValueError):
        receive(cache, clock, value.model_copy(update={"nodes": (*value.nodes, loop)}))
    with pytest.raises(ValueError):
        cache.update_local("unregistered", nodes=(observed_node(),))


def test_filtered_snapshots_have_no_other_site_graph_or_counts(runtime):
    cache, clock = runtime
    receive(cache, clock, peer(clock))
    cache.update_local("pc-a", nodes=(observed_node(),))
    left = cache.snapshot(frozenset({"site-a"}))
    right = cache.snapshot(frozenset({"site-b"}))
    assert set(left.scope_sites) == {"site-a"} and all(n.site_id == "site-a" for n in left.nodes)
    assert set(right.scope_sites) == {"site-b"} and all(n.site_id == "site-b" for n in right.nodes)
    with pytest.raises(ValueError):
        cache.snapshot(frozenset({"not-authorized"}))
