# OMX 시범 학습 준비와 왼쪽 손목 진단

2026-11-02 운영 Learning, 관제 PC의 녹화 자료, 현재 장치 상태와 카메라를 확인했다. **학습과 새 팔 동작은 실행하지 않았고, 손목 고장 원인은 미해결이다.**

## 실행 코드와 관측 방법

- 문서 기준 main commit: `2f75c92d736e`.
- 현장 배포 도구: `rosy-omx/releases/2ba97ac2c346`. 기존 `register_probe.open_readonly_port`와 `read_motors(allow_fault=True)`로 arm_a를 읽었다. 도구의 버스 독점 검사와 PING/READ 패킷 제한을 유지했다.
- 기존 arm_b 실행기는 `omx-tools-9fc65a8ca3`의 record_session/chunk_runner였다. 해당 세션에 명령을 보내거나 종료하지 않았다.
- 운영 뷰어의 `/state.json`, `/frame/top.jpg`, `/frame/front.jpg`, `/frame/side.jpg`를 조회했다. 확대본은 원본 일부를 최근접 보간으로 3배 늘렸으며 세부를 생성하지 않았다.

## 학습 입력

운영 Learning은 계정 화면까지 HTTP 200이다. 운영 검수 DB의 학습 대상·과제 기록과 자료 결속은 0건이며 OMX center의 uploads/datasets/runs는 비어 있다.

관제 PC의 실제 리더 녹화 중 `supply-box-to-conveyor-r1-20261024-214652`와 `pinky-box-to-conveyor-r1-20261024-215808`에는 리더가 움직이지 않았다는 `DO_NOT_TRAIN.txt`가 있다. 학습에서 제외한다.

`teach-cycle-r1-20261024-222009`, `teach-cycle-r2-20261024-222455`, `teach-cycle-r3-20261024-223841`은 각각 1 episode, 1794/2692/1794 frames, 30 fps, 영상 2개다. 기존 현장 Python 환경의 pyarrow로 parquet를 읽어 action/state가 finite이며 움직임이 있음을 확인했다. 대응하는 봉인 collection, 녹화 당시 종료·보정 출처, 성공·무개입 검수는 확인하지 못했다. 현재 session.json은 다른 scripted-teacher 세션이고 연결된 dataset도 없어 위 녹화의 출처로 재사용할 수 없다.

## 왼쪽 손목

현재 observer 설정으로 식별한 arm_a의 ID 11–16은 모두 응답했다. hardware_error와 torque는 모두 0, XL430 전압은 11.6–11.7 V, XL330은 6.0–6.1 V, 온도는 19–32 °C였다. 이 정지 상태 관측은 기계적 정상 판정이 아니다.

`chunk-io/chunk-status.jsonl`에는 `run goto above_pick` 중 wrist_roll의 5° 초과 추종 오차 정지가 반복된다. 마지막 정지와 같은 장치·시각의 `motor-health-1793542706586879235.jsonl`을 대조했다. 2026-11-01 14:19:00.217–14:19:01.032 UTC에 실제 위치는 2718→2714 raw 부근에서 정체됐고 목표는 2688→2662 raw로 진행했다. 마지막 건강 표본은 오차 4.5703°, PWM -82/300, 전압 6.1 V, 온도 18 °C, hardware_error 0이었다. 직후 가드는 command/current=2657/2714에서 5° 초과를 기록했다. 같은 시각의 다른 장치 로그는 분리했다.

상단 영상에 손목 주변 케이블 루프와 가까운 주황색 물체가 보인다. 측면에서는 말단 일부가 가려진다. 케이블 걸림, 기구 저항, 체결 이상 또는 구동 설정 중 어느 것이 원인인지는 정지 영상과 이 표본만으로 확정할 수 없다. 출력 상한 도달도 관측하지 않았다.

arm_a의 읽기 전용 observer 시작은 기존 global session.lock 검사에서 거절됐다. 시작 시도로 생긴 자동 재시도는 중지해 원래 비활성 상태로 돌렸으며, 락이나 가드는 변경하지 않았다. arm_b의 기존 live 상태는 최신이고 fault null이었다.

## 증거 보관과 한계

원본 사진과 확대본은 Git 밖 작업 공간 `Rosy/artifacts/device-evidence/2026-11-02-left-arm/`에 보관한다. 이 문서에 사진 자체를 포함하지 않는다.

| 파일 | SHA-256 |
|---|---|
| top.jpg | 70eecaad6893847278c0e398e6216fd1867781424248f02615e1b1d12f2b71af |
| front.jpg | cb6d6e4ee481138b64295f39c31f8a338deb30654d80bd37b52b1f658b70bf43 |
| side.jpg | d4ab16533b926bb156b8fda8a2713754eb244ba7a4c80663b054c73050d00e4a |
| left-wrist-top-3x.png | 891f0287ca58ac12bf2ca80deba725c6b5b544b2c7478e2094428d85bd73f368 |
| left-wrist-side-3x.png | 90189eed915c4b339f48d0dcb4e01415ece3026b275e04dfa891060e28a198e8 |

이 기록은 데이터 준비·읽기 전용 관측의 근거다. 실제 학습, 모델 평가, 수리, 새로운 동작 시험 및 실물 수용은 미실행이다. 후속으로 적격 시범의 출처·사람 검수를 확보하고, 왼쪽 손목의 원인을 기존 가드 안에서 감독 진단해야 한다.

CE: 미해결 — 확인한 증상과 미검증 원인을 구분했으며 해결 교훈은 추가하지 않았다.
