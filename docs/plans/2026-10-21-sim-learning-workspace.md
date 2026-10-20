# 웹·CLI 공통 SIM 실험 작업공간 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or superpowers:subagent-driven-development to implement this plan task-by-task. 아래 체크박스로 진행을 기록한다. 실행 방식은 사용자 검토 후 선택한다.

**Goal:** 기존 학습 관리 센터와 CLI에서 같은 설정·run ID·결과로 OMX-F import 검사를 실행·관찰·중지·재실행한다.

**Architecture:** 모델 PC의 파일 기반 run 저장소와 Isaac 전용 실행 모듈을 두 진입점이 공유한다. 기존 학습 GPU 잠금에 참여하며, 웹은 같은 서버의 좁은 HTTP 어댑터를 사용한다. 기존 결과 링크·Perception 제어·로봇 owner는 유지한다.

**Tech Stack:** Python 표준 라이브러리, Linux flock·사용자 systemd, 기존 Isaac SDK Python, 기존 HTTP 서버·JS·공통 셸, pytest·Playwright. 새 제품 의존성 없음.

**Spec:** [승인된 설계 v1](2026-10-21-sim-learning-workspace-design.md). 실험 목적·판정은 [D-826 계획](2026-10-21-port-grid-experiment-design.md).

## Global Constraints

- 웹·CLI는 같은 시나리오·검증기·run 저장소를 사용한다. 같은 조건 새 실행은 새 run이며 이전 결과를 보존한다.
- 첫 실행은 OMX-F 모델 import 검사다. 물리 집기·적층·회수·양팔 복구는 준비 안 됨으로 표시한다.
- 실행 종료와 과제 성공은 별개다. GPU 물리 시뮬레이션의 비트 단위 재현성을 주장하지 않는다.
- GPU 모델 PC의 별도 Isaac SDK Python을 사용한다. SDK 5.1을 시작 환경으로 확인하되 실제 버전·GPU·드라이버를 실행마다 기록한다. 노트북·현장 PC 대체 실행 없음.
- 기존 계정·Host·Origin·요청 token·권한 방어를 유지한다. HTTP에 임의 shell·argv·호스트·절대 경로·unit을 받지 않는다.
- 계약 시험은 커밋 SHA를 원격 시험 PC에서 실행한다. 실제 SDK 검사·브라우저 검사·물리 실험의 증거를 구분한다.
- 작업별 새 worktree·명시 경로 staging·독립 착지·D-766/798 크기 규칙을 따른다. 이 계획 승인만으로 push·호스트 설치·로봇 실행을 승인받았다고 해석하지 않는다.

## Review Focus

1. 응답 유실 직후 같은 요청 재전송과 실행기 재시작: 두 실행을 만들지 않는다(Task 2·3).
2. 감독 프로세스가 먼저 죽고 SDK child가 남음: GPU 잠금이 유지되고 새 실행을 막는다(Task 3).
3. 같은 이름의 unit·PID 재사용 또는 binding 변경: 오래된 receipt로 다른 실행을 중지하지 않는다(Task 3).
4. 읽기 중 산출물 교체·symlink·과대 파일·경로 이탈: 웹·fetch는 거절하고 최종 결과를 보존한다(Task 2·4).
5. 다른 탭의 로그인 교체·view만 있는 사용자·미인증 로컬 모드: 실행 제어를 허용하지 않는다(Task 4).

## 확인한 접점과 착지 순서

조사 기준은 설계 커밋 `aa28022f55`다. 실행 시 main과 실제 함수·크기를 다시 대조하고, 다른 세션의 변경은 보존한다.

| 순서 | 책임·주요 파일 | 의존성·완료물 |
|---|---|---|
| 1 | `review_app.py` → 새 `review_store.py`, `test/architecture/size_ratchet.txt` | 기존 검수 저장 코드의 순수 분리. 기능 전에 별도 착지 |
| 2 | 새 `learning/envs/isaac/run_catalog.py`, `run_store.py` | 불변 입력·중복 방지·run 기록·안전한 산출물 조회, Proposed ADR |
| 3 | 새 `run_admission.py`, `run_control.py`, `tools/remote/remote_isaac.py`; 기존 `import_omx.py` | 같은 GPU owner 잠금·실제 제한 실행·CLI·receipt |
| 4 | 새 `sim_web.py`, `review_app_web/sim.html`, `sim.js`; 기존 `/learning` 연결 | 공통 실행기 사용·기존 계정과 셸·로컬 HTTP 계약 |
| 5 | 날짜별 SDK·브라우저 검증 기록 | 양쪽 실제 실행·교차 조회·새 실행·중지·결과 대조 |

