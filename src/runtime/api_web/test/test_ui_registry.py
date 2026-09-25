"""D-204 — 패널 레지스트리는 기동 때 검증되고, 틀리면 기동을 거부한다."""

from __future__ import annotations

from pathlib import Path

import pytest

from core_api_web.api.ui_registry import RegistryError, load_registry

WEB_ROOT = Path(__file__).resolve().parents[3] / "hmi" / "dashboard"

SURFACES = """
version: 1
surfaces:
  console: {title: 운용, min_role: viewer, grammar: spatial, slots: [banner, sense, observe, act]}
  device: {title: 설치·정비, min_role: administrator, grammar: procedure, slots: [main]}
"""


def _web(tmp_path: Path, panels: str, *, files=("panels/a/one.js", "panels/a/one.css")) -> Path:
    for name in files:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("export function mount() {}\n", encoding="utf-8")
    (tmp_path / "panels.yaml").write_text(SURFACES + panels, encoding="utf-8")
    return tmp_path


ONE = """
panels:
  - id: a.one
    title: 하나
    surface: device
    slot: main
    order: 10
    module: panels/a/one.js
"""


def test_the_shipped_registry_loads():
    registry = load_registry(WEB_ROOT / "panels.yaml", WEB_ROOT)
    assert set(registry.surfaces) == {"console", "setup", "device"}
    assert "system.events" in {panel.id for panel in registry.panels}


def test_a_minimal_panel_takes_the_surface_role_and_no_requirements(tmp_path):
    registry = load_registry(_web(tmp_path, ONE) / "panels.yaml", tmp_path)
    (panel,) = registry.panels
    assert panel.min_role == "administrator"
    assert panel.requires == ()
    assert panel.css == ()
    assert registry.assets() == {"panels/a/one.js": "application/javascript"}


def test_css_is_listed_as_an_asset(tmp_path):
    text = ONE + "    css: [panels/a/one.css]\n"
    registry = load_registry(_web(tmp_path, text) / "panels.yaml", tmp_path)
    assert registry.assets()["panels/a/one.css"] == "text/css"


@pytest.mark.parametrize("change, message", [
    (("surface: device", "surface: garage"), "unknown surface"),
    (("slot: main", "slot: act"), "unknown slot"),
    (("module: panels/a/one.js", "module: panels/a/missing.js"), "missing file"),
    (("module: panels/a/one.js", "module: ../api/app.py"), "outside panels/"),
    (("module: panels/a/one.js", "module: panels/a/one.css"), ".js"),
    (("order: 10", "order: ten"), "order"),
    (("    title: 하나\n", ""), "title"),
    # 경로 하드닝(리뷰 배치 A) — 백슬래시는 Windows에서 실제 구분자로 동작하므로
    # panels/ 밖으로 나가는 별도 통로다. 글자 그대로 거부한다.
    ((r"module: panels/a/one.js", r"module: panels/..\api\app.js"), "outside panels/"),
    # 정규형이 아닌 표기(., 중복 슬래시)는 문자열 비교 보안 검사를 우회할 수 있어 거부한다.
    (("module: panels/a/one.js", "module: panels/./a/one.js"), "normal form"),
    (("module: panels/a/one.js", "module: panels//a/one.js"), "normal form"),
    # 값이 문자열이 아니면(list 등) 예전 코드는 dict.get()/in 에서 TypeError로 죽었다.
    (("surface: device", "surface: [device]"), "unknown surface"),
    (("slot: main", "slot: [main]"), "unknown slot"),
])
def test_a_wrong_panel_refuses_to_load(tmp_path, change, message):
    text = ONE.replace(*change)
    with pytest.raises(RegistryError, match=message):
        load_registry(_web(tmp_path, text) / "panels.yaml", tmp_path)


def test_a_duplicate_css_entry_in_one_panel_refuses_to_load(tmp_path):
    text = ONE + "    css: [panels/a/one.css, panels/a/one.css]\n"
    with pytest.raises(RegistryError, match="duplicate"):
        load_registry(_web(tmp_path, text) / "panels.yaml", tmp_path)


