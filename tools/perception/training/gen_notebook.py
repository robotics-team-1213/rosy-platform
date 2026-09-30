"""Source of rosy_lane_training.ipynb (D-373). Edit here, then: python gen_notebook.py

The .ipynb is generated output; test_training_notebook.py checks they match."""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "rosy_lane_training.ipynb"
cells = []


def md(text):
    cells.append({"cell_type": "markdown", "metadata": {}, "source": text.strip("\n").splitlines(True)})


def code(text):
    cells.append({"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
                  "source": text.strip("\n").splitlines(True)})


md("""
# Rosy 차선 분할 학습 (D-373)

입력 칸만 채우고 **런타임 → 모두 실행**을 누르면 기준 모델(LaneUNet)로 학습부터 HF 업로드까지 끝난다.
결과는 HF 모델 저장소의 commit 하나(`model.onnx` + `model_manifest.json`)다.
사이트 PC가 그 commit을 자동으로 intake하고, 통과하면 로봇에 **섀도**로 배포한다(주행에는 쓰지 않는다).

준비물:

- 팀 HF 조직의 **모델 저장소에 쓰기 권한이 있는 내 HF 토큰**. Colab 왼쪽 열쇠 아이콘(Secrets)에 `HF_TOKEN`으로 넣고 노트북 접근을 허용한다.
- 데이터셋 저장소 이름과 **commit SHA(40자)**. 태그·브랜치 이름은 받지 않는다.
- 런타임 유형은 GPU(T4 이상)를 권장한다. CPU로도 돌지만 느리다.

약속의 전체 정의는 [README.md](https://github.com/livsbittt/rosy-os/blob/main/tools/perception/training/README.md)에 있다.
""")

md("""
## 1. 학습 도구 받기

저장소 전체는 크므로 학습 도구와 로봇 쪽 검사 코드만 sparse clone으로 받는다.
이미 받아 둔 clone이 있으면 `git pull --ff-only`로 최신으로 맞춘다.
GPU PC에서 이미 받은 저장소를 쓰려면 환경 변수 `ROSY_REPO_DIR`에 그 경로를 넣는다(이때는 pull하지 않는다).
""")
code('''
#@title 1. 학습 도구 받기
import os, subprocess, sys

REPO_URL = "https://github.com/livsbittt/rosy-os.git"
ROSY = os.environ.get("ROSY_REPO_DIR") or os.path.abspath("rosy")
if not os.path.exists(os.path.join(ROSY, ".git")):
    subprocess.run(["git", "clone", "--depth", "1", "--filter=blob:none", "--sparse", REPO_URL, ROSY],
                   check=True)
    subprocess.run(["git", "-C", ROSY, "sparse-checkout", "set",
                    "tools/perception/training", "src/runtime/sensing/control"], check=True)
elif not os.environ.get("ROSY_REPO_DIR"):
    subprocess.run(["git", "-C", ROSY, "pull", "--ff-only"], check=True)
%pip install -q onnx onnxruntime huggingface_hub
for p in (os.path.join(ROSY, "tools", "perception", "training"), os.path.join(ROSY, "src", "runtime", "sensing")):
    if p not in sys.path:
        sys.path.insert(0, p)
REPO_COMMIT = subprocess.run(["git", "-C", ROSY, "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, check=True).stdout.strip()
print("rosy-os commit:", REPO_COMMIT)
''')

