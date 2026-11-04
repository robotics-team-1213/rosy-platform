---
title: OMX 프로세스 잠금 해제는 공유 구역의 물리적 비움이 아니다
module: deploy/robot/omx
date: "2026-11-04"
problem_type: logic_error
component: deployment
severity: high
symptoms:
  - "park 완료의 ok=true를 홈 도달로 해석해 settled=false인데 구역 예약을 해제함"
  - "상대 HOLD와 빈 세션 잠금만으로 상대 팔 쪽 진입을 허용함"
root_cause: missing_validation
resolution_type: code_fix
tags: [omx, safety, coordination, persistence]
---

# OMX 프로세스 잠금 해제는 공유 구역의 물리적 비움이 아니다

## 문제와 원인

2026-11-04 미착지 변경의 독립 안전 리뷰에서 두 경로를 확인했다. 실물 충돌을
일으켜 재현한 기록은 아니다. Runner는 park 대기 시간이 끝나면
`{"ok": true, "settled": false}`를 반환할 수 있었지만, Gate는 ok만 보고 구역을
내줬다. 또한 HOLD는 팔이 뻗은 채 끝난 고장에도 생기는데, 빈 세션 잠금과 HOLD를
다른 팔 쪽 진입의 근거로 사용했다.

예약을 park 성공까지 유지하는 수정만으로도 부족했다. 프로세스가 죽으면 flock은
풀리지만 팔은 접히지 않는다. 잠금을 다시 얻었다는 사실을 물리적 비움으로 해석하면
재시작 뒤에도 같은 문제가 생긴다. 파일 내용만 fsync하고 새 파일의 디렉터리 항목을
동기화하지 않는 구현도 호스트 중단에 대한 보존 근거가 되지 않는다.

## 해결한 소스 동작

- [Gate](../../../deploy/robot/omx/cell_transfer.py)는 현재 guarded 세션에 맞는 새 응답,
  오류 없음, settled=true, 유한 몸체 관절 측정과 기존 홈 오차 조건을 함께 확인한 뒤에만
  점유를 비운다. 확인하지 못한 park는 거절하고 점유를 남긴다.
- [Zones](../../../deploy/robot/omx/cell_zones.py)는 움직이기 전에 기존 구역 파일에 검증된
  장치·instance·설정/profile digest와 세션을 기록한다. 파일, 그 디렉터리, 상위 경로를
  동기화한 뒤에만 진입을 허용한다. 동기화 실패는 점유를 남기고 이동을 막는다.
- 프로세스 종료 뒤 남은 점유는 평상시 진입으로 채택하지 않는다. 같은 검증 owner가
  guarded park로 현재 홈 도달을 확인했을 때만 자신의 중단 기록을 해제할 수 있다.
  다른 owner 또는 손상된 기록은 계속 막는다.
- 상대 팔 쪽 takeover는 거절한다. 상대 HOLD가 있으면 중앙도 거절한다.
  zone.takeover 설정값이 이 조건을 완화하지 않는다.

## 검증과 적용 상태

원격 RED는 실제 Runner.tick의 park timeout, 불확실·다른 세션·잘못된 홈,
프로세스 종료, 다른 owner의 해제, 파일·디렉터리 동기화 실패를 재현했다.
수정 소스 edc23d4559e52c6649b3a123586a3b22356acf5f의 최종 원격 시험은
252 passed, 0 skipped이며 known_failures의 new/known/flaky는 모두 0이었다.
같은 소스의 독립 재검토에서 두 P1과 디렉터리 보존 P2가 해소됐음을 확인했다.
[시험 범위와 운영 제한](../../validation/omx-zone-occupancy-2026-11-04/result.md)을 함께 본다.

이 기록을 작성할 때 수정은 미착지·미배포 상태다. 실제 저장장치 전원 손실,
OS 재시작과 실물 양팔 구역 수용은 시험하지 않았다.

## 복구와 다음 적용 조건

옛 reader는 점유 파일 내용을 읽지 않으므로 새 reader와 섞어 실행하지 않는다.
기존 세션을 안전하게 끝내고 실제 이격을 확인한 뒤 모든 팔의 공유 runtime을 함께
갱신한다. 빈 옛 잠금 파일도 이격의 증거로 사용하지 않는다.

공개 main을 따르는 OMX 자동 갱신은 Learning 서명 코드 배포와 별도 경로다. 기존
torque OFF·프로세스 유휴 확인만으로 이 전환 조건을 충족했다고 판단하지 않는다.
공개 게시 전 자동 갱신 보류와 실행 중 updater 확인은
[운영 절차](../../../deploy/robot/omx/README.md)의 「양팔 구역 점유와 중단 복구」를 따른다.

중단한 팔은 기존 사람 감독·사건 복구 절차로 회복하고 같은 검증 owner의 guarded
park로 점유를 해제한다. 파일 삭제, profile 변경에 의한 채택, force-clear로 우회하지
않는다. Fleet 사건 HOLD의 사람 확인과 해제는 별도다.

다음에 자원 잠금을 물리 장치와 연결할 때는 정상 종료뿐 아니라 프로세스 종료,
저장 실패와 새 프로세스의 재진입까지 검사한다. 명령 완료·프로세스 유휴·운영자 HOLD는
각각 실제 구역 비움과 별도의 사실이다.
