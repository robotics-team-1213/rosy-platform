# 주제별 학습센터 UI와 실제 브라우저 학습 완주

2026-10-29. 최종 제품 소스 `95c5598ba6`. 사용자 요청에 따라 과제 화면을 탭·상태 카드로
구성하고 실제 소프트웨어 흐름을 검증했다. 운영 배포나 실물·현장 수용 기록은 아니다.

## 참고 사례와 적용

- [MLflow Tracking](https://mlflow.org/docs/latest/tracking/): 실행·평가·모델을 구분하는 구성을 참고해 실행 카드·관절 오차 표·모델 다운로드를 묶었다.
- [IBM Carbon Tabs](https://www.carbondesignsystem.com/building-blocks/core/components/tabs/guidelines): 같은 맥락의 작업 내용을 탭으로 전환한다. 탭 선택은 실제 완료 여부와 분리하고 상태 카드를 함께 비교한다.

과제 제목·현재 단계·다음 작업 아래에서 시연을 명시적으로 선택한다. 준비 탭은 로봇·관절 단위·카메라,
녹화 탭은 현장 녹화 가용 상태·준비서·기존 시연 연결, 검수 탭은 대상·분할 수·저장 여부,
학습 탭은 저장 검수 선택·방법별 요건, 결과 탭은 완료 근거·실행·모델을 다룬다.
한 패널만 표시하며 URL·키보드·새로고침으로 선택을 유지한다. 진행 중 과제를 다시 열면 상태와
중지 제어가 있는 결과 탭으로 안내한다. 여러 시연의 검수 대상은 자동으로 첫 자료를 고르지 않는다.
시작 준비·실행·중지 대기·실패·취소·완료를 구분하며 상태가 같으면 실행 DOM을 다시 만들지 않는다.

## 커밋과 원격 검증

로컬 pytest는 실행하지 않았다. 공식 remote runner로 커밋한 소스만 실행했다.

| 범위 | 커밋 | 결과 |
|---|---|---|
| affected `--base 6c7c9dafe4 --json` 선택 전체 | `7c65846848` | 3,379 passed / 362 skipped / 종료0 / NEW0 |
| 주제 탭·기존 과제·native 접수 Chromium 3파일 | `95c5598ba6` | 12 passed / skip0 / 종료0 / NEW0 |
| 검토 수정의 workflow·HTTP 전체 | `9e78120fbe` | 15 passed / skip0 / 종료0 / NEW0 |
| 가짜 응답 없는 실제 브라우저 학습 완주 | `9e78120fbe` | 1 passed / skip0 / 종료0 / NEW0 |
| 공통 색·반응형·hidden·타이포·토큰과 Chromium | `c078982b50` | 선택 전체 종료0 / NEW0 |

전체 영향 시험 후 바뀐 제품 코드는 active-run 안내와 공통 시연 선택이다. 이를 15개 workflow/HTTP
검사와 최종 Chromium에서 검증했다. 마지막 `95c5598ba6`은 시연 선택의 명시적 label 연결만 바꾼다.
브라우저 시험은 빈 과제, 명시적 시연 연결, 저장 검수 선택, 응답 유실 재시도, 중지·중지 대기·실패,
완료 근거, 자료 검사와 상태 폴링 분리, 키보드·재진입·여러 시연 선택을 포함한다.
362 skip은 실행하지 않은 옵션 시험이며 장치·GPU·현장 수용으로 계산하지 않는다.

초기 영향 시험은 3,374 passed / 360 skipped / 5 failed였다. 새 CSS의 의미 색상·글자 크기·줄 간격
토큰, 반응형 구간, 중복 hidden 규칙을 공통 계약에 맞춰 수정했다. 검사나 허용 목록은 약화하지 않았다.
새 통합 시험은 처음에 모듈 경로와 fixture를 일반 pytest 환경에서 만드는 문제로 실패했다.
네이티브 fixture 생성·영상 읽기·학습은 기존 pinned learner Python을 사용하도록 고쳤다.
최종 다중 시연 시험은 select 안에 포함된 label 문구의 정확한 접근성 이름을 찾지 못했다.
독립 label/for 연결로 고쳤고 동일 시험을 포함한 12개 Chromium을 재실행해 통과했다.

독립 읽기 전용 검토가 찾은 진행 중 작업의 상태/중지 숨김과 다중 시연 검수 선택 문제는 수정하고
회귀로 검증했다. 수정 재검토에서 추가 중요 발견은 없었다. 원본·과제·장치 권한 변경은 없다.

원격 PC의 다른 작업으로 대기한 중복/이전 소스 호출은 task 소유 job만 종료했다(143, 미실행 또는
수행 중단). site PC의 조기 보조 검사 한 호출은 여유 부족으로 미실행 종료했다. 통과 수에 넣지 않았다.
마지막 예약량은 기존 실측 peak(브라우저 약0.3GiB, 실제 학습 약1.6GiB)를 기준으로 각각1GiB/3GiB로
설정했다. 공식 runner의 프로세스 메모리 제한·독점 작업/CPU/메모리 admission 검사는 유지했다.

## 실제 브라우저 완주

모델 시험 PC에서 정상 HTTP 경로만 사용했다. API 응답 가로채기·worker 모형·가짜 학습은 없다.
실제 장치 대신 명시적인 합성 native LeRobot v3 시연 두 세션을 만들었고 pinned LeRobot0.4.4 CPU
환경으로 실행했다. 의존성 설치·환경 업그레이드·운영 라벨 변경은 하지 않았다.

브라우저에서 과제를 열고 시연을 연결 → 검수 탭에서 영상 프레임 디코딩 확인 → 학습/평가 시도 선택과
사람 검수 저장 → 과제로 복귀 → ACT100단계 시작 → 결과 확인 → 정상 artifact 링크로 ZIP 다운로드까지
완주했다. 원래 decisions 파일은 그대로다. 다운로드 ZIP의 요청·결과 과제 snapshot과 실제 호스트
`model`을 확인하고 모든 모델 파일 SHA-256을 검증했다.

- 과제: `ff015cc1-a2d6-4d5a-9cf5-2d2925d5a2cb`; 실행: `77deb693-003d-4692-a8e0-1bbfa6521580`.
- 100단계, 독립 평가3samples, 평균 관절 MAE9.8316509 / 학습 평균 기준10.
- 새 프로세스 모델 재로딩 true, `physical_learning_verified=false`, 실물 성공값 null.
- 검수·학습·오프라인 평가만 완료 근거가 있다. 녹화·실물 평가·적용 승인은 미확인이다.

이 수치는 정규화된 합성 6관절 smoke 결과다. 실제 작업 성공률·실물 정확도를 나타내지 않는다.
task 전용 원격 `~/rosy-test/evidence/learning-tabs-pipeline-20261029-final/`과 로컬
`C:/DevTemp/learning-tabs-20261029/learning-tabs-pipeline-20261029-final/`에 ZIP·proof·실제 결과 캡처를 보존했다.

proof.json SHA-256: `160163172559b83017c0ff3c86389277191044fbdd75962bacb562cccefc208f`.

download.zip SHA-256: `df3c2123f8ea377d7847b6c3a19d05a5d37ac0c7f70d5105456245c40f05623c`.

## 화면과 원본 로그

dark/light 각각1366×768,390×844,320×568의 최종 캡처6개를 직접 확인했다. 가로 넘침 검사도 통과했다.
캡처는 `learning-tabs-accessible-ui-20261029/learning-workflow-results-<theme>-<size>.png`다.
모바일에서 카드는 한 열이고 탭·시연 선택이 유지된다. fixture 캡처의 오차0.125와 실제 학습 오차9.832는
서로 다른 증거다. 실제 브라우저 완주 캡처는 위 numerical evidence의 result-desktop.png다.

로컬 로그 루트는 `C:/DevTemp/learning-tabs-20261029/`다.

affected-verified/run-1.txt SHA-256: `ced5a1faee719a8fb054fc0ba6bb35e85fb91ba002329092b0e86c673725b57c`.

browser-accessible/run-1.txt SHA-256: `41d1ae3bb0593c0372828394a3941565a06b58af082b37ab2ac650b7f951e4bb`.

pipeline-model/run-1.txt SHA-256: `24fd5ed5b7ef43f943d9dc79b3b17df01b5fe742a095a9de0f0bf5747d55de47`.

workflow-measured/run-1.txt SHA-256: `aae0097b22eb4b1d61dc5620427ec9ea368931f5e297a117e2b61ad819604495`.

## 미리보기와 수용 한계

task 전용 소스 `~/rosy-test/runs/learning-tabs-preview-95c5598ba6`와 기존 별도 합성 상태를 사용한다.
`rosy-learning-structure-preview-20261029.service`는 loopback 전용·2시간 TTL·MemoryMax2G·CPUQuota200%다.
기존 preview 재시작에서 생성 전용 empty-training 옵션을 다시 준 실패는 기존 상태로 재개하도록
helper만 고쳤다. 운영 상태나 사람이 만든 원본 자료는 바꾸지 않았다.

실물 녹화의 웹 전송, 현장 보정·장치 통합, 실제 로봇 추론/성공률, 온라인 HIL·VLA·공통 SIM 어댑터는
미수용이다. 실행 가능한 것으로 표시하지 않는다. 상용 배포·부하/보안 운영 수용·실물 안전 수용·main
착지·push를 수행하지 않았으므로 이번 기록만으로 상용 출시 완료를 선언하지 않는다.

CE: 해당 없음 — pinned learner의 기존 환경 경계 교훈을 적용했고 이번 수정은 코드·회귀·이 기록으로
재구성할 수 있다. 같은 내용을 별도 교훈으로 늘리지 않았다.
