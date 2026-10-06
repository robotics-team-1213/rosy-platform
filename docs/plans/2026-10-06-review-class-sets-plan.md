# Pinky 검수 클래스셋 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 검수 앱이 고정 6클래스(`OBJECT_CLASSES`)와 화면 하드코딩 이름표 대신, 모델·작업마다 다른 클래스셋을 불변 record로 묶어 검수·승인·내보내기에 쓴다.

**Architecture:** 픽셀 쪽에 이미 있는 "작업 공간에 한 번 묶는 sha 고정 `classes.yaml`"(`review_masks.bind_classes`)을 객체 쪽에도 같은 모양으로 들인다. 클래스셋은 `data.yaml`(Ultralytics `names`)이나 `classes.yaml`에서 들어오고, 서버가 화면에 표시명·색·단축키까지 내려 준다. 한 작업 공간은 객체 클래스셋 하나와 픽셀 클래스셋 하나를 갖는다. 다른 모델의 클래스셋은 다른 `--state` 작업 공간으로 연다.

**Tech Stack:** Python 3.10+ 표준 라이브러리 + PyYAML(기존 `build.load_classes` 의존), SQLite, 빌드 없는 vanilla JS, pytest, Playwright(브라우저 시험).

**근거:** 외부 도구 조사 [2026-10-06-label-review-tool-survey.md](../assessments/2026-10-06-label-review-tool-survey.md) 5절, 현재 고정 위치 조사(아래 "현재 상태").

---

## 현재 상태 (2026-10-06 main 95428dde2)

| 위치 | 고정 내용 |
|---|---|
| `middleware/perception/control/sensing/perception/learned/manifest.py:24` | `OBJECT_CLASSES` 6개, `:179` object_det manifest는 이 순서만 허용 (D-423 계약 v1) |
| `learning/training/perception/dataset/object_boxes.py:97,113,116,218` | 저장 검증, YOLO 번호 `OBJECT_CLASSES.index`, export manifest `classes` |
| `dataset/review_return.py:78,93,131` | 반환 검증과 `classes` 기록 |
| `dataset/review_app.py:104,276` | 저장 검증, `/api/workspace`의 `classes` |
| `dataset/review_pack.py:14` | 세 번째 사본 `CLASSES` |
| `dataset/review_app_web/app.js:6` | 한국어 이름표 `names` (서버 `classes`를 읽지 않음) |
| `dataset/review_app_web/pixels.js:3,34` | 픽셀 7개 이름표와 색 토큰 |
| `dataset/review_masks.py:38-66` | 픽셀 클래스셋 binding — 이미 sha 고정, 작업 공간당 1회 |

실제 차선 모델(`pinky-lane-segmentation`)의 클래스는 `background, lane_left, lane_right, crosswalk, speed_bump`(4/5클래스)이고, 검수 앱의 픽셀 기본값은 `floor, lane_line, wall, drivable, stop_line, crosswalk`이다. 좌·우 차선 구분과 speed_bump가 없다.

## 결정이 필요한 점 (Task 0에서 ADR로 닫는다)

1. **작업 공간 단위.** 이 계획은 "작업 공간 1개 = 객체 클래스셋 1개 + 픽셀 클래스셋 1개"를 택한다. 같은 사진을 두 클래스셋으로 검수하려면 같은 원본으로 작업 공간을 두 개 만든다. "사진 × 클래스셋" review row(조사 7절 2)는 frames 표 키 마이그레이션이 필요해 뒤로 미룬다.
2. **D-423과의 경계.** 검수·내보내기는 클래스셋을 따른다. 로봇에 올리는 object_det manifest의 6클래스 계약(`manifest.py:179`)은 이 계획에서 바꾸지 않는다. 다른 객체 클래스셋 모델을 로봇에 배포하려면 별도 ADR이 필요하다.
3. **차선 role.** `lane_left`, `lane_right`는 role `lane_marking`이다. `speed_bump`는 닫힌 role 목록(`manifest.py:20`, D-373)에 맞는 것이 없다. 이번에는 lane 5클래스 classes.yaml에서 `crosswalk`·`speed_bump`를 role `ignore`로 둔다(로봇 런타임 의미 없음). 새 role 추가는 별도 ADR이다.
4. **`.pt` 파일.** 앱은 `.pt`를 열지 않는다(pickle, Ultralytics AGPL-3.0). 모델 PC에서 `YOLO(path).names`를 `data.yaml`로 내보내는 한 줄 도구를 쓴다.

