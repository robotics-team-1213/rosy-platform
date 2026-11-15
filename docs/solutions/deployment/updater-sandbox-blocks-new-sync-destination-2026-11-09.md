---
title: "An updater unit older than the release sandbox-cannot-write a new sync destination, rolling the release back"
date: "2026-11-09"
category: deployment
module: deploy/robot/pinky_pro/native
problem_type: integration_issue
component: deployment
symptoms:
  - "updater last_result IMAGE_LAYER_SYNC_FAILED: [Errno 30] Read-only file system: '/etc/NetworkManager/conf.d/.60-rosy-wifi.conf.rosy-sync.tmp'"
  - "outcome rolled_back, the release withdrawn; the same release would fail on every flashed robot"
root_cause: missing_integration
resolution_type: code_fix
applies_when:
  - "adding a destination directory to the image-layer sync (ALLOWED_PREFIXES, OVERLAY_CONFIGS)"
  - "a payload canary rolls back with IMAGE_LAYER_SYNC_FAILED and an Errno 30 detail"
---

# 옛 unit 샌드박스에서 돈 첫 sync가 새 쓰기 경로에 EROFS로 롤백한 경우

## 증상

2026-11-09 11:54 UTC, 릴리스 2026.11.09-177(8dcdd033f)의 canary geg6가
`IMAGE_LAYER_SYNC_FAILED: [Errno 30] Read-only file system: '/etc/NetworkManager/conf.d/.60-rosy-wifi.conf.rosy-sync.tmp'`
로 롤백했고 CD가 177을 철회했다. bb40089f77(11-01)이 sync 대상에 더한
`etc/NetworkManager/conf.d/60-rosy-wifi.conf`가 원인이었다.

## 원인 (부트스트랩 딜레마)

`rosy-auto-update.service`는 `ProtectSystem=strict`에 필요한 경로만
`ReadWritePaths`로 연다. 동작 중인 기체의 updater는 **옛 unit 정의**의 샌드박스에서
**새 릴리스의** sync 스크립트를 실행한다. unit에 경로를 더하는 커밋은 다음 릴리스부터
적용되므로, 새 쓰기 경로를 처음 소개하는 릴리스는 영원히 옛 샌드박스 안에서 그 경로에
쓰다가 EROFS로 실패한다. 기존 회귀 시험과 `test_native_systemd_contract.py`의
`DECLARED_WRITES`는 이 경로를 선언조차 안 했고(대상 경로가 상수 조합으로 만들어져
리터럴 스캔에도 잡히지 않았다), unit과 plan을 대조하는 시험은 없었다.

## 수정과 검증

- unit: `ReadWritePaths`에 `-/etc/NetworkManager/conf.d` 추가(정상 경로).
- sync(`sync-image-layer.py` `apply()`): `kind == "config"`인 설치가 EROFS(errno 30)면
  실패 대신 그 파일만 "deferred"로 기록하고 진행한다. 매니페스트에서 해당 기록을 빼
  나중 reconcile·rollback이 건드리지 않게 하고, updater는 history에 `sync_deferred`를
  남긴다. plan은 다음 sync에서 같은 파일을 다시 "new"로 잡아 자연히 재시도한다.
  EROFS 외 오류(EACCES 등)와 다른 kind의 EROFS는 그대로 실패·롤백.
- 회귀 시험(`test_image_layer_sync.py`): EROFS 미룸→진행·매니페스트 제외·다음 실행
  설치, EACCES·runtime 경로 EROFS는 여전히 실패, 그리고 plan의 모든 대상
  디렉터리(ALLOWED_PREFIXES·boot·backup·lock)를 unit의 ReadWritePaths·StateDirectory와
  대조하는 시험. `DECLARED_WRITES`에도 NM 설정 경로를 선언했다.
- 시험은 변이 확인(unit에서 경로를 빼면 적색, 새 prefix를 더하면 적색)했다.

## 복구

기체 쪽 조작은 필요 없다. 수정이 든 새 릴리스(178)를 게시하면 된다. 미뤄진 wifi
설정은 **다음 sync가 도는 다음 릴리스 적용·롤백·operator push**에서 착지한다(유휴
tick에는 sync가 돌지 않으므로). NetworkManager는 어차피 다음 시작 때 읽는다.

## 다음에 적용할 조건

sync에 쓰기 대상 디렉터리를 더할 때는 같은 커밋에서 (1) unit `ReadWritePaths`,
(2) `DECLARED_WRITES`, (3) `test_every_plan_destination_is_writable_in_the_updater_unit`
대조가 함께 통과해야 한다. canary가 `IMAGE_LAYER_SYNC_FAILED: [Errno 30]`로 롤백하면
새 경로가 옛 unit 샌드박스에 없는지부터 본다.
