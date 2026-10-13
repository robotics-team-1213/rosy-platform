# 직선·곡선 관측과 카메라 소실 경로 유지 조사

> 조사: 2026-10-12. B 실험 commit: `4e7aad086` (`fix/isaac-held-path`). 일차 자료 조사와 원격 통합 시험을 구분해 기록한다. Isaac 재실행·장치 수용의 결과가 아니다. D-615의 계약을 바꾸지 않는다.

## 판단

이전 관측을 이동량으로 보정하여 짧은 소실을 잇는 방향은 타당하다. 그러나 현재 `ExpectedPath`는 **직선으로 확인한 차선의 접선**을 기억한다고 보기 어렵다. `drivable_centre`는 중심 추종 전략이고 곡선에서도 나올 수 있으며, 저장 heading은 중심점의 방위각이다. 이 상태로 CORE에 held 관측을 허용하는 B안을 일반 채택하면 곡선을 직선으로 연장할 수 있다. A안의 엄격한 정지는 진행성을 제한하지만, B안은 직선 자격과 공백 예산을 입증한 범위에서만 비교해야 한다.

기억할 대상은 차선의 기하와 관측 시각이다. 직전 회전 명령은 로봇의 횡오차·heading 오차를 함께 보정한 출력이므로, 그것을 오래 유지하는 것으로 차선 추세를 대신할 수 없다. `DrivableSteer.reset()`의 조향 평활 이력 초기화와 `ExpectedPath`의 명시적 경로 기억은 별개의 계약이다.

## 실제 A/B 원격 시험과 결정

시험은 같은 GroundPlane의 합성 drivable mask, 기존 LearnedPaintWorker·LaneKeeper·DrivableSteer·ExpectedPath·CORE LineFollowManager·camera_tick을 통과했다. ONNX 모델 정확도나 실제 차량 물리 시험은 아니다. 첫 영상 전 odom 표본을 준비해 독립 관측 3회의 확정과 2회의 미확정을 구분했다.

| 입력 | A: 현행 목표 소실 정지 | B: expected_path_held 허용 |
|---|---|---|
| 직선 독립 관측 2회 뒤 공백 | zero | zero |
| 직선 독립 관측 3회 뒤 공백, odom 위치/yaw 이동 | zero | 양의 선속도 및 오돔 이동에 맞는 우측 보정; RL state는 None |
| 반경 1 m 곡선 관측 3회 뒤 공백 | zero | 선속도 0.033846153846m/s, 각속도 0: 곡선을 직선으로 연장 |

B `4e7aad086`의 AI PC 검증은 22 cores·9.0 GB 유효 floor에서 2 PASS·1 FAIL이다. 실패는 곡선 뒤 zero를 요구한 negative control이며 실제 양의 선속도 때문에 실패했다. A `53ccf7564`의 모델 PC 검증은 22 cores·9.0 GB에서 84 PASS·NEW 0이다. 두 로그는 관리 세션 `X:/DevTemp/projects/rosy-platform/2026-10-12--103052--isaac-held-path--90cf61/logs/{curve-control,option-a-corrected}/run-1.txt`에 있다. 초기 B 시험 일부는 runner의 floor 미달 fallback을 사용했으므로 수용 근거에서 제외한다.

결정: 이번에는 A를 유지한다. B는 직선 공백을 잇는 진행성은 보였지만 곡선 대조군을 통과하지 못했다. B의 5줄 pilot wiring은 되돌렸고 상수나 안전 gate를 완화하지 않았다. 일반 채택 대신 직선 자격의 기하학적 증명과 곡선 형상의 odom 보존을 후속 대상으로 남긴다. R29의 최초 camera_lane_lost 해결이나 완주는 입증하지 않았다.

## 현재 코드에서 확인한 것

근거 소스는 [expected_path.py](../../middleware/perception/vision/perception/learned/expected_path.py), [drivable_steer.py](../../middleware/perception/vision/perception/drivable/drivable_steer.py), [drivable_keep.py](../../middleware/perception/vision/perception/drivable/drivable_keep.py), [test_expected_path.py](../../middleware/perception/test/test_expected_path.py), [D-615](../adr/D-615-expected-path-hold.md)다.

