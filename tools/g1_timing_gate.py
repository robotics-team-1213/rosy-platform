"""Observe original G1 collection/results; a timing skip never constitutes evidence."""
import os
from collections import Counter
from pathlib import Path

import pytest

from tools.harness.affected_exclusive import TARGET


class TimingGate:
    def __init__(self, target=None):
        self.target = Path(target or Path(__file__).resolve().parents[1] / TARGET).resolve()
        self.expected, self.passed, self.collected = Counter(), Counter(), Counter()
        self.skipped = 0
        self.clean = False

    def pytest_configure(self, config):
        if os.environ.get('ROSY_JOB_ALONE') != '1':
            raise pytest.UsageError('G1 timing requires host-exclusive admission')
        if len(config.args) != 1 or '::' in str(config.args[0]) or Path(config.args[0]).resolve() != self.target:
            raise pytest.UsageError('G1 timing requires one explicit whole-file argument')

    def pytest_collectreport(self, report):
        for item in getattr(report, 'result', ()) or ():
            if isinstance(item, pytest.Item) and Path(item.path).resolve() == self.target:
                self.expected[item.nodeid] += 1

    def pytest_runtest_logreport(self, report):
        self.skipped += int(report.skipped)
        if report.when == 'call' and report.passed and not getattr(report, 'wasxfail', False):
            self.passed[report.nodeid] += 1

    def pytest_sessionfinish(self, session, exitstatus):
        self.collected = Counter(item.nodeid for item in session.items)
        self.clean = bool(self.expected) and exitstatus == 0 and not self.skipped and (
            self.expected == self.collected == self.passed and all(n == 1 for n in self.expected.values())
            and all(Path(item.path).resolve() == self.target for item in session.items))
        if not self.clean and exitstatus in (0, pytest.ExitCode.NO_TESTS_COLLECTED):
            session.exitstatus = pytest.ExitCode.TESTS_FAILED

    def pytest_terminal_summary(self, terminalreporter):
        terminalreporter.write_line(f'[g1-timing-gate] expected={sum(self.expected.values())} '
            f'collected={sum(self.collected.values())} passed={sum(self.passed.values())} '
            f'skipped={self.skipped} clean={int(self.clean)}')


def pytest_configure(config):
    config.pluginmanager.register(TimingGate(), 'g1-timing-results')
