"""D-922 display adapters and acknowledged indicator RPCs; no ROS imports."""
import json

from core_features.power.battery import LedCommand, resolve_led


def observe(policy, raw, *, models, source_now, now):
    """A reported active model revision admits display evidence, never motion."""
    try:
        packet = json.loads(raw) if isinstance(raw, str) and len(raw.encode("utf-8")) <= 8192 else None
    except (ValueError, UnicodeError):
        packet = None
    tasks = models.snapshot(now=now)["tasks"]
    known = isinstance(packet, dict) and any(
        task["task"] == "object_det" and task["slot"] == "active" and not task["stale"]
        and not task["last_error"] and task["model_revision"] == packet.get("model_revision")
        for task in tasks)
    policy.observe(packet, source_now=source_now, now=now, known_revision=known)


def led_command(desired, *, alert, info_visible, gauge_percent, now):
    if alert is not None or info_visible:
        return resolve_led(alert, info_visible=info_visible, gauge_percent=gauge_percent, now=now)
    return LedCommand("fill", *desired.rgb) if any(desired.rgb) else LedCommand("clear")


def emotion_accepted(value, reply):
    return reply is not None and reply.response == f"Emotion set to {value}"


class ServiceOutput:
    """Latch successful replies only; bound pending calls and refresh across restarts."""

    def __init__(self, *, accept=None):
        self._accept = accept or (lambda value, reply: reply is not None and reply.success is True)
        self._pending = None
        self._pending_value = self._applied = None
        self._sent_at = self._confirmed_at = float("-inf")

    def apply(self, value, *, now, ready, send):
        if not ready:
            if self._pending is not None:
                self._pending.cancel()
            self._pending = self._applied = None
            return
        if self._pending is not None:
            if self._pending.done():
                try:
                    reply = self._pending.result()
                    self._applied = self._pending_value if self._accept(self._pending_value, reply) else None
                    self._confirmed_at = now
                except Exception:  # an indicator reply must not break the state timer
                    self._applied = None
                self._pending = None
            elif value != self._pending_value or now - self._sent_at >= 1.0:
                self._pending.cancel()
                self._pending = self._applied = None
            else:
                return
        if value is None or value == self._applied and now - self._confirmed_at < 5:
            return
        try:
            self._pending = send(value)
        except Exception:  # the next existing state tick retries after service recovery
            self._pending = None
        self._pending_value, self._sent_at = value, now
