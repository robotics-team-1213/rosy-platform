# 14. ROSY Verification & Acceptance Plan

## 1. ROSY v1 Acceptance Scope

ROSY v1 is accepted when:

- base runtime installs reproducibly
- profile-based installation works
- Pinky is recognized as a ROSY Device
- OMX is recognized as a ROSY Device
- Gram is recognized as an Edge/Compute Node
- RTX5080 is recognized as a GPU Node
- capabilities are registered
- tasks can be assigned by capability
- control-plane loss does not break local safety
- composite Pinky + OMX task executes

## 2. Required Tests

### Installation

- clean Ubuntu installation
- install each profile independently
- combine profiles
- remove profile
- upgrade profile

### Device

- discovery
- heartbeat
- reconnect
- fault state
- safe stop

### Compute

- GPU job execution
- OpenVINO fallback
- worker loss
- job retry

### Composite Robot

End-to-end:

```text
Navigate
 -> Align
 -> Pick
 -> Verify
 -> Navigate
 -> Place
 -> Verify
```

## 3. Exit Criteria

ROSY v1 should not be considered complete until profile installation, runtime lifecycle, and device/compute abstraction are stable.
