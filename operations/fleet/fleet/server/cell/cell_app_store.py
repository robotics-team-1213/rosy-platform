"""Revisioned Cell application documents; execution remains in Fleet's ledger."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from core_common.protocol.schemas import utc_now_iso


class DocumentChanged(ValueError):
    """The caller no longer holds the stored document revision."""


class CellAppStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS cell_app_documents (
                kind TEXT NOT NULL, document_id TEXT NOT NULL,
                digest TEXT NOT NULL, document TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY (kind, document_id))""")

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _identity(kind, identifier):
        if kind not in {"recipe", "cell"} or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", identifier):
            raise ValueError("kind must be recipe/cell and id must be a bounded document name")

    @staticmethod
    def _document(row):
        if row is None:
            return None
        return {"kind": row["kind"], "id": row["document_id"], "digest": row["digest"],
                "document": json.loads(row["document"]), "updated_at": row["updated_at"]}

    def get(self, kind, identifier):
        self._identity(kind, identifier)
        with self._connect() as db:
            return self._document(db.execute(
                "SELECT * FROM cell_app_documents WHERE kind=? AND document_id=?", (kind, identifier),
            ).fetchone())

    def list(self):
        with self._connect() as db:
            return [{"kind": row["kind"], "id": row["document_id"], "digest": row["digest"],
                     "updated_at": row["updated_at"]} for row in db.execute(
                         "SELECT * FROM cell_app_documents ORDER BY kind, document_id")]

    def save(self, kind, identifier, document, *, expected_digest):
        self._identity(kind, identifier)
        if not isinstance(document, dict):
            raise ValueError("document must be an object")
        encoded = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(encoded.encode("utf-8")) > 64 * 1024:
            raise ValueError("document exceeds 64 KiB")
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        updated_at = utc_now_iso()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT digest FROM cell_app_documents WHERE kind=? AND document_id=?",
                                 (kind, identifier)).fetchone()
            if (current["digest"] if current else None) != expected_digest:
                raise DocumentChanged("document changed; reload before saving")
            db.execute("""INSERT INTO cell_app_documents VALUES (?,?,?,?,?)
                ON CONFLICT(kind,document_id) DO UPDATE SET
                digest=excluded.digest, document=excluded.document, updated_at=excluded.updated_at""",
                       (kind, identifier, digest, encoded, updated_at))
        return {"kind": kind, "id": identifier, "digest": digest,
                "document": json.loads(encoded), "updated_at": updated_at}
