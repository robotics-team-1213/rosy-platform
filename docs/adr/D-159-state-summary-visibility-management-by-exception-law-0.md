## D-159 State Summary Visibility: Management by Exception (Law 0)

**Date:** 2026-09-21
**Status:** Accepted (2026-09-25 — D-219 supplied the missing fleet-side
executable contract and promoted this decision)
**Context:** Operators struggled to quickly determine the robot's operational status without parsing raw diagnostic tiles (e.g., "지형이 로봇에 보낼 수 있는가?", "하드웨어가 통신할 수 있는가?").
**Decision:** Top-level visual surfaces should render one operational summary
derived from authoritative state, including degraded capabilities and HITL.
This remains Proposed until the summary vocabulary and both surface behaviors
have executable contracts.
