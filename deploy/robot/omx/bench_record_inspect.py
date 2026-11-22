#!/usr/bin/env python3
"""Inspection, status, lock-holder, and task-card helpers for bench_record.py."""
from __future__ import annotations

import argparse, json, math, os, re, signal, socket, subprocess, sys, threading, time, urllib.request
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import cell_robot_profile  # noqa: E402  (established rosy.omx-cell-robot-profile.v1 loader)
from bench_record_guard import (  # noqa: E402,F401  (proc_* are re-exported for tests)
    HANDOVER, active_handover_units, arm_connectivity, check_proc_visible, hold_other_arm_locks, inspect_config_cameras, load_registry, proc_cmdlines, proc_mounts, recorder_running, release, systemctl, write_restore_list, write_snapshot)
from bench_record_replay import recording_progress  # noqa: E402
from bench_record_step import starting_step  # noqa: E402
from bench_record_safety import end_verdict  # noqa: E402

# Observer instance per arm (units rosy-omx-observer@<arm>.service, the --arm record_session takes) and the
# letter the prep folder binds files with (caps-arm-<letter>-*, arm-<letter>-robot-profile.json).
ARMS = {"arm_a": "a", "arm_b": "b", "arm_s": "s"}
BI_ARM = "arm_ab"
NAME = re.compile(r"[a-z0-9][a-z0-9-]{2,63}")


def _read_task_card(path):
    try:
        import yaml
        yaml_err = (yaml.YAMLError,)
    except ImportError:
        yaml_err = ()
    try:
        from record_session_helpers import load_task_card
        data = load_task_card(path)
    except (SystemExit, OSError, ValueError, TypeError, *yaml_err) as exc:
        return {"valid": False, "error": str(exc)}
    rec, layout = data["record"], data.get("layout") if isinstance(data.get("layout"), dict) else {}
    shot = data.get("shot") if isinstance(data.get("shot"), dict) else {}
    card = {"valid": True, "task_id": data["task_id"], "revision": data["revision"],
            "single_task": data["single_task"], "episode_time_s": rec["episode_time_s"],
            "reset_time_s": rec["reset_time_s"], "num_episodes": rec["num_episodes"],
            "raw": path.read_text(encoding="utf-8-sig")}
    fallbacks = {"origin": shot.get("source"), "target_slot": shot.get("target"), "shot_arm": shot.get("arm")}
    for key in ("origin", "target_slot", "target_layer", "shot_arm", "home_pose"):
        val = layout.get(key) if layout.get(key) not in (None, "") else (data.get(key) if data.get(key) not in (None, "") else fallbacks.get(key))
        if val not in (None, ""):
            card[key] = val if (isinstance(val, (str, int)) and not isinstance(val, bool)) or (isinstance(val, float) and math.isfinite(val)) else str(val)
    if isinstance(data.get("cameras_lighting"), dict):
        card["cameras_note"] = " / ".join(f"{k}: {v}" for k, v in data["cameras_lighting"].items() if isinstance(v, str))
    return card


