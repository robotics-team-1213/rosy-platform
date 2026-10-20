# 웹·CLI 공통 Isaac 실행 검증 — 부분 수용

검증일은 2026-10-21(KST)이다. D-834 Proposed의 공통 실행·기록 경계를 검증했다. 실제 OMX-F 구조 검사 보고서와 웹↔CLI 교차 조회·중복 방지·GPU 점유 거절을 확인했다. **GPU가 비어 있는 조건의 최종 SUCCEEDED·실제 중지 완료 수용은 아직 확인하지 못했다.** 기존 서비스 rollout·실물 장치·컨테이너 집기·팔레타이징·학습 수용은 이 기록의 범위 밖이다.

## 소스와 시험

| 소스 SHA | 범위 | 관측 |
|---|---|---|
| `f6820a6c32` | 불변 run 기록·실제 프로세스 중단 복구 | 원격431 PASS/1 SKIP. xacro overlay 미설치 skip |
| `688c33120e` | 실행 코어 검토 수정·CLI 1차 통합 | 원격466 PASS/1 SKIP |
| `73b8c20fdf` | CLI fetch 지문·영속 게시 검토 수정 | 원격11 PASS |
| `5d95ffae27` | 웹·권한·공통 셸·서명 source 누락 거절·브라우저 | 명시적 Chromium 포함322 PASS |
| `9dbaca197b0adeb2cd461c1565f71412288af1e5` | 전체 binding 지문을 controller/worker까지 전달 | 명시적 Chromium 포함477 PASS/1 SKIP |
| `c47e8454e3e64fef5f378ba40d50fb9f89ec5791` | UNKNOWN 진단 전달·user bus·준비 거절 응답 | 명시적 Chromium 포함479 PASS/1 SKIP |

시험은 개발 노트북에서 실행하지 않았다. `tools/remote/remote_pytest.py`로 커밋된 SHA를 전송했다. 실제 SDK 실행과 host pytest를 구분한다. 원격 로그는 저장소 밖 `rosy-sim-task2-review-green`, `rosy-sim-task3-cli-final`, `rosy-sim-task3-cli-review-green`, `rosy-sim-task4-final`, `rosy-sim-task4-review-green`, `rosy-sim-task5-final`의 `remote/run-1.txt`에 보존했다. 마지막 행 이후의 수정·최종 병합 SHA 검증은 별도 landing 기록을 따른다.

## 실제 모델 PC와 SDK 관측

기존 NVIDIA GeForce RTX 5080 Laptop GPU와 Isaac Sim `5.1.0.0`, Python `3.11.17`을 사용했다. 패키지를 설치하지 않았다. 같은 계정의 model-code root·work.lock·gpu.lock과 SDK interpreter 지문을 확인했다. 기존 interpreter target의0775 권한 때문에 첫 check가 거절되어, 계정 home 아래 본인 소유 regular file의 그룹/기타 쓰기만 제거해0755로 맞췄다. 변경 전후 파일 SHA-256은 같고 owner write·execute/read는 유지됐다. 이 interpreter를 공유하는 기존 venv에도 권한 변경이 적용된다.

실제 계정·주소·경로는 private 설정에 둔다. 운영 SDK 설정은0600으로 새로 만들었고 source SHA별 binding을 exclusive 게시했다. 기존 검수 서비스 설정과 사람 라벨은 수정하지 않았다.

| run ID | 실제 소스 | 결과와 한계 |
|---|---|---|
| `3bc987eb28165351b9e7f163ebc5d76e` | `9dbaca197b` | CLI start. OMX-F·120프레임·한 articulation·예상 관절 집합을 포함한10 joints 보고서 생성. unit exit2, cleanup/GPU 해제 미확정으로 UNKNOWN 유지 |
| `80e42a2fa5d35c8698d090ecd5450f3a` | `9dbaca197b` | 격리된 웹 fixture의 새 start. adapter가 user bus 환경을 넘기지 못해 unit 시작 응답 미확정·UNKNOWN. 해당 run을 재시작하지 않고 원본 보존 |
| `4ff0182c7bee573a89a7c181fe741408` | `c47e8454e3` | user bus 수정 후 웹 start→CLI 조회. 외부 GPU 점유로 최종 FAILED, `reason=admission_refused`, `cleanup=SDK_NOT_STARTED`, `task_success=null`. fetch FINAL snapshot 검증 |

