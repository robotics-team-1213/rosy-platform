"""Device twin plumbing: build (key, releases, images), the twin container, the GitHub side. Twin only."""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RELEASE_TOOLS = ROOT / "deploy" / "robot" / "pinky_pro" / "release"
sys.path.insert(0, str(RELEASE_TOOLS))
import signing  # noqa: E402

NET = "rosy-twin-net"
GH = "rosy-twin-github"
TWIN = "rosy-twin"
HOSTNAME = "rosy-pinky-twin"
REPO = "twin/rosy-os"
KEY_NAME = "twin-d406-test"
TRUSTED_STEM = "rosy-release-2026-01"   # the device's fixed trusted-key file name
API_PORT = 18080
GH_PORT = 8080
API_BASE = f"http://{GH}:{GH_PORT}"
IMAGE_BASE = "rosy-d406-twin:base"
IMAGE = "rosy-d406-twin:run"
DAY = "2026.10.02"
RELEASES = {  # name: (release id, fake CORE variant, carries an image-layer change)
    "A": (f"{DAY}-001", "good", False),
    "B": (f"{DAY}-002", "good", False),
    "C": (f"{DAY}-003", "crash-after-ready", True),
    "N": (f"{DAY}-004", "never-ready", False),
    "D": (f"{DAY}-005", "good", False),
}
R = {name: value[0] for name, value in RELEASES.items()}
UPDATER = "/opt/rosy/native-runtime/rosy_auto_update.py"
UPDATES = "/var/lib/rosy/updates"
#: D-418: CORE's own hand-over code (stdlib), run in the twin as rosy-core by twin-ssh-request.
SSH_HANDOFF = "middleware/core/api_web/core_api_web/api/v1/ssh_handoff.py"


def log(message: str) -> None:
    print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


def run(argv: list[str], *, timeout: float = 600, check: bool = True, env: dict | None = None,
        cwd: Path | None = None) -> subprocess.CompletedProcess:
    done = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, env=env, cwd=cwd)
    if check and done.returncode != 0:
        raise RuntimeError(f"{' '.join(argv)} -> {done.returncode}\n{done.stdout[-2000:]}\n{done.stderr[-2000:]}")
    return done


# --- build ----------------------------------------------------------------------


