#!/usr/bin/env python3
"""Emit `rosy.omx-failure-context.v1` bundles for non-placed `cell_auto_pick`, `cell_policy_drive` and `cell_policy_run` (which calls the drive) exits (D-1072)."""
from __future__ import annotations

import json
import math
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_evidence as ev  # noqa: E402
import cell_failure_context as cfc  # noqa: E402
from cell_job_validators import _is_amr_bed_site  # noqa: E402


def resolve_bundle_root(config: dict[str, Any] | None = None) -> Path:
    if isinstance(config, dict) and config.get("failure_bundle_root"):
        return Path(str(config["failure_bundle_root"])).expanduser()
    return cfc.default_bundle_root()


def arm_and_cell(config: dict[str, Any]) -> tuple[str, str]:
    arm = str(config.get("arm_id") or "arm_s")
    if arm not in ("arm_s", "arm_a", "arm_b"):
        arm = "arm_s"
    return arm, ("cell_s" if arm == "arm_s" else "cell_ab")


def _read_state_gen(work: Path, config: dict[str, Any]) -> int:
    cfg_work = Path(str(config.get("work_dir") or work)).expanduser()
    for base in dict.fromkeys((work, work.parent, cfg_work, cfg_work.parent)):
        p = base / "cell-job-api" / "cell-state-gen.json"
        if p.is_file():
            try:
                val = json.loads(p.read_text(encoding="utf-8")).get("cell_state_gen", 0)
                if isinstance(val, int) and not isinstance(val, bool) and val >= 0:
                    return val
            except (OSError, ValueError):
                pass
    return 0


def _read_live_json(config: dict[str, Any]) -> dict[str, Any]:
    io_raw = config.get("io")
    if not io_raw:
        return {}
    p = Path(str(io_raw)).expanduser() / "live.json"
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _read_jsonl_tail(path: Path, limit: int = 5) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            if isinstance(row, dict):
                out.append(row)
        except ValueError:
            pass
    return out


def _clamp_depth(value: Any, max_d: int = 2) -> Any:
    if max_d <= 0:
        if isinstance(value, (dict, list)):
            return str(value)[:120]
        return value
    if isinstance(value, dict):
        return {str(k): _clamp_depth(v, max_d - 1) for k, v in list(value.items())[:24]}
    if isinstance(value, list):
        return [_clamp_depth(v, max_d - 1) for v in value[:12]]
    if isinstance(value, float) and not (value == value and abs(value) != float("inf")):
        return None
    if isinstance(value, str) and len(value) > 200:
        return value[:200]
    return value


