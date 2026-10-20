# Fleet 프런트 독립 개발 설계

상태: 검토용 설계. 구현·운영 계약 변경·병합 승인을 뜻하지 않는다.

## 목표와 완료 기준

공개 저장소 하나를 유지한다. 프런트 담당자는 Fleet 백엔드·ROS·장치·운영 DB 없이 앱을 실행하고, 현재 지원 기능의 화면과 대표 흐름을 개발·시험한다. 같은 화면을 개발용 Fleet에 연결할 수 있어야 한다. 운영 배포는 기존 Fleet 배포에 함께 포함한다.

사용자가 확인한 범위는 앱의 독립 실행·테스트, 샘플 데이터, 대표 흐름의 조작과 상태 전환이다. 조회용 목업만으로 완료하지 않는다. 백엔드의 인증·원장·admission·dispatch 책임은 유지한다.

완료 조건:

1. 샘플 실행은 Python 표준 라이브러리와 저장소 자산만으로 시작한다. Fleet 패키지·ROS·운영 DB 설치나 외부 연결을 요구하지 않는다.
2. 현재 Fleet 진입 화면 8개가 열리고, 각 기능군의 대표 흐름과 실패 상태를 검증한다. 기능과 시나리오의 대응 목록에서 빠진 기능은 완료로 세지 않는다.
3. 샘플과 연결 모드는 동일한 HTML·JS·공통 HTTP 클라이언트를 사용한다. 화면 코드에 샘플 전용 화면·업무 분기를 만들지 않는다.
4. 화면 자산을 추가할 때 앱의 자산 목록을 수정한다. Fleet 서버의 Python 자산 목록을 함께 수정할 필요가 없어야 한다.
5. 앱 브라우저 시험의 정적 자산 fixture는 Fleet 서버를 import하지 않는다. API·인증·원장과의 실제 통합 시험은 별도로 유지한다.
6. 기존 URL, wheel·import·CLI 신원과 운영 배포를 보존한다.

## 현재 구현과의 연결

기준: 로컬 main `45b2bfe064b739d425564d1bd0b3c06af314fa2f`.

| 현재 근거 | 바꿀 연결 |
|---|---|
| `applications/fleet/web/console.js`, `cell/cell.js`가 `/common/fleet-client.js`를 사용 | 화면의 HTTP 요청 경로·응답 처리 유지 |
| `shared/web/request.js`가 origin·자격 증명·취소·오류를 처리 | 샘플/연결 선택을 개발 HTTP 호스트 뒤에 두고 클라이언트 구현 재사용 |
| `operations/fleet/fleet/server/console/static_routes.py`의 `CONSOLE_ASSETS` | 앱 소유 자산 목록을 운영 서버와 개발 도구가 소비 |
| `test/console_browser_site.py`가 `fleet.server.static_routes`를 import | 앱 자산 목록과 공통 정적 fixture로 교체 |
| `fleet.cli.main → rosy_gateway.compose.main → fleet.cli._main_impl` | Fleet이 공개 실행 진입점을 소유하고 gateway가 그것을 사용 |
| `tools/packaging/fleet_sources.py`, Fleet `setup.py` | 화면과 자산 목록을 기존 Fleet wheel에 계속 포함 |

기존 결정은 [D-822](../adr/D-822-fleet-application-source-boundary.md)다. 이 문서는 작업 설계이며 기존 ADR·API reference를 대체하지 않는다. 구현 전에 CLI 조립 방향과 자산 소유 변경을 후속 ADR로 기록한다.

## 선택한 방식

앱 전용 개발 HTTP 호스트가 같은 브라우저 origin에서 화면·공통 자산·개발 API를 제공한다. 기존 vanilla ES module과 빌드 없는 화면 구성을 유지한다. 새 프런트 프레임워크나 Node 빌드 도구는 도입하지 않는다.

```text
동일한 Fleet 화면
  └─ 기존 Fleet HTTP 클라이언트
       └─ 앱 개발 HTTP 호스트
            ├─ sample: 샘플 상태와 시나리오 응답
            └─ connected: 지정한 개발 Fleet으로 HTTP 전달

운영: 기존 Fleet HTTP 서버 → 같은 화면·API·인증·원장·dispatch
```

