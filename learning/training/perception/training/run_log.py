"""Local run records + optional TensorBoard (D-356 addendum 2026-10-03).

Default experiment tracking: history.json / config.json / summary.json in a run folder plus
TensorBoard event files. No torch import at module level; tensorboard is optional.
Never writes secrets: config keys containing token/secret/key/password are dropped."""

from __future__ import annotations

import json
import os
from pathlib import Path

SECRET_WORDS = ("token", "secret", "key", "password")


def _atomic_json(path: Path, doc) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def strip_secrets(doc):
    """Recursively drop dict keys that look like secrets (case-insensitive)."""
    if isinstance(doc, dict):
        return {k: strip_secrets(v) for k, v in doc.items()
                if not any(w in str(k).lower() for w in SECRET_WORDS)}
    if isinstance(doc, (list, tuple)):
        return [strip_secrets(v) for v in doc]
    return doc


def chain(*callbacks):
    """One on_epoch hook that calls every non-None callback in order."""
    active = [c for c in callbacks if c is not None]

    def _hook(row):
        for cb in active:
            cb(row)

    return _hook


class RunLog:
    def __init__(self, run_dir, *, tensorboard: bool = True):
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.history: list[dict] = []
        self.tensorboard = None  # "enabled" | "unavailable" | None (not requested)
        self._writer = None
        if tensorboard:
            try:
                from torch.utils.tensorboard import SummaryWriter
                self._writer = SummaryWriter(log_dir=str(self.run_dir))
                self.tensorboard = "enabled"
            except Exception:  # missing tensorboard/torch: keep the local records only
                self.tensorboard = "unavailable"

    def write_config(self, config: dict) -> None:
        _atomic_json(self.run_dir / "config.json", strip_secrets(config))

    def on_epoch(self, row: dict) -> None:
        self.history.append(row)
        doc = {"history": self.history}
        if self.tensorboard == "unavailable":
            doc["tensorboard"] = "unavailable"
        _atomic_json(self.run_dir / "history.json", doc)
        w = self._writer
        if w is None:
            return
        step = row["epoch"]
        w.add_scalar("loss/train", row["train_loss"], step)
        w.add_scalar("loss/val", row["val_loss"], step)
        if row.get("mean_val_iou") is not None:
            w.add_scalar("iou/mean", row["mean_val_iou"], step)
        for name, v in (row.get("val_iou") or {}).items():
            if v is not None:
                w.add_scalar(f"iou/{name}", v, step)
        w.flush()

    def finish(self, summary: dict) -> None:
        _atomic_json(self.run_dir / "summary.json", strip_secrets(summary))
        if self._writer is not None:
            self._writer.close()
            self._writer = None
