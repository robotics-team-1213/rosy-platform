# 모델 제어의 남은 소프트웨어·SIM 검증

2026-10-24. 사용자는 남은 항목의 처리를 요청했고 현장 관찰자가 없어 소프트웨어·SIM을 먼저 진행하도록 답했다. 장치 동작·토크 활성화·물리 교정·실물 수용은 수행하지 않는다. 합성 CPU 모델·host callback·ROS 수락을 실제 학습 성능이나 독립 과제 성공으로 바꾸지 않는다.

## A0 · 실제 ACT CPU 검사에 앞선 CI 목록 분리

공개 base commit `93307c76fa18`에서 일반 learning-policy CI는 실제 LeRobot ACT 의존성이 없어 native 모델 검사를 skip할 수 있었다. 기존 모델 bytes·관측·owner parent journal 검사를 고정된 CPU 환경에서 빠짐없이 실행하는 것이 다음 목표다. D-854 정책 실행기 ADR은 다른 세션의 Proposed 설계이며 이번 작업은 실행기나 권한 경계를 새로 만들지 않는다.

`affected_tests.py`가 592/600줄이므로 저장소의 95% 분리 기준에 따라 먼저 `CI_FULL_MATRIX`와 `CI_FULL_EXCLUDED` 선언만 `ci_suites.py`로 옮겼다. 기존 이름은 원래 모듈에서 재수출한다. 선언 AST는 원본과 같고 선택기 파일은 557줄이다. suite·순서·gating·skip·ROS 환경은 변경하지 않았다.

| source | 실행 | 결과 |
|---|---|---|
| `93307c76fa18` | 원격 affected/CI dependency 기준 시험 | 99 passed, 0 skipped, 5 warnings |
| `36293ae574` | 원격 affected/CI dependency/harness/구조 회귀 | 239 passed, 0 skipped, 40 warnings |

명령은 `python tools/remote/remote_pytest.py --sha <source> --log-dir <external-scratch>/rosy-model-control-next/<run> -- test/test_affected_tests.py test/test_ci_dependencies.py`와 수정 뒤 같은 명령에 `test/test_harness_contracts.py test/architecture/test_module_structure.py`를 더한 것이다. warning은 기존 문서 staleness와 정규식 escape 경고다. 원격 결과는 known_failures와 비교하며 실제 최종 게시 SHA의 native pre-push와 GitHub FULL은 별도 확인한다.

읽기 전용 독립 검토자는 base→36293ae574의 두 파일과 소비자 경로에서 지적을 찾지 못했다. 최종 문서 포함 head는 별도로 검토한다. 현재 기록은 ACT CPU 검사를 새로 실행했거나 SIM/장치 수용이 완료됐다는 뜻이 아니다.

CE: 해당 없음. 이 선행 변경은 기존 상수의 동일한 이동이며 판단 근거는 크기 규칙·코드·회귀 시험에 있다. 별도 운영 DNS와 과거 워크트리 제거는 미해결 상태로 작업 기록에 보존하고 해결 교훈으로 쓰지 않는다.

## A1 · 실제 ACT CPU 검사를 CI 필수 작업으로 실행

A0는 PR #180, merge commit `2fba8ea42fe4`로 반영했다. 최종 head `f5622bee44e4`의 native pre-push는 519+222 passed, 0 skipped, NEW 0이었고 GitHub FULL run `40042168189`의 19개 작업이 모두 성공했다.

`omx-act-cpu` 작업은 기존 OMX CPU requirements를 별도 `/tmp` 경로에 설치하고 모든 선언 버전과 CUDA 비사용을 검사한다. 기존 Pinky 환경은 유지한다. 실제 ACT bytes·capture·parent journal의 세 시험 파일을 FULL과 해당 OMX 시험의 affected 선택에서 실행한다. 모델 다운로드는 막고 CPU thread 수는 2로 제한한다. skip·빈 수집은 실패이며 기존 quarantine 재시험이 성공해도 원래 skip은 실패로 남는다.

tests-only commit `ecf048b3ef`는 누락된 작업·affected 선택·skip/빈 수집에 해당하는 6 failed, 102 passed를 재현했다. 구현 commit `7771e1cd3c`의 원격 CI 계약·선택기·remote runner 회귀는 162 passed, 0 skipped, NEW 0이다. 이 결과는 CI 제어 로직 검사이며 실제 LeRobot 실행 증거는 최종 GitHub CPU 작업에서 별도 확인한다. 합성 가중치로 실제 CPU inference를 실행해도 승인된 학습 모델의 과제 성능을 증명하지 않는다.

## 소프트웨어·SIM 수용 범위

공식 원격 `fleet_trips --render cpu --boot-s 300 --budget-s 240`을 commit `f5622bee44e4`로 AI PC에서 실행했다. Fleet와 두 CORE, Gazebo가 연결되고 두 로봇 모두 running→arrived를 보고했다. 30초 settle 후 목표 오차는 0.023m와 0.134m로 기존 0.15m 검사에 통과했다. Fleet의 arrived 시점 오차는 약 0.29m와 0.28m이며, 이는 기존 lane hold/통과 창 의미와 후속 settle 검사로 구분해야 한다. learned policy 실행이나 물리 도착 판정의 변경은 없다.

원본 결과 SHA-256은 `3b06d2500c75d33bd9929df18e41f398bc129733a924d2552bbfe3d61854a16f`다. 운영 로그·원본 결과·비공개 endpoint 진단은 Git 밖 workspace-records의 model-control-next/evidence에 보존한다. 승인된 실제 policy artifact와 OMX vendor SIM overlay는 확인되지 않아 ACT 과제 성공을 주장하지 않는다. 장치 capture endpoint는 이름 해석 실패와 직접 TCP 접속 실패가 남아 있다. 관찰자가 없어 장치 동작·재시작·토크·교정·실물 수용은 수행하지 않았다.
