# D-577 구현 계획 — 문제 상황의 로봇: Fleet 규칙, 예외 큐, AI PC 실시간 사실

- 날짜: 2026-10-09
- 결정: [D-577](../adr/D-577-trouble-fleet-rules-and-ai-pc-realtime-situation-facts.md) (Proposed)
- 규칙: 브랜치 하나에 단계 하나. 각 단계의 시험은 구현 전에 먼저 실패해야 한다(실패 출력을 `X:\DevTemp\<branch>\red.txt`에 남긴다). pytest·브라우저·Gazebo는 모델 PC 또는 AI PC(D-568)에서 돌린다. 노트북에서 돌리지 않는다. 실기는 사용자 승인 뒤 한 대씩.
- 주인 표기: **Fleet** = `operations/fleet` 세션, **AI PC** = `rosy-situation` 서비스 세션, **모델 PC** = 재생 평가 세션, **사용자** = 승인.

| 단계 | 브랜치 | 주인 | Safety-Review | 의존 |
|---|---|---|---|---|
| (a) | `feat/d577-resolver-default-lane-lost` | Fleet | 예 | — |
| (b) | `uiux/d577-queue-evidence-notify` | Fleet | 아니오 | (a) |
| (c) | `feat/d577-ai-pc-situation-skeleton` | AI PC + Fleet | 아니오(shadow만) | — |
| (d) | `feat/d577-deadlock-livelock-analyzers` | AI PC | 아니오(shadow만) | (c) |
| (e) | `feat/d577-vision-identity-shadow` | AI PC + Fleet | 아니오(shadow만) | (c), 소유자 동의 |
| (f) | `feat/d577-replay-eval-gate` | 모델 PC | 아니오 | (d), (e) |
| (g) | `feat/d577-ai-facts-acting` | Fleet | 예 | (f) 통과, 사용자 승인 |
| (h) | `feat/d577-gazebo-trouble-scenarios` | 모델 PC | 아니오 | (a), (d) |
| (i) | (배포·수용 기록) | 사용자 + Fleet | 예 | (a)–(h) |

## (a) 판단기 기본 켜짐 + 차선 상실 규칙 (non-trip)

바꿀 곳: `operations/fleet/fleet/server/stuck_resolver.py`(`_rule`), `stuck_resolver_loop.py`(R5의 WAIT + 상승 두 동작), `operations/fleet/fleet/cli.py`(`--no-stuck-resolver`), API Reference `GET /api/fleet/line-stuck` 상승 사유 `lane_lost_hold:*`.

먼저 실패할 시험(`operations/fleet/test/test_stuck_resolver.py`, `test_stuck_resolver_loop.py`, `test_fleet_cli*.py`):
- `lane_lost` + 로컬 복구 켜짐 + 시도 남음 + 뒤 띠 비어 있음 + 횡단보도 밖 → R3 `BACK_AND_RETRY`.
- 같은 조건에 동료 로봇이 뒤 0.30 m 안 → R5 `WAIT` + `lane_lost_hold:peer_behind` 상승, R3 없음.
- 시도 소진 → R5 `WAIT` + `lane_lost_hold:attempts`. 로컬 복구 꺼짐 → `lane_lost_hold:local_disabled`. 횡단보도 안 → `lane_lost_hold:crosswalk`.
- `MapPose` `DEGRADED` 또는 `age_s` > 2 s → R3 없음(`lane_lost_hold:pose`).
- `lane_lost`에서 어떤 경로로도 `RESUME`이 나가지 않음(속성 시험: 무작위 행 1000개).
- trip 로봇의 `lane_lost` → 지금처럼 `no_rule`(M4 회귀).
- R5는 규칙 예산을 쓰지 않음. 같은 `stuck_id`에 R5는 한 번.
- 인자 없는 `fleet console`이 판단기 루프를 만든다. `--no-stuck-resolver`면 만들지 않는다. 자격 없는 로봇의 막힘은 `no_resolver_token`.
- 사고 재현: 9dfk 모양 행(`cause=lane_lost`, `attempts=2`, `max_attempts=2`, 등록 로봇) → `no_resolver_token`; 자격을 준 같은 행 → R5 `WAIT` + 상승.