def _collect_visual_assets(cell, config: dict[str, Any], ring, tips: dict[str, Any], state_vec, at_s: float) -> tuple[dict[str, Any], dict[str, bytes]]:
    cameras = config.get("cameras") or {}
    missing = set(str(c) for c in (config.get("missing_cameras") or []))
    manifest: dict[str, Any] = {}
    assets: dict[str, bytes] = {}
    frames_meta: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    ring_frames, ring_gaps = ring.window_with_meta(at_s - getattr(ring, "keep_s", ev.KEEP_S)) if ring is not None else ([], [])
    for t_val, cam, why in ring_gaps:
        gaps.append({"camera": str(cam), "t_rel_s": round(float(t_val) - at_s, 2), "why": str(why)[:120]})

    raw_by_cam: dict[str, list[dict[str, Any]]] = {}
    for rf in ring_frames:
        raw_by_cam.setdefault(str(rf["camera"]), []).append(rf)

    receipt_fn = getattr(cell, "frame_receipt", None)
    for cam in sorted(set(cameras) | missing):
        if cam in missing:
            manifest[cam] = {"status": "missing_device", "required_for_mode": True, "error": "device absent"}
            continue
        cam_rows = raw_by_cam.get(cam, [])
        if not cam_rows and cell is not None:
            try:
                if callable(receipt_fn):
                    rec = receipt_fn(cam)
                    jpeg = rec.get("jpeg_bytes")
                    if jpeg is None and rec.get("image") is not None:
                        import cv2

                        ok, enc = cv2.imencode(".jpg", rec["image"], [cv2.IMWRITE_JPEG_QUALITY, 80])
                        jpeg = enc.tobytes() if ok else None
                    if jpeg:
                        cam_rows = [{"t": float(rec.get("captured_at") or at_s), "camera": cam, "jpeg": bytes(jpeg), "source_seq": rec.get("source_seq"), "source_stamp": rec.get("source_stamp")}]
                        raw_by_cam[cam] = cam_rows
                elif hasattr(cell, "frame"):
                    import cv2

                    ok, enc = cv2.imencode(".jpg", cell.frame(cam), [cv2.IMWRITE_JPEG_QUALITY, 80])
                    if ok:
                        cam_rows = [{"t": at_s, "camera": cam, "jpeg": enc.tobytes(), "source_seq": None, "source_stamp": None}]
                        raw_by_cam[cam] = cam_rows
            except Exception as exc:
                gaps.append({"camera": cam, "t_rel_s": 0.0, "why": str(exc)[:120]})
        if cam_rows:
            last_row = cam_rows[-1]
            raw_stamp = last_row.get("source_stamp")
            stamp = float(raw_stamp) if isinstance(raw_stamp, (int, float)) and not isinstance(raw_stamp, bool) and math.isfinite(raw_stamp) and raw_stamp >= 0.0 else None
            raw_seq = last_row.get("source_seq")
            seq = raw_seq if isinstance(raw_seq, int) and not isinstance(raw_seq, bool) and raw_seq >= 0 else None
            age = max(0.0, at_s - stamp) if stamp is not None else None
            manifest[cam] = {
                "status": "ok",
                "required_for_mode": cam in ("top", "side"),
                "source_seq": seq,
                "source_stamp": stamp,
                "age_at_stop_s": round(age, 3) if age is not None else None,
            }
        else:
            manifest[cam] = {"status": "error", "required_for_mode": cam in ("top", "side"), "error": "no fresh frame"}

    tip_imgs = dict(tips or {})
    if not tip_imgs and config.get("tip_view") and isinstance(state_vec, (list, tuple)) and len(state_vec) >= 5:
        try:
            import cv2
            import numpy as np
            import cell_tip_view

            decoded = {}
            for cam, rows in raw_by_cam.items():
                arr = cv2.imdecode(np.frombuffer(rows[-1]["jpeg"], np.uint8), cv2.IMREAD_COLOR)
                if arr is not None:
                    decoded[cam] = arr
            if decoded:
                tip_imgs = cell_tip_view.tip_crops(decoded, cell_tip_view.fk_tip(state_vec), config["tip_view"])
        except Exception:
            tip_imgs = {}
    for cam, img in sorted(tip_imgs.items()):
        if cam in missing:
            continue
        try:
            import cv2

            ok, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if ok:
                fname = f"{cam}-tip.jpg"
                assets[fname] = enc.tobytes()
                frames_meta.append({"id": f"tip-{cam}", "file": fname, "camera": cam, "kind": "tip_crop", "t_rel_s": 0.0, "bytes": 1, "sha256": "0" * 64})
        except Exception:
            pass

    ring_cams = {str(r["camera"]) for r in ring_frames}
    combined = list(ring_frames) + [
        row for cam, rows in sorted(raw_by_cam.items()) if cam not in ring_cams for row in rows
    ]
    wrist_first = sorted(combined, key=lambda r: ("wrist" not in str(r["camera"]), float(r["t"])))
    for idx, rf in enumerate(wrist_first):
        if len(frames_meta) >= 24:
            break
        cam = str(rf["camera"])
        if cam in missing:
            continue
        fname = f"{cam}-{idx:02d}.jpg"
        assets[fname] = rf["jpeg"]
        raw_t = rf.get("t")
        t_rel = round(float(raw_t) - at_s, 2) if isinstance(raw_t, (int, float)) and not isinstance(raw_t, bool) and math.isfinite(raw_t) else 0.0
        entry: dict[str, Any] = {
            "id": f"f-{idx:02d}-{cam}",
            "file": fname,
            "camera": cam,
            "kind": "at",
            "t_rel_s": t_rel,
            "bytes": 1,
            "sha256": "0" * 64,
        }
        raw_seq = rf.get("source_seq")
        if isinstance(raw_seq, int) and not isinstance(raw_seq, bool) and raw_seq >= 0:
            entry["source_seq"] = raw_seq
        raw_stamp = rf.get("source_stamp")
        if isinstance(raw_stamp, (int, float)) and not isinstance(raw_stamp, bool) and math.isfinite(raw_stamp) and raw_stamp >= 0.0:
            entry["source_stamp"] = float(raw_stamp)
        frames_meta.append(entry)
    return {"camera_manifest": manifest, "frames": frames_meta[:24], "gaps": gaps[:24], "control_ref": None, "depth_summary": None}, assets


