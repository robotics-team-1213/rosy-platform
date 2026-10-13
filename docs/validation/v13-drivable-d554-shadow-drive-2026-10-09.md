# v13-drivable D-554 첫 후보 shadow 주행, 2026-10-09

**판정: 학습·intake·shadow 배포·실물 shadow 기록 완료. drivable 품질은 D-475 §8 정의를 만족하지 않는다(선 경계를 무시하고 바닥 전체를 칠함). 주행 수용 아님, 조향 권한 없음.**

## 계보

- 자료: AI PC `data-v13`(manifest `846ab931…c04b`)에서 D-554 규칙으로 유도. 1,808장 유도, Claude 검수자 판정으로 182장 제외, 1,626장(train 1,207 / val 243 / test 176). 자료 ref `v13-lane-derived@f9d23ea8…`.
- 판정자: Claude 에이전트 5명 + 묶음 2개는 2차 검수자(합집합). 숨긴 카나리아 181개 중 171개 검출(0.945, 묶음별 0.905~0.972). 같은 카나리아 시험에서 로컬 Qwen3-VL 8B는 망가뜨린 겹쳐 그리기 17장을 모두 `ok`로 답했다.
- 부모: v11 `lane-seg-20261006-5f5ddcd9`(frozen). 후보 `v13-drivable-20261009-982b09a9`, ONNX sha256 `982b09a9…e711`, camera provenance provisional(D-554 7항).
- 학습: 30 epoch, best 21. val drivable IoU 0.933(부모 배경 화소), 0.930(라벨 화소 전체). 부모 차선 동등성 max_abs 1.14e-5, 모호 화소 0.
- intake: 기존 deployment gate는 heldout 정의 불일치로 거절(mIoU 0.065, 차선 클래스 불일치). D-554 8항의 shadow gate(부모 v11과 같은 임계값)로 통과: 재생 7,160프레임, p50 34.4 ms, NaN 0, 가시율 1.0. 읽을 수 없는 재생 영상 1개(`teleop_rosy_26_20261006T130504Z.mp4`)는 제외했다.

## 실물 shadow 주행 (8kcn, release 2026.10.09-058)

- 07:34Z `deliver.py push` → shadow 슬롯. `learned_lane_node`가 바로 읽음(서명 없음 경고는 lane_seg에서 warn-only, D-423).
- 07:38~07:46Z 녹화 463 s(`rosy_rec.sh`, camera/front 3,704, shadow 431). 주행은 가드를 건 teleop 직진·회전과 CORE `CAMERA_LINE` 60 s(hold deadman)였다.
- CORE 차선 추종은 회전교차로에서 링 도로가 아니라 안쪽 원의 흰 선 위를 따라 돌았다. 실물 `camera_lane_mode: line`의 선 추종기 특성 그대로다(D-378 E1).
- 신호등 기둥 앞에서 guard(3.3~3.9 cm)와 CORE `obstacle_ahead`(4.7 cm)가 각각 멈췄다. 연결된 충전 케이블이 기둥 하나를 끌었다.

## 결과

| 항목 | 값 |
|---|---|
| Pi shadow 추론 지연 | p50 297 ms, p95 336 ms, 최대 465 ms(약 0.93 Hz) |
| drivable 면적 비율 | p05 0.34, p50 0.36, p95 0.45 |
| learned 조향 오차와 규칙 오차의 차이 | p50 0.37, p95 0.52 |
| 벽 비율(wall_fraction) | 항상 0 |

녹화 프레임 36장에 모델을 다시 돌린 겹쳐 그리기(모델 PC `~/rosy-ml/scratch/v13-drive-20261009/drive-*.png`)에서 확인한 것:

1. **drivable은 흰 선 경계를 무시하고 ignore_top 아래 카펫 전체를 칠한다.** 선 바깥 바닥, 회전교차로 안쪽 섬, 링 바깥이 모두 녹색이다. 원인은 D-554 1항이다. 선 바깥을 255로 두고 음성은 벽만 줬기 때문에 "선 사이 = drivable"이 아니라 "벽이 아닌 바닥 = drivable"을 학습했다. val IoU 0.933은 선 사이 화소만 재므로 이 오류를 보지 못한다.
2. 벽은 drivable로 칠하지 않는다.
3. 부모 v11의 오류가 그대로 보인다. 신호등 기둥 받침을 speed_bump(주황), 바닥의 하늘색 케이블을 lane_right(빨강)로 칠한다. 이 후보는 부모 출력을 바꾸지 않는다.
4. learned와 규칙의 조향 차이(p50 0.37)는 위 1 때문에 의미 있는 비교가 아니다.

## 다음

- 라벨 규칙에 선 바깥 음성을 넣어야 한다. D-475 §8은 다른 도로 바닥도 drivable로 정의하므로 "선 바깥 = 배경"은 틀린 곳이 생긴다. 지도(`map_v2_fleet` 도로 래스터)와 카메라 자세로 화소를 도로 안·밖으로 나누는 방법, 또는 사람 확인 음성(섬·바깥 바닥) 구역 표시가 후보다. 어느 쪽이든 D-554 개정이 필요하다.
- Pi 지연 297 ms는 D-475 §8 조향 게이트 이전에 따로 잰다(호스트 34 ms와 9배 차이).
- 8kcn shadow 슬롯은 이 후보로 남아 있다. 되돌리기: `deliver.py rollback <robot-ip> --slot shadow`(이전 = v11 `lane-seg-20261006-5f5ddcd9`).