각 기능 브랜치는 해당 모듈의 logs와 필요한 생성 index를 포함한다. 15개 파일 초과 또는 land dry-run FULL이면 착지 전 다시 분리한다. shared 자산의 구현 변경이 필요해지면 웹 기능과 따로 착지한다. Task 1은 순수 분리이며 라벨·승인·자료를 변경하지 않는다.

## 공통 인터페이스와 고정값

모든 경로는 저장소 루트 기준이다. 아래는 새 인터페이스이며 현재 구현돼 있지 않다. JSON은 중복 key·NaN·Infinity·알 수 없는 필드를 거절한다.

- `run_catalog.catalog() -> list[dict]`, `normalize(scenario_id: str, config: dict) -> dict`. 실행 가능 후보 ID는 `omx-f-import`; 고정 `model=omx_f`, `headless=true`, `frames=120`, 설정 입력은 `seed` 정수 0..2147483647만 받는다. import는 seed의 효과가 없음을 결과에 명시한다. 나머지 catalog ID `port-e0-pick-place`, `port-mixed-stacking`, `port-retrieval`, `port-cooperative-recovery`는 거절 이유와 함께 disabled다.
- `run_store.RunStore(root: Path)`: `create(request_id: str, scenario_id: str, config: dict, source_sha: str, *, parent_run_id: str | None = None) -> dict`, `get(run_id: str) -> dict`, `list() -> list[dict]`, `update(run_id: str, expected_revision: int, changes: dict) -> dict`, `artifact(run_id: str, artifact_id: str) -> dict`. 요청·run ID는 UUID hex 32자, SHA는 hex 40자. 같은 요청·입력이면 같은 run, 다른 입력이면 conflict다.
- `run_store.input_snapshot(scenario_id: str, config: dict, source_sha: str) -> dict`가 catalog 정규화와 pinned 자산/판정기 해시를 모아 `input`·`input_sha256`을 반환한다. check/create/start는 이 함수 하나를 쓴다. start request의 정확한 key는 `request_id`, `scenario_id`, `config`, `source_sha`, `expected_input_sha256`와 선택적 `parent_run_id`다.
- store는 `<root>/requests/<request_id>.json`, `<root>/runs/<run_id>/input.json`, `state.json`, append-only `events.jsonl`, 최종 `result.json`, `artifacts.json`을 사용한다. 승인된 root의 전용 flock 아래 요청 생성·CAS 상태 전이를 직렬화하고 파일은 fsync+atomic replace한다. 요청 예약 뒤 중단됐어도 같은 ID로 복구하며 입력·최종 파일은 exclusive 생성한다. 웹과 CLI가 별도 DB를 만들지 않는다.
- 입력은 정규화 설정·catalog 버전·SHA·적용 가능한 자산/판정기 지문을 묶어 SHA-256을 계산한다. `get/list`는 기본 비공개 내부 기록, 웹은 별도 allowlist DTO로 변환한다. `artifact_id`는 서버 생성 식별자이며 경로가 아니다.
- `run_admission.acquire(binding: dict) -> context manager`: model-code `<root>/work.lock` 다음 `~/.cache/rosy-learning/gpu.lock`을 nonblocking flock으로 잡고 두 FD를 반환한다. 파일을 삭제하거나 명시 unlock하지 않고 닫아 해제한다. SDK child에 `pass_fds`로 상속한다.
- `run_control.Runner(store: RunStore, binding_file: Path, *, system=None)`: `check(scenario_id: str, config: dict, source_sha: str) -> dict`, `start(request: dict) -> dict`, `status(run_id: str) -> dict`, `stop(run_id: str, expected_revision: int) -> dict`. system 인자는 시험용 OS 경계다. SDK import는 child만 수행한다.
- private binding은 workspace ID·동일 Linux UID·canonical model-code root·run root·승인 source checkout/SHA·Isaac Python 및 SDK 버전을 고정한다. 파일·부모 symlink, 예상 계정/root/SHA 불일치는 거절한다. 브라우저가 binding 값을 제출하거나 바꾸지 못한다.
- run별 `rosy-isaac-<run_id>.service` transient user unit: `KillMode=control-group`, `RuntimeMaxSec=180`, `TimeoutStopSec=10`. unit·InvocationID·cgroup·실제 PID 시작 시각을 receipt에 결합한다. `UNKNOWN`은 자동 재실행하지 않는다. 출력 상한 256 MiB/run, 파일 256개, JSON 1 MiB/file, 로그 16 MiB, MP4 128 MiB. 초과는 실행 실패/중지와 부분 산출물 사유로 남긴다.
- 상태는 `PENDING`, `RUNNING`, `STOP_REQUESTED`, `SUCCEEDED`, `FAILED`, `STOPPED`, `UNKNOWN`. 성공은 해당 시나리오의 보고서 검증까지 필요하다. import는 `stage=model_import`, `task_success=null`, `video_unavailable_reason`을 기록하며 D-826의 물리 파지 증거로 분류하지 않는다.

