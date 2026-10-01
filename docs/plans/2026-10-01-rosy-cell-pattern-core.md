# Rosy Cell Pattern Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Also follow the repo skill `rosy-land-on-main` (own worktree, path-exact `git add`, ADR numbering, `known_failures`).

**Goal:** Build the ROS-free core of Rosy Cell. It turns a taught cell config and a palletizing recipe into a validated, ordered Job (a list of `pick`/`place`/`pallet_done` Steps in the robot base frame).

**Architecture:** This is a new ament_python package `rosy_cell` at `src/site/cell`, the Application layer in D-399. It has small single-purpose modules:
- `geometry` — frames taught by three points
- `load` — box and pallet
- `pattern` — layer patterns and their checks
- `stack` — layers and slip sheets
- `sequence` — place order
- `recipe` and `cell` — YAML loaders with content hashes
- `compiler` — turns a recipe and cell into a Job

The package does no ROS, I/O, motion or IK. Reachability is the device's job (roadmap P3/P4).

**Tech Stack:** Python 3.12, PyYAML, pytest. Units are SI: metres, radians, kilograms.

**Parent:** [roadmap](2026-10-01-rosy-layered-architecture-roadmap.md) P1 (Rosy Cell ADR) and P2.

**Precondition:** D-399 is on local `main` (roadmap P0). Otherwise `adrs: [D-399]` fails harness lint (unknown ADR).

---

## Conventions used by every task

- Run every command from the worktree root, for example `F:\Dev\Control\Robot\ROS\Rosy\Rosy OS\.worktrees\rosy-cell-core`.
- Create the worktree once:

  ```bash
  git worktree add --relative-paths .worktrees/rosy-cell-core -b feat/rosy-cell-pattern-core main
  ```

- Tests: `python -m pytest src/site/cell/test -q -p no:cacheprovider`. Use `python`, not `python3`, on Windows.
- Pallet frame: the origin is a pallet corner, `+x` runs along the pallet length, `+y` along its width, and `+z` points up. A box placement is its centre `(x, y)` in that frame, plus the yaw of the box's long side (`0` or `pi/2`). `z_top` is the height of the box's top face, which is where the top-down gripper grasps.
- Validation thresholds (`tol_m`, `min_span_m`, `min_angle_deg`, `max_tilt_deg`, `approach_clearance_m`) are always passed in from config. Modules carry no hidden physical defaults; this is the repo's URDF-nominal and no-magic-number rule. The only literal is `_EPS = 1e-9`, which is float slack for `floor()` on exact fits.
- Commit after every task with exact paths. End each message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## File map

| File | Responsibility |
|---|---|
| `src/site/cell/package.xml`, `setup.py`, `setup.cfg`, `resource/rosy_cell` | ament_python package `rosy_cell` |
| `src/site/cell/AGENTS.md`, `progress.md`, `logs.md` | Module records (D-61 harness) |
| `src/site/cell/rosy_cell/__init__.py` | Package marker, `SCHEMA_RECIPE`, `SCHEMA_CELL` |
| `src/site/cell/rosy_cell/geometry.py` | `Frame` from three taught points, point and yaw transform, tilt |
| `src/site/cell/rosy_cell/load.py` | `Box`, `Pallet` value objects |
| `src/site/cell/rosy_cell/pattern.py` | `Placement`, `grid`, `best_grid`, `split_block`, `mirrored`, `layer_issues`, `PATTERNS` |
| `src/site/cell/rosy_cell/stack.py` | `LayerSpec`, `PlacedBox`, `SlipSheet`, `StackPlan`, `build_stack`, `stack_issues` |
| `src/site/cell/rosy_cell/sequence.py` | `APPROACHES`, `place_order` |
| `src/site/cell/rosy_cell/recipe.py` | `Recipe`, `PalletSlot`, `RecipeError`, `load_recipe` |
| `src/site/cell/rosy_cell/cell.py` | `Station`, `CellConfig`, `CellError`, `load_cell` |
| `src/site/cell/rosy_cell/compiler.py` | `Pose`, `Step`, `Job`, `CompileError`, `compile_job` |
| `src/site/cell/test/conftest.py` + `test_*.py` | Tests that run with no colcon install |
| `tools/harness/harness.yaml` | Register the module |
| `test/architecture/test_folder_package_names.py`, `test/architecture/test_target_layout.py` | Add `site/cell` rows |
| `docs/adr/D-<n>-rosy-cell-application.md`, `docs/reference/ROSY ADR Log.md` | Rosy Cell ADR (Proposed) |

---

### Task 1: Rosy Cell ADR (Proposed)

**Files:**
- Create: `docs/adr/D-<n>-rosy-cell-application.md`
- Modify: `docs/reference/ROSY ADR Log.md` (append one CRLF row; the file has no BOM)

- [ ] **Step 1: Pick the number.** Follow `rosy-land-on-main` "ADR numbers": `ls docs/adr` on main and every `.worktrees/*/docs/adr`, `git ls-tree` on all branches, Log rows, and `adr_gaps`. Take the next free number `<n>`.
- [ ] **Step 2: Write the ADR.** Use the D-399 header style (`## D-<n> …`, `**Status:** Proposed (…)`). Decision sections:
  1. Rosy Cell is a D-399 Application at `src/site/cell`, package `rosy_cell`, display name "Rosy Cell" (D-377).
  2. Two files. `cell.yaml` (schema `rosy_cell.cell/1`) holds taught three-point frames as raw points plus thresholds, stations, and `approach_clearance_m`. `recipe.yaml` (schema `rosy_cell.recipe/1`) holds box, pallets→frame ids, mode, approach side, gap, layers and slip sheet.
  3. Both files get a content hash (sha256 of canonical JSON). A Job records both hashes, and a device must refuse a Job whose cell hash is not the one it was validated against.
  4. A Job is an ordered list of Steps: `pick`, `place` (item `box` or `slip_sheet`, target pose in the robot base frame, `approach_z`) and `pallet_done`. Rosy Cell submits the Job to Fleet as a Mission; Fleet admits it (D-330) and dispatches the Steps to the device (D-336). Rosy Cell never calls the device directly, never sends a Motion Intent and never decides IK or reachability (D-399 §5).
  5. v1 patterns are `grid` (better of 0° and 90°), `split` (0° columns plus a 90° strip) and `mirrored` on any layer for interlock. Also in v1: slip sheets below any layer, several pallets filled in order, and depalletize (the exact reverse).
  6. Thresholds come from config, and geometry defaults come from URDF (D-397 rule).
  Add Alternatives (MoveIt Task Constructor in-app, ROBOTIS "task constructor tab", vendor palletizing UIs) and an Evidence boundary (SOURCE only). **Related decisions:** D-376, D-377, D-386, D-397, D-399.
- [ ] **Step 3: Append the Log row** with Python in binary mode, keeping CRLF:

```bash
python - <<'EOF'
p = "docs/reference/ROSY ADR Log.md"
b = open(p, "rb").read()
row = "| D-<n> | Rosy Cell 애플리케이션: 셀 설정·레시피 분리, 해시로 묶은 Job(Step 목록), 팔레타이징 패턴 v1 | Proposed |\r\n"
open(p, "wb").write(b + (b"" if b.endswith(b"\r\n") else b"\r\n") + row.encode("utf-8"))
EOF
```

- [ ] **Step 4: Lint.** Run `python tools/harness/rosy_harness.py lint`. Expected: `0 error(s)`.
- [ ] **Step 5: Commit**

```bash
git add "docs/adr/D-<n>-rosy-cell-application.md" "docs/reference/ROSY ADR Log.md"
git commit -m "docs(adr): D-<n> Rosy Cell application — cell/recipe split, hashed Job of Steps"
```

### Task 2: Package scaffold and registration

