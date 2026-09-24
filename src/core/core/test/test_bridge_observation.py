"""`bridge/observation.py` — the decide half of every sensor callback (C1).

`ros_bridge.py` cannot be imported by host pytest, so a decision computed inside
one of its callbacks was unreachable: the source-grep checks standing in for it
passed on wrong values. These are value assertions for those decisions —
duck-typed services, injected clocks, no rclpy.

Plan: `docs/plans/2026-09-06-module-split-criteria.md`.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from core.bridge import observation as obs


class _Sink:
    """One callable that records how it was called."""

    def __init__(self, name: str, calls: list, returns=None) -> None:
        self._name = name
        self._calls = calls
        self._returns = returns

    def __call__(self, *args, **kwargs):
        self._calls.append((self._name, args, kwargs))
        return self._returns


def _sink(calls: list, name: str, returns=None) -> _Sink:
    return _Sink(name, calls, returns)


def _services():
    """A `CoreServices`-shaped double. Every leaf records into `svc.calls`."""
    calls: list = []
    svc = SimpleNamespace(
        calls=calls,
        state=SimpleNamespace(
            set_sensor=_sink(calls, "state.set_sensor"),
            set_line_follow=_sink(calls, "state.set_line_follow"),
            set_traffic_policy=_sink(calls, "state.set_traffic_policy"),
            set_capabilities_degraded=_sink(
                calls, "state.set_capabilities_degraded"),
            set_hitl_requested=_sink(calls, "state.set_hitl_requested"),
        ),
        command=SimpleNamespace(
            clear_navigation=_sink(calls, "command.clear_navigation"),
            set_nav_twist=_sink(calls, "command.set_nav_twist"),
        ),
        line_follow=SimpleNamespace(
            active=False,
            observe=_sink(calls, "line_follow.observe", returns=True),
            invalidate=_sink(calls, "line_follow.invalidate", returns=True),
            tick=_sink(calls, "line_follow.tick"),
            status=_sink(calls, "line_follow.status", returns="STATUS"),
        ),
        traffic_policy=SimpleNamespace(
            observe=_sink(calls, "traffic_policy.observe"),
            reset=_sink(calls, "traffic_policy.reset", returns="RESET"),
            mode=SimpleNamespace(value="ENFORCED"),
        ),
        advisory_feed=SimpleNamespace(
            ingest=_sink(calls, "advisory_feed.ingest")),
        vision=SimpleNamespace(publish=_sink(calls, "vision.publish")),
        maps=SimpleNamespace(
            set_path=_sink(calls, "maps.set_path"),
            set_costmap=_sink(calls, "maps.set_costmap"),
        ),
        power=SimpleNamespace(on_range=_sink(calls, "power.on_range")),
        # `apply_voltage` is the real policy; `percent=None` is the moment
        # right after the filter, where it stops. That is enough to see whether
        # the reading was routed at all.
        battery=SimpleNamespace(
            on_voltage=_sink(calls, "battery.on_voltage"), percent=None),
    )
    return svc, calls


def _calls(calls: list, name: str) -> list:
    return [entry for entry in calls if entry[0] == name]


def _warn(calls: list) -> _Sink:
    return _sink(calls, "logger.warning")


def _logger(calls: list) -> SimpleNamespace:
    return SimpleNamespace(warn=_sink(calls, "logger.warn"),
                           error=_sink(calls, "logger.error"))


# --- line/observation --------------------------------------------------------

def _line_payload(**overrides) -> str:
    payload = {"source": "IR_LINE", "stamp": 12.5, "visible": True,
               "error": 0.25, "confidence": 0.9}
    payload.update(overrides)
    return json.dumps(payload)


def test_a_well_formed_observation_reaches_the_manager_with_both_clocks():
    """The ROS clock and the receipt clock are different questions."""
    svc, calls = _services()

    obs.line_observation(svc, _line_payload(),
                         source_now=100.0, received_at=50.0)

    _name, _args, kwargs = _calls(calls, "line_follow.observe")[0]
    assert kwargs == {"received_at": 50.0, "source_now": 100.0}
    mirror = _calls(calls, "state.set_sensor")[0][1][1]
    assert mirror == {"valid": True, "accepted": True, "source": "IR_LINE"}
    assert _calls(calls, "command.clear_navigation") == []


def test_a_string_visible_is_rejected_not_coerced():
    """`"true"` is not a verdict — coercing it would let malformed evidence drive."""
    svc, calls = _services()

    obs.line_observation(svc, _line_payload(visible="true"),
                         source_now=1.0, received_at=2.0)

    assert _calls(calls, "line_follow.observe") == []
    assert _calls(calls, "line_follow.invalidate")[0][2] == {"received_at": 2.0}
    mirror = _calls(calls, "state.set_sensor")[0][1][1]
    assert mirror["valid"] is False
    assert mirror["reason"] == "invalid_observation"
    assert "visible must be a boolean" in mirror["detail"]
    assert _calls(calls, "command.clear_navigation"), "invalidate returned True"


def test_a_rejection_that_is_already_handled_does_not_clear_again():
    """`invalidate` returning False means nothing was driving, so nothing to stop."""
    svc, calls = _services()
    svc.line_follow.invalidate = _sink(calls, "line_follow.invalidate",
                                       returns=False)

    obs.line_observation(svc, "{not json", source_now=1.0, received_at=2.0)

    assert _calls(calls, "command.clear_navigation") == []
    assert _calls(calls, "line_follow.tick") == []
    assert _calls(calls, "state.set_line_follow") == []
    assert _calls(calls, "state.set_sensor")[0][1][1]["valid"] is False


# --- road/observation --------------------------------------------------------

def _road_payload(**overrides) -> str:
    payload = {
        "source": "CAMERA_ROAD", "stamp": 5.0, "map_id": "survey:abcd1234",
        "scene_revision": "7",
        "lane": {"visible": True, "error": 0.1, "confidence": 0.9},
        "stop_line": {"visible": False, "image_row": None,
                      "distance_m": None, "confidence": 0.0},
        "crosswalk": {"visible": False, "image_row": None,
                      "distance_m": None, "confidence": 0.0},
        "signal": {"visible": False, "conflict": False,
                   "colour": None, "confidence": 0.0},
    }
    payload.update(overrides)
    return json.dumps(payload)


def test_valid_road_evidence_reaches_the_policy_and_is_mirrored():
    svc, calls = _services()

    obs.road_observation(svc, _road_payload(),
                         source_now=100.0, received_at=50.0)

    _name, _args, kwargs = _calls(calls, "traffic_policy.observe")[0]
    assert kwargs == {"received_at": 50.0, "source_now": 100.0}
    mirror = _calls(calls, "state.set_sensor")[0][1][1]
    assert mirror["valid"] is True
    assert mirror["map_id"] == "survey:abcd1234"
    assert mirror["scene_revision"] == "7"
    assert mirror["context_id"] is None, "context is optional (D-162)"
    assert _calls(calls, "state.set_traffic_policy") == []


def test_malformed_road_evidence_enforces_by_cancelling_navigation():
    svc, calls = _services()          # mode defaults to ENFORCED

    obs.road_observation(svc, "{not json", source_now=1.0, received_at=2.0)

    assert _calls(calls, "traffic_policy.reset")[0][1] == (
        "invalid_road_observation",)
    assert _calls(calls, "command.clear_navigation")
    assert _calls(calls, "state.set_traffic_policy")
    mirror = _calls(calls, "state.set_sensor")[0][1][1]
    assert mirror["valid"] is False and mirror["reason"] == "invalid_observation"


def test_the_same_malformed_evidence_in_advisory_mode_leaves_the_route_alone():
    """Advisory evidence may be wrong; only an enforced lease buys a cancel."""
    svc, calls = _services()
    svc.traffic_policy.mode = SimpleNamespace(value="ADVISORY")

    obs.road_observation(svc, "{not json", source_now=1.0, received_at=2.0)

    assert _calls(calls, "traffic_policy.reset")
    assert _calls(calls, "command.clear_navigation") == []


# --- detection_evidence ------------------------------------------------------

def test_bad_wire_bytes_become_none_not_a_crash():
    svc, calls = _services()

    obs.detection_evidence(svc, "<<<not json>>>")

    assert _calls(calls, "advisory_feed.ingest") == [
        ("advisory_feed.ingest", (None,), {})]


def test_a_well_formed_packet_is_ingested_as_parsed():
    svc, calls = _services()

    obs.detection_evidence(svc, json.dumps({"boxes": [[1, 2, 3, 4]]}))

    assert _calls(calls, "advisory_feed.ingest")[0][1][0] == {
        "boxes": [[1, 2, 3, 4]]}


# --- camera/preview ----------------------------------------------------------

def _preview(fmt="jpeg; source=front; width=640; height=480",
             data=b"\xff\xd8JPEG"):
    return SimpleNamespace(
        format=fmt,
        data=data,
        header=SimpleNamespace(
            stamp=SimpleNamespace(sec=3, nanosec=500_000_000),
            frame_id="camera_front",
        ),
    )


def test_a_jpeg_preview_is_stored_with_its_capture_stamp():
    svc, calls = _services()

    obs.camera_preview(svc, _preview(), warn=_warn(calls))

    _name, args, kwargs = _calls(calls, "vision.publish")[0]
    assert args == (b"\xff\xd8JPEG",)
    assert kwargs["captured_at"] == 3.5, "stamp is sec + nanosec * 1e-9"
    assert kwargs["frame_id"] == "camera_front"
    assert kwargs["source"] == "FRONT"
    assert kwargs["width"] == 640
    assert _calls(calls, "logger.warning") == []


def test_a_non_jpeg_preview_is_dropped_with_a_warning():
    """Display-only — a wrong format must never reach the driving policy."""
    svc, calls = _services()

    obs.camera_preview(svc, _preview(fmt="png"), warn=_warn(calls))

    assert _calls(calls, "vision.publish") == []
    assert _calls(calls, "logger.warning")[0][1][0] == (
        "ignored camera preview: camera preview format must be jpeg")


# --- robot/hitl_request ------------------------------------------------------

def test_a_requested_hitl_is_logged_and_mirrored():
    svc, calls = _services()
    raw = json.dumps({"requested": True, "module": "line", "confidence": 0.75})

    obs.hitl_request(svc, raw, logger=_logger(calls))

    assert _calls(calls, "logger.warn")[0][1][0] == (
        "HITL Assistance Requested by [line] (confidence: 0.75)")
    assert _calls(calls, "state.set_hitl_requested")[0][1] == (True,)


def test_an_unparsable_hitl_request_changes_nothing_but_the_log():
    svc, calls = _services()

    obs.hitl_request(svc, "{not json", logger=_logger(calls))

    assert _calls(calls, "state.set_hitl_requested") == []
    assert "Failed to parse HITL request" in _calls(
        calls, "logger.error")[0][1][0]


# --- robot/degraded_modules --------------------------------------------------

def test_the_degraded_list_is_split_and_trimmed():
    svc, calls = _services()

    obs.degraded_modules(svc, " camera , ,imu,  ")

    assert _calls(calls, "state.set_capabilities_degraded")[0][1] == (
        ["camera", "imu"],)


# --- nav_cmd_vel -------------------------------------------------------------

def test_nav_twist_is_dropped_while_the_line_follow_owns_the_wheels():
    svc, calls = _services()
    svc.line_follow.active = True

    obs.nav_twist(svc, 0.4, -0.2)

    assert _calls(calls, "command.set_nav_twist") == [], "dropped, not queued"


def test_nav_twist_is_admitted_when_the_line_follow_is_idle():
    svc, calls = _services()

    obs.nav_twist(svc, 0.4, -0.2)

    sent = _calls(calls, "command.set_nav_twist")[0][1][0]
    assert (sent.linear, sent.angular) == (0.4, -0.2)


# --- plan / costmap ----------------------------------------------------------

def _path(points):
    return SimpleNamespace(poses=[
        SimpleNamespace(pose=SimpleNamespace(
            position=SimpleNamespace(x=x, y=y)))
        for x, y in points
    ])


def test_a_plan_becomes_a_point_list():
    svc, calls = _services()

    obs.nav_path(svc, _path([(1.0, 2.0), (3.0, 4.0)]), warn=_warn(calls))

    assert _calls(calls, "maps.set_path")[0][1] == (
        [{"x": 1.0, "y": 2.0}, {"x": 3.0, "y": 4.0}],)


def test_an_unreadable_plan_is_ignored_not_fatal():
    svc, calls = _services()

    obs.nav_path(svc, _path([("not-a-number", 2.0)]), warn=_warn(calls))

    assert _calls(calls, "maps.set_path") == []
    assert _calls(calls, "logger.warning")[0][1][0].startswith(
        "ignored nav path: ")


def _costmap(size_x=4, size_y=3, resolution=0.05, data=None):
    origin = SimpleNamespace(
        position=SimpleNamespace(x=1.0, y=2.0),
        orientation=SimpleNamespace(w=1.0, x=0.0, y=0.0, z=0.0),
    )
    return SimpleNamespace(
        metadata=SimpleNamespace(size_x=size_x, size_y=size_y,
                                 resolution=resolution, origin=origin),
        data=[0, 0, 0] if data is None else data,
    )


def test_a_costmap_snapshot_is_stored_under_its_own_kind():
    svc, calls = _services()

    obs.nav_costmap(svc, "local", _costmap(), warn=_warn(calls))

    _name, args, _kwargs = _calls(calls, "maps.set_costmap")[0]
    assert args[0] == "local"
    assert args[1]["width"] == 4
    assert args[1]["origin"] == {"x": 1.0, "y": 2.0, "yaw": 0.0}


def test_the_warning_names_the_kind_that_failed():
    svc, calls = _services()

    obs.nav_costmap(svc, "global", _costmap(size_x="nope"), warn=_warn(calls))

    assert _calls(calls, "maps.set_costmap") == []
    assert _calls(calls, "logger.warning")[0][1][0].startswith(
        "ignored global costmap: ")


# --- us_sensor/range ---------------------------------------------------------

def _range(range_m, min_range=0.02, max_range=4.0):
    return SimpleNamespace(header=SimpleNamespace(frame_id="us_front"),
                           range=range_m, min_range=min_range,
                           max_range=max_range, field_of_view=0.5)


def test_a_reading_inside_the_sensor_range_wakes_power():
    svc, calls = _services()

    obs.us_range(svc, _range(1.25), received_at=10.0)

    assert _calls(calls, "power.on_range") == [
        ("power.on_range", (1.25,), {})]
    mirror = _calls(calls, "state.set_sensor")[0][1]
    assert mirror[0] == "ultrasonic"
    assert mirror[1]["received_at"] == 10.0


def test_a_saturated_reading_is_not_a_distance_but_is_still_mirrored():
    """Out of the sensor's own range means "nothing there", not "99 m away"."""
    svc, calls = _services()

    obs.us_range(svc, _range(99.0), received_at=10.0)

    assert _calls(calls, "power.on_range") == []
    assert _calls(calls, "state.set_sensor"), "the raw sample is still shown"


