"""D-922: bounded display-only attention; no motion or safety authority."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, pi, sin
from threading import RLock

from core_common.protocol.detections import DETECTION_MAX_AGE_S, DetectionEvidence
from core_features.command.emotion_map import emotion_for


@dataclass(frozen=True)
class Expression:
    face: str | None
    gaze_x: float = 0.0
    resting: bool = False
    rgb: tuple[int, int, int] = (0, 0, 0)
    reacting: bool = False

    def handover(self) -> dict | None:
        return ({"gaze_x": self.gaze_x, "resting": self.resting}
                if self.reacting or self.gaze_x or self.resting else None)


class ExpressionPolicy:
    """One locked encounter history shared by observation and the 5 Hz tick."""

    def __init__(self):
        self._lock = RLock()
        self._frame_at = None
        self._seq = None
        self._revision = None
        self._ever = False
        self._recover = False
        self._people = {}
        self._encounters = {}
        self._group = None
        self._labels = set()
        self._object = None
        self._active = None
        self._target = None
        self._until = 0.0
        self._hold_until = 0.0
        self._last_event = float("-inf")
        self._idle_since = None
        self._activity_at = float("-inf")
        self._mode = None
        self._navigation = None

    def _cancel(self):
        self._active = self._target = self._object = None
        for entry in self._encounters.values():
            entry["pending"] = False

    def _invalidate(self):
        self._frame_at = None
        self._people = {}
        self._recover = self._ever
        self._cancel()
        for entry in self._encounters.values():
            entry["absent"] = None

    def observe(self, packet, *, source_now: float, now: float, known_revision: bool):
        """Admit only fresh, validated evidence; translate source age to monotonic."""
        with self._lock:
            try:
                if (not known_revision or not isfinite(source_now) or not isfinite(now)):
                    raise ValueError("untrusted source")
                evidence = DetectionEvidence.model_validate(packet)
                if (len(evidence.detections) > 64 or not evidence.fresh(source_now)
                        or any(len(d.label) > 64 for d in evidence.detections)):
                    raise ValueError("invalid evidence")
            except (ValueError, TypeError, OverflowError):
                self._invalidate()
                return
            at = now - (source_now - evidence.observed_at)
            changed = self._revision is not None and evidence.model_revision != self._revision
            gap = not changed and self._seq is not None and evidence.seq > self._seq + 1
            replay = not changed and self._seq is not None and evidence.seq <= self._seq
            if replay:
                # A sequence regression starts a suppressed generation, never a new encounter.
                if evidence.seq < self._seq:
                    self._seq = evidence.seq
                self._invalidate()
                return
            lost = self._ever and (self._frame_at is None or at - self._frame_at > DETECTION_MAX_AGE_S)
            baseline = self._recover or lost or changed or gap
            continuous = self._seq is not None and evidence.seq == self._seq + 1 and not baseline
            if baseline:
                self._cancel()
                self._encounters.clear()
            self._seq, self._revision = evidence.seq, evidence.model_revision
            self._frame_at, self._ever, self._recover = at, True, False
            persons = evidence.of_label("person", .5)
            ids = [p.track_id for p in persons]
            group = any(i is None for i in ids) or len(set(ids)) != len(ids)
            switched = self._group is not None and group != self._group and bool(persons)
            if switched:
                self._cancel()
                self._encounters.clear()
                baseline = True
            if persons:
                self._group = group
            people = {}
            if group and persons:
                total = sum(p.confidence for p in persons)
                people["group"] = (sum((p.x + p.w / 2) * p.confidence for p in persons) / total, 1.)
            else:
                people = {p.track_id: (p.x + p.w / 2, p.confidence) for p in persons}
            # Retain visible IDs; only old absent encounters expire.
            self._encounters = {k: e for k, e in self._encounters.items()
                                if k in people or now - e["seen"] <= 60}
            if len(set(self._encounters) | set(people)) > 64:
                self._cancel()
                self._encounters.clear()
                if persons:
                    total = sum(p.confidence for p in persons)
                    people = {"group": (sum((p.x + p.w / 2) * p.confidence for p in persons) / total, 1.)}
                self._group, baseline = True, True
            for key, entry in self._encounters.items():
                if key not in people:
                    if not continuous:
                        entry["absent"] = None
                    elif entry["absent"] is None:
                        entry["absent"] = at
                    entry["pending"] = False
            for key in people:
                entry = self._encounters.get(key)
                if entry is None:
                    entry = dict(first=at, seen=at, absent=None, greeted=None,
                                 pending=not baseline and now - self._last_event >= 5)
                    self._encounters[key] = entry
                    self._activity_at = now
                elif key not in self._people:
                    absent = entry["absent"]
                    cooled = entry["greeted"] is None or now - entry["greeted"] >= 60
                    entry["pending"] = bool(not baseline and absent is not None
                        and at - absent >= 10 and cooled and now - self._last_event >= 5)
                    entry["first"] = at
                    self._activity_at = now
                elif not continuous:
                    entry["first"] = at
                entry["seen"], entry["absent"] = at, None
            self._people = people
            objects = [d for d in evidence.detections if d.label != "person" and d.confidence >= .5]
            labels = {d.label for d in objects}
            fresh_objects = [d for d in objects if d.label not in self._labels]
            self._object = (max(fresh_objects, key=lambda d: d.confidence)
                            if fresh_objects and not baseline else None)
            self._labels = labels
            if gap and not persons:
                self._recover = True

    def update(self, mode, nav_state, now: float, *, suspended=False, moving=False) -> Expression:
        with self._lock:
            return self._update(mode, nav_state, now, suspended=suspended, moving=moving)

    def _update(self, mode, nav_state, now, *, suspended, moving):
        if not isfinite(now):
            self._invalidate()
            return Expression(None)
        fresh = self._frame_at is not None and 0 <= now - self._frame_at <= DETECTION_MAX_AGE_S
        if not fresh:
            self._invalidate()
        arrived = self._navigation in ("PLANNING", "NAVIGATING") and nav_state == "ARRIVED"
        self._navigation = nav_state
        blocked = mode == "NAVIGATION" and nav_state == "BLOCKED"
        unsafe = mode == "EMERGENCY" or nav_state == "FAILED"
        if mode != self._mode:
            if self._mode is not None:
                self._cancel()
            self._idle_since = None
            self._mode = mode
        if suspended or unsafe or blocked:
            self._cancel()
            self._idle_since = None
            return Expression(emotion_for(mode, nav_state), rgb=(self._rgb(mode, nav_state, now) if blocked else (0, 0, 0)))
        if mode == "IDLE" and moving is False:
            if self._idle_since is None:
                self._idle_since = now
            self._idle_since = max(self._idle_since, self._activity_at)
        else:
            self._idle_since = None
        resting = bool(fresh and self._idle_since is not None and now - self._idle_since >= 300)
        base = emotion_for(mode, nav_state)
        if mode == "NAVIGATION" and not moving:
            base = "basic"
        if resting:
            base = "bored"
        if self._target is not None and self._target not in self._people:
            self._active = self._target = None
        candidates = [key for key in self._people if self._encounters[key]["pending"]
                      and now - self._encounters[key]["first"] >= .5]
        pending_people = any(self._encounters[key]["pending"] for key in self._people)
        duration = .6 if moving or mode != "IDLE" else 1.5
        if candidates and now - self._last_event >= 5 and now >= self._hold_until:
            self._target = min(candidates, key=lambda key: (abs(self._people[key][0] - .5),
                                                          -self._people[key][1], key if isinstance(key, int) else 0))
            entry = self._encounters[self._target]
            entry["pending"], entry["greeted"] = False, now
            self._active, self._until, self._hold_until = "happy", now + duration, now + 3
            self._last_event, self._idle_since, resting = now, now if mode == "IDLE" else None, False
        elif self._object is not None and not pending_people and now - self._last_event >= 5:
            self._active, self._until = "interest", now + duration
            self._target, self._last_event = None, now
            self._object_gaze = (2 * (self._object.x + self._object.w / 2) - 1) * 6
            self._object = None
            self._idle_since, resting = now if mode == "IDLE" else None, False
        elif arrived and fresh and not pending_people and now - self._last_event >= 5:
            self._active, self._target, self._object_gaze = "happy", None, 0.
            self._until, self._last_event = now + 1.5, now
        active = self._active is not None and now < self._until
        gaze = 0.0
        if fresh and self._target is not None and (active or mode == "IDLE" and now < self._hold_until):
            gaze = (2 * self._people[self._target][0] - 1) * 6
            base = self._active if active else "interest"
        elif active and fresh:
            gaze, base = getattr(self, "_object_gaze", 0.), self._active
        else:
            self._active = None
        rgb = self._rgb(mode, nav_state, now, resting=resting, moving=moving)
        if active and max(rgb) > 0:
            elapsed = now - self._last_event
            ramp = min(.4, (self._until - self._last_event) / 2)
            gain = min(1., elapsed / ramp, (self._until - now) / ramp)
            peak = max(rgb)
            scale = 1 + (36 / peak - 1) * max(0., gain)
            rgb = tuple(min(36, round(c * scale)) for c in rgb)
        return Expression(base, max(-6., min(6., gaze)), resting, rgb, reacting=active)

    @staticmethod
    def _rgb(mode, nav, now, *, resting=False, moving=False):
        if resting:
            color, period = (8, 3, 7), 8
        elif mode == "NAVIGATION" and nav == "BLOCKED":
            color, period = (24, 14, 0), 2
        elif mode == "NAVIGATION" and moving:
            color, period = (0, 24, 24), 4
        elif mode == "MANUAL":
            color, period = (20, 20, 20), 4
        elif mode == "DOCKING":
            color, period = (24, 0, 20), 4
        elif mode == "IDLE" or mode == "NAVIGATION":
            color, period = (12, 4, 10), 0
        else:
            return (0, 0, 0)
        amount = (.625 + .375 * sin(2 * pi * now / period) if resting
                  else .7 + .3 * sin(2 * pi * now / period)) if period else 1
        return tuple(round(c * amount) for c in color)
