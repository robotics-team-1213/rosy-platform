# D-432 자동 발견·Pilot 앱 접속 검증

## 범위

2026-10-03 Windows 호스트의 `feat/common-discovery-link`에서 공통 LAN 발견·접속을 검증했다.
실제 주소·코드·토큰·화면 원본은 공개 저장소에 넣지 않는다.

- 영향받는 Python 계약: 2345 passed, 84 skipped.
- 저장소 quick tier: 459 passed, 2 skipped. Harness 기존 경고 26개.
- Pilot PWA 드라이버 및 화면 계약: 87 passed, 58 skipped. 등록된 드라이버의
  `describeReason` 누락으로 접속 화면이 멈추던 회귀를 실패 시험으로 재현하고 수정했다.
- 기존 코드 규약을 유지한 최종 인증·페어링 계약: 174 passed, 4 skipped.
- Cam: 기존 코드 규약을 유지한 최종 JVM 318개 성공, `testDebugUnitTest`와 `assembleDebug` 성공.
- 실제 TLS HTTP/WS는 발견 주소가 바뀌어도 DNS 이름·CA 검증을 유지하고 잘못된
  신원·정책·인증 실패를 거절한다. mDNS 캐시는 64개 상한·TTL·종료 정리를 갖는다.

## Android 앱과 실제 로봇

Lenovo TB-J606F에 무선 ADB로 독립 실행 Pilot APK를 설치했다. 화면 JS는 APK에
포함되며 앱 실행 → LAN 장비 목록 → 장비 선택 흐름이다. 설정 파일 가져오기는 없다.

실제 Rosy Pinky 두 대가 `_rosy._tcp`로 검색됐다. 선택한 로봇의 호스트 신원과
CORE active를 기존 고정 키 SSH로 확인했다. 로봇의 기존 릴리스는
`GET /api/v1/auth/connection`을 제공하지 않으므로 앱은 기존 코드 페어링으로 연결한다.
새 서버는 기본 paired 모드이며 명시적으로 켠 LAN development 모드에서만 코드 없이 접속한다.

실제 태블릿에서 기존 8자리 코드로 Pinky 페어링이 성공했다. 앱에 장비 이름과 `연결됨`이
표시됐고, 인증된 로봇 ID `rosy_60`을 확인했다. 설정 가져오기·주소 입력 없이 목록에서 선택했다.
검증 중 코드 입력 자동화의 하이픈 처리·장비 행 위치 갱신·코드 만료 문제를 구별했고 새 코드로
재확인했다. 임시 진단 토큰은 로그아웃 204를 확인했다. 태블릿 앱에 저장한 운영자 자격은
다음 접속에 쓰도록 유지하며 공개 로그·스크린샷에 포함하지 않는다. 주행 명령은 실행하지 않았다.

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

## 최종 Pilot UI와 공용 디자인 적용

`impeccable` Operate·`frontend-ui-engineering` 기준으로 목록/연결/카메라/주행/입력/녹화본/
OMX SIM/태블릿 메뉴를 순차 점검했다. 결정은 D-432와 DESIGN.md에 기록했다.
웹 버튼은 공용 `actionIcon`과 기존 컨트롤/토큰을 쓰고, native 색·theme·vector·런처는
canonical tokens.css에서 build 시 생성한다. 누락된 색 역할은 build를 실패시킨다.

실제 Lenovo 태블릿에서 로봇 두 대 발견, Pinky 선택/인증된 로봇 ID 확인, 저장 자격 재접속,
조회 전용 카메라 전체 영상/채우기/접속 화면·목록 복귀를 확인했다. 담당 에이전트의 기록 외에
주 담당자가 실제 설치 화면과 가로/세로 브라우저 화면을 직접 보았다. 시스템 글자 130%에서도
native 목록과 검색/태블릿 메뉴가 잘리지 않는 것을 확인하고 원래 글자 크기로 복귀했다.

