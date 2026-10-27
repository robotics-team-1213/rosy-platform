# OMX 클라이언트 배포 준비 파이프라인

2026-10-18 사용자 요청: 실물·배포를 위한 파이프라인과 로컬 커밋·머지.
사용자는 대상 workcell/instance와 승인된 정책 revision이 아직 없다고 답했다.
따라서 대상·승인을 만들거나 장치를 활성화하지 않고, 빌드·점검과 차단 결과를 구현했다.
이 기록은 착지 전 검증이며 머지·GitHub CI·장치 배포 성공의 증거는 아니다.

## 변경

- `Build OMX LeRobot client` 수동 workflow: 기존 OMX integration과 내부 의존 wheel
  3개, source SHA, SHA256SUMS를 artifact로 생성한다. 모델·토큰·장치 설정은 넣지 않는다.
- `rosy-omx-preflight`: 실제 LeRobot 0.4.4 환경, RecordConfig, ACT 단일 행동 설정,
  로컬 checkpoint 파일 hash, CORE의 정책 pin·관절·RGB 설정을 검사한다.
- CORE에는 GET policy만 보낸다. 관측 소비·행동·정지·lease 발급·승인을 하지 않는다.
  기존 보고서는 교체하지 않는다. 예외 원문·bearer token은 보고서에 넣지 않는다.
- `--target real`은 항상 현재의 실물 policy runtime, Fleet→장치 policy lease 연결,
  D-793 승인·실물 수용 미완료를 차단 사유로 남기며 exit 3이다. SIM I/O 준비 통과는
  exit 0이고, 잘못된 입력·보고서 쓰기 실패는 exit 2다. 보고서는 실행 권한이 아니다.

설정·설치·명령은 [CORE_LEROBOT.md](../../../integrations/robots/omx/docs/CORE_LEROBOT.md),
복사용 비공개 설정의 시작점은 `integrations/robots/omx/core-record.json.example`이다.
기존 D-793 hardware owner의 `rule_based` 제한과 SIM session 제한을 유지했다.

## 검증

모든 pytest는 커밋을 전달하여 승인된 원격 AI PC에서 실행했다.
모델 PC 도달 불가 및 시험 자원 하한 미달 경고에 runner의 기존 대체 호스트 선택을 사용했다.
노트북 pytest는 실행하지 않았다.

| 커밋 | 실행 | 결과 |
|---|---|---|
| `ff74b5b0ab` | SDK 계약 RED | 새 deployment 모듈 부재로 1 expected failed |
| commit `abca4839667bdc9f2f57db93eb57e38e944acf11` | CORE API·native ROS·SDK·wheel | 22 passed, wheel fixture의 PATH 누락 1 failed |
| `f6050b86a7` | 실제 workflow build shell·오프라인 설치 | 1 passed, 0 skipped, NEW 0 |

두 번째 실행의 22개 통과에는 실제 SDK의 recorder loop, 합성 데이터 학습·추론,
preflight CLI JSON 읽기·차단 exit 3·파일 hash·보고서 덮어쓰기 거부·CORE 불가 시
차단 결과가 포함된다. 이후 제품 코드 변화는 없고 wheel fixture의 Python PATH를 보완했다.
wheel 시험은 workflow의 실제 build step을 실행하고, SHA256SUMS와 source SHA를 확인한 뒤
`pip install --no-index --find-links ... --target ...`로 내부 의존성을 오프라인 설치했다.
설치된 wheel의 두 entry point와 ROS/torch 없는 client import도 확인했다.

집중 실행:

```text
python tools/remote/remote_pytest.py --log-dir <external>/deploy-focused -- ROSY_OMX_NATIVE_RUNTIME_TESTS=1 middleware/core/api/test/test_arm_policy_api.py test/test_omx_native_ros_runtime.py test/test_omx_lerobot_integration.py test/test_omx_client_distribution.py
python tools/remote/remote_pytest.py --log-dir <external>/wheel-final -- test/test_omx_client_distribution.py
```

원시 로그: 저장소 밖 `%LOCALAPPDATA%/Temp/rosy-omx-core-lerobot/`의
`deploy-red/run-1.txt`, `deploy-focused/run-1.txt`, `wheel-final/run-1.txt`.
최초 wheel 실패는 remote runner가 절대 경로로 Python을 실행하고 하위 셸의 PATH는
바꾸지 않는 데서 발생했다. fixture가 setup-python과 같이 선택된 Python 경로를
하위 셸에 전달하도록 고쳤다. 제품 빌드 명령이나 의존성 검증을 생략하지 않았다.

독립 `core_arm_review`가 commit `abca4839667bdc9f2f57db93eb57e38e944acf11`과
main 통합 결과를 읽고 추가 권한·안전 계약 위반을 발견하지 않았다.
이 리뷰는 소스 검토이며 원격 시험 재실행이나 실물 수용이 아니다.

## 남은 실제 활성화 조건

대상 workcell/instance·설치된 정책 pin, 실제 CORE/owner 결선, D-793 C/D의 정책·shadow·
live lease 전달 및 owner 재확인, 두 사람의 L3 승인, 물리 한계와 독립 정지의 수용이 필요하다.
LIMITED 사용에는 G4도 필요하다. 새 CLI나 복사한 승인 문서는 이 조건을 대체하지 않는다.

checkpoint hash 시험은 합성 bytes의 지문 검증이다. 모델 품질·원격 모델과 승인된 정책의
동일성·실물 과제 성공을 증명하지 않는다. 새 GitHub workflow 자체는 아직 원격 repository에서
실행하지 않았다. push·실제 장치 설치·실물 학습 정책 구동을 수행하지 않았다.
