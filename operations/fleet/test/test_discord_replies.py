"""Discord reply transport cannot choose another destination or claim device success."""
import asyncio
import json

import httpx
import pytest

import fleet  # noqa: F401 -- production source-holder bootstrap
from rosy_discord.replies import DiscordReplies


CHANNEL, BOT, MESSAGE, REPLY = (str(100000000000000000 + i) for i in range(4))


def deliver(handler, *, message=MESSAGE, nonce="a" * 24):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            sender = DiscordReplies(channel_id=CHANNEL, bot_id=BOT, token="test-bot-token", http=http)
            return await sender.send(message_id=message, nonce=nonce, content="ROSY request received")
    return asyncio.run(run())


def accepted_body(**updates):
    body = {"id": REPLY, "channel_id": CHANNEL, "author": {"id": BOT, "bot": True},
            "message_reference": {"message_id": MESSAGE, "channel_id": CHANNEL}}
    body.update(updates)
    return body


def test_reply_is_bound_to_fixed_channel_original_message_and_no_mentions():
    def handler(request):
        assert str(request.url) == f"https://discord.com/api/v10/channels/{CHANNEL}/messages"
        assert request.headers["Authorization"] == "Bot test-bot-token"
        body = json.loads(request.content)
        assert body["message_reference"] == {
            "message_id": MESSAGE, "channel_id": CHANNEL, "fail_if_not_exists": True}
        assert body["allowed_mentions"] == {"parse": [], "replied_user": False}
        assert body["nonce"] == "a" * 24 and body["enforce_nonce"] is True
        return httpx.Response(200, json=accepted_body())
    assert deliver(handler) == {"state": "SENT", "provider_id": REPLY}


@pytest.mark.parametrize("body", [
    accepted_body(channel_id=MESSAGE), accepted_body(author={"id": MESSAGE, "bot": True}),
    accepted_body(message_reference={"message_id": CHANNEL, "channel_id": CHANNEL}),
    {"id": REPLY},
])
def test_unproven_provider_response_is_unknown(body):
    assert deliver(lambda request: httpx.Response(200, json=body))["state"] == "UNKNOWN"


@pytest.mark.parametrize("status,state", [
    (429, "RETRY"), (403, "FAILED"), (404, "FAILED"), (500, "UNKNOWN"), (302, "FAILED")])
def test_no_blind_retry_after_ambiguous_or_refused_delivery(status, state):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={})
    assert deliver(handler)["state"] == state
    assert len(calls) == 1


@pytest.mark.parametrize("error,state", [
    (httpx.ConnectError, "RETRY"), (httpx.ReadTimeout, "UNKNOWN")])
def test_network_failure_distinguishes_not_connected_from_unknown(error, state):
    def handler(request):
        raise error("private credential must never reach result", request=request)
    result = deliver(handler)
    assert result == {"state": state, "provider_id": None}


def test_invalid_reply_identifiers_never_enter_http():
    def handler(request):
        pytest.fail("invalid reply entered HTTP")
    for message, nonce in (("https://other.example", "a" * 24), (MESSAGE, "bad nonce")):
        with pytest.raises(ValueError):
            deliver(handler, message=message, nonce=nonce)


def test_large_provider_body_is_bounded_and_unknown():
    assert deliver(lambda request: httpx.Response(200, content=b"x" * 20000))["state"] == "UNKNOWN"
