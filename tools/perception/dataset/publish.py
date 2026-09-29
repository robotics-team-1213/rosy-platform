"""Publish a built dataset folder to a private Hugging Face dataset repo.

publish.py <dataset_dir> --repo <org/name> [--tag ds-YYYY.MM.DD]

Frames listed in manifest.json are sharded into images|masks/shard_0000/, ... of <= 1000
frames each, and manifest.json paths are rewritten to match.
The token comes from HF_TOKEN or the huggingface-cli login cache, never from a file here."""

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path


def shard_paths(paths, size: int = 1000) -> list[list]:
    """Sorted paths split into consecutive chunks of at most `size`."""
    ordered = sorted(paths, key=str)
    return [ordered[i:i + size] for i in range(0, len(ordered), size)]


def _stage(dataset_dir: Path, staging: Path, size: int) -> None:
    """Copy frames listed in manifest.json into shard_NNNN folders and rewrite their paths.

    Frame k goes to shard_{k // size:04d}; image and mask share the shard. File names keep the
    session (already-prefixed names are kept as is) so equal frame indexes from different sessions stay unique."""
    dataset_dir = Path(dataset_dir)
    manifest = json.loads((dataset_dir / "manifest.json").read_text(encoding="utf-8"))
    frames = []
    for k, frame in enumerate(manifest["frames"]):
        shard = f"shard_{k // size:04d}"
        new = dict(frame)
        for key, kind in (("image", "images"), ("mask", "masks")):
            src = dataset_dir / frame[key]
            if not src.is_file():
                raise FileNotFoundError(f"frame {k}: {key} missing: {frame[key]}")
            base = Path(frame[key]).name
            if base.startswith(f"{frame['session']}__"):
                name = base
            else:
                name = "__".join(Path(frame[key]).parts[1:])
            rel = f"{kind}/{shard}/{name}"
            (staging / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, staging / rel)
            new[key] = rel
        frames.append(new)
    manifest["frames"] = frames
    (staging / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dataset_dir", type=Path)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--tag")
    ap.add_argument("--shard-size", type=int, default=1000)
    args = ap.parse_args(argv)
    from huggingface_hub import HfApi  # lazy

    api = HfApi()
    api.create_repo(args.repo, repo_type="dataset", private=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:  # sharded copy; keep it off F: via TEMP
        staging = Path(tmp)
        _stage(args.dataset_dir, staging, args.shard_size)
        info = api.upload_folder(folder_path=str(staging), repo_id=args.repo,
                                 repo_type="dataset", commit_message="dataset publish")
    sha = info.oid
    if args.tag:
        api.create_tag(args.repo, tag=args.tag, revision=sha, repo_type="dataset")
    print(sha)
    return 0


if __name__ == "__main__":
    sys.exit(main())
