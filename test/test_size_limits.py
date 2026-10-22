"""D-766 size rule (tools/harness/size_limits.py): the mutation proofs of D-766 7(a) 6 on small inputs."""

import datetime as dt
from pathlib import Path

import pytest

import size_limits as s

TODAY = dt.date(2026, 10, 15)
ROOTS = ("middleware",)
PACKAGES = {"pkg": "middleware/pkg"}


def _over(**files):
    return s.measure({f"middleware/pkg/{name.replace('__', '/')}.py": n for name, n in files.items()},
                     PACKAGES, ROOTS, ["pkg/unit"])


def _problems(over, rows, base=None, safety=None, commit=(TODAY, True)):
    return s.ratchet_problems(over, rows, safety or {}, base, TODAY, lambda key: commit)


def test_measure_counts_units_innermost_and_keys_files_by_colcon_root():
    counts, over, owner = s.measure(
        {"middleware/pkg/a.py": 700, "middleware/pkg/unit/b.py": 50, "middleware/pkg/test/t.py": 900,
         "middleware/pkg/web/x.js": 801, "tools/run.py": 601, "tools/test/t.py": 999},
        PACKAGES, ROOTS, ["pkg/unit"])
    assert counts == {"pkg/unit": 50, "pkg": 1501}
    assert over == {"pkg/a.py": 700, "pkg/web/x.js": 801, "tools/run.py": 601}
    assert owner["middleware/pkg/unit/b.py"] == "pkg/unit" and owner["pkg/unit"] == "pkg"


def test_a_matching_ratchet_is_green():
    _, over, _ = _over(a=700)
    assert _problems(over, {"pkg/a.py": 700}, base={"pkg/a.py": 700}) == []


@pytest.mark.parametrize("over_files, rows, base, needle", [
    ({"a": 601}, {}, {}, "split it below the limit"),                          # new over-limit file
    ({"a": 701}, {"pkg/a.py": 700}, {"pkg/a.py": 700}, "grew 700 -> 701"),       # frozen file +1 line
    ({"a": 701}, {"pkg/a.py": 701}, {"pkg/a.py": 700}, "rows only go down"),     # row raised over the base
    ({"a": 650}, {"pkg/a.py": 700}, {"pkg/a.py": 700}, "lower its ratchet row to 650"),  # row above measured
    ({"a": 650}, {"pkg/a.py": 650}, {}, "new ratchet row"),                      # row added in the change
    ({"a": 500}, {"pkg/a.py": 700}, {"pkg/a.py": 700}, "delete its ratchet row"),  # back under the limit
])
def test_ratchet_mutations_are_red(over_files, rows, base, needle):
    _, over, _ = _over(**over_files)
    assert any(needle in problem for problem in _problems(over, rows, base=base)), _problems(over, rows, base=base)


def test_safety_row_allows_up_to_30_over_until_it_expires():
    _, over, _ = _over(a=720)
    rows, base = {"pkg/a.py": 700}, {"pkg/a.py": 700}
    ok = {"pkg/a.py": (720, TODAY + dt.timedelta(days=7))}
    assert _problems(over, rows, base=base, safety=ok, commit=(TODAY, True)) == []
    expired = {"pkg/a.py": (720, TODAY - dt.timedelta(days=1))}
    assert any("expired" in p for p in _problems(over, rows, base, expired, commit=(TODAY - dt.timedelta(days=3), True)))
    assert any("no `Safety-Review:`" in p for p in _problems(over, rows, base, ok, commit=(TODAY, False)))
    assert any("not in a commit" in p for p in _problems(over, rows, base, ok, commit=None))
    late = {"pkg/a.py": (720, TODAY + dt.timedelta(days=8))}
    assert any("more than 7 days" in p for p in _problems(over, rows, base, late))
    _, far, _ = _over(a=731)
    assert any("more than 30 over" in p for p in _problems(far, rows, base, {"pkg/a.py": (731, TODAY)}))


def test_a_coverage_row_may_be_new_once_at_no_more_than_its_count(monkeypatch):
    monkeypatch.setattr(s, "COVERAGE_ROWS", {"pkg/a.py": 650})
    _, over, _ = _over(a=650)
    assert _problems(over, {"pkg/a.py": 650}, base={}) == []
    _, over, _ = _over(a=651)
    assert any("new ratchet row" in p for p in _problems(over, {"pkg/a.py": 651}, base={}))


def test_ops_root_files_are_owned_and_held_to_their_own_limit():
    _, over, owner = s.measure({"tools/a.kt": 601, "tools/b.css": 700, "tools/c.mjs": 601}, {}, ROOTS, [])
    assert over == {"tools/a.kt": 601, "tools/c.mjs": 601}
    assert owner == {"tools/a.kt": "tools", "tools/b.css": "tools", "tools/c.mjs": "tools"}


