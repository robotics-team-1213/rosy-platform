# Fleet 기명 계정 준비 검증

사용자에게 기존 Console 로그인 ID가 없어 D-519 Accepted 계정 계약을 현장 관리 도구에 적용했다. Discord 사용자 연결·Bot 권한·장치 writer는 변경하지 않았다.

- SOURCE: `deploy/site/site_users.py`의 `add-login --password-hash-stdin`, 로그인·토큰 혼합 문서 검사, 현재 AI observer 보존, 비밀번호 hash 출력 제거. 기존 Fleet hash 생성 명령을 사용한다.
- 회귀: 잘못된 hash·중복 principal/login·기계 로그인 거절, dry-run 및 기존 계정 보존, 실제 Fleet loader/password verification/session, 원자 교체 전 Fleet 소유권·권한 설정과 실패 시 원본 보존.
- RED: 새 명령 미구현 1 NEW, 소유권 게시 순서 2 NEW를 각각 원격에서 확인했다. 기존 실패로 등록하지 않았다.
- GREEN: 계정 CLI·loader·session 77 passed/NEW 0. 소유권 수정 후 계정·harness 시험도 exit 0/NEW 0.
- 독립 읽기 전용 검토: 게시 전 권한 문제를 수정한 `cc345ea9a2` 소스 승인. 회귀 소유권은 syscall을 모의하며 실제 root 설치 수용을 대신하지 않는다.
- LAND: `tools/land.py --tests auto` 1 round, 최신 main 통합 commit `e9e6b17f64`. AI PC 722 passed/2 skipped/NEW 0, lint 0 errors. land record와 main SHA를 직접 readback했다. 동료의 미커밋 파일을 보존했다.

실제 현장에는 토큰 기반 사용자만 있으며 기명 비밀번호 로그인은 없었다. 실행 이미지에서 D-519 loader/session 모듈이 존재하고 설정이 read-only mount됨을 확인했다. `sudo -n`은 본인 인증을 요구해 실제 파일 게시·계정 생성·재시작·HTTPS 로그인은 하지 않았다. 기존 운영자 token을 Discord Bot에 넘기지 않았다.

실제 운영 수용은 **HOLD**다. 숨김 비밀번호 입력과 현장 관리자 인증을 받은 뒤 백업·dry-run·파일 소유권·설정 검사·재시작·HTTPS 세션 principal을 순서대로 확인한다. 이 계정 도구의 소스 병합은 D-669 대화 intake·Bot 연결·provider 활성화·로봇 주행 수용이 아니다. 이번 작업은 push하지 않았다.
