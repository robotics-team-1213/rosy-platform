# 현장 트랙 교체와 천장 카메라 로봇 인식

트랙(매트·차선)이 바뀌었을 때 새 CAD를 반영하고, 천장 카메라가 로봇을 다시 찾게 하는 순서다. 2026-10-31 261026 월드로 실제 진행하며 확인한 사실만 적었다. 카메라 설치·페어링은 [천장 카메라 가이드](site-ceiling-camera-console-runbook.md), 로봇 등록은 같은 문서 6절을 따른다.

## 한눈에 보기

| 단계 | 하는 사람 | 도구 | 끝 판정 |
|---|---|---|---|
| 1. 지금 지도가 실제 바닥과 맞는지 판정 | 누구나 | 관제 **관제 카메라 → 맵 자동 맞춤** | 맞춤이 수락되면 2~3단계를 건너뛴다 |
| 2. 새 CAD에서 차선 페인트 추출 | 개발자 | `tools/calibration/extract_world_paint.py`(트랙마다 원본 해시·번들 경로 고정) | `meshes/road_lines.json`의 매트 크기·페인트 면적이 실물과 맞다 |
| 3. 카메라 프레임에 새 페인트 정합 | 개발자 | `rosy_vision.map_register` (Vision 이미지 안) | recall·precision ≥ 0.8, 겹친 그림에서 흰 테이프 위에 선이 놓인다 |
| 4. 새 지도 그리기·활성화 | 운영자 | 관제 **지도** 화면(도면 올리기·그리기·검토·활성화), `stl_floor_layer.py` | 새 `map_id` 활성, 카메라 교정 수락 |
| 5. 로봇 인식 | 운영자 | 관제 로봇 카드 **위치 찍기**, **배경 다시 학습**, **LED로 찾기** | 로봇 카드 위치가 카메라 기준으로 표시된다 |

## 1. 지금 지도가 맞는지 판정

관제 **맵 자동 맞춤**이 거부되고 "weak paint match"이면 지도와 바닥이 다른 트랙일 수 있다. 2026-10-31에는 `map_v2_fleet`(2.81 × 1.26 m)이 0.47로 거부됐다. 실제 바닥은 261026 트랙(2.44 × 1.22 m)이었다.

## 2. 새 CAD에서 차선 페인트 추출

- 원본 월드 STL(수십 MB, 로봇팔 포함)은 Git에 넣지 않는다. 작업 공간 `Rosy/docs/research/map-world-<날짜>/`에 두고, sha256을 추출 스크립트에 고정한다.
- 월드 STL은 높이로 나뉜다. 위를 향한 면의 높이별 넓이를 보면 매트(가장 넓은 면)와 그 위 1 mm 페인트층이 구분된다. 261026은 매트 33.7 mm, 페인트 34.7 mm, 셀 판 105.7 mm였다.
- 좌표는 기존 지도와 같다: R_x(+90°), mm → m, 매트 중심이 원점이다.

```bash
python tools/calibration/extract_world_paint.py <월드 STL>
```

## 3. 카메라 프레임에 새 페인트 정합

노트북에는 OpenCV가 없으므로 관제 PC에서 Vision 이미지를 일회용 컨테이너로 돌린다. Vision 컨테이너 파일시스템은 읽기 전용이라 `docker cp`가 안 된다.

```bash
IMG=$(docker inspect rosy-site-vision-1 --format '{{.Config.Image}}')
docker run --rm --network none -v /tmp/fit:/tmp/fit:ro -w /tmp/fit \
  -e PYTHONPATH=/opt/rosy/src/site/vision:/opt/rosy/src/contracts/foundation \
  --entrypoint python3 "$IMG" fit.py
```

`fit.py`는 프레임 JPEG와 페인트 STL로 `register_map_jpeg`를 부르고 `accepted`·`reason`을 출력한다. 프레임은 관제 API `POST /api/fleet/vision/lease`로 받은 임대로 한 장 읽는다.

- **정합 마스크는 흰 선만 본다**(채도 ≤ 70). 분홍·초록 테이프 구역이 CAD에 흰 페인트로 있으면 recall이 떨어진다. 261026은 전체 0.71로 거부됐고, 주차 구역(y > 0.20 m)을 빼면 recall 0.85, precision 0.91, coverage 0.97로 수락됐다. 수락 기준을 낮추지 않는다. 색 테이프 구역은 정합용 페인트에서 뺀다.
- 겹친 그림으로 눈으로도 확인한다(예: `Rosy/docs/research/map-world-261026/2026-10-31-ceiling-fit-overlay.jpg`). CAD에만 있는 선과 실물에만 있는 테이프를 적어 둔다.

