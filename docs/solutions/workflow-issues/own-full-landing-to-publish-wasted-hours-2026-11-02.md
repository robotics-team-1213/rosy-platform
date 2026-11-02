---
module: tools/publish_main.py
date: 2026-11-02
problem_type: workflow_issue
component: landing_pipeline
severity: medium
tags: ["publish", "land", "FULL", "LOAD-FLAKY", "batch"]
applies_when: "착지한 변경을 공개 main에 올리고 싶은데 publish_main.py가 'no commit past origin/main has a green FULL land record'를 낼 때"
---

# 게시하려고 내 FULL 착지를 따로 돌리다 반나절을 썼다

## 증상

2026-11-02 `feat/review-gate`를 로컬 main에 착지한 뒤 바로 게시하려 했다. `publish_main.py`가 "green FULL 기록 없음"으로 거부했다. FULL 기록을 만들려고 다음을 차례로 시도했고 모두 기록을 남기지 못했다.

1. main 끝과 같은 브랜치로 `land_async.py --tests full --no-cache`: 이미 main에 든 브랜치라 시험 없이 `== landed in a batch`로 끝났다.
2. 빈 커밋을 얹어 다시 FULL: 약 11시간 브라우저 chunk를 돌던 중 준비 단계에서 `test_ws_teleop.py::test_disconnect_after_motion_applies_zero`가 LOAD-FLAKY로 나왔다. 명시 FULL은 LOAD-FLAKY 하나로 저장·착지가 막힌다(`docs/reference/pr-pipeline.md`).
3. 그 시험을 고친 커밋으로 다시 FULL: 이번엔 `test_station_camera_scheduling.py`의 다른 시험이 LOAD-FLAKY였다.

그동안 다른 세션의 게시 PR(#227)이 이미 내 착지를 포함한 SHA로 열려 `ci-result`·`review-gate`가 녹색이었다. 그 PR을 병합하자 끝났다.

## 원인

게시는 로컬 main 전체를 올리는 공동 작업이고, FULL 기록은 게시 담당 흐름이 주기적으로 만든다. 한 세션이 자기 변경 하나를 위해 FULL을 새로 만들려 하면, 시험 PC 부하가 높은 시간대에는 FULL 행렬 어딘가에서 LOAD-FLAKY가 나올 확률이 높아 명시 FULL이 자주 무효가 된다. 이미 main에 든 브랜치는 시험 자체가 돌지 않는다.

## 해결과 다음에 할 일

- 착지 뒤 게시가 필요하면 먼저 `gh pr list --search "head:publish/main" --state open`을 본다. 열린 게시 PR의 head가 내 착지를 포함하면(`git merge-base --is-ancestor <내-SHA> <head>`) `publish_main.py --merge-when-green <PR> --apply`로 끝낸다.
- 열린 PR이 없으면 다음 정기 게시를 기다리거나, 게시가 급할 때만 FULL을 시도한다. 빈 커밋이나 이미 main에 든 브랜치로는 FULL 기록이 생기지 않는다.
- FULL 도중 LOAD-FLAKY가 보이면 그 실행은 게시에 쓸 수 없으니 즉시 멈추고, 흔들리는 시험은 원인을 고쳐 일반 착지로 넣는다(이번 `fix/teleop-disconnect-zero-wait`: 서버 `finally`의 0 적용을 시험이 기다리지 않던 경쟁).

## 검증

- #227 head `8a84c7e359`가 `9f5474d961`(review-gate 마지막 커밋)을 포함함을 `merge-base --is-ancestor`로 확인하고, `publish_main.py --merge-when-green 227 --apply`가 merge commit으로 병합했다.
- 고친 teleop 시험은 원격 시험 PC에서 파일 전체 7 passed.
