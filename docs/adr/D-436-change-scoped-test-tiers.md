## D-436 호스트 시험은 변경 범위로 고른다 — 반복과 PR CI는 affected 티어, 공용 기반·미분류 변경과 main·야간·릴리스는 풀

**Status:** Accepted (2026-10-03, 사용자 요청; 저장소 도구·CI·작업 규칙만). D-346의 2티어(푸시 시점 패스트 게이트 / 풀 게이트)를 대체하지 않고, 그 사이에 변경 범위 티어를 넣는다. 게이트 정의(ROS-SIM…FIELD)와 장치·현장 수용 기준은 바꾸지 않는다. 호스트 pytest 녹색은 여전히 장치·ARM64 이미지·현장 수용이 아니다.

### Context

- 호스트 시험은 약 8400건이고, 이 Windows 개발 PC에서 한 번 도는 데 40~60분, 두 브랜치가 병행하면 그보다 길다. 에이전트와 CI는 변경 내용과 무관하게 매번 전체를 돌렸다 — `tools/ssh`와 문서만 바꾼 브랜치도 마찬가지다.
- 2026-10-03 D-418(로봇 SSH 접근) 병합은 풀 실행에 약 1시간을 썼다. 그런데 병합으로 생긴 실패는 전부 상시 검사 묶음(비밀 스캔 `test_release_boundary_guards`, `architecture/test_module_structure`, harness 계약, 프로토콜 버전 핀, 로봇 리터럴, `platform_parts`)에서 나왔다. 그 묶음은 수십 초짜리다. 비용의 대부분은 변경과 닿지 않는 스위트였다.
- 변경을 모듈로 되짚을 재료는 이미 있다: `tools/harness/harness.yaml`(모듈 `path`·`tests`), `platform_parts.yaml`(root별 `import_prefix`), `platform_dependencies.yaml`, D-346 pre-push 패스트 게이트, CI의 단계별 스위트.
- 같은 기본 이름을 가진 시험 파일(gateway·sensing의 `test_battery.py`, games·vision의 `test_preview.py`)은 한 pytest 호출에 넣으면 수집 단계에서 충돌한다. 지금까지는 사람이 호출을 나눠 적었다.

### Decision

1. **affected 티어(로컬 에이전트 반복, PR CI).** `python tools/harness/rosy_harness.py affected [--base main]`이 `git diff --name-only --no-renames base...HEAD`와 작업 트리 변경(스테이지·비스테이지·추적 안 된 파일)을 합쳐 다음을 고른다.
   - 바뀐 파일이 속한 harness 모듈(가장 긴 `path` 접두)의 `tests`.
   - 그 모듈의 직접 역의존: 출하 코드(시험 파일 제외)가 `platform_parts.yaml`의 `import_prefix`를 import하는 다른 모듈의 `tests`와, 그 접두를 import하는 시험 파일. 한 단계만 본다 — `control`이나 `core_features`에서 전이 폐포를 따라가면 거의 전체 트리가 되어(2026-10-03 측정: sensing 파일 하나가 시험 파일 약 70개·디렉터리 8개를 끌어옴) 티어를 둘 이유가 사라진다. 더 깊은 경로는 main push 풀 실행이 그물이다.
   - 바뀐 경로를 직접 가리키는 시험 파일(저장소 경로 문자열, 저장소에서 유일한 파일 이름, 시험 보조 모듈의 import, 또는 경로 성분 — 파일 이름과 부모 디렉터리 이름이 둘 다 독립 토큰으로 나타나는 경우. 계약 시험은 `ROOT / "deploy" / "robot" / "pinky_pro" / "compose.yaml"`처럼 경로를 성분으로 만든다). 문서 계약 시험(`test_line_follow_contract_docs`, `test_task_contract_docs` 등)은 이 규칙으로 따라온다.
   - 바뀐 파일이 시험 파일이면 그 파일만(모듈 전체나 역의존을 끌어오지 않는다).
   - 모듈 `tests`가 루트 `test/` 전체인 경우(`deploy`)는 너무 넓어서, 그 파일을 가리키는 시험이 있을 때만 그 시험과 모듈 `functional`로 좁힌다. 가리키는 시험이 없으면 `test/` 전체를 돈다(좁힐 근거가 없다).
   - 항상 도는 상시 검사 묶음: `test/test_release_boundary_guards.py`(비밀 스캔), `test/architecture/test_module_structure.py`, `test/test_harness_contracts.py`, `src/runtime/gateway/test/test_protocol_version_alignment.py`(버전 핀·프로토콜 정렬), `test/test_robot_literals.py`, `test/architecture/test_platform_parts.py`.
   - 출력은 pytest 호출 목록이고, 기본 이름이 겹치는 경로는 별도 호출로 나눈다(AGENTS.md 규칙의 자동화). 각 스위트가 **왜** 골라졌는지와 풀로 올라간 이유를 함께 찍는다.