## 4. 사이트에 새 지도 반영 — 관제에서 직접 그린다 (D-825)

새 트랙은 이미지 배포가 아니라 관제 **지도**(`/console/site-map`)에서 그린다.

1. **도면 줄이기**: Fleet 도면 업로드는 16 MB·200,000 삼각형 이하이고, 투영은 회전·축척만 해서 거울상을 만들 수 없다. 큰 월드 STL은 바닥층만 남기고 Z-up으로 바꾼다.

   ```bash
   python tools/calibration/stl_floor_layer.py <월드 STL> <바닥층 STL> --above-mm 80
   ```

   261026: 23,582 삼각형, 1.2 MB가 되었다. Y-up 원본을 그대로 `xz` 평면으로 투영하면 거울상이 된다.
2. **도면 올리기**: 지도 화면에서 바닥층 STL을 올린다. 평면 `xy`, 단위 `mm`, 원점 = 매트 중심(원본 좌표), 방향 0, 축척 1이다. 새 projection은 새 `map_id`를 받는다. 이전 카메라·로봇 좌표 증거는 넘어오지 않는다.
3. **그리기**: 도면 위에 차선(edge), 교차점·주차·충전 장소(place, `kind: charge|park|junction|…`), 횡단보도를 그린다. 저장은 초안만 바꾼다.
4. **축척 근거**: survey에 줄자로 잰 두 점 거리를 적는다. CAD 값만 있으면 그렇다고 쓰고 검토를 끝내지 않는다.
5. **검토 → 활성화**: 검토 메모를 남기고 활성화한다. 주행·대형·teach 중이면 활성화가 막힌다.
6. **카메라**: `site-cameras.yaml`의 `map_id`를 새 지도로 맞추고, 관제 카메라 교정을 새 지도 기준으로 다시 받는다. 이 파일을 바꾸면 `rosy-site-config-reload`가 Fleet과 Vision을 재시작한다. 몇 초간 Vision의 설정 읽기가 502를 내는 것은 정상이다. `robot_ids: enrolled`이면 등록 로봇을 카메라가 자동으로 따른다(D-580).

2026-10-31 261026: 바닥층 업로드 `a739985e…`, projection `5c7b3c3d…`, 초안 `world_261026`(장소·차선 없음, 미검토)까지 만들었다.

## 5. 로봇 인식

카메라는 배경을 배워 움직이는 물체를 찾는다. **로봇이 매트 위에 있을 때 배경을 배우면 로봇이 배경이 된다.** 그러면 관제 안내에 `CAMERA_NOT_SEEING`이 뜨고, LED 확인 결과도 `none`(후보 없음)이 된다.

1. 로봇 카드 **위치 찍기**로 지도에 로봇 위치와 방향을 찍는다. 지도가 실제 바닥과 맞아야(4단계) 의미가 있다.
2. **배경 다시 학습**(`POST /api/fleet/tracking/relearn`)을 누른다. 위치를 아는 로봇 둘레는 배경에서 빠진다. 위치를 모르는 로봇은 `unlocated`로 응답된다.
   - 위치를 찍을 수 없으면 로봇을 잠시 매트 밖으로 들어낸 뒤 다시 학습하고, 학습이 끝나면 내려놓는다.
3. 로봇 카드 **LED로 찾기**를 누른다. 로봇마다 색(파랑·주황)이 정해져 있고, 카메라가 그 점멸을 보고 트랙에 이름을 붙인다(D-596).
4. 확인: `GET /api/fleet/tracking`에서 로봇 `status`가 `NO_POSE`에서 바뀌고 `unknown` 후보가 줄어든다.

## 증상별 원인

| 증상 | 원인 | 조치 |
|---|---|---|
| LED 확인 응답의 `sources: []` | 카메라 설정 로봇 목록에 그 로봇이 없다 | `robot_ids: enrolled` |
| LED 확인 결과 `none` | 카메라가 움직이는 후보를 하나도 못 찾는다 | 5단계 배경 다시 학습 |
| `CAMERA_NOT_SEEING` | 위와 같다 | 5단계 |
| Vision `tracking config read failed ... 502` | Fleet 재시작 중 | 몇 초 뒤 자동 회복. 계속되면 프록시 로그 확인 |
| 맵 자동 맞춤 "weak paint match" | 다른 트랙의 지도이거나 색 테이프 구역 | 1·3단계 |
