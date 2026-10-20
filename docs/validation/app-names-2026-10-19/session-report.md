# ROSY 앱 이름과 구조 정리

2026-10-19 사용자 승인 명명안에 따라 실제 화면·문서·검사를 수정했다. 전체 제품은 **ROSY Platform**, 사용자 앱은 **Rosy + 영어 한 단어**로 쓴다.

플랫폼 기준 문서는 [앱 이름과 역할](../../reference/app-names-and-roles.md), 결정은 [D-806](../../adr/D-806-app-display-names-and-implemented-product-roles.md)이다. 두 문서 모두 로컬 main에 병합됐다.

## 앱 이름

| 확정 표시 이름 | 역할 | 현재 형태·소유 |
|---|---|---|
| **Rosy Robot** | 로봇 한 대의 상태·조작·설치·정비 | 로봇 CORE가 제공하는 웹 역할 화면 |
| **Rosy Fleet** | 현장 관제·작업 승인·진행·기기 연결·계정 관리 | 웹 화면과 Fleet 서비스·원장. 이전 표시 이름은 Rosy Console이며 내부 id는 console 유지 |
| **Rosy Pilot** | 직접 수동 운전·운전석 영상 | 웹/PWA와 Android 연결 셸 |
| **Rosy Cam** | 천장 카메라 폰의 영상 캡처·전송 | Android 앱. 관측 처리는 Vision |
| **Rosy Learning** | 객체·픽셀 검수·자료 등록·학습 작업·카메라 맞춤·모방학습 | 모델 PC의 학습 관리 센터 웹앱 |
| **Rosy Games** | 경기 운영과 게임 호스트 상태 | 노트북 게임 호스트·경기 보드 |
| **Rosy Vault** | 보관고 입고·출고·장부·보류 처리 | 별도 rosy-vault 저장소의 업무 웹앱 |
| **Rosy Device** | 연결 기기의 상태·측정·보정·설정·복구 | rosy-vault/device_core의 기기 콘솔. Robot의 /device 역할 화면과 구분 |

## 앱 안의 기능

| 이름 | 소속·현재 역할 |
|---|---|
| **Cell** | **Fleet의 팔레타이징 작업 준비**. 현재 운영 화면은 /console/cell이며 제목은 **Rosy Fleet — Cell**. 기존 공정 앱 명칭 Rosy Cell과 rosy_cell 호환 경로는 유지 |
| **Studio** | Learning의 검수 작업대 |
| **Account** | 공용 로그인·계정·권한 기능. 화면 이름은 소속 앱을 따름 |
| **Pilot 연결 로비** | Pilot에서 신뢰된 장비 발견·접속을 제공하는 하위 화면 |
| **로봇 얼굴 LCD** | Robot의 상태 표시 표면 |
| **오프라인 검수 페이지** | Learning의 엣지·영상 라벨 검수 산출물 |

## Cell이 맡는 일

**레시피 + 작업대 설정 → 팔레타이징 계획 후보 → Fleet 작업 제안·별도 승인 → 장치 실행 → 결과 확인**

- Cell 화면은 레시피·티칭한 작업대 설정을 준비하고 적재 계획을 미리 본다.
- 실제 공정 코드는 operations/processes/palletizing에 있고, rosy_cell은 기존 import 경로를 제공한다.
- Fleet이 제안·승인·원장·순서·팔별 자원 claim·진행을 관리한다.
- 장치 owner가 요청을 수락하고 장치 계획·최종 명령·안전 판단을 맡는다.
- Workcell은 좌표·설비·접근·공유 자원이 있는 작업 공간이다. 현재 팔레타이징 앱 Cell을 범용 Workcell 관리 앱으로 해석하지 않는다.
- 혼합 레시피·여러 팔 코드가 있다는 사실과 D-778·D-781의 수용, 실제 양팔 동작·DEVICE/FIELD 검증은 각각 구분한다.

## 내부 이름

CORE는 로봇 실행 게이트웨이, Fleet은 현장 조정·원장, Vision은 천장 관측, World는 현재 세계 상태·자세, Decision은 판단 후보 영역이다. 이들을 모두 독립 사용자 앱으로 세지 않는다.

Dock·Signal은 현장 장치, Signal Observer는 관측 서비스다. Media는 영상 세션 권한·시청 요청·미디어 프로세스를 관리하는 별도 서비스이며 Fleet 화면이 아니다. device-core는 Rosy Device의 서비스 코드 이름이며 로봇 CORE와 구분한다.

operations/apps/fleet은 이름과 달리 Fleet 서버나 화면이 아니라 Site App Gateway 조립 코드다. 휠은 rosy-app-gateway, 명령은 rosy-site-gateway다. 현재 경로를 옮기지 않고 역할과 표시 이름을 구분해 기록했다.

