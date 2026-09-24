## D-217 SEC-102의 CORS 문장을 좁힌다 — 로봇 API는 CORS를 제공하지 않는다

**Status:** Accepted (2026-09-25). SEC-102 문장 축소 적용함.

**Context:**

1. `docs/spec/ROSY CORE SRS.md:982`(SEC-102)는 "CORS 제어를 지원한다"고 적는다.
2. API Ref AUTH-103(`ROSY API & Protocol Reference.md:83-90`)는 "이 API는 CORS 헤더를 제공하지 않는다.
   소비자는 ① 로봇 로컬 대시보드(동일 출신 정적 자산), ② 서버 간 클라이언트, ③ 자기 출신 프록시 웹 앱만 해당한다"고 못 박는다.
3. 코드(`src/core/core_api_web` 전체 grep)에 `CORSMiddleware`가 없다. 동작하는 쪽은 API Ref다.

**Decision:**

1. SEC-102의 "CORS 제어를 지원한다"를 지우고 다음과 같이 좁힌다: "로봇 API는 CORS 헤더를 제공하지 않는다(AUTH-103).
   브라우저 직접 접속이 필요하면 호출자 출신의 리버스 프록시가 CORS를 처리한다."
2. HTTPS/WSS 리버스 프록시 옵션과 폐쇄 LAN HTTP 허용 문장은 그대로 둔다. 코드 변경 없음.

**Alternatives:** 지금 CORS를 구현하는 안 — AUTH-103 계약을 뒤집는 breaking 변경이고, 토큰을 쿼리·헤더에 싣는
API의 브라우저 직접 호출은 애초에 계약 밖이다. SRS를 그대로 두고 코드를 맞추지 않는 안 — 거짓 광고(D-32 위반)다.

**Consequences:** 브라우저에서 로봇 API를 직접 fetch하는 구성은 계속 계약 밖이다. 프록시가 필요한 소비자는
자기 출신에서 처리한다.

**Validation:** 문서 결정이다. 계약 시험에 CORS 관련 단언이 있으면 "미제공" 방향으로 고정한다.
