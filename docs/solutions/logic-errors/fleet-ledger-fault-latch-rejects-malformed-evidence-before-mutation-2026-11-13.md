---
title: Fleet 작업 원장의 장애 잠금 전에 외부 관측값을 검증한다
date: "2026-11-13"
category: logic-errors
module: operations/fleet
problem_type: logic_error
component: service_layer
severity: high
symptoms:
  - "AMR 관측이나 구역 설정에 NaN·무한대가 있으면 작업 claim 또는 dispatch 저장이 실패할 수 있다"
  - "저장 실패를 영구 원장 장애로 분류하면 정상 작업까지 503으로 막힌다"
root_cause: missing_validation
resolution_type: code_fix
tags: [fleet, ledger, data-integrity, validation, amr]
---

# Fleet 작업 원장의 장애 잠금 전에 외부 관측값을 검증한다

## 문제

Fleet 셀 작업 원장은 파일·디렉터리 fsync와 원자 교체로 저장하고, 손상이나 저장 실패가 나면 claim과 완료를 막는 장애 상태를 유지한다. 이 보호는 디스크 장애에 필요하다. 그러나 검토 중 AMR 관측 callback의 비유한 pose/추가 필드, 업로드된 구역 YAML의 `-.inf`, Pinky 이동 시간 계산의 overflow가 원장 변경 뒤 `allow_nan=False` 직렬화 오류를 만들 수 있음을 찾았다. 이때 입력 오류가 저장 장애로 오인돼 다른 정상 작업도 멈출 수 있었다. 실물 현장에서 이 장애가 발생했다는 증거는 없다.

## 원인과 해결

입력마다 유한 값을 확인하는 것만으로는 부족했다. `max_step_m`과 `max_speed_mps`가 각각 유한해도 나눗셈 결과는 무한대가 될 수 있고, AMR 관측의 알려진 좌표가 정상이더라도 관측 dict의 추가 필드가 직렬화를 깨뜨릴 수 있다. 구역 설정은 HTTP 요청에서 검사해도 디스크에 이미 비유한 값이 있을 수 있다.

- [입력 검사](../../../operations/fleet/fleet/server/sitemap/pipeline_task_input.py)는 요청 전체를 `allow_nan=False`로 검사하고 수치 변환 결과가 유한한지 확인한다. Pinky 작업의 계산된 소요 시간도 작업을 만들기 전에 검사한다.
- [AMR 인수](../../../operations/fleet/fleet/server/sitemap/pipeline_routes.py)는 callback 관측 전체를 작업에 복사하기 전에 직렬화 가능성과 유한 pose를 확인한다.
- [구역 설정](../../../operations/fleet/fleet/pipeline/station_zones.py)은 업로드 값을 저장하기 전에, [dispatch](../../../operations/fleet/fleet/server/sitemap/pipeline_aux_routes.py)는 기존 설정에서 읽은 값을 작업에 넣기 전에 다시 확인한다.
- [원장 저장](../../../operations/fleet/fleet/server/sitemap/pipeline_ledger.py)의 원자 교체·동기화와 저장 장애 잠금은 유지한다. 잘못된 입력은 상태 변경 전에 422 또는 인수 보류로 끝낸다.

복구할 때는 먼저 원장 장애가 실제 저장 매체/손상인지 입력의 직렬화 오류인지 구분한다. 입력이 원인이면 값을 고치고 새 작업을 다시 제출한다. 실제 저장 장애로 잠긴 프로세스는 디스크와 원장 파일을 조사·복구한 뒤 재시작하며, 잠금을 임의로 풀어 작업을 진행시키지 않는다.

## 검증과 재적용 조건

현재 로컬 작업 브랜치 커밋 `4bfee668fe`의 원격 Fleet API 시험 `operations/fleet/test/test_pipeline_orchestrator.py`가 21/21 통과했고 새 known failure는 0건이었다. 이 커밋은 아직 원격 main에 없으며 ROSY 절차는 로컬 main fast-forward 착지 후 공개하므로, 이 SHA는 현재 로컬 검증의 식별자다. NaN 관측, 구역 YAML의 무한대, 유한 입력에서 넘친 Pinky 소요 시간, 정상 인수 복구를 포함한다. 독립 재검토에서 변경 범위의 추가 P0/P1은 발견하지 못했다. 이 시험은 API·파일 상태 검증이며 실물 로봇 수용이 아니다.

새로운 Fleet 작업 입력이나 센서 callback을 원장에 넣을 때에는 **상태 변경 전** 요청 전체·변환값·계산 결과를 검사하는 회귀 시험을 붙인다. 테스트는 잘못된 요청 뒤에도 기존 원장 바이트와 장애 상태가 그대로이고 정상 요청이 계속 처리되는지 확인해야 한다. 현재 배포의 단일 프로세스 외에 여러 Fleet 프로세스가 같은 JSON 원장에 쓰게 되면 별도의 프로세스 간 잠금/CAS가 필요하다.
