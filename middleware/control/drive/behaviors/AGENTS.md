# Drive behaviors

**Parent context:** `../AGENTS.md`

D-649: ROS-free Base behavior engines installed by the existing `core_features` distribution. Source folder ownership differs from package identity. `line_follow` owns curvature/body proofs and its bounded recovery machine; docking owns its approach/charging lifecycle; navigation is the goal/readiness facade; localization consumes evidence and manages bounded pose/search requests; swarm consumes moving references; road behavior and traffic policy produce caps/admission results.

CORE gateway `core/drive` only composes these managers. CORE command arbitration and Safety Guard remain the final admission/output authority, and its bridge remains the sole operational `/cmd_vel` publisher. Do not import the legacy `control` distribution here, create another process/writer, or merge OMX joint ownership into Base behavior.

Source-only search paths, setup mappings, sdist, native/container build, development overlay, ownership manifest and architecture scans must all include this holder. Existing child package imports, clocks, locks, resources and configuration semantics stay unchanged. The moved charging/body-stop/clearance/rotate-to files retain per-file Safety tags and independent-review requirements.

Run services/gateway and architecture tests with the committed-HEAD remote runner. Installed-package and sdist proof do not establish robot/field acceptance.
