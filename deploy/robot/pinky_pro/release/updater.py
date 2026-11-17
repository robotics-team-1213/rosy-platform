"""Release activation, rollback and power-loss recovery (WP-2).

Activation is the moment an update can leave a robot unbootable, so the order
here is deliberate and the journal is written before anything moves.

The sequence, matching the design's activation procedure:

1. Record the old activation, the candidate activation and the display
   pointers in the journal, and flush it.
2. Stop the running runtime.
3. Replace ``activation.json`` atomically with the candidate.
4. Repoint the cosmetic ``current``/``previous`` symlinks.
5. Start the candidate in ``core`` mode and health-check it under a bound.
6. On success, mark ``previous`` and complete the journal.
7. On failure, restore the old activation record atomically, restore the
   pointers and bring the previous release back up in ``core``.

If power is lost anywhere in the middle, :meth:`Updater.recover` reads the
journal on the next boot and finishes the story before the runtime is allowed
to start. That ordering is why ``rosy-release-recover.service`` must run
before ``rosy-runtime.service``, with the runtime depending on it — otherwise
a half-activated device boots a candidate nobody ever health-checked.

Neither activation nor rollback ever restores ``motor`` or ``hardware``. Both
end core-only, and returning to a hardware mode is a separate field approval.

Runtime control and health checking are injected so the whole sequence runs
in a temporary directory, including the failure paths that are impractical to
provoke on real hardware.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, replace
from pathlib import Path
import subprocess
import sys
import time

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from layout import (  # noqa: E402, F401
    ACTIVATION_RUNTIME_MODE,
    ActivationRecord,
    ActivationUnreadable,
    Layout,
    freeze_tree,
    read_activation,
    update_display_pointers,
    write_activation,
    write_json_atomic,
)
from storage import check_update_headroom, reclaim  # noqa: E402
from updater_helpers import (  # noqa: E402, F401
    DEFAULT_HEALTH_TIMEOUT_S,
    HEALTH_POLL_INTERVAL_S,
    JOURNAL_SCHEMA_VERSION,
    PRE_INSTALL_STATES,
    Journal,
    JournalEntry,
    Outcome,
    RecoveryHeld,
    UpdateState,
    UpdaterStateJournalMixin,
    _now,
    prunable_image_digests,
    releases_to_keep,
)


class Updater(UpdaterStateJournalMixin):
    """Drives activation, rollback and recovery against a :class:`Layout`."""

    def __init__(
        self,
        layout: Layout,
        *,
        stop_runtime: Callable[[], None],
        start_runtime: Callable[[str], None],
        health_check: Callable[[], bool],
        disable_runtime: Callable[[], None] | None = None,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.layout = layout
        self._stop_runtime = stop_runtime
        self._start_runtime = start_runtime
        self._health_check = health_check
        # A RECOVERY HOLD has to actually keep the runtime down, not merely be
        # returned to the caller. Falls back to stopping it, which is weaker
        # than disabling the unit but never worse than nothing.
        self._disable_runtime = disable_runtime or stop_runtime
        self._sleep = sleep or time.sleep
        #: What the last completed activation reclaimed, for the dashboard.
        self.last_storage_report = None
        # A real monotonic clock by default: a stub that always returns the
        # same value turns the bounded wait into an infinite loop.
        self._clock = clock or time.monotonic

    # --- activation -------------------------------------------------------

    def check_headroom(self, bundle_bytes: int) -> list:
        """Whether an update of this size may start at all.

        Called before a bundle is unpacked. Refusing here costs nothing;
        refusing halfway through leaves a partial staging tree behind.
        """
        return check_update_headroom(bundle_bytes, staging=self.layout.staging)

    def activate(
        self,
        candidate: ActivationRecord,
        *,
        backup_path: Path | None = None,
        health_timeout_s: float = DEFAULT_HEALTH_TIMEOUT_S,
    ) -> Outcome:
        """Activate ``candidate``, rolling back if its CORE does not come up."""
        if candidate.runtime_mode != ACTIVATION_RUNTIME_MODE:
            raise ValueError(
                f"an activation must install {ACTIVATION_RUNTIME_MODE!r}, got {candidate.runtime_mode!r}"
            )

        # A held device must not be updated as though nothing were wrong. The
        # hold is what the next boot reads, so activating through it reports
        # success and then comes back disabled — the worst of both designs.
        # Clearing the hold is a deliberate act; requiring it here is what
        # makes it one.
        hold = self.read_recovery_hold()
        if hold is not None:
            raise RecoveryHeld(
                f"device is held for recovery ({hold.get('detail', 'no detail')}); "
                "clear the hold deliberately before installing a release"
            )

        old = self._current_activation()
        import json
        old_previous = (json.loads(self.layout.previous_activation.read_text(encoding="utf-8"))
                        if self.layout.previous_activation.exists() else None)

        # Freeze before the record moves. Immutability is what rollback rests
        # on: the previous set has to still be what was activated. A function
        # nothing calls is worse than none — it reads as enforcement.
        self._freeze(candidate)

        journal = Journal(
            schema_version=JOURNAL_SCHEMA_VERSION,
            release_id=candidate.release_id,
            candidate_activation=asdict(candidate),
            old_activation=asdict(old) if old else None,
            old_current=old.release_id if old else None,
            old_previous=self._link_target_id(self.layout.previous_link),
            backup_path=str(backup_path) if backup_path else None,
            old_previous_activation=old_previous,
        )
        self._write_journal(journal)

        self.record_state(UpdateState.ACTIVATING_CORE_ONLY, candidate.release_id)

        self._stop_runtime()
        write_activation(self.layout, candidate)
        update_display_pointers(
            self.layout,
            current=candidate.release_id,
            previous=old.release_id if old else None,
        )
        try:
            self._start_runtime(candidate.runtime_mode)
            healthy = self._await_health(health_timeout_s)
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            # A failed compose start is an unhealthy candidate too. Preserve the
            # journal and roll back; do not expose command stderr or environment.
            return self._roll_back(journal, detail=f"candidate startup failed: {type(exc).__name__}")

        if healthy:
            self.record_state(UpdateState.CORE_HEALTHY, candidate.release_id)
            self._write_previous(asdict(old) if old else None)
            journal = self.read_journal() or journal
            journal.complete = True
            self._write_journal(journal)
            self.record_state(UpdateState.ACTIVATED_CORE_ONLY, candidate.release_id)
            self._clear_journal()
            # Only now. Reclaiming before this point can delete the tree a
            # rollback is about to need.
            self._reclaim(keep_staged=())
            return Outcome(
                UpdateState.ACTIVATED_CORE_ONLY,
                candidate.release_id,
                "candidate CORE reached health within the bound",
            )

        return self._roll_back(
            journal,
            detail=f"candidate CORE did not become healthy within {health_timeout_s:g}s",
        )

    def _reclaim(self, *, keep_staged) -> None:
        """Free what is safe to free, and never fail an activation for it.

        Cleanup runs after the device is already in a good state, so a problem
        here is a disk-space problem, not an update problem. Letting it raise
        would turn a completed activation into a reported failure.
        """
        try:
            self.last_storage_report = reclaim(self.layout, keep_staged=keep_staged)
        except OSError as exc:  # pragma: no cover - defensive
            self.last_storage_report = None
            self.record_state(
                UpdateState.ACTIVATED_CORE_ONLY,
                None,
                f"activation succeeded; storage reclamation failed: {exc}",
            )

    def _freeze(self, record: ActivationRecord) -> None:
        """Drop write permission across the release and its generations."""
        for path in (
            Path(record.release_path),
            self.layout.config_generation(record.config_generation),
            self.layout.data_generation(record.data_generation),
        ):
            if path.is_dir():
                freeze_tree(path)

    def _await_health(self, timeout_s: float) -> bool:
        """Poll the injected health check until it passes or the bound expires."""
        deadline = self._clock() + timeout_s
        while True:
            if self._health_check():
                return True
            if self._clock() >= deadline:
                return False
            self._sleep(HEALTH_POLL_INTERVAL_S)

    def _link_target_id(self, link: Path) -> str | None:
        try:
            if link.is_symlink():
                return Path(link.readlink()).name
        except OSError:
            pass
        return None

    # --- rollback ---------------------------------------------------------

    def _write_previous(self, record: dict | None) -> None:
        if record is None:
            self.layout.previous_activation.unlink(missing_ok=True)
        else:
            write_json_atomic(self.layout.previous_activation, record, mode=0o600)

    def _roll_back(self, journal: Journal, *, detail: str) -> Outcome:
        """Restore the previous activation set and bring it up core-only."""
        self.record_state(UpdateState.ROLLING_BACK, journal.release_id, detail)

        self._stop_runtime()

        if journal.old_activation is None:
            # Nothing to go back to — a failed first activation.
            self.layout.activation.unlink(missing_ok=True)
            update_display_pointers(self.layout, current=None, previous=None)
            return self._enter_recovery_hold(
                journal,
                release_id=journal.release_id,
                detail=f"{detail}; no previous release to fall back to",
            )

        previous = self._previous_record(journal)
        write_activation(self.layout, previous)
        update_display_pointers(self.layout, current=previous.release_id, previous=journal.old_previous)
        try:
            self._start_runtime(previous.runtime_mode)
            healthy = self._await_health(DEFAULT_HEALTH_TIMEOUT_S)
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
            healthy = False

        if not healthy:
            return self._enter_recovery_hold(
                journal,
                release_id=previous.release_id,
                detail="the previous release also failed its health check; runtime left disabled",
            )

        self._write_previous(journal.old_previous_activation)
        self._complete_journal(journal)
        self.record_state(UpdateState.ROLLED_BACK_CORE_ONLY, previous.release_id, detail)
        self._clear_journal()
        return Outcome(UpdateState.ROLLED_BACK_CORE_ONLY, previous.release_id, detail)

    def _settled(self, detail: str, release_id: str | None = None) -> Outcome:
        """Nothing to finish — but only if there is something to boot.

        Clearing a journal is not the same as having a usable device. If the
        activation record is gone or unreadable, letting the runtime start
        would boot nothing at all, so that is a hold in its own right.

        "Gone" and "never existed" are different, though, and conflating them
        bricks a factory-fresh device: recover() runs before the runtime on
        every boot, so an unprovisioned robot would hold itself on boot one
        and then refuse its own first activation. release-state.json is the
        discriminator — absent until activate() first records a state — so a
        device with no history is simply not yet installed, not held.
        """
        current = self._current_activation()
        if current is None and self._never_activated():
            return Outcome(
                UpdateState.NOT_INSTALLED,
                None,
                "no release installed yet; awaiting first activation",
            )
        if current is None:
            detail = "no usable activation record; the device has nothing to boot"
            # Persist it like any other hold, so an operator inspecting
            # /var/lib/rosy sees a marker rather than having to infer the state.
            write_json_atomic(
                self.layout.recovery_hold,
                {
                    "schema_version": JOURNAL_SCHEMA_VERSION,
                    "release_id": release_id,
                    "detail": detail,
                    "at": _now(),
                },
            )
            self._disable_runtime()
            self.record_state(UpdateState.RECOVERY_HOLD, release_id, detail)
            return Outcome(UpdateState.RECOVERY_HOLD, release_id, detail)
        return Outcome(UpdateState.ACTIVATED_CORE_ONLY, current.release_id, detail)

    def _never_activated(self) -> bool:
        """Whether this device has ever reached an activation.

        Keyed on how far the recorded state got rather than on whether a file
        exists, so the steps that precede a first install do not read as
        history. An unreadable state file counts as history: not knowing is a
        reason to hold, not a reason to boot.
        """
        recorded = self.read_state()
        if recorded is None:
            return True
        if recorded.get("unreadable"):
            return False
        try:
            state = UpdateState(recorded.get("state"))
        except ValueError:
            return False  # a state this build does not know is not reassurance
        return state in PRE_INSTALL_STATES

    def _previous_record(self, journal: Journal) -> ActivationRecord:
        """The record to roll back to, forced to core.

        A robot commissioned into ``motor`` that then fails an update must not
        come back with its wheels live on a release whose health check just
        failed. Restoring the old record verbatim did exactly that, while
        still reporting ROLLED_BACK_CORE_ONLY. Re-approving a hardware mode is
        a field decision, so rollback always lands in core and the operator
        re-commissions deliberately.
        """
        try:
            restored = ActivationRecord(**journal.old_activation)
        except TypeError as exc:
            # Propagates out of recover() without writing a hold marker. That
            # is deliberate: rosy-release-recover.service is a Requires= of
            # rosy-runtime.service, so a non-zero exit already keeps the
            # runtime down. Writing a marker from a path we cannot interpret
            # would claim more understanding than we have.
            raise ActivationUnreadable(
                f"journal holds an activation record this build cannot read: {exc}"
            ) from exc
        return replace(restored, runtime_mode=ACTIVATION_RUNTIME_MODE)

    def _enter_recovery_hold(
        self, journal: Journal, *, release_id: str | None, detail: str
    ) -> Outcome:
        """Stop, and stay stopped across reboots.

        A hold that lives only in a return value is gone by the next boot. The
        marker is written before the journal is completed so the recover unit
        sees the hold first and refuses to let the runtime start.
        """
        write_json_atomic(
            self.layout.recovery_hold,
            {
                "schema_version": JOURNAL_SCHEMA_VERSION,
                "release_id": release_id,
                "detail": detail,
                "at": _now(),
            },
        )
        self._complete_journal(journal)
        self.record_state(UpdateState.RECOVERY_HOLD, release_id, detail)
        self._disable_runtime()
        return Outcome(UpdateState.RECOVERY_HOLD, release_id, detail)

    # --- recovery ---------------------------------------------------------

    def recover(self) -> Outcome:
        """Finish an interrupted activation before the runtime may start.

        Called by ``rosy-release-recover.service`` on every boot. With no
        journal there is nothing to do. With an unfinished one, the device
        goes back to the activation set that was known good rather than
        booting a candidate whose health was never established.
        """
        hold = self.read_recovery_hold()
        if hold is not None:
            self._disable_runtime()
            self.record_state(UpdateState.RECOVERY_HOLD, hold.get("release_id"), hold.get("detail", ""))
            return Outcome(
                UpdateState.RECOVERY_HOLD,
                hold.get("release_id"),
                hold.get("detail", "device is held for recovery"),
            )

        journal = self.read_journal()
        if journal is None:
            return self._settled("no interrupted update")

        if journal.complete:
            self._clear_journal()
            return self._settled("journal was already complete; cleaned up", journal.release_id)

        return self._roll_back(
            journal,
            detail="update was interrupted before the candidate was confirmed healthy",
        )
