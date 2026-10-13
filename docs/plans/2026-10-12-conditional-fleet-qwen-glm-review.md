# Fleet·Qwen 불일치와 GLM 재평가 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 무료 Qwen 기본 추론을 유지하면서 Fleet 판단과의 불일치를 제한된 GLM 재평가로 기록한다.

**Architecture:** Fleet이 사건과 판단 기준·원장을 소유하고 Decision이 검증·비교·조건부 검토를 수행한다. AI PC는 기존 OpenCode와 선택된 GLM 인증을 격리된 실행 경로에 연결한다. 재평가 완료는 HOLD이며 CORE 명령 승인과 독립 평가를 대신하지 않는다.

**Tech Stack:** Python asyncio/sqlite3, 기존 Decision CLI 번역기, OpenCode 1.18.35, bubblewrap/systemd scope, AF_UNIX, 기존 GLM Coding Plan.

---

## Task 1: 비교와 원장 계약

- Modify: `operations/decision/src/rosy/decision/deliberation/conditional.py`, `operations/decision/src/rosy/decision/deliberation/__init__.py`.
- Modify: `operations/fleet/fleet/server/deliberation_journal.py`, `operations/fleet/fleet/server/incident_deliberation.py`.
- Test: `operations/fleet/test/test_conditional_review.py`, `test_deliberation_journal.py`, `test_incident_deliberation.py` (같은 디렉터리).

1. Fleet·Qwen 일치 1회 종료, 불일치 시 Qwen 1회+GLM 1회, 다른 사건·정상·위험·비용 불명에서 GLM 미호출 시험을 먼저 추가한다.
2. 원격 RED를 확인하고 같은 사건 digest에 Fleet의 검증된 판단을 포함한다. 비교 기준이 없으면 비교 결과를 만들어 내지 않는다.
3. 기존 정책과 조건부 정책의 cached 결과 교차 사용을 HOLD로 거부한다. 두 번째 검토는 항상 HOLD이며 추가 호출하지 않는다.
4. 커밋한 HEAD를 원격 시험하고 known_failures와 비교한다. 관련 suite의 기존 Supervisor 동작도 검증한다.

## Task 2: 고정 GLM 실행 경계

- Create: `deploy/ai_pc/deliberation_glm_gateway.py`, `deploy/ai_pc/deliberation_relay.py`, `deploy/ai_pc/deliberation_opencode.py`.
- Test: `test/test_deliberation_glm_gateway.py`, `test/test_deliberation_relay.py`, `test/test_deliberation_opencode.py`.

1. 가짜 전송 시험으로 모델 ID·목적지·tools·토큰·응답 바인딩·시간·권한 오류를 재현한다.
2. 기존 `SandboxLauncher`, `bounded_process`, `cleanup_scope`를 재사용한다. namespace에는 인증 없이 고정 소켓과 최소 설정만 연결한다.
3. OpenCode의 도구·플러그인·MCP·자동 갱신·부가 모델 호출을 제한한다. 게이트웨이도 요청을 검증하므로 설정만으로 도구 제한을 증명하지 않는다.
4. 취소와 시간 초과 후 호스트 게이트웨이와 namespace 자식 전체의 종료를 확인하고 원격 GREEN을 기록한다.

## Task 3: 합성 사건 한 번의 실제 호출

- Modify: `docs/validation/deliberation-host-admission-2026-10-12/result.md`.
- Create: 같은 디렉터리의 `glm-review-smoke.md`.
- Temporary scripts/receipts: 세션 `X:/DevTemp/projects/rosy-platform/2026-10-12--033443--deliberation-local-gateway--fc42b3/`.

1. 검증된 소스를 AI PC의 비공개 임시 디렉터리에 전송하고 hash를 확인한다.
2. 관리자 스크립트는 선택된 `zai-coding-plan` 인증만 전용 계정의 0600 파일로 설치한다. 인증을 출력하지 않는다.
3. 실제 요청 전 영속한 사용 표식을 선점한다. 결과 불명·실패도 자동 재발송을 금지한다.
4. 사용자에게 실행할 OpenSSH 명령 한 줄을 제공한다. 사용자가 실행한 뒤 비공개 값 없이 로그·종료 코드·모델·호출 수·토큰·cleanup을 읽어 확인한다.
5. 한 건·한 번·1,024 출력 토큰·30초의 증거를 보고한다. 실제 비용이 불명이면 별도로 명시한다.

## Task 4: 독립 평가와 현장 수용

팀이 Pinky 차선 정지·재관측의 정답을 검수한다. 관측 부족·위험 누락·다른 사건에 조치·정상 상태의 불필요 명령은 수용 세트에서 0건을 요구한다. 나머지 정확도·지연 한계는 사람 검토 후 확정한다. Discord는 별도 담당 세션이 처리한다.

## Validation commands

커밋 후 워크트리에서 실행한다. pytest 자체는 원격 PC에서만 실행한다.

```powershell
python tools/remote/remote_pytest.py --log-dir X:/DevTemp/conditional-review-check -- operations/fleet/test/test_conditional_review.py operations/fleet/test/test_deliberation_journal.py operations/fleet/test/test_incident_deliberation.py
python test/known_failures.py X:/DevTemp/conditional-review-check/run-1.txt
python tools/harness/rosy_harness.py lint
```

실제 모델 호출 성공과 독립 정답·현장 수용은 별도다. 관련 원격 시험과 독립 검토가 끝난 뒤 사용자에게 이미 승인받은 로컬 착지를 진행한다. push는 별도 요청이 필요하다.
