# 무신호 교차로·관측 융합 폐루프 검증 (2026-09-29)

## 결과

`SEMANTIC_ROAD_HOST_SIM_PASS` — 시나리오 3종: `signal_controlled`(기존),
`stop_and_go_unsignalized`(신규), `observer_fusion`(신규).

`tools/sim/simulate_semantic_road.py`의 결정론적 합성 카메라 폐루프다 — production
detector, strict bridge decoder, line-follow manager, traffic policy(매니저 3기:
신호 제어·무신호·융합용), 최종 atomic command gate을 그대로 돌린다. 시맨틱 YAML
truth는 씬 생성·감사에만 쓰이고 detector 입력으로 전달하지 않는다
(`semantic_truth_fed_to_detector: false`).

## 무신호 교차로 (`junction_rule: stop_and_go`, 운영자 선언)

| Phase | 판정 | 최종 linear |
|---|---|---:|
| unsig_clear | `FOLLOW / clear_road` | 0.07984 m/s |
| unsig_approach | `APPROACH / stop_line_approach` | 0.04139 m/s |
| unsig_stop → unsig_dwell | `STOP_REQUIRED / stop_dwell` | 0.00000 m/s |
| unsig_proceed (dwell 완료, 신호 없음) | `PROCEED / unsignalized_proceed` | 0.02457 m/s |
| unexpected_signal (RED 램프 출현) | `HOLD / signal_unexpected` | 0.00000 m/s |

완전정지+dwell 선행, 진입 속도는 `proceed_speed_scale`(0.5) 적용. 선언된 무신호
씬에 신호가 관측되면(오탐 포함) 진입하지 않는다 — 설계
`docs/plans/2026-09-29-traffic-policy-unsignalized-junction-design.md`의 불변식 그대로.

## 관측 융합 (D-337: 카메라는 신호등을 못 봄)

| Phase | 카메라 | 관측 서비스(measured light) | 판정 | signal_source_kind |
|---|---|---|---|---|
| obs_stop → obs_unknown | 신호 없음 | — | `WAIT_SIGNAL / signal_unknown` (기존 무한 대기) | camera |
| obs_green | 신호 없음 | GREEN 확정 | `PROCEED / signal_green` | **fused** |
| obs_conflict | RED | GREEN | `HOLD / signal_source_conflict` | fused |

호스트 폐루프에서 관측 증거는 `SignalHeadEvidence`로 주입했다(T2 폴러의 전송
계약은 `test_observer_source.py`가 가짜 전송으로 검증). `obs_green`이 이 통합의
존재 이유다 — 로봇 카메라가 등을 못 봐도 측정된 빛이 있으면 정상 판정한다.

## 재현

```bash
python tools/sim/simulate_semantic_road.py --output <dir>
python -m pytest src/runtime/sensing/test/test_semantic_road_simulation.py -q
```

## 수용 경계

HOST-SIM 증거다. 실물 Gazebo 렌더링 폐루프(WSL2 Jazzy + `semantic_road_dashboard`
launch, 무신호 씬 저작), 관측 서비스 실HTTP 연결(T2 전송), Pi/ARM64, 실물 카메라
마운트·신호등 시야, 제동 거리, 무인 현장 수용은 포함하지 않는다
(`physical_device_validated: false`). 이들은 T5 벤치 회차와 DEVICE/FIELD 게이트로
남는다.
