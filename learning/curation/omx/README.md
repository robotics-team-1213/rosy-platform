# OMX 실물 모방학습 준비

## 필요한 파지 구간만 검수·학습하기

`/learning/omx`에서 등록한 intake의 「파지 구간 검수」를 연다. 원본 카메라 프레임을 확인하고 시작(포함)·끝(제외), 대상 물체, 실제 관찰 결과, 개입 여부, 검수자·근거와 분할을 기록한다. 저장은 review DB에 새 검수 revision을 추가하고 원본 `decisions.json`을 유지한다. 프로젝트 계정에서는 manage 권한이 필요하고 인증된 사용자를 검수자로 기록한다. 원본 확인에는 모델 PC의 LeRobot 0.4.4 환경이 필요하다.

1. 「원본을 보고 구간 선택」에서 Episode·카메라·프레임을 선택하고 프레임을 확인한다. 시작은 포함, 끝은 제외한다. `[2, 6)`은 2~5번 프레임이다.
2. 「구간 결과 확인」에서 대상·관찰 근거·결과·개입·분할을 입력한 뒤 「구간 추가」를 누른다. 입력 중인 폼은 구간 추가 전에는 저장 대상이 아니다.
3. 「구간 저장·내려받기」에서 저장 상태와 분할별 개수를 확인한다. 저장 중 추가·삭제한 구간은 다음 저장 대상으로 남으며, 미저장 구간이 있으면 JSON 내려받기가 막힌다. 저장 실패·버전 충돌은 현재 편집을 유지한다. 다른 검수자의 최신 revision을 다시 읽으려면 필요한 미저장 내용을 확인한 뒤 「다시 확인」에서 버리기를 명시한다.

「원본 전체 시연 상태·메타데이터」는 원본 결과다. 구간 검수로 원본의 미판정 결과를 성공으로 바꾸지 않는다. 화면에 저장된 JSON이 있어도 실제 내보내기에는 독립 학습·평가 구간과 원본 검증이 필요하다. 미저장 이탈 경고는 제공하지만 탭 강제 종료 후 임시 편집 복구는 제공하지 않는다.

선택 JSON을 내려받은 뒤 같은 모델 PC의 전용 venv에서 실행한다. 출력은 모두 기존 자료와 분리된 새 폴더여야 한다.

```text
python learning/curation/omx/native_segments.py <intake-root> --report <intake-root>/inspection.json --segments <downloaded-segments.json> --out <new-segment-splits>
python learning/training/omx/native_cycle.py run --splits <new-segment-splits> --out <new-act-run> --steps 100 --device cpu
```

각 파지 구간은 별도 child Episode다. 원본 state/action·대응 카메라·source clocks를 보존하고 child index/time만 다시 매긴다. 성공을 직접 확인했고 개입이 없는 구간만 학습에 넣는다. 실패·미판정·개입은 제외로 보존한다. 같은 원본·content hash·session·cycle의 후손은 한 분할에만 둔다. 독립 train/eval이 필요하며 test를 선택하면 test도 비어 있으면 안 된다. native 정규화 단위를 SIM rad와 혼합하지 않는다.

Legacy `leader_native` inspection에 session/cycle이 선언되지 않았으면 session 독립성을 보장할 수 없다. 누락된 계보를 추정하지 않는다. Production `scripted_teacher` intake는 원본 bytes에 묶인 session/cycle을 계속 검증한다.

`split-receipt.json`은 원본 report/hash, 구간 선택, child→원본 frame 계보, readback과 출력 hashes를 묶는다. 원본 전체의 outcome은 구간 outcome과 별개이고, 환경 coverage도 원본 parent Episode 범위다. 다른 작업자·카메라·물체·장비에서 재사용 가능하다는 뜻은 아니다. [D-833](../../../docs/adr/D-833-native-omx-grasp-segments.md)과 [구현 계획](../../../docs/plans/2026-10-21-omx-native-grasp-segments.md)을 따른다.

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
Windows의 데이터·HF cache·로그는 스크래치 세션에, Linux는 선정한 호스트의 명시적 데이터 경로에 둔다.
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

native reader는 `omx_follower`의 6관절과 `bi_omx_follower`의 12관절을 지원한다.
양팔은 `arm_a.*` 6개 다음 `arm_b.*` 6개의 동일한 관절 순서를 사용해야 한다.
state/action 이름·개수·순서가 robot_type과 다르면 거절하며 분할 출력도 원래 robot_type을 보존한다.
실제 SDK의 양팔 합성 연결 범위와 한계는 [검증 기록](../../../docs/validation/omx-bimanual-native-cycle-2026-10-23/result.md)을 따른다.

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

`--calibration <follower.json>`(양팔은 `arm_a=<a.json> arm_b=<b.json>`)을 주면 [D-854](../../../docs/adr/D-854-omx-policy-runner-and-action-space.md)
행동 단위 선언 `action_space`(`lerobot_norm_v1`, omx_follower 모터 순서, 보정 range digest)를 `inspection.json`에 남긴다.
정규화 데이터만 선언할 수 있고, 분할과 구간 선택은 선언을 그대로 다시 확인한다. 선언 없는 보고서는 지금처럼 동작한다.
VLA 학습 입구에서 선언을 필수로 하는 일은 D-854 정책 실행기 단계에서 한다. SIM rad 데이터셋은 변환하지 않는다.

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
train/eval의 관절 layout이 같아야 하며 결과의 `joint_names`와 MAE 배열은 해당 6/12관절 순서다.
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
일반 dataset의 완결성은 별도로 검사하며 부분 파일 전송은 byte receipt만 발급한다.
`lerobot_export.py`의 OMX export는 `rosy_export.json`, 원본 `rosy_provenance/`, SIM이면
`rosy_sim_truth/`까지 전체 파일을 선택해야 한다. 누락된 원본 증거는 전송 전에 거부한다.
파일이 많으면 검토한 상대 POSIX 경로 문자열의 JSON 배열을 `--file-list <files.json>`으로
전달한다(`--file`과 함께 사용하지 않는다). 이 목록은 export 밖에 보존한다.
기존 private 저장소만 허용하고 새 저장소 생성·가시성 변경은 하지 않는다.
commit SHA를 고정해 재다운로드·hash 비교 후 `receipt.json`을 만든다.
중단된 다운로드는 동일 bundle로 재시도한다. `upload.json`이 있으면 같은 commit을 재검증한다.
성공 receipt가 있는 bundle은 다시 전송하지 않는다. 원본·이전 receipt는 보존한다.
`bytes_verified=true`는 형식/품질 검증이 아니다. OMX export는 준비·전송 직전·고정 commit
재다운로드 후에 원본 시연과 SIM 과제 증거를 다시 검사하고 LeRobot 0.4.4 reader로 모든
RGB·원본 시각·state/action·관절 순서를 비교한다. 통과한 receipt만 `reader_verified=true`와
`reader` 보고서를 가진다. 전용 LeRobot 환경에서 실행하며 ROS 환경에 설치하지 않는다.
그 밖의 dataset/model은 `reader_verified=false`다. 다운로드한 `readback/`을
`native_review.py inspect` 또는 공식 model loader로 읽고 별도 보고서를 receipt와 보존한다.
reader 통과는 독립 정책 과제 성공·승격·장치 실행 승인이 아니다.

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
