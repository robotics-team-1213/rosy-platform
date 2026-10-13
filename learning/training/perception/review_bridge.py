"""Forward immutable Pinky review exports to the approved model PC, key-only.

review_bridge.py config.json --out STATE [--once]
Config: source, peer, remote_reviews, interval_s, max_attempts. No training/approval.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tarfile
import time
from urllib.parse import urlparse
from urllib.request import urlopen

from job_state import Job, JobError, receipt
from learning_cycle import verified_export

SSH_OPTIONS = ["-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes", "-o",
               "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=5"]


def peer_target(config):
    peer, target = config["peer"], config["remote_reviews"]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", peer):
        raise JobError("invalid approved SSH peer alias")
    if not re.fullmatch(r"/[A-Za-z0-9/_.-]+", target) or ".." in Path(target).parts:
        raise JobError("remote review root must be a safe absolute path")
    return peer, target


def export_files(folder):
    """Transfer v2's outer seal, not only the legacy object-review manifest."""
    folder = Path(folder)
    if (folder / "review-contract.json").exists():
        doc = json.loads((folder / "review-contract.json").read_bytes())
        return sorted({"review-contract.json", "AUTHORITY_COMPLETE",
                       *(item["path"] for item in doc["files"])})
    doc = json.loads((folder / "manifest.json").read_bytes())
    return sorted({"manifest.json", "COMPLETE", *(item["path"] for item in doc["files"])})


def fetch_current(config):
    endpoint = config["authority"]["endpoint"]
    parsed = urlparse(endpoint)
    if (parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost", "::1")
            or parsed.path != "/api/decisions" or parsed.query or parsed.fragment
            or parsed.username or parsed.password):
        raise JobError("configured local current-decisions endpoint required")
    with urlopen(endpoint, timeout=5) as response:
        # Redirects must not silently move the configured authority off localhost.
        if response.geturl() != endpoint:
            raise JobError("current authority redirect refused")
        raw = response.read(16 * 1024 * 1024 + 1)
    if len(raw) > 16 * 1024 * 1024:
        raise JobError("current authority response too large")
    return json.loads(raw)


def publish_current(snapshot, config, out):
    """Replace a receiver snapshot atomically; a failed fetch delivers unavailable."""
    peer, target = peer_target(config)
    raw = (json.dumps(snapshot, sort_keys=True, allow_nan=False) + "\n").encode()
    digest = hashlib.sha256(raw).hexdigest()
    local = Path(out) / "current-upload.json"
    local.write_bytes(raw)
    incoming = target + "/.current-upload.json"
    subprocess.run(["scp", *SSH_OPTIONS, str(local), peer + ":" + incoming],
                   check=True, capture_output=True, timeout=30)
    script = r'''
import hashlib,json,pathlib,os
root=pathlib.Path(ROOT);incoming=root/'.current-upload.json'
assert not incoming.is_symlink() and incoming.is_file()
raw=incoming.read_bytes();assert hashlib.sha256(raw).hexdigest()==DIGEST
doc=json.loads(raw);assert doc['schema']=='rosy.pinky-review-current-delivery/1'
assert doc['workspace_id']==WORKSPACE
folder=root/'.authority';assert not folder.is_symlink();folder.mkdir(exist_ok=True)
target=folder/'current.json';assert not target.is_symlink()
if target.exists():
    previous_raw=target.read_bytes();previous=json.loads(previous_raw);assert previous['workspace_id']==doc['workspace_id']
    old,new=previous.get('revision'),doc.get('revision')
    if old:
        assert new is not None  # An unavailable sender with lost history must not erase the high-water mark.
        assert new['generation']>=old['generation']
        if new['generation']==old['generation']:assert new['decision_sha256']==old['decision_sha256']
partial=folder/'.current.tmp';assert not partial.is_symlink()
with partial.open('wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
os.replace(partial,target)
print(json.dumps({'available':doc['available'],'snapshot_sha':DIGEST}))
'''.replace("ROOT", repr(target)).replace("DIGEST", repr(digest)).replace(
        "WORKSPACE", repr(config["authority"]["workspace_id"]))
    result = subprocess.run(["ssh", *SSH_OPTIONS, peer, "python3 -"], input=script,
                            capture_output=True, text=True, encoding="utf-8", timeout=30, check=True)
    receipt_value = json.loads(result.stdout)
    if receipt_value.get("snapshot_sha") != digest or receipt_value.get("available") is not snapshot["available"]:
        raise JobError("current authority remote receipt differs")
    return receipt_value


