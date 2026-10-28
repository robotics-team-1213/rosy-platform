## D-806 앱 표시 이름은 현재 구현한 제품 역할을 따른다

**Status:** Accepted (2026-10-19, 사용자 명명안 승인; 표시 이름·분류·브라우저 제목 범위).

## Context

현재 Rosy Learning은 앱 바에서 Learning을 쓰지만 탭에는 `Rosy 개발`, 계정 화면에는 `ROSY`를 쓴다. 경기 앱은 `Rosy 사이트`, Fleet의 계정 화면은 `Rosy Account`로 보여 상위 앱을 구분하기 어렵다. 별도 저장소의 보관고 웹앱은 설명만 표시한다. Cell은 공정 애플리케이션 이름, Fleet 내부 화면, 작업 공간 개념과 혼용된다.

사용자는 현재 구현하는 앱 구조를 검토하고 이름을 화면·문서·검사까지 맞추도록 요청했으며 아래 명명안을 승인했다. 새 실행 권한이나 설치 구조를 만드는 결정은 아니다.

## Decision

1. 전체 제품은 **ROSY Platform**이다. 사람에게 표시하는 앱 이름은 **Rosy + 영어 한 단어**로 쓴다. 기존 **Rosy Robot, Rosy Fleet, Rosy Pilot, Rosy Cam, Rosy Learning, Rosy Device**를 유지한다. 보관고 앱은 **Rosy Vault**, 경기 앱은 **Rosy Games**로 부른다. Vault와 Device 구현은 별도 `rosy-vault` 저장소가 소유한다.
2. **Cell은 Fleet의 팔레타이징 작업 준비 화면**이다. 기존 공정 애플리케이션 명칭 Rosy Cell과 `rosy_cell` 호환 경로는 유지한다. 화면의 브라우저 제목은 `Rosy Fleet — Cell`, 주제는 `팔레타이징 작업 준비`다. 레시피·작업대 설정으로 계획 후보를 만들고 Fleet에 제안한다. 미리보기·제안은 실행 승인이 아니다. Fleet이 원장·승인·배정·자원을 소유하고 장치 owner가 수락·실행·최종 안전 판단을 소유한다. D-664의 범용 Workcell과 현재 팔레타이징 계약은 계속 구분한다.
3. **Account는 공용 계정·인증 기능**이며 Fleet의 계정 관리 화면은 Fleet 이름으로 표시한다. Learning의 계정·외부 자료 화면은 Learning 이름으로 표시한다. `Rosy Account 로그인` 같은 인증 기능 설명과 기존 인증 계약은 유지한다. **Studio는 Learning의 검수 작업대**, **Pilot 연결 로비는 Pilot의 하위 화면**, **얼굴 LCD는 Robot의 상태 표시 표면**이다. 이를 독립 앱으로 새로 등록하지 않는다.
4. 앱 안의 브라우저 제목은 **`Rosy <App> — <화면>`**이다. 앱 첫 화면은 앱 이름만 쓸 수 있다. D-339의 일반 범위 제목은 앱 이름이 없는 진단·시뮬 표면에 유지한다. Learning의 `Rosy 개발 —` 제목 규칙(D-792 1항의 제목 부분)을 이 규칙으로 대체한다. D-377의 설치 앱 신원과 D-487의 Fleet 표시 이름·기존 id 예외는 유지한다.
5. **웹 화면 이름과 설치 신원은 구분한다.** `shared/web/surfaces.yaml`의 `title_prefix`는 Learning·Games의 브라우저 표시 이름을 기록한다. `app_name`과 달리 런처·PWA·아이콘·ROS·Android 패키지를 등록하지 않는다. 기존 id `pinky-review`, `game-board`, `console`, URL·포트·스키마·실행 파일·systemd 유닛은 바꾸지 않는다. 이름을 맞추기 위한 폴더 이동이나 호환 패키지 추가도 하지 않는다.
6. 현재 앱 분류·소유·경로는 [앱 이름과 역할](../reference/app-names-and-roles.md)에 적는다. 이 문서의 배포·실물 수용 여부는 별도 증거로 판단한다. 양팔 코드의 존재를 D-778·D-781의 수용이나 DEVICE/FIELD 검증 완료로 표시하지 않는다.

## Architecture boundaries

| 기존 결정 | 관계 |
|---|---|
| D-427 폴더별 책임 | 기존 소유 위치에 표시 이름·제목만 맞춘다. 새 part나 설치 경로를 만들지 않는다 |
| D-429 책임·의존 방향 | 화면은 기존 API를 소비한다. 공정 후보·Fleet 원장·장치 실행의 의존 방향을 유지한다 |
| D-430 안전 경계 | 명령·정지·grant·원장 로직과 안전 경로는 변경하지 않는다 |

## Consequences and validation

- 브라우저 탭과 앱 바에서 현재 앱을 알 수 있고, 기능 이름이 별도 제품처럼 보이지 않는다.
- `shared/web/test/test_surface_titles.py`는 Learning·Games의 웹 표시 이름과 Fleet 계정·Cell 등 하위 문서의 제목도 검사한다. 기존 D-377 앱 신원 검사는 유지한다.
- Games의 경기 맥락 `1v1 피치`는 앱 이름 아래 설명에 남기며 정지 조작·권한을 유지한다. 기존 경기 보드·Fleet 정적 제공·계정·Learning 검사를 함께 실행한다.
- `rosy-vault`는 두 웹 화면·서비스 제목·기존 HTTP 화면 시험에서 Vault와 Device 이름을 확인한다. 플랫폼 저장소에 외부 앱을 복제하지 않는다.
- 표시 이름 변경은 실물 로봇·팔·폰 배포나 동작 수용을 뜻하지 않는다.
