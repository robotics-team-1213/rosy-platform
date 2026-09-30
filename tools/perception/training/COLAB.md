# Colab에서 학습하고 로봇 쪽으로 넘기기 (D-356)

이 문서는 노트북(Colab 또는 GPU PC)에서 차선 분할 모델을 학습하는 사람을 위한 절차서다.
셀을 위에서부터 차례로 복사해 실행하면 된다. 약속의 전체 정의는 같은 폴더의
[README.md](README.md)에 있다.

**결과물은 딱 하나다:** `model.onnx`와 `model_manifest.json`이 든 폴더.
로봇 쪽은 이 폴더를 받아 검사(intake)하고, 통과하면 로봇에 섀도로 배포한다.

## 한눈에 보기

| 단계 | 어디서 | 무엇을 |
|---|---|---|
| 1 | Colab | 저장소에서 학습 도구 두 파일과 검사용 코드만 받는다 |
| 2 | Colab | 데이터를 준비한다(지금 쓰던 데이터, 또는 HF 데이터셋) |
| 3 | Colab | 평소처럼 학습한다 |
| 4 | Colab | `export()` 한 번으로 ONNX와 manifest를 만든다 |
| 5 | Colab | `check_manifest.py`로 검사한다 |
| 6 | Colab | HF에 올리고 commit SHA를 넘긴다(또는 폴더를 zip으로 받는다) |

## 1. 저장소에서 필요한 것만 받기

저장소 전체(지도·영상 포함)는 크다. 학습 도구와 로봇 쪽 검사 코드만 sparse checkout으로 받는다.

```python
!git clone --depth 1 --filter=blob:none --sparse https://github.com/livsbittt/rosy-os.git rosy
!cd rosy && git sparse-checkout set tools/perception/training src/runtime/sensing/control
!pip -q install onnx onnxruntime huggingface_hub

import sys
sys.path += ["/content/rosy/tools/perception/training", "/content/rosy/src/runtime/sensing"]
from export_cell import export, write_manifest
```

받는 것:

- `tools/perception/training/export_cell.py`: ONNX 내보내기와 manifest 작성
- `tools/perception/training/check_manifest.py`: 넘기기 전 검사
- `src/runtime/sensing/control/...`: 로봇이 실제로 쓰는 manifest 검사기와 모델 로더.
  `export()`와 `check_manifest.py`가 이것으로 로봇과 똑같이 검사한다.

## 2. 데이터 준비

### 지금(0930 모델을 만든 데이터로 계속 학습)

지금 쓰던 데이터와 노트북을 그대로 쓴다. 4단계의 `export()`만 추가하면 된다.

### 로봇이 모은 데이터셋이 HF에 올라온 뒤

로봇 쪽이 넘겨주는 것은 **HF 데이터셋 저장소 이름**과 **commit SHA(40자)** 두 가지다.

```python
from huggingface_hub import login, snapshot_download
login()   # Colab 왼쪽 열쇠 아이콘(Secrets)에 HF_TOKEN을 넣어 두면 편하다

DS_REPO = "<org>/rosy-lane-seg-data"
DS_SHA  = "<40자 commit SHA>"
ds_dir = snapshot_download(DS_REPO, repo_type="dataset", revision=DS_SHA, local_dir="ds")
```

데이터셋은 `manifest.json`이 가리키는 경로만 따라 읽는다. 폴더를 훑거나 파일 이름을 조립하지 않는다.

```python
import json, cv2, numpy as np, torch
from pathlib import Path

class RosyLaneDataset(torch.utils.data.Dataset):
    def __init__(self, root, split):
        self.root = Path(root)
        m = json.loads((self.root / "manifest.json").read_text(encoding="utf-8"))
        self.classes = m["classes"]                       # [{index, name, role, color}]
        self.frames = [f for f in m["frames"] if f["split"] == split]

    def __len__(self):
        return len(self.frames)

    def __getitem__(self, i):
        f = self.frames[i]
        bgr = cv2.imread(str(self.root / f["image"]), cv2.IMREAD_COLOR)
        mask = cv2.imread(str(self.root / f["mask"]), cv2.IMREAD_UNCHANGED)   # 화소값 = 클래스 index
        bgr = cv2.resize(bgr, (320, 240), interpolation=cv2.INTER_AREA)
        mask = cv2.resize(mask, (320, 240), interpolation=cv2.INTER_NEAREST)
        rgb = bgr[..., ::-1].astype(np.float32) / 255.0   # 4단계 color/scale/mean/std와 반드시 같게
        x = torch.from_numpy(rgb.transpose(2, 0, 1).copy())
        return x, torch.from_numpy(mask.astype(np.int64))

train_ds = RosyLaneDataset(ds_dir, "train")
val_ds   = RosyLaneDataset(ds_dir, "val")
```

- split(`train`/`val`)은 세션 단위로 이미 나뉘어 있다. **다시 섞지 않는다.** 섞으면 같은 주행의
  연속 프레임이 양쪽에 들어가 검증 점수가 부풀려진다.
- 이미지 크기는 카메라 그대로라 320×240이 보장되지 않는다. 위처럼 직접 resize한다.

## 3. 학습

평소처럼 학습한다. 조건은 두 가지뿐이다.

- 모델 입력 `1×3×240×320`, 출력 `1×C×240×320` logit(softmax 전)
- 전처리(RGB/BGR, 나누는 값, mean, std)를 기억해 둔다. 4단계에 그대로 적는다.

## 4. 내보내기: `export()` 한 번

학습이 끝난 `model` 객체로 호출한다.

