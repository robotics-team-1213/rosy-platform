# 다기종 ROSY 배포 준비

2026-10-25. 기체에 직접 설치하는 ROSY와 제조사 SDK 호스트에 설치하는 연결 어댑터를
구분해서 준비한다. 이 문서는 기종 접수·배포 준비 기준이며 실행 설정 schema나
새 비행 API가 아니다. 현재 기종별 상태는 [호환 목록](../reference/robot-compatibility.md)을 따른다.

## 배포 경로 선택

| 경로 | ROSY 산출물의 설치 대상 | 먼저 확인할 것 | 현재 적용 |
| --- | --- | --- | --- |
| 기체 직접 설치 | 기체의 Linux 컴퓨터 | 보드/CPU/OS, native 패키지 closure, 드라이버, 로컬 제어와 정지, 부팅/복구 | Pinky 기존 구현; RaspTank 설정 소스 준비 |
| 외부 SDK 연결 | 휴대전화·조종기 앱 또는 연결 호스트 | 정확한 기종/조종기/펌웨어/SDK 지원, 호스트 OS, 인증, 제공 API, 로컬 제어권과 링크 단절 동작 | 후속 설계 대상. 설치 가능한 ROSY SDK 어댑터는 아직 없음 |
| 관측 또는 수동 운영 | 검증된 데이터 수신 호스트/운영 기록 | 실제 제공 데이터 경로, 원본 시각·출처·보존·권한 | 제어 불가 기종에도 검토 가능하나 데이터 연결도 별도 증거 필요 |

외부 연결형에 ROSY를 배포한다는 것은 제조사 기체 펌웨어를 ROSY로 교체한다는 뜻이 아니다.
제조사 SDK 지원 여부, ROSY 어댑터 소스 존재, 설치 가능한 릴리스, 실물 제어 수용을 각각 기록한다.
SDK가 없으면 연결 가능한 것처럼 보이는 빈 드라이버·가짜 telemetry·성공 응답을 만들지 않는다.

## 현재 배포 코드와의 접점

- `deploy/robot/pinky_pro/image/create-image-manifest.py`는 `board=pinky_pro`를 만든다.
  `deploy/robot/pinky_pro/sd/provision.schema.json`도 모델을 `pinky_pro`로 제한한다.
  이 제한을 풀기만 해서는 RaspTank 또는 SDK 호스트용 이미지가 되지 않는다.
- `contracts/foundation/core_common/profile.py`의 모델 조회를 재사용하되,
  `middleware/core/gateway/core/node.py`의 절대경로 overlay는 모델 조회를 우회할 수 있다.
  제품 시작 시 선택 기종·설치 package·실제로 읽힌 설정·capability의 결속 검증이 선행되어야 한다.
- 서명·digest·의존 목록·설치 readback·롤백 규칙은 기존 릴리스 경계를 따른다.
  공통 처리 추출은 두 번째 실제 소비자가 확인된 부분부터 하며 기존 Pinky 패키지를 일괄 이동하지 않는다.
- SDK 호스트용 산출물은 그 호스트의 플랫폼에 맞게 별도로 설계한다. Android 앱을 Pi 이미지로
  배포하거나 제조사 SDK 바이너리를 재배포 허가 확인 없이 공통 이미지에 넣지 않는다.

## 새 기종 접수표

다음 표를 복사해 기종별 준비 기록을 작성한다. 미확인 값은 그대로 미확인으로 두며,
이 표의 값은 아직 런타임이 소비하는 manifest 필드가 아니다.

| 항목 | 작성할 근거 |
| --- | --- |
| 기종 식별 | 제조사·정확한 모델·보드 revision·기체 펌웨어. 마케팅 이름과 설치 package 이름 구분 |
| 배포 대상 | 기체/조종기/휴대전화/연결 호스트 중 실제 설치 대상, OS/CPU/지원 버전 |
| 공식 연결 경로 | SDK/API 이름·고정 버전·지원 기종/조종기·공식 URL·확인일. 미지원과 미조사를 구분 |
| 배포 권리 | SDK 라이선스·재배포 조건·개발자 계정/app key·온라인 활성화·지역 의존 여부 |
| 실제 기능 | 관측/영상/수동 제어/업무 action을 분리. 각 기능의 공식 API와 실제 검증 상태 |
| 명령 소유권 | 최종 장치 writer, 제조사 앱/수동 조종과의 제어권 전환, 병행 실행 차단 |
| 상태와 결과 | 원본 시각·좌표계·단위·ACK/실행/완료의 차이, 재연결 후 UNKNOWN 재조회 |
| 단절과 복구 | 링크·호스트·프로세스·전원 실패 때 장치가 수행하는 동작, 재시작 후 자동 재실행 여부 |
| 설치 산출물 | commit·SDK lock·dependency inventory·서명/digest·설치 검사·복구용 이전 버전 |
| identity·비밀 | 어댑터 호스트와 실제 장치 identity의 결속, 키/토큰 보관·회수, 이미지 복제 시 중복 방지 |
| 자원 | 전력·열·RAM·영상 대역폭·지연·보존 로그 용량의 측정 조건과 결과 |
| 증거와 담당 | SOURCE/LOCAL・ROS-SIM・ARTIFACT・DEVICE・FIELD 각각의 로그/commit·담당·차단 사유 |

