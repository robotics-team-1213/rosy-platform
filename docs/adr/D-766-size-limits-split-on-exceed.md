## D-766 줄 수 한도는 넘으면 나눈다 — 파일 600줄(웹 800), 크기 단위 10,000줄, 다시 자랄 허용(+150)은 없다

**Status:** Proposed (2026-10-15). 사용자가 2026-10-15에 "코드가 몇 줄을 넘으면 나눈다 — 기준을 잡아라"라고 요청했다. 이 ADR은 D-168 P6의 판정(`split:`/`accept:`)과 +150 재판정, D-362의 1,000줄 등급을 이 규칙으로 바꾸자고 제안한다. 아직 승인되지 않았다. 시험과 문서 변경은 아래 조각마다 따로 착지한다. 이 브랜치는 ADR과 Log 행만 바꾼다.

### Context

D-168 P6은 제품 파일 600줄, 패키지 10,000줄을 예산으로 두고, 넘으면 `SIZE_VERDICTS`에 `split:` 또는 `accept:` 판정을 적게 한다. 판정 시점의 줄 수가 기준선이 되고, 그 위로 150줄(`REGROWTH_ALLOWANCE`)까지 자랄 수 있다. 1,000줄 넘는 파일은 허용이 0이다(D-362, `HARD_TIER`). 패키지 안의 하위 패키지는 `SIZE_UNITS`에 등록하면 자기 단위로 세어지고, 등록된 단위는 크기와 상관없이 늘 판정을 하나 가지며 판정값 +150이 한도다.

이 장치가 지금 만드는 문제는 다음과 같다. 숫자는 모두 main `c1def3006`에서 시험의 `_over_budget()`과 `_allowance()`를 그대로 불러 쟀다(읽기 전용).

1. **나누면 허용이 생긴다.** 새 단위마다 +150이 붙으므로 나누기가 여유를 얻는 길이 됐다. 2026-10-14와 10-15 이틀 동안 Fleet에서 새 크기 단위가 일곱 개 생겼다: `site_ui/console`, `fleet/fleet/server/ledger`(main, `docs/plans/2026-10-14-fleet-console-size-unit.md`, `2026-10-14-fleet-ledger-size-unit.md`), `site_ui/console/work`, `fleet/fleet/server/missions`, `fleet/fleet/server/work`, `fleet/fleet/server/trips`, `fleet/fleet/server/trip_checks`(착지 전 브랜치 `feat/fleet-work-read-sources`, 2026-10-15 날짜 계획 셋). 합친 한도는 그때마다 150씩, 모두 1,050줄 늘었다. 그런데도 그 브랜치 끝에서 `site_ui/console`은 한도까지 2줄, `trip_checks`는 17줄 남았다. 계획 문서는 스스로 "이 등록은 실패하는 시험을 넘기려는 것이다"라고 적는다(`2026-10-15-fleet-console-work-unit.md`).
2. **작은 단위가 큰 단위보다 더 묶인다.** 단위의 한도는 10,000줄이 아니라 판정값 +150이다. `drive/behaviors/swarm`은 949줄인데 한도가 949이고, `decision/.../deliberation/contracts`는 382줄인데 한도가 382다. 등록된 38개 단위 가운데 25개가 1,000줄 아래이고 19개가 500줄 아래다.
3. **변경마다 산수를 한다.** main의 98개 판정 가운데 22개가 한도까지 20줄 이하다(그 가운데 단위 11개). 날짜 계획은 줄 수를 판정 커밋, 브랜치 기점, 지금으로 나눠 다시 재고, "쓴 허용"과 "남은 허용"을 계산하고, 판정 문구 앞에 줄을 붙이고, 독립 재판정을 받는다. 착지 순서도 이 여유에 맞춰 정해졌다. `SIZE_VERDICTS`는 `test_module_structure.py` 2,422줄 가운데 1,836줄(137–1972행)이다. 이 시험 파일은 2026-10-14 이후 main에서만 9번 바뀌었다.
4. **판정이 실제 크기를 따라가지 않는다.** `control`은 판정 35,183에 지금 30,125다. 줄어든 5,058줄만큼 다시 자랄 수 있다. `fleet/fleet/localization`도 판정 1,707에 지금 1,267이다.

