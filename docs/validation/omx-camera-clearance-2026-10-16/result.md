# OMX 카메라 원격 조정·고해상도 시야 확인 — 2026-10-16

[D-770](../../adr/D-770-fleet-omx-autonomous-imitation-pipeline.md)의 첫 구동 전에 남은
집게 시야를 조사했다. 두 카메라의 실제 제어 항목을 읽고 고해상도 진단 프레임을
확보했다. 손끝 위치는 더 잘 드러났으나 양쪽 gripping face/tip과 바닥·본체 사이
간격은 확정하지 못했다. 이 회차에 robot bus open·torque ON·목표 명령은 없었다.

## 실제 장치 제어 항목

현재 선택한 두 카메라에 `v4l2-ctl --list-ctrls-menus`와 `--list-formats-ext`를 실행했다.
stream capture나 control 쓰기를 하지 않는 metadata 조회다. 조회 전후 두 producer의
MainPID·InvocationID·active 상태는 같았다.

| 카메라 | 노출된 제어 | 지원 형식 중 진단에 사용한 크기 |
|---|---|---|
| top | 밝기·대비·색·gain·exposure 등, pan/tilt/zoom 항목 없음 | 1280×720 |
| front | 밝기·대비·색·gain·exposure 등, pan/tilt/zoom 항목 없음 | 1280×720 |

이는 현재 V4L2 장치에 노출된 제어 항목이다. 설치되지 않은 외부 PTZ 장치나 물리
카메라 마운트의 조정 가능성까지 부정하는 결론은 아니다.

## 중복 capture 없이 고해상도 프레임 확보

private 진단 helper를 사용해 한 카메라씩 별도로 실행했다. 기존 producer를 멈추기
전에 transient unit과 독립 ExecStopPost 복구를 먼저 등록했다. helper 안에서 원본
unit의 정확한 PID·InvocationID·명령·환경을 확인한 뒤 그 producer만 멈췄다.
camera device가 비어 있어야 진단 capture를 열고, open 뒤에도 sole PID를 확인했다.

실제 MJPEG1280×720·buffer1을 읽어 확인하고 세 frame을 받은 뒤 마지막 것을 보존했다.
각 frame의 시각은 host receive 시각이다. sensor exposure 동기화나 calibrated depth
증거는 아니다. helper는 frame 저장 뒤 capture를 release했다.

진단 unit은 RuntimeMaxSec=6·TimeoutStopSec=3·KillMode=control-group·Restart=no다.
source preview stop을 transient unit 내부에서 수행하므로 caller가 죽더라도 이미
등록된 종료 후처리가 원본 producer를 다시 시작한다. 이 순서는 standalone fake-command
검사에서 수정 전 실패·수정 후 통과를 확인했다. 해당 검사는 pytest 수에 합산하지 않는다.

두 실제 실행 모두 systemd-run --wait 성공과 frame/receipt를 확인했다. 원본 unit의
명령·환경 설정을 유지했고 최종적으로 두 producer가 active·각 장치 sole owner임을
재확인했다. 실제 capture 형식은 다시 MJPEG640×480이었다. 기존 ROS 소비자에서
진행하는 두 timestamp와 fresh frame을 읽었고 그때 source age는 top 약46ms·front
약79ms였다. 영구적인 camera source 수정이나 두 번째 상시 producer를 추가하지 않았다.

## 이미지 해석과 남은 조건

1280×720 top에서는 두 팔과 작업대가 더 넓게 보이며 follower end assembly는 대략
(930,280) 근처에 식별된다. front에서는 기존640 프레임 밖에 있던 양쪽 구조도 보인다.
보이는 중앙 공간에 손이나 물체는 나타나지 않는다. 그러나 양쪽 집게 tip/face와
주변 구조물·매트 사이 간격은 이 두 시야만으로 신뢰성 있게 구별되지 않는다.
앞선 nominal mesh/FK는 카메라 depth나 접촉을 확인하는 실측을 대신하지 않는다.

고해상도 영상의 독립 검토도 이 불확실성을 유지했다. 사용자에게 요청한 손끝 위치
설명 또는 손끝과 바닥이 함께 보이는 각도 확인은 아직 받지 못했다. 구동 후보는
준비돼 있지만 이 시야 확인을 실제로 해결하기 전에는 실행하지 않는다. 실제 시연과
IL eligible 데이터는 계속0회다.

## 보존

Fleet private `~/rosy-test/omx-camera-controls-033ab57d1/`에 실제 controls/formats와
전후 producer identity·hash를, `~/rosy-test/omx-camera-hires-033ab57d1/`에 수정 전후
진단 source·expected hash·역할별 frame·세 수신 시각·baseline·복구 receipt를 보존했다.
`~/rosy-test/omx-hires-restoration-033ab57d1/`에는 최종 원본 형식·sole producer 검사와
실제 ROS 소비자 재수신을 보존했다. raw image와 실장치 identity는 공개 문서에 넣지 않는다.
