# D-720 — Discord 상태 질의와 읽기 전용 숙고형 연결

- Status: Accepted (source design; runtime acceptance remains separate)
- Date: 2026-10-12
- Related: D-671, D-675, D-679, D-680, D-693, D-694

## Decision

`fleet_status/READ_ONLY_QUERY`만은 root가 승인한 `d720-read-only-status-v1` 정책으로 action calibration을 면제한다. 고정 source·primary profile SHA·모델 digest/context·schema conformance 실제 추론을 검증하고 정책 만료를 확인해야 한다. 답글 사실은 현재 관측의 deterministic formatter만 사용하며 모델 자유 문장은 사실로 게시하지 않는다. 이 면제는 정확도·물리 수용이나 장치 실행·복구 판단·학습 후보 승격을 허가하지 않는다. 다른 domain의 calibration과 GLM 독립 status admission·실제 계정/키/비용 증거·1회 spent 예산은 그대로 필요하다.

사용자의 관제·AI·Discord 실제 왕복 및 숙고형 연결 지시를 구현한다. Discord 원문은 기명 요청 자료이며 명령·권한·현재 CORE 사건을 만들지 않는다. 일반 상태 질의를 line_follow 막힘으로 위장하지 않고 별도 읽기 전용 fleet_status 도메인으로 검증한다. 기존 line_follow/door/arm_target 모델 계약과 정상 무개입 경로는 유지한다.

Fleet의 기존 tasks journal이 immutable receipt, 현재 user mapping/계정/원문 hash, 고정 profile 집합과 현재 관측에 묶인 모델 job을 소유한다. 모델 호출 전에 attempt·한도를 영속 예약한다. 재시작·취소·응답 불명은 UNKNOWN이며 자동 재발송하지 않는다. 각 await 뒤 원문 소유권·계정·관측·profile을 다시 확인한다. 결과와 기존 reply outbox를 같은 transaction으로 저장한다. 원래 채널·메시지·nonce·mentions 차단·provider readback 규칙을 유지한다.

상태 질의의 입력은 bounded 현재 관측과 원문이며 출력은 바인딩된 schema 2 advisory다. 상태 도메인의 tool은 읽기 전용 현재 Fleet 조회뿐이다. Task/Mission/incident claim, 주행·정지·E-stop 해제, 장치 성공 또는 독립 목표 수용을 만들지 않는다. 현재 CORE 사건은 별도 incident worker와 기존 사건 예산을 공유하며 Discord 원문마다 CORE 예산을 새로 만들지 않는다.

기본 제공자는 고정 Qwen profile이다. GLM 검토는 D-679의 유효 불일치/형식·근거 검토 조건과 승인된 비용·호출 한도에서만 수행한다. 정상 상태와 권한/근거 부족은 모델 무호출 또는 HOLD다. 원문 status 질문에 대한 읽기 전용 설명과 장치 조치의 admission은 구분한다.

Fleet↔AI 전달은 고정 host/known_hosts와 broker 전용 key의 bounded SSH/stdin을 사용한다. 기존 Service Control key를 재사용하거나 임의 host/argv/URL을 허용하지 않는다. AI의 보호된 전용 계정이 고정 모델·sandbox·credential·비용 증거를 검증한다. 소스의 ready/isolated/cost_verified 표식을 참으로 바꾸는 것으로 운영 수용을 대신하지 않는다. 관리자 설치·호스트 preflight·실제 모델 receipt·billing 근거와 calibration은 각각 읽어 확인한다.

첫 GLM 외부 시험은 기존 1회·30초·1,024 출력 토큰·무재시도 규약을 유지한다. UNKNOWN 비용을 0으로 만들지 않는다. 모델 의견은 실행 가능한 후보나 정확도 증거로 자동 승격하지 않는다.

## Verification

원문 수정/계정 철회/다른 채널·owner, stale 관측, profile drift, malformed schema, HTTP/SSH 중단, 취소, job/outbox transaction 실패, 재시작·중복·비용 불명과 전용 계정 경계를 원격 검증한다. 실제 신규 Discord 메시지 → Fleet receipt → 고정 숙고형 호출 → validated result journal → reply outbox → Discord readback을 별도로 확인한다. 현재 오프라인 기기는 FIELD 성공으로 집계하지 않는다.
