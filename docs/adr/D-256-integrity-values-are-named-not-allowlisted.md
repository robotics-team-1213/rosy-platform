## D-256 공개 무결성 값은 이름으로 지우고, 스캐너는 매처를 넓히지 않는다

**Status:** Accepted (2026-09-26).

잇는 결정: [D-175](D-175-debug-log-system-outside-core.md)(모든 층이 같은 redaction
모듈을 지난다), [D-212](D-212-artifact-native-path.md)(이미지에 비밀이 없는 것은
`secret_scan`으로 검증한다).

**Context:**

1. `deploy/release/secret_scan.py` 하나가 저장소 검사(추적 파일)와 이미지 검사 두 게이트의
   같은 매처를 돌린다. 그래서 한 줄의 이름이 어긋나기만 해도 릴리스 게이트가 멈춘다.
2. 2026-09-25 전수 시험에서 apt 소스의 공개 SHA-256이 `pin`이라는 이름의 대입으로 걸려
   릴리스 게이트가 레드가 됐다. 값은 이미지와 똑같이 공개돼 있는 무결성 데이터였다.
3. 값 배제는 이미 두 번 값을 치렀다. `KNOWN_FIXTURES`에 PEM 헤더 리터럴을 올렸을 때 그
   헤더는 저장소 전체의 개인키 매처를 무장 해제시켰고(스캐너 코드 주석의 기록), 스캐너 자신도
   파일 단위 제외를 자기 파일 이름 하나로만 받는다 — 파일을 빼면 비밀을 숨기기 가장 좋은
   자리가 되기 때문이다.

**Decision:**

1. **무결성 값은 값의 이름으로 지운다.** 체크섬·다이제스트·고정 리비전이 담긴 줄에 무결성
   목적의 이름이 있으면(`sha256`, `sha512`, `digest`, `revision`, `checksum`, `commit`,
   `oid`, `fingerprint`) 고엔트로피 토큰 매처는 그 줄을 건너뛴다. 이름이 곧 근거다.
   `hash`는 의도적으로 목록에 없다 — 산문에 흔해 넣으면 그 줄의 매처를 통째로 끄는 틈이 된다.
2. **매처는 한 사례를 위해 넓히지 않는다.** 값 단위 허용목록을 새로 만들지 않는다. 제외는
   구조적 판단(플레이스홀더·코드 참조·무결성 맥락)으로만 둔다. 매칭을 끄는 가장 빠른 길은
   넓히기이고, 그 소리는 아무도 듣지 않는다.
3. **오탐은 호출 지점에서 고친다.** 공개 값을 담은 테스트·설정은 이름을 그 값의 본분으로
   바꾼다(`pin` → `apt_source_sha256`). 스캐너 본문은 그대로다.

**Consequences:** 새 공개 체크섬은 무결성 이름을 달아야 한다. 반대로 이름에 무결성 단어를
붙인다고 사실의 비밀이 풀리는 것은 아니다 — 같은 줄의 `api_token`은 여전히 `credential`로
돈다. 이 문장은 프로브 3건(무결성 맥락 없는 hex → `high-entropy-token`, 무결성 이름 → 침묵,
`api_token`에 `sha256` 병기 → `credential`)으로 확인했다.

**Validation:** `python -m pytest test/test_release_boundary_guards.py test/test_native_payload_workflow.py -q`.
