"""관측 서버 시험 — 합성 프레임으로 분류기와 경계를 고정한다.

합성 프레임 통과가 실물 보장은 아니다(수용 계획 §5: 합성 ≠ DEVICE). 실촬 프레임
회귀 세트는 벤치에서 수집해 이 파일에 합류시킨다. 네트워크·실제 카메라 없음.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from observer import (
    ObserverConfig,
    ObserverConfigError,
    Roi,
    classify_frame,
    create_app,
    load_config,
)

#: BGR 색 — 판정은 HSV 에서 하니까 여기선 "그 색으로 보이는 BGR"만 맞으면 된다.
RED_BGR = (0, 0, 255)
ORANGE_BGR = (0, 140, 255)
GREEN_BGR = (80, 220, 80)
BLACK_BGR = (10, 10, 10)

SIZE = (240, 320)  # (h, w)


def make_frame(lenses: dict[str, tuple[int, int, int]]) -> np.ndarray:
    """검은 판에 렌즈를 그린 합성 프레임. 키는 ROI 이름."""
    frame = np.full((SIZE[0], SIZE[1], 3), BLACK_BGR, dtype=np.uint8)
    # cv2.circle 의 중심은 (x, y). ROI(left 40–80, mid 140–180, right 220–260) 안에 맞춘다.
    centers = {"left": (60, 60), "mid": (160, 60), "right": (240, 60),
               "beacon": (160, 20)}
    for name, color in lenses.items():
        cx, cy = centers[name]
        cv2.circle(frame, (cx, cy), 24, color, -1)
    return frame


ROIS = [
    Roi("left", 40, 30, 40, 60),
    Roi("mid", 140, 30, 40, 60),
    Roi("right", 220, 30, 40, 60),
]


def by_name(readings):
    return {r.name: r for r in readings}


# --- classifier ------------------------------------------------------------------


def test_a_lit_red_lens_is_lit_and_red():
    readings = classify_frame(make_frame({"left": RED_BGR}), ROIS)
    rows = by_name(readings)
    assert rows["left"].lit is True
    assert rows["left"].group == "red"


def test_an_unlit_lens_is_reported_as_off_not_as_a_color():
    """꺼진 램프를 '색 모름'이 아니라 꺼짐으로 답한다 — 다크 ROI 는 group 이 None."""
    readings = classify_frame(make_frame({}), ROIS)
    rows = by_name(readings)
    assert all(r.lit is False and r.group is None for r in rows.values())


def test_orange_and_green_are_told_apart():
    frame = make_frame({"mid": ORANGE_BGR, "right": GREEN_BGR})
    rows = by_name(classify_frame(frame, ROIS))
    assert rows["mid"].group == "orange"
    assert rows["right"].group in ("green", "blue")   # 청록 계열은 green/blue 경계에 있을 수 있다
    assert rows["mid"].group != rows["right"].group


def test_reading_order_follows_roi_order():
    frame = make_frame({"left": RED_BGR, "right": GREEN_BGR})
    names = [r.name for r in classify_frame(frame, ROIS)]
    assert names == ["left", "mid", "right"]


def test_roi_outside_the_frame_is_off_without_crashing():
    bad = [Roi("offscreen", 500, 500, 40, 40)]
    rows = by_name(classify_frame(make_frame({"left": RED_BGR}), bad))
    assert rows["offscreen"].lit is False


def test_same_frame_same_answer():
    """관측은 결정론적이어야 한다 — 같은 프레임, 같은 답."""
    frame = make_frame({"left": RED_BGR, "mid": ORANGE_BGR})
    a = classify_frame(frame, ROIS)
    b = classify_frame(frame, ROIS)
    assert a == b


# --- config --------------------------------------------------------------------

def test_config_roundtrip(tmp_path):
    import json
    path = tmp_path / "observer.json"
    path.write_text(json.dumps({
        "camera": 1,
        "rois": [{"name": "left", "x": 10, "y": 20, "w": 30, "h": 40}],
        "thresholds": {"lit_value_min": 80, "lit_sat_min": 50},
    }), encoding="utf-8")
    cfg = load_config(path)
    assert cfg.camera == 1
    assert cfg.rois == (Roi("left", 10, 20, 30, 40),)
    assert cfg.lit_value_min == 80
    assert cfg.freeze_after_s == 5.0


@pytest.mark.parametrize("bad", [
    {"rois": []},
    {"camera": -1, "rois": [{"name": "a", "x": 1, "y": 1, "w": 1, "h": 1}]},
    {"camera": 0, "rois": [{"name": "a", "x": -5, "y": 1, "w": 1, "h": 1}]},
    {"camera": 0, "rois": [{"name": "a", "x": 1, "y": 1, "w": 1, "h": 1},
                           {"name": "a", "x": 2, "y": 2, "w": 1, "h": 1}]},
    # 프레임 경계 밖 ROI — 로더에서 거절한다(자르기 실패를 판정으로 위장하지 않는다)
    {"camera": 0, "rois": [{"name": "a", "x": 640, "y": 1, "w": 40, "h": 1}]},
    {"camera": 0, "rois": [{"name": "a", "x": 1, "y": 470, "w": 1, "h": 40}]},
    {"camera": 0, "frame_width": 0,
     "rois": [{"name": "a", "x": 1, "y": 1, "w": 1, "h": 1}]},
    # 동결 예산 — 0 이하면 언제나(또는 절대) 동결이 되어 관측이 쓸모없다
    {"camera": 0, "freeze_after_s": -1,
     "rois": [{"name": "a", "x": 1, "y": 1, "w": 1, "h": 1}]},
    {"camera": 0, "freeze_after_s": "five",
     "rois": [{"name": "a", "x": 1, "y": 1, "w": 1, "h": 1}]},
])
def test_bad_configs_are_refused(tmp_path, bad):
    import json
    path = tmp_path / "observer.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ObserverConfigError):
        load_config(path)


# --- 프레임 소스 (Pi 배치 가능성의 접점) ------------------------------------------

def test_file_source_replays_recorded_frames(tmp_path):
    """벤치에서 촬영한 프레임을 기록해 두면 같은 분류기가 그대로 재생 판정한다 —
    Pi 배치(picamera2)도 이 소스 경계 뒤에 있는 것과 같은 이치다."""
    import cv2
    from observer import ObserverConfig, make_source
    for i, color in enumerate((RED_BGR, GREEN_BGR)):
        frame = np.full((120, 160, 3), BLACK_BGR, dtype=np.uint8)
        cv2.circle(frame, (80, 60), 30, color, -1)
        cv2.imwrite(str(tmp_path / f"f{i}.png"), frame)
    cfg = ObserverConfig(rois=(Roi("mid", 50, 30, 60, 60),),
                         source={"type": "file", "path": str(tmp_path)})
    grab = make_source(cfg)
    first = by_name(classify_frame(grab(), cfg.rois))["mid"]
    assert first.lit is True and first.group == "red"
    second = by_name(classify_frame(grab(), cfg.rois))["mid"]
    assert second.group in ("green", "blue")


def test_unknown_source_type_is_refused(tmp_path):
    from observer import ObserverConfig, make_source
    cfg = ObserverConfig(rois=(Roi("a", 1, 1, 2, 2),),
                         source={"type": "banana"})
    with pytest.raises(ObserverConfigError):
        make_source(cfg)


def test_picamera2_outside_pi_is_a_clear_refusal():
    """picamera2 가 없는 호스트에서는 'Pi 용'이라고 명확히 거절한다 — 알 수 없는
    ImportError 로 관측이 죽지 않게."""
    from observer import ObserverConfig, make_source
    cfg = ObserverConfig(rois=(Roi("a", 1, 1, 2, 2),),
                         source={"type": "picamera2"})
    try:
        make_source(cfg)
        pytest.skip("picamera2 installed on this host")
    except ObserverConfigError:
        pass


# --- 안정 상태 (debounce) ---------------------------------------------------------

def test_stable_needs_two_consecutive_frames():
    """한 프레임 반짝임은 stable 을 바꾸지 못한다 — 두 프레임 연속 일치가 조건이다."""
    cfg = ObserverConfig(rois=tuple(ROIS), stable_after=2)
    frame = make_frame({"left": RED_BGR})
    client = _client([frame, frame], config=cfg)
    first = client.get("/observed").json()
    assert first["lamps"]["left"]["lit"] is True              # raw 는 즉시
    assert first["stable"]["left"]["lit"] is None             # stable 은 아직
    assert first["stable"]["left"]["pending"] is True
    second = client.get("/observed").json()
    assert second["stable"]["left"]["lit"] is True
    assert second["stable"]["left"]["pending"] is False


def test_stable_holds_through_a_single_frame_glitch():
    """빨강으로 안정된 뒤 초록 한 프레임이 반짝여도 stable 은 유지된다."""
    cfg = ObserverConfig(rois=tuple(ROIS), stable_after=2)
    red = make_frame({"left": RED_BGR})
    green = make_frame({"left": GREEN_BGR})
    client = _client([red, red, green, green], config=cfg)
    client.get("/observed")
    client.get("/observed")
    mid = client.get("/observed").json()
    assert mid["lamps"]["left"]["group"] in ("green", "blue")  # raw 는 이미 바뀌었다
    assert mid["stable"]["left"]["lit"] is True                # 아직 직전 안정 상태 유지
    assert mid["stable"]["left"]["pending"] is True
    final = client.get("/observed").json()
    assert final["stable"]["left"]["pending"] is False


def test_stable_after_one_is_pass_through(tmp_path):
    """stable_after=1 이면 안정화가 사실상 꺼진다 — 바로 stable 이 따라간다."""
    cfg = ObserverConfig(rois=tuple(ROIS), stable_after=1)
    client = _client([make_frame({"left": RED_BGR})], config=cfg)
    body = client.get("/observed").json()
    assert body["stable"]["left"]["lit"] is True
    assert body["stable"]["left"]["pending"] is False


# --- preview (캘리브레이션 조격) ----------------------------------------------------

def test_preview_returns_annotated_jpeg_after_first_observation():
    client = _client([make_frame({"left": RED_BGR})])
    client.get("/observed")                       # 프레임을 하나 확보한 뒤에
    resp = client.get("/preview.jpeg")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    assert resp.content[:2] == b"\xff\xd8"        # JPEG magic


def test_preview_is_503_before_any_frame():
    assert _client([]).get("/preview.jpeg").status_code == 503


def test_preview_captures_its_own_frame():
    """/observed 없이도 자기 프레임을 캡처한다 — 캘리브레이션이 관측 호출을 안 타게."""
    resp = _client([make_frame({"left": RED_BGR})]).get("/preview.jpeg")
    assert resp.status_code == 200
    assert resp.content[:2] == b"\xff\xd8"


# --- 프레임 동결 (낡은 증거로 확정 만들지 않기) --------------------------------------

def test_observed_carries_frame_identity_and_age():
    """frame_id/captured_at/age_s/frozen — 소비자가 '몇 초 전 증거'를 가릴 수 있게."""
    now = [1000.0]
    client = _client([make_frame({"left": RED_BGR}), make_frame({"left": GREEN_BGR})],
                     clock=lambda: now[0])
    first = client.get("/observed").json()
    assert first["frame_id"] == 1
    assert first["frozen"] is False
    assert first["age_s"] == 0.0
    now[0] += 6.0                      # 내용이 바뀌었다 — 캡처는 새로이다, 동결 없음
    second = client.get("/observed").json()
    assert second["frame_id"] == 2
    assert second["frozen"] is False


def test_a_frozen_frame_demotes_stable_to_unknown():
    """같은 내용이 계속되면 정보는 낡은 것이다 — CONFIRMED 를 만들지 말 것."""
    cfg = ObserverConfig(rois=tuple(ROIS), stable_after=2, freeze_after_s=5.0)
    now = [1000.0]
    frame = make_frame({"left": RED_BGR})
    client = _client([frame, frame], config=cfg, clock=lambda: now[0])
    first = client.get("/observed").json()
    assert first["frozen"] is False
    now[0] += 6.0                      # 내용 변화 없음 — 프레임이 멈춘 셈이다
    second = client.get("/observed").json()
    assert second["frozen"] is True
    assert second["frame_id"] == first["frame_id"]      # 내용이 안 오른다
    assert second["stable"]["left"] == {"lit": None, "group": None,
                                        "pending": True, "stale": True}
    assert second["lamps"]["left"]["lit"] is True       # 그 프레임의 사실 자체는 남긴다


def test_unfreezing_restarts_the_debounce():
    """동결에서 깨어나면 멈춘 구간을 이어 붙이지 않는다 — debounce 를 새로 돈다."""
    cfg = ObserverConfig(rois=tuple(ROIS), stable_after=2, freeze_after_s=5.0)
    now = [1000.0]
    client = _client([make_frame({"left": RED_BGR}), make_frame({"left": RED_BGR}),
                      make_frame({"left": GREEN_BGR})],
                     config=cfg, clock=lambda: now[0])
    first = client.get("/observed").json()          # 아직 안정화 전
    assert first["stable"]["left"]["pending"] is True
    now[0] += 6.0
    frozen = client.get("/observed").json()         # 동결 → 강등 + 이력 소거
    assert frozen["frozen"] is True
    now[0] += 6.0
    fresh = client.get("/observed").json()          # 내용이 바뀜 → 동결 해제
    assert fresh["frozen"] is False
    assert fresh["stable"]["left"]["pending"] is True
    assert fresh["stable"]["left"]["lit"] is None


def test_config_rejects_non_positive_stable_after(tmp_path):
    import json
    path = tmp_path / "observer.json"
    path.write_text(json.dumps({
        "camera": 0, "stable_after": 0,
        "rois": [{"name": "a", "x": 1, "y": 1, "w": 1, "h": 1}]}), encoding="utf-8")
    with pytest.raises(ObserverConfigError):
        load_config(path)


# --- HTTP 경계 -------------------------------------------------------------------

def _client(frames, config: "ObserverConfig | None" = None, *, clock=None):
    source = iter(frames)

    def grab():
        try:
            return next(source)
        except StopIteration:
            return None

    cfg = config or ObserverConfig(camera=0, rois=tuple(ROIS))
    app = create_app(grab, cfg) if clock is None else create_app(grab, cfg, clock=clock)
    return TestClient(app)


def test_observed_answers_the_classified_frame():
    frame = make_frame({"left": RED_BGR})
    body = _client([frame]).get("/observed").json()
    assert body["lamps"]["left"]["lit"] is True
    assert body["lamps"]["left"]["group"] == "red"
    assert "ts" in body


def test_no_frame_is_503_not_a_fake_reading():
    """카메라가 프레임을 못 주면 없는 판독을 만들지 않는다 — 503 이다."""
    assert _client([None]).get("/observed").status_code == 503


def test_there_is_no_command_path():
    """관측 서버의 존재 이유는 읽기 전용이다 — 명령 경로가 있으면 이 설계는 무너진다."""
    client = _client([])
    assert client.post("/observed", json={"mode": "all_red"}).status_code == 405
    assert client.get("/healthz").json() == {"ok": True}
