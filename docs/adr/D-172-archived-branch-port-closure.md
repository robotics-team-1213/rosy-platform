## D-172 구조 개편 이전의 미병합 브랜치는 태그로 보존하고, 재구현·독립 리뷰를 거쳐서만 main에 들인다 — Python 3.12가 기준

**Status:** Accepted (2026-09-22).

**Context:** 2026-09-22 로컬 main 정리에서 브랜치 50여 개와 worktree 40여 개를 점검했다.
대부분은 이미 병합돼 있었지만, D-125/D-126 구조 개편(`src/rosy_core/...` →
`src/core/{core,core_common,core_features,core_events,core_api_web}`) 이전에 갈라진 브랜치
5개에는 main에 없는 커밋이 남아 있었다. main보다 450~620커밋 뒤처진 상태여서 그대로
병합하면 대규모 충돌이 나고, 충돌 없이 들어가더라도 옛 경로에 코드가 되살아난다.
그렇다고 지우면 검증되지 않은 결함 수정이 사라진다. 같은 날 여러 세션이 한 main 트리를
공유했고, 병합된 두 브랜치가 API 레퍼런스 버전을 동시에 올리는 충돌도 났다.

**Decision:**

1. **보존:** main에 없는 커밋을 가진 브랜치는 지우기 전에 주석 태그
   `archive/<YYYY-MM-DD>/<branch>`를 단다. 이 태그는 지우지 않는다. 문서가 태그 안의
   커밋을 근거로 인용할 수 있다(`docs/solutions/workflow-issues/a-fixture-from-the-same-model-is-one-belief-not-two.md`).
2. **이관 방식:** 옛 브랜치는 병합하거나 cherry-pick하지 않는다. main에서 딴 `port/<name>`
   브랜치에서 변경 단위마다 판정한다.
   - **ALREADY-IN-MAIN:** 같은 효과가 이미 main에 있다.
   - **SUPERSEDED/OBSOLETE:** main이 다른 설계를 택했거나 코드 경로가 사라졌다. 근거 ADR이나 커밋을 인용한다.
   - **PORT:** 현재 구조에 맞춰 재구현하고, 결함이 main에 실제로 남아 있음을 시험으로 먼저 보인다.

   PORT는 작성자와 다른 리뷰어가 APPROVE해야 병합한다. `cmd_vel` 경로나 이벤트 버스
   스레드를 건드리는 변경은 "main이 0을 보내는 곳에서 0이 아닌 값을 보낼 수 있는가"를 CRITICAL로 본다.
3. **기준 인터프리터:** CI(`ros:jazzy` 컨테이너, Ubuntu 24.04)와 Pi가 쓰는 Python 3.12를
   기준으로 삼는다. Windows 호스트의 3.14 통과만으로는 병합 근거가 되지 않는다. core를
   건드리는 변경은 3.12에서 `src/core/core/test/`를 돌린다. `ast.dump`처럼 버전에 따라
   출력이 달라지는 값을 시험 고정값으로 쓰지 않는다.
4. **버전 고정 문서:** 여러 브랜치가 API 레퍼런스 버전을 동시에 올리면 병합 순서대로
   다시 매긴다. 먼저 들어간 쪽이 번호를 유지하고, 나중 쪽이 다음 번호를 받는다.
   `test/test_line_follow_contract_docs.py`의 버전 고정값도 같은 커밋에서 맞춘다.
5. **worktree 정리:** 병합이 끝났고 커밋 안 된 변경·untracked 파일이 없으며 최근 1시간 안에
   수정이 없는 worktree만 지운다. 나머지는 소유자의 몫으로 남긴다.

**2026-09-22 판정 결과:**

| 옛 브랜치 (태그) | 판정 | main 반영 |
|---|---|---|
| `cap/lock-capability-contract` | SUPERSEDED. 모드별 광고 제한은 배포 오버레이(`capabilities.<mode>.yaml`)와 D-68이 대체했다. 신원 고정은 이미 main에 있다. | 없음 |
| `feat/dock-detector-measurement-rig` | SUPERSEDED. 도킹 인식은 카메라 태그로 정해졌다(DNC-007, D-138/D-139). 용어집과 학습 노트만 PORT. | 병합 `2ee9a9a` |
| `fix/event-catalogue-drift` | PORT. `safety.watchdog` 발행, cmd_vel 50 Hz 사이클을 ROS 없는 `bridge/cmd_vel.py`로 분리, §8 카탈로그 가드. API Ref v1.13 | 병합 `0adbe50` |
| `fix/audit-log-write-cost` | PORT. append 전용 기록, 백그라운드 압축 워커, 꼬리부터 역방향 조회, 격리 파일. API Ref v1.14 | 병합 `11f1164` |
| `feat/rosy-control-absorption` | ALREADY-IN-MAIN (patch 동일) | 없음 |

