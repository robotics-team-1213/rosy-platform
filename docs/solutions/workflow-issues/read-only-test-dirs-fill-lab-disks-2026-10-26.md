---
title: 읽기 전용 시험 디렉터리가 시험 PC 디스크를 채운다
date: 2026-10-26
category: workflow-issues
module: tools/remote/remote_pytest.py, rosy-ops host maintenance
problem_type: workflow_issue
component: development_workflow
severity: high
root_cause: missing_tooling
resolution_type: tooling_addition
symptoms:
  - "AI PC 루트 디스크가 약 12시간 만에 100%(1.4 GB 남음), 모델 PC 89%"
  - "/tmp/pytest-of-<user>에 garbage-<uuid> 디렉터리 약 40개(개당 약 1.5 GB)"
  - "~/rosy-test/runs에 고아 run 디렉터리 149개(모델 PC, 22 GB)·157개(AI PC, 34 GB)"
  - "수동 정리 뒤 몇 분 만에 garbage-*가 다시 생김"
applies_when:
  - "시험 PC의 디스크가 빠르게 차거나 원격 시험이 이유 없이 MAIN-RED·NEW로 보일 때"
  - "rm -rf나 git worktree remove가 시험 산출물을 지우지 못할 때"
  - "제품 시험이 읽기 전용 디렉터리를 만드는 것을 '고치려' 할 때"
tags: [test-hosts, disk, pytest-basetemp, read-only, remote-tests, host-maintenance]
---

# 읽기 전용 시험 디렉터리가 시험 PC 디스크를 채운다

## 증상

2026-10-26 시험 PC 두 대에서 측정했다. AI PC 루트 디스크는 약 12시간 만에 100%(1.4 GB 남음)가 됐고 모델 PC는 89%였다. 디스크를 채운 것은 전부 우리 시험 도구의 산출물이었다.

## 원인

1. **pytest garbage 디렉터리.** `/tmp/pytest-of-<user>`에 `garbage-<uuid>` 디렉터리가 약 40개(개당 약 1.5 GB, pytest 세션마다 하나) 있었다. pytest는 오래된 basetemp를 `garbage-*`로 이름을 바꾼 뒤 지우려 하는데, 제품 시험이 일부러 읽기 전용 디렉터리(release store, rollback, data-generations)를 만들기 때문에 지우지 못한다. garbage 디렉터리 하나에 쓰기 불가 디렉터리가 266개 있었다.
2. **고아 run 디렉터리.** `~/rosy-test/runs`에 모델 PC 149개(22 GB), AI PC 157개(34 GB)가 남았다. runner가 `<name>.jobs`는 지웠지만 읽기 전용 내용이 든 run 디렉터리의 `rm -rf`·`git worktree remove`가 실패해, 어떤 정리 규칙에도 걸리지 않는 디렉터리가 남았다.
3. **호스트 선택이 디스크를 보지 않음.** 원격 호스트 선택은 코어 수와 메모리만 봤으므로 디스크가 찬 호스트로 계속 작업을 보냈다.

**읽기 전용 디렉터리를 만드는 시험을 고치지 않는다.** 읽기 전용 release는 제품 동작이다. 지우는 쪽이 권한을 먼저 돌려놓아야 한다.

## 해결

- rosy-platform `fix/test-host-disk-2`: pytest `--basetemp`를 run의 job 디렉터리 아래로 두고, run·job을 지우기 전마다 chmod하고, 끝난 run은 2시간 뒤 치우고, 남은 공간이 20 GB 미만인 호스트는 호스트 탐색이 거절한다. 퍼센트 기준은 버렸다. 440 GB 디스크의 90%여도 44 GB가 남기 때문이다.
- rosy-ops `ops/daily-host-maintenance`(커밋 9f907ab, e24736e, 5f88c77): PC가 05:00에 재부팅된 직후인 05:30과 6시간마다 정비를 돈다. `garbage-*`와 오래된 `pytest-N`, `~/rosy-jobs`의 죽은 잠금·만료된 예약·깨진 링크, 끝난 run과 고아 run을 chmod 후 지운다. `~/rosy-test` 최상위의 모르는 항목과 7일 넘은 native-omx는 지우지 않고 보고만 한다. `~/rosy-jobs/disk-low`와 `maintenance/last-report.json`을 쓴다. 2026-10-26 약 02:00 KST에 모델 PC와 AI PC에 배포했고 백업은 `~/rosy-test/maintenance/bak-20261026`에 있다.
- 첫 실제 적용은 AI PC에서 `FileNotFoundError`로 실패했다. pytest가 같은 garbage 디렉터리 일부를 동시에 지웠기 때문이다. 5f88c77에서 고쳤고, 이 경합을 재현하는 self-test를 넣었다(뮤테이션으로 시험이 잡는 것을 확인).

