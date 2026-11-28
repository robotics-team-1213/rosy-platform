#!/usr/bin/env python3
"""Live AI + MuJoCo + Sim-Fleet + Read-Only World closed-loop rehearsal (D-1088 Slice 4A).

Exercises boundary fault injection, live Ollama OpenAI-compatible structured diagnosis
(via ``rosy.decision.structured_output.openai_chat`` over ``/v1/chat/completions``),
cross-venv MuJoCo 3.3.7 stepping, Gazebo Pinky event bridge, real Sim-Fleet FastAPI app, and Read-Only World SSE parity.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable
import urllib.error
import urllib.request

SIM_DIR = Path(__file__).resolve().parent
if str(SIM_DIR) not in sys.path:
    sys.path.insert(0, str(SIM_DIR))

from coupled_gazebo_bridge import (  # noqa: E402
    DEFAULT_S3_LIMITS,
    CoupledGazeboBridge,
    compute_s3_arrival_observation,
)
from coupled_mujoco_bridge import CoupledMujocoBridge, MujocoCellRunner, WallClockPacer  # noqa: E402
from coupled_sim_sandbox import CoupledSimSandbox, _ensure_repo_paths  # noqa: E402

_ensure_repo_paths()
from rosy.decision.structured_output import openai_chat, openai_reply  # noqa: E402

SCHEMA = "rosy.sim.live-loop-receipt.v1"
DIAGNOSIS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["fault_id", "severity", "recommended_action"],
    "properties": {
        "fault_id": {"type": "string"},
        "severity": {"type": "string", "enum": ["hold", "degraded", "nominal"]},
        "recommended_action": {"type": "string"},
    },
}


def make_minimal_world_bundle(root: Path, site_map_sha256: str) -> Path:
    """Create a minimal deterministic Read-Only ROSY World bundle matching ``site_map_sha256``."""
    bundle = root / "world-bundle"
    (bundle / "data").mkdir(parents=True, exist_ok=True)
    (bundle / "index.html").write_text("<html></html>\n", encoding="utf-8", newline="\n")
    (bundle / "SHA256SUMS.txt").write_text("", encoding="utf-8", newline="\n")
    (bundle / "manifest.json").write_text(
        json.dumps({"inputs": {"site-map/world_261026_v7_active.json": {"sha256": site_map_sha256}}}) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (bundle / "data" / "site-map.json").write_text(
        json.dumps({"version": 7, "map": {"map_id": "world_261026", "places": [{"id": "S3", "x": -0.1914, "y": -0.207}], "edges": []}}) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return bundle


def read_world_sse_once(world_url: str, world_id: str = "coupled-sim", timeout_s: float = 4.0) -> dict[str, Any]:
    """Read one live SSE frame from Read-Only ROSY World."""
    url = f"{world_url.rstrip('/')}/sim/stream?world={world_id}&max_events=1"
    with urllib.request.urlopen(url, timeout=timeout_s) as resp:
        event_line = resp.readline().decode("utf-8", errors="replace").strip()
        data_line = resp.readline().decode("utf-8", errors="replace")
    if event_line != "event: state" or not data_line.startswith("data: "):
        raise RuntimeError(f"unexpected SSE frame: {event_line!r} / {data_line!r}")
    return json.loads(data_line[6:])


class OllamaFaultAdvisor:
    """Fail-closed structured AI fault advisor using OpenAI-compatible ``/v1/chat/completions``."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        model: str = "qwen3-vl:8b-instruct",
        timeout_s: float = 45.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = float(timeout_s)

    def __call__(self, summary: dict[str, Any]) -> dict[str, Any]:
        messages = [
            {
                "role": "system",
                "content": (
                    "You are ROSY Fleet supervisor. Diagnose the active simulation boundary fault "
                    "and return compact JSON matching the schema."
                ),
            },
            {"role": "user", "content": json.dumps(summary, ensure_ascii=False, sort_keys=True)},
        ]
        body = openai_chat(
            self.model,
            messages,
            schema=DIAGNOSIS_SCHEMA,
            name="sim_fault_diagnosis",
            max_tokens=512,
        )
        req = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(body, allow_nan=False, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as err:
            raise RuntimeError(f"AI_ADVISOR_UNAVAILABLE: {err}") from err
        return validate_diagnosis(openai_reply(raw, self.model, "INVALID_AI_DIAGNOSIS"))


def validate_diagnosis(payload: Any) -> dict[str, Any]:
    """Enforce fail-closed schema validation after OpenAI envelope decoding."""
    if (
        type(payload) is not dict
        or set(payload) != {"fault_id", "severity", "recommended_action"}
        or not isinstance(payload.get("fault_id"), str)
        or not payload["fault_id"].strip()
        or payload.get("severity") not in {"hold", "degraded", "nominal"}
        or not isinstance(payload.get("recommended_action"), str)
        or not payload["recommended_action"].strip()
    ):
        raise ValueError("INVALID_AI_DIAGNOSIS")
    return payload


def _run_mujoco_step(
    controller_url: str,
    *,
    mujoco_backend: str,
    mujoco_python: str | None,
) -> tuple[dict[str, Any], str]:
    if mujoco_python:
        cmd = [
            str(mujoco_python),
            str(SIM_DIR / "coupled_mujoco_bridge.py"),
            "--controller-url",
            controller_url,
            "--backend",
            "mujoco",
            "--once",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", check=True)
        return json.loads(res.stdout.strip()), "mujoco"
    runner = MujocoCellRunner(backend=mujoco_backend, pacer=WallClockPacer())
    bridge = CoupledMujocoBridge(controller_url, runner=runner, advance_downstream=True)
    return bridge.poll_once(), runner.backend


def _sample_s3_observation() -> dict[str, Any]:
    samples = [
        {"sim_time_s": 10.0 + i * 0.5, "pose_xy_yaw": [-0.1864, -0.197, -1.5508], "linear_m_s": 0.0, "angular_rad_s": 0.0}
        for i in range(4)
    ]
    return compute_s3_arrival_observation(samples, DEFAULT_S3_LIMITS, wall_elapsed_s=1.5)


def run_live_loop_rehearsal(
    *,
    work_dir: Path,
    site_map_sha256: str | None = None,
    mujoco_backend: str = "auto",
    mujoco_python: str | None = None,
    ai_advisor: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Execute fault-hold + AI diagnosis + recovery + nominal closed-loop rehearsal."""
    from fastapi.testclient import TestClient

    sha = site_map_sha256 or hashlib.sha256(b"coupled-sim-live-loop").hexdigest()
    work_dir.mkdir(parents=True, exist_ok=True)
    bundle = make_minimal_world_bundle(work_dir, sha)
    advisor = ai_advisor or (lambda s: {"fault_id": str(s.get("fault_id")), "severity": "hold", "recommended_action": "hold_and_clear"})

    diagnoses: list[dict[str, Any]] = []
    phases: dict[str, Any] = {}
    used_backend = "mujoco" if mujoco_python else mujoco_backend

    with CoupledSimSandbox(work_dir=work_dir / "sandbox", world_bundle_dir=bundle, site_map_sha256=sha) as sb:
        gazebo = CoupledGazeboBridge(sb.sim_url, robot_id="rosy_45")
        obs = _sample_s3_observation()
        assert obs["in_bounds"] and obs["bed_velocity_measured"]

        with TestClient(sb.app) as client:
            fleet_state = client.get("/api/fleet/state", headers=sb.auth_headers)
            fleet_state.raise_for_status()
            fleet_online = fleet_state.json()["fleet"]["online"]
            phases["fleet_online"] = fleet_online
            assert fleet_online == 6

            # Fault 1: pinky.tangled_or_stall
            sb.set_fault("pinky.tangled_or_stall", True, {"robot_id": "rosy_45"})
            clamped = gazebo.filter_cmd_vel(0.25, -0.1)
            assert clamped == (0.0, 0.0)
            diagnoses.append(advisor({"fault_id": "pinky.tangled_or_stall", "cmd_vel": list(clamped), "cargo_state": "ON_PINKY"}))
            sb.set_fault("pinky.tangled_or_stall", False)
            restored = gazebo.filter_cmd_vel(0.25, -0.1)
            assert restored == (0.25, -0.1)
            phases["fault_tangled"] = {"clamped": list(clamped), "restored": list(restored)}

            # Fault 2: arm.usb_unplugged blocks S3 arrival until recovered
            sb.set_fault("arm.usb_unplugged", True, {"arm_id": "arm_s"})
            refused_s3 = gazebo.report_s3_arrival(obs)
            assert refused_s3["accepted"] is False and refused_s3["reason"] == "ARM_USB_UNPLUGGED:arm_s"
            diagnoses.append(advisor({"fault_id": "arm.usb_unplugged", "reply": refused_s3}))
            sb.set_fault("arm.usb_unplugged", False)
            phases["fault_arm_usb"] = refused_s3

            # Nominal S3 handoff -> HANDOFF_AT_S3
            s3_ok = gazebo.report_s3_arrival(obs)
            assert s3_ok["accepted"] is True and s3_ok["cargo_state"] == "HANDOFF_AT_S3"
            phases["s3_arrived"] = s3_ok

            # Fault 3: bridge.seq_conflict_409 holds MuJoCo handoff cleanly, then recovers
            sb.set_fault("bridge.seq_conflict_409", True, {"arm_id": "arm_s"})
            held, _ = _run_mujoco_step(sb.sim_url, mujoco_backend=mujoco_backend, mujoco_python=mujoco_python)
            assert held["action"] == "cargo_lifted_held" and held["cargo_state"] == "HANDOFF_AT_S3"
            assert held["reply"]["status_code"] == 409
            diagnoses.append(advisor({"fault_id": "bridge.seq_conflict_409", "reply": held["reply"]}))
            sb.set_fault("bridge.seq_conflict_409", False)
            phases["fault_bridge_409"] = held["reply"]

            # Phase 2: Full closed-loop recovery to ON_SHIP + departure + Read-Only World SSE
            done, used_backend = _run_mujoco_step(sb.sim_url, mujoco_backend=mujoco_backend, mujoco_python=mujoco_python)
            assert done["cargo_state"] == "ON_SHIP"
            dep = gazebo.check_departure_permission()
            assert dep["permitted"] is True
            sse = read_world_sse_once(sb.world_url, world_id=sb.world_id)
            assert sse["read_only"] is True
            assert sse["parity"]["ok"] is True
            assert sse["cargo"]["state"] == "ON_SHIP"
            assert sse["inconclusive"] is False
            phases["nominal_complete"] = {
                "cargo_state": done["cargo_state"],
                "departure": dep,
                "world_sse_parity_ok": sse["parity"]["ok"],
                "world_sse_read_only": sse["read_only"],
                "world_sse_inconclusive": sse["inconclusive"],
            }

    return {
        "schema": SCHEMA,
        "all_passed": True,
        "mujoco_backend": used_backend,
        "world_parity_ok": True,
        "cargo_state": "ON_SHIP",
        "ai_diagnoses": diagnoses,
        "phases": phases,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--mujoco-backend", default="auto", choices=("auto", "mujoco", "stub"))
    parser.add_argument("--mujoco-python", default=None)
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--ollama-model", default="qwen3-vl:8b-instruct")
    parser.add_argument("--no-ai", action="store_true")
    args = parser.parse_args(argv)

    advisor = None if args.no_ai else OllamaFaultAdvisor(args.ollama_url, args.ollama_model)
    receipt = run_live_loop_rehearsal(
        work_dir=args.work_dir,
        mujoco_backend=args.mujoco_backend,
        mujoco_python=args.mujoco_python,
        ai_advisor=advisor,
    )
    rendered = json.dumps(receipt, indent=2, ensure_ascii=False)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered + "\n", encoding="utf-8", newline="\n")
    print(rendered)
    return 0 if receipt["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