class Build:
    def __init__(self, work: Path) -> None:
        self.work = work
        self.ctx = work / "ctx"
        self.keys = work / "keys"
        self.releases = work / "releases"
        self.store = work / "store"
        self.appdata = work / "localappdata"
        self.revision = ""
        self.python_runtime = ""

    def prepare(self) -> None:
        for folder in (self.ctx, self.keys, self.releases):
            if folder.exists():
                shutil.rmtree(folder)
            folder.mkdir(parents=True)
        self.revision = run(["git", "rev-parse", "HEAD"], cwd=ROOT).stdout.strip()
        dirty = run(["git", "status", "--porcelain", "--", "deploy/robot/pinky_pro"], cwd=ROOT).stdout.strip()
        if dirty:
            log("WARNING: deploy/robot/pinky_pro has uncommitted changes; the twin uses HEAD only")
        # LF product content from the commit, never the CRLF working tree.
        with (self.ctx / "repo.tar").open("wb") as handle:
            subprocess.run(["git", "archive", "--format=tar", "HEAD", "deploy/robot/pinky_pro", SSH_HANDOFF],
                           cwd=ROOT, stdout=handle, check=True)
        requirements = subprocess.run(
            ["git", "show", "HEAD:deploy/robot/pinky_pro/image/device-python-requirements.txt"],
            cwd=ROOT, capture_output=True, check=True).stdout
        self.python_runtime = hashlib.sha256(requirements).hexdigest()
        # Twin files: the working tree, normalized to LF.
        for source in HERE.rglob("*"):
            if source.is_dir() or "__pycache__" in source.parts:
                continue
            target = self.ctx / "twin" / source.relative_to(HERE)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes().replace(b"\r\n", b"\n"))
        log(f"context ready at {self.ctx} (HEAD {self.revision[:12]})")

    def docker_mount(self, path: Path) -> str:
        return str(path.resolve())

    def base_image(self) -> None:
        log("building the base image (ubuntu:24.04 + systemd + python3 + openssl)")
        run(["docker", "build", "--target", "base", "-t", IMAGE_BASE, "-f",
             str(self.ctx / "twin/image/Dockerfile"), str(self.ctx)], timeout=1800)

    def key(self) -> None:
        """A fresh throwaway Ed25519 key per run, made inside the base container."""
        run(["docker", "run", "--rm", "-v", f"{self.docker_mount(self.keys)}:/keys", IMAGE_BASE, "bash", "-c",
             f"openssl genpkey -algorithm ed25519 -out /keys/{KEY_NAME}.private.pem && "
             f"openssl pkey -in /keys/{KEY_NAME}.private.pem -pubout -out /keys/{TRUSTED_STEM}.pem"])
        signing_dir = self.appdata / "Rosy" / "signing"
        signing_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.keys / f"{KEY_NAME}.private.pem", signing_dir / f"{KEY_NAME}.private.pem")
        log(f"throwaway key {KEY_NAME} -> {self.keys}")

    @property
    def public_key(self) -> Path:
        return self.keys / f"{TRUSTED_STEM}.pem"

    @property
    def private_key(self) -> Path:
        return self.keys / f"{KEY_NAME}.private.pem"

    def build_releases(self) -> dict:
        lines = ["set -euo pipefail", "mkdir -p /work/repo", "tar -xf /ctx/repo.tar -C /work/repo",
                 "cp -r /ctx/twin /work/twin", "find /work/twin -type f -exec chmod 0644 {} +"]
        for name, (release_id, variant, marker) in RELEASES.items():
            lines.append(
                f"python3 -B /work/twin/build_twin_release.py --repo /work/repo --twin /work/twin "
                f"--release-id {release_id} --revision {self.revision} --python-runtime {self.python_runtime} "
                f"--variant {variant} {'--layer-marker' if marker else ''} "
                f"--private-key /keys/{KEY_NAME}.private.pem --public-key /keys/{TRUSTED_STEM}.pem --out /out")
        log("building signed twin releases with build_payload_release.py + sign_image_release.py")
        done = run(["docker", "run", "--rm", "-v", f"{self.docker_mount(self.ctx)}:/ctx:ro",
                    "-v", f"{self.docker_mount(self.keys)}:/keys:ro",
                    "-v", f"{self.docker_mount(self.releases)}:/out", IMAGE_BASE, "bash", "-c", "\n".join(lines)],
                   timeout=1800)
        built = {}
        for line in done.stdout.splitlines():
            if line.startswith("{"):
                item = json.loads(line)
                built[item["release_id"]] = item
        for name, (release_id, variant, _marker) in RELEASES.items():
            log(f"  {name} {release_id} {variant} sha256 {built[release_id]['sha256'][:16]}")
        return built

    def twin_image(self) -> None:
        (self.ctx / "keys").mkdir(exist_ok=True)
        shutil.copyfile(self.public_key, self.ctx / "keys" / f"{TRUSTED_STEM}.pem")
        (self.ctx / "releases").mkdir(exist_ok=True)
        shutil.copyfile(self.releases / f"{R['A']}.tar.gz", self.ctx / "releases" / f"{R['A']}.tar.gz")
        (self.ctx / "twin.env").write_bytes(
            (f"FACTORY_RELEASE={R['A']}\nPYTHON_RUNTIME={self.python_runtime}\nAPI_BASE={API_BASE}\n"
             f"REPO={REPO}\nAPI_PORT={API_PORT}\n").encode())
        log("building the twin image (real native runtime + units, factory release A)")
        run(["docker", "build", "--target", "twin", "-t", IMAGE, "-f",
             str(self.ctx / "twin/image/Dockerfile"), str(self.ctx)], timeout=1800)

    def network(self) -> None:
        if run(["docker", "network", "inspect", NET], check=False).returncode != 0:
            # Docker Desktop's predefined pools can be exhausted; fall back to fixed subnets.
            for subnet in (None, "10.231.46.0/24", "10.231.47.0/24", "172.30.246.0/24"):
                created = run(["docker", "network", "create", *(["--subnet", subnet] if subnet else []), NET],
                              check=False)
                if created.returncode == 0:
                    break
            else:
                raise RuntimeError(f"cannot create docker network {NET}: {created.stderr.strip()}")
        run(["docker", "rm", "-f", GH], check=False)
        if self.store.exists():
            shutil.rmtree(self.store)
        self.store.mkdir(parents=True)
        run(["docker", "run", "-d", "--name", GH, "--network", NET,
             "-v", f"{self.docker_mount(self.store)}:/store",
             "-v", f"{self.docker_mount(self.ctx / 'twin')}:/twin:ro", IMAGE_BASE,
             "python3", "-B", "/twin/fake_github.py", "--store", "/store", "--port", str(GH_PORT),
             "--public-base", API_BASE])
        log(f"fake GitHub {API_BASE} (store {self.store})")


