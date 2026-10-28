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

생산 코드는 `c1de655151`, 회귀 자료는 `b496d1e26`이며 최종 문서 HEAD는 `1b6d47f4bb`다. b311 원격 관련·문서·release 452 passed, affected 두 실행 6860+9=6869 passed / 408 skipped / NEW0. 1b6 문서·release 별도 실행은 212 passed / NEW0이며 전체 affected 재실행으로 표시하지 않는다.

- 문서 HEAD `1b6d47f4bb03a1e39be818d74b75686b7d0f28b4`.

같은 고정 모델·지도 조건의 `sim-1b6d47f4bb-58308c`는 progress3.421m에서 stall FAIL. 먼 출구 거절40회, 현재 차로 우선 판단2회가 실제 적용돼 앞선1.861m 실패 구간은 통과했다. learned_drivable677회 / fallback0, 최종 cmd·odom0, lease 해제, 남은 프로세스 없음, native 정리 완료. 연속 완주 수용은 미달이다.

- result SHA256: `fd6d06bba6477e87fdf487e98e9d9b2a263541fcb305d5d9e6c61ccdffd1c906`.
- observations SHA256: `ad181349fd148a8c78802985191c1f1e5ab58a6cd2eade4f20b3a62a4956e96a`.

새 실패는90.75s recentre_first가 운동 선택 `_side`를 지운 뒤 다음 프레임이 관측 기억 `_route_exit`까지 지우는 수명 결합으로 재현된다. 88.625s에 near 수용한 오른쪽 관측점은 raw odom 보간상91.875s에도 현재 좌표(.1038,-.0819)m, 원점 이동.0804m로 기존.5m 범위 안에 있다. 같은 route leg이며, 새 프로토콜·정렬 회전 예산 완화 없이 관측 기억과 운동 선택의 수명을 분리하는 후보를 검증한다. 재현 커밋 `a10a7d275`의 원격 시험은 최근접 관측 유실·원거리 만료 두 항목 RED이며 기존 실패 목록과 비교했다.

## 관측 기억 수명 후보 124cccd115: 관련 회귀 통과

생산·회귀 HEAD `124cccd11548e8a3a52f6770faa68ee2987318fa`. 독립 read-only contract reviewer `/root/drive_success_review`가 원본 wall 임계값과 검출 가능한 odom 시각·pose 불연속에 대한 두 지적을 재검토해 해소했다. source 시각·pose 연속성과 실제 keeper의 current_stamp로 source→current 나이·이동·yaw를 검사하며, 모든 odom epoch 변화를 검출한다고 주장하지 않는다. 과거 current_stamp 없는 직접 호출은 기존 호환 범위다.

원격 관련5개 파일은150 passed / NEW0, skip0, runner exit0. 새 회귀는 recentre 보존, 좌표변환, reset·경로·wall·stale 거절, 원래.5m 만료, far/generated 미저장, cached source 결속, clock·pose 불연속을 포함한다. size-range는1b6 이후 두 커밋 통과. 기존 회전량 예산·CORE 최종 명령은 유지했다. 전체 영향 범위와 같은 조건 SIM은 별도 검증 전이며 완주 수용 HOLD다.

## 관측 기억 수명 후보 4d0f811fad: SIM 실패

독립 최종 검토는 Critical0 / Important0 / Minor0. 원격 affected는1회차6873 passed / 408 skipped / 38 warnings / 62 subtests와 문서 secret guard1 failed, 2회차9 passed / NEW0이다. 문서 SHA 옆 한글·구두점 때문에 integrity 문맥으로 인식되지 않은 표기 문제이며, guard를 완화하지 않고 기록 형식을 고쳐 별도 재검증한다. 이 실행을 전체 GREEN으로 기록하지 않는다.

같은 고정 조건 `sim-4d0f811fad-e6b372`는 progress3.420m에서 stall FAIL. learned_drivable682회 / fallback0, 최종 cmd·odom0, lease 해제와 남은 프로세스 없음, native 정리 완료. 근접 출구 기억은91.375~94s 실제 유지됐으나 current-lane 보정6회(5회 유효)가 현재 관측 분기까지 덮었다. 89.125s 오른쪽 near=True 관측점(.189,-.092)m, 89.625s 같은 관측의 bounded memory(.1773,-.0911)m인데도 centre left로 바뀌었다. 이후91.375s left recentre, off-line,93.75s 정렬 예산.9083rad/limit.6039rad 소진으로 HOLD했다. 완주 수용 미달이며 같은 실패 source를 반복하지 않는다.

- result SHA256: `a02158eceee1259d56ac12fa9f0f2780a657714ebedee668ea05ed6fb84f6117`.
- observations SHA256: `017c15028baba0a4ffaf6617a5e98d8f954b35d0ae2eb6e542e7fe62ef095f2c`.

후속 회귀는 이미 near 수용한 경로 분기 및 그 범위 안 관측 기억을 미래 분기로 간주하지 않도록 요구한다. 임계값·회전량 예산 완화와 새 API는 추가하지 않는다.

## 현재 분기 선택 보존 후보 bd3a450cbb: 관련·문서 회귀 통과

생산 commit `bd3a450cbbc9e21b839abc38182a542efc3c7a3e`. d639 재현2 failed / 106 passed / NEW2 후1행 보정 가드를 추가했다. 선택된 출구의 near=True 또는 유효한 route observation memory라면 기존 조향 후보를 보존한다. 다른 쪽 출구가 near라는 이유로 미래 보정을 막지는 않는다. 독립 reviewer `/root/drive_success_review`가 실제6회 기록과 생산 경계를 확인했고 추가 소스 지적이 없다.

원격 관련·문서·release 합계340 passed / 0 skipped / 36 warnings / NEW0, runner exit0. 앞선 문서 해시 표기 실패는 이 실행에서 해소됐다. size-range는4d0 이후3커밋 통과. 다음 영향 범위·동일 조건 SIM은 별도 검증하며 연속 완주 수용 HOLD를 유지한다.

## 8463f45c51: 현재 분기 보정 범위 수정 후에도 SIM 실패

최종 독립 검토는 Critical0 / Important0 / Minor0. affected는1회차6862 passed / 408 skipped / 38 warnings / 62 subtests, 원본 마스크 시험의 이전 centre 보정 기대값1 failed; 2회차9 passed / NEW0. 실패를 숨기지 않고 두 원본 mask의 right near=True를 명시적으로 검사해 현재 분기를 보존하도록 기대값을 맞췄다. 시험 commit `4dc209dccea56e99ff3f31beba3d761ada62e183`의 원본 마스크·현재 차로 회귀34 passed / NEW0. 이를 전체 최신 affected 재실행으로 표시하지 않는다.

고정 조건 `sim-8463f45c51-e208e7`는3.253m에서 realign 뒤 stall FAIL. current-lane deferral0, learned_drivable632회 / fallback0, 최종 cmd·odom0, lease 해제·남은 프로세스 없음·native 정리 완료다.

