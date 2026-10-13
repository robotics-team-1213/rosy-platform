"""Lane-failure analysis loop (D-578): recorded lane losses -> facts -> Claude review -> rule -> routes.

Model PC only (heavy steps); the VLM endpoint is the AI PC's pinned model when its owner allows it.
Run the steps in order on one new run folder RUN:

  collect  --raw-root DIR --session ID [--session ID ...] --out RUN --models DIR [--models DIR ...]
           [--model-for DEVICE=REVISION ...] [--canary-bank FILE] [--frames 3] [--max-per-session 3]
           [--seed 0] [--tool-commit SHA]
           failure episodes (keep_debug strategy none, reason no_boundary/washed), sampled frames,
           sensor facts, the robot's own model revision re-run on them, and hidden canary tiles
           (bank: hand-labelled windows; synthetic: re-exposed / erased-mask / keeper-drop / ok copies
           of frames where both boundaries were held). RUN/key.json is the canary key.
  vlm      --run RUN [--backend ollama|fake] [--url URL] [--model NAME] [--timeout 90] [--unload]
           identity facts per frame from the fixed prompt (lane_failure.VLM_PROMPT); facts only.
           --unload sends keep_alive 0, which unloads the model for every user of that Ollama
  sheets   --run RUN [--per-sheet 3]
           RUN/sheets/: contact sheets (raw | overlay per frame + facts panel), index.json and
           REVIEW.md. Give a reviewer only this folder, never RUN/key.json.
  import-verdicts --run RUN --verdicts FILE --reviewer NAME
           reviewer JSONL {tile, cause, confidence, reason}; refused when canary accuracy is below
           lane_failure.MIN_CANARY_RATE or there are too few canaries. One try per run: after a refusal
           only a new collect (new seed, new canaries) can be reviewed; misses go to canary-misses.json
  fuse     --run RUN
           rule fusion per episode (rewrites label-candidates/ every time) -> final.jsonl,
           label-candidates/verified-inputs.jsonl (model_miss
           only; no draft mask, pending human labels via review_ingest), stuck-handoff.jsonl,
           perception-issue.jsonl, human-queue.jsonl, report.md, report.json

Canary bank JSON: [{"session": ID, "t0": s, "t1": s, "cause": CAUSE, "labelled_by": WHO, "note": ...}],
t0/t1 in seconds after the session's first camera frame.
"""
import argparse
import hashlib
import json
import random
import shutil
import sys
import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np

import extract  # noqa: E402  (adds middleware/perception and contracts/foundation to sys.path)
import lane_failure as lf
from lane_derived_drivable import _git_commit

OVERLAY = {"background": (60, 60, 60), "lane_marking": (255, 255, 255), "wall": (0, 0, 255),
           "drivable": (0, 200, 0), "stop_line": (255, 0, 255)}  # BGR: grey, white, red, green, magenta
CAL_TOPIC, KEEP_TOPIC = "camera/calibration/status", "line/keep_debug"


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _file_sha(path):
    """sha256 of a file, or None when it does not exist (VLM not run)."""
    return _sha(Path(path).read_bytes()) if Path(path).exists() else None


def _jsonl(path, rows):
    Path(path).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def _read_jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


# --- collect -------------------------------------------------------------------------------------

def _models(roots):
    """{revision: folder} from folders that are, or hold up to two levels down, model folders."""
    found = {}
    for root in roots:
        root = Path(root)
        for manifest in [root / "model_manifest.json", *root.glob("*/model_manifest.json"),
                         *root.glob("*/*/model_manifest.json")]:
            if manifest.is_file():
                rev = json.loads(manifest.read_text(encoding="utf-8")).get("model_revision")
                found.setdefault(rev, manifest.parent)
    return found


class _Runner:
    """The robot-side manifest + preprocessing (learned.lane_mask), ONNX on the model PC CPU."""

    def __init__(self, folder):
        import onnxruntime as ort
        from control.sensing.perception.learned.lane_mask import preprocess
        from control.sensing.perception.learned.manifest import load_manifest, verify_files
        self.manifest = load_manifest(folder)
        verify_files(self.manifest)
        self._pre = preprocess
        self._s = ort.InferenceSession(str(self.manifest.onnx_file()), providers=["CPUExecutionProvider"])
        self._in = self._s.get_inputs()[0].name
        self.revision = self.manifest.model_revision
        self.classes = [(c.index, c.name, c.role) for c in self.manifest.classes]

    def __call__(self, bgr):
        logits = self._s.run(None, {self._in: self._pre(bgr, self.manifest.input)})[0][0]
        cmap = logits.argmax(0).astype(np.uint8)
        return cv2.resize(cmap, (bgr.shape[1], bgr.shape[0]), interpolation=cv2.INTER_NEAREST)


