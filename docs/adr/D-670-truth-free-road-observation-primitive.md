## D-670 정답과 주행 정책 없이 도로면·현재 구역 관측을 산출한다

**Status:** Accepted (2026-10-12, D-659 관측 전용 전달의 내부 산출 경계). 범위는 ROS-free 관측 함수와 평가의 공통 추론이며 외부 API·토픽·슬롯·운영 consumer 활성화는 별도다.

### Context

D-666은 독립 정답과 관측 입력을 분리해 고정 모델을 평가한다. D-663의 기존 shadow/paint 출력은 조향 후처리이므로 전체 도로면을 그 슬롯에 전달할 수 없다. 장치 관측 전용 consumer를 연결하기 전에 정답 없이 같은 모델·전처리·구역 로직을 실행하는 산출 경계가 필요하다.

### Decision

1. `LaneSegModel.infer_road_surface`는 검증된 lane_seg 모델에서 명시적인 단일 `road_surface/1` 클래스만 허용한다. 원본 uint8 BGR 영상과 기존 preprocess/session으로 원시 class labels를 산출한다. 출력은 resize된 전체 카메라 grid이고 crop 밖은 255다. legacy lane/paint 후처리를 호출하지 않는다. 잘못된 입력·의미·logit shape/비유한 값은 거절한다.
2. `road_observation.observe_model_frame`은 모델·영상·D-667 image/anchor snapshot·원본 영상 grid의 정수 기준점·현재 시각/최대 나이만 받는다. 정답, 목적지, 통행 정책은 입력에 없다. 기존 D-665 유효성 검사와 연결 구역 로직을 사용한다. image 무효/미래/오래됨은 추론하지 않고 도로면도 보류한다. anchor·frame·calibration·transform·image reference 문제는 현재 구역을 보류하되 유효 영상의 도로면은 관측할 수 있다.
3. 반환값은 내부 Python mapping이며 numpy labels/도로면/현재 구역 mask, 구역 사유와 입력 오류, 두 snapshot ID, 실제 로드한 model revision/camera profile revision/input 전처리, 원본·예측 grid와 crop 행, 모델 추론 지연을 포함한다. 원본 기준점은 픽셀 중심 기준으로 예측 grid에 매핑한다. 경계 밖 기준점을 중앙/최대 영역으로 보충하지 않는다. model camera profile revision과 snapshot calibration revision은 서로 다른 계보이며 동일성·물리 보정이 검증됐다고 추정하지 않는다.
4. 반환 판단은 항상 진단/HOLD다. infer latency는 모델 추론 구간이며 촬영부터 전달까지 지연이나 프레임 손실을 뜻하지 않는다. 함수는 네트워크·파일 전달·pointer 변경·주행 명령을 수행하지 않는다. 운영 연결에는 별도 consumer/전달·버전 readback·clock alignment·지연/손실·장치 증거가 필요하다.
5. D-666 모델 평가도 같은 원시 추론 함수를 사용한다. 원본 정답 검증은 resize 전에 수행하며 ROI 제외 분모와 실물/시뮬레이션 분리는 유지한다. 기존 legacy 추론과 전달의 거절 조건을 완화하지 않는다.
6. 관측 함수가 필요한 `core_common.observation`은 Foundation 0.0.1부터 제공된다. control 배포물/ROS package를 0.1.1로 맞추고 Python dependency와 ROS exec dependency에 `core_common>=0.0.1` 최소 버전을 명시한다. sdist에서 만든 wheel과 설치된 Foundation만으로 관측 import와 metadata를 검증한다.
7. D-155 contract surface에는 D-667의 순수 공통 `core_common.observation` 모듈을 정확히 포함한다. 모든 Foundation 모듈이나 운영 CORE 구현의 import를 허용하지 않는다.

### Verification and consequences

원격 시험은 crop 밖 255, 원본 기준점 변환, 전체 도로와 현재 구역 분리, 무효 image 추론 금지, 무효 anchor 구역 보류, 의미/비유한 logits 거절, 기존 평가 지표와 legacy 거절 유지에 대해 RED/GREEN을 확인한다. source·합성 시험은 독립 정답, 실제 기준점 투영/보정·관측 producer, 장치 전달 및 인지 성능 수용의 증거가 아니다.

새 segmentation head·서비스·의존성은 추가하지 않는다. 장치 소비 코드가 정답을 필요로 하지 않는 공통 추론 경계를 재사용할 수 있으며 실제 운영 연결은 아직 구현됐다고 주장하지 않는다.

**Related:** D-659, D-663, D-665, D-666, D-667.
