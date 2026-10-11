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
