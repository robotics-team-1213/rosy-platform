# ROSY Platform 남은 구조 간극 지도

작성일: 2026-09-26
상태: 현행 소스/결정과 목표 문서의 대조. 새 기능·API·장치 가동 승인이 아니다.

## 판단

지금 필요한 것은 `Control Plane`, `Fabric`, `AI Runtime`을 한꺼번에 서비스로 만드는 일이 아니다. **하나의 작업이 사람의 요청에서 장치의 실제 결과까지 어떤 소유자를 거치는지** 먼저 고정해야 한다. 그 축은 `Console 입력 → Fleet의 단일 작업 원장/판정 → 장치별 수용된 API → 로컬 안전·실행 → 결과 readback`이다. Vision/AI는 이 축에 근거를 제공하고, Data는 승인된 자료를 나중에 Episode로 묶는다. 호스트 수가 달라도 각 단계의 권한은 변하지 않는다([D-290](../adr/D-290-rosy-platform-naming-and-site-intent-boundaries.md), [배치 토폴로지](2026-09-26-site-role-deployment-topology-design.md)).

| 영역 | 현재 확인한 범위 | 목표와의 간극 | 다음에 고정할 계약 |
|---|---|---|---|
| Console/대화 | 사이트 Fleet `/console`과 로봇 CORE 화면은 서로 다른 origin; 사이트 API는 principal별 권한이 있다 | 채팅·음성 해석과 사용자 확인 흐름 없음 | 자유 문장→구조화된 **후보**; 사용자/역할 확인 후 기존 작업 검증기로 제출. 모델 응답을 명령 수락/완료로 표시하지 않음 |
| Fleet/Operations | Fleet SQLite에 로봇별 이동 작업, 큐·멱등성·감사·`UNKNOWN`; CORE REST 실행. RabbitMQ 필요성 미확인 | 다장치 Mission/Step 원장과 최종 결과 상관관계 없음 | 현행 Fleet을 미션 정본으로 확장할지, 장래 Operations로 **단일 이행**할지 첫 이종 미션 전에 결정. Mission/Step/Action ID·상태·취소·결과 증거를 D-18 사이클에서 고정 |
| Fabric | CORE REST/WSS, Agent 이벤트, 폰 WSS, Vision sighting HTTPS 등 역할별 계약 | 범용 노드 버스·공통 DDS·OMX 원격 계약은 없음 | 계약별 identity/권한/방향/버전/만료/재시도 의미. 로봇 DDS는 장치 안에 유지; Fabric 자체의 중앙 서버는 만들지 않음 |
| Vision | 사이트 `overhead`가 최신 JPEG→CPU ArUco→표시용 sighting; 합성 Docker LOCAL | 복수 카메라 융합, GPU 추론, 정책 적격 증거의 FIELD 수용 없음 | raw frame 경로와 파생 evidence를 분리. source·시계·frame/map·보정·모델 revision을 검증; D-268 전에는 자동 작업 입력 HOLD |
| Pinky | Pi CORE가 로컬 최종 `cmd_vel`과 안전을 소유 | 사이트와의 실물 readback·중앙 미션 최종 결과 연결은 별도 | CORE의 접수/완료와 Fleet 원장의 상태를 구분. 링크 상실 시 로컬 안전 유지 |
| 고정 OMX 1~2대 | 작업대별 inventory·중복 장치 거부, vendor ROS-SIM owner 정책; `omx.enabled: false` | native 단일 writer, DDS 우회 차단, 독립 물리 정지와 원격 작업 API 없음 | 작업대별 identity·capability·허용 작업·취소·최종 readback을 DEVICE 수용 후 계약화; 장비마다 로컬 owner 하나 |
| 이동 조작 합성 장비 | D-55의 로컬 manipulation 목표; v1 Asset은 단일 Device | Pinky에 OMX를 장착한 실물 제품·전원·충돌·hand-eye·payload 근거 없음 | 고정 OMX 작업대와 별도 제품 경로로 다룸. 로컬 조작 거래가 안전/결과를 소유하고 Fleet은 상위 순서만 소유 |
| Data/AI/VLA/월드 모델 | 목표 문서 11/12의 개념과 제한된 teleop 자료; 운영 registry/episode pipeline 없음 | 입력·행동·결과의 재현 가능한 Episode, 모델 평가/승격, 계산 자원 경계 없음 | 수집 허가·출처·시간·calibration·task/action/result 결합 → 평가 → 고정 모델 산출물 → 제한된 추론. 출력은 제안/관측으로 시작 |

## 구조적으로 먼저 풀어야 할 세 가지

