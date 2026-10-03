# 천장 카메라 무마커 로봇 추적 — 설계

**결정:** 새 ADR 하나(번호는 main에 들일 때 rosy-land-on-main 절차로 정한다). 이 문서는 그 ADR의 근거다.
**상태:** 설계. 코드 0줄. ADR이 Accepted되기 전에는 구현하지 않는다.
**범위:** 표시·교차확인 전용(D-268). 로봇을 조향하지 않는다. 차선 경로 하달(Fleet 경로 → 로봇 카메라 차선유지)은 별도 설계로 뒤에 한다.

## 1. 문제

천장 카메라(Rosy Cam → Rosy Vision)는 지금 ArUco로만 로봇을 찾는다. 모서리 마커 4개(30–33)와 로봇 마커가 한 프레임에 모두 보여야 sighting이 나온다(`src/site/vision/rosy_vision/project.py`). 2026-10-01 실물 트랙에는 둘 다 없어서, 영상은 3 fps로 들어오는데(S21, `ceiling_north`) sighting은 0건이었다.

목표는 마커 없이 다음 두 가지를 하는 것이다.

1. 콘솔 지도 위에 천장 카메라가 본 로봇 위치를 그린다.
2. 그 위치를 로봇이 스스로 보고한 map 자세와 비교해 차이(교차확인)를 보여 준다.

## 2. 지금 있는 것 (저장소에서 확인)

| 사실 | 위치 |
|---|---|
| 로봇 검출은 ArUco(DICT_4X4_50)뿐 | `src/site/vision/rosy_vision/detect.py` |
| 좌표 변환은 모서리 마커 4개가 다 보일 때만 | `project.py` `project_frame` |
| sighting 계약은 `robot_id` 필수, 추가 필드 금지, 표시 전용 | `src/contracts/foundation/core_common/protocol/sightings.py` |
| Fleet sighting 수명 1.0 s | `src/site/fleet/fleet/server/sightings.py:14` |
| 차선 페인트 → 맵 맞춤(D-375)은 main에 있으나 제안 표시만, `CameraMap`에 안 들어감 | `map_register.py`, `map_worker.py` |
| 로봇 보고 자세는 map TF가 없으면 odom으로 대신하고 프레임 표시가 없음 | `src/runtime/gateway/core/bridge/ros_bridge.py:214-218` |
| D-395(Proposed)는 overhead sighting을 위치 확정 보조 단서로 쓴다 | `docs/plans/2026-10-01-fleet-assisted-localization-design.md` |
| 로봇 크기: 회전 반경 0.088 m | Pinky URDF |

## 3. 구조

```
S21 ──JPEG──▶ Vision ──익명 검출(map 좌표)──▶ Fleet ──매칭·교차확인──▶ 콘솔
               │                                ▲
               └ 승인된 보정(D-375 맞춤)          └ 로봇 자가보고 자세(이미 받는 중)
```

Vision은 영상만 아는 프로세스로 남는다. 로봇 자세를 이미 가진 곳은 Fleet이므로 매칭은 Fleet이 한다. Fleet은 계속 영상을 받지 않는다(`test_no_video_relay.py`).

## 4. 부품

### 4.1 보정 기록 (영상 → map)

- 운영자가 콘솔에서 D-375 맞춤 제안을 보고 "적용"을 누르면, 카메라 소스별 보정 기록으로 저장한다: `source_id, map_id, calibration_revision, map_to_image(3×3), fit_score, approved_by, approved_at`.
- Vision은 승인된 기록이 있을 때만 좌표를 변환한다. 기록이 없거나 소스·map이 다르면 검출을 내보내지 않고 상태를 `CALIBRATION_REQUIRED`로 둔다.
- 모서리 마커 경로(`CameraMap`)는 그대로 둔다. 둘 다 있으면 마커가 우선한다. 마커는 측정이고, 페인트 맞춤은 추정이기 때문이다.
- 카메라를 다시 달거나 렌즈를 바꾸면(`X-Source-Lens`가 달라지면) 기록은 무효가 된다.

### 4.2 검출기 (Vision, 새 `rosy_vision/track/`)

고정 인터페이스. 백엔드를 바꿔도 나머지는 바뀌지 않는다.

```python
class RobotDetector(Protocol):
    def detect(self, frame: Frame, calib: Calibration) -> DetectorResult: ...

@dataclass(frozen=True)
class Detection:
    x: float            # map m
    y: float            # map m
    footprint_m: float  # 바닥 투영 등가 지름
    score: float        # 0..1

@dataclass(frozen=True)
class DetectorResult:
    detections: tuple[Detection, ...]
    status: Literal["OK", "LEARNING", "CALIBRATION_REQUIRED", "SCENE_CHANGED"]
```

첫 백엔드 `background_blob`:

1. 빈 트랙 배경을 학습한다(MOG2 또는 이동 중앙값). 첫 10 s(3 fps에서 30프레임)는 `LEARNING`.
2. 전경 마스크에서 트랙 영역(보정 기록의 map 사각형) 밖을 지운다.
3. 연결 성분마다 바닥 투영 크기를 m로 바꿔, 등가 지름 0.12–0.26 m만 남긴다(회전 반경 0.088 m에서 유도).
4. 위치는 성분 무게중심에 높이 시차 보정을 한 값이다. 로봇 높이는 URDF에서 가져온다. 방향(yaw)은 내보내지 않는다.
5. 전경이 트랙 면적의 30%를 넘으면(조명 변화, 카메라 흔들림) 그 프레임은 `SCENE_CHANGED`로 버리고 배경을 다시 학습한다.