## Task 1: 웹 서버의 검수 저장 책임 순수 분리

**Files:** `learning/curation/perception/review_app.py`, 새 `review_store.py`, `test/architecture/size_ratchet.txt`, 기존 `test/learning/perception/test_review_app.py`.

**Interfaces:** 기존 `from review_app import ReviewStore, Conflict`를 재노출해 유지한다. `detail_preview`, `make_server`, `ThreadingHTTPServer`의 위치·호출·monkeypatch 경로를 바꾸지 않는다.

- [ ] 기존 소비자를 `rg`로 확인하고 재노출 회귀를 추가한다. `test_store_exports_preserved`에서 `assert review_app.ReviewStore is review_store.ReviewStore`, `assert review_app.Conflict is review_store.Conflict`를 검증한다. fixture는 별도 임시 state만 사용한다.
- [ ] 시험 변경만 커밋하고 원격 해당 시험이 새 모듈 부재로 실패하는지 확인한다. 아래 공통 검증 절차를 사용한다.
- [ ] 현재 약 59~345행의 `Conflict`, `ReviewStore`와 필요한 import만 새 파일로 이동한다. 기존 exception identity·잠금·DB·업데이트·경로 검증을 유지한다. 두 파일 모두 제품 목표 510행 이하가 되게 하고 실제 ratchet을 낮춘다. 1531행 동결된 `test_review_flow_browser.py`에는 추가하지 않는다.
- [ ] 변경을 커밋하고 `test_review_app.py`, `test_review_app_smoke.py`, `test_learning_workspace.py`, `test_learning_control.py`, `test_omx_web.py`, `test_camera_setup_web.py`의 원격 회귀와 size 검사를 통과시킨다. 기대: 새 실패 0, 기존 인터페이스 동일.
- [ ] 독립 검토 후 이 분리만 별도 착지한다. 기능 브랜치는 그 main에서 시작한다.

## Task 2: 시나리오·불변 run 기록·산출물 경계

**Files:** 새 `learning/envs/isaac/run_catalog.py`, `learning/envs/isaac/run_store.py`, `learning/envs/isaac/test/test_run_catalog.py`, `learning/envs/isaac/test/test_run_store.py`; 새 Proposed ADR 본문과 ADR Log 행.

**Interfaces:** 위 catalog·RunStore 계약. storage는 SDK·HTTP·SSH·torch에 의존하지 않는다.

- [ ] `test_same_request_is_one_run`은 동시 create 두 개가 같은 run ID와 입력 해시를 반환하고 디렉터리가 하나임을 단언한다. `test_changed_request_conflicts`, `test_request_reservation_survives_crash`, `test_terminal_result_is_immutable`을 추가한다. `test_catalog_refuses_physics_and_extra_settings`는 disabled 시나리오·`frames=0`·bool seed·추가 필드를 거절한다.
- [ ] `test_artifact_refuses_swap_and_escape`는 파일 교체·symlink·case 충돌·상한 초과·잘못된 해시에 거절을 단언한다. final manifest만 최종 증거이고 실행 중 snapshot은 `OBSERVATION_NOT_ATOMIC`임을 시험한다. 실패·중단 run도 list에 남는지 확인한다.
- [ ] 시험 변경만 커밋해 원격에서 새 모듈 부재 실패를 확인한 뒤 catalog·store를 구현한다. CAS revision 충돌과 fsync/rename 실패를 성공으로 바꾸지 않는다. source/model/설정/판정기 지문은 입력 snapshot에 고정한다.
- [ ] ADR 작성 직전에 번호를 예약한다. Proposed ADR은 공통 run 책임·기존 GPU 잠금 참여·로컬 HTTP와 장치 권한 구분·D-427/429/430 관계를 적고 Log 행과 함께 커밋한다. 구현 전 단계의 capability/DEVICE 수용을 선언하지 않는다.
- [ ] 원격 두 suite·문서 계약 검사, lint·생성 index·독립 검토를 통과시킨 뒤 run 기록 단위로 착지한다.

