# 두 Pinky 현장 재확인 — 2026-10-09 KST

## 대상과 방법

- 소스 기준: `25342c9d4b33e226085405adb97af3b89be4c285`. 현장 Fleet 이미지 revision은 `ed006ce92cc4832619dc96d4d0e00f779b439ec9`, 두 로봇의 설치 릴리스는 `2026.10.08-055` (`source-revision.txt`: `e8efc5cb510c9a5c454b333d436a60857fb22a0e`). 이 기록은 새 배포의 검증이 아니다.
- 현장 PC에서 사이트 CA로 Fleet HTTPS를 검증하고 개발 세션으로 `GET /api/fleet/state`와 Rosy Cam `ceiling_north` 프레임을 읽었다. 로봇별 Web의 TLS 호스트명과 CA를 검증하고 인증된 `POST /api/v1/host/hardware/test` (`device: lamp`) 후 `GET /api/v1/host/hardware`를 읽었다. 로그인 코드는 단기 발급했고 토큰은 기록하지 않았으며, 각 시험 후 로그아웃했다. 램프 시험은 두 기체를 정지 상태에서 차례대로 실행했다.
- 두 로봇에서 `rosy-core`, `rosy-face`, `rosy-io`는 active였다. 설치된 `emotion/rosy_lcd.py` SHA-256은 양쪽 모두 `52b0ea26d393536b321ce8482e75a5f54fcf0cb72bc39f41542bfeac2c40b3e0`이었다. `rosy-face` 프로세스는 `/dev/spidev0.0`을 열고 있었고 현재 부팅의 journal에는 SPI 오류가 보이지 않았다. 이것은 LCD 실제 픽셀 확인이 아니다.

## 일회성 몸체 대조

2026-10-08 23:50–23:51 UTC의 1280×720 Rosy Cam 연속 프레임을 직접 검토했다. 각 시험에서 요청한 기체만 빨강에서 초록으로 변했고 다른 기체는 변하지 않았다.

| 장치 ID | 장치 시험 결과 | 영상 속 몸체 | 대표 원본 SHA-256 (`시험 전` / `빨강` / `초록`) |
|---|---|---|---|
| `rosy_26` | 요청 `ff977f9c16c0a230` 수락, `done`, 23:50:29 UTC 완료 | 왼쪽 위 | `702508c4cb79cbe1671ffaa09b9e1f963d7c07c2b968d6b2c277cd37ce708e75` / `ea8393daf615f2dc6f1f4880bd60488e3af9c69f1dc822d5041380d483d46fc1` / `f0f360bb33d711c87fa4d311bb7d16282df419c4e8b309cab88eab7ef02c840d` |
| `rosy_60` | 요청 `cc10b3abfb651a24` 수락, `done`, 23:51:21 UTC 완료 | 왼쪽 아래 | `065a3f8640045675d3b702bddcad882e415d54fe20956ef06823334316e5cbe3` / `4a01ea09afe5c3013016e809d7d86eb22cc7f79dcf29d1dff9d3bcea2c7429b9` / `98534f65cefae44a41ea16a99651cf4d02efcbe378eca1fbc42a872facd87029` |

비공개 원본은 각각 `X:/DevTemp/rosy-id-proof-1009/rosy-id-proof-1009-26-b/`와 `...-60-b/`에 보관했다. 두 `manifest.json`의 SHA-256은 순서대로 `cb5df9bb6a8c6b44e59c5cfb080b575268a04197e1fdf0a15ab9fa46792970f6`, `687b478366be369f0e8827e60a1e99e6a83c11e16b32cbbbb497726bbba07af3`이다. 이는 [D-537](../../adr/D-537-one-time-physical-identity-proof.md)의 현재 주차 위치 대조다. 몸체나 카메라가 움직이면 다시 대조해야 한다.

## 이동 전 상태와 판정

- Fleet `GET /api/fleet/state`: 두 기체 `online`, 속도 0, E-Stop 표시 `false`; `rosy_26`은 `MANUAL`, `rosy_60`은 `IDLE`. 두 기체 모두 `evidence.safety.received_at=null`, `evidence.safety.evidence=disconnected`, `localization=null`이었다. 이 표시는 이동 허가 증거가 아니다.
- 각 기체의 올바른 ROS domain과 Cyclone DDS 설정으로 `/scan`을 읽었다. 720-beam LaserScan의 섹터별 최소 거리(−90…−30 / −30…0 / 0…30 / 30…90°, m)는 `rosy_26`: `0.148 / 0.129 / 0.130 / 0.112`, `rosy_60`: `0.558 / 0.487 / 0.256 / 0.108`이었다. 앞선 잘못된 domain의 `no_scan`은 센서 장애 증거로 쓰지 않는다.
- 새 머리 위 프레임에도 왼쪽 바퀴 경로 부근 케이블과 작은 물건이 보였다. 원본 `X:/DevTemp/rosy-current-ceiling-1009.jpg`의 SHA-256은 `55dc8b724ce0bc1c4dd1aa0ada12e35b291d102b84f163b19b23f84a18005fc5`다. 영상은 LCD 전면을 보여주지 않는다.
- [D-522](../../adr/D-522-development-remote-motion-operator-authority.md)의 이동 전 경로·안전 증거를 충족하지 못해 이 회차에는 이동 명령을 보내지 않았다. LCD 픽셀, 지도 위치, 운영용 지속 추적, Web 이동 및 물리 주행은 미검증이다. [이전 LCD 기록](../pinky-lcd-runtime-2026-10-09/result.md)과 [이전 몸체 대조](../pinky-physical-id-2026-10-09/result.md)를 대체하지 않는 재확인이다.
