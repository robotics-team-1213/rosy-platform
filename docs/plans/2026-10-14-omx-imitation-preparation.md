# OMX 모방학습 및 Hugging Face 연동 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 리더 시연을 쉽게 반복·검토하고, 고정 데이터 revision으로 모방학습을 재현하며, Pilot 실물 수동 조작을 함께 준비한다.

**Architecture:** 공식 LeRobot native recorder를 첫 수집 경로로 사용한다. 기존 ROSY OMX owner와 버스 소유를 분리하고, 데이터/모델은 로컬 검증 뒤 private Hub에 동기화한다. Spaces는 저장된 결과를 읽는다.

**Tech Stack:** Python, LeRobot(현재 SIM 기준 0.4.4; 실물 환경 lock 별도), Hugging Face Hub, 기존 ROSY OMX adapter/Pilot, 필요 시 Gradio.

---

설계 정본: [준비 설계](2026-10-14-omx-imitation-preparation-design.md).
구현 브랜치: `feat/omx-imitation-tools`. [실행 안내](../../learning/curation/omx/README.md)에 현재 명령을 정리했다.
Task 1–4의 준비 도구를 구현했다: 녹화 설정 검사, native reader 검토·분할, 공식 ACT 설정, private Hub 해시 왕복 도구.
원격 기본 시험 70개와 별도 실제 LeRobot 통합 시험 1개가 통과했다. 통합 시험은 합성 RGB 영상의 저장·재독출·분할, train 통계 격리, ACT 1-step backward·저장·재로딩이다.
실물 환경 lock·녹화·GPU 학습·실제 Hub 왕복은 미확인이다. 실행 PC와 HF 조직은 미정이며, Task 5 Pilot 실물 조작과 Task 6 Spaces 계정 접근 검증은 남아 있다.
아래 Task는 전체 수용 기준이며, 일부 준비 구현만으로 완료 처리하지 않는다.
후속 검증: 공식 학습 CLI로 합성 영상 train split을 CPU 2 step 학습하고 저장된 model/preprocessor/postprocessor를 재적재했다. Hub 중단·손상 응답·동일 commit 재시도도 대역 시험했다. 관련 원격 12개 통과, NEW 0.
실물·계정 미정으로 보류한 항목과 재개 입력·완료 증거는 [D-756](../adr/D-756-omx-imitation-preparation-and-resumption-gates.md)에 기록했다.

## Task 1: 실물 녹화 구성과 환경을 고정한다

**Files:**
- 재사용: `deploy/robot/omx/preflight.py`, `deploy/robot/omx/host-inventory.yaml.example`.
- 추가 후보: `deploy/robot/omx/lerobot-record.example.json`, `deploy/robot/omx/requirements-lerobot-record.txt`.
- 문서: `deploy/robot/omx/README.md`.
- Test: `test/test_omx_multi_preflight.py`, `test/test_omx_host_inventory.py`, 새 `test/test_omx_record_config.py`.

1. 선정한 LeRobot 버전의 config parser에 예시를 넣는 시험을 먼저 만든다. 실제 장치 constructor/connect는 호출하지 않는다.
2. 장치 ID·포트·카메라·저장 위치가 미선정이면 시작 설정을 만들지 못하게 하고, 로컬 저장·업로드 꺼짐·private 기본값을 확인한다.
3. recorder venv와 GPU trainer venv를 따로 lock한다. ROSY CPU export lock은 유지한다.
4. 포트 중복 거부뿐 아니라 실제 runner의 독점·정지·이전 owner 해제 검사 필요성을 README에 명시한다.
5. exact files만 커밋하고 원격 시험을 실행한다. 버전 문자열 일치와 실제 native 지원·reader 동작을 구분해 기록한다.

### 운영자가 미리 채울 워크셀 카드

| 항목 | 작성할 값 |
|---|---|
| 첫 과제 | 동작 한 가지와 눈으로 확인 가능한 성공 조건 |
| OMX | follower/leader 실물 revision, 각 영구 포트, 전원·고정 상태 |
| 보정 | motor map, joint/gripper 단위·부호, calibration revision |
| 카메라 | 고정 위치, stable identity, 데이터 key, 해상도·fps, rig revision |
| 환경 | recorder/trainer 버전, PC 역할, 저장 위치·여유 공간 |
| HF | org, dataset/model 저장소 후보, private 권한, 업로드 담당자 |

실제 포트·주소·자격증명은 공개 카드에 쓰지 않는다. 채운 카드는 gitignored `private/` 또는 해당 호스트의 운영 설정에 보관한다.
Windows의 녹화 검토·학습 산출물·로그는 등록한 X: 세션 아래에 둔다. Linux host의 기존 데이터 경로는 유지하고 명시적으로 기록한다.

