"""Frozen A/B recovery after actual projection and root-specific factory admission."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from native_release import NativeReleaseManager
from os_factory_release import PUBLIC_KEY, prepare_factory
from os_state_firstboot import _hold


def _reconciler():
    path = Path(__file__).with_name("image-layer-reconcile.py")
    spec = importlib.util.spec_from_file_location("os_image_layer_reconcile", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@_hold
def recover(root: Path, *, run=subprocess.run) -> dict:
    root = Path(root).absolute()
    factory = prepare_factory(root)
    manager = NativeReleaseManager(root=root, public_key=root / PUBLIC_KEY)
    report = manager.recover(admit_current=True)

    def checked_run(argv):
        result = run(argv, capture_output=True, timeout=120, check=False)
        if result.returncode:
            raise ValueError("OS recovery reload command failed")
        return result

    reconciled = _reconciler().reconcile_at_boot(root, run=checked_run)
    return dict(schema_version=1, phase="RECOVERED", release_id=report["release_id"],
                factory_release_id=factory["release_id"], native_recovered=report["recovered"],
                image_layer=reconciled)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/"))
    args = parser.parse_args(argv)
    try:
        report = recover(args.root)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print(json.dumps({"schema_version": 1, "phase": "HOLD", "reason": "OS_RECOVERY_HOLD"}))
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
