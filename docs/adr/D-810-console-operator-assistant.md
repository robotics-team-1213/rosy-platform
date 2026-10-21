# D-810 통합관제 운영자 AI 대화의 출처와 조회 권한

Status: Accepted for implementation (2026-10-20 사용자 구현 요청). 운영 활성화·모델 승격·장비 이동 승인은 별도다.

## Context

관제 AI를 Console에 넣는다. 기존 D-728 대화 입력·이력은 Discord 식별자에 결속되고 실행 설치는 단일 owner만 허용한다. 웹 세션을 가짜 Discord 식별자로 바꾸거나 두 번째 실행 worker를 설치하면 기존 검증의 의미가 달라진다.

## Decision

- Console 메시지는 인증된 Fleet principal·서버의 현장 DB·대화 ID에 결속한다. 본문에는 principal·Discord 식별자를 받지 않는다.
- `core_common.protocol.assistant`가 웹 입력/조회 계약을 직접 소유·공개한다. 이미 큰 `schemas.py` facade에 재공개 행을 추가하지 않는다. API v1.294에 접수·자기 대화 조회·요청 상태·준비 상태를 추가한다. 로컬 설계의 v1.289는 미게시 번호였으며 원격의 기존 계약을 보존해 새 번호로 게시한다.
- Decision `conversation/operator.py`는 Console 전용 모델 입력을 검증한다. 기존 Discord v1 스키마·원장·broker 정책을 그대로 유지한다.
- 첫 배포는 조회 전용이다. 모델은 질문 분류와 읽기 근거 선택만 제안하고 Fleet는 근거를 검증해 응답한다. 작업 요청은 기존 작업 화면으로 안내한다. 실행·ROS·원장 수정 도구를 모델에 주지 않는다.
- Fleet `server/assistant`는 HTTP, 대화 처리, 영속 요청, 허용된 문맥 읽기를 나눈다. 별도 서버·새 최상위 폴더를 만들지 않는다. UI는 기존 정적 Console 패널로 제공한다.
- 동일 principal·요청 ID의 같은 본문은 재접수하지 않고 다른 본문은 충돌이다. RUNNING 중 재시작/취소·타임아웃 결과는 UNKNOWN으로 남기며 모델을 자동 재호출하지 않는다.
- 모델 설정과 승인 증거가 없거나 만료되면 HOLD. D-728의 기존 승인 증거로 Console 계약을 승인하지 않는다.

| 기존 결정 | 관계 |
|---|---|
| D-427 | 기존 Fleet/Decision/Console 소스 소유 영역 안에서 구현 |
| D-429 | Decision은 제안·검증, Fleet가 권한·현재 사실·실행 원장을 소유 |
| D-430 | CORE 최종 명령·기존 안전 경로를 변경하지 않음 |
| D-728 | Discord v1을 보존. 웹 대화와 조회 전용 모델 정책을 독립 검증 |

## Consequences

모델·입력 경로 변경이 UI·실행 소유자 변경으로 번지지 않는다. 별도 웹 계약과 모델 승인 시험이 필요하다. 소스·자동 회귀가 통과해도 실제 AI PC 연결·음성 품질·현장 수용의 증거를 대신하지 않는다.
