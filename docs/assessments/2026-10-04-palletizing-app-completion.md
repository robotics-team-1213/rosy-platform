# 팔레타이징 앱 현황과 완료 우선순위

작성: 2026-10-04. 기준: `origin/main`의 `f32643ffde593f84959b28e990b01120cefaeda1`. 조사 브랜치: `docs/palletizing-completion-review-20261004`.

## 판단

Rosy Cell은 계산 코어와 실행 기반이 있는 **미완성 앱**이다. 레시피를 편집하고 셀을 준비한 뒤 제안·승인·실행·중단·복구까지 운영자가 화면에서 수행하는 제품 흐름은 아직 완성되지 않았다. 기존 코어를 다시 만드는 것보다 전용 앱과 기존 Fleet/OMX 경계를 연결하는 일이 우선이다.

첫 완료 목표는 **시뮬레이션에서 박스 전용 작업 한 건을 화면으로 끝내는 것**으로 제안한다. 원래 목표인 두 팔레트·두 층·슬립시트 전체 수용은 별도 후속 목표로 유지한다. 이 제안은 기존 C6 수용 범위를 조용히 축소하거나 실물 작동을 허용하는 결정이 아니다.

## 실제로 있는 것과 없는 것

| 영역 | 확인한 구현 | 남은 일 / 근거 |
|---|---|---|
| 레시피·셀·배치 | `operations/processes/palletizing`의 로더, 패턴, 적재 순서, `compile_job`, `compile_plan_bundle` | 코어를 UI에서 호출하고 검증 오류를 입력 항목과 연결해야 한다. `src/site/cell/rosy_cell`은 호환층이다. |
| 컴파일 경계 | `operations/apps/fleet/src/rosy_gateway/cell_compiler.py`의 `PalletizingCellCompiler` | 프로세스 산출물 SHA-256과 허용 오차를 고정한다. Job과 PlanBundle 생성은 승인이나 실행이 아니다. |
| Fleet 제출·복구 | `mission_routes.py`의 Cell 제안·별도 운영자 승인, `cell_job_routes.py`의 reconcile/resume/cancel, 자원 점유 조회 | 앱의 서비스 자격과 사람 운영자 자격을 구분해 연결하고, HOLD/UNKNOWN/점유 상태를 표시해야 한다. |
| 독립 완료 근거 | Cell goal evidence registry/service/routes와 정식 수신 경계 | 실제 독립 배치 판정기를 연결해야 한다. Action `SUCCEEDED`만으로 박스 위치를 확인했다고 표시할 수 없다. |
| 로컬 OMX 실행 | 해석 IK, Cell owner, phase/workflow, Fleet fence 역조회 및 UDS 시험 | 실제 ROS/UDS 구성, stop/fence/seat 경합·재시작·지연 결과 종단 검증이 남아 있다. |
| 웹 앱 | 공유 웹 자산, Fleet 콘솔, Pilot 시뮬 조작 화면 | 조사 기준 Cell 전용 HTML/JS·앱 서버가 없고 `surfaces.yaml`에도 Cell 표면 등록이 없다. Pilot의 팔 조작 화면은 레시피 앱을 대신하지 않는다. |
| 설치 | gateway와 process/execution wheel, 기존 설치 조합 | 깨끗한 설치에서 앱 서버·자산·설정·entrypoint가 함께 시작되는 증거가 필요하다. fake lifecycle smoke는 실제 배포가 아니다. |
| Gazebo | C3 일부 transfer 및 Linux 집중 UDS/HTTP checkpoint 기록 | 전체 레시피 종단 수용은 없다. 넓은 Linux 실행의 실패 2건을 통과로 간주하지 않는다. |

코드 부재 판단은 위 기준 SHA의 `src/site/cell`, `src/hmi`, Fleet 웹 자산, 표면 레지스트리와 앱 wheel을 조사한 범위에 한정한다. 다른 세션의 미병합 구현이나 실제 호스트 서비스 존재 여부를 증명하는 말은 아니다.

## 실행 호스트 결정 (사용자 지시 2026-10-04)

Gazebo는 작업 PC 로컬/WSL에서 실행하지 않고 **모델 PC를 우선 실행 호스트**로 한다. 관제 PC는 운영 Fleet·Vision·콘솔을 유지한다. 이는 [D-434의 역할 분담](../adr/D-434-model-pc-and-site-pc-roles.md)을 따른다. D-434의 Isaac 설치 기록은 Gazebo 준비 완료의 증거가 아니다.

현재 OMX Action UDS는 [D-336](../adr/D-336-fleet-omx-local-ipc-boundary.md)의 같은 호스트 경계이고 `apps/agent/src/rosy_agent/fleet_fence.py`의 Fleet-current 역조회도 literal-loopback을 요구한다. 따라서 첫 Gazebo 수용에는 **모델 PC 안에 격리한 검증용 Fleet·Cell 앱·OMX owner·Gazebo**를 함께 배치한다. 작업 PC는 원격 접속·브라우저·결과 열람만 맡는다. 관제 PC의 운영 DB·인증정보·등록 로봇을 시뮬레이션 원장에 재사용하지 않는다. 별도 테스트 Fleet는 같은 운영 작업을 중복 제어하는 두 번째 writer가 아니다.

