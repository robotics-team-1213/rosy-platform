# 차선 비가시 프레임 검토와 경계 복구 — 2026-10-05

## 범위와 판정

`fix/lane-visibility`, 비교 기준 `95dc4e2f0`(앞선 splay/crossing 수정 포함). 원본 148장과 과거 7녹화 2,252 sampled frames를 같은 nominal ground/폭 0.0925 m으로 재생한다. 이는 모델 PC 자동 라벨링 구현이나 사람의 정답 마스크·독립 현장 수용 증거가 아니다.

원본 비가시 21장을 에이전트가 시각 검토했다. 87–90은 전경부터 원거리까지 이어진 왼쪽 차선 경계가 있어 복구 대상이다. 32–36, 58–65, 115, 134, 138, 141은 교차로·코너·급곡선의 경계 역할/진행 방향이 불확실하여 HOLD를 유지한다. 페인트 존재와 안전하게 추종할 경계 존재를 구분한다.

## 원인과 변경

횡단보도 bar의 대각 chord가 RANSAC 최대 support를 가져갔다. blob으로 탈락한 후보의 제거 영역이 실제 얇은 경계를 함께 삭제했다. 원래 추출에서 승인된 선이 없고 blob만 있을 때 원본 점 전체에 대해 한 번만 forward support 가중 재시도한다. 승인된 선이 있으면 원래 결과를 유지한다. 기존 길이·셀 수·전체 점 flank 검사, keeper의 pair/side/junction/급경사 검사는 그대로 적용한다. 단순 저신뢰 임계값 완화는 적용하지 않는다.

합성 횡단보도+경계 테스트가 수정 전에 실패하는 것을 확인한 뒤 수정했다. solid patch가 새 경계가 되지 않는 반례를 함께 검사한다. 전역 heading 가중 prototype은 기존 코너/junction 회귀 7개를 깨뜨려 채택하지 않았다.

## 재생 결과

148장 비가시 21→17(19.0% 감소), 복구 87–90 네 장이다. 직진 첫36장 관측32장의 평균 절대 error 0.0518125와 jump 0.007은 그대로다. on_line 0.181→0.176, on_paint 0.063→0.084이다. 페인트 위 목표점 증가를 품질 개선으로 단정하지 않는다.

| 녹화 | 표본 | 비가시 비율 전→후 | jump 전→후 | on_paint 전→후 |
|---|---:|---|---|---|
| real-drive-1 | 148 | 0.142→0.115 | 0.007→0.007 | 0.063→0.084 |
| teleop_20260919_151213_part01 | 402 | 0.097→0.097 | 0.000→0.000 | 0.163→0.163 |
| teleop_20260919_151213_part02 | 372 | 0.226→0.220 | 0.016→0.016 | 0.038→0.045 |
| teleop_20260919_151213_part03 | 377 | 0.141→0.135 | 0.013→0.013 | 0.028→0.028 |
| teleop_20260919_151213_part04 | 304 | 0.214→0.194 | 0.017→0.017 | 0.054→0.073 |
| teleop_20260919_151213_part05 | 350 | 0.126→0.126 | 0.014→0.014 | 0.020→0.020 |
| teleop_20260919_151213_part06 | 374 | 0.120→0.120 | 0.005→0.005 | 0.030→0.030 |
| teleop_20260919_151213_part07 | 73 | 0.178→0.082 | 0.000→0.000 | 0.200→0.179 |

추가 접촉 시트 시각 검토: part04의 14–19는 연속된 경계가 있는 곡선 진입, part07의 26,28,29,31,33–35는 양 경계와 횡단보도가 보이는 장면이다. 모두 paint는 있으나 목표점 정답·진행 경로의 독립 사람 판정은 아직 없다. 기존 nominal 투영과 영상 구성의 편향을 그대로 포함한다.

## 검증과 배포 경계

- 집중 관련 시험 150 passed, 1 skipped, known_failures NEW0 (`focused.txt`).
- 독립 코드 리뷰 Critical/Important 결함 없음; 별도 lane 시험 59 passed, NEW0 (`X:/DevTemp/keep-visible-review-20261005/lane-tests.txt`).
- 최신 main 반영 뒤 집중 시험·harness generate/lint·실제 pre-push·GitHub CI를 별도로 수행한다.
- 장치 릴리스/실행 source 확인은 후속 deployment.md에 실제 수행 결과만 기록한다. 이 문서는 아직 장치 설치 PASS를 주장하지 않는다.
- camera lane mode=line, paint source=threshold의 기존 설정을 변경하지 않는다. learned 모델 shadow/hold와 line-follow OFF를 보존한다. keep의 실제 제어 적용·R1/R2 제한 주행은 현장 관찰자가 필요한 별도 단계로 HOLD다.

## 증거

임시 원본/재생/접촉 시트/검증 출력은 `X:/DevTemp/keep-visible-20261005/`이다. 원본 장치 주소와 인증 자료를 공개 저장소에 넣지 않는다.

| 파일 | SHA256 |
|---|---|
| `final-comparison-summary.json` | SHA256: `f81f3088e6cab4167015eb4affb9ea7064946418766748181c5c014ab5eb897d` |
| `review-debug.json` | SHA256: `5f2c0e86e6f1f07c3afee8d878e068f3c3cf02a2bf21fea1194246df2357ceea` |
| `recovered-0.png` | SHA256: `0b1a8c8ec261386ea5b9f2830272244738ac0dfdb9b52849f51ccd6e88eabb65` |
| `recovered-1.png` | SHA256: `6db4e107bb2b8a0f5b8c75bd9ff20c21b4e51bcc0e36fcf08d8ef5fec1c106ae` |
| `focused.txt` | SHA256: `cfaf532db2c52cb79a7e6bbe9be132844b5b2cc15d06ba42c47bcc01f0e7add9` |
