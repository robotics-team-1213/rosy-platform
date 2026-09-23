## D-168 ROS 패키지 구조 기준 — 인정 조건, 필수 구성, 도메인 방향표를 시험으로 고정한다

**Status:** Accepted (2026-09-22). D-147(6개 도메인 그룹)을 보완한다. 대체하지 않는다.

**Context:** 패키지 구조에 관한 규칙은 이미 여럿 있다 — D-147(도메인 6그룹·패키지명·
계약 소유 방향), D-126/`test_module_separation.py`(core→슬라이스 import 금지, import 선언,
단일 `cmd_vel`), D-61(모듈 기록), `2026-09-06-module-split-criteria.md`(Python 하위패키지
분리 기준 A/B/C와 반기준 X1–X6). 그러나 **ROS 패키지 단위**에서 세 질문은 기록도 시험도
없었다.

1. 무엇이 별도 패키지가 될 자격이 있는가. 09-06 기준은 하위패키지만 다루고, 09-03
   유지보수 규칙의 "새 ROS 패키지 금지"는 그 계획의 non-goal이었을 뿐 D-125가 core를
   5개 패키지로 나눈 뒤로는 근거가 사라졌다.
2. 패키지가 무엇을 갖춰야 하는가. 2026-09-22 실측: 20개 패키지 중 6개(`core_common`,
   `core_events`, `core_features`, `core_api_web`, `web_common`, `omx_adapter`)가 harness에
   없고, 5개는 `AGENTS.md`가 없는데 `src/core/AGENTS.md`는 그 파일들을 가리킨다.
   `core_features`(5.5k줄)·`core_events`는 자체 시험이 0개이며 `core/core/test` 28개 파일이
   대신 검증한다. 기준 문서는 여전히 "19개 패키지"라고 쓴다.
3. D-147 §3의 "계약 소유 방향"이 도메인 쌍마다 무엇을 허용하는가. core 쪽 방향만
   시험되고, launch 참조는 어떤 시험도 보지 않는다. 그 사이 배포 경로인
   `navigation/launch/hardware.launch.py`가 `control`의 `line_follow.launch.py`를
   포함하면서 `navigation/package.xml`에는 `control`이 없다 — 미선언이자 역방향 결합이다.

**Decision:**

1. **P1 — 패키지 인정.** 새 ROS 패키지는 다음 중 하나를 이름으로 댈 수 있을 때만 만든다.
   (a) 별도 빌드·설치·배포 단위다(다른 이미지·서비스·프로필에 들어가거나 빠진다),
   (b) 다른 패키지들이 공유하는 계약(IDL·스키마·토큰)을 소유한다,
   (c) 다른 프로세스로 떠서 장애가 격리되어야 한다.
   어느 것도 아니면 기존 패키지의 하위패키지이며 09-06 기준 A/B를 따른다. 09-06의
   반기준 X2–X6(대칭, 투기적 작업, 시험 크기, 단일 소유 긴 파일, 경합 중 분리)은 패키지
   단위에도 그대로 적용한다. 줄 수는 P6의 예산으로 다룬다.
2. **P2 — 필수 구성.** `src/<domain>/<package>/` 모든 패키지는 (a) 디렉터리명 = 패키지명,
   (b) `AGENTS.md`, (c) `tools/harness/harness.yaml` 등록과 `progress.md`/`logs.md`,
   (d) 자체 `test/`에 `test_*.py` 1개 이상을 갖는다. **라이브러리·계약 패키지**
   (`core_common`, `core_events`, `core_features`, `core_api_web`, `web_common`)는 스스로
   프로세스를 띄우지 않으므로 ROS-SIM·ARTIFACT·DEVICE·FIELD gate를 `N/A`로 쓰고, 그 판정은
   이들을 싣는 런타임 모듈(`core`, `fleet`)의 gate가 소유한다. SOURCE·LOCAL은 자기 것이다.
3. **P3 — 선언된 결합만.** 패키지 간 결합 — Python import, C++ include, launch의
   `get_package_share_directory`/`FindPackageShare`/`$(find-pkg-share)`, launch 안의
   `Node(package=...)`/`<node pkg=...>` — 은 모두 `package.xml`의
   `depend`/`exec_depend`/`build_depend`/`build_export_depend`에 선언되어야 한다.
   `test_depend`는 결합으로 세지 않는다. 동적 import(`import_module`, 진입점)는 시험이 보지
   못한다 — 의도된 사례는 core의 `rosy.sensor_provider` 로드(D-126) 하나다.
4. **P4 — 도메인 방향표.** 선언 결합의 대상은 출발 도메인별로 아래만 허용한다.
   *core 계약* = `interfaces`, `core_common`, `web_common`.

   | 출발 | 허용 대상 |
   |---|---|
   | `core` | `core` 안에서만 (기존 단방향 사슬 `common ← events ← features ← api_web ← core` 유지) |
   | `apps` | core 계약 |
   | `hardware` | core 계약, `description`(로봇 모델) |
   | `navigation` | core 계약, `hardware` |
   | `site` | core 계약 |
   | `sim` | 전 도메인 — 조립·벤치 최상위 층이다. 대상 패키지의 공개면만 쓴다(D-148) |

