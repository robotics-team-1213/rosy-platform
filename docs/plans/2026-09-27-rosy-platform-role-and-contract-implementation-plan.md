# ROSY Platform Role and Contract Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** ROSY Platform의 한 작업이 사람의 요청부터 장치의 실제 결과까지 단일 미션 원장과 장치별 로컬 제어 경계를 거치도록 계약·실행·증거를 단계별로 연결한다.

**Architecture:** Platform은 전체 제품이며 하나의 공통 실행 프로세스나 호스트가 아니다(D-290/D-296). 공통 계약은 장치 식별·capability·유한한 action 요청·수락·결과·취소·증거의 의미를 버전 관리하고, Pinky CORE와 OMX 로컬 제어기는 각각 자신의 하드웨어·최종 명령·정지를 소유한다. Fleet은 사이트 Mission/Step과 인계의 단일 정본이고, Vision·AI·Data는 관측·후보·Episode를 제공한다. LeRobot은 OMX의 개발/기록 또는 검증된 정책 입력 경로로 이 구조에 참여한다(D-299).

**Tech Stack:** 현행 Python/FastAPI·typed protocol, ROS 2 Jazzy, Pinky CORE, OMX `omx_adapter`와 ROBOTIS `open_manipulator`, Fleet SQLite/REST, 선택적 LeRobot 오프라인 데이터 형식. 배포 단위는 Pinky Pi, 사이트 호스트, OMX 작업대 인스턴스의 실제 역할에 따라 따로 검증한다.

**상태:** 플랫폼 부모 계획. [OMX/LeRobot 제어 경계 실행 계획](2026-09-27-omx-lerobot-control-boundary-implementation-plan.md)은 장치·데이터 하위 트랙이다. D-281/D-282/D-299의 제안과 D-71의 미래 AI/Data 기능을 이 계획만으로 운영 승인하지 않는다.

---

## 경계 판정 기준 (각 변경마다 같은 순서로 적용)

| 순서 | 판정 질문 | 소유자·진입 조건 |
|---|---|---|
| 1. 물리 권한 | 최종 actuator 명령·정지·재개를 누가 실제로 검증하는가? | 해당 **장치 로컬 제어기**. 독립 정지 수단, 신선한 하드웨어 readback, 단일 writer와 fault/recovery 증거가 없으면 capability를 열지 않는다. |
| 2. 작업 정본 | 장치 간 순서·인계·우선순위·결과 불명을 누가 복구하는가? | **Fleet 한 원장**. 장치의 실제 상태·정지 판정은 가져오지 않는다. |
| 3. 공통 의미 | 독립된 두 소유자가 같은 의미를 실제로 교환하며 버전·호환 시험이 필요한가? | 그 의미만 **공통 계약 후보**. API Reference에 출처·상태·증거를 구분한다. OMX의 예상 작업만으로 공개 schema를 고정하지 않는다. |
| 4. 증거 승격 | 카메라·AI·LeRobot 출력이 관측인가, 검증된 Device Action인가? | 검증 전에는 provenance 있는 **관측·제안·데이터**. Fleet 정책 검증과 장치 로컬 수용을 통과해야 동작 요청이 된다. |
| 5. 폴더·배포 | 실제 코드·독립 수명·소유자가 있고 기존 Accepted ADR의 위치 규칙에 맞는가? | 그때만 폴더/서비스를 만든다. 호스트 공유나 제품 이름만으로 권한·프로세스·패키지를 합치지 않는다. 위치 규칙 변경은 새 ADR에서 명시적으로 대체한다. |

**동률 판정:** 물리 owner 단일성 → Fleet 미션 원장 단일성 → 기존 API 호환 → 더 작은 독립 검증 단위 순으로 고른다. `SOURCE/LOCAL`, `ROS-SIM`, `ARTIFACT`, `DEVICE`, `FIELD` 중 실제로 확보한 증거만 기록한다. 단계명·HTTP 수락·action cancel·software HOLD는 물리 정지의 대체 증거가 아니다(D-298). 공통 **실행 코드**는 같은 규칙이 두 장치에서 구현·시험돼 중복이 확인된 뒤 별도로 추출한다(D-296). D-18의 세 번째 실제 소비자는 계약 패키지 분리의 **재검토 조건**이며 자동 분리 지시가 아니다.