첫 run의 실제 JSON 보고서를 `import_report.verify_report`로 독립 재검증했다. `completed_frames=120`, `import_verified=true`, articulation1개, joints10개, SDK `5.1.0.0`, `task_success=null`, seed 미사용·영상 없음 사유가 일치했다. 보고서 SHA-256은 `6f68c1f185ee549607a85cc200153ac5b8f80ad45ad55456c230183f34d41f31`이다. **이 보고서는 모델 구조 검사 증거이며 run 최종 성공 receipt가 아니다.**

SDK 전후 관찰에서 외부 same-account `llama-server` compute PID가 확인됐고 해당 PID는 이 실험의 cgroup에 속하지 않았다. 종료하지 않았다. 첫 worker의 cleanup 각 부울과 child exit code가 UNKNOWN 상태에 별도로 저장되지 않아, 원인을 외부 점유 하나로만 확정하지 않는다. 후속 check는 `ready=false`와 입력 지문을 보존했고 새 worker는 SDK 시작 전에 admission을 거절했다. 원시 SDK 로그에는 world visual reference 경고와 종료 중 비동기 `get_stage_state` AttributeError도 있었다. 이 시험으로 영상 품질·mesh 렌더 정확도를 수용하지 않는다.

## 웹·CLI 교차 검증

기존 검수 서비스의 Python 환경으로 **새로운 빈 검수 state**와 loopback 임시 HTTP 서버를 사용했다. 프로젝트 인증·view/manage·CSRF 경로를 거치는 격리된 계정 fixture이며 실제 Account 서비스 로그인이나 production rollout을 증명하지 않는다. source·workspace·전체 binding 지문은 실제 `LocalRuns` 경계에서 검사했다.

- CLI가 만든 첫 run을 HTTP 목록·상세에서 조회했고 raw runtime·private home 경로가 응답에서 제외됐다.
- 같은 요청을 웹에서 재전송해 같은 run을 받았다. 기존 UNKNOWN을 자동 재시작하지 않았다.
- 수정 source의 웹에서 새 parent-linked run을 만들고 CLI status/start 재전송으로 같은 최종 FAILED를 확인했다. SDK 시작 전 GPU 거절 기록이 양쪽에서 보존됐다.
- 실제 CLI parser의 `status`, 동일 요청 `start`, `fetch`가 모두 exit0으로 끝났다. status의 exit0은 과제 성공이 아니라 조회 성공이다. UNKNOWN과 FAILED를 그대로 반환했다.
- fetch는 매번 새 snapshot을 만들고 입력 지문·산출물 경계를 확인했다. UNKNOWN은 `OBSERVATION_NOT_ATOMIC`, 최종 admission 거절은 `FINAL`이다. SDK 원시 로그·USD·미확정 import 보고서를 웹 산출물로 우회 공개하지 않았다.

개발 PC의 private 원본 묶음은 저장소 밖 `rosy-sim-task5-live`에 있다. `sdk-evidence.json`, `receipt.json`, `web-receipt*.json`, `request*.json`, `web-probe*.json`, `cli-summary.json`과 새 `snapshots/`를 보존했다. SDK 원본은 모델 PC의 해당 불변 run 디렉터리에 남았다. 외부 공개용 원시 로그가 아니므로 Git에 넣지 않았다.

## 다음 수용 조건

외부 GPU 작업 종료에 관한 사용자 결정을 기다린다. 기존 작업을 임의 종료하거나 이번 UNKNOWN을 성공으로 바꾸지 않는다. GPU가 비면 **새 request/run**으로 전체 import·소유 프로세스/GPU 해제·최종 manifest를 검증하고, 별도 새 run의 실제 stop을 확인한다. 새 결과는 이 기록을 고치지 않고 다음 dated evidence에 추가한다. D-826 E0·혼합 적층·회수·양팔 복구는 별도 선행 검증을 통과한 뒤 활성화한다.
