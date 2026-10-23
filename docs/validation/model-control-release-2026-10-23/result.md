# 모델 제어 공통 경계의 공개 통합과 배포

2026-10-23. 사용자가 커밋·머지·배포와 남은 문제 확인을 승인했다. 이 기록은 공개 통합 작업의 증거이며, 이전 독립 작업 브랜치의 결과는 별도로 보존한다. PR·CI·서명 후보·운영 readback은 실제 결과가 생긴 단계만 추가한다.

## 공개 변경

공정별 제출 검증은 `rosy.processes.palletizing.submission`으로 옮기고 Fleet은 설치된 compiler의 검증된 제출 port를 소비한다. Mission 피드백은 한 SQLite snapshot의 소유자·시도·진행·정지·목표 근거를 함께 검사한다. `InferenceResult`는 관측에 결속된 유한 출력·관절 수·시간 순서·불변 벡터를 검증한다. 공개 wire와 CORE/OMX 최종 명령 권한은 유지한다.

로컬 main의 다른 미게시 작업을 섞지 않고 공개 base `ab9f4bb8bd` 위에 필요한 변경만 이관했다. 현재 공개 gateway 소스는 `operations/apps/fleet`이며 설치 wheel/sdist 시험도 그 경로를 사용한다. 공개에 없는 개발 sample fixture는 추가하지 않았다. size unit은 `site_execution` 등록만 제거하고 기존 OMX `pick_place` 단위는 유지했다. ADR index는 이 변경의 D-849 한 행만 추가하며 다른 로컬 설계 행·중복 gap을 반입하지 않는다.

## 실행 근거

| Source | 실행 | 결과 |
|---|---|---|
| `2697d56dc1` | 원격 설치 wheel/sdist·Fleet 소비자·Mission 문맥·추론 계약·제출 회귀 | 79 passed, 0 skipped, 2 warnings, 27.25초 |

시험 명령은 아래와 같다. 로그는 저장소 밖 `<scratch>/rosy-model-control-release/targeted/run-1.txt`에 보존하며 known_failures와 비교한다.

`f33869fbc0`의 공개 guard는 357 passed/1 failed였다. 실행부 814줄의 부모 합산으로 이미 한도를 넘은 Fleet 부모가 13,351→14,165줄이 된 것이 원인이었다. 제한을 높이는 대신 선행 PR #169에서 기존 Python 서버 패키지를 독립 측정 단위로 등록했다. 서버 9,792줄, Fleet 부모 3,559줄이며 전체 측정 264,701줄과 측정 파일 집합은 동일하다. 원격 구조·harness 140 passed와 native pre-push 519+123 passed/NEW0, GitHub CI `39972660344`의 scope·affected 두 묶음·build-smoke·ci-result가 모두 성공한 뒤 `e3bb7aa395`로 squash 병합했다. 이 변경을 본 브랜치에 merge하여 부모의 증가 금지를 지켰다. 검사 로직·상한·예외는 수정하지 않았다.

```text
python tools/remote/remote_pytest.py --sha 2697d56dc1 --log-dir <scratch>/rosy-model-control-release/targeted -- test/test_process_submission_installed.py test/test_remaining_platform_installed.py test/test_inference_result_contract.py operations/fleet/test/test_er2_tool_dispatch.py operations/fleet/test/test_mission_progress.py operations/fleet/test/test_cell_compiler.py test/test_platform_cell_submission.py
```

기존 로컬 머지 시도의 `dda3bc318a` guard는 273 passed였다. 이후 FULL 실행 중 작업 워크트리들이 외부에서 제거되어 로컬 머지 실행을 중단했다. 완료하지 않은 FULL을 통과로 사용하지 않는다. 커밋은 보존됐으며 공개 작업 워크트리를 정상 gateway로 복구하고 잠갔다. 삭제의 수행자·의도는 확인하지 못했으므로 작업 공간 운영 문제는 해결된 교훈으로 기록하지 않는다.

## 검토와 수용 범위

공개 main의 별도 CI `39973374315`는 곡선 map-entry 시험에서 두 가상 운행의 실제 조회→전송 지연 차이를 정확 비교에 섞어 실패했다(0.377m 대 0.378m). 기존 시계 주입 지점을 해당 시험에서만 고정한 PR #173을 원격 관련 시험 87 passed, native pre-push 519+68 passed, CI `39977272914` 전 잡 성공 및 독립 검토 후 `c190b0f7b2`로 병합했다. 정확 비교·실제 지연 보정·진행 시계 시험·timeout·허용 오차는 유지했다.