수용: 위 시험 통과, `python test/known_failures.py`에 NEW 없음, Safety-Review(R3 조건, R5와 D-541 trip lease·통행권 정지 겹침) 기록. 실제 로봇 자격 발급은 D-503 6항 브랜치와 사용자 승인으로 따로 한다.

## (b) 예외 큐: 근거·AI 칸·알림

바꿀 곳: `operations/fleet/fleet/server/web/queues.js`, `line-stuck.js`, 막힘 미리보기 메모리 보관(`line_stuck.py`), `require_named_operator` 연결.

먼저 실패할 시험(`test/test_fleet_console_browser.py`, Fleet 호스트 시험):
- 상승한 막힘 행에 원인·HOLD 사유·판단기 상승 사유·근거 이미지(그 막힘의 한 장)가 보인다. 막힘이 닫히면 이미지가 메모리에서 사라진다(디스크 파일 0).
- 이름 없는 세션의 다섯 답 → 거절(D-540 ②).
- 행이 생기면 소리·브라우저 알림 한 번, 30 s 무응답이면 다시 한 번과 위험 단계 상승. 기한 뒤에도 로봇으로 나가는 답 0.
- AI 칩: heartbeat 없음 → "AI 판단 없음".

수용: 브라우저 시험 통과(모델 PC), D-493 한 규칙 유지(새 화면 없음).

## (c) AI PC 서비스 골격 + 전송 + 상태 (shadow)

바꿀 곳: 새 `operations/situation/`(서비스, `rosy-situation.service`), Fleet `POST /api/fleet/ai/facts`·`/api/fleet/ai/heartbeat`, 역할 `ai_observer`(`site_auth.py`), 표 `fleet_ai_facts`, API Reference 행, `private/`의 주소·bearer.

먼저 실패할 시험:
- `ai_observer`는 viewer 읽기와 두 POST만 통과, 그 밖의 쓰기(정지 포함 운영 경로, 막힘 답, trip) 403.
- 사실 검사: 명령 단어 키·값, `ttl_s` 초과, 미래 `observed_at`, 33개 이상, 64 KiB 초과 → 거절. 초당 2 요청 초과 → 429.
- heartbeat 6 s 없음 → `absent`. `absent` 중 사실은 무시된다.
- AI 끝점이 멈춰도(시험용 느린 서버) `/api/fleet/estop`·판단기 한 주기·교통 표 주기의 지연이 늘지 않는다.
- 서비스: 폴링 커서가 재시작 뒤 이어지고, 대기열 256 넘으면 오래된 것부터 버린다, `owner_mode=owner_busy`면 heartbeat만.

수용: 위 시험, AI PC에서 소유자 동의 뒤 `shared` 모드로 24 h 연속 동작(메모리 2 GB 이하, 사실 0개여도 heartbeat 끊김 0).

## (d) 교착·livelock·정체 분석기 (shadow)

바꿀 곳: `operations/situation/analyzers/`(순수 함수, 입력 = 폴링 스냅샷 열).

먼저 실패할 시험(합성 스냅샷):
- `wait_cycle_confirmed`: 두 로봇이 서로의 블록을 3주기 이상 기다리고 둘 다 정지.
- `wait_cycle_stale_input`: 순환 안 로봇의 `MapPose.age_s` > 2 s 또는 `state` ≠ `LOCALIZED`.
- `waiting_but_moving`: 표의 `wait`인데 2 s 동안 0.05 m 넘게 움직임.
- `livelock`: 같은 로봇 집합의 순환이 60 s 안에 3번 이상 풀렸다 다시 생김, 또는 경로 진행 0.05 m 미만인데 명령 중.
- `stalled`: 차선 주행 중 20 s 동안 0.05 m 미만(trip 정체 규칙과 같은 수치, trip 밖 로봇에도).
- `unknown_occupancy_long`: UNKNOWN 점유 30 s 초과(M4와 같은 수치, 교차 확인용).
- 문제 없는 1시간 합성 운행에서 사실 0개.

