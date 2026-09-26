"""protocol 스키마 단위 테스트 (P1-19) — ROSY-API-REF-001 §7 대응."""

import pytest

from core_common.protocol.schemas import (
    AckPayload,
    AckStatus,
    Envelope,
    EnvelopeType,
    EventMessage,
    PoseSample,
    RobotMode,
    Severity,
    StateSnapshot,
    SwarmFollowParams,
    SwarmRole,
    SwarmStatus,
    VisionPreviewStatus,
)


def test_robot_mode_has_no_soccer():
    """D-90: 축구는 게임 호스트다. CORE 모드가 아니다."""
    assert "SOCCER" not in RobotMode.__members__
    assert set(RobotMode) == {
        RobotMode.IDLE,
        RobotMode.MANUAL,
        RobotMode.NAVIGATION,
        RobotMode.DOCKING,
        RobotMode.EMERGENCY,
    }


def test_envelope_defaults():
    env = Envelope(type=EnvelopeType.HEARTBEAT, payload={})
    assert env.protocol_version == "1.0"
    assert env.msg_id
    assert env.correlation_id is None


def test_envelope_roundtrip():
    env = Envelope(type=EnvelopeType.ACK, correlation_id="c-1", payload=AckPayload(status=AckStatus.ACCEPTED).model_dump())
    assert Envelope.model_validate(env.model_dump()) == env


def test_event_model_seq_monotone_field():
    e1 = EventMessage(seq=1, robot_id="rosy_01", type="nav.completed")
    e2 = EventMessage(seq=2, robot_id="rosy_01", type="safety.estop", severity=Severity.CRITICAL)
    assert e2.seq > e1.seq
    assert e1.event_id != e2.event_id


def test_state_snapshot_defaults():
    snap = StateSnapshot(robot_id="rosy_01")
    assert snap.mode.value == "IDLE"
    assert snap.navigation.value == "IDLE"
    assert snap.evidence == {}


def test_vision_preview_status_contract():
    status = VisionPreviewStatus(
        available=True,
        stale=False,
        source="GAZEBO",
        frame_id="front_camera",
        captured_at=42.5,
        age_ms=80,
        width=640,
        height=360,
        overlay="semantic-road-v1",
        sequence=7,
    )
    assert status.model_dump() == {
        "available": True,
        "stale": False,
        "source": "GAZEBO",
        "frame_id": "front_camera",
        "captured_at": 42.5,
        "age_ms": 80,
        "width": 640,
        "height": 360,
        "overlay": "semantic-road-v1",
        "sequence": 7,
    }


def test_state_snapshot_evidence_is_additive():
    """v1.8: evidence 없는 구 페이로드도 읽고, 모르는 채널 키는 유지한다(API-002)."""
    dumped = StateSnapshot(robot_id="rosy_01").model_dump()
    dumped.pop("evidence", None)
    restored = StateSnapshot.model_validate(dumped)
    assert restored.evidence == {}

    from core_common.protocol.evidence import EvidenceState, ValueEvidence

    snap = StateSnapshot(
        robot_id="rosy_01",
        evidence={
            "pose": ValueEvidence(evidence=EvidenceState.FRESH, stale_after_s=2.0),
            "custom_channel": ValueEvidence(evidence=EvidenceState.UNAVAILABLE),
        },
    )
    roundtrip = StateSnapshot.model_validate(snap.model_dump())
    assert roundtrip.evidence["pose"].evidence is EvidenceState.FRESH
    assert "custom_channel" in roundtrip.evidence


def test_swarm_status_additive_default():
    """v1.1 additive: swarm 필드 기본값 — 기존 소비자 영향 없음 (CAP-002)."""
    snap = StateSnapshot(robot_id="rosy_01")
    assert snap.swarm.role == SwarmRole.NONE
    assert snap.swarm.active is False
    snap2 = StateSnapshot.model_validate(snap.model_dump())  # 직렬화 왕복
    assert snap2.swarm.role == SwarmRole.NONE