def test_a_symlink_that_escapes_panels_refuses_to_load(tmp_path):
    import os

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "one.js").write_text("export function mount() {}\n", encoding="utf-8")
    web = tmp_path / "web"
    (web / "panels").mkdir(parents=True)
    try:
        os.symlink(outside, web / "panels" / "escape", target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are not permitted in this environment")
    text = ONE.replace("module: panels/a/one.js", "module: panels/escape/one.js")
    (web / "panels.yaml").write_text(SURFACES + text, encoding="utf-8")
    with pytest.raises(RegistryError, match="outside panels/"):
        load_registry(web / "panels.yaml", web)


def test_a_non_string_role_refuses_to_load_without_crashing(tmp_path):
    with pytest.raises(RegistryError, match="unknown role"):
        load_registry(_web(tmp_path, ONE + "    min_role: [operator]\n") / "panels.yaml", tmp_path)


def test_a_non_string_inventory_refuses_to_load_without_crashing(tmp_path):
    with pytest.raises(RegistryError, match="inventory"):
        load_registry(_web(tmp_path, ONE + "    inventory: [mobility.move]\n") / "panels.yaml", tmp_path)


def test_the_top_level_document_must_be_a_mapping(tmp_path):
    (tmp_path / "panels.yaml").write_text("- 1\n- 2\n", encoding="utf-8")
    with pytest.raises(RegistryError, match="mapping"):
        load_registry(tmp_path / "panels.yaml", tmp_path)


def test_panels_must_be_a_list(tmp_path):
    text = SURFACES + "panels: 5\n"
    (tmp_path / "panels.yaml").write_text(text, encoding="utf-8")
    with pytest.raises(RegistryError, match="list"):
        load_registry(tmp_path / "panels.yaml", tmp_path)


def test_an_unknown_role_refuses_to_load(tmp_path):
    with pytest.raises(RegistryError, match="unknown role"):
        load_registry(_web(tmp_path, ONE + "    min_role: root\n") / "panels.yaml", tmp_path)


def test_a_duplicate_id_refuses_to_load(tmp_path):
    twice = ONE + ONE.replace("panels:\n", "").replace("order: 10", "order: 20")
    with pytest.raises(RegistryError, match="duplicate id"):
        load_registry(_web(tmp_path, twice) / "panels.yaml", tmp_path)


def test_a_duplicate_order_in_one_slot_refuses_to_load(tmp_path):
    twice = ONE + ONE.replace("panels:\n", "").replace("a.one", "a.two")
    with pytest.raises(RegistryError, match="duplicate order"):
        load_registry(_web(tmp_path, twice) / "panels.yaml", tmp_path)


def test_a_bad_requires_key_refuses_to_load(tmp_path):
    with pytest.raises(RegistryError, match="requires"):
        load_registry(_web(tmp_path, ONE + "    requires: [Teleop!]\n") / "panels.yaml", tmp_path)


@pytest.mark.parametrize("surfaces, message", [
    ("version: 2\nsurfaces: {}\n", "version"),
    ("version: 1\nsurfaces:\n  api: {title: x, min_role: viewer, grammar: procedure, slots: [main]}\n",
     "reserved"),
    ("version: 1\nsurfaces:\n  device: {title: x, min_role: viewer, grammar: exception, slots: [main]}\n",
     "grammar"),
    ("version: 1\nsurfaces:\n  device: {title: x, min_role: viewer, grammar: procedure, slots: []}\n",
     "slots"),
    ("version: 1\nsurfaces:\n  device: {title: x, min_role: viewer, grammar: [procedure], slots: [main]}\n",
     "grammar"),
    ("version: 1\nsurfaces:\n  device: {title: x, min_role: [viewer], grammar: procedure, slots: [main]}\n",
     "unknown role"),
    ("version: 1\nsurfaces:\n  device: {title: x, min_role: viewer, grammar: procedure, slots: [main, main]}\n",
     "duplicate slot"),
])
def test_a_wrong_surface_refuses_to_load(tmp_path, surfaces, message):
    (tmp_path / "panels.yaml").write_text(surfaces + "panels: []\n", encoding="utf-8")
    with pytest.raises(RegistryError, match=message):
        load_registry(tmp_path / "panels.yaml", tmp_path)


def test_a_trailing_newline_in_a_surface_id_is_rejected(tmp_path):
    # re.match()의 `$`는 끝의 개행 하나를 남몰래 통과시킨다 — fullmatch()로 막는다.
    surfaces = ('version: 1\nsurfaces:\n'
                '  "device\\n": {title: x, min_role: viewer, grammar: procedure, slots: [main]}\n')
    (tmp_path / "panels.yaml").write_text(surfaces + "panels: []\n", encoding="utf-8")
    with pytest.raises(RegistryError, match="id must match"):
        load_registry(tmp_path / "panels.yaml", tmp_path)


def test_a_trailing_newline_in_a_slot_name_is_rejected(tmp_path):
    surfaces = ('version: 1\nsurfaces:\n'
                '  device: {title: x, min_role: viewer, grammar: procedure, slots: ["main\\n"]}\n')
    (tmp_path / "panels.yaml").write_text(surfaces + "panels: []\n", encoding="utf-8")
    with pytest.raises(RegistryError, match="slots must be"):
        load_registry(tmp_path / "panels.yaml", tmp_path)
