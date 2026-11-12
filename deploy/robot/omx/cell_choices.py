"""Competing values for one cell, each with where it came from and how it did for real (D-872).

A taught value (a leader demonstration, a taught reference), a measured one (what the arm or a camera
showed) and a simulated one are candidates side by side; none wins by default. Each real try adds an
outcome, and the value used is the one that has done best for that purpose, with the others kept as
fallbacks. Names carry the purpose: the taught top reference belongs to the taught replay, the
measured start pixel to the top-down plan (2026-10-25: both right, each for its own plan).

  rosy.omx-cell-choices.v1: {"schema", "values": {"<name>": [{"value", "source", "ok", "tries", "last"}]}}
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "rosy.omx-cell-choices.v1"


class Choices:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {"schema": SCHEMA, "values": {}}
        if self.data.get("schema") != SCHEMA:
            raise SystemExit(f"{path}: not a {SCHEMA} file")

    def _find(self, name, value):
        return next((c for c in self.data["values"].get(name, []) if c["value"] == value), None)

    def offer(self, name: str, value, source: str):
        """Add a candidate once; offering it again keeps its record."""
        if self._find(name, value) is None:
            self.data["values"].setdefault(name, []).append(
                {"value": value, "source": source, "ok": 0, "tries": 0, "last": None})

    def offer_contextual(self, name: str, value: Any, source: str):
        """Offer a candidate with contextual bandit statistics initialized."""
        self.offer(name, value, source)
        c = self._find(name, value)
        c.setdefault("reward_sum", 0.0)
        c.setdefault("history", [])

    def outcome(self, name: str, value, ok: bool, note: str | None = None):
        candidate = self._find(name, value)
        if candidate is None:
            raise KeyError(f"{name}: {value!r} was never offered")
        candidate["tries"] += 1
        candidate["ok"] += bool(ok)
        candidate["last"] = {"ok": bool(ok), "note": note, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}

    def outcome_contextual(
        self,
        name: str,
        value: Any,
        ok: bool,
        reward: float | None = None,
        features: list[float] | None = None,
        propensity: float = 1.0,
        note: str | None = None,
    ):
        """Record a contextual outcome with scalar reward, feature context, and action propensity."""
        if self._find(name, value) is None:
            self.offer_contextual(name, value, "contextual")
        self.outcome(name, value, ok, note=note)
        candidate = self._find(name, value)
        r = (1.0 if ok else -0.2) if reward is None else float(reward)
        candidate["reward_sum"] = float(candidate.get("reward_sum", 0.0)) + r
        hist = candidate.setdefault("history", [])
        hist.append({
            "ok": bool(ok),
            "reward": r,
            "propensity": float(max(propensity, 1e-4)),
            "features": list(features) if features is not None else None,
            "note": note,
        })
        if len(hist) > 64:
            del hist[:-64]

    def best(self, name: str, default=None):
        """The candidate with the best record: (ok + 1) / (tries + 2), so one success beats an untried value
        and an untried value beats one failure; ties go to the one tried more."""
        candidates = self.data["values"].get(name, [])
        if not candidates:
            return default
        return max(candidates, key=lambda c: ((c["ok"] + 1) / (c["tries"] + 2), c["tries"]))["value"]

    def best_contextual(
        self,
        name: str,
        allowed: list[Any],
        features: list[float] | None = None,
        alpha: float = 0.25,
    ) -> dict[str, Any]:
        """Select the best candidate among safety-gated `allowed` actions using empirical reward + UCB."""
        if not allowed:
            return {"value": None, "propensity": 0.0, "scores": {}}
        for v in allowed:
            if self._find(name, v) is None:
                self.offer_contextual(name, v, "allowed")
        total_tries = sum(max(0, (self._find(name, v) or {}).get("tries", 0)) for v in allowed) + 1
        scores: dict[str, float] = {}
        best_val = allowed[0]
        best_score = -1e18
        for idx, v in enumerate(allowed):
            c = self._find(name, v) or {"ok": 0, "tries": 0, "reward_sum": 0.0, "history": []}
            n = int(c.get("tries", 0))
            prior_mean = (c.get("ok", 0) + 1.0) / (n + 2.0)
            emp_reward = (float(c.get("reward_sum", 0.0)) + prior_mean) / (n + 1.0)
            ctx_bonus = 0.0
            if features and c.get("history"):
                sims = []
                f_norm = math.sqrt(sum(x * x for x in features)) or 1.0
                for h in c["history"]:
                    hf = h.get("features")
                    if hf and len(hf) == len(features):
                        hf_norm = math.sqrt(sum(x * x for x in hf)) or 1.0
                        cos = sum(a * b for a, b in zip(features, hf)) / (f_norm * hf_norm)
                        sims.append(cos * float(h.get("reward", 0.0)))
                if sims:
                    ctx_bonus = 0.15 * (sum(sims) / len(sims))
            ucb = float(alpha) * math.sqrt(math.log(total_tries + 1.0) / (n + 1.0))
            score = emp_reward + ctx_bonus + ucb - 1e-6 * idx
            scores[str(v)] = round(score, 6)
            if score > best_score:
                best_score = score
                best_val = v
        max_s = max(scores.values())
        exps = {k: math.exp(min(20.0, (s - max_s) * 4.0)) for k, s in scores.items()}
        z = sum(exps.values()) or 1.0
        propensity = round(exps[str(best_val)] / z, 6)
        return {"value": best_val, "propensity": propensity, "scores": scores}

    def ranked(self, name: str, values: list) -> list:
        """The values by the same record as best(); equal records keep the given order, untried ones included."""
        def record(value):
            c = self._find(name, value) or {"ok": 0, "tries": 0}
            return -(c["ok"] + 1) / (c["tries"] + 2)
        return sorted(values, key=record)

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1))
        tmp.replace(self.path)
