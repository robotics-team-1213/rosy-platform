"""App assets load without the operational Fleet server or ROS."""

import json
from pathlib import Path
import re
import runpy
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[3]
WEB = ROOT / "applications/fleet/web"
LOADER = WEB / "asset_registry.py"


def loader():
    assert LOADER.is_file(), "Backend-free app asset registry loader is missing"
    return runpy.run_path(str(LOADER))


def test_registry_preserves_pages_and_existing_aliases():
    api = loader()
    registry = api["load_registry"](WEB)
    assert set(registry["pages"]) == {
        "/console", "/console/login", "/console/profile", "/console/accounts",
        "/console/policy", "/console/cell", "/console/site-map", "/console/install",
    }
    assert {entry["path"] for entry in registry["pages"].values()} == {
        path.relative_to(WEB).as_posix() for path in WEB.rglob("*.html")
    }
    assert api["resolve_entry"](WEB, registry["assets"], "assistant.js") == (
        (WEB / "assistant/panel.js").resolve(), "application/javascript"
    )
    for source in list(WEB.rglob("*.js")) + list(WEB.rglob("*.html")):
        for name in re.findall(r'''["']/console/assets/([^"']+)["']''', source.read_text(encoding="utf-8")):
            if "${" not in name:
                assert api["resolve_entry"](WEB, registry["assets"], name) is not None, (source.name, name)


def small_registry(root):
    (root / "index.html").write_text("sample", encoding="utf-8")
    (root / "app.js").write_text("export const value = 1;", encoding="utf-8")
    return {"pages": {"/console": {"path": "index.html", "media_type": "text/html"}},
            "assets": {"app.js": {"path": "app.js", "media_type": "application/javascript"}}}


@pytest.mark.parametrize("path", ["../outside.js", "/outside.js", "C:/outside.js", "..\\outside.js", "missing.js"])
def test_registry_rejects_escape_and_missing_entries(tmp_path, path):
    api = loader()
    registry = small_registry(tmp_path)
    registry["assets"]["app.js"]["path"] = path
    (tmp_path / "assets.json").write_text(json.dumps(registry), encoding="utf-8")
    with pytest.raises(ValueError):
        api["load_registry"](tmp_path)


def test_registry_rejects_duplicate_names(tmp_path):
    api = loader()
    small_registry(tmp_path)
    (tmp_path / "assets.json").write_text(
        '{"pages":{},"assets":{"app.js":{"path":"app.js","media_type":"application/javascript"},'
        '"app.js":{"path":"index.html","media_type":"text/html"}}}', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="duplicate"):
        api["load_registry"](tmp_path)


def test_resolution_rechecks_files_and_symlinks(tmp_path):
    api = loader()
    registry = small_registry(tmp_path)
    (tmp_path / "assets.json").write_text(json.dumps(registry), encoding="utf-8")
    loaded = api["load_registry"](tmp_path)
    asset = tmp_path / "app.js"
    asset.unlink()
    outside = tmp_path.parent / (tmp_path.name + "-outside.js")
    outside.write_text("outside", encoding="utf-8")
    asset.symlink_to(outside)
    assert api["resolve_entry"](tmp_path, loaded["assets"], "app.js") is None
    assert api["resolve_entry"](tmp_path, loaded["assets"], "unknown.js") is None


def test_registry_loads_without_fleet_or_ros():
    loader()
    code = "import runpy,sys; from pathlib import Path; a=runpy.run_path(sys.argv[1]); r=a['load_registry'](Path(sys.argv[2])); assert len(r['pages'])==8; assert not any(n=='fleet' or n.startswith('rclpy') for n in sys.modules)"
    result = subprocess.run([sys.executable, "-I", "-c", code, str(LOADER), str(WEB)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