검은 카메라 화면의 원인은 grid 안의 높이 100% 계산이었다. flex 높이 연결로 수정했다.
입력 설정 변경 뒤 detached preview node를 갱신하던 문제도 수정했다. 보조 패널은 한 번에
하나만 열고 닫으면 보이는 도구 버튼으로 초점이 돌아간다. 공유 아이콘은 재적용해도 한 개이며
비활성 사유와 Enter 동작을 보존한다.

카메라를 볼 때 `/mode` 쓰기나 주행 목표를 보내지 않는다. 최초 장비 확인에서는 EMERGENCY,
이후 진단 조회에서는 IDLE였으며 이 작업에서 비상 정지를 해제하거나 양의 주행을 실행하지 않았다.
원본 320×240의 센서 표시와 낮은 해상도는 앱 크기 변경으로 제거/개선되지 않는다. 장치 보정에
영향을 줄 수 있어 원본 해상도나 센서 overlay는 변경하지 않았다.

| 검증 | 결과 |
|---|---|
| native Pilot JVM + APK build | 30 passed, 실패/오류/skip 0, 설치 완료 |
| Cam JVM + APK build | 318 passed, 실패/오류/skip 0 |
| 공용 웹 UI host suite | 214 passed, 24 skipped |
| quick tier (D-418 통합 후) | 459 passed, 2 skipped, 기존 이력 warning 27 |
| SSH/발견 접속/TLS/native 설치 영향 범위 | 480 passed, 7 skipped |
| 마지막 main 문서 통합 후 harness/network/version | 86 passed, 기존 이력 warning 27 |
| 최신 D-435 main 통합 후 network/harness/parts/colcon/version | 108 passed, 기존 이력 warning 27 |

브라우저 시험은 opt-in으로 별도 실행한다. 녹화 관련 9개·나머지 시나리오 50개·공용 아이콘
1개가 통과했고, 전체 실행 중 스틱 해제 뒤 마지막 응답 확인에서 한 번 실패한 두 viewport
시험은 소스 변경 없이 따로 재실행하여 2개 모두 통과했다. OMX 재조작 시험은 전역 SUCCEEDED가
새 목표까지 즉시 완료하여 count 2를 지나치는 fixture 문제를 진단했다. 단순 RUNNING 재설정도
이전 목표를 다시 실행 중으로 만들어 실패했으므로, 완료 receipt를 해당 목표 ID에만 고정했다.
제품 제어 로직은 변경하지 않았다. 관련 완료/접속 상실/sequence/연속 조작 4개가 통과했고,
최종 fixture 수정 후 재조작 시험 1개도 통과했다(57.16초). 전체 63개 항목이 분할 실행에서
통과했다. 첫 실행의 실패를 전체 최초 통과로 기록하지 않는다.

native UI 커밋 `768837712`, 웹/ADR 커밋 `e084652fb`, D-418 통합 `770168ae3`,
통합 계약 수정 `c98c8de75`. API Ref는 D-418 v1.89를 보존하고 D-432를 v1.90으로 기록한다.
최종 설치 APK SHA256: `bc78d4ff674b0b0c5401f2384f0e85f06c13033734a3d04c426af2fef0a864c7`.
APK 안의 `assets/common/ui.js`와 현재 공용 소스의 바이트 일치를 주 담당자가 확인했다.

첫 local main 머지 시도는 다른 세션의 미커밋 `docs/index.md`·`docs/logs.md` 보호 때문에 Git이
거부했다. 해당 파일을 stash·삭제·대신 커밋하지 않았다. 이후 소유 세션이 `b2fb0c276`에
커밋한 최신 main을 `b827a1e6d`에서 통합하고 양쪽 journal과 generated index를 보존했다.
main 최종 착지는 커밋/병합 결과를 별도 확인하며 원격 push/CI나 물리 수용 증거로 확장하지 않는다.
