---
title: A host that changed role kept its old test-host entry and stopped the same landing twice
date: 2026-11-10
category: deployment
module: tools/remote/lab_hosts.py, private/lab-hosts.json, tools/land_async.py
problem_type: workflow_issue
component: development_workflow
severity: low
applies_when:
  - "a lab PC changes role (site/control/cell) or is renamed, and private/lab-hosts.json is edited"
  - "a landing stops with pytest exit 255 and a truncated run-*.txt on one specific host"
tags: [lab-hosts, test-hosts, host-roles, landing-stop, remote-pytest]
---

# A host that changed role kept its old test-host entry and stopped the same landing twice

## Context

2026-11-09에 robttt가 통합관제 site 호스트에서 OMX 셀 호스트(rosy-arm-cell, 4 cores)로
역할을 바꿀 때 `private/lab-hosts.json`의 `site_host`·`omx_hosts`는 고쳤지만 옛 강호스트
역할이던 `test_hosts`의 `robttt@100.82.51.8`은 그대로 남았다. 그 뒤 `fix/arm-cell-host-role`
착지가 두 번 "`pytest … exited 255`"로 멈췄다. 작은 시험 묶음은 그 호스트에서 통과했지만
큰 묶음(`test --ignore=test_platform_g1_timing.py`)은 출력 중간에 끊겼고(62바이트 로그),
remote_pytest의 "below pytest floor 6 cores/4 GB" 경고는 디스패치를 막지 않았다. 두 번 모두
"일시 실패"로 읽혀 재시도만 반복할 뻔했다. 같은 날 그 파일을 PowerShell `Set-Content
-Encoding utf8`로 고쳤다가 BOM이 붙어 `lab_hosts.load()`가 `JSONDecodeError`로 터져 착지
재개가 한 번 더 실패했다.

## Guidance

1. 호스트의 역할을 바꾸는 변경은 `private/lab-hosts.json`의 **모든 역할 키**를 함께 본다:
   `site_host`, `sim_hosts`, `omx_hosts`, `test_hosts`, `robots`. `deploy/hosts/README.md`의
   규칙("감시를 위해 제어 PC를 test_hosts나 sim_hosts에 추가하지 않는다")은 제어 PC가 된
   순간 기존 test_hosts 항목에도 적용된다. 2026-11-10 조치: `test_hosts`에서 제거(백업
   `.bak-20261110-r-consolidation`), 이후 같은 착지가 정상 진행.
2. 착지가 `pytest exited 255`로 멈추면 그 회차의 `run-*.txt` 크기부터 본다. 수십~수백 바이트
   로 끊겨 있으면 시험 실패가 아니라 전송·호스트 중단이고, 같은 호스트로 재시도하면 같은
   결과가 재현된다. "일시" 판정은 재현 확인 뒤에만 한다.
3. `private/lab-hosts.json`을 PowerShell로 고칠 때는 BOM 없는 UTF-8로 쓴다
   (`[System.IO.File]::WriteAllText` + `UTF8Encoding($false)`). `Set-Content -Encoding utf8`은
   BOM을 붙이고 `lab_hosts.load()`는 이를 거부한다.

## Evidence

- 착지 STOP 두 건과 끊긴 `run-gpre-3.txt`(62바이트), 같은 묶음의 `run-pre-2/4` 통과:
  `…/rosy-land-wt/land-fix-arm-cell-host-role-20261109145741.log`, prepare 로그.
- test_hosts 제거 뒤 같은 스냅샷 재개 성공(진행), BOM 오류 재현·해결:
  `Rosy/docs/workspace-records/2026-11-10/r-consolidation.md` 2단계.
