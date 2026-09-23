---
title: An inability to check is not a clean result
date: 2026-09-07
category: workflow-issues
module: verification
problem_type: workflow_issue
component: development_workflow
severity: critical
applies_when:
  - "adding a guard, gate, contract test, or any control whose job is to refuse something"
  - "a shell probe's output is consumed without checking the command's exit status"
  - "a test asserts on the result of a subprocess, filesystem probe, or environment lookup"
  - "changing a template, default, or example file that a documented human procedure copies"
  - "a plan defers a claim to hardware when upstream source could answer it"
symptoms:
  - "a control is green in CI and survives review, but mutating the thing it guards leaves it green"
  - "a shell guard treats a failed command's empty stdout as \"nothing found\" and opens"
  - "a test suite reports skipped or passed for a gate that was never actually exercised"
  - "identical test-file runs give different pass/skip/fail counts across invocations"
  - "a documented human path (README quickstart, deploy script) breaks while the suite stays green"
root_cause: missing_validation
resolution_type: workflow_improvement
related_components:
  - testing_framework
  - infrastructure
  - documentation
tags:
  - fail-open
  - mutation-testing
  - silent-failure
  - verification-discipline
  - false-green-tests
  - bash
  - deployment-gates
  - flaky-tests
---

# An inability to check is not a clean result

> **Track: knowledge.** The six instances below were each fixed as bugs, but the durable
> thing is not any one fix — it is the shape they share and the verification discipline
> that was the only reliable way to find them.
>
> All commits referenced here landed on branch `feat/dds-phase0-measurement`, which is
> **not merged to `main`** as of writing. The SHAs are bare branch commits and will be
> rewritten by any rebase or squash, so treat them as pointers into that branch's history,
> not as durable identifiers. The repo has no configured remote, so there are no PR numbers.

## Context

A single session on `feat/dds-phase0-measurement` set out to do two unrelated things:
reduce DDS/ROS 2 message load (ADR D-34) and fix a per-robot identity collision
(ADR D-33). It found six defects that had nothing to do with each other — one in a
shell installer, one in a Python contract test, one in bash arithmetic, one in a motor
safety preflight, one in a pytest fixture helper, one in three human-followed documents.

They shared exactly one shape.

**An inability to check was recorded as a clean result.** In each case some component
was asked a question, could not answer it, and returned the same value it would have
returned if the answer were "nothing is wrong." A compose command that failed printed
no container IDs, which is indistinguishable from "no containers running." A bash probe
that timed out returned an empty string, which became an empty path, which sent a script
under test to its production defaults. A `set_env_default` that found the key already
present did nothing, which is indistinguishable from "the default was applied."

Every one of these was green in CI at the time. Several had been read by two independent
expert reviewers and survived. Two of them had already been "fixed" twice by earlier plan
revisions, and both fixes were no-ops that left the tests green.

The friction that prompted this document is that *reading* did not catch any of them, and
*the test suite reporting success* was in several cases the mechanism by which they hid.

### How the code got this shape (session history)

None of this was carelessness, which is the part worth understanding before judging the
code. Prior sessions in this repo (Codex, 2026-08-31 to 2026-09-01) show each ingredient
being chosen deliberately, for a reason that was correct at the time:

- **`.env` had to survive re-install.** A code review flagged as a merge blocker that
  `rsync --delete` into `/opt/rosy` erased the device's `.env`. Preserving per-device
  identity across re-installation became a hard-won constraint — so the installer used a
  write-only-if-absent primitive precisely so it could never clobber a commissioned robot.
  That primitive was right; treating a call to it as proof of the resulting value was not.
- **A shared default had to exist.** An early critical review found the two containers
  landing in *different* namespaces, so command and state topics never connected. The fix
  was to make both resolve to `/rosy_01`. A concrete default in the template solved a real
  connectivity bug, and then quietly became the collision.
- **The same failure shape had already bitten once.** During dashboard verification a
  harness concluded the server was ready because *port 18080 was open* — the listener was
  an unrelated `SimpleHTTPServer`, and Rosy had failed to start with `WinError 10048`. The
  recorded root cause was that "port open" is the wrong evidence for "service up." The
  repeated lesson across those sessions was already written down as *container presence is
  not evidence the thing inside is alive.* Nobody generalised it into a rule, so it
  recurred in a different subsystem.

Two constraints pulling in opposite directions — never overwrite device identity, always
have a working default — produced a template that was authoritative-looking and a writer
that could not fire. Neither half is wrong alone.

