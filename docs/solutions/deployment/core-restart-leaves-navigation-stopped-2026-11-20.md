---
title: "rosy-core를 재시작하면 rosy-navigation이 멈춘 채 failed로 남는다"
date: "2026-11-20"
module: "Pinky native runtime (rosy-core, rosy-navigation)"
problem_type: runtime_error
component: deployment
severity: medium
symptoms:
  - "CORE dev 오버레이 sync, 실행기 drop-in 시험, 자동 업데이트 뒤에 rosy-navigation이 failed(Result=exit-code)로 남는다."
  - "그 뒤에 잰 CORE CPU가 크게 낮게 나온다. odom·scan·/tf 트래픽이 없기 때문이다."
root_cause: config_error
resolution_type: workflow_improvement
tags: ["pinky", "rosy-navigation", "rosy-core", "systemd", "measurement"]
---

# rosy-core를 재시작한 뒤에는 rosy-navigation 상태부터 본다

## 증상

2026-11-20 y8xs에서 세 번 있었다. 오버레이 sync(08:02 UTC), 업데이트 준비(09:43 UTC), 실행기 drop-in 시험 때다. 매번 rosy-core가 재시작되었고, rosy-navigation은 `failed`로 남아 다시 뜨지 않았다. 그 상태에서 잰 CORE CPU는 navigation이 켜졌을 때(약 77%)와 비교할 수 없었다.

## 원인 (journal과 unit으로 확인)

- `rosy-navigation.service`는 `Requires=rosy-core.service`다. rosy-core가 멈추거나 재시작되면 navigation도 멈춘다.
- 멈출 때 `ros2 launch`가 SIGTERM을 받고 `Cannot shutdown a ROS adapter that is not running` 예외로 exit 1을 낸다. 그래서 정상 정지인데도 `failed`로 표시된다. 명시적 정지라 `Restart=on-failure`도 동작하지 않는다.
- navigation을 띄우는 것은 승인 호스트뿐이다(`deploy/robot/pinky_pro/native/navigation_approval_host.py`의 `systemctl start --no-block rosy-navigation.service`). 어떤 target도 navigation을 원하지 않는다. 그래서 rosy-core가 돌아와도 navigation은 저절로 뜨지 않는다.
- unit의 ExecCondition이 승인 봉인을 다시 확인한다. 릴리스가 바뀐 뒤에는 `systemctl start`를 해도 `Skipped due to 'exec-condition'`으로 뜨지 않는다. 이것은 의도된 동작이다.

## 대처

- rosy-core를 재시작하는 작업 앞뒤로 `systemctl show rosy-navigation -p ActiveState,Result`를 기록한다. 작업 전에 active였다면, 끝난 뒤 승인 경로로 다시 띄우거나 사용자에게 알린다. ExecCondition을 우회하지 않는다.
- CPU·지연을 비교할 때는 두 조건 모두 navigation 상태가 같은지 확인한다. 같지 않으면 그 비교는 쓰지 않는다.
- `failed` 표시만으로 고장이라 판단하지 않는다. journal에서 `Stopping` 뒤의 launch 예외인지 먼저 본다.

## 남은 것

launch가 SIGTERM 정지에서 exit 1을 내지 않게 하면(`SuccessExitStatus=1` 또는 launch 쪽 처리) `failed` 표시는 사라진다. 다만 진짜 실패도 함께 가려질 수 있어서 이번에는 바꾸지 않았다.
