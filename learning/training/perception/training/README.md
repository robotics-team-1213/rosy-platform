# 학습 약속 (D-356)

학습은 Colab이든 GPU PC든 어디서 돌려도 된다. 로봇 쪽과의 약속은 **입력과 출력**뿐이다.
이 폴더의 `export_cell.py`와 `check_manifest.py`가 그 약속의 실물이다.
Colab에서 셀 단위로 따라 하는 절차는 [COLAB.md](COLAB.md)에 있다.
바로 실행하는 Colab 노트북(기준 모델 학습부터 넘기기까지)은 [rosy_lane_training.ipynb](rosy_lane_training.ipynb)다(D-373).
노트북은 개발 PC에서 셀을 차례로 실행하는 **로컬 stub 실행으로만** 확인했다. 실제 Colab 런타임에서는 아직 돌려 보지 않았다.

**HF는 선택이다.** 데이터셋과 모델의 정본은 **store 폴더**다(D-373 결정 8). store는 경로 하나이고
(지금은 사이트 PC의 로컬 폴더, 나중에는 NAS나 Google Drive를 같은 구조로), 구조는 다음과 같다.

```
<store>/datasets/<name>/<content_sha>/   데이터셋, 한 번 쓰면 바꾸지 않는다
<store>/models/inbox/<폴더>/             학습자가 넘기는 곳
<store>/models/accepted/<revision>/      intake 통과
<store>/models/rejected/<폴더>/          intake 탈락 (REJECTED.txt)
```

`content_sha`는 폴더 안 파일의 상대 경로(`/` 구분)와 sha256을 `relpath\0sha256\n` 줄로 만들어 정렬한 뒤
sha256한 값이다(`learning/training/perception/store.py`). OS 찌꺼기(`.DS_Store`, `Thumbs.db`, `desktop.ini`)와
`READY`는 빼고 센다.

## 입력

- 데이터셋 ref `store:<name>@<content_sha>`(64자 hex). 내용 해시라 바뀌지 않는다. 받은 폴더의
  `content_sha`를 다시 계산해 ref와 다르면 학습하지 않는다(노트북 3단계가 한다).
  HF를 쓰는 팀은 HF dataset 저장소와 **commit SHA(40자 hex)**를 쓴다. 태그는 움직이므로 받지 않는다.
- 데이터셋 레이아웃. 파일 경로를 추측하지 말고 **`frames[].image` / `frames[].mask` 경로만
  따라간다**(디렉터리를 훑거나 이름을 조립하지 않는다). 두 가지 배치가 있다:

```
# 로컬 build 산출물 (build.py)
manifest.json
images/<session>/<session>__<index:06d>.jpg
masks/<session>/<session>__<index:06d>.png

# store(또는 HF)에 올라간 배치 (publish.py, shard당 최대 1000 frame, manifest 경로도 같이 바뀐다)
manifest.json
images/shard_0000/<...>.jpg
masks/shard_0000/<...>.png
```

- 이미지 이름은 `<session>__<index:06d>`(세션 이름 + 6자리 frame index)다. 마스크는 8-bit
  class-index PNG이고 화소값이 `classes[].index`다.
- 이미지 크기는 카메라 JPEG 크기 그대로다. 320x240을 **보장하지 않는다**. 학습 쪽에서 모델
  입력 `240x320`(HxW)으로 직접 resize한다(마스크는 nearest, 이미지는 학습 때 쓴 보간).
- `manifest.json` 필드:
  - `schema`: `rosy.perception.dataset/1`
  - `classes[]`: `{index, name, role, color}`. `color`는 CVAT 표시용이며 학습에는 쓰지 않는다.
    export의 `classes` 인자는 이 목록의 index 순서·role과 같아야 한다.
  - `frames[]`: `{image, mask, session, split}`. 경로는 데이터셋 루트 기준 상대 경로,
    `split`은 `train`/`val`이다. 다시 섞지 않는다.
  - `deleted_indexes`: 라벨링 중 버린 frame 목록(`"session__NNNNNN"` 문자열). 학습에는 쓰지 않는다.
  - `sources[]`: 프레임을 뽑은 세션의 `session.json` 내용(device, CameraProfile, 섀도 모델
    revision 등 출처 기록).
- split은 **세션 단위**다(같은 세션의 프레임은 한쪽 split에만 있다).
- CVAT에서 background role 클래스의 라벨 이름은 `background`다.

