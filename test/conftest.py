"""Make the release tooling importable from the contract tests.

``deploy/release`` is shipped as scripts on the build host rather than as an
installed package, so it is not on ``sys.path``. Bootstrapping it here keeps
the test modules free of import-order gymnastics.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

for path in (
    ROOT / "deploy" / "release",
    ROOT / "tools" / "harness",
    ROOT / "src" / "contracts" / "foundation",
    ROOT / "src" / "site" / "fleet",
):
    entry = str(path)
    if entry not in sys.path:
        sys.path.insert(0, entry)

# Windows 호스트는 PATH 에 openssl 이 없는 대신 Git for Windows 를 들고 있는
# 경우가 많다. 서명·readback·bundle 계약이 전부 openssl 을 부르므로, 없으면
# 여기서 Git 것을 PATH 앞에 붙인다. 있으면 무엇도 건드리지 않는다.
if os.name == "nt" and shutil.which("openssl") is None:
    for candidate in (
        r"C:\Program Files\Git\usr\bin",
        r"C:\Program Files\Git\mingw64\bin",
    ):
        if os.path.isfile(os.path.join(candidate, "openssl.exe")):
            os.environ["PATH"] = candidate + os.pathsep + os.environ.get("PATH", "")
            break
