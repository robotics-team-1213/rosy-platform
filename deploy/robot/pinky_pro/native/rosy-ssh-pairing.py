#!/usr/bin/env python3
"""Opt-in SSH-only Host Agent: no release, network, or reboot execution."""

from pathlib import Path
import os
import pwd

from host_agent import HostAgent, JsonlAudit
from host_agent_server import SubprocessCommands, serve_forever


def main():
    if os.geteuid() != 0:
        raise SystemExit('SSH pairing agent requires root')
    account = pwd.getpwnam('rosy-core')
    journal = JsonlAudit(Path('/var/log/rosy-ssh-pairing/audit.jsonl'))

    def audit(record):
        journal(record)
        journal.records.clear()

    agent = HostAgent(SubprocessCommands(), allowed_profiles=[], allowed_units=[],
                      allowed_commands=['ssh.register_key'],
                      audit=audit)
    serve_forever(agent, path=Path('/run/rosy-host/ssh-pairing.sock'),
                  expected_uid=account.pw_uid, group_gid=account.pw_gid)


if __name__ == '__main__':
    main()