## 출력

store `models/inbox/`의 **한 폴더**에 두 파일과 `READY`가 있어야 한다(HF 백엔드면 한 commit에 두 파일).

- `model.onnx` — opset 17, 고정 입력 `1x3x240x320`, 입력 이름 `x`, 출력 이름 `logits`
  (`1xCx240x320` logit).
- `model_manifest.json` — `schema: rosy.perception.model/1`.

| 필드 | 뜻 |
|---|---|
| `model_revision` | `lane-seg-YYYYMMDD-<sha8>`, 전역 유일 (`export_cell`이 만든다) |
| `task` | `lane_seg` |
| `files[]` | `name`, `sha256`, `precision` (`fp32`/`int8`) |
| `input` | `shape`, `layout: nchw`, `color` (`rgb`/`bgr`), `scale`, `mean[3]`, `std[3]` |
| `output` | `layout: nchw_logits`, `classes[]` = `{index, name, role}` |
| `dataset` | `repo`, `revision`: store면 `store:<name>`과 `content_sha`, HF면 저장소 이름과 commit SHA |
| `camera_profile_revision` | 학습 영상의 CameraProfile |
| `metrics` | 검증 split의 클래스별 IoU |
| `trainer` | 코드 저장소·commit 또는 노트북 식별자 |

`role`은 닫힌 목록이다: `background`, `lane_marking`, `drivable`, `stop_line`, `ignore`, `wall`.
`wall`(D-373 결정 9)은 차선도 주행 가능 영역도 아니다. 후처리는 차선 중심 계산에서 `wall` 화소를 빼고,
섀도 결과에 가까운 영역(아래 40 %)의 벽 비율 `wall_fraction`을 낸다. `ignore`와 달리 평가와 라벨에서 따로 센다.
팀 기본 클래스 목록: 0 floor/`background`, 1 lane_line/`lane_marking`, 2 wall/`wall`, 3 drivable/`drivable`,
4 stop_line/`stop_line`, 5 crosswalk/`ignore`(노트북 입력 칸의 기본값, 데이터셋과 다르면 노트북이 멈춘다).
후처리는 이름이 아니라 role을 읽는다. `lane_marking`이 하나도 없으면 접수를 거부한다.
`classes`는 출력 채널 순서 그대로 적는다(index는 0부터 빈틈없이).

### 전처리는 학습과 똑같아야 한다

로봇은 BGR 프레임에 `x = (pixel * scale - mean) / std`를 채널별로 적용하고(`color`가 `rgb`면
채널 순서를 뒤집는다) 그 값을 `x`로 넣는다. 학습 때 쓴 `color`, `scale`, `mean`, `std`를
manifest에 **그대로** 적는다. 하나라도 다르면 모델은 오류 없이 엉뚱한 마스크를 낸다.
입력 크기는 `1x3x240x320`이 아니면 접수되지 않는다.

## 내보내기

학습 노트북 끝에서 (torch는 함수 안에서만 import한다):

```python
from export_cell import export   # 이 폴더의 파일을 노트북에 복사하거나 sys.path에 추가

export(model, "out/model_folder",
       classes=[("background", "background"), ("lane", "lane_marking"),
                ("road", "drivable"), ("stop", "stop_line")],   # 채널 순서대로 (name, role)
       color="rgb", scale=1 / 255, mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225],
       dataset_repo="store:rosy-lane", dataset_revision="<64-hex content_sha>",
       camera_profile_revision="<rev>", trainer="colab:<notebook or repo@commit>",
       val_iou={"lane": 0.61, "road": 0.93})
```

`export()`는 torch 2.5 이상을 권장한다(`dynamo=False` 인자가 있는 버전에서만 넘기고, 없으면 생략한다). `model.eval()`로 ONNX를 내보내고 sha256을 계산해 `model_manifest.json`을 쓴다.
torch 없이 이미 만든 `.onnx`가 있으면 `write_manifest(out_dir, onnx_path=..., <같은 인자>)`를 쓴다.
TorchScript만 있다면 개발 PC에서 `learning/training/perception/model/export_onnx.py`로 변환한다.

## 실험 기록(로컬 + TensorBoard)

