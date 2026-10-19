## D-798 한도에 걸린 크기 단위는 미리 나눠 여유를 만든다 — fleet·site_ui/console·rosy_auto_update 분할 지도, 95% 선, 상속된 초과 커밋의 재적층

**Status:** Accepted (2026-10-18, 사용자 결정: 분할을 실행한다). D-766을 약하게 하지 않는다. 한도, ratchet, 커밋마다 녹색 규칙은 그대로다. 이 ADR은 그 규칙 아래에서 막힌 단위에 실제 여유를 만드는 분할 지도와 순서를 정한다. 각 분할은 4항의 순서대로 한 단계 한 브랜치로 착지한다.

### Context

2026-10-18 네트워크 부하·WebRTC 작업이 D-766 크기 검사(`tools/harness/size_range.py`, `tools/land.py`가 원격 시험 전에 돌림) 때문에 몇 시간 늦었다. 배경과 다른 막힘은 `docs/solutions/workflow-issues/landing-blockers-cost-hours-2026-10-18.md`에 있다.

1. **이미 넘은 단위는 순증을 하나도 받지 못한다.** `fleet` 패키지 16,499줄(한도 10,000), `site_ui/console` 11,317줄, `rosy_auto_update.py` 1,591줄(600), `test/test_rosy_auto_update.py` 2,632줄(1,500), `trip_runner.py` 899줄은 ratchet에 묶여 있다. `trip_ports.py`는 정확히 600줄이다. 고칠 것이 이 단위에 있으면 고친 만큼 다른 곳에서 지워야 했다.
2. **일부만 나누면 여유가 생기지 않는다.** D-766 4항대로, 떼어 낸 만큼 천장이 같이 내려간다. 동작을 지키는 부분 분할을 해도 그 단위에 더할 자리는 생기지 않았다. 그래서 수정 하나를 새 모듈 여러 개로 비틀어 넣었고, 계획했던 jitter 변경 하나는 뺐다.
3. **앞 세션의 커밋을 뒤 커밋으로 고칠 수 없었다.** 앞 세션 브랜치에서 이어받은 커밋 하나가 단위를 한도 위로 키웠다. `size_range.py`는 커밋마다 따로 재므로 같은 브랜치의 나중 커밋으로는 고쳐지지 않는다. 새 브랜치에 다시 쌓아야 했다(재적층).

### Decision

