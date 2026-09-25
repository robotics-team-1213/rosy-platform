# 다기종 로봇 구조 재편 실행 계획 (D-196)

> **2026-09-25:** Task 6–8(폴더 이동)은 [D-231 이동 묶음 계획](2026-09-25-d231-layered-move.md)이 대체한다. 이 문서의 `src/hardware`·`src/apps`·`src/robots` 경로는 작성 당시의 기록이다. Task 0–5와 P4–P7은 그대로다.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pinky Pro, Pinky+OMX, 단독 OMX, 다른 주행 베이스를 같은 CORE로 돌릴 수 있게 `src/`에
`devices/<계열>/`과 `robots/<robot>/` 축을 세운다. P1–P3은 동작을 바꾸지 않는다.

**Architecture:** 설계와 근거는 [초안](2026-09-24-multi-robot-structure-draft.md)에 있다. 이 계획의
Task 1에서 그 초안을 ADR D-196으로 올린다.
- 먼저 시험으로 규칙을 고정한다. D-168 구조 시험에 도메인 두 개와 방향표 행을 넣고, `pinky` 리터럴은
  백로그 목록(집합 동일성)으로 묶는다.
- 다음으로 로봇 프로필을 core 밖의 `robots/pinky_pro` 패키지로 옮기고 `robot.model`/`ROSY_ROBOT`으로 고른다.
- 마지막으로 패키지 디렉터리를 기계적으로 옮긴다. 패키지 이름은 그대로 둔다.

**Tech Stack:** Python 3.12, pytest(host, ROS-free), ament_cmake/ament_python, colcon(WSL Ubuntu
Jazzy), `tools/harness/rosy_harness.py`.

**기준 커밋:** 로컬 `main` `27821a5c`. origin/main을 PR #34까지 합쳤다. ADR은 D-195까지 쓰였고, D-196은 이 재편 몫이다.

---

## 지켜야 할 것

- **동시 작업.** 같은 체크아웃에 다른 세션이 커밋한다. 작업은 `main`에서 만든 worktree(`../.worktrees/multi-robot`)에서
  한다. `main` 반영은 `git merge --ff-only`로만 한다. 겹치는 미커밋 편집이 있으면 반영하지 말고 그 세션에 커밋을 요청한다.
- **기록.** 패키지를 바꾸면 그 패키지의 `logs.md`에 항목을 추가한다. 추가만 하고 기존 항목은 고치지 않는다.
  필드는 `- 변경:` `- 증거:` `- gate 변화:` `- 결정:` `- 교훈:`이다. 끝나면 `python tools/harness/rosy_harness.py generate`를 돌린다.
- **P3(이동)는 이미지 릴리스 사이에 한다(D-191).** 이동 뒤 첫 이미지는 실기 평가표를 다시 통과해야 한다.
- **host 전체 시험**(약 15–20분, 백그라운드로 돌린다):
  ```bash
  python -m pytest src/core/core/test/ src/core/core_features/test src/core/control/test/ src/site/fleet/test \
    src/apps/omx_adapter/test src/apps/games/test src/sim/gz_sim/test test/ -q -p no:cacheprovider
  ```
  `-n auto`는 쓰지 않는다. xdist가 설치되어 있지 않다.

## 파일 지도

| 파일 | 책임 | Task |
|---|---|---|
| `docs/adr/D-196-devices-and-robots-domains.md` (신규) | 결정 기록 | 1 |
| `docs/reference/ROSY ADR Log.md` | D-196 색인 행 | 1 |
| `docs/plans/2026-09-22-control-package-split-design.md` | §3 개정: 장치 코드는 `control_sensing`이 아니라 devices로 간다 | 1 |
| `test/test_module_structure.py` | 도메인, 레이아웃(devices는 3단), P4 방향표를 순수 함수로 | 2 |
| `test/test_robot_literals.py` (신규) | `pinky` 리터럴의 거주지 규칙 | 3 |
| `test/robot_literal_backlog.txt` (신규) | 현재 위반 목록(P5 작업량) | 3 |
| `src/core/core_common/core_common/profile.py` | `DEFAULT_ROBOT`, `robot_config_dir()` | 4 |
| `src/core/core_common/core_common/config.py` | `ROSY_ROBOT` → `robot.model` | 4 |
| `src/core/core/core/node.py` | 프로필과 capabilities를 로봇 패키지에서 찾는다 | 4 |
| `src/core/core/config/rosy_default.yaml` | `robot.model: pinky_pro`. `profile:`/`capabilities:` 키 제거 | 4 |
| `src/robots/pinky_pro/**` (신규 패키지) | `config/profile.yaml`, `config/capabilities.yaml`, 기록 3종, 자체 시험 | 5 |
| `deploy/image/required-ros-packages.txt`, `tools/harness/harness.yaml` | 새 패키지 등록 | 5 |
| `src/devices/**` (이동) | `hardware/*`, `apps/omx_adapter`, `sim/description`이 옮겨 오는 곳 | 6–8 |

---

## Task 0: worktree

- [ ] **Step 1: 깨끗한 main에서 worktree를 만든다**

```bash
cd "f:/Dev/Control/Robot/ROS/Rosy/Rosy OS"
git status --short            # 비어 있지 않아도 된다. worktree는 커밋에서 만든다
git worktree add -b refactor/multi-robot-structure ../.worktrees/multi-robot main
cd ../.worktrees/multi-robot
```

이후 모든 명령은 이 worktree에서 실행한다.

---

## Task 1: ADR D-196과 control 분할 설계 개정 (문서만)

**Files:**
- Create: `docs/adr/D-196-devices-and-robots-domains.md`
- Modify: `docs/reference/ROSY ADR Log.md`, `docs/plans/2026-09-22-control-package-split-design.md`,
  `docs/plans/2026-09-24-multi-robot-structure-draft.md`(상태 줄)
- Test: `test/test_harness_contracts.py::test_repository_adr_log_is_contiguous_and_indexed`

- [ ] **Step 1: ADR 파일을 쓴다**

`docs/adr/D-196-devices-and-robots-domains.md`:

