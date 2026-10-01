# Fleet-assisted localization (D-395) — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every Pinky on the 180-degree symmetric map_v2_fleet track a correct map pose with no human input, by having the robot list its pose hypotheses and Fleet arbitrate between them ([D-395](../adr/D-395-fleet-assisted-localization.md) with revisions 1 and 2, [design](2026-10-01-fleet-assisted-localization-design.md)). Phase 1 builds and proves the decision logic on the host; Phase 2+ wires it into CORE, the robot and Fleet.

**Architecture:** Phase 1 is a thin vertical slice of pure functions and classes with fixed output contracts. On the robot side, ROS-free modules under `src/runtime/sensing/control/sensing/` turn a scan into every distinct pose candidate (global search and the two reference-square slots), list unmapped lidar objects, run the UNKNOWN/CANDIDATES/LOCALIZED/SUSPECT state machine and the 3 s post-injection check; `sensing/perception/` adds a paint-hypothesis score and an HSV reference-square detector behind a backend protocol. `core_common.protocol.localization` holds the wire models (status with an explicit `map|odom` frame flag, `CandidateReport`, `LocalizationDecision`), and `StateSnapshot.localization` is the one additive snapshot field (API Ref v1.69). `src/site/fleet/fleet/localization/` scores candidates with bounded cues and decides only on a margin held for 2 s. A host end-to-end test wires all of it on the checked-in map with two simulated robots. Nothing in Phase 1 is launched, configured or served; CORE stays the only external gateway and the only final `cmd_vel` publisher.

**Tech Stack:** Python 3.12 reference (host may be newer), numpy, OpenCV (`cv2`), PyYAML, pydantic v2, pytest. No rclpy anywhere in Phase 1.

---

## Ground rules (read before Task 0)

- **Worktree.** All Phase 1 work happens in `.worktrees/d395-host`, branch `feat/d395-host-localization`, created from the repo root with `git worktree add --relative-paths .worktrees/d395-host -b feat/d395-host-localization main`. Phase 2 topics get their own `feat/d395-<topic>` worktree the same way.
- **Commits.** Commit only the paths a task names, plus the generated `index.md`/`STATUS.md` the harness rewrites for that change. Never `git add -A`, never bare `git stash`, never `--amend`, never rebase, never push. Peers commit to `main` concurrently (see `docs/solutions/workflow-issues/peers-share-one-git-index-never-amend-stage-only-your-line-2026-09-26.md`). Commit messages end with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; write them with `git commit -F - <<'EOF' … EOF` from Git Bash.
- **Python.** Use `python`, not `python3`, on Windows. Every command below runs from the worktree root and needs no rclpy.
- **Harness (D-61).** Every task that changes a module appends one entry to that module's `logs.md` with the hash slot `uncommitted` and the three fields `변경`/`증거`/`gate 변화` (Korean prose, English identifiers), then runs `python tools/harness/rosy_harness.py generate` and `python tools/harness/rosy_harness.py lint` (expected last line: `0 error(s), N warning(s)`). Use the actual commit date in the heading if it is not 2026-10-01.
- **Size budgets (D-362, `test/architecture/test_module_structure.py`).** No new file above 600 lines; the largest Phase 1 file is 246 lines. The `control` and `fleet` packages and `schemas.py` already carry verdicts with little or no regrowth allowance, so Tasks 8, 10 and 11 re-judge them with measured counts. Between Task 2 and Task 11 `test_size_verdicts_are_well_formed_and_current` may report `control` over its allowance; that one test is expected red until Task 11 Step 6, nothing else is.
- **Invariants.** CORE is the only external gateway and the only final `cmd_vel` publisher (D-2, D-267, D-269). Phase 1 changes no robot config, params, launch file or served API path. Fleet never drives wheels.
- **Paths.** Never write a Windows path into a Python string literal or a sed expression. Python code builds paths with `Path(__file__)` joins; shell steps use the Edit tool or Python file I/O on repo-relative paths.
- **Test basenames** must be unique across suites (`docs/solutions/workflow-issues/new-package-must-pass-four-full-suite-guards-2026-09-26.md`); every new name below was checked with `git ls-files "*/<name>"`.

## Spec decisions this plan takes

These are the places where the ADR and design disagree or leave a choice; the plan follows the left column. They are also listed under Open questions at the end.

| Topic | Plan follows | Why |
|---|---|---|
| Failed 3 s check | SUSPECT with `reason='inject_rejected'` (ADR Decision 7, design §9) | Design §5 diagram draws the arrow back to CANDIDATES; the ADR text and §4.1 reason list win |
| "Within 3 s" vs "held 3 s" | 0.5 s AMCL settle, then fit ≥ 0.85 on every fresh scan for 3 s; one low fit or a 0.5 s scan gap fails at once | Design §4.4 `converged` says "held 3 s"; failing fast keeps a wrong pose from living 3 s |
| A mirror injection | Passes the 3 s check (scan fit is identical on this map: measured 1.0 for both twins) | ADR Consequences claims a wrong injection falls back to SUSPECT; that is false for the mirror, so arbitration and Fleet's monitor carry that risk. Tested in Task 4 docstring and Task 11 |
| "No cue decides alone" (§7) | `last_good` (0.5) and `overhead` (0.5) weigh less than the 1.0 margin and can never decide alone; scan-asymmetric cues (paint 2.0, peers 2.0, slot 1.5, square 3.0) can | Otherwise a lone robot on a square without a camera could never localize, which contradicts rev. 2 ("the scan picks the heading") and §5 ("strong prior") |
| Lone unique candidate | Decides after the 2 s hold (gap treated as infinite) | Non-symmetric maps; the existing unique-match behaviour |
| Square sightings on the wire | Optional `CandidateReport.square_sightings` | §4.2 table predates rev. 1's `square_seen` cue |
| `expires_at` | Absolute seconds as specified; robot compares with its own clock | Needs Fleet/robot clock agreement within the 5 s TTL; flagged |
| Slots | The two reference squares with heading axis only (rev. 1 + 2), not four `{id,x,y,yaw}` slots (§10) | Revisions supersede §10 |

## File structure

| File | Responsibility | Task |
|---|---|---|
| `src/runtime/sensing/control/sensing/localization.py` (modify) | Expose `valid_beams`, `apart`, `GLOBAL_OFFSETS`, `MapAgreement.clear_poses/refine/global_results`; `global_match` keeps its answer | 1 |
| `src/runtime/sensing/control/sensing/loc_candidates.py` | `Mount`, `PoseCandidate`, `ReferenceSquare`; base/sensor transforms; `global_candidates`, `slot_candidates`, `merge` | 2 |
| `src/runtime/sensing/control/sensing/loc_objects.py` | `unmapped_objects`: unexplained returns clustered into base_link objects | 3 |
| `src/runtime/sensing/control/sensing/loc_verify.py` | `InjectionCheck`: the 3 s post-injection check | 4 |
| `src/runtime/sensing/control/sensing/loc_state.py` | `LocState`, `Step`, `LocalizationStateMachine` | 5 |
| `src/runtime/sensing/control/sensing/perception/paint_hypothesis.py` | `paint_score(paint_map, points, pose)` | 6 |
| `src/runtime/sensing/control/sensing/perception/reference_square.py` | `SquareObservation`, `SquareDetector` protocol, `HsvSquareDetector` | 7 |
| `src/runtime/sensing/test/loc_world.py` | Test-only world: checked-in map at 2 cm, ray-cast scans with peer discs, paint points | 2 |
| `src/runtime/sensing/test/test_localization_search.py`, `test_loc_candidates.py`, `test_loc_objects.py`, `test_loc_verify.py`, `test_loc_state.py`, `test_paint_hypothesis.py`, `test_reference_square.py`, `test_loc_e2e.py` | Host tests | 1–7, 11 |
| `src/contracts/foundation/core_common/protocol/localization.py` | Wire models | 8 |
| `src/contracts/foundation/core_common/protocol/schemas.py` (modify) | `StateSnapshot.localization` | 8 |
| `src/contracts/foundation/test/test_localization_contracts.py` | Model and API Ref tests | 8 |
| `docs/reference/ROSY API & Protocol Reference.md` (modify) | v1.69: §6.1 field, §7.9 models, changelog row | 8 |
| `src/runtime/api_web/core_api_web/api/app.py`, `test/test_line_follow_contract_docs.py` (modify) | The other two version pins (D-347) | 8 |
| `src/site/fleet/fleet/localization/__init__.py`, `cues.py`, `arbiter.py`, `AGENTS.md` | Fleet arbiter, pure | 9, 10 |
| `src/site/fleet/test/test_localization_cues.py`, `test_localization_arbiter.py`, `test_boundaries.py` (modify) | Fleet tests | 9, 10 |
| `test/architecture/test_module_structure.py` (modify) | Re-judged size verdicts | 8, 10, 11 |
| `AGENTS.md` rows in `control/sensing/`, `control/sensing/perception/`, `core_common/protocol/`, `fleet/` | Key-file tables | 7, 8, 9 |

---

## Phase 1 — host-testable vertical slice

### Task 0: Worktree and baseline

**Files:** none changed.

- [ ] **Step 1: Create the worktree**

Run from the repo root (`F:\Dev\Control\Robot\ROS\Rosy\Rosy OS`):

```bash
git worktree add --relative-paths .worktrees/d395-host -b feat/d395-host-localization main
cd .worktrees/d395-host
```

Expected: `Preparing worktree (new branch 'feat/d395-host-localization')`.

- [ ] **Step 2: Record the baseline**

```bash
python -m pytest src/runtime/sensing/test/test_localization.py src/runtime/sensing/test/test_map_v2_fleet_reference_squares.py src/runtime/sensing/test/test_paint_localizer.py src/site/fleet/test/test_boundaries.py src/contracts/foundation/test src/runtime/gateway/test/test_protocol_schemas.py src/runtime/gateway/test/test_protocol_version_alignment.py test/test_line_follow_contract_docs.py test/architecture/test_module_structure.py -q
python tools/harness/rosy_harness.py lint
```

Expected: all pass (one skip in `test_localization.py` is pre-existing), lint `0 error(s)`. If anything fails on a clean `main`, write it down with its message before changing code; it is not this plan's to fix. At plan time (2026-10-01) these failed on main for reasons outside this plan and may still: `test/test_behavior_test_ownership.py` (new `gateway/test/test_emotion_map.py`, `test_lidar_mount_source.py`), `test_over_budget_code_has_a_recorded_verdict` (`hmi/dashboard/app.js` 803 lines), `src/site/fleet/test/test_console_camera_pairing.py::test_the_shell_wires_the_panel_and_reasks_it_on_every_login`, and the timing test `src/runtime/sensing/test/test_follower_budget.py` under host load (it asks for an idle host).

- [ ] **Step 3: Read the live contract version**

```bash
grep -n '^\*\*Version:\*\*' "docs/reference/ROSY API & Protocol Reference.md"
```

Expected: `5:**Version:** v1.68`. If main has moved past v1.68, Task 8 uses the next free MINOR everywhere it says v1.69.

---

### Task 1: Expose the global search without changing its answer

`MapAgreement.global_match` refuses whenever the best pose is not unique, which is always on this map. Split it so the refined candidate list, the footprint mask and one-seed refinement are reusable; `global_match` returns exactly what it returned before.

**Files:**
- Modify: `src/runtime/sensing/control/sensing/localization.py`
- Test: `src/runtime/sensing/test/test_localization_search.py`

- [ ] **Step 1: Write the failing test**

Create `src/runtime/sensing/test/test_localization_search.py`:

```python
"""D-395: the global search exposes every refined candidate; global_match keeps its answer."""
import math
from pathlib import Path

import numpy as np

from control.sensing.localization import MapAgreement, apart, valid_beams

FIXTURE = Path(__file__).parent / "fixtures/gazebo_localization_corner.npz"


def recorded():
    d = np.load(FIXTURE)
    return d, MapAgreement(d["grid"], float(d["resolution"]), d["origin"])


def test_valid_beams_drop_nan_short_and_non_finite_angles():
    ranges, angles = valid_beams([1., math.nan, .04, 2., 3.], [0., .1, .2, math.inf, .4])
    assert ranges.tolist() == [1., 3.] and angles.tolist() == [0., .4]


def test_apart_separates_by_position_or_heading_with_wrap():
    assert not apart((0., 0., 0.), (.1, 0., .2))
    assert apart((0., 0., 0.), (.2, 0., 0.))
    assert apart((0., 0., 0.), (0., 0., .4))
    assert not apart((0., 0., math.pi - .1), (0., 0., -math.pi + .1))


def test_clear_poses_keeps_the_footprint_off_walls_and_unknown():
    grid = np.zeros((50, 50), dtype=np.int8)
    grid[:, 40] = 100
    grid[10, 10] = -1
    clear = MapAgreement(grid, .02, (0., 0.)).clear_poses(.1)
    assert clear[25, 25]
    assert not clear[25, 36]      # 8 cm from the wall: inside radius + half a cell
    assert not clear[10, 12]      # unknown is never free


def test_refine_keeps_three_clear_poses_per_seed_around_the_truth():
    d, m = recorded()
    ranges, angles = valid_beams(d["ranges"], d["angles"])
    out = m.refine([np.array(d["truth"])], ranges, angles, m.clear_poses(.105))
    assert len(out) == 3
    best = max(out, key=lambda item: item[0])
    assert math.dist(best[2][:2], d["truth"][:2]) < .02


def test_global_results_are_best_first_and_global_match_reports_the_first():
    d, m = recorded()
    results, reason = m.global_results(d["ranges"], d["angles"], .105)
    assert reason is None and len(results) >= 2
    scores = [r[0] for r in results]
    assert scores == sorted(scores, reverse=True)
    match = m.global_match(d["ranges"], d["angles"], .105)
    assert np.allclose(results[0][2], match["pose"]) and match["unique"]


def test_global_results_name_the_reason_for_an_empty_answer():
    m = MapAgreement(np.zeros((20, 20), dtype=np.int8), .02, (0., 0.))
    assert m.global_results([1.] * 10, np.linspace(-1., 1., 10), .1) == ([], "insufficient-scan")
```

- [ ] **Step 2: Run it and see it fail**

```bash
python -m pytest src/runtime/sensing/test/test_localization_search.py -q
```

Expected: collection error, `ImportError: cannot import name 'apart' from 'control.sensing.localization'`.

- [ ] **Step 3: Add the shared helpers**

In `src/runtime/sensing/control/sensing/localization.py`, directly after the line `import numpy as np`, insert:

```python
#: Refinement around one global seed: +-5 cm in 1 cm steps, +-5 deg in 1 deg steps.
GLOBAL_OFFSETS = np.array(np.meshgrid(
    np.arange(-.05, .051, .01), np.arange(-.05, .051, .01), np.radians(np.arange(-5., 5.1, 1.)),
    indexing='ij')).reshape(3, -1).T
#: Two poses closer than this in both position and heading are one hypothesis.
SEPARATION_M = .18
SEPARATION_RAD = .3


def wrap(angle):
    return math.atan2(math.sin(angle), math.cos(angle))


def apart(a, b):
    """True when two (x, y, yaw) poses are distinct hypotheses, not one blurred twice."""
    return math.dist(a[:2], b[:2]) > SEPARATION_M or abs(wrap(a[2]-b[2])) > SEPARATION_RAD


def valid_beams(ranges, angles):
    """Finite beams beyond the 5 cm lidar minimum, as arrays."""
    ranges, angles = np.asarray(ranges, dtype=float), np.asarray(angles, dtype=float)
    valid = np.isfinite(ranges) & (ranges > .05) & np.isfinite(angles)
    return ranges[valid], angles[valid]
```

- [ ] **Step 4: Replace `global_match` with the split search**

Replace everything from the line `    def global_match(self, ranges, angles, radius, minimum=.9, margin=.04):` to the end of the file with:

```python
    def clear_poses(self, radius):
        """Cells where a footprint of `radius` is wholly free. Unknown is never free."""
        h, w = self.grid.shape
        free = self.grid == 0
        blocked = ~free
        clear = free.copy()
        inflated_radius = radius + self.resolution/math.sqrt(2)
        cells = int(math.ceil(inflated_radius/self.resolution))
        for dy in range(-cells, cells+1):
            for dx in range(-cells, cells+1):
                if math.hypot(dx, dy)*self.resolution > inflated_radius:
                    continue
                y0, y1 = max(0, dy), min(h, h+dy)
                x0, x1 = max(0, dx), min(w, w+dx)
                if y1 > y0 and x1 > x0:
                    clear[y0:y1, x0:x1] &= ~blocked[y0-dy:y1-dy, x0-dx:x1-dx]
        return clear

    def refine(self, seeds, ranges, angles, clear, offsets=None):
        """Best three refinements per seed as (0.7*agreement + 0.3*quality, agreement, pose).

        Inputs are valid sensor-frame beams (see `valid_beams`); poses are sensor poses."""
        offsets = GLOBAL_OFFSETS if offsets is None else offsets
        h, w = self.grid.shape
        results = []
        for seed in seeds:
            poses = np.asarray(seed) + offsets
            indices = np.floor((poses[:, :2]-self.origin)/self.resolution).astype(int)
            inside = (indices[:, 0] >= 0) & (indices[:, 0] < w) & (indices[:, 1] >= 0) & (indices[:, 1] < h)
            allowed = np.zeros(len(poses), dtype=bool)
            allowed[inside] = clear[indices[inside, 1], indices[inside, 0]]
            poses = poses[allowed]
            if not len(poses):
                continue
            quality = self._qualities(poses, ranges, angles)
            for idx in np.argsort(quality)[-3:]:
                pose = poses[idx]
                agreement = self.score(pose, ranges, angles)
                results.append((agreement*.7 + float(quality[idx])*.3, agreement, pose))
        return results

    def global_results(self, ranges, angles, radius):
        """Every refined sensor-pose candidate, best first, and a reason when there are none.

        Coarse-to-fine: 4 cm x 5 deg seeds, the 48 best distinct ones refined by
        GLOBAL_OFFSETS. Inputs are sensor-frame observations."""
        ranges, angles = valid_beams(ranges, angles)
        if len(ranges) < 30:
            return [], 'insufficient-scan'
        clear = self.clear_poses(radius)
        stride = max(1, round(.04/self.resolution))
        yy, xx = np.nonzero(clear[::stride, ::stride])
        if not len(xx):
            return [], 'no-footprint-clear-candidate'
        xy = np.column_stack((xx*stride+.5, yy*stride+.5))*self.resolution + self.origin
        candidates = []
        for theta in np.arange(-math.pi, math.pi, math.radians(5)):
            poses = np.column_stack((xy, np.full(len(xy), theta)))
            quality = self._qualities(poses, ranges[::2], angles[::2])
            for idx in np.argsort(quality)[-16:]:
                candidates.append((float(quality[idx]), poses[idx]))
        seeds = []
        for quality, pose in sorted(candidates, key=lambda item: item[0], reverse=True):
            if all(apart(pose, other) for other in seeds):
                seeds.append(pose)
            if len(seeds) >= 48:
                break
        results = self.refine(seeds, ranges, angles, clear)
        if not results:
            return [], 'no-refined-candidate'
        results.sort(key=lambda item: item[0], reverse=True)
        return results, None

    def global_match(self, ranges, angles, radius, minimum=.9, margin=.04):
        """Coarse-to-fine scan search. Repeated geometry must remain ambiguous.

        Returns a candidate, not driving authority. AMCL and subsequent fresh
        scans still have to confirm it. Inputs are sensor-frame observations.
        """
        results, reason = self.global_results(ranges, angles, radius)
        if reason:
            return {'unique': False, 'reason': reason}
        best = results[0]
        competitors = [r for r in results[1:] if apart(r[2], best[2])]
        gap = best[0] - competitors[0][0] if competitors else 1.
        return {'unique': bool(best[1] >= minimum and gap >= margin),
                'pose': best[2].tolist(), 'agreement': best[1], 'quality': best[0], 'margin': gap}
```

