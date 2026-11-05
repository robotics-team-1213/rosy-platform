# 검수 자료의 ACT·SmolVLA 학습 연결 검증

## 범위와 소스

기준 commit `3a004fad06c025af0f39d0055c05596810e17d5e`, 최종 구현 commit `348778e549ba963ed6a7e4d1d4f3cda8cf0c8d00`.
작업 branch는 `feat/omx-smolvla-reviewed-cycle`다. 이 기록 뒤 문서만 바뀐 head와 시험한 구현 SHA를 구분한다.
main 착지·게시·서비스 배포·모델 승격·장치 동작은 수행하지 않았다.

`collection_pipeline.py train`은 기존 ACT 기본값을 유지하며 명시적인 `--policy smolvla --base-model <local-policy> --vlm-assets <local-metadata>`를 받는다.
기존 검수·episode/session 분할·lease·변조 거부·실패 기록과 공식 LeRobot trainer를 재사용한다.
로컬 기반 정책을 snapshot하고, 학습 산출물에 tokenizer/VLM metadata를 동봉한다. 자료·코드·환경·기반 자산·checkpoint 지문을 receipt에 결속한다.
없는 자산은 자동 다운로드하지 않는다. L0 등록은 정책 종류를 표시하는 제안이며 실행 승인이 아니다.
기본 실행 허용 목록은 ACT만 유지하며 SmolVLA의 이번 적재·추론 증거는 명시적인 bench/SIM probe 범위다.

## 원격 검증

모든 pytest는 `tools/remote/remote_pytest.py`가 커밋된 소스를 원격에 배치해 실행했다. 개발 PC에서 pytest를 실행하지 않았다.

| 소스 | 실행 | 결과와 주장 범위 |
|---|---|---|
| `409c36fa8f` | 필수 rad readback을 명시한 collection 왕복, 현재 고정 CPU SDK | 1 passed /0 skipped, exit0, NEW0. 원본에 저장된 관절 순서·값도 확인 |
| `0e82c4fafa` | 실제 SmolVLA SDK, CPU, 6관절·12관절 | 2 passed /0 skipped, 351.47초, exit0, NEW0. 각 optimizer 1회→독립 4-frame 평가→모델 이동→빈 HF cache·오프라인 새 프로세스 재적재→실제 bench runner 적재·유한 출력 |
| `0e82c4fafa` | 현재 고정 ACT CPU SDK 호환 | 2 passed /0 skipped, 34.30초, exit0, NEW0. collection/분할·구간의 실제 ACT optimizer 2-step cycle과 재적재도 포함 |
| `0e82c4fafa` | 공식 FULL 29 invocations | 28개 exit0, root 묶음 exit1/NEW5. 아래 원인을 수정한 뒤 재검증 |
| `bc81a33cad` | 공식 FULL 29 invocations | 28개 exit0, root 3 failed/14990 passed/1498 skipped, exit1/NEW3. 추가로 내부 wheel의 정확 pin 계약을 수정 |
| `348778e549` | 의존성 계약·실제 오프라인 client wheel 설치4파일 | 44 passed /0 skipped, 26.13초, exit0/NEW0 |
| `348778e549` | 실제 고정 Qwen, model PC에 한정한 순차3함수 | 3 passed /0 skipped, 97.99초, exit0/NEW0. Console26/26, 전처리 비교19/19, Discord46건 실패0 |
| `348778e549` | 최종 FULL29개 | 전부 exit0. 각29로그의 NEW/known/flaky 모두0. root14994 passed/1497 skipped, G1 12 passed/0 skipped |

최종 구현348778e549의 영향 분석도 `mode=full`, unmapped0이며 등록된 `full_invocations` 29개가 실행한 선택과 정확히 같음을 다시 확인했다. 겹치는 시험이 있어 invocation별 pass 수를 고유 시험 수로 합산하지 않는다.
일반 환경에서 LeRobot/torch/ROS 또는 opt-in 모델·브라우저 조건 때문에 skip되는 시험은 실행 통과로 세지 않는다.
특히 Monitoring 실브라우저 묶음은 18 skipped였다. 일반 FULL의 skip이 별도 위 SDK 실행을 대신하지 않는다.
SmolVLA와 ACT SDK 실행은 CUDA를 비활성화했다. 기존 v13 시연 세션의 GPU·모델·자료를 변경하지 않았다.

실제 SDK 시험 명령의 host별 경로는 `<...>`로 표시한다. FULL은 위 SHA에서 공식 selector가 낸 `full_invocations` 전체를 실행했다.

