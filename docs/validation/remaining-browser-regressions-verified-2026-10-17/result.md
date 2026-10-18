# 남은 브라우저 회귀의 원격 재검증

2026-10-17. [앞선 접속 실패 기록](../remaining-browser-regressions-2026-10-17/remote-unavailable.md)에 이어
시험 PC 연결 복구 뒤 수행한 검증이다. 앞선 미실행 결과를 변경하지 않는다.

검증한 최종 commit은 `0e8ba728329a33b4adc47a01368a42b81a011bec`이다.
`tools/remote/remote_pytest.py`가 모델 PC와 AI PC에서 해당 커밋을 실행했다.
코드 검토자는 `camera_contract_review`이며 실제 실행 결과와 별도로 소스를 검토했다.

## 실행과 결과

외부 증거 루트는 `C:/DevTemp/browser-regressions/recheck-20261017T051307Z/`다.
정확한 SHA와 invocation 목록은 `verified-selection.json`, 호스트 배치·종료값은
`verified-runner.txt`와 `verified-exit.json`에 있다. 호출은 다음과 같다.

```text
python -X utf8 tools/remote/remote_pytest.py --sha 0e8ba728329a33b4adc47a01368a42b81a011bec --log-dir C:/DevTemp/browser-regressions/recheck-20261017T051307Z/verified --affected-json C:/DevTemp/browser-regressions/recheck-20261017T051307Z/verified-selection.json  # commit pin
```

각 invocation에는 `ROSY_RUN_BROWSER_TESTS=1`이 있다. 보정 표시는 별도 invocation으로
실행하여 다른 시험의 `sys.path` 변경이 import 오류를 가리지 않게 했다.

| 원본 로그 | 결과 | 기존 실패 비교 |
|---|---|---|
| `verified/run-1.txt` | 19 passed, skip 0, exit 0 | NEW 0, known 0, flaky 0 |
| `verified/run-2.txt` | 보정 표시 단독 1 passed, skip 0, exit 0 | NEW 0, known 0, flaky 0 |

`python test/known_failures.py <원본 로그>`를 두 로그 각각에 실행해 비교했다.
사진·결과의 첫 화면 배치, 짧은 화면의 사진 전체 표시, 만료 토큰 제거,
실제 CORE 비상 정지 상태, 보정 lease 표시·해제의 다섯 기존 실패가 모두 통과했다.
전화 폭 편집 도구, 원본/마스크 표시, AI 참고 초기화, 명시적 전체 채우기 확인,
픽셀 결정·준비, 객체 AI 버튼과 검수 이력도 함께 검사했다.

## 실제 실패에서 수정한 범위

초기 재시도의 CLI 묶음 전달 오류는 exit 4·수집 0이었다. 실행 증거로 세지 않고
runner가 지원하는 JSON invocation 목록으로 고쳤다.

`fcf3499fc7`은 10 passed / 기존 배치 실패 2건, 보정 단독 1 passed였다.
정적 AI 참고 패널 외에도 동적 AI 실행 패널이 사진 위에 남아 있었다.
`a10c699f9`에서 이 패널을 사진 아래로 옮긴 뒤에도 검수 주체 요약과 이력 링크가
사진 위 두 줄을 차지해 배치 실패가 남았다. `39b9305543`에서 이 정보를 사진 아래로
옮겼지만 전화 폭 도구 간격 회귀 2건이 생겼다. 최종 소스는 검수 주체 정보를
픽셀 결정 열의 실제 검수 이력 바로 앞에 두어 사진·도구의 연속성을 유지한다.
중간 실패는 외부 로그에 보존했고 새 실패를 기준선에 추가하지 않았다.

## 화면과 한계

`inspect_layout.py`는 native shipping으로 같은 소스를 모델 PC에 전달하고,
별도 임시 합성 검수 상태에서 loopback 서버를 열었다. 문서 탐색 완료와 실제
마스크·캔버스 표시를 기다린 뒤 1280×720, 1262×632, 390×800 화면을 캡처했다.
`layout-0e8ba72832/`의 세 PNG를 직접 확인했다. 짧은 화면에서 사진 전체가 보이며,
전화 화면은 사진·결과·편집 도구 순서를 유지한다. 합성 원본은 실제 카메라 촬영이 아니다.

이번 결과로 다섯 기존 실패 항목을 해제한다. 목록 변경의 독립 검토와
`Safety-Review:` trailer를 남기며, main 병합 전 native landing의 FULL 검증은 별도로 필요하다.
FULL·main 병합·push·배포 성공을 이 집중 검증으로 주장하지 않는다.
실제 사람 라벨·모델 정확도·ARM64·DEVICE/FIELD·D-598 선행 실측 자료는 이번 범위에 없다.

| 파일 | SHA-256 |
|---|---|
| `verified-selection.json` | `45602467f8ddf4f731f669fd03975e052349538c76ae0c674da1b59c34c202a8` |
| `verified-runner.txt` | `18119f8bda7b0046a4d8962810bd0e2e8eb4676b8d58f6b69042b8c7eb8ab4ce` |
| `verified/run-1.txt` | `31266f189b3b11f67327f06b1b2fc4159c46451c284ae2332d4a706ef660f000` |
| `verified/run-2.txt` | `c77bc73b3dc773d61e307a2026c87c23138e863a19b9f687a43e1ef514cc1b14` |
| `layout-0e8ba72832/pixels-1280.png` | `c17f5350aae11f569e61a507c2189ef7853e474a8310c4ccdbab09f918d7a9f6` |
| `layout-0e8ba72832/pixels-1262.png` | `7f3305fed644c339d5e98fd59ca8894a7ad6a21e9773363488ae11573f09d75f` |
| `layout-0e8ba72832/pixels-390.png` | `0360668d7565aa9492e103330acbbf3a872b23657376e1d505ef2fb9f643fc45` |
| `layout-0e8ba72832/rects.json` | `7279abe1354ba6592ec1cd4827b1bbdac0c6d96f298d052affeff284d1205a73` |
