"""Job resolution and execution under the existing installed controller guards."""
import os
from pathlib import Path
import time
from types import SimpleNamespace


def job_entry(source, script, *, runtime):
    """(entry file, conflict base, conflict name, mapped path or None) for a job name.

    A JOB_ENTRY_POINTS name resolves to exactly its one signed file; any other name
    only under the CLI holder PREFIX. '../', absolute and symlinked escapes raise ValueError."""
    r = SimpleNamespace(**runtime)
    source = Path(source).resolve(strict=True)
    # Existing signed releases retain their original bytes, paths and job names.
    # New candidates require LEARNING_REQUIRED; this only resolves a retained release.
    if script != "camera_lane_map.py" and not (source / "learning/registry/perception/watch.py").is_file():
        for prefix in r.LEGACY_LEARNING_PREFIXES:
            perception = source / prefix
            if (perception / "model/watch.py").is_file():
                file = (perception / script).resolve(strict=True)
                file.relative_to(perception)
                return file, perception, script, None
    mapped = r.JOB_ENTRY_POINTS.get(script) if isinstance(script, str) else None
    if mapped is not None:
        file = (source / mapped).resolve(strict=True)
        if file.relative_to(source) != Path(mapped):
            raise ValueError("job entry point is not its mapped file")
        return file, source, mapped, mapped
    perception = source / r.PREFIX
    file = (perception / script).resolve(strict=True)
    file.relative_to(perception)
    return file, perception, script, None


def execute(config, script, args, *, source_expectation=None, runtime):
    r = SimpleNamespace(**runtime)
    expected = r.model_code_source.validate_expectation(source_expectation) if source_expectation is not None else None
    root = Path(config["root"])
    # Serialize GPU jobs as well as code switches (D-434: no concurrent Isaac
    # and training). The child inherits the lock, including if its parent dies.
    with r.work_lock(root, exclusive=True, blocking=True) as lock_fd:
        busy = r.legacy_busy(config.get("legacy_roots", [])) or r.gpu_busy()
        if busy: raise r.WorkBusy("work busy: " + busy)
        state = r.Updater(root, config["key_id"], config["public_key"], config["python"]).state()
        if state.get("pending"): raise ValueError("interrupted update needs recovery first")
        source = (root / "current").resolve(strict=True)
        source.relative_to((root / "releases").resolve())
        file, base, name, mapped = r.job_entry(source, script)
        if file.suffix != ".py": raise ValueError("job entry point must be a Python script")
        local = Path(config["work_dir"]) / (base.relative_to(source) if mapped is None else "")
        conflict = r.checkout_script_conflict(base, local, name)
        if conflict: raise ValueError(conflict)
        if script != "camera_lane_map.py":
            # Retained enrolled paths must not lose their local edit guard after a move.
            for prefix in r.LEGACY_LEARNING_PREFIXES:
                legacy = Path(config["work_dir"]) / prefix / Path(script).parent
                conflict = r.checkout_script_conflict(file.parent, legacy, Path(script).name)
                if conflict: raise ValueError(conflict)
        env_hash = r.Updater(root, config["key_id"], config["public_key"], config["python"]).probe_environment()
        if env_hash != state.get("environment_sha256"):
            raise ValueError("job environment differs from the activated candidate")
        # Finish preparatory probes before measuring the bytes the child will use.
        proof = None
        if expected is not None:
            if (not (root / "current").is_symlink() or source.parent != (root / "releases").resolve()
                    or Path(os.readlink(root / "current")) != source):
                raise ValueError("strict source requires a direct installed release")
            # Keep lexical enrollment ancestry: resolving current must not hide a linked root.
            installed = root / "releases" / source.name
            proof = r.model_code_source.verify_source(installed, key_id=config["key_id"],
                        public_key=config["public_key"], policy=r.source_policy(),
                        data_root=Path(config["work_dir"]) / "data" if (installed / "data").is_symlink() else None)
            if (any(proof[key] != value for key, value in expected.items())
                    or any(state.get(key) != proof[key] for key in ("sequence", "source_commit", "environment_sha256"))
                    or source.name != f"{proof['sequence']}-{proof['source_commit']}"):
                raise ValueError("installed signed source differs from pinned activation")
        receipt = root / "jobs" / f"{time.time_ns()}-{os.getpid()}.json"
        job = {"source_commit": state["source_commit"], "environment_sha256": env_hash,
               "script": str(file.relative_to(base)) if mapped is None else script,
               "arguments_sha256": r.fingerprint(args), "started": time.time()}
        if proof is not None: job["source_proof"] = proof
        if mapped is not None: job["entry"] = mapped
        r.atomic_json(receipt, job)
        result = r.subprocess.run(r.bootstrap_command(config["python"], source, file, args), cwd=config["work_dir"],
                                pass_fds=(lock_fd,))
        job.update(exit_code=result.returncode, finished=time.time())
        r.atomic_json(receipt, job)
        return result.returncode
