"""patterns.yaml (D3): every built row names a module that really exports the part, a gate file, a product adopter
that calls it, and a product-page test that exercises that adopter (and is not skipped)."""

import ast
from pathlib import Path
import re

import yaml

WEB = Path(__file__).resolve().parents[1]
REPO = WEB.parents[1]
ROWS = yaml.safe_load((WEB / "patterns.yaml").read_text(encoding="utf-8"))["patterns"]
DESIGN = (REPO / "DESIGN.md").read_text(encoding="utf-8")
LOCATORS = {"locator", "get_by_role", "get_by_label", "get_by_text", "get_by_test_id", "query_selector", "query_selector_all",
            "wait_for_selector", "click", "fill", "check", "uncheck", "select_option", "press"}


def test_listed_patterns_are_unique_ordered_and_start_with_c1_to_c12():
    ids = [row["id"] for row in ROWS]
    assert ids[:12] == [f"C{n}" for n in range(1, 13)] and len(set(ids)) == len(ids)
    # C13 (icons, tooltips) is a DESIGN.md rule without a registry row; later rows only grow the list
    assert [int(i[1:]) for i in ids] == sorted(int(i[1:]) for i in ids)
    for row in ROWS:
        assert {"id", "need", "module", "export", "rule", "gate", "status"} <= set(row) <= {"id", "need", "module", "export", "rule", "gate", "status", "adopters", "debt", "product_test", "product_hook", "forbid"}, row
        assert row["status"] in ("built", "planned"), row
        assert f"| {row['id']} |" in DESIGN, f"DESIGN.md 표에 {row['id']} 행이 없다"


def test_built_rows_export_their_part_and_have_a_gate_file():
    built = [row for row in ROWS if row["status"] == "built"]
    assert built, "C5 setGeometry is built"
    for row in built:
        module = WEB / row["module"]
        assert module.is_file(), f"{row['id']}: {row['module']} missing"
        pattern = rf"export\s+(?:async\s+)?(?:function|const|class)\s+{re.escape(row['export'])}\b|export\s*\{{[^}}]*\b{re.escape(row['export'])}\b"
        assert re.search(pattern, module.read_text(encoding="utf-8")), f"{row['id']}: {row['module']} does not export {row['export']}"
        assert (REPO / row["gate"]).is_file(), f"{row['id']}: gate file {row['gate']} missing"


# --- adopter call site -------------------------------------------------------------------------------------------

_JS_NOISE = re.compile(r"""//[^\n]*|/\*.*?\*/|"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'|`(?:[^`\\]|\\.)*`""", re.S)


def js_code(text):
    """Source with comments dropped and string literals emptied: what is left can really execute."""
    return _JS_NOISE.sub(lambda match: '""' if match.group(0)[0] in "\"'`" else "", text)


def imports_and_calls(text, name):
    """(imported, called): `name` is imported, and called outside the import statements, in real code."""
    code = js_code(text)
    word = "(?<![A-Za-z0-9_])" + re.escape(name) + "(?![A-Za-z0-9_])"
    statement = r'^[ \t]*import\b.*?""'  # strings are already emptied, so an import ends at its module string
    imported = any(re.search(word, m.group(0)) for m in re.finditer(statement, code, re.M | re.S))
    body = re.sub(statement, "", code, flags=re.M | re.S)
    return imported, bool(re.search(word + "[(]", body))


def test_every_built_part_has_a_product_adopter_that_imports_and_calls_it():
    """A built component nobody uses fails: the point of a shared part is the local copy it deletes."""
    for row in (row for row in ROWS if row["status"] == "built"):
        adopters = row.get("adopters") or []
        assert adopters, f"{row['id']}: built but no adopter"
        for adopter in adopters:
            assert "component-gallery" not in adopter, f"{row['id']}: the gallery is not an adopter"
            imported, called = imports_and_calls((REPO / adopter).read_text(encoding="utf-8"), row["export"])
            assert imported, f"{row['id']}: {adopter} does not import {row['export']}"
            assert called, f"{row['id']}: {adopter} imports {row['export']} but never calls it in code"


def test_migration_debt_is_listed_and_matches_the_style_gate_exceptions():
    debt = {path for row in ROWS if row["id"] == "C5" for path in (row.get("debt") or {})}  # C5 debt = style-gate exceptions; other rows list adoption debt with a reason
    assert debt == {"middleware/perception/web/diagnostic-core.js", "middleware/perception/web/diagnostic-map.js"}
    assert "이행 부채" in DESIGN and all(path.rsplit("/", 1)[1] in DESIGN for path in debt)


# --- product-page test -------------------------------------------------------------------------------------------

