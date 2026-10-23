"""Offline bench for closed-question VLM judgement (docs/plans/2026-10-23-vlm-fast-judge-design.md, T3-T4).

Model PC only. Per frame: deterministic preprocessing (quality metrics, fixed size on the model's patch grid),
one image prefix forward, then one short suffix forward per question; each answer is the probability over the
options' first tokens, read from logits without generating text. ``--check`` compares the cached-prefix
probabilities with a full forward of the same tokens. ``--ollama`` times the current per-image observation call
(operations/situation/rosy_situation/incidents/vision.py) on the same frames as a lower bound for that method.
Frames are read only; results are JSON lines and a summary. No labels: this measures latency and answer spread.
"""

import argparse
import base64
import copy
import glob
import io
import json
import math
import random
import statistics
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

INSTRUCTION = ("You check one {view} camera picture from a small robot. Answer the question with exactly one "
               "word from the options. Answer unclear when the picture does not show it.")
#: Question id -> (question, options). Ids and options follow the design; QUESTION_SET versions them.
QUESTIONS = {
    "front": {
        "front.lane_obstruction": ("Is there an object on the floor inside the lane ahead?", ("yes", "no", "unclear")),
        # v2: v1's multi-way "what is ahead" answered wall on nearly every frame; one yes/no per kind instead.
        "front.wall_ahead": ("Is a wall or upright panel blocking the lane directly ahead?", ("yes", "no", "unclear")),
        "front.robot_ahead": ("Is another robot in the lane directly ahead?", ("yes", "no", "unclear")),
        "front.person_ahead": ("Is a person or a person's legs in the lane directly ahead?", ("yes", "no", "unclear")),
        "front.lane_tape": ("Which lane boundary tapes are visible on the floor?", ("both", "left", "right", "none")),
        "front.shape": ("Is the lane ahead a bend, blocked, or straight?", ("bend", "blocked", "straight", "unclear")),
    },
    # shortcut: full ceiling frames have no target-robot crop, so ahead_space/robot_adjacent become scene-level
    # questions; switch to the design's per-robot questions once frames come with a crop around the robot.
    "top": {
        "top.robots_close": ("Are any two small robots within one robot length of each other?", ("yes", "no", "unclear")),
        "top.person_present": ("Is a person visible on the floor area?", ("yes", "no", "unclear")),
    },
    "wrist": {
        "wrist.object_in_gripper": ("Is an object held between the gripper fingers?", ("yes", "no", "unclear")),
        "wrist.gripper_empty": ("Is the gripper empty?", ("yes", "no", "unclear")),
    },
}
QUESTION_SET = "v2"
OBSERVE_PROMPT = ("Describe only visible physical surfaces and floor markings in this {view} image in one short "
                  "sentence. Do not assume a corner or free path. Do not identify a target robot. Answer JSON with "
                  "observation.")


def quality(image: Image.Image) -> dict:
    gray = np.asarray(image.convert("L"), dtype=np.float32)
    lap = (4 * gray[1:-1, 1:-1] - gray[:-2, 1:-1] - gray[2:, 1:-1] - gray[1:-1, :-2] - gray[1:-1, 2:])
    return {"sharpness": round(float(lap.var()), 1), "mean": round(float(gray.mean()), 1),
            "dark": round(float((gray < 10).mean()), 3), "bright": round(float((gray > 245).mean()), 3)}


def grid_size(width: int, height: int, long_side: int, factor: int) -> tuple:
    scale = long_side / max(width, height)
    return tuple(max(factor, int(round(v * scale / factor)) * factor) for v in (width, height))


def option_tokens(tokenizer, options) -> list:
    ids = [tokenizer.encode(o, add_special_tokens=False)[0] for o in options]
    if len(set(ids)) != len(ids):
        raise ValueError(f"options share a first token: {options}")
    return ids


def pct(values, q):
    values = sorted(values)
    return round(values[min(len(values) - 1, max(0, math.ceil(q * len(values)) - 1))], 4) if values else None