md("""
## 2. 입력 칸

- `TRAINER_NOTE`: manifest의 `trainer`에 덧붙일 짧은 메모(예: `lr 실험 A`). 이름과 노트북 commit은 자동으로 들어간다.
- `HF_DATASET_SHA`: 데이터셋 commit **40자 SHA**. 학습 중에는 바꾸지 않는다.
- `CLASSES`: 비워 두면 데이터셋 manifest의 클래스를 그대로 쓴다. 적으면 `이름:role,이름:role,...`(출력 채널 순서)로 쓰고, 데이터셋과 다르면 멈춘다.
- `COLOR`/`SCALE`/`MEAN`/`STD`: 학습 전처리. **이 값이 그대로 manifest에 적히고 로봇이 같은 값으로 전처리한다.**
- `CAMERA_PROFILE_REVISION`: 비워 두면 데이터셋 `sources[]`에서 가져온다.
""")
code('''
#@title 2. 입력 칸
TRAINER_NOTE = ""  #@param {type:"string"}
HF_DATASET_REPO = "<org>/rosy-lane-seg-data"  #@param {type:"string"}
HF_DATASET_SHA = ""  #@param {type:"string"}
HF_MODEL_REPO = "<org>/rosy-lane-seg-models"  #@param {type:"string"}
CLASSES = ""  #@param {type:"string"}
COLOR = "rgb"  #@param ["rgb", "bgr"]
SCALE = 1/255  #@param {type:"raw"}
MEAN = [0.0, 0.0, 0.0]  #@param {type:"raw"}
STD = [1.0, 1.0, 1.0]  #@param {type:"raw"}
EPOCHS = 30  #@param {type:"integer"}
LR = 0.001  #@param {type:"number"}
BATCH = 8  #@param {type:"integer"}
CAMERA_PROFILE_REVISION = ""  #@param {type:"string"}

import re
from rosy_lane_model import Preprocess

HF_DATASET_SHA = HF_DATASET_SHA.strip().lower()
for _name, _repo in (("HF_DATASET_REPO", HF_DATASET_REPO), ("HF_MODEL_REPO", HF_MODEL_REPO)):
    if "<" in _repo or "/" not in _repo:
        raise ValueError(f"2단계 입력 칸의 {_name}을(를) 채우세요: '<org>'를 팀 HF 조직 이름으로 바꿉니다 "
                         f"(지금: {_repo!r}). 바꾼 뒤 2단계부터 다시 실행합니다.")
if not re.fullmatch(r"[0-9a-f]{40}", HF_DATASET_SHA):
    raise ValueError("2단계 입력 칸의 HF_DATASET_SHA를 채우세요: 데이터셋 commit의 40자 hex SHA. "
                     "태그·브랜치 이름은 받지 않습니다.")
PRE = Preprocess(COLOR, SCALE, MEAN, STD)   # 데이터셋과 export가 이 한 객체를 같이 쓴다
print(PRE)
''')

md("""
## 3. Hugging Face 로그인

Colab Secret `HF_TOKEN`이 있으면 그것을 쓰고, 없으면 가려진 입력 칸에 토큰을 붙여 넣는다.
토큰은 노트북에 적지 않고 출력하지도 않는다. 로그인한 HF 사용자 이름이 manifest의 `trainer`에 자동으로 들어간다.
""")
code('''
#@title 3. Hugging Face 로그인
import getpass
from huggingface_hub import login, whoami

_token = None
try:
    from google.colab import userdata
    _token = userdata.get("HF_TOKEN")
except Exception:   # Colab 밖이거나, Secret이 없거나, 노트북 접근을 허용하지 않았다
    _token = None
if not _token:
    _token = getpass.getpass("HF 토큰(쓰기 권한)을 붙여 넣으세요: ").strip()
if not _token:
    raise RuntimeError("HF 토큰이 없습니다. Colab 왼쪽 열쇠 아이콘(Secrets)에 HF_TOKEN을 추가하고 "
                       "'노트북 액세스'를 켠 뒤 이 셀을 다시 실행하세요.")
login(token=_token, add_to_git_credential=False)
del _token
HF_USER = whoami()["name"]
print("HF 사용자:", HF_USER)
''')

