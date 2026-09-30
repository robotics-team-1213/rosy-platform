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
sha256한 값이다(`tools/perception/store.py`). OS 찌꺼기(`.DS_Store`, `Thumbs.db`, `desktop.ini`)와
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

`role`은 닫힌 목록이다: `background`, `lane_marking`, `drivable`, `stop_line`, `ignore`.
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
TorchScript만 있다면 개발 PC에서 `tools/perception/model/export_onnx.py`로 변환한다.

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
