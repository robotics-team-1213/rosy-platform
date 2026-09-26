## D-226 문서는 공개 여부를 먼저 가르고, 그다음 주인 폴더에 둔다

**Status:** Accepted (2026-09-25). 이동은 9a83470e에서 했다. 경계는 `test/test_document_placement.py`가 CI에서 지킨다.

**Context:** 저장소 `livsbittt/rosy-os`는 공개(PUBLIC)다. D-17은 계약 문서
구조를, D-45는 `docs/`를 단일 기준 경로로, D-186 §4는 "모듈 설명은 그 모듈의
`docs/`, 저장소 결정과 계획은 `docs/adr`·`docs/plans`"를 정했다. 세 결정이
다루지 않는 경계가 남았다.

- 공개 여부. 내부 초안과 실제 장치 주소를 둘 곳이 없었다. 2026-09-25에
  `.gitignore`의 `/private/`가 생겼지만(c8c5c6ac) 무엇이 거기 가는지는 정하지
  않았다. `docs/validation/pinky-pro-evaluation-2026-09-24.md`에는 실제 장치의
  사설 IP가 이미 공개 이력에 있다.
- 날짜가 박힌 검증 증거. `docs/validation/`에 246개가 있는데
  `src/core/control/docs/validation/`에도 날짜가 붙은 결과 네 건이 있다.
- 모듈 안 깊은 곳의 문서 묶음. `map/map_260905_update_v2/`는 `docs/`,
  `reports/`, `review/`, `CHANGELOG.md`를 자기 안에 가진다.
- 모듈 루트의 낱장 문서. `control/STEPS.txt`, `imu_bno055/INITIALIZATION.md`.

모으기 작업은 이 기준이 Accepted 된 뒤에 한다.

**Decision:** 문서 하나마다 아래 순서로 묻고, 처음 걸리는 답을 따른다.

1. **공개해도 되는가.** 하나라도 해당하면 `private/`에 둔다. git에 들어가지 않는다.
   - 실제 장치의 주소·계정·비밀번호·토큰, 현장 Wi-Fi 이름
   - 사람·고객·현장을 식별하는 정보
   - 재배포 권리가 확인되지 않은 벤더 자료나 업로드 원본
   - 공개 전 사업·전략 초안

   `private/`에서 `docs/`로 올릴 때는 위 항목을 지우거나 `<robot-ip>` 같은
   자리표시로 바꾼다. 이미 공개 이력에 있는 것은 되돌릴 수 없으므로, 이 규칙은
   새로 쓰는 문서와 이후 수정분부터 적용한다.
2. **코드나 시험이 읽는가.** 읽으면 문서가 아니라 데이터다. 읽는 쪽 옆에 그대로
   둔다. 시험 fixture, 맵이 쓰는 텍스처, 시험이 인용하는 `reports/*.json`이 여기에 든다.
3. **저장소 전체의 결정·계약·계획인가.** `docs/adr`, `docs/spec`,
   `docs/reference`, `docs/plans`에 둔다(D-17, D-186 §4).
4. **날짜가 박힌 측정 증거인가.** 그날 실행한 결과, 캡처, 측정 JSON은
   `docs/validation/<주제>-<YYYY-MM-DD>/`에 둔다. 모듈 안에 두지 않는다.
   증거는 그날의 기록이라 코드와 함께 고쳐지지 않는다. 모듈 안에 있으면
   설치물과 섞이고 찾기도 어렵다. 결과 양식(template)은 증거가 아니므로 5로 간다.
5. **모듈을 쓰거나 고치는 법인가.** 코드와 함께 바뀌는 설명은 그 모듈 루트의
   `docs/` 하나에 둔다. 모듈 루트에 남는 문서는 `README.md`, `AGENTS.md`,
   `CLAUDE.md`, 하네스 기록(`progress.md`, `logs.md`, `index.md`)뿐이다.
6. **출처가 따로 있는 자산 묶음인가.** 맵처럼 한 번에 받아 한 단위로 갱신하는
   묶음은 `README.md`, `CHANGELOG.md`, `SOURCES.md`, 묶음 전용 `docs/`와
   `reports/`까지 묶음 안에 둔다. 출처와 갱신 이력이 자산과 함께 움직여야 하기
   때문이다. 묶음 밖에서도 쓰는 설명은 5를 따른다.

저장소 루트의 문서는 `README.md`, `AGENTS.md`, `LICENSE`, 하네스가 생성하는
`STATUS.md`, ce-compound가 관리하는 `CONCEPTS.md`만 둔다.

**옮기는 규칙:**

- 경로를 참조하는 살아 있는 문서와 시험(README, AGENTS, `progress.md`, spec,
  reference, test)은 같은 변경에서 고친다(D-186 §6).
- 기록 문서(`logs.md`, 날짜가 붙은 `docs/plans/*`, ADR 본문, 인벤토리 CSV)
  안의 옛 경로는 그날의 사실이므로 고치지 않는다.
- Accepted ADR이 이름으로 가리키는 진입 파일은 그 ADR이 대체될 때까지 옮기지 않는다.
- 증거 폴더는 날짜 이름을 그대로 유지한 채 `git mv`로 옮긴다. 이력을 끊지 않는다.
- `src/` 아래 폴더 이동(refactor/multi-robot-structure, D-196 예약)과 겹치는
  경로는 그 이동이 끝난 뒤에 옮긴다.

**현재 목록에 적용한 결과** (2026-09-25):

