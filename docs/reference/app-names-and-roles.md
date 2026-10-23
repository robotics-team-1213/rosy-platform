# ROSY 앱 이름과 역할

전체 제품은 **ROSY Platform**이다. 아래 이름은 [D-806](../adr/D-806-app-display-names-and-implemented-product-roles.md)의 사용자 승인 명명안과 현재 소스 구조를 따른다. 앱은 사람이 사용하는 업무 단위이며 패키지·프로세스·호스트 개수와 같지 않다.

## 앱

| 표시 이름 | 사람이 하는 일 | 구현·소유 |
|---|---|---|
| **Rosy Robot** | 로봇 한 대 상태 확인·조작·설치·정비 | `middleware/robot_ui/robot`, CORE가 제공하는 웹 역할 화면 |
| **Rosy Fleet** | 현장 관제·작업 승인·진행·기기 연결·계정 관리 | `operations/site_ui/console`의 웹, `operations/fleet`의 서비스·원장. 화면 id는 `console` 유지 |
| **Rosy Pilot** | 직접 수동 운전과 운전석 영상 | `middleware/robot_ui/pilot`의 웹/PWA와 Android 연결 셸. 연결 로비는 별도 앱이 아님 |
| **Rosy Cam** | 카메라 폰에서 천장 영상 캡처·전송 | `operations/site_ui/cam`의 Android 앱. 관측 처리는 Vision 서비스가 담당 |
| **Rosy Learning** | 객체·픽셀 검수·자료 등록·학습 작업 | `learning/curation/perception/review_app.py`와 `review_app_web`의 웹앱. 학습 관리 센터이며 작업 실행은 기존 학습 소유자를 호출. 별도 미게시 화면을 이름 변경과 함께 추가하지 않음 |
| **Rosy Games** | 경기 운영과 게임 호스트 상태 확인 | `operations/apps/games`의 노트북 호스트·경기 보드. Fleet 관제나 CORE 로봇 모드가 아님 |
| **Rosy Vault** | (은퇴 2026-10-24) 보관고 입고·출고·장부·보류 작업 처리 | `rosy-vault` 저장소가 GitHub archived로 은퇴해 개발하지 않는다. 보관고 도메인은 선정되지 않았다 |
| **Rosy Device** | (은퇴 2026-10-24) 로봇팔 등 연결 기기의 상태·보정·설정·복구 | `rosy-vault`의 `device_core/web`이었다. 실물 팔 실행 경로는 플랫폼 OMX owner로 흡수한다(D-858). Robot의 `/device` 역할 화면과는 다른 구현이었다 |

## 외부 업무 앱

ROSY 제품 앱이 아닌 외부 업무 앱은 플랫폼 Python·DB·ROS를 쓰지 않고 공개 Fleet HTTP 계약만 소비한다. 소비 가능한 경로·권한·상태 의미의 기준표는 업무 앱 지원 계약 문서가 정하며 이 문서의 공개 게시는 후속 변경으로 따라온다.

