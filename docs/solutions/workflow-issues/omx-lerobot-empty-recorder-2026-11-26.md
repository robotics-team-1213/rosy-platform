---
title: OMX 시연 성공 후 LeRobot 데이터셋에 0회가 저장되는 경우
date: 2026-11-26
category: workflow-issues
module: learning/curation/omx
problem_type: workflow_issue
component: development_workflow
severity: medium
tags: [omx, lerobot, data-gate, demonstration-collection]
applies_when:
  - "같은 시뮬레이션 수집기에서 데이터셋 없이 평가하거나 새 LeRobotDataset에 교사 동작을 기록할 때"
---

# 시연 성공 후 저장 회차가 0인 경우

B팔 c6 운반 수집에서 여섯 회차 모두 인양 후 교사 운반과 안착을 마쳤다. 실행 영수증의 `done`은 참이고 여섯 회차의 관절 명령도 남았다. 하지만 `saved`와 LeRobot 메타데이터의 `total_episodes`, `total_frames`는 모두 0이었다. 영수증에 저장된 명령만으로는 대응하는 세 카메라 영상을 학습에 사용할 수 없다.

이 수집기는 `None`을 전달해 물리 평가만 수행할 수도 있었다. 새로 만든 빈 데이터셋도 파이썬 조건문에서 거짓으로 평가됐다. 프레임 콜백 등록과 `save_episode()` 호출을 모두 `if ds`로 감싸 첫 회차의 모든 쓰기를 건너뛰었다. 에피소드 수가 계속 0이어서 이후 회차도 같은 경로를 거쳤다.

두 조건을 모두 `ds is not None`으로 바꾸고 빈 출력 디렉터리에 같은 시드로 다시 수집했다. 첫 회차에서 `saved=1`, 메타데이터에서 1회·249프레임을 확인했다. 남은 다섯 시드는 별도 출력에 기록했다. 그 데이터셋을 다시 열었을 때 5회·1,245프레임이었고 관절 행과 세 영상의 프레임 수도 맞았다. 재수집할 때는 이전 출력과 물리 영수증을 보존하고, 같은 시드는 실제로 저장된 회차만 한 번 반입한다.

첫 성공 회차에서 저장 횟수가 증가하는지 확인한다. 종료 후에는 디스크에서 다시 열어 저장 회차 수, 관절·동작 행 수, 각 카메라의 디코딩 프레임 수를 해당 시연과 대조한다. 이 확인을 마친 데이터셋에 OMX 반입 검사를 실행한다. [OMX 데이터 반입 검사](../../../learning/curation/omx/data_gate.py)
