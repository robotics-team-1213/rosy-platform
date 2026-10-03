"""Local run records + optional TensorBoard (D-356 addendum 2026-10-03).

Default experiment tracking: history.json / config.json / summary.json in a run folder plus
TensorBoard event files. No torch import at module level; tensorboard is optional.
Logging never stops training: TensorBoard and file errors are recorded, not raised.

Secrets: config/summary keys containing a secret-looking word are dropped. Only key NAMES are
checked, values are not scanned, so config must not carry free-text secrets."""

from __future__ import annotations

import json
import os
from pathlib import Path

SECRET_WORDS = ("token", "secret", "key", "password", "passwd", "pwd", "credential",
                "auth", "bearer", "cookie", "private")


def _atomic_json(path: Path, doc) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def strip_secrets(doc):
    """Recursively drop dict keys that look like secrets (case-insensitive, key names only)."""
    if isinstance(doc, dict):
        return {k: strip_secrets(v) for k, v in doc.items()
                if not any(w in str(k).lower() for w in SECRET_WORDS)}
    if isinstance(doc, (list, tuple)):
        return [strip_secrets(v) for v in doc]
    return doc


def chain(*callbacks):
    """One on_epoch hook that calls every non-None callback in order. A callback that raises an
    Exception is reported and skipped; the rest still run (KeyboardInterrupt is not caught)."""
    active = [c for c in callbacks if c is not None]

    def _hook(row):
        for cb in active:
            try:
                cb(row)
            except Exception as exc:
                print(f"warning: on_epoch hook failed ({type(exc).__name__}); training continues")

    return _hook


class RunLog:
    def __init__(self, run_dir, *, tensorboard: bool = True):
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.history: list[dict] = []
        self.tensorboard = None  # None (not requested) | "enabled" | "unavailable" | "error"
        self.tensorboard_error = None  # exception type name, set once
        self.write_errors = 0  # failed file writes (history/config/summary), never raised
        self._writer = None
        if tensorboard:
            try:
                from torch.utils.tensorboard import SummaryWriter
                self._writer = SummaryWriter(log_dir=str(self.run_dir))
                self.tensorboard = "enabled"
            except Exception:  # missing tensorboard/torch: keep the local records only
                self.tensorboard = "unavailable"

    def _write(self, name: str, doc) -> None:
        try:
            _atomic_json(self.run_dir / name, doc)
        except OSError:
            self.write_errors += 1

    def write_config(self, config: dict) -> None:
        self._write("config.json", strip_secrets(config))

    def on_epoch(self, row: dict) -> None:
        self.history.append(row)
        self._write_history()
        w = self._writer
        if w is None:
            return
        try:
            step = row.get("epoch", len(self.history))
            for tag, value in (("loss/train", row.get("train_loss")), ("loss/val", row.get("val_loss")),
                               ("iou/mean", row.get("mean_val_iou"))):
                if value is not None:
                    w.add_scalar(tag, value, step)
            for name, v in (row.get("val_iou") or {}).items():
                if v is not None:
                    w.add_scalar(f"iou/{name}", v, step)
            w.flush()
        except Exception as exc:  # a broken writer must not stop training
            self.tensorboard = "error"
            self.tensorboard_error = type(exc).__name__
            self.close()
            self._write_history()

    def _write_history(self) -> None:
        doc = {"history": self.history}
        if self.tensorboard in ("unavailable", "error"):
            doc["tensorboard"] = self.tensorboard
        if self.tensorboard_error:
            doc["tensorboard_error"] = self.tensorboard_error
        if self.write_errors:
            doc["write_errors"] = self.write_errors
        self._write("history.json", doc)

    def close(self) -> None:
        """Close the TensorBoard writer; safe to call more than once."""
        w, self._writer = self._writer, None
        if w is not None:
            try:
                w.close()
            except Exception:
                pass

    def finish(self, summary: dict) -> None:
        self._write("summary.json", strip_secrets(summary))
        self.close()
