#!/usr/bin/env python3
"""Intake readings from this cell PC to its Fleet (D-996 2-3): written to a local outbox first, resent unchanged.

The PC sends what it read (a tag id, unreadable, or a mismatch) at the conveyor end or the A/B wrist; the cell Fleet
maps the tag to an object_ref, compares it with the trip's declaration and writes the port events. So the PC never
holds an app's cargo code (D4). The observation_ref is a fresh uuid per reading, so it never repeats after a restart,
and the reading is stored before it is sent, so a resend is the same reading (Fleet answers with the same rows).

  port_event_outbox.py send --arm ARM     resend every unsent reading (also run before each carry)
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
from uuid import uuid4

HERE = Path(__file__).resolve()
for extra in (HERE.parents[3] / "contracts/foundation",):
    if extra.is_dir() and str(extra) not in sys.path:
        sys.path.append(str(extra))

from core_common.protocol.port_events import IntakeReading  # noqa: E402


def outbox_dir() -> Path:
    from joint_tune import lock_root

    return lock_root() / "intake-readings" / "outbox"


def reading(point: str, result: dict, *, arm_mission_id: str | None = None,
            observed_at: datetime | None = None) -> IntakeReading:
    """A cell_identity point result ({"state", "tag"?}) as the reading Fleet translates."""
    return IntakeReading(observation_ref="obs-" + uuid4().hex, point=point, state=result["state"],
                         tag=result.get("tag"), arm_mission_id=arm_mission_id,
                         observed_at=observed_at or datetime.now(timezone.utc))


def queue(item: IntakeReading, directory: Path | None = None) -> Path:
    directory = directory or outbox_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{item.observation_ref}.json"
    if not path.exists():  # the first write wins: a resend must carry the stored bytes
        tmp = path.with_suffix(".tmp")
        tmp.write_text(item.model_dump_json(), encoding="utf-8")
        tmp.replace(path)
    return path


def send(link, directory: Path | None = None) -> bool:
    """Resend every unsent reading; a file leaves the outbox only once Fleet recorded it. False if any stays."""
    ok = True
    for path in sorted((directory or outbox_dir()).glob("*.json"), key=lambda p: p.stat().st_mtime):
        try:
            link.post_intake_reading(IntakeReading.model_validate_json(path.read_text(encoding="utf-8")))
        except Exception as exc:  # unreachable, refused or a bad file: it stays for the next send
            print(f"intake reading {path.name} not sent: {type(exc).__name__}: {str(exc)[:120]}")
            ok = False
            continue
        path.unlink()
    return ok


def main(argv=None) -> int:
    import argparse
    import os

    from workcell_observation_bridge import ArmIncidentLink

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=["send"])
    ap.add_argument("--arm", required=True, help="any arm of this workcell: its token identifies the cell PC")
    args = ap.parse_args(argv)
    link = ArmIncidentLink.from_environment(args.arm, os.environ)
    if link is None:
        print("no observation configuration on this PC")
        return 1
    return 0 if send(link) else 1


if __name__ == "__main__":
    sys.exit(main())