class Scorer:
    def __init__(self, model_id: str, quant: str):
        import torch
        from transformers import AutoModelForImageTextToText, AutoProcessor, BitsAndBytesConfig
        self.torch = torch
        kwargs = {"dtype": torch.bfloat16, "device_map": "cuda"}
        if quant == "4bit":
            kwargs["quantization_config"] = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                                                bnb_4bit_compute_dtype=torch.bfloat16)
        self.processor = AutoProcessor.from_pretrained(model_id)
        self.model = AutoModelForImageTextToText.from_pretrained(model_id, **kwargs).eval()
        ip = self.processor.image_processor
        self.factor = int(ip.patch_size) * int(getattr(ip, "merge_size", 1))
        self.tokenizer = self.processor.tokenizer
        text_config = getattr(self.model.config, "text_config", self.model.config)
        # Recurrent (linear-attention) layers cannot be cropped back to the prefix; copy the prefix cache instead.
        self.rollback = "copy" if any("linear" in str(t) for t in getattr(text_config, "layer_types", None) or ()) else "crop"

    def _texts(self, view: str, question: str, options) -> tuple:
        ask = f"Question: {question}\nOptions: {', '.join(options)}."
        messages = [{"role": "user", "content": [{"type": "image"},
                                                 {"type": "text", "text": INSTRUCTION.format(view=view) + "\n" + ask}]}]
        text = self.processor.apply_chat_template(messages, add_generation_prompt=True, tokenize=False,
                                                  enable_thinking=False)
        cut = text.index(ask)
        return text[:cut], text[cut:]

    def _sync(self):
        self.torch.cuda.synchronize()
        return time.perf_counter()

    def frame(self, image: Image.Image, view: str, check: bool) -> dict:
        torch = self.torch
        questions = QUESTIONS[view]
        t0 = self._sync()
        prefix, _ = self._texts(view, *next(iter(questions.values())))
        inputs = self.processor(text=[prefix], images=[image], return_tensors="pt").to("cuda")
        t1 = self._sync()
        with torch.inference_mode():
            out = self.model(**inputs, use_cache=True)
            cache = out.past_key_values
            length = inputs["input_ids"].shape[1]
            t2 = self._sync()
            answers, timings = {}, {"processor_s": t1 - t0, "prefix_s": t2 - t1, "image_tokens": int(length)}
            for qid, (question, options) in questions.items():
                p, suffix = self._texts(view, question, options)
                if p != prefix:
                    raise AssertionError("questions must share the image prefix")
                ids = self.tokenizer(suffix, add_special_tokens=False, return_tensors="pt").input_ids.to("cuda")
                tq = self._sync()
                # No attention_mask: with a cache, transformers 5.x builds M-RoPE positions from the mask's full
                # length; without it they continue from the cache length plus the prefix's rope delta.
                step = copy.deepcopy(cache) if self.rollback == "copy" else cache
                logits = self.model(input_ids=ids, past_key_values=step, use_cache=True,
                                    cache_position=torch.arange(length, length + ids.shape[1], device="cuda")
                                    ).logits[0, -1]
                if self.rollback == "crop":
                    cache.crop(-ids.shape[1])  # transformers 5.x: a negative count removes that many tokens
                if cache.get_seq_length() != length:
                    raise AssertionError("cache did not return to the image prefix")
                answers[qid] = self._read(logits, options)
                answers[qid]["s"] = round(self._sync() - tq, 4)
                if check:
                    joined = {**inputs, "input_ids": torch.cat([inputs["input_ids"], ids], 1),
                              "attention_mask": torch.ones(1, length + ids.shape[1], device="cuda",
                                                           dtype=inputs["attention_mask"].dtype)}
                    if "mm_token_type_ids" in inputs:
                        joined["mm_token_type_ids"] = torch.cat(
                            [inputs["mm_token_type_ids"], torch.zeros_like(ids, dtype=inputs["mm_token_type_ids"].dtype)], 1)
                    full = self.model(**joined).logits[0, -1]
                    ref = self._read(full, options)
                    answers[qid]["check_diff"] = round(max(abs(a - b) for a, b in zip(answers[qid]["p"], ref["p"])), 4)
                    answers[qid]["check_same"] = ref["answer"] == answers[qid]["answer"]
            timings["total_s"] = self._sync() - t0
        return {"answers": answers, "timings": {k: round(v, 4) if isinstance(v, float) else v for k, v in timings.items()}}

    def _read(self, logits, options) -> dict:
        ids = option_tokens(self.tokenizer, options)
        full = logits.float().softmax(-1)
        chosen = logits[ids].float().softmax(-1).tolist()
        best = max(range(len(options)), key=chosen.__getitem__)
        return {"answer": options[best], "p": [round(x, 4) for x in chosen], "mass": round(float(full[ids].sum()), 4)}


