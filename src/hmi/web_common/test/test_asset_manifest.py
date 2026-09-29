"""manifest.json is the one /common allowlist for core, fleet, games and control.

Each server reads it instead of keeping its own list, so a shared file that is
installed but missing here would 404 on some servers and not others.
"""

import json
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((WEB / "manifest.json").read_text(encoding="utf-8"))
ASSETS = MANIFEST["shared_assets"]
#: Installed next to the assets but not served under /common.
NOT_SHARED = {"manifest.json"}


def _installed_files() -> set[str]:
    text = (WEB / "CMakeLists.txt").read_text(encoding="utf-8")
    block = re.search(r"install\(FILES(.*?)DESTINATION", text, re.S)
    assert block, "CMakeLists.txt no longer has an install(FILES ...) block"
    return set(block.group(1).split())


def test_every_manifest_asset_exists_as_a_plain_file():
    for name in ASSETS:
        assert "/" not in name and not name.startswith("."), name
        assert (WEB / name).is_file(), f"manifest names a missing file: {name}"


def test_manifest_and_install_list_agree():
    installed = _installed_files()
    assert "manifest.json" in installed, "servers read share/web_common/manifest.json"
    assert installed - NOT_SHARED == set(ASSETS), (
        f"installed but not shared: {sorted(installed - NOT_SHARED - set(ASSETS))}; "
        f"shared but not installed: {sorted(set(ASSETS) - installed)}")


def test_media_types_are_canonical():
    allowed = {".css": "text/css", ".html": "text/html", ".js": "text/javascript"}
    for name, media in ASSETS.items():
        assert media == allowed[Path(name).suffix], (name, media)


def test_hold_ticker_is_shared():
    assert "hold-ticker.js" in ASSETS
