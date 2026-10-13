"""Trusted operator-PC coordinator: main push -> unsigned build (beside CI) -> signed rollout.

The unsigned ARM64 build starts as soon as main moves (D-553); signing waits
for that commit's successful CI and a failed CI ends the transaction.

Install an approved, fixed snapshot before scheduling this program. It never
checks out or executes incoming main code on the signing PC. Robots retain
their own D-412 eligibility, canary and rollback gates.
"""
from __future__ import annotations

import argparse
import contextlib
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
SHA = re.compile(r"[0-9a-f]{40}")
MAX_STATE_DIR = 64
RELEASE = re.compile(r"(?:payload-(?:reserved-)?)?(\d{4}\.\d{2}\.\d{2})-(\d{3})")


def approved_run(run, *, sha, repo_id, workflow_id, event):
    return (run.get("head_sha") == sha and run.get("head_branch") == "main"
            and run.get("event") == event and run.get("workflow_id") == workflow_id
            and run.get("status") == "completed" and run.get("conclusion") == "success"
            and run.get("repository", {}).get("id") == repo_id
            and run.get("head_repository", {}).get("id") == repo_id)


def next_release_id(date, names):
    numbers = [int(m.group(2)) for name in names if (m := RELEASE.fullmatch(name))]
    number = max(numbers, default=0) + 1
    if number > 999:
        raise ValueError("release sequence exhausted; an approved ID-format migration is required")
    return f"{date}-{number:03d}"


def verify_source(path, expected):
    with tarfile.open(path, "r:gz") as bundle:
        sources = [m for m in bundle.getmembers() if m.name == "source-revision.txt"]
        if len(sources) != 1 or not sources[0].isfile() or sources[0].size > 64:
            raise ValueError("candidate source revision is missing, duplicated or not a regular file")
        if bundle.extractfile(sources[0]).read().decode("ascii").strip() != expected:
            raise ValueError("candidate source revision differs from successful CI/build")


def write_json(path, data):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".new")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def write_snapshot(root, files, revision):
    write_json(Path(root) / "trusted-snapshot.json", {
        "source_revision": revision,
        "files": {name: hashlib.sha256((Path(root) / name).read_bytes()).hexdigest() for name in files},
    })


def verify_snapshot(root):
    root = Path(root).resolve()
    manifest = json.loads((root / "trusted-snapshot.json").read_text(encoding="utf-8"))
    if not SHA.fullmatch(manifest["source_revision"]) or not manifest["files"]:
        raise ValueError("invalid trusted installation")
    for name, digest in manifest["files"].items():
        path = (root / name).resolve()
        if not path.is_relative_to(root) or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("trusted signer installation changed; install a reviewed snapshot again")


def dispatch_expired(stamp, now=None):
    return ((now or datetime.now(timezone.utc)) - datetime.fromisoformat(stamp)).total_seconds() >= 1200


def preparation_folder(base, state, release_id):
    previous = Path(state.get("work_dir", base / "attempt-1"))
    attempt = state.get("attempt", 1)
    if ((previous / "x" / release_id).exists()
            and not (previous / f"{release_id}.tar.gz").exists()):
        attempt += 1
    if attempt > 3:
        raise ValueError("preparation interrupted three times; preserved attempts require review")
    return Path(base) / f"attempt-{attempt}"


def check_resume_identity(remote, state):
    expected = {"release_id": state["release_id"], "source_revision": state["sha"],
                "tarball_sha256": state["tarball_sha256"], "canary": [state["canary_name"]]}
    if any(remote.get(key) != value for key, value in expected.items()):
        raise ValueError("signed remote rollout differs from this release transaction")


@contextlib.contextmanager
def locked(folder):
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "coordinator.lock").open("a+b") as stream:
        if os.name == "nt":
            import msvcrt
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


