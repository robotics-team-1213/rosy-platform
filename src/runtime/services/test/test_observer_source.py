"""D-337 T2 — observer source transport: parse, silence, fail-closed.

가짜 전송으로 관측 서비스 `/observed` 소비를 검증한다. 실전 전송(httpx)은
게으른 import 덕에 여기 닿지 않는다 — 호스트 시험은 전송이 아니라 계약을
검증한다(설계 §6, D-94: 합성 ≠ DEVICE).
"""

from __future__ import annotations

import pytest

from core_features.traffic_policy import (
    RoadEvidence,
    SignalHeadEvidence,
    SignalObserverConfigError,
    SignalObserverMonitor,
    SignalObserverPoller,
    SignalObserverSourceConfig,
    TrafficPolicyConfig,
    TrafficPolicyManager,
    TrafficPolicyMode,
    parse_observed,
)


class _NoEvents:
    """EventBus stub — this suite exercises observe/gate, not event emission."""

    def publish(self, *_args, **_kwargs) -> None:
        pass


MAP = "map_260905_update_v2"
SCENE = "road-scene-v1"


def binding(**overrides) -> SignalObserverSourceConfig:
    values = {
        "url": "http://observer:8095",
        "roi_map": {"left": "red", "mid": "yellow", "right": "green"},
        "timeout_s": 0.8,
    }
    values.update(overrides)
    return SignalObserverSourceConfig(**values)


def observed(*, left=None, mid=None, right=None, frozen=False,
             pending=False, ts=1770000000.0, confidence=0.93) -> dict:
    """A syntactic `/observed` body — lit lamps get a colour group."""
    raw = {"left": left, "mid": mid, "right": right}
    lamps = {
        name: {"lit": group is not None, "group": group,
               "confidence": confidence}
        for name, group in raw.items()
    }
    if frozen:
        stable = {
            name: {"lit": None, "group": None, "pending": True, "stale": True}
            for name in raw
        }
    else:
        stable = {
            name: {"lit": lamps[name]["lit"], "group": lamps[name]["group"],
                   "pending": pending}
            for name in raw
        }
    return {"ts": ts, "frame_id": 7, "captured_at": ts, "age_s": 0.05,
            "frozen": frozen, "lamps": lamps, "stable": stable}


@pytest.mark.parametrize("overrides", [
    {"url": "observer:8095"},
    {"url": "ftp://observer"},
    {"roi_map": {}},
    {"roi_map": {"left": "cyan"}},
    {"roi_map": {"left": "red", "top": "red"}},
    {"timeout_s": 0.0},
    {"poll_interval_s": -1.0},
])
def test_binding_is_validated(overrides):
    with pytest.raises(SignalObserverConfigError):
        binding(**overrides)


def test_confirmed_frame_maps_positions_to_colours():
    evidence = parse_observed(
        observed(left="red"), binding(), map_id=MAP, scene_revision=SCENE)

    assert isinstance(evidence, SignalHeadEvidence)
    assert (evidence.red, evidence.yellow, evidence.green) == (True, False, False)
    assert evidence.colour == "RED"
    assert evidence.confidence == pytest.approx(0.93)
    assert evidence.frozen is False and evidence.stable is True
    assert evidence.stamp == pytest.approx(1770000000.0)
    assert (evidence.map_id, evidence.scene_revision) == (MAP, SCENE)


def test_confidence_is_the_worst_mapped_lamp():
    body = observed(left="red")
    body["lamps"]["right"]["confidence"] = 0.31

    evidence = parse_observed(
        body, binding(), map_id=MAP, scene_revision=SCENE)

    assert evidence.confidence == pytest.approx(0.31)


@pytest.mark.parametrize("body_reason, payload", [
    ("frozen", observed(left="red", frozen=True)),
    ("pending debounce", observed(left="red", pending=True)),
])
def test_unconfirmed_frames_are_silence(body_reason, payload):
    assert parse_observed(
        payload, binding(), map_id=MAP, scene_revision=SCENE) is None, body_reason


@pytest.mark.parametrize("mutate", [
    lambda b: b.update(ts=None),
    lambda b: b.update(ts=float("nan")),
    lambda b: b.pop("stable"),
    lambda b: b["stable"].pop("mid"),
    lambda b: b["stable"]["mid"].update(lit="yes"),
    lambda b: b["lamps"]["mid"].pop("confidence"),
    lambda b: b["lamps"]["mid"].update(confidence=1.4),
])
def test_malformed_bodies_are_rejected(mutate):
    body = observed(left="red")
    mutate(body)

    with pytest.raises(ValueError):
        parse_observed(body, binding(), map_id=MAP, scene_revision=SCENE)


def test_poll_confirms_and_records_age():
    poller = SignalObserverPoller(
        binding(), map_id=MAP, scene_revision=SCENE,
        transport=lambda url, timeout: observed(left="red"))

    evidence = poller.poll()

    assert evidence is not None and evidence.red is True
    assert poller.last_outcome == "confirmed"
    assert poller.last_age_s == pytest.approx(0.05)


