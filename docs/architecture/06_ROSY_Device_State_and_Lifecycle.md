# 06. ROSY Device State & Lifecycle Specification

## 1. Standard States

```text
UNKNOWN
BOOTING
INITIALIZING
READY
BUSY
DEGRADED
FAULT
SAFE_STOP
OFFLINE
UPDATING
```

## 2. Typical Transition

```text
BOOTING
 -> INITIALIZING
 -> READY
 -> BUSY
 -> READY
```

Fault transition:

```text
BUSY
 -> FAULT
 -> SAFE_STOP
 -> READY
```

## 3. Control Plane Loss

When the Control Plane is lost:

- local safety remains active
- node may enter `DEGRADED`
- central tasks are rejected or queued
- approved local tasks may continue
- reconnect must occur automatically

## 4. Device-Specific Safe States

### Pinky

Preferred safe state:

- stop motion
- preserve localization
- maintain obstacle sensing

### OMX

Preferred safe state:

- stop active trajectory
- hold or safely release according to policy
- maintain joint limits
- reject unsafe commands
