# OMX feedback·관절 이동 후속 검증 (2026-10-18)

## 판정과 범위

AI 시험 PC의 실제 Gazebo controller에서 `rule_based` 관절 명령 완료와 joint-state 이동을 확인했다. 이 결과는 LeRobot 학습 정책의 작업 성공, Fleet→장치 lease 전달, 물리 로봇 구동을 입증하지 않는다. 해당 경로는 아직 별도 수용 증거가 필요하다.

검증 소스 commit: `4b97b23ac76e1efe7a86c68ad2b6c7f866f8de4e`. 변경은 선택적 시험 계측과 고정 횟수 진단 wrapper뿐이다. 생산 admission, freshness, executor thread 수, timeout, quarantine은 바꾸지 않았다. 원격 시험은 committed revision을 전송하는 `tools/remote/remote_pytest.py`, 시뮬레이션은 `tools/remote/remote_sim.py`로 실행했다. 아래 상대 로그 경로는 외부 보존 폴더 `C:/Users/SERIGGG/AppData/Local/Temp/rosy-omx-feedback-fix/` 기준이다. 원시 로그에는 호스트 정보가 있어 저장소에 넣지 않았다.

## Native feedback 진단

이전 CORE runtime 검증과 main에서 `test_slow_feedback_handling_cannot_starve_the_joint_state_subscription`이 `joint_state_stale`로 실패한 기록을 보존한다. 같은 revision의 단독 통과만으로 그 실패를 해소했다고 판정하지 않았다. 이 진단은 최초 HOLD, source timestamp, intake 수락·거절, owner lock 대기·획득, thread stack을 기록한다. 유효 시각을 새로 쓰거나 실패를 통과로 바꾸지 않는다.

| 사전에 정한 실행 묶음 | 결과 | 로그 |
|---|---|---|
| 계측 켠 단독 native 사례 5회 | wrapper 5 passed | `samples/run-1.txt` |
| 계측 켠 native 8개 전체 suite 5회 | wrapper 5 passed, 다른 묶음 5 deselected; 내부 40 passed | `suite-samples/run-1.txt` |
| 계측 끈 native 8개 전체 suite 5회 | wrapper 5 passed, 다른 묶음 5 deselected; 내부 40 passed | `untraced-suite/run-1.txt` |
| 변경하지 않은 main (commit: `a2076ddd8d79fd9cb1f19fc436925e00bdbdb667`) 전체 suite, 별개 호출 5회 | 매 호출 wrapper 1 passed·내부 8 passed | `main-fixed-1/run-1.txt`부터 `main-fixed-5/run-1.txt` |

계측 켠 단독·전체 묶음에서 HOLD와 intake 거절은 없었다. 최대 intake 간격은 각각 약 0.03887s·0.03328s였다. 기존 freshness 0.2s, slow sink 0.6s, executor 4 threads를 유지했다. 계측 자체의 영향을 배제하기 위해 계측 없는 묶음과 수정하지 않은 main도 별도로 실행했다. 이 20개 표본 호출의 통과는 간헐 실패의 원인 규명이나 영구 수정 증거가 아니다.

`--keep-duplicates`로 동일 node ID를 다섯 번 전달한 별도 시도는 실제로 한 번만 수집됐다. 그 로그 `unchanged-main-five/run-1.txt`는 5회 증거에서 제외했다. 이후 위 main 시험을 별도 호출 다섯 번으로 실행했다.

- SHA256: `fdd923c8e7a5ff358be04064d9035018219f052d62a33e7cb383f4498d2dc850` (`samples/run-1.txt`)
- SHA256: `87ba3171adb8618023709b7a66652d9f2f32d1ce8391e5605b1647e0c25a872f` (`suite-samples/run-1.txt`)
- SHA256: `0ea1fa6b5f494f75b67830ab619452c37fdd7eb490701faf9ba53b20fea352a2` (`untraced-suite/run-1.txt`)

## Gazebo 실제 관절 이동

AI 시험 PC에 `joint_trajectory_controller/JointTrajectoryController` plugin이 없어 controller 로드가 실패했다. 기존 `deploy/robot/omx/hardware_readiness.py`는 이미 이 패키지를 필수로 검사한다. 사용자에게 정확한 버전을 승인받고 사람이 SSH sudo 인증을 완료한 뒤 `ros-jazzy-joint-trajectory-controller=4.42.1-1noble.20260924.190511` 하나를 설치했다. dpkg 설치 상태를 확인했다. 기존 패키지 업그레이드·삭제는 없었다.

