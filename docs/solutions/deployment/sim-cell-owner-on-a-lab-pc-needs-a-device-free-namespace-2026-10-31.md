---
title: 실험실 PC에서 시뮬 셀 소유자는 장치 없는 namespace와 짧은 소켓 경로로 띄운다
date: 2026-10-31
category: deployment
module: tools/sim/run_arm_transfer_sim.sh, tools/sim/without_devices.sh, deploy/robot/omx/run_cell_owner.py
modules: [tools, deploy]
problem_type: environment_constraint
component: simulation_bringup
severity: medium
symptoms:
  - "RuntimeError: the simulation cell owner refuses hardware device grants (AI PC에 /dev/video* 있음)"
  - "bwrap/unshare: setting up uid map: Permission denied (비특권 user namespace 차단)"
  - "RuntimeError: UDS parent directory must be provisioned by the service manager"
  - "OSError: AF_UNIX path too long (하네스 임시 폴더 아래 소켓)"
root_cause: environment_constraint
resolution_type: tooling
tags: [omx, simulation, lab-pc, namespace, uds, d-927]
applies_when:
  - "컨테이너 없이 실험실 PC에서 run_cell_owner.py를 띄울 때"
  - "시뮬 소유자 UDS 소켓을 깊은 작업 폴더 아래에 둘 때"
---

# 실험실 PC에서 시뮬 셀 소유자는 장치 없는 namespace와 짧은 소켓 경로로 띄운다

## Problem

`run_cell_owner.py`는 컨테이너 안을 전제로 `/dev/video*`·`/dev/serial/by-id`가 보이면 시작을 거부한다.
AI PC에는 카메라가 있어 D-927 C4 시뮬 소유자가 뜨지 않았다. 이어서 UDS 폴더·경로 길이 문제가 차례로 나왔다.

## Solution

- 가드는 그대로 둔다. 장치가 보이는 호스트에서는 `tools/sim/without_devices.sh`가 `sudo -n unshare --mount`로
  새 mount namespace를 만들고, `/dev`를 tmpfs로 덮어 null·zero·full·random·urandom·tty와 호스트 `/dev/shm`
  (DDS 공유 메모리)만 둔 뒤 `setpriv`로 호출 사용자로 내려 실행한다. 네트워크 namespace는 같아 loopback
  Fleet·DDS가 그대로 닿는다. 실험실 PC는 비특권 user namespace가 AppArmor로 막혀(`bwrap`·`unshare -r` 실패)
  비밀번호 없는 sudo를 쓴다. sudo가 `LD_*`·`PATH`를 지우므로 `export -p` 파일을 권한을 내린 뒤 다시 읽는다.
- 소켓 상위 폴더(`<root>/<instance>`)는 서비스 관리자 몫이라 스크립트가 `0750`으로 미리 만든다.
- AF_UNIX 경로는 108바이트에서 끊긴다. `SOCKETS`를 따로 받고 하네스는 `/tmp/rosy-uds-*`를 쓴다.

## Verification

AI PC `remote_sim.py cmd -- "CHECK=1 tools/sim/run_arm_transfer_sim.sh"`: 소유자 기동, live
`GetTransferCapability`로 Fleet `TransferInstallation` 완성, 물체 source 자세 0.03 mm, 그리퍼 OPEN, zone 비점유.
remote_sim scope 안에서 namespace 안팎 netns가 같고(`net:[4026531833]`) loopback HTTP 200을 확인했다.

## Prevention

소유자가 "Fleet fence stale"로 멈추면 먼저 Fleet가 이미 종료됐는지 본다. 이번에는 Fleet가 앞선 오류로 HOLD한
뒤 하네스가 Fleet를 내렸고, 소유자의 늦은 fence 읽기가 ConnectionRefused로 실패했다. 원인이 아니라 결과였다.