**Files:**
- Create: `src/site/cell/package.xml`, `src/site/cell/setup.py`, `src/site/cell/setup.cfg`, `src/site/cell/resource/rosy_cell` (empty), `src/site/cell/rosy_cell/__init__.py`, `src/site/cell/test/conftest.py`, `src/site/cell/test/test_cell_package.py`, `src/site/cell/AGENTS.md`, `src/site/cell/progress.md`, `src/site/cell/logs.md`
- Modify: `tools/harness/harness.yaml`, `test/architecture/test_folder_package_names.py`, `test/architecture/test_target_layout.py`

- [ ] **Step 1: Write the failing test** `src/site/cell/test/test_cell_package.py`

```python
from rosy_cell import SCHEMA_CELL, SCHEMA_RECIPE


def test_schema_ids_are_versioned():
    assert SCHEMA_RECIPE == "rosy_cell.recipe/1"
    assert SCHEMA_CELL == "rosy_cell.cell/1"
```

and `src/site/cell/test/conftest.py`

```python
"""colcon install 없이 pytest를 돌린다 (Windows/CI)."""

from __future__ import annotations

import sys
from pathlib import Path

CELL = Path(__file__).resolve().parents[1]
if str(CELL) not in sys.path:
    sys.path.insert(0, str(CELL))
```

- [ ] **Step 2: Run it.** `python -m pytest src/site/cell/test -q -p no:cacheprovider`. Expected: FAIL with `ModuleNotFoundError: No module named 'rosy_cell'`.
- [ ] **Step 3: Create the package files**

`src/site/cell/rosy_cell/__init__.py`

```python
"""Rosy Cell core: palletizing patterns, taught frames and Job compilation (ROS-free)."""

SCHEMA_RECIPE = "rosy_cell.recipe/1"
SCHEMA_CELL = "rosy_cell.cell/1"
```

`src/site/cell/package.xml`

```xml
<?xml version="1.0"?>
<?xml-model href="http://download.ros.org/schema/package_format3.xsd" schematypens="http://www.w3.org/2001/XMLSchema"?>
<package format="3">
  <name>rosy_cell</name>
  <version>0.1.0</version>
  <description>Rosy Cell: ROS-free palletizing recipes, taught cell frames and Job compilation (D-399 Application).</description>
  <maintainer email="56295815+livsbittt@users.noreply.github.com">ROSY</maintainer>
  <license>Apache-2.0</license>

  <buildtool_depend>ament_python</buildtool_depend>
  <exec_depend>python3-yaml</exec_depend>
  <test_depend>python3-pytest</test_depend>

  <export>
    <build_type>ament_python</build_type>
  </export>
</package>
```

`src/site/cell/setup.py`

```python
from setuptools import find_packages, setup

package_name = "rosy_cell"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
    ],
    install_requires=["setuptools", "PyYAML"],
    zip_safe=True,
    description="ROS-free palletizing recipes, taught cell frames and Job compilation.",
    license="Apache-2.0",
)
```

`src/site/cell/setup.cfg`

```ini
[develop]
script_dir=$base/lib/rosy_cell
[install]
install_scripts=$base/lib/rosy_cell
```

`src/site/cell/AGENTS.md`

```markdown
<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-01 | Updated: 2026-10-01 -->

# cell

## Purpose

Rosy Cell (D-377 id `cell`, package `rosy_cell`): the D-399 Application for palletizing and easy cell setup. ROS-free core that turns a taught cell config and a recipe into a hashed Job of `pick`/`place`/`pallet_done` Steps in the robot base frame. It never sends Motion Intents, solves IK, or judges reachability; the device's local owner does (D-376, D-399).

## Key Files

| File | Description |
|------|-------------|
| `package.xml` / `setup.py` / `setup.cfg` | ament_python, PyYAML only |
| `progress.md` | Gate snapshot (SOURCE…FIELD). Overwrite |
| `logs.md` | Append-only work journal |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `rosy_cell/` | `geometry`, `load`, `pattern`, `stack`, `sequence`, `recipe`, `cell`, `compiler` |
| `test/` | ROS-free pytest; `conftest.py` puts the package on `sys.path` |

## For AI Agents

### Working In This Directory

- Harness (D-61): read `progress.md` and `index.md` first; append `logs.md`; overwrite `progress.md` when a gate moves; run `python tools/harness/rosy_harness.py generate`.
- Units are SI (m, rad, kg). Thresholds are always passed in from config; do not add physical defaults in code.
- Pallet frame: origin at a pallet corner, +x along length, +y along width, +z up. `z_top` is the grasp height.

### Testing Requirements

```bash
python -m pytest src/site/cell/test -q
```
```

`src/site/cell/progress.md`

```markdown
---
module: rosy_cell
logical_modules: []
owner: SITE
last_verified: { commit: "uncommitted", date: 2026-10-01 }
gates:
  SOURCE:
    state: HOLD
    blocker: "core modules not yet implemented (plan docs/plans/2026-10-01-rosy-cell-pattern-core.md)"
    cmd: "python -m pytest src/site/cell/test -q"
  LOCAL:
    state: N/A
  ROS-SIM:
    state: HOLD
    blocker: "needs roadmap P3/P4 (MoveIt OMX-F Gazebo, device Step API)"
  ARTIFACT:
    state: N/A
  DEVICE:
    state: PARKED
  FIELD:
    state: PARKED
adrs: [D-399]
plans:
  - docs/plans/2026-10-01-rosy-layered-architecture-roadmap.md
  - docs/plans/2026-10-01-rosy-cell-pattern-core.md
---
```

`src/site/cell/logs.md`

```markdown
# rosy_cell logs

추가만 한다. 형식: [module harness 설계](../../../docs/plans/2026-09-15-module-harness-design.md) §4.2.

## 2026-10-01 · uncommitted · feat(cell): rosy_cell package scaffold

- 변경: ament_python 패키지 `rosy_cell`(`src/site/cell`), schema id 상수.
- 증거: `python -m pytest src/site/cell/test -q` 1 passed
- gate 변화: SOURCE HOLD 시작.
```

Add the ADR id from Task 1 to `adrs:` in `progress.md`.

- [ ] **Step 4: Register.** In `tools/harness/harness.yaml`, under `modules:`, right after the `rosy_vision` entry, add:

```yaml
  - name: rosy_cell
    path: src/site/cell
    tests: [src/site/cell/test]
    functional_kind: pytest
    functional: [src/site/cell/test]
```

In `test/architecture/test_folder_package_names.py`, add `"site/cell": "rosy_cell",` to `FOLDER_TO_PACKAGE`, next to `"site/vision"`. In `test/architecture/test_target_layout.py`, add `"site/cell": "site/cell",` to `TARGET`, next to `"site/vision": "site/vision"`.

In `.github/workflows/ci.yml`, right after the `Test (Rosy Vision receiver)` step, add:

```yaml
      # Rosy Cell 코어는 ROS·네트워크 없이 돈다(D-399 Application). 기본 이름 겹침이 없도록 따로 돈다.
      - name: Test (Rosy Cell core)
        run: python3 -m pytest src/site/cell/test -q
```

In `src/AGENTS.md`, make three edits: add `rosy_cell` to the ament_python list; change `site (Fleet, Rosy Vision, Rosy Cam, Games)` to `site (Fleet, Rosy Vision, Rosy Cell, Rosy Cam, Games)`; and add a row `| site/cell | rosy_cell (D-377 app rule rosy_<word>) |` under the `site/vision` row of the folder→package table. In `src/site/AGENTS.md`, add a row `| cell/ | ROS package rosy_cell (Rosy Cell, D-377, D-399 Application): palletizing recipes and taught cell frames compiled into a Job; submits to Fleet, never to a device |` under `vision/`.

Add these three files to the Step 6 `git add` line.

- [ ] **Step 5: Run the tests.**

```bash
python -m pytest src/site/cell/test -q -p no:cacheprovider
python -m pytest test/architecture -q -rfE -p no:cacheprovider > X:/DevTemp/rosy-cell-core/arch.txt
python test/known_failures.py X:/DevTemp/rosy-cell-core/arch.txt
python tools/harness/rosy_harness.py lint
```