기존 공개 PR #172는 최종 tree의 검사와 별개로 과거 두 중간 커밋이 D-766을 위반하여 이력 검사에서 거절됐다. 해당 PR과 브랜치는 보존하고 머지하지 않았다. 선행 수정이 포함된 최신 공개 main 위에 최종 변경만 새 미게시 브랜치로 정리해 각 commit의 크기 조건을 적용한다. 공개 이력을 강제로 바꾸거나 gate를 우회하지 않는다. 최신 base가 임시 선언한 D-849 gap은 이 ADR 본문과 함께 제거하며 다른 예약은 유지한다.

별도 읽기 전용 검토자는 `ab9f4bb8bd..2697d56dc1`의 producer/consumer·import·설치와 권한 경계에서 코드 회귀를 찾지 못했다. 과거 로컬 FULL과 공개 통합 head를 구분하고 공개에 없는 ADR·sample 변경 주장을 정리하라는 지적을 반영했다. 최종 게시 head의 변경 범위 재검토와 해당 SHA 검증은 게시 전에 완료한다.

호스트 시험은 실제 모델 소비·물리 작업 성공을 증명하지 않는다. `unobserved` 물체 상태, 파일 출처와 실제 추론 소비, Action 결과와 독립 목표 근거의 차이를 유지한다. 정책 활성화·새로운 실물 동작·학습·보정은 배포에 묶어 자동 실행하지 않는다. 운영 배포 완료는 서명 후보 source와 이미지 digest, 실제 설치 모듈·서비스 health를 대조한 뒤에만 기록한다.

## 설치 이미지의 공정 의존성 누락 — 후속 수정

PR #174는 공개 main commit `857af906da81`로 병합됐다. PR CI `39981405297`와 main CI `39984489421`의 19개 job, 후보 build/provenance `39984489364`의 4개 job이 모두 성공했다. 검토 head의 native pre-push는 11,933 passed/547 skipped/NEW0이었다. 기존 signer의 provenance·main·CI·서명 검사를 통과한 후보가 2026-10-23T16:34:22Z 설치됐지만, UID 10001 설치 probe가 compiler import에서 `ModuleNotFoundError: rosy.processes`로 실패했다. 일반 서비스 health를 공정 실행 가능성으로 사용하지 않는다.

Docker COPY와 PYTHONPATH에 palletizing 공정과 Skill 계약 소스가 누락돼 있었다. 직전 c190b0f7b2 이미지도 network none/UID 10001의 `find_spec` 검사에서 공정 패키지가 없었다. 기존 미포함 경로이며 이번 모듈 이동만의 회귀로 단정하지 않는다. wheel/sdist 회귀와 Docker payload 검증은 별개다.

공개 base `29ec6ca93e` 위의 후속 수정은 두 소스의 COPY·PYTHONPATH·dockerignore·후속 build 트리거를 연결하고, 이미지 빌드에서 실제 Fleet compiler·Mission 피드백·InferenceResult를 import한다. 격리 payload 시험은 주요 타입이 복사된 이미지 트리에서 로드됐는지 검사하므로 테스트 호스트의 설치 wheel이 누락을 가리지 못한다. 실패 시험 head `7ef0b7fc70`에서 1 failed/NEW1, 수정 head `4e05ccbae2`에서 해당 시험·후보·workflow·추론 계약 52 passed/0 skipped/NEW0을 확인했다. 독립 읽기 검토에서 추가 지적은 없다. 실제 수정 이미지 빌드·설치 검증은 아직 진행 중이다. 운영 설정·owner 권한·정책 활성화는 변경하지 않는다.

이미지 수정 PR #178의 첫 전체 CI `39989430189`는 CORE 모터 health route 시험 한 건이 fresh 대신 delayed여서 실패했다(같은 묶음 7,196 passed/64 skipped). 모터 표본을 저장한 뒤 전체 API를 구성하는 실제 시간이 reader의 2초 표본 나이에 섞이는 시험이었다. 테스트 helper에서 producer·reader 모듈의 시계 참조만 같은 고정 시각으로 주입하고 미래 표본은 원래 시각에 20초를 더하도록 했다. 전역 time/monotonic·실행 loop·운영 2초 기준·부정 입력·fault/ended/3초 stale 검사는 유지했다. 수정 head `5ca70d83c9`의 원격 API·native 모터 health 44 passed/0 skipped/NEW0. 새 게시 head의 전체 CI는 별도로 확인한다.

CE: 미해결. 작업 워크트리 제거의 수행자·의도는 확인하지 못했다. 데이터 손실 없이 공개 작업을 복구한 사실과 검증 중단을 보존하며, 원인 해결을 주장하지 않는다. 이미지 의존성 누락은 설치 위치 검사 교훈의 적용 대상으로 추적하며 최종 설치 성공을 확인하기 전에는 해결 완료로 기록하지 않는다.
