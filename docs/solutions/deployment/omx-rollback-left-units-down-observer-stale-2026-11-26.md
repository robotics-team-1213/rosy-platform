---
title: "A cell update rollback left later units down, and the next updates waited forever on observer_stale"
date: "2026-11-26"
category: deployment
module: deploy/robot/omx
problem_type: runtime_error
component: deployment
symptoms:
  - "omx-devices autoupdate: {\"step\": \"deferred\", \"reason\": \"observer_stale\"} on every run"
  - "rosy-omx-observer@arm_s, rosy-omx-observation-bridge, rosy-omx-arm-status inactive with no failure of their own"
  - "cell-job-api refused a new job parameter (unknown params) although the release with it was prepared"
root_cause: logic_error
resolution_type: code_fix
applies_when:
  - "an omx-devices update reports rolled_back or session_started_during_restart"
  - "the updater keeps deferring with observer_stale while no session holds that arm"
---

# 셀 갱신 되돌리기가 뒤쪽 서비스를 꺼 둔 채 남긴 경우

## 증상

2026-11-26 19:13 KST 셀 PC의 `rosy-omx-devices-autoupdate`가 새 릴리스로 바꾸는 사이 다른 작업이 arm_b 세션을 열었다. 갱신기는 `rolled_back` 뒤 `session_started_during_restart`로 보류했다. 그 뒤 `rosy-omx-observer@arm_s`, `rosy-omx-observation-bridge`, `rosy-omx-arm-status`가 꺼진 채 남았고, 다음 실행은 `observer_stale`로 계속 보류해 작업 큐는 옛 코드로 돌았다(새 `remeasure` 매개변수를 `unknown params`로 거절).

## 원인

- `omx_autoupdate_host.Host.restart`의 `sequential` 모드가 첫 `systemctl start` 실패에서 바로 반환했다. 되돌리기에서 arm_b 관측기 시작은 세션이 버스를 잡고 있어 정상적으로 거절됐고, 설정 `units` 목록에서 그 뒤에 있는 서비스는 시작 명령조차 받지 않았다.
- 이 셀은 `restart_running_only: true`라 다음 전환은 켜져 있는 서비스만 다시 켠다. 꺼진 서비스는 사람이 켤 때까지 남고, arm_s 관측 파일이 낡아 `observer_stale`가 된다.

## 해결

`sequential` 재시작은 모든 서비스를 멈추고 시작한 뒤 실패한 것을 `units_failed`로 기록하고 False를 반환한다(`test_one_unit_that_will_not_start_does_not_leave_the_later_ones_down`).

## 현장 복구(코드가 배포되기 전, 또는 다시 보이면)

1. `journalctl --user -u rosy-omx-devices-autoupdate.service`에서 `rolled_back`·`deferred` 이유를 본다.
2. 설정 `~/.config/rosy/omx-devices-autoupdate.json`의 `units`마다 `systemctl --user is-active`를 확인한다.
3. 세션 잠금(`flock -n ~/rosy-omx/session-<arm>.lock true`)이 빈 팔의 관측기와 읽기 전용 브리지만 `systemctl --user start`로 켠다. 세션이 잡은 팔의 관측기는 켜지 않는다(그 세션이 끝나며 넘겨준다).
4. `systemctl --user start rosy-omx-devices-autoupdate.service`로 한 번 돌려 `switched`를 확인하고, 작업 큐 `ActiveEnterTimestamp`가 전환 뒤인지 본다.

## 검증

19:27 arm_s 관측기를 켜고 갱신을 돌리자 19:29 `switched`(4ff877eb2f90)였고, 작업 큐가 `remeasure`를 받아 arm_s 강제 재측정(`20261126-192914-724c94`)이 통과했다. 꺼져 있던 두 브리지는 19:37에 켰다.