**판정 기록 형식:** 새 경계마다 `사용 사례 → 최종 명령/정지 owner → 미션·상태 정본 → 교환되는 최소 정보와 버전 → 단절/재시작 결과 → 현재 증거 수준 → 기존 ADR과의 관계 → 다음 반례 시험`을 한 표에 적는다. 항목을 채우지 못하면 목표 구조는 후보로 남기고 폴더·공개 API·capability를 먼저 만들지 않는다.

| 반례 사례 | 이 기준으로 정한 경계 | 아직 결정하지 않는 것 |
|---|---|---|
| Pinky 이동 | Fleet은 순서·요청 원장, CORE는 최종 `cmd_vel`·장치 상태 | 수락 receipt를 물리 도착으로 간주하지 않음 |
| 고정 OMX 집기 | Fleet은 인계, OMX 로컬 owner는 trajectory·관절/그리퍼 readback·정지 | 실물 API·운영 capability는 DEVICE 전 미승인 |
| Pinky 탑재 OMX | base와 arm은 각 최종 writer를 유지; 로컬 상호 인터록 필수 | 별도 조정기와 두 제어기의 교차 게이트 중 구현 주체는 미결정 |
| Native LeRobot | 직접 시리얼 사용 중에는 OMX-F의 유일한 실험 owner | 브랜드만으로 운영 적격·부적격 판정하지 않음 |
| 학습 정책·카메라 | 출처·시간·보정이 있는 관측/제안 | 장치 action이나 Fleet 미션의 새 owner가 되지 않음 |

## 먼저 고정할 책임 경계

| 플랫폼 역할 | 현재 정본/후보 | 소유하는 것 | 넘겨주지 않는 것 |
|---|---|---|---|
| 공통 계약·Fabric | API Reference, 현행 Pinky 중심 `core_common.protocol.schemas`, 역할별 REST/WSS | 실제 교환되는 identity·요청·결과·증거의 버전된 의미 | 단일 중앙 버스, 범용 상태 enum, 장치 최종 명령 |
| 사이트 미션·운영 | `src/site/fleet` | Mission/Step 원장, 우선순위, 인계, UNKNOWN 조정 | 장치의 실제 상태·정지 판정·trajectory |
| Pinky 장치 미들웨어 | CORE와 Pinky 장치 코드 | 로컬 요청 수용, 주행 상태, 최종 `cmd_vel`, 로컬 정지 | 사이트 미션 원장 |
| OMX 장치 미들웨어 | 현재 비활성 `omx_adapter`; 운영 제어기는 후속 | 작업대별 팔 action 검증, 최종 trajectory, 정지·복구 | Pinky 주행 명령, Fleet 미션 원장 |
| 관측·AI·Data | 현재 `site/overhead`; AI/Data 운영 경로는 미래 | 출처 있는 관측, 정책 후보, Episode/모델 provenance | 장치 직접 제어와 별도 미션 실행기 |
| 사람의 화면 | CORE dashboard, Fleet console | 요청·수락·실제 결과·불명 상태 표시 | 화면 응답을 물리 완료로 해석 |

`ROSY Operations`는 운영 경험의 목표 이름이며 Fleet과 병행하는 두 번째 미션 DB가 아니다. `ROSY Fabric`은 역할별 계약의 이름이며 하나의 ROS graph나 중앙 브로커를 추가하는 지시가 아니다(D-290). 현재 `src/contracts/foundation/core_common/`은 Pinky 중심 구현이고 Fleet이 재사용한다(D-18). OMX가 이를 통째로 의존하도록 만들지 않는다. 실제 OMX 소비자와 작업·결과 표본이 확인되면 API Reference와 typed schema의 공통 의미를 검토한다. 별도 계약 패키지는 D-18의 세 번째 소비자 조건, 의존·배포 비용과 호환 시험을 함께 보고 결정한다.