## 파일 구조

| 파일 | 책임 |
|---|---|
| Create `learning/training/perception/dataset/class_sets.py` | 클래스셋 record 정규화(`data.yaml`/이름 목록), sha, 작업 공간 binding, 기존 작업 공간의 v1 기본값 |
| Create `learning/training/perception/test/test_class_sets.py` | 위 모듈 시험 |
| Modify `dataset/object_boxes.py` | `to_yolo_lines`, `merge_review`가 클래스 목록을 인자로 받음(기본 `OBJECT_CLASSES`) |
| Modify `dataset/review_return.py` | 검증·manifest가 넘겨받은 클래스 목록 사용 |
| Modify `dataset/review_app.py` | `--object-classes` 첫 실행 인자, 저장 검증, `/api/workspace`에 `object_class_set` |
| Modify `dataset/review_evidence.py` | `decisions`와 export contract에 `object_class_set_sha256` |
| Modify `dataset/review_app_web/app.js` | `names` 맵 삭제, 서버 클래스셋으로 select·제목 구성, 숫자키 |
| Modify `dataset/review_app_web/pixels.js` | `names`·`classToken` 삭제, classes.yaml의 `display`·`color` 사용, 숫자키 |
| Create `tools/perception/export_class_names.py` | 모델 PC 전용: `.pt` → `data.yaml` |
| Create `learning/training/perception/classes/lane_lr5.yaml` | 차선 모델 5클래스 classes.yaml |
| Create `docs/adr/D-<n>-review-class-sets.md` + ADR Log 행 | 결정 1–4 |
| Modify `learning/training/perception/docs/review-app.md`, `.claude/skills/rosy-pinky-review/SKILL.md` | 운영 절차 |

`review_pack.py:14`의 세 번째 사본은 Task 3에서 `OBJECT_CLASSES` import로 바꾼다.

---

### Task 0: ADR

**Files:**
- Create: `docs/adr/D-<n>-review-class-sets.md`
- Modify: `docs/reference/ROSY ADR Log.md` (UTF-8 BOM, CRLF 유지)

- [ ] **Step 1: 번호를 파일 만들기 직전에 고른다** (AGENTS.md 4항: `ls docs/adr`, 각 브랜치 `git ls-tree -r --name-only <branch> docs/adr`, ADR Log `| D-nnn |` 행, `tools/harness/harness.yaml`의 `adr_gaps`).
- [ ] **Step 2: ADR 본문** — 상태 Proposed. 위 "결정이 필요한 점" 1–4를 결정으로 적고, 근거로 조사 문서 5.1–5.3을 링크한다. 비채택: 다중 사용자 플랫폼, 앱 안 모델 호출(D-459), `.pt` 언피클, 공유 ontology 전파.
- [ ] **Step 3: Log 행과 같은 커밋**, `python tools/harness/rosy_harness.py lint` 오류 0.
- [ ] **Step 4: 사용자 확인** — Proposed → Accepted는 사용자가 정한다. Accepted 전에는 Task 1 이후를 브랜치에만 둔다.

### Task 1: 클래스셋 record 모듈

**Files:**
- Create: `learning/training/perception/dataset/class_sets.py`
- Test: `learning/training/perception/test/test_class_sets.py`

- [ ] **Step 1: 실패하는 시험**

```python
"""Versioned class sets: same names in the same order always give the same sha."""
import pytest

import class_sets
from object_boxes import OBJECT_CLASSES


def test_data_yaml_dict_and_list_give_the_same_record():
    as_dict = class_sets.from_data_yaml(b'names:\n  0: robot\n  1: cone\n', 'detect')
    as_list = class_sets.from_data_yaml(b'names: [robot, cone]\n', 'detect')
    assert as_dict['sha256'] == as_list['sha256']
    assert [c['name'] for c in as_dict['classes']] == ['robot', 'cone']
    assert as_dict['classes'][0]['hotkey'] == '1'


def test_display_and_color_come_from_the_file_and_do_not_change_identity():
    plain = class_sets.from_data_yaml(b'names: [robot]\n', 'detect')
    shown = class_sets.from_data_yaml(
        b'names: [robot]\ndisplay: {robot: "\xeb\xa1\x9c\xeb\xb4\x87"}\ncolors: {robot: [255, 0, 0]}\n', 'detect')
    assert shown['classes'][0]['display'] == '로봇'
    assert shown['classes'][0]['color'] == [255, 0, 0]
    assert shown['sha256'] == plain['sha256']


def test_bad_names_are_refused():
    for raw in (b'names: []\n', b'names: [a, a]\n', b'names: {0: a, 2: b}\n', b'nc: 2\n'):
        with pytest.raises(ValueError):
            class_sets.from_data_yaml(raw, 'detect')


def test_legacy_object_set_is_the_d423_list():
    legacy = class_sets.legacy_object_set()
    assert tuple(c['name'] for c in legacy['classes']) == OBJECT_CLASSES
    assert legacy['source']['kind'] == 'd423_v1'
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest learning/training/perception/test/test_class_sets.py -q -p no:cacheprovider`
Expected: FAIL `ModuleNotFoundError: No module named 'class_sets'`