## Guidance

### 1. Every "nothing found" answer must be distinguishable from "could not look"

Any call that can fail, time out, or be absent has three outcomes, not two: the thing is
there, the thing is not there, and *I could not tell*. Collapsing the third into the
second is the defect. Branch on the failure signal — exit status, exception,
empty-but-should-not-be — before you interpret the value.

The motor preflight is the clearest form. It asks compose which motor containers are
running, and refuses to touch the UART if any are (`deploy/robot/verify/verify-motors.sh:87-92`):

```bash
if ! running="$("${compose[@]}" --profile motor --profile hardware ps -q rosy-motor rosy-io)"; then
    fail "cannot tell whether the motor runtime is active — docker compose failed; fix that before probing the UART"
fi
if [[ -n "$running" ]]; then
    fail "motor runtime is active; switch to core mode before the read-only probe"
fi
```

The earlier version had only the second `if`. A compose that fails prints nothing on
stdout, so the guard read "nothing running" and let the probe proceed against a live
motor runtime. Missing docker did it. An unreadable compose file did it. And after D-33,
an unset identity did it too, because `deploy/robot/compose.yaml:4` and `:8` now carry
`${ROS_DOMAIN_ID:?...}` / `${ROSY_NAMESPACE:?...}` guards that make compose exit non-zero
before it can list anything. Verified against real Docker: with identity unset, `ps -q`
exits 1 with empty stdout, and the old guard evaluated false.

The same rule in Python, where the fix is to raise rather than return an empty answer
(`test/test_image_pipeline.py:315-348`):

```python
    last = ""
    for attempt in range(3):
        result = subprocess.run(["bash", "-c", "pwd"], cwd=str(path), ..., check=False, timeout=60)
        answer = result.stdout.strip()
        if result.returncode == 0 and answer:
            return answer
        last = (result.stderr or "").strip() or f"exit {result.returncode}, empty stdout"
    raise RuntimeError(
        f"bash could not report a path for {path} after 3 attempts ({last}). "
        f"Refusing to continue: an empty path silently sends the script under "
        f"test to its production defaults and turns this into a false verdict."
    )
```

### 2. A default-if-absent write is not a guarantee that the value is right

`set_env_default` writes only when the key is missing (`deploy/robot/install-pi.sh:220-225`).
That is correct behavior and a correct primitive — it exists so a re-install cannot
renumber a commissioned robot. It is *not* an assertion. Calling it tells you nothing
about the resulting value, because its no-op path and its success path are equally silent.

When the value matters, check what is actually there and fail on a mismatch.
`require_robot_identity` does both, checking every key before writing any
(`deploy/robot/install-pi.sh:259-266`):

```bash
    for key in ROS_DOMAIN_ID ROSY_NAMESPACE; do
        existing="$(get_env_value "$env_file" "$key")"
        if [[ -n "$existing" && "$existing" != "${derived[$key]}" ]]; then
            fail "$env_file already has $key=$existing but ROSY_ROBOT_NUMBER=$number derives ${derived[$key]}. ..."
        fi
    done
    set_env_default "$env_file" ROS_DOMAIN_ID "$domain"
    set_env_default "$env_file" ROSY_NAMESPACE "$namespace"
```

All checks first, then all writes — writing one key and failing on the next leaves a unit
with a half-migrated identity, the exact state the work exists to eliminate.

### 3. When two readings of an input can disagree silently, refuse the input

`ROSY_ROBOT_NUMBER=010` used to produce domain 48 and namespace `rosy_08`. Bash arithmetic
reads a leading zero as octal, and `printf '%02d'` agrees with it, so both halves of the
identity were *consistently* wrong. No cross-check between them could detect it, because
there was no disagreement to detect. `08` and `09` behaved differently again — they died
inside bash with "value too great for base," giving three behaviors for three adjacent
inputs.

The fix is not to pick an interpretation. It is to refuse the ambiguity
(`deploy/robot/install-pi.sh:246-250`):

```bash
    [[ "$number" =~ ^(0|[1-9][0-9]*)$ ]] || fail "ROSY_ROBOT_NUMBER must be a decimal integer with no leading zero, got '$number'"
    domain=$((40 + 10#$number))
```

The regex refuses leading zeros; `10#` forces base ten as a second line of defence. The
in-file comment states why refusing beats guessing:

