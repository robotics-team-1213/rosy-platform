# 실물 차선 디버그와 지면 투영 읽기 전용 확인

**판정: 실물 메시지 수신 확인, 주행영역·차선 추종 수용 HOLD.** 2026-10-09 00:59 KST에 두 Pinky의 ROS 토픽과 설치 상태를 읽기 전용으로 확인했다. 로봇 모드·설정·모델 포인터·주행 명령은 바꾸지 않았다. 분석 시점의 로컬 소스는 `977a75dc4`, 두 장치의 `/opt/rosy/current`는 `2026.10.08-055`였다. 호스트 소스가 장치 설치본과 같다고 가정하지 않는다.

## 실물 관측

| 대상 | 현재 관측 | 범위 |
|---|---|---|
| `rosy_26` | `rosy-core`, `rosy-io`, `rosy-camera` active. `line_observer_node`는 `keep`, `camera_ground_source=NOMINAL`, `paint_source=learned`; 카메라 프레임과 `line/keep_debug` 수신 | `learned_lane_pointer=/var/lib/rosy/models/shadow`는 설정돼 있으나 장치에 대상이 **없다**. `learned`가 실제 추론을 뜻하지 않는다. |
| `rosy_60` | 같은 세 서비스 active, 카메라 프레임 수신. `camera_lane_mode=line`, `camera_ground_source=PINKY`, `paint_source=threshold` | 15초 구독에서 `line/keep_debug` 메시지가 없었다. 현재 모드는 keep 디버그를 내는 경로가 아니다. shadow 포인터 대상도 없다. |

`rosy_26`의 [집계](evidence/summary.json)는 12초 구독에서 받은 디버그 84건과 이미지 헤더 85건을 [분석 코드](evidence/analyze.py)로 대조한 것이다. 디버그 83건은 원본 이미지 stamp와 1 µs 안에서 일치한다. 불일치 1건은 이미지 헤더 구독이 시작되기 **0.131초 전**의 첫 디버그다. 84건의 영상 시각은 엄격히 증가했고 범위는 10.3748초다.

| 관측 항목 | 84프레임 결과 |
|---|---:|
| `strategy=none`, `reason=flipping`, 목표점 없음 | 각각 84 |
| `paint_source_used=denoise_fallback` | 84 |
| 전략 전환 | 0 |
| 최장 연속 `none` | 84프레임 |
| `ground_projection` 변경 | 0 |

실제 사용된 투영은 높이 `0.0549084823 m`, 아래 pitch `0.2114843207 rad`(약 12.117°), 초점 `281.6 px`, 주점 `(160,120) px`, 전방 오프셋 `0.03317 m`였다. `line_observer_node`의 읽기 전용 파라미터 `camera_height_m_override`와 `camera_pitch_rad_override`가 두 값과 일치했다. `ground=NOMINAL`은 이 모드의 **라벨**이고 URDF 기본 높이 `0.06343 m`·pitch `0.139626 rad`를 실제로 썼다는 뜻이 아니다. 별도 `camera/calibration/status`는 `active=false`, `eligible=false`, `reason=mode_pinhole`이었으며 차선 관측기 투영의 사람 승인 보정 revision을 증명하지 않는다.

이 구간은 모델이 학습 주행영역을 만들어 낸 결과가 아니다. 차선 관측기가 학습 페인트를 **요청**했지만 모델 포인터가 없고 84프레임 모두 denoise로 fallback했다. 따라서 전략 전환 0건도 안정적인 차선 추종 점수가 아니라 `none`이 계속된 사실이다. 실제 주행/정지 명령과 바닥·벽 픽셀의 사람 정답을 이 구독에서 수집하지 않았으므로 논문의 `R_F/R_M`, 주행영역 IoU, 차선 이탈률, 안전 정지 성공률을 산정하지 않는다.

## 재현과 보존

장치에서 설치 서비스와 같은 `ROS_DOMAIN_ID`, `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp`, `CYCLONEDDS_URI=file:///etc/rosy/cyclonedds.xml`로 `ros2 topic list --no-daemon`을 실행해야 토픽이 보였다. 설정 파일을 빼고 조회하면 `/parameter_events`와 `/rosout`만 보여 잘못된 토픽 부재 판정이 된다. `ros2 param get --no-daemon`으로 위 모드를 읽었고, `ros2 topic echo --full-length`로 디버그를 받았다. `--full-length`가 없으면 JSON 문자열이 `...`으로 잘려 분석할 수 없다.

원시 ROS echo와 카메라 보정 상태는 비공개 X: 세션 `X:/DevTemp/projects/rosy-platform/2026-10-09--005412--lane-live-ground-readback--299423/evidence/`에만 있다. 집계 입력 SHA-256은 디버그 `8efb7c1836904b6cb2abdf0680e8ed83d3a432cdbd284d448f243963f54fa3fa`, 이미지 헤더 `0fac9736ef97793931789df5bb8a07575519507040b6d524531a5866974d60e5`다. 보정 상태 단일 메시지는 `731be7410a3b3fa9b80137ff89c8b7071c685a3f8445c5d559779d4e000fd384`다. Windows PowerShell의 리디렉션으로 저장된 UTF-16 원시 파일을 분석 코드는 입력 BOM으로 판별한다. 공개 저장소에는 원시 영상이나 장치 주소를 넣지 않는다.

분석 코드 SHA-256 `1a7b5cebc37a844fe5f461908c970f682310541504a81c20b6d66e83022987f5`, 집계 SHA-256 `861c6b3798240233d46e52ad355c362485cead58d3491c88a27a14b3b975b3b8`.

문서·하네스 계약 pytest는 136 passed, 1 skipped, `known_failures` NEW 0이었다. 하네스 lint는 0 errors, 기존 `last_verified` 경고 23건이다. 새 공개 파일에 대한 비밀 문자열 검사는 탐지 0건이다. 이 호스트 검사는 위의 실물 토픽 관측이나 주행 수용을 대신하지 않는다.

다음에는 같은 시각의 영상과 사람이 승인한 물리 경계 ID·보이는 바닥/unknown을 확보해 `none/flipping`의 원인을 판별해야 한다. 포인터 설치나 `keep` 모드 변경만으로 검수된 주행영역·차선 추종을 주장하지 않는다. 불확실하면 STOP을 유지하고 최종 `/cmd_vel`은 CORE만 발행한다.
