# 10/6·10/7 주행영역 후보와 정면 LiDAR 근접 대조

**판정: 오프라인 후보 진단, 주행 수용 HOLD.** 시험용 6클래스 모델이 화면 아래 40%를 넓게 `drivable`로 칠하는 순간에 같은 녹화의 정면 LiDAR가 무엇을 보았는지 4개 세션 3,336프레임에서 대조했다. 이 결과는 벽 픽셀 정답, `undrivable` 마스크, 안전한 진입 경로 또는 자율주행 성공률이 아니다.

## 입력과 방법

- 원본 MCAP·MP4·모델 계보는 [10/6 후보 출력](../drivable-smoke-1006-full-2026-10-08c/result.md), [10/7 후보 출력](../drivable-smoke-1007-full-2026-10-08b/result.md), [10/6 원본 증명](../lane-1006-mcap-candidates-2026-10-08/result.md), [10/7 원본 증명](../lane-1007-source-proof-2026-10-08/result.md)에 있다. 모델은 20장 smoke 데이터에서 학습된 `lane-seg-20261007-b389d6a0`이다. 그 데이터와 이 영상이 겹치므로 일반화 평가가 아니다.
- [analyze.py](evidence/analyze.py)는 모델 출력 `per_frame.jsonl` 2개와 MP4 sidecar·LiDAR `.scan.npz` 4쌍의 프레임 수·순서·카메라 stamp·LiDAR stamp·sidecar 간격을 확인한다. [summary.json](evidence/summary.json)에 각 입력 SHA-256이 있다. 원본 영상과 스캔 배열은 X:에 남기고 공개 저장소에는 집계만 기록했다.
- 정면 기준은 Pinky Pro 프로필의 LiDAR 180°이며 ±20° 안에서 가장 가까운 유효 반환을 썼다. 최근 0.15초 스캔이고 유효 빔이 70% 이상인 프레임만 대조했다. 0.30m 미만은 **근접 검수 후보**로만 정의했다. 모델의 넓은 마스크는 화면 아래 40% 중 `drivable` >50%다. 0.30m와 50%는 주행 허가 또는 CORE 정지 문턱이 아니다. 장치의 승인된 LiDAR mount revision은 이 옛 녹화에 묶여 있지 않아 178°·180°·182°를 모두 계산했다.

```text
python docs/validation/drivable-lidar-candidate-2026-10-08/evidence/analyze.py --video-dir X:/DevTemp/projects/rosy-platform/2026-10-08--045427--lane-evidence-learning--e0687b/evidence/recordings/video --out X:/DevTemp/projects/rosy-platform/2026-10-08--235301--lidar-mask-audit--c533fa/evidence/summary.json
```

## 전체 프레임 대조

| 세션 | 프레임 | 사용 가능 스캔 | 180° 정면 <0.30m | 그중 넓은 마스크 | 178°·180°·182° 모두 근접·넓은 마스크 |
|---|---:|---:|---:|---:|---:|
| 10/6 `082612Z` | 2,487 | 1,968 | 1,392 | 990 | 989 |
| 10/6 `091340Z` | 642 | 475 | 271 | 271 | 266 |
| 10/7 `143038Z` | 124 | 95 | 0 | 0 | 0 |
| 10/7 `143211Z` | 83 | 83 | 19 | 19 | 11 |

10/6 긴 영상 884번은 정면 0.227m·마스크 96.2%, 짧은 영상 448번은 0.256m·73.3%, 630번은 0.272m·89.6%였다. 10/7 둘째 영상 80번은 0.116m·55.4%였다. 네 정면 거리와 유효 빔 수는 제품의 `front_sector` 함수로 별도 계산해 [summary.json](evidence/summary.json)과 일치함을 확인했다. 연속 장면의 프레임은 서로 독립 표본이 아니므로 위 건수를 오류율로 해석하지 않는다.

반례도 있다. 10/7 첫 영상은 180° 기준 근접 후보가 0건이지만 [R0 재생](../lane-1007-r0-gate-2026-10-08/result.md)은 한쪽 경계 지속·횡단/분기 혼동으로 실패했다. 둘째 영상 55번의 원형·분기 표식은 정면 0.596m, 넓은 마스크 73.9%여서 이 근접 조건에 걸리지 않는다. LiDAR 거리 하나로 경계의 동일성이나 가지 선택을 해결할 수 없다.

## 다음 검수와 제한

10/6의 884·448·630번은 [원본 MCAP 후보 묶음](../lane-1006-mcap-candidates-2026-10-08/result.md)에 이미 있고, 10/7의 55·63·80번은 [207/207 원본 화소 증명](../lane-1007-source-proof-2026-10-08/result.md)에 있다. 사람은 원본 화소에서 벽·물체·흰 선의 실제 관계, 동일 물리 경계 ID, 보이는 바닥과 unknown을 판정해야 한다. LiDAR 한 점의 거리에는 물체 실루엣이나 카메라 픽셀 좌표가 없고, 옛 녹화에는 차선 관측기의 지면 투영값도 없다. 따라서 이 대조로 픽셀을 `undrivable`로 칠하거나 STOP을 풀지 않는다. CORE 단일 최종 `/cmd_vel` 경계는 유지한다.

실행 기준 코드는 로컬 `main` `eb0d06b4b`, 분석 스크립트 SHA-256 `2195595134affc9a7b85f806e3525679dfa85d3c668c491074fc3144bc81a815`, 요약 SHA-256 `d91dcb0c033feb3c2caa7700bb1e7382b89fd261560048794c00ffc3f063dd54`이다. 확인 범위는 호스트 오프라인 계산뿐이다.

같은 입력으로 분석을 재실행한 요약 SHA-256도 위 값과 같았다. 문서 배치·폴더·네트워크·하네스 계약 시험은 136 passed, 1 skipped, known-failures NEW 0이었다. 하네스 lint는 0 errors, 23개의 기존 `last_verified` 경고를 냈다. 이 검증은 장치 LiDAR mount 보정이나 실제 주행 시험이 아니다.
