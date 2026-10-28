---
title: Windows에서 새 SSH 키도 소유자 전용 ACL을 별도로 확인한다
date: 2026-10-28
module: tools/ssh/rosy_ssh_enroll.py, tools/release/os_tools_vm.py
problem_type: workflow_issue
component: development_workflow
severity: high
symptoms:
  - "새 운영자 전용 SSH 개인키의 소유자는 맞지만 owner-only 검사가 거절했다."
  - "PowerShell Set-Acl 복구가 SeSecurityPrivilege 오류로 실패했다."
root_cause: incomplete_setup
resolution_type: environment_setup
applies_when:
  - "Windows에서 새 SSH 키를 생성한 뒤 기존 owner-only ACL 검사를 통과시켜야 할 때"
tags: [windows, openssh, acl, operator-key, provisioning]
---

# Windows에서 새 SSH 키도 소유자 전용 ACL을 별도로 확인한다

## 증상과 원인

기본 운영자 전용 키가 없는 Windows 환경에서 기존 `tools/ssh/rosy_ssh_enroll.py`의
`generate_key`로 새 키 쌍을 만들었다. 기존 개인용 키는 재사용하지 않았다.
생성 직후 소유자는 현재 사용자였지만 다른 주체에 대한 Allow 규칙이 두 개 남아,
`tools/release/os_tools_vm.py`의 `_windows_private` 검사가 거절했다.

`generate_key`는 Windows DACL을 정규화하지 않는다. `_windows_private`는 현재 사용자 소유인지와
비소유자 Allow 규칙이 없는지를 별도로 검사한다. 생성 성공이나 소유자 일치만으로 이 검사를 대신할 수 없다.
PowerShell `Set-Acl`을 이용한 두 복구 방식은 이 환경에서 `SeSecurityPrivilege` 오류로 실패했다.

## 확인된 복구

이번에 새로 만든 운영자 전용 개인키 하나에만 Windows 기본 `icacls`를 적용했다.
상속을 제거하는 `/inheritance:r`와 남은 비소유자 Allow 규칙 제거로 DACL을 복구했다.
개인키를 다시 생성하거나 기존 키를 덮어쓰지 않았다.
그 뒤 기존 `_windows_private` 검사와 개인키에서 유도한 공개키의 쌍 일치 검사를 모두 통과했다.

같은 증상이면 먼저 대상이 이번 작업에서 생성한 전용 키인지와 현재 ACL을 확인한다.
그 대상에 한정해 복구하고 기존 두 검사를 다시 실행한다. 기존 개인용 키나 상위 SSH 폴더 전체에
권한 변경을 확대하지 않는다. `icacls`도 실패하거나 검사가 계속 거절하면 그 지점에서 중단하고 원인을 확인한다.

## 검증 근거와 적용 범위

증거는 작업 공간의 `Rosy/artifacts/receipts/2026-10-27-full-os-integration/operator-ssh-readiness.json`이다.
전용 키 최초 부재, 기존 키 미사용·미덮어쓰기, 비소유자 Allow 두 개, `Set-Acl` 실패와 `icacls` 복구,
최종 ACL 검사 및 공개키 쌍 검사 통과를 기록한다. 카드 개인화에는 공개키만 전달한다.
이 증거는 로컬 운영자 키 준비 확인이며 매체 기록, 장치 부팅, SSH 접속 또는 OTA 수용 증거가 아니다.
