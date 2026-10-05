# 차선 유지 재생 회귀 수정

날짜: 2026-10-05. 브랜치: `fix/lane-keep-replay`. 시작 source: `0cfd9cf4d`.
범위: ROS-free LaneKeeper 판단 수정, 호스트 재생·테스트·코드 리뷰. 장치 배포·설정 변경·주행은 수행하지 않았다.

## 원인과 수정

같은 원본 148프레임과 같은 Python/OpenCV 환경에서 과거 source를 독립 모듈로 읽어 비교했다. 옛 profile을 사용한 `662a5c6c`의 첫 36프레임 평균 절대 error는 0.073715로 역사적 0.074를 재현했다. 경계 짝의 폭·충돌 검사를 추가한 `998d7bfd1`에서 0.150207로 증가했고, 현재 코드도 같은 profile에서 0.150207였다. 현재 nominal profile에서는 0.150174였다. 따라서 의존성이나 profile 교체만으로 이 차이를 설명할 수 없다.

1. nominal 투영에서 좌/우 경계가 +27/−8도처럼 바깥으로 벌어져도, 공통 관측 구간의 폭은 유효했다. 기존 상대 각도 30도 조건이 왼쪽 경계를 제거하면서 오른쪽 단독 경계의 조향 편향을 만들었다. 수정은 양쪽이 바깥으로 벌어지고 **각 경계의 heading이 기존 30도 한도 안**에 있을 때 짝으로 평가한다. 공통 관측 구간이 있어야 이 예외를 허용하고 SIDE_X와 공통 구간 양 끝의 폭 검사는 그대로 적용한다. 좁아지는 chord·개별 한도 밖 경계·폭이 맞지 않는 경계는 이 예외를 받지 않는다.
2. 가로 흰 표시가 투영 후 약 61도가 되어 일반 transverse 기준 아래로 들어왔다. 원래 steep-crossing 검사는 SIDE_X에서 한 차로 이상 떨어진 선만 제거해, 실제로 차로 전체를 가로지르는 표시를 단독 경계로 읽었다. 수정은 paint의 관측 양 끝이 양쪽 차로 경계를 모두 넘는 경우, extrapolated offset에 관계없이 steep crossing으로 제거한다. 경로 근처에 닿는 짧은 곡선까지 제거하는 초기 후보는 폐기했다. 기존 far/steep 검사와 corner latch 조건은 유지한다.

재현 테스트를 먼저 실행해 splay와 full-lane crossing 두 경우가 실패하는 것을 확인했다. 초기 crossing 후보에는 짧은 곡선 반례 테스트가 실패했고, 조건을 전체 차로 span으로 좁힌 뒤 그 반례도 통과했다. 기존 chord·junction·fork·corner 테스트를 포함해 `test_lane_keep.py` 57개가 통과했다. 새로운 모드나 CORE 명령 경로는 추가하지 않았다.

## 원본 재생 결과

입력: 기존 `real-drive-1` 148 JPG, 세션 `20260930T124745Z`, 카메라 320×240 bgr8. 과거와 같은 첫 36프레임 비교 범위를 사용했다. baseline은 시작 source에서 추출한 원본 LaneKeeper와 관련 모듈이며, fixed는 수정 코드다. profile·입력 순서·환경·재생 지표 코드는 양쪽이 같다. Python 3.14 / NumPy 2.5.3 / OpenCV 5.0.0.93.

```powershell
python tools/lane_replay.py --frames <repo>/data/perception/frames/real-drive-1/frames --crop none --detectors line,between,keep --out X:/DevTemp/keep-fix-20261005/replay-fixed
```

최종 비교는 `X:/DevTemp/keep-fix-20261005/final-replay.py`로 양쪽 코드를 다시 실행했다. 다음 값은 final-comparison 결과이며 초기 후보의 결과를 혼합하지 않는다.

