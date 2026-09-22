---
title: A fixture written from the same model as the code is one belief, not two
date: 2026-09-09
category: workflow-issues
module: docking
problem_type: workflow_issue
component: development_workflow
severity: high
applies_when:
  - "a test's inputs come from a generator written by the same author, in the same sitting, as the code under test"
  - 'a fixture has a "nothing here" branch — inf, NaN, None, an empty list, a 404 — that the real world may never produce'
  - "building an instrument, benchmark, sweep or evaluation harness whose errors come out as numbers about something else"
  - "a candidate is about to be eliminated on measured evidence"
  - "two artifacts describe one shape — a simulator model and a detector config, a schema and a migration"
symptoms:
  - "the whole suite is green and none of its assertions is weak, wrong, or mutable into red"
  - "a scan fixture emits an out-of-range sentinel for every ray that misses the target, so no background object exists in any test case"
  - "a rule that splits only on angular gaps finds no gaps once a surface fills every bearing"
  - "a measurement rig is about to report near-zero acquisition for a candidate whose geometry is sound"
root_cause: logic_error
resolution_type: code_fix
related_components:
  - testing_framework
  - tooling
tags:
  - co-designed-fixture
  - shared-premise
  - false-green-tests
  - measurement-rig
  - unmodelled-background
  - lidar-clustering
  - dock-detection
  - ros2
---

# A fixture written from the same model as the code is one belief, not two

> **Track: knowledge.** The concrete defect below was fixed as a bug, but the durable thing
> is not the fix. It is that a synthetic input generator and the code that consumes it were
> written from one mental model, so they agreed, and their agreement was read as correctness.
>
> All of this lived on branch `feat/dock-detector-measurement-rig`, which was **never
> merged**. On 2026-09-22 the branch was frozen as tag
> `archive/2026-09-22/feat/dock-detector-measurement-rig`, and every SHA and path below
> resolves against that tag, not against `main`. The rig itself was superseded rather than
> ported: SRS v1.1 DNC-007 and D-138/D-139 chose ArUco camera tag detection, so the LiDAR /
> intensity / IR comparison the rig existed to settle no longer has a question to answer. The
> paths (`src/rosy_core/...`, `src/rosy_gz_sim/...`) predate the D-125/D-126 layout and do not
> exist on `main`. Only the lesson was carried forward.
>
> Citations of the form `SHA^:path` are **git revision syntax, not working-tree paths** —
> they name a file as it stood *before* the fix, and are read with
> `git show 3593465^:src/rosy_core/rosy_core/docking/profile.py`. A path checker will flag
> them as missing; that is expected, because the content they quote is deliberately the
> version this document exists to explain the replacement of. Verified resolvable at the time
> of writing.
>
> Numbers below are marked either **re-derived** (run against the tree while writing this) or
> **as measured** (recorded by the session that made the change, and not re-run here).

## Context

The dock work on this branch is not a feature. It is a **measurement rig**: its job is to
decide, from recorded numbers rather than from anyone's opinion, which of three candidate
methods becomes the charging-dock detector. The geometric candidate is
`src/rosy_core/rosy_core/docking/profile.py` — deliberately ROS-free, taking a flat scan in
(`ranges`, `angle_min`, `angle_increment`) and returning a dock pose in `base_link`, so that
host pytest can see every decision it makes (`profile.py:39-40`).

The first version of its clustering rule cut the scan **only on angular gaps between
returns**, and said why in its own docstring. That docstring survives in git and is worth
reading verbatim, because it states the premise plainly (`3593465^:profile.py`, function
`_cluster_by_angular_gap`):

```
    """각도 간극으로만 자른다.

    기둥 사이는 광선이 아무것도 맞히지 않아 방위각이 그냥 건너뛴다. 그 간극에는
    거리 잡음이 없다. [...]
    """
    gap = 1.5 * abs(angle_increment)
```