폴더만 나누는 방식은 백엔드 없는 실행·시험 요구를 충족하지 못한다. 화면·API를 독립 제품으로 배포하는 방식은 이번 합의 범위를 넘는다. 개발 실행과 데이터 공급을 분리하고 운영 배포를 유지하는 방식을 선택한다.

## 소유 위치

아래는 제안 경로다. 실제 명령과 실행 안내는 구현 후 앱 README 한 곳에 기록한다.

| 위치 | 책임 |
|---|---|
| `applications/fleet/web/` | 기존 화면 구현, `assets.json`의 페이지·정적 자산 매핑 |
| `applications/fleet/dev/` | 개발 HTTP 호스트, sample/connected 데이터 공급, 실행 인자 |
| `applications/fleet/dev/sample/` | 예시 데이터·시나리오·샘플 상태 전환 |
| `applications/fleet/test/` | 앱 자산·샘플 시나리오·프런트 동작 시험과 기능 대응 목록 |
| `applications/fleet/gateway/` | 공개 Fleet 진입점과 공정 인터페이스를 사용하는 앱 실행 조립 |
| `shared/web/` | 기존 공통 UI·HTTP 요청·응답 처리. Fleet 앱의 샘플 상태는 두지 않음 |
| `operations/fleet/` | 운영 HTTP 서버·인증·원장·admission·dispatch·백엔드 시험 |

앱 테스트는 프런트 표시·입력·요청·오류 처리를 소유한다. Fleet 테스트는 실제 인증·저장·승인·실행 불변식을 소유한다. 기존 시험을 파일 위치만 보고 일괄 이동하지 않고 이 책임으로 분류한다. CI selector·browser scope·module harness도 새 시험 위치를 인식하게 한다.

## 화면과 API의 인터페이스

화면은 기존 HTTP 경로를 호출한다. 개발 데이터 공급은 method/path, 요청 body, status, 응답 envelope, revision·request key와 권한 거절을 현재 API 계약과 맞춘다. 입력 형식은 기존 API reference·모델·fixture를 우선 재사용하고 앱 안에 운영 계약의 두 번째 정의를 만들지 않는다.

`assets.json`은 공개 페이지 URL과 기존 `/console/assets/<name>` 별칭에 대응하는 상대 경로·media type을 보유한다. 기존 `/common/` 자산 목록은 `shared/web/shared-assets.json`을 계속 따른다. Fleet 운영 서버와 앱 개발 호스트가 이 목록을 읽는다. 경로 이탈·미등록 자산 거절과 운영 CSP·응답 헤더는 보존한다. 목록 파일도 wheel·sdist·사이트 이미지에 포함한다.

개발 HTTP 호스트는 기본 loopback에 바인딩한다. sample은 기본 모드이고 upstream을 만들거나 접속하지 않는다. connected는 모드와 개발 Fleet 주소를 명시해야 하며, 요청·오류·인증 실패를 실제 서버의 의미대로 전달한다. API·이미지 등 현재 프런트가 쓰는 HTTP 응답을 전달하고, 지원되지 않은 전달 형태를 성공으로 바꾸지 않는다. 연결 오류 때 샘플 응답으로 자동 전환하지 않는다.

### 연결 모드의 인증과 origin

Fleet은 `auth/password_session.py`에서 Origin과 Host를 비교하고 `auth/password_routes.py`에서 Secure·HttpOnly 세션 쿠키를 발급한다. 개발 프록시는 이 검사를 끄지 않는다.

