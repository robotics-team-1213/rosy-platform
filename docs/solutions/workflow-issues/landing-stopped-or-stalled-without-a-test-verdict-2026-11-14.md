---
title: Landings stalled after green tests and stopped or were bisected when no test had failed
date: 2026-11-14
category: workflow-issues
module: tools/land_mainred.py, tools/land_async.py, tools/land_rollup.py, tools/remote/host_caps.py, tools/remote/host_probe.py, tools/remote/remote_pytest.py
problem_type: workflow_issue
component: development_workflow
severity: high
root_cause: logic_error
resolution_type: code_fix
symptoms:
  - "a landing's log stayed silent for over 30 min after its last pytest invocation passed"
  - "a 31-member rollup stopped after a 5969 s FULL on three 'exited 255' invocations and was split into halves"
  - "'[remote-pytest] ... not run: no working host has it' for learner_venv tests while both test PCs had the venv"
  - "the split log ended in a traceback: git rev-parse land/<member> exit 128"
  - "'[land-async] resuming cleared MAIN-RED stops skipped: No module named 'land_queue'' after six landings"
---

# 시험이 실패하지 않았는데 착지가 멈추거나 쪼개졌다

## 증상

2026-11-14 오전, 시험이 모두 통과한 착지가 30분 넘게 아무 줄도 찍지 않았다. 31개를 묶은
rollup은 99분 FULL 뒤 `exited 255` 세 건으로 멈췄고, 실패한 시험이 하나도 없는데 반으로
쪼개졌다. 쪼개는 과정은 구성원 브랜치가 없다는 traceback으로 죽었다.

## 원인

1. `land_mainred.close()`는 통과한 호출마다 `state()`를 읽고, `state()`는 close 기록마다
   `git merge-base --is-ancestor`를 한 번씩 불렀다. 한 번에 최대 372번, FULL 한 번에 68번
   반복했다(호출당 약 0.15~0.2초). 실제로 다른 쌍은 51개뿐이었다.
2. `remote_pytest.place()`는 여유가 있는 host만 `HEADROOM`에 넣고 능력(`caps`)도 거기에만
   두었다. 두 시험 PC가 모두 floor 아래여서 "닿는 host를 그냥 쓴다"로 갔을 때, 그 host들은
   능력이 없는 것으로 보여 `learner_venv` 시험이 exit 255 "not run"이 됐다.
3. 감독 프로세스는 STOP의 마지막 줄만 보고, `exited 255`를 재시도 대상으로도 쪼개지 않을
   대상으로도 알지 못했다. 그래서 판정이 없는 정지를 시험 실패처럼 이분했다.
4. `land_rollup.build`는 구성원의 스냅샷 브랜치가 이미 지워진 경우 `git rev-parse` 예외로
   죽어 나머지 구성원까지 버렸다.
5. 착지 뒤 "MAIN-RED가 풀린 정지를 다시 시작"하는 단계는 감독 사본이 로그 옆에서 돌고
   워크트리는 이미 지워진 뒤라 `land_queue`를 import하지 못해 매번 건너뛰었다.

## 해결

- `land_mainred._ancestor`를 `functools.lru_cache`로 감쌌다. 두 커밋의 조상 관계는 변하지 않는다.
- `host_probe.placed_hosts`가 닿은 host의 능력을 `host_caps.KNOWN`에 적고,
  `host_caps.room()`이 `HEADROOM`에 없는 host에 그 능력을 돌려준다. floor·배치 규칙은 그대로다.
- `land_async.lost_host()`: 마지막 STOP의 pytest 줄이 모두 `exited 255`이면 기존 자원 부족
  재시도(최대 3번, 5분 간격)로 `land.py`를 다시 돌린다. `land_cache`가 통과한 호출을 남기므로
  잃은 호출만 다시 돈다. 실제 실패가 섞여 있으면 재시도하지 않는다. `exited 255`로 끝난
  정지는 쪼개지 않는다(`NO_SPLIT`).
- `build`는 브랜치가 없으면 `.members`에 적힌 `candidate` 커밋으로 병합하고, 그것도 없으면
  그 구성원만 빼고 계속한다.
- 착지 뒤 재시작 단계 앞에서 main의 `tools/`를 `sys.path`에 넣는다.

## 검증

- 새 시험 4개: `test_land_mainred.py::test_state_asks_git_about_one_pair_of_commits_once`,
  `test_host_caps.py::test_a_fallback_host_below_the_floor_keeps_its_probed_capabilities`,
  `test_land_async.py`의 `exited 255` 두 행, `test_land_rollup.py::test_build_merges_a_member_whose_snapshot_branch_is_gone_from_its_recorded_commit`.
- 각 수정 파일을 main 것으로 되돌린 커밋에서 새 시험이 실패했고(조상 호출 3번, 능력 없음,
  재시도 1번, traceback), 수정본에서는 원격 147개와 101개가 통과했다.
- `land_queue` import 수정은 시험으로 덮지 않았다. 착지 뒤 로그에 "skipped: No module named"
  줄이 사라지는지로 확인한다.
- 착지 뒤 실제 FULL 시간이 얼마나 줄었는지는 아직 재지 않았다.

## 복구

기존 착지 경로로 이 변경을 되돌린다. 착지 도구는 main의 것으로 돌기 때문에 이 수정은
main에 들어간 뒤 시작한 착지부터 적용된다.

## 다음에 적용할 조건

- 시험이 끝났는데 착지 로그가 조용하면 시험 PC가 아니라 노트북의 `git.exe` 자식 프로세스
  수부터 본다.
- STOP 줄이 전부 `exited 255`이면 브랜치를 고치거나 쪼개지 말고 host 상태(닿는지, floor,
  `not run` 문구)를 본다.
- 남은 일: 재시도 3번 뒤에도 255로 끝난 rollup은 쪼개지 않고 멈춘 채 남는다. 구성원을
  되살리는 단계는 아직 없다.