1. **목표는 85%다.** 분할은 나온 단위와 파일이 모두 한도의 약 85%(단위 8,500줄, 제품 파일 510줄, 시험 파일 1,275줄) 아래가 되게 한다. 한도 바로 아래로만 나누면 다음 변경에서 다시 막힌다.
2. **95% 선에서는 나누기를 먼저 착지한다.** D-766 2항의 "95% 이상은 더하기 전에 나눈다"를 브랜치 단위로 적용한다. 한도의 95% 이상인 파일(570줄, 웹 760줄)이나 단위(9,500줄)에 더할 일이 있으면, 그 나누기를 따로 된 브랜치로 먼저 착지하고 기능 브랜치는 그 위에서 시작한다. 한 브랜치 안에서 나누기 커밋을 앞에 두는 것은 허용되지만, 나누기 브랜치가 따로 착지하면 다른 세션도 바로 그 여유를 쓴다.
3. **분할 지도(제안).** 아래 줄 수는 2026-10-18 작업 트리를 D-766 계산기로 잰 값이다. 3.3~3.5의 메서드 범위는 함수 목록에서 읽은 대략값이다. 각 분할은 D-766 3항의 경계 검토(한 책임, 새 단위 1,000줄 바닥)를 따로 받는다.
   1. **`fleet` 패키지 16,499 → 약 7,960.** `fleet/server/__init__.py`가 `fleet/_source_layout.py`의 `SERVER_HOLDERS` 폴더를 모두 `fleet.server.__path__`에 더한다. 그래서 `server/<폴더>/x.py`도 `fleet.server.x`로 import 되고, 옮겨도 import를 고칠 필요가 없다. 옮기기 하나는 `git mv`, `SERVER_HOLDERS` 항목 하나, `size_units.txt` 한 줄, 경로 문자열 수정이다. 이미 있는 폴더(`server/peer` 759, `meet` 644, `hub` 470)는 모두 1,000줄 바닥 아래라서, 코드를 옮기지 않고 등록만 해서 되는 것은 없다.

      | 순서 | 새 holder 단위 | 파일 | 줄 | 뒤의 fleet | 고칠 경로 문자열 |
      |---|---|---|---|---|---|
      | 1 | `server/evidence` | proposal_store, model_feedback_dispatch, goal_evidence_{registry,service,store}, policy_evidence(+_config), learning_{bundle,receiver}, deliberation_journal, incident_deliberation | 2,416 | 14,083 | proposal_store ratchet 행, `test/test_judgment_extraction.py`, `operations/fleet/test/test_task_contract_docs.py` |
      | 2 | `server/sitemap` | site_map_store, site_map_routes, teach_service, teach_routes, site_lanes, lane_route_routes, path_history, start_points, start_point_routes | 1,652 | 12,431 | 찾지 못함 |
      | 3 | `server/pose` | localization_service, map_pose_service, lane_compliance_service | 1,180 | 11,251 | `localization_service.py`의 `parents[4]` → `parents[5]`, `test_boundaries.py`, `test_shared_state_read.py` |
      | 4 | `server/recognition` | identity, identity_triggers, sightings, sightings_config, sighting_store, ingest_routes, address_drift, discovery, roster | 1,685 | 9,566 | `test_boundaries.py` |
      | 5 | `server/rightofway` | signals, signal_config, signal_routes, junction_signal, traffic, traffic_reservations, segment_store, bays | 1,606 | **7,960 (80%)** | `test/robot_literal_backlog.txt` |
      | 선택 | `server/dispatch` | step_dispatcher, step_action_kinds, local_{action,stop}_transport, cancel_all(+_store), dispatch_admission, intent_execution, intent_routes, goal_lease, tether_watch, tether_routes | 2,018 | 5,942 | safety 태그: `platform_parts.yaml`, `test_safety_separation.py`. D-430 검토가 필요해 맨 뒤 |

      위에 남는 것은 `app.py`(962, 묶인 파일), `cli.py`(923, 묶인 파일), `http_errors.py`, `sqlite_policy.py`, `background_workers.py`, `host_control_routes.py`, `guide_service.py`와 `channel_*` 별칭 파일이다. 이 모듈들을 import 하는 것은 `app.py`, `cli.py`와 형제 단위(`server/console`, `missions`, `ledger`, `tracking`)뿐이다.
   2. **`site_ui/console` 11,317 → 약 6,460.** 페이지는 자산을 공개 이름 `/console/assets/<name>`으로 읽는다(`server/console/static_routes.py`의 `CONSOLE_ASSETS`). 옮기기는 새 폴더, `git mv`, `CONSOLE_ASSETS`의 상대 경로(`.html`이면 페이지 경로도), `operations/fleet/test/web/*.mjs`의 파일 경로 수정이다. JS import와 URL은 바뀌지 않는다.
      - `sitemap/`(1,596): site-map.html·.js·.css, site-map-teach/survey/camera.js. 페이지 경로는 `static_routes.py`의 site-map 행.
      - `install/`(1,358): install.html·.js, host-services.js, camera-peer.js, peer-picker.js, start-point-view.js, tracking-relearn.js.
      - `map/`(1,903): map-view.js, camera-backdrop.js, camera-warp.js, site-layer.js, trail-view.js, traffic-view.js, tracking-layer.js, map-datum.js, start-point-layer.js. 앞의 둘만으로는 8,363(84%)이라 이것까지 한다.
      - 나중에 쓸 수 있는 묶음: `roster/`(1,562), `attention/`(line-stuck.js, incident-view.js, inbox.js, 1,223).
      - 넘은 파일: `console.js`(981)는 인증·잠금(console-auth.js), 목표 지정(console-goal.js), 새로고침 루프(console-refresh.js)로 나눠 약 400줄이 남는다. `map-view.js`(952)는 덧그림(map-overlays.js)과 폴링(map-polling.js)으로 나눠 약 310줄이 남는다. `line-stuck.js`(756)는 문구 함수(line-stuck-text.js)를 뗀다. `site-map.js`(771)는 profile과 plan/plane을 뗀다. `roster.js`(709)는 `card()` 하나가 약 480줄이라 그 안부터 나눈다. 각 파일은 `size_limits.COVERAGE_ROWS`의 행을 같이 고치거나 지운다.
   3. **`rosy_auto_update.py` 1,591.** 로봇은 `python3 -I -B /opt/rosy/native-runtime/rosy_auto_update.py`로 돌린다. 이 파일은 이미 자기 폴더를 `sys.path`에 넣고 형제 `rosy_claim`을 import 한다. `install-native-runtime.sh`는 `native/` 폴더 전체를 복사하고 `sync-image-layer.py`도 그 폴더의 모든 파일을 옮긴다. 그래서 형제 모듈로 나눠도 배포 목록은 바뀌지 않는다. 메서드는 `Updater`의 mixin으로 옮긴다.
      - `auto_update_host.py`(약 350): 상수, 오류, `_z`·`_tail`·`_outcome`, `Host`, `Http`, JSON 읽기·쓰기.
      - `auto_update_records.py`(약 330): 상태·marker·`_face_swap`·이력·`_finish`·설정, hold/release, `_sealed`, `precheck`, `eligibility`.
      - `auto_update_stage.py`(약 190): backoff, release 목록, rollout, stage, 다운로드 정리, gate.
      - `auto_update_apply.py`(약 335): systemctl부터 settle, 되돌리기, native 복구, prune, `apply`, `_core_down`.
      - `rosy_auto_update.py`(약 390): `Updater` 본체와 경로, resume, 잠금, `run`, `main`.
      - 고칠 것: `test/test_native_systemd_contract.py`의 유닛 파일 목록, 시험의 monkeypatch 대상 셋(`upd.Host`, `upd.API_BASE`, `upd.HISTORY_MAX_BYTES`). 열린 질문: `sync-image-layer.py`가 native-runtime 파일을 한 번에 바꾸는지 확인한다. 아니면 동기화 중 꺼진 로봇에 서로 다른 판의 모듈이 남을 수 있다. 실기 확인이 필요해 맨 뒤에 한다.
        - 답(2026-10-19): 한 번에 바꾸지 않는다. 파일마다 `os.replace`하고(`_install`), manifest의 `files_applied`로 기록해 다음 sync의 `reconcile()`이 마무리하거나 되돌린다. 그 다음 sync는 보통 이 updater가 부르므로, 섞인 형제 때문에 import가 실패하면 아무도 고치지 못한다. 그래서 `rosy_auto_update.py`는 `/opt/rosy/native-runtime`에서 실행될 때 import 실패를 받으면 활성 릴리스의 `sync-image-layer.py`를 한 번 돌리고 다시 실행한다(`ROSY_AUTO_UPDATE_RESYNCED`로 한 번만, `test/test_rosy_auto_update_resync.py`). import는 되지만 판이 섞인 경우는 막지 못한다. 실기 전원 차단 확인은 아직 하지 않았다.
   4. **`test/test_rosy_auto_update.py` 2,632.** 가짜와 fixture는 `test/auto_update_fakes.py`(약 380, `test/fake_core_ssh.py`와 같은 방식). 시험은 3.3의 경계대로 `_check`(설정·GitHub·stage·gate·네트워크, 약 420), `_eligibility`(약 500), `_apply`(기록·유닛·prune·D-433 표시, 약 615), `_resume`(resume·core-down 면제·되돌리기 검토, 약 650)로 나눈다. `COVERAGE_ROWS`의 행을 지운다.
   5. **trip 파일.** `trip_ports.py`(600)에는 port, `HttpLaneJunction`, `TripConfig`, `TripError`(약 225줄, 39개 파일이 import)를 남기고 굽은 길·교차로 기하는 `trip_geometry.py`로, `LiveTrip`은 `trip_live.py`로 옮긴다(약 10개 import 수정). `trip_runner.py`(899)는 이미 mixin(`TripAdmission`, `TripProgress`)을 쓴다. `_step`부터 `_step_free`까지(약 310줄)를 `TripSteps` mixin으로, 재계획·AI 확인·바퀴 수 부분을 `TripReplan`으로 옮겨 약 470줄을 남긴다.
   6. **`core_features` 단위(후보).** 2026-10-18 main 머지 뒤 10,000/10,000줄로 한도에 딱 닿았다(`docs/solutions/workflow-issues/landing-blockers-cost-hours-2026-10-18.md` 5절). 다음 순증은 어디서든 나누기가 먼저다. 분할 지도는 아직 없다. 이 단위에 더할 일이 생기면 그 세션이 먼저 지도를 이 절에 적고, 나누기 브랜치를 따로 착지한다. 이 후보는 4항 순서의 (1)~(5) 뒤가 아니라 필요해지는 때에 한다.
      - 실행(2026-10-19, `refactor/core-features-split`): `middleware/drive/behaviors/docking`(2,190줄)을 `test/architecture/size_units.txt`에 단위로 등록했다. 이미 형제 `line_follow`·`navigation`·`localization`·`swarm`이 같은 방식으로 등록된 D-649 소스 holder이고, `core_features.docking` 자기 모듈만 import하며, 모듈 docstring과 `core_features/AGENTS.md` 행이 이미 있다. 파일을 옮기지 않아 import와 설치 경로는 그대로다. `core_features`는 10,000에서 7,810줄(78%)이 되고 docking 단위는 2,190/10,000이다. 다음 후보는 같은 조건을 갖춘 `core_features/power`(1,264줄, 자기 모듈만 import)다.