```text
python tools/remote/remote_pytest.py --sha 0e82c4fafa --log-dir <external-logs> -- ROSY_OMX_LEROBOT_PYTHON=<installed-smolvla-python> ROSY_SMOLVLA_BASE=<local-base> ROSY_SMOLVLA_VLM_ASSETS=<local-vlm-metadata> ROSY_JOB_CORES=2 ROSY_JOB_MEM_GB=6 test/test_omx_smolvla_native_cycle.py -s -ra
python tools/remote/remote_pytest.py --sha 0e82c4fafa --log-dir <external-logs> -- ROSY_OMX_LEROBOT_PYTHON=<pinned-act-python> ROSY_JOB_CORES=2 ROSY_JOB_MEM_GB=6 test/test_omx_collection_roundtrip.py::test_collection_intake_real_native_split_roundtrip test/test_omx_lerobot_integration.py::test_official_config_reader_and_split_roundtrip -ra
python test/known_failures.py <each-run-log>
```

SmolVLA 시험은 기존 별도 SDK의 LeRobot0.4.4, torch2.7.1+cu128, transformers4.57.6, tokenizers0.22.2를 CPU로 사용했다.
기반 정책 snapshot commit은 `lerobot/smolvla_base`의 `5e8d12a6e2975b0e5e5fce7c8caf47c371d257b6`, VLM metadata snapshot commit은 `HuggingFaceTB/SmolVLM2-500M-Video-Instruct`의 `7b375e1b73b11138ff12fe22c8f2822d8fe03467`다.
ACT 시험은 현재 `deploy/robot/omx/requirements-lerobot-export.txt`의 9개 pin과 일치하는 CPU 환경을 썼다. SmolVLA 시험 환경을 ACT 정본 환경과 동일하다고 표시하지 않는다.

원시 로그는 작업 공간의 `Rosy/docs/workspace-records/2026-11-05/decision-vla-pipeline/evidence-smolvla/`에 보존한다. 공개 저장소에는 실제 host 경로가 든 로그를 넣지 않는다.
이 디렉터리의 최종 코드 검증·이전 실패 이력·Decision 원본을 보존한 `source348778e549-evidence.zip`의 SHA-256은 `b3e78f8bb77c5c61f41828a1693c2e8250cba2dd2e186fe9f89b43c1dd9d0f67`이다. 최종 FULL root 로그의 SHA-256은 `0b10e049cb728be0af6c27c19d912cc7c755913ddcee06f419dd16746e44826c`이다.
SmolVLA `actual-smolvla-final-queued/run-1.txt` SHA-256은 `62eff587832f442553575904dacf81b4a698cbf1058061da198523d474013dc6`, ACT `act-final-pinned/run-1.txt`는 `a18bdec7177ae82cf5b19dab7fa38cf56d34d01de481220cbdd20d20c6827e67`이다.
후속 기본 환경 skip audit는21 skipped/exit0/NEW0였다. terminal에 개별 사유는 출력되지 않았다. 소스상 collection1개는 명시 SDK 경로, SmolVLA2개는 SDK·기반 정책·VLM metadata, Monitoring18개는 실브라우저 opt-in을 요구한다.

### Decision 최종 소스 평가 원본

고정 `qwen3-vl:8b-instruct` digest `0533d74300e4f9bc367d675d4e64ffd073d50ff16a2b4096cc2e8a1cf8c96319`를 사용했다. 실행 전 resident 없음과 설치 digest 일치를 확인했으며 다운로드·메시지 전송·장치 동작은 없다.
`test_operator_model_acceptance.py`, `test_operator_preprocessing_benchmark.py`를 model PC만 지정해 `ROSY_RUN_OPERATOR_MODEL_TESTS=1`, `ROSY_OPERATOR_EVALUATION_OWNER=model_pc`, 최종 전체 source SHA, `-pno:xdist -s -ra`로 실행했다.
사전 부재를 확인한 별도 원격 임시 디렉터리를 `--basetemp`로 지정해 runner cleanup 후에도 원본을 회수했다. 기존 경로를 지정하면 pytest가 내용을 지울 수 있으므로 이 기록의 실행에서는 기존 자료를 재사용하지 않았다.
원본3개를 `evidence-smolvla/decision-final-json/`에 복사했고 원격 SHA-256과 사본의 일치, JSON 안의 최종 source SHA를 확인했다.

| 원본 JSON | SHA-256 |
|---|---|
| `operator-model-evaluation.json` | `d9a68833c8122ac9a2aba2120ec4dc5863fcbebbbb80c1b18715fda7be8bc2aa` |
| `preprocessing-benchmark.json` | `dc757576dab952e6e2261cc3fc6f122b829694c5d2348a17fbcbceb34f0eb6eb` |
| `discord-preprocessing-proof.json` | `cbf058926a72996dbe90490887d578db3c4c4c3105c1a0dde82b4b89df09ebfb` |

