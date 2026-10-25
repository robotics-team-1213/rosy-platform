# 접촉 진단 경로: 계약·실제 SDK 검사 통과

2026-10-24, [동일 모델 추종 HOLD](../omx-policy-tracking-after-admission-2026-10-24/result.md)의 다음 관측을 준비했다. 정책 재실행·학습·실물 동작은 이번 검증에 포함하지 않는다.

`pick-place-policy-contact`는 기존 native study 승인과 고정 입력·예산 경로를 사용한다. 기존 정책·명령 소유자·과제 판정·world 물리는 유지하고 table/infeed collision의 수신 전용 접촉 관측을 추가한다. 저장은 채널별10Hz·최대6000개이며 모든 수신 메시지를 먼저 검증한다. 잘못된 값·절단·관측 프로세스 상실·종료 검증 실패는 진단 HOLD다. 수집기를 먼저 종료해 최종 기록을 보존한 뒤 나머지 자식을 항상 정리한다.

## 검증

- RED source `50f28d1921`: 승인·dispatch·접촉 수집 미구현으로13개 예상 실패. raw `contact-diagnostic-20261024/red/`.
- GREEN source `522094aba3`: 원격 단위·계약 검사132개 실행 통과. `test_remote_omx_native`, `test_omx_policy_native_inputs`, `test_omx_sim_policy_contacts`, `test_omx_native_sim`, `test_native_sim_job`, `test_omx_native_study_authority`, `test_omx_sim_policy_runtime`. `known_failures.py`: NEW0/known0/flaky0. 저장 주기 사이 잘못된 메시지의 검증 누락을 독립 검토에서 수정하고 회귀 사례를 포함했다.
- 실제 SDK source `752107535318602182441464b31987a7bc76a975`: AI 시험 호스트, `remote_sim.py --host ai --durable --minutes 5 ... cmd -- 'env ROSY_RUN_CONTACT_SENSOR_TEST=1 python3 -m pytest test/test_omx_sim_contacts_ros.py --basetemp "$OUT/pytest-tmp" -q -pno:launch_testing -pno:launch_ros'`. CPU4/4GiB/5분, domain197/loopback·고유 Gazebo partition, 단1회. actor `sim-7521075353-969df4`, 종료0, **1 passed in2.48s**, NEW0. 준비·build도 전체 예산에 포함했다.
- 로봇 모델·command owner·정책 추론·optimizer 없이 cube/table 접촉만 확인했다. table27/infeed26개 메시지를 검증하고 채널별1개씩 저장했다. 두 채널 positive control 확인, invalid0/truncated=false, 유한한 nonzero force 확인. wrench의 빈 frame/body 이름과0인 stamp/id는 원래 발행 필드로 보존했다.
- 수집 종료 확인과 `process-cleanup.json` remaining_groups=[]/verified_absent=true. 이후 별도 read-only 검사에서 bound journal rc0, PID 부재, scope inactive·빈 cgroup, lock/reservation 부재, 회수한 원격 source/output 정리를 확인했다.

raw는 `C:/DevTemp/learning-execution-20261023/contact-diagnostic-20261024/`에 보존한다. 저장소에는 호스트 주소·원본 관측을 게시하지 않는다.

| 보존 파일 | SHA-256 |
|---|---|
| sensor-probe/.../policy-contacts.json | sha256: `5c17d681701e005fa57c89a3d90c46281ab7e41367064f1deb02f8ffa2d402b1` |
| sensor-probe/.../contact-probe-closure.json | sha256: `5a9dfa55284c1413b96fbe3178b1656fd8bf8edf6ea4c94f0bc7e381dd3d0f36` |
| sensor-probe/.../process-cleanup.json | sha256: `abfe6596d5581fd7e043ca19f08c4d75ba07363e3210b26362a8b498a2b2320e` |

## 해석과 다음 확인

[Gazebo Contact 구현](https://github.com/gazebosim/gz-sim/blob/gz-sim8/src/systems/contact/Contact.cc)은 접촉이 있을 때만 발행한다. 무수신은 unknown이며 비접촉·지속 관측의 근거가 아니다. 원래 frame/stamp/force 필드를 변환 없이 보존하며 임의의 힘 좌표계를 주장하지 않는다. 이번 짧은 양성 대조는 센서·bridge·종료 경로만 검증한다. 장시간 정책 관측, 자체 충돌·다른 구조물 접촉, 실패 인과·과제 성공·승격·실물 수용은 미검증이다.

기존 실제 관절 벡터와 동결 vendor URDF·8개 collision mesh의 해시를 대조한 nominal FK/정점 분석에서는 마지막 세 자세의 table plane 아래 정점을 찾지 못했다. 정적 mesh 분석은 실시간 충돌·swept volume·engine 근사를 포함하지 않으므로 원인을 확정하지 않는다. 외부 분석 result SHA256 `658502369799bd6bc56be0102e38dab82792b571cb7cb3e3f71948515703c1f6`. 다음은 별도 고정 manifest로 동일 모델 calibration1회·접촉 관측 episode1회 이내를 수행하는 것이다. 자동 재시도·허용치 완화는 하지 않는다.

CE: 미해결 — 실제 정책 추종 실패의 물리 원인은 확정하지 않았다. 수집 검증·종료 규칙은 코드·시험·README에 남겨 별도 해결 교훈을 중복 작성하지 않았다.
