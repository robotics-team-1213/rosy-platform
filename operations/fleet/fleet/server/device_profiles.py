"""Descriptive device metadata in the Fleet database; never command authority."""

from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3
import time
import unicodedata

from .sqlite_policy import configure_connection, enable_wal


_DEVICE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
_FIELDS = {"display_name", "manufacturer", "model", "device_kind", "arm_count", "hardware_ids"}


def _device_id(value):
    if not isinstance(value, str) or _DEVICE_ID.fullmatch(value) is None:
        raise ValueError("device_id must be a stable identifier of at most 64 ASCII characters")


def _text(value, field, limit, *, required=False):
    if (not isinstance(value, str) or len(value) > limit
            or any(unicodedata.category(char) in {"Cc", "Cs"} for char in value)
            or (required and not value.strip())):
        raise ValueError(f"{field} must be a {'nonblank ' if required else ''}string of at most {limit} characters")
    return value


def _metadata(body):
    if not isinstance(body, dict) or body.keys() - _FIELDS:
        raise ValueError("profile must contain only descriptive metadata fields")
    result = {"display_name": _text(body.get("display_name"), "display_name", 80, required=True),
              "manufacturer": _text(body.get("manufacturer", ""), "manufacturer", 80),
              "model": _text(body.get("model", ""), "model", 80)}
    kind = body.get("device_kind")
    if kind not in ("manipulator", "mobile", "other"):
        raise ValueError("device_kind must be manipulator, mobile, or other")
    count = body.get("arm_count")
    if count is not None and (type(count) is not int or not 0 <= count <= 16
                              or (kind == "manipulator" and count == 0)):
        raise ValueError("arm_count must be null or an integer from 0 to 16 (at least 1 for manipulators)")
    hardware_ids = body.get("hardware_ids", [])
    if not isinstance(hardware_ids, list) or len(hardware_ids) > 16:
        raise ValueError("hardware_ids must be a list of at most 16 opaque identifiers")
    for value in hardware_ids:
        _text(value, "hardware_ids entry", 200, required=True)
    if len(set(hardware_ids)) != len(hardware_ids):
        raise ValueError("hardware_ids must be unique")
    return {**result, "device_kind": kind, "arm_count": count, "hardware_ids": hardware_ids}


def _profile(row):
    return {**json.loads(row["metadata_json"]), "device_id": row["device_id"],
            "updated_by": row["updated_by"], "updated_at": row["updated_at"],
            "connection_status": "not_checked", "control_enabled": False}


class DeviceProfileStore:
    """Create, list, read and replace profiles without touching enrollment or SiteRoster."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            enable_wal(connection)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS fleet_device_profiles (
                    device_id TEXT PRIMARY KEY,
                    metadata_json TEXT NOT NULL,
                    updated_by TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)

    def _connect(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return configure_connection(connection)

    def list_profiles(self):
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT * FROM fleet_device_profiles ORDER BY device_id").fetchall()
        return [_profile(row) for row in rows]

    def get_profile(self, device_id):
        _device_id(device_id)
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT * FROM fleet_device_profiles WHERE device_id=?", (device_id,)).fetchone()
        return _profile(row) if row is not None else None

    def put_profile(self, device_id, body, *, updated_by):
        """Replace descriptive fields atomically; omitted optional fields return to defaults."""
        _device_id(device_id)
        metadata = _metadata(body)
        _text(updated_by, "updated_by", 96, required=True)
        row = {"device_id": device_id, "metadata_json": json.dumps(metadata, ensure_ascii=False),
               "updated_by": updated_by, "updated_at": time.time()}
        with closing(self._connect()) as connection, connection:
            connection.execute("""
                INSERT INTO fleet_device_profiles(device_id, metadata_json, updated_by, updated_at)
                VALUES (:device_id, :metadata_json, :updated_by, :updated_at)
                ON CONFLICT(device_id) DO UPDATE SET
                    metadata_json=excluded.metadata_json,
                    updated_by=excluded.updated_by,
                    updated_at=excluded.updated_at
            """, row)
        return _profile(row)
