"""D-525/D-620 signal methods on the existing traffic table; no separate state or writer."""
from typing import Optional

from fleet.traffic import signal_phase
from fleet.routing.execute import arc_id

#: D-525 4 / D-443: a manual green lasts while a named operator's console says it is there this often.
PRESENCE_S = 10.0


class SignalService:
    def _green(self) -> dict[str, frozenset]:
        """Advance every signal and return ``{zone: approaches allowed in}``; a refused plan stays red."""
        now, green = self._signal_clock(), {}
        for signal_id, plan in self._signals.items():
            state = self._phase[signal_id]
            if state.mode == "manual" and now >= self._present_until:  # nobody there: all red, not cycle
                signal_phase.command(plan, state, "all_red", now)
            signal_phase.advance(plan, state, now, self._busy is None or plan.zone in self._busy)
            green[plan.zone] = frozenset() if self._signal_errors.get(signal_id) else signal_phase.green(plan, state)
        return green

    def _signals_ahead(self, robots) -> dict[str, dict]:
        """D-525 rev 3: each localized trip robot's next signalled zone on its route: the signal, the
        approach it enters from, front-to-stop-line metres (negative: already past it) and whether it
        already holds that zone (may enter; the D-517 authority is still what lets it move)."""
        zones = {plan.zone: plan.id for plan in self._signals.values()}
        out = {}
        for robot in robots:
            if robot.d is None or not zones:
                continue
            held = self._state.held.get(robot.id, {})
            for index, span in enumerate(robot.spans):
                if span.unit in zones and span.d1 > robot.d:
                    out[robot.id] = {"signal_id": zones[span.unit], "approach": span.entry,
                                     "distance_m": round(span.d0 - robot.d, 3), "may_enter": index in held}
                    break
        return out

    def signal_ahead(self, robot_id: str) -> Optional[dict]:
        """The next signal on this robot's trip with its approach's countdown (advisory), or None."""
        ahead = self._ahead.get(robot_id)
        if ahead is None:
            return None
        plan = self._signals[ahead["signal_id"]]
        signal = self._signal_row(plan, None)
        row = next((a for a in signal["approaches"] if a["approach"] == ahead["approach"]), {})
        return {"robot_id": robot_id, **ahead, "virtual": True, "advisory": True, "mode": signal["mode"],
                "occupancy": signal["occupancy"], **{k: row.get(k) for k in ("lamp", "left_s", "green_in_s", "exact")}}

    def junction_signal(self, robot_id: str, approach: Optional[str] = None) -> dict:
        """D-620: cached signal advice; never creates or enlarges a movement authority."""
        ahead = self.signal_ahead(robot_id)
        if ahead is not None:
            return dict(lamp='green' if ahead['lamp'] == 'green' else 'red',
                        may_enter=ahead['lamp'] == 'green' and ahead['may_enter'] is True,
                        reason='trip_signal')
        matches = [p for p in self._signals.values() if approach in dict(p.phases)]
        if len(matches) != 1:
            return dict(lamp='unknown', may_enter=False, reason='signal_unmapped')
        row = self._signal_row(matches[0], None)
        lamp = next(a['lamp'] for a in row['approaches'] if a['approach'] == approach)
        holder = row['occupancy']['holder']
        clear = not row['zone_busy'] or holder == robot_id
        return dict(lamp='green' if lamp == 'green' else 'red',
                    may_enter=lamp == 'green' and clear and not row['errors'], reason='approach_signal')

    def signal_command(self, signal_id: str, verb: str, approach: Optional[str] = None) -> dict:
        """Operator verb (D-525 4): ``occupancy`` (rev 6, the default), ``cycle``, ``hold``, ``all_red``,
        ``demand`` (rev 4) or ``set_aspect`` (green for one approach while the operator is present).
        KeyError: unknown signal; ValueError: bad verb or approach; PermissionError: a manual green
        without presence."""
        plan = self._signals[signal_id]
        now = self._signal_clock()
        if verb == "set_aspect":
            if approach not in {a for a, _green in plan.phases}:
                raise ValueError(approach)
            if now >= self._present_until:
                raise PermissionError("presence")
        elif verb not in signal_phase.VERBS:
            raise ValueError(verb)
        signal_phase.command(plan, self._phase[signal_id], verb, now, approach)
        return self._signal_row(plan, None)

    def signal_demand(self, signal_id: str, approach: Optional[str], ttl_s: float, reason: str = ""):
        """D-525 rev 4: a controller's request (``signal_phase.demand``); (row, new demand)."""
        plan = self._signals[signal_id]
        fresh = signal_phase.demand(plan, self._phase[signal_id], approach, self._signal_clock(), ttl_s, reason)
        return self._signal_row(plan, None), fresh

    def signal_presence(self) -> dict:
        """A named operator's console is open (D-525 4): a manual green may stay for PRESENCE_S."""
        self._present_until = self._signal_clock() + PRESENCE_S
        return {"present": True, "for_s": PRESENCE_S}

    def signals_all_red(self) -> None:
        """E-stop: every virtual signal all red at once (D-525 4)."""
        now = self._signal_clock()
        for signal_id, plan in self._signals.items():
            signal_phase.command(plan, self._phase[signal_id], "all_red", now)

    def signal_refusal(self, segments, authority_mode: str) -> Optional[tuple[str, dict]]:
        """D-525 1/6 trip start check: no route starting inside a signalled zone, and only a robot that
        takes CORE authority may cross one (junction hold-back alone does not stop it at red)."""
        if not self._signals or not segments:
            return None
        layout = self._layout_for(self._store.active())
        if layout is None:
            return None
        zones = {plan.zone: signal_id for signal_id, plan in self._signals.items()}
        spans = layout.route(self._store.active()[2], [arc_id(seg) for seg in segments])
        if spans and spans[0].unit in zones:
            return "TRIP_SIGNAL_START_IN_ZONE", {"signal_id": zones[spans[0].unit]}
        crossed = sorted({zones[s.unit] for s in spans if s.unit in zones})
        if crossed and authority_mode != "core":
            return "TRIP_SIGNAL_NEEDS_AUTHORITY", {"signals": crossed}
        return None

    def _signal_row(self, plan, graph) -> dict:
        state, now = self._phase[plan.id], self._signal_clock()
        held = now - state.since
        left = {"green": (plan.phases[state.phase][1] - held) if state.mode == "cycle" else None,
                "yellow": plan.yellow_s - held, "all_red": plan.all_red_s - held}[state.aspect]
        approaches = []
        errors = self._signal_errors.get(plan.id) or []
        busy = self._busy is None or plan.zone in self._busy
        occupancy = self._occupancy.get(plan.zone, signal_phase.UNKNOWN)
        ahead = signal_phase.forecast(plan, state, now, busy, occupancy)
        aspect = state.aspect
        if state.mode == "occupancy":  # rev 6: a summary of the derived lamps; no time is known
            aspect, left = {"free": "green", "reserved": "yellow"}.get(occupancy[0], "all_red"), None
        for approach, green_s in plan.phases:
            lamp = "red" if errors else ahead[approach]["lamp"]  # a refused plan's zone is never granted
            row = {"approach": approach, "lamp": lamp, "green_s": green_s,
                   **({"left_s": None, "green_in_s": None, "exact": False} if errors else
                      {k: ahead[approach][k] for k in ("left_s", "green_in_s", "exact")})}
            if graph is not None and approach in graph.arcs:  # the stop line: where the approach meets the zone
                arc = graph.arcs[approach]
                x, y, yaw = arc.point_at(arc.length_m)
                row["stop_line"] = {"x": round(x, 3), "y": round(y, 3), "yaw": round(yaw, 4)}
            approaches.append(row)
        manual = plan.phases[state.manual][0] if state.mode == "manual" and state.manual is not None else None
        return {"signal_id": plan.id, "zone": plan.zone, "virtual": True, "mode": state.mode, "manual": manual,
                "demands": [{"approach": a, "age_s": round(now - state.demands[a][0], 1), "reason": state.demands[a][2]}
                            for a in signal_phase.queue(plan, state, now)] if state.mode == "demand" else [],
                "controller_age_s": round(now - state.heard, 1) if state.mode == "demand" else None,
                "aspect": "all_red" if errors else aspect,
                "occupancy": dict(zip(("state", "holder", "approach"), occupancy)),
                "left_s": None if left is None or errors else round(max(0.0, left), 1),
                "zone_busy": busy,
                "approaches": approaches, "errors": errors, "alert": signal_phase.alert(plan, state, now)}

    def _signal_view(self, graph) -> list[dict]:
        return [self._signal_row(plan, graph) for _id, plan in sorted(self._signals.items())]
