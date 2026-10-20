# Fleet 프런트 분리: API 대응과 남은 확인

기준: main `45b2bfe064b739d425564d1bd0b3c06af314fa2f`, 2026-10-21 코드 조사. 실행·배포 검증 결과가 아니다. [분리 설계](2026-10-21-fleet-frontend-development-design.md)의 실행 계획 입력이다.

## 판단

CORE·Fleet의 주요 HTTP API와 프런트 소비 경로는 구현돼 있다. 모든 기능에 대해 요청·권한·진행·결과·실패 계약이 충분한지는 아직 확정하지 않았다. 아래 표는 소스에서 확인한 기능군 대응이며, 구현 단계에서 method/path별 시험과 샘플 시나리오로 세분화해야 한다.

- CORE: `middleware/core/api/core_api_web/api/app.py`가 상태·항법·안전·팔·영상·진단 등 `/api/v1/*` 라우터를 등록한다. 예를 들어 `v1/robot.py`의 상태 조회는 `svc.state.snapshot()`을 사용한다.
- Fleet: `operations/fleet/fleet/server/app.py`가 `/api/fleet/*` 기능을 조립한다. `fleet/swarm/transport.py`, `navigation_transport.py`는 CORE 상태·정지·항법 API를 소비한다.
- World: `server/pose/map_pose_service.py`가 World projection을 사용하고 Fleet map-pose HTTP 표면을 제공한다. World 전체가 별도 HTTP 서버라는 뜻은 아니다.
- Decision·Execution: 내부 인터페이스와 Fleet의 Assistant·제안·승인·실행 경로를 사용한다. 앱이 내부 모듈을 직접 import하도록 바꾸지 않는다.

## 화면별 기능·API 대응

백엔드 경로는 `operations/fleet/fleet/server/`, 프런트 경로는 `applications/fleet/web/` 기준이다. API 열은 대표 요청이며 전체 endpoint 목록이 아니다. **소스 확인은 실행 가능성 확인과 구분한다.**

| 기능/화면 | 프런트 근거 | 대표 HTTP 표면 | 백엔드 근거 | 샘플·통합에서 확인할 조건 |
|---|---|---|---|---|
| 로그인·세션 | `login.html`, `shared/password-login.js` | `POST /api/fleet/auth/login`, `GET /api/fleet/auth/session` | `auth/password_routes.py` | 쿠키/토큰, 만료, 첫 비밀번호 변경, 로그인 비활성 상태 |
| 계정 관리 | `accounts.html`, `shared/account-page.js` | `GET/POST /api/fleet/auth/accounts`, 계정 PATCH·세션 폐기 | `auth/account_routes.py` | 실제 관리자 권한·Origin·revision·자기 잠금 방지 |
| 프로필 | `profile.html`, `shared/profile-page.js` | `GET/PATCH /api/fleet/auth/profile`, `auth/change-password` | `auth/password_routes.py` | 변경 충돌, 잘못된 비밀번호, 변경 후 세션 |
| 정책 | `work/policy.html`, `work/policy-page.js` | `GET /api/fleet/policy-governance/workcells`, `workcells/{id}/policy/*` | `missions/policy_governance_routes.py` | 정책 관리자·운영자 역할 차이, 제안/승인/lease·거절 |
| 관제 상태·로봇 | `index.html`, `console.js`, `roster.js` | `GET /api/fleet/state`, `robots/{id}/*` | `console/console_routes.py`, `ledger/task_dispatch_routes.py` | fresh/offline/stale, 로봇 capability·명령 거절 |
| 정지·취소·재개 | `console-refresh.js`, `confirmed-action.js` | `POST /api/fleet/estop`, `cancel-all`, `dispatch/rearm` | `ledger/task_dispatch_routes.py` | 확인·세대·권한, 접수와 실제 결과 구분 |
| 작업·운행 단계 | `work/work-view.js`, `roster.js` | `GET /api/fleet/work`, `tasks/{id}`, `trips/{id}/*` | `work/work_routes.py`, `ledger/task_dispatch_routes.py`, `trips/trip_routes.py` | 생성·진행·종료·보류·취소, 목록/상세/결과 일관성 |
| 제안·Mission·채널 | `work/channel-request-view.js`, `cell/cell.js` | `POST /api/fleet/proposals`, `missions/{id}/admit`, `channel-requests/{id}/*` | `missions/mission_routes.py`, `channel/missions.py` | 제안자·이름 있는 운영자, 중복 요청·승인 대기·거절 |
| Cell 문서·컴파일 | `cell/cell.html`, `cell/cell.js` | `/api/fleet/cell-app/documents`, `compile`, `proposals` | `cell/cell_app_routes.py` | compiler/service principal 설정, 미설정 503, 문서 digest 충돌 |
| Cell 진행·복구 | `cell/cell.js` | `/api/fleet/cell-jobs/{id}/reconcile`, `resume`, arm resume | `cell/cell_job_routes.py` | 보류·재승인·취소·다중 팔 결과, 실제 장치 증거와 표시 구분 |
| 지도·pose·경로 | `sitemap/site-map.html`, `map/map-polling.js` | `/api/fleet/site-map`, `site-lanes`, `robots/{id}/map-pose` | `sitemap/site_map_routes.py`, `pose/map_pose_service.py` | 맵 세대·보정·오래된 관측·좌표 일관성 |
| 설치·등록·발견 | `installation/install.html`, `devices/device-discovery.js` | `/api/fleet/discovery`, `enrollment/robots`, `hosts` | `recognition/ingest_routes.py`, `auth/enrollment_routes.py`, `host_control_routes.py` | 등록 미설정·후보/승인 구분·주소/역할 거절 |
| 카메라 pairing | `devices/camera-pairing.js`, `installation/camera-peer.js` | `/api/fleet/pairing/v1/*`, `/api/fleet/pairing/v2/*` | `auth/pairing_routes.py`, `app.py`의 camera-peer 설치 | v1/v2 위임 등록·TLS·만료·승인, 샘플은 장치 연결 안 함 |
| 추적·보정·teaching | `calibration/`, `sitemap/site-map-teach.js` | `/api/fleet/tracking`, `calibrations`, `teach/*`, `start-points` | `tracking/tracking_routes.py`, `sitemap/teach_routes.py`, `sitemap/start_point_routes.py` | 유효/무효 보정, 저장 충돌·센서 없음·진행/실패 |
| 대형·통행권·신호 | `formation.js`, `signals.js`, `map/traffic-view.js` | `/api/fleet/formation/*`, `traffic/*`, `signals/*` | `console/console_routes.py`, `trips/trip_routes.py`, `rightofway/signal_routes.py` | 운영 조건·waiting/hold·명령 거절·취소·TTL |
| 영상·Vision | `shared/vision-view.js`, `shared/robot-video.js` | `/api/fleet/vision/sources`, `vision/lease` 및 승인된 media 경로 | `tracking/vision_preview_routes.py`, `shared/web/webrtc.js` | lease·이미지·WebRTC 상태, 샘플 로컬 프레임·stale·불가 |
| 사건·알림 | `incident-view.js`, `inbox.js` | `/api/fleet/incidents`, facts review | `console/console_routes.py` | 정보 없음·사건 생성/처리·재조회·권한 거절 |
| Assistant·음성 | `assistant/panel.js`, `assistant/assistant-voice.js` | `/api/fleet/assistant/status`, `messages`, message/history 조회 | `assistant/routes.py`, `assistant/runtime.py` | 모델/저장소 미가동, 이름 있는 운영자·언어·취소·과거 세션; 브라우저 음성은 별도 어댑터 |