1. **작업 단위의 이름과 상태 정본.** `CONCEPTS.md`의 `TaskKind`는 로봇 원자 액션이다. 목표 문서 08의 `Transport`는 여러 단계인 Mission/Workflow 예시다. 현재 Fleet 이동 작업의 `REQUESTED/QUEUED/ACCEPTED/UNKNOWN`을 목표 문서의 `PENDING/ASSIGNED/RUNNING/SUCCEEDED`로 치환하지 않는다. 첫 이종 미션 때 입력 후보, Mission, Step, Device Action, Episode의 ID와 결과 관계를 한 번에 정의한다. D-170/D-177의 유예된 `correlation_id`를 단독으로 조기 도입하지 않는다.
2. **증거와 명령 사이의 승격 경계.** 천장 sighting, 향후 다중 카메라 추론, VLA 계획, 월드 모델 예측은 서로 다른 신뢰도를 가진다. 모두 원본 출처·시각·좌표계·보정/모델 revision을 보존한다. Fleet이 자동 작업에 사용할 수 있는 것은 별도 수용된 정책 증거뿐이며, 작업 적격성 검증과 로컬 안전이 뒤따른다. 합성 화면에서 보였다는 사실은 정책 승인이나 실제 로봇 위치 증명이 아니다.
3. **물리 결합과 논리 배치를 구별.** 고정 OMX 두 대가 사이트 PC에 연결되는 구조와 Pinky 위에 OMX를 단 이동 조작 장비는 장치·정지·전원·좌표계가 다르다. 전자는 D-281/D-282의 작업대 호스트 배치 문제, 후자는 D-55/D-71의 새 제품 수용 문제다. 한 YAML `profile`이나 한 ROS graph로 합치지 않는다.

## 권장 순서와 중단 조건

| 순서 | 필요한 결과 | 다음 단계로 넘어가는 조건 |
|---|---|---|
| 1. 현재 경로의 의미 고정 | Fleet 이동 작업 원장, sighting 표시, CORE 수락/최종 결과의 사실과 미구현 경계를 문서·UI에서 일치 | SOURCE/LOCAL과 실제 Ubuntu/CORE readback을 별개로 기록. `src/site/fleet/progress.md`의 오래된 sighting 미연결 서술은 최신 코드와 재대조 |
| 2. OMX 로컬 owner 수용 | 한 작업대의 단일 writer·DDS 직접 action 우회 차단·장치 정지/복구 | ROS-SIM 후 ARTIFACT/DEVICE. `omx.enabled: false`를 실물 수용 전 유지 |
| 3. 한 종류의 이종 작업만 | Fleet의 단일 Mission/Step 원장과 하나의 Pinky+고정 OMX handoff | 첫 시나리오의 장치 계약·인증·멱등성·`UNKNOWN` reconciliation·취소/정지·현장 결과가 사전 정의됨. 범용 DSL과 브로커는 필요가 측정될 때 |
| 4. 정책 증거와 AI | 별도 evidence 계약, 데이터 수집/모델 평가, 제한된 추론 | D-268과 작업별 신선도/오탐 FIELD 통과 전 자동 실행 금지. Episode와 학습 서비스는 D-71 후속 결정으로 분리 |
| 5. 배치 확대 | GPU PC, OMX별 PC 또는 독립 worker | 실제 USB·GPU·지연·장애 요구가 확인될 때만 호스트 이동. DB 공유 마운트나 원격 DDS로 우회하지 않음 |

**우선 권장:** 다음 구현 단위는 범용 `ROSY Runtime`/Fabric 구축이 아니라, 현재 이동 작업의 상태와 실제 완료를 구분하는 계약·readback을 닫는 것이다. 그 뒤 OMX 로컬 안전 경계를 통과시키고, 한 종류의 handoff만 이종 미션으로 올린다. 첫 이종 미션은 Fleet 원장을 확장하는 안을 권장한다. 기존 큐·멱등성·감사·`UNKNOWN` 처리를 한 정본에서 이어갈 수 있기 때문이다. `ROSY Operations`는 우선 화면/운영 역할 이름으로 두고, 별도 서버가 실제로 필요해지면 D-12/D-290을 다루는 ADR과 단일 원장 이행 계획을 먼저 만든다. Chat/VLA·Data는 그 경로에 의도와 근거를 추가하되 두 번째 명령/미션 소유자가 되지 않는다.

## 근거와 제한

- 현행 [Fleet task service](../../src/site/fleet/fleet/server/task_service.py)는 이동 요청·idempotency·큐·`UNKNOWN`을 구현하지만 이종 Mission/최종 결과 상관관계까지 구현하지 않는다. [사이트 Compose](../../deploy/site/compose.yaml)는 Fleet·Vision·Caddy를 배치하고, [OMX Compose](../../deploy/omx/compose.yaml)는 개발/시뮬레이션 프로필이다.
- [D-59](../adr/D-59-.md)/[D-269](../adr/D-269-device-server-contracts-and-ros-boundary.md)는 장치별 REST/WSS와 로컬 DDS를 분리한다. [D-65](../adr/D-65-core-d-62.md)/[D-71](../adr/D-71-concept-05-09-12-15-apt-v1.md)은 범용 Runtime/Compute/VLA/Episode/합성 Asset을 v1 구현으로 읽지 않도록 정한다.
- 목표 문서 01/08/09/11/12는 미래 기능을 설명한다. 이번 대조는 그 기능을 삭제하거나 현재 API로 승인하지 않는다. Ubuntu·폰·OMX·Pinky 현장 계측이 없으므로 성능/안전 배치의 확정 판단도 하지 않는다.
