"""Subject: advisory vision detection evidence; never a stop authority.

D-137: LiDAR/IR decide, the camera reports.  One immutable snapshot per
inference packet, frozen beside the producer and re-evaluated by CORE per
read -- the TrackedEvidence pattern (obstacle_risk.py) with the action
vocabulary removed: evaluate() classifies evidence, it never commands.

"Empty" and "missed" are different facts (API Ref section 6.1.1): a packet
with no detections whose seq is contiguous says *nothing was there*; a
packet whose seq jumped says *frames were lost*, and no clear verdict may
be drawn from frames nobody saw.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass

#: D-136 freshness ceiling for vision evidence on the policy snapshot.
MAX_AGE_S = 0.3
#: Boxes are normalized, so a packet is tiny; 8 KiB admits 64 boxes with a
#: generous label budget while keeping a runaway producer from wedging a
#: consumer the way an unbounded packet would.
MAX_PACKET_BYTES = 8192
MAX_DETECTIONS = 64
MAX_LABEL_CHARS = 64
#: Input-plane bounds follow the camera profile contract
#: (sensing/perception/camera_worker.py).  The inference plane is smaller in practice;
#: the bound only rejects impossible specifications.
MIN_INPUT_PX = 8
MAX_INPUT_PX = 4096


def _finite(value) -> bool:
    # type() rejects bools, which are ints but never valid measurements.
    return type(value) in (int, float) and math.isfinite(value)


def _freeze_detection(detection) -> dict:
    """Normalize one box or raise ValueError; unknown keys are dropped."""
    if not isinstance(detection, dict):
        raise ValueError('Invalid detection')
    label = detection.get('label')
    if (type(label) is not str or not label.strip()
            or label != label.strip() or len(label) > MAX_LABEL_CHARS):
        raise ValueError('Invalid detection label')
    box = tuple(detection.get(k) for k in ('x', 'y', 'w', 'h'))
    # Same rules as the wire truth (core_common.protocol.detections):
    # origin normalized to [0, 1], size in (0, 1].  The D-18 sync test
    # pins the two gates to identical accept/reject sets.
    if not (_finite(box[0]) and 0.0 <= box[0] <= 1.0
            and _finite(box[1]) and 0.0 <= box[1] <= 1.0):
        raise ValueError('Detection box origin must be normalized to [0, 1]')
    if not all(_finite(v) and 0.0 < v <= 1.0 for v in box[2:]):
        raise ValueError('Detection box size must be in (0, 1]')
    x, y, w, h = (float(v) for v in box)
    # Boundary sums such as 0.9 + 0.1 are exactly 1.0 in binary floats, so
    # this is the same expression the pydantic wire validator uses.
    if x + w > 1.0 or y + h > 1.0:
        raise ValueError('Detection box exceeds the input frame')
    confidence = detection.get('confidence')
    if not _finite(confidence) or not 0.0 <= confidence <= 1.0:
        raise ValueError('Invalid detection confidence')
    track_id = detection.get('track_id')
    if track_id is not None and (type(track_id) is not int or track_id < 0):
        raise ValueError('Invalid detection track id')
    return {'label': label, 'x': x, 'y': y, 'w': w, 'h': h,
            'confidence': float(confidence),
            'track_id': None if track_id is None else int(track_id)}


@dataclass(frozen=True)
class DetectionEvidence:
    detections_json: str
    observed_at: float
    observed_at_mono: float
    seq: int
    model_revision: str
    input_width: int
    input_height: int
    input_fps: float
    inference_ms: float | None

    @classmethod
    def capture(cls, packet, *, source_now, received_at) -> 'DetectionEvidence':
        """Validate one producer packet and freeze it.  Raises ValueError.

        Capture beside inference, not inside the CORE output loop.  The
        source stamp is kept for wire fidelity; staleness is judged on the
        monotonic translation, like TrackedEvidence does.
        """
        if (not isinstance(packet, dict)
                or not _finite(source_now) or not _finite(received_at)):
            raise ValueError('Invalid detection packet or clocks')
        revision = packet.get('model_revision')
        if (type(revision) is not str or not revision.strip()
                or revision != revision.strip() or len(revision) > 128):
            raise ValueError('Invalid model revision')
        observed_at = packet.get('observed_at')
        if not _finite(observed_at) or observed_at < 0:
            raise ValueError('Invalid observation stamp')
        seq = packet.get('seq')
        if type(seq) is not int or seq < 0:
            raise ValueError('Invalid detection sequence')
        width, height = packet.get('input_width'), packet.get('input_height')
        for size in (width, height):
            if type(size) is not int or not MIN_INPUT_PX <= size <= MAX_INPUT_PX:
                raise ValueError('Invalid inference input size')
        fps = packet.get('input_fps')
        if not _finite(fps) or not 0 < fps <= 240:
            raise ValueError('Invalid inference fps')
        inference_ms = packet.get('inference_ms')
        if inference_ms is not None and (not _finite(inference_ms) or inference_ms < 0):
            raise ValueError('Invalid inference latency')
        detections = packet.get('detections')
        if not isinstance(detections, list) or len(detections) > MAX_DETECTIONS:
            raise ValueError('Detection evidence requires at most 64 detections')
        text = json.dumps([_freeze_detection(d) for d in detections],
                          allow_nan=False)
        if len(text.encode('utf-8')) > MAX_PACKET_BYTES:
            raise ValueError('Detection evidence exceeds size bound')
        return cls(text, observed_at, received_at - (source_now - observed_at),
                   seq, revision, width, height, float(fps),
                   None if inference_ms is None else float(inference_ms))

    def evaluate(self, now, previous_seq=None) -> dict:
        """Classify this packet for one consumer read.  Advisory output.

        fresh   detections present, inside the freshness window
        empty   no detections, contiguous seq -- "none there"
        missed  no detections, seq jumped -- frames were lost, not empty
        stale   outside the freshness window, or an older packet re-read
        invalid snapshot corrupted or the read clock is unusable
        """
        if (type(self.detections_json) is not str
                or len(self.detections_json.encode('utf-8')) > MAX_PACKET_BYTES
                or type(self.seq) is not int or self.seq < 0
                or type(self.model_revision) is not str or not self.model_revision
                or type(self.input_width) is not int
                or not MIN_INPUT_PX <= self.input_width <= MAX_INPUT_PX
                or type(self.input_height) is not int
                or not MIN_INPUT_PX <= self.input_height <= MAX_INPUT_PX
                or not _finite(self.input_fps) or self.input_fps <= 0
                or (self.inference_ms is not None
                    and (not _finite(self.inference_ms) or self.inference_ms < 0))
                or not _finite(self.observed_at_mono) or not _finite(now)):
            status, detections, age_ms = 'invalid', [], None
        else:
            try:
                detections = json.loads(self.detections_json)
            except ValueError:
                detections = None
            if not isinstance(detections, list) or len(detections) > MAX_DETECTIONS:
                status, detections, age_ms = 'invalid', [], None
            else:
                age = now - self.observed_at_mono
                age_ms = round(age * 1000.0, 3)
                if not 0.0 <= age <= MAX_AGE_S:
                    status = 'stale'
                elif previous_seq is not None and self.seq <= previous_seq:
                    # An older or regressed packet is old news, not evidence.
                    status = 'stale'
                elif detections:
                    # Boxes are evidence of their own moment even when the
                    # sequence gapped; the gap only poisons empty claims.
                    status = 'fresh'
                elif previous_seq is not None and self.seq > previous_seq + 1:
                    status = 'missed'
                else:
                    status = 'empty'
        return {'status': status, 'detections': detections, 'age_ms': age_ms,
                'seq': self.seq, 'model_revision': self.model_revision}

    def to_wire(self) -> dict:
        """The API Ref section 6.1.1 packet, for publishing and contract tests."""
        return {
            'model_revision': self.model_revision,
            'observed_at': self.observed_at,
            'seq': self.seq,
            'input_width': self.input_width,
            'input_height': self.input_height,
            'input_fps': self.input_fps,
            'inference_ms': self.inference_ms,
            'detections': json.loads(self.detections_json),
        }
