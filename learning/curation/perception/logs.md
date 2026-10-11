# perception_curation verification log

2026-10-11: D-637 folder move in progress; committed-SHA verification pending.

2026-10-11: source d4988bffba landed on local main after independent review, remote regressions/known_failures 0 NEW and installed wheel/sdist/HTTP proof. SOURCE/LOCAL GO only; CI FULL and ROS-SIM/ARM64/device/field remain unverified. See docs/validation/d637-remaining-folders-2026-10-11/result.md.

2026-10-11: D-663 semantic 보존/검증과 새 road_surface_v1 classes를 추가했다. 6353771b7 원격 builder/export/intake 관련 회귀 terminal exit 0, NEW 0. 실제 road_surface 독립 검수와 승인·새 dataset publication은 미완료다.

2026-10-12: `reclaim.py`는 검증된 학습 영상 또는 검증된 compact bag이 있는 raw 세션만 `--apply`로 지운다. b7dc4f511의 `test/learning/perception/test_reclaim.py`를 모델 PC에서 실행해 10 passed, `known_failures.py` 0 NEW. 이 PC의 9.4 GB raw는 아직 지우지 않았다.

2026-10-12: `media_pipeline.py`가 학습 잡 앞에 scan, video, verify, reclaim, receipt 단계를 둔다. 027013563의 media/reclaim/recording_job 시험 39 passed, `known_failures.py` 0 NEW. 이 PC 원본에 대한 dry-run 영수증은 trainable 10, applied false다. raw는 지우지 않았다.

2026-10-12: 같은 경로에 `--apply`를 실행했다. 영수증은 trainable 10, applied true, raw_state removed 10이다. 학습 mp4 22개는 그대로고, `.compact` 두 폴더(8kcn 58.9 MB, 9dfk 30.7 MB)만 raw 아래에 남았다.

2026-10-12: e15b44f5d는 영상이 확인되면 raw가 이미 없는 `.compact`도 `--apply`로 지운다. `test_reclaim.py`와 `test_media_pipeline.py` 21 passed (`X:\DevTemp\reclaim-compact\run-1.txt`). 같은 경로 영수증은 sessions 0, applied true, compact_state removed 2(8kcn, 9dfk)다. 2026-09-28 upright 검증 영상 두 개(640×480)는 그대로 두었다.

2026-10-12: D-681 source `c7afe628ca`는 선택적 model feedback export를 기존 녹화 사건에 정확한 robot/case·content hash로 연결한다. 기존 bind/schema1과 검수 정답은 유지하며 모델 근거는 UNREVIEWED다. 실제 export→binder·CLI·한글 해시·비용/종결 무결성·크기/폴더 경계의 관련 원격 87 passed, exit 0, NEW 0. 경로는 `docs/plans/2026-10-12-model-improvement-feedback.md`; 실제 현장 데이터·학습·품질·승격은 수행하지 않았다.
