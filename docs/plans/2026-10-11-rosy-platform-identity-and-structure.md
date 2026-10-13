# ROSY Platform Identity and Structure Implementation Plan

**현재 상태 (2026-10-11):** 채택한 실제 폴더 이동·소비자/패키징 수정은 D-626/D-628/D-630/D-637로 완료하고 local main `d4988bffba`에 반영했다. [현재 89개 holder 책임](../reference/platform-folder-responsibilities.md)과 [D-637 검증 결과](../validation/d637-remaining-folders-2026-10-11/result.md)가 현재 기준이다. 아래 원래 후보·미실행 표는 각 당시 기준의 이력이다. 미래 모델·producer admission 확장·새 API·실기 수용은 폴더 단계 완료에 포함하지 않는다.

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** ROSY의 공통 제품 정체성에 맞춰 3단계 도메인 개요와 필요한 내부 책임을 최대 5 depth로 정돈하고 세계 상태와 행동 예측을 권한·근거·학습 수명에 맞게 연결한다.

**Architecture:** [플랫폼 설계](2026-10-11-rosy-platform-identity-and-structure-design.md)의 `middleware/operations/learning` 세 파트와 공용 계약·adapter를 유지한다. `control`, `devices`, `prediction` 구조 방향은 [D-625](../adr/D-625-semantic-structure-and-staged-migration.md)로 결정하고 필요한 소스 단위만 단계별 검증 후 이동한다. 세계 상태는 관측의 projection, world model은 예측 생산자다.

**Tech Stack:** 기존 Python/ROS 2 Jazzy/ament/wheel, platform manifest, remote pytest, 기존 episode/registry 도구. world model 기술·가중치·GPU 요구는 아직 선정하지 않았다.

**상태:** Proposed, 2026-10-11, 기준 `81b6ed879`, `docs/core-responsibility-plan`. 문서 완료가 코드 이동·모델 학습·배포·실물 수용을 뜻하지 않는다.

**후속 결정:** S1의 구조 방향 ADR과 [이전 계획·도구](2026-10-11-platform-structure-migration.md)는 준비했다. S2 이후 책임 추출·world 소비자·학습/추론 구현은 미실행이다. 도구 브랜치는 `feat/platform-structure-migration`이다.

**개정:** 후속 사용자 요청으로 책임 분류 상한을 5단계로 조정했다. 현행 소스의 이동과 실제 namespace 깊이는 별도 검증하며, 4·5단계의 후보를 일괄 생성하지 않는다.

---

## 공통 규칙

[CORE 실행 계획](2026-10-11-core-responsibility-and-driving.md)의 worktree·own-path commit·원격 시험·known_failures·Safety 리뷰·착지/push 규칙을 따른다. pytest/Gazebo는 노트북에서 실행하지 않는다. root 제품 문구·Accepted 폴더 구조·새 Prediction wire는 임의 확정하지 않는다. 필요한 ADR은 `tools/harness/adr_reserve.py`로 파일 생성 직전에 선점한다.

## S0. 현재 구조·권한·이름을 고정한다

**대상:** root `AGENTS.md`, `README.md`, `PRODUCT.md`, `CONCEPTS.md`, `tools/harness/platform_parts.yaml`, package/setup/entry point/launch와 이 설계.

1. tracked file 기준 3 depth 개요와 최대 5 depth 상세 inventory를 만든다. 각 root의 package/import prefix, 실제 소비자, writer, deployment profile, Safety tag를 연결한다. 책임 holder와 Python/ament 내부 경로를 구분하고 scratch 결과는 X 관리 세션에 둔다.
2. source와 Accepted/Proposed 계약, 설치 runtime을 구분한다. 세 파트의 import table, safety anchors, `colcon_roots`와 각 설치 closure를 확인한다.
3. 제안된 이름마다 유지/변경 이유와 비용을 기록한다. 큰 혼재 단위는 `core/services`, `perception/control`, `apps/device`부터 선정한다. 4·5단계 후보마다 요구사항·서로 다른 코드 역할·실제 소비자를 적고 `폴더 승격 / 기존 파일 유지 / 실소비자 전까지 보류`로 판정한다.
4. 기존 구조 시험을 커밋된 기준으로 원격 실행한다: `test/architecture/test_platform_parts.py`, `test_platform_dependency_boundaries.py`, `test_module_structure.py`, `test_colcon_roots.py`, `test_safety_separation.py`(모두 `test/architecture/` 아래). NEW를 별도 main 기준과 비교한다.

