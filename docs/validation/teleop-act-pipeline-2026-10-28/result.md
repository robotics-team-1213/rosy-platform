# 저장 검수에서 native ACT 학습·독립 평가까지

제품 소스 `9c2ea19fae`를 모델/AI 시험 PC에서 검증했다. 전체 시연 저장 검수와 정확한 파지 구간 저장 버전을 각각 기존 owned worker lifecycle에 연결했다. source/review/split/cycle/model 바이트, 독립 분할, 별도 프로세스 모델 재적재와 ZIP 검증이 실행 경로에 포함된다.

## 실제 실행 범위

실제 텔레옵 자료가 학습센터에 등록돼 있지 않았다. 조사 당시 기존 데이터 15개는 모두 `synthetic_smoke`였다. 새 수치 검증은 기존 `teacher_fixture.teacher_dataset`과 봉인 교사 fixture를 사용해 task 전용 경로에 만든 합성 native 기록이다. 각 세션의 미판정 원본 결정은 유지했고 합성 시험임을 명시한 별도 검수만 저장했다. 운영 서비스·진짜 사람 라벨·장치 명령을 변경하지 않았다.

실제 LeRobot ACT optimizer를 **각각 100단계** 실행했다. CPU learner의 패키지는 LeRobot 0.4.4, torch 2.10.0+cpu, torchvision 0.25.0+cpu, av 15.1.0, datasets 4.8.5다. learner 환경에 패키지를 설치하지 않았다.

| 경로 | 작업 ID | 정책 revision | step 1 → 100 loss | 독립 eval 평균 관절 MAE |
|---|---|---|---|---|
| 전체 시연 저장 검수 | `24b4d3ba-f328-454d-9567-d88385e2bd0d` | `act-363ec6a0ed225404` | 0.642 → 0.225 | 9.831651 |
| 저장 파지 구간 v1 | `2c802157-3372-4f8d-8f0f-a84287f55c02` | `act-067f1f26c16ae0e2` | 0.642 → 0.225 | 9.831554 |

둘 다 `model_reloaded_in_new_process=true`, 독립 eval 3프레임, train 평균 baseline MAE 10.0이다. MAE는 native normalized 단위이며 rad나 집기 성공률이 아니다. 작은 합성 자료에서 수치 경로가 작동한 근거일 뿐 일반화나 실제 작업 성능의 근거가 아니다. `physical_task_success=null`, `physical_learning_verified=false`, `policy_activation=false`다.

## 검증 명령과 결과

`tools/harness/rosy_harness.py affected --base 2e9eb670ed --json`의 전체 선택을 `tools/remote/remote_pytest.py --affected-json -`로 실행했다.

- 영향 범위: **3,141 PASS / 337 SKIP / 51 warnings / 0 NEW**, AI 시험 PC. `C:/DevTemp/teleop-act-pipeline-20261028/affected-1/run-1.txt`.
- 명시 Chromium: `ROSY_RUN_BROWSER_TESTS=1`로 `test_omx_native_train_browser.py`, `test_omx_center_browser.py`, `test_omx_segments_browser.py`를 실행해 **6 PASS / 0 SKIP / 0 NEW**. UUID secure-context API 부재, 저장본 선택, 응답 유실 후 동일 요청 재시도, 구간 버전과 fixture 거절을 포함한다. `browser-2/run-1.txt`.
- 실제 수치 통합: 모델 PC에서 `ROSY_RUN_PINNED_LEARNING=1 ROSY_NATIVE_PIPELINE_STEPS=100`과 `test_experiment_native_train.py::test_pinned_numerical_native_pipeline_trains_reloads_and_evaluates -q -s -n 0`을 실행해 **1 PASS / 0 SKIP / 0 NEW**. 두 경로의 실제 학습·모델 재적재·평가·ZIP 검증을 한 시험이 실행한다. `numerical-100/run-1.txt`.
- 회귀 red 단계의 `43efe5ebc3`는 미구현 모듈로 9개 실패했다. 최초 묶음 `3a519286d9`는 재시작 모의 Popen이 환경 probe에도 적용되는 시험 문제 1개가 실패했다. mock 범위를 고친 후 위 최종 소스의 영향 범위에서 통과했다. 이 실패들을 기존 실패로 등록하지 않았다.
- 독립 읽기 전용 검토에서 HTTP UUID, cycle receipt 다운로드 검증, 큰 저장 검수의 worker 읽기 상한을 지적했다. 모두 수정·회귀시험을 추가했고 `9c2ea19fae` 재검토에서 중요한 미해결 항목이 없었다.

337 SKIP은 실행 성공으로 계산하지 않는다. 별도 6개 Chromium과 1개 수치 통합만 명시 활성화된 범위다. 기존 경고는 gate 이동이나 실물 수용으로 해석하지 않는다. 수치 learner가 만든 임시 config JSON 두 개를 remote runner가 `/tmp` 누출로 보고했으며 실행은 exit 0이었다. 운영 파일을 정리하거나 기존 cache를 삭제하지 않았다.

## 보존 산출물

모델 PC의 task 전용 `~/rosy-test/evidence/native-act-pipeline-20261028-100/`에 prepared 원본, 분할, 검수, 두 run의 학습 로그·environment·평가·weights와 ZIP을 보존했다. Windows의 ZIP 사본은 `C:/DevTemp/teleop-act-pipeline-20261028/`에 있다. 원격과 다운로드 사본의 SHA-256이 일치한다.

| ZIP | 크기(bytes) | SHA-256 |
|---|---:|---|
| `episodes.zip` | 41,855,462 | `61636cc01bbe51cdb4beaaa870121f277c3c940942d7bf53c586ea226ed2c305` |
| `segments.zip` | 41,855,614 | `d8f0737625674adce32447bd35966b3338d79ef0285e0563df70d3d8469123ff` |

## 미리보기와 남은 수용

동일 제품 소스의 별도 transient 미리보기를 task 전용 review-state와 위 center 데이터로 열었다. 생성한 자료 이름과 검수자는 합성 시험임을 표시한다. 기존 운영 센터와 분리했으며 loopback으로만 제공한다. 미리보기 unit은 2시간 뒤 종료된다. 완료 run 두 개와 모델 다운로드를 HTTP로 확인했다. 이 미리보기를 운영 배포로 계산하지 않는다.

실제 leader 텔레옵 녹화와 사람의 영상 검수, 생산 데이터의 전체 경로, 실물 평가·정책 활성화는 미실행이다. raw 세션을 준비하는 기존 CLI와 기존 등록 권한은 유지한다. 임의 LeRobot 폴더 직접 업로드나 LeRobot 전체 기능 대체를 완료했다고 주장하지 않는다.

CE: 해당 없음 — pinned learner 환경 교훈을 적용했다. 이번 연결·세 가지 검토 수정의 이유와 재발 방지는 코드·회귀시험·이 검증 기록으로 확인할 수 있어 별도 교훈을 늘리지 않았다.
