# OMX 카메라 입력 복구

브랜치: `fix/inference-integration`. 계약: D-273, D-496.

현장 두 USB 카메라의 기존 `cam2image`는 USB 분리 뒤 프로세스와 토픽만
남기고 새 프레임을 내지 않았다. 재시작 뒤 상단 영상은 복구됐으나 앞 카메라는
커널의 USB bandwidth 거절로 캡처하지 못했다. 앞 카메라는 MJPEG 640×480을
지원한다. 팔 드라이버나 관절 명령은 이번 복구 대상이 아니다.

1. MJPEG 캡처·형식 readback·빈 프레임 거절·장치 해제를 ROS 없는 시험으로 고정한다.
2. 기존 토픽/프레임 이름을 받는 읽기 전용 ROS 카메라 입력을 추가한다.
   지속 USB 경로만 허용하고 최신 프레임만 발행한다. 읽기 실패 시 장치를 다시 연다.
3. 사용자 systemd watchdog이 막힌 캡처 호출을 재시작하도록 구성한다.
4. 원격 시험과 known_failures 비교 후 현장 두 카메라에 적용한다.
   각 카메라의 기존 producer만 교체하고 팔 프로세스는 유지한다.
5. 증가하는 두 영상과 실제 AI 추론을 확인한다. Fleet 화면의 실제 URL/인스턴스와
   대조한 뒤 나머지 연결을 보완한다.

영상의 header stamp는 호스트 수신 시각이다. 검증된 CameraInfo·카메라→팔 보정과
깊이/충돌 증거를 만들지 않으며, 이 입력만으로 집기 좌표나 팔 실행을 승인하지 않는다.
원자료·실제 장치 경로·실행 증거는 X: 세션에 둔다. main 착지·push는 하지 않는다.

## 실행 결과와 남은 경계

- `fix/inference-integration`의 독립 검토 뒤 USB 부재를 재시도 가능한 오류로
  바꾸고, 캡처 버퍼가 실제 한 장인지 확인하도록 보완했다. 두 회귀는 원격
  RED 재현 후 GREEN으로 닫았다. adapter·배치 시험은 526 passed, 7 skipped,
  known_failures 비교는 NEW 0이다.
- 선택한 두 지속 USB 장치에 사용자 서비스를 설치했다. MJPEG 640×480의 서로
  다른 frame_id에서 증가하는 영상과 캡처 호출 정지 뒤 watchdog 자동 복구를
  관측했다. 두 unit enabled 및 `Linger=yes`를 확인했다. 실제 USB 재연결과
  재부팅 시험은 하지 않았다. 현장 기존 ROS 경로는 Jazzy 이름이지만 실제로
  Lyrical을 가리킨다. 이 경로를 유지했으며 Jazzy 실물 수용으로 보고하지 않는다.
- 실제 두 JPEG의 SHA-256을 고정하고 AI PC의 고정 `qwen3-vl:8b-instruct`에
  관측만 요청했다. 상단 2.526초, 전면 1.836초에 응답했다. 상단 작업대의
  물체와 팔 일부를 설명했고 전면은 가림과 제한된 시야를 보고했다. 이는
  단일 프레임 추론이며 지속 Fleet 소비 경로나 검출 정확도 수용이 아니다.
- 현재 Fleet 실행에는 OMX instance/action owner 연결이 없고, 실측
  CameraInfo·hand-eye·TCP·관절/그리퍼 프로필도 확인되지 않았다. Pinky용
  상황 VLM이나 `ceiling_north`의 위치를 OMX로 덮어쓰지 않았다. Fleet의
  dispatch 구현과 실제 OMX 장치 실행은 별도 증거다. 위 입력만으로
  `omx` capability, 실물 Pilot 드라이버 또는 자동 집기를 활성화하지 않는다.
