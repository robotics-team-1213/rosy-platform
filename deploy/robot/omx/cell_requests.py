#!/usr/bin/env python3
"""Requests to a person in the cell: what to measure or check, and what the answer means (D-951 addendum, 2026-11-09).

Some cell facts only a person can settle: a distance a ruler reads independently of the camera model, a supervised
check of a known arm pose. The real-to-sim pipeline (tools/sim/omx_real2sim.py) or the calibration engine opens a
request; the Calibration app's screen (later; until then this command) shows it and records the answer. Nobody types
a cell value here (D-951 2: numbers are not set by hand). A `measure` request names the candidates the answer decides
between, each with the value it predicts, and the answer becomes the verdict "which candidate the ruler supports"; a
`check` request lists steps and takes pass or fail. The pipeline reads the verdict and changes a default only by commit.

  cell_requests.py open REQUEST.json [--image FILE]    a request (rosy.cell-request.v1) into the store, prints its id
  cell_requests.py list [--all]                        open requests (with --all, answered ones too)
  cell_requests.py show ID
  cell_requests.py answer ID --value 190 --by NAME [--note TEXT]     a measure request
  cell_requests.py answer ID --result pass|fail --by NAME [--note]   a check request

The store is ROSY_CELL_REQUESTS (default ~/.local/state/rosy/cell-requests): one <id>.json per request, its image
beside it, and history.jsonl with every open and answer. A request is answered once; a new reading is a new request.
Stdlib only, so it runs on the control PC as is.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

SCHEMA = "rosy.cell-request.v1"
KINDS = ("measure", "check")


def store() -> Path:
    return Path(os.environ.get("ROSY_CELL_REQUESTS", Path.home() / ".local/state/rosy/cell-requests"))


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _write(path: Path, data: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _log(root: Path, row: dict) -> None:
    with (root / "history.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def validate(req: dict) -> dict:
    """The request as stored; raises ValueError naming what is missing or wrong."""
    for key in ("id", "kind", "item", "question", "how"):
        if not str(req.get(key, "")).strip():
            raise ValueError(f"request needs {key}")
    if req["kind"] not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    if not req["id"].replace("-", "").replace("_", "").isalnum():
        raise ValueError("id: letters, digits, - and _ only")
    if req["kind"] == "measure":
        cands = req.get("candidates")
        if not isinstance(cands, dict) or len(cands) < 2 or not all(isinstance(v, (int, float)) for v in cands.values()):
            raise ValueError("a measure request names two or more candidates with the value each predicts")
        if not isinstance(req.get("tolerance"), (int, float)) or req["tolerance"] <= 0 or not req.get("unit"):
            raise ValueError("a measure request needs a positive tolerance and a unit")
        values = sorted(cands.values())
        if any(b - a <= 2 * req["tolerance"] for a, b in zip(values, values[1:])):
            raise ValueError("candidates closer than twice the tolerance: one reading cannot tell them apart")
    elif not isinstance(req.get("steps"), list) or not req["steps"]:
        raise ValueError("a check request lists its steps")
    return dict(req, schema=SCHEMA)


def open_request(req: dict, image: Path | None = None, root: Path | None = None) -> dict:
    root = root or store()
    root.mkdir(parents=True, exist_ok=True)
    req = validate(req)
    path = root / f"{req['id']}.json"
    if path.exists():
        raise ValueError(f"request {req['id']} exists; a new reading is a new request")
    if image:
        req["image"] = f"{req['id']}{Path(image).suffix}"
        shutil.copyfile(image, root / req["image"])
    req.update(status="open", opened_at=now(), answer=None)
    _write(path, req)
    _log(root, dict(event="open", id=req["id"], at=req["opened_at"], item=req["item"]))
    return req


def load(request_id: str, root: Path | None = None) -> dict:
    path = (root or store()) / f"{request_id}.json"
    if not path.exists():
        raise ValueError(f"no request {request_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def verdict(req: dict, value: float) -> str:
    """The candidate whose prediction is within tolerance of the reading, else 'neither' (the reading supports none)."""
    near = [(abs(value - v), name) for name, v in req["candidates"].items() if abs(value - v) <= req["tolerance"]]
    return min(near)[1] if near else "neither"


def answer(request_id: str, by: str, value: float | None = None, result: str | None = None, note: str = "",
           root: Path | None = None) -> dict:
    root = root or store()
    req = load(request_id, root)
    if req["status"] != "open":
        raise ValueError(f"request {request_id} is already {req['status']}")
    if not by.strip():
        raise ValueError("an answer names who measured or checked")
    if req["kind"] == "measure":
        if value is None:
            raise ValueError("a measure request is answered with --value")
        ans = dict(value=float(value), unit=req["unit"], verdict=verdict(req, float(value)))
    else:
        if result not in ("pass", "fail"):
            raise ValueError("a check request is answered with --result pass or fail")
        ans = dict(result=result)
    ans.update(by=by.strip(), note=note.strip(), at=now())
    req.update(status="answered", answer=ans)
    _write(root / f"{request_id}.json", req)
    _log(root, dict(event="answer", id=request_id, **ans))
    return req


def listing(root: Path | None = None, everything: bool = False) -> list[dict]:
    root = root or store()
    if not root.exists():
        return []
    rows = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(root.glob("*.json"))]
    return [r for r in rows if r.get("schema") == SCHEMA and (everything or r["status"] == "open")]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("open"); o.add_argument("request"); o.add_argument("--image")
    ls = sub.add_parser("list"); ls.add_argument("--all", action="store_true")
    s = sub.add_parser("show"); s.add_argument("id")
    a = sub.add_parser("answer"); a.add_argument("id"); a.add_argument("--value", type=float)
    a.add_argument("--result", choices=["pass", "fail"]); a.add_argument("--by", required=True); a.add_argument("--note", default="")
    args = p.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # the questions are Korean; a cp1252/cp949 console must not refuse them
    try:
        if args.cmd == "open":
            src = sys.stdin.read() if args.request == "-" else Path(args.request).read_text(encoding="utf-8")
            print(open_request(json.loads(src), Path(args.image) if args.image else None)["id"])
        elif args.cmd == "list":
            for r in listing(everything=args.all):
                tail = r["answer"] and (r["answer"].get("verdict") or r["answer"].get("result"))
                print(f"{r['id']}  {r['status']}  {r['item']}  {r['question']}" + (f"  -> {tail}" if tail else ""))
        elif args.cmd == "show":
            print(json.dumps(load(args.id), ensure_ascii=False, indent=1))
        else:
            req = answer(args.id, args.by, args.value, args.result, args.note)
            print(json.dumps(req["answer"], ensure_ascii=False))
    except ValueError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
