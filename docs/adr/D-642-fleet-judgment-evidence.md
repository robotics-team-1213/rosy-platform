## D-642 Fleet 판단 1단계 사건 근거와 현재 상태 규약

**Status:** Proposed (2026-10-11, 사용자 요구: Fleet 중앙 판단 규약을 D-640보다 먼저 단계별로 다듬고 비개입과 외부 사람 처리를 포함). 문서만이며 구현·배포·모델 호출·외부 발송·장치 수용은 미실행.

### Context
화면의 과거 사건에는 CORE 원인, 시작 단계, 주변 카메라 메타데이터, AI 초안, Fleet 답과 사람 검토가 함께 표시된다. 최신 관측과 당시 자료, 진단과 원인 확정의 의미를 먼저 고정해야 중앙 판단의 정확도를 평가할 수 있다.

### 책임·배포 선행 관문
[D-647 공통 판단 책임·배포 0단계](../adr/D-647-shared-judgment-ownership-and-deployment.md)을 먼저 따른다. 이 ADR의 Fleet은 현재 소비자·서비스 문맥이다. 공통 상황평가 holder와 초기 배포는 아직 미결정이며 권고와 작업/자원 승인·원장 소유를 구별한다. 기존 Fleet transaction과 CORE/OMX 권한은 유지한다.

### Decision
1. 기존 incident/episode와 robot/site/Mission/attempt 식별을 재사용한다. 각 근거에 원본 producer, 관측/수신 시각, 사건 binding, 지도·보정·정책 revision, 신선도와 누락/상충을 구분한다. 시간상 근접한 카메라 관측만으로 사건 원인을 확정하지 않는다.
2. 현재 열린 개입과 닫힌 사건 보고를 분리한다. `phase_at_open`은 당시 단계, `held_s_max`는 과거 집계이며 지금의 로봇 상태로 읽지 않는다. 닫힌 사건 자료로 새 답을 보내지 않는다. 현재 상태를 못 읽으면 미확인으로 둔다.
3. `line_stuck.cause`는 장치가 보고한 증상, AI `cause_draft`는 가설, 사람 검토는 검토 기록으로 유지한다. `ContextDraft`의 원인별 0.45/0.35/0.2 값은 코드에 고정된 초안 점수이며 보정된 확률·원인 정확도가 아니다. 검증 방법 없는 점수는 화면에서 실측 신뢰도로 표시하지 않는다. 모델 자신이 사실을 verified로 승격하지 못한다.
4. 근거 갱신 시 같은 사건의 새 판단 revision을 남긴다. 현재 ContextDraft의 사건당 1회 `seen` 억제를 재관측 갱신에 어떻게 연결할지 구현에서 명시한다. 원본·과거 검토는 덮어쓰지 않는다. 종료 후 보존되지 않은 앞 영상은 없는 근거다.
5. 공개 필드/호환 정책은 API Reference와 producer/consumer validator 및 fixtures를 함께 바꿀 때 확정한다. 이 문서는 새 wire enum이나 endpoint가 아니다.

### 완료 관문
당시/현재, stale/미래 시각/상충/누락, 잘못된 사건·지도·보정 binding, 고정 점수 표시, 닫힌 사건 재사용 거절에 대한 원격 계약 시험이 통과해야 한다. 기존 SQLite 보고서의 비파괴 이전과 현재 API 호환을 확인한다. 장치·영상 내용 정확도와 현장 수용은 별도다.

### 기존 계약과 범위

D-427의 소유 분류, D-429의 후보/실행 분리, D-430의 safety gate와 CORE/OMX 최종 writer를 유지한다. D-608/D-619의 사건·상황 및 D-632의 inbox 의미를 재사용한다. 새 공개 API는 producer/consumer와 API Reference를 함께 변경할 때 확정한다.

단계 순서·수용 시나리오·파일별 작업은 [중앙 판단 선행 계획](../plans/2026-10-11-fleet-central-judgment-stages.md)을 따른다.