- result SHA256: `f4193eb8fd884011d11041ecc542eab2f6797c257825ac3dc2636b9788acbe37`.
- observations SHA256: `971f1399377ab70898e22746b377fd94fcdf846fb598cbe6528fe1eed29422c1`.

경로 station 급변도 추적했다. Fleet 다음 arc admission에서 약2mm 더 가까운 다음 polyline을 선택하며 발생했고 CORE 시점·좌표 전달 오류는 발견하지 못했다. 같은 station/here의 과거 PASS에서도 유사한 안내가 있으므로 이를 실패의 단독 원인으로 단정하지 않는다.

동일 PNG·고정 모델의 native `mask-replay-5`는 exit 계산과 목표 행 순서를 분리했다. 이번710 PNG는 새 행 순서 centre(.222,+.099)m, 과거 x 정렬(.171,-.152)m, ahead.315m/right near=True였다. r51 PASS710 PNG도 새 순서(.201,+.126)m와 과거 정렬(.219,-.103)m로 방향이 달랐고 ahead.306m였다. 앞이 열린 현재 junction에서 fresh route가 선택한 near right를 final arc selector가 `ahead<.25` 조건 때문에 소비하지 않고 neutral centre로 대체하는 경로를 확인했다.

후속 수정은 이 새 범위에서 운동 target 선택을 바꾼다. 이미 선택된 near 출구가 source→current 변환 후에도 앞에 있고 guide가 fresh이면 기존 arc 경로로 소비하도록 검증한다. 원본 mask 행 순서 롤백·REALIGN 임계값 완화·CORE 권한 변경은 하지 않는다. 재현 commit `903560ba1` native1 failed / 7 passed / NEW1, 반례는 stale·far 출구다. 추가 안전·지난 출구 반례와 GREEN·SIM은 별도 확인한다.

## 열린 junction 선택 출구 소비 후보 67e0b96e85

생산 commit `67e0b96e85e52046a2109b8a68e63e250b1b7dab`. 독립 reviewer `/root/drive_success_review`가 현재 좌표의 전방 검사를 포함한 source/test diff를 확인했고 추가 material finding이 없다. 열린 junction에서도 fresh guide와 일치하는 실제 near 출구를 기존 arc에 전달한다. 현재 뒤로 지난 cached 출구, 누락 점, 반대쪽만 near, far, stale·안내 없음, wall 차단은 새 선택을 허용하지 않는다. front-stop·straddle·crosswalk·pivot 우선 처리는 앞에서 유지한다. 이것은 새 범위의 조향 목표 선택 변경이며 CORE 권한과 기존 임계값·회전량 예산을 유지한다.

관련6개 파일 native168 passed / 0 skipped / NEW0, runner exit0. 8463 이후3커밋 size-range 통과. 반복 SIM과 최신 전체 영향 범위는 아직 별도 검증 전이며 완주 수용 HOLD다.

- native replay JSON SHA256: `e1b6209cdc1d51983207f36475363c52443dd3d7b439b136874f23f6e7934087`.
- 이번 실패710 PNG SHA256: `d805d512002093ddba660b668433ed98bfbbb2d1c57de498ad396683c61ceae8`.
- r51 PASS710 PNG SHA256: `07028eba6c6060b43432fbe23271acffb8a6ff35df30879c6c627bf2001e3e6f`.

## e5b1e33744: 같은 소스 1 PASS / 1 FAIL

생산67e0와 문서 포함 검증 HEAD `e5b1e3374451b4b33b95f52723b84f3e79d8c8f7`의 최종 독립 검토는 Critical0 / Important0 / Minor0. native affected는1회차6886 passed / 408 skipped / 38 warnings / 62 subtests, 2회차9 passed이며 각각 NEW0, exit0이다. 합계6895 passed이며 skip을 통과로 계산하지 않는다.

두 SIM은 실제 result의 pointer·render·paint target·lap·stall60·제외 항목·spawn·place 값이 같다. source·world·graph·URDF provenance도 동일하다. 다만 결과는 연속 완주 기준에 미달이다.

| 기록 | 1차 | 2차 |
|---|---|---|
| run | sim-e5b1e33744-1213a3 | sim-e5b1e33744-068d4c |
| 결과 | PASS / arrived | FAIL / pose / off_lane .114m |
| 열린 junction 선택 / 먼 출구 거절 | 252 / 100 | 257 / 86 |
| learned_drivable / fallback | 1483 / 0 | 1342 / 0 |
| 최종 cmd·odom | 0 / 0 | 0 / 0 |
| lease / 남은 프로세스 | released / 없음 | released / 없음 |
| native 종료·회수·정리 | exit0 / 완료 | exit1 / 완료 |

1차 motion interval 중 realign33회·정렬 예산 HOLD2회 뒤 최종 도착했으므로 무중단 주행으로 표시하지 않는다. 1차 revision metadata1473개와 2차1340개는 고정 revision과 일치한다. 나머지10개·2개는 null이다. 1차10개는 mask_for metadata 초기화와 latest_way 캐시 소비 경로 차이로 설명되며 cached learned-drivable 사용과 일치한다. null 표본별 revision을 직접 입증하지 않는다. 1차 mask age는.25/.375s이고 다른 denoise·expected_path 조향으로 바뀐 증거는 없다.

- 1차 result SHA256: `6218283dfcf085aa914ba62e599dad5a8fab469b030a87e9467f2aecedeb5d16`.
- 1차 observations SHA256: `099f8079a339f3f5fe275f8cd15a2da0d38771d74f39b212211462bfeae5c0d8`.
- 2차 result SHA256: `f50bbd2e7ddb7134e3d48fd7f830584f45accbd7f8a484d28c7e3638cefc531f`.
- 2차 observations SHA256: `b189ddd1f6f6166c13c46997b99271ddc4e8ac429de6da7c36182f28f8cf0cb2`.

## 2차 마지막 코너의 분리된 opening 혼합 재현

169.375s 오른쪽 점(.183,-.089)m이169.5s(.407,-.214)m로 바뀌어 near=True로 저장됐고, 이후 네 표본의 route memory로 남았다. native PNG 재생 `mask-replay-6`은1356 원본에서 서로 다른 두 border run을 직접 확인했다. 먼6행(123~128, x.4071~.4521m)과 가까운5행(194~198, x.1792~.1846m)이 합쳐져 전체11행 중앙값이 먼 점이 됐다. 인접1355에는 가까운6행만,1357에는 opening이 없다. near 입장과 point·reach가 같은 opening이라는 결속이 빠진 직접 재현이다.

PNG SHA256 `f8ee3850c152629863afe40337ac7713dd54e50eaa285d2b821b1f14cc733933`의 native mask를 RLE fixture로 보존했다. 재현 commit `0aaacaf136`의 native 회귀1 failed / NEW1, point x=.407m를 확인했다. 후속 수정은 기존 above 조건·최소4행·기존 row gap 기준으로 연결된 opening을 고르고 near·point·reach를 동일 run에 결속한다. 넓게 연결된 단일 opening은 잘라내지 않는다. 실제 diff 독립 검토·GREEN·반복 SIM은 별도 확인한다. 완주 수용 HOLD를 유지한다.