- [ ] **Step 3: 구현**

```python
"""Immutable class sets the review app binds once per workspace.

Identity is the ordered class names and the task; display names, colours and
hotkeys are presentation and do not change the sha (renaming a label for people
must not invalidate approved reviews).
"""
import hashlib
import json

import yaml

from object_boxes import OBJECT_CLASSES

KOREAN = {'robot': '로봇', 'obstacle_box': '장애물 상자', 'cone': '콘', 'traffic_light': '신호등',
          'sign': '표지판', 'person_feet': '사람 발'}
TASKS = ('detect', 'semantic')


def _record(names, task, source, display=None, colors=None):
    if task not in TASKS:
        raise ValueError(f'task one of {TASKS}')
    if not names or len(set(names)) != len(names) or not all(isinstance(n, str) and n for n in names):
        raise ValueError('class names must be unique non-empty strings')
    identity = json.dumps({'task': task, 'names': list(names)}, ensure_ascii=False).encode()
    display, colors = display or {}, colors or {}
    return {'task': task, 'source': source, 'sha256': hashlib.sha256(identity).hexdigest(),
            'classes': [{'index': i, 'name': n, 'display': display.get(n, n),
                         'color': colors.get(n), 'hotkey': str(i + 1) if i < 9 else None}
                        for i, n in enumerate(names)]}


def from_data_yaml(raw, task):
    doc = yaml.safe_load(raw)
    names = doc.get('names') if isinstance(doc, dict) else None
    if isinstance(names, dict):
        if sorted(names) != list(range(len(names))):
            raise ValueError('names indices must be dense 0..N-1')
        names = [names[i] for i in range(len(names))]
    if not isinstance(names, list):
        raise ValueError('data.yaml needs names')
    return _record(names, task, {'kind': 'data_yaml', 'sha256': hashlib.sha256(raw).hexdigest()},
                   doc.get('display'), doc.get('colors'))


def legacy_object_set():
    return _record(list(OBJECT_CLASSES), 'detect', {'kind': 'd423_v1'}, KOREAN)
```

- [ ] **Step 4: 통과 확인** — 같은 명령, Expected: `4 passed`
- [ ] **Step 5: 커밋** `git add learning/training/perception/dataset/class_sets.py learning/training/perception/test/test_class_sets.py` → `feat(review): versioned class set records`

### Task 2: 작업 공간 binding

> 구현 메모: 규칙은 "프레임이 하나라도 있으면 거절"이다(계획의 라벨 있는 프레임 기준보다 엄격). Task 4는 `ReviewStore.__init__`에서 프레임 삽입 전에 바인딩해야 한다. 지금 시험의 `DELETE FROM frames`는 Task 4의 실제 첫 시작 경로로 대체한다.

**Files:**
- Modify: `learning/training/perception/dataset/class_sets.py`
- Test: `learning/training/perception/test/test_class_sets.py`

- [ ] **Step 1: 실패하는 시험** (`test_review_app.open_store` 재사용)

```python
from test_review_app import open_store


def test_old_workspace_reads_the_legacy_set_and_binding_is_write_once(tmp_path):
    store = open_store(tmp_path)
    assert class_sets.object_set(store)['sha256'] == class_sets.legacy_object_set()['sha256']
    other = class_sets.from_data_yaml(b'names: [car, person]\n', 'detect')
    with pytest.raises(ValueError, match='do not reinterpret'):
        class_sets.bind_object_set(store, other)
    class_sets.bind_object_set(store, class_sets.legacy_object_set())   # same sha: no-op
```