| 경로 | 기준 | 판정 |
|---|---|---|
| `private/ROSY_Architecture_v0.4_Research_Enhanced.md` | 1 | `private/`에 둔다. 올리려면 검토와 결정이 필요하다 |
| `src/core/control/docs/validation/` 날짜 폴더 3개와 날짜 문서 1개 | 4, 2 | 옮겼다(9a83470e). 결과 세 건은 `docs/validation/`으로 갔다. `mapping-finish-2026-09-08`은 `test_straight_escape.py`가 읽는 데이터라서 `src/core/control/test/fixtures/`로 갔다 |
| `src/core/control/docs/*.md` 3개 | 5 | 유지 |
| `src/core/control/STEPS.txt` | 옮기는 규칙 | 유지. D-50이 이름으로 가리키는 runbook이다 |
| `src/core/control/CLAUDE.md` | 5 | 유지 |
| `map/map_260905_update_v2/` 전체 | 2, 6 | 유지. `reports/wall_geometry.json`은 `pinky_integrated_acceptance.launch.py`가 설치 경로에서 읽는 데이터다 |
| `map/*/review/*.png`, `textures/` | 2, 6 | 유지 |
| `src/devices/imu_bno055/INITIALIZATION.md` | 5 | `src/devices/imu_bno055/docs/`로 옮겼다(9a83470e) |
| `CONCEPTS.md`, `STATUS.md` | 루트 규칙 | 유지 |
| `docs/validation/pinky-pro-evaluation-2026-09-24.md`의 장치 IP | 1 | `<robot-ip>`로 바꿨다. 옛 값은 공개 이력에 남는다 |

**gitignore로 막는 것과 추적하는 것:** 기준 1을 파일 이름으로 옮긴 표다. 왼쪽은
`.gitignore`가 막고, 오른쪽은 반드시 추적한다. 두 칸은 같은 곳에 나란히 있어서
규칙이 넓어지면 템플릿이 함께 사라진다. 그래서 두 칸을 모두 시험한다.

| 막는 것 (git에 들어가지 않는다) | 추적하는 것 (공개해도 되는 짝) |
|---|---|
| `/private/` 내부 초안·전략·벤더 자료·현장 메모 | `docs/` 공개 문서 |
| `.env`, `.env.*`, `*.local.env`, `match.local.yaml` | `.env.example`, `deploy/robot/native/rosy-runtime.env` 비밀 없는 템플릿 |
| `provision.json`, `rosy-config.yaml` 채운 장치 설정 | `provision.schema.json`, `rosy-config.template.yaml` |
| `*.key`, `*.p12`, `*.pfx`, `id_rsa*`, `id_ecdsa*`, `id_ed25519*` | `deploy/release/public-keys/*.pem` 공개키 |
| `rosy-diag-*.tar.gz` 로봇에서 가져온 진단 번들 | `deploy/robot/native/rosy-diag` 수집 스크립트 |
| `*.img*`, `*.iso`, `*.mcap`, `*.db3`, `rosbag2_*/`, `*.sqlite3`, `*.db` | 이미지를 만드는 절차(`deploy/image/`) |
| `data/teleop/*`, `data/drive/**` 세션 기록 | `data/teleop/learning/` 학습용 영상 |
| 빌드·캐시·에이전트 상태, `.worktrees/`, `.claude/worktrees/` | `.claude/settings.json`, `.omc/skills/` |

새 비밀 종류가 생기면 왼쪽 칸과 `test/test_document_placement.py`의 `MUST_IGNORE`에,
그 템플릿은 오른쪽 칸과 `MUST_TRACK`에 같은 변경에서 더한다.

**Alternatives:**
- 모든 문서를 `docs/`로 모으기. D-186 §4를 뒤집고, 코드와 함께 바뀌는 설명을
  코드에서 떼어 놓게 된다.
- 증거도 모듈에 두기. `docs/validation/`과 두 곳이 되어 날짜별 기록을 한 번에 찾을 수 없다.
- 내부 자료를 비공개 두 번째 저장소에 두기. 사람 한 명이 쓰는 지금은 관리 비용만 든다.
  공동 작업자가 생기면 다시 검토한다.

**Consequences:**
- 새 문서는 위 순서로 자리를 정한다.
- 공개 여부 판정이 첫 질문이 된다. 장치 실측 문서는 주소를 자리표시로 적는다.
- 옮긴 것은 control 날짜 결과, 시험이 읽는 맵 데이터, imu 낱장 문서다. 모두 9a83470e 한 커밋이다.

**Validation:** `test/test_document_placement.py`. CI(`ci.yml`의 `pytest test/`)가 push와 PR마다 돌린다.
- 추적 파일 중 ignore 규칙에 걸리는 것이 없다(`git ls-files -ci`). 강제로 올린 비밀과, 템플릿까지 삼키는 규칙을 둘 다 잡는다.
- `MUST_IGNORE`의 경로는 전부 ignore되고, `MUST_TRACK`은 전부 추적되며 ignore되지 않는다.
- 저장소 루트에는 허용 목록 밖의 파일이 없다.
- `src/**/docs/validation/` 아래에 날짜가 박힌 항목이 없다. 결과 양식은 예외다.
- 모듈 루트에는 허용 목록 밖의 `.md`/`.txt`가 없다. D-50 runbook `STEPS.txt`는 명시한 예외다.

변이 확인: `.gitignore`에서 `provision.json` 줄을 지우면 시험이 `deploy/sd/provision.json`을 들고 실패했다.

`python tools/harness/rosy_harness.py lint`와 `git diff --check`를 통과시킨다.

**References:** [D-17](D-17-3-2.md), [D-45](D-45-.md), [D-186](D-186-script-and-capture-folder-layout.md), [D-50](D-50-active-rosy-control-guides-use-rosy-os-device-procedures.md).