## 연결된 opening 결속 후보 f47dbb4ddd: 관련 회귀 통과

생산 commit `f47dbb4dddcb1fba59a6b4225d90c664b137ff24`. `_exit_rows`가 기존 above .04m·최소4행·행 간격 기준을 유지한 채 유효한 연결 opening을 선택하고, 동일한 행에서 near·point·reach를 산출한다. 가까운 유효 run이 있으면 그 run을 사용하고, 없으면 기존 reach 판단을 위해 먼 유효 run을 유지하되 near로 입장시키지 않는다. 전체 mask 연결성 보장이나 새로운 최대거리 cap은 추가하지 않는다.

독립 reviewer `/root/drive_success_review`의 실제 source/test 검토에서 추가 material finding은 없다. native 관련7개 파일173 passed / 0 skipped / NEW0, exit0. 실제1356 mask와 저장 기억, 고립 near hit, 두 opening, 누락 이미지 행, 넓게 연결된 opening을 검증했다. e5b1 이후2커밋 size-range 통과. native replay JSON SHA256: `8e694f171efab03ec9bee05fabd9fdb51868ac9c287441cbf311cd1eb26d3f47`.

최신 영향 범위·동일 조건 반복 SIM은 별도로 검증하며, 앞선1 PASS / 1 FAIL을 이 후보의 통과로 이월하지 않는다. CORE 권한·기존 임계값·회전량 예산과 새 연결점 프로토콜 NO-GO 판정을 유지한다.

## b42 검증 종료와 마지막 코너 실패

HEAD `b42b05b0893a4db9f978f9333efda8e6cc5a1776`

native 영향 범위는 run-1 6,891 passed / 408 skipped, run-2 9 passed로 총6,900건을 통과했다. 두 로그 모두 known_failures 비교 NEW0이다. e5..b42 독립 최종 검토는 Critical0 / Important0 / Minor0이었다.

동일 조건 첫 SIM `sim-b42b05b089-81d313`은 마지막 코너에서 pose/off_lane 0.108m로 실패했다. settled_xy는 (0.002470, -0.358619), 목표 거리는0.551514m였다. 실제 주행 표본1,291개 모두 learned_drivable이고 fallback0이다. revision 표기가 있는1,280개는 고정 revision과 일치하고11개는 누락되어 표본별 revision을 직접 입증하지 않는다. 열린 junction 수용298회·먼 출구 거절63회였다. final cmd·odom은0, lease released, left_running은 빈 목록이며 산출물 회수와 native 정리를 마쳤다. lane_return은 기존 조건대로 SKIP이다.

167.125초에는 오른쪽 영상 목표(0.223, -0.091)를 미래 왼쪽 안내로 다시 명명한 exit_from_target 후보가 왼쪽 pivot을 선택했다. 당시 here는-17.77도, ahead는+53.5도였다. 원래 관측 방향과 지도 유래 후보의 출처 분리를 후속 진단 대상으로 삼는다. centre_path_m은 보간된 행 중심이므로 그 자체를 실제 마스크 연결 증거로 사용하지 않는다. 같은 실패 후보를 수정 없이 반복하지 않으며 수용은 HOLD다.

- result.json SHA256: `b4d4c8b9319a55860914935f71dc1611124a218e9fdad7128cb4953f042a9196`
- observations.jsonl SHA256: `701bea450c2a6a26397d8f9a65b25e0a58a3aad0b49fab50621eb0e947014c43`
- run.txt SHA256: `7c7db8e26cf01b83d282add11891667818b05076c086b498531f66912f1fe479`

## 관측 출처 보존과 실제 화면 바닥 정렬 후보

HEAD `8a870ada3ea6a8a657d102a9f8921a9395bd4f17`

b42의 원본 PNG001337·001338·001339를 같은 모델로 native 재생했다. 001337의 합성 목표는(0.223, -0.091)이지만 원래 행 중심 추정점은 화면 밖이라 실제 마스크 지지를 직접 증명하지 못했다. 화면 경계로 제한한 픽셀을 다시 지면으로 투영하고, 원본 픽셀과 행 사이 연결 픽셀이 모두 floor인 실제 raw 행 prefix만 정렬 근거로 삼았다. 이 값은 차로 중심이나 출구 사실로 표시하지 않는다.

수정 후보는 memory·target의 원래 방향을 미래 guide 방향으로 바꾸지 않는다. 반대 관측은 출구 승격을 거절하고 명시적인 guide 후보로 구분한다. guide만으로 반대쪽 현재 target을 따라 전진하는 경로도 제자리 look로 제한했다. 현재 target의 반대 여부는 odometry로 현재 좌표에 변환해 검사한다.

짧은 실제 floor prefix가4개 이상의 raw 행을 가지며 source/current 모든 점이 앞쪽0.18m 안이고 같은 side일 때만 기존 정렬 분기에서 사용한다. 회전 방향과 초기 상한은 같은 prefix의 첫 실측점에 결속한다. 전체 prefix가 더 멀리 이어지면 근접 구간만 잘라 수용하지 않는다. zero-linear confidence, 누적 yaw 예산, odometry 연속성, fresh guide, 전진 후 수명 종료와 CORE 최종 권한은 유지한다.

native RED는 a81c256의14개 NEW와 현재 좌표 별도 회귀1개 NEW로 확인했다. 이후8a870 생산 후보의 관련8파일193건이 native 통과했고 skip0, known_failures NEW0이다. clip 지점이 non-way일 때, 픽셀 연결의 구멍, 긴 prefix, current 범위 이탈, 무전진 예산 소진을 포함한다. 실제001337 mask를 사용한 full steer는 반대 미래 pivot보다 관측 floor 방향의 bounded 정렬을 선택했다. 독립 contract 검토의 두 P2를 수정하고 소스 커밋 전 재검토에서 추가 material finding 없음을 확인했다. b42 이후5커밋 size-range 통과. 최신 영향 범위와 반복 SIM 수용은 별도 검증하며 아직 HOLD다.

- 원본001337 PNG SHA256: `9c5eeba847fec65766775ff7a220c06813069b959cc78a1857811fcc36f0e0b8`
- native mask packbits SHA256: `820227703f251726f03f3b7bbcbbb3a5767b06f66ef5be770a4e4dbad037ee07`
- native replay JSON SHA256: `55e829a44bbedbd0210c118a9aac9c5b67900de09cd4552818f4bc7715d8de08`

## 촬영 이후 회전한 합성 후보의 현재 좌표 판정

HEAD `8387e53ffbd2ba132b278b34ea0098cc7dc315d1`

8a870의 별도 최종 소스 검토에서 Important1을 확인했다. target 승격 방향은 source 좌표였고, source target(0.15, +0.10), 관측 이후 yaw +0.8rad, guide +30도에서는 현재 목표가 오른쪽으로 바뀌어도 왼쪽 출구로 승격해 오른쪽 전진 arc가 남았다. 같은 문제가 memory 유래 후보에도 남아 native3794606c 회귀2개 NEW로 재현했다.

