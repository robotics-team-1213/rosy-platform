"""D-356 addendum 2026-10-03: local run records + optional TensorBoard."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
TRAINING = ROOT / "learning" / "training" / "perception" / "training"
if str(TRAINING) not in sys.path:
    sys.path.insert(0, str(TRAINING))

import run_log  # noqa: E402
from run_log import RunLog, chain  # noqa: E402


def _row(epoch):
    return {"epoch": epoch, "train_loss": 1.0 / epoch, "val_loss": 2.0 / epoch,
            "val_iou": {"lane": 0.5, "wall": None}, "mean_val_iou": 0.5}


def test_history_is_written_every_epoch_without_leftover_tmp(tmp_path):
    log = RunLog(tmp_path / "r", tensorboard=False)
    for e in (1, 2):
        log.on_epoch(_row(e))
        doc = json.loads((tmp_path / "r" / "history.json").read_text(encoding="utf-8"))
        assert [r["epoch"] for r in doc["history"]] == list(range(1, e + 1))
    assert not list((tmp_path / "r").glob("*.tmp"))
    assert log.tensorboard is None


def test_config_drops_secret_keys_and_sorts(tmp_path):
    log = RunLog(tmp_path, tensorboard=False)
    log.write_config({"lr": 0.1, "WANDB_API_KEY": "x", "hf_Token": "y", "Password": "z",
                      "nested": {"client_secret": "s", "epochs": 3}, "batch": 8})
    text = (tmp_path / "config.json").read_text(encoding="utf-8")
    assert json.loads(text) == {"batch": 8, "lr": 0.1, "nested": {"epochs": 3}}
    assert text.index('"batch"') < text.index('"lr"')
    for leak in ("WANDB", "hf_Token", "Password", "client_secret", '"x"', '"s"'):
        assert leak not in text


def test_finish_writes_summary_and_closes_writer(tmp_path):
    log = RunLog(tmp_path, tensorboard=False)
    closed = []

    class W:
        def close(self):
            closed.append(1)

    log._writer = W()
    log.finish({"best_epoch": 2, "model_revision": "m", "api_token": "no"})
    assert json.loads((tmp_path / "summary.json").read_text(encoding="utf-8")) == \
        {"best_epoch": 2, "model_revision": "m"}
    assert closed == [1] and log._writer is None


def test_tensorboard_unavailable_is_recorded_and_training_continues(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "torch.utils.tensorboard", None)  # import raises ImportError
    log = RunLog(tmp_path, tensorboard=True)
    assert log.tensorboard == "unavailable"
    log.on_epoch(_row(1))
    doc = json.loads((tmp_path / "history.json").read_text(encoding="utf-8"))
    assert doc["tensorboard"] == "unavailable" and len(doc["history"]) == 1


def test_tensorboard_scalars_are_named_per_class(tmp_path, monkeypatch):
    import types
    calls = []

    class FakeWriter:
        def __init__(self, log_dir):
            calls.append(("dir", log_dir))

        def add_scalar(self, tag, value, step):
            calls.append((tag, value, step))

        def flush(self):
            pass

        def close(self):
            calls.append("closed")

    mod = types.ModuleType("torch.utils.tensorboard")
    mod.SummaryWriter = FakeWriter
    monkeypatch.setitem(sys.modules, "torch.utils.tensorboard", mod)
    log = RunLog(tmp_path, tensorboard=True)
    log.on_epoch(_row(2))
    log.finish({})
    tags = [c[0] for c in calls if isinstance(c, tuple) and len(c) == 3]
    assert tags == ["loss/train", "loss/val", "iou/mean", "iou/lane"]  # None IoU skipped
    assert calls[-1] == "closed"


def test_chain_skips_none_and_keeps_order():
    seen = []
    hook = chain(None, lambda r: seen.append(("a", r)), None, lambda r: seen.append(("b", r)))
    hook(1)
    assert seen == [("a", 1), ("b", 1)]
    chain()(1)


def test_module_imports_no_torch_at_top_level():
    assert "import torch" not in "\n".join(
        ln for ln in Path(run_log.__file__).read_text(encoding="utf-8").splitlines()
        if not ln.startswith(" "))
