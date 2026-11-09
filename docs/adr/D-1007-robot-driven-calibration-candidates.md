## D-1007 카메라 위치에 관계없이 맞추기의 첫 걸음 — 로봇 대응점으로 검토용 보정 후보를 만든다 (오프라인, 적용 없음)

**Status:** Accepted (2026-11-09, 사용자 지시: "카메라 위치에 관계없이 보정이 되어야 한다"). SOURCE와 호스트 시험까지다. 실제 로봇이 화면 안을 달리는 수집·현장 수용은 이 기록이 하지 않는다. D-1006 7항의 "자동 적용은 규정만"을 바꾸지 않는다.

잇는 결정: [D-1006](D-1006-calibration-health-before-adaptation.md) · [D-375](D-375-overhead-map-registration-from-lane-paint-proposal.md) · [D-587](D-587-ceiling-marker-sightings-anchor-map-pose.md)(스티커 높이·마운트) · [D-595](D-595-freeze-accepted-map-calibration.md) · [D-1003](D-1003-nav2-free-goals-in-the-robot-map-frame.md)(기체 지도↔현장 지도). 폴더 구조는 바뀌지 않으므로 D-427 3항은 해당하지 않는다. 이 기록은 어떤 움직임도 명령하지 않고(D-2) 보정은 표시·위치 표시 전용으로 남는다.

### Context

`ceiling_north`는 트랙의 43–59 %만 본다. 코드 확인: D-375 게이트(재현율·정밀도 ≥ 0.8, 곱 ≥ 0.75, 면적 ≥ 0.20, 방향 여유 ≥ 0.1)는 **잘린 변만으로는 거절하지 않는다**. 합성 프레임에서 서쪽 1/3이 잘린 맞춤도 수락된다(`test_rotated_180_with_west_cut_off`). 11-09의 거절(점수 0.51–0.60)이 부분 시야 때문인지 바닥·의자 불일치 때문인지는 **아직 모른다**. 그래서 페인트 부분 맞춤에 유효 구역을 붙여 수락 범위를 넓히는 일은 이번에 하지 않는다.

### Debate (Architect 대 Critic)

- Critic: 부분 시야의 페인트 맞춤은 한 주기 어긋나도 자신 있게 틀린다(D-1006 7항). 유효 다각형은 "어디에 적용"이지 "맞는지"가 아니다. 사각 `track_bounds_m`을 쓰는 소비자가 다섯 곳이라 스키마 변경이 넓다. 먼저 페인트와 독립한 증거가 필요하다.
- Architect: 같은 결론. 로봇은 페인트·보이는 면적과 무관한 독립 증거다. 첫 증분은 수집·오프라인 해법·검토용 후보까지, 유효 구역 게이트와 증거 융합은 두 번째 출처가 생긴 뒤.
- 둘 다 요구한 안전장치(채택): 시야 안 속도·시각 정렬 제한(오차 v·Δt), 같은 자리·같은 순간은 표본 1개, 공간 퍼짐과 비공선 검사, 공간 블록 단위 홀드아웃(무작위 분할은 낙관적), 마커 높이 시차, 유효 구역은 보이는 트랙이 아니라 **대응점의 볼록 껍질**, 적용은 운영자 승인만.

### Decision

1. **`rosy_vision/correspondence.py`(numpy만, 오프라인).** 표본 = 로봇의 현장 지도 자세(AMCL을 D-1003 변환으로 옮긴 값, 변환은 호출자 책임) + 같은 로봇 마커의 프레임 픽셀 + 시각·AMCL 상태·자세 나이·속도. `gate_samples`가 `LOCALIZED`, 자세 나이 ≤ 0.3 s, 시각 어긋남 ≤ 0.1 s, 속도 ≤ 0.15 m/s만 남기고 0.15 m 안의 중복을 솎는다(버린 이유를 센다).
2. **`solve_candidate`.** 스티커 높이(0.125 m) 평면의 호모그래피를 RANSAC(0.05 m)로 맞추고, 렌즈 FOV로 카메라 바로 아래 점(nadir)·높이를 풀어 바닥 호모그래피로 바꾼다. 상태는 첫 실패 문턱의 이름 또는 `ok`: `insufficient_samples`(< 12) · `insufficient_inliers` · `insufficient_time_span`(< 20 s) · `insufficient_spread`(껍질 면적/트랙 < 0.25 또는 공선) · `insufficient_heldout` · `heldout_residual_high`(홀드아웃 RMS > max(1.5×적합 RMS, 3 cm)) · `camera_not_solvable`(렌즈 모름·해 불량).
3. **후보 JSON**(`use: review-only`): `image_to_map`, `plane_height_m`, `rms_m`, `heldout_rms_m`, `n_*`, `spread`, `valid_region_m`(인라이어 볼록 껍질, 5 cm 바깥으로 키움), 승인 기록이 있으면 `approved_delta_m`(같은 픽셀을 두 보정이 놓는 거리의 중앙값·p90). 후자가 카메라 이동(A)을 보는 첫 독립 숫자다. 바닥 변경(B)과의 구분은 여전히 미해결(D-1006 3항).
4. **연결하지 않는다.** Fleet 저장·API·콘솔·Vision `from_record`·`marker_pose`는 바뀌지 않는다. 문턱(0.25·12·20 s·0.05 m 등)은 한 사건에서 잡은 시작값이고 근거가 아니다. 기록된 주행으로 조정한다.

### 다음 증분 (각각 별도 증거·ADR)

1. 수집기: Vision이 이미 내는 마커 감지와 Fleet의 로봇 자세를 한 시계로 묶어 JSONL로 남기는 읽기 전용 로거. 이 증분의 해법을 실제 주행 기록으로 돌려 문턱을 정한다.
2. 후보를 운영자 검토 화면에 올리고(D-1006 건강 상태와 나란히) 승인 시 `valid_region_m`을 기록에 실어 `marker_pose`가 그 구역 밖 위치를 만들지 않게 한다(레코드 스키마·소비자 5곳).
3. 페인트·고정 마커·로봇 후보의 증거 융합(홀드아웃 잔차로 선택). 자동 적용은 D-1006 7항 조건에 더해 대응점 출처가 하나라 위험하므로(AMCL이 보정에서 나오고 보정이 AMCL을 고치는 순환 금지) 별도 ADR.

### Consequences

- 카메라 위치와 무관한 보정의 독립 증거 경로가 생겼지만 **오늘은 아무 동작도 바뀌지 않는다.** 실제 로봇이 화면 안을 천천히 달리는 기록이 있어야 처음으로 쓸모가 생긴다.
- 사람이 해야 하는 일: 기체 하나를 `LOCALIZED` 상태로 카메라 시야 안에서 0.15 m/s 이하로 20 s 이상, 시야 대부분을 가로지르게 달리게 하고 그 동안의 Vision 마커 픽셀과 Fleet 자세 기록 확보(수집기 증분).
- 시험: `operations/overhead/test/test_correspondence.py`(ceiling_north 모델 합성 주행: 트랙 약 40 %만 보임, 바닥 정확도 < 2 cm, 공선·무작위 픽셀·낡은 표본 거절). 호스트 pytest는 현장 수용을 대신하지 않는다.
