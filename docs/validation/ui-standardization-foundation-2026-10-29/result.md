# UI 표준화의 공용 발견·회귀 선택 기반

2026-10-29, `fix/ui-surface-discovery`. 시작점 `f05af50515`, 최종 소스·시험 `bc25167b00`. 등록된 12개 표면과 제품 소스 holder의 HTML 31개를 대조했다. 전체 플랫폼 UI 표준화의 첫 검증 단위이며 나머지 앱 이행 완료 기록이 아니다.

## 변경과 발견 경로

독립 설계 평가 A(`/root/ui_design`)와 detector·시험 범위 평가 B(`/root/ui_evidence`)를 서로의 결과를 공유하기 전에 수행했다. 소스 감사에서 `discover_html()`이 은퇴한 `src/`와 `operations/`만 훑어 현재 applications·middleware·learning·integrations·shared의 새 HTML을 놓치는 것을 발견했다. 기존 등록 표면의 `for_contract()` 검사는 살아 있었다.

Git의 tracked·untracked·ignore 의미를 유지하면서 현재 제품 holder 6곳을 검색한다. 문서·도구 산출물은 제품 표면으로 취급하지 않는다. 새 fixture는 각 holder에서 추적된 HTML과 add 전 HTML을 모두 찾고 ignored HTML·다른 확장자·문서를 제외하는지 검사한다. 미등록 검사 이름과 안내도 현재 소스 어휘로 바꿨다.

셸 발견 검사는 HTML의 직접 module 또는 진입 module의 직접 공용 UI import를 인정한다. Learning의 실제 ESM 구조를 지원하면서 HTML/JS 주석, template 예시, 사용하지 않는 경로 문자열과 없는 파일은 로드 증거로 인정하지 않는다. 전체 JS resolver를 만들지는 않았다. 공용 자산 변경 시 실제 소비자인 Monitoring과 SIM 레인 뷰어도 브라우저 선택에 포함한다.

## 실제 실행 근거

로그 원본은 저장소 밖 `C:/DevTemp/rosy-ui-standardization/`에 있다. 아래 여섯 로그의 SHA-256은 `reports.sha256`에 고정했다. 모두 공식 원격 시험 PC에서 커밋된 SHA를 실행했다. 운영 데이터·계정·HF·로봇 명령을 사용하지 않았다.

| source | 실행·로그 | 결과 |
|---|---|---|
| `3109535984` | 신규 holder 발견 fixture / `discovery-red/run-1.txt` | 변경 전 5 실패·1 통과. operations만 발견함 |
| `23d6ccf766` | consumer 선택·module entry fixture / `consumers-red/run-1.txt` | 변경 전 3 실패. 신규 지원 함수 부재 2개와 누락된 consumer 선택 1개 |
| `70f1ef10da` | 주석 속 import 부정 fixture / `comments-red/run-1.txt` | 리뷰에서 찾은 오인 2 실패 |
| `bc25167b00` | registry·shared controls·browser scope / `discovery-verified/run-1.txt` | **78 passed, 0 skipped** |
| `bc25167b00` | 공식 affected JSON → remote runner / `foundation-verified/run-1.txt` | **861 passed, 0 skipped**, warnings 46 |
| `8e4826c93b` | `ROSY_RUN_BROWSER_TESTS=1 test/test_monitoring_browser.py integrations/simulation/gazebo/test/test_lane_live_view_browser.py` / `consumer-browser/run-1.txt` | **18 passed, 0 skipped**. 이후 bc25167b00까지 시험 코드만 변경, runtime 자산 동일 |

마지막 세 합격 로그는 `test/known_failures.py`에서 각각 NEW 0 / known 0 / flaky 0이다. 비교기가 표시하는 listed-but-not-failing 테마 시험 한 개는 이 실행에서 수정됐다는 뜻이 아니므로 baseline에서 제거하지 않았다. 이전 중간 실행(`consumers-green`, `discovery-green`, `foundation-full`)도 삭제·덮어쓰지 않았다.

영향 selector는 `test/browser_scope.py` 변경 때문에 **FULL 티어**를 선언한다. 정본 `remote_pytest.affected_invocations()`는 full일 때 `local_invocations` 사전 계약을 실행하므로 위 861건은 그 한 묶음이다. 이를 FULL 27묶음·전체 CI·제품 전체 브라우저 통과로 쓰지 않는다. `foundation-full`은 중간 로그 폴더 이름이며 FULL 완료 증거가 아니다. 로컬 pytest는 실행하지 않았다.

## 검토와 한계

A는 최종 검사 수정을 재검토해 주석 오인 P2 해소와 추가 필수 문제 없음을 보고했다. 런타임 UI·토큰·API·명령 권한·설치 자산은 변경하지 않았다. 실제 Chromium 두 소비자의 실행을 확인했지만 새 시각 캡처나 G2/G3·native 빌드·장치·현장 수용을 선언하지 않는다.

별도 후속 목록에는 Learning 저장 공간의 일반 버튼 2개, Games 수신 신선도, Robot SSH 작업 오류 수명, Fleet 요청 목록·Pilot 녹화 목록의 초점, native Pilot 목록 초점·Cam 비활성 이유가 남아 있다. 각 앱의 별도 브랜치·시험·화면 증거로 처리해야 한다. 배포·착지·push·merge는 수행하지 않았다.

CE: 해당 없음 — 경로 이동 뒤 발견 범위가 빠진 원인과 복구 조건은 최종 발견 함수·6곳의 Git fixture·module/주석 부정 fixture 및 이 검증 기록으로 재구성할 수 있다. 기존 교훈 `docs/solutions/workflow-issues/landing-blockers-cost-hours-2026-10-18.md`의 registry 소비자/시험 선택 범위 확인을 적용했고 별도 중복 교훈을 만들지 않았다.