## 플랫폼의 한 작업 경로

```text
사람·Console → Intent 후보 → Fleet Mission / Mission Step
                            │  권한·대상·capability·중복·만료·순서
                            ├── Device Action → Pinky CORE → 최종 cmd_vel
                            └── Device Action → OMX 로컬 제어기 → 최종 arm trajectory
                                   ↑ 정책/teleop 제안, 검증 후에만 수용

장치 readback / 결과 증거 → Fleet 단일 미션 원장 → Console
허용된 관측·명령·결과 ─────────────────────────→ Episode / Data / AI 평가
```

장치 action의 HTTP/ROS 수락, 결과 완료, 속도 0 또는 팔 정지 readback, 물리 정지는 서로 다른 증거다(D-298). 연결 상실이나 재시작 뒤 UNKNOWN을 성공으로 만들거나 이전 명령을 재생하지 않는다. LeRobot의 직접 OMX 시리얼 제어는 운영 ROS owner가 종료된 독립 실험 모드에만 둔다. LeRobot 정책은 나중에 장치 제어기의 제한된 입력 후보가 될 수 있다.

## 현재 소스 폴더와 목표 배치

```text
Rosy OS/                         # 저장소 이력 이름; 전체 제품은 ROSY Platform
├─ src/
│  ├─ contracts/
│  │  ├─ foundation/
│  │  │  └─ core_common/         # 현재 Pinky 중심 domain/protocol
│  │  └─ interfaces/             # 현재 장치 내부 ROS .srv
│  ├─ runtime/                   # 현재 Pinky CORE·API·navigation 등 소스 분류
│  ├─ devices/
│  │  ├─ pinky_pro/               # Pinky 하드웨어 적응
│  │  └─ omx/adapter/             # OMX 로컬 action owner 후보·카메라 계약
│  ├─ products/{pinky_pro,omx}/   # 제품별 설정; OMX 비활성 유지
│  ├─ site/
│  │  ├─ fleet/                   # 사이트 미션 원장; 이종 Mission은 후속
│  │  └─ overhead/                # 현행 사이트 관측
│  └─ hmi/                       # 장치 dashboard와 공용 웹 자산
├─ deploy/{robot,site,omx}/      # 현재 역할별 배포 경로
├─ tools/perception/             # 현재 재생·라벨 도구; OMX 변환 후보는 실제 코드 때
├─ data/{teleop,drive}/          # 현재 자료 경로; Episode 형식은 별도 결정
└─ docs/{adr,plans,reference,validation}/
```

이 그림은 **현재 존재하는 역할 경로**만 보인다. `deploy/omx/native/`, `deploy/omx/lerobot/`, `tools/perception/omx/`, `services/ai_worker/`는 해당 실행 코드가 필요한 커밋에서만 만든다. `data/episodes`·`data/datasets`는 Episode 형식의 별도 결정 전에는 예약하지 않는다(D-231). 새 공통 계약 패키지도 실제 세 번째 소비자와 중복 의미·호환 시험을 확인하기 전에는 이름·위치를 고정하지 않는다(D-18). `ROSY Platform`은 역할들이 계약으로 이루는 제품 이름이며, 단일 `platform/` 폴더·프로세스·설치 패키지 이름이 아니다. `src/contracts/interfaces/`의 ROS `.srv`는 사이트 REST 계약 저장소가 아니다.

## 순서와 검증 게이트

