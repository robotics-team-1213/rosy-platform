---
title: landed_copy() shadowed tools/remote fixes and GPU-idle ALONE holds stalled landings
date: 2026-11-16
category: workflow-issues
module: tools/land_checks.py, tools/land_rollup.py, tools/remote/remote_job.py
problem_type: workflow_issue
component: development_workflow
severity: high
root_cause: logic_error
symptoms:
  - "a merge-train branch containing a remote_job.py admission fix still hit '[remote-pytest] admission deferred: gpu/sim hold' inside land.py"
  - "landed_copy() re-executed main/tools/land.py, whose sys.path imported main's pre-fix tools/remote/remote_job.py"
  - "ROSY_BROWSER_ALONE=1 and test_platform_g1_timing.py stalled behind 2-4h GPU training holds despite zero CUDA or sim contention"
  - "land_rollup.build() merged member_metadata back onto member dicts before lead(merged) / adopted(), clobbering the carrier ticket"
  - "Windows laptop gateway/self-IP change left Tailscale reporting Online=True while peer rx bytes froze and SSH timed out"
---

# `landed_copy()`가 `tools/remote` 수정을 가리고 GPU 대기로 착지가 멈춘 문제

## 증상

1. 2026-11-16 `fix/track4-merge-train` 안에 `tools/remote/remote_job.py`의 `ROSY_JOB_CPU_ALONE=1` 수정이 들어 있었으나, `land.py` 실행 중에는 계속 `[remote-pytest] admission deferred: gpu/sim hold`가 발생했다.
2. `test/test_platform_g1_timing.py`와 `ROSY_BROWSER_ALONE=1` 3개 파일이 GPU 학습(`train-*.lock gpu`) 때문에 장시간 `D-584`로 막혔다. (이전 날 재시도 중 재롤업된 `land-rollup`은 `land_stats.py --goal`에서 `(unproven member origin)`을 냈다.)
3. `land_rollup.build()`에서 `member_ticket` 보존용 `member_metadata`를 `{**r, **metadata}`로 덮어써 `lead(merged).get("ticket")` / `adopted()` 시점에 실시간 큐 티켓이 사라질 수 있었다.
4. 노트북(`seriggga`)의 게이트웨이/IP 변경 직후 `tailscale status`는 `Online=True`인데 모든 피어 `rx`가 멈추고 SSH가 타임아웃되었다.

## 원인

1. **`land_checks.landed_copy()`의 `sys.path` 그림자:** 브랜치가 `tools/land*.py`를 함께 바꾸면 `landed_copy()`가 `main` 체크아웃의 `tools/land.py`를 재실행한다. `main/tools/land.py`는 `sys.path[0] = main/tools`로 `main`의 `tools/remote/remote_job.py`를 import하므로, 브랜치에 포함된 `tools/remote/` 수정이 준비(prepare) 및 라운드에서 무시된다.
2. **CPU/Playwright 단독 잡의 과도한 GPU 배제:** 실측 결과 GPU 학습 중인 `ai`/`rosy`에서도 `test_platform_g1_timing.py`는 8/8회(`jitter 0.16-0.73ms`, `fsync p90 0.20-0.67ms`, `12/12 passed`), `ROSY_BROWSER_ALONE=1` 3개 파일은 `rosy`(`133 passed in 397.58s`)와 `ai`(`133 passed in 455.87s`) 모두 무결점으로 통과했다. 반면 `test_platform_g1_sim.py`와 일반 `ROSY_JOB_ALONE=1`은 시뮬레이션/부하 격리를 위해 기존 hold를 유지해야 했다.
3. **`land_rollup.build()` 티켓 덮어쓰기:** `unrolled()`는 큐 인계용 carrier `ticket`과 기록용 `member_ticket`을 분리했지만 `build()`가 `{**r, **metadata}`로 `r["ticket"]`을 덮어쓴 뒤에 `lead(merged)`와 `adopted()`를 호출했다.

## 해결 및 검증 근거

1. **선(先) 분리 착지 절차:** `tools/remote/remote_job.py` + `test/test_remote_reboot_admission.py`만 포함한 독립 브랜치(`fix/g1-timing-cpu-alone`, `tools/land*.py` 무변경)를 먼저 `main`(`6bfe95e342`)에 착지시켜 `landed_copy()` 그림자를 우회한 뒤, `fix/track4-merge-train`(`main` `8a32178864`)을 연속 착지했다.
2. **`ROSY_JOB_CPU_ALONE=1` 제한적 공존:** `tools/remote/remote_job.py`에서 `test/test_platform_g1_timing.py`(비브라우저) 및 `ROSY_BROWSER_ALONE=1 && ROSY_RUN_BROWSER_TESTS=1`에만 `ROSY_JOB_CPU_ALONE=1`을 켜 `non_gpu == 0`, `sh == 0`(sim 없음), GPU+요청 코어/메모리 여유(`gc + RC <= CAPC && gg + G <= CAPG`)일 때만 실행하도록 했다 (`test/test_remote_reboot_admission.py` 등 Linux 검증 `76 passed`, `449 passed`, `609 passed`, `186 passed` 및 `8a32178864` FULL 통과).
3. **`land_rollup.build()` carrier 티켓 유지:** `.members` JSON 기록에만 `member_ticket`을 쓰고 `merged` 내부의 `r["ticket"]`은 유지하도록 수정하고 `test_build_adopts_unrolled_carrier_ticket_while_preserving_member_ticket` 회귀 테스트(`20 passed in test_land_rollup.py`)로 검증했다.
4. **Windows Tailscale 복구:** `netcheck`에 `gateway and self IP changed`가 찍히고 피어 `rx`가 멈출 때 `tailscale down; Start-Sleep 2; tailscale up`으로 600초 `RECONNECT_S` 타임아웃 전에 터널을 복구했다.

## 다음에 적용할 조건

- `tools/land*.py`와 `tools/remote/*.py`를 동시에 고쳐야 착지가 뚫리는 상황이라면, `tools/land*.py`를 건드리지 않는 `tools/remote/` 브랜치를 먼저 단독 착지한다.
- Windows 테스트 코디네이터가 네트워크 전환 직후 SSH 폴링에 일제히 실패하면 원격 장애로 단정하기 전에 `tailscale ping`과 `tailscale netcheck`의 게이트웨이 변경 로그를 먼저 확인한다.