시뮬레이션은 별도 ROS graph에서 기존 준비된 vendor overlay와 실제 `RosArmCommandRuntime`을 사용했다. owner는 `rule_based`, workcell·instance와 calibration은 명시적인 합성 SIM 값이다. 외부 probe는 snapshot sequence가 전송 전에 전진할 수 있으므로 기존 owner의 start-reference 검사에 원래 위치와 최대 0.001rad tolerance를 전달한다. source sequence와 timestamp를 갱신하거나 안전 기준을 완화하지 않았다.

실행: `remote_sim.py --host ai --sha 4b97b23ac --minutes 12 --log-dir <external>/gazebo-ai-installed cmd -- <vendor launch + probe>`.

| 측정 | 결과 |
|---|---|
| 원래 관절 위치 | 0.000000180818rad |
| 목표 | 0.010000180818rad |
| 관측 위치 | 0.008547306061rad |
| 관측 이동량 | 0.008547125243rad |
| 목표 절대 오차 | 0.001452874757rad |
| terminal | `completed` |
| source sequence 전진 | true |

실행 전 정한 기준은 이동량 >0.007rad, 절대 오차 <0.003rad였다. 둘 다 통과했다. trace는 최초 HOLD 없음, 수락 intake 98개, advancing source 검사 거절 1개를 기록했다. 거절된 source를 fresh로 바꾸지 않았다. 최대 수락 intake wall 간격은 약 0.15630s였다.

- SHA256: `4dbfb518250c3803ad36b795e25074da4315d68ccb1e8d0df910c284fe242fce` (`gazebo-ai-installed/run.txt`)
- SHA256: `35786786db14b731c1dc2562f3e3a4e788c21e35c0e37864fe081877e7a00f94` (`gazebo-ai-installed/out/executed-probe.py`, 실행 당시 원본 보존)
- SHA256: `3cfa398056169ca084f7339ef2e0b339ad0c18d88d24637bbe91f348c93f53b8` (`gazebo-ai-installed/out/feedback-trace.json`)

### 후속 이동 중 취소·위치 안정성

동일 소스 revision의 `gazebo-ai-stop-final`은 exit 0이었다. 실행 자원이 부족한 동안에는 runner가 시작을 거절했고, 30초 간격으로 배치 가능 여부만 확인했다. 시뮬레이션이 시작된 뒤 실패를 재시도한 결과가 아니다. placement floor와 host cap은 유지했다.

첫 목표 0.01rad는 `completed`였고 1초 settling 뒤 이동량 0.009999965723rad, 목표 오차 약 0.00000003428rad였다. 이는 단일 SIM 표본이며 장치 정확도 수치로 쓰지 않는다. 두 번째 목표는 1초 동안 추가 0.01rad 이동이며 실제 변화가 0.002rad를 넘은 뒤 같은 command를 취소했다.

| 취소·정지 관측 | 결과 |
|---|---|
| ROS driver goal UUID | `04976b3c-d45b-470d-a722-c8c0913f9fe6` |
| cancel ACK | true |
| terminal | 5 (`CANCELED`), 해당 command의 terminal event 정확히 1개 |
| owner | `hold` |
| 취소 요청 시 위치 | 0.012047898024rad |
| 이후 관측 위치 | 0.012143172324rad |
| 관측 1초 중 마지막 0.3초의 서로 다른 sequence | 12개 |
| 마지막 구간 위치 최댓값−최솟값 | 약 0.00000001397rad; 사전 기준 <0.001rad 통과 |

최초 HOLD 이유는 `cancel_requested`였다. 이 관측은 Gazebo의 취소 후 위치 안정성이며 물리 정지 거리·E-stop·torque 차단 수용을 대신하지 않는다. teardown에는 `cannot use Destroyable because destruction was requested`라는 미수거 예외 경고 3건이 있었다. 실행과 측정 assertion은 통과했지만 ROS 종료 정리의 무경고 성공은 주장하지 않는다. runner는 종료 후 해당 scope를 정리했다.

