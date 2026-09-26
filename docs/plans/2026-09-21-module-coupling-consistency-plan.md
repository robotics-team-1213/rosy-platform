# Module Coupling Consistency Continuation Plan

- Date: 2026-09-21
- Status: Partially implemented — D-155 and D-157 Accepted; D-156 Proposed

## Context

Following D-126 (Full Module Separation) and the extraction of cross-domain
integration scripts (`simulate_*.py`) to the repository-level `tools/`
directory, the measured static dependencies between core and control no longer
require a source-level back-edge. Maintaining that result still needs explicit
build-time and runtime guardrails; the move and this proposal are not by
themselves proof of zero coupling.

## Decisions and remaining gate

### 1. [D-155] Zero-Coupling AST Validation (Build-time Guard) — Accepted

- **Problem**: Python's dynamic nature allows accidental cross-domain imports
  that pass in a monolithic development environment but break isolated runtime
  slices.
- **Decision**: Introduce an automated AST parser in
  `test/test_module_separation.py`. It inspects `import` and
  `from ... import ...` statements and reject dependencies outside the explicit
  domain allowlist. Test-only boundaries remain separately declared.

### 2. [D-156] ROS 2 Namespace Strict Segregation (Runtime Guard) — Proposed

- **Problem**: Static imports can be clean while ROS 2 topics remain global. An
  application node could accidentally publish the operational final
  `cmd_vel`, violating D-2.
- **Decision**: Define and test a topic-ownership allowlist. `core/control`
  publishes evidence/sensor topics only; CORE owns operational state, intent
  and final `cmd_vel`. A launch/graph check must verify actual publishers before
  this proposal can become Accepted.

### 3. [D-157] Shared Headless UI Package (Monorepo Web Decoupling) — Accepted

- **Problem**: D-999 called for a framework-free adapter, but placing it in
  `core_api_web` would couple other surfaces to the robot dashboard package.
- **Decision**: Install `core_ui_logic.js` and `tokens.css` through the neutral
  `web_common` ament package. CORE and Fleet resolve the installed share path,
  retain source-tree fallbacks for host tests, and share no visual components.
