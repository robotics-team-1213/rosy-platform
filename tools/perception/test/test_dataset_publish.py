"""D-373 decision 8: publish.py writes the dataset into the store; HF is optional."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
for p in (ROOT / "tools" / "perception", ROOT / "tools" / "perception" / "dataset"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import publish  # noqa: E402
import store  # noqa: E402


def _dataset(root: Path) -> Path:
    frames = []
    for i in range(3):
        img, mask = f"images/s1/{i:06d}.jpg", f"masks/s1/{i:06d}.png"
        for rel in (img, mask):
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_bytes(f"{rel}".encode())
        frames.append({"image": img, "mask": mask, "session": "s1", "split": "train"})
    (root / "manifest.json").write_text(json.dumps({"frames": frames}), encoding="utf-8")
    return root


def test_publish_to_the_store_prints_the_ref(tmp_path, capsys, monkeypatch):
    monkeypatch.setitem(sys.modules, "huggingface_hub", None)  # HF is never touched
    src = _dataset(tmp_path / "lane-0930")
    assert publish.main([str(src), "--store", str(tmp_path / "store")]) == 0
    out = capsys.readouterr().out
    line = next(l for l in out.splitlines() if l.startswith("dataset: "))
    name, sha = store.parse_dataset_ref(line.removeprefix("dataset: "))
    assert name == "lane-0930"
    path = store.Store(tmp_path / "store").dataset_path(name, sha)
    assert store.content_sha(path) == sha
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["frames"][0]["image"].startswith("images/shard_0000/")
    # publishing the same build again gives the same ref
    assert publish.main([str(src), "--store", str(tmp_path / "store")]) == 0
    assert f"dataset: store:{name}@{sha}" in capsys.readouterr().out


def test_publish_name_flag_and_config_default(tmp_path, capsys, monkeypatch):
    cfg = tmp_path / "ml.yaml"
    cfg.write_text(f"store: {json.dumps(str(tmp_path / 'cfgstore'))}\n", encoding="utf-8")
    monkeypatch.setenv("ROSY_ML_CONFIG", str(cfg))
    src = _dataset(tmp_path / "d")
    assert publish.main([str(src), "--name", "lane"]) == 0
    assert "dataset: store:lane@" in capsys.readouterr().out
    assert (tmp_path / "cfgstore" / "datasets" / "lane").is_dir()


def test_publish_without_store_or_hf_is_refused(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ROSY_ML_CONFIG", str(tmp_path / "missing.yaml"))
    assert publish.main([str(_dataset(tmp_path / "d"))]) == 2
    assert "--store" in capsys.readouterr().err


def test_publish_rejects_a_bad_name(tmp_path):
    with pytest.raises(SystemExit):
        publish.main([str(_dataset(tmp_path / "d")), "--store", str(tmp_path / "s"),
                      "--name", "../x"])
