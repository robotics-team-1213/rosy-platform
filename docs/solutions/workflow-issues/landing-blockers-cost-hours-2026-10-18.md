---
title: Four landing blockers cost hours on one day; size-locked units, a red main, a crowded test queue and oversized branches
date: 2026-10-18
last_updated: 2026-10-27
category: workflow-issues
module: tools/land.py, tools/land_checks.py, tools/harness/size_range.py, tools/harness/affected_tests.py, tools/harness/affected_narrow.py, shared/web/surfaces.yaml
problem_type: workflow_issue
component: development_workflow
severity: high
root_cause: missing_tooling
resolution_type: tooling_addition
symptoms:
  - "size_range.py refused a branch for a commit inherited from an earlier session; later commits on the branch could not fix it"
  - "fleet 16,499 / site_ui/console 11,317 / rosy_auto_update.py 1,591 / trip_ports.py 600 accepted no net growth; a partial split lowered the ceiling by the lines moved"
  - "NEW shared/web/test/test_shared_controls.py::test_measure_comes_from_the_scale on branches that never touched it (main was red after D-792)"
  - "two sessions landed the same main fix in parallel (f376f8cbba, 44a24983da)"
  - "land runs took 30-90+ minutes with ~10 sessions on the test PCs; one run lost to 'no test host reachable' after 600 s"
  - "fix/fleet-network-load-v2 needed 4 land.py rounds (~2.5 h): each passed, but main moved and forced a full-tier rerun; one merge put core_features at 10,001 / 10,000"
applies_when:
  - "a land.py run stops on a D-766 size verdict, or a NEW failure in a file the branch did not change"
  - "planning a change inside fleet, site_ui/console, rosy_auto_update.py, trip_runner.py or trip_ports.py"
  - "a branch bundles several tasks (WebRTC T2-T5 + console + topology) into one landing"
  - "an existing package still claims a size unit but its registration disappeared during history reconstruction"
tags: [land-py, d-766, size-ratchet, restack, main-red, affected-tier, surfaces-yaml, test-queue, branch-size]
---

# Four landing blockers cost hours on one day; size-locked units, a red main, a crowded test queue and oversized branches

## Context

On 2026-10-18 the network-load and WebRTC work (T2-T5, console, topology) was ready in code but
took hours to land. Four separate things blocked it.

### 1. D-766 size check

- **Symptom (a):** `tools/land.py` runs `tools/harness/size_range.py main HEAD` before any remote
  test. It refused the branch for a commit inherited from an earlier session's branch that had
  grown a unit over its limit. Later commits that shrank the unit did not help.
- **Root cause (a):** `size_range.py` checks every commit on its own so bisect never meets a size
  red (D-766 2). "Grow, then split in a later commit" is red on the growing commit by design.
- **Symptom (b):** units already over their limit took no net growth at all: the `fleet` package
  (16,499 lines vs 10,000), `site_ui/console` (11,317), `rosy_auto_update.py` (1,591 vs 600),
  `test/test_rosy_auto_update.py` (2,632 vs 1,500), `trip_runner.py` (899), and `trip_ports.py`
  (exactly 600). A fix had to be bent into new modules, and a planned jitter change was dropped.
- **Root cause (b):** the ratchet row must equal the measured count (D-766 4). A partial,
  behaviour-preserving split lowers the ceiling by the lines it moves, so it frees no room. Room
  appears only when the unit drops below its absolute limit and its row is deleted.

### 2. Main went red and blocked everyone

- **Symptom:** the D-792 camera page in `learning/curation/perception/review_app_web` landed with
  `test_shared_controls.py::test_measure_comes_from_the_scale`,
  `::test_product_fields_carry_the_shared_field_class` and
  `test_ui_token_contracts.py::test_no_raw_colour_outside_the_token_file[pinky-review]` failing.
  Every later branch that touched `shared/web` was refused with those as NEW. Two sessions then
  fixed it at the same time (f376f8cbba, 44a24983da).
- **Root cause:** those suites scan every tree listed in `shared/web/surfaces.yaml` through
  `surface_registry`. They never name `review_app_web`, so the D-436 affected selector, which
  matches by module, import and path name, did not pick them for that landing. `land.py` also had
  no way to say "this NEW failure fails on main too", so each blocked session debugged it as its own.

### 3. Test PC queue

- **Symptom:** each land run took 30-90+ minutes with about ten sessions sharing the hosts, and
  hosts below the memory floor were used anyway. One run was lost when the API/network dropped:
  every host was unreachable for 600 s (the D-584 wait) and the agent died mid-land.