**완료:** 3단계 개요/최대 5단계 책임 목표와 실제 경로의 차이, 깊이를 늘릴 근거, 소유권·호환 경계가 기록돼 있다.

## S1. 이름·소유권·migration 계약을 결정한다

**대상:** 설계의 목표 트리·이전표, 후속 ADR/ADR Log, 관련 root/module 안내.

1. `middleware/control/{drive,arm}`, `middleware/devices/{pinky,omx}`, `core/api`, `operations/prediction/world_model` 후보를 D-427/D-429/D-430과 대조한다. 새 writer/process가 생기지 않음을 계약에 명시한다.
2. 선택된 단위의 `현재 경로→목적 경로→caller→package→entry point→launch→deploy→tests→safety→rollback` 표를 작성한다. 목표 책임 depth≤5와 실제 namespace/ament filesystem 경로를 각각 적는다. 폴더 수나 깊이 때문에 추가 process/store/lock이 생기지 않음을 확인한다.
3. 공통 제품 정의·폴더 기준이 확정된 변경에 한해 root 안내·README·CONCEPTS를 정렬한다. umbrella/저장소의 같은 shared-git 문구를 바꿀 이유는 없으므로 건드리지 않는다.
4. schema/namespace/토픽/ROS package 외부 식별자 변경은 소스 이동과 분리한다. API 변경이 필요한 경우에만 schema/reference를 함께 수정한다.

**완료:** 모든 이동의 목적·권한·호환 방식이 결정되고, empty placeholder tree는 생성하지 않는다.

## S2. 공통 CORE와 장치 Control을 먼저 정돈한다

**대상:** [CORE 상세 계획](2026-10-11-core-responsibility-and-driving.md)의 P0–P4/A1–A2.

1. common 계약·장치별 owner/guard·Drive 복구와 곡률·Arm 궤적/복구의 책임을 먼저 고정한다.
2. 하나의 응집 단위만 이동하고 caller·설치·테스트·manifest를 같은 변경에서 완료한다. 기존 슬롯·lock·transaction의 원자성을 보존한다.
3. `perception/control`은 센서-only 활성 경계를 먼저 확인한다. legacy control/planning/escape 계산은 실제 소비자를 확인한 뒤 옮기고 legacy publisher를 활성화하지 않는다.
   공통 local 실행 수명과 도메인 recovery, 프로세스 runtime lifecycle과 명령 attempt lifecycle은 구분한다. Drive recovery의 lane_return/stuck/realign을 나눠도 같은 generation·lock·budget과 소유자를 보존한다.
4. 원격 회귀와 Safety 독립 리뷰, 실제 패키지 설치/import 검증을 완료한 단위만 다음으로 진행한다.

**완료:** 코드 위치가 제어 authority를 우회하지 않고 새 Drive/Arm 등록에 CORE 복사나 도메인 역의존이 필요하지 않는다.

## S3. 첫 세계 상태 소비자와 관측/예측 계약을 연결한다

**대상:** `operations/world/src/rosy/world/api/observation.py`, `operations/fleet/fleet/localization/map_pose.py`, `operations/situation/`, `operations/execution/`, `contracts/learning/`.

1. 두 번째 실소비자가 요구하는 관측 묶음과 갱신 주기만 정한다. Fleet MapPose나 사건 projection을 재사용하고 일반 전체-world DB를 먼저 만들지 않는다.
2. 시간·frame·calibration·revision·conflict·unknown 처리와 watermark를 정한다. snapshot은 관측/원장 참조이고 실행 원장을 직접 쓰지 않는다.
3. World State와 Prediction의 별도 입출력 의미를 후속 계약에서 결정한다. 예측은 input revision·후보 action·horizon·model digest·만료·불확실성/기권을 보존한다.
4. 결정적인 재생으로 stale/conflict·frame 불일치·event 중복·예측의 관측 덮어쓰기 금지·예측 성공의 goal 완료 금지를 고정한다. 실제 소비자 import 시험과 원격 architecture 경계를 확인한다.

