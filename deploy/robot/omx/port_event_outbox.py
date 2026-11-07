#!/usr/bin/env python3
"""Port events from this cell PC to its Fleet (D-996 2): written to a local outbox first, resent with the same event_id.

An identity fact from cell_identity becomes container.received_at_intake (observed) or container.handling_failed
(MISMATCH / UNREADABLE). The observation_ref is a fresh uuid per observation, so it never repeats after a restart, and
the event is stored before it is sent, so a resend is byte-for-byte the same event (Fleet answers with the same row).

  port_event_outbox.py send      resend every unsent event (also run before each carry, like the incident outbox)
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

from core_common.protocol.port_events import PortEvent, event_id  # noqa: E402


def outbox_dir() -> Path:
    from joint_tune import lock_root

    return lock_root() / "port-events" / "outbox"


def new_observation_ref() -> str:
    return "obs-" + uuid4().hex


def intake_event(fact: dict, *, workcell_id: str, intake_point: str, observation_ref: str | None = None,
                 observed_at: datetime | None = None) -> PortEvent:
    """The conveyor-end (or wrist) fact as the one port event Harbor reads. Unreadable never becomes observed."""
    ref, at = observation_ref or new_observation_ref(), observed_at or datetime.now(timezone.utc)
    if "failed" in fact:
        kind = "container.handling_failed"
        fields = {"reason": fact["failed"], "object_ref": fact.get("object_ref")}
    else:
        kind = "container.received_at_intake"
        fields = {"object_ref": fact["object_ref"], "intake_point": intake_point, "identity": fact["identity"]}
    return PortEvent(event_id=event_id(workcell_id, ref, kind), kind=kind, observation_ref=ref, observed_at=at, **fields)


def queue(event: PortEvent, directory: Path | None = None) -> Path:
    directory = directory or outbox_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{event.event_id}.json"
    if not path.exists():  # the first write wins: a resend must carry the stored bytes
        tmp = path.with_suffix(".tmp")
        tmp.write_text(event.model_dump_json(), encoding="utf-8")
        tmp.replace(path)
    return path


def send(link, directory: Path | None = None) -> bool:
    """Resend every unsent event; a file leaves the outbox only once Fleet recorded it. False if any stays."""
    ok = True
    for path in sorted((directory or outbox_dir()).glob("*.json"), key=lambda p: p.stat().st_mtime):
        try:
            link.post_port_event(PortEvent.model_validate_json(path.read_text(encoding="utf-8")))
        except Exception as exc:  # unreachable, refused or a bad file: it stays for the next send
            print(f"port event {path.name} not sent: {type(exc).__name__}: {str(exc)[:120]}")
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
