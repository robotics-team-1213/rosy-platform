"""D-499: robot link class from the gather outcome. No HTTP."""

import ssl

import httpx

from fleet.server.console_view import classify_link
from fleet.swarm.transport import RobotApiError


def _refused(status):
    return RobotApiError("rosy_01", status, "HTTP_%s" % status, "no")


def test_success_is_up_even_when_the_address_moved():
    assert classify_link(None, scheme="http", address_status="seen_at_other_address") == "up"


def test_a_failed_gather_at_another_address_is_moved_ahead_of_protocol_and_401():
    protocol = httpx.RemoteProtocolError("disconnected")
    assert classify_link(protocol, scheme="http",
                         address_status="seen_at_other_address") == "moved"
    assert classify_link(_refused(401), scheme="https",
                         address_status="seen_at_other_address") == "moved"
    assert classify_link(_refused(500), scheme="http",
                         address_status="seen_at_other_address") == "moved"


def test_http_401_is_tls_refused_and_any_other_robot_api_error_omits_link():
    assert classify_link(_refused(401), scheme="https", address_status=None) == "tls-refused"
    assert classify_link(_refused(403), scheme="https", address_status=None) is None
    assert classify_link(_refused(500), scheme="http", address_status="outside_scanned_subnets") is None


def test_plain_http_remote_protocol_error_is_protocol():
    exc = httpx.RemoteProtocolError("disconnected")
    assert classify_link(exc, scheme="http", address_status=None) == "protocol"
    assert classify_link(exc, scheme="HTTP", address_status="unknown") == "protocol"


def test_https_protocol_errors_and_connect_failures_stay_unreachable():
    remote = httpx.RemoteProtocolError("disconnected")
    assert classify_link(remote, scheme="https", address_status=None) == "unreachable"
    assert classify_link(httpx.ConnectError("refused"), scheme="http", address_status=None) == "unreachable"
    assert classify_link(ssl.SSLError("certificate"), scheme="https", address_status=None) == "unreachable"
    assert classify_link(TimeoutError("slow"), scheme="http", address_status="outside_scanned_subnets") == "unreachable"
