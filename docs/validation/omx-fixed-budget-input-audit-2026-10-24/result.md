# OMX 고정 예산 수집·입력 검사와 중단된 학습

2026-10-24 KST 관측이다. 실행 소스는 commit `8d119665da8f`다. 수집과 입력 검사는 통과했지만 학습은 중단됐으며, 완료 모델·정책 품질·실물 수용 근거는 없다.

## 수집과 실제 입력 검사

- study `CT20261024B36_8d1196`: 예정한 12묶음·36개 고유 episode를 모두 실행했다. train 27개·validation 9개가 모두 teacher 작업 성공이며 실패·미실행·대체 회차가 없다.
- coordinator는 종료 0, 최종 상태는 `collected_pending_audit`·active batch 없음이다. 각 묶음의 원본 archive·파일 map·일반 파일 byte·원본 결과·소스/의존성 inventory·분할/기존 자료 제외·종료 정리를 독립 검토했다.
- 실제 모델 PC 입력 검사 `fixed-budget-teacher-audit-e9978d70181794c8`는 종료 0이다. 성공 후보 36개 모두 원래 진실·RGB·명령·미래 타깃 검사와 실제 LeRobot 0.4.4 export/readback을 통과했다. 전체 57,209프레임이다.
- 원래 고정 순서대로 train slot 001–020·validation slot 028–032를 선택했다. 25개·39,723프레임이며 사용하지 않은 성공 11개도 검사·보존했다. 실패 후보를 숨기거나 추가 회차로 채우지 않았다.
- 독립 검토에서 Important 지적이 없었다. 승인된 MODEL 읽기 전용 경로에서 전체 export 58,109파일·1,279,177,309바이트를 실제 inventory와 다시 대조했다. 누락·추가·symlink가 없었다.

검사 범위는 `whole_fixed_budget_input_audit_only`다. `quality_gate_passed=true`는 입력 적격성만 뜻하며, 검사 결과의 `data_admitted=false`·`training_submitted=false`·정책 평가 0·운영 권한 none을 유지한다. teacher 성공률을 학습 정책 성공률로 해석하지 않는다.

## 원래 학습 실행: interrupted/HOLD

원래 입력 검사에 대한 독립 검토 뒤 `fixed-budget-teacher-training-46d848a6cce69e6d`를 한 번 제출했다. 설정은 10,000step·seed 42750·`n_action_steps=1`·`command_entry_and_exit`·`joint_delta_tanh_from_chunk_source_v1`·state noise 0.01·부모 모델 없음으로 동결했다.

native 원격 실행 ID는 `sim-8d119665da-e09f15`다. MODEL 역할, 8 CPU·6GiB·120분 제한으로 실행했다. site나 실물 로봇에서 실행하지 않았다.

SSH 연결이 끊겨 로컬 runner는 255로 끝났고 결과 fetch도 실패했다. 06:04:37 KST 재연결 관측에서는 같은 scope가 active/running, 모델 상태는 `training`, 메모리 현재 약 2.88GB·최대 약 2.94GB였다. 설정의 `steps=10000`은 목표이며 완료 step 수가 아니다.

06:07:36 KST 관측에서는 같은 scope가 inactive/dead·빈 cgroup이고 lock·예약이 없었다. 원격 journal은 05:51:09 시작·06:05:01 정지·CPU 23분 6.049초·메모리 최대 2.7G·swap 0을 기록했다. 모델 경로에는 normalization·training-index·중간 상태·reader 입력 복사본만 있었다. 가중치·체크포인트·history·offline report·별도 reload·최종 model result가 없다. 독립 읽기 전용 검토에서도 이 경계를 확인했다.

원래 실행의 OUT만 회수했고 원격 결과는 삭제하지 않았다. native와 같은 링크 제외·data filter로 일반 파일 92개를 추출했다. colcon의 `latest` 링크 두 개는 제외했다. 중간 `TRAINING` 상태나 scope의 `Result=success`를 완료 증거로 사용하지 않는다. 정책 평가를 시작하지 않았다.

실행기의 SSH 종료 뒤 STOP 및 원격 HUP/EXIT 정리 경로는 확인했다. 다만 실제 정지 주체나 worker exit code는 확보하지 못했으므로 특정 HUP·OOM·정상 종료를 확정 원인으로 기록하지 않는다. 이 실행을 재개 가능한 체크포인트로 취급하거나 claim을 지워 다시 실행하지 않는다.

## 보존 근거

외부 scratch의 `learning-execution-20261023/` 아래 원본을 보존한다. Git에는 원본 영상·비공개 설정·토큰을 넣지 않는다.

| 산출물 | SHA256 |
|---|---|
| `fixed-budget-teacher-curation-8d1196/progress.json` | `sha256:2f43a1b3aee0b24b56e9ebb1effc2e1ae88cdb6ce9efc267c70dec45e093f0fb` |
| audit `execution/out/result.json` | `sha256:75df54e16334ecd88efb05578a637614f7e867423b67afee26f0def3ce2d547c` |
| audit `execution/out/export-inventory.json` | `sha256:d97fef6a40ad62fc58f50c4fe56ded68acb3d4863e7de719d6abc0907c9794e1` |
| audit `execution/out/split.json` | `sha256:9fc1cb34a565a0b0a43e0effe08f737f2133de30cacf0d2187a06037b5fc4d81` |
| training `transport-recovery.tar` (8,325,120바이트) | `sha256:8500d0ecea8b48761a4af25025e637e29848c6ee55809b6f2a84c16e9f20c4f7` |

## 남은 수용 조건

기존 두 HOLD 수집, prototype 및 한 번의 진단 실행의 3개 episode는 계속 제외한다. 원래 7개 동결 스크립트와 이번 claim을 보존한다. 향후 학습 시도는 중단된 실행과 구분하는 사전 검토 기록 및 연결 중단에도 동일 작업만 추적하는 실행 경로가 필요하다. 모델 완료·두 별도 프로세스 reload·독립 검토 뒤에만 원래 engineering 검사와 20회 독립 정책 평가(18회 성공 기준)로 진행한다.

HF 인증은 사용자 요청대로 연기했다. 양팔 SDK smoke는 실자료 정책 품질 근거가 아니며, 사람 라벨·실물 동작·운영 승격도 이번 검사에서 수용하지 않았다. 기존 [native 진단 기록](../omx-teacher-gripper-native-diagnostic-2026-10-24/result.md)의 미해결 물리 원인도 바꾸지 않는다.

CE: 미해결 — 중단 경계는 확인했지만 정확한 정지 원인과 지속 가능한 학습 실행 경로의 재발 방지 검증이 남았다.
