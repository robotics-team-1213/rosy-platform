"""Main-red carry-over inside tools/land.py: no land record, carried ids in every selection, no FULL reuse."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import doctor  # noqa: E402
import land  # noqa: E402
from test_land import commit, git, repos  # noqa: E402,F401  (land.py's fixture repos)

ID = "pkg/test/test_a.py::test_a"


def test_a_carrying_landing_lands_without_a_land_record_and_records_the_carry(repos, monkeypatch):
    main, wt = repos
    commit(wt, {"pkg/a.py": "x = 2\n"}, "branch")
    monkeypatch.setattr(land.land_checks, "verdict", lambda *a, **k: (1, [], "MAIN-RED: also fails on main"))
    monkeypatch.setattr(land.land_checks, "carry", lambda *a, **k: (
        land.land_mainred.CARRIED.append((ID, "m" * 40, "why", tuple(a[4]))) or [ID], "why"))
    assert land.main(["--tests", "auto"]) == 0
    landed = git(main, "rev-parse", "HEAD")
    assert landed == git(wt, "rev-parse", "HEAD"), "it landed"
    assert land.land_record.read(main, landed) is None, "never a green record"
    carries = [r for r in land.land_mainred.read(wt) if r["event"] == "carry"]
    assert [(r["id"], r["sha"]) for r in carries] == [(ID, landed)]
    assert subprocess.run(["git", "-C", str(main), "merge-base", "--is-ancestor", carries[0]["sha"], "main"]
                          ).returncode == 0, "a carry names a commit main holds, so a later pass can cover it"

    monkeypatch.setattr(land.land_checks, "carry", lambda *a, **k: ([], "fingerprint differs"))
    commit(wt, {"pkg/a.py": "x = 3\n"}, "next")
    assert land.main(["--tests", "auto"]) == 1, "the mutation: no carry, the NEW stops as before"


def test_carried_ids_join_every_selection_and_a_carried_full_is_never_restored(repos):
    main, wt = repos
    land.land_mainred.write(wt, "red", id=ID, main=git(main, "rev-parse", "HEAD"), fp="f", env=[], by="x")
    land.land_mainred.write(wt, "carry", id=ID, main="m", sha=git(main, "rev-parse", "HEAD"), branch="b", why="")
    commit(wt, {"pkg/a.py": "x = 2\n"}, "branch")
    invocations, _ = land.select(wt, "main", sys.executable)
    assert ["-rA", ID] in invocations, "every selection runs the carried id until a pass covers it"
    assert ["-rA", ID] not in land.select(wt, "main", sys.executable, head="HEAD", landed=True)[0]
    head, base = git(wt, "rev-parse", "HEAD"), git(main, "rev-parse", "HEAD")
    land.land_full.save(wt, "feat/x", head, base, "carried", invocations)
    assert land.land_full.restore(wt, "feat/x") is None
    land.land_full.save(wt, "feat/x", head, base, "full", invocations)
    assert land.land_full.restore(wt, "feat/x") == base, "the mutation: a full tier is restored"


def test_no_pretest_starts_in_the_test_pcs_reboot_window(capsys):
    clock = iter([(5, 30), (5, 59), (6, 10)])
    naps = []

    def at():
        h, m = next(clock)
        return time.struct_time((2026, 10, 27, h, m, 0, 0, 300, -1))

    land.land_prepare.after_reboot(None, sleep=naps.append, clock=at)
    assert len(naps) == 2 and "reboot at 06:00" in capsys.readouterr().out
    land.land_prepare.after_reboot(None, sleep=naps.append, clock=lambda: time.struct_time((2026, 10, 27, 6, 10, 0, 0, 300, -1)))
    assert len(naps) == 2, "outside the window it does not wait"


def test_doctor_shows_open_main_red_records(repos):
    main, wt = repos
    out: list[str] = []
    doctor.run(main, out=out.append)
    assert "OK   main-red: no open record" in "\n".join(out)
    land.land_mainred.write(wt, "red", id=ID, main=git(main, "rev-parse", "HEAD"), fp="f", env=[], by="x")
    out.clear()
    doctor.run(main, out=out.append)
    assert f"WARN main-red {ID}: red 0 min, owner none" in "\n".join(out)
