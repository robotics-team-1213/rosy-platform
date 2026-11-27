"""rclpy fixes a logger's severity per call site: one line that picks warning or info crashes the node."""
import re
from pathlib import Path

from control.loc_window import log_by

PICKED = re.compile(r"get_logger\(\)\.\w+\s+if\s.+\selse\s.*get_logger\(\)\.\w+")


def test_no_log_line_picks_its_severity_at_run_time():
    root = Path(__file__).resolve().parents[1]
    hits = [f"{path.relative_to(root)}:{n}" for path in root.rglob("*.py") if "test" not in path.parts
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1) if PICKED.search(line)]
    assert hits == []  # 2026-11-27: this form killed loc_assist_node 58 times in one day on a real Pinky


def test_log_by_calls_each_severity_from_its_own_line():
    class Logger:
        def __init__(self):
            self.calls = []

        def warning(self, message):
            self.calls.append(("warning", message))

        def info(self, message):
            self.calls.append(("info", message))

    logger = Logger()
    log_by(logger, True, "slow")
    log_by(logger, False, "fine")
    assert logger.calls == [("warning", "slow"), ("info", "fine")]