- **Root cause:** cost per landing is set by the selection size (a FULL round runs every suite) and
  by the number of sessions landing at once. Nothing in the workflow made a session weigh the land
  cost before bundling.

### 4. Big bundles

- **Symptom:** WebRTC T2-T5, console and topology rode on one branch. Each attempt paid a full
  round, and one failure anywhere sent the whole bundle back. Splitting into smaller branches is
  what finally landed it.

### 5. Main moved during every round (observed later the same day)

- **Symptom:** `fix/fleet-network-load-v2` needed four `land.py` rounds. Every round passed, but
  each time another session had landed on `main` meanwhile, so `land.py` merged the new `main` and
  reran the full-tier tests: about 30-60 minutes per round, about 2.5 hours in total.
- **Symptom (size):** after one of those merges, `main`'s growth plus the branch put the
  `core_features` unit at 10,001 lines (limit 10,000). The size refusal came from the merge, not
  from the branch alone. `core_features` now sits exactly at its limit, so the next addition
  anywhere in it needs a split first; it is a [D-798](../../adr/D-798-size-headroom-splits-and-restack.md)
  split candidate next to `fleet` and `site_ui/console`.
- **Symptom (infra):** two runs lost host contact for more than 600 s (exit 255).
  `test/test_platform_g1_timing.py::test_coordinated_pairs_pass_both_barriers_within_the_proposed_bounds`
  was flagged LOAD-FLAKY twice. Correction 2026-10-26: the cause is not suite load. It failed 3/3
  first tries on the AI PC after its disk was freed (0/2 on the model PC); the likely cause is AI PC
  disk I/O contention (io pressure full avg10 up to 57%, a continuous foreign WAL writer), not proven.
  See [read-only-test-dirs-fill-lab-disks-2026-10-26.md](read-only-test-dirs-fill-lab-disks-2026-10-26.md).
- **Root cause:** there is no landing order or queue. A wide branch selects the full tier, so every
  move of `main` during a round costs a full rerun.

## What worked

- **Re-stack, do not patch on top.** Make a new worktree from `main`, cherry-pick the needed commits,
  and fold each grow-then-split pair into one commit (`git cherry-pick -n`, then add the split).
  Steps are in [D-798](../../adr/D-798-size-headroom-splits-and-restack.md) Decision 5.
- **Put new code in modules that are under their limit,** each with one responsibility. Do not
  squeeze a locked file.
- **Fix main first, in a small branch** that changes only the broken tests' cause, then rerun the
  blocked landings. Check whether a peer is already on it before starting (see the duplicate commits).
- **Split the bundle** into one landable concern per branch.

## Prevention (landed with this note)

- **Affected selection reads the registry.** `tools/harness/affected_narrow.py` `registry_readers`:
  a change under any tree listed in `shared/web/surfaces.yaml` now selects every test that imports
  `surface_registry` (14 suites, including the two above). Test:
  `test/test_affected_tests.py::test_a_surface_tree_change_selects_the_registry_contract_suites`.
- **MAIN-RED.** When a land round stops on NEW failures, `tools/land_checks.py` reruns those ids
  once on `main`. Ids red there too print as `MAIN-RED`, and the stop message says main is broken
  and to fix it in a small branch first. The landing is still refused. Test:
  `test/test_land.py::test_new_failure_that_also_fails_on_main_is_named_main_red`.
- **Size headroom plan.** [D-798](../../adr/D-798-size-headroom-splits-and-restack.md) (Proposed)
  maps the splits that take `fleet` to about 7,960 lines and `site_ui/console` to about 6,460, and
  splits `rosy_auto_update.py`, its test file and the trip files. It also sets the rule "at 95% of
  a limit, land the split branch before the feature". D-766 itself is unchanged.
- **Branch size rule.** `AGENTS.md` 「같이 하는 깃」 1 and `docs/reference/shared-checkout.md`:
  one landable concern and one module family per branch. Over about 15 changed files, or a FULL
  plan from `land.py --dry-run`, split first. FULL-trigger and `shared/web` parts land first, on
  their own branch.

## Prevention for 5 (user decision 2026-10-18: "improve further if possible")

- **Landing queue (implemented, [D-803](../../adr/D-803-landing-queue-before-delta-rerun.md)).** `tools/land.py`
  takes a FIFO ticket in `<git-common-dir>/rosy-land-queue/` (`tools/land_queue.py`) before its test rounds,
  prints its position and who is ahead, and waits (`--queue-timeout`, default 180 min) until it is first; then it
  merges `main` once and tests. The ticket is released on every exit, Ctrl-C included; a dead holder's ticket (PID
  gone on this host, or not refreshed for 3 h) is reclaimed. `--no-queue` is the incident escape hatch. Tests:
  `test/test_land_queue.py`, `test/test_land.py::test_a_live_ticket_ahead_holds_the_landing_until_the_queue_timeout`.
