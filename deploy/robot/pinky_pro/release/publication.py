"""Verify an externally signed draft release before making it public."""
import argparse
import json
from pathlib import Path
import tempfile

from bundle import BundleError, release_id, stage_archive, verify_tree
from layout import Layout


def verify_publication(archive, key, version, revision):
    release_id(version)
    with tempfile.TemporaryDirectory(prefix="rosy-publication-") as work:
        staged = stage_archive(archive, Layout.rooted(Path(work)), key)
        manifest = verify_tree(staged, key)
        if manifest["release_id"] != version or manifest["git_revision"] != revision:
            raise BundleError("PUBLICATION_IDENTITY", "signed manifest does not match release tag and commit")
        return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("verify-publication",))
    parser.add_argument("archive", type=Path)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--git-revision", required=True)
    parser.add_argument("--public-key", required=True, type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    manifest = verify_publication(args.archive, args.public_key, args.release_id, args.git_revision)
    if args.json:
        print(json.dumps({
            "ok": True,
            "release_id": manifest["release_id"],
            "git_revision": manifest["git_revision"],
            "signed": True,
            "physical_acceptance": "HOLD",
        }))
    else:
        print(f"verified {manifest['release_id']} at {manifest['git_revision']}; physical acceptance remains HOLD")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
