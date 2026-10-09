# 서쪽 모서리 굽이 지시 후보 폐루프 SIM — 2026-10-09

**판정: 서쪽 모서리 통과 후보 확인, 한 바퀴·주행 안전 승격 HOLD.** 모델 PC의 격리된 Gazebo/CORE/Fleet 폐루프에서, 지도에 이미 그려진 서쪽 바깥 모서리를 Fleet `bend` 장소로 추가했다. U-Net은 `route_context_enabled=true` 두 실행 모두 기존 정지 위치를 지나갔고, 한 번은 `arrived`했다. 두 번째는 링 구간의 `arc_mismatch`로 멈췄다. 차체 표본과 도색 중심선 사이의 작은 양의 여유는 연속 시간 안전성이나 실물 차로 경계 수용을 증명하지 않는다.

## 후보와 실행 경계

- [첫 모델 폐루프](../lane-model-closed-loop-2026-10-09/result.md)는 U-Net이 서쪽 모서리 전 `stopped/stall`이었다. [같은 프레임 재생](../lane-loop-failure-audit-2026-10-09/result.md)에서 실패 순간 종방향 경계가 사라지고 다섯 도색 방식이 모두 `none`이었다. 마지막 횡단 띠를 종방향 선으로 승격하지 않았다.
- 이 후보는 [D-507](../../adr/D-507-lane-trip-leg-structure-and-site-floor.md)의 기존 Fleet→CORE 굽이 지시를 쓴다. SIM 전용 [Fleet 지도](evidence/lap_fleet.py)에 `B_WEST=(-1.269,-0.509)`, 진입 −90°, 출구 0°, 반경 0.15m를 추가했다. 현장 지도에는 쓰지 않았다. `bend_geometry`는 `west:rev`에서 호 접점 `s=1.789…2.061m`, 회전 +90°를 반환했다. 실측·사람 승인 형상이 아니라 지도 중심선 기반 후보이다.
- [전용 launch](evidence/closed_loop.launch.py), [CORE overlay 실행](evidence/run_closed_loop.sh), [Fleet batch](evidence/closed_loop_batch.sh), [한 바퀴 입력](evidence/one_lap.txt)을 썼다. 원본 실행과 같은 시작 `(-1.26955,0.24255,-1.5708)`, world SHA-256 `14c8de02f683435a103728a30a24a83237ff9bc03ba1dc6f87a08feb99f31ebb`, 모델 U-Net 리비전 `sim-unet-5159bea1`, ROS domain 95, Gazebo partition `rosy_lane_loop`이다. SIM 지도 자세는 Gazebo 참값이다. 원본 소스 기준은 첫 폐루프의 `4d16150dcd807c7044d44ff2fc122c04e2787876`이며, 원격 `line_observer_node.py` SHA-256 `a37afe3bbfaba1ddcad58f8c8743bb0fe3e6cbbdef028010e15510da59ac0f14`, `lane_keep.py` `cf58c0fe99439e71deafa4d407022544b69f1512bc09ea608a62ceacf2af22bc`였다. 이번 변경은 SIM 하네스·지도 후보만이며 제품 주행 코드를 바꾸지 않았다.
- CORE의 `route_context_enabled`는 실행별 격리 overlay에서만 `true`/`false`로 바꿨다. 현장 기본값은 `false`다. `true` 실행에서 CORE `line/route_context` 발행과 `keep_debug.route_context_seq` 소비를 별도로 확인했다. CORE만 최종 `cmd_vel`을 발행했다.
- 첫 실행의 잘못된 `WS` 기본 경로는 스크립트 실행 전 오류로 끝났다. `WS`를 명시한 첫 threshold 실행은 초기 정지, 두 번째는 Fleet capability 미확인으로 시작 거절됐다. 둘 다 아래에 남겼다. 모든 조건은 고정 난수 시드나 동일 시작 이후의 렌더링 순서를 증명하지 못한다.

## 폐루프 결과

`서쪽 통과`는 Gazebo 참값이 굽이 뒤의 남쪽 직선 `x>-1.10, y<-0.45`에 들어간 경우다. 목적지 `arrived`와 다르다. 도색 중심선 여유는 [차체 표본 검사](evidence/audit_path.py)가 SIM URDF의 10점 볼록 외곽(반경 0.08826m)과 지도 `west` 중심선 폭 0.185m로 계산한 **후보 대리값**이다.

| 실행 | 도색 | 경로 문맥 | 서쪽 통과 | Fleet 종료 | 서쪽 최소 표본 여유 |
| --- | --- | --- | --- | --- | ---: |
| 기존 기준 | U-Net | 꺼짐, `B_WEST` 없음 | 아니오 | `stopped/stall` | +10.8mm, 정지 전만 |
| T1 | threshold | 켬, `B_WEST` | 아니오 | `stopped/stall` (초기 정지·문맥 소비 0장) | 측정 제외 |
| T2 | threshold | 켬, `B_WEST` | 주행 시작 전 거절 | `start_refused/TRIP_ROBOT_CAPS_UNKNOWN` | 측정 제외 |
| T3 | threshold | 켬, `B_WEST` | 예 | `stopped/stall` (링 뒤) | +7.3mm, 0/199 표본 교차 |
| U1 | U-Net | 켬, `B_WEST` | 예 | **`arrived`** | +6.7mm, 0/133 표본 교차 |
| U2 | U-Net | 켬, `B_WEST` | 예 | `stopped/junction` (링 `arc_mismatch`) | +5.3mm, 0/137 표본 교차 |
| A1 | U-Net | 꺼짐, `B_WEST` | 예 | `failed/TRIP_ROBOT_UNREACHABLE` (SW 전) | +5.8mm, 0/96 표본 교차 |
| A2 | U-Net | 꺼짐, `B_WEST` | 아니오 | `stopped/junction` (굽이 `odom` 중단) | +7.9mm, 0/91 표본 교차 |

