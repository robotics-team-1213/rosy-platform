# 인수인계 — 무엇을 만들고, 어디까지 왔고, 다음은 무엇인가

- **대상:** 이 저장소를 이어 받는 팀원과 에이전트 세션. 코드를 열기 전에 읽는다.
- **기준일:** 2026-10-16. 적은 시점의 사실이다. 계약은 SRS·API reference·ADR이 이긴다.
- **함께 읽기:** git으로 일하는 법은 [git-workflow.md](git-workflow.md), 첫날 설정은 [팀 가이드](team-guide.md).

## 1. 우리가 만들려는 것

> 어떤 로봇이든 웹·표준 API로 제어하고, 현장 Fleet이 여러 대에 미션을 나눠 주는 로봇 플랫폼. 첫 하드웨어는 Pinky Pro (Raspberry Pi 5). — [README](../../README.md)

관측한 세계 상태(World), 현장 작업 조정(Fleet), 장치별 안전한 실행(CORE·OMX), 오프라인 학습·평가(모델 PC → AI PC)를 잇는다. 목표 범위 전체는 [Vision and Definition](../architecture/00_ROSY_OS_Vision_and_Definition.md)에 있고, 그 문서가 스스로 말하듯 "구현됐다는 주장이 아니다".

최상위 목표와 완료 조건은 [PRODUCT.md 「Product Purpose」](../../PRODUCT.md#product-purpose)가 정본이다(2026-10-24: 범용 실행 플랫폼, 첫 적용 사례 Harbor). 아래는 그 목표의 능력 증명 마일스톤이다.

| 마일스톤 | 무엇이 되면 끝인가 | 근거 |
|---|---|---|
| **Pinky 두 대의 차로 주행** | Fleet 아래 두 대가 횡단보도·신호를 지키며 코스를 연속으로 돈다 | [Gazebo 차로 한 바퀴](../plans/2026-10-12-gazebo-lane-lap.md), [차로 규칙 시뮬 인계](../plans/2026-10-15-lane-regulation-sim-handoff.md) |
| **OMX 팔 모방 학습** | 흰 원형 용기에서 딸기를 꺼내 임시 위치에 놓고 다시 돌려놓는다 | [OMX 미완 인계](../plans/2026-10-15-omx-integration-unfinished-handoff.md) |

고정 셀 작업(Rosy Cell 팔레타이징)은 별도 목표에서 내려 Harbor 흐름에 흡수했다.

변하지 않는 원칙은 [README 「핵심 계약」](../../README.md#핵심-계약)이다. 특히 **외부는 CORE API로만 말하고, 최종 `/cmd_vel`은 CORE 하나만 낸다.**

## 2. 지금 어디까지 왔나 — 증거 기준

게이트는 SOURCE → LOCAL → ROS-SIM → ARTIFACT → DEVICE → FIELD 순이다. 모듈별 표는 [STATUS.md](../../STATUS.md)지만, **그 원본인 모듈 `progress.md`가 2–4주 묵었다**(fleet·docs는 2026-09-30, core·deploy는 10-02 기준). 표를 "적어도 이만큼"으로 읽고, 최근 사실은 아래와 `docs/validation/`의 날짜 폴더로 확인한다.

| 수준 | 된 것 | 안 된 것 |
|---|---|---|
| 실물 로봇 | 학습 조향 첫 실주행 10초([d592](../validation/d592-drivable-steer-field-test-2026-10-10.md)). 두 대 연속 차로 시험에서 한 대는 TRACKING, 한 대는 HOLD([lane-continuous-test](../validation/lane-continuous-test-2026-10-10/)). Pilot 원격 조종 DEVICE(사용자 확인 등급, [pilot-device](../validation/pilot-device-user-confirmed-2026-10-05/)) | 두 대 동시 한 바퀴는 다섯 번 모두 FIELD HOLD(`two-robot-one-lap-2026-10-10`…`10e`). 코스 완주, 횡단보도 뒤 재출발 |
| 실물 OMX 팔 | 읽기 전용 관절 피드백 120초, 토크 0([omx-physical-feedback](../validation/omx-physical-feedback-2026-10-15/)). 카메라 두 대 30분 수신 | 명령으로 팔을 움직인 적 없음 |
| 시뮬레이션 | Gazebo 한 대 15바퀴 연속, 신호 켜고 14바퀴(대체 인지). 두 대 trip 단계([d763](../validation/d763-trip-steps-sim-2026-10-15/)). OMX Gazebo 집기·놓기. Isaac 한 대 RL 9.3 m([isaac-map-rl](../validation/isaac-map-rl-2026-10-11/)) | 학습 모델로는 한 바퀴 안에 차로를 잃는다. 두 대 경합 시나리오가 교착 |
| 릴리스·배포 | ARM64 payload 빌드(CI) | 서명된 이미지·digest, Pi 실기 부팅 readback — ARTIFACT GO인 모듈이 없다 |

## 3. 진행 중인 흐름과 그 인계 문서

2026-10-15에 컴퓨터를 옮기기 전, 흐름마다 인계 문서를 남겼다. 이어 받을 때는 해당 문서부터 연다.

| 흐름 | 인계 문서 | 핵심 다음 일 |
|---|---|---|
| main 관문·착지·push 운영 | [main-gateway-handoff](../plans/2026-10-15-main-gateway-handoff.md) | 밀린 커밋 push, 11-15 마감, 두 번째 관리자 |
| Fleet 주행 한계·경로 미리보기 (D-760, D-767) | [d760-d767-handoff](../plans/2026-10-15-d760-d767-handoff.md) | D-767 P0 정확도 증거(Gazebo 정답 추출 → 두 대 30분), D-760 단계 6 현장 적용 |
| 차로 규칙 시뮬 | [lane-regulation-sim-handoff](../plans/2026-10-15-lane-regulation-sim-handoff.md) | 두 대 경합 시나리오 재구성, `no_anchor` 실패 원인 |
| Fleet 작업 종류·크기 한도 (D-763, D-766) | [fleet-work-size-limits](../plans/2026-10-15-handoff-fleet-work-size-limits.md) | 크기 한도 안에서 남은 작업 슬라이스 |
| OMX 팔 | [omx-integration-unfinished](../plans/2026-10-15-omx-integration-unfinished-handoff.md) | 실물 구동 전 H2–H6, 물체 맥락 P1 |
| 화면 결함 | [ui-screenshot-defects](../plans/2026-10-15-ui-screenshot-defects.md) | 남은 화면 결함 |

최근 결정 가운데 아직 Proposed인 것: D-754(굽은 길 다음 선 거리), D-758(로봇이 가진 현장 기준점), D-759(굽은 길 진입 방향, 플래그 뒤 구현), D-761(워크트리 관문), D-768(차로 순간 상실 때 경로 유지). D-769(drivable RL과 Gazebo 검증)는 방향만 Accepted다.

## 4. 다음에 할 일 — 우선순위

1. **local `main` → `origin` push.** 2026-10-16 기준 152커밋이 origin에 없다. 새 팀원은 그 일을 볼 수 없고, CI 증거도 없다. 순서는 [git-workflow §5](git-workflow.md#5-push와-origin-동기화).
2. ~~CI `modules` 러너 실패 0 — 마감 2026-11-15.~~ 2026-10-27 판정에 넣음(10-25부터 main 연속 녹색, D-762 단계 1).
3. **두 번째 관리자 지정.** merge queue·필수 검사(D-762 단계 3)가 이것 하나에 막혀 있다.
4. **두 대 차로 주행:** 경합 시나리오 재구성 → D-768 구현 → 학습 모델로 Gazebo 완주(D-769) → 실물.
5. **OMX:** H2–H6을 닫고 첫 명령 구동.
6. **기록 갱신:** 묵은 모듈 `progress.md`를 다시 검증하고 `generate`. World·Drive 등 STATUS에 행이 없는 모듈을 등록한다.

## 5. 브랜치·워크트리 현황

- 2026-10-16 `git branch --no-merged main` 20개. 일부러 보류한 것과 풀리는 조건은 [held-branches.md](held-branches.md). 그 뒤 더한 보류: `fix/gazebo-map-lap`(전방 정지 sweep 배선, 안전 경로 미검토 — 착지하지 않는다).
- 실험실 clone에만 있는 ref(보관 태그 `archive/*`, `refs/wip/*`, `refs/adr/*`, origin에 없는 브랜치)는 번들로 옮긴다. 명령은 [main-gateway-handoff §4](../plans/2026-10-15-main-gateway-handoff.md). **공개 origin에 push하지 않는다.**

## 6. 누가 무엇을

담당이 정해져 있지 않다. [팀 가이드](team-guide.md) §5.1 영역 표의 담당 칸이 비어 있고 `.github/CODEOWNERS`는 `* @livsbittt` 하나다. 담당이 정해지면 그 표와 `CODEOWNERS`를 같은 PR에서 고친다.

## 7. 새 컴퓨터·새 사람 체크리스트

- [ ] Python 3.12 + `pyyaml` (하네스·훅·`land.py`가 모두 Python이다. 없으면 push가 막힌다)
- [ ] `gh` 로그인(조직 `robotics-team-1213`), git 2.48 이상
- [ ] `git config user.name` / `user.email`이 내 GitHub 계정
- [ ] `bash tools/hooks/install.sh`로 pre-push 훅
- [ ] 실험실 접근이 필요하면 Tailscale 로그인과 `private/lab-hosts.json`(모양은 `tools/remote/hosts.example.json`). 주소는 Notion 비공개 페이지에 있다
- [ ] 스크래치 폴더를 저장소 밖에 정한다(실험실 노트북은 `X:\DevTemp`)
- [ ] `python tools/harness/rosy_harness.py lint`가 `0 error(s)`

이 문서를 고칠 때는 기준일을 바꾸고, 지나간 사실은 지우지 말고 바로잡는다.
