# Colab에서 학습하고 로봇 쪽으로 넘기기 (D-356, D-373)

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/livsbittt/rosy-os/blob/main/tools/perception/training/rosy_lane_training.ipynb)

**바로 실행하는 노트북(D-373):** 위 배지로 [`rosy_lane_training.ipynb`](rosy_lane_training.ipynb)를 연다. 입력 칸만 채우면 기준 모델(LaneUNet)로 학습, export, 검사, store inbox로 넘기기까지 끝난다. 5b 셀에서 자기 모델로 바꿔 끼울 수 있다. 아래 절차는 자기 노트북을 쓰는 사람을 위한 것이다.

> **검증 범위:** 이 노트북은 개발 PC에서 셀을 차례로 실행하는 **로컬 stub 실행으로만** 확인했다
> (clone 대신 로컬 저장소, Drive·업로드 창 없이 로컬 store 폴더, CPU 1 에폭). 실제 Colab
> 런타임에서 돌려 본 적은 아직 없다. 처음 쓰는 사람은 이상한 점을 알려 달라.

**HF는 선택이다.** 데이터셋과 모델의 정본은 팀의 **store 폴더**다(D-373 결정 8). HF 계정이 없어도
전체 흐름이 돈다. HF를 쓰는 팀만 노트북 마지막 10단계(선택)를 켠다.

## store 폴더

store는 경로 하나다. 지금은 사이트 PC의 로컬 폴더이고, 팀이 Google Drive나 NAS에 두면 같은 구조를
그대로 쓴다. Colab에서는 Drive를 마운트한 경로(`/content/drive/MyDrive/<store 폴더>`)가 store다.

```text
<store>/datasets/<name>/<content_sha>/   데이터셋 (운영자가 publish.py로 넣는다)
<store>/models/inbox/<폴더>/             학습자가 넘기는 곳
<store>/models/accepted/<revision>/      intake 통과
<store>/models/rejected/<폴더>/          intake 탈락 (REJECTED.txt에 이유)
```

- **데이터셋 ref:** 운영자가 `store:<name>@<content_sha>`를 준다. `content_sha`는 폴더 안 파일의
  상대 경로와 sha256을 정렬해 해시한 64자 값이다. 노트북은 받은 폴더의 해시를 다시 계산해 다르면 멈춘다.
- **READY 규칙:** inbox 폴더는 파일을 모두 쓴 **뒤에** `READY`(내용 = 폴더의 `content_sha`)를 쓴다.
  사이트 PC는 `READY`가 폴더 내용과 맞는 폴더만 가져가므로, Drive 동기화가 덜 끝난 폴더는 기다린다.
  직접 넘길 때도 `handover.py`를 쓰면 이 규칙이 지켜진다.

## 여러 사람이 학습할 때

- 모두 **같은 store**를 쓴다(팀 Drive 폴더 또는 운영자에게 받은 zip). 개인 폴더에 넣으면 사이트 PC가 보지 않는다.
- manifest의 `trainer`에는 입력한 이름과 노트북 commit(`colab:rosy_lane_training.ipynb@<commit>`)이 들어간다.
- 같은 inbox에 여러 사람이 넘기면, **intake를 통과한 가장 새 폴더**가 로봇의 섀도가 된다(마지막에 넘긴 사람). 주행 활성화는 자동이 아니다.
- 데이터셋 ref는 고정해서 쓴다. 비교할 모델끼리는 같은 `content_sha`로 학습해야 IoU를 비교할 수 있다.

이 문서는 노트북(Colab 또는 GPU PC)에서 차선 분할 모델을 학습하는 사람을 위한 절차서다.
셀을 위에서부터 차례로 복사해 실행하면 된다. 약속의 전체 정의는 같은 폴더의
[README.md](README.md)에 있다.

**결과물은 딱 하나다:** `model.onnx`와 `model_manifest.json`이 든 폴더.
로봇 쪽은 이 폴더를 받아 검사(intake)하고, 통과하면 로봇에 섀도로 배포한다.

## 한눈에 보기

| 단계 | 어디서 | 무엇을 |
|---|---|---|
| 1 | Colab | 저장소에서 학습 도구와 검사용 코드만 받는다 |
| 2 | Colab | 데이터를 준비한다(지금 쓰던 데이터, 또는 store 데이터셋) |
| 3 | Colab | 평소처럼 학습한다 |
| 4 | Colab | `export()` 한 번으로 ONNX와 manifest를 만든다 |
| 5 | Colab | `check_manifest.py`로 검사한다 |
| 6 | Colab | `handover.py`로 store inbox에 넣는다(또는 zip으로 받는다) |

## 1. 저장소에서 필요한 것만 받기

저장소 전체(지도·영상 포함)는 크다. 학습 도구와 로봇 쪽 검사 코드만 sparse checkout으로 받는다.

```python
!git clone --depth 1 --filter=blob:none --sparse https://github.com/livsbittt/rosy-os.git rosy
!cd rosy && git sparse-checkout set tools/perception/training src/runtime/sensing/control
!pip -q install onnx onnxruntime

import sys
sys.path += ["/content/rosy/tools/perception/training", "/content/rosy/tools/perception",
             "/content/rosy/src/runtime/sensing"]
from export_cell import export, write_manifest
```

받는 것:

