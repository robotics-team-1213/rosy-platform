# 정지 Pinky 적재면 ↔ 컨베이어 접촉 왕복 — 2026-10-25

Isaac Sim 5.1.0.0에서 OMX-F CAD 집게가 동적 물체를 Pinky 적재면 proxy에서 컨베이어 proxy로 옮기고, 다시 원래 위치에 놓는 **단일 접촉 왕복 스모크**를 통과했다. 부착·물체 pose 재설정·외력 보조를 사용하지 않았다. 실측 카메라 맵, Pinky 전체 로봇, 주행, 학습 정책 또는 실물 수용을 뜻하지 않는다.

## 실행과 판정

- 실행 source: `7d0cfcd6e94fd0181e324319e12c274f3e2f3890`.
- run: `36041b241ee25366986bb3a6262ba0be`, 최종 `SUCCEEDED`, `task_success=true`, `PHYSICS_GRASP`, 실패 목록 없음.
- 기존 공식 `remote_isaac.py` check/start/status/fetch와 계정·source·SDK binding, 두 학습 잠금, 165/180초 supervisor를 사용했다. 설치·서비스 활성화·실물 명령은 없었다.
- `stationary-proxy-v3`: 18 mm 정육면체·0.05 kg, 120 Hz, Pinky 지지면 `(0.14,-0.07,0.09)` m, 컨베이어 `(0.14,0.07,0.09)` m. 두 지지면은 정지한다. 합성 좌표이며 실제 카메라와 정합하지 않았다.
- 관측 physics step 3,624개, 경과 `30.200001575052738`초. 단계별 관측 시계와 정확한 정수 step 수를 검사했다. float32 callback dt의 누적 반 ULP 범위만 허용하며 한 step 차이는 거절한다.
- CAD FK/수직 파지 IK의 결정론적 제어기다. 기존 HF 학습 정책은 실행·승격하지 않았다.

독립 판정기는 양쪽 손가락 접촉, 지지면에서 20 mm 이상 자유 lift, 실제 이송 중 접촉 유지, 목표 위치, 집게가 40 mm 이상 물러난 뒤 1초 안정 상태를 요구한다. XY 15 mm, 높이 5 mm, 기울기 10도, 선속도 0.01 m/s 이하 기준을 실행 전에 고정했다.

| 관측 | 실제 결과 |
|---|---|
| 첫 lift / 반대 방향 lift의 마지막 물체 중심 높이 | 0.18066 / 0.17993 m, 최초 0.09900 m |
| lift/이송 hold의 양쪽 손가락 접촉 | 독립 검토에서 최소 3.28 N, 두 지지면 접촉 0 |
| 컨베이어 안착 XY 오차 | 최대 2.263 mm, 지지 접촉·집게 해제·안정 확인 |
| Pinky 원위치 복귀 XY 오차 | 최대 1.859 mm, 지지 접촉·집게 해제·안정 확인 |
| 최종 정리 | `OWNED_PROCESSES_EXITED_GPU_RELEASED` |
| 최종 산출물 | JSON 보고서 1개·PNG 5개, 모두 크기·SHA-256 재검증 |

초기, 첫 lift, 컨베이어 안착, 복귀 lift, 최종 안착 이미지를 각각 열어 실제 물체 위치를 확인했다. 서로 다른 이미지 해시와 증가하는 rendering frame/time도 확인했다. 동영상은 만들지 않았다. 독립 검토는 receipt/request/input/source·verifier·asset 지문, 결과·manifest 지문, 여섯 파일, 판정기 재평가와 이미지까지 대조했다.

## 보존한 실패와 변경

| run | 결과와 다음 변경 |
|---|---|
| `79f62a44052b5ceeae5d9058b3b5bb93` | 4 step 뒤 measured roll을 정확히 0으로 가정한 FK에서 중단. 실제 roll을 포함하도록 수정 |
| `c84ba1be157259c4b8ce4e8db7e1805d` | 루프 3,624회, 접촉 파지 실패. 이 회차의 루프 횟수를 독립 확인된 physics step 수로 해석하지 않음. 렌더/물리 stepping 분리, 관측 시계 추가, 카메라 clip 및 구동 목표 보강 |
| `1b0fdcdd20af5797a8860333c45964f3` | 2,301 step 뒤 1 µs 고정 시계 오차 제한에 걸림. 보존한 시각 차이가 float32 dt 누적과 일치해 반 ULP 누적 검사로 교체 |
| `50868081e8e45752b3bf23b72f3e6d1f` | 3,624개 실제 step, 파지 실패. 닫힘 뒤 첫 손가락 +0.481 rad, 둘째 +0.1086 rad로 비대칭; 물체가 source에 남음 |

모든 SDK 회차는 소유 프로세스 종료·GPU 해제를 확인했고 실패를 성공으로 덮어쓰지 않았다. 잘못된 source SHA로 전송 전에 거절된 요청 1개와 GPU 점유로 ready=false였던 check도 SDK 실행으로 세지 않았다.

마지막 변경은 angular drive type을 `force`로 명시한 것이다. 성공 회차에서 변경 전 조합은 joints1–5·첫 손가락 `acceleration`, 둘째 손가락 `force`였고 변경 후 모두 `force`임을 기록했다. 직전 회차와 gain·effort cap·목표·파지 판정은 같으며, fixture revision과 drive type·진단 기록만 바뀌었다. 반복 성능·payload 일반화의 인과 효과나 성공률을 주장하지 않는다.

## 지문·보관·남은 범위

- input: `63504c7ffcdc1a90bb140fc03d1f3c7e9e4aa1e2ce6e4668d6921ea71c353d3a`
- result: `354d8bf48f179a4ebbf706d8649f1567a00584e287f85373552af62a7cc05bcf`
- artifacts: `424e8dd6d972af6009065628eefa8fbcea34d998e2d2d8a204427276d39647ea`
- contact report: `b91a359bc461a110d86d30e44f1bbd10a69bfb072cb388d10672c7336bdc0568`

비공개 작업 공간 기록의 `2026-10-25/omx-camera-map-reference/`에 실제 top/front 원본·수신 상태, 배치도 HTML, 회차별 request/receipt/FINAL snapshot·원문·요약·해시 확인을 보존했다. 공개 저장소에는 원시 실제 카메라 영상·실장치 identity를 넣지 않는다.

실제 top 영상에서 컨베이어와 팔 구조는 보였지만 Pinky 적재면은 식별하지 못했다. front 시야는 구조물에 가려져 있었다. 카메라 내부 보정·카메라↔팔 변환·Pinky/컨베이어의 실측 좌표·높이와 물체 물성을 확보하기 전에는 합성 배치를 현장 맵으로 사용하지 않는다. 벨트 이동, full Pinky 자산·이동, learned AI 평가, 실물 제어는 미검증이다.

실행 source의 원격 Isaac/CLI 회귀는 377 PASS·1 SKIP(xacro 환경), NEW 0이다. 이후 문서 커밋과 main 병합 검증은 landing receipt를 따른다. CE: [구동 방식 교훈](../../solutions/runtime-errors/isaac-imported-gripper-drive-modes-must-match-gain-units-2026-10-25.md) 새 기록.