D-168은 "예산 초과를 곧바로 분리 의무로 두는 안"을 Alternatives에서 기각했다. `docking/manager.py`(그때 511줄, 단일 소유)처럼 나눌 이유가 없는 파일에 억지 경계를 만든다는 이유였다. 이 ADR은 사용자의 지시로 그 기각을 뒤집는다. 억지 경계 걱정에 대한 답은 결정 3항과 4항이다.

### Decision

1. **한도는 절대값이고 다시 자랄 허용은 없다.** 제품 파일(`.py`/`.cpp`/`.hpp`/`.sh`, D-362의 범위 그대로) 600줄, 웹 자산(`.js`/`.html`/`.css`) 800줄, 크기 단위(패키지 또는 `SIZE_UNITS`에 등록한 하위 패키지) 10,000줄이다. 이 값은 기준선이 아니라 천장이다. 판정 시점 줄 수와 +150은 없다. 줄 수는 지금처럼 물리 줄(빈 줄과 주석 포함)이고 세는 방법은 `_over_budget()` 그대로다.
2. **넘으면 나눈다.** 어떤 파일이나 단위를 한도 위로 올리는 변경은, 같은 변경 안에서(또는 그보다 앞선 변경으로) 그것을 나눠 나온 파일과 단위가 모두 한도 아래가 되게 한다. 새로 넘는 것에 `accept`는 더 쓰지 않는다. 나누지 않는 길은 하나다: 같은 파일이나 단위 안에서 지워서 한도 아래에 머무는 것이다.
3. **나누기의 조건(억지 경계를 막는다).** 줄 수는 언제 나눌지를 정하고, 어디서 나눌지는 정하지 않는다. 경계는 `docs/plans/2026-09-06-module-split-criteria.md`의 C1(host로 시험 못 하는 결정), C2(서로 다른 생명주기), C5(서비스 주인이 둘인 API 모듈), B(B1–B3 하위 패키지 자격) 가운데 무엇이 발화했는지로 고른다.
   - 여유를 만들려고 관련 없는 파일을 다른 폴더로 옮기지 않는다. 옮긴 묶음은 그 자체로 한 책임이어야 한다.
   - 새 단위는 모듈 독스트링(또는 `__init__.py`의 한 줄)과 그 패키지 `AGENTS.md`의 행을 가진다.
   - **새 단위의 바닥은 1,000줄이다.** 등록할 때 1,000줄 아래인 하위 패키지는 단위가 아니라 부모 안의 하위 패키지로 센다. 1,000줄은 한도의 10%다. 그보다 작은 조각은 넘은 패키지를 한도 아래로 되돌리지 못하고, 오늘 단위 38개 가운데 25개가 그 아래에 있어 등록부만 늘렸다.
   - **나누기로 새로 만든 파일의 바닥은 150줄이다.** 150줄 아래로 떼어 내면 옛 허용 한 번보다 적은 여유를 위해 경계를 하나 만든 것이다. 이 바닥은 시험이 어느 파일이 나누기에서 나왔는지 알 수 없으므로 검토가 본다. 이미 이름이 붙은 역할(예: 앞서 떼어 둔 mixin) 하나를 통째로 옮기는 것은 예외로 본다.
   - 독립 검토는 경계를 본다(어느 기준이 발화했는지, 옮긴 것이 한 책임인지). 줄 수 산수는 시험이 본다.
   - 어느 기준도 발화하지 않으면 그 파일이나 단위에는 더 넣지 않는다. 새 코드는 자기 책임을 가진 다른 자리에 두거나, 같은 곳에서 그만큼 지운다. `docking/manager.py` 같은 파일은 자라지 않는 한 나눌 일이 없다(4항).
