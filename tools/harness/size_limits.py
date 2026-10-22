"""D-766 size limits: one counting rule for the architecture guard and the per-commit range check.

Absolute limits, no baselines: a production file (``.py``/``.cpp``/``.hpp``/``.sh``/``.kt``) and a
script (``.js``/``.mjs``/``.ts``) 600 lines, markup (``.html``/``.css``) 800 with at most 600 lines of
inline ``<script>``, a test file 1,500 (revision 2), a size unit (a package, a
standalone root in ``STANDALONE``, or a subpackage or holder listed in ``size_units.txt``) 10,000. What is already over is frozen at its
measured count in ``size_ratchet.txt``: the count may fall (and the row falls with it), never
rise. ``test/architecture/test_module_structure.py`` measures the working tree;
``size_range.py`` measures each commit of a range through git. Both call :func:`measure`
and :func:`ratchet_problems`, so the two cannot drift. Standard library only.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import PurePosixPath

FILE_LIMIT = 600
FILE_LIMIT_WEB = 800
#: D-766 revision 2: script assets take the code limit; markup keeps 800, its inline script 600.
SCRIPT_SUFFIXES = {".js", ".mjs", ".ts"}
INLINE_SCRIPT_LIMIT = 600
INLINE_SCRIPT = re.compile(r"<script\b[^>]*>(.*?)</script>", re.S | re.I)
#: D-766 revision 2: test files (under a test/tests folder), browser tests included.
TEST_LIMIT = 1_500
UNIT_LIMIT = 10_000
#: D-766 3: a new unit is at least UNIT_FLOOR lines when its parent (before the split) is FLOOR_PARENT or more.
UNIT_FLOOR = 1_000
FLOOR_PARENT = 2_000
#: D-766 8: a safety fix may pass its ceiling by this much until the row's expiry.
SAFETY_MAX_OVER = 30
SAFETY_MAX_DAYS = 7

CODE_SUFFIXES = {".py", ".cpp", ".hpp", ".sh", ".kt"}
WEB_SUFFIXES = {".js", ".mjs", ".ts", ".html", ".css"}
OPS_SUFFIXES = CODE_SUFFIXES | WEB_SUFFIXES
#: Roots outside every package: each file is held to its file limit, there is no unit total.
OPS_ROOTS = ("deploy", "tools", "learning",  # learning: moved perception tooling (D-427 wave 1)
             "applications/fleet/dev",  # D-830 development scripts; no operational package
             "operations/site_devices",  # site device firmware (D-427 wave 3b)
             "operations/signal_observation",  # one-file site service (D-766 coverage addendum)
             "operations/prediction")  # D-782 checker and shadow scripts, no package
#: Source folders outside a package's own directory whose files count toward that package.
#: fleet: the SOURCE_ROOTS of operations/fleet/fleet/_source_layout.py (a test keeps them equal).
PACKAGE_HOLDERS = {
    "control": tuple(f"middleware/drive/{holder}" for holder in
                     ("calibration", "recovery", "motion_limits", "tracking", "planning/grid", "runtime")),
    "core_features": ("middleware/drive/behaviors",),
    "fleet": ("operations/decision", "applications/fleet/web", "operations/situation",
              "operations/site_execution", "integrations/messaging/discord"),
}
#: Product roots without a package.xml (pyproject distributions, the Gradle app), counted like a package.
STANDALONE = {
    "rosy-contracts-learning": "contracts/learning",
    "rosy-contracts-motion": "contracts/motion",
    "rosy-contracts-skill": "contracts/skill",
    "rosy-integration-robot-omx": "integrations/robots/omx",
    "rosy-app-agent": "middleware/devices/omx/agent",
    "rosy-execution-local": "middleware/robot_execution/local",
    "rosy-skill-api": "middleware/skills/api",
    "rosy-skill-manipulation": "middleware/skills/manipulation",
    "rosy-app-gateway": "applications/fleet/gateway",
    "rosy-palletizing": "operations/processes/palletizing",
    "rosy-world": "operations/world",
    "rosy-cam": "operations/site_ui/cam",
    "rosy-media": "operations/site_ui/media",
    "rosy-media-edge": "middleware/media",
}
#: D-766 coverage addendum (2026-10-15): files already over their limit when the roots above and
#: ``.kt`` joined the count. Each may enter the ratchet as a new row once, at no more than this.
#: D-766 revision 2 (2026-10-16): the scripts over 600 and the test files over 1,500 when those limits began.
COVERAGE_ROWS = {
    "site_ui/cam/app/src/main/java/io/github/livsbittt/rosy/cam/camera/CameraController.kt": 791,
    "robot_ui/pilot/screens/drive.js": 783, "fleet/web/line-stuck.js": 756,
    "fleet/web/roster.js": 711, "fleet/web/shared/site-map-model.js": 800,
    "fleet/web/shared/vision-view.js": 788, "fleet/web/sitemap/site-map.js": 771,
    "middleware/core/events/test/test_audit.py": 1533,
    "middleware/robot_ui/pilot/test/test_pilot_browser.py": 3059,
    "operations/fleet/test/test_trip_runner.py": 1757,
    "test/learning/perception/test_review_flow_browser.py": 1531,
    "test/test_dashboard_browser.py": 3049, "test/test_fleet_console_browser.py": 3884,
    "test/test_rosy_auto_update.py": 2632, "test/test_rosy_face.py": 2484,
    "test/test_sd_writer_contract.py": 2725,
}

RATCHET = "test/architecture/size_ratchet.txt"
UNITS = "test/architecture/size_units.txt"
_SKIP = ("test", "tests", "build", "install", "log")


def is_prod(parts) -> bool:
    return (not any(part in _SKIP or part.startswith(".") for part in parts)
            and ("src", "androidTest") not in zip(parts, parts[1:]))


def _under(path: str, folder: str) -> bool:
    return path.startswith(folder.rstrip("/") + "/")


def is_test(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return (PurePosixPath(path).suffix in OPS_SUFFIXES
            and (any(p in ("test", "tests") for p in parts) or ("src", "androidTest") in zip(parts, parts[1:]))
            and not any(p in ("build", "install", "log") or p.startswith(".") for p in parts))


def limit_for(path: str) -> int:
    if is_test(path):
        return TEST_LIMIT
    suffix = PurePosixPath(path).suffix
    return FILE_LIMIT_WEB if suffix in WEB_SUFFIXES - SCRIPT_SUFFIXES else FILE_LIMIT


def inline_script_lines(text: str) -> int:
    """Lines inside an ``.html`` file's ``<script>`` elements (revision 2: at most INLINE_SCRIPT_LIMIT)."""
    return sum(match.group(1).count("\n") for match in INLINE_SCRIPT.finditer(text))


