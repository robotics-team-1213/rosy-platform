# D-520 호 주행 단계 1: 모델 PC ROS-SIM, 2026-10-08

**판정: FAIL. 장치에서 `arc_enabled`를 켜지 않는다.** [D-520 7항](../../adr/D-520-map-guided-ring-arc-following.md)의 단계 1 합격선은 6/6 구간 전체 |Δr| ≤ 0.05 m, 구간 흐름 평균 절댓값 ≤ 0.03 m, `near_stop`·`lane_arc_edge`·IR 보정 0이다. 이 측정은 코드 `981c446d1`에서 SW 3회, NE 3회 지시 중 5개 호, SW→SE→NE 연결 1회와 별도 곡률 이득 1.1 탐색 각 1회를 돌린 것이다. 실물 로봇·현장 수용 증거가 아니다.

## 환경과 측정

- 모델 PC의 전용 `rosy_d520_s1_ws`; ROS_DOMAIN_ID 108, GZ_PARTITION `rosy_d520_s1`, CORE 포트 8118. 기존 다른 세션의 시뮬레이션은 건드리지 않았다. 완료 뒤 이 전용 실행만 종료했다.
- Jazzy/Gazebo `map_v2_fleet_real.world`, D-495의 `d495_real.launch.py`·`d495_sim_aux.py` 참값 `/d495/gt`·IR 모형·keep 카메라. 설치 패키지 `gz_sim core control description`을 해당 소스 커밋에서 다시 빌드했다. CORE 설정은 [gain 1.0 overlay](evidence/core_overlay_gain10.yaml)와 [gain 1.1 overlay](evidence/core_overlay_gain11.yaml) 그대로다. `arc_blind_max_m`은 상속 기본값 1.0 m다.
- 각 run에서 OFF→어두운 내부 위치→RESET 지시→OFF→4c 진입 자세로 이동했다. SW는 (−0.655, −0.432, 64°), NE는 (−0.0711, 0.4774, −117.8°). CORE HTTP `CAMERA_LINE`과 `/api/v1/line-follow/junction`만 사용했다. `turn_deg`는 SW −114.6°, NE −102.8°(접선), `pivot_past_line_m` −0.096 m, `expect_in_m` 0.3 m, `expect_tol_m` 0.18 m, `map_id` `map_v2_fleet`. 호는 κ 3.98 1/m, 길이 SW 0.3739 m/NE 0.3722 m, 바깥선 오프셋 0.095 m다. 지시의 원문·응답은 각 run의 `actions.jsonl`에 있다.
- Gazebo 참값에서 중심 (−0.3357, 0.0011)까지의 거리에서 반지름 0.2514 m를 뺀 값을 Δr로 썼다. 구간 흐름은 끝 Δr − 첫 Δr. 진입 heading 오차는 참값 yaw − 중심 원의 반시계 접선이다. [analyze.py](evidence/analyze.py)가 원본 `*_arc.jsonl`에서 다시 계산한다. CORE가 이전 `arc` 상태를 API에 남기므로 **현재 `arc_seq`의 `running`부터만** 계산했다. 원래 `summary.json`의 SW `start_dr=0.2867 m`와 NE 미진입 run의 숫자는 이전 호가 섞인 프로브 오류이며 판정에 쓰지 않았다.

| 계수 1.0 | 호 결과 | 전체 최대 |Δr| | 흐름 | 진입 yaw 오차 | IR 보정 |
|---|---|---:|---:|---:|---|
| SW 1 | 끝 | 29.1 mm | +34.3 mm | +1.0° | 없음 |
| SW 2 | 끝 | 27.8 mm | +32.9 mm | +1.7° | 없음 |
| SW 3 | 끝 | 29.3 mm | +33.4 mm | +1.4° | 없음 |
| NE 1 | `lane_arc_edge` HOLD | 62.7 mm | +62.9 mm | −14.2° | 있음 |
| NE 2 | 끝, 다음 지시 없음 | 69.6 mm | +79.7 mm | −20.6° | 있음 |
| NE 3 | 호 미진입, `turn_basis_lost` | 측정 불가 | 측정 불가 | 측정 불가 | 해당 없음 |

SW 흐름 평균 절댓값은 **33.5 mm**로 30 mm 기준을 넘었다. NE는 두 유효 호가 모두 50 mm와 IR 보정 0 기준을 넘었고, 하나는 `lane_arc_edge`로 멈췄다. NE 3의 `turn_basis_lost`는 같은 CORE에서 앞선 run 뒤 상태를 재사용한 영향일 수 있어 독립 물리 결함으로 확정하지 않는다. 기록된 `log.jsonl`·`events.jsonl`에서 `near_stop`은 0이었다.

SW 호가 달릴 때 SE `straight`와 `ring_e`를 보낸 연결 시험에서는 지시가 `armed`로 수락되고 두 번째 호가 0.4596 m에서 끝났다. 그러나 SE 호 최대 |Δr|은 **59.2 mm**, IR 보정은 1회였다([chain2](evidence/chain2)). 다음 NE 지시를 보내지 않은 단일/연결 시험의 `lane_arc_end_unarmed`는 이 직접 프로브의 끝 지시 부재를 뜻한다. Fleet 한 바퀴 완료 증거는 아니다.

## 원인 가설을 좁힌 별도 탐색

시뮬레이션에서만 `arc_curvature_gain=1.1`을 준 각 1회([sw_gain11](evidence/sw_gain11), [ne_gain11](evidence/ne_gain11)): SW는 최대 |Δr| 10.5 mm, 흐름 15.6 mm, IR 보정 0으로 개선됐다. NE는 진입 yaw 오차 −21.4°, 최대 |Δr| 64.6 mm, 흐름 76.5 mm, IR 보정과 `lane_arc_edge` HOLD가 남았다. **계수 1.1은 SW의 후보일 뿐이며 NE 해결책이나 장치 설정값으로 승인하지 않는다.**

두 NE 유효 run은 호 시작부터 지도 원 접선 대비 yaw가 −14.2°/−20.6°였고, SW는 +1.0°~+1.7°였다. NE의 큰 바깥 흐름은 이 진입 방향 오차와 일치한다는 **가설**이다. 현재 단계 1 코드의 `lane_arc_entry` 검사는 아직 단계 2 첫 카메라 맞춤에 예약되어 있어 참값 기준의 이 오차를 이 단계에서 막지 않는다. 지도 자세나 카메라 맞춤으로 진입 heading을 독립 검증한 뒤, NE의 회전 종료 자세와 odom/실제 yaw 비를 분석해야 한다. 커맨드 곡률만 조정해 실물에 적용할 근거는 없다.

다음 검증은 (1) NE를 매회 새 CORE에서 시작해 회전 종료 yaw와 참값 접선을 분리 기록, (2) 단계 2의 첫 맞춤·`lane_arc_entry` 문을 붙인 뒤 같은 6회와 연결 구간 재시험, (3) Fleet 한 바퀴 SIM이다. 10/7 영상의 동일 물리 경계 ID는 사람 승인 정답이 없으므로 학습 수용 지표로 쓰지 않는다. 실물은 독립 위치 기준과 사람 승인 이후에만 평가한다.