## Task 3: GPU admission·제한 SDK 실행·원격 CLI

**Files:** 새 `learning/envs/isaac/run_admission.py`, `run_control.py`; 기존 `import_omx.py`; 새 `learning/envs/isaac/test/test_run_admission.py`, `test_run_control.py`, `test_import_report.py`; 새 `tools/remote/remote_isaac.py`, `test/test_remote_isaac.py`; 새 `docs/deployment/isaac-experiment-runs.md`.

**Interfaces:** Task 2의 catalog·store, 위 Runner 계약. CLI는 `check --scenario omx-f-import --config FILE --sha SHA`, `start --request FILE --receipt FILE`, `status|stop|fetch --receipt FILE`만 제공한다. model 호스트는 `lab_hosts.load()`의 명시 선언에서 하나만 선택하고 `--cmd`·임의 호스트 옵션은 제공하지 않는다.

- [ ] admission 시험에서 기존 trainer의 gpu.lock과 signed owner의 work.lock 각각이 Isaac 시작을 막는지, Isaac이 양쪽을 잡으면 반대 owner도 막히는지 실제 Linux subprocess로 검증한다. `test_child_keeps_locks_after_supervisor_exit`는 부모 종료 후 SDK 대역 child가 살아 있는 동안 잠금 충돌을 단언한다. 별도 계정/root·nvidia-smi 실패·GPU compute 점유는 거절한다.
- [ ] 실행 시험은 가짜 SDK child·system 경계로 duplicate launch, launch 직후 응답 유실, unit 재사용/InvocationID 변경, runtime timeout, stop 실패, 재시작 뒤 UNKNOWN, GPU 잔존, output 상한을 재현한다. `test_stop_stale_receipt_never_targets_new_invocation`은 `assert system.stop_calls == []`를 검증한다. 실패 SDK·보고서 없음·120프레임 미완료는 SUCCEEDED가 될 수 없다.
- [ ] CLI 시험은 단절 뒤 같은 receipt 조회·중복 start·잘못된 SHA/host·bounded fetch·Windows 경로 충돌을 고정한다. 테스트를 커밋해 원격 RED를 확인한 뒤 구현한다. `remote_sim.py`의 Gazebo 빌드나 native OMX provision 경로를 호출하지 않는다.
- [ ] `acquire()`는 두 기존 lock을 위 순서로 획득한 다음 GPU·SDK·binding을 재확인한다. 동일 계정이 아니거나 설치된 canonical model-code root를 확인할 수 없으면 거절한다. 기존 `train_job.gpu_lease`·signed execute를 child로 다시 부르지 않는다. 다른 계정/관리 밖 외부 GPU 작업까지 차단한다고 주장하지 않는다.
- [ ] Runner는 입력·예상 지문을 검증하고 store의 요청 예약으로 중복을 먼저 처리한다. 같은 run 재조회에는 새 admission이나 unit 생성을 하지 않는다. 새 PENDING run에만 deterministic unit을 한 번 생성하고 worker가 두 lock 획득 뒤 SDK를 실행한다. admission 거절도 결과에 남긴다. worker가 lock FD를 유지하고 SDK child에 상속한다. stop은 unit과 InvocationID를 다시 확인한 뒤 해당 cgroup만 종료하며, 잔존·cleanup 실패는 결과에 남긴다. root 파일을 unlink해 잠금을 해제하지 않는다.
- [ ] import 입력은 `prepare_omx_urdf.prepare('omx_f', run 전용 경로)`로 만든다. `import_omx.py`에 선택적 `--report FILE`을 추가해 모델/관절/SDK/실행 프레임/자산 지문 보고서를 exclusive 작성한다. 기존 report 없는 CLI·`sdk_entrypoint.close_sdk/run_cli` 종료 동작을 보존한다. 전체 프레임과 관절 검증 뒤만 import 성공이다. 기본 import에는 MP4가 없음을 명시한다.
- [ ] 원격 CLI는 승인 SHA의 detached source를 운반하되 실행 상태·결과를 source worktree 밖에 보존한다. start receipt를 먼저 보존하고 status/stop/fetch는 같은 소유 실행만 참조한다. archive 해시·안전한 regular file 추출을 검증하고 매 fetch는 새 snapshot을 만든다.
- [ ] 소스·운영 binding 예제·상한·복구 절차를 커밋한다. 원격 위 네 suite와 기존 `test_sdk_entrypoint.py`, model/import 관련 회귀를 통과시킨 뒤 독립 검토·착지한다. 실제 SDK 실행은 Task 5에서 별도 증명한다.

