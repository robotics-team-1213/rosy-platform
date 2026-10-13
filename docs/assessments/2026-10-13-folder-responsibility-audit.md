# Rosy 폴더 중복·책임 경계 조사

**조사일:** 2026-10-13 · **제품 소스 기준:** commit `a967ab11a5a1a41ec488f32fb8ef37aedb7fc465` · **브랜치:** `docs/folder-responsibility-audit`

Rosy 우산 폴더는 제품 저장소, 동결 보관본, 릴리스 증거를 담는다. 실제 제품은 `rosy-platform` 하나이며 CORE가 로봇 최종 명령, Fleet이 현장 작업 원장을 소유한다. 여러 개발 세션이 같은 PC와 공유 main을 사용하는 상황을 기준으로 조사했다.

**판정: 정리 방향은 이미 결정되어 있지만, 실제 정리는 완료되지 않았다.** 반복 이름의 대부분은 설치 이름·서로 다른 권한·이력 보존으로 설명된다. 우선 고칠 것은 현재 경로를 잘못 안내하는 문서다. 그 다음은 D-738의 단계별 이름/책임 정리, 실제 인증 보조 코드 중복, 소스처럼 남은 캐시·분석 산출물의 위치다. 이름만 보고 폴더를 합치거나 지울 근거는 없다.

## 범위와 조사 방법

- 우산 `F:\Dev\Control\Robot\Rosy`와 제품 저장소를 조사했다. `archive`·`artifacts`는 역할 안내와 최상위 배치만 확인했으며, 보관된 모든 바이트를 대조하지 않았다.
- 제품 분석은 독립 worktree의 위 SHA에 고정했다. 공유 main은 조사 도중 전진했다. 물리 잔여 폴더 조사에서 관측한 main은 commit `413ef5aed14156c689bcfb2341f44c4051c47d13`, 관리 도구의 worktree 인벤토리는 2026-10-13 12:01:48 KST의 별도 스냅샷이다. 서로 다른 시점의 수치를 한 SHA의 상태로 합치지 않았다.
- `git ls-files`, `git worktree list --porcelain`, 관리 도구 `workspace.ps1 -Action Worktrees`, 소유권 manifest, 실제 `setup.py`·source layout·호출자·시험 파일을 읽었다. 물리 폴더 조사에서는 junction/reparse 하위 경로를 따라가지 않았다.
- 파일 동일성은 여섯 제품 part의 `.py`, `.js`, `.mjs`, `.html`, `.css`, `.sh`, `.cpp`, `.hpp` 중 120바이트 이상을 SHA-256으로 비교했다. 의미가 비슷한 다른 구현, Kotlin·헤더의 다른 확장자, 짧은 초기화 파일까지 동일성 검사를 했다는 뜻은 아니다.
- 제품 코드, 기존 폴더, 동료 변경은 수정·이동·삭제하지 않았다. 이 보고서와 문서 작업 기록만 독립 worktree에 작성했다. 착지·push·배포는 수행하지 않았다.

| 측정 | 결과 | 해석 |
|---|---:|---|
| 추적 파일 | 7,665 | 보고서 작성 전 기준 SHA |
| 여섯 제품 part의 추적 파일을 담는 디렉터리 | 492 | namespace·test·resource 등 패키지 내부 디렉터리 포함 |
| 두 곳 이상에 등장하는 디렉터리 마지막 이름 | 97종 | 97건의 결함이라는 뜻이 아님 |
| manifest root | 95 | `platform_parts.yaml`의 `path` 항목 |
| 위 part에서 root에 매칭되지 않은 비-Markdown 추적 파일 | 0 | 경로 배정 확인. import 규칙·실행 권한·기능 정확성 PASS는 아님 |
| 동일 내용 소스/시험 파일 묶음 | 5 | 제품 구현 1쌍, 시험 템플릿/부트스트랩 4묶음 |
| 등록 worktree | 250 | primary 1 + task 249. 이번 보고서 worktree 포함 |
| 변경이 있는 worktree | 53 | primary 1 + task 52. 상태 관측일 뿐 변경 소유자 확인은 아님 |
| 관리 도구 판정 | HOLD 155 / REVIEW 95 | 삭제 승인이나 안전 제거 판정이 아님 |
| 미등록 `.worktrees` 하위 디렉터리 | 1 | `.omc/state`; 제품 사본으로 분류하지 않음 |

