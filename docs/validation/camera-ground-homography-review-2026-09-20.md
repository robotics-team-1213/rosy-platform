# 카메라 지면 호모그래피 초안 검토 — 수치 재계산과 수용 체크리스트

작성일: 2026-09-20
대상: 공급받은 `two_photo_checker_ground_homography` 초안 (version 2, 미착지)
상태: **수용 보류** — 포맷 게이트 미통과(context 필드 전무) + img2 후반 데이터 미수령

## 1. 수치 재계산 (본 검토의 핵심 근거)

순수 산술로 픽셀 → 지면 투영을 재계산했다 (외부 의존 없음, 2026-09-20).

### 이미지 1 (카메라-검은격자 전면 26.0cm, 12점)
- 자기정합 RMSE **0.306cm 재현** — 공급 주장치와 일치 (최대 0.536cm)

### 이미지 2 (14.8cm, 16픽셀점 — 지면점 8점만 수신)
- top-level 호모그래피 적용: 근거리(≤21.8cm) 평균 0.36cm / 원거리(>21.8cm) 평균 0.46cm
- **거리 의존적 열화 없음** — 단일 호모그래피가 18.3~36.5cm 전 대역을 ≈0.5cm 수준으로 커버한다

> **정정:** 1차 검토에서 "img2 RMSE 1.75cm·최대 3.70cm"로 보고했으나, 붙여넣기가
> 잘린 지면점 2개를 잘못 짝지은 본 검토자의 오류였다. 정정한다 — 배포 호모그래피의
> 두 캡처 적합도는 양호하다.

### 확인된 것
- top-level `image_to_ground_homography` 는 두 캡처 모두를 유효 커버
- `status: approximate_requires_physical_validation` 라벨은 정직하다

## 2. 포맷 게이트 — 현재 상태로는 저장소 수용 불가

control 의 캘리브레이션 레코드 계약(`calibration_record.py`)은 다음을 요구한다:
- `schema_version: 1` (int) — 수신본은 `version: 2`
- context 5필드: `robot_id`·`hardware_model`·`geometry_revision`·`sensor_revision`·`data_generation` — 전무
- `actor`·`recorded_at`·`revision`·`previous_digest`/`digest` 체인 — 전무

node.py 는 `ROSY_DATA_GENERATION`/`ROSY_DATA_PATH` 를 주입하고 context/generation
불일치 시 워커 생성을 차단한다. **수용 경로: 공급자가 house 형식으로 재발행하거나
`calibration_record.encode_record` 로 래핑한다.**

## 3. 내용상 갭 (공급자 요구사항)

1. 융합/선택 방법 미문서 — top-level 호모그래피가 두 캡처 중 무엇에서 왔는지 기록 없음
2. 카메라 내부파라미터·왜곡 계수 없음 — 평면 밖 확장·정합성 검증 불가
3. x축이 **보드 기준**(로봇 측면 아님) — 장착 오프셋/회전 변환 미정의
4. 커버리지: 전방 18.3~36.5cm, 측면 ±5.25cm — 36.5cm 초과는 외삽
5. `camera_to_black_grid_front` 26.0/14.8cm 의 측정 방법 미기재 — 스케일 앵커
6. 캡처 시각은 파일명(2026-09-19 15:10)뿐 — 장착 상태 동일성 보장 없음

## 4. 수용 체크리스트

### 포맷 게이트
- [ ] house 레코드 재발행 (context 5필드 + digest 체인, `calibration_record.encode_record` 경유)
- [ ] `status: approximate_requires_physical_validation` 유지 — 물리 검증 전 런타임 주입 금지

### 정적 (호스트, 재계산 스크립트)
- [x] 이미지 1 자기정합 RMSE ≤ 0.3cm — 0.306 확인
- [ ] 이미지 2 나머지 지면점 수령 후 자기정합 RMSE ≤ 1.0cm
- [ ] top-level H 가 두 캡처 모두 ≤ 0.5cm 유지 — 2026-09-20 시점 확인
- [ ] 융합/선택 근거 문서화 수령

### 물리 (실기, 카메라 장착 확정 상태)
- [ ] 마커를 전방 15/25/35cm 배치 → 보고 거리 오차 ≤ 1cm
- [ ] 측면 -5/0/+5cm → x 오차 ≤ 1cm
- [ ] **ArUco 교차검증**: dock tag pose 거리 vs homography 거리, 동일 지점 차 ≤ 2cm
- [ ] 보드 x → 로봇 측면 장착 변환 검증 (마커를 로봇 기준 좌/우에 배치)
- [ ] 반복성: 동일 지점 5캡처 σ ≤ 0.5cm
- [ ] 조명 3종 변화
- [ ] 36.5cm+ 외삽 시도는 "참고"로만 기록
- [ ] 카메라 재장착/충격 시 geometry_revision bump 로 재캘리브레이션

## 5. 다음

1. 공급자로부터 잘리지 않은 전체 JSON 수령 (img2 지면점 9~16 + img2 자체 호모그래피)
2. §2 포맷 래핑 여부 결정 — `encode_record` 경유
3. §4 물리 체크박스 실행 (장착 상태 고정 후)