- **Delta rerun across runs (implemented, D-803 6).** Within one run, D-762 stage 0 already reran only main's
  delta selection after a green FULL tier. A fresh run (after a lost host, Ctrl-C or the round cap) started with
  FULL again: `refactor/land-split` itself hit "main kept moving: gave up after 5 rounds" on 2026-10-18 and its
  rerun paid a second FULL tier. `tools/land_full.py` now keeps the FULL pass in `<git-common-dir>/rosy-land-full/`
  and a later run reuses it while the branch added nothing but merges of main. Not done: uniting main's delta with
  the branch's own mapped suites. The FULL tier already passed those with the branch's code, and the delta selection
  takes direct reverse dependents of what main changed, so the union would rerun suites that passed on the same
  branch code. A narrow (non-FULL) branch still reruns its own affected tier each round, as before.
  Tests: `test/test_land.py::test_a_later_run_reruns_only_main_delta_over_an_earlier_full_pass` and the two after it.
- **Landed ADR gaps drop themselves (2026-10-19).** `tools/harness/adr_gaps.txt` merges with `merge=union`, so a
  merge of `main` kept the branch's copy of a gap line `main` had already removed when that ADR landed, and lint
  stopped the landing with "declared gap now exists" (three branches that day, `feat/land-queue` among them).
  After each merge of `main`, `tools/land.py` now drops every gap line whose ADR file or Log row exists
  (`land_merge.landed_gaps`) and prints it in the land log. Since 2026-10-26 this happens inside `land.merge`, in
  the merge commit itself (see 6). Test:
  `test/test_land.py::test_a_gap_line_whose_adr_landed_on_main_is_dropped_after_the_merge`.

### 6. The queue held for FULL turns that had already passed (2026-10-25)

- **Symptom:** 12 tickets queued, the oldest 173 min. Turns with the affected tier took 4-13 min, but a turn that
  ran FULL held everyone behind it for about an hour (`feat/rasptank-no-motion`, 22:17-23:20), although its FULL
  tier had passed while it waited. One branch restarted 16 times before landing. Numbers from six sessions:
  workspace record `local-main-landing-speed.md` (outside the repo).
- **Root causes found in the code:**
  - main's delta during the wait held `tools/harness/affected_tests.py`, so the delta selection escalated
    ("harness configuration or the selector itself") and the turn ran FULL again. That harness edit had passed its
    own FULL tier when it landed.
  - The turn loop committed the gap clean-up as a separate non-merge commit. `land_full.restore` treats any
    non-merge commit after the FULL candidate as new code, so the FULL pass was voided. A merge commit that
    `generate` changed (`docs/index.md`) was voided the same way.
  - `pretest()` merged `main` without the gap clean-up, so lint stopped it with "declared gap now exists" when a
    peer had declared a gap for the ADR the branch adds (D-877).
  - A `--no-queue` landing at 22:52 moved `main` in the middle of another turn and gave that turn a second round.
- **Fixed (2026-10-26):** `land.merge` drops landed gap lines in the merge commit (pretest and turn alike);
  `land_full.restore` keeps a FULL pass when the merge commit differs from git's merge only in the records
  `land_merge.resolver` auto-resolves; a delta that escalated only for landed harness files runs its guards and
  mapped suites (`select(..., landed=True)`); `--no-queue` is refused while a live ticket holds its turn. Tests:
  `test/test_land.py::test_a_gap_main_declared_for_an_adr_this_branch_adds_is_dropped_by_the_pretest_merge`,
  `::test_a_merge_that_only_dropped_gap_lines_keeps_the_full_pass`,
  `::test_main_delta_escalated_only_by_landed_harness_files_runs_its_mapped_suites`,
  `::test_no_queue_is_refused_while_a_lander_holds_its_turn`.
- **Retries rerun only what failed (2026-10-26):** `run_tests` stopped on the first NEW failure, so the passes
  after it were never kept, and it kept nothing when any invocation lost its host. One fixed failure then reran
  every invocation. Now every invocation is judged, each clean pass of its own usable evidence is kept
  (`land_cache`), and the stop lists every failure at the end. LOAD-FLAKY passes are still not kept. Tests:
  `test/test_land.py::test_a_new_failure_still_keeps_the_invocations_that_passed_beside_it`,
  `::test_cache_never_keeps_a_failure_or_a_partial_run`.
