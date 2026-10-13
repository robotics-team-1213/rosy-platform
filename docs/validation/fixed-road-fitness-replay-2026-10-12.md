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

## 검수의 도로면 의미 보존

`be11481c27` 원격 RED 4건은 전체 도로면의 unknown 병합·indexed draft import에 자기 차선 제한이 적용되던 문제와 차선 전용 도구의 잘못된 입력 수용을 재현했다. `3cdbe9d244`에서 공통 검수는 명시적 `road_surface/1`에만 자기 차선 제한을 적용하지 않고, lane clipping/Qwen completion은 전체 도로면을 처리 전에 거절하도록 수정했다. 구형/현재 구역 제한과 검수 화소 불변, 255 및 pending/명시 승인·classes hash 결속은 유지한다.

관련 원격 회귀 56건은 terminal exit 0, NEW0이다. 추가하려던 bootstrap 시험 파일이 없는 첫 GREEN 호출은 collection exit 4였으므로 통과 근거에 포함하지 않았다. 교정한 기존 시험 경로로 GREEN을 확인했다. 합성 import/apply/approve 시험은 검수 기능의 증거이며 실제 독립 사람이 정답을 검수했다는 증거가 아니다. 기존 Desktop 원본·classes·검수 승인은 수정하지 않았다. 실제 도로면 정답·다른 자동 라벨 producer의 지원·장치 관측 전달은 여전히 별도다.

독립 소스 검토는 별도 whole-road 클래스가 현재 구역 클래스의 제한까지 해제하는 혼합 binding 문제를 지적했다. `59731df3a3`에서 RED 1건으로 재현한 뒤, 제한 해제를 해당 경계 검사가 대상으로 삼는 이름 `drivable` 클래스의 명시적 도로면 의미에만 적용하도록 좁혔다. 다른 이름의 도로면 클래스가 존재해도 기존 현재 구역 화소의 차선 제한은 유지한다.

## 모델 기반 초안의 의미 계보

`211ac02af6`의 원격 RED는 semantic 검사와 raw model classes 결속의 미구현을 확인했다. `57d7455c47`의 CLI RED는 현재 구역 모델에 도로면 YAML을 연결해도 exit 0으로 출력 디렉터리를 만들던 동작을 재현했다. 그 이전 CLI 실행은 불완전 fixture에서 AttributeError로 끝났으므로 CLI 동작 근거로 사용하지 않는다.

`b4ac3362a8`은 공통 prelabel 검사 및 prelabel/pixel draft job의 두 호출을 raw manifest에 결속한다. 독립 소스 검토에서 남은 blocker는 없었다. 수정 후 원격 GREEN 호출은 SSH 연결 단절로 exit 255였으며 시험 결과는 미확인이다. 원격 프로세스 상태 확인도 연결 timeout으로 완료하지 못했다. 이 기록 시점에는 회귀 통과·통합·local main 병합을 주장하지 않는다. 원본 로그는 X: 세션의 `logs/prelabel-*`에 있다.

## 연결 복구 후 착지와 관측 파일 증거

연결 복구 후 보존된 원격 통합 회귀 결과를 확인했다. prelabel 통합 회귀는 1,897 passed / 228 skipped, NEW 0이며 local main commit `abcab27ebf`에 착지했다. 앞 미확인 기록은 당시 상태이며 이 후속 결과와 구별한다. 연결이 끊긴 호출 자체의 결과를 확인했다는 뜻은 아니다.

D-673은 정답 없는 `rosy_ml observe`의 입력/model hash 결속, exclusive 파일 작성 및 hash·mask·중복 계보 readback을 연결한다. 링크 입력 거절, session 생성 전 예측 grid 제한, snapshot ID/hash 불일치와 입력 오류 시 구역 보류를 원격 RED/GREEN으로 확인했다. 실제 ONNX Runtime 합성 실행을 포함한 관련 시험 71건은 terminal exit 0이다. 독립 소스 검토에서 수정 후 merge blocker는 없었다.

