"""Icon catalog and static icon/tooltip gates (concept rules 7-11, 14; D-926).

Catalog: every actionIcon glyph has one category (nav/action/object/status/measure) and a Korean label, names are
kebab-case, and the status glyphs keep one meaning each. Gates scan product web surfaces (surfaces.yaml, medium web)
statically: HTML tags and JS literals. Each gate has an explicit exception list of CURRENT violations, counted per
file; the lists may only shrink (a count above the list fails, a count below it fails too until the list is lowered).
"""

import re
from pathlib import Path

import surface_registry as registry

WEB = Path(__file__).resolve().parents[1]
UI = (WEB / "ui.js").read_text(encoding="utf-8")
CATEGORIES = ("nav", "action", "object", "status", "measure")
STATUS_GLYPHS = {"warn", "safety", "estop", "lock", "wifi", "minus", "history"}
KEBAB = re.compile(r"^[a-z]+(?:-[a-z]+)*$")


def glyph_names():
    body = UI.split("function icons()", 1)[1].split("}; }", 1)[0]
    return re.findall(r'^  "?([\w-]+)"?: ', body, re.M)


def catalog():
    body = UI.split("ICON_CATALOG = {", 1)[1].split("\n};", 1)[0]
    out = {}
    for line in body.strip().splitlines():
        category = line.strip().split(":", 1)[0]
        out[category] = dict(re.findall(r'"?([\w-]+)"?: "([^"]+)"', line.split(":", 1)[1]))
    return out


def test_every_glyph_has_one_category_and_a_korean_label_in_kebab_case():
    names, cat = glyph_names(), catalog()
    assert tuple(cat) == CATEGORIES or set(cat) == set(CATEGORIES), list(cat)
    listed = [name for group in cat.values() for name in group]
    assert sorted(listed) == sorted(names), (set(names) ^ set(listed), [n for n in listed if listed.count(n) > 1])
    for group in cat.values():
        for name, label in group.items():
            assert KEBAB.match(name), name
            assert re.search("[가-힣]", label) or label.isupper(), (name, label)


def test_status_glyphs_are_one_to_one_with_a_state():
    cat = catalog()
    assert set(cat["status"]) == STATUS_GLYPHS
    tags = (WEB / "status-tag.js").read_text(encoding="utf-8")
    icons = re.findall(r'icon: "([\w-]+)"', tags.split("STATUS_TAGS", 1)[1].split("});", 1)[0])
    assert len(icons) == len(set(icons)) and set(icons) <= STATUS_GLYPHS, icons
    for name in STATUS_GLYPHS:  # one meaning: no other glyph shares its path
        body = UI.split("function icons()", 1)[1]
        path = re.search(r'^  "?%s"?: (.+),$' % re.escape(name), body, re.M).group(1)
        assert len(re.findall(r'^  "?[\w-]+"?: %s,$' % re.escape(path), body, re.M)) == 1, name


# ---- static gates over product surfaces ------------------------------------------------------------------------
def sources():
    base = registry.REPO
    out = {}
    for row in registry.load():
        if row.get("medium", "web") != "web":
            continue
        for suffix in (".html", ".js"):
            for page in registry._pages(base, row["path"], suffix):
                rel = page.relative_to(base).as_posix()
                if "/test" not in rel and "node_modules" not in rel:
                    out[rel] = page.read_text(encoding="utf-8", errors="ignore")
    return out


TAG = re.compile(r"<([a-z][\w-]*)\b([^<>]*?\bdata-icon-only\b[^<>]*)>(.*?)(?=</\1>|<[a-z])", re.S)
DESTRUCTIVE = re.compile(r"정지|삭제|해제|지우기|제거|stop|delete|trash|release", re.I)
JS_ICON_ONLY = re.compile(r'"data-icon-only"\s*:\s*""[^;]*?"aria-label"\s*:\s*"([^"]*)"', re.S)
DESTRUCTIVE_ICONS = {"estop", "trash", "stop"}


def icon_only_tags(text):
    """(line, tag, attrs, body) for HTML-ish icon-only controls (also inside JS template strings)."""
    for m in TAG.finditer(text):
        yield text.count("\n", 0, m.start()) + 1, m.group(1), m.group(2), m.group(3)


