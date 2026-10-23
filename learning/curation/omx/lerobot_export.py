"""Offline SIM export. This module never connects to a robot or uploads data."""

from __future__ import annotations

import argparse
from omx_output_paths import in_source_checkout
import importlib.metadata
import json
import shutil
from pathlib import Path
import sys
from uuid import UUID

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'contracts/learning/src'))
from rosy.contracts.learning.omx import validate_demonstration as validate_episode  # noqa: E402


LEROBOT_VERSION = "0.4.4"


def image_key(manifest: dict) -> str:
    """LeRobot image key named after the recorded camera (D-794 B: ``front`` today, ``wrist`` later)."""
    return "observation.images." + manifest["provenance"]["camera"]["name"]


def dataset_features(manifest: dict) -> dict:
    source = manifest["provenance"]
    names = source["joint_names"]
    features = {
        name: {"dtype": "float32", "shape": (len(names),), "names": names}
        for name in ("observation.state", "action")
    }
    camera = source["camera"]
    features[image_key(manifest)] = {
        "dtype": "video", "shape": (3, camera["height"], camera["width"]),
        "names": ["channels", "height", "width"],
    }
    features["action.duration_s"] = {"dtype": "float32", "shape": (1,), "names": ["seconds"]}
    if source.get("gripper_joint") is not None:
        features["action.gripper"] = {"dtype": "float32", "shape": (1,), "names": ["position_rad"]}
    for name in ("capture_time_ns", "state_time_ns", "received_wall_time_ns", "state_sequence"):
        features[f"source.{name}"] = {"dtype": "int64", "shape": (1,), "names": [name]}
    features["task.success"] = {"dtype": "int64", "shape": (1,), "names": ["source_task_success"]}
    return features


def iter_dataset_frames(episode: Path, validated: dict):
    manifest, samples = validated["manifest"], validated["samples"]
    first_ns = samples[0]["capture_time_ns"]
    for row in samples:
        with Image.open(Path(episode) / row["image_path"]) as image:
            pixels = np.array(image, dtype=np.uint8)
        frame = {
            "observation.state": np.array(row["observation.state"], dtype=np.float32),
            "action": np.array(row["action"], dtype=np.float32),
            "action.duration_s": np.array([row["duration_s"]], dtype=np.float32),
            image_key(manifest): pixels,
            "task.success": np.array([manifest["task_outcome"] == "success"], dtype=np.int64),
            "task": manifest["task"],
            "timestamp": (row["capture_time_ns"] - first_ns) / 1_000_000_000,
        }
        for destination, original in (("capture_time_ns", "capture_time_ns"),
                                      ("state_time_ns", "state_time_ns"),
                                      ("received_wall_time_ns", "received_at_ns"),
                                      ("state_sequence", "state_sequence")):
            frame[f"source.{destination}"] = np.array([row[original]], dtype=np.int64)
        if manifest["provenance"].get("gripper_joint") is not None:
            frame["action.gripper"] = np.array([row["action.gripper"]], dtype=np.float32)
        yield frame


def _readback(episode, validated, output, repo_id):
    if importlib.metadata.version('lerobot') != LEROBOT_VERSION:
        raise ValueError(f'readback requires lerobot=={LEROBOT_VERSION}')
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    manifest = validated['manifest']
    reader = LeRobotDataset(repo_id, root=output, video_backend='pyav', download_videos=False)
    info = reader.meta.info
    if (reader.num_frames != manifest['frame_count'] or reader.num_episodes != 1
            or info['fps'] != manifest['provenance']['fps'] or info['robot_type'] != manifest['robot_type']
            or info['codebase_version'] != 'v3.0'):
        raise ValueError('LeRobot readback frame/episode count or source rig differs')
    features = dataset_features(manifest)
    for key, expected in features.items():
        actual = info['features'].get(key, {})
        if any(actual.get(field) != (list(value) if field == 'shape' else value)
               for field, value in expected.items()):
            raise ValueError('LeRobot source feature metadata differs')
    max_image_error = 0.0
    for index, expected in enumerate(iter_dataset_frames(episode, validated)):
        actual = reader[index]
        for key, feature in features.items():
            if key == image_key(manifest):
                pixels = actual[key].numpy().transpose(1, 2, 0) * 255
                if pixels.shape != expected[key].shape:
                    raise ValueError('video readback dimensions differ')
                error = float(np.abs(pixels - expected[key]).mean())
                max_image_error = max(max_image_error, error)
                if error > 8:
                    raise ValueError('video readback differs beyond lossy encoding tolerance')
            elif feature['dtype'] == 'int64':
                np.testing.assert_array_equal(actual[key].numpy(), expected[key])
            else:
                np.testing.assert_allclose(actual[key].numpy(), expected[key], rtol=1e-6, atol=1e-7)
        np.testing.assert_allclose(float(actual['timestamp']), index / manifest['provenance']['fps'], atol=1e-6)
    return dict(verified_frames=reader.num_frames, video_mean_absolute_error_max=max_image_error)


