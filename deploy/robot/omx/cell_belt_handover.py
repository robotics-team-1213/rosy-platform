"""Evidence-gated, one-box belt handover ledger."""

import time


class Hold(Exception):
    """A refused handover transition."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class BeltHandover:
    """The belt as a one-box buffer. One token; every move needs evidence."""

    def __init__(self, missing_after_s: float, clock=time.monotonic):
        self.missing_after_s = missing_after_s
        self.clock = clock
        self.state = "empty"
        self.generation = 0
        self.cargo = None
        self.events: list[dict] = []
        self._placed_at = None

    def _record(self, event: str, reason: str = "", **extra) -> None:
        self.events.append({"event": event, "generation": self.generation,
                            "cargo": self.cargo, "t": self.clock(), "reason": reason, **extra})

    def _gate(self, event: str, generation: int, cargo: str | None, state: str) -> bool:
        if generation != self.generation:
            raise Hold("stale_generation")
        if any(entry["event"] == event and entry["generation"] == generation
               and (cargo is None or entry["cargo"] == cargo) for entry in self.events):
            return False
        if cargo is not None and cargo != self.cargo:
            raise Hold("cargo_mismatch")
        if self.state != state:
            raise Hold(f"state_{self.state}")
        return True

    @staticmethod
    def _reading(reading: dict, expected: str) -> None:
        occupancy = reading.get("occupancy")
        if occupancy == expected:
            return
        if occupancy == "unknown":
            raise Hold(f"reading_{reading.get('reason', '')}")
        raise Hold("belt_occupied" if occupancy == "occupied" else "belt_empty")

    def reserve(self, cargo: str, reading: dict) -> int:
        if self.state != "empty":
            raise Hold(f"state_{self.state}")
        self._reading(reading, "empty")
        self.generation += 1
        self.cargo = cargo
        self.state = "reserved"
        self._record("reserve")
        return self.generation

    def placed(self, generation: int, cargo: str) -> None:
        if not self._gate("placed", generation, cargo, "reserved"):
            return
        self.state = "placed"
        self._placed_at = self.clock()
        self._record("placed")

    def arrived(self, generation: int, cargo: str, reading: dict) -> None:
        if not self._gate("arrived", generation, cargo, "placed"):
            return
        self._reading(reading, "occupied")
        self.state = "at_end"
        self._record("arrived")

    def grasped(self, generation: int, cargo: str) -> None:
        if not self._gate("grasped", generation, cargo, "at_end"):
            return
        self.state = "picked"
        self._record("grasped")

    def cleared(self, generation: int, reading: dict) -> None:
        if not self._gate("cleared", generation, None, "picked"):
            return
        self._reading(reading, "empty")
        self.state = "empty"
        self._record("cleared")
        self.cargo = None
        self._placed_at = None

    def check(self) -> str:
        if self.state == "placed" and self.clock() - self._placed_at > self.missing_after_s:
            self.state = "missing"
            self._record("missing", "timeout")
        return self.state

    def resolve(self, operator: str, note: str) -> None:
        if self.state != "missing":
            raise Hold(f"state_{self.state}")
        self.state = "empty"
        self._record("resolve", note, operator=operator, note=note)
        self.cargo = None
        self._placed_at = None
