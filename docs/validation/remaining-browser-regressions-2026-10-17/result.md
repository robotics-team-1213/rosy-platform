# 남은 브라우저 회귀 수정

2026-10-17. 브랜치 `fix/remaining-browser-regressions`, 기준 커밋 `96424b3227`,
수정 커밋 `eab1d0fb1`의 기록이다. 사용자 요청에 따라 직전 카메라 교정 검증에서
남았던 소프트웨어 문제를 처리한다. 실제 촬영·측량·DEVICE/FIELD·D-598 운영 활성화는
앞서 합의한 제외 범위를 유지한다. push·배포는 수행하지 않는다.

## 수정과 근거

| 항목 | 원인 | 수정 |
|---|---|---|
| 픽셀 사진의 첫 화면·낮은 화면 배치 2건 | `pixels.js`가 AI 참고 패널을 사진 위로 이동해 사진을 아래로 밀었다 | 원래 사진 아래의 참고 패널 배치를 유지한다. 라벨 저장·사람 승인·AI 동작은 바꾸지 않는다 |
| 만료된 기억 토큰 검사 | 계정 세션 조회가 먼저 실행되는 현재 초기화 흐름을 옛 호출 목록이 반영하지 않았다 | 익명 GET 두 개를 정확히 확인하고, 만료 토큰 삭제와 로그인 서랍 표시 검사를 유지한다. 고정 지연 대신 실제 연결 조회를 기다린다 |
| 셸 비상 정지 검사 | 문자열 대기식이 현재 CSP의 `unsafe-eval` 금지에 걸렸다 | 함수 대기식으로 바꾼다. 실제 CORE 요청과 `services.safety.estop` 검사는 유지한다 |
| 보정 표시의 단독 실행 | 옛 `src/runtime` import 경로 때문에 다른 시험의 경로 설정에 의존했다 | 현재 `middleware/core`와 `contracts/foundation` 경로를 직접 사용한다. 실제 보정 lease 생성·표시·해제는 유지한다 |

앞선 전체 lab tier의 실패 원본은
`C:/DevTemp/camera-calibration/landing-full-green-receipt.json`과 그 receipt가 결속한
`land-fixed/feat-measured-camera-calibration/run-1-20.txt`부터 `run-1-22.txt`에 있다.
이번 기준과 그 당시 커밋 사이에서 위 네 수정 파일은 변경되지 않았음을 확인했다.
앞선 실패가 수정본의 성공 증거가 되지는 않는다. 보정 표시 1건의 넓은 묶음 통과도
독립 실행 성공으로 재해석하지 않는다.

## 확인한 범위

- `node --check learning/curation/perception/review_app_web/pixels.js` 통과.
- 수정한 Python 시험 파일 3개의 `ast.parse` 통과.
- `git diff --check` 통과.
- 수정 커밋의 `safety_review.py 96424b3227 HEAD` 통과.
- 독립 계약 검토 `/root/camera_contract_review`: 지원되는 P1/P2 지적 없음.
  화면 배치만 바뀌고, 인증정보 수명·최종 정지·사람 라벨 저장 경로가 유지됨을 확인했다.
  검토자는 시험을 실행하거나 현장 수용을 확인하지 않았다.

## 원격 검증 대기

현재 시험 PC 세 곳 모두 SSH 연결 시간이 초과된다. 로컬 Tailscale의 Running/online과
시험 PC로의 SSH 도달 가능성은 구분해 확인했다. 네트워크 프로필을 전환하거나 장치에
접근하지 않았다. 시험 도구의 30초 간격·최대 10분 재시도 절차를 유지한다.

원본 기록은 저장소 밖 `C:/DevTemp/browser-regressions/`에 둔다.

- `baseline-runner.txt`: 기준 커밋에서 기존 실패 다섯 node를 다시 확인하는 실행.
- `fixed-runner.txt`: `eab1d0fb1`의 같은 node들과 픽셀 도구·AI 참고·보기 상태 회귀.
  보정 표시 node는 별도 invocation으로 실행해 import 순서 의존을 드러낸다.
- 두 실행 모두 `ROSY_RUN_BROWSER_TESTS=1`을 명시한다. 로컬 pytest 대체 실행은 하지 않는다.

위 원격 결과를 확보하기 전에는 수정 성공이나 전체 회귀 통과로 표시하지 않는다.
`test/known_failures.txt`의 다섯 항목도 유지한다. 각 node의 커밋된 수정본에서 실제 실행,
skip 없음, 성공과 `known_failures.py` 비교를 확보한 뒤에만 해당 항목을 제거한다.
그 뒤 변경 범위 검사·필요한 전체 lab tier를 거쳐야 main에 착지할 수 있다.

## 전달 브랜치 정리

초기 `eab1d0fb1`의 대시보드 시험 파일이 기존 크기 상한보다 두 줄 늘어 커밋 단위
크기 검사에서 거절됐다. 같은 두 GET 기대값과 실제 조회 대기를 유지하면서 각 문장을
120자 안에 정리했고, 시험 파일의 길이를 기존과 같게 유지했다.
원래 검토 이력은 `fix/remaining-browser-regressions`에 보존한다. 전달 브랜치는
같은 기준 `96424b3227`에서 만든 `fix/browser-regressions-ready`이며 최종 변경을
한 번에 담는다. 실패 목록을 줄이거나 크기 상한을 높이지 않는다. 최종 커밋의 원격
검증도 별도로 필요하며, 앞선 초기 커밋의 재시도를 최신 커밋의 결과로 재사용하지 않는다.