def verify_export(root: Path, repo_id: str) -> dict:
    """Reopen a preserved export against its original clocks, labels, RGB and task proof."""
    root = Path(root).resolve()
    report = json.loads((root/'rosy_export.json').read_bytes())
    episode_id = report['episode_id']
    if (str(UUID(episode_id)) != episode_id or report['status'] != 'verified'
            or report['lerobot_version'] != LEROBOT_VERSION or report['dataset_version'] != 'v3.0'):
        raise ValueError('verified OMX export identity and pinned dataset version required')
    episode = root/'rosy_provenance'/episode_id
    validated = validate_episode(episode)
    manifest = validated['manifest']
    if any(report[key] != manifest[key] for key in ('episode_id', 'robot_type', 'action_semantics')):
        raise ValueError('export report differs from original demonstration')
    proof = root/'rosy_sim_truth/truth.json'
    judge = report['task_outcome_judge']
    if judge == 'sim_ground_truth':
        from rosy.contracts.learning.sim_object_truth import validate_truth
        validate_truth(proof, validated, source=episode)
    elif judge != 'operator' or proof.exists():
        raise ValueError('export judge contradicts independent SIM proof')
    actual = _readback(episode, validated, root, repo_id)
    if report['verified_frames'] != actual['verified_frames']:
        raise ValueError('export report frame count differs from reader')
    return dict(status='verified', episode_id=episode_id, task_outcome_judge=judge, **actual)


def export_episode(episode: Path, output: Path, repo_id: str, *, sim_ground_truth=None) -> dict:
    episode, output = Path(episode).resolve(), Path(output).resolve()
    validated = validate_episode(episode)
    if output.exists() or output.is_relative_to(episode) or episode.is_relative_to(output):
        raise ValueError("export requires a new directory separate from the source episode")
    if in_source_checkout(output):
        raise ValueError("export output belongs outside the source checkout")
    truth = None
    if sim_ground_truth is not None:
        from rosy.contracts.learning.sim_object_truth import validate_truth
        truth = validate_truth(sim_ground_truth, validated, source=episode)
    version = importlib.metadata.version("lerobot")
    if version != LEROBOT_VERSION:
        raise ValueError(f"export requires lerobot=={LEROBOT_VERSION}; found {version}")
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    manifest = validated["manifest"]
    report = {"status": "failed", "lerobot_version": version, "episode_id": manifest["episode_id"],
              "robot_type": manifest["robot_type"], "action_semantics": manifest["action_semantics"],
              "task_outcome_judge": "sim_ground_truth" if truth else "operator"}
    dataset = None
    try:
        dataset = LeRobotDataset.create(
            repo_id=repo_id, fps=manifest["provenance"]["fps"], features=dataset_features(manifest),
            root=output, robot_type=manifest["robot_type"], use_videos=True, video_backend="pyav",
            vcodec="h264", batch_encoding_size=1,
        )
        for frame in iter_dataset_frames(episode, validated):
            # 0.4.4 validates timestamp as an extra feature before its own pop.
            # Keep exact clocks in int64 features; the video axis uses index/fps.
            frame.pop("timestamp")
            dataset.add_frame(frame)
        dataset.save_episode(parallel_encoding=False)
        dataset.finalize()
        dataset = None
        readback = _readback(episode, validated, output, repo_id)
        shutil.copytree(episode, output / "rosy_provenance" / manifest["episode_id"])
        if truth is not None:
            for relative, payload in {'truth.json': Path(sim_ground_truth).read_bytes(), **truth['payloads']}.items():
                target = output/'rosy_sim_truth'/relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)
            validate_truth(output/'rosy_sim_truth/truth.json', validated, source=episode)
        report.update(status="verified", dataset_version="v3.0", **readback)
        return report
    finally:
        if dataset is not None:
            dataset.finalize()
        if output.is_dir():
            (output / "rosy_export.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("episode", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--repo-id", default="rosy-local/omx-sim")
    parser.add_argument('--sim-ground-truth', type=Path)
    args = parser.parse_args()
    print(json.dumps(export_episode(args.episode, args.output, args.repo_id,
                                    sim_ground_truth=args.sim_ground_truth), indent=2))


if __name__ == "__main__":
    main()
