"""D-373 decision 7: the ready-to-run Colab notebook stays valid and token-free."""
import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
NB = ROOT / "tools" / "perception" / "training" / "rosy_lane_training.ipynb"


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
                   "Preprocess", "snapshot_download", "upload_folder", "whoami", "#@param"):
        assert needle in text, needle
    assert "rosy_lane_training.ipynb@" in text   # trainer string carries the notebook commit


def test_no_literal_token():
    raw = NB.read_text(encoding="utf-8")
    assert not re.search(r"hf_[A-Za-z0-9]{20,}", raw)
