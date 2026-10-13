---
module: pilot
logical_modules: []
owner: 화면
last_verified: { commit: "10daaae5", date: 2026-10-02 }
gates:
  SOURCE:
    state: GO
    evidence: "T1 /pilot 라우트 계약 2 passed·T3 stick 매핑 8 passed·api_web 전체 72 passed·web_common known_failures 0 new (2026-09-29 Windows)"
    cmd: "python -m pytest src/hmi/pilot/test src/runtime/api_web/test/test_pilot_route.py -q -p no:cacheprovider"
  LOCAL:
    state: HOLD
    blocker: "OMX 페어링→조그와 Pinky 게이트 브라우저 시험은 각각 통과. 기록 시작 실패·재시도·결과·stale 영상·dispose Chromium 시험과 실제 Gazebo 15프레임→LeRobot 재독출은 통과. 전체 Pilot/Pinky 경로 재측정은 남음"
    cmd: "python -m pytest src/hmi/pilot/test/test_pilot_browser.py -q -p no:cacheprovider"
  ROS-SIM:
    state: HOLD
    blocker: "OMX 관절·그리퍼·취소의 Gazebo action/readback은 docs/validation/pilot-omx-gazebo-2026-10-01/에서 확인. Gazebo 작업대 영상·시연 기록 15프레임과 실제 LeRobot v3 재독출도 통과. 그리퍼 정밀 도달·전체 재시작 회복·Pinky 재측정은 남음"
  ARTIFACT:
    state: HOLD
    cmd: "gh workflow run payload-boot-smoke.yml -R livsbittt/rosy-os --ref af0b3211384c9a8f2e5abbc2863c2fbcb54b0ca3 -f build_run_id=37189180389; gh run watch <issued-run-id> -R livsbittt/rosy-os"
    evidence: "share/pilot: 서명 payload 2026.10.04-034 설치 관측. 무서명 동일 빌드(source dd159ab3361739e41c105dcef533bd0e1fd8f614)의 hosted ARM GET /pilot 200+CSP(run 37200780702, workflow source af0b3211384c9a8f2e5abbc2863c2fbcb54b0ca3). cmd는 이 역사적 벤치 재현이며 현재 통합 후보 수용을 증명하지 않는다"
    blocker: "D-444 R1의 서명 release를 탄 기기에서 GET /pilot 200+CSP는 미확인. hosted ARM 무서명 벤치는 이를 대체하지 않는다"
  DEVICE:
    state: GO
    cmd: "Pilot 브라우저에서 실기 Pinky 원격 조종·페달 해제·e-stop 확인"
    evidence: "사용자 직접 확인 (2026-10-05, '건했어. pilot 는 돌아'). 정량 측정값 회차는 별도 보강 예정 — docs/validation/pilot-device-user-confirmed-2026-10-05 (D-444 §2 R2)"
  FIELD:
    state: N/A
adrs: [D-323, D-365, D-366, D-390, D-411, D-432]
plans:
  - docs/plans/2026-10-01-omx-demonstration-lerobot-design.md
  - docs/plans/2026-09-29-rosy-pilot-teleop-app-design.md
  - docs/plans/2026-09-29-rosy-pilot-teleop-app.md
  - docs/plans/2026-10-01-pilot-omx-gazebo-practice.md
  - docs/plans/2026-10-02-d411-pilot-recording-controls-plan.md
---

## 지금 상태

- 2026-10-10 D-590: Android 로봇 목록에 `2대 함께 조종` 진입점을 추가했다. 두 인증 세션·두 카메라·공용 조이스틱의 SOURCE 빌드 및 JVM 시험 105건을 확인했다. Lenovo 태블릿에서 `rosy_40`·`rosy_41`의 실제 두 카메라와 조이스틱 화면을 최신 설치본으로 촬영했다(`X:/DevTemp/pilot-group-entry/pilot-group-live-final.png`). 비영 명령의 두 로봇 동시 실물 주행·단절 시 물리 정지는 FIELD HOLD다. 이 모드는 같은 명령 전송이며 leader/follower 추종(D-559)은 아니다.

- 2026-10-05 D-456: Native Pilot의 LAN 선택·수신 승인·암호화 승인 기록·신원 증명 재연결은 SOURCE/LOCAL 구현과 실제 Kotlin/JVM 81 PASS를 확인했다. 새 페어링의 서명 APK·실제 승인 화면·DHCP/장기 오프라인 재접속은 미확인이다. 기존 DEVICE GO는 D-444의 사용자 확인 범위이며 새 페어링 수용을 뜻하지 않는다.

- 골격 착지: `/pilot` 라우트·web_common ui-shell 표면·`stick.js` 순수 입력 매핑.
- 앱은 같은 출처의 `/api/v1`·`/ws/*` 만 말한다(D-323, CORE SRS §1.3).
- 1차 기기는 현장 태블릿(Lenovo 1200×2000) — 가로 모드 기준 레이아웃.

- 2026-09-29 가제보 실조종 교정: 부호 규약(REP-103)·2 축 스틱·제자리 회전·CORE 한도 비율 프리셋·송신 타이밍. 팔은 조작 프로필 `arm` 설계만(계약 대기).
- 2026-10-02 D-411 B: 화면은 기기가 알리는 `rosy.controls/1` 로 조립된다(주행 `base_velocity`, OMX SIM `joint_jog` 조이스틱). 브라우저 시험 통과, OMX Gazebo 에서 조이스틱은 아직 미실행(ROS-SIM HOLD).

## 다음 gate

2026-10-03 D-432: `apps/pilot` Android shell에 기존 화면 JS를 번들했다. 같은 LAN 장비
검색·선택·기존 코드 페어링·암호화 저장·인증된 로봇 ID 확인을 구현하고 Lenovo 태블릿에 설치했다.
구형 Pinky의 새 접속 API 404는 기존 페어링으로 처리한다. 4자리 통합은 추후 적용한다.
관련 증거는 `docs/validation/discovery-link-2026-10-03/`에 있으며 연결 확인으로 주행 DEVICE gate를 올리지 않는다.

1. LOCAL: 실행 계획 T11 Playwright 종단(가짜 CORE) 통과 뒤 GO.
2. ARTIFACT: 이미지 closure 에 pilot 패키지 포함 확인.
3. DEVICE: 실기 Pinky 주행 확인(증거는 `docs/validation/pilot-<date>/`).
