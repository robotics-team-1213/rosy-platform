# 착지 순서의 미완료 원격 시험 제한 시간

## 범위

착지 turn의 600초 제한을 시험 완료 callback과 독립적으로 적용한다. 준비 라운드는 제한하지 않는다.
취소된 실행은 기존 Overtime 경로를 통해 순서 밖 준비 단계로 넘기고 통과 cache에 넣지 않는다.
원격 연결을 잃은 작업을 관측 없이 종료하거나, 실물 장치·운영 서비스를 바꾸는 동작은 추가하지 않았다.

## 원인과 관측

읽기 전용 py-spy stack에서 MainThread는 `remote_pytest.run`의 futures를 기다리고 host worker는
`remote_job.run`의 poll sleep에 있었다. 낮은 로컬 CPU와 자식 프로세스 부재는 원격 작업의 중단 증거가 아니다.
기존 10분 검사는 `on_done`에만 있어 미완료 invocation을 중단시키지 못했고, failed-first 묶음 이후
다음 묶음이 예산을 새로 시작할 수도 있었다.

## 커밋별 공식 원격 시험

| revision | 범위 | 결과 |
|---|---|---|
| `b6e38c98bf` | 최초 단일/복수 host deadline 반례 | 2 failed, 완료되지 않은 작업의 취소 이벤트가 설정되지 않음 |
| `2adf742e62` | 실행 함수 분리 뒤 기존 land/queue/remote/memory 4파일 | 227 passed |
| `31f10d74e8` | 단일/복수 host × failed-first 묶음 유무 | 4 failed, 모두 deadline assertion 실패 |
| `2d8245514f` | 초기 수정의 같은 5파일 | 231 passed; 파일 크기 제한을 넘어 착지 후보에서 제외 |
| `dbf5635803` | 크기 분리 후 첫 구현의 같은 5파일 | 231 passed |
| `142e6afe88` | 단독 재시험/main 비교 중 만료 × 단일/복수 host | 4 failed, 진단 실행에 공통 stop event가 전달되지 않음 |
| `d9c54c4f7a` | 진단 수정 뒤 land/prepare/main-red/browser/record/remote 15파일 | 324 passed |

테스트 명령은 공식 `tools/remote/remote_pytest.py --sha <revision>`으로 실행했다.
각 작업 직전에 기존 qualified-labs wrapper가 model/AI host의 디스크 조건을 확인했다.
원본 로그는 개발 PC 시스템 TEMP의
`rosy-land-turn-deadline/{red,extraction,red-budget,green,green-final,red-diagnostics,green-diagnostics}/run-1.txt`다.
중복 `-q`로 수량 요약이 없었던 별도 baseline은 위 수량에 합산하지 않는다.

회귀는 실제 `land.run_tests` → remote runner → shared Work → host worker 경로를 실행하고,
외부 SSH와 긴 시계만 제어한다. 시험이 끝나지 않은 채 601초가 되는 상황, queued 작업 미시작,
완료된 첫 묶음만 cache에 남는 상황을 검증한다. 추가 회귀는 실패 판정 callback이 중첩 원격 진단을 시작한 뒤
deadline이 지나도 같은 event가 실행을 취소하고 main 비교를 추가로 시작하지 않는지 확인한다.
정상 deadline 취소는 broken-callback 경고로 바꾸지 않는다.
준비 단계 무제한·첫 실패 취소·기존 remote job 종료 경로는
기존 suite와 함께 확인했다. 긴 실시간 순서 점유를 인위적으로 재현하거나 실물 시험을 수행한 결과가 아니다.

## 구조와 남은 검증

`run_tests`는 기존 `land_checks`로 옮기고 public wrapper를 유지했다. 취소 결과 정리는 기존 Work queue로
옮겨 remote runner의 public alias를 유지했다. 최종 후보의 모든 커밋에 대한 size-range 검사는 exit0이다.
분리된 함수는 controller 한정 이름을 되돌린 AST가 원본과 같은지도 확인했다.

독립 읽기 전용 검토에서 진단 재시험이 deadline을 벗어날 수 있는 P1을 발견해 별도 RED로 재현했다.
공통 이벤트와 취소 제어 흐름을 연결한 뒤 재검토에서는 추가 중요 발견이 없었다.

이 문서는 집중 회귀 증거를 기록한다. 필수 FULL·최종 착지·공개 CI·실행 중인 구버전 프로세스 갱신은
각각 별도 단계이며 이 324건으로 완료했다고 주장하지 않는다.

CE: 기존 실행기 관측 교훈 갱신 — 자식·CPU 관측만으로 정체를 단정하지 않고 stack과 원격 진행을 확인한다.