| 항목 | 확인한 동작 | 의미 |
|---|---|---|
| 현재 보이는 길 | `way_target()`이 행마다 투영한 좌우 경계의 중심을 만들고 `_centre_target()`으로 목표를 고름 | 직선과 곡선 모두 중심 추종 가능 |
| 실제 현재 조향 | 몸 좌표 목표 `(tx, ty)`에서 `2*ty/(tx²+ty²)`를 계산하고 0.5 평활 | 이것은 추종 명령 곡률이며 차선 자체 곡률과 동일하지 않음 |
| 직선 자격 | `_centre_heading()`은 strategy가 `drivable_centre`이고 금지 사유가 없으면 허용 | 기하학적 직선 residual·접선 변화 검증이 없음 |
| 저장 heading | `pose.yaw + atan2(near.y, near.x)` | 가까운 점의 방위각을 접선으로 취급 |
| 확정 | 3개의 독립 관측이 첫 heading의 12° 이내 | 짧은 시간 동안 완만한 곡선도 이 조건을 만족할 수 있음 |
| 공백 출력 | odom에 저장한 anchor와 heading의 직선 위에서 투영점 + 0.10 m를 목표로 함 | 저장 형상은 곡선을 표현하지 못함 |
| 중단 조건 | pivot/turn/off-line/crosswalk/straddle/closed 등은 즉시 폐기 | 명시적 금지 전략의 우선권은 있음 |
| 예산 | `hold()`에서 구간 길이·0.25 m·2.5 s를 검사 | 시간과 이동은 첫 `hold()`부터이며 실제 마지막 카메라 관측부터가 아님 |
| 이동량 | 첫 소실 pose와 현재 pose의 유클리드 거리 | 누적 주행거리보다 작을 수 있음 |
| 새 관측 불일치 | heading이 기존 값보다 12° 이상 다르면 3프레임 후 교체 | 이전 가설을 유지하는 debug 출력과 현재 steering 출력을 구별해야 함 |

### 직선에서도 방위각과 접선은 다르다

차선이 몸 앞 `x` 방향과 평행하지만 로봇이 중심에서 0.03 m 벗어나 가까운 중심점이 `(0.20, 0.03)`이면, 실제 직선 접선은 0°다. 현재 저장값은 `atan2(0.03, 0.20) ≈ 8.53°`다. 이는 소스 수식으로 확인되는 기하학적 반례이며 실행 시험 결과는 아니다. 같은 점으로 pure pursuit의 제어 곡률을 구하면 약 `1.467 m⁻¹`다. 둘 다 로봇이 중심에 복귀하기 위한 오차를 담지만 **도로가 그만큼 굽었다는 뜻은 아니다**.

실제 직선 여부는 여러 차선 중심점의 방향·직선 fit residual로 판단해야 한다. 직선의 평행 이동은 접선을 바꾸지 않아야 한다. 여러 프레임의 몸 좌표 방위각이 안정적이라는 사실만으로 도로 직선성을 입증하지 못한다.

### 예산과 좌표계의 주의점

`keep_step()`은 source pose를 `pose_at(way_stamp)`로 얻어 저장하고, 공백에서 현재 pose를 이용해 odom 경로를 몸 좌표로 옮긴다. 이 구조는 이미지 픽셀을 고정하는 방식보다 적절하다. 다만 `latest_way(WAY_MAX_AGE_S)`가 기존 추론을 최대 1.5 s 재사용하는 동안에는 `hold()`가 시작하지 않는다. 따라서 2.5 s는 마지막 실제 관측 시각으로부터의 총 경과 상한이 아니다. 같은 inference를 재사용하는 경우의 시간과 pose 변화는 별도로 시험해야 한다.

`ExpectedPath.update()`는 heading이 없거나 새 heading의 교체를 기다릴 때 `_steer(..., 'held')`를 직접 반환한다. 이 경로는 `hold()`의 거리·시간 검사를 호출하지 않는다. 현재 fresh-way `keep_step()`은 이 반환을 debug 기억에만 쓰고 실제 명령은 `steer.update()`의 출력을 쓰므로, 이 사실만으로 현행 명령의 예산 우회라고 단정할 수 없다. 다른 소비자나 이후 wiring이 이 결과를 곧바로 제어에 쓰면 문제가 된다.

`_jumped()`는 시간 역행과 0.25 m 초과 위치 점프를 감지한다. 이 클래스 자체에는 yaw reset, 비정상 수치, odom frame 교체를 명시적으로 검증하는 분기가 없다. 상위 입력 경계가 보증하는지 확인해야 하며, 확인 전에는 이 클래스를 단독 안전 경계로 취급하지 않는다.

## 일차 자료가 지지하는 원리

### Pure pursuit: 목표점과 경로 접선은 서로 다르다