## Task 4: 기존 학습 관리 센터에 SIM 연결

**Files:** 새 `learning/curation/perception/sim_web.py`, `review_app_web/sim.html`, `sim.js`; 기존 `review_app.py`, `review_app_web/learning.html`, `learning.js`; 새 `test/learning/perception/test_sim_web.py`, `test_sim_browser.py`; 기존 `shared/web/test/test_app_shell_seats.py`, `learning/curation/perception/docs/review-app.md`, `docs/reference/ROSY API & Protocol Reference.md`.

**Interfaces:** `make_server(..., sim_runs=None)`의 선택 주입을 추가한다. `sim_web.get(handler, path, runs) -> bool`, `post(handler, path, body, runs, collaboration) -> bool`은 True면 처리 완료다. runs는 Task 3 Runner이고 HTTP 파일에서 SDK를 import하지 않는다.

- [ ] HTTP 시험에서 로그인·view·manage 권한, Host/Origin/token, 1 MiB JSON, path/argv/unit/환경변수 입력 거절, private 경로 비노출을 고정한다. `test_view_cannot_start_or_stop`과 `test_unidentified_mode_cannot_control_sim`은 실행 호출 0회를 단언한다. collaboration이 없는 기존 로컬 검수는 유지하되 SIM 실행 제어는 비활성화한다.
- [ ] route는 GET `/learning/sim`, `/api/learning/sim/catalog`, `/api/learning/sim/runs`, `/api/learning/sim/runs/<run_id>`, `/api/learning/sim/runs/<run_id>/artifacts/<artifact_id>`; POST `/api/learning/sim/check`, `/start`, `/stop`을 사용한다. 공개 DTO는 입력 지문·seed·단계·공개 결과·정제한 event 로그·산출물 ID만 반환한다. 원시 SDK stdout/환경변수/private 경로는 웹으로 내보내지 않는다.
- [ ] check는 scenario/config/SHA, start는 request ID/scenario/config/SHA/예상 입력 지문/선택 parent ID, stop은 run ID/expected revision만 받는다. 인증 뒤 view는 조회, manage는 check/start/stop을 허용한다. 서버가 현재 binding·지문·준비 상태를 다시 검증한다. 새 endpoint의 API 번호는 실제 계약 편집 직전에 예약하고 reference·로컬 HTTP 문서·producer/consumer 시험을 함께 수정한다. CORE `/api/v1`·로봇 명령 schema는 변경하지 않는다.
- [ ] 브라우저 시험은 isolated state·가짜 Runner로 CLI 생성 run 조회, 웹 start 후 같은 store 조회, 더블 클릭, 새 run 재실행·원본 보존, 미준비 사유, stop, 로그·영상 없음 사유, 다른 탭 신원 변경을 검증한다. 시험 변경을 커밋해 원격 RED를 확인한 뒤 구현한다.
- [ ] 기존 공통 셸·`accountFetch`·카드·CSS를 재사용하고 `/learning`에 SIM 진입을 추가한다. 기존 `Workspace`의 isaac 링크·`state.json`/`summary.json`·등록/해제·JPG와 D-745 제어는 보존한다. 별도 앱·PWA·Fleet 경로는 만들지 않는다.
- [ ] 원격 API/기존 learning workspace·control/account 회귀, 공통 셸 시험, `ROSY_RUN_BROWSER_TESTS=1`을 명시한 새 브라우저 suite를 통과시킨다. skip된 브라우저 검사는 통과로 세지 않는다. 독립 검토 후 웹 단위로 착지한다.

## Task 5: 실제 모델 PC에서 교차 실행 증거 고정

