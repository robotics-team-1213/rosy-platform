"""D-971: the AI PC explains an OMX arm incident from its frames and measured facts. Explanation only.

Pull path (D-610): ``GET /api/fleet/workcell-observations/arm-incidents/unexplained`` as ``ai_observer`` returns open
incidents without an explanation; the local Ollama vision model is asked what it sees and the likely physical cause;
the reply goes to ``POST .../arms/{source_id}/incidents/{incident_id}/explanation``. Fleet stores and shows it. The
prompt forbids motions and the reply has two text fields only, so nothing here can become an action. A model that is
not loaded, a timeout or a bad answer leaves the incident unexplained and is logged; Fleet and the hold are unaffected.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error

_LOG = logging.getLogger("rosy_situation.arm_incidents")
TIMEOUT_S = 90.0                 # no one waits on this: the hold already stands
RETRY_S = 300.0                  # an incident the model could not explain is tried again after this
BASE = "/api/fleet/workcell-observations"
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["seen", "suspected_cause"],
          "properties": {"seen": {"type": "string", "minLength": 1, "maxLength": 380},
                         "suspected_cause": {"type": "string", "minLength": 1, "maxLength": 380}}}
PROMPT = ("An OMX robot arm session ended with these measured facts (JSON):\n{facts}\n"
          "The images are the top and side cameras at the moment of the fault, in this order: {roles}. "
          "Say what you see near the arm and its jaws (objects caught, leaning or wedged) and the most likely "
          "physical cause of the fault. Describe only what the pictures show; if they show nothing useful say so. "
          "Do not suggest motions, commands or recovery steps. Answer with one JSON object: "
          '{{"seen": one or two short sentences, "suspected_cause": one short sentence}}.')


def _clean(value) -> str:
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", value).strip() if isinstance(value, str) else ""
    return text[:380]


class ArmIncidentExplainer:
    def __init__(self, fleet, vlm, *, clock) -> None:
        self.fleet, self.vlm, self.clock, self._tried = fleet, vlm, clock, {}

    def explain(self, incident: dict):
        """The explanation body for Fleet, or None (no frames, model not loaded, bad answer)."""
        frames = incident.get("frames") or []
        profile = self.vlm.profile() if frames else None
        if profile is None:
            return None
        facts = json.dumps({k: incident.get(k) for k in ("facts", "decision", "recovery")}, default=str,
                           ensure_ascii=False)[:6000]
        reply = self.vlm._post(f"{self.vlm.url}/api/chat", {
            "model": self.vlm.model, "stream": False, "think": False, "format": SCHEMA, "options": self.vlm.options,
            "messages": [{"role": "user", "images": [f["jpeg_b64"] for f in frames],
                          "content": PROMPT.format(facts=facts, roles=", ".join(f["role"] for f in frames))}]},
            TIMEOUT_S)
        answer = json.loads((reply.get("message") or {}).get("content") or "")
        if not isinstance(answer, dict) or set(answer) != {"seen", "suspected_cause"}:
            return None
        seen, cause = _clean(answer["seen"]), _clean(answer["suspected_cause"])
        return {"seen": seen, "suspected_cause": cause, "model": profile} if seen and cause else None

    def cycle(self, available=lambda: True) -> int:
        """Explain at most one open incident; returns how many explanations were posted."""
        try:
            listing = self.fleet.call(f"{BASE}/arm-incidents/unexplained")
        except urllib.error.HTTPError as exc:
            if exc.code in (404, 503):      # this Fleet has no workcell observations
                return 0
            raise
        now = self.clock()
        for incident in listing.get("incidents") or []:
            key = incident.get("incident_id")
            if now - self._tried.get(key, float("-inf")) < RETRY_S:
                continue
            self._tried[key] = now
            body = self.explain(incident)
            if body is None or not available():
                _LOG.info("arm incident %s not explained", str(key)[:8])
                return 0
            self.fleet.call(f"{BASE}/arms/{incident['source_id']}/incidents/{key}/explanation", body)
            return 1
        self._tried = {k: t for k, t in self._tried.items() if now - t < RETRY_S}
        return 0