수용: 순수 시험 통과, 같은 입력 로그 → 같은 사실(결정론).

## (e) 비전 정체 사실 (shadow)

바꿀 곳: Fleet 막힘 미리보기 한 장 → `POST <ai>/v1/identity`, AI PC Ollama `qwen3-vl:8b-instruct`(digest·`lidar-identity/1` 고정), D-523 파서 연결.

먼저 실패할 시험:
- `lane_lost` 막힘은 묻지 않는다. `obstacle_ahead` + 앞 거리 있음만 묻는다.
- 촬영 시각 없음·막힘 이전·8 s 초과 → `UNKNOWN`. 프로파일 불일치 → `UNKNOWN`.
- shadow에서 정체 사실이 규칙 입력에 들어가지 않는다(판단기 답이 사실 유무와 같다).
- AI PC 디스크에 프레임 파일 0, 입력 로그에는 sha256만.

수용: 소유자 동의 기록, `available` 모드에서 지연 분포(p50·p95) 기록.

## (f) 재생 평가 관문

바꿀 곳: `tools/decision_replay.py` 옆 `tools/situation_replay.py`, 평가 세트 `learning/.../situation_eval/`(hash 고정).

먼저 실패할 시험:
- 세트에 `20261009T130633Z_rosy_41`이 들어 있고, (a) 규칙으로 재생하면 R5 또는 R3가 나온다(무응답이 아님).
- 주입 문제(낡은 자세 순환, 움직이는 wait, livelock, 정체, 차선 관측 vs LiDAR 어긋남)에서 재현율 계산, 문제 없는 구간 오경보율 계산.
- 관문: 재현율 ≥ 0.9, 오경보 ≤ 시간당 1건. 비전은 D-492 V0(사람 정답 정체 정확도)·V1.

수용: 모델 PC 실행 기록(세트 hash, 분석기 버전, 결과)을 `docs/validation/`에 남긴다.

## (g) 행동 단계 (플래그 뒤)

바꿀 곳: Fleet `ai_facts_acting.<kind>`(기본 `false`), 판단기·M4 해결기에 "더 제한적인 쪽" 병합.

먼저 실패할 시험:
- `acting` 사실은 상승 앞당김, R2·R3 → R5, `replan` → `human`, 기존 정지 경로만 만든다. 블록 해제·허가·RESUME·BACK_AND_RETRY·YIELD 생성 0(속성 시험).
- 플래그 꺼짐이면 판단기·M4 출력이 사실 유무와 같다.
- `ttl_s` 지난 사실은 효과 0.

수용: Safety-Review, (f) 통과 기록, shadow 3 운행일 오경보 ≤ 운행일당 2건, 사용자 승인. 종류마다 따로 켠다.

## (h) Gazebo 다중 로봇 시나리오

모델 PC 또는 AI PC(D-568 `--pick`)에서. 노트북 금지.

시나리오: 두 로봇 마주 보는 교착, 세 로봇 순환, 자세 소스 끊김으로 낡은 순환, 좁은 차로 livelock, 차선 상실(뒤에 동료 있음/없음), 횡단보도 안 차선 상실, AI PC 정지(서비스 kill) 중 같은 시나리오.

수용: 각 시나리오에서 로봇이 무응답 HOLD로 끝나지 않는다(답 또는 큐 + 알림), AI 정지 시 결과가 규칙 → 사람과 같다, 몸 겹침 0.

## (i) 실기

사용자 승인 뒤 한 대씩: 자격 발급(D-503 6항) → (a)를 한 로봇에 → 차선 상실 실주행(Fleet 지켜봄, D-407 재검사 거절 기록 확인) → 두 번째 로봇 → AI PC shadow 한 운행일 → (g) 종류별. 각 단계는 `artifacts/receipts/`에 기록한다. Safety-Review.
