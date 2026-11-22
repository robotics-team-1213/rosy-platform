---
surface: fleet
kind: additive
slug: cell-s-bed-camera
date: 2026-11-21
title: Fleet 셀 S 적재함 카메라 판정 경로 (D-1057 2-9)
history: Additive (D-1057 2-9, Safety-Review 대상): Fleet POST /api/fleet/pipeline/cell-tasks/{task_id}/bed-observation(셀 S owner service 주체, QUEUED, READY만 Fleet 자세·정지로 다시 묶어 10 s 확인 기록), 새 거부 코드 BED_CAMERA_CELL_NOT_SUPPORTED·BED_CAMERA_DISABLED·BED_OBSERVATION_INVALID·BED_OBSERVATION_ROBOT_NOT_STILL·BED_CAMERA_NOT_READY, bed_confirmation 추가 필드(source, principal, camera). 셀 S bed-confirm은 10 s 안의 카메라 NOT_READY에 409.
---
표면: Fleet. 추가형. `claim`·`complete`의 요청·응답 모양과 거부 코드는 바뀌지 않는다. 셀 S의 `bed-confirm`에 새 409가 하나 생긴다.

| Method and path | Contract |
|---|---|
| `POST /api/fleet/pipeline/cell-tasks/{task_id}/bed-observation` | D-1057 2-9. 셀 S 상단 카메라의 적재함 판정. 검사 순서: 작업이 `cell_s`(아니면 409 `BED_CAMERA_CELL_NOT_SUPPORTED`), 사이트 설정 `ROSY_FLEET_CELL_S_BED_CAMERA`가 `off`·`0`·`false`·`no`가 아님(호출 때 읽음, 기본 켜짐; 아니면 409 `BED_CAMERA_DISABLED`), 셀 S owner로 등록된 service 주체(`ROSY_FLEET_CELL_OWNERS`, 아니면 403 `OWNER_PRINCIPAL_NOT_REGISTERED`), QUEUED 작업(409 `CELL_TASK_NOT_QUEUED`, RUNNING 재확인은 운영자만), 본문 `robot_id` 일치(422 `BED_CONFIRM_ROBOT_MISMATCH`), 본문 64 KB 이하(413 `EVIDENCE_BODY_TOO_LARGE`), 유한 JSON, `verdict` `READY`·`NOT_READY`·`UNKNOWN`, `frames` 3장 이상(`source_seq` 정수·증가, `source_stamp` 증가, 끝−첫 1.0 s 이상, 끝 장 나이 −0.5…2.0 s; 아니면 422 `BED_OBSERVATION_INVALID`, 아무것도 저장하지 않음). 본문 `{robot_id, verdict, reasons[], frames[{source_seq, source_stamp, jpeg_sha256}], bed{score, offset_px, tol_px}, objects, site, roi, config_sha256}`. 판정은 작업별로 메모리에 남고(`READY`가 아니면 200 `{ok, recorded:false, verdict}`), `READY`일 때만 Fleet이 자기 측정으로 다시 묶는다: 지도 자세(`bed-confirm`과 같음, 아니면 409 `BED_CONFIRM_POSE_UNAVAILABLE`), 정지 유지(`wheel_brake_locked`, odom 1e-4 m/s 이하)이고 그 정지 구간이 첫 프레임 `source_stamp` − 0.5 s 전에 시작(아니면 409 `BED_OBSERVATION_ROBOT_NOT_STILL`). 이미 유효한 확인(운영자 또는 카메라)이 있으면 200 `recorded:false`(갱신하지 않음). 통과하면 `bed-confirm`과 같은 기록(`source: cell_top_camera`)을 만들고 200 `{ok, recorded:true, verdict, expires_in_s:10}`. claim까지 10 s 유효하며, claim이 lease에 묶은 뒤의 2 cm·지도 변경 영구 무효와 `/complete` 422 `BED_CONFIRMATION_INVALID`는 운영자 확인과 같다. `UNKNOWN`은 기록을 만들지 않는다. |
| `POST /api/fleet/pipeline/cell-tasks/{task_id}/bed-confirm` (변경) | 셀 S 작업에 10 s 안의 카메라 판정이 `NOT_READY`이면 409 `BED_CAMERA_NOT_READY`(끄는 스위치가 꺼져 있으면 검사하지 않음). 그 밖(UNKNOWN·판정 없음·셀 A/B)은 그대로다. |
| 작업 행 `bed_confirmation` (추가 필드) | 카메라 기록을 claim이 묶으면 `{operator: null, source: "cell_top_camera", principal, camera{frames, bed, objects, config_sha256}, confirmed_at, pose, map_id, map_version}`. 운영자 확인의 모양은 그대로다. |
