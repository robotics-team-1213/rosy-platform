"""One-shot host probe of an already running, isolated Pilot Gazebo container.

Consumes the container's one-time pairing code. Prints no code or token.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4


BASE = "http://127.0.0.1:8088/api/v1/sim/omx"


def request(path: str, *, method: str = "GET", token: str = "", body=None):
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.load(response) if response.status != 204 else None
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"{path}: HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}") from exc


def main(container: str) -> int:
    deadline = time.monotonic() + 1800
    code = None
    while time.monotonic() < deadline:
        if container == "--inside":
            path = Path("/run/rosy-omx-pilot/pairing-code")
            if path.is_file():
                code = path.read_text(encoding="utf-8").strip()
        else:
            result = subprocess.run(["docker", "exec", container, "cat", "/run/rosy-omx-pilot/pairing-code"],
                                    capture_output=True, text=True)
            if result.returncode == 0 and result.stdout.strip():
                code = result.stdout.strip()
        if code:
            break
        time.sleep(1)
    if code is None:
        raise RuntimeError("pairing code did not appear")
    while time.monotonic() < deadline:
        try:
            request("/target")
            break
        except (OSError, ConnectionError):
            time.sleep(1)
    else:
        raise RuntimeError("Pilot HTTP target did not become available")
    token = request("/pair", method="POST", body={"code": code})["token"]
    code = None
    seat = request("/seat", method="POST", token=token)["seat_id"]
    stop = threading.Event()
    renew_errors = []

    def renew():
        while not stop.wait(0.8):
            try:
                request(f"/seat/{seat}", method="PUT", token=token)
            except Exception as exc:
                renew_errors.append(str(exc))
                if "HTTP 409" in str(exc) or "HTTP 401" in str(exc):
                    stop.set()

    thread = threading.Thread(target=renew, daemon=True)
    thread.start()
    try:
        while time.monotonic() < deadline and not stop.is_set():
            state = request("/state", token=token)
            if state["ready"]:
                break
            time.sleep(1)
        else:
            raise RuntimeError(f"SIM never ready: owner={state['owner_state']}, "
                               f"seq={state['state_sequence']}, age_ms={state['joint_age_ms']}, "
                               f"action_server_ready={state.get('action_server_ready')}, "
                               f"last_renew_error={renew_errors[-1] if renew_errors else 'none'}")
        def ready_state():
            until = time.monotonic() + 30
            while time.monotonic() < until and not stop.is_set():
                current = request("/state", token=token)
                if current["ready"]:
                    return current
                time.sleep(0.2)
            raise RuntimeError("owner did not return to ready between goals")

        def run_goal(joint: str, delta: float):
            current = ready_state()
            before = current["positions"][joint]
            command_id = str(uuid4())
            goal = request("/goals", method="POST", token=token, body={
                "instance_id": current["instance_id"], "seat_id": seat,
                "request_id": command_id, "joint": joint, "delta_rad": delta,
                "duration_s": 0.4, "state_sequence": current["state_sequence"],
                "expires_at_ms": int(time.time() * 1000) + 5000,
            })
            print(f"{joint}_submit={goal['state']}")
            if goal["state"] != "LOCAL_ACCEPTED":
                raise RuntimeError(f"{joint} local command was not accepted")
            finish = time.monotonic() + 60
            while time.monotonic() < finish and not stop.is_set():
                goal = request(f"/goals/{command_id}", token=token)
                if goal["state"] in {"SUCCEEDED", "REJECTED", "CANCELED", "UNKNOWN_HOLD"}:
                    break
                time.sleep(0.2)
            after_state = request("/state", token=token)
            after = after_state["positions"].get(joint)
            print(f"{joint}_goal={goal['state']} reason={goal.get('reason', '')} "
                  f"ros_id_present={bool(goal.get('ros_goal_id'))} "
                  f"before={before:.4f} after={after:.4f} owner={after_state['owner_state']}")
            moved = None if after is None else after - before
            tolerance = 0.015 if joint == "gripper_joint_1" else 0.01
            if (goal["state"] != "SUCCEEDED" or moved is None or moved * delta <= 0
                    or abs(moved) < 0.005 or abs(moved - delta) > tolerance):
                raise RuntimeError(f"{joint} ROS action or independent readback did not meet probe")

        run_goal("joint1", 0.02)
        run_goal("gripper_joint_1", 0.02)

        current = ready_state()
        cancel_id = str(uuid4())
        submitted = request("/goals", method="POST", token=token, body={
            "instance_id": current["instance_id"], "seat_id": seat,
            "request_id": cancel_id, "joint": "joint1", "delta_rad": 0.05,
            "duration_s": 1.0, "state_sequence": current["state_sequence"],
            "expires_at_ms": int(time.time() * 1000) + 5000,
        })
        if submitted["state"] != "LOCAL_ACCEPTED":
            raise RuntimeError("cancel probe goal was not accepted")
        canceled = request(f"/goals/{cancel_id}/cancel?seat_id={seat}", method="POST", token=token)
        print(f"cancel_request={canceled['state']}")
        if canceled["state"] != "CANCEL_REQUESTED":
            raise RuntimeError("cancel request was not accepted")
        finish = time.monotonic() + 30
        while time.monotonic() < finish:
            canceled = request(f"/goals/{cancel_id}", token=token)
            if canceled["state"] in {"CANCELED", "UNKNOWN_HOLD"}:
                break
            time.sleep(0.2)
        print(f"cancel_terminal={canceled['state']} ros_id_present={bool(canceled.get('ros_goal_id'))}")
        if canceled["state"] != "CANCELED":
            raise RuntimeError("ROS cancel terminal readback was not observed")
        return 0
    finally:
        stop.set()
        thread.join(timeout=2)
        try:
            request(f"/seat/{seat}", method="DELETE", token=token)
        except Exception:
            pass


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "rosy-omx-pilot-sim"))
    except Exception as exc:
        print(f"probe failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
