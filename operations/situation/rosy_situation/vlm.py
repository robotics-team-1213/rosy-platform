"""D-610 6: the AI PC judges one Fleet case with Qwen3-VL through the local Ollama; analyzers stay the fallback.

A case (``GET /api/fleet/ai/case/{problem_id}``) carries the problem, its context and two views: the Rosy Cam
crop around the robot and one robot front-camera frame (JPEG base64, frame id, captured_at). The model is
called on ``127.0.0.1`` only (the service runs on the AI PC, so the site PC -> AI PC network does not matter),
with a 6 s timeout. Its answer must be one word of the case kind's table (D-610 4) and cite both views; anything
else, a timeout or no model is ``None`` and the caller keeps the deterministic analyzer's proposal (D-610 5 end:
that one still passes every D-577 gate). Frames are never written to disk; the proposal cites frame ids, ages and
sha256 only.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import urllib.request
from typing import Callable, Optional

OLLAMA_URL = "http://127.0.0.1:11434"
MODEL = "qwen3-vl:8b-instruct"           # D-492 model; the digest is pinned in the profile id
PROMPT_ID = "d610-v1"
TIMEOUT_S = 6.0
TTL_S = 6.0
VIEWS = ("rosy_cam", "front")
#: D-610 4: the words the model may choose per problem kind (existing CORE / Fleet commands only).
WORDS = {"stuck": ("WAIT", "BACK_AND_RETRY", "RESUME", "ABORT", "YIELD", "REALIGN", "MANUAL"),
         "stalled": ("WAIT", "LINE_OFF", "STOP"),
         "pose_lost": ("WAIT", "IDENTIFY", "STOP"),
         "deadlock": ("REPLAN", "WAIT"),
         "trip_failed": ("STOP", "CANCEL")}
_LOG = logging.getLogger("rosy_situation.vlm")

PROMPT = """You decide what a small lane-following robot should do next. Two pictures follow: first the ceiling
camera crop around the robot, then the robot's own front camera. The robot's local safety (body stop, watchdog,
E-stop) and its own sensor re-check stay in force whatever you choose. Answer with one JSON object only:
{{"decision": one of {words}, "reason": short snake_case, "confidence": 0..1, "seen": what in the pictures decided it}}.
Prefer WAIT when the pictures do not show the way clear. Problem and context:
{context}"""


def _post(url: str, body: dict, timeout: float) -> dict:
    request = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


class Vlm:
    def __init__(self, url: str = OLLAMA_URL, model: str = MODEL, *,
                 post: Callable[[str, dict, float], dict] = _post) -> None:
        self.url, self.model, self._post = url.rstrip("/"), model, post
        self._profile: Optional[str] = None

    def profile(self) -> Optional[str]:
        """``<model>@<digest12>:<prompt>`` once Ollama reports the model, else None (not loaded)."""
        if self._profile is None:
            try:
                info = self._post(f"{self.url}/api/show", {"model": self.model}, TIMEOUT_S)
            except (OSError, ValueError) as exc:
                _LOG.info("vlm not available: %s", exc)
                return None
            digest = str(info.get("digest") or (info.get("details") or {}).get("digest") or "")[:12]
            self._profile = f"{self.model}@{digest or 'unknown'}:{PROMPT_ID}"
        return self._profile

    def judge(self, case: dict, now: float) -> Optional[dict]:
        """One proposal for this case, or None (the analyzer's proposal stands)."""
        words = WORDS.get(case.get("kind"), ())
        views = case.get("views") or {}
        if not words or any(not (views.get(v) or {}).get("jpeg_b64") for v in VIEWS):
            return None                               # D-610 5: both views or no VLM judgement
        profile = self.profile()
        if profile is None:
            return None
        context = json.dumps({k: case.get(k) for k in ("kind", "robot_id", "problem_id", "context")},
                             separators=(",", ":"), default=str)[:6000]
        images = [views[v]["jpeg_b64"] for v in VIEWS]
        try:
            reply = self._post(f"{self.url}/api/chat", {
                "model": self.model, "stream": False, "format": "json", "options": {"temperature": 0},
                "messages": [{"role": "user", "content": PROMPT.format(words=list(words), context=context),
                              "images": images}]}, TIMEOUT_S)
            answer = json.loads((reply.get("message") or {}).get("content") or "")
            decision = str(answer["decision"]).upper()
            confidence = min(1.0, max(0.0, float(answer.get("confidence", 0.0))))
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            _LOG.warning("vlm judgement dropped: %s", exc)
            return None
        if decision not in words:
            _LOG.warning("vlm word %r not allowed for %s", decision, case.get("kind"))
            return None
        reason = "".join(c if c.isalnum() or c in "_:.-" else "_" for c in str(answer.get("reason") or "vlm").lower())
        evidence = {"views": {v: {"frame_id": views[v].get("frame_id"), "captured_at": views[v].get("captured_at"),
                                  "age_s": round(now - float(views[v].get("captured_at") or 0.0), 3),
                                  "sha256": hashlib.sha256(base64.b64decode(views[v]["jpeg_b64"])).hexdigest()}
                            for v in VIEWS},
                    "map_pose": (case.get("context") or {}).get("map_pose"),
                    "seen": str(answer.get("seen") or "")[:200]}
        return {"robot_id": case.get("robot_id"), "stuck_id": case.get("stuck_id") or case.get("problem_id"),
                "decision": decision, "reason": reason[:64] or "vlm", "confidence": confidence,
                "evidence": evidence, "source": f"vlm:{profile}", "observed_at": now, "ttl_s": TTL_S}
