<!-- Parent: ../AGENTS.md -->

# Applications

**Parent context:** `../AGENTS.md`

제품 앱은 `applications/<product>/`에서 개발한다. Fleet의 현재 경계와 실행 방법은 [fleet/README.md](fleet/README.md)를 먼저 읽는다.

- 앱 화면과 앱 실행 조합만 이곳에 둔다. 플랫폼 API·원장·admission·dispatch는 기존 소유 모듈에서 바꾼다.
- 화면은 소유 서비스의 HTTP API를 사용한다. 앱에 별도 실행 권한이나 플랫폼 DB 직접 접근을 추가하지 않는다.
- 경로를 옮기면 패키징, manifest, CI/배포 입력, 테스트와 browser scope를 같은 변경에서 갱신한다. 최상위 개발·검증 절차는 [../AGENTS.md](../AGENTS.md)를 따른다.

구조 결정: [D-822](../docs/adr/D-822-fleet-application-source-boundary.md).
