"""Subject: video burst trigger gate — corroboration or operator, never vision alone.

D-137 §4: YOLO 단독으로는 영상 버스트 전송을 트리거할 수 없다. 전송 조건은
YOLO + LiDAR/IR corroboration 또는 operator 요청. D-136 §5: quality 저하는
evidence 무효로만 결합한다 — 깨진 영상의 판정은 트리거가 아니다.

The gate answers one question per evidence packet: may this packet start or
sustain a video burst?  It is bandwidth policy, not motion policy — the answer
never reaches cmd_vel.  The false-positive rate cap is deliberately absent:
분당 FP 상한은 T4 ROS-SIM 합의 항목으로 아직 수치가 없고, 정해지면 송신 측
token bucket이 된다(D-136 §4의 on-demand 1req/5s).  A per-packet
corroboration gate is all this module can honestly decide today.
"""
from __future__ import annotations

from .detection_evidence import DetectionEvidence


def burst_gate(evidence: DetectionEvidence, now: float, previous_seq=None, *,
               metric_obstacle_fresh: bool, operator_request: bool) -> dict:
    """Decide one burst-trigger question: {'burst': bool, 'reason': str}.

    ``metric_obstacle_fresh`` is the caller's freshness verdict on the metric
    side (LiDAR/IR) — this module does not re-derive sensor freshness, the
    same way ``clip`` does not re-derive detection freshness.  Operator
    request short-circuits first: 명시적 요청은 자문 서열 위가 아니라 별도
    권한이다.
    """
    if not isinstance(operator_request, bool) or not isinstance(metric_obstacle_fresh, bool):
        raise ValueError('Corroboration inputs must be booleans')
    if not isinstance(evidence, DetectionEvidence):
        raise ValueError('Burst gate evaluates DetectionEvidence snapshots')
    if operator_request:
        return {'burst': True, 'reason': 'operator_request'}
    status = evidence.evaluate(now, previous_seq)['status']
    if status == 'fresh':
        if metric_obstacle_fresh:
            return {'burst': True, 'reason': 'corroborated'}
        # THE D-137 rule: a box alone spends nobody's bandwidth.
        return {'burst': False, 'reason': 'vision_only'}
    if status == 'empty':
        # YOLO saw nothing; metric alone does not trigger a vision burst.
        return {'burst': False, 'reason': 'no_detection'}
    if status == 'missed':
        # Frames were lost: "not seen" is not absence, so no trigger either.
        return {'burst': False, 'reason': 'vision_missed'}
    if status == 'stale':
        return {'burst': False, 'reason': 'vision_stale'}
    return {'burst': False, 'reason': 'vision_invalid'}