def test_swarm_follow_params_defaults():
    p = SwarmFollowParams(target_robot_id="rosy_02")
    assert p.distance == 0.5 and p.lateral == 0.0
    assert p.max_speed == 0.15 and p.stream_timeout_ms == 1000
    assert p.source.value == "fleet"  # v1.2 additive 기본값 — 기존 소비자 호환 (D-21)


def test_pose_stream_envelope():
    sample = PoseSample(robot_id="rosy_01", pose={"x": 1.0, "y": 0.0, "yaw": 0.1}, seq=1)
    env = Envelope(type=EnvelopeType.POSE, payload=sample.model_dump())
    assert Envelope.model_validate(env.model_dump()).type == EnvelopeType.POSE
    parsed = PoseSample.model_validate(env.payload)
    assert parsed.pose.x == 1.0 and parsed.seq == 1


def _detection(**kwargs):
    from core_common.protocol.detections import Detection
    options = dict(label="person", x=0.4, y=0.3, w=0.2, h=0.4, confidence=0.8)
    options.update(kwargs)
    return Detection(**options)


def _evidence(**kwargs):
    from core_common.protocol.detections import DetectionEvidence
    options = dict(model_revision="yolo11n-r1", observed_at=1000.0, seq=41,
                   input_width=640, input_height=640, input_fps=10.0,
                   detections=[_detection()])
    options.update(kwargs)
    return DetectionEvidence(**options)


def test_detection_evidence_roundtrip():
    from core_common.protocol.detections import DetectionEvidence
    ev = _evidence()
    assert DetectionEvidence.model_validate(ev.model_dump()) == ev
    assert ev.detections[0].label == "person"


def test_detection_bounds_are_normalized():
    import pydantic
    with pytest.raises(pydantic.ValidationError):
        _detection(x=0.9, w=0.2)          # x+w > 1
    with pytest.raises(pydantic.ValidationError):
        _detection(confidence=1.5)
    with pytest.raises(pydantic.ValidationError):
        _detection(label="")


def test_evidence_revision_and_seq_are_required():
    import pydantic
    with pytest.raises(pydantic.ValidationError):
        _evidence(model_revision="")
    with pytest.raises(pydantic.ValidationError):
        _evidence(seq=-1)
    with pytest.raises(pydantic.ValidationError):
        _evidence(input_width=0)


def test_inference_latency_meta_is_additive_and_optional():
    """v1.11 additive: 지연 메타 없는 구 패킷도 여전히 유효하다 (plan T2)."""
    import pydantic
    from core_common.protocol.detections import DetectionEvidence
    ev = _evidence()
    assert ev.inference_ms is None
    assert DetectionEvidence.model_validate(ev.model_dump()) == ev
    with pytest.raises(pydantic.ValidationError):
        _evidence(inference_ms=-1.0)
    with pytest.raises(pydantic.ValidationError):
        _evidence(inference_ms=float("nan"))
    timed = _evidence(inference_ms=12.3)
    assert DetectionEvidence.model_validate(timed.model_dump()).inference_ms == 12.3


def test_freshness_boundary_is_300ms():
    """D-136: 신선도 >300ms면 INVALID — 깨진 영상의 clear가 제일 위험하다."""
    ev = _evidence(observed_at=1000.0)
    assert ev.fresh(now=1000.29)
    assert not ev.fresh(now=1000.31)


def test_empty_detections_is_absence_not_loss():
    """빈 detections + seq 전진 = "없는 것". seq 점프 = "못 본 것"."""
    ev = _evidence(detections=[], seq=42)
    assert ev.detections == []
    assert ev.gap_after(last_seq=41) == 0
    assert ev.gap_after(last_seq=39) == 2


def test_of_label_filters_by_confidence():
    ev = _evidence(detections=[_detection(label="person", confidence=0.8),
                               _detection(label="person", confidence=0.3),
                               _detection(label="box", confidence=0.9)])
    assert len(ev.of_label("person", min_confidence=0.5)) == 1
    assert len(ev.of_label("box")) == 1
    assert ev.of_label("forklift") == []