class Coordinator:
    def __init__(self, config, *, gh=None):
        self.config = config
        self.repo = config["repo"]
        self.folder = Path(config["state_dir"])
        self.folder.mkdir(parents=True, exist_ok=True)
        self.state_path = self.folder / "state.json"
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        self.gh = gh or self.command

    def command(self, *args):
        result = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8", timeout=180)
        if result.returncode:
            # Do not relay credentials, signed URLs or arbitrary command output.
            raise RuntimeError(f"GitHub {args[0]} failed (exit {result.returncode})")
        return result.stdout

    def api(self, path):
        return json.loads(self.gh("api", f"repos/{self.repo}" + (f"/{path}" if path else "")))

    def save(self, **values):
        self.state.update(values)
        write_json(self.state_path, self.state)

    def audit(self, result):
        with (self.folder / "audit.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(),
                                    "result": result, **self.state}) + "\n")
        return result

    def ci(self, sha):
        """success, failed or pending for this exact main push."""
        workflow = self.api("actions/workflows/ci.yml")
        runs = self.api(f"actions/workflows/ci.yml/runs?branch=main&event=push&head_sha={sha}&per_page=30")
        ours = [r for r in runs["workflow_runs"]
                if approved_run(dict(r, status="completed", conclusion="success"), sha=sha,
                                repo_id=self.config["repo_id"], workflow_id=workflow["id"], event="push")]
        if any(approved_run(r, sha=sha, repo_id=self.config["repo_id"], workflow_id=workflow["id"],
                            event="push") for r in ours):
            return "success"
        return "failed" if ours and all(r.get("status") == "completed" for r in ours) else "pending"

    def superseded(self, release_id):
        """A newer published payload exists; signing this one could only roll robots back."""
        mine = int(RELEASE.fullmatch(release_id).group(2))
        for ref in self.api("git/matching-refs/tags/payload-"):
            match = re.fullmatch(r"payload-\d{4}\.\d{2}\.\d{2}-(\d{3})", ref["ref"].removeprefix("refs/tags/"))
            if match and int(match.group(1)) > mine:
                return True
        return False

    def ssh(self, argv):
        import prepare_payload_release as prepare
        if self.config.get("ssh_jump"):
            argv = argv[:1] + ["-J", self.config["ssh_jump"]] + argv[1:]
        return prepare.run_ssh(argv)

    def tick(self):
        latest = self.api("git/ref/heads/main")["object"]["sha"]
        if not SHA.fullmatch(latest):
            raise ValueError("invalid main revision")
        active = self.state.get("phase") not in (None, "done", "failed")
        sha = self.state["sha"] if active else latest
        ci = self.ci(sha)
        if active and self.api(f"compare/{sha}...main")["status"] not in ("ahead", "identical"):
            raise ValueError("pending source is no longer on main")
        if not active:
            if ci == "failed":
                return self.audit("ci_failed")
            if self.state.get("sha") == sha:
                return self.audit(self.state["phase"])
            # Completed signed rollouts are not recreated; unfinished ones need
            # their existing rollout watcher, not a second release with the same SHA.
            releases = self.api("releases?per_page=100")
            for release in releases:
                if release.get("target_commitish") == sha and release.get("tag_name", "").startswith("payload-"):
                    assets = {a["name"] for a in release.get("assets", [])}
                    if {"rollout.json", "rollout.json.sig"} <= assets:
                        return self.audit("existing_rollout")
            refs = self.api("git/matching-refs/tags/payload-")
            names = [r["ref"].removeprefix("refs/tags/") for r in refs]
            import prepare_payload_release as prepare
            local = Path(os.environ["LOCALAPPDATA"])
            for robot in self.config["robots"]:
                code, out, _ = self.ssh(prepare.ssh_argv(robot, local, "readlink -f /opt/rosy/current"))
                if code:
                    raise RuntimeError("robot version unavailable; release allocation refused")
                names.append(out.strip().rsplit("/", 1)[-1])
            release_id = next_release_id(datetime.now(timezone.utc).strftime("%Y.%m.%d"), names)
            # GitHub's atomic ref creation reserves the ID across signing PCs.
            self.gh("api", "--method", "POST", f"repos/{self.repo}/git/refs",
                    "-f", f"ref=refs/tags/payload-reserved-{release_id}", "-f", f"sha={sha}")
            if self.state:
                self.audit("previous_transaction")
            self.state = {}  # attempt budget, canary and PID belong to one release only
            self.save(sha=sha, release_id=release_id, phase="dispatching",
                      dispatched_at=datetime.now(timezone.utc).isoformat())
            self.gh("workflow", "run", "build-native-payload.yml", "--repo", self.repo,
                    "--ref", "main", "-f", f"release_id={release_id}")
            self.save(phase="building")
            return self.audit("build_dispatched")
        release_id = self.state["release_id"]
        if ci == "failed" and self.state["phase"] in ("dispatching", "building", "preparing"):
            # Signed rollouts are past this gate. The speculative build is discarded; its reserved ID stays a gap.
            self.save(phase="failed", reason="CI failed for this source; unsigned build discarded")
            return self.audit("ci_failed")
        if self.state["phase"] in ("dispatching", "building"):
            workflow = self.api("actions/workflows/build-native-payload.yml")
            runs = self.api("actions/workflows/build-native-payload.yml/runs?branch=main&event=workflow_dispatch&per_page=100")
            candidates = [r for r in runs["workflow_runs"]
                          if r.get("display_title") == f"Pinky payload {release_id}"]
            if not candidates:
                if dispatch_expired(self.state["dispatched_at"]):
                    self.save(phase="failed", reason="dispatch never registered; review before retry")
                    return self.audit("dispatch_failed")
                return self.audit("waiting_build_registration")
            if len(candidates) != 1:
                raise ValueError("duplicate payload build identity")
            run = candidates[0]
            if run["status"] != "completed":
                return self.audit("waiting_build")
            if not approved_run(run, sha=sha, repo_id=self.config["repo_id"],
                                workflow_id=workflow["id"], event="workflow_dispatch"):
                self.save(phase="failed", reason="build failed or source changed during dispatch")
                return self.audit("build_refused")
            self.save(phase="preparing", build_run=run["id"])
        if self.state["phase"] == "preparing":
            if ci != "success":
                return self.audit("waiting_ci")
            if self.superseded(release_id):
                self.save(phase="failed", reason="a newer payload release exists")
                return self.audit("superseded")
            import prepare_payload_release as prepare
            try:
                work = preparation_folder(self.folder / release_id, self.state, release_id)
                self.save(work_dir=str(work), attempt=int(work.name.removeprefix("attempt-")))
                signed = work / f"{release_id}.tar.gz"
                if not signed.exists():
                    _, unsigned = prepare.download_unsigned(self.state["build_run"], release_id, work, self.repo, 8)
                    verify_source(unsigned, sha)
                    args = ["--artifact-dir", str(work), "--out-dir", str(work), "--release-id", release_id,
                            "--repo", self.repo, "--key-name", self.config["key_name"]]
                    for robot in self.config["robots"]:
                        args += ["--robot", robot]
                    if prepare.main(args, ssh_runner=self.ssh):
                        raise RuntimeError("payload preparation refused; preserve work folder for review")
                verify_source(signed, sha)
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, tarfile.TarError) as error:
                # D-553 3: a refusal used to retry every tick forever, unlogged.
                failures = self.state.get("prepare_failures", 0) + 1
                self.save(prepare_failures=failures, last_error=f"{type(error).__name__}: {error}")
                if failures >= 3:
                    self.save(phase="failed", reason="preparation failed three times; review the work folder")
                    return self.audit("prepare_failed")
                return self.audit("prepare_retry")
            self.save(phase="publishing", tarball_sha256=hashlib.sha256(signed.read_bytes()).hexdigest())
        if self.state["phase"] == "publishing":
            import publish_payload_release as publish
            work = Path(self.state["work_dir"])
            signed = work / f"{release_id}.tar.gz"
            if hashlib.sha256(signed.read_bytes()).hexdigest() != self.state["tarball_sha256"]:
                raise ValueError("signed payload changed after preparation")
            args = ["--tarball", str(signed), "--canary", self.config["canary"], "--repo", self.repo,
                    "--key-name", self.config["key_name"], "--canary-timeout-min", "30",
                    "--evidence-dir", str(self.folder / "rollouts")]
            for robot in self.config["robots"]:
                if robot != self.config["canary"]:
                    args += ["--robot", robot]
            existing = self.api(f"git/matching-refs/tags/payload-{release_id}")
            local = Path(os.environ["LOCALAPPDATA"])
            publisher = publish.Publisher(
                release_id=release_id, repo=self.repo, work_dir=work / f"publish-{release_id}",
                key_name=self.config["key_name"],
                private_key=local / "Rosy/signing" / f'{self.config["key_name"]}.private.pem',
                public_key=ROOT / "deploy/robot/pinky_pro/release/public-keys" / f'{self.config["key_name"]}.pem',
                local_appdata=local, evidence_dir=self.folder / "rollouts", gh=publish.run_gh,
                ssh=self.ssh, now=lambda: datetime.now(timezone.utc),
                monotonic=time.monotonic, sleep=time.sleep)
            if "canary_name" not in self.state:
                self.save(canary_name=publisher.hostname(self.config["canary"]))
            lock = publisher.work_dir / ".lock"
            if lock.exists():
                pid = int(lock.read_text(encoding="ascii").strip())
                if pid == self.state.get("publisher_pid") and not publish.pid_alive(pid):
                    lock.unlink()  # this transaction's dead process only; coordinator lock is held
            if existing:
                remote, _ = publisher.download()  # public-key verification precedes identity checks
                check_resume_identity(remote, self.state)
                if remote["withdrawn"]:
                    self.save(phase="failed", reason="signed rollout withdrawn")
                    return self.audit("withdrawn")
                args += ["--resume"]
            self.save(publisher_pid=os.getpid())
            result = publish.main(args, ssh_runner=self.ssh)
            if result == 0:
                self.save(phase="done", reason="rollout approved")
                return self.audit("done")
            # A transport failure must not masquerade as policy rejection. Keep
            # this transaction pending; the next tick verifies its remote signed
            # rollout before resuming. A withdrawn rollout becomes terminal above.
            return self.audit("rollout_pending")
        return self.audit("waiting")


