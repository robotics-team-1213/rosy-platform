# OMX 실물 모방학습 준비

## 필요한 파지 구간만 내보내기

[D-833](../../../docs/adr/D-833-native-omx-grasp-segments.md)의 `rosy.omx-native-segments.v1` 선택 JSON은 원본 inspection의 SHA-256, 원본 Episode의 identity·session·cycle, 시작 포함·끝 제외 프레임과 사람의 대상·결과·개입·검수자·근거·분할을 기록한다. 성공을 직접 확인하고 개입이 없는 구간만 학습에 포함한다. 실패·미판정·개입은 제외로 보존한다.

```text
python learning/curation/omx/native_segments.py <intake-root> --report <intake-root>/inspection.json --segments <selection.json> --out <new-segment-splits>
python learning/training/omx/native_cycle.py run --splits <new-segment-splits> --out <new-act-run> --steps 100 --device cpu
```

각 구간은 별도 child Episode다. 원본 state/action·대응 카메라·source clocks를 보존하고 child index/time만 다시 매긴다. 같은 원본·content hash·session·cycle의 후손은 한 분할에만 두며 독립 train/eval이 필요하다. 원본에 session/cycle이 없으면 독립성을 추정하지 않는다. 원본 전체 outcome과 환경 coverage도 구간 결과로 바꾸지 않는다. 출력은 기존 자료와 분리된 새 폴더여야 한다. native 정규화 단위를 SIM rad와 혼합하지 않는다.

`split-receipt.json`은 선택 JSON·원본 hashes·child frame 계보·실제 reader readback·출력 hashes를 묶는다. ACT 실행 전에도 이 기록과 출력 파일을 다시 확인한다. 실제 장치 성공·모델 품질·다른 작업자에 대한 일반화와 데이터 절감 효과는 별도 평가다.

수집 대상은 Fleet PC, 학습·독립 평가는 모델 PC다. HF 조직은 미정이며 로컬 수집의 선행 조건이 아니다.
현재 도구는 host 주소를 고정하지 않고 장치를 시작하거나 기존 ROSY 실물 profile을 활성화하지 않는다.
첫 수집 목표는 D-770의 제한된 자동 교사다. 공식 LeRobot leader recorder는 사람 시연 경로로 유지한다.
자동 교사의 실물 실행 owner·정지·수집 연결과 Pilot 실물 조작은 별도 벤치 수용 대상이다.

## 환경과 녹화

LeRobot 0.4.4 전용 venv를 사용한다. ROS venv에 설치하지 않는다.
직접 의존성 후보는 `deploy/robot/omx/requirements-lerobot-record.txt`다.
CPU 시험 환경과 GPU 학습 환경을 구분하고, 설치 후 `pip check`와 `pip freeze`를 보존한다.
원격 CPU 통합 시험은 torch 2.7.1+cpu / torchvision 0.22.1+cpu / av 15.1.0으로 수행했다.
검토·분할·학습 예제의 영상 backend는 `pyav`다. 이 환경의 기본 TorchCodec 경로는 검증하지 않았으므로 backend를 생략하지 않는다.
Windows의 데이터·HF cache·로그는 X: 세션에, Linux는 선정한 호스트의 명시적 데이터 경로에 둔다.
`HF_HOME`도 그 데이터 드라이브로 설정한다.

1. `deploy/robot/omx/lerobot-record.example.json`을 private 설정 위치로 복사한다.
2. leader/follower ID·by-id 포트, stable camera 경로, 첫 과제, 새 저장 경로를 채운다.
3. `max_relative_target`은 장치와 단위의 실측 제한으로 채운다. 예시에는 값을 넣지 않았다.
4. 설정만 검사한다:

```text
python deploy/robot/omx/record_config.py <record-config.json>
```

검사기는 장치를 열지 않는다. 포트 alias·소유권·보정·토크·정지 경로·실제 카메라 fps는
현장 preflight와 벤치에서 별도로 확인한다. 640×480/30 fps는 제안값이지 측정값이 아니다.
공식 0.4.4 OMX leader는 body에 -100..100 정규화를 사용하므로 follower의
`use_degrees=false`를 유지한다. leader에 `use_degrees`를 추가하지 않는다.
gripper는 0..100이며 ROSY SIM rad와 다르다.

