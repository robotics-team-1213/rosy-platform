from __future__ import annotations


import hashlib
import inspect
import json
import os
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

from fastapi import Depends, HTTPException

from fleet.charge_bays import bays_from_map
from .pipeline_governance_store import PipelineGovernanceStore, canonical_digest
from .pipeline_ledger import write_ledger
from .pipeline_task_input import finite_json_value


def _storage_dir() -> Path:
    var_lib = Path(os.environ.get("ROSY_VAR_LIB") or "/var/lib/rosy")  # a dev sim names its own: /tmp reads as a ledger fault
    if var_lib.is_dir() and os.access(var_lib, os.W_OK):
        d = var_lib / "pipeline"
        d.mkdir(parents=True, exist_ok=True)
        return d
    return Path("/tmp")


def _enrich_task_health(task: dict) -> dict:
    stop_ev = ((task.get("hardware_telemetry") or {}).get("stop_event") or {})
    health = stop_ev.get("health") or {}
    temps = health.get("temp_c") or []
    currents = health.get("current_ma") or []
    status = task.get("status") or "QUEUED"
    if status == "COMPLETED":
        substage = "Fold Home 완료" if stop_ev.get("folded") else "Place 완료"
    elif status == "RUNNING":
        substage = "Grasp → Lift → Place 실행 중"
    elif status == "PAUSED_HUMAN":
        substage = "사람 감지 비상정지 대기 (이탈 시 자동 재개)"
    elif status in ("CANCELLED", "ABORTED"):
        substage = "작업 취소·중단 (인터락 해제)"
    elif status == "PROPOSED":
        substage = "승인 대기 (PROPOSED)"
    else:
        substage = "큐 대기 (Approach 준비)"
    task["health_summary"] = {
        "max_temp_c": max(temps) if temps else None,
        "max_current_ma": max(currents) if currents else None,
        "substage": substage,
        "folded": bool(stop_ev.get("folded", False)),
    }
    return task


