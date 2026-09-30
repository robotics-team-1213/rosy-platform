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

입력 칸만 채우고 **런타임 → 모두 실행**을 누르면 기준 모델(LaneUNet)로 학습부터 넘기기까지 끝난다.
**HF 계정은 필요 없다.** 데이터셋과 모델의 정본은 팀의 **store 폴더**다(D-373 결정 8).

- 데이터셋: store의 `datasets/<이름>/<내용 해시>/` 폴더(Google Drive 마운트) 또는 운영자에게 받은 데이터셋 zip.
- 결과: `model.onnx` + `model_manifest.json` 폴더 하나. store의 `models/inbox/`에 넣거나(Drive 마운트), zip으로 받아 운영자에게 준다.
- 사이트 PC가 inbox의 새 폴더를 자동으로 intake하고, 통과하면 로봇에 **섀도**로 배포한다(주행에는 쓰지 않는다).
- HF에 올리고 싶은 사람만 마지막 10단계(선택)를 쓴다.

런타임 유형은 GPU(T4 이상)를 권장한다. CPU로도 돌지만 느리다.
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
%pip install -q onnx onnxruntime
for p in (os.path.join(ROSY, "tools", "perception", "training"), os.path.join(ROSY, "tools", "perception"),
          os.path.join(ROSY, "src", "runtime", "sensing")):
    if p not in sys.path:
        sys.path.insert(0, p)
