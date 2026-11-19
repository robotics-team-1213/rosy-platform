## D-1052 셀프 리뷰 1급 지원, 블로킹 FULL 폐지(Zero-FULL), Merge Queue 직행

**Status:** Accepted (2026-11-19, 사용자 결정: "리뷰어는 자기 자신이 될수도 있어", "아예 full 을 없애는것도 고려해", "바로 처리해")

잇는 결정: [D-427](D-427-platform-three-parts-middleware-operations-learning.md)(3개 파트 소유·경계) · [D-429](D-429-five-concerns-control-port-and-site-devices.md)(5관심·포트) · [D-430](D-430-safety-as-a-separate-concern.md)(safety 관심·트레일러) · [D-436](D-436-change-scoped-test-tiers.md)(변경 범위 시험) · [D-441](D-441-site-stack-automatic-update.md)(정확 SHA `ci-result` 서명) · [D-762](D-762-main-gateway-pull-request-merge-queue.md)(GitHub Merge Queue) · [D-1037](D-1037-land-speed-import-closure-and-pool-waits.md)(import 폐포) · [D-1038](D-1038-scheduled-publish-merge-review-gate-append-only-and-urgent-lane.md)(review-gate).

### D-427 · D-429 · D-430 관계표

| 기준 ADR | 유지되는 계약 | D-1052에서의 변경 |
|---|---|---|
| D-427 (파트 소유) | `platform_parts.yaml` 루트·`app:`·import 방향 경계 불변 | `app_of()`를 Zero-FULL 앱 캡슐 범위 산정에 직접 사용 |
| D-429 (관심·포트) | 5관심·장치 포트 경계 유지 | 미변경 |
| D-430 (safety) | `Safety-Review:` 트레일러 강제 및 `--no-merges`/merge commit 유지 | `safety_review.py` 단일 스트림 배치화(<1초), 작성자+이종 모델 독립 리뷰 증적 표준화, safety 경로를 레포 `FULL` 대신 전체 소유+역의존+소유 앱 캡슐로 실행 |

### Context

1. 직렬 로컬 `main` 착지 큐(`land*.py`)와 레포 전체 `FULL` 티어(`merge_group`·`push: [main]`·6종 선택기 격상·`publish_main` 로컬 `FULL`)가 다수 병렬 작업 및 1인 다트랙 운영을 수십 시간씩 정체시켰다.
2. `.github/review-gate.sh`는 과거 14일 병합 이력의 타인 수정 파일 접촉 시 타인 `APPROVE`를 요구해 1인·야간 셀프 리뷰 시 데드락을 유발했다.

### Decision

1. **셀프 리뷰 호환 (`review-gate` & `D-430`):**
   - `main-protection` 규칙(`required_approving_review_count: 0`, `require_code_owner_review: false`)을 유지한다(D-762의 2번째 인간 Admin 의무 폐기).
   - `.github/review-gate.sh`는 기본 `WINDOW_DAYS=0`으로 **현재 열린(`OPEN`) 타 PR과의 파일 겹침만** 검사하고, PR 본문 또는 리뷰 코멘트의 `Overlap-Review: self (<사유>)`로 자가 해제를 허용한다.
   - `Safety-Review:` 트레일러는 작성자 점검 + 이종 모델 패밀리 독립 읽기 전용 계약 리뷰 조합을 정식으로 허용하며, `known_failures.txt` 편집이 `FULL`로 격상되지 않는다.
2. **블로킹 `FULL` 폐지 (`Zero-FULL`):**
   - `.github/workflows/ci.yml`은 `pull_request`·`merge_group`·`push: [main]` 모두 각 이벤트 base(`base.sha` / `merge_group.base_sha` / `before`) 기준 `--ci-matrix` 영향 선택만 실행하며, `schedule`·`workflow_dispatch`만 `--full`을 유지한다(D-441 `push:main` `ci-result` 서명 검증 및 `concurrency` 미설정 불변 유지).
   - `tools/harness/affected_capsules.py`가 `concern: safety`, `contracts/foundation` 런타임 소비자, 패키징/`ros_idl`/`compose`, 폴더 이동/삭제, `SELECT_CORE`/매니페스트, `unmapped`를 각 정밀 캡슐(`Safety`/`Importer-Closure`/`Packaging`/`Harness`/`Moved` + `test/architecture`)로 실행한다(`ROSY_FULL_LEGACY=1` 복구 스위치는 보존).
   - `tools/publish_main.py --via-ci`는 로컬 `FULL` 기록 대기 없이 `secret_gate`·`safety_review`와 GitHub `ci-result`로 적체 게시를 허용한다.
3. **고속 PR 착지 & ADR 연속성 완화:**
   - `tools/hooks/pre-push`는 `rosy.staticPrePush=true`(또는 `ROSY_STATIC_PRE_PUSH=1`)일 때 정적 게이트(lint·secret·Safety-Review·size) 후 pytest를 CI/Merge Queue에 위임하고, `tools/pr_land.py`로 PR 생성·자동 병합을 일원화한다.
   - `tools/harness/adr_gaps.py`는 연속 번호(gap) 검사를 `D-1043`까지로 한정하고 `D-1044+`부터는 유일성만 검사한다.
   - `tools/harness/affected_pack.py`는 비직렬 캡슐을 `MAX_GROUP_PATHS = 28` 단위로 분할해 랩 PC와 GitHub Actions 러너에 병렬 분산한다.
   - `.github/workflows/build-site-candidate.yml`은 `push: [main]` 시 최신 서명된 `site-*` 후보를 `base_commit`으로 자동 탐색·재사용하고, `deploy/site/build_candidate.py`(`--jobs 4`)·`Dockerfile.{fleet,vision}` 계층 캐시 순서 및 `publish-release.yml` 사전 설치 도구 분기로 CD·릴리즈 빌드를 단축한다.

### Consequences

- PR·Merge Queue·`push: [main]` 소요가 25분×2회(42+ 잡)에서 정밀 캡슐(3~6분)로 단축되며 서명 검증과 안전 트레일러는 그대로 유지된다.
- 개인 부분 클론(`--filter=blob:none --no-tags`, Graphify 훅 제거, `rosy.staticPrePush=true`)에서 `git pull`과 PR 착지가 인적·큐 병목 없이 동작한다.
