# Fleet 브라우저 관제 크기 단위 분리

**날짜:** 2026-10-14
**범위:** D-168/D-753 구조 판정만. 코드 이동이나 동작 변경 없음. D-763 조각 3(`feat/fleet-work-move-entry`, 새 작업의 이동 입구)과 같은 브랜치의 변경이다.

`fleet` 판정(D-757 재판정)은 56,755줄에 +150 허용이고, D-753 문구는 "기능 성장 허용을 더하지 않았다"다.
D-763 구현 조각 표는 조각마다 Fleet 크기 단위에서 순증 0 이하이거나, 먼저 새 크기 단위를 등록하는 날짜 있는 계획을 내라고 정했다.
조각 3은 관제 화면(`operations/site_ui/console`)만 고친다. 서버 변경이 없는데 순증이 +35줄이라 순증 0을 맞추지 못했다. 이 계획이 그 날짜 있는 계획이다.

## 무엇을 단위로 하는가

`operations/site_ui/console`을 크기 단위 `site_ui/console`로 등록한다.

- 오늘 이 폴더는 `fleet` 패키지의 비패키지 보관 자리(`_files`의 holders: `operations/decision`, `operations/site_ui/console`, `integrations/messaging/discord`)로 `fleet` 합계에 들어간다. 확인: 단위를 등록하지 않은 측정에서 `fleet`이 56,856줄이고, 단위를 등록하면 `fleet` 38,868줄과 `site_ui/console` 17,988줄로 나뉜다(브랜치 기점에서 합 56,856).
- 이미 Python 하위 패키지다(`operations/site_ui/console/__init__.py`). `cell/`, `shared/`도 그 안이고 가장 안쪽 단위가 줄을 가져가므로(`_over_budget`) 모두 이 단위에 든다.
- 스캔에서 빠지는 파일은 없다. 줄은 `fleet` 대신 이 단위로 세어진다. D-753의 "비패키지 보관 자리는 크기 단위 제외가 아니다"는 그대로 맞다: 제외가 아니라 자기 단위다.

## 왜 나누는가

- D-763은 관제에 화면(새 작업의 종류, 승인 대기 자리, 작업 한 건의 오른쪽 칸)을 더한다. 화면 줄은 서버와 다른 owner(브라우저, node·Chromium 시험, CSP)이고 다른 속도로 는다.
- 한 합계로 두면 화면 조각이 서버의 남은 여유를 쓰고, 서버의 증가가 화면 증가 뒤에 숨는다. Fleet 서버의 증가는 자기 단위에서 따로 보여야 한다.

## 기준선(브랜치 기점 `06e97383b`에서 잰 값)

| 단위 | 기점 측정 | 판정값 | 지금(조각 3 뒤) |
|---|---|---|---|
| `fleet`(서버·decision·discord) | 38,868 | 38,767 | 38,868 |
| `site_ui/console` | 17,988 | 17,988 | 18,023 |

- `fleet` 판정값은 기점 측정이 아니라 56,755 − 17,988 = 38,767이다. 기점의 합계 56,856은 이미 D-757 판정 56,755보다 101줄 위였다(+150 가운데 101 사용). 서버 단위를 기점 측정으로 다시 잡으면 그 101줄이 기준선 안으로 사라진다. 그래서 서버 단위는 옛 판정에서 관제 줄만 빼고, 101줄은 서버 단위가 이미 쓴 허용으로 남긴다. 그 101줄이 어느 쪽에서 늘었는지는 나누지 않았다(보수적으로 서버에 둔다).
- `fleet`은 D-753 문구를 그대로 지킨다: 기능 성장 허용을 더하지 않았다. 남은 여유는 49줄이다.
- `site_ui/console`은 기점 17,988에 +150 허용이다. 조각 3이 35줄을 쓰고 115줄이 남는다.

## 그대로 두는 것

- 모든 안쪽 단위(`fleet/fleet/traffic`, `observe`, `server/channel`과 그 아래, `localization`, `stuck`과 `stuck/submission`, `incidents`와 그 아래, `decision/.../deliberation`·`conversation`과 그 아래)의 기준선과 +150.
- 파일 600·800줄 판정과 1,000줄 HARD_TIER의 증가 0. 관제 파일 판정(`site_ui/console/console.js` 1,175, `map-view.js` 984, `shared/styles.css` 802)은 그대로 검사한다. `console.js`는 HARD_TIER 위라 파일 허용이 0이다.
- `fleet` 판정 문구의 이전 분리 의무(observe/server/UI, D-728 channel, D-757 account) 전부. 이 계획은 그 문구 앞에 한 줄을 붙일 뿐 지우지 않는다.
- 다음 관제 증가가 +150에 닿으면 수용으로 넘기지 않는다. 그때는 새 작업·승인 대기의 화면 코드(`work-view.js`와 `console.js`의 작업 영역 연결)를 자기 하위 패키지로 낸다.

## 검증

`test/architecture/test_module_structure.py`의 실측(`test_over_budget_code_has_a_recorded_verdict`, `test_size_units_are_real_subpackages_with_a_split_plan`, `test_size_verdicts_are_well_formed_and_current`)을 원격 시험 PC에서 돌린다. SOURCE 구조 증거이며 ROS-SIM·DEVICE·FIELD 수용을 뜻하지 않는다.

판정 상태: 제안값이다. 앞선 단위 등록처럼 읽기 전용 critic의 독립 재판정을 받는다.