def publish(folder, digest, config, out):
    from job_state import sha
    peer, target = peer_target(config)
    archive = Path(out) / (digest + ".tar")
    files = export_files(folder)
    with tarfile.open(archive, "w") as tar:
        for name in files:
            tar.add(folder / name, arcname=name, recursive=False)
    remote_archive = target + "/.incoming-" + digest + ".tar"
    # The remote root is provisioned by the producer; no root command or secret copy.
    subprocess.run(["scp", *SSH_OPTIONS, str(archive), peer + ":" + remote_archive],
                   check=True, capture_output=True, timeout=60)
    script = r'''
import hashlib,json,pathlib,tarfile
root=pathlib.Path(ROOT);archive=root/('.incoming-'+DIGEST+'.tar')
assert hashlib.sha256(archive.read_bytes()).hexdigest()==ARCHIVE_SHA
target=root/('pinky-web-export-'+DIGEST)
with tarfile.open(archive) as tar:
    members=tar.getmembers()
    assert all(m.isfile() and not pathlib.PurePosixPath(m.name).is_absolute() and '..' not in pathlib.PurePosixPath(m.name).parts for m in members)
    if target.exists():
        for m in members:
            p=target/m.name
            assert p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(target.resolve()) and p.read_bytes()==tar.extractfile(m).read()
    else:
        staging=root/('.partial-'+DIGEST)
        staging.mkdir(exist_ok=True)
        assert not staging.is_symlink()
        for m in members:
            p=staging/m.name
            assert p.resolve().is_relative_to(staging.resolve()) and not p.is_symlink()
            p.parent.mkdir(parents=True,exist_ok=True)
            data=tar.extractfile(m).read()
            if p.exists():assert p.read_bytes()==data
            else:p.write_bytes(data)
        outer='review-contract.json' if (staging/'review-contract.json').exists() else 'manifest.json'
        seal='AUTHORITY_COMPLETE' if outer=='review-contract.json' else 'COMPLETE'
        raw=(staging/outer).read_bytes()
        assert hashlib.sha256(raw).hexdigest()==DIGEST and (staging/seal).read_text().strip()==DIGEST
        for item in json.loads(raw)['files']:
            p=staging/item['path'];assert p.stat().st_size==item['bytes'] and hashlib.sha256(p.read_bytes()).hexdigest()==item['sha256']
        if outer=='review-contract.json':
            legacy=(staging/'manifest.json').read_bytes()
            assert (staging/'COMPLETE').read_text().strip()==hashlib.sha256(legacy).hexdigest()
        staging.rename(target)
print(json.dumps({'transfer_sha':DIGEST,'remote_path':str(target),'training_dataset_qualified':False}))
'''.replace("ROOT", repr(target)).replace("ARCHIVE_SHA", repr(sha(archive))).replace("DIGEST", repr(digest))
    response = subprocess.run(["ssh", *SSH_OPTIONS, peer, "python3 -"], input=script,
                              text=True, encoding="utf-8", capture_output=True, timeout=45, check=True)
    result = json.loads(response.stdout)
    if result.get("transfer_sha") != digest or result.get("training_dataset_qualified") is not False:
        raise JobError("remote receipt differs")
    return result