**완료:** 실제 두 소비자가 쓰는 좁은 상태 조회와 예측 참조 경계가 있고 기존 로컬/사이트 원장이 그대로 권위를 가진다.

## S4. 하나의 행동 예측 문제를 오프라인 평가한다

**기존 대상:** `learning/curation/{pinky,omx}`, `learning/registry/policy`, `contracts/learning`, 기존 recording·Fleet export. **결정 후 후보:** `learning/training/world_model`, `learning/evaluation/world_model`, 필요한 model-provider adapter.

1. 첫 문제를 하나 선택한다. 후보는 짧은 Drive 동작의 pose/진전 예측 또는 Arm 접근/파지 결과 예측이다. 실제 기록·정답·동기화 수준과 사용할 장치/하드웨어가 갖춰진 문제를 선택한다. 선택 전 양쪽을 동시에 구현하지 않는다.
2. 요청 행동·guard 이후 허용 출력·실제 odom/joint/작업 결과를 분리한 episode를 만든다. train/eval 세션·MCAP·작업 식별 중복을 금지하고 합성/실물 출처를 보존한다.
3. 상수/기존 결정적 예측 baseline과 동일 재생 입력·horizon으로 비교한다. 단위가 있는 예측 오차, 불확실성에 대한 실제 오차, 장기 오차 누적, 기권·timeout·지연을 측정한다. 지표/문턱은 실제 문제와 데이터에서 결정한다.
4. 모델 이름을 고르기 전에 입출력 계약·계산 예산·학습/평가 호스트·장치 근거를 확정한다. 모델 PC에서 학습/독립 평가하고 digest·세트 hash·계약 버전·fallback을 고정 산출물로 기록한다.

**완료:** 실제 독립 데이터에 대한 baseline 비교와 승격/거절 이유가 있다. 데이터 부족·baseline보다 나쁨이면 현장 경로를 열지 않는다.

## S5. 제한된 shadow 추론과 작업 비교

**대상:** S1/S3에서 수용된 prediction owner, `operations/fleet` admission·상황 사실 연결, 승인된 AI PC deploy profile. `operations/situation`의 fact 종류를 쓰면 D-577 계약을 먼저 개정한다.

1. 고정 산출물 적재·입력 freshness·지연 budget·timeout·이전 승인 버전 rollback을 확인한다. AI PC 합성 호출 성공을 독립 예측 정확도로 보고하지 않는다.
2. 같은 실제 입력으로 shadow 예측을 기록하며 명령 binding/원장 쓰기 권한을 부여하지 않는다. 학습 process를 runtime에 설치하지 않는다.
3. 나중에 계획 비교에 쓰는 경우에도 Fleet admission·사람 확인과 로컬 guard를 통과한다. 예측이 clearance나 실제 목표 완료를 대체하지 않는 회귀를 원격 검증한다.
4. 구조/모델/source, ROS-SIM, 설치 readback, 장치, 현장 수용을 각각 기록한다. 기존 HOLD는 충족한 tier에 한해 변경한다.

**완료:** 예측·상태·실행·학습이 연결되면서 책임과 실패 출구가 유지된다. runtime 설치·새 모델 자동화·motion은 별도 사용자 승인 범위로 수행한다.

## 이번 회차의 산출물

플랫폼 설계/계획과 CORE 설계/계획 네 문서를 교차 연결하고 docs plan 목록·log·생성 index를 갱신한다. 링크/실제 경로 확인, harness generate/lint, 원격 문서 계약 시험을 수행한다. 제품 root 명칭·폴더·소스·공개 계약·현장 정책은 이 문서 회차에서 변경하지 않는다.
