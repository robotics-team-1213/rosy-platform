<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-02 -->

# system

## Purpose

Host and ROS-graph observability plus the unprivileged Host Agent client. Never invent telemetry when the agent or `/proc` is missing.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker |
| `runtime.py` | `HostRuntimeProbe` — CPU, mem, disk, temp, hostname from `host_root` |
| `ros_graph.py` | Bounded node/topic/edge snapshot; `ROS_DOMAIN_ID` 0–101 |
| `host_agent_client.py` | Unix-socket client; codes `HOST_AGENT_UNAVAILABLE` / `HOST_AGENT_TIMEOUT` / `HOST_AGENT_UNREADABLE_RESPONSE` |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- Socket `/run/rosy/host-agent.sock` is absent on dev machines — that is normal.
- Caps: MAX_NODES 64, MAX_TOPICS 96, MAX_EDGES 256.
- Dashboard cards must display the explicit failure mode. Never return empty-success when the agent is down.

### Testing Requirements

`test_host_runtime.py`, `test_ros_graph_monitor.py`, `test_host_cards.py`

### Common Patterns

Read-only filesystem views; JSON request lines to Host Agent.

## Dependencies

### Internal

- Contract `docs/reference/rosy-host-agent-contract.md`
- Server `deploy/release/host_agent.py`

### External

- POSIX sockets (client no-ops if missing)

<!-- MANUAL: -->
