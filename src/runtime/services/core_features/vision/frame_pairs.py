"""Bounded display-only capture pairs. Called under VisionFrameStore's lock."""
from collections import deque
from dataclasses import replace


class FramePairs:
    def __init__(self):
        self.raw = deque(maxlen=4)
        self.annotated = deque(maxlen=4)
        self.pulls = {}

    def add(self, frame, *, raw: bool):
        (self.raw if raw else self.annotated).append(frame)

    def annotated_for(self, sequence):
        return next((f for f in reversed(self.annotated) if f.sequence == sequence), None)

    def raw_for(self, frame):
        found = next((f for f in reversed(self.raw)
                      if f.captured_at == frame.captured_at and f.frame_id == frame.frame_id
                      and bool(f.frame_id) and f.width == frame.width and f.height == frame.height
                      and f.width > 0 and f.height > 0), None)
        return None if found is None else replace(found, sequence=frame.sequence)

    def expire(self, now, ttl):
        for queue in (self.raw, self.annotated):
            while queue and not 0 <= now - queue[0].received_at <= ttl:
                queue.popleft()
        self.pulls = {viewer: entry for viewer, entry in self.pulls.items()
                      if 0 <= now - entry['at'] <= ttl}