REPO_COMMIT = subprocess.run(["git", "-C", ROSY, "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, check=True).stdout.strip()
print("rosy-os commit:", REPO_COMMIT)
''')

md("""
## 2. 입력 칸

- `TRAINER`: 내 이름(필수). manifest의 `trainer`에 노트북 commit과 함께 들어간다.
- `TRAINER_NOTE`: `trainer`에 덧붙일 짧은 메모(예: `lr 실험 A`).
- `STORE`: store 폴더 경로. Google Drive에 있으면 `/content/drive/MyDrive/<store 폴더>`처럼 적는다(3단계가 Drive를 마운트한다).
  비워 두면 Drive 없이 진행한다: 데이터셋은 zip으로 받고, 결과도 zip으로 내려받는다.
- `DATASET`: 운영자가 `publish.py`로 받은 `store:<이름>@<내용 해시 64자>`. 학습 중에는 바꾸지 않는다.
- `DATASET_ZIP`: `STORE`를 비웠을 때만. 데이터셋 zip 경로. 비워 두면 3단계에서 업로드 창이 뜬다.
- `CLASSES`: 기본값은 팀 기본 클래스 목록이다(D-373 결정 9: 0 floor/background, 1 lane_line/lane_marking, 2 wall/wall, 3 drivable/drivable, 4 stop_line/stop_line, 5 crosswalk/ignore). `이름:role,이름:role,...`(출력 채널 순서)이고, **데이터셋 클래스와 다르면 멈춘다.** 데이터셋이 다른 목록이면 그 목록을 적거나 비운다(비우면 데이터셋 manifest의 클래스를 그대로 쓴다).
- `COLOR`/`SCALE`/`MEAN`/`STD`: 학습 전처리. **이 값이 그대로 manifest에 적히고 로봇이 같은 값으로 전처리한다.**
- `CAMERA_PROFILE_REVISION`: 비워 두면 데이터셋 `sources[]`에서 가져온다.
""")
code('''
#@title 2. 입력 칸
TRAINER = ""  #@param {type:"string"}
TRAINER_NOTE = ""  #@param {type:"string"}
STORE = "/content/drive/MyDrive/rosy-store"  #@param {type:"string"}
DATASET = ""  #@param {type:"string"}
DATASET_ZIP = ""  #@param {type:"string"}
CLASSES = "floor:background,lane_line:lane_marking,wall:wall,drivable:drivable,stop_line:stop_line,crosswalk:ignore"  #@param {type:"string"}
COLOR = "rgb"  #@param ["rgb", "bgr"]
SCALE = 1/255  #@param {type:"raw"}
MEAN = [0.0, 0.0, 0.0]  #@param {type:"raw"}
STD = [1.0, 1.0, 1.0]  #@param {type:"raw"}
EPOCHS = 30  #@param {type:"integer"}
LR = 0.001  #@param {type:"number"}
BATCH = 8  #@param {type:"integer"}
CAMERA_PROFILE_REVISION = ""  #@param {type:"string"}

from rosy_lane_model import Preprocess
from store import parse_dataset_ref

TRAINER, STORE, DATASET_ZIP = TRAINER.strip(), STORE.strip(), DATASET_ZIP.strip()
if not TRAINER:
    raise ValueError("2단계 입력 칸의 TRAINER를 채우세요: 내 이름(예: ana). 바꾼 뒤 2단계부터 다시 실행합니다.")
try:
    DS_NAME, DS_SHA = parse_dataset_ref(DATASET)
except ValueError:
    raise ValueError("2단계 입력 칸의 DATASET을 채우세요: 운영자가 준 'store:<이름>@<내용 해시 64자>' "
                     f"(지금: {DATASET!r}). 바꾼 뒤 2단계부터 다시 실행합니다.") from None
PRE = Preprocess(COLOR, SCALE, MEAN, STD)   # 데이터셋과 export가 이 한 객체를 같이 쓴다
print(PRE)
print("dataset:", f"store:{DS_NAME}@{DS_SHA}", "| store:", STORE or "(없음: zip으로 받고 zip으로 넘긴다)")
''')

md("""
## 3. 데이터셋 가져오기 (내용 해시 확인)

`STORE`가 있으면 `STORE/datasets/<이름>/<해시>/`를 이 런타임의 `ds/`로 복사한다(Drive에서 바로 읽으면 느리다).
없으면 데이터셋 zip을 `ds/`에 푼다. 그다음 `ds/`의 **내용 해시**를 계산해 `DATASET`의 해시와 비교한다.
다르면 경고하고 **멈춘다**: 다른 데이터로 학습한 모델에 틀린 데이터셋 이름이 붙지 않게 하기 위해서다.
""")
code('''
#@title 3. 데이터셋 가져오기
import shutil, zipfile
from store import Store, content_sha

DS_DIR = os.path.abspath("ds")
shutil.rmtree(DS_DIR, ignore_errors=True)
if STORE:
    if STORE.startswith("/content/drive") and not os.path.isdir("/content/drive/MyDrive"):
        from google.colab import drive
        drive.mount("/content/drive")
    _src = Store(STORE).dataset_path(DS_NAME, DS_SHA)
    if not _src.is_dir():
        raise FileNotFoundError(f"store에 데이터셋이 없습니다: {_src}. STORE 경로와 DATASET을 확인하세요.")
    shutil.copytree(_src, DS_DIR)
else:
    _zip = DATASET_ZIP
    if not _zip:
        try:
            from google.colab import files
        except ImportError:
            raise RuntimeError("STORE가 비었으면 2단계 입력 칸의 DATASET_ZIP에 데이터셋 zip 경로를 적으세요.") from None
        _zip = next(iter(files.upload()))
    with zipfile.ZipFile(_zip) as _z:
        _z.extractall(DS_DIR)
    _subs = os.listdir(DS_DIR)
    if "manifest.json" not in _subs and len(_subs) == 1:   # zip 안에 폴더 하나로 묶인 경우
        DS_DIR = os.path.join(DS_DIR, _subs[0])
_got = content_sha(DS_DIR)
if _got != DS_SHA:
    print("경고: 데이터셋 내용 해시가 DATASET과 다릅니다.")
    print("  DATASET:", DS_SHA)
    print("  받은 것:", _got)
    raise RuntimeError("데이터셋 내용이 DATASET의 해시와 다릅니다. 멈춥니다. 운영자에게 받은 ref와 zip/폴더를 확인하세요.")
print("데이터셋 내용 해시 OK:", _got)
''')

md("""
## 4. 데이터셋 읽기

`manifest.json`의 `frames[].image` / `frames[].mask` 경로만 따라 읽는다.
split(`train`/`val`)은 세션 단위로 이미 나뉘어 있으므로 **다시 섞지 않는다.**
""")
code('''
#@title 4. 데이터셋 읽기
from rosy_lane_model import RosyLaneDataset, class_mismatch

_pre = dict(color=PRE.color, scale=PRE.scale, mean=PRE.mean, std=PRE.std)
train_ds = RosyLaneDataset(DS_DIR, "train", **_pre)
val_ds = RosyLaneDataset(DS_DIR, "val", **_pre)
ds_classes = sorted(train_ds.classes, key=lambda c: c["index"])
print("데이터셋 클래스 (출력 채널 순서):")
for c in ds_classes:
    print(f"  {c['index']}: {c['name']:<20} {c['role']}")
print(f"train {len(train_ds)} frames, val {len(val_ds)} frames")
if not len(train_ds) or not len(val_ds):
    raise RuntimeError("train 또는 val split이 비었습니다. 데이터셋을 확인하세요.")

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
manifest의 `dataset`에는 `store:<이름>`과 내용 해시가 들어간다.
""")
code('''
#@title 7. 내보내기
from export_cell import export

TRAINER_ID = f"{TRAINER} colab:rosy_lane_training.ipynb@{REPO_COMMIT} {TRAINER_NOTE}".strip()
OUT_DIR = "out/lane_model"
doc = export(model, OUT_DIR, classes=EXPORT_CLASSES, **PRE.manifest_kwargs(),
             dataset_repo=f"store:{DS_NAME}", dataset_revision=DS_SHA,
             camera_profile_revision=CAMERA_PROFILE_REVISION, trainer=TRAINER_ID, val_iou=VAL_IOU)
MODEL_REVISION = doc["model_revision"]
print(MODEL_REVISION)
print("trainer:", TRAINER_ID)
''')

md("""
## 8. 검사

로봇과 같은 코드로 manifest, sha256, ONNX 로드와 워밍업을 확인한다. `OK`가 아니면 넘기지 않는다.
""")
code('''
#@title 8. check_manifest
_r = subprocess.run([sys.executable, os.path.join(ROSY, "tools", "perception", "training", "check_manifest.py"),
                     OUT_DIR], capture_output=True, text=True)
print(_r.stdout, _r.stderr)
if _r.returncode != 0 or not _r.stdout.startswith("OK"):
    raise RuntimeError("check_manifest 실패. 넘기지 않습니다.")
''')

md("""
## 9. 넘기기

- `STORE`가 있으면 `STORE/models/inbox/<revision>__<UTC 시각>/`에 넣는다. 파일을 모두 복사한 **뒤에** `READY` 표식을 쓴다.
  사이트 PC는 `READY`가 폴더 내용과 맞는 폴더만 가져가므로, Drive 동기화가 덜 끝난 폴더는 끝날 때까지 기다린다.
- `STORE`가 없으면 같은 폴더(안에 `READY` 포함)를 zip으로 만들어 내려받는다. 운영자는 zip을 store의 `models/inbox/`에 **그대로 푼다**.

여러 사람이 넘기면 **intake를 통과한 가장 새 폴더**가 로봇의 섀도가 된다. 누가 넘겼는지는 manifest의 `trainer`에 남는다.
""")
code('''
#@title 9. store inbox에 넘기기 (또는 zip)
from handover import package, package_zip

if STORE:
    HANDED = package(OUT_DIR, os.path.join(STORE, "models", "inbox"))
    print("넘김:", HANDED)
    print("사이트 PC가 10분 안에 intake하고, 통과하면 섀도로 배포합니다.")
else:
    HANDED = package_zip(OUT_DIR, os.path.join("out", f"{MODEL_REVISION}.zip"))
    try:
        from google.colab import files
        files.download(str(HANDED))
    except ImportError:
        pass
    print("zip:", HANDED, "— 운영자에게 주고 store의 models/inbox/에 그대로 풀게 합니다.")
''')

md("""
## 10. (선택) HF 모델 저장소에도 올리기

HF를 쓰는 팀만 쓴다. **store로 넘기는 데는 필요 없다.** `USE_HF`를 켜야 실행된다.
토큰은 Colab Secret `HF_TOKEN`(없으면 가려진 입력 칸)에서 읽고, 노트북에 적지 않고 출력하지도 않는다.
""")
code('''
#@title 10. (선택) HF 모델 저장소에 올리기
USE_HF = False  #@param {type:"boolean"}
HF_MODEL_REPO = "<org>/rosy-lane-seg-models"  #@param {type:"string"}

if USE_HF:
    if "<" in HF_MODEL_REPO or "/" not in HF_MODEL_REPO:
        raise ValueError(f"10단계 입력 칸의 HF_MODEL_REPO를 채우세요 (지금: {HF_MODEL_REPO!r}).")
    try:
        import huggingface_hub  # noqa: F401
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "huggingface_hub"], check=True)
    import getpass
    from huggingface_hub import HfApi, login, whoami
    from huggingface_hub.utils import RepositoryNotFoundError

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
    api = HfApi()
    try:
        api.repo_info(HF_MODEL_REPO, repo_type="model")   # 쓰기 권한만 있어도 된다
    except RepositoryNotFoundError:
        api.create_repo(HF_MODEL_REPO, repo_type="model", private=True, exist_ok=True)
    info = api.upload_folder(folder_path=OUT_DIR, repo_id=HF_MODEL_REPO, repo_type="model",
                             commit_message=f"{MODEL_REVISION} by {TRAINER} ({HF_USER})")
    print(HF_MODEL_REPO, info.oid)
else:
    print("HF 건너뜀 (USE_HF = False). store/zip으로 이미 넘겼습니다.")
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
