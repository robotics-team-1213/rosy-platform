#!/usr/bin/env python3
"""Canonical cell map provenance, live log stream, custom task synthesis, and factory defaults reset."""
from __future__ import annotations

from collections import deque
import json
import os
from pathlib import Path
import re
import threading
import time

from bench_record_handoff import atomic_write_json, load_json_value, save_handoff_config
from bench_record_inspect import ARMS, BI_ARM
from bench_record_replay import apply_task_override
from teleop_speed import read_stage, summary as speed_summary

FACTORY_DEFAULTS_FILE = ".bench-factory-defaults.json"
_SPOT_RE = re.compile(r"^[a-zA-Z0-9_:-]{1,64}$")
_LAYER_RE = re.compile(r"^[a-zA-Z0-9_-]{1,32}$")
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_SECRET_HF_RE = re.compile(r"\bhf_[A-Za-z0-9]{10,}\b")
_SECRET_BEARER_RE = re.compile(r"(?i)(Bearer\s+)[^\s\"']+")
_GRIP_KEYS = ("leader_closed", "leader_open", "follower_closed", "follower_open")


def sanitize_log_line(text: str) -> str:
    clean = _ANSI_RE.sub("", str(text or ""))
    clean = _SECRET_HF_RE.sub("hf_<REDACTED>", clean)
    clean = _SECRET_BEARER_RE.sub(r"\1<REDACTED>", clean)
    return clean.strip()


def _line_level(text: str) -> str:
    up = text.upper()
    if any(k in up for k in ("ERROR", "REFUSED", "TRACEBACK", "FAIL", "HOLD", "CRITICAL", "차단", "실패")):
        return "crit"
    if any(k in up for k in ("WARN", "STALE", "SKIPPED", "취소", "지연", "주의", "미수신")):
        return "warn"
    return "info"


def build_custom_task_card(arm: str, override: dict, cfg_data: dict, overrides: dict) -> dict:
    """Build a valid rosy.omx-task-card.v1 dict from an inline custom origin/target pick."""
    if not isinstance(override, dict) or override.get("custom") is not True:
        raise ValueError("custom task override에는 custom=true가 필요합니다")
    origin = str(override.get("origin") or "").strip()
    target_slot = str(override.get("target_slot") or "").strip()
    if not origin or not target_slot:
        raise ValueError("직접 목표 설정에는 집을 곳(origin)과 놓을 곳(target_slot)이 필요합니다")
    if not _SPOT_RE.fullmatch(origin) or not _SPOT_RE.fullmatch(target_slot):
        raise ValueError("출발/목표 위치 식별자 형식이 올바르지 않습니다")
    if origin == target_slot:
        raise ValueError("집을 곳(origin)과 놓을 곳(target_slot)은 같을 수 없습니다")
    target_layer = str(override.get("target_layer") or "").strip()
    if target_layer and not _LAYER_RE.fullmatch(target_layer):
        raise ValueError("target_layer 형식이 올바르지 않습니다")
    raw_instr = re.sub(r"\s+", " ", str(override.get("single_task") or "")).strip()[:240]
    single_task = raw_instr or f"Move container from {origin} to {target_slot}."
    slug = re.sub(r"[^a-z0-9-]+", "-", f"custom-{origin}-to-{target_slot}".lower()).strip("-")[:64].strip("-")
    task_id = slug if len(slug) >= 3 else "custom-task"
    ds_cfg = cfg_data.get("dataset") if isinstance(cfg_data.get("dataset"), dict) else {}
    ep_t = overrides.get("episode_time_s") or ds_cfg.get("episode_time_s") or 40
    rs_t = overrides.get("reset_time_s") or ds_cfg.get("reset_time_s") or 10
    n_ep = overrides.get("num_episodes") or ds_cfg.get("num_episodes") or 5
    root_prefix = str(ds_cfg.get("root") or (Path.home() / "rosy-data" / "omx-leader"))
    layout = {"origin": origin, "target_slot": target_slot, "shot_arm": arm, "source_kind": "custom_bench_ui"}
    if target_layer:
        layout["target_layer"] = target_layer
    return {
        "schema": "rosy.omx-task-card.v1",
        "task_id": task_id,
        "revision": 1,
        "single_task": single_task,
        "record": {
            "repo_id": f"local/omx-{task_id}",
            "root_prefix": root_prefix,
            "episode_time_s": ep_t,
            "reset_time_s": rs_t,
            "num_episodes": n_ep,
        },
        "layout": layout,
    }


