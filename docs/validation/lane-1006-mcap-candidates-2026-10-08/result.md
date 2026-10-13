# 10/6 MCAP 원본 프레임 후보 검토 묶음 (2026-10-08)

**판정: 출처 증명 통과, 사람 승인 정답 0건.** [앞선 MP4 파생 후보 묶음](../lane-1006-human-candidate-queue-2026-10-08/result.md)의 동일한 178개 프레임을 원본 MCAP 카메라 메시지로 다시 찾았다. 일부 구간은 시험 모델의 이상 출력을 보고 골랐으므로, 원본 화소를 쓰더라도 D-475의 독립 고정 평가 세트가 아니다.

## 출처와 재현

- X: `DevTemp/rosy-lane-1006-mcap-review-20261008/`의 `mcap-candidate-gallery.html`, `mcap-candidate-review-queue.csv`, `082612/frames/`, `091340/frames/`가 검토 자료다. 영상·사진 화소는 저장소에 넣지 않았다. [생성 코드](evidence/prove_candidates.py)와 [독립 검증 코드](evidence/validate_pack.py)를 기록했다.
- 10/6 `20261006T082612Z_rosy_26`의 2,487개 카메라 메시지 중 103개, `20261006T091340Z_rosy_26`의 642개 중 75개다. 기존 MP4 sidecar의 index·header stamp·bag log time과 전체 3,129개 모두 1:1 일치했다. 원본 수집 기록 `source-readback-1006.json` SHA-256: `ab5378c963d8a04277b155086c4655456ebb6e0e9b34154caf07b843f397c57d`. 이 기록이 열거한 원본 파일 20개의 SHA-256을 재계산해 불일치 0개를 확인했다.
- 기존 `extract.py --min-interval 0 --max-hamming -1`로 MCAP 압축 카메라 프레임을 바이트 그대로 추출했다. `mcap_proof.prove_frames`는 metadata의 bag 순서와 bag SHA-256을 검증하고, 각 후보의 topic·`log_ns`·channel ID·message ordinal·header stamp·해독 화소를 원본 메시지와 대조했다. [긴 영상 증명](evidence/proof-082612.json) 103건 SHA-256: `0d717c4c945751956cfa6adf7b03bceb2200f31dc00f659221365f23c61f0125`; [짧은 영상 증명](evidence/proof-091340.json) 75건 SHA-256: `0065de49ed338ef9a8da1e9a0a5f335c349d8bfebe3560a8ffbdcdc8aeeb366c`.
- [영수증](evidence/receipt.json)은 새 검토 CSV SHA-256 `3f636af4a5a000136f8b538bdd076aa423394621f5457e2e0e7a3662988e1fd0`, 갤러리 SHA-256 `4220bff259b6c690264a7b025afa12f77a3dce7b345682091970fd9f2c079da0`을 기록한다. 독립 검사에서 178행, 증명 178건, 이미지별 해시 불일치 0건, 갤러리 누락 0건, 사람 검수란 입력 0건이었다.

## 관찰과 한계

같은 시간표식의 MP4 파생 PNG와 MCAP 원본 JPEG은 **178/178장 모두 해독 화소가 달랐다**. 장당 채널 절대차 평균의 중앙값은 1.94, 최대는 2.60(0–255 범위)이었다. MP4 파생 화면을 MCAP 원본 화소 정답이라고 부를 수 없다는 것을 실측으로 확인했다. 이후 경계·주행영역 사람 검토에는 이 MCAP 원본 화면을 쓴다.

CSV의 같은 물리 경계 쌍, 좌우 ID, 소실 원인, 재출현, 보이는 주행영역, 검수자와 시각은 전부 공란이다. 원본 출처 증명은 라벨 정확도나 차선 추종 성공을 증명하지 않는다. 벽 앞 장면을 포함한 모든 후보의 실제 의미는 사람 판독 전이며, 이 자료를 학습 정답·고정 평가 정답·STOP 해제 근거로 사용하지 않는다. D-475의 사람 승인과 별도 평가 workspace가 필요하다.
