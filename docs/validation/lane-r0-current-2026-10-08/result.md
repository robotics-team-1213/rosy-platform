# 차선 추종 R0 현재 코드 재생, 2026-10-08

증거 등급: **호스트 오프라인 재생**. 실물 주행, ROS-SIM 폐루프, 사람 검수 정답이 아니다. 차선 추종 목표는 [논문·영상 계약 검토](../../plans/2026-10-08-lane-papers-contract-fit.md)의 H1–H3와 [D-378](../../adr/D-378-real-drive-errors-and-autonomy-gates.md)의 R0→R1→R2 순서를 따른다.

## 입력과 실행

- source: `21e521c9c` (`main`), Python 3.14.5, OpenCV 5.0.0, NumPy 2.5.3.
- 입력: `data/perception/frames/real-drive-1/frames`의 148 JPG. 파일명을 정렬해 `파일명 UTF-8 bytes + 파일 bytes` 순서로 이어 계산한 SHA-256은 `b7053f6c4821ca4bae97082650e5b2a5cb91efe826cea51cbff73bbc3c959e68`이다.
- 명령: `python tools/lane_replay.py --frames data/perception/frames/real-drive-1/frames --crop none --detectors line,between,keep --out X:/DevTemp/lane-goal-20261008/main-replay`
- 원시 `frames.json` SHA-256: `a1176ac598a00327603eb4b3a588d3e6e869e471f6e333a14e0ca8aad60dbed1`. 출력은 X:에만 둔다.
- 장치 payload의 `lane_corner_turning: true` 후보를 확인하기 위해 같은 source·입력을 `--detectors keep,keep_corner --out X:/DevTemp/lane-goal-20261008/corner-replay`로 재생했다. 이 실행의 `frames.json` SHA-256은 `1e0689f5ae2e14750b1ec644588b945ce0f35f9c20e28b048a02c7dead56d710`이다. 실기 설치 모드가 현재 `keep`인지는 별도 readback이 필요하다.

| 검출기 | 첫 36프레임 가시 수 / 평균 절대 error | 148프레임 비가시 | 목표가 선 위 | 목표가 페인트 위 | 튐 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `line` | 36 / 0.295611 | 0.014 | 0.253 | 0.158 | 0.007 |
| `between` | 34 / 0.012735 | 0.243 | 0.170 | 0.062 | 0.007 |
| `keep` | 32 / 0.061063 | 0.108 | 0.167 | 0.083 | 0.020 |
| `keep_corner` | 32 / 0.061063 | 0.250 | 0.117 | 0.081 | 0.000 |

두 `keep` 설정의 직진 구간 평균 절대 error는 D-378의 0.08 이하이고, 목표가 선 위인 비율은 `line`보다 낮다. 기본 `keep`의 튐은 보고된 세 자리 소수에서 0.020으로 문턱과 같다. 그러나 `keep` 비가시 16프레임(32–36, 58–65, 115, 134, 141)의 **실제 차선 가시 여부**는 확인된 정답이 없다. 32·58·115·134·141 이미지를 육안으로 보면 횡단선, 원형 선, 벽 근접이 섞여 있어 검출기 `none`만으로 오검출 또는 정당한 STOP을 확정할 수 없다.

`keep_corner`는 148장 중 29장에서 기본 `keep`과 판단이 달랐고, 비가시는 37장이다. 특히 126–147의 22프레임 연속 `none`에는 곡선 페인트가 보인다. 126·130·136·147 이미지를 육안 확인했으나 그 칠이 동일 주행 차로의 유효 경계인지는 사람의 프레임 연속 검수가 필요하다. 따라서 D-378 R0 전체 판정은 **HOLD**다. 곡선·분기·한쪽 선 소실의 회복도 이 148장으로 수용하지 않는다.

2026-10-08 공유 `main`의 `877dab90f`(뒤집힘 래치 수정 병합 포함)에서 같은 입력과 `--detectors keep,keep_corner`로 다시 재생했다. 출력 `X:/DevTemp/lane-goal-20261008/main-877dab-replay/frames.json`의 SHA-256은 앞선 `keep_corner` 재생과 동일한 `1e0689f5ae2e14750b1ec644588b945ce0f35f9c20e28b048a02c7dead56d710`이다. 즉 이 녹화에서는 126–147 연속 `none`이 개선되지 않았다. 해당 수정이 다른 주행 경로에서 효과가 있는지는 이 재생으로 판단할 수 없다.

재생 도구의 출력 지속성 지표를 추가해 같은 148장을 재측정했다(`X:/DevTemp/lane-goal-20261008/replay-miss/current/metrics.json`, SHA-256 `6c5f0fd54ef0c2f6ac6395e82e90cf6ef23c1974daee9f588ada6a895f5715e1`). 기본 `keep`은 연속 `none` 5구간·최장 8프레임이고, `keep_corner`는 5구간·최장 22프레임이다. 이는 검출기 출력의 지속성으로, 실제 차선 정답에 매칭한 논문 `R_F/R_M`이나 잘못된 STOP 횟수가 아니다.

[2026-10-05 준비 기록](../line-tracking-readiness-2026-10-05/result.md)의 `keep` 첫 36프레임 평균 0.150088과 이번 0.061063은 다르다. source·환경·출력 provenance가 다른 별도 재생이므로 역사적 결과를 현재 결과로 대체하지 않는다. 차이 원인을 규명하기 전에는 변화량을 알고리즘 개선으로 귀속하지 않는다.

## 다음 판정

1. 두 설정의 비가시 프레임(특히 126–147)에서 같은 차로의 실제 좌우 경계와 정상적인 STOP 여부를 사람에게 확인받는다. 한쪽 선만 보이는 구간은 이전에 확인한 경계·오도메트리·시간을 함께 검수한다.
2. 10/6·10/7 원본의 가림→재출현 양성은 아직 0건이고 10/6 두 영상은 전진 중 자율 주행이 아니다. 양성 재획득률은 새 동기 녹화와 검수 전까지 수치화하지 않는다.
3. 남서 굽이 B9 수정 후보는 게이트를 켠 SIM에서 0/6 통과였으므로 착지·실기 전환 근거가 아니다. 같은 지도·차체·CORE 경로의 굽이, 교차로, 벽/분기 음성, R1 사람 운전 그림자 비교를 통과해야 R2를 검토한다.
