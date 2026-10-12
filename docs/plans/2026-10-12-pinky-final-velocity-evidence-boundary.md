# Pinky 최종 속도 원본 검증 Implementation Plan

**Goal:** 평면 행동 자료에서 무시되는 다른 축의 움직임과 비정상 숫자를 원본 단계에서 거절한다.

1. 실제 ROS 2 CDR/MCAP writer로 다른 네 축의 nonzero와 여섯 축의 NaN/±Infinity를 기록하고 committed HEAD 원격 RED를 확인한다. MCAP/numpy/OpenCV가 없어 건너뛰면 원본 검증 통과로 보고하지 않는다.
2. 기존 raw_messages.load_tables의 cmd_vel branch에서 여섯 축을 검증한 뒤 기존 두 필드만 내보낸다. 0이 아닌 다른 축은 명시적으로 거절한다. 원본을 바꾸거나 정규화하지 않는다.
3. 기존 MCAP/video round trip·raw derivation·Episode/behavior prepare와 구조 회귀를 원격 시험하고 독립 검토 및 승인된 로컬 병합을 한다.

후속은 모델 개입 원인·명령·정상 상태의 시각 결속과 전체 수집 범위, 재발 원본의 독립 평가다. 최종 속도만으로 정상 주행을 불필요 모델 명령으로 분류하지 않으며 0건과 실제 현장 수용을 주장하지 않는다. 통합 목표는 ACTIVE다.