# --- the twin --------------------------------------------------------------------


class Twin:
    def __init__(self, build: Build) -> None:
        self.build = build
        #: A scenario may lower the default per-step timeout (the D-418 ssh steps use 90 s).
        self.step_timeout: float | None = None

    def start(self) -> None:
        run(["docker", "rm", "-f", TWIN], check=False)
        self.reset_store()
        run(["docker", "run", "-d", "--name", TWIN, "--hostname", HOSTNAME, "--network", NET,
             "--privileged", "--cgroupns=host", "--tmpfs", "/run", "--tmpfs", "/run/lock",
             "-v", "/sys/fs/cgroup:/sys/fs/cgroup:rw",
             "-v", f"{self.build.docker_mount(self.build.releases)}:/twin/releases:ro", IMAGE])
        self.wait_runtime()

    def reset_store(self) -> None:
        for item in self.build.store.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()

    def wait_runtime(self, timeout: float = 120) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            done = self.x("systemctl is-active rosy-core.service rosy-io.service rosy-camera.service "
                          "&& test -s /run/rosy/status-inputs.json", check=False)
            if done.returncode == 0:
                return
            time.sleep(1)
        raise RuntimeError("the twin runtime did not come up:\n"
                           + self.x("systemctl --no-pager status rosy-core.service rosy-runtime.target "
                                    "| tail -40", check=False).stdout)

    def x(self, command: str, *, user: str | None = None, timeout: float | None = None,
          check: bool = True) -> subprocess.CompletedProcess:
        """docker exec in the twin. A step that hangs past its timeout (the call's, else
        `step_timeout`, else 900 s) is logged by name; with check=False it returns exit 124 so
        the scenario records a FAIL for that step and goes on, with check=True it raises."""
        limit = timeout if timeout is not None else (self.step_timeout or 900)
        argv = ["docker", "exec", *(["-u", user] if user else []), TWIN, "bash", "-c", command]
        try:
            return run(argv, timeout=limit, check=check)
        except subprocess.TimeoutExpired:
            log(f"  STEP TIMEOUT after {limit:.0f} s: {command[:200]}")
            if check:
                raise RuntimeError(f"step timed out after {limit:.0f} s: {command[:300]}") from None
            return subprocess.CompletedProcess(argv, 124, "", f"STEP TIMEOUT after {limit:.0f} s")

    def out(self, command: str, **kwargs) -> str:
        return self.x(command, **kwargs).stdout.strip()

    # observations
    def main_pid(self, unit: str = "rosy-core.service") -> int:
        return int(self.out(f"systemctl show -p MainPID --value {unit}") or 0)

    def cwd(self, pid: int) -> str:
        return self.out(f"readlink /proc/{pid}/cwd", check=False) if pid else ""

    def current(self) -> str:
        return Path(self.out("readlink -f /opt/rosy/current")).name

    def json_file(self, path: str) -> dict | None:
        text = self.out(f"cat {path} 2>/dev/null || true")
        return json.loads(text) if text else None

    def status(self) -> dict:
        return self.json_file(f"{UPDATES}/status.json") or {}

    def state(self) -> dict:
        return self.json_file(f"{UPDATES}/state.json") or {}

    def history(self) -> list[dict]:
        text = self.out(f"cat {UPDATES}/history.jsonl 2>/dev/null || true")
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    def api_version(self) -> str:
        text = self.out(f"curl -s --max-time 3 http://127.0.0.1:{API_PORT}/api/v1/openapi.json", check=False)
        try:
            return json.loads(text)["info"]["version"]
        except (ValueError, KeyError, TypeError):
            return f"unavailable ({text[:80]!r})"

    def control(self, mode: str, settle: bool = True) -> None:
        self.x(f"twin-control {mode}")
        if settle:
            time.sleep(11)  # one CORE write cycle (10 s) carries the new mode

    def run_updater(self, timeout: float = 1500) -> float:
        started = time.monotonic()
        self.x("systemctl start rosy-auto-update.service", timeout=timeout, check=False)
        return time.monotonic() - started

    def unpack_and_activate(self, release_id: str) -> str:
        return self.out(
            f"cp /twin/releases/{release_id}.tar.gz /tmp/{release_id}.tar.gz && "
            f"bash /opt/rosy/native-runtime/rosy-release-unpack.sh {release_id} /tmp/{release_id}.tar.gz && "
            f"bash /opt/rosy/native-runtime/activate-release.sh {release_id} && "
            f"python3 -B /opt/rosy/current/deploy/robot/native/sync-image-layer.py | tail -c 400")

    def journal(self, unit: str, lines: int = 25) -> str:
        return self.out(f"journalctl -u {unit} -o cat --no-pager | tail -n {lines}", check=False)