**Alternatives:**

- 옛 브랜치를 그대로 병합하는 안: 옛 경로 코드가 되살아나고 D-125/D-126 경계를 깨뜨린다.
  CAP 브랜치의 `extra="forbid"` 스키마는 현재 설정 키를 거부해 sim과 실기 부팅을 막는다.
- 태그 없이 삭제하는 안: audit·event 결함 수정(각각 main에서 30개, 12개 시험이 실패하는
  실결함)이 근거와 함께 사라진다.
- 리뷰 없이 병합하는 안: 이번 리뷰에서 CRITICAL 2건이 나왔다. 매시 압축이 발행 스레드를
  0.66~0.79 s 붙잡는 문제, 그리고 수정 도중 생긴 20 ms 동안 끊기기 전 명령을 다시 보내는
  경합이다. 3.12 전용 시험 실패 1건도 나왔다.

**Consequences:** 태그 5개가 영구 기록이 된다. 이관 판정의 근거는 `docs/logs.md`,
`src/core/core/logs.md`, `src/core/core_events/logs.md`의 2026-09-22 항목에 있다.

**후속 항목 (이 ADR이 소유; 닫히면 logs.md에 기록):**

- **F1 core ROS-SIM 재확인:** cmd_vel 경로와 audit 워커가 바뀌어 core ROS-SIM은 HOLD다.
  `docs/validation/ros-sim-core-2026-09-22/README.md` 절차를 현재 트리에서 다시 돌려
  `/cmd_vel` 발행자 1개(core)를 확인한 뒤 GO로 되돌린다.
- **F2 audit 후속:** 격리 파일 fsync를 잠금 밖으로 옮기고 재시도 중복을 막는다(MEDIUM).
  스레드 시작 실패가 `record()` 밖으로 새지 않게 한다(LOW). 디렉터리 fsync 실패를 압축
  실패와 구분한다(LOW).
- **F3 빈 worktree 6개:** `X:/DevTemp/**` 아래 옛 저장소 경로를 가리키는 빈 worktree
  (`.git`, `.gitignore`만 남음)를 지우고 `worktree prune`한다. 강제 제거라서 사용자 승인이 필요하다.
  브랜치 `feat/module-split-criteria`, `feature/rosy-pi-runtime`(병합 완료)과
  태그로 보존된 옛 브랜치 3개가 여기에 묶여 있다.
- **F4 커밋 안 된 작업이 남은 worktree 8개**(`pinky-*` 4개, `gazebo-slam-complete`,
  `line-follow-modes`, `optional-runtime-slices`, `rosy-control-absorption`): 소유자가
  커밋하거나 버린다. 이 ADR은 대신 판단하지 않는다.
- **F5 D-171 목록 행:** `451223c`가 다른 세션이 작성 중이던 D-171 목록 행을 본문보다 먼저
  커밋해 하네스 lint가 적색이었다. D-171 작성자가 본문 커밋과 `generate`로 닫았다(`581741e`). **닫힘.** 공유 트리에서는
  `git add -A` 대신 경로를 지정해 스테이징한다.

**Validation:** `python -m pytest src/core/core/test/ test/ -q -p no:cacheprovider` (3.14) ·
`uv run --no-project --python 3.12 --with-requirements deploy/robot/requirements-core.txt --with pytest --with httpx --with numpy --with jsonschema python -m pytest src/core/core/test/ -q`
(3.12, 병합 후 1214 passed) · `git tag -l 'archive/2026-09-22/*'` 5개.

**References:** D-125/D-126(구조 개편), D-168(패키지 구조 기준, audit.py 길이 판정),
D-68(CAP-001 descriptor), D-138/D-139(도킹 인식), D-1(단일 인스턴스), API Ref v1.13/v1.14 변경 이력.

---
