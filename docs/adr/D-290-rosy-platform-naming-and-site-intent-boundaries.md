## D-290 ROSY Platform 이름과 현장 대화·미션·통신 책임을 구분한다

**Status:** Accepted (2026-09-26, 명명과 권한 경계). 이 결정은 자연어 명령, 중앙 Fleet 미션 실행기, OMX 원격 API, AI 정책, 데이터 수집 서비스 또는 실물 동작을 구현·활성화하지 않는다.

**Context:** 기존 제품 정의는 Ubuntu·ROS 2·장치 드라이버 위의 소프트웨어를 `ROSY OS`라고 부르면서 Linux 커널이나 Ubuntu를 대체하지 않는다고 설명한다. Pinky Pi, 고정 OMX-AI 1–2대, 사이트 PC, 관제 브라우저, 카메라와 향후 GPU 노드가 협업하면 제품 이름과 호스트·서비스 이름을 구별해야 한다. 사용자에게는 채팅·음성으로 작업을 요청하고 결과를 확인하는 경로가 필요하지만, 현재 `/api/fleet/do`는 허용된 구조화 동사를 해석할 뿐 자연어를 처리하지 않는다. D-12는 현장 Mission DSL을 Fleet에 두고 로봇에는 원자 액션과 이벤트만 제공하게 한다. 현행 Fleet의 영속 작업 기록은 로봇별 navigation task 중심이며 중앙 다장치 미션 실행기 완성을 뜻하지 않는다. `CONCEPTS.md`의 Task는 원자 REST 액션이지만 목표 구조 문서 08은 Transport 같은 복합 작업도 Task로 부른다. D-55의 미래 로봇 로컬 조작 상태기계 역시 현장 Mission DSL과 다른 범위다.

**Decision:**

1. **전체 제품 이름은 `ROSY Platform`이다.** 기존 저장소·패키지·파일명과 발표된 API에 남은 `ROSY OS`는 호환 및 이력 이름으로 점진 정리한다. Platform은 Ubuntu, ROS 2, 운영체제의 대체물을 뜻하지 않는다. `ROSY Site`는 한 현장의 설치·설정·배포 범위, `ROSY Console`은 사람의 화면·채팅·음성 접점을 뜻한다. `ROSY Runtime`은 노드의 로컬 실행 기반이며 Pinky CORE와 OMX별 controller는 각 장치의 구체적인 명령·상태 소유자다. PC 수, 컨테이너 수, 화면 수를 제품의 논리적 역할 수와 동일시하지 않는다.
2. **현재 현장 미션 권한과 기록의 정본은 Fleet 한 곳에 둔다.** D-12를 유지한다. `ROSY Operations`는 현장 작업 운영과 통합 콘솔의 목표 표현이며 별도 미션 실행기나 두 번째 작업 DB의 이름이 아니다. Fleet이 고정 OMX까지 조정하게 될 때는 OMX 작업 API·장치 수용 전에 Fleet을 이종 장비 미션 소유자로 명시적으로 확장할지, 기존 실행기·기록을 Operations로 단일 이행하며 D-12를 새 ADR로 대체할지 결정한다. 어느 경우에도 두 미션 소유자를 동시에 운영하지 않는다.
3. **입력·미션·장치 액션·에피소드를 구별한다.** 사람의 문장은 요청 입력이고, 채팅/AI 해석은 검증 전의 intent 후보이다. 현장 Mission/Workflow는 여러 장치 액션과 인계의 순서를 소유하며, 장치 Action은 CORE 또는 작업대 로컬 제어기가 실행·종료하는 유한한 요청이다. Episode는 관측·명령·실제 결과를 연결한 학습·재현 기록이다. 기존 `TaskKind`, `/api/fleet/tasks/*`, 목표 구조 문서 08의 `Task`를 이 ADR만으로 개명하거나 새 스키마로 간주하지 않는다. 첫 다장치 미션 계약 전에 이 용어와 미션/단계/장치 요청 ID, 요청자·대상·capability, 중복키, 만료, 취소, 수락·최종 상태, 결과 증거를 API Reference·공유 schema·용어집에서 함께 정합한다(D-18). D-170의 유예된 `correlation_id`/ACK 필드를 이 ADR만으로 활성화하지 않는다.
4. **대화는 실행 권한의 원천이 아니다.** Console의 채팅·음성 입력은 등록된 장비와 허용 capability에 맞는 구조화된 요청 후보를 만든다. 현재 Fleet 또는 후속 단일 미션 소유자가 요청자 권한, 장치 상태, 작업 가능성, 만료, 중복 제출, 취소, 결과 확인을 검증·기록한 뒤 장치별 수용된 API로 제출한다. LLM·VLA·월드 모델의 출력은 임의 ROS 토픽·`cmd_vel`·팔 trajectory 또는 미등록 API 호출 권한을 얻지 않는다. 요청 접수, 장치 수락, 실제 완료와 결과 불명확(`UNKNOWN`/HOLD)을 화면과 채팅에서 구분한다. 정지 수단은 채팅 모델의 가용성에 의존하지 않는다.
5. **`ROSY Fabric`은 버전 계약·어댑터·연결 정책의 기술명이다.** 단일 중앙 메시지 버스나 모든 데이터를 지나는 서버를 새로 만들라는 결정이 아니다. D-269의 역할별 HTTPS REST/WSS 연결을 유지하고, 각 장치 내부의 ROS 2/DDS와 사이트 간 인증 계약을 구분한다. 사이트 UI·Fleet·AI가 장치 DDS graph에 직접 참여하거나 원본 영상을 Fleet으로 중계하지 않는다. 새로운 OMX 작업 API나 장치 간 브리지는 장치 identity, 허용 capability, 요청·취소·결과, 인증, 신선도, 장애 시 HOLD를 별도 계약과 장치 시험으로 수용한다(D-282).
6. **관측·AI·데이터는 작업 기록과 연결하되 각자의 수명을 가진다.** Vision/Perception은 출처·시각·좌표계·보정 revision이 있는 관측을 만든다. AI는 VLA·월드 모델의 예측과 행동 후보 및 모델 version을 관리한다. Data는 허용된 원본 영상·관절·행동·결과를 에피소드와 데이터셋으로 연결한다. Fleet에는 운영에 필요한 파생 관측과 작업 이력을 두며 원본 영상·학습 부하를 Fleet 명령 프로세스/DB에 합치지 않는다. 장치 실제 상태와 최종 주행·팔 명령은 Pinky CORE와 OMX별 로컬 제어기에 남는다(D-275, D-281, D-282).

