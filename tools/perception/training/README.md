# 학습 약속 (D-356)

학습은 Colab이든 GPU PC든 어디서 돌려도 된다. 로봇 쪽과의 약속은 **입력과 출력**뿐이다.
이 폴더의 `export_cell.py`와 `check_manifest.py`가 그 약속의 실물이다.
Colab에서 셀 단위로 따라 하는 절차는 [COLAB.md](COLAB.md)에 있다.
바로 실행하는 Colab 노트북(기준 모델 학습부터 업로드까지)은 [rosy_lane_training.ipynb](rosy_lane_training.ipynb)다(D-373).

## 입력

- HF dataset 저장소(private)와 **commit SHA(40자 hex)**. 태그는 움직이므로 SHA로 고정한다.
- 데이터셋 레이아웃. 파일 경로를 추측하지 말고 **`frames[].image` / `frames[].mask` 경로만
  따라간다**(디렉터리를 훑거나 이름을 조립하지 않는다). 두 가지 배치가 있다:

```
# 로컬 build 산출물 (build.py)
manifest.json
images/<session>/<session>__<index:06d>.jpg
masks/<session>/<session>__<index:06d>.png

# HF에 올라간 배치 (publish.py, shard당 최대 1000 frame, manifest 경로도 같이 바뀐다)
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

HF model 저장소(private)의 **한 commit**에 두 파일이 있어야 한다.

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
| `dataset` | `repo`, `revision` (입력으로 받은 SHA) |
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
       dataset_repo="org/rosy-lane-ds", dataset_revision="<40-hex commit SHA>",
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

1. 폴더 전체를 HF **private model 저장소**에 push한다(한 commit에 두 파일).
2. 그 commit의 **40자 hex SHA**를 넘긴다. 태그·브랜치 이름은 받지 않는다(mutable).
3. 접수(intake)는 `hf:<org/repo>@<sha>`로 받아 재생 보고서를 만들고, 통과하면 섀도 배포된다.
