# D-916 intake 원본 시각 보존 검증

코드 기준은 `commit 724ecfbff1edb5cff7b1d650a33b37e23d2d52c4`다. 내부 frozen JointStateSnapshot에 원본 stamp/현재 source clock 값을 함께 보존한다. 이 정수쌍은 UTC·검증된 clock domain/epoch·publisher identity·owner admission 증거가 아니다. HTTP/UDS·D-915 physical proof에 새 의미를 부여하지 않았다.

## 확인한 결과

| 실행 | source commit | 실제 결과 |
|---|---|---|
| 기본 runner의 신규 intake RED | `commit 77c1f6abfb` | 11 failed/19 passed, NEW11; metadata 부재·미지원 인수 |
| focused intake/owner/preflight/진단 GREEN | `commit 724ecfbff1` | 139 passed/0 skipped, NEW/known/flaky 0 |
| 실제 native ROS RED | `commit 77c1f6abfb` | 1 failed/1 passed; source_stamp_ns 부재 AttributeError |
| 실제 native ROS GREEN | `commit 724ecfbff1` | 2 passed/0 skipped; callback 객체 전달, source replay 이후 기존 stale HOLD/cancel 보존 |
| 공식 lab FULL 행렬 | `commit 724ecfbff1` | 공식 full_invocations 27개 실행 중; 아직 완료로 보고하지 않는다 |
| 실제 Gazebo 수동 intake/state 진단 | `commit 724ecfbff1` | intake-only 실행 terminal 0, native ROS 2 passed/0 skipped, 세 state 응답의 source 시각·iteration 증가 |

기존 네 positional 인수, accepted sequence, source age를 차감한 received_at, 거절 이후 이전 state 보존과 명령 판정은 유지한다. 원본 metadata가 나중 거절 진단 mutation으로 바뀌지 않음을 확인한다. 새 int 상한을 넣어 기존 intake 범위를 바꾸지 않았다.

실제 ROS 시험은 기본 venv의 importorskip을 통과로 세지 않고, 고정 source와 기존 Jazzy SDK를 source한 별도 bounded native 실행에서 수행했다. 생산자 module origin이 고정 checkout 아래임을 확인했다. 수동 Gazebo 진단은 별도이며 source barrier·UTC mapping·전체 link/velocity/gripper/held 수용을 뜻하지 않는다.

## 수동 Gazebo 원본과 측정 누락

격리된 native 실행 `sim-724ecfbff1-5bdf78`은 실제 `/joint_states`를 `JointStateIntake`로 구독했다. accepted stamp 78,000,000 ns, source-now 80,000,000 ns, sequence 7이 같은 snapshot에 보존됐다. 명령 목표와 Fleet physical observation 제출은 모두 0이다. 첫 진단의 disabled runtime 생성은 기존 명시적 enable 가드로 중단됐고, 가드를 바꾸지 않고 runtime 없는 intake 구독으로 수정했다. 이후 메모리 floor 미달 배정은 시작 전 거절됐으며, 성공 실행과 구분한다.

설치된 gz-sim 8.15.0의 `/world/omx_cell_workcell/state`에서 SerializedStepMap 원문을 세 번 확보했다. 각 응답은 63 entities이며 sim 시각은 194/304/410 ms, iteration은 97/152/205, paused=false였다. 요청·응답 UTC/steady 끝점은 진단 JSON에 별도로 남겼고 capture UTC로 복사하지 않았다.

| 원문 | SHA-256 |
|---|---|
| full-state-0.pb | `51e0ec82b84535b4d84fbd417c9be96a6caa0a58b776315cfc2801c1125a0d9b` |
| full-state-1.pb | `d95ecb60ec628db2c263507d1543f895d208e18e517fc97c30664d1402731a37` |
| full-state-2.pb | `3591ca5369361eaa007667cd0162abeb4c83f5aac07e9cb052612ce791e8fa56` |