```markdown
## D-196 로봇은 장치의 조합이다 — `src/devices/<계열>/`과 `src/robots/<robot>/`을 두고, 로봇 지식은 그 안에만 둔다

**Status:** Proposed (2026-09-24). D-147 §1·§2 일부와 D-168 P4 방향표를 대체한다. D-11/HWA-003, D-57,
D-44, D-163, D-169, D-171, D-192를 유지하고 확장한다. 설계와 재평가: `docs/plans/2026-09-24-multi-robot-structure-draft.md`.
실행: `docs/plans/2026-09-24-multi-robot-structure.md`.

**Context:** Rosy OS는 Pinky Pro, Pinky+OMX, 단독 OMX, 다른 주행 베이스(TurtleBot3, 메카넘)를 같은
CORE API로 돌려야 한다. `src/`는 역할 기준 6개 도메인(D-147)이고 로봇 축이 없다. 그래서 Pinky 지식이
6개 도메인에 흩어져 있다. core의 `profile.pinky_pro.yaml`, 사실상 Pinky 전용인 `hardware/bringup`,
sim 안의 URDF, nav2 반경, control의 `robot.yaml`과 센싱 기하, fleet의 반지름 상수가 그렇다. 또
`apps/omx_adapter`는 장치 어댑터인데 apps에 있다. 2026-09-24 기준 src 안에서 `pinky`를 말하는 제품 파일은 72개다.

**Decision:**

1. **도메인.** `src/devices/<계열>/<패키지>/`를 둔다. 계열은 `pinky_pro`, `omx`, `common`이고, 보드에
   딸린 부품은 그 계열 안에 함께 둔다. `src/robots/<robot>/`은 코드 없이 설정·URDF 조립·launch만 담는
   패키지다. `hardware` 도메인은 이동이 끝나면 없앤다. `devices/<계열>/` 안의 패키지에는 계열 접두
   이름을 허용한다. 이것이 D-147 §2를 대체하는 부분이다.
2. **P4 방향표 추가 행.** `devices` → core 계약, 같은 계열, `devices/common`. `robots` → core 계약,
   `devices`. `navigation` → core 계약, `devices`(전 `hardware`).
3. **거주지 규칙.** src 제품 파일의 `pinky` 리터럴은 `devices/pinky_pro/`와 `robots/pinky_pro*` 안에만
   둔다. 현재 위반은 `test/robot_literal_backlog.txt`에 집합 동일성으로 묶는다(D-168 P5).
4. **로봇 선택.** CORE는 프로필과 capabilities를 `robot.model`(환경 변수 `ROSY_ROBOT`, 기본
   `pinky_pro`) 패키지의 `share/<model>/config/`에서 읽는다. 절대 경로 오버레이(`/etc/rosy/*.yaml`)는
   그대로 우선한다. core는 로봇 패키지를 선언 의존하지 않는다. 동적 조회는 D-126 `sensor_provider`와
   같은 종류의 결합이다. 이미지는 `required-ros-packages.txt`로 로봇 패키지를 싣는다.
5. **계약(후속 단계).** 베이스 경계는 `ros2_control`이다(D-57). 최종 `cmd_vel`은 drive capability가 있을
   때만 CORE가 소유한다. 정적 층은 Profile v2의 장치 조합이고, 런타임 층은 US-010 `withhold_hardware_flags`이다.
   팔 동작은 CORE가 MoveIt 액션을 대행한다. 카메라는 `devices/common/camera`가 캡처하고, apps는 역할 이름으로 구독한다.
   센싱 코드의 배치 규칙: 로봇을 바꿨을 때 코드가 바뀌면 devices, 숫자만 바뀌면 apps에 두고 값은 프로필/TF에서 읽는다.

**Alternatives:** 최소 재편(`robots/`만 추가), `devices` 종류별 구분(bases/arms/sensors), 로봇별 최상위
폴더. 모두 기각했다. 근거는 초안 §Alternatives에 있다.

**Consequences:** 도메인 이동은 도메인당 1커밋으로 하고 동작 변경을 섞지 않는다. 이동은 이미지 릴리스
사이에 하고, 이동 뒤 첫 이미지는 D-191 평가표를 다시 통과해야 한다. `core/control`의 장치 코드 분리는
D-171 트랙 3(control 분할)과 한 계획으로 묶는다.

**Validation / Transition:** P1 `test_module_structure.py`와 `test_robot_literals.py`가 녹색이어야 한다. P2
`robots/pinky_pro` 패키지와 core 시험이 녹색이어야 한다. P3에서는 이동마다 host 전체 시험, colcon build(WSL Jazzy),
2대 gz 벤치 결과가 이동 전과 같아야 한다. 백로그가 비고 두 번째 로봇 프로필(sim)이 같은 CORE API로 뜨면 Accepted로 올린다.
```

- [ ] **Step 2: ADR Log에 행을 넣는다**

`docs/reference/ROSY ADR Log.md`의 `| D-195 | ... |` 행 바로 아래에:

```markdown
| D-196 | 로봇은 장치의 조합이다 — `src/devices/<계열>/`과 `src/robots/<robot>/`을 두고, 로봇 지식은 그 안에만 둔다 | Proposed |
```

그리고 `docs/reference/AGENTS.md`의 `append-only decisions through D-195`를 `through D-196`으로 고친다.

- [ ] **Step 3: control 분할 설계 §3에 개정 문단을 붙인다**

`docs/plans/2026-09-22-control-package-split-design.md`에서 `## 3. 목표 구조 — 3개 패키지` 절의 표 바로 아래에 다음을 넣는다.

```markdown
**개정 (2026-09-24, D-196):** `control_sensing`에 넣기로 했던 것 중 장치 코드는 devices로 간다.
- `ir_adc_node`와 `sensing/ir_adc.py`는 `devices/pinky_pro`로 간다. D-192 §4의 0x08 독자를 한 계열에 모으기 위해서다.
- `camera_detect_node`의 캡처부와 `sensing/camera_controls.py`는 `devices/common/camera`로 간다.
- `control_sensing`에는 알고리즘만 남는다. line/road/dock observer는 `Image`를 구독하고, 카메라
  기하는 프로필/TF에서 받는다.

이 개정은 트랙 3의 첫 단계에서 함께 실행한다. io 이미지 폐쇄는 `devices/pinky_pro` + `devices/common/camera` + `control_sensing`이 된다.
```

- [ ] **Step 4: 초안의 상태 줄을 바꾼다**

`docs/plans/2026-09-24-multi-robot-structure-draft.md` 첫 `**Status:**` 줄을 다음으로 바꾼다.

```markdown
**Status:** ADR로 승격됨 — [D-196](../adr/D-196-devices-and-robots-domains.md) (2026-09-24). 이 문서는 설계 근거로 남긴다.
```

- [ ] **Step 5: 시험**

```bash
python -m pytest test/test_harness_contracts.py -q -p no:cacheprovider
python tools/harness/rosy_harness.py generate && python tools/harness/rosy_harness.py lint
```
Expected: `46 passed`, lint `0 error(s)`.

- [ ] **Step 6: 커밋**

```bash
git add docs/adr/D-196-devices-and-robots-domains.md "docs/reference/ROSY ADR Log.md" docs/reference/AGENTS.md \
  docs/plans/2026-09-22-control-package-split-design.md docs/plans/2026-09-24-multi-robot-structure-draft.md docs/index.md
git commit -m "docs(adr): D-196 robots are compositions of devices (Proposed)"
```

---

## Task 2: D-168 구조 시험에 devices/robots를 넣는다

**Files:**
- Modify: `test/test_module_structure.py` (`DOMAINS` 27행, `_domain` 이후, `_allowed` 201–213행, 레이아웃 시험 224–231행)

- [ ] **Step 1: 실패하는 시험을 쓴다**

`test/test_module_structure.py` 맨 위 import에 `import pytest`를 넣는다. 파일 끝에 다음을 붙인다.

```python
@pytest.mark.parametrize(
    "src_domain, src_family, dst_domain, dst_family, target, ok",
    [
        ("devices", "pinky_pro", "devices", "pinky_pro", "description", True),
        ("devices", "pinky_pro", "devices", "common", "imu_bno055", True),
        ("devices", "pinky_pro", "devices", "omx", "omx_adapter", False),
        ("devices", "omx", "devices", "pinky_pro", "description", False),
        ("devices", "omx", "core", None, "core_common", True),
        ("devices", "omx", "core", None, "core", False),
        ("robots", None, "devices", "pinky_pro", "bringup", True),
        ("robots", None, "apps", None, "control", False),
        ("navigation", None, "devices", "pinky_pro", "bringup", True),
        ("apps", None, "devices", "common", "imu_bno055", False),
    ],
)
def test_direction_table_rows_for_devices_and_robots(src_domain, src_family, dst_domain, dst_family, target, ok):
    """D-196 P4 rows, checked before any package moves into them."""
    assert edge_allowed(src_domain, src_family, dst_domain, dst_family, target) is ok


@pytest.mark.parametrize(
    "rel, name, ok",
    [
        (("devices", "pinky_pro", "bringup"), "bringup", True),
        (("devices", "bringup"), "bringup", False),
        (("robots", "pinky_pro"), "pinky_pro", True),
        (("apps", "control"), "control", True),
        (("apps", "x", "control"), "control", False),
    ],
)
def test_layout_rule_allows_a_family_level_only_under_devices(rel, name, ok):
    """P2(a) + D-196: src/<domain>/<package>, except src/devices/<family>/<package>."""
    assert layout_ok(rel, name) is ok
```

- [ ] **Step 2: 실패를 확인한다**

```bash
python -m pytest test/test_module_structure.py -q -p no:cacheprovider
```
Expected: FAIL with `NameError: name 'edge_allowed' is not defined` (수집 단계).

- [ ] **Step 3: 최소 구현**

27행을 다음으로 바꾼다.

```python
DOMAINS = {"core", "apps", "hardware", "devices", "robots", "navigation", "sim", "site"}
```

`_domain` 함수 바로 아래에 다음을 넣는다.

```python
def _family(name: str):
    parts = PACKAGES[name]["dir"].relative_to(SRC).parts
    return parts[1] if parts[0] == "devices" else None


def layout_ok(rel: tuple, name: str) -> bool:
    """P2(a) + D-196: src/<domain>/<package>, except src/devices/<family>/<package>."""
    if rel and rel[0] == "devices":
        return len(rel) == 3 and rel[2] == name
    return len(rel) == 2 and rel[0] in DOMAINS and rel[1] == name
```

기존 `_allowed` 전체를 다음 두 함수로 바꾼다.

```python
def edge_allowed(src_domain, src_family, dst_domain, dst_family, target) -> bool:
    """P4 direction table (D-168, D-196). Pure, so rows are testable before packages move."""
    if target in CORE_CONTRACTS:
        return True
    if src_domain == "core":
        return dst_domain == "core"
    if src_domain == "sim":
        return True
    if src_domain == "hardware":
        return target == "description"
    if src_domain == "devices":
        return dst_domain == "devices" and dst_family in (src_family, "common")
    if src_domain == "robots":
        return dst_domain == "devices"
    if src_domain == "navigation":
        return dst_domain in ("hardware", "devices")
    return False


def _allowed(source: str, target: str) -> bool:
    return edge_allowed(_domain(source), _family(source), _domain(target), _family(target), target)
```

`test_every_package_sits_in_a_domain_group_under_its_own_name`의 조건을 바꾼다.

```python
        if not layout_ok(rel, name):
            bad.append(f"{name}: {'/'.join(rel)}")
```

- [ ] **Step 4: 통과를 확인한다**

```bash
python -m pytest test/test_module_structure.py -q -p no:cacheprovider
```
Expected: 모두 PASS. 기존 시험과 새 매개변수 15건이다.

- [ ] **Step 5: 커밋**

```bash
git add test/test_module_structure.py
git commit -m "test(structure): D-196 devices/robots domains and direction rows"
```

---

## Task 3: `pinky` 리터럴 거주지 시험과 백로그

**Files:**
- Create: `test/test_robot_literals.py`, `test/robot_literal_backlog.txt`

- [ ] **Step 1: 시험을 쓴다**

`test/test_robot_literals.py`:

```python
"""D-196: robot-specific names live in the robot's device family and robot package.

Every other product file under src/ that still says "pinky" is listed in
robot_literal_backlog.txt and checked by set equality (D-168 P5): a new hit
fails, and so does a line whose file no longer matches. Shrinking the list is
the de-Pinky work (plan P5).
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
BACKLOG = Path(__file__).with_name("robot_literal_backlog.txt")
PATTERN = re.compile(r"pinky", re.IGNORECASE)
SUFFIXES = {".py", ".yaml", ".yml", ".xml", ".xacro", ".urdf", ".sdf", ".world", ".cpp", ".hpp", ".json"}
SKIP_PARTS = {"test", "tests", "build", "install", "log", "__pycache__"}
HOME_PREFIXES = ("devices/pinky_pro/", "robots/pinky_pro")


def hits() -> set:
    found = set()
    for path in SRC.rglob("*"):
        if not path.is_file() or path.suffix not in SUFFIXES:
            continue
        rel = path.relative_to(SRC)
        if any(part in SKIP_PARTS or part.startswith(".") for part in rel.parts):
            continue
        key = rel.as_posix()
        if key.startswith(HOME_PREFIXES):
            continue
        if PATTERN.search(path.read_text(encoding="utf-8", errors="ignore")):
            found.add(key)
    return found


def backlog() -> set:
    lines = BACKLOG.read_text(encoding="utf-8").splitlines()
    return {line.strip() for line in lines if line.strip() and not line.startswith("#")}


def test_robot_literals_stay_in_their_family():
    found, known = hits(), backlog()
    assert found == known, f"new: {sorted(found - known)}, stale (remove): {sorted(known - found)}"
```

`test/robot_literal_backlog.txt`는 머리 주석만으로 시작한다.

```text
# D-196 de-Pinky backlog: src product files outside devices/pinky_pro and robots/pinky_pro*
# that still say "pinky". Set equality with test_robot_literals.py. Remove lines, never add.
```

- [ ] **Step 2: 실패를 확인한다**

```bash
python -m pytest test/test_robot_literals.py -q -p no:cacheprovider
```
Expected: FAIL `new: ['core/control/...', ...]`. 2026-09-24 `27821a5c` 기준 72개다(control 44, gz_sim 10, bringup 9, core 4, navigation 2, fleet 2, omx_adapter 1).

- [ ] **Step 3: 백로그를 현재 상태로 채운다**

```bash
python -c "import sys; sys.path.insert(0, 'test'); import test_robot_literals as t; print('\n'.join(sorted(t.hits())))" \
  >> test/robot_literal_backlog.txt
```

- [ ] **Step 4: 통과를 확인한다**

```bash
python -m pytest test/test_robot_literals.py -q -p no:cacheprovider
```
Expected: `1 passed`.

- [ ] **Step 5: 커밋**

```bash
git add test/test_robot_literals.py test/robot_literal_backlog.txt
git commit -m "test(repo): D-196 pinky literals live in the pinky family; backlog of 72"
```

---

## Task 4: core가 로봇 패키지에서 프로필을 찾는다

**Files:**
- Modify: `src/core/core_common/core_common/profile.py`, `src/core/core_common/core_common/config.py`(137행 `mode = ...` 앞),
  `src/core/core/core/node.py:27-55`, `src/core/core/config/rosy_default.yaml:1-22`
- Test: `src/core/core_common/test/test_robot_selection.py` (신규)

- [ ] **Step 1: 실패하는 시험을 쓴다**

`src/core/core_common/test/test_robot_selection.py`:

```python
"""D-196: CORE finds the robot's profile in the robot package named by robot.model."""

from pathlib import Path

import pytest

from core_common import config as config_module
from core_common.config import ConfigError, load_config
from core_common.profile import DEFAULT_ROBOT, robot_config_dir

SRC = Path(__file__).resolve().parents[3]


def test_robot_config_dir_falls_back_to_the_source_tree():
    assert robot_config_dir("pinky_pro") == SRC / "robots" / "pinky_pro" / "config"


def test_default_robot_is_pinky_pro():
    assert DEFAULT_ROBOT == "pinky_pro"


@pytest.fixture(autouse=True)
def _no_operator_overlay(monkeypatch):
    for name in ("ROSY_CONFIG", "ROSY_ROBOT", "ROSY_RUNTIME_MODE", "ROSY_NAMESPACE", "ROSY_DEVICE_NAME"):
        monkeypatch.delenv(name, raising=False)


def test_default_config_names_the_robot_model(monkeypatch, tmp_path):
    monkeypatch.setattr(config_module, "LOCAL_CONFIG_PATH", tmp_path / "absent.yaml")
    assert load_config()["robot"]["model"] == "pinky_pro"


def test_rosy_robot_env_selects_the_model(monkeypatch, tmp_path):
    monkeypatch.setenv("ROSY_ROBOT", "omx_desk")
    monkeypatch.setattr(config_module, "LOCAL_CONFIG_PATH", tmp_path / "absent.yaml")
    assert load_config()["robot"]["model"] == "omx_desk"


@pytest.mark.parametrize("bad", ["Pinky", "../etc", "pinky pro", "1robot"])
def test_rosy_robot_env_must_be_a_package_name(monkeypatch, tmp_path, bad):
    monkeypatch.setenv("ROSY_ROBOT", bad)
    monkeypatch.setattr(config_module, "LOCAL_CONFIG_PATH", tmp_path / "absent.yaml")
    with pytest.raises(ConfigError):
        load_config()
```

- [ ] **Step 2: 실패를 확인한다**

```bash
python -m pytest src/core/core_common/test/test_robot_selection.py -q -p no:cacheprovider
```
Expected: FAIL `ImportError: cannot import name 'DEFAULT_ROBOT'`.

- [ ] **Step 3: 구현**

`src/core/core_common/core_common/profile.py`의 `class RobotProfile` 위에 다음을 넣는다.

```python
#: D-196: the robot package CORE loads when nothing names one.
DEFAULT_ROBOT = "pinky_pro"


def robot_config_dir(robot: str) -> Path:
    """Config directory of the robot package ``robot`` (D-196).

    The installed ament share wins; a host checkout falls back to src/robots/<robot>/config.
    """
    try:
        from ament_index_python.packages import get_package_share_directory
        return Path(get_package_share_directory(robot)) / "config"
    except Exception:
        return Path(__file__).resolve().parents[3] / "robots" / robot / "config"
```

`src/core/core_common/core_common/config.py`의 `mode = os.environ.get("ROSY_RUNTIME_MODE", "").strip()` 줄 바로 앞에 다음을 넣고, 파일 import에 `import re`를 추가한다.

```python
    model = os.environ.get("ROSY_ROBOT", "").strip()
    if model:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", model):
            raise ConfigError(f"ROSY_ROBOT must be a robot package name, got {model!r}")
        robot["model"] = model
```

`src/core/core/config/rosy_default.yaml`에서 `robot:` 블록에 `model` 줄을 넣는다.

```yaml
robot:
  id: rosy_01
  name: Rosy 01
  model: pinky_pro            # D-196 robots/<model> 패키지 — ROSY_ROBOT 가 덮는다
  frame_prefix: ""            # namespace 런치 시 rosy_01/ 로 주입 (§6.1)
```

그리고 다음 두 줄은 지운다.

```yaml
profile: profile.pinky_pro.yaml   # HWA-001 Robot Profile
capabilities: capabilities.yaml
```

`src/core/core/core/node.py`의 `_resolve_path`와 호출부를 바꾼다.

```python
def _resolve_path(config: dict[str, Any], key: str, fallback: Path, base_dir: Path) -> Path:
    raw = config.get("robot", {}).get(key) or config.get(key)
    if raw:
        candidate = Path(str(raw)).expanduser()
        return candidate if candidate.is_absolute() else base_dir / candidate.name
    return fallback
```

```python
        from core_common.profile import DEFAULT_ROBOT, RobotProfile, robot_config_dir
        import yaml

        robot_dir = robot_config_dir(str(config.get("robot", {}).get("model") or DEFAULT_ROBOT))
        profile_path = _resolve_path(config, "profile", robot_dir / "profile.yaml", robot_dir)
        capability_path = _resolve_path(config, "capabilities", robot_dir / "capabilities.yaml", robot_dir)
```

- [ ] **Step 4: 통과를 확인한다**

```bash
python -m pytest src/core/core_common/test/test_robot_selection.py -q -p no:cacheprovider
```
Expected: 모두 PASS(8건). `robot_config_dir` 시험은 경로만 비교하므로 패키지가 생기기 전(Task 5)에도 통과한다. ROS가 source된 셸에서 `pinky_pro`가 설치돼 있으면 share 경로가 나와 첫 시험이 실패한다 — host 시험은 ROS를 source하지 않은 셸에서 돌린다.

- [ ] **Step 5: 커밋하지 않는다.** Task 5와 한 커밋이다. 프로필 파일이 옮겨지기 전까지 core 시험이 적색이다.

---

## Task 5: `src/robots/pinky_pro` 패키지

**Files:**
- Create: `src/robots/AGENTS.md`, `src/robots/pinky_pro/{package.xml,CMakeLists.txt,AGENTS.md,progress.md,logs.md}`,
  `src/robots/pinky_pro/test/test_robot_package.py`
- Move: `src/core/core/config/profile.pinky_pro.yaml` → `src/robots/pinky_pro/config/profile.yaml`,
  `src/core/core/config/capabilities.yaml` → `src/robots/pinky_pro/config/capabilities.yaml`
- Modify: core 시험 중 두 파일을 읽는 것들(`git grep -l "profile.pinky_pro.yaml\|capabilities.yaml" -- src/core/core/test`),
  `src/core/core/config/AGENTS.md`, `deploy/image/required-ros-packages.txt`, `tools/harness/harness.yaml`, `AGENTS.md:51`

- [ ] **Step 1: 패키지 시험을 쓴다**

`src/robots/pinky_pro/test/test_robot_package.py`:

```python
"""D-196: a robot package carries the profile and capabilities CORE loads for it."""

from pathlib import Path

import yaml

CONFIG = Path(__file__).resolve().parents[1] / "config"


def test_profile_names_the_model_and_base_limits():
    profile = yaml.safe_load((CONFIG / "profile.yaml").read_text(encoding="utf-8"))["profile"]
    assert profile["model"] == "Pinky Pro"
    assert profile["max_linear_velocity"] > 0
    assert profile["max_angular_velocity"] > 0


def test_capabilities_match_the_profile_limits():
    """HWA-003: advertised navigation limits are the profile's."""
    profile = yaml.safe_load((CONFIG / "profile.yaml").read_text(encoding="utf-8"))["profile"]
    caps = yaml.safe_load((CONFIG / "capabilities.yaml").read_text(encoding="utf-8"))
    assert caps["capability_version"] == 1
    assert caps["navigation"]["max_linear_velocity"] == profile["max_linear_velocity"]
    assert caps["navigation"]["max_angular_velocity"] == profile["max_angular_velocity"]
    assert caps["docking"]["supported"] is False
```

- [ ] **Step 2: 실패를 확인한다**

```bash
python -m pytest src/robots/pinky_pro/test -q -p no:cacheprovider
```
Expected: FAIL `FileNotFoundError: ...src/robots/pinky_pro/config/profile.yaml`.

- [ ] **Step 3: 설정을 옮기고 패키지를 만든다**

```bash
mkdir -p src/robots/pinky_pro/config
git mv src/core/core/config/profile.pinky_pro.yaml src/robots/pinky_pro/config/profile.yaml
git mv src/core/core/config/capabilities.yaml src/robots/pinky_pro/config/capabilities.yaml
sed -i 's#Robot Profile(profile.pinky_pro.yaml)#Robot Profile(profile.yaml)#' src/robots/pinky_pro/config/capabilities.yaml
```

`src/robots/pinky_pro/package.xml`:

```xml
<?xml version="1.0"?>
<?xml-model href="http://download.ros.org/schema/package_format3.xsd" schematypens="http://www.w3.org/2001/XMLSchema"?>
<package format="3">
  <name>pinky_pro</name>
  <version>0.0.0</version>
  <description>Pinky Pro robot composition: HWA-001 profile and CAP-001 capabilities CORE loads (D-196). Config only.</description>
  <maintainer email="byeongkyu@todo.todo">byeongkyu</maintainer>
  <license>Apache-2.0</license>

  <buildtool_depend>ament_cmake</buildtool_depend>

  <test_depend>python3-pytest</test_depend>
  <test_depend>python3-yaml</test_depend>

  <export>
    <build_type>ament_cmake</build_type>
  </export>
</package>
```

`src/robots/pinky_pro/CMakeLists.txt`:

```cmake
cmake_minimum_required(VERSION 3.8)
project(pinky_pro)

find_package(ament_cmake REQUIRED)

install(DIRECTORY config DESTINATION share/${PROJECT_NAME})

ament_package()
```

`src/robots/AGENTS.md`:

```markdown
<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-24 | Updated: 2026-09-24 -->

# robots

## Purpose

로봇 하나 = 패키지 하나(D-196). 코드 없이 CORE가 읽는 프로필·capabilities, 이후 URDF 조립과 launch만 담는다. 장치 코드는 `src/devices/<계열>/`에 둔다.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `pinky_pro/` | Pinky Pro 단독 구성 (see `pinky_pro/AGENTS.md`) |

## For AI Agents

- 새 로봇은 `robots/<name>/`이고 패키지 이름 = 디렉터리 이름이다. `ROSY_ROBOT=<name>`이 고른다.
- core는 로봇 패키지를 선언 의존하지 않는다. 이미지는 `deploy/image/required-ros-packages.txt`로 싣는다.
- 방향: robots → core 계약, devices만(D-168 P4, D-196).
```

`src/robots/pinky_pro/AGENTS.md`:

```markdown
<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-24 | Updated: 2026-09-24 -->

# pinky_pro

## Purpose

Pinky Pro 로봇 구성. CORE가 `robot.model: pinky_pro`일 때 `share/pinky_pro/config/`에서 HWA-001 프로필과 CAP-001 capabilities를 읽는다(D-196, D-11).

## Key Files

| File | Description |
|------|-------------|
| `config/profile.yaml` | HWA-001 Robot Profile (model, 속도 한계, 기하, 센서) |
| `config/capabilities.yaml` | CAP-001 정적 선언. 프로필과 일치해야 한다(HWA-003) |
| `progress.md` / `logs.md` | harness 기록 (D-61) |

## For AI Agents

- 프로필과 capabilities는 함께 바꾼다. `test/test_robot_package.py`가 속도 한계 일치를 본다.
- 런타임 모드별 광고 파일(`deploy/robot/config/*.{core,motor,hardware}.yaml`)은 deploy가 소유한다. 여기로 옮기는 것은 후속 작업이다.

## Testing Requirements

python -m pytest src/robots/pinky_pro/test -q
```

`src/robots/pinky_pro/progress.md`:

```markdown
---
module: pinky_pro
logical_modules: [M06]
owner: 로봇 통합
last_verified: { commit: "uncommitted", date: 2026-09-24 }
gates:
  SOURCE:
    state: GO
    evidence: "프로필·capabilities 일치 시험 통과 (2026-09-24)"
    cmd: "python -m pytest src/robots/pinky_pro/test -q"
  LOCAL:
    state: GO
    evidence: "core가 source tree 폴백으로 이 설정을 읽어 core 시험 통과 (2026-09-24 Windows)"
    cmd: "python -m pytest src/core/core/test src/core/core_common/test -q"
  ROS-SIM:
    state: HOLD
    blocker: "colcon build 뒤 share/pinky_pro/config 에서 CORE 기동 확인 전 (WSL Jazzy)"
  ARTIFACT:
    state: HOLD
    blocker: "required-ros-packages.txt 등재 후 이미지 빌드·인벤토리 확인 전"
  DEVICE:
    state: HOLD
    blocker: "새 이미지에서 CORE_READY와 GET /system/capabilities 확인 전"
  FIELD:
    state: PARKED
adrs: [D-196, D-11]
plans:
  - docs/plans/2026-09-24-multi-robot-structure.md
---

# pinky_pro progress

Pinky Pro 로봇 구성 패키지. 설정만 담는다.
```

`src/robots/pinky_pro/logs.md`:

```markdown
# pinky_pro logs

추가만 한다. 형식: [module harness 설계](../../../docs/plans/2026-09-15-module-harness-design.md) §4.2.

## 2026-09-24 · uncommitted · feat(robots): pinky_pro robot package carries the profile CORE loads (D-196)
- 변경: `src/core/core/config/profile.pinky_pro.yaml`와 `capabilities.yaml`을 이 패키지의 `config/profile.yaml`·`config/capabilities.yaml`로 옮겼다. CORE는 `robot.model`(기본 `pinky_pro`, `ROSY_ROBOT`)의 share에서 읽는다
- 증거: `python -m pytest src/robots/pinky_pro/test src/core/core_common/test src/core/core/test -q` 통과 (2026-09-24 Windows)
- gate 변화: SOURCE GO, LOCAL GO (신규)
- 결정: D-196 Proposed
- 교훈: 없음
```

`tools/harness/harness.yaml`의 `modules:`에서 `- name: description` 항목 앞에 다음을 넣는다.

```yaml
  - name: pinky_pro
    path: src/robots/pinky_pro
    tests: [src/robots/pinky_pro/test]
    functional_kind: host-contract
    functional: [src/robots/pinky_pro/test/test_robot_package.py]
```

`deploy/image/required-ros-packages.txt`의 `core` 줄 다음에 `pinky_pro`를 넣는다.

- [ ] **Step 4: core 시험의 경로를 바꾼다**

```bash
files=$(git grep -l 'profile\.pinky_pro\.yaml\|"capabilities\.yaml"' -- src/core/core/test)
sed -i -E \
  -e 's#Path\(__file__\)\.parent\.parent / "config" / "profile\.pinky_pro\.yaml"#robot_config_dir("pinky_pro") / "profile.yaml"#g' \
  -e 's#Path\(__file__\)\.parent\.parent / "config" / "capabilities\.yaml"#robot_config_dir("pinky_pro") / "capabilities.yaml"#g' \
  -e 's#\b(CONFIG_DIR|config_dir) / "profile\.pinky_pro\.yaml"#robot_config_dir("pinky_pro") / "profile.yaml"#g' \
  -e 's#\b(CONFIG_DIR|config_dir) / "capabilities\.yaml"#robot_config_dir("pinky_pro") / "capabilities.yaml"#g' \
  -e 's#\bread\("capabilities\.yaml"\)#yaml.safe_load((robot_config_dir("pinky_pro") / "capabilities.yaml").read_text(encoding="utf-8"))#g' \
  $files
for f in $files; do grep -q "^from core_common.profile import" "$f" \
  && sed -i -E 's#^from core_common\.profile import (.*)$#from core_common.profile import \1, robot_config_dir#' "$f" \
  || sed -i '0,/^from pathlib import Path$/s##from pathlib import Path\n\nfrom core_common.profile import robot_config_dir#' "$f"; done
git grep -n 'profile\.pinky_pro\|"capabilities\.yaml"' -- src/core/core/test
```

Expected: 마지막 grep 결과가 `test_node_wiring.py`의 `tmp_path / "capabilities.yaml"`(임시 파일, 그대로 둠) 하나뿐이다. `read(...)`를 바꾼 파일에 `import yaml`이 없으면 추가한다(`python -m pyflakes`나 시험 실패로 드러난다). `test_node_wiring.py`가 `_resolve_path`를 직접 부르면 네 번째 인자(`tmp_path`)를 넘긴다.

그리고 문서를 고친다. `src/core/core/config/AGENTS.md`에서 두 파일 행을 지우고 "프로필과 capabilities는 `src/robots/<model>/config/`(D-196)" 한 줄을 넣는다. 루트 `AGENTS.md:51`의 `src/core/core/config/profile.pinky_pro.yaml`은 `src/robots/pinky_pro/config/profile.yaml`로 고친다.

- [ ] **Step 5: 통과를 확인한다**

```bash
python -m pytest src/robots/pinky_pro/test src/core/core_common/test src/core/core/test test/test_module_structure.py \
  test/test_robot_literals.py test/test_native_ros_payload.py -q -p no:cacheprovider
```

Expected: 모두 PASS다. `test_robot_literals`는 옮긴 `robots/pinky_pro/config/*`가 거주지 안이라 백로그에서 두 줄이 stale로 뜬다. 그 두 줄(`core/core/config/profile.pinky_pro.yaml`, `core/core/config/capabilities.yaml`)을 지우고 다시 돌린다.

- [ ] **Step 6: 기록과 전체 시험**

`src/core/core/logs.md`와 `src/core/core_common/logs.md`에 같은 형식으로 항목을 하나씩 추가한다(변경: 프로필 조회를 `robot.model`로 / `ROSY_ROBOT`·`robot_config_dir`). 그리고:

```bash
python tools/harness/rosy_harness.py generate && python tools/harness/rosy_harness.py lint
```
host 전체 시험(머리말 명령)을 백그라운드로 돌려 통과를 확인한다.

- [ ] **Step 7: 커밋**

```bash
git add -A
git commit -m "feat(robots): CORE loads the robot profile from robots/<model> (D-196)"
```

- [ ] **Step 8: ROS 확인 (WSL Ubuntu)**

```bash
wsl -d Ubuntu -- bash -lc 'rsync -a --delete "/mnt/f/Dev/Control/Robot/ROS/Rosy/.worktrees/multi-robot/src/" ~/rosy_ws/src/ \
  && cd ~/rosy_ws && source /opt/ros/jazzy/setup.bash && colcon build --symlink-install --packages-up-to core pinky_pro \
  && source install/setup.bash && ls $(ros2 pkg prefix pinky_pro)/share/pinky_pro/config'
```
Expected: `capabilities.yaml  profile.yaml`. 결과는 `src/robots/pinky_pro/progress.md` ROS-SIM 증거에 적는다.

---

## Task 6: `devices/pinky_pro` 계열로 이동 (P3, 동작 변경 없음)

**Files:**
- Move: `src/hardware/{bringup,sensor_adc,lamp_control,led}` → `src/devices/pinky_pro/`, `src/sim/description` → `src/devices/pinky_pro/description`
- Modify (경로 참조): `.github/workflows/ci.yml:106`, `deploy/image/build-native-payload.sh:79`, `deploy/robot/Dockerfile:25,113-118`,
  `.dockerignore:14-26`, `test/test_robot_runtime.py:98`, `test/test_image_customization_contract.py:687,688,828,838`,
  `test/test_native_systemd_contract.py:375-381`, `tools/fix_ament_resource.sh:5`, `tools/harness/harness.yaml`, 이동한 패키지의 AGENTS.md와 시험

- [ ] **Step 1: 이동**

```bash
mkdir -p src/devices/pinky_pro
for p in bringup sensor_adc lamp_control led; do git mv src/hardware/$p src/devices/pinky_pro/$p; done
git mv src/sim/description src/devices/pinky_pro/description
```

- [ ] **Step 2: 경로 참조를 바꾼다 (기록 문서는 제외)**

```bash
refs() { git grep -l "$1" -- . ':!docs/adr' ':!docs/plans' ':!**/logs.md' ':!docs/logs.md' ':!**/index.md'; }
for pair in "src/hardware/bringup:src/devices/pinky_pro/bringup" "src/hardware/sensor_adc:src/devices/pinky_pro/sensor_adc" \
            "src/hardware/lamp_control:src/devices/pinky_pro/lamp_control" "src/hardware/led:src/devices/pinky_pro/led" \
            "src/sim/description:src/devices/pinky_pro/description"; do
  old=${pair%%:*}; new=${pair##*:}
  for f in $(refs "$old"); do sed -i "s#$old#$new#g" "$f"; done
done
sed -i 's#src/apps/\* src/core/\* src/hardware/\* src/navigation/\* src/sim/\* src/site/\*#src/apps/* src/core/* src/devices/*/* src/hardware/* src/navigation/* src/robots/* src/sim/* src/site/*#' tools/fix_ament_resource.sh
git grep -n "src/hardware/\(bringup\|sensor_adc\|lamp_control\|led\)\|src/sim/description" -- . ':!docs/adr' ':!docs/plans' ':!**/logs.md' ':!**/index.md'
```
Expected: 마지막 grep이 비어 있다.

- [ ] **Step 3: 한 단계 깊어진 상대 경로를 고친다**

패키지가 한 층 깊어졌으므로 저장소 루트를 `parents[N]`으로 찾는 시험은 N을 1 올린다.

```bash
sed -i 's#^REPO = PACKAGE.parents\[2\]#REPO = PACKAGE.parents[3]#' src/devices/pinky_pro/bringup/test/test_adc_ownership.py
sed -i 's#^ROOT = Path(__file__).resolve().parents\[4\]  \# repository root#ROOT = Path(__file__).resolve().parents[5]  \# repository root#' \
  src/devices/pinky_pro/bringup/test/test_rosylib_battery_curve.py
git grep -nE "parents\[[0-9]\]" -- src/devices/pinky_pro
```
Expected: 남은 `parents[1]`은 패키지 루트를 뜻하므로 그대로 둔다. 다른 N이 보이면 저장소 루트/`src` 기준인지 읽고 1 올린다.

- [ ] **Step 4: 계층 AGENTS.md**

`src/devices/AGENTS.md`(계열 표: `pinky_pro/`, `common/`, `omx/`와 D-196 방향 규칙)와 `src/devices/pinky_pro/AGENTS.md`(패키지 표: bringup, sensor_adc, lamp_control, led, description)를 만든다. 이동한 패키지 AGENTS.md의 `<!-- Parent: ../AGENTS.md -->`는 그대로 맞다. `src/hardware/AGENTS.md`에서 옮긴 행을 지우고, `src/sim/AGENTS.md`에서 description 행을 지운다.

- [ ] **Step 5: 구조 시험과 이미지 계약 시험**

```bash
python -m pytest test/test_module_structure.py test/test_robot_literals.py test/test_robot_runtime.py \
  test/test_image_customization_contract.py test/test_native_systemd_contract.py test/test_native_ros_payload.py \
  src/devices/pinky_pro -q -p no:cacheprovider
```
Expected: PASS. `test_robot_literals`에서 옮긴 bringup(9개)·description 파일이 stale로 뜨면 백로그에서 지운다. `test_module_structure`의 `bringup → description`은 같은 계열이라 허용된다.

- [ ] **Step 6: 기록, 전체 시험, 커밋**

옮긴 5개 패키지 `logs.md`에 항목을 추가한다(`- 변경: src/devices/pinky_pro/<pkg>로 이동, 동작 변경 없음`). `generate`와 `lint`를 돌리고, host 전체 시험을 통과시킨다.

```bash
git add -A
git commit -m "refactor(devices): move the Pinky Pro board packages into src/devices/pinky_pro (D-196)"
```

- [ ] **Step 7: ROS 확인 (WSL)**

```bash
wsl -d Ubuntu -- bash -lc 'rsync -a --delete "/mnt/f/Dev/Control/Robot/ROS/Rosy/.worktrees/multi-robot/src/" ~/rosy_ws/src/ \
  && cd ~/rosy_ws && rm -rf build install log && source /opt/ros/jazzy/setup.bash && colcon build --symlink-install 2>&1 | tail -5'
```
Expected: `Summary: 21 packages finished`(20 + pinky_pro), 실패 0이다. 다음으로 이동 전과 같은 2대 벤치를 돌려 같은 결과가 나오는지 본다.
`ros2 launch gz_sim gz_multi.launch.py robots:=2 headless:=true core:=true`

---

## Task 7: `devices/common/imu_bno055`와 `devices/omx/omx_adapter`

- [ ] **Step 1: 이동과 참조 변경**

```bash
mkdir -p src/devices/common src/devices/omx
git mv src/hardware/imu_bno055 src/devices/common/imu_bno055
git mv src/apps/omx_adapter src/devices/omx/omx_adapter
refs() { git grep -l "$1" -- . ':!docs/adr' ':!docs/plans' ':!**/logs.md' ':!docs/logs.md' ':!**/index.md'; }
for f in $(refs src/hardware/imu_bno055); do sed -i 's#src/hardware/imu_bno055#src/devices/common/imu_bno055#g' "$f"; done
for f in $(refs src/apps/omx_adapter); do sed -i 's#src/apps/omx_adapter#src/devices/omx/omx_adapter#g' "$f"; done
git grep -nE "parents\[[0-9]\]" -- src/devices/common src/devices/omx
```
`src/devices/omx/omx_adapter/test/conftest.py`의 `SRC = Path(__file__).resolve().parents[2]`는 원래 `src/apps`를 가리켰다. 이 값을 어디에 쓰는지 읽고, `src`가 필요하면 `parents[3]`으로 올린다.

- [ ] **Step 2: 시험**

```bash
python -m pytest test/test_module_structure.py test/test_robot_literals.py test/test_robot_runtime.py \
  src/devices/omx/omx_adapter/test src/devices/common/imu_bno055/test -q -p no:cacheprovider
```
Expected: PASS. `KNOWN_DIRECTION`의 `("control", "imu_bno055")`는 이제 apps → devices 위반으로 남는다(사유 문자열의 "apps -> hardware"를 "apps -> devices"로 고친다). omx_adapter 백로그 줄 1개는 거주지 밖(`devices/omx`)이므로 그대로 둔다.

- [ ] **Step 3: 기록, 전체 시험, 커밋**

```bash
git add -A
git commit -m "refactor(devices): move imu_bno055 to devices/common and omx_adapter to devices/omx (D-196)"
```

---

## Task 8: `hardware` 도메인 제거와 반영

- [ ] **Step 1: 빈 도메인 정리**

```bash
git rm -q src/hardware/AGENTS.md && rmdir src/hardware 2>/dev/null; ls src
```
`test/test_module_structure.py`에서 `DOMAINS`의 `"hardware"`와 `edge_allowed`의 `if src_domain == "hardware": ...` 두 줄, `navigation` 행의 `"hardware"`를 지운다. `tools/fix_ament_resource.sh`의 `src/hardware/*`와 `src/AGENTS.md`의 hardware 행도 지운다.

- [ ] **Step 2: 시험과 커밋**

```bash
python -m pytest test/test_module_structure.py -q -p no:cacheprovider
git add -A && git commit -m "refactor(structure): retire the hardware domain (D-196)"
```

- [ ] **Step 3: main 반영**

```bash
cd "f:/Dev/Control/Robot/ROS/Rosy/Rosy OS"
git status --short                       # 겹치는 미커밋 편집이 있으면 멈추고 주인 세션에 커밋 요청
git merge --no-ff refactor/multi-robot-structure -m "Merge branch 'refactor/multi-robot-structure' (D-196 P1-P3)"
git worktree remove ../.worktrees/multi-robot && git branch -d refactor/multi-robot-structure
```
`main`이 그 사이 움직였으면 먼저 브랜치에 `main`을 머지하고 전체 시험을 다시 돌린다.

---

## P4–P7 (별도 계획으로 쓴다)

| 단계 | 범위 | 계획을 쓸 때 볼 것 |
|---|---|---|
| **P4** 장치 코드 분리 + D-171 트랙 3 | `ir_adc_node`/`sensing/ir_adc.py` → `devices/pinky_pro`, `emotion/rosy_lcd.py` → `devices/pinky_pro`, 카메라 캡처 → `devices/common/camera`. control 3분할 | `refactor/d171-track1`은 D-172 방식으로 재구현한다. D-192 `test_adc_ownership`·`test_ir_source_exclusivity`, D-190 부팅 표시 경로. control은 32,106줄이다 |
| **P5** Pinky 값 걷어내기 | 백로그 비우기: safety 외곽 수치, `lidar_yaw_offset` → TF, `sensing/body.py`, `camera_geometry_source='PINKY'`(line/road/dock observer) → 카메라 장착 정보를 `robots/<robot>`로, fleet 반지름, nav2 오버레이, `deploy/robot/config/*` 광고 파일 | 백로그 줄 수가 진척 지표다 |
| **P6** 두 번째 로봇 | Profile v2(장치 조합)와 정적 capability 파생, 장치별 xacro 매크로와 `robots/*` 조립, `pinky_pro_omx` → `omx_desk` → TurtleBot3 sim | 단독 OMX에서 drive capability false, US-010 런타임 층과의 합성 |
| **P7** ros2_control | Pinky 베이스 교체와 실기 비교 | D-57 Validation 항목 |
