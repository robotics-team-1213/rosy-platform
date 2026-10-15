# OMX 학습·운용 통합 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 흰 원형 용기의 딸기를 꺼내 임시로 놓고 원래 용기에 다시 넣는 교시·IL·SIM RL·평가·제한 운용과 Web UI/UX를 연결한다.
용기 역할은 사용자 확인이다. 임시 놓을 위치·내용물·현재 단계는 아직 미확인이다.
선행 관측 작업은 [물체·문맥 계획](2026-10-15-omx-object-context.md)에 둔다.

**Architecture:** 기존 [통합 설계](2026-10-15-omx-learning-operations-design.md)와 D-756 준비 도구를 사용한다.
워크셀은 단독 버스/로컬 owner와 반응형 정책 추론, 모델 PC는 학습·독립 평가,
AI PC는 승인된 사실/Task 후보, Fleet은 admission·원장을 맡는다.
초기 IL을 완성하고 RL은 같은 과제의 SIM 실험으로 확장한다.

**Tech Stack:** 기존 Python·ROS 2·Gazebo·LeRobot 0.4.4·학습 계약/registry·Pilot·Fleet·review web.
환경/driver/API/RL 알고리즘은 해당 관문에서 고정하며 새 의존성을 선제 도입하지 않는다.

상태: **실행 전 계획**. 10/14 IL 상세 task와 SIM 준비 절차는 해당 정본을 참조한다.
이 문서는 연결 작업과 신규 RL·UI의 책임·선후관계·시험을 소유한다. 배포 일정은 실물/계정/
GPU 입력 확정 뒤 산정한다. 구현 작업은 별도 격리 브랜치에서 하고 아래 경로의 ‘제안’은
아직 존재/승인된 API나 모듈이라는 뜻이 아니다.

## 병렬 작업과 선후관계

| 작업 | 담당 역할 | 선행 | 병렬로 할 수 있는 것 | 종료 산출물 |
|---|---|---|---|---|
| T1 과제/계약 | 작업셀 담당·계약 담당 | 없음 | T2 실측 준비, T8 UI 상태 설계 | 빈칸 없는 과제 카드·계약 결정 목록 |
| T2 BENCH·환경 | 장치 담당·독립 안전 검토 | T1 | T3 합성 fixture, T6 SIM build 준비 | 실측 profile·owner/stop readback·환경 lock |
| T3 시연·검수 | 시연자·검수자 | 실제 수집은 T2a | T8 episode 검수 UI | 10 pilot 정합 보고·검토/고정 split |
| T4 IL 기준선 | 학습 담당 | T3 | T5 독립 평가 도구 | ACT 저장·재적재·baseline 보고 |
| T5 평가·artifact | 독립 평가자·승인자 | T1, 실행 평가는 T4/T6 | T7 RL 계약 초안 | 독립 outcome·정책 원장·승격 증거 |
| T6 SIM 폐루프 | SIM/장치 통합 담당 | T1, 현재 소스 이미지 | T4 및 T8 UI | 실제 owner/action/recording/task readback |
| T7 SIM RL | RL 담당·독립 평가자 | T5/T6 기준선·계약 | T8 결과 화면 | 재현 가능한 env/reward·IL/RL 비교 |
| T8 Web UX | 각 표면 소유자 | 상태 설계는 T1 | 각 backend 구현 | 전체 사용자 여정·오류/권한/접근성 증거 |
| T9 전달·제한 운용 | 배포·현장 운영자 | T2/T5/T8, RL은 추가 관문 | private Hub/Space 읽기 검증 | 설치·stop·canary task·rollback receipt |
| T10 FIELD 인계 | Fleet/현장 운영자 | T9 | 운영 문서·교육 | 실제 Fleet 원장·교대/장애/복구 확인 |

같은 follower 버스에서 native recorder와 ROSY owner를 병렬 실행하지 않는다. 같은 GPU의
훈련·평가도 자원 admission 후 순서를 잡는다. 각 작업의 구현자와 승인자 실명은 아직 미지정이다.

## T1. 첫 과제와 계약 빈칸을 닫는다

**Files:** 기존 `deploy/robot/omx/host-inventory.yaml.example`, `record_config.py`,
`contracts/learning/src/rosy/contracts/learning/{omx.py,artifacts.py,omx_execution.py}`.
실측값은 비공개 운영 설정에 둔다. 새 계약은 선점 도구로 ADR를 확보한 뒤 작성한다.

