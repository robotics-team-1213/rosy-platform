"""D-725 rev 1 + D-760 4: a stale native SIM pose waits in link_wait; any other lost pose still stops the trip."""
import dataclasses

from test_trip_link_wait import NEW, _running, _setup, _ticks


def _unknown(fleet, source):
    fleet.p["a"].pose = dataclasses.replace(fleet.p["a"].pose, state="UNKNOWN", source=source)


def test_a_stale_sim_pose_waits_and_the_trip_runs_on_when_it_is_fresh_again():
    runner, store, fleet = _running(*_setup({"a": NEW}))
    fresh = fleet.p["a"].pose
    _unknown(fleet, "native_gazebo_sim")
    _ticks(runner, fleet, 2)
    view = runner.view("a")
    assert view["state"] == "link_wait" and view["wait"]["kind"] == "pose_stale", (view["state"], view.get("reason"))
    fleet.p["a"].pose = dataclasses.replace(fresh, odom_stamp=fleet.now - 0.2)
    _ticks(runner, fleet, 2)
    assert runner.view("a")["state"] == "running"


def test_an_unknown_pose_from_any_other_source_still_stops_the_trip():
    runner, store, fleet = _running(*_setup({"a": NEW}))
    _unknown(fleet, "sighting")
    _ticks(runner, fleet, 2)
    view = runner.view("a")
    assert (view["state"], view["reason"]) == ("stopped", "pose")
