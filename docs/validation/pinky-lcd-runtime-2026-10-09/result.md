# 두 Pinky LCD 런타임·Rosy Cam 재확인 — 2026-10-09 KST

**판정:** 두 기체에서 SPI 오류 수정 코드가 설치되고 얼굴 서비스가 실행 중임을 확인했다. LCD 실제 픽셀과 이동은 미확인이다. 현재 이동 경로는 확보되지 않았다.

## 설치본과 장치 읽기

- `rosy_26` (`rosy-pinky-9dfk`)와 `rosy_60` (`rosy-pinky-8kcn`) 모두 `/opt/rosy/current`가 `2026.10.08-055`를 가리킨다. 두 설치본의 `source-revision.txt`는 `e8efc5cb510c9a5c454b333d436a60857fb22a0e`이다.
- 양쪽 `rosy-core`, `rosy-face`, `rosy-io`가 active다. 현재 부팅의 `rosy-face` journal에는 시작 기록만 있고 LCD 오류는 없다. 각 `rosy-face` 프로세스의 열린 파일 목록에서 `/dev/spidev0.0`을 확인했다. 이는 장치 파일을 열었다는 증거이며 SPI 전송 성공이나 LCD 픽셀 증거는 아니다.
- 설치된 양쪽 `emotion/rosy_lcd.py` SHA-256은 `52b0ea26d393536b321ce8482e75a5f54fcf0cb72bc39f41542bfeac2c40b3e0`로 같다. 설치 파일과 현재 소스의 내용은 줄 끝 차이를 제외하고 같다. 수정된 `_write_data_buffer`는 64바이트씩 `writebytes2`로 전송한다. 호스트 소스의 파일 SHA-256은 `ab69429640c3d7223d067be6c6a61cf2967b7c27ca6c473da0034a82201d8ef0`이다.
- 설치된 호스트 `rosy-face.py`와 현재 소스의 의미 있는 차이는 페어링 요청 화면의 CA 지문 표기다. 이를 포함한 최신 소스를 실행 중이라고 주장하지 않는다.

## Fleet와 현장 영상

- 현장 사이트 HTTPS 프록시를 사이트 CA로 검증해 개발 모드의 정상 `development-session`을 발급받고 `GET /api/fleet/state`를 읽었다. 두 로봇 모두 `online: true`, E-Stop 표시는 `false`, 속도는 거의 0이었다. `rosy_26`은 MANUAL, `rosy_60`은 IDLE이었다.
- 두 상태 모두 `evidence.safety.received_at: null`, `evidence.safety.evidence: disconnected`, `localization: null`이었다. 이 읽기만으로 안전 상태와 이동 구역을 확정하지 않는다. 설치된 Fleet의 `GET /api/fleet/tracking/identity`는 404여서 D-472의 named track을 확인할 수 없었다.
- `ceiling_north`의 1280×720 JPEG 한 프레임을 2026-10-08 22:33:01 UTC에 받았다. 응답의 프레임 나이는 207 ms였다. 이전 [물리 ID 대조](../pinky-physical-id-2026-10-09/result.md)와 같은 상단 왼쪽·하단 왼쪽 배치가 보였으나, 좌측 주행 구역에는 케이블과 작은 물건이 여러 개 놓여 있었다. 영상은 LCD 앞면을 보여주지 않는다. 원본은 비공개 `X:/DevTemp/rosy-cam-goal-20261009.jpg`에만 있으며 SHA-256은 `7eb9aefaf58a19ff3ebc57b2da478e9d229fe029bd98972e88f1cdf97a0a8287`이다.

## 다음 경계

로봇 Web의 새 램프 자가 시험 버튼은 설치본 055에 없다. 현재 main과 설치 이미지 기준 사이 변경에 `deploy/robot/pinky_pro/native/rosy-face.py`가 있어 D-325 산출물 판정은 `review`(미분류 경로 42개, 이미지 입력 2개)였다. 전체 이미지 경로가 필요하며, 미서명 빌드·오프라인 서명·실제 설치·LCD 전면 관찰을 각각 따로 검증해야 한다. 이 회차에는 모드 전환이나 이동 명령을 보내지 않았다. 케이블·물건을 치운 뒤 최신 머리 위·전면 영상과 LiDAR로 바퀴 경로를 확인해야 D-522 범위의 이동 시험을 시작할 수 있다.