def run_once(config, out, *, publisher=publish, current_fetcher=fetch_current,
             current_publisher=publish_current):
    if set(config) - {"authority"} != {"source", "peer", "remote_reviews", "interval_s", "max_attempts"}:
        raise JobError("bridge source/peer/remote_reviews/interval_s/max_attempts required")
    if any(type(config[k]) is not int or config[k] < 1 for k in ("interval_s", "max_attempts")):
        raise JobError("positive interval and attempt limit required")
    authority_config = config.get("authority")
    if authority_config is not None and (not isinstance(authority_config, dict)
            or set(authority_config) != {"endpoint", "workspace_id"}):
        raise JobError("authority endpoint/workspace_id required")
    out = Path(out).resolve()
    with Job(out, config) as job:
        current, delivered = None, False
        if authority_config is not None:
            from review_authority import advance_revision
            previous = job.state.get("current_authority", {}).get("revision")
            snapshot = {"schema": "rosy.pinky-review-current-delivery/1",
                        "workspace_id": authority_config["workspace_id"],
                        "checked_at_unix": time.time(), "available": False,
                        "authority": None, "revision": previous}
            status = "unavailable"
            error = None
            try:
                current = current_fetcher(config)
                revision = advance_revision(current, workspace_id=authority_config["workspace_id"],
                                            previous=previous)
                snapshot.update(available=True, authority=current, revision=revision,
                                checked_at_unix=time.time())
                status = "verified"
            except Exception as failure:
                current = None
                error = f"{type(failure).__name__}: {failure}"
            try:
                current_publisher(snapshot, config, out)
                delivered = snapshot["available"]
            except Exception as failure:
                status = "delivery_failed"
                error = f"{type(failure).__name__}: {failure}"
            job.state["current_authority"] = {"status": status, "revision": snapshot["revision"],
                                              "checked_at_unix": snapshot["checked_at_unix"],
                                              "error": error}
            job._save()
        for folder in sorted(Path(config["source"]).glob("*")):
            if folder.name.startswith(".") or not folder.is_dir() or not (folder / "COMPLETE").is_file():
                continue
            if authority_config is not None and not (folder / "AUTHORITY_COMPLETE").is_file():
                # COMPLETE precedes the outer contract during producer sealing. In v2 mode
                # even a not-yet-created contract must never fall back to legacy transfer.
                continue
            try:
                info = verified_export(folder)
                key = info["manifest_sha"]
                if (folder / "review-contract.json").exists() or (folder / "AUTHORITY_COMPLETE").exists():
                    if not (folder / "AUTHORITY_COMPLETE").is_file():
                        continue  # Never transfer v2 as a legacy bundle while its producer is sealing.
                    if current is None or not delivered:
                        raise JobError("current authority unavailable or not delivered")
                    from review_authority import verify_bundle
                    verified = verify_bundle(folder, current, workspace_id=authority_config["workspace_id"])
                    key = verified["contract_sha"]
                prior = job.state["steps"].get(key, {})
                if prior.get("status") == "failed" and prior.get("attempts", 0) >= config["max_attempts"]:
                    continue
                def stage(attempt):
                    result = publisher(folder, key, config, out)
                    files = [folder / path for path in export_files(folder)]
                    return receipt(result, files)
                job.step(key, stage)
                if str(folder) in job.state.get("errors", {}):
                    job.state["errors"].pop(str(folder))
                    job._save()
            except Exception as error:
                job.state.setdefault("errors", {})[str(folder)] = f"{type(error).__name__}: {error}"
                job._save()
        return json.loads(job.path.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config")
    parser.add_argument("--out", required=True)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    while True:
        state = run_once(config, args.out)
        print(json.dumps({"exports": {k: v["status"] for k, v in state["steps"].items()},
                          "errors": state.get("errors", {})}), flush=True)
        if args.once:
            return
        time.sleep(config["interval_s"])


if __name__ == "__main__":
    main()