운영자는 콘솔에서 "배경 다시 학습"을 누를 수 있다. 숫자(10 s, 30%, 0.12–0.26 m)는 시작값이고, 실물 측정 뒤 설정으로 확정한다.

### 4.3 계약 (새 payload)

sighting은 `robot_id`가 필수라 익명 검출을 담을 수 없다. 새 경로 `POST /api/fleet/detections`(소스 토큰 인증, sighting과 같은 방식):

| 필드 | 형식 |
|---|---|
| `source_id`, `map_id`, `calibration_revision`, `processor_revision` | str |
| `captured_at` | float (Vision 시계, D-261 규칙) |
| `seq` | int, 소스별 단조 증가 |
| `status` | `DetectorResult.status` |
| `detections` | `[{x, y, footprint_m, score}]`, 최대 16개 |

- 영상, 픽셀 좌표, 로봇 id는 없다. 추가 필드는 금지한다.
- 표시 전용이다(D-268). D-395 위치 확정의 입력이 아니다. 그렇게 쓰려면 별도 결정이 필요하다.
- 계약 픽스처는 `test/fixtures/protocol/`에 두고 Vision·Fleet 테스트가 같이 읽는다.

### 4.4 매칭 (Fleet)

- Fleet은 소스별 마지막 검출을 1.0 s 동안 보관한다(sighting과 같은 수명). 오래된 것은 지운다.
- 로봇이 매칭 대상이 되려면 상태의 `map_id`가 검출의 `map_id`와 같아야 한다. 그렇지 않으면 그 로봇의 자세는 odom일 수 있으므로 `NO_POSE`다(2절 `ros_bridge.py`).
- 대상 로봇과 검출을 거리 기준 일대일로 짝짓는다(헝가리안, 게이트 0.30 m).

| 상태 | 뜻 |
|---|---|
| `MATCHED(offset_m)` | 게이트 안 검출이 있음 |
| `NO_DETECTION` | 대상 로봇인데 가까운 검출 없음 |
| `NO_POSE` | 로봇에 map 자세가 없음 |
| `CAMERA_UNAVAILABLE` | 신선한 검출 payload 없음 또는 status가 OK 아님 |

남는 검출은 `UNKNOWN_OBJECT`로 보인다.

- 결과는 `GET /api/fleet/tracking`(읽기 권한)으로 낸다. 교통정리·bays·미션은 이 결과를 읽지 않는다.

### 4.5 콘솔

- 지도에 "관제 카메라 추적" 레이어를 둔다.
- `MATCHED`: 카메라 위치에 고리, 자가보고 위치까지 가는 선, 차이 숫자. 0.15 m를 넘으면 주황.
- `UNKNOWN_OBJECT`: 회색 점.
- 상태줄: 검출기 상태(학습 중 / 보정 필요 / 장면 변화 / 오래됨), fps.
- 검출이 없으면 아무것도 그리지 않는다. 지난 값을 남기지 않는다.
- CSP `style-src 'self'`: 색과 위치는 클래스로만.

## 5. 실패 처리

| 상황 | 동작 |
|---|---|
| 프레임 끊김 | 1 s 뒤 Fleet이 지우고 `CAMERA_UNAVAILABLE` |
| 보정 revision 불일치 | Fleet이 409, 콘솔 "보정 불일치" |
| 조명 변화·카메라 흔들림 | `SCENE_CHANGED`, 배경 재학습 |
| 사람·상자가 트랙 위 | 크기로 걸러지고, 남으면 `UNKNOWN_OBJECT`. 표시 전용이라 로봇 동작에 영향 없음 |
| 로봇 두 대가 붙어 한 덩어리 | 지름 상한 초과로 버려짐 → 두 로봇 모두 `NO_DETECTION`. 분리는 학습형 백엔드에서 다룬다 |

## 6. 시험

| 단계 | 내용 | 등급 |
|---|---|---|
| 단위 | 합성 프레임(배경 + 움직이는 사각형)으로 검출기; 매칭 규칙(게이트, 일대일, `NO_POSE`, 수명); 계약 픽스처 | SOURCE |
| 재생 | 2026-10-01 실물 트랙에서 받은 프레임: 빈 트랙 → 로봇을 손으로 놓고 옮김. 정답은 수동 라벨 | LOCAL |
| 실물 | 로봇 모터 동작 없이, 사람이 로봇을 손으로 옮기며 차이 기록. G4/G5 필요 없음 | DEVICE |

합격 기준(잠정): 정지 로봇의 `MATCHED` 차이 ≤ 0.10 m, 재생 세트에서 오검출(로봇 아닌 곳의 `UNKNOWN_OBJECT`) 프레임당 평균 ≤ 0.1개. 실측 뒤 ADR에 확정 숫자를 적는다.

## 7. 하지 않는 것

- 로봇 조향, 미션·교통정리 입력, D-395 위치 확정 입력.
- 로봇 식별(어느 로봇인지)을 영상에서 하지 않는다. 식별은 자가보고 자세와의 매칭으로만 한다.
- 학습형 검출기. 인터페이스만 열어 두고, 데이터가 모이면 별도 결정으로 한다.

## 8. 다음 설계 (참고)

차선 경로 하달: 운영자가 목적 노드를 고르면 Fleet이 `lane_graph`에서 경로를 찾아 분기 선택 목록을 로봇에 보내고, 로봇은 카메라 차선유지(D-364)와 `line_follow` route로 따른다. 로봇 API가 늘어나므로 D-12에 대한 새 ADR이 필요하고, 실물 주행은 G4/G5 뒤다.