4. **이미 넘은 것은 지금 줄 수로 묶는다(ratchet).** 이 규칙의 시험 조각이 착지하는 커밋에서 잰 줄 수가 그 파일·단위의 천장이 된다. 줄어들 수는 있고, 줄면 천장도 새 줄 수로 내려간다. 다시 올라가지 않는다. 그것을 키우는 변경은 먼저 그것을 나눠 절대 한도 아래로 만든다. 일부만 떼어 내면 천장이 떼어 낸 만큼 내려가므로 여유가 생기지 않는다. 같은 곳에서 더하고 지워 순증이 0 이하인 변경은 된다. 오늘 목록은 아래 「오늘 넘은 것」 표다.
5. **없애는 것과 남기는 것.**
   - 없앤다: 판정 문구(`split:`/`accept:`)와 판정 시점 줄 수, `REGROWTH_ALLOWANCE`, `_allowance()`, 한도 아래 단위의 판정, 숫자 재판정, 날짜 계획의 기준선 표.
   - `HARD_TIER`(1,000줄, 허용 0)는 없앤다. 넘은 파일은 모두 4항에 따라 증가가 0이므로 따로 둘 이유가 없다. 새 파일은 600·800줄에서 이미 막힌다.
   - 남긴다: 시험 파일 면제(X4), 웹 800줄(D-362: 마크업 오버헤드, 웹 파일 184개의 p90이 538줄), `SIZE_UNITS`와 가장 안쪽 단위가 줄을 가져가는 셈, Fleet 서버 보관 자리 단위(`FLEET_SERVER_HOLDER_UNITS`, D-763), 운영 루트(`OPS_ROOTS`) 범위, P5의 집합 동일성.
6. **오늘 진행 중인 브랜치.** 이 ADR의 시험 조각(7(a))이 착지하기 전까지는 지금 규칙이 그대로다. 그 전에 착지하는 브랜치(지금 `test_module_structure.py`를 바꾸는 진행 중 브랜치는 `feat/fleet-work-read-sources` 하나다)는 그 날짜 계획과 판정 그대로 착지한다. 그 브랜치가 만든 1,000줄 아래 단위(`site_ui/console/work`, `fleet/fleet/server/work`, `fleet/fleet/server/trip_checks`)는 이미 있던 작은 단위와 함께 7(a)의 기존 작은 단위 목록에 든다. 7(a)는 착지하는 날의 main에서 표를 다시 만든다. 7(a) 뒤에 main을 머지하는 브랜치는 `SIZE_VERDICTS` 충돌을 7(a)의 표로 풀고 자기 줄 수만 다시 잰다. 날짜 계획 문서는 기록으로 남고 고치지 않는다. 누구의 작업도 이 ADR 때문에 무효가 되지 않는다.
7. **구현 조각.**
   - (a) **시험.** `test/architecture/test_module_structure.py`에서 `SIZE_VERDICTS`를 `FROZEN_OVER_LIMIT = {경로나 단위: 줄 수}`로 바꾼다. 착지하는 커밋에서 생성하고 문구는 없다. 검사는 셋이다. 한도를 넘은 것의 집합이 `FROZEN_OVER_LIMIT`의 키와 같다(새로 넘은 것도, 한도 아래로 내려간 항목도 적색). 넘은 것은 표의 줄 수를 넘지 않는다. 표의 줄 수보다 줄었으면 같은 변경에서 표를 내린다(집합 동일성과 같은 장치로, 표가 실제보다 높으면 적색). 등록 단위는 `UNIT_FLOOR = 1_000` 이상이다. 오늘의 작은 단위는 `SMALL_UNITS` 집합(집합 동일성)에 둔다. 작은 단위가 바닥 아래로 줄면 부모에 여유가 있을 때 같은 변경에서 부모로 합치고, 부모가 묶여 있으면 `SMALL_UNITS`에 넣는다. `REGROWTH_ALLOWANCE`, `HARD_TIER`, `_allowance()`를 지운다. 단위의 "분리 계획 인용" 검사는 바닥 검사로 바꾼다. 변이 증명(새 초과 주입, 묶인 것 1줄 증가, 바닥 아래 단위 등록 → 적색 → 복구 → 초록)을 거친다. 이 파일은 FULL 등급 시험이라 착지 창을 디스패처와 맞춘다. 시험은 `tools/remote/remote_pytest.py`로 시험 PC에서 돌린다.
   - (b) **문서.** D-168 P6과 D-362에 "D-766이 대체한다"는 한 줄, 분리 기준 문서의 X1 각주와 D-168 Alternatives 문장, `test/architecture/AGENTS.md`의 행을 고친다. 이 ADR이 Accepted가 될 때 D-168 P6을 이 ADR로 가리킨다.
   - (c) **첫 강제 분리.** 묶인 것 가운데 다음에 자랄 곳을 먼저 나눈다. 한도를 조금 넘은 단위가 먼저다: `perception/front_camera/perception`(75줄 초과), `core_common`(643줄), `dashboard`(1,085줄). 각각 날짜 계획 하나와 경계 검토 하나로 한다. 이 조각들은 자라야 할 때 시작하고, 이 ADR이 일정을 정하지 않는다.