def _session_frames(session):
    """Every camera frame with the facts the loop reads (clock rule of extract.py)."""
    import geometry
    meta = json.loads((session / "session.json").read_text(encoding="utf-8"))
    forward, forward_source = geometry.labeller_lidar_yaw_deg(meta.get("device"))
    rows = []
    for ordinal, (t, item, side, ext, extra) in enumerate(extract._mcap_frames(extract._mcap_files(session))):
        if ext != "jpg":
            continue
        cal = side.get(CAL_TOPIC)
        scan_dt = extra["dt"].get("scan")  # scan log time - frame log time; latest at or before the frame
        scan = side.get("scan") if scan_dt is not None and -lf.MAX_SCAN_DT_S <= scan_dt <= 0 else None
        rows.append({"ordinal": ordinal, "t": t, "log_ns": extra["log_ns"], "jpg": item,
                     "keep": lf.keep_fields(side.get(KEEP_TOPIC)),
                     "lidar_front_m": lf.lidar_front_m(scan, forward),
                     "odom": side.get("odom"), "calibration_active": cal.get("active") if isinstance(cal, dict) else None})
    bags = extract._mcap_files(session)
    bag_shas = [_sha(b.read_bytes()) for b in bags]
    source = {"session": session.name, "device": meta.get("device"), "mode": meta.get("mode"),
              "lidar_forward_deg": forward, "lidar_forward_source": forward_source,
              "bags": [b.name for b in bags], "bag_sha256": bag_shas,
              "source_video": f"{session.name}/bag/{bags[0].name}" if len(bags) == 1 else f"{session.name}/bag/",
              "source_video_sha256": bag_shas[0] if len(bags) == 1 else _sha("\n".join(bag_shas).encode())}
    return source, rows


def _frame_facts(row, t_first, bgr, cmap, classes, keep=None):
    return {"ordinal": row["ordinal"], "t": row["t"], "t_rel": round(row["t"] - t_first, 3), "log_ns": row["log_ns"],
            "lidar_front_m": row["lidar_front_m"], "calibration_active": row["calibration_active"],
            "keep": row["keep"] if keep is None else keep, "image": lf.image_facts(bgr),
            "model": lf.model_facts(cmap, classes)}


def _revision(rows, device, model_for):
    revs = [r["keep"]["paint_model_revision"] for r in rows if r["keep"] and r["keep"]["paint_model_revision"]]
    if revs:
        return max(sorted(set(revs)), key=revs.count), "keep_debug paint_model_revision"
    if device in model_for:
        return model_for[device], f"--model-for {device} (robot did not run a learned paint here)"
    raise ValueError(f"no model revision for device {device}: pass --model-for {device}=REVISION")


def _majority(values):
    values = [v for v in values if v is not None]
    return max(sorted(set(values)), key=values.count) if values else None


def _tile(ctx, first, last, frames_per_tile, kind=None):
    """One review tile: sampled frames of rows[first..last] with facts; kind makes a canary copy."""
    source, rows = ctx["source"], ctx["rows"]
    run = ctx["runner"](rows[first:last + 1])
    t_first, span = rows[0]["t"], rows[first:last + 1]
    frames = []
    for i in lf.sample(first, last, frames_per_tile):
        raw = cv2.imdecode(np.frombuffer(rows[i]["jpg"], np.uint8), cv2.IMREAD_COLOR)
        shown = lf.canary_image(raw, kind)
        cmap = lf.canary_class_map(run(shown), run.classes, kind)
        keep = lf.canary_keep(rows[i]["keep"], kind) if kind else None
        frames.append((rows[i], shown, cmap, _frame_facts(rows[i], t_first, shown, cmap, run.classes, keep)))
    facts = [f[3] for f in frames]
    keeps = [f["keep"] for f in facts if f["keep"]]
    return {"session": source, "t0": round(rows[first]["t"] - t_first, 2), "t1": round(rows[last]["t"] - t_first, 2),
            "n_frames": last - first + 1, "model": {"revision": run.revision, "source": run.source, "classes": run.classes},
            "motion": lf.odom_motion([r["odom"] for r in span]),
            "keep_reason": _majority([k["reason"] for k in keeps]),
            "paint_source": _majority([r["keep"]["paint_source_used"] for r in span if r["keep"]]),
            "frames": frames, "summary": lf.summarize(facts)}


