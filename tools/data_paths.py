"""Host-side data location; explicit tool arguments remain authoritative."""

import os
from pathlib import Path


def data_root(repo: Path) -> Path:
    configured = os.environ.get("ROSY_DATA_ROOT")
    if configured is None:
        return repo / "data"
    root = Path(configured).expanduser()
    if not configured.strip() or not root.is_absolute():
        raise ValueError("ROSY_DATA_ROOT must be an absolute path")
    return root
