## D-1065 OMX 셀 카메라는 역할 이름(`top`·`side`·`wrist`)으로만 부른다 — 녹화·데이터·시뮬·정책·변환이 같은 이름을 쓴다

**Status:** Proposed (2026-11-21, 사용자 요청 「정확하게, 완전하게 규칙화해서 ADR로 기록」). 녹화기 연결과 셀 설정 적용은 담당 세션과 별도로 한다.

**관련:** D-792(카메라 촬영 기준), D-1012(MuJoCo→Isaac 파이프라인), D-1057(셀 작업 허가 증거, D435), D-1063(공급암 S `top` 카메라), D-943(작업대 녹화). PR #401(정책 체크포인트 카메라 이름 검사)과 함께 읽는다.

### Context

같은 카메라가 곳마다 다른 이름으로 불려 왔다. 2026-11-21 기준:

| 위치 | 위 D435 | 옆 Jieli | 팔 손목 |
|---|---|---|---|
| 셀 카메라 서비스 `omx-cameras.json` | `top` | `side` | `arm_a_wrist`·`arm_b_wrist` |
| 셀 정책 입력 `cell_act_inputs` | `top` | `side` | `wrist`(팔별) |
| 시뮬 렌더(`omx_two_arm_world`) | `top` | `side` | `a_wrist`·`b_wrist` |
| 셀 녹화 설정 A(`record-config-arm-a.json`) | `top` | 없음 | `front` |
| 셀 녹화 설정 B(`record-config-arm-b.json`) | 없음 | `side` | `front` |
| 실물 데이터 Purple-SY(11-04~11-19) | `rs` | `top` | `wrist` |
| 11-20~21 팔별 시뮬 학습 데이터 | `rs` | (`side`, 11-21 3카메라부터) | `wrist` |

**어떻게 이렇게 됐나.** 이름을 역할이 아니라 설치 당시 장치에 붙였고, 역할이 바뀔 때 카메라 서비스만 고쳤다.

1. 2026-10-18 Jieli USB 카메라를 작업대 위 약 650 mm에 달고 `top`이라 불렀다. 녹화 설정(`record-config*.json` 10-19~10-24)은 `top`=Jieli, `front`=손목 Innomaker였다.
2. 10-28 `front` 역할을 카메라 서비스에서 은퇴시켰지만 녹화 설정은 손목을 계속 `front`로 불렀다.
3. 11-04 무렵 위에 D435를 더 달았다. `top` 이름은 이미 Jieli가 쓰고 있어 녹화에서 D435를 `rs`(RealSense)로 불렀다(`omx-left-arm-20261104`부터 `rs`·`rs_depth`·`top`·`wrist`).
4. 11-07 카메라 서비스의 역할을 `top`=D435, `side`=Jieli로 바꾸고 Jieli를 옆으로 옮겼다(`deploy/hosts/services.yaml` 주석 「camera roles of 2026-11-07」). 녹화 설정과 팀원의 LeRobot 녹화는 바꾸지 않아, 옆으로 간 Jieli를 계속 `top`, 위 D435를 `rs`로 저장했다. Purple-SY 데이터 프레임으로 확인했다: `top`=정면 옆 화면, `rs`=위에서 내려다본 화면.
5. 이름만 보고 데이터를 쓰면 옆 화면을 위 화면 자리에 넣게 된다. 11-21 실물·시뮬 혼합 학습에서 프레임을 직접 보고서야 알았고, 셀에서는 체크포인트 입력 이름을 손으로 바꾼 사본을 쓰고 있다.

LeRobot 카메라 키는 자유 문자열이고, 장치↔역할 대응을 한 곳에서 검사하는 코드가 없었다.

### Decision

