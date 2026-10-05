"""D-426 Task 3 — 수치 판정(ROS-free). observer.py가 만든 관측 기록을 판정한다.

시뮬 수용 목표(계획 T3 항목 3·4, 실물 안전 기준이 아니다):
- 도착: 위치 오차 ≤ 0.10 m, 방향 오차 ≤ 10°
- 정지: |v| ≤ 0.01 m/s · |w| ≤ 0.03 rad/s 를 1 s 연속 유지
- 여유: 로봇 footprint 경계 간 최소 거리 ≥ 0.10 m (중심점 거리 아님)
- 접촉: contact 0건 — 단, 양성 대조(의도적 접촉 검출)가 통과해야만 단언 가능
- 관측: 20 Hz 이상; 빈 구간 > 0.15 s 면 충돌 계열 판정은 INCONCLUSIVE
- 시계: 물리 진행·도착은 sim time, 네트워크 시한은 monotonic — 분리해서만 쓴다
- epoch: pause/reset 은 새 epoch — 이전 물리 단언을 이어 붙이지 않는다

모든 단언은 PASS/FAIL/NOT_RUN/INCONCLUSIVE 와 관측원·단위·시계·임계값·원본 위치를
남긴다(계획 T3 항목 5). 임계값을 몰래 완화하지 않는다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

VERDICTS = ("PASS", "FAIL", "NOT_RUN", "INCONCLUSIVE")

#: 관측원 표기 — observer.py 의 수집 경로.
OBSERVER_POSE = "gz-model-pose"
OBSERVER_CONTACT = "gz-contact-sensor"

ARRIVAL_POSITION_M = 0.10
ARRIVAL_HEADING_DEG = 10.0
STANDSTILL_LINEAR_MPS = 0.01
STANDSTILL_ANGULAR_RADPS = 0.03
STANDSTILL_HOLD_S = 1.0
CLEARANCE_M = 0.10
MIN_OBSERVATION_HZ = 20.0
MAX_GAP_S = 0.15


def _verdict(name, verdict, *, observer, unit, clock, threshold, evidence):
    return {
        "name": name, "verdict": verdict, "observer": observer, "unit": unit,
        "clock": clock, "threshold": threshold, "evidence": evidence,
    }


@dataclass(frozen=True)
class PoseSample:
    """한 순간의 로봇 자세. sim(t)·monotonic(mono)·frame 을 함께 실어 혼용을 잡는다."""

    robot_id: str
    t: float                 # sim time — 물리 진행·도착 판정의 시계
    mono: float              # monotonic — 네트워크·관측 시한의 시계
    x: float
    y: float
    yaw: float
    v: float = 0.0
    w: float = 0.0
    frame: str = "map"


@dataclass(frozen=True)
class ContactEvent:
    robot_id: str
    t: float
    mono: float
    other: str = ""


def heading_error_deg(yaw: float, goal_yaw: float) -> float:
    delta = math.atan2(math.sin(yaw - goal_yaw), math.cos(yaw - goal_yaw))
    return abs(math.degrees(delta))


def arrival(samples: list[PoseSample], *, robot_id: str, goal, epoch=None) -> dict:
    """마지막 관측 자세의 도착 판정. 이동 없음·frame 혼용은 각각 별도 단언이 잡는다."""
    owned = [s for s in samples if s.robot_id == robot_id]
    if not owned:
        return _verdict("arrival", "NOT_RUN", observer=OBSERVER_POSE, unit="m",
                        clock="sim", threshold={"position_m": ARRIVAL_POSITION_M,
                                                "heading_deg": ARRIVAL_HEADING_DEG},
                        evidence=[])
    last = owned[-1]
    position_err = math.hypot(last.x - goal["x"], last.y - goal["y"])
    heading_err = heading_error_deg(last.yaw, goal.get("yaw", last.yaw))
    ok = position_err <= ARRIVAL_POSITION_M and heading_err <= ARRIVAL_HEADING_DEG
    return _verdict("arrival", "PASS" if ok else "FAIL", observer=OBSERVER_POSE,
                    unit="m", clock="sim",
                    threshold={"position_m": ARRIVAL_POSITION_M,
                               "heading_deg": ARRIVAL_HEADING_DEG},
                    evidence=[{"sample_t": last.t, "position_error_m": round(position_err, 4),
                               "heading_error_deg": round(heading_err, 3)}])


def standstill(samples: list[PoseSample], *, robot_id: str,
               hold_s: float = STANDSTILL_HOLD_S) -> dict:
    """마지막 관측 시점으로부터 hold_s 동안 |v|·|w| 상한 연속 유지."""
    owned = sorted((s for s in samples if s.robot_id == robot_id), key=lambda s: s.t)
    if len(owned) < 2:
        return _verdict("standstill", "NOT_RUN", observer=OBSERVER_POSE, unit="m/s",
                        clock="sim",
                        threshold={"linear_mps": STANDSTILL_LINEAR_MPS,
                                   "angular_radps": STANDSTILL_ANGULAR_RADPS,
                                   "hold_s": hold_s}, evidence=[])
    end = owned[-1]
    window = [s for s in owned if end.t - s.t <= hold_s + 1e-9]
    span = end.t - window[0].t
    gaps = [b.t - a.t for a, b in zip(window, window[1:])]
    mono_gaps = [b.mono - a.mono for a, b in zip(window, window[1:])]
    valid = all(type(v) in (int, float) and math.isfinite(v)
                for s in window for v in (s.t, s.mono, s.v, s.w))
    max_gap = max(gaps + mono_gaps, default=math.inf)
    rate = (len(window) - 1) / span if span > 0 else 0.
    continuous = (valid and all(g > 0 for g in gaps + mono_gaps) and
                  max_gap <= MAX_GAP_S and rate >= MIN_OBSERVATION_HZ)
    worst_v = max(abs(s.v) for s in window)
    worst_w = max(abs(s.w) for s in window)
    complete = span >= hold_s - 1e-9
    ok = complete and continuous and worst_v <= STANDSTILL_LINEAR_MPS and worst_w <= STANDSTILL_ANGULAR_RADPS
    verdict = "PASS" if ok else ("INCONCLUSIVE" if not complete or not continuous else "FAIL")
    return _verdict("standstill", verdict, observer=OBSERVER_POSE, unit="m/s",
                    clock="sim", threshold={"linear_mps": STANDSTILL_LINEAR_MPS,
                                            "angular_radps": STANDSTILL_ANGULAR_RADPS,
                                            "hold_s": hold_s},
                    evidence=[{"window_s": round(span, 3), "worst_v": worst_v,
                               "worst_w": worst_w, "samples": len(window),
                               "max_gap_s": max_gap, "rate_hz": rate}])


def _polygon_edges(polygon: list[tuple[float, float]]):
    count = len(polygon)
    for i in range(count):
        yield polygon[i], polygon[(i + 1) % count]


def _point_segment_distance(px, py, ax, ay, bx, by) -> float:
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    if length2 <= 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _segments_intersect(a, b, c, d) -> bool:
    def cross(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    values = cross(a, b, c), cross(a, b, d), cross(c, d, a), cross(c, d, b)
    if values[0] * values[1] < 0 and values[2] * values[3] < 0:
        return True
    for value, p, q, r in ((values[0], a, b, c), (values[1], a, b, d),
                           (values[2], c, d, a), (values[3], c, d, b)):
        if (abs(value) <= 1e-12 and min(p[0], q[0]) <= r[0] <= max(p[0], q[0]) and
                min(p[1], q[1]) <= r[1] <= max(p[1], q[1])):
            return True
    return False


def _inside_polygon(point, polygon) -> bool:
    x, y = point
    inside = False
    for (ax, ay), (bx, by) in _polygon_edges(polygon):
        if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay):
            inside = not inside
    return inside


def footprint_clearance_m(pose: PoseSample, other: PoseSample,
                          footprint: list[tuple[float, float]],
                          other_footprint: list[tuple[float, float]]) -> float:
    """두 footprint 경계 사이 최소 거리. 중심점 거리로 대체하지 않는다."""
    def world(p, sample):
        cos, sin = math.cos(sample.yaw), math.sin(sample.yaw)
        return (p[0] * cos - p[1] * sin + sample.x, p[0] * sin + p[1] * cos + sample.y)

    a = [world(point, pose) for point in footprint]
    b = [world(point, other) for point in other_footprint]
    if len(a) < 3 or len(b) < 3 or any(not math.isfinite(v) for p in a + b for v in p):
        raise ValueError("footprints must contain finite polygons")
    if (any(_segments_intersect(start, end, other_start, other_end)
            for start, end in _polygon_edges(a) for other_start, other_end in _polygon_edges(b)) or
            _inside_polygon(a[0], b) or _inside_polygon(b[0], a)):
        return 0.
    best = math.inf
    for point in a:
        for start, end in _polygon_edges(b):
            best = min(best, _point_segment_distance(point[0], point[1], start[0], start[1],
                                                     end[0], end[1]))
    for point in b:
        for start, end in _polygon_edges(a):
            best = min(best, _point_segment_distance(point[0], point[1], start[0], start[1],
                                                     end[0], end[1]))
    return best


def clearance(pair_samples: list[tuple[PoseSample, PoseSample]], footprints: dict,
              *, threshold_m: float = CLEARANCE_M) -> dict:
    """매 순간쌍의 footprint 여유 최솟값 판정."""
    if not pair_samples:
        return _verdict("clearance", "NOT_RUN", observer=OBSERVER_POSE, unit="m",
                        clock="sim", threshold={"min_gap_m": threshold_m}, evidence=[])
    worst = math.inf
    worst_at = None
    for pose, other in pair_samples:
        gap = footprint_clearance_m(pose, other, footprints[pose.robot_id],
                                    footprints[other.robot_id])
        if gap < worst:
            worst, worst_at = gap, pose.t
    ok = worst >= threshold_m
    return _verdict("clearance", "PASS" if ok else "FAIL", observer=OBSERVER_POSE,
                    unit="m", clock="sim", threshold={"min_gap_m": threshold_m},
                    evidence=[{"min_gap_m": round(worst, 4), "at_t": worst_at}])


def contacts(events: list[ContactEvent], *, robot_ids, positive_control_passed: bool,
             collision_inconclusive: bool = False) -> dict:
    """contact 0건 단언. 양성 대조 미통과면 단언 금지(NOT_RUN)."""
    if not positive_control_passed:
        return _verdict("contacts", "NOT_RUN", observer=OBSERVER_CONTACT, unit="count",
                        clock="sim", threshold={"contacts": 0},
                        evidence=[{"reason": "positive contact control not passed; "
                                             "zero-contact assertion is forbidden"}])
    mine = [e for e in events if e.robot_id in robot_ids]
    if mine:
        return _verdict("contacts", "FAIL", observer=OBSERVER_CONTACT, unit="count",
                        clock="sim", threshold={"contacts": 0},
                        evidence=[{"at_t": e.t, "other": e.other} for e in mine])
    if collision_inconclusive:
        return _verdict("contacts", "INCONCLUSIVE", observer=OBSERVER_CONTACT, unit="count",
                        clock="sim", threshold={"contacts": 0},
                        evidence=[{"reason": "observation gap exceeded; no-contact is "
                                             "not provable"}])
    return _verdict("contacts", "PASS", observer=OBSERVER_CONTACT, unit="count",
                    clock="sim", threshold={"contacts": 0}, evidence=[])


def observation_gaps(samples: list[PoseSample], *, robot_id: str,
                     max_gap_s: float = MAX_GAP_S) -> dict:
    """관측 빈 구간. 빈 구간 > 0.15 s 면 충돌 계열 판정은 INCONCLUSIVE 다."""
    owned = sorted((s for s in samples if s.robot_id == robot_id), key=lambda s: s.t)
    gaps = [(b.t - a.t, a.t) for a, b in zip(owned, owned[1:])]
    worst = max((g for g, _ in gaps), default=0.0)
    return {
        "max_gap_s": worst,
        "inconclusive_collision": worst > max_gap_s,
        "evidence": [{"gap_s": round(g, 3), "after_t": t} for g, t in gaps if g > max_gap_s],
    }


def observation_rate_hz(samples: list[PoseSample], *, robot_id: str,
                        span_s: float | None = None) -> float:
    owned = [s for s in samples if s.robot_id == robot_id]
    if len(owned) < 2:
        return 0.0
    window = owned if span_s is None else owned[-max(2, int(span_s * MIN_OBSERVATION_HZ)):]
    span = window[-1].t - window[0].t
    return 0.0 if span <= 0 else (len(window) - 1) / span


def rate_verdict(samples, *, robot_id: str, min_hz: float = MIN_OBSERVATION_HZ) -> dict:
    rate = observation_rate_hz(samples, robot_id=robot_id)
    return _verdict("observation-rate", "PASS" if rate >= min_hz else "FAIL",
                    observer=OBSERVER_POSE, unit="Hz", clock="sim",
                    threshold={"min_hz": min_hz}, evidence=[{"measured_hz": round(rate, 2)}])


def frame_consistency(samples: list[PoseSample], *, robot_id: str,
                      expected_frame: str = "map") -> dict:
    """map/odom 혼용 판정 — 관측 frame 이 섞이면 위치 단언의 근거가 무너진다."""
    frames = {s.frame for s in samples if s.robot_id == robot_id}
    foreign = sorted(frames - {expected_frame})
    if foreign:
        return _verdict("frame-consistency", "FAIL", observer=OBSERVER_POSE, unit="frame",
                        clock="sim", threshold={"expected": expected_frame},
                        evidence=[{"foreign_frames": foreign}])
    return _verdict("frame-consistency", "PASS", observer=OBSERVER_POSE, unit="frame",
                    clock="sim", threshold={"expected": expected_frame}, evidence=[])


def displacement_m(samples: list[PoseSample], *, robot_id: str) -> float:
    """관측된 이동량(경로 길이). 성공 이벤트만 있고 이동 없음을 잡는 근거."""
    owned = sorted((s for s in samples if s.robot_id == robot_id), key=lambda s: s.t)
    return sum(math.hypot(b.x - a.x, b.y - a.y) for a, b in zip(owned, owned[1:]))


def claimed_motion_verdict(*, displacement: float, terminal_status: str | None,
                           min_travel_m: float = 0.05) -> dict:
    """성공 이벤트(completed) 없이 이동한 경우·성공만 있고 이동 없는 경우 모두 잡는다."""
    completed = terminal_status in ("COMPLETED",)
    if completed and displacement < min_travel_m:
        return _verdict("claimed-motion", "FAIL", observer=OBSERVER_POSE, unit="m",
                        clock="sim", threshold={"min_travel_m": min_travel_m},
                        evidence=[{"displacement_m": round(displacement, 4),
                                   "terminal": terminal_status}])
    return _verdict("claimed-motion", "PASS", observer=OBSERVER_POSE, unit="m",
                    clock="sim", threshold={"min_travel_m": min_travel_m},
                    evidence=[{"displacement_m": round(displacement, 4),
                               "terminal": terminal_status}])


def stale_pose(samples: list[PoseSample], *, robot_id: str, now_mono: float,
               max_age_s: float = 1.0) -> dict:
    """마지막 관측의 monotonic 나이 — 네트워크 시한 계열. 늙으면 위치 단언 INCONCLUSIVE."""
    owned = [s for s in samples if s.robot_id == robot_id]
    if not owned:
        return _verdict("pose-freshness", "NOT_RUN", observer=OBSERVER_POSE, unit="s",
                        clock="monotonic", threshold={"max_age_s": max_age_s}, evidence=[])
    age = now_mono - max(s.mono for s in owned)
    verdict = "PASS" if age <= max_age_s else "INCONCLUSIVE"
    return _verdict("pose-freshness", verdict, observer=OBSERVER_POSE, unit="s",
                    clock="monotonic", threshold={"max_age_s": max_age_s},
                    evidence=[{"age_s": round(age, 3)}])


def epoch_cut(samples: list[PoseSample], *, pause_at_t: float) -> tuple[list, list]:
    """pause/reset 은 새 epoch — 경계 이전 관측은 이후 단언에 이어 붙이지 않는다."""
    before = [s for s in samples if s.t < pause_at_t]
    after = [s for s in samples if s.t >= pause_at_t]
    return before, after


def wrong_robot_motion(samples: list[PoseSample], *, commanded: str,
                       min_travel_m: float = 0.05) -> dict:
    """명령받지 않은 로봇의 이동 — 다른 로봇 오작동 0(M01)의 근거."""
    strangers = sorted({s.robot_id for s in samples} - {commanded})
    moved = [rid for rid in strangers
             if displacement_m(samples, robot_id=rid) >= min_travel_m]
    return _verdict(
        "stranger-motion", "FAIL" if moved else "PASS", observer=OBSERVER_POSE,
        unit="m", clock="sim", threshold={"min_travel_m": min_travel_m},
        evidence=[{"moved": moved}])