4. **순서.** (1) fleet holder 1→5. 기계적인 이동이고 import 수정이 없다. (2) console `sitemap/`, `install/`, `map/`. (3) `trip_ports`, 다음 `trip_runner`. (4) console의 넘은 파일. (5) `rosy_auto_update`와 그 시험(실기 확인). 단계마다 ratchet 행을 잰 값으로 고치고, 옮긴 파일의 행은 새 키로 옮기며(D-766의 rename 규칙), 한도 아래가 된 행은 지운다. 한 단계가 한 브랜치다. 한 단계 브랜치는 이동만 하고 동작을 바꾸지 않는다(D-766 3항의 순수 이동 검토).
5. **상속된 초과 커밋의 재적층.** `size_range.py main HEAD`가 이 브랜치에 앞 세션에서 이어받은 커밋을 적색으로 찍으면, 그 브랜치의 나중 커밋으로는 고칠 수 없다. 공유 체크아웃에서 rebase나 amend는 하지 않는다(「같이 하는 깃」 2항). 절차는 다음이다.
   1. `python tools/harness/size_range.py main HEAD`로 적색 커밋과 단위를 확인한다.
   2. `python tools/worktrees.py new <이름>-restack <type>/<topic>-restack`로 `main`에서 새 워크트리를 만든다.
   3. 적색 단위를 키우지 않는 커밋은 `git cherry-pick <sha>`로 그대로 옮긴다. 적색 커밋은 `git cherry-pick -n <sha>`로 가져와 같은 커밋 안에 그 단위의 나누기(또는 같은 단위에서 그만큼 지우기)를 넣고 커밋한다. 단위를 키운 뒤 나중 커밋에서 나눈 짝은 하나로 합친다. 이 브랜치에 필요 없는 남의 커밋은 가져오지 않는다.
   4. `size_range.py main HEAD`가 녹색이면 새 브랜치로 `tools/land.py`를 돌린다. 옛 브랜치는 지우지 않는다. 커밋된 채 두고, 소유자에게 대체한 브랜치 이름을 알린다.