def load_config(path):
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    required = {"repo", "repo_id", "state_dir", "robots", "canary", "key_name", "trusted_root"}
    if set(config) - required - {"ssh_jump"} or not required <= set(config):
        raise ValueError("invalid robot CD configuration fields")
    if not re.fullmatch(r"[\w-]+/[\w.-]+", config["repo"]) or type(config["repo_id"]) is not int:
        raise ValueError("invalid repository identity")
    if (not isinstance(config["robots"], list) or not config["robots"]
            or config["canary"] not in config["robots"]):
        raise ValueError("canary must belong to the configured robots")
    if not all(isinstance(h, str) and re.fullmatch(r"[A-Za-z0-9.-]+", h) for h in config["robots"]):
        raise ValueError("invalid robot host")
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", config["key_name"]):
        raise ValueError("invalid signing key name")
    if not Path(config["state_dir"]).is_absolute() or Path(config["state_dir"]).resolve().is_relative_to(ROOT):
        raise ValueError("state and downloads must be outside the trusted signer installation")
    # The payload is extracted under <state>/<id>/attempt-N/x/.<id>.partial-*/ and its
    # deepest file is ~120 characters; past Windows MAX_PATH (260) extraction fails.
    # A 95-character state path stalled release 045 for four days (D-553).
    if len(str(Path(config["state_dir"]).resolve())) > MAX_STATE_DIR:
        raise ValueError(f"state_dir longer than {MAX_STATE_DIR} characters; payload paths would pass MAX_PATH")
    if config.get("ssh_jump") and not re.fullmatch(r"[A-Za-z0-9_.@-]+", config["ssh_jump"]):
        raise ValueError("invalid SSH jump")
    if Path(config["trusted_root"]).resolve() != ROOT.resolve():
        raise ValueError("run the installed trusted snapshot, not a source checkout")
    verify_snapshot(ROOT)
    return config


def configure_environment(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    os.environ.update(TEMP=str(folder), TMP=str(folder), PYTHONDONTWRITEBYTECODE="1")
    tempfile.tempdir = str(folder)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        configure_environment(config["state_dir"])
        sys.path.insert(0, str(ROOT / "tools/release"))
        with locked(Path(config["state_dir"])):
            coordinator = Coordinator(config)
            if coordinator.api("")["id"] != config["repo_id"]:
                raise ValueError("configured repository ID changed")
            try:
                print(coordinator.tick())
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
                coordinator.audit(f"stopped: {type(error).__name__}: {error}")
                raise
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Robot CD stopped: {type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