포트 정적 점검은 Linux 워크셀에서 기존 명령을 사용한다. 두 인자는 운영자가 고른 서로 다른 실제 by-id 항목이다.

```bash
python3 deploy/robot/omx/preflight.py \
  --follower /dev/serial/by-id/<selected-follower-id> \
  --leader /dev/serial/by-id/<selected-leader-id>
```

이 도구는 포트 점유 검사·arm stop readback·motion admission을 대신하지 않는다.
공식 recorder에 사용할 녹화 옵션은 `--dataset.push_to_hub=false --dataset.private=true`다.
장치·제한·카메라 값이 검증되지 않아 지금 복사 실행 가능한 motion 명령은 제공하지 않는다.

## Task 2: 시연 수집·검토를 반복 가능한 작업으로 만든다

**Files:**
- 추가 후보: `learning/curation/omx/native_review.py`, `learning/curation/omx/test/test_native_review.py`.
- 재사용 검토: `contracts/learning/src/rosy/contracts/learning/omx.py`, `learning/curation/omx/common_episode.py`.
- 기존 export: `learning/curation/omx/lerobot_export.py`는 SIM 기능을 유지한다.

1. 작은 native LeRobot fixture로 actual reader round trip 시험을 만든다. fixture는 영상·관절 순서·단위·gripper·episode 경계를 포함한다.
2. 필수 관측 누락, 길이 불일치, 잘못된 단위, nonfinite action, 미완료 녹화를 거부하는 시험을 만든다.
3. 기존 Episode 계약이 표현할 수 있는 review 항목을 먼저 재사용한다. native mapping을 SIM으로 위장하지 않는다. 새 계약 필드가 필요하면 ADR/스키마를 함께 정한다.
4. 검토 결과는 원본과 분리하고 해시로 연결한다. 재시도·제외는 원본 삭제가 아니다.
5. 입력은 명시적 로컬 dataset 경로로 제한하고 device/ROS/Hub 연결이 없는 검토기를 구현한다.
6. 한 짧은 실제 시연을 저장한 뒤 영상과 action을 다시 읽는다. 강제 중단 뒤 불완전 episode를 완료로 집계하지 않는지 확인한다.

### 한 episode의 운영 순서

과제 선택 → 장치/카메라 확인 → 작업 시작 자세 준비 → 녹화 시작 → 리더 시연 → 녹화 종료 → 실제 팔 상태 확인 → 재생 → 성공/실패/미판정 및 채택/제외 → 다음 episode.
준비 자세로 옮기는 구간은 과제 녹화와 분리한다. 재시도 전 정지·환경을 확인하며 자동 원점 복귀를 넣지 않는다.

검토표 열: `source episode ID | task | source mode | rig revision | outcome | include/exclude | reason | reviewer | source hash`.
이는 작업 기록 양식이며 새로운 public wire schema가 아니다.

## Task 3: 공식 native 학습 경로를 재현한다

**Files:**
- 추가 후보: `learning/training/omx/native_act_job.py`, `learning/training/omx/test/test_native_act_job.py`.
- 문서: `learning/training/omx/README.md`.
- 재사용: `contracts/learning/`의 DatasetManifest/PolicyArtifact, 기존 registry 경계.

1. official CLI만으로 충분하면 wrapper를 추가하지 않고 고정 config와 실행 기록만 제공한다.
2. episode/시연 원본 해시 기준 train/validation/test 중복 거부를 시험한다. 학습용 normalization에 평가 데이터가 들어가지 않게 한다.
3. 한 과제의 검토한 native 데이터로 작은 ACT 학습을 수행하고, 저장한 weights/config/processor/normalization을 새 프로세스에서 로드한다.
   학습 config의 모델 자동 업로드도 고정 버전의 옵션으로 명시적으로 끈다. 데이터와 모델 전송은 모두 Task 4에서만 수행한다.
4. 고정 평가 입력으로 추론 결과·latency·단위·카메라 mapping을 확인한다. native 결과를 기존 SIM artifact로 등록하지 않는다.
5. model PC에서만 학습·독립 평가한다. 이 단계에서 arm 실행·Fleet dispatch·승격을 만들지 않는다.

## Task 4: private Hub 왕복을 별도 작업으로 만든다

**Files:**
- 구현: `learning/registry/policy/hub_sync.py`, `learning/registry/policy/test/test_hub_sync.py`. curation의 업로드 금지 경계를 유지한다.
- 문서: `learning/curation/omx/README.md`.

