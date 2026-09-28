# ER2형 자율 루프 개념과 현행 소스의 대조

작성일: 2026-09-29
상태: 외부 개념 그림 대조. 새 기능·API·AI 승격 승인이 아니다.

## 대상 개념

비교 대상은 다섯 마디의 닫힌 루프다: **사용자 목표 → 상위 판단 에이전트(장면 이해·작업 분해·로봇/Skill 선택·진행 상태 판단) → Robot Skill 또는 VLA → Controller/Robot → 센서·실행 결과 → 상위 판단 에이전트가 다시 판단**. 회의 노트의 명칭 "ER2"는 외부 어휘이며 `CONCEPTS.md`·SRS·ADR 어디에도 없다. 본 문서는 그 상자가 프로젝트 계약에서 이미 예약된 자리 — FLEET SRS §14 AIV-001의 `LLM/VLA → Mission Planner → Fleet API → Rosy API → Nav2` — 와 현행 소스를 대조한다.

## 판단

루프의 **아래 절반(Skill → Controller/Robot → 센서·실행 결과)은 실재하고 계약으로 묶여 있다. 위 절반(상위 판단 에이전트)은 소스에 없고, 구현율 0%이며, 그 자리의 계약만 문서에 있다.** 폐루프의 마지막 마디("다시 판단")는 코드에서 의도적으로 차단돼 있다: 정책(source="policy") 작업은 생성 즉시 `HOLD, POLICY_NOT_ACCEPTED`로 내려가고 사람이 루프를 닫는다. 이는 결함이 아니라 [11_ROSY_AI_and_Physical_AI](../architecture/11_ROSY_AI_and_Physical_AI.md)("AI 출력은 후보/관측이며 Fleet의 작업 검증과 장치 로컬 안전 경계를 통과하기 전 물리 동작을 만들지 않는다")와 [D-290](../adr/D-290-rosy-platform-naming-and-site-intent-boundaries.md)의 현행 표현이다. 이 대조의 결론은 [D-326](../adr/D-326-agent-loop-boundary.md)으로 결정 기록됐다.

## 마디별 대조

| 개념의 마디 | 상태 | 현행 소스·근거 |
|---|---|---|
| 사용자 목표 입력 | 부분 | CORE REST(`src/runtime/api_web/core_api_web`), Fleet 콘솔(`src/site/fleet/fleet/server/web/`), `fleet/cli.py`, `games/cli.py`). 전부 구조화된 명령(goto 좌표, 작업 제출)이고 자연어 목표 해석·사용자 확인 흐름은 없음(2026-09-26 갭맵 Console 행과 동일 간극) |
| 장면 이해 | 원시적 | 로봇: `src/runtime/sensing/control/sensing/perception/`(camera·lane·road·scene_context·paint_localizer — 고전 CV, D-162 장면 상황 프로파일은 닫힌 context 집합). 사이트: `src/site/overhead/`(천장 폰 CPU ArUco → Fleet sighting). VLM/시맨틱 이해 없음. [D-268](../adr/D-268-policy-eligible-vision-evidence-for-fleet-tasks.md)이 Proposed인 한 sighting은 자동 작업 증거 자격이 없음 |
| 작업 분해 | 설계만 | FLEET SRS §14 AIV-001(Mission Planner + MSN-001 DSL)이 이 자리를 설계. 현행 [task_service](../../src/site/fleet/fleet/server/task_service.py)는 `task_type="navigate"` 단일 종류 — Mission/Step 원장·분해 없음 |
| 로봇·Skill 선택 | 약함 | [task_scheduler](../../src/site/fleet/fleet/server/task_scheduler.py) `claim_next(available_robot_ids)`는 가용성 기반 claim뿐. 로봇이 `deploy/robot/pinky_pro/config/capabilities.{core,motor,hardware}.yaml`를 광고하지만 이를 읽는 역량 매칭기는 없음. 진짜 플러그인 카탈로그는 [games/catalog](../../src/site/games/games/catalog.py)(`GAMES={"soccer"}`, `POLICIES={"heuristic"}`)뿐 — 게임 호스트 범위 |
| 진행 판단·재판단 | 밸브 폐쇄 | `task_service.py`: `POLICY_DISPATCH_ENABLED = False` → 정책 발의 작업은 즉시 HOLD. 결과 보고(`task_results.py`)·CORE 상태(`core_features/state`)·goal_tracker·reconcile은 있으나 결과를 먹고 재결정하는 자율 주체는 없음. 루프는 사람(Fleet 콘솔·HITL)으로 닫힘 |
| Robot Skill | 있음 | Nav2 관리(`core_features/navigation`), `line_follow`, `docking`(탐지~충전 풀스택), `wander`, `swarm`/formation, [decision/router](../../src/runtime/services/core_features/decision/router.py)(하드 제약→룰 1개, "no network and no actuator") |
| VLA | 없음 | 자리만 설계: 로봇 이미지 밖 `backend_learned`([D-209](../reference/ROSY ADR Log.md)), 도입 순서는 규칙 기반 → ACT → SmolVLA(OMX AI 카메라 리포트 2026-09-26 §10). "검출 → cmd_vel 지름길"은 [비전 가속기 설계](2026-09-05-vision-accelerator-shield-design.md)에서 High 위험으로 명시 거부 |
| Controller / Robot | 탄탄 | CORE가 유일 외부 게이트웨이(CORE SRS §1.3), Command Manager가 유일 `cmd_vel` 퍼블리셔(D-2), arbitration·traffic gate·HITL. sensing(흡수된 control)의 레거시 최종 퍼블리셔는 CORE 옆 병행 금지 |
| 센서·실행 결과 피드백 | 증거까지만 | observers(line/road/obstacle/dock), `detection_evidence`, `camera_evidence`, CORE Agent 업링크(이벤트 전용, 제어 채널 아님) → Fleet `core_event_store`·`task_results`. **증거 생산은 되지만 그걸 소비하는 판단자가 없음** — 루프의 화살표가 도중에 끊김 |