기본은 로컬 기록이다(D-356 부록 2026-10-03): `run_log.py`의 `RunLog(run_dir)`가 `config.json`, `history.json`(에폭마다), `summary.json`을
쓰고, `tensorboard`가 있으면 이벤트 파일도 쓴다. `train(..., on_epoch=chain(log.on_epoch, ...))`로 연결하고, 끝에 `log.finish({...})`를 부른다.
`config`의 토큰·키·비밀번호 항목은 기록에서 빠진다. 기록 폴더는 모델 폴더 밖에 둔다(store로 넘어가지 않는다).
manifest의 `metrics.experiment`는 선택이고 두 형태만 받는다: `{"tracker": "wandb", "run_id", "url", "project"}` 또는
`{"tracker": "local", "run_id", "path": "runs/<run_id>"}`(상대 경로, 호스트 경로 없음, `export_cell`이 검증). 기록 오류는 학습을 멈추지 않는다. W&B는 선택이다. 절차는 [COLAB.md](COLAB.md)의 "실험 기록(로컬 + TensorBoard)".

## 넘기기 전에

```
python check_manifest.py out/model_folder      # OK lane-seg-YYYYMMDD-xxxxxxxx 이면 통과
```

`load_manifest`(스키마·role) + `verify_files`(sha256)를 돌리고, onnxruntime이 있으면
로봇이 쓰는 `LaneSegModel.open`으로 실제 로드와 워밍업까지 한다. 실패하면 메시지를 출력하고
종료 코드 1이다. 통과하기 전에는 넘기지 않는다.

## 넘기기

1. `handover.package(model_folder, <store>/models/inbox)`로 넣는다. `<model_revision>__<UTC>/`
   폴더에 manifest와 manifest가 이름을 댄 파일만 복사하고, **마지막에** `READY`(내용 = 폴더의
   `content_sha`)를 쓴다. store를 마운트하지 않았으면 `handover.package_zip(model_folder, out.zip)`으로
   같은 폴더를 zip으로 만들어 운영자에게 주고, 운영자는 inbox에 그대로 푼다.
2. 사이트 PC는 `READY`가 폴더 내용과 맞는 폴더만 가져간다(동기화 중인 폴더는 무시). intake를 통과하면
   `models/accepted/<revision>/`으로 옮기고 섀도 배포한다. 탈락하면 `models/rejected/<폴더>/`로 옮기고
   `REJECTED.txt`에 이유를 쓴다.
3. 손으로 접수하려면 `rosy_ml intake store-inbox:<폴더>`(또는 폴더 경로).
4. (선택) HF를 쓰는 팀: 폴더를 HF private model 저장소에 한 commit으로 올리고 **40자 hex SHA**를
   넘긴다. 접수는 `hf:<org/repo>@<sha>`다. 사이트 PC는 `backend: hf`일 때만 HF를 본다.
# 모델 비교 recipe (2026-10-04)

`recipes.py`는 `now2466/pinky-lane-segmentation@443f63fd4a5f6a4929775cecbda01c7b0a4557fe`의
조명 증강·CE+Dice·AdamW 접근을 ROSY manifest에 맞춘 학습용 helper다.
기존 `train()`의 기본 Adam/CE 동작은 유지하고, `loss_fn`과
`optimizer_factory`를 전달한 비교 run에서만 사용한다.

`LightingDataset(train_ds)`는 mask와 geometry를 보존하고 RGB 밝기/대비만 변경한다.
`pixel_counts(train_ds)`는 255를 제외한 클래스별 학습 픽셀을 집계한다.
`make_loss(counts, device=...)`는 weighted CE와 관측된 foreground의 masked Dice를 사용한다.
미관측 클래스는 학습됐다고 표시하지 않으며 foreground 정답이 전혀 없으면 거절한다.
이 helper는 배경 index 0을 사용하는 현행 자동 라벨 데이터용이다.

외부 모델의 4/5-class 이름을 현행 6-class 이름으로 바꾸거나 partial-label
background를 임의 변환하지 않는다. 클래스 개선 계획은
[인식 클래스 설계](../../../../docs/plans/2026-10-04-perception-class-expansion-design.md)를 따른다.
같은 데이터·세션 분할·seed·에폭으로 base16 기준/개선 recipe와 base8 소형 모델을
비교하고, 고정 평가의 클래스별 IoU·CPU 지연·모델 크기를 함께 기록한다.
검증 세션의 높은 수치만으로 전달하거나 주행을 활성화하지 않는다.

## 모델 PC의 재시작 가능한 학습 job

