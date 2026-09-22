---
title: 호스트 pytest가 초록이어도 Gazebo 인식 경로는 실제로 돌려서 렌더된 값을 재야 한다
date: 2026-09-22
category: workflow-issues
module: sim/gz_sim + apps/control (map_v2_fleet 차선 주행)
problem_type: workflow_issue
component: development_workflow
severity: high
applies_when:
  - STL/CAD에서 새 Gazebo 월드를 만들거나 카메라 인식 임계값을 정할 때
  - 다른 맵의 CORE 오버레이나 launch 인자를 빌려 쓸 때
  - 관측 노드가 여러 프레임의 기억(odometry로 옮긴 메모리)으로 증거를 낼 때
tags: [gazebo, ros-sim, perception, fail-closed, threshold, rasterize, odometry]
---

# 호스트 pytest가 초록이어도 Gazebo 인식 경로는 실제로 돌려서 렌더된 값을 재야 한다

## Context

`feat/map-v2-fleet-world`에서 260919 STL을 Gazebo 월드로 바꾸고 카메라 차선 주행을 붙였다.
Task 1-5를 마쳤을 때 호스트 pytest는 1,248개 모두 통과였다. 그러나 WSL Gazebo 첫 실행부터
로봇은 한 번도 움직이지 않았다. 호스트 시험으로는 잡히지 않는 결함 다섯 개가 실행에서 차례로
나왔다(`docs/validation/map-v2-fleet-gazebo-2026-09-22/result.md`).

| 결함 | 호스트 시험이 못 본 이유 |
|---|---|
| `launch_sim.launch.xml` 주석 안의 `--` 때문에 XML 파싱이 실패해 모든 launch가 거부됨 | XML을 문자열로만 검사했고 파싱하지 않았다 |
| 5 mm 벽을 1 cm 셀로 래스터화하자 +x 벽이 셀 중심 부동소수 동점으로 빠지고, 외곽이 free로 새어 나감 | PGM 크기만 검사했다 |
| 로봇 차체가 카메라 하단 행에 회색 218로 찍혀 흰 선(224-228)으로 읽힘. 화면 42%가 밝아서 washed-out으로 거부됨 | 합성 프레임에는 차체가 없었다 |
| 빌려 온 CORE 오버레이가 `ENFORCED` 교통 정책이라 도로 증거 없이 모든 명령을 HOLD | CORE는 TRACKING 상태를 보고했는데 `/cmd_vel`은 0이었다 |
| 무게중심 검출기는 단일 선용이라, 두 선짜리 차로에서 한쪽 경계선에 붙음 | 단위 시험은 선 하나짜리 프레임만 썼다 |

## Guidance

1. **첫 번째 실행 게이트는 "움직이는가"다.** `ros2 topic hz`, 관측 JSON, `/cmd_vel` 퍼블리셔 목록,
   odom 경로 길이를 한 스크립트로 기록한다. 결과가 "TRACKING인데 0 명령"이면 CORE와 인식
   사이의 게이트(정책, 오버레이)부터 본다.
2. **임계값은 렌더된 픽셀을 재고 나서 정한다.** 실제 프레임을 저장해 행별 회색값을 찍는다.
   이번 실측값은 바닥 109, 차체 218, 선 224-228이었고 원거리 선은 214까지 어두워졌다.
   숫자는 그 측정값과 함께 커밋 메시지와 시험 docstring에 남긴다.
3. **래스터 해상도는 가장 얇은 벽 두께 이하로 둔다.** 시험은 크기가 아니라 셀 단위로 판정한다.
   스폰 셀은 free, 벽 중점 4개는 occupied, 외곽은 unknown이어야 한다.
4. **런치/월드 XML은 `ET.parse`로 파싱하는 시험을 둔다.** XML 주석 안에 `--`를 쓰면 파일 전체가 죽는다.
5. **맵마다 자기 CORE 오버레이를 둔다.** 정책을 빌리면 존재하지 않는 증거를 기다리며 조용히 멈춘다.
6. **기억 기반 증거는 이동 거리와 시계 둘 다로 제한한다.** odometry가 멈추면 이동 거리 기반
   prune은 영영 돌지 않는다. odom stamp가 오래됐으면 pose=None으로 보고, 새 페인트 없이 지난
   시간에도 상한을 둔다(`pose_if_fresh`, `MEMORY_MAX_AGE_S`). 리뷰어가 만든 재현(odom 고정,
   빈 프레임 3,000장)이 수정 전에는 600 s 동안 출력을 냈다.
7. **실행에서 얻은 프레임을 오프라인 재현 입력으로 쓴다.** 멈춘 지점의 프레임에 검출기를 직접
   돌리면 원인(신뢰도 분모, 횡단보도 막대 페어링, washed-out 컷)이 한 번에 보인다.

## Why This Matters

다섯 결함 모두 fail-closed로 드러났다. 로봇은 멈췄고 위험한 명령은 없었다. 그래서 호스트 시험만
보면 "안전하고 정상"처럼 보인다. 실제 실행과 렌더 측정 없이 "완료"라고 하면 동작하지 않는
기능을 넘기게 된다. 반대로 실행 증거를 run ID별로 남기면 각 수정이 무엇을 고쳤는지 추적되고,
최종 한 바퀴 폐합(run 194559에서 2.9 mm, 수정 후 run 204552에서 4.3 mm)이 근거를 갖는다.
이 문서는 ROS-SIM 교훈이다. DEVICE/FIELD에는 odom drift, 조명, 카메라 보정이라는 별도 게이트가 남아 있다.
