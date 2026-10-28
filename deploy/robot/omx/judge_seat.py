#!/usr/bin/env python3
"""The decision model's seat between chunks: measurement decides first, the model picks among what is left.

2026-10-25 offline evaluation (qwen3-vl:8b on 30 recorded arm S steps): the model matched the measured
rule 6/30 with numbers, 1/30 from images alone, and chose grasp with no box in view. So fine wrist
correction stays with grasp_servo, and this seat only chooses the next step (proceed, retry, park,
abort) and explains failures. Measured facts veto: a runner fault forces park, a missing box forces
abort, and proceed is refused when the next chunk's precondition is not measured (aligned before a
grasp, holding before a lift). The model never sees a choice the measurement already ruled out.

The backend is any callable(prompt, images_b64, schema) -> dict. `ollama()` talks to an Ollama
/api/chat (loopback on the AI PC, or through an SSH tunnel); a Fleet route needs an ADR first.
"""
from __future__ import annotations

import json
import time
import urllib.request

DECISIONS = ("proceed", "retry", "park", "abort")
PRECONDITION = {"grasp": "aligned", "lift": "holding"}  # next chunk kind -> measured fact it needs


def measured(facts: dict):
    """(forced decision or None, decisions the measurement forbids)."""
    if facts.get("fault"):
        return "park", set()
    if not facts.get("box_found"):
        return "abort", set()
    need = PRECONDITION.get(facts.get("next"))
    return None, ({"proceed"} if need and not facts.get(need) else set())


def ollama(url="http://127.0.0.1:11434", model="qwen3-vl:8b-instruct", timeout=90):
    def ask(prompt, images, schema):
        body = {"model": model, "stream": False, "format": schema, "options": {"temperature": 0, "seed": 42},
                "messages": [{"role": "user", "content": prompt, "images": list(images)}]}
        request = urllib.request.Request(f"{url}/api/chat", json.dumps(body).encode(),
                                         {"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            return json.loads(json.loads(reply.read())["message"]["content"])
    return ask


class Seat:
    def __init__(self, backend, log=None):
        self.backend, self.log = backend, log or (lambda row: None)

    def decide(self, facts: dict, images=()) -> dict:
        forced, forbidden = measured(facts)
        if forced:
            row = {"decision": forced, "by": "measurement", "reason": "fault" if facts.get("fault") else "box not seen"}
        else:
            allowed = [d for d in DECISIONS if d not in forbidden]
            schema = {"type": "object", "required": ["decision", "reason"], "additionalProperties": False,
                      "properties": {"decision": {"type": "string", "enum": allowed}, "reason": {"type": "string"}}}
            started = time.time()
            try:
                reply = self.backend(prompt(facts, allowed), images, schema)
            except Exception as error:  # timeout, HTTP or broken JSON: no answer is an abort, never a retry
                reply = {"decision": f"no reply ({type(error).__name__})"}
            if not isinstance(reply, dict):
                reply = {"decision": f"non-object reply ({type(reply).__name__})"}
            if reply.get("decision") not in allowed:  # the schema is advice to the model, not a guarantee
                row = {"decision": "abort", "by": "veto", "reason": f"model chose {reply.get('decision')!r}"}
            else:
                row = {"decision": reply["decision"], "by": "model", "reason": str(reply.get("reason", ""))[:300]}
            row["latency_s"] = round(time.time() - started, 1)
        row |= {"facts": facts, "t": round(time.time(), 3)}
        self.log(row)
        return row


def prompt(facts, allowed):
    return ("You decide the next step of a robot arm moving a box between taught chunks. "
            f"Measured now: {json.dumps(facts)}. "
            "proceed = run the next taught chunk; retry = redo the last correction and chunk; "
            "park = return home slowly; abort = stop and ask a person. "
            f"Allowed now: {allowed}. Images, if any: wrist camera then top camera. "
            "Explain in one sentence what you see that supports the choice. Reply with JSON only.")