최신 main 통합 회귀는 6,467 passed / 483 skipped / 33 warnings, terminal exit 0 및 known failures NEW 0이다. lint가 통과한 뒤 local main commit `9f31764332`에 착지했으며 push하지 않았다. 보존 로그는 비공개 세션 `logs/observe-integrated-green-9f31764332/run-1-1.txt`, source receipt는 `road-observation-artifact-landing-receipt.json`이다. 일반 통합 환경에서 제외된 ONNX dependency 사례의 실행 증거는 별도 실제 ONNX Runtime 시험에 있다.

## D-659 요구사항별 완료 감사 (2026-10-12)

| 요구사항 | 현재 증거 | 남은 작업 |
|---|---|---|
| 도로면/현재 구역/선택 경로 의미 분리 | D-663/665 및 runtime·검수·prelabel 거절 회귀 | 실제 새 도로면 정답과 모델 |
| 라벨→학습→model/eval 의미 계보 | builder/export/intake 및 호출자 회귀 | 실제 upstream 학습 출처 closure |
| 독립 실물 정답·출처 예약/split | 20261010 검수 데이터 hash와 추가 1,341장 저장 mask 대조 | 전체 도로면/현재 구역 독립 pair, 원본 영상별 분리·독립 authority |
| 독립 시뮬레이션 정답과 실물 분리 | D-666 loader·조건/도메인 집계 합성 회귀 | 기존 map_v2_fleet 출처를 유지한 실제 장면/정답 실행 |
| 현재 구역의 검증된 기준점 | D-667 유효성 및 D-670 보류 회귀 | 실제 투영 생산자·보정/위치 오차·시각 정렬 증거 |
| 도로/구역 지표와 제외 분모 | D-665/666 ROI·경계·보류·집계 회귀 | 독립 모델 성능과 조건별 최소 표본·coverage |
| 물체 정밀도/재현율·작음/가림 | 기존 물체 검수·모델 실행과 변환 동등성은 별도 경로 | 독립 물체 fitness 평가 연결과 실행 |
| 사전 고정 수용 profile | 현재 진단은 항상 HOLD | 기준선 측정 후 범위·표본·임계값 사전 고정 |
| 관측 전달·버전 readback·지연/손실 | D-673 내부 파일 생성/readback | 실제 관측 전용 장치 전달과 capture-to-result 지연/손실 |
| 후속 주행 권한 분리 | 기존 조향 거절과 CORE final writer 계약 | 주행 활성화·배포·현장 수용은 별도 권한/증거 |

이 감사는 목표 완료 판정이 아니다. 파일 진단·소스 회귀·local main 착지는 독립 성능 승인 또는 실제 장치 전달을 대신하지 않는다. 20261010 원본과 mask를 전체 도로면으로 재태깅하지 않는다.

## 물체 지표·기존 detector 프레임 어댑터 (2026-10-12)

D-659의 물체 정밀도·재현율 공백에 `object_fitness.py`를 추가했다. D-602 여섯 클래스의 원본 grid 박스, confidence 순서의 같은 클래스 one-to-one 매칭, 중복 FP·미검출 FN, 작은/명시적 가림 정답의 recall, 가림 미확인 분모와 추론 보류를 처리한다. 기존 ObjectDetModel의 infer만 호출하며 독립 정답은 모델 입력에 넣지 않는다. 카메라 시간/유효성 오류는 추론 전에 보류하고 모델 revision·전처리·camera profile·confidence/NMS를 남긴다. 서로 다른 결속/지표 기준의 결과를 합산하지 않는다.

새 모듈과 모델 어댑터가 없을 때 각각 원격 import RED를 확인했다. 집계 결속 혼용을 거절하는 RED 5개도 재현하고 수정했다. 수정 커밋 SHA `2a6405baa4`의 원격 지표/어댑터 회귀는 33개 통과했다. 로그는 X 세션 `logs/object-fitness-red`, `object-model-red`, `object-pooling-red`, `object-pooling-green`에 보존했다. 소스 리뷰에서 집계 모델 결속 누락을 지적받아 공통 결속 보존과 bound/unbound 혼용 거절을 보완했다.

이 증거는 SOURCE 수준이다. 고정 물체 검수 출판물 loader/CLI, 학습·평가 원본 closure, 인증된 가림·완전 negative 검수, 실제 고정 후보의 독립 실물/시뮬레이션 성능과 장치 관측 전달은 남아 있다. 지표 함수나 열린 모델 어댑터를 전체 물체 fitness 재생 완성으로 주장하지 않는다. 사전 수용 profile 및 물체 적합성은 HOLD이며 배포·주행을 수행하지 않았다.

