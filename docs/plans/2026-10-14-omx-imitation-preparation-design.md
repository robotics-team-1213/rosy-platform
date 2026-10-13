# OMX 모방학습 우선 준비 설계

상태: 로컬 준비 도구와 원격 합성 데이터·ACT smoke 검증 구현. 실물 연결·실데이터 학습, Hugging Face 저장소 생성·업로드, Spaces 배포는 미실행이다.
사용자 요구: OMX-L 교시·녹화 후 모방학습이 우선이며, Pilot의 OMX-F 수동 조작과 LeRobot/Hugging Face 연동도 필요하다.
기준 소스: `b0f7a1896a7f205cf97a695e403dcaf299180fb6`, 작업 브랜치 `docs/omx-imitation-preparation`.

## 1. 첫 사용 경험

운영자가 과제를 선택하고 장치·카메라를 확인한 뒤, 리더로 시연하고 저장·재시도·성공/실패를 표시한다.
저장한 영상을 즉시 확인하고 유효한 episode를 모아 학습 묶음을 만든다. 학습은 모델 PC에서 실행한다.
Hub 동기화가 실패해도 녹화 원본은 남고, 네트워크 복구 때문에 팔이나 녹화가 자동 재개되지 않는다.

최초 범위는 한 워크셀, 리더/팔로워 한 쌍, 고정 RGB 카메라 한 개, 한 과제다.
카메라 이름은 실제 rig를 확인해 고정하며 위치를 바꾸거나 카메라를 추가하면 새 rig revision으로 기록한다.
리더 교시·녹화를 Pilot 실물 UI 완성에 종속시키지 않는다. 초기에는 공식 LeRobot 도구를 사용한다.
Pilot 실물 조작은 별도 경로로 준비하며 이후 녹화에 같은 review 항목을 사용한다.

## 2. 배치와 권한

```text
워크셀 PC: OMX-L + OMX-F + 카메라
  교시 녹화: LeRobot 단독 owner -> native OMX 데이터 + 로컬 review 기록
  ROSY 조작: Pilot -> OMX 로컬 owner -> ROS 드라이버 -> OMX-F
                 (두 경로의 팔로워 버스 소유는 상호 배타적)
                    |
                검토한 데이터
                    v
비공개 HF Dataset 저장소 <-> 모델 PC 학습·독립 평가
                                  |
                         비공개 HF Model 저장소
                                  |
                     revision 고정·검증 후 별도 배포

HF Spaces: 저장된 episode/평가 결과를 읽는 검토·시연 화면
```

- 모델 PC는 학습·평가를 맡고 팔·ROS 제어권을 갖지 않는다. AI PC나 Spaces를 팔의 실시간 명령 중계로 사용하지 않는다.
- 교시 모드에서 LeRobot이 직접 팔로워를 소유한다. 기존 OMX ROS 드라이버는 같은 포트를 열지 않는다.
- ROSY 모드에서는 기존 OMX owner가 최종 팔 명령을 소유한다. 리더·Pilot·정책은 입력 후보다.
- 모드 전환은 입력 차단 → 장치 정지 확인 → 이전 owner 종료·포트 해제 확인 → 새 owner의 장치/보정/상태 확인 → 사람의 시작 순서다. 현재 자동 전환기가 구현됐다고 간주하지 않는다.
- 녹화 종료/재시도는 물리 정지와 다르다. 교시 중 Pilot 정지를 제공하려면 native runner의 정지 경로와 실제 readback이 먼저 필요하다. 연결되지 않은 정지 버튼을 노출하지 않는다.

## 3. 재사용할 것과 아직 없는 것

| 현재 경로 | 확인한 구현 | 이번 연결에서 필요한 것 |
|---|---|---|
| `deploy/robot/omx/preflight.py` | 영구 포트 식별·접근 가능성·중복 포트 검사 | 프로세스 독점, 토크·정지 상태, 카메라 상태는 별도 검사 |
| `middleware/devices/omx/adapter/omx_adapter/command_owner.py` | owner·fresh state·관절 제한 경계 | 실측 하드웨어 profile과 native 실행 수용 |
| `middleware/robot_ui/pilot/drivers/omx_sim.js` | SIM 전용 조작 | 별도 실물 driver/API. SIM 플래그 우회 금지 |
| `learning/curation/omx/lerobot_export.py` | ROSY SIM 시연을 LeRobot 0.4.4로 export·재독출 | native OMX 데이터는 별도 입력 계약 필요 |
| `learning/training/omx/act_job.py` | SIM export의 ACT 연구·평가 | 실물 native 데이터는 우선 공식 LeRobot 학습 경로 사용 |
| `middleware/robot_execution/local/src/rosy/execution/local/omx_policy.py` | 기본 비활성 SIM 후보 제출 경계 | 실물 배포·trusted capture·권한 발급은 별도 구현 |

