"""Run a finite or live match: arm, tick, always estop."""

from __future__ import annotations

import time

from games.game.state import MatchState
from games.host.loop import MatchHost

HOST_PERIOD_S = 0.05  # 20 Hz (D-102)


def run_match(
    host: MatchHost,
    ticks: int | None = 1,
    *,
    period_s: float = 0.0,
    halt_check=None,
) -> list[MatchState]:
    states: list[MatchState] = []
    try:
        host.arm()
        count = 0
        while ticks is None or count < ticks:
            states.append(host.tick())
            count += 1
            if halt_check is not None and halt_check():
                break
            if period_s > 0:
                time.sleep(period_s)
        return states
    except KeyboardInterrupt:
        return states
    finally:
        host._estop_all()


def space_pressed() -> bool:
    try:
        import msvcrt

        if not msvcrt.kbhit():
            return False
        key = msvcrt.getch()
        return key in (b" ", b"\x03")
    except ImportError:
        import io
        import select
        import sys

        # A stdin without a file descriptor (pytest capture, a pipe closed early) has no key to read.
        try:
            if not select.select([sys.stdin], [], [], 0)[0]:
                return False
        except (io.UnsupportedOperation, OSError, ValueError):
            return False
        return sys.stdin.read(1) == " "