def install_pipeline_routes(
    app, *, console=None, site_maps=None, read_guard=(), operator_guard=None, proposer_guard=None,
    amr_evidence_fn=None, omx_evidence_fn=None,
) -> None:
    if getattr(app.state, "_pipeline_routes_installed", False):
        return
    app.state._pipeline_routes_installed = True

    def _deny_missing_guard():
        raise HTTPException(403, detail={"code": "OPERATOR_GUARD_MISSING"})

    resolved_operator = operator_guard if operator_guard is not None else getattr(app.state, "operator_guard", None)
    if resolved_operator is None:
        # Bare unit-test apps pass read_guard=(); guarded apps without an operator guard fail closed.
        resolved_operator = [Depends(_deny_missing_guard)] if read_guard else ()
    operator_guard = resolved_operator
    resolved_proposer = proposer_guard if proposer_guard is not None else getattr(app.state, "proposer_guard", None)
    proposer_guard = resolved_proposer if resolved_proposer is not None else operator_guard
    app.state.omx_cell_states = getattr(app.state, "omx_cell_states", None) or {}
    app.state.omx_cell_tasks = getattr(app.state, "omx_cell_tasks", None) or {}
    app.state.omx_cell_plans = getattr(app.state, "omx_cell_plans", None) or {}
    app.state.pinky_tasks = getattr(app.state, "pinky_tasks", None) or {}
    app.state.pipeline_decisions = getattr(app.state, "pipeline_decisions", None) or []
    app.state.detected_displaced_site = getattr(app.state, "detected_displaced_site", None)
    app.state.cable_tangled = getattr(app.state, "cable_tangled", True)
    app.state.human_detected = getattr(app.state, "human_detected", None) or {"cell_s": False, "cell_ab": False, "all": False}
    app.state.cell_camera_quality = getattr(app.state, "cell_camera_quality", None) or {}
    app.state.arm_holds = getattr(app.state, "arm_holds", None) or {
        "arm_s": {"arm": "arm_s", "held": False, "reason": None, "incident_ids": []},
        "arm_a": {"arm": "arm_a", "held": False, "reason": None, "incident_ids": []},
        "arm_b": {"arm": "arm_b", "held": False, "reason": None, "incident_ids": []},
    }
    app.state.pending_clear_arms = getattr(app.state, "pending_clear_arms", None) or {}
    app.state.arm_live_states = getattr(app.state, "arm_live_states", None) or {
        "arm_s": {"arm": "arm_s", "cell_id": "cell_s", "station_id": "S3", "joints_deg": [0.0, -58.0, 50.0, 50.0, -5.0, 58.1], "folded": True, "temp_c": 31.0, "current_ma": 42.0, "voltage_v": 12.0, "updated_at": None, "source": "boot_default"},
        "arm_a": {"arm": "arm_a", "cell_id": "cell_ab", "station_id": "S2", "joints_deg": [0.8, -62.5, 53.3, 51.7, 45.0, 50.0], "folded": True, "temp_c": 31.0, "current_ma": 38.0, "voltage_v": 12.0, "updated_at": None, "source": "boot_default"},
        "arm_b": {"arm": "arm_b", "cell_id": "cell_ab", "station_id": "S5", "joints_deg": [-1.2, -61.0, 52.0, 51.0, -45.0, 50.0], "folded": True, "temp_c": 31.5, "current_ma": 40.0, "voltage_v": 12.0, "updated_at": None, "source": "boot_default"},
    }
    STATION_CAMERA_LINKS: dict[str, dict] = {
        "S2": {"place_id": "S2", "target_id": "arm_a", "cell_id": "cell_ab", "primary_cam": "arm_a_wrist", "secondary_cam": "top", "label": "S2 상차 · arm_a"},
        "S3": {"place_id": "S3", "target_id": "arm_s", "cell_id": "cell_s", "primary_cam": "arm_s_wrist", "secondary_cam": "arm_s_top", "label": "S3 하역 셔틀 · arm_s"},
        "S5": {"place_id": "S5", "target_id": "arm_b", "cell_id": "cell_ab", "primary_cam": "arm_b_wrist", "secondary_cam": "top", "label": "S5 적재·반출 · arm_b"},
        "S1": {"place_id": "S1", "target_id": None, "cell_id": "pinky", "primary_cam": "side", "secondary_cam": "top", "label": "S1 출구·반출대 · Pinky"},
        # Bay links name no robot here; station_camera_links_for fills the robot actually in the bay.
        "C1": {"place_id": "C1", "target_id": None, "cell_id": "pinky", "primary_cam": "pinky", "secondary_cam": "side", "label": "C1 충전칸"},
        "C2": {"place_id": "C2", "target_id": None, "cell_id": "pinky", "primary_cam": "pinky", "secondary_cam": "side", "label": "C2 충전칸"},
        "C3": {"place_id": "C3", "target_id": None, "cell_id": "pinky", "primary_cam": "pinky", "secondary_cam": "side", "label": "C3 충전칸"},
    }

    def station_camera_links_for(bays=None) -> dict[str, dict]:
        """Station links with each charge bay pointed at the robot the bay plan sees in it."""
        links = {pid: dict(link) for pid, link in STATION_CAMERA_LINKS.items()}
        for row in bays or ():
            link = links.get(row.get("bay"))
            if link is not None and row.get("robot_id") and row.get("state") in ("arrived", "charging"):
                link.update(target_id=row["robot_id"], label=f"{link['label']} · {row['robot_id']}")
        return links

    def _arm_live_catalog() -> dict[str, dict]:
        now = time.time()
        out: dict[str, dict] = {}
        tasks = list(app.state.omx_cell_tasks.values())
        for arm_id in ("arm_s", "arm_a", "arm_b"):
            base = dict((app.state.arm_live_states or {}).get(arm_id) or {})
            arm_tasks = [t for t in tasks if t.get("arm_id") == arm_id]
            last_t = arm_tasks[-1] if arm_tasks else None
            stop_ev = ((last_t or {}).get("hardware_telemetry") or {}).get("stop_event") or {}
            if isinstance(stop_ev.get("state"), list) and len(stop_ev["state"]) >= 6:
                t_stamp = float(last_t.get("completed_at") or last_t.get("created_at") or 0.0)
                if t_stamp >= float(base.get("updated_at") or 0.0):
                    health = stop_ev.get("health") or {}
                    temps = health.get("temp_c") or []
                    curs = health.get("current_ma") or []
                    base["joints_deg"] = [round(float(x), 1) for x in stop_ev["state"][:6]]
                    base["folded"] = bool(stop_ev.get("folded", False))
                    if temps:
                        base["temp_c"] = round(float(max(temps)), 1)
                    if curs:
                        base["current_ma"] = round(float(max(curs)), 1)
                    base["updated_at"] = round(t_stamp, 3)
                    base["source"] = "task_telemetry"
                    base["last_task_id"] = last_t.get("task_id")
            # The boot default is a placeholder pose, never an observation of the arm.
            observed = base.get("source") != "boot_default" and base.get("updated_at") is not None
            age_s = max(0.0, round(now - float(base["updated_at"]), 1)) if observed else None
            running_t = next((t for t in arm_tasks if t.get("status") == "RUNNING"), None)
            out[arm_id] = {
                **base,
                "arm": arm_id,
                "observed": observed,
                "age_s": age_s,
                "fresh": bool(observed and age_s <= 15.0),
                "active_task_id": running_t["task_id"] if running_t else None,
                "substage": (running_t.get("health_summary") or {}).get("substage") if running_t else ("Fold Home 대기" if base.get("folded", True) else "Place 완료"),
            }
        return out
    app.state.get_arm_live_catalog = _arm_live_catalog
    app.state.station_camera_links = STATION_CAMERA_LINKS
    app.state.station_camera_links_for = station_camera_links_for

    storage_dir = _storage_dir()
    ledger_path = storage_dir / "rosy-pipeline-ledger.json"
    zones_override_path = storage_dir / "station_zones.yaml"
    gov_db = getattr(app.state, "pipeline_governance_db_path", None)
    if gov_db is None:
        gov_db = ":memory:" if (os.environ.get("PYTEST_CURRENT_TEST") or storage_dir == Path("/tmp")) else (storage_dir / "rosy-pipeline-governance.sqlite3")
    if getattr(app.state, "pipeline_governance", None) is None:
        app.state.pipeline_governance = PipelineGovernanceStore(gov_db)
    def _ledger_payload() -> dict:
        return {
            "omx_cell_states": app.state.omx_cell_states,
            "omx_cell_tasks": app.state.omx_cell_tasks,
            "omx_cell_plans": app.state.omx_cell_plans,
            "pinky_tasks": app.state.pinky_tasks,
            "unload_releases": getattr(app.state, "unload_releases", {}),
            "cell_auto_events": getattr(app.state, "cell_auto_events", None) or [],
            "repark_requests": getattr(app.state, "repark_requests", {}),
            "repark_done": getattr(app.state, "repark_done", []),
            "pipeline_decisions": app.state.pipeline_decisions[-100:],
            "pipeline_recovery_ledger": (getattr(app.state, "pipeline_recovery_ledger", None) or [])[-100:],
            "pipeline_recovery_budgets": getattr(app.state, "pipeline_recovery_budgets", None) or {},
            "pipeline_recovery_idempotency": getattr(app.state, "pipeline_recovery_idempotency", None) or {},
            "pipeline_homing_sessions": getattr(app.state, "pipeline_homing_sessions", None) or {},
            "pending_safe_home_arms": getattr(app.state, "pending_safe_home_arms", None) or {},
            "safe_home_history": getattr(app.state, "safe_home_history", None) or {},
            "pipeline_recovery_escalations": getattr(app.state, "pipeline_recovery_escalations", None) or {},
            "detected_displaced_site": app.state.detected_displaced_site,
            "cable_tangled": app.state.cable_tangled,
            "human_detected": app.state.human_detected,
            "_gov_managed": True,
        }

    def _disk_has_uncommitted_stop(disk_doc: dict | None, base_doc: dict | None) -> bool:
        if not isinstance(disk_doc, dict):
            return False
        base_hd = (base_doc or {}).get("human_detected") or {}
        if any(bool(v) and not bool(base_hd.get(k)) for k, v in (disk_doc.get("human_detected") or {}).items()):
            return True
        base_cells = (base_doc or {}).get("omx_cell_states") or {}
        return any((st or {}).get("phase") == "HUMAN_HOLD" and ((base_cells.get(cid) or {}).get("phase") != "HUMAN_HOLD")
                   for cid, st in (disk_doc.get("omx_cell_states") or {}).items())

    def _apply_fail_closed_disk_hold(disk_doc: dict) -> None:
        if isinstance(disk_doc.get("human_detected"), dict):
            app.state.human_detected.update({k: bool(v) for k, v in disk_doc["human_detected"].items() if v})
        for cid, st in (disk_doc.get("omx_cell_states") or {}).items():
            if isinstance(st, dict) and st.get("phase") == "HUMAN_HOLD":
                app.state.omx_cell_states[cid] = dict(st)

    app.state._pipeline_ledger_fault = storage_dir == Path("/tmp") and not os.environ.get("PYTEST_CURRENT_TEST")
    if not app.state._pipeline_ledger_fault and not os.environ.get("PYTEST_CURRENT_TEST"):
        try:
            committed = app.state.pipeline_governance.load_committed_ledger()
            saved: dict | None = None
            if committed is not None:
                saved = committed["payload"]
                disk_raw: dict | None = None
                file_ok = False
                if ledger_path.is_file():
                    try:
                        disk_raw = json.loads(ledger_path.read_text(encoding="utf-8"))
                        file_ok = canonical_digest(disk_raw) == committed["sha256"]
                    except Exception:
                        file_ok = False
                if not file_ok and _disk_has_uncommitted_stop(disk_raw, committed["payload"]):
                    app.state._pipeline_ledger_fault = True
                    _apply_fail_closed_disk_hold(disk_raw)
                    saved = None
                elif not file_ok:
                    write_ledger(ledger_path, saved)
            elif ledger_path.is_file():
                raw = json.loads(ledger_path.read_text(encoding="utf-8"))
                if raw.get("_gov_managed"):
                    if _disk_has_uncommitted_stop(raw, None):
                        app.state._pipeline_ledger_fault = True
                        _apply_fail_closed_disk_hold(raw)
                    else:
                        ledger_path.unlink(missing_ok=True)
                else:
                    saved = raw
                    app.state.pipeline_governance.commit_enqueue(bump_dispatch=False, ledger_snapshot=raw)
            if isinstance(saved, dict):
                app.state.omx_cell_states.update(saved.get("omx_cell_states") or {})
                app.state.omx_cell_tasks.update(saved.get("omx_cell_tasks") or {})
                app.state.omx_cell_plans.update(saved.get("omx_cell_plans") or {})
                app.state.pipeline_governance.reconcile_unpersisted_admissions(app.state.omx_cell_tasks)
                app.state.pinky_tasks.update(saved.get("pinky_tasks") or {})
                app.state.unload_releases = dict(saved.get("unload_releases") or {})
                for _bid, _rec in app.state.unload_releases.items():
                    if isinstance(_rec, dict) and _rec.get("submit_in_flight") and _rec.get("state") in ("SENDING", "SENT"):
                        _rec.update(state="HELD", reason="DEPART_RESTART_AMBIGUOUS")
                        _dt = app.state.pinky_tasks.setdefault(f"depart-{_bid}", {
                            "task_id": f"depart-{_bid}", "robot_id": _rec.get("robot_id"), "action": "depart_s3",
                            "target_place": _rec.get("target") or "S1", "status": "SENT", "auto": True,
                            "created_at": _rec.get("at") or round(time.time(), 3),
                        })
                        _dt.update(cancel_requested=True, cancelled_by="depart_restart_recovery",
                                   cancel_receipt={"error": "DEPART_RESTART_AMBIGUOUS"})
                app.state.cell_auto_events = list(saved.get("cell_auto_events") or [])[-100:]
                app.state.repark_requests = dict(saved.get("repark_requests") or {})
                app.state.repark_done = list(saved.get("repark_done") or [])
                app.state.pipeline_decisions = list(saved.get("pipeline_decisions") or [])[-100:]
                app.state.pipeline_recovery_ledger = list(saved.get("pipeline_recovery_ledger") or [])[-100:]
                app.state.pipeline_recovery_budgets = dict(saved.get("pipeline_recovery_budgets") or {})
                app.state.pipeline_recovery_idempotency = dict(saved.get("pipeline_recovery_idempotency") or {})
                app.state.pipeline_homing_sessions = dict(saved.get("pipeline_homing_sessions") or {})
                app.state.pending_safe_home_arms = dict(saved.get("pending_safe_home_arms") or {})
                app.state.safe_home_history = dict(saved.get("safe_home_history") or {})
                app.state.pipeline_recovery_escalations = dict(saved.get("pipeline_recovery_escalations") or {})
                app.state.detected_displaced_site = saved.get("detected_displaced_site")
                if "cable_tangled" in saved:
                    app.state.cable_tangled = bool(saved["cable_tangled"])
                if isinstance(saved.get("human_detected"), dict):
                    app.state.human_detected.update({k: bool(v) for k, v in saved["human_detected"].items()})
        except Exception:
            app.state._pipeline_ledger_fault = True
    try:
        from fleet.server.pipeline_recovery_policy import effective_stop_fence

        app.state.safety_stop_generation = int(app.state.pipeline_governance.snapshot()["stop_generation"])
        _fence_held, _cur_fence = effective_stop_fence(app.state)
        for _aid in list((getattr(app.state, "pending_safe_home_arms", None) or {}).keys()):
            _row = app.state.pending_safe_home_arms.get(_aid)
            if not isinstance(_row, dict) or _cur_fence is None or _row.get("stop_generation") != _cur_fence:
                _popped = app.state.pending_safe_home_arms.pop(_aid, None) or {}
                _rt = _popped.get("root_task_id")
                if _rt and isinstance((getattr(app.state, "pipeline_homing_sessions", None) or {}).get(_rt), dict):
                    app.state.pipeline_homing_sessions[_rt].update(stage="SKIPPED", last_error="RESTART_STOP_PREEMPTED")
    except Exception:
        app.state._pipeline_ledger_fault = True

    def _write_ledger_only(payload: dict) -> None:
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return
        if app.state._pipeline_ledger_fault:
            raise HTTPException(503, detail={"code": "PIPELINE_LEDGER_UNAVAILABLE"})
        try:
            write_ledger(ledger_path, payload)
        except Exception as exc:
            app.state._pipeline_ledger_fault = True
            raise HTTPException(503, detail={"code": "PIPELINE_LEDGER_UNAVAILABLE"}) from exc

    def _commit_ledger(
        *,
        bump_dispatch: bool = False,
        bump_stop: bool = False,
        idempotency: tuple[str, str, int, dict] | None = None,
        delete_confirmation: tuple[str, str] | None = None,
        commit: bool = True,
    ) -> None:
        gov = app.state.pipeline_governance
        if os.environ.get("PYTEST_CURRENT_TEST"):
            if commit and (bump_dispatch or bump_stop or idempotency is not None or delete_confirmation is not None):
                gov.commit_enqueue(
                    bump_dispatch=bump_dispatch, bump_stop=bump_stop, idempotency=idempotency,
                    delete_confirmation=delete_confirmation,
                )
            return
        payload = _ledger_payload()
        _write_ledger_only(payload)
        if commit:
            gov.commit_enqueue(
                bump_dispatch=bump_dispatch, bump_stop=bump_stop, idempotency=idempotency,
                ledger_snapshot=payload, delete_confirmation=delete_confirmation,
            )

    def _save_ledger() -> None:
        _commit_ledger()

    def _ready_amr(task: dict) -> dict | None:
        if app.state._pipeline_ledger_fault:
            return None
        # No Fleet source currently reports brake and bed readiness; absent source holds the task.
        try:
            observed = amr_evidence_fn(task) if callable(amr_evidence_fn) else None
        except Exception:
            return None
        if not isinstance(observed, dict):
            return None
        if not finite_json_value(observed):
            return None
        stamp = observed.get("observed_at")
        speed = observed.get("v_cmd_mps")
        pose = observed.get("pose")
        if (observed.get("robot_id") != task["robot_id"] or observed.get("cell_id") != task["cell_id"]
                or observed.get("wheel_brake_locked") is not True or observed.get("bed_ready") is not True
                or not isinstance(stamp, (int, float)) or isinstance(stamp, bool)
                or not 0 <= time.time() - stamp <= 2.0
                or not isinstance(speed, (int, float)) or isinstance(speed, bool)
                or abs(speed) > 1e-4
                or not isinstance(pose, dict)
                or any(not isinstance(pose.get(axis), (int, float)) for axis in ("x", "y", "yaw"))):
            return None
        return observed

    def _is_human_detected(subject_id: str | None = None) -> bool:
        hd = app.state.human_detected or {}
        if hd.get("all"):
            return True
        if subject_id in ("cell_s", "cell_ab"):
            return bool(hd.get(subject_id))
        return any(bool(v) for v in hd.values())

    def _evaluate_decision(subject_id: str, domain: str | None = None, facts_override: dict | None = None,
                           *, save: bool = True) -> dict:
        ov = dict(facts_override or {})
        if "human_detected" in ov and ov["human_detected"] is not None and not ov["human_detected"]:
            raise HTTPException(409, detail={"code": "HUMAN_CLEAR_EVIDENCE_UNAVAILABLE"})
        if "tangled" in ov and ov["tangled"] is not None:
            app.state.cable_tangled = bool(ov["tangled"])
        if "displaced_to" in ov and ov["displaced_to"] in ("belt_far", "floor_front", None, ""):
            app.state.detected_displaced_site = ov["displaced_to"] or None
        if "human_detected" in ov and ov["human_detected"] is not None:
            key = subject_id if subject_id in ("cell_s", "cell_ab") else "all"
            app.state.human_detected[key] = True
        tangled = bool(app.state.cable_tangled)
        displaced = app.state.detected_displaced_site
        human_near = _is_human_detected(subject_id)
        resolved_domain = domain or ("arm_target" if subject_id in ("cell_s", "cell_ab") else "line_follow")
        now_ts = round(time.time(), 3)
        decision_id = f"dec-{uuid.uuid4().hex[:8]}"

        if resolved_domain == "arm_target":
            target_state = "human_intrusion" if human_near else ("missing" if (subject_id == "cell_s" and displaced) else "present")
            facts = {
                "state": target_state,
                "target_state": target_state,
                "displaced_to": displaced if subject_id == "cell_s" else None,
                "tangled": tangled,
                "human_detected": human_near,
            }
            choices = ["object_reacquire", "reobserve", "human"]
            if human_near:
                chosen = "human"
                auto_preset = None
                objections = ["unsafe", "human_near_arm"]
                reason = f"Decision(arm_target): {subject_id} 작업 반경 내 사람 감지(HUMAN_HOLD) → 즉시 비상정지 및 클레임 차단"
            elif subject_id == "cell_s" and displaced == "floor_front":
                chosen = "object_reacquire"
                auto_preset = "s3_recover_floor_front"
                objections = ["unsafe"] if tangled else []
                reason = f"Decision(arm_target): 전방 바닥 이탈(floor_front) 감지 → object_reacquire 바닥 복구 자동 선택 (미세 조그 {'ON' if tangled else 'OFF'})"
            elif subject_id == "cell_s" and displaced == "belt_far":
                chosen = "object_reacquire"
                auto_preset = "s3_recover_belt_far"
                objections = ["unsafe"] if tangled else []
                reason = f"Decision(arm_target): 벨트 원거리 이탈(belt_far) 감지 → object_reacquire 벨트 복구 자동 선택 (미세 조그 {'ON' if tangled else 'OFF'})"
            else:
                chosen = "reobserve"
                auto_preset = "s3_shuttle" if subject_id == "cell_s" else "s5_tier1_arm_a"
                objections = ["unsafe"] if tangled else []
                reason = f"Decision(arm_target): 용기 정위치(present) 확인 → {auto_preset} 자동 선택 (미세 조그 {'ON' if tangled else 'OFF'})"
            auto_pinky_action = None
        else:
            cell_locked = any((cs.get("phase") in ("ARM_IN_BED_ZONE", "HUMAN_HOLD", "ABORTED") or cs.get("amr_motion_inhibited"))
                              for cs in app.state.omx_cell_states.values())
            state_str = "human_estop" if human_near else ("blocked" if (tangled or cell_locked) else "normal")
            facts = {
                "state": state_str,
                "tangled": tangled,
                "cell_locked": cell_locked,
                "human_detected": human_near,
                "recovery": {
                    "phase": "ASKING",
                    "attempts": 1,
                    "max_attempts": 3,
                    "local_enabled": True,
                    "cause": "human_intrusion" if human_near else ("no_motion" if tangled else ("obstacle_ahead" if cell_locked else "lane_lost")),
                },
            }
            choices = ["back_and_retry", "reobserve", "human"]
            if human_near:
                chosen = "human"
                auto_pinky_action = "stop_now"
                objections = ["unsafe", "human_near_arm"]
                reason = "Decision(line_follow): 셀/주행 구역 사람 접근 감지(HUMAN_HOLD) → stop_now 즉시 비상정지"
            elif cell_locked:
                chosen = "reobserve"
                auto_pinky_action = "stop_now"
                objections = ["unsafe"]
                reason = "Decision(line_follow): OMX 셀 작업 중(ARM_IN_BED_ZONE) 인터락 감지 → stop_now 즉시 정지 유지"
            elif tangled:
                chosen = "back_and_retry"
                auto_pinky_action = str(ov.get("preferred_micro_action") or "micro_forward_2cm")
                objections = ["unsafe"]
                reason = "Decision(line_follow): 선 꼬임(tangled=true) 감지 → 장거리 주행 차단 및 1.5cm(0.02m/s) 미세 이동(back_and_retry) 자동 전환"
            else:
                chosen = "reobserve"
                auto_pinky_action = "dock_and_unload_s3"
                objections = []
                reason = "Decision(line_follow): 선 꼬임 없음·경로 정상(normal) → S3 도킹+하역(dock_and_unload_s3) 자동 승인"
            auto_preset = None

        recommended = auto_preset or auto_pinky_action or "stop_now"
        digest = hashlib.sha256(
            json.dumps({"subject_id": subject_id, "domain": resolved_domain, "facts": facts, "choices": choices}, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]
        row = {
            "schema": "rosy.omx-cell-decision.v1",
            "decision_id": decision_id,
            "subject_id": subject_id,
            "domain": resolved_domain,
            "input_hash": digest,
            "facts": facts,
            "options": choices,
            "chosen": chosen,
            "choice": chosen,
            "recommended_action": recommended,
            "objections": objections,
            "cable_guard_micro": tangled,
            "human_detected": human_near,
            "auto_preset": auto_preset,
            "auto_pinky_action": auto_pinky_action,
            "by": "decision_engine",
            "reason": reason,
            "t": now_ts,
        }
        app.state.pipeline_decisions.append(row)
        if len(app.state.pipeline_decisions) > 100:
            app.state.pipeline_decisions = app.state.pipeline_decisions[-100:]
        if save:
            _save_ledger()
        return row

    def _maps():
        return site_maps if site_maps is not None else getattr(app.state, "site_maps", None)

    async def inputs(active):
        fn = getattr(app.state, "bay_inputs", None)
        if callable(fn):
            result = fn()
            if inspect.isawaitable(result):
                result = await result
            _, robots, bays = result
            return list(robots), list(bays)
        return [], bays_from_map(active[1])

    def rules():
        m = _maps()
        return (m.rules.active_rules() if m is not None and
                getattr(m, "rules", None) is not None else None)

    def active_map():
        m = _maps()
        active = m.active() if m is not None else None
        if active is None:
            raise HTTPException(404, detail={"code": "NO_ACTIVE_MAP"})
        return active

    from fleet.server.sitemap.pipeline_cell_task_routes import install_cell_tasks_routes
    from fleet.server.sitemap.pipeline_cell_plan_routes import install_cell_plan_routes
    from fleet.server.sitemap.pipeline_gate_routes import install_gates_routes
    from fleet.server.sitemap.pipeline_camera_routes import install_cameras_routes
    from fleet.server.sitemap.pipeline_evidence import install_evidence_routes
    from fleet.server.pipeline_recovery_tools import install_recovery_tool_routes

    ctx = SimpleNamespace(
        STATION_CAMERA_LINKS=STATION_CAMERA_LINKS, _arm_live_catalog=_arm_live_catalog,
        zones_override_path=zones_override_path, _save_ledger=_save_ledger, _commit_ledger=_commit_ledger,
        _ledger_payload=_ledger_payload, _write_ledger_only=_write_ledger_only,
        _is_human_detected=_is_human_detected, _evaluate_decision=_evaluate_decision,
        inputs=inputs, rules=rules, active_map=active_map, read_guard=read_guard,
        operator_guard=operator_guard, proposer_guard=proposer_guard,
        _ready_amr=_ready_amr, omx_evidence_fn=omx_evidence_fn, console=console, gov=app.state.pipeline_governance,
    )
    install_cell_tasks_routes(app, ctx)
    install_cell_plan_routes(app, ctx)
    install_gates_routes(app, ctx)
    install_cameras_routes(app, ctx)
    install_evidence_routes(app, ctx)
    install_recovery_tool_routes(app, ctx)

    def _hold_state():  # a real hazard is HUMAN_HOLD; the closed dispatch latch alone needs a named rearm (D-540)
        if (
            _is_human_detected()
            or getattr(app.state, "_fleet_estop_latch_unresolved", False)
            or getattr(app.state, "_pipeline_ledger_fault", False)
            or any((s or {}).get("phase") == "HUMAN_HOLD" for s in app.state.omx_cell_states.values())
        ):
            return "HUMAN_HOLD", {}
        tsvc = getattr(app.state, "task_service", None)
        if tsvc is not None:
            try:
                ctrl = tsvc.store.dispatch_control()
            except Exception:
                return "HUMAN_HOLD", {}
            if not isinstance(ctrl, dict) or ctrl.get("dispatch_enabled") is not True:
                keys = ("reason", "rearm_available", "queued_tasks", "unresolved_actions")
                known = isinstance(ctrl, dict) and ctrl.get("dispatch_enabled") is False  # unknown state stays a hazard
                return ("DISPATCH_REARM_REQUIRED", {k: ctrl.get(k) for k in keys}) if known else ("HUMAN_HOLD", {})
        return None

    app.state.pipeline_hold_state_fn = _hold_state
    app.state.pipeline_human_hold_fn = _human_hold_active = lambda: _hold_state() is not None  # noqa: E731
    if (tr := getattr(app.state, "trip_runner", None)) is not None:
        tr.human_hold_fn = _human_hold_active
        tr.hold_state_fn = _hold_state
