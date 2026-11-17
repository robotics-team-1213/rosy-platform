"""State types, journal records, and retention helpers for release activation (WP-2)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
import sys

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from layout import (  # noqa: E402
    ActivationRecord,
    ActivationUnreadable,
    read_activation,
    write_json_atomic,
)

JOURNAL_SCHEMA_VERSION = 1

#: The health check is bounded so a candidate that never comes up cannot hold
#: the device in an unusable state indefinitely.
DEFAULT_HEALTH_TIMEOUT_S = 90.0

#: Gap between health probes. Without it the bounded wait is a hot spin that
#: pegs a core on the Pi 5 for the whole timeout, during an update.
HEALTH_POLL_INTERVAL_S = 1.0


class RecoveryHeld(Exception):
    """The device is in RECOVERY HOLD and refuses to activate anything."""


class UpdateState(str, Enum):
    """States recorded in release-state.json and the journal."""

    #: Nothing has ever been installed. RECEIVED would assert that a bundle
    #: arrived, which on a factory-fresh device did not happen — and `state`
    #: is what a dashboard filters and displays, so it has to be true on its
    #: own. §8.1 draws the same distinction on the network side with
    #: UNPROVISIONED.
    NOT_INSTALLED = "NOT_INSTALLED"
    RECEIVED = "RECEIVED"
    SIGNATURE_VERIFIED = "SIGNATURE_VERIFIED"
    CHECKSUM_VERIFIED = "CHECKSUM_VERIFIED"
    COMPATIBILITY_CHECKED = "COMPATIBILITY_CHECKED"
    STAGED = "STAGED"
    CONFIG_BACKED_UP = "CONFIG_BACKED_UP"
    MIGRATION_VALIDATED = "MIGRATION_VALIDATED"
    ACTIVATING_CORE_ONLY = "ACTIVATING_CORE_ONLY"
    CORE_HEALTHY = "CORE_HEALTHY"
    ACTIVATED_CORE_ONLY = "ACTIVATED_CORE_ONLY"
    COMMISSIONING_REQUIRED = "COMMISSIONING_REQUIRED"
    ROLLING_BACK = "ROLLING_BACK"
    ROLLED_BACK_CORE_ONLY = "ROLLED_BACK_CORE_ONLY"
    RECOVERY_HOLD = "RECOVERY_HOLD"


#: States that do not imply anything was ever activated.
#:
#: The discriminator used to be "has any state been recorded", which was
#: right only because nothing yet records the seven steps that precede an
#: activation. The first time WP-4 records STAGED during a *first* install and
#: the download is interrupted, that device would hold itself and refuse its
#: own first install — the same brick through a different door. Holding is
#: correct from ACTIVATING_CORE_ONLY onward, which is the moment the device
#: first had something to lose, and the same boundary activate() already draws.
PRE_INSTALL_STATES = frozenset({
    UpdateState.NOT_INSTALLED,
    UpdateState.RECEIVED,
    UpdateState.SIGNATURE_VERIFIED,
    UpdateState.CHECKSUM_VERIFIED,
    UpdateState.COMPATIBILITY_CHECKED,
    UpdateState.STAGED,
    UpdateState.CONFIG_BACKED_UP,
    UpdateState.MIGRATION_VALIDATED,
})


@dataclass
class JournalEntry:
    state: str
    at: str
    detail: str = ""


@dataclass
class Journal:
    """What an interrupted activation left behind.

    Written and flushed *before* the activation record moves, so a device that
    loses power mid-update always has enough to decide what to do.
    """

    schema_version: int
    release_id: str
    candidate_activation: dict
    old_activation: dict | None
    old_current: str | None
    old_previous: str | None
    backup_path: str | None = None
    complete: bool = False
    states: list[dict] = field(default_factory=list)
    old_previous_activation: dict | None = None


@dataclass(frozen=True)
class Outcome:
    """The result of an activation, rollback or recovery."""

    state: UpdateState
    release_id: str | None
    detail: str

    @property
    def ok(self) -> bool:
        """Whether the device ended in a good activated state."""
        return self.state in {
            UpdateState.ACTIVATED_CORE_ONLY,
            UpdateState.ROLLED_BACK_CORE_ONLY,
        }

    @property
    def blocks_runtime(self) -> bool:
        """Whether rosy-release-recover.service must refuse to let boot proceed.

        Distinct from :attr:`ok`, and the distinction matters for exactly one
        case: a factory-fresh device has nothing activated, so ``ok`` is
        False, but nothing is wrong with it and the first-boot flow needs the
        boot to continue. Only a hold actually blocks.
        """
        return self.state is UpdateState.RECOVERY_HOLD


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class UpdaterStateJournalMixin:
    """Recorded state, journal, and recovery-hold persistence for :class:`Updater`."""

    # --- recorded state ---------------------------------------------------

    def record_state(self, state: UpdateState, release_id: str | None, detail: str = "") -> None:
        """Publish the current step for the dashboard and the audit trail."""
        write_json_atomic(
            self.layout.release_state,
            {
                "schema_version": JOURNAL_SCHEMA_VERSION,
                "state": state.value,
                "release_id": release_id,
                "detail": detail,
                "at": _now(),
            },
        )
        journal = self.read_journal()
        if journal is not None and not journal.complete:
            journal.states.append(asdict(JournalEntry(state=state.value, at=_now(), detail=detail)))
            self._write_journal(journal)

    def read_state(self) -> dict | None:
        """The last recorded step: absent, readable, or unreadable.

        Three outcomes, not two. Mirroring read_journal and returning None on
        a corrupt file would make an unreadable state read as *absent* — which
        flips a device that has lost its activation record into "never
        installed" and lets it boot with nothing. release-state.json sits in
        the one host path CORE can write, so a CORE bug truncating it must not
        be able to talk the device out of a hold.

        Raising is also wrong: this is on the boot path, and a traceback with
        no recorded reason is worse than a hold with one.
        """
        path = self.layout.release_state
        if not path.is_file():
            return None

        try:
            recorded = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
            return {"state": None, "release_id": None, "unreadable": str(exc)}
        if not isinstance(recorded, dict):
            return {"state": None, "release_id": None, "unreadable": "not an object"}
        return recorded

    # --- journal ----------------------------------------------------------

    def _write_journal(self, journal: Journal) -> None:
        write_json_atomic(self.layout.journal, asdict(journal))

    def read_journal(self) -> Journal | None:
        path = self.layout.journal
        if not path.is_file():
            return None

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        if data.get("schema_version") != JOURNAL_SCHEMA_VERSION:
            return None
        return Journal(
            schema_version=data["schema_version"],
            release_id=data["release_id"],
            candidate_activation=data["candidate_activation"],
            old_activation=data.get("old_activation"),
            old_current=data.get("old_current"),
            old_previous=data.get("old_previous"),
            backup_path=data.get("backup_path"),
            complete=data.get("complete", False),
            states=data.get("states", []),
            old_previous_activation=data.get("old_previous_activation"),
        )

    def _clear_journal(self) -> None:
        self.layout.journal.unlink(missing_ok=True)

    def _current_activation(self) -> ActivationRecord | None:
        try:
            return read_activation(self.layout)
        except ActivationUnreadable:
            return None

    def _complete_journal(self, journal: Journal) -> None:
        """Mark the journal done without discarding the state trail.

        record_state appends to the journal on disk, so writing back a stale
        in-memory copy erases every step recorded since it was read.
        """
        current = self.read_journal() or journal
        current.complete = True
        self._write_journal(current)

    # --- recovery hold ----------------------------------------------------

    def read_recovery_hold(self) -> dict | None:
        """The persisted hold, if the device is in one."""
        path = self.layout.recovery_hold
        if not path.is_file():
            return None

        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # An unreadable marker is still a marker: hold rather than guess.
            return {"release_id": None, "detail": "recovery hold marker is unreadable"}

    def clear_recovery_hold(self) -> None:
        """Release the hold. A deliberate operator action, never automatic."""
        self.layout.recovery_hold.unlink(missing_ok=True)


def prunable_image_digests(
    all_digests: set[str],
    *,
    activation_records: list[ActivationRecord | None],
    manifests_by_release: dict[str, dict],
) -> set[str]:
    """Digests safe to delete: everything no live activation set refers to.

    Rollback works by pointing the activation record back at the previous
    release, which is only possible while that release's container images
    still exist. A plain ``docker image prune`` does not know that, so image
    cleanup must subtract the digests named by every activation the device
    can still return to — current and previous at minimum.
    """
    protected: set[str] = set()
    for record in activation_records:
        if record is None:
            continue
        manifest = manifests_by_release.get(record.release_id)
        containers = (manifest or {}).get("containers") or {}
        if not containers:
            # A manifest that is missing, unreadable, or names no images tells
            # us nothing about what this live release needs. Not knowing is a
            # reason to delete nothing, not a reason to delete everything.
            return set()
        protected.update(str(d) for d in containers.values())

    return all_digests - protected


def releases_to_keep(
    installed: list[str],
    *,
    keep_last: int,
    protected: set[str],
) -> set[str]:
    """Which release directories survive retention.

    ``protected`` holds the releases an activation record still points at.
    Those are kept regardless of age: deleting the release a device can roll
    back to converts a recoverable failure into a site visit.
    """
    ordered = sorted(installed, reverse=True)
    return set(ordered[:keep_last]) | (protected & set(installed))