- connected의 브라우저 진입점은 HTTPS loopback origin으로 고정한다. 인증서·키는 기존 개발 인증서 절차로 마련한 private 파일을 명시하며, 자격 증명을 쓰는 연결 모드에 HTTP 예외나 TLS 검증 생략을 두지 않는다. 샘플 실행에는 이 설정이 필요하지 않다.
- 개발 호스트가 먼저 요청 Host를 설정된 로컬 authority와 비교한다. Origin이 있으면 정확한 로컬 origin이어야 하고, 변경 요청은 Origin이 없거나 다른 origin이면 upstream에 보내기 전에 거절한다. localhost라는 이유로 임의 포트·Host·Origin을 허용하지 않는다.
- 로컬 검사를 통과한 요청만 지정된 단일 Fleet origin으로 전달한다. upstream Host는 그 authority로 설정하고, 검증된 로컬 Origin이 있던 경우만 upstream origin으로 매핑한다. 클라이언트가 보낸 Forwarded·X-Forwarded-*와 hop-by-hop 헤더는 제거하며 사용자·역할을 새로 부여하지 않는다.
- Authorization과 Fleet 세션 쿠키는 요청 시점의 값만 지정된 upstream으로 전달한다. upstream의 host-only `rosy_fleet_session` 쿠키는 이름·값·Path·Secure·HttpOnly·SameSite·만료/삭제 속성을 보존해 로컬 HTTPS origin에서 사용한다. Domain이 있는 예상 밖 쿠키는 거절한다. 다른 origin으로 redirect를 따라가며 자격 증명을 전달하지 않는다.
- sample은 실제 Fleet 쿠키를 읽거나 전달하지 않는다. HTTP loopback에서 샘플 로그인 상태가 필요하면 별도 `rosy_sample_session` 쿠키를 사용한다. 이는 샘플 UI 상태용이며 실제 인증·Secure 쿠키 동작의 검증 증거가 아니다. sample과 connected는 서로 다른 origin/포트를 사용한다.
- 연결 시험은 로그인→세션 확인→인증된 변경→로그아웃→이전 세션 거절을 검사한다. 외부 Origin·잘못된 Host·Origin 없는 변경·조작된 전달 헤더·예상 밖 Domain 쿠키·upstream TLS 오류가 upstream 호출이나 인증 우회로 이어지지 않는지도 검사한다. 실제 인증·CSRF 계약의 기준은 기존 Fleet 구현과 시험이다.

## 샘플 데이터와 대표 흐름

단순한 URL별 고정 JSON 대신 하나의 시나리오 상태를 사용한다. 예를 들어 작업 생성 응답의 ID가 목록·상세·승인·진행·결과 조회에 일관되게 나타나야 한다. 시간·ID·진행은 결정적으로 제어하며, 시나리오 초기화로 같은 상태를 다시 만든다. 샘플 상태는 개발 프로세스 메모리에만 존재한다.

샘플은 화면이 소비하는 계약을 흉내 낸다. Fleet 원장·admission·로봇 실행 엔진을 복제하거나 import하지 않는다. 운영 알고리즘의 정확성·실제 승인·장치 작업 완료를 샘플로 증명하지 않는다.

| 현재 기능군 | 지원할 대표 시나리오 |
|---|---|
| 로그인·세션·계정·프로필 | 역할별 접속, 로그아웃·만료, 조회/조작 권한 거절, 계정·프로필 변경 표시 |
| 관제·로봇·지도·통신 | 정상/오프라인/오래된 상태, 지도·목표 표시, 요청 접수·진행·거절·중지 표시 |
| 작업·Mission·채널 요청·대기열 | 생성→승인 대기→승인→진행→결과, 취소·보류·복구, 중복 요청·revision 충돌 |
| Cell 문서·공정 | 문서 편집·저장·검증 오류→컴파일 미리보기→제안→승인·진행·결과 표시 |
| 사이트 맵·설치·장치·카메라 | 등록 후보·승인·연결 상태, 보정/저장 성공·충돌·실패, 영상 예시·소스 없음 |
| 정책·dispatch·알림·사건 | 권한별 변경·거절, 정지/재개 표시, 경고·사건 조회와 처리 결과 |
| Assistant·음성 관련 화면 | 예시 대화·도구 제안·실패·취소, 음성 기능의 준비/처리/불가 표시. 실제 모델·마이크 입력은 요구하지 않음 |

구현의 첫 단계에서 현재 8개 진입 화면, 화면 동작, 호출 API, 기능 설정을 대조해 `applications/fleet/test/`의 대응 목록을 확정한다. 각 항목은 화면 진입점·시나리오 ID·시험·지원 조건을 가진다. 표의 기능군에 묶였다는 이유만으로 하위 기능의 대응을 생략하지 않는다. 실제로 비활성인 기능은 샘플에서도 그 조건을 표시하고 활성/비활성 상태를 따로 시험한다.

정상 상태와 오류 시나리오를 모두 선택할 수 있어야 한다. 미등록 요청은 method/path를 포함한 개발 오류로 실패하고 실제 네트워크로 전달하지 않는다. 미지원 기능에 빈 목록이나 무조건 성공을 돌려 완료처럼 보이게 하지 않는다.

