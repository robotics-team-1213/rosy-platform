# 학습 과제 중심 구조와 native ACT 연결 검증

2026-10-29. 제품 소스 `edeef55180`, 브라우저 시험·문서 보정 `2cac25d227`.
기준 merge는 `f48c3f1546`이다. 이 기록은 로컬 작업 브랜치의 소프트웨어 근거이며
운영 배포·실물 녹화·장치 적용·현장 수용을 뜻하지 않는다.

## 변경과 사용 경로

`/learning/tasks`에서 과제를 골라 준비 → 직접 조종·녹화 → 검수 → 학습 → 결과로 진행한다.
기존 로봇·과제 등록은 `/learning/tasks/manage`, 장치 프로필과 시연 편집은 기존 화면을 사용한다.
시연을 과제에 명시적으로 연결하면 원본·프로필·과제 revision과 참여 순서가 고정된다.
전체 시연 또는 저장 구간을 선택해 ACT를 시작하며, 요청·worker·결과·다운로드 ZIP이 같은 과제를 보존한다.
과거 과제 없는 실행을 소급 연결하지 않는다. native 연결을 누락할 수 있는 과제 전달은 거절한다.

원본 무결성 검사는 첫 진입·명시적 새로고침에서 실행하고 마지막 확인 시각을 보여준다.
주기적인 상태 조회는 요약 캐시를 사용한다. 연결·학습 admission은 항상 현재 원본을 별도로 검증한다.
완료 표시는 녹화·검수·학습·오프라인 평가·실물 평가·적용 승인을 구분한다.
API와 자세한 제약은 [review-app 안내](../../../learning/curation/perception/docs/review-app.md)의 D-840 절에 있다.

## 원격 시험

로컬 pytest는 실행하지 않았다. 공식 remote runner로 커밋한 소스만 전송했다.

| 실행 | 소스 | 결과 |
|---|---|---|
| affected `--base f48c3f1546 --json`의 선택 전체 | `edeef55180` | 3,642 passed / 368 skipped / 종료 0 / NEW 0 |
| 명시적 Chromium workflow/tasks/native-train 3개 파일 | `2cac25d227` | 8 passed / skip 0 / 종료 0 / NEW 0 |
| harness lint | 같은 제품 소스 | 오류 0, 기존 상태·워크트리 수 경고 41 |

영향 선택에는 native worker·export·Tasks·HTTP·학습 curation 전체, 공유 UI 계약,
프로토콜 정렬, release/land/harness와 문서 배치 검사가 포함됐다. 일반 affected에서 건너뛴
브라우저 시험 중 이번 변경의 세 파일은 별도 Chromium 실행으로 확인했다. 모든 선택 사항의
368 skip을 실물·GPU·SDK·수치 시험 통과로 계산하지 않았다.

최초 Chromium 실행은 7 passed / 1 failed였다. 새 폴링 시험의 문자열 표현식을 Playwright가
평가하면서 실제 CSP의 unsafe-eval 금지에 걸렸다. 함수 형태로 대기를 바꿨고 보안 정책은 유지했다.
최종 세 파일 전체 8건을 다시 통과했다. known_failures에 추가한 항목은 없다.
독립 검토가 찾은 완료 필드 불일치와 반복 영상 해시는 코드·HTTP 호출 수·브라우저 회귀로 수정했다.
최종 수정의 추가 읽기 전용 검토에서 남은 구체적 발견은 없었다.

원격 PC의 다른 독점 시험으로 대기하던 이전 focused/중복 affected/browser/opt-in numerical
호출은 task 소유 job만 종료했다(143, 미실행). site PC의 마지막 중복 browser 호출은
실행 여유 부족으로 120초 뒤 미실행 종료했다. 이것들은 통과 수에 포함하지 않는다.
최종 Chromium은 AI 시험 PC, affected는 여유가 있었던 site 시험 PC에서 실행했다.

원본 로그는 작업 PC의 `C:/DevTemp/learning-structure-20261029/` 아래에 있다.

| 파일 | SHA-256 |
|---|---|
| `affected-site/run-1.txt` | `e39aad7f37ee8b3a895d5f43be68ead981592e5882867246f845bee4b6093cbb` |
| `browser-final/run-1.txt` | `20ed9e7507406bfbedde1606adc439af80b0cd0dac97339dd4708b13460a611d` |
| `http-evidence/proof.json` | `7ac07a06591b6fedd27f90cb96e9425502e44932f083acd87769ebe3cde063bf` |

## 실제 수치 실행과 산출물