1. 딸기의 실물/모형·실측 질량·흰 원형 용기·임시 놓을 구역·허용 오차·안정 시간·timeout·독립 판정자를 적는다.
   꺼냄·임시 놓기·복귀의 개별 증거와 전체 cycle 성공을 구분하고, 같은 cycle의 데이터는 같은 split에 둔다.
2. 실제 joint/그리퍼 단위·순서·부호, rig·보정·clock·action 의미를 확정한다.
3. native mapping, hardware API/trust, RL transition, 새 holder의 결정 안건을 분리한다.
4. 누락·단위/순서 불일치·보정 교체·무권한 시작을 거절하는 생산자/소비자 시험부터 작성한다.
5. source 경로와 contract/schema/API reference를 함께 검토한다. 미결 안건을 UI 버튼으로 먼저 열지 않는다.

**종료:** 필수값/승인자가 있고, Proposed 결정과 Accepted 계약이 구별된 카드·결정 기록.

## T2. 장치 BENCH와 재현 환경을 준비한다

**Files:** `deploy/robot/omx/{preflight.py,record_config.py,requirements-lerobot-record.txt}`,
`middleware/devices/omx/adapter/omx_adapter/{profile.py,command_owner.py,local_stop.py,camera_contract.py}`.
**Tests:** `test/test_omx_record_config.py`, `test/test_omx_multi_preflight.py`, adapter owner/stop/camera 시험.

T2a는 native 교시의 장치·단위·제한·보정·단독 점유·정지·환경 수용이다.
T2b는 ROSY 실물 driver/API·owner·Pilot 수용이다. T3는 T2a 뒤 시작할 수 있고,
Pilot 실물 완성이나 T2b 전체에 종속시키지 않는다. T8 실물 조작과 T9는 T2b가 필요하다.

1. 고정 identity·중복/별칭 포트·독점 점유·실측 joint/gripper/하중·충돌을 확인한다.
2. 독립 stop·토크/전원 손실·USB 분리·재시작·HOLD/재개를 사람 감독하에 계측한다.
3. 노출/capture 시각, CameraInfo·작업면·hand-eye/TCP와 별도 기준점 오차를 확인한다.
4. recorder/trainer/SIM 환경을 별도 lock하고 import·reader·한 step·저장/reload·`pip check`를 남긴다.
5. raw preview 정상과 보정/정지 수용을 분리해 검토하고 snapshot을 고정한다.

**종료:** 실측과 stop readback이 있는 BENCH 기록. 준비 config 통과만으로 DEVICE를 승격하지 않는다.

## T3. 시연 원본에서 검토·split까지 연결한다

**Files:** `learning/curation/omx/{native_review.py,common_episode.py,lerobot_export.py}`,
`learning/curation/omx/test/test_native_review.py`, `test/test_omx_lerobot_integration.py`.

1. 기존 10/14 계획대로 native leader 교시를 시작한다. ROSY owner는 동시에 포트를 열지 않는다.
2. 첫 10 pilot에서 영상·joint/action·clock 정합, frame 누락·디스크·중단·재시도를 재독출한다.
3. 성공/실패/미판정과 채택/제외를 별도로 검토한다. 원본은 변경하지 않고 판정자·사유를 연결한다.
4. 동일 내용·수집 세션·초기 배치의 train/eval 누출과 train 외 normalization을 거부하는 RED→GREEN을 만든다.
5. 고정 manifest와 실제 독립 split을 저장한다. 추가 시연 수는 범위·coverage와 평가 부족에 따라 정한다.

**종료:** 실제 reader로 재생되는 원본·검토·고정 split. 10개라는 개수만으로 학습량 충분을 선언하지 않는다.

## T4. IL 기준선과 재적재를 확인한다

**Files:** `learning/training/omx/{act_job.py,act_inference.py,native-act.example.json}`와 해당 `test/`.
공식 native `lerobot-train`이 충분하면 새 wrapper를 만들지 않는다.

1. 같은 split·조건에서 규칙/상수와 ACT 기준선을 정의하고 기존 reject 결과를 보존한다.
2. config·데이터·processor·환경을 검증하는 작은 RED→GREEN 후 모델 PC에서 GPU smoke를 한다.
3. 새 프로세스에서 weight/config/processor/정규화를 다시 적재하고 고정 fixture를 재생한다.
4. 승인된 GPU/시간 예산 안에서 실데이터 학습을 실행하고 loss와 독립 task 지표를 별도로 저장한다.
5. 학습 설정/seed·데이터·source·환경 hash를 묶어 T5에 전달한다. loss 감소만으로 승인하지 않는다.

