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
import re
import uuid

ROOT = Path(__file__).resolve().parents[2]
for relative in ("deploy/robot/pinky_pro/release", "deploy/robot/pinky_pro/native"):
    sys.path.insert(0, str(ROOT / relative))
from os_state_io import _write_atomic
from os_update_manifest import verify_metadata
from os_update_rollout import _shape as validate_rollout, verify as verify_rollout
from os_update_transport import bundle_assets
from signing import sign_checksums, verify_signature

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


def publish(directory, public_key, *, release_id, source_revision, apply=False, gh=None,
            publication_only=False, open_release=False, transaction=None, journal=None):
    """Publish verified assets; only an explicitly closed rollout is publication-only.

    A supplied durable transaction owns one draft by nonce and numeric ID. The
    journal callback must persist each checkpoint before GitHub is mutated.
    """
    if publication_only and open_release:
        raise ValueError("OS publication-only rollout cannot open a release")
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
        if policy["withdrawn"] or (not open_release and policy["canary_ok"]):
            raise ValueError("OS engineering publication requires an initial unpromoted rollout")
        if publication_only and policy["canary"]:
            raise ValueError("OS publication-only rollout must authorize no canary")
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
        result = dict(tag=tag, source_revision=source_revision, assets=sorted(names),
                      prerelease=not open_release, applied=False)
        if not apply:
            return result

        def tag_refs():
            refs = api("git/matching-refs/tags/" + tag)
            if not isinstance(refs, list) or any(not isinstance(row, dict) for row in refs):
                raise ValueError("OS publication received invalid tag references")
            return [row for row in refs if row.get("ref") == "refs/tags/" + tag]

        resumable = transaction is not None
        checkpoint = dict(transaction) if resumable else {"nonce": uuid.uuid4().hex}
        if (not isinstance(checkpoint.get("nonce"), str) or not re.fullmatch("[0-9a-f]{32}", checkpoint["nonce"])
                or resumable and not callable(journal)):
            raise ValueError("OS publication resume requires a durable nonce journal")
        bindings = dict(tag=tag, source_revision=source_revision, assets=expected)
        if any(key in checkpoint and checkpoint[key] != value for key, value in bindings.items()):
            raise ValueError("OS publication assets or source changed since the durable checkpoint")
        checkpoint.update(bindings)

        def record(**values):
            checkpoint.update(values)
            if resumable:
                journal(dict(checkpoint))

        # This includes every transport-part hash and the nonce before draft POST.
        record()
        marker = "<!-- rosy-os-publication:" + checkpoint["nonce"] + " -->"
        existing = [row for row in releases() if row.get("tag_name") == tag]
        if len(existing) > 1 or not resumable and (existing or tag_refs()):
            raise ValueError("OS release or tag already exists; refusing overwrite")
        identity = checkpoint.get("release_id")
        if identity is not None and (type(identity) is not int or identity < 1):
            raise ValueError("OS resume has an invalid numeric release identity")

        def validate(remote, *, draft=None, prerelease=None):
            if prerelease is None:
                allowed_pre = (True,) if (remote.get("draft") is True or not open_release) else (True, False)
            else:
                allowed_pre = (prerelease,)
            if (not isinstance(remote, dict) or type(remote.get("id")) is not int or remote["id"] != identity
                    or remote.get("tag_name") != tag or remote.get("target_commitish") != source_revision
                    or type(remote.get("draft")) is not bool or remote.get("prerelease") not in allowed_pre
                    or draft is not None and remote["draft"] is not draft
                    or marker not in remote.get("body", "")):
                raise ValueError("OS draft identity, source or publication state differs")

        if identity is not None:
            remote = api("releases/" + str(identity))
            validate(remote)
        elif existing:
            remote = existing[0]
            identity = remote.get("id")
            if type(identity) is not int or identity < 1:
                raise ValueError("OS existing draft has no numeric identity")
            validate(remote)
            record(release_id=identity)
        else:
            if tag_refs():
                raise ValueError("OS tag exists without an owned release; refusing adoption")
            remote = api("releases", "--method", "POST", "-f", "tag_name=" + tag,
                "-f", "target_commitish=" + source_revision, "-f", "name=" + tag,
                "-f", "body=Engineering OS prerelease. CMS/verity checks belong to signing and consumer.\n" + marker,
                "-F", "draft=true", "-F", "prerelease=true")
            identity = remote.get("id") if isinstance(remote, dict) else None
            if type(identity) is not int or identity < 1:
                raise ValueError("OS draft creation did not return a numeric release identity")
            validate(remote, draft=True)
            record(release_id=identity)
        endpoint = "releases/" + str(identity)

        def checked_assets(remote, *, complete):
            items = remote.get("assets", [])
            if (not isinstance(items, list) or any(not isinstance(item, dict) or not isinstance(item.get("name"), str) for item in items)
                    or len({item["name"] for item in items}) != len(items)
                    or not {item["name"] for item in items} <= names
                    or complete and {item["name"] for item in items} != names):
                raise ValueError("OS draft assets differ from the exact signed set")
            for item in items:
                record = expected[item["name"]]
                if type(item.get("size")) is not int or item["size"] != record["size"] or item.get("digest") != record["digest"]:
                    raise ValueError("OS draft asset size or SHA256 is absent or differs")
            return {item["name"]: item for item in items}

        remote = api(endpoint)
        validate(remote)
        present = checked_assets(remote, complete=not remote["draft"])
        if remote["draft"]:
            for name in sorted(names - present.keys()):
                # Never clobber: partial matching uploads can resume, foreign bytes cannot.
                command("api", f"https://uploads.github.com/repos/{REPO}/{endpoint}/assets?name={name}",
                    "--hostname", "github.com", "--method", "POST", "--input", str(staged / name),
                    "-H", "Content-Type: application/octet-stream", "-H", "Content-Length: " + str(expected[name]["size"]))
        remote = api(endpoint)
        validate(remote)
        checked_assets(remote, complete=True)
        # GitHub may defer creating a draft's tag until publication.
        for ref in tag_refs():
            obj = ref.get("object", {})
            if not isinstance(obj, dict) or obj.get("type") != "commit" or obj.get("sha") != source_revision:
                raise ValueError("OS draft tag no longer points to the signed source")
        if remote["draft"] or (open_release and remote.get("prerelease") is not False):
            api(endpoint, "--method", "PATCH", "-F", "draft=false",
                "-F", "prerelease=" + ("false" if open_release else "true"))
        # A successful PATCH response is insufficient (it can be lost or stale).
        final = api(endpoint)
        validate(final, draft=False, prerelease=not open_release)
        assets = checked_assets(final, complete=True)
        refs = tag_refs()
        if len(refs) != 1 or refs[0].get("object", {}).get("type") != "commit" or refs[0]["object"].get("sha") != source_revision:
            raise ValueError("OS public tag does not resolve to the signed source")
        readback = {}
        for name in SIDECARS:
            asset_id = assets[name].get("id")
            if type(asset_id) is not int or asset_id < 1:
                raise ValueError("OS public sidecar lacks a numeric asset identity")
            raw = command("api", f"repos/{REPO}/releases/assets/{asset_id}", "--hostname", "github.com",
                          "-H", "Accept: application/octet-stream").encode("utf-8")
            if len(raw) != expected[name]["size"] or "sha256:" + hashlib.sha256(raw).hexdigest() != expected[name]["digest"]:
                raise ValueError("OS public sidecar bytes differ from the signed checkpoint")
            readback[name] = raw
        verified = verify_metadata(readback["os-update.json"], readback["os-update.json.sig"].decode("ascii").strip(), work / "authority.pem")
        closed = verify_rollout(readback["os-rollout.json"], readback["os-rollout.json.sig"].decode("ascii").strip(), work / "authority.pem", verified)
        if publication_only and (closed["canary"] or closed["canary_ok"] or closed["withdrawn"]):
            raise ValueError("OS public rollout authorizes a device")
        record(published=True)
        return dict(result, applied=True, prerelease=final["prerelease"], github_release_id=checkpoint["release_id"])