**Alternatives:**

- `ROSY OS`를 전체 제품명으로 유지: 기존 문서·저장소에는 익숙하지만 자체 운영체제 또는 모든 PC에 같은 OS를 설치한다는 오해를 만든다.
- Fleet에 채팅, 영상 원본, 데이터셋, 모델 학습과 장치 제어를 모두 넣는다: 운영 미션의 정본은 단순해 보여도 인증·자원·저장·장애와 명령 소유권 경계가 무너진다.
- 새 Operations 서버에 Fleet과 별도 미션 저장소를 즉시 만든다: D-12를 사실상 바꾸고 한 작업의 상태 정본을 둘로 나눈다.
- Fabric을 공통 버스 또는 사이트 ROS graph로 구현한다: D-269의 목적별 연결과 로컬 제어 경계를 흐린다.

**Transition / validation:** 제품 정의 문서의 이름을 먼저 맞춘다. 현행 `fleet`, `vision`, `core`, `/api/fleet/*` 경로와 이미 배포된 계약은 이 ADR만으로 개명하지 않는다. 첫 자연어 명령은 구조화된 의도→권한·capability 검증→기존 작업 경로→장치 readback을 끝까지 시험하고, 단순 응답 수락을 완료로 표시하지 않는다. D-170에 따라 `correlation_id`/ACK 추적은 현재 미구현이며 중앙 Fleet 착수 때 D-177과 함께 다룬다. D-268의 자동 Vision 정책, D-273의 OMX 실물 경로, D-281/D-282의 배치·제어 제안은 각각의 수용 게이트 전까지 비활성이다. 이 ADR의 SOURCE/LOCAL 문서 검증은 DEVICE/FIELD 수용이 아니다.

**References:** [D-12](D-12-mission-fleet.md), [D-18](D-18-rosy-core.md), [D-55](D-55-mobile-manipulation-is-a-robot-local-mission-capability.md), [D-170](D-170-prt-004-deferred-until-central-fleet.md), [D-177](D-177-prt-004-activation-design.md), [D-268](D-268-policy-eligible-vision-evidence-for-fleet-tasks.md), [D-269](D-269-device-server-contracts-and-ros-boundary.md), [D-273](D-273-omx-camera-stream-and-arm-control-order.md), [D-275](D-275-web-surface-and-video-runtime-ownership.md), [D-281](D-281-site-host-placement-and-omx-instance-isolation.md), [D-282](D-282-per-hardware-ros-ownership-and-control-boundaries.md), [용어집](../../CONCEPTS.md), [제품 정의](../architecture/00_ROSY_OS_Vision_and_Definition.md), [목표 구조](../architecture/01_ROSY_OS_Target_Architecture.md), [작업 구조](../architecture/08_ROSY_Task_and_Workflow.md).