### D-427·D-429·D-430과의 관계

| ADR | 관계 |
|---|---|
| D-427 (세 부분 배치) | 새 최상위 폴더가 없다. 새 holder와 폴더는 모두 기존 root(`operations/fleet`, `operations/site_ui/console`, `deploy/robot/pinky_pro/native`) 안이다. |
| D-429 (다섯 관심사) | 관심사 경계를 바꾸지 않는다. 각 holder는 한 관심사 안의 한 책임이다. |
| D-430 (안전 분리) | `server/dispatch`는 safety 태그 파일을 옮기므로 맨 뒤에 하고, `platform_parts.yaml`의 `safety_modules`·`safety_anchors`를 같은 커밋에서 옮기고 `Safety-Review:` trailer를 단다. 나머지 단계는 safety 경로를 건드리지 않는다. |

### Alternatives

- **한도를 올리거나 ratchet에 여유(+N)를 준다.** D-766이 일부러 없앤 것이다(Alternatives, 5항). 하지 않는다.
- **막힐 때마다 그 변경을 새 모듈로 비틀어 넣는다.** 오늘 한 방식이다. 책임이 흩어지고 다음 변경도 같은 비용을 낸다.
- **fleet를 새 패키지 여러 개로 나눈다.** 패키징, `colcon_roots`, 설치 경로, CI 행렬을 같이 바꿔야 한다. holder 폴더는 import도 설치도 바꾸지 않고 같은 줄 수 효과를 낸다.

### Consequences

- 1~2단계 뒤 fleet와 console은 15~20%의 여유를 가진다. 그 동안 다른 세션의 브랜치는 옮긴 파일 경로와 충돌할 수 있다. 각 단계를 한산한 착지 창에 짧게 착지하고, 착지 전에 「같이 하는 깃」의 동료 확인을 한다.
- ratchet 행 키가 옮긴 파일의 새 경로로 바뀐다. 진행 중 브랜치는 main을 머지할 때 그 행을 새 키로 푼다.
- 이 ADR은 도구를 바꾸지 않는다. 95% 선은 D-766에 이미 있는 규칙을 브랜치 순서로 적은 것이다.

### Validation

- 단계마다 `python tools/harness/size_range.py main HEAD`가 녹색이고, `test/architecture/test_module_structure.py`와 옮긴 단위의 시험이 시험 PC에서 0 NEW이다.
- 1단계 뒤 계산기로 잰 fleet 자체 줄 수가 8,500 이하이고, `size_ratchet.txt`에서 `fleet` 행이 지워진다.
- 재적층 절차는 다음 번 상속 적색에서 그대로 써 보고, 맞지 않으면 이 절을 고친다.

**References:** D-766(4항 일부 분할은 여유가 없다, 2항 95%), D-763(Fleet 서버 holder 단위), D-436, D-584, D-790, D-172(새 브랜치로 다시 만들기), D-372, `docs/solutions/workflow-issues/landing-blockers-cost-hours-2026-10-18.md`, `docs/plans/2026-10-14-fleet-console-size-unit.md`, `operations/fleet/fleet/_source_layout.py`, `test/architecture/size_ratchet.txt`, `test/architecture/size_units.txt`.
