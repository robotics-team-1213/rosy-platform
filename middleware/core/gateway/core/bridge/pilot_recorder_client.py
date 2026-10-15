"""core.bridge.pilot_recorder_client — requests to the camera unit's recorder (D-411).

Split out of `ros_bridge.py` (D-766): the bridge owns the service clients and
passes one in; these functions only build the request, wait or not, and log a
refusal. Pure transport — the guard decides, CORE stays the only cmd_vel publisher.
"""

from __future__ import annotations

from typing import Callable

from interfaces.srv import PilotRecordingStart
from std_srvs.srv import SetBool

from core.bridge import save_map


def request_active(client, on: bool, wait: bool, warn: Callable[[str], None]) -> tuple[bool, str]:
    """D-411: ask the camera unit's recorder. wait=False from executor callbacks."""
    if not client.service_is_ready():
        return False, ""
    request = SetBool.Request()
    request.data = on
    return _send(client, request, wait, warn)


def request_start(client, preview_mode: str, wait: bool,
                  warn: Callable[[str], None]) -> tuple[bool, str]:
    if not client.service_is_ready():
        return False, ''
    request = PilotRecordingStart.Request()
    request.preview_mode = {'raw': 0, 'annotated': 1}[preview_mode]
    return _send(client, request, wait, warn)


def _send(client, request, wait: bool, warn: Callable[[str], None]) -> tuple[bool, str]:
    future = client.call_async(request)
    if not wait:
        # The guard announces nothing until the recorder's status confirms; log a refusal.
        future.add_done_callback(lambda done: _log_refusal(done, warn))
        return True, ""
    try:
        response = save_map.await_call(future, timeout=3.0)
    except RuntimeError:
        return False, ""
    return bool(response.success), str(response.message)


def _log_refusal(future, warn: Callable[[str], None]) -> None:
    response = future.result() if not future.cancelled() and future.exception() is None else None
    if response is None:
        warn("pilot recorder did not answer a guard stop")
    elif not response.success:
        warn(f"pilot recorder refused a guard stop: {response.message}")
