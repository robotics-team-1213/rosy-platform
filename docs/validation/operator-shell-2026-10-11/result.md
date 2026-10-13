# D-641 운용 shell·아이콘·근거 검증

## 구현과 독립 검토

헤더의 전역 조작, 좌측 문서 탐색, 중앙 업무, 우측 현재 맥락, 흐름 안의 푸터를 Fleet 네 문서에 적용했다. 아이콘은 공용 이름과 SVG를 사용하며 선택 상태와 접근성 이름을 유지한다. 설명은 hover와 키보드 focus에서 열리는 공용 tooltip으로 제공한다. 필수 위험·거절 이유·실행 상태는 보이는 문구로 남긴다.

사건은 요약과 다음 조치를 먼저 보여주고 판단 근거와 개발 진단을 단계적으로 연다. 기존 검토·내보내기·권한 검사를 유지하며 AI 제안, Fleet 전달, CORE 수락과 완료를 구분한다. 새로운 API나 메시지 broker는 추가하지 않았다.

독립 검토에서 기존 테마·새로고침 버튼의 키보드 설명 누락 P2 한 건을 발견했다. 공용 `actionIcon`에서 기존 title과 접근성 이름을 연결하고 실제 소비 마크업 회귀를 추가했다. P1은 발견되지 않았다.

## 원격 실행 증거

| 검사 | 소스 | 실행 결과 | 로그 |
| --- | --- | --- | --- |
| 공용 아이콘·tooltip·토큰·CSP·선택 상태, 기존 아이콘 설명 회귀 | 4402c5c4b | 102 PASS, NEW 0 | X:/DevTemp/ui-shell-common-641/run-4.txt |
| 사건 요약·근거·진단, 카메라 만료, 검토·거절·focus 보존 | 92592fc2ef | 16 PASS, NEW 0 | X:/DevTemp/ui-shell-evidence/run-3.txt |
| 헤더 네 문서·크기, 인증·세션·수명 | d73e03894 | 24 PASS; 별도 traffic 실패 3건은 아래 통합에서 재검증 | X:/DevTemp/operator-shell-fleet-d73/run-1.txt |
| 통합 네 문서 두 테마·네 폭, traffic, 개입, 의미 아이콘, 세션·수명 | 354b7f95fd | 45 PASS, NEW 0 | X:/DevTemp/operator-shell-root-integrated/run-1.txt |
| 관측 만료의 지도 위치 보존·낮은 창의 작업 흐름·네 문서 두 테마/네 폭 | 3410a453bf | 4 PASS, NEW 0 | X:/DevTemp/operator-shell-root-map-flows-fixed/run-1.txt |
| 축소 지도 로봇 식별자·동일 자리 겹침 방지·최우선 표시와 기존 역할 | ff534fae66 | 6 PASS, NEW 0 | X:/DevTemp/operator-shell-map-labels-ff534/run-1.txt |
| 탐색·지도 자산·전체 Node 단위 wrapper의 현재 shell 계약 | 511f62c90 | 28 PASS, NEW 0 | X:/DevTemp/operator-shell-static-node-511f/run-1.txt |
| 사건 패널 분리·검토/내보내기·페이지 scope·wheel/sdist 설치 자산 | e58d7c4f52 | 36 PASS, NEW 0 | X:/DevTemp/ui-incident-view/run-2.txt |
| 전체 콘솔 브라우저 | bc891a06977 | 117 PASS, NEW 0; root ed92d719a와 tree 동일 | X:/DevTemp/operator-shell-broad-final-ed92/run-1.txt |
| 최신 main의 지도 상황 패널 통합·좌표 만료·네 문서/테마/크기·traffic | 2a57511acc | 14 PASS, NEW 0 | X:/DevTemp/operator-shell-map-context-integration/run-1.txt |
| 최신 지도 상황 패널의 영상 만료·map plane·보정 경고 | 2a57511acc | 3 PASS, NEW 0 | X:/DevTemp/operator-shell-map-context-camera/run-1.txt |

통합 시험은 main의 지도 높이 수정과 profiles fixture를 포함한다. 하위 브랜치의 오래된 fixture 실패는 통합 시험에서 재검증했다. 별도 기존 지도 흐름 검사에서 좌표 만료 시 높이 변동과 낮은 창의 고정 프레임 2건이 NEW로 확인됐다. 펼친 좌표에만 안정된 높이를 적용하고 낮은 창은 문서 흐름을 사용하도록 수정했다. 같은 두 검사와 네 문서 두 테마·네 폭을 다시 실행하여 모두 통과했다. 실패 목록이나 검사 기준은 완화하지 않았다.

스크린샷 경로 권한 오류가 있었던 이전 실행은 수용 증거로 사용하지 않는다. Python과 Chromium은 원격 PC에서 실행했으며 공용 최신 회귀와 통합 실행은 각각 가용 메모리 7.6 GB, 8.2 GB로 pytest 하한을 충족했다. 마지막 지도 흐름 회귀도 가용 메모리 10.2 GB로 하한을 충족했다. 중복된 시험 수는 합산하지 않는다.

기존 main의 CI에서 실패했던 로봇 이름표 검사를 현재 소스에서도 재현했다. 축소 지도에서 글자 상자와 자기 로봇 표식이 겹쳐 일반 이름표가 숨겨지는 원인을 공용 글자 크기와 배율에 맞춘 간격 계산으로 수정했다. 같은 자리의 중복 숨김과 최우선 식별자 조건은 유지했다. 전체 검사에서 신규 탐색 속성과 역할 표시를 거부했던 옛 fixture는 실제 현재 계약에 맞춰 갱신했으며 제품 권한 기준은 변경하지 않았다.

사건 표시가 console의 기존 zero-growth 제한을 넘겨 명시된 분리 의무를 적용했다. console.js는 994줄, incident-view.js는 219줄이다. 패키지와 지도 표시의 성장 판정은 독립 검토를 받았으며 기존 예산·분리 의무를 유지했다. 전체 브라우저 실행의 공통 tree는 `19e29a385116`이며 실행 커밋과 통합 커밋을 구분했다. 이후 main의 지도 상황 패널 변경은 별도 14개와 영상 3개 시험으로 재검증했다.

공식 `tools/land.py --tests auto`는 `2a57511acc53`을 main에 fast-forward했다. 원격 검사 첫 호출 4,605 PASS·696 SKIP, 두 번째 호출 492 PASS·81 SKIP, known_failures 모두 NEW 0이다. 로그는 `X:/DevTemp/operator-shell-land-2a57511acc/run-1-1.txt`와 `run-1-2.txt`이다. 건너뛴 검사는 실행 증거로 계산하지 않는다.

## 수용 경계

이 문서는 소스 검증 시점의 증거다. 정확한 출시 SHA의 푸시·CI·서명 설치와 설치본 화면 검증은 `artifacts/receipts/operator-shell-2026-10-11/<source-sha>/receipt.json`에 별도로 기록한다. 소스와 원격 브라우저 결과는 설치본이나 실제 기기 수용을 대신하지 않는다. 로봇 이동·E-Stop 해제·실물 주행 시험은 수행하지 않았다.