def prepare_session_task_card(effective_task, task_card, task_override, arm, cfg_data, overrides, snap_dir: Path):
    """Resolve existing/custom task card into snapshot YAML when overrides apply."""
    ds_cfg = cfg_data.get("dataset") if isinstance(cfg_data.get("dataset"), dict) else {}
    eff_root = ds_cfg.get("root")
    eff_eps = overrides.get("num_episodes") or ds_cfg.get("num_episodes")
    if isinstance(task_override, dict) and task_override.get("custom") is True and not effective_task:
        tc_data = build_custom_task_card(arm, task_override, cfg_data, overrides)
        rec = tc_data["record"]
        out_p = snap_dir / "effective-task-card.yaml"
        return (
            tc_data["task_id"],
            rec.get("root_prefix") or eff_root,
            rec.get("num_episodes") or eff_eps,
            str(out_p),
            ("effective-task-card.yaml", json.dumps(tc_data, indent=2, ensure_ascii=False).encode("utf-8")),
        )
    if effective_task and (overrides or task_override):
        import yaml
        tc_data = yaml.safe_load(Path(effective_task).read_text(encoding="utf-8"))
        if not isinstance(tc_data, dict):
            raise ValueError("과제 카드 YAML 형식이 올바르지 않습니다")
        if overrides:
            tc_data.setdefault("record", {}).update(overrides)
        if task_override:
            tc_data = apply_task_override(tc_data, task_override)
        rec_blk = tc_data.get("record") or {}
        out_p = snap_dir / "effective-task-card.yaml"
        return (
            tc_data.get("task_id"),
            rec_blk.get("root_prefix") or eff_root,
            rec_blk.get("num_episodes") or eff_eps,
            str(out_p),
            ("effective-task-card.yaml", json.dumps(tc_data, indent=2, ensure_ascii=False).encode("utf-8")),
        )
    eff_task_id = None
    if effective_task and task_card:
        eff_task_id = task_card.get("task_id")
        eff_eps = task_card.get("num_episodes") or eff_eps
        eff_root = task_card.get("root_prefix") or eff_root
    return eff_task_id, eff_root, eff_eps, effective_task, None


def snapshot_factory_grip(prep: Path, arm: str, existing_grip: dict | None) -> bool:
    """Save the initial pre-edit gripper map once per arm as the factory default."""
    if arm not in ARMS or not isinstance(existing_grip, dict):
        return False
    if any(isinstance(existing_grip.get(k), bool) or not isinstance(existing_grip.get(k), int) for k in _GRIP_KEYS):
        return False
    path = Path(prep) / FACTORY_DEFAULTS_FILE
    doc = load_json_value(path, {})
    if not isinstance(doc, dict):
        doc = {}
    gmap = doc.get("gripper_factory")
    if not isinstance(gmap, dict):
        gmap = {}
    if arm in gmap:
        return False
    gmap[arm] = {k: int(existing_grip[k]) for k in _GRIP_KEYS}
    doc["schema"] = "rosy.bench-factory-defaults.v1"
    doc["gripper_factory"] = gmap
    atomic_write_json(path, doc)
    return True


def _build_spot_catalog(site_doc: dict) -> list[dict]:
    spots = [
        {"code": "belt", "label": "벨트 인출단 (belt)", "site_id": "not_places:belt", "zone": "belt", "arms": ["arm_a", "arm_b"], "source": "shared/web/cell-site-map.json"},
        {"code": "belt-in", "label": "벨트 공급단 (belt-in)", "site_id": "not_places:supply_s", "zone": "belt-in", "arms": ["arm_s"], "source": "shared/web/cell-site-map.json"},
        {"code": "pinky", "label": "핑키 로봇 짐칸 (pinky)", "site_id": "not_places:vehicle_tray", "zone": "pinky", "arms": ["arm_s"], "source": "shared/web/cell-site-map.json"},
        {"code": "supply", "label": "공급대 (supply)", "site_id": "not_places:supply_s", "zone": "arm-s", "arms": ["arm_s"], "source": "shared/web/cell-site-map.json"},
    ]
    tier_mm = float(site_doc.get("tier_height_mm") or 32.4) if isinstance(site_doc, dict) else 32.4
    zones = site_doc.get("zones") if isinstance(site_doc, dict) and isinstance(site_doc.get("zones"), list) else []
    row_names = {1: "A쪽 줄", 2: "가운데 줄", 3: "B쪽 줄"}
    for z in zones:
        zid = str(z.get("id") or "")
        for sl in z.get("slots") or []:
            arms = list(sl.get("arms") or [])
            for t in sl.get("tiers") or []:
                code = str(t.get("item") or "").strip()
                if not code:
                    continue
                tier_num = int(t.get("tier") or 1)
                h_mm = round((tier_num - 1) * tier_mm, 1)
                if zid == "yard":
                    hm = re.match(r"^ship-h(\d)", code)
                    h_no = hm.group(1) if hm else str(sl.get("hold") or "?")
                    lbl = f"화물칸 h{h_no} · {row_names.get(sl.get('row'), sl.get('label', ''))} · {tier_num}층 ({code})"
                elif zid in ("temp_a", "temp_b"):
                    side = "A(좌)" if zid == "temp_a" else "B(우)"
                    lbl = f"임시대 {side} · {sl.get('label', '')} · {tier_num}층 ({code})"
                elif zid == "stand":
                    lbl = "반출대 · 컨베이어 우측 (stand)"
                else:
                    lbl = f"{z.get('label', zid)} · {code}"
                spots.append({
                    "code": code, "label": lbl, "site_id": str(t.get("id") or ""), "zone": zid, "arms": arms,
                    "hold": sl.get("hold"), "row": sl.get("row"), "slot": sl.get("slot"), "tier": tier_num,
                    "height_mm": h_mm, "source": "shared/web/cell-site-map.json",
                })
    return spots