각 샘플 페이지는 샘플 데이터 사용을 표시한다. 작업·정지·승인 버튼은 샘플 상태만 바꾼다. 외부 데이터·실제 자격 증명·운영 장치 설정을 샘플에 복사하지 않는다. 모드를 바꾸면 페이지를 새로 열고 샘플 접속 상태·대기 요청을 재사용하지 않는다.

## 브라우저 음성·영상 의존성

HTTP 응답만 바꿔도 브라우저의 음성 설치·인식, WebRTC 연결은 남는다. 현재 `assistant/assistant-voice.js`의 `createVoice`는 `platform`을 받고, 앱 `shared/robot-video.js`의 `createRobotVideo`는 `open`을 받는다. 이 주입 지점을 사용해 샘플에서 실제 마이크·음성 팩 다운로드·외부 미디어 연결 없이 준비/입력/취소와 영상 준비/오래됨/불가 상태를 재현한다. 공유 WebRTC 내부의 `Peer`까지 가짜로 구현하지 않고 앱의 카메라 세션 인터페이스를 대체한다.

앱의 작은 runtime provider가 브라우저 어댑터를 제공한다. 운영과 connected는 native provider, sample은 개발 호스트가 명시적으로 선택한 sample provider를 제공한다. HTML과 화면 업무 코드는 같고, 차이는 이 의존성 공급 지점에 한정한다. 전역 브라우저 API를 덮어쓰거나 화면마다 sample 분기를 추가하지 않는다. 운영 패키지는 native provider만 제공하며 샘플 구현을 포함하지 않는다.

## gateway와 배포

Fleet CLI는 gateway 설치 여부에 따라 앱 코드를 다시 호출하지 않는다. Fleet이 공개 실행 함수를 제공하고, `fleet` 명령과 `rosy-site-gateway` 명령이 각자의 진입점에서 이를 사용하도록 정리한다. `_main_impl` 직접 import는 제거하되 기존 인자·종료·인터럽트 처리와 기존 설치 조합을 보존한다.

운영 화면은 계속 Fleet wheel에 포함된다. 운영 서버가 앱 자산 목록을 제공하며 기존 `/console`, `/api/fleet/*`, 설치된 `fleet.server.web`과 CLI 신원을 유지한다. 개발 호스트·샘플 상태·시나리오는 운영 실행에 포함하지 않는다. 별도 프런트 배포와 다른 도메인 인증 설계는 실제 독립 배포 요구가 생길 때 진행한다.

## 검증과 구현 순서

1. 현재 기능·API·시험의 대응 목록과 후속 ADR을 정리한다.
2. 앱 자산 목록과 정적 제공을 분리한다. 운영 자산·페이지·CSP·경로 거절, wheel/sdist/이미지 입력과 기존 브라우저 fixture를 검증한다.
3. gateway의 공개 실행 인터페이스를 정리하고 기존 설치·CLI·한 번만 실행되는 조립 동작을 검증한다.
4. sample/connected 개발 호스트와 시나리오 상태를 구현한다. 모든 진입 화면과 대표 기능 흐름·오류·초기화를 앱 테스트로 검증한다.
5. 프런트 시험과 실제 백엔드 통합 시험을 분류하고 selector·browser scope·CI·앱 README를 연결한다.

샘플의 HTTP status·응답 형식은 실제 계약과 대조한다. 브라우저 시험은 샘플의 상태 전환과 화면 결과를 함께 검증하고, 예상하지 않은 API 요청·외부 네트워크 요청이 하나라도 발생하면 실패한다. connected 전달은 가짜 upstream으로 인증·오류·취소·이미지 응답을 검사한 뒤 개발 Fleet 통합을 별도 증거로 기록한다.

pytest·Chromium 실행은 [공유 체크아웃 절차](../reference/shared-checkout.md)의 원격 시험 경로를 따른다. 노트북에서 개발 화면을 여는 것과 자동 시험을 실행하는 것은 구분한다. 샘플 시험·실제 Fleet 통합·사이트 이미지·장치 수용의 결과를 각각 기록하며 서로 대신하지 않는다.

설계 검토가 끝나면 각 단계의 소유 파일·커밋 범위·필수 검증을 담은 실행 계획을 작성한다. 그 전에는 이 문서를 구현 지시나 운영 계약 변경으로 취급하지 않는다.