def test_revision_2_scripts_take_600_markup_800_and_its_inline_script_600():
    files = {"middleware/pkg/web/a.js": 601, "middleware/pkg/web/b.css": 799, "middleware/pkg/web/c.html": 700,
             "middleware/pkg/web/d.html": 700, "middleware/pkg/web/e.ts": 600}
    _, over, _ = s.measure(files, PACKAGES, ROOTS, [], {"middleware/pkg/web/c.html": 601,
                                                        "middleware/pkg/web/d.html": 600})
    assert over == {"pkg/web/a.js": 601, "pkg/web/c.html": 700}
    page = "<p>x</p>\n<script type=module>\n" + "f();\n" * 3 + "</script>\n<SCRIPT>\ng();\n</SCRIPT>\n"
    assert s.inline_script_lines(page) == 6


def test_revision_2_test_files_are_held_to_1500_wherever_they_live():
    files = {"test/test_a.py": 1501, "middleware/pkg/test/test_b.py": 1501, "tools/test/test_c.py": 1500,
             "operations/fleet/test/web/d.test.mjs": 1501, "middleware/pkg/build/test/x.py": 9000}
    counts, over, _ = s.measure(files, PACKAGES, ROOTS, [])
    assert over == {"test/test_a.py": 1501, "middleware/pkg/test/test_b.py": 1501,
                    "operations/fleet/test/web/d.test.mjs": 1501}
    assert counts == {"pkg": 0}  # test lines never count toward a package or unit
    assert any("over 1500" in p for p in _problems(over, {}, base={}))


@pytest.mark.parametrize("test_lines", [1500, 1501])
def test_android_instrumentation_sources_are_tests_not_package_code(test_lines):
    app = "operations/site_ui/cam/app"
    instrumented = f"{app}/src/androidTest/java/cam/RecoveryTest.kt"
    main = f"{app}/src/main/java/cam/StreamScreen.kt"
    lookalike = f"{app}/src/main/java/androidTest/Camera.kt"
    files = {instrumented: test_lines, main: 600, lookalike: 1}
    counts, over, owner = s.measure(files, {"rosy-cam": "operations/site_ui/cam"}, ("operations",), [])
    assert counts == {"rosy-cam": 601}
    assert owner == {main: "rosy-cam", lookalike: "rosy-cam"}
    assert over == ({instrumented: 1501} if test_lines == 1501 else {})
    if test_lines == 1501:
        assert any("over 1500" in p for p in _problems(over, {}, base={}))


def test_units_floor_applies_to_new_units_of_large_parents_only():
    counts = {"pkg": 2500, "pkg/unit": 400}
    owner = {"pkg/unit": "pkg"}
    assert any("below the 1000 floor" in p for p in s.unit_problems(counts, owner, ["pkg/unit"], set(), set()))
    assert s.unit_problems(counts, owner, ["pkg/unit"], {"pkg/unit"}, {"pkg/unit"}) == []  # grandfathered
    assert any("new `small` mark" in p for p in s.unit_problems(counts, owner, ["pkg/unit"], {"pkg/unit"}, set()))
    assert s.unit_problems({"pkg": 1500, "pkg/unit": 400}, owner, ["pkg/unit"], set(), set()) == []  # parent < 2000
    assert any("no longer small" in p for p in s.unit_problems({"pkg": 9000, "pkg/unit": 1200}, owner,
                                                                 ["pkg/unit"], {"pkg/unit"}, {"pkg/unit"}))


def test_fleet_work_holder_move_preserves_only_its_existing_small_mark():
    unit = "fleet/web/work"
    counts, owner = {"fleet": 9000, unit: 796}, {unit: "fleet"}
    assert s.unit_problems(counts, owner, [unit], {unit}, {"site_ui/console/work"}) == []
    assert any("new `small` mark" in problem for problem in
               s.unit_problems(counts, owner, [unit], {unit}, set()))
    assert any("no longer small" in problem for problem in
               s.unit_problems({"fleet": 9000, unit: 1000}, owner, [unit], {unit}, {"site_ui/console/work"}))


def test_data_file_parsers_reject_malformed_rows():
    rows, safety = s.parse_ratchet("# c\n700 pkg/a.py\nsafety 720 pkg/a.py 2026-10-20\n")
    assert rows == {"pkg/a.py": 700} and safety == {"pkg/a.py": (720, dt.date(2026, 10, 20))}
    assert s.parse_units("a\nb small  # old\n") == (["a", "b"], {"b"})
    for bad in ("700\n", "x pkg/a.py\n", "700 a\n700 a\n", "safety 1 a\n"):
        with pytest.raises(ValueError):
            s.parse_ratchet(bad)
    with pytest.raises(ValueError):
        s.parse_units("a big\n")


