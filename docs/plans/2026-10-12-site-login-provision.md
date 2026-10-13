# Fleet 기명 로그인 계정 준비

기존 D-519 Accepted 계약을 현장 계정 관리 도구에도 적용한다. Discord 대화 권한을 새로 만드는 작업은 아니다. 사용자에게 기존 Console ID가 없으며, 실제 현장에는 토큰 사용자만 있다. 계정 도구의 토큰 전용 검사로는 로그인 사용자와 현재 AI observer를 보존하며 계정을 추가할 수 없었다.

1. 기존 `deploy/site/site_users.py`에 `add-login --password-hash-stdin`을 추가한다. 해시 생성은 기존 Fleet 명령을 사용하며 평문 비밀번호 생성·저장 기능은 추가하지 않는다.
2. D-519 로그인·토큰 혼합 문서와 D-577 `ai_observer` 토큰을 검사한다. 기존 principal·login 충돌은 거절하고 기계 계정의 사람 로그인을 금지한다. 기존 계정 변경·암호 초기화·Discord 사용자 자동 연결은 하지 않는다.
3. 기존 CLI 회귀와 실제 Fleet loader·비밀번호 검증·세션 시험을 원격에서 실행하고 NEW와 비교한다. 독립 검토와 최신 main 통합 후 로컬 FF한다.
4. 실제 적용은 운영자 ID·숨김 비밀번호 입력, 비공개 백업, dry-run, 원자적 파일/소유권 검사, Fleet 재시작 후 HTTPS 로그인·세션 principal readback으로 확인한다. 비밀번호를 대화로 받지 않는다. 미완료 단계를 SOURCE 통과로 대신하지 않는다.
5. Discord의 불변 사용자 ID와 Fleet principal 연결은 D-669 후속이다. 이 도구는 Bot bearer나 실행 경로를 만들지 않는다. 로봇 오프라인과 provider/FIELD HOLD를 유지한다.

영향 범위는 계정 CLI·같은 도구를 호출하는 설정 검사·운영 문서·관련 시험이다. Fleet 로그인 API·DTO·DB·장치 writer·배포 이미지의 소스 구성은 변경하지 않는다. 현장 watcher는 저장소 밖에 있으므로 계정 적용 전에 실제 검사 호출과 재시작 경로를 별도로 확인한다.

검증: 원격 RED에서 새 명령 미구현으로 1 NEW를 확인했다. GREEN에서 계정 CLI·Fleet loader·세션 77건이 통과했고 NEW 0이다. 실제 계정 생성·비밀번호 입력·HTTPS 로그인·Bot 연결은 별도 증거다.