현행 근거는 [폴더 책임 안내](../reference/platform-folder-responsibilities.md), [소유권 manifest](../../tools/harness/platform_parts.yaml), Accepted [D-738](../adr/D-738-folder-one-authority.md)이다. D-738은 **정리 규칙과 10단계 순서의 수락**이다. 기준 SHA에는 `middleware/drive`, `middleware/perception/nodes`, `robot_execution`, `site_execution`, `robot_ui`, `site_ui`, `overhead`, `front_camera` 목표 holder가 아직 없었다. 규칙 수락을 이동 완료로 기록하면 안 된다.

## 우선 수정

### 1. 우산 입구와 일부 AGENTS가 옛 소스·화면 경로를 안내한다

- **현재 역할:** 우산 README와 폴더 안내는 새 세션이 제품 소스를 찾는 입구다.
- **문제와 근거:** 우산 `README.md:4,28`은 `rosy-platform/src/runtime/sensing`, `src/site/fleet`을 현재 경로로 안내하고 `archive/AGENTS.md:26`도 옛 Control 경로를 안내한다. 현재 추적 소스는 각각 `middleware/perception`, `operations/fleet`에 있다. 제품 [CORE API 안내](../../middleware/core/api/core_api_web/api/AGENTS.md)의 `../web/`, [Fleet server 안내](../../operations/fleet/fleet/server/AGENTS.md)의 `web/`도 실제 UI 원본 위치와 다르다. 실제 설치는 `middleware/ui/robot`, `operations/ui/console`을 소비한다.
- **최소 조치:** 현재 작업을 안내하는 문장과 링크만 현재 소스·UI holder로 고친다. 과거 ADR·날짜 증거·릴리스 내부 안내는 그 당시 사실을 보존한다. 우산 README의 과거 실행 계획도 현행 작업 입구와 역사 링크를 구분한다.
- **그대로 두면:** 새 세션은 캐시만 남은 옛 트리나 화면의 옛 설치 경로를 정본으로 오인하고, 잘못된 위치에 파일을 만들 수 있다. `reference/`도 안내상 frozen zip holder이지만 공유 main에서는 추적 AGENTS 2개가 삭제된 상태이고 물리 폴더가 없었다. 동료 변경을 복구하지 말고 해당 소유자의 의도부터 확인해야 한다.

## 책임·이름 정리 필요

### 2. 같은 마지막 이름이 다른 권한을 가리킨다 — D-738 실행이 남았다

- **현재 역할:** 폴더 이름은 편집할 책임을 알려주고 설치 이름은 기존 소비자를 연결한다.
- **문제와 근거:** 아래 표처럼 `control`, `execution`, `ui`, `vision`, `decision`, `safety`는 서로 다른 출력·권한을 가리킨다. [Perception source mapping](../../middleware/perception/control/_source_layout.py), [CORE behavior mapping](../../middleware/core/services/core_features/_source_layout.py)이 기존 import와 실제 소스를 따로 연결한다. 따라서 단순 전체 문자열 치환이나 폴더 합치기는 설치·admission 경계를 깨뜨린다.
- **최소 조치:** D-738 순서를 그대로 사용한다. 바깥 holder부터 한 단계씩 바꾸고 `package_dir`, manifest, 배포 source closure, 호출자와 시험을 같은 단계에서 갱신한다. 다섯 호환 initializer와 Python namespace는 예외로 유지한다.
- **그대로 두면:** 이름만 보고 CORE의 허가를 현장 AI 후보와 섞거나, 관측을 동작 입력으로 취급하거나, 설치 이름을 중복 구현으로 오판한다.