새 범용 어댑터나 공통 데이터 형식을 만들지 않는다. LeRobotDataset과 기존 ROSY 계약을 재사용한다.
기존 export 요구사항은 CPU/SIM용이다. 실물 recorder 환경과 GPU trainer 환경에 그대로 설치하지 않는다.
LeRobot 0.4.4를 호환성 조사 기준으로 삼되, 실물 recorder·trainer의 최종 버전은 같은 fixture의 녹화→reader→학습→모델 재적재 시험으로 결정하고 lock한다. 이 문서는 최신 버전으로 업그레이드하지 않는다.

## 4. 데이터가 처음부터 학습에 쓸 수 있도록

| 기록 | 필요한 내용 |
|---|---|
| 장치/환경 | 워크셀, OMX 실물 revision, motor map, 보정 revision, 작업 공간과 대상 조건 |
| 영상 | 카메라 키·실제 identity·rig revision·해상도·fps·프레임 시각과 누락 검사 |
| 상태/행동 | 명시적 joint 순서, 단위, 부호, 정규화, gripper 표현, 관측/명령 시각 |
| episode | 안정 ID, 과제, 입력 출처(리더/Pilot/정책), 시작·종료, 성공/실패/미판정, 제외 사유 |
| 재현 | recorder/trainer 버전과 설정, 원본 파일 해시, source episode ID, 데이터 commit SHA |
| 학습/평가 | train/validation/test episode 목록, seed, 설정, 모델·전처리·정규화 bytes, 독립 평가 |

LeRobot native의 joint 이름과 정규화 값은 ROSY SIM의 ordered rad 목표와 다르다.
공식 0.4.4 leader는 body -100..100 정규화이며 `use_degrees` 설정이 없다. follower는 `use_degrees=false`, gripper는 0..100으로 맞춘다.
이름 변경이나 단순 숫자 복사로 데이터셋을 합치지 않는다. 필요할 때만 명시적 변환을 추가하고 원본을 보존한다.
리더가 요청한 행동, 실제 전송한 행동, 팔로워 관측값을 구분한다. recorder가 어느 값을 action으로 저장하는지 고정 버전으로 확인한다.
타임스탬프가 부족한 원본에 sensor capture 시각을 추정해 채우지 않는다.

성공 여부는 녹화 프로세스 종료 코드나 목표 도달 결과로 자동 채우지 않는다.
미판정·중단·실패 episode는 보존하되 첫 behavior cloning 학습 묶음에는 검토한 유효 시연만 선택한다.
재시도는 원본 덮어쓰기가 아니라 새 episode다. 삭제 대신 제외 사유를 남긴다.
초기 한 과제에서도 물체 위치·방향·시연 시작 자세를 달리하고 세션별 분리를 유지한다.
연속 프레임을 무작위로 train/test에 나누지 않는다. 같은 시연의 재export·복제도 다른 split에 들어가지 않게 한다.
Pilot으로 위치를 맞춘 구간과 실제 과제 시연 구간은 따로 표시한다. 두 입력의 sampling과 action 의미가 검증되기 전에는 섞지 않는다.

## 5. Hugging Face Hub와 Spaces

### Hub: 원본 검토 뒤 동기화

- Dataset 저장소: `<org>/omx-<task>-<rig-revision>` 제안. Model 저장소: `<org>/omx-<task>-act-<run-id>` 제안. 실제 org·이름은 생성 전에 확정한다.
- 초기 가시성은 private. 녹화는 명시적으로 `dataset.push_to_hub=false`, `dataset.private=true`를 사용한다. 0.4.4의 기본값은 자동 업로드 켜짐·private 꺼짐이다.
- 업로드 단계는 계정·대상·기존 저장소의 실제 private 상태·파일 목록을 표시한다. private 요청 인자만으로 기존 공개 저장소가 비공개라고 판단하지 않는다.
- 동기화 대상은 검토한 dataset/model 묶음만이다. `private/`, 토큰, host inventory, 원격 접속 정보, 임의 세션 전체를 올리지 않는다. 실제 장치 identity와 공유용 rig ID를 분리한다.
- 업로드 성공 후 repo ID·repo type·commit SHA·파일 해시를 기록하고, 새 디렉터리로 해당 revision을 받아 같은 LeRobot reader로 episode/frame/영상·행동을 다시 읽는다.
- Model에는 weights뿐 아니라 config, 전처리·정규화, 데이터 revision, split, 평가, 사용 제한을 포함한다. 공식 loader 재적재를 확인한다. 업로드가 ROSY 배포나 활성화는 아니다.
- 녹화 PC에 Hub write token을 상시 요구하지 않는다. 동기화 작업에 필요한 범위로 제한하고 로그·명령줄·브라우저에 원문을 넣지 않는다. 다운로드용 권한은 분리한다.

### Spaces: 저장된 결과를 보기 편하게