1. 전송 전 preview, allowlist 파일만 전송, 기존 public 저장소 거부, 토큰 미출력, 실패 시 원본 유지, commit SHA receipt 시험을 만든다.
2. 별도 구현 전에 공식 Hub SDK/CLI가 필요한 preview·upload·revision download를 충족하는지 확인한다. 충족하면 이를 사용하고 wrapper를 만들지 않는다.
3. repo type(dataset/model)·org·private 상태를 실제 readback으로 확인하고 선택한 묶음만 업로드한다. 녹화 종료 hook에 업로드를 넣지 않는다.
4. 반환 commit SHA로 새 디렉터리에 다운로드해 원본 해시 및 실제 LeRobot reader/model loader로 비교한다.
5. 네트워크 중단을 시험한다. 재시도 시 새 녹화를 만들거나 원본을 덮어쓰지 않고 미완료를 성공으로 표시하지 않는다.

Dataset card: 과제·수집 조건·rig/단위·review 기준·split·버전·데이터 권리/공유 범위.
Model card: 학습 dataset SHA·split·seed·config·모델/processor hash·평가 조건·실물 미수용 여부.
카드의 실제 사용권·성공률·장치 수용은 추정해 채우지 않는다.

## Task 5: Pilot 수동 조작과 데이터 연속성을 준비한다

**Files:**
- 기존: `middleware/robot_ui/pilot/drivers/omx_sim.js`, `middleware/robot_ui/pilot/app.js`, `middleware/robot_ui/pilot/screens/arm.js`.
- 추가 후보: `middleware/robot_ui/pilot/drivers/omx_hardware.js` (kind/API 명칭은 계약 단계에서 결정).
- owner: `middleware/devices/omx/adapter/omx_adapter/command_owner.py`, `local_stop.py`.
- 계약: `docs/reference/ROSY API & Protocol Reference.md`, `contracts/foundation/core_common/protocol/`.
- Test: `middleware/robot_ui/pilot/test/test_drivers.py`, `test_shell_assets.py`, `test_pilot_browser.py`, OMX owner/stop suite.

1. D-496의 실측 profile·API 계약을 먼저 마련한다. 이 계획만으로 disabled profile을 활성화하지 않는다.
2. SIM/실물 오접속 거부, leader 소유 중 Pilot 명령 거부, timeout/HOLD/재연결 후 자동 재개 금지를 시험한다.
3. 기존 조그/그리퍼 화면을 재사용하고 실제 source mode·owner·상태 freshness·정지 readback을 표시한다.
4. app registration, `pilot_assets`, service worker SHELL, dev server MIME, CMake 설치, Android 번들 검증을 함께 갱신한다.
5. native와 Pilot 녹화를 서로 다른 source mode로 보존한다. joint/gripper mapping과 sampling의 비교 fixture 통과 전 합치지 않는다.
6. stop·복구·제어권 코드는 safety 변경으로 취급하고 D-430 독립 리뷰와 실제 벤치 readback을 확보한다.

## Task 6: Spaces 검토 화면을 연결한다

공식 viewer로 필요한 검토가 가능하면 새 앱을 만들지 않는다. private dataset 접근 지원을 먼저 확인한다.
부족할 때만 새 Space의 소스 위치·배포 holder를 정하고 authenticated private Gradio reader를 만든다.
필수 화면은 dataset SHA·episode 선택·영상/행동 확인·평가 결과다. 장치 connect/start/stop 기능은 넣지 않는다.
시험은 비인가 접근 거부, secret/client 노출 없음, 고정 revision 표시, Space 재시작 후 동일 revision 읽기다.
유료 compute를 예약하거나 계정/저장소를 자동 생성하지 않는다.

## 검증과 보고

각 구현 단계의 변경은 작업 브랜치에 exact paths로 커밋한 뒤 시험한다.
pytest는 노트북에서 실행하지 않으며 관련 단계의 suite만 remote runner에 전달한다.

```text
python tools/remote/remote_pytest.py --log-dir X:/DevTemp/projects/rosy-platform/<session>/logs/<step> -- <suite-paths> -q -p no:cacheprovider
python test/known_failures.py X:/DevTemp/projects/rosy-platform/<session>/logs/<step>/run-1.txt
```

SOURCE/config parse, remote tests, reader round trip, Hub commit/download, model reload, ROS-SIM, BENCH/DEVICE를 각각 보고한다.
시험 PC가 닿지 않으면 로컬 pytest로 대체하지 않는다. 새 실패는 해결하기 전 착지하지 않는다.
현재 작성한 준비 문서는 링크·경로·diff와 harness로 검사한다. 이것은 위 구현 시험의 실행 증거가 아니다.
착지·push·Hub 전송·배포의 권한과 실제 완료 증거는 각각 구분한다.