## 확인 근거

- 수동 회수(chmod -R u+rwX 후 rm) 뒤 AI PC 81%(89 GB 남음), 모델 PC 82%(81 GB 남음).
- 수정 전에는 회수 몇 분 뒤 새 `garbage-*`가 다시 생겼다. 원인 1이 계속 작동한다는 증거다.
- 이 기록은 시험 PC에서 잰 값이며, 정비 작업의 장기 운영 결과는 아직 관측 중이다.

## 복구

호스트에서 직접 회수할 때는 권한을 먼저 돌려놓는다. 다른 세션의 pytest가 같은 디렉터리를 지우는 중일 수 있으므로 사라진 파일 오류는 무시한다.

```bash
df -h /
du -sh /tmp/pytest-of-$USER ~/rosy-test/runs 2>/dev/null
# pytest garbage: chmod first, then remove
for d in /tmp/pytest-of-$USER/garbage-*; do chmod -R u+rwX "$d" 2>/dev/null; rm -rf "$d"; done
# orphan run dir (no matching <name>.jobs and no live job)
chmod -R u+rwX ~/rosy-test/runs/<name> && rm -rf ~/rosy-test/runs/<name>
```

진행 중인 run은 지우지 않는다. 정비 작업이 배포된 호스트에서는 `~/rosy-test/maintenance/last-report.json`과 `~/rosy-jobs/disk-low`를 먼저 본다.

## 다음에 적용할 조건

- 시험 산출물을 지우는 코드는 읽기 전용 하위 디렉터리를 전제로 chmod 후 지운다. 지우기 실패를 무시하고 상위 기록(`.jobs`)만 지우면 고아가 생긴다.
- 호스트 여유 판단은 남은 절대 용량으로 한다.
- 공용 `/tmp` basetemp에 기대지 않고 run 소유 경로 아래에 basetemp를 둔다.

## 같은 날 관측: g1 타이밍 실패는 디스크 공간 때문이 아니다

`test/test_platform_g1_timing.py`는 AI PC에서 정리 뒤(87 GB 남음)에도 첫 시도 3/3 실패했고(contact gap p99 5.73 s, 4.71 s, HOLD 시간 초과 1회), 모델 PC는 2/2 통과했다. 시험 부하도 남은 공간도 원인이 아니었다. AI PC의 `/proc/pressure/io` full avg10은 57%까지 올랐다. AI PC에서 ROSY가 아닌 사용자 서비스(다른 프로젝트의 SQLite WAL을 쓰는 백엔드)가 계속 약 1.8 MB/s(19시간에 120 GB)를 쓴다. 이 시험의 barrier journal은 호출마다 새 SQLite 연결을 열고 기본 동기화(synchronous FULL)로 쓴다(`middleware/devices/omx/agent/src/rosy_agent/barrier_journal.py`의 `_connect`). 바쁜 호스트 판별은 CPU 깨어남 지연만 재므로(`test/test_platform_g1_timing.py`의 `scheduling_jitter_s`·`assert_timing`) 디스크 경합은 skip이 아니라 실패가 된다. 그 서비스가 경합 원인일 가능성이 높지만, 서비스를 멈춰 확인하지 않았으므로 **증명되지 않았다.** 격리 사유는 `test/flaky_quarantine.txt`에 있다.
