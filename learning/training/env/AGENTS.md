# env

**Parent context:** `../AGENTS.md`
**Generated:** 2026-11-19 · **Updated:** 2026-11-19

## Purpose

Reproducible SmolVLA + ACT GPU learning environment for host-side training (model PC). See `README.md` for the order and the person-only steps. Never installed on a robot image.

## For AI Agents

- Provision only at a new venv path; never delete or recreate an existing env, and keep `requirements-policy-gpu.txt` an exact freeze of a working env.
- Proof that the env works is `../omx/il_proof.py` (synthetic, wiring only). Do not describe its receipt as policy quality or physical evidence.
- Tests: `python -m pytest learning/training/env/test -q` (no GPU needed).
