# D-692 — Native Isaac 카메라 경계 관측 출처

- 상태: Accepted (2026-10-12, D-676 승인 파이프라인의 관측 연결).
- 범위: native 한 대의 카메라 경계/횡단보도 관측과 기존 CORE receiver. 교통 수용이나 주행 권한 추가가 아니다.

## 문제

R19는 고정 segmentation과 기존 drivable 로직에서 회전 전략을 선택한 뒤 유효 차선 상태를 잃었다. native 연결은 scalar observation과 LiDAR만 전달하고 차선 경계·횡단보도 관측을 CORE에 전달하지 않았다. 실물 NOMINAL 또는 GAZEBO로 출처를 바꾸면 검증되지 않은 실물/다른 시뮬레이터의 오차 근거를 잘못 사용하게 된다.

## 결정

기존 strict `LaneContainmentEvidence.ground_source`에 ISAAC을 추가하고 API reference v1.210에 기록한다. envelope version은 기존 1.0을 유지한다. 기존 containment producer를 사용해 같은 이미지 stamp와 실제 keeper의 selected boundary, crosswalk extent를 전달한다. 검출기가 실행된 프레임의 crosswalk 오차는 기존 nullable 계약을 사용한다.

ISAAC에는 GAZEBO의 detector 2px 오차를 자동 부여하지 않는다. 승인된 projection/detection bounds가 없는 현재 연결의 uncertainty는 null이다. 빈/단일 경계, 검출기 미실행, unknown uncertainty는 안전 증거로 승격하지 않는다. 물리 카메라 node의 source 선택/opt-in과 실물 NOMINAL driver hold는 변경하지 않는다. invalid native 카메라는 기존 invalidate·명령 0·학습 제외를 유지한다. 경계 근거가 필요한 CORE 회복/횡단보도 receiver의 거절을 해제하지 않는다.

## 검증과 후속

shared producer/schema의 ISAAC 출처, finite selected boundary, detector가 돈 경우의 unknown crosswalk error, source별 geometry identity와 NOMINAL/GAZEBO 회귀를 시험한다. native 연결에서 원본 stamp 일치·CORE 전달·오차 null·invalid 뒤 학습 상태 없음도 시험한다. 실제 SDK 재실행·카메라 오차 검증·CORE/Fleet 회전 연결·차선 재획득·완주·교통·Gazebo 두 대·병렬 RL은 별도 증거가 필요하다. SOURCE 시험이 이를 대신하지 않는다.