첫 원문의 52 component type 모두를 설치 SDK의 components/*.hh 등록명과 Factory.hh가 사용하는 common/Util.hh의 hash64(FNV-1a 64-bit)로 대조했다. JointPosition/JointVelocity는 joint1–5와 gripper_joint_1/2의 7 entities에 있다. WorldLinearVelocity는 이름 없는 entity 3 하나에만 있으며 participant/link 속도 coverage가 아니다. WorldAngularVelocity, ContactSensorData와 DetachableJoint는 없다. component 존재 자체로 값의 finite·frame·단위·대상 적합성이나 held 판정을 수용하지 않는다. 접촉 부재를 비접촉으로 해석하거나 관절 개방을 물체 해제 증거로 바꾸지 않는다.

[동일 버전 SceneBroadcaster 소스](https://github.com/gazebosim/gz-sim/blob/gz-sim8_8.15.0/src/systems/scene_broadcaster/SceneBroadcaster.cc)의 StateService는 PostUpdate 직렬화를 기다린다. 요청 도착 전에 시작한 iteration도 처리될 수 있으므로 응답 완료만으로 physics capture-after-request는 입증되지 않는다. 다음 단계는 첫 source iteration을 기준점으로 삼은 이후 capture, source reset/pause/늦은 응답 배제, 검증된 clock profile, 전체 대상 속도·접촉 측정의 계약·회귀 검증이다. 기존 D-915 UTC 필드를 요청/응답 시각으로 채우는 임시 연결은 하지 않는다.

원문·진단 JSON은 `%TEMP%/rosy-pipeline-g1c-native-passive/out/`에 있다. `source-barrier.json`의 capture_utc_mapping=UNVALIDATED, full_measurement_coverage=NOT_ESTABLISHED를 유지했다.

## 실행 범위와 이전 보고 정정

기존 D-915 기록의 25,723 통과는 mode=full에서 선택된 local_invocations 네 묶음이었다. native CLI의 affected_invocations()는 mode=full도 local_invocations를 소비한다. 공식 lab FULL은 affected_tests.lab_full_invocations()가 만드는 별도 전체 목록이다. [원래 기록의 범위 정정](../physical-evidence-export-2026-10-29/result.md)을 보존했다.

이번에는 고정 selector의 공식 27개를 native runner가 소비하는 배열에 그대로 공급했다. 차이는 root test 묶음의 ROSY_BROWSER_ALONE=1 및 -n 0뿐이며 파일은 제거하지 않았다. 독립 최종 리뷰가 원래 배열과 직접 비교해 확인했다. 진행/실패/skip을 최종 통과로 바꾸지 않는다. [재발 방지 교훈](../../solutions/workflow-issues/full-mode-json-does-not-prove-full-matrix-execution-2026-10-29.md)은 이 실행 계층 구분을 설명한다.

### 최초 Fleet 실패와 테스트 수정

공식 행렬 run-13은 1 failed/7,270 passed/413 skipped, known-failure 비교 NEW1/known0/flaky0이었다. `operations/fleet/test/test_ai_facts.py::test_more_than_two_fact_posts_a_second_is_429`의 세 요청 결과가 기대 [200,200,429] 대신 [200,200,200]이었다. 실제 요청 처리 시간은 이 로그로 확정하지 않는다. production `AiFactsBoard.admit_post()`는 주입된 monotonic clock에서 1초가 지난 요청을 만료시키므로, 기존 시험은 실행 지연에 의존하며 이 실패만으로 production 결함이 입증되지는 않는다.

후속 테스트 전용 `commit f2af364bcf`는 기존 FakeClock과 _app(clock=...)를 사용한다. 기존 세 응답 assertion을 유지하고 .999초의 429와 정확히 1초의 200을 추가했다. 독립 리뷰에서 정책 약화·추가 P1/P2 없음. production/known-failure/quarantine은 바꾸지 않았다. 수정 source는 `%TEMP%/rosy-pipeline-g1c-fleet-clock-green/`에서 별도 원격 검증하며 최초 행렬의 실패를 지우지 않는다.

외부 scratch는 `%TEMP%/rosy-pipeline-g1c-intake-{red,green}/`, `%TEMP%/rosy-pipeline-g1c-native-{red,green}/`, `%TEMP%/rosy-pipeline-g1c-actual-full/`다. native ROS의 ros-runtime.txt와 원격 terminal code를 기본 pytest 보고서와 구분한다. 실제 simulation은 모델 역할의 격리 domain/partition에서만 시도하며 site PC·실물 장치에 실행하지 않는다.

소스 contract/Safety 및 fresh-context 전체 변경 리뷰에서 추가 P1/P2 결함은 없었다. source review는 실제 stop·운영·장치 안전 인증이 아니다. 설치·배포·착지·push를 수행하지 않았다. G1c 전체와 G2–G6는 아직 미완료다.

문서 harness lint는 0 errors/40 warnings다. warnings는 모듈별 오래된 last_verified·변경 누적 등의 상태 경고이며, 이번 source나 field 수용으로 해소한 것이 아니다. 생성 index와 ADR Log의 UTF-8 BOM/CRLF 보존을 확인했다. CE claims/frontmatter 검사는 UTF-8 모드에서 통과했다.

CE: 새 교훈 기록 — FULL JSON 판정과 실제 실행 행렬의 차이를 정본 함수·배열 비교·실행 로그로 확인하고 이전 범위 표기를 정정했다. 원본 source barrier는 미해결로 남긴다.