class BenchInspectMixin:
    def recent_sessions(self, limit=6):
        root = self.prep / "sessions"
        if not root.is_dir():
            return []
        rows = []
        for d in sorted((p for p in root.iterdir() if p.is_dir()), reverse=True)[:limit]:
            sess_f = d / "session.json"
            sess = {}
            if sess_f.is_file():
                try:
                    sess = json.loads(sess_f.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    pass
            sealed = (d / "seal.json").is_file() or (d / "manifest.json").is_file() or any(d.glob("*.seal.json"))
            hf = (d / "hub-receipt.json").is_file() or (d / "hf-upload.json").is_file()
            rows.append({"folder": d.name, "safe_end": sess.get("safe_end"), "interrupted": sess.get("interrupted"),
                         "sealed": sealed, "hf_uploaded": hf})
        return rows

    def lerobot_datasets(self, limit=8):
        ds_root = Path.home() / "rosy-data" / "omx-leader"
        if not ds_root.is_dir():
            return []
        rows = []
        dirs = [p for p in ds_root.iterdir() if p.is_dir() and not p.name.startswith(".")]
        for d in sorted(dirs, key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
            parquets = len(list(d.glob("data/**/*.parquet")))
            videos = len(list(d.glob("videos/**/*.mp4")))
            ep_cnt = parquets
            info_p = d / "meta" / "info.json"
            if parquets > 0 and info_p.is_file():
                try:
                    te = json.loads(info_p.read_text(encoding="utf-8")).get("total_episodes")
                    if type(te) is int and te > 0:
                        ep_cnt = te
                except (OSError, ValueError):
                    pass
            size_bytes = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
            rc_p = self.prep / ".hf-receipts" / f"{d.name}.json"
            rev = self.dataset_review_summary(d.name) if hasattr(self, "dataset_review_summary") else {}
            item = {"name": d.name, "episodes": ep_cnt, "videos": videos, "size_bytes": size_bytes,
                    "empty": ep_cnt == 0, "do_not_train": (d / "DO_NOT_TRAIN.txt").is_file(), "review_summary": rev}
            if rc_p.is_file():
                rc = json.loads(rc_p.read_text(encoding="utf-8"))
                item.update(hf_uploaded=bool(rc.get("repo_id")), hf_repo_id=rc.get("repo_id", ""), hf_repo_url=rc.get("url", ""))
            rows.append(item)
        return rows

    def scenario_counts(self):
        ds_root = Path.home() / "rosy-data" / "omx-leader"
        if not ds_root.is_dir():
            return {}
        counts = {}
        for d in ds_root.iterdir():
            if not d.is_dir() or d.name.startswith(".") or (d / "DO_NOT_TRAIN.txt").is_file():
                continue
            m = re.match(r"^(.+?)-r\d+-\d{8}-\d{6}$", d.name)
            tid = m.group(1) if m else d.name
            ep = len(list(d.glob("data/**/*.parquet")))
            if ep > 0 and (d / "meta" / "info.json").is_file():
                try:
                    te = json.loads((d / "meta" / "info.json").read_text(encoding="utf-8")).get("total_episodes")
                    if type(te) is int and te > 0:
                        ep = te
                except (OSError, ValueError):
                    pass
            vid = len(list(d.glob("videos/**/*.mp4")))
            cur = counts.setdefault(tid, {"episodes": 0, "videos": 0, "datasets": 0})
            cur["episodes"] += ep
            cur["videos"] += vid
            cur["datasets"] += 1
        return counts

    def hf_logged_in(self):
        hf_dir = Path.home() / ".cache" / "huggingface"
        return (hf_dir / "token").is_file() or (hf_dir / "stored_tokens").is_file()

    def active_lock_holders(self):
        with self.lock:
            if self.state.get("status") in ("handing_over", "homing", "recording", "restoring", "sealing"):
                return []
        try:
            import fcntl
            import joint_tune_lock
            root = joint_tune_lock.lock_root()
            if not root.is_dir():
                return []
            locked_paths = {}
            for p in sorted(root.glob("session*.lock")):
                try:
                    mode = fcntl.LOCK_SH if p.name == "session.lock" else fcntl.LOCK_EX
                    with p.open("a") as fh:
                        try:
                            fcntl.flock(fh, mode | fcntl.LOCK_NB)
                        except BlockingIOError:
                            locked_paths[str(p.resolve())] = p.name
                except OSError:
                    continue
            if not locked_paths:
                return []
            holders = []
            seen = set()
            for proc in Path("/proc").iterdir():
                if not proc.name.isdigit() or proc.name == str(os.getpid()):
                    continue
                fd_dir = proc / "fd"
                try:
                    fds = list(fd_dir.iterdir())
                except OSError:
                    continue
                matched = []
                for fd in fds:
                    try:
                        tgt = str(Path(os.readlink(fd)).resolve())
                    except OSError:
                        continue
                    if tgt in locked_paths:
                        matched.append(locked_paths[tgt])
                if matched:
                    pid = int(proc.name)
                    try:
                        cmd = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()
                    except OSError:
                        cmd = ""
                    for lname in sorted(set(matched)):
                        if (pid, lname) not in seen:
                            seen.add((pid, lname))
                            holders.append({"lock": lname, "pid": pid, "cmd": cmd})
            for lname in sorted(set(locked_paths.values())):
                if not any(h["lock"] == lname for h in holders):
                    holders.append({"lock": lname, "pid": None, "cmd": ""})
            return holders
        except Exception:
            return []

    def release_lock(self, body):
        target_pid = body.get("pid")
        if not isinstance(target_pid, int) or isinstance(target_pid, bool) or target_pid <= 1:
            raise ValueError("종료할 대상 PID를 명시해야 합니다 (다른 팔 보호)")
        with self.lock:
            if self.state.get("status") in ("handing_over", "homing", "recording", "restoring", "sealing"):
                raise ValueError("작업대 세션이 진행 중일 때는 외부 락 해제를 실행할 수 없습니다")
        holders = [h for h in self.active_lock_holders() if h.get("pid") == target_pid]
        if not holders:
            return self.status()
        cmd = holders[0].get("cmd") or ""
        if not re.search(r"(?:^|[/\s])(record_session|chunk_runner)\.py(?:\s|$)", cmd):
            raise ValueError(f"안전 제한: OMX 레코더(record_session/chunk_runner)가 아닌 PID {target_pid}는 종료할 수 없습니다")
        try:
            os.kill(target_pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        deadline = self.clock() + 2.5
        while self.clock() < deadline:
            if not any(h.get("pid") == target_pid for h in self.active_lock_holders()):
                break
            time.sleep(0.2)
        return self.status()

    def arms_status(self):
        ch = self.choices()
        st = self.status()
        locks = st.get("active_locks", [])
        out = {}
        for a in (*ARMS, BI_ARM):
            sub = ("arm_a", "arm_b") if a == BI_ARM else (a,)
            lock_names = {f"session-{x}.lock" for x in (*sub, a)}
            out[a] = {
                "instance_id": ch.get("instances", {}).get(a),
                "bindings": ch.get("arm_bindings", {}).get(a),
                "has_initial_pose": all((self.prep / f"initial-pose-{x}.json").is_file() for x in sub),
                "has_leader_pose": all((self.prep / f"leader-home-{x}.json").is_file() for x in sub),
                "locked_by": [h for h in locks if h.get("lock") in lock_names], **arm_connectivity(self.prep, a),
            }
        return {"status": st.get("status"), "arms": out}

    def telemetry(self):
        with self.lock:
            state_snap = dict(self.state)
        cand = None
        if state_snap.get("status") == "recording" and state_snap.get("folder"):
            p = Path(state_snap["folder"]) / "motor-health-current.json"
            if p.is_file():
                cand = p
        if cand is None:
            live_p = self.prep / "telemetry-live.json"
            if live_p.is_file() and (self.clock() - live_p.stat().st_mtime) <= 10.0:
                cand = live_p
        if cand is None:
            out = {"active": False, "status": state_snap.get("status"), **recording_progress(state_snap, self.clock)}
            return out
        try:
            data = json.loads(cand.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"active": False, "status": state_snap.get("status"), **recording_progress(state_snap, self.clock)}
        if isinstance(data, dict):
            data.setdefault("active", True)
            data.update(recording_progress(state_snap, self.clock))
        return data

    def check_camera_drift(self, arm=""):
        arm_key = arm if arm in (*ARMS, BI_ARM) else "default"
        try:
            raw = json.loads(urllib.request.urlopen("http://127.0.0.1:8767/state.json", timeout=1.5).read())
        except Exception:
            return {"ok": False, "cameras": {}}
        bdir = self.prep / "camera-baselines" / arm_key
        bfile = bdir / "baseline.json"
        try:
            base = json.loads(bfile.read_text(encoding="utf-8")) if bfile.is_file() else {}
        except (OSError, ValueError):
            base = {}
        base_cams = base.get("cameras") if isinstance(base.get("cameras"), dict) else {}
        out = {}
        for lbl, info in raw.items():
            if not re.fullmatch(r"[a-zA-Z0-9_-]+", str(lbl)) or not isinstance(info, dict) or "quality" not in info:
                continue
            q = info.get("quality") or {}
            if info.get("fresh") is False:
                out[lbl] = {"status": "stale"}
            elif q.get("condition") != "NORMAL" or q.get("usable") is not True:
                out[lbl] = {"status": "unusable_lighting", "condition": q.get("condition")}
            elif lbl not in base_cams:
                out[lbl] = {"status": "no_baseline"}
            else:
                bq = base_cams[lbl].get("quality") or {}
                try:
                    dm = round(abs(float(q.get("mean_intensity", 0)) - float(bq.get("mean_intensity", 0))), 1)
                    dc = round(abs(float(q.get("spatial_contrast", 0)) - float(bq.get("spatial_contrast", 0))), 1)
                except (TypeError, ValueError):
                    out[lbl] = {"status": "no_baseline"}
                    continue
                if dm > 25.0 or dc > 20.0:
                    out[lbl] = {"status": "lighting_mismatch", "delta_mean": dm, "delta_contrast": dc}
                else:
                    out[lbl] = {"status": "ok", "delta_mean": dm}
        return {"ok": True, "arm": arm_key, "cameras": out}

    def status(self):
        with self.lock:
            cur_status = self.state["status"]
        if cur_status == "idle" and self.pending.exists() and self.clock() >= self._retry_at:
            self._retry_at = self.clock() + 10  # a skipped or failed startup recovery is retried, not every poll
            self.restore_leftovers()
        with self.lock:
            if self.state.get("status") == "unsafe_or_failed" and self.state.get("exit_code") is not None:
                self.state.update(end_verdict(self.state))  # re-judged on every poll: an older verdict resolves without a restart
            out = dict(self.state)
        out["recent_sessions"] = self.recent_sessions()
        out["lerobot_datasets"] = self.lerobot_datasets()
        out["scenario_counts"] = self.scenario_counts()
        out["hf_logged_in"] = self.hf_logged_in()
        out["active_locks"] = self.active_lock_holders()
        out["hf_upload"] = self.hf_upload_status() if hasattr(self, "hf_upload_status") else {}
        out.update(recording_progress(out, self.clock))
        out.update(starting_step(out, self.__dict__.setdefault("_step_memory", {})))
        out.update(self.issue_fields(out), **self.speed_fields(), **self.link_fields(out))
        mh = self.manual_hold_info() if hasattr(self, "manual_hold_info") else None
        out["manual_hold"] = mh if (mh and mh.get("active")) else None
        if out.get("folder") and out.get("status") in ("unsafe_or_failed", "failed", "seal_failed"):
            log_p = Path(out["folder"]) / "bench.log"
            try:
                if log_p.is_file():
                    out["log_tail"] = "\n".join(log_p.read_text(encoding="utf-8", errors="replace").splitlines()[-12:])
            except OSError:
                pass
        return out

    def choices(self):
        pick = lambda pattern: sorted(p.name for p in self.prep.glob(pattern))
        instances = {}  # arm -> its robot profile's instance_id (start refuses when this is missing)
        for arm, letter in ARMS.items():
            path = self.prep / f"arm-{letter}-robot-profile.json"
            if path.is_file():
                try:
                    instances[arm] = cell_robot_profile.load(path)["binding"]["instance_id"]
                except (OSError, ValueError):
                    pass
        if "arm_a" in instances and "arm_b" in instances:
            instances[BI_ARM] = f"{instances['arm_a']}+{instances['arm_b']}"
        inv_inst = {v: k for k, v in instances.items()}
        try:
            reg, reg_err = load_registry(), None
        except ValueError as exc:
            reg, reg_err = None, str(exc)
        configs = pick("record-config*.json")
        robots = {}  # config file -> its robot.id, so the page can mark which files belong to the chosen arm
        config_meta = {}
        for name in configs:
            try:
                cfg_j = json.loads((self.prep / name).read_text(encoding="utf-8-sig"))
                r = cfg_j["robot"]
                robots[name] = r["id"]
                ds = cfg_j.get("dataset") if isinstance(cfg_j.get("dataset"), dict) else {}
                cfg_arm = BI_ARM if r.get("type") == "bi_omx_follower" else inv_inst.get(r["id"], "arm_s" if "arm-s" in name else "")
                cams, rebinds, cam_issues, _ = inspect_config_cameras(cfg_j, cfg_arm, reg, reg_err=reg_err)
                config_meta[name] = {
                    "fps": ds.get("fps"), "use_degrees": r.get("use_degrees"), "max_relative_target": r.get("max_relative_target"),
                    "cameras": cams, "camera_rebinds": rebinds, "camera_issues": cam_issues,
                    "episode_time_s": ds.get("episode_time_s"), "reset_time_s": ds.get("reset_time_s"), "num_episodes": ds.get("num_episodes")}
            except (OSError, ValueError, KeyError, TypeError):
                pass
        caps = pick("caps*.json")
        caps_data = {}
        for cname in caps:
            try:
                caps_data[cname] = json.loads((self.prep / cname).read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                pass
        calibrations = sorted(str(p) for p in (Path.home() / ".cache/huggingface/lerobot/calibration")
                              .glob("*/*/*.json"))
        cal_meta = {}
        for cp in calibrations:
            try:
                p = Path(cp)
                raw = json.loads(p.read_text(encoding="utf-8"))
                joints = list(raw.keys()) if isinstance(raw, dict) else []
                cal_meta[cp] = {"role": "팔로워 관절 영점·범위" if p.parent.parent.name == "robots" else "리더 관절 영점·범위",
                                "joints": len(joints), "updated": time.strftime("%m-%d %H:%M", time.localtime(p.stat().st_mtime))}
            except (OSError, ValueError):
                pass
        task_paths = sorted((self.prep / "tasks").glob("*.yaml"))
        tasks = ["tasks/" + p.name for p in task_paths]
        task_cards = {name: _read_task_card(p) for name, p in zip(tasks, task_paths)}
        replays = sorted("replays/" + p.name for p in (self.prep / "replays").glob("*.json")) if (self.prep / "replays").is_dir() else []
        arm_bindings = {arm: self._arm_binding(arm, configs, caps, calibrations) for arm in (*ARMS, BI_ARM)}
        recommended = {arm: self._recommend(arm, arm_bindings[arm]) for arm in (*ARMS, BI_ARM)}
        return {"configs": configs, "config_meta": config_meta, "robots": robots, "caps": caps, "caps_data": caps_data,
                "arms": [*ARMS, BI_ARM], "instances": instances, "arm_bindings": arm_bindings,
                "arm_connectivity": {a: arm_connectivity(self.prep, a) for a in (*ARMS, BI_ARM)},
                "recommended": recommended, "tasks": tasks, "task_cards": task_cards,
                "replays": replays, "calibrations": calibrations, "cal_meta": cal_meta}

    def _recommend(self, arm, binding):
        cfgs, caps_list, cals = binding.get("configs", []), binding.get("caps", []), binding.get("calibrations", [])
        pick_cfg = next((c for c in cfgs if f"arm-{ARMS.get(arm, 'bi')}" in c or c.endswith("-bi-ab.json")), cfgs[0] if cfgs else "")
        base_caps = [c for c in caps_list if "-custom-" not in c] or caps_list
        pick_cap = max(base_caps, key=lambda n: (self.prep / n).stat().st_mtime) if base_caps else ""
        robots = [c for c in cals if Path(c).parent.parent.name == "robots"]
        leaders = [c for c in cals if Path(c).parent.parent.name == "teleoperators"]
        want_l = {"arm_a": ("arm_a_leader", "omx_leader_arm"), "arm_b": ("arm_b_leader",),
                  "arm_s": ("arm_s_leader",), "arm_ab": ("arm_a_leader", "arm_b_leader")}.get(arm, ())
        pick_l = [c for c in leaders if Path(c).stem in want_l]
        if not pick_l and leaders:
            pick_l = [leaders[0]]
        return {"config": pick_cfg, "caps": pick_cap, "calibrations": [*robots, *(pick_l if arm == BI_ARM else pick_l[:1])]}
