"""Mention-only transport projection, independent of Fleet account and DB owners."""
import hashlib
import hmac
import json
import time

from core_common.protocol.channel_requests import DiscordRequestEnvelope
from pydantic import ValidationError


def project_message(message, *, guild_id, channel_id, bot_id):
    if not isinstance(message, dict) or not isinstance(message.get("author"), dict):
        return None
    author = message.get("author", {})
    if (message.get("guild_id") != guild_id or message.get("channel_id") != channel_id
            or author.get("bot", False) or message.get("webhook_id") is not None):
        return None
    try:
        envelope = DiscordRequestEnvelope(
            guild_id=guild_id, channel_id=channel_id, message_id=message.get("id"),
            author_id=author.get("id"), content=message.get("content", ""),
            mentions=[user["id"] for user in message.get("mentions", [])],
            author_bot=False, webhook_id=None)
    except (ValidationError, KeyError, TypeError):
        return None
    return envelope if bot_id in envelope.mentions else None


def signed_request(envelope, *, key, now=None):
    timestamp = str(int(time.time() if now is None else now))
    body = json.dumps(envelope.model_dump(), ensure_ascii=False, separators=(",", ":")).encode()
    signature = hmac.new(key.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return body, {"Content-Type": "application/json", "X-ROSY-Timestamp": timestamp,
                  "X-ROSY-Signature": signature}