## T5. 독립 평가·정책 원장·단계를 연결한다

**Files:** 기존 `learning/registry/policy/{registry.py,dataset_store.py,hub_sync.py,fleet_join.py}`,
`contracts/learning/src/rosy/contracts/learning/artifacts.py`; 새 `learning/evaluation/omx/`는 holder 승인 뒤 제안.

1. 독립 outcome과 action terminal의 불일치·누락·미판정·누출을 거부하는 시험부터 만든다.
2. 같은 holdout 조건에서 성공/전체·개입·실패 영상·충돌/낙하·지연·관측 age를 비교한다.
3. evaluator는 훈련 reward와 분리하고, 실패 보고와 검토자도 artifact에 고정한다.
4. 기존 `unregistered→L0→L1→L2→L3`의 필수 증거와 서명을 검증한다.
5. metadata 승격·비활성 전달·설치·runtime admission·과제 성공을 다른 상태로 readback한다.

**종료:** baseline보다 나쁘거나 미판정인 후보는 reject/hold로 남는다. Hub revision만으로 실행하지 않는다.

## T6. 현재 소스의 SIM 폐루프를 닫는다

**Files:** `deploy/robot/omx/{compose.pilot-sim.yaml,run_pilot_sim.sh,probe_pilot_recording.py}`,
`middleware/devices/omx/adapter/omx_adapter/pilot_sim_runtime.py`,
`middleware/robot_execution/local/src/rosy/execution/local/`의 policy runtime/journal.

1. 기존 10/14 SIM 계획에 따라 선택한 호스트에서 고정 source image를 build하고 domain/partition을 분리한다.
2. Pilot→단독 owner→ROS action UUID/terminal→실제 joint→complete recording→reader를 확인한다.
3. 정책 후보→owner의 제한·stale 거절→독립 물체 결과까지 연결한다.
4. stop·lease 만료·시뮬 clock 정지·worker/USB에 대응하는 fault를 시험하고 재시작 자동 재실행을 거부한다.
5. synthetic controller 시험, 실제 Gazebo 폐루프, 물리 팔 증거를 별도 표에 남긴다.

## T7. OMX SIM RL 환경과 비교 실험을 추가한다

**제안 Files:** `contracts/learning/src/rosy/contracts/learning/rl.py`,
`learning/envs/omx/{task.py,reward.py}`, 각 `test/`,
필요할 때 `learning/training/omx/rl_job.py` 및 T5 evaluator 확장.
경로·모듈 등록은 T1에서 승인하며 이 문서가 생성 권한/공개 wire 계약을 대신하지 않는다.

1. D-427을 따르는 transition/reward/종료/reset/intervention 계약과 독립 성공 verifier를 먼저 확정한다.
   관측/행동 공간은 대상 PolicyArtifact와 일치시키며, 모든 action은 동일 owner/envelope/
   Safety Guard를 거친다. 원격 AI/Fleet를 반응형 제어 루프로 연결하지 않는다.
2. 결정적 seed/reset, 실제 적용 action, NaN/단위/경계 이탈, stale/HOLD credit, timeout과
   envelope 이탈, reward 재계산·중단/예산을 검증하는 RED→GREEN을 만든다.
3. T6의 기존 Gazebo 작업셀을 작은 Gymnasium adapter로 연결한다. Isaac geometry import를 env로 세지 않는다.
4. 고정 위치→배치 변화→관측/지연 변화 curriculum을 재현하고, ACT/규칙 baseline과 같은 holdout으로 비교한다.
5. pinned upstream 알고리즘 spike 결과로 trainer를 선택한다. offline RL은 transition coverage를
   확인한 별도 결정이고, 실물 HIL-SERL은 설계의 모든 진입조건 뒤 별도 작업이다.

**종료:** reward 상승과 별개인 task 성공·개입·안전·지연 보고. 자동 승격·실물 탐험은 범위 밖이다.

## T8. 기존 Web 표면에서 전체 여정을 완성한다

**Files:** `learning/curation/perception/{review_app.py,learning_workspace.py,review_app_web/learning.html,review_app_web/learning.js}`,
`middleware/robot_ui/pilot/{screens/arm.js,recording.js,drivers/omx_sim.js}`,
`operations/site_ui/console/{install.js,cell/cell.js}` 및 공용 UI/등록 manifest.