| 지표 | baseline keep | fixed keep | 기존 조건 |
|---|---:|---:|---|
| 첫 36프레임 가시 관측 수 | 34 | 32 | 가시성 정답 별도 확인 필요 |
| 첫 36프레임 평균 절대 error | 0.150088 | **0.051813** | ≤0.08: 수치 통과 |
| 전체 목표-선 위 비율 | 0.172 | **0.181** | line 0.253보다 낮음: 수치 통과 |
| 전체 paint 위 비율 | 0.060 | 0.063 | 독립 정답 기반 정확도가 아님 |
| 전체 튐 비율 | 0.014 | **0.007** | ≤0.02: 수치 통과 |
| 전체 비가시 비율 | 0.095 | **0.142** | 14 → 21프레임, 수용 미검증 |

가시 관측만으로 계산한 평균 오차가 줄어든 것을 전체 프레임 성공률로 해석하지 않는다. 첫 36프레임에서 새로 제외한 34·35번은 관측된 paint가 차로 전체를 가로지르는 표시이며, 기존 비가시 32·33번도 같은 종류의 표시다. 해당 프레임의 검출 mask에서 사용 가능한 차로 경계가 없다는 것과 실제 영상에 차로가 없다는 것은 다른 주장이다. 전체 비가시 21프레임에 대한 독립 정답 검증은 아직 없다.

## 별도 녹화 영향 평가

`data/teleop/learning/teleop_20260919_151213_part01..07.mp4` 7개를 약 4fps로 동일 추출하고 양쪽에 재생했다. 이 영상들에는 직진 36프레임 정답이 없으므로 prefix 오차를 수용 점수로 쓰지 않는다. 아래 비교는 검출 동작 변화이며 실기 성공률이 아니다.

| 녹화 part | 평가 프레임 | 비가시 baseline → fixed | 튐 baseline → fixed | 목표-선 위 baseline → fixed |
|---|---:|---:|---:|---:|
| 01 | 402 | 0.097 → 0.097 | 0.000 → 0.000 | 0.014 → 0.014 |
| 02 | 372 | 0.167 → 0.226 | 0.016 → 0.016 | 0.113 → 0.122 |
| 03 | 377 | 0.082 → 0.141 | 0.019 → 0.013 | 0.087 → 0.093 |
| 04 | 304 | 0.178 → 0.214 | 0.017 → 0.017 | 0.092 → 0.096 |
| 05 | 350 | 0.089 → 0.126 | 0.011 → 0.014 | 0.094 → 0.098 |
| 06 | 374 | 0.083 → 0.120 | 0.013 → 0.005 | 0.073 → 0.076 |
| 07 | 73 | 0.178 → 0.178 | 0.000 → 0.000 | 0.050 → 0.050 |

7개 합계 2,252프레임을 비교했다. part05의 튐 비율은 0.011에서 0.014로 증가했으나 0.02 이하이고, 일부 목표-선 위 비율도 증가했다. 새로운 비가시와 이런 변화가 실제로 옳은지는 독립 정답 없이는 판단할 수 없다. 수치를 모두 개선했다고 주장하지 않는다.

## 검증과 다음 관문

- 전체 perception: 2,629 passed, 109 skipped, NEW0 (`run.txt`, 562.02s). 마지막 공통 관측 구간 hardening 후에는 해당 차선 테스트를 별도로 재실행해 57 passed를 확인했다. 최신 main 반영 뒤 관련 소비 경로도 다시 검사한다.
- 독립 리뷰: Critical/Important 결함 없음. 최종 차선 테스트 57 passed, NEW0 (`X:/DevTemp/keep-review-20261005/final-lane-tests.txt`).
- 문서 계약·배치: 126 passed, 1 Windows skip, 21 warnings, NEW0 (`docs-tests.txt`).
- 구조 예산: 2 passed, NEW0 (`architecture.txt`). Harness lint: 0 errors, 21 기존 검증 상태 warnings (`lint.txt`).
- 호스트 검사는 ROS 런타임·ARM64 payload·실기/현장 수용을 대신하지 않는다.

