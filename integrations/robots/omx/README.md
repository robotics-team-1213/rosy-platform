# ROSY OMX Robot Integration

This package holds the OMX LeRobot `rosy_omx` Robot, the CORE arm client and the
`rosy-omx-preflight` entry point. It imports no middleware.

The `pallet.transfer` Skill binding (`transfer_provider`, `arm_transfer`, `cell_workflow`) and
the mixed-planner IK reach (`mixed_reach`) moved to the OMX cell owner
`middleware/devices/omx/agent/src/rosy_agent/` on 2026-11-03. They compose `omx_adapter` and the
manipulation Skill, which an integration may not import (D-427 §2).

## CORE and LeRobot

The optional HTTP-only `rosy_omx` Robot adapter connects LeRobot recording and
inference to CORE's installed OMX policy session. See [setup and limits](docs/CORE_LEROBOT.md).
