# 웹·CLI 공통 Isaac 실행 — 무점유 종료·실제 중지 검증

2026-10-21(KST), [앞선 부분 수용 기록](../isaac-shared-runs-2026-10-21/result.md) 이후 외부 GPU 점유가 자연 해제되어 새 request/run으로 검증했다. 외부 프로세스를 종료하지 않았고 기존 UNKNOWN·FAILED 기록을 변경하지 않았다.

실제 실행 소스는 `8aa57b3d0e1d90afc07f524ec970ac8494d56485`다. source/browser 시험 SHA `1ec6d389b66f9b2b7ac23976e1ac092d7d08c721` 이후 제품 코드는 같고 문서·로그만 추가된 커밋이다. 해당 원격 시험은 명시적 `ROSY_RUN_BROWSER_TESTS=1`로379 PASS/1 SKIP(xacro)이며 `rosy-sim-task5-readiness-green/remote/run-1.txt`에 보존했다. 이 기록 이후 최종 병합 검증은 landing receipt를 따른다.

## 실제 SDK 성공

| 항목 | 관측 |
|---|---|
| run ID | `981e96c0bd105e38bf8b1923159ad614` |
| parent run | `3bc987eb28165351b9e7f163ebc5d76e` — 앞선 UNKNOWN 보존 |
| 최종 상태 | `SUCCEEDED`, snapshot `FINAL` |
| SDK·모델 | 기존 Isaac Sim `5.1.0.0`, OMX-F, headless |
| 검사 |120프레임, articulation1개, 예상 관절 집합을 포함한 joints10개 |
| 종료 | SDK child exit0, `OWNED_PROCESSES_EXITED_GPU_RELEASED` |
| 입력 지문 | `13a4b99c0936a67f86f5f558f20623975d5d11582440472bd2d9e142017e0cb4` |
| 결과 지문 | `c5fc381040d7fe01db79f29160d9fe3f00e094ce51083baa6c172a6cf9abdb0b` |
| manifest 지문 | `ce18605f61ad661bd3bbddae113f1cc43b2888c454c611b845fe5670412b5732` |
| 보고서 지문 | `6f68c1f185ee549607a85cc200153ac5b8f80ad45ad55456c230183f34d41f31` |
| 과제 성공 | `task_success=null` — 모델 검사이며 물리 집기 판정 없음 |

CLI check가 GPU 준비를 확인한 뒤 새 request를 receipt에 먼저 보존하고 start했다. 최종 status와 fetch가 동일 입력·결과·manifest 지문을 대조했다. 다운로드한 실제 JSON의 프레임·관절·articulation 수와 SHA-256을 다시 계산했다. 기본 import의 seed 미사용·영상 없음 사유도 유지됐다.

## 웹 시작·CLI 중지와 최종 회수

같은 source·실제 run root를 사용하는 새 빈 검수 state와 loopback HTTP 계정 fixture에서 위 SUCCEEDED run을 조회했다. 웹의 같은 start 요청 재전송은 같은 run을 반환했으며 새 SDK를 시작하지 않았다. raw runtime·private 경로가 공개 DTO에서 제외됨도 다시 확인했다.

웹에서 별도 요청을 만들어 run `83ef940c7e0d553cade26575bc72dffd`를 시작했다. parent는 위 SUCCEEDED run이며 원본은 그대로 남았다. RUNNING 확인 뒤 CLI가 사용하는 `observe(..., stop=True)` 경로에서 현재 revision·unit·InvocationID·boot·cgroup·PID 시작 시각과 pidfd를 검사해 소유 worker에 중지를 요청했다.

- 응답은 먼저 `STOP_REQUESTED`였고 최종 상태는 `STOPPED`였다.
- 종료 사유는 `stop_requested`, SDK child exit는 `-15`였다.
- `cleanup=OWNED_PROCESSES_EXITED_GPU_RELEASED`, `task_success=null`이었다.
- 최종 fetch는 `FINAL` snapshot을 새 디렉터리에 만들고 입력 지문·산출물 경계를 검증했다.

private 원본은 앞선 기록과 같은 저장소 밖 `rosy-sim-task5-live`에 있다. `clear-gpu-{check,request,receipt,start,latest}.json`, `success-{final,proof}.json`, `web-probe-8aa57b3d0e1d.json`, `web-receipt-8aa57b3d0e1d.json`, `actual-stop-{request,final}.json`과 새 `snapshots/`를 보존했다. 모델 PC의 원본 run과 실제 SDK 로그도 유지했다.

## 수용 범위

이 증거는 제한된 모델 import의 정상 종료·실제 소유 실행 중지·자원 회수와 웹↔CLI 공통 기록의 수용이다. 기존 실패·UNKNOWN을 성공으로 덮어쓰지 않았다. 단일 성공 스모크이며 반복 성능·물리 정확도·컨테이너 집기·3×3×3 적층·양팔 복구·학습 데이터 수용·정책 승격·실물 장치·field acceptance를 증명하지 않는다. 기존 production 검수 서비스·실제 Account 로그인은 rollout하지 않았다. D-834는 Proposed이며 D-826의 물리 단계는 계속 비활성이다.