def collect(args):
    out = Path(args.out)
    if out.exists():
        raise ValueError("new run folder required")
    commit = _git_commit(args.tool_commit)
    models, runners = _models(args.models), {}
    model_for = dict(x.split("=", 1) for x in args.model_for)
    bank_raw = Path(args.canary_bank).read_bytes() if args.canary_bank else b"[]"
    bank = json.loads(bank_raw)
    rng = random.Random(args.seed)
    real, ok_sources, bank_tiles = [], [], []
    for name in dict.fromkeys([*args.session, *[b["session"] for b in bank]]):
        source, rows = _session_frames(Path(args.raw_root) / name)
        if not rows:
            continue

        def runner(span, source=source):
            rev, rev_source = _revision(span, source["device"], model_for)
            if rev not in runners:
                if rev not in models:
                    raise ValueError(f"model {rev} not found under --models")
                runners[rev] = _Runner(models[rev])
            runners[rev].source = rev_source
            return runners[rev]
        ctx = {"source": source, "rows": rows, "runner": runner}
        times = [r["t"] for r in rows]
        if name in args.session:
            eps = lf.runs([lf.is_failure(r["keep"]) for r in rows], times)
            for first, last in sorted(eps, key=lambda e: e[0] - e[1])[:args.max_per_session]:
                real.append(_tile(ctx, first, last, args.frames))
            oks = lf.runs([bool(r["keep"]) and r["keep"]["strategy"] in lf.OK_STRATEGIES for r in rows], times,
                          min_frames=6, merge_gap_s=0.3)
            ok_sources += [(ctx, a, b) for a, b in rng.sample(oks, min(2, len(oks)))]
        for entry in (e for e in bank if e["session"] == name):
            idx = [i for i, t in enumerate(times) if entry["t0"] <= t - times[0] <= entry["t1"]]
            if not idx:
                raise ValueError(f"canary bank window has no frames: {entry}")
            bank_tiles.append((_tile(ctx, idx[0], idx[-1], args.frames), {"cause": entry["cause"], "kind": "bank"}))
    need = lf.canaries_needed(len(real)) - len(bank_tiles)
    if need > 0 and not ok_sources:
        raise ValueError("no held-lane stretch to build synthetic canaries from")
    synthetic = []
    for j in range(max(0, need)):
        ctx, a, b = ok_sources[j % len(ok_sources)]
        kind = lf.CANARY_KINDS[j % len(lf.CANARY_KINDS)]
        synthetic.append((_tile(ctx, a, b, args.frames, kind=kind), {"cause": lf.CANARY_CAUSE[kind], "kind": kind}))
    items = [(t, None) for t in real] + bank_tiles + synthetic
    rng.shuffle(items)
    out.mkdir(parents=True)
    tiles, key = [], {}
    for n, (t, hidden) in enumerate(items, 1):
        tid = f"T{n:03d}"
        folder = out / "tiles" / tid
        folder.mkdir(parents=True)
        shown = []
        for k, (row, bgr, cmap, facts) in enumerate(t["frames"]):
            raw = row["jpg"] if hidden is None else cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 95])[1].tobytes()
            (folder / f"f{k}.jpg").write_bytes(raw)
            cv2.imwrite(str(folder / f"f{k}-class.png"), cmap)
            shown.append(dict(facts, file=f"tiles/{tid}/f{k}.jpg", class_png=f"tiles/{tid}/f{k}-class.png",
                              image_sha256=_sha(raw), width=int(bgr.shape[1]), height=int(bgr.shape[0])))
        tiles.append(dict({k: v for k, v in t.items() if k != "frames"}, tile=tid, frames=shown))
        if hidden is not None:
            key[tid] = dict(hidden, source_session=t["session"]["session"], t0=t["t0"], t1=t["t1"])
    _jsonl(out / "tiles.jsonl", tiles)
    (out / "key.json").write_text(json.dumps(key, indent=1) + "\n", encoding="utf-8")
    (out / "run.json").write_text(json.dumps({
        "schema": "rosy.lane-failure-run/1", "run": out.name, "tool_commit": commit,
        "sessions": args.session, "canary_bank": {"sha256": _sha(bank_raw), "entries": len(bank)},
        "frames_per_episode": args.frames,
        "models": {rev: str(models.get(rev)) for rev in runners}, "seed": args.seed,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, indent=1) + "\n", encoding="utf-8")
    return {"tiles": len(tiles), "episodes": len(real), "canaries": len(key)}


# --- VLM -----------------------------------------------------------------------------------------

class Ollama:
    """A pinned Ollama VLM (D-465/D-492 local model); identity facts only."""

    def __init__(self, url, model, timeout):
        self.url, self.model, self.timeout = url.rstrip("/"), model, timeout
        tags = self._call("/api/tags", None, method="GET")
        self.digest = next((m["digest"] for m in tags.get("models", []) if m["name"] == model), None)
        if self.digest is None:
            raise ValueError(f"{model} is not installed at {url}")

    def _call(self, path, body, method="POST"):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.url + path, data, {"Content-Type": "application/json"}, method=method)
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.load(r)

    def ask(self, bgr):
        big = cv2.resize(bgr, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)  # qwen_points.SCALE
        png = cv2.imencode(".png", big)[1].tobytes()
        import base64
        body = {"model": self.model, "stream": False, "think": False, "keep_alive": "2m",
                "options": {"temperature": 0, "num_predict": 200},
                "messages": [{"role": "user", "content": lf.VLM_PROMPT, "images": [base64.b64encode(png).decode()]}]}
        return self._call("/api/chat", body)["message"]["content"]

    def unload(self):
        """keep_alive 0 frees the model for EVERY user of this Ollama, not only this run: opt-in."""
        self._call("/api/generate", {"model": self.model, "keep_alive": 0})