- **What failed last time runs first (2026-10-26):** an invocation with a NEW failure is marked in
  `<git-common-dir>/rosy-land-failed.json` and cleared once it passes. The next run sends the marked ones to the
  test PCs alone first; if they fail again the landing stops before the rest is spent. Test:
  `test/test_land.py::test_what_failed_last_run_runs_alone_first_and_a_repeat_stops_before_the_rest`.
- **A branch's reordered copy of main's log entries (2026-10-26):** a hand-fitted merge of main left main's
  `docs/logs.md` entries in another order on the branch; the turn stopped "a side changed existing lines".
  `land_logs.append_blocks` now keeps main's order when the branch only reordered (nothing edited or dropped)
  and inserts the branch's new entries by date; main reordering, or an edit, still stops. Test:
  `test/test_land.py::test_logs_md_this_branch_reordering_mains_entries_keeps_mains_order`.
- **Old branches landed with old landing code (2026-10-26):** `land.py` ran from the landing branch's own copy,
  so a branch made before a landing fix still landed with the old rules (robot-71's turn stopped on a log merge
  that main's `land_logs` already accepts). `land_checks.landed_copy` now re-runs main's `tools/land.py` with the
  same arguments, in the branch's worktree, whenever the branch's `tools/land*.py` differ from main's
  (`ROSY_LAND_OWN_COPY` stops a second re-run). Test:
  `test/test_land.py::test_a_branch_with_older_landing_code_lands_with_mains_copy`.
- **A FULL tier at the front held everyone (2026-10-26):** the pretest ran only when someone was ahead, so a
  FULL lander first in line ran its tier inside the lock (`feat/monitoring-registration`, 40+ min, 10 batches).
  Tickets now carry a status: `preparing` (the FULL tier before the turn: keeps its place, blocks no one),
  `waiting`, `turn`. A turn starts when no ticket is in its turn and no earlier ticket is waiting
  (`land_queue.blockers`). The pretest runs for every auto landing without a FULL record. Tests:
  `test/test_land_queue.py::test_a_preparing_ticket_keeps_its_place_without_blocking_and_a_turn_blocks_everyone`,
  `test/test_land.py::test_harness_selector`.
- **Every tier prepares outside the lock (2026-10-26, D-889 A'):** `land_prepare.prepare` runs each auto
  landing's own selection before its turn (ticket `pending` until fewer than three prepare, then
  `preparing`; neither blocks anyone) and records the tier that passed. The turn selects main's delta since
  that main on the candidate, so overlap is judged by the selector, not by a separate area model; a delta
  that escalates to FULL is prepared outside the lock again and the ticket waits once more. Without the
  D-436 selector only a FULL tier prepares. Tests:
  `test/test_land.py::test_an_affected_landing_prepares_outside_the_lock_and_its_turn_runs_mains_delta_only`,
  `test/test_land_queue.py::test_at_most_three_landings_prepare_at_once_and_a_pending_one_blocks_no_one`.
- **First confirmed failure stops the round; the turn has a time cap (2026-10-26):** a round ran 19 more min
  after its first real failure. `run_tests` now judges each invocation as it finishes (`remote_pytest.run`
  `on_done`, `land_checks.verdict`: known_failures, then the rerun alone) and cancels the rest on a confirmed
  NEW failure; cancelled invocations are neither kept nor failures of their own. In a turn, tests past
  `TURN_CAP_S` (600 s) cancel the rest as `Overtime`, and `land_prepare.again` runs them outside the lock
  before the ticket waits again. Tests:
  `test/test_land.py::test_a_confirmed_new_failure_cancels_the_rest_and_the_cancelled_are_neither_kept_nor_failures`,
  `::test_the_turns_time_cap_cancels_the_rest_as_overtime_and_a_prepare_round_has_no_cap`.
- **Queue time lost to a conflict found only at the turn (2026-10-26):** two landings waited 121 and 149 min, then
  stopped on `tools/AGENTS.md`, where each side had edited a different table row. `land_merge.table_rows` now
  merges AGENTS.md tables row by row (first cell as key; the same row changed on both sides, or dropped on one
  and edited on the other, still needs a person), and `land_prepare.watch` previews the merge with
  `git merge-tree` each time main moves during the wait, stopping at once on a conflict land.py cannot resolve.
  `--queue-timeout` defaults to 0 (no limit): dead tickets are reclaimed by PID and refresh age, and a live
  landing gained nothing from being dropped (robot-91 lost its prepared tier that way). Tests:
  `test/test_land.py::test_agents_md_rows_edited_on_different_sides_merge_by_first_cell`,
  `::test_agents_md_same_row_on_both_sides_needs_a_human`,
  `test/test_land_queue.py::test_a_check_that_names_a_reason_stops_the_wait_at_once_and_zero_means_no_limit`.
- **Apply when:** a turn runs FULL after a green pretest, or a pretest stops on lint after merging `main`. Read the
  selector's escalation for main's delta first (`rosy_harness.py affected --base <tested main> --head <main> --json`).
- **Still open:** the queue is first-come, and tests run while the lock is held; the next stage (tests outside the
  lock, a ready-order queue) is planned separately.

The candidates as first written:


1. **Landing queue or lock.** Sessions land in order; the next one merges or rebases onto `main`
   once, after the one ahead of it has landed, instead of chasing a moving `main`.
2. **Rerun only the delta when `main` moves.** When `main` moves during a round, rerun the tests
   affected by `main`'s delta united with the branch's affected set, not the whole tier.
3. **Keep branches narrow.** The existing rule in `AGENTS.md` 「같이 하는 깃」 1 (one landable concern
   per branch, about 15 changed files at most) keeps branches in narrow tiers, so a rerun is cheap.

### 7. Accepted size-unit metadata was omitted during history reconstruction (2026-10-27)

The OMX profile checkpoint passed its 49 behavior cases but failed the package-size guard at
10,353 lines. Its earlier combined-prerequisite commit was already over the limit at 10,039.
The existing `real` package and owner log said it was independently measured, yet
`test/architecture/size_units.txt` lacked its row.

History established a missing registration, not a newly eligible split. [PR #184](https://github.com/robotics-team-1213/rosy-platform/pull/184)
contained `devices/omx/adapter/omx_adapter/real`; the local reconstruction retained its code and
purpose statement but omitted the registry change. The first local history-join merge also
retained the omission although its second parent contained the row.
Current promotion criteria did not independently fire, so inventing a new lifecycle criterion
would have hidden the cause. The repair restores the accepted row and its parent ownership entry.

Before landing, the pending local restoration passed the complete affected selection:
1,893 tests passed, 22 remained skipped, and the known-failure comparison reported no NEW failures.
The measured parent changed from 9,681 to 8,348 lines; the existing real package remained 1,333.
Its runtime source, limits, floor, ratchet and counting algorithm were unchanged. This verifies
the pending source restoration, not native deployment or physical acceptance.

When a package declaration and registry disagree, inspect the accepted source commit and merge
parents before inventing another split or exception. Carry ownership and size metadata with the
implementation. If consumer commits already exceed the limit, preserve them as evidence and
rebuild from a base containing the prerequisite: a later registry merge cannot repair their
per-commit verdicts. The old profile history still required that reconstruction at this checkpoint.

## Not fixed here

- Test PC placement still uses hosts below the memory floor when nothing else is free (D-568), and
  an agent that dies mid-land leaves no resumable state. Run long lands as a watched background task
  ([landing-runs-need-a-watched-runner-and-a-checked-network-2026-10-15.md](landing-runs-need-a-watched-runner-and-a-checked-network-2026-10-15.md)).
- `tools/harness/affected_tests.py` (600) and `tools/land.py` (594) were at or above 95% of the
  600-line limit. `refactor/land-split` moved the CI full-run matrix to `tools/harness/affected_ci.py`
  (`affected_tests.py` 495) and the conflict auto-resolution to `tools/land_merge.py` (`land.py` 472),
  pure moves with the old names re-exported.

## Related

- [D-766](../../adr/D-766-size-limits-split-on-exceed.md) size limits, [D-436](../../adr/D-436-change-scoped-test-tiers.md)
  affected tiers, [D-584](../../adr/D-584-tests-never-run-on-operator-laptop.md) remote-only tests,
  [D-790](../../adr/D-790-worktree-rules-landed-orphan-stale-flaky.md) LOAD-FLAKY rerun.
- [adr-numbers-collide-between-concurrent-sessions-2026-09-25.md](adr-numbers-collide-between-concurrent-sessions-2026-09-25.md)
- [prepush-gate-red-from-other-sessions-unpushed-commits-2026-10-10.md](prepush-gate-red-from-other-sessions-unpushed-commits-2026-10-10.md)
- [structural-guards-should-fail-before-the-full-land-round-2026-10-15.md](structural-guards-should-fail-before-the-full-land-round-2026-10-15.md)
- [full-host-suite-per-branch-cost-hours-while-failures-sat-in-the-guard-set-2026-10-04.md](full-host-suite-per-branch-cost-hours-while-failures-sat-in-the-guard-set-2026-10-04.md)
