## D-664 주행·고정 셀·이동식 로봇암의 공통 작업 개념과 책임 검토

**Status:** Accepted (2026-10-11; 개념 경계와 공통 읽기 첫 단위). 사용자 구현 요청에 따라 원장별 공통 읽기 API와 화면을 구현한다. 복합 Asset, 다단계 실행, 동시 주행·팔 작업과 장치 수용은 후속이며 활성화하지 않는다.

**Context:** D-296은 Fleet의 사이트 조정과 장치 미들웨어의 실행을 구별한다. 그러나 Console의 관제/Cell 분류는 장치 종류, 작업 공간, 공정 앱을 같은 탐색 층위에 놓는다. 현행 주행은 `FleetTaskStore`의 navigate 요청이며 `MissionStore`는 고정 workcell의 `PICK_PLACE`만 허용한다. Cell 제출은 `pallet.transfer`로 제한된다. 따라서 공통 Mission이라는 이름만으로 혼합 장치 작업을 지원한다고 표시할 수 없다. CONCEPTS의 모바일 Device/Asset 설명과 목표 OMX 설명도 구현 단계가 다르다.

**Decision:**

1. 화면과 문서에서 장치(Device: 독립 실행·정지 경계), 구성(Component: 장치의 하드웨어), 기능(Capability: 현재 검증된 수행 가능성), 작업 공간(Workcell: 좌표·설비·접근·공유 자원 범위), 공정(Process: 수행할 업무), 작업(Mission: 사이트 목표·순서·결과)을 구별한다. Rosy Cell 앱과 `rosy_cell.cell/2`는 현재 팔레타이징 앱/설정 계약으로 유지하며 범용 Workcell 계약으로 재해석하지 않는다.
2. Fleet는 사이트 Mission 원장·배정·순서·공유 자원·인계를 소유한다. 공정 컴파일러는 계획 후보를 만든다. World/Vision은 출처·좌표·시각·revision을 가진 관측을 제공한다. AI는 맥락에 대한 판단·후보를 반환한다. 장치의 수락과 최종 실행·안전 판단은 CORE/OMX owner에 남긴다(D-296, D-369, D-657).
3. 운반 로봇과 고정 팔의 협업은 사이트 단계와 인계로 묶는다. 베이스에 장착한 팔은 D-55의 별도 로컬 복합 transaction과 상태별 footprint/속도/충돌 장면 검증이 필요하다. 물리 장착 또는 UI 묶음만으로 복합 운용 기능을 활성화하지 않는다.
4. Console은 공통 현장 개요·작업·장치·작업 공간·알림을 중심으로 구성한다. 주행 지도와 팔 작업 장면은 선택한 작업/장치의 문맥별 패널로 둔다. 연결됨, 설치됨, 실행 가능, 수락됨, 실행 중, 완료 근거 확인을 구별한다. 기존 경로와 권한은 단계적 이전 기간에 유지한다.
5. 현재 원장을 즉시 병합하거나 범용 실행기를 새로 만들지 않는다. 읽기 전용 공통 투영으로 출처별 상태와 ID를 보여 준다. 첫 단위의 `GET /api/fleet/work`는 SRS `UI-WORK-001`·API Reference·typed schema와 함께 정의한다. 기존 Mission 상세의 principal 소유 범위를 유지하며 제한된 최근 목록임을 표시한다. 후속 실행 계약은 한 가지 운반→고정 팔 인계 시나리오로 한정하며 기존 장치 API를 사용한다. 실행을 위한 새 외부 필드/경로는 후속 계약으로 확정한다.

**Alternatives:** 현재 두 앱을 따로 유지하면 빠르지만 혼합 작업의 책임과 이력이 계속 갈라진다. 모든 장치를 한 범용 제어기로 통합하면 권한·장치 수용 범위를 크게 바꾼다. 공통 작업 모델과 장치별 실행 경계를 조합하는 안을 권고한다.

**Consequences:** 탐색 구조와 실행 범위를 함께 명시할 수 있다. 읽기 화면 통합과 실제 다단계 실행은 별도 작업이다. 기존 `PICK_PLACE` 제한을 삭제하는 것으로 다장치 협업을 구현하지 않는다.

**Validation:** [검토·단계별 계획](../plans/2026-10-11-mixed-device-work-design.md)의 협업 인계, 중복/지연 메시지, 취소·재시작·정지 범위, 완료 증거 시나리오를 요구한다. 문서 검증은 장치/현장 협업 수용이 아니다.

**References:** [D-55](D-55-mobile-manipulation-is-a-robot-local-mission-capability.md), [D-296](D-296-device-middleware-and-site-orchestration-terminology.md), [D-298](D-298-mission-action-and-stop-evidence-terminology.md), [D-369](D-369-control-authority-and-stop-evidence.md), [D-657](D-657-judgment-adapter-and-pure-execution-extraction.md), [CONCEPTS](../../CONCEPTS.md).

> 2026-10-14 부기(D-763): 5항의 소유 범위는 [D-763](D-763-fleet-work-kinds-composed-steps.md)(Accepted)이 바꾼다: 두 사람 승인이 필요한 작업의 요약 행은 다른 이름 있는 운영자에게도 보인다. 상세와 본문의 소유 범위는 그대로다. 해당 조각(D-763 4)이 착지할 때 적용된다.
