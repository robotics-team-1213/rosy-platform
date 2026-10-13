## D-644 Fleet 판단 3단계 중앙 중재와 조치 결과 규약

**Status:** Proposed (2026-10-11, 사용자 요구: Fleet 중앙 판단 규약을 D-640보다 먼저 단계별로 다듬고 비개입과 외부 사람 처리를 포함). 문서만이며 구현·배포·모델 호출·외부 발송·장치 수용은 미실행.

### Context
같은 문제에 rule, AI, 운영자, trip owner가 동시에 대응하면 충돌한다. `WAIT 수락`, episode 종료, 실제 문제 해결은 각각 다른 결과이며 현재 보고의 `resolved_by`도 수락된 답 tier에서 계산될 수 있다.

### 책임·배포 선행 관문
[D-647 공통 판단 책임·배포 0단계](../adr/D-647-shared-judgment-ownership-and-deployment.md)을 먼저 따른다. 이 ADR의 Fleet은 현재 소비자·서비스 문맥이다. 공통 상황평가 holder와 초기 배포는 아직 미결정이며 권고와 작업/자원 승인·원장 소유를 구별한다. 기존 Fleet transaction과 CORE/OMX 권한은 유지한다.

### Decision
1. 현재 Fleet 서비스 안의 작업/사건 owner가 권고 소비·사건 소유·조치 제출을 중재하고 Fleet coordination은 배차·교통·로봇 공유 자원을 담당한다. 이는 D-435의 목표 역할 구분을 검토하는 제안이며 기존 원장의 실제 소유를 바꾸지 않는다. 로봇/작업별 활성 판단 하나, 현재 owner/claim/attempt/generation, 사람이 맡은 사실을 기존 원장에 연결한다. 자동 판단은 운영자 소유를 침범하지 않는다. 새 agent나 알림 채널이 별도 writer를 만들지 않는다.
2. 비개입은 durable 판단 기록만 남기며 장치 요청을 보내지 않는다. 판단 보류는 필요한 근거/다음 확인 시점과 담당을 남긴다. 개입은 기존 허용 답/Skill/후보와 정책·현재 capability·CORE/OMX 검사를 통과해야 한다. 단계 2에서 개입 필요라고 해서 새 실행 권한이 생기지 않는다.
3. 판단, 제출, 수락/거절/응답 불명, 실행 terminal, 목표 확인, 문제 해소를 따로 기록한다. 답 수락이나 `WAIT` 유지로 해결 성공을 판정하지 않는다. 개입하지 않고 자연히 해소된 경우도 관측 결과로 닫고 인과 성공을 주장하지 않는다.
4. 동일 판단 revision의 중복은 같은 결과로 조정한다. stop·새 세대·사건 변경·다른 owner·기한 초과이면 늦은 후보/알림 응답은 거절한다. timeout 뒤 physical action을 맹목 재전송하지 않고 실제 owner 상태를 확인한다. 기존 제한 재전송/복구 예산을 넓히지 않는다.
5. 원장 실패는 새 조치 제출을 차단하고 기존 safety chain은 독립 유지한다. 재시작은 durable 소유와 장치 readback을 대조하며 자동 재무장하지 않는다. E-stop, 보정 lease, 후방/사각·Arm 하중 조건과 최종 writer를 우회하지 않는다.

### 완료 관문
rule/AI/사람 경쟁, trip owner, 다른 작업, 중복/내용 변경, 늦은 응답, 원장 장애, 중간 재시작, 결과 불명과 재발을 remote fake-clock/transport 계약 시험으로 확인한다. safety 태그의 실제 변경은 D-430 독립 Safety 리뷰가 필요하다. 실물 정지·복구·목표 수용은 여전히 별도다.

### 기존 계약과 범위

D-427의 소유 분류, D-429의 후보/실행 분리, D-430의 safety gate와 CORE/OMX 최종 writer를 유지한다. D-608/D-619의 사건·상황 및 D-632의 inbox 의미를 재사용한다. 새 공개 API는 producer/consumer와 API Reference를 함께 변경할 때 확정한다.

단계 순서·수용 시나리오·파일별 작업은 [중앙 판단 선행 계획](../plans/2026-10-11-fleet-central-judgment-stages.md)을 따른다.
