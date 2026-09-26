# ROSY Platform Role and Contract Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** ROSY Platform의 한 작업이 사람의 요청부터 장치의 실제 결과까지 단일 미션 원장과 장치별 로컬 제어 경계를 거치도록 계약·실행·증거를 단계별로 연결한다.

**Architecture:** Platform은 전체 제품이며 하나의 공통 실행 프로세스나 호스트가 아니다(D-290/D-296). 공통 계약은 장치 식별·capability·유한한 action 요청·수락·결과·취소·증거의 의미를 버전 관리하고, Pinky CORE와 OMX 로컬 제어기는 각각 자신의 하드웨어·최종 명령·정지를 소유한다. Fleet은 사이트 Mission/Step과 인계의 단일 정본이고, Vision·AI·Data는 관측·후보·Episode를 제공한다. LeRobot은 OMX의 개발/기록 또는 검증된 정책 입력 경로로 이 구조에 참여한다(D-299).

**Tech Stack:** 현행 Python/FastAPI·typed protocol, ROS 2 Jazzy, Pinky CORE, OMX `omx_adapter`와 ROBOTIS `open_manipulator`, Fleet SQLite/REST, 선택적 LeRobot 오프라인 데이터 형식. 배포 단위는 Pinky Pi, 사이트 호스트, OMX 작업대 인스턴스의 실제 역할에 따라 따로 검증한다.

**상태:** 플랫폼 부모 계획. [OMX/LeRobot 제어 경계 실행 계획](2026-09-27-omx-lerobot-control-boundary-implementation-plan.md)은 장치·데이터 하위 트랙이다. D-281/D-282/D-299의 제안과 D-71의 미래 AI/Data 기능을 이 계획만으로 운영 승인하지 않는다.

---

## 먼저 고정할 책임 경계

| 플랫폼 역할 | 현재 정본/후보 | 소유하는 것 | 넘겨주지 않는 것 |
|---|---|---|---|
| 공통 계약·Fabric | API Reference, `core_common.protocol.schemas`, 역할별 REST/WSS | identity, capability, 요청/수락/결과/증거의 버전된 의미 | 단일 중앙 버스, 장치 최종 명령 |
| 사이트 미션·운영 | `src/site/fleet` | Mission/Step 원장, 우선순위, 인계, UNKNOWN 조정 | 장치의 실제 상태·정지 판정·trajectory |
| Pinky 장치 미들웨어 | CORE와 Pinky 장치 코드 | 로컬 요청 수용, 주행 상태, 최종 `cmd_vel`, 로컬 정지 | 사이트 미션 원장 |
| OMX 장치 미들웨어 | 현재 비활성 `omx_adapter`; 운영 제어기는 후속 | 작업대별 팔 action 검증, 최종 trajectory, 정지·복구 | Pinky 주행 명령, Fleet 미션 원장 |
| 관측·AI·Data | 현재 `site/overhead`; AI/Data 운영 경로는 미래 | 출처 있는 관측, 정책 후보, Episode/모델 provenance | 장치 직접 제어와 별도 미션 실행기 |
| 사람의 화면 | CORE dashboard, Fleet console | 요청·수락·실제 결과·불명 상태 표시 | 화면 응답을 물리 완료로 해석 |

