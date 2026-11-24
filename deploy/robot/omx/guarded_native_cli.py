#!/usr/bin/env python3
"""Native LeRobot Factory Wiring & CLI Session Runner (`guarded_native_cli.py`).

Single Responsibility:
  - Wraps native LeRobot `make_robot_from_config` / `make_teleoperator_from_config` / `build_dataset_frame`
    factories (`run_native`) so `OmxFollower` and `OmxLeader` use passive connection (`connect_passive`),
    real-time guarded streaming (`NativeJointMotion`), and fail-closed cleanup (`close_device`).
  - CLI entrypoint (`main`) for `record [--teacher]` and `teleoperate [--body-only]`.
"""
from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import sys
import time

from bench_live_frames import offer_preview, preview_reset_loop, start_live_frames
from guarded_device import close_device, connect_passive
from guarded_native_watch import BoundaryWatch
from guarded_native_link import ENV as LINK_ENV, IDLE_LIMIT_S, LinkChannel, LinkEvents
from teleop_speed import stage_from_env


_GUARD_NOTED = [False]


def note_end(reason: str) -> None:
    """End evidence for the bench (the session folder is the recorder's cwd): why the session ended by a guard event, not by its plan or the user's stop.
    The first reason wins. The bench reads it with the session record and never starts the automatic home after one (bench_record_manual._publish_end)."""
    _GUARD_NOTED[0] = True
    path = Path("guard-end.json")
    try:
        if not path.exists():
            path.write_text(json.dumps({"reason": str(reason)[:300], "t": time.time()}), encoding="utf-8")
    except OSError:
        pass


def note_clean_end() -> None:
    """Explicit clean-end marker for bench auto-home (fail closed when missing, when guard-end.json exists, or if note_end ever ran)."""
    if _GUARD_NOTED[0] or Path("guard-end.json").exists():
        return
    try:
        Path("clean-end.json").write_text(json.dumps({"clean": True, "t": time.time()}), encoding="utf-8")
    except OSError:
        pass


def _gn_attr(name: str, default):
    for mod_name in ("omx_guard_test", "guarded_native"):
        mod = sys.modules.get(mod_name)
        if mod is not None and hasattr(mod, name):
            return getattr(mod, name)
    return default


def leader_mount(leader) -> dict:
    """The Leader's commissioned mount offsets: `<calibration>.mount.json` beside its calibration file, else none."""
    path = getattr(leader, "calibration_fpath", None)
    if not path:
        return {}
    try:  # only a missing file means "no mount offset"; anything unreadable stops the session before torque
        text = Path(path).with_suffix(".mount.json").read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    mount = json.loads(text)
    if type(mount) is not dict:
        raise ValueError(f"{Path(path).with_suffix('.mount.json')}: a JSON object of joint: ticks is required")
    for key in ("gripper", "follower_floor"):  # a present key must state something: null would silently mean "none"
        if key in mount and mount[key] is None:
            raise ValueError(f"{Path(path).with_suffix('.mount.json')}: {key} is null; remove the key or state its values")
    return mount  # body joints: half-turn ticks; "follower_floor": {joint: tick}; "gripper": the trigger and jaw ends (NativeJointMotion validates both)