[D-378](../../adr/D-378-real-drive-errors-and-autonomy-gates.md)의 직진 평균 오차·목표-선 위·튐 수치는 통과한다. 그러나 새로 비가시가 된 프레임의 독립 검토와 추가 곡선·교차로 평가는 남아 있으므로 **전체 R0 수용과 실기 차선 유지 주행은 HOLD**다. 앞선 [실기 준비 상태](../line-tracking-readiness-2026-10-05/result.md)는 정지 관측 기록이며 이번 수정 코드의 장치 설치 증거가 아니다.

다음 순서는 새 비가시 프레임의 사람이 확인한 정답 → 후보 source와 시험 장치 설치 source 일치 → 사람이 수동 운전하는 R1 비교 → [D-344](../../adr/D-344-pilot-assisted-autonomy.md)의 신선한 진행 버튼/hold lease를 사용하는 제한 R2이다. 현장 진행 조작자가 없다는 답변은 유지한다. 원격 root 권한이나 host pytest를 주행 수용으로 대체하지 않는다.

## 원본 증거와 재현 한계

원본 위치는 공개 저장소 밖 `X:/DevTemp/keep-fix-20261005/`다. 과거 코드는 비교용으로만 추출했으며 build/run/deploy 경로에 등록하지 않았다. scratch는 영구 보관을 보장하지 않는다. 공개 기록에는 주소·인증 정보·영상 원본을 포함하지 않는다.

| 증거 (scratch 기준) | SHA-256 |
|---|---|
| `history-summary.json` | `fe5d8ec2d670b2d940c3d4795d06ac67aa2b127aac704499e1e4f5dc88817391` |
| `final-comparison-summary.json` | `adc90a8920cf61b46b1f736f6ef170fc993ddf9ad2efe039aef27e1863e3cef6` |
| `final-replay.py` | `0ac80a0e5533264cbec48680057a376e74c2ab1809e017380e8b16335a8bb8af` |
| `history.py` | `cef2ec75b5d740dd92affbfd30b6e22fd3404dee2ef071b7a1b283c0f4fb16f7` |
| `final-comparison/real-drive-1/fixed/frames.json` | `724eab75469fcceebed1946b65f9eed6e040f3a8de17d6be188e74b628e9b3ad` |
| `final-comparison/real-drive-1/fixed/metrics.json` | `5a895680c61f84c87c763bab11fc6939a34f49f70255b469df0532891dcfbd02` |
| `history/HEAD/lane.py` | `392d2eb289e90ed0889e25821d969968e9b7ce2137987aacedf3a265e8f21f68` |
| `history/HEAD/lane_bev.py` | `259c1c0543f7b212d353d1a5fb642812a4c0402020ef1c84c131af0071d1277c` |
| `history/HEAD/lane_keep.py` | `b6cc6db8f97429a136050dce1a8156d4286219f97a8eebddfea976bbd93ee485` |
| `history/HEAD/lane_keep_lines.py` | `098704deb2ed1ee18e0c1f798d7a1665c6ee617413cf8785811a1b764bb5182d` |
| `history/HEAD/lane_keep_pairs.py` | `233e10ac1075a870ead1783d8062259b6de64327adcc89f328e5102d653fe79f` |
| `input-sha256.json` | `c9f51112248cdf5cff6e2cb8cae09e31196c11b80fab4cf99b68957f61db1f41` |

| `run.txt` | `05fcc6568d28a381580bd50869a0f65217dcd06b08b0e3bde3c367eb85e50195` |
| `docs-tests.txt` | `796f32197e0bf175e6068cddb306ecd3c4d78acc2dc7555a02fe59af4edeac77` |
| `architecture.txt` | `1620b57ac8f55b7b55264558e71676e393b0dc427c02ef2eb5e55e705b200460` |
| `lint.txt` | `30ce4c30ab45a1b0a74bfbe21a4a27d840c8d81e5f7c8e19837483613a7f2c7c` |