Expected: `1 passed`, `known_failures.py` exit 0 (no NEW), lint `0 error(s)`. If `test_app_identity` or `test_module_structure` names `rosy_cell`, fix exactly what its message asks for (a missing row or record). Do not add it to any exception list.

- [ ] **Step 6: Generate and commit**

```bash
python tools/harness/rosy_harness.py generate
git status --short   # stage only the files listed in this task plus src/site/cell/index.md and STATUS.md if generate changed them
git add src/site/cell tools/harness/harness.yaml test/architecture/test_folder_package_names.py test/architecture/test_target_layout.py .github/workflows/ci.yml src/AGENTS.md src/site/AGENTS.md
git commit -m "feat(cell): rosy_cell ament_python scaffold and harness registration"
```

(`src/site/cell` is a new directory that holds only your files, so staging the directory is safe here.)

### Task 3: Taught frames (`geometry.py`)

**Files:** Create `src/site/cell/rosy_cell/geometry.py`, Test `src/site/cell/test/test_cell_frame.py`

- [ ] **Step 1: Write the failing test**

```python
import math

import pytest

from rosy_cell.geometry import Frame, FrameError

RULES = {"min_span_m": 0.02, "min_angle_deg": 10.0}


def _close(a, b, tol=1e-9):
    assert all(abs(x - y) < tol for x, y in zip(a, b)), (a, b)


def test_axis_aligned_points_give_the_identity_frame():
    f = Frame.from_three_points((0, 0, 0), (1, 0, 0), (0, 1, 0), **RULES)
    _close(f.to_base((0.1, 0.2, 0.3)), (0.1, 0.2, 0.3))
    assert f.yaw_to_base(0.3) == pytest.approx(0.3)
    assert f.tilt_deg() == pytest.approx(0.0)


def test_rotated_offset_frame_maps_points_and_yaw():
    f = Frame.from_three_points((1, 2, 0), (1, 3, 0), (0, 2, 0), **RULES)
    _close(f.to_base((0.5, 0.25, 0.0)), (0.75, 2.5, 0.0))
    assert f.yaw_to_base(0.0) == pytest.approx(math.pi / 2)


def test_plane_point_on_the_right_hand_side_points_z_down():
    f = Frame.from_three_points((0, 0, 0), (1, 0, 0), (0, -1, 0), **RULES)
    assert f.tilt_deg() == pytest.approx(180.0)


@pytest.mark.parametrize(
    "x_point, plane_point",
    [((0.01, 0, 0), (0, 1, 0)), ((1, 0, 0), (0, 0.01, 0)), ((1, 0, 0), (2, 0.05, 0))],
)
def test_degenerate_teaching_is_rejected(x_point, plane_point):
    with pytest.raises(FrameError):
        Frame.from_three_points((0, 0, 0), x_point, plane_point, **RULES)
```

- [ ] **Step 2: Run it.** `python -m pytest src/site/cell/test/test_cell_frame.py -q -p no:cacheprovider`. Expected: FAIL, `ModuleNotFoundError: No module named 'rosy_cell.geometry'`.
- [ ] **Step 3: Implement**

```python
"""Frames taught by three points: origin, a point on +x, a point on the +y side of the plane."""

from __future__ import annotations

import math
from dataclasses import dataclass

Vec3 = tuple[float, float, float]


class FrameError(ValueError):
    """The three taught points do not define a usable frame."""


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _length(a: Vec3) -> float:
    return math.sqrt(_dot(a, a))


def _unit(a: Vec3) -> Vec3:
    n = _length(a)
    return (a[0] / n, a[1] / n, a[2] / n)


@dataclass(frozen=True)
class Frame:
    origin: Vec3
    x_axis: Vec3
    y_axis: Vec3
    z_axis: Vec3

    @classmethod
    def from_three_points(
        cls, origin: Vec3, x_point: Vec3, plane_point: Vec3, *, min_span_m: float, min_angle_deg: float
    ) -> Frame:
        vx = _sub(x_point, origin)
        vp = _sub(plane_point, origin)
        if _length(vx) < min_span_m:
            raise FrameError("x_point is closer than min_span_m to the origin")
        if _length(vp) < min_span_m:
            raise FrameError("plane_point is closer than min_span_m to the origin")
        ex = _unit(vx)
        normal = _cross(ex, vp)
        if _length(normal) / _length(vp) < math.sin(math.radians(min_angle_deg)):
            raise FrameError("plane_point lies almost on the x axis")
        ez = _unit(normal)
        ey = _cross(ez, ex)
        return cls(origin=tuple(origin), x_axis=ex, y_axis=ey, z_axis=ez)

    def to_base(self, p: Vec3) -> Vec3:
        return tuple(
            self.origin[i] + self.x_axis[i] * p[0] + self.y_axis[i] * p[1] + self.z_axis[i] * p[2]
            for i in range(3)
        )

    def yaw_to_base(self, yaw: float) -> float:
        c, s = math.cos(yaw), math.sin(yaw)
        v = tuple(self.x_axis[i] * c + self.y_axis[i] * s for i in range(3))
        return math.atan2(v[1], v[0])

    def tilt_deg(self) -> float:
        return math.degrees(math.acos(max(-1.0, min(1.0, self.z_axis[2]))))
```

- [ ] **Step 4: Run it.** `python -m pytest src/site/cell/test -q -p no:cacheprovider`. Expected: `7 passed` (6 new).
- [ ] **Step 5: Commit.** `git add src/site/cell/rosy_cell/geometry.py src/site/cell/test/test_cell_frame.py`, then `git commit -m "feat(cell): three-point taught frame"`.

### Task 4: Box, pallet and grid patterns (`load.py`, `pattern.py`)

**Files:** Create `src/site/cell/rosy_cell/load.py`, `src/site/cell/rosy_cell/pattern.py`, Test `src/site/cell/test/test_pattern_grid.py`

- [ ] **Step 1: Write the failing test**

```python
import math

import pytest

from rosy_cell.load import Box, Pallet
from rosy_cell.pattern import best_grid, footprint, grid

BOX = Box(length=0.04, width=0.03, height=0.02, mass_kg=0.01)
PALLET = Pallet(length=0.12, width=0.09, max_stack_height=0.10, max_load_kg=1.0)


def test_box_and_pallet_reject_non_positive_sizes():
    with pytest.raises(ValueError):
        Box(length=0.0, width=0.03, height=0.02, mass_kg=0.01)
    with pytest.raises(ValueError):
        Pallet(length=0.12, width=0.09, max_stack_height=-1.0, max_load_kg=1.0)


def test_footprint_swaps_sides_at_ninety_degrees():
    assert footprint(BOX, 0.0) == (0.04, 0.03)
    assert footprint(BOX, math.pi / 2) == (0.03, 0.04)


def test_exact_fit_grid_counts_and_centres():
    layer = grid(BOX, PALLET, gap=0.0, yaw=0.0)
    assert len(layer) == 9
    assert (layer[0].x, layer[0].y) == pytest.approx((0.02, 0.015))
    assert len(grid(BOX, PALLET, gap=0.0, yaw=math.pi / 2)) == 8


def test_gap_reduces_count_and_block_is_centred():
    layer = grid(BOX, PALLET, gap=0.01, yaw=0.0)
    assert len(layer) == 4
    assert (layer[0].x, layer[0].y) == pytest.approx((0.035, 0.025))


def test_best_grid_picks_the_orientation_with_more_boxes():
    layer = best_grid(BOX, PALLET, gap=0.0)
    assert len(layer) == 9
    assert all(p.yaw == 0.0 for p in layer)
```

- [ ] **Step 2: Run it.** Expected: FAIL, `No module named 'rosy_cell.load'`.
- [ ] **Step 3: Implement** `load.py`