### 오늘 넘은 것

main `c1def3006`, `_over_budget()` 그대로. 이 62개가 4항의 ratchet 대상이다. 7(a)는 착지하는 날 다시 잰다.

| 패키지·단위 | 줄 수 | 한도 | 한도 아래로 가려면 나눌 줄 |
|---|---|---|---|
| `fleet`(서버·decision·discord 보관 자리, 등록 단위 제외) | 31,904 | 10,000 | 21,904 |
| `control` | 30,125 | 10,000 | 20,125 |
| `site_ui/console`(단위) | 18,082 | 10,000 | 8,082 |
| `dashboard` | 11,085 | 10,000 | 1,085 |
| `core_common` | 10,643 | 10,000 | 643 |
| `perception/front_camera/perception`(단위) | 10,075 | 10,000 | 75 |

`feat/fleet-work-read-sources` 끝(`bbf8acb33`)에서는 `fleet` 31,846, `site_ui/console` 17,717이다. 등록 단위를 모두 합친 Fleet 쪽 총합은 71,481줄이다.

파일 56개(제품 코드 1,653개 가운데 600줄 초과 47개, 웹 자산 184개 가운데 800줄 초과 9개). 경로는 colcon 루트 또는 저장소 루트 기준이다.

| 파일 | 줄 수 | 한도 |
|---|---|---|
| `perception/web/diagnostic.html` | 1857 | 800 |
| `deploy/robot/pinky_pro/native/rosy_auto_update.py` | 1591 | 600 |
| `foundation/core_common/protocol/schemas.py` | 1359 | 600 |
| `fleet/fleet/server/console/console.py` | 1325 | 600 |
| `deploy/robot/pinky_pro/native/rosy-face.py` | 1273 | 600 |
| `devices/omx/adapter/omx_adapter/action_store.py` | 1141 | 600 |
| `site_ui/console/console.js` | 1080 | 800 |
| `deploy/robot/pinky_pro/native/sync-image-layer.py` | 1023 | 600 |
| `fleet/fleet/server/ledger/task_store.py` | 1014 | 600 |
| `fleet/fleet/server/app.py` | 983 | 600 |
| `fleet/fleet/server/cell/cell_job_store.py` | 963 | 600 |
| `robot_ui/pilot/styles.css` | 956 | 800 |
| `site_ui/console/map-view.js` | 952 | 800 |
| `web/components.css` | 943 | 800 |
| `fleet/fleet/server/ledger/mission_store.py` | 936 | 600 |
| `fleet/fleet/cli.py` | 923 | 600 |
| `core/gateway/core/bridge/ros_bridge.py` | 908 | 600 |
| `robot_ui/robot/app.js` | 898 | 800 |
| `fleet/fleet/server/ledger/trip_runner.py` | 898 | 600 |
| `overhead/rosy_vision/ingest.py` | 869 | 600 |
| `site_ui/console/shared/styles.css` | 862 | 800 |
| `deploy/robot/pinky_pro/native/rosy-ssh-access.py` | 862 | 600 |
| `tools/harness/rosy_harness.py` | 858 | 600 |
| `simulation/gazebo/scripts/lane_live_view.html` | 856 | 800 |
| `drive/motion_limits/adapter/node.py` | 847 | 600 |
| `fleet/fleet/server/auth/enrollment.py` | 847 | 600 |
| `drive/behaviors/line_follow/manager.py` | 822 | 600 |
| `deploy/robot/pinky_pro/image/first-boot/rosy-first-boot.py` | 817 | 600 |
| `deploy/robot/pinky_pro/release/secret_scan.py` | 815 | 600 |
| `web/ui.js` | 814 | 800 |
| `deploy/robot/pinky_pro/sd/verify-media-readback.py` | 806 | 600 |
| `fleet/fleet/server/proposal_store.py` | 797 | 600 |
| `drive/behaviors/docking/manager.py` | 788 | 600 |
| `perception/front_camera/perception/lane.py` | 771 | 600 |
| `learning/curation/perception/review_app.py` | 756 | 600 |
| `perception/sensors/line_observation/line_observer_node.py` | 755 | 600 |
| `tools/perception/rosy_ml.py` | 749 | 600 |
| `core/events/core_events/events/audit.py` | 748 | 600 |
| `devices/omx/adapter/omx_adapter/pose_plan.py` | 728 | 600 |
| `perception/front_camera/perception/lane_bev.py` | 717 | 600 |
| `simulation/gazebo/scripts/lane_live_view.py` | 709 | 600 |
| `tools/device_twin/scenarios.py` | 703 | 600 |
| `deploy/site/rosy_model_code.py` | 698 | 600 |
| `tools/release/publish_payload_release.py` | 697 | 600 |
| `devices/omx/adapter/omx_adapter/command_owner.py` | 696 | 600 |
| `drive/behaviors/swarm/manager.py` | 691 | 600 |
| `deploy/robot/pinky_pro/release/updater.py` | 686 | 600 |
| `learning/curation/perception/lane_derived_drivable.py` | 678 | 600 |
| `robot_ui/face/emotion/info_screen.py` | 676 | 600 |
| `deploy/robot/pinky_pro/native/rosy-hw-probe.py` | 641 | 600 |
| `overhead/rosy_vision/track/background_blob.py` | 633 | 600 |
| `drive/behaviors/traffic_policy/manager.py` | 630 | 600 |
| `learning/registry/perception/deliver.py` | 629 | 600 |
| `fleet/fleet/swarm/session.py` | 628 | 600 |
| `deploy/site/rosy_site_autoupdate.py` | 616 | 600 |
| `tools/device_test/run.py` | 609 | 600 |