def _over_limit(path: str, count: int, scripts: dict) -> bool:
    return count > limit_for(path) or scripts.get(path, 0) > INLINE_SCRIPT_LIMIT


def _limit(key: str) -> int:
    return limit_for(key) if PurePosixPath(key).suffix in CODE_SUFFIXES | WEB_SUFFIXES else UNIT_LIMIT


def measure(files: dict[str, int], packages: dict[str, str], colcon_roots, units,
            scripts: dict[str, int] | None = None) -> tuple[dict, dict, dict]:
    """Count ``files`` (repo-relative posix path -> lines).

    ``packages`` maps a package name to its repo-relative directory. Returns ``(counts,
    over, owner)``: ``counts`` holds every unit and package total, ``over`` every file,
    unit or package above its limit (file keys are colcon-root-relative inside packages,
    repo-relative in ``OPS_ROOTS`` and for test files), ``owner`` maps a counted file to the unit or package
    that takes its lines and each unit to its parent (enclosing unit, else package).
    ``scripts`` maps an ``.html`` path to its inline script lines (``inline_script_lines``).
    """
    scripts = scripts or {}
    roots = tuple(colcon_roots)
    counts = dict.fromkeys(units, 0)
    over, owner, package_of = {}, {}, {}
    for name, directory in packages.items():
        counts[name] = 0
        dirs = (directory, *PACKAGE_HOLDERS.get(name, ()))
        for path, count in files.items():
            if PurePosixPath(path).suffix not in CODE_SUFFIXES | WEB_SUFFIXES or not any(_under(path, d) for d in dirs):
                continue
            root = next((r for r in roots if _under(path, r)), None)
            rel = path[len(root) + 1:] if root else path
            if not is_prod(PurePosixPath(rel).parts):
                continue
            unit = max((u for u in units if _under(rel, u)), key=len, default=None)  # innermost
            key = unit or name
            counts[key] += count
            owner[path] = key
            if unit:
                package_of[unit] = name
            if _over_limit(path, count, scripts):
                over[rel] = count
    for path, count in files.items():
        root = next((root for root in OPS_ROOTS if _under(path, root)), None)
        if root and PurePosixPath(path).suffix in OPS_SUFFIXES and is_prod(PurePosixPath(path).parts):
            owner.setdefault(path, root)
            if _over_limit(path, count, scripts):
                over[path] = count
        elif is_test(path) and count > TEST_LIMIT:
            over[path] = count
    for unit in units:
        owner[unit] = max((u for u in units if u != unit and _under(unit, u)), key=len,
                          default=package_of.get(unit))
    over.update((key, count) for key, count in counts.items() if count > UNIT_LIMIT)
    return counts, over, owner