def ollama_observe(image: Image.Image, view: str, url: str, model: str) -> dict:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, "JPEG", quality=90)
    body = {"model": model, "stream": False, "options": {"temperature": 0, "num_ctx": 8192, "seed": 42, "num_predict": 96},
            "format": {"type": "object", "additionalProperties": False, "required": ["observation"],
                       "properties": {"observation": {"type": "string", "minLength": 1, "maxLength": 180}}},
            "messages": [{"role": "user", "content": OBSERVE_PROMPT.format(view=view),
                          "images": [base64.b64encode(buffer.getvalue()).decode()]}]}
    started = time.perf_counter()
    request = urllib.request.Request(f"{url}/api/chat", data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        reply = json.loads(response.read())
    return {"wall_s": round(time.perf_counter() - started, 4), "eval_count": reply.get("eval_count"),
            "prompt_eval_count": reply.get("prompt_eval_count")}


def ollama_questions(image: Image.Image, view: str, url: str, model: str) -> dict:
    """Same questions through Ollama: one token per question, options read from top_logprobs (prefix cache is Ollama's)."""
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, "JPEG", quality=90)
    jpeg = base64.b64encode(buffer.getvalue()).decode()
    answers, started = {}, time.perf_counter()
    for qid, (question, options) in QUESTIONS[view].items():
        body = {"model": model, "stream": False, "logprobs": True, "top_logprobs": 20,
                "options": {"temperature": 0, "num_ctx": 8192, "seed": 42, "num_predict": 1},
                "messages": [{"role": "user", "images": [jpeg], "content": INSTRUCTION.format(view=view)
                              + f"\nQuestion: {question}\nOptions: {', '.join(options)}."}]}
        tq = time.perf_counter()
        request = urllib.request.Request(f"{url}/api/chat", data=json.dumps(body).encode(), method="POST",
                                         headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=60) as response:
            reply = json.loads(response.read())
        top = {t["token"]: t["logprob"] for t in (reply.get("logprobs") or [{}])[0].get("top_logprobs", [])}
        # shortcut: an option is matched by its whole word or a prefix token; fine for one-word options of v1.
        scores = [max([lp for tok, lp in top.items() if tok and o.startswith(tok)] or [-math.inf]) for o in options]
        peak = max(scores)
        weights = [math.exp(s - peak) if s > -math.inf else 0.0 for s in scores] if peak > -math.inf else [0.0] * len(options)
        total = sum(weights) or 1.0
        p = [round(w / total, 4) for w in weights]
        answers[qid] = {"answer": options[p.index(max(p))] if peak > -math.inf else "none_in_top",
                        "p": p, "s": round(time.perf_counter() - tq, 4),
                        "prompt_eval_count": reply.get("prompt_eval_count")}
    return {"answers": answers, "wall_s": round(time.perf_counter() - started, 4)}


