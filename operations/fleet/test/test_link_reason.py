"""D-535: the console names why a robot read failed with the shared reason codes."""

import errno
import socket
import ssl

import httpx

from fleet.server.console_view import link_reason
from fleet.swarm.transport import RobotApiError


def _wrapped(cause):
    try:
        try:
            raise cause
        except BaseException as inner:
            raise httpx.ConnectError("connect failed") from inner
    except httpx.ConnectError as outer:
        return outer


def _verify(code):
    error = ssl.SSLCertVerificationError("certificate verify failed")
    error.verify_code = code
    return error


def test_transport_failures_get_reasons():
    assert link_reason(None, scheme="https") is None
    cases = [
        (_wrapped(socket.gaierror(11001, "getaddrinfo failed")), "ROBOT_UNREACHABLE"),
        (_wrapped(ConnectionRefusedError(errno.ECONNREFUSED, "refused")), "CORE_NOT_READY"),
        (_wrapped(_verify(62)), "TLS_NAME_MISMATCH"),
        (_wrapped(_verify(20)), "CA_UNKNOWN"),
        (httpx.ReadTimeout("slow"), "ROBOT_UNREACHABLE"),
    ]
    for exc, code in cases:
        reason = link_reason(exc, scheme="https")
        assert reason["code"] == code and reason["message"] and reason["action"], (exc, reason)
    assert link_reason(httpx.RemoteProtocolError("bad"), scheme="http")["code"] == "TLS_REQUIRED"


def test_robot_answers_keep_their_reason():
    assert link_reason(RobotApiError("rosy_60", 401, "UNAUTHORIZED", "x"), scheme="https")["code"] == "PAIRING_REQUIRED"
    assert link_reason(RobotApiError("rosy_60", 409, "CALIBRATION_ACTIVE", "x"), scheme="https")["code"] == "SESSION_TAKEN"
    assert link_reason(RobotApiError("rosy_60", 409, "APPROVAL_EXPIRED", "x"), scheme="https")["code"] == "APPROVAL_EXPIRED"
    assert link_reason(RobotApiError("rosy_60", 200, "BAD_RESPONSE", "x"), scheme="https")["code"] == "UNEXPECTED_RESPONSE"
