# 원격 수동 직진과 keeper 실시간 관측

## 범위와 판정

사용자는 안전한 환경에서 최대 10초 원격 조작과 차선 추종 개선을 요청했다. 현장 조작자는 없다고 답했다.
실제 수행은 D-378 §4의 카메라로 확인한 짧은 수동 직진이다. D-344 R2 자동 차선 주행은 **NOT_RUN**이다.
원격 사람이 화면을 보며 진행을 누를 수 있다면 현장 부재 자체는 차단 사유가 아니다.
에이전트 타이머나 마우스 홀드를 사람의 진행 확인으로 대신하지 않았다.

## 실제 장치 조작

- 대상: 승인된 `rosy-pinky-9dfk` SSH 별칭. TLS CA와 정확한 호스트 이름을 검증한 관리자 세션 사용.
- 설치 런타임: `2026.10.05-040`, source `58d246ab3d2842890529893c8ef34e944153639a`.
- 카메라 원본에서 전방 바닥과 차로를 확인한 뒤, 실제 대시보드 MANUAL 확인 대화상자와 직진 버튼을 사용했다.
- 첫 직진: 0.03 m/s 명령, 홀드 1.025초, 속도 readback에서 움직임 확인, 해제 후 정지 기준 도달 0.26초.
- keeper 적용 뒤 두 번째 직진: 같은 명령, 홀드 1.027초, 정지 기준 도달 0.26초.
  오도메트리 `(0.029078, 0.000011)` → `(0.059122, 0.000250)` m, 약 0.030 m 이동.
- 정지 기준은 `tools/dashboard_drive.py`의 속도 허용 오차이며 물리 정지 거리나 전원 차단 실측이 아니다.
  두 번째 종료 직후 오도메트리에 미소 속도가 남았으므로 그 순간을 정확한 속도 0으로 기록하지 않는다.
- 최종 line-follow readback은 OFF/OFF. 관리자 세션 두 개를 logout 204로 폐기했다.
- 06:52:52 UTC 후속 장치 snapshot은 IDLE/OFF, 선속도·각속도 0, CORE·카메라·IO active를 확인했다.

## 실제 keeper 연결

기존에는 `camera_lane_mode: line`, `camera_ground_source: PINKY`, operator overlay 없음이었다.
IDLE/OFF에서 설치된 `line_observer_overrides` 도구로 9dfk의 operator overlay를 적용하고 카메라 서비스만 재시작했다.
`keep`, `NOMINAL`, `allow_nominal_ground: true`, 설치 릴리스의 `camera_nominal.yaml`을 사용했다.
pitch/height 수치를 임의로 만들지 않았고 CORE·모터 서비스는 재시작하지 않았다.

정지 관측: 10초 중 원본 73프레임, CAMERA_LINE 73/73 visible, keeper debug 73건, final cmd 500건 모두 0.
두 번째 수동 직진과 겹친 관측: 원본 80프레임, CAMERA_LINE **80/80 visible**, keeper debug 80건,
final cmd 501건의 최대 직진 명령 0.03 m/s·각속도 명령 0. 마지막 keeper 전략 `both`,
목표 `(0.249, 0.016)` m, 관측 오차 −0.177, 신뢰도 0.9.

CORE `/line-follow/perception`은 실제 출처 `threshold`, source age 0.047초, lane mode `keep`를 반환했다.
`applied: false`는 설정 응답의 플래그이며 최근 keeper receipt의 출처 readback과 구분한다.
이는 학습 모델 사용 증거가 아니다. NOMINAL 기하는 측정 교정이나 FIELD 수용을 대신하지 않는다.
8kcn의 관측 설정과 주행은 변경하지 않았다. 안전 상태 UNKNOWN을 해제하거나 수용으로 바꾸지 않았다.

## 대시보드 수정과 검증

콘솔이 차선 추종 시작에 `navigation.goal_navigation`을 요구하는 오류를 재현했다.
D-344 §7과 서버 MOVE 권한에 맞춰 `teleop === true && runtime.drive === "ready"`로 확인한다.
구동 증거가 없으면 계속 막고, Nav2가 없어도 구동 준비가 확인된 경우 시작 버튼을 제공한다.
OFF 정지 경로와 기존 확인 대화상자는 유지한다. 새 권한이나 무인 자동 주행 경로는 추가하지 않는다.

새 브라우저 회귀는 수정 전 실패, 수정 후 통과했다. 독립 검토 세션은 관련 브라우저 3개를 통과했다.
전체 패널 검사에서 main에도 있던 peer approval import/section fixture 불일치를 확인했고,
실제 모듈 라우트와 작업별 section 선택으로 fixture를 수정했다. 제품 안전 정책은 바꾸지 않았다.
호스트 검사와 signed payload 배포 결과는 각각 별도 증거로 기록한다.
최신 main 병합 뒤 관련 브라우저/API/대시보드·공개 provenance 검사는 **79 PASS, 0 NEW**였다.

증거: `X:/DevTemp/line-remote-20261005/`의 `keeper-manual-rosy-pinky-9dfk-camera.json`,
`manual-result.json`, `keeper-manual-operation.txt`, `keeper-apply.txt`, `logout.json`.
첫 직진 상세 파일은 두 번째 시험으로 갱신되었으므로 첫 수치는 도구 실행 출력의 기록에 한정한다.
독립 검토: `X:/DevTemp/line-remote-review-20261005/browser-tests.txt`.

자동 조향·곡선·교차로·완주·무인 추종의 성공률과 이탈 거리는 측정하지 않았다.