모델 PC의 task 전용 합성 preview를 정상 HTTP API로 실행했다. 고정 LeRobot 0.4.4의
기존 CPU 환경을 사용했으며 새 의존성 설치나 운영 센터 상태 변경은 없다.
과제 `21a042a5-f7d8-43fd-9d6b-9fab14f93f43`를 사용했다.
원본 SHA-256: `3aceaddb36d3f5d097c96bcf0b814d64401f8f5bd56eb39d9ff273f755bc9c7f`.

| 검수 입력 | 실행 | 단계 | 독립 평가 | 평균 관절 MAE / 기준 |
|---|---|---|---|---|
| 전체 시연 | `c497962c-c331-437d-a2fa-d38156a1fca1` | 100 | 3 samples | 9.8316509 / 10 |
| 저장 구간 v1 | `b30925c2-46b5-43a5-98f7-687cb653c6ab` | 100 | 3 samples | 9.8315543 / 10 |

두 실행 모두 succeeded이고 `model_reloaded_in_new_process=true`다. 구간 실행의 같은 요청
재전송은 같은 실행 ID를 반환했다. 정상 artifact API로 두 ZIP을 내려받아 모든 model 파일 해시,
파일 집합의 policy revision, `source-request.json`·`result.json`의 동일 `learning_task`를 확인했다.
proof 수집기의 최초 비교는 policy revision을 단일 safetensors SHA로 오인해 실패했다.
기존 계약대로 모델 파일 집합의 canonical 해시를 비교하도록 고쳐 두 ZIP 모두 확인했다.
캐시를 명시 갱신하지 않은 재수집은 segment version 충돌 409로 거절됐고, 갱신 후 같은 요청으로 재수집했다.
제품 검증을 약하게 바꾸거나 실패를 숨기지 않았다.

| 로컬 `http-evidence/` ZIP | SHA-256 |
|---|---|
| `c497962c-c331-437d-a2fa-d38156a1fca1.zip` | `36a1dc7a1fdc066d47c73a7f78d95eb635ea5adc98accaf5c918ec84ec93caad` |
| `b30925c2-46b5-43a5-98f7-687cb653c6ab.zip` | `e5df564482a145f0f9531c991a3ded41f1ba03f5849f4791063e10664ee21e63` |

이 수치는 정규화된 6관절 합성 자료의 작은 smoke 실행이다. 실물 정확도나 작업 성공률이 아니다.
두 결과의 `physical_learning_verified=false`, `policy_activation=false`이며 실물 성공값은 null이다.
workflow는 검수·학습·오프라인 평가만 true, 녹화·실물 평가·적용 승인은 false로 반환했다.

## 화면 확인과 미리보기

Chromium fixture 화면을 dark/light 각각 1366×768, 390×844, 320×568에서 full-page 캡처했다.
여섯 캡처를 직접 확인했으며 조작 폼·단계·결과 문구가 작은 폭에서 줄바꿈되어 접근 가능했다.
모바일 보조 탐색은 공유 셸의 가로 스크롤을 사용한다. 이 캡처의 실행·평가 숫자는 browser fixture이며
위 실제 HTTP 수치 실행과 구분한다. 파일은 로컬 `learning-structure-ui-20261029/`, AI 시험 PC의
task 전용 `~/rosy-test/evidence/learning-structure-ui-20261029/`에 보존했다.

합성 preview는 모델 시험 PC의 `~/rosy-test/runs/learning-structure-preview-edeef55180`에서 실행한다.
별도 `~/rosy-test/evidence/learning-structure-preview-20261029/` 상태를 사용하고,
`rosy-learning-structure-preview-20261029.service`는 2시간 TTL·MemoryMax 2G·CPUQuota 200%다.
운영 서비스 설치가 아니다. 공개 자료에는 실제 접속 정보·계정 설정·토큰을 넣지 않는다.

## 남은 수용 범위

실물 녹화의 웹 전송은 아직 연결되지 않았다. 현장용 task card만 명시 입력으로 생성하며,
기존 OMX owner의 장치·보정·카메라·안전 확인 후 현장 수집이 필요하다. Pilot OMX는 SIM 경로다.
온라인 HIL의 실물 actor·보상·초기화·개입 연결, VLA 미세조정과 공통 과제 SIM 어댑터도 미완료다.
다른 학습 방법의 요건을 표시한 것을 LeRobot 전체 기능 대체 완료로 해석하지 않는다.
실제 팀 자료·실물 조종·실물 추론·현장 성능·운영 배포·main 착지·push는 이번 실행에서 수행하지 않았다.

CE: 해당 없음 — 기존 pinned learner 교훈을 적용했다. 이번 수정의 판단은 코드·회귀 시험·이 검증
기록과 기존 계약으로 재구성할 수 있어 별도 교훈을 늘리지 않는다.
