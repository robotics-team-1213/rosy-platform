#!/usr/bin/env python3
"""Run the real tools/release/publish_payload_release.py against the device twin (twin only).

publish_payload_release.main() takes its `gh` and `ssh` runners as arguments.
This wrapper keeps everything else real and only redirects those two programs:

- `gh ...`  -> `python fake_gh.py ...` (the fake GitHub store, TWIN_GH_STORE);
- `ssh ... rosy@<host> <command>` -> `docker exec -u rosy <TWIN_CONTAINER> bash -c <command>`.

LOCALAPPDATA must point at the twin's folder (the throwaway key lives in
<LOCALAPPDATA>/Rosy/signing/<key-name>.private.pem); this wrapper refuses to run otherwise.

    python tools/device_twin/twin_publish.py --tarball X:/DevTemp/d406-twin/releases/<id>.tar.gz \
        --canary rosy-pinky-twin --repo twin/rosy-os --key-name twin-d406-test --public-key <pem> ...
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def _load_publish():
    spec = importlib.util.spec_from_file_location("publish_payload_release",
                                                  ROOT / "tools/release/publish_payload_release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(argv: list[str], timeout: float) -> tuple[int, str, str]:
    try:
        done = subprocess.run(argv, capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        return 255, "", f"{type(error).__name__}: {error}"
    return done.returncode, done.stdout.decode("utf-8", "replace"), done.stderr.decode("utf-8", "replace")


def fake_gh(argv: list[str]) -> tuple[int, str, str]:
    assert argv[0] == "gh", argv
    return _run([sys.executable, str(HERE / "fake_gh.py"), *argv[1:]], 300)


def fake_ssh(argv: list[str]) -> tuple[int, str, str]:
    assert argv[0] == "ssh" and argv[-2].startswith("rosy@"), argv
    container = os.environ["TWIN_CONTAINER"]
    return _run(["docker", "exec", "-u", "rosy", container, "bash", "-c", argv[-1]], 60)


def main() -> int:
    appdata = os.environ.get("LOCALAPPDATA", "")
    if "d406-twin" not in appdata.replace("\\", "/"):
        print("refusing: LOCALAPPDATA must point at the twin folder, never the operator's signing folder",
              file=sys.stderr)
        return 2
    if not os.environ.get("TWIN_GH_STORE") or not os.environ.get("TWIN_CONTAINER"):
        print("TWIN_GH_STORE and TWIN_CONTAINER are required", file=sys.stderr)
        return 2
    publish = _load_publish()
    return publish.main(sys.argv[1:], gh_runner=fake_gh, ssh_runner=fake_ssh)


if __name__ == "__main__":
    raise SystemExit(main())
