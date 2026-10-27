---
title: A land run started with shell & failed silently for six hours; a flipped Tailscale profile killed two FULL rounds
date: 2026-10-15
last_updated: 2026-10-28
category: workflow-issues
module: tools/land.py, tools/land_checks.py, tools/remote/remote_pytest.py, tools/remote/work_queue.py, agent session practice
problem_type: workflow_issue
component: development_workflow
severity: high
root_cause: missing_workflow_step
resolution_type: workflow_improvement
symptoms:
  - "land.py stopped at about 05:20 on a size verdict; nobody noticed until 10:59 while peers held main"
  - "two FULL land rounds ended with exit 255 and 'Connection reset by peer' while no test had failed"
  - "tailscale switch --list showed the current profile on bc4d, which has no test PCs"
  - "a turn held its queue while every remote invocation was unfinished; a completion callback never checked the elapsed budget"
applies_when:
  - "an agent launches tools/land.py or tools/remote/remote_pytest.py for a long run"
  - "remote runs fail with exit 255, connection reset, or 'shipping failed' and no test failure"
  - "a local landing process is idle with no children while detached remote jobs may still be running"
tags: [land-py, remote-pytest, tailscale, background-task, notification, coordination, turn-deadline]
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
- Historical 2026-10-15 checkpoint: a tooling fix on `fix/land-fast-fail-and-log-order` was pending; remote_pytest checks
  the profile against a lab-config key and fails fast with the switch command.

## An idle local process is not proof that remote work stopped (2026-10-28)

The remote jobs are detached. A read-only Python stack showed the landing's main thread waiting for
worker futures and its workers sleeping in `remote_job.run` between polls. Low local CPU and no local
children did not establish a deadlock. Do not terminate a peer's run from those two observations alone:
inspect the stack, committed candidate, remote log progress and queue state first. Never dump locals or
copy host addresses or credentials into a public record.

There was also a real time-limit defect: `on_done` checked the turn's 600-second budget only after an
invocation completed. If every invocation remained unfinished, nothing set the existing cancellation
event. A failed-first batch could also start another budget for the remaining work.

At the focused-verification checkpoint, before local landing, the pending fix in `land_checks.run_tests`
creates one deadline for the actual turn and arms a timer
independent of invocation completion. Single- and multiple-host workers share its stop event.
Isolated retries and main-comparison diagnostics receive the same event; expiry propagates as cancellation
instead of launching another diagnostic or reporting a broken callback. Visible running jobs use the existing
cancellation path on their next poll, queued jobs do not start, and cancelled results never become passing
cache entries. Preparation rounds remain uncapped. Existing
SSH/contact-loss timeouts still apply; a disconnected job is not killed without observing it.

Recovery: preserve source and evidence, update and restart the landing through `tools/land.py` after
the fix is integrated. Already running Python processes do not reload changed modules automatically.
Do not bypass verification or cancel unrelated host jobs to free a queue position.

Evidence: eight deterministic remote RED cases covered one/two hosts, a successful failed-first batch,
and expiry in isolated/main diagnostics. The fixed source passed those cases and the broader existing
landing/remote suites (324 passed).
See [the revision-bound validation record](../../validation/land-turn-deadline-2026-10-28/result.md).
This focused result is not a FULL-tier, device or field acceptance claim.

## Applicability
Any long-running remote job started by an agent on the shared laptop.
