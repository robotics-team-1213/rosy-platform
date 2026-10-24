# OMX 충돌 표현 대조: 로봇 없는 SIM pilot

동일 손가락 STL을 사용하는 두 fixture에서 충돌 표현에 따른 명목 기하–접촉점 차이를
재현했다. [이전 실제 관절 진단](../omx-policy-articulation-native-2026-10-24/result.md)의
정책 실패 인과나 제품 충돌 형상 수용은 아직 입증하지 못했고 정책은 HOLD다.

## 고정 범위와 실제 결과

소스 commit `29d3f2e1d8e33889c99dd1487f9aff2823dcbf66`에서 official remote_sim의
AI-PC 격리 SDK를 사용했다. `run_pilot.py --binding-sha256 <아래 binding 해시>`로
기본 mesh와 동일 STL의 `convex_hull`을 각각 새 프로세스에서1회 실행했다.
순서는 baseline→hull로 고정했으며 무작위·독립 반복 추정을 하지 않는다.
물리 fixture2개, 로봇 모델·명령·정책 추론·optimizer·formal trial은 모두0이다.
초기 자세·mesh scale0.001·질량·관성·중력·table·engine은 두 조건이 같다.
설치 SDF1.11 파서가 두 optimization 값을 경고 없이 보존하는 것을 실행 전에 확인했다.

| 조건 | 첫 저장 양수 depth 시각 | 양쪽 pose 표본 | 명목 STL 최저 Z−선택 접촉점 Z |
|---|---|---|---|
| 기본 mesh | 65ms | 64/66ms | 9.850975/9.849052mm |
| convex_hull | 77ms | 76/78ms | 1.447952/1.430196mm |

사전 기준은 baseline 양쪽 차이가8…12mm이고,
min(baseline)−max(hull)≥5mm인 것이다. 실제 보수적 endpoint 차이는8.401100mm다.
각 contact의 양수 depth 중 최대값에 대응하는 같은 index의 point를 선택했고,
동률은 첫 index를 사용했다. 두 조건 모두 collision1=table이므로 WorldOnA 해석이 같다.
원본 source stamp와 이름이 붙은 world→model→link 변환을 보존했으며,
관측한 quaternion과 모든 STL 정점으로 각각의 endpoint 값을 계산했다.

hull의 선택 depth는9.313×10⁻¹⁰m로 거의0이다. 미리 고정한 `>0` 기준에 해당하지만
유의한 관통을 뜻하지 않는다. 첫 저장 보고를 실제 접촉 시작 시각으로 부르지 않는다.
endpoint 비교는 표본 사이 연속 자세의 경계나 engine margin 속성 측정값이 아니다.

## 실행·회수·검토 근거

각 월드는 paused 상태에서 토픽·구독 연결을 확인한 뒤 단 한 번의
WorldControl pause=true,multi_step=1000 요청을 받았다.1ms step으로 engine 자체가
1초 후 재정지하므로 관측이 끊겨도 무한 진행하지 않는다. 각 fixture wall 제한120초,
공통 외부 제한5분이었다. 실제 fixture wall8.90/8.84초, pose66/78개,
contact1/2개를 보존했다. 실행 scope에서 CPUQuotaPerSecUSec4s/MemoryMax4294967296을 읽었다.
적재된 physics/SIM/PosePublisher 파일의 실제 map 경로를 해석하고 고정 해시와 대조했다.
각 child process group 종료와 fetch 후 scope inactive/not-found·빈 cgroup·lock/reservation 해제를 확인했다.
Coordinator는 terminal EXIT0으로 끝났으며 수집 성공만 의미한다.

최초 Windows 시작 시도는 CreateProcess의 WinError206으로 원격 자식·예약·actor 생성 전에
실패했다. 원본 claim을 보존하고 전달을 압축했다. 길이·roundtrip 자체 점검2개와
fixture 자체 점검9개가 통과했다. 실제 두 fixture는 재시도·교체 없이 한 번씩 실행했다.
독립 검토2건이 최종 입력, 원본 pose/contact와 STL 계산, 한계 해석을 확인했다.
upstream 소스·설치 파일 대응 근거와 runtime branch 직접 관측은 구분한다.
이번 실험은 binary rebuild 동등성이나 runtime mesh branch를 직접 증명하지 않는다.

외부 루트: `C:/DevTemp/learning-execution-20261023/collision-envelope-pilot-20261024/`.
아래 fixture 파일은 `remote/out/mesh-pilot/` 아래에 있다.

| 산출물 | SHA-256 |
|---|---|
| binding.json | `e0e150f753f5daee3dff6c1271ec9499b4e793db834f034fd622fd6d334ce0e7` |
| fixture.py | `42a5ba75564693342f30069eda903b1cb20796488fba753a24866a9de9d7123f` |
| summary.json | `c2b73c07cd3904d6c2ffc0f4a2e22cd19ca826b6da743309f42ca7ad4472016e` |
| baseline/result.json | `c1362b8c160ca0917aeee8c8bdc0f12f44725696290d1b48748ba7a27349ed86` |
| hull/result.json | `65a172742dde7050427cf12c668a618172bce6e5cb03da99ed3b0c79d57900bb` |
| baseline/world.sdf | `ec5a41f57573f88aa542d0c58dff74552f4073733360ae09a41430bc2e352d09` |
| hull/world.sdf | `aa6f3eb02c5f25ff76559af4b29e4d01b578add8044ecd0f02c937389977f970` |
| terminal-closure.json (외부 루트) | `70e5c6555751ae5d2d2db6f529fe59ae81b0cbaded036b788fa3865c57943f32` |

원본 poses.json/contacts.json·library maps·active-scope·자체 점검과 설치/파서/source
preflight도 같은 루트에 보존했다. 추가 actor 예산은 소진됐다.
다음은 동일 로봇 task의 통제 대조이며, 이 fixture 결과만으로 제품 형상을 바꾸거나
정책을 승격하지 않는다. 실물·양팔 실제 작업·HF 인증/전송 수용은 미검증이다.

CE: 미해결 — fixture의 차이는 재현했지만 정책 실패의 해결책은 아직 검증하지 못했다.
