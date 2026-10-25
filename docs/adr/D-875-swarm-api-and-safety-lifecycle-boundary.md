## D-875 Swarm owner-local API separates planning from safety lifecycle

**Status:** Accepted for implementation (2026-10-25, independently reviewed plan; source and device acceptance separate)

### Context

C1 preserves behavior but classifies the Fleet lifecycle, arming and relay as Safety. Whole-module classification exposes existing Decision imports and non-public type reexports. The two D-430 separation guards pass on main commit `6abf6a8a7e` and fail on C1 commit `9f9fc5846d`. Enlarging the frozen violation list or classifying the planner/transport implementation as Safety would conceal the boundary.

### Decision

Keep the actual lifecycle stop/resume, post-await epoch checks, arming cleanup and relay gates Safety. Move the existing lifecycle implementation to `fleet.swarm.session_lifecycle`; preserve `fleet.swarm.session.FormationSession` as a small Decision construction facade. It wires only the existing assignment planner and default assigner factory. The factory executes at its original constructor position; the planner executes once at its original pre-relay position. Stop and cleanup never invoke planning.

An owner-local `fleet.swarm.api` root contains existing data types, enums, exceptions and Protocol declarations only. It has no transport, planning math, admission, clock or I/O. Existing public module paths reexport the same objects. Geometry and the Greedy assignment implementation remain Decision; no strategy is relabeled. Fresh capability admission and leader emergency preflight live in the existing Safety arming owner and have genuine public anchors. Error contents, logging channels and public constructor defaults remain unchanged.

| Decision | Relationship |
|---|---|
| D-427 | Same Fleet distribution and installation; no new runtime or top-level part |
| D-429 section 4 | Owner-local API root follows the existing port-ownership pattern; imports only contracts/API |
| D-430 | Actual safety implementation remains tagged, Decision uses actual public entrypoints, no new frozen violation |

### Verification and limits

Verify API purity and reexport identity, unchanged planning order/count and planner-independent stop, all safety separation/anchor/API-root constraints, and formation/session/relay/transport/CLI/receipt regressions remotely against committed revisions. Review the implementation independently before its Safety-Review trailer. C2/C3 and later native/MotorHealth preps need source-owner-aware integration; older session.py must not overwrite the new lifecycle owner. No HTTP or envelope change, API version bump, landing, deployment or field acceptance is part of this ownership correction.