| 단계 | 먼저 완성할 것 | 관련 소스·문서 | 출구 증거 |
|---|---|---|---|
| P0 현행 경로 감사 | Pinky/Fleet의 요청·장치 수락·Fleet 상태·실제 결과·정지 증거를 출처별로 대조하고 첫 이종 작업의 물리 결과를 지정 | `src/site/fleet`, `src/runtime`, API Reference, D-297/D-298 | 현재 `task_service.py`는 수락 receipt를 기록한다는 사실과 최종 결과 상관관계의 간극이 명시됨; 공통 필드는 비규범적 비교표로만 표시 |
| P1 OMX 로컬 경계 수용 | 작업대 identity·단일 writer·원본 관절 샘플 시각·취소 후 실제 상태·독립 정지·복구 계측 | [OMX 하위 계획](2026-09-27-omx-lerobot-control-boundary-implementation-plan.md), `src/devices/omx`, `deploy/omx` | ROS-SIM/ARTIFACT와 실제 DEVICE 결과를 분리 기록; 승인 전 `omx.enabled: false` 유지 |
| P2 공통 계약 심사 | P0 Pinky trace와 P1 OMX action/결과 표본에서 **동일한 의미**만 추출 | API Reference, 현행 typed schema, D-18/D-296 | 버전·호환·반례 시험을 갖춘 최소 공통 의미와 장치별 payload 결정; 3번째 실제 소비자가 있을 때 패키지 분리 재검토 |
| P3 한 종류의 이종 미션 | Fleet Mission/Step 원장과 Pinky↔고정 OMX 인계 | `src/site/fleet`, 승인된 OMX 장치 API, D-12/D-290 | ID 연결, 인증, 멱등성, 취소, UNKNOWN 재조회, 두 장치의 실제 결과를 FIELD에서 확인 |
| P4 관측·학습 (선택) | 승인된 Episode·데이터셋·정책 후보의 별도 수명 | `src/site/overhead`, D-231이 정한 서비스/도구 경로, OMX LeRobot 자료 | timestamp/frame/calibration/model/원본 해시와 결과 대조; 규칙 기반 기준선 대비 평가 |
| P5 배치 확장 | 한 사이트에서 장치·Fleet·관측·계산 역할의 패키징과 복구 | `deploy/robot`, `deploy/site`, `deploy/omx` | 각 호스트의 실행 provenance, 독립 정지, 백업·복구, 자원 경합 및 현장 수용 |

P0은 기존 [플랫폼 구조 간극 지도](2026-09-26-platform-structure-gap-map.md)와 현재 Fleet·CORE 작업을 재사용한다. P2에서 공통 실행 라이브러리를 추출하지 않는다. **LeRobot bench·데이터 변환은 P3의 선행조건이 아니다.** 같은 OMX 시리얼 장치에 LeRobot을 설치·사용할 때만 ROS↔LeRobot 배타적 모드 전환이 P1 DEVICE 조건에 들어간다. Native LeRobot을 장래 운영 후보로 평가할 경우 ROS 후보와 같은 단일 writer·정지/readback·fault/recovery·DEVICE/FIELD 기준을 적용하며 D-299의 Proposed 선택을 다시 판단한다. P4의 Data/AI와 P5의 GPU 확대는 실제 작업·데이터·지연 요구가 확인될 때만 범위를 정한다.

**Pinky 탑재 OMX 별도 판정:** 고정 작업대 인계와 물리적으로 다른 사례다. base와 arm의 최종 writer는 각각 유지한다. 팔 전개 중 주행, 주행 중 팔 동작, 한쪽 상태 stale·정지 실패를 막는 **로컬 상호 인터록과 복구 순서**가 필요하며, 이를 별도 조정기와 두 로컬 제어기의 교차 게이트 중 누가 구현할지는 실물 시험 전 미결정으로 둔다. 그 전에는 동시 동작을 열지 않는다(D-55/D-296). Fleet의 사이트 순서만으로 복합 장치의 로컬 안전을 증명하지 않는다.

