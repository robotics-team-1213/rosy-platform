# 무신호 교차로 정지 후 진입 — traffic policy `junction_rule` 설계

- **Status:** 구현 동반 승인 (2026-09-29, 이 변경 안에서 착지)
- **Date:** 2026-09-29
- **Related:** `docs/plans/2026-09-21-semantic-road-control-design.md` (D-151 도로 증거 게이트),
  `src/runtime/services/core_features/traffic_policy/manager.py`,
  `docs/reference/ROSY API & Protocol Reference.md` (v1.54)

## 1. 문제 — "신호 없음"의 두 뜻

현행 `TrafficPolicyManager._verdict()`는 정지선 완전정지+dwell 이후 `signal_colour is None`이면
`WAIT_SIGNAL / signal_unknown`으로 무한 대기한다. 이 판정은 두 상황을 구분하지 못한다:

1. **무신호 교차로** — 그 씬에는 신호등이 없다 (정지 후 진입이 올바른 동작)
2. **인식 실패** — 신호등은 있으나 카메라가 못 보고 있다 (대기가 올바른 동작)

구분 없이는 무신호 교차로를 통과할 방법이 없다. 카메라가 "신호등 부재"를 판정하는
것도 답이 아니다 — 부재는 증명이 아니라 오탐에 취약하다.

## 2. 결정 — 부재는 선언이다, 관측이 아니라

검토한 세 갈래:

| 갈래 | 요지 | 판정 |
|---|---|---|
| **채택** — `TrafficPolicyConfig` 신규 필드 `junction_rule` | 운영자가 dashboard stage/apply로 정지선 규칙을 선언. 기존 리비전·맵·씬 커플링, 스테이징 파이프라인 전부 재사용 | 문제(1)을 가장 싸게 안전하게 푼다. scene당 규칙 1개는 v1 제약으로 기록 |
| 오프라인 교차로 규칙 파일 | `lane_graph_path`처럼 씬 곁에 정지선/노드 id 단위 규칙 | 다중 교차로 표현 가능하나 policy가 정지선 identity를 받아야 함 — perception이 id를 발행하지 않아 과투자. 채택 갈래가 닳으면 승격 |
| perception이 부재 판정 (`RoadEvidence` 필드) | 카메라가 "신호없음"을 보고 | 기각 — §1의 이유. 부재는 선언이어야 한다 |

**방향 스코프: 방향 무관.** `stop_and_go` 규칙은 "완전정지+dwell 후 진입"이며
우회전/직진/좌회전을 구분하지 않는다. 회전 의도 소스(route 위상·candidate 각속도)를
정책이 알 필요가 없어 가장 견고하고, 우회전 특례(예: 신호 있는 교차로의 적신화 우회전)는
같은 필드의 값 확장으로 나중에 붙일 수 있다(§7).

## 3. 판정 분기

`_verdict()`의 dwell 완료 지점 뒤에 끼어든다. 그 앞의 stale·map/scene 불일치·
`signal_conflict`·정지선 신뢰도·거리·dwell 검사는 규칙과 무관하게 그대로다.

```
[정지선 도달] → STOP_REQUIRED (dwell 진행)
                    ↓ dwell 완료
        junction_rule == "stop_and_go"?
        ├─ 예 + signal_colour is None
        │     → PROCEED / "unsignalized_proceed" / scale = proceed_speed_scale
        ├─ 예 + signal_colour 관측됨 (색·신뢰도 무관)
        │     → HOLD / "signal_unexpected" / 0.0
        └─ 아니오 (signal_controlled, 기본값)
              → 기존 동작 (신호 없으면 WAIT_SIGNAL, GREEN만 PROCEED)
```

불변식:

1. 무신호 `PROCEED`는 **완전정지 + `stop_dwell_s` 경과 후에만** — 상태기계 변경 없음.
2. `stop_and_go`에서 신호등이 관측되면(약한 오탐 포함, `signal_colour is not None`)
   `signal_unexpected` HOLD. 운영자 선언과 카메라 관측의 충돌은 진행하지 않고
   운영자에게 돌아간다 — fail-closed.
3. `signal_conflict` → HOLD는 규칙보다 앞선다(기존 순서 유지).
4. 새 상태 문자 없음 — `PROCEED` 재사용, reason만 추가. 상태 어휘·시뮬레이터 색 맵 무변경.
5. `MONITOR_ONLY`는 후보를 통과시키면서 status에 같은 판정을 표시(기존 패턴 유지).

## 4. 표면 변화

- `TrafficPolicyConfig.junction_rule: str = "signal_controlled"` (값 검증: 두 값 외 거부)
- `TrafficPolicyStatus.junction_rule` 신규 필드 (additive, API Ref v1.54)
- `POST /api/v1/traffic/policy/stage` 본문에 `junction_rule` 허용 (`TrafficPolicyPatch`)
- `rosy_default.yaml` `traffic_policy.junction_rule: signal_controlled` 기본값
- dashboard `/setup` 교통 정책 패어널: 규칙 select 추가(신호 제어 / 무신호: 정지 후 진입),
  상태 facts에 규칙 행. `/console` 메인 facts에도 규칙 행 추가

## 5. 전제와 한계

- 폐쇄 코스 전제: 보행자 인식이 없으므로 `stop_and_go` 진입의 양보는
  `proceed_speed_scale`(기본 0.5) 속도 상한과 씬 선언(운영자 승인)이 담당한다.
  `crosswalk_visible`은 여전히 관측 표시일 뿐 판정에 쓰지 않는다.
- scene당 규칙 1개(다중 교차로 미지원). 정지선 identity가 필요해지면 §2의 갈래 2로 승격.

## 6. 시험

`src/runtime/gateway/test/test_traffic_policy.py`:

- `stop_and_go` + 신호 없음: dwell 중 `STOP_REQUIRED`, 이후 `PROCEED` /
  `unsignalized_proceed`, linear = 후보 × `proceed_speed_scale`, angular 무변경
- `stop_and_go` + RED(신뢰도 충분/미달 포함) → HOLD `signal_unexpected`
- `stop_and_go` + `signal_conflict` → HOLD `signal_conflict` (규칙이 충돌 검사를 무시하지 않음)
- 기본 `signal_controlled` 무변경(기존 시험 유지)
- `stage()`로 `junction_rule` 패치·`configuration()`·`status()` 노출, 값 검증 거부

## 7. 향후 확장 (이 문서의 범위 밖)

- **적신호 우회전 특례**: `junction_rule` 값 추가(예: `right_on_red_after_stop`)로
  같은 메커니즘 위에 얹는다. 방향 스코프(§2)가 먼저 풀려 있어 확장은 값 하나다.
- **다중 교차로**: 오프라인 규칙 파일 승격 — perception의 정지선 identity 선행.
- **ESP32/observer 신호 소스**: `RoadEvidence.source`가 `CAMERA_ROAD` 단일인 현 구조에서
  실측 관측 서비스(`firmware/signal/observer`)를 로봇의 제2 증거로 붙이는 갈래.
  "신호등 보고를 안전 근거로 삼지 않는다"(ROSY-SIGNAL-001) 경계와의 정리가 선행 과제.
