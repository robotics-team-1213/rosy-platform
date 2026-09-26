# 사이트 역할별 실행·배치 토폴로지 설계

작성일: 2026-09-26
상태: 설계 초안. [D-275](../adr/D-275-web-surface-and-video-runtime-ownership.md), [D-281](../adr/D-281-site-host-placement-and-omx-instance-isolation.md), [D-282](../adr/D-282-per-hardware-ros-ownership-and-control-boundaries.md), [D-290](../adr/D-290-rosy-platform-naming-and-site-intent-boundaries.md)의 책임을 배포 단위로 구체화한다. 신규 API나 실물 OMX 가동 승인 문서는 아니다.

## 1. 고정할 것과 옮길 수 있는 것

**책임과 계약은 고정하고, 프로세스의 호스트 배치는 옮길 수 있게 한다.** 첫 현장의 Ubuntu PC 한 대에 사이트 서비스를 둘 수 있으나, 이것을 하나의 `ROSY Platform` 프로세스나 하나의 ROS graph로 만들지 않는다. 관제 PC의 브라우저는 실행 호스트가 아니다. Pinky는 각 Pi의 CORE가, 고정 OMX는 각 작업대의 로컬 제어 인스턴스가 실제 장치를 소유한다.

| 실행 역할 | 현재 소스·배포 | 권위 있는 상태와 권한 | 옮길 때 지킬 경계 |
|---|---|---|---|
| Site edge | `deploy/site`의 Caddy | 사이트 HTTPS 입구·라우팅 | 브라우저/폰이 내부 Compose 이름을 알지 않음 |
| Fleet | `src/site/fleet`, 사이트 Compose | 작업·이벤트·sighting의 현행 SQLite, 로봇 배정·요청 이력 | 원장 단일 writer·백업/복구를 먼저 검증; OMX trajectory나 영상 바이트를 소유하지 않음 |
| Vision ingress/관측 | 현재 `src/site/overhead`의 단일 서비스 | 천장 폰 source 인증, 최신 프레임, CPU ArUco 관측 | 추론 worker 분리는 미래 변경; source·촬영 시각·보정 revision 유지 |
| 추가 AI/학습 | 아직 운영 서비스 없음 | 모델 후보·학습 자료·평가 결과의 별도 수명 | GPU PC를 추가해도 관측/제안만 제출; 모델 배포와 정책 활성화는 별개 |
| Pinky runtime | Pi의 native CORE | 로컬 ROS graph, 최종 `cmd_vel`, 안전·정지, CORE API | 사이트 중단 중에도 로컬 정지 경로 유지 |
| OMX runtime | 작업대별 adapter 후보, 개발/ROS-SIM 이미지 | 해당 serial/camera·팔 action의 단일 로컬 owner | D-281 Proposed와 DEVICE 정지 수용 전 native 운영 서비스/원격 작업 API를 열지 않음 |
| 사용자 화면 | 사이트 Fleet `/console`, 로봇 CORE `/console` | 각 origin의 인증·권한·readback | 같은 경로명이어도 별도 서버·세션; 진단 `web_node`는 운영 경로 밖 |

물리 `host_id`는 위 역할의 배치 속성이고 `site_id`·`robot_id`·`workcell_id`를 대신하지 않는다. 동일 PC에 두 OMX가 있더라도 `instance_id`·device binding·ROS domain/namespace·설정·로그·중지 절차는 각각 갖는다. 한 PC의 장애는 공통 장애이므로 프로세스 분리를 안전 격리로 표시하지 않는다.

## 2. 검토할 배치 모양

| 후보 | 구성 | 채택 조건 |
|---|---|---|
| A. 단일 사이트 PC | Ubuntu 한 대의 Site Compose(Fleet·Vision·Caddy), 같은 PC에 OMX별 native 제어 후보; Pinky는 각 Pi | 첫 설치·ROS-SIM 측정 후보. 두 팔+Vision 부하, USB, 물리 정지와 공통 전원 장애를 통과하기 전 운영 기본값으로 확정하지 않음 |
| B. 사이트 PC + OMX PC | Site Compose는 사이트 PC, OMX 1~2 인스턴스는 별도 PC | USB 거리·정지·자원/장애 요구가 A를 벗어날 때. Fleet→OMX 연결은 별도 수용된 workcell 계약 이후 |
| C. 사이트 PC + OMX별 PC + AI PC | 장치별 제어 호스트와 별도 GPU 학습/추론 호스트 | 독립 장애·계산 자원·보존 요구가 측정으로 확인될 때. AI PC는 장치 명령 주체가 아님 |

