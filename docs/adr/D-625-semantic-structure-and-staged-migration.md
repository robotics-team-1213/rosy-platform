## D-625 ROSY 의미 기반 책임 구조와 단계별 폴더 이전

**Status:** Accepted (2026-10-11, 사용자 결정; 구조 방향·계획·이전 도구 준비에 한정, 실제 이동·실행 권한 변경·장치 수용은 별도).

## Context

사용자는 CORE의 조향·길찾기·복구·Safety를 검토하면서, 이동 로봇과 Arm의 차이를 보존하고 ROSY 전체를 확장 가능한 의미로 분류하기로 했다. 3단계 개요 아래 필요한 책임만 최대 5단계까지 설명한다. World model은 세계 상태와 행동 결과 예측을 함께 지원하되 관측과 예측을 섞지 않는다.

현재 `core/services`에는 공통 서비스와 Drive 로직이 섞여 있고, `perception/control`의 Python package `control`은 전체 제어 계층을 뜻하지 않는다. `apps/device`는 장치 profile·bringup·adapter를 포함한다. 폴더 이름을 바꾸는 것만으로 이 책임이 분리되지는 않는다.

## Decision

1. ROSY를 **서로 다른 로봇과 현장 장치를 근거를 가진 작업으로 연결하고, 장치별 안전한 실행과 실제 결과를 확인하며, 그 경험으로 개선하는 로봇 작업 플랫폼**으로 설계한다. 기존 D-290의 제품 이름과 현장 실행 경계는 유지한다.
2. D-427의 `middleware`(장치 실행), `operations`(현장 조정·원장), `learning`(경험·학습·평가)을 유지한다. `contracts`는 공유 계약, `integrations`는 외부 adapter이며, `profiles/deploy/tools/test/docs`는 지원 구조다. 깊이는 저장소 아래 **책임 holder** 기준이다. Python namespace·ament 패키징 깊이에는 일률적인 5단계 제한을 적용하지 않는다.
3. [상세 목표 트리](../plans/2026-10-11-rosy-platform-identity-and-structure-design.md)의 배치를 채택한다. 대표 책임은 다음과 같다. 새 소비자나 분리할 코드가 없는 폴더는 만들지 않는다.

   | 책임 | 목표 holder | 경계 |
   |---|---|---|
   | 공통 CORE | `middleware/core/{gateway,api,runtime,capabilities,state,events}` | admission·외부 API·process lifecycle·공통 상태 |
   | Drive | `middleware/control/drive/{planning,tracking,recovery,docking,localization,safety}` | 경로 후보·조향·제한된 복구·Drive guard |
   | Arm | `middleware/control/arm/{planning,tracking,recovery,safety}` | 관절·gripper·workspace, 장치별 실행 owner |
   | 인지 | `middleware/perception/{sensors,vision}` | 관측 생산, 최종 명령을 발행하지 않음 |
   | 장치 구성 | `middleware/devices/{pinky,omx}` | profile·bringup·장치 binding |
   | 로컬 실행 | `middleware/execution/local/{admission,lifecycle,receipts}` | action attempt, 공통 process lifecycle과 구별 |
   | 현장 실행 | `operations/execution/{api,site}` | transaction·admission·scheduling·journal |
   | 관측 상태 | `operations/world/{api,state}` | observations·frames·projections, 기존 원장을 대체하지 않음 |
   | 행동 예측 | `operations/prediction/world_model/{context,inference,results}` | 후보 행동의 rollout·uncertainty, 실행 승인 권한 없음 |
   | 학습·평가 | `learning/{training,evaluation}/world_model` | datasets/objectives/jobs 및 replay/metrics/acceptance |

4. Safety는 별도 서비스 하나로 집중하지 않는다. 공통 중재·정지, Drive envelope/clearance, Arm limits/workspace, 장치 stop/readback, Fleet lease/통행권의 책임을 구별한다. D-430의 태그·anchor·독립 리뷰를 보존한다. 물리적 최종 writer는 CORE의 `/cmd_vel` 및 Arm의 기존 장치 owner에 남는다. 새로운 실행 process·lock·원장·writer를 폴더 분류 때문에 만들지 않는다.
5. Drive 경로 계획, tracking, 곡률/속도 envelope, recovery는 같은 실행 generation·취소·budget·guard를 보존한 채 분리한다. Nav2·차선·swarm·docking의 후보 생산과 최종 명령 확정을 구별한다. Arm에 Pinky의 주행 모드나 twist를 강제하지 않는다. 구체적인 추출 순서는 [CORE 계획](../plans/2026-10-11-core-responsibility-and-driving.md)을 따른다.
6. World State는 관측·확정 사건의 projection이고 Prediction은 action-conditioned 추정이다. 예측은 input revision·horizon·model digest·불확실성·만료를 가진 별도 계약으로 설계한다. 예측 성공은 실행 완료 증거가 아니다. D-503의 실제 추가 소비자 조건과 D-516의 offline 평가→승인 버전 추론→Fleet admission→local 실행 경계를 유지한다. 이번 결정은 wire schema나 모델 선정이 아니다.
7. [이전 실행 계획](../plans/2026-10-11-platform-structure-migration.md)을 먼저 작성한 뒤 도구를 준비한다. `api_web→api`, Pinky·OMX device holder, Nav2 package 이동은 후보 단위이며 책임 추출과 구별한다. ROS package명·Python import prefix·entry point를 보존한다. `platform_parts.yaml`의 현재 `path`와 하위 root/anchor는 이동 시 갱신하되 `d427_target`은 기존 소유권 식별자로 보존한다. 기존 `legacy` 이력도 덮어쓰지 않는다.
8. 이전 도구는 기본 read-only preview, 선택 단위 하나의 물리적 이동만 지원한다. 참조·패키징 수정은 소비자 목록을 보고 같은 이전 커밋에서 검토한다. Safety가 포함된 단위는 도구의 자동 이동 대상에서 제외한다. 미커밋·미추적/ignored 파일, 대상 충돌, linked path, main, 오래된 HEAD는 거절한다. 자동 삭제·stash·reset·광역 staging을 하지 않는다. 계획 문서와 도구 준비는 실제 제품 폴더 이전을 승인하거나 완료하지 않는다.

## Consequences

CORE를 거대한 주행 모듈로 해석하지 않으면서 Drive·Arm·세계 상태·예측의 자리를 설명할 수 있다. 4·5단계는 독립 책임과 실제 소비자가 생길 때 사용한다. 현재 폴더와 목표 폴더가 함께 존재하는 동안 manifest·설치·deploy·test·Safety 경로를 빠뜨리지 않고 한 단위씩 닫아야 한다.

이번 변경은 ADR·계획·도구의 SOURCE와 원격 도구 시험만 검증한다. 책임 추출, colcon/ARM64 설치, 배포, 실행 활성화, 물리적 수용은 완료하지 않는다. 기존 Accepted ADR을 다시 쓰지 않으며 D-427의 part/import 규칙에는 예외를 추가하지 않는다.

## Alternatives

전체를 `core` 아래 넣으면 Arm과 현장 원장까지 주행 중재에 종속된다. 전 폴더를 한 번에 이동하면 패키징·Safety 변경을 개별 검증하기 어렵다. 모든 holder를 5단계로 강제하면 실제 책임이 없는 placeholder가 생긴다. 따라서 책임 추출과 패키지 보존 이동을 분리하고 필요한 단위부터 진행한다.