| 반복 이름 | 현재 위치와 책임 | 처리 |
|---|---|---|
| `control` | `middleware/control`의 Drive 분류 / `middleware/perception/control`의 ROS 조립 / 그 안 `control` 설치 호환 initializer | D-738 1~3. 호환 initializer 유지 |
| `drive` | `middleware/control/drive`의 행동·근거 / `middleware/core/gateway/core/drive`의 CORE 조립 | 합치지 않음. 알고리즘과 최종 선택/조립은 별개 |
| `execution` | `middleware/execution/local`의 설치 policy·receipt / `operations/execution`의 현장 목표·진척 / Fleet 내부 채널·incident 실행 어댑터 | D-738 4는 바깥 holder. 내부 어댑터는 각각 원장 경계에 유지 |
| `ui` | `middleware/ui`의 로봇 화면 / `operations/ui`의 현장 화면 | D-738 5. Android `.../ui` namespace는 별개 |
| `vision` | `middleware/perception/vision`의 앞 카메라 / `operations/vision`의 천장·신호 관측 / `core_features/vision`의 bounded preview 저장 | D-738 6~7. 서로 다른 출력이므로 통합하지 않음 |
| `decision` | `core_features/decision`의 장치 로컬 허용 집합 / `operations/decision`의 현장 모델 후보 / `learning/evaluation/decision`의 오프라인 평가 | D-738 7 및 학습 경계 유지 |
| `safety` | `core_features/safety`의 공통 게이트 / `middleware/control/drive/safety`의 동작 후보 제한 / `control/safety` 설치 initializer | D-738 7. 공통 Safety와 후보 제한을 구분 |
| `calibration` | Drive 보정 동작 / `core_features/calibration`의 attended session lease | 출력이 다름. 합치지 않음 |
| `incidents` | `rosy_situation/incidents`의 상황 근거 / `fleet/incidents`의 기명 인수·알림·운영 원장 | 출력이 다름. 합치지 않음 |
| `fleet` | `operations/fleet` 서버 / 그 안 `fleet` Python package / `operations/apps/fleet`의 `rosy-app-gateway` 조립 | 설치 package 유지. apps holder는 기능명 `site_gateway` 후보로 별도 결정 필요; D-738에 없는 개명은 실행하지 않음 |
| `perception` | `learning/{curation,training,evaluation,registry}/perception` / 로봇 인지 구현과 설치 namespace | 학습 수명주기별 반복은 정상. 하나로 합치지 않음 |

### 3. Perception의 `control` 조립 폴더에는 아직 순수 판단도 있다