```python
"""Box and pallet value objects (SI units)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Box:
    length: float
    width: float
    height: float
    mass_kg: float

    def __post_init__(self) -> None:
        if min(self.length, self.width, self.height) <= 0 or self.mass_kg < 0:
            raise ValueError("box sizes must be positive and mass non-negative")


@dataclass(frozen=True)
class Pallet:
    length: float
    width: float
    max_stack_height: float
    max_load_kg: float

    def __post_init__(self) -> None:
        if min(self.length, self.width, self.max_stack_height) <= 0 or self.max_load_kg < 0:
            raise ValueError("pallet sizes must be positive and max load non-negative")
```

and `pattern.py`

```python
"""Single-layer placements in the pallet frame."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .load import Box, Pallet

_EPS = 1e-9  # float slack so exact fits are not floored away; not a physical tolerance


@dataclass(frozen=True)
class Placement:
    x: float
    y: float
    yaw: float


def footprint(box: Box, yaw: float) -> tuple[float, float]:
    """(extent along pallet x, extent along pallet y) for a box at yaw 0 or pi/2."""
    # yaw is 0 or pi/2 by contract; |sin| > 0.5 just tells the two apart without float equality
    return (box.width, box.length) if abs(math.sin(yaw)) > 0.5 else (box.length, box.width)


def _count(span: float, size: float, gap: float) -> int:
    return max(0, math.floor((span + gap) / (size + gap) + _EPS))


def _extent(n: int, size: float, gap: float) -> float:
    return n * size + max(0, n - 1) * gap


def _block(box: Box, yaw: float, nx: int, ny: int, gap: float, x0: float, y0: float) -> list[Placement]:
    dx, dy = footprint(box, yaw)
    return [
        Placement(x0 + i * (dx + gap) + dx / 2, y0 + j * (dy + gap) + dy / 2, yaw)
        for j in range(ny)
        for i in range(nx)
    ]


def grid(box: Box, pallet: Pallet, *, gap: float, yaw: float) -> list[Placement]:
    dx, dy = footprint(box, yaw)
    nx, ny = _count(pallet.length, dx, gap), _count(pallet.width, dy, gap)
    x0 = (pallet.length - _extent(nx, dx, gap)) / 2
    y0 = (pallet.width - _extent(ny, dy, gap)) / 2
    return _block(box, yaw, nx, ny, gap, x0, y0)


def best_grid(box: Box, pallet: Pallet, *, gap: float) -> list[Placement]:
    straight = grid(box, pallet, gap=gap, yaw=0.0)
    turned = grid(box, pallet, gap=gap, yaw=math.pi / 2)
    return turned if len(turned) > len(straight) else straight
```

- [ ] **Step 4: Run it.** `python -m pytest src/site/cell/test -q -p no:cacheprovider`. Expected: `12 passed` (5 new).
- [ ] **Step 5: Commit.** `git add src/site/cell/rosy_cell/load.py src/site/cell/rosy_cell/pattern.py src/site/cell/test/test_pattern_grid.py`, then `git commit -m "feat(cell): box/pallet and grid patterns"`.

### Task 5: Split block, mirror and layer checks (`pattern.py`)

**Files:** Modify `src/site/cell/rosy_cell/pattern.py`, Test `src/site/cell/test/test_pattern_split.py`

- [ ] **Step 1: Write the failing test**

```python
import math

import pytest

from rosy_cell.load import Box, Pallet
from rosy_cell.pattern import PATTERNS, Placement, best_grid, layer_issues, mirrored, split_block

BOX = Box(length=0.05, width=0.03, height=0.02, mass_kg=0.01)
PALLET = Pallet(length=0.11, width=0.10, max_stack_height=0.10, max_load_kg=1.0)
TOL = {"tol_m": 1e-6}


def test_split_beats_both_pure_grids():
    assert len(best_grid(BOX, PALLET, gap=0.0)) == 6
    layer = split_block(BOX, PALLET, gap=0.0)
    assert len(layer) == 7
    assert sum(1 for p in layer if p.yaw == 0.0) == 3
    assert sum(1 for p in layer if p.yaw == pytest.approx(math.pi / 2)) == 4
    assert layer_issues(layer, BOX, PALLET, **TOL) == []


def test_mirror_reflects_x_and_keeps_the_layer_valid():
    layer = split_block(BOX, PALLET, gap=0.0)
    flipped = mirrored(layer, PALLET)
    assert [round(p.x, 6) for p in flipped] == [round(0.11 - p.x, 6) for p in layer]
    assert layer_issues(flipped, BOX, PALLET, **TOL) == []


def test_overlap_and_overhang_are_reported():
    bad = [Placement(0.025, 0.015, 0.0), Placement(0.03, 0.015, 0.0), Placement(0.10, 0.015, 0.0)]
    issues = layer_issues(bad, BOX, PALLET, **TOL)
    assert "boxes 0 and 1 overlap" in issues
    assert "box 2 overhangs the pallet" in issues


def test_pattern_registry_names():
    assert set(PATTERNS) == {"grid", "split"}
```

- [ ] **Step 2: Run it.** Expected: FAIL, `ImportError: cannot import name 'PATTERNS'`.
- [ ] **Step 3: Append to `pattern.py`**

```python
def split_block(box: Box, pallet: Pallet, *, gap: float) -> list[Placement]:
    """0-degree columns from x=0, then 90-degree columns in the remaining strip; the best split wins."""
    dx0, dy0 = footprint(box, 0.0)
    dx1, dy1 = footprint(box, math.pi / 2)
    ny0, ny1 = _count(pallet.width, dy0, gap), _count(pallet.width, dy1, gap)
    best: tuple[int, int, int] | None = None
    for k in range(_count(pallet.length, dx0, gap) + 1):
        m = _count(pallet.length - k * (dx0 + gap), dx1, gap)
        total = k * ny0 + m * ny1
        if best is None or total > best[0]:
            best = (total, k, m)
    _, k, m = best
    joint = gap if k and m else 0.0
    length_a = _extent(k, dx0, gap)
    x0 = (pallet.length - (length_a + joint + _extent(m, dx1, gap))) / 2
    first = _block(box, 0.0, k, ny0, gap, x0, (pallet.width - _extent(ny0, dy0, gap)) / 2)
    second = _block(
        box, math.pi / 2, m, ny1, gap, x0 + length_a + joint, (pallet.width - _extent(ny1, dy1, gap)) / 2
    )
    return first + second


def mirrored(placements: list[Placement], pallet: Pallet) -> list[Placement]:
    """Reflect across the pallet's mid-length line (interlock with the layer below)."""
    return [Placement(pallet.length - p.x, p.y, p.yaw) for p in placements]


def layer_issues(placements: list[Placement], box: Box, pallet: Pallet, *, tol_m: float) -> list[str]:
    issues: list[str] = []
    rects = []
    for i, p in enumerate(placements):
        dx, dy = footprint(box, p.yaw)
        r = (p.x - dx / 2, p.y - dy / 2, p.x + dx / 2, p.y + dy / 2)
        if r[0] < -tol_m or r[1] < -tol_m or r[2] > pallet.length + tol_m or r[3] > pallet.width + tol_m:
            issues.append(f"box {i} overhangs the pallet")
        rects.append(r)
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            a, b = rects[i], rects[j]
            if min(a[2], b[2]) - max(a[0], b[0]) > tol_m and min(a[3], b[3]) - max(a[1], b[1]) > tol_m:
                issues.append(f"boxes {i} and {j} overlap")
    return issues


PATTERNS = {"grid": best_grid, "split": split_block}
```

- [ ] **Step 4: Run it.** `python -m pytest src/site/cell/test -q -p no:cacheprovider`. Expected: `16 passed` (4 new).
- [ ] **Step 5: Commit.** `git add src/site/cell/rosy_cell/pattern.py src/site/cell/test/test_pattern_split.py`, then `git commit -m "feat(cell): split-block pattern, mirror interlock, layer checks"`.

### Task 6: Stack and slip sheets (`stack.py`)

