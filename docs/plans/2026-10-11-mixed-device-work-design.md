# 주행·고정 셀·이동식 로봇암의 공통 작업 구조 검토

날짜: 2026-10-11. 기준 소스: `94d253307`. 브랜치: `docs/mixed-work-responsibilities`.
상태: 검토 및 제안. 연결 ADR: [D-664](../adr/D-664-mixed-device-work-and-workcell-boundaries.md).

## 문제와 현행 근거

| 관찰 | 근거 | 의미 |
|---|---|---|
| 주행 요청은 별도 작업 원장 | `operations/fleet/fleet/server/task_service.py`: `submit_navigation`, `FleetTaskStore`, `task_type="navigate"` | Cell Mission과 공통 다단계 이력으로 연결됐다는 증거가 없다. |
| Mission은 고정 팔 동작으로 제한 | `operations/fleet/fleet/server/mission_store.py`: SQL `action_kind='PICK_PLACE'`, `create_proposal`의 동일 검증 | 범용 Mission 명칭과 실제 지원 범위가 다르다. |
| Mission 배정은 OMX workcell 중심 | `operations/fleet/fleet/server/mission_dispatcher.py`: `omx_instances`, workcell/instance 일치 검사 | 이동 장치 배정을 그대로 추가할 수 있는 범용 dispatcher가 아니다. |
| Cell 계획은 팔레타이징 전용 | `operations/execution/src/rosy/execution/site/cell_submission.py`: `pallet.transfer`만 허용, workcell/pallet 자원 | 앱 설정을 범용 공간 모델로 취급하면 공정과 공간이 혼재한다. |
| Cell 화면은 별도 문서·계획·승인 흐름 | `operations/ui/console/cell/cell.js`: `/api/fleet/cell-app/documents`, recipe/cell/compile/propose/admit | 주행과 팔 작업을 한 흐름으로 이해할 공통 작업 화면이 필요하다. |
| Device/Asset 용어에 구현 단계가 섞임 | `CONCEPTS.md`: Device는 CORE 관리 로봇, OMX는 제안; Asset v1 mobile_base, 복합 Asset 미구현 | 목표 개념과 현재 장치 등록·실행 가능성을 나누어 표시해야 한다. |
| 책임 계약은 이미 존재 | D-296·D-298·D-369·D-55 | 책임을 새로 뒤집기보다 기존 경계를 작업과 화면에 반영해야 한다. |

이는 소스 기준 평가이며 실제 고정 팔·이동식 팔의 설치 또는 현장 수용 여부를 조사한 결과는 아니다.

## 개념과 책임

| 개념 | 질문 | 책임/예시 |
|---|---|---|
| Site | 어디서 작업하는가? | 현장의 공간·장치·작업 집합. Fleet가 현장 작업을 조정한다. |
| Device | 누가 실행하고 멈추는가? | 이동 베이스, 독립 팔 제어 인스턴스. CORE/OMX 로컬 owner. |
| Component | 무엇으로 구성되는가? | 구동부, 센서, 그리퍼. 별도 제어 경계가 있는지는 계약으로 확인한다. |
| Capability | 지금 무엇을 할 수 있는가? | 이동·파지·배치 기능의 현재 검증 상태와 허용 범위. 설치 프로파일과 구별한다. |
| Workcell | 어떤 작업 공간과 자원을 공유하는가? | 작업대, 접근 구역, 프레임, 보정, 설비. 팔 자체나 공정 이름과 구별한다. |
| Process/Recipe | 무엇을 어떤 규칙으로 만드는가? | 팔레타이징, 운반 후 적재. 공정 코드가 계획 후보를 만든다. |
| Mission/Step | 어떤 목표를 어떤 순서로 달성하는가? | Fleet가 배정·예약·인계·전체 결과를 소유한다. |
| Device Action/Local Transaction | 장치가 수락한 범위 안에서 어떻게 실행하는가? | 장치가 최신 상태를 대조하고 로컬 절차를 수행한다. 수락과 완료를 구별한다. |

