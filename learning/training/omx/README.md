# OMX ACT 오프라인 학습 연구

기존 Learning 앱의 `/learning/omx`에 데이터 폴더 업로드와 ACT/SAC 오프라인 학습 실행·중단·진행·결과·모델 다운로드가 추가되었다. `experiment_center.py`는 별도 호스트 설정으로만 활성화한다. 실제 로봇이 새 경험을 공급하는 온라인 HIL-SERL 연결은 아직 없다. 합성 스모크의 수치 결과를 집기 성공률로 사용하지 않는다.

입력 폴더는 `dataset.json` (`rosy.omx.experiment-dataset/1`)과 해시가 선언된 평면 `.npz` 파일로 구성한다. 프로필은 `experiment_profile.py`, 배열과 세션/원본 분할은 `experiment_dataset.py`에서 검증한다. 팔 수·카메라 수·배치가 입력 프로필에 포함되며 정책 카메라는 모델에 명시적으로 64×64로 축소한다. 카메라의 실제 시각 동기화·교정·장치 접근은 이 파일 형식 검증과 별도다.

봉인된 native 분할은 `experiment_native.convert_native(splits, output, profile=...)`로 ACT 자료로 변환할 수 있다. 실제 source session/cycle·rig·calibration·프레임 지문과 입력 프로필이 맞아야 한다. native 경로는 단일 팔 6관절(`omx_follower`) 또는 `arm_a`·`arm_b` 순서의 두 팔 12관절(`bi_omx_follower`)을 받으며, 프로필의 팔 id와 순서를 실제 reader의 관절 배치와 대조한다. 카메라는 원본 metadata의 정확한 입력 키·영상 크기와 대조하며 top/wrist 외 추가 키도 보존한다. 역할·배치·용도를 추정하거나 과거 키를 별칭으로 바꾸지 않고 wrist 역할은 팔 소속을 요구한다. 생성한 `native-split-receipt.json`·`conversion-receipt.json`도 폴더 업로드에 포함한다. 보상·개입·다음 상태를 추정하지 않으므로 이 변환 결과를 HIL 전이 자료로 사용하지 않는다.

화면의 ‘등록된 검수 시연’에서 생산 intake와 팔·카메라 프로필 JSON을 선택하면 `experiment_export.py`가 기존 검토·분할·변환을 별도 영속 작업으로 실행한다. 완료 자료는 검증 후 학습 데이터 목록에 자동 등록된다. 재접속·중단은 기존 작업 경로를 사용하며 변환 자체를 ACT 학습이나 모델 산출물로 표시하지 않는다. 기본 unknown/exclude와 fixture_only는 거절한다. ‘검수 열기’에서 정확한 원본 프레임과 판정을 보고 별도 불변 검토 버전을 저장할 수 있다. 변환 시 명시 선택한 검토 버전은 canonical 결정 해시·원본 revision에 묶이고, 원본 판정 파일을 바꾸지 않는다. 원본 raw-session 준비는 이 화면에 아직 없다. 두 팔 준비 자료는 프로필이 `arm_a`·`arm_b`를 그 순서로 선언할 때만 받는다. 실제 합성 영상 reader는 검증했지만 수용 가능한 생산 검토 자료의 전체 변환은 미실행이다.

`experiment_smoke.py --out <새 외부 폴더> --arms 2 --cameras 3`은 수치 학습 시험 전용 합성 자료를 만든다. 앱에서 폴더를 올린 후 방법과 학습 단계를 선택한다. 결과 ZIP에는 weights뿐 아니라 입력 프로필·정규화·평가가 포함된다. 기존 native LeRobot 폴더는 이 NPZ 형식으로 자동 변환되지 않는다.

공식 native recorder/자동 교사 데이터는 [native 실행 안내](../../curation/omx/README.md)의
`native_cycle.py` 경로를 사용한다. byte-bound 검토 분할 → 공식 ACT CLI → 별도 프로세스
model/processor 재적재 → eval 재생을 연결한다. 아래 `act_job.py`의 SIM rad 계약과 혼합하지 않는다.

`act_job.py`는 기존 LeRobot 0.4.4 export의 원본 OMX 시연을 검증하고,
episode 단위 train/eval → ACT 학습 → weights 저장·재독출 → offline 평가 →
공통 DatasetManifest/PolicyArtifact까지 연결한다. 분리된 CPU 환경에서 실행하며
장치나 ROS에 연결하지 않는다. 승격/READY/dispatch를 만들지 않는다.