def attr(attrs, name):
    found = re.search(r'\b%s\s*=\s*"([^"]*)"' % re.escape(name), attrs)
    return found.group(1) if found else None


def violations():
    found = {"title": [], "name": [], "verb": [], "details": [], "tooltip": [], "status": []}
    for rel, text in sources().items():
        for line, tag, attrs, body in icon_only_tags(text):
            where = f"{rel}:{line}"
            if attr(attrs, "title") is not None:
                found["title"].append(where)
            named = (attr(attrs, "aria-label") or "").strip() or re.sub(r"<[^>]*>", "", body).strip()
            wired = "data-action-icon" in attrs or attr(attrs, "data-ui-tooltip")
            if not named or not wired:
                found["name"].append(where)
            icon = attr(attrs, "data-action-icon")
            before = text[:text.find(attrs)]
            in_nav = before.rfind("<nav") > before.rfind("</nav>")
            if tag == "a" or in_nav or icon in DESTRUCTIVE_ICONS or DESTRUCTIVE.search(named):
                found["verb"].append(where)
        for m in JS_ICON_ONLY.finditer(text):  # el("ui-button", null, {"data-icon-only": "", "aria-label": ...})
            if DESTRUCTIVE.search(m.group(1)):
                found["verb"].append(f"{rel}:{text.count(chr(10), 0, m.start()) + 1}")
        for m in re.finditer(r'data-action-icon="(history|minus|warn|safety|lock|wifi)"|actionIcon\([^,()]+,\s*"(history|minus|warn|safety|lock|wifi)"', text):
            found["status"].append(f"{rel}:{text.count(chr(10), 0, m.start()) + 1}")
        if rel.endswith(".html"):
            depth = 0
            for m in re.finditer(r"<(/?)details\b", text):
                depth += -1 if m.group(1) else 1
                if depth > 1 and not m.group(1):
                    found["details"].append(f"{rel}:{text.count(chr(10), 0, m.start()) + 1}")
        for m in re.finditer(r'data-ui-tooltip(?:"\s*,\s*|\s*=\s*)"([^"$`{}]+)"', text):
            value, line = m.group(1), text.count("\n", 0, m.start()) + 1
            icon_only = "data-icon-only" in text[max(0, m.start() - 300):m.end() + 300]
            sentences = len(re.findall(r"[.!?。]\s|다\.\s|[.!?。]$", value + " "))
            if (icon_only and len(value) > 12) or sentences > 2:
                found["tooltip"].append(f"{rel}:{line}")
    return found


# Exception lists: file -> allowed count today. Entries may only shrink (re-layout work removes them).
EXCEPTIONS = {
    "title": {},
    "name": {},
    # styleguide.html is the sample page for icon-only nav/tab/toggle states: 6 deliberate samples, shrink when the sample
    # switches to labelled rows.
    "verb": {"middleware/robot_ui/robot/styleguide.html": 6},
    "details": {},
    "tooltip": {},
    # Fleet rails/tabs moved to list/task (relayout-fleet); Robot styleguide/host panel moved (restructure-base).
    "status": {},
}


def per_file(items):
    counts = {}
    for item in items:
        counts[item.rsplit(":", 1)[0]] = counts.get(item.rsplit(":", 1)[0], 0) + 1
    return counts


def check(gate):
    actual, listed = per_file(violations()[gate]), EXCEPTIONS[gate]
    grew = {f: n for f, n in actual.items() if n > listed.get(f, 0)}
    stale = {f: n for f, n in listed.items() if actual.get(f, 0) < n}
    assert not grew, f"{gate}: new violations {grew}"
    assert not stale, f"{gate}: lower the exception list {stale}"


def test_no_title_attribute_on_icon_only_controls():
    check("title")


def test_icon_only_controls_have_a_name_and_a_tooltip():
    check("name")


def test_nav_and_destructive_verbs_are_never_icon_only():
    check("verb")


def test_details_are_never_nested_in_product_pages():
    check("details")


def test_tooltips_stay_short_names_or_two_sentence_definitions():
    check("tooltip")


def test_status_glyphs_are_not_reused_for_other_meanings_in_product_surfaces():
    check("status")
