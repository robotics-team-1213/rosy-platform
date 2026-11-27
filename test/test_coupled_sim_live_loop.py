"""Regression tests for live closed-loop rehearsal & OpenAI-compatible AI advisor (D-1088 Slice 4A)."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading

import pytest

ROOT = Path(__file__).resolve().parents[1]
SIM_DIR = ROOT / "tools" / "sim"
if str(SIM_DIR) not in sys.path:
    sys.path.insert(0, str(SIM_DIR))

import coupled_sim_live_loop as csll  # noqa: E402


def test_run_live_loop_rehearsal_stub_and_diagnoses(tmp_path: Path) -> None:
    seen: list[str] = []

    def _advisor(summary: dict) -> dict:
        fid = str(summary["fault_id"])
        seen.append(fid)
        return {"fault_id": fid, "severity": "hold", "recommended_action": f"clear:{fid}"}

    receipt = csll.run_live_loop_rehearsal(work_dir=tmp_path / "live", mujoco_backend="stub", ai_advisor=_advisor)
    assert receipt["schema"] == csll.SCHEMA
    assert receipt["all_passed"] is True
    assert receipt["world_parity_ok"] is True
    assert receipt["mujoco_backend"] == "stub"
    assert receipt["phases"]["nominal_complete"]["world_sse_inconclusive"] is False
    assert receipt["cargo_state"] == "ON_SHIP"
    assert seen == ["pinky.tangled_or_stall", "arm.usb_unplugged", "bridge.seq_conflict_409"]
    assert len(receipt["ai_diagnoses"]) == 3


def test_ollama_fault_advisor_openai_compatible_and_fail_closed() -> None:
    valid_content = json.dumps({"fault_id": "arm.usb_unplugged", "severity": "hold", "recommended_action": "reconnect_usb"})
    mode: dict[str, object] = {"status": 200, "envelope": None, "content": valid_content}

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: object) -> None:  # noqa: A003
            return

        def do_POST(self) -> None:  # noqa: N802
            assert self.path == "/v1/chat/completions"
            length = int(self.headers.get("Content-Length") or 0)
            req = json.loads(self.rfile.read(length).decode("utf-8"))
            assert req["model"] == "qwen3-vl:8b-instruct"
            if mode["status"] != 200:
                self.send_response(int(mode["status"]))  # type: ignore[arg-type]
                self.end_headers()
                self.wfile.write(b"{}")
                return
            payload = mode["envelope"] if mode["envelope"] is not None else {
                "model": "qwen3-vl:8b-instruct",
                "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": mode["content"]}}],
            }
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        advisor = csll.OllamaFaultAdvisor(f"http://127.0.0.1:{srv.server_port}", "qwen3-vl:8b-instruct")
        reply = advisor({"fault_id": "arm.usb_unplugged"})
        assert reply == {"fault_id": "arm.usb_unplugged", "severity": "hold", "recommended_action": "reconnect_usb"}

        for bad_content in (
            "not-json",
            json.dumps([]),
            json.dumps({"fault_id": "arm.usb_unplugged", "severity": "hold"}),
            json.dumps({"fault_id": "   ", "severity": "hold", "recommended_action": "ok"}),
            json.dumps({"fault_id": "arm.usb_unplugged", "severity": "hold", "recommended_action": "   "}),
            json.dumps({"fault_id": "arm.usb_unplugged", "severity": "hold", "recommended_action": "ok", "extra": 1}),
            json.dumps({"fault_id": "arm.usb_unplugged", "severity": "panic", "recommended_action": "ok"}),
        ):
            mode["envelope"] = None
            mode["content"] = bad_content
            with pytest.raises(ValueError, match="INVALID_AI_DIAGNOSIS"):
                advisor({"fault_id": "arm.usb_unplugged"})

        for bad_envelope in (
            {"bad": 1},
            {"model": "other-model", "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": valid_content}}]},
            {"model": "qwen3-vl:8b-instruct", "choices": []},
            {"model": "qwen3-vl:8b-instruct", "choices": [{"finish_reason": "length", "message": {"role": "assistant", "content": valid_content}}]},
            {"model": "qwen3-vl:8b-instruct", "choices": [{"finish_reason": "stop", "message": {"role": "user", "content": valid_content}}]},
            {"model": "qwen3-vl:8b-instruct", "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": valid_content, "tool_calls": [{"id": "1"}]}}]},
        ):
            mode["envelope"] = bad_envelope
            with pytest.raises(ValueError, match="INVALID_AI_DIAGNOSIS"):
                advisor({"fault_id": "arm.usb_unplugged"})

        mode["envelope"] = None
        mode["status"] = 500
        with pytest.raises(RuntimeError, match="AI_ADVISOR_UNAVAILABLE"):
            advisor({"fault_id": "arm.usb_unplugged"})
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=2)