## D-682 고정 물체 정답 출판과 재생

[D-682](../adr/D-682-fixed-object-truth-and-fitness-replay.md)에 따라 기존 evaluation workspace에 `ready/publish --target objects`를 연결했다. D-602 클래스셋, 예약 MCAP 원본과 모든 프레임의 명시적 완료된 물체 검수를 확인한다. 픽셀 pending과 물체 approved는 별개이며 빈 boxes도 전체 화면 검수 완료가 필요하다. 기존 픽셀 기본값·훈련 export 거절은 유지한다. 출판 전후 bag/metadata·실제 decoded image·검수 authority·클래스 결속을 다시 확인한다.

`rosy_ml object-fitness MODEL --store STORE --eval DIR --inputs DIR --max-age-ns N --out FILE`은 로봇 설정 없이 실행된다. immutable 평가/입력/학습 버전, 원본 이미지, 물체 검수 hash·version, 모델 파일·manifest·전처리와 confidence/NMS/매칭/크기 기준을 결속한다. 후보 직접 학습 자료의 클래스 순서/역할을 확인하고 세션·capture group·실제 이미지 중복을 거절한다. 실행 후 파일과 예약을 재검증한다. 추론 엔진 실패는 진단 exit 2이며 보고서를 만들지 않고 기존 out은 덮어쓰지 않는다. 성공 exit 0도 항상 HOLD다.

`240c63c9e3` 관련 원격 시험은 terminal exit 0, 65 passed / 1 skipped, known-failures NEW0다. skip은 시험 runner의 `mcap_ros2` 미설치에 따른 실제 MCAP 시험이다. 모델 PC의 기존 ML 환경에서 별도로 실행한 합성 MCAP 출판/재생은 실제 encoder/decoder와 ONNX Runtime을 사용했다. 출판한 원본 이미지로 CLI를 실행해 person TP 1, 가림 recall 1을 확인했고, 기존 out 거절(exit 2), 입력 파일 변조 거절(exit 2, 보고서 없음), 원본 bag 변경 시 재출판 proof 거절을 확인했다. 독립 리뷰에서 찾은 클래스 index·후보 학습 클래스 순서·backend 오류 반환 누락은 실패 시험으로 재현 후 수정했다.

합성 실행 source archive SHA256은 `a50465a87da3cd9fff8c91b783eb545995293a60631610a116ea4ab739c7eada`, 내려받아 다시 해시 확인한 보고서 SHA256은 `a6f389d4551fdf474916b2054788ef687b7b9f6e531293ff77549114c72b1943`이다. 세션 evidence의 `synthetic-object-replay-proof-20261012.json` / `synthetic-object-replay-report-20261012.json`과 로그 `object-replay-lineage-green/run-1.txt`에 보존했다. 합성 label·상수 ONNX는 파일/실행 경로 증거이며 사람이 독립 검수한 정답이나 실제 정확도 수치가 아니다.

기존 자료 추가 검색에서는 20261010 drivable 2,769장의 manifest와 human_edit/done 기록을 다시 확인했다. 구형 v11/SAM 결과 830개의 저장 mask 해시가 일치했지만 drivable 클래스와 사람 최종 승인 기록은 없었다. dataset-review-937의 검수 JSON은 비어 있었다. 전체 보이는 도로면의 독립 검수 정답은 추가로 확보하지 못했다. 검색은 bounded inventory이며 모든 외부/미연결 보관소를 확인했다는 뜻이 아니다.

위 물체 loader/CLI는 구현·합성 실행 근거를 확보했다. 인증된 reviewer·live freshness·가림 검수 독립성·전체 upstream 원본 closure, 실제/시뮬레이션 독립 정답 및 성능, 물리 기준점 생산/보정, 사전 수용 profile과 실제 장치 관측 전달의 버전·지연·손실 증거는 여전히 미완료다. local integration, CI, 배포, 장치/현장 수용과 주행 활성화는 각각 별도이며 이 실행은 어느 것도 승인하지 않는다.