- **현재 역할:** `middleware/perception/control`은 센서·관측 ROS 노드와 저장·전송 어댑터를 조립한다.
- **문제와 근거:** 직접 Python 파일 51개가 있고 [loc_assist.py](../../middleware/perception/control/loc_assist.py)는 탐색 시점·후보·주입 결정을 소유한다. [loc_assist_node.py:45](../../middleware/perception/control/loc_assist_node.py#L45)가 이를 호출한다. [watch.py](../../middleware/perception/control/watch.py)는 ROS 없는 graph 검사다. '노드만 있는 폴더'로 분류하면 실제 판단을 빠뜨린다.
- **최소 조치:** D-738 2에서 입력/출력별 순수 판단과 해당 어댑터를 기능 단위로 판정한 뒤, 남은 조립 holder를 3단계에서 `nodes`로 바꾼다. 서로 다른 출력의 판단을 새 거대 `logic` 폴더로 몰지 않는다.
- **그대로 두면:** 새 판단이 임의로 `control` 또는 Drive에 추가되고 같은 기능의 시험·어댑터·소유권이 계속 흩어진다. 이 사례는 내용이 같은 두 구현이 있다는 증거는 아니다.

### 4. Fleet `server`가 여러 책임의 공동 편집 장소다

- **현재 역할:** Fleet 서버는 단일 프로세스·SQLite 원장을 조립한다.
- **문제와 근거:** `operations/fleet/fleet/server` 바로 아래 Python 파일이 141개다. [app.py](../../operations/fleet/fleet/server/app.py)는 `CellJobStore`, 인증 세션, 콘솔·mission·signal·ingest·peer route를 조립한다. 원장 전이, 채널, 셀 어댑터, 화면 조립, peer 승인 파일들이 같은 일반 이름 아래 있다. 이미 있는 `server/channel` 하위 분리만으로 전체 책임 분리가 끝난 것은 아니다.
- **최소 조치:** D-738 8의 다섯 책임으로 파일을 옮기되 한 DB·한 프로세스·기존 거래 경계를 유지한다. `app.py`는 조립을 소유하고 순수 판단은 기존 World/Situation/Decision/Execution을 소비한다. 파일 수만으로 서비스나 DB를 새로 만들지 않는다.
- **그대로 두면:** 파일을 찾거나 변경 소유자를 정할 때 `server`가 답이 되고, 후보 계산과 원장 전이를 같은 책임으로 취급하기 쉬워진다. 현재 데이터 경쟁이나 거래 오작동을 재현했다는 판정은 아니다.

### 5. 인증 보조 코드 121행이 두 제품 owner에 완전히 동일하게 있다

- **현재 역할:** CORE peer 승인과 Fleet camera peer 승인에서 public key·서명 transcript·identity 파일을 처리한다.
- **문제와 근거:** [CORE peer_crypto.py](../../middleware/core/api/core_api_web/api/peer_pairing/peer_crypto.py)와 [Fleet camera_peer_crypto.py](../../operations/fleet/fleet/server/camera_peer_crypto.py)는 SHA-256과 바이트가 동일하고 각각 121행이다. CORE `receiver_service`, Fleet `camera_peer_service/store/routes`가 각각 자기 사본을 import한다. 사용하지 않는 파일이 아니다.
- **최소 조치:** 공통 proof 처리를 한 구현으로 둘 수 있는 기존 shared holder와 dependency/설치 경계를 먼저 확인한다. CORE/Fleet 승인 principal·DB·rate limit은 각각 남겨야 한다. `cryptography`를 ROS-free contracts에 무조건 추가하거나 Fleet이 CORE 내부를 직접 import하게 만들지 않는다. 의도적인 복제라면 두 사본의 동등성을 검사하고 유지 이유를 기록한다.
- **그대로 두면:** 한쪽에서 key/encoding/path 검증을 고쳐도 다른 쪽은 옛 정책을 유지할 수 있다. 현재 보안 취약점을 입증한 것은 아니며 유지보수 중복을 확인했다. 기존 [Fleet golden-vector 시험](../../operations/fleet/test/test_camera_peer_vectors.py)과 CORE peer 시험을 함께 보존해야 한다. 전체 공유 파일 통합이 아니라 이 proof 구현 한 쌍만 후보이다.

### 6. 호스트 도구와 장치 측 도구가 제품 인지 폴더에 함께 있다

- **현재 역할:** `middleware/perception/tools`에는 이름 감사·보정 이관·Gazebo rig·장치 측 측정 도구가 있다.
- **문제와 근거:** [tools 안내](../../middleware/perception/tools/AGENTS.md)는 host-side utilities라고 소개하면서 `device/hotpath_measure.py`, `device/ir_line_calibrate.py`는 Pi/센서 측 측정이라고 구분한다. 폴더만 보고 전체를 같은 실행 환경의 런타임 진입점으로 분류하면 잘못이다.
- **최소 조치:** D-738 9에서 호스트 Gazebo·보정 도구를 `tools/sim`, `tools/calibration`로 옮긴다. `device` 파일은 실제 실행 host와 배포 소비를 확인한 뒤 개별 판정한다. 파일 내용과 기록이 다른 측정 도구를 basename 때문에 합치지 않는다.
- **그대로 두면:** 도구 위치로 설치 대상이나 시험 환경을 추정하고 배포 closure에서 필요한 측정을 빠뜨리거나 호스트 도구를 런타임에 넣는다.

### 7. World 구현은 하나지만 Fleet 별칭 호출자가 남았다

- **현재 역할:** [fleet/localization/map_pose.py](../../operations/fleet/fleet/localization/map_pose.py)는 `sys.modules`로 [World 구현](../../operations/world/src/rosy/world/state/projections/map_pose.py)을 연결하는 identity alias다.
- **문제와 근거:** `fleet.localization.map_pose` 문자열이 operations/tools/test의 추적 파일 35개에 남는다. 실제 소비자에는 `map_pose_service`, trip admission/progress/ports, swarm anchor와 시뮬 도구가 있다. 별칭은 중복 알고리즘이 아니지만 편집 위치를 Fleet으로 오인하게 한다.
- **최소 조치:** D-738 10에서 생산 호출자와 시험/monkeypatch 대상을 World import로 이전한 뒤 별칭을 제거한다. 별칭부터 지우지 않는다.
- **그대로 두면:** 이동이 끝난 구현을 Fleet에 다시 만들거나 단순 alias 제거로 소비자 import를 깨뜨릴 수 있다.

## 물리 잔여물·소유자 검토 필요

### 8. 옛 제품 경로가 캐시·도구 상태 때문에 소스처럼 남아 있다

- **현재 역할:** 옛 배치 경로의 잔여물이다. 아래 7곳에는 현재 추적 제품 파일이 없다.
- **문제와 근거:** 물리 파일 1,803개 중 `.pyc`는 1,715개다. 나머지에는 `.omc` 세션 JSON, pytest 캐시, lock·문서가 있다. `src`를 현재 소스라고 설명하는 입구와 만나면 실제 제품 트리로 오인된다.
- **최소 조치:** 생산자·활성 세션·파일 참조를 확인한 뒤 X: 세션 또는 도구 상태 정본으로 이관할 대상을 분리한다. 캐시만 있다는 이유로 `.omc`, lock, 로컬 기록까지 재귀 삭제하지 않는다.
- **그대로 두면:** 디스크 트리와 Git 트리의 차이가 계속 커지고 '이전 폴더가 아직 구현을 소유한다'는 오판이 반복된다.

| 물리 경로 | 파일 | `.pyc` | 추적 파일 |
|---|---:|---:|---:|
| `src` | 1,499 | 1,413 | 0 |
| `apps` | 2 | 2 | 0 |
| `modules` | 20 | 20 | 0 |
| `firmware` | 3 | 3 | 0 |
| `signal` | 3 | 3 | 0 |
| `middleware/core/api_web` | 118 | 116 | 0 |
| `middleware/apps/device` | 158 | 158 | 0 |

별도로 `build` 1,697개, `install` 1,500개, `log` 462개가 관측됐다. 생성/설치 결과이며 소스 중복으로 집계하지 않았다. 활성 overlay·실행 참조를 확인하기 전 이동/삭제 대상이 아니다. `.pytest-tmp-control` 56개, `.pytest_cache` 6개, `.ruff_cache` 15개도 X: 배치 원칙과 맞지 않지만 이번에는 건드리지 않았다. 숫자는 reparse target을 제외한 관측값이다.

### 9. `graphify-out`이 네 위치에 분산되어 있다

- **현재 역할:** 코드 그래프 분석 결과와 캐시다.
- **문제와 근거:** 우산 `graphify-out`에는 `.graphify_root`, manifest, HTML/JSON graph와 보고서가 있다. 제품 root와 `middleware`의 동명 경로는 각각 `cache/stat-index.json` 1개, `middleware/core/graphify-out`에는 JSON 407개가 있다. 범위·완성도가 서로 다른 결과이므로 같은 이름만으로 동일 산출물이라 할 수 없다. 제품의 세 경로는 추적 소스가 아니다.
- **최소 조치:** 각 분석 root·생산 세션·재사용 참조를 확인하고 X:의 해당 세션 export/evidence/cache로 이관한다. 다음 분석의 출력 위치도 함께 바로잡는다. 우산 `pidA`, `wsA.json`은 역할·생산자를 확인하지 못해 별도 HOLD로 남긴다.
- **그대로 두면:** 분석 실행 위치마다 결과가 누적되고 어느 그래프가 현재 범위의 결과인지 판단하기 어렵다. 이번 조사에서 프로세스 종료나 캐시 삭제를 하지 않았다.

### 10. worktree 반복은 중복 제품이 아니라 작업·보존 상태다

- **현재 역할:** Git에 등록된 브랜치별 작업 공간이다.
- **문제와 근거:** 관리 도구 스냅샷은 primary 1/task 249, dirty task 52, HOLD 155/REVIEW 95였다. local main에 포함된 HEAD는 131개, 포함되지 않은 HEAD는 119개다. Git lock 세 곳의 사유는 활성 배포·시험, 초기화, Fleet timing 비교다. `.worktrees/.omc`는 미등록 tool state로 HOLD다.
- **최소 조치:** 별도 정리 작업에서 소유 세션, 미커밋, branch/HEAD 보존, ancestry, ignored 로컬 데이터, 프로세스 사용, Git lock을 다시 확인한다. 기존 제거 도구와 정식 `git worktree remove`를 사용한다. REVIEW나 merged만으로 자동 제거하지 않는다.
- **그대로 두면:** worktree를 소스 복사본으로 취급해 작업을 잃거나, 반대로 종료된 작업까지 소유자 검토 없이 쌓아 둔다. 이번 인벤토리는 삭제 준비 완료 판정이 아니다.

### 11. 필수 `.worktrees` 안내 파일이 없다

- **현재 역할:** 작업 위치와 관리 명령의 입구여야 한다.
- **문제와 근거:** `F:\AGENTS.md`는 `.worktrees/AGENTS.md`, `.worktrees/README.md`를 먼저 읽도록 하지만 두 파일 모두 없었다. 저장소 `.gitignore`의 `.worktrees/` 규칙은 존재한다. '안내를 읽은 뒤 시작'의 전제만 현재 디스크와 맞지 않는다.
- **최소 조치:** 해당 안내 owner가 관리 도구의 `InitWorktrees`로 설치/갱신한다. 작업 checkout 내부나 archive에 AGENTS를 새로 퍼뜨리지 않는다. 이번에는 안내 설치도 실행하지 않았다.
- **그대로 두면:** 새 작업자가 경로 규칙을 찾지 못하거나 세션마다 서로 다른 방식으로 checkout과 임시 파일을 만든다.

## 중복으로 처리하지 않은 것

| 대상 | 확인한 이유 | 결론 |
|---|---|---|
| `archive`의 과거 소스·잘못된 경로 사본 | 동결 provenance라는 별도 계약 | 현재 제품 소스와 합치거나 안내를 갱신하지 않음 |
| `artifacts/releases`의 코드·AGENTS | 특정 소스 revision에서 만든 릴리스 payload | source와 비슷해도 release bytes/lineage 보존 |
| `control/{control,planning,safety,sensing,wander}` | 추적 파일은 initializer와 안내; source mapping이 실제 구현을 연결 | 삭제할 알고리즘 복사본이 아님 |
| `src/rosy`, `fleet/fleet`, Android `ui` | 언어 namespace 또는 설치 package | 바깥 holder 문제와 별개 |
| `test`, `config`, `resource`, `docs`, `api` 반복 | 패키지별 자원/계약/시험 관례 | 이름 반복만으로 위반 판정하지 않음 |
| `learning/.../perception` | 수집·학습·평가·registry는 다른 수명주기 | 데이터와 승인 권한을 합치지 않음 |
| 동일 시험 템플릿 3묶음 | bringup·pinky_led·face의 copyright/flake8/pep257 시험 | 패키지별 표준 검사. 공통화의 효과가 작음 |
| 동일 UI 시험 conftest 1쌍 | Pilot/Robot의 공통 browser harness 경로 bootstrap | 121행 proof 중복보다 낮은 우선순위. 새 abstraction을 만들 필요 없음 |

## 권장 처리 순서와 완료 기준

1. **현재 안내 정정:** 우산 README, archive의 현재 소스 안내, CORE/Fleet의 현재 UI 안내를 고친다. 역사 문서는 보존하고, 현재 작업용 로컬 링크의 실재 경로를 확인한다. missing `reference`는 삭제 owner의 의도를 확인한다.
2. **생성물 생산자 정리:** 옛 source cache와 graphify 결과를 생산자별로 분류한다. 종료된 대상만 X: 정본으로 옮기고 생성 도구의 출력 설정도 바꾼다. 활성 세션·DB·lock·overlay는 보존한다.
3. **D-738 단계 실행:** 1→10 순서를 유지한다. 한 단계마다 source mapping/manifest/설치·배포 소비/호출자/시험·안내를 함께 갱신하고 원격 검증을 얻은 뒤, 사용자가 착지를 요청했을 때만 local main에 반영한다. folder만 이동한 상태는 완료가 아니다.
4. **proof 중복 별도 판단:** 인증·서명·파일 permission 처리를 빠뜨리지 않는 최소 공유화 또는 동등성 가드를 선택한다. 121행 한 사본 제거는 가능한 상한이며 설치/호환 facade에 필요한 행을 제외한 실제 순감소량은 아직 계산하지 않았다. 새 dependency 제거 이득은 입증하지 않았다.
5. **worktree 별도 정리:** 최신 소유권·프로세스·lock·로컬 데이터 확인으로 후보를 확정한다. branch와 commit 복구 참조를 유지한다. 이 보고서의 250개 수치를 나중의 삭제 목록으로 쓰지 않는다.

**검증 범위:** 추적/물리 inventory, SHA-256 비교, 설치 source mapping과 정적 호출자 확인이다. 보고서의 로컬 근거 링크 17개, 집계 수치, proof 121행의 바이트 동일성 검사 PASS. harness generate는 `docs/index.md`만 갱신했고 lint는 exit 0, 오류 0/경고 28이었다. 경고는 모듈 `last_verified` 이후 변경 또는 uncommitted 검증 기준에 관한 것이며 이번 보고서로 해소하지 않았다. 명령 출력은 아래 X: 세션 로그에 보존했다. pytest·ROS graph·이미지 build·배포·실물/현장 수용은 수행하지 않았다. 따라서 단일 구현의 설치 독립성이나 실제 `/cmd_vel` 단일 publisher를 이번 조사로 인증하지 않는다.

**증거 위치:** `X:\DevTemp\projects\rosy-platform\2026-10-13--115930--folder-responsibility-audit--deea14`

- `evidence/tracked-inventory.json`: 기준 SHA, 97종 전체 반복 이름/경로, 동일 파일 5묶음, root coverage.
- `evidence/physical-inventory.json`: 옛 경로·생성물 수량, graphify 범위, Git 등록·lock.
- `evidence/worktrees.json`: 관리 도구의 시각이 고정된 전체 worktree 상태. 세션·프로세스/lock 완전 검증 자료는 아님.
- `export/repeated-folder-names.csv`: 반복 이름 전체 조회표. 후보 목록이며 결함·삭제 목록이 아님.
- `export/2026-10-13-folder-responsibility-audit.md`: 이 보고서의 읽기용 사본.

**미확인:** 모든 보관/릴리스 바이트의 동일성, AST 기반 유사 코드 탐지, 실제 프로세스 사용과 삭제 적격성, 시험·장치·현장 검증. **위험:** 이름만으로 통합/삭제하거나 설치 alias를 먼저 없애면 실행 경계와 진행 작업을 잃을 수 있다.