## 그림과 아키텍처의 구조 차이

그림은 상위 판단을 **한 상자**로 그려 루프를 직접 닫는다. 프로젝트 계약은 같은 네 인지 기능을 안전 경계로 쪼개 배치한다:

- **장면 이해 = 증거 생산자.** 로봇 탑재 perception과 사이트 overhead는 원본 출처·시각·좌표계를 보존하는 관측을 만든다. 정책이 쓸 수 있는 것은 별도 수용된 증거뿐(D-268).
- **작업 분해 = Fleet 측 Mission Planner.** 로봇 위가 아니고, Fleet API를 통해서만 명령한다(AIV-001: "AI가 직접 로봇 모터 Topic을 제어하지 않는다").
- **선택 = 스케줄러.** 사람 우선순위(`priority_class 0=operator, 1=policy`)가 이미 코드에 새겨져 있다.
- **재판단 = 작업 결과 + 사람 확인.** `POLICY_DISPATCH_ENABLED`는 그 확인 단계의 코드 표현이다.

따라서 "ER2를 어디에 둘까"의 정답은 이미 AIV-001/AIV-002(Fleet API function calling, 최소 함수 집합)에 있다: **Fleet API 위, CORE 옆 아님, ROS 토픽 위 아님.** ER2가 CORE나 cmd_vel 옆에 붙는 변형은 11_AI 문서·비전 가속기 설계·D-209가 전부 거부하는 모양이다.

## 채우려면 필요한 계약

| # | 간극 | 막힌 결정 | 비고 |
|---|---|---|---|
| 1 | 증거 → 판단 자격 | D-268(Policy-eligible vision evidence)의 Accepted/기각 여부 | Accepted로 두지 않으면 상위 에이전트는 영구히 "제안만 하는 상자"로 남음 |
| 2 | 작업 분해 | Mission/Step 스키마 + MSN-001 DSL, Fleet 확장 vs Operations 단일 이행 | 2026-09-26 갭맵 순서 3(첫 이종 미션 전 결정)과 동일 결정 |
| 3 | 역량 기반 선택 | capabilities YAML을 읽는 매칭기 계약 | 지금은 availability뿐. 로봇 수가 늘기 전엔 급하지 않음 |
| 4 | 재판단 루프 | `POLICY_DISPATCH_ENABLED`를 여는 정책+ADR. 사람 확인 단계를 어디에 둘지(제출 전/실행 전/결과 수용 전) 포함 | 1·2 없이 열 수 없는 밸브 |
| 5 | VLA | Episode 수집 → 평가 → 고정 모델 산출물 → 제한 추론 파이프라인 | D-71 후속. 2026-09-26 갭맵 Data/AI/VLA 행과 동일 |

## 근거와 제한

- 근거는 2026-09-29 Windows 호스트에서의 소스 읽기다: `task_service.py`·`task_scheduler.py`·`decision/router.py`·`games/catalog.py` 전문, `sensing/control`·`overhead`·`core_features`·Fleet `server/` 파일 목록, 그리고 인용된 SRS·아키텍처 문서·ADR. 장치·현장 계측은 없다.
- 본 문서는 개념 그림의 어느 마디도 승인하지 않고, 폐루프를 지금 열으라는 권고도 아니다. 2026-09-26 플랫폼 갭맵의 권장 순서(현재 경로의 의미 고정 → OMX 로컬 owner → 한 종류 이종 작업 → 정책 증거와 AI)가 이 갭맵의 상위 프레임으로 그대로 유효하다.
- "ER2"를 프로젝트 어휘로 채택하려면 `CONCEPTS.md`와 해당 ADR에서 이름·경계를 먼저 정의해야 한다. 본 문서는 그렇게 하지 않았다.