이는 개발·수용 사례의 실제 추론이며 미사용 사람 정답·보정 완료·단독 지연 보장의 근거가 아니다. 원본을 보존한 것도 자동 승격 승인은 아니다.

### 실패와 수정

- 수집 왕복 fixture가 필수 `joint_positions`를 빠뜨려 학습 전에 실패했다. 운영 수집기는 이미 필드를 검증했다. 합성 관측에 명시적인 rad 값을 넣고 실제 저장값을 확인했다. 제품 기본값이나 가드를 느슨하게 하지 않았다.
- 신규 계약 15 RED, collection/L0 진입점 7 RED, 선택 SDK 사전 점검 2 RED 뒤 구현했다. 중간 조합 회귀는 76 passed였다.
- learning→integration 역방향 import는 D-427 검사에서 실패했다. 공유 validator를 ROS/torch/LeRobot 없는 `contracts/learning`으로 옮겼다. scanner 허용 목록을 바꾸지 않았다.
- 실제 client wheel 설치와 `pip check`에서 dependency closure 및 정확 pin 불일치가 재현됐다. 계약 wheel 포함과 local execution pin을 맞췄다. code identity 1 RED 뒤 소스 hash 결속을 구현했다.
- 첫 FULL의 NEW5 중 4건은 CI의 이전 learning/OMX wheel 정확 pin, 1건은 독립 SDK source 시험의 누락된 계약 import root였다. `bc81a33cad`에서 pin과 source 경로를 맞췄다. 오프라인 wheel 설치와 실제 ACT 추론·거부 assertions는 유지했다.
- 두 번째 FULL의 NEW3은 내부 wheel 의존성에 범위가 아닌 정확한 `==` pin을 요구하는 기존 계약이었다. `348778e549`에서 OMX의 learning 의존성을 `==0.1.16`으로 맞췄다. 계약 시험은 바꾸지 않았다.
- 자원 대기 후 NOT RUN인 실행, 시험 시작 전 취소된 작업, 잘못된 interpreter를 지정한 시도는 PASS나 유효한 RED로 합산하지 않는다.

## 독립 리뷰

별도 읽기 전용 reviewer가 기준→`0e82c4fafa`, 이어 `0e82c4fafa`→`bc81a33cad`→`348778e549`의 각 delta를 검토했다. Critical/Important 없음, 추가 delta 지적 없음.
기존 Minor 1건은 보류했다: 저장된 normalizer/unnormalizer 통계와 train 통계의 직접 동등 비교 회귀가 없다.
LeRobot 0.4.4 trainer가 train dataset stats로 processor를 덮어쓰는 것은 소스와 리뷰로 확인했다. 현재 잘못된 통계라는 결함 근거는 없지만 SDK 변경 시 직접 비교가 필요하다.
리뷰는 시험 실행·CUDA 동작·실자료 품질·현장 수용을 인증하지 않는다.

## 완료 조건별 판정과 다음 입력

| 조건 | 현재 판정 | 다음 입력·행동 |
|---|---|---|
| 검수→분할→학습→새 프로세스 평가→L0 연결 | 구현·합성 연결·최종 원격 회귀 PASS | 실제 데이터의 모델 품질은 아래 별도 조건으로 평가 |
| 기반 자산 폐쇄·이동 후 오프라인 재적재 | 합성 연결 PASS | 실자료 품질과 별도로 유지 |
| 실제 데이터 ACT/SmolVLA 비교 | 미수용 | 실제 검수 revision, 서로 독립인 train/eval/test session, 고정 rig/보정·카메라·관절·단위·새 집게/자산 지문을 갖춘 입력으로 동일 과제 비교 |
| Decision 독립 품질·확률 보정 | 미수용 | 미사용 사람 정답과 사전 검수된 calibration limits, 규칙/단일/협력 비교. 개발 사례 재생을 독립 정답으로 쓰지 않음 |
| 시뮬 작업 성공 | 미수용 | 고정 checkpoint와 새 조건에서 기존 목표 20회 중 18회 이상 성공을 별도 관측 |
| 실물 수용 | 미수용 | 기존 owner의 단위·순서·freshness·속도·관절·공간·HOLD 검증 후 감독 시험. 물리 설치·사람 정답·D-911 현장 확인은 사람이 수행 |

합성 optimizer와 유한한 action은 파지·운반·안착 성공률을 나타내지 않는다. `physical_task_success`는 null이다.
이 변경은 실패한 물리 보정이나 단위 변환을 학습으로 대체하지 않으며 전체 목표를 완료 처리하지 않는다.

CE: 해당 없음 — 기존 learner/test venv 분리 교훈을 적용했고, 이번 판단은 최종 코드·회귀·README로 재구성 가능하다. 미검증 품질·실물 결과를 해결 교훈으로 기록하지 않았다.
