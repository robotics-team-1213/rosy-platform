# Pinky 선택 경로 연결점 거리 안내 설계

상태: 사용자 승인 후 feasibility 단계에서 **NO-GO**. 실패 장면의 현재 관측으로 연결점을 입증할 수 없어 이 설계의 새 제품 계약은 구현하지 않았다. 후속 후보와 실제 실패 결과는 [검증 기록](../validation/pinky-junction-feasibility-2026-10-20/result.md)을 따른다. 아래 내용은 제안된 설계이며 운영 계약이 아니다.

## 문제와 근거

현재 후보의 같은 소스·모델 반복 주행은 1회 성공, 1회 실패다. 실패에서는 제한된 왼쪽 정렬 뒤에도 다음 오른쪽 코너를 통과하지 못했고, perception의 `realign` 판단이 관측 소실과 CORE HOLD/LOST로 이어졌다. 정확한 소스·모델·장면·시험 결과는 [동결된 검증 기록](../validation/pinky-corner-lifetime-2026-10-19/result.md)이 소유한다.

실패 직전 안내의 경로 누적 거리는 약 3.4163 m, 선택된 다음 연결점은 약 3.4447 m로 차이는 약 0.0284 m였다. 현재 안내는 현재 방향·미리 본 방향·누적 거리만 전달한다. 미리 본 방향이 현재 굽은 통로에 속하는지 다음 연결점 이후에 속하는지 소비자가 구분하기 어렵다. 연결점 거리 안내가 판단을 개선한다는 것은 검증할 가설이다. 지도·모델·실제 관측 중 어느 것이 틀렸는지는 확정하지 않는다.

목표는 선택된 다음 연결점까지의 거리를 동일한 관측 기준으로 전달하고, 그 연결점에서 관측으로 입증된 조향 후보를 잘못된 재중앙화로 억제하는지를 검증하는 것이다. 자동 trip REALIGN, 모델 교체, 지도 수정, 정지 조건 완화는 이 설계에 포함하지 않는다.

## 기존 경계와 재사용

| 책임 | 기준 코드와 유지할 경계 |
|---|---|
| Fleet 경로 기하 | `operations/fleet/fleet/routing/direction.py::route_direction`의 선택된 연속 directed arc와 부분 목적지 처리를 재사용한다. 최근접 다른 차선으로 갈아타지 않는다. |
| Fleet 관측 결합 | `operations/fleet/fleet/traffic/route_guide.py`의 지도 revision·LOCALIZED pose·authority odom stamp·수명 검증을 그대로 거친다. |
| 기존 bend hint | `operations/fleet/fleet/server/trips/trip_geometry.py::bend_candidate`는 현재 edge 안의 굽음에 대한 읽기 전용 진단이다. 다음 edge 연결점 안내로 재해석하지 않는다. |
| CORE | 선택 authority와 결합한 prior만 카메라에 전달한다. 최종 이동 명령, clearance, HOLD/LOST 및 재선택은 CORE가 결정한다. |
| perception | 현재 관측의 연결된 통로와 기존 제한된 정렬 예산을 사용한다. 지도 정보는 관측된 후보 선택의 근거만 보탠다. |

`SelectedRoutePrior.pivot_ok`는 계속 `Literal[False]`다. perception의 `realign`은 Fleet 복구 요청이 아니다. D-622에 따른 `trip_realign_unproved` 거절과 정지 후 사람 인계 경계는 유지한다.

## 제안하는 계약

다음 내용은 구현 시 API reference·관련 ADR·스키마에 함께 반영할 **제안**이다. 이 문서만으로 현행 프로토콜에 필드를 추가하지 않는다. 번호·API 버전은 구현 직전에 정식 도구로 예약한다.

`AuthorityRouteGuide`와 `SelectedRoutePrior`에 선택적 `next_junction` 객체를 추가한다. 기본값은 `None`이며, 객체의 필드는 모두 함께 있어야 한다.

| 필드 | 의미와 검증 |
|---|---|
| `segment_index` | 현재 선택 segment의 0 이상 정수 인덱스. bool은 거절한다. 이 segment 끝에서 다음 segment로 넘어가는 연결점이다. |
| `s_m` | 기존 guide `s_m`와 같은 누적 거리 원점에서 계산한 연결점 station. 유한한 0 이상 수이며 생성 시 현재 station 이상이어야 한다. |
| `heading_after_deg` | 선택된 다음 directed arc 시작 접선의 방향. 같은 authority pose yaw 기준 상대각, 유한한 [-180, 180]도다. |

