#!/usr/bin/env python3
"""Settle an image-layer sync that a power loss cut off, at boot (D-798).

sync-image-layer.py replaces /opt/rosy/native-runtime files one at a time; a run that stops
between its first change and its files_applied flag leaves files from two releases there. Its
reconcile() finishes such a run (every file landed) or undoes it from the backups, but only on
the next sync. rosy-release-recover runs this after recovery, before rosy-core and the runtime
target start, so no service starts on a mix. It only reconciles: no plan, no install, no
restart. Reload/enable work it owes goes to pending.json for the next sync, as reconcile() does.

    python3 -I -B image-layer-reconcile.py [--root /]   # JSON report on stdout
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from typing import Callable

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent


def _sync_module():
    spec = importlib.util.spec_from_file_location("image_layer_sync_for_reconcile", HERE / "sync-image-layer.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def reconcile_at_boot(root: Path, run: Callable[[list[str]], object] = subprocess.run) -> dict:
    sync = _sync_module()
    pending, _, _ = sync.reconcile(root, dry_run=True)
    if not pending:  # the usual boot: nothing unfinished, no lock taken, nothing written
        return {"reconciled": []}
    with sync._release_lock(root):
        report, steps, _ = sync.reconcile(root, dry_run=False)
    # Units start right after this; they must see the unit files reconcile left.
    if steps["daemon_reload"]:
        run(["systemctl", "daemon-reload"])
    if steps["udev_reload"]:
        run(["udevadm", "control", "--reload"])
    return {"reconciled": report}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=Path("/"))
    args = parser.parse_args(argv)
    print(json.dumps(reconcile_at_boot(args.root), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
