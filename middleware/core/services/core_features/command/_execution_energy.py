"""CORE-owned energy publication; all mutations under modes -> ledger.

Final predicates read cached immutable facts only. The adapter serializes raw
ingestion, releases source locks, then publishes here under the writer boundary.
"""
from dataclasses import dataclass
import math

from core_features.command._execution_budget import Budget
from core_features.power.execution_energy import PackEnergySource, EnergyReceipt, covers


@dataclass(frozen=True)
class _State:
    latest: object = None
    retained: tuple = ()
    pending: object = None
    closed: bool = False


class EnergyContext:
    def __init__(self, source, clock):
        if type(source) is not PackEnergySource or source._clock is not clock:
            raise ValueError('exact original source required')
        self.source, self.profile = source, source._profile
        self.clock = clock
        self._state = _State()

    def peek(self):
        return self._state.latest

    def begin(self, token):
        state = self._state
        if (state.closed or state.pending is not None or self.source._profile is not self.profile
                or self.source._clock is not self.clock):
            return False
        self._state = _State(state.latest, state.retained, token, False)
        return True

    def admission_open(self):
        return self._state.pending is None and not self._state.closed

    def _covers(self, sample, budget, now):
        if (type(budget) is not Budget or budget._limits.revision != self.profile.revision
                or budget._limits.whole_load_w != self.profile.whole_load_w):
            return False
        end = math.nextafter(budget._start + budget._duration, math.inf)
        return covers(sample, self.profile, end_mono=end, now=now)

    def valid(self, sample, budget, now):
        state = self._state
        return (not state.closed and self.source._profile is self.profile and self.source._clock is self.clock
                and any(sample is value for value in state.retained)
                and self._covers(sample, budget, now)
                and self._covers(state.latest, budget, now))

    def finish(self, token, sample, *, now, parent, fence):
        """Latch exact-parent fault BEFORE replacing facts or opening admission."""
        state = self._state
        if token is not state.pending:
            return False
        if parent is not fence._ledger._current:
            self._state = _State(state.latest, state.retained, None, state.closed)
            return False
        scope = (type(sample) is EnergyReceipt and sample.profile is self.profile
                 and self.source._profile is self.profile and self.source._clock is self.clock and now is not None
                 and sample.validated_mono <= now < sample.valid_until_mono)
        retained = tuple(value for value in state.retained
                         if now is not None and value.valid_until_mono > now)
        closed = state.closed
        if scope and not any(sample is value for value in retained):
            if len(retained) >= 8:
                closed, scope = True, False
            else:
                retained += (sample,)
        good = scope and not closed
        if parent is not None and (not good or not self._covers(sample, parent.budget, now)):
            fence.request_stop(parent)
            fence._ledger._remaining(parent, now=now)
        self._state = _State(sample if good else None, retained, None, closed)
        return good
