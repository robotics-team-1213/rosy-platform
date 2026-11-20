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

import argparse, json, math, os, re, signal, socket, subprocess, sys, threading, time, urllib.request
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import cell_robot_profile  # noqa: E402  (established rosy.omx-cell-robot-profile.v1 loader)
from bench_record_guard import (  # noqa: E402,F401  (proc_* are re-exported for tests)
    check_proc_visible, hold_other_arm_locks, proc_cmdlines, proc_mounts, recorder_running, release, write_restore_list, write_snapshot)

from bench_record_inspect import (  # noqa: E402,F401
    ARMS, BI_ARM, HANDOVER, NAME, BenchInspectMixin, _read_task_card, active_handover_units, systemctl)
from bench_record_ops import BenchOpsMixin  # noqa: E402
from bench_record_http import PAGE, make_server  # noqa: E402,F401


class Bench(BenchInspectMixin, BenchOpsMixin):
    def __init__(self, config, *, run=systemctl, popen=subprocess.Popen, clock=time.time, procs=proc_cmdlines,
                 mounts=proc_mounts):
        self.python, self.prep = config["python"], Path(config["prep_root"]).expanduser()
        self.run, self.popen, self.clock, self.procs, self.mounts = run, popen, clock, procs, mounts
        self.lock, self.child, self.abort, self.state = threading.Lock(), None, False, {"status": "idle"}
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

    def _check_single_robot(self, arm, name, robot):
        if not isinstance(robot, dict) or robot.get("type") != "omx_follower":
            raise ValueError("단일 팔(omx_follower) 설정이 아닙니다")
        try:
            binding = cell_robot_profile.load(self.prep / f"arm-{ARMS[arm]}-robot-profile.json",
                                              robot_config=robot)["binding"]
        except (OSError, ValueError) as exc:
            raise ValueError(f"선택한 녹화 설정은 {arm}의 로봇 프로필과 맞지 않습니다: {exc}") from None
        if binding["device_id"] != arm:
            raise ValueError(f"{arm}의 로봇 프로필 device_id({binding['device_id']})가 팔과 다릅니다")
        return robot["id"]

    def _check_robot(self, arm, name, data):
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
            return f"{self._check_single_robot('arm_a', name, robot.get('arm_a'))}+{self._check_single_robot('arm_b', name, robot.get('arm_b'))}"
        return self._check_single_robot(arm, name, robot)

    def start(self, body):
        if not isinstance(body, dict) or any(not isinstance(body.get(k, ""), str)
                                             for k in ("name", "rig_revision", "arm", "config", "caps", "task")):
            raise ValueError("JSON object with text fields required")
        if body.get("at_bench") is not True:
            raise ValueError("confirm that a person is at the bench with a hand on the follower power switch")
        choices = self.choices()
        if not NAME.fullmatch(body.get("name", "")) or not NAME.fullmatch(body.get("rig_revision", "")):
            raise ValueError("collection name and rig revision: lowercase letters, digits and dashes")
        if body.get("arm") not in (*ARMS, BI_ARM):
            raise ValueError("팔을 선택하세요 (arm_a, arm_b, arm_s, arm_ab)")
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
        stems = [Path(c).stem for c in calibrations]
        robots = [stem for c, stem in zip(calibrations, stems) if Path(c).parent.parent.name == "robots"]
        if not set(req_instances).issubset(set(robots)) or any(stem not in req_instances for stem in robots):
            raise ValueError(f"{', '.join(req_instances)} 보정 파일을 선택하세요 (다른 팔의 보정은 선택할 수 없습니다)")
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
            if "episode_time_s" in lp and lp["episode_time_s"] is not None:
                raw_v = lp["episode_time_s"]
                if isinstance(raw_v, bool):
                    raise ValueError("episode_time_s는 1~3600초여야 합니다")
                try:
                    v = float(raw_v)
                except (TypeError, ValueError):
                    raise ValueError("episode_time_s는 1~3600초여야 합니다") from None
                if not math.isfinite(v) or not (1.0 <= v <= 3600.0):
                    raise ValueError("episode_time_s는 1~3600초여야 합니다")
                overrides["episode_time_s"] = v
            if "reset_time_s" in lp and lp["reset_time_s"] is not None:
                raw_v = lp["reset_time_s"]
                if isinstance(raw_v, bool):
                    raise ValueError("reset_time_s는 0.5~600초여야 합니다")
                try:
                    v = float(raw_v)
                except (TypeError, ValueError):
                    raise ValueError("reset_time_s는 0.5~600초여야 합니다") from None
                if not math.isfinite(v) or not (0.5 <= v <= 600.0):
                    raise ValueError("reset_time_s는 0.5~600초여야 합니다")
                overrides["reset_time_s"] = v
            if "num_episodes" in lp and lp["num_episodes"] is not None:
                v = lp["num_episodes"]
                if isinstance(v, bool) or not isinstance(v, int) or not (1 <= v <= 500):
                    raise ValueError("num_episodes는 1~500 정수여야 합니다")
                overrides["num_episodes"] = v
        with self.lock:
            if self.state["status"] in ("handing_over", "recording", "restoring", "sealing"):
                raise ValueError("a bench session is already running")
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
                if overrides:
                    if effective_task:
                        import yaml
                        tc_data = yaml.safe_load(Path(effective_task).read_text(encoding="utf-8"))
                        tc_data.setdefault("record", {}).update(overrides)
                        snap_files.append(("effective-task-card.yaml", json.dumps(tc_data, indent=2, ensure_ascii=False).encode("utf-8")))
                        effective_task = str(snap / "effective-task-card.yaml")
                    else:
                        cfg_data = json.loads(config_bytes.decode("utf-8-sig"))
                        cfg_data.setdefault("dataset", {}).update(overrides)
                        effective_cfg = json.dumps(cfg_data, indent=2).encode("utf-8")
                snap_files.insert(0, ("record-config.json", effective_cfg))
                if replay_path:
                    snap_files.append(("replay.json", Path(replay_path).read_bytes()))
                write_snapshot(snap, tuple(snap_files))
                command = [self.python, str(HERE / "record_session.py"), "--config", str(snap / "record-config.json"),
                           "--caps", str(snap / "caps.json")]
                if body["arm"] != BI_ARM:
                    command += ["--arm", body["arm"]]
                if effective_task:
                    command += ["--task-card", effective_task]
                if replay_path:
                    command += ["--replay", str(snap / "replay.json")]
                folder = self.prep / "sessions" / stamp
                folder.mkdir(parents=True)
            except BaseException:
                release(handles)
                raise
            self.state = {"status": "handing_over", "name": body["name"], "folder": str(folder), "started": self.clock(),
                          "config": body["config"], "caps": body["caps"], "snapshot": str(snap)}
            self.child, self.abort = None, False
        seal = [self.python, str(HERE / "record_seal.py"), "--session-dir", str(folder), "--name", body["name"],
                "--rig-revision", body["rig_revision"], *[a for c in calibrations for a in ("--calibration", c)]]
        try:
            threading.Thread(target=self._session, args=(command, seal, folder, handles), daemon=True).start()
        except BaseException as exc:
            release(handles)
            self._set(status="failed", error=f"{type(exc).__name__}: {exc}")
            raise
        return self.status()

    def _set(self, **values):
        with self.lock:
            self.state.update(values)

    def _remember(self, stopped):
        # A bench restart mid-session must still restore what it stopped (see restore_leftovers).
        write_restore_list(self.pending, stopped)

    def _start_units(self, units):
        """Start units in the given order; returns (failed units, first error text)."""
        failed, detail = [], ""
        for unit in units:
            try:
                done = self.run("start", unit)
                if done.returncode != 0:
                    failed.append(unit)
                    detail = detail or f"{unit}: {(done.stderr or '').strip() or 'exit ' + str(done.returncode)}"
            except Exception as exc:
                failed.append(unit)
                detail = detail or f"{unit}: {type(exc).__name__}: {exc}"
        return failed, detail

    def restore_leftovers(self):
        if self.pending.is_file():
            try:
                check_proc_visible(self.mounts)
            except Exception as exc:  # hidepid or unreadable mounts: a recorder could be invisible, so no restore
                return self._set(error=f"복원 보류: {exc}")
            if recorder_running(self.procs):  # a live recorder owns the bus; retried on the next status poll or restart
                return self._set(error="복원 보류: record_session 또는 chunk_runner가 실행 중이거나 확인할 수 없습니다")
            failed, detail = self._start_units(reversed(json.loads(self.pending.read_text())))
            self._remember(failed)  # failed units stay listed for the next recovery
            self._set(restore_errors=failed, **({"error": f"복원 실패: {detail}"} if failed else {}))

    def _session(self, command, seal, folder, handles=()):
        stopped, code = [], None
        try:
            for unit in active_handover_units(self.run):
                stopped.append(unit)  # before the call: a timed-out stop still gets restored
                self._remember(stopped)
                self.run("stop", unit)
            with self.lock:
                if self.abort:
                    raise RuntimeError("stopped before recording started")
                self.state.update(status="recording", stopped=stopped)
                if "--arm" not in command:
                    for h in list(handles):
                        if getattr(h, "name", "").endswith("session.lock"):
                            try:
                                h.close()
                            except OSError:
                                pass
                with (folder / "bench.log").open("ab") as log:
                    self.child = self.popen(command, cwd=folder, stdout=log, stderr=subprocess.STDOUT,
                                            start_new_session=True)
            code = self.child.wait()
        except Exception as exc:
            self._set(error=f"{type(exc).__name__}: {exc}")
        finally:
            release(handles)  # recording is over; observer@ ExecStartPre needs that arm's lock free to restart
            self._set(status="restoring")
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
                return self._set(status="unsafe_or_failed" if code is not None else "failed")
            self._set(status="sealing")
            with (folder / "bench.log").open("ab") as log:
                sealed = self.popen(seal, cwd=folder, stdout=log, stderr=subprocess.STDOUT).wait()
            self._set(status="sealed" if sealed == 0 else "seal_failed", seal_exit=sealed)
        except Exception as exc:
            self._set(status="failed", error=f"{type(exc).__name__}: {exc}")

    def stop(self):
        with self.lock:
            if self.state["status"] == "handing_over":
                self.abort = True
                return dict(self.state)
            child = self.child
            if child is None or child.poll() is not None:
                raise ValueError("no recording is running")
        # SIGTERM: record_session maps it to the same clean ending, and it is not ignored under nohup.
        child.send_signal(signal.SIGTERM)
        return self.status()



def main(argv=None):
    from bench_record_http import main as _http_main
    return _http_main(argv, bench_cls=Bench)


if __name__ == "__main__":
    raise SystemExit(main())
