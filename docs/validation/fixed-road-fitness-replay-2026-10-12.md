# 고정 도로면·현재 구역 진단 파이프라인 검증

Branch: `feat/perception-fitness-pipeline`. 계약: D-659, D-663, D-665, D-666, D-667.

## 구현과 책임

모델은 전체 관측 도로면을 `drivable.semantic: road_surface/1`로 예측한다. 현재 구역은 별도 관측 기준점과 연결 영역 로직으로 산출한다. 목적지·통행 정책에 따른 경로 선택과 주행은 후속 책임이다. 기존 v13 검수 자료의 연결된 자기 도로 의미는 보존한다.

`rosy_ml fitness`는 두 immutable 사람 승인 eval set과 별도 관측 입력을 읽고 모델의 기존 preprocess/session을 실행한다. 정답은 추론 입력에 넣지 않는다. 모델/전처리·정답/승인·동일 원본 영상·source/group 예약·선언된 학습 참조를 확인하고 실행 후 content/file/manifest를 다시 확인한다. 오류는 정상 보고서를 만들지 않으며 기존 보고서를 덮어쓰지 않는다. 정상 실행은 항상 진단/HOLD다.

관측 형식과 순수 유효성 검사는 `core_common.observation`에 한 번만 구현한다. World 기존 API는 같은 객체를 재노출하고 학습은 운영 구현을 직접 참조하지 않는다. 서명 모델 코드 묶음은 재생기가 있으면 관측 계약 파일을 요구한다. Foundation 0.0.1과 World 0.1.1 최소 의존성, 전이된 exact pin과 CI·이미지 설치 pin을 함께 맞췄다.

## 확보한 실행 증거

| 범위 | 커밋 | 결과와 한계 |
|---|---|---|
| 고정 재생·관측 입력·승인·학습 분리 | `1905962030` | 원격 합성 20개 시험 terminal exit 0, NEW0. 실제 독립 정답 수용이 아니다 |
| 승인 hash/짝 영상 검사의 실효성 | `2a74dc6d8a` → `699b049d8a` | 두 검사를 제거하면 해당 2개 시험이 실패하며 복구 후 회귀 통과 |
| 공통 계약·World wheel·아키텍처·학습 호환 | `1a1313510e` | 원격 관련 시험 terminal exit 0, NEW0. 설치 wheel은 계약과 World의 객체 동일성 확인 |
| 새 패키지 의존 버전·signed archive·wheel/sdist·오프라인 이미지 설치 | `53ce017eb8` | 원격 관련 시험 terminal exit 0, NEW0. 실제 ARM64 이미지·장치 설치 증거가 아니다 |
| 별도 export CLI의 semantic 손실 재현 | `acdc9fdb4b` | 새 6개 시험 실패. YAML reader가 semantic을 버리는 원인 확인 |
| export reader 수정 후 writer/기존 전달 경계 | `c57b59c402` | 원격 training contract 시험 terminal exit 0, NEW0. 2개 ML 의존 시험은 제외이며 실제 모델 변환 실행 증거가 아니다 |

최신 main `53b45aafb4`를 통합한 `c41dfcb0aa`를 시험 PC에서 검사하고 local main에 fast-forward로 착지했다. 관련 회귀 세 묶음은 각각 9,494/4,206/3,699개 통과, 444/116/211개 제외이며 모두 terminal exit 0과 known-failure 비교 NEW0이다. 합계는 17,399개 통과, 771개 제외다. lint는 error 0, warning 27이다.

첫 통합 검사에서 발견한 신규 실패 세 가지는 시험 소유 경로, 문서 checksum 표기, Fleet initializer 버전 불일치였다. 모듈 시험 경로와 harness 등록, checksum 문맥, 패키지 버전 일치를 수정했고 예외 목록을 늘리지 않았다. 독립 소스 검토도 수정 후 추가 차단 사항이 없음을 확인했다.

selector가 FULL로 승격했지만 이번 실행은 guard와 mapped suite 범위다. 전체 CI tier는 미확인이다. 원격 원본 로그와 SHA256 receipt는 비공개 세션 artifact 위치에 보존한다. 이 착지는 push·장치 배포·실물 또는 시뮬레이션 성능 수용 증거가 아니다.

## 독립 소스 검토와 수정

독립 reviewer는 D-663 class/export/intake/delivery, D-665 구역·좌표·지표, D-666 재생과 D-667 계약·패키지를 읽었다. 초기 ‘이름이 다른 drivable의 의미 검사 우회’ 지적은 기존 helper가 drivable 이름의 합집합과 미확인 의미를 거절하는 소스·원격 시험으로 기각했고 회귀 사례를 남겼다.