def test_a_nan_reading_cannot_be_compared_as_a_distance():
    svc, calls = _services()

    obs.us_range(svc, _range(float("nan")), received_at=10.0)

    assert _calls(calls, "power.on_range") == []


# --- batt_state --------------------------------------------------------------

def _battery(voltage=12.4, percentage=0.88):
    return SimpleNamespace(voltage=voltage, percentage=percentage,
                           power_supply_status=2, location="pack")


def test_batt_state_drives_the_policy_when_it_is_the_only_voltage_source():
    """An ADC-only build has no `battery/voltage`; this topic is it (SAF-005)."""
    svc, calls = _services()

    obs.batt_state(svc, _battery(), received_at=10.0, voltage_topic_seen=False)

    assert _calls(calls, "battery.on_voltage") == [
        ("battery.on_voltage", (12.4,), {})]


def test_batt_state_defers_once_the_dedicated_voltage_topic_has_spoken():
    """Two sources must not both feed the same filter; the dedicated one wins."""
    svc, calls = _services()

    obs.batt_state(svc, _battery(), received_at=10.0, voltage_topic_seen=True)

    assert _calls(calls, "battery.on_voltage") == []
    mirror = _calls(calls, "state.set_sensor")[0][1]
    assert mirror[0] == "battery"
    assert mirror[1]["voltage"] == 12.4