def parse_ratchet(text: str) -> tuple[dict[str, int], dict[str, tuple[int, dt.date]]]:
    """``<count> <key>`` rows and ``safety <count> <key> <YYYY-MM-DD>`` rows; ``#`` comments."""
    rows, safety = {}, {}
    for number, line in enumerate(text.splitlines(), 1):
        fields = line.split("#", 1)[0].split()
        try:
            if not fields:
                continue
            if fields[0] == "safety" and len(fields) == 4 and fields[2] not in safety:
                safety[fields[2]] = (int(fields[1]), dt.date.fromisoformat(fields[3]))
            elif len(fields) == 2 and fields[1] not in rows:
                rows[fields[1]] = int(fields[0])
            else:
                raise ValueError(line)
        except ValueError as exc:
            raise ValueError(f"{RATCHET}:{number}: expected '<count> <key>' or "
                             f"'safety <count> <key> <YYYY-MM-DD>', got {line!r}") from exc
    return rows, safety


def parse_units(text: str) -> tuple[list[str], set[str]]:
    """One unit per line, ``<path>`` or ``<path> small`` (grandfathered below the floor)."""
    units, small = [], set()
    for number, line in enumerate(text.splitlines(), 1):
        fields = line.split("#", 1)[0].split()
        if not fields:
            continue
        if len(fields) > 2 or fields[1:] not in ([], ["small"]) or fields[0] in units:
            raise ValueError(f"{UNITS}:{number}: expected '<unit>' or '<unit> small', got {line!r}")
        units.append(fields[0])
        if fields[1:]:
            small.add(fields[0])
    return units, small


def render_ratchet(over: dict[str, int]) -> str:
    return "".join(f"{count} {key}\n" for key, count in sorted(over.items()))


def regenerate(text: str, over: dict[str, int]) -> str:
    """Rewrite the measured rows of ``text``: comments and ``safety`` rows stay, an existing row
    only goes down (never above its value), a safety key keeps its row, a row back under the limit
    goes. New over-limit keys get a row (the guard refuses them against a base that lacks them)."""
    rows, safety = parse_ratchet(text)
    keep = [line for line in text.splitlines(True) if line.startswith("#") or line.startswith("safety ")]
    new = {key: (rows[key] if key in safety else min(rows[key], count)) if key in rows else count
           for key, count in over.items()}
    new.update((key, rows[key]) for key in safety if key in rows)
    return "".join(keep) + render_ratchet(new)