- SHA256: `9988009dac1f2380578d31d4fc45404e69de9f30b3114f93e889cd8840c23156` (`gazebo-ai-stop-final/run.txt`)
- SHA256: `3172243e6eb01ea2564c6e6d8bfc71cb795a7bcfc508259cb21edfaf4ddd980a` (`gazebo-ai-stop-final/out/executed-probe.py`, 실행 원본)
- SHA256: `05da12a0b22af471a7079cb4f0ac2063aa6a7a578cfb1359be044ec5c963c5c6` (`gazebo-ai-stop-final/out/feedback-trace.json`)

## Fleet lease와 장치 방어

`operations/fleet/test/test_policy_governance.py` 및 장치의 lease expiry·revocation 집중 시험은 원격에서 합계 14 passed였다. Fleet 시험은 실제 FastAPI/auth/SQLite를 사용하지만 dispatcher는 비활성이고 owner readback은 fixture transport다. 장치 시험도 자체 session binding이다. Fleet 시험의 `device_delivery`는 `not_connected`다.

- 장치 시험: `test_lease_expiry_cancels_active_policy_and_never_auto_recovers`, `test_watchdog_rechecks_revoked_lease_and_cancels`.
- SHA256: `c5ab3922d7ebd07c43c459b4366221700761af3c6308fb9ec6cc34225eb6c916` (`lease-guards/run-1.txt`)

따라서 검증된 것은 Fleet 발급·차단과 장치 만료·철회 방어 각각이다. 실제 전달을 완료하려면 동일 execution에서 인증된 장치 신원·승인 범위·정책 digest를 묶고, wall clock 만료를 장치 monotonic 시각으로 보수적으로 변환하고, lease 발급→수신→갱신→철회/연결 단절→HOLD·해당 goal 취소를 연계 receipt로 확인해야 한다. 현재 CORE arm HTTP는 lease 설치·갱신 경로를 제공하지 않는다. 실제 workcell이나 승인 revision을 임의로 만들지 않았다.

## 기존 증거와 착지 제한

동일 소스 revision의 원격 affected selection은 `affected-remote/run-1.txt`에서 1,281 passed, 22 skipped, 38 warnings였다. `test/known_failures.py` 비교는 0 new, 0 known, 0 flaky였다. 선택적 native 진단 등 skipped 사례는 통과로 세지 않는다. SHA256: `c07b593a245bf7e9053f6ff2b28d1b21954a55b61e61f6c0f611c67b873cbf3f`.

독립 read-only 리뷰는 위 세 시험 파일에서 안전·권한 계약 위반을 발견하지 못했고 진단 전용 변경으로 적절하다고 판단했다. 계측의 실행시간·스케줄링 영향은 남으므로 계측 켠 통과만으로 원인 해결을 주장하지 말아야 한다. 리뷰 범위는 코드이며 원시 실행 로그 검증은 포함하지 않는다.

도중 `affected --run`이 노트북 pytest를 직접 시작하는 것을 확인하고 중단했다. 그 불완전한 실행은 증거에서 제외했고, 위 결과는 `remote_pytest.py --affected-json -`로 별도 실행한 원격 결과다.

기록 추가 뒤 commit `94071ba816`의 원격 문서 배치·harness·release secret·robot literal guards는 `final-record-labeled/run-1.txt`에서 202 passed, 36 warnings, NEW 0이었다. 최초 기록의 main revision이 secret scanner에서 고엔트로피 토큰으로 분류돼 명시적인 `commit:` 표기를 붙인 뒤 이 묶음이 통과했다. 그 이후 추가한 Gazebo 취소 기록도 같은 scanner로 직접 검사해 finding 0건을 확인했다. Harness lint는 0 errors, 33 warnings였고 `size_range.py main HEAD`도 통과했다.

별도 `feat/omx-core-runtime`의 native socket 검증은 LeRobot 별도 subprocess→실제 loopback CORE HTTP→합성 SIM policy binding→native ROS fixture→disconnect fence를 다룬다. 그 증거와 이번 Gazebo 이동은 서로 다른 실행이며 이어 붙여 하나의 종단간 학습 정책 시험으로 취급하지 않는다.

이전 MAIN-RED의 간헐 stale-feedback 원인은 확정되지 않았다. 진단 branch와 CORE socket branch는 그 차단을 해제한 생산 수정으로 표현하지 않으며, 검증 기록을 커밋해 보존한다. 실물 구동·배포, 학습 정책 평가, Fleet→장치 lease 전달, GitHub CI·push는 수행하지 않았다.