md("""
## 4. 데이터셋 받기

`manifest.json`의 `frames[].image` / `frames[].mask` 경로만 따라 읽는다.
split(`train`/`val`)은 세션 단위로 이미 나뉘어 있으므로 **다시 섞지 않는다.**
""")
code('''
#@title 4. 데이터셋 받기 (SHA 고정)
from huggingface_hub import snapshot_download
from rosy_lane_model import RosyLaneDataset, class_mismatch

DS_DIR = snapshot_download(HF_DATASET_REPO, repo_type="dataset", revision=HF_DATASET_SHA, local_dir="ds")
_pre = dict(color=PRE.color, scale=PRE.scale, mean=PRE.mean, std=PRE.std)
train_ds = RosyLaneDataset(DS_DIR, "train", **_pre)
val_ds = RosyLaneDataset(DS_DIR, "val", **_pre)
ds_classes = sorted(train_ds.classes, key=lambda c: c["index"])
print("데이터셋 클래스 (출력 채널 순서):")
for c in ds_classes:
    print(f"  {c['index']}: {c['name']:<20} {c['role']}")
print(f"train {len(train_ds)} frames, val {len(val_ds)} frames")
if not len(train_ds) or not len(val_ds):
    raise RuntimeError("train 또는 val split이 비었습니다. 데이터셋 SHA를 확인하세요.")

EXPORT_CLASSES = [(c["name"], c["role"]) for c in ds_classes]
if CLASSES.strip():
    _form = [tuple(s.strip() for s in item.split(":")) for item in CLASSES.split(",") if item.strip()]
    if any(len(t) != 2 for t in _form):
        raise ValueError("CLASSES는 '이름:role,이름:role,...' 형식입니다.")
    _problem = class_mismatch(_form, ds_classes)
    if _problem:
        raise RuntimeError("CLASSES가 데이터셋과 다릅니다. 멈춥니다. " + _problem)

if not CAMERA_PROFILE_REVISION.strip():
    _revs = sorted({s.get("camera_profile_revision") for s in train_ds.manifest.get("sources", [])
                    if s.get("camera_profile_revision")})
    if len(_revs) > 1:
        raise RuntimeError(f"데이터셋에 CameraProfile이 여러 개입니다 {_revs}. CAMERA_PROFILE_REVISION을 직접 적으세요.")
    CAMERA_PROFILE_REVISION = _revs[0] if _revs else "unknown"
print("CameraProfile:", CAMERA_PROFILE_REVISION)
''')

md("""
## 5. 모델

기본은 0930 모델과 같은 구조의 `LaneUNet`(4단 U-Net, 16채널, 약 1.9M 파라미터)을 새로 학습한다.
**다시 학습할 때는 이 셀(또는 5b)부터 다시 실행한다.** 6단계만 다시 돌리면 이전 학습에 이어서 학습된다.
""")
code('''
#@title 5. 기준 모델 (LaneUNet)
import torch
from rosy_lane_model import LaneUNet

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
model = LaneUNet(n_classes=len(EXPORT_CLASSES))
print(DEVICE, sum(p.numel() for p in model.parameters()), "params")
''')

md("""
### 5b. (선택) 내 모델로 바꾸기

자기 모델을 쓰려면 아래 셀의 주석을 풀고 `model = ...` 한 줄을 바꾼다. 조건은 두 가지다.

- 입력 `1×3×240×320`(위 `PRE`로 전처리된 값), 출력 `1×C×240×320` **logit**(softmax 전). `C`는 클래스 수, 채널 순서는 4단계에 출력된 순서.
- 전처리를 바꿨다면 2단계의 `COLOR`/`SCALE`/`MEAN`/`STD`도 똑같이 바꾸고 2단계부터 다시 실행한다.

다음 셀이 출력 모양을 확인하고, 다르면 학습 전에 멈춘다.
""")
code('''
#@title 5b. (선택) 내 모델
# import torchvision
# model = MyLaneNet(num_classes=len(EXPORT_CLASSES))   # ← 이 줄을 내 모델로 바꾼다
# model.load_state_dict(torch.load("my_weights.pt"))  # 이어서 학습할 가중치가 있으면

with torch.no_grad():
    _out = model.eval()(torch.zeros(1, 3, 240, 320))
if tuple(_out.shape) != (1, len(EXPORT_CLASSES), 240, 320):
    raise ValueError(f"모델 출력이 {tuple(_out.shape)}입니다. (1, {len(EXPORT_CLASSES)}, 240, 320)이어야 합니다.")
print("출력 모양 OK:", tuple(_out.shape))
''')