배포에서 A→B→C로 옮겨도 장비와 작업 identity는 보존한다. 호스트 간 Docker bridge나 SQLite 공유 마운트로 역할을 연결하지 않는다. Vision을 다른 PC로 옮길 때는 현재 Compose 내부 `vision` 연결을 그대로 확장할 수 없다. 보호된 서비스 주소, TLS 신뢰·source/service 자격 증명, 프레임/관측 계약, 단절·재시도, 대역·지연 예산을 별도 구현·시험해야 한다. 원본 프레임의 Fleet 유입은 계속 금지한다.

## 3. 통신 방향과 결정 권한

```text
운영자 브라우저 ─HTTPS─> Site edge ─> Fleet ─인증 REST─> Pinky CORE ─> 로컬 구동
천장 폰       ─WSS────> Site edge ─> Vision ─작은 sighting─> Fleet
향후 AI/VLA   ─제안/증거 계약──────────────────────────────> Fleet의 정책·작업 검사
Fleet ─미정의 workcell 작업 계약─> OMX 로컬 owner ─> vendor action ─> 해당 팔
```

그림에서 **현재 소스 경로**는 폰→Vision→Fleet sighting, 브라우저→Fleet, Fleet→CORE와 선택적 CORE Agent→Fleet 이벤트다. AI/VLA와 Fleet→OMX는 설계 경로이며 endpoint·schema·자격 증명은 아직 없다. 미래 경로를 임의 REST 경로나 공용 명령 envelope로 구현하지 않는다. CORE Agent 업링크는 이벤트용이고 제어 채널이 아니다.

문장형 채팅 요청도 바로 명령이 아니다. 향후 도입한다면 `사용자 입력 → 모델의 구조화된 목표 후보 → 사용자·역할 확인 → Fleet의 허용 동사/자원/멱등성/상태 검사 → 장치별 작업 접수 → 실제 결과 readback`을 거친다. 모델은 장비 ID, 좌표, 성공 상태를 단독 확정하지 못한다. 자동 경로는 [D-268](../adr/D-268-policy-eligible-vision-evidence-for-fleet-tasks.md)의 별도 현장 수용 전까지 HOLD다. Fleet의 접수, CORE/OMX의 수락, 물리 완료는 서로 다른 상태다. 응답 유실이나 결과 불명은 `UNKNOWN`으로 기록하고 무조건 재발행하지 않는다.

현 단계의 미션 권한과 기록 정본은 D-290에 따라 Fleet 한 곳이다. **현재 구현된 영속 작업은 로봇별 이동 작업 중심**이며 이종 장비 미션 실행기는 없다. 향후 Fleet에서 확장할지 Operations로 **단일 이행**할지는 별도 ADR에서 정한다. 두 저장소가 같은 미션을 동시에 소유하는 전환은 허용하지 않는다. `ROSY Fabric`은 위 역할별 계약과 어댑터의 이름이며 별도 중앙 버스/서버를 지금 추가하는 뜻이 아니다.

OMX 원격 계약을 열 때는 작업대 ID·capability·요청/멱등성 ID·만료·취소·최종 readback을 먼저 결정한다. 사이트의 작업 요청은 팔의 관절 경로·속도·그리퍼 폐루프를 포함하지 않는다. OMX 로컬 owner는 policy arbitration과 독립 정지/timeout HOLD를 책임지고, vendor action을 직접 호출할 수 있는 다른 DDS 참가자가 없는지 실행 경계에서 검증한다. 현재 ROS-SIM의 `busy` 거절은 프로세스 내부 정책 증거일 뿐 이 배포 경계의 증거가 아니다.

## 4. 데이터와 모델의 위치

Fleet의 현행 SQLite는 사이트 작업·이벤트·sighting 원장이다. 영상 저장소, 학습 데이터 레이크, 로봇 내부 로그의 정본이 아니다. Vision은 원본 프레임을 최신 처리에 사용하며, 장기 보존·재학습 자료가 필요하면 별도 동의/보존기간/삭제/접근권한/용량 계약을 먼저 만든다. 파생 증거에는 source, 촬영·수신·처리 시각, frame/map, 보정·모델 revision, 만료와 품질을 결부한다. 현재 sighting을 자동 명령의 정책 적격 증거로 승격하지 않는다.

VLA/월드 모델은 `오프라인 학습·평가 → 고정 모델 산출물 → 제한된 운영 추론 → 근거가 있는 목표 후보` 순으로 도입한다. 학습 worker는 Fleet의 SQLite나 제어 호스트 장치 파일을 직접 쓰지 않는다. 모델 교체는 배포 revision과 평가 기록을 요구하며, 학습 완료가 현장 작업 허가를 뜻하지 않는다. 운영 추론과 학습은 CPU/GPU·메모리·저장 예산과 재시작 정책을 분리한다.

