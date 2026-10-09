# 차선 arc 종료 지시 보존: Fleet 경쟁 조건과 폐루프 SIM

**판정: Fleet 지시 순서 수정 후보는 SOURCE/SIM 검증. 차선 유지·실물 주행 수용은 HOLD.**

## 문제와 수정

2026-10-09 [서쪽 굽이 재생](../lane-west-bend-candidate-2026-10-09/result.md)의 U2는 `ring_s` arc가 끝나기 전에 Fleet 지도 자세가 `ring_e`에 들어가 `SE`의 대기 중 `straight` 지시를 `NE` 지시로 교체했다. CORE는 arc 종료 시 `SE`를 기대해 `arc_mismatch`로 정지했다. 지도 투영과 CORE 오도메트리의 경계 통과 시점이 다를 수 있다.

`operations/fleet/fleet/server/trip_runner.py`는 CORE arc가 `running`이고 그 종료 장소에 대한 Fleet 지시가 실제로 `armed`인 동안 다음 장소 지시를 보내지 않는다. CORE가 종료 장소 지시를 소비하면 다음 장소로 진행한다. Fleet의 `hold`는 이 보호보다 우선해 STOP을 보낼 수 있다. CORE만 최종 `cmd_vel`을 낸다. 지도·기본 운용 설정·모델은 바꾸지 않았다.

회귀 테스트는 지도 투영만 한 구간 앞서는 상황에서 `SE` 지시 유지, CORE 소비 후 `NE` 지시 전송, `hold` STOP 우선을 확인한다. 이는 지시 순서 테스트이며 차체의 실제 차선 점유 보증은 아니다.

## 폐루프 재생

격리된 모델 PC 작업공간에서 2026-10-10에 기존 [서쪽 굽이 SIM 하네스](../lane-west-bend-candidate-2026-10-09/result.md)를 재사용했다. 같은 world SHA-256 `14c8de02f683435a103728a30a24a83237ff9bc03ba1dc6f87a08feb99f31ebb`, U-Net 리비전 `sim-unet-5159bea1`, 시작 자세, `WEST_BEND=1`, `ROUTE_CONTEXT_ENABLED=true`, `REC=1`을 썼다. 실험용 원격 Fleet 사본에 지시 보존 조건을 적용한 SHA-256은 `f3905652d39b1c89662bea9c7fb39cbebc4eb8542c8cd826c131b37acae68671`이다. 이 사본은 로컬 후보와 별개로 진화한 원격 소스를 바탕으로 하며, 로컬 후보의 `hold` 예외 조건은 원격 재생에 포함하지 않았다. `hold` 예외는 로컬 회귀 테스트로 확인했다. 재생은 현장 배포가 아니다.

| 실행 | 종료 | 서쪽 굽이 최소 표본 여유 | 링 남·동쪽 최소 표본 여유 | 링 북쪽 최소 표본 여유/침범 표본 |
| --- | --- | ---: | ---: | ---: |
| R1 | `arrived`, 55.9s | +6.0mm | +8.4/+8.3mm | **-2.6mm, 18/44** |
| R2 | `arrived`, 65.5s | +6.6mm | +4.8/+4.8mm | **-6.6mm, 27/45** |

여유는 SIM URDF 차체 꼭짓점·변 중점과 지도 페인트 중심선 사이의 **이산 표본 대리 지표**다. 링 검사도 차체 다각형과 페인트 중심 원의 거리이며, 페인트 폭·지도 오차·연속 sweep은 포함하지 않는다. 두 실행 모두 `SW→SE→NE→NW` 지시 후 도착했으나 링 북쪽에서 차체 표본이 바깥 페인트 중심선을 넘었다. 최대 표본 간 차체 꼭짓점 이동은 R1 14.7mm, R2 13.5mm라 연속 안전성은 증명되지 않는다. `arc_mismatch`가 재현되지 않은 두 실행만으로 코드 수정의 인과 효과를 단정할 수 없고, 정밀한 경계 유지 성능도 수용할 수 없다.

원본 `log.jsonl`, `summary.json`, `sends.jsonl`은 격리 모델 PC의 `~/rosy_d567_ws/loop_west_unet_arc_guard_r1|r2/` 및 로컬 `X:/DevTemp/arc-end-guard-20261010/r1|r2/`에 보관했다. 대용량 원본은 git에 넣지 않았다.

| 파일 | R1 SHA-256 | R2 SHA-256 |
| --- | --- | --- |
| `log.jsonl` SHA-256 | `5b560c449fab70477b3e91e6cf91ed1a0bc5839dd4961fcfbeab259c68736b20` | `e99c555e747d87b7ff99a5e3371ad759e59d8096f1e43b99cda1e0ab5d3f3ac8` |
| `summary.json` SHA-256 | `d41c885325194e955ec2de55f22505e85637a1a55386f68ab20c703b6eacfc9a` | `2ae515a47229131ddcac8407f2a9027047c0fabc1d1f3f103b602da680f57c29` |
| `sends.jsonl` SHA-256 | `c181670e822f8f46d22e17d3b958cc09215192b65cc3ba04938d6dfa8c2a6c81` | `ac2c41cf8f4db4e0e3635363bc266a8dd5913ac6b8a3f7e5a3cd3615579f2d06` |

## 후속 수용 조건

같은 입력의 반복 주행에서 차체 전체가 지도 오차와 페인트 폭을 포함한 보수적 차로 안에 머무는지 확인해야 한다. 링 북쪽 이탈 원인을 arc 시작 자세·추종 오차·종료 STOP 위치로 분리하고 수정 후 다시 폐루프 재생한다. 10/7 원본 영상의 물리 경계 ID·소실·재출현은 D-475에 따른 사람 검수가 아직 없어 학습 정답으로 쓰지 않는다. ARM64 이미지·로봇 장치·현장 안전 담당자 수용은 별도이며 현재 HOLD다.
