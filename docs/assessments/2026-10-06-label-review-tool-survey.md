# 라벨 검수 도구 조사: 모델별 클래스 집합

**기준:** 2026-10-06, 브랜치 `docs/review-dynamic-classes` (워크트리 HEAD `95428dde2`). 외부 사실은 모두 1차 출처(공식 문서, 소스 저장소, licence 파일)에서 확인했고 각 문장에 URL을 단다. licence SPDX는 같은 날 GitHub `repos/<owner>/<repo>` API의 `license.spdx_id`와 LICENSE 파일 본문으로 확인했다.

## 1. 문제와 현재 앱

Pinky 검수 앱(D-459, D-461, D-462, D-469)은 표준 라이브러리 Python 서버, SQLite, 빌드 없는 vanilla JS로 되어 있다. 객체 박스와 인덱스 픽셀 마스크를 검수하며, 사람의 명시 승인, version CAS, 동결된 sealed export를 가진다(`learning/training/perception/docs/review-app.md`).

클래스는 지금 세 곳에 고정돼 있다.

| 위치 | 내용 |
|------|------|
| `middleware/perception/control/sensing/perception/learned/manifest.py:24` | `OBJECT_CLASSES = ("robot", "obstacle_box", "cone", "traffic_light", "sign", "person_feet")` |
| `manifest.py:179` | `object_det` manifest는 이 튜플을 **순서까지** 같게 요구한다 (런타임 계약) |
| `dataset/review_app.py:104`, `:276` | 박스 검증과 `/api` 응답이 `review_return.exporter.OBJECT_CLASSES`를 쓴다 |
| `dataset/review_app_web/app.js:6` | 한국어 표시 이름 맵 `names = {robot:'로봇', ...}` 하드코딩 |
| `dataset/review_masks.py:44-49` | 픽셀 쪽은 이미 `classes.yaml` 원문을 `bind_classes`로 묶고 `sha256`, `ignore_index: 255`를 기록한다 |

픽셀 쪽 `bind_classes`는 아래 권고의 "버전 있는 클래스 집합"의 축소판이다. 객체 쪽을 같은 모양으로 일반화하고, 한 workspace에 하나만 묶던 것을 모델·작업별 여러 개로 넓히면 된다. 단 `manifest.py:179`의 순서 계약은 런타임(로봇) 쪽 계약이므로, 검수 앱에서 클래스 집합을 바꿔도 배포 manifest가 조용히 바뀌어서는 안 된다(아래 7.1).

YOLO 학습 대상은 Ultralytics YOLO11 detect/segment `.pt`, 그리고 left lane / right lane / background 같은 lane segmentation이다. 따라서 "작업 종류 + 클래스 목록 + 인덱스"가 모델마다 다르다.

## 2. Ultralytics가 클래스 이름을 저장하는 방식

클래스 집합을 모델에서 끌어올 수 있는지가 설계의 출발점이다.

| 출처 | 형태 | 근거 |
|------|------|------|
| dataset YAML | `names:` 아래 `0: person` 같은 index→name dict. `path/train/val/test` 와 함께 둔다 | https://docs.ultralytics.com/datasets/detect/ |
| 로드된 모델 / `Results` | `names`는 "A dictionary mapping class indices to class names" | https://docs.ultralytics.com/modes/predict/ |
| export metadata | exporter가 `task`, `imgsz`, `names` 등을 metadata dict에 넣는다 | https://github.com/ultralytics/ultralytics/blob/7142057731/ultralytics/engine/exporter.py#L980-L994 |
| ONNX | 그 dict의 각 값을 `str(v)`로 `metadata_props`에 쓴다 | https://github.com/ultralytics/ultralytics/blob/7142057731/ultralytics/engine/exporter.py#L1213-L1216 |
| ONNX 읽기 | Ultralytics 자신은 `names`, `imgsz` 등 문자열을 `ast.literal_eval`로 되돌린다 | https://github.com/ultralytics/ultralytics/blob/7142057731/ultralytics/nn/backends/base.py#L211-L212 |
| `.pt` | Ultralytics는 전체 checkpoint 언피클을 위해 `torch.load`를 `weights_only=False`로 감싼다 | https://github.com/ultralytics/ultralytics/blob/7142057731/ultralytics/utils/patches.py#L185-L197 |
| `torch.load` 안전성 | "uses pickle module implicitly, which is known to be insecure", "Only load data you trust" | https://docs.pytorch.org/docs/2.8/generated/torch.load.html |
| licence | Ultralytics 저장소는 `AGPL-3.0` | https://github.com/ultralytics/ultralytics/blob/main/LICENSE |