**Files:** Create `src/site/cell/rosy_cell/stack.py`, Test `src/site/cell/test/test_stack.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest

from rosy_cell.load import Box, Pallet
from rosy_cell.stack import LayerSpec, build_stack, stack_issues

BOX = Box(length=0.05, width=0.03, height=0.02, mass_kg=0.01)
PALLET = Pallet(length=0.11, width=0.10, max_stack_height=0.05, max_load_kg=1.0)
LAYERS = [LayerSpec("split"), LayerSpec("split", mirrored=True, slip_sheet_below=True)]


def test_two_layers_with_a_slip_sheet():
    plan = build_stack(BOX, PALLET, LAYERS, gap=0.0, slip_sheet_thickness=0.002)
    assert [len(layer) for layer in plan.layers] == [7, 7]
    assert plan.layers[0][0].z_top == pytest.approx(0.02)
    assert plan.slip_sheets[0].below_layer == 1
    assert plan.slip_sheets[0].z == pytest.approx(0.022)
    assert plan.layers[1][0].z_top == pytest.approx(0.042)
    assert plan.height == pytest.approx(0.042)
    assert plan.mass_kg == pytest.approx(0.14)
    assert stack_issues(plan, BOX, PALLET, tol_m=1e-6) == []


def test_height_load_and_empty_layer_are_reported():
    low = Pallet(length=0.11, width=0.10, max_stack_height=0.04, max_load_kg=0.1)
    plan = build_stack(BOX, low, LAYERS, gap=0.0, slip_sheet_thickness=0.002)
    issues = stack_issues(plan, BOX, low, tol_m=1e-6)
    assert any(i.startswith("stack height") for i in issues)
    assert any(i.startswith("stack mass") for i in issues)
    tiny = Pallet(length=0.01, width=0.01, max_stack_height=0.05, max_load_kg=1.0)
    empty = build_stack(BOX, tiny, [LayerSpec("grid")], gap=0.0, slip_sheet_thickness=0.002)
    assert "layer 0 is empty" in stack_issues(empty, BOX, tiny, tol_m=1e-6)


def test_unknown_pattern_is_rejected():
    with pytest.raises(ValueError, match="unknown pattern"):
        build_stack(BOX, PALLET, [LayerSpec("pinwheel")], gap=0.0, slip_sheet_thickness=0.002)
```

- [ ] **Step 2: Run it.** Expected: FAIL, `No module named 'rosy_cell.stack'`.
- [ ] **Step 3: Implement**

```python
"""Layers stacked on one pallet, with optional slip sheets."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .load import Box, Pallet
from .pattern import PATTERNS, Placement, layer_issues, mirrored


@dataclass(frozen=True)
class LayerSpec:
    pattern: str
    mirrored: bool = False
    slip_sheet_below: bool = False


@dataclass(frozen=True)
class PlacedBox:
    layer: int
    x: float
    y: float
    z_top: float
    yaw: float


@dataclass(frozen=True)
class SlipSheet:
    below_layer: int
    z: float  # top surface of the sheet


@dataclass(frozen=True)
class StackPlan:
    layers: tuple[tuple[PlacedBox, ...], ...]
    slip_sheets: tuple[SlipSheet, ...]
    height: float
    mass_kg: float


def build_stack(
    box: Box, pallet: Pallet, layers: Sequence[LayerSpec], *, gap: float, slip_sheet_thickness: float
) -> StackPlan:
    z = 0.0
    out: list[tuple[PlacedBox, ...]] = []
    sheets: list[SlipSheet] = []
    for n, spec in enumerate(layers):
        try:
            make = PATTERNS[spec.pattern]
        except KeyError:
            raise ValueError(f"unknown pattern {spec.pattern!r}") from None
        placements = make(box, pallet, gap=gap)
        if spec.mirrored:
            placements = mirrored(placements, pallet)
        if spec.slip_sheet_below:
            z += slip_sheet_thickness
            sheets.append(SlipSheet(n, z))
        z += box.height
        out.append(tuple(PlacedBox(n, p.x, p.y, z, p.yaw) for p in placements))
    count = sum(len(layer) for layer in out)
    return StackPlan(tuple(out), tuple(sheets), z, count * box.mass_kg)


def stack_issues(plan: StackPlan, box: Box, pallet: Pallet, *, tol_m: float) -> list[str]:
    issues: list[str] = []
    if plan.height > pallet.max_stack_height + tol_m:
        issues.append(f"stack height {plan.height:.3f} m exceeds {pallet.max_stack_height:.3f} m")
    if plan.mass_kg > pallet.max_load_kg:
        issues.append(f"stack mass {plan.mass_kg:.3f} kg exceeds {pallet.max_load_kg:.3f} kg")
    for n, layer in enumerate(plan.layers):
        if not layer:
            issues.append(f"layer {n} is empty")
            continue
        placements = [Placement(b.x, b.y, b.yaw) for b in layer]
        issues += [f"layer {n}: {msg}" for msg in layer_issues(placements, box, pallet, tol_m=tol_m)]
    return issues
```

- [ ] **Step 4: Run it.** `python -m pytest src/site/cell/test -q -p no:cacheprovider`. Expected: `19 passed` (3 new).
- [ ] **Step 5: Commit.** `git add src/site/cell/rosy_cell/stack.py src/site/cell/test/test_stack.py`, then `git commit -m "feat(cell): layer stack with slip sheets and stack checks"`.

### Task 7: Place order (`sequence.py`)

**Files:** Create `src/site/cell/rosy_cell/sequence.py`, Test `src/site/cell/test/test_sequence.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest

from rosy_cell.stack import PlacedBox
from rosy_cell.sequence import APPROACHES, place_order

LAYER = (
    PlacedBox(0, 0.095, 0.075, 0.02, 0.0),
    PlacedBox(0, 0.025, 0.050, 0.02, 0.0),
    PlacedBox(0, 0.025, 0.020, 0.02, 0.0),
    PlacedBox(0, 0.065, 0.025, 0.02, 0.0),
)


def test_far_side_first_for_each_approach():
    assert [(b.x, b.y) for b in place_order(LAYER, approach="+x")][:2] == [(0.025, 0.020), (0.025, 0.050)]
    assert place_order(LAYER, approach="-x")[0].x == 0.095
    assert place_order(LAYER, approach="+y")[0].y == 0.020
    assert place_order(LAYER, approach="-y")[0].y == 0.075


def test_unknown_approach_is_rejected():
    assert set(APPROACHES) == {"+x", "-x", "+y", "-y"}
    with pytest.raises(ValueError):
        place_order(LAYER, approach="up")
```

- [ ] **Step 2: Run it.** Expected: FAIL, `No module named 'rosy_cell.sequence'`.
- [ ] **Step 3: Implement**

```python
"""Order inside one layer: boxes far from the robot go first so the gripper never reaches over a placed box.

`approach` names the pallet side the robot reaches in from. A robot on the +x side reaches
toward -x, so the far side is the smallest x.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from .stack import PlacedBox

APPROACHES: dict[str, Callable[[PlacedBox], tuple[float, float]]] = {
    "+x": lambda b: (b.x, b.y),
    "-x": lambda b: (-b.x, b.y),
    "+y": lambda b: (b.y, b.x),
    "-y": lambda b: (-b.y, b.x),
}


def place_order(layer: Sequence[PlacedBox], *, approach: str) -> tuple[PlacedBox, ...]:
    try:
        key = APPROACHES[approach]
    except KeyError:
        raise ValueError(f"unknown approach {approach!r}") from None
    return tuple(sorted(layer, key=key))
```

- [ ] **Step 4: Run it.** `python -m pytest src/site/cell/test -q -p no:cacheprovider`. Expected: `21 passed` (2 new).
- [ ] **Step 5: Commit.** `git add src/site/cell/rosy_cell/sequence.py src/site/cell/test/test_sequence.py`, then `git commit -m "feat(cell): far-side-first place order"`.

### Task 8: Recipe loader (`recipe.py`)