5. **P5 — 예외는 시험 안의 목록으로만.** 현재 위반은 시험 파일의 `KNOWN_*` 집합에 사유와
   함께 적는다. 목록은 **집합 동일성**으로 검사한다 — 새 위반도, 이미 사라진 예외도 적색이다
   (09-06 C6 `ALLOWED`와 같은 장치). 2026-09-22 기준 예외: P2(d) `core_events`,
   `core_features`, `web_common`, `navigation`(시험이 루트 `test/`에 있음); P3·P4
   `navigation → control`(hardware.launch.py의 line_follow 포함); P3·core 사슬
   `core_common → core`(`config._find_default_config`가 `core` share에서 기본 설정을 찾는
   역참조 — `try/except` 폴백이 결합을 숨겨 왔다); P3·P4 `control → imu_bno055`(레거시
   robot/wander launch가 IMU 드라이버를 띄움, apps→hardware); P3·P4 `navigation → core`
   (web_nav2/web_slam 계열 launch XML이 core 노드를 띄움 — 내비가 아니라 조립 launch다). 시험이 처음 돌며 찾은
   `bringup → description` 미선언(배포 `rosy-io.service`가 쓰는 `bringup_robot.launch.py`)은
   예외로 두지 않고 `exec_depend`를 추가해 바로 고쳤다.
6. **P6 — 줄 수 예산.** 제품 코드(`test/` 밖의 `*.py`/`*.cpp`/`*.hpp`) **파일 600줄**,
   **패키지 10,000줄**을 예산으로 둔다. 예산 초과는 그 자체로 결함이 아니라 **판정을 강제하는
   신호**다. 초과한 파일·패키지는 시험의 `SIZE_VERDICTS`에 둘 중 하나로 기록해야 한다.
   - `split: <근거>` — 09-06 C1/C2/C5 또는 B 규칙 중 무엇이 발화했는지와 계획 문서.
   - `accept: <근거>` — 09-06 X5(단일 소유·host 시험 가능)나 X6(경합 중) 같은 반기준, 또는
     기존 판정 문서.
   이로써 09-06 X1을 개정한다. 줄 수는 여전히 **단독으로는 분리 근거가 아니지만**, 예산을
   넘은 파일은 판정 없이 남을 수 없다. 판정이 `accept`인 파일이 다시 크게 자라면(판정 시점
   대비 +150줄) 판정을 갱신한다. 시험 파일은 예산 밖이다(X4). 2026-09-22 초과: 파일 9개,
   패키지 1개(`control` 약 28k). 첫 적용에서 `ros_bridge.py`는 09-06 accept 판정(516줄)
   이후 759줄로 자랐고 그 판정의 재진입 조건 (a) — 7번째 타이머(`_tick_line_follow`) — 가
   이미 발화해 있었다. 기준선을 조용히 옮기지 않고 `split`(C2 재개)으로 기록했다.

**Alternatives:** 예산 없이 X1(줄 수 무시)을 유지하는 안 — `web_node.py` 1,091줄처럼 세
역할이 섞인 파일이 "크기는 근거가 아니다"를 이유로 검토 없이 자란다. 예산 초과를 곧바로
분리 의무로 두는 안 — `docking/manager.py`(511줄, 단일 소유) 선례처럼 쪼갤 이유가 없는 파일에
억지 경계를 만든다. 둘 다 채택하지 않는다. 예산 값은 2026-09-22 분포(제품 파일 411개 중
600줄 초과 9개, 800줄 초과 2개)에서 검토 부담이 감당 가능한 선으로 정했다. `description`을 `hardware`로 옮기는 안 — sim과 hardware가 함께 소비하는 로봇
모델이라 어느 쪽이든 한쪽은 도메인을 넘는다. 이동은 D-147에 따라 별도 ADR이 필요하며, 이
ADR은 방향표에 명시 허용으로만 둔다. 모든 라이브러리 패키지에 6개 gate를 독자 판정시키는
안 — 프로세스가 없는 패키지의 DEVICE gate는 판정할 대상이 없다.

**Consequences:** 새 패키지·새 도메인 간 결합·새 launch 포함은 시험을 통과해야 들어온다.
`navigation → control` 예외는 해소 대상이다 — `line_follow` 포함을 배포 조립층(`deploy`
또는 전용 bringup launch)으로 올리거나, D-147에 따른 ADR로 방향표를 바꾼다. `control`
분리 여부는 P1과 09-06 C1/C2/C5로 판단하며 설계는
`docs/plans/2026-09-22-control-package-split-design.md`가 소유한다.
`ROSY Module Operational Acceptance Criteria`의 "19개 패키지" 서술은 20개로 고친다.

**Validation / Transition:** `python -m pytest test/test_module_structure.py test/test_module_separation.py test/test_harness_contracts.py -q` ·
`python tools/harness/rosy_harness.py lint`. 새 시험의 각 가드는 변이 증명(위반 주입→적색→복구→초록)을 거친다.

**References:** D-147, D-148, D-126, D-61, D-125,
[module split criteria](../plans/2026-09-06-module-split-criteria.md),
[runtime maintainability rules](../plans/2026-09-03-runtime-maintainability-rules.md),
`docs/assessments/module-coupling-report.md`.

---
