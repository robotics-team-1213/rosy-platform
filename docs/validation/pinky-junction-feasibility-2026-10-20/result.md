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
