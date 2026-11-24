#!/usr/bin/env python3
"""Structured cell-side incident risk evaluation and guarded auto-clear pipeline (safety_score >= 95)."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import omx_incident_auto  # noqa: E402
import omx_incident_fleet  # noqa: E402

SCHEMA = "rosy.omx-incident-risk-pipeline.v1"
RECENT_WINDOW_S = 86400.0


def _ensure_core_common() -> None:
    here = Path(__file__).resolve()
    if len(here.parents) > 3:
        extra = here.parents[3] / "contracts" / "foundation"
        if extra.is_dir() and str(extra) not in sys.path:
            sys.path.append(str(extra))


def _incident_roots() -> list[Path]:
    roots = [omx_incident_fleet.incidents_dir(), omx_incident_fleet.INCIDENTS]
    out, seen = [], set()
    for root in roots:
        try:
            key = str(root.resolve())
        except OSError:
            key = str(root)
        if key not in seen:
            seen.add(key)
            out.append(root)
    return out


def _latest_incident_file(arm: str) -> Path | None:
    found: list[Path] = []
    for root in _incident_roots():
        if root.is_dir():
            found.extend(root.glob(f"*-{arm}/incident.json"))
    return max(found, key=lambda p: p.parent.name, default=None)


def _read_motor_health(arm: str, explicit_path: Path | None) -> tuple[dict | None, str | None]:
    if explicit_path is not None:
        try:
            return json.loads(Path(explicit_path).read_text(encoding="utf-8")), None
        except (OSError, ValueError) as exc:
            return None, f"motor_health unreadable: {type(exc).__name__}: {exc}"
    mh_dir = os.environ.get("ROSY_OMX_MOTOR_HEALTH_DIR")
    base = Path(mh_dir).expanduser() if mh_dir else (Path.home() / ".local" / "state" / "rosy" / "motor-health")
    candidate = base / f"{arm}.json"
    if not candidate.is_file():
        return None, None
    try:
        return json.loads(candidate.read_text(encoding="utf-8")), None
    except (OSError, ValueError) as exc:
        return None, f"motor_health unreadable: {type(exc).__name__}: {exc}"


def _count_recent_clears_24h(arm: str, now_s: float) -> int:
    seen_lines: set[str] = set()
    count = 0
    cutoff = now_s - RECENT_WINDOW_S
    for root in _incident_roots():
        log_path = root / "auto-events.jsonl"
        if not log_path.is_file():
            continue
        for raw in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line in seen_lines:
                continue
            seen_lines.add(line)
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if (
                isinstance(ev, dict)
                and ev.get("arm") == arm
                and ev.get("kind") == "auto_clear"
                and ev.get("result") is True
                and isinstance(ev.get("t"), (int, float))
                and float(ev["t"]) >= cutoff
            ):
                count += 1
    return count


def _note_risk_event(row: dict, now_s: float) -> None:
    """Append full structured risk verdict to incidents_dir()/risk-events.jsonl. Never raises."""
    try:
        path = omx_incident_fleet.incidents_dir() / "risk-events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({**row, "t": round(now_s, 3)}, default=str) + "\n")
    except Exception:
        pass


def _default_reassess(arm: str, config: str | Path) -> dict:
    import omx_incident_reassess

    return omx_incident_reassess.reassess(arm, config)


def _default_camera_check(arm: str) -> dict:
    import cell_clear_check
    import judge_seat

    viewer = os.environ.get("ROSY_VIEWER_URL", "http://127.0.0.1:8767")
    model_url = os.environ.get("ROSY_JUDGE_URL", "http://127.0.0.1:11434")
    model = os.environ.get("ROSY_JUDGE_MODEL", "qwen3-vl:8b-instruct")

    def fetch(view: str) -> bytes:
        import urllib.request

        req = urllib.request.Request(f"{viewer}/frame/{view}.jpg", headers={"Host": "127.0.0.1:8767"})
        with urllib.request.urlopen(req, timeout=10) as reply:
            return reply.read()

    return cell_clear_check.check(arm, fetch, judge_seat.ollama(model_url, model, timeout=60))


def run_pipeline(
    arm: str,
    *,
    config: str | Path | None = None,
    incident_file: Path | None = None,
    motor_health_file: Path | None = None,
    camera_check_file: Path | None = None,
    apply: bool = False,
    reassess: bool = False,
    camera_check: bool = False,
    min_score: int = 95,
    link=None,
    clear_fn=None,
    reassess_fn=None,
    camera_check_fn=None,
    now_fn=time.time,
) -> tuple[dict, int]:
    """Run the 5-stage deterministic safety evaluation and only apply AI assessor clear when score >= 95."""
    _ensure_core_common()
    from core_common.protocol.arm_incident.arm_incident_risk import AUTO_CLEAR_MIN_SCORE, evaluate_clear_safety

    if isinstance(min_score, bool) or not isinstance(min_score, int) or not (AUTO_CLEAR_MIN_SCORE <= min_score <= 100):
        raise ValueError("min_score must be an integer in [95, 100]")

    now_s = float(now_fn())
    link_obj = link if link is not None else omx_incident_fleet.link_for(arm)
    stage_errors: list[str] = []
    stage_vetoes: list[tuple[str, str]] = []
    try:
        local_reason = omx_incident_fleet.held(arm)
    except Exception as exc:
        local_reason = f"local hold unreadable: {type(exc).__name__}"
        stage_errors.append(local_reason)
        stage_vetoes.append(("HOLD_UNREADABLE", local_reason))

    fleet_held = None
    fleet_ids: list[str] = []
    if link_obj is not None:
        try:
            ans = link_obj.hold()
            fleet_held = omx_incident_fleet._effectively_held(ans)
            fleet_ids = list(ans.incident_ids)
        except Exception as exc:
            err = f"fleet hold unavailable: {type(exc).__name__}: {str(exc)[:120]}"
            stage_errors.append(err)
            stage_vetoes.append(("FLEET_HOLD_UNREADABLE", err))

    has_open_hold = bool(local_reason) or bool(fleet_held) or (incident_file is not None)
    if not has_open_hold and not stage_errors:
        result = {
            "schema": SCHEMA, "arm": arm, "status": "no_open_incident", "threshold": min_score,
            "safety_score": 100, "risk_score": 0, "allowed": False, "decision": "noop",
            "cleared": False, "applied": False, "incident_id": None, "incident_file": None,
            "hard_vetoes": [], "deductions": [], "stage_errors": [],
            "why": "no open local or Fleet hold",
        }
        return result, 0

    src_path = Path(incident_file) if incident_file is not None else _latest_incident_file(arm)
    facts, recovery, since = None, None, None
    if src_path is not None and src_path.is_file():
        try:
            loaded = json.loads(src_path.read_text(encoding="utf-8"))
            facts = loaded.get("facts", loaded) if isinstance(loaded, dict) else None
            raw_rec = loaded.get("recovery") if isinstance(loaded, dict) else None
            recovery = raw_rec if isinstance(raw_rec, dict) and raw_rec.get("kind") == "auto_fold" else None
            if isinstance(loaded, dict):
                since = loaded.get("reported_at") or loaded.get("t") or src_path.stat().st_mtime
        except (OSError, ValueError) as exc:
            err = f"incident unreadable: {type(exc).__name__}: {str(exc)[:120]}"
            stage_errors.append(err)
            stage_vetoes.append(("INCIDENT_UNREADABLE", err))
    else:
        stage_errors.append("no local incident record found")

    incident_id = fleet_ids[0] if fleet_ids else None
    motor_health, mh_err = _read_motor_health(arm, motor_health_file)
    if mh_err:
        stage_errors.append(mh_err)
        stage_vetoes.append(("MOTOR_HEALTH_UNREADABLE", mh_err))
    recent_clears = _count_recent_clears_24h(arm, now_s)

    remeasured = None
    binding = None
    if reassess:
        if config is None:
            err = "reassess requested without --config"
            stage_errors.append(err)
            stage_vetoes.append(("REASSESS_FAILED", err))
        else:
            try:
                remeasured = (reassess_fn or _default_reassess)(arm, config)
                if isinstance(remeasured, dict):
                    if incident_id and not remeasured.get("incident_id"):
                        remeasured = {**remeasured, "incident_id": incident_id}
                    if isinstance(remeasured.get("board_serial"), str):
                        binding = (arm, remeasured["board_serial"])
            except (SystemExit, Exception) as exc:
                err = f"reassess failed: {type(exc).__name__}: {str(exc)[:120]}"
                stage_errors.append(err)
                stage_vetoes.append(("REASSESS_FAILED", err))

    cam_payload = None
    if camera_check_file is not None:
        try:
            cam_payload = json.loads(Path(camera_check_file).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            cam_payload = {"unavailable": True, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}
            stage_errors.append(f"camera_check_file unreadable: {type(exc).__name__}")
    elif camera_check:
        try:
            cam_payload = (camera_check_fn or _default_camera_check)(arm)
        except Exception as exc:
            cam_payload = {"unavailable": True, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}
            stage_errors.append(f"camera_check unavailable: {type(exc).__name__}: {str(exc)[:120]}")

    try:
        risk = evaluate_clear_safety(
            facts, remeasured=remeasured, recovery=recovery, camera_check=cam_payload,
            motor_health=motor_health, recent_clears_24h=recent_clears,
            since=since, now=now_s, incident_id=incident_id, binding=binding, min_score=min_score,
        )
    except Exception as exc:
        stage_errors.append(f"evaluate_clear_safety error: {type(exc).__name__}: {str(exc)[:120]}")
        risk = {
            "threshold": min_score, "safety_score": 0, "risk_score": 100, "allowed": False,
            "decision": "escalate_human", "clear_path": "none", "policy_reason": f"rule error: {type(exc).__name__}",
            "hard_vetoes": [{"code": "RULE_ERROR", "detail": str(exc)[:120]}], "deductions": [],
            "signals": {"recent_clears_24h": recent_clears, "camera_checked": False,
                        "motor_health_checked": isinstance(motor_health, dict),
                        "remeasured": remeasured is not None, "auto_fold": recovery is not None},
        }
    seen_vetoes = {v["code"] for v in risk["hard_vetoes"]}
    for code, detail in stage_vetoes:
        if code not in seen_vetoes:
            risk["hard_vetoes"].append({"code": code, "detail": detail})
            seen_vetoes.add(code)
    if stage_vetoes:
        risk["safety_score"] = 0
        risk["risk_score"] = 100
        risk["allowed"] = False
        risk["decision"] = "escalate_human"

    cleared = False
    clear_why = risk["policy_reason"]
    exit_code = 0 if risk["allowed"] else 2
    if apply and risk["allowed"]:
        if len(fleet_ids) > 1 and incident_id is not None:
            clear_res = {"cleared": False, "why": f"multiple open incidents ({len(fleet_ids)}); refuse bulk clear"}
        else:
            clear_res = omx_incident_auto.auto_clear(
                arm, facts or {}, link_obj, clear_fn=clear_fn,
                remeasured=remeasured, recovery=recovery, camera_check=cam_payload,
                motor_health=motor_health, recent_clears_24h=recent_clears,
                since=since, now=now_s, incident_id=incident_id, binding=binding,
                min_score=min_score, only=incident_id,
            )
        cleared = bool(clear_res.get("cleared"))
        clear_why = str(clear_res.get("why") or clear_why)
        omx_incident_auto.note_auto_clear(arm, {**clear_res, "incident_id": incident_id})
        exit_code = 0 if cleared else 1
    elif apply:
        omx_incident_auto.note_event({
            "kind": "auto_clear", "arm": arm, "incident_id": incident_id, "result": False,
            "why": f"score={risk['safety_score']}/{risk['threshold']} ({risk['decision']}): {clear_why}"[:200],
        })

    _note_risk_event({
        "schema": SCHEMA, "arm": arm, "incident_id": incident_id, "apply": bool(apply), "cleared": cleared,
        "safety_score": risk["safety_score"], "risk_score": risk["risk_score"], "threshold": risk["threshold"],
        "decision": risk["decision"], "hard_vetoes": risk["hard_vetoes"], "deductions": risk["deductions"],
        "why": clear_why,
    }, now_s)

    result = {
        "schema": SCHEMA, "arm": arm, "status": "evaluated",
        "threshold": risk["threshold"], "safety_score": risk["safety_score"], "risk_score": risk["risk_score"],
        "allowed": risk["allowed"], "decision": risk["decision"], "cleared": cleared, "applied": bool(apply),
        "incident_id": incident_id, "incident_file": str(src_path) if src_path else None,
        "clear_path": risk["clear_path"], "hard_vetoes": risk["hard_vetoes"], "deductions": risk["deductions"],
        "signals": risk["signals"], "stage_errors": stage_errors, "why": clear_why,
    }
    return result, exit_code


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--arm", required=True)
    ap.add_argument("--config", type=Path)
    ap.add_argument("--incident-file", type=Path)
    ap.add_argument("--motor-health-file", type=Path)
    ap.add_argument("--camera-check-file", type=Path)
    ap.add_argument("--apply", action="store_true", help="only clear via AI assessor when safety_score >= min_score")
    ap.add_argument("--reassess", action="store_true", help="run motionless register remeasure (requires --config)")
    ap.add_argument("--camera-check", action="store_true", help="run camera obstruction check before clearing")
    ap.add_argument("--min-score", type=int, default=95, help="minimum safety score [95..100] required to auto-clear")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    result, code = run_pipeline(
        args.arm, config=args.config, incident_file=args.incident_file,
        motor_health_file=args.motor_health_file, camera_check_file=args.camera_check_file,
        apply=args.apply, reassess=args.reassess, camera_check=args.camera_check,
        min_score=args.min_score,
    )
    text = json.dumps(result, ensure_ascii=False, indent=1)
    if args.out is not None:
        if not args.out.is_absolute():
            cur = Path(".")
            for part in args.out.parts:
                cur = cur / part
                if cur.is_symlink():
                    raise SystemExit(f"refusing symlink out path: {cur}")
        elif args.out.is_symlink():
            raise SystemExit(f"refusing symlink out path: {args.out}")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return code


if __name__ == "__main__":
    sys.exit(main())