class Fake:
    """Stand-in backend with the same interface: every answer 'unsure' (no AI PC model yet)."""
    model, digest = "fake-unsure", None

    def ask(self, bgr):
        return json.dumps({"lines_direction": "unsure", "lane_line_count": None, "wall_close": "unsure",
                           "on_road": "unsure"})

    def unload(self):
        pass


def vlm(args, backend=None):
    run = Path(args.run)
    backend = backend or (Fake() if args.backend == "fake" else Ollama(args.url, args.model, args.timeout))
    path = run / "vlm.jsonl"
    done = {(r["tile"], r["frame"]) for r in _read_jsonl(path)}
    asked = 0
    with path.open("a", encoding="utf-8") as fh:
        for tile in _read_jsonl(run / "tiles.jsonl"):
            for k, frame in enumerate(tile["frames"]):
                if (tile["tile"], k) in done:
                    continue
                t0 = time.time()
                try:
                    text = backend.ask(cv2.imread(str(run / frame["file"])))
                    facts = lf.parse_vlm(text)
                except (OSError, ValueError, KeyError) as exc:
                    text, facts = "", dict(lf.UNSURE_VLM, error=f"{type(exc).__name__}: {exc}"[:200])
                fh.write(json.dumps({"tile": tile["tile"], "frame": k, "facts": facts, "reply": text[:400],
                                     "seconds": round(time.time() - t0, 2), "model": backend.model,
                                     "model_digest": backend.digest, "endpoint": getattr(backend, "url", "fake"),
                                     "prompt_id": lf.VLM_PROMPT_ID,
                                     "prompt_sha256": _sha(lf.VLM_PROMPT.encode())}) + "\n")
                fh.flush()
                asked += 1
    if getattr(args, "unload", False):  # after success only; Ollama's keep_alive (2m) ends it otherwise
        backend.unload()
    return {"asked": asked}


# --- sheets --------------------------------------------------------------------------------------

def _vlm_by_tile(run):
    out = {}
    for row in _read_jsonl(run / "vlm.jsonl"):
        out.setdefault(row["tile"], []).append(row["facts"])
    return {t: lf.vlm_vote(rows) for t, rows in out.items()}