**Files:** Create `src/site/cell/rosy_cell/recipe.py`, `src/site/cell/test/fixtures/recipe_two_layer.yaml`, Test `src/site/cell/test/test_recipe.py`

- [ ] **Step 1: Write the fixture and failing test**

`src/site/cell/test/fixtures/recipe_two_layer.yaml`

```yaml
schema: rosy_cell.recipe/1
name: foam-blocks-two-layer
mode: palletize
box: {length: 0.05, width: 0.03, height: 0.02, mass_kg: 0.01}
pallets:
  - {id: A, frame: pallet_a, length: 0.11, width: 0.10, max_stack_height: 0.05, max_load_kg: 1.0}
  - {id: B, frame: pallet_b, length: 0.11, width: 0.10, max_stack_height: 0.05, max_load_kg: 1.0}
pick_station: infeed
approach: "+x"
gap: 0.0
slip_sheet: {thickness: 0.002, station: sheets}
layers:
  - {pattern: split}
  - {pattern: split, mirrored: true, slip_sheet_below: true}
```

`src/site/cell/test/test_recipe.py`

```python
from pathlib import Path

import pytest

from rosy_cell.recipe import RecipeError, load_recipe

FIXTURE = Path(__file__).parent / "fixtures" / "recipe_two_layer.yaml"


def test_fixture_loads_with_a_stable_hash():
    text = FIXTURE.read_text(encoding="utf-8")
    recipe = load_recipe(text)
    assert recipe.mode == "palletize"
    assert [slot.id for slot in recipe.pallets] == ["A", "B"]
    assert recipe.layers[1].mirrored and recipe.layers[1].slip_sheet_below
    assert recipe.slip_sheet_station == "sheets"
    assert len(recipe.content_hash) == 64
    reordered = text.replace("mode: palletize\n", "") + "mode: palletize\n"
    assert load_recipe(reordered).content_hash == recipe.content_hash


@pytest.mark.parametrize(
    "old, new, problem",
    [
        ("rosy_cell.recipe/1", "rosy_cell.recipe/0", "schema"),
        ("mode: palletize", "mode: stack", "mode"),
        ('approach: "+x"', 'approach: "up"', "approach"),
        ("{pattern: split}", "{pattern: pinwheel}", "pattern"),
        ("id: B", "id: A", "duplicate pallet id"),
        ("slip_sheet: {thickness: 0.002, station: sheets}\n", "", "slip_sheet"),
        ("length: 0.05", "length: -0.05", "invalid recipe field"),
    ],
)
def test_bad_recipes_name_the_problem(old, new, problem):
    text = FIXTURE.read_text(encoding="utf-8").replace(old, new, 1)
    with pytest.raises(RecipeError) as err:
        load_recipe(text)
    assert any(problem in p for p in err.value.problems), err.value.problems
```

- [ ] **Step 2: Run it.** Expected: FAIL, `No module named 'rosy_cell.recipe'`.
- [ ] **Step 3: Implement**

```python
"""recipe.yaml (schema rosy_cell.recipe/1) -> Recipe, with a content hash."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

import yaml

from . import SCHEMA_RECIPE
from .load import Box, Pallet
from .pattern import PATTERNS
from .sequence import APPROACHES
from .stack import LayerSpec

MODES = ("palletize", "depalletize")


class RecipeError(ValueError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = tuple(problems)


@dataclass(frozen=True)
class PalletSlot:
    id: str
    frame: str
    pallet: Pallet


@dataclass(frozen=True)
class Recipe:
    name: str
    mode: str
    box: Box
    pallets: tuple[PalletSlot, ...]
    pick_station: str
    approach: str
    gap: float
    slip_sheet_thickness: float | None
    slip_sheet_station: str | None
    layers: tuple[LayerSpec, ...]
    content_hash: str


def content_hash(data: object) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def load_recipe(text: str) -> Recipe:
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise RecipeError(["recipe must be a mapping"])
    try:
        box = Box(**data["box"])
        pallets = tuple(
            PalletSlot(
                str(p["id"]),
                str(p["frame"]),
                Pallet(p["length"], p["width"], p["max_stack_height"], p["max_load_kg"]),
            )
            for p in data["pallets"]
        )
        layers = tuple(LayerSpec(**layer) for layer in data["layers"])
        sheet = data.get("slip_sheet")
        recipe = Recipe(
            name=str(data["name"]),
            mode=data["mode"],
            box=box,
            pallets=pallets,
            pick_station=str(data["pick_station"]),
            approach=data["approach"],
            gap=float(data["gap"]),
            slip_sheet_thickness=float(sheet["thickness"]) if sheet else None,
            slip_sheet_station=str(sheet["station"]) if sheet else None,
            layers=layers,
            content_hash=content_hash(data),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RecipeError([f"invalid recipe field: {exc}"]) from None

    problems: list[str] = []
    if data.get("schema") != SCHEMA_RECIPE:
        problems.append(f"schema must be {SCHEMA_RECIPE}")
    if recipe.mode not in MODES:
        problems.append(f"mode must be one of {MODES}")
    if recipe.approach not in APPROACHES:
        problems.append(f"approach must be one of {sorted(APPROACHES)}")
    if not recipe.pallets:
        problems.append("at least one pallet is required")
    ids = [slot.id for slot in recipe.pallets]
    problems += [f"duplicate pallet id {i!r}" for i in sorted({i for i in ids if ids.count(i) > 1})]
    if not recipe.layers:
        problems.append("at least one layer is required")
    problems += [f"unknown pattern {s.pattern!r}" for s in recipe.layers if s.pattern not in PATTERNS]
    if any(s.slip_sheet_below for s in recipe.layers) and recipe.slip_sheet_station is None:
        problems.append("slip_sheet (thickness, station) is required when a layer has slip_sheet_below")
    if recipe.gap < 0:
        problems.append("gap must be non-negative")
    if problems:
        raise RecipeError(problems)
    return recipe
```

- [ ] **Step 4: Run it.** `python -m pytest src/site/cell/test -q -p no:cacheprovider`. Expected: `29 passed` (8 new).
- [ ] **Step 5: Commit.** `git add src/site/cell/rosy_cell/recipe.py src/site/cell/test/test_recipe.py src/site/cell/test/fixtures/recipe_two_layer.yaml`, then `git commit -m "feat(cell): recipe loader with schema checks and content hash"`.

### Task 9: Cell config loader (`cell.py`)

**Files:** Create `src/site/cell/rosy_cell/cell.py`, `src/site/cell/test/fixtures/cell_demo.yaml`, Test `src/site/cell/test/test_cell.py`

- [ ] **Step 1: Write the fixture and failing test**

`src/site/cell/test/fixtures/cell_demo.yaml`

```yaml
schema: rosy_cell.cell/1
frame_rules: {min_span_m: 0.02, min_angle_deg: 10.0, max_tilt_deg: 5.0}
frames:
  base: {origin: [0, 0, 0], x_point: [0.1, 0, 0], plane_point: [0, 0.1, 0]}
  pallet_a: {origin: [0.2, 0, 0], x_point: [0.3, 0, 0], plane_point: [0.2, 0.1, 0]}
  pallet_b: {origin: [0.2, -0.15, 0], x_point: [0.3, -0.15, 0], plane_point: [0.2, -0.05, 0]}
stations:
  infeed: {frame: base, x: 0.0, y: 0.2, z: 0.02, yaw: 0.0}
  sheets: {frame: base, x: -0.1, y: 0.2, z: 0.002, yaw: 0.0}
approach_clearance_m: 0.05
```

`src/site/cell/test/test_cell.py`

