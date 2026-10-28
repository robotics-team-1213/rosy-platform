# 학습 정책의 제어기 추종 관측

2026-10-24 KST 기록이다. [기존 engineering HOLD](../omx-recovered-policy-engineering-2026-10-24/result.md)의 실패 원인을 구분하기 위해 SIM의 읽기 전용 제어기 관측을 추가했다. 원래 학습·모델·실패 평가·formal0회는 보존한다. 관측 추가를 정책 작업 성공이나 물리 원인 해결로 해석하지 않는다.

## 변경과 회귀

runtime source는 `bbf2af074bb7`이다. `arm_controller/controller_state`에서 설치된 Jazzy 메시지의 `reference`·`feedback`·`error` 위치와 속도, 원본 ROS 시각·수신 owner 시각·관절 순서를 최대10Hz·6000개로 수집한다. 현재 명령 참조는 관측 연결용이며 controller goal과의 인과적 연결을 보증하지 않는다. 빈 속도 배열은 원본 그대로 보존한다.

수집기는 자체 lock만 사용하며 owner/session lock·lease·admission·관측 freshness·목표 생성·허용치·terminal 판정을 바꾸지 않는다. malformed 입력·상한 초과·수신 없음·파일 쓰기 실패는 진단 불완전으로 남기며 원래 정책 결과와 정리를 덮지 않는다. 파일은 제어 종료 뒤 기록한다.

RED source `085bde4d38`에서 새 모듈 부재로 collection이 실패한 뒤 구현했다. 위 runtime commit의 원격 AI 회귀는 새 수집기10개와 기존 정책 runtime·camera·trial evidence·설정·demonstration106개, 총116개를 실행했다. 실제 로그의116개 passing 표시와 종료0을 확인했고 known-failure 비교는 NEW0·known0·flaky0이다. skip 표시는 없다. 명령은 다음과 같다.

```text
python tools/remote/remote_pytest.py --log-dir <scratch>/green -- test/test_omx_sim_policy_tracking.py test/test_omx_sim_policy_runtime.py test/test_omx_sim_policy_camera.py test/test_omx_policy_trial_evidence.py test/architecture/test_omx_policy_config.py test/test_omx_pick_place_demonstrations.py -q
```

독립 검토는 읽기 전용 구독부터 collector·post-cleanup receipt까지 확인했고 Important 지적이 없었다. 이는 수집 코드의 회귀 근거이며 실제 controller 메시지 수신과 정책 작업 성공은 별도다.

## 원래 실패 상태의 기술적 비교

원래 train20개31,787행을 동결 archive와 byte 단위로 대조하고 선택한 실제 rollout 상태와 raw 관절값의 최근접 최대 절대 차이를 계산했다. validation은 이 비교에서 제외했다. 마지막 입력의 최근접 차이는 약0.02696rad다. 같은 기존 순기구학으로 계산한 TCP는 최근접 teacher보다 약7mm 낮고8mm 안쪽이며 공구 기울기는 약3.3도 다르다. 이 계산은 기술 통계이며 새로운 품질 기준·OOD 판정·접촉 원인 증명이 아니다.

원본과 로컬 증거는 Git 밖 `learning-execution-20261023/joint-tracking-diagnosis-20261024/`에 보존한다. 원본 SQLite·이미지·가중치·private 설정은 공개 기록에 넣지 않는다.

## 사전 고정과 실제 calibration

별도 manifest와 driver를 독립 검토한 뒤 실행했다. 원래 평가60개 pins·새 입력8개·manifest 자체, 총69개 실제 해시를 검사했고 중복 덮어쓰기는 없다. driver는 매 호출과 자원 대기마다 같은 검사를 반복하며 calibration1회·instrumented episode1회·formal0회·추가 optimizer0회로 제한한다. protocol의8개 위반 및 잘못된 manifest binding을 거부하는 assert 검사도 통과했다. staging helper의 원래 campaign 기준 선언20회/18성공은 유지하며 driver는 그 formal loop를 호출하지 않는다. 이 진단은 기존 평가를 대체하지 않는다.

모델·고정 world 설정·허용치·timing 조건은 유지한다. simulation seed는 원래처럼 기록되지 않았으므로 같은 궤적의 결정적 재현이나 무작위 일반화 검사는 주장하지 않는다.

같은 부모 모델로 위 source의 native ID suffix `eb3932d8a7be`를 한 번 실행했다. 실제 종료0·calibration PASS·12개 추론 검사·정책 목표0개다. 추종 기록331개는 malformed0·상한 초과 없음이며 모든 sample의 reference/feedback/error 속도가6개씩 존재한다. 원본 archive96개 파일·map·result/exit·동일 source/run을 byte 단위로 대조했다. 09:10:05 KST 종료 관측은 main PID0·inactive·빈 cgroup·잔여 cgroup 없음·lock/예약 없음이다. cleanup_verified=true를 확인한 뒤에만 정책 진단으로 넘어갔다.

