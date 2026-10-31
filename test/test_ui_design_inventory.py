"""Inventory parser checks use fixtures, not screenshots or source-text assertions."""

import importlib.util
from pathlib import Path


SPEC = importlib.util.spec_from_file_location(
    "ui_design_inventory", Path(__file__).resolve().parents[1] / "tools/ui_design_inventory.py")
inventory = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inventory)


def test_themes_aliases_comments_layout_and_per_surface_closure(tmp_path):
    tokens = '''/* --fake: red; */
:root, [data-theme="dark"] { --ink: #ffffff; --ground: #101214; }
[data-theme="light"] { --ink: #101214; --ground: #ffffff; }
:root {
  --text-primary:
    var(--ink);
  --line: color-mix(in oklab, var(--ink) 14%, transparent);
}
'''
    files = {
        "shared/web/tokens.css": tokens,
        "apps/a/app.css": '''/* var(--comment-missing) */
@media (width < 30rem) {
  .map { --cursor-x: 20px; --a-only: var(--text-primary);
    width: calc(100% - 2px); padding: var(--optional, var(--text-primary)); }
}
''',
        "apps/b/app.css": ".b { color: var(--a-only); gap: var(--missing-gap); }",
        "apps/a/index.html": '<!-- var(--html-comment) -->\n<style>\n.a { display: grid; }\n</style>',
        "apps/a/app.js": '// readColour("--commented-js")\nreadColour("--text-primary");',
    }
    surfaces = [{"id": name, "path": f"apps/{name}", "medium": "web"} for name in ("a", "b")]
    data = inventory.build_inventory(tmp_path, surfaces, files)
    by_name = {row["name"]: row for row in data["tokens"]}
    assert set(by_name) == {"--ink", "--ground", "--text-primary", "--line"}
    assert len(by_name["--ink"]["occurrences"]) == 2
    assert by_name["--text-primary"]["theme_expressions"] == {"dark": "#ffffff", "light": "#101214"}
    assert by_name["--text-primary"]["occurrences"][0]["line"] == 5
    assert by_name["--line"]["theme_expressions"]["light"] == "color-mix(in oklab, #101214 14%, transparent)"
    assert data["surfaces"][0]["missing_reference_candidates"] == []
    assert {r["name"] for r in data["surfaces"][1]["missing_reference_candidates"]} == {"--a-only", "--missing-gap"}
    local = {row["property"]: row for row in data["local_custom_properties"]}
    assert local["--cursor-x"]["classification"] == "inferred-runtime-or-data-geometry"
    assert local["--a-only"]["classification"] == "component-or-surface-local"
    assert local["--a-only"]["context"] == ["@media (width < 30rem)", ".map"]
    assert any(r["property"] == "display" and r["line"] == 3 for r in data["layout_declarations"])
    assert not any("comment" in r["name"] for r in data["uses"])
    assert any(r["name"] == "--optional" and r["optional"] for r in data["uses"])
    assert "#ffffff" in inventory.markdown(data)


def test_nested_fallbacks_and_quoted_semicolons_do_not_split_declarations():
    source = '.a { --label: "a;b"; width: var(--outer, var(--inner, 10px)); }'
    rows = inventory.css_declarations(source, "fixture.css")
    assert [(r["property"], r["value"]) for r in rows] == [
        ("--label", '"a;b"'), ("width", "var(--outer, var(--inner, 10px))")]
    assert [(r["name"], r["optional"]) for r in inventory.var_references(source)] == [
        ("--outer", True), ("--inner", True)]
    escaped = inventory.css_declarations(r'.a { --label: "trail\\"; width: var(--ink); }', "fixture.css")
    assert [(r["property"], r["value"]) for r in escaped] == [
        ("--label", r'"trail\\"'), ("width", "var(--ink)")]
    template = inventory.parse_asset("fixture.js", '''sheet.replaceSync(`.a {
/* var(--commented-template) */
width: var(--ink);
}`);''')
    assert [(r["name"], r["line"]) for r in template["uses"]] == [("--ink", 3)]
    assert template["declarations"][0]["line"] == 3


def test_registration_tables_dynamic_names_and_non_token_boundaries():
    source = '''
for (const [name, ctor] of [
  ["ui-example", UiExample], ["ui-another", UiAnother],
]) { if (!customElements.get(name)) customElements.define(name, ctor); }
const BOUNDARY = "--frame";
readColour("--ink");
getComputedStyle(root).getPropertyValue("--text-label");
sheet.replaceSync(`.a { font-size: var(--text-${role}); }`);
'''
    assert [r["name"] for r in inventory.component_definitions("ui.js", source)] == ["ui-example", "ui-another"]
    parsed = inventory.parse_asset("ui.js", source)
    assert {r["name"] for r in parsed["uses"]} == {"--ink", "--text-label"}
    assert all(r["kind"] == "js-token-getter" for r in parsed["uses"])
    assert [r["name"] for r in parsed["excluded_literals"]] == ["--frame"]
    assert [r["expression"] for r in parsed["dynamic_names"]] == ["--text-${role}"]
