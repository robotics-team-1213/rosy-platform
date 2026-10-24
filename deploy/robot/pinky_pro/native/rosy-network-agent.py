#!/usr/bin/env python3
"""Two dedicated local peers, one serialized network transaction."""
from pathlib import Path
import grp
import pwd
import sys
import threading

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from host_agent import JsonlAudit
from host_agent_server import serve_forever
from network_agent import NetworkCommands, make_agent
from network_runtime import commit_handoff, maintenance_claim, maintenance_ready, recovery_snapshot
from network_transaction import NetworkTransaction
from nm_network import NMNetworkBackend


def main():
    root = Path('/')
    peers = []
    for account, name in [('rosy-core', 'core.sock'), ('rosy-recovery', 'recovery.sock')]:
        user = pwd.getpwnam(account)
        if user.pw_uid == 0 or user.pw_shell != '/usr/sbin/nologin':
            raise RuntimeError('network_peer_account_invalid')
        peers.append((user.pw_uid, grp.getgrnam(account).gr_gid, name))
    transaction = NetworkTransaction(NMNetworkBackend(), root=root,
        claim=lambda: maintenance_claim(root), maintenance_check=lambda: maintenance_ready(root),
        on_commit=lambda record: commit_handoff(root, record))
    transaction.reconcile()
    commands = NetworkCommands(transaction, recovery_state=lambda: recovery_snapshot(root))
    sink = JsonlAudit(Path('/var/log/rosy-network-agent/audit.jsonl'))

    def audit(record):
        sink(record)
        sink.records.clear()

    def listen(uid, gid, name):
        serve_forever(make_agent(commands, audit=audit),
            path=Path('/run/rosy-network-agent') / name,
            expected_uid=uid, group_gid=gid)

    # Either listener failing must fail the unit, not leave half the authority alive.
    failures = []
    def guarded(*peer):
        try:
            listen(*peer)
        except BaseException:
            pass
        finally:
            failures.append(True)

    threads = [threading.Thread(target=guarded, args=peer, daemon=True) for peer in peers]
    for thread in threads:
        thread.start()
    while not failures:
        for thread in threads:
            thread.join(.5)
    raise SystemExit('network_listener_failed')


if __name__ == '__main__':
    main()
