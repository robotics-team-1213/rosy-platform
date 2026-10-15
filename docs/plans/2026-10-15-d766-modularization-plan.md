# D-766 modularization plan — slice (c)

**Date:** 2026-10-15. **Status:** plan for [D-766](../adr/D-766-size-limits-split-on-exceed.md) slice (c) (첫 강제 분리). 숫자는 main `4a45239a5`에서 잰 것이고, 각 조각을 시작할 때 `python test/architecture/test_module_structure.py`로 다시 잰다. 이 계획은 일정을 정하지 않는다(D-766 7(c)). 각 조각은 이 계획을 인용하고 경계 검토 하나를 받는다.

이 계획이 쓰는 규칙: 단위 한도 10,000줄, 파일 600줄(웹 800), 새 단위 바닥 1,000줄(부모 2,000줄 이상일 때), 경계는 C1/C2/C5/B로 고른다(D-766 3). 단위 등록은 `test/architecture/size_units.txt`에 한 줄을 더하는 데이터 변경이고, 행을 내리는 것은 `test/architecture/size_ratchet.txt`의 데이터 변경이다. 둘 다 FULL 착지가 아니다(slice (a)). 순수 이동은 `python tools/harness/split_check.py <base> <head>`가 "AST identical, only imports/paths changed"를 찍으면 검토가 경계만 본다.

경로는 colcon 루트(`contracts`, `middleware`, `operations`, …) 기준이다.

## 단위별 분석

### core_common 10,643 → 등록만

| 조치 | 대상 | 줄 수 | 기준 | 비고 |
|---|---|---|---|---|
| 단위 등록 | `foundation/core_common/protocol` | 5,860 | B | 등록만, 코드는 그대로 |
| 파일 분리 | `protocol/schemas.py` 1,359 | — | C5 | family별 `schemas_actions.py`/`schemas_mission.py`로 나누고 `schemas.py`가 다시 내보낸다. 다음에 자랄 때 |

### dashboard 11,085 → 등록만

| 조치 | 대상 | 줄 수 | 기준 | 비고 |
|---|---|---|---|---|
| 단위 등록 | `robot_ui/robot/panels` | 2,987 | B | CMake `install(DIRECTORY panels)` 폴더라 `__init__.py` 없이 보관 자리로 인정된다(slice (a) 4번) |

### perception/front_camera/perception 10,075 → route 하위 단위

| 조치 | 대상 | 줄 수 | 기준 | 비고 |
|---|---|---|---|---|
| 새 단위 | `perception/front_camera/perception/route` | 1,649 | B, C2 | `route_camera`, `route_hybrid`, `route_map`, `lane_route`, `paint_localizer`, `paint_hypothesis`. 보관 자리는 `__path__.extend` + HolderBuild |
| 기각 | 카메라 묶음 | — | — | 가져다 쓰는 곳 77개라 경계가 아니다 |
| 파일 분리 | `lane.py` 771 → `lane_corner.py` | — | C1 | 다음에 자랄 때 |
| 파일 분리 | `lane_bev.py` 717 → `LaneEdgeFollower` 파일 | — | C2 | 다음에 자랄 때 |

### site_ui/console 18,082 → shared 등록과 페이지 묶음

| 조치 | 대상 | 줄 수 | 기준 | 비고 |
|---|---|---|---|---|
| 단위 등록 | `site_ui/console/shared` | 4,387 | B | 등록만 |
| 이동 | `install` 페이지 묶음(`install.html`, `install.js` …) | 3,308 | C2 | 하위 폴더로. URL은 평평하게 유지: `__init__.py`, `package_data`, `static_routes` 허용 목록, `resolve-console-assets.mjs` |
| 이동 | `site_map` 페이지 묶음(`site-map*.js/html/css`) | 1,595 | C2 | 같은 방식 |
| 파일 | `console.js` 1,080 | — | — | 다음에 자랄 때 나눈다 |
| 파일 | `map-view.js` 952 | — | — | 묶음(freeze) |
| 파일 | `shared/styles.css` 862, `shared/site-map-model.js` 799 | — | — | `site-map-model.js`는 한도 800까지 1줄. 더하기 전에 나눈다(95% 선) |

### fleet 31,902 → 기존 보관 자리 등록과 순수 이동

| 조치 | 대상 | 줄 수 | 비고 |
|---|---|---|---|
| 등록 | `fleet/fleet/server/auth` | 4,769 | `SERVER_HOLDERS` |
| 등록 | `fleet/fleet/server/console` | 2,426 | `SERVER_HOLDERS`, safety 파일 포함 |
| 등록 | `fleet/fleet/server/cell` | 1,819 | `SERVER_HOLDERS` |
| 등록 | `fleet/fleet/swarm` | 2,327 | 패키지 |
| 등록 | `fleet/fleet/routing` | 1,075 | 패키지 |
| 등록 | `decision/src/rosy/decision` 나머지 | 1,680 | 패키지 |
| 이동 | `server/overhead` (새 보관 자리) | 2,634 | 순수 이동 |
| 이동 | `server/site_map` (새) | 1,398 | 순수 이동 |
| 이동 | `server/evidence` (새) | 1,041 | 순수 이동 |
| 이동 | `proposal_store` + `model_feedback_dispatch` → `missions` | 1,220 | `missions`는 `feat/fleet-work-read-sources`가 만든다. `proposal_store.py`(797, 묶임)는 같은 커밋에서 옛 행을 지우고 새 경로 행(값 이하)을 더하는 이름 바꿈으로 옮긴다 |
| 이동 | `server/right_of_way` (새) | 1,606 | 가장 약한 경계. 이동 전에 경계 검토 |
| 이동 | `server/dispatch` (새) | 2,013 | safety 태그 파일 6개. 맨 끝 |