객체는 외부 필드를 거절하고 불변으로 다룬다. 지도·leg·authority sequence·source stamp는 바깥 prior의 결합을 공유한다. 이 정보가 다른 trip/leg에 재사용되지 않도록 기존 문맥이 바뀌면 prior와 소비자 상태를 함께 폐기한다. 같은 leg 안에서는 `(segment_index, s_m)`로 같은 연결점을 식별한다.

별도 `distance_m`는 보내지 않는다. 수신 시 잔여 거리는 `next_junction.s_m - current_s_m`로 계산해 두 거리 필드의 불일치를 피한다. 단순 시간×명령 속도로 거리를 갱신하지 않는다.

## 생성과 전달

1. Fleet은 현재 segment의 선택된 `s_to`까지 거리에 이전 선택 segment 길이를 더해 연결점 station을 구한다. 기존 네 자리 station 반올림 허용 범위를 재사용한다.
2. 현재 segment가 실제 arc 끝까지 가고, 다음 선택 segment가 lane 모드의 시작 station 0에서 시작하며, place와 polyline endpoint가 연속일 때만 객체를 만든다. 부분 목적지, 마지막 segment, free-space 전환, 불연속 경로에는 `None`을 보낸다. 왼쪽/오른쪽 임계각으로 새로운 회전점을 탐색하지 않는다.
3. 다음 arc 시작 접선을 현재 guide와 같은 pose yaw 기준으로 변환한다. 다음 edge가 직진이어도 연결점 사실은 보낼 수 있다. 소비자는 연결점이라는 이유만으로 회전하지 않는다.
4. 기존 guide의 freshness·선택 authority 문맥 검증이 실패하면 기존 규칙대로 guide 자체를 무효화한다. next_junction만 다른 pose나 오래된 trip view에서 조립하지 않는다.
5. CORE authority 입력, 선택 prior 복사, gateway publish, 카메라 입력 및 source→current pose 보정까지 객체가 손실 없이 전달되는지를 각각 검증한다. source→current 변환은 기존 here/ahead 각도와 같은 yaw 변화량을 적용한다. 현재 keeper의 source/current 위치 직선 거리는 곡선의 경로 station 증가량이 아니므로 `current_s_m` 보정에 그대로 사용하지 않는다.

실행 계획을 승인하기 전에 선택 경로에 대한 current pose 투영 방법과 오차 범위, 관측된 연결 통로의 누적 길이와 비교하는 방법을 확정해야 한다. 유효한 투영에 필요한 경로 기하가 소비자에게 없다면 그 전달 계약까지 먼저 설계·검토한다. 새 API를 임의로 만들거나 직선 이동량으로 대체하지 않는다. 잔여 거리의 오차 구간 전체가 0 이상이고 관측 경로 길이의 보수적 하한 이내일 때만 연결점이 도달 범위 안이라고 판단한다. 오차 때문에 연결점 전후 또는 관측 범위 안팎을 구분할 수 없으면 새 분기를 비활성화한다. 이 보정 증거가 준비되지 않으면 후보 선택 구현을 시작하지 않는다.

## 소비자 동작과 중단 기준

새 안내는 `drivable_steer.py`의 미래 방향과 반대인 재중앙화 후보를 우선하는 결정에만 적용한다. 다음 연결점이 현재 관측으로 연결된 통로의 도달 범위 안에 있고, 그 통로에서 선택한 출구 방향이 `heading_after_deg`와 기존 방향 일치 허용 범위 안에 있을 때, 그 출구를 단순한 미래 굽음으로 취급해 반대 재중앙화로 덮어쓰지 않는다. 기존 출구 검출·방향 일치·통로 연결성 기준을 공유하며 새로운 넓은 각도 허용치는 만들지 않는다.

지도에 맞추기 위해 출구·통로·전방 가시 거리를 합성하지 않는다. 회전 후보가 관측으로 성립하지 않으면 기존 HOLD/관측 소실 경로를 따른다. 이 분기는 기존 zero-linear 정렬이나 관측 기반 조향 후보만 선택하며, 지도 거리만으로 전진 또는 pivot을 허가하지 않는다. 기존 정렬 총각도·횟수·수명 예산을 늘리거나 재충전하지 않는다.

아래 경우 새 분기는 비활성화한다. 기존 안전한 판단 또는 정지가 그대로 적용되며, 실패를 강제로 성공 처리하지 않는다.

- 안내/pose가 만료되었거나 지도·leg·authority 문맥이 다르다.
- 연결점 station을 지났거나 segment 식별이 바뀌었다. 지난 연결점을 0 m로 고정하지 않는다.
- current station 보정이 불가능하거나 뒤로 점프했다. 새 유효 문맥이 확인되기 전까지 누적 상태를 이어 쓰지 않는다.
- 관측된 통로 범위 밖, 통로 단절, 출구 방향 불일치, crosswalk/front-stop/CORE 차단 상태다.

