# 장치 읽기 표 항목명 가독성 후속 — 2026-11-05

이 기록은 [최종 통합 근거](final-closure.md) 이후의 실제 화면 발견과 수정이다. 최종 공식 FULL·main 이동 전 기록이며 전체 착지 GO를 선언하지 않는다. 과거 성공·HOLD·취소 결과는 소급하지 않는다.

## 발견과 수정 범위

완료 감사에서 최종76b의 장치 화면을 기존 두 capture 함수로 다시 확인했다. 실제320/390 긴 값 상태는 한 값이 모든 행 항목명 열을1–2글자로 압축했고 SSID도 갈라졌다. 이전 G3의 해당 수용을 원 검토자가 P2/HOLD로 정정했다. 새 네트워크 진단4행 자체는 읽을 수 있고 원천에 정직했다.

Robot 소유 surface-panels.css에서 기존 host.operations 표에만 fixed layout과40% 항목명 열을 지정했다. 공용 표·색/토큰·원본 값/값 줄바꿈·caption·초점/스크롤·조작 우선·권한/명령/API·기존 확인은 바꾸지 않았다. 새 카드·접힘·도구는 없다.

현재 peer main26752318cf를 정상 merge한4f6dc2 이후,6563dac55f의 기존 production 긴 값 시험에 실제 행 항목명의 쓸 수 있는 폭 회귀를 추가했다. 패딩을 빼고 font-size4배 이상인지 확인한다. 첫1366 경우가44.30px<56px(font14)로 실제 RED1/NEW1이었다. 이것은 새 제품 수치 기준이 아니라 전체 label 열이 한두 글자로 붕괴하는 현상을 잡는 회귀 하한이며 실제 세 폭의 G3를 함께 판단했다.

## 고정 소스 실행

| 소스 | 실행 | 결과/제한 |
| --- | --- | --- |
| 6563dac55f | 기존 long-readout production 시험 |1 fail/0skip/NEW1,11초. CSS 수정 전 실제 열 압축 재현 |
| df46d9a2f4 | 기존 긴 값·identity-feedback 두 capture 함수 |2 pass/0skip/NEW0,exit0,11초. 실제1366×768·390×844·320×844의 표3장, native summary-open1366/390 진단2장 |
| df46d9a2f4 | host/role/remaining/panel/package/shared-controls/size 기존7파일 |171 pass/0skip/NEW0,exit0,303초. 불필요한138장 재생성 없이 실행 |
| 0cc1e36a35 | 제품 동일, Robot logs/index 기록2파일만 추가 |main..HEAD92커밋 size/safety PASS,lint0오류43경고,tracked/index clean. role 시험1484/1500,CSS127/600 |

source와 명령·전체 RED/GREEN 출력·분류·원격/로컬 해시는 ROSY 작업 공간 `docs/workspace-records/2026-11-05/ui-map/review-reports/host-header-r9-report.md`, `host-header-r9-test-logs/`에 보존했다. 원본은 `host-header-r9-df46d9a2f4/`, 지문은 [후속 manifest](host-header-r9.sha256)다.5 PNG·폭 JSON3개·기존 matrix JSON·JUnit10파일 모두 원격 원본 해시와 일치한다. 원본 진단 화면의 사설 주소/호스트 값은 이 기록에 옮기거나 Git에 추가하지 않는다.

| 실제 viewport | 최소 항목명 content 폭 | 글자 크기/회귀 하한 |
| --- | --- | --- |
|320×844 |101.59px |14px/56px |
|390×844 |129.59px |14px/56px |
|1366×768 |398.39px |14px/56px |

각 폭의24개 행 머리글을 측정했다. 값은 자신의 열 안에서 줄바꿈하고 모든 원래 값이 남는다. 기본 dark 캡처이며 light나320의 열린 identity 진단을 촬영한 것으로 부르지 않는다. 색 코드는 변경하지 않았다.

## 독립 G3/소스 검토

원 검토자는4f6dc2..df46의 두 커밋과 새5 PNG 전부를 보고 P2 ADDRESSED, scoped spec/quality 승인·새 발견0으로 판정했다. 값/누락·증거 상태·색·평평한 위계/조작 우선·불가역 확인·읽을 수 있는 어휘·표면 질문·절차 스크롤의 여덟 항에서 해당 수정의 위반이 없음을 확인했다. 다른 표면 전체를 새로 감사하거나 실물 수용을 수행했다는 뜻은 아니다.

## 전체 완료 조건과 남은 검증

새 CSS 뒤 최종 현재 트리 G1과 기본 공식 AUTO/FULL·실제 main ancestry는 별도로 확인한다. G1은 기존14파일에 실제 현재 `middleware/core/api/test/test_ui_route.py`와 `test/test_web_dialog_contract.py`를 더한다. D-153의 옛 `test_styleguide.py` 예시 경로는 현재/접근 가능한 이력에 없고, 실제 styleguide serving/token/allowlist 시험은 처음부터 test_ui_route.py에 있었다. 은퇴나 PARKED로 지어내지 않는다. 현재 Robot/Fleet의 dialog 계약도 실행하며 Learning 인증/폼의 명시된 예외와 구분한다. 새로운 시험이나 ADR 변경은 필요 없다.

소유015709 gate는 이 실제 G3 HOLD 때문에 canonical stop으로 중단했고 원격 own collection handle도 process/lease0으로 확인했다. 완료된 부분 출력의 rc0을 FULL 통과로 합치지 않는다. Peer main과 다른 FULL·GPU·queue는 그대로다. 이후에는 수정된 고정 최종 소스만 기본 경로로 다시 요청한다.

CE: 해당 없음 — 기존 D-153/D-926의 가독성 요구, scoped CSS 및 실제 폭/화면 회귀가 원인과 보장 조건을 직접 설명한다. GitHub 게시·배포·실물·모델 품질·FIELD 수용은 이 LOCAL 기록에 포함하지 않는다.
