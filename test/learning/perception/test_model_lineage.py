"""A lineage query binds existing owner records without admitting a candidate."""
import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "learning/registry/perception"))
from store import content_sha  # noqa: E402
from test_model_deliver import _model  # noqa: E402


def _fixed(root, name, doc):
    temp = root / "building"
    temp.mkdir(parents=True)
    (temp / "manifest.json").write_text(json.dumps(doc))
    fixed = root / name / content_sha(temp)
    fixed.parent.mkdir(parents=True)
    temp.rename(fixed)
    return fixed


@pytest.fixture
def candidate(tmp_path):
    models, store = tmp_path / "models", tmp_path / "store"
    dataset = _fixed(store / "datasets", "train", {"builder": "auto-labels", "sources": ["capture-a"]})
    evaluation = _fixed(store / "evalsets", "heldout", {"sources": ["capture-b"]})
    revision = _model(models, "pass")
    folder = models / revision
    path = folder / "model_manifest.json"
    doc = json.loads(path.read_text())
    doc["dataset"].update(repo="store:train", revision=dataset.name)
    path.write_text(json.dumps(doc))
    report = folder / "intake_report.json"
    doc = json.loads(report.read_text())
    doc.update(tool_commit=None, eval={"set": {"path": f"/old/store/evalsets/heldout/{evaluation.name}",
                                               "content_sha": evaluation.name}})
    report.write_text(json.dumps(doc))
    return models, store, revision, dataset, evaluation


def query(candidate, **kwargs):
    return importlib.import_module("model_lineage").inspect_model(*candidate[:3], **kwargs)


def test_one_candidate_binds_content_and_records_missing_proofs(candidate):
    result = query(candidate)
    assert result["model"]["revision"] == candidate[2]
    assert result["dataset"]["content_sha"] == candidate[3].name
    assert result["dataset"]["declared"]["builder"] == "auto-labels"
    assert result["eval"]["path"] == str(candidate[4])
    assert result["intake"]["verdict"] == "pass"
    assert {"source_proof", "human_review", "training_receipt", "tool_commit", "delivery"} <= set(result["missing"])
    assert "approved" not in result


@pytest.mark.parametrize("part", ["model", "dataset", "eval"])
def test_tampered_content_is_refused(candidate, part):
    folder = {"model": candidate[0] / candidate[2], "dataset": candidate[3], "eval": candidate[4]}[part]
    path = folder / ("model.onnx" if part == "model" else "manifest.json")
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="sha256|content hash"):
        query(candidate)


@pytest.mark.parametrize("field,value", [("model_revision", "another-candidate"), ("files", [])])
def test_other_or_unbound_intake_is_refused(candidate, field, value):
    path = candidate[0] / candidate[2] / "intake_report.json"
    doc = json.loads(path.read_text())
    doc[field] = value
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="intake"):
        query(candidate)


def test_missing_named_data_does_not_select_another_name(candidate):
    candidate[3].rename(candidate[3].with_name("b" * 64))
    result = query(candidate)
    assert result["dataset"] is None
    assert "dataset" in result["missing"]


def test_missing_intake_is_partial_result(candidate):
    (candidate[0] / candidate[2] / "intake_report.json").unlink()
    result = query(candidate)
    assert result["intake"] is None and result["eval"] is None
    assert {"intake", "eval"} <= set(result["missing"])


def test_symlinked_dataset_cannot_escape_store(candidate, tmp_path):
    original = candidate[3]
    outside = tmp_path / "outside"
    original.rename(outside)
    original.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="escapes|symlink"):
        query(candidate)


def test_eval_path_cannot_rebind_a_different_hash(candidate):
    path = candidate[0] / candidate[2] / "intake_report.json"
    doc = json.loads(path.read_text())
    doc["eval"]["set"]["path"] = "/outside/heldout/" + candidate[4].name
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="eval path/content hash"):
        query(candidate)


def test_malformed_intake_json_is_refused(candidate):
    (candidate[0] / candidate[2] / "intake_report.json").write_text("{")
    with pytest.raises(ValueError):
        query(candidate)


def test_journal_filters_candidate_and_preserves_consumer_mismatch(candidate, tmp_path):
    journal = tmp_path / "pointer_changes.jsonl"
    rows = [{"schema": "rosy.model-pointer-change/1", "pointer_revision": revision,
             "node_revision": "other", "readback": "mismatch"}
            for revision in ["another-candidate", candidate[2]]]
    journal.write_text("\n".join(map(json.dumps, rows)))
    assert query(candidate, journal=journal)["delivery"] == [rows[1]]


@pytest.mark.parametrize("revision", ["../escape", "/outside", "bad"])
def test_invalid_revision_is_refused(candidate, revision):
    module = importlib.import_module("model_lineage")
    with pytest.raises(ValueError):
        module.inspect_model(candidate[0], candidate[1], revision)


def test_cli_is_read_only_and_reports_errors(candidate, capsys):
    module = importlib.import_module("model_lineage")
    root = candidate[0].parent
    before = {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    args = ["--models", str(candidate[0]), "--store", str(candidate[1]), "--revision", candidate[2]]
    assert module.main(args) == 0
    assert json.loads(capsys.readouterr().out)["model"]["revision"] == candidate[2]
    assert module.main([*args[:-1], "../escape"]) == 2
    assert "error" in capsys.readouterr().err.lower()
    assert before == {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}
