# 20261010 drivable 검수 패키지 확인

2026-10-11 KST. 소스 기준 `7c0f8c93a3`, branch `feat/perception-fitness-pipeline`.
사용자가 알려 준 Desktop의 20261010 검수 데이터를 모델 PC와 AI PC에서 읽기 전용으로 확인했다.
판정은 **기존 drivable 기준선 자료 확인 / 새 도로면 적합성 HOLD**다.

## 발견한 산출물과 직접 확인

| 산출물 | 위치 | 확인한 버전 |
|---|---|---|
| 최초 패키지 | 모델 PC `~/Desktop/drivable-v13-crop128-20261010` | `v13-drivable-20261010-ede0ae96` |
| 후속 패키지 | 모델 PC `~/Desktop/drivable-v13-crop128-20261010-v2` | `v13-drivable-20261010-451f0f85` |
| 후속 원본 데이터 | AI PC `~/drivable-full-20261010/dataset-v2` | `v13-drivable-human-20261010` |

v2 Desktop 패키지에는 dataset 디렉터리가 없다. README와 head/run.json의 원본 위치를 따라 AI PC에서 원본을 확인했다. 패키지를 복사하거나 모델을 교체하지 않았다.

| 읽기/해시 검증 | 결과 |
|---|---|
| 최초 패키지 SHA256SUMS | 47개 일치, 실패 0 |
| v2 패키지 SHA256SUMS | 63개 일치, 실패 0 |
| 최초 데이터 image/mask SHA256 | 2,856개 일치, 실패 0 |
| v2 데이터 image/mask SHA256 | 5,538개 일치, 실패 0 |
| v2 frame review 기록 | 2,769개 모두 `status: done`, `source: human_edit` |
| v2 동일 image SHA256의 split 중복 | 0 |
| v2 동일 image SHA256의 데이터 내 중복 | 0 |

최초 dataset manifest 파일 SHA256은 `da3e9919474e93b476aec96911e1e892de3247e35ac1516b8b6d4cbeecc3ec95`다.
v2 dataset manifest 파일 SHA256은 `0ef7359a16fcf8449853cf545b1d9fdca79b768f222a616dc06e29a3ee255a94`이며 model manifest와 head/run.json의 선언에 일치한다.
이 값은 **manifest 파일** SHA256이다. 기존 store의 전체 디렉터리 content SHA로 간주하지 않는다.

| 데이터 부분 | train | val | test |
|---|---:|---:|---:|
| 20261009 기존 검수분 | 1,075 | 190 | 163 |
| 20261010 추가 검수분 | 1,092 | 168 | 81 |
| v2 합계 | 2,167 | 358 | 244 |

추가 test 81장은 `one_lane` 67장, `flat_lines` 14장이다. AI PC review/status.json에는 추가분 1,341개의 done 시각이 있으며, dataset 생성 소스는 이 done 항목의 saved mask를 사용한다. 생성 시 rows 0..109를 255로 되돌린다. saved mask와 최종 mask의 화소별 일치 및 검수자 독립성은 이번 확인 범위 밖이다.

## 의미와 평가 사용 범위

README와 dataset 설명은 drivable을 로봇에서 흰 선을 넘지 않고 연결되는 바닥으로 정의한다. 차선 밖 바닥은 제외하고, 선을 넘지 않고 연결된 갈림길의 가지는 유지한다. v2는 차선 종류에 따른 도로 측면과 사람 판단도 사용한다. 따라서 D-659/D-663의 **모든 가시 도로면 `road_surface/1`** 정답으로 자동 전환하지 않는다. 기존 구역 의미를 가진 기준선 및 재검수 원본으로 보존한다.

원본 classes/model에는 D-663 semantic 선언이 없다. 확인을 이유로 manifest를 수정하거나 `current_road_region/1`을 소급 부여하지 않았다. 현재 구역 정답으로 사용할 때도 기존 선/연결 규칙과 D-665의 stop-line/crosswalk 통과 규칙 차이를 검수해야 한다. 기존 masks에서 배경을 반전해 전체 도로면 정답을 만들지 않는다.

입력은 320x240으로 resize한 뒤 rows 112..239를 사용하는 128x320 crop이다. 정답·기준점·출력도 같은 좌표 변환에 결속해야 하며 상단 미예측 화소를 정상 음성으로 점수화하지 않는다.