장치 수용·단독 버스 소유 확인 후 운영자가 공식 `lerobot-record --config_path=<record-config.json>`을 실행한다.
설정 검증의 성공만으로 이 명령을 실행하지 않는다. 녹화 종료와 팔 정지는 별개다.
자동 Hub 업로드와 resume은 예시에서 꺼져 있다. 재시도는 새 녹화/episode로 보존한다.

## 실제 reader로 검사하고 검토표 만들기

다음 명령은 로컬 LeRobotDataset을 읽으며 네트워크를 사용하지 않는다.
해당 venv에 LeRobot 0.4.4·PyAV가 필요하다. 장치 identity와 보정값을 추정하지 않는다.

```text
python learning/curation/omx/native_review.py inspect <dataset-root> --repo-id local/omx-pick --body-units normalized_-100_100 --rig-revision <rig-revision> --calibration-revision <calibration-revision> --source-mode leader_native --out <new-review-directory>
```

`inspection.json`은 원본 파일 hash·관절/카메라·frame/episode 수·실제 reader 결과를 담는다.
`decisions.json`은 모든 episode를 `outcome=unknown`, `split=exclude`로 시작한다.
영상을 확인한 사람이 `outcome`을 success/failure/unknown, `split`을 train/eval/exclude로
기록하고 `reviewer`·`reason`을 채운다. episode identity·hash·frame 수는 고치지 않는다.
선택적으로 final test를 `split=test`로 분리할 수 있다. 이때 train/eval/test가 모두 비어 있지 않아야 한다.
출처를 생략한 검사는 `unverified_native`를 기록하며 학습용 분할을 거절한다.
검토 명령은 body 단위를 변환하지 않는다. 선언한 rig/보정은 실물 검증 증거가 아니다.

```text
python learning/curation/omx/native_review.py split <dataset-root> --report <review-directory>/inspection.json --decisions <review-directory>/decisions.json --out <new-split-directory>
```

원본을 다시 검사해 보고서와 비교한다. 유효한 성공 시연만 포함하며 같은 episode의 복제가
train/eval에 나뉘면 거부한다. 공식 LeRobot splitter로 각각의 dataset·통계를 만들고 실제 reader로
재독출한다. 원본을 덮어쓰지 않는다. 실패한 출력은 남으며 재시도는 새 출력 디렉터리를 쓴다.
이 검사는 byte/content 중복을 잡지만 비슷한 장면의 독립성을 판단하지는 못한다. 수집 세션·물체 배치도
운영자가 나눠야 한다. 실물 과제 성공률은 별도의 독립 시행에서 평가한다.

## 자동 교사 데이터의 출처

자동으로 제출한 동작을 사람 리더 시연으로 기록하지 않는다(D-770).
자동 수집은 `--source-mode scripted_teacher --capture-provenance <capture.json>`을 지정한다.
수집기는 종료 시 `rosy.omx-native-capture.v1` manifest에 다음 항목을 보존해야 한다.

- `source_mode=scripted_teacher`, 고정 교사 코드의 `teacher_sha256`.
- `action_semantics=absolute_joint_position_target_normalized`, body/gripper 단위,
  `rig_revision`, `calibration_revision`.
- `files`: 종료된 원본의 `native_review.dataset_files(root)` SHA-256 목록.
- `episodes`: 실제 순서의 `episode_index`, 수집 `session_id`, 왕복/재시도 전체의 `cycle_id`.

manifest와 실제 bytes·단위·revision·episode 순서가 다르면 검사를 거절한다.
session/cycle은 inspection에서 검토표로 복사되며 같은 그룹을 여러 split에 넣을 수 없다.
종료된 분할의 각 출력 hash도 `split-receipt.json`에 보존한다.
분할 중 원본이 바뀌면 성공 receipt를 만들지 않는다.
이 metadata 검사는 수집기의 출처 선언을 묶는 검사이며 물리 실행·정지·과제 성공의 독립 검증이 아니다.
실제 실행 기록이 없는 데이터를 후처리에서 자동 교사로 추정해 채우지 않는다.

## 검토 분할에서 학습·재적재까지 실행

모델 PC의 전용 LeRobot 0.4.4 환경에서 실행한다. 기존 ROS·GPU 작업 환경에 설치하지 않는다.

```text
python learning/training/omx/native_cycle.py run --splits <reviewed-split-directory> --out <new-run-directory> --steps 100 --batch-size 8 --device cpu
```

