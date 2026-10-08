# 10/6 원본 두 세션의 현재 R0 주행 재생 (2026-10-08)

**판정: 안전한 STOP은 확인, 차선 추종 수용은 실패/HOLD.** 로컬 `main` `cabcfaf8f`의 `road_replay.py`를 10/6 두 원본 MCAP 3,129프레임에 실행했다. 입력 출처와 화소는 [MCAP 증명](../lane-1006-mcap-candidates-2026-10-08/result.md)에 기록했다. 촬영 당시 주행 intent는 `MANUAL/manual`이므로 이 결과는 오프라인 재생이며 실제 자율주행이 아니다.

| 원본 세션 | 지면 설정 | RoadState 단계 | 경계 단계 `BOTH/ONE/MEMORY/STOP` | 재획득 |
|---|---|---|---|---|
| `082612Z` 2,487장 | 공칭 | `STOP` 2,487 | `0/0/0/2487` | 0 |
| `082612Z` 2,487장 | 후보 pitch 11.8° | `STOP` 2,487 | `0/0/0/2487` | 0 |
| `091340Z` 642장 | 공칭 | `STOP` 642 | `0/0/0/642` | 0 |
| `091340Z` 642장 | 후보 pitch 11.8° | `STOP` 642 | `0/7/100/535` | 0 |

긴 영상 884번과 짧은 영상 630번의 벽 앞 원본 후보 화면에서도 네 재생 모두 RoadState·경계 단계가 `STOP`이었다. 앞선 [시험 drivable 헤드 출력](../drivable-smoke-1006-full-2026-10-08c/result.md)은 이 자리의 화면 하단을 넓게 칠했지만, 이번 R0 재생은 학습 마스크를 추종기에 공급하지 않았다. 따라서 모델의 안전성을 입증한 비교가 아니며, 마스크 면적으로 STOP을 해제하지 않는다.

짧은 영상의 11.8° 후보에서는 경계 `ONE` 7장과 `MEMORY` 100장이 생겼으나 후보 107건이 모두 억제됐다. 642장 중 keeper의 차선 쌍 판단 비율은 0.0327이고, 지도 폭과 비교할 수 있는 쌍 폭은 2건뿐이며 RoadState 재획득은 0건이다. 공칭 지면은 두 영상 모두 쌍 폭 0건이다. 이것은 안전한 거절과 함께 **추종 근거가 부족함**을 보여 준다. `on_line_le_keep` 등 일부 게이트의 `pass=true`는 RoadState 출력이 없어서 성립한 공허한 통과다. 직선 오차·coast 생존·벽 오수용은 평가값이 `null`이며 `validated=false`다.

## 재현과 해시

각 `<session>`은 X: `DevTemp/projects/rosy-platform/2026-10-08--045427--lane-evidence-learning--e0687b/evidence/recordings/<session>`이다. 출력은 X: `DevTemp/rosy-lane-1006-current-replay-20261008/<시각>-<설정>/`에 두었다.

```text
python learning/training/perception/road_replay.py <session> --out <출력> --compare-boundary
python learning/training/perception/road_replay.py <session> --out <출력> --compare-boundary --pitch-deg 11.8
```

| 결과 | `metrics.json` SHA-256 | `frames.jsonl` SHA-256 |
|---|---|---|
| [긴 영상 공칭](evidence/082612-nominal-metrics.json) | SHA-256 `6b0a806099c196a4ed3c49d0330e3e83200b702b3717c8435c395f8327e27057` | `ca4725718dd5957205ce5ef0605fc8e4288e92e665d5770dbc2f1f39d8b16c45` |
| [긴 영상 11.8°](evidence/082612-pitch118-metrics.json) | SHA-256 `36640d697bd0a57a36b96745713f26dd5631ea0d7b459e7e76e93c7a9a02c87c` | `0240610b2b0cfda126058bf141f06186ca1ee9a9616751cde0f39508e4d18ce9` |
| [짧은 영상 공칭](evidence/091340-nominal-metrics.json) | SHA-256 `da77aa944a1696916a5a445756d46ac4f64ded4bfcbdbb6f0a27500c49a9cd61` | `4bcbc4300c2b0e02cb9b71d257043a25f571571bcbd28b5897ec344f37fe3e2c` |
| [짧은 영상 11.8°](evidence/091340-pitch118-metrics.json) | SHA-256 `fd08e972339d937165c31c59760622659660b5869e1abfd79e417e034c18718f` | `cd73cf28646433a392ee7efff754417779998f39d7df78374450b106e55b6079` |

두 지면 설정 모두 `ground_provenance=nominal_or_override`이다. 11.8°는 후보일 뿐 촬영 당시 보정의 측정값이 아니다. 사람 승인 동일 물리 경계·벽/분기 마스크와 실제 카메라 보정이 없으므로 IoU·연속 소실 회복률·운영 주행 성공률을 계산하지 않았다. 다음 재생은 승인된 경계 ID와 보정 revision을 같은 프레임에 묶어야 한다. CORE 단일 최종 `/cmd_vel` 경계와 불확실 시 STOP은 유지한다.