v2 추가분은 이전 모델이 틀린 장면을 우선 포함하며 자동 초기 라벨에도 이전 head 결과가 사용됐다. 사람 수정 기록은 확인했지만, 이 사실만으로 모델과 독립적인 최종 수용 세트가 되지는 않는다. 동일 이미지 hash 비겹침은 확인했으나 원본 영상/capture group 단위 split 분리는 확인하지 못했다. frame에는 session/capture_group/identity/calibration/transform 필드가 없고, 이 dataset 디렉터리에는 기존 review authority/approval 결속 파일이 없다. 카메라 출처는 패키지에서 provisional로 선언한다.

패키지에 저장된 성능 수치는 재추론 결과가 아니다. README의 floor-only IoU와 model manifest의 IoU는 평가 분모가 다를 수 있으며 섞지 않는다. 새 모델 비교 시 분모·조건·출처를 보고서에 함께 기록한다.

## 다음 실행과 제한

기존 모델·검수분·추가 어려운 장면은 버전과 원본 hash를 유지해 기준선으로 활용한다. 새 도로면 검수는 D-663 road_surface classes로 별도 작성하고, 현재 구역 정답은 로직 평가용으로 분리한다. 원본 영상 단위 예약/split, 독립 검수 authority, 실제 기준점 투영, 실물/시뮬레이션별 coverage와 사전 고정 profile은 후속 결속 대상이다.

원시 확인 로그는 X: 세션 `2026-10-11--213319--perception-fitness-pipeline--024175/evidence/desktop-20261010-*`에 있다. 주소·계정·원본 이미지·모델 파일은 공개 저장소에 넣지 않는다. 이번 확인은 새 학습·모델 재추론·시뮬레이션·장치 지연·배포·주행 활성화·현장 수용 증거가 아니다.

## 저장 검수 마스크의 직접 대조 (2026-10-12)

동일 dataset manifest SHA256을 다시 확인하고 추가 검수분 1,341장의 `review/saved` 마스크와 최종 dataset 마스크를 직접 읽었다. rows 110..239의 화소 불일치는 0, dataset rows 0..109에서 255가 아닌 화소도 0이다. 최종 mask 파일 hash 1,341개 모두 manifest와 일치했고 저장 검수 누락·크기 오류는 없었다. split은 train 1,092 / val 168 / test 81이다. 따라서 앞 기록에서 미확인이었던 saved mask→최종 mask 보존은 이 추가분에 한해 확인됐다. 기존 1,428장의 저장 검수 대조나 검수 독립성을 확대한 결론은 아니다.

readback 로그는 위 비공개 세션의 `evidence/desktop-20261010-saved-mask-readback-20261012.json`이며 SHA256은 `316647b1aa78512d47fe0b132f2b3dfeb55503fbe719b4fb65a5b38f1043422b`이다. 이 로그는 UTF-16로 저장된 원격 JSON 출력의 byte hash다. 기존 mask·classes·manifest를 수정하지 않았다. 현재 구역 기준선이라는 의미와 새 도로면 적합성 HOLD를 유지한다.

## upstream 원본 영상별 split 대조 (2026-10-12)

AI PC의 기존 `data-v13/manifest.json`에서 각 item의 image SHA256과 선언된 source_video_sha256을 읽고, 위 검수 데이터의 image SHA256에 정확히 연결했다. upstream manifest SHA256은 `846ab9310f43b2f75edd9d38cd2c6f5dd62a4e0771a72931ee5a20143741c04b`이다. 2,769장 중 2,519장이 단일 원본 영상 hash에 연결됐고, 250장은 연결되지 않았다. 둘 이상의 원본 영상 hash가 겹치는 모호한 image 연결은 0이었다.

| 선언된 원본 영상 그룹 | train | val | test |
|---|---:|---:|---:|
| 첫 그룹 | 674 | 234 | 166 |
| 둘째 그룹 | 220 | 0 | 45 |
| 셋째 그룹 | 503 | 31 | 0 |
| 넷째 그룹 | 112 | 47 | 0 |
| 다섯째 그룹 | 268 | 14 | 0 |