8387은 target 승격을 현재 좌표에서 판정하고, guide·target·memory 유래 후보의 반대 방향 검사도 final selector와 같은 선택 점을 현재 좌표로 변환해 수행한다. 실제 near 출구의 관측 입장은 바꾸지 않는다. 최신 diff는 source 커밋 전 독립 safety 재검토에서 추가 material finding이 없었다. 이전193건 통과는 후속 변경의 검증을 대신하지 않으며 최신 native 회귀·영향 범위·SIM은 별도로 확인한다.

8387의 최신 관련8파일은 native195 passed / skip0, known_failures NEW0로 종료했다. b42 이후7커밋 size-range 통과. 영향 범위와 동일 조건 반복 SIM은 아직 수용 증거가 아니며 HOLD를 유지한다.

## 7a0 영향 범위 통과와 중반 코너 실패

HEAD `7a0bb35e63f4c0a633e447fd88bc3e644c0bd528`

최신 native 영향 범위는 run-1 6,913 passed / 408 skipped / 38 warnings / 62 subtests passed, run-2 9 passed로 총6,922건 통과했고 두 로그 모두 NEW0이다. 최신 소스와 문서 delta 독립 최종 검토는 Critical0 / Important0 / Minor0이었다.

동일 조건 첫 SIM `sim-7a0bb35e63-6537e8`은 중반 코너에서 pose/off_lane0.104m로 실패했다. settled_xy(-0.733093, 0.340562), 목표 거리1.524783m, via0.543m였다. 주행684표본 모두 learned_drivable, fallback0, nonnull revision678개는 고정 revision과 일치하고6개는 metadata 누락이다. 열린 junction 수용187회·먼 출구 거절38회이며 새 local alignment 활성화는0회였다. final cmd·odom0, lease released, left_running 빈 목록, 산출물 회수·native 정리 완료, lane_return SKIP이다.

90.375초 s3.623에서 current-here -18.56도와 미래 안내 +42.37도가 충돌했다. 오른쪽 target(0.227, -0.090), near centre(0.163, -0.083), near right opening(0.213, -0.105)이 있었으나 explicit guide의 왼쪽 pivot을 선택했다. 실제 floor prefix가0.18m를 넘어 이어진다는 이유로 local-floor 증거가 비어 정렬 분기는 활성화되지 않았다. 후속 진단은 도로 끝 판단과 bounded 제자리 정렬의 근거리 관측 범위를 구분한다. ROI의 끝을 도로 끝·junction·opening으로 표시하지 않으며, 같은 실패 후보를 수정 없이 재실행하지 않는다.

- result.json SHA256: `f6585e04cea1ee4a174f43ff1fd969a6a0d7cecc32b535a8a9446adebfd69c2f`
- observations.jsonl SHA256: `0bb8fd00de5770c987d983f07514be9f3e1575d0d74e44200bf3685a9ddfa5df`
- run.txt SHA256: `c5e33cf7ab22bda54bb050b9a8bd13c11a6e4f8545a0168c3353432b9dc5b4aa`

## 도로 끝과 근거리 정렬 ROI의 분리

HEAD `5be728c2ebc23e333b3d1762e88153856d1e6dde`

7a0 실패 지점000722·000723·000724 PNG를 같은 모델로 native 재생했다. 000723에서 실제 연결 floor119행 중 가까운42행은 x0.139118..0.179172m, y-0.064225..-0.081173m였고 더 먼 연결은 x0.473155m까지 이어졌다. 새 후보는 검증된 연속 raw prefix의 첫 점부터 처음 x>=0.18m이 나오기 직전까지를 정렬 ROI로 사용한다. 이는 종전의 “전체 prefix가 짧게 끝나야 한다”는 입장 조건을 의도적으로 바꾸는 것이다. ROI 끝을 도로 끝·closed·junction·opening으로 표시하거나 전진 후보·정렬 수명 종료·예산 재생성에 사용하지 않는다.

최소4개 실제 raw 행, 원본 픽셀과 연결 픽셀의 floor 지지, source/current 근거리·동일 side, fresh current-here 일치와 첫 실측점 기반 기존 회전 상한은 유지한다. 928d882 native RED2개 뒤5be 관련197 passed/skip0/NEW0, 7a0 이후2커밋 size-range 통과였다. 독립 safety 검토에서 추가 material finding은 없었다.

- 000723 PNG SHA256: `fc4ac55c609d75f279e32f8d2fc21a8d8dcd9dc2a0a2ffc3672375d2b6ca2692`
- native mask packbits SHA256: `da9f5ddecc0b9d1b39f307f81d2e6b3fb6900850d1b587e53e3cb7902cb3fa69`
- native replay JSON SHA256: `56f77f8977f855d1bdbb3678c2a6e3fbe3c1130ac841a71e4f2a803e6fa2261b`

## 회전 중 현재 좌표 ROI와 예산의 연속성

HEAD `b8e9ac4ebe9c395bb412feafdbd48f03a0ba8268`

5be 별도 최종 검토에서 Important1을 확인했다. source ROI 끝 x0.179m가 오른쪽 yaw -0.05rad 변화 뒤 current x0.18m 밖으로 나가면, 앞쪽에 충분한 유효 점이 남아 있어도 전체 정렬이 거절됐다. native c8f788 회귀1개 NEW, cached source의 동일 전환을 검증한24f083 회귀1개 NEW로 재현했다.

현재 좌표에서도 같은 raw prefix의 첫 점부터 최초 범위 이탈 직전까지만 선택한다. 최소4개 원본 점을 유지하고 첫 점을 건너뛰거나 뒤의 재진입 점을 붙이지 않는다. 첫 점이 뒤로 가거나 남은 지지가 부족하면 기존 후보/HOLD로 남는다. episode origin·초기 limit·누적 yaw는 다시 만들지 않는다. 최신 actual diff는 소스 커밋 전 독립 safety 검토에서 추가 material finding이 없었다. 최신 native 회귀·영향 범위·SIM은 별도 검증한다.

b8e9 최신 관련8파일은 native200 passed / skip0 / NEW0이며, 7a0 이후5커밋 size-range 통과다. 별도 최종 소스 검토의 Important1을 닫고 Critical0 / Important0 / Minor0을 확인했다. 최신 영향 범위와 반복 SIM은 아직 진행 전이며 수용 HOLD를 유지한다.

## dfca 영향 범위와 후반 정렬 수명 실패

HEAD `dfca5bc48b68a068f8c60d892dba16e577e90b26`

native 영향 범위는 run-1 6,905 passed / 408 skipped / 38 warnings / 62 subtests passed, run-2 9 passed로 총6,914건 통과했고 두 로그 모두 NEW0이었다. 소스와 문서 delta 독립 검토는 Critical0 / Important0 / Minor0이다.