이 명령은 원본 출처·검토·그룹·분할 출력 hash를 다시 검사하고 공식 ACT CLI를 실행한다.
trainer 종료 뒤 새 Python 프로세스에서 model/preprocessor/postprocessor를 적재하여 eval을 재생한다.
final test는 학습·eval 지표 계산에서 제외한다. 모델은 예시의 작은 ACT 연결 점검 설정이므로
이 설정의 성공을 학습 품질 수용으로 해석하지 않는다.
학습 전후 데이터·모델 hash가 같아야 `cycle-receipt.json`을 발급한다.
실패한 출력·로그는 보존하며 새 경로로 재시도한다. 예전 receipt에 `outputs` hash가 없으면
원본을 다시 검증하고 새 디렉터리에 분할해야 한다.

`evaluation.json`은 native 단위의 관절별 MAE와 train 평균 상수 기준선이다.
실물 과제 성공률은 `null`로 유지한다. 결과는 offline-only이며 장치 실행·승격·업로드를 하지 않는다.

## 학습과 저장된 모델 확인

`learning/training/omx/native-act.example.json`의 dataset을 생성된 `train/`에 연결한다.
eval dataset을 train에 합치지 않는다. 새 output 경로를 지정하고 모델 PC의 전용 환경에서
공식 `lerobot-train --config_path=<train-config.json>`을 사용한다.
이 예시는 CPU 소형 ACT 연결 점검용이며 품질 수용 설정이 아니다. 기본 모델 가중치 다운로드,
W&B, Hub 업로드를 끈다. 학습 뒤 model/config/preprocessor/postprocessor·정규화 파일을 함께
보존하고 새 프로세스에서 재적재한다. 기존 `act_job.py`는 계속 ROSY SIM 연구 전용이다.

## Hub 동기화

수집·검토 모듈은 업로드하지 않는다. 별도 [artifact 동기화 도구](../../registry/policy/hub_sync.py)를 사용한다.
실제 HF org가 정해지면 대상 dataset/model 저장소를 private로 준비한다.
인증은 공식 HF login cache 또는 서버의 `HF_TOKEN`을 사용하며 인자로 토큰을 전달하지 않는다.

```text
python learning/registry/policy/hub_sync.py prepare <artifact-root> --out <new-bundle> --repo-id <org>/<name> --repo-type dataset --file README.md --file meta/info.json --file <each-reviewed-relative-file>
python learning/registry/policy/hub_sync.py upload <new-bundle>
```

`prepare`는 선택 파일만 snapshot하고 manifest를 출력한다. 목록·대상·내용을 검토한 후에만
`upload`를 실행한다. 완전한 LeRobot dataset은 meta/data/videos의 필요한 파일을 전부 선택해야 한다.
도구는 dataset의 완결성을 대신 판단하지 않으며, 부분 파일 전송도 byte receipt만 발급한다.
기존 private 저장소만 허용하고 새 저장소 생성·가시성 변경은 하지 않는다.
commit SHA를 고정해 재다운로드·hash 비교 후 `receipt.json`을 만든다.
중단된 다운로드는 동일 bundle로 재시도한다. `upload.json`이 있으면 같은 commit을 재검증한다.
성공 receipt가 있는 bundle은 다시 전송하지 않는다. 원본·이전 receipt는 보존한다.
`bytes_verified=true`는 형식/품질 검증이 아니다. reader 검증 필드는 false로 남는다.
다운로드한 `readback/`을 다시 `native_review.py inspect`에 넣거나 공식 model loader로 읽는다.
이 별도 보고서를 Hub receipt와 함께 보존해야 왕복 검증이 완료된다.

## Spaces와 Pilot