Coulter의 원문은 현재 pose에서 경로상의 lookahead 목표를 고르고 그 목표에 도달하는 원호를 계산한다. 긴 lookahead는 복귀를 완만하게 하지만 굽은 경로의 추종 오차를 늘릴 수 있으며, 제어기는 차량·액추에이터 동특성을 직접 모델링하지 않는다. 이것은 목표점의 방위각이 차선 접선이라는 근거가 아니다. [CMU 원문, §2–4](https://publications.ri.cmu.edu/storage/publications/pub_files/pub3/coulter_r_craig_1992_1/coulter_r_craig_1992_1.pdf).

Nav2 Jazzy는 경로를 현재 로봇 좌표로 변환하고 목표점에서 `2*y/(x²+y²)`를 계산한다. 속도에 따른 lookahead, 곡률·장애물에 따른 감속, 명령 원호의 충돌 검사도 제공한다. collision horizon은 시간과 carrot 거리로 제한된다. ROSY에 같은 패키지를 추가하자는 제안이 아니라, **경로 기억·추종 출력·현재 충돌 검사를 분리하는 원리**의 근거다. [Jazzy 소스](https://raw.githubusercontent.com/ros-navigation/navigation2/jazzy/nav2_regulated_pure_pursuit_controller/src/regulated_pure_pursuit_controller.cpp), [Jazzy 공식 설정](https://docs.nav2.org/jazzy/configuration_and_development/configuration_guide/controller_plugins/configuring_regulated_pp/).

### 여러 프레임을 쓰되 움직임과 소실 원인을 고려한다

RVLD는 이전 프레임의 lane 결과와 feature를 motion field로 현재 프레임에 맞춘 후 새 feature를 정제한다. 재귀 기억은 오래된 출력 좌표를 그대로 복사하는 방식과 다르다. ROSY의 odom transform은 비슷한 목적의 결정론적 구현이지만, 영상 motion field와 같은 정보를 제공한다고 볼 수 없다. [저자 연구실 원문 소개와 논문 링크](https://mcl.korea.ac.kr/~dkjin/iccv2023/index.html), [논문](https://arxiv.org/abs/2308.11106).

OMR은 현재 영상, 이전 lane 출력과 feature, occlusion mask, 메모리를 함께 사용한다. 기억으로 가려진 부분을 복원하는 원리지만, 차선이 사라졌다는 사실만으로 공간이 비었다고 가정하지 않는다. 논문의 영상 검출 성능은 ROSY의 주행 안전이나 CORE 액추에이션을 증명하지 않는다. [ECCV 2024 원문, §3.3–3.4](https://www.ecva.net/papers/eccv_2024/papers_ECCV/papers/04822.pdf).

## A/B 비교에 포함할 판정

| 장면 | A: 현재 엄격한 정지 | B: 제한된 odom expected path | 필요한 증거 |
|---|---|---|---|
| 중심 정렬 직선의 짧은 소실 | 진행성 손실 측정 | 예산 내 연장 후보 | 횡편차, 실제 마지막 관측 age, 정지 거리 |
| 횡오프셋이 있는 평행 직선 | 정지 후 재획득 | 현재 bearing heading 오염 가능 | 동일 접선·서로 다른 횡오프셋에서 저장 heading 불변 여부 |
| 완만한 곡선·곡선 진입 | 정지 | 현행 직선 모델의 코너 절단 가능 | 실제 curved way가 `drivable_centre`로 확정되는지, 경계 침범량 |
| 새 경계·장애물이 이전 기억과 충돌 | 신선한 제약으로 정지 | 기억보다 신선한 제약을 우선해 중단해야 함 | held admission이 새로운 safety refusal을 지우지 않는지 |
| 카메라 전체 미갱신과 segmentation 한 프레임 누락 | 각각 실패 원인을 기록 | 두 경우에 같은 무조건 연장 적용 금지 | 원본 camera timestamp와 inference timestamp를 분리한 기록 |
| 곡선 주행·왕복·odom reset | 기존 safety 검사 유지 | 누적 거리·yaw/frame 연속성이 추가로 필요 | chord가 작은데 실제 travel이 큰 경우, reset 후 가설 폐기 |

두 안 모두 같은 fixture, 같은 초기 odom 준비 상태, 같은 관측 시각으로 비교한다. 진행량만 비교하면 잘못된 방향으로 전진한 B가 유리해지므로, 경계 침범·heading/횡오차·현재 제약 거절·예산 초과를 먼저 판정한다. 관련 원격 회귀 통과 뒤 Isaac 시계열 readback을 별도 증거로 남긴다. RL fallback 또는 resource floor 미달 실행은 이 판정의 수용 증거가 아니다.

## 최소 후속 방향

이번 합성 곡선 반례를 유지하고 평행 직선 횡오프셋 사례를 더한다. D-615의 직선 자격을 기하로 입증할 때까지 A를 유지한다. 원래 방향인 경로 기억은 유지하되 직전 명령의 평활 이력과 혼동하지 않는다.

곡선 기억이 필요하다는 판정이 나오면 기존 `way_target()`에서 이미 계산하는 여러 중심점을 odom에 옮겨 제한된 관측 구간을 기억하는 방식을 먼저 검토한다. 새 모델·학습 파이프라인은 필요하지 않다. 형상의 신뢰가 부족하면 그 틱은 연장하지 않고, 소실 시간·실제 누적 거리·남은 관측 구간·경계 여유 중 먼저 소진되는 조건에서 중단한다. 이 문서는 새 임계값을 확정하지 않는다.

문헌 조사 세션은 시험을 수행하지 않았으며, 위 원격 비교 시험은 구현 세션에서 수행했다. Isaac 재실행은 하지 않았다. B의 직선 자격, 총 소실 예산, 현재 경계 우선권이 확인되기 전에는 주행 수용으로 간주할 수 없다.
