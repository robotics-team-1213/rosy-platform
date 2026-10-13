# Fleet 실제 규칙 선택 근거 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 실제 resolver 선택을 원장에 기록하고 의미가 일치하는 선택만 조건부 모델 검토의 기준으로 연결한다.

**Architecture:** selector 실행은 기존 Fleet resolver 하나다. loop가 실제 결과·Assessment를 결속하고 observe가 같은 DB에 저장한다. 독립 소비 가능한 JSON은 contracts.learning에서 검증하며 factory는 현재 기록의 읽기 포트만 연결한다.

**Tech Stack:** 기존 Python dataclass/SQLite, 공통 계약 wheel, 기존 Fleet 설치·원격 시험.

## 실행

1. `operations/fleet/test/test_rule_selection.py`에서 실제 정상/HOLD/HANDOFF pass, physical ANSWER 미변환, MIXED·stale·다른 사건·기록 실패 거절 시험을 먼저 추가하고 원격 RED를 확인한다.
2. `contracts/learning/src/rosy/contracts/learning/incident_rule.py`에 exact-field·finite·scope·kind·privacy 검증을 구현한다. 명령/모델/결과 건수를 추정하지 않는다.
3. `operations/fleet/fleet/observe/rules.py`에 동일 DB의 bounded append/read 원장을 구현한다. `stuck/pipeline.py`와 `stuck/loop.py`에서 실제 step 결과를 기록하며 모델 시작 전에 현재 기준을 교체한다. 기록 오류는 기존 dispatch를 중단하지 않고 비교 기준을 비운다.
4. `incidents/automation/runtime.py`에서 미지정 baseline만 현재 저장 선택 포트로 연결한다. physical/mixed/ABSTAIN/stale/다른 사건은 None이며 수동 기존 포트의 호환은 유지한다.
5. 커밋 HEAD를 적격 시험 PC로 보내 신규 실패와 비교한다. 실제 설치·기존 resolver/model loop·holder/크기를 확인하고 독립 검토 후 승인된 local landing을 한다. 전체 map/lifecycle provenance·규칙 전략 export/독립 cohort 비교·배포·현장 수용은 후속이며 목표 완료로 바꾸지 않는다.

## Source 검증 checkpoint

최신 main 통합 commit `8520b77d663e1922f68518821ed771ad4d080d5e`를 로컬 착지했다. 적격 AI PC 9GB의 12개 시험 그룹은 621 passed/1 skipped, terminal exit 0, known-failures NEW 0과 lint를 통과했다. 실제 wheel/sdist·base loop·local policy loader·계약·기존 resolver/worker와 parent/child 구조 회귀를 포함한다. 고정 로그는 세션 `logs/rule-land-8520b77d66/run-1.txt`다. 아래 측정과 부분 시험은 통합 전 checkpoint이며 실제 모델·CI·배포·현장 수용을 승인하지 않는다.

commit `5a9859b5b`의 원격 8개 그룹은 적격 AI PC 9GB에서 343 passed/1 skipped, terminal exit 0, known-failures NEW 0이다. 실제 wheel·sdist→별도 target 설치에서 SDK 파일 위치·필수 dependency metadata·기본 resolver 생성을 확인했고 기존 local execution loader와 learning artifact 계약을 함께 검사했다. 로그는 세션 `logs/rule-final-green/run-1.txt`다.

독립 검토의 bare Fleet 설치 의존성과 autonomous WAIT 의미 지적은 재현 RED 후 수정했다. SDK 0.1.10을 필수 설치하고 기존 extra 이름을 유지한다. CI offline installer와 local execution의 고정 SDK 버전도 함께 맞췄으며 새 CI-input 환경 준비를 확인했다. 모든 physical ANSWER는 비교 기준 None이며 human 비교는 실제 HANDOFF 선택에만 적용한다. 비활성 AiFirst·기록 실패·claim 경합·현재 rule config 변경도 거절한다. 추가 commit `a12ea31e57`의 실제 selector→factory→worker Problem.fleet_choice 연결과 config fence는 18 passed/NEW 0이다.

같은 source 필터의 독립 동시 실측은 Fleet 부모 55,460/55,814, observe 293/362, stuck 3,385/3,467, automation 472/472다. 기준·+150을 올리지 않았다. automation은 여유가 없으므로 후속 성장은 실제 책임 분리·설치·호출자·부모/child 동시 검증을 먼저 해야 한다. 독립 재검토에서 중요한 미해결 source blocker는 없었다. 최신 main 통합·local landing은 다음 gate이며 실제 모델·CI·배포·현장 수용·명령/호출/재발 0건은 입증하지 않는다.
