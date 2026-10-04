#!/usr/bin/env python3
"""Native lane-only Host Agent; peer uid is the installed dedicated CORE account."""
from pathlib import Path
import grp
import pwd

from host_agent import HostAgent, JsonlAudit
from host_agent_server import SubprocessCommands, serve_forever


def main():
    uid = pwd.getpwnam("rosy-core").pw_uid
    gid = grp.getgrnam("rosy-core").gr_gid
    sink = JsonlAudit(Path("/var/log/rosy-host-agent/audit.jsonl"))

    def audit(record):
        sink(record)
        sink.records.clear()  # live polling must not retain audit history in memory

    agent = HostAgent(SubprocessCommands(), allowed_profiles=(), allowed_units=(),
                      allowed_commands=("lane_perception.status", "lane_perception.set"),
                      audit=audit)
    serve_forever(agent, expected_uid=uid, group_gid=gid)


if __name__ == "__main__":
    main()
