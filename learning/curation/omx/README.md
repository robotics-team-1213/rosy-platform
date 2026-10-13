# OMX 실물 모방학습 준비

실행 PC·HF 조직은 아직 미정이다. 이 도구는 host 주소를 고정하지 않고,
장치를 시작하거나 기존 ROSY 실물 profile을 활성화하지 않는다.
첫 수집은 공식 LeRobot leader recorder, Pilot 실물 조작은 D-496의 별도 구현·벤치 수용 대상이다.

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
python learning/curation/omx/native_review.py inspect <dataset-root> --repo-id local/omx-pick --body-units normalized_-100_100 --rig-revision <rig-revision> --calibration-revision <calibration-revision> --out <new-review-directory>
```

`inspection.json`은 원본 파일 hash·관절/카메라·frame/episode 수·실제 reader 결과를 담는다.
`decisions.json`은 모든 episode를 `outcome=unknown`, `split=exclude`로 시작한다.
영상을 확인한 사람이 `outcome`을 success/failure/unknown, `split`을 train/eval/exclude로
기록하고 `reviewer`·`reason`을 채운다. episode identity·hash·frame 수는 고치지 않는다.
검토 명령은 body 단위를 변환하지 않는다. 선언한 rig/보정은 실물 검증 증거가 아니다.

```text
python learning/curation/omx/native_review.py split <dataset-root> --report <review-directory>/inspection.json --decisions <review-directory>/decisions.json --out <new-split-directory>
```

원본을 다시 검사해 보고서와 비교한다. 유효한 성공 시연만 포함하며 같은 episode의 복제가
train/eval에 나뉘면 거부한다. 공식 LeRobot splitter로 각각의 dataset·통계를 만들고 실제 reader로
재독출한다. 원본을 덮어쓰지 않는다. 실패한 출력은 남으며 재시도는 새 출력 디렉터리를 쓴다.
이 검사는 byte/content 중복을 잡지만 비슷한 장면의 독립성을 판단하지는 못한다. 수집 세션·물체 배치도
운영자가 나눠야 한다. 실물 과제 성공률은 별도의 독립 시행에서 평가한다.

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
