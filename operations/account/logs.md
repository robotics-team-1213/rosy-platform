# Account 변경 기록

## 2026-11-02 · uncommitted · 인증 계약의 실제 응답 증거 갱신

- 변경: 공통 Account로 이동한 13개 handler의 검증표 소유 경로를 바로잡고, 개발 세션 발급은 403 거절로 검증한다. Fleet 호환 import 검사는 기존 alias와 Account 모듈의 동일성을 명시적으로 확인한다.
- 증거: `e82b3cfc73` 소유·호환 import 원격 3 passed. `023d9915a3` 실제 HTTP 수집 9 passed, 인증 요청 15종의 응답·passing node 수집. 같은 SHA의 sample 로그인·거절·로그아웃과 Chromium 전송 흐름 2 passed, skip 0. 이 증거는 운영 사용자 로그인 수용을 대신하지 않는다.
- 경계: 운영 PC의 기존 인증서 호스트 매핑은 관리자 승인 뒤 기존 파일 바이트를 보존해 한 줄만 추가했다. 일반 이름 해석과 인증서 검증을 유지한 Python·Edge의 기존 Fleet health 응답 200을 확인했다. 계정 DB·서비스 전환은 아직 적용하지 않았다.
- CE: 검증표·호환 import 수정은 코드와 회귀 시험이 설명한다. 기존 로그인 화면 교훈 외의 새 교훈은 추가하지 않는다.
- gate 변화: SOURCE·LOCAL GO, ARTIFACT·FIELD HOLD. 이번 검증은 서명 설치나 운영 사용자 수용을 증명하지 않는다. ROS-SIM·DEVICE N/A.

## 2026-11-02 · uncommitted · D-962 독립 인증 소유 모듈

- 변경: 기존 계정·비밀번호·프로필·grant·세션·OAuth·감사를 독립 모듈로 이동했다. 활성 authority의 열 개 테이블·원자적 회수·계정 식별자를 보존하며 Fleet은 서명 자격을 검증하는 receiver가 된다.
- 증거: `da5aab6c09` 원격 Account/브라우저 279 passed, 공유 클라이언트·수신 66 passed, skip 0/NEW 0. `dd9d55404f` 모듈 소유 표식·크기·중복·독립 import 58 passed. 최종 설치와 실제 사용자 수용은 별도다.
- 경계: 서명 이미지 공유가 프로세스·원장·키 공유를 뜻하지 않는다. Account는 Fleet·ROS를 import하지 않는다. 복구 권한은 보존된 receiver 세션의 최신 서명·온라인 회수 상태를 요구한다.
- CE: 로그인 화면과 개발 모드의 결합 교훈은 공통 solutions에 기록했다. 추가 인증 로직은 코드·회귀 시험·D-962가 설명한다.
- gate 변화: SOURCE·LOCAL GO, 서명 설치 ARTIFACT·운영 수용 FIELD HOLD. ROS-SIM·DEVICE N/A.

## 2026-11-02 · uncommitted · 독립 배포 의존성과 통합 검사 보완

- 변경: Fleet은 `rosy-account==0.1.0`을 별도 배포 의존성으로 요구한다. CI wheel 목록·기존 Fleet 조건부 설치·이미지 시험 구성에 Account를 포함하고 Fleet 배포물의 중복 소유를 없앴다. API 이력 행과 추가 서비스의 로그 제한 검사도 보완했다.
- 증거: `8ec7d66580` API·공개 출처·로그 검사 24 passed. `3286f5528e` 실제 wheel·sdist·설치·CI 관련 24 passed와 기존 실패 네 항목의 격리 재실행 4 passed, isolation complete 4, skip 0/NEW 0. 같은 head의 독립 검토 지적 없음.
- 경계: 과거 공개 Actions pin은 독립 검토로 upstream commit API·태그를 확인한 정확한 과거 commit/path/rule 기록만 사용한다. 비밀 탐지 정책은 바꾸지 않는다. 런타임 인증·grant·장치 제어 계약은 그대로다.
- CE: 추가 패키징 판단은 의존성 선언·실제 설치 회귀 시험이 설명한다. 기존 로그인 화면 교훈 외의 새 교훈은 늘리지 않는다.
- gate 변화: 통합 FULL은 실패 수정 후 재실행 대기다. 서명 산출물 ARTIFACT·운영 수용 FIELD HOLD를 유지한다.

## 2026-11-02 · uncommitted · 사람 로그인 보완과 읽기 전용 기계 자격 보존

- 변경: 천장 marker 도구의 폐기된 Fleet 개발 로그인 옵션은 네트워크 전에 사람 로그인과 `ROSY_FLEET_TOKEN`을 안내하고 종료한다. 기존 상태 점검 viewer는 권한·토큰을 유지하고 `machine: true`인 token-only viewer만 receiver에서 명시적으로 보존한다. 기존 점검 계정 생성기도 같은 표식을 보존한다.
- 증거: `643c3b399c` 적색 뒤 `453d43267f` 원격 보정 도구 11 passed. `b2537af54b` 적색 세 항목 뒤 `8faa6099e1` loader·receiver·writer 126 passed. `ca93b3dddb` 점검 계정 생성기 35 passed. 모두 skip 0이며 실제 시험 API에서 상태·비전 조회 허용, 정지·작업 제안 거절과 사람의 이전 Bearer 거절을 확인했다.
- 경계: YAML·직접 구성·registry writer는 사람 로그인·비밀번호·정책 권한과의 결합 및 잘못된 marker를 거절한다. CORE의 별도 개발 인증과 보정 계산·동작은 그대로이며 실물 주행은 실행하지 않았다. 운영 계정 설정은 아직 적용하지 않았다.
- gate 변화: SOURCE·LOCAL GO, ARTIFACT·FIELD HOLD. 통합 FULL과 서명 설치·운영 수용은 별도 증거다. ROS-SIM·DEVICE N/A.
- CE: 경계 판단은 명시적 설정 계약과 회귀 시험이 설명한다. 기존 로그인 화면 교훈 외의 새 교훈은 늘리지 않는다.
