# Learning·G1 후속 검증 — 2026-10-25

[Learning 서명 배포 기록](../learning-conveyor-deployment-2026-10-25/result.md)의 후속이다. 문서 병합 후 전체 CI의 최종 결과와 새 G1 조사를 보존한다. G1 지연 원인 해결, 운영 로그인 화면 수용, 학습·정책·물리 수용을 주장하지 않는다.

## 새로 확인한 전체 CI

commit `61addd56955e7683e39a7db8d026610772f7719d`의 [main CI 40187440248](https://github.com/robotics-team-1213/rosy-platform/actions/runs/40187440248)는 최종 SUCCESS, 20개 job 모두 SUCCESS다. 이전 배포 보고 시점의 진행 중 상태를 대체한다. 읽기 전용 독립 검토자도 동일 SHA와 20개 성공을 확인했다. 실행을 재시도하거나 취소하지 않았다.

## 새로 실행한 G1 단독 검사

공식 원격 runner로 원래 실패 commit `e7870d279ba918d3c6f7ac211d46a72b65cd0cac`의 `test/test_platform_g1_timing.py::test_coordinated_pairs_pass_both_barriers_within_the_proposed_bounds`를 모델 PC에서 실행했다. 실행 인자는 `--sha e7870d279ba918d3c6f7ac211d46a72b65cd0cac --log-dir <external-log-dir> -- <node-id> -s --durations=3`이다.

결과는 **1 PASS / 0 SKIP / 0 NEW**, 전체 6.47초, call 5.52초다. 로그를 `test/known_failures.py`와 비교했다. 로그 자체에는 SHA가 없으므로 runner의 고정 SHA 호출 기록과 함께 보존한다. 현재 원격 runner의 의존성 recipe로 준비한 별도 시험 venv를 사용했다. 원래 GitHub runner와 환경이 동일하다고 단정하지 않으며 운영 Python 환경을 업그레이드한 것이 아니다.

기존 실패는 `test/test_platform_g1_timing.py:212`에서 ReleaseBarrier p99/max 0.422716초 > 0.25초였다. 원래 실패와 같은 소스의 후속 e231 전체 CI 통과는 이전 기록에 보존돼 있다. 새 단독 통과를 근본 해결로 취급하지 않는다.

## 새로 실행한 SQLite 원인 분리 실험

고정 commit e787의 원본 source closure를 사용해 실제 `BarrierJournal.release`를 호출했다. 독립 검토자는 대상 모듈 hash와 원본 blob의 일치를 확인했다. 선정된 모델 PC의 별도 임시 합성 DB에서 nice 15·ionice 3·MemoryMax 1 GiB와 자체 job lock으로 실행했다. 운영 DB·라벨·정책·로봇을 사용하지 않았고 자체 lock은 finally에서 제거했다.

SQLite connection subclass의 계측 wrapper로 SQL 단계별 `perf_counter`, `thread_time`, `RUSAGE_THREAD` context switch를 기록했다. 제품 timeout·DB 동작·판정 bound를 변경하지 않았다. 모든 release에서 created와 released 상태를 확인했다. 잠금 없음 / 300ms 별도 writer 잠금을 고정 순서로 세 쌍 교차 측정했다.

| 조건 | release wall time | release thread CPU | 가장 긴 SQL 단계 | 이후 40회 5ms sleep overshoot 최대 |
|---|---:|---:|---|---:|
| 잠금 없음, 3회 | 4.087–5.602ms | 0.479–0.638ms | COMMIT 3.801–5.225ms | 0.335ms |
| 300ms 잠금 주입, 3회 | 334.750–339.643ms | 0.951–1.314ms | BEGIN IMMEDIATE 329.654–333.039ms | 0.339ms |

관측은 **SQLite 대기로 250ms bound를 넘겨도 사후의 짧은 sleep 기반 scheduler probe는 정상일 수 있다**는 반례를 지지한다. 현재 request 측정은 직접 dispatch 안의 SQLite BEGIN·commit 비용까지 포함하므로 네트워크 RTT나 순수 CPU 시간으로 해석할 수 없다.

원래 CI에 다른 writer가 있었다거나 422.716ms가 잠금 대기·commit·스케줄러 중 무엇 때문이었는지는 입증하지 못했다. 원래 Pair/SimArm 경로는 순차 호출이다. 이번 실험의 holder thread를 원래 실행에 소급하지 않는다. wrapper·합성 DB·고정 순서 세 쌍이라는 메커니즘 실험이며 실제 end-to-end 분포나 일반 성능 결과가 아니다. 독립 읽기 전용 검토자는 수치와 위 귀속 한계를 확인했다. bound·skip·quarantine은 바꾸지 않았다.

원시 자료는 공개 Git 밖의 작업 조사 폴더 `g1-latency-baseline-20261025`에 보존한다. 아래 SHA-256은 보존 바이트의 식별이며 원격 attestation이나 CI 환경 동일성 증명이 아니다.

| 파일 | 크기 | SHA-256 |
|---|---:|---|
| run-1.txt | 284 B | `4900eee30554874e9857994c7318300669cd0e5eba263b9045d45b69394d966e` |
| sqlite-profile.json | 15,607 B | `b6fab38e2e0e7bd91fd91df0e655571d29b9bf70f5ac80583f111d6daa810fcd` |
| profile_sqlite.py | 5,939 B | `275bd29dc666ae64f3638b90310660efbe811c879ab4177cddc9161053438fcd` |

## 실제 운영 배포와 공개 main의 동일성

추가 커밋·머지·배포 지시 뒤 읽기 전용 독립 검토자가 public main commit `d0d7f7367b4ddf5e2292a2c649419d1fdcd17ede`와 실제 배포 source commit `e231f97b06766661a96cd0e3530a7864fe928fd9`를 비교했다. `model_code_layout.CODE_PREFIXES` signed payload의 경로·mode·blob 732개가 동일하다. 공통 inventory SHA-256은 `c18f101d4a16011eab4be59957898e1522a1bd46216af98c2dd5e7960d0d849b`이다. public d0d7의 전체 CI40192429649도 정확한 SHA에서 20개 job 모두 SUCCESS였다.

21:47:29 KST 운영 읽기 조회에서 `rosy-edge-review.service`는 active/running, current는 `model-code-41-e231f97b0676`, 실제 argv와 unit이 일치하고 `--sim-config`가 존재했다. unit hash는 이전 배포 검증값과 동일하며 accepted sequence41/sourcee231/current가 일치했다. pending·failed 없음, updater 결과는 정상 idle이었다.

따라서 signed model-code 범위에 추가 배포할 제품 차이가 없었다. 이 검증을 새 배포·재시작으로 기록하지 않는다. 공개 main 전체나 다른 세션의 PR이 운영에 배포됐다는 뜻도 아니다.

## 미확인 항목과 완료 기준

사용자는 정상 로그인한 Learning → SIM에서 기존 run의 보고서·PNG 다섯 개를 아직 확인하지 못했다고 답했다. 운영 로그인 화면 수용을 완료 처리하지 않는다. 계정 보호를 우회하거나 사용자 세션을 합성하지 않았다.

운영 OMX center를 URI mode=ro·PRAGMA query_only로 다시 확인했다. datasets=0, runs=0이며 dataset/run 디렉터리와 upload 파일도 각각 0개다. 기존 접촉 JSON과 PNG는 동기화 state/action/camera Episode가 아니다. 현재 입력으로 ACT 학습·독립 정책 평가를 시작하거나 시연 성공·사람 검수·policy revision을 만들어 채우지 않는다.

남은 완료 기준은 원래 end-to-end 호출의 실패 시점 wall/thread CPU·DB BEGIN/commit·동시 scheduler 관측 결속, 정상 계정의 실제 화면 수용, 동기화 Episode 수집과 독립 train/eval·검토·모델 재적재·고정 policy revision의 새 SIM 평가다. 카메라·팔·적재면·컨베이어 실측·보정과 물리 수용은 별도 승인·증거가 필요하다. 이 조사에서는 실물 명령을 실행하지 않았다.

CE: 미해결 — 원래 G1 지연 원인을 확정하지 못해 해결 교훈을 추가하지 않았다. 기존 간헐 실패 귀속 교훈의 실패 줄·같은 조건·원인과 후속 통과 구분을 적용했다.