위 다섯 그룹은 같은 upstream 원본 영상 hash가 두 개 이상의 split에 존재한다. 나머지 두 연결 그룹은 train에만 194장과 11장이 있다. 따라서 앞 확인의 동일 이미지 split 중복 0은 원본 영상 단위 분리를 증명하지 않는다. 이 세트는 기준선/개발 자료로 보존하며 독립 최종 시험으로 승격하지 않는다. 새 최종 시험은 학습에서 제외하도록 사전 예약한 출처와 독립 검수 정답이 필요하다.

이 대조는 upstream 선언에 대한 연결이며 원본 영상 파일을 다시 hash한 물리 출처 검증은 아니다. 연결되지 않은 250장의 출처도 임의로 부여하지 않았다. 원본 group hash별 전체 표와 readback은 위 비공개 세션의 `evidence/desktop-20261010-upstream-source-splits-20261012.json`에 보존한다. 원본 데이터·split·학습 모델은 수정하지 않았다.

## 이전 촬영분·검수 산출물의 확대 탐색 (2026-10-12)

사용자가 이전 자료도 확인해 달라고 요청해 로컬 추적 제외 `data`와 시험 PC 세 대의 기존 보관 위치를 읽었다. 로컬 `data/teleop/learning`에는 영상 22개, `data/perception/raw`에는 bag 디렉터리 12개가 있다. bag 디렉터리에는 원본/compact 사본이 포함돼 독립 촬영 세션 수로 해석하지 않는다. 로컬 영상 22개의 파일 hash와 전체 매체 경로 목록을 비공개 세션의 `evidence/existing-footage-local-20261012.json`에 보존했다. 기존 ignore 규칙으로 숨겨진 자료를 탐색에서 누락하지 않도록 `rg --files --no-ignore`를 사용했다.

원격 탐색은 각 home 및 `/srv/rosy`, `/mnt`, `/media`의 깊이 6 이내에서 ROSY/Pinky/teleop 관련 영상·MCAP·DB3와 manifest를 찾았다. 모델 PC는 매체 596개/manifest 214개, AI PC는 109개/25개, 현장 PC는 22개/25개다. 이는 반복 checkout 사본·분할 bag·파생 영상·일부 upstream 예제까지 포함한 탐색 결과이며 새 원본이나 독립 정답 수가 아니다. 권한 거절은 모델 PC 2곳, AI PC 1곳에 있었고 깊이 밖·다른 PC·미연결 볼륨은 미확인이다. 전체 목록은 `evidence/existing-footage-{local,model,ai,site}-20261012.json`에 있다.

다음 두 원본 파일을 직접 hash해 앞 upstream 선언과 결속했다. 이는 7개 연결 그룹 중 2개 원본에 대한 추가 증거이며, 나머지 그룹과 연결되지 않은 250장 전체의 출처를 검증한 결과가 아니다.

| 원본 | 확인한 SHA256 | 연결된 검수 데이터 |
|---|---|---|
| 로컬 20261005T134540Z 카메라 영상 | SHA256 `a5dd55eb10d2514e405ecf9547b2e181c9da1cc713ee124943a7657ae2d499b9` | train 194장 |
| 모델 PC 20261006T091340Z 카메라 영상 | SHA256 `c41d9dc375035516096a32cff2b78471fe9b6747192691b2d24e3ed72c9dfbda` | train 11장 |

모델 PC의 20261008 촬영분에는 원본 hash와 capture group을 가진 준비 영상/프레임 8장 및 16장이 있다. 확인한 입력 JSONL에는 사람 정답·검수 완료·독립 authority 결속이 없다. 이름에 eval이 있어도 독립 수용 세트라고 판단하지 않는다. 기존 객체 검수 반환 하나는 `person_feet` 클래스, exported 0 / queued 20, reviewer authentication unverified라 D-602의 `person` 독립 정답으로 전환하지 않는다. 기존 고정 eval 세트 세 개도 LiDAR/trajectory 자동 라벨이며 독립 사람 정답이 아니다. Isaac의 OMX/OMY RGB·semantic·box 자료는 도로 지도 출처의 대체물이 아니다.

자료가 없다는 결론은 철회하고 원본·기준선·미검수 후보를 구분한다. 실제 새 도로면/현재 구역 정답 검수와 source 단위 학습 제외·독립성 확인이 남아 있다. 이 탐색은 데이터를 복사·재라벨·승인하거나 모델을 배포하지 않았다.

