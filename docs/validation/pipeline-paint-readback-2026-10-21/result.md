# Paint 모델 소비 readback

## 변경 범위

기준 commit `c42fa0260f1fdc1e9e602294c9e4d30feb99f8b4`에서 lane_seg paint는 consumer가 있는데도 no_node로 기록됐다. 현재 producer의 volatile `line/keep_debug`는 실제 소비한 `paint_model_revision`을 출력한다. 새 readback은 이 frame과 수집 전후의 pointer를 대조한다.

learned/learned_drivable 소비·비어 있지 않은 revision·유한한 음이 아닌 stamp가 있어야 모델 사용 증거로 읽는다. fallback/null/malformed/timeout은 unavailable, 다른 모델은 mismatch, 전후 pointer가 바뀌거나 사후 읽기가 실패하면 unavailable이다. paint의 서명은 unknown이며 기존 latched shadow/object_det·전달 exit 계약을 유지한다.

## 커밋과 원격 시험

| source | 검사 | 결과 |
|---|---|---|
| `53fc1f423e` | paint readback 회귀 RED | 15 failed / 9 passed, native AI 시험 PC, runner exit1 |
| `3e315715b2` | readback/deliver/task/paint source 4파일 | 154 passed / 1 skipped, runner exit0, known-failures NEW0 |
| 같은 `3e315715b2` | paint source skip 조사 | 24 passed / 1 skipped, runner exit0 |
| 같은 `3e315715b2` | 단일 ONNX Runtime session-options 시험 verbose | 1 skipped, 해당 optional dependency 시험 미실행 확인 |

각 실행은 다른 invocation이므로 합산하지 않는다. source 회귀는 subprocess runner fixture를 통해 기존 CLI/journal과 연결한다. 실제 ROS CLI의 직렬화·발견, 실제 장치 상태·서명·모델 정확도·FIELD 수용은 이 기록의 범위 밖이다.

시험 경로:

- `test/learning/perception/test_model_promote_readback.py`
- `test/learning/perception/test_model_deliver.py`
- `test/learning/perception/test_model_deliver_tasks.py`
- `middleware/perception/test/test_lane_paint_source.py`

## 검토와 원본

독립 검토자 `paint_readback_branch_review`가 기준점부터 `3e315715b2`까지의 전체 diff, deliver→after_change→read_back→record, 실제 producer와 worker provenance를 읽었다. Critical/Important/Minor 발견은 없었다. 검토 자체는 원격 시험·장치 접근을 수행하지 않았으며 안전/운영 수용 승인으로 사용하지 않는다.

로컬 실행 ledger와 원본 run-N 로그는 저장소 밖 `<session-scratch>/pipeline-completion-20261021/`의 `b2-red`, `b2-green`, `b2-paint-skip-reason`, `b2-ort-skip`에 보존한다. main 착지·push 결과는 이후 실제 landing 기록과 구분한다.