2. **풀로 올리는 조건(escalation).** 다음 중 하나라도 맞으면 affected를 버리고 풀 티어를 낸다.
   - 공용 기반: `src/contracts/foundation/**`(`core_common`), `src/contracts/interfaces/**`, `tools/harness/**`(harness 설정·선택기 자체), 어디에 있든 `conftest.py`, `pyproject.toml`·`setup.py`·`setup.cfg`·`pytest.ini`·`tox.ini`, `*requirements*.txt`, `.github/workflows/**`, 그리고 시험이 경로 상수로만 닿는 배포 매니페스트 — `deploy/**/compose*.yaml`과 `deploy/robot/*/{image,native}/`의 `.service`·`.timer`·`.path`·`.target`·`.conf`·`.env`·`.txt`·`.json`·`.yaml`·`.list`(2026-10-04 리뷰: compose 시험 28개 중 16개는 `DEPLOY / "compose.yaml"`, `staged / "runtime/compose.yaml"`처럼 상수를 거쳐 어떤 경로 일치로도 찾을 수 없었다).
   - 풀로 올라간 파일도 아래 매핑은 그대로 한다. 로컬에서 FULL 선택을 `--run`하면 그 매핑(소유 모듈·직접 역의존·참조 시험)과 상시 묶음이 돌기 때문이다 — 그래야 `core_common` 변경이 상시 묶음만, 선택기 변경이 자기 시험 없이 끝나지 않는다.
   - **미분류는 풀이다.** 바뀐 파일이 어떤 모듈·import root에도 속하지 않고, 그것을 가리키는 시험도 없으면 풀로 올린다(모르면 전부, 절대 아무것도 안 함이 아니다). 예외는 Markdown 노트 하나다: 모듈 밖의 `*.md`(AGENTS.md·README 등)는 직접 참조 시험이 있으면 그것을, 없으면 상시 묶음만 돈다.
   - base ref를 못 찾거나 git diff가 실패하면 풀이다.
3. **문서만 바뀐 경우.** `docs/` 변경은 `docs` 모듈 시험(`test_network_topology_contracts`, `test_harness_contracts`)과 그 문서를 직접 읽는 계약 시험, 상시 묶음을 돈다. ADR 문서는 harness lint와 `test_harness_contracts`(ADR 인덱스·본문 정합)가 이미 상시 묶음에 있으므로 따로 늘리지 않는다 — ADR을 직접 읽는 시험(`test_module_scorecard`가 D-178을 읽는 식)은 참조 규칙으로 따라온다.
4. **풀 티어는 GitHub Actions 러너에서만 돈다(2026-10-03 사용자 추가 요구).** 로컬 PC는 빠른 반복을 위한 affected 티어와 pre-push 패스트 게이트만 돈다. 풀 스위트는 기본적으로 로컬에서 돌지 않는다 — `affected --run`이 FULL 선택을 받으면 상시 묶음과 바뀐 파일에서 매핑된 스위트(소유 모듈·직접 역의존·참조 시험)만 돌고 "풀은 GitHub"라고 알린다(`--full`로만 강제). 풀은 GitHub 러너에서 돈다: main push(머지 큐 포함), PR(선택기가 FULL로 올린 경우), 야간 schedule, `workflow_dispatch`, 릴리스 빌드 전. 페이로드 빌드는 이미 GitHub ARM64 러너에서 돈다(`build-native-payload.yml`).
   - **병렬 matrix.** `ci.yml`은 `scope` 잡(전체 이력 체크아웃, D-430 Safety-Review, 선택기)이 matrix를 내고 `test` 잡이 항목마다 러너 하나로 병렬 실행한다. 풀 matrix(`affected_tests.py`의 `CI_FULL_MATRIX`)는 core-domain(gateway·events·services·web_common·foundation·profiles), sensing(gateway와 `test_battery.py` 기본 이름이 겹쳐 별도 러너; CI에서 처음 도는 스위트라 첫 녹색까지 비게이팅), fleet, site-vision-cell(vision·cell·palletizing을 별도 호출로), gz-sim, hardware-safety, 루트 `test/` 3분할(정렬된 파일 목록 라운드로빈), build-smoke(colcon 빌드·flake8·부팅 스모크·SaveMap 가드)다. affected matrix는 선택된 pytest 호출마다 항목 하나 + build-smoke다.
   - **셋업.** 항목마다 컨테이너·apt·pip(약 70초)와 플랫폼 wheel(약 7초)을 반복하고, colcon 빌드(약 20초)는 오버레이가 필요한 항목(`ros: overlay` — 루트 test/, gz-sim, affected)과 build-smoke만 한다. 산출물 전달이나 캐시는 두지 않는다 — 2026-10-03 녹색 실행(37127100807)에서 colcon 빌드는 17초로, artifact 업·다운로드보다 짧다.
   - **예상 벽시계 시간.** 오늘의 직렬 잡은 약 10분 10초(셋업 약 1.5분 + 시험 약 8.5분, 그중 루트 `test/` 4분 29초, core-domain 1분 55초)다. 병렬에서는 scope 약 1분 + 가장 긴 항목(셋업 약 1.5분 + 루트 test/ 3분할 하나 약 1.5~2분 또는 core-domain 약 2분) ≈ 5분 안팎이다. 러너 사용 분은 셋업 반복만큼 는다(항목 10개 × 약 1.5분).
   - **결과 읽기.** 에이전트는 로컬에서 풀을 다시 돌리지 않고 GitHub 결과를 기다려 읽는다: `gh run list --branch <branch> -L 3`, `gh run watch <run-id> --exit-status`, 실패만 `gh run view <run-id> --log-failed`, 잡 이름은 `gh run view <run-id> --json jobs --jq '.jobs[] | select(.conclusion=="failure") | .name'`. 실패한 항목의 pytest 호출만 로컬에서 재현한다. push하지 않은 로컬 main에는 CI 증거가 없다.