Linux CUDA 모델 PC에서 `python training/train_job.py config.json --out <job-dir>`로
기존 immutable store 데이터셋을 학습하고 ONNX 내보내기, 고정 평가 intake,
canonical inbox의 READY 생성까지 실행한다. 수집·라벨 검수·데이터셋 생성과
watcher 실행은 별도다. 로봇에 명령을 보내지 않는다.

설정은 다음 키만 받는다. 호스트 경로를 채운 설정은 공개 저장소에 넣지 않는다.

```json
{
  "store": "<store-root>",
  "dataset": "<dataset-name>@<content-sha>",
  "gate": "<require-eval-gate.yaml>",
  "replay_root": "<recording-root>",
  "intake_out": "<shared-qualified-models>",
  "camera_profile": "<camera-provenance.json>",
  "training": {
    "seed": 42705, "epochs": 30, "lr": 0.0003,
    "batch_size": 16, "base": 16, "recipe": "enhanced"
  }
}
```

camera provenance에는 `accepted` boolean을 명시한다. false는 잠정 캘리브레이션을
기록하며 장치 승인을 뜻하지 않는다. job은 데이터·평가·설정·소스 SHA와 픽셀
coverage를 기록하고, 검증에만 있는 클래스는 학습 전에 거절한다.
`baseline`/`enhanced`, base 8/16을 지원한다. 현행 recipe의 배경 채널은 index 0이다.

같은 설정·소스·job 경로로 재실행하면 완료 단계의 파일 SHA를 확인하고 건너뛴다.
실패 단계는 새 attempt 폴더에서 재시도하며 이전 오류를 보존한다. 품질 탈락은
terminal rejected이고 READY를 만들지 않는다. 입력/소스 변경이나 파일 변조는
재개를 거절한다. 변경 실험에는 새 job 경로를 사용한다.
자체 intake 증거를 고정하므로 공유 intake 보고서의 후속 지연 측정이 재개를
깨뜨리지 않는다. watcher가 accepted로 옮긴 동일 모델도 다시 복사하지 않는다.

`job_state.py`가 단일 작성자 잠금과 원자적 상태 저장을 맡는다. GPU job들은
`~/.cache/rosy-learning/gpu.lock`을 공유하고 시작 시 다른 GPU 프로세스가 있으면
거절한다. 다른 Isaac 실행기가 이 잠금을 사용하지 않으면 학습 시작 이후의
동시 실행까지 막지는 못한다. 현장 전달·rollback·주행 승인은 별도 gate다.
실행 증거는 [학습 job 검증](../../../../docs/validation/training-job-2026-10-04.md)에 있다.

## 녹화부터 시작하는 반복 job

`python training/recording_job.py <config.json> --out <job-dir>`는 선택한 녹화의
수거(선택), 출처 catalog, 자동 라벨, store 빌드와 위 train_job을 연결한다.
`--prepare-only`는 학습 전에 멈추고 dataset ref와 생성된 training-config 경로를
반환한다. 이때 부모 상태는 running이며 모델 READY 완료를 뜻하지 않는다.
`state.json`에는 앞단 단계가, `model-job/state.json`에는 학습 이후 단계가 남는다.

설정의 정확한 키는 `store`, `name`, `recordings`, `harvest`, `label`, `trainer`다.
`trainer`는 위 학습 설정에서 store/dataset을 뺀 `gate`, `replay_root`,
`intake_out`, `camera_profile`, `training`이다. store/dataset은 빌드 결과로 채운다.

```json
{
  "store": "<store-root>",
  "name": "recorded-auto-v2",
  "recordings": [
    {"session": "<recording-session-a>", "video": "<bag-to-video.mp4>", "pitch_deg": 11.5},
    {"session": "<recording-session-b>", "raw": "<completed-session-dir>"}
  ],
  "harvest": [],
  "label": {"min_interval": 0.5, "max_frames": 140, "lidar_yaw_deg": 180.0},
  "trainer": {
    "gate": "<require-eval-gate.yaml>", "replay_root": "<recording-root>",
    "intake_out": "<shared-qualified-models>", "camera_profile": "<provenance.json>",
    "training": {"seed": 42705, "epochs": 30, "lr": 0.0003,
                 "batch_size": 16, "base": 16, "recipe": "enhanced"}
  }
}
```