**탑재형·드론 독립 반례:** [반례 검증표](../validation/2026-09-27-platform-mounted-interlock-and-drone-counterexamples.md)에 이전 허가/세션 재사용, ROS 수신 시각과 하드웨어 원본 샘플의 차이, 미확인 적재물의 footprint·속도 한계, 취소 ACK 뒤 관성·driver readback, 선택된 드론 스택의 실제 최종 actuator authority를 기록한다. 이 표의 탑재형 게이트는 위 P3 고정 작업대 인계와 별개이며 드론 게이트와도 서로 선행조건이 아니다. 모두 실물 검증 전 운영 HOLD다.

## 첫 실행 단위

**P0 결과 (2026-09-27):** [한 Pinky 이동 작업의 요청·수락·결과·정지 증거 추적](../validation/2026-09-27-platform-p0-task-result-trace.md). Fleet 수락과 CORE 이벤트 사이에 `task_id`/명령 ID 연결이 없음을 확인했다. 이 표본은 공통 장치 계약의 승인 근거가 아니며 P1/P2는 각각의 게이트를 유지한다.

**P1 소스 판정 (2026-09-27):** [OMX 로컬 제어 경계 점검](../validation/2026-09-27-platform-p1-omx-source-gate.md). 정적 inventory·owner 검증은 통과했지만 실제 장치 identity, 원본 joint 샘플, 독립 정지와 Ubuntu 실행 owner는 미측정이다. DEVICE 게이트와 `omx.enabled: false`를 유지한다.

1. **P0 추적표 작성:** 현행 `/api/fleet/tasks/*`, Pinky CORE 수락, Fleet 상태, 장치 최종 이벤트/실물 readback의 유무, D-298 정지 증거를 한 이동 작업으로 연결한다. 파일: `docs/reference/ROSY API & Protocol Reference.md`, 관련 Fleet/CORE 테스트. `proven(Pinky) / candidate(OMX) / open`과 반례를 표시하고, 미구현 상관관계를 완료로 쓰지 않는다.
2. **P1 OMX 하위 계획 실행:** 실물 inventory, 단일 owner, native ROS와 실제 관절/정지 readback을 먼저 확인한다. 같은 장치에서 LeRobot을 쓰는 경우에는 배타적 모드 전환을 추가 검증한다. LeRobot 기록·데이터 매핑은 이종 미션과 독립적으로 진행한다.
3. **P2 최소 계약 심사:** 한 Pinky 이동과 실제 OMX 고정 작업 표본을 비교해 공유할 identity·action·결과 의미와 각 장치 고유 payload를 나눈다. Fleet 상태 enum과 장치 ACK/실행 결과를 합치지 않는다. API Reference·typed schema 변경은 실제 소비자·버전·호환 시험이 갖춰질 때 수행하며, D-18에 따른 패키지 분리는 별도로 재검토한다.
4. **P3 최초 이종 미션 설계:** 기존 Fleet을 단일 원장으로 확장하는 안을 우선 검증한다. 별도 Operations 원장이 필요하다는 증거가 나오면 D-12/D-290을 다루는 새 결정과 단일 이행 계획을 먼저 만든다.

**검증:** 문서 변경은 `python tools/harness/rosy_harness.py generate`, `python tools/harness/rosy_harness.py lint`, `python -m pytest test/test_network_topology_contracts.py test/test_harness_contracts.py -q`. 각 구현은 영향을 받는 Fleet/CORE/OMX 테스트를 선행하고 SOURCE/LOCAL, ROS-SIM, ARTIFACT, DEVICE, FIELD를 별도 기록한다. 실패 시 해당 capability·프로필을 비활성으로 두고 마지막 승인된 단일 owner와 계약으로 되돌린다.

**근거:** [D-290](../adr/D-290-rosy-platform-naming-and-site-intent-boundaries.md), [D-296](../adr/D-296-device-middleware-and-site-orchestration-terminology.md), [D-298](../adr/D-298-mission-action-and-stop-evidence-terminology.md), [D-299](../adr/D-299-omx-lerobot-development-and-command-ownership.md), [구조 간극 지도](2026-09-26-platform-structure-gap-map.md), [제품 정의](../architecture/00_ROSY_OS_Vision_and_Definition.md).
