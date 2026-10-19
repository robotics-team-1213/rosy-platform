# Pinky 연결점 가설과 현재 차로 후보 검증

2026-10-20 기록. **주행 수용 HOLD.** 아래 후보의 원격 회귀 통과와 실제 완주를 구분한다. 기존 [정렬 수명 검증](../pinky-corner-lifetime-2026-10-19/result.md)을 대체하거나 성공 회차만 골라 집계하지 않는다.

## 연결점 거리 계약: NO-GO

사용자 승인 후 [설계](../../plans/2026-10-20-pinky-turn-distance-guidance-design.md)와 [계획](../../plans/2026-10-20-pinky-turn-distance-guidance.md)의 첫 feasibility 단계를 실행했다. 기존 실패의 decision93.375/source93.25에서 연결점까지 계획 station 차이는 약0.0284m이나 현재 영상의 가까운 연결 path는 약0.1391m 앞에서 시작한다. 현재 본 출구는 왼쪽이고 오른쪽은 관측 기억이다. 새 계약으로 현재 관측된 연결점까지 입증한다는 조건이 성립하지 않는다.

`next_junction` 필드·API 버전·Fleet/CORE 전달·운영 활성화는 구현하지 않았다. native model-pose를 일반 localization의 2D/yaw 오차 보증으로 취급하지 않았다.

## 첫 현재 차로 후보: 회귀 통과, SIM 실패

source SHA `88121a4c422a1db6d377b39588882379276fa599`는 기존 current/ahead와 관측 target이 서로 다른 방향을 가리킬 때 보수적인 현재 차로 선택을 비교한다. 관련 원격154 passed/0 skipped, 영향 범위6,649 passed/408 skipped/NEW0(62 subtests 별도), 독립 소스 검토에서 중대한 결함 없음.

native SIM `sim-88121a4c42-22347b`는 FAIL. Fleet reason `pose`, off_lane0.093m. `future_turn_deferred` 후보·적용 모두0회로, 이 판단이 해결책이라는 증거가 없다. motion 중 learned_drivable682/fallback0, 최종 명령·odom 속도0, lease released, 잔존 프로세스 없음, native fetch/정리 완료.

## 공통 목표 행 순서 후보: 회귀 통과, SIM 실패

원본 PNG를 같은 모델·실제 ground/lane half0.0925m로 native 재추론했다. 먼 영상 행의 법선 보정점 x0.112/0.120m를 x좌표 정렬이 가까운 관측 x0.139m 앞에 섞는 것을 확인했다. source `44f463f1c`는 입력을 near→far 행 순서로 유지하고 반환 band도 원래 영상 행으로 되돌린다. 법선 보정·곡률 상한·CORE 정지 조건은 유지한다.

검증 head SHA `100c962ec47f30734f4d31a1136a316818418846`. 이후 커밋은 시험 자료 형식 정리이며 제품 source는 `44f463f1c`와 같다.

| 증거 | 결과 |
|---|---|
| 관련·release 원격 | 252 passed, 0 skipped, NEW0 |
| 영향 범위 원격 | 6,659+9=6,668 passed, 408 skipped, NEW0, 62 subtests 별도, 40 warnings |
| source·fixture 독립 검토 | Critical0 / Important0 / Minor0. 반복 주행 수용은 유보 |
| 동일 조건 native SIM | `sim-100c962ec4-dbea6c` FAIL, `stall`, progress1.861m, `future_turn_deferred`0회 |
| 종료 | 최종 명령·odom 속도0, lease released, 잔존 프로세스 없음, native fetch/정리 완료 |

초기 압축 mask 문자열의 source 삽입은 secret scanner에 탐지됐다. 예외를 추가하지 않고 동일 bytes·출처를 기존 gzip JSON fixture 형식으로 옮겨 위 head에서 검사와 회귀를 통과했다. 경로 오타로0건 수집한 실행과 미구현 gap-cut·일괄 직진 가설을 요구한 실패 시험은 성공 증거로 계산하지 않았다.

mask 회귀는 같은 PNG·ONNX의 재추론 결과이며 pose·guide는 합성 입력이다. 실제 worker/조향 상태 전체의 시간순 재생으로 확대하지 않는다. 정상적인90도 이후 곡선의 x 접힘과 confidence 행 결속도 검증했다.

## 남은 수명 문제와 기각한 완화

100c 실행은46.125초에 왼쪽 정렬을 시작했다. 정상 오른쪽 전진을 거쳐52.375초까지 station 약0.269m, odom chord 약0.233m를 이동했지만 raw centre path의 불연속·가까운 횡 offset으로 종료 조건을 충족하지 못했다. 이전 episode의 yaw 예산이 남아 오른쪽 pivot을 `recentre_alignment_spent`로 거절했다.

고정 관측 cue를 통과하는 평면도 검토했다. 현재 yaw에서 cue가 뒤에 보이는 것만으로 종료하면 회전으로 통과를 위조할 수 있다. 시작 위치→cue 방향의 고정 평면에서52.375초 source/current의 통과량은 약0.0120/0.0148m로 기존0.03m 여유에 못 미쳤다. **이 장면에서 해당 완화는 NO-GO**이며 여유나 정렬 예산을 낮추거나 늘리지 않았다.