```python
from pathlib import Path

import pytest

from rosy_cell.cell import CellError, load_cell

FIXTURE = Path(__file__).parent / "fixtures" / "cell_demo.yaml"


def test_fixture_builds_frames_and_stations():
    cell = load_cell(FIXTURE.read_text(encoding="utf-8"))
    assert cell.frames["pallet_a"].to_base((0.0, 0.0, 0.0)) == pytest.approx((0.2, 0.0, 0.0))
    assert cell.station_pose("infeed") == pytest.approx((0.0, 0.2, 0.02, 0.0))
    assert cell.approach_clearance_m == 0.05
    assert len(cell.content_hash) == 64


@pytest.mark.parametrize(
    "old, new, problem",
    [
        ("rosy_cell.cell/1", "rosy_cell.cell/9", "schema"),
        ("plane_point: [0.2, 0.1, 0]", "plane_point: [0.2, 0.1, 0.05]", "tilt"),
        ("x_point: [0.3, 0, 0]", "x_point: [0.205, 0, 0]", "pallet_a"),
        ("{frame: base, x: 0.0", "{frame: nowhere, x: 0.0", "unknown frame"),
        ("approach_clearance_m: 0.05", "approach_clearance_m: 0", "approach_clearance_m"),
    ],
)
def test_bad_cells_name_the_problem(old, new, problem):
    text = FIXTURE.read_text(encoding="utf-8").replace(old, new, 1)
    with pytest.raises(CellError) as err:
        load_cell(text)
    assert any(problem in p for p in err.value.problems), err.value.problems
```

(The tilt case: plane point raised 0.05 m over 0.1 m tilts z by about 26.6°, which is more than 5°.)

- [ ] **Step 2: Run it.** Expected: FAIL, `No module named 'rosy_cell.cell'`.
- [ ] **Step 3: Implement**

```python
"""cell.yaml (schema rosy_cell.cell/1) -> CellConfig. Frames are kept as taught points and rebuilt here."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import yaml

from . import SCHEMA_CELL
from .geometry import Frame, FrameError
from .recipe import content_hash


class CellError(ValueError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = tuple(problems)


@dataclass(frozen=True)
class Station:
    frame: str
    x: float
    y: float
    z: float
    yaw: float


@dataclass(frozen=True)
class CellConfig:
    frames: Mapping[str, Frame]
    stations: Mapping[str, Station]
    approach_clearance_m: float
    content_hash: str

    def station_pose(self, station_id: str) -> tuple[float, float, float, float]:
        s = self.stations[station_id]
        frame = self.frames[s.frame]
        x, y, z = frame.to_base((s.x, s.y, s.z))
        return (x, y, z, frame.yaw_to_base(s.yaw))


def load_cell(text: str) -> CellConfig:
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise CellError(["cell config must be a mapping"])
    problems: list[str] = []
    if data.get("schema") != SCHEMA_CELL:
        problems.append(f"schema must be {SCHEMA_CELL}")
    try:
        rules = data["frame_rules"]
        frames: dict[str, Frame] = {}
        for frame_id, pts in data["frames"].items():
            try:
                frame = Frame.from_three_points(
                    tuple(pts["origin"]),
                    tuple(pts["x_point"]),
                    tuple(pts["plane_point"]),
                    min_span_m=float(rules["min_span_m"]),
                    min_angle_deg=float(rules["min_angle_deg"]),
                )
            except FrameError as exc:
                problems.append(f"frame {frame_id}: {exc}")
                continue
            if frame.tilt_deg() > float(rules["max_tilt_deg"]):
                problems.append(f"frame {frame_id}: tilt {frame.tilt_deg():.1f} deg exceeds max_tilt_deg")
            frames[str(frame_id)] = frame
        stations = {str(k): Station(**v) for k, v in data["stations"].items()}
        clearance = float(data["approach_clearance_m"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CellError(problems + [f"invalid cell field: {exc}"]) from None
    problems += [
        f"station {k}: unknown frame {s.frame!r}"
        for k, s in stations.items()
        if s.frame not in frames and s.frame not in data["frames"]
    ]
    if clearance <= 0:
        problems.append("approach_clearance_m must be positive")
    if problems:
        raise CellError(problems)
    return CellConfig(frames, stations, clearance, content_hash(data))
```

- [ ] **Step 4: Run it.** `python -m pytest src/site/cell/test -q -p no:cacheprovider`. Expected: `35 passed` (6 new).
- [ ] **Step 5: Commit.** `git add src/site/cell/rosy_cell/cell.py src/site/cell/test/test_cell.py src/site/cell/test/fixtures/cell_demo.yaml`, then `git commit -m "feat(cell): cell config loader with three-point frames and tilt check"`.

### Task 10: Job compiler (`compiler.py`)

**Files:** Create `src/site/cell/rosy_cell/compiler.py`, Test `src/site/cell/test/test_compiler.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

import pytest

from rosy_cell.cell import load_cell
from rosy_cell.compiler import CompileError, compile_job
from rosy_cell.recipe import load_recipe

FIX = Path(__file__).parent / "fixtures"
TOL = {"tol_m": 1e-6}


def _inputs(recipe_edit=("", ""), cell_edit=("", "")):
    recipe = (FIX / "recipe_two_layer.yaml").read_text(encoding="utf-8").replace(*recipe_edit, 1)
    cell = (FIX / "cell_demo.yaml").read_text(encoding="utf-8").replace(*cell_edit, 1)
    return load_recipe(recipe), load_cell(cell)


def test_palletize_job_shape_and_first_place():
    recipe, cell = _inputs()
    job = compile_job(recipe, cell, **TOL)
    assert job.recipe_hash == recipe.content_hash and job.cell_hash == cell.content_hash
    # per pallet: 7 boxes x (pick, place) + 1 sheet x (pick, place) + 7 x 2 + pallet_done = 31
    assert len(job.steps) == 62
    first_pick, first_place = job.steps[0], job.steps[1]
    assert (first_pick.kind, first_pick.item, first_pick.target.y) == ("pick", "box", pytest.approx(0.2))
    assert first_place.kind == "place" and first_place.pallet == "A" and first_place.layer == 0
    assert (first_place.target.x, first_place.target.y, first_place.target.z) == pytest.approx((0.225, 0.02, 0.02))
    assert first_place.approach_z == pytest.approx(0.07)
    sheet_place = job.steps[15]
    assert (sheet_place.item, sheet_place.target.z) == ("slip_sheet", pytest.approx(0.022))
    assert (sheet_place.target.x, sheet_place.target.y) == pytest.approx((0.255, 0.05))
    assert job.steps[30].kind == "pallet_done" and job.steps[30].pallet == "A"
    assert job.steps[32].target.y == pytest.approx(-0.15 + 0.02)


def test_depalletize_is_the_reverse_of_palletize():
    recipe, cell = _inputs(recipe_edit=("mode: palletize", "mode: depalletize"))
    job = compile_job(recipe, cell, **TOL)
    assert len(job.steps) == 62
    first = job.steps[0]
    assert (first.kind, first.item, first.layer) == ("pick", "box", 1)
    assert (first.target.x, first.target.y, first.target.z) == pytest.approx((0.285, 0.08, 0.042))
    assert job.steps[1].target.y == pytest.approx(0.2)
    assert (job.steps[14].item, job.steps[14].kind) == ("slip_sheet", "pick")


def test_compile_refuses_missing_frame_station_and_tall_stack():
    recipe, cell = _inputs(recipe_edit=("frame: pallet_b", "frame: pallet_c"))
    with pytest.raises(CompileError, match="pallet_c"):
        compile_job(recipe, cell, **TOL)
    recipe, cell = _inputs(recipe_edit=("pick_station: infeed", "pick_station: dock"))
    with pytest.raises(CompileError, match="dock"):
        compile_job(recipe, cell, **TOL)
    recipe, cell = _inputs(recipe_edit=("max_stack_height: 0.05", "max_stack_height: 0.03"))
    with pytest.raises(CompileError, match="pallet A: stack height"):
        compile_job(recipe, cell, **TOL)
```