def test_range_check_is_red_on_a_commit_that_grows_before_a_later_split(tmp_path, monkeypatch, capsys):
    """D-766 2 (bisect): over the limit in one commit, split in the next, is red on the first."""
    import shutil
    import subprocess

    import size_range

    if shutil.which("git") is None:
        pytest.skip("git is required")
    monkeypatch.chdir(tmp_path)
    for key in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(key, "t")
    for key in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(key, "t@x")

    def git(*args):
        return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()

    def commit(files, message):
        for path, text in files.items():
            (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / path).write_text(text, encoding="utf-8")
        git("add", "-A")
        git("commit", "-q", "--no-verify", "-m", message)
        return git("rev-parse", "HEAD")

    git("init", "-q", "-b", "main")
    git("config", "core.autocrlf", "false")
    base = commit({"middleware/pkg/package.xml": "<package><name>pkg</name></package>\n",
                   "middleware/pkg/pkg/a.py": "x = 1\n" * 500, s.RATCHET: "# rows\n", s.UNITS: "# units\n"}, "base")
    grown = commit({"middleware/pkg/pkg/a.py": "x = 1\n" * 601}, "grow a.py past 600")
    commit({"middleware/pkg/pkg/a.py": "x = 1\n" * 300, "middleware/pkg/pkg/b.py": "y = 1\n" * 301}, "split a.py")
    assert size_range.check(git("rev-parse", "HEAD")) == []
    assert any("pkg/pkg/a.py: 601 lines" in p for p in size_range.check(grown))
    assert size_range.main([base, "HEAD"]) == 1
    assert "grow a.py past 600" in capsys.readouterr().err
    assert size_range.main([grown, "HEAD"]) == 0
    # A merge's base row is the higher parent's: a row the other side already carried is not new or raised.
    git("checkout", "-q", "-b", "side", base)
    commit({"middleware/pkg/pkg/d.py": "w = 1\n" * 650, s.RATCHET: "# rows\n650 pkg/pkg/d.py\n"}, "side row")
    git("checkout", "-q", "main")
    git("merge", "-q", "--no-edit", "side")
    assert size_range.check(git("rev-parse", "HEAD")) == []
    # Each commit is judged by its own size_limits.py: a later stricter rule does not redden it.
    rule = Path(s.__file__).read_text(encoding="utf-8")
    loose = commit({"tools/harness/size_limits.py": rule.replace("FILE_LIMIT = 600", "FILE_LIMIT = 700"),
                    "middleware/pkg/pkg/c.py": "z = 1\n" * 650}, "c.py at 650 under a 700 rule")
    assert size_range.check(loose) == []


def test_a_row_moves_with_a_pure_move_only_when_the_old_row_goes():
    _, over, _ = s.measure({"middleware/pkg/new.py": 790}, PACKAGES, ROOTS, [])
    base = {"pkg/old.py": 797}
    assert _problems(over, {"pkg/new.py": 790}, base=base) == []  # old row gone, not above it
    assert any("new ratchet row" in p for p in _problems(over, {"pkg/new.py": 790}, base={"pkg/old.py": 700}))
    _, both, _ = s.measure({"middleware/pkg/new.py": 790, "middleware/pkg/old.py": 797}, PACKAGES, ROOTS, [])
    assert any("new ratchet row" in p for p in _problems(both, {"pkg/new.py": 790, "pkg/old.py": 797}, base=base))


def test_a_safety_row_from_the_base_is_never_renewed():
    _, over, _ = _over(a=720)
    rows = {"pkg/a.py": 700}
    old = {"pkg/a.py": (720, TODAY)}
    renewed = {"pkg/a.py": (720, TODAY + dt.timedelta(days=5))}
    assert s.ratchet_problems(over, rows, old, rows, TODAY, lambda k: (TODAY, True), base_safety=old) == []
    assert any("never renewed" in p for p in s.ratchet_problems(over, rows, renewed, rows, TODAY,
                                                                  lambda k: (TODAY, True), base_safety=old))


def test_a_safety_row_below_its_ceiling_asks_for_the_lower_row():
    _, over, _ = _over(a=650)
    assert any("delete the safety row and lower its ratchet row to 650" in p
               for p in _problems(over, {"pkg/a.py": 700}, base={"pkg/a.py": 700}, safety={"pkg/a.py": (650, TODAY)}))


def test_regenerate_never_raises_a_row_and_keeps_safety_keys():
    text = "# c\n700 pkg/a.py\n900 pkg/b.py\nsafety 720 pkg/b.py 2026-10-20\n650 pkg/gone.py\n"
    out = s.regenerate(text, {"pkg/a.py": 710, "pkg/b.py": 720, "pkg/c.py": 601})
    assert s.parse_ratchet(out)[0] == {"pkg/a.py": 700, "pkg/b.py": 900, "pkg/c.py": 601}
    assert out.startswith("# c\nsafety 720 pkg/b.py 2026-10-20\n")
    assert s.parse_ratchet(s.regenerate(text, {"pkg/a.py": 640}))[0] == {"pkg/a.py": 640, "pkg/b.py": 900}
    with pytest.raises(ValueError):
        s.parse_ratchet("safety 1 a 2026-10-20\nsafety 2 a 2026-10-21\n")