1. **역할 이름은 셋이다(셀 A·B).** `top` = 작업대 위 D435, `side` = 옆 카메라, `wrist` = 그 팔의 손목 카메라. 공급암 S 셀은 `top`(위 USB)·`wrist`이고 `side`가 없다. 깊이 영상을 쓰면 `top_depth`다. 이름은 장치나 제조사(`rs`, `jieli`, `front`)가 아니라 역할을 나타낸다.
2. **장치→역할 대응의 정본은 셀의 `omx-cameras.json` 하나다.** 다른 설정·코드·데이터는 역할 이름으로만 카메라를 부른다. 장치 경로(`/dev/v4l/by-id/rosy-*`) 이름은 바꾸지 않는다(`rosy-arm_a_jieli`가 옆 카메라인 것처럼 경로 이름은 역할이 아니다).
3. **녹화 설정.** 팔 녹화 설정의 `robot.cameras` 키는 그 셀의 역할 이름과 정확히 같아야 한다(A·B: `top`·`side`·`wrist`). 각 키의 장치는 `omx-cameras.json`에서 그 역할의 장치와 같아야 한다(손목은 그 팔의 `<arm>_wrist`). 녹화기는 이를 만족하지 않는 설정을 거절한다. 검사는 `deploy/robot/omx/camera_roles.py`의 `check_record_cameras` 하나다. 녹화 설정을 바꾸면 팔별 로봇 프로필 결속(`fix/bench-record-arm-binding`)을 같은 절차로 갱신한다.
4. **데이터.** 새 LeRobot 데이터의 영상 키는 `observation.images.top`·`observation.images.side`·`observation.images.wrist`다. 옛 데이터는 변환기가 명시한 대응표로만 바꾼다(아래 표). 대응은 이름이 아니라 표본 프레임을 보고 정하고, 변환 영수증에 대응표와 확인한 프레임을 남긴다.

   | 옛 데이터 | 옛 키 → 역할 |
   |---|---|
   | Purple-SY 2026-11-04~11-19 | `rs`→`top`, `top`→`side`, `wrist`→`wrist`, `rs_depth`→`top_depth` |
   | 2026-10 녹화(`record-config*.json` 10-19~10-24) | `top`→Jieli가 위에 있던 시기의 `top`(현재 배치와 다름, 섞지 않음), `front`→`wrist` |
   | 셀 녹화 설정 A·B(11-21 01:59판) | `front`→`wrist` |
   | 11-20~21 팔별 시뮬 학습 데이터 | `rs`→`top` |

5. **시뮬.** 시뮬 렌더 이름(`top`·`side`·`a_wrist`·`b_wrist`)은 데이터에 `top`·`side`·`wrist`로 적는다.
6. **정책.** 체크포인트의 입력 영상 이름은 역할 이름이다. 정책 실행기는 역할 밖 이름을 거절한다(PR #401). 옛 이름 체크포인트는 입력 이름만 바꾼 사본을 만들고, 같은 입력에서 출력이 같은지 확인한 기록을 남긴다(가중치·입력 순서는 바꾸지 않는다).
7. **역할 변경 절차.** 카메라의 역할이나 물리 위치를 바꾸는 일은 작업대 배치 revision을 올리는 변경이다. `omx-cameras.json`, 팔 녹화 설정, 로봇 프로필 결속, 촬영 기준(D-792)을 한 변경에서 함께 고친다. 그 전 데이터는 자기 revision의 대응표를 따른다.

### 일부러 하지 않는 것

- 장치 경로·카메라 서비스 유닛 이름 변경.
- 옛 데이터 파일 다시 쓰기. 변환 단계에서만 대응표를 적용한다.

### 열린 항목

- 녹화기(`bench_record.py`)가 `check_record_cameras`를 부르게 하는 연결은 팔별 결속 브랜치(`fix/bench-record-arm-binding`)가 병합된 뒤 그 담당이 한다.
- 셀 A·B 녹화 설정을 세 카메라(`top`·`side`·`wrist`)로 바꾸는 적용과 3대 동시 녹화의 프레임 누락 확인(초안: 조정 세션 `D:/DevTemp/cell-camera-names-1121/`).
- 공급암 S의 `arm_s_top` 화면 이름(D-1063)과 이 규칙의 `top`을 맞추는 일.
- 2026-11-21 혼합 학습 4판(`mix-1121`)은 위 D435를 `rs`로 부른다. 셀에 쓸 때 §6 절차로 이름을 바꾼다.

### Consequences

- 이름만 보고 옆 화면을 위 화면 자리에 넣는 실수를 녹화·변환·정책 세 곳에서 막는다.
- 녹화 설정을 바꾸면 결속 갱신이 필요해 첫 적용은 한 번 손이 간다.
