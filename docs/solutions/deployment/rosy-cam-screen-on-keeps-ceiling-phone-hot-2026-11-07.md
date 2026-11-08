---
module: cam
tags: [android, site-camera, thermal, operations]
problem_type: deployment
applies_when: a ceiling Rosy Cam phone runs hot, pauses for heat, or its sensor stays open with no request
---

# 천장 폰 화면을 켜 두면 요청이 없어도 센서가 켜진 채 뜨거워진다

## 문제

2026-11-07 현장 천장 폰(Galaxy S21)이 재부팅 뒤 "휴대폰이 뜨거워 송출을 멈췄습니다"를 냈다. 평소에도 표면 40.6°C, AP 47.5°C, OS 발열 단계 MODERATE였다.

## 원인

- 폰 설정 "충전 중 화면 켜짐"(`stay_on_while_plugged_in=7`)으로 화면이 계속 켜져 있었고 Rosy Cam이 맨 앞에 있었다.
- D-691은 앱 화면이 열려 있으면 맞추기용 미리보기를 유지한다. 그래서 요청이 없어도 센서가 켜져 있었다. 그 설정을 누가 켰는지는 찾지 못했다. 저장소 코드는 켜지 않는다.
- 배터리 100%에서 충전기에 계속 꽂혀 있었다.

읽은 값과 기준을 섞지 않는다. 37.8°C는 멈췄을 때 읽은 배터리 온도이고, 멈춤 기준은 OS SEVERE이며 이 값은 상태를 못 읽을 때만 배터리 45°C로 대체된다. 이번 멈춤이 정말 SEVERE 때문이었는지는 OS에 기록이 없어 확인하지 못했다. 재부팅 부하가 유력하지만 추정이다.

## 해결

폰에서 다음을 설정한다. 송출에 화면은 필요 없다.

```
adb shell settings put global stay_on_while_plugged_in 0
adb shell input keyevent 223
adb shell settings put global protect_battery 3
```

One UI 7의 `protect_battery`는 1이 기본(100%까지 충전, 95%에서 다시 충전), 3이 최대(80%에서 멈춤)다. `dumpsys battery`의 `mProtectBatteryMode`와 `mProtectionThreshold`로 확인한다. 1을 "켬"으로 읽고 바꾸면 100%로 붙어 있는다(2026-11-07 실측). 화면 되돌리기 값은 이 현장 기준 `stay_on` 7이다. 구도를 맞출 때만 화면을 켠다.

멈춤 기준을 40°C로 낮추지 않는다. 경고만 배터리 40°C다. 표면 온도는 평소에 40°C 가까이 가므로, 낮추면 카메라가 자주 멈춰 위치 추정이 끊긴다.

## 검증 근거

| | 끄기 직전 | 20분 뒤 |
|---|---|---|
| AP | 47.5°C | 34.5°C |
| 통신칩 | 43.8°C | 34.5°C |
| 표면 | 40.6°C | 33.8°C |
| 배터리 | 38.7°C | 33.0°C |
| OS 발열 단계 | 2 | 0 |

- 20분 뒤 값은 센서가 꺼진 상태다. 프레임을 계속 읽는 동안의 평형 온도는 재지 않았다.
- 화면을 끈 채 프레임 요청: 첫 응답 404, 약 3초 뒤 200, 이후 약 2.9 fps, 장면 정상, 화면은 계속 꺼짐.
- 요청이 멈추고 46~52초 뒤 센서가 닫혔다. D-691의 유지 시간 30초보다 길며 이유는 찾지 못했다.
- `protect_battery=1`(기본 모드)로 바꾼 뒤 약 7시간 뒤 배터리 100%, `recharge_level` 95였다. 3으로 되돌리자 `mProtectBatteryMode: 3`, 기준 80이 됐다. 100%에서 80% 아래로 내려와 머무는지는 아직 확인하지 않았다.

## 복구 때 주의

화면이 꺼지면 잠금 화면 상태가 된다. 이 폰의 잠금은 보안 잠금이 아니라 `rosy_cam_screen.py stream-start`가 풀 수 있고, 보안 잠금이면 그 명령은 거절한다. 천장 폰에 보안 잠금을 걸지 않는다.

## 다음에 적용할 조건

천장 폰이 뜨겁거나 발열로 멈출 때, 폰을 새로 설치할 때 위 설정부터 본다. 전체 현장 폰에 강제하는 자동 설정은 아직 없다.
