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
   - 그 모듈의 역의존: `platform_parts.yaml`의 `import_prefix`를 import하는 다른 모듈(전이 폐포)의 `tests`와, 그 접두를 import하는 시험 파일.
   - 바뀐 경로를 직접 가리키는 시험 파일(저장소 경로 문자열, 저장소에서 유일한 파일 이름, 시험 보조 모듈의 import). 문서 계약 시험(`test_line_follow_contract_docs`, `test_task_contract_docs` 등)은 이 규칙으로 따라온다.
   - 바뀐 파일이 시험 파일이면 그 파일만(모듈 전체나 역의존을 끌어오지 않는다).
   - 모듈 `tests`가 루트 `test/` 전체인 경우(`deploy`)는 너무 넓어서 그 모듈의 `functional`과 위의 직접 참조 시험으로 좁힌다. 둘 다 비면 `test/` 전체로 돌아간다.
   - 항상 도는 상시 검사 묶음: `test/test_release_boundary_guards.py`(비밀 스캔), `test/architecture/test_module_structure.py`, `test/test_harness_contracts.py`, `src/runtime/gateway/test/test_protocol_version_alignment.py`(버전 핀·프로토콜 정렬), `test/test_robot_literals.py`, `test/architecture/test_platform_parts.py`.
   - 출력은 pytest 호출 목록이고, 기본 이름이 겹치는 경로는 별도 호출로 나눈다(AGENTS.md 규칙의 자동화). 각 스위트가 **왜** 골라졌는지와 풀로 올라간 이유를 함께 찍는다.
2. **풀로 올리는 조건(escalation).** 다음 중 하나라도 맞으면 affected를 버리고 풀 티어를 낸다.
   - 공용 기반: `src/contracts/foundation/**`(`core_common`), `src/contracts/interfaces/**`, `tools/harness/**`(harness 설정·선택기 자체), 어디에 있든 `conftest.py`, `pyproject.toml`·`setup.py`·`setup.cfg`·`pytest.ini`·`tox.ini`, `*requirements*.txt`, `.github/workflows/**`.
   - **미분류는 풀이다.** 바뀐 파일이 어떤 모듈·import root에도 속하지 않고, 그것을 가리키는 시험도 없으면 풀로 올린다(모르면 전부, 절대 아무것도 안 함이 아니다). 예외는 Markdown 노트 하나다: 모듈 밖의 `*.md`(AGENTS.md·README 등)는 직접 참조 시험이 있으면 그것을, 없으면 상시 묶음만 돈다.
   - base ref를 못 찾거나 git diff가 실패하면 풀이다.
3. **문서만 바뀐 경우.** `docs/` 변경은 `docs` 모듈 시험(`test_network_topology_contracts`, `test_harness_contracts`)과 그 문서를 직접 읽는 계약 시험, 상시 묶음을 돈다. ADR 문서는 harness lint와 `test_harness_contracts`(ADR 인덱스·본문 정합)가 이미 상시 묶음에 있으므로 따로 늘리지 않는다 — ADR을 직접 읽는 시험(`test_module_scorecard`가 D-178을 읽는 식)은 참조 규칙으로 따라온다.
4. **풀 티어는 그대로 남는다.** main push(머지 큐 포함), 야간 schedule, `workflow_dispatch`, 릴리스 빌드 직전에는 지금의 전체 스위트를 돈다. PR CI는 affected 티어를 돌고, 선택기가 풀을 내면 PR에서도 전체 단계를 돈다. colcon 빌드·부팅 스모크·SaveMap 가드·Safety-Review 트레일러 검사는 티어와 무관하게 남는다.
5. **pre-push.** D-346 패스트 게이트의 내용은 그대로 두고, 그 뒤에 affected 티어를 덧붙인다(`origin/main` 기준). 풀로 올라간 경우 훅은 풀을 돌리지 않고 경고만 남긴다 — 풀은 CI의 main push와 릴리스 전 게이트가 맡는다.

### Alternatives

- **계속 매번 풀:** 40~60분, 병행 시 더 길다. 실패 대부분이 수십 초짜리 묶음에서 나는데 그 비용을 모든 변경에 물린다. 기각.
- **pytest-testmon 같은 커버리지 기반 선택:** 실행 기록 데이터베이스를 브랜치·CI·Windows/Linux 사이에서 맞춰야 하고, 문서·YAML·셸을 읽는 계약 시험(이 저장소 시험의 큰 몫)을 커버리지로 잡지 못한다. 기각.
- **사람이 고르는 시험 목록:** 이미 AGENTS.md에 있었고 낡았다(`src/devices/omx/adapter` 같은 옛 경로). 기각.
- **미분류 파일은 상시 묶음만:** 빠르지만 새 디렉터리의 변경이 시험 없이 지나간다. 이 ADR은 반대로 정한다 — 미분류는 풀.

### Consequences

- `tools/ssh`만 바뀐 브랜치는 상시 묶음과 SSH 도구 시험만 돈다. `core_common`이나 harness 설정을 건드리면 지금과 같이 전부 돈다.
- 선택기의 정확도는 harness 등록(`harness.yaml`)과 `platform_parts.yaml`의 `import_prefix` 정확도에 묶인다. 등록 누락은 미분류 → 풀로 드러나므로 조용한 누락이 아니라 느린 실행으로 보인다.
- 역의존은 정적 import만 본다. 웹 정적 파일·YAML 설정 같은 비 Python 결합은 직접 참조 규칙과 main push 풀 실행이 마지막 그물이다. main 풀 실행에서 affected가 놓친 실패가 나오면 선택 규칙을 고치고 그 사례를 선택기 시험 표에 더한다.

**References:** [D-346 커밋 시점 충돌 방어](D-346-commit-time-collision-defenses.md), [D-61 progress-logs-index](D-61-progress-logs-index.md), [D-427](D-427-platform-three-parts-middleware-operations-learning.md), [D-430](D-430-safety-as-a-separate-concern.md), `tools/harness/affected_tests.py`, `test/test_affected_tests.py`.
