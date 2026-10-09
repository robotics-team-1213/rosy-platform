# 실물 카메라 `line` 관측의 밝은 페인트 모호성

**판정: 인식 반례 확인, 주행 사건 판정 보류.** 2026-10-09 11:31:48 KST에 주행 명령을 보내지 않고 `rosy_60`의 전방 카메라 프레임과 같은 영상 stamp의 `CAMERA_LINE` 관측을 읽었다. 로봇 설정·명령·파일은 변경하지 않았다. 원본 영상의 물리적 페인트 역할은 사람 정답으로 승인되지 않았다.

## 재현 증거

- 장치 설치 경로 `/opt/rosy/releases/2026.10.09-056`, `source-revision.txt`는 `f588e0ad879fab3f3b726802f4c99b78eed32f87`이었다. 관측 노드의 실제 파라미터는 `camera_lane_mode=line`, `camera_bright_threshold=180`, `camera_roi_top_fraction=0.4`, `camera_washed_fraction=0.4`, `camera_min_pixels=80`이었다.
- 원본 `bgr8` 320×240 Image와 observation의 stamp는 모두 `1791513108.431689`였다. 프레임을 손실 없는 PNG로 저장한 로컬 증거는 `X:/DevTemp/lane-live-readonly-20261009/frame.png`, SHA-256 `e2e23fc8dc798dfee59c5c548af290c317ed1cfb6f89a8097948a1af90de2333`이다. 원본 영상 자체는 공개 저장소에 넣지 않았다.
- 영상 하단에는 시야를 가로지르는 넓은 흰 페인트와 오른쪽의 밝은 벽이 보인다. 이는 **후보 해석**이며 물리적 차선·정지선 ID를 확정한 GT가 아니다.
- 동일 파라미터로 PNG 화소를 다시 계산하면 ROI 320×144에서 밝은 화소 3,845개(8.34%), 중심 x=201.5183355, `error=0.25948959687906364`, `confidence=1.0`이다. 장치의 `CAMERA_LINE {visible:true,error:0.25948959687906364,confidence:1.0}`과 정확히 일치한다. 최대 밝은 연결 영역은 면적 3,076px, x=10..319로 폭 310px이다. 이 값은 차로 중심의 신뢰도가 아니라 ROI 밝기 양을 나타낸다.

## 원인과 후보 비교

| 후보 | 같은 프레임/현장 조건에서 확인한 결과 | 판단 |
|---|---|---|
| 현재 `line` | `detect_lane_error`가 모든 밝은 화소의 무가중 중심을 쓴다. 1,500px 이상이면 confidence가 1로 포화된다. | 한 줄 추종용이며 차로 중앙 증거가 아니다. 밝기 임계값만 조정해도 물리적 의미는 구분하지 못한다. |
| 기존 `between` | 이 프레임 첫 두 호출 모두 `error=0.23125`, `confidence=0.15`. | 2경계 이미지 공간 후보이나 한쪽 벽·횡단 표시·분기에는 물리 지면 정보가 없다. 현재 CORE 기본 최소 confidence 0.35에도 못 미친다. |
| 기존 `keep` | 동일 프레임에 현재 장치 지면 설정 `PINKY`를 적용하면 지면 평면이 없어 `None`, `reason=no_ground`. | 목표인 차로 안 유지에 맞는 구현이다. 검증된 카메라 지면 보정값 없이 모드명만 바꾸는 것은 해결이 아니다. |
| 학습 마스크/지도 | 이 프레임의 사람 승인 차로·횡단선 GT가 없다. | 현재 분류 정답이나 주행 허가를 만들 수 없다. 승인 GT·분리 평가 후 섀도에서 비교한다. |