동일 연결점의 새 메시지는 증거 갱신일 뿐 새 정렬 episode가 아니다. 연결점을 통과했다는 경로 진행과 기존 관측 기반 수명 종료 조건을 만족해야 다음 코너의 독립 상태로 넘어간다.

## 변경 범위와 배포

구현은 foundation 계약과 consumer 호환성 준비를 먼저 분리한다. `extra="forbid"`인 구버전 독자는 새 필드를 거절하므로 optional 추가만으로 혼합 버전 호환이 성립하지 않는다. 기본 `model_dump()`의 `next_junction: null`도 같은 문제를 일으킨다. 지원이 확인되기 전에는 모든 전달 단계에서 필드 자체를 생략해야 한다. 객체 값만 `None`으로 만드는 것은 비활성화가 아니다. 우선 전체 수신자를 갱신하고, CORE·gateway·카메라의 스키마/복사/소비 지원이 확인된 동일 배포 묶음에서만 필드 송신을 활성화한다. 현재 capability가 이를 보장하지 못하면 필드 지원을 명시적으로 협상하는 계약 변경을 먼저 설계에 반영한다. 구버전 수신자 대상 출력에 키 자체가 없는 회귀 시험을 포함한다.

구체 실행 계획에는 foundation 스키마/시험, Fleet 기하/authority producer/시험, CORE authority→prior→publish, perception 입력·좌표 보정·후보 선택/캡처 회귀 시험, API reference/ADR, wheel·payload 의존 버전의 실제 경로를 열거한다. 새 일반 추상화나 별도 회전 상태 머신은 만들지 않는다. D-766 한도 95% 이상 파일에 추가할 경우 동작을 바꾸지 않는 분리 작업을 먼저 진행한다. foundation FULL 검사와 제품 관심사를 별도 착지 단위로 유지한다.

## 검증과 완료 조건

| 단계 | 필요한 증거 |
|---|---|
| 계약·기하 RED/GREEN | 누락 필드의 기존 동작, 원자적 객체 검증, NaN/bool/역전 station 거절, 역방향 arc, 부분 목적지, 직진 연결, 마지막 segment, 불연속/free-space 전환. 선택된 다음 edge 외의 방향을 쓰지 않음을 검증한다. |
| 전달·수명 | 같은 source stamp의 좌표와 각도 보정, map/leg/seq 교체, 만료, 지나간 연결점, 후진·station 점프, 필드 누락/구버전 처리. 같은 메시지 반복으로 정렬 예산이 초기화되지 않아야 한다. |
| 실패 장면 회귀 | 동결 기록의 정확한 source frame·pose·prior를 결합한 fixture에서 기존 실패를 먼저 재현한다. 새 안내 활성/비활성 비교로 목표 분기가 실제 달라졌음을 보이고, 반대 출구·보이지 않는 통로·만료 안내에서는 안전 조건이 유지됨을 검증한다. 저해상도 RLE 미리보기를 전체 마스크의 정확한 재생으로 간주하지 않는다. |
| native 원격 시험 | 커밋 SHA별 관련 및 affected 시험, 기존 실패 비교 NEW 0. FULL로 분류되는 계약 변경은 프로젝트의 FULL 게이트를 그대로 적용한다. |
| 같은 조건 Gazebo | 같은 소스·모델·지도·lap 조건으로 연속 2회 성공. 실패 회차를 보존하고 리셋하여 성공만 고르지 않는다. 목표 코너에서 새 분기의 실제 사용·통과, zero fallback, 최종 정지·lease 해제·프로세스 정리를 함께 확인한다. |

진단에는 연결점 식별, source/current station과 잔여 거리, 안내 유효성, 관측 도달 범위, 선택/거절 이유를 기존 debug 기록에 남긴다. 원본 영상 좌표와 현재 pose 좌표를 섞지 않는다. 새 분기가 실행되지 않은 성공만으로 가설을 채택하지 않는다. 연속 성공이 나와도 기존 `lane_return` 제외 범위와 실물·현장 미검증은 별도로 표시한다.

설계 승인 → 실제 producer/consumer 경로와 지원 협상을 확정한 실행 계획 검토 → RED/GREEN 구현 → 독립 안전 리뷰 → 원격 시험과 반복 SIM 순서로 진행한다. 반복 SIM 수용 전에는 파이프라인 주행 완성도를 HOLD로 유지한다. main 착지·push·실물 주행은 각각의 별도 승인 범위를 따른다.
