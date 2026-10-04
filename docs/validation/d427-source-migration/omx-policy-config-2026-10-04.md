# D-442 POLICY configuration guard — 2026-10-04

Candidate `test/d442-policy`, parent `f17f4f906`. Added `test_no_production_config_allows_learned_policy` scanning tracked OMX production Python owner declarations, parameter defaults and YAML allowed_owners. Covers both ordinary and annotated declarations. Name reservation in KNOWN_OWNERS remains valid; enabling POLICY without its later envelope admission remains forbidden in tracked operating configuration.

Local original state: **1 passed** (1.00 s); independent reviewer rerun: **1 passed**, APPROVE, no blocker. Mutation proof: temporary learned_policy injection in actual pilot_sim_server allowed_owners, command_owner ArmCommandConfig annotated default, and omx_cell_owner annotated ALLOWED_OWNERS each failed the guard. Original bytes restored after each probe; product files are clean. Raw evidence: `X:/DevTemp/rosy-d427/resume/policy-mutant-red.txt`, `policy-annotated-0-red.txt`, `policy-annotated-1-red.txt`, `policy-green-final.txt`.

Scope: static tracked declarations; runtime overlays, computed/imported configuration beyond the scanned declarations and envelope admission require subsequent runtime enforcement. SOURCE/local proof only; CI, ROS-SIM, ARM64, DEVICE and FIELD NOT_RUN for this candidate. No motion authority or operating configuration changed.