운영 관제 Fleet와 모델 PC의 owner를 직접 연결하려면 현재 UDS/loopback 계약을 대조한 원격 transport 설계와 인증·fence·단절 수용이 선행해야 한다. UDS를 네트워크 공유에 올리거나 loopback 제한을 제거해서 연결하지 않는다.

첫 준비 작업은 모델 PC 신원과 SSH 접근, Linux/ROS Jazzy/Gazebo 또는 고정된 OMX 시뮬 이미지, RAM·GPU 여유, 설치 산출물 SHA, 테스트 자격/DB·소켓·run ID 격리와 원격 증거 회수 확인이다. 이번 조사에서는 모델 PC에 Gazebo가 실행 가능한지 아직 검증하지 않았다. 관제 PC로 시뮬레이터를 옮기는 대안은 사이트 부하 영향과 역할 변경을 먼저 검토한다.

## 오래된 기록에서 바로잡아야 할 점

1. `2026-10-01-rosy-cell-completion.md`의 첫 상태는 10월 1일 스냅샷이다. 현재는 IK·Fleet 경로·owner 구현이 있으므로 그 문장의 “없다”를 오늘의 backlog로 복사하면 안 된다.
2. `src/site/cell/progress.md`의 grasp depth 미지원 blocker는 현재 코드와 다르다. 현재 `recipe.py`, compiler, compatibility 시험에는 `grasp_depth`와 손끝 overhang 처리가 있다. 다음 실행 회차에서 기록을 갱신해야 한다.
3. `test/test_cell_omx_sim_layout_contract.py::test_every_box_transfer_plans_and_slip_sheets_are_refused_by_width`는 박스 계획 성공과 **슬립시트 거절**을 시험한다. 모든 transfer가 실행 가능하다는 완료 근거로 쓸 수 없다.
4. `docs/validation/cell-fleet-uds-2026-10-03/README.md`의 집중 Linux 시험과 넓은 실행 결과는 서로 다르다. 응답 시간 및 ROS 상태 최신성 실패를 timeout 확대나 freshness 제거로 숨기면 안 된다.

## 범위 선택

| 선택 | 장점 | 비용·제약 | 의견 |
|---|---|---|---|
| 박스 전용 앱 흐름부터 완료 | 현재 그리퍼와 코어를 재사용하고, 앱·권한·실행·복구를 한 흐름으로 확인한다. | 원래 슬립시트 C6는 아직 미완료로 남는다. | 권고 |
| 슬립시트 취급까지 한 번에 완료 | 원래 C6 범위를 한 번에 충족한다. | 2 mm 시트는 현재 그리퍼 기하에서 거절된다. 흡착·전용 도구·공급 방식 등 별도 설계와 검증이 필요하다. | 후속 결정 |
| 화면만 먼저 완성 | 레시피 편집과 미리보기는 빠르게 평가할 수 있다. | 화면 성공이 적재 성공처럼 보일 위험이 있다. | 준비 단계로만 허용 |

## 실행 순서와 출구 조건

| 순서 | 책임 | 구체적인 작업 | 완료를 판단할 증거 |
|---|---|---|---|
| 0 기준선 정리 | PROCESS / SITE / OMX | 현재 SHA에 맞춘 미완료 목록, 설치 의존성, stale blocker 정리. D-427 이동 wave와 대상 경로 확인. | 실제 installed-wheel 회귀 결과와 현재 계획의 차이 기록. |
| 1 앱 최소 서버·레시피 화면 | Cell 앱 / PROCESS | D-427 목표 경로에서 앱 서버와 정적 자산 구성. 기존 cell/recipe 형식으로 입력·불러오기·수정·검증·2D 층 미리보기. | 브라우저에서 유효·잘못된 입력, 저장/재시작, 설정 변경 후 이전 Job 무효화 확인. 새 서버 경로는 구현 전에 API Reference로 확정. |
| 2 셀 준비·티칭 | Cell 앱 / OMX | 시뮬 연결·home·프레임·스테이션 준비. 기존 D-404 계약을 대조해 누락 API만 식별. | pairing과 seat 단독 소유, 브라우저 생존에 따른 갱신, 연결 상실 시 조작 종료, 검증된 Cell 해시 일치. |
| 3 제안·승인·진행 | Cell 앱 / FLEET | 기존 제안 경로 연결, 사람 운영자의 별도 승인, 단계·HOLD 이유·자원 점유 표시. | 서비스 계정의 자기 승인 거절, 오래된 레시피/셀 거절, 승인 전 dispatch 없음. |
| 4 복구·독립 완료 판정 | FLEET / OMX / 관측기 | 응답 유실·취소·정지·seat 경합·재시작·늦은 성공·오래된 증거를 정식 경로에서 검증. 독립 배치 판정기 연결. | 같은 attempt 대조, 재제출/자동 재개 없음, 실제 관측 없이는 완료·점유 해제 안 됨. |
| 5 박스 전용 종단 수용 | 통합 검증 담당 | 두 팔레트·두 층 박스 레시피를 앱 → Fleet → UDS → OMX owner → Gazebo로 완료. | 레시피/셀/산출물 해시, 원장·attempt·phase, 독립 최종 위치와 오차, 중단·복구, 설치/재시작 결과의 동일 실행 묶음. |
| 6 슬립시트·설치 산출물 | PROCESS / 도구 담당 / DEPLOY | 시트 취급 도구 또는 공급 방식 결정, 원래 C6 재수용, 실제 설치 프로파일·산출물 검증. | 거절을 없앤 것만으로 성공 처리하지 않고 집기·놓기·접촉·최종 위치를 관측. |

