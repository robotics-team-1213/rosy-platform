"""D-365 — 서비스 워커 SHELL 은 앱이 부팅에 쓰는 모든 모듈을 담는다.

정적 import 하나가 SHELL 에 없으면 오프라인 셸은 그 모듈에서 멈춘다(2026-09-30 리뷰:
drive.js 가 부르는 /common/evidence.js 가 빠져 있었다). 모든 pilot 모듈의 import 를 따라가며
(/common/* 도 따라간다) 닿는 URL 이 SHELL 에 있는지, SHELL 의 /pilot/assets/* 가 CORE
allowlist(app.py pilot_assets)에 있는지 본다.
"""

from __future__ import annotations

import posixpath
import re
from pathlib import Path

PILOT = Path(__file__).resolve().parents[1]
REPO = PILOT.parents[2]
COMMON = REPO / "shared" / "web"
APP = REPO / "src/runtime/api_web/core_api_web/api/app.py"

IMPORT = re.compile(
    r"""(?:^|[;\s])(?:import|export)\s+(?:[\w*{}\s,$]+?\s+from\s+)?["']([^"']+)["']"""
    r"""|\bimport\(\s*["']([^"']+)["']\s*\)""",
    re.M,
)


def _shell() -> set[str]:
    text = (PILOT / "sw.js").read_text(encoding="utf-8")
    block = re.search(r"const SHELL = \[(.*?)\];", text, re.S)
    assert block, "sw.js 에 SHELL 이 없다"
    return set(re.findall(r'"([^"]+)"', block.group(1)))


def _pilot_assets() -> set[str]:
    text = APP.read_text(encoding="utf-8")
    block = re.search(r"pilot_assets = \{(.*?)\n    \}", text, re.S)
    assert block, "app.py 에 pilot_assets 가 없다"
    return set(re.findall(r'^\s*"([^"]+)":', block.group(1), re.M))


def _file_for(url: str) -> Path:
    if url.startswith("/pilot/assets/"):
        return PILOT / url.removeprefix("/pilot/assets/")
    if url.startswith("/common/"):
        return COMMON / url.removeprefix("/common/")
    raise AssertionError(f"알 수 없는 모듈 URL: {url}")


def _imports(url: str) -> set[str]:
    source = _file_for(url).read_text(encoding="utf-8")
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    source = re.sub(r"^\s*//.*$", "", source, flags=re.M)
    found = set()
    for static, dynamic in IMPORT.findall(source):
        spec = static or dynamic
        found.add(spec if spec.startswith("/") else posixpath.normpath(posixpath.join(posixpath.dirname(url), spec)))
    return found


def _pilot_modules() -> set[str]:
    return {
        "/pilot/assets/" + path.relative_to(PILOT).as_posix()
        for path in PILOT.rglob("*.js")
        if "test" not in path.relative_to(PILOT).parts and path.name != "sw.js"
    }


def _reachable() -> dict[str, str]:
    """URL -> 그 URL 을 부르는 모듈. 모든 pilot 모듈에서 시작해 import 를 끝까지 따라간다."""
    seen: dict[str, str] = {}
    todo = [(url, "<pilot>") for url in sorted(_pilot_modules() | {"/common/ui.js"})]
    while todo:
        url, parent = todo.pop()
        if url in seen:
            continue
        seen[url] = parent
        assert _file_for(url).is_file(), f"{parent} 가 없는 모듈을 부른다: {url}"
        todo.extend((child, url) for child in _imports(url))
    return seen


def test_the_import_walk_finds_the_known_edges():
    reachable = _reachable()
    assert reachable["/common/evidence.js"] == "/pilot/assets/screens/drive.js"
    assert "/pilot/assets/screens/drive-auto.js" in reachable
    assert "/pilot/assets/autonomy.js" in reachable


def test_every_module_the_app_can_import_is_in_the_shell():
    shell = _shell()
    missing = {url: parent for url, parent in _reachable().items() if url not in shell}
    assert missing == {}, f"SHELL 에 없음 (URL: 부르는 모듈): {missing}"


def test_every_shell_pilot_asset_is_served_by_core():
    served = _pilot_assets()
    missing = sorted(url for url in _shell()
                     if url.startswith("/pilot/assets/") and url.removeprefix("/pilot/assets/") not in served)
    assert missing == [], missing


def _dict_keys(path: Path, name: str) -> set[str]:
    text = path.read_text(encoding="utf-8")
    block = re.search(rf"{name} = \{{(.*?)\n\}}", text, re.S)
    assert block, f"{path.name} 에 {name} 가 없다"
    return set(re.findall(r'"([^"]+)":', block.group(1)))


def test_the_sim_server_and_dev_server_serve_the_same_pilot_assets_as_core():
    """D-411 구조 규칙 6: app.js 가 drive.js 를 정적으로 부르므로 OMX SIM·개발 서버도 모두 서빙한다."""
    core = _pilot_assets()
    sim = _dict_keys(REPO / "middleware/apps/device/omx/adapter/omx_adapter/pilot_sim_api.py", "PILOT_ASSETS")
    dev = _dict_keys(PILOT / "test/dev_server.py", "PILOT_MIME")
    assert sim == core, sorted(sim ^ core)
    assert dev == core, sorted(dev ^ core)
