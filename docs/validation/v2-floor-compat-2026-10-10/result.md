# v2 drivable 모델과 floor gate 호환 수정

## 수정과 시험

설치본 133의 floor gate가 wall 역할을 가진 모델만 열어 v2 로딩을 거부했다. v2에는 drivable 역할이 있으므로 검증된 drivable 영역을 읽는 경로도 허용했다. lane_marking_mask의 wall 요구와 실패 시 거부는 유지했다. drivable 영역이 부족할 때 벽 근거 없이 lane 페인트로 전환할 수 없다. 모델 해시·입출력·비유한값 검증과 CORE 보호는 유지했다.

- 재현 커밋 `5eec69003`: 신규 2개 시험이 모델 로딩 단계에서 실패했다.
- 수정 커밋 `b72453193`: 관련 원격 회귀 121 passed, 2 skipped, known_failures 0 NEW. ONNX 파일 자체는 장치에서 따로 열어 확인했다.
- 장치 candidate commit `fff186117`는 설치본 133 위에 이 변경만 적용했다. 같은 회귀 121 passed, 2 skipped, 0 NEW.
- 두 장치 signed delta 2026.10.10-136 적용. 변경 payload는 runner.py 한 파일. 설치 파일 SHA256 `0ab5583bc9525f19e35ec46bb368e6e337ecbdd5a44d8288355c1a3f00c4ad87`가 candidate git blob과 일치했다.
- 두 장치에서 floor_gate true로 v2 열기 성공, last_error null, revision lane-seg-20261010-451f0f85. 실제 keeper에도 같은 v2 수신과 learned_drivable, paint_floor_gate true가 기록됐다.

## 실물 재시험

- 9dfk 녹화 `20261010T110459Z_rosy_41` (17.201초): TRACKING 전진, 곡선 명령속도 약 0.026–0.030m/s, 완만한 구간 최대 명령 0.06767m/s. MCAP cmd_vel 807개, odom 496개, odom 끝점 이동 0.548m. 이후 crosswalk_looking → crosswalk_person_present로 정지했다. 이 사유는 LiDAR 점유 판단이며 사람 신원을 확인한 것은 아니다.
- 8kcn 녹화 `20261010T110458Z_rosy_40` (1.997초): v2 confidence 0.90, obstacle_ahead/body_gap 0으로 정지했다. cmd_vel 49개 모두 0. 이 장애물 근거는 후속 분석 대상이다.
- 두 시험 OFF 200, 녹화 종료, 토큰 logout 204, update hold 해제. 11:06 UTC IDLE/OFF 재확인. 9dfk encoder의 미세 잡음을 독립적인 이동으로 판단하지 않았다.

원본은 X:/DevTemp/lane-pair-analysis/*-v2-floor-field.log 및 *-v2-floor-field.json. 원격 시험 로그는 X:/DevTemp/v2-floor-regression/ 및 v2-floor-device/. 보호 정지, v2 소비, 한 구간 이동 증거를 전체 코스 합격으로 부르지 않는다. 최대 0.15m/s 실물 시험과 횡단보도 비움 후 통과는 확인하지 않았다.