def _emit_common(
    *,
    cell,
    config: dict[str, Any],
    work: Path,
    kind: str,
    executor_mode: str,
    attempt_cause: str,
    stage: str,
    result_text: str,
    ring=None,
    tips: dict[str, Any] | None = None,
    state_vec: list | None = None,
    correlation: dict[str, Any] | None = None,
    spatial: dict[str, Any] | None = None,
    extra_meas: dict[str, Any] | None = None,
) -> str | None:
    try:
        arm_id, cell_id = arm_and_cell(config)
        at_s = time.time()
        live = _read_live_json(config)
        if state_vec is None and isinstance(live.get("state"), list):
            state_vec = live["state"]
        visual, assets = _collect_visual_assets(cell, config, ring, tips or {}, state_vec, at_s)
        arm_id_val = arm_id
        tail = ev.trace_tail(arm_id_val, search_dir=work) or ev.trace_tail(arm_id_val)
        trace_ref = None
        if tail:
            assets["trace-tail.jsonl"] = tail
            trace_ref = {"id": "trace-tail", "file": "trace-tail.jsonl", "kind": "trace", "bytes": 1, "sha256": "0" * 64}
        home = (config.get("plan") or {}).get("home") or config.get("home")
        home_err = (round(max(abs(float(a) - float(b)) for a, b in zip(state_vec[:5], home[:5])), 2)
                    if isinstance(state_vec, list) and len(state_vec) >= 5 and isinstance(home, list) and len(home) >= 5 else None)
        folded = live.get("folded") if live.get("folded") is not None else (None if home_err is None else home_err <= cfc.HOME_POSE_TOL_UNITS)
        from cell_job_peer_health import is_stale_row
        if folded is True and is_stale_row(live, 15.0):
            folded = None  # an old row never says folded now; an old False stays, it only vetoes
        meas: dict[str, Any] = {
            "outcome": {"result": result_text[:200], "attempt_cause": attempt_cause[:80], "stage": stage[:60]},
            "kinematics_and_health": {"last_state": state_vec[:6] if isinstance(state_vec, list) else None, **({"max_home_err_units": home_err} if home_err is not None else {})},
            "holding_and_fold": {"live_fold": {"folded": folded}},
        }
        if trace_ref is not None:
            meas["trace_ref"] = trace_ref
        if extra_meas:
            meas.update({k: _clamp_depth(v, 3) for k, v in extra_meas.items()})
        gen = {"cell_state_gen": _read_state_gen(work, config)}
        attempts_tail = [_clamp_depth(r, 2) for r in _read_jsonl_tail(work / "attempts.jsonl", 3)]
        decisions_tail = [_clamp_depth(r, 1) for r in _read_jsonl_tail(work / "decisions.jsonl", 5)]
        why_tail = [_clamp_depth(r, 1) for r in _read_jsonl_tail(work / "why.jsonl", 3)]
        bid = f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime(at_s))}-{arm_id_val}-{kind}-{uuid.uuid4().hex[:6]}"
        bundle = cfc.build_bundle(
            kind=kind, arm_id=arm_id_val, cell_id=cell_id, executor_mode=executor_mode, bundle_id=bid, created_at_s=at_s,
            correlation=_clamp_depth(correlation or {}, 1), generation=gen, measurement=_clamp_depth(meas, 4),
            spatial=_clamp_depth(spatial or {}, 4), visual=visual,
            history={
                "recent_attempts": attempts_tail, "recent_decisions": decisions_tail, "recent_why": why_tail,
                "repeat_unknown_tripped": any(bool(w.get("repeat_unknown")) for w in why_tail if isinstance(w, dict)),
            },
        )
        root = resolve_bundle_root(config)
        pinned: set[str] = set()
        for ref_dir in (work, root.parent / "incidents"):
            if not ref_dir.is_dir():
                continue
            for cand in [ref_dir / "attempts.pending.json", *ref_dir.glob("HOLD-*.json")]:
                try:
                    data = json.loads(cand.read_text(encoding="utf-8"))
                    if isinstance(data, dict) and isinstance(data.get("failure_bundle_id"), str):
                        pinned.add(data["failure_bundle_id"])
                except (OSError, ValueError):
                    pass
        cfc.write_bundle(root, bundle, assets, pinned_bundle_ids=pinned)
        return str(bundle["bundle_id"])
    except Exception as exc:
        sys.stderr.write(f"cell_bundle_emit failed: {type(exc).__name__}: {str(exc)[:160]}\n")
        return None


