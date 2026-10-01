"""Record real Gazebo data through Pilot HTTP; prints no pairing code/token."""

import json
import subprocess
import sys
import threading
import time
from uuid import uuid4

from probe_pilot_sim_http import request


def main(container: str) -> None:
    code = subprocess.run(["docker", "exec", container, "cat", "/run/rosy-omx-pilot/pairing-code"],
                          check=True, capture_output=True, text=True).stdout.strip()
    token = request("/pair", method="POST", body={"code": code})["token"]
    seat = request("/seat", method="POST", token=token)["seat_id"]
    stopped = threading.Event()

    def renew():
        while not stopped.wait(0.8):
            request(f"/seat/{seat}", method="PUT", token=token)

    thread = threading.Thread(target=renew, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            state = request("/state", token=token)
            camera = request("/camera", token=token)
            if state["ready"] and camera["fresh"]:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError(f"capture never ready: state={state}, camera={camera}")
        recording = request("/recordings", method="POST", token=token,
                            body={"seat_id": seat, "task": "Gazebo joint1 positive jog demonstration"})
        command_id = str(uuid4())
        state = request("/state", token=token)
        goal = request("/goals", method="POST", token=token, body={
            "instance_id": state["instance_id"], "seat_id": seat, "request_id": command_id,
            "joint": "joint1", "delta_rad": 0.02, "duration_s": 0.4,
            "state_sequence": state["state_sequence"], "expires_at_ms": int(time.time() * 1000) + 5000,
        })
        if goal["state"] not in {"LOCAL_ACCEPTED", "ROS_ACCEPTED", "RUNNING"}:
            raise RuntimeError(f"goal rejected: {goal}")
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            current = request("/recordings", token=token)
            goal = request(f"/goals/{command_id}", token=token)
            if current["status"] != "recording":
                raise RuntimeError(f"recording interrupted: {current}")
            if current["frame_count"] >= 10 and goal["state"] == "SUCCEEDED":
                break
            time.sleep(0.2)
        else:
            raise RuntimeError(f"capture/goal incomplete: {current}, {goal}")
        closed = request(f"/recordings/{recording['episode_id']}/stop", method="POST", token=token,
                         body={"seat_id": seat, "outcome": "success"})
        if closed["status"] != "complete":
            raise RuntimeError(f"source incomplete: {closed}")
        after = request("/state", token=token)
        print(json.dumps({"recording": closed, "goal": goal, "camera": camera,
                          "joint1_before": state["positions"]["joint1"],
                          "joint1_after": after["positions"]["joint1"]}, indent=2))
        request("/recordings", method="POST", token=token,
                body={"seat_id": seat, "task": "Lease expiry must leave incomplete source"})
        stopped.set()
        thread.join(timeout=2)
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            fault = request("/recordings", token=token)
            if fault["status"] == "incomplete":
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("lease expiry did not close the recording")
        if "control_released" not in fault["issues"]:
            raise RuntimeError(f"wrong lease interruption: {fault}")
        print(json.dumps({"lease_expiry_recording": fault}, indent=2))
    finally:
        stopped.set()
        thread.join(timeout=2)
        try:
            request(f"/seat/{seat}", method="DELETE", token=token)
        except RuntimeError as exc:
            if "HTTP 409" not in str(exc):
                raise


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "rosy-omx-recording-sim")
