---
title: 장소 좌표의 주인은 활성 지도 하나다. 구역 설정에 좌표를 복제하면 지도가 바뀐 뒤 겹침으로 보인다
date: 2026-11-26
category: logic-errors
module: operations/fleet/fleet/pipeline/station_zones.py, applications/fleet/web/map/zone-blueprint-model.js
problem_type: logic_error
component: frontend
severity: medium
symptoms:
  - "구역 도면에 정류장 S1·S3·S5와 반출대 EXP_S1·EXP_S3_BELT·EXP_S5_PALLET가 같은 자리에 따로 그려진다."
  - "임시 대기칸 STG_S3_WAIT·STG_C2 표식이 차로 한가운데와 분기점 위에 놓인다."
  - "2D는 빈 격자 위의 점, 3D는 현장에 놓이지 않은 0.28 m 격자 슬롯이라 두 그림이 실제 배치와 맞지 않는다."
root_cause: config_error
resolution_type: code_fix
applies_when:
  - "Fleet 콘솔 지도·도면에 장소, 정차 공간, 작업대, 컨베이어를 그리는 일"
  - "station_zones.yaml에 구역이나 고정물을 더하거나 옮기는 일"
  - "셀 작업대를 옮기거나 다시 등록한 뒤 구역맵 영역을 다시 잡는 일"
tags: [fleet, site-map, station-zones, zone-blueprint, world_261026, d-1021]
---

# 장소 좌표의 주인은 활성 지도 하나다. 구역 설정에 좌표를 복제하면 지도가 바뀐 뒤 겹침으로 보인다

## Problem

2026-11-26 사용자가 관제 콘솔의 구역 도면(2D·3D)이 실제 현장 배치와 전혀 다르고 구역끼리 겹쳐 보인다고 지적했다. 로봇 동작에는 영향이 없었지만, 운영자가 어느 구역이 어디인지 도면으로 판단할 수 없었다.

## Symptoms

- 활성 지도 v394의 장소와 `station_zones.yaml`에 따로 적힌 좌표가 5개 구역 모두 달랐다. EXP_S1은 S1에서 0.5 cm, EXP_S5_PALLET은 S5에서 2.3 cm, EXP_S3_BELT은 S3에서 6.4 cm, STG_S3_WAIT는 S3에서 17 cm, STG_C2는 이름의 장소 C2에서 90 cm 떨어져 있었다.
- 구역 도면은 site-points와 station-zones의 점만 그리고 활성 지도(`rosy.site_map/1`)의 차로·장소는 읽지 않았다.
- 팔 셀 구역(장치 야드·임시 장치 A/B·반출대)은 현장 좌표 없이 행·열 격자로만 그려졌고, 3D는 칸을 0.28 m로 그려 로봇보다 큰 슬롯이 되었다.

## What Didn't Work

- **점을 더 그리는 것.** 저장 좌표와 장소 좌표를 둘 다 그리니 같은 장소가 두 번 나왔다. 겹침은 그림 문제가 아니라 값이 둘인 문제였다.
- **꼭짓점·모서리 검사만으로 다각형 겹침 판정.** 한쪽 꼭짓점이 다른 쪽 안에 있는지, 모서리가 교차하는지만 보면 변이 겹치는 두 사각형(꼭짓점은 안에 없고 모서리가 T자로 닿음)을 놓친다. 시험이 이 틀림을 잡았다.
- **3D 슬래브을 회전 없이 두는 것.** 바닥에 눕히는 `-90도` 회전이 shape의 y를 `-z`로 보내서, 차로·라벨과 슬래브의 남북이 뒤집혔다. 위에서 본 시점을 2D 옆에 놓고 보고 찾았다.

## Solution

- **장소에 묶인 구역은 좌표를 갖지 않는다.** `staging_bays`·`export_stations`는 `place_id`만 남기고 `x`·`y`·`yaw_deg`를 지웠다. 배차는 이미 `place_id`만 읽었으니 동작은 그대로다. `operations/fleet/test/test_station_zones_zone_map.py`가 좌표 키가 다시 들어오면 실패한다.
- **지도에 없는 고정물은 `areas`에 둔다.** `station_zones.yaml`의 `areas`가 작업대·컨베이어·셀 구역의 폴리곤(활성 지도 프레임, m), `height_m`, `status`, `evidence`를 갖는다. 차체 크기는 같은 파일의 `vehicle`가 갖고 Pinky 프로파일 `geometry.yaml`과 같은지 시험이 대조한다.
- **뷰 하나가 모델 하나를 읽는다.** `zone-blueprint-model.js`가 site-points·station-zones·활성 지도(`GET /api/fleet/site-map/active`)를 한 모델로 합치고, 2D(SVG)와 3D(three.js)가 그 모델을 그린다. 차량 구역은 장소 자세와 차체 크기로 그리고 굵은 선이 짐칸이다. 지도의 `view_turn_deg`도 같은 모델이 따른다.
- **겹침은 자른 면적으로 잰다.** 두 다각형을 Sutherland-Hodgman으로 잘라 공유 면적을 본다(Python과 JS에 같은 식). 저장 시에는 영역끼리 부분 겹침이거나 차로 표준 폭에 2 cm 넘게 들어간 `areas`를 422로 거절하고, 화면의 "지도 검사"에는 겹침·2 cm 미만 여유·YAML 좌표 불일치를 적는다.

