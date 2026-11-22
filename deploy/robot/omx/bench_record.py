#!/usr/bin/env python3
"""Bench page that starts one leader recording and seals it (D-943 §3). Local only: 127.0.0.1.

A person at the bench presses Start after confirming a hand is on the follower power switch. The page
does not move anything itself; it hands the bus and cameras over and runs the existing tools:

1. stop the torque-OFF observers and camera units that hold the follower ports and V4L devices;
2. run record_session.py unchanged (caps, torque-OFF ending and session.lock stay its job) with the chosen
   arm's observer instance as --arm, so the hold lookup and the end-of-run incident report name that arm;
3. after it exits and releases session.lock, start exactly the units stopped in step 1;
4. if session.json says safe_end in record mode and the exit was 0, run record_seal.py.

The page names the arm (arm_a/arm_b; arm_s is not supported here yet). A start is refused unless the record
config's robot section passes that arm's robot profile (arm-<letter>-robot-profile.json in prep: device_id, robot.id
and config hash), the caps file carries that arm's prefix, a chosen robots/ calibration is named <robot.id>.json,
and no other OMX session (lock held, record_session/chunk_runner process) is running: the handover stops every
observer and camera unit, which would cut that session off.

  bench_record.py --config ~/.config/rosy/omx-bench-record.json [--port 8771]
config: {"python": "<LeRobot 0.4.4 python>", "prep_root": "<folder with record-config*.json, caps*.json, arm-*-robot-profile.json, tasks/>"}
UI template: bench_record.html (same directory, served at /).
"""
from __future__ import annotations

import json, math, os, signal, subprocess, sys, threading, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if not (HERE / "omx_adapter").is_dir():
    _rel = sorted((Path.home() / "rosy-omx" / "releases").glob("*/omx_adapter"), key=lambda p: p.stat().st_mtime, reverse=True)
    if _rel:
        os.environ["PYTHONPATH"] = f"{_rel[0].parent}:{os.environ['PYTHONPATH']}" if os.environ.get("PYTHONPATH") else str(_rel[0].parent)
import cell_robot_profile  # noqa: E402  (established rosy.omx-cell-robot-profile.v1 loader)
from teleop_speed import read_stage, summary as speed_summary  # noqa: E402
from bench_record_guard import (  # noqa: E402,F401  (proc_* are re-exported for tests)
    check_bimanual_child, check_proc_visible, hold_other_arm_locks, proc_cmdlines, proc_mounts, recorder_running, release, resolve_start_config, write_restore_list, write_snapshot)

from bench_record_inspect import (  # noqa: E402,F401
    ARMS, BI_ARM, HANDOVER, NAME, BenchInspectMixin, _read_task_card, active_handover_units, systemctl)
from bench_record_ops import BenchOpsMixin  # noqa: E402
from bench_live_preview import open_preview, recorder_env  # noqa: E402
from bench_record_leader import BenchLeaderMixin  # noqa: E402
from bench_record_manual import BenchManualMixin  # noqa: E402
from bench_record_link import BenchLinkMixin  # noqa: E402
from bench_record_http import PAGE, make_server  # noqa: E402,F401
from bench_record_replay import apply_task_override, transform_replay  # noqa: E402
from bench_record_pipeline import BenchPipelineMixin  # noqa: E402
from bench_record_safety import end_verdict  # noqa: E402
from bench_record_workspace import BenchWorkspaceMixin, prepare_session_task_card  # noqa: E402
from bench_record_review import BenchReviewMixin  # noqa: E402
from bench_record_recover import BenchRecoverMixin  # noqa: E402