def ratchet_problems(over: dict[str, int], rows: dict[str, int], safety: dict, base_rows: dict | None,
                     today: dt.date, safety_commit=None, keys=None, base_safety: dict | None = None) -> list[str]:
    """Why the ratchet does not match ``over``; empty when it does.

    ``base_rows``/``base_safety`` are the rows at the base (None: no ratchet there yet, first
    landing). ``safety_commit(key)`` returns ``(commit date, has Safety-Review trailer)`` for the
    commit that added that key's safety row, or None when it is not committed. ``keys`` limits
    the report (the range check reports only what a commit touched). ``today`` is the run date,
    so a safety row that was green when committed turns red on the first run after its expiry,
    whatever the change (D-766 8: the split is due by then).

    A new row is allowed only as a rename (a pure move): a base row of the same kind (file or
    unit) disappears in the same change and the new row is not above it.
    """
    bad = []
    wanted = (lambda key: keys is None or key in keys)
    file_kind = (lambda key: PurePosixPath(key).suffix in CODE_SUFFIXES | WEB_SUFFIXES)
    gone = sorted((key for key in (base_rows or {}) if key not in rows), key=lambda key: base_rows[key])
    renamed = {}
    for key in sorted(set(rows) - set(base_rows or {}), key=lambda key: rows[key]):
        old = next((g for g in gone if file_kind(g) == file_kind(key) and base_rows[g] >= rows[key]), None)
        if base_rows is not None and old is not None:
            gone.remove(old)
            renamed[key] = old
    for key in sorted(set(over) - set(rows)):
        if wanted(key):
            bad.append(f"{key}: {over[key]} lines is over {_limit(key)};"
                       " split it below the limit (D-766 2), no new ratchet row")
    for key in sorted(set(rows) - set(over)):
        if wanted(key):
            bad.append(f"{key}: back under the limit; delete its ratchet row")
    for key, ceiling in sorted(rows.items()):
        if key not in over or not wanted(key):
            continue
        if (base_rows is not None and key not in base_rows and key not in renamed
                and not ceiling <= COVERAGE_ROWS.get(key, -1)):
            bad.append(f"{key}: new ratchet row; split it instead (only `safety` rows, or a rename whose old"
                       " row goes in the same change, may be added)")
        elif base_rows is not None and key in base_rows and ceiling > base_rows[key]:  # renamed: checked above
            bad.append(f"{key}: row raised {base_rows[key]} -> {ceiling}; rows only go down")
        measured = over[key]
        if key in safety:
            allowed, expiry = safety[key]
            if measured != allowed:
                bad.append(f"{key}: measured {measured}, safety row says {allowed}; set it to {measured}")
            if allowed > ceiling + SAFETY_MAX_OVER:
                bad.append(f"{key}: safety row {allowed} is more than {SAFETY_MAX_OVER} over the ceiling {ceiling}")
            if measured < ceiling:
                bad.append(f"{key}: shrank below its ceiling {ceiling} -> {measured}; delete the safety row and "
                           f"lower its ratchet row to {measured}")
        elif measured > ceiling:
            bad.append(f"{key}: grew {ceiling} -> {measured}; split it below the limit first (D-766 4)")
        elif measured < ceiling:
            bad.append(f"{key}: shrank {ceiling} -> {measured}; lower its ratchet row to {measured} in this change")
    for key, (allowed, expiry) in sorted(safety.items()):
        if not wanted(key):
            continue
        if key not in rows:
            bad.append(f"{key}: safety row without a ratchet row; the exception covers frozen paths only")
        if base_safety and key in base_safety and base_safety[key] != safety[key]:
            bad.append(f"{key}: safety row changed from the base {base_safety[key]}; it is never renewed")
        if today > expiry:
            bad.append(f"{key}: safety row expired {expiry}; split it below the limit and delete the row")
        found = safety_commit(key) if safety_commit else None
        if found is None:
            bad.append(f"{key}: safety row is not in a commit (git history needed to check its trailer)")
            continue
        date, trailer = found
        if not trailer:
            bad.append(f"{key}: the commit adding the safety row has no `Safety-Review:` trailer (D-430 5)")
        if expiry > date + dt.timedelta(days=SAFETY_MAX_DAYS):
            bad.append(f"{key}: safety expiry {expiry} is more than {SAFETY_MAX_DAYS} days after {date}")
    return bad


def unit_problems(counts: dict, owner: dict, units, small: set, base_small: set) -> list[str]:
    """D-766 3: units count lines; a unit below the floor whose parent (before it left) was
    FLOOR_PARENT or more needs a grandfathered ``small`` mark; marks are never added."""
    bad = []
    for unit in units:
        if counts.get(unit, 0) <= 0:
            bad.append(f"{unit}: counts no lines")
            continue
        parent_before = counts.get(owner.get(unit), 0) + counts[unit]
        if unit not in small and counts[unit] < UNIT_FLOOR and parent_before >= FLOOR_PARENT:
            bad.append(f"{unit}: {counts[unit]} lines, below the {UNIT_FLOOR} floor for a parent of "
                       f"{parent_before}; move a whole responsibility or do not register it")
        if unit in small and counts[unit] >= UNIT_FLOOR:
            bad.append(f"{unit}: {counts[unit]} lines, no longer small; drop its `small` mark")
    # D-822: the existing small work holder moved without changing its contents.
    base_small = {"fleet/web/work" if unit == "site_ui/console/work" else unit for unit in base_small}
    bad += [f"{unit}: new `small` mark; only grandfathered units carry one" for unit in sorted(small - base_small)]
    return bad