U1의 U-Net 프레임은 `learned` 524장, `denoise_fallback` 45장이고, U2는 각각 532·37장이다. `B_WEST`의 `route_context_seq=2`가 U1 124장, U2 120장에 실렸다. 두 실행에서 `bending→reacquiring`을 거쳐 모서리 뒤 차로에 진입했다. A1/A2의 `route_context_seq`는 전부 null이다. A1은 모서리 뒤 `x≈−0.837`까지 갔지만 CORE 연결 실패가 섞였고, A2의 `odom` 중단은 안전한 정지이므로 우회하지 않는다. 이 소수 실행은 지도 굽이 지시와 B9 인식 문맥 각각의 인과 효과를 분리하지 못한다.

U1의 링 호 세 구간에서 도색 **중심** 교차 표본은 0개였으나 최소 표본 여유가 2.8mm이고 최대 표본 간 차체 꼭짓점 이동은 13.5mm였다. T3의 링 최소 여유는 0.8mm, 최대 이동은 14.0mm였다. 특히 U2는 링 호 검사가 완결되기 전에 `arc_mismatch`로 종료됐다. 서쪽에서도 U1 최소 6.7mm에 비해 최대 표본 간 이동은 9.4mm다. 이 데이터는 표본 사이 차체 sweep·정지 후 이동·지도 오차를 묶은 통행 안전 증명이 아니다. 도색 중심선 자체가 승인된 통행 경계라는 뜻도 아니다.

## 원시 증거와 재현

원시 `log.jsonl`, `rec/keep.jsonl`, `summary.json`, Fleet `sends.jsonl`·`trip.jsonl`, 카메라 `frames.npz`는 모델 PC의 격리 작업공간 `~/rosy_d567_ws/loop_<실행명>/lap_d567_baseline/`에 남겼다. `T3`는 `loop_west_threshold_r3`, `U1/U2`는 `loop_west_unet_r1/r2`, `A1/A2`는 `loop_west_unet_no_context[/_r2]`다. T1은 `loop_west_threshold_r1`, T2는 `loop_west_threshold_r2`이다. 원시 카메라와 대용량 로그는 git에 넣지 않았다.

| 로그 | `log.jsonl` SHA-256 |
| --- | --- |
| T3 log SHA-256 | `0ebce9b28278bde6f1fd7fdcc143650178add0f86df5c6c9bad53e40f4aae202` |
| U1 log SHA-256 | `bad57e8c783657a9b32d0f25f7dc624a4bd7370a100dd21caede04dafae3d4ce` |
| U2 log SHA-256 | `4fc29543a1c469a0488df9553ebe8083866a85f80e85c09800911e69193a15c9` |
| A1 log SHA-256 | `4b15b187cd66345935c5c247da47056b2418e8ecb6d63b8746cc1c61bafcea19` |
| A2 log SHA-256 | `83b2c19e3c6c497b3b6fd37f045dda7b0252f623e1d75e474ddc2cad43fe971e` |

재현 시 `run_closed_loop.sh`를 격리 모델 PC에서 먼저 실행하고, CORE 준비 후 `WEST_BEND=1 REC=1 OUTD=<고유 디렉터리> bash closed_loop_batch.sh one_lap.txt`를 실행한다. `MODEL=unet` 또는 `threshold`, `ROUTE_CONTEXT_ENABLED=true` 또는 `false`를 첫 스크립트에 준다. `OUTD`는 매번 새 경로를 쓴다. 실행이 끝나면 자신의 ROS launch와 동일 partition 프로세스만 종료한다. [검사 스크립트](evidence/audit_path.py)에 각 `log.jsonl` 경로를 준다.

## 판정과 남은 검증

서쪽 모서리의 추가 학습보다, Fleet의 지도 굽이 지시로 CORE가 경계 소실 **전** 호를 시작하는 후보가 이번 SIM에서 효과를 보였다. 그러나 10/7 원본 207프레임은 D-475 사람 승인 경계가 아직 0개이며, 이 SIM의 0.15m 반경도 실측 승인값이 아니다. `route_context_enabled=false` 운영 기본값, 불확실 경계에서 STOP, CORE 단일 `cmd_vel`을 유지한다.

다음 수용 단계는 (1) 지도·카메라의 같은 물리 경계 ID와 모서리 반경·테이프 폭 사람 검수, (2) 동일 조건 반복과 한쪽 선 가림·벽·분기에서 HOLD→주행 변화 검사, (3) 지도 자세 오차·표본 사이 차체 sweep·정지 거리를 포함한 차로 containment, (4) AI PC 추론 지연과 ARM64/장치·현장 안전 담당 아래의 별도 읽기·정지 검증이다. 링 `arc_mismatch`와 불안정한 Fleet 종료도 별도 실패로 남긴다. 이 항목들이 끝나기 전 실물 주행 승격은 HOLD다.
