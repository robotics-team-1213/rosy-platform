# 추가 도로 영상과 업데이트 기록 검증 — 2026-10-04

실제 과거 녹화 영상 두 개를 기존 모델 두 개로 재생했다. 중앙 원의 흰 경계는 검출되지만 바닥/벽 오분류가 남아 있어 회전교차로 주행 승인 근거가 되지 않는다. 펌웨어 업데이트와 모델 교체 이력은 장치에 저장된다. native 이력을 웹 API/화면에서 조회하는 연결은 아직 부족하다.

## 영상 검증

| 입력 | 총 프레임 | FPS | 표본 |
|---|---:|---:|---:|
| teleop_rosy-pinky-9dfk_20261001T131825Z.mp4 | 9649 | 7.953 | 12 |
| teleop_rosy-pinky-8kcn_20261001T130842Z.mp4 | 14240 | 7.967 | 12 |

각 영상의 처음부터 끝까지 균등 간격으로 12프레임을 디코딩했다. 모델 PC의 기존 ONNX bundle을 `LaneSegModel.open(threads=2, allow_spinning=False)`로 열어 manifest/hash 및 warmup shape 검증 후 24표본 × 2모델, 48개 모델 판정 출력을 기록했다. 마스크 표시를 위한 backend 재실행 48회와 모델 open warmup은 별도다. 표본 인덱스/시각, 원본 디코딩 이미지 hash, 영상 hash, 모델 manifest/ONNX/동일 학습 폴더 best.pt hash와 출력은 [video-results.json](video-results.json)에 보존한다. 이번 시험은 기존 export 추론이며 새 `.pt` 변환 또는 PT↔ONNX 출력 동등성 시험은 아니다.

- wall-v2-expanded-20261004-seed42704: `lane-seg-20261004-72799466`.
- lighting-dice-base8-20261004-seed42704: `lane-seg-20261004-f21a7a97`.
- 두 모델 모두 24/24 표본에서 `visible=true`. 이는 차선 존재 판정이며 정답률이나 주행 가능 판정이 아니다.
- 9dfk의 0, 7893, 8770, 9648번 프레임에서 밝은 중앙 원의 흰 경계가 차선으로 분류된다. 클래스는 floor/lane_line/wall/drivable/stop_line/crosswalk이며, 원의 의미·진입·출구·회전 방향을 인식한 것은 아니다.
- 8kcn의 2588번 프레임에서 wall-v2의 wall_fraction은 0.728, base8은 0.005. 다른 로봇이 시야를 가리는 5177–10355번에서도 wall-v2는 0.754–0.832, base8은 0.000–0.035다. 육안 비교에서 wall-v2는 바닥을 벽으로 넓게 오분류한다. fraction 자체는 정확도 지표가 아니며 출력 ROI의 모델 근거다.
- base8은 위 장면에서 개선되지만 경계 단편과 배경 오검출은 남는다. 정지 장면 반복이 있어 24개 독립 장면 시험으로 셀 수 없다. 횡단보도/초저조도/과노출을 균형 있게 검증한 표본도 아니다.

별도 검토자가 원본과 두 모델 마스크 contact sheet를 확인했다. 원본/영상에는 작업실, 로봇 화면 및 사람 신체 일부가 있어 공개 저장소에는 숫자/hash/판정만 기록한다. 원본 영상은 모델 PC의 비공개 learning 녹화 저장소에, contact sheet와 재생 스크립트 `additional_road_video_review.py`는 로컬 `X:/DevTemp/rosy-lane-device-20261004/`에 보관한다. 영상 파일명과 hash로 원본을 대응한다. 학습 데이터와의 중복은 미확인이고 라벨 기반 정확도, 전체 영상 디코딩 성공률, 실제 Pi 성능 및 실주행은 미검증이다. 이번에 기기 모델을 교체하거나 펌웨어를 배포하지 않았다.

## 업데이트 기록

현재 소스 `6a549b980`와 장치의 설치 릴리스 `.033`을 구분했다. 읽기 전용 장치 조회 결과는 [update-records.json](update-records.json)에 기록한다. 저장 status의 마지막 갱신은 `2026-10-04T03:02:38Z`, phase는 idle이며 이 오래된 snapshot을 실시간 업데이트 중이라는 근거로 사용하지 않는다.

