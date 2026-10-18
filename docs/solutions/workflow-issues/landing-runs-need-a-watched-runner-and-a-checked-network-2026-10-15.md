---
title: A land run started with shell & failed silently for six hours; a flipped Tailscale profile killed two FULL rounds
date: 2026-10-15
category: workflow-issues
module: tools/land.py, tools/remote/remote_pytest.py, agent session practice
problem_type: workflow_issue
component: development_workflow
severity: high
root_cause: missing_workflow_step
resolution_type: workflow_improvement
symptoms:
  - "land.py stopped at about 05:20 on a size verdict; nobody noticed until 10:59 while peers held main"
  - "two FULL land rounds ended with exit 255 and 'Connection reset by peer' while no test had failed"
  - "tailscale switch --list showed the current profile on bc4d, which has no test PCs"
applies_when:
  - "an agent launches tools/land.py or tools/remote/remote_pytest.py for a long run"
  - "remote runs fail with exit 255, connection reset, or 'shipping failed' and no test failure"
tags: [land-py, remote-pytest, tailscale, background-task, notification, coordination]
---

# A land run started with shell & failed silently for six hours; a flipped Tailscale profile killed two FULL rounds

## Context
- **Silent failure:** an agent re-launched a land script inside a foreground shell with a trailing
  `&`. The harness tracks only its own background tasks, so no completion notice arrived. The land
  had stopped on a size verdict; peers held main for it from about 05:20 to 10:59 on 2026-10-15.
- **Network:** the laptop's Tailscale switched by itself to profile bc4d, which has no test PCs.
  Every ship to the test PCs failed with exit 255. It happened twice that day; no Rosy session
  switched it.
- **Orphans:** shipments cut by resets left `cat` processes holding the `~/rosy-test` lock on the
  test PCs for over an hour, so every session's ships timed out. Main fixed this with the commit
  "fix(remote): read the bundle before taking repo.lock, bounded" in `tools/remote/remote_pytest.py`.

## Guidance
- Launch long land or test runs only as the harness's notifying background task, never with `&` or
  `nohup` inside another command. If one was started that way, poll it until it ends.
- Before a FULL land, check that `tailscale switch --list` shows `*` on the lab profile (665e on
  2026-10-15). Do not switch profiles for a peer; report it instead.
- After a reset, check the test PC for your own leftover ship processes (your sha is in the command
  line) and kill only those.
- Tooling fix in progress on branch `fix/land-fast-fail-and-log-order` (pending): remote_pytest checks
  the profile against a lab-config key and fails fast with the switch command.

## Applicability
Any long-running remote job started by an agent on the shared laptop.
