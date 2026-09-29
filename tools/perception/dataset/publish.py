"""Publish a built dataset folder to a private Hugging Face dataset repo.

publish.py <dataset_dir> --repo <org/name> [--tag ds-YYYY.MM.DD]

images/ and masks/ are sharded into shard_0000/, shard_0001/, ... of <= 1000 files.
The token comes from HF_TOKEN or the huggingface-cli login cache, never from a file here."""

import argparse
import shutil
import sys
import tempfile
from pathlib import Path


def shard_paths(paths, size: int = 1000) -> list[list]:
    """Sorted paths split into consecutive chunks of at most `size`."""
    ordered = sorted(paths, key=str)
    return [ordered[i:i + size] for i in range(0, len(ordered), size)]


def _stage(dataset_dir: Path, staging: Path, size: int) -> None:
    for item in dataset_dir.iterdir():
        if item.is_file():
            shutil.copy2(item, staging / item.name)
    for sub in ("images", "masks"):
        src = dataset_dir / sub
        if not src.is_dir():
            continue
        for n, shard in enumerate(shard_paths([p for p in src.iterdir() if p.is_file()], size)):
            dst = staging / sub / f"shard_{n:04d}"
            dst.mkdir(parents=True, exist_ok=True)
            for p in shard:
                shutil.copy2(p, dst / p.name)


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