> `010` 이 10 인지 8 인지는 우리가 정할 일이 아니라 거절할 일이다.
> ("Whether `010` means 10 or 8 is not ours to decide — it is ours to refuse.")

`deploy/robot/deploy-from-windows.ps1:27-31` carries the same regex, so the Windows
entrypoint refuses the same inputs rather than sending them down to bash to be
reinterpreted.

### 4. Mutation-test every new control before believing it

Change the thing the test guards, confirm red, restore, confirm green. This is the only
step in the session that reliably caught the defect class, and it caught two "controls"
during plan review that could not fail at all.

The worst offender asserted that the identity gate ran before any container start:

```python
assert text.index('require_robot_identity "$env_file"') < text.index("build_and_start_core() {") \
       or text.index("write_runtime_environment") < text.index("build_and_start_core")
```

The `or` branch compares the file positions of two **function definitions**, fixed by
source layout and completely unaffected by where either function is *called*. The
assertion was a tautology. A reviewer moved the gate below `docker compose build` and the
test stayed green.

The replacement makes three separate structural claims
(`test/test_dds_identity_contracts.py:147-170`): the gate lives inside the caller's body,
there is exactly one call site (without which the containment check proves nothing), and
`main()` calls the caller before the container starter.

```python
    body = text[
        text.index("write_runtime_environment() {"): text.index("build_and_start_core() {")
    ]
    assert 'require_robot_identity "$env_file"' in body, (...)
    assert text.count('require_robot_identity "') == 1, (
        "exactly one call site, or the containment check above proves nothing"
    )
    calls = [line.strip() for line in text[text.index("main() {"):].splitlines()]
    assert calls.index("write_runtime_environment") < calls.index("build_and_start_core")
```

### 5. Confirm the mutation actually landed

Once during this session a mutation script had a syntax error, the mutation never applied,
and the test's subsequent pass was therefore meaningless — the same defect one level up, in
the tooling used to find the defect. `grep -c` on the mutated marker before trusting the
red became the rule. **A mutation test you did not verify as applied is a control you did
not test.**

### 6. Mock the boundary and execute; do not re-read

Reading a script tells you what it says. Running it under a stubbed boundary tells you
what it does. A stub `docker` placed on PATH exercised the full report path of a new
measurement script and found `set -e` plus `pipefail` converting an absent topic into a
silent mid-report abort. The absent topic was absent *by design* after the config change
(`publish_voxel_map: False` means `voxel_grid` is never created), so every real run would
have truncated (`deploy/robot/measure-dds-baseline.sh:115-119`).

### 7. Run the commands the docs tell humans to run

This is the only thing that found instance 6, and no amount of test-suite green would have.
The test suite exercises code paths; it does not execute a README.

### 8. Read upstream source instead of inferring from it

Two Nav2 claims in the plan were marked "verify on the rig" — deferred to hardware nobody
had. Both were answerable from `ros-navigation/navigation2` at `jazzy`, and doing so
surfaced a fact the plan never contained: `Costmap2DPublisher::publishCostmap()` gates each
topic on `get_subscription_count() > 0 || !costmap_published_once_`. Attaching
`ros2 topic bw` creates a subscription, which means **the instrument manufactures the
traffic it measures**. Written up at
`docs/plans/2026-09-06-dds-bandwidth-reduction-design.md:74` onward.

"Verify on the rig" is a legitimate answer for behavior. It is not a legitimate answer for
what the source code says.

## Why This Matters

The severity here comes from the failure direction. Each of these defects made a system
report success while doing nothing, or the wrong thing, and success is the answer nobody
investigates.

- **The inert guard shipped identical identity to every unit.** The key was never absent,
  so the derivation could not fire. Every released robot would have come up on the same DDS
  domain and the same namespace — a collision on the wire, not a cosmetic problem.
- **The fail-open motor gate is a physical safety control.** Its purpose is to keep a
  read-only UART probe away from a bus the motor runtime owns. It opened whenever docker
  was missing, whenever the compose file was unreadable, and — after D-33 — whenever
  identity was unset. That last one is the sharpest lesson available here: **hardening one
  subsystem changed the failure mode of an unrelated subsystem, and the unrelated subsystem
  interpreted the new failure as an all-clear.**