한도 아래의 등록 단위 36개는 판정이 없어진다. 그 가운데 1,000줄 아래 25개(브랜치가 착지하면 28개)가 `SMALL_UNITS`에 든다.

### 값의 근거

- **600·800·10,000은 그대로 둔다.** 제품 코드 1,653개의 중앙값은 113줄, p90 430줄, p99 847줄이고 600줄 초과는 47개(2.8%)다. 웹 자산 184개의 p90은 538줄이고 800줄 초과는 9개다. 패키지 27개 가운데 22개가 단위를 나누기 전 원래 합계로도 10,000줄 아래다. 한도를 올리면 넘은 목록이 짧아지지만 사용자가 요청한 것은 기준을 잡는 것이지 넓히는 것이 아니다.
- **단위 바닥 1,000.** 한도의 10%다. 1,000줄 아래 조각은 넘은 패키지를 한도 아래로 되돌리는 데 거의 기여하지 못한다. 오늘 1,000줄 아래 단위는 대부분 +150을 얻으려고 생겼다.
- **파일 바닥 150.** 옛 허용 한 번의 크기다. 그보다 작게 떼어 내는 것은 경계보다 여유를 사는 모양이다.

### Alternatives

- **+150을 유지한다.** 지금의 문제(나누기가 여유를 만들고, 작은 단위가 더 묶이고, 변경마다 산수와 재판정)가 그대로 남는다. 기각.
- **한도를 올린다(예: 파일 1,000, 단위 15,000).** 목록이 짧아지지만 기준선과 +150이 남으면 같은 산수가 더 높은 곳에서 되풀이된다. 기준선을 없애면 이 ADR과 같고 값만 다르다. 값은 위 분포가 받친다. 기각.
- **나누기마다 허용을 하나만 주고 단위들이 나눠 쓴다(공유 허용).** 단위가 몇 개든 합친 한도가 늘지 않아 허용 농사는 막지만, 누가 공유 여유를 쓸지 정하는 착지 순서 조정이 생긴다. 지금 Fleet에서 실제로 일어난 일이다. 기각.
- **D-168대로 초과를 판정 신호로만 둔다.** 사용자의 지시와 반대다. `accept`가 98개 판정 가운데 73개다.

