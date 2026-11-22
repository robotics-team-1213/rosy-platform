"""Static icon and tooltip gates (concept rules 8-11, 14; D-926).

Gates scan product web surfaces (surfaces.yaml, medium web) statically: HTML tags and JS literals. Each gate has an explicit
exception list of CURRENT violations, counted per file; the lists may only shrink (a count above the list fails, a count
below it fails too until the list is lowered). The glyph catalog check (every actionIcon glyph has one category and a Korean
label) arrives with the icon catalog itself.
"""

import re

import surface_registry as registry


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
    # switches to labelled rows. connect.js: one icon-only control with a stop/release word in its name, to relabel.
    "verb": {"middleware/robot_ui/robot/styleguide.html": 6, "middleware/robot_ui/pilot/screens/connect.js": 1},
    "details": {},
    "tooltip": {"middleware/robot_ui/robot/styleguide.html": 1},
    # Status glyphs (history, minus, warn, safety, lock, wifi) used directly instead of through the shared status tag.
    "status": {
        "middleware/robot_ui/robot/styleguide.html": 2,
        "middleware/robot_ui/robot/panels/host/operations.js": 1,
        "applications/fleet/web/cell/cell.html": 1,
        "applications/fleet/web/index.html": 2,
        "applications/fleet/web/installation/install.html": 1,
        "applications/fleet/web/maintenance/maintenance.html": 1,
        "applications/fleet/web/sitemap/site-map.html": 1,
        "applications/fleet/web/work/policy.html": 1,
    },
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


# Fleet chrome actionIcon & header glyph contracts (merged from retired test_action_icon_contract.py)
CHROME_ICONS = ("settings:", '"theme-dark":', '"theme-light":', '"theme-system":', "estop:")
SESSION_ICONS = ("login:", "account:", "logout:")


def test_action_icon_names_cover_fleet_chrome_and_keep_screen_reader_text():
    ui_js = registry.REPO / "shared" / "web" / "ui.js"
    body = ui_js.read_text(encoding="utf-8").split("export function actionIcon", 1)[1]
    for name in (*CHROME_ICONS, *SESSION_ICONS):
        assert name in body, name
    assert "sr-only" in body
    glyphs = re.findall(r'^\s+"?([\w-]+)"?: "([^"]+)",$', body.split("};", 1)[0], re.M)
    paths = [d for _, d in glyphs]
    assert len(glyphs) > 40 and len(set(paths)) == len(paths), [n for n, d in glyphs if paths.count(d) > 1]
    names = dict(glyphs)
    assert names["tools"] != names["settings"] and names["fit"] != names["box"] != names["expand"]
    for side in ("pose:", "yaw:", "battery:", "safety:"):
        assert side in body, side


def test_fleet_documents_share_the_stop_and_chrome_icons():
    fleet_web = registry.REPO / "applications" / "fleet" / "web"
    for name in ("index.html", "installation/install.html"):
        page = (fleet_web / name).read_text(encoding="utf-8")
        assert 'data-action-icon="estop"' in page
        assert ">비상 정지</span>" in page
        assert "래치 · 로봇별 관리자 해제" in page
        assert 'sr-only">전체 비상 정지' not in page
        for icon in ("notification", "theme-dark", "refresh"):
            assert f'data-action-icon="{icon}"' in page, (name, icon)
        assert ('data-action-icon="connect"' in page) == (name == "index.html"), name
        assert 'd="M4 7h16' not in page
