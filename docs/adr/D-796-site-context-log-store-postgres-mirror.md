## D-796 사이트 문맥·로그 저장소(Postgres 미러)

**Status:** Accepted (2026-10-18, SOURCE; 런타임·현장 수용은 별도). 사용자 결정: 미러 대상은 D-640 숙고 저널, 편집 뒤 리뷰 요청(커밋 없음). D-750(원장은 SQLite 하나), D-197(Docker는 제품 체인 밖, 사이트 Compose는 현재 사이트 스택), D-333(SQLite WAL 유지)을 좁게 예외 처리한다. D-427/D-429/D-430과의 관계는 아래 표다.

### Context

로깅은 세 층이다. (A) 런타임 진단은 로컬 파일·journald로 끝낸다. (B) 영속 원장·감사는 Fleet `fleet.sqlite3`(SQLite)와 JSONL이다. (C) 거버넌스 저널은 ADR·`logs.md`(markdown/git)다. Fleet 원장은 SQLite 하나라는 것이 D-750이고, SRS `DAT-001`의 PostgreSQL은 목표로만 남아 있었다.

결합 실측은 원장 이전이 위험함을 보인다. store 모듈 40여 개가 각각 `sqlite3.connect()`를 직접 호출하고, `BEGIN IMMEDIATE`가 100곳을 넘으며, `PRAGMA table_info/user_version/database_list`, `Connection.backup`, row-value range, partial index를 쓴다. 계약시험이 pragma 값 자체를 단언한다(`test_mission_store.py`, `test_proposal_store.py`, `test_policy_evidence_store.py`, `test_sighting_store.py`). 사이트 관제 PC의 Compose는 `fleet`/`vision`/`proxy` 세 서비스뿐이었다.

사이트 호스트에 파생 문맥/로그를 모아 두자는 요청이 있었다. 원장을 옮기지 않고 그 요청을 받을 방법이 필요했다.

### Decision

1. **원장은 그대로 SQLite 하나다.** `fleet.sqlite3`의 트랜잭션·admission·WAL 정책(D-333)은 바뀌지 않는다. PostgreSQL은 파생 문맥/로그 전용이며 진실의 원천이 아니다.
2. **미러 대상은 D-640 숙고 저널의 터미널 run뿐이다.** `operations/fleet/fleet/server/ledger/context_log.py`의 `ContextLog`(import 이름은 평탄한 `fleet.server.context_log`)가 `rosy_deliberation_run`(SCHEMA_VERSION 1, unique key `(subject_id, case_id, generation)`, `ON CONFLICT DO NOTHING`)에 기록한다. `DeliberationJournal.run`은 SQLite 커밋 뒤에만 `_mirror`를 부르고, `ContextLog`는 어떤 실패도 경고로만 남기고 `False`를 돌려주며 절대 예외를 올리지 않는다. Postgres가 없거나 죽어도 Fleet 결정·원장 트랜잭션은 영향을 받지 않는다.
3. **배치는 관제 PC 한 곳뿐이다.** Postgres는 Compose 네 번째 서비스이고 `site_backend`(internal)에만 붙으며 포트를 공개하지 않는다. Fleet만 TCP(`postgres:5432`)로 접속한다. 비밀번호는 Docker secret `postgres_password` → `POSTGRES_PASSWORD_FILE` → psycopg `password_file` 경로로만 읽는다. 로봇·AI PC·모델 PC는 DB에 직접 접속하지 않는다(Fleet HTTPS/WSS 경로만). 각 PC 로컬 SQLite/JSONL은 남긴다.
4. **서명 candidate에 미러 이미지를 포함한다.** `build_candidate.py`가 `MIRRORED_IMAGES = {"postgres": "postgres:16-alpine"}`를 빌드 시 `docker pull`/`tag`하고 해석된 image ID를 서명 manifest에 `source: "mirror"`·`upstream`과 함께 기록한다. `verify_candidate.py`가 그 서명·digest·SBOM을 검증하고, 업데이터 `SERVICES`(`site_update_io.py`)에 `postgres`를 넣어 compose-config 대조·health gate·런타임 드리프트 검사가 네 이미지를 모두 본다. 미러 이미지에는 별도 Dockerfile이 없다.
5. **최소 의존만 더한다.** `psycopg[binary]==3.2.3` 하나다. SQLAlchemy·Alembic·연결 풀 프레임워크는 쓰지 않는다.
6. **이미지 경화는 fleet/vision보다 약함을 명시한다.** 재고 upstream 이미지라 `read_only: true` + tmpfs(`/tmp`, `/run`, `/var/run/postgresql`), `cap_drop: [ALL]` + 최소 `cap_add`, `no-new-privileges`, 전용 volume `pg_data`, healthcheck `pg_isready`만 쓴다.
7. **연결 배선은 ledger 홀더가 들고 콘솔 플래그가 그 sink를 활성화한다(D-766).** sink와 그 CLI 표면은 소스 홀더 `operations/fleet/fleet/server/ledger/`(등록 유닛)의 `context_log.py`(`ContextLog`), `context_options.py`(`--context-db-*` 정의 `add_cli_arguments` + `activate_from_args`), `deliberation_journal.py`에 있다(셋 다 import 이름은 평탄한 `fleet.server.*`). `cli.py`는 홀더를 한 줄씩만 부르고, 활성화된 sink는 프로세스 전역(`set_active`/`active`)으로 두어 `DeliberationJournal`이 기본값으로 집는다. `app.state` handoff는 두지 않는다 — `cli.py`·`app.py`는 D-766 동결 파일이라 늘릴 수 없고, 배선이 어차피 유일한 소비자(저널) 옆에 있는 편이 낫다.

