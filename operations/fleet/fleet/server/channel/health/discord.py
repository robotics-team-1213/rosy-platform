"""Bare scheduled post through the existing authenticated Discord client."""
import json
import re

import httpx


class BareDiscordPublisher:
    def __init__(self, *, guild_id, channel_id, bot_id, token, http):
        if any(type(value) is not str or re.fullmatch(r"[0-9]{17,20}", value) is None
               for value in (channel_id, bot_id)):
            raise ValueError("invalid fixed Discord destination")
        self.scope = (guild_id, channel_id, bot_id)
        self.channel_id, self.bot_id, self.token, self.http = channel_id, bot_id, token, http

    async def publish(self, *, nonce, content):
        if (type(nonce) is not str or re.fullmatch(r"[0-9a-f]{24}", nonce) is None
                or type(content) is not str or not 1 <= len(content) <= 2000 or "\x00" in content):
            raise ValueError("invalid Discord publication")
        payload = {"content": content, "nonce": nonce, "enforce_nonce": True,
                   "allowed_mentions": {"parse": [], "replied_user": False}}
        result = {"state": "UNKNOWN", "provider_id": None}
        try:
            async with self.http.stream(
                    "POST", f"https://discord.com/api/v10/channels/{self.channel_id}/messages",
                    headers={"Authorization": f"Bot {self.token}"}, json=payload,
                    timeout=5, follow_redirects=False) as response:
                if response.status_code == 429:
                    result["state"] = "RETRY"
                elif 300 <= response.status_code < 500:
                    result["state"] = "FAILED"
                elif response.status_code == 200:
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 16384:
                            return result
                    body = json.loads(raw)
                    author, candidate = body.get("author", {}), body.get("id")
                    if (type(candidate) is str and re.fullmatch(r"[0-9]{17,20}", candidate)
                            and body.get("channel_id") == self.channel_id
                            and author.get("id") == self.bot_id and author.get("bot") is True
                            and body.get("nonce") == nonce):
                        result.update(state="SENT", provider_id=candidate)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            result["state"] = "RETRY"
        except (httpx.HTTPError, OSError, ValueError, TypeError, AttributeError):
            pass
        return result