- **A flaky probe became a product verdict.** `_bash_view` returned
  `result.stdout.strip()` with `check=False` and no validation. WSL cold start on this host
  measured 5.7s against a 0.23s warm start, so the call sometimes returned empty,
  `_run_gate` built `ROSY_LAYOUT_ROOT=""`, the gate script fell back to the production
  default it was explicitly being kept away from, never saw the fabricated
  `recovery-hold.json`, exited 0 — and `test_the_gate_blocks_a_held_device` reported that a
  held device was allowed to boot. Three identical runs of that one file gave 43 passed /
  31 passed + 12 skipped / 3 failed. Separately, `bash_only` probed once at import
  (`test/test_image_pipeline.py:28-51`), and a lost race marked twelve gate tests
  **skipped** — which reads as a pass in the pytest summary line, and is how a suite quietly
  stops being a gate.
- **Green tests actively concealed all of it.** In the skip case and the tautological-
  assertion case, the suite's green was *produced by* the defect. A test that cannot fail
  and a test that was skipped are indistinguishable from a test that passed, when you are
  reading a summary line.

## When to Apply

- **A shell command's output is being interpreted without checking its exit status.**
  Especially `$(...)` inside `[[ -n ... ]]`, and especially under `set -e` with `pipefail`,
  where "this failure is normal" and "any failure exits" are easy to get backwards in
  either direction.
- **A subprocess, network call, or external tool feeds a value into a decision.** If it can
  be slow, absent, or racy, its empty answer must be a distinct outcome from its negative
  answer.
- **You are adding a control, gate, guard, or contract test.** Before believing it, mutate
  what it guards and confirm it goes red — and confirm the mutation applied.
- **A test asserts on source text rather than behavior.** Structural assertions are
  legitimate (three are load-bearing in `test/test_dds_identity_contracts.py:147-170`) but
  unusually easy to write as tautologies. Mutation-test them harder, not less.
- **A default-if-absent primitive is standing in for a correctness requirement.**
- **A change touches a file that humans copy, follow, or paste from** — templates, READMEs,
  deployment runbooks, installer wrappers. The test suite does not read these.
- **A test can skip itself based on an environment probe.** Skips read as passes; a racy
  probe converts a gate into decoration.
- **A plan defers a claim to hardware you do not have.** Check whether the claim is actually
  a source-code question first.

## Examples

### Instance 1 — the inert guard (identity)

**Before.** `deploy/robot/.env.example` assigned `ROS_DOMAIN_ID=42` and
`ROSY_NAMESPACE=rosy_01`. The installer copied the template, then called `set_env_default`
for both keys. The keys were present, so nothing happened, so every unit shipped with the
same identity.

**After.** The template assigns neither key and carries the reasoning instead
(`deploy/robot/.env.example:6-10`). `test_the_template_assigns_neither_identity_key`
(`test/test_dds_identity_contracts.py:43`) is the assertion that would have caught it: the
thing to test is not "is the call present" but "does the value actually differ."
Commit `0646969`.

### Instance 2 — a control that could not fail

**Before.** The `A or B` assertion quoted under Guidance §4, whose `B` branch compared two
function *definition* positions and was therefore always true.

**After.** Three checks — body containment, exactly one call site, `main()` call order — at
`test/test_dds_identity_contracts.py:147-170`.

### Instance 3 — octal, a silently wrong answer

**Before.** `ROSY_ROBOT_NUMBER=010` → domain 48, namespace `rosy_08`; both wrong,
consistently, so no cross-check could detect it.

**After.** `^(0|[1-9][0-9]*)$` at `deploy/robot/install-pi.sh:246` plus `10#` at `:247`;
the same regex mirrored in `deploy/robot/deploy-from-windows.ps1:27`. Regression tests cover
both the refusal (`test/test_dds_identity_contracts.py:270-281`) and that plain decimals
still derive correctly (`:289-294`). Commit `f3d339c`.

### Instance 4 — a fail-open safety gate

**Before.** `if [[ -n "$(compose ... ps -q rosy-motor rosy-io)" ]]; then fail ...` — one
branch, and compose's empty output on failure read as "nothing running."

**After.** Exit status first, then emptiness (`deploy/robot/verify/verify-motors.sh:87-92`).
Verified against real Docker and re-driven through bash with a stub `docker` that exits 1,
asserting the probe is not reached. This defect predates the identity work; the identity
work only added a third way to trigger it. Commit `057a198`.

### Instance 5 — a flaky probe became a product verdict

