"""Record real Gazebo data through Pilot HTTP; prints no pairing code/token."""

import json
import sys
import threading
import time
from probe_pilot_sim_http import Probe, pairing_code, request


def main(container: str) -> None:
    code = pairing_code(container, time.monotonic() + 120)
    token = request("/pair", method="POST", body={"code": code})["token"]
    seat = request("/seat", method="POST", token=token)["seat_id"]
    stopped = threading.Event()
    renew_errors = []

    def check_renewal():
        if renew_errors:
            raise RuntimeError("seat renewal failed; recording is not verified") from renew_errors[0]

    def renew():
        while not stopped.wait(0.8):
            try:
                request(f"/seat/{seat}", method="PUT", token=token)
            except Exception as exc:
                renew_errors.append(exc)
                stopped.set()

    thread = threading.Thread(target=renew, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            check_renewal()
            state = request("/state", token=token)
            camera = request("/camera", token=token)
            if state["ready"] and camera["fresh"]:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError(f"capture never ready: state={state}, camera={camera}")
        recording = request("/recordings", method="POST", token=token,
                            body={"seat_id": seat, "task": "Gazebo joint1 positive jog demonstration"})
        state = request("/state", token=token)
        result = Probe(token, seat, stop=stopped).run_jog("joint1", 0.02)
        goal = result["goal"]
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            check_renewal()
            current = request("/recordings", token=token)
            if current["status"] != "recording":
                raise RuntimeError(f"recording interrupted: {current}")
            if current["frame_count"] >= 10 and goal["state"] == "SUCCEEDED":
                break
            time.sleep(0.2)
        else:
            raise RuntimeError(f"capture/goal incomplete: {current}, {goal}")
        check_renewal()
        closed = request(f"/recordings/{recording['episode_id']}/stop", method="POST", token=token,
                         body={"seat_id": seat, "outcome": "success"})
        if closed["status"] != "complete":
            raise RuntimeError(f"source incomplete: {closed}")
        after = result["state"]
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
