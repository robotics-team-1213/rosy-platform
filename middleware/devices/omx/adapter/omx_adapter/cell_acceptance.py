"""Owner-local journal of the accepted Rosy Cell cell and recipes (D-404 §6, D-403 §9).

The store is the only source of the two values the owner checks a CELL_TRANSFER against: the
accepted cell hash (``capability_current`` before journaling, the planner before planning) and
the accepted recipe's item geometry (grasp width/depth, height) looked up by recipe hash.

Validation of the documents is a port. The device adapter does not import the palletizing
process (D-413 §1: integrations own no process rules); the owner composition injects a
validator that runs the palletizing loaders in this process. The store itself recomputes every
hash from the stored text, checks the kinematics revision and refuses a replacement while an
Action is unresolved, so a caller cannot satisfy the checks with a hash it merely asserts.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import threading
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

_GEOMETRY_KEYS = frozenset({"grasp_width_m", "grasp_depth_m", "height_m"})


def canonical_sha256(document: Mapping[str, Any]) -> str:
    """sha256 of sorted, space-free JSON: the same bytes as the palletizing content hash."""
    return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode("utf-8")).hexdigest()


class CellAcceptanceRefused(PermissionError):
    """The owner refused to record the cell or recipe as accepted."""


@dataclass(frozen=True)
class ValidatedCell:
    sha256: str
    kinematics_revision: str


@dataclass(frozen=True)
class ValidatedRecipe:
    sha256: str
    items: Mapping[str, Mapping[str, float]]


class CellDocumentValidator(Protocol):
    """Composition-provided process validation (palletizing loaders and compiler)."""

    def validate_cell(self, cell: Mapping[str, Any]) -> ValidatedCell: ...

    def validate_recipe(self, recipe: Mapping[str, Any], cell: Mapping[str, Any]) -> ValidatedRecipe: ...


def _geometry(items: object) -> dict[str, dict[str, float]]:
    if not isinstance(items, Mapping) or not items:
        raise CellAcceptanceRefused("recipe item geometry is missing")
    result = {}
    for item, geometry in items.items():
        if not isinstance(geometry, Mapping) or set(geometry) != _GEOMETRY_KEYS:
            raise CellAcceptanceRefused(f"recipe item geometry for {item!r} is incomplete")
        values = {}
        for key in sorted(_GEOMETRY_KEYS):
            value = geometry[key]
            minimum_ok = (value >= 0) if key == "grasp_depth_m" else (value > 0)
            if isinstance(value, bool) or not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or not minimum_ok:
                raise CellAcceptanceRefused(f"recipe item geometry {item}.{key} is invalid")
            values[key] = float(value)
        result[str(item)] = values
    return result


class CellAcceptanceStore:
    """Single accepted cell plus the recipes accepted against it, in the owner's SQLite file."""

    def __init__(self, path: Path | str, *, workcell_id: str, instance_id: str,
                 kinematics_revision: str, config_revision: str,
                 validator: CellDocumentValidator,
                 unresolved_actions: Callable[[], Sequence[object]],
                 now: Callable[[], datetime] | None = None) -> None:
        if validator is None or not callable(getattr(validator, "validate_cell", None)) \
                or not callable(getattr(validator, "validate_recipe", None)):
            raise ValueError("a cell/recipe document validator is required")
        if not callable(unresolved_actions):
            raise ValueError("an unresolved-Action reader is required")
        for name, value in (("workcell_id", workcell_id), ("instance_id", instance_id),
                            ("kinematics_revision", kinematics_revision),
                            ("config_revision", config_revision)):
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError(f"{name} must be a non-empty trimmed string")
        self.path = Path(path)
        self.workcell_id, self.instance_id = workcell_id, instance_id
        self.kinematics_revision, self.config_revision = kinematics_revision, config_revision
        self.validator = validator
        self.unresolved_actions = unresolved_actions
        self.now = now or (lambda: datetime.now(timezone.utc))
        self._lock = threading.RLock()
        with closing(self._connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS omx_accepted_cell (
                    workcell_id TEXT NOT NULL,
                    instance_id TEXT NOT NULL,
                    cell_sha256 TEXT NOT NULL,
                    cell_json TEXT NOT NULL,
                    kinematics_revision TEXT NOT NULL,
                    accepted_by TEXT NOT NULL,
                    accepted_at TEXT NOT NULL,
                    PRIMARY KEY(workcell_id, instance_id)
                );
                CREATE TABLE IF NOT EXISTS omx_accepted_recipes (
                    workcell_id TEXT NOT NULL,
                    instance_id TEXT NOT NULL,
                    recipe_sha256 TEXT NOT NULL,
                    cell_sha256 TEXT NOT NULL,
                    recipe_json TEXT NOT NULL,
                    items_json TEXT NOT NULL,
                    accepted_by TEXT NOT NULL,
                    accepted_at TEXT NOT NULL,
                    PRIMARY KEY(workcell_id, instance_id, recipe_sha256)
                );
                CREATE TABLE IF NOT EXISTS omx_cell_acceptance_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workcell_id TEXT NOT NULL,
                    instance_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    document_sha256 TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _stamp(self) -> str:
        now = self.now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise RuntimeError("acceptance clock must return an aware timestamp")
        return now.astimezone(timezone.utc).isoformat(timespec="microseconds")

    @staticmethod
    def _actor(actor_id: str) -> str:
        if not isinstance(actor_id, str) or not actor_id or actor_id != actor_id.strip() or len(actor_id) > 96:
            raise ValueError("actor_id must be a non-empty trimmed identifier")
        return actor_id

    def _cell_row(self, connection: sqlite3.Connection) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT * FROM omx_accepted_cell WHERE workcell_id=? AND instance_id=?",
            (self.workcell_id, self.instance_id),
        ).fetchone()

    def accept_cell(self, cell: Mapping[str, Any], *, actor_id: str) -> dict[str, Any]:
        actor_id = self._actor(actor_id)
        if not isinstance(cell, Mapping):
            raise CellAcceptanceRefused("cell must be a JSON object")
        text = json.dumps(cell, sort_keys=True, separators=(",", ":"), allow_nan=False)
        document = json.loads(text)
        sha256 = canonical_sha256(document)
        try:
            validated = self.validator.validate_cell(document)
        except (TypeError, ValueError) as exc:
            raise CellAcceptanceRefused(f"cell is invalid: {exc}") from None
        if not isinstance(validated, ValidatedCell) or validated.sha256 != sha256:
            raise CellAcceptanceRefused("validated cell hash differs from the owner's recomputed hash")
        if validated.kinematics_revision != self.kinematics_revision:
            raise CellAcceptanceRefused("cell kinematics_revision is not this owner's kinematics")
        with self._lock, closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                if self.unresolved_actions():
                    raise CellAcceptanceRefused("cell replacement is refused while an Action is unresolved")
                now = self._stamp()
                current = self._cell_row(connection)
                if current is None or current["cell_sha256"] != sha256:
                    # Recipes were checked against the previous cell; they must be accepted again.
                    connection.execute(
                        "DELETE FROM omx_accepted_recipes WHERE workcell_id=? AND instance_id=?",
                        (self.workcell_id, self.instance_id),
                    )
                connection.execute(
                    """INSERT OR REPLACE INTO omx_accepted_cell
                       (workcell_id, instance_id, cell_sha256, cell_json, kinematics_revision,
                        accepted_by, accepted_at) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (self.workcell_id, self.instance_id, sha256, text, self.kinematics_revision,
                     actor_id, now),
                )
                self._event(connection, "CELL_ACCEPTED", sha256, actor_id, now)
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                raise
        return {"cell_sha256": sha256, "kinematics_revision": self.kinematics_revision,
                "accepted_by": actor_id, "accepted_at": now}

    def accept_recipe(self, recipe: Mapping[str, Any], *, actor_id: str) -> dict[str, Any]:
        actor_id = self._actor(actor_id)
        if not isinstance(recipe, Mapping):
            raise CellAcceptanceRefused("recipe must be a JSON object")
        text = json.dumps(recipe, sort_keys=True, separators=(",", ":"), allow_nan=False)
        document = json.loads(text)
        sha256 = canonical_sha256(document)
        with self._lock, closing(self._connect()) as connection:
            cell_row = self._cell_row(connection)
            if cell_row is None:
                raise CellAcceptanceRefused("a recipe needs an accepted cell first")
            try:
                validated = self.validator.validate_recipe(document, json.loads(cell_row["cell_json"]))
            except (TypeError, ValueError) as exc:
                raise CellAcceptanceRefused(f"recipe is invalid for the accepted cell: {exc}") from None
            if not isinstance(validated, ValidatedRecipe) or validated.sha256 != sha256:
                raise CellAcceptanceRefused("validated recipe hash differs from the owner's recomputed hash")
            items = _geometry(validated.items)
            connection.execute("BEGIN IMMEDIATE")
            try:
                if self._cell_row(connection)["cell_sha256"] != cell_row["cell_sha256"]:
                    raise CellAcceptanceRefused("the accepted cell changed during recipe validation")
                now = self._stamp()
                connection.execute(
                    """INSERT OR REPLACE INTO omx_accepted_recipes
                       (workcell_id, instance_id, recipe_sha256, cell_sha256, recipe_json,
                        items_json, accepted_by, accepted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (self.workcell_id, self.instance_id, sha256, cell_row["cell_sha256"], text,
                     json.dumps(items, sort_keys=True), actor_id, now),
                )
                self._event(connection, "RECIPE_ACCEPTED", sha256, actor_id, now)
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                raise
        return {"recipe_sha256": sha256, "cell_sha256": cell_row["cell_sha256"],
                "items": items, "accepted_by": actor_id, "accepted_at": now}

    def _event(self, connection: sqlite3.Connection, event_type: str, sha256: str,
               actor_id: str, now: str) -> None:
        connection.execute(
            """INSERT INTO omx_cell_acceptance_events
               (workcell_id, instance_id, event_type, document_sha256, actor_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (self.workcell_id, self.instance_id, event_type, sha256, actor_id, now),
        )

    def current(self) -> dict[str, Any] | None:
        """Readback for ``GET /cell``: the accepted cell text and the recipes bound to it."""
        with self._lock, closing(self._connect()) as connection:
            cell_row = self._cell_row(connection)
            if cell_row is None:
                return None
            recipes = connection.execute(
                "SELECT recipe_sha256, recipe_json FROM omx_accepted_recipes "
                "WHERE workcell_id=? AND instance_id=? AND cell_sha256=? ORDER BY recipe_sha256",
                (self.workcell_id, self.instance_id, cell_row["cell_sha256"]),
            ).fetchall()
        return {"cell_sha256": cell_row["cell_sha256"], "cell": json.loads(cell_row["cell_json"]),
                "kinematics_revision": cell_row["kinematics_revision"],
                "accepted_by": cell_row["accepted_by"], "accepted_at": cell_row["accepted_at"],
                "recipes": {row["recipe_sha256"]: json.loads(row["recipe_json"]) for row in recipes}}

    def accepted_cell_sha256(self) -> str | None:
        with self._lock, closing(self._connect()) as connection:
            row = self._cell_row(connection)
        return None if row is None else row["cell_sha256"]

    def accepted_item_geometry(self, recipe_sha256: str, item: str) -> dict[str, float] | None:
        """Geometry of ``item`` in a recipe accepted against the current cell, else None."""
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                """SELECT r.items_json FROM omx_accepted_recipes r JOIN omx_accepted_cell c
                   ON r.workcell_id=c.workcell_id AND r.instance_id=c.instance_id
                   AND r.cell_sha256=c.cell_sha256
                   WHERE r.workcell_id=? AND r.instance_id=? AND r.recipe_sha256=?""",
                (self.workcell_id, self.instance_id, recipe_sha256),
            ).fetchone()
        if row is None:
            return None
        geometry = json.loads(row["items_json"]).get(item)
        return dict(geometry) if isinstance(geometry, Mapping) else None

    def capability_current(self, grant: object) -> bool:
        """ActionRunner hook: a CELL_TRANSFER grant matches the accepted cell, recipe and item."""
        if getattr(grant, "action_kind", None) != "CELL_TRANSFER":
            return False  # this owner admits only the fixed-cell transfer
        transfer = getattr(grant, "cell_transfer", None)
        if (transfer is None or transfer.frame != "robot_base"
                or getattr(grant, "config_revision", None) != self.config_revision):
            return False
        if self.accepted_cell_sha256() != transfer.cell_sha256:
            return False
        return self.accepted_item_geometry(transfer.recipe_sha256, transfer.item) is not None


__all__ = [
    "CellAcceptanceRefused", "CellAcceptanceStore", "CellDocumentValidator", "ValidatedCell",
    "ValidatedRecipe", "canonical_sha256",
]
