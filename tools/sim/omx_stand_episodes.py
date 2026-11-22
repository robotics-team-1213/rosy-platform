#!/usr/bin/env python3
"""Generate standalone D-1065 three-camera (`top`, `side`, `wrist`) LeRobot episodes placing into the `arm_a` outbound `stand`."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (HERE, ROOT / "learning/curation/omx"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import numpy as np  # noqa: E402
import omx_two_arm_sites as sites  # noqa: E402
import omx_two_arm_tasks as tasks  # noqa: E402
import omx_two_arm_teacher as teaching  # noqa: E402

JOINTS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
VIEWS = ("top", "side", "wrist")
SHAPE = (480, 640, 3)
REAL_CONTAINER_RGB = ((.92, .45, .62), (.62, .31, .14), (.78, .13, .12), (.86, .66, .10), (.10, .10, .10), (.18, .62, .24))
SOURCE_GROUPS = {
    "belt": ["belt"],
    "ship-h1": [f"ship-h1r{r}-l{l}" for r in (0, 1, 2) for l in (0, 1, 2)],
    "ship-h2": [f"ship-h2r{r}-l{l}" for r in (0, 1, 2) for l in (0, 1, 2)],
    "tmp-a": [f"tmp-a-{i}{s}" for i in (1, 2, 3) for s in ("", "-l1", "-l2")],
}
BACKGROUND_STACKS = [*(f"h1r{r}" for r in (0, 1, 2)), *(f"h2r{r}" for r in (0, 1, 2)), *(f"tmp-a-{i}" for i in (1, 2, 3))]


def dataset_features():
    """D-1065 three-camera 6-axis features for standalone `arm_a` `stand` episodes."""
    vec = dict(dtype="float32", shape=(len(JOINTS),), names=list(JOINTS))
    img = dict(dtype="video", shape=SHAPE, names=["height", "width", "channels"])
    return {"observation.state": vec, "action": vec, **{f"observation.images.{v}": img for v in VIEWS}}


def parse_seeds(spec: str) -> list[int]:
    """Parse `'6001..6003'` or `'6001,6002'` into a list of integer seeds."""
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if ".." in part:
            a, b = (int(x) for x in part.split("..", 1))
            if b < a:
                raise ValueError(f"invalid seed range {part!r}")
            out.extend(range(a, b + 1))
        else:
            out.append(int(part))
    if not out:
        raise ValueError("at least one seed is required")
    return out


def expand_sources(spec: str, layout) -> list[str]:
    """Expand source group names (`belt,ship-h1,ship-h2,tmp-a`) and explicit site names uniquely in order."""
    out, seen = [], set()
    for token in (t.strip() for t in spec.split(",") if t.strip()):
        items = SOURCE_GROUPS.get(token, [token])
        for s in items:
            if s not in layout.sites:
                raise ValueError(f"unknown source site {s!r}")
            if s not in seen:
                seen.add(s)
                out.append(s)
    if not out:
        raise ValueError("at least one source site is required")
    return out


def build_episode_plan(layout, src: str, rng: np.random.Generator, step_id: str = "o1") -> dict | None:
    """Build a validated single-step `arm_a -> stand` task for `src` with randomized background occupancy."""
    site = layout.sites[src]
    if site.get("blocked"):
        return None
    pool = [cid for cid, _ in layout.containers()]
    target = pool[0]
    rem = pool[1:]
    supports = {}
    if src != "belt" and site.get("layer", 0) > 0:
        for layer in range(site["layer"]):
            sup = layout.stack_at.get((site["stack"], layer))
            if not sup or not rem:
                return None
            supports[rem.pop(0)] = sup
    src_stack = None if src == "belt" else site.get("stack")
    step = {"id": step_id, "container": target, "from": src, "to": "stand", "arm": "arm_a", "outbound": True}

    def _validated(bg: dict):
        here = {**supports, **bg}
        if src != "belt":
            here[target] = src
        task = {"name": f"stand-{src}", "supply": [target] if src == "belt" else [], "start": here, "steps": [step]}
        try:
            tasks.validate(layout, task)
            return task
        except tasks.PlanRefused:
            return None

    avail = [st for st in BACKGROUND_STACKS if st != src_stack]
    rng.shuffle(avail)
    bg, free = {}, list(rem)
    for st in avail:
        if not free:
            break
        h = int(rng.integers(0, 4))
        for layer in range(min(h, len(free))):
            name = layout.stack_at.get((st, layer))
            if not name or layout.sites[name].get("blocked"):
                break
            cand = {**bg, free[0]: name}
            if _validated(cand) is not None:  # keep each background column compatible with wrist clearance
                bg = cand
                free.pop(0)
            else:
                break
    return _validated(bg) or _validated({})


def recolor_containers(world, layout, rng: np.random.Generator) -> None:
    """Apply cell container palette colors with +-10% brightness jitter per episode."""
    m = world.model
    for cid, _ in layout.containers():
        bid = m.body(cid).id
        rgb = np.asarray(REAL_CONTAINER_RGB[int(rng.integers(len(REAL_CONTAINER_RGB)))]) * float(rng.uniform(.9, 1.1))
        for g in np.where(m.geom_bodyid == bid)[0]:
            if m.geom_rgba[g][3] > 0:
                m.geom_rgba[g][:3] = np.clip(rgb, 0, 1)


def dart_scale(phase: str, settling: bool) -> float:
    """OU noise scale per teacher phase: 0 during closed-loop settle and contact phases, attenuated during lower."""
    if settling or phase in ("grasp", "close", "lift", "release"):
        return 0.0
    return 0.15 if phase == "lower" else 1.0


class StandArmRecorder(teaching.Teacher):
    """Records `arm_a` 6-DOF D-1065 3-camera episodes placing into `stand` with clean action labels and optional DART noise."""

    def __init__(self, world, dataset, *, dart_sigma: float = 0.03, dart_rho: float = 0.9, seed: int = 0, snapshot_dir=None):
        super().__init__(world, seed=seed)
        self.dataset, self.dart_sigma, self.dart_rho = dataset, float(dart_sigma), float(dart_rho)
        self.dart_rng = np.random.default_rng([seed, 4242])
        self.step_ctx, self.frames, self.saved = None, 0, []
        self._settling, self._dart, self._dart_step = False, None, None
        self.snapshot_dir = Path(snapshot_dir) if snapshot_dir else None
        self._snapped = set()

    def settle_g(self, *args, **kwargs):
        self._settling = True
        try:
            return (yield from super().settle_g(*args, **kwargs))
        finally:
            self._settling = False

    def _save_snap(self, data, tag: str):
        if self.snapshot_dir is None or tag in self._snapped:
            return
        from PIL import Image
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        for view in ("top", "side", "a_wrist"):
            Image.fromarray(self.world.render(data, view)).save(self.snapshot_dir / f"{tag}_{view}.png")
        self._snapped.add(tag)

    def frame(self, data, targets, label, ctxs=None):
        if self.step_ctx is not None:
            arm = self.step_ctx["arm"]
            if self._dart is None or self._dart_step is not self.step_ctx:
                self._dart, self._dart_step = np.zeros(5), self.step_ctx
            scale = dart_scale(self.phase, self._settling)
            self._dart = (self.dart_rho * self._dart
                          + math.sqrt(max(0.0, 1.0 - self.dart_rho ** 2)) * self.dart_sigma * self.dart_rng.standard_normal(5))
            clean_arm = np.asarray(targets[arm], dtype=np.float32)
            exec_arm = np.asarray(clean_arm, dtype=float).copy()
            if self.dart_sigma > 0.0 and scale > 0.0:
                exec_arm[:5] += scale * self._dart
            if not self._settling and self.phase == "lower":
                self._snap_ready = True
            elif getattr(self, "_snap_ready", False) and self.phase == "release":
                self._save_snap(data, "lower")
                self._snap_ready = False
            self.dataset.add_frame({
                "task": f"Move the designated container from {self.step_ctx['from']} to stand.",
                "observation.state": data.qpos[self.world.q[arm]].astype(np.float32),
                "action": clean_arm,
                "observation.images.top": self.world.render(data, "top"),
                "observation.images.side": self.world.render(data, "side"),
                "observation.images.wrist": self.world.render(data, "a_wrist"),
            })
            self.frames += 1
            super().frame(data, {**targets, arm: exec_arm}, label, ctxs)
            return
        super().frame(data, targets, label, ctxs)

    def run_single(self, here, step, branch="best"):
        return super().run_single(here, step, branch=branch)

    def run_step(self, data, step, here):
        self.step_ctx, self.frames, self._snap_ready = step, 0, False
        try:
            result = super().run_step(data, step, here)
            if result["result"] == "pass" and self.frames > 0:
                self._save_snap(data, "after_release")
                self.dataset.save_episode()
                self.saved.append(dict(step=step, initial_occupancy=here, frames=self.frames, pose=result["pose"]))
            else:
                self.dataset.clear_episode_buffer()
            return result
        finally:
            self.step_ctx = None


def generate(out: Path, seeds: list[int], sources_spec: str, *, max_per_seed: int = 0, preset: str | None = "v24-20261114",
             choices: dict | None = None, dart_sigma: float = 0.03, repo_id: str = "local/omx-stand-sim-arm_a",
             snapshot_dir: Path | None = None, run_gate: bool = True) -> dict:
    """Generate standalone `stand` LeRobot dataset, write receipt, and optionally gate with `data_gate`."""
    import omx_two_arm_world as sim
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    out = Path(out)
    if out.exists():
        raise ValueError(f"--out already exists: {out}")
    layout_kw = {**({"preset": preset} if preset else {}), **(choices or {})}
    layout = sites.Layout(**layout_kw)
    candidates = expand_sources(sources_spec, layout)
    world = sim.World(layout)
    dataset = LeRobotDataset.create(
        repo_id, sim.FPS, root=out, robot_type="omx_sim_arm", features=dataset_features(),
        video_backend="pyav", vcodec="h264", streaming_encoding=True, encoder_threads=1, metadata_buffer_size=1,
    )
    records = []
    try:
        for seed in seeds:
            rng = np.random.default_rng([seed, 7717])
            picked = list(candidates)
            if max_per_seed and len(picked) > max_per_seed:
                idx = rng.choice(len(picked), size=max_per_seed, replace=False)
                picked = [picked[int(i)] for i in sorted(idx)]
            for idx, src in enumerate(picked):
                ep_seed = seed * 100 + idx + 1
                plan = build_episode_plan(layout, src, rng, step_id=f"st-{ep_seed}")
                if plan is None:
                    records.append(dict(seed=seed, source=src, status="skipped", reason="plan_refused"))
                    continue
                recolor_containers(world, layout, np.random.default_rng([ep_seed, 9341]))
                rec = StandArmRecorder(world, dataset, dart_sigma=dart_sigma, seed=ep_seed, snapshot_dir=snapshot_dir)
                row = rec.run_single(plan["start"], plan["steps"][0])
                records.append(dict(seed=seed, ep_seed=ep_seed, source=src, status=row["result"],
                                    frames=rec.saved[-1]["frames"] if row["result"] == "pass" else 0,
                                    pose=row.get("pose"), reason=row.get("reason")))
                print(json.dumps({"seed": seed, "source": src, "result": row["result"], "pose": row.get("pose")}), flush=True)
    finally:
        for renderer in world.renderers.values():
            renderer.close()
        dataset.finalize()
    receipt = dict(
        schema="rosy.omx-stand-episodes.v1", repo_id=repo_id, fps=sim.FPS, dart_sigma=dart_sigma,
        choices=layout.choices, passed=sum(r["status"] == "pass" for r in records), total=len(records),
        episodes=records,
    )
    if run_gate and receipt["passed"] > 0:
        import data_gate
        gate = data_gate.gate(out, "arm_a", {"kind": "sim", "layout": "random"})
        admitted = data_gate.check_receipt(out)
        receipt["gate"] = dict(counts=gate["counts"], goals_passing=gate["goals_passing"], admitted=len(admitted))
    (out / "stand-episodes-receipt.json").write_text(json.dumps(receipt, indent=1), encoding="utf-8")
    return receipt


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--seeds", required=True, help="e.g. 6001..6003 or 6001,6002")
    p.add_argument("--sources", default="belt,ship-h1,ship-h2,tmp-a")
    p.add_argument("--max-per-seed", type=int, default=0)
    p.add_argument("--preset", default="v24-20261114")
    p.add_argument("--choice", action="append")
    p.add_argument("--dart-sigma", type=float, default=0.03)
    p.add_argument("--repo-id", default="local/omx-stand-sim-arm_a")
    p.add_argument("--snapshot-dir", type=Path)
    p.add_argument("--gate", action=argparse.BooleanOptionalAction, default=True)
    a = p.parse_args(argv)
    preset = None if a.preset in ("none", "default", "") else a.preset
    receipt = generate(a.out, parse_seeds(a.seeds), a.sources, max_per_seed=a.max_per_seed, preset=preset,
                       choices=sites.parse_choices(a.choice), dart_sigma=a.dart_sigma, repo_id=a.repo_id,
                       snapshot_dir=a.snapshot_dir, run_gate=a.gate)
    print(json.dumps({k: receipt[k] for k in ("passed", "total", "gate") if k in receipt}, indent=1))
    return 0 if receipt["passed"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
