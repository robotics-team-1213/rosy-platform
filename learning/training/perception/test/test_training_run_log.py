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


def test_tensorboard_write_error_never_stops_training(tmp_path, monkeypatch):
    class Broken:
        closed = 0

        def add_scalar(self, *a):
            raise RuntimeError("disk full")

        def flush(self):
            pass

        def close(self):
            Broken.closed += 1

    log = RunLog(tmp_path, tensorboard=False)
    log._writer = Broken()
    log.tensorboard = "enabled"
    log.on_epoch(_row(1))
    log.on_epoch(_row(2))  # writer is gone, still fine
    assert log.tensorboard == "error" and log.tensorboard_error == "RuntimeError"
    assert log._writer is None and Broken.closed == 1
    doc = json.loads((tmp_path / "history.json").read_text(encoding="utf-8"))
    assert len(doc["history"]) == 2 and doc["tensorboard"] == "error"
    assert doc["tensorboard_error"] == "RuntimeError"


def test_history_write_oserror_is_counted_not_raised(tmp_path, monkeypatch):
    log = RunLog(tmp_path, tensorboard=False)

    def boom(path, doc):
        raise OSError("read-only")

    monkeypatch.setattr(run_log, "_atomic_json", boom)
    log.on_epoch(_row(1))
    log.write_config({"a": 1})
    log.finish({"b": 1})
    assert log.write_errors == 3 and len(log.history) == 1


def test_row_missing_keys_is_tolerated(tmp_path):
    log = RunLog(tmp_path, tensorboard=False)
    log.on_epoch({})
    log.on_epoch({"epoch": 2, "val_iou": None})
    assert len(log.history) == 2


def test_close_is_idempotent(tmp_path):
    log = RunLog(tmp_path, tensorboard=False)
    n = []

    class W:
        def close(self):
            n.append(1)

    log._writer = W()
    log.close()
    log.close()
    log.finish({})
    assert n == [1]


def test_chain_continues_after_a_raising_callback_but_not_ctrl_c():
    import pytest
    seen = []

    def bad(r):
        raise ValueError("x")

    chain(bad, lambda r: seen.append(r))(7)
    assert seen == [7]

    def interrupt(r):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        chain(interrupt, lambda r: seen.append("no"))(1)
    assert seen == [7]


def test_more_secret_words_are_dropped_and_values_are_not_scanned(tmp_path):
    log = RunLog(tmp_path, tensorboard=False)
    cfg = {"passwd": 1, "DB_PWD": 1, "Credentials": 1, "oauth": 1, "Bearer": 1, "cookie_jar": 1,
           "private_note": 1, "note": "sk-looks-secret"}
    log.write_config(cfg)
    assert json.loads((tmp_path / "config.json").read_text(encoding="utf-8")) == {"note": "sk-looks-secret"}
