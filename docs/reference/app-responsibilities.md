# 앱별 작업과 책임

Rosy Fleet은 **현장 운영**, Rosy Robot은 **한 대 관리**, Rosy Pilot은 **직접 운전**, Rosy Cam은 **카메라 송신**, Rosy Learning은 **학습 루프(수집 → 정답 → 데이터셋 → 학습 → 평가 → 승격 기록)**를 맡는다(D-857). 앱 화면, API, 사실을 저장하는 정본과 실제 장치 실행 권한은 서로 구별한다.

## 사용자 진입

| 구분 | 이름·소스 | 소유 작업 | 다른 소유자에게 연결할 작업 |
|---|---|---|---|
| 현장 웹 앱 | Rosy Fleet, `operations/site_ui/console` | 감시·작업·지도·설치·계정 관리 화면 | 한 로봇 상세 정비는 Robot, 직접 운전은 Pilot |
| 로봇 웹 앱 | Rosy Robot, `middleware/robot_ui/robot` | 상세 상태·전방 영상·작업 준비·로컬 조작·영구 설정·정비 | 직접 운전은 Pilot, 현장 작업 조정은 Fleet |
| 조종 웹/PWA/Android | Rosy Pilot, `middleware/robot_ui/pilot` | 직접 운전·운전 영상·현재 조종 세션·세션별 설정·기록 | 영구 설정·정비는 같은 대상의 Robot |
| Android 앱 | Rosy Cam, `operations/site_ui/cam` | 캡처·송신·물리 설치와 연결 안내 | 사이트 승인·좌표 보정은 Fleet 설치 |
| 학습 센터 화면 | Rosy Learning, `learning/curation/perception/review_app_web` | 5단계 메뉴(홈·자료·정답·학습·평가·승격): 정답 달기·확인, 학습 실행 요청, 평가 결과, 승격 요청(D-857) | 학습·평가 실행은 각 pipeline owner, 승격 승인·배포·모델 활성화는 Fleet·사람·배포 owner |
| 표시 전용 | Face, `middleware/robot_ui/face` | 이름·표정·부팅·연결 상태 | 입력·운동 명령 없음 |
| 관측 서비스 | Rosy Vision, `operations/overhead` | 프레임 수신·관측 생성·허가된 preview | 명령·현장 원장은 Fleet/장치 owner |
| 공통 신원 | Rosy Account, 기존 Fleet auth 배포 | 사람 신원·권한·세션·회수 | 장치 admission·조종 좌석·업무 승인과 구분 |
| 업무 도구 | Games 보드, `operations/apps/games` | 경기 상태와 경기별 입력 | 사이트 Mission과 최종 장치 명령은 별도 owner |
| 개발 도구 | control diagnostic / lane live view | 현재 PARKED 진단 / 시뮬 관측 | 제품 운용 진입으로 확대하지 않음 |
| 공유 기반 | `shared/web` | 디자인·컨트롤·통신 도구 | 사용자 업무·전역 인증 상태를 소유하지 않음 |

Fleet 내부 id·아이콘·URL의 `console`은 호환 식별자다. 표시 이름은 Rosy Fleet이다(D-487). Robot의 `/console`은 그 로봇의 운용 화면이다. Learning은 별도 런처/PWA 등록을 뜻하지 않는다. Pilot Android는 같은 조종 앱의 제공 방식이며 별도 실행 권한을 만들지 않는다.

## 작업별 정본과 완료 확인

아래 경로는 소스 owner다. 배포 호스트·설치 identity는 [폴더 책임 안내](platform-folder-responsibilities.md)와 실제 설치 manifest로 확인한다.

