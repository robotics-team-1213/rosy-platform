---
title: "An OS update poll started I/O and stopped healthy SLAM before returning no-update"
date: "2026-11-05"
category: deployment
module: deploy/robot/pinky_pro/native
problem_type: integration_issue
component: deployment
symptoms:
  - "rosy-navigation.service stops while all Nav2 nodes were active and no goal was sent"
  - "rosy-os-update.service reports no-update after rosy-io.service starts"
root_cause: config_error
resolution_type: code_fix
applies_when:
  - "a frozen OS update timer runs beside an approved native SLAM runtime"
  - "a harmless polling result is mistaken for a harmless systemd start transaction"
---

# 업데이트 점검이 항법을 정지시킨 경우

## 증상과 확인 근거

2026-11-05 현장 담당 에이전트가 보존한 journal에서 14:24:39 UTC에 일반 I/O 시작과
항법 정지, 14:24:40에 OS 업데이트 시작, 14:24:42에 `no-update`를 확인했다.
G4 원시 자료를 봉인하고 Nav2 노드 활성화·실제 점유 지도·필수 readiness를 확인한
상태였다. 실행 중인 OS 업데이트가 없음을 확인하고 **타이머만 임시 정지**한 뒤에는
항법과 최신 지도를 유지했고 CORE는 `required=true, ready=true`를 보고했다.
처음 의심했던 CORE 재시작 순서 문제를 이 장애의 확정 원인으로 기록하지 않는다.

## 원인

[OS 업데이트 unit](../../../deploy/robot/pinky_pro/native/rosy-os-update.service)의
기존 `Wants=`가 `rosy-io.service`를 시작했다. I/O와 항법 unit은 서로 `Conflicts=`이므로
이미 정상 실행 중인 항법이 중지됐다. 이 의존성 처리는 Python 제어기의 점검 결과보다
먼저 일어난다. 따라서 [feed](../../../deploy/robot/pinky_pro/native/os_update_feed.py)가
서비스 명령 없이 `no-update`를 반환한다는 시험만으로는 발견할 수 없었다.

`After=rosy-io.service`는 시작 순서만 지정하므로 남겨도 I/O를 시작하지 않는다.
반면 `Wants=`를 `Requires=`로 바꾸거나 상위 `rosy-runtime.target`을 시작하게 하면
같은 충돌을 되살린다.

## 수정과 검증 범위

후보 소스는 `Wants=`에서 일반 I/O만 제거한다. OS storage·motion guard·release recovery·
CORE 의존성, I/O와의 순서, 독립 trial deadline은 유지한다.
[제어기](../../../deploy/robot/pinky_pro/native/os_update_controller.py)의 claim, 서명,
read-only source health, pending 기록, `reconcile`·정지·RAUC admission·trial 건강 검사를
변경하지 않았다. 항법이 실행 중이고 I/O가 꺼져 있으면 실제 새 업데이트도 source health에서
보수적으로 연기된다. **항법 중 자동 설치까지 성공하게 만든 수정은 아니다.**

아래 SHA는 아직 게시하지 않은 로컬 검증 후보의 식별자다. PR 병합이나 장치 배포 완료를
주장하지 않으며, 게시 후에는 해당 PR의 검증 기록으로 이어 확인한다.

- RED: `31d4e5aefd`의 새 시작 의존성 시험이 기존 `rosy-io.service`를 찾아 실패했다.
  별도 실제 HTTP feed 시험은 `no-update`, OS 원장 불변, 서비스 명령 0건을 확인했다.
- GREEN: `90e631297f`를 AI 시험 PC에서 다음 명령으로 검증했다. 311개 통과·skip 0,
  known-failures 비교는 new/known/flaky 모두 0이었다. 실제 systemd **오프라인 parser**를
  포함하며 PID1의 수정 unit 실행이나 새 이미지 장치 수용을 대신하지 않는다.

```text
python tools/remote/remote_pytest.py --sha 90e631297f -- test/test_os_controller_image.py test/test_os_update_feed.py test/test_os_update_controller.py test/test_native_systemd_contract.py -q
```

독립 읽기 전용 계약 검토는 `34033c5da8..90e631297f`에서 수정 필요 사항이 없었다.
후보 소스의 착지·게시·서명 OS 배포는 이 기록만으로 완료되지 않는다.

## 배포와 임시 복구

이 unit은 **frozen OS bootstrap** 소유다. 보통 payload의 image-layer sync는 이 목적지를
`IMAGE_LAYER_DESTINATION`으로 거절한다. 일반 payload 갱신으로 고쳤다고 보고하거나
서명 payload·frozen bootstrap 파일을 손으로 편집하지 않는다. 새 서명 OS 이미지의
frozen staging·설치와 실제 PID1 의존성, no-update 시 항법 유지, 실제 update 시 기존
admission·정지·trial·rollback을 검증해야 한다. 경계는
[이미지 계약 시험](../../../test/test_os_controller_image.py)에 고정돼 있다.

옛 설치에서의 감독 시험은 [맵핑 복구 절차](../../deployment/pinky-native-mapping-recovery.md)를
따른다. 타이머 정지는 시험 동안의 임시 조치이며 정상 업데이트 지원을 뜻하지 않는다.
실제 자동 업데이트를 항법 runtime에서도 지원하려면 유휴·유지보수 admission 뒤의 안전한
runtime 전환과 실패 복귀를 별도로 구현·수용해야 한다. source-health 조건을 끄지 않는다.

재발 확인은 점검 함수의 반환값과 **unit 시작 의존성**을 함께 본다.
