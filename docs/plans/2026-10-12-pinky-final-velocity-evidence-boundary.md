# Pinky 최종 속도 원본 검증 Implementation Plan

**Goal:** 평면 행동 자료에서 무시되는 다른 축의 움직임과 비정상 숫자를 원본 단계에서 거절한다.

## Source checkpoint

최신 main 통합 commit `5f06e03ab1d2a2d870e341c1801259605857552d`를 로컬 착지했다. 적격 Model PC 8GB의 원본 패키지가 설치된 별도 원격 환경에서 관련 20개 파일은 473 passed/skipped 0, terminal exit 0, NEW 0과 lint를 통과했다. Native CDR/MCAP·raw derivation·구조·release·운영 도구 회귀를 포함한다. 고정 로그는 세션 `logs/raw-velocity-land-5f06e03ab1/run-1.txt`다. 아래 107개는 통합 전 전체 Pinky/구조 회귀이며 실제 모델/현장 수용은 포함하지 않는다.

commit `305aa8466f`의 적격 Model PC 7.9GB 원격 Pinky/구조 회귀는 107 passed, skipped 0, terminal exit 0, known-failures NEW 0이다. 로그는 세션 `logs/raw-velocity-green/run-1.txt`다. Native CDR/MCAP RED는 22 NEW/6 passed로 누락을 재현했으며 기존 실패 목록에 추가하지 않았다. 최초 기본 CI 환경의 28 skipped는 별도 미확인 기록이고 통과로 쓰지 않았다.

기존 원본 요구 파일을 별도 dependency hash의 원격 venv에 설치했다. MCAP·numpy 2.2.6·OpenCV 4.12.0 실제 import/version을 확인했고 공유 CI venv를 바꾸지 않았다. 독립 source 검토에서 중요한 blocker는 없었다. main 통합은 같은 원본 환경으로 착지 도구를 실행한다. 실제 자료·정상 개입 원인·모델·배포·현장 수용은 후속이다.

1. 실제 ROS 2 CDR/MCAP writer로 다른 네 축의 nonzero와 여섯 축의 NaN/±Infinity를 기록하고 committed HEAD 원격 RED를 확인한다. MCAP/numpy/OpenCV가 없어 건너뛰면 원본 검증 통과로 보고하지 않는다.
2. 기존 raw_messages.load_tables의 cmd_vel branch에서 여섯 축을 검증한 뒤 기존 두 필드만 내보낸다. 0이 아닌 다른 축은 명시적으로 거절한다. 원본을 바꾸거나 정규화하지 않는다.
3. 기존 MCAP/video round trip·raw derivation·Episode/behavior prepare와 구조 회귀를 원격 시험하고 독립 검토 및 승인된 로컬 병합을 한다.

후속은 모델 개입 원인·명령·정상 상태의 시각 결속과 전체 수집 범위, 재발 원본의 독립 평가다. 최종 속도만으로 정상 주행을 불필요 모델 명령으로 분류하지 않으며 0건과 실제 현장 수용을 주장하지 않는다. 통합 목표는 ACTIVE다.
