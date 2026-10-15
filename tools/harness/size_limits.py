"""D-766 size limits: one counting rule for the architecture guard and the per-commit range check.

Absolute limits, no baselines: a production file (``.py``/``.cpp``/``.hpp``/``.sh``) 600
lines, a web asset (``.js``/``.html``/``.css``) 800, a size unit (a package, or a subpackage
or holder listed in ``size_units.txt``) 10,000. What is already over is frozen at its
measured count in ``size_ratchet.txt``: the count may fall (and the row falls with it), never
rise. ``test/architecture/test_module_structure.py`` measures the working tree;
``size_range.py`` measures each commit of a range through git. Both call :func:`measure`
and :func:`ratchet_problems`, so the two cannot drift. Standard library only.
"""

from __future__ import annotations

import datetime as dt
from pathlib import PurePosixPath

FILE_LIMIT = 600
FILE_LIMIT_WEB = 800
UNIT_LIMIT = 10_000
#: D-766 3: a new unit is at least UNIT_FLOOR lines when its parent (before the split) is FLOOR_PARENT or more.
UNIT_FLOOR = 1_000
FLOOR_PARENT = 2_000
#: D-766 8: a safety fix may pass its ceiling by this much until the row's expiry.
SAFETY_MAX_OVER = 30
SAFETY_MAX_DAYS = 7

CODE_SUFFIXES = {".py", ".cpp", ".hpp", ".sh"}
WEB_SUFFIXES = {".js", ".html", ".css"}
OPS_SUFFIXES = {".py", ".sh"}
OPS_ROOTS = ("deploy", "tools", "learning",  # learning: moved perception tooling (D-427 wave 1)
             "operations/site_devices",  # site device firmware (D-427 wave 3b)
             "operations/situation")  # D-577 AI PC situation service (outside the fleet package)
#: Source folders outside a package's own directory whose files count toward that package.
PACKAGE_HOLDERS = {
    "control": tuple(f"middleware/drive/{holder}" for holder in
                     ("calibration", "recovery", "motion_limits", "tracking", "planning/grid", "runtime")),
    "core_features": ("middleware/drive/behaviors",),
    "fleet": ("operations/decision", "operations/site_ui/console", "integrations/messaging/discord"),
}

RATCHET = "test/architecture/size_ratchet.txt"
UNITS = "test/architecture/size_units.txt"
_SKIP = ("test", "tests", "build", "install", "log")


def is_prod(parts) -> bool:
    return not any(part in _SKIP or part.startswith(".") for part in parts)


def _under(path: str, folder: str) -> bool:
    return path.startswith(folder.rstrip("/") + "/")


def limit_for(path: str) -> int:
    return FILE_LIMIT_WEB if PurePosixPath(path).suffix in WEB_SUFFIXES else FILE_LIMIT


def _limit(key: str) -> int:
    return limit_for(key) if PurePosixPath(key).suffix in CODE_SUFFIXES | WEB_SUFFIXES else UNIT_LIMIT


def measure(files: dict[str, int], packages: dict[str, str], colcon_roots, units) -> tuple[dict, dict, dict]:
    """Count ``files`` (repo-relative posix path -> lines).

    ``packages`` maps a package name to its repo-relative directory. Returns ``(counts,
    over, owner)``: ``counts`` holds every unit and package total, ``over`` every file,
    unit or package above its limit (file keys are colcon-root-relative inside packages,
    repo-relative in ``OPS_ROOTS``), ``owner`` maps a counted file to the unit or package
    that takes its lines and each unit to its parent (enclosing unit, else package).
    """
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
            if count > limit_for(path):
                over[rel] = count
    for path, count in files.items():
        if (any(_under(path, root) for root in OPS_ROOTS) and PurePosixPath(path).suffix in OPS_SUFFIXES
                and is_prod(PurePosixPath(path).parts) and count > FILE_LIMIT):
            over[path] = count
            owner.setdefault(path, path)
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
        if base_rows is not None and key not in base_rows and key not in renamed:
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
    bad += [f"{unit}: new `small` mark; only grandfathered units carry one" for unit in sorted(small - base_small)]
    return bad