`deploy/robot/omx/requirements-lerobot-export.txt`의 Python 3.12 CPU 환경을
사용한다. source checkout의 adapter와 foundation을 PYTHONPATH에 둔다.

```text
python learning/training/omx/act_job.py
  --train-export <LeRobot-episode-a-root> <LeRobot-episode-b-root>
  --eval-export <independent-episode-root>
  --out <new-artifact-directory> --steps 40 --seed 42750 --n-action-steps 4
```


Windows 출력은 X에 둔다. 새 출력만 허용하며 실패 시 state/error와 부분 산출물을
보존한다. 학습 중단 시 재개를 지원하지 않는 초기 연구 CLI이므로 새 run 경로를
사용한다. perception 반복 job·장치 배포 경로와 구분한다.

완료/clock/단위/관절·카메라·limits·world/calibration과 원본 provenance를 검증한다.
원래 export를 snapshot해 실제 Parquet/MP4 reader로 학습하고 파일 SHA를
DatasetManifest에 포함한다. train-only 정규화를 사용하며 RGB source/model shape,
resize/scale, 실제 source duration을 기록한다. chunk는 episode 경계를 넘지 않는다.

현재 설정: ACT ResNet18, dim64/head4/encoder1/decoder1, chunk4, VAE off,
pretrained weights 없음, CPU4threads, batch8, AdamW lr0.001.
모든 policy parameter를 하나의 optimizer group으로 학습한다. 저장 ACTConfig의
optimizer_lr/optimizer_lr_backbone은 둘 다 0.001, weight_decay는 0.0001이며
offline-report는 실제 optimizer parameter group의 lr/weight_decay/betas/eps와
실행 옵션, gradient clip norm 1.0을 기록한다. 기존 artifact는 덮어쓰지 않는다.
영상 정책을 학습하지만 task/duration 정책을 학습했다고 주장하지 않는다. HOLD/reset/stale는 선언이며
실제 owner 집행은 후속이다. camera_profile은 null을 유지하고 rig fingerprint는
별도로 보존한다.

고정 episode에서 rad MAE·상수 목표 평균 기준·joint limit·목표 다양성을 평가한다.
다양성은 0.001rad bin 최소 3 target cluster의 연구 기준이다. 실물 safety/품질
표준이 아니며 통과해도 offline_only다. independent task success·owner contract·
SIM 실행이 없으면 L0를 등록하지 않는다.

실행 증거: [실제 시연 ACT 학습](../../../docs/validation/omx-act-offline-2026-10-04.md).

## 모델 bytes와 추론 관측 binding

`act_inference.ACTInference(root, policy_revision)`는 pinned PolicyArtifact의 실제
config/weight/정규화 bytes를 검증해 메모리로 snapshot한다. safetensors byte loader를
사용하며 모델 구성 후 mutable 경로를 다시 읽지 않는다. 지원 범위는 CPU/LeRobot0.4.4,
front RGB 한 개와 OMX SIM 절대 관절 목표이다. pretrained 다운로드/temporal ensemble는 없다.

`InferenceObservation`은 ordered joint rad, sequence/수신 시각, camera identity/calibration/
CHW shape와 **HWC 순서의 interleaved RGB uint8 bytes**를 보존한다. 가변 byte buffer는 복사한다.
모든 수신/생성 시각은 owner와 같은 monotonic clock domain이어야 한다. reset은 추론 큐만
지우며 owner HOLD나 local stop을 해제하지 않는다. clock rollback anchor는 reset으로 지우지 않는다.

ACT의 `n_action_steps` 큐를 유지하고, queued action은 **최초 소비 관측과 최초 생성 시각**을
그대로 반환한다. 현재 호출에 새 이미지가 들어와도 큐 값의 관측이라고 주장하지 않는다.
`InferenceResult.candidate_fields()`는 기존 local 후보 필드이며 public wire/실행 권한이 아니다.
호출자가 실제 owner에서 원래 sequence/time/camera frame을 대조하게 해야 한다.
후보는 원frame SHA와 `camera_received_at_ns`를 함께 전달해 동일 RGB의 다른 capture와
구별한다. 큐 출력도 원 수신 시각을 보존한다. owner의 guarded metadata capture와 실제
immutable RGB snapshot을 맞춰야 하며 timestamp 필드 자체가 capture 신뢰를 부여하지 않는다.
공통 `rosy.contracts.learning.inference`는 기존 InferenceObservation/InferenceResult
DTO를 소유하며 이 모듈은 같은 타입을 재수출한다. owner의 명시적
`capture_inference_input(rgb, camera)`는 guarded camera와 원 metadata·RGB의
SHA·크기를 대조하고, 기존 잠금 안에서 원 lease·관절 입력을 고정한다.
학습 쪽 `act_owner_capture.infer_captured`는 이 DTO와 같은 caller clock·policy
revision만 받아 결과를 반환하며 안전 owner 타입을 import하지 않는다.
현재 isolated caller 시험이 잠금 밖 추론과 lease 재검사·PolicyCandidate 구성을
연결한다. 원 관측 재전달·큐 시각 갱신은 없다. 실제 제출·최종 판단은 기존
`session.submit`에 맡긴다. 기본 runtime·명령·issuer·자동 scheduler·HOLD 해제는 없다.
실제 trusted capture/issuer·승인된 모델의 ROS 프로세스 결선은 여전히 별도다.