```python
DS_REPO = "unknown/colab-local"      # HF 데이터셋을 안 썼다면 이렇게 두고,
DS_SHA  = "0" * 40                   # 썼다면 2단계의 저장소 이름과 SHA를 그대로

doc = export(model, "out/lane_model",
    classes=[                        # ★ 출력 채널 순서 그대로 (이름, role)
        ("floor",      "background"),
        ("lane_left",  "lane_marking"),
        ("lane_right", "lane_marking"),
        ("wall",       "ignore"),
    ],
    color="rgb", scale=1/255, mean=[0, 0, 0], std=[1, 1, 1],   # ★ 학습 전처리 그대로
    dataset_repo=DS_REPO, dataset_revision=DS_SHA,
    camera_profile_revision="unknown",
    trainer="colab:<노트북 이름>@<날짜>",
    val_iou={"lane_left": 0.0, "lane_right": 0.0},   # 검증 IoU를 넣는다
)
print(doc["model_revision"])
```

★ 표시한 두 곳이 가장 중요하다.

- **`classes`:** 출력 채널 0, 1, 2, …의 의미를 순서대로 적는다. `role`은 다음 중 하나다.

  | role | 뜻 |
  |---|---|
  | `background` | 바닥·배경 |
  | `lane_marking` | 차선(흰 선). **하나 이상 반드시 있어야 한다** |
  | `drivable` | 주행 가능 영역(있을 때만) |
  | `stop_line` | 정지선(있을 때만) |
  | `ignore` | 벽 등 판단에 쓰지 않는 클래스 |

  위 예시는 0930 모델 출력을 보고 **추정한** 값이다. 노트북의 실제 클래스 정의로 바꾼다.
- **`color`, `scale`, `mean`, `std`:** 학습 때 입력을 만든 방식과 똑같이 적는다.
  로봇은 이 값으로 전처리한다. 틀리면 오류 없이 엉뚱한 마스크가 나온다.
  - 0–1로 나누기만 했다면: `scale=1/255, mean=[0,0,0], std=[1,1,1]`
  - ImageNet 정규화를 했다면: `mean=[0.485,0.456,0.406], std=[0.229,0.224,0.225]`
  - OpenCV로 읽고 채널을 바꾸지 않았다면: `color="bgr"`

`export()`는 torch 2.5 이상을 권장한다. `model.eval()`로 opset 17 ONNX를 만들고, sha256을
계산해 manifest를 쓴 뒤, 로봇 쪽 검사기로 바로 검증한다. 문제가 있으면 여기서 오류가 난다.

## 5. 검사

```python
!python /content/rosy/tools/perception/training/check_manifest.py out/lane_model
```

`OK lane-seg-YYYYMMDD-xxxxxxxx`가 나오면 통과다. onnxruntime이 설치돼 있으면 로봇과 같은
코드로 모델을 실제로 열고 워밍업까지 해 본다. `FAIL ...`이 나오면 메시지대로 고친다.

## 6. 넘기기

### 방법 A: HF private 모델 저장소(권장)

```python
from huggingface_hub import HfApi
api = HfApi()
MODEL_REPO = "<org>/rosy-lane-seg-models"
api.create_repo(MODEL_REPO, repo_type="model", private=True, exist_ok=True)
info = api.upload_folder(folder_path="out/lane_model", repo_id=MODEL_REPO, repo_type="model",
                         commit_message=doc["model_revision"])
print("넘길 값:", MODEL_REPO, info.oid)   # oid = 40자 commit SHA
```

로봇 쪽에 **저장소 이름과 40자 SHA**를 전달한다. 태그나 브랜치 이름은 받지 않는다(나중에 다른
commit을 가리킬 수 있다). 로봇 쪽은 이렇게 접수한다:

```
python tools/perception/model/intake.py hf:<org>/rosy-lane-seg-models@<40자 SHA>
```

### 방법 B: 폴더를 직접 전달

HF를 아직 안 쓴다면 폴더를 zip으로 받아 전달한다.

```python
!cd out && zip -r lane_model.zip lane_model
from google.colab import files; files.download("out/lane_model.zip")
```

로봇 쪽은 개발 PC의 `data/drive/` 아래(저장소에 올라가지 않는 곳)에 풀고 접수한다.

```
python tools/perception/model/intake.py data/drive/lane_model
```

## 이후 흐름(로봇 쪽)

1. **intake:** manifest와 해시를 확인하고, teleop 영상 재생 보고서를 만든다. 통과하면 등록한다.
2. **deliver:** 로봇의 `/var/lib/rosy/models/<revision>/`에 복사하고 섀도 포인터를 바꾼다.
   문제가 있으면 한 명령으로 되돌린다.
3. **섀도 추론:** 로봇이 새 모델을 돌려 `perception/learned/shadow`에 결과를 낸다.
   **주행에는 쓰지 않는다.** 주행 활성화는 D-205 재생 게이트를 통과한 뒤 별도로 결정한다.

## 자주 틀리는 것

| 증상 | 원인 |
|---|---|
| `check_manifest`에서 `no lane_marking role` | `classes`에 `lane_marking`이 하나도 없다 |
| 검사는 통과했는데 마스크가 엉뚱하다 | `color`/`scale`/`mean`/`std`가 학습과 다르다 |
| `output shape ... !=` | 모델 출력 채널 수와 `classes` 개수가 다르다, 또는 입력이 240×320이 아니다 |
| `sha256 mismatch` | manifest를 만든 뒤 `model.onnx`를 바꿨다. `export()`를 다시 돌린다 |
| intake에서 revision 거부 | HF에 태그나 브랜치 이름을 줬다. 40자 commit SHA를 준다 |
