"""Publish a built dataset folder into the store (D-373 decision 8); HF is optional.

publish.py <dataset_dir> [--store <path>] [--name <name>] [--hf <org/name> [--tag ds-...]]

Frames listed in manifest.json are sharded into images|masks/shard_0000/, ... of <= 1000
frames each, and manifest.json paths are rewritten to match. The sharded copy goes to
<store>/datasets/<name>/<content_sha>/ (never overwritten) and the line
`dataset: store:<name>@<content_sha>` is printed: that ref is what the trainer enters.
--store defaults to `store` in the rosy_ml config. --hf also (or only) uploads to a private
HF dataset repo; its token comes from HF_TOKEN or the huggingface-cli login cache."""

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

    The manifest's frame order drives the sharding: frame k goes to shard_{k // size:04d}, and
    its image and mask share that shard. Each file keeps its session in the name so equal frame
    indexes from different sessions stay unique: a base name already starting with
    "<session>__" is kept as is, otherwise the path below its top folder is joined with "__"
    (e.g. images/s1/000001.jpg -> s1__000001.jpg)."""
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


def _configured_store():
    """`store` from the rosy_ml config, if there is one (no other key is needed here)."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import rosy_ml
    path = rosy_ml.config_path()
    if not path.is_file():
        return None
    import yaml
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return doc.get("store") if isinstance(doc, dict) else None


def _hf_publish(staging: Path, repo: str, tag) -> str:
    from huggingface_hub import HfApi  # lazy: optional backend

    api = HfApi()
    api.create_repo(repo, repo_type="dataset", private=True, exist_ok=True)
    info = api.upload_folder(folder_path=str(staging), repo_id=repo,
                             repo_type="dataset", commit_message="dataset publish")
    if tag:
        api.create_tag(repo, tag=tag, revision=info.oid, repo_type="dataset")
    return info.oid


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dataset_dir", type=Path)
    ap.add_argument("--store", help="store folder (default: `store` in the rosy_ml config)")
    ap.add_argument("--name", help="dataset name in the store (default: the folder name)")
    ap.add_argument("--hf", metavar="ORG/NAME", help="optional: also upload to this HF repo")
    ap.add_argument("--tag", help="HF tag (with --hf)")
    ap.add_argument("--shard-size", type=int, default=1000)
    args = ap.parse_args(argv)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import store as store_mod

    name = args.name or Path(args.dataset_dir).resolve().name
    if not store_mod.safe_name(name):
        ap.error(f"--name {name!r}: expected [A-Za-z0-9][A-Za-z0-9._-]*")
    root = args.store or _configured_store()
    if not root and not args.hf:
        print("refused: no store: pass --store <path> or set `store` with rosy_ml init "
              "(or --hf <repo> for the optional HF backend)", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory() as tmp:  # sharded copy; keep it off F: via TEMP
        staging = Path(tmp) / name
        staging.mkdir()
        _stage(args.dataset_dir, staging, args.shard_size)
        if root:
            path, sha = store_mod.Store(root).put_dataset(staging, name)
            print(f"stored: {path}")
            print(f"dataset: store:{name}@{sha}")
        if args.hf:
            print(f"hf: {args.hf}@{_hf_publish(staging, args.hf, args.tag)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