남는 것은 약 7,900줄이다. 파일: `console/console.py` 1,325(safety, mixin으로, 큰 일), `app.py` 981(route installer로), `cell/cell_job_store.py` 963, `auth/enrollment.py` 847, `proposal_store.py` 797. `cli.py` 923과 `swarm/session.py` 628은 묶어 둔다.

### control 30,125 → 기존 자리 등록과 새 CONTROL_ROOT

| 조치 | 대상 | 줄 수 | 비고 |
|---|---|---|---|
| 등록 | `drive/tracking/wander` | 2,390 | `PACKAGE_DIRS` |
| 등록 | `drive/planning/grid` | 1,435 | `PACKAGE_DIRS` |
| 등록 | `perception/sensors/sensing` | 2,736 | `PACKAGE_DIRS` |
| 등록 | `drive/motion_limits` | 3,470 | `FLAT_ROOTS` |
| 등록 | `drive/calibration` | 1,691 | `FLAT_ROOTS` |
| 등록 | `drive/recovery` | 1,381 | `FLAT_ROOTS` |
| 등록 | `perception/sensors/line_observation` | 1,091 | `CONTROL_ROOTS` |
| 등록 | `perception/map` 스크립트 | 1,797 | 옮기지 않는다(`MANIFEST.sha256`) |
| 새 CONTROL_ROOT | `perception/calibration` | 3,074 | `nodes/calibration_*`, `calib_node`, `startup_calibration_node`에서 |
| 새 CONTROL_ROOT | `perception/recording` | 1,225 | `nodes/record_session`, `recording`, `pilot_recording`, `pilot_recorder_node`에서 |
| 새 CONTROL_ROOT | `perception/web` | 3,131 | |

남는 것은 약 6,700줄이다. 새 ROS 패키지는 필요 없다. 단위는 세는 경계일 뿐이고, 패키지 신원은 console_scripts, entry point, launch 참조를 지닌다. 파일: `web/diagnostic.html` 1,857(JS/CSS를 떼어 낸다), `drive/motion_limits/adapter/node.py` 847(safety, `tick_policy.py`로, 큰 일), `perception/sensors/line_observation/line_observer_node.py` 755.

## 순서

0. `feat/fleet-work-read-sources`가 옛 규칙으로 착지한다. 그다음 D-766 slice (a)가 착지한다.
1. **레인 A — 등록만, 한 커밋.** core_common, dashboard(끝), fleet(→ 17,806), control(→ 17,022), console(→ 13,695)의 등록 행 전부. `size_units.txt`와 `size_ratchet.txt`만 바뀐다.
2. **레인 B, C, D — 나란히.** B: perception route. C: console 페이지 묶음. D: control의 새 CONTROL_ROOT.
3. **레인 E — Fleet 보관 자리 이동, 차례대로.** overhead → site_map → evidence → proposals → right_of_way → dispatch(safety, 맨 끝).
4. **파일 분리.** 각 파일이 다음에 자랄 때.

## 열린 항목

- **닫음(2026-10-15, D-766 덧붙임 「세지 않던 루트와 `.kt`」).** 아래 루트와 `.kt`를 센다. 처음 잰 것 가운데 넘은 것은 `CameraController.kt` 791줄 하나다.
- **레인 A 실측(2026-10-15).** 등록 16개, 모두 1,000줄 이상. `fleet` 17,788, `control` 15,931, `site_ui/console` 13,330. `core_common`(4,783)과 `dashboard`(8,098)는 표에서 빠졌다. `perception/map` 스크립트는 하위 패키지도 선언된 보관 자리도 아니라 등록하지 않았다.
- **(옛) 세지 않는 루트(검토 지적 8, 이번에 고치지 않음).** `operations/site_execution`, `middleware/robot_execution`, `contracts/learning`, `operations/world`, `integrations/robots`의 생산 코드와 `.kt` 파일은 어느 패키지·운영 루트의 셈에도 들지 않는다. 이 루트를 `OPS_ROOTS`나 패키지 보관 자리에 넣고 `.kt`를 코드 유형에 넣는 변경은 넘은 목록을 늘리므로, 따로 날짜 계획과 생성 행으로 한다.

## 위험

- **D-430 safety.** `dispatch` 파일, `console/console.py`, `motion_limits/adapter/node.py`. 순수 이동이면 `split_check.py` 결과를 인용한 `Safety-Review:` trailer로 된다.
- **패키징.** Fleet 보관 자리는 `__init__.py`가 없다. 설치 파일 보관 자리 목록, control `HolderSource`의 하드코딩 목록, console `package_data`를 같이 고친다.
- **동료 변경.** `fleet/server`는 자주 바뀐다. 이동은 짧은 브랜치로 한다.
- **맵 번들 manifest.** `perception/map`은 옮기지 않는다.
