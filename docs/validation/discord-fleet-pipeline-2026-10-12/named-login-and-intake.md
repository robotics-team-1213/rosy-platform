# 기명 로그인과 Discord 접수 source 후속 증거

2026-10-12. 기존 result.md의 당시 미완료 항목에 대한 후속이며 과거 증거를 바꾸지 않는다.

## 실제 계정과 로그인

사용자가 별도 SSH 창의 sudo 및 Fleet 비밀번호 숨김 입력을 수행했다. 기존 machine principal을 보존하고 D-519 operator 계정 한 개를 추가했다. 기존 image digest·Compose 프로젝트·DB를 유지하며 실제 site.env의 connection mode만 development에서 paired로 변경하고 Fleet만 재시작했다. `/api/fleet/auth/connection`은 paired/password_login=true를 반환했다.

SSH로 읽은 public site CA와 로컬 복사본의 DER SHA256 일치를 확인하고 사용자 Windows CurrentUser Root에 설치했다. 기존 인증서 SAN에 맞춘 이름과 browser-session host rule로 접속했으며 TLS 검증을 끄지 않았다. 사용자가 HTTPS Console에 로그인한 뒤 같은 브라우저의 `/api/fleet/auth/session`이 HTTP200, 기명 operator, via=cookie를 반환했다. 개발 모드 표시가 사라졌다. 이후 screenshot 도구 timeout으로 자동화 browser context가 닫혔으므로 지속 로그인 세션을 주장하지 않는다. 비밀번호/hash/cookie/token은 공개 증거에 없다.

Bot의 서버 설치는 UI 성공과 채널 멤버 목록을 readback했다. webhook 연결 메시지 한 건 수신은 기존 승인 범위다. Bot token·Gateway 연결·Discord immutable user ID와 Fleet 계정의 운영 mapping은 아직 없다. 두 로봇은 offline이며 robot command/rearm/provider를 호출하지 않았다.

## D-671 접수 source

전용 HMAC·scope·현재 operator mapping → 기존 SQLite 접수 표 → 자기 요청 Console 조회를 구현했다. 순수 Discord adapter는 Fleet wheel/sdist/source image에 함께 들어간다. 접수는 status=REQUESTED이고 Task/Mission/Job/claim/모델 호출/장치 명령을 생성하지 않는다. 설정 없으면 접수 API는 열리지 않는다.

Remote RED commit `adbaad0e5`: 없는 수신 모듈 collection 실패1/NEW1. 첫 GREEN commit `65f1c00e3`은 manifest integration 종류 누락1/NEW1이며 기존 실패로 분류하지 않았다. 종류를 messaging으로 등록했다. 인증·수정/재전송·재시작·owner read·용량·설치·source image와 Console 안전 표시는 후속 원격 결과 및 독립 검토를 아래에 기록한다.

## 남은 수용

Gateway 실행기, Bot token 비공개 주입, 운영 immutable identity mapping, 실제 Discord 메시지 → Fleet receipt → 실제 Console 조회, 후보/승인/결과 reply는 미완료다. main 착지와 실제 image build/deploy·FIELD는 다른 증거다. D-669의 새 실행 권한 및 D-640 provider gate는 유지한다.

## 후속 원격·독립 검토

`066a19f8f`의 구조 NEW1은 Fleet 전체/조립 파일 증가였다. 기능 조립을 feature owner로 이동하고 기존 shared credential tuple을 재사용했다. 독립 검토가 일반 Goal/Cell Goal producer credential 중복 누락을 발견했고 양쪽 registry를 검사하는 회귀를 추가했다.

최신 통합 source commit `40b7937fa0`: AI PC 접수·기존 work owner read·manifest44 passed/NEW0/terminal0. Chromium은 처음 notebook 환경 변수가 전달되지 않아4 skipped였으며 이를 pass로 집계하지 않았다. 기존 remote runner의 선택·자원·committed shipping을 유지하고 시험 PC에서 opt-in을 설정한 `ac7a0bd59f` 실제 Chromium4 passed/NEW0/terminal0(320/1366 viewport, viewer/operator, 원문 XSS 미실행·권한 철회 삭제·overflow 검사)다. Console source는 이후 변경하지 않았다.

`safety_structure_review`는 `40b7937fa0` source/Safety를 승인했다. 실제 설치 holder를 포함한 Fleet53396, app.py906을 독립 재측정했다. 기존 +150 및 모든 file ceiling, full-progress/observe/server/UI 분리 의무는 유지한다. 과거 판정은 보존하고 새 설치 holder도 기존 크기/의존성 검사에 포함했다. 최종 착지는 최신 main 통합 원격 검증으로 별도 확인한다.
