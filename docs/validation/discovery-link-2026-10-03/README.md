# D-432 자동 발견·Pilot 앱 접속 검증

## 범위

2026-10-03 Windows 호스트의 `feat/common-discovery-link`에서 공통 LAN 발견·접속을 검증했다.
실제 주소·코드·토큰·화면 원본은 공개 저장소에 넣지 않는다.

- 영향받는 Python 계약: 2345 passed, 84 skipped.
- 저장소 quick tier: 459 passed, 2 skipped. Harness 기존 경고 26개.
- Pilot PWA 드라이버 및 화면 계약: 87 passed, 58 skipped. 등록된 드라이버의
  `describeReason` 누락으로 접속 화면이 멈추던 회귀를 실패 시험으로 재현하고 수정했다.
- 기존 코드 규약을 유지한 최종 인증·페어링 계약: 174 passed, 4 skipped.
- Cam: JVM 319개 성공, `testDebugUnitTest`와 `assembleDebug` 성공.
- 실제 TLS HTTP/WS는 발견 주소가 바뀌어도 DNS 이름·CA 검증을 유지하고 잘못된
  신원·정책·인증 실패를 거절한다. mDNS 캐시는 64개 상한·TTL·종료 정리를 갖는다.

## Android 앱과 실제 로봇

Lenovo TB-J606F에 무선 ADB로 독립 실행 Pilot APK를 설치했다. 화면 JS는 APK에
포함되며 앱 실행 → LAN 장비 목록 → 장비 선택 흐름이다. 설정 파일 가져오기는 없다.

실제 Rosy Pinky 두 대가 `_rosy._tcp`로 검색됐다. 선택한 로봇의 호스트 신원과
CORE active를 기존 고정 키 SSH로 확인했다. 로봇의 기존 릴리스는
`GET /api/v1/auth/connection`을 제공하지 않으므로 앱은 기존 코드 페어링으로 연결한다.
새 서버는 기본 paired 모드이며 명시적으로 켠 LAN development 모드에서만 코드 없이 접속한다.

PC 임시 CORE로는 개발 세션 발급·인증된 `/system/info` 조회를 확인했다.
이 결과와 실제 Pinky 연결 증거는 따로 판정한다.

## 화면과 발열

Cam은 과열 때 Activity 미리보기를 내리고 화면을 쉬게 한다. CameraX 캡처와 송출은
기존 foreground service가 유지한다. OS thermal severe 이상에서 동작하고, thermal
정보가 없는 기기에서는 배터리 온도 45℃를 보조 기준으로 쓴다. 복귀에는 이력 여유를 둔다.

Android의 즉시 화면 잠금은 사용자가 승인한 force-lock 권한으로 실행한다. 승인 전에는
화면 켜짐 강제 유지와 밝기를 해제하여 OS 화면 대기를 허용한다. 밝기 감소만으로 화면이
물리적으로 꺼졌다고 판정하지 않는다.

## 남은 장치 판정

호스트 시험과 APK 빌드는 ROS 2/ARM64 이미지 또는 현장 수용 증거가 아니다.
이번 접속 확인은 주행하지 않는다. 실제 페달 해제 정지, 실기 과열에 따른 화면 소등·
Cam 연속 송출, 현장 규모의 무선 트래픽은 해당 DEVICE/FIELD 검증이 필요하다.
