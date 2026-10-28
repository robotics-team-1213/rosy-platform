---
module: learning/training/omx + deploy/robot/pinky_pro/image
date: 2026-10-26
last_updated: 2026-10-28
problem_type: workflow_issue
component: testing_framework
severity: high
tags: ["land", "full-tier", "pytest", "sys.path", "sys.modules", "test-isolation", "main-red", "standalone-cli"]
applies_when: "시험이 원본 모듈을 importlib.util.spec_from_file_location으로 읽거나 conftest가 제품 경로를 보충할 때, 원본이 형제 모듈을 맨 이름으로 import할 때, 또는 FULL이 초록인데 파일 단독이나 실제 CLI가 실패할 때"
---

# 폴더 단위 pytest 초록은 파일 하나의 초록이 아니다

## 증상

`feat/learning-storage-pool`이 FULL 착지(10-26 12:16, main e6e7c47b3c)를 통과했는데, 그 뒤 착지들의 좁은 선택에서 `learning/training/omx/test/test_native_cycle.py`가 26 ERROR(`ModuleNotFoundError: experiment_dataset`)를 냈다. 착지 기록에는 이 파일이 들어 있는 `learning/training/omx/test` 폴더 호출이 착지 직전 후보와 사전 준비 두 번 모두 `419 passed, 21 skipped`로 남아 있다. 캐시 재사용, known_failures·FLAKY 매칭, ERROR 집계는 관련이 없었다.

## 원인

4030c29401이 `native_cycle.py`에 `from experiment_dataset import dataset_lease`(형제 모듈 맨 이름 import)를 넣었다. 시험은 `native_cycle.py`를 `spec_from_file_location`으로 읽으므로 그 폴더가 `sys.path`에 없다. 폴더 전체를 한 pytest 프로세스로 돌리면 앞서 수집되는 형제 시험 모듈(`test_act_job.py:8`, `test_experiment_dataset.py:10` 등)이 모듈 최상위에서 `sys.path.insert(0, <omx 폴더>)`를 하고, `test_experiment_dataset.py`는 `experiment_dataset`을 `sys.modules`에 올려 둔다. 수집이 모든 실행보다 먼저 끝나므로 이름순과 무관하게 import가 성공한다. 파일을 혼자, 또는 그런 형제 없이 묶어 돌릴 때만 실패한다.

FULL 계층(`full_invocations`)은 모듈 폴더 단위로 호출을 만들고, affected 계층은 파일을 묶어(pack) 호출을 만든다. 어느 쪽이든 결과가 "같은 프로세스에 누가 함께 있었나"에 달려 있다. D-790의 LOAD-FLAKY 재실행은 "묶음에서 실패, 혼자 통과"만 다루고, 반대 방향("묶음에서 통과, 혼자 실패")은 어떤 계층도 보지 않는다.

## 확인 근거

- 원격 5e162cca21: `learning/training/omx/test/test_native_cycle.py` 혼자 exit 1, ERROR 26. `learning/training/omx/test` 폴더 exit 0.
- `.git/rosy-land-cache.jsonl`: commit e6e7c47b3c, argv `["learning/training/omx/test"]`, log `%TEMP%/rosy-land/feat-learning-storage-pool/run-1-3.txt`(11:57, 실제 실행, 19.88 s). 사전 준비 3957d15507 `run-pre-3.txt`(07:43)도 같은 결과.
- 이 착지에는 `.git/rosy-land/<sha>.json` 착지 기록이 없다. FULL을 잠금 밖에서 돌린 착지는 `full_main` 분기에서 `reusable = False`가 되어 기록을 쓰지 않았기 때문이다. 이 결함은 `fix/land-record-after-prepare`에서 고쳤다([[land-record-stopped-when-tests-moved-before-the-turn-2026-10-26]]). 그 전 착지의 증거는 land_cache와 로그 폴더에서 찾는다.

## 해결

이번 건은 `fix/native-cycle-import-path`가 원본 모듈이 자기 폴더를 `sys.path`에 넣게 해 고친다. 같은 부류를 막으려면 경로 지정 로드 대상 모듈이 맨 이름 형제 import를 하지 않거나 자기 폴더를 스스로 넣어야 한다.

## collect-only로는 부족하다 (착지 게이트 설계, 2026-10-26)