def _facts_text(tile, vote):
    s, f0 = tile["summary"], tile["frames"][0]
    keep = f0["keep"] or {}
    shown = [f"{k} {v}" for k, v in f0["model"]["fractions"].items() if v >= 0.01]
    lines = [tile["tile"],
             f"LiDAR front: {s['lidar_front_m']} m",
             f"odom: moved {tile['motion']['moved_m']} m, turned {tile['motion']['turned_deg']} deg",
             f"keep: {keep.get('strategy')} / {keep.get('reason')}",
             f"  paint {tile['paint_source']}, boundaries {s['boundaries']}",
             f"  transverse {s['transverse']}, rejected {','.join(keep.get('rejected') or []) or '-'}",
             f"  failing share {s['keep_failing']}",
             f"model: lane near {s['lane_near']}, dir {s['lane_direction']}",
             *["  " + ", ".join(pair) for pair in (shown[i:i + 2] for i in range(0, len(shown), 2))],
             f"image: mean {f0['image']['mean_gray']}, sat {f0['image']['saturated']}, dark {f0['image']['dark']}",
             f"calibration active: {s['calibration_active']}"]
    if vote:
        lines += [f"VLM: lines {vote['lines_direction']}, count {vote['lane_line_count']}",
                  f"  wall close {vote['wall_close']}, on road {vote['on_road']}"]
    else:
        lines.append("VLM: not run")
    return lines


def _tile_image(run, tile, vote):
    cols = []
    for frame in tile["frames"]:
        raw = cv2.imread(str(run / frame["file"]))
        cmap = cv2.imread(str(run / frame["class_png"]), cv2.IMREAD_UNCHANGED)
        paint = np.zeros_like(raw)
        for index, _, role in tile["model"]["classes"]:
            paint[cmap == index] = OVERLAY.get(role, (0, 255, 255))
        cols.append(np.vstack([raw, cv2.addWeighted(raw, 0.5, paint, 0.5, 0)]))
    while len(cols) < 3:
        cols.append(np.full_like(cols[0], 255))
    body = np.hstack(cols)
    panel = np.full((body.shape[0], 520, 3), 255, np.uint8)
    for i, text in enumerate(_facts_text(tile, vote)):
        cv2.putText(panel, text, (8, 26 + i * 28), cv2.FONT_HERSHEY_SIMPLEX, 0.62 if i else 0.9,
                    (0, 0, 0), 2 if i == 0 else 1, cv2.LINE_AA)
    out = np.hstack([body, panel])
    return np.vstack([out, np.full((12, out.shape[1], 3), 180, np.uint8)])


REVIEW = """# Lane failure review ({run})

Each tile is one moment where a robot's lane keeper reported no lane. Top row: raw forward camera
frames (time left to right). Bottom row: the robot's lane model on the same frame (white lane line,
red wall, green drivable, grey floor, magenta stop line). Right: recorded facts (LiDAR front distance,
odometry, keep_debug, model fractions and line direction, exposure, VLM identity facts).
The VLM facts can be wrong; the pictures and sensors decide.

Choose ONE cause per tile:
- model_miss: white lane tape is visible along the road in the raw frames, but the model did not mark it
  (or marked it badly) -> these frames should become training labels
- pose_off_lane: the robot is not on a lane facing along it (across the lane, nose to a wall, outside
  the track); the model may be right, there is simply no road ahead to keep
- keeper_logic: the model marked the lane lines along the road correctly but keep still lost them
- geometry_calibration: lines marked correctly, but the ground projection/camera calibration is the
  likely problem (e.g. calibration inactive and lines far from where keep looked)
- camera_exposure: the image is too dark, washed out or blurred to see the floor
- ok: no real loss (the keeper held a boundary; nothing to fix)

Some tiles are test tiles with a known answer; judge every tile on its own.
Write one JSON line per tile to verdicts.jsonl:
{{"tile": "T001", "cause": "pose_off_lane", "confidence": 0.9, "reason": "faces wall 15 cm away, one transverse line"}}
Tiles: {tiles}. Sheets: {sheets}.
"""