`line_observer_node._ground()`는 명시된 `NOMINAL` 프로필 또는 허용된 GAZEBO 평면만 만든다. 장치에서는 `camera_ground_source=PINKY`, `allow_nominal_ground=false`, `nominal_camera_profile_path`가 빈 값이었다. `keep`의 기존 횡단 표시 거절 및 한쪽 경계 반폭 추정은 오프라인 후보로 유지하되, 이 프레임에서 실제 두 경계가 옳게 선택되는지는 보정 프로필과 사람 GT로 다시 검증해야 한다.

추가 읽기 전용 확인에서 `nominal_camera_profile_path`는 빈 값이고 기본 보정 저장소 `/var/lib/rosy/calibration`도 없었다. 동일 PNG를 저장소의 `camera_nominal.yaml`(피치 8°)과 10/6 재생의 후보 피치 11.8°로 각각 `LaneKeeper(corner_turning=True)`에 오프라인 입력했다. 두 경우 모두 관측 `None`, `reason=no_boundary`, 선택 경계 0개였다. 두 프로필은 촬영 당시 승인 보정값이 아니므로 이 결과는 **안전한 거절 후보**일 뿐 검출 성능의 수용값이 아니다. 현재 프레임만으로 보정값을 역산하거나 임의의 피치를 승격하지 않는다.

같은 장치에서 기존 `tools/calibration/camera_capture.py`를 SSH 표준 입력으로 실행한 읽기 전용 정지 수집은 scan 40개, 영상 15개, odom 121개, 수집 fault 0개를 기록했다. 출력은 `X:/DevTemp/lane-live-readonly-20261009/camera-auto-candidate.json`, SHA-256 `bedbb4af817edb7ed405aac774d0e582086b13cc3ee85c25cdca2c988ffaa6948`이다. 계산기는 피치 `0.36826 rad`(약 21.1°), 높이 `0.0634 m`를 냈지만 `recommended=false`, 사유 `too few wall returns in view`였다. 높이는 `height_source=base`이며 실측값이 아니다. 보정 저장소·로봇 설정에는 적용하지 않았다.

이 **거절된** 후보를 같은 PNG에 대입한 민감도 시험에서는 `corner_turning=false`가 `no_boundary`로 멈췄으나 `corner_turning=true`는 선택 경계 0개·횡단 후보 2개에서 `strategy=corner_left`, `error=-0.6`, `confidence=0.6`을 냈다. 이는 21.1°가 실제 카메라 피치라는 근거가 아니며, 잘못된 지면 투영과 모서리 규칙이 결합하면 STOP이 회전 후보로 바뀔 수 있다는 반사실 반례다. 자동 보정의 거절 판정과 승인된 장치별 지면 프로필을 `keep` 전환의 필수 게이트로 유지한다.

## 주행 권한과 다음 검증

`CAMERA_LINE` 메시지 발행만으로 바퀴 명령이 나가지는 않는다. CORE의 모드 선택, 관측 신선도, 권한, 장애물 및 안전 게이트를 통과해야 한다. 이 캡처는 해당 시각의 CORE 모드·최종 `/cmd_vel`을 짝지어 읽지 않았으므로 **현장 오주행 사례라고 판정하지 않는다**. 10/7 테이프 추종 이탈은 별도 [D-511](../../adr/D-511-fleet-lane-compliance-watch-and-correction-cue.md)에 기록되어 있다.

다음에는 같은 원본 영상과 촬영 당시 카메라 프로필·odom을 보존해 `keep`에서 선택한 좌우 경계, 횡단 표시, STOP 이유를 재생한다. 사람이 물리 경계 ID와 페인트 역할을 검수한 고정 GT에서 직선·곡선·한쪽 소실·벽·분기를 나누어 연속 miss, flicker, 차로 밖 목표, false STOP을 비교한다. 그 뒤 모델 PC 재생과 SIM을 통과하고 장치 안전 상태가 확인될 때에만 보조 운전·실물 수용을 검토한다. 현장 기본값이나 설치 릴리스는 이 검토에서 바꾸지 않았다.