중요 지적 두 가지를 수정했다. 같은 Foundation 버전으로 새 World 의존성을 충족시키던 문제는 새 버전과 전이 pin으로 해결했다. 별도 ONNX CLI reader의 의미 손실은 공유 reader에서 optional semantic을 보존하도록 수정했다. convert와 lane NCNN export도 같은 reader를 사용한다. 검토는 소스 검토이며 실행·배포·현장 증거가 아니다.

## 미확인과 다음 단계

### 기존 소비자의 의미 혼용 경계 보완

후속 런타임 조사에서 전달 도구를 거치지 않은 직접 로드와 pointer 변경은 전체 도로면 모델을 기존 lane evidence/paint/drivable 후처리에 사용할 수 있음을 확인했다. `0667921ce4`의 원격 RED 8건은 추론 전 거절 누락, `514b41d743`의 RED 2건은 교체 시 이전 모델 유지 누락을 재현했다. manifest의 기존 의미 helper를 전달·intake와 런타임이 공유하고 후처리 전에 검사하며, ModelSlot은 호환되지 않은 lane 후보를 거절해 이전 모델을 유지한다. 원시 session 로드는 오프라인 도로면 평가에 계속 사용할 수 있다.

`804bcdc80e`에서 거절한 후보의 서명 상태가 이전 모델 상태를 덮는 RED 2건도 재현했다. `SignatureCheck`가 의미 검사 뒤에만 서명 상태를 갱신하도록 수정했다. `0abc58f999`의 원격 runner/signature/object detector/고정 fitness/training contract 회귀는 terminal exit 0이다. 실제 관측 consumer·장치 전달을 구현하거나 배포한 증거는 아니다.

20261010 검수 데이터는 기존 연결 도로 구역 기준선 자료다. 전체 도로면의 독립 정답으로 재해석하지 않는다. 전체 도로면과 현재 구역의 실제/시뮬레이션 독립 정답 pair, 실제 관측 기준점 생산/보정·출처, 검수 독립성·freshness와 upstream 학습 closure가 필요하다.

### 정답 없는 관측 산출 경계

D-670은 정답·목적지·통행 정책 없이 기존 모델 세션과 D-665/D-667 로직을 실행하는 내부 관측 함수를 정의한다. 도로면/현재 구역 mask, 두 snapshot ID, 로드한 모델·camera profile·전처리·crop/기준점 변환과 추론 구간 latency를 반환한다. image 무효·오래됨·미래는 추론 전 보류하며 anchor만 무효면 도로면은 유지하고 구역을 보류한다. 반환 판단은 항상 HOLD이고 transport·장치 consumer는 아직 연결하지 않았다.

`609df1bf06`의 원격 RED 14건으로 새 경계의 미구현을 확인했다. 첫 두 실행은 fixture의 crop 형식과 필수 lane class 오류로 실패했으므로 경계 RED 근거로 사용하지 않는다. `fae7bdf1d8`의 RED 1건은 anchor의 image-reference 누락이 유효한 도로면까지 보류하던 기존 평가 문제를 재현했다. `b5565a104b`의 원격 관련 GREEN은 terminal exit 0, NEW0이며 별도 ONNX Runtime 실행에서도 기존 crop/전체 영상 시험 2개를 포함한 68개 시험이 통과했다. 이는 합성 모델 실행이며 실물 인지 수용이 아니다.

설치 closure 검토 지적은 control 0.1.1과 Foundation 최소 0.0.1 의존 선언으로 수정했다. `db1eb3058b`의 설치 metadata RED 뒤 `dc3148cdde`의 sdist→wheel·Foundation wheel 설치·격리 import 및 관련 회귀가 terminal exit 0이다. Foundation source 경로를 import에 넣지 않고 설치본만으로 새 관측 함수와 공통 타입을 읽었다. 실제 ARM64 이미지 또는 장치 설치는 미확인이다.

물체 평가, 조건별 최소 표본·coverage와 출처 단위 불확실성, 사전 고정 수용 임계값, 실제 장치의 관측 전용 전달·버전 readback·지연/손실도 미확인이다. 이 작업에서 push·장치 배포·운영 활성화·주행·실물/시뮬레이션 성능 수용을 수행하지 않았다. SOURCE 시험과 local main 착지를 이 단계의 수용으로 확대하지 않는다.
