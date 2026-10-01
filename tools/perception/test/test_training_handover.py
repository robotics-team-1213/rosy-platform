"""D-373 decision 8: a trainer hands a model over by dropping a READY folder into the store inbox."""
import ast
import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
for p in (ROOT / "tools" / "perception", ROOT / "tools" / "perception" / "training"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import handover  # noqa: E402
import store  # noqa: E402

REV = "lane-seg-20260930-0123abcd"


def _model(folder: Path, rev: str = REV) -> Path:
    folder.mkdir(parents=True)
    (folder / "model.onnx").write_bytes(b"weights")
    (folder / "model_manifest.json").write_text(json.dumps({
        "model_revision": rev, "files": [{"name": "model.onnx", "sha256": "0" * 64}]}),
        encoding="utf-8")
    (folder / "scratch.pt").write_bytes(b"not handed over")
    return folder


def test_package_drops_a_ready_folder_named_after_the_revision(tmp_path):
    st = store.Store(tmp_path / "store")
    dest = handover.package(_model(tmp_path / "out"), st.inbox)
    assert dest.parent == st.inbox and dest.name.startswith(REV + "__")
    assert sorted(p.name for p in dest.iterdir()) == ["READY", "model.onnx",
                                                      "model_manifest.json"]
    assert st.inbox_ready(dest.name) and st.list_inbox() == [dest.name]


def test_ready_is_written_last(tmp_path, monkeypatch):
    order = []
    real_copy = handover.shutil.copy2

    def copy(src, dst, **kw):
        order.append(Path(dst).name)
        return real_copy(src, dst, **kw)
    monkeypatch.setattr(handover.shutil, "copy2", copy)
    real_write = Path.write_text

    def write(self, *a, **kw):
        order.append(self.name)
        return real_write(self, *a, **kw)
    monkeypatch.setattr(Path, "write_text", write)
    handover.package(_model(tmp_path / "out"), tmp_path / "inbox")
    assert order[-1] == "READY" and "model.onnx" in order[:-1]


@pytest.mark.parametrize("rev", ["../x", "", "a b"])
def test_package_refuses_a_bad_revision(tmp_path, rev):
    with pytest.raises(ValueError):
        handover.package(_model(tmp_path / "out", rev), tmp_path / "inbox")
    assert not (tmp_path / "inbox").exists() or not list((tmp_path / "inbox").iterdir())


def test_package_refuses_a_missing_file(tmp_path):
    folder = _model(tmp_path / "out")
    (folder / "model.onnx").unlink()
    with pytest.raises(FileNotFoundError):
        handover.package(folder, tmp_path / "inbox")


def test_zip_unpacks_into_a_ready_inbox_folder(tmp_path):
    zpath = handover.package_zip(_model(tmp_path / "out"), tmp_path / "hand.zip")
    st = store.Store(tmp_path / "store")
    st.ensure_layout()
    with zipfile.ZipFile(zpath) as z:
        tops = {n.split("/")[0] for n in z.namelist()}
        assert len(tops) == 1 and next(iter(tops)).startswith(REV + "__")
        z.extractall(st.inbox)
    assert st.list_inbox() == [next(iter(tops))]


def test_handover_imports_only_the_stdlib_and_store():
    tree = ast.parse((ROOT / "tools/perception/training/handover.py").read_text(encoding="utf-8"))
    mods = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import)
            for a in n.names}
    mods |= {n.module.split(".")[0] for n in ast.walk(tree)
             if isinstance(n, ast.ImportFrom) and n.module}
    assert mods <= {"__future__", "datetime", "json", "shutil", "sys", "tempfile", "zipfile",
                    "pathlib", "os", "store"}, mods
