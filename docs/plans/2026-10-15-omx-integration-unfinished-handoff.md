# OMX·AI·Fleet 미완료 작업과 재개 인계

2026-10-15 마감 기록. 기준 commit: `9a59940e1`.
사용자 요청에 따라 미완료 범위와 재개 조건을 보존한다. 이 문서의 커밋·병합은
실물 제어 완료, runtime 활성화, 원격 push 또는 FIELD 수용을 뜻하지 않는다.

## 유지할 목표

모델 PC의 학습·독립 평가·고정 산출물, AI PC의 승인 버전 추론, Fleet의 검증·admission,
CORE의 base 제어와 OMX 로컬 owner의 팔 제어를 실제 요청·결과 readback으로 연결한다.
교육 과제는 **흰 원형 용기에서 딸기를 꺼내 임시 위치에 놓고 원래 용기로 돌려놓기**다.
선정된 영상상의 위치는 작업 후보이며, 보정된 실물 목표 좌표가 아니다.

## 확보한 증거와 한계

| 항목 | 확보한 범위 | 대신하지 못하는 증거 |
|---|---|---|
| 모델 PC·AI PC | 앞선 고정 입력 실제 추론, Fleet 애플리케이션 UID에서 보호된 AI broker 요청/응답 확인 | 실물 과제 정확도·지속 관측·장치 실행 |
| 모델 산출물 | accepted 저장소 6개 산출물의 manifest/ONNX/READY 해시 대조 | 독립 평가 품질·로봇 설치·실제 사용 버전 |
| OMX 영상 | 현장 PC 내부에서 두 카메라 30분 수신, 각각 9.985 FPS | PC 간 영상 전달·화질·노출 시각·보정·재부팅 복구 |
| 실물 준비 | 읽기 전용 readiness, private native build/link, 실측 문서 검사 CLI | driver 활성화·실측 진위·독립 정지·실물 제어 |
| 계획 | 물체/문맥, IL/RL, 운영 UI, 실물 제어 design/execute 문서 | 해당 모듈과 사용자 여정의 구현·배포·수용 |

현재 확인: Fleet AI 상태는 present/available이나 등록된 Pinky 두 대는 연결 불가다.
모델 전달 watcher의 마지막 관측 시도는 `No route to host`, exit 78이었다.
현장 기본 ROS는 Lyrical이며 고정 대상은 Jazzy다. private build는 이 차이의 지원 승인이 아니다.
관측한 OMX graph에는 팔 Action이 없고 `/joint_states`는 `joint_state_publisher`가 발행했다.
실제 하드웨어 feedback으로 세지 않는다. 이 값들은 기록 시점의 관측이며 재개 시 다시 읽는다.

## 미완료 목록

| ID | 남은 작업 | 선행 조건·담당 역할 | 완료로 인정할 증거 |
|---|---|---|---|
| I1 | Fleet↔실제 CORE 연결, 모델 전달·설치·추론 readback | 현장 운영자: 로봇 전원/네트워크 복구; 통합 담당: 기존 등록 경로 확인 | 실제 CORE 상태·버전, 전달 receipt, 설치 해시와 실행 버전 일치 |
| I2 | 모델 PC 독립 평가와 AI PC 운영 버전의 승격·재적재 연결 | 평가 담당: 고정 데이터/독립 정답; 운영 담당: 승인 artifact | 평가 receipt와 대상 버전 binding, 재적재·실패/rollback readback |
| V1 | OMX 지속 관측→AI 후보→Fleet 검증·원장 연결 | 소프트웨어 담당: 작업대 source/frame/context·인증·freshness 계약 확정 | 새 프레임과 context revision에 묶인 관측, stale/timeout 거부, 실제 원장 readback |
| V2 | 카메라 실물 품질·보정·복구 | 현장 설치자: 렌즈/조명/초점, 장치 식별, CameraInfo·hand-eye/TCP | 별도 기준점 오차, USB 분리/재연결·cold boot 복구, 촬영 시각/동기화 증거 |
| H2 | 지원 native runtime과 설치 경로 확정 | 플랫폼 담당: Jazzy/Lyrical 지원 판단, 고정 source·의존성·설치 권한 | 선택 runtime의 설치 receipt·lifecycle 검증. build/link만으로 통과 금지 |
| H3 | follower 식별과 실측 profile·독립 stop 수용 | 현장 설치자/검수자: leader/follower 물리 대조, 한계·jaw·하중·workspace·정지 측정 | 검수된 rig/profile/calibration revision과 통신/전원 상실·처짐·재시작 증거 |
| H4 | 실물 local owner/native composition 구현 | 소프트웨어 담당: H2/H3의 실제 binding·정지 인터페이스 확정 | 단일 bus/graph writer, 실제 feedback, UUID·terminal·cancel 미확인 분리, stale/중복/재시작 HOLD 시험 |
| H5 | 실물 API·Fleet/Pilot driver·UI 연결 | 계약/클라이언트 담당: 별도 hardware 계약, 공유 schema/API reference 정렬 | 인증·admission→owner→결과 원장, 모든 asset/Android 등록, 장애/복구 브라우저 검증 |
| H6 | 딸기 꺼내기→임시 놓기→복귀 | 현장 감독자: H2–H5, 보정된 도달/충돌·용기/대상 질량 검증 | 전체 cycle의 영상·관절·명령·독립 결과, 실패·개입 기록과 사용자 수용 |
| L1 | 실물 시범 수집·검수·cycle 단위 split | 교육/데이터 담당: H3와 독점 소유권·동기화 | 파일럿 episode 정합, 가림/낙하/실패 판정, 누출 없는 train/holdout |
| L2 | IL 학습·독립 평가·고정 artifact 재적재 | 학습/평가 담당: L1, 동일 과제 규칙 baseline | 새 조건의 성공률·주기·개입률·지연 비교와 artifact 재적재 |
| L3 | RL 환경·reward·reset·평가 모듈 | 학습 담당: 계약/holder 확정, 기존 Gazebo 기반 비구동 실험 | 결정적 seed/reset, 실제 적용 action·종료·개입 기록, reward와 독립된 성공 평가 |
| U1 | Learning·Fleet Cell·Pilot·episode review 전체 UX | UI 담당: 실제 소유 실행기와 H5/L1–L3 계약 | 요청/running/terminal/cancel readback, 권한/단절/중복/복구, 키보드·200%·모바일·Android 여정 |
| R1 | 제한 운용·배포/rollback·FIELD 인계 | 승인/운영 담당: 선행 수용과 별도 push/배포 지시 | 대상 rig와 artifact 일치, 비활성 전달→승인 운용, 이전 승인 버전 복구·운영자 인계 |

