"""The updater's apply, health and rollback (D-412; moved out of rosy_auto_update.py, D-798)."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
import shlex
import shutil
import subprocess

import rosy_claim
from auto_update_host import (ACTIVATE_TIMEOUT_S, BACKOFF_MAX_S, CLAIM_HOLDER, CLAIM_TTL_S, CORE_DOWN_NOTE,
    Deferred, HEALTH_HOLD_S, HEALTH_POLL_S, HEALTH_UNITS, _last_json, NATIVE_JOURNAL, _outcome,
    PRUNE_MIN_AGE_S, READY_TIMEOUT_S, RELEASE_ID, RELEASE_LOCK, RELEASE_SYNC, RELEASES, RESTART_TIMEOUT_S,
    ROLLBACK_MAX_RETRIES, SELF_UNIT, STAGE_BACKOFF_BASE_S, SYNC_TIMEOUT_S, SYSTEMCTL_TIMEOUT_S, _tail,
    TRUSTED_KEY, UNIT_NAME, UpdateError, _z)


class UpdaterApply:
    """Updater mixin: systemctl, sync, restart, health, settle, roll back, recover, prune and apply."""

    # apply --------------------------------------------------------------------------

    def _systemctl(self, *args: str, timeout: float = SYSTEMCTL_TIMEOUT_S) -> subprocess.CompletedProcess:
        return self.host.run(["systemctl", *args], timeout)

    def _main_pid(self, unit: str) -> int:
        shown = self._systemctl("show", "-p", "MainPID", "--value", unit)
        text = shown.stdout.strip()
        return int(text) if shown.returncode == 0 and text.isdigit() else 0

    def _core_release_check(self) -> None:
        """CORE's main process must run from current, else restart rosy-core (push parity)."""
        current = self.host.current_release()
        pid = self._main_pid("rosy-core.service")
        if pid and current and self.host.process_cwd(pid) == self.release_path(current):
            return
        restarted = self._systemctl("restart", "rosy-core.service", timeout=RESTART_TIMEOUT_S)
        if restarted.returncode != 0:
            raise UpdateError(f"CORE_RESTART_FAILED: {_tail(restarted.stderr)}")

    def _sync(self, script: str) -> dict:
        synced = self.host.run(["python3", "-B", script], SYNC_TIMEOUT_S)
        result = _last_json(synced.stdout)
        if synced.returncode != 0 or not result or result.get("ok") is not True:
            raise UpdateError(f"IMAGE_LAYER_SYNC_FAILED: {_tail(synced.stderr or synced.stdout)}")
        return result

    def _restart(self, sync_result: dict) -> list[str]:
        # Never restart this unit: it is the process running the update.
        units = [unit for unit in sync_result.get("restart_units") or []
                 if isinstance(unit, str) and UNIT_NAME.fullmatch(unit) and unit != SELF_UNIT]
        if units:
            restarted = self._systemctl("restart", *units, timeout=RESTART_TIMEOUT_S)
            if restarted.returncode != 0:
                raise UpdateError(f"RESTART_FAILED: {' '.join(units)}: {_tail(restarted.stderr)}")
        return units

    def _ready(self) -> None:
        ready = self.host.run(self._ready_command(), READY_TIMEOUT_S)
        if ready.returncode != 0:
            raise UpdateError(f"CORE_NOT_READY: {_tail(ready.stderr)}")

    def _failed_units(self) -> list[str] | None:
        """Failed rosy-* units (never this one), or None when systemctl cannot say."""
        listed = self._systemctl("list-units", "--state=failed", "--plain", "--no-legend", "--all", "rosy-*")
        if listed.returncode != 0:
            return None
        failed = [line.split()[0] for line in listed.stdout.splitlines() if line.split()]
        return sorted(unit for unit in failed if unit != SELF_UNIT)

    def _baseline(self) -> dict:
        """Which health units ran (and from where) and which rosy-* units had failed, before activation."""
        active = {}
        for unit in HEALTH_UNITS:
            if self._systemctl("is-active", "--quiet", unit).returncode == 0:
                pid = self._main_pid(unit)
                active[unit] = self.host.process_cwd(pid) if pid else None
        return {"active": active, "failed": self._failed_units() or []}

    @staticmethod
    def _baseline_notes(baseline: dict) -> list[str]:
        notes = [f"{unit} was not active before the apply; not checked"
                 for unit in HEALTH_UNITS[1:] if unit not in baseline.get("active", {})]
        if baseline.get("failed"):
            notes.append(f"already failed before the apply: {' '.join(baseline['failed'])}")
        return notes

    def _unit_problems(self, release_id: str, baseline: dict) -> list[str]:
        """rosy-core always; io/camera only if they ran before; only newly failed units count."""
        problems = []
        want = self.release_path(release_id)
        required = [unit for unit in HEALTH_UNITS
                    if unit == "rosy-core.service" or unit in baseline.get("active", {})]
        for unit in required:
            if self._systemctl("is-active", "--quiet", unit).returncode != 0:
                problems.append(f"{unit} is not active")
                continue
            pid = self._main_pid(unit)
            cwd = self.host.process_cwd(pid) if pid else None
            if cwd != want:
                problems.append(f"{unit} runs from {cwd}, not {want}")
        if (Path(want) / "deploy/robot/native/image-layer/boot/catalog.json").is_file():
            for unit in ("rosy-network-agent.service", "rosy-network-recovery.timer"):
                if self._systemctl("is-active", "--quiet", unit).returncode != 0:
                    problems.append(f"{unit} is not active")
        failed = self._failed_units()
        if failed is None:
            problems.append("cannot list failed units")
        else:
            new = [unit for unit in failed if unit not in baseline.get("failed", [])]
            if new:
                problems.append(f"failed units: {' '.join(new)}")
        return problems

    def _health(self, release_id: str, baseline: dict) -> None:
        self._ready()
        deadline = self.host.now() + _dt.timedelta(seconds=HEALTH_HOLD_S)
        while True:
            problems = self._unit_problems(release_id, baseline)
            if problems:
                raise UpdateError(f"HEALTH: {'; '.join(problems)}")
            if self.host.now() >= deadline:
                return
            self.host.sleep(HEALTH_POLL_S)

    def _journal(self, state: dict, step: str) -> None:
        """Record the step before doing it, and keep the claim alive for the next one (review M8)."""
        state["applying"]["step"] = step
        self._save_state(state)
        self._update_marker(state["applying"])
        try:
            claim = rosy_claim.check(self.root, now=self.host.now())
            if (claim is None or claim.get("holder") != CLAIM_HOLDER
                    or not rosy_claim.refresh(self.root, CLAIM_HOLDER, CLAIM_TTL_S, now=self.host.now())):
                raise Deferred("update claim was lost; waiting before the next step")
        except (OSError, ValueError, rosy_claim.ClaimBusy) as exc:
            raise Deferred("update claim could not be verified") from exc

    def _settle(self, state: dict, release_id: str) -> dict:
        """Everything after activation; commit, or roll back on any failure."""
        # A journal without a baseline (none is written that way) checks CORE only.
        baseline = state["applying"].get("baseline") or {"active": {}, "failed": []}
        notes = self._baseline_notes(baseline) + ([state["applying"]["note"]] if state["applying"].get("note") else [])
        try:
            self._journal(state, "core-release-check")
            self._recheck_waived(state)
            self._core_release_check()
            self._journal(state, "image-layer-sync")
            result = self._sync(str(Path(self.release_path(release_id)) / RELEASE_SYNC))
            self._journal(state, "restart")
            self._recheck_waived(state)
            self._restart(result)
            self._journal(state, "health")
            self._health(release_id, baseline)
        except Deferred as exc:
            return self._finish(state, "ineligible", f"finishing {release_id} deferred: {exc}", release_id)
        except UpdateError as exc:
            return self._roll_back(state, release_id, "; ".join([str(exc), *notes]))
        except Exception as exc:  # noqa: BLE001 - a bug after activation must still roll back
            return self._roll_back(state, release_id, "; ".join([f"UNEXPECTED: {exc!r}", *notes]))
        state["applying"] = None
        state["staged"] = None
        (state.get("apply_errors") or {}).pop(release_id, None)
        (state.get("self_rolled_back") or {}).pop(release_id, None)
        committed = [item for item in state.get("committed") or [] if item != release_id]
        state["committed"] = (committed + [release_id])[-20:]
        self._result(state, release_id, "committed", "; ".join(["healthy for 60 s", *notes]))
        self._prune(state)
        return self._finish(state, "committed", f"{release_id} is healthy", release_id)

    def _recheck_waived(self, state: dict) -> None:
        """Re-review N4: a waived resume whose CORE is back needs the normal idleness check."""
        if state["applying"].get("note") != CORE_DOWN_NOTE or self._core_down():
            return
        report = self.eligibility(own_claim_ok=True)
        if not report["eligible"]:
            raise Deferred("; ".join(report["reasons"]))
        state["applying"].pop("note", None)

    def _rollback_tail(self, release_id: str) -> list[str]:
        """Bring the image layer and CORE back to whatever release is current now."""
        try:
            self._inverse_boot_layer(release_id)
        except (UpdateError, OSError, ValueError) as exc:
            return [str(exc)]  # Never downgrade the coordinator while its inverse is unresolved.
        # The release now current may predate D-388; fall back to the copy in the
        # release rolled away from (it syncs from current all the same).
        current = self.host.current_release() or ""
        script = Path(self.release_path(current)) / RELEASE_SYNC
        if not script.is_file():
            script = Path(self.release_path(release_id)) / RELEASE_SYNC
        problems = []
        for step in (lambda: self._restart(self._sync(str(script))), self._restore_display,
                     self._core_release_check, self._ready):
            try:
                step()
            except UpdateError as exc:
                problems.append(str(exc))
            except Exception as exc:  # noqa: BLE001 - finish the other steps
                problems.append(f"UNEXPECTED: {exc!r}")
        return problems

    def _inverse_boot_layer(self, release_id: str) -> None:
        journal = self.root / "var/lib/rosy/image-layer-backup/boot-transition.json"
        if not journal.exists() and not journal.is_symlink():
            return
        script = str(Path(self.release_path(release_id)) / RELEASE_SYNC)
        inverse = self.host.run(["python3", "-B", script, "--root", str(self.root),
                                 "--inverse-before-legacy-sync"], SYNC_TIMEOUT_S)
        result = _last_json(inverse.stdout)
        if inverse.returncode != 0 or not result or result.get("ok") is not True:
            raise UpdateError("BOOT_INVERSE: rollback held; continuity inverse could not be verified")

    def _roll_back(self, state: dict, release_id: str, why: str, mark_failed: bool = True) -> dict:
        """Roll back. A rollback that cannot run now stays journaled and is retried (review M7)."""
        applying = state["applying"]
        first = applying.get("step") != "rollback"
        applying.update(why=why, mark_failed=mark_failed)
        self._journal(state, "rollback")
        if first:
            self._history("rollback_started", release_id, why)
        if mark_failed:
            self._mark_failed(state, release_id, why)  # recorded now: never retried, even mid-rollback
        problems = []
        gave_up = refused = False
        if self.host.current_release() == release_id:
            rolled = self.host.run(["bash", self._native("rollback-release.sh")], ACTIVATE_TIMEOUT_S)
            kind, error = _outcome(rolled)
            if kind != "ok":
                self._recover_native()  # re-review N8: a dead rollback may leave the journal too
            if kind in ("busy", "transient", "refused"):
                applying["rollback_attempts"] = applying.get("rollback_attempts", 0) + 1
                if applying["rollback_attempts"] <= ROLLBACK_MAX_RETRIES:  # the first try + 5 retries
                    self._save_state(state)
                    return self._finish(state, "error", f"ROLLBACK_PENDING: {error}; retrying on the next run",
                                        release_id)
                # Re-review N12: stop retrying and ask a person.
                gave_up = True
                problems.append(f"rollback could not run after {ROLLBACK_MAX_RETRIES} retries ({error}); operator "
                                "action required: rosy-release-push.ps1 -Rollback")
            elif kind == "definitive":
                refused = True
                problems.append(f"rollback: {error}")
        # Verification review 2, HIGH 1: only a rollback that really moved current away
        # is ours; one that gave up or was refused leaves the release current, and a later
        # operator rollback of it is an operator rollback (N9).
        moved = not gave_up and not refused and self.host.current_release() != release_id
        if not problems:
            problems = self._rollback_tail(release_id)
        if any("BOOT_INVERSE" in problem for problem in problems):
            return self._finish(state, "held", "; ".join(problems), release_id)
        if not mark_failed and moved:
            # previous is now above current: not an operator rollback (N9), and the
            # release stays retryable (N7). HIGH 2: the apply error is counted even
            # when the tail had problems, so backoff and escalation bound the loop.
            state.setdefault("self_rolled_back", {})[release_id] = _z(self.host.now())
            self._apply_error(state, release_id, why)
        note = applying.get("note")
        state["applying"] = None
        detail = why if not problems else f"{why}; rollback incomplete: {'; '.join(problems)}"
        if note and note not in detail:
            detail = f"{detail}; {note}"
        # Final verification LOW 1: a refused rollback is as stuck as one that gave up.
        self._result(state, release_id, "rollback_failed" if gave_up or refused else "rolled_back", detail)
        self._prune(state)
        return self._finish(state, "rolled_back" if not problems else "failed", detail, release_id)

    def _recover_native(self) -> None:
        """An activation that died mid-way left native_release's journal: recover, restart the runtime."""
        if not (self.root / NATIVE_JOURNAL).exists():
            return
        recovered = self.host.run(["python3", "-B", self._native("native_release.py"), "--root", str(self.root),
                                   "--public-key", self._dev(TRUSTED_KEY), "recover"], ACTIVATE_TIMEOUT_S)
        kind, error = _outcome(recovered)
        if kind != "ok":
            self._history("native_recover_failed", None, error)
            return
        started = self._systemctl("start", "rosy-runtime.target", timeout=RESTART_TIMEOUT_S)
        self._history("native_recovered", None, f"runtime start exit {started.returncode}")

    def _release_claim(self) -> None:
        try:
            rosy_claim.release(self.root, CLAIM_HOLDER)
        except (rosy_claim.ClaimBusy, OSError) as exc:
            self._history("claim_release_failed", None, str(exc))

    def _apply_error(self, state: dict, release_id: str, message: str) -> None:
        """Re-review N7: transient apply failures back off like staging errors."""
        record = state.setdefault("apply_errors", {}).setdefault(release_id, {"attempts": 0})
        record["attempts"] += 1
        record["last"] = message
        delay = min(STAGE_BACKOFF_BASE_S * 2 ** (record["attempts"] - 1), BACKOFF_MAX_S)
        record["retry_after"] = _z(self.host.now() + _dt.timedelta(seconds=delay))

    def _prune(self, state: dict) -> None:
        """Keep current, previous and the staged release; drop every other release directory (review M5)."""
        current = self.host.current_release()
        if current is None:
            return
        keep = {current, self.host.previous_release(), state.get("staged")} - {None}
        pruned = []
        try:
            with self._locked_file(self.root / RELEASE_LOCK):
                from os_factory_release import pinned_factory
                try:
                    factory = pinned_factory(self.root)
                except ValueError:
                    return  # Unknown factory binding must never make it a prune candidate.
                if factory is not None:
                    keep.add(factory)
                cutoff = self.host.now().timestamp() - PRUNE_MIN_AGE_S
                for path in sorted((self.root / RELEASES).iterdir()):
                    if (path.name in keep or not RELEASE_ID.fullmatch(path.name) or path.is_symlink()
                            or not path.is_dir() or path.stat().st_mtime > cutoff):
                        continue
                    shutil.rmtree(path, ignore_errors=True)
                    pruned.append(path.name)
        except OSError:
            return  # native_release is busy: prune next time
        if pruned:
            self._history("pruned", None, " ".join(pruned))

    def apply(self, release_id: str, state: dict) -> dict:
        """Activate ``release_id`` under the claim. Refuses anything not newer than current."""
        if problem := self._maintenance_problem():
            raise UpdateError(problem)
        current = self.host.current_release()
        if current is None or not RELEASE_ID.fullmatch(release_id) or not release_id > current:
            raise UpdateError(f"NOT_NEWER: {release_id} is not above the current release {current}")
        try:
            rosy_claim.acquire(self.root, CLAIM_HOLDER, f"auto-update to {release_id}", CLAIM_TTL_S,
                               now=self.host.now())
        except rosy_claim.ClaimBusy as exc:
            holder = (exc.claim or {}).get("holder")
            return self._finish(state, "ineligible", f"claim held by {holder}", release_id)
        try:
            state["applying"] = {"release_id": release_id, "previous": current, "step": "activate",
                                 "started_at": _z(self.host.now()), "boot_id": self.host.boot_id(),
                                 "baseline": self._baseline()}
            # Review M2: one more look right before anything stops. What is left is the
            # moment between this read and the activator stopping the runtime (ADR R4).
            busy = self._inputs_problems()
            if busy:
                state["applying"] = None
                return self._finish(state, "ineligible", f"robot became busy: {'; '.join(busy)}", release_id)
            self._save_state(state)
            self._finish(state, "applying", f"activating {release_id} (from {current})", release_id)
            # Re-review N1: native_release runs our precheck after its verify and right
            # before it stops the runtime, so hold/seal/idleness are judged at that moment.
            precheck = f"python3 -B {shlex.quote(self._native('rosy_auto_update.py'))} --root " \
                       f"{shlex.quote(str(self.root))} precheck"
            activated = self.host.run(["env", f"ROSY_ACTIVATE_PRECHECK={precheck}", "bash",
                                       self._native("activate-release.sh"), release_id], ACTIVATE_TIMEOUT_S)
            kind, error = _outcome(activated)
            if kind == "ok":
                return self._settle(state, release_id)
            if kind == "busy":
                state["applying"] = None
                return self._finish(state, "waiting", f"{error}; retrying on the next run", release_id)
            if kind == "refused":
                state["applying"] = None
                return self._finish(state, "ineligible", f"robot became busy: {error}", release_id)
            # Review H3: a dead activation may have left native_release's journal.
            self._recover_native()
            definitive = kind == "definitive"
            if self.host.current_release() == release_id:
                return self._roll_back(state, release_id, f"activation: {error}", mark_failed=definitive)
            state["applying"] = None
            if not definitive:
                self._apply_error(state, release_id, f"activation: {error}")
                return self._finish(state, "error", f"ACTIVATION_TRANSIENT: {error}; retrying on the next run",
                                    release_id)
            self._mark_failed(state, release_id, f"activation: {error}")
            image_required = error.startswith("NATIVE_PYTHON_RUNTIME:")
            self._result(state, release_id, "image_required" if image_required else "refused", f"activation: {error}")
            return self._finish(state, "image_required" if image_required else "failed",
                                f"activation refused: {error}", release_id)
        finally:
            self._release_claim()

    def _core_down(self) -> bool:
        """True only when systemd says CORE is stopped (or crash-looping) with no main process.

        Re-review N2: fail closed. A failed call or an unreadable answer means running.
        """
        shown = self._systemctl("show", "-p", "ActiveState,SubState,MainPID", "rosy-core.service")
        if shown.returncode != 0:
            return False
        values = dict(line.split("=", 1) for line in shown.stdout.splitlines() if "=" in line)
        active, sub, pid = values.get("ActiveState"), values.get("SubState"), values.get("MainPID")
        stopped = active in ("inactive", "failed") or (active == "activating" and sub == "auto-restart")
        return stopped and pid == "0"