| 종류 | 저장 기록 | 확인 결과와 한계 |
|---|---|---|
| native 펌웨어 | `/var/lib/rosy/updates/state.json`, `status.json`, `history.jsonl` | 현재 파일 27건. applying 4, committed 3, rollback_started 1, rolled_back 1, error 1. 여러 boot_id의 기록이 재부팅 후 남아 있다. |
| 모델 교체 | `/var/lib/rosy/models/history.jsonl` | push 1건, revision `lane-seg-20261003-6e2e5640`; shadow pointer 동일. lane_seg의 flat shadow-only 계약상 active 없음은 정상이다. |
| .pt intake | 학습/배포 PC의 `intake_report.json` | 성공/실패 보고서 저장. 동일 revision 재실행은 덮어쓸 수 있고 장치에 자동 전달되는 전체 누적 이력이 아니다. |

`deploy/robot/pinky_pro/native/rosy_auto_update.py`는 applying/committed/rollback 및 중단 복구를 기록하고 JSON/JSONL을 fsync한다. 1MiB 회전 후 현재 파일과 `.1`만 보존하므로 무제한 보관이 아니다. 내부 작업 step은 state journal에 갱신되며 모든 step별 시작/완료 이벤트가 history에 쌓이는 것은 아니다. committed는 60초 health 확인 완료이고 모델 정확도나 실주행 승인이 아니다. systemd exit 성공만으로 업데이트 성공을 판단하면 안 된다.

업데이트 중 LCD용 `/run/rosy-boot/update-display.txt` marker를 만드는 경로가 있으며 종료 후 삭제한다. 실제 LCD 표시와 현재 marker 부재의 원인은 이번에 물리 관찰하지 않았다.

`learning/training/perception/model/deliver.py`는 push/rollback/promote 등 pointer 변경을 별도 JSONL에 기록한다. 전송 시작 및 모든 실패를 누적하는 계약은 없다. pointer 변경 후 audit append에는 별도 fsync가 없어 전원 차단 직후 마지막 기록의 내구성이 펌웨어 기록보다 약하다. 변경 후 기록 실패는 exit 3으로 명시한다.

## API/화면의 공백과 후속 작업

`middleware/core/api_web/core_api_web/api/v1/host.py`의 GET `/api/v1/host/release`는 Host Agent `release.status`를 요청한다. general agent는 legacy release state를 반환하지만 설치용 native `rosy-host-agent.py`는 lane_perception.status/set만 허용한다. native updater phase/history를 직접 반환하는 연결이 아니다. 현재 릴리스 카드는 current/previous/staged/last_failure를 표시하며 native 단계/시각/boot_id 이력 timeline은 없다. 실 API 요청은 이번 감사에서 미검증이다. 모델 선택/상태 readback도 모델 변경 이력 API와 다르다.

후속 구현은 native status/history의 읽기 전용 API 및 UI, 기록 source·freshness·boot_id 표시, 모델 attempt start/end/failure ledger 및 fsync, 이력 장기 보관 정책으로 나눈다. 인식 개선은 바닥/벽 오분류 라벨 보완과 중앙 원 진입·출구의 별도 정답 영상 평가가 먼저다. 기존 기록이나 차선 visible 결과만으로 회전교차로 자동 주행을 승인하지 않는다.

## 검증 범위

영상 hash/인덱스/시각/48개 판정 출력 정합성 확인 및 독립 육안 검토 완료. updater source 계약 시험은 273 passed/1 skipped, 모델 deliver/intake 계약 시험은 99 passed/24 skipped(총 372 passed/25 skipped). Windows의 Linux/shell 의존 등 skip은 실기기 검증으로 대체하지 않았다. 문서 계약 98 passed/1 skipped, harness lint 0 errors/16 기존 검증 경고. 경고는 모듈의 last_verified 노후화/미커밋 기록이며 장치 gate 통과로 해석하지 않는다. 기존 반복 정지/재부팅의 원인은 이 시험으로 확정하지 않았고 gate 변화는 없다.