- [ ] **Step 2: 실패 확인** — Expected: `AttributeError: module 'class_sets' has no attribute 'object_set'`
- [ ] **Step 3: 구현** — metadata key `object_class_set`. 없으면 `legacy_object_set()`을 돌려준다(기존 작업 공간 소급, 조사 7절 3). 바인딩은 `review_masks.bind_classes`와 같은 `BEGIN IMMEDIATE` + sha 비교, 새로 쓸 때 `generation` +1.

```python
def object_set(store):
    with store.connect() as db:
        row = db.execute("SELECT value FROM metadata WHERE key='object_class_set'").fetchone()
    return json.loads(row[0]) if row else legacy_object_set()


def bind_object_set(store, record):
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute("SELECT value FROM metadata WHERE key='object_class_set'").fetchone()
        current = json.loads(row[0]) if row else legacy_object_set()
        if current['sha256'] != record['sha256']:
            if row or db.execute("SELECT 1 FROM frames WHERE review LIKE '%\"label\": \"%' LIMIT 1").fetchone():
                raise ValueError('workspace object classes differ; do not reinterpret labels')
        if not row:
            db.execute("INSERT INTO metadata VALUES ('object_class_set',?)", (json.dumps(record),))
            db.execute("UPDATE metadata SET value=CAST(value AS INTEGER)+1 WHERE key='generation'")
    return record
```

- [ ] **Step 4: 통과 확인**, **Step 5: 커밋** `feat(review): bind one object class set per workspace`

### Task 3: 내보내기와 반환이 클래스 목록을 받는다

**Files:**
- Modify: `dataset/object_boxes.py:94-117` (`merge_review`, `to_yolo_lines`에 `classes=OBJECT_CLASSES` 인자)
- Modify: `dataset/review_return.py:78,93,131` (`receive_review(..., classes=OBJECT_CLASSES)`)
- Modify: `dataset/review_pack.py:14` (`from object_boxes import OBJECT_CLASSES as CLASSES`)
- Test: `test/test_object_boxes.py`, `test/test_review_return.py`

- [ ] **Step 1: 실패하는 시험**

```python
def test_yolo_lines_use_the_given_class_order():
    boxes = [{'label': 'person', 'bbox_xyxy': [0, 0, 10, 10]}]
    assert object_boxes.to_yolo_lines(boxes, (20, 20), classes=('car', 'person'))[0].startswith('1 ')
    assert object_boxes.to_yolo_lines(boxes, (20, 20)) == []      # default stays D-423 v1
```

- [ ] **Step 2: 실패 확인** — `TypeError: unexpected keyword argument 'classes'`
- [ ] **Step 3: 구현** — 함수 안의 `OBJECT_CLASSES`를 `classes`로 바꾸고 기본값을 둔다. `review_return.receive_review`는 `classes`를 export manifest `classes`에 그대로 쓴다. 기존 호출부는 인자 없이 동작이 같다.
- [ ] **Step 4: 기존 검수 시험 묶음 전체 통과** (`review-app.md`의 시험 명령) — 기본값 경로가 바뀌지 않았음을 확인.
- [ ] **Step 5: 커밋** `refactor(review): pass the object class list through export`

### Task 4: 서버가 클래스셋을 쓰고 내려 준다

**Files:**
- Modify: `dataset/review_app.py` (`validate_boxes`에 classes, `__init__`에 `object_classes=None`, `main`에 `--object-classes <data.yaml>`, `/api/workspace`)
- Modify: `dataset/review_evidence.py` (`decisions` 응답과 `review-contract.json`에 `object_class_set_sha256`)
- Test: `test/test_review_app.py`

- [ ] **Step 1: 실패하는 시험**

```python
def test_workspace_with_a_new_class_set_saves_and_exports_its_labels(tmp_path):
    source, human, images = fixture_inputs(tmp_path)
    record = class_sets.from_data_yaml(b'names: [car, robot]\n', 'detect')
    store = ReviewStore(tmp_path / 'state', source, human, images, object_classes=record)
    frame = store.get(0)
    boxes = [dict(frame['review']['boxes'][0], label='car')]
    saved = store.update(0, {'version': frame['version'], 'action': 'save', 'boxes': boxes})
    with pytest.raises(ValueError, match='known object class'):
        store.update(0, {'version': saved['version'], 'action': 'save',
                         'boxes': [dict(boxes[0], label='cone')]})
    assert class_sets.object_set(store)['sha256'] == record['sha256']
```