md("""
## 6. 학습

에폭마다 학습 손실, 검증 손실, 검증 split의 클래스별 IoU를 출력한다.
학습이 끝나면 평균 IoU가 가장 좋았던 에폭의 가중치로 되돌리고, 그 에폭의 IoU를 manifest에 적는다.
""")
code('''
#@title 6. 학습
from rosy_lane_model import train

result = train(model, train_ds, val_ds, epochs=EPOCHS, lr=LR, batch_size=BATCH, device=DEVICE)
best_epoch = result["best_epoch"]
VAL_IOU = {k: round(v, 4) for k, v in result["val_iou"].items() if v is not None}
print(f"가장 좋은 에폭 {best_epoch}/{EPOCHS}의 검증 클래스별 IoU:")
for _k, _v in result["val_iou"].items():
    print(f"  {_k:<20} {'-' if _v is None else f'{_v:.3f}'}")
model = model.cpu().eval()
''')

md("""
## 7. 내보내기

`export()`가 opset 17 ONNX와 `model_manifest.json`을 만든다. 전처리 값은 2단계의 `PRE`에서 그대로 가져온다.
""")
code('''
#@title 7. 내보내기
from export_cell import export

TRAINER = f"{HF_USER} colab:rosy_lane_training.ipynb@{REPO_COMMIT} {TRAINER_NOTE}".strip()
OUT_DIR = "out/lane_model"
doc = export(model, OUT_DIR, classes=EXPORT_CLASSES, **PRE.manifest_kwargs(),
             dataset_repo=HF_DATASET_REPO, dataset_revision=HF_DATASET_SHA,
             camera_profile_revision=CAMERA_PROFILE_REVISION, trainer=TRAINER, val_iou=VAL_IOU)
MODEL_REVISION = doc["model_revision"]
print(MODEL_REVISION)
print("trainer:", TRAINER)
''')

md("""
## 8. 검사

로봇과 같은 코드로 manifest, sha256, ONNX 로드와 워밍업을 확인한다. `OK`가 아니면 올리지 않는다.
""")
code('''
#@title 8. check_manifest
_r = subprocess.run([sys.executable, os.path.join(ROSY, "tools", "perception", "training", "check_manifest.py"),
                     OUT_DIR], capture_output=True, text=True)
print(_r.stdout, _r.stderr)
if _r.returncode != 0 or not _r.stdout.startswith("OK"):
    raise RuntimeError("check_manifest 실패. 올리지 않습니다.")
''')

md("""
## 9. 올리기

팀 모델 저장소(private)에 commit 하나로 올린다. 여러 사람이 같은 저장소에 올리면 **intake를 통과한 가장 새 commit**이 로봇의 섀도가 된다.
누가 올렸는지는 commit 메시지와 manifest의 `trainer`에 남는다.
""")
code('''
#@title 9. HF 모델 저장소에 올리기
from huggingface_hub import HfApi
from huggingface_hub.utils import RepositoryNotFoundError

api = HfApi()
try:
    api.repo_info(HF_MODEL_REPO, repo_type="model")   # 쓰기 권한만 있어도 된다
except RepositoryNotFoundError:
    api.create_repo(HF_MODEL_REPO, repo_type="model", private=True, exist_ok=True)
info = api.upload_folder(folder_path=OUT_DIR, repo_id=HF_MODEL_REPO, repo_type="model",
                         commit_message=f"{MODEL_REVISION} by {HF_USER}")
MODEL_SHA = info.oid
print(HF_MODEL_REPO, MODEL_SHA)
print("이 SHA가 자동 반영의 입력입니다 — 사이트 PC가 intake 후 섀도로 배포합니다")
''')

nb = {
    "nbformat": 4,
    "nbformat_minor": 5,
    "metadata": {
        "colab": {"provenance": [], "gpuType": "T4", "toc_visible": True},
        "accelerator": "GPU",
        "kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"},
        "language_info": {"name": "python"},
    },
    "cells": cells,
}
for i, c in enumerate(nb["cells"]):
    c["id"] = f"cell-{i:02d}"


def render() -> str:
    return json.dumps(nb, indent=1, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    OUT.write_text(render(), encoding="utf-8", newline="\n")
    print("wrote", OUT, len(cells), "cells")
