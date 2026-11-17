"""G3 / G8 static gates for the choice parts: the --selection mark, no motion, and the hand-written patterns that may
only shrink (role=tab, role=option, hand chip groups). Contrast is in test_ui_token_contracts.py."""

from pathlib import Path
import re

WEB = Path(__file__).resolve().parents[1]
REPO = WEB.parents[1]
CSS = (WEB / "choice-controls.css").read_text(encoding="utf-8")
TOKENS = (WEB / "tokens.css").read_text(encoding="utf-8")
PRODUCT_ROOTS = ("applications", "middleware", "operations", "learning", "integrations", "shared")


def rules(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return [(m.group(1).strip(), m.group(2)) for m in re.finditer(r"([^{}@]+)\{([^{}]*)\}", text)]


def source_files(*suffixes):
    for root in PRODUCT_ROOTS:
        for path in sorted((REPO / root).rglob("*")):
            parts = path.relative_to(REPO).as_posix()
            if path.suffix in suffixes and path.is_file() and "/test/" not in parts and "node_modules" not in parts:
                yield parts, path


def files_matching(pattern, *suffixes):
    return {name for name, path in source_files(*suffixes) if pattern.search(path.read_text(encoding="utf-8", errors="ignore"))}


def test_selection_is_one_alias_of_series_secondary_and_distinct_from_focus():
    assert re.search(r"--selection:\s*var\(--series-secondary\)\s*;", TOKENS), "--selection must be the one-line alias"
    assert "--selection:" not in TOKENS.split("--focus-ring:", 1)[0], "--selection belongs to the derived block, not a palette"
    assert "var(--selection)" in CSS and "--focus-ring: var(--series-primary)" in TOKENS


def test_the_selected_mark_never_fills_a_row_and_never_relies_on_colour_alone():
    marked = [(sel, body) for sel, body in rules(CSS) if re.search(r"data-selected|aria-selected=\"true\"|:checked|aria-pressed", sel)]
    assert marked, "the selection mark rules were not found"
    for selector, body in marked:
        fill = re.search(r"background(?:-color)?\s*:\s*([^;]+);?", body)
        assert not fill or fill.group(1).strip() == "transparent", f"selected mark fills: {selector}"
    assert re.search(r"box-shadow:\s*inset var\(--space-1\) 0 0 var\(--selection\)", CSS), "the thick --selection edge is missing"
    assert ".choice-check" in CSS and "visibility: visible" in CSS, "the check mark (non-colour cue) is missing"
    assert not re.search(r"\.robot-row\[data-selected\]\s*\{[^}]*background", (WEB / "component-controls.css").read_text(encoding="utf-8"))


def test_choice_css_has_no_motion_and_no_raw_colour():
    code = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    assert not re.search(r"\b(transition|animation|@keyframes|transform)\b", code), "D-220: no motion"
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|\boklch\(", code), "colours come from tokens.css"


def test_choice_parts_use_no_inline_style_and_no_innerhtml():
    for name in ("choice-list.js", "choice-group.js", "selection.js", "choice-logic.js", "robot-options.js"):
        code = re.sub(r"/\*.*?\*/|//[^\n]*", "", (WEB / name).read_text(encoding="utf-8"), flags=re.S)
        assert not re.search(r"\.style\b|setAttribute\(\s*[\"']style|innerHTML", code), f"{name}: CSP / no HTML strings"


def test_new_parts_are_installed_and_served():
    import json
    served = json.loads((WEB / "shared-assets.json").read_text(encoding="utf-8"))["shared_assets"]
    cmake = (WEB / "CMakeLists.txt").read_text(encoding="utf-8")
    for name in ("choice-list.js", "choice-group.js", "choice-logic.js", "robot-options.js", "selection.js", "choice-controls.css"):
        assert name in served and name in cmake, name


# --- hand-written patterns may only shrink (debt lists: delete an entry when its file moves to the shared part) ------

ROLE_TAB = re.compile(r"""role=["']tab["']|\.setAttribute\(\s*["']role["']\s*,\s*["']tab["']\s*\)""")
ROLE_TAB_ALLOWED = {"shared/web/interaction-controls.js", "shared/web/task-chooser.js", "shared/web/ui.js"}  # createTabs, createTaskChooser, the ui-button reader
ROLE_TAB_DEBT = {
    "applications/calibration/web/index.html",
    "integrations/simulation/gazebo/scripts/lane_live_view.html",
    "middleware/robot_ui/robot/shell/mount.js",
    "middleware/robot_ui/robot/styleguide.html",
    "middleware/robot_ui/robot/styleguide.js",
}
ROLE_OPTION = re.compile(r"""role=["'](?:option|listbox)["']|["']role["']\s*,\s*["'](?:option|listbox)["']""")
HAND_CHIPS = re.compile(r"data-layer-toggle|data-preset\b")
HAND_CHIP_DEBT = set()


def test_role_tab_is_written_only_by_createtabs_and_the_listed_debt_only_shrinks():
    found = files_matching(ROLE_TAB, ".js", ".html", ".mjs") - ROLE_TAB_ALLOWED
    assert found == ROLE_TAB_DEBT, (f"role=tab 직접 작성: 새로 {sorted(found - ROLE_TAB_DEBT)}, 이미 옮겼는데 목록에 남음 {sorted(ROLE_TAB_DEBT - found)}"
                                    " — 패널 전환은 createTabs, 순차 단계는 ol.ui-stage-track")


def test_role_option_and_listbox_are_written_only_by_createchoicelist():
    found = files_matching(ROLE_OPTION, ".js", ".html", ".mjs") - {"shared/web/choice-list.js"}
    assert found == set(), f"listbox/option 직접 작성: {sorted(found)} — createChoiceList를 쓴다(K3)"


def test_hand_written_chip_groups_are_listed_and_only_shrink():
    found = files_matching(HAND_CHIPS, ".js", ".html", ".mjs")
    assert found == HAND_CHIP_DEBT, (f"손으로 쓴 칩 그룹: 새로 {sorted(found - HAND_CHIP_DEBT)}, 옮겼는데 목록에 남음 {sorted(HAND_CHIP_DEBT - found)}"
                                    " — createChoiceGroup(K1/K5/K6)을 쓴다")


def test_the_gate_detects_what_it_guards():
    assert ROLE_TAB.search('<ui-button role="tab">') and ROLE_TAB.search('tab.setAttribute("role", "tab")')
    assert ROLE_OPTION.search('<li role="option">') and not ROLE_OPTION.search("role=button")
    assert HAND_CHIPS.search("data-layer-toggle") and not HAND_CHIPS.search("data-presets-list")


# --- shared modules import each other relatively: a prefixed standalone bundle (/monitoring/, ...) has no /common/ route ---

ABSOLUTE_COMMON = re.compile(r"""["'`]/common/""")  # any string naming /common/: import, dynamic import, multi-line import


def test_shared_web_modules_never_import_each_other_by_an_absolute_common_path():
    offenders = []
    for path in sorted(WEB.rglob("*.js")):
        if "vendor" in path.relative_to(WEB).parts:
            continue
        code = re.sub(r"/\*.*?\*/|(?<!:)//[^\n]*", "", path.read_text(encoding="utf-8"), flags=re.S)
        if ABSOLUTE_COMMON.search(code):
            offenders.append(path.relative_to(WEB).as_posix())
    assert offenders == [], f"/common/ 절대 경로: {offenders} — 같은 폴더 모듈은 ./모듈.js로 부른다(접두 번들은 /common/ 길이 없다)"
    assert ABSOLUTE_COMMON.search('import {a} from "/common/ui.js";') and ABSOLUTE_COMMON.search("await import(`/common/ui.js`)")
    assert ABSOLUTE_COMMON.search('import {a}\n  from "/common/ui.js"') and not ABSOLUTE_COMMON.search('import {a} from "./ui.js";')
