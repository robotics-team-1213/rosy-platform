# D-630 나머지 플랫폼 책임 폴더의 실행

**Status:** Accepted (2026-10-11, 사용자 전체 폴더 정리·Ralph 실행 요청). source와 검증 단위별 main 착지에 한정한다. push·배포·새 모델·실물 활성화는 별도다.

## Context

D-625/D-626으로 API·장치·Nav2 holder를 이전했으나 인지/Drive 계산과 실제 world projection이 과거 패키지에 혼재했다. 전체 나머지 소스 root를 조사해 기존 책임에 맞는 것은 유지하고, 실제 코드와 소비자가 있는 아래 단위를 분리한다. 미래 트리의 예시를 빈 폴더로 채우지 않는다.

## Decision

| 현재 | 의미에 맞는 구현 holder | 보존할 계약 |
|---|---|---|
| perception의 `control.sensing` | `middleware/perception/sensors/sensing` | 기존 import·ROS sensor-provider |
| `control.sensing.perception` | `middleware/perception/vision/perception` | detector·drivable·learned import와 모델 resource |
| `control.control`의 안전·추종·복구·보정 계산 | `middleware/control/drive/{safety,tracking,recovery,calibration}` | 하나의 기존 Python package identity, 상대 import·monkeypatch identity |
| `control.planning`, `control.wander`, `control.safety` | Drive planning/tracking/safety의 응집된 하위 holder | 기존 package·sensor-only adapter·비활성 legacy writer |
| Fleet `localization/map_pose.py` | `operations/world/src/rosy/world/state/projections/map_pose.py` | MapPoseService·객체 identity·동일 Fleet facade·현재 사실 projection |
| Situation analyzers와 incident context/vision | Situation의 실제 분석·사건 책임 하위 holder | service·기존 module identity·사실-only 권한 |

Perception ROS package의 compatibility/provider 조립은 유지한다. 분할 source를 설치할 때 패키지는 한 번만 설치하며 기존 `control.*` identity를 유지한다. source 조회는 좁은 package search path, build는 static holder mapping만 사용한다. 분할된 `control.control`에 한해 기존 installed package로 모듈을 모으는 최소 build 처리를 허용한다. sdist는 외부 source를 내부 snapshot으로 묶어 저장소 없이 재빌드할 수 있어야 한다. 임시 snapshot은 X/원격 임시 빌드에서만 만들며 checkout에 생성하지 않는다.

World는 관측/odom으로 확인한 현재 상태 projection을 소유한다. Fleet는 기존 원장·admission·claim·dispatch와 projection 소비자를 유지한다. World의 `predicted` odom 표기는 dead reckoning이며 행동 조건부 미래 예측을 구현했다는 뜻이 아니다. 학습·독립 평가·AI 추론·prediction 폴더는 실제 계약/소비자 없는 상태에서 만들거나 기존 ACT 정책 연구를 이름만 바꾸어 채우지 않는다.

나머지 learning/contracts/integrations/local execution/skills/drivers/UI/site devices/support root는 실제 책임이 일치하면 유지한다. 전체 root 판정과 현재 경로는 새 구조 안내에 기록한다. 새 범용 executor·registry·store·공개 API·wire·프로세스·writer는 추가하지 않는다.

| 기존 결정 | 관계 |
|---|---|
| D-427 | parts/import table·colcon roots·frozen d427_target 유지; 현재 layout_target만 기록 |
| D-429 | World/관측·장치 Control·모델 adapter 권한 구분; transaction owner 유지 |
| D-430 | 보호 대상의 Safety 추적·독립 리뷰·trailer와 단일 writer 유지 |
| D-625 | 의미 있는 구현 단위만 depth≤5 책임 holder로 이전; namespace/빌드 깊이 예외 유지 |

## Validation and rollback

파일 이전과 caller/packaging/launch/build/manifest/test/안내를 같은 소스 단위에서 마무리한다. Linux source import와 wheel, self-contained sdist→wheel 설치·entrypoint·resource·중복 없음, 관련 원격 회귀와 구조/Safety 검사를 확인한다. 기존 map/STL lineage와 ROS package share를 유지한다. source 역이동과 own-path 참조 역패치로 되돌리며 main/peer를 reset·stash하지 않는다. 실패 단위는 착지하지 않는다.
