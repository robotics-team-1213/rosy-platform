# 교차로 Fleet 신호 질의 검증 — 2026-10-10

## 요청과 구현

- 결정: [D-620](../../adr/D-620-junction-fleet-signal-query.md).
- 브랜치: `feat/junction-signal`; 구현 검증 SHA `48de3f65c3`.
- 질의: 기존 paired Fleet WebSocket heartbeat, 요청 ID는 정지 교차로 에피소드 UUID.
- 응답: green + may_enter이면 기존 CORE 우측 90도 회전 선택.
  red/unknown/오류/만료/진입 불허는 대기. 완전 무응답만 3초 뒤 우측 선택.
- CORE 몸 정지·회전 근거·오돔·횡단보도·통행권·watchdog·E-Stop 유지.

## SOURCE / 원격 시험

- 테스트 먼저 작성한 `1ea877e301`: 새 기능 부재로 9개 실패를 모델 PC에서 재현.
- 구현 `05987ace3a`, 보강 `770e1d6da3`, 최종 동작 검증 `48de3f65c3`.
- AI PC에서 관련 **273 passed**, `test/known_failures.py`: **0 NEW**.
  원격 로그 `X:/DevTemp/junction-signal-final/run-1.txt`.
- 검증: 3초 경계, 한 번만 선택, red→green, 늦은 red, 잘못된 reply/이전 ID,
  pairing 거부, OFF, 카메라 공백, 중복 회전 금지, 회전 근거 없는 정지,
  실제 FleetAgent 송수신, paired hub 신원, 신호표 자유/점유,
  지도 신선도 및 기존 교차로/Fleet 링크/횡단보도 회귀.
- 기본 설정은 꺼짐이다. 자체 신호 상태의 `entered`나 API 성공으로 실물 이동을 주장하지 않는다.

## ARTIFACT / DEVICE / FIELD

- 새 `core_features/.../junction/signal.py` 런타임 파일은 기존 D-553 verbatim
  delta 경로의 대상이 아니다. native ARM64 전체 payload 빌드가 필요하다.
- Fleet 이미지에도 hub/지도 신호 조회 변경을 빌드해야 한다.
- 이 기능의 signed artifact, 설치, 실물 교차로 통과는 **아직 확인하지 않았다**.
  기존 설치 release 137과 이전 주행 증거는 D-620의 설치/통과 증거가 아니다.
- 공동 교차로 우선권은 무응답 fallback이 보장하지 않는다. 현장 감독 시험에 한정한다.

## 앞선 요청의 현장 상태

- v2 floor-gate 호환 수정은 양쪽 release 136에서 실제 load와 v2 추론을 확인했다.
- CORE 몸 내부 LiDAR 반사 수정은 release 137로 양쪽 설치했다.
  8kcn은 정지 상태에서 TRACKING으로 실제 약 4cm 이동한 뒤 외부 여유 약 1.3cm로 정지했다.
  원래 몸 내부 반환에 의한 출발 차단과 남은 외부 근접 반환을 구분한다.
- 횡단보도 설정 양쪽 `crosswalk_clear_s:3.0`, `crosswalk_look_min_scans:24`를 읽어 확인했고
  관련 합성 시험 55 passed. 연속 비움 3초의 의미이며 사람이 있거나 미확인이면 기다린다.
  실물 빈 횡단보도에서 3초 뒤 통과한 증거는 아직 없다.
- 9dfk 최신 시도는 차선 손실/재선택 요구로 종료했다. 합격 판정하지 않는다.