`ROSY Operations`는 운영 경험의 목표 이름이며 Fleet과 병행하는 두 번째 미션 DB가 아니다. `ROSY Fabric`은 역할별 계약의 이름이며 하나의 ROS graph나 중앙 브로커를 추가하는 지시가 아니다(D-290). 현재 `src/contracts/foundation/core_common/`은 Pinky 중심 구현이므로 OMX가 이를 통째로 의존하도록 만들지 않는다. 두 장치가 실제로 공유할 의미를 승인할 때 API Reference와 typed schema를 함께 바꾸고(D-18), 작은 계약 패키지의 필요성은 구현·검증으로 판단한다(D-296).

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
│  │  │  ├─ core_common/         # 현재 Pinky 중심 domain/protocol
│  │  │  └─ [device_contracts/]  # 제안: 첫 공통 의미가 검증될 때만 추가
│  │  └─ interfaces/             # 현재 장치 내부 ROS .srv
│  ├─ runtime/                   # 현재 Pinky CORE·API·navigation 등 소스 분류
│  ├─ devices/
│  │  ├─ pinky_pro/               # Pinky 하드웨어 적응
│  │  └─ omx/adapter/             # OMX 로컬 action owner 후보·카메라 계약
│  ├─ products/{pinky_pro,omx}/   # 제품별 설정; OMX 비활성 유지
│  ├─ site/
│  │  ├─ fleet/                   # 사이트 미션 원장; 이종 Mission은 후속
│  │  └─ overhead/                # 현행 사이트 관측
│  ├─ hmi/                       # 장치 dashboard와 공용 웹 자산
│  ├─ [ai/]                      # 목표 역할; 모델/정책 계약 승인 뒤 위치 확정
│  └─ [data/]                    # 목표 역할; Episode/보존 계약 승인 뒤 위치 확정
├─ deploy/{robot,site,omx}/      # 현재 역할별 배포 경로
│  └─ omx/{native,lerobot}/       # 제안: 운영 후보/독립 실험 분리
├─ tools/omx/                    # 제안: 오프라인 데이터 검증, 후순위
└─ docs/{adr,plans,reference,validation}/
```

대괄호 항목과 `deploy/omx/{native,lerobot}`, `tools/omx/`는 **미생성 목표 경로**다. 기존 `runtime/`, `devices/`, `site/`를 새 `platform/` 폴더 하나로 옮기는 마이그레이션은 계획하지 않는다. `ROSY Platform`은 이 역할들이 계약으로 이루는 제품 이름이며, 폴더명이나 단일 설치 패키지 이름이 아니다. `src/contracts/interfaces/`의 ROS `.srv`는 곧바로 사이트 REST 계약 저장소가 되지 않는다.

## 순서와 검증 게이트

| 단계 | 먼저 완성할 것 | 관련 소스·문서 | 출구 증거 |
|---|---|---|---|
| P0 현재 계약 기준선 | Pinky/Fleet의 요청·ACK·실제 결과·UNKNOWN 의미, identity와 capability를 API·코드·화면에서 대조 | `src/site/fleet`, `src/runtime`, API Reference, D-297/D-298 | 현행 한 이동 작업이 수락·최종 결과·정지 증거를 혼동하지 않음 |
| P1 플랫폼 공통 의미 | 첫 Pinky/OMX Device Action의 공통 필드와 각 장치별 payload·오류 범위 설계; 구현 전 두 장치의 실제 필요 확인 | `src/contracts/foundation`, API Reference, 별도 계약 결정 | 요청 ID·만료·중복·취소·상태·결과·증거의 버전과 호환 시험; 실행 코드는 로컬 유지 |
| P2 OMX 장치 수용 | native owner·정지·LeRobot 모드 배타성과 실물 readback | [OMX 하위 계획](2026-09-27-omx-lerobot-control-boundary-implementation-plan.md), `src/devices/omx`, `deploy/omx` | ROS-SIM→ARTIFACT→DEVICE의 독립 결과; 비활성 capability 유지 until 수용 |
| P3 한 종류의 이종 미션 | Fleet Mission/Step 원장과 Pinky↔고정 OMX 인계 | `src/site/fleet`, 장치 API, D-12/D-290 | ID 연결, 인증, 멱등성, 취소, UNKNOWN 재조회, 두 장치의 실제 결과를 FIELD에서 확인 |
| P4 관측·학습 | 승인된 Episode·데이터셋·정책 후보의 별도 수명 | `src/site/overhead`, 미래 Data/AI, OMX LeRobot 변환 | timestamp/frame/calibration/model/원본 해시와 결과 대조; 규칙 기반 기준선 대비 평가 |
| P5 배치 확장 | 한 사이트에서 장치·Fleet·관측·계산 역할의 패키징과 복구 | `deploy/robot`, `deploy/site`, `deploy/omx` | 각 호스트의 실행 provenance, 독립 정지, 백업·복구, 자원 경합 및 현장 수용 |

P0은 기존 [플랫폼 구조 간극 지도](2026-09-26-platform-structure-gap-map.md)와 현재 Fleet·CORE 작업을 재사용한다. P1에서 공통 실행 라이브러리를 먼저 추출하지 않는다. P2의 LeRobot은 플랫폼 Data/AI 경로에 자료를 줄 수 있지만, P3의 Fleet action이나 장치 최종 명령권을 대신하지 않는다. P4의 Data/AI와 P5의 GPU 확대는 실제 작업·데이터·지연 요구가 확인될 때만 구현 범위를 정한다.

## 첫 실행 단위

1. **P0 추적표 작성:** 현행 `/api/fleet/tasks/*`, Pinky CORE 요청/결과, D-297 ACK, D-298 정지 증거를 한 이동 작업으로 연결한다. 파일: `docs/reference/ROSY API & Protocol Reference.md`, 관련 Fleet/CORE 테스트. 먼저 누락/상충 의미를 재현하는 테스트를 작성하고, 문서와 구현을 함께 맞춘다.
2. **P1 계약 설계:** 한 Pinky 이동과 한 OMX 고정 작업을 비교해 공통 identity·action·status·result 필드와 장치별 payload를 나눈다. API Reference·typed schema를 함께 변경해야 하는 실제 필드가 확정될 때만 코드 패키지를 만들고 버전·호환 시험을 추가한다. OMX 원격 API는 D-282의 DEVICE 게이트 전에는 공개하지 않는다.
3. **P2 OMX 하위 계획 실행:** 실물 inventory, 단일 owner/모드, native ROS, LeRobot bench, 데이터 매핑 순으로 진행한다. 중복 포트·stale state·취소/정지 미확인 시 신규 명령을 차단한다.
4. **P3 최초 이종 미션 설계:** 기존 Fleet을 단일 원장으로 확장하는 안을 우선 검증한다. 별도 Operations 원장이 필요하다는 증거가 나오면 D-12/D-290을 다루는 새 결정과 단일 이행 계획을 먼저 만든다.

**검증:** 문서 변경은 `python tools/harness/rosy_harness.py generate`, `python tools/harness/rosy_harness.py lint`, `python -m pytest test/test_network_topology_contracts.py test/test_harness_contracts.py -q`. 각 구현은 영향을 받는 Fleet/CORE/OMX 테스트를 선행하고 SOURCE/LOCAL, ROS-SIM, ARTIFACT, DEVICE, FIELD를 별도 기록한다. 실패 시 해당 capability·프로필을 비활성으로 두고 마지막 승인된 단일 owner와 계약으로 되돌린다.

**근거:** [D-290](../adr/D-290-rosy-platform-naming-and-site-intent-boundaries.md), [D-296](../adr/D-296-device-middleware-and-site-orchestration-terminology.md), [D-298](../adr/D-298-mission-action-and-stop-evidence-terminology.md), [D-299](../adr/D-299-omx-lerobot-development-and-command-ownership.md), [구조 간극 지도](2026-09-26-platform-structure-gap-map.md), [제품 정의](../architecture/00_ROSY_OS_Vision_and_Definition.md).
