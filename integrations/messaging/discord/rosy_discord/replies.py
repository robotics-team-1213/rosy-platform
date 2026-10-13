"""Bounded Discord reply transport; Fleet owns the durable delivery decision."""
import json
import re

import httpx


class DiscordReplies:
    def __init__(self, *, channel_id, bot_id, token, http):
        if any(type(value) is not str or re.fullmatch(r"[0-9]{17,20}", value) is None
               for value in (channel_id, bot_id)):
            raise ValueError("invalid fixed Discord destination")
        self.channel_id, self.bot_id, self._token, self.http = channel_id, bot_id, token, http

    async def send(self, *, message_id, nonce, content):
        if (type(message_id) is not str or re.fullmatch(r"[0-9]{17,20}", message_id) is None
                or type(nonce) is not str or re.fullmatch(r"[0-9a-f]{24}", nonce) is None
                or type(content) is not str or not 1 <= len(content) <= 2000 or "\x00" in content):
            raise ValueError("invalid Discord reply")
        payload = {"content": content, "nonce": nonce, "enforce_nonce": True, "flags": 4,
                   "allowed_mentions": {"parse": [], "replied_user": False},
                   "message_reference": {"message_id": message_id, "channel_id": self.channel_id,
                                         "fail_if_not_exists": True}}
        state, provider_id = "UNKNOWN", None
        try:
            async with self.http.stream(
                    "POST", f"https://discord.com/api/v10/channels/{self.channel_id}/messages",
                    headers={"Authorization": f"Bot {self._token}"}, json=payload,
                    timeout=5, follow_redirects=False) as response:
                if response.status_code == 429:
                    state = "RETRY"
                elif 300 <= response.status_code < 500:
                    state = "FAILED"
                elif response.status_code == 200:
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 16384:
                            return {"state": "UNKNOWN", "provider_id": None}
                    body = json.loads(raw)
                    identity, reference = body.get("author", {}), body.get("message_reference", {})
                    candidate = body.get("id")
                    if (type(candidate) is str and re.fullmatch(r"[0-9]{17,20}", candidate)
                            and body.get("channel_id") == self.channel_id
                            and identity.get("id") == self.bot_id and identity.get("bot") is True
                            and reference.get("message_id") == message_id
                            and reference.get("channel_id") == self.channel_id):
                        state, provider_id = "SENT", candidate
        except (httpx.ConnectError, httpx.ConnectTimeout):
            state = "RETRY"
        except (httpx.HTTPError, OSError, ValueError, TypeError, AttributeError):
            pass
        return {"state": state, "provider_id": provider_id}