AI는 목표·작업 단계·장치별 기능·공간 프레임·관측 시각/revision·기존 행동과 결과를 맥락으로 받는다. 판단의 관찰 사실, 해석, 불확실성, 제안, 제약을 표시하며 장치 명령 권한으로 간주하지 않는다. 영상은 해당 판단의 capture ID/시각과 연결하고 현재 영상과 구별한다. 구체적인 외부 envelope 변경은 이 문서에서 정의하지 않는다.

## 함께 쓰는 두 시나리오

### 운반 베이스 + 고정 팔

같은 사이트 작업 안에서 다음 경계를 확인한다.

1. Fleet가 목적 작업 공간의 접근·작업 자원과 장치를 배정한다.
2. CORE가 운반 요청을 수락하고 이동한다. 도착 응답 외에 지정 공간의 위치·정지 상태·좌표 revision을 확인한다.
3. Fleet가 인계를 승인한다. 물건·수량/identity·위치·소유 상태와 최신 증거를 연결한다.
4. OMX owner가 팔 작업을 수락한다. 로컬 충돌·툴·보정·현재 물체 상태가 맞아야 실행한다.
5. 팔 결과와 작업 목표 증거를 대조한 뒤 다음 단계 또는 전체 완료를 기록한다.

한 장치가 멈추면 해당 장치에 의존하는 다음 단계는 HOLD한다. 무관한 작업과의 관계는 공유 자원 및 정지 범위 계약으로 정한다. 로컬 정지, 작업 취소, 현장 비상정지를 같은 상태로 합치지 않는다. timeout/연결 상실 시 응답 없음은 미확인이고 성공이 아니다. 지연 응답으로 취소 후 작업을 재개하지 않는다.

### 베이스에 장착한 팔

Fleet의 사이트 작업 아래 D-55의 로컬 복합 transaction이 필요하다. 베이스는 CORE, 팔은 OMX owner가 최종 명령을 유지한다. 팔 접힘·적재·배치 상태별 실측 footprint, payload, 속도 한계, 3-D scene, 장착/hand-eye 보정과 interlock을 대조한다. 초기 수용 시나리오는 이동 완료·정지 확인 후 팔 작업이다. 동시 이동·팔 동작은 별도 검증 전 제공하지 않는다. 재시작 후 물체 소유·팔 상태가 미확인이면 HOLD하며 자동으로 재파지/재운반하지 않는다.

## 화면 구성 제안

```text
공용 헤더: 현장 / 연결·권한 / 알림·설정 / 비상정지
왼쪽 탐색             중앙 작업 영역                    오른쪽 문맥 패널
  현장 개요             현장 공간 + 전체 작업 현황          선택 대상의 상태·증거
  작업                  목표와 단계·담당 장치·인계          현재 영상 / 판단 당시 영상
  장치                  기능과 실행 가능 상태               AI 판단·CORE/OMX 응답
  작업 공간             공간·프레임·보정·공유 자원          개입과 명령 결과
  알림                  출처와 관련 작업이 연결된 메시지
푸터: 시각·관측 신선도·진단 진입
```

주행 지도와 팔 장면/Recipe 편집은 중앙의 작업별 보기다. 선택하지 않은 장치의 전용 조작은 노출하지 않는다. 작업 상세에는 베이스와 팔의 단계를 함께 보여 주고, 장치 상세에서는 각 장치의 독립 상태를 유지한다. 아이콘은 역할별 접근성 이름·툴팁을 갖는다. 핵심 목표, 상태, 거절/정지 이유에는 짧은 텍스트를 남긴다.

## 단계와 완료 기준

