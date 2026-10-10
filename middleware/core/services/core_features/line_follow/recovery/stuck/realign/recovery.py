"""D-607 8 REALIGN answer and phases on top of the D-407 StuckRecovery machine."""
from __future__ import annotations

from typing import Optional

from core_features.line_follow.recovery.stuck.realign.manoeuvre import Manoeuvre
from core_features.line_follow.recovery.stuck.stuck_recovery import (
    _SOURCE, CROSSWALK, WAITING_CONSOLE, AnswerRefused, StuckAction, StuckRecovery)

REALIGNING = "REALIGNING"
REALIGN_SETTLING = "REALIGN_SETTLING"


class RealignRecovery(StuckRecovery):
    """StuckRecovery plus the REALIGN answer and its two phases. ``starter`` is set by RealignMixin under
    the manager lock right before ``answer``; ``live`` judges each running tick."""

    def __init__(self, events, config, *, live, **kwargs) -> None:
        self._carry: Optional[tuple] = None      # (stuck id, realigns) of the last `recovered` close
        self.starter = None
        self._live = live
        super().__init__(events, config, **kwargs)

    def _clear(self) -> None:
        super()._clear()
        self._move: Optional[Manoeuvre] = None
        self._realigns = 0

    @property
    def realigning(self) -> bool:
        return self._phase in (REALIGNING, REALIGN_SETTLING)

    @property
    def realigns(self) -> int:
        return self._realigns

    def _open(self, inp, ask: bool = True) -> None:
        super()._open(inp, ask)
        if self._carry is not None and self._restuck_of == self._carry[0]:
            self._realigns = self._carry[1]      # the same stuck for the REALIGN limit too
        self._carry = None

    def _close(self, reason: str, now: float) -> None:
        self._carry = (self._id, self._realigns) if reason == "recovered" else None
        super()._close(reason, now)

    def reset(self, reason: str, now: float) -> None:
        super().reset(reason, now)
        self._carry = None

    def _decisions(self) -> tuple:
        on = self._config.stuck_realign_enabled and self._cause != CROSSWALK
        return super()._decisions() + (("REALIGN",) if on else ())

    def answer(self, now: float, stuck_id: str, decision: str, by: str,
               principal_ref: Optional[str] = None, **kwargs) -> str:
        starter, self.starter = self.starter, None
        if decision != "REALIGN":
            if self.realigning and stuck_id == self._id and decision in ("BACK_AND_RETRY", "YIELD"):
                self._answered(stuck_id, decision, by, principal_ref, False, "realign_active")
                raise AnswerRefused("STUCK_DECISION_REFUSED", f"{decision} refused: realign_active")
            outcome = super().answer(now, stuck_id, decision, by, principal_ref, **kwargs)
            if not self.realigning:
                self._move = None                # WAIT, RESUME, MANUAL, ABORT end a running manoeuvre
            return outcome
        if self._id is None or stuck_id != self._id:
            self._answered(stuck_id, decision, by, principal_ref, False, "stuck_id_mismatch")
            raise AnswerRefused("STUCK_ID_MISMATCH", "no open stuck with this id (late or wrong answer)")
        move, why = (None, "realign_kind") if starter is None else starter(self._last_or(now))
        if why is not None:
            self._answered(stuck_id, decision, by, principal_ref, False, why)
            raise AnswerRefused("STUCK_DECISION_REFUSED", f"REALIGN refused: {why}")
        self._answered(stuck_id, decision, by, principal_ref, True, None)
        self._last_answer, self._move, self._phase, self._deadline = decision, move, REALIGNING, None
        self._realigns += 1
        self._events.publish("nav.line_stuck_local_attempt", severity="warning", source=_SOURCE, data={
            "stuck_id": self._id, "attempt": self._attempts, "trigger": "realign",
            "realign_attempt": self._realigns, "realign": move.view()})
        return "realign"

    def step(self, inp) -> StuckAction:
        if not self.realigning or inp.cause == CROSSWALK:
            if self.realigning:                  # D-573 4: the crosswalk stuck takes over, nothing moves
                self._result("aborted", "crosswalk_gate", inp=inp)
                self._phase, self._move = WAITING_CONSOLE, None
            return super().step(inp)
        self._last = inp
        if self._phase == REALIGN_SETTLING:
            if inp.now < self._until:
                return StuckAction("hold")
            if inp.lane_visible and inp.front_clear:
                self._result("recovered", None, lane=True, front=True)
                self._close("recovered", inp.now)
                return StuckAction("resume")
            self._result("still_stuck", None, lane=inp.lane_visible, front=inp.front_clear)
            self._console_only("realign_done", inp.now)
            return StuckAction("hold")
        verdict, out = self._live(inp, self._move)
        if verdict == "move":
            return StuckAction("realign", *out)
        self._move = None
        if verdict == "done":
            self._phase, self._until = REALIGN_SETTLING, inp.now + self._config.recovery_settle_s
            return StuckAction("hold")
        self._result("aborted", out, inp=inp)
        self._console_only("local_aborted", inp.now)
        return StuckAction("hold")