**Files:** 새 `docs/validation/isaac-experiment-runs-YYYY-MM-DD.md`; 관련 모듈 logs/progress·생성 index. 관측일을 파일명에 사용한다.

**Interfaces:** Task 3 CLI/receipt, Task 4 웹. 검증 대상은 승인된 착지 SHA·모델 PC binding·같은 run 저장소다. 호스트 설치·계정/서비스 설정 변경은 실행 전에 실제 권한과 기존 배포 절차를 확인한다.

- [ ] 실제 Linux UID·두 canonical lock 경로·GPU/VRAM·SDK Python/version·source SHA·data root·시간/용량 상한을 read-only 확인한다. 조건이 없으면 HOLD와 이유를 기록한다. 의존성 설치나 다른 GPU 작업 종료로 자동 우회하지 않는다.
- [ ] CLI에서 OMX-F import 1회 실행하고 웹에서 같은 run의 입력 지문·seed·관절 보고서·로그·종료·산출물 해시를 확인한다. 웹에서 새 실행 1회 후 CLI로 같은 정보를 회수한다. run 사이 GPU 잠금과 종료·회수 결과를 확인한다.
- [ ] 같은 조건 새 run, 연결 끊김 뒤 재조회, 별도 실행의 중지를 확인한다. 이전 결과가 유지되고 다른 학습/로봇 서비스는 변하지 않아야 한다. 실제 SDK의 180초 상한을 못 지키면 실패를 보존하고 수치를 조용히 늘리지 않는다.
- [ ] 실행 횟수·실패 포함 전 결과·실제 SHA·SDK·관절·해시·cleanup·브라우저 증거와 NOT RUN 항목을 기록한다. import 성공은 asset/SDK 연결 근거이며 물리 파지·적층·학습 정책 수용이 아니다.
- [ ] 제품 코드 시험과 실제 SDK 증거를 함께 독립 검토한다. D-826 E0 구현을 시작할 다음 입력은 scene/source tray·제어기·그리퍼·성공 판정 공백 목록이며, 이번 완료 범위에는 넣지 않는다.

## 공통 커밋·원격 검증 절차

각 task에서 명시 파일만 stage하고 커밋한다. RED 커밋은 원격 확인용으로 task 브랜치에만 두고, GREEN 전에는 착지하지 않는다. 테스트 결과는 SHA와 연결한다. 최종 승인된 구현을 밀어 넣기 위해 기존 실패를 면제하거나 새 flaky 등록을 하지 않는다.

```powershell
git diff --check
git rev-parse HEAD
python tools/remote/remote_pytest.py --sha <전체-SHA> --log-dir <외부-scratch/task-N> -- <명시한-suite>
python test/known_failures.py <회수한-run-log>
python tools/harness/rosy_harness.py generate
python tools/harness/rosy_harness.py lint
python tools/land.py --dry-run --tests auto
```

기대 결과는 새 실패 0·문서 lint 오류 0·크기 검사 통과·변경 경로가 자기 목록과 일치하는 것이다. generated 파일이 바뀌면 명시 staging·새 커밋 후 실제 최종 SHA의 영향 범위 시험을 확인한다. 착지는 세션에 병합 권한이 있을 때만 수행하며 push는 별도다. 원격 로그의 호스트 주소·계정은 공개 문서에 복사하지 않는다.

## 자기 검토와 실행 인수

설계의 시나리오/공통 기록은 Task 2, GPU/실행/CLI는 Task 3, 웹/기존 결과 보존은 Task 4, 실제 SDK·교차 검증은 Task 5로 대응한다. 다섯 Review Focus를 해당 task의 시험에 배치했다. 학습 연결은 현재 run 출처와 기존 결과 열람까지이며 자동 export·ACT/RL 실행·정책 승격 기능은 추가하지 않는다. 기존 owner의 두 잠금 경로를 재사용하므로 trainer·signed payload의 범위를 넓히지 않는다.

아직 구현·신규 SDK 실행·호스트 반영은 하지 않았다. 권장 실행 방식은 **Native**다. 한 세션에서 순서대로 구현하고 전체 변경을 독립 검토하면, 공통 store/Runner 인터페이스를 맞추면서 별도 착지 단위를 유지할 수 있다. 사용자가 이 계획을 검토하고 실행 방식을 선택한 뒤 제품 구현을 시작한다.