## 재개 순서

1. 이 문서와 아래 실행 계획을 읽고 현재 main·서비스·장치 상태를 재확인한다.
   지난 시험 프로세스는 모두 종료됐다. 새 실행을 과거 실행의 연속으로 기록하지 않는다.
2. I1의 연결 복구와 H2/H3의 현장 확인을 먼저 확보한다. 실물 포트 역할·한계·정지 수단을
   이름 순서, 명목 URDF, SIM 값이나 AI 추정으로 채우지 않는다.
3. 소프트웨어 작업은 독립적으로 가능한 계약/오프라인 검증과 물리 수용 의존 작업을 구분한다.
   H4/H5, V1, L3/U1은 아직 구현 과제가 남아 있다. 전부 현장 문제로 처리하거나 완료로 닫지 않는다.
4. 제품 변경은 새 격리 worktree에서 수행한다. 커밋된 HEAD의 원격 검사와 `known_failures`
   비교, 필요한 독립 안전 리뷰를 마친 뒤 사용자 지시 범위의 로컬 병합을 진행한다.
5. 현장 수용 이후 H6, L1/L2, 제한 운용을 단계별로 확인한다. 물리 시험은 감독 조건을 먼저 확보한다.

## 유지할 경계

- AI·Fleet는 팔 버스의 최종 writer가 아니다. OMX 로컬 owner와 CORE base 권한을 유지한다.
- SIM endpoint/identity/clock/gripper 관측을 hardware로 이름만 바꿔 쓰지 않는다.
- 벤더 launch의 초기 위치 이동·controller 활성화는 비구동 준비가 아니다. 자동 launch 금지.
- E-stop 해제·torque-off·cancel ACK를 독립 물리 정지 증거로 대체하지 않는다.
- D-273의 작업대/천장 카메라 구분, 로컬 원본과 제한 미리보기 경계를 지킨다.
  Fleet 원본/DDS 중계나 가짜 map 보정으로 V1을 채우지 않는다.
- 문서 검사·단위시험·모델 간 동의·SIM 성공을 실물 성공으로 승격하지 않는다.

## 이어 볼 문서

- [실물 제어 설계](2026-10-15-omx-hardware-control-design.md) · [G1–G6 실행 계획](2026-10-15-omx-hardware-control.md)
- [실물 준비 증거](../validation/omx-hardware-control-preparation-2026-10-15/result.md)
- [30분 영상 수신 증거와 소비 공백](../validation/omx-camera-endurance-2026-10-15/result.md)
- [딸기 임시 위치 선정](../validation/omx-strawberry-placement-2026-10-15/result.md)
- [물체·문맥 실행 계획](2026-10-15-omx-object-context.md)
- [IL/RL·운영 설계](2026-10-15-omx-learning-operations-design.md) · [T1–T10 실행 계획](2026-10-15-omx-learning-operations.md)

원문 로그는 비공개 실행 세션에 보존한다: `omx-readiness-post-endurance.txt`,
`fleet-post-endurance.txt`, `model-delivery-blocker-audit-2.txt`, `field-blocker-audit-3.txt`.
실제 장치 주소·계정·자격 증명·원본 영상은 공개 문서에 옮기지 않는다.