셀 장비를 현장 프레임에 놓은 근거는 코드에 숫자만 남으므로 여기에 남긴다.

- R08 CAD194 메시(`rosy.world.meshes.v1`)를 색별 조각으로 나눠 작업대·벨트·선체·임시 판·반출대의 셀 프레임 범위를 얻는다.
- Rosy World 인계의 등록 후보(`rosy.world.registration-check.v1`, 표시 전용)로 옮긴다. 셀 -> 현장은 yaw `-90도`, 원점 `(0.793, 0.355)`이다. 즉 `site_x = 0.793 + cell_y`, `site_y = 0.355 - cell_x`.
- 2026-11-01 천장 보정 사진(`world_261026_v7_map.png`) 위에 겹쳐 맞춰 본다. 작업대 서쪽 가장자리는 사진 0.466 m, CAD 0.467 m, 벨트 남쪽 끝은 사진 -0.100 m, CAD -0.103 m였다. 임시 판과 반출대는 사진에 보이지 않아 "설계 배치"로만 적었다.
- 사진에만 있는 공급 작업대 S는 노란 색 영역으로 잡아 `photo_estimated`로 두었다. 동쪽 끝은 사진 경계에서 잘렸다.

같은 검사에서 나온 여유이다. 컨베이어 남단과 S3 차로 가장자리 사이는 4 mm, 공급 작업대 S 남쪽 가장자리는 `loop_right` 차로의 표준 폭(0.20 m)에 9 mm 들어온다. 둘 다 2 cm 오차 범위 안이라 거절하지 않고 "지도 검사"에만 적힌다. 차체 반폭 5.7 cm 기준으로 실물 여유는 있지만, CAD 등록과 사진 판독의 오차(약 1 cm)를 생각하면 실측 전이다.

## Why This Works

D-1021이 말한 "값마다 주인 하나"는 좌표에도 그대로 들어맞는다. 장소 좌표의 주인은 활성 지도이고, 지도는 자동 보정으로 자주 바뀐다(같은 달에 S3의 x가 0.70, 0.82, 0.745 m로 세 번 바뀌었다는 작업 기록이 있으나 이 문서를 쓸 때 저장소에서 대조하지는 못했다). 설정 파일에 복제된 좌표는 따라가지 못해 겹침·오판을 만든다. 구역이 `place_id`만 참조하면 지도가 바뀌어도 도면이 저절로 맞는다. 지도에 없는 고정물은 주인이 없으니, 근거 등급을 붙인 `areas`가 그 주인이 된다.

## Prevention

- 장소에 묶인 구역·표식에는 좌표를 쓰지 않는다. 좌표가 필요하면 `place_id`로 활성 지도에서 읽는다. `site_points.py` 머리말의 "Single-owner truth"가 같은 뜻이다.
- 고정물을 더하거나 옮길 때는 위 순서(CAD 범위 -> 등록 변환 -> 보정 사진 위에 겹침)로 숫자를 얻고, `status`와 `evidence`에 어떻게 얻었는지 적는다. 눈으로 어림잡은 숫자는 `measured`로 적지 않는다.
- 저장은 `PUT /api/fleet/pipeline/station-zones`가 검사하지만, 그림이 맞는지는 실제 응답으로 그려 봐야 안다. 3D 슬래브 뒤집힘과 이름 가림은 시험이 아니라 캡처에서 찾았다.
- 다각형 겹침을 새로 쓸 때는 꼭짓점·모서리 검사에 그치지 않고 자른 면적으로 잰다.

## Related Issues

- D-1021: 값마다 주인 하나(신원·배치·유닛). 이 교훈은 그것을 현장 좌표에 적용한 것이다.
- `docs/solutions/logic-errors/world-261026-floor-and-maneuver-lines.md`: 같은 지도에서 도색·경로·지도 표시를 겹쳐 대조하는 방법.
- 증거와 캡처는 `D:/DevTemp/zone-blueprint-map-20261126/`에 있다(저장소 밖).