def _function(source, name):
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def product_test_problems(source, name, hook):
    """Why `name` in a pytest file is not a real product test for `hook` ([] when it is): skipped, or the hook is not
    used in a locator/query call (a comment or a plain string elsewhere does not count)."""
    node = _function(source, name)
    if node is None:
        return [f"no test named {name}"]
    problems = []
    for decorator in node.decorator_list:
        text = ast.unparse(decorator)
        opt_in = "browser_tests_enabled" in text or "ROSY_RUN_BROWSER_TESTS" in text  # the suite's own opt-in is fine
        if "xfail" in text or re.search(r"\.skip\b", text) or ("skipif" in text and not opt_in):
            problems.append("marked skip/xfail")
    used = False
    for call in (n for n in ast.walk(node) if isinstance(n, ast.Call)):
        callee = call.func.attr if isinstance(call.func, ast.Attribute) else getattr(call.func, "id", "")
        if callee in LOCATORS:
            strings = [c.value for arg in call.args for c in ast.walk(arg) if isinstance(c, ast.Constant) and isinstance(c.value, str)]
            used = used or any(hook in text for text in strings)
    if not used:
        problems.append(f"{hook} is not inside a locator/query call")
    if not any(isinstance(n, ast.Assert) for n in ast.walk(node)) and "expect(" not in ast.unparse(node):
        problems.append("no assertion")
    return problems


def _page_folder(adopter):
    folder = (REPO / adopter).parent
    while folder != REPO and not any(folder.glob("*.html")):
        folder = folder.parent
    return folder


def test_each_product_test_is_real_and_tied_to_its_adopter_page_by_a_hook():
    """The test must locate product_hook on the page, and the adopter's page folder must contain that hook."""
    for row in (row for row in ROWS if row["status"] == "built"):
        path, _, name = (row.get("product_test") or "").partition("::")
        assert path and name, f"{row['id']}: built but no product_test (file::test)"
        assert "component-gallery" not in path and "shared/web/test" not in path, f"{row['id']}: product_test must run a product page"
        hook = row.get("product_hook")
        assert hook, f"{row['id']}: built but no product_hook"
        problems = product_test_problems((REPO / path).read_text(encoding="utf-8"), name, hook)
        assert not problems, f"{row['id']}: {path}::{name}: {problems}"
        sources = [f for adopter in row["adopters"] for f in _page_folder(adopter).rglob("*") if f.suffix in (".js", ".html") and f.is_file()]
        assert any(hook in f.read_text(encoding="utf-8", errors="ignore") for f in sources), f"{row['id']}: no adopter page file mentions {hook}"


# --- the gate must not be cheatable ------------------------------------------------------------------------------

def test_the_gate_rejects_cheating_samples():
    real = "import {createStopControl} from '/common/stop-control.js';\nconst stop = createStopControl({button});\n"
    assert imports_and_calls(real, "createStopControl") == (True, True)
    unused = "import {createStopControl} from '/common/stop-control.js';\n// createStopControl({button});\nconst s = 'createStopControl(';\n"
    assert imports_and_calls(unused, "createStopControl") == (True, False)  # comment and string calls do not count
    only_comment = "// import {createStopControl} from '/x.js';\nconst a = createStopControl({});\n"
    assert imports_and_calls(only_comment, "createStopControl")[0] is False

    good = "def test_a(page):\n    page.locator('#halt-status').click()\n    assert True\n"
    assert product_test_problems(good, "test_a", "halt-status") == []
    cheat_comment = "def test_a(page):\n    # halt-status\n    assert True\n"
    assert product_test_problems(cheat_comment, "test_a", "halt-status")
    cheat_string = "def test_a(page):\n    note = 'halt-status'\n    assert note\n"
    assert product_test_problems(cheat_string, "test_a", "halt-status")
    skipped = "@pytest.mark.skip(reason='x')\ndef test_a(page):\n    page.locator('#halt-status').click()\n    assert True\n"
    assert "marked skip/xfail" in product_test_problems(skipped, "test_a", "halt-status")
    neighbour = "@pytest.mark.custom\ndef test_b(page):\n    page.locator('#halt-status').click()\n    assert True\n\n\ndef test_a(page):\n    assert True\n"
    assert product_test_problems(neighbour, "test_a", "halt-status")  # a decorator cannot borrow the neighbour's locator


def test_design_md_never_states_a_pattern_status_patterns_yaml_does():
    """One place says planned or built: patterns.yaml. A C row in DESIGN.md that repeats it goes stale."""
    rows = [line for line in DESIGN.splitlines() if re.match(r"\| C\d+ \|", line)]
    assert rows, "DESIGN.md C rows not found"
    words = re.compile(r"`planned`|`built`|아직 계획|구현됨|\b(?:planned|built)\b")
    assert not [line[:30] for line in rows if words.search(line)], "DESIGN.md C 행에 planned/built 상태를 적지 않는다(patterns.yaml이 정본)"
    assert "patterns.yaml" in DESIGN.split("동적 값(D1)", 1)[0].rsplit("### 공용 패턴", 1)[1], "표 뒤에 상태 정본이 patterns.yaml이라는 문장이 있어야 한다"


