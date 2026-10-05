# 체커보드 자동 추정값 실기 적용 — 2026-10-05

사용자의 `apply it` 지시에 따라 체커보드를 촬영한 9dfk 장치에 추정한 높이·하향각을 적용했다.
[앞선 후보 검증](../camera-board-2026-10-05/result.md)은 당시 적용하지 않은 기록으로 그대로 보존한다.
이번 작업은 카메라 인식 설정 적용이며 자동 주행 성공이나 새로운 내부 보정 수용이 아니다.

## 적용 범위

- 장치 실행 release: `2026.10.05-042`, source `07dc89f20d681e581277d84d3cd38ebd7ddffea7`.
- `/etc/rosy/line_observer_overrides.yaml`의 높이·하향각 두 항목만 추가했다.
- `camera_height_m_override`: `0.05490848234741523` m.
- `camera_pitch_rad_override`: `0.211484320738765` rad, 약 `12.117159`도.
- 높이는 보드 표면 기준 `53.908482` mm에 사용자가 추정한 판 두께 `1` mm를 더한 값이다.
- `keep`, `threshold`, `NOMINAL` 및 기존 프로필 경로를 유지했다. 내부값은 기존 seed이며 왜곡은 0으로 가정했다.
- 8kcn에는 이 장치별 보정값을 적용하지 않았다. 보정 저장소의 accepted record도 변경하지 않았다.

## 적용과 실제 실행 확인

2026-10-05 09:59:43 UTC에 신선한 IDLE/OFF·속도 0 상태를 확인하고 기존 overlay를 백업했다.
설치된 `control.line_observer_overrides.write_overlay`로 기존 항목을 보존하여 원자적으로 기록했다.
`rosy-camera`만 재시작했다. CORE PID `3704`는 유지됐으며 카메라 PID는 `3754`에서 `10223`으로 바뀌었다.

카메라 시작 로그는 `operator override height_m, pitch_rad`를 실제 프로필 출처로 보고했다.
실행 중인 `/rosy_26/line_observer_node`의 읽기 전용 파라미터에서 두 값이 정확히 일치했다.
재시작 후 10초 관측에서 타임스탬프가 진행하는 카메라 80프레임, 차선 관측 281개,
모터 명령 501개가 수신됐다. 모든 모터 명령의 선속도·각속도는 0이었다.
10:00:18 UTC 상태도 IDLE/OFF·속도 0이며 CORE/IO/camera 서비스가 active였다.

추가 관측에서도 카메라 80프레임과 속도 0 명령 500개가 수신됐다. 보드가 영상에 남아 있고
keeper는 `no_boundary`였다. 차선 인식·자동 주행의 현장 수용은 미완료이며 추정 기하의
NOMINAL 표기와 CORE의 진행 확인 조건을 유지했다.

## 백업과 증거

- 장치 백업: `/etc/rosy/line_observer_overrides.yaml.backup-checkerboard-20261005T095943Z`.
- 적용 전 overlay SHA256: `a4b04df967a40f9b5a9708714ac7d02fea850224d78f2e67e67315efc5ad527d`.
- 적용 후 overlay SHA256: `61dbc8d80036be66bf4eee96df61756ce1c13c0f67399227336ed9f3763dd341`.
- 로컬 원본 기록: `X:/DevTemp/line-remote-20261005/camera-board-application-verified.json`.
- 실행 파라미터·영상·관측: 같은 폴더의 `checkerboard-applied-rosy-pinky-9dfk-camera.json` 및 `.png`.
- 추가 인식 관측: `lane-after-calibration-rosy-pinky-9dfk-camera.json` 및 `.png`.

이 기록은 추정 카메라 기하의 실제 인식 노드 적용·정지 상태 검증이다.
신규 ARM64 payload 배포, CI 통과 또는 자동 차선 주행 완료를 뜻하지 않는다.