def emit_pick_failure(cell, config: dict[str, Any], calibration: dict[str, Any], source: str, dest: str,
                      work: Path, result: dict[str, Any], tried: dict[str, Any], *, stills=None, gate=None,
                      executor_mode: str = "ik_auto_pick") -> str | None:
    if stills is not None:
        stills.close()
    res_str, moved, fail = str(result.get("result") or "stopped"), (tried.get("transfer") or {}), (tried.get("fail") or {})
    kind = "fault" if moved.get("result") == "fault" else "refusal" if res_str.startswith(("held:", "refused")) else "verify_fail" if "verify" in str(fail.get("stage") or "") or res_str.endswith("unverified") else "stop"
    cause = str(moved.get("result") or (tried.get("diagnosis") or {}).get("cause") or fail.get("class") or "unknown")
    steps = moved.get("steps") or []
    last_state = next((s.get("state") for s in reversed(steps) if isinstance(s.get("state"), list)), None)
    corr = {"source": source, "dest": dest, "fleet_task_id": config.get("_fleet_task") or None, "scenario_id": tried.get("scenario_id")}
    spat = {
        "sites": {"source": source, "dest": dest, "is_amr_bed": any(_is_amr_bed_site(s) for s in (source, dest))},
        "calibration": {"missing_map": [s for s in (source, dest) if s not in ((calibration or {}).get("sites") or {})]},
        "perception": {"verify": _clamp_depth(tried.get("verify"), 1), "zone_verification": _clamp_depth(tried.get("zone_verification"), 1)},
    }
    mode = executor_mode if executor_mode in ("ik_auto_pick", "recovery") else "ik_auto_pick"
    return _emit_common(
        cell=cell, config=config, work=work, kind=kind, executor_mode=mode,
        attempt_cause=cause, stage=str(fail.get("stage") or moved.get("at") or "auto_pick"),
        result_text=res_str, ring=getattr(stills, "ring", None), tips=getattr(stills, "last_tips", None),
        state_vec=last_state, correlation=corr, spatial=spat,
        extra_meas={"compensation": tried.get("compensation")},
    )


