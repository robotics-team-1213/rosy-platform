## D-243 운용 화면은 hmi 에 두고 API 는 런타임에 둔다

**Status:** Accepted (2026-09-25).

잇는 결정: D-23(화면은 FastAPI 가 같은 프로세스에서 서빙), D-77(운용 콘솔은 `/dashboard` 하나),
[D-231](D-231-layered-source-roots-keep-package-names.md)(정적 화면을 hmi 로 떼는 일은 그때의 일이 아니었다).

**Context:**

1. 운용 콘솔의 HTML·JS·CSS 가 API 패키지 `core_api_web/web` 안에 있어서, 화면을 고칠 때도 백엔드 패키지를 연다.
2. 공용 토큰은 이미 `src/hmi/web` 이다. 얼굴 LCD 는 `src/hmi/face` 다.
3. Fleet 콘솔과 게임 보드, 센싱 진단 페이지는 그 서비스의 화면이다. 로봇 운용 콘솔과 한 폴더로 합치지 않는다.

**Decision:**

1. **운용 화면의 소스 자리는 `src/hmi/dashboard` 다.** 패키지 이름은 `dashboard` 다. 설치 경로는 `share/dashboard`.
2. **API 는 `src/runtime/api_web` 에 남는다.** 패키지 이름 `core_api_web` 은 유지한다. 프로세스가 바뀌지 않는다. 설치된 share 를 먼저 읽고, 없으면 소스 트리 `src/hmi/dashboard` 를 읽는다.
3. **사이트 화면과 센싱 진단 페이지는 각자의 패키지에 둔다.** `src/site/fleet/fleet/server/web`, `src/site/games/games/web`, `src/runtime/sensing/web`.

**Consequences:** 화면 파일만 바꾸는 변경은 `src/hmi/dashboard` 에서 끝난다. API 라우트 변경은 `src/runtime/api_web` 에서 끝난다.

**Validation:** `python -m pytest src/hmi/dashboard/test src/runtime/gateway/test/test_dashboard.py src/runtime/gateway/test/test_dashboard_no_bundler.py src/runtime/api_web/test/test_ui_route.py -q`.