- `tools/perception/training/export_cell.py`: ONNX 내보내기와 manifest 작성
- `tools/perception/training/check_manifest.py`: 넘기기 전 검사
- `tools/perception/training/handover.py`: store inbox로 넘기기(READY는 마지막에)
- `tools/perception/store.py`: 내용 해시(`content_sha`)와 store 구조. sparse checkout은 `training`의
  상위 폴더 파일도 받으므로 따로 지정하지 않아도 된다.
- `src/runtime/sensing/control/...`: 로봇이 실제로 쓰는 manifest 검사기와 모델 로더.
  `export()`와 `check_manifest.py`가 이것으로 로봇과 똑같이 검사한다.

## 2. 데이터 준비

### 지금(0930 모델을 만든 데이터로 계속 학습)

지금 쓰던 데이터와 노트북을 그대로 쓴다. 4단계의 `export()`만 추가하면 된다.

### 로봇이 모은 데이터셋이 store에 올라온 뒤

운영자가 넘겨주는 것은 **데이터셋 ref** `store:<name>@<content_sha>` 하나다. store를 Drive로 공유하면
마운트해서 읽고, 아니면 운영자에게 받은 데이터셋 zip을 푼다. 어느 쪽이든 내용 해시를 확인한다.

```python
import os, shutil, zipfile
from store import Store, content_sha, parse_dataset_ref

DS_NAME, DS_SHA = parse_dataset_ref("store:<name>@<64자 content_sha>")
STORE = "/content/drive/MyDrive/rosy-store"          # Drive를 안 쓰면 "" 로 두고 zip을 쓴다
if STORE:
    from google.colab import drive
    drive.mount("/content/drive")
    shutil.copytree(Store(STORE).dataset_path(DS_NAME, DS_SHA), "ds")   # Drive에서 바로 읽으면 느리다
    ds_dir = "ds"
else:
    zipfile.ZipFile("<데이터셋>.zip").extractall("ds")
    ds_dir = "ds" if os.path.exists("ds/manifest.json") else os.path.join("ds", os.listdir("ds")[0])
if content_sha(ds_dir) != DS_SHA:
    raise RuntimeError("데이터셋 내용 해시가 ref와 다르다. 멈춘다.")
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
DS_REPO = "store:unknown"            # store 데이터셋을 안 썼다면 이렇게 두고,
DS_SHA  = "0" * 64                   # 썼다면 "store:" + DS_NAME 과 2단계의 DS_SHA를 그대로

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
  | `ignore` | 판단에 쓰지 않는 클래스(예: 횡단보도) |
  | `wall` | 벽. 차선 중심 계산에서 빠지고, 섀도 결과에 가까운 영역의 벽 비율(`wall_fraction`)로 나온다. `ignore`와 달리 평가·라벨에서 따로 센다(D-373 결정 9) |

  위 예시는 0930 모델 출력을 보고 **추정한** 값이다(그때는 `wall` role이 없어서 벽을 `ignore`로 적었다).
  새로 학습할 때는 팀 기본 목록을 쓴다: 0 floor/`background`, 1 lane_line/`lane_marking`, 2 wall/`wall`,
  3 drivable/`drivable`, 4 stop_line/`stop_line`, 5 crosswalk/`ignore`. 노트북의 실제 클래스 정의로 바꾼다.
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

### 방법 A: store inbox에 넣기(권장, Drive 마운트)

```python
from handover import package
package("out/lane_model", os.path.join(STORE, "models", "inbox"))
# -> <store>/models/inbox/<model_revision>__<UTC 시각>/ (model.onnx, model_manifest.json, READY)
```

`package()`는 manifest와 manifest가 이름을 댄 파일만 복사하고, 마지막에 `READY`를 쓴다. 사이트 PC가
10분 안에 intake하고, 통과하면 섀도로 배포한다. 결과는 store의 `models/accepted/<revision>/` 또는
`models/rejected/<폴더>/REJECTED.txt`에서 본다.

### 방법 B: zip으로 받아 운영자에게 전달

store를 마운트하지 않았다면 같은 폴더를 zip으로 받는다. zip 안에 `READY`까지 들어 있다.

```python
from handover import package_zip
z = package_zip("out/lane_model", "out/lane_model_handover.zip")
from google.colab import files; files.download(str(z))
```

운영자는 zip을 store의 `models/inbox/`에 **그대로 푼다**. 손으로 검사만 해 보려면:

```
python tools/perception/rosy_ml.py intake store-inbox:<폴더>
```

### 방법 C(선택): HF private 모델 저장소

HF를 쓰는 팀만. 노트북의 10단계(`USE_HF`)가 같은 일을 한다. 사이트 PC는 설정이 `backend: hf`일 때만
HF 저장소를 본다. 그때는 저장소 이름과 **40자 commit SHA**를 넘기고, 접수는
`rosy_ml intake hf:<org>/<repo>@<40자 SHA>`다. 태그나 브랜치 이름은 받지 않는다.

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
| 사이트 PC가 inbox 폴더를 안 가져간다 | `READY`가 없거나 폴더 내용과 다르다(복사·동기화 중, 또는 넣은 뒤 파일을 바꿨다). `handover.py`로 다시 넘긴다 |
| 노트북 3단계에서 멈춘다(내용 해시) | 받은 데이터셋이 ref와 다르다. 운영자에게 ref와 폴더/zip을 확인한다 |
| intake에서 revision 거부(HF) | HF에 태그나 브랜치 이름을 줬다. 40자 commit SHA를 준다 |