# --- forbidden references (C23/C24: the dock and panel never reach the supervised-path bypass routes) -----------------

_JS_STRINGS_KEPT = re.compile(r"""("(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'|`(?:[^`\\]|\\.)*`)|//[^\n]*|/\*.*?\*/""", re.S)


def js_without_comments(text):
    """Source with comments dropped; strings stay, because a forbidden route is a string."""
    return _JS_STRINGS_KEPT.sub(lambda match: match.group(1) or "", text)


def forbidden_hits(text, forbidden):
    code = js_without_comments(text)
    # `*` in a forbidden entry matches any run of non-quote characters (pipeline/cell-tasks/*/resume)
    gap = r"""[^"'`\s]*"""
    return [name for name in forbidden if re.search(gap.join(re.escape(part) for part in name.split("*")), code)]


def test_forbidden_references_are_absent_from_the_module_and_every_adopter():
    """`forbid` rows: neither the module nor an adopter file may name these strings in code (comments are ignored)."""
    for row in (row for row in ROWS if row.get("forbid")):
        files = [WEB / row["module"], *(REPO / adopter for adopter in row.get("adopters") or [])]
        if row["status"] == "built":
            assert all(path.is_file() for path in files), f"{row['id']}: a built row's module and adopters must exist"
        for path in files:
            if path.is_file():  # a planned module may not exist yet
                assert not forbidden_hits(path.read_text(encoding="utf-8"), row["forbid"]), f"{row['id']}: {path.name} names a forbidden route"


def test_the_forbid_gate_sees_strings_and_ignores_comments():
    bad = 'await fetch("/api/fleet/pipeline/arm-holds/clear", {method: "POST"});'
    assert forbidden_hits(bad, ["arm-holds/clear"]) == ["arm-holds/clear"]
    assert forbidden_hits("const path = `/api/fleet/pipeline/${'human-safety-gate'}`;", ["human-safety-gate"]) == ["human-safety-gate"]
    assert forbidden_hits("// never call arm-holds/clear\n/* human-safety-gate */ const ok = 1;", ["arm-holds/clear", "human-safety-gate"]) == []
    assert forbidden_hits("post(`/api/fleet/pipeline/cell-tasks/${id}/resume`)", ["pipeline/cell-tasks/*/resume"]) == ["pipeline/cell-tasks/*/resume"]
    assert forbidden_hits('"/api/fleet/pipeline/cell-tasks/7/resume"', ["pipeline/cell-tasks/*/resume"]) == ["pipeline/cell-tasks/*/resume"]
    for row in (row for row in ROWS if row["id"] in ("C23", "C24")):
        assert set(row.get("forbid", [])) >= {"pipeline/decision-gate", "human-safety-gate", "vision-auto-check", "station-zones/dispatch", "arm-holds/clear", "pipeline/cell-tasks/*/resume", "human-safety-gate/clear", "decision-gate/execute"}, row["id"]


# --- registry and DESIGN.md must describe the same parts (2026-11-18) ----------------------------------------------

def test_design_and_registry_list_the_same_pattern_numbers():
    in_design = {int(n) for n in re.findall(r"^\| C(\d+) \|", DESIGN, re.M)}
    in_registry = {int(row["id"][1:]) for row in ROWS}
    assert in_design - in_registry == {13}, "DESIGN.md C rows without a registry row (only C13, a rule, may lack one)"
    assert in_registry <= in_design
    assert f"공용 패턴 C1–C{max(in_design)}" in DESIGN, "DESIGN.md heading range is stale"


def test_a_planned_row_is_not_already_used_by_a_product_file():
    """planned means 'nothing uses it yet'. A product file that imports the part says the row is stale."""
    for row in (row for row in ROWS if row["status"] == "planned"):
        module = row["module"]
        if not module.endswith(".js") or module == "ui.js":  # ui.js holds many parts; C6/C7 stay planned until their gate exists
            continue
        users = [p for p in REPO.rglob("*.js") if p.name != module and not {"node_modules", "vendor", "test", ".worktrees"} & set(p.relative_to(REPO).parts) and "gallery" not in p.name
                 and re.search(rf"import[^;]*{re.escape(row['export'])}[^;]*{re.escape(module)}", p.read_text(encoding="utf-8", errors="ignore"))]
        assert not users, f"{row['id']} is planned but {[u.relative_to(REPO).as_posix() for u in users]} import it"