## 5. 장애 시 기본 동작과 구현 순서

| 사건 | 사이트 표시·작업 원장 | 장치 측 기본 동작 |
|---|---|---|
| Vision/폰 단절 또는 stale | 관측을 stale로 표시; 해당 자동 조건 HOLD | 진행 중인 로컬 안전·정지 유지 |
| Fleet/사이트 PC 단절 | 신규 원격 작업 불가, 미확인 작업 `UNKNOWN`; 복구 후 readback | Pinky CORE와 OMX owner의 로컬 정지/timeout 유지 |
| OMX 링크·joint state·owner 단절 | 완료로 추측하지 않음; 운영자 조정 필요 | 해당 작업대 HOLD, 재시작 뒤 무명령·재승인 |
| 공유 PC 과부하/전원 상실 | Fleet과 Vision 동시 손실을 공통 장애로 기록 | 각 팔의 독립 물리 정지와 복귀 절차를 DEVICE에서 검증 |

1. **지금 가능한 SOURCE 작업:** 역할·호스트·장치 인벤토리와 실제 Compose/서비스 매핑을 정적 검사하고, 사이트 원장 백업/복원·stale/UNKNOWN 표시를 기존 계약 안에서 검증한다. 화면의 origin·권한과 원본 영상 비유입을 유지한다.
2. **ROS-SIM:** OMX별 단일 owner와 두 graph 격리, 경쟁 policy, 직접 vendor action 우회 가능성, 재시작/timeout HOLD를 계측한다. 우회 경계가 닫히기 전 native 자동 기동을 구현하지 않는다.
3. **ARTIFACT/SITE:** 수용된 native OMX 후보와 Site Compose 각각의 digest·config·TLS·권한·서비스 복구를 실제 Ubuntu에서 확인한다. 역할을 다른 PC로 옮길 때 네트워크 계약을 명시적으로 추가한다.
4. **DEVICE/FIELD:** OMX 1대→2대, 천장 폰·Pinky·사이트 동시 부하, 물리 정지, 공통 PC 장애, 작업 결과 reconciliation을 순서대로 확인한 뒤 A/B/C 배치를 선택한다.

이 설계는 [사이트 배치 설계](2026-09-26-site-host-placement-design.md)의 배치 모델을 역할·통신·데이터 경계까지 펼친 것이다. 현재 `omx.enabled: false`, D-281 Proposed, D-268 Proposed를 유지한다. 실제 호스트나 OMX 접근 전에는 배치 후보를 운영 채택으로 바꾸지 않는다.

## 6. 배치가 바뀌어도 유지할 입구와 내부 연결

사이트의 외부 주소는 브라우저와 천장 폰이 접속하는 **사이트 FQDN/Caddy 입구**다. 현행 Caddy는 `/overhead/v1/frames`만 `vision:8095`로 보내고 나머지를 `fleet:8090`으로 보낸다. 두 이름은 현재 Compose 내부 DNS다. `proxy`의 포트 바인딩 기본값은 loopback이므로 현장 LAN 노출 여부는 호스트 설정·방화벽·인증서와 함께 결정해야 한다. 이 구성을 복수 PC에 그대로 복사해도 호스트 사이에 `vision` DNS가 생기지는 않는다.

| 배치 변경 | 외부 주소 | 내부에서 새로 필요한 계약 | 지금 가능한가 |
|---|---|---|---|
| Fleet와 Vision을 같은 PC에 유지 | 사이트 FQDN 유지 | 현행 Compose `site_backend` | LOCAL 구성 존재; SITE 미검증 |
| Vision 서비스 전체를 다른 PC로 이전 | 사이트 FQDN 유지, Caddy의 upstream만 변경 | 호스트 간 Vision 주소·TLS 신뢰·서비스 인증, 네트워크 단절 처리, 영상 대역 측정 | 현행 Caddy/Compose만으로 불가 |
| 영상 수신은 사이트 PC에 두고 GPU 추론만 이전 | 사이트 FQDN과 폰 계약 유지 | 수신→원격 worker의 별도 영상 전달, 프레임 신선도·역압·인증·삭제 정책 | worker/전달 계약 없음 |
| OMX 제어를 다른 PC로 이전 | 사이트 FQDN과 `workcell_id` 유지 | 먼저 수용된 workcell 작업·상태 API, 장치/보정/정지 재검증 | 현행 원격 OMX API 없음 |