| 사용자 작업 / 화면 | API·소스 owner | 상태 정본 / 최종 실행 | 완료 확인과 소비자 |
|---|---|---|---|
| Mission 요청·진행·개입 / Fleet 작업 | `operations/fleet/fleet/server/missions/{mission_routes,mission_service,mission_store}.py` | Fleet Mission 원장 / 장치 로컬 Action owner | 원장 상태와 연결된 장치 결과·목표 증거. HTTP 수락만으로 물리 완료를 확정하지 않음 |
| 현장 등록·기기 승인 / Fleet 설치 | `operations/fleet/fleet/server/auth/{enrollment_routes,enrollment_store,pairing_routes}.py` | 승인·등록·카메라 자격의 기존 store / 장치 명령 없음 | 서버 등록 결과. 검색 목록에 보임·로그인 성공과 등록 승인은 별개 |
| 현장 좌표·카메라 보정 / Fleet 설치·지도 | `operations/site_ui/console/{install,site-map,field-view}.js`와 해당 Fleet API | 활성 map/fit의 기존 Fleet 저장 owner / 장치 주행 없음 | 승인·저장된 보정 결과. Cam 송신 성공은 좌표 보정 완료가 아님 |
| 영구 설정 / Robot 설치·정비 | `middleware/robot_ui/robot/settings.js`, CORE API | CORE 설정 owner / 설정을 적용하는 로컬 기능 | 서버 저장·읽기 결과. Pilot 세션 프리셋은 이 정본을 수정하지 않음 |
| 로컬 목표·도킹 / Robot | `middleware/core/api/core_api_web/api/v1/{navigation,docking}.py` | 로컬 동작 상태 / CORE 명령 중재·장치 실행 | 로컬 동작 상태·결과. 사이트 Mission 순서는 Fleet에 남음 |
| 직접 운전 / Pilot | `middleware/robot_ui/pilot/{client,app}.js`와 `screens/drive.js`, CORE API | 장치의 조종·안전 상태 / Pinky CORE 최종 주행 명령 | 장치 응답·상태, 누름 해제·종료·연결 상실의 정지 경로. 페이지 이동만으로 운전 시작 금지 |
| 현장 정지 / Fleet, 개별 정지 / Robot·Pilot | Fleet stop owner 및 `middleware/core/api/core_api_web/api/v1/safety.py` | Fleet 요청 결과와 로컬 안전 래치 / 각 장치 owner | 요청 접수·장치 래치·물리 정지를 별도로 표시. 취소와 e-stop을 합치지 않음 |
| 카메라 송신 / Cam | Cam Android, `operations/overhead/rosy_vision` ingest | 프레임·관측 생산자 / 장치 명령 없음 | 송신·수신 상태. 현장 등록과 관측 신선도·보정은 별도 확인 |
| 검수·승인·export / Learning | `learning/curation/perception/review_app.py`와 검수 handlers | 검수 state/SQLite·exports / 로봇 실행 없음 | 저장 revision·승인·export receipt. 데이터셋 수용·학습 실행·모델 활성화 증거로 대체하지 않음 |
| 사용자·권한 관리 / Fleet 계정 | `operations/fleet/fleet/server/auth` | Account 원장·회수 revision / 장치 admission과 분리 | 현재 서버 권한·세션 결과. 각 앱은 대상별 권한을 다시 검사 |

Fleet → Robot/Pilot은 등록된 장치 식별자에 결속된 주소만 사용한다. 발견된 주소, 로봇 표시 이름이나 포트 추정만으로 목적지를 만들지 않는다. 앱 전환에 토큰을 URL로 전달하지 않으며, 접근 자격은 기존 Account 흐름으로 처리한다. 승인된 주소라도 현재 닿는다는 보장은 아니므로 연결·권한 상태는 대상 앱에서 확인한다.

현재 Fleet 카드의 외부 링크는 PeerCatalogue의 `approved-directory` 행만 사용한다. 승인 신원에 연결된 mDNS 광고도 transport·port까지 승인된 것은 아니므로 링크 원본으로 사용하지 않는다. catalogue가 등록 directory 행을 광고 행으로 대체한 경우에는 링크 대신 안내를 표시한다. 화면 이탈·복원·사용자/역할 변경 때 이전 링크와 cache를 먼저 폐기한다.

## 현재 이행 항목

| 항목 | 처리 | 조건·근거 |
|---|---|---|
| Fleet/Robot/Pilot 이름·현재 URL·서버·프로세스 | 유지 | D-377·D-425·D-487 |
| 앱 간 이동과 업무 안내 | 연결·정리 | 현행 roster/peer/Account 계약 소비, 새 실행 API 없음 |
| Robot `console.teleop` | 증거 확인 뒤 링크 전환 | Pilot `progress.md`의 2026-10-05 DEVICE GO를 보존. D-323 Validation과 현재 대상·릴리스별 증거의 연결이 필요하며, 미확인 대상은 이행 예외 유지 |
| Robot 로컬 목표·도킹·영구 설정 | 유지 | 직접 운전과 다른 사용자 작업 |
| 앱별 인증 자동 연결 | 기존 Account 계획 소비 | [Account 실행 계획](../plans/2026-10-14-rosy-account-completion.md); 기계 자격·조종 좌석은 사람 로그인과 별개 |
| 진단·시뮬·Games | 현 상태 유지 | 새 제품 앱·런처를 선행 생성하지 않음 |

## 검증 연결

- `test/architecture/test_app_roles.py`: Cam/Vision의 실행 경계와 표면 소유·이행 예외.
- `test/test_app_ownership_contracts.py`: 실제 CORE 인증·설정 쓰기·Fleet 정지의 owner와 거절.
- `operations/fleet/test/test_document_imports.py`: Fleet 운용/설치 문서의 기능 import 경계.
- `test/test_role_menu_migration.py`: Robot 패널의 표면·설치 위치와 현재 이행 조종 계약.
- 앱 간 이동·화면·설치 검증은 [실행 계획](../plans/2026-10-16-app-role-clarity.md)과 실행 결과 기록을 따른다. 계획·소스·호스트 시험은 DEVICE/FIELD 증거를 대신하지 않는다.