1. 통합 설계의 9단계 여정을 화면 상태·역할/권한·다음 행동·차단/복구 표로 고정한다.
2. 기존 Learning OMX 카드에 episode 재생·joint/action 비교·판정/split을 연결한다.
   perception pipeline의 기존 제어는 유지하고 OMX/RL 제어는 새 소유 실행기 계약 뒤 연결한다.
3. run 요청/running/terminal/cancelled를 실제 worker readback과 맞춘다. report 링크를 제어 성공으로 표시하지 않는다.
4. 실물 Pilot은 별도 driver/API 이후 연결한다. API asset allowlist·SW SHELL/cache·dev server MIME·
   CMake 설치·Android proxy/bundle을 함께 검증하고 SIM guard는 유지한다.
5. 모든 등록 표면 영향과 브라우저 여정을 검사한다. 정상/빈/403/409/5xx·지연/단절·중복 클릭·
   취소·재로그인·편집 보존, keyboard/touch/200% 확대/320폭/태블릿 가로세로·긴 한국어를 포함한다.

**Tests:** 기존 native review/ACT/registry와 review workspace HTTP/browser suite에 더해 아래를 확장한다.

- `middleware/robot_ui/pilot/test/{test_pilot_browser.py,test_recording_view.py,test_controls.py,test_shell_assets.py}`
- `operations/fleet/test/{test_cell_app_browser.py,test_policy_evidence_api.py,test_fleet_header_browser.py}`
- `shared/web/test/{test_surface_registry.py,test_responsive_tiers.py,test_surface_typography_focus_contracts.py}`

영향받는 각 표면의 D-153 G1 계약/G2 상태/G3 전체 과제 수용을 구분한다.
1920×1080·1366×768, 전화 390/320폭, Pilot 2000×1200·Android 회전을 확인한다.
브라우저·Android·실제 장치 증거는 각각 남긴다. 새 버튼만 보이는 상태를 완료로 세지 않는다.

## T9–T10. 전달·제한 운용·FIELD 인계를 확인한다

**Files:** 기존 policy install/runtime/journal/episode, registry Hub/Fleet join,
Fleet Cell/admission·receipt 경로와 해당 시험. 신규 실물 API는 T1의 계약 작업에 종속된다.

1. 대상 rig/profile과 일치하는 고정 artifact를 비활성 전달하고 byte/hash·설치 trust·재적재를 읽는다.
2. private Hub/Spaces는 실제 계정·권한·고정 SHA 왕복을 확인한다. 없어도 로컬 원본은 유지한다.
3. L1 shadow와 사람 감독 제한 실행을 구분하고, 실물 stop/하중/작업면 조건 뒤 canary task를 확인한다.
4. 새 입력 차단→행동 종결/stop readback→이전 승인 artifact→새 session으로 rollback을 확인한다.
5. Fleet admission→local attempt→독립 task outcome→실제 receipt/원장 readback과 운영자 교대·장애를 확인한다.

**종료:** 실측 조건의 성공/전체·실패·개입과 사용자 확인이 있다. Pinky 연계/모바일 조작·다른 rig/하중은 별도 범위다.

## 검증·인계 규칙

- 각 구현 작업은 실패 시나리오를 먼저 커밋하고 원격 RED를 확인한 뒤 최소 수정·GREEN·known_failures 비교를 한다.
- 예: `python tools/remote/remote_pytest.py --sha <committed-sha> --log-dir X:/DevTemp/<session>/logs/<task> -- <existing-tests>`.
  이어 `python test/known_failures.py X:/DevTemp/<session>/logs/<task>/run-1.txt`로 NEW 0을 확인한다.
  경로는 실제 등록한 X: 세션을 사용한다. pytest와 Gazebo를 노트북에서 실행하지 않는다.
- 새 holder는 manifest·설치·import·caller·fixture·suite를 함께 검증한다. owner/stop/recovery 변경은 독립 안전 리뷰를 받는다.
- SOURCE, 정적 LOCAL, REMOTE, ROS-SIM, ARTIFACT, BENCH, DEVICE, FIELD를 별도 증거로 남긴다.
  실제 문서/pytest 성공이 실물 수용을 대체하지 않는다.
- 실제 host·포트·serial·자격증명·원본 영상은 공개 문서에 넣지 않는다. 정책/데이터 접근·보존·삭제 담당을 기록한다.
- 시연자·검수자·학습자·독립 평가자·승인자·배포자·운영자의 과제 수행과 복구를 확인한다.
  요청 접수만으로 성공 처리하거나 미완료 값을 0/성공으로 채우지 않는다.