("Cut on angular gaps only. Between the posts the rays hit nothing, so the bearing simply
skips. There is no range noise in that gap.") The elided sentence is the 398-of-400 result
that §4 treats at length — the pre-fix docstring already carried the dead end that produced it.

The premise is true of a dock standing in a void and false of a dock standing in a room. It
went unchallenged because the test suite was green — and the suite was green because its
scan builder emitted `math.inf` for every ray that missed a post. The fixture modelled a
world that cannot occur. The fix commit records fifteen tests passing; **re-derived**, the
file carried sixteen `def test` functions at `3593465^`, one of which had landed after the
probe was run. Either way, the whole suite was green and none of it could have objected.

Re-derived by importing the pre-fix `profile.py` out of git and raycasting a flat background
across every bearing:

| background behind the posts | pre-fix result |
|---|---|
| none (a void) | `found=True`, `clusters=3` |
| wall at 0.60 m | `found=False`, `clusters=1`, reason `expected 3 clusters, saw 1` |
| wall at 1.00 m | `found=False`, `clusters=1`, reason `expected 3 clusters, saw 1` |
| wall at 1.50 m | `found=True`, `clusters=3` — only because 1.50 m is outside `max_range_m` = 1.20 |

That reproduces the table the design document already recorded at
`docs/plans/2026-09-07-dock-detector-measurement-rig-design.md:179-184`.

**Why this was severe rather than merely wrong.** The code is an instrument. Shipped as
built, it would have reported a near-zero detection rate on hardware and in Gazebo, and the
project would have concluded that the *geometric candidate* failed. What had failed was the
clustering rule. An instrument calibrated against an impossible world returns a verdict
about itself while looking exactly like a verdict about the thing it measures — the design
document says this in as many words at `:187-188`, that the rig would have produced a
verdict about the clustering rule, not about the shape.

## Guidance

### 1. A fixture and its consumer written from one model are not two pieces of evidence

This is the whole lesson, and it is not about weak assertions. The assertions here were
strong, specific and correct: three clusters at pessimistic noise, pose recovered in
`base_link`, a plain wall refused, two visible posts refused, the residual gate separating a
noisy real dock from a wrong layout. Every one of them was a real claim about real behaviour.

They were all also **downstream of one belief** — that rays which miss a post return
nothing. The implementation held that belief in its clustering rule. The fixture held it in
its miss branch. Nothing in the suite came from outside the belief, so nothing in the suite
could contradict it. Sixteen agreeing tests were one belief expressed sixteen times.

The generalisation: **a synthetic input generator written by the same author, in the same
sitting, as the code that consumes it is not independent evidence.** It is a restatement.
The number of assertions you pile on top of it does not change that, because they all
inherit its world.

The helper now says so itself, which is the cheapest possible guard against the next reader
re-deriving the same premise (`src/rosy_core/test/test_dock_profile.py:45-53`):

```python
def _raycast(centres, radius, angle_min, step, count, sigma=0.0, seed=1,
             wall=None):
    """Ideal flat raycast against vertical cylinders, with optional background.

    `wall` puts a flat surface across every bearing at that distance. Without
    it the scene is a void, and a void is a scene that cannot happen in a
    room -- which is exactly how the angular-gap-only clustering rule went
    unchallenged for as long as it did.
    """
```

### 2. Break the loop with an input that comes from outside the model

Three things actually work, in rough order of strength: a recorded real input; a second
generator written to a different specification; an adversarial case someone else names. This
repo used the second, and it is worth being precise about **which loop it closes**.

`test/test_dock_shape_contract.py` builds its scan from geometry it parses out of the Gazebo
model file (`:27`, `_sdf_posts()` at `:42-56`) rather than from `DockProfile`. Its docstring
states the structural reason (`:8-10`): the unit tests' synthetic scans are all built from
`DockProfile`, so profile and test agree by construction, and this file is the only place
that closes the loop. It then asserts that the two artifacts describe the same posts
(`:122-131`), the same radius (`:134-141`), that every post crosses the 95 mm scan plane
(`:144-151`), and that the fit recovers a pose from the model's own geometry at four poses
(`:207-228`).

That the loop was real, and not decorative, is checkable: the layout and the model **did**
disagree by 20 mm on the middle post between commits `3593465` and `76efeb4`, and the fix
commit says so explicitly rather than papering over it — "The Gazebo dock SDF still stands
its three posts collinear at x = 0 and now disagrees with this profile by 20 mm."
`src/rosy_gz_sim/models/dock/model.sdf:39-46` now stands the middle post at `x = -0.020`,
and its comment at `:28-29` states that the value has to match `DockProfile.post_forward_m`
and the dock's mechanical drawing.

**And an agreement check can pass vacuously**, so the file carries a deliberate control:
`test_a_mirrored_middle_post_is_refused` (`:231-251`) flips only the sign of the middle
post's forward offset and requires the fit to refuse it, on the stated grounds that if a
mirrored layout is accepted then the agreement checks above prove nothing about the sign
convention. The margin is thin and the docstring says so. **Re-derived**: the mirrored
layout fits with residual 18.99 mm against an 18.0 mm gate (`profile.py:77`) — 0.99 mm of
margin. A fourth post is the known lever if that needs widening
(`test_dock_shape_contract.py:236-238`).

**Be honest about what this contract does not cover.** Its own raycast appends `math.inf`
for a missed ray (`:118`) and takes no background, so it models a void too. What it closes
is the *geometry-source* loop, not the *scene-realism* loop. The scene-realism loop was
closed separately, by tests that put something behind the posts (§3). Two fixtures that
disagree about the layout but share a ray model are independent on layout and dependent on
scene. Knowing which axis your second source is independent along is the difference between
a closed loop and a wider one.

### 3. Once the missing case is known, it becomes a test — including the constraint it creates

`test_a_wall_behind_the_posts_is_still_a_dock`
(`src/rosy_core/test/test_dock_profile.py:368-391`) walks walls at 0.60 / 0.80 / 1.00 /
1.19 m at two noise levels and requires `found=True`, the pose within 5 mm, and
`got.clusters > got.candidates` — the last assertion being the one that proves the wall is
still in the scene and being *filtered*, not merely absent.

The interesting sibling is `test_a_dock_pressed_against_its_background_cannot_be_separated`
(`:393-413`), which asserts a **mechanical** requirement rather than a software one: 55 cm of
wall behind a dock at 50 cm fails, 58 cm works. Its docstring gives the reason a test is the
right home for it — "The dock does not exist yet, so this is an input to its mechanical
design, and a test is the place it will not be forgotten." The same constraint is written
into the design document as a hard requirement at `:314-320`.

### 4. When a threshold fails inside the noise, fix the threshold — do not abandon the signal

This is the recorded dead end, and it is the reason the void-only version got written at all.

An earlier version clustered on **range** discontinuity with a ~30 mm threshold and lost
**398 of 400 fits** at the simulator's declared σ = 20 mm (*as measured*; the number is
preserved in the field comment at `profile.py:78-82` and in the design document at
`:131-132`). The conclusion drawn from that failure was "range is the wrong signal." The
correct conclusion was "30 mm sat inside the noise." Those two readings are one word apart
and lead to opposite designs — and the wrong one is what produced a rule that could only
work in a void.

