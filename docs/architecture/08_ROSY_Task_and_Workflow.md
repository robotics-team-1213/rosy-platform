# 08. ROSY Task & Workflow Specification

## 1. Task

A Task is a requested unit of work.

Examples:

- Navigate
- Pick
- Place
- Transport
- Inspect
- Dock

## 2. Workflow

A Workflow combines multiple Tasks.

Example:

```text
TransportObject
  -> DetectObject
  -> NavigateToObject
  -> AlignBase
  -> Pick
  -> VerifyGrip
  -> NavigateToDestination
  -> Place
  -> VerifyPlace
```

## 3. Task State

```text
PENDING
ASSIGNED
RUNNING
SUCCEEDED
FAILED
CANCELLED
BLOCKED
```

## 4. Task Requirements

A Task may declare:

- capabilities
- deadline
- priority
- preferred node
- preferred asset
- safety class
- retry policy

## 5. Task Execution Boundary

Low-level safety and actuator loops remain local.

ROSY Task orchestration issues higher-level commands.