| 단계 | 도달 범위 | 완료 증거 |
|---|---|---|
| 1. 용어·현황 정리 | CONCEPTS/PRODUCT/SRS/현행 API의 의미와 화면 항목 대응을 검토. 지원됨/계획됨 분리 | 같은 장치·공간·공정을 문서와 화면에서 구별할 수 있음. 새 필드 없음. |
| 2. 공통 읽기 화면 | 기존 주행 Task와 Cell Mission을 출처별 ID/상태로 투영. 상세는 기존 API 사용 | 두 원장의 동일 ID 충돌 방지, 상태/시간/권한/신선도 보존, 지원 안 되는 조작 없음. |
| 3. 한 혼합 작업의 실행 계약 | 운반 베이스→고정 팔 인계 1종. API/SRS/schema/migration·자원 예약·취소/재시작 확정 | 단일 목표 이력에서 요청·수락·행동 결과·인계·완료 증거 추적. |
| 4. 혼합 작업 실행 | 단계 3의 확정 계약에 맞춰 기존 task/mission adapter와 장치별 소비자 연결 | 원격 계약 테스트와 ROS-SIM에서 전체 흐름·실패 시나리오 통과. |
| 5. 현장 및 이동식 팔 | 실제 장치 수용 후 복합 로컬 transaction/interlock 별도 확정 | DEVICE/FIELD에서 실측·정지·파지/배치·연결 상실·재시작 확인. |

영향 범위: 용어집/제품 정의, FLEET·CORE SRS 및 OMX 계약, API Reference와 typed schemas, Fleet Task/Mission store/service/dispatcher와 migration, execution/site 및 공정 compiler, CORE/OMX adapter, world 관측, Console 탐색·상세·알림, 권한·fixtures·remote browser 테스트, 설치 wheel/source image 및 배포 문서. 실제 코드 변경은 각 단계에서 필요한 경로로 한정한다.

필수 반례: 중복 submit/result, 이전 attempt의 지연 응답, 관측·보정·map revision 변경, 위치 확인 전 팔 요청, 공유 공간의 예약 경쟁, 취소 중 인계, 한 장치 재시작, 통신 상실, 파지 실패/물건 상태 미확인, 완료 응답은 있으나 독립 목표 증거 없음. 2단계 UI 테스트는 베이스 전용/팔 전용/혼합 현장, operator/viewer, 모바일 및 키보드 탐색을 포함한다.

## 이번 검토의 경계

## 첫 구현 · 공통 읽기 화면

사용자의 2026-10-11 구현 요청에 따라 단계 1–2의 첫 단위를 구현한다. 브랜치는 `feat/mixed-work-read`이며 기존 단계 3–5의 실행/장치 수용은 유지한다. `/console?view=work`에서 기존 네 문서의 탐색을 통해 같은 작업 화면에 들어간다. 중심은 업무별 목록, 오른쪽은 담당 장치·공간·실행 owner·상태·사유·갱신 시각·상세 read 근거다. raw 원장 단어는 tooltip/identity에 보존하고 operator 본문은 한국어 상태를 표시한다. Cell 설정은 팔 공정 설정 링크로 구별한다.

기존 목록 API가 없으므로 작은 bounded `GET /api/fleet/work` projection을 추가한다. typed schema/API Reference/SRS `UI-WORK-001`을 함께 갱신하며 Mission의 principal 범위를 넓히지 않는다. 원장별 제한과 절단 여부·미설정을 표시한다. 로그인 세대 변경·실패 시 이전 목록을 지우며 선택한 작업의 원장 revision이 바뀌면 이전 상세 결과를 재사용하지 않는다.

검증은 Task/Mission ID 충돌·principal 격리·limit/auth·원장 불변 API 시험, 상태 의미 Node 시험, desktop/mobile × viewer/operator Chromium 선택/필터/조회 실패 및 가로 넘침 시험을 포함한다. 검증 전 성공 수나 배포를 기록하지 않는다.

소스와 계약을 비교해 분리된 실행 흐름을 확인했다. 이 문서는 현재 UI를 바꾸거나 기존 SQL 제한을 제거하지 않는다. API 테스트 통과, 두 장치 협업 실행, 실물 로봇암의 안전 수용을 주장하지 않는다. 다음 구현의 우선순위는 공통 읽기 화면과 운반→고정 팔 인계 계약이며 범용 TaskGraph 엔진을 선행 구축하지 않는다.
