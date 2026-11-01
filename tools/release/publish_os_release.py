#!/usr/bin/env python3
"""Publish a signed five-file OS release as an engineering prerelease.

Default is offline dry-run. --apply creates a draft, verifies uploaded SHA256
bindings, then opens only a prerelease. CMS/verity validation belongs to the
offline signing stage and the consumer; this tool verifies the Ed25519 binding.
No private key, rollout promotion, robot access, or activation is involved.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
for relative in ("deploy/robot/pinky_pro/release", "deploy/robot/pinky_pro/native"):
    sys.path.insert(0, str(ROOT / relative))
from os_update_manifest import verify_metadata
from os_update_rollout import verify as verify_rollout
from os_update_transport import bundle_assets

REPO = "robotics-team-1213/rosy-platform"
SIDECARS = ("os-update.json", "os-update.json.sig", "os-rollout.json", "os-rollout.json.sig")
CHUNK = 2 * 1024**2


def run_gh(argv):
    try:
        done = subprocess.run(argv, capture_output=True, timeout=1800)
    except (OSError, subprocess.TimeoutExpired):
        return 127, "", ""
    return done.returncode, done.stdout.decode("utf-8", "replace"), ""


def _plain(path, *, directory=False):
    try:
        info = path.lstat()
    except OSError:
        raise ValueError("OS publication input is missing or unreadable") from None
    if (path.is_symlink() or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
            or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))):
        raise ValueError("OS publication requires plain directories and regular files")
    return info


def _capture(source, target, limit):
    before = _plain(source)
    if not 0 < before.st_size <= limit:
        raise ValueError("OS asset exceeds its allowed size or is empty")
    digest, total = hashlib.sha256(), 0
    with source.open("rb") as incoming, target.open("xb") as outgoing:
        opened = os.fstat(incoming.fileno())
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino) or not stat.S_ISREG(opened.st_mode):
            raise ValueError("OS asset changed while being captured")
        while raw := incoming.read(min(CHUNK, limit - total + 1)):
            total += len(raw)
            if total > limit:
                raise ValueError("OS asset grew beyond its allowed size")
            digest.update(raw)
            outgoing.write(raw)
    return dict(size=total, digest="sha256:" + digest.hexdigest())


def _split_bundle(source, assets, expected_sha256):
    records, whole = {}, hashlib.sha256()
    with source.open("rb") as incoming:
        for name, size in assets:
            digest, remaining = hashlib.sha256(), size
            with (source.parent / name).open("xb") as outgoing:
                while remaining:
                    raw = incoming.read(min(CHUNK, remaining))
                    if not raw:
                        raise ValueError("OS captured bundle ended before its transport parts")
                    digest.update(raw)
                    whole.update(raw)
                    outgoing.write(raw)
                    remaining -= len(raw)
            records[name] = dict(size=size, digest="sha256:" + digest.hexdigest())
        if incoming.read(1) or whole.hexdigest() != expected_sha256:
            raise ValueError("OS captured bundle changed while creating transport parts")
    source.unlink()
    return records


def publish(directory, public_key, *, release_id, source_revision, apply=False, gh=None):
    """Validate and capture inputs, optionally publish an inert engineering prerelease."""
    directory = Path(directory).absolute()
    for parent in (*reversed(directory.parents), directory):
        _plain(parent, directory=True)
    gh = run_gh if gh is None else gh

    def command(*args):
        code, output, _ = gh(["gh", *args])
        if code:
            # gh stderr can contain credentials or signed redirect URLs.
            raise ValueError("OS publication GitHub operation failed; inspect the draft before retrying")
        return output

    def api(endpoint, *args):
        try:
            return json.loads(command("api", f"repos/{REPO}/{endpoint}", "--hostname", "github.com", *args))
        except (json.JSONDecodeError, UnicodeError):
            raise ValueError("OS publication received invalid GitHub JSON") from None

    def releases():
        pages = api("releases?per_page=100", "--paginate", "--slurp")
        if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
            raise ValueError("OS publication received an invalid release catalogue")
        rows = [row for page in pages for row in page]
        if any(not isinstance(row, dict) for row in rows):
            raise ValueError("OS publication received an invalid release catalogue")
        return rows

    with tempfile.TemporaryDirectory(prefix="rosy-os-publish-", dir=os.environ.get("ROSY_SCRATCH") or None) as temporary:
        work = Path(temporary)
        staged = work / "assets"
        staged.mkdir(mode=0o700)
        # Use one captured authority for both signatures, even if the original key changes.
        _capture(Path(public_key), work / "authority.pem", 16384)
        expected = {}
        for name in SIDECARS:
            expected[name] = _capture(directory / name, staged / name, 512 if name.endswith(".sig") else 16384)
        metadata = verify_metadata((staged / "os-update.json").read_bytes(),
            (staged / "os-update.json.sig").read_text(encoding="ascii").strip(), work / "authority.pem")
        policy = verify_rollout((staged / "os-rollout.json").read_bytes(),
            (staged / "os-rollout.json.sig").read_text(encoding="ascii").strip(), work / "authority.pem", metadata)
        if metadata["release_id"] != release_id or metadata["source_revision"] != source_revision:
            raise ValueError("OS release or source differs from the operator's expected identity")
        if policy["canary_ok"] or policy["withdrawn"]:
            raise ValueError("OS engineering publication requires an initial unpromoted rollout")
        bundle = metadata["bundle"]
        assets = bundle_assets(bundle)
        names = {*SIDECARS, bundle["filename"]}
        if {path.name for path in directory.iterdir()} != names:
            raise ValueError("OS publication requires exactly the signed five-asset set")
        captured = _capture(directory / bundle["filename"], staged / bundle["filename"], bundle["size_bytes"])
        if captured != dict(size=bundle["size_bytes"], digest="sha256:" + bundle["sha256"]):
            raise ValueError("OS bundle size or SHA256 differs from signed metadata")
        if len(assets) == 1:
            expected[bundle["filename"]] = captured
        else:
            expected.update(_split_bundle(staged / bundle["filename"], assets, bundle["sha256"]))
        names = set(expected)
        tag = "os-pinky-pro-" + release_id
        result = dict(tag=tag, source_revision=source_revision, assets=sorted(names), prerelease=True, applied=False)
        if not apply:
            return result

        def tag_refs():
            refs = api("git/matching-refs/tags/" + tag)
            if not isinstance(refs, list) or any(not isinstance(row, dict) for row in refs):
                raise ValueError("OS publication received invalid tag references")
            return [row for row in refs if row.get("ref") == "refs/tags/" + tag]

        if tag_refs() or any(row.get("tag_name") == tag for row in releases()):
            raise ValueError("OS release or tag already exists; refusing overwrite")
        created = api("releases", "--method", "POST", "-f", "tag_name=" + tag,
            "-f", "target_commitish=" + source_revision, "-f", "name=" + tag,
            "-f", "body=Engineering OS prerelease. Ed25519 asset binding checked; CMS/verity checks belong to signing and consumer.",
            "-F", "draft=true", "-F", "prerelease=true")
        identity = created.get("id") if isinstance(created, dict) else None
        if type(identity) is not int or identity < 1:
            raise ValueError("OS draft creation did not return a numeric release identity")

        def validate_draft(remote):
            if (not isinstance(remote, dict) or type(remote.get("id")) is not int or remote["id"] != identity
                    or remote.get("tag_name") != tag or remote.get("target_commitish") != source_revision
                    or remote.get("draft") is not True or remote.get("prerelease") is not True):
                raise ValueError("OS draft identity, source or publication state differs")

        validate_draft(created)
        endpoint = "releases/" + str(identity)
        for name in sorted(names):
            # Fix the upload host and numeric identity; never follow an API-supplied URL or re-resolve a tag.
            command("api", f"https://uploads.github.com/repos/{REPO}/{endpoint}/assets?name={name}",
                "--hostname", "github.com", "--method", "POST", "--input", str(staged / name),
                "-H", "Content-Type: application/octet-stream", "-H", "Content-Length: " + str(expected[name]["size"]))
        remote = api(endpoint)
        validate_draft(remote)
        assets = remote.get("assets")
        if (not isinstance(assets, list) or len(assets) != len(names)
                or any(not isinstance(item, dict) or not isinstance(item.get("name"), str) for item in assets)
                or {item.get("name") for item in assets} != names):
            raise ValueError("OS draft assets differ from the exact signed set")
        for item in assets:
            record = expected[item["name"]]
            if type(item.get("size")) is not int or item["size"] != record["size"] or item.get("digest") != record["digest"]:
                raise ValueError("OS draft asset size or SHA256 is absent or differs")
        # GitHub may defer creating a draft's tag until publication.
        for ref in tag_refs():
            obj = ref.get("object", {})
            if not isinstance(obj, dict) or obj.get("type") != "commit" or obj.get("sha") != source_revision:
                raise ValueError("OS draft tag no longer points to the signed source")
        api(endpoint, "--method", "PATCH", "-F", "draft=false", "-F", "prerelease=true")
        return dict(result, applied=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--public-key", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--apply", action="store_true", help="publish engineering prerelease after draft verification")
    args = parser.parse_args(argv)
    try:
        result = publish(args.directory, args.public_key, release_id=args.release_id,
                         source_revision=args.source_revision, apply=args.apply)
    except ValueError as error:
        print("OS publication refused: " + str(error), file=sys.stderr)
        return 1
    except OSError:
        print("OS publication refused; no promotion or robot activation was requested. Inspect any draft before retrying.", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