def open_rollout(directory, private_key, public_key, *, release_id, canary=None,
                 promote=False, open_release=False, apply=False, gh=None):
    """Re-sign os-rollout.json locally and optionally update an existing GitHub release rollout."""
    if os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
        raise ValueError("OS rollout signing must not run in hosted CI")
    directory = Path(directory).absolute()
    private_key = Path(private_key).absolute()
    for parent in (*reversed(directory.parents), directory):
        _plain(parent, directory=True)
    for parent in (*reversed(private_key.parents), private_key):
        info = _plain(parent, directory=(parent != private_key))
    if info.st_nlink != 1 or any(private_key.is_relative_to(p) for p in (directory,)):
        raise ValueError("private signing key must remain single-link and outside release directories")
    if os.name == "nt":
        try:
            from tools.release.os_tools_vm import _windows_private
        except ImportError:
            from os_tools_vm import _windows_private
        _windows_private(private_key)
    elif info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600:
        raise ValueError("private signing key permissions or owner differ")
    gh = run_gh if gh is None else gh

    with tempfile.TemporaryDirectory(prefix="rosy-os-rollout-", dir=os.environ.get("ROSY_SCRATCH") or None) as temporary:
        work = Path(temporary)
        _capture(Path(public_key), work / "authority.pem", 16384)
        old_raw = (directory / "os-rollout.json").read_bytes()
        old_sig = (directory / "os-rollout.json.sig").read_bytes()
        meta_raw = (directory / "os-update.json").read_bytes()
        meta_sig = (directory / "os-update.json.sig").read_text(encoding="ascii").strip()
        metadata = verify_metadata(meta_raw, meta_sig, work / "authority.pem")
        if metadata["release_id"] != release_id:
            raise ValueError("OS rollout release identity differs")
        policy = verify_rollout(old_raw, old_sig.decode("ascii").strip(), work / "authority.pem", metadata)
        if policy["withdrawn"]:
            raise ValueError("a withdrawn OS release cannot be opened again")
        if canary is not None:
            policy["canary"] = list(canary)
        if promote:
            policy["canary_ok"] = True
        validate_rollout(policy)
        new_raw = (json.dumps(policy, sort_keys=True, indent=2) + "\n").encode("utf-8")
        new_sig = (sign_checksums(new_raw, private_key) + "\n").encode("ascii")
        if verify_signature(new_raw, new_sig.decode("ascii").strip(), work / "authority.pem"):
            raise ValueError("offline Ed25519 signing key does not match distribution authority")
        verify_rollout(new_raw, new_sig.decode("ascii").strip(), work / "authority.pem", metadata)
        try:
            _write_atomic(directory / "os-rollout.json", new_raw, 0o644)
            _write_atomic(directory / "os-rollout.json.sig", new_sig, 0o644)
        except BaseException:
            _write_atomic(directory / "os-rollout.json", old_raw, 0o644)
            _write_atomic(directory / "os-rollout.json.sig", old_sig, 0o644)
            raise
        if not apply:
            return dict(tag="os-pinky-pro-" + release_id, rollout=policy, applied=False)

        def command(*args):
            code, output, _ = gh(["gh", *args])
            if code:
                raise ValueError("OS rollout GitHub operation failed")
            return output

        def api(endpoint, *args):
            try:
                return json.loads(command("api", f"repos/{REPO}/{endpoint}", "--hostname", "github.com", *args))
            except (json.JSONDecodeError, UnicodeError):
                raise ValueError("OS rollout received invalid GitHub JSON") from None

        tag = "os-pinky-pro-" + release_id
        remote = api("releases/tags/" + tag)
        identity = remote.get("id")
        source_revision = metadata["source_revision"]
        if (not isinstance(remote, dict) or type(identity) is not int or identity < 1
                or remote.get("tag_name") != tag or remote.get("target_commitish") != source_revision):
            raise ValueError("OS remote release identity or source differs")
        refs = api("git/matching-refs/tags/" + tag)
        exact_refs = [r for r in refs if isinstance(r, dict) and r.get("ref") == "refs/tags/" + tag] if isinstance(refs, list) else []
        if len(exact_refs) != 1 or exact_refs[0].get("object", {}).get("type") != "commit" or exact_refs[0]["object"].get("sha") != source_revision:
            raise ValueError("OS remote tag does not resolve to the signed source")
        by_name = {item.get("name"): item for item in remote.get("assets", []) if isinstance(item, dict)}
        bundle = metadata["bundle"]
        bundle_parts = dict(bundle_assets(bundle))
        required_assets = {"os-update.json", "os-update.json.sig", *bundle_parts}
        if not required_assets <= set(by_name):
            raise ValueError("OS remote release is missing verified non-rollout assets")
        for req_name in sorted(required_assets):
            item = by_name[req_name]
            if type(item.get("size")) is not int or item["size"] < 1 or not isinstance(item.get("digest"), str) or not item["digest"].startswith("sha256:"):
                raise ValueError("OS remote non-rollout asset lacks size or digest")
            if req_name in bundle_parts and item["size"] != bundle_parts[req_name]:
                raise ValueError("OS remote bundle asset size differs")
            if len(bundle_parts) == 1 and req_name == bundle["filename"] and item["digest"] != "sha256:" + bundle["sha256"]:
                raise ValueError("OS remote bundle digest differs")
        meta_remote = by_name["os-update.json"]
        if meta_remote["digest"] != "sha256:" + hashlib.sha256(meta_raw).hexdigest() or meta_remote["size"] != len(meta_raw):
            raise ValueError("OS remote metadata differs from local signed metadata")
        endpoint = f"releases/{identity}"
        staged = {"os-rollout.json": new_raw, "os-rollout.json.sig": new_sig}
        for name, raw in staged.items():
            existing_asset = by_name.get(name)
            if existing_asset and type(existing_asset.get("id")) is int:
                command("api", f"repos/{REPO}/releases/assets/{existing_asset['id']}",
                        "--hostname", "github.com", "--method", "DELETE")
            file_path = work / name
            file_path.write_bytes(raw)
            command("api", f"https://uploads.github.com/repos/{REPO}/{endpoint}/assets?name={name}",
                "--hostname", "github.com", "--method", "POST", "--input", str(file_path),
                "-H", "Content-Type: application/octet-stream", "-H", "Content-Length: " + str(len(raw)))
        if open_release and remote.get("prerelease") is not False:
            api(endpoint, "--method", "PATCH", "-F", "draft=false", "-F", "prerelease=false")
        final = api(endpoint)
        if open_release and final.get("prerelease") is not False:
            raise ValueError("OS remote release remained prerelease")
        assets = {item.get("name"): item for item in final.get("assets", []) if isinstance(item, dict)}
        readback = {}
        for name, expected_raw in staged.items():
            item = assets.get(name) or {}
            asset_id = item.get("id")
            if (type(asset_id) is not int or asset_id < 1 or item.get("size") != len(expected_raw)
                    or item.get("digest") != "sha256:" + hashlib.sha256(expected_raw).hexdigest()):
                raise ValueError("OS remote rollout asset differs after upload")
            fetched = command("api", f"repos/{REPO}/releases/assets/{asset_id}", "--hostname", "github.com",
                              "-H", "Accept: application/octet-stream").encode("utf-8")
            if fetched != expected_raw:
                raise ValueError("OS remote rollout bytes differ after upload")
            readback[name] = fetched
        verified = verify_rollout(readback["os-rollout.json"], readback["os-rollout.json.sig"].decode("ascii").strip(),
                                  work / "authority.pem", metadata)
        return dict(tag=tag, rollout=verified, prerelease=final.get("prerelease"), applied=True)


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
