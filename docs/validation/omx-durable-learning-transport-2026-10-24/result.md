# 학습용 선택형 원격 실행의 연결 중단 검사

2026-10-24 KST 검사다. 원래 학습의 [중단 기록](../omx-fixed-budget-input-audit-2026-10-24/result.md)을 보존하며, 여기서는 학습·정책 품질을 검사하지 않는다.

## 변경과 범위

`remote_sim.py --durable`은 기존 native SIM/INNER를 detached supervisor 아래 실행한다. 기본 실행 방식·host placement·site 제외·소스 shipping·CPU/메모리/wall 제한은 유지한다. 선택 모드는 기존 `remote_job`의 SSH 호출·재연결·로그/종료 코드 해석을 재사용한다.

START를 직렬화하고 원격 submitted claim을 먼저 만든다. 응답이 끊기거나 PID 없이 claim만 남아도 새 작업으로 대체하지 않는다. 메타데이터에는 host/role·full source commit·명령/인수·자원 제한·실행기와 native body의 해시를 묶는다. supervisor PID의 starttime과 process group도 확인하므로 재사용된 PID로 취소하지 않는다.

연결 소실·종료 코드 없는 actor는 STOP/CLEANUP/DROP하지 않고 보존한다. 정상 terminal rc는 native body와 정리가 끝난 뒤 atomic rename으로 남긴다. 로컬 결과 회수에 성공한 뒤 기존 source/OUT을 정리하며, 별도 `.sim-job`의 rc/log/identity는 남는다. `follow`는 같은 메타데이터의 작업만 읽고 placement·ship·START를 하지 않는다. 각 관측자는 별도 로컬 로그를 사용한다.

## 원격 회귀 검사

실행 소스 commit `67b368605a`로 `test/test_remote_sim_job.py test/test_remote_sim.py test/test_remote_pytest.py`를 공식 remote pytest에서 실행했다. AI 역할 검사 PC에서 **98 PASS, 7.31초**, 실패·skip 없음이다. 외부 scratch의 `learning-execution-20261023/durable-transport-green3/run-1.txt`를 보존한다.

새 회귀 7개는 실제 짧은 detached Bash 검사와 모의 통합 경계 검사로 시작 응답 소실·단일 실행·완료 후 follow, 관측 연결 소실 시 보존, PID 재사용 시 취소 거부, claim만 남은 두 불완전 상태의 무대체, 통신 소실 뒤 native 정리 생략, child의 지연된 EXIT 정리 이후 terminal rc를 확인한다. 기존 실행기 회귀 91개도 함께 통과했다. 노트북에서 pytest나 ML을 실행하지 않았다.

첫 RED는 helper가 없어서 collection 오류였다. 첫 구현의 원격 1 FAIL·95 PASS에서 PID/starttime의 줄바꿈과 시작 경합을 찾았다. 다음 1 FAIL·96 PASS는 로그 부재와 종료 코드 부재를 혼동한 fixture였고, 두 경우 모두 작업을 보존하는 검증으로 구분했다. 앞선 실패를 통과로 바꾸어 기록하지 않는다.

## 실제 MODEL SSH 경로 검사

동일 commit의 native 실행 ID는 `sim-67b368605a-172b4f`다. MODEL 역할·8 CPU·6GiB·3분 제한으로 colcon/native 환경 아래 짧은 파일 기록 명령을 실행했다. 학습·Gazebo 동작·실물 명령은 없다.

성공한 첫 START 응답만 로컬 관측자에서 의도적으로 숨겼다. START RPC는 2회였지만 같은 ID였으며, 회수한 `launches.txt`에는 정확히 한 줄만 있었다. 완료 파일이 존재하고 runner는 실제 종료 0이었다. 외부 scratch의 `durable-native-model-smoke/verification.json`과 injection 관측을 보존한다.

native 정리 뒤 별도 `follow`로 동일 작업의 종료 0과 원래 로그 byte 전체를 다시 읽었다. 읽기 전용 서버 대조에서도 terminal journal이 남고 source/OUT·lock·예약은 없는 것을 확인했다. `terminal-retention.json`을 보존한다.

| 근거 | SHA-256 |
|---|---|
| 원래 `remote-run.json` | `sha256:7f3ae2aea91858aaf9bddc4246eeabb8f8e7353a4f3005fe0a05dc7b0900d73f` |
| native terminal log 및 정리 후 follow log | `sha256:a932d7d55641d83419921c360bbd418684e1071d137968b41f5cb68cfe7b3b52` |

## 수용 경계

이 결과는 연결 복구를 위한 실행 계약의 근거다. 원래 중단된 optimizer의 정확한 정지 주체·원격 exit code는 여전히 미확인이다. 원래 학습 study·claim·7개 동결 스크립트를 바꾸지 않았고 학습을 재제출하지 않았다. 향후 별도 학습 시도는 원래 실패를 유지하는 사전 binding과 독립 검토가 필요하다. 실제 모델 완료·reload·독립 정책 평가·HF 업로드·사람 라벨·실물 수용 근거로 해석하지 않는다.

CE: 해당 없음 — 이 실행 계약과 재발 방지는 코드·실제 회귀·위의 native 증거에 직접 남았다. 원래 중단의 상세 원인과 기존 물리 원인은 별도 미해결 상태다.
