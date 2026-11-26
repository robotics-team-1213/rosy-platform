#!/usr/bin/env python3
"""Train a bounded pickup correction against an arm-local S3 MuJoCo proxy."""

import argparse
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import math
from pathlib import Path
import random

REGISTRATION = "unregistered-arm-local-proxy"
TASK = "omx-s-s3-pickup-alignment"
LIMITS = (.012, .012, .15)
BASE = (0., 0., 0.)
TRAIN_SEEDS = 3
EVAL_SEEDS = 6


@dataclass(frozen=True)
class Condition:
    seed: int
    stratum: str
    box_dx_m: float
    box_dy_m: float
    box_yaw_rad: float
    observed_dx_m: float
    observed_dy_m: float
    observed_yaw_rad: float


def make_condition(index, split):
    limit = TRAIN_SEEDS if split == "train" else EVAL_SEEDS
    if split not in {"train", "evaluation"} or not 0 <= index < limit:
        raise ValueError("unknown S3 condition")
    seed = index if split == "train" else 1000 + index
    rng = random.Random(seed)
    limit_m = .004 if split == "train" else .006
    dx, dy = [rng.uniform(-limit_m, limit_m) for _ in range(2)]
    yaw = rng.uniform(-.025, .025)
    stratum = "nominal"
    if split == "evaluation" and index in (2, 3):
        stratum, dy = "overhang", .026
    if split == "evaluation" and index in (4, 5):
        stratum, yaw = "wrong-yaw", .46
    # Fixed synthetic observation error shared by the two policies.
    observed = (dx + .005 + rng.uniform(-.001, .001),
                dy - .004 + rng.uniform(-.001, .001),
                yaw + .065 + rng.uniform(-.009, .009))
    return Condition(seed, stratum, dx, dy, yaw, *observed)


def allowed(condition):
    return (abs(condition.observed_dx_m) <= .015
            and abs(condition.observed_dy_m) <= .014
            and abs(condition.observed_yaw_rad) <= .20)


def bounded(residual):
    if len(residual) != 3 or not all(math.isfinite(x) for x in residual):
        raise ValueError("S3 correction requires three finite values")
    return tuple(max(-limit, min(limit, value)) for value, limit in zip(residual, LIMITS))


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True).encode("utf-8")


def save(path, value):
    pending = path.with_suffix(".pending")
    pending.write_bytes(encode(value) + b"\n")
    pending.replace(path)


def summarize(rows):
    return {
        "episodes": len(rows),
        "attempted": sum(row["attempted"] for row in rows),
        "stable_placements": sum(row["result"] == "placed" for row in rows),
        "safe_refusals": sum(row["result"] == "safe_refusal" for row in rows),
        "forbidden_contacts": sum(row["result"] == "forbidden_contact" for row in rows),
    }


def run(out, *, trials=10):
    from world_s3_pickup_physics import Scene

    if type(trials) is not int or not 1 <= trials <= 24:
        raise ValueError("trials must be between 1 and 24")
    scene = Scene()
    out.mkdir(parents=True, exist_ok=False)
    binding = {"run_id": out.name, "task": TASK, "engine": "mujoco",
               "scene_sha256": scene.digest, "registration": REGISTRATION}
    train = [make_condition(index, "train") for index in range(TRAIN_SEEDS)]
    held_out = [make_condition(index, "evaluation") for index in range(EVAL_SEEDS)]
    rng = random.Random(7603)
    champion = BASE
    best_reward = -math.inf
    for step in range(trials):
        candidate = BASE if step == 0 else bounded(tuple(
            center + rng.gauss(0, limit / 3) for center, limit in zip(champion, LIMITS)
        ))
        observations = [scene.rollout(condition, candidate, attempted=allowed(condition))[0] for condition in train]
        reward = sum(row["reward"] for row in observations) / len(observations)
        if reward > best_reward:
            champion, best_reward = candidate, reward
        progress = dict(binding, phase="training", step=step + 1, total_steps=trials,
                        reward=reward, best_reward=best_reward)
        save(out / "progress.json", progress)
        print(encode(progress).decode(), flush=True)
    checkpoint = dict(binding, schema="rosy.world.s3-residual.v1", correction=champion,
                      limits=LIMITS, training_conditions=[asdict(c) for c in train],
                      best_mean_reward=best_reward, trials=trials)
    save(out / "checkpoint.json", checkpoint)
    checkpoint_hash = sha256((out / "checkpoint.json").read_bytes()).hexdigest()
    save(out / "progress.json", dict(binding, phase="evaluation", step=trials, total_steps=trials,
                                     reward=reward, best_reward=best_reward))
    pairs = []
    for condition in held_out:
        pair = {}
        for policy, residual in (("ik", BASE), ("learned", champion)):
            result, frames = scene.rollout(condition, residual, attempted=allowed(condition), capture=True)
            name = f"episode-{condition.seed}-{policy}.json"
            pair[policy] = dict(result, replay=name)
            save(out / name, dict(
                binding, schema="rosy.world.s3-replay.v1", policy=policy,
                checkpoint_sha256=checkpoint_hash if policy == "learned" else None,
                condition=result["condition"], result=result["result"], geometry=scene.geometry, frames=frames,
            ))
        pairs.append(pair)
    report = dict(binding, schema="rosy.world.s3-evaluation.v1",
                  checkpoint_sha256=checkpoint_hash, pairs=pairs,
                  policies={policy: summarize([pair[policy] for pair in pairs])
                            for policy in ("ik", "learned")})
    save(out / "evaluation.json", report)
    save(out / "progress.json", dict(binding, phase="completed", step=trials, total_steps=trials,
                                     reward=reward, best_reward=best_reward))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="new experiment output directory")
    parser.add_argument("--trials", type=int, default=10, help="bounded search budget")
    args = parser.parse_args()
    run(args.out, trials=args.trials)


if __name__ == "__main__":
    main()
