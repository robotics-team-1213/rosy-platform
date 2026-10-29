# Pilot 녹화 목록의 초점과 조회 수명

2026-10-29 · `fix/pilot-recording-focus` · 지원 브랜치 `3d036c77f9` 기준 제품 diff · runtime `e3e0fec900` · 최종 시험 `d99e15a1e2`.

## 변경

기존 코드는 목록이 같을 때만 DOM을 유지했다. 행 재정렬·삭제·받기/취소 전환에서는 현재 초점이 사라졌고, 닫았다 다시 연 시트가 이전 시트의 GET 결과를 받을 수 있었다.

DOM 교체 직전에 목록 안의 현재 녹화 ID를 읽어 같은 행의 enabled 동작으로 복원한다. 사용할 동작이 없으면 그 행의 보이는 facts, 행이 사라지거나 조회가 실패하면 기존 notice로 이동한다. 목록 밖으로 옮긴 초점·입력은 유지하며, 초점 중인 notice도 숨기지 않는다. 같은 상태이면 다시 만들지 않는 기존 최적화는 유지했다.

조회 진행 여부는 시트 객체로 관리한다. 새 시트는 이전 조회를 기다리지 않고 자기 조회를 시작하며, 이전 응답은 새 시트 DOM이나 조회 잠금을 바꾸지 않는다. 실제 전체 drive 검사에서 재정렬 후 올바른 버튼이 목록 스크롤 밖에 숨는 것을 확인해 nearest scroll로 드러내도록 보완했다.

공용 ui-button/ui-text·토큰·CSS·API·권한·녹화 시작/정지·파일 검증·닫기/나가기 취소 정책은 유지했다. 새 컴포넌트나 의존성은 없다. 시험 분리·selector·ratchet 변경은 별도 지원 브랜치의 frozen 기록이 소유한다.

## 원격 증거

원본 scratch는 `C:/DevTemp/rosy-ui-standardization/`이며 reports/captures manifests로 확인한다. 모든 pytest는 승인된 시험 PC에 커밋 SHA를 전달한 실행이다.

| SHA / 로그 | 결과 | 판단 |
|---|---|---|
| `a868fa0002`, pilot-focus-red/run-1.txt | 11 failed, 1 passed, 17 deselected | 제품 반례8경우와 fixture 실패3경우를 구분 |
| `ef820ea179`, pilot-focus-green/run-1.txt | 3 failed, 26 passed | 남은3개는 bytes+1이 표시 서식에서 반올림돼 같은 state인 fixture. 제품 early return을 지우지 않고 시험을 가시적인 +1MB 변화로 보정 |
| `d7b73e2e5d`, pilot-focus-visibility-red/run-1.txt | 2 failed, 37 deselected | 실제320/1200 drive에서 초점은 맞지만 viewport ratio0인 반례 |
| `e3e0fec900`, pilot-focus-final/run-1.txt | 39 passed, 0 skipped | 녹화 browser 파일 전체·캡처12장 |
| `e3e0fec900`, pilot-focus-affected/run-1.txt | 1 failed, 608 passed, 189 skipped, 56 warnings | 지원 분리의 ratchet 감소 누락. 지원 브랜치에서 고쳐 merge |
| `088329aebc`, pilot-focus-stop-green/run-1.txt | 39 passed, 0 skipped | 정지 버튼 viewport assertion 추가 후 전체 재검증 |
| `088329aebc`, pilot-focus-ratchet-affected/run-1.txt | 609 passed, 189 skipped, 56 warnings | 공식 affected 재검증 |
| `b269a1b4b4`, pilot-focus-keyboard/run-1.txt | 8 passed, 31 deselected, 0 skipped | 실제 Shift+Tab/Tab modality 뒤 전체 drive8경우·새 캡처8장 |
| `d99e15a1e2`, pilot-focus-scroll-check/run-1.txt | exit143, 시험 미실행 | admission 대기 중 Terminated. 접속 관측 timeout을 종료로 오인하지 않았고 실제 종료 코드를 받은 뒤 재요청 |
| `d99e15a1e2`, pilot-focus-scroll-retry/run-1.txt | 8 passed, 31 deselected, 0 skipped | window.scrollY 불변 assertion 추가 후 전체 drive8경우 |

합격 로그는 모두 NEW0/known0/flaky0이다. 초기8제품 반례는 받기→취소 초점2경우, 재정렬·disabled·삭제·빈 목록·조회 실패·닫기/재열기다. fixture3경우는 다른 행/목록 밖/처음부터 목록 밖 초점이며 최초 실패를 제품 결함으로 세지 않는다. 반복39건과 부분8건을 합산하지 않는다.189 optional browser skip은 실행 통과가 아니며 전체 CI/FULL·Android 시험도 아니다. e3→088→b269→d99의 runtime 파일은 동일하다.

주입 request fixture는 재정렬·disabled·삭제·빈 목록·조회 실패·대기 중 다른 행/밖 이동·다운로드 완료/거부/짧은 본문 후 입력 보존·닫기/재열기의 응답 순서·dispose 뒤 늦은 응답을 검사한다. 실제 dev_server 전체 drive에서는320×900/1200×800의 받기→취소/나가기,12행 재정렬·행 삭제·받기 제한·조회 실패, 대상 초점·viewport·상단 정지·문서 스크롤 위치를 검사한다. 실제 기기나 파일을 쓰지 않는 fake CORE 근거다.

## 독립 검토와 캡처

A는 최종 runtime의 현재 초점·fallback·시트 소유권·nearest scroll을 검토했고 해당 diff에 추가 P1/P2는 없다. B는 초기 최종12장과 실제 키보드 modality의 새8장을 각각 모두 직접 확인했다. 받기/취소 버튼, disabled facts, 삭제/오류 notice의 초점 테두리와 목록 안 대상이 보이고, 모든20장에서 상단 비상 정지가 패널에 가려지지 않는다. Root도 두 묶음에서 각각2장을 직접 확인했다.

`pilot-focus-captures-final/`의12장은 e3의 receiving/cancelled/reorder/removed/disabled/read-failed × 두 폭이다. `pilot-focus-keyboard-captures/`의8장은 b269(동일 runtime)의 뒤 네 결과×두 폭이다. 이전12장을 덮어쓰지 않았다. 새8장에서 notice/facts의 파란 키보드 초점 테두리를 확인했다. 같은 날짜·문구가 반복되므로 정확한 녹화 ID·전환 과정·주입 응답 경합은 정지 이미지로 증명하지 않으며 브라우저 assertion과 구분한다. Pilot은 등록 계약에 따라 dark 고정이다. 더 짧은 viewport·실기 동작 수용으로 확대하지 않는다.

## 게이트와 CE

소스 UI 근거만 추가했다. 실제 로봇 녹화·다운로드 수신·명령/정지 readback·라벨·실제 HF·native 빌드·ARTIFACT/DEVICE/FIELD·배포·착지·공개 push/merge는 수용하지 않았다. 다른 표면과 최종 통합 검증은 진행 중이다.

CE: 해당 없음 — 시트 객체/현재 초점 경계와 클리핑 반례는 최종 코드·회귀·이 검증 기록으로 복원된다. 새로운 일반화된 규칙이나 중복 교훈을 늘리지 않는다.
