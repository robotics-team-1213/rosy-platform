"""Fleet hold ledger, outbox transport, evidence sidecar upload, and operator clear helpers for `omx_incident.py`."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import time
from pathlib import Path

INCIDENTS = Path("incidents")


def incidents_dir() -> Path:
    """The one place holds and the outbox live (under the cell's lock root, not the recording directory)."""
    from joint_tune import lock_root

    return lock_root() / "incidents"


def hold_path(arm: str) -> Path:
    return incidents_dir() / f"HOLD-{arm}.json"


def hold_file(arm: str) -> Path | None:
    """The hold file of `arm` that exists: here, else one an older version left in the working directory."""
    return next((p for p in (hold_path(arm), INCIDENTS / f"HOLD-{arm}.json") if p.is_file()), None)


def outbox(arm: str) -> list[Path]:
    """Unsent reports: this cell's outbox plus any an older version left in the working directory."""
    return sorted(incidents_dir().joinpath("outbox").glob(f"{arm}-*.json")) + sorted(
        (INCIDENTS / "outbox").glob(f"{arm}-*.json")
    )


def held(arm: str) -> str | None:
    """Why the next session of `arm` must not start according to the local copy of the hold, or None."""
    path = hold_file(arm)
    return json.loads(path.read_text())["reason"] if path else None


def keep_hold(arm: str, reason: str, incident_ids=(), source="local") -> None:
    hold_path(arm).parent.mkdir(parents=True, exist_ok=True)
    hold_path(arm).write_text(
        json.dumps(
            {
                "reason": reason,
                "incident_ids": list(incident_ids),
                "source": source,
                "since": time.strftime("%Y%m%dT%H%M%S"),
            }
        )
    )


def _bridge_environ() -> dict[str, str]:
    env = dict(os.environ)
    if env.get("ROSY_WORKCELL_OBSERVATIONS"):
        return env
    env_path = env.get("ROSY_OBSERVATION_BRIDGE_ENV")
    cfg_dir = Path.home() / ".config/rosy"
    candidates = (
        [Path(env_path)]
        if env_path
        else (
            [cfg_dir / "omx-observation-bridge.env", cfg_dir / "omx-arm-status.env"]
            if not env.get("ROSY_OMX_HOME")
            else []
        )
    )
    for candidate in candidates:
        if candidate.is_file():
            for raw in candidate.read_text(encoding="utf-8", errors="replace").splitlines():
                line = raw.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return env


def link_for(arm: str):
    """The Fleet channel of this arm from the environment, or None (not configured or not usable here)."""
    here = Path(__file__).resolve()
    for extra in (here.parents[3] / "contracts/foundation", here.parents[3] / "operations/overhead"):
        if extra.is_dir() and str(extra) not in sys.path:
            sys.path.append(str(extra))
    env = _bridge_environ()
    try:
        from workcell_observation_bridge import ArmIncidentLink

        return ArmIncidentLink.from_environment(arm, env)
    except (ImportError, OSError, ValueError) as exc:
        if arm in (env.get("ROSY_ARM_STATUS_ARM_ID"), env.get("ROSY_ARM_STATUS_SOURCE_ID")) and env.get("ROSY_ARM_S_TOKEN"):
            try:
                import ssl
                from workcell_observation_bridge import ArmIncidentLink

                return ArmIncidentLink(
                    env["ROSY_ARM_STATUS_FLEET_URL"],
                    env["ROSY_ARM_STATUS_SOURCE_ID"],
                    env["ROSY_ARM_S_TOKEN"],
                    context=ssl.create_default_context(cafile=env.get("ROSY_ARM_STATUS_CA_FILE") or None),
                )
            except (ImportError, OSError, ValueError) as inner_exc:
                exc = inner_exc
        print(f"fleet incident link unavailable: {type(exc).__name__}: {str(exc)[:120]}")
        return None


def label_box(arm: str) -> list[Path]:
    """Unsent label-only reports (a guard stop a person names the cause of): they never hold the arm or block a session."""
    return sorted(incidents_dir().joinpath("labels").glob(f"{arm}-*.json"))


_NON_HOLD_SUFFIXES = (
    "reported for a person's cause, the arm is not held",
    "with the arm folded on its command; nothing physical held it",
)


def _effectively_held(answer) -> bool:
    """True when Fleet's hold answer reflects a holding incident (guards against pre-2026-11-08/09 Fleet servers that
    returned held=True for a single non-holding label or folded software-stop report)."""
    if answer is None or not answer.held:
        return False
    reason = str(answer.reason or "").strip()
    if reason.startswith("1 open arm incident(s):") and reason.endswith(_NON_HOLD_SUFFIXES):
        return False
    return True


def evidence_of(since: float) -> dict | None:
    """The newest stop bundle (cell_evidence) of this session: its jaw-tip crops, then whole frames from 3 s before on,
    at most ARM_INCIDENT_EVIDENCE_FRAMES; {"bundle", "files"} or None."""
    from core_common.protocol.arm_incidents import ARM_INCIDENT_EVIDENCE_FRAMES

    bundles = [p for p in sorted((INCIDENTS / "evidence").glob("*-stop")) if p.stat().st_mtime >= since]
    if not bundles:
        return None
    manifest = json.loads((bundles[-1] / "manifest.json").read_text())
    tips = [f["file"] for f in manifest["files"] if f["file"].endswith("-tip.jpg")]
    whole = [
        f["file"]
        for f in sorted(manifest["files"], key=lambda f: f.get("t_rel_s", 0))
        if "camera" in f and f["t_rel_s"] >= -3
    ]
    return {"bundle": str(bundles[-1]), "files": (tips + whole)[:ARM_INCIDENT_EVIDENCE_FRAMES]}


def upload_evidence(sidecar: Path, reply, link) -> None:
    """Best effort, after the report: a frame Fleet did not take is left out, never resent and never a hold."""
    from core_common.protocol.arm_incidents import ArmIncidentEvidenceFrame

    if not sidecar.is_file():
        return
    try:
        chosen = json.loads(sidecar.read_text())
        listed = {f["file"]: f for f in json.loads((Path(chosen["bundle"]) / "manifest.json").read_text())["files"]}
        for name in chosen["files"]:
            try:
                data, tip = (Path(chosen["bundle"]) / name).read_bytes(), name.endswith("-tip.jpg")
                link.post_evidence(
                    reply.incident_id,
                    ArmIncidentEvidenceFrame(
                        camera=listed.get(name, {}).get("camera") or name.removesuffix("-tip.jpg"),
                        t_rel_s=listed.get(name, {}).get("t_rel_s", 0.0),
                        kind="tip" if tip else "full",
                        sha256=hashlib.sha256(data).hexdigest(),
                        jpeg_b64=base64.b64encode(data).decode(),
                    ),
                )
            except Exception as exc:
                print(f"evidence {name} not sent: {type(exc).__name__}: {str(exc)[:120]}")
    except Exception as exc:
        print(f"evidence of {sidecar.name} not sent: {type(exc).__name__}: {str(exc)[:120]}")
    finally:
        sidecar.unlink(missing_ok=True)


def send(arm: str, link, paths=None) -> bool:
    """Resend the unsent reports of `arm` (each file leaves the outbox only once Fleet accepted it), then their evidence."""
    from core_common.protocol.arm_incidents import ArmIncidentReport

    for path in outbox(arm) if paths is None else paths:
        try:
            report = ArmIncidentReport.model_validate_json(path.read_text())
            reply = link.post(report.model_copy(update={"source_id": link.source_id}))
        except Exception as exc:
            print(f"incident report {path.name} not sent: {type(exc).__name__}: {str(exc)[:120]}")
            return False
        path.unlink()
        upload_evidence(path.with_name(path.stem + ".evidence"), reply, link)
        if _effectively_held(reply.hold):
            keep_hold(arm, reply.hold.reason or "arm incident not cleared", reply.hold.incident_ids, "fleet")
    return True


def report_for(source_id: str, session_id: str, f: dict, d: dict, acted):
    """The Fleet report: measured facts without local paths, the decision, the device recovery, up to two frames."""
    from core_common.protocol.arm_incidents import ARM_INCIDENT_FRAME_BYTES, ArmIncidentReport

    plain = lambda value: json.loads(json.dumps(value, default=str))  # noqa: E731
    shown = {k: v for k, v in f.items() if k not in ("frames", "fault_records")}
    shown["windup_hits"] = shown["windup_hits"][:5]
    shown["fault_records"] = [Path(p).name for p in f["fault_records"]][-3:]
    frames = []
    for path in f["frames"]:
        data = Path(path).read_bytes() if Path(path).is_file() else b""
        if data[:2] == b"\xff\xd8" and len(data) <= ARM_INCIDENT_FRAME_BYTES:
            frames.append(
                {
                    "role": Path(path).stem.rsplit("-", 1)[-1],
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "jpeg_b64": base64.b64encode(data).decode(),
                }
            )
    body = {
        "source_id": source_id,
        "session_id": session_id,
        "decision": plain(d),
        "recovery": plain(acted),
        "frames": frames,
    }
    try:
        return ArmIncidentReport.model_validate({**body, "facts": plain(shown)})
    except ValueError:
        keep = {k: shown[k] for k in ("safe_end", "latched", "torque_after", "folded") if k in shown}
        return ArmIncidentReport.model_validate({**body, "facts": plain({**keep, "truncated": True})})


def default_token_file() -> Path | None:
    """Discover the single operator bearer token in ~/.config/rosy/*-operator-*.token when not passed explicitly.
    D-1039: an AI assessor's own token is named by ROSY_ARM_ASSESSOR_TOKEN_FILE, outside that glob."""
    for name in ("ROSY_OPERATOR_TOKEN_FILE", "ROSY_ARM_ASSESSOR_TOKEN_FILE"):
        if os.environ.get(name):
            return Path(os.environ[name]).expanduser()
    cfg_dir = Path.home() / ".config/rosy"
    matches = sorted(cfg_dir.glob("*-operator-*.token")) if cfg_dir.is_dir() else []
    return matches[0] if len(matches) == 1 else None


def clear_incidents(arm, note, token_file=None, link=None, *, cause=None, basis=None, token=None, refuse_fn=None) -> int:
    """Clear every open incident of one arm using explicit Core JWT or 0600 operator token file, then lift local hold."""
    if not note.strip():
        raise SystemExit("a note of what was checked is required")
    if token is None:
        token_file = token_file or default_token_file()
        if token_file is None or not Path(token_file).is_file():
            raise SystemExit("an operator --token-file (chmod 600) is required")
        token_file = Path(token_file)
        if token_file.stat().st_mode & 0o077:
            raise SystemExit(f"{token_file} must be readable by its owner only (chmod 600)")
        token = token_file.read_text(encoding="utf-8").strip()
    link = link or link_for(arm)
    if link is None:
        raise SystemExit(f"{arm}: no Fleet channel configured on this PC (source the observation bridge env)")
    answer = link.hold()
    cleared = list(answer.incident_ids)
    for incident_id in cleared:
        if cause is not None or basis is not None:
            try:
                answer = link.clear(incident_id, note, token, cause=cause, basis=basis)
            except OSError as exc:
                if getattr(exc, "code", None) != 422:
                    raise
                answer = link.clear(incident_id, note, token)
        else:
            answer = link.clear(incident_id, note, token)
    print(json.dumps({"arm": arm, "cleared": cleared, "held": answer.held,
                      **({"cause": cause} if cause else {}), **({"basis": basis} if basis else {})}))
    if refuse_fn is not None:
        refuse_fn(arm, link)
    return 0


def verify_baseline_caps(device: str) -> bool:
    """Read-only bus confirmation that every follower motor is fault-free, torque OFF, and at baseline caps."""
    from joint_tune import BASELINE, FOLLOWER, SerialBus

    time.sleep(0.3)
    bus = None
    try:
        bus = SerialBus(device, 0)
        for motor, (exp_model, exp_mode) in FOLLOWER.items():
            bus.motor = motor
            if (bus.cleanup_read("model"), bus.cleanup_read("mode")) != (exp_model, exp_mode):
                return False
            if bus.cleanup_read("torque") != 0 or bus.cleanup_read("hw_error") != 0:
                return False
            if bus.cleanup_read("pwm_limit") != BASELINE["pwm_limit"]:
                return False
            if exp_model == 1200 and bus.cleanup_read("current_limit") != BASELINE["current_limit"]:
                return False
        return True
    except Exception:
        return False
    finally:
        if bus is not None:
            try:
                bus.close()
            except Exception:
                pass
