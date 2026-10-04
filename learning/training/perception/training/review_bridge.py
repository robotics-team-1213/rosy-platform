"""Forward immutable Pinky review exports to the approved model PC, key-only.

review_bridge.py config.json --out STATE [--once]
Config: source, peer, remote_reviews, interval_s, max_attempts. No training/approval.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import tarfile
import time

from job_state import Job, JobError, receipt
from learning_cycle import verified_export

SSH_OPTIONS = ["-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes", "-o",
               "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=5"]


def publish(folder, digest, config, out):
    from job_state import sha
    peer, target = config["peer"], config["remote_reviews"]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", peer):
        raise JobError("invalid approved SSH peer alias")
    if not re.fullmatch(r"/[A-Za-z0-9/_.-]+", target) or ".." in Path(target).parts:
        raise JobError("remote review root must be a safe absolute path")
    archive = Path(out) / (digest + ".tar")
    doc = json.loads((folder / "manifest.json").read_text())
    files = ["manifest.json", "COMPLETE", *(r["path"] for r in doc["files"])]
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
        raw=(staging/'manifest.json').read_bytes()
        assert hashlib.sha256(raw).hexdigest()==DIGEST and (staging/'COMPLETE').read_text().strip()==DIGEST
        for item in json.loads(raw)['files']:
            p=staging/item['path'];assert p.stat().st_size==item['bytes'] and hashlib.sha256(p.read_bytes()).hexdigest()==item['sha256']
        staging.rename(target)
print(json.dumps({'manifest_sha':DIGEST,'remote_path':str(target),'training_dataset_qualified':False}))
'''.replace("ROOT", repr(target)).replace("ARCHIVE_SHA", repr(sha(archive))).replace("DIGEST", repr(digest))
    response = subprocess.run(["ssh", *SSH_OPTIONS, peer, "python3 -"], input=script,
                              text=True, encoding="utf-8", capture_output=True, timeout=45, check=True)
    result = json.loads(response.stdout)
    if result.get("manifest_sha") != digest or result.get("training_dataset_qualified") is not False:
        raise JobError("remote receipt differs")
    return result


def run_once(config, out, *, publisher=publish):
    if set(config) != {"source", "peer", "remote_reviews", "interval_s", "max_attempts"}:
        raise JobError("bridge source/peer/remote_reviews/interval_s/max_attempts required")
    if any(type(config[k]) is not int or config[k] < 1 for k in ("interval_s", "max_attempts")):
        raise JobError("positive interval and attempt limit required")
    out = Path(out).resolve()
    with Job(out, config) as job:
        for folder in sorted(Path(config["source"]).glob("*")):
            if folder.name.startswith(".") or not folder.is_dir() or not (folder / "COMPLETE").is_file():
                continue
            try:
                info = verified_export(folder)
                key = info["manifest_sha"]
                prior = job.state["steps"].get(key, {})
                if prior.get("status") == "failed" and prior.get("attempts", 0) >= config["max_attempts"]:
                    continue
                def stage(attempt):
                    result = publisher(folder, key, config, out)
                    doc = json.loads((folder / "manifest.json").read_text())
                    files = [folder / "manifest.json", folder / "COMPLETE",
                             *(folder / row["path"] for row in doc["files"])]
                    return receipt(result, files)
                job.step(key, stage)
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