- 수집 게이트(선택된 시험 파일마다 따로 `pytest --collect-only`)는 이 사고를 잡지 못한다. `test_native_cycle.py`는 `native_cycle.py`를 픽스처 안에서 `spec_from_file_location`으로 읽으므로 import 실패가 수집이 아니라 실행 때 난다. 사고 재현(6a07a06b0f 이전 `native_cycle.py`, 원격): 폴더 실행 419 passed, 파일 단독 실행 ERROR 26, 수집 게이트 `learning/training/omx/test` 31 passed(초록).
- 잡은 것은 바뀐 원본을 참조하는 시험(D-436 셀렉터의 `references X` 간선)을 파일마다 따로 끝까지 돌리는 단독 실행이다. `native_cycle.py`를 참조하는 시험은 7개이고 `test_native_cycle.py`가 그 안에 든다.
- 그래서 `tools/land_isolation.py`는 착지 준비 단계에서 수집 게이트와 함께 참조 시험 단독 실행(안전 태그 원본의 참조 시험 먼저, 개수 상한 없이 시간 상한, 못 돈 파일은 `<git-common-dir>/rosy-land-isolation.jsonl`에 기록)을 돌린다. 수집 게이트만으로 충분하다고 다시 제안하지 않는다.

## pytest 파일 단독 실행도 실제 CLI를 대신하지 않는다 (2026-10-28)

고정 소스 `7b3245d3c594a8b5856ad791a334e1e342be6bdb`의 FULL과 관련 원격 시험은 통과했지만,
실제 native ARM [이미지 실행 40632587457](https://github.com/robotics-team-1213/rosy-platform/actions/runs/40632587457)
attempt1/job122632180302는 이미지 생성 전 lock 해석에서 실패했다.
`resolve-build-lock.py` → `os_cms_trust.py` → `os_rauc.py` → `os_update_manifest.py`의
`from signing import verify_signature`가 `ModuleNotFoundError`를 냈다.

`test/conftest.py`가 `deploy/robot/pinky_pro/release/`를 pytest 경로에 넣었으므로 시험 파일을 혼자 돌려도 이 누락은 보이지 않았다.
`export-os-bundle-inputs.py`에도 같은 누락이 있었다. 두 CLI는 서로 다른 Python 프로세스이므로
앞선 CLI에서 경로를 고쳐도 뒤의 exporter에 전달되지 않는다.

두 진입점이 각자 필요한 `release/` 경로를 명시하게 고쳤다. 회귀 검사는 빈 임시 cwd에서
`sys.executable -I <실제 CLI> --help`를 실행해 `PYTHONPATH`를 무시한다. pytest의 `sys.path`나
이미 import한 `sys.modules`가 자식에 새어 들어가 통과할 수 없게 한다.
빌드 인증서·지문·소유권 검사와 native ARM 거절 조건은 바꾸지 않았다.

근거는 Git 밖의 로컬 receipt `Rosy/artifacts/receipts/2026-10-27-full-os-integration/`에 보존했다.
`native-image-40632587457/image-failed/`에는 인증된 API 상태와 실제 실패 step 로그가 있다.
`image-cli-import-red/run-1.txt`와 `image-cli-export-red/run-1.txt`는 각각 같은 누락으로 실패했다.
`image-cli-import-green/run-1.txt`는 20 passed/0 skipped,
`image-cli-export-green/run-1.txt`는 CMS·resolver·exporter·signer 43 passed/0 skipped, classifier 0 NEW다.
수정 검증 SHA `b515fb03c86ea96896e00eb71106524f24be8777`, `28f95ef47e45c6346196dbdf173026954e73c63d`는
이 기록을 쓸 때 아직 게시 전인 로컬 커밋이다. 이 결과는 독립 CLI import와 원격 기능 검증이며,
다음 native ARM 이미지 생성·SD·실물 부팅 성공을 뜻하지 않는다.

`resolve-build-lock.py` 전체 명령은 x86 시험 PC에서 native ARM gate에 걸린다.
플랫폼을 속인 실행을 실제 native 명령의 증거로 쓰지 않는다. 독립 helper import 검증과
향후 실제 native resolve/build 검증을 구분한다.

## 다음에 적용할 조건

- 착지 뒤 main에서 파일 하나가 빨간데 착지 기록·캐시가 초록이면, 먼저 그 파일을 혼자 원격 실행하고 폴더 실행과 비교한다. 캐시나 known_failures부터 의심하지 않는다.
- 시험 모듈 최상위의 `sys.path.insert`와 `sys.modules` 적재는 같은 프로세스의 다른 시험 파일 전부에 새어 나간다. 원본 모듈이 import 경로를 시험의 부작용에 기대지 않는지 파일 혼자 실행으로 확인한다.
- `spec_from_file_location`으로 읽히는 모듈에 형제 import를 추가하는 변경은, 해당 시험 파일을 혼자 돌린 결과를 검증 근거로 남긴다.
- conftest가 경로를 보충하는 CLI는 파일 단독 pytest만으로 충분하지 않다. 실제 진입점을 빈 cwd의 격리된 자식 프로세스에서도 실행한다.
