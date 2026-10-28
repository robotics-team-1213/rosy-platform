<!-- Parent: ../AGENTS.md -->

# Fleet application

**Parent context:** `../AGENTS.md`

먼저 [README.md](README.md)에서 화면·gateway·플랫폼 서비스의 경계를 확인한다.

- 화면 소스는 `web/`, 실행 조합은 `gateway/`에서 고친다. 각각의 하위 `AGENTS.md`를 따른다.
- HTTP API·인증·원장·admission·dispatch는 `operations/fleet`에 남긴다. 별도 서버나 플랫폼 DB 직접 접근을 추가하지 않는다.
- 소스 holder를 바꿔도 `/console`, `/api/fleet/*`, `fleet.server.web`, `rosy-app-gateway`, `rosy-site-gateway` 신원을 유지한다.
- 시험·공유 체크아웃 절차는 [../../AGENTS.md](../../AGENTS.md)를 따른다.
