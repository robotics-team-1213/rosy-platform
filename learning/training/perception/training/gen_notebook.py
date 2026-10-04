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
약속의 전체 정의는 [README.md](https://github.com/livsbittt/rosy-os/blob/main/learning/training/perception/training/README.md)에 있다.
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
if not os.environ.get("ROSY_REPO_DIR"):
    # control imports core_common (D-424), so the sparse set carries it too
    subprocess.run(["git", "-C", ROSY, "sparse-checkout", "set", "learning/training/perception/training",
                    "middleware/perception/control", "contracts/foundation/core_common"], check=True)
    subprocess.run(["git", "-C", ROSY, "pull", "--ff-only"], check=True)
%pip install -q onnx onnxruntime
for p in (os.path.join(ROSY, "learning", "training", "perception", "training"), os.path.join(ROSY, "learning", "training", "perception"),
          os.path.join(ROSY, "middleware", "perception"), os.path.join(ROSY, "contracts", "foundation")):
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
- `RUNS_DIR`: 실험 기록(로컬 + TensorBoard)을 쌓을 폴더. 비워 두면 환경 변수 `ROSY_RUNS_DIR`, 없으면 Colab에서는 `/content/rosy-runs`, 그 밖(GPU PC)에서는 `~/rosy-ml/runs`다. Colab 런타임은 닫히면 지워지므로 남기려면 Drive 경로를 적는다.
- `USE_WANDB`/`WANDB_PROJECT`: (선택) Weights & Biases 실험 기록. 키는 Colab Secret `WANDB_API_KEY`에만 둔다(5d단계). 키가 없으면 W&B 없이 학습한다. 로컬 기록은 항상 남는다.
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
RUNS_DIR = ""  #@param {type:"string"}
WANDB_PROJECT = "rosy-perception"  #@param {type:"string"}
USE_WANDB = True  #@param {type:"boolean"}

from rosy_lane_model import Preprocess
from store import parse_dataset_ref

TRAINER, STORE, DATASET_ZIP = TRAINER.strip(), STORE.strip(), DATASET_ZIP.strip()
RUNS_DIR = RUNS_DIR.strip() or os.environ.get("ROSY_RUNS_DIR", "")
if not RUNS_DIR:
    try:
        import google.colab  # noqa: F401
        RUNS_DIR = "/content/rosy-runs"
    except ImportError:   # Colab 밖(GPU PC)
        RUNS_DIR = os.path.join("~", "rosy-ml", "runs")
RUNS_DIR = os.path.abspath(os.path.expanduser(RUNS_DIR))
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
print("실험 기록 폴더:", RUNS_DIR)
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
# D-379: 라벨 없는 화소 값(manifest ignore_index, 보통 255)은 손실과 IoU에서 빠진다.
IGNORE_INDEX = train_ds.ignore_index
print(f"ignore_index: {IGNORE_INDEX}")
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
### 5c. 실험 기록 (로컬 + TensorBoard)

기본 기록이다. `RUNS_DIR/<UTC 시각>-<TRAINER>/`에 `config.json`(학습 설정), `history.json`(에폭마다 갱신, 중간에 멈춰도 남는다),
`summary.json`(7단계 끝에 가장 좋은 에폭, `model_revision`, 내보낸 폴더의 상대 경로)을 쓰고, `tensorboard`가 설치돼 있으면 TensorBoard 이벤트 파일도 같은 폴더에 쓴다
(없으면 TensorBoard만 건너뛰고 `history.json`에 `"tensorboard": "unavailable"`로 남긴다). 토큰·키가 들어간 설정 항목은 기록에서 빠진다(키 이름만 본다. 설정에 비밀 문장을 적지 않는다). 기록 중 오류(TensorBoard, 디스크)는 기록만 멈추고 학습은 멈추지 않는다.
manifest에는 호스트 경로 없이 고정 형태 `runs/<run_id>`만 들어간다.
이 폴더는 모델 폴더(`out/lane_model`)와 따로이므로 store inbox로 넘어가지 않는다.
""")
code('''
#@title 5c. 실험 기록 (로컬 + TensorBoard)
import datetime, re
from run_log import RunLog, chain

if globals().get("RUN_LOG") is not None:   # 이 셀을 다시 실행: 앞 기록을 먼저 닫는다
    RUN_LOG.close()
_slug = re.sub(r"[^A-Za-z0-9._-]", "_", TRAINER)[:64]
RUN_ID = f"{datetime.datetime.now(datetime.timezone.utc):%Y%m%dT%H%M%SZ}-{_slug}"
RUN_DIR = os.path.join(RUNS_DIR, RUN_ID)
RUN_CONFIG = {
    "epochs": EPOCHS, "lr": LR, "batch": BATCH, "classes": EXPORT_CLASSES,
    "preprocessing": PRE.manifest_kwargs(), "dataset": f"store:{DS_NAME}", "dataset_content_sha": DS_SHA,
    "camera_profile_revision": CAMERA_PROFILE_REVISION, "repo_commit": REPO_COMMIT,
    "trainer": TRAINER, "trainer_note": TRAINER_NOTE}
RUN_LOG = RunLog(RUN_DIR)
RUN_LOG.write_config(RUN_CONFIG)
LOCAL_EXPERIMENT = {"tracker": "local", "run_id": RUN_ID, "path": f"runs/{RUN_ID}"}
print("실험 기록 폴더:", RUN_DIR, "| TensorBoard:", RUN_LOG.tensorboard)
''')

md("""
### 5d. (선택) 실험 기록 (W&B)

`USE_WANDB`가 켜져 있고 Colab Secret `WANDB_API_KEY`(또는 환경 변수)가 있으면 Weights & Biases에 run을 하나 만든다.
에폭마다 손실과 클래스별 검증 IoU가 기록되고, run 링크가 manifest의 `metrics.experiment`에 들어간다.
키가 없으면 건너뛰고 학습은 그대로 진행한다(5c의 로컬 기록은 W&B와 상관없이 남는다). **키를 셀에 붙여 넣지 않는다**(공개 저장소). 키는 출력하지도, 파일에 쓰지도 않는다.
""")
code('''
#@title 5d. (선택) W&B 실험 기록
if globals().get("WANDB_RUN") is not None:   # 이 셀을 다시 실행: 앞 run을 먼저 닫는다
    WANDB_RUN.finish()
WANDB_RUN = WANDB_EXPERIMENT = None
_key = None
_skip = "USE_WANDB가 꺼져 있거나 Colab Secret WANDB_API_KEY가 없습니다"
_env_key = "WANDB_API_KEY" in os.environ   # GPU PC에서 사용자가 둔 환경 변수는 지우지 않는다
if USE_WANDB:
    try:
        from google.colab import userdata
        try:
            _key = userdata.get("WANDB_API_KEY")
        except (userdata.SecretNotFoundError, userdata.NotebookAccessError):
            _key = None
    except ImportError:   # Colab 밖(GPU PC): 환경 변수를 쓴다
        _key = None
    _key = _key or os.environ.get("WANDB_API_KEY")
if _key:
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "wandb"], check=True)
    import wandb
    # 키는 wandb.init 동안만 이 프로세스의 환경 변수에 둔다(wandb.login()은 ~/.netrc에 키를 쓴다).
    # init이 끝나면(실패해도) 바로 지우므로, 뒤 셀에서 학습이나 내보내기가 멈춰도 키가 남지 않는다.
    os.environ["WANDB_API_KEY"] = _key
    del _key
    try:
        WANDB_RUN = wandb.init(project=WANDB_PROJECT, job_type="train", config=RUN_CONFIG)
    except Exception as _exc:   # 네트워크, 잘못된 키 등: 기록 없이 학습한다
        WANDB_RUN, _skip = None, f"wandb.init 실패: {type(_exc).__name__}"   # 메시지 본문은 출력하지 않는다
    finally:
        if not _env_key:
            os.environ.pop("WANDB_API_KEY", None)
if WANDB_RUN is not None:
    WANDB_EXPERIMENT = {"tracker": "wandb", "run_id": WANDB_RUN.id, "url": WANDB_RUN.url,
                        "project": WANDB_PROJECT}
    print("W&B run:", WANDB_RUN.url)
else:
    print(f"W&B 기록을 건너뜁니다 ({_skip}). 학습은 그대로 진행합니다.")
''')

md("""
## 6. 학습

에폭마다 학습 손실, 검증 손실, 검증 split의 클래스별 IoU를 출력하고, 5c의 실험 기록 폴더(와 W&B가 켜져 있으면 W&B)에도 남긴다.
학습이 끝나면 평균 IoU가 가장 좋았던 에폭의 가중치로 되돌리고, 그 에폭의 IoU를 manifest에 적는다.
""")
code('''
#@title 6. 학습
from rosy_lane_model import train


def _log_epoch(row):
    if WANDB_RUN is not None:
        WANDB_RUN.log({"epoch": row["epoch"], "train_loss": row["train_loss"], "val_loss": row["val_loss"],
                       "mean_val_iou": row["mean_val_iou"],
                       **{f"val_iou/{k}": v for k, v in row["val_iou"].items() if v is not None}},
                      step=row["epoch"])


result = train(model, train_ds, val_ds, epochs=EPOCHS, lr=LR, batch_size=BATCH, device=DEVICE,
               ignore_index=IGNORE_INDEX,
               on_epoch=chain(RUN_LOG.on_epoch, _log_epoch if WANDB_RUN is not None else None))
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
`metrics.experiment`에는 W&B run이 있으면 그 링크, 없으면 로컬 기록 폴더(`tracker: local`)가 들어간다.
로컬 `summary.json`에 가장 좋은 에폭, 검증 IoU, `model_revision`, 내보낸 폴더(상대 경로)를 적고(W&B가 있으면 그 요약에도), run을 닫는다.
끝에 TensorBoard 실행 명령을 출력한다.
""")
code('''
#@title 7. 내보내기
from export_cell import export

TRAINER_ID = f"{TRAINER} colab:rosy_lane_training.ipynb@{REPO_COMMIT} {TRAINER_NOTE}".strip()
OUT_DIR = "out/lane_model"
doc = export(model, OUT_DIR, classes=EXPORT_CLASSES, **PRE.manifest_kwargs(),
             dataset_repo=f"store:{DS_NAME}", dataset_revision=DS_SHA,
             camera_profile_revision=CAMERA_PROFILE_REVISION, trainer=TRAINER_ID, val_iou=VAL_IOU,
             experiment=WANDB_EXPERIMENT or LOCAL_EXPERIMENT)
MODEL_REVISION = doc["model_revision"]
print(MODEL_REVISION)
print("trainer:", TRAINER_ID)
RUN_LOG.finish({"best_epoch": best_epoch, "val_iou": VAL_IOU, "model_revision": MODEL_REVISION,
                "export_dir": OUT_DIR, "trainer": TRAINER_ID,
                "experiment": WANDB_EXPERIMENT or LOCAL_EXPERIMENT})
print("실험 기록 폴더:", RUN_DIR)
print("TensorBoard 보기:  tensorboard --logdir", RUNS_DIR)
if WANDB_RUN is not None:
    WANDB_RUN.summary["best_epoch"] = best_epoch
    WANDB_RUN.summary["model_revision"] = MODEL_REVISION
    for _k, _v in VAL_IOU.items():
        WANDB_RUN.summary[f"best_val_iou/{_k}"] = _v
    WANDB_RUN.finish()
    WANDB_RUN = None
''')

md("""
## 8. 검사

로봇과 같은 코드로 manifest, sha256, ONNX 로드와 워밍업을 확인한다. `OK`가 아니면 넘기지 않는다.
""")
code('''
#@title 8. check_manifest
_r = subprocess.run([sys.executable, os.path.join(ROSY, "learning", "training", "perception", "training", "check_manifest.py"),
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