def run_native(module, follower_type, leader_type, *, body_only=False, teacher=False):
    """Keep native factories/recording; replace only hardware lifecycle and action guard."""
    from guarded_native import NativeJointMotion

    devices = []
    if body_only and hasattr(module, "record"):
        raise ValueError("body-only mode is manual teleoperation only")
    if teacher and not hasattr(module, "record"):
        raise ValueError("teacher mode is a recording")
    _GUARD_NOTED[0] = False
    shared = {}
    original_robot = module.make_robot_from_config
    original_teleop = module.make_teleoperator_from_config

    def stop_watch():
        """The pause watch, verified ended. One that is still running keeps the bus: control is not resumed and the port is not closed."""
        watch = shared.get("watch")
        if watch is None:
            return None
        if not watch.stop():
            shared["hung"] = True
            raise RuntimeError("boundary watch did not end: control is not resumed and the port stays open")
        shared.pop("watch")
        watch_fault = getattr(watch, "fault_exc", None)
        if watch_fault is not None:
            note_end(f"guard_fault: {watch_fault}")
        elif watch.expired:
            note_end(getattr(watch, "pause_saturated", None) or getattr(watch, "read_failure", None) or "pause_expired")
        return watch

    def request_stop():  # a pause past BOUNDARY_MAX_S: end like a user stop (lerobot's own Esc flags), the arm holds meanwhile
        watch = shared.get("watch")
        note_end("pause_saturated" if getattr(watch, "pause_saturated", None) else "pause_read_failure" if getattr(watch, "read_failure", None)
                 else "pause_over_bound")  # lerobot may then end normally (exit 0): the bench must still not move the arm again
        events = shared.get("events")
        if events is not None:
            events["stop_recording"] = events["exit_early"] = True

    def start_watch():  # the pause after a record loop: nothing calls the guard until the next one
        motion = shared.get("motion")
        if motion is not None and not motion.failed:
            shared["watch"] = BoundaryWatch(motion, on_expire=request_stop)
            shared["watch"].start()

    class Follower(follower_type):
        def connect(self, calibrate=True):
            _gn_attr("connect_passive", connect_passive)(self, follower=True)

        def send_action(self, action):
            if "motion" not in shared:
                import inspect
                from motor_health import MotorHealth

                mon = MotorHealth(async_publish=True) if "async_publish" in inspect.signature(MotorHealth).parameters else MotorHealth()
                motion_cls = _gn_attr("NativeJointMotion", NativeJointMotion)
                shared["motion"] = motion_cls(
                    self.bus,
                    None if teacher else shared["leader"].bus,
                    body_only=body_only,
                    teacher=teacher,
                    stage=None if teacher or body_only else stage_from_env(),
                    monitor=mon,
                    **({} if teacher else (lambda m: {"grip_map": m.pop("gripper", None), "follower_floor": m.pop("follower_floor", None), "mount": m})(
                        leader_mount(shared["leader"]))),
                )
            sent = shared["motion"].send(action)
            shared["sent"] = sent
            return sent

        def disconnect(self):
            stop_watch()
            _gn_attr("close_device", close_device)(self)

    class Leader(leader_type):
        def connect(self, calibrate=True):
            _gn_attr("connect_passive", connect_passive)(self, follower=False)

        def disconnect(self):
            stop_watch()  # the watch reads the Follower only, but a cut it makes touches both: nobody else uses a bus while it lives
            _gn_attr("close_device", close_device)(self)

    def robot_factory(config):
        device = original_robot(config)
        if not isinstance(device, follower_type) or getattr(config, "use_degrees", False):
            raise ValueError("guard supports only normalized OMX follower manual control")
        device.__class__ = Follower
        devices.append(device)
        return device

    def teleop_factory(config):
        device = original_teleop(config)
        if teacher:
            if isinstance(device, leader_type):
                raise ValueError("teacher mode replays a trajectory, not a leader")
            if all(hasattr(device, a) for a in ("get_action", "frames", "calls", "names")):
                orig_get_action = device.get_action

                def replay_get_action():
                    motion = shared.get("motion")
                    if motion is None or not motion.tracking:
                        return dict(zip(device.names, device.frames[min(device.calls, len(device.frames) - 1)]))
                    return orig_get_action()

                device.get_action = replay_get_action
            return device
        if not isinstance(device, leader_type):
            raise ValueError("guard requires OMX leader")
        device.__class__ = Leader
        devices.append(device)
        shared["leader"] = device
        return device

    module.make_robot_from_config = robot_factory
    module.make_teleoperator_from_config = teleop_factory
    original_frame = getattr(module, "build_dataset_frame", None)
    preview = start_live_frames() if original_frame is not None else None
    link = LinkChannel(os.environ[LINK_ENV]) if os.environ.get(LINK_ENV) and not (teacher or body_only) else None  # W16: linked wait between episodes
    if original_frame is not None:

        def frame(features, values, prefix):
            if prefix == module.ACTION:
                values = shared["sent"]
                if link is not None:
                    link.frames += 1
            elif preview is not None and prefix == module.OBS_STR:
                offer_preview(preview, values)
            return original_frame(features, values, prefix=prefix)

        module.build_dataset_frame = frame
    original_loop = getattr(module, "record_loop", None)
    prerolled = [teacher or body_only]  # the replay teacher is never run twice, and teleoperate has no episodes

    class PrerollEvents:  # lerobot's loop ends early on events["exit_early"]: here, once the guard tracks
        def __init__(self, events):
            self.events = events

        def __getitem__(self, key):
            return key == "exit_early" and shared.get("motion") is not None and shared["motion"].tracking or self.events[key]

        def __setitem__(self, key, value):
            self.events[key] = value

    def wait_linked(args, kwargs):
        """Ready state: the same loop as the pre-roll (no dataset, same guard and pause watch around it) until the guard is aligned and the bench asks to record."""
        if shared.get("motion") is not None:
            shared["motion"].boundary = True  # the save that came before is a declared pause
        link_ready = lambda: shared.get("motion") is None or (not shared["motion"].boundary and shared["motion"].tracking)
        link.publish("waiting" if link_ready() else "aligning")
        events = LinkEvents(kwargs["events"], link, True, is_ready=None if shared.get("motion") is None else link_ready)
        robot = kwargs.get("robot")
        observe = getattr(robot, "get_observation", None)
        had_obs = robot is not None and "get_observation" in robot.__dict__
        if preview is not None and observe is not None and not had_obs:
            robot.get_observation = lambda: (lambda obs: (offer_preview(preview, obs), obs)[1])(observe())
        try:
            original_loop(*args, **{**kwargs, "dataset": None, "events": events, "control_time_s": IDLE_LIMIT_S})
        finally:
            if shared.get("motion") is not None:
                shared["motion"].boundary = False
            if observe is not None and preview is not None and not had_obs:
                robot.__dict__.pop("get_observation", None)
        if events.started and not events.finished and not kwargs["events"]["stop_recording"] and link_ready():
            link.publish("recording")
            return True
        # finish, a stop event, unaligned abort, or the idle limit: clean end through lerobot's own exit (no frame saved, dataset finalized)
        kwargs["events"]["stop_recording"] = kwargs["events"]["rerecord_episode"] = True
        return False

    if original_loop is not None:  # each record loop (episode, reset) starts after lerobot's own pauses, e.g. save_episode

        def loop(*args, **kwargs):
            if link is not None and prerolled[0] and kwargs.get("dataset") is None and kwargs.get("policy") is None:
                return None  # lerobot's fixed reset period: replaced by the wait before the next episode; the save that follows stays under the pause watch
            shared["events"] = kwargs.get("events")
            watch = stop_watch()
            fault = getattr(watch, "fault_exc", None)
            if fault is not None:  # the watch found a fault (cut already applied) even if this call came while its read was in flight
                note_end(f"guard_fault: {fault}")
                raise RuntimeError(f"pause watch fault, control is not resumed: {fault}") from fault
            if watch is not None and watch.expired:  # healthy but over the bound (or unreadable): no new motion, the session ends the way a stop ends
                raise KeyboardInterrupt(getattr(watch, "pause_saturated", None) and f"{watch.pause_saturated}: ending the session, torque kept"
                                        or getattr(watch, "read_failure", None) and f"record loop pause watch could not read the arm ({watch.read_failure}): ending the session, torque kept"
                                        or "record loop pause longer than the bound: ending the session")
            if not prerolled[0] and kwargs.get("dataset") is not None and kwargs.get("policy") is None:
                prerolled[0] = True  # the 1 degree/s alignment runs before episode 0 starts, not inside it: same loop, no dataset
                if link is not None:
                    link.publish("aligning")
                pre_kwargs = {**kwargs, "dataset": None, "events": PrerollEvents(kwargs["events"]), "control_time_s": 120}
                preview_reset_loop(preview, pre_kwargs)
                original_loop(*args, **pre_kwargs)
                if kwargs["events"].get("stop_recording"):  # Esc ends the pre-roll: no episode, the normal stop ending
                    raise KeyboardInterrupt("stop requested before the first episode")
                if shared.get("motion") is None or not shared["motion"].tracking:
                    raise ValueError("leader alignment did not finish before the first episode (pre-roll ended without tracking, limit 120 s)")
            episode = link is not None and kwargs.get("dataset") is not None and kwargs.get("policy") is None
            if episode:
                if not wait_linked(args, kwargs):
                    start_watch()  # keep BoundaryWatch active through dataset.finalize() and disconnect()
                    return None
                link.frames = 0
                kwargs = {**kwargs, "events": LinkEvents(kwargs["events"], link, False, require_frame=original_frame is not None)}
            if not episode and shared.get("motion") is not None:
                shared["motion"].boundary = True
            if not episode and kwargs.get("dataset") is None:
                kwargs = dict(kwargs)
                preview_reset_loop(preview, kwargs)
            try:
                return original_loop(*args, **kwargs)
            finally:  # a loop that sent no command leaves no mark for the next one
                if shared.get("motion") is not None:
                    shared["motion"].boundary = False
                start_watch()
                if episode:
                    link.publish("saving")
                    kwargs["events"].poll_final()
                    if not kwargs["events"].events.get("rerecord_episode"):
                        link.episode += 1
                    link.publish("saving")

        module.record_loop = loop
    fault = None
    try:
        return module.main()
    except BaseException as exc:
        fault = exc
        if not (isinstance(exc, KeyboardInterrupt) and not exc.args):  # a plain Ctrl-C/SIGTERM is the user's stop; everything else is a guard event
            note_end(f"exception: {type(exc).__name__}: {exc}")
        raise
    finally:
        try:
            stop_watch()
        except RuntimeError as exc:
            errors_hung = exc  # the watch thread still owns the bus: no port is closed underneath it
        else:
            errors_hung = None
        if original_loop is not None:
            module.record_loop = original_loop  # before any device cleanup can be interrupted
        errors = [errors_hung] if errors_hung is not None else []
        close_fn = _gn_attr("close_device", close_device)
        for device in ([] if errors_hung is not None else reversed(devices)):
            try:
                close_fn(device)
            except Exception as exc:
                errors.append(exc)
        module.make_robot_from_config, module.make_teleoperator_from_config = original_robot, original_teleop
        if original_frame is not None:
            module.build_dataset_frame = original_frame
        motion = shared.get("motion")
        if fault is not None and motion is not None and not motion.failed:
            motion.report_fault(fault)
        if motion is not None and motion.monitor is not None:
            try:
                motion.monitor.end()
            except BaseException:
                pass
        if preview is not None:
            preview.close()
        if errors:
            note_end(f"cleanup_error: {errors}")
            raise RuntimeError(f"native cleanup failed: {errors}")
        if (fault is None or (isinstance(fault, KeyboardInterrupt) and not fault.args)) and not (motion is not None and motion.failed):
            note_clean_end()


def main():
    mode = sys.argv.pop(1)
    teacher = "--teacher" in sys.argv
    if teacher:
        sys.argv.remove("--teacher")
        if mode != "record":
            raise SystemExit("teacher mode is a recording")
    body_only = "--body-only" in sys.argv
    if body_only:
        sys.argv.remove("--body-only")
        if mode != "teleoperate":
            raise SystemExit("body-only mode is manual teleoperation only")
    if mode not in ("record", "teleoperate"):
        raise SystemExit("expected record or teleoperate")
    from lerobot.robots.omx_follower.omx_follower import OmxFollower
    from lerobot.teleoperators.omx_leader.omx_leader import OmxLeader

    module = importlib.import_module("lerobot.scripts.lerobot_" + mode)
    run_native(module, OmxFollower, OmxLeader, body_only=body_only, teacher=teacher)
