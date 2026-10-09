# 차선 추종 녹화의 지면 근거 연결 (2026-10-08)

**판정: SOURCE/LOCAL 확인, 주행 수용 HOLD.** [10/6 원본 재생](../lane-1006-current-r0-replay-2026-10-08/result.md)의 3,129프레임은 현재 R0에서 모두 STOP이었다. 당시 지면 설정은 공칭값 또는 미승인 11.8° 후보여서 물리 보정값과 같은 프레임의 근거가 없었다.

새 녹화의 Pilot과 스냅샷은 `camera/calibration/status`를 함께 저장한다. 이 상태는 **camera_detect_node의 보정 평가**이며, 별도 `line_observer_node`가 차선 판단에 사용한 보정의 승인 증명이 아니다. 스냅샷에는 이미 Pilot에 있던 `line/keep_debug`도 저장한다. 해당 진단의 `ground_projection`은 차선 관측기가 그 프레임에 실제 사용한 수치 투영이며, 경계 후보와 선택 결과를 포함한다. 두 토픽은 학습 정답이 아니다.

MCAP 직접 추출과 MP4 sidecar는 상태 메시지를 과거 방향으로만 연결하고 2.5초가 지나면 `null`로 둔다. `line/keep_debug`는 이미지 stamp가 맞는 프레임에만 연결한다. 카메라 보정 상태와 차선 관측기의 투영을 혼동하거나, 오래된 상태를 현재 프레임의 근거로 재사용하지 않는다. 짧은 스냅샷의 side-topic 캐시 예산은 프레임당 4 KB에서 8 KB로 늘려 진단 메시지를 포함했다. 이 수치는 용량 추정이며 장치에서 실제 메시지 크기와 60초 보존 길이를 확인해야 한다.

## 남은 검증

- 사람 검수 동일 물리 경계 ID, 가림·재출현, 벽/분기 정답은 아직 없다. AI 후보는 승인 정답으로 승격하지 않는다.
- 실제 카메라의 승인된 보정 revision과 차선 관측기 투영의 일치, 녹화된 상태 토픽의 실물 수신, ROS 폐루프 전체 경로 및 실물 주행은 확인되지 않았다.
- 불확실한 경계는 STOP, 최종 `/cmd_vel`은 CORE 단독 소유를 유지한다.

## 로컬 회귀

`middleware/perception/test/` 전체: 2,821 passed, 110 skipped, known-failures NEW 0. 녹화·추출 집중 5개 파일: 154 passed. `learning/training/perception/test/` 전체: 1,286 passed, 212 skipped, 5 failed. 실패 5개는 이 변경과 무관한 `test_site_install_model_watch.py`의 Windows 기본 `C:\WINDOWS\system32\bash.EXE` 선택으로, 같은 `main`에서도 동일하게 재현했다. `C:\Program Files\Git\bin`을 PATH 앞에 놓은 해당 파일 재검증은 11 passed다. 학습 전체 통과 판정으로 확대하지 않는다.