공개 문서에 실제 계정·장치 serial·주소·키를 넣지 않는다. 영상이 보이거나 호스트가 온라인이라는
사실을 기체의 조작 가능·작업 완료 근거로 사용하지 않는다.

## SDK 어댑터 준비 순서

1. 공식 지원표와 해당 SDK 문서로 기종/조종기/펌웨어 조합을 확인한다. 미지원이면 제어 구현을 중단하고
   차단 이유·확인일·재검토 조건을 기록한다. 관측용 경로도 제공된다고 가정하지 않는다.
2. 지원 조합이면 별도 호스트에서 공식 예제의 연결·상태 조회부터 검증한다.
   계정 등록·SDK 설치·유료 구매·장치 접근은 준비 문서와 실제 수행을 구분해 기록한다.
3. 기존 ROSY 명령/결과 계약과 비교해 맞는 부분만 재사용한다. SDK 호출 수락을 동작 완료로 바꾸지 않는다.
   취소/timeout 뒤 실제 결과가 불명이면 UNKNOWN을 유지하고 물리 명령을 자동 재전송하지 않는다.
4. 버전 고정 SDK 응답의 replay/mock으로 인증 실패·미지원·stale·중복/지연·재시작·단절 반례를 검증한다.
   mock 통과는 제조사 SDK 연결이나 실제 장치 결과를 증명하지 않는다.
5. 배포 대상별 패키지/앱의 서명·설치·readback·rollback을 검증하고, 실제 장치의 기능별 수용 후
   해당 기능만 관제에 노출한다. 업데이트 시 SDK/기체 펌웨어/조종기 조합을 다시 검증한다.

## 비행 기종의 별도 경계

[D-305](../adr/D-305-platform-boundary-outcome-invariants-and-independent-gates.md)에 따라
Pinky의 평면 `x/y/yaw`, `RobotMode`, `/cmd_vel`과 ground stop 의미를 드론에 그대로 확장하지 않는다.
Fleet은 업무 입장·dispatch·원장을 소유하고 비행 제어의 최종 owner는 별도 검토한다.
이 준비서로 새 flight action schema나 owner를 승인하지 않는다.

기종 선정 후 좌표계/고도 기준·비행 모드·arming·이착륙·수동 인계·링크 단절·배터리 부족·위치 추정
상실의 실제 동작을 확인한다. 공중에서의 안전 동작은 기종별 hover/return/land 등으로 검토하며,
지상 로봇처럼 단순한 출력 0이나 전원 차단을 공통 stop으로 호출하지 않는다.
비행 시험은 장치·운영 환경에 대한 별도 승인과 수용 절차로 수행한다.

## DJI Neo 2 판정

**2026-10-25 공식 자료 확인: SDK 제어 미지원. ROSY 직접 설치·SDK 어댑터·실시간 telemetry/영상 연결 모두 미구현/미수용.**

DJI 공식 [SDK 호환표](https://repair.dji.com/help/content?customId=01700000763&documentType=&lang=en&paperDocType=ARTICLE&re=US&spaceId=17)는
Neo 2를 Windows/Mobile/Onboard SDK 미지원으로 표기한다.
공식 SDK 저장소 [문의 #684](https://github.com/dji-sdk/Mobile-SDK-Android-V5/issues/684)에서
DJI 지원팀은 2025-12-24 Neo 2 대응 계획이 없고 Enterprise 기종 지원에 집중한다고 답했다.
이는 당시 계획 답변이며 미래 지원을 단정하지 않는다. 공식 지원표가 변경되면 다시 판단한다.

DJI Fly로 조작할 수 있다는 사실은 제3자 SDK 제어 권한이 아니다.
Cloud API·Payload SDK 등 다른 SDK가 Neo 2에도 적용된다고 추론하지 않는다.
비공식 프로토콜·제조사 앱 화면 자동화를 제품 제어 지원의 근거로 채택하지 않는다.
현재 가능한 준비는 기종 목록과 공식 지원 근거를 보존하고, 수동 운영·파일 반입의 후속 요구를
분리하는 것이다. 파일 반입이나 관측 연동도 이번에 구현된 기능은 아니다.

[공식 Mobile SDK 제품 목록](https://developer.dji.com/mobile-sdk/)에는 Mini 4 Pro·Mini 3 계열 및
일부 Enterprise 제품이 올라 있다. 이것은 외부 SDK 연결형을 검토할 후보 근거이며 구매 추천이나
ROSY 지원 선언이 아니다. 조종기·SDK 버전·필요 API·실물 수용을 확인하기 전 선정하지 않는다.
