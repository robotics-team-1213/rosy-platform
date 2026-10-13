"""Durable learning stages: one writer, verified outputs, terminal quality rejection."""
import datetime
import hashlib
import json
import os
from pathlib import Path


class JobError(ValueError):
    pass


class Rejected(JobError):
    pass


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def receipt(values=None, files=()):
    return {"values": values or {},
            "files": {str(Path(p).resolve()): sha(p) for p in files}}


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class Job:
    def __init__(self, folder, inputs):
        self.folder = Path(folder).resolve()
        self.folder.mkdir(parents=True, exist_ok=True)
        self.path = self.folder / "state.json"
        self.signature = hashlib.sha256(json.dumps(inputs, sort_keys=True,
                                                   allow_nan=False).encode()).hexdigest()
        self.inputs = inputs
        self.lock = None
        self._load()

    def _load(self):
        if self.path.exists():
            self.state = json.loads(self.path.read_text(encoding="utf-8"))
            if self.state.get("input_signature") != self.signature:
                raise JobError("job inputs changed; use a new job directory")
        else:
            self.state = {"schema": "rosy.learning.job/1", "input_signature": self.signature,
                          "inputs": self.inputs, "steps": {}, "outcome": "running"}

    def _save(self):
        target = self.path.with_suffix(".json.tmp")
        with target.open("w", encoding="utf-8") as stream:
            json.dump(self.state, stream, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(target, self.path)

    def __enter__(self):
        self.lock = (self.folder / ".lock").open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                self.lock.seek(0)
                if not self.lock.read(1):
                    self.lock.write(b"0")
                    self.lock.flush()
                self.lock.seek(0)
                msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.lock.close()
            self.lock = None
            raise JobError("job is already running") from exc
        try:
            self._load()  # read again while holding the writer lock
            self._save()
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, exc_type, exc, traceback):
        if self.lock:
            if isinstance(exc, Rejected):
                self.state.update(outcome="rejected", outcome_error=str(exc))
                self._save()
            self.lock.close()  # closing the descriptor releases the OS lock
            self.lock = None

    def step(self, name, action):
        if self.lock is None:
            raise JobError("job writer lock required")
        if self.state["outcome"] == "rejected":
            raise Rejected("job was rejected; use a new job for a new candidate")
        previous = self.state["steps"].get(name, {})
        if previous.get("status") == "done":
            result = previous["receipt"]
            for path, digest in result["files"].items():
                if not Path(path).is_file() or sha(path) != digest:
                    raise JobError(f"completed output changed or missing: {path}")
            return result["values"]
        attempt = previous.get("attempts", 0) + 1
        history = previous.get("history", [])
        if previous:
            history = [*history, {k: v for k, v in previous.items() if k != "history"}]
        row = {"status": "running", "attempts": attempt, "started_at": _now(), "history": history}
        self.state["steps"][name] = row
        self._save()
        try:
            result = action(attempt)
            if not isinstance(result, dict) or not {"files", "values"} <= result.keys():
                raise JobError("stage must return a receipt")
            row.update(status="done", receipt=result, ended_at=_now())
            self._save()
            return result["values"]
        except BaseException as exc:
            row.update(status="rejected" if isinstance(exc, Rejected) else "failed",
                       error=f"{type(exc).__name__}: {exc}", ended_at=_now())
            if isinstance(exc, Rejected):
                self.state["outcome"] = "rejected"
            self._save()
            raise

    def finish(self, outcome="ready"):
        if self.lock is None or self.state["outcome"] == "rejected":
            raise JobError("cannot finish unlocked/rejected job")
        if outcome not in ("ready", "candidate"):
            raise JobError("unsupported job outcome")
        self.state["outcome"] = outcome
        self._save()
