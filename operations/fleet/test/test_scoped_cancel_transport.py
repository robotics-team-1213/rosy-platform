"""The sender binds cancel receipts and never falls back to unconditional stop."""

import asyncio
import copy

import pytest

from fleet.swarm.navigation_transport import NavigationTransport


SCOPE = {"expected_boot_id": "9ed6c9cf-15b1-4245-a2bc-836b21c9bfa2",
         "run_id": "5b4c766a-6cd2-4ebd-9d43-1b67638d92d2", "correlation_id": "attempt-1"}


def receipt():
    return {"navigation": "CANCELED", "operation": {
        "boot_id": SCOPE["expected_boot_id"], "run_id": SCOPE["run_id"],
        "correlation_id": SCOPE["correlation_id"], "phase": "TERMINAL", "result": "CANCELED"}}


class Sender(NavigationTransport):
    def __init__(self, response):
        self.response, self.calls = response, []

    async def _post(self, path, body=None):
        self.calls.append((path, body))
        if isinstance(self.response, Exception):
            raise self.response
        return copy.deepcopy(self.response)


def test_exact_receipt_and_body_are_preserved():
    sender = Sender(receipt())
    assert asyncio.run(sender.navigation_cancel_scoped(**SCOPE)) == receipt()
    assert sender.calls == [("/api/v1/navigation/cancel-scoped", SCOPE)]


@pytest.mark.parametrize("section,key,value", [
    ("operation", "boot_id", "other-boot"), ("operation", "run_id", "other-run"),
    ("operation", "correlation_id", "other-attempt"), ("operation", "phase", "ACCEPTED"),
    ("operation", "result", "COMPLETED"), (None, "navigation", None),
    (None, "operation", None),
])
def test_unverified_response_is_not_a_success(section, key, value):
    response = receipt()
    (response[section] if section else response)[key] = value
    with pytest.raises(ValueError, match="SCOPED_CANCEL_RESPONSE_UNVERIFIED"):
        asyncio.run(Sender(response).navigation_cancel_scoped(**SCOPE))


def test_unsupported_scoped_endpoint_never_uses_legacy_cancel():
    sender = Sender(RuntimeError("unsupported scoped endpoint"))
    with pytest.raises(RuntimeError, match="unsupported"):
        asyncio.run(sender.navigation_cancel_scoped(**SCOPE))
    assert [path for path, _ in sender.calls] == ["/api/v1/navigation/cancel-scoped"]


def test_bad_scope_does_not_send_a_request():
    sender = Sender(receipt())
    with pytest.raises(ValueError):
        asyncio.run(sender.navigation_cancel_scoped(**dict(SCOPE, run_id="not-a-uuid")))
    assert sender.calls == []


def test_old_cancel_receipt_is_valid_even_if_the_facade_now_shows_a_new_run():
    response = receipt()
    response["navigation"] = "NAVIGATING"
    assert asyncio.run(Sender(response).navigation_cancel_scoped(**SCOPE)) == response