동일 조건 첫 SIM `sim-dfca5bc48b-42bb40`은 s5.357에서 stall60초로 실패했다. settled_xy(-1.229924, -0.466980), 목표 거리1.763511m, via0.007m였다. 주행1,039표본 모두 learned_drivable, fallback0이다. nonnull revision1,034개는 고정 revision과 일치하고5개는 metadata 누락이다. 열린 junction 수용200회·먼 출구 거절77회, local alignment는76.625초 left와133.625초 right 두 번 활성화됐다. final cmd·odom0, lease released, left_running 빈 목록, 산출물 회수·native 정리 완료, lane_return SKIP이다.

133.625초에 시작한 오른쪽 정렬은 limit0.4417rad였다. 이후 실제 왼쪽 관측 출구를 따라 전진했고138.0초의 odometry 기준 origin 이동은 약0.150m였다. 하지만 _observed_turn이 current-here -18.77도와 곡선상의 먼 target bearing 약+25.3도를 비교해44도 차이로 거절했다. 같은 current 경로의 가까운 첫 구간 진행 방향은 약-0.78도로 current-here와 기존30도 범위에서 맞았다. 다른 coverage·연결·target/opening 거리 조건은 통과했다. 139.75초 새 왼쪽 pivot이 이전 오른쪽 episode의 spent HOLD에 막혔다. 같은 실패 후보를 수정 없이 반복하지 않으며 수용 HOLD를 유지한다.

후속 native eef043 회귀3개 NEW로 실제138초 near 방향 일치·측정된 곡선 전진 후 이전 상태 종료·sideways-first 거절의 누락을 재현했다. fixture는 raw odom145개를 native OdomHistory로 보간하며 origin·source·current 시각과 원본 관측 해시에 결속한다. 방향 비교를 검증된 가까운 첫 연결 구간의 current tangent로 수정한다. 근처 점을 바라보는 bearing 자체도 tangent가 아니므로 대체 근거로 쓰지 않는다.

- result.json SHA256: `97901ca696f59695eeb846edf69d540b5af0b17cbed441d52a80c110ac864cbb`
- observations.jsonl SHA256: `f944fcf58821d8bde3dd89b12696e2be1689c81d8fb125576279e8b233828573`
- run.txt SHA256: `e26d2c020588757a30919b8ddd67fd61f435198ac7a7bdd8ecad576cf53b75f3`

## 가까운 진행 방향으로 곡선 전진 수명 종료 검증

HEAD `eeb3a746e34ccf8821a490e7004d52276cbc5f73`

_observed_turn의 방향 비교만 검증된 current path 첫 segment tangent로 바꿨다. 기존30도 한도, 실제 origin/source/current 이동, fresh 관측, 연결·coverage·target/opening 결속, 불확실 odometry 거절과 누적 회전량 예산은 유지한다. 첫 segment는 잡음에 민감할 수 있으며 반복 SIM에서 수용 여부를 별도로 확인한다.

eef043 native RED3개 뒤eeb3 관련9파일203 passed / skip0 / NEW0으로 종료했다. 실제138초의 곡선 관측과 odometry로 이전 spent episode가 종료되어 다음 왼쪽 pivot을 막지 않는 것을 확인했다. sideways-first 경로는 near 위치나 먼 target이 맞더라도 진행 방향이 다르면 거절한다. 기존 CURVED·tight bend·불확실 odom·source 이동·예산 보호 회귀도 통과했다. 소스 커밋 전 독립 safety 검토에서 추가 material finding은 없었으며 dfca 이후2커밋 size-range 통과다. 최신 영향 범위·동일 조건 연속2회 SIM은 별도이며 수용 HOLD다.

## d42 반복 결과: 1 PASS / 1 FAIL과 열린 직진로의 추정 artifact

HEAD `d42e93133b38a703a51611e4943431614010e4ae`

native 영향 범위는 run-1 6,908 passed / 408 skipped / 38 warnings / 62 subtests passed, run-2 9 passed로 총6,917건 통과했고 두 로그 모두 NEW0이었다. 소스·문서 최종 검토 Critical0 / Important0 / Minor0, dfca 이후3커밋 size-range 통과다.

첫 SIM `sim-d42e93133b-e250bd`은 arrived/PASS였다. settled_xy(0.405612,-0.506585), 목표 거리0.127497m, via0.030m였다. 비영 속도 명령의 최초~마지막 구간에서 learned_drivable1,527개·fallback0, nonnull revision1,514개 고정 일치·누락13개, 열린 junction296회·먼 출구 거절86회였다. 이 구간의 정렬 예산 HOLD2회를 포함하므로 무중단 주행으로 표시하지 않는다.

두 번째 `sim-d42e93133b-09c9be`는 realign HOLD 뒤 s4.851의 stall60초로 실패했다. settled_xy(-1.276760,0.023497), 목표 거리1.886557m, via0.031m였다. 비영 속도 명령의 최초~마지막 구간에서 learned_drivable874개·fallback0, nonnull revision869개 고정 일치·누락5개, 열린 junction181회·먼 출구 거절62회였다. 종단 realign HOLD는 마지막 비영 명령 뒤에도 이어지므로 이 구간 집계와 별도로 keep_debug의119.75초 이후 관측으로 확인했다. 두 실행 모두 final cmd·odom0, lease released, left_running 빈 목록, 산출물 회수·native 정리 완료, lane_return SKIP이다.

두 실행의 pointer·render·paint target·lap·scenario·skip·stall·spawns·places JSON이 동일함을 대조했다. 모델·manifest는 각 시작 전 native 해시로 재확인했다. 같은 조건1 PASS / 1 FAIL이므로 연속2회 조건은 미달이며 수정 없이 세 번째를 반복하지 않는다.

두 번째119.75초에는 guide here/ahead +1.41도, ahead0.601m, near centre(0.163,+0.011)인데 source target(0.194,-0.133)이었다. exact PNG000957·000958·000959를 같은 모델로 native 재생해 band median(0.222034,-0.024891), reach0.25m를 확인했다. 선택 k_path -4.801843의 보이는13개 arc 표본 중8개가 non-way였고, 같은 band의 k_chord -0.997280은 보이는45개 표본에 non-way가 없었다. 이는 source 추정 artifact의 근거이며, sample 사이 pixel 연결과 최종 current/smoothing 동작은 별도로 검증해야 한다. 화면 밖·사각은 unknown이며 clip해 floor로 인정하지 않는다. 검증된 same-band 대안이 있을 때만 source estimate를 보정하는 좁은 후보를 검토하며, REALIGN·CORE·near 출구 입장은 유지한다.

