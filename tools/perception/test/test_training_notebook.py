"""D-373 decision 7: the ready-to-run Colab notebook stays valid and token-free."""
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TRAINING = ROOT / "tools" / "perception" / "training"
NB = TRAINING / "rosy_lane_training.ipynb"


def _nb():
    return json.loads(NB.read_text(encoding="utf-8"))


def _src(cell):
    return "".join(cell["source"]) if isinstance(cell["source"], list) else cell["source"]


def _code_cells():
    return [_src(c) for c in _nb()["cells"] if c["cell_type"] == "code"]


def test_nbformat_4_and_colab_ready():
    nb = _nb()
    assert nb["nbformat"] == 4
    assert nb["metadata"]["kernelspec"]["language"] == "python"
    assert any(c["cell_type"] == "markdown" for c in nb["cells"])
    for c in nb["cells"]:
        assert c["cell_type"] in ("code", "markdown")
        if c["cell_type"] == "code":
            assert c["outputs"] == [] and c["execution_count"] is None


def test_every_code_cell_parses():
    for src in _code_cells():
        body = "\n".join(line for line in src.splitlines()
                         if not line.lstrip().startswith(("!", "%")))
        ast.parse(body)


def test_references_the_contract_and_baseline():
    text = "\n".join(_code_cells())
    for needle in ("export_cell", "export(", "check_manifest", "RosyLaneDataset", "LaneUNet",
                   "Preprocess", "#@param", "content_sha(", "parse_dataset_ref", "drive.mount",
                   "package(", "package_zip(", "files.upload", "files.download"):
        assert needle in text, needle
    assert "rosy_lane_training.ipynb@" in text   # trainer string carries the notebook commit
    assert '"pull", "--ff-only"' in text           # an existing clone is refreshed
    assert 'dataset_repo=f"store:{DS_NAME}"' in text and "dataset_revision=DS_SHA" in text
    assert "best_epoch" in text


def _cell(prefix):
    return next(s for s in _code_cells() if s.startswith(prefix))


def test_hf_is_optional_and_only_in_the_last_cell():
    cells = _code_cells()
    uses_hf = [i for i, s in enumerate(cells) if "huggingface_hub" in s]
    assert uses_hf == [len(cells) - 1]
    hf = cells[-1]
    assert hf.startswith("#@title 10. (선택)") and "USE_HF = False" in hf
    assert "if USE_HF:" in hf and "repo_info(" in hf and "RepositoryNotFoundError" in hf
    assert "%pip install -q onnx onnxruntime\n" in _cell("#@title 1.")


def test_hf_login_never_prints_or_embeds_the_token():
    login = _cell("#@title 10.")
    assert "getpass" in login and "RuntimeError" in login and "del _token" in login
    assert not re.search(r"print\([^)]*_token", login)


def test_dataset_hash_mismatch_stops():
    fetch = _cell("#@title 3.")
    assert "content_sha(DS_DIR)" in fetch and "!= DS_SHA" in fetch
    assert "경고" in fetch and "raise RuntimeError" in fetch


def test_handover_writes_ready_via_store_or_zip():
    give = _cell("#@title 9.")
    assert 'os.path.join(STORE, "models", "inbox")' in give and "package_zip(" in give


def test_placeholder_stop_names_the_field():
    form = _cell("#@title 2.")
    assert "2단계 입력 칸의 TRAINER" in form and "2단계 입력 칸의 DATASET" in form
    assert "HF_DATASET" not in form and "huggingface" not in form


def test_notebook_is_regenerated_from_generator():
    if str(TRAINING) not in sys.path:
        sys.path.insert(0, str(TRAINING))
    import gen_notebook

    committed = NB.read_bytes().decode("utf-8").replace("\r\n", "\n")
    assert gen_notebook.render() == committed


def test_no_literal_token():
    raw = NB.read_text(encoding="utf-8")
    assert not re.search(r"hf_[A-Za-z0-9]{20,}", raw)


DEFAULT_CLASSES = ("floor:background,lane_line:lane_marking,wall:wall,drivable:drivable,"
                   "stop_line:stop_line,crosswalk:ignore")


def test_default_class_list_is_the_decision_9_list_and_mismatch_stops():
    form = _cell("#@title 2.")
    assert f'CLASSES = "{DEFAULT_CLASSES}"  #@param' in form
    read = _cell("#@title 4.")
    assert "class_mismatch(_form, ds_classes)" in read and "raise RuntimeError" in read