- [ ] **Step 5: Run the new and the existing localization tests**

```bash
python -m pytest src/runtime/sensing/test/test_localization_search.py src/runtime/sensing/test/test_localization.py src/runtime/sensing/test/test_localization_gate.py -q
```

Expected: `15 passed, 1 skipped` (the skip is pre-existing). `test_recorded_gazebo_corner_is_not_lost_between_coarse_candidates` passing is the proof that `global_match` kept its answer.

- [ ] **Step 6: Log, generate, lint**

Append to `src/runtime/sensing/logs.md`:

```markdown
## 2026-10-01 · uncommitted · refactor(localization): 전역 탐색을 후보 목록·발자국 마스크·시드 정밀화로 나눔 (D-395 1단계)
- 변경: `sensing/localization.py`에 `valid_beams`, `apart`(0.18 m / 0.3 rad), `GLOBAL_OFFSETS`, `MapAgreement.clear_poses/refine/global_results`를 꺼냈다. `global_match`는 같은 계산을 거쳐 같은 답을 낸다. 대칭 맵에서 유일하지 않다고 버리던 후보를 D-395 후보 목록이 쓰게 하려는 준비다.
- 증거: `test_localization_search.py`(신규 6), `test_localization.py`의 기록된 Gazebo 모서리 시험(유일 해·2 cm) 그대로 통과, `test_localization_gate.py`.
- gate 변화: 없음(SOURCE). 노드 동작 불변.
- 결정: D-395 Proposed(설계 승인, 1단계 호스트 전용).
```

Then:

```bash
python tools/harness/rosy_harness.py generate
python tools/harness/rosy_harness.py lint
git status --short
```

Expected: lint `0 error(s)`; status shows only `localization.py`, the new test, `src/runtime/sensing/logs.md`, `src/runtime/sensing/index.md` and possibly `STATUS.md`.

- [ ] **Step 7: Commit**

```bash
git add src/runtime/sensing/control/sensing/localization.py src/runtime/sensing/test/test_localization_search.py src/runtime/sensing/logs.md src/runtime/sensing/index.md
git add STATUS.md 2>/dev/null; git status --short
git commit -F - <<'EOF'
refactor(localization): expose the global search as candidates, mask and refinement (D-395)

global_match keeps its answer; the split lets the D-395 candidate list reuse it.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

(`git add STATUS.md` only matters if `generate` changed it; if `git status` showed no `STATUS.md`, skip that line.)

---

### Task 2: Every pose hypothesis, mirror included

**Files:**
- Create: `src/runtime/sensing/control/sensing/loc_candidates.py`
- Create: `src/runtime/sensing/test/loc_world.py` (test helper, not a test)
- Test: `src/runtime/sensing/test/test_loc_candidates.py`

- [ ] **Step 1: Write the test world helper**

Create `src/runtime/sensing/test/loc_world.py`. It reads the checked-in `map_v2_fleet.pgm` (not a generated map), so the symmetry under test is the real one; the ray caster is ours, which is why Task 2 also checks a recorded Gazebo scan.

```python
"""Host-only map_v2_fleet world for the D-395 tests: the checked-in occupancy map
at 2 cm, ray-cast lidar scans with other robots as discs, and the floor paint a
camera would see. Truth lives here; the code under test only sees scans."""
from __future__ import annotations

import functools
import math
from pathlib import Path

import cv2
import numpy as np
import yaml

from control.sensing.loc_candidates import Mount, reference_squares, sensor_from_base
from control.sensing.localization import MapAgreement

BUNDLE = Path(__file__).resolve().parents[1] / "map" / "map_v2_fleet"
#: map_v2_fleet.yaml: 5 mm cells, origin (-1.705, -0.93). 4x max-pooled to 2 cm
#: keeps the walls and makes one global search take seconds, not tens of seconds.
RESOLUTION, ORIGIN, DOWNSAMPLE = .005, (-1.705, -.93), 4
#: Lidar 12 mm ahead and 8 mm right of base_link, scan 0 at the rear (D-397 nominal).
MOUNT = Mount(.012, -.008, math.pi)
BEAMS, MAX_RANGE, PEER_RADIUS = 120, 3.5, .06
SQUARES = reference_squares(yaml.safe_load((BUNDLE / "lane_rules.yaml").read_text(encoding="utf-8")))