| 고정·회수 근거 | SHA-256 |
|---|---|
| 진단 manifest | `sha256:23a5c583ada813d630f0ab030b8d362d19c23b8072cc85aa30423f32fccd8510` |
| 진단 driver | `sha256:4d7c7e59a989330b5a252f75b654f19cd9efceade7d4d190f189511278b2d73a` |
| calibration archive | `sha256:f0b80b74a1f503ea26201f01d002e428047ef1e1102ce0b6d34c1f5de7da56bf` |
| calibration map | `sha256:a74aa816d9c135bbbeff77e03852b2713597f860c884d81eb5895cd4f005a472` |
| calibration 추종 기록 | `sha256:b9dc45f154559486976a6ee8f9d8fdc14a62f30b00c6232e8021b71ce27a0223` |

## 실제 정책 진단: lease 만료로 HOLD

같은 source의 native ID suffix `1cb9bea72585`는 실제 종료1이다. 원본42개 policy step 중41개 목표가 수락됐고41개 terminal은 모두 status4/result0이다. SQLite에는42개 intent가 있으며 마지막 intent의 driver goal은 NULL이다. 마지막 목표는 전송되지 않았다. actor 오류는 `policy_lease_expired_or_invalid`, worker 기록은 `lease_renewal:policy_lease_expired_or_invalid`이며 owner는 HOLD다. admission rejection은 없다.

마지막 intent와 admission timing을 대조했다. 당시 lease 발급/만료는 각각11571306550145ns/11572306550145ns였다. `journal_prepare`는11571598786969ns에 시작해11572332517474ns에 끝났으며733.730505ms가 걸렸다. 시작 때 남은 lease 시간은707.763176ms이고, 반환 시점은 만료보다25.967329ms 늦다. 직후 guard는 만료보다25.994498ms 늦게 시작했고 실제 lease 검사에서 제출을 거부했다. session lock은 prepare와 최종 guard를 감싸며 renewal도 같은 lock을 요구한다. worker 오류만으로 renewal이 먼저 실패를 일으켰다고 결론 내리지 않는다.

마지막 추론775.498ms와 submit822.659ms도 보존한다. 하지만 긴 추론 자체나 새 telemetry가 만료를 일으켰다고 단정하지 않는다. 실제 기록은 intent에 저장된 lease가 prepare 구간 안에서 만료된 사실을 증명한다. 전체 prepare에는 연결 생성·source 조회·직렬화·writer 대기·FULL-synchronous commit·연결 종료가 포함되어 있어 특정 SQL 단계나 fsync를 지연 원인으로 지목할 수 없다. renewal의 발급/시작/lock 획득/설치 시각도 아직 기록되지 않았다. 읽기 전용 코드 검토에서 durability·sequence 검사 결함은 확인되지 않았으며 이를 완화하거나 추정한 저장 방식으로 바꾸지 않았다.

추종 기록748개는 malformed0·상한 초과 없음이며 모든 위치·속도가 유한한6관절 배열이다. 보존한 최대10Hz 관측의 최대 절대 위치 오차는 관절 순서대로 약0.002567/0.000695/0.000861/0.001629/0.000813/0.001218rad다. 모든 sample에서 기록된 error는 reference−feedback과 일치했다. 이 실행은 원래169번째 성공 뒤의 JTC 허용오차 실패까지 도달하지 않았으며 원래 물리 실패를 재현하거나 해결한 근거가 아니다.

archive126개 파일·111,149,834바이트·map·원본 result/exit·동일 source/run을 대조했다. 09:15:40 KST 종료 관측은 main PID0·failed·실제 exit1·빈 cgroup·잔여 cgroup 없음·lock/예약 없음이며 cleanup_verified=true다. 독립 검토도 archive·SQLite·timing·trace·안전 정리를 대조했다. 로컬 coordinator 종료0과 `diagnostic_collected`는 진단 회수 완료만 뜻하며 실제 정책 결과는 false/HOLD다. 추가 실행이나 formal 재평가는 하지 않았다.

| 정책 진단 근거 | SHA-256 |
|---|---|
| 최종 진단 ledger | `sha256:c525f5b4fae29239d2a4c4fa2f0034420b0cb5d1cb6db1671e02e0891bfee16b` |
| 정책 진단 archive | `sha256:dc58fbbce212f804eb264b2a584fef77e702ea0f2bdab25c51b7d99585576da8` |
| 정책 진단 map | `sha256:22fff4008f8916ddc6bd74a8b922642e869d76a709b079cbf9b30570d805b7de` |
| 정책 진단 추종 기록 | `sha256:63aa1de79f3e1220e75fca96c372be78be8f8859b3db671714ebd98cb45338fe` |
| SQLite·timing·trace 파생 분석 | `sha256:70c9fd634d92c15bb31ee226703a3ec1fb474c37ffd15a1c5588fc808a5bae42` |

CE: 미해결 — 원래 추종 실패의 물리 원인과 새 prepare 지연의 세부 원인은 미확정이다. 관측 코드·회귀·이 기록이 보완 내용을 설명하며, 해결된 교훈이나 정책 품질·운영·실물·HF 수용으로 승격하지 않는다.