5. **pre-push.** D-346 패스트 게이트의 내용은 그대로 두고, 그 뒤에 affected 티어를 덧붙인다(`origin/main` 기준, `--run`). 풀로 올라간 경우에도 훅은 상시 묶음과 바뀐 파일에서 매핑된 스위트만 돌린다 — 풀은 GitHub 러너가 맡는다. 패스트 게이트가 이미 돈 파일(상시 묶음 대부분)은 `--skip`으로 빼서 두 번 돌지 않는다.
6. **브랜치 보호용 집계 잡.** matrix 잡 이름은 선택에 따라 바뀌므로, `ci-result` 잡(`needs: [scope, test]`, `if: always()`)이 `scope`와 모든 게이팅 항목의 성공을 확인한다. 취소·건너뜀은 실패다. 보호 규칙은 `ci-result` 하나를 가리킨다.

### Alternatives

- **계속 매번 풀:** 40~60분, 병행 시 더 길다. 실패 대부분이 수십 초짜리 묶음에서 나는데 그 비용을 모든 변경에 물린다. 기각.
- **pytest-testmon 같은 커버리지 기반 선택:** 실행 기록 데이터베이스를 브랜치·CI·Windows/Linux 사이에서 맞춰야 하고, 문서·YAML·셸을 읽는 계약 시험(이 저장소 시험의 큰 몫)을 커버리지로 잡지 못한다. 기각.
- **사람이 고르는 시험 목록:** 이미 AGENTS.md에 있었고 낡았다(`src/devices/omx/adapter` 같은 옛 경로). 기각.
- **풀을 로컬에서 기본 실행:** 이 PC에서 40~60분, 병행 브랜치가 있으면 더 길고 CI 러너와 결과가 갈린다(Windows 경로·wheel 부재 — 2026-10-03 dogfood에서 `src/site/cell/test`가 `rosy.processes` wheel 부재로 수집 실패). 기각.
- **CI 직렬 유지:** 한 잡이 10분을 넘게 잡고, 실패 하나를 보려면 끝까지 기다린다. 병렬 matrix가 답이다. 채택.
- **미분류 파일은 상시 묶음만:** 빠르지만 새 디렉터리의 변경이 시험 없이 지나간다. 이 ADR은 반대로 정한다 — 미분류는 풀.

### Consequences

- `tools/ssh`만 바뀐 브랜치는 상시 묶음과 SSH 도구 시험만 돈다. `core_common`이나 harness 설정을 건드리면 지금과 같이 전부 돈다.
- 선택기의 정확도는 harness 등록(`harness.yaml`)과 `platform_parts.yaml`의 `import_prefix` 정확도에 묶인다. 등록 누락은 미분류 → 풀로 드러나므로 조용한 누락이 아니라 느린 실행으로 보인다.
- 역의존은 정적 import만 본다. 웹 정적 파일·YAML 설정 같은 비 Python 결합은 직접 참조 규칙과 main push 풀 실행이 마지막 그물이다. main 풀 실행에서 affected가 놓친 실패가 나오면 선택 규칙을 고치고 그 사례를 선택기 시험 표에 더한다.

**References:** [D-346 커밋 시점 충돌 방어](D-346-commit-time-collision-defenses.md), [D-61 progress-logs-index](D-61-progress-logs-index.md), [D-427](D-427-platform-three-parts-middleware-operations-learning.md), [D-430](D-430-safety-as-a-separate-concern.md), `tools/harness/affected_tests.py`, `test/test_affected_tests.py`.