수치는 설정 형식 예시이며 해당 마운트의 보정 승인을 뜻하지 않는다.
video는 bag_to_video의 metadata JSON·clock sidecar JSONL을 필요로 한다.
metadata가 선언한 scan NPZ의 누락이나 session identity 불일치는 거절한다.
raw는 ended_at이 있는 session.json과 bag의 MCAP을 필요로 한다.
각 recording은 session과 video/raw 중 하나만 지정한다.
scan이 없는 입력의 pitch는 같은 마운트의 LiDAR 녹화 근거에서 명시한다.

`harvest` 요소는 `host`, `core_token_file`, `identity`, `known_hosts`, `dest`,
`host_key_alias`를 필수로, `user`, `remote_root`, `core_url`, `timeout`,
`status_timeout`을 선택값으로 받는다. 기존 harvest.py를 호출해 CORE idle 확인과
SSH pin을 유지한다. assume_idle이나 임의 CLI 인자는 받지 않는다.
학습에 쓸 수집 대상은 recordings에 명시하고 원본 데이터를 삭제하지 않는다.

job별 catalog-source.jsonl과 catalog-curated.jsonl을 보존하며 기존 catalog를
덮어쓰지 않는다. video만 있는 입력에서 raw 데이터나 운전자 근거를 만들지 않는다.
설정·소스·gate 변경에는 새 job이 필요하고, 원본/label/dataset 변경은 재개를 거절한다.
부분 라벨은 새 attempt에서 만들고 성공한 소스의 처리는 반복하지 않는다.
CVAT/model 예측의 검수 대기 mask를 이 자동 라벨 경로에 섞지 않는다.
Windows scratch/output은 X 드라이브에 둔다.

## 여러 데이터 버전을 반복 학습하기

`learning_cycle.py config.json --out <상태 경로>`는 새 요청을 확인하고 기존
`train_job.py`를 반복 호출한다. `--once`는 한 번 검사한 뒤 끝낸다. 설정에는
`trainer`(기존 train_job 설정), `recipes`(training 설정 목록), `requests_dir`,
`reviews_dir`, `interval_s`, `max_attempts`를 넣는다. 요청 폴더의 새 JSON은
`{"dataset":"<name>@<content_sha>","purpose":"research"}`다. 요청 파일은 수정하지
않고 새 파일로 게시한다. 같은 데이터와 training 설정은 중복 요청·재시작에도
다시 학습하지 않는다. 품질 거절은 그 후보만 끝내고, 실행 오류는 제한된 횟수만
재시도한다. 프로세스가 끊기면 기존 train_job의 검증된 단계부터 재개한다.

연속 실행 상태의 writer lock은 중복 실행을 거절한다. 요청 데이터의 내용 해시,
train/val 세션 분리와 저장소의 모든 고정 평가셋 제외를 먼저 검사한다. 실제
학습·수출·intake·READY 게시에는 기존 train_job의 품질 게이트를 그대로 쓴다.
camera provenance가 미수용인 연구 데이터는 운영 검증을 마친 데이터가 아니다.
이 실행기는 로봇 연결, 전달, HOLD 해제, 주행 활성화를 수행하지 않는다.

`reviews_dir/<export>/`의 Pinky 웹 검수 결과는 COMPLETE와 manifest의 모든 파일
해시를 검사한 뒤 승인·대기·제외 행을 상태에 기록한다. `review_queue`는 영상·원본
프레임·이미지 해시가 같은 행을 묶는다. 내보내기 간 결정이 다르면 `conflict`와
`decision=null`로 남기며 파일명·수신 순서로 승인을 고르지 않는다. 동일 결정은
내보내기 내부 index가 달라도 합친다. 사라지거나 불완전해진 내보내기는 기록을
보존하되 현재 집계에서 제외한다. 검수 중인 결과는
집계하지 않는다. 객체 박스 검수 결과는 segmentation 학습 자료로 변환하지
않으며 `training_dataset_qualified=false`를 유지한다. 검수자가 승인한 새 픽셀
마스크는 기존 build.py를 통해 세션이 분리된 불변 데이터 버전으로 만들어야 한다.

검수 PC의 `review_bridge.py config.json --out <상태 경로>`는 새 COMPLETE export를
모델 PC의 `reviews_dir`로 전달한다. 설정은 `source`, `peer`(승인된 SSH alias),
`remote_reviews`, `interval_s`, `max_attempts`다. SSH는 key-only와 host pin을 유지하고,
원격에서는 파일·manifest 해시를 다시 확인한 뒤 staging을 불변 export로 바꾼다.
같은 export는 재전달하지 않고 네트워크 오류만 제한 재시도한다. hidden staging과
미완료 export는 읽지 않는다. 라벨 승인·데이터셋 구성·학습·로봇 활성화는 하지 않는다.


