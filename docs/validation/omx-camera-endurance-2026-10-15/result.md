# OMX 영상 장시간 수신과 소비 경로 확인 — 2026-10-15

이 기록은 실제 native 카메라 두 개의 **메시지 수신**을 확인한다.
화질·노출 시각·좌표 보정·팔 동작·지속 AI/Fleet 소비의 수용 기록은 아니다.
앞선 [30초 비교](../omx-preview-receiver-2026-10-15/result.md)는 그대로 보존한다.

## 실행 조건

- 문서 기준 commit: `fab5adc188d432e6fdc3de03282b12a21f6092a1`.
  실행된 camera source는 기존 `dbe5db55b7`이다.
  파일 SHA-256: `caaa439c383eb9ed33ee8dc3dbc3637bbc82b9147b1de5ec8bfdf4c78cbcf1e9`.
- 현장 native ROS Lyrical, `rmw_fastrtps_cpp`, `rclpy 10.0.11`.
  Jazzy/CycloneDDS 실물 제어 수용으로 확장하지 않는다.
- producer와 같은 현장 PC의 workcell domain에서 `/top_camera/image_raw`, `/front_camera/image_raw`의
  `sensor_msgs/msg/Image`를 읽었다. publisher는 best-effort depth 1,
  두 진단 subscriber는 sensor-data QoS depth 5다. 영상은 640×480 `bgr8`이다.
- 기본 수신기는 `FASTDDS_BUILTIN_TRANSPORTS`가 없는 환경에서 시작했다.
  비교 수신기는 ROS 초기화 전에 다음 값을 해당 프로세스에만 적용했다.

```bash
export FASTDDS_BUILTIN_TRANSPORTS='DEFAULT?max_msg_size=60KB&sockets_size=2MB&non_blocking=true'
```

producer는 이미 같은 값을 쓰고 있었다. 이번 시험 중 producer 설정·서비스·전역 RMW는
바꾸지 않았다. 두 시험은 시작 시각이 다르고 대부분의 구간이 겹치는 동시 관측이다.
단독 부하 시험이나 무작위 교차 시험은 아니다.
PC 간 영상 전달을 시험한 것은 아니다.

## 최종 수신 결과

두 프로세스 모두 `event=complete`와 exit 0을 확인했다. 기본 수신기는
07:12:55 UTC에 시작해 1800.004초, 같은 설정 수신기는 07:17:25 UTC에 시작해
1800.020초 실행했다.

| 수신기 | 영상 | 메시지 수 | 평균 FPS | 최대 간격(초) | stale / nonadvancing |
|---|---|---:|---:|---:|---:|
| 기본 | top | 11,284 | 6.269 | 4.207 | 0 / 0 |
| 기본 | front | 7,697 | 4.276 | 5.411 | 0 / 0 |
| producer와 같은 설정 | top | 17,974 | 9.985 | 0.121 | 0 / 0 |
| producer와 같은 설정 | front | 17,973 | 9.985 | 0.113 | 0 / 0 |

기본 수신기의 첫 메시지 대기는 top 0.309초, front 4.005초였다.
수신한 메시지의 최대 host stamp age는 기본 top/front 0.014/0.015초,
같은 설정 top/front 0.017/0.015초였다.
이 조건에서는 설정을 맞춘 수신기가 두 영상의 약 10 FPS 전달을 30분 유지했다.
전송 내부 원인이나 모든 부하·재부팅 조건에서의 동작을 입증한 것은 아니다.

FPS는 시작 이후 받은 메시지 수를 경과 시간으로 나눈 값이다. 최대 간격은 수신 사이의
monotonic 간격 및 보고 시점의 마지막 수신 이후 간격이다. `stale`은 수신한 메시지의
host stamp age가 음수이거나 2초를 넘는 경우, `nonadvancing`은 직전 stamp 이하인 경우다.
둘이 0이어도 메시지가 오지 않는 구간이 없다는 뜻은 아니다. stamp는 host-receive 시각이며
카메라 노출 시각을 검증하지 않았다. 픽셀 변화·초점·가림·동일 영상 반복도 검사하지 않았다.

## 실제 소비 경로의 공백

같은 domain의 3초 discovery 관측에서 두 Image topic의 subscriber는 이번 진단 수신기
두 개뿐이었다. 이 관측에서 지속 AI/Fleet 소비자는 발견하지 못했다.
`/joint_states` publisher는 `joint_state_publisher`였고 Action 목록은 비어 있었다.
이는 실물 관절 feedback이나 팔 Action의 연결 증거가 아니다.

현재 site Vision은 `rosy_vision.cli vision --track`으로 실행 중이다.
기준 소스의 `operations/overhead/rosy_vision/vision_config.py`는 map·보정 revision·
세계 좌표·robot marker를 요구하고, `cli.py`는 각 source에 `VisionWorker`를 만든다.
일반 작업대 영상만 보는 source를 기존 천장 카메라 이름으로 등록하는 계약은 없다.

[D-273](../../adr/D-273-omx-camera-stream-and-arm-control-order.md)에 따라 OMX 작업
카메라는 이동 로봇·천장 카메라와 source/frame/profile을 구분해야 한다.
Fleet에 원본 영상이나 DDS를 중계하는 구성으로 이 공백을 채우지 않는다.
CORE 화면 미리보기는 기존 최대 2 FPS·640 px·최신 1장·인증/lease 경계를 따른다.
새 작업대 관측 계약이 필요하면 원본은 로컬에 두고 허용된 관측·미리보기의 소비 경로를
먼저 결정해야 한다. 측정하지 않은 map 좌표나 보정값을 넣어 기존 경로를 통과시키지 않는다.

## 후속 작업과 증거 위치

1. 실제 소비 프로세스에도 전송 조건을 고정하고 latest-only·stale 거부와 원장 readback을
   검증한다. 이번 진단 subscriber의 성공을 운영 소비자의 성공으로 대신하지 않는다.
2. USB 분리·재연결·cold boot 뒤 장치 식별과 영상 복구를 별도 확인한다.
3. [실물 제어 계획](../../plans/2026-10-15-omx-hardware-control.md)의 실측 profile·
   독립 정지·camera-to-arm/TCP·실물 feedback을 수용한 뒤 딸기 왕복을 진행한다.

비공개 실행 세션의 `logs/omx-stream-endurance-30min.txt`,
`logs/omx-stream-endurance-matched-30min.txt`, `scratch/omx-endurance.py`,
`logs/omx-consumer-graph-readback.txt`, `logs/omx-native-rmw-readback.txt`,
`logs/vision-consumer-command.txt`에 원문과 계측 코드가 있다.
장치 주소·자격 증명·실제 호스트 경로는 이 공개 기록에 포함하지 않는다.
하드웨어 명령은 보내지 않았고, 실물 왕복은 미수행이다.

원문 파일 SHA-256:

- 기본 수신기 로그 SHA-256: `c11778fec1d7f50d35f336396a5e8adbbcbb3af172832076fca6b583f13840b3`
- 같은 설정 수신기 로그 SHA-256: `6c1fc138d6f30fd56f4e0f7555df411b842bf044bb2aa89d067224a0b3b25541`
- 같은 설정 계측 코드 SHA-256: `d19d159eea89f44b8a89ed74b25155d1954d8c8620dad21269206bd1f9fed0d2`
