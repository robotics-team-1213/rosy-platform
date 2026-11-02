---
module: tools/publish_main.py
date: 2026-11-02
last_updated: 2026-11-03
problem_type: workflow_issue
component: landing_pipeline
severity: medium
tags: ["publish", "land", "FULL", "LOAD-FLAKY", "batch", "browser", "evidence"]
applies_when: "기존 게시 PR이나 FULL 착지 기록으로 로컬 변경을 공개하려 할 때: 포함 범위와 실제 시험 근거를 함께 확인한다"
---

# 기존 게시 PR도 포함 범위와 FULL 실행 근거를 확인한다

## 증상

2026-11-02 `feat/review-gate`를 로컬 main에 착지한 뒤 바로 게시하려 했다. `publish_main.py`가 "green FULL 기록 없음"으로 거부했다. FULL 기록을 만들려고 다음을 차례로 시도했고 모두 기록을 남기지 못했다.

1. main 끝과 같은 브랜치로 `land_async.py --tests full --no-cache`: 이미 main에 든 브랜치라 시험 없이 `== landed in a batch`로 끝났다.
2. 빈 커밋을 얹어 다시 FULL: 약 11시간 브라우저 chunk를 돌던 중 준비 단계에서 `test_ws_teleop.py::test_disconnect_after_motion_applies_zero`가 LOAD-FLAKY로 나왔다. 명시 FULL은 LOAD-FLAKY 하나로 저장·착지가 막힌다(`docs/reference/pr-pipeline.md`).
3. 그 시험을 고친 커밋으로 다시 FULL: 이번엔 `test_station_camera_scheduling.py`의 다른 시험이 LOAD-FLAKY였다.

그동안 다른 세션의 게시 PR(#227)이 이미 내 착지를 포함한 SHA로 열려 `ci-result`·`review-gate`가 녹색이었고 실제로 병합됐다. 그러나 2026-11-03 후속 검토에서 그 head의 FULL 기록에 연결된 보고서 73개 중 9개가 전부 skip이며 opt-in 브라우저 실행이 없음을 확인했다. **병합 성공은 자동화가 받아들였다는 사실이며, 적격 FULL을 입증하지 않는다.** 이전 문서의 "그 PR을 병합하자 끝났다"는 해석은 이를 구분하지 못했다.

## 원인

게시는 로컬 main 전체를 올리는 공동 작업이므로 기존 PR을 먼저 확인해야 한다. 한편 당시 `green_full()`은 tier와 base ancestry만 확인했다. FULL 표시는 있었어도 등록된 브라우저 chunk·ALONE 실행과 보고서의 실제 대응을 입증하지 않았다. 준비 단계의 로그 정보도 최종 기록에 충분히 남지 않았고, 당시 `--no-cache`는 새 성공 결과의 cache 행까지 버렸다. CI 녹색이나 tier 문자열로 이 공백을 대신할 수 없다.

준비한 FULL을 재사용할 때는 그 뒤 자신의 새 코드가 추가되지 않았는지도 확인해야 한다. 또 같은 branch의 보고서 경로는 재실행 때 덮어써질 수 있어, 경로만 같다는 이유로 과거 후보의 근거로 쓸 수 없다.

## 해결과 다음에 할 일

- 착지 뒤 먼저 열린 게시 PR을 확인하고, **실제 게시 head에 요청한 착지가 모두 포함되는지와 적격 FULL 근거를 각각 확인한다.** 둘 다 충족하고 같은 head의 필수 CI·독립 검토도 완료됐을 때만 병합한다. 과거의 병합 성공이나 오래된 도구의 dry-run 성공을 현재 검증 대신 쓰지 않는다.
- FULL 근거는 불변 후보의 정본 호출·브라우저 chunk/ALONE 계획과 실행 당시 commit·tree·환경·argv·로그 내용의 대응이 있어야 한다. 준비 후보를 쓴다면 기존 main 병합 bridge 조건도 유지해야 한다. 로그 내용의 SHA-256이 없거나 달라진 기록은 거부한다. 캐시·보고서가 정리돼 근거가 사라졌을 때도 통과로 추정하지 않는다.
- 열린 PR이 요청한 변경이나 적격 근거를 갖추지 못했다면 필요한 변경을 포함해 정본 FULL을 수행한다. 이미 main에 든 브랜치의 조기 종료나 빈 커밋은 실제 시험의 대안이 아니다. `--no-cache`는 재사용을 끄되 새로 실행한 clean 근거는 보존해야 한다.
- LOAD-FLAKY나 불완전 실행을 적격 FULL로 기록하지 않는다. 시험 원인을 고쳐 정상 관문을 다시 거친다. 일반 ROS skip과 승인된 quarantine 재실행은 기존 판정을 따르며, 브라우저의 무실행·skip과 혼동하지 않는다.

중단할 때도 자기 실행만 다룬다. 로컬 `land_async.stop()`만으로는 분리된 원격 pytest가 남는다. 해당 run의 PID·PGID·cwd를 다시 확인한 뒤 `remote_job.KILL`을 사용하고 rc·프로세스·잠금 해제를 확인한다. 보고서와 커밋은 보존하고 다른 세션의 시험을 취소하지 않는다.

## 검증

- #227 head `8a84c7e359`가 `9f5474d961`을 포함했고 실제 병합됐다는 당시 사실은 유지한다. 이후 검토한 FULL 기록·보고서는 opt-in 실행을 입증하지 못했으며, 새 검증기의 작업 브랜치 검사에서도 이 head는 거부됐다.
- 게시 근거 회귀 RED는 tier-only 허용·no-cache 근거 유실 3건, 준비 뒤 새 코드·수작업 merge·hash 없는 행·같은 경로의 로그 교체 4건을 재현했다. 수정 commit `cf16fa8214`의 원격 관련 7파일은 318 passed, 0 skipped, NEW/known/flaky 0이었다. 정상 main 전진 후 merge, 실제 분할기·브라우저 계획과 hash 대응을 갖춘 경우도 확인했다.
- 위 수정은 이 문서 갱신 시점의 로컬 작업 브랜치 검증이다. 최종 통합 SHA의 적격 FULL·공개 CI·장치 수용은 별도이며, 과거 실행을 소급 승인하지 않는다.
