# 필드 경계 자동 캘리브레이션 — 설계 및 실행 계획 (D-484)

날짜: 2026-10-06 · 브랜치: `feat/vision-field-auto-calib` · ADR: [D-484](../adr/D-484-field-boundary-auto-calibration.md)

## 목표

- 코너 ArUco 마커 없이, 천장 카메라 프레임의 흰 경계 사각형(D-360)과 Fleet 사이트 맵 사각형
  (`corner_world_m`)만으로 매-주기 측정 캘리브레이션을 유지한다.
- 회전 대응(이미지 코너 ↔ 맵 코너)은 사람 입력 없이 D-375 페인트 정합으로 확정한다.
- 보정된(top-down) 미리보기 영상을 자동으로 송출한다(D-318 수동 드래그 대체).
- 로봇 ArUco 마커 관측, 폰 앱, 전선, 정책 증거 의미는 그대로 둔다.

## 구조

```
폰 앱(변경 없음) ── rosy-overhead/1 ──▶ IngestServer(원본 최신 프레임만)
                                            ▲ report_field(수용 사각형·상태)
VisionWorker.process_latest()               │
  ├ 매 프레임: 로봇 ArUco 감지 → 캐시 호모그래피로 투영/sighting
  ├ 주기(1 Hz): detect_field(to_thread) → FieldCalibrator.feed(안정성 게이트)
  ├ orientation 미확정 시에만: map_worker 프로세스에 페인트 정합 1회(단일 flight)
  │    → 수용되면 map_to_image로 맵 코너 투영 ↔ 감지 코너 최근접 대응 → 확정
  └ FieldCalibrator.homography() = games fit(사각형, 회전된 corner_world_m)
미리보기: lease rectification mode:"auto" → 수용 사각형으로 warpPerspective 송출
```

## 상태 머신 (`rosy_vision/field_calib.py`, 신규)

- `no_field` — 사각형 없음(초기·상실). 상실 시 orientation도 지운다.
- `orientation_pending` — 사각형은 수용, 회전 미확정. sighting 없음, 사유 표시.
- `calibrated` — 회전 확정 + 수용 사각형. 호모그래지 제공.
- `stale` — 코너 급변. 연속 일관 감지(기본 3회) 후 재수용; 종횡비가 뒤집히면 orientation
  초기화(재정합). 재획득 전 sighting 없음.

상수: 재획득 문턱(코너 최대 이동) = 대각선의 1.5%, orientation 거리 게이트 = 대각선의 5%,
상실 = 연속 5회 감지 실패(약 5 s), 페인트 재시도 최소 간격 5 s. 모두 생성자로 덮을 수 있다.

## 회전 판정

맵 코너 `c` 를 `map_to_image`(3×3)로 이미지에 투영, 감지 코너 4개 중 최근접과 대응.
전 두 가지를 다 통과해야 확정: (1) 모든 거리 ≤ 게이트, (2) 대응이 순환 일대일
(quad[i] ↔ world[(i+r)%4], 단일 r). 아니면 거부(사유). 4후보 시험이 아니라 정합이 주는
답을 검증만 한다.

## 파일별 변경

| 파일 | 변경 |
|------|------|
| `core_common/protocol/sightings.py` | `corner_marker_ids` 선택화, `calibration_source` 추가(값 제한), 상호 검증 |
| `core_common/protocol/vision_preview.py` | `PreviewRectification.mode: manual\|auto` (additive) |
| `rosy_vision/field_calib.py` (신규) | 상태 머신·안정성 게이트·orientation 판정·호모그래피 (cv2 금지, 순수 파이썬) |
| `rosy_vision/project.py` | `CameraMap.calibration_source`, `corner_marker_ids` 선택화, `project_frame(homography=...)` |
| `rosy_vision/worker.py` | 주기 감지·정합 요청·`report_field` 배선 |
| `rosy_vision/ingest.py` | `report_field` 저장, 미리보기 `mode:"auto"` 경로, `X-Frame-Rectified: auto` |
| `rosy_vision/vision_config.py` | `calibration_source` 검증 |
| `rosy_vision/cli.py` | field 소스에 calibrator·페인트 실행기 주입, `--map-paint` 필요 검증 |
| `fleet/server/sightings.py` | `SightingSource.calibration_source`, `site_map()` null 안전 |
| `fleet/server/sightings_config.py` | field_boundary 검증(corner_world_m 필수) |
| `fleet/server/web/vision-view.js` | "자동 보정" 보기 모드 |
| `docs/reference/ROSY API & Protocol Reference.md` | additive 버전 행 |

## 시험

- `test_field_calib.py`(신규): 상태 전이 전부, 급변·상실·재획득, orientation 거리/순환 게이트.
- `test_vision_project.py`, `test_vision_worker.py`, `test_preview_rectification.py`,
  `test_vision_config.py`, fleet 설정·수리 시험, contracts payload 시험 확장.
- 저장소 규칙: `X:\DevTemp\field-auto-calib\run.txt` + `test/known_failures.py` 비교.
