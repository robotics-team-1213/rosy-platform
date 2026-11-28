
# harness

**Parent context:** `../AGENTS.md`

The D-61 module harness: `harness.yaml` registers modules; `rosy_harness.py` generates `index.md` and `STATUS.md` and lints.
Also the D-436 `affected` selector (`affected_*.py`) and the D-766 size gate. Design: `docs/plans/2026-09-15-module-harness-design.md`. ROS-free; stdlib plus PyYAML.

## For AI Agents

### Working In This Directory

- Harness (D-61): each registered module keeps `progress.md` (gates) and `logs.md`; procedure in the repository root `AGENTS.md`.
- `logs.md` is append-only: a committed entry is never edited (checked against git history). After editing a `progress.md` or `logs.md`: `generate`, `lint`, commit the regenerated `index.md`/`STATUS.md`.
- `progress.md/logs.md/index.md` may exist only at paths registered in `harness.yaml`; register every new ROS package there rather than adding `affected` special cases.
- D-430 §5: a commit that touches a safety-tagged path (`concern: safety` roots, `safety_modules`) or removes a safety root, module or `safety_anchors` entry needs a `Safety-Review:` trailer. A `git mv` touches both paths (D-427 wave 3/4).
- `safety_review.py` (Safety-Review check) runs in CI, `pr_land.py` and pre-push; exemptions only in `safety_review_exempt.json`.
- D-430 §4: a robot config with `safety.fleet_loss_policy` other than STOP/HOLD carries `safety.fleet_loss_policy_approval {robot, approver, evidence}`. `test_safety_separation.py` checks tracked YAML only, not runtime PUT or device overlays.
- `platform_parts.yaml` `concern`/`safety_modules`/`safety_anchors` follow D-429/D-430 §1; edit with care, a Safety-Review trailer applies (D-430).
- `safety_review_paths` in `platform_parts.yaml` need the trailer only; no FULL escalation applies.
- ADR numbers: claim with `adr_reserve.py next "<topic>"`, API versions with `api_reserve.py next`; never pick by hand. A deliberate hole goes in `adr_gaps.txt`.
- D-766: each commit must pass `size_range.py BASE HEAD` alone. `split_check.py` proves a pure move; compression is not a split. A non-merge commit touching `tools/land*.py` needs `Metrics: before=` (D-889 36).
- D-436: iterate with `rosy_harness.py affected --run`; the full suite runs only on GitHub Actions. Editing `affected_tests.py`, `harness.yaml` or any file here escalates the selector itself to FULL. Add a whole suite to `CI_FULL_MATRIX` in `affected_ci.py`.
- `ci_triage.py` reruns a red run only when every causing job is infra, once per (run, job). Never widen it to real failures.
- `structure_jira.py` publishes Jira tasks; do not run its publishing CLI without a user request.
- Run from the repository root. Korean log field names (`변경`, `증거`, `gate 변화`) have English aliases (Change, Evidence, Gate).
- Use `python`, not `python3` (Store stub without PyYAML on Windows). `run_functional.py` builds `PYTHONPATH` from the pre-regroup `src/rosy_core`; check before relying on it.

### Testing Requirements

```bash
python tools/harness/rosy_harness.py lint
python -m pytest test/test_harness_contracts.py test/test_affected_tests.py -q
```
