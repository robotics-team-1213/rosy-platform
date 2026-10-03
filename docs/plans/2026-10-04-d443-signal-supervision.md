# D-443 신호 감독 구현 계획

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 수용된 D-443 §1.4와 이행 (b2)의 상시 감독·presence·stale 의도 금지·seq 복구·non-agree·오프라인 나이를 기존 wire에 구현한다.

**Architecture:** `SignalConsole` 한 곳이 장치별 명령 잠금, 접촉/의도 시각, 재명령 필요 래치를 소유한다. Fleet lifespan의 취소 가능한 task가 2 s 주기로 감독한다. 인증된 operator의 presence만 수동 점등을 유지하며 화면이 숨겨지면 갱신하지 않는다. 일반 상태 조회와 viewer는 presence를 만들지 않는다.

**Tech Stack:** Python asyncio, FastAPI 역할 guard, 기존 httpx 장치 클라이언트, 순수 시계/가짜 장치 pytest, 기존 콘솔 JavaScript.

## 승인과 경계

D-443 Accepted 및 인계 문서의 이전 직후 첫 안전 작업 승인을 실행한다. firmware/wire 변경, PLC 어댑터, 계약 타입 carve, 신호 상태를 쓰는 새 로봇/Fleet admission 기능은 이 작업에 넣지 않는다. 신호 소비를 새로 연결할 때 요구되는 다섯 조건 admission 술어는 설계 정본에 남긴다. 펌웨어 S7은 다음 펌웨어 개정이다.

`seq`는 지금 wire의 마지막 수용 seq다. 내부 장부는 `max(local, status.seq)`로 동기화하며 409 `last_seq`도 같은 방식이다. `all_red`와 `flash_red`만 한 번 재시도하고 그밖에는 불일치로 남긴다. 클라이언트가 seq를 덮어쓰지 못한다.

감독 연속성은 **이번 성공 응답 이전**의 마지막 인증 접촉과 현재 시각의 차이로 검사한다. 10 s 이상 끊긴 의도는 성공 폴링이 돌아와도 복구하지 않는다. 운영자의 새 명령만 래치를 해제한다. 수동 점등 presence가 끊기면 기존 의도를 stale로 표시하고 wire `flash_red`만 보내며 자동 cycle로 바꾸지 않는다. 마지막 의도와 나이는 화면에 남긴다.

## Task 1: fail-closed 효과와 seq

- Modify: `operations/fleet/fleet/server/signals.py`.
- Test: 기존 `operations/fleet/test/test_server_signals.py`, 신규 `operations/fleet/test/test_signal_supervision.py`.
- RED: absent/pending가 agree가 아님, poll.seq 동기화, 재시작 후 safe 재시도, unsafe 재시도 금지, 두 번째409 거부, 동시 명령의 seq 직렬화 시험을 먼저 실행한다.
- GREEN: 장치별 명령 잠금과 bounded retry, 단조 장부, 별도 claimed-vs-measured 판단을 구현한다.
- Verify: 두 파일의 pytest와 `test_signal_contract.py`. 기존 "all_red도 재시도 없음" 시험은 승인된 안전 방향 재시도 규칙으로 바꾼다.

## Task 2: 감독 연속성과 presence

- Modify: `signals.py`, `console.py`, `console_routes.py`, `app.py`, `web/console.js`, `web/signals.js`.
- RED: 장시간 공백 뒤 재단언 금지/재접촉 후에도 래치 유지, 수동 absence/timeout 시 flash_red, 비수동 presence 무관, viewer/일반 조회가 presence를 만들지 않음, UI 없이 lifespan 감독, 종료 시 task 취소 시험.
- GREEN: 단조 시각과 stale 래치, actor presence, Fleet lifespan 감독과 취소를 넣는다. `POST /api/fleet/signals/presence`는 기존 operator guard와 actor 식별을 사용한다. 수동 명령은 그 인증 actor의 presence를 시작한다.
- Verify: 신호·auth·console·app·전체 정지 관련 pytest, 기존 Node 콘솔 회귀.

## Task 3: 증거와 통합

- Modify: `operations/fleet/logs.md`, 생성 `index.md`, `operations/fleet/docs/`의 살아 있는 신호 사용 문서.
- Create: `docs/validation/d427-source-migration/signal-supervision-2026-10-04.md`.
- 독립 리뷰는 재단언 래치와 presence/seq 경합, 전체 정지 safe retry의 실패 처리, 감독 loop의 시작·종료를 확인한다. 발견한 결함은 RED 재현 뒤 고친다.
- `python tools/harness/rosy_harness.py generate`, lint 0 error, 관련 pytest/known_failures NEW 0, Safety-Review trailer를 확인하고 커밋한다. 커밋한 깨끗한 checkout에서 대표 회귀를 재검증한다.
- main 반영은 마이그레이션 푸시 완료 후 fetch/rebase/generate/pre-push 순서를 따른다. 호스트 시험은 ROS-SIM·ARM64·기기·FIELD 증거가 아니다.