결론: 검수 앱이 직접 읽기에 안전한 것은 (1) `data.yaml`의 `names`(`yaml.safe_load`)와 (2) ONNX `metadata_props`의 `names`/`task`(`ast.literal_eval`, 코드 실행 없음)다. `.pt`는 torch와 ultralytics 패키지, 그리고 신뢰된 파일의 언피클이 필요하므로 앱 프로세스에서 열지 않는다. `.pt`는 모델 PC 쪽 도구가 `model.names`를 꺼내 YAML/JSON으로 내보내고, 앱은 그 파일만 받는다.

## 3. 도구별 비교

### 3.1 요약 표

| 도구 | 클래스 모델 | 스키마 변경 | 모델 라벨 → 프로젝트 라벨 | 예측과 사람 정답 분리 | 검수 흐름 | SPDX |
|------|------------|-------------|----------------------------|----------------------|-----------|------|
| CVAT | project/task label 목록 + label type + attributes | project 라벨을 task가 상속, 이후 수정 가능 | 이름 자동 매칭 + 매칭 UI, 미매칭 오류 | 자동 주석은 job에 shape로 들어감, "Clean old annotations" 선택 | annotation → validation → acceptance stage, issue/comment, consensus, GT/honeypot | `MIT` |
| Label Studio | labeling config XML의 `<*Labels>`/`<Label>` | 사용 중 라벨 삭제·타입 변경 불가 | `predicted_values`, 같은/소문자 이름 자동 매칭 | `predictions` 배열 분리, read-only, `model_version`, `score` | 검수(review) 흐름은 Enterprise 전용 | `Apache-2.0` |
| X-AnyLabeling | 라벨 파일/CLI/label manager, 모델별 config YAML `classes` | label manager로 rename/delete | config `classes`가 학습 라벨과 일치해야 함, `filter_classes` | 예측이 편집 가능한 shape + score로 들어감 | 검증 상태 토글(`Ctrl+Alt+K`) | `GPL-3.0` |
| AnyLabeling | (X-AnyLabeling과 같은 `anylabeling` 패키지 계열) | — | — | — | — | `GPL-3.0` |
| FiftyOne | `dataset.classes`, `default_classes`, `mask_targets`; annotate `label_schema` | annotation run(`anno_key`) 단위 기록 | (외부 backend로 위임) | 필드 분리(`ground_truth` vs 예측 필드), `evaluate_detections` | 외부 backend(CVAT/LS/Labelbox) + FP/FN view | `Apache-2.0` |
| labelme | `--labels` 쉼표 목록 또는 파일 | 파일 편집 | — | SAM/EfficientSAM 보조 | 없음 (단일 사용자 앱) | `GPL-3.0` |
| Supervisely | project meta의 Classes/Tags (project-wide) | — | — | — | Labeling Queues, reject → 원 작업자에게 반려 | SDK `Apache-2.0` |
| COCO Annotator | 전역 category를 만들고 dataset에 배정 | dataset 편집 | — | Magic Wand, DEXTR | 없음 | `MIT` |
| VIA | file/region attribute (dropdown/radio/checkbox) | 프로젝트 JSON | — | — | 없음 | `BSD-2-Clause` |
| Diffgram | label + attribute group/template, trigger | — | — | — | — | 사용자 정의 licence (SPDX 없음) |
| Roboflow (상용) | project class 목록, Lock Classes | rename/merge/delete가 전 이미지에 적용 | Label Assist "remap any class names" | — | Annotating → Review → Dataset, approve/reject | — |
| Encord (상용) | ontology: objects + classifications + nested attributes | shared class 편집은 breaking change 없음, 이력 보존 | — | — | — | — |
| Labelbox (상용) | ontology: objects, classifications, relationships, 재사용 feature | 사용 중 편집 시 구 라벨이 새 구조와 어긋날 수 있음, 사용된 feature는 archive만 | — | — | — | — |

### 3.2 CVAT