먼저 [공식 Dataset Visualizer](https://huggingface.co/spaces/lerobot/visualize_dataset)를 사용한다.
private dataset 접근을 실제 계정으로 확인하기 전에는 지원 완료라고 하지 않는다.
접근이 안 되면 데이터를 public으로 바꾸지 않고 로컬 viewer를 사용한다.
Spaces는 원본 저장소나 arm controller가 아니다. HF 계정이 정해지기 전 Space를 만들지 않는다.
Pilot 실물 driver/API와 native owner 전환은 아직 없으며 SIM 화면을 실물에 연결하지 않는다.

검증 현황은 [실행 기록](../../../docs/plans/2026-10-14-omx-imitation-preparation.md)의 구현 상태를 본다.
공식 학습 CLI의 합성 데이터 2 step과 model/preprocessor/postprocessor 재적재까지 원격 검증했다.
실물·실계정 작업의 보류 사유와 재개 조건은 [D-756](../../../docs/adr/D-756-omx-imitation-preparation-and-resumption-gates.md)을 따른다.

## Native 환경 이력 연결

`native_environment.py`는 닫힌 v3 `environment.jsonl` 원본과 수집기가 기록한 episode별
Fleet host Unix ns 시간 창을 데이터 파일 hash·rig·calibration에 묶는다. 별도 출력에 원본
UTF-8 문자열과 SHA-256을 함께 보존하며 원본 데이터와 카메라 서비스를 수정하지 않는다.

```text
python learning/curation/omx/native_review.py seal-environment <dataset-root> --log <closed-environment.jsonl> --windows <episode-windows.json> --rig-revision <rig> --calibration-revision <calibration> --out <new-evidence-directory>
python learning/curation/omx/native_review.py inspect <dataset-root> --repo-id <repo-id> --body-units normalized_-100_100 --rig-revision <rig> --calibration-revision <calibration> --source-mode scripted_teacher --capture-provenance <capture.json> --environment-evidence <new-evidence-directory>/environment.json --out <new-review-directory>
```

`episode-windows.json`은 episode 순서의 배열이다. 각 항목은 `episode_index`, `start_ns`,
`end_ns`(미포함), `run_id`, `profile_sha256`을 가진다. 시간 창은 양수이며 순서대로 겹치지
않아야 하고 해당 run/profile의 기록과 일치해야 한다. 상대 dataset timestamp나 bag 시각을
host 시각으로 추측해 채우지 않는다. 실제 수집기가 이 시간 창을 발행하는 결선은 아직 없다.
run/profile은 카메라 receipt의 값을 보존한다. rig/보정·창 선언은 독립적인 진위 증명이 아니다.

부분 JSONL·중복 JSON 키·비유한 수치·host 시각 역행·다른 run/profile 혼입·파일/rig/보정 불일치를
거부한다. 원본 log는 최대8MiB이며 더 큰 기록은 수집 시 episode 창을 포함하는 닫힌 snapshot을
별도로 보존한다. 기존 파일을 잘라 덮어쓰지 않는다. 실제 reader 검사는 기존 inspect에서 수행한다.

`inspection.json`의 `environment_summary`와 split receipt의 `environment_coverage`를
검토한다. 영상 시각·순번·나이·v3 품질 수치가 확인된 새로운 프레임만 알려진 영상 조건으로
집계한다. 재조회·만료·확인 불가 영상은 UNKNOWN, 창 안에 기록이 없으면 unobserved다.
환경 이력이 없는 기존 보고서는 unrecorded로 분할할 수 있으며 정상 조명으로 간주하지 않는다.
실패/미판정/exclude 시도도 coverage에 남는다. 조건별 수량은 **변경 이벤트 수**로,
프레임 수·시간 비율·에피소드 전체 환경 수용률이 아니다.

분할과 학습 시작·별도 모델 재적재에서 원본 log/hash/요약/coverage를 다시 검증한다.
학습 receipt와 offline 평가에도 coverage를 보존한다. 로그는 상태가 바뀔 때만 기록하므로
연속 readiness·물체 가시성·실제 과제 성공을 입증하지 않는다. 사람 성공 검토와 세션/parent-cycle
독립 분할은 그대로 적용한다. 환경별 실제 성공률 평가는 별도다.


## 자동 교사 raw 수집의 intake와 학습

`collection_pipeline.py prepare <raw-session...> --out <new-dataset> --repo-id <local/id>`는
실물 CLOSED 원본의 hash·teacher/native 종료·RGB·원본 시각·환경을 재검증하고 실제 LeRobot reader로
검사한다. `train <dataset> --decisions <human-review.json> --out <new-run>`은 사람 검토와 독립
session/cycle 분할 뒤 ACT 학습과 별도 process model/pre/post 재적재를 실행한다.
기본 unknown/exclude는 학습할 수 없다. 실패·중단 원본은 보존하며 `--completed-only`는 명시적으로만 사용한다.
rehearsal 데이터는 실물 intake가 거부한다. [Fleet 수집·전송·검토·학습 절차](../../../docs/plans/2026-10-17-omx-next-day-collection.md).
물리 시연 수집과 학습 정책의 실물 평가는 각각 현장 수용 후 진행한다.
