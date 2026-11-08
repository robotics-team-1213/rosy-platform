#!/usr/bin/env python3
"""Native Host Agent for lane perception and navigation approval; peer uid is the dedicated CORE account."""
from pathlib import Path
import grp
import pwd
import sys
import threading
import time

from host_agent import HostAgent, JsonlAudit
from host_agent_server import SubprocessCommands, serve_forever
import navigation_approval_host as approval


def watch_approval_expiry():
    """D-986: this service starts at every boot, so an interrupted measurement returns even after a reboot."""
    while True:
        try:
            approval.expire_if_due(Path("/"), approval.SystemOps())
        except Exception as exc:  # noqa: BLE001 - the watch outlives one failed check
            print(f"navigation approval expiry check failed: {exc}", file=sys.stderr, flush=True)
        time.sleep(60)


def main():
    uid = pwd.getpwnam("rosy-core").pw_uid
    gid = grp.getgrnam("rosy-core").gr_gid
    sink = JsonlAudit(Path("/var/log/rosy-host-agent/audit.jsonl"))

    def audit(record):
        sink(record)
        sink.records.clear()  # live polling must not retain audit history in memory

    agent = HostAgent(SubprocessCommands(), allowed_profiles=(), allowed_units=(),
                      allowed_commands=("lane_perception.status", "lane_perception.set",
                                        "navigation_approval.status", "navigation_approval.begin",
                                        "navigation_approval.cancel", "navigation_approval.seal",
                                        "navigation_approval.start_navigation"),
                      audit=audit)
    threading.Thread(target=watch_approval_expiry, name="approval-expiry", daemon=True).start()
    serve_forever(agent, expected_uid=uid, group_gid=gid)


if __name__ == "__main__":
    main()
