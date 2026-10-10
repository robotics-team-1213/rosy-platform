# D-614 v2 실제 CAMERA_LINE 및 횡단보도 시험

## 범위와 실행

- 2026-10-10 08:43:36–08:44:07 UTC, 사용자 현장 감독 확인과 즉시 시험 승인에 따라 9dfk, 8kcn을 순서대로 시험했다.
- 두 장치의 설치 release: `2026.10.10-128`. 시험 전 자동 적용 hold, 시험 후 release. E-Stop 재설정이나 안전 설정 변경은 하지 않았다.
- paint: `lane-seg-20261010-451f0f85` (v2), shadow: `lane-seg-20261010-ede0ae96` (원본 v1). 두 pointer 파일의 실제 내용을 읽었다.
- 기존 `tools/capture/edge_drive.py`의 Core, recording, arm/hold/disarm 함수를 재사용했다. `PUT /line-follow/mode` CAMERA_LINE, `hold_s: 1.0`, 0.3초 hold, 최대 3초 관찰, 자동 재무장 없이 finally OFF와 녹화 종료를 수행했다.
- 시험 전 IDLE, E-Stop false, 충전 false. 시험 종료 후 두 장치 모두 IDLE, line-follow OFF, 실제 velocity linear/angular 0. API 세션 logout 204, 시험용 token 삭제.

## 실제 관측

| 항목 | 9dfk | 8kcn |
|---|---|---|
| CAMERA_LINE 수락 | HTTP 200 | HTTP 200 |
| 시작→종료 odom 변위 | 0.0640 m | 0.0218 m |
| 종료 odom yaw 변화 | +0.07166 rad (4.11°) | +0.44986 rad (25.78°) |
| 녹화 최종 cmd_vel 선속도 범위 | 0–0.03350 m/s | 0–0.03378 m/s |
| 녹화 최종 cmd_vel 각속도 범위 | 0–0.05428 rad/s | −0.08529–0.00551 rad/s |
| 횡단보도 API 상태 | approaching → looking → waiting | approaching → looking |
| 횡단보도 정지 | crosswalk_looking, 이어서 crosswalk_person_present, 명령/실측 속도 0 | crosswalk_looking, 명령 0; OFF 종료 후 실측 속도 0 |
| 횡단보도 포함 camera observation 수 | 27 | 31 |
| crosswalk_uncertainty_m 범위 | 0.02787–0.04578 | 0.02857–0.03558 |
| keep_debug 수 / 사용 모델 | 27 / 전부 v2 | 32 / 전부 v2 |
| 관측 paint_mask_age_s 최대 | 0.500 s | 1.117 s |

두 장치의 설치 `pinky_pro/config/core.yaml`은 `crosswalk_gate_enabled: true`, obstacle_mode path이며 observer overlay는 `crosswalk_uncertainty_enabled: true`다. observation의 crosswalk near/far와 불확실성, keep_debug의 `paint_source_used: learned_drivable`, `paint_model_revision`을 녹화에서 확인했다. v2 출력→camera observation→CORE gate→최종 정지 명령의 실제 연결을 확인했다.

OFF 상태의 crosswalk `perception_stale`는 이번 모드 활성화 뒤 fresh observation과 camera-1 zone으로 바뀌었다. `crosswalk_person_present`는 LiDAR 점유 판단의 reason 이름이며, 실제 사람 분류나 사람 존재를 입증하지 않는다. 별도 `traffic_policy`는 DISABLED였으므로 신호등 통행 규칙 검증은 아니다.

## 확인된 제한과 다음 진단

- 횡단보도 **인식 및 접근 정지**는 실제 장치에서 관측했다. 연속 5초/최소 scan 수의 clear 증명 이후 재출발·완전 통과는 이번 짧은 시험에서 확인하지 않았다. 점유 판단을 수동 우회하거나 generic RESUME으로 넘기지 않았다.
- 8kcn의 녹화 구간 cmd_vel 각속도 적분은 −0.08101 rad (−4.64°), 같은 구간 odom yaw 변화는 +0.44898 rad (+25.73°)다. 9dfk는 각각 +0.06982/+0.07166 rad로 근접한다. 8kcn은 명령과 측정의 부호·크기가 불일치하므로 차선추종 합격으로 판정하지 않는다. 구동기·바퀴 응답과 odom 방향/스케일을 진단해야 하며, 원인을 모델 오류로 단정하지 않는다.
- 두 장치의 camera ground_source는 NOMINAL이다. 실제 거리 교정이나 전체 코스 수용을 입증하지 않는다. v2 TEST alias의 정식 모델 intake HOLD는 기존 기록과 같다.
- 모델만 적용했으며 이번 시험을 위한 제품 코드·설정 변경이나 새 build는 없었다. 기존 설치 runtime을 시험했다.

## 증거 위치

로컬 원본은 `X:/DevTemp/d614-live/`, 장치 녹화는 `/var/lib/rosy/pilot-recordings/<recording-id>/bag`에 보존했다. raw bag은 git에 넣지 않았다.

| 파일 / 녹화 | SHA-256 또는 식별자 |
|---|---|
| 9dfk camera-line-crosswalk.jsonl | sha256: `8b5e8017b32d3a4efbb532ae019a2f8b14fd327ed3c1b3dcfc99706fc4073073` |
| 8kcn camera-line-crosswalk.jsonl | sha256: `0d1f4e6a96ad4c05d624eed5544ef3289f3e9650c3acf2c30d33315c5cd7fe7e` |
| 9dfk bag-analysis.json | sha256: `aa447ead75448511ba8689bd3752ba142ea43687274f8e4f24757d19cc69978a` |
| 8kcn bag-analysis.json | sha256: `7cbf3a5cd087e985eacabec4fa1af129a1eea2d310df3bd02a6ec7f4624f8af8` |
| 9dfk 녹화 / duration | `20261010T084336Z_rosy_41` / 4.598 s |
| 8kcn 녹화 / duration | `20261010T084356Z_rosy_40` / 5.398 s |

이 기록은 [적용 기록](../drivable-v2-apply-2026-10-10/result.md), [정지 상태 dry-run](../drivable-v2-dryrun-2026-10-10/result.md), [거리 해석 정정](../drivable-v2-clearance-review-2026-10-10/result.md)에 이어 실제 짧은 주행의 증거를 추가한다.