@pytest.mark.parametrize("payload,reason", [
    (observed(left="red", frozen=True), "frozen"),
    (observed(left="red", pending=True), "pending"),
    ({"error": "NO_FRAME"}, "bad_payload"),
])
def test_poll_labels_silence_reasons(payload, reason):
    poller = SignalObserverPoller(
        binding(), map_id=MAP, scene_revision=SCENE,
        transport=lambda url, timeout: payload)

    assert poller.poll() is None
    assert poller.last_outcome == reason


def test_poll_http_failure_is_silence():
    def unreachable(url, timeout):
        raise TimeoutError("observer silent")

    poller = SignalObserverPoller(
        binding(), map_id=MAP, scene_revision=SCENE, transport=unreachable)

    assert poller.poll() is None
    assert poller.last_outcome == "http_error"
    assert poller.last_age_s is None


def test_polled_evidence_feeds_the_traffic_policy_manager():
    now = [100.0]
    manager = TrafficPolicyManager(
        _NoEvents(),
        config=TrafficPolicyConfig(
            mode=TrafficPolicyMode.ENFORCED,
            map_id=MAP,
            scene_revision=SCENE,
            stop_dwell_s=0.5,
        ),
        clock=lambda: now[0],
    )
    poller = SignalObserverPoller(
        binding(), map_id=MAP, scene_revision=SCENE,
        transport=lambda url, timeout: observed(left="red"))

    def observe_road():
        manager.observe(
            RoadEvidence(
                source="CAMERA_ROAD", stamp=now[0] - 0.01,
                map_id=MAP, scene_revision=SCENE,
                stop_line_visible=True, stop_line_distance_m=0.08,
                stop_line_confidence=0.9,
            ),
            received_at=now[0], source_now=now[0] - 0.01,
        )

    for _ in range(2):
        observe_road()
        manager.observe_signal(poller.poll(), received_at=now[0])
        manager.gate(0.06, 0.0)
        now[0] += 0.51

    assert manager.status().state == "WAIT_SIGNAL"
    assert manager.status().reason == "signal_red"


class _RecordingEvents:
    def __init__(self):
        self.published = []

    def publish(self, type_, severity="info", *, source="", data=None):
        self.published.append((type_, severity, source, data or {}))


def _manager_for_monitor(now):
    return TrafficPolicyManager(
        _NoEvents(),
        config=TrafficPolicyConfig(
            mode=TrafficPolicyMode.ENFORCED,
            map_id=MAP, scene_revision=SCENE, stop_dwell_s=0.5,
        ),
        clock=lambda: now[0],
    )


def test_monitor_tick_feeds_manager_with_age_compensation():
    now = [100.0]
    manager = _manager_for_monitor(now)
    poller = SignalObserverPoller(
        binding(), map_id=MAP, scene_revision=SCENE,
        transport=lambda url, timeout: observed(left="red"))
    monitor = SignalObserverMonitor(
        poller, manager, stale_after_s=0.4, events=_RecordingEvents(),
        clock=lambda: now[0])

    monitor.tick()
    manager.gate(0.06, 0.0)

    status = manager.status()
    assert status.signal_source_kind == "fused"
    assert status.signal_head_age_s == pytest.approx(0.05)
    assert poller.last_outcome == "confirmed"


def test_monitor_announces_staleness_once_per_lapse():
    now = [100.0]
    manager = _manager_for_monitor(now)
    events = _RecordingEvents()
    flaky = {"fail": False}

    def transport(url, timeout):
        if flaky["fail"]:
            raise TimeoutError("observer silent")
        return observed(left="red")

    poller = SignalObserverPoller(
        binding(), map_id=MAP, scene_revision=SCENE, transport=transport)
    monitor = SignalObserverMonitor(
        poller, manager, stale_after_s=0.4, events=events,
        clock=lambda: now[0])

    monitor.tick()
    flaky["fail"] = True
    now[0] = 100.3
    monitor.tick()
    assert events.published == []

    now[0] = 100.6
    monitor.tick()
    assert len(events.published) == 1
    type_, severity, source, data = events.published[0]
    assert type_ == "nav.traffic_policy_signal_source_stale"
    assert severity == "warning"
    assert source == "traffic_policy_manager"
    assert data["outcome"] == "http_error"
    assert data["silent_for_s"] == pytest.approx(0.6)

    now[0] = 100.9
    monitor.tick()
    assert len(events.published) == 1

    flaky["fail"] = False
    monitor.tick()
    flaky["fail"] = True
    now[0] += 0.41
    monitor.tick()
    assert len(events.published) == 2


def test_monitor_start_stop_is_clean():
    now = [100.0]
    manager = _manager_for_monitor(now)

    def unreachable(url, timeout):
        raise TimeoutError("observer silent")

    poller = SignalObserverPoller(
        binding(url="http://127.0.0.1:9", poll_interval_s=0.01),
        map_id=MAP, scene_revision=SCENE, transport=unreachable)
    monitor = SignalObserverMonitor(
        poller, manager, stale_after_s=0.4, events=_RecordingEvents(),
        clock=lambda: now[0])

    monitor.start()
    assert monitor.is_alive()
    monitor.stop()
    assert not monitor.is_alive()