# --- GitHub side ----------------------------------------------------------------


def _load_publish():
    spec = importlib.util.spec_from_file_location("publish_payload_release",
                                                  ROOT / "tools/release/publish_payload_release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GitHubSide:
    def __init__(self, build: Build) -> None:
        self.build = build
        self.publish = _load_publish()

    def env(self) -> dict:
        return {**os.environ, "LOCALAPPDATA": str(self.build.appdata), "TWIN_GH_STORE": str(self.build.store),
                "TWIN_CONTAINER": TWIN, "PYTHONUTF8": "1"}

    def gh(self, *args: str) -> subprocess.CompletedProcess:
        return run([sys.executable, str(HERE / "fake_gh.py"), *args], env=self.env())

    def signed_rollout(self, release_id: str, folder: Path, **changes) -> list[Path]:
        tarball = self.build.releases / f"{release_id}.tar.gz"
        rollout = self.publish.build_rollout(
            release_id, signing.sha256_file(tarball), self.build.revision,
            self.publish.utc_stamp(dt.datetime.now(dt.timezone.utc)), HOSTNAME, 600)
        rollout.update(changes)
        data = self.publish.rollout_bytes(rollout)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "rollout.json").write_bytes(data)
        (folder / "rollout.json.sig").write_bytes(
            signing.sign_checksums(data, self.build.private_key).encode("ascii"))
        return [folder / "rollout.json", folder / "rollout.json.sig"]

    def release(self, release_id: str, **changes) -> None:
        """Create payload-<id> with a rollout signed the way the publish tool signs it."""
        folder = self.build.work / "staging" / release_id
        files = self.signed_rollout(release_id, folder, **changes)
        self.gh("release", "create", f"payload-{release_id}", "--repo", REPO, "--target", self.build.revision,
                "--title", f"payload-{release_id}", "--notes", "device twin",
                str(self.build.releases / f"{release_id}.tar.gz"), *map(str, files))

    def reupload(self, release_id: str, **changes) -> None:
        folder = self.build.work / "staging" / f"{release_id}-reupload"
        files = self.signed_rollout(release_id, folder, **changes)
        self.gh("release", "upload", f"payload-{release_id}", "--repo", REPO, "--clobber", *map(str, files))

    def remote_rollout(self, release_id: str) -> tuple[dict, bool]:
        folder = self.build.store / REPO / "assets" / f"payload-{release_id}"
        data = (folder / "rollout.json").read_bytes()
        signature = (folder / "rollout.json.sig").read_text(encoding="ascii")
        ok = not signing.verify_signature(data, signature, self.build.public_key)
        return json.loads(data), ok

    def publish_argv(self, release_id: str, *extra: str) -> list[str]:
        return [sys.executable, "-B", str(HERE / "twin_publish.py"), "--repo", REPO, "--key-name", KEY_NAME,
                "--public-key", str(self.build.public_key), "--evidence-dir", str(self.build.work / "evidence"),
                "--out-dir", str(self.build.work / "publish"), *extra]

    def start_publish(self, release_id: str, timeout_min: int = 10) -> subprocess.Popen:
        argv = self.publish_argv(release_id, "--tarball", str(self.build.releases / f"{release_id}.tar.gz"),
                                 "--canary", HOSTNAME, "--canary-timeout-min", str(timeout_min))
        log_path = self.build.work / "logs" / f"publish-{release_id}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handle = log_path.open("w", encoding="utf-8")
        process = subprocess.Popen(argv, stdout=handle, stderr=subprocess.STDOUT, env=self.env(), cwd=ROOT)
        process.log_path = log_path  # type: ignore[attr-defined]
        return process

    def wait_release(self, release_id: str, timeout: float = 120) -> None:
        folder = self.build.store / REPO / "assets" / f"payload-{release_id}"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if all((folder / name).is_file() for name in (f"{release_id}.tar.gz", "rollout.json", "rollout.json.sig")):
                return
            time.sleep(1)
        raise RuntimeError(f"payload-{release_id} was not published within {timeout:.0f} s")
