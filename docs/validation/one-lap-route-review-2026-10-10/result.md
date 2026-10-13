# 유한 한 바퀴 경로 판단 수정과 독립 검토

## 수정과 원격 증거

- 검증 후보 commit `cb505c760`은 알려진 기종의 공칭 차체를 `core_common.robot_body.nominal_body_for`에서 선택하고, 미지원 기종은 차체가 없는 것으로 처리한다. Fleet에 기종 문자열을 중복하지 않는다.
- AI 경로 분석이 캐시된 `pose.age_s`만 읽어 10초 전에 멈춘 자세도 새 `ON_ROUTE`로 발행하는 문제를 독립 검토자가 재현했다. 새 `pose_observed_at`은 자세를 읽은 순간의 wall timestamp이며, junction 조회·명령·trip 저장 지연으로 갱신하지 않는다. AI는 표본 나이와 읽은 뒤 경과를 합산한다. 1.5초 초과, 없는 시각, 비유한 시각·나이, 음수 나이, 0.5초를 넘는 미래 시각은 `UNKNOWN`이다.
- AI snapshot 관측 시각은 HTTP 읽기가 모두 끝난 시각이다. 신규 regression 세 건을 시험 PC에서 먼저 실패시킨 뒤 수정했다. 수정 후 AI 상황 서비스, 공칭 차체, Fleet trip runner, 구조·비밀·기종 문자열 검사 원격 묶음 exit 0, `known_failures.py` 신규 0·기존 실패 0. 로그: `X:/DevTemp/one-lap-stale-red/run-1.txt`, `X:/DevTemp/one-lap-stale-green/run-1.txt`.
- Fleet의 delayed-junction regression은 자세를 읽은 뒤 저장까지 3초가 지나도 `pose_observed_at`이 과거 값을 유지하는지 검사한다. AI 회귀시험은 저장 시각만 최신인 오래된 자세를 `UNKNOWN`으로 검사한다.
- 독립 검토자 `lap_review`가 차체 선택, 자세 관측 시각과 입력 신선도, API reference·D-613을 재검토해 승인했다. Fleet 크기를 직접 51,507줄로 측정하고 기존 `split` 판정과 localization/observe 분리 의무를 보존한 재판정에 동의했다.
- 별도 실제 Chromium 시험은 현장 시험 PC에서 AI 경로 편차 경고 표시와 새 `ON_ROUTE`에 따른 경고 해제를 확인했다. 열린 trip이 있고 교착이 없어도 조회하며 주행 명령은 보내지 않는다. 로그: `X:/DevTemp/one-lap-ai-route-browser/run-1.txt`.
- main 통합 후보 commit `51c256284`의 원격 착지 1차 묶음은 6,123 + 4,278 + 3,388 = 13,789 passed, 각 로그의 `known_failures.py` 신규 0·기존 실패 0이다. 460건은 skip으로 통과 증거가 아니다. 검사 중 main이 변경되어 최종 착지 후보는 추가 검증한다. 로그: `X:/DevTemp/land/feat-one-lap-current/run-1-{1,2,3}.txt`.
- AI PC에 통합 후보 commit `70c750457`의 소스를 별도 staging 경로로 전달해 SHA256 `89476e7c0705cd04a0e392c0379609fadfdc2632a2b24dac0edc83e81e0bf198`를 대조했다. 그 AI PC에서 새 모듈 v0.3.0을 읽고 합성 입력의 `ON_ROUTE`, `OFF_ROUTE`, 오래된 입력 `UNKNOWN`을 자체 확인했다. 상주 서비스는 변경하지 않았고 Fleet에 합성 사실을 보내지 않았다. 로그: `X:/DevTemp/one-lap/ai-stage-proof.txt`.
- 2차 통합 묶음에서 안전 경계 검사 `test_decision_and_learning_use_only_safety_public_api`가 새 차체 선택 함수의 공개 선언 누락을 신규 실패로 검출했다. 이를 기존 실패로 처리하지 않는다. 독립 검토자 `lap_review`는 기존 읽기 전용 공칭 차체와 `None`만 반환하는 선택 함수 하나의 `public: true` 등록을 승인했다. 명령·안전 정책을 공개하지 않으며 기존 위반 목록이나 검사기를 완화하지 않는다. 수정 후 원격 안전 경계 재검증이 필요하다.

## 기존 병합의 소급 안전 검토

통합 이력의 commit `dc4ef1a90f3f8c28db9eccbf7b9288980eb297fe`에는 안전 검토 trailer가 없다. 독립 검토자 `lap_review`가 부모별 diff와 AST를 비교해 소급 소스 검토를 승인했다.

- `safety.py`는 첫 부모 commit `ff1f70b3c83856050170ddc41d8ae1df373c02d0`와 AST가 동일하다. 첫 부모에는 별도 독립 `Safety-Review: APPROVE WITH NOTES`가 있다.
- 병합에서 새로 해결한 행은 주석의 API 버전 `v1.195` → `v1.196`뿐이다. 관리자 전용 해제, IDLE과 E-Stop 래치가 함께 있는 경우의 복구, NAV/MANUAL 거절, 도킹 복귀 취소는 부모의 구현을 보존한다.
- 기존 안전 검사기의 `EXEMPT` 규칙에 전체 commit과 이 근거를 기록했다. 동료 커밋은 수정하지 않았고 검사 규칙을 완화하지 않았다. 이 소스 검토를 시험 실행이나 장치 수용으로 기록하지 않는다.