추가 native 재생은 그보다 앞선 source45.125초의 producer가 `exit=None`으로 거절한 먼 오른쪽 입구를 guide가 선택·기억하는 우회를 확인했다. side별 near admission과 source에 결속한 기억의 회귀를 별도로 작성했다. 이 후속 수정의 GREEN·SIM 결과는 새 절에 추가한다.

## 재현과 증거 보존

raw root: `$ROSY_SCRATCH/pinky-success-baseline-20261019/`. `current-lane-*`, `centre-order-*`, `centre-fixture-*`, `mask-replay-*`에 원격 시험·실패 SIM·원본 PNG를 보존한다. pytest는 native owner가 선택한 시험 PC, SIM/재추론은 native model PC에서 실행했다. site PC는 pytest만 실행했다.

SIM은 GPU, map_v2_fleet, lap, stall60, record, `lane_return` 제외 조건을 동일하게 사용했다. 모델 revision `lane-seg-20261010-451f0f85`.

- ONNX SHA256: `451f0f85b390d6601dc38c60865ed721936ff407845f7a8196099ae9a110f3d2`.
- native replay 당시 manifest SHA256: `0b0c4e3de8b58e128dc195c5362f3ba9688154f7771ae62960ba68ee9903a2d2`.
- 100c SIM result SHA256: `95215cd5cf7e7cec4795b8d329a1ef178d58123b235816637d02d3a6184aed32`.
- 100c observations SHA256: `a254856dd38538633051439333564ff1666a38e4b9fd1779749d4487313e6d81`.

수용에는 같은 source·모델·지도 조건에서 연속2회 완주와 목표 판단의 실제 적용, 정지·lease·정리 확인이 필요하다. 실물·현장 수용, lane_return, 모델 독립 정확도, main 착지·push는 이 기록으로 입증하지 않는다.

## 기록 범위 정정

독립 리뷰에 따라 위 “이후 커밋은 시험 자료 형식 정리”의 범위를 명시한다. 이는 `44f463f1c` 이후 `100c962ec47`까지의 후속 커밋을 뜻한다. 그 뒤 `c1de655151`은 별도의 near admission·기억 source 결속 생산 코드 수정이며, 위100c의 시험·SIM 결과로 검증됐다고 해석하지 않는다.

## near admission 후보 1b6d47f4bb: SIM 실패

생산 코드는 `c1de655151`, 회귀 자료는 `b496d1e26`이며 최종 문서 HEAD는 `1b6d47f4bb03a1e39be818d74b75686b7d0f28b4`다. b311 원격 관련·문서·release 452 passed, affected 두 실행 6860+9=6869 passed / 408 skipped / NEW0. 1b6 문서·release 별도 실행은 212 passed / NEW0이며 전체 affected 재실행으로 표시하지 않는다.

같은 고정 모델·지도 조건의 `sim-1b6d47f4bb-58308c`는 progress3.421m에서 stall FAIL. 먼 출구 거절40회, 현재 차로 우선 판단2회가 실제 적용돼 앞선1.861m 실패 구간은 통과했다. learned_drivable677회 / fallback0, 최종 cmd·odom0, lease 해제, 남은 프로세스 없음, native 정리 완료. 연속 완주 수용은 미달이다.

- result SHA256: `fd6d06bba6477e87fdf487e98e9d9b2a263541fcb305d5d9e6c61ccdffd1c906`.
- observations SHA256: `ad181349fd148a8c78802985191c1f1e5ab58a6cd2eade4f20b3a62a4956e96a`.

새 실패는90.75s recentre_first가 운동 선택 `_side`를 지운 뒤 다음 프레임이 관측 기억 `_route_exit`까지 지우는 수명 결합으로 재현된다. 88.625s에 near 수용한 오른쪽 관측점은 raw odom 보간상91.875s에도 현재 좌표(.1038,-.0819)m, 원점 이동.0804m로 기존.5m 범위 안에 있다. 같은 route leg이며, 새 프로토콜·정렬 회전 예산 완화 없이 관측 기억과 운동 선택의 수명을 분리하는 후보를 검증한다. 재현 커밋 `a10a7d275`의 원격 시험은 최근접 관측 유실·원거리 만료 두 항목 RED이며 기존 실패 목록과 비교했다.

## 관측 기억 수명 후보 124cccd115: 관련 회귀 통과

생산·회귀 HEAD `124cccd11548e8a3a52f6770faa68ee2987318fa`. 독립 read-only contract reviewer `/root/drive_success_review`가 원본 wall 임계값과 검출 가능한 odom 시각·pose 불연속에 대한 두 지적을 재검토해 해소했다. source 시각·pose 연속성과 실제 keeper의 current_stamp로 source→current 나이·이동·yaw를 검사하며, 모든 odom epoch 변화를 검출한다고 주장하지 않는다. 과거 current_stamp 없는 직접 호출은 기존 호환 범위다.

원격 관련5개 파일은150 passed / NEW0, skip0, runner exit0. 새 회귀는 recentre 보존, 좌표변환, reset·경로·wall·stale 거절, 원래.5m 만료, far/generated 미저장, cached source 결속, clock·pose 불연속을 포함한다. size-range는1b6 이후 두 커밋 통과. 기존 회전량 예산·CORE 최종 명령은 유지했다. 전체 영향 범위와 같은 조건 SIM은 별도 검증 전이며 완주 수용 HOLD다.