첫 실행 import가 기존 `robot` 등 라벨을 담고 있으면 새 클래스셋에 없는 라벨은 거부해야 한다. 시험 fixture의 라벨이 새 클래스셋에 있는지 먼저 확인하고(`fixture_inputs`), 없으면 import가 `ValueError('known object class required')`로 멈추는 시험을 하나 더 쓴다.

- [ ] **Step 2: 실패 확인**
- [ ] **Step 3: 구현**
  - `ReviewStore.__init__(..., object_classes=None)`: 첫 실행에서 `validate_boxes` 전에 `class_sets.bind_object_set(self, object_classes or class_sets.legacy_object_set())`. 재실행에 `object_classes`가 오면 binding 비교만 한다(다르면 거부).
  - `validate_boxes(source, boxes, *, classes, approved=False)`: `allowed = classes + (() if approved else (None,))`. 호출부 3곳은 `tuple(c['name'] for c in class_sets.object_set(self)['classes'])`.
  - `/api/workspace`: `'classes'`를 지우지 말고(하위 호환) `'object_class_set': class_sets.object_set(store)`를 더한다.
  - `prepare()`: `review_return.receive_review(..., classes=names)`.
  - `main()`: `--object-classes PATH` → `class_sets.from_data_yaml(path.read_bytes(), 'detect')`.
- [ ] **Step 4: 통과 + 기존 묶음 통과** — 기존 작업 공간(`legacy`)의 결정 sha가 바뀌지 않아야 한다. `decision_sha256`에 새 필드를 넣으면 기존 소비자의 sha가 바뀌므로, 필드는 `decisions` 최상위에만 더하고 frame row에는 넣지 않는다. `test_review_bridge*.py`, `test_review_authority.py`도 돌린다.
- [ ] **Step 5: 커밋** `feat(review): workspaces review and export their bound object class set`

### Task 5: 화면이 서버 클래스셋을 쓴다

**Files:**
- Modify: `dataset/review_app_web/app.js` (`names` 삭제)
- Modify: `dataset/review_app_web/pixels.js` (`names`, `classToken` 삭제)
- Modify: `dataset/review_masks.py` `bind_classes` — classes.yaml의 선택 필드 `display`를 `build.load_classes` 결과에 더한다(identity인 `classes_signature`는 기존 필드만으로 계산하도록 유지).
- Test: `test/test_review_flow_browser.py`, `test/test_pixel_review_browser.py`

- [ ] **Step 1: 실패하는 브라우저 시험**

```python
def test_class_select_lists_the_workspace_class_set(browser_workspace):
    page, store, expect = browser_workspace
    options = page.locator('#boxes select').first.locator('option').all_inner_texts()
    assert options == ['클래스 선택 필요', '로봇', '장애물 상자', '콘', '신호등', '표지판', '사람 발']
```

새 클래스셋 작업 공간용 fixture(`browser_workspace_with(record)`)로 `car`가 `자동차`로 보이는 시험을 하나 더 쓴다. 현재 화면은 `names` 맵에 없는 이름을 빈칸으로 보여 주므로 실패한다.

- [ ] **Step 2: 실패 확인** (`ROSY_RUN_BROWSER_TESTS=1`)
- [ ] **Step 3: 구현**
  - app.js: `load()`에서 `const set=workspace.object_class_set; names=Object.fromEntries([['','클래스 선택 필요'],...set.classes.map(c=>[c.name,c.display])]);` — `names`는 `let`으로 남기고 select 생성(`:165`)과 제목(`:159`)은 그대로 쓴다.
  - 박스 색: `paint()`에서 클래스 `color`가 있으면 `rgb(...)`, 없으면 기존 토큰.
  - pixels.js: 이름은 `cls.display||cls.name`, 색은 `rgb(cls.color)`(classes.yaml은 color 필수). 범례 대비는 기존 공용 토큰으로 테두리만 준다.
- [ ] **Step 4: 통과**, 실데이터 복사본에서 `python tools/review_app_smoke.py --state <copy>`와 스크린샷 확인.
- [ ] **Step 5: 커밋** `uiux(review): screens use the server class set, no hard-coded names`

### Task 6: 숫자키·A·X 단축키

**Files:** `app.js`, `pixels.js`, 두 브라우저 시험