## 현재 검수 결정을 모델 PC로 전달하기

새 GUI 계약은 `rosy.pinky-review-decisions/1`과 `rosy.pinky-review-export/2`이다.
외부 봉인은 `review-contract.json`의 SHA256인 `AUTHORITY_COMPLETE`이다.
`COMPLETE`만 있는 내보내기는 최신 승인 근거가 아니다.

bridge 설정에 다음 선택 항목을 추가하면 새 봉인을 기다리고 contract SHA로 전송을 구분한다.

```json
{"authority":{"endpoint":"http://127.0.0.1:8767/api/decisions","workspace_id":"<verified-workspace-id>"}}
```

endpoint는 검수 PC의 localhost이다. bridge는 현재 결정을 검증해 승인된 SSH peer의
`<remote_reviews>/.authority/current.json`으로 atomic replace한다. 두 봉인과 외부 manifest의
모든 파일을 전송한다. 현재 조회 실패는 unavailable로 전달하고 전송 실패는 별도로 기록한다.
같은 generation의 다른 digest, 이전 generation, 다른 workspace는 거절한다.

학습 PC의 cycle 설정에는 다음 선택 항목을 쓴다.

```json
{"authority":{"path":"<reviews>/.authority/current.json","workspace_id":"<verified-workspace-id>","max_age_s":90}}
```

cycle은 확인 시각·최대 나이·고정 workspace·generation/digest를 검증하고 현재와 완전히
일치하는 v2 export만 `authority_queue`에 넣는다. 이 큐는 항상
`training_dataset_qualified=false`이다. 기존 legacy `review_queue`는 과거 검수 증거이며
독립 픽셀 승인이나 최신 권한으로 올리지 않는다.

`review_authority.py`는 파일 봉인·binding·revision을 확인하는 ROS-free 소비 검증기이다.
검증 통과는 사람의 정답 라벨, 데이터셋 자격 또는 모델/로봇 활성화가 아니다.
indexed PNG를 기존 CVAT RGB builder에 바로 넣지 않는다. 별도 adapter와 명시 사람 승인,
이미지/마스크/labelmap/class 서명, 모든 고정 eval session 제외가 확보되어야 한다.

기존 Job은 입력 signature가 바뀌면 거절한다. 기존 서비스 설정만 바꿔 같은 상태 디렉터리에
덮어 실행하지 않는다. 신규 상태/기존 dedup history 이관을 검증한 후 서비스 전환한다.
이번 host 구현·테스트는 실제 GUI/SSH 전달이나 현장 수용 완료를 뜻하지 않는다.

### D-464 indexed trainer의 독립 admission

`review_dataset.py`의 게시 결과와 producer 큐는 계속 admission/qualification false다.
`train_job.run(..., indexed_review=...)`의 내부 owner 경로만 `review_admission.IndexedReview`를
받는다. 일반 CLI/config의 boolean이나 build receipt로 indexed 학습을 허용하지 않는다.
owner는 기존 transport ledger의 고정 workspace/highwater, fresh current provider, 원래 봉인
export, 실제 원본 proof와 X scratch를 공급해야 한다. 새 Job의 빈 상태로 highwater를 초기화하지 않는다.

admission은 모든 실제 Store eval version/gate ref와 원본 pixels를 다시 검사해 데이터셋을
scratch에 재구축하고, 저장된 content SHA와 정확히 같아야 허용한다. Store에는 다시 게시하지
않는다. trainer는 캡처한 dataset/eval/gate 사본을 소비하며 Job, GPU, export/intake와 READY 경계에서
authority·TTL·recipe/소스·실제 eval inventory·사본 bytes를 다시 검증한다. 느린 검사 후 만료도 거절한다.

실제 마스크 승인0, 평가 frame/group UNKNOWN과 부족한 source proof는 구현 뒤에도 HOLD다.
격리 synthetic 시험은 실제 사람 정답·GPU 학습·서비스 전환 수용이 아니다. 이 owner 경로를
기존 서비스에 연결하거나 실제 학습을 실행하는 작업은 별도 실행 범위다.
