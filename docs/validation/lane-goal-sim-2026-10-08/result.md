# 차선 추종 주행 목표: B9 굽이 후보와 현재 CORE의 결합 재생

2026-10-08, 모델 PC의 독립 `~/rosy_bend_window_ws`에서 시행했다. 소스는 `feat/bend-window-sim`의 `3a6586947`이다. 이 브랜치는 현재 main의 CORE 기대 창 가드와 미착지 B9 keeper를 SIM용으로만 합쳤다. B9의 `bend_expected`는 장치 기본값 `false`이며, 이 실험에서만 `sitecustomize.py`로 켰다. ROS domain 81, Gazebo partition `rosy_bws`, CORE port 8101을 썼고 종료 뒤 이 partition의 프로세스를 멈췄다.

| 재생 | 결과 | 해석 |
|---|---|---|
| `bw1`, `trip --plan left:60` | 굽이 전 x≈−0.951 m에서 첫 `no_boundary`; 33프레임 지속 뒤 x≈−0.948 m에서 `LOST_between_junctions`. 차로 중심 오프셋 중앙값 +0.0196 m(32프레임). 분기 지시는 `armed`, 소비 0 | 굽이 통과 실패. 보이지 않는 구간에 진입할 근거가 없으므로 STOP은 맞는 안전 결과다. [프로브](bw1-summary.json), [분석](analysis.json). |
| `bw2`, 같은 경로 | 굽이 평가 창 0프레임. x≈−1.271 m에서 LOST, 종료 때 프로브 Python이 core dump | 굽이 후보의 성공·실패 표본에서 제외. 재현 환경도 별도 조사 대상이다. [분석](analysis.json). |

이 프로브의 `/api/v1/line-follow/junction` 요청에는 `map_id`와 기대 창이 없다. 따라서 `bw1`의 지시 미소비를 CORE의 새 **지도 지시 기대 창 가드 검증**으로 해석할 수 없다. 그 가드는 소스 회귀 시험에서만 확인했다. 이 실험으로 확인된 것은 B9를 강제로 켜도 굽이 전 경계 공백이 남는다는 점이다. 앞선 B9 단독 SIM은 6회 중 0회 통과했고, 이번 결과는 이를 통과로 바꾸는 근거가 없다.

다음 gate는 (1) Fleet 경로의 굽이 장소·기대 창을 CORE와 keeper에 시각·지도 ID를 묶어 전달하고, (2) 앞서 검증한 같은 차로 경계와 신선한 오돔·차체 여유가 있는 짧은 구간에서만 공백 접근을 허용하며, (3) 기대 창 밖 분기·벽·오래된 오돔에서는 정지하는 것이다. 이 계약과 10/6·10/7 영상의 사람 승인 동일 경계 정답이 갖춰지기 전에는 B9 게이트를 장치에 연결하지 않는다. CORE만 최종 `cmd_vel`을 낸다. 이번 증거는 ROS-SIM이며 장치·현장 수용이 아니다.