현재 HTML 진입점은 `index.html`, `login.html`, `accounts.html`, `profile.html`, `work/policy.html`, `installation/install.html`, `cell/cell.html`, `sitemap/site-map.html`이다. 조사는 이 Fleet 앱 범위다. Robot·Pilot·Face·Cam·Learning 전체 UI가 이 표로 완료된다는 뜻은 아니다.

## API 누락으로 단정하지 않은 항목

1. 본문에 고정 문자열로 선언된 Fleet 경로와 프런트의 문자열·template 호출 표현식을 조사했다. 상수 prefix·동적 경로·위임 라우터는 별도 추적해야 한다. 예를 들어 pairing은 BASE 상수를 사용하므로 단순 고정 문자열 집계에서 빠진다.
2. `cell_app_routes.py`는 미설정 기능을 503으로 거절하고 CORE navigation은 미지원 capability를 501로 거절한다. 라우트 존재만으로 기능 활성·장치 가동을 선언하지 않는다.
3. 순차 작업의 요청/진행/결과·revision·권한·오류 값은 method/path별로 아직 대조하지 않았다. 샘플 개발 전에 기존 API 모델·계약 시험과 대조한다. 빈 값이나 임의 성공으로 메우지 않는다.
4. 브라우저 음성·WebRTC는 HTTP 응답만으로 샘플화되지 않는다. 기존 `createVoice({platform})`, 앱 `createRobotVideo({open})` 주입 지점으로 분리한다. 실제 미디어는 승인된 grant의 별도 origin으로 연결되며, sample은 로컬 세션으로 이를 대체하고 connected는 기존 grant·TLS·`credentials: omit` 경계를 유지한다.

## 계약별 확정 형식과 완료 기준

실행 계획의 첫 단계에서 `applications/fleet/test/feature_matrix.json`을 만든다. 각 feature는 `id`, `entrypoints`, `consumers`, `availability`, `requests`, `flows`를 가진다. request는 HTTP method·path template·서버 구현 위치·계약 시험·관측할 성공/거절 상태를, flow는 단계·요청·화면 assertion·시나리오 ID를 가진다. API 응답 schema를 이 파일에 복사하지 않고 기존 모델/fixture를 참조한다.

- 현재 지원된 기능의 항목 누락 0, 참조한 화면/구현/시험의 존재 확인, 시나리오 없는 정상·거절·종료 흐름 0이 완료 기준이다.
- 확인되지 않은 method/path 또는 응답은 `unverified`로 남기며 완료 판정을 막는다. 구현 중 결정한 새 API는 소유 서비스와 live 계약에서 먼저 정의한다.
- sample과 connected가 같은 요청 계약 시험을 통과해야 한다. sample은 실제 인증·DB·장치 실행의 정확성 증거가 아니다.

이 문서의 확인 결과는 **주요 API 구현과 프런트 소비 경로 존재**까지다. 전체 API 충족, 샘플 기능 구현, 실제 연결·배포 완료는 주장하지 않는다.