- 첫 result SHA256: `f32758bc506ef9f9b0d99f0fc37b949da91153f01aea8c5f550f789d9be4d0b1`
- 첫 observations SHA256: `89cc08326fed150ded21fb59c3abdde2f42998e3cba61a0ad2808ee2b4d5a20b`
- 두 번째 result SHA256: `253f5ad228e6f8b04614b13260744360e0bbd0db3a087d23ff4cfc3dfba72696`
- 두 번째 observations SHA256: `15f0ad5d7e2b2a6b9f9c9f1afaebe08d1bd6d61551dd1df28596516aa7f86d53`
- 재생 PNG SHA256: `90f958b5f3a183c53197449da9e161c6080c1cfebe4460976df0fd803cbab6b1`
- native mask packbits SHA256: `897ffa891ed446bb74b76103b54b39afa4d28667e43b0cca8f3e82ef926c5aa0`
- native replay JSON SHA256: `2efd886f7350f9f625917bd91d3d2c728fe192c995b5a4c811ac7456df674b38`

## 가시 픽셀 지지에 한정한 source 곡률 보정

생산 HEAD `9550f4c9ce2422e6bb4350153f9105376fc4ab2e`.

기존 source arc가 가시 non-way 픽셀을 지나고 같은 confidence band의 기존 chord가 가시 바닥에 지지될 때만 교체한다. 투영 표본 사이 픽셀 연결도 검사하며 화면 밖을 clip하여 바닥 근거로 만들지 않는다. 불확실하거나 대안이 검증되지 않으면 기존 후보를 유지한다. 정상 굽은 바닥의 기존 곡률도 유지한다. 이 검사는 source 추정 artifact 보정이며 최종 smoothing/current 변환 이후 궤적 전체의 바닥 보장을 뜻하지 않는다. REALIGN·CORE 명령 권한·정렬 예산을 완화하지 않는다.

원본000958의 실제 마스크를 RLE fixture로 결속했다. native4e0 회귀 RED6개 뒤9550 관련10파일210 passed / skip0 / NEW0이었다. 픽셀 공백·완전 offscreen·보정 조건 부재·정상 굽은 바닥 보존과 이전 smoothing 뒤 기존 REALIGN 통과 회귀를 포함한다. 독립 safety 검토와 별도 최종 소스 검토는 Critical0 / Important0 / Minor0, d42 이후3커밋 size-range 통과다. 새 후보의 영향 범위 및 동일 조건 연속2회 SIM 전까지 수용 HOLD이며 d42의 첫 PASS를 이월하지 않는다.

## 24cc 반복 결과와 안내 유실 중 정렬 odometry 추적

검증 HEAD `24cc04516bd59c93b1a07c73f00abe72f12b6125`의 native 영향 범위는 run-1 6,928 passed / 408 skipped / 38 warnings / 62 subtests passed, run-2 9 passed로 총6,937건 통과했고 두 로그 모두 NEW0이었다. 별도 소스·문서 최종 검토0/0/0, d42 이후4커밋 size-range 통과다.

첫 SIM `sim-24cc04516b-04d5e4`은 arrived/PASS, settled_xy(0.425275,-0.500844), 목표 거리0.108119m, via0.036m였다. 비영 명령 최초~마지막 구간의 learned_drivable1,458개·fallback0, nonnull revision1,451개 고정 일치·누락7개, 열린 junction329회·먼 출구 거절67회였다. drivable_closed1회를 포함하므로 무중단 주행으로 표시하지 않는다.

두 번째 `sim-24cc04516b-2565db`는 마지막 코너에서 stall60초/진행6.848m로 실패했다. debug station은6.872735m, settled_xy(-0.069592,-0.355832), 목표 거리0.621837m, via0.030m였다. 같은 명령 구간 learned_drivable1,292개·fallback0, nonnull revision1,289개 고정 일치·누락3개, 열린 junction236회·먼 출구 거절62회, drivable_closed1회·recentre_alignment_spent5회였다. 종단 spent HOLD는171.5초 이후에도 계속되므로 명령 구간 집계와 별도로 보존한다. 두 실행 모두 final cmd·odom0, lease released, left_running 빈 목록, 회수·native 정리 완료, lane_return SKIP이다. pointer·render·paint target·lap·scenario·skip·stall·spawns·places JSON 동일 및 각 실행 전 native model/manifest hash를 확인했다. 1 PASS/1 FAIL로 수용 HOLD이며 수정 없이 세 번째를 반복하지 않는다.

- 첫 result SHA256: `0b240dff0ef53cc8e3a6c754724f06749519e00e4f21aeacfd38c8ddac4b67ee`
- 첫 observations SHA256: `3fb2bb70ed0af6b2ca7f0e515de05dffddc6ccb762e61a8602269c913fd00c9d`
- 두 번째 result SHA256: `eb755a9e843867a975b947f43090c9a26d4557918b86fab6625b61b6c03647b2`
- 두 번째 observations SHA256: `7a06842c4954330fdc505d225e36efda5a189a5cdaefba2051d691cc555d0dd1`

두 번째155초의 LEFT 정렬 limit0.4561 뒤156.875·157·157.125초에는 SelectedRoutePrior가 없지만 camera/way·odom은0.125초 간격으로 계속됐다. observed_route_candidate의 early return으로 기존 episode 추적까지 빠져157.25초에 마지막 갱신 이후0.5초를 실제 odom 공백 한도0.2초와 비교해 uncertain을 영구 설정했다. native 원본 재생12가 이를 재현했다. 모든 관측 프레임의 odom을 추적하면 기존160.375초 straight 증거(ahead0.473m, current 실제 변위0.181521m, source0.177060m)로 이전 episode가 종료된다. 재생은 recorded strategy의 switch_pending도 복원했으며, 누적 경로 s를 원점 변위로 대체하지 않았다.

- native 재생12 analysis SHA256: `b75d86f9a345ec06b885786d5481ebcc97005c212a7494204d4e0944fd1a725f`

생산 HEAD `1941d5025efbd7b8c2e41e392bb7d0a1a6f83bee`.

기존 episode의 시간·pose 연속성 검사와 누적 절대 yaw 갱신을 `_track_alignment`로 분리한다. 선택 안내가 없는 경로는 기존 episode 추적만 하며 후보 객체·출력을 그대로 반환한다. 이 경로는 상태를 생성·종료하지 않는다. 안내 복귀 후 기존 실제 이동·fresh 관측·straight/curve 종료 조건을 평가하며 실제 odom 공백·jump·reset의 uncertainty는 유지한다. seen_exit·기하 기준·회전량 예산·CORE 권한은 바꾸지 않았다. 원본168개 odom과 실제 안내 공백·160.375 관측을 fixture로 결속한 e12 native RED4개 후1941 관련12파일 통과/skip0/NEW0, 독립 소스 safety 검토 material finding 없음, 24cc 이후3커밋 size-range 통과다. 최신 영향 범위·같은 후보 연속2회 SIM 검증 전까지 수용 HOLD다.

## f976: 코너 통과 후 조기 도착 선언으로 수용 실패

검증 HEAD `f976d6001a0ce85948cd0be9d5c1f3f41f0d8e2f`.