앱 화면과 독립 판정기 작업은 공유 계약을 확정한 뒤 병행할 수 있다. 같은 실행 원장·grant·owner 상태를 별도 구현으로 복제하면 안 된다. 실제 작업 시간은 첫 종단 실행과 장애 원인 확인 전까지 확정하지 않는다.

## 권한과 완료 표시

- 앱은 입력과 컴파일·제안 UX를 소유하고, Fleet은 승인·순서·점유·원장을 소유한다. 장치 owner는 IK·실행·로컬 정지를 소유한다.
- 앱·Pilot·모델에서 ROS/관절/모터 명령을 우회 하달하지 않는다. 승인과 로컬 stop/fence 조건은 유지한다.
- 화면의 `계획 유효`, `승인됨`, `실행됨`, `목표 확인됨`은 서로 다른 상태다. 네트워크 응답이나 Action 성공만으로 목표 확인을 표시하지 않는다.
- 앱 완성, ROS-SIM, 설치 산출물, DEVICE, FIELD는 각각 별도 증거다. 현장 PC나 실물 OMX를 이 조사 중에 배포·구동하지 않았다.

## 이번 조사에서 실행한 검증

기본 Python 환경에서는 필요한 `rosy` wheel이 없어 Cell suite가 수집되지 않았다(9 collection errors, 2 skipped). 제품 코드 결함으로 단정하지 않고, X:의 별도 venv에 기준 SHA에서 복사·빌드한 skill/execution/palletizing wheel을 설치해 다시 검증한다. 소스 경로만 PYTHONPATH에 덧붙여 설치 문제를 숨기지 않는다.

X:의 별도 venv에 기준 SHA로 빌드한 skill/execution/palletizing wheel 세 개를 설치한 뒤 `test/test_platform_palletizing_compat.py`, `test/test_cell_omx_sim_layout_contract.py`, `src/site/cell/test`를 함께 실행해 **174 passed, skip 없음**을 확인했다. 이는 설치한 계산 코어·호환층·레이아웃 회귀이며 Fleet 실행, 브라우저, ROS-SIM 수용은 아니다. 빌드 복사·wheel·venv·로그·pytest 출력은 X:에만 두었다. 기존 문서의 시험 수치는 과거 증거이며 이번 재실행 결과와 구분한다.

완료 목표와 단계별 출구는 [D-446 초안](../adr/D-446-palletizing-app-completion-goals.md)에 정리했다.

문서·구조 관련 검사에서 127 passed / 1 skipped였고 ADR 연속성 관련 2건은 기존 브랜치가 선점한 D-438 예약 누락으로 실패했다. 예약을 보완한 뒤 해당 2건을 재실행해 2 passed를 확인했다. 최종 harness lint는 0 errors / 26 기존 warnings이고 상대 링크 검사와 diff whitespace 검사도 통과했다. 이 결과는 위 installed-wheel 회귀와 별개의 문서 검사다.

## 남은 결정

1. 첫 제품 수용을 박스 전용 시뮬레이션 흐름으로 분리할지.
2. 슬립시트는 전용 도구·공급장치·수동 투입 중 어떤 취급 방식을 요구할지.
3. 기존 Cell 앱 이름·계약을 유지하면서 D-427 목표 경로에 앱을 둘 구체적인 설치 조합. 조사에서는 새 포트·프로토콜 필드를 정하지 않는다.

위 항목은 ADR 초안의 제안이다. 이 보고서는 개발 우선순위를 검토하는 문서이며, 구현·운영 배포·실물 구동을 진행한 결과가 아니다.

## Isaac 주행 추가 검토

모델 PC에서 Isaac 주행을 더하는 목표는 [추가 검토 문서](../plans/2026-10-04-isaac-navigation-integration-review.md)에 분리했다. 먼저 단일 로봇의 CORE 주행·정지를 검증하고 Nav2·두 로봇 Fleet·이동 후 적재 순으로 확대한다. 현재는 검토 문서와 host helper 시험만 완료됐으며 앱·Gazebo·Isaac 전체 개발을 완료한 상태가 아니다.
