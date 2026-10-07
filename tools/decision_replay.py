"""Offline, loopback-only choice replay for Jev-compatible decision servers."""

import argparse
import json
import math
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def replay(data: Path, endpoint: str, model: str, timeout: float) -> dict:
    url = urllib.parse.urlsplit(endpoint)
    if (url.scheme != "http" or url.hostname not in ("localhost", "127.0.0.1", "::1")
            or url.path != "/v1/systemone" or url.query or url.fragment):
        raise ValueError("endpoint must be a loopback http://.../v1/systemone URL")
    if timeout <= 0:
        raise ValueError("timeout must be positive")

    rows = []
    seen = set()
    with data.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            case = json.loads(line)
            case_id = case["id"]
            criteria = case["criteria"]
            if (not isinstance(case_id, str) or not case_id or case_id in seen
                    or not isinstance(criteria, dict) or len(criteria) < 2
                    or any(not isinstance(k, str) or not k or not isinstance(v, str)
                           for k, v in criteria.items())
                    or case["expected"] not in criteria
                    or not isinstance(case["instructions"], str)
                    or not case["instructions"]):
                raise ValueError(f"invalid case at line {line_number}")
            seen.add(case_id)
            body = {"state": case["state"], "model": model, "questions": {
                "decision": {"type": "choice", "instructions": case["instructions"],
                             "criteria": criteria}}}
            req = urllib.request.Request(endpoint, json.dumps(body).encode("utf-8"),
                                         {"Content-Type": "application/json"}, method="POST")
            started = time.perf_counter()
            predicted = None
            error = None
            try:
                with urllib.request.urlopen(req, timeout=timeout) as response:
                    answer = json.load(response)["answers"]["decision"]
                    predicted = answer["choice"]
                    if not isinstance(predicted, str) or predicted not in criteria:
                        predicted = None
                        raise ValueError("choice outside criteria")
            except (urllib.error.URLError, TimeoutError, ValueError, KeyError,
                    TypeError, json.JSONDecodeError) as exc:
                error = type(exc).__name__
            rows.append({"id": case_id, "expected": case["expected"],
                         "predicted": predicted, "correct": predicted == case["expected"],
                         "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                         "error": error})
    if not rows:
        raise ValueError("no cases")
    latencies = sorted(row["latency_ms"] for row in rows)
    return {"model": model, "cases": rows, "summary": {
        "count": len(rows), "correct": sum(row["correct"] for row in rows),
        "abstain_or_error": sum(row["predicted"] is None for row in rows),
        "p95_latency_ms": latencies[math.ceil(0.95 * len(latencies)) - 1]}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path, help="JSONL with id, state, instructions, criteria, expected")
    parser.add_argument("--endpoint", default="http://127.0.0.1:8000/v1/systemone")
    parser.add_argument("--model", required=True, help="server model ID; record exact revision separately")
    parser.add_argument("--timeout", type=float, default=8.0)
    args = parser.parse_args()
    try:
        print(json.dumps(replay(args.data, args.endpoint, args.model, args.timeout),
                         ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"decision replay: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