| 앱 | 하는 일 | 저장소 |
|---|---|---|
| **Harbor** (HarborLogi) | 항만 모형 야드의 회수 순위·방해 화물 처리 제안, 업무 장부, 업무 완료 판정. Fleet HTTP로 제안·조회만 하고 로봇을 직접 움직리거나 승인하지 않는다 | 공개 팀 저장소 [kernel-robot-8th/kernel-robot-repo-2](https://github.com/kernel-robot-8th/kernel-robot-repo-2)의 `harborlogi/` |

## 상위 앱 안의 기능과 화면

| 이름 | 소속과 범위 |
|---|---|
| **Cell** (기존 공정 앱 명칭 Rosy Cell) | **Fleet의 팔레타이징 작업 준비**. `/console/cell`, 제목 `Rosy Fleet — Cell`. 레시피·작업대 설정 → 계획 미리보기 → 작업 제안. 별도 승인·진행은 Fleet이 소유 |
| **Studio** | Learning 안의 검수 작업대. Learning 전체 앱 이름으로 쓰지 않음 |
| **Account** | 공용 로그인·계정·권한 기능. Fleet 계정 관리는 `Rosy Fleet — 계정 관리`, Learning 계정 화면은 `Rosy Learning — 계정과 외부 자료` |
| **Pilot 연결 로비** | Android에서 신뢰된 대상 발견·접속을 제공하는 Pilot 하위 화면 |
| **로봇 얼굴 LCD** | Robot의 상태 표시 표면. 별도 Rosy Face 앱을 만들지 않음 |
| **오프라인 검수 페이지** | Learning의 엣지·영상 라벨 검수 산출물. 별도 검수 앱으로 등록하지 않음 |

## Cell의 구조와 책임

**Cell은 무엇을 어떻게 쌓을지 준비하고, Fleet은 승인한 작업을 조정하며, 장치는 실제 동작을 수행한다.**

1. Cell 화면은 레시피와 티칭한 작업대 설정을 편집·저장하고 계획을 요청한다.
2. 실제 팔레타이징 컴파일러는 `operations/processes/palletizing`에 있다. `operations/processes/cell/rosy_cell`은 기존 import 경로를 재노출한다.
3. `operations/fleet/fleet/server/cell`의 어댑터가 계획 후보를 기존 제안 경로에 연결한다. 문서 해시 검증·제안·별도 실행 승인을 구분한다.
4. Fleet이 작업 원장·배정·순서·자원 claim·결과를 관리한다. 장치 owner가 요청 수락·장치 계획·최종 실행·안전 판단을 담당한다.

Workcell은 좌표·설비·접근·공유 자원을 가진 작업 공간이다. Process는 그 공간의 업무다. 현재 Rosy Cell과 `rosy_cell.cell/2`를 모든 공정에 쓰는 범용 Workcell 계약으로 확대 해석하지 않는다([D-664](../adr/D-664-mixed-device-work-and-workcell-boundaries.md)).

혼합 레시피·여러 팔 컴파일과 팔별 원장 코드가 추가돼 있다. 그러나 D-778·D-781의 Proposed 상태, D-779의 계약 수용 범위, 실제 실행·DEVICE/FIELD 증거는 별도로 확인한다. 이름 정리로 수용 상태를 바꾸지 않는다.

## 서비스·설치·저장소 이름

| 이름 | 구분 |
|---|---|
| **CORE** | 로봇의 명령·상태 게이트웨이와 실행 경계 |
| **Fleet** | 현장 조정·승인·원장 서비스. 화면 이름은 Rosy Fleet |
| **Rosy Vision** | 천장 영상에서 관측을 만드는 서비스. 독립 사용자 화면 없음 |
| **World** | 관측·odom 등으로 현재 세계 상태·자세를 제공 |
| **Decision** | 규칙·정책·판단 후보를 다루는 영역. 독립 앱명 아님 |
| **Dock / Signal / Signal Observer** | 충전·교통 신호 장치와 관측 서비스. 독립 사용자 앱으로 세지 않음 |
| **Media** | 영상 세션 권한·시청 요청·미디어 프로세스를 관리하는 별도 서비스. `operations/site_ui/media`에 있으며 Fleet이 설치·제공하는 화면이 아님 |
| **Site App Gateway** | `operations/apps/fleet`의 프로세스 조립 코드. 휠 `rosy-app-gateway`, 명령 `rosy-site-gateway`. Fleet 서버나 Fleet 화면과 구분 |
| **device-core** | 은퇴한 rosy-vault 저장소가 제공하던 Rosy Device 콘솔·기기 API의 서비스 코드 이름(2026-10-24 은퇴). 로봇 CORE와는 다른 것이었다 |
| **ROSY Site / Runtime / Fabric / Operations** | 각각 현장 배포 범위 / 로컬 실행 기반 / 연결 계약·어댑터 / 운영 목표 표현. [D-290](../adr/D-290-rosy-platform-naming-and-site-intent-boundaries.md)의 역할 이름 |
| **rosy-platform / rosy-vault / rosy-ops / rosy-docs** | 각각 플랫폼 소스 / Vault·Device 소스(2026-10-24 은퇴, GitHub archived) / 비공개 운영 설정·기록 / 설계·가이드 문서 저장소 |

## 이름을 적용하는 기준

- 브라우저 제목은 `Rosy <App> — <화면>`이다. 첫 화면은 앱 이름만 쓸 수 있다. 앱 바에는 제품 워드마크와 현재 업무 설명을 나눠 표시할 수 있다.
- 웹 전용 Learning·Games는 `shared/web/surfaces.yaml`의 `title_prefix`, 기존 설치 앱은 `app_name`을 사용한다. 화면 이름만 바꾸려고 런처·PWA·패키지 신원을 만들지 않는다.
- 기존 URL·포트·surface id·패키지·systemd·프로토콜 스키마는 유지한다. 과거 ADR과 검증 기록의 이름은 당시 사실로 남긴다.
- 소스에서 이름이 맞는다는 사실과 실제 배포·장치 동작·현장 수용은 별개다.