class Bench(BenchInspectMixin, BenchOpsMixin, BenchLeaderMixin, BenchManualMixin, BenchLinkMixin, BenchPipelineMixin, BenchWorkspaceMixin, BenchReviewMixin, BenchRecoverMixin):
    def __init__(self, config, *, run=systemctl, popen=subprocess.Popen, clock=time.time, procs=proc_cmdlines,
                 mounts=proc_mounts):
        self.python, self.prep, self._config = config["python"], Path(config["prep_root"]).expanduser(), dict(config)
        self.run, self.popen, self.clock, self.procs, self.mounts = run, popen, clock, procs, mounts
        self.lock, self.child, self.abort, self.state = threading.Lock(), None, False, {"status": "idle"}
        self._auto_homes, self._pre_cancel = {}, set()  # per-session ownership: auto-home records and stop intents, keyed by the session's claim
        self.live_preview = None
        self.pending, self._retry_at = self.prep / ".bench-stopped-units.json", 0

    def _caps_ok(self, arm, cap_name):
        if arm == BI_ARM:
            return cap_name.startswith(("caps-bi-", "caps-arm-a-", "caps-arm-b-"))
        return cap_name.startswith(f"caps-arm-{ARMS[arm]}-")

    def _req_instances(self, arm):
        return (self._instance("arm_a"), self._instance("arm_b")) if arm == BI_ARM else (self._instance(arm),)

    def _arm_binding(self, arm, configs, caps, calibrations):
        try:
            reqs = set(self._req_instances(arm))
            inst = "+".join(self._req_instances(arm))
        except ValueError:
            return {"configs": [], "caps": [], "calibrations": []}
        ok_configs = []
        for name in configs:
            try:
                if self._check_robot(arm, name, (self.prep / name).read_bytes()) == inst:
                    ok_configs.append(name)
            except (OSError, ValueError):
                pass
        ok_caps = [c for c in caps if self._caps_ok(arm, c)]
        ok_cals = [c for c in calibrations if Path(c).parent.parent.name != "robots" or Path(c).stem in reqs]
        return {"configs": ok_configs, "caps": ok_caps, "calibrations": ok_cals}

    def _file(self, name, allowed):
        if name not in allowed:
            raise ValueError("choose a listed file")
        return str(self.prep / name)

    def _instance(self, arm):
        """The arm's instance from its prep robot profile; missing or broken profile = refuse (fail closed)."""
        path = self.prep / f"arm-{ARMS[arm]}-robot-profile.json"
        if not path.is_file():
            raise ValueError(f"{arm}의 로봇 프로필({path.name})이 준비 폴더에 없습니다")
        try:
            return cell_robot_profile.load(path)["binding"]["instance_id"]
        except (OSError, ValueError) as exc:
            raise ValueError(f"{arm}의 로봇 프로필({path.name})을 읽을 수 없습니다: {exc}") from None

    def _check_single_robot(self, arm, name, robot, profile=None):
        if not isinstance(robot, dict) or robot.get("type") != "omx_follower":
            raise ValueError("단일 팔(omx_follower) 설정이 아닙니다")
        try:
            binding = cell_robot_profile.load(profile or self.prep / f"arm-{ARMS[arm]}-robot-profile.json",
                                              robot_config=robot)["binding"]
        except (OSError, ValueError) as exc:
            raise ValueError(f"선택한 녹화 설정은 {arm}의 로봇 프로필과 맞지 않습니다: {exc}") from None
        if binding["device_id"] != arm:
            raise ValueError(f"{arm}의 로봇 프로필 device_id({binding['device_id']})가 팔과 다릅니다")
        return robot["id"]

    def _check_robot(self, arm, name, data, profile=None):
        try:
            cfg = json.loads(data.decode("utf-8-sig"))
            robot = cfg["robot"]
        except (ValueError, KeyError, TypeError):
            raise ValueError(f"녹화 설정 {name}의 robot을 읽을 수 없습니다") from None
        if "policy" in cfg:
            raise ValueError(f"리더-팔로워 모드 전용입니다: {name}에 policy(자동 제어) 설정이 있어 시작할 수 없습니다")
        if arm == BI_ARM:
            if not isinstance(robot, dict) or robot.get("type") != "bi_omx_follower":
                raise ValueError("arm_ab는 양팔(bi_omx_follower) 설정만 녹화합니다")
            chk = lambda a, n, r: self._check_single_robot(a, n, r, profile)  # noqa: E731
            return f"{check_bimanual_child(self.prep, 'arm_a', robot.get('arm_a'), chk)}+{check_bimanual_child(self.prep, 'arm_b', robot.get('arm_b'), chk)}"
        return self._check_single_robot(arm, name, robot, profile)

    def start(self, body):
        claimed = []  # set once align_leader returned: this request then holds the bench (homing) until it hands over
        try:
            return self._start(body, claimed)
        except BaseException:
            if claimed:
                with self.lock:
                    if self.state.get("status") == "homing":  # still the alignment claim, not handing_over or failed
                        self._idle()
            raise

    def _start(self, body, claimed):
        if not isinstance(body, dict) or any(not isinstance(body.get(k, ""), str)
                                             for k in ("name", "rig_revision", "arm", "config", "caps", "task")):
            raise ValueError("JSON object with text fields required")
        choices = self.choices()
        if not NAME.fullmatch(body.get("name", "")) or not NAME.fullmatch(body.get("rig_revision", "")):
            raise ValueError("collection name and rig revision: lowercase letters, digits and dashes")
        if body.get("arm") not in (*ARMS, BI_ARM):
            raise ValueError("팔을 선택하세요 (arm_a, arm_b, arm_s, arm_ab)")
        if body.get("link_only") is True and (body["arm"] == BI_ARM or body.get("replay")):
            raise ValueError("연동 준비(/prepare)는 단일 팔 리더 세션만 지원합니다")
        calibrations = body.get("calibrations")
        if not isinstance(calibrations, list) or not calibrations or any(not isinstance(c, str) or c not in choices["calibrations"] for c in calibrations):
            raise ValueError("choose the calibration files used by these arms")
        req_instances = self._req_instances(body["arm"])
        instance = "+".join(req_instances)
        config = self._file(body.get("config"), choices["configs"])
        caps = self._file(body.get("caps"), choices["caps"])
        try:
            config_bytes, caps_bytes = Path(config).read_bytes(), Path(caps).read_bytes()
        except OSError as exc:
            raise ValueError(f"녹화 설정 또는 caps를 읽을 수 없습니다: {exc}") from None
        if self._check_robot(body["arm"], body["config"], config_bytes) != instance:
            raise ValueError(f"선택한 녹화 설정은 {body['arm']}({instance})의 것이 아닙니다")
        if not self._caps_ok(body["arm"], body.get("caps", "")):
            raise ValueError(f"caps 파일은 {body['arm']}에 맞는 파일을 선택하세요")
        cfg_data, cam_rebinds = resolve_start_config(config_bytes, body["arm"])
        stems = [Path(c).stem for c in calibrations]
        robots = [stem for c, stem in zip(calibrations, stems) if Path(c).parent.parent.name == "robots"]
        if not set(req_instances).issubset(set(robots)) or any(stem not in req_instances for stem in robots):
            raise ValueError(f"{', '.join(req_instances)} 보정 파일을 선택하세요 (다른 팔의 보정은 선택할 수 없습니다)")
        self._check_manual()
        for held_arm in (("arm_a", "arm_b") if body["arm"] == BI_ARM else (body["arm"],)):
            self._check_lease(held_arm)  # before the Leader alignment child or any torque write: record_session would refuse it too late
        if self.pending.exists():
            raise ValueError("이전 녹화에서 멈춘 유닛이 아직 복원되지 않았습니다. 먼저 복원하세요 (작업대 서비스 재시작 또는 상태 확인)")
        replay_raw = body.get("replay")
        if replay_raw is not None and not isinstance(replay_raw, str):
            raise ValueError("replay는 문자열 경로여야 합니다")
        replay_path = None
        if replay_raw:
            if body["arm"] == BI_ARM:
                raise ValueError("replay(--teacher)는 단일 팔(arm_a, arm_b, arm_s)만 지원합니다")
            replay_path = self._file(replay_raw, choices.get("replays", []))
        task = self._file(body["task"], choices["tasks"]) if body.get("task") else None
        task_card = None
        if task:
            task_card = _read_task_card(Path(task))
            if not task_card.get("valid"):
                raise ValueError(f"과제 카드를 사용할 수 없습니다: {task_card.get('error', '형식 오류')}")
        lp = body.get("lerobot_params")
        overrides = {}
        if lp is not None:
            if not isinstance(lp, dict):
                raise ValueError("lerobot_params는 JSON 객체여야 합니다")
            locked = set(lp.keys()) & {"robot", "max_relative_target", "use_degrees", "fps", "cameras", "teleop"}
            if locked:
                raise ValueError(f"안전 잠금(cell_robot_profile/D-911) 파라미터는 변경할 수 없습니다: {', '.join(sorted(locked))}")
            for key, lo, hi, bounds in (("episode_time_s", 1.0, 3600.0, "1~3600초"), ("reset_time_s", 0.5, 600.0, "0.5~600초")):
                if key in lp and lp[key] is not None:
                    raw_v = lp[key]
                    if isinstance(raw_v, bool):
                        raise ValueError(f"{key}는 {bounds}여야 합니다")
                    try:
                        v = float(raw_v)
                    except (TypeError, ValueError):
                        raise ValueError(f"{key}는 {bounds}여야 합니다") from None
                    if not math.isfinite(v) or not (lo <= v <= hi):
                        raise ValueError(f"{key}는 {bounds}여야 합니다")
                    overrides[key] = v
            if "num_episodes" in lp and lp["num_episodes"] is not None:
                v = lp["num_episodes"]
                if isinstance(v, bool) or not isinstance(v, int) or not (1 <= v <= 500):
                    raise ValueError("num_episodes는 1~500 정수여야 합니다")
                overrides["num_episodes"] = v
        if body.get("link_only") is True:
            overrides["num_episodes"] = 500  # a linked session ends at finish, not by count
        replay_mode = body.get("replay_mode") or "none"
        invert_gripper = bool(body.get("invert_gripper", False))
        task_override = body.get("task_override")
        if task_override is not None:
            if not isinstance(task_override, dict):
                raise ValueError("task_override는 JSON 객체여야 합니다")
            if task_override and not task and task_override.get("custom") is not True:
                raise ValueError("집기/놓기 스왑 또는 목표 변경은 작업 카드 선택이 필요합니다")
        homed = self._pre_start_home(body, replay_path)
        if body.get("align_leader") is True:
            if replay_path:
                raise ValueError("리더 정렬(align_leader)은 replay 없는 텔레옵에서만 쓸 수 있습니다")
            snap0 = self.prep / ".bench-runs" / f"align-{time.time_ns()}-{body['name']}"  # the bytes validated above
            write_snapshot(snap0, (("record-config.json", config_bytes),))
            self.align_leader(body, str(snap0 / "record-config.json"), keep=True)
            claimed.append(True)
        elif body.get("align_leader") not in (None, False):
            raise ValueError("align_leader는 true 또는 false여야 합니다")
        with self.lock:
            if not claimed and self.state["status"] in ("handing_over", "homing", "recording", "restoring", "sealing", "leader_manual_check"):
                raise ValueError("a bench session is already running or the Leader needs a manual check")
            if (claimed or homed) and self.abort:  # a /stop since home or the alignment began
                raise ValueError("정지 요청이 있어 녹화를 시작하지 않습니다")
            handles, busy = hold_other_arm_locks(body["arm"], ARMS, self.procs, self.mounts)
            if busy:
                if "session-" in busy and f"session-{body['arm']}.lock" not in busy:
                    raise ValueError(f"{busy} — 공용 카메라·옵저버 인계 중 다른 팔 세션을 보호하기 위해 대기해야 합니다")
                raise ValueError(busy)
            try:
                stamp = f"{time.strftime('%Y%m%d-%H%M%S')}-{body['name']}"
                snap = self.prep / ".bench-runs" / stamp  # record_session runs from copies of the bytes validated above
                effective_cfg = config_bytes
                effective_task = task
                snap_files = [("caps.json", caps_bytes)]
                eff_task_id, eff_root_prefix, eff_target_eps, effective_task, tc_snap = prepare_session_task_card(
                    effective_task, task_card, task_override, body["arm"], cfg_data, overrides, snap)
                if tc_snap is not None:
                    snap_files.append(tc_snap)
                if overrides or cam_rebinds:
                    if overrides:
                        cfg_data.setdefault("dataset", {}).update(overrides)
                    effective_cfg = json.dumps(cfg_data, indent=2).encode("utf-8")
                snap_files.insert(0, ("record-config.json", effective_cfg))
                if replay_path:
                    eff_target_eps = 2
                    raw_replay = Path(replay_path).read_bytes()
                    snap_files.append(("replay.json", transform_replay(raw_replay, mode=replay_mode, invert_gripper=invert_gripper)))
                write_snapshot(snap, tuple(snap_files))
                command = [self.python, str(HERE / "record_session.py"), "--config", str(snap / "record-config.json"),
                           "--caps", str(snap / "caps.json")]
                if body["arm"] != BI_ARM:
                    command += ["--arm", body["arm"]]
                if effective_task:
                    command += ["--task-card", effective_task]
                if replay_path:
                    command += ["--replay", str(snap / "replay.json")]
                stage = None if replay_path or body["arm"] == BI_ARM else read_stage(self.prep / f"teleop-speed-{body['arm']}.json")
                command += ["--teleop-stage", str(stage)] if stage else []  # W14: the declared speed stage of a full-arm Leader session
                folder = self.prep / "sessions" / stamp
                folder.mkdir(parents=True)
            except BaseException:
                release(handles)
                raise
            self.state = {"status": "handing_over", "name": body["name"], "arm": body["arm"], "folder": str(folder), "started": self.clock(),
                          "config": body["config"], "caps": body["caps"], "snapshot": str(snap),
                          "target_episodes": eff_target_eps, "task_id": eff_task_id,
                          "dataset_root_prefix": eff_root_prefix, "replay_mode": replay_mode, "teleop_speed": speed_summary(stage),
                          "link": body.get("link_only") is True}
            self.child, self.abort = None, False
            self.state["claim"] = self._claim_bench()  # the session's own claim: its stop intent and its auto-home record are keyed by it
        self._log_event("session", "info", f"{body['arm']} 세션 시작: {body['name']} ({eff_task_id or '자유'})")
        seal = [self.python, str(HERE / "record_seal.py"), "--session-dir", str(folder), "--name", body["name"],
                "--rig-revision", body["rig_revision"], *[a for c in calibrations for a in ("--calibration", c)]]
        try:
            threading.Thread(target=self._session, args=(command, seal, folder, handles, cfg_data["robot"]),
                             daemon=True).start()
        except BaseException as exc:
            release(handles)
            self._set(status="failed", error=f"{type(exc).__name__}: {exc}")
            raise
        return self.status()

    def _set(self, **values):
        with self.lock:
            self.state.update(values)

    def _session(self, command, seal, folder, handles=(), robot=None):
        stopped, code = [], None
        preview = open_preview(folder, robot) if robot is not None else None
        try:
            for unit in active_handover_units(self.run):
                stopped.append(unit)  # before the call: a timed-out stop still gets restored
                self._remember(stopped)
                self.run("stop", unit)
            with self.lock:
                if self.abort:
                    raise RuntimeError("stopped before recording started")
                self.state.update(status="recording", stopped=stopped, recording_started=self.clock())
                self.live_preview = preview
                if "--arm" not in command:
                    for h in list(handles):
                        if getattr(h, "name", "").endswith("session.lock"):
                            try:
                                h.close()
                            except OSError:
                                pass
                with (folder / "bench.log").open("ab") as log:
                    self.child = self.popen(command, cwd=folder, stdout=log, stderr=subprocess.STDOUT,
                                            start_new_session=True, env=recorder_env(preview, folder / "link" if self.state.get("link") else None))
            code = self.child.wait()
        except Exception as exc:
            self._set(error=f"{type(exc).__name__}: {exc}")
        finally:
            release(handles)  # recording is over; observer@ ExecStartPre needs that arm's lock free to restart
            self._set(status="restoring", recording_ended=self.clock())
            if preview is not None:
                self.live_preview = None
                preview.close()
            errors, detail = self._start_units(reversed(stopped))
            try:
                self._remember(errors)
            except Exception as exc:
                detail = detail or f"복원 목록 기록 실패: {type(exc).__name__}: {exc}"
            self._set(restored=[u for u in stopped if u not in errors], restore_errors=errors,
                      **({"error": f"복원 실패: {detail}"} if errors or detail else {}))
        try:
            session = folder / "session.json"
            record = json.loads(session.read_text()) if session.is_file() else {}
            self._set(exit_code=code, safe_end=record.get("safe_end"),
                      manual_attention=record.get("manual_attention_required"))
            if record.get("interrupted"):  # record_seal refuses interrupted sessions; keep the raw recording
                return self._set(status="stopped_not_sealed")
            if not (code == 0 and record.get("safe_end") is True):
                if code is None:
                    return self._set(status="failed")
                # unsafe_or_failed unless session.json proves the safe end (bench_record_safety); the status that was published decides the auto home
                if self._publish_end(verdict=end_verdict) == "stopped_safe":
                    self._auto_home_after_session()
                return
            self._set(status="sealing")
            with (folder / "bench.log").open("ab") as log:
                sealed = self.popen(seal, cwd=folder, stdout=log, stderr=subprocess.STDOUT).wait()
            self._publish_end(status="sealed" if sealed == 0 else "seal_failed", seal_exit=sealed)
            self._log_event("session", "good" if sealed == 0 else "crit", f"세션 종료: {'sealed' if sealed == 0 else 'seal_failed'} ({folder.name})")
            if sealed == 0:
                self._auto_home_after_session()
                self._on_session_sealed(folder)
        except Exception as exc:
            self._set(status="failed", error=f"{type(exc).__name__}: {exc}")


def main(argv=None):
    from bench_record_http import main as _http_main
    return _http_main(argv, bench_cls=Bench)


if __name__ == "__main__":
    raise SystemExit(main())