기본 n_action_steps=4는 유지한다. `--n-action-steps 1`은 chunk_size4를 유지하면서
매 관측의 첫 행동만 반환하는 별도 config/평가/PolicyArtifact를 만든다. 허용 값은 1..4이다.
설정을 바꾸어 기존 artifact의 revision이나 거절 이력을 덮어쓰지 않는다.

`act_inference_replay.py`는 bound Dataset 파일에 포함된 실제 LeRobot 평가 reader로
모델의 입력/행동/큐 provenance·latency를 새 X artifact에 보존하고 기존 offline metrics를
재현한다. 원래 sim capture/state/wall 시계는 별도 필드로 보존한다.
재생 입력 수신 시각을 원래 센서 수신 시각이라고 표시하지 않는다.

```text
python learning/training/omx/act_inference_replay.py
  --policy-root <ACT-run> --dataset-root <bound-dataset-root>
  --eval-export <bound-reader-input> --policy-revision <canonical-hash>
  --out <new-directory-on-X>
```

이는 numerical/replay 증거이다. 모델 pin은 integrity이며 승격/설치 trust가 아니다.
owner dispatch·독립 SIM 과제·물리 수용을 증명하지 않는다.
고정 seed/data의 4행동/1행동 실제 비교와 남은 품질 거절은
[추론 binding 검증](../../../docs/validation/act-inference-binding-2026-10-04.md)에 기록했다.

## 실행 중 경험을 받는 SAC

`experiment_online.py --request <고정 요청 JSON> --out <새 출력 경로>`는 `method=hilserl`의 호스트 지속 학습기다. 앱의 `/online-run`이 실행하고 `/experience`가 등록 자료만 영속 큐에 넣는다. 모델·optimizer·초기 train 관측 정규화는 프로세스 내에서 유지하며 새 자료마다 지정한 steps만큼 갱신한다. 초기 eval은 고정하고 입력 전체의 원본/세션 분할을 재검증한다. 프로필 schema 2의 팔별 `action_limits`가 고정 행동 매핑이며 하드웨어 실행 승인은 아니다.

`versions/000001/`부터 완료 버전의 weights·프로필·정규화·평가·결과를 저장한다. 상위 progress는 waiting_for_experience/training·누적 step·소비 입력·거절 사유를 제공한다. 큐 예약은 앱 DB에 남아 서버 재접속 시 복구되며, 종료된 worker의 모델/optimizer 자동 재시작은 지원하지 않는다. 새 작업으로 시작해야 한다. 정책은 자동 활성화하지 않는다. 현장 actor의 관측·실행 행동·보상·개입을 생성하는 경로는 별도 구현 대상이다.

두 PC의 실제 CPU 연속 업데이트·HTTP·중단/재시작 증거와 미검증 범위는 [학습센터 검증](../../../docs/validation/omx-learning-center-2026-10-21/result.md)에 기록한다.

## 현장 PC의 봉인 자료 전달

`experiment_transfer.py`는 완성된 `dataset.json`·NPZ 폴더를 기존 학습센터 upload/publish로 전달한다. 운영자가 지정한 HTTPS origin에 직접 연결하고 기본 인증서·호스트 검증을 사용한다. HTTP는 bench의 명시적 포트가 있는 loopback 터널만 허용한다. 인증 모드에서는 기존 manage 세션 쿠키를 `ROSY_LEARNING_SESSION_COOKIE` 환경으로 전달하며 쿠키·CSRF 토큰은 체크포인트에 저장하지 않는다. URL 자격 증명·하위 경로·query·fragment·프록시·리디렉션을 허용하지 않는다. 중앙 인증 운영 서버는 허용된 HTTPS origin을 사용해야 한다.

