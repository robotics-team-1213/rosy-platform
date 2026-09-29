# 로봇 신호 소스 통합 설계 — 로봇은 실측된 빛만 읽는다

- **Status:** 구조 확정 (ADR D-337). 구현은 실행 계획 T1~T5로 별도 회차
- **Date:** 2026-09-29
- **Related:** `firmware/signal/README.md` (ROSY-SIGNAL-001 — 제어 평면),
  `docs/plans/2026-09-22-signal-observer-vision-design.md` (D-163 — 관측 평면,
  §4 "훗날 로봇이 신호를 '보고' 판단해야 하면 이 관측 API가 그 입력이 된다"),
  `docs/plans/2026-09-29-traffic-policy-unsignalized-junction-design.md` (junction_rule),
  `src/runtime/services/core_features/traffic_policy/manager.py`

## 1. 결론 — 세 가지 결정

```
Fleet ──명령──▶ [ESP32 컨트롤러] ──접점──▶ [신호등]
  │                                        │ 빛
  │                                        ▼
  └─3자 교차 검증 ◀── [관측 서비스 /observed] ◀── 카메라
                        │
                        └─HTTP 읽기(폴러)─▶ [로봇 CORE] ─▶ TrafficPolicyManager 융합
```

1. **로봇의 제2 신호 소스는 관측 서비스의 실측(`GET /observed`)뿐이다.**
   ESP32 `/status`(접점 주장)을 로봇이 직접 소비하지 않는다. 3자 교차 검증이
   존재하는 이유가 2≠3(주장≠점등)이다 — 로봇이 `/status`를 믿으면 배선 끊김·
   LED 사망 같은 표시 불일치를 주행 허가로 그대로 번역한다. "신호등 보고를
   안전 근거로 삼지 않는다"(ROSY-SIGNAL-001 §클라이언트)의 구체적 준수다.
2. **방향은 읽기뿐.** 로봇→신호등·관측으로 가는 명령 경로를 만들지 않는다
   (관측 서버에는 POST가 애초에 없다). 신호등 순서의 소유자는 여전히 Fleet(D-12).
3. **융합은 fail-closed.** 관측 증거는 카메라 증거를 대체하지 않고 보강한다.
   두 소스가 불일치하면 정지한다. 소등(0개 점등)은 "신호 없음"이 아니라
   "판정 불능"이다 — 어떤 경우도 관측이 진입을 **허가**하는 근거가 되지 않고,
   카메라가 이미 보는 색과 만났을 때만 함께 쓰인다(§3).

## 2. 신규 증거 계약 — `SignalHeadEvidence`

`core_features.traffic_policy`에 ROS-free dataclass 추가. `RoadEvidence`와 같은
커플링(`map_id`·`scene_revision`)을 지니고, 위반 시 기각.

| 필드 | 뜻 |
|---|---|
| `source="OBSERVER_HTTP"` | 관측 서비스 `/observed` 원 |
| `stamp` | 관측 서버의 `ts` |
| `red`·`yellow`·`green` | 운영자 지도 적용 뒤의 점등 불리언 — 정확히 한 색만 점등이 색 주장, 0개 또는 2개 이상은 부정(진입 불허) |
| `confidence` | 관측 `confidence` |
| `frozen` | 관측 서버의 동결 표기(낡은 프레임의 CONFIRMED 금지) |
| `stable` | debounce 확정 여부 — `pending`은 침묵으로 취급 |

램프 ROI 이름→색 지도(`left/mid/right → red/yellow/green`)는 로봇 설정이
운영자 기입으로 갖는다(Fleet `signals.yaml`의 `observer_map`과 같은 정신 —
여기서 지어내지 않는다). 판정: 정확히 한 색 점등 → 그 색. 0개 또는 2개 이상 →
`signal_head_indeterminate`(진입 불허).

## 3. 융합 규칙 — `TrafficPolicyManager` 확장

정지선 완전정지+dwell 이후의 신호 판정을 다음처럼 확장한다. 앞단(stale·
map/scene·`signal_conflict`·정지선 신뢰도·dwell)과 `junction_rule` 분기는
변경 없다.

| 카메라 색 | 관측 색 | 결과 |
|---|---|---|
| 있음 | 같은 색 | 그 색 (신뢰도는 min) |
| 있음 | 다른 색 | HOLD `signal_source_conflict` |
| 있음 | 부재·stale·frozen·pending | 카메라 단독 (현행과 동일) |
| 없음 | 확정 1색 | 관측 색으로 verdict — **이 통합의 존재 이유**: 로봇 카메라가 신호등을 못 봐도 무한 `signal_unknown` 대신 정상 판정 |
| 없음 | 소등/부정(0·2개 이상) | `WAIT_SIGNAL / signal_dark` — 진입 불허 |
| 없음 | 부재·stale·frozen | 현행 유지 (`signal_unknown`) |

추가 불변식:

- `junction_rule: stop_and_go`에서는 **어떤 소스의 신호 관측이든**
  `signal_unexpected` HOLD — 무신호 선언과 충돌하는 증거의 출처를 가리지 않는다.
- 관측 증거의 나이는 카메라 증거와 같은 `stale_after_s` 예산으로 본다.
- 관측은 카메라의 `signal_conflict`(내부 충돌)를 상쇄하지 않는다.

## 4. 배치와 경계

- **폴러**: CORE 프로세스 안, `core_features`의 신규 전송 소자(httpx, 주입 시계,
  단일 스레드 폴링). ROS도 bridge도 아니다. 설정이 없으면 폴러 자체가 없다
  (기본 꺼짐 — capability가 아니라 설정 게이트).
- **설정**: `traffic_policy.signal_observer: {url, roi_map, timeout_s}` —
  `url`이 비면 통합 전체가 꺼진다. 값은 `~/.rosy/rosy.yaml`(현장 오버레이)에.
- **Fleet은 이 경로를 모른다.** 로봇↔관측 직결이고, Fleet의 3자 교차 검증은
  그대로 별도로 돈다. 관측 서버 쪽 변경은 없다(읽기 전용 계약이면 충분).
- **보안**: 관측 서버가 인증을 요구하게 되는 날에만 토큰을 단다(D-30 패턴).
  v1 계약에는 인증이 없다 — 읽기 전용이고 사이트 LAN 안이다.

## 5. 관측성

`TrafficPolicyStatus`에 additive로 `signal_source_kind: "camera" | "fused"`와
관측 증거 `age_s`·`frozen` 노출(API Ref MINOR와 함께). dashboard 교통 팩트에
"신호 원" 행. 새 이벤트는 최소 하나 — `nav.traffic_policy_signal_source_stale`
(관측 증거가 예산을 넘겨 무시되기 시작한 순간, 상태 전환 1회).

## 6. 시험

- **T1 순수 융합 단위시험**(§3 표 전 행 + 불변식 3): 호스트 pytest, ROS 불필요
- **T2 폴러 전송 시험**: 가짜 httpx transport — 200/503/지연/동결 프레임
- **T3 설정·readback**: url 부재 → 폴러 없음·상태 `camera`
- **T4 dashboard**: 신호 원 행 (정적 스캔)
- **T5 벤치**: WSL/Gazebo 폐루프 + 실물 — 호스트 합격 ≠ DEVICE(D-94 교훈)

## 7. 비목표

- ESP32 `/status`의 로봇 직접 소비 (금지 — §1.1)
- 로봇의 신호등 제어·명령 경로 (금지)
- 관측 서버·Fleet 쪽 변경
- 다중 교차로(정지선 identity), 공공 도로
- `stop_and_go`의 양보 판단 보강(보행자 인식)
