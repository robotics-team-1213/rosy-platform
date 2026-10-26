---
module: monitoring
owner: MONITORING
last_verified: {commit: efdddebe30, date: 2026-10-26}
gates:
  SOURCE:
    state: HOLD
    blocker: 관측 Python 기반은 있으나 독립 수집·집계 런타임과 읽기 API 구현이 남아 있다.
  LOCAL:
    state: HOLD
    blocker: 독립 프로세스·수신 프로세스 재시작 복구·실제 backend를 쓰는 화면 검증이 남아 있다.
  ROS-SIM:
    state: N/A
  ARTIFACT:
    state: HOLD
    blocker: wheel 설치 시험만 통과했으며 CLI·화면·native 서비스·TLS 프록시 배포 묶음이 남아 있다.
  DEVICE:
    state: HOLD
    blocker: 실제 관제 PC의 네이티브 설치·프로세스 수명 검증을 수행하지 않았다.
  FIELD:
    state: HOLD
    blocker: 실 PC 배치·LAN/TLS 단절 및 복구·시각·제어 영향 수용이 남아 있다.
adrs: [D-876]
---

## 지금 상태

이름은 **ROSY Monitoring**, 한국어는 **ROSY 시스템 모니터링**이다.
독립 wheel `rosy-monitoring`, import `rosy.monitoring`의 관측 모델·설정·자격·캐시가 있다.
`efdddebe30`의 원격 52시험(설치 wheel 포함)과 캐시 독립 검토는 이 Python 기반만 검증했다.
실제 수집기·조회 API·상태 화면을 구현한 것으로 계산하지 않는다.

ROS-free HTTP 감시 프로필이므로 ROS-SIM은 N/A다. 로봇·호스트의 제어·안전·복구 권한은 기존 소유자에게 남긴다.

## 다음 gate

1. source/wheel/test 기반과 이 등록을 먼저 착지한다.
2. 원천 어댑터·제한된 SQLite 이력/anchor·독립 프로세스·읽기 API를 구현하고 원격 검증한다.
3. Fleet 종료·중앙 단절·오류 응답·권한 밖 사이트·수신 프로세스 재시작을 검증한다.
4. 별도 상태 화면과 기존 관제 진입점, native 배포 묶음을 검증한다.

## 현재 유효한 금지사항

- Monitoring으로 재시작·재부팅·네트워크 변경·안전 해제를 실행하지 않는다.
- 수집기 자체의 정상 보고, host 시험이나 화면만으로 현장 가용성을 GO로 올리지 않는다.
