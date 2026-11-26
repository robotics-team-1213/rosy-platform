"""Auto-release of an arm incident hold without a person round trip (panel 2026-11-27 verdict C, D-1047).

Two entry points, one judge. Both run omx_incident_pipeline.run_pipeline(apply=True): the 95 score, every hard veto and the
24 h clear counter stay exactly as they are; a latch, a cable wind-up or a held object still goes to a person.
  after_torque_off(arm)   cell_torque_off_folded.py, once torque is OFF and caps are verified: a motionless folded
                          torque-0 re-read (ArmIncidentRemeasure) is the evidence (rule torque_off_folded_remeasure).
  before_refusal(arms..)  cell_job_api, just before it answers ARM_INCIDENT_HELD: one pipeline run per arm per
                          COOLDOWN_S (rule precheck_auto_clear).
Who released (the rule id) and the measured values go to the Fleet clear note, incidents/auto-release.jsonl and
release.json beside the incident record. The 24 h counter still counts only the pipeline's own auto_clear row.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))

RULE_AFTER_TORQUE_OFF = "torque_off_folded_remeasure"
RULE_BEFORE_REFUSAL = "precheck_auto_clear"
COOLDOWN_S = 10.0
_last: dict[str, float] = {}


class _Skip(Exception):
    """A person is required: the pipeline is not run."""
_lock = threading.Lock()


def cell_config(arm: str) -> Path | None:
    """The arm's own cell config (arm_id, plan_path) from the auto-fold settings, or None: no motionless re-read then."""
    try:
        import omx_incident_auto

        cfg = json.loads(omx_incident_auto._auto_fold_config().read_text(encoding="utf-8")).get(arm)
        path = Path(cfg["cwd"]).expanduser() / cfg["config"]
        return path if path.is_file() else None
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def summary(block) -> str:
    """The measured values of one re-read, short enough for a Fleet clear note."""
    if not isinstance(block, dict):
        return "no re-read"
    total = lambda key: sum(v for v in (block.get(key) or {}).values() if isinstance(v, int))  # noqa: E731
    return (f"torque={total('torque_after')} hw_error={total('hardware_error')} folded={block.get('folded')} "
            f"home_err={block.get('max_home_err')} stable={block.get('stable')}")


def human_only(arm: str) -> str | None:
    """Why a machine must not release this arm even when the pipeline could (verdict C: latch, cable wind-up, object in the
    jaws and a home recovery stay with a person), else None. Unreadable facts pass: the pipeline then fails closed itself."""
    try:
        import omx_incident_fleet
        import omx_incident_pipeline

        omx_incident_pipeline._ensure_core_common()
        from core_common.protocol.arm_incident.arm_incidents import held_facts, remeasure_kind
        from core_common.protocol.arm_incident.home_recovery import HOME_RECOVERY_REASON

        if omx_incident_fleet.held(arm) == HOME_RECOVERY_REASON:
            return "home recovery required"
        path = omx_incident_pipeline._latest_incident_file(arm)
        loaded = json.loads(path.read_text(encoding="utf-8")) if path else None
        facts = loaded.get("facts", loaded) if isinstance(loaded, dict) else None
        if not isinstance(facts, dict):
            return None
        if facts.get("latched"):
            return "latched hardware error"
        if facts.get("windup_hits") or remeasure_kind(facts) == "wind-up before the end":
            return "wind-up or snag (cable)"
        if held_facts(facts):
            return "object held in the jaws"
    except (SystemExit, Exception):
        return None
    return None


def _reassess(arm, config):
    import omx_incident_reassess

    return omx_incident_reassess.reassess(arm, config)


def _record(arm: str, rule: str, result: dict, measured: str, now: float) -> None:
    """Append the audit row; when the incident was cleared also write release.json beside its incident record. Never raises."""
    try:
        import omx_incident_fleet

        row = {"t": round(now, 3), "arm": arm, "rule": rule, "cleared": bool(result.get("cleared")),
               "incident_id": result.get("incident_id"), "safety_score": result.get("safety_score"),
               "decision": result.get("decision"), "measured": measured, "why": str(result.get("why"))[:200],
               "hard_vetoes": [v.get("code") for v in result.get("hard_vetoes") or [] if isinstance(v, dict)]}
        path = omx_incident_fleet.incidents_dir() / "auto-release.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, default=str) + "\n")
        if row["cleared"] and result.get("incident_file"):
            Path(result["incident_file"]).with_name("release.json").write_text(json.dumps(row, default=str, indent=1), encoding="utf-8")
    except Exception:  # a lost note must never change what the arm does
        pass


def evaluate(arm: str, rule: str, *, pipeline=None, config="auto", clear_fn=None, reassess_fn=None, now_fn=time.time) -> dict:
    """One guarded pipeline run for `arm` (apply). Never raises; {cleared, why, rule, measured, ...} either way."""
    seen: dict = {}

    def reassess(a, c):
        seen["block"] = (reassess_fn or _reassess)(a, c)
        return seen["block"]

    def clear(a, note, *args, **kwargs):
        if clear_fn is None:
            import omx_incident

            real = omx_incident.clear
        else:
            real = clear_fn
        return real(a, f"{note[:250]} [rule={rule}; {summary(seen.get('block'))}]"[:400], *args, **kwargs)

    now = now_fn()
    try:
        if why := human_only(arm):
            result = {"cleared": False, "why": f"person required: {why}"}
            raise _Skip
        cfg = cell_config(arm) if config == "auto" else config
        if pipeline is None:
            import omx_incident_pipeline

            pipeline = omx_incident_pipeline.run_pipeline
        result, _ = pipeline(arm, config=cfg, reassess=cfg is not None, apply=True, reassess_fn=reassess, clear_fn=clear)
    except _Skip:
        pass
    except (SystemExit, Exception) as exc:  # fail closed: the hold stays
        result = {"cleared": False, "why": f"{type(exc).__name__}: {str(exc)[:120]}"}
    measured = summary(seen.get("block"))
    if result.get("status") != "no_open_incident":  # nothing was held: nothing to audit
        _record(arm, rule, result, measured, now)
    return {**result, "rule": rule, "measured": measured}


def after_torque_off(arm: str, **kwargs) -> dict:
    """cell_torque_off_folded.py: torque OFF and baseline caps are confirmed on a folded arm; re-read and release by rule."""
    return evaluate(arm, RULE_AFTER_TORQUE_OFF, **kwargs)


def before_refusal(arms, check, *, enabled: bool = True, evaluate_fn=None, now_fn=time.monotonic) -> None:
    """cell_job_api: for each held arm, one evaluation per COOLDOWN_S so the request that would be refused can go on.
    The caller checks the hold again afterwards; a hold that stays is refused exactly as before."""
    if not enabled:
        return
    for arm in arms:
        try:
            from core_common.protocol.arm_incident.home_recovery import HOME_RECOVERY_REASON

            reason = check(arm)
            if not reason or reason == HOME_RECOVERY_REASON:  # a home recovery is its own job, never a release
                continue
            with _lock:
                now = now_fn()
                if arm in _last and now - _last[arm] < COOLDOWN_S:
                    continue
                _last[arm] = now
            (evaluate_fn or evaluate)(arm, RULE_BEFORE_REFUSAL)
        except (SystemExit, Exception):  # the caller's own hold check decides
            continue