def sheets(args):
    run = Path(args.run)
    dest = run / "sheets"
    if dest.exists():
        raise ValueError("sheets already made for this run")
    dest.mkdir()
    tiles, votes = _read_jsonl(run / "tiles.jsonl"), _vlm_by_tile(run)
    index, names = {}, []
    for start in range(0, len(tiles), args.per_sheet):
        name = f"sheet-{start // args.per_sheet + 1:03d}.png"
        group = tiles[start:start + args.per_sheet]
        images = [_tile_image(run, t, votes.get(t["tile"])) for t in group]
        cv2.imwrite(str(dest / name), np.vstack(images))
        names.append(name)
        index.update({t["tile"]: name for t in group})
    (dest / "index.json").write_text(json.dumps({"run": run.name, "tiles": index,
                                                 "vlm_sha256": _file_sha(run / "vlm.jsonl")}, indent=1) + "\n",
                                     encoding="utf-8")
    (dest / "REVIEW.md").write_text(REVIEW.format(run=run.name, tiles=len(index), sheets=", ".join(names)),
                                    encoding="utf-8")
    return {"sheets": len(names), "tiles": len(index)}


# --- verdicts and fusion -------------------------------------------------------------------------

def import_verdicts(args):
    """One import per run. A refused batch ends the run: the reviewer has seen these canaries, so a
    retry needs a fresh collect (new run, new seed, new canaries). Refusal output carries counts only;
    which tiles missed goes to canary-misses.json beside key.json, never into sheets/."""
    run = Path(args.run)
    if (run / "review-refused.json").exists():
        raise ValueError("this run's review was refused; collect a new run (new seed, new canaries)")
    sheet_index = json.loads((run / "sheets" / "index.json").read_text(encoding="utf-8"))
    if sheet_index.get("vlm_sha256") != _file_sha(run / "vlm.jsonl"):
        raise ValueError("vlm.jsonl changed after the sheets were made; the reviewer saw other facts")
    index = sheet_index["tiles"]
    key = json.loads((run / "key.json").read_text(encoding="utf-8"))
    raw = Path(args.verdicts).read_bytes()
    answers = lf.parse_verdicts(raw.decode("utf-8").splitlines(), index)
    kinds = [h["kind"] for h in key.values()]
    record = {"reviewer": args.reviewer, "verdicts_sha256": _sha(raw), "vlm_sha256": sheet_index["vlm_sha256"],
              "instructions_sha256": _sha((run / "sheets" / "REVIEW.md").read_bytes()),
              "canary_kinds": {"bank": kinds.count("bank"), "synthetic": len(kinds) - kinds.count("bank")},
              "imported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    try:
        record["canaries"], misses = lf.score_canaries(key, answers, len(index) - len(key))
    except ValueError as exc:
        if isinstance(exc, lf.CanaryRefused):
            record["canaries"] = exc.block
            (run / "canary-misses.json").write_text(json.dumps(exc.misses, indent=1) + "\n", encoding="utf-8")
        (run / "review-refused.json").write_text(json.dumps(dict(record, refused=str(exc)), indent=1) + "\n",
                                                 encoding="utf-8")
        raise
    (run / "canary-misses.json").write_text(json.dumps(misses, indent=1) + "\n", encoding="utf-8")
    _jsonl(run / "verdicts.jsonl", [answers[t] for t in sorted(answers)])
    record["imported_sha256"] = _file_sha(run / "verdicts.jsonl")
    (run / "review.json").write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
    return record["canaries"]


def _candidate_rows(run, tile, out):
    rows = []
    s = tile["session"]
    for frame in tile["frames"]:
        image = out / "images" / f"{tile['tile']}-{Path(frame['file']).name}"
        image.parent.mkdir(parents=True, exist_ok=True)
        image.write_bytes((run / frame["file"]).read_bytes())
        rows.append({"source_session": s["session"], "capture_group": s["session"],
                     "source_video": s["source_video"], "source_video_sha256": s["source_video_sha256"],
                     "video_frame": frame["ordinal"], "video_time_s": frame["t_rel"],
                     "timestamp_basis": "camera_header_stamp", "collection": f"lane-failure-{run.name}",
                     "width": frame["width"], "height": frame["height"], "image": str(image.resolve()),
                     "image_sha256": frame["image_sha256"], "annotation_source": "lane_failure_loop",
                     "annotation_note": f"model_miss {tile['tile']} {tile['model']['revision']}"[:100]})
    return rows


def fuse_run(args):
    run = Path(args.run)
    review = json.loads((run / "review.json").read_text(encoding="utf-8"))
    if (_file_sha(run / "verdicts.jsonl") != review["imported_sha256"]
            or _file_sha(run / "vlm.jsonl") != review["vlm_sha256"]):
        raise ValueError("verdicts.jsonl or vlm.jsonl differ from what import-verdicts recorded")
    key = json.loads((run / "key.json").read_text(encoding="utf-8"))
    verdicts = {r["tile"]: r for r in _read_jsonl(run / "verdicts.jsonl")}
    votes = _vlm_by_tile(run)
    shutil.rmtree(run / "label-candidates", ignore_errors=True)  # never keep candidates of an older fuse
    (run / "label-candidates").mkdir()
    finals, routes, candidates = [], {k: [] for k in ("stuck_handoff", "perception_issue", "human_queue")}, []
    for tile in _read_jsonl(run / "tiles.jsonl"):
        if tile["tile"] in key:
            continue
        result = lf.fuse(tile["summary"], votes.get(tile["tile"]), verdicts.get(tile["tile"]))
        row = {"episode": tile["tile"], "session": tile["session"]["session"], "device": tile["session"]["device"],
               "t0": tile["t0"], "t1": tile["t1"], "n_frames": tile["n_frames"], "model": tile["model"]["revision"],
               "model_source": tile["model"]["source"], "keep_reason": tile["keep_reason"],
               "paint_source": tile["paint_source"], "motion": tile["motion"], "summary": tile["summary"],
               "vlm": votes.get(tile["tile"]), "verdict": verdicts.get(tile["tile"]), "fusion": result}
        finals.append(row)
        if result["route"] == "label_candidate":
            candidates += _candidate_rows(run, tile, run / "label-candidates")
        elif result["route"] in routes:
            routes[result["route"]].append(row)
    _jsonl(run / "final.jsonl", finals)
    for name, rows in routes.items():
        _jsonl(run / f"{name.replace('_', '-')}.jsonl", rows)
    _jsonl(run / "label-candidates" / "verified-inputs.jsonl", candidates)
    meta = json.loads((run / "run.json").read_text(encoding="utf-8"))
    vlm_rows = _read_jsonl(run / "vlm.jsonl")
    meta.update(reviewer=review["reviewer"], canaries={k: review["canaries"][k] for k in ("count", "caught", "rate")},
                vlm=f"{vlm_rows[0]['model']} @ {vlm_rows[0]['endpoint']}" if vlm_rows else "not run")
    (run / "report.md").write_text(lf.report_markdown(meta, finals), encoding="utf-8")
    summary = {"episodes": len(finals), "label_candidate_frames": len(candidates),
               **{k: len(v) for k, v in routes.items()},
               "final": {c: sum(r["fusion"]["final"] == c for r in finals) for c in lf.CAUSES}}
    (run / "report.json").write_text(json.dumps(dict(meta, summary=summary), indent=1) + "\n", encoding="utf-8")
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("collect")
    p.add_argument("--raw-root", required=True)
    p.add_argument("--session", action="append", default=[])
    p.add_argument("--out", required=True)
    p.add_argument("--models", action="append", required=True)
    p.add_argument("--model-for", action="append", default=[])
    p.add_argument("--canary-bank")
    p.add_argument("--frames", type=int, default=3)
    p.add_argument("--max-per-session", type=int, default=3)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--tool-commit")
    p = sub.add_parser("vlm")
    p.add_argument("--run", required=True)
    p.add_argument("--backend", choices=("ollama", "fake"), default="ollama")
    p.add_argument("--url", default="http://127.0.0.1:11434")
    p.add_argument("--model", default="qwen3-vl:8b-instruct")
    p.add_argument("--timeout", type=float, default=90)
    p.add_argument("--unload", action="store_true",
                   help="unload the model when done (keep_alive 0 frees it for every user of that Ollama)")
    p = sub.add_parser("sheets")
    p.add_argument("--run", required=True)
    p.add_argument("--per-sheet", type=int, default=3)
    p = sub.add_parser("import-verdicts")
    p.add_argument("--run", required=True)
    p.add_argument("--verdicts", required=True)
    p.add_argument("--reviewer", required=True)
    p = sub.add_parser("fuse")
    p.add_argument("--run", required=True)
    args = ap.parse_args(argv)
    step = {"collect": collect, "vlm": vlm, "sheets": sheets, "import-verdicts": import_verdicts,
            "fuse": fuse_run}[args.command]
    print(json.dumps(step(args)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