Vision 분리의 **첫 후보는 수신 입구를 유지하고 무거운 연산만 옮기는 방식**이다. 폰 설정과 Caddy의 외부 경로를 유지하면서 연산 장애를 별도로 다룰 수 있기 때문이다. 다만 원본 프레임을 PC 사이에 보내는 새 내부 계약과 대역 예산이 필요하므로, 그 계약 없이 GPU PC를 단순히 Compose에 추가하지 않는다. 측정 결과 전송 비용이 크면 Vision 서비스 전체 이전과 Caddy upstream 변경을 비교한다. 어느 경우에도 Fleet에는 파생 관측만 보낸다.

## 7. 배포 기록과 재기동의 권한

**설치 기록은 물리 배치의 정본, Fleet DB는 작업 상태의 정본, 장치 readback은 실제 동작의 정본**으로 구별한다. 현재 아래 설치 기록은 설계 계약이며 실행 파서가 아니다. 비밀 값과 실주소는 공개 저장소에 두지 않는다.

| 기록 단위 | 반드시 연결할 정보 | 변경 승인과 확인 |
|---|---|---|
| 사이트 배포 revision | `site_id`, Site Compose 이미지 digest, 사이트 FQDN/CA, Fleet DB volume·백업 revision, 카메라 source·보정 revision | 서비스 재시작 뒤 HTTPS, 인증, DB 복원과 sighting readback |
| Pinky 배치 | `robot_id`, Pi/CORE 산출물·설정 revision, CORE endpoint/토큰 식별자 | 로봇 로컬 정지 경로와 API readback; 사이트 DB 행만으로 판정하지 않음 |
| OMX 작업대 배치 | `workcell_id`, 활성 `instance_id`, `host_id`, native 산출물·설정·보정 revision, follower/leader/camera 영속 ID | 이전 host 종료·장치 점유 해제, 새 host 무명령 기동·물리 정지/readback·운영자 승인 |
| AI 모델 배치 | 모델·입력·보정 호환 revision, 배포 host, 평가 기록 | 추론 결과 품질과 stale 시험; Fleet 자동 정책 활성화는 별도 결정 |

Fleet SQLite는 현행 단일 사이트 volume의 writer 한 곳만 허용한다. 백업은 WAL을 고려한 SQLite-aware 방식으로 만들고 **분리된 volume에 복원 시험**한 뒤 이전한다. 두 Fleet 인스턴스를 공유 마운트로 동시에 실행하거나, 백업 복원본을 살아 있는 원본과 함께 명령 서버로 올리지 않는다. Fleet 장애·복원 중 접수 여부가 불명확한 작업은 `UNKNOWN`을 유지하고 CORE/장치 상태와 대조한다. 현재 코드의 `UNKNOWN`·idempotency 경로는 이동 작업에 대한 것이며, 이 절차가 범용 다장치 미션 복구 구현을 뜻하지 않는다.

OMX 이전에는 자동 failover를 두지 않는다. 이전 PC의 제어 프로세스 종료와 실제 device release를 확인하고, 새 PC의 identity·장치·보정·artifact를 검증한 후 무명령 상태에서 시작한다. 작업 재개는 새 요청과 운영자 승인으로 처리한다. 네트워크가 끊겨 이전 PC의 상태를 확인할 수 없으면 새 인스턴스를 시작하지 않는다. 두 PC가 같은 물리 팔의 활성 owner가 되지 않는다는 현장 readback이 배포 기록보다 우선한다.

## 8. 다음 구조 결정의 순서

1. **현행 사이트 경로 고정:** Caddy 외부 경로, 내부 `fleet`/`vision` DNS, 서로 다른 인증 주체, Fleet SQLite의 단일 writer·백업/복원과 현재 이동 작업 상태를 SOURCE/LOCAL에서 검증한다. 폰→사이트, Fleet→실물 CORE는 별도 SITE/DEVICE로 남긴다.
2. **OMX 로컬 제어 경계:** 단일 writer·DDS 직접 action 우회 차단·timeout/정지 상태를 ROS-SIM과 DEVICE에서 확인한다. 그 결과와 D-281 수용 전에는 native 운영 서비스와 Fleet 원격 작업 경로를 열지 않는다.
3. **첫 PC 배치 선택:** 사이트 서비스와 한 OMX를 함께 실측하고, 두 번째 OMX를 추가하여 USB/CPU/GPU/열/정지 간섭을 측정한다. 실패 원인에 따라 Site↔OMX 분리, OMX 간 분리, GPU worker 분리 중 필요한 것만 선택한다.
4. **자연어·VLA 확장:** 입력 후보의 검증·사용자 확인·작업 원장·장치 readback을 먼저 끝까지 연결한다. 이종 장비 미션 정본(Fleet 확장 또는 Operations 단일 이행), 에피소드 수집과 모델 배포는 각각 별도 계약·ADR에서 확정한다.