- [ ] **Step 1: 실패하는 시험** — 박스 선택 후 `page.keyboard.press('2')` → select 값 `obstacle_box`. `#complete` 체크 후 `a` → 다음 대기 사진. 숫자 입력 칸 포커스에서 `2`는 숫자 입력으로 남는다.
- [ ] **Step 2–4:** 기존 `keydown` 처리기(`app.js` ArrowLeft/Right 분기)에 추가. 조건은 기존 화살표와 같다(`INPUT/SELECT/TEXTAREA` 밖). `A`는 `#approve`가 disabled면 아무것도 하지 않는다(체크 생략 금지 — D-461 명시 승인). `hotkey`가 없는 10번째 이후 클래스는 select로만 고른다.
- [ ] **Step 5: 커밋** `uiux(review): number keys pick classes, A approves, X excludes`

### Task 7: 모델 클래스 가져오기와 차선 5클래스

**Files:**
- Create: `tools/perception/export_class_names.py` (모델 PC 전용)
- Create: `learning/training/perception/classes/lane_lr5.yaml`
- Test: `test/test_class_sets.py` (lane_lr5.yaml이 `review_masks.bind_classes`를 통과)

```python
"""Model PC only: write a review data.yaml from an Ultralytics .pt (the app never unpickles models).

    python tools/perception/export_class_names.py best.pt --out data.yaml
"""
import argparse
from pathlib import Path

import yaml
from ultralytics import YOLO   # AGPL-3.0: used as an installed library on the model PC, not vendored

parser = argparse.ArgumentParser()
parser.add_argument('model', type=Path)
parser.add_argument('--out', type=Path, required=True)
args = parser.parse_args()
model = YOLO(str(args.model))
args.out.write_text(yaml.safe_dump({'task': model.task, 'names': dict(model.names)}, allow_unicode=True),
                    encoding='utf-8')
```

```yaml
# Pinky lane segmentation 5-class model (pinky-lane-segmentation CLASSES order).
classes:
- {index: 0, name: background, role: background, display: 배경, color: [90, 90, 90]}
- {index: 1, name: lane_left, role: lane_marking, display: 왼쪽 차선, color: [255, 210, 0]}
- {index: 2, name: lane_right, role: lane_marking, display: 오른쪽 차선, color: [0, 200, 255]}
- {index: 3, name: crosswalk, role: ignore, display: 횡단보도, color: [255, 255, 255]}
- {index: 4, name: speed_bump, role: ignore, display: 과속방지턱, color: [255, 90, 90]}
```

- [ ] **Step 1:** 시험 `test_lane_lr5_binds_as_a_pixel_class_set`: `review_masks.bind_classes(store, Path(...lane_lr5.yaml).read_bytes())`가 성공하고 이름 순서가 모델 `CLASSES`와 같다.
- [ ] **Step 2–4:** 실패 → yaml 작성 → 통과. `export_class_names.py`는 모델 PC에서 1회 실행해 결과 yaml을 `X:\DevTemp`가 아닌 모델 PC 작업 폴더에 둔다(저장소 시험 대상 아님: ultralytics 미설치 호스트).
- [ ] **Step 5: 커밋** `feat(review): lane left/right class set and model class export`

### Task 8: 문서·스킬·착지

- [ ] `review-app.md`: 첫 실행 `--object-classes data.yaml`, 픽셀 `classes.yaml`의 `display`, 단축키 표, "다른 모델 = 다른 `--state`".
- [ ] `.claude/skills/rosy-pinky-review/SKILL.md`: 클래스셋 작업 공간 만들기, 단축키 선택자.
- [ ] `docs/logs.md` 행, `python tools/harness/rosy_harness.py generate`.
- [ ] 관련 시험 전체 + `test/known_failures.py` 비교 → 독립 리뷰 → 사용자 말 뒤 `--ff-only` 착지.

## 뒤로 미루는 것

| 항목 | 이유 | 조건 |
|---|---|---|
| 사진 × 클래스셋 review row | frames 키 마이그레이션 | 한 작업 공간에서 여러 클래스셋이 실제로 필요해질 때 |
| 모델 라벨 → 검수 라벨 매핑 표 (조사 5.3) | `prelabel.py` 후보 provenance 변경 포함 | 검수 클래스셋과 다른 이름의 모델 후보를 가져올 때 |
| 로봇 manifest의 새 객체 클래스셋 | D-423 계약 변경 | 6클래스 밖 모델을 로봇에 배포할 때 별도 ADR |
| `speed_bump` 등 새 role | D-373 닫힌 role 목록 | 로봇 런타임이 그 클래스를 써야 할 때 |
| 모델-사람 불일치 정렬, frame 메모, polygon 채우기 | 선택 (조사 5.7–5.9) | 검수량이 늘었을 때 |
