"""Frozen control lists: safety-separation exceptions and Fleet ledger writers.

패널 보고서 2026-11-04 쟁점 C: ``KNOWN_SAFETY_VIOLATIONS``와 ``KNOWN_WRITERS``는
현재 값에서 동결한다. 상향은 리드 사전 승인 후 이 파일의 cap과 team-guide §5.1을
함께 고친다. shrink는 자유다.
"""

import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
SAFETY_CAP = 26  # RED 변이: 실제 27보다 1 낮춰 검사가 실패함을 증명한다
WRITER_CAP = 19  # RED 변이: 실제 20보다 1 낮춰 검사가 실패함을 증명한다


def _count(file_name: str, attr: str) -> int:
    spec = importlib.util.spec_from_file_location(file_name, HERE / file_name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return len(getattr(module, attr))


def test_safety_exception_list_stays_under_cap():
    count = _count("test_safety_separation.py", "KNOWN_SAFETY_VIOLATIONS")
    assert count <= SAFETY_CAP, (
        f"KNOWN_SAFETY_VIOLATIONS {count} > cap {SAFETY_CAP}. 상향은 리드 사전 승인 후 "
        "이 파일의 SAFETY_CAP과 team-guide §5.1을 함께 고친다(패널 보고서 2026-11-04 쟁점 C)."
    )


def test_fleet_ledger_writer_list_stays_under_cap():
    count = _count("test_fleet_ledger_writers.py", "KNOWN_WRITERS")
    assert count <= WRITER_CAP, (
        f"KNOWN_WRITERS {count} > cap {WRITER_CAP}. 상향은 리드 사전 승인 후 "
        "이 파일의 WRITER_CAP과 team-guide §5.1을 함께 고친다(패널 보고서 2026-11-04 쟁점 C)."
    )