## 현장 상태와 미완료

이번 세션 읽기에서 Fleet·Vision·proxy 설치 commit `21a92b2f422a73a655bc04894e4c8f09867f1b82`는 healthy이며 자동 갱신 timer는 active다. AI PC 상주 서비스는 v0.2.0, shared, heartbeat present였다. 새 구현의 설치 증거가 아니다.

두 로봇은 온라인 IDLE, 열린 trip 0이다. `rosy_40`은 `junction_turn:false`, `rosy_41`은 `E_mid`에서 약 0.754 m 떨어져 있다. 사용자는 현장 감독과 출발 위치 준비가 가능하다고 확인했다. 시험 PC의 Gazebo 자원은 부족하다. 설치·능력·출발 자세·SIM·독립 물리 관측은 각각 확인해야 한다.

**FIELD HOLD:** AI 사실은 shadow다. 기존 Fleet 중심 기준 정지와 공칭 반폭 검사는 회전 자세, 위치 오차, 정지 거리까지 포함한 실제 차체 이탈 방지 증거가 아니다. 두 로봇의 물리적 한 바퀴 복귀·정지와 무이탈은 미확인이다. 노트북에서 pytest·Chromium·Gazebo는 실행하지 않았다.

## 재개 후 전달 준비 (2026-10-10 09:54 UTC)

- commit `016ca6b6d09ccff0c8b8ab5045761e96e0276fe7`은 원격 AI PC에서 310 passed, NEW 0·KNOWN 0을 확인하고 공유 main에 fast-forward 착지했다. 로그는 `X:/DevTemp/land/feat-one-lap-current/run-1-1.txt`이다. 이전 같은 이름의 로그는 덮어쓰였으므로 앞선 회차의 수치와 혼동하지 않는다.
- 통합 검증 기록의 네 해시는 실제 Git commit임을 대조하고 명시적으로 표기했다. 같은 시각 main에 추가된 exact-line 예외 4개는 그 문구 수정으로 오래된 항목이 되었다. 독립 검토자 `lap_review`는 그 4개만 삭제하는 수정을 승인했다. 다른 104개 예외와 검사 규칙은 유지했다. 위 310개 원격 시험에 secret boundary·public provenance 검사가 포함된다.
- commit `ca8068c81d98`의 push 전 검사는 최초 묶음에서 위 문서 표기 문제로 NEW 1을 검출했고, 후속 두 묶음은 각각 5,663 passed·215 skipped 및 4,802 passed·375 skipped, NEW 0·KNOWN 0이었다. Fleet 및 나머지 묶음은 진행 중이다. `ca8068c81`에서 `016ca6b6d`까지 최종 tree 차이는 검증 문서의 표기뿐이며 제품 소스는 같다. 로그는 `X:/DevTemp/remote-pytest/ca8068c81d98/run-{1,2,3}.txt`이다. 원래 실패한 로그를 녹색으로 바꾸거나 건너뜀을 통과로 세지 않는다.
- AI PC의 기존 `~/rosy-platform`은 Git 저장소가 아닌 운영 소스 복사본이다. 이를 보존하고 `~/rosy-situation/repo`에 별도 Git 배포 저장소를 준비했다. 후보 commit `016ca6b6d09ccff0c8b8ab5045761e96e0276fe7`은 분리 worktree에 적재했으며 source tree `13301b9c26cddb6b0d9b82fdcff52c043911979a`, 전달 bundle SHA256 `03db3b31d14f172909eb2385fdb94d52ae9d937b71a532408f210ae4bdf459a1`을 대조했다. 해당 AI PC에서 service v0.3.0과 `build_commit: 016ca6b6d09c`를 읽었다. 상시 유닛은 재시작하지 않았고 합성 사실은 Fleet에 올리지 않았다. 근거는 `X:/DevTemp/one-lap/ai-git-stage-proof.txt`다.
- 최신 현장 읽기에서 AI 상시 서비스는 여전히 v0.2.0/shared/present, 열린 trip은 0이며 두 로봇은 IDLE·line-follow OFF였다. `rosy_40`은 `junction_turn:false`, W_mid에서 약 0.517 m였고, `rosy_41`은 지도 자세 DEGRADED, anchor age 약 79.7 s, E_mid에서 약 2.231 m였다. 미보고 sensor_health는 건강함을 뜻하지 않는다. 주행·모드·E-Stop 명령은 보내지 않았다. 근거는 `X:/DevTemp/one-lap/readiness-idle-current.txt`, `motion-diagnostics-current.txt`다.
- 한 바퀴 후보의 착지·push 승인은 유지된다. 이후 main에 포함된 전체 통합의 기록에는 별도로 로컬 착지만 승인되고 push는 제외된 것으로 명시되어 있다. 그 추가 공개 범위와 최종 후보 검사를 확인한 뒤 원격 main 및 CI·설치 SHA를 검증한다. source staging은 상시 배포나 현장 수용이 아니다.

남은 검증: 최종 공개 후보의 push 관문·CI, 현장 Fleet/CORE 이미지, AI 상시 v0.3.0과 heartbeat build_commit, Gazebo 동시 한 바퀴, 기기 회전 능력·신선한 출발 자세, 두 로봇의 물리적 한 바퀴 복귀·정지와 차체 경계 무이탈. 목표는 계속 미완료이며 AI 경로 사실은 shadow다.