```bash
python learning/training/omx/experiment_transfer.py /data/sealed-batch \
  --origin http://127.0.0.1:8769 --name 'Recorded batch' \
  --checkpoint /data/transfers/model-batch.json
```

체크포인트는 원본 폴더·각 파일의 크기/해시·대상 origin·표시 이름·선택한 작업을 upload/request UUID에 결속한다. 중단 후 같은 명령과 체크포인트를 재사용한다. 모든 조각을 원래 offset부터 재전송해 서버의 동일 바이트 확인을 받으므로 대용량 자료의 재시도는 시간이 걸린다. 원본이나 대상을 바꿔 같은 체크포인트를 쓰면 네트워크 전송 전에 거절한다. Model과 AI에는 별도 체크포인트를 쓴다.

선택적 `--run-id <running-continuous-run-uuid>`는 게시된 자료를 기존 experience 큐에 추가한다. 서버가 전체 전이·프로필·팔별 신호·행동 범위를 검증하며 이미 받은 revision은 중복 학습하지 않는다. ACK는 등록/큐 수신이며 실제 worker 소비는 앱의 queued/consumed/rejected에서 확인한다. 전달기는 시범의 보상·개입·다음 상태를 생성하지 않고 실제 팔을 움직이거나 정책을 활성화하지 않는다. 원본 검수·수집·초기화 연결은 별도다.

현장 Linux/Python 3.14.4에서 전달기와 `experiment_io.py`·`experiment_profile.py` 세 파일로 Model PC 직결 SSH 터널을 검증했다. 새 프로세스에서 같은 체크포인트를 재사용하고 실제 큐 소비·SAC 갱신까지 확인했다. 경로·정확한 커밋·합성 자료의 제한은 `docs/validation/omx-learning-center-2026-10-21/result.md`에 있다. 터널은 시험 후 종료했으며 서비스 자동 기동이나 현장→AI 인증 설정을 새로 설치한 것은 아니다.

## 저장 가능한 팔·카메라 입력 프로필

학습센터의 프로필 편집기로 팔/관절 순서·단위·행동 범위와 카메라 identity·배치·소속·용도를 입력한다. 서버는 새 불변 버전을 저장하고 부모 버전·작성 신원·지문을 보존한다. `GET /center/profiles`, `POST /center/profile`, `GET /center/profile/<id>`는 기존 OMX center API 접두사와 권한을 사용한다. 마지막 경로는 지문을 보존하는 원래 프로필 JSON을 내려준다.

`/run`과 `/online-run`의 선택적 `profile_id`는 데이터의 전체 프로필과 의미가 같아야 한다. 저장 선택은 작업의 `selected_profile={id,revision}`에 남는다. 이름·과제·팔/카메라 순서·배치 등이 다르면 실행 전에 거절한다. 기존 요청은 저장 프로필 없이 계속 동작한다. 프로필 저장은 장치 연결·기하 교정·협동 동작·정책 활성화를 뜻하지 않는다.

## 팔별 개별 정책과 공동 정책

`mode=independent`이고 팔이 여러 개면 화면에서 대상 팔을 선택한다. `/run`, `/online-run` 및 고정 worker 요청의 `arm_id`가 필수다. 한 작업은 해당 팔 정책을 학습하며 다른 팔은 별도 작업으로 시작한다. 기존 호스트의 한 작업 슬롯을 지킨다. 공동 모드는 `arm_id`를 받지 않고 전체 관절 벡터를 학습한다.

개별 입력 view는 대상 팔의 state/action/next_state 열, 소속 없는 카메라와 대상 팔 카메라, 명시된 대상 팔 신호를 사용한다. 원본 데이터·분할·파일 해시는 바꾸지 않는다. `dataset_revision`은 원래 전체 자료이고 `profile_revision`은 실제 모델 입력이다. request/result의 `training_scope`가 `mode,arm_ids,source_profile_revision,action_indices,camera_keys`를 기록한다. ZIP의 profile·정규화·모델 형상도 실제 선택 팔에 대응하며 지속 학습은 처음 범위와 정규화를 유지한다. 비교 화면은 같은 원본·대상 팔의 결과만 묶는다.