관련 native220 passed/skip0/NEW0 및 독립 소스·문서 최종 검토0/0/0 뒤 영향 범위는 run-1 6,918 passed / 408 skipped / 38 warnings / 62 subtests passed, run-2 9 passed였으나 release guard1건이 실패했다. 동결 기록의 전체 source SHA 바로 뒤에 붙은 한국어 조사가 high-entropy-token으로 오인되었다. SHA 값은 보존하고 HEAD 단독 문장으로 표기를 수정했으며 해당 guard 재검증 전이다. 통과 수와 별개로 이 영향 범위 실행은 FAIL/NEW1이다.

첫 SIM `sim-f976d6001a-40c170`은 마지막 코너와 전체 경로를 통과해 states arrived였지만 실제 정착 거리가 기존0.15m를 초과해 FAIL이었다. settled_xy(0.336366,-0.507173), 목표 거리0.196729m, via0.032m다. 비영 명령 구간 learned_drivable1,425개/fallback0, nonnull revision1,418개 고정 일치/누락7개, 열린 junction292회/먼 출구 거절87회, drivable_closed1회·일시적 realign38회였다. final cmd·odom0, lease released, left_running 빈 목록, 산출물 회수·native 정리 완료, lane_return SKIP이다. 같은 소스로 두 번째를 반복하지 않는다.

Fleet API 원본의 마지막 running pose는(0.230,-0.510), arrived에 저장된 pose는(0.246,-0.511)로 목표(0.533086,-0.509)보다 약0.287m 전이다. Fleet의 matching stop executing + pass_window0.3m 예외가 도착을 인정했다. CORE는 stop 접수 즉시 executing이며 실제 hold가 아닐 수 있다. 실제 settled 오차0.196729m와 도착 선언을 분리하고 기존0.15m 수용 기준을 유지한다. terminal 처리 뒤 authority 갱신 중단은 소스에서 확인했으나 기록에 stop held/seq 상세 receipt가 없어 최종 정지의 직접 원인까지 확정하지 않는다.

- result SHA256: `b8eee31c678b0a18164f0c999f771c2850302f7bfdfa34b49407b3a9aa74cfcd`
- observations SHA256: `774144fa428239691e023b7b390c84e8731f7e18c28a3728bc41feb8c1ea7f78`
- run SHA256: `233ab91544635e6fdedc774acdba011cf350ebfdc0c6a8859457dcbd29e846e4`

## 실제 정지 목표 거리로 lane 도착 판정 결속

생산 HEAD `737630e6ba6cc0164426dce631c752f0bb1fdbbb`.

Fleet lane 도착은 해당 segment의 stop 수락 기록과 실제 검증된 MapPose가 기존 arrive_lane_m 이내라는 증거를 요구한다. 선택된 arc의 s_to에서 기존 traffic hold-back을 뺀 실제 정지 목표와 Euclidean 거리를 비교해 접근 중 executing·overshoot·측면 오차를 구분한다. stop 수신 직후 executing을 실제 hold로 간주한 pass_window0.3m 예외를 제거했다. 기존 arrive_lane_m0.15m·free 판정·CORE stop 권한·재전송/해제 정책은 유지한다. 목표 전에 CORE가 실제 hold하면 자동 전진시키지 않고 기존 trip 정체 처리를 유지한다.

새 native 회귀에서 접근 중 executing의 조기 arrival을 확인한 RED4개 뒤 관련6파일은254 passed / skip0와 기존 문서 secret guard1 FAIL/NEW1이었다. 초과 거리에서 실제 hold를 만들어도 running 유지,0.14m 도착, overshoot·측면 거리·traffic hold-back 및 stop 거절 회귀를 포함한다. 해당 실행의 wrapper는 실패 로그의 한국어 출력 중 encoding 오류로 종료했으며 보존된 run-1 결과로 판정을 대조했다. 문서 SHA 형식 수정은 당시 커밋에 포함되지 않았으므로 수정 문서 HEAD의 guard 재검증 전이다. 독립 safety·최종 소스 검토0/0/0, f976 이후4커밋 size-range 통과다. 새 후보 영향 범위·동일 조건 연속2회 SIM 전까지 수용 HOLD이며 임계값을 바꿔 이전 실패를 PASS로 재해석하지 않는다.

## 7956 중간 코너 실패와 곡선 근거리 입장 기준

검증 HEAD `7956cd9d315dbea17fcf26bbbcb15dd76ba0f501`.

수정 문서의 release guard80 passed/skip0/NEW0을 확인했다. Fleet 영향 범위 실행은 SSH 연결 유실 뒤92%에서 Terminated로 끝났고89%의 F 표시1개가 남았다. 완료 summary가 없어 known_failures 파서의0건을 NEW0 근거로 사용하지 않는다. native collection으로 실패 위치를 module_structure의 ratchet 검사로 좁히고 별도 재실행에서 정확히 재현했다. 기존 테스트 중복 삭제로 test_trip_runner.py가1,757→1,748줄이 되어 저장된 ratchet도 낮추라는 실패다. 수용 범위를 줄이거나 테스트를 제외하지 않고 row를1,748로 갱신한 후 해당 구조 검사40 passed/NEW0을 확인했다. 전체 영향 범위는 재검증 대상이다.

첫 SIM `sim-7956cd9d31-0212c5`는 중간 코너 spent HOLD 뒤 stall60초/진행3.841m로 FAIL이었다. debug station3.872m, settled_xy(-0.748327,0.484273), 목표 거리1.621299m, via0.524m다. 비영 명령 구간 learned_drivable755개/fallback0, nonnull revision751개 고정 일치/누락4개, 열린 junction198회/먼 출구 거절55회, spent23회였고 이후 종단 HOLD도 이어졌다. final cmd·odom0, lease released, left_running 빈 목록, 회수·native 정리 완료, lane_return SKIP이다. 같은 소스로 두 번째를 반복하지 않는다. 목표에 못 갔으므로 Fleet 도착 보정의 SIM 수용은 아직 검증하지 못했다.

- result SHA256: `dad811f28d3212e4900d9fef5f6fb2cf53e3ebea818f175021530bec063c8c87`
- observations SHA256: `3b27344e7f46bd78178ce2857ba1b5e081c673f38756b79e08ab10d374ee1f71`
- run SHA256: `e4fad71875d67a5709c574f4995e8e961c18172ccbbce782cf70dbadd6ff90d9`
- native 재생13 analysis SHA256: `d7cb4cee00aa076cb83c29303ddeac6e656319b06032bb95424839760c7a3b95`

native 재생13에서95.375초 RIGHT episode는 불확실성 없이 추적됐고 선택 출구와 seen_exit도 LEFT로 일치했다.97.25~98.75초 곡선 증거는 통과했지만 실제 이동이0.14m 미만이었다.100.125초 이후에는 실제 이동을 만족하고 가까운 tangent·연결·선택 target/opening도 맞지만 가까운 곡선이 직선 body-axis에서0.03m 이상 벗어나 종료를 막았다. 원본100.125/100.25/100.375의 source 첫 점 y는0.0376/0.0400/0.0420m다. 기록 odom으로 current 좌표에 옮긴 y는0.03587/0.03830/0.04033m이며 선택 current 원호의 같은 x와 오차는 약0.0060/0.0084/0.0106m다. 추가 재생14는 SSH banner timeout으로 실행되지 않았고 이 수치 계산은 회수한 기록의 stdlib 분석이며 제품 실행으로 표시하지 않는다.

