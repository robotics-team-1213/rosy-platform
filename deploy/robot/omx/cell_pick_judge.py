#!/usr/bin/env python3
"""A decision model looks at the candidates the measurement left and says which one to pick (2026-10-29).

Measurement first: only candidates that matched the catalogue, have a finger gap and a plan reach the model, so it
can never choose what the checks refused. It sees the top frame with each candidate's outline numbered and answers
one number or -1 ("none of them is a single green container lying flat"). Its pick goes first; -1 stops the attempt
(the model may only add a veto); no answer, a timeout or a number out of range keeps the rule's order. Typical use:
pieces split from touching boxes, a box that may be tilted, a fragment that matched by size.

The backend is judge_seat.ollama(**config["decision_model"]) or any callable(prompt, images_b64, schema) -> dict.
"""
from __future__ import annotations

import base64

SCHEMA = {"type": "object", "properties": {"choice": {"type": "integer"}, "reason": {"type": "string"}},
          "required": ["choice", "reason"]}


def picture(img, usable: list) -> str:
    """The top frame with each candidate's outline and number, as base64 JPEG."""
    import cv2
    import numpy as np

    out = img.copy()
    for i, u in enumerate(usable):
        hull = u["object"].get("hull_px")
        if hull:
            pts = np.asarray(hull, np.int32)
            cv2.polylines(out, [pts], True, (0, 0, 255), 2)
            x, y = pts.mean(axis=0).astype(int)
            cv2.putText(out, str(i), (int(x) - 6, int(y) + 6), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    return base64.b64encode(cv2.imencode(".jpg", out)[1].tobytes()).decode()


def ask(backend, img, usable: list) -> dict:
    """{'order': indexes, 'choice', 'reason', 'by'}: the model's pick first, or the rule order when it cannot help."""
    rule = {"order": list(range(len(usable))), "choice": 0 if usable else None, "by": "rule"}
    if backend is None or len(usable) < 1:
        return {**rule, "reason": "no decision model"}
    facts = [{"n": i, "object": u["object"].get("object"), "size_mm": [round(u["object"]["length_mm"]), round(u["object"]["width_mm"])],
              "split_from": u["object"].get("split_from")} for i, u in enumerate(usable)]
    prompt = ("Top view of a robot cell. The numbered red outlines are candidates the measurements accepted for a "
              f"top-down grasp: {facts}. Which number is one single green shipping container lying flat, not "
              "touching or leaning on another object? Answer its number, or -1 if none of them is.")
    try:
        answer = backend(prompt, [picture(img, usable)], SCHEMA)
        choice = int(answer["choice"])
    except Exception as exc:  # the model is advice: when it cannot answer, the rule stands
        return {**rule, "reason": f"model unavailable: {str(exc)[:80]}"}
    if choice == -1:
        return {"order": [], "choice": -1, "reason": str(answer.get("reason", ""))[:200], "by": "model"}
    if not 0 <= choice < len(usable):
        return {**rule, "reason": f"model answered {choice}, out of range"}
    return {"order": [choice] + [i for i in range(len(usable)) if i != choice], "choice": choice,
            "reason": str(answer.get("reason", ""))[:200], "by": "model"}