@functools.lru_cache(maxsize=1)
def field() -> MapAgreement:
    image = cv2.imread(str(BUNDLE / "maps" / "map_v2_fleet.pgm"), cv2.IMREAD_UNCHANGED)
    p = (255. - image) / 255.             # trinary, negate 0: dark is occupied
    grid = np.where(p > .65, 100, np.where(p < .196, 0, -1)).astype(np.int8)[::-1]
    k = DOWNSAMPLE
    h, w = grid.shape[0] // k * k, grid.shape[1] // k * k
    blocks = grid[:h, :w].reshape(h // k, k, w // k, k)
    pooled = np.where((blocks >= 65).any(axis=(1, 3)), 100,
                      np.where((blocks < 0).any(axis=(1, 3)), -1, 0)).astype(np.int8)
    return MapAgreement(pooled, RESOLUTION * k, ORIGIN)


def mirror(pose):
    """The 180-degree twin every scan on this map also fits."""
    return (-pose[0], -pose[1], math.atan2(math.sin(pose[2] + math.pi), math.cos(pose[2] + math.pi)))


def scan(pose, peers=()):
    """Sensor-frame (ranges, angles) seen from base pose `pose`; NaN means no return."""
    f = field()
    sx, sy, syaw = sensor_from_base(pose, MOUNT)
    angles = np.linspace(-math.pi, math.pi, BEAMS, endpoint=False)
    steps = np.arange(.05, MAX_RANGE, f.resolution / 2)
    heading = syaw + angles
    px = sx + np.cos(heading)[:, None] * steps[None, :]
    py = sy + np.sin(heading)[:, None] * steps[None, :]
    ix = np.floor((px - f.origin[0]) / f.resolution).astype(int)
    iy = np.floor((py - f.origin[1]) / f.resolution).astype(int)
    h, w = f.grid.shape
    inside = (ix >= 0) & (ix < w) & (iy >= 0) & (iy < h)
    hit = ~inside
    hit[inside] = f.grid[iy[inside], ix[inside]] >= 65
    for peer in peers:
        hit |= np.hypot(px - peer[0], py - peer[1]) <= PEER_RADIUS
    first = np.argmax(hit, axis=1)
    ranges = np.where(hit.any(axis=1), steps[first], np.nan)
    return ranges, angles


@functools.lru_cache(maxsize=1)
def _paint_xy():
    from control.sensing.perception.paint_localizer import PaintMap
    paint = PaintMap.from_bundle()
    rows, cols = np.nonzero(paint.paint)
    return paint, np.column_stack((paint.x0 + cols * paint.raster_m, paint.y1 - rows * paint.raster_m))


def paint_map():
    return _paint_xy()[0]


def paint_points(pose, ahead=(.08, .40), half_width=.20, every=7):
    """Robot-frame (forward, left) floor points of paint the front camera would see."""
    _, xy = _paint_xy()
    c, s = math.cos(pose[2]), math.sin(pose[2])
    rel = xy - np.asarray(pose[:2])
    forward, left = rel[:, 0] * c + rel[:, 1] * s, -rel[:, 0] * s + rel[:, 1] * c
    keep = (forward > ahead[0]) & (forward < ahead[1]) & (np.abs(left) < half_width)
    return np.column_stack((forward[keep], left[keep]))[::every]
```

- [ ] **Step 2: Write the failing test**

Create `src/runtime/sensing/test/test_loc_candidates.py`:

```python
"""D-395: the robot lists every pose hypothesis, mirror included, instead of refusing."""
import math
from pathlib import Path

import numpy as np
import pytest

from control.sensing.loc_candidates import (
    Mount, PoseCandidate, base_from_sensor, global_candidates, merge, reference_squares,
    sensor_from_base, slot_candidates)
from control.sensing.localization import MapAgreement
from loc_world import MOUNT, SQUARES, field, mirror, scan

RADIUS = .105


def near(candidate, pose, xy=.03, yaw=math.radians(4)):
    d = math.atan2(math.sin(candidate.yaw - pose[2]), math.cos(candidate.yaw - pose[2]))
    return math.dist((candidate.x, candidate.y), pose[:2]) <= xy and abs(d) <= yaw


def test_sensor_and_base_poses_round_trip_through_the_rotated_mount():
    base = (.3, -.2, 1.0)
    sensor = sensor_from_base(base, MOUNT)
    assert sensor[2] == pytest.approx(1.0 + math.pi - 2 * math.pi)
    assert base_from_sensor(sensor, MOUNT) == pytest.approx(base)
    assert sensor_from_base(base, Mount(0., 0., 0.)) == pytest.approx(base)


def test_reference_squares_come_from_lane_rules_with_the_axis_in_radians():
    assert [(s.id, s.x, s.y) for s in SQUARES] == [("A", -1.26, .49), ("B", .86, -.52)]
    assert [s.axis_rad for s in SQUARES] == pytest.approx([math.pi / 2, 0.])
    assert reference_squares({}) == [] and reference_squares(None) == []


def test_global_search_returns_the_pose_and_its_mirror_on_the_symmetric_track():
    truth = (0., -.51, 0.)
    ranges, angles = scan(truth)
    found = global_candidates(field(), ranges, angles, RADIUS, MOUNT)
    assert 2 <= len(found) <= 4
    assert any(near(c, truth) for c in found)
    assert any(near(c, mirror(truth)) for c in found)
    assert all(c.origin == "global" and c.scan_fit >= .9 for c in found)


@pytest.mark.parametrize("truth, square", [((-1.26, .49, -math.pi / 2), "A"),
                                           ((.86, -.52, 0.), "B")])
def test_a_robot_on_a_square_gets_one_slot_candidate_and_the_scan_picks_the_heading(truth, square):
    ranges, angles = scan(truth)
    found = slot_candidates(field(), SQUARES, ranges, angles, RADIUS, MOUNT)
    assert len(found) == 1
    assert found[0].origin == "slot:" + square and near(found[0], truth)


def test_an_off_slot_robot_gets_no_slot_candidate():
    ranges, angles = scan((0., -.51, 0.))
    assert slot_candidates(field(), SQUARES, ranges, angles, RADIUS, MOUNT) == []


def test_too_few_beams_yield_no_candidates():
    ranges = np.full(20, 1.)
    angles = np.linspace(-1, 1, 20)
    assert global_candidates(field(), ranges, angles, RADIUS, MOUNT) == []
    assert slot_candidates(field(), SQUARES, ranges, angles, RADIUS, MOUNT) == []


def test_merge_keeps_slot_candidates_first_and_drops_global_duplicates():
    slot = [PoseCandidate(-1.26, .49, -1.57, .99, "slot:A")]
    global_ = [PoseCandidate(-1.25, .48, -1.55, .98, "global"), PoseCandidate(1.26, -.49, 1.57, .98, "global")]
    assert merge(slot, global_) == [slot[0], global_[1]]


def test_a_recorded_gazebo_scan_on_an_asymmetric_map_keeps_its_true_pose():
    """Independent of loc_world's ray caster: a real Gazebo scan and map (fixture)."""
    d = np.load(Path(__file__).parent / "fixtures/gazebo_localization_corner.npz")
    m = MapAgreement(d["grid"], float(d["resolution"]), d["origin"])
    found = global_candidates(m, d["ranges"], d["angles"], RADIUS, Mount(0., 0., 0.))
    assert found and math.dist((found[0].x, found[0].y), d["truth"][:2]) < .02
```

- [ ] **Step 3: Run it and see it fail**

```bash
python -m pytest src/runtime/sensing/test/test_loc_candidates.py -q
```

Expected: collection error, `ModuleNotFoundError: No module named 'control.sensing.loc_candidates'`.

- [ ] **Step 4: Implement the candidate module**

Create `src/runtime/sensing/control/sensing/loc_candidates.py`:

```python
"""Subject: every map/scan pose hypothesis worth arbitrating (D-395).

`MapAgreement.global_match` answers "is there exactly one pose?" and refuses on
the 180-degree symmetric map_v2_fleet track. Arbitration needs the opposite:
every distinct base pose the scan supports, each with its own fit, so Fleet can
tell the true pose from its mirror with cues the robot does not hold. Nothing
here authorizes motion; a decision still passes the 3 s check (loc_verify).

Poses are base_link in the map frame unless a name says sensor. The lidar is
mounted rotated (scan 0 is the rear), so the conversion goes through `Mount`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .localization import apart, valid_beams, wrap

#: D-395 §5: a candidate within 10 cm / 20 deg of a slot earns the slot prior;
#: the same box bounds where a robot "placed on the square" can really stand.
SLOT_XY_M = .10
SLOT_YAW_RAD = math.radians(20.)
SLOT_OFFSETS = np.array(np.meshgrid(
    np.arange(-SLOT_XY_M, SLOT_XY_M + 1e-9, .02), np.arange(-SLOT_XY_M, SLOT_XY_M + 1e-9, .02),
    np.radians(np.arange(-20., 20.1, 4.)), indexing='ij')).reshape(3, -1).T


@dataclass(frozen=True)
class Mount:
    """Lidar pose in base_link: metres and radians (nominal yaw is pi, D-397)."""
    x: float
    y: float
    yaw: float


@dataclass(frozen=True)
class PoseCandidate:
    """One base_link pose hypothesis in the map frame and how well the scan fits it."""
    x: float
    y: float
    yaw: float
    scan_fit: float
    origin: str  # 'global' or 'slot:<square id>'


@dataclass(frozen=True)
class ReferenceSquare:
    """A floor square from lane_rules.yaml; robots placed on it face along `axis_rad`, either way."""
    id: str
    x: float
    y: float
    axis_rad: float


def reference_squares(rules):
    """Squares from a parsed lane_rules.yaml mapping; [] when the map has none."""
    return [ReferenceSquare(str(s['id']), float(s['centre'][0]), float(s['centre'][1]),
                            math.radians(float(s['heading_axis_deg'])))
            for s in (rules or {}).get('reference_squares') or ()]


def base_from_sensor(sensor, mount):
    yaw = wrap(sensor[2] - mount.yaw)
    c, s = math.cos(yaw), math.sin(yaw)
    return (float(sensor[0] - c*mount.x + s*mount.y), float(sensor[1] - s*mount.x - c*mount.y), yaw)


def sensor_from_base(base, mount):
    c, s = math.cos(base[2]), math.sin(base[2])
    return (base[0] + c*mount.x - s*mount.y, base[1] + s*mount.x + c*mount.y, wrap(base[2] + mount.yaw))


def distinct(results, minimum_fit=.9, keep_within=.05, limit=4):
    """(sensor_pose, agreement) for each distinct hypothesis near the best one.

    `results` is `MapAgreement.global_results` output, best first. A pose is
    kept when its scan agreement reaches `minimum_fit` and its combined score is
    within `keep_within` of the best; the mirror on a symmetric map is both."""
    if not results:
        return []
    best = results[0][0]
    picked = []
    for combined, agreement, pose in results:
        if agreement < minimum_fit or combined < best - keep_within:
            continue
        if all(apart(pose, other) for other, _ in picked):
            picked.append((pose, float(agreement)))
        if len(picked) >= limit:
            break
    return picked


def global_candidates(field, ranges, angles, radius, mount, minimum_fit=.9, keep_within=.05, limit=4):
    """Every distinct global pose; [] when the scan or the map cannot support one."""
    results, _ = field.global_results(ranges, angles, radius)
    return [PoseCandidate(*base_from_sensor(pose, mount), scan_fit=fit, origin='global')
            for pose, fit in distinct(results, minimum_fit, keep_within, limit)]


def slot_candidates(field, squares, ranges, angles, radius, mount, minimum_fit=.9):
    """Axis and axis+180 at each square (D-395 rev. 2), refined within the slot box.

    The square is off-centre along its axis, so the front and rear walls differ
    and the scan fit keeps one heading; a blocked view can keep both or neither."""
    ranges, angles = valid_beams(ranges, angles)
    if len(ranges) < 30 or not squares:
        return []
    clear = field.clear_poses(radius)
    out = []
    for square in squares:
        for yaw in (square.axis_rad, square.axis_rad + math.pi):
            seed = np.array(sensor_from_base((square.x, square.y, wrap(yaw)), mount))
            refined = field.refine([seed], ranges, angles, clear, SLOT_OFFSETS)
            if not refined:
                continue
            _, fit, pose = max(refined, key=lambda item: item[0])
            if fit >= minimum_fit:
                out.append(PoseCandidate(*base_from_sensor(pose, mount), scan_fit=float(fit),
                                         origin='slot:' + square.id))
    return out


def merge(slot, global_):
    """Slot candidates first, then global ones that are not the same hypothesis."""
    out = list(slot)
    for candidate in global_:
        pose = (candidate.x, candidate.y, candidate.yaw)
        if all(apart(pose, (o.x, o.y, o.yaw)) for o in out):
            out.append(candidate)
    return out
```

- [ ] **Step 5: Run it and see it pass**

```bash
python -m pytest src/runtime/sensing/test/test_loc_candidates.py -q
```

Expected: `9 passed` in about 20 s (two global searches at 2 cm).

- [ ] **Step 6: Log, generate, lint**

Append to `src/runtime/sensing/logs.md`:

```markdown
## 2026-10-01 · uncommitted · feat(localization): 거울상까지 모든 자세 후보를 내는 순수 모듈 (D-395 1단계)
- 변경: `sensing/loc_candidates.py` — `global_candidates`(유일하지 않아도 거절하지 않고 서로 다른 가설을 최대 4개, 적합도 ≥ 0.9, 최고점에서 0.05 안), `slot_candidates`(기준 사각형마다 축·축+180°를 10 cm / 20° 안에서 정밀화, 적합도로 방향을 고름, 개정 2), `merge`, 회전 장착(스캔 0° = 후방)을 거치는 base↔sensor 변환. 시험 도우미 `test/loc_world.py`는 체크인된 `map_v2_fleet.pgm`을 2 cm로 읽고 LiDAR를 광선 투사한다.
- 증거: `test_loc_candidates.py` 9 passed — 대칭 트랙에서 참 자세와 거울상이 함께 나옴, 사각형 A(−90°)·B(0°) 위 로봇은 슬롯 후보 하나와 맞는 방향, 슬롯 밖은 슬롯 후보 없음, 기록된 Gazebo 스캔(독립 픽스처)에서 참 자세 2 cm.
- gate 변화: 없음(SOURCE/LOCAL). 노드 배선 없음.
- 결정: D-395 Proposed(설계 승인, 1단계 호스트 전용).
```

```bash
python tools/harness/rosy_harness.py generate
python tools/harness/rosy_harness.py lint
git status --short
```

Expected: lint `0 error(s)`.

- [ ] **Step 7: Commit**

```bash
git add src/runtime/sensing/control/sensing/loc_candidates.py src/runtime/sensing/test/loc_world.py src/runtime/sensing/test/test_loc_candidates.py src/runtime/sensing/logs.md src/runtime/sensing/index.md
git commit -F - <<'EOF'
feat(localization): list every pose hypothesis, mirror included (D-395)

Global candidates no longer refuse on a symmetric map; slot candidates
take the square's axis and axis+180 and let the scan pick the heading.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 3: Unmapped lidar objects

**Files:**
- Create: `src/runtime/sensing/control/sensing/loc_objects.py`
- Test: `src/runtime/sensing/test/test_loc_objects.py`

- [ ] **Step 1: Write the failing test**

```python
"""D-395 §4.2: returns the map does not explain become objects in base_link."""
import math

import pytest

from control.sensing.loc_candidates import sensor_from_base
from control.sensing.loc_objects import unmapped_objects
from loc_world import MOUNT, field, mirror, scan


def to_base(pose, point):
    c, s = math.cos(pose[2]), math.sin(pose[2])
    dx, dy = point[0] - pose[0], point[1] - pose[1]
    return (c * dx + s * dy, -s * dx + c * dy)


def test_an_empty_track_has_no_unmapped_objects():
    pose = (-.9, -.509, 0.)
    ranges, angles = scan(pose)
    assert unmapped_objects(field(), sensor_from_base(pose, MOUNT), ranges, angles, MOUNT) == []


def test_another_robot_is_one_object_near_its_true_offset():
    pose, peer = (-.9, -.509, 0.), (-1.26, .49)
    ranges, angles = scan(pose, peers=[peer])
    found = unmapped_objects(field(), sensor_from_base(pose, MOUNT), ranges, angles, MOUNT)
    assert len(found) == 1
    assert math.dist(found[0], to_base(pose, peer)) < .08


def test_the_mirror_hypothesis_sees_the_same_objects():
    pose, peer = (-.9, -.509, 0.), (-1.26, .49)
    ranges, angles = scan(pose, peers=[peer])
    true = unmapped_objects(field(), sensor_from_base(pose, MOUNT), ranges, angles, MOUNT)
    mirrored = unmapped_objects(field(), sensor_from_base(mirror(pose), MOUNT), ranges, angles, MOUNT)
    assert mirrored == pytest.approx(true, abs=1e-6)
```

- [ ] **Step 2: Run it and see it fail**

```bash
python -m pytest src/runtime/sensing/test/test_loc_objects.py -q
```

Expected: `ModuleNotFoundError: No module named 'control.sensing.loc_objects'`.

- [ ] **Step 3: Implement**

Create `src/runtime/sensing/control/sensing/loc_objects.py`:

```python
"""Subject: lidar returns the map does not explain, grouped into objects (D-395 §4.2).

Another robot is the commonest unmapped object on the track. The Fleet arbiter
projects each object through every pose hypothesis and asks which one puts it on
a robot that is already LOCALIZED. Returns are judged at one candidate pose: on
a symmetric map the mirror explains exactly the same returns, so the list does
not depend on which hypothesis is used. Output is base_link (forward, left), m.
"""
from __future__ import annotations

import math

import numpy as np

from .localization import valid_beams

#: Neighbouring unexplained returns farther apart than this start a new object.
#: A Pinky is ~0.12 m across; two robots side by side are farther apart than 6 cm.
GAP_M = .06
MIN_POINTS = 2
MAX_OBJECTS = 16


def unmapped_objects(field, sensor_pose, ranges, angles, mount, gap_m=GAP_M, min_points=MIN_POINTS):
    """Centroids of unexplained return clusters as base_link (x, y) tuples, at most MAX_OBJECTS."""
    ranges, angles = valid_beams(ranges, angles)
    if not len(ranges):
        return []
    order = np.argsort(angles)
    ranges, angles = ranges[order], angles[order]
    heading = sensor_pose[2] + angles
    wx = sensor_pose[0] + np.cos(heading) * ranges
    wy = sensor_pose[1] + np.sin(heading) * ranges
    ix = np.floor((wx - field.origin[0]) / field.resolution).astype(int)
    iy = np.floor((wy - field.origin[1]) / field.resolution).astype(int)
    h, w = field.near.shape
    inside = (ix >= 0) & (ix < w) & (iy >= 0) & (iy < h)
    unexplained = np.zeros(len(ranges), dtype=bool)
    unexplained[inside] = ~field.near[iy[inside], ix[inside]]
    # Sensor-frame points into base_link through the rotated mount.
    sx, sy = np.cos(angles) * ranges, np.sin(angles) * ranges
    c, s = math.cos(mount.yaw), math.sin(mount.yaw)
    bx, by = mount.x + c * sx - s * sy, mount.y + s * sx + c * sy
    objects, cluster = [], []
    for i in np.flatnonzero(unexplained):
        if cluster and math.hypot(bx[i] - bx[cluster[-1]], by[i] - by[cluster[-1]]) > gap_m:
            objects.append(cluster)
            cluster = []
        cluster.append(i)
    if cluster:
        objects.append(cluster)
    out = [(float(np.mean(bx[c_])), float(np.mean(by[c_]))) for c_ in objects if len(c_) >= min_points]
    return out[:MAX_OBJECTS]
```

- [ ] **Step 4: Run it and see it pass**

```bash
python -m pytest src/runtime/sensing/test/test_loc_objects.py -q
```

Expected: `3 passed`.

- [ ] **Step 5: Log, generate, lint**

Append to `src/runtime/sensing/logs.md`:

```markdown
## 2026-10-01 · uncommitted · feat(localization): 지도에 없는 LiDAR 물체를 base_link 물체로 묶음 (D-395 4.2절)
- 변경: `sensing/loc_objects.py` `unmapped_objects` — 지도 벽(`near`)으로 설명되지 않는 반환을 6 cm 간격으로 묶어 중심을 base_link (앞, 왼쪽)으로 낸다. 대칭 맵에서는 거울 가설도 같은 반환을 설명하므로 목록은 가설과 무관하다.
- 증거: `test_loc_objects.py` 3 passed(빈 트랙 0개, 다른 로봇 1개·8 cm 안, 거울 가설에서 같은 목록).
- gate 변화: 없음(SOURCE/LOCAL).
```

```bash
python tools/harness/rosy_harness.py generate
python tools/harness/rosy_harness.py lint
```

Expected: `0 error(s)`.

- [ ] **Step 6: Commit**

```bash
git add src/runtime/sensing/control/sensing/loc_objects.py src/runtime/sensing/test/test_loc_objects.py src/runtime/sensing/logs.md src/runtime/sensing/index.md
git commit -F - <<'EOF'
feat(localization): group unexplained lidar returns into base_link objects (D-395)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 4: The 3 s post-injection check

**Files:**
- Create: `src/runtime/sensing/control/sensing/loc_verify.py`
- Test: `src/runtime/sensing/test/test_loc_verify.py`

- [ ] **Step 1: Write the failing test**

```python
"""D-395 §7: an injected pose is LOCALIZED only after 3 s of good scan fit."""
from control.sensing.loc_verify import FAILED, PASSED, PENDING, InjectionCheck


def run(check, samples):
    result = PENDING
    for now, fit in samples:
        result = check.observe(now, fit)
    return result


def test_good_fit_for_settle_plus_hold_passes():
    check = InjectionCheck(10.)
    assert run(check, [(10. + .25 * k, .95) for k in range(1, 14)]) == PENDING   # up to 13.25 s
    assert check.observe(13.5, .95) == PASSED


def test_low_fit_during_settle_is_forgiven():
    check = InjectionCheck(0.)
    assert run(check, [(.25, .2)] + [(.25 * k, .95) for k in range(2, 15)]) == PASSED


def test_one_low_fit_after_settle_fails_with_a_reason():
    check = InjectionCheck(0.)
    assert run(check, [(.25 * k, .95) for k in range(1, 6)] + [(1.5, .5)]) == FAILED
    assert check.reason == 'fit_low'
    assert check.observe(5., .99) == FAILED      # a result is final


def test_a_scan_gap_fails_as_stale():
    check = InjectionCheck(0.)
    assert check.observe(.25, .95) == PENDING
    assert check.observe(.8, None) == FAILED
    assert check.reason == 'stale_scan'


def test_nan_fit_counts_as_no_scan():
    check = InjectionCheck(0.)
    assert check.observe(.2, float('nan')) == PENDING
    assert check.observe(.6, float('nan')) == FAILED
```

- [ ] **Step 2: Run it and see it fail**

```bash
python -m pytest src/runtime/sensing/test/test_loc_verify.py -q
```

Expected: `ModuleNotFoundError: No module named 'control.sensing.loc_verify'`.

- [ ] **Step 3: Implement**

Create `src/runtime/sensing/control/sensing/loc_verify.py`:

```python
"""Subject: the 3 s scan/map check after every pose injection (D-395 §7).

Every injected pose, whatever its source (candidate, overhead, homing_ref,
human), must earn LOCALIZED the same way: after a settle time for AMCL, the
scan/map fit stays at or above `min_fit` on fresh scans for `hold_s`. One low
fit or a scan gap fails it at once, because a held-but-wrong pose is the
dangerous outcome and a retry is cheap.

Limit: on a 180-degree symmetric map the mirror fits exactly as well as the
truth, so this check cannot reject a mirror injection. Arbitration must.
"""
from __future__ import annotations

import math

PENDING, PASSED, FAILED = 'pending', 'passed', 'failed'


class InjectionCheck:
    def __init__(self, started_s, hold_s=3., settle_s=.5, min_fit=.85, max_gap_s=.5):
        self.started_s = float(started_s)
        self.hold_s, self.settle_s = float(hold_s), float(settle_s)
        self.min_fit, self.max_gap_s = float(min_fit), float(max_gap_s)
        self.last_s = self.started_s
        self.result, self.reason = PENDING, None

    def observe(self, now_s, fit=None):
        """Feed one fresh-scan fit (or None for a tick without a scan); returns the result."""
        if self.result != PENDING:
            return self.result
        if fit is not None and math.isfinite(fit):
            if now_s >= self.started_s + self.settle_s and fit < self.min_fit:
                return self._fail('fit_low')
            self.last_s = now_s
        elif now_s - self.last_s > self.max_gap_s:
            return self._fail('stale_scan')
        if self.last_s >= self.started_s + self.settle_s + self.hold_s:
            self.result = PASSED
        return self.result

    def _fail(self, reason):
        self.result, self.reason = FAILED, reason
        return self.result
```

- [ ] **Step 4: Run it and see it pass**

```bash
python -m pytest src/runtime/sensing/test/test_loc_verify.py -q
```

Expected: `5 passed`.

- [ ] **Step 5: Log, generate, lint**

Append to `src/runtime/sensing/logs.md`:

```markdown
## 2026-10-01 · uncommitted · feat(localization): 주입 뒤 3 s 스캔/지도 검증 (D-395 7항)
- 변경: `sensing/loc_verify.py` `InjectionCheck` — 0.5 s 안정 뒤 새 스캔마다 적합도 ≥ 0.85가 3 s 유지되면 통과, 한 번이라도 낮거나 스캔이 0.5 s 끊기면 즉시 실패(`fit_low`/`stale_scan`). 출처와 무관하게 같은 관문이다. 한계: 대칭 맵에서는 거울상도 같은 적합도라 이 검증이 거울 주입을 못 거른다(문서화).
- 증거: `test_loc_verify.py` 5 passed.
- gate 변화: 없음(SOURCE/LOCAL).
```

```bash
python tools/harness/rosy_harness.py generate
python tools/harness/rosy_harness.py lint
```

- [ ] **Step 6: Commit**

```bash
git add src/runtime/sensing/control/sensing/loc_verify.py src/runtime/sensing/test/test_loc_verify.py src/runtime/sensing/logs.md src/runtime/sensing/index.md
git commit -F - <<'EOF'
feat(localization): hold-for-3-s scan/map check after every injection (D-395)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 5: The localization state machine

**Files:**
- Create: `src/runtime/sensing/control/sensing/loc_state.py`
- Test: `src/runtime/sensing/test/test_loc_state.py`

- [ ] **Step 1: Write the failing test**

```python
"""D-395 §5: UNKNOWN -> CANDIDATES -> (decision + 3 s check) -> LOCALIZED; SUSPECT on doubt."""
import itertools
import math

import pytest

from control.sensing.loc_candidates import PoseCandidate
from control.sensing.loc_state import LocalizationStateMachine, LocState

TRUE = PoseCandidate(-1.26, .49, -math.pi / 2, .99, "slot:A")
MIRROR = PoseCandidate(1.26, -.49, math.pi / 2, .99, "global")


def machine():
    ids = (f"r1-{n}" for n in itertools.count(1))
    return LocalizationStateMachine(lambda: next(ids))


def feed(m, start, end, fit, dt=.25):
    step, t = None, start
    while t <= end + 1e-9:
        step = m.observe_fit(t, fit)
        t += dt
    return step


def localized():
    m = machine()
    m.offer([TRUE, MIRROR], 0.)
    m.decide("r1-1", 1., candidate_index=0, expires_at=5.)
    feed(m, 1.25, 4.5, .95)
    assert m.state is LocState.LOCALIZED
    return m


def test_power_on_is_unknown_and_blocks_autonomy():
    m = machine()
    assert m.state is LocState.UNKNOWN and not m.autonomy_allowed


def test_candidates_get_a_request_id_and_ask_to_be_reported():
    m = machine()
    step = m.offer([TRUE, MIRROR], 0.)
    assert (step.state, step.actions, m.request_id) == (LocState.CANDIDATES, ("report_candidates",), "r1-1")
    assert m.offer([], 1.).reason == "no_candidates"


def test_a_decision_injects_then_three_good_seconds_localize_and_cancel_the_nav_goal():
    m = machine()
    m.offer([TRUE, MIRROR], 0.)
    step = m.decide("r1-1", 1., candidate_index=0, expires_at=5.)
    assert step.actions == ("inject_pose",) and step.pose == (TRUE.x, TRUE.y, TRUE.yaw)
    assert feed(m, 1.25, 4.25, .95).state is LocState.CANDIDATES
    step = m.observe_fit(4.5, .95)
    assert step.state is LocState.LOCALIZED and step.actions == ("cancel_nav_goal", "report_status")
    assert m.autonomy_allowed


@pytest.mark.parametrize("request_id, kwargs, reason", [
    ("r1-0", dict(candidate_index=0, expires_at=5.), "stale_request"),
    ("r1-1", dict(candidate_index=0, expires_at=.5), "expired"),
    ("r1-1", dict(candidate_index=2, expires_at=5.), "bad_index"),
    ("r1-1", dict(expires_at=5.), "ambiguous_decision"),
    ("r1-1", dict(candidate_index=0, pose=(0., 0., 0.)), "ambiguous_decision"),
    ("r1-1", dict(pose=(math.nan, 0., 0.)), "bad_pose"),
])
def test_bad_decisions_are_rejected_and_change_nothing(request_id, kwargs, reason):
    m = machine()
    m.offer([TRUE, MIRROR], 0.)
    step = m.decide(request_id, 1., **kwargs)
    assert (step.actions, step.reason, step.state) == (("reject_decision",), reason, LocState.CANDIDATES)
    assert m.check is None


def test_a_second_decision_while_checking_is_busy():
    m = machine()
    m.offer([TRUE, MIRROR], 0.)
    m.decide("r1-1", 1., candidate_index=0)
    assert m.decide("r1-1", 1.1, candidate_index=1).reason == "busy"


def test_a_direct_pose_is_checked_like_a_candidate():
    m = machine()
    m.offer([TRUE, MIRROR], 0.)
    step = m.decide("r1-1", 1., pose=(-1.2, .5, -1.5), source="homing_ref")
    assert step.pose == (-1.2, .5, -1.5) and m.source == "homing_ref"


def test_a_failed_check_is_suspect_inject_rejected_and_old_ids_die():
    m = machine()
    m.offer([TRUE, MIRROR], 0.)
    m.decide("r1-1", 1., candidate_index=1)
    step = feed(m, 1.25, 1.5, .4)   # settle ends at 1.5 s; the first low fit after it fails
    assert (step.state, step.reason) == (LocState.SUSPECT, "inject_rejected")
    assert m.decide("r1-1", 2.5, candidate_index=0).reason == "stale_request"
    assert m.offer([TRUE], 3.).state is LocState.CANDIDATES and m.request_id == "r1-2"


def test_pickup_while_localized_is_suspect_and_flags_the_report():
    m = localized()
    step = m.picked_up(10.)
    assert (step.state, step.reason, m.pickup) == (LocState.SUSPECT, "pickup", True)
    assert not m.autonomy_allowed


def test_a_sustained_fit_drop_is_suspect_but_a_blip_is_not():
    m = localized()
    assert m.observe_fit(10., .5).state is LocState.LOCALIZED
    assert m.observe_fit(10.25, .95).state is LocState.LOCALIZED
    feed(m, 11., 11.75, .5)
    step = m.observe_fit(12., .5)
    assert (step.state, step.reason) == (LocState.SUSPECT, "fit_drop")


def test_fleet_can_mark_a_localized_robot_suspect_and_candidates_are_ignored_while_localized():
    m = localized()
    assert m.offer([MIRROR], 10.).state is LocState.LOCALIZED
    assert m.mark_suspect("fleet_monitor").reason == "fleet_monitor"
    assert m.mark_suspect("again").reason is None   # only from LOCALIZED
```

- [ ] **Step 2: Run it and see it fail**

```bash
python -m pytest src/runtime/sensing/test/test_loc_state.py -q
```

Expected: `ModuleNotFoundError: No module named 'control.sensing.loc_state'`.

- [ ] **Step 3: Implement**

Create `src/runtime/sensing/control/sensing/loc_state.py`:

```python
"""Subject: the robot-owned localization state, UNKNOWN/CANDIDATES/LOCALIZED/SUSPECT (D-395 §5).

Power-on is always UNKNOWN: Nav2's `set_initial_pose` (0, 0, 0) is not evidence.
Candidates move UNKNOWN or SUSPECT to CANDIDATES under a fresh request id. A
decision must name that id, be unexpired, and then pass `InjectionCheck`;
only then is the robot LOCALIZED, and any running Nav2 goal is cancelled and
replanned. A failed check, a pickup, a sustained fit drop, or Fleet's monitor
send it to SUSPECT with a reason. Autonomy runs in LOCALIZED only; teleop,
check manoeuvres and homing are the caller's to allow in the other states.

Pure logic: the node feeds time, fits and events and executes `Step.actions`.
"""
from __future__ import annotations

import enum
import math
from dataclasses import dataclass

from .loc_verify import FAILED, PASSED, InjectionCheck


class LocState(str, enum.Enum):
    UNKNOWN = 'UNKNOWN'
    CANDIDATES = 'CANDIDATES'
    LOCALIZED = 'LOCALIZED'
    SUSPECT = 'SUSPECT'


@dataclass(frozen=True)
class Step:
    """What changed and what the node must do: 'report_candidates', 'inject_pose',
    'reject_decision', 'cancel_nav_goal', 'report_status'."""
    state: LocState
    actions: tuple = ()
    reason: str | None = None
    pose: tuple | None = None


class LocalizationStateMachine:
    def __init__(self, new_request_id, hold_s=3., settle_s=.5, min_fit=.85, fit_drop_s=1.):
        self._new_id = new_request_id
        self._check_args = dict(hold_s=hold_s, settle_s=settle_s, min_fit=min_fit)
        self.min_fit, self.fit_drop_s = float(min_fit), float(fit_drop_s)
        self.state, self.reason = LocState.UNKNOWN, None
        self.request_id, self.candidates = None, ()
        self.check, self.pose, self.source = None, None, None
        self.pickup = False
        self._low_since = None

    @property
    def autonomy_allowed(self):
        return self.state is LocState.LOCALIZED

    def offer(self, candidates, now_s):
        """New candidates from the global/slot search; ignored while LOCALIZED."""
        if self.state is LocState.LOCALIZED:
            return Step(self.state)
        if not candidates:
            return Step(self.state, reason='no_candidates')
        self.request_id, self.candidates = self._new_id(), tuple(candidates)
        self.check, self.state = None, LocState.CANDIDATES
        return Step(self.state, ('report_candidates',))

    def decide(self, request_id, now_s, candidate_index=None, pose=None, source='candidate',
               expires_at=None):
        """A Fleet (or human) decision: a candidate index or a direct (x, y, yaw)."""
        if self.state is LocState.LOCALIZED:
            return self._reject('already_localized')
        if request_id != self.request_id:
            return self._reject('stale_request')
        if expires_at is not None and not now_s <= expires_at:
            return self._reject('expired')
        if self.check is not None:
            return self._reject('busy')
        if (candidate_index is None) == (pose is None):
            return self._reject('ambiguous_decision')
        if candidate_index is not None:
            if not 0 <= candidate_index < len(self.candidates):
                return self._reject('bad_index')
            c = self.candidates[candidate_index]
            pose = (c.x, c.y, c.yaw)
        if not all(math.isfinite(v) for v in pose):
            return self._reject('bad_pose')
        self.pose, self.source = tuple(float(v) for v in pose), source
        self.check = InjectionCheck(now_s, **self._check_args)
        return Step(self.state, ('inject_pose',), pose=self.pose)

    def observe_fit(self, now_s, fit):
        """One fresh scan/map fit at the current AMCL pose (None: a tick without a scan)."""
        if self.check is not None:
            result = self.check.observe(now_s, fit)
            if result == PASSED:
                self.state, self.reason, self.check = LocState.LOCALIZED, None, None
                self.pickup, self._low_since = False, None
                return Step(self.state, ('cancel_nav_goal', 'report_status'))
            if result == FAILED:
                return self._suspect('inject_rejected')
            return Step(self.state)
        if self.state is LocState.LOCALIZED and fit is not None:
            if fit >= self.min_fit:
                self._low_since = None
            elif self._low_since is None:
                self._low_since = now_s
            elif now_s - self._low_since >= self.fit_drop_s:
                return self._suspect('fit_drop')
        return Step(self.state)

    def picked_up(self, now_s):
        """Wheel slip or IMU tilt: the last good pose is no longer a cue."""
        self.pickup = True
        if self.state in (LocState.LOCALIZED, LocState.CANDIDATES):
            return self._suspect('pickup')
        return Step(self.state)

    def mark_suspect(self, reason):
        """Fleet's monitor saw this robot elsewhere (D-395 §9)."""
        if self.state is LocState.LOCALIZED:
            return self._suspect(reason)
        return Step(self.state)

    def _suspect(self, reason):
        self.state, self.reason = LocState.SUSPECT, reason
        self.check, self.request_id, self._low_since = None, None, None
        return Step(self.state, ('report_status',), reason=reason)

    def _reject(self, reason):
        return Step(self.state, ('reject_decision',), reason=reason)
```

- [ ] **Step 4: Run it and see it pass**

```bash
python -m pytest src/runtime/sensing/test/test_loc_state.py -q
```

Expected: `15 passed`.

- [ ] **Step 5: Log, generate, lint**

Append to `src/runtime/sensing/logs.md`:

```markdown
## 2026-10-01 · uncommitted · feat(localization): UNKNOWN/CANDIDATES/LOCALIZED/SUSPECT 상태 기계 (D-395 5절)
- 변경: `sensing/loc_state.py` `LocalizationStateMachine` — 전원 투입은 항상 UNKNOWN, 후보가 오면 새 request_id로 CANDIDATES, 결정은 같은 id·만료 전·후보 인덱스 또는 직접 좌표 하나만 받고 `InjectionCheck` 통과 시 LOCALIZED(`cancel_nav_goal` 동작), 검증 실패(`inject_rejected`)·픽업·적합도 1 s 지속 하락(`fit_drop`)·Fleet 감시는 SUSPECT. 자율 주행 허용은 LOCALIZED만. 설계 5절 그림의 "검증 실패 → CANDIDATES"는 ADR 7항·9절의 SUSPECT를 따랐다.
- 증거: `test_loc_state.py` 15 passed(낡은 id·만료·잘못된 인덱스·둘 다/둘 다 없음·NaN 자세 거부, 검증 중 busy, 실패 뒤 옛 id 거부).
- gate 변화: 없음(SOURCE/LOCAL).
```

```bash
python tools/harness/rosy_harness.py generate
python tools/harness/rosy_harness.py lint
```

- [ ] **Step 6: Commit**

```bash
git add src/runtime/sensing/control/sensing/loc_state.py src/runtime/sensing/test/test_loc_state.py src/runtime/sensing/logs.md src/runtime/sensing/index.md
git commit -F - <<'EOF'
feat(localization): robot-owned UNKNOWN/CANDIDATES/LOCALIZED/SUSPECT machine (D-395)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 6: Paint score per hypothesis

The walls are symmetric; the paint is not (measured on map_v2_fleet: truth ≈ 1.0, mirror < 0.05 at six poses). This is the cue that resolves a lone robot with a camera.

**Files:**
- Create: `src/runtime/sensing/control/sensing/perception/paint_hypothesis.py`
- Test: `src/runtime/sensing/test/test_paint_hypothesis.py`

- [ ] **Step 1: Write the failing test**

```python
"""D-395 §7: paint separates a pose from its 180-degree mirror on map_v2_fleet."""
import math

import pytest

from control.sensing.perception.paint_hypothesis import paint_score
from loc_world import mirror, paint_map, paint_points

POSES = [(-1.26, .49, math.pi / 2), (-1.26, .49, -math.pi / 2), (.86, -.52, 0.),
         (.86, -.52, math.pi), (0., .51, 0.), (-.9, -.509, 0.)]


@pytest.mark.parametrize("pose", POSES)
def test_the_true_pose_explains_the_paint_and_the_mirror_does_not(pose):
    points = paint_points(pose)
    assert paint_score(paint_map(), points, pose) > .9
    assert paint_score(paint_map(), points, mirror(pose)) < .1


def test_too_few_or_non_finite_points_are_no_evidence():
    assert paint_score(paint_map(), [(.2, 0.)] * 9, (0., 0., 0.)) is None
    assert paint_score(paint_map(), [(math.nan, 0.)] * 20, (0., 0., 0.)) is None
    assert paint_score(paint_map(), [(.2, 0.)] * 20, (math.nan, 0., 0.)) is None
```

- [ ] **Step 2: Run it and see it fail**

```bash
python -m pytest src/runtime/sensing/test/test_paint_hypothesis.py -q
```

Expected: `ModuleNotFoundError: No module named 'control.sensing.perception.paint_hypothesis'`.

- [ ] **Step 3: Implement**

Create `src/runtime/sensing/control/sensing/perception/paint_hypothesis.py`:

```python
"""Subject: how well one pose hypothesis explains the paint the camera sees (D-395 §7, D-375).

The track walls are 180-degree symmetric; the floor paint is not. Placing the
camera's paint points on the map from a hypothesis and measuring how far they
land from real paint separates a pose from its mirror (measured on
map_v2_fleet: about 1.0 for the truth, under 0.05 for the mirror). Same
distance score as the paint particle filter, so the two never disagree on
what "on paint" means.
"""
from __future__ import annotations

import math

import numpy as np

from .paint_localizer import MATCH_SCALE_M, MATCH_TRUNCATE_M

#: Fewer paint points than this is no evidence either way (None, not 0).
MIN_POINTS = 10


def paint_score(paint_map, points, pose):
    """exp(-mean capped distance / scale) for base_link (forward, left) paint points at `pose`; None if too few."""
    points = np.asarray(points, dtype=float).reshape(-1, 2)
    points = points[np.all(np.isfinite(points), axis=1)]
    if len(points) < MIN_POINTS or not all(math.isfinite(v) for v in pose):
        return None
    c, s = math.cos(pose[2]), math.sin(pose[2])
    on_map = np.column_stack((pose[0] + c * points[:, 0] - s * points[:, 1],
                              pose[1] + s * points[:, 0] + c * points[:, 1]))
    distance = np.minimum(paint_map.distance_at(on_map), MATCH_TRUNCATE_M)
    return float(math.exp(-float(np.mean(distance)) / MATCH_SCALE_M))
```

- [ ] **Step 4: Run it and see it pass**

```bash
python -m pytest src/runtime/sensing/test/test_paint_hypothesis.py src/runtime/sensing/test/test_perception_folder.py -q
```

Expected: `9 passed` (7 new, 2 folder guards: no rclpy, no `cmd_vel` in perception).

- [ ] **Step 5: Log, generate, lint**

Append to `src/runtime/sensing/logs.md`:

```markdown
## 2026-10-01 · uncommitted · feat(perception): 가설 자세별 페인트 점수 (D-395 7절, D-375)
- 변경: `sensing/perception/paint_hypothesis.py` `paint_score` — 카메라의 바닥 페인트 점(base_link)을 가설 자세로 지도에 놓고 페인트 입자 필터와 같은 거리 점수(exp(−평균 거리/5 mm), 3 cm 상한)를 낸다. 점이 10개 미만이면 None(증거 없음).
- 증거: `test_paint_hypothesis.py` 7 passed — map_v2_fleet 여섯 자세에서 참 > 0.9, 거울 < 0.1.
- gate 변화: 없음(SOURCE/LOCAL). 실제 카메라 차선 마스크 연결은 2단계.
```

```bash
python tools/harness/rosy_harness.py generate
python tools/harness/rosy_harness.py lint
```

- [ ] **Step 6: Commit**

```bash
git add src/runtime/sensing/control/sensing/perception/paint_hypothesis.py src/runtime/sensing/test/test_paint_hypothesis.py src/runtime/sensing/logs.md src/runtime/sensing/index.md
git commit -F - <<'EOF'
feat(perception): paint agreement per pose hypothesis separates the mirror (D-395)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 7: Reference-square detector (pluggable backend)

**Files:**
- Create: `src/runtime/sensing/control/sensing/perception/reference_square.py`
- Test: `src/runtime/sensing/test/test_reference_square.py`
- Modify: `src/runtime/sensing/control/sensing/AGENTS.md`, `src/runtime/sensing/control/sensing/perception/AGENTS.md`

- [ ] **Step 1: Write the failing test**

The images are synthetic (our renderer and our detector share one belief, see `docs/solutions/workflow-issues/a-fixture-from-the-same-model-is-one-belief-not-two.md`); real-camera evidence is a Phase 2 item (P2-8).

```python
"""D-395 rev. 1 §6: the HSV reference-square detector on synthetic floor images."""
import math

import numpy as np
import pytest

from control.sensing.perception.camera_ground import GroundPlane, focal_from_hfov
from control.sensing.perception.reference_square import (
    HsvSquareDetector, SquareDetector, SquareObservation)

W, H = 320, 180
CAM_X = .034
#: Real Pinky camera is near-horizontal (pitch ~11.8 deg, height ~0.059 m, 2026-10-01 fit).
GROUND = GroundPlane(height_m=.059, pitch_rad=math.radians(11.8), focal_px=focal_from_hfov(W, 1.1519),
                     principal_x=W / 2, principal_y=H / 2, max_range_m=.8)
CARPET, WALL, WHITE = (100, 104, 108), (185, 185, 185), (235, 235, 235)
RED, BLUE = (40, 40, 200), (200, 70, 30)   # BGR


def floor_grid():
    """Base_link (forward, left) of every pixel's floor point; NaN above the horizon."""
    fwd, left = np.full((H, W), np.nan), np.full((H, W), np.nan)
    for r in range(H):
        d = GROUND.distance(r)
        if d is not None:
            fwd[r] = d + CAM_X
            left[r] = [-GROUND.lateral(c, r) for c in range(W)]
    return fwd, left


FWD, LEFT = floor_grid()


def render(squares=(), lines=(), ring=RED, core=BLUE):
    """Carpet floor, wall above the horizon, axis-aligned squares (centre, outer, core sizes)."""
    img = np.empty((H, W, 3), np.uint8)
    img[:] = CARPET
    img[np.isnan(FWD)] = WALL
    for (cx, cy), outer, inner in squares:
        dx, dy = np.abs(FWD - cx), np.abs(LEFT - cy)
        img[(dx <= outer[0] / 2) & (dy <= outer[1] / 2)] = ring
        img[(dx <= inner[0] / 2) & (dy <= inner[1] / 2)] = core
    for left in lines:
        img[np.abs(LEFT - left) <= .0125] = WHITE
    return img


SQUARE_B = ((.13, .14), (.08, .09))


def test_the_detector_satisfies_the_backend_contract():
    assert isinstance(HsvSquareDetector(CAM_X), SquareDetector)


@pytest.mark.parametrize("centre", [(.30, 0.), (.30, .06), (.45, -.08), (.60, .05)])
def test_a_square_ahead_gives_its_bearing_and_range(centre):
    found = HsvSquareDetector(CAM_X).detect(render([(centre, *SQUARE_B)]), GROUND)
    assert len(found) == 1
    obs = found[0]
    assert obs.bearing_rad == pytest.approx(math.atan2(centre[1], centre[0]), abs=math.radians(3))
    assert obs.range_m == pytest.approx(math.hypot(*centre), abs=.03)
    assert obs.confidence > .6


@pytest.mark.parametrize("image", [
    render(),                                                  # bare carpet
    render(lines=(.09, -.09)),                                 # white lane paint
    render([((.3, 0.), *SQUARE_B)], ring=CARPET),              # blue patch without a ring
    render([((.3, 0.), *SQUARE_B)], core=RED),                 # red patch without a core
])
def test_carpet_paint_and_half_squares_are_not_squares(image):
    assert HsvSquareDetector(CAM_X).detect(image, GROUND) == []


def test_no_ground_plane_means_no_observation():
    assert HsvSquareDetector(CAM_X).detect(render([((.3, 0.), *SQUARE_B)]), None) == []


def test_beyond_trusted_range_keeps_the_bearing_without_a_range():
    near = GroundPlane(height_m=.059, pitch_rad=math.radians(11.8), focal_px=GROUND.focal_px,
                       principal_x=W / 2, principal_y=H / 2, max_range_m=.2)
    found = HsvSquareDetector(CAM_X).detect(render([((.45, .05), *SQUARE_B)]), near)
    assert len(found) == 1 and found[0].range_m is None
    assert found[0].bearing_rad > 0
    assert isinstance(found[0], SquareObservation)
```

- [ ] **Step 2: Run it and see it fail**

```bash
python -m pytest src/runtime/sensing/test/test_reference_square.py -q
```

Expected: `ModuleNotFoundError: No module named 'control.sensing.perception.reference_square'`.

- [ ] **Step 3: Implement**

Create `src/runtime/sensing/control/sensing/perception/reference_square.py`:

```python
"""Subject: the floor reference square (red ring, blue core) seen by the front camera (D-395 rev. 1 §6).

Fixed output contract, swappable backend: every detector returns
`SquareObservation(bearing_rad, range_m, confidence)` in base_link (bearing
left-positive from the nose, range from base_link, confidence 0..1), best first.
`HsvSquareDetector` is the rule-based backend; a learned `reference_square`
class (proposed for the D-379 label spec) can replace it behind the same
`detect(bgr, ground)` call.

Range comes from the ground plane at the blue core's centroid (the square is
flat on the floor, so the centroid is a floor point). Without a ground plane
there is no honest range or bearing, so nothing is returned; beyond the plane's
trusted range the bearing is kept and the range is None.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import cv2
import numpy as np

#: OpenCV HSV (H 0..180). Blue core and red ring; S/V floors reject grey carpet
#: and white paint, which have almost no saturation.
BLUE = ((100, 120, 50), (130, 255, 255))
RED_LOW = ((0, 120, 70), (10, 255, 255))
RED_HIGH = ((170, 120, 70), (180, 255, 255))
#: The ring is 0.03 m wide around a 0.07-0.08 m core, so a box grown by 60% of
#: the core on each side holds the whole ring. Seen by the near-horizontal
#: camera the ring rows are foreshortened and red fills ~0.35-0.55 of that box
#: (synthetic 0.3-0.6 m); 0.35 counts as full confidence, under 0.2 is no ring.
RING_GROW = .6
RING_FULL = .35


@dataclass(frozen=True)
class SquareObservation:
    bearing_rad: float
    range_m: float | None
    confidence: float


@runtime_checkable
class SquareDetector(Protocol):
    def detect(self, bgr: np.ndarray, ground) -> list[SquareObservation]: ...


class HsvSquareDetector:
    def __init__(self, camera_x_offset_m, min_core_px=30, min_ring=.2):
        self.camera_x_offset_m = float(camera_x_offset_m)
        self.min_core_px, self.min_ring = int(min_core_px), float(min_ring)

    def detect(self, bgr, ground):
        if ground is None or bgr is None or bgr.ndim != 3:
            return []
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        blue = cv2.inRange(hsv, *BLUE)
        red = cv2.inRange(hsv, *RED_LOW) | cv2.inRange(hsv, *RED_HIGH)
        count, _, stats, centroids = cv2.connectedComponentsWithStats(blue)
        height, width = blue.shape
        found = []
        for i in range(1, count):
            x, y, w, h, area = stats[i]
            if area < self.min_core_px:
                continue
            gx, gy = max(1, round(w * RING_GROW)), max(1, round(h * RING_GROW))
            x0, y0 = max(0, x - gx), max(0, y - gy)
            x1, y1 = min(width, x + w + gx), min(height, y + h + gy)
            ring = np.ones((y1 - y0, x1 - x0), dtype=bool)
            ring[y - y0:y - y0 + h, x - x0:x - x0 + w] = False
            ratio = float(np.mean(red[y0:y1, x0:x1][ring] > 0)) if ring.any() else 0.
            if ratio < self.min_ring:
                continue
            found.append(self._observe(ground, *centroids[i], min(1., ratio / RING_FULL)))
        return sorted((f for f in found if f is not None), key=lambda f: -f.confidence)

    def _observe(self, ground, column, row, confidence):
        ahead = ground.distance(row)
        if ahead is None:
            bearing = -math.atan2(column - ground.principal_x, ground.focal_px)
            return SquareObservation(bearing, None, round(confidence, 3))
        forward = ahead + self.camera_x_offset_m
        left = -ground.lateral(column, row)
        return SquareObservation(math.atan2(left, forward), math.hypot(forward, left), round(confidence, 3))
```

- [ ] **Step 4: Run it and see it pass**

```bash
python -m pytest src/runtime/sensing/test/test_reference_square.py src/runtime/sensing/test/test_perception_folder.py -q
```

Expected: `13 passed`.

- [ ] **Step 5: Add the key-file rows**

In `src/runtime/sensing/control/sensing/AGENTS.md`, after the row that starts with ``| `dock_observer.py` |``, add:

```markdown
| `loc_candidates.py` | D-395 pose hypotheses: `global_candidates` (every distinct pose, mirror included), `slot_candidates` (reference square axis and axis+180), `merge`; base/sensor transforms through `Mount` |
| `loc_objects.py` | D-395 `unmapped_objects`: unexplained lidar returns as base_link objects (other robots) |
| `loc_verify.py` | D-395 `InjectionCheck`: 0.5 s settle + 3 s of fit ≥ 0.85; cannot reject a mirror on a symmetric map |
| `loc_state.py` | D-395 `LocalizationStateMachine` UNKNOWN/CANDIDATES/LOCALIZED/SUSPECT; autonomy only when LOCALIZED |
```

In `src/runtime/sensing/control/sensing/perception/AGENTS.md`, after the row that starts with ``| `image_frame.py` |``, add:

```markdown
| `paint_hypothesis.py` | D-395 `paint_score`: how well a pose hypothesis explains the camera's paint points (same distance score as `paint_localizer`) |
| `reference_square.py` | D-395 reference square (red ring, blue core): `SquareObservation(bearing_rad, range_m, confidence)` contract, `SquareDetector` protocol, `HsvSquareDetector` rule backend |
```

- [ ] **Step 6: Log, generate, lint**

Append to `src/runtime/sensing/logs.md`:

```markdown
## 2026-10-01 · uncommitted · feat(perception): 기준 사각형 HSV 검출기, 출력 계약 고정 (D-395 개정 1 6항)
- 변경: `sensing/perception/reference_square.py` — 출력 계약 `SquareObservation(bearing_rad, range_m, confidence)`(base_link, 왼쪽 +), `SquareDetector` 프로토콜, 규칙 백엔드 `HsvSquareDetector`(파란 중심 연결 요소 + 둘레 빨간 고리 비율, 거리는 지면 평면에서 중심 행). 지면 평면이 없으면 결과 없음, 신뢰 거리 밖이면 방위만. 학습 클래스 `reference_square`가 같은 `detect(bgr, ground)` 뒤로 바꿔 들어올 수 있다. sensing·perception AGENTS 표에 D-395 모듈 행 추가.
- 증거: `test_reference_square.py` 11 passed — 합성 영상(카펫·벽·실측에 가까운 11.8° 피치), 0.3–0.6 m에서 방위 3°·거리 3 cm, 카펫·흰 페인트·고리 없는 파랑·중심 없는 빨강은 0개. 합성 영상은 검출기와 같은 믿음이다 — 실제 카메라 가시 거리·조명은 미검증(2단계 P2-8).
- gate 변화: 없음(SOURCE/LOCAL).
```

```bash
python tools/harness/rosy_harness.py generate
python tools/harness/rosy_harness.py lint
```

- [ ] **Step 7: Commit**

```bash
git add src/runtime/sensing/control/sensing/perception/reference_square.py src/runtime/sensing/test/test_reference_square.py src/runtime/sensing/control/sensing/AGENTS.md src/runtime/sensing/control/sensing/perception/AGENTS.md src/runtime/sensing/logs.md src/runtime/sensing/index.md
git commit -F - <<'EOF'
feat(perception): reference-square HSV detector behind a fixed output contract (D-395)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 8: Wire models, the snapshot frame flag, API Ref v1.69

D-18: the schema source and the API Reference change together. PRT-006/API-002: additive only, so the document MINOR moves (v1.68 → v1.69) and the envelope `protocol_version` stays `1.0`. D-347: the MINOR lives in three pins (`docs/solutions/workflow-issues/a-contract-version-bump-is-three-pins-not-one.md`). The models live in their own module, like `sightings.py`; `schemas.py` gains only the import and one optional field because it sits in the zero-growth hard tier.

**Files:**
- Create: `src/contracts/foundation/core_common/protocol/localization.py`
- Modify: `src/contracts/foundation/core_common/protocol/schemas.py` (import + `StateSnapshot.localization`)
- Modify: `docs/reference/ROSY API & Protocol Reference.md` (header, §6.1, §7.9, changelog)
- Modify: `src/runtime/api_web/core_api_web/api/app.py:1,110`, `test/test_line_follow_contract_docs.py:15`
- Modify: `test/architecture/test_module_structure.py` (`schemas.py` verdict)
- Modify: `src/contracts/foundation/core_common/protocol/AGENTS.md`
- Test: `src/contracts/foundation/test/test_localization_contracts.py`

- [ ] **Step 1: Write the failing test**

Create `src/contracts/foundation/test/test_localization_contracts.py` (model tests plus one API Ref check that stays red until Step 6):

```python
"""D-395 §4 wire models: additive, frame-explicit, one decision target."""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from core_common.protocol.localization import (
    CandidateReport, DecisionSource, LocalizationDecision, LocalizationStatus, LocState, PoseFrame)
from core_common.protocol.schemas import StateSnapshot

REFERENCE = Path(__file__).resolve().parents[4] / "docs" / "reference" / "ROSY API & Protocol Reference.md"


def _report(**over):
    doc = {"robot_id": "rosy_01", "request_id": "rosy_01-7",
           "candidates": [{"x": -1.26, "y": .49, "yaw": -1.57, "scan_fit": .99, "paint_score": .97},
                          {"x": 1.26, "y": -.49, "yaw": 1.57, "scan_fit": .99}],
           "unmapped_objects": [{"x": .6, "y": .1}],
           "square_sightings": [{"bearing_rad": .1, "range_m": .3, "confidence": .9}],
           "pickup": False, "stamp": 1760000000.5}
    doc.update(over)
    return doc


def test_a_snapshot_without_localization_is_a_pre_d395_robot():
    snap = StateSnapshot(robot_id="rosy_01")
    assert snap.localization is None
    assert "localization" in snap.model_dump()


def test_a_snapshot_carries_state_and_frame():
    snap = StateSnapshot.model_validate({"robot_id": "rosy_01", "localization": {
        "state": "LOCALIZED", "pose_frame": "map", "confidence": .93, "request_id": "rosy_01-7"}})
    assert snap.localization.state is LocState.LOCALIZED
    assert snap.localization.pose_frame is PoseFrame.MAP
    assert snap.model_dump(mode="json")["localization"]["pose_frame"] == "map"


@pytest.mark.parametrize("bad", [
    {"state": "LOST", "pose_frame": "map"},
    {"state": "UNKNOWN", "pose_frame": "base_link"},
    {"state": "UNKNOWN", "pose_frame": "odom", "confidence": 1.5},
    {"state": "UNKNOWN", "pose_frame": "odom", "request_id": "has space"},
    {"state": "UNKNOWN", "pose_frame": "odom", "extra": 1},
])
def test_status_rejects_unknown_values(bad):
    with pytest.raises(ValidationError):
        LocalizationStatus.model_validate(bad)


def test_a_candidate_report_round_trips():
    report = CandidateReport.model_validate(_report())
    assert report.candidates[1].paint_score is None
    assert CandidateReport.model_validate_json(report.model_dump_json()) == report


@pytest.mark.parametrize("over", [
    {"candidates": []},
    {"candidates": [{"x": 0., "y": 0., "yaw": 0., "scan_fit": .9}] * 9},
    {"candidates": [{"x": math.nan, "y": 0., "yaw": 0., "scan_fit": .9}]},
    {"candidates": [{"x": 0., "y": 0., "yaw": 0., "scan_fit": 1.2}]},
    {"square_sightings": [{"bearing_rad": 0., "range_m": 0., "confidence": .5}]},
    {"stamp": math.inf},
    {"request_id": ""},
])
def test_a_candidate_report_rejects_malformed_fields(over):
    with pytest.raises(ValidationError):
        CandidateReport.model_validate(_report(**over))


def test_a_decision_names_a_candidate_or_a_pose_never_both():
    by_index = LocalizationDecision(request_id="rosy_01-7", candidate_index=0, source="candidate",
                                    expires_at=1760000005.)
    assert by_index.source is DecisionSource.CANDIDATE and by_index.pose is None
    direct = LocalizationDecision(request_id="rosy_01-7", pose={"x": -1.2, "y": .5, "yaw": 0.},
                                  source="homing_ref", expires_at=1760000005.)
    assert direct.pose.x == -1.2
    for bad in ({"candidate_index": 0, "pose": {"x": 0., "y": 0., "yaw": 0.}, "source": "candidate"},
                {"source": "candidate"},
                {"candidate_index": 0, "source": "overhead"},
                {"pose": {"x": 0., "y": 0., "yaw": 0.}, "source": "candidate"},
                {"candidate_index": True, "source": "candidate"},
                {"candidate_index": 8, "source": "candidate"}):
        with pytest.raises(ValidationError):
            LocalizationDecision(request_id="rosy_01-7", expires_at=1.0, **bad)


def test_the_api_reference_documents_the_field_and_the_models():
    text = REFERENCE.read_text(encoding="utf-8")
    assert '"localization": {' in text
    assert "## 7.9 Fleet 보조 위치 확정 모델" in text
    for name in ("CandidateReport", "LocalizationDecision", "square_sightings", "pose_frame"):
        assert name in text
```

- [ ] **Step 2: Run it and see it fail**

```bash
python -m pytest src/contracts/foundation/test/test_localization_contracts.py -q
```

Expected: `ModuleNotFoundError: No module named 'core_common.protocol.localization'`.

- [ ] **Step 3: Implement the models**

Create `src/contracts/foundation/core_common/protocol/localization.py`:

```python
"""Fleet-assisted localization wire models (D-395 §4, API Ref §6.1 and §7.9).

Robot -> Fleet: `LocalizationStatus` on every state snapshot (the frame flag the
pose never had) and a `CandidateReport` when the state changes. Fleet -> robot:
`LocalizationDecision`, a candidate index or a direct pose with its source.
All fields are additive (API-002, PRT-006): an old consumer ignores them, and a
snapshot without `localization` is a robot that predates D-395.
"""

from __future__ import annotations

import enum
import re
from typing import Annotated, Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Finite = Annotated[float, Field(allow_inf_nan=False)]
Unit = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
_REQUEST_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


class LocState(str, enum.Enum):
    UNKNOWN = "UNKNOWN"
    CANDIDATES = "CANDIDATES"
    LOCALIZED = "LOCALIZED"
    SUSPECT = "SUSPECT"


class PoseFrame(str, enum.Enum):
    MAP = "map"
    ODOM = "odom"


class DecisionSource(str, enum.Enum):
    CANDIDATE = "candidate"
    OVERHEAD = "overhead"
    HOMING_REF = "homing_ref"
    HUMAN = "human"


def _request_id(value: str) -> str:
    if not _REQUEST_ID.fullmatch(value):
        raise ValueError("request_id must be 1-64 of [A-Za-z0-9_.:-]")
    return value


class LocalizationStatus(BaseModel):
    """Robot-owned state; `pose_frame` says which frame the snapshot `pose` is in."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: LocState
    pose_frame: PoseFrame
    confidence: Unit = 0.0
    reason: Optional[str] = Field(default=None, max_length=64)
    needs_human: bool = False
    request_id: Optional[str] = None

    @field_validator("request_id")
    @classmethod
    def _id(cls, value: Optional[str]) -> Optional[str]:
        return None if value is None else _request_id(value)


class MapPose(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    x: Finite
    y: Finite
    yaw: Finite


class LocCandidate(MapPose):
    """One base_link pose hypothesis in the map frame (D-395 §4.2)."""

    scan_fit: Unit
    paint_score: Optional[Unit] = None


class RobotPoint(BaseModel):
    """An unmapped lidar object in base_link: forward x, left y, metres."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    x: Finite
    y: Finite


class SquareSighting(BaseModel):
    """Reference-square detector output (D-395 rev. 1 §6), base_link."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    bearing_rad: Finite
    range_m: Optional[Annotated[float, Field(gt=0.0, allow_inf_nan=False)]] = None
    confidence: Unit


class CandidateReport(BaseModel):
    """Robot -> Fleet when the localization state changes (D-395 §4.2)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    robot_id: str = Field(min_length=1, max_length=64)
    request_id: str
    candidates: list[LocCandidate] = Field(min_length=1, max_length=8)
    unmapped_objects: list[RobotPoint] = Field(default_factory=list, max_length=16)
    square_sightings: list[SquareSighting] = Field(default_factory=list, max_length=4)
    pickup: bool = False
    stamp: Finite

    @field_validator("request_id")
    @classmethod
    def _id(cls, value: str) -> str:
        return _request_id(value)


class LocalizationDecision(BaseModel):
    """Fleet -> robot: a candidate index or a direct pose, never both (D-395 §4.3)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str
    candidate_index: Optional[int] = Field(default=None, ge=0, le=7, strict=True)
    pose: Optional[MapPose] = None
    source: DecisionSource
    evidence: dict[str, Any] = Field(default_factory=dict, max_length=16)
    expires_at: Finite

    @field_validator("request_id")
    @classmethod
    def _id(cls, value: str) -> str:
        return _request_id(value)

    @model_validator(mode="after")
    def _one_target(self) -> "LocalizationDecision":
        if (self.candidate_index is None) == (self.pose is None):
            raise ValueError("exactly one of candidate_index and pose")
        if (self.source is DecisionSource.CANDIDATE) != (self.candidate_index is not None):
            raise ValueError("source 'candidate' goes with candidate_index; other sources carry a pose")
        return self
```

- [ ] **Step 4: Add the snapshot field**

In `src/contracts/foundation/core_common/protocol/schemas.py`, after the line `from core_common.protocol.evidence import EvidenceState, ValueEvidence` add:

```python
from core_common.protocol.localization import LocalizationStatus
```

and in `class StateSnapshot`, after the line `    activity: Optional[RobotActivity] = None`, add:

```python
    #: v1.69 additive (D-395): state and pose frame; null from robots before D-395.
    localization: Optional[LocalizationStatus] = None
```

- [ ] **Step 5: Run the model tests (the API Ref test still fails)**

```bash
python -m pytest src/contracts/foundation/test/test_localization_contracts.py -q
```

Expected: `16 passed, 1 failed` — only `test_the_api_reference_documents_the_field_and_the_models` fails.

- [ ] **Step 6: Document v1.69 in the API Reference**

In `docs/reference/ROSY API & Protocol Reference.md`:

1. Header: `**Version:** v1.68` → `**Version:** v1.69`.
2. §6.1: after the line ``GET /api/v1/robot/state` 도 같은 스냅샷이다.`` (line 415) insert a blank line and:

````markdown
`localization` 은 v1.69 additive 다(D-395). D-395 이전 로봇은 `null` 이다.

```json
"localization": {
  "state": "LOCALIZED",
  "pose_frame": "map",
  "confidence": 0.93,
  "reason": null,
  "needs_human": false,
  "request_id": "rosy_01-7"
}
```

- `state`: `UNKNOWN` \| `CANDIDATES` \| `LOCALIZED` \| `SUSPECT`. 로봇이 소유한다. 전원 투입은 항상 `UNKNOWN` 이고 자율 주행은 `LOCALIZED` 에서만 한다.
- `pose_frame`: 같은 스냅샷 `pose` 의 프레임, `map` \| `odom`. Fleet 교통정리·bays 는 `odom` 이거나 `LOCALIZED` 가 아닌 자세를 쓰지 않는다(D-395 10항, 적용은 2단계).
- `confidence`: 스캔/지도 적합도 0–1. `reason`: SUSPECT 사유(`pickup`, `fit_drop`, `inject_rejected`, `fleet_monitor`). `needs_human`: 사다리 시간 초과. `request_id`: 진행 중인 후보 보고의 id.
````

3. §7.9: replace the two lines

```markdown
---

# 8. 이벤트 카탈로그
```

with

````markdown
## 7.9 Fleet 보조 위치 확정 모델 (D-395, v1.69 스키마만)

원천은 `core_common.protocol.localization` 이다. v1.69 는 모델만 고정한다. 전송 경로(설계 문서 4.4절의 `POST /api/v1/localization/decision` 등)와 capability 는 2단계에서 이 절과 §5.3 을 함께 고쳐 연다. 그 전에는 어떤 경로도 이 모델을 받지 않는다.

| 모델 | 방향 | 필드 |
|---|---|---|
| `CandidateReport` | 로봇 → Fleet | `robot_id`, `request_id`(1–64자 `[A-Za-z0-9_.:-]`), `candidates[1..8]` `{x, y, yaw, scan_fit 0–1, paint_score 0–1\|null}`(map 프레임 base_link), `unmapped_objects[≤16]` `{x, y}`(base_link, 앞 x·왼쪽 y), `square_sightings[≤4]` `{bearing_rad, range_m>0\|null, confidence 0–1}`, `pickup`, `stamp`(로봇 시각 s) |
| `LocalizationDecision` | Fleet → 로봇 | `request_id`, `candidate_index`(0–7) **또는** `pose {x, y, yaw}` 중 정확히 하나, `source` `candidate`\|`overhead`\|`homing_ref`\|`human`(`candidate` 는 인덱스와만, 나머지는 `pose` 와만), `evidence`(≤16 키), `expires_at`(s) |

로봇은 낡은 `request_id` 와 만료된 결정을 무시한다. 받아들인 결정도 주입 뒤 3 s 스캔/지도 일치를 통과해야 `LOCALIZED` 가 되고, 실패하면 `SUSPECT`(`inject_rejected`)다. 대칭 맵에서는 거울상도 같은 적합도라 이 검증이 거울 주입을 거르지 못한다 — 거울은 Fleet 중재와 감시가 막는다. `square_sightings` 는 설계 4.2절 표 이후 개정 1의 `square_seen` 단서를 위해 더한 선택 필드다.

---

# 8. 이벤트 카탈로그
````

4. Changelog: directly above the row that starts with `| v1.68 | 2026-10-01 |`, add:

```markdown
| v1.69 | 2026-10-01 | Additive (D-395 1단계, feat/d395-host-localization): 상태 스냅샷(`/robot/state`·`/ws/state`)·하트비트 `localization` `{state, pose_frame, confidence, reason, needs_human, request_id}`(D-395 이전 로봇은 null); §7.9 `CandidateReport`·`LocalizationDecision` 모델(스키마만, 전송 경로 없음). 기존 필드 변화 없음 |
```

- [ ] **Step 7: Move the other two pins**

- `src/runtime/api_web/core_api_web/api/app.py` line 1: `ROSY-API-REF-001 v1.68.` → `ROSY-API-REF-001 v1.69.`; line 110: `ROSY-API-REF-001 (v1.68)` → `ROSY-API-REF-001 (v1.69)`.
- `test/test_line_follow_contract_docs.py` line 15: `"v1.68" in header[0]` → `"v1.69" in header[0]`.

- [ ] **Step 8: Re-judge the `schemas.py` size verdict**

```bash
python -c "import sys; sys.path.insert(0, 'test/architecture'); import test_module_structure as t; print(t._over_budget().get('contracts/foundation/core_common/protocol/schemas.py'))"
```

Expected: `1095` (1092 + 3). In `test/architecture/test_module_structure.py`, in the `"contracts/foundation/core_common/protocol/schemas.py"` entry, change `1_092,` to the printed number (`1_095,`) and replace

```python
on robot state (still accept)",
```

with

```python
on robot state (still accept); re-judged 2026-10-01 at 1095 for the D-395 StateSnapshot.localization field and its import — the models live in protocol/localization.py (still accept)",
```

(use the printed number in both places if it differs).

- [ ] **Step 9: Add the key-file row**

In `src/contracts/foundation/core_common/protocol/AGENTS.md`, after the row that starts with ``| `schemas.py` |``, add:

```markdown
| `localization.py` | D-395 wire models: `LocalizationStatus` (state + `map\|odom` frame flag, on `StateSnapshot.localization`), `CandidateReport`, `LocalizationDecision` (candidate index or direct pose, source, request id, expiry) |
```

- [ ] **Step 10: Run the contract tests and every version pin**

```bash
python -m pytest src/contracts/foundation/test src/runtime/gateway/test/test_protocol_schemas.py src/runtime/gateway/test/test_protocol_version_alignment.py test/test_line_follow_contract_docs.py test/architecture/test_module_structure.py -q
```

Expected: all pass, including `test_localization_contracts.py` 17 passed. (If `test_size_verdicts_are_well_formed_and_current` fails only on `control`, that is the expected interim state from the ground rules; any other failure is not.)

- [ ] **Step 11: Log, generate, lint**

Append to `src/contracts/foundation/logs.md`:

```markdown
## 2026-10-01 · uncommitted · feat(protocol): D-395 위치 확정 모델과 스냅샷 `localization` (API Ref v1.69)
- 변경: `core_common/protocol/localization.py` — `LocState`, `PoseFrame`(map|odom), `DecisionSource`, `LocalizationStatus`, `LocCandidate`, `RobotPoint`, `SquareSighting`, `CandidateReport`, `LocalizationDecision`(인덱스 또는 직접 좌표 정확히 하나, `candidate` 출처는 인덱스와만). `StateSnapshot.localization` 선택 필드(D-395 이전 로봇은 null). 모두 추가 전용(API-002, PRT-006).
- 증거: `test_localization_contracts.py` 17 passed, `test_protocol_schemas.py`, `test_protocol_version_alignment.py`, `test_line_follow_contract_docs.py`.
- gate 변화: 없음(SOURCE). 아직 아무 경로도 이 모델을 보내거나 받지 않는다.
- 결정: D-395 Proposed, D-18, D-347.
```

Append to `src/runtime/api_web/logs.md`:

```markdown
## 2026-10-01 · uncommitted · docs(api): 계약 버전 핀 v1.69 (D-395 1단계)
- 변경: `app.py` 독스트링·FastAPI description의 계약 버전 v1.68 → v1.69(D-347 세 핀 중 하나). 코드 경로 변화 없음.
- 증거: `test_protocol_version_alignment.py`.
- gate 변화: 없음.
```

Append to `docs/logs.md`:

```markdown
## 2026-10-01 · uncommitted · docs(api): API Ref v1.69 — 스냅샷 `localization`과 §7.9 D-395 모델
- 변경: 헤더 v1.69, §6.1 `localization`(state·pose_frame·confidence·reason·needs_human·request_id), §7.9 `CandidateReport`·`LocalizationDecision`(스키마만, 전송 경로는 2단계), 변경 이력 행. 핀 셋(헤더·`app.py`·`test_line_follow_contract_docs.py`)을 함께 옮겼다. `test_module_structure.py`의 `schemas.py` 판정을 1095로 재판정(accept 유지).
- 증거: `test_protocol_version_alignment.py`, `test_line_follow_contract_docs.py`, `test_localization_contracts.py`의 참조서 시험.
- gate 변화: 없음.
- 결정: D-395 Proposed, D-18, D-347, PRT-006.
```

```bash
python tools/harness/rosy_harness.py generate
python tools/harness/rosy_harness.py lint
git status --short
```

Expected: lint `0 error(s)`.

- [ ] **Step 12: Commit**

```bash
git add src/contracts/foundation/core_common/protocol/localization.py src/contracts/foundation/core_common/protocol/schemas.py src/contracts/foundation/core_common/protocol/AGENTS.md src/contracts/foundation/test/test_localization_contracts.py "docs/reference/ROSY API & Protocol Reference.md" src/runtime/api_web/core_api_web/api/app.py test/test_line_follow_contract_docs.py test/architecture/test_module_structure.py src/contracts/foundation/logs.md src/contracts/foundation/index.md src/runtime/api_web/logs.md src/runtime/api_web/index.md docs/logs.md docs/index.md
git commit -F - <<'EOF'
feat(protocol): D-395 localization models and snapshot frame flag (API Ref v1.69)

Additive only: StateSnapshot.localization {state, pose_frame, ...},
CandidateReport and LocalizationDecision. No path sends or accepts them yet.
The three version pins move together (D-347).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 9: Fleet scoring cues

**Files:**
- Create: `src/site/fleet/fleet/localization/__init__.py`, `src/site/fleet/fleet/localization/cues.py`, `src/site/fleet/fleet/localization/AGENTS.md`
- Modify: `src/site/fleet/fleet/AGENTS.md`, `src/site/fleet/test/test_boundaries.py`
- Test: `src/site/fleet/test/test_localization_cues.py`

- [ ] **Step 1: Write the failing tests**

Create `src/site/fleet/test/test_localization_cues.py`:

```python
"""D-395 §7 cues: bounded values, absent input is 0, never a guess."""

from __future__ import annotations

import math

import pytest

from fleet.localization import cues

A = (-1.26, 0.49)
B = (0.86, -0.52)
SLOTS = [cues.Slot(*A, math.pi / 2), cues.Slot(*B, 0.0)]
ON_A = (-1.26, 0.49, -math.pi / 2)
MIRROR_A = (1.26, -0.49, math.pi / 2)


def test_to_map_places_a_forward_point_along_the_heading():
    assert cues.to_map((1.0, 2.0, math.pi / 2), (0.5, 0.0)) == pytest.approx((1.0, 2.5))
    assert cues.to_map((0.0, 0.0, 0.0), (0.0, 0.3)) == pytest.approx((0.0, 0.3))


@pytest.mark.parametrize("pose, objects, peers, expected", [
    ((0.0, 0.0, 0.0), [(1.0, 0.0)], [(1.0, 0.05)], 1.0),                 # object lands on the peer
    ((0.0, 0.0, math.pi), [(1.0, 0.0)], [(1.0, 0.05)], -1.0),            # mirror heading: lands at (-1, 0)
    ((0.0, 0.0, 0.0), [], [(1.0, 0.0)], -1.0),                           # peer in view, nothing seen
    ((0.0, 0.0, 0.0), [(1.0, 0.0)], [(1.0, 0.0), (0.0, 1.0)], 0.0),      # one seen, one missing
    ((0.0, 0.0, 0.0), [(1.0, 0.0)], [(3.0, 0.0)], 0.0),                  # peer out of view
    ((0.0, 0.0, 0.0), [(1.0, 0.0)], [], 0.0),                            # no peers
])
def test_peers_cue(pose, objects, peers, expected):
    assert cues.peers_cue(pose, objects, peers) == pytest.approx(expected)


@pytest.mark.parametrize("pose, expected", [
    (ON_A, 1.0),                                     # axis + 180
    ((-1.26, 0.49, math.pi / 2), 1.0),               # axis
    ((-1.20, 0.55, math.radians(105)), 1.0),         # inside 10 cm / 20 deg
    ((-1.26, 0.49, 0.0), 0.0),                       # across the axis
    ((-1.10, 0.49, math.pi / 2), 0.0),               # 16 cm off
    (MIRROR_A, 0.0),                                 # the mirror of A is no slot
    ((0.86, -0.52, math.pi), 1.0),
])
def test_slot_cue(pose, expected):
    assert cues.slot_cue(pose, SLOTS) == expected


def test_last_good_cue_is_off_after_a_pickup_or_without_history():
    assert cues.last_good_cue(ON_A, ON_A[:2] + (0.0,), pickup=False) == pytest.approx(1.0)
    assert cues.last_good_cue(MIRROR_A, ON_A, pickup=False) < 0.01
    assert cues.last_good_cue(ON_A, ON_A, pickup=True) == 0.0
    assert cues.last_good_cue(ON_A, None, pickup=False) == 0.0


@pytest.mark.parametrize("age, expected_positive", [(0.0, True), (0.3, True), (0.31, False), (-0.1, False)])
def test_overhead_cue_needs_a_sighting_fresher_than_300_ms(age, expected_positive):
    sighting = cues.Sighting(-1.25, 0.5, 0.0, captured_at=100.0)
    value = cues.overhead_cue(ON_A, sighting, now=100.0 + age)
    assert (value > 0.9) is expected_positive
    assert cues.overhead_cue(ON_A, None, 100.0) == 0.0


@pytest.mark.parametrize("pose, sightings, expected", [
    ((-1.26, 0.19, math.pi / 2), [(0.0, 0.30)], 1.0),       # 30 cm short of A, square dead ahead
    ((-1.26, 0.19, math.pi / 2), [(0.0, None)], 1.0),       # unranged, on the bearing
    ((-1.26, 0.19, math.pi / 2), [], -1.0),                 # A should be in view and is not
    ((1.26, -0.19, -math.pi / 2), [(0.0, 0.30)], -1.0),     # mirror: sees a square where none is mapped
    ((0.0, 0.0, 0.0), [], 0.0),                             # no square in view, none seen
])
def test_square_cue(pose, sightings, expected):
    assert cues.square_cue(pose, [A, B], sightings) == expected
```

Append to `src/site/fleet/test/test_boundaries.py`:

```python
LOCALIZATION_DIR = Path(__file__).resolve().parents[1] / "fleet" / "localization"
#: D-395: the arbiter is scoring only. The service loop that talks to robots lives
#: in server/ (Phase 2) and calls in; the arbiter never calls out.
LOCALIZATION_FORBIDDEN = FORBIDDEN + ("fleet.server", "fastapi")


@pytest.mark.parametrize("module", sorted(p.name for p in LOCALIZATION_DIR.glob("*.py")))
def test_localization_arbiter_modules_import_no_transport(module):
    for name in _imports(LOCALIZATION_DIR / module):
        assert not name.startswith(LOCALIZATION_FORBIDDEN), f"{module} imports {name}"
```

- [ ] **Step 2: Run them and see them fail**

```bash
python -m pytest src/site/fleet/test/test_localization_cues.py src/site/fleet/test/test_boundaries.py -q
```

Expected: `test_localization_cues.py` collection error `ModuleNotFoundError: No module named 'fleet.localization'`; `test_boundaries.py` passes its old cases and reports the new test as skipped with an empty parameter set (the folder does not exist yet).

- [ ] **Step 3: Implement**

Create `src/site/fleet/fleet/localization/__init__.py`:

```python
"""Fleet localization arbiter (D-395): pure scoring, no transport, no asyncio."""
```

Create `src/site/fleet/fleet/localization/cues.py`:

```python
"""Scoring cues for one pose hypothesis (D-395 §7, rev. 1 §7). Pure numbers.

Each cue returns a bounded value; `arbiter.Weights` turns them into a score. No
cue decides alone: the arbiter needs a margin between hypotheses held for a
while. A missing input (no camera, no peers, no slot) contributes 0, never a
guess, so every cue can be absent and the arbiter still works (S4).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

Pose = tuple[float, float, float]

#: D-395 §5: the slot prior's box.
SLOT_XY_M = 0.10
SLOT_YAW_RAD = math.radians(20.0)
#: A projected object within this of a peer's reported pose is that peer.
PEER_MATCH_M = 0.15
#: A LOCALIZED peer closer than this should be in the scan (no occlusion model yet).
PEER_VIEW_M = 2.0
#: D-395 §7: an overhead sighting older than this is not a cue.
OVERHEAD_FRESH_S = 0.3
LAST_GOOD_SCALE_M = 0.3
OVERHEAD_SCALE_M = 0.25
#: A seen square must land this close to a mapped square under the hypothesis.
SQUARE_MATCH_M = 0.15
#: Where the front camera can see a square: range and half field of view.
SQUARE_VIEW_M = 0.6
SQUARE_HALF_FOV_RAD = math.radians(30.0)


@dataclass(frozen=True)
class Slot:
    x: float
    y: float
    axis_rad: float


@dataclass(frozen=True)
class Sighting:
    """Overhead camera pose of this robot, site clock seconds."""
    x: float
    y: float
    yaw: float
    captured_at: float


def wrap(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


def to_map(pose: Pose, point: tuple[float, float]) -> tuple[float, float]:
    """A base_link (forward, left) point placed on the map from `pose`."""
    c, s = math.cos(pose[2]), math.sin(pose[2])
    return (pose[0] + c * point[0] - s * point[1], pose[1] + s * point[0] + c * point[1])


def peers_cue(pose: Pose, objects: Sequence[tuple[float, float]],
              peers: Sequence[tuple[float, float]]) -> float:
    """(+1 per peer an object lands on, -1 per peer in view with none) / peers in view."""
    placed = [to_map(pose, o) for o in objects]
    in_view = [p for p in peers if math.dist(pose[:2], p) <= PEER_VIEW_M]
    if not in_view:
        return 0.0
    seen = sum(1 if any(math.dist(p, q) <= PEER_MATCH_M for q in placed) else -1 for p in in_view)
    return seen / len(in_view)


def slot_cue(pose: Pose, slots: Sequence[Slot]) -> float:
    """1 when the pose sits on a slot facing along its axis, either way."""
    for slot in slots:
        off = abs(wrap(pose[2] - slot.axis_rad))
        if math.dist(pose[:2], (slot.x, slot.y)) <= SLOT_XY_M and min(off, math.pi - off) <= SLOT_YAW_RAD:
            return 1.0
    return 0.0


def last_good_cue(pose: Pose, last_good: Optional[Pose], pickup: bool) -> float:
    """Closeness to the last LOCALIZED pose; never after a pickup."""
    if pickup or last_good is None:
        return 0.0
    return math.exp(-math.dist(pose[:2], last_good[:2]) / LAST_GOOD_SCALE_M)


def overhead_cue(pose: Pose, sighting: Optional[Sighting], now: float) -> float:
    """Closeness to an overhead sighting fresher than 300 ms."""
    if sighting is None or not 0.0 <= now - sighting.captured_at <= OVERHEAD_FRESH_S:
        return 0.0
    return math.exp(-math.dist(pose[:2], (sighting.x, sighting.y)) / OVERHEAD_SCALE_M)


def square_cue(pose: Pose, squares: Sequence[tuple[float, float]],
               sightings: Sequence[tuple[float, Optional[float]]]) -> float:
    """+1 when a seen square lands on a mapped one; -1 when a seen square lands on none,
    or a mapped one should be in view and is not; 0 when nothing is seen or expected.

    `sightings` are (bearing_rad, range_m) in base_link; an unranged sighting counts
    as seen when a mapped square lies on its bearing within the view.
    """
    c, s = math.cos(pose[2]), math.sin(pose[2])
    expected = []
    for sx, sy in squares:
        dx, dy = sx - pose[0], sy - pose[1]
        forward, left = c * dx + s * dy, -s * dx + c * dy
        bearing, rng = math.atan2(left, forward), math.hypot(forward, left)
        if forward > 0.0 and rng <= SQUARE_VIEW_M and abs(bearing) <= SQUARE_HALF_FOV_RAD:
            expected.append((bearing, rng, (sx, sy)))
    for bearing, rng in sightings:
        for e_bearing, e_range, centre in expected:
            if rng is None:
                if abs(wrap(bearing - e_bearing)) * e_range <= SQUARE_MATCH_M:
                    return 1.0
            elif math.dist(to_map(pose, (rng * math.cos(bearing), rng * math.sin(bearing))),
                           centre) <= SQUARE_MATCH_M:
                return 1.0
    return -1.0 if expected or sightings else 0.0
```

Create `src/site/fleet/fleet/localization/AGENTS.md`:

```markdown
<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-01 | Updated: 2026-10-01 -->

# localization

## Purpose

D-395 Fleet localization arbiter. Scores each robot's pose candidates with bounded cues and decides only when one leads the next by a margin held for 2 s. Pure: no transport, no asyncio, no robot calls. The service loop that feeds it and sends decisions belongs to `server/` (Phase 2).

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker |
| `cues.py` | Bounded cues per hypothesis: peers, slot (10 cm / 20 deg, either way along the axis), last good pose (never after a pickup), overhead sighting (≤ 300 ms), reference square |
| `arbiter.py` | `Weights`, `Context`, `score()`, `Arbiter.observe()` → `LocalizationDecision` |

## For AI Agents

### Working In This Directory

- Keep it pure: `test_boundaries.py` forbids httpx, websockets, rclpy, asyncio, fastapi, `fleet.swarm` and `fleet.server` here.
- A missing input is a 0 cue, never a guess; the arbiter must work with no camera and no peers.
- `last_good` and `overhead` weigh less than the margin on purpose: neither may decide alone (D-395 §7).

### Testing Requirements

`python -m pytest src/site/fleet/test/test_localization_cues.py src/site/fleet/test/test_localization_arbiter.py src/site/fleet/test/test_boundaries.py -q`

## Dependencies

### Internal

- `core_common.protocol.localization` (`CandidateReport`, `LocalizationDecision`)

### External

None.

<!-- MANUAL: -->
```

In `src/site/fleet/fleet/AGENTS.md`, after the row that starts with ``| `formation/` |``, add:

```markdown
| `localization/` | D-395 arbiter: pure cue scoring and held-margin decisions (see `localization/AGENTS.md`) |
```

- [ ] **Step 4: Run them and see them pass**

```bash
python -m pytest src/site/fleet/test/test_localization_cues.py src/site/fleet/test/test_boundaries.py -q
```

Expected: `test_localization_cues.py` 24 passed; `test_boundaries.py` all pass including `test_localization_arbiter_modules_import_no_transport[__init__.py]` and `[cues.py]`.

- [ ] **Step 5: Log, generate, lint**

Append to `src/site/fleet/logs.md`:

```markdown
## 2026-10-01 · uncommitted · feat(fleet): D-395 위치 중재 채점 단서 (순수)
- 변경: 새 하위 패키지 `fleet/localization/` — `cues.py`: 다른 LOCALIZED 로봇 일치(+1)/시야 안인데 안 보임(−1), 슬롯(10 cm / 20°, 축 앞뒤 모두), 마지막 정상 자세(픽업 뒤 0), 300 ms보다 신선한 오버헤드 sighting, 기준 사각형(맞으면 +1, 없는 곳에 보이거나 보여야 할 곳에 없으면 −1). 입력이 없으면 0. `test_boundaries.py`가 이 폴더의 전송·asyncio·server import를 막는다.
- 증거: `test_localization_cues.py` 24 passed, `test_boundaries.py`.
- gate 변화: 없음(SOURCE/LOCAL).
- 결정: D-395 Proposed(설계 승인, 1단계).
```

```bash
python tools/harness/rosy_harness.py generate
python tools/harness/rosy_harness.py lint
```

- [ ] **Step 6: Commit**

```bash
git add src/site/fleet/fleet/localization/__init__.py src/site/fleet/fleet/localization/cues.py src/site/fleet/fleet/localization/AGENTS.md src/site/fleet/fleet/AGENTS.md src/site/fleet/test/test_localization_cues.py src/site/fleet/test/test_boundaries.py src/site/fleet/logs.md src/site/fleet/index.md
git commit -F - <<'EOF'
feat(fleet): pure scoring cues for the D-395 localization arbiter

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 10: Fleet arbiter — decide on a margin held for 2 s

**Files:**
- Create: `src/site/fleet/fleet/localization/arbiter.py`
- Modify: `test/architecture/test_module_structure.py` (`fleet` verdict)
- Test: `src/site/fleet/test/test_localization_arbiter.py`

- [ ] **Step 1: Write the failing test**

Table-driven, with a mirror case per square (slot and square-sighting variants, each with the mirror listed first).

```python
"""D-395 §7 arbiter: decide only on a clear margin held for 2 s; a mirror case per square."""

from __future__ import annotations

import math

import pytest

from core_common.protocol.localization import CandidateReport, DecisionSource
from fleet.localization import cues
from fleet.localization.arbiter import Arbiter, Context, score

A, B = (-1.26, 0.49), (0.86, -0.52)
SLOTS = (cues.Slot(*A, math.pi / 2), cues.Slot(*B, 0.0))


def report(candidates, request_id="r1-1", objects=(), squares=(), pickup=False, robot_id="r1"):
    return CandidateReport.model_validate({
        "robot_id": robot_id, "request_id": request_id, "pickup": pickup, "stamp": 0.0,
        "candidates": [dict(zip(("x", "y", "yaw", "scan_fit", "paint_score"), c)) for c in candidates],
        "unmapped_objects": [{"x": x, "y": y} for x, y in objects],
        "square_sightings": [{"bearing_rad": b, "range_m": r, "confidence": 0.9} for b, r in squares]})


def pair(pose, fit=0.99, paint=(None, None)):
    """The pose and its 180-degree mirror, both fitting the scan equally (symmetric map)."""
    mirror = (-pose[0], -pose[1], math.atan2(math.sin(pose[2] + math.pi), math.cos(pose[2] + math.pi)))
    return [(*pose, fit, paint[0]), (*mirror, fit, paint[1])]


def run(arbiter, rep, context, start=0.0, end=3.0, dt=0.25):
    t = start
    while t <= end + 1e-9:
        decision = arbiter.observe(rep, context, t)
        if decision is not None:
            return t, decision
        t += dt
    return None, None


ON_A = (-1.26, 0.49, -math.pi / 2)
ON_B = (0.86, -0.52, math.pi)
OFF = (-0.9, -0.509, 0.0)

CASES = {
    # name: (candidates, report kwargs, context, expected index or None)
    "slot A beats its mirror": (pair(ON_A), {}, Context(slots=SLOTS), 0),
    "slot B beats its mirror": (pair(ON_B), {}, Context(slots=SLOTS), 0),
    "mirror listed first, slot A still wins": (pair(ON_A)[::-1], {}, Context(slots=SLOTS), 1),
    "mirror listed first, slot B still wins": (pair(ON_B)[::-1], {}, Context(slots=SLOTS), 1),
    "paint breaks the tie off-slot": (pair(OFF, paint=(0.98, 0.02)), {}, Context(slots=SLOTS), 0),
    "a peer seen where it is": (pair(OFF), {"objects": [(0.3, 0.9)]},
                                Context(peers=[(-0.6, 0.391)], slots=SLOTS), 0),
    "square seen on arrival near A": (pair((-1.26, 0.19, math.pi / 2)), {"squares": [(0.0, 0.30)]},
                                      Context(squares=(A, B)), 0),
    "square near B, mirror listed first": (pair((0.56, -0.52, 0.0))[::-1], {"squares": [(0.0, 0.30)]},
                                           Context(squares=(A, B)), 1),
    "symmetric and no cue: no decision": (pair(OFF), {}, Context(slots=SLOTS), None),
    "last good pose alone is below the margin": (pair(OFF), {}, Context(last_good=OFF), None),
    "last good pose after a pickup is ignored": (pair(OFF), {"pickup": True},
                                                 Context(last_good=OFF, slots=SLOTS), None),
}


@pytest.mark.parametrize("name", list(CASES))
def test_decision_table(name):
    candidates, kwargs, context, expected = CASES[name]
    t, decision = run(Arbiter(), report(candidates, **kwargs), context)
    if expected is None:
        assert decision is None
        return
    assert decision.candidate_index == expected and decision.source is DecisionSource.CANDIDATE
    assert decision.request_id == "r1-1" and t == pytest.approx(2.0)
    assert decision.expires_at == pytest.approx(t + 5.0)
    assert decision.evidence["margin"] >= 1.0


def test_the_lead_must_hold_two_seconds_and_resets_when_the_leader_changes():
    arbiter = Arbiter()
    win = report(pair(ON_A))
    flip = report(pair(ON_A)[::-1])
    assert arbiter.observe(win, Context(slots=SLOTS), 0.0) is None
    assert arbiter.observe(win, Context(slots=SLOTS), 1.5) is None
    assert arbiter.observe(flip, Context(slots=SLOTS), 1.75) is None   # leader index changed
    assert arbiter.observe(flip, Context(slots=SLOTS), 3.5) is None
    assert arbiter.observe(flip, Context(slots=SLOTS), 3.75).candidate_index == 1


def test_a_gap_below_the_margin_resets_the_hold():
    arbiter = Arbiter()
    clear = report(pair(ON_A))
    assert arbiter.observe(clear, Context(slots=SLOTS), 0.0) is None
    assert arbiter.observe(clear, Context(), 1.0) is None              # slot cue gone: no margin
    assert arbiter.observe(clear, Context(slots=SLOTS), 1.5) is None   # hold restarts here
    assert arbiter.observe(clear, Context(slots=SLOTS), 3.0) is None
    assert arbiter.observe(clear, Context(slots=SLOTS), 3.5) is not None


def test_one_decision_per_request_and_a_new_request_starts_over():
    arbiter = Arbiter()
    assert run(arbiter, report(pair(ON_A)), Context(slots=SLOTS))[1] is not None
    assert run(arbiter, report(pair(ON_A)), Context(slots=SLOTS), 3.0, 6.0)[1] is None
    again = run(arbiter, report(pair(ON_A), request_id="r1-2"), Context(slots=SLOTS), 6.0, 9.0)
    assert again[0] == pytest.approx(8.0)


def test_a_single_candidate_decides_after_the_hold():
    t, decision = run(Arbiter(), report([(*OFF, 0.97, None)]), Context())
    assert decision.candidate_index == 0 and t == pytest.approx(2.0)


def test_robots_are_arbitrated_independently():
    arbiter = Arbiter()
    r1, r2 = report(pair(ON_A)), report(pair(ON_B), robot_id="r2", request_id="r2-1")
    for t in (0.0, 1.0):
        assert arbiter.observe(r1, Context(slots=SLOTS), t) is None
        assert arbiter.observe(r2, Context(slots=SLOTS), t + 0.5) is None
    assert arbiter.observe(r1, Context(slots=SLOTS), 2.0).request_id == "r1-1"
    assert arbiter.observe(r2, Context(slots=SLOTS), 2.5).request_id == "r2-1"


def test_score_reports_every_cue_and_the_total():
    rows = score(report(pair(ON_A)), Context(slots=SLOTS), 0.0)
    assert set(rows[0]) == {"scan_fit", "paint", "peers", "slot", "last_good", "overhead", "square", "total"}
    assert rows[0]["total"] == pytest.approx(0.99 + 1.5) and rows[1]["total"] == pytest.approx(0.99)
```

- [ ] **Step 2: Run it and see it fail**

```bash
python -m pytest src/site/fleet/test/test_localization_arbiter.py -q
```

Expected: `ModuleNotFoundError: No module named 'fleet.localization.arbiter'`.

- [ ] **Step 3: Implement**

Create `src/site/fleet/fleet/localization/arbiter.py`:

```python
"""Fleet localization arbiter (D-395 §3, §7): score each robot's candidates, decide on a held margin.

Pure: the caller feeds `CandidateReport`s, what Fleet knows (`Context`) and its
clock; `observe` returns a `LocalizationDecision` once one candidate has led
the next by at least `margin` for `hold_s` under the same request id, and
never twice for one request. No transport, no asyncio, no robot calls.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Sequence

from core_common.protocol.localization import CandidateReport, LocalizationDecision

from fleet.localization import cues

#: D-395 §7: the hold is 2 s; margin and weights are initial values for S1 tuning.
HOLD_S = 2.0
MARGIN = 1.0
DECISION_TTL_S = 5.0


@dataclass(frozen=True)
class Weights:
    scan_fit: float = 1.0
    paint: float = 2.0
    peers: float = 2.0
    slot: float = 1.5
    last_good: float = 0.5
    overhead: float = 0.5
    square: float = 3.0


@dataclass(frozen=True)
class Context:
    """What Fleet knows about one robot's surroundings at decision time."""
    peers: Sequence[tuple[float, float]] = ()            # other LOCALIZED robots, map frame
    slots: Sequence[cues.Slot] = ()
    squares: Sequence[tuple[float, float]] = ()          # mapped reference square centres
    last_good: Optional[cues.Pose] = None
    sighting: Optional[cues.Sighting] = None


def score(report: CandidateReport, context: Context, now: float,
          weights: Weights = Weights()) -> list[dict]:
    """Per-candidate cue values and weighted total, in report order."""
    objects = [(o.x, o.y) for o in report.unmapped_objects]
    seen = [(s.bearing_rad, s.range_m) for s in report.square_sightings]
    out = []
    for c in report.candidates:
        pose = (c.x, c.y, c.yaw)
        values = {
            "scan_fit": c.scan_fit,
            "paint": c.paint_score or 0.0,
            "peers": cues.peers_cue(pose, objects, context.peers),
            "slot": cues.slot_cue(pose, context.slots),
            "last_good": cues.last_good_cue(pose, context.last_good, report.pickup),
            "overhead": cues.overhead_cue(pose, context.sighting, now),
            "square": cues.square_cue(pose, context.squares, seen) if seen else 0.0,
        }
        values["total"] = sum(getattr(weights, k) * v for k, v in values.items())
        out.append(values)
    return out


@dataclass
class _Lead:
    request_id: str
    index: int
    since: float


@dataclass
class Arbiter:
    margin: float = MARGIN
    hold_s: float = HOLD_S
    ttl_s: float = DECISION_TTL_S
    weights: Weights = field(default_factory=Weights)
    _leads: dict = field(default_factory=dict)
    _decided: dict = field(default_factory=dict)

    def observe(self, report: CandidateReport, context: Context,
                now: float) -> Optional[LocalizationDecision]:
        robot = report.robot_id
        if self._decided.get(robot) == report.request_id:
            return None
        scores = score(report, context, now, self.weights)
        order = sorted(range(len(scores)), key=lambda i: -scores[i]["total"])
        best = order[0]
        gap = scores[best]["total"] - scores[order[1]]["total"] if len(order) > 1 else math.inf
        lead = self._leads.get(robot)
        if gap < self.margin:
            self._leads.pop(robot, None)
            return None
        if lead is None or lead.request_id != report.request_id or lead.index != best:
            self._leads[robot] = _Lead(report.request_id, best, now)
            return None
        if now - lead.since < self.hold_s:
            return None
        self._decided[robot] = report.request_id
        self._leads.pop(robot, None)
        return LocalizationDecision(
            request_id=report.request_id, candidate_index=best, source="candidate",
            evidence={"totals": [round(s["total"], 3) for s in scores],
                      "margin": round(min(gap, 99.0), 3),
                      "cues": {k: round(v, 3) for k, v in scores[best].items()}},
            expires_at=now + self.ttl_s)
```

- [ ] **Step 4: Run it and see it pass**

```bash
python -m pytest src/site/fleet/test/test_localization_arbiter.py src/site/fleet/test/test_localization_cues.py src/site/fleet/test/test_boundaries.py -q
```

Expected: `test_localization_arbiter.py` 17 passed, the rest pass.

- [ ] **Step 5: Re-judge the `fleet` package verdict**

```bash
python -c "import sys; sys.path.insert(0, 'test/architecture'); import test_module_structure as t; print(t._over_budget().get('fleet'))"
```

Expected: about `23528` (23299 on main at plan time + 229). In `test/architecture/test_module_structure.py`, in the `"fleet"` entry change `23_237,` to the printed number and replace

```python
        "Split remains unscheduled (docs/plans/2026-09-30-er2-mission-feedback-loop.md)",
```

with

```python
        "Re-judged 2026-10-01 at <printed number> when the D-395 localization arbiter joined as its own pure "
        "subpackage (fleet/localization: cues.py, arbiter.py); verdict unchanged. "
        "Split remains unscheduled (docs/plans/2026-09-30-er2-mission-feedback-loop.md)",
```

writing the printed number where the angle brackets are. Then:

```bash
python -m pytest test/architecture/test_module_structure.py -q
```

Expected: pass, except possibly the interim `control` allowance (ground rules).

- [ ] **Step 6: Log, generate, lint**

Append to `src/site/fleet/logs.md`:

```markdown
## 2026-10-01 · uncommitted · feat(fleet): D-395 위치 중재기 — 뚜렷한 격차가 2 s 유지될 때만 결정
- 변경: `fleet/localization/arbiter.py` — `Weights`(초기값: scan 1, paint 2, peers 2, slot 1.5, last_good 0.5, overhead 0.5, square 3; S1에서 조정), `Context`, `score()`, `Arbiter.observe()`: 1등이 2등을 1.0 이상 앞서고 같은 request_id·같은 1등으로 2 s 유지되면 `LocalizationDecision`(source candidate, 근거 점수, 만료 5 s)을 한 번만 낸다. last_good·overhead는 격차보다 가벼워 혼자 결정하지 못한다. `fleet` 크기 판정을 실측값으로 재판정.
- 증거: `test_localization_arbiter.py` 17 passed — 사각형마다 거울 사례(슬롯·사각형 관측, 거울을 앞에 둔 경우 포함), 페인트·다른 로봇으로 해소, 단서 없음·마지막 자세만·픽업 뒤는 결정 없음, 유지 시간·1등 교체·격차 붕괴 시 재시작, 로봇별 독립.
- gate 변화: 없음(SOURCE/LOCAL). 서비스 루프·전송은 2단계.
- 결정: D-395 Proposed(설계 승인, 1단계).
```

Append to `docs/logs.md`:

```markdown
## 2026-10-01 · uncommitted · chore(architecture): `fleet` 크기 판정 재판정 (D-395 중재기)
- 변경: `test_module_structure.py`의 `fleet` 판정 줄 수를 D-395 `fleet/localization/` 추가 뒤 실측값으로 옮기고 사유를 덧붙였다. 판정(split, 미예정) 그대로.
- 증거: `test_module_structure.py`.
- gate 변화: 없음.
```

```bash
python tools/harness/rosy_harness.py generate
python tools/harness/rosy_harness.py lint
```

- [ ] **Step 7: Commit**

```bash
git add src/site/fleet/fleet/localization/arbiter.py src/site/fleet/test/test_localization_arbiter.py test/architecture/test_module_structure.py src/site/fleet/logs.md src/site/fleet/index.md docs/logs.md docs/index.md
git commit -F - <<'EOF'
feat(fleet): D-395 arbiter decides only on a margin held for 2 s

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 11: Host end-to-end — two robots, zero human input

Wires Tasks 1–10 with fakes: the robots' truth lives only in the test world; every robot decision is the pure modules', every Fleet decision the arbiter's, and every message crosses the D-395 wire models.

**Files:**
- Test: `src/runtime/sensing/test/test_loc_e2e.py`
- Modify: `test/architecture/test_module_structure.py` (`control` verdict)

- [ ] **Step 1: Write the test**

```python
"""D-395 Phase 1 host end-to-end: robot pure logic + wire models + Fleet arbiter, no ROS.

Two simulated robots on the checked-in map_v2_fleet map (180-degree symmetric).
Each robot searches, reports candidates over the D-395 wire model, Fleet
arbitrates, the robot injects and runs the 3 s check. Every case must end
LOCALIZED at the true pose with zero human input: no decision ever carries
source 'human' and nothing outside this loop touches the robots.
"""
import itertools
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "site" / "fleet"))

from core_common.protocol.localization import CandidateReport, DecisionSource  # noqa: E402
from fleet.localization import cues  # noqa: E402
from fleet.localization.arbiter import Arbiter, Context  # noqa: E402

from control.sensing.loc_candidates import (  # noqa: E402
    global_candidates, merge, sensor_from_base, slot_candidates)
from control.sensing.loc_objects import unmapped_objects  # noqa: E402
from control.sensing.loc_state import LocalizationStateMachine, LocState  # noqa: E402
from control.sensing.perception.paint_hypothesis import paint_score  # noqa: E402
from loc_world import MOUNT, SQUARES, field, mirror, paint_map, paint_points, scan  # noqa: E402

RADIUS, DT, LIMIT_S = .105, .25, 12.


class SimRobot:
    """One robot: truth for the world, pure D-395 logic for everything it decides."""

    def __init__(self, robot_id, truth, camera=False, mirror_first=False):
        self.robot_id, self.truth, self.camera, self.mirror_first = robot_id, truth, camera, mirror_first
        ids = itertools.count(1)
        self.machine = LocalizationStateMachine(lambda: f"{robot_id}-{next(ids)}")
        self.report, self.injected = None, None

    def others(self, robots):
        return [r.truth[:2] for r in robots if r is not self]

    def search(self, now, robots):
        ranges, angles = scan(self.truth, peers=self.others(robots))
        found = merge(slot_candidates(field(), SQUARES, ranges, angles, RADIUS, MOUNT),
                      global_candidates(field(), ranges, angles, RADIUS, MOUNT))
        if self.mirror_first:   # the forced mirror: the wrong twin is reported first
            found.sort(key=lambda c: math.dist((c.x, c.y), mirror(self.truth)[:2]))
        self.machine.offer(found, now)
        first = found[0]
        objects = unmapped_objects(field(), sensor_from_base((first.x, first.y, first.yaw), MOUNT),
                                   ranges, angles, MOUNT)
        points = paint_points(self.truth) if self.camera else None
        self.report = CandidateReport.model_validate({
            "robot_id": self.robot_id, "request_id": self.machine.request_id, "stamp": now,
            "pickup": self.machine.pickup,
            "candidates": [{"x": c.x, "y": c.y, "yaw": c.yaw, "scan_fit": c.scan_fit,
                            "paint_score": None if points is None else
                            paint_score(paint_map(), points, (c.x, c.y, c.yaw))} for c in found],
            "unmapped_objects": [{"x": x, "y": y} for x, y in objects]})

    def apply(self, decision, now):
        step = self.machine.decide(decision.request_id, now, candidate_index=decision.candidate_index,
                                   source=decision.source.value, expires_at=decision.expires_at)
        if "inject_pose" in step.actions:
            self.injected = step.pose

    def tick(self, now, robots):
        if self.injected is not None and self.machine.state is not LocState.LOCALIZED:
            ranges, angles = scan(self.truth, peers=self.others(robots))
            fit = field().score(sensor_from_base(self.injected, MOUNT), ranges, angles)
            self.machine.observe_fit(now, fit)


def context(robot, robots):
    """Fleet's view: only LOCALIZED robots are peers, at the pose they reported."""
    peers = [r.injected[:2] for r in robots
             if r is not robot and r.machine.state is LocState.LOCALIZED]
    return Context(peers=peers, slots=[cues.Slot(s.x, s.y, s.axis_rad) for s in SQUARES],
                   squares=[(s.x, s.y) for s in SQUARES])


def localize(robots):
    arbiter, decisions = Arbiter(), []
    for k in range(int(LIMIT_S / DT) + 1):
        now = k * DT
        for robot in robots:
            if robot.machine.state is LocState.LOCALIZED:
                continue
            if robot.report is None:
                robot.search(now, robots)
            decision = arbiter.observe(robot.report, context(robot, robots), now)
            if decision is not None:
                decisions.append(decision)
                robot.apply(decision, now)
            robot.tick(now, robots)
        if all(r.machine.state is LocState.LOCALIZED for r in robots):
            break
    return decisions


def assert_at_truth(robot):
    assert robot.machine.state is LocState.LOCALIZED, robot.robot_id
    x, y, yaw = robot.injected
    assert math.dist((x, y), robot.truth[:2]) < .03
    assert abs(math.atan2(math.sin(yaw - robot.truth[2]), math.cos(yaw - robot.truth[2]))) < math.radians(4)


def test_on_square_and_off_slot_robots_power_on_together_without_a_camera():
    """r1 on square A facing -y (axis + 180): the scan picks the heading, the slot prior
    beats the mirror. r2 off-slot has no prior until r1 is LOCALIZED; then r1 in r2's
    scan lands on r1 only under the true hypothesis."""
    r1 = SimRobot("r1", (-1.26, .49, -math.pi / 2))
    r2 = SimRobot("r2", (-.9, -.509, 0.))
    decisions = localize([r1, r2])
    assert_at_truth(r1)
    assert_at_truth(r2)
    assert {d.source for d in decisions} == {DecisionSource.CANDIDATE}
    assert len(decisions) == 2


@pytest.mark.parametrize("truth", [(0., .51, 0.), (.86, -.52, math.pi)],
                         ids=["off-slot", "on-square-B"])
def test_a_lone_robot_with_the_mirror_reported_first_still_localizes_on_paint(truth):
    robot = SimRobot("r3", truth, camera=True, mirror_first=True)
    decisions = localize([robot])
    assert_at_truth(robot)
    assert [d.source for d in decisions] == [DecisionSource.CANDIDATE]
    assert decisions[0].candidate_index != 0     # index 0 was the mirror


def test_a_lone_off_slot_robot_without_cues_is_left_to_the_ladder():
    """No camera, no peer, no slot: the twins tie, so Fleet decides nothing (D-395 §6, step 2+)."""
    robot = SimRobot("r4", (-.9, -.509, 0.))
    assert localize([robot]) == []
    assert robot.machine.state is LocState.CANDIDATES and robot.injected is None
```

- [ ] **Step 2: Run it**

```bash
python -m pytest src/runtime/sensing/test/test_loc_e2e.py -q
```

Expected: `4 passed` in about 20 s. If a case fails, read the decision `evidence` (totals and cues) before changing weights: a fix belongs in the module whose contract was wrong, not in the test world. The fourth case is the negative control: with no cue Fleet must decide nothing.

- [ ] **Step 3: Mutation check (do not commit)**

Temporarily set `slot: float = 0.0` in `Weights` (`src/site/fleet/fleet/localization/arbiter.py`) and rerun:

```bash
python -m pytest src/runtime/sensing/test/test_loc_e2e.py -q -k power_on
```

Expected: FAIL (`r1` never LOCALIZED). Restore `slot: float = 1.5` with the Edit tool and confirm `git diff src/site/fleet/fleet/localization/arbiter.py` is empty. This proves the on-square case is carried by the slot prior and not by an accident of the world.

- [ ] **Step 4: Run every touched suite once, in one process each**

```bash
python -m pytest src/runtime/sensing/test -q
python -m pytest src/site/fleet/test src/contracts/foundation/test -q
python -m pytest src/runtime/gateway/test/test_protocol_schemas.py src/runtime/gateway/test/test_protocol_version_alignment.py test/test_line_follow_contract_docs.py test/test_behavior_test_ownership.py test/architecture -q
```

Expected: all pass except `test_size_verdicts_are_well_formed_and_current` on `control` (fixed next step) and the failures recorded as pre-existing in Task 0 Step 2. At plan time the full prototype of Tasks 1–11 ran here with exactly that result (sensing, fleet, foundation, gateway protocol and architecture suites). `test_behavior_test_ownership.py` passes because the e2e lives in the sensing package, not in `test/` or `gateway/test`.

- [ ] **Step 5: Re-judge the `control` package verdict**

```bash
python -c "import sys; sys.path.insert(0, 'test/architecture'); import test_module_structure as t; print(t._over_budget().get('control'))"
```

Expected: about `40487` (39975 on main at plan time + 512). In `test/architecture/test_module_structure.py`, in the `"control"` entry change `39_914,` to the printed number and replace

```python
        "move with the P1a split — verdict unchanged)",
```

with

```python
        "move with the P1a split — verdict unchanged; re-judged 2026-10-01 at <printed number> when the "
        "D-395 ROS-free localization candidates, objects, injection check and state machine "
        "(sensing/loc_*.py) and the paint-hypothesis and reference-square cues (sensing/perception) "
        "joined — they move with the P1a split, verdict unchanged)",
```

writing the printed number where the angle brackets are.

- [ ] **Step 6: Architecture suite green**

```bash
python -m pytest test/architecture/test_module_structure.py -q
```

Expected: all pass.

- [ ] **Step 7: Log, generate, lint**

Append to `src/runtime/sensing/logs.md`:

```markdown
## 2026-10-01 · uncommitted · test(localization): D-395 1단계 호스트 종단 시험 — 두 로봇, 사람 입력 0
- 변경: `test/test_loc_e2e.py` — 체크인된 map_v2_fleet 지도 위 모의 로봇 2대가 순수 모듈(후보·물체·상태 기계·3 s 검증·페인트 점수)과 D-395 선 모델(`CandidateReport`/`LocalizationDecision`)과 Fleet 중재기를 거쳐 위치를 확정한다. 사각형 A 위(카메라 없음, 슬롯 사전)와 슬롯 밖(카메라 없음, 먼저 확정된 로봇이 단서)을 동시에 켬, 거울을 첫 후보로 강제한 외톨이 로봇(슬롯 밖·사각형 B, 페인트로 해소), 단서 없는 외톨이는 결정 없음(음성 대조). `control` 크기 판정을 실측값으로 재판정.
- 증거: `test_loc_e2e.py` 4 passed, 슬롯 가중 0 돌연변이에서 첫 사례 실패 확인(커밋 안 함), sensing·fleet·foundation 전체와 아키텍처 시험 통과.
- gate 변화: SOURCE/LOCAL GO. ROS-SIM(S1)·DEVICE 해당 없음 — 노드·launch·API 배선은 2단계.
- 결정: D-395 Proposed(설계 승인, 1단계 완료).
```

Append to `docs/logs.md`:

```markdown
## 2026-10-01 · uncommitted · chore(architecture): `control` 크기 판정 재판정 (D-395 1단계)
- 변경: `test_module_structure.py`의 `control` 판정 줄 수를 D-395 sensing 순수 모듈 추가 뒤 실측값으로 옮기고 사유를 덧붙였다. 판정(split, P1a) 그대로.
- 증거: `test_module_structure.py`.
- gate 변화: 없음.
```

```bash
python tools/harness/rosy_harness.py generate
python tools/harness/rosy_harness.py lint
git status --short
```

Expected: lint `0 error(s)`; status shows only the paths below.

- [ ] **Step 8: Commit**

```bash
git add src/runtime/sensing/test/test_loc_e2e.py test/architecture/test_module_structure.py src/runtime/sensing/logs.md src/runtime/sensing/index.md docs/logs.md docs/index.md
git commit -F - <<'EOF'
test(localization): D-395 host end-to-end, two robots and zero human input

On-square + off-slot power-on together, a forced mirror on paint, and a
no-cue negative control, all through the wire models and the Fleet arbiter.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 12: Review, merge main, land

**Files:** whatever the merge touches; no new content.

- [ ] **Step 1: Independent review**

Dispatch `superpowers:requesting-code-review` (or `oh-my-claudecode:code-reviewer`) on `main..feat/d395-host-localization` with this plan and D-395 as the spec. Fix findings in new commits (no amend). Run `/ce-compound` afterwards if the review taught a reusable lesson.

- [ ] **Step 2: Merge main into the branch**

```bash
git merge main
```

On conflicts in `logs.md`/`index.md`/`STATUS.md`: keep main's entries first, then this branch's, then `python tools/harness/rosy_harness.py generate`. On `test/architecture/test_module_structure.py`: keep both sides' verdict edits and re-measure with the commands in Tasks 8, 10 and 11. On the API Reference version: if main took v1.69, move this change to the next MINOR in all three pins and the changelog row. Then:

```bash
git grep -nE '^(<<<<<<<|>>>>>>>)( |$)'
python tools/harness/rosy_harness.py lint
```

Expected: `git grep` prints nothing; lint `0 error(s)`. Commit the merge with the `Co-Authored-By` line.

- [ ] **Step 3: Re-run the Task 11 Step 4 suites on the merge commit**

Expected: all pass.

- [ ] **Step 4: Fast-forward main**

From the repo root (not the worktree):

```bash
git merge --ff-only feat/d395-host-localization
```

Expected: `Fast-forward`. If it refuses, main moved: repeat Step 2 in the worktree. Do not push.

---

## Phase 2 and later — outline

Each item is its own worktree (`feat/d395-<topic>`) and its own detailed plan written when it starts. **[APPROVAL]** marks items that change robot config, launch, params, a served API or capability, or robot motion; they start only after the user approves that item. Order follows design §14.

| # | Topic | Main files | Approval |
|---|---|---|---|
| P2-1 | **CORE reports the state and the frame.** Fill `StateSnapshot.localization` from a robot topic; `pose_frame` follows the map-TF freshness branch that today silently swaps in odom (`ros_bridge.py:214-218`); FleetAgent's 1 Hz heartbeat and `/ws/state` carry it unchanged | `src/runtime/gateway/core/bridge/ros_bridge.py`, CORE state assembly, `src/runtime/services/core_features/fleet_agent/agent.py`, gateway tests | [APPROVAL] device runtime change (field becomes non-null) |
| P2-2 | **Fleet ignores untrusted poses.** Traffic and bays skip poses whose `pose_frame` is `odom` or whose state is not LOCALIZED, and treat such robots as wide obstacles; decide the legacy (`localization: null`) policy first (open question 2) | `src/site/fleet/fleet/server/traffic.py`, `bays.py`, `console.py` (snapshot cache), `test_server_traffic.py`, `test_server_bays.py` | [APPROVAL] changes live Fleet behaviour |
| P2-3 | **Robot node integration.** A ROS adapter (new `control/loc_assist_node.py` or a rework of `localization_node.py`) runs `global_candidates`/`slot_candidates`/`unmapped_objects`/`LocalizationStateMachine`, publishes `localization/state` and `localization/candidates`, consumes CORE's decision, and feeds `observe_fit` from the existing `MapAgreement.score`. Remove `localization_node`'s own `/initialpose` publication on a unique match (rejected alternative B). Paint points from `lane_bev`/line_observer keep mode; square sightings from `HsvSquareDetector` on `camera/front`. Pickup from `safety/pickup` | `src/runtime/sensing/control/localization_node.py` (or new node), `launch/localization.launch.py`, `robot.launch.py`, `setup.py` entry point, launch contract tests | [APPROVAL] robot launch and params (`nav2_params.yaml` `set_initial_pose` stays as is until the user decides) |
| P2-4 | **CORE API and bridge.** `POST /api/v1/localization/decision` (`LocalizationDecision`), legacy `POST /api/v1/localization/initialpose {x,y,yaw}` read as `source: human` and routed through the same 3 s check; per-source covariance in `initial_pose.py`; Nav2 goal cancel and replan on LOCALIZED; navigation goal and lane keep refuse unless LOCALIZED; events `localization.candidates`, `localization.result`, `localization.initialpose` with `source`; candidate reports up through FleetAgent's `event` envelope; still blocked during a D-321 calibration lease. API Ref §5.3/§7.9/§8 and the three pins move together | `src/runtime/api_web/core_api_web/api/v1/navigation.py`, `src/runtime/gateway/core/bridge/ros_bridge.py:576`, `src/runtime/services/core_features/navigation/initial_pose.py`, `core_common/capability.py`, API Ref | [APPROVAL] new API paths and behaviour |
| P2-5 | **Capability and role.** New capability (`LOCALIZE_ASSIST`, name proposed) carried by Fleet's operator token, separate from human `NAVIGATE` | `core_common` capability/role model, `src/runtime/api_web` auth, `robots.yaml` token handling | [APPROVAL] role model change |
| P2-6 | **Fleet client and service loop.** `RobotClient.localization_decision/maneuver/homing` + `HttpRobotClient` + fakes; `server/localization_service.py` gathers reports and snapshots, builds `Context` (LOCALIZED peers, slots and squares from `lane_rules.yaml`, sightings ≤ 300 ms from `sighting_store.py`), runs `Arbiter`, sends decisions, runs the §8 monitor (25 cm or 60° for 1.5 s → `mark_suspect`), times the ladder and raises `needs_human`; console badge "위치 확인 필요" | `src/site/fleet/fleet/swarm/transport.py:108-127`, `src/site/fleet/test/fakes.py`, new `server/localization_service.py`, `console.py`, `web/` | [APPROVAL] only for the console wording/UI review; code otherwise Fleet-internal |
| P2-7 | **Check manoeuvre and homing missions.** CORE executes `rotate_in_place`, `nudge_forward`, `to_square`, `wall_to_corner`, `lane_to_stopline` very slowly under its own obstacle stop, E-stop, `max_distance_m` and `max_time_s`; accept/reject with reasons (`path_not_clear`, `estop`, `busy`, `calibration_lease`); Fleet clears traffic with the existing yield; Fleet never drives wheels (D-2, D-369). On arrival at a square: `square_cue` resolves, `homing_ref` direct pose → 3 s check | CORE mission executor (new module under `src/runtime/services/core_features/`), `core_api_web` routes, Fleet service | [APPROVAL] robot motion |
| P2-8 | **Gazebo benches S1/S2** in WSL Jazzy: `ros2 launch gz_sim gz_multi.launch.py robots:=2 world_name:=map_v2_fleet_real.world core:=true` (then `robots:=4`); per-robot spawn poses for on-square, off-slot, forced mirror, pickup during a drive, simultaneous re-arbitration, homing in traffic; record weights/margin/thresholds from the runs; also a real-camera recording check of `HsvSquareDetector` (visible range, carpet, lighting) before any weight on `square` is trusted | `src/sim/gz_sim/launch/gz_multi.launch.py` (per-robot spawn), bench script under `tools/`, results doc in `docs/plans/` | Sim only; no approval for S1/S2 themselves. Pass: zero human input, all LOCALIZED, zero mirror lock (S2: zero collisions) |
| P2-9 | **D-257 / D-393 amendments.** After S1 passes, propose acceptance of the D-395 amendment table (D-257 §5 last sentence and out-of-scope line, D-393 §3 lines 2–3; one-line confirmations in D-360 §3 and D-375 §5); D-379 `reference_square` label class with D-373 | `docs/adr/D-257-…`, `D-393-…`, `D-360-…`, `D-375-…`, `D-395-…`, ADR Log | [APPROVAL] ADR acceptance |
| P2-10 | **Real robots S3**: two Pinkys at low speed, S1 scenarios, on `9dfk`/`8kcn` (shared and gated robots) | device deploy, evidence under `X:\DevTemp` | [APPROVAL] required before any motion |
| P2-11 | **Overhead camera cue S4**: camera on/off runs behave the same; sightings enter only as the ≤ 300 ms cue and the `overhead` decision source | Fleet service, `sightings.py` | Depends on P2-9 (D-257 amendment accepted) |

---

## Self-review

**Spec coverage** (ADR Decision items and revisions → where):

| Spec | Phase 1 | Later |
|---|---|---|
| 1 Goal: 2–4 robots, no human input, camera optional, no new ArUco | Task 11 (2 robots, zero human input, no camera in case 1) | P2-8 (4 robots), P2-11 |
| 2 Four states; autonomy only LOCALIZED; power-on UNKNOWN | Task 5 | P2-3, P2-4 (gating in CORE) |
| 3 Robot proposes, Fleet arbitrates; margin held 2 s | Tasks 2, 3, 6, 10 | P2-6 |
| 4 Escalation ladder (manoeuvre, homing, stop + "위치 확인 필요") | Negative control in Task 11 proves step 1 does not guess | P2-6, P2-7 |
| 5 Start slots as prior, 10 cm / 20° | Tasks 2 (`slot_candidates`), 9 (`slot_cue`) | — |
| 6 Messages: status with frame flag, candidate report, decision, manoeuvre/homing | Task 8 (status, report, decision) | P2-4, P2-7 (manoeuvre/homing messages) |
| 7 Robot checks every injection for 3 s; source logged; Nav2 goal cancelled | Tasks 4, 5 (`cancel_nav_goal` action) | P2-4 (logging, events, cancel) |
| 8 Cues: peers, missing peer, paint, slot, last good (no pickup), overhead ≤ 300 ms | Tasks 6, 9 | P2-6 (inputs) |
| 9 Monitoring while LOCALIZED | Robot side: Task 5 (`fit_drop`, `pickup`, `mark_suspect`) | Fleet monitor P2-6 |
| 10 Safety: traffic/bays ignore odom or non-LOCALIZED; Fleet death | Frame flag exists (Task 8) | P2-2, P2-3 |
| 11 Out of scope (config now, EKF, inter-robot lidar likelihood) | Respected | — |
| Rev. 1: squares A/B, homing to square, square sighting cue, detector, S1/S2 scenarios | Tasks 2, 7, 9 (`square_cue`), 10 | P2-7, P2-8 |
| Rev. 2: axis only; axis and axis+180; scan picks | Task 2 (`slot_candidates`), Task 9 (`slot_cue` either way) | — |
| D-18 / PRT-006 / D-347 | Task 8 | P2-4 |

**Placeholder scan:** every code step embeds the full file or the exact inserted/replaced block. The only values the executor fills in are measured line counts printed by the command in the same step (Tasks 8, 10, 11), because peers move `main` between plan and execution.

**Type consistency:** `PoseCandidate(x, y, yaw, scan_fit, origin)` (Task 2) is what `LocalizationStateMachine.offer/decide` index (Task 5) and Task 11 converts to `LocCandidate` (Task 8). `Mount(x, y, yaw)` and `sensor_from_base/base_from_sensor` (Task 2) are the only frame conversions, used by Tasks 3 and 11. `InjectionCheck.observe(now_s, fit)` returns `PENDING/PASSED/FAILED` (Task 4) and is consumed only by `LocalizationStateMachine.observe_fit` (Task 5). `paint_score(paint_map, points, pose)` (Task 6) fills `LocCandidate.paint_score`. `SquareObservation(bearing_rad, range_m, confidence)` (Task 7) matches `SquareSighting` field names (Task 8) and `square_cue` reads `(bearing_rad, range_m)` (Task 9). `cues.Slot(x, y, axis_rad)` mirrors `ReferenceSquare(id, x, y, axis_rad)`. `Arbiter.observe(report, context, now) -> LocalizationDecision | None` (Task 10) feeds `LocalizationStateMachine.decide(request_id, now_s, candidate_index=, source=, expires_at=)` in Task 11. `LocState` string values are identical in `loc_state.py` and `core_common.protocol.localization`.

---

## Open questions (need the user)

1. **Status vs. implementation.** The design says no implementation before D-395 is Accepted; the user approved the design and asked to proceed. Phase 1 is host-only and leaves D-395 Proposed until S1. Confirm, or say whether to record the go-ahead as a D-395 revision 3.
2. **Legacy snapshots.** When P2-2 lands, should Fleet ignore poses from robots whose snapshot has `localization: null` (safe, but stalls pre-D-395 robots in traffic) or keep trusting them until every robot runs P2-1?
3. **Decision expiry.** `expires_at` is absolute time and needs Fleet/robot clocks within the 5 s TTL; switch to a relative `ttl_s` before P2-4 opens the path?
4. **Which cues may decide alone** (spec decisions table): slot, paint, peers and square can; last good pose and overhead cannot. Confirm.
5. **Mirror injections pass the 3 s check** on this map. Accept that mirror safety rests on arbitration plus Fleet's monitor (and a human `source: human` mirror pose would also pass), or require a second, asymmetric check (paint or square) before LOCALIZED?
6. **Thresholds** stay initial until S1: weights, margin 1.0, fit 0.85, settle 0.5 s, fit-drop 1 s, peer view 2 m, square view 0.6 m / ±30°.
7. **Carried from D-395 Open:** pickup signal on Pinky (IMU, `safety/pickup` on device), paint-score Pi cost, per-source covariance, capability name and role model, square tape measurement (D-397 session).