The field comment now carries both readings so the next reader cannot re-derive the wrong
one (`profile.py:78-82`):

```
    #: 거리 단차로 클러스터를 자르는 임계. 선언 잡음 σ = 20 mm 의 4배다.
    #: 처음 판은 이것을 30 mm 로 두었고 σ = 20 mm 에서 400회 중 398회를
    #: 놓쳤다 — 30 mm 가 잡음 안에 있었기 때문이다. 거리를 버리는 것이 답이
    #: 아니라 임계를 잡음에 맞춰 키우는 것이 답이었다. 기종별로 조정한다.
    max_range_step_m: float = Field(default=0.080, gt=0.0)
```

("The threshold for splitting a cluster on a range step. Four times the declared noise
σ = 20 mm. The first version put it at 30 mm and lost 398 of 400 fits at σ = 20 mm —
because 30 mm was inside the noise. The answer was not to discard range, it was to scale the
threshold to the noise.")

### 5. Compare against the running aggregate, not the neighbour, when noise is the budget

Worth separating from §4 because it is the part that is easy to get right in the threshold
and wrong in the comparison. The step is measured against the running cluster mean rather
than the previous point (`profile.py:235-243`):

```python
    for previous, point in zip(points, points[1:]):
        mean_range = total / len(current)
        if point[0] - previous[0] > gap or abs(point[1] - mean_range) > step:
```

A point-to-point difference carries σ√2, so 80 mm would be only 2.8σ there; *as measured*,
5.5% of posts (22 of 400) split on noise alone, and the half-cluster's skewed bearing mean
was the dominant term in yaw RMS (2.8° → 4.2°) — `profile.py:218-223`. Against the mean the
noise is σ, 80 mm is a genuine 4σ, and the same threshold cuts the background while leaving
the posts intact.

### 6. A relaxed clustering rule forces the rejection rule to be relaxed with it

Splitting the background off produces **more** than three clusters, so the old
`len(clusters) != wanted` hard reject went from correct to fatal — it refused every scene
with anything in it. This is the second-order consequence, and it is the one that is easy to
miss when reviewing only the clustering diff. The comment at `profile.py:379-381` names it
as the actual identity of the wrong verdict the rig nearly produced.

The replacement is a cheap physical filter plus a bounded search:

- **Filter by angular width** (`_looks_like_a_post`, `:262-276`): a post of radius r at
  distance d subtends 2·asin(r/d); a wall segment subtends an order of magnitude more.
  Principled, and one arithmetic expression.
- **Cap the candidate count** at 12 (`_MAX_POST_CANDIDATES`, `:254-259`), because cost is
  cubic in candidates and a forward window holding more than twelve post-width objects is
  not a dock scene. Over the cap returns a reason, not a longer search (`:387-392`).
- **Search subsets for the lowest residual** (`:398-403`) instead of demanding an exact
  count.

`ProfileFit` grew a `candidates` field alongside `clusters` for this reason (`:147-149`):
with a background in the scene the two diverge, and the rig needs the one that diverged.

### 7. Say out loud when a software choice has become a hardware requirement

The range-step rule buys realistic scenes at the cost of a new physical constraint: the posts
must stand more than `max_range_step_m` (80 mm) in front of whatever is behind them at scan
height. `profile.py:225-228` states it in the docstring; the design document lists it
alongside the two other mechanical constraints at `:303-320` and marks it as the one that,
unlike the others, is **not absorbed by configuration** — lowering the threshold spends the
noise margin that made range clustering usable in the first place.

**Re-derived** at the simulator's angular step with a dock at 0.500 m and no noise:

| clearance behind posts | result |
|---|---|
| 60 mm | `found=False`, 3 clusters, 0 candidates |
| 65 mm | `found=False`, 3 clusters, 0 candidates |
| 70 mm | `found=False`, 6 clusters, 4 candidates |
| 75 mm | `found=True` |
| 80 mm and above | `found=True` |

which matches the design document's "65 mm fails, 80 mm works" (`:316-317`) and shows the
transition is a band, not a cliff — 80 mm is the specified value with margin, not the edge.

### 8. This repo already requires the next step: mutation-prove the new guard

`test/AGENTS.md:54` carries the rule, and it is the operative one for everything above:

> A new guard, gate or contract test is not believed until it has been **mutation-proven**:
> change the thing it guards, watch it go red, restore, watch it go green — and confirm the
> mutation actually landed before trusting the red. Assertions on source text are the easiest
> to write as tautologies, so mutate them harder, not less
> (`docs/solutions/workflow-issues/inability-to-check-recorded-as-clean-result.md`).

Note the relationship between that document and this one. That one is about a control that
*cannot fail*. This one is about a suite where **every control can fail and none of them can
be wrong**, because they were all derived from the premise under test. Mutation testing
catches the first. Only an outside input catches the second — mutate the clustering rule in
the pre-fix tree and the old suite dutifully goes red, having proved nothing about rooms.
Keep both rules; they cover different failures.

## Why This Matters

The severity here comes from what the code *is*, not from how wrong it was. Ordinary code
that mismodels the world produces bad behaviour, and bad behaviour eventually gets noticed.
An **instrument** that mismodels the world produces a *number*, and a number gets believed
and acted on.

- **The wrong artifact would have been blamed.** A near-zero detection rate reads as
  "geometric fitting is not good enough for this dock," and the rig exists precisely to
  answer that question. The cost of the defect is not a bug report; it is a candidate
  eliminated on false evidence, and the eliminating evidence looks like data.
- **The dock was still on paper, which is the only reason this was cheap.** The same defect
  found after the dock was fabricated would have arrived as a mechanical constraint — 80 mm
  of standoff at scan height — against a built part. The design document notes the freedom
  the missing hardware bought (`:43-47`).
- **The wrong lesson from a dead end costs more than the dead end.** 30 mm inside the noise
  cost one implementation. The mis-drawn conclusion "range is the wrong signal" cost the
  entire void-only design, its fifteen tests and the review cycle that caught it. A dead end
  is worth recording *with its correct reading attached*, or it will be re-entered from the
  other side.
- **Green is not neutral here.** In the tautological-assertion case documented in the sibling
  learning, the suite's green was produced by a broken control. In this case the green was
  produced by a *correct* suite asking the wrong world. That is harder to see, because
  nothing in the suite is wrong and nothing in it is mutable into red.
- **The `candidates`/`clusters` split is the shape of the whole problem in miniature.** Before
  the fix there was one number, and it was only unambiguous in a void. Anywhere real, "how
  many things are in the scene" and "how many could be posts" have different answers, and
  instrumentation that conflates them cannot report what happened.

## When to Apply

- **A test's inputs are generated by code that shares an author and a sitting with the code
  under test.** This is the default condition for most unit suites, so treat it as a standing
  question rather than an exception: name the premise the generator encodes, then ask what in
  the suite could contradict it.
- **A fixture has a "nothing here" branch** — `inf`, `NaN`, `None`, an empty list, a
  zero-filled buffer, a 404. Check whether the real world ever produces it. Sensor rays,
  database rows, API responses and message queues rarely return nothing; they return
  something you did not model.
- **You are building an instrument, benchmark, sweep, or evaluation harness.** Its errors come
  out as numbers about something else. Ask specifically: if this were miscalibrated, what
  would it look like? — then check whether that is what you are looking at.
- **A candidate is about to be eliminated on measured evidence.** Before accepting the
  elimination, confirm the measurement was not made in a world the candidate cannot exist in.
- **A threshold fails and you are about to change signals.** Establish whether the threshold
  was inside the noise floor of the signal you are abandoning. Scaling the threshold to
  measured noise (this repo uses 4σ) is often the whole fix.
- **A clustering, segmentation, or grouping rule is relaxed.** The downstream count check,
  exact-match, or cardinality assertion almost always has to be relaxed with it, and it will
  be in a different function from the diff you are reviewing.
- **A software threshold implies a physical clearance, tolerance, or timing margin.** Write it
  where the mechanical or ops decision is made, and hold it with a test — especially while the
  hardware does not exist yet and has no other place to remember it.
- **Two artifacts describe one shape** — a simulator model and a detector config, a schema and
  a migration, an SDK type and a wire format. A test that reads both and compares them is
  independent evidence in a way that a test reading one of them cannot be. Give it a
  deliberately wrong control case, or it can pass vacuously.

## Examples

### Clustering — before and after

**Before** (`3593465^:src/rosy_core/rosy_core/docking/profile.py`, `_cluster_by_angular_gap`).
One criterion, and a docstring asserting the premise as fact:

```python
    """각도 간극으로만 자른다.

    기둥 사이는 광선이 아무것도 맞히지 않아 방위각이 그냥 건너뛴다.
    """
    gap = 1.5 * abs(angle_increment)
    ...
        if point[0] - previous[0] > gap:
```

and downstream, an exact-count gate:

```python
    if len(clusters) != wanted:
        return ProfileFit(reason=f"expected {wanted} clusters, saw {len(clusters)}", ...)
```

**After** (`profile.py:230-245`, `:374-403`). Angular gap stays the primary criterion because
it carries no range noise; the range step is secondary, scaled to noise, and compared against
the running mean. The count gate is gone, replaced by a width filter, a cap, and a subset
search:

```python
    gap = _GAP_FACTOR * abs(angle_increment)
    step = profile.max_range_step_m
    ...
        mean_range = total / len(current)
        if point[0] - previous[0] > gap or abs(point[1] - mean_range) > step:
```

```python
    clusters = _cluster(points, angle_increment, profile)
    candidates = [cluster for cluster in clusters
                  if len(cluster) >= profile.min_points_per_post
                  and _looks_like_a_post(cluster, profile, angle_increment)]
    if len(candidates) < wanted:
        return ProfileFit(reason=f"only {len(candidates)} post-shaped clusters, need {wanted}", ...)
    if len(candidates) > _MAX_POST_CANDIDATES:
        return ProfileFit(reason=f"{len(candidates)} post-shaped clusters over the "
                                 f"{_MAX_POST_CANDIDATES} candidate cap", ...)
    ...
    for chosen in itertools.combinations(centres, wanted):
        attempt = _procrustes(model, chosen)
        if best is None or attempt[3] < best[3]:
            best = attempt
```

**Re-derived acquisition after the fix**, across two angular resolutions (Gazebo's 640-sample
step and the C1's 0.24 degrees), three noise levels (σ = 0, 3.5, 20 mm), five dock distances
(0.30–0.70 m) and three background clearances (100, 200, 400 mm) — 90 fits in total, single
seed:

| σ | fits | misses | worst pose error |
|---|---|---|---|
| 0 mm | 30 | 0 | 1.33 mm |
| 3.5 mm | 30 | 0 | 1.67 mm |
| 20 mm | 30 | 0 | 12.27 mm |

Acquisition is complete at every combination. The "within 1 mm" figure carried in this
session's summary reproduces only at zero noise (1.33 mm on this grid); at the simulator's
declared σ = 20 mm the worst error on the same grid is 12.3 mm. The in-tree test asserts 5 mm
at a dock distance of 0.500 m (`test_dock_profile.py:386-387`), which is the tighter, narrower
claim and the one actually held. Repeating the sweep at exactly 80 mm of clearance — the
specified minimum — does produce misses, which is the expected reading of a "more than 80 mm"
requirement rather than a contradiction of it.

### The fixture — before and after

**Before.** `_scan_of_posts` built a scene with nothing in it but posts, and every missed ray
became `math.inf`. It had no way to express a room.

**After.** `_raycast` takes an optional `wall` that fills every bearing at a given distance
(`test_dock_profile.py:45-77`), the `inf` branch survives but is now one scene among several
(`:72-73`), and the docstring names the void as the thing that let the bug live (`:49-52`).
The parameter threads through `_scan_of_posts` (`:79-88`), and three tests use it: the wall
behind the posts (`:368-391`), the dock pressed against its background (`:393-413`), and a
cluttered scene where six post-shaped candidates are normal and the subset search picks the
right three (`:415-436`).

### The outside source — a contract test that reads the simulator, not the config

**Before.** Nothing read `model.sdf`. The layout lived in `DockProfile` and in the SDF
independently, and they silently diverged by 20 mm on the middle post when the profile changed
(commits `3593465`, then `76efeb4` moved the model, then `5b9d6f7` added the contract).

**After.** `test/test_dock_shape_contract.py` parses the SDF and compares layouts (`:122-131`),
checks the radius the fit assumes (`:134-141`), checks that every post crosses the 95 mm scan
plane (`:144-151`), checks that the base plate stays *below* it (`:181-204`) — a box the
`post_` name filter had never looked at, and that would otherwise have put a 100 × 200 mm slab
exactly where the posts stand — and checks that each `post_*_collision` matches its own
`post_*_visual` (`:154-178`), because the simulator's `gpu_lidar` scans visuals and a
collision-only mutation is therefore invisible to every number the rig records. The vacuity
control is `:231-251`, refusing a mirrored middle post with a **re-derived** 0.99 mm of
residual margin. The row in `test/AGENTS.md:38` records what the file holds, so the next agent
does not have to rediscover that this is the only place the loop closes.

### What did not catch it

The fifteen-test suite, run repeatedly and green. Reading the clustering function, whose
docstring stated the premise clearly enough that a reader could agree with it. What caught it
was a code-quality review that **ran the code against a scene the fixture could not build** —
the same conclusion the sibling learning reaches from six unrelated defects: reading tells you
what the code says; only execution against an input from outside your own model tells you what
it does.

## Related

- `docs/solutions/workflow-issues/inability-to-check-recorded-as-clean-result.md` — the sibling
  shape and the corpus's other half. There, a control could not fail. Here, every control could
  fail and none could be wrong. Its §4 mutation rule is necessary and, for this defect,
  insufficient.
- `test/AGENTS.md:54` — the enforced copy of the mutation rule; `:38` — the Key Files row for
  `test_dock_shape_contract.py`, naming it as the shape-agreement contract.
- `docs/plans/2026-09-07-dock-detector-measurement-rig-design.md` — `:169-198` records the
  review that found this, with the wall table at `:179-184`; `:141-167` records the earlier
  estimator replacement (minimum range → chord mean) whose measured residual distributions set
  the 18 mm gate; `:303-320` lists the three mechanical constraints the posts impose, of which
  the 80 mm standoff is the one configuration cannot absorb; `:224-245` records the standing
  admission that three posts cannot reach zero false positives.
- `src/rosy_core/rosy_core/docking/profile.py:1-43` — the module docstring, which carries the
  measured shape-selection table and states plainly what the change does *not* achieve.
- `src/rosy_gz_sim/models/dock/model.sdf:16-29` — the other half of the shape, with the comment
  binding its 20 mm to `DockProfile.post_forward_m` and to the dock's mechanical drawing.
