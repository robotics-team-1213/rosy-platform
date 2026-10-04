# Pinky 인식 클래스 개선 설계

사용자 요청: 벽·신호등·장애물 및 외부 pinky-lane-segmentation 학습 코드를 반영한다.
현재 데이터에서 검증 가능한 클래스와 추가 수집이 필요한 클래스를 구분한다.

## 클래스와 라벨 단위

| 대상 | 라벨 단위 | 현재 계약 / 개선 |
|---|---|---|
| 바닥·차선·벽·주행영역·정지선·횡단보도 | 픽셀 mask | lane_seg. wall 역할은 수정 완료. 현재 crosswalk는 ignore 역할이므로 도로 의미 활성화는 후속 계약 검토 |
| 다른 로봇 | 물체 box | object_det의 robot |
| 상자·콘 | 물체 box | obstacle_box / cone |
| 신호등·표지판 | 물체 box | traffic_light / sign |
| 사람 발 | 물체 box | person_feet. 전신 사람 검출로 해석하지 않음 |
| 신호등 색 | 검출 ROI와 시간별 상태 라벨 | 적색·황색·녹색·소등·미확인 후보. 가림·작은 ROI·반사·여러 신호 충돌도 라벨링 |
| 차량·전신 사람·기타 장애물 | 추가 물체 라벨 후보 | 현행 object_det의 고정 6-class 목록 밖. 장면에서 존재를 확인한 뒤 별도 모델 profile/ADR로 확장 |
| 이름을 모르는 장애물 | LiDAR 점유·거리 근거 | 이름을 못 맞춰도 공간 근거는 유지. 물체 이름과 충돌 가능성을 같은 판단으로 취급하지 않음 |

기존 object_det 클래스 순서는 robot, obstacle_box, cone, traffic_light, sign,
person_feet이며 manifest가 정확한 목록을 요구한다. 이름만 추가해 기존 모델을
호환된 것으로 표시하지 않는다. 신호 상태는 TrafficSignalObservation과 연계할
후속 설계 대상이며 이번 학습 recipe 변경으로 제어 권한을 추가하지 않는다.

외부 모델의 lane_left/lane_right를 합쳐 lane_marking으로 활용하려면 원본 mask가
필요하다. 현행 단일 lane_line에서 좌우 정답을 생성하거나 background에서
과속방지턱 정답을 추측하지 않는다. 클래스 index/role 변경은 새 dataset/model 버전이다.

## 데이터와 평가

1. 기존 녹화에서 대상 존재·크기·가림·거리·조명과 세션별 클래스 픽셀/box 수를 집계한다.
2. LiDAR box는 후보 영역만 제공한다. 자동 후보에 물체 이름이나 신호 색 정답을 붙이지 않는다.
3. 사람이 확인한 box/ROI 상태·도로 mask를 immutable 데이터 버전으로 만든다.
4. 주행/촬영 세션으로 train/val/고정 평가를 분리하고 클래스별 미관측을 기록한다.
5. 도로는 클래스별 IoU, 물체는 precision/recall 및 작은 물체 누락,
   신호는 색 confusion·미확인·충돌·시간 지연을 각각 측정한다.
6. base16 기준/개선 recipe와 base8 소형 모델의 정확도·CPU 지연·크기를 같은 데이터로 비교한다.

신호등이 녹색이라는 예측은 단독으로 주행 허가가 아니다. 최종 동작 판단은 기존 CORE
owner와 Safety Guard 계약을 따른다. 장치 성능과 제동/정지 수용은 별도 증거다.

## 기존 결정과 관계

| 결정 | 관계 |
|---|---|
| D-423 | 현행 object_det 6-class와 서명·증거 계약을 유지; 클래스 확장은 별도 계약 결정 |
| D-427 | training/perception 목표 경로에만 학습 코드 추가, 외부 저장소는 scratch에서 조사 |
| D-429 | 구조 이동 없음 |
| D-430 | runtime safety 경로 수정 없음; 학습 코드가 최종 cmd_vel을 발행하지 않음 |

현재 630프레임은 floor/lane/wall/drivable 근거를 포함하며 stop_line/crosswalk와
새 물체·신호 상태의 충분한 학습/평가 라벨은 확인되지 않았다.
클래스 이름을 설계한 것과 해당 클래스의 인식 모델을 학습·수용한 것은 구분한다.
