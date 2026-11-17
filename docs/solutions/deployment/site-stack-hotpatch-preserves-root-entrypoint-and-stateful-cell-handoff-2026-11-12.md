---
title: rosy-fleet-r 컨테이너 핫패치는 secret_bootstrap용 root 시작과 상태 유지형 셀 핸드오프를 지켜야 한다
date: 2026-11-12
category: deployment
module: operations/fleet/fleet/server/sitemap/pipeline_routes.py, operations/fleet/fleet/server/console/charge_bay_routes.py, deploy/robot/omx/cell_fleet_pipeline.py
modules: [operations, deploy]
problem_type: environment_constraint
component: site_stack_runtime
severity: high
symptoms:
  - "secret bootstrap: container must start as root or the configured runtime uid (rosy-site-fleet / rosy-site-vision 재시작 루프 및 502 Bad Gateway)"
  - "site map / routing config: /opt/rosy/maps/map_v2_fleet/lane_graph.yaml needs nodes and segments"
  - "원격 PC에서 POST /api/fleet/pipeline/cell-handoff 호출 후 GET /api/fleet/pipeline/status 및 /api/fleet/charge-bays에 잠금 상태가 남지 않음"
root_cause: environment_constraint
resolution_type: code_and_ops
tags: [fleet-r, omx-cell, secret-bootstrap, cross-pc, handoff]
applies_when:
  - "별도 호스트(rosy-fleet-r)의 rosy-site-fleet / rosy-site-vision 이미지를 오버레이 빌드하거나 재기동할 때"
  - "시뮬/AI 호스트 또는 OMX 셀 호스트에서 rosy-fleet-r로 원격 셀 핸드오프(rosy.fleet-r-cell-contract.v1)를 수행할 때"
---

# rosy-fleet-r 컨테이너 핫패치는 secret_bootstrap용 root 시작과 상태 유지형 셀 핸드오프를 지켜야 한다

## Problem

1. `rosy-site-fleet`·`rosy-site-vision` 컨테이너는 `/usr/local/bin/secret_bootstrap`을 entrypoint로 써서 시크릿을 읽은 뒤 런타임 UID로 권한을 내린다. 오버레이 `Dockerfile` 마지막에 `USER 10001:10001` 또는 `USER 10002:10002`를 두면 시작 즉시 `container must start as root or the configured runtime uid`로 죽고 프록시가 `502 Bad Gateway`를 반환한다. 또한 수동 `docker compose` 실행 시 `-f compose.workcell.yaml`을 빼면 workcell peer 컨테이너가 누락된다.
2. Tailscale 태그가 붙은 시뮬/AI 호스트(`tagged-devices`)는 ACL 정책상 `rosy-fleet-r`의 Tailscale TCP 포트로 직접 붙지 못하므로 동일 서브넷 LAN HTTPS 경로를 써야 한다.
3. 원격 호스트가 `POST /api/fleet/pipeline/cell-handoff`로 `ARM_IN_BED_ZONE` 잠금을 걸었을 때 서버가 이를 요청 간 상태로 보존하지 않으면, 뒤이은 `GET /api/fleet/pipeline/status`나 `GET /api/fleet/charge-bays` 조회에서 AMR 출발 억제(`amr_motion_inhibited: true`, `blocked_by_cell: true`)가 풀려 버린다.

## Solution

- `rosy-fleet-r`에서 이미지를 오버레이 빌드할 때는 최종 `USER root`를 유지해 `secret_bootstrap`이 시크릿 마운트를 읽고 자체적으로 UID를 내리게 하고, 기동은 항상 `sudo systemctl restart rosy-site-stack.service`(`compose.yaml` + `compose.workcell.yaml` 포함)로 수행한다.
- `pipeline_routes.py`와 `charge_bay_routes.py`는 `app.state.omx_cell_states`에 셀별 최신 핸드오프 상태(`phase`, `robot_id`, `station_place`, `updated_at`)를 저장하고, `GET /api/fleet/pipeline/status`·`POST /api/fleet/pipeline/evaluate`·`GET /api/fleet/charge-bays`가 이 상태를 읽어 잠긴 로봇의 출발 액션을 `blocked_by_cell: true`, `reason: "locked_by_cell"`로 표시한다.
- `FleetModelPipeline.execute_remote_fleet_r_handoff`는 원격 `rosy-fleet-r`에 `ARM_IN_BED_ZONE` 잠금을 선언하고 `/api/fleet/charge-bays`·`/api/fleet/pipeline/status`에서 잠금 반영을 확인한 뒤 `pinky -> belt` 스테이지를 실행하고 `RELEASED`(`sha256` 다이제스트 포함)를 게시한다.

## Verification

- AI 호스트에서 `pytest` 11개 스위트(**104 passed**) 및 웹 콘솔 Node 테스트(**6 passed**) 통과.
- AI 호스트에서 실제 `rosy-fleet-r` 호스트 HTTPS 엔드포인트로 `run_s3_cell_contract_handoff`를 실행해 `ARM_IN_BED_ZONE` 잠금(`amr_motion_inhibited: true`) -> OMX `pinky -> belt` 이송 -> `RELEASED`(`amr_can_depart: true`) 왕복을 검증했다.

## Prevention

- `rosy-site-*` 컨테이너 오버레이 빌드 시 `USER` 지시어로 비루트 UID를 고정하지 말고 `rosy-site-stack.service` 유닛을 통해 기동 상태를 확인한다.
- 교차 PC 핸드오프 시험은 인메모리 더미뿐 아니라 `app.state.omx_cell_states`를 거치는 연속 HTTP 호출(`POST /cell-handoff` -> `GET /charge-bays` -> `GET /status`)로 검증한다.
