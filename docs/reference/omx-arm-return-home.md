# OMX 팔 A·B 홈 복귀 로직

2026-11-27 origin/main(`9f015e08d0` 이후) 코드 기준. 값 단위는 관절 단위(native unit). 홈은 각 팔 라이브러리의 `chunks.home[-1]`이다(팔마다 다름).

## 1. 복귀 경로 하나: `park_path`

`middleware/devices/omx/adapter/omx_adapter/chunk_library.py` `park_path(start, home, closed, fps)`. 시작 자세로 세 갈래 중 하나를 고른다.

| 시작 자세 | 조건 | 경로 |
|---|---|---|
| 홈 근처·접힘 | 몸 5관절이 홈과 5 이내이고 집게 차이 5 이내, 또는 lift ≤ -50이고 lift·elbow·wrist 차이 10 이내 | 집게 닫기 → wrist_roll 차이가 10 넘으면 elbow -10 들고 돌리기 → 홈. pan 차이 12 이내면 속도 절반 |
| 웅크림(tucked) | -50 < lift ≤ -15, elbow ≥ 35 | elbow ≤ 43으로 판 피하기 → lift -42 → lift·elbow 홈으로 접기 → 홈 |
| 그 밖(뻗은 팔) | `transit_path` | 집게가 열려 있으면 먼저 들어 올림 → 운반 높이(lift -27, elbow 18, wrist_flex 46)에서 집게 닫기 → pan·roll 회전 → 홈으로 내림 |

속도 상한은 가드 한계 5 단위/s(`GUARD_UNITS_PER_S`)의 0.85배, 들어 올림 2 단위/s다.

## 2. 복귀를 일으키는 곳

| 계기 | 코드 | 동작 |
|---|---|---|
| `park` 명령 | `chunk_runner_commands.py` | `park_path`로 홈. 집게는 닫음 |
| `stop` | `chunk_runner_commands.py` | 실물(scope=hardware)은 기본 `fold_on_stop`: 홈이 아니면 `park_path` 뒤 종료. `stop now`는 접지 않음. 접을 수 없으면(가드 hold, hard fault, 해제 미확인) 토크 ON으로 human-hold |
| 무명령(idle) | `chunk_runner_settle.check_runner_idle` | 마지막 명령·청크 끝에서 `runner.idle_park_s`(60 s) → `park`. 접기가 hold로 막히면 `idle_retry_s`(300 s) 뒤 한 번 더, 두 번째도 막히면 사람 호출 hold. 홈 도착 `idle_stop_s`(30 s) 뒤 세션 종료·토크 OFF. 정책(ACT) 세션은 제외 |
| 무명령 + 집게 열기 | `runner.idle_open_grip`, `chunk_runner_idle_open.py`(기본 0 = 끔, 최대 65) | 값을 주면 첫 idle 접기에서 **빈 집게**를 제자리에서 그 값까지 열고 1.5 s 뒤 `park`(1절 "집게 열림 → 먼저 들어 올림" 경로). 빈 집게 판정: `holding` false, fault 없음, 실측 집게와 명령 집게가 모두 `gripper_closed` + 2.0 이하. 하나라도 아니면 열지 않고 기존 `park`. 재시도 접기에서는 열지 않음 |
| 작업 전 재홈 | `cell_transfer.Gate.open` → `cell_unwedge.rehome_before_work` | 아래 3절 |
| `POST /jobs/home` | `cell_pipeline --stage home` → `return_home(grip=True)` | 3절과 같은 조그, 끝에 집게를 홈 값으로 |
| ACT 시작 검사 | `cell_policy_pre_home.pre_settle_home` | 홈 2.0 이내·정지·빈 집게가 아니면 `START_POSE_OFF_HOME`로 거절. hold를 남기면 다음 단계는 `recover_hold` |
| `POST /jobs/recover_hold`, `/jobs/safe_home` | `cell_safe_home.py` → `cell_auto_fold.py` | 살아 있는 human-hold면 `--unlatch-hold`(`recover-unlatch` → `recovery_park_path`). 토크 OFF 사고 팔이면 lease 확인 → `register_probe`로 6모터 hardware_error 0 확인 → 열린 사고 3건 이하 → 세션 래퍼로 접기 → 평가 토큰이 있으면 사고 해제 |
| D-1048 자동 접기 | `omx_incident_auto` → `cell_auto_fold.py launch` | 설정이 있을 때만 |
| 쥔 것 없는 `recover` | `cell_pipeline_stages.recover` → `cell_unwedge.unwedge` | 고정 상수 `cell_unwedge.HOME`을 향해 lift·pull 1 단위씩. 라이브러리 홈이 아님 |

## 3. 작업 전 재홈 (`return_home`)

1. 허용 조건(`can_rehome`): 정상 상태, fault·접촉·hold 없음, `holding` false, 집게 전류 140 mA 미만, 몸 4관절이 홈과 10 이내.
2. 홈과 5관절 모두 3.0(`SETTLE_TOL`) 이내면 아무것도 하지 않는다.
3. 계획(`_home_plan`): 한계 밖 관절을 먼저 안으로 → wrist_roll이 10 넘게 벗어나면 elbow -10 들기 → roll, wrist_flex, elbow, lift, pan 순으로 홈 → 든 elbow를 홈으로.
4. 조그 한 번은 최대 4 단위, 2 s 기다린 뒤 지연(lag)을 본다. 지연이 max(2.0, 시작 지연+0.4)를 넘으면 `bind_suspected`, 조그 80회를 넘으면 `stopped`.
5. 작업 전 재홈은 집게 명령을 보내지 않는다(감지 못 한 상자가 떨어질 수 있음).
6. 실패하면 홈 8.0(`REST_TOL`) 이내는 `stop now`, 아니면 `human-hold`. Gate는 `rehome_<결과>`로 작업을 막는다.

## 4. 알려진 어긋남

- `cell_unwedge.HOME`은 고정 상수다. 팔별 라이브러리 홈과 다를 수 있어 `unwedge` 경로만 이 값을 쓴다.
- 무명령 판정은 "명령이 없는 시간"이다. 청크가 도는 동안은 시간이 흐르지 않는다(2026-11-19 교훈).

## 5. arm_a에 "1분 무동작 → 제자리 열기 → 복귀" 켜기

집게가 제자리에서 벌어지므로(한쪽 약 65 mm) 무명령으로 멈추는 자세 옆에 이웃 상자가 붙어 있으면 닿을 수 있다. 두께 2.0 단위 미만의 얇은 물체는 빈 집게로 판정될 수 있다.

셀 PC의 arm_a 매개변수 파일에 다음을 넣는다(셀 매개변수 화면 또는 배포 설정). 값은 그 팔의 열린 집게 값(관측 55.6~56.0)이다.

```json
"runner.idle_open_grip": {"value": 56.0, "unit": "joint_unit", "source": "default", "evidence": "2026-11-27 user: arm_a idle 60 s → open jaws in place → fold home"}
```