- **클래스 모델.** label은 name, color, attributes를 가지며 attribute 입력 타입은 SELECT, RADIO, CHECKBOX, TEXT, NUMBER다. label type은 any, cuboid, ellipse, mask, points, polygon, polyline, rectangle, skeleton, tag 등이다 (https://docs.cvat.ai/docs/api_sdk/sdk/reference/models/label/). project의 task는 label 목록을 상속하고 project의 label 목록은 나중에 바꿀 수 있다 (https://docs.cvat.ai/docs/workspace/projects/). Constructor와 JSON Raw 편집 두 방식이 있다 (https://docs.cvat.ai/docs/workspace/tasks-page/).
- **모델 라벨 매핑.** 자동 주석 실행 시 모델 라벨과 task 라벨을 맞추는 매칭 UI가 있고(예: 모델 `car` → task `vehicle`), threshold, "Return masks as polygons", "Clean old annotations" 선택지가 있다 (https://docs.cvat.ai/docs/annotation/auto-annotation/automatic-annotation/). SDK 자동 주석 함수는 `DetectionFunctionSpec`으로 라벨을 선언하고, driver가 이름으로 task 라벨에 맞추며 미매칭은 오류, `allow_unmatched_label=True`면 조용히 버린다 (https://docs.cvat.ai/docs/api_sdk/sdk/auto-annotation/).
- **ML backend 모양.** nuclio 함수는 `function.yaml`의 `metadata.annotations.spec`에 `{id, name, type}` 라벨 목록을 선언하고 `type: detector`다. handler는 base64 `image`와 `threshold`를 받아 JSON 결과를 돌려준다 (https://github.com/cvat-ai/cvat/blob/develop/serverless/onnx/WongKinYiu/yolov7/nuclio/function.yaml, https://github.com/cvat-ai/cvat/blob/develop/serverless/onnx/WongKinYiu/yolov7/nuclio/main.py). SAM은 `type: interactor`로, 양/음 클릭으로 마스크를 얻는다 (https://github.com/cvat-ai/cvat/blob/develop/serverless/pytorch/facebookresearch/sam/nuclio/function.yaml).
- **검수.** job stage는 annotation, validation, acceptance, 상태는 new, in progress, rejected, completed다. review mode에서 Issue 도구로 영역에 문제를 표시하고 comment를 달고 resolve/reopen한다 (https://docs.cvat.ai/docs/qa-analytics/manual-qa/). consensus는 replica job을 다수결로 병합하고 점수를 남긴다 (https://docs.cvat.ai/docs/qa-analytics/consensus/). 자동 QA는 Ground Truth job 또는 honeypot과 IoU 기반 비교로 품질 보고서를 만든다 (https://docs.cvat.ai/docs/qa-analytics/auto-qa/).
- **마스크 UX.** brush, eraser, polygon-to-mask, "remove underlying pixels", 크기·원/사각 모양, hide mask, `N`으로 저장 (https://docs.cvat.ai/docs/annotation/manual-annotation/shapes/annotation-with-brush-tool/).
- **단축키.** `Ctrl+0..9`로 라벨을 바꾸며 처음 10개 라벨만 키로 닿는다는 열린 이슈가 있다 (https://github.com/cvat-ai/cvat/issues/9219).
- **licence.** `MIT` (https://github.com/cvat-ai/cvat/blob/develop/LICENSE). 코드 재사용이 가능하지만 우리 스택(Django/React 앱)과 맞지 않아 실질적으로 아이디어 참고다.

### 3.3 Label Studio

- **클래스 모델.** labeling config XML이 클래스를 정의한다. `<Label>`은 `value`, `hotkey`("Automatically generated if not specified"), `alias`, `background`(색), `maxUsages`, `category`("Used in export to order labels for YOLO and COCO formats")를 가진다 (https://labelstud.io/tags/label). "You cannot remove labels or change the type of labeling being performed unless you delete any existing annotations that are using those labels" (https://labelstud.io/guide/setup).
- **ML backend.** `LabelStudioMLBase`를 상속해 `predict(tasks, context)`와 `fit(event, data)`를 구현하고 `self.model_version`, `self.label_interface`를 쓴다. 기본 `localhost:9090` 웹 서버다 (https://labelstud.io/guide/ml_create). YOLO 예제는 control 태그 속성 `model_path`, `model_score_threshold`를 읽고, 라벨은 같은(또는 소문자) 이름으로 자동 매칭하거나 `predicted_values="jeep,cab,limousine"`처럼 여러 모델 클래스를 한 라벨로 묶는다. `<BrushLabels>` 예측은 지원하지 않는다 (https://github.com/HumanSignal/label-studio-ml-backend/blob/master/label_studio_ml/examples/yolo/README.md).
- **예측과 정답 분리.** 예측은 task JSON의 별도 `predictions` 배열에 `model_version`, `score`와 함께 저장되고 "Predictions cannot be modified and are always read-only". 사람이 annotation을 만들 때 복사본으로 시작한다 (https://labelstud.io/guide/predictions).
- **검수.** Accept, Fix & Accept, Reject(No Rework / Return to Annotator / Pass to Another Annotator)와 review stream이 있으나 "The annotation review workflow is only available in Label Studio Enterprise Edition" (https://docs.humansignal.com/guide/quality).
- **마스크.** `BrushLabels` 결과는 RLE로 저장된다 (https://labelstud.io/tags/brushlabels).
- **단축키.** 제출 `ctrl+enter`, 라벨 `1-9` 자동 배정, `EDITOR_KEYMAP`으로 재정의 (https://labelstud.io/guide/hotkeys).
- **licence.** `Apache-2.0` (https://github.com/HumanSignal/label-studio/blob/develop/LICENSE, https://github.com/HumanSignal/label-studio-ml-backend/blob/master/LICENSE). 재사용 가능하나 아이디어 참고가 현실적이다.

### 3.4 X-AnyLabeling / AnyLabeling

- **모델 config.** 모델마다 YAML 하나: `type`(변경 불가, 예 `yolov5`, `yolo11_seg`), `name`, `display_name`, `model_path`, `conf_threshold`, `iou_threshold`, 선택 `filter_classes`, `max_det`, `agnostic`, `engine`, 그리고 "must match the training labels"인 `classes` 목록 (https://github.com/CVHub520/X-AnyLabeling/blob/main/docs/en/custom_model.md, 예: https://github.com/CVHub520/X-AnyLabeling/blob/a75f31f02e/anylabeling/configs/auto_labeling/yolo11s_seg.yaml).
- **클래스 출처.** YOLO 베이스 클래스는 `self.classes = self.config.get("classes", [])`로 config에서만 클래스를 읽는다. ONNX metadata에서는 `kpt_shape`만 읽는다 (https://github.com/CVHub520/X-AnyLabeling/blob/a75f31f02e/anylabeling/services/auto_labeling/__base__/yolo.py#L108, #L217). 즉 클래스 목록 중복 입력이 생기며, 우리가 ONNX metadata에서 끌어오면 그 단계를 줄일 수 있다.
- **검수/UX.** label manager(rename, delete, 표시, 색), `I` 모델 실행, `Q`/`E` SAM 양/음 점, `D`/`A` 이미지 이동, `Ctrl+Alt+K` 검증 상태 토글, `Ctrl+B` 일괄 실행. 예측은 score를 가진 편집 가능한 shape가 된다 (https://github.com/CVHub520/X-AnyLabeling/blob/main/docs/en/user_guide.md).
- **licence.** X-AnyLabeling `GPL-3.0` (https://github.com/CVHub520/X-AnyLabeling/blob/main/LICENSE), AnyLabeling `GPL-3.0` (https://github.com/vietanhdev/anylabeling/blob/master/LICENSE). 공개 저장소에 코드를 가져오면 GPL 의무가 생기므로 **아이디어만** 참고한다.

### 3.5 FiftyOne

- **클래스 모델.** `dataset.classes`는 필드별 클래스 목록, `dataset.default_classes`는 공통 목록이다 (https://docs.voxel51.com/user_guide/using_datasets.html). annotate의 `label_schema`는 필드별 `type`, `classes`, `attributes`, segmentation용 `mask_targets`(클래스 ↔ 픽셀 값)를 가진다 (https://docs.voxel51.com/integrations/annotation.html).
- **annotation run.** `annotate(anno_key, ...)`로 CVAT, Label Studio, Labelbox backend에 올리고 `load_annotations(dest_field=...)`로 되받으며 `list_annotation_runs()`, `delete_annotation_run()`으로 run 기록을 관리한다. `allow_additions`, `allow_deletions`, `allow_label_edits`, `allow_spatial_edits`로 편집 범위를 제한한다 (https://docs.voxel51.com/integrations/annotation.html).
- **예측 검토.** `evaluate_detections()`가 예측 필드와 정답 필드를 비교해 `eval_key`로 표본별 TP/FP/FN을 기록하고, `F("eval") == "fp"` 같은 view로 실수만 모은다 (https://docs.voxel51.com/user_guide/evaluation/index.html). 앱 내 편집은 auto-save, undo/redo를 가진다 (https://docs.voxel51.com/user_guide/annotation.html).
- **licence.** `Apache-2.0` (https://github.com/voxel51/fiftyone/blob/develop/LICENSE). MongoDB 기반 런타임은 우리 제약과 맞지 않아 개념만 가져온다.

### 3.6 labelme

`--labels a,b` 또는 `--labels labels.txt`로 라벨 목록을 주고, 이미지 flag, 자동 저장, SAM/EfficientSAM 점→polygon/mask, YOLO-world/SAM3 텍스트→주석, JSON 출력과 `~/.labelmerc` 설정을 가진다 (https://github.com/wkentaro/labelme/blob/main/README.md). licence `GPL-3.0` (https://github.com/wkentaro/labelme/blob/main/LICENSE). 아이디어만.

### 3.7 Supervisely

Classes와 Tags는 project meta(`meta.json`)에 project-wide로 정의된다 (https://developer.supervisely.com/getting-started/supervisely-annotation-format/project-structure). Labeling Queues는 "Confirm and pull next"로 다음 항목을 받고, reviewer가 반려한 항목은 원 작업자에게 돌아간다 (https://docs.supervisely.com/labeling/jobs/labeling-queues). SDK 저장소는 `Apache-2.0` (https://github.com/supervisely/supervisely/blob/master/LICENSE). 플랫폼 본체 licence는 이번 조사 범위에서 확인하지 않았다.

### 3.8 COCO Annotator

category를 전역으로 만든 뒤 dataset 생성·편집 시 배정한다 (https://github.com/jsbroks/coco-annotator/wiki/Usage). Magic Wand(flood fill)와 DEXTR 도구가 있다 (https://github.com/jsbroks/coco-annotator/wiki). licence `MIT` (https://github.com/jsbroks/coco-annotator/blob/master/LICENSE). GitHub API 기준 마지막 push는 2025-01-30이다 (https://api.github.com/repos/jsbroks/coco-annotator).

### 3.9 VIA

설치 없는 단일 HTML 파일, file/region attribute(dropdown, radio, checkbox), JSON 프로젝트 파일 (https://www.robots.ox.ac.uk/~vgg/software/via/). licence `BSD-2-Clause` (https://gitlab.com/vgg/via/-/raw/master/LICENSE). "빌드 없는 정적 웹앱"이라는 점에서 우리와 가장 닮았다.

### 3.10 Diffgram

attribute는 dropdown, multiple select, free text, radio이고 label별 group, 재사용 template group이 있다 (https://diffgram.readme.io/docs/attributes-1). trigger로 특정 라벨에서만 attribute를 보인다 (https://diffgram.readme.io/docs/contextual-annotation-triggers). licence는 SPDX가 아닌 자체 문서로, 일정 규모 이상 회사는 별도 계약이 필요하고 "Deployed Usage or Contribution" 외의 복제·파생을 금한다 (https://github.com/diffgram/diffgram/blob/master/LICENSE.md). **코드·문구 모두 가져오지 않는다.**

### 3.11 상용 UX 참고

- **Roboflow.** class rename/merge(같은 이름으로 rename), delete는 모든 이미지의 해당 주석을 지우며 되돌릴 수 없음, "Lock Classes"로 주석 중 새 클래스 생성 금지 (https://docs.roboflow.com/datasets/manage/manage-datasets/manage-classes.md). Label Assist는 모델 클래스 이름을 "remap any class names" 한다 (https://docs.roboflow.com/datasets/annotate/annotate/ai-labeling/model-assisted-labeling.md). 작업은 annotating → review → dataset, 반려는 작업자에게 돌아간다 (https://docs.roboflow.com/datasets/annotate/annotate/manage-annotation-workflow.md). 단축키: `b` box, `p` polygon, `s` smart polygon, `←/→` 이전/다음, `meta+z` undo, review mode에서 `a` approve, `r` reject (https://docs.roboflow.com/datasets/annotate/annotate/use-roboflow-annotate/keyboard-shortcuts.md).
- **Encord.** ontology는 objects(box, polygon, bitmask 등)와 classifications(checklist, radio, text, numeric), 중첩 attribute로 구성된다. shared class 편집은 "does not introduce breaking changes"이고 변경 이력이 남는다 (https://docs.encord.com/platform-documentation/Annotate/annotate-ontologies/annotate-ontologies.md).
- **Labelbox.** ontology는 objects, classifications, relationships이며 feature를 여러 ontology가 공유하고 수정이 모두에 전파된다. 사용 중 ontology를 고치면 "annotations created with the old version will remain, but they may no longer align with the new structure", 사용된 feature는 삭제 대신 archive만 된다 (https://docs.labelbox.com/docs/labelbox-ontology).

## 4. 축별 정리

### 4.1 클래스 집합 모델

- 모든 도구가 클래스 목록을 **프로젝트(또는 작업) 단위**로 둔다: CVAT project/task, LS config, Supervisely meta, COCO Annotator dataset, Roboflow project. 우리 workspace도 같은 단위가 맞다.
- 클래스에는 거의 공통으로 `name`, `color`, 선택 `hotkey`, 표시 `alias`가 붙고 export 순서를 따로 갖는 경우가 있다(LS `category`). YOLO는 순서(index)가 곧 계약이므로 index를 명시 필드로 가져야 한다.
- 스키마 변경 처리는 셋으로 갈린다. (a) 사용 중 변경 금지(LS), (b) 변경을 전체 이미지에 즉시 적용(Roboflow rename/delete), (c) 공유 ontology 변경 전파 + 이력(Labelbox, Encord). 우리의 동결 export·CAS와 맞는 것은 (a)에 가까운 **불변 버전**이다: 바꾸면 새 sha의 새 클래스 집합이 생기고, 옛 승인 결과는 옛 sha에 묶여 남는다.

### 4.2 모델 라벨 → 프로젝트 라벨

- 세 가지 방식이 있다: 이름 자동 매칭(CVAT driver, LS YOLO backend), 명시 매핑 UI/속성(CVAT 매칭 UI, LS `predicted_values`, Roboflow remap), 모델 config에 클래스 목록 재기입(X-AnyLabeling).
- 미매칭 처리는 CVAT SDK처럼 **기본 오류, 명시 시 버림**이 가장 안전하다.

### 4.3 예측과 사람 정답 분리

- LS: 별도 `predictions` 배열, read-only, `model_version`, `score`. FiftyOne: 별도 필드 + 평가 run. CVAT·X-AnyLabeling: 예측이 곧 편집 가능한 shape가 된다(분리 약함).
- 우리 앱은 이미 원본 후보(LiDAR `objects`, 모델 `boxes`)와 사람 review를 분리하고 "자동·초안 라벨"을 사람이 확인해야 다시 가져온다(`review-app.md`). LS 방식과 같은 방향이며, 누락은 후보에 `model_id`/`class_set_sha`/`score` provenance가 없다는 점이다.

### 4.4 검수 흐름

- 상용·대형 도구는 다단계 stage(CVAT), 작업자/검수자 역할(Supervisely, Roboflow, LS Enterprise), consensus·GT·honeypot(CVAT)를 둔다. 모두 다중 사용자 전제다.
- 단일 운영자에게 남는 핵심은 셋이다: **대기열 필터**, **승인 후 다음 항목 자동 이동**(Supervisely "Confirm and pull next"), **영역 단위 메모**(CVAT issue). 우리 상태 `pending/approved/excluded`는 이미 충분하다.

### 4.5 마스크 편집 UX

- 공통 도구: brush, eraser, 크기, polygon→mask 채우기, 마스크 숨김/불투명도, undo(CVAT, FiftyOne, Roboflow). 클릭형 SAM(CVAT interactor, X-AnyLabeling `Q`/`E`, labelme).
- 우리 `pixels.js`는 brush, eraser, opacity, undo를 이미 가진다. 인덱스 마스크는 픽셀당 클래스 하나라 CVAT의 "remove underlying pixels" 문제가 원래 없다.

### 4.6 licence 결론

| 범주 | 도구 | 우리에게 |
|------|------|---------|
| 허용적 | CVAT `MIT`, COCO Annotator `MIT`, VIA `BSD-2-Clause`, Label Studio `Apache-2.0`, FiftyOne `Apache-2.0`, Supervisely SDK `Apache-2.0` | 작은 조각 재사용 가능(고지 유지). 그래도 스택이 달라 실제로는 아이디어 위주 |
| copyleft | X-AnyLabeling, AnyLabeling, labelme `GPL-3.0`, Ultralytics `AGPL-3.0` | 코드 복사 금지, 아이디어·파일 형식만. Ultralytics는 모델 PC 학습 도구로만 쓰고 앱에서 import하지 않는다 |
| 비표준 | Diffgram 자체 licence | 사용하지 않는다 |
| 상용 | Roboflow, Encord, Labelbox | 공개 문서의 UX 개념만 |

## 5. Pinky 검수에 들일 패턴 (순위순)

### 5.1 버전 있는 클래스 집합 record (필수)

`review_masks.bind_classes`를 일반화한다. 한 record:

```yaml
class_set:
  id: lane_lr_v1            # 사람이 읽는 이름
  task: detect | segment | semantic   # semantic = 인덱스 픽셀 마스크(lane 등)
  classes:                  # index 순서가 계약 (YOLO names)
    - {index: 0, name: background, display: 배경, color: "#000000", hotkey: "1"}
    - {index: 1, name: left_lane,  display: 왼쪽 차선, color: "#..."}
    - {index: 2, name: right_lane, display: 오른쪽 차선, color: "#..."}
  ignore_index: 255         # semantic만
  source: {kind: data_yaml | onnx_metadata | classes_yaml | manual, sha256: <원문 sha>}
sha256: <정규화 JSON의 sha>
```

- SQLite `class_sets(sha PRIMARY KEY, id, task, body)` 한 표. 수정 API는 없고 새 sha만 추가한다(LS의 "사용 중 변경 금지", Labelbox 경고에서 얻은 교훈).
- 각 frame review와 승인 event, sealed export 영수증에 `class_set_sha`를 기록한다. export 검증은 `OBJECT_CLASSES` 대신 그 frame의 class set으로 한다(`review_app.py:104`).
- 서버가 `/api` 응답에 class set을 내려 주고 `app.js:6`의 `names` 맵을 지운다. 한국어 표시명은 record의 `display`.
- 출처: 4.1, Label Studio setup, Labelbox ontology, Encord 이력.

### 5.2 Ultralytics에서 클래스 집합 가져오기 (필수)

- `data.yaml`: `yaml.safe_load` 후 `names`(dict 또는 list)를 index 순으로 정렬. task는 인자로 받는다.
- ONNX: `onnx` 없이 읽기 어렵다면 모델 PC 도구가 `metadata_props`의 `names`, `task`를 `ast.literal_eval`로 꺼내 YAML로 넘긴다(Ultralytics `base.py#L211-L212`와 같은 방식).
- `.pt`: 앱에서 열지 않는다(pickle, AGPL). 모델 PC에서 `YOLO(path).names`를 YAML로 내보낸다.
- 기존 픽셀 `classes.yaml`은 `source.kind: classes_yaml`로 그대로 들어온다.
- X-AnyLabeling처럼 클래스 목록을 손으로 다시 적는 단계를 없애는 것이 목적이다.

### 5.3 모델별 매핑 표 (필수)

```yaml
model_mapping:
  model: {id: yolo11n_obj_2026xx, class_set_sha: <모델 자체 집합>}
  target_class_set_sha: <검수 집합>
  map: {person: drop, cone: cone, box: obstacle_box}
  unmatched: error          # 기본. CVAT SDK allow_unmatched_label 과 같은 의미
```

- `prelabel.py`/`autolabel.py`가 후보를 쓸 때 매핑을 적용하고 매핑 sha를 후보 provenance에 남긴다. 이름이 같으면 자동 제안하되 저장은 명시 표로만 한다(CVAT 매칭 UI, LS `predicted_values`, Roboflow remap).
- 여러 모델 라벨 → 한 라벨(`predicted_values="jeep,cab"`)을 허용하고, 한 모델 라벨 → 여러 라벨은 허용하지 않는다.

### 5.4 예측과 사람 정답 분리 강화 (필수, 작음)

- 후보에 `model_id`, `class_set_sha`, `mapping_sha`, `score`를 붙이고 읽기 전용으로 둔다. 사람 review는 지금처럼 별도 객체다(LS `predictions` read-only, `model_version`).
- "자동·초안 라벨"은 계속 복사본을 만들고 미승인 상태로 돌린다. 승인 판정은 사람 review만 본다.

### 5.5 단축키 (권장)

| 키 | 동작 | 근거 |
|----|------|------|
| `1`–`9` | 선택 박스/브러시의 클래스를 class set index 순 1–9번으로 | LS 자동 `1-9`, CVAT `Ctrl+0..9` |
| `A` | 승인 (전체 확인 체크가 끝난 경우만) | Roboflow review `a` |
| `X` | 제외 | (우리 동작 이름) |
| `←` / `→` | 이전/다음 (현재 필터 안에서) | Roboflow 화살표 |
| `Ctrl+Z` / `Ctrl+Shift+Z` | undo / redo | Roboflow `meta+z` |
| `Esc`, `Delete` | 기존 동작 유지 | `review-app.md` |

- 클래스가 10개를 넘으면 숫자키로 닿지 않는다(CVAT 이슈 #9219). 그 경우 드롭다운이 기본이고 `hotkey` 필드로 명시 배정한다.
- 숫자 입력 칸 포커스에서는 단축키를 끄는 현재 규칙(Delete)과 같이 처리한다. X-AnyLabeling은 `A`가 "이전 이미지"이므로 그 습관이 있는 운영자에게 혼동 가능성이 있다고 운영 문서에 적는다.

### 5.6 대기열과 다음 항목 (권장)

- 필터 `pending`이 기본, 승인/제외 직후 다음 `pending`으로 이동(Supervisely "Confirm and pull next"). 브랜치 `uiux/pinky-review-local-run`의 auto-advance가 이미 이 방향이므로 class set 필터(같은 sha만)를 추가하는 정도다.
- 다단계 stage(annotation → validation → acceptance)는 들이지 않는다. 우리 `pending/approved/excluded` + 명시 승인이 이미 acceptance 역할이다.

### 5.7 모델-사람 불일치 순 정렬 (선택)

FiftyOne `eval_key`처럼 승인된 사람 정답과 새 모델 후보를 비교해 FP/FN이 많은 frame을 먼저 보이게 한다. 학습 루프 D-356의 평가와 같은 IoU 규칙을 재사용해야 하므로, 평가 코드가 이미 있을 때만 한다.

### 5.8 frame 메모 (선택)

CVAT issue처럼 frame에 짧은 메모(좌표 선택)를 events 표에 남긴다. 제외 사유 기록에 쓸모가 있으나 필수는 아니다.

### 5.9 마스크 도구 (선택)

polygon→mask 채우기 하나만 추가 후보다. SAM 클릭은 앱이 모델을 호출하지 않는다는 D-459 경계와 충돌하므로, 모델 PC에서 미리 계산한 후보 마스크를 가져오는 방식으로만 한다(5.4의 후보 분리 규칙 적용).

## 6. 들이지 않을 것

- **서버 플랫폼 배포** (CVAT, Label Studio, FiftyOne+MongoDB, nuclio, Docker 스택): 우리는 단일 PC, 표준 라이브러리 서버, 빌드 없음이 계약이다.
- **다중 사용자 역할·consensus·GT·honeypot**: 단일 운영자 전제. CVAT consensus/auto-QA는 대규모 외주용이다.
- **앱 안의 live ML backend** (LS `predict`, CVAT serverless, X-AnyLabeling `I` 실행): D-459는 앱이 로봇·모델 API를 부르지 않는다고 정했다. 추론은 모델 PC 도구, 앱은 결과 파일만 읽는다.
- **변경이 전파되는 공유 ontology** (Labelbox): 동결 export와 충돌한다. 불변 sha가 맞다.
- **클래스 delete가 기존 주석을 지우는 동작** (Roboflow): 승인 이력 손실. 새 class set + 매핑으로 대신한다.
- **attribute 체계 전체** (CVAT/Encord/Diffgram 중첩 attribute): 지금 필요한 attribute는 신호등 상태 하나이고 이미 있다. 두 번째 attribute가 생길 때 다시 본다.
- **GPL/AGPL/Diffgram 코드 복사**: 4.6.
- **앱에서 `.pt` 언피클**: 2절.

## 7. 열린 점

1. `manifest.py:179`의 `object_det` 순서 계약. 검수 class set이 `OBJECT_CLASSES`와 다른 모델(예: lane 3-class, 새 detect 집합)은 배포 manifest의 다른 role/계약이 필요하다. 이것은 검수 앱이 아니라 manifest/ADR 결정이며, class set 도입 ADR이 이 경계를 적어야 한다.
2. 한 frame을 여러 class set으로 검수할 수 있는가(같은 사진을 object 집합과 lane 집합으로). 권고는 "frame × class_set" 단위 review row다. 현재 `frames` 표의 키를 바꾸는 변경이므로 마이그레이션 계획이 필요하다.
3. 기존 승인 결과의 class set sha 소급. 현재 승인분은 `OBJECT_CLASSES`와 바인딩된 `classes.yaml` sha로 기록하는 일회성 마이그레이션이면 충분하다.
4. 이번 조사는 Encord의 feature hash, Supervisely 플랫폼 licence, Label Studio 기본 브러시 단축키를 1차 출처에서 확인하지 못했다.
