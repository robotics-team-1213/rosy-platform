"""Which datasets a two-arm round trains on: its own sim parts plus `--extra-dataset` ones (real recordings, older sim), in what share.

A weight is a whole number of copies: an extra dataset with weight 3 is aggregated three times (LeRobot has no per-dataset sampling weight in
`lerobot-train`), so its frames are 3x of the mix. Datasets that differ in any feature, fps or robot type are refused before aggregation."""
import json
from pathlib import Path

STAMPS = ("fps", "robot_type")


def _info(root):
    try:
        return json.loads((Path(root) / "meta/info.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"{root} is not a LeRobot dataset ({type(error).__name__}: {error})") from error


def _goal_mode(root):
    """The goal mode a dataset's sibling `<name>.steps.json` declares (collect and the real export both write it), else unknown."""
    path = Path(root).parent / f"{Path(root).name}.steps.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("goal_mode")
    except (OSError, ValueError):
        return None


def require_same_features(roots):
    """Raise ValueError naming the first dataset whose features, fps, robot type or goal mode differ from the first one's."""
    roots = [Path(r) for r in roots]
    ref_info, ref_mode = _info(roots[0]), _goal_mode(roots[0])
    for root in roots[1:]:
        info = _info(root)
        for key in STAMPS:
            if info.get(key) != ref_info.get(key):
                raise ValueError(f"{root} has {key} {info.get(key)!r}, {roots[0]} has {ref_info.get(key)!r}")
        have, want = info["features"], ref_info["features"]
        if have != want:
            names = sorted(set(have) ^ set(want)) or sorted(k for k in want if have[k] != want[k])
            raise ValueError(f"{root} features differ from {roots[0]} in {names}: {[(k, have.get(k), want.get(k)) for k in names][:3]}")
        mode = _goal_mode(root)
        if ref_mode is not None and mode is not None and mode != ref_mode:
            raise ValueError(f"{root} goal mode {mode!r} differs from {roots[0]} {ref_mode!r}")


def weighted_roots(parts, extras, weights=None):
    """(roots to aggregate, {root: {weight, frames, share}}): the sim parts once, each extra `weight` times; features checked first."""
    extras = [Path(p) for p in extras or []]
    weights = [int(w) for w in weights or []]
    if len(weights) not in (0, 1, len(extras)) or any(w < 1 for w in weights):
        raise ValueError(f"--extra-dataset-weight takes whole numbers >= 1, one for all or one per --extra-dataset ({len(extras)}); got {weights}")
    weights = (weights * len(extras) if len(weights) == 1 else weights) or [1] * len(extras)
    parts = [Path(p) for p in parts]
    if parts + extras:
        require_same_features(parts + extras)
    roots = parts + [root for root, w in zip(extras, weights) for _ in range(w)]
    frames = {str(root): (1 if root in parts else weights[extras.index(root)]) * _info(root)["total_frames"] for root in dict.fromkeys(parts + extras)}
    total = sum(frames.values()) or 1
    mix = {key: dict(weight=1 if Path(key) in parts else weights[extras.index(Path(key))], frames=n, share=round(n / total, 4)) for key, n in frames.items()}
    return roots, mix