## 빈 도로면 검수 작업 준비 및 영상 프레임 대응 (2026-10-12)

앞서 찾은 20261008 두 촬영분의 준비 PNG 24장을 원본 MP4에서 지정된 `video_frame`까지 순차 디코딩해 대조했다. 이미지·영상 SHA256과 24/24 프레임 픽셀 일치를 확인했다. AI PC의 확대 탐색에서 발견한 manifest 25개의 `items`/`frames`/`samples` 행에는 이 후보의 이미지 hash 또는 원본 영상 hash가 없었다. 이는 검사한 manifest의 한정된 결과이며 전체 과거 학습·모델 비교 이력의 부재나 독립 최종 평가를 증명하지 않는다.

로컬 main SHA `ddcfbbcce0def51a62fe92075f1c749234dc554e`의 기존 검수 코드를 이용해 별도 후보 작업 공간을 만들었다. `road_surface_v1.yaml` SHA256 `7ecdb083899449d4c3717f25e5b347ae9506f68ec6bd0f9528d2fb4e5c0fd4a9`를 동결했고 24개 초기 마스크는 모두 255, 픽셀 검수 pending 24 / 승인 0이다. 이전 모델의 라벨·객체 초안은 가져오지 않았다. `workspace_kind=training`은 검수 앱의 입력 준비 모드이며 학습 수용을 뜻하지 않는다. 이 영상 후보 작업 공간은 MCAP 전용 고정 평가 등록 경로를 대체하지 않는다. 현재 영상 후보의 training-mode 승인 경로는 255가 남으면 거부하므로, 가림·미관측 255를 유지한 정답의 승인·출력은 아직 지원하지 않는다. 준비 묶음의 실행 안내는 편집·검수 대기 작업만을 열며 이 제약을 우회하거나 255를 배경으로 채워 승인하지 않는다. 최신 main의 해당 검수·registry·perception·Foundation·공용 웹 소스와도 차이가 없음을 준비 후 확인했다.

작업 공간 재개와 loopback 임시 서버에서 `/pixels`, `/api/workspace`, 24개 `/api/mask-images/<index>`의 HTTP 200 및 빈 마스크를 확인했다. 서버는 확인 후 종료했다. 브라우저 렌더·사람 검수·검수자 신원·독립 평가·물리 캘리브레이션 수용은 확인하지 않았다. contact sheet는 실제 실내 도로 촬영 화면이며 정답 mask가 아니다.

검수 코드·동결 원본·SQLite·클래스·실행 안내를 포함한 `evidence/road-surface-review-24.zip`의 SHA256은 `2f003b3d606c52895b5d8f760d711855c135cf6318db6e10bbb440b339285d54`이다. 증거는 같은 X 드라이브 세션의 `evidence/blank-road-review-preparation-20261012.json`, `candidate-known-manifest-overlap-20261012.json`, `blank-road-review-http-readback-20261012.json`에 보존했다. 모델 PC 작업 공간은 `/home/rosy/rosy-ml/scratch/road-surface-review-20261012-024175/review-state`다. 기존 운영 앱·자료·원본 영상·모델을 수정하지 않았고 HOLD를 유지한다.

## 기존 평가 원본과 학습 영상의 출처 중복 (2026-10-12)

기존 MCAP 평가 검수 작업 공간 두 개를 읽기 전용으로 확인했다. `human-eval-review-20261006`의 225개 마스크와 `review-v13-drivable/eval-20261008T163945Z`의 8개 마스크는 파일 hash가 모두 일치하지만 픽셀 승인은 0이고 모두 pending이다. 승인되지 않은 상태를 정답으로 승격하지 않는다. D-475는 가림 255를 사람이 확인한 평가 전용 MCAP 승인에서 보존하며 D-464 학습용 승인은 계속 255를 거절한다. 앞 절의 영상 후보 제한은 이 기존 계약의 의도된 경계이며 자동 배경 채우기로 우회할 코드 오류가 아니다.