### D-427·D-429·D-430과의 관계

| 결정 | 관계 |
|---|---|
| D-427 (parts) | 폴더 소유는 바뀌지 않는다. 미러 sink와 그 CLI 표면은 `operations/fleet/fleet/server/ledger/`(기존 서버 홀더, D-750) 안에 둔다 |
| D-429 (device local rules) | 무관하다. 장치 로컬 판단·Safety는 건드리지 않는다 |
| D-430 (safety anchors) | safety 태그 경로를 바꾸지 않는다. `Safety-Review:` trailer 불필요 |

### 일부러 하지 않는 것

- 원장 이전·공유 DB PC·다중 호스트 DB는 하지 않는다.
- mDNS 새 서비스 종류를 만들지 않는다(`site-lan-discovery-profile.md`의 종류만 남는다). LAN 밖은 D-477 tailnet MagicDNS다.
- 로봇·AI PC·모델 PC의 직접 접속을 만들지 않는다.
- D-640 활성화는 하지 않는다. sink가 붙는 seam은 지금은 **dormant**하다 — `--context-db-*`가 준 sink를 활성화해 두면, `DeliberationJournal`이 실제로 만들어지는 순간부터 미러가 함께 켜진다.

### 열린 항목

- `DeliberationJournal`(D-640)은 현재 프로덕션 생성처가 없다(테스트만 쓴다). 따라서 sink가 붙은 seam은 런타임 행을 아직 만들지 않는다. 활성 경로인 D-720 채널 모델 저널로 옮길지는 사용자 확인이 필요하다.
- 모듈 **소스 위치**만 `server/ledger/`로 옮겼다(D-766 크기 유닛). import 신원은 소스트리·설치본 모두 평탄한 `fleet.server.deliberation_journal`, `fleet.server.context_log`, `fleet.server.context_options` 그대로다(홀더는 빌드 때 `fleet.server.*`로 평탄화된다). 그래서 이 세 모듈과 그 호출자는 홀더를 거치는 이름(`fleet.server.ledger.*`)을 쓰지 않는다 — 설치본에는 그 이름이 없다. 설치 모듈 목록 시험(`test_remaining_platform_installed.py`)이 세 평탄 이름을 고정한다.
- Docker가 없는 개발 노트북에서는 pull·digest 해석을 확인할 수 없다. digest는 CI 빌드 시 확정·기록된다.
- pytest는 이 노트북에서 돌리지 않는다(D-584). 원격 PC 없이는 계약시험을 확인할 수 없다.

### Consequences

- 원장·admission·WAL 정책은 그대로다. Postgres 장애·부재 시에도 Fleet 결정은 바뀌지 않는다.
- Postgres는 사이트 호스트에서 네 번째로 경화 자세가 가장 약한 서비스다(문서화). 그래서 internal 네트워크에만 둔다.
- 업데이터가 네 이미지를 모두 대상으로 한다: compose-config 대조, health gate, 드리프트 검사, prune 정규식이 `postgres`를 포함한다.
- Compose에 서비스·volume·secret이 하나씩 늘어난다(`pg_data`, `postgres_password`).

### Validation

- `test/test_site_candidate.py`, `test/test_site_candidate_signing.py`, `test/test_site_candidate_verifier.py`, `test/test_site_autoupdate.py`, `test/test_site_functional_setup.py`, `operations/fleet/test/test_context_log.py`, `operations/fleet/test/test_deliberation_journal.py`.
- 원격 pytest·Docker 빌드·장치/현장 수용은 **NOT RUN**이다.

**References:** D-750, D-640, D-720, D-437, D-301, D-441, D-427, D-429, D-430, D-197, D-333, D-516, D-477, D-584, D-510.
