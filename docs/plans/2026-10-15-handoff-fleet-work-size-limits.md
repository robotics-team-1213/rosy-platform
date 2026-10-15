# 인계: Fleet 작업 종류(D-763)·크기 한도(D-766)·도구 정비 (2026-10-15)

**왜:** 사용자가 작업 컴퓨터를 옮긴다. 세션 상태(`.omc/`)와 노트북의 `X:\DevTemp` 증거는 따라가지 않는다. 이 문서만 보고 이어 갈 수 있게 남은 일, 착지 순서, 실행 방법, 막힌 것을 적는다. 브랜치 이름은 `git branch`의 출력 그대로다.

## 1. 오늘 main에 들어간 것

| 브랜치 | 내용 |
|---|---|
| `feat/fleet-work-read-sources` | D-763 조각 4. 작업 읽기의 trip·Cell Job 출처, API v1.237. trip 파일을 `server/trips/`, `server/trip_checks/`로, Mission을 `server/missions/`로 옮김 |
| `fix/fleet-proposal-read-scope` | 보안 수정, API v1.240. 제안 읽기는 Cell Job 상세와 같은 범위, 제안자 신원 가림, 채널 admit·submit은 이름 있는 운영자, `resource-claims` 축소, `TRIP_ROBOT_BUSY`에 남의 job id 안 실음 |
| `fix/remote-ship-lock-hang` | 원격 시험 전송이 반쯤 끊긴 링크로 `repo.lock`을 몇 시간 쥐던 문제 |
| `fix/worktrees-omc-state-is-cache` | `.omc/state/`만 캐시로 봐서 착지한 워크트리가 정리됨 |
| `fix/land-runs-browser-tests` | `land.py --tests auto`가 바뀐 화면의 `*_browser.py`를 `ROSY_RUN_BROWSER_TESTS=1`로 돌림 |

## 2. 착지를 기다리는 브랜치와 순서

FULL 묶음(하네스·구조 가드를 고침). 다른 세션의 FULL 두 개(`docs/remove-reference-folder`, `fix/dependabot-alerts`) 뒤에, 조용한 시간에 이 순서로 올린다. 시작 전에 `tailscale switch --list`에서 시험 PC용 프로필이 선택되어 있는지 본다. 다른 세션(D-767 갈래, 착지 도구 수정)은 이 묶음 뒤다.

1. **`refactor/size-ratchet-d766-squash`** — D-766 조각 (a), 커밋 하나. 절대 상한(파일 600, 웹 800, 단위 10,000), 줄어들기만 하는 `test/architecture/size_ratchet.txt`, 단위 목록 `size_units.txt`, `tools/harness/size_limits.py`·`split_check.py`·`size_range.py`, pre-push와 CI에 커밋별 크기 검사. 독립 검토 지적 반영 끝.
   - **main을 합칠 때 충돌이 난다:** `test/architecture/test_module_structure.py`는 이 브랜치 쪽을 택한다. main이 옛 규칙으로 늘린 행(`core_common`, `site_ui/console`)은 손으로 측정값에 맞춘다(다시 만드는 명령은 행을 올리지 않는다). main이 새로 만든 단위(예: `fleet/fleet/server/trip_progress`)는 `size_units.txt`에 `small`로 넣는다. 합칠 때는 `git merge --no-commit main` → 행 맞춤 → 커밋.
   - 원래 브랜치 `refactor/size-ratchet-d766`은 기록용이고 커밋별 검사에 걸리는 커밋이 있다. 올리지 않는다.
2. **`feat/api-version-reserve`** — `tools/harness/api_reserve.py next|list|release|bump`. ADR 번호 도구(D-510)와 같은 방식으로 API 버전을 선점한다. 착지 뒤 우산 폴더(저장소 밖) `AGENTS.md`의 「같이 하는 깃」 4항에 같은 문장을 넣는다.
3. **`refactor/size-units-lane-a`** — 1번 위에 쌓음. 갈래 A 등록(새 단위 16개, 코드 이동 없음)과 세지 않던 루트·`.kt` 측정, 모든 코드 파일이 어느 단위에 속하는지 보는 시험. 결과: `core_common`·`dashboard`는 동결 표에서 빠지고 Fleet 17,788, control 15,931, 콘솔 13,330.

FULL 아님:

