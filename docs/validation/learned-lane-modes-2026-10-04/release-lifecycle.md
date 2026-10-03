# 설정 담당 서비스의 릴리스 종료 경계

확장 검사에서 새 `rosy-host-agent.service`가 `PartOf=rosy-runtime.target`인데도 릴리스 관리자의 명시적 종료 대기 목록에는 빠진 것을 확인했다. 이전 코드의 권한 있는 설정 담당 프로세스가 릴리스 전환을 넘어 남지 않도록 종료 목록에 포함했다.

종료는 동기식 `systemctl stop`이며 오류나 제한 시간 초과 시 후보 시작과 current/previous 링크 전환을 하지 않는다. 복구용 prepared journal은 보존한다. 시작은 기존 runtime target 소유권을 따른다. target의 Wants 또는 enable 반환값만으로 담당 서비스 준비 완료를 주장하지 않는다.

집중 검증: native activation/systemd 계약 195 passed, 1 skipped. 종료 목록에서 서비스를 누락시키는 메모리 내 결함 주입으로 기존 종료 계약 검사가 실패함을 확인했다. 분리된 카메라 프레임 모듈의 실제 import/제공 경로/인증/취소 계약 47 passed, API 문서 v1.91의 Fleet 계약 22 passed.

기기에서는 현재 설치된 activation helper와 서비스 정의를 함께 확인해야 한다. 이전 기기에 없는 서비스를 새 helper의 종료 목록으로 요구하려면 서비스 설치와 daemon-reload가 먼저 완료되어야 한다. 기존 bootstrap helper를 동기화하기 전에는 후보 소스의 수정만으로 배포 동작이 바뀌었다고 주장하지 않는다.

SOURCE/LOCAL 증거다. ARM64 빌드, installed helper readback, 실제 서비스 PID와 current 릴리스 일치, 실기 녹화와 조명 전후 촬영은 별도 검증이다.

독립 Safety Review `lowlight_research`: native activation/image-layer 95 passed, 6 skipped. activate와 rollback 모두 링크 전환 전 같은 동기 종료 장벽을 사용함을 확인했다. image-layer 동기화의 서명·허용 목록·백업·install→daemon-reload→enable 경계는 유지하며, 설치 helper와 unit 선행 조건 및 실제 PID/current 확인을 조건으로 이 수정의 안전 검토를 승인했다. Windows skip은 실기 증거가 아니다.

통합 재검증: 수정된 7개 실패를 포함하는 Dashboard/role/Fleet/native 계약 256 passed, 1 skipped. 이전 확장 검사 실패 결과를 합격으로 대체하는 주장이 아니라 수정 후보의 집중 검증 결과다.
# Concurrent main integration

The local merge preserves both the lane Host Agent and the main branch's opt-in SSH pairing service. Both installed helpers and target dependencies remain present, and both `PartOf=rosy-runtime.target` services are named in the synchronous stop list before the release links change. The two native command allowlists, CORE peer credentials, audit trails and socket paths remain separate. Independent scoped merge review passed 191 tests; coordinator native/API checks passed 162 with 7 platform skips. These are SOURCE/LOCAL results.

The signed ARM64 candidate `2026.10.04-034` was built from `c3d2a37d614cbf8e87f6dce8af47bc892edb71be`, before this integration. Its build, signature and ABI evidence do not certify the merged revision. No merged runtime or illumination/IR motion trial was installed or activated during integration.