def build_cell_map_payload(prep: Path, repo_root: Path | None = None) -> dict:
    """Load canonical cell topology, two-arm sim layout, and measured site calibrations."""
    root = repo_root or Path(__file__).resolve().parents[3]
    site_p = root / "shared" / "web" / "cell-site-map.json"
    two_p = Path(__file__).resolve().parent / "sim" / "two_arm_tasks.json"
    site_doc = load_json_value(site_p, {})
    two_doc = load_json_value(two_p, {})
    sd = site_doc if isinstance(site_doc, dict) else {}
    td = two_doc if isinstance(two_doc, dict) else {}
    sources = [
        {"kind": "canonical_map", "label": "셀 표준 구역/슬롯 맵", "path": "shared/web/cell-site-map.json", "exists": site_p.is_file(), "schema": sd.get("schema"), "revision": sd.get("revision"), "status": sd.get("status")},
        {"kind": "sim_tasks", "label": "양팔 시뮬 작업 배치도", "path": "deploy/robot/omx/sim/two_arm_tasks.json", "exists": two_p.is_file(), "schema": td.get("schema"), "revision": None, "status": "sim_reference"},
    ]
    sim_tasks = {}
    raw_tasks = td.get("tasks") if isinstance(td.get("tasks"), dict) else {}
    for name, info in raw_tasks.items():
        if not isinstance(info, dict):
            continue
        steps = info.get("steps") if isinstance(info.get("steps"), list) else []
        arms = sorted({str(s.get("arm")) for s in steps if isinstance(s, dict) and s.get("arm")})
        sample = [{"from": s.get("from"), "to": s.get("to"), "arm": s.get("arm")} for s in steps[:4] if isinstance(s, dict)]
        sim_tasks[name] = {"step_count": len(steps), "arms": arms, "note": str(info.get("_note") or "")[:180], "sample": sample}
    calibrated_sites = {}
    for arm, fn in (("arm_a", "cell-arm-a-stack.json"), ("arm_b", "cell-arm-b-stack.json")):
        p = prep / fn
        doc = load_json_value(p, {}) if p.is_file() else {}
        top = ((doc.get("cameras") or {}).get("top") or {}) if isinstance(doc, dict) else {}
        sites = doc.get("sites") if isinstance(doc, dict) and isinstance(doc.get("sites"), dict) else {}
        sources.append({"kind": "stack_config", "label": f"{arm} 실측 스택 설정", "path": fn, "exists": p.is_file(), "schema": "stack-config", "revision": None, "status": "loaded" if p.is_file() else "missing"})
        if p.is_file():
            calibrated_sites[arm] = {"file": fn, "top_height_m": top.get("height_m"), "warp_measured": (top.get("warp_to_reference") or {}).get("measured"), "sites": sorted(sites.keys())}
    cs_p = Path.home() / ".config" / "rosy" / "omx-cell-s.json"
    cs_doc = load_json_value(cs_p, {}) if cs_p.is_file() else {}
    sources.append({"kind": "cell_profile", "label": "Arm S 실측 셀 프로필", "path": "~/.config/rosy/omx-cell-s.json", "exists": cs_p.is_file(), "schema": cs_doc.get("schema") if isinstance(cs_doc, dict) else None, "revision": None, "status": "loaded" if cs_p.is_file() else "missing"})
    if isinstance(cs_doc, dict) and cs_doc:
        calibrated_sites["arm_s"] = {"file": "~/.config/rosy/omx-cell-s.json", "sites": sorted((cs_doc.get("sites") or {}).keys()) if isinstance(cs_doc.get("sites"), dict) else [], "tolerance": cs_doc.get("tolerance")}
    task_prov = {}
    if (prep / "tasks").is_dir():
        from record_session_helpers import load_task_card
        for tp in sorted((prep / "tasks").glob("*.yaml")):
            try:
                tdoc = load_task_card(tp)
                rec_d = tdoc.get("record") or {}
                task_prov[f"tasks/{tp.name}"] = {
                    "source_file": f"tasks/{tp.name}", "repo_id": str(rec_d.get("repo_id") or ""),
                    "root_prefix": str(rec_d.get("root_prefix") or ""),
                    "known_limits": [str(x) for x in (tdoc.get("known_limits") or [])[:4]] if isinstance(tdoc.get("known_limits"), list) else [],
                    "success_end_state": str((tdoc.get("success") or {}).get("end_state") or "") if isinstance(tdoc.get("success"), dict) else "",
                }
            except Exception:
                continue
    return {
        "schema": sd.get("schema"), "revision": sd.get("revision"), "tier_height_mm": sd.get("tier_height_mm", 32.4),
        "zones": sd.get("zones", []), "not_places": sd.get("not_places", []), "aliases": sd.get("aliases", {}),
        "spot_catalog": _build_spot_catalog(sd), "sim_tasks": sim_tasks, "calibrated_sites": calibrated_sites,
        "task_provenance": task_prov, "sources": sources,
    }