생산 HEAD `d8fe6d1d022c42becd920bc64bf7db5529f7a1dc`.

기존 중심축0.03m 입장은 유지하고, 축 밖인 가까운 점은 guard에 전달된 선택 current 후보의 short arc와 같은 x에서0.03m 이내일 때 추가 인정한다. 이는 곡선의 공간적 입장을 넓히는 변경이며 숫자가 같다는 이유로 보호 범위가 동일하다고 주장하지 않는다. 관측점을 옮기거나 path를 수정하지 않으며 기존 first x·연결·gap·coverage·target/opening·here/tangent30도·실제 source/current 이동·uncertainty·회전량 예산을 유지한다. finite/영점/직선 근접/원호 정의역 밖을 처리하고 새 저장 경로나 TTL 예외는 추가하지 않는다.

원본156개 odom·3개 관측 회귀에서6ea native RED는 실제 positive/종료4개와 신규 helper 미구현10개로 NEW14/기존 negative1 passed였다. 첫2b 구현은 새15개는 통과했지만 기존 정상 직선-prefix 곡선3개가 실패했다. 최종 검토 Important1을 보존하고, 기존 중심축 입장을 OR로 복원한 d8에서 관련13파일235 passed/skip0/NEW0으로 재검증했다. 독립 safety 재검토와 최종 소스 재검토0/0/0,7956 이후4커밋 size-range 통과다. 반대 곡률·평행 오프셋·원호 다른 branch/정의역 밖·비유한 값·직선 근접 회귀를 포함한다. 최신 전체 영향 범위·동일 후보 연속2회 SIM 전까지 수용 HOLD다.

## 최종 고정 조건 주행 SIM 수용: 연속2회 PASS

검증 HEAD `a24ed73549294d7a5a61fb097c320acf1f881cde`.

생산 Perception은 d8, Fleet 도착 판정은737이다. 소스·문서 별도 최종 검토0/0/0 및7956 이후5커밋 size-range 통과 후 이 HEAD를 두 실행과 전체 영향 범위 동안 고정했다. 이전 후보의 PASS를 이월하지 않았다.

영향 범위는 f976 이후 selector가 선택한86개 경로를 Fleet1·Perception/CORE/SIM15·기타70경로의3묶음으로 나눴다. 원본과 분할 경로 Counter 일치를 assert했으며 제외한 경로는 없다. native wrapper exit0, run-1 5,592 passed/317 skipped/2 warnings, run-2 4,354 passed/128 skipped/2 warnings/62 subtests passed, run-3 3,027 passed/331 skipped/38 warnings로 총12,973 passed/776 skipped/42 warnings/62 subtests passed다. 완료된 세 로그 각각 known_failures NEW0을 확인했다. skipped는 통과로 세지 않으며 이전 중단 실행을 완료 증거로 대체하지 않는다.

| 항목 | 첫 실행 | 두 번째 실행 |
|---|---|---|
| run | sim-a24ed73549-8dce8c | sim-a24ed73549-eb4e59 |
| 결과 | PASS / arrived | PASS / arrived |
| settled_xy | (0.534763,-0.513414) | (0.532310,-0.501539) |
| 실제 목표 거리 | 0.004721585m | 0.007500985m |
| via 거리 | 0.029m | 0.029m |
| API arrived에 저장된 pose | (0.386,-0.510) | (0.396,-0.500) |
| 비영 명령 구간 learned_drivable | 1,481 | 1,467 |
| 같은 구간 fallback | 0 | 0 |
| nonnull revision 고정 일치 | 1,475 | 1,459 |
| revision metadata 누락 | 6 | 8 |
| 열린 junction 선택 / 먼 출구 거절 | 263 / 71 | 272 / 81 |
| final cmd / odom | (0,0) / (0,0) | (0,0) / (0,0) |
| lease / left_running | released / 빈 목록 | released / 빈 목록 |
| wrapper·회수·정리 | exit0·완료 | exit0·완료 |

비영 명령 구간은 최초~마지막 nonzero cmd의 receipt 시간으로 제한한다. 두 구간의 drivable reason 집계는 비어 있지만 CORE의 교통·횡단보도 대기까지 무중단이었다는 뜻은 아니다. revision 누락6/8개는 cached learned 소비 경로와 일치하는 metadata 한계이며 개별 표본의 revision을 직접 입증하지 않는다. nonnull 표본은 모두 고정 revision과 일치한다.

두 result JSON의 pointer·render·paint target·lap·scenario·skip·stall·spawns·places가 동일함을 대조했다. 각 실행 전 native ONNX·manifest hash를 재검증했다. 모델 revision은 lane-seg-20261010-451f0f85, ONNX SHA256은 `451f0f85b390d6601dc38c60865ed721936ff407845f7a8196099ae9a110f3d2`, manifest SHA256은 `0b0c4e3de8b58e128dc195c5362f3ba9688154f7771ae62960ba68ee9903a2d2`다. Fleet native binding도 두 실행 모두 source_revision이 위 HEAD와 일치하며 world/graph/URDF hash는 기존 고정값과 일치한다. API arrived 저장 위치도 실제 정지 목표의 기존0.15m 이내이고,10초 settle 뒤 실제 목표 거리를 별도로 통과했다. 도착 임계값이나 lane_return 제외 조건은 완화하지 않았다.

- 첫 result SHA256: `62ecfafd747c0828569c9486830d71fed61d51527af66665a4c0d6cdfecf9695`
- 첫 observations SHA256: `fd8524315a0d2bbc00fdf57192f72947f3a4ed037701cadee8767a9349bf33fa`
- 첫 run SHA256: `5df1025d6e1f58a21eeb5c01d0dbad15ddc2334be4be2ac73e6f5abb3a4c9ce1`
- 두 번째 result SHA256: `cc8493089e455ce5c9fb0189b3545022533e2a2cd618e40473e54b0ef39c3682`
- 두 번째 observations SHA256: `cc8b44ba7b01e1f29850376628fe2064b8b100d2025fdde013437a9f5a183f4c`
- 두 번째 run SHA256: `8e31573246bbf206a1e057dbdf05598f04eedbcad84e4790ed697f876414fb6b`

충족한 범위는 고정 지도·고정 학습 모델·native model-pose·GPU·lap·stall60·record·기존 lane_return SKIP 조건의 주행 SIM이다. 실제 Pinky·현장 localization·lane_return·동적 모델/지도 교체·main 착지/push는 검증하거나 수행하지 않았다. Perception의 가시 source 픽셀 보정은 최종 smoothing/current 궤적 전체의 안전 보장이 아니다. 전체 모듈·FIELD gate를 승격하지 않으며 후속 문서 커밋은 이 SIM 소스를 바꾸지 않는 증거 정리다.
