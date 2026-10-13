# D-755 협업 계정과 자료 가져오기 구현 계획

**Goal:** 검수 앱에서 개인별 로그인, 프로젝트 권한, 복수 HF 계정 연결과 고정 revision 가져오기를 사용할 수 있게 한다.
**Architecture:** 기존 ReviewStore와 Workspace를 유지한다. 선택적인 협업 설정으로 각 검수 workspace를 하나의 project에 고정하고, 공동 계정 DB는 여러 project의 membership·session·연결을 관리한다. 기존 단일 workspace 모드는 유지하며 협업 활성화 시 모든 자료/쓰기 요청에 신원·권한을 검사한다.
**Tech Stack:** Python stdlib SQLite/HTTP, 기존 cryptography, 기존 정적 web components. HF는 명시적 자격증명과 고정 endpoint를 사용한다.

## 작업과 소유 경로

1. `learning/curation/perception/learning_accounts.py`, `learning_oauth.py`, `test/learning/perception/test_learning_accounts.py`, `test_learning_oauth.py`: 이름 있는 사용자·프로젝트 ACL·세션, 암호화 연결 비밀, PKCE/OIDC 로그인과 명시적 연결. 구성은 private JSON; 공개 예제는 비밀 없는 template만. provider subject를 email과 분리한다.
2. `learning/curation/perception/learning_imports.py`, `test/learning/perception/test_learning_imports.py`: 읽기 전용 HF dataset/model import, immutable revision·파일 hash·권리 증거·부분 전송과 완성 등록·재시도·취소. 연결을 명시적으로 전달하고 자동 전역 로그인 fallback을 금지한다.
3. `contracts/learning/src/rosy/contracts/learning/media.py`, `test/test_learning_media_contracts.py`: 행동 없는 자료의 provenance/권리/용도 profile과 계보 검증. 기존 Episode v1·변환기 wire는 변경하지 않는다.
4. `review_app.py`, `review_app_web/accounts.html`, `accounts.js`, 기존 `learning.html`, `test/learning/perception/test_learning_collaboration.py`: 로그인/로그아웃, 현재 사용자·project·계정 선택, 연결/해제와 import/재시도/readback. 모든 기존 자료 route에도 ACL 적용. review payload의 reviewer는 인증된 사용자로 묶고 기존 version 충돌을 유지한다.
5. `learning/curation/perception/docs/review-app.md`, 배포 설정 template/요구사항, API reference와 schema 등록이 필요한 경계: 설정·키 보관·HTTPS callback·기존 state 백업/되돌림을 문서화한다. 사용자 입력 없이 provider 앱을 생성하거나 외부 게시하지 않는다.

## 검증 순서

- 각 비단순 동작은 실패 테스트를 먼저 커밋하고 canonical 원격 runner로 실패 원인을 확인한 뒤 구현한다. root가 공유 브랜치의 정확한 파일만 커밋하며 작업자끼리 index를 동시에 변경하지 않는다.
- `python tools/remote/remote_pytest.py --log-dir <X-session>/logs/<stage> -- <affected tests>` 뒤 `python test/known_failures.py <log>`를 실행한다. 노트북 pytest는 사용하지 않는다.
- 사용자 A/B, project A/B, 한 사용자의 두 HF 계정, 권한 취소/로그아웃/만료, 위조 callback/state·nonce·JWT, 동시 라벨 수정, 같은 revision 재시도와 부분 파일 미등록을 검증한다.
- 기존 review_app·review_masks·review_evidence·learning_workspace 회귀와 실제 격리 HTTP/browser 흐름을 확인한다. 실제 HF OAuth는 등록된 앱/HTTPS callback과 사용자 로그인 동의가 있어야 시험할 수 있다.
- lint와 독립 코드 검토 후 커밋·착지 결과, 외부 live 연결, 배포·학습 품질을 각각 보고한다. 실제 승인 정답이 없는 학습 수용은 보류한다.

## 구현 경계

- 프로젝트 membership는 명시적으로 부여한다. 계정 연결 자체는 프로젝트 가입/학습 승인/장치 실행 권한이 아니다.
- 기존 검수 state를 덮어쓰거나 계정을 email로 자동 합치지 않는다. 프로젝트 간 자료와 credential 접근을 차단한다.
- 게시·Space 실행·새 provider는 첫 HF 읽기 흐름의 수용 뒤 별도 구현한다. UI는 지원하지 않는 기능을 완료로 표시하지 않는다.