class BenchWorkspaceMixin:
    def _ensure_logs(self):
        if not hasattr(self, "_log_lock"):
            with self.lock:
                if not hasattr(self, "_log_lock"):
                    self._log_lock = threading.Lock()
                    self._bench_logs = deque(maxlen=200)

    def _log_event(self, source: str, level: str, message: str):
        self._ensure_logs()
        text = sanitize_log_line(message)
        if not text:
            return
        lvl = level if level in ("info", "warn", "crit", "good") else "info"
        row = {"ts": time.strftime("%H:%M:%S", time.localtime(self.clock())), "epoch": round(float(self.clock()), 3), "source": str(source or "bench"), "level": lvl, "text": text[:400]}
        with self._log_lock:
            self._bench_logs.append(row)

    def cell_map(self):
        repo_root = Path(__file__).resolve().parents[3]
        return build_cell_map_payload(self.prep, repo_root=repo_root)

    def live_logs(self, limit: int = 80):
        self._ensure_logs()
        lim = max(1, min(200, int(limit or 80)))
        with self._log_lock:
            entries = list(self._bench_logs)
        with self.lock:
            st = dict(self.state)
        log_path = None
        if st.get("folder"):
            cand = Path(st["folder"]) / "bench.log"
            if cand.is_file():
                log_path = cand
        if log_path is None and st.get("status") == "homing" and st.get("step_arm"):
            cand = self.prep / ".bench-runs" / f"home-{st['step_arm']}.log"
            if cand.is_file():
                log_path = cand
        if log_path is None and (self.prep / "sessions").is_dir():
            for d in sorted((p for p in (self.prep / "sessions").iterdir() if p.is_dir()), reverse=True)[:3]:
                cand = d / "bench.log"
                if cand.is_file():
                    log_path = cand
                    break
        if log_path is not None:
            try:
                mt = time.strftime("%H:%M:%S", time.localtime(log_path.stat().st_mtime))
                lines = [ln for ln in log_path.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()][-50:]
                for ln in lines:
                    clean = sanitize_log_line(ln)
                    if clean:
                        entries.append({"ts": mt, "epoch": 0.0, "source": "session", "level": _line_level(clean), "text": clean[:400]})
            except OSError:
                pass
        pipe_logs = getattr(self, "_pipe_state", {}).get("logs") if hasattr(self, "_pipe_state") else None
        if isinstance(pipe_logs, list):
            for ln in pipe_logs[-20:]:
                clean = sanitize_log_line(ln)
                if clean:
                    entries.append({"ts": "", "epoch": 0.0, "source": "pipeline", "level": _line_level(clean), "text": clean[:400]})
        return {"entries": entries[-lim:], "log_file": log_path.name if log_path else "", "status": st.get("status", "idle"), "total": len(entries)}

    def defaults_summary(self):
        fdoc = load_json_value(self.prep / FACTORY_DEFAULTS_FILE, {})
        gmap = fdoc.get("gripper_factory") if isinstance(fdoc, dict) and isinstance(fdoc.get("gripper_factory"), dict) else {}
        rec = self.choices().get("recommended", {})
        return {
            "speed_factory": None,
            "speed_recommended": 60,
            "recommended": rec,
            "grip_factory_available": {a: (a in gmap) for a in ARMS},
            "handoff_defaults": {"auto_loop": True, "auto_hf_upload": False},
        }

    def reset_defaults(self, body):
        if not isinstance(body, dict):
            raise ValueError("JSON object required")
        preset = str(body.get("preset") or "factory").strip()
        scope = str(body.get("scope") or "all").strip()
        raw_arm = str(body.get("arm") or "").strip()
        if preset not in ("factory", "recommended"):
            raise ValueError("preset은 factory 또는 recommended여야 합니다")
        if scope not in ("speed", "grip", "params", "handoff", "all"):
            raise ValueError("scope는 speed, grip, params, handoff, all 중 하나여야 합니다")
        if not raw_arm or raw_arm == BI_ARM:
            target_arms = ("arm_a", "arm_b") if raw_arm == BI_ARM else ("arm_a", "arm_b", "arm_s")
        elif raw_arm in ARMS:
            target_arms = (raw_arm,)
        else:
            raise ValueError("유효한 팔(arm_a, arm_b, arm_s, arm_ab)을 선택하세요")
        with self.lock:
            if self.state.get("status") in ("handing_over", "homing", "recording", "restoring", "sealing", "leader_manual_check"):
                raise ValueError("세션이나 홈 이동이 진행 중일 때는 기본값으로 되돌릴 수 없습니다")
        reset_items, skipped_items = [], []
        if scope in ("speed", "params", "all"):
            for a in target_arms:
                sp = self.prep / f"teleop-speed-{a}.json"
                if preset == "factory":
                    sp.unlink(missing_ok=True)
                    reset_items.append(f"{a}:속도=공장기본(25°/s)")
                else:
                    atomic_write_json(sp, {"stage": 60})
                    reset_items.append(f"{a}:속도=권장(60°/s)")
        if scope in ("grip", "params", "all"):
            from bench_record_link import _leader_mount_path
            fdoc = load_json_value(self.prep / FACTORY_DEFAULTS_FILE, {})
            gmap = fdoc.get("gripper_factory") if isinstance(fdoc, dict) and isinstance(fdoc.get("gripper_factory"), dict) else {}
            for a in target_arms:
                snap = gmap.get(a)
                mp = _leader_mount_path(a)
                if not isinstance(snap, dict) or any(not isinstance(snap.get(k), int) for k in _GRIP_KEYS):
                    skipped_items.append(f"{a}:집게(초기 스냅샷 없음-현재값 유지)")
                    continue
                if mp.is_symlink() or mp.parent.is_symlink():
                    skipped_items.append(f"{a}:집게(심볼릭 링크 차단)")
                    continue
                mp.parent.mkdir(parents=True, exist_ok=True)
                existing = load_json_value(mp, {})
                if not isinstance(existing, dict):
                    existing = {}
                existing["gripper"] = {k: int(snap[k]) for k in _GRIP_KEYS}
                tmp = mp.with_name(mp.name + ".tmp")
                tmp.write_text(json.dumps(existing, ensure_ascii=False) + "\n", encoding="utf-8")
                os.replace(tmp, mp)
                reset_items.append(f"{a}:집게=공장초기값")
        if scope in ("handoff", "all"):
            patch = {"auto_loop": True, "auto_hf_upload": False}
            if body.get("clear_targets"):
                patch.update(model_target="", intake_url="", peer_token_file="")
            cfg = save_handoff_config(self.prep, patch)
            if hasattr(self, "_pipe_lock"):
                with self._pipe_lock:
                    self._pipe_state["auto_loop"] = bool(cfg["auto_loop"])
                    self._pipe_state["model_target"] = cfg["model_target"]
                    self._pipe_state["intake_url"] = cfg["intake_url"]
            if hasattr(self, "_hf_lock"):
                with self._hf_lock:
                    self._hf_state["auto_upload"] = bool(cfg["auto_hf_upload"])
            reset_items.append("handoff:자동전달기본")
        self._log_event("config", "good", f"기본값 복원({preset}/{scope}): {', '.join(reset_items) or '없음'}")
        return {
            "ok": True,
            "preset": preset,
            "scope": scope,
            "reset_items": reset_items,
            "skipped_items": skipped_items,
            "status": self.status(),
            "choices": self.choices(),
            "grip_maps": self.grip_maps(),
            "defaults": self.defaults_summary(),
        }