**After.** Bounded retry plus a raise in `_bash_view` (`test/test_image_pipeline.py:315-348`);
three probe attempts in `_bash_is_usable` (`:28-46`). Five consecutive runs at 43 passed /
0 skipped / 0 failed, against the previous 43 / 31+12 skipped / 3 failed. The failure paths
are themselves driven by monkeypatching `subprocess` — three failures raise; a transient
failure followed by an empty-but-rc-0 result followed by success recovers; bash genuinely
absent still skips. Commit `72f6895`.

### Instance 6 — the blast radius nobody executed

Removing the identity values from `.env.example` broke three human-followed paths while the
suite stayed green:

- **`README.md` quickstart** did `cp .env.example .env` then `docker compose build`, and
  compose now dies on its own `${ROS_DOMAIN_ID:?...}` guard with a message pointing at
  `install-pi.sh` — correct guidance for a robot, wrong for a development bench. The
  quickstart now sets identity between the copy and the build (`README.md:54-60`), and
  `test_the_readme_quickstart_sets_identity_before_invoking_compose`
  (`test/test_dds_identity_contracts.py:103-125`) asserts that ordering.
- **`docs/deployment/raspberry-pi-wifi-image.md`** now passes `-RobotNumber 1` (`:104`).
- **`deploy/robot/deploy-from-windows.ps1`** ran `sudo bash deploy/robot/install-pi.sh` with
  no `ROSY_ROBOT_NUMBER`, so the entire Windows→Pi deploy path failed at install. It now
  takes, requires, validates and forwards `-RobotNumber` (`:3`, `:23-31`, `:107`).

Found in the same sweep: `check_runtime_defaults` in `deploy/release/image_checks.py:202` validated
the image's `.env` for `ROSY_RUNTIME_MODE=core` but said nothing about identity. A prebuilt
image that baked identity would have reproduced the D-33 collision at image scale. It now
refuses one (`:218-227`, finding code `IMAGE_IDENTITY_BAKED`) — which matches the boundary
the ROSY OS v1 image design had already drawn: images carry no identity, first boot injects
it (session history). Commits `9f021c0` and `f4e3a1d`.

### What did not catch any of them

Code review. Every instance was read over, several by two independent expert reviewers, and
survived. Reading tells you what code says. Only mutation, execution against a stubbed
boundary, and following the documented human path tell you what it does.

## Related

- `docs/reference/ROSY ADR Log.md` — **D-33** (identity derives from one robot number;
  supersedes D-6) narrates instance 1 at decision altitude and states the general rule this
  document generalises: verification asks not "is the call present" but "does a fresh
  install actually produce a different value." **D-34** records the sibling shape — no test
  was attached to the publish rates at all.
- `test/AGENTS.md:44-51` — the operative copy for these rules, and it already carries two
  bullets of exactly this shape ("proves the click fired, not that the handler finished";
  "Opt-in tests that are never run are not coverage"). Guidance §4, §5 and the skip-reads-as-
  pass rule belong there as the next bullets.
- `docs/plans/2026-09-06-module-split-criteria.md` — arrives at the same claim independently
  for a different unit of work: record the verdict *including "nothing fired"*, and a
  criterion that no longer matches the tree is a bug in the criterion.
- `docs/plans/2026-09-03-runtime-maintainability-rules.md` — the format precedent: short,
  numbered, enforceable rules derived from a specific set of defects.
- `docs/plans/2026-09-06-dds-bandwidth-reduction-design.md` — where Guidance §8's upstream
  findings are written down.
- `deploy/robot/AGENTS.md:44-47` — the enforced-rule location for the identity half
  ("A default here is what shipped every unit as 42/rosy_01").

### Known stale, not fixed here

Left for `ce-compound-refresh` rather than edited by this run, and both are the same defect
class in documentation form — a stale statement that reads as current fact:

- **`AGENTS.md:65`** (repo root) still says "Default robot id `rosy_01`", which contradicts
  D-33 and `docs/spec/ROSY CORE SRS.md:315`. This is the file every agent loads first.
- **`test/AGENTS.md`** Key Files table has no row for `test_dds_identity_contracts.py` or
  `test_nav2_bandwidth_contracts.py`, both added on this branch.
- `docs/deployment/raspberry-pi-runtime.md:102-105` documents the domain range but not the
  leading-zero refusal, so an operator cannot learn that `ROSY_ROBOT_NUMBER=03` hard-fails.
- `docs/reference/AGENTS.md:26`'s curated ADR list omits D-33 and D-34.