225개 가운데 99개의 `source_session`은 `20261005T134540Z_rosy_26`, `capture_group`은 `heldout-20261005T134540Z_rosy_26`이다. 로컬 `pilot_saved_20261005T134540Z.manifest.json`의 전달 계보는 실제 장치 hostname `rosy-pinky-9dfk`와 보존된 원래 namespace `rosy_26`를 구별하고 같은 원본 세션을 선언한다. 이 receipt의 원본 bag 16개를 X 드라이브의 보존 원본에서 실제 hash했고, 모델 PC 평가 입력의 bag 16개와 metadata도 실제 hash했다. 양쪽 bag inventory의 16/16 SHA256 및 metadata SHA256이 모두 일치하며, 99개 평가 frame의 동결 MCAP inventory도 같은 값이다.

동시에 로컬 전달 영상·JSON·JSONL·scan 4개를 receipt의 hash·크기와 대조해 모두 일치를 확인했다. 해당 MP4 SHA256은 `a5dd55eb10d2514e405ecf9547b2e181c9da1cc713ee124943a7657ae2d499b9`이다. AI PC upstream `data-v13`의 이 영상 hash와 기존 20261010 dataset-v2의 image SHA256을 다시 연결하면 194개가 모두 `train`에 있다. 이 연결은 upstream의 영상 출처 선언과 검증한 전달 receipt의 원본 bag 계보를 사용하며 날짜 문자열·장치 별명만으로 추정한 결과가 아니다. 전달 receipt의 `source_capture_group`과 `operator_collection_group`은 여전히 UNKNOWN이며, 검수자 권한이나 물리 보정 유효성을 새로 인정하지 않는다.

따라서 해당 99프레임의 촬영 원본은 이 194개 학습 자료와 출처를 공유한다. 평가 PNG image SHA와 세 기존 dataset의 image SHA 직접 대조는 모두 0이었지만 출처 독립성은 성립하지 않는다. 이 99프레임을 20261010 학습 자료에 대한 독립 최종 평가 정답으로 사용하지 않는다. 나머지 126프레임이나 별도 8프레임의 독립성을 이 결과로 증명하지 않는다. 기존 검수 상태·예약·raw·dataset split·모델을 바꾸거나 삭제하지 않고 연구 기준선으로 보존한다.

증거는 같은 X 드라이브 세션의 `evidence/existing-eval-review-source-audit-20261012.json`, `existing-eval-review-training-image-overlap-20261012.json`, `20261005-derived-video-bag-closure-20261012.json`, `20261005-existing-eval-original-bag-join-20261012.json`, `20261005-source-video-train-membership-20261012.json`이다. 실제 학습 실행 전체의 재현, 검수 독립성, 전체 upstream 출처 closure, paired 도로면/구역 정답 및 실물·시뮬레이션 적합성은 여전히 HOLD다.

## 이전 사용자 검수 ZIP의 실제 마스크 대조 (2026-10-12)

AI PC의 `pinky-v13-pidnet-unet-20261008/review-before-user-confirmation.zip`과 `review-user-completed-snapshot.zip`을 추출·수정 없이 읽었다. 각 묶음의 242개 마스크는 선언된 SHA256, 크기, 허용 픽셀 값 대조를 모두 통과했다. 두 묶음 사이 이미지·원본 영상·프레임·세션 식별자는 동일하고 마스크 해시 변경은 0개다. 상태는 approved 101 / needs_fix 140 / excluded 1에서 approved 241 / excluded 1로 바뀌었지만, 두 묶음 모두 `human_mask_review_completed=false` 242개, `visual_bump_presence_reviewed=true` 242개다. 파일명과 approved 상태만으로 전체 픽셀 검수 완료를 인정하지 않는다.

클래스는 background, lane_left, lane_right, crosswalk, speed_bump이며 drivable/도로 전체 정답이 없다. 두 원본 영상의 선언된 SHA256별 항목은 215개와 27개이고 intended_split은 모두 train이다. 완료 묶음 이미지 SHA256을 현재 20261010 dataset-v2와 대조하면 205개가 일치하며 모두 train에 있다. 기존 차선·과속방지턱 개발 자료로 보존하고 독립 도로면 평가 정답으로 승격하지 않는다. 검수자 인증이나 나머지 37개의 학습 이력 독립성을 이 결과로 증명하지 않는다.

증거는 같은 X 드라이브 세션의 `evidence/older-user-review-zip-metadata-20261012.json` 및 `older-review-zip-mask-readback-20261012.json`이다. 기존 파일·라벨·검수 상태·split은 변경하지 않았으며 도로면 적합성은 HOLD다.