- **`feat/fleet-job-trip-steps`** — D-763 조각 7(작업 안의 운행 단계). 사용자 결정 "작게 풀고 진행": Step 원장의 종류 CHECK만 등록부의 종류로 풀었다(D-420 §3의 나머지는 그대로). 안전 검토 세 번: 마지막 판정 PASS WITH CONDITIONS, 위험한 움직임 회귀 없음. 남은 조건: 최신 커밋에서 Gazebo S7(정지 넘겨받기)을 다시 돌려 증거로 남기기, LOW 세 개(만드는 중 lease 놓음, 제자리 trip의 정지 버림, 사건 중복 검사 범위), 커밋에 `Safety-Review:` trailer. 자세한 남은 일은 그 브랜치의 D-763 부기에 있다. API 번호는 `api_reserve.py next`로 받는다(이 문서 시점에 v1.241은 다른 세션 것).
- **`uiux/screenshot-defects`** — 스크린샷에서 나온 화면 결함 일곱 개(Pilot 시험 서버 허용 목록, 로봇 카드의 `undefined`, 좁은 지도, 새 작업 종류 모양, 승인 요구 표시·선택 행, 경기판 계정 링크, 학습 검수 단추). 상태는 그 브랜치의 `docs/plans/2026-10-15-ui-screenshot-defects.md`.
- **`fix/sim-multi-robot-trips`** — 커밋된 2대 Fleet+Gazebo 설정이 trip을 못 달리는 문제(관측 노드 IR 보정 없음, 학습 차선 모델 라이브러리 없음, 의존성 버전 차이, 커밋된 2대 trip 실행기 없음). 실행 방법과 상태는 그 브랜치 문서.
- **`feat/fleet-work-approval-seat`** — 일부러 세워 둔 승인 화면 초안. 조각 5c가 이것을 다시 쓴다.

## 3. 남은 일

1. 위 FULL 묶음 착지.
2. 조각 7 마무리(2절) 뒤 착지.
3. D-766 모듈화 갈래 B·C·D·E — 계획 `docs/plans/2026-10-15-d766-modularization-plan.md`. B 전방 카메라 경로 판단 분리, C 콘솔 설치·지도 편집 화면 이동, D control 루트 이동, E Fleet 묶음 이동(천장 카메라 → 지도 → 증거 → 제안 → 통행권 → 명령 분배, 명령 분배는 안전 경로라 맨 끝). D-760 2c 이후 `core/trip_lease.py`를 고치는 커밋은 `Safety-Review:` trailer가 필요하다.
4. D-763 조각 5c(승인 화면) — 콘솔 단위가 동결되므로 갈래 C 뒤.
5. D-763 조각 8.
6. `perception/map` 스크립트(약 1,800줄)는 패키지도 홀더도 아니라 크기 단위로 등록하지 못했다.
7. Rosy Cam 앱이 9,964줄로 단위 상한 바로 밑이다. 무엇을 더하기 전에 나눈다.
8. 사람이 기기에서 본 적 없는 화면: D-741 통합 셸 전부, D-763 작업 화면, Cam 앱.

## 4. 열린 결정

- Kotlin 파일 상한은 D-766에 없어 600줄(파이썬과 같음)로 넣었다. 다르게 할지는 사용자 결정.
- D-420 §3(Step 원장 요구 S1–S12)의 나머지는 소유자가 정한다. 조각 7은 CHECK만 풀었다.
- 조각 7의 정지 넘겨받기: Pilot·LCD·AI PC 판정이 CORE를 `executing`+`STOP`으로 둘 수 있는지 확인 못 함. 그렇다면 넘겨받기에 소유 확인이 더 필요하다.

## 5. 실행 방법

- 시험은 노트북에서 돌리지 않는다(D-584). `python tools/remote/remote_pytest.py --log-dir <스크래치>/<이름> -- <경로>` 다음 `python test/known_failures.py <로그>`.
- 브라우저 시험: `python tools/remote/remote_pytest.py -- ROSY_RUN_BROWSER_TESTS=1 <경로>`. `land.py --tests auto`는 바뀐 화면의 것을 알아서 고른다.
- Gazebo: `python tools/remote/remote_pytest.py --pick sim ...` 또는 `tools/remote/remote_sim.py`. 2대 Fleet trip은 `fix/sim-multi-robot-trips`가 들어가기 전에는 커밋된 실행기가 없다.
- 착지: 워크트리에서 `python tools/land.py --tests auto --node --max-rounds 12`. main이 움직이면 회차를 다시 돈다. API 버전 줄 충돌은 자기 버전을 위에 두고 두 변경 기록을 모두 남긴다.
- 원격 전송이 빈 문구로 실패하면 시험 PC의 `~/rosy-test/repo.lock`을 누가 쥐었는지 본다(`lsof`).

## 6. 막힌 것

- Cell Job 승인·거절(조각 5)은 시뮬레이션에 OMX 작업대가 없어 끝에서 끝까지 확인 못 함.
- push는 사용자가 말한 세션만 한다. 이 문서 시점에 보안 수정(v1.240) 이후 착지분은 아직 공개되지 않았다.