def _selftest():
    assert grid_size(1280, 720, 448, 32) == (448, 256)
    assert grid_size(320, 240, 320, 28) == (308, 252)
    flat = quality(Image.new("L", (16, 16), 0))
    assert flat["sharpness"] == 0 and flat["dark"] == 1.0
    assert pct([1, 2, 3, 4], 0.5) == 2 and pct([1, 2, 3, 4], 0.95) == 4


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--frames", action="append", required=True, metavar="VIEW=GLOB",
                        help="view (front, top, wrist) and a glob of JPEG frames; repeatable")
    parser.add_argument("--model", default="Qwen/Qwen3-VL-8B-Instruct")
    parser.add_argument("--quant", choices=("bf16", "4bit"), default="bf16")
    parser.add_argument("--long-side", type=int, action="append", help="resize long side (default: native)")
    parser.add_argument("--limit", type=int, default=40, help="frames per view, sampled with a fixed seed")
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--check", type=int, default=3, help="frames per view compared with a full forward")
    parser.add_argument("--ollama", default="", help="loopback Ollama URL to time the observation call")
    parser.add_argument("--ollama-model", default="qwen3-vl:8b-instruct")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--dump-questions", type=Path, metavar="FILE",
                        help="write {question_set, questions} for learning/curation/perception/vlm_judge.py and exit")
    known = argparse.ArgumentParser(add_help=False)
    known.add_argument("--dump-questions", type=Path)
    if (target := known.parse_known_args(argv)[0].dump_questions):
        target.write_text(json.dumps({"question_set": QUESTION_SET, "questions": QUESTIONS}, indent=2), encoding="utf-8")
        return 0
    args = parser.parse_args(argv)
    _selftest()
    if args.ollama and not args.ollama.startswith(("http://127.0.0.1:", "http://localhost:")):
        raise SystemExit("--ollama must be a loopback URL")
    pools = {}
    for spec in args.frames:
        view, _, pattern = spec.partition("=")
        if view not in QUESTIONS or not pattern:
            raise SystemExit(f"bad --frames {spec!r}")
        files = sorted(glob.glob(pattern))
        if not files:
            raise SystemExit(f"no frames for {spec!r}")
        pools.setdefault(view, []).extend(files)  # repeated views pool their globs
    sets = {view: random.Random(7).sample(files, min(args.limit, len(files))) for view, files in pools.items()}
    scorer = Scorer(args.model, args.quant)
    args.out.mkdir(parents=True, exist_ok=True)
    rows = []
    with open(args.out / "rows.jsonl", "w", encoding="utf-8") as sink:
        for long_side in args.long_side or [0]:
            for view, files in sets.items():
                for index, path in enumerate([files[0]] * args.warmup + files):
                    started = time.perf_counter()
                    image = Image.open(path).convert("RGB")
                    metrics = quality(image)
                    size = grid_size(*image.size, long_side or max(image.size), scorer.factor)
                    image = image.resize(size, Image.BICUBIC)
                    preprocess_s = time.perf_counter() - started
                    result = scorer.frame(image, view, check=args.warmup <= index < args.warmup + args.check)
                    if index < args.warmup:
                        continue
                    row = {"frame": path, "view": view, "long_side": long_side, "size": size, "quality": metrics,
                           "preprocess_s": round(preprocess_s, 4), **result}
                    if args.ollama:
                        row["ollama"] = ollama_observe(image, view, args.ollama, args.ollama_model)
                        row["ollama_questions"] = ollama_questions(image, view, args.ollama, args.ollama_model)
                    rows.append(row)
                    sink.write(json.dumps(row) + "\n")
    summary = {"model": args.model, "quant": args.quant, "question_set": QUESTION_SET, "factor": scorer.factor,
               "rollback": scorer.rollback,
               "groups": []}
    for long_side in args.long_side or [0]:
        for view in sets:
            group = [r for r in rows if r["view"] == view and r["long_side"] == long_side]
            totals = [r["timings"]["total_s"] + r["preprocess_s"] for r in group]
            entry = {"view": view, "long_side": long_side, "frames": len(group), "size": group[0]["size"],
                     "image_tokens": group[0]["timings"]["image_tokens"],
                     "total_p50_s": pct(totals, 0.5), "total_p95_s": pct(totals, 0.95),
                     "prefix_p50_s": pct([r["timings"]["prefix_s"] for r in group], 0.5),
                     "question_p50_s": pct([a["s"] for r in group for a in r["answers"].values()], 0.5),
                     "processor_p50_s": pct([r["timings"]["processor_s"] for r in group], 0.5),
                     "check_max_diff": max([a.get("check_diff", 0) for r in group for a in r["answers"].values()]),
                     "check_answer_mismatch": sum(a.get("check_same") is False for r in group for a in r["answers"].values()),
                     "questions": {}}
            for qid, (_, options) in QUESTIONS[view].items():
                picks = [r["answers"][qid] for r in group]
                entry["questions"][qid] = {
                    "answers": {o: sum(p["answer"] == o for p in picks) for o in options},
                    "top_p_median": round(statistics.median(max(p["p"]) for p in picks), 4),
                    "mass_median": round(statistics.median(p["mass"] for p in picks), 4)}
            if args.ollama:
                walls = [r["ollama"]["wall_s"] for r in group]
                entry["ollama_observe_p50_s"], entry["ollama_observe_p95_s"] = pct(walls, 0.5), pct(walls, 0.95)
                walls = [r["ollama_questions"]["wall_s"] for r in group]
                entry["ollama_questions_p50_s"], entry["ollama_questions_p95_s"] = pct(walls, 0.5), pct(walls, 0.95)
                entry["ollama_agree_with_hf"] = round(statistics.mean(
                    r["ollama_questions"]["answers"][q]["answer"] == r["answers"][q]["answer"]
                    for r in group for q in QUESTIONS[view]), 3)
            summary["groups"].append(entry)
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
