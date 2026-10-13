## D-660 Fleet 현재 판단 영수증과 관측 종료를 구분한다

**Status:** Accepted (2026-10-11, D-656 단계별 처리 사용자 지시의 읽기·기록 범위). 중앙 실행 정책·모델 호출·실채널·장치 수용은 이 결정의 승인 범위가 아니다.

### Context

D-652의 공통 판단은 내부 shadow다. 과거 사건에서 고정된 45% 초안 점수와 수락된 WAIT, `cleared` 종료를 복구 성공처럼 읽을 수 있다. 정상 구간 기록 없이 열린 사건만 평가하면 오개입 분모가 없다. D-656 Task 0~2의 원장 도구/순수 규칙 분리 뒤 현재 증거와 관측 종료를 명확하게 연결한다.

### Decision

1. CORE snapshot adapter와 `LineStuckBoard`의 같은 불변 입력을 재사용한다. `/api/fleet/state`의 로봇 행에 선택 `judgment`를 추가한다. `FleetJudgmentReceipt`는 현재 시각에서 재검사한 필요성·사유·정책·유효기한과 원본 request를 담는다. 원본 metadata는 미확인·잘못된 값도 보류 근거로 남는 자료이며 실행 인자가 아니다. `shadow=true`, `action_admissible=false`를 고정한다. 공개 출처와 계약은 API Reference v1.206/`core_common.protocol.schemas`에 함께 기록한다.
2. 기존 Fleet DB에 `fleet_judgment_current`(로봇당 최신 참고)와 `fleet_judgment_records`(변화 및 60초 정상/보류 분모 표본)를 추가한다. 원장 소유자는 `LineStuckAnswerLog`다. board는 기존 ordered flush를 사용하고 별도 Mission DB를 만들지 않는다. 필요성·사유·case·owner·정책 변화는 즉시, 같은 분류는 60초마다 기록한다. 보존은 7일이며 단순 표본 수를 전체 현장 시간·정답 수로 치환하지 않는다. viewer+의 `/api/fleet/judgments?limit=1..1000`은 과거 기록 조회다.
3. `FleetObservedClosure`를 기존 incident 응답에 더한다. `cleared`이며 수락/응답불명 답이 없으면 `NATURAL_CLEARANCE`; 답이 있으면 `CLEARANCE_OBSERVED`와 `UNVERIFIED` 조치 기여다. 열림은 `OPEN`, restart/replaced/left_roster 등은 `OBSERVATION_ENDED`이며 해결이 아니다. 기존 `resolved_by`는 호환을 위해 남기되 마지막 수락 답의 주체라는 진단 자료로만 표시한다. 기존 board가 사건 종료를 쓰는 책임은 유지한다.
4. Console은 과거 단계, 검증되지 않은 원인 초안 점수, 관측 해소와 조치 성공 미검증을 분리한다. 현재 사건이 다르거나 TTL을 넘긴 판단은 보류로 표시한다. 정상 기록은 새 장치 명령이나 새 사건을 만들지 않는다.
5. 사람 인수/알림 outbox, 현재 owner·revision·stop generation에 묶인 운영 소비와 independent FIELD receipt는 D-644~D-646 후속 관문이다. D-660 참고 판단을 admission, 해소 정답, 성능 확률, 새로운 자동 실행 권한으로 소비하지 않는다. 평가의 정답과 정확도·지연 한계는 팀원 검토 후 확정한다. 근거 부족은 보류이며 위험 누락/다른 사건 조치/정상 불필요 명령 0건 조건과 구별한다.

### Consequences and verification

현재 입력의 stale/case 변경, 정상 분모의 샘플링·재시작·보존, 무조치 해소, 관측 종료, viewer 인증/조회 한도, UI의 TTL/case 표기를 remote 계약과 설치 시험으로 검증한다. 표본의 영상 의미·현장 정확도·사람 인수·실채널 수신·장치 결과는 각각 별도다. D-642~D-646 전체를 Accepted로 올리거나 D-640 모델 토론 관문을 통과시킨 결정은 아니다.