공식 [LeRobot Dataset Visualizer](https://huggingface.co/spaces/lerobot/visualize_dataset)를 먼저 평가한다.
우리 private 데이터 접근을 지원하는지 실제 계정으로 확인하기 전에는 연동 완료라고 하지 않는다. 접근이 안 된다고 데이터를 공개로 바꾸지 않는다.
필요하면 인증된 private Gradio Space에서 데이터 선택, episode 영상/관절·행동 비교, 성공·제외 표시, 모델별 독립 평가를 제공한다.
첫 Space는 읽기 전용이다. review 원장은 로컬/모델 PC에 보존하고 업로드 revision과 함께 표시한다.
Secrets는 서버에서만 사용한다. private 데이터 토큰을 가진 공개 Space가 영상을 대신 공개하지 않게 실제 접근 권한도 검증한다.
Space의 임시 디스크를 원본 저장소로 삼지 않고 재시작 후 고정 Hub revision에서 다시 읽게 한다.
Spaces 비용·계정 권한은 생성 시 확인한다. 유료 자원·공개 배포·실물 연결은 이번 준비 범위가 아니다.

## 6. 준비 순서와 완료 판정

1. **P0 구성 고정:** 장치/카메라 inventory, 첫 과제와 성공 정의, native 데이터 샘플, recorder/trainer 환경 lock을 준비한다. 실물 미확인 값은 빈칸으로 남긴다.
2. **P1 녹화 반복:** 짧은 시연 → 재생 확인 → 성공/실패/재시도 → 새 episode 보존을 실제로 반복한다. 이미지 누락·중단 복구·Hub 없는 녹화를 확인한다.
3. **P2 학습·Hub:** 검토한 episode를 분리해 ACT smoke → 저장/재적재 → 독립 평가, private 업로드 → commit 고정 재다운로드/reader 검증을 수행한다.
4. **P3 Pilot 실물 조작:** 별도 API/driver, 제어권 전환, 조그·그리퍼·정지 readback을 검증한다. P1/P2와 병행 준비하되 데이터 혼합은 mapping 이후다.
5. **P4 검토 화면·정책:** Spaces reader를 연결하고, 정책의 실제 OMX 실행은 실물 owner/보정/정지 수용 후 별도 단계로 수행한다.

첫 완료 기준은 '모델이 생김'이 아니라 **다른 사람이 같은 설정으로 시연을 수집하고, 검토한 데이터 revision에서 모델을 재학습·재적재할 수 있음**이다.
과제 성공률은 독립 실물 시행의 성공/전체 횟수·조건으로 별도 보고한다. 녹화량이나 학습 loss만으로 수용하지 않는다.

## 7. 계약 관계와 범위

| 계약 | 이번 준비안의 관계 |
|---|---|
| D-299 (Proposed), D-399 | native 녹화의 단독 버스 소유와 운영 owner 분리 유지 |
| D-427 | middleware/operations/learning 책임 유지. 학습 환경을 ROS 장치 이미지에 추가하지 않음 |
| D-429 | UI·학습이 장치 binding을 우회하지 않음. source 경로로 실행 host를 정하지 않음 |
| D-430 | safety를 모델 외부에 유지. 모델/HF 상태로 HOLD·정지를 해제하지 않음 |
| D-449 | ROSY artifact/provenance 경계 유지. Hub commit은 승격/실행 권한이 아님 |
| D-496 (Proposed) | 실물 profile/API/수용 미완료를 유지. SIM profile 재사용 금지 |

이 문서는 구현 요구사항이다. 새로운 API·권한·모드 계약을 확정하거나 Proposed ADR을 승인하지 않는다.
native runner 제어 API, 실물 Pilot API, review schema를 구현할 때 해당 ADR·SRS·API reference와 생산자/소비자 시험을 먼저 정한다.

## 출처 (2026-10-14 확인)

- [LeRobot OMX](https://huggingface.co/docs/lerobot/en/omx): 공식 leader/follower 경로.
- [0.4.4 recorder](https://github.com/huggingface/lerobot/blob/v0.4.4/src/lerobot/scripts/lerobot_record.py): 녹화 설정 및 업로드 기본값.
- [0.4.4 OMX follower config](https://github.com/huggingface/lerobot/blob/v0.4.4/src/lerobot/robots/omx_follower/config_omx_follower.py): 단위 옵션과 상대 목표 제한.
- [Hub upload](https://huggingface.co/docs/huggingface_hub/guides/upload), [revision download](https://huggingface.co/docs/huggingface_hub/guides/download): 묶음 업로드와 revision 재독출.
- [Spaces](https://huggingface.co/docs/hub/spaces-overview), [Space 관리](https://huggingface.co/docs/huggingface_hub/guides/manage-spaces): 검토 앱 배포·인증·Secrets.
- [실행 준비 목록](2026-10-14-omx-imitation-preparation.md).