ROSY Site·Runtime·Fabric·Operations는 D-290의 역할·배포 범위 이름이다. rosy-platform·rosy-vault·rosy-ops·rosy-docs는 저장소 이름이다.

## 실제 수정 범위

- Learning: 여섯 웹 화면과 오프라인 검수 산출물 제목을 **Rosy Learning — 화면**으로 통일. 계정 화면 앱 바도 Learning으로 표시.
- Games: 제목·앱 바를 **Rosy Games**로 정하고 **1v1 피치**는 업무 설명으로 유지.
- Fleet: 계정·로그인·프로필·지도·정책·Cell 제목을 **Rosy Fleet — 화면**으로 통일. Cell의 주제를 **팔레타이징 작업 준비**로 표시.
- Vault·Device: 브라우저 제목, 화면 이름, FastAPI 제목, README와 기존 HTTP 화면 검사를 수정.
- 분류·계약: D-806, 앱 역할 기준 문서, 화면 레지스트리, README·PRODUCT·CONCEPTS, 관련 회귀 검사와 모듈 기록 반영.
- 기존 URL·포트·패키지·systemd·스키마·명령 권한은 유지. 표시 이름 때문에 새 런처·PWA·아이콘·패키지를 만들지 않음.

## 작업 위치와 검증

- 플랫폼: 브랜치 uiux/app-names를 착지 도구로 로컬 main에 병합했다. 병합 커밋은 **d03d869688**이며, 구현·문서 커밋 **1b6a2f98f**와 공개 출처 등록 **4afd6c42b**가 포함된다. 이후 main에서도 해당 변경의 포함을 Git 이력으로 확인했다.
- Vault·Device: 최신 main과 합쳐 전체 검사 188 passed / 4 skipped를 다시 확인했고, main에 병합했다. main 커밋은 **ea2a5756c**다.
- 보관고 전체 검사: 188 passed, 4 skipped. 건너뛴 실제 Fleet 통합 검사는 별도 환경이 필요하다.
- 플랫폼 구현 시점 일반 회귀: **8,767 passed, 889 skipped**. 별도 관측 서비스: **647 passed**. 두 묶음 모두 exit 0, 새 실패 0.
- 실제 Chromium: 첫 실행 **230 passed / 4 failed**. 이전 Cell 안내·지도 제목을 기대하던 4건은 수정 후 **4 passed**. Games 480px·600px 별도 검사 **2 passed**. 수정 후 검사와 중간 폭 검사 모두 새 실패 0.
- 독립 리뷰에서 수정 필요 문제를 찾지 못했다. 검사 결과와 커밋별 적용 범위는 [검증 기록](result.md)에 남겼다. 이 원본 기록은 병합 과정에서도 보존했다.
- 최종 문서 커밋 **1b6a2f98f**의 원격 배치·폴더 검사 **18 passed**, 새 실패 0. 기록은 시스템 임시 디렉터리의 rosy-app-names-docs/run-1.txt다. harness lint는 오류 0이며 기존 모듈 검증 시점 등에 대한 경고는 남아 있다. 문서 링크와 ADR Log의 UTF-8 BOM·CRLF도 확인했다.
- 병합 중 원격 AI PC의 uv 부재로 한 실행이 중단돼, uv가 있는 모델 PC를 지정해 재실행했다. 검증 문서의 실제 Git 커밋 해시 6개 행이 비밀 토큰으로 오인된 문제는 독립 확인 후 기존 공개 출처 목록에 정확한 행 해시·값을 등록해 해결했다. 검사 규칙과 원본 기록은 유지했고, 관련 원격 검사 **97 passed**를 확인했다.
- 최종 병합 커밋 **d03d869688**: 최신 main **6f6c53fee0**를 합친 상태에서 구조 선행 검사 **247 passed**, 일반 회귀 **8,682 passed / 890 skipped**, 별도 관측·기기 검사 **807 passed**, 실제 Chromium 네 묶음 **239 + 347 + 424 + 188 = 1,198 passed**. 새 실패 0으로 착지 도구가 exit 0을 반환했다. 로그는 시스템 임시 디렉터리의 `rosy-land/uiux-app-names/`, 착지 확인서는 Platform의 `.git/rosy-land/commit d03d8696880f7bfc236420f99c0713c2d5d5922f.json`이다.
- **Platform과 Vault·Device 모두 로컬 main 병합 완료.** main 이력에서 두 저장소의 이름 변경 커밋 포함을 확인했다. 이후 요청한 원격 게시·배포의 진행 상태와 실제 설치 확인은 [배포 기록](../rosy-app-deployment-2026-10-19/result.md)에 별도로 남겼다.
