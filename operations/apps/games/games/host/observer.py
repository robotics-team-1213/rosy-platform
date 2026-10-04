"""Observation source. OpenCV stays in a later adapter, not here."""

from __future__ import annotations

from typing import Protocol

from games.game import Observation


class Observer(Protocol):
    def observe(self) -> Observation: ...