### Consequences

- 묶인 큰 단위는 자라려면 진짜 분리가 먼저다. `fleet` 서버 단위(31,904)는 한 줄이라도 자라려면 21,904줄을 실제 책임 단위로 옮겨야 한다. `control`(30,125)도 같다. Fleet의 새 기능은 여유가 있는 등록 단위(예: `fleet/fleet/server/ledger` 1,871줄, `missions` 2,575줄, `trips` 2,269줄. 브랜치 기준)에 두면 된다. 그 단위들은 이제 10,000줄까지 자랄 수 있다.
- 묶인 파일 56개는 자라지 않는다. 그 파일에 기능을 더하려면 먼저 C1/C2/C5/B 경계로 600(웹 800)줄 아래까지 나눈다. 바로 쓰는 파일(`console.js`, `app.py`, `trip_runner.py`, `task_store.py`)은 곧 강제 분리가 필요하다.
- 순증 0 리팩터링(더하고 같은 곳에서 지우기)은 늘 된다. 지우기가 여유를 얻는 유일한 길이 된다.
- 위험: 억지 경계. 3항의 기준·바닥·경계 검토가 막는다. 그래도 경계가 없으면 거기에 넣지 않는다는 답이 맞다.
- 위험: 7(a) 착지 날 진행 중 브랜치의 충돌. 6항의 순서와 생성 표가 줄인다. 이 파일은 FULL 등급이라 착지 창이 필요하다.
- `SIZE_VERDICTS` 1,836줄이 `FROZEN_OVER_LIMIT` 약 62줄과 `SMALL_UNITS` 약 28줄이 된다.

### Open questions (사용자)

1. 단위 바닥을 1,000줄로 할까? 권장: 1,000. 500이면 오늘 작은 단위 25개 가운데 6개(500–999줄)만 정식 단위가 되고 바닥의 뜻이 약해진다.
2. `HARD_TIER`를 없앨까? 권장: 없앤다. 4항의 ratchet이 넘은 모든 파일의 증가를 0으로 만들어 1,000줄 등급은 하는 일이 없다.
3. 웹 자산 800줄을 유지할까? 권장: 유지. D-362의 근거(마크업 오버헤드)가 그대로이고 바꾸면 웹 파일 9개의 목록만 흔들린다.

### Validation

이 브랜치: `python tools/harness/rosy_harness.py generate`와 `lint`(오류 0). 7(a): `test/architecture` 전체를 `tools/remote/remote_pytest.py`로 시험 PC에서 돌리고 `test/known_failures.py`와 비교한다. 변이 증명 넷(새 초과, 묶인 것 증가, 표가 실제보다 높음, 바닥 아래 단위)을 기록한다. SOURCE 구조 증거이며 장치·현장 수용과 무관하다.

**References:** D-168(P6, Alternatives), D-362, D-753, D-763, [module split criteria](../plans/2026-09-06-module-split-criteria.md), [file size budget](../plans/2026-09-30-file-size-budget-and-refactor-queue.md), `docs/plans/2026-10-14-fleet-console-size-unit.md`, `docs/plans/2026-10-14-fleet-ledger-size-unit.md`, `test/architecture/test_module_structure.py`.
