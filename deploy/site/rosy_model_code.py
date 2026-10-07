"""D-446 signed perception-code candidates and an idle-only model-PC updater.

The installed controller is outside the candidate. No pip, apt, git pull,
training cancellation, credential replacement or driving-model selection.
Uncommitted perception edits hold the switch and stay on disk. exec does not
run a work-tree script that differs from the signed release.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from candidate_signing import sign_manifest_bytes, verify_manifest_signature

PREFIX = "learning/training/perception/"
CAMERA_PROFILE = "middleware/apps/device/pinky/profile/config/camera_nominal.yaml"
CAMERA_MAP_FILES = tuple("operations/vision/rosy_vision/" + name
                         for name in ("__init__.py", "lane_map.py", "map_register.py"))
CODE_PREFIXES = (PREFIX, "middleware/perception/control/", "contracts/foundation/core_common/",
                 "shared/web/", CAMERA_PROFILE, *CAMERA_MAP_FILES)
# Observe enrolled pre-migration checkouts too; new signed archives stay canonical.
CHECKOUT_PREFIXES = CODE_PREFIXES + ("tools/perception/", "src/runtime/sensing/control/",
                                    "src/contracts/foundation/core_common/")
LIMIT = 512 * 1024 * 1024
FORBIDDEN = {"data", "private", "runs", "scratch", "checkpoints", "store", ".git", ".venv", "__pycache__", "secrets"}
IMPORT_PATHS = (PREFIX.rstrip("/"), PREFIX + "model", PREFIX + "dataset", PREFIX + "training",
                "middleware/perception", "contracts/foundation", "operations/vision",
                "src/runtime/sensing", "src/contracts/foundation")
PATH_SETUP = ("import pathlib,sys,runpy;root=pathlib.Path(sys.argv.pop(1)).resolve();"
              f"sys.path[:0]=[str(root/p) for p in {IMPORT_PATHS!r}]")


def bootstrap_command(python, root, script, args):
    code = PATH_SETUP + ";script=sys.argv.pop(1);sys.argv[0]=script;runpy.run_path(script,run_name='__main__')"
    return [str(python), "-I", "-B", "-c", code, str(root), str(script), *args]


class WorkBusy(ValueError):
    """A job is deferred because enrolled/observed work is still running."""


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""): h.update(block)
    return h.hexdigest()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def distribution_fingerprint(distribution):
    metadata, version = distribution.metadata, distribution.version
    name = metadata.get("Name")
    if isinstance(name, str) and name and isinstance(version, str) and version:
        return name.lower().replace("_", "-"), version
    # An incomplete installed record still participates in the environment.
    # PathDistribution's metadata entry identifies it without exposing its host path.
    try:
        entry = Path(distribution._path)
        if not entry.name or entry.is_symlink(): raise ValueError("unidentified metadata entry")
        if entry.is_file():
            files = [(entry.name, digest(entry))]
        elif entry.is_dir():
            files, pending = [], [entry]
            while pending:
                for path in pending.pop().iterdir():
                    if path.is_symlink(): raise ValueError("linked metadata entry")
                    if path.is_dir(): pending.append(path)
                    elif path.is_file(): files.append((path.relative_to(entry).as_posix(), digest(path)))
                    else: raise ValueError("unreadable metadata member")
            files.sort()
        else:
            raise ValueError("missing metadata entry")
        record = {"metadata": sorted(metadata.items()), "version": version, "files": files}
        return "<invalid-metadata>:" + entry.name, fingerprint(record)
    except (AttributeError, OSError, TypeError, ValueError) as exc:
        raise ValueError("environment package metadata unreadable or unidentified") from exc


def environment_info():
    return {"python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "packages": sorted(distribution_fingerprint(d) for d in importlib.metadata.distributions())}


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as f:
        temp = Path(f.name)
        f.write((json.dumps(value, sort_keys=True) + "\n").encode())
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)
    sync_dir(path.parent)


def sync_dir(path):
    if os.name == "posix":
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)


@contextlib.contextmanager
def work_lock(root, *, exclusive, blocking=False):
    import fcntl
    Path(root).mkdir(parents=True, exist_ok=True)
    with (Path(root) / "work.lock").open("a+") as f:
        mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        fcntl.flock(f, mode | (0 if blocking else fcntl.LOCK_NB))
        # Closing this descriptor releases our ownership. Explicit LOCK_UN
        # would also unlock a surviving child's inherited open description.
        yield f.fileno()


def gpu_busy(*, runner=subprocess.run):
    try:
        apps = runner(["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader,nounits"],
                      capture_output=True, text=True, timeout=15, check=False)
        load = runner(["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                      capture_output=True, text=True, timeout=15, check=False)
        if apps.returncode or load.returncode: return "GPU observation failed"
        if apps.stdout.strip(): return "GPU compute job"
        values = [int(v.strip()) for v in load.stdout.splitlines()]
        if not values: return "GPU observation empty"
        if any(v > 0 for v in values): return "GPU utilization"
    except (OSError, ValueError, subprocess.SubprocessError):
        return "GPU observation unavailable"
    return None


def perception_edits(roots):
    """Uncommitted payload code in an enrolled checkout. None when clean.

    Non-git legacy roots are ignored. A git failure holds the switch: an
    unreadable checkout is not treated as idle.
    """
    for root in roots:
        root = Path(root)
        if not (root / ".git").exists():
            continue
        try:
            result = subprocess.run(
                ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all", "--", *CHECKOUT_PREFIXES],
                capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.SubprocessError):
            return "checkout observation failed"
        if result.returncode != 0:
            return "checkout observation failed"
        if result.stdout.strip():
            return "uncommitted perception edits"
    return None


def checkout_script_conflict(source, work_dir, script):
    """Protect local edits; a clean older checkout does not override signed code."""
    local = Path(work_dir) / script
    if local.is_symlink() or not local.is_file():
        return None
    signed = Path(source) / script
    try:
        repo = subprocess.run(["git", "-C", str(work_dir), "rev-parse", "--is-inside-work-tree"],
                              capture_output=True, text=True, timeout=15)
        if repo.returncode == 0 and repo.stdout.strip() == "true":
            status = subprocess.run(["git", "-C", str(work_dir), "status", "--porcelain", "--untracked-files=all", "--", script],
                                    capture_output=True, text=True, timeout=15)
            if status.returncode: return "checkout observation failed"
            if not status.stdout.strip(): return None
        local_bytes = local.read_bytes()
        signed_bytes = signed.read_bytes() if signed.is_file() and not signed.is_symlink() else None
    except (OSError, subprocess.SubprocessError):
        return "checkout script unreadable"
    if signed_bytes != local_bytes:
        return "work checkout script differs from the signed release"
    return None


def legacy_busy(roots, *, proc=Path("/proc")):
    """Observe legacy Python/Isaac jobs without logging their secret-bearing argv."""
    for entry in proc.iterdir():
        if not entry.name.isdecimal() or int(entry.name) == os.getpid(): continue
        try:
            if entry.stat().st_uid != os.getuid(): continue
            comm = (entry / "comm").read_text().strip().lower()
            relevant = comm.startswith("python") or "isaac" in comm or "jupyter" in comm or comm in {"uv", "pip", "pip3"}
            if not relevant: continue
            args = (entry / "cmdline").read_bytes().decode(errors="replace").split("\x00")
            monitor = any(Path(a).name in {"tensorboard", "rosy_model_code.py", "review_app.py"} for a in args)
            if monitor: continue
            cwd = (entry / "cwd").resolve(strict=True)
            if (any(cwd.is_relative_to(Path(r).resolve()) for r in roots)
                    or any(PREFIX in a or "isaac-sim" in a for a in args)):
                return f"legacy work pid {entry.name}"
        except (FileNotFoundError, ProcessLookupError):
            continue
        except PermissionError:
            return "legacy process observation denied"
    return None


def unpack(archive, dest):
    """Manual extraction: code subtree only; no links, duplicates or special files."""
    dest = Path(dest)
    seen, total = set(), 0
    with tarfile.open(archive, "r:") as tar:
        entries = tar.getmembers()
        if len(entries) > 10000: raise ValueError("too many archive members")
        checked = []
        for item in entries:
            name = item.name.rstrip("/")
            path = PurePosixPath(name)
            if "\\" in name or path.is_absolute() or ".." in path.parts or str(path) != name:
                raise ValueError("unsafe archive path")
            ancestors = {str(p) for prefix in CODE_PREFIXES for p in PurePosixPath(prefix).parents}
            if item.isdir() and (name in ancestors or any(name == prefix.rstrip("/") for prefix in CODE_PREFIXES)): continue
            if not any(name == prefix or (prefix.endswith("/") and name.startswith(prefix)) for prefix in CODE_PREFIXES) or not (item.isfile() or item.isdir()):
                raise ValueError("archive must contain only approved model-code dependencies, without links")
            relative = path
            if set(relative.parts) & FORBIDDEN or any(p.startswith(".env") for p in relative.parts):
                raise ValueError("persistent data or secrets in code archive")
            if str(relative) in seen: raise ValueError("duplicate archive member")
            seen.add(str(relative))
            total += item.size
            if total > LIMIT: raise ValueError("expanded archive too large")
            checked.append((item, dest.joinpath(*relative.parts)))
        for item, target in checked:
            if item.isdir(): target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(item) as src, target.open("xb") as out:
                    shutil.copyfileobj(src, out)
                if os.name == "posix": target.chmod(0o444)
    for required in (PREFIX + "model/watch.py", PREFIX + "rosy_ml.py",
                     "middleware/perception/control/__init__.py", "contracts/foundation/core_common/__init__.py"):
        if not (dest / required).is_file(): raise ValueError("missing model-code entry point or dependency")
    if (dest / PREFIX / "camera_lane_map.py").is_file():
        if not all((dest / name).is_file() for name in CAMERA_MAP_FILES):
            raise ValueError("missing camera-map dependency")


def replace_link(root, target):
    root = Path(root)
    link = root / "current"
    if link.exists() and not link.is_symlink(): raise ValueError("current must be a symlink")
    if target is None:
        link.unlink(missing_ok=True)
    else:
        path = Path(target).resolve(strict=True)
        path.relative_to((root / "releases").resolve())
        temporary = root / "current.new"
        temporary.unlink(missing_ok=True)
        temporary.symlink_to(path, target_is_directory=True)
        os.replace(temporary, link)
    sync_dir(root)


class Updater:
    def __init__(self, root, key_id, public_key, python, *, environment=None, busy=None, health=None, legacy_roots=(), data_root=None, checkouts=()):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.key_id, self.public_key, self.python = key_id, Path(public_key), str(python)
        self.legacy_roots = tuple(legacy_roots)
        self.checkouts = tuple(checkouts) if checkouts else self.legacy_roots
        self.data_root = Path(data_root).resolve(strict=True) if data_root is not None else None
        if self.data_root is not None and (not self.data_root.is_dir()
                or self.data_root.is_relative_to((self.root / "releases").resolve())):
            raise ValueError("persistent data must be an existing directory outside releases")
        self.environment = environment or self.probe_environment
        self.busy = busy or (lambda: legacy_busy(self.legacy_roots) or gpu_busy())
        self.health = health or self.check_health

    def probe_environment(self):
        result = subprocess.run([self.python, "-I", str(Path(__file__).resolve()), "fingerprint"],
                                capture_output=True, text=True, check=True, timeout=60)
        return json.loads(result.stdout)["sha256"]

    def check_health(self, source):
        # Compile without writing into the immutable payload. CUDA work is tiny,
        # performed only inside the exclusive work lock after the idle guard.
        code = ("import ast,pathlib; p=pathlib.Path(__import__('sys').argv[1]); "
                "[ast.parse(f.read_bytes(), filename=str(f)) for f in p.rglob('*.py')]; "
                "import torch,onnx,onnxruntime,cv2,numpy,yaml,ultralytics,ncnn,pnnx; "
                "assert torch.cuda.is_available(); "
                "assert torch.ones(1,device='cuda').sum().item()==1")
        subprocess.run([self.python, "-I", "-c", code, str(source)],
                       capture_output=True, check=True, timeout=120)
        # These actual entrypoints eagerly import the committed control/core_common
        # closure. Isolated mode prevents ambient PYTHONPATH/user-site fallback;
        # --help exits before training, robot access or model delivery.
        scripts = ("rosy_ml.py", "model/watch.py", "model/intake.py", "model/convert.py",
                   "dataset/build.py", "dataset/review_app.py")
        if (Path(source) / PREFIX / "camera_lane_map.py").is_file():
            scripts += ("camera_lane_map.py",)
        for script in scripts:
            subprocess.run(bootstrap_command(self.python, source, Path(source) / PREFIX / script, ["--help"]),
                           cwd=source, capture_output=True, check=True, timeout=60)
        code = PATH_SETUP + ";import export_ncnn,export_ncnn_lane,autolabel,control,core_common"
        subprocess.run([self.python, "-I", "-B", "-c", code, str(source)],
                       cwd=source, capture_output=True, check=True, timeout=60)

    def state(self):
        p = self.root / "state.json"
        if not p.exists(): return {"sequence": 0, "failed": [], "source_commit": None}
        value = json.loads(p.read_text())
        if not isinstance(value, dict) or type(value.get("sequence")) is not int or not isinstance(value.get("failed"), list):
            raise ValueError("invalid durable updater state")
        return value

    def record(self, state, result, **fields):
        reason = fields.pop("reason", None)
        state.update(result=result, time=time.time(), reason=reason, **fields)
        atomic_json(self.root / "state.json", state)
        return state

    def read_candidate(self, folder):
        for name, maximum in [("release.json", 65536), ("release.json.sig", 16384), ("READY", 128), ("code.tar", LIMIT)]:
            p = folder / name
            if p.is_symlink() or not p.is_file() or p.stat().st_size > maximum:
                raise ValueError("missing or unsafe candidate file")
        raw = (folder / "release.json").read_bytes()
        if (folder / "READY").read_text().strip() != hashlib.sha256(raw).hexdigest():
            raise ValueError("candidate is not complete")
        verify_manifest_signature(raw, (folder / "release.json.sig").read_bytes(),
                                  trusted_key_id=self.key_id, public_key=self.public_key)
        v = json.loads(raw)
        if not isinstance(v, dict) or set(v) != {"schema", "source_commit", "sequence", "environment_sha256", "archive_sha256"} or v["schema"] != "rosy-model-code/1":
            raise ValueError("wrong model-code manifest")
        if type(v["sequence"]) is not int or not 0 < v["sequence"] < 2**63:
            raise ValueError("invalid sequence")
        for k, length in [("source_commit", 40), ("environment_sha256", 64), ("archive_sha256", 64)]:
            if not isinstance(v[k], str) or not re.fullmatch(f"[0-9a-f]{{{length}}}", v[k]):
                raise ValueError("invalid manifest digest")
        return v

    def run(self):
        try:
            with work_lock(self.root, exclusive=True): return self._run()
        except BlockingIOError:
            # No state write while a job/update holds the work lock.
            return {"result": "held", "reason": "work lock busy"}

    def _run(self):
        state = self.state()
        if state.get("pending"):
            p = state.pop("pending")
            replace_link(self.root, p["previous"])
            state["failed"].append(p["sequence"])
            return self.record(state, "recovered", reason="interrupted switch restored")
        if (self.root / "HOLD").exists(): return self.record(state, "held", reason="operator hold")
        busy = self.busy()
        if busy: return self.record(state, "held", reason=busy)
        edits = perception_edits(self.checkouts)
        if edits: return self.record(state, "held", reason=edits)
        candidates, rejected = [], False
        inbox = self.root / "inbox"
        inbox.mkdir(exist_ok=True)
        for folder in sorted(inbox.iterdir())[:1000]:
            if folder.is_symlink() or not folder.is_dir() or not (folder / "READY").exists(): continue
            try:
                manifest = self.read_candidate(folder)
                if manifest["sequence"] > state["sequence"] and manifest["sequence"] not in state["failed"]:
                    candidates.append((manifest["sequence"], folder, manifest))
            except ValueError:
                rejected = True
        if not candidates: return self.record(state, "rejected" if rejected else "idle")
        seq, folder, manifest = max(candidates, key=lambda v: v[0])
        state["desired_commit"] = manifest["source_commit"]
        if self.environment() != manifest["environment_sha256"]:
            return self.record(state, "held", reason="environment fingerprint differs; separate environment release required")
        previous = str((self.root / "current").resolve()) if (self.root / "current").is_symlink() else None
        releases = self.root / "releases"
        releases.mkdir(exist_ok=True)
        target = releases / f"{seq}-{manifest['source_commit']}"
        try:
            # Always use a fresh snapshot, also after a failed preparation.
            with tempfile.TemporaryDirectory(prefix="stage-", dir=releases) as directory:
                stage = Path(directory)
                archive = stage / "code.tar"
                shutil.copyfile(folder / "code.tar", archive)
                if digest(archive) != manifest["archive_sha256"]: raise ValueError("archive digest differs")
                source = stage / "source"
                unpack(archive, source)
                if self.data_root is not None:
                    (source / "data").symlink_to(self.data_root, target_is_directory=True)
                self.health(source)
                if target.exists(): raise ValueError("release directory already exists")
                os.replace(source, target)
                sync_dir(releases)
            state["sequence"] = seq
            state["pending"] = {"previous": previous, "sequence": seq}
            self.record(state, "switching")
            replace_link(self.root, target)
            self.health(target)
        except Exception as error:
            if state.get("pending"):
                replace_link(self.root, previous)
                state.pop("pending")
                result = "rolled-back"
            else: result = "rejected"
            state["sequence"] = max(seq, state["sequence"])
            state["failed"].append(seq)
            return self.record(state, result, reason=type(error).__name__)
        state.pop("pending")
        return self.record(state, "applied", source_commit=manifest["source_commit"],
                           environment_sha256=manifest["environment_sha256"], reason=None)


def build(repo, commit, sequence, env_hash, output, key_id, private_key, public_key):
    if not re.fullmatch("[0-9a-f]{40}", commit) or not re.fullmatch("[0-9a-f]{64}", env_hash) or not 0 < sequence < 2**63:
        raise ValueError("build requires full commit, environment hash and positive sequence")
    output = Path(output)
    if output.exists(): raise ValueError("candidate output already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix="build-") as directory:
        stage = Path(directory)
        map_job = subprocess.check_output(["git", "-C", str(repo), "ls-tree", "--name-only", commit,
                                           PREFIX + "camera_lane_map.py"]).strip()
        paths = CODE_PREFIXES if map_job else tuple(p for p in CODE_PREFIXES if p not in CAMERA_MAP_FILES)
        subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", "--output", str(stage / "code.tar"), commit, *paths], check=True)
        # Enforce the same source-only policy before signing. Worktree/ignored
        # files are never inputs; archive reads the committed Git object.
        unpack(stage / "code.tar", stage / "inspect")
        shutil.rmtree(stage / "inspect")
        v = {"schema": "rosy-model-code/1", "source_commit": commit, "sequence": sequence,
             "environment_sha256": env_hash, "archive_sha256": digest(stage / "code.tar")}
        raw = (json.dumps(v, sort_keys=True) + "\n").encode()
        (stage / "release.json").write_bytes(raw)
        (stage / "release.json.sig").write_bytes(sign_manifest_bytes(raw, key_id=key_id,
                                                  private_key=Path(private_key), public_key=Path(public_key)))
        (stage / "READY").write_text(hashlib.sha256(raw).hexdigest() + "\n")
        os.replace(stage, output)
        # TemporaryDirectory sees a moved directory and has nothing to clean.
    return v


def load_config(path):
    v = json.loads(Path(path).read_text())
    if set(v) != {"root", "key_id", "public_key", "python", "work_dir", "legacy_roots"}:
        raise ValueError("invalid model-code config fields")
    for k in ("root", "public_key", "python", "work_dir"):
        if not isinstance(v[k], str) or not Path(v[k]).is_absolute(): raise ValueError("config paths must be absolute")
    if not isinstance(v["legacy_roots"], list) or not v["legacy_roots"] or any(not Path(p).is_absolute() for p in v["legacy_roots"]):
        raise ValueError("legacy job roots must be enrolled")
    return v


def execute(config, script, args):
    root = Path(config["root"])
    # Serialize GPU jobs as well as code switches (D-434: no concurrent Isaac
    # and training). The child inherits the lock, including if its parent dies.
    with work_lock(root, exclusive=True, blocking=True) as lock_fd:
        busy = legacy_busy(config.get("legacy_roots", [])) or gpu_busy()
        if busy: raise WorkBusy("work busy: " + busy)
        state = Updater(root, config["key_id"], config["public_key"], config["python"]).state()
        if state.get("pending"): raise ValueError("interrupted update needs recovery first")
        source = (root / "current").resolve(strict=True)
        source.relative_to((root / "releases").resolve())
        perception = source / PREFIX
        file = (perception / script).resolve(strict=True)
        file.relative_to(perception)
        if file.suffix != ".py": raise ValueError("job entry point must be a Python script")
        conflict = checkout_script_conflict(perception, Path(config["work_dir"]) / PREFIX, script)
        if conflict: raise ValueError(conflict)
        env_hash = Updater(root, config["key_id"], config["public_key"], config["python"]).probe_environment()
        if env_hash != state.get("environment_sha256"):
            raise ValueError("job environment differs from the activated candidate")
        receipt = root / "jobs" / f"{time.time_ns()}-{os.getpid()}.json"
        job = {"source_commit": state["source_commit"], "environment_sha256": env_hash,
               "script": str(file.relative_to(perception)), "arguments_sha256": fingerprint(args), "started": time.time()}
        atomic_json(receipt, job)
        result = subprocess.run(bootstrap_command(config["python"], source, file, args), cwd=config["work_dir"],
                                pass_fds=(lock_fd,))
        job.update(exit_code=result.returncode, finished=time.time())
        atomic_json(receipt, job)
        return result.returncode


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("fingerprint")
    sub.add_parser("run")
    sub.add_parser("status")
    job = sub.add_parser("exec")
    job.add_argument("script")
    job.add_argument("args", nargs=argparse.REMAINDER)
    b = sub.add_parser("build")
    for name in ("repo", "commit", "environment-sha256", "output", "key-id", "private-key", "public-key"):
        b.add_argument("--" + name, required=True)
    b.add_argument("--sequence", required=True, type=int)
    a = p.parse_args()
    try:
        if a.command == "fingerprint":
            info = environment_info()
            print(json.dumps({"sha256": fingerprint(info), "environment": info}))
        elif a.command == "build":
            print(json.dumps(build(a.repo, a.commit, a.sequence, a.environment_sha256, a.output,
                                   a.key_id, a.private_key, a.public_key)))
        else:
            config = load_config(a.config)
            if a.command == "exec": return execute(config, a.script, a.args)
            u = Updater(config["root"], config["key_id"], config["public_key"], config["python"],
                        legacy_roots=config["legacy_roots"],
                        checkouts=(config["work_dir"], *config["legacy_roots"]),
                        data_root=Path(config["work_dir"]) / "data")
            result = u.run() if a.command == "run" else u.state()
            print(json.dumps(result, sort_keys=True))
            return int(result.get("result") in {"rejected", "rolled-back"})
    except WorkBusy as error:
        print(json.dumps({"result": "held", "reason": str(error)}))
        return 3
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({"result": "error", "reason": type(error).__name__}), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