Check the expected numbers:
- Layer 0 boxes in `+x` order start at pallet `(0.025, 0.02)`. `pallet_a` has origin `(0.2, 0, 0)` with identity axes, so that is base `(0.225, 0.02)` with `z_top` 0.02, and approach is 0.02 + 0.05.
- The sheet is step index 14 (pick) and 15 (place), at the pallet centre `(0.055, 0.05)`, which is base `(0.255, 0.05)`, `z` 0.022.
- Pallet A uses steps 0–30. Pallet B's first place, step 32, is at y = −0.15 + 0.02.
- Depalletize starts with the last box of layer 1 in `+x` order. The mirrored layer has its 0° column at x = 0.085 with y 0.02/0.05/0.08, so the last is `(0.085, 0.08)`, base `(0.285, 0.08)`, `z` 0.042.
- Depalletize removes layer 1's 7 boxes first (steps 0–13). The sheet sits below layer 1, so its removal comes next (steps 14–15), and layer 0's boxes follow (steps 16–29).

- [ ] **Step 2: Run it.** Expected: FAIL, `No module named 'rosy_cell.compiler'`.
- [ ] **Step 3: Implement**

```python
"""Recipe + cell config -> Job: ordered pick/place Steps in the robot base frame.

Rosy Cell submits the Job to Fleet as a Mission; Fleet dispatches the Steps to the device
(D-399 §5, D-336). The device plans, checks reachability and owns the final command; this
module never does.
"""

from __future__ import annotations

from dataclasses import dataclass

from .cell import CellConfig
from .geometry import Frame
from .recipe import Recipe
from .sequence import place_order
from .stack import StackPlan, build_stack, stack_issues


class CompileError(ValueError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = tuple(problems)


@dataclass(frozen=True)
class Pose:
    x: float
    y: float
    z: float
    yaw: float


@dataclass(frozen=True)
class Step:
    kind: str  # "pick" | "place" | "pallet_done"
    item: str  # "box" | "slip_sheet" | "" for pallet_done
    pallet: str
    layer: int | None
    target: Pose | None
    approach_z: float | None


@dataclass(frozen=True)
class Job:
    recipe_hash: str
    cell_hash: str
    steps: tuple[Step, ...]


def _on_pallet(frame: Frame, x: float, y: float, z: float, yaw: float) -> Pose:
    bx, by, bz = frame.to_base((x, y, z))
    return Pose(bx, by, bz, frame.yaw_to_base(yaw))


def _transfer(src: Pose, dst: Pose, item: str, pallet: str, layer: int, clearance: float) -> list[Step]:
    return [
        Step("pick", item, pallet, layer, src, src.z + clearance),
        Step("place", item, pallet, layer, dst, dst.z + clearance),
    ]


def _check(recipe: Recipe, cell: CellConfig, tol_m: float) -> dict[str, StackPlan]:
    problems: list[str] = []
    needed = [recipe.pick_station] + ([recipe.slip_sheet_station] if recipe.slip_sheet_station else [])
    problems += [f"unknown station {s!r}" for s in needed if s not in cell.stations]
    plans: dict[str, StackPlan] = {}
    for slot in recipe.pallets:
        if slot.frame not in cell.frames:
            problems.append(f"pallet {slot.id}: unknown frame {slot.frame!r}")
        plan = build_stack(
            recipe.box,
            slot.pallet,
            recipe.layers,
            gap=recipe.gap,
            slip_sheet_thickness=recipe.slip_sheet_thickness or 0.0,
        )
        problems += [f"pallet {slot.id}: {msg}" for msg in stack_issues(plan, recipe.box, slot.pallet, tol_m=tol_m)]
        plans[slot.id] = plan
    if problems:
        raise CompileError(problems)
    return plans


def compile_job(recipe: Recipe, cell: CellConfig, *, tol_m: float) -> Job:
    plans = _check(recipe, cell, tol_m)
    clearance = cell.approach_clearance_m
    station = Pose(*cell.station_pose(recipe.pick_station))
    sheet_station = Pose(*cell.station_pose(recipe.slip_sheet_station)) if recipe.slip_sheet_station else None
    steps: list[Step] = []
    for slot in recipe.pallets:
        frame, plan = cell.frames[slot.frame], plans[slot.id]
        sheets = {s.below_layer: s for s in plan.slip_sheets}
        centre = (slot.pallet.length / 2, slot.pallet.width / 2)
        layer_ids = range(len(plan.layers))
        for n in layer_ids if recipe.mode == "palletize" else reversed(layer_ids):
            ordered = place_order(plan.layers[n], approach=recipe.approach)
            sheet = sheets.get(n)
            sheet_pose = _on_pallet(frame, *centre, sheet.z, 0.0) if sheet else None
            if recipe.mode == "palletize":
                if sheet_pose:
                    steps += _transfer(sheet_station, sheet_pose, "slip_sheet", slot.id, n, clearance)
                for b in ordered:
                    steps += _transfer(station, _on_pallet(frame, b.x, b.y, b.z_top, b.yaw), "box", slot.id, n, clearance)
            else:
                for b in reversed(ordered):
                    steps += _transfer(_on_pallet(frame, b.x, b.y, b.z_top, b.yaw), station, "box", slot.id, n, clearance)
                if sheet_pose:
                    steps += _transfer(sheet_pose, sheet_station, "slip_sheet", slot.id, n, clearance)
        steps.append(Step("pallet_done", "", slot.id, None, None, None))
    return Job(recipe.content_hash, cell.content_hash, tuple(steps))
```

- [ ] **Step 4: Run it.** `python -m pytest src/site/cell/test -q -p no:cacheprovider`. Expected: `38 passed` (3 new). If a numeric assertion fails, recompute it by hand from the fixture as shown above before touching the code. A wrong expectation in the test is a test bug; an unexplained difference is a code bug.
- [ ] **Step 5: Commit.** `git add src/site/cell/rosy_cell/compiler.py src/site/cell/test/test_compiler.py`, then `git commit -m "feat(cell): compile recipe and cell into a hashed Job of Steps"`.

### Task 11: Records, full checks and landing

**Files:** Modify `src/site/cell/progress.md`, `src/site/cell/logs.md`, generated `src/site/cell/index.md` and `STATUS.md`

- [ ] **Step 1: Full checks**

```bash
python -m pytest src/site/cell/test -q -p no:cacheprovider
python -m pytest test/architecture -q -rfE -p no:cacheprovider > X:/DevTemp/rosy-cell-core/arch.txt
python test/known_failures.py X:/DevTemp/rosy-cell-core/arch.txt
python tools/harness/rosy_harness.py lint
```

Expected: `38 passed`, known_failures exit 0, lint `0 error(s)`.

- [ ] **Step 2: Records.** Set `SOURCE` to `state: GO` in `progress.md`, with `evidence: "38 passed (2026-10-01 Windows); ROS-free; no Motion Intent, IK or reachability"` and `last_verified` set to the HEAD commit. Append a `logs.md` entry listing modules, evidence and the gate change. Run `python tools/harness/rosy_harness.py generate`.
- [ ] **Step 3: Commit records** with exact paths from `git status --short`.
- [ ] **Step 4: Independent review.** Dispatch a reviewer agent (`oh-my-claudecode:code-reviewer`) on the branch diff against `main`. Fix confirmed findings on the branch and commit each fix.
- [ ] **Step 5: Land.** Follow `rosy-land-on-main` "Landing": `git merge main` in the worktree, rerun Step 1, then run `git merge --ff-only feat/rosy-cell-pattern-core` in the main checkout. Do not push.

---

## Self-review notes

- Spec coverage:
  - Frames (3-point) → Task 3
  - Patterns grid, split and mirror → Tasks 4–5
  - Slip sheets → Task 6
  - Multi-pallet and depalletize → Task 10
  - Recipe and cell split with hashes → Tasks 8–9
  - Job of Steps → Task 10
  - ADR → Task 1
  - The setup wizard, device execution, MoveIt, LeRobot and reachability are deliberately out of scope (roadmap P3–P7).
- Test counts: the file-level count is listed per task, and the suite total is cumulative: 1 → 7 → 12 → 16 → 19 → 21 → 29 → 35 → 38.
