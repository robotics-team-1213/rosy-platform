"""D-889 addendum 32 (2026-11-09 bottleneck report 4-8): API pin conflicts, mixed branches, the unattended rollup,
the watchdog's rollup schedule and the stage numbers."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import land_merge  # noqa: E402

HEAD = b"# Ref\n\n**Version:** v1.%d\n\n"
OLD = b"### v1.10 old\n\n- old fact\n\n## 1. Rules\n\nbody\n"


def section(n: int) -> bytes:
    return b"### v1.%d new %d\n\n- fact %d\n\n" % (n, n, n)


def ref(pin: int, *sections: int) -> bytes:
    return HEAD % pin + b"".join(section(n) for n in sections) + OLD


def test_both_sides_bumping_the_api_version_merge_with_the_higher_pin_and_newest_section_first():
    data = land_merge.api_version(ref(10), ref(11, 11), ref(12, 12))
    assert data == ref(12, 12, 11), data.decode()
    assert land_merge.api_version(ref(10), ref(12, 12), ref(11, 11)) == ref(12, 12, 11)


def test_contract_version_pins_take_the_higher_version():
    pin = b'CONTRACT = "ROSY-API-REF-001 v1.%d"\n'
    assert land_merge.api_version(pin % 10, pin % 12, pin % 11) == pin % 12
    assert land_merge.resolver("middleware/core/api/core_api_web/api/contract_version.py") == "api"
    assert land_merge.resolver(land_merge.API_REF) == "api"


@pytest.mark.parametrize("ours,theirs", [
    (ref(11, 11), ref(11, 11)),  # one number taken twice, without api_reserve: a person renumbers
    (ref(11, 11), ref(12, 12).replace(b"### v1.10 old", b"### v1.10 renamed")),  # an existing line changed
    (ref(11, 12), ref(12, 12)),  # a new section under a number the other side has
])
def test_api_conflicts_a_person_must_decide_stay_manual(ours, theirs):
    assert land_merge.api_version(ref(10), ours, theirs) is None


def fake_land(paths):
    class Stop(Exception):
        pass
    calls = []
    gate = lambda name: lambda *a: calls.append(name)  # noqa: E731
    return calls, SimpleNamespace(
        Stop=Stop, HARNESS="absent.py", out=lambda *a: "main-sha", lines=lambda *a: paths,
        safety_review=gate("safety"), size_check=gate("size"), secret_scan=gate("secret"),
        git=lambda *a, **k: SimpleNamespace(returncode=0, stdout=""))  # no grep hit: no CRLF added