class PolicyCapture:
    """Background `cell_evidence.Ring` + `CellFailureContext` emitter outside the timed policy loop."""

    def __init__(self, cell, config: dict[str, Any], *, work: Path, mode: str, paced_chunks: bool, dry_run: bool, log_path: Path, site: str | None = None, goal_site: str | None = None, dest_site: str | None = None):
        self.cell, self.config, self.work = cell, config, Path(work)
        self.mode, self.paced_chunks, self.dry_run, self.log_path = mode, paced_chunks, dry_run, Path(log_path)
        self._site, self._goal_site, self._dest_site = site, goal_site, dest_site
        self.ring = None

    def __enter__(self) -> "PolicyCapture":
        if not self.dry_run and self.config.get("evidence") is not False and self.config.get("cameras"):
            ev_cfg = self.config.get("evidence") if isinstance(self.config.get("evidence"), dict) else {}
            self.ring = ev.Ring(
                self.cell.frame, self.config["cameras"], ev_cfg.get("period_s", ev.PERIOD_S),
                ev_cfg.get("keep_s", ev.KEEP_S), frame_receipt=getattr(self.cell, "frame_receipt", None),
            )
        return self

    def emit_if_failed(self, result: dict[str, Any]) -> str | None:
        if self.dry_run:
            return None
        ok = result.get("result") in ("released", "chunks_done", "dry_run", "placed") and result.get("parked") is not False
        if ok:
            return None
        if self.ring is not None:
            self.ring.close()
        exec_mode = "act_paced" if (self.mode == "act" and self.paced_chunks) else "act_timed" if self.mode == "act" else self.mode
        res_name = str(result.get("result") or "policy_fail")
        kind = "fault" if res_name == "fault" else "policy_fail"
        tail_rows = [_clamp_depth(r, 1) for r in _read_jsonl_tail(self.log_path, 5)]
        state_vec = next((r.get("end_state") or r.get("state") for r in reversed(tail_rows) if isinstance(r.get("end_state") or r.get("state"), list)), None)
        sites = {"source": self._site, "dest": self._dest_site or self._goal_site, "is_amr_bed": any(_is_amr_bed_site(s) for s in (self._site, self._goal_site, self._dest_site) if s)}
        return _emit_common(
            cell=self.cell, config=self.config, work=self.work, kind=kind, executor_mode=exec_mode,
            attempt_cause=str(result.get("reason") or res_name), stage=f"chunk:{result.get('at', 0)}",
            result_text=f"{res_name}: {result.get('reason') or ''}", ring=self.ring, state_vec=state_vec,
            correlation={"fleet_task_id": self.config.get("_fleet_task") or None, "mode": self.mode},
            spatial={"sites": sites},
            extra_meas={"policy_log_tail": tail_rows},
        )

    def __exit__(self, *_exc) -> None:
        if self.ring is not None:
            self.ring.close()


def emit_two_arm_policy_failure(
    cells: Mapping[str, Any], configs: Mapping[str, dict[str, Any]], work: Path,
    receipt: Mapping[str, Any], tasks: Mapping[str, Mapping[str, Any]], revisions: Mapping[str, str],
) -> str | None:
    """Emit a `rosy.omx-failure-context.v1` bundle for a non-dry-run two-arm policy refusal or fault."""
    if receipt.get("dry_run") or receipt.get("result") in ("dry_run", "chunks_done", "released"):
        return None
    stopped = str(receipt.get("stopped_reason") or "")
    arms_rep = receipt.get("arms") if isinstance(receipt.get("arms"), Mapping) else {}
    arm_key = next((k for k in ("a", "b") if stopped.startswith((f"{k}:", f"{k} "))), None) or next(
        (k for k in ("a", "b") if isinstance(arms_rep.get(k), Mapping) and arms_rep[k].get("outcome") in ("fault", "refused")),
        "a",
    )
    site_vals = [tasks[k].get(f) for k in ("a", "b") if isinstance(tasks.get(k), Mapping) for f in ("src", "dst")]
    return _emit_common(
        cell=cells.get(arm_key), config={**configs[arm_key], "arm_id": f"arm_{arm_key}"}, work=work,
        kind="fault" if receipt.get("result") == "fault" else "policy_fail", executor_mode="act_timed",
        attempt_cause=stopped or str(receipt.get("result") or "policy_fail"),
        stage=str(receipt.get("task_id") or "two_arm_policy"), result_text=f"{receipt.get('result')}: {stopped}",
        correlation={
            "task_id": receipt.get("task_id"), "policy_revision": revisions.get(arm_key),
            "peer_revision": revisions.get("b" if arm_key == "a" else "a"),
            "proposer": receipt.get("proposer"), "operator": receipt.get("operator"),
        },
        spatial={"sites": {
            "source": (tasks.get(arm_key) or {}).get("src"), "dest": (tasks.get(arm_key) or {}).get("dst"),
            "is_amr_bed": any(_is_amr_bed_site(str(v)) for v in site_vals if v),
        }},
        extra_meas={"arms": dict(arms_rep), "park": receipt.get("park")},
    )
