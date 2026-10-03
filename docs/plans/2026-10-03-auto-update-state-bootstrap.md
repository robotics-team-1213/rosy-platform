# 자동 업데이트 상태 디렉터리 bootstrap Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 구 이미지의 로봇도 payload 자동 업데이트 중 필요한 상태 디렉터리를 서비스 재시작 전에 확보한다.

**Architecture:** 서명 검증된 `tmpfiles-rosy-state.conf`에서 maps/models/pilot-recordings의 정확한 `d` 규칙만 선택한다. 기존 updater의 읽기 전용 mount namespace 밖에서 PID 1이 제한된 transient root oneshot을 실행한다. 재귀 소유권 변경, 장치 설정 변경과 녹화 삭제는 수행하지 않는다.

**Tech Stack:** Python stdlib, systemd-run, systemd-tmpfiles, host pytest.

## 실행 순서

1. `test/test_image_layer_sync.py`에 누락 디렉터리, 변경 없는 재시도, dry-run, 규칙 거부, symlink 거부, rollback 데이터 보존 시험을 추가한다.
2. `deploy/robot/pinky_pro/native/sync-image-layer.py`에서 지정된 mode/user/group을 검증하고 root 전용 설정을 기존 backup 위치에 원자적으로 저장한다.
3. transient oneshot을 reload/enable보다 먼저 실행한다. 권한은 CHOWN/FOWNER/FSETID/DAC_OVERRIDE로 제한한다. `CAP_FSETID`는 2750의 setgid 보존에 필요하다.
4. 종료 코드뿐 아니라 실제 디렉터리의 종류·권한·소유자를 검사한다. 실패는 기존 pending journal에 남기고 다음 sync에서 다시 계산한다. rollback에서는 디렉터리와 녹화를 보존한다.
5. `python -B -m pytest test/test_image_layer_sync.py test/test_native_systemd_contract.py test/test_rosy_auto_update.py -q`로 확인한다. provisioning 제거 mutation은 기존 실패 증상을 재현해야 한다.
6. parent coordinator가 CI/ARM64 payload 발행 후 두 장치의 자동 commit과 실제 서비스 상태를 별도로 검증한다. host 시험은 장치 수락 근거로 대체하지 않는다.

## 확인된 제약

- 기존 updater unit만 교체해도 실행 중인 구 namespace의 쓰기 범위는 늘어나지 않는다. PID 1을 통한 transient 실행이 bootstrap 경로다.
- 전체 tmpfiles 설정에는 `z`/`Z` migrations가 있으므로 전체 파일을 실행하지 않는다. 정확한 세 디렉터리의 비재귀 `d` 규칙만 실행한다.
- 실제 장치의 독립 probe에서 CAP_FSETID가 없으면 tmpfiles는 성공을 반환하면서 0750을 남겼고, 추가하면 2750과 지정 소유자를 유지했다. 전체 worker 속성의 nested namespace probe도 통과했다.