독립 전이는 `schema=rosy.omx.experiment-dataset/2`와 `profile.mode=independent`를 사용한다. JSON의 기존 profile/source/episodes 필드는 유지하며 NPZ에 전체 state/action/카메라와 next_state/next 카메라를 기록한다. 각 팔에는 `arms.<id>.reward`(유한 float[N]), `arms.<id>.terminated`, `arms.<id>.truncated`, `arms.<id>.is_intervention`(bool[N])이 모두 필요하다. 같은 팔의 종료/시간 제한 동시 참은 거절한다. 공동 reward·교정을 팔별 신호로 복사하지 않는다. ACT의 검토 시범은 전이 없는 base 배열도 허용하지만 robot_rollout의 개별 ACT와 개별 SAC에는 실제 팔별 전이가 필요하다. 기존 schema 1 공동/단일 팔 자료는 유지한다.

## Native OMX ACT 준비

등록 native 시연의 검토 프리뷰는 `experiment_preview.frame`(단일 JPEG)과 `frame_set`(같은 행의 복수 카메라 JSON)을 사용한다. 공식 reader의 episode/frame/index와 원본 지문을 전후 검사하며 frame_set은 기록 timestamp와 frame/fps도 확인한다. 최대 8개 카메라·16M pixels·8MiB JPEG이고 요청한 카메라가 없으면 대체하지 않는다. 시각은 기록 행 기준이며 실제 센서 촬영 동기화와 별도다. 원본과 검토 판정은 프리뷰로 변경되지 않는다.

`native-act.example.json`은 공식 LeRobot 0.4.4 CPU smoke 설정이다. [실행 안내](../../curation/omx/README.md)에 따라 검토한 train 경로를 채운다. SIM rad 데이터와 섞지 않는다. 실제 GPU 학습·독립 평가는 별도다.

`native_cycle.py`는 split receipt의 환경 원본·hash·episode 창·요약·split coverage도 시작과
별도 모델 재적재에서 재검증한다. cycle receipt와 offline evaluation에 환경 coverage를
보존한다. 이 값은 sparse 변경 이벤트 집계이며 에피소드 전체 환경 수용률이나 환경별 과제
성공률이 아니다. 환경 이력이 없는 기존 receipt는 unrecorded로 표시한다.

## 학습센터의 현장 owner 상태 관찰

Center 설정의 선택형 `owner_status`는 기존 Fleet viewer GET만 사용한다.
브라우저는 서버가 허용한 작업대를 선택하고 최근 owner 상태·관측 순번·조회 완료
시각을 확인한다. 조회 실패/미설정/화면 이탈 시 이전 확인 값을 지운다.
owner의 `ready`는 실물 학습 제어 가능 판정이 아니며, 이 응답에는 원본 feedback의
시각·교정·세대나 물리 정지 증거가 없다. 기존 학습 시작/중단은 별도다.

기존 `{schema, root, python}` 설정에 다음 항목을 선택적으로 추가한다:

```json
{"owner_status": {
  "origin": "http://127.0.0.1:18770",
  "token_env": "ROSY_FLEET_VIEWER_TOKEN",
  "targets": {"workcell-id": "arm-id"},
  "timeout_s": 1.0
}}
```

origin은 기존 승인된 Fleet 연결의 numeric loopback HTTP tunnel이고 URL 자격 증명,
path·query·proxy·redirect는 허용하지 않는다. viewer 자격은 서버 환경변수에만 두고
설정 JSON/브라우저/로그에는 넣지 않는다. 토큰이나 SSH 권한을 이 기능이 만들지 않는다.
1~32개의 중복 없는 target, 양수 3초 이하 조회 제한, 64KiB 응답 한도를 적용한다.
HTTP 응답 identity/schema를 확인하고 실제 상태가 없으면 unavailable로 표시한다.
수신 시각은 학습 서버의 조회 완료 시각이며 센서 capture 시각이 아니다.
읽기 경로는 `experiment_owner_status.py`와 기존 authenticated review-app
`GET /api/learning/omx/center/owner-status/{workcell_id}`다.
실물 장치·owner 개입/복귀·제어권·보상/reset 연결을 이 설정으로 활성화하지 않는다.

## 학습 결과를 L0 정책으로 등록 (D-793)

`native_cycle.py`의 `cycle-receipt.json`에는 `policy_revision`(모델 파일 목록의 해시), `rig_revision`, `calibration_revision`이 남는다. `register_policy.py`는 이 영수증으로 Fleet에 L0 제안을 올린다. 근거는 영수증의 SHA-256이다. L0은 실행 권한이 아니며 관리자가 `/console/policy`에서 결정한다.

```bash
python learning/training/omx/register_policy.py --cycle <run> --fleet https://<site>:8443 --workcell <id> --dry-run
ROSY_FLEET_TOKEN=<policy-admin token> python learning/training/omx/register_policy.py --cycle <run> --fleet https://<site>:8443 --workcell <id> --confirm
```
