"""Vision backend validation, camera capture, and measured-fact collection for `cell_vlm_orchestrator`."""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import judge_seat  # noqa: E402
from cell_job_client import CellJobClient, CellJobError  # noqa: E402
from cell_job_spec import AB_ARMS  # noqa: E402

AB_VIEWS = ("top", "side", "arm_a_wrist", "arm_b_wrist")
_CLI_PROVIDERS = ("cli", "opencode", "codex", "claude")
_HTTP_CHAT_PROVIDERS = ("zai", "glm", "openai", "http", "vllm", "litellm", "openrouter")
_VISION_TAGS = ("vl", "vision", "4v", "gpt-4o", "claude-3", "gemini")


def _validate_vision_spec(spec) -> None:
    if spec is None:
        raise ValueError("a vision backend is required for VLM orchestration")
    if callable(spec):
        name = getattr(spec, "__name__", "")
        if name.startswith(("opencode:", "codex:", "claude:")):
            raise ValueError(f"text-only CLI backend {name!r} cannot inspect camera frames")
        return
    if isinstance(spec, (list, tuple)):
        items = [item for item in spec if item is not None]
        if not items:
            raise ValueError("a vision backend is required for VLM orchestration")
        for item in items:
            _validate_vision_spec(item)
        return
    if isinstance(spec, str):
        s = spec.strip()
        lower = s.lower()
        if lower.startswith(("opencode:", "codex:", "claude:")):
            raise ValueError(f"text-only CLI provider {s!r} cannot inspect camera frames")
        if lower.startswith(("zai:", "glm:", "openai:")) or lower.startswith("glm"):
            model = s.split(":", 1)[1] if ":" in s else s
            if not any(tag in model.lower() for tag in _VISION_TAGS):
                raise ValueError(f"non-vision HTTP chat model {s!r} cannot inspect camera frames")
        return
    if not isinstance(spec, dict):
        raise ValueError(f"unsupported backend spec: {spec!r}")
    if "models" in spec or "profiles" in spec:
        items = [item for item in (spec.get("models") or spec.get("profiles") or ()) if item is not None]
        if not items:
            raise ValueError("a vision backend is required for VLM orchestration")
        for item in items:
            _validate_vision_spec(item)
        if spec.get("arbiter") is not None:
            _validate_vision_spec(spec["arbiter"])
        return
    provider = str(spec.get("provider", "ollama")).lower()
    if provider in _CLI_PROVIDERS:
        raise ValueError(f"text-only CLI provider {provider!r} cannot inspect camera frames")
    if spec.get("vision") is False:
        raise ValueError("vision=False backend cannot inspect camera frames")
    if provider in _HTTP_CHAT_PROVIDERS:
        model = str(spec.get("model", "")).lower()
        if spec.get("vision") is not True and not any(tag in model for tag in _VISION_TAGS):
            raise ValueError(f"HTTP chat backend {provider}:{model or '?'} requires vision=True or a vision model")


def select_vision_backend(spec_or_fn):
    """Build or validate a vision-capable backend; reject text-only CLI and non-vision specs."""
    _validate_vision_spec(spec_or_fn)
    backend = judge_seat.from_config(spec_or_fn)
    if backend is judge_seat.rules or backend is None:
        raise ValueError("a vision backend is required for VLM orchestration")
    return backend


def parse_last_json(text: str) -> dict | None:
    """Parse the trailing JSON dict from multi-line or log-prefixed job output."""
    stripped = (text or "").strip()
    if not stripped:
        return None
    decoder, start = json.JSONDecoder(), stripped.find("{")
    while start != -1:
        try:
            value, end = decoder.raw_decode(stripped, start)
        except ValueError:
            value = None
        else:
            if isinstance(value, dict) and not stripped[end:].strip():
                return value
        start = stripped.find("{", start + 1)
    return None


def query_incident(client: CellJobClient, arm: str, *, poll_s: float = 0.2, timeout_s: float = 30.0) -> dict:
    """Read `incident_status` for one arm; fail closed (`held=True`) on errors or unsent outbox."""
    try:
        started = client.start("incident_status", {"arm": arm})
        res = client.wait(started["id"], poll_s=poll_s, timeout_s=timeout_s)
    except (CellJobError, TimeoutError, OSError) as exc:
        return {"arm": arm, "held": True, "exit": None, "reason": f"incident_status failed: {exc}", "raw": None}
    parsed = parse_last_json(res.get("log", ""))
    if res.get("exit") != 0 or parsed is None:
        return {"arm": arm, "held": True, "exit": res.get("exit"), "reason": "unreadable incident_status", "raw": parsed}
    local_held = parsed.get("local_held") is True
    fleet_held = parsed.get("fleet_held")
    unsent = parsed.get("unsent_outbox") or 0
    held = bool(local_held or fleet_held is True or unsent > 0)
    reason = parsed.get("local_reason") or parsed.get("fleet_reason") or ("unsent outbox" if held else "")
    return {"arm": arm, "held": held, "exit": res.get("exit"), "reason": reason, "raw": parsed}


def collect_measured_facts(
    client: CellJobClient,
    arm_configs: dict[str, dict] | None = None,
    *,
    arms: tuple[str, ...] = tuple(sorted(AB_ARMS)),
    run_dry_pick: bool = True,
    poll_s: float = 0.2,
) -> dict:
    """Measure arm hold status and optional serial `auto_pick_dry_run` observations before VLM planning."""
    incidents = {arm: query_incident(client, arm, poll_s=poll_s) for arm in arms}
    available = [arm for arm in arms if not incidents[arm]["held"]]
    dry_pick = {}
    if run_dry_pick and arm_configs:
        for arm in available:
            cfg = arm_configs.get(arm) or {}
            if not all(k in cfg for k in ("config", "catalog", "roi")):
                continue
            source, dest = cfg.get("source", "belt"), cfg.get("dest", "pallet")
            try:
                started = client.start(
                    "auto_pick_dry_run",
                    {
                        "config": cfg["config"],
                        "catalog": cfg["catalog"],
                        "roi": cfg["roi"],
                        "source": source,
                        "dest": dest,
                        "purpose": f"facts:{arm}",
                    },
                )
                res = client.wait(started["id"], poll_s=poll_s, timeout_s=60.0)
                parsed = parse_last_json(res.get("log", "")) or {}
                attempts = parsed.get("attempts") if isinstance(parsed.get("attempts"), list) else []
                first = attempts[0] if attempts and isinstance(attempts[0], dict) else {}
                dry_pick[arm] = {
                    "exit": res.get("exit"),
                    "source": source,
                    "dest": dest,
                    "result": parsed.get("result"),
                    "observed": first.get("observed"),
                    "chosen": first.get("chosen"),
                    "refused_count": len(first.get("refused") or ()),
                }
            except (CellJobError, TimeoutError, OSError) as exc:
                dry_pick[arm] = {"source": source, "dest": dest, "error": str(exc)}
    return {"incidents": incidents, "dry_pick": dry_pick, "available_arms": available}


def collect_frames(client: CellJobClient, views: tuple[str, ...] = AB_VIEWS) -> tuple[list[str], list[str]]:
    """Fetch available non-empty JPEG frames from `cell_job_api` as base64 strings."""
    images_b64, captured = [], []
    for view in views:
        try:
            raw = client.frame(view)
        except CellJobError as exc:
            if exc.status_code == 404:
                continue
            raise
        if not raw:
            continue
        images_b64.append(base64.b64encode(raw).decode("ascii"))
        captured.append(view)
    return images_b64, captured
