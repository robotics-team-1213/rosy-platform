# 기본 내 프로필 구현 계획

범위는 [D-689](../adr/D-689-fleet-self-profile.md)와 사용자의 기본 프로필 선택이다. 기존 전체 UI/계정 목표를 잇는다.

1. 서버: 기존 PasswordSessions/SQLite에 본인 표시 이름 조회·수정과 일반 비밀번호 변경의 현재 비밀번호 검증을 연결한다. 계정/권한/이메일 원본은 수정하지 않는다. 현재 인증/CSRF·세션 회전·source-binding·자원 제한을 보존한다.
2. 화면: 네 업무 문서 우상단 계정 메뉴 → 내 계정 → 읽기 전용 계정 정보/이름 수정/현재 비밀번호 확인 변경 → 실제 결과 재조회. Map/Cell 새 탭과 기존 초안 보존, 로그인·강제 변경 복귀를 잇는다. 새 CSS/JS도 기존 공용 컨트롤/토큰을 쓴다.
3. 계약/검증: API reference additive 버전/핀, 정적 allowlist, wheel/sdist closure, UI/권한/실패 복구 회귀를 같은 변경에 포함한다. 적정 원격 테스트와 독립 명세/품질 검토 후 기존 main 착지·push·서명·배포 gate를 수행한다.
4. 발급: 강제 변경과 프로필을 제공하는 설치 SHA를 확인한 뒤 팀원 네 명만 사람 로그인으로 발급한다. 서비스 자격은 보존하고 실제 계정 읽기/초기 제한을 확인한다. 당사자의 최종 비밀번호 변경과 실물 수용을 대신 수행하거나 완료로 추정하지 않는다.

## Fleet 크기 재판정

83c2a49fd의 P6 실제 집계는 Fleet parent 54,074줄이다. 공유 main c90833b2a는 53,408줄, D-683/D-686 계정 진입·인증·초안 복구는 385줄, D-689 기본 프로필은 281줄 증가다. 시험 코드는 이 집계에서 제외된다. 직전 D-678 판정 53,366줄과의 차이는 708줄이므로 기존 +150 allowance로는 착지할 수 없다.

기존 observe/server/UI 분리 의무를 유지한다. 사람 폼과 프로필은 기존 Console의 별도 shared 모듈/문서, 정적 자산은 기존 Fleet 설치 경로, 인증·프로필 저장은 기존 PasswordSessions와 SQLite에 둔다. CORE/운행/AI 권한 소유자는 늘리지 않았다. 새 SIZE_UNITS나 파일 예산을 추가하지 않고 package +150도 유지한다. password_session.py는 실제 549줄이다. 인증 endpoint가 다음에 늘어 이 파일의 600줄 경계에 닿으면 HTTP 설치 함수를 같은 server의 password_routes.py로 분리하고 저장·검증은 PasswordSessions에 남긴다. 이는 현재 서비스나 권한을 추가하는 계획이 아니다.

learning_ui가 실제 production/web diff의 666줄 증가와 소유권을 독립 확인하고 54,074줄 기준점을 승인했다. SIZE_VERDICTS만 이 기준으로 갱신하며 allowance·파일 한도는 늘리지 않는다. 최신 main 병합과 최종 영향 검사는 별도다.
