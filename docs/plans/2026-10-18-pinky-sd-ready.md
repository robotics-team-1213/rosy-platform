# Pinky SD 배포 준비 계획 및 실행 기록

## 목표

PowerShell 명령 한 번으로 기존 도구의 이미지·Wi-Fi·카드 선택을 안내하고,
서명 검증과 전체 readback 후 첫 부팅 설정 및 자동 업데이트 상태를 확인한다.
사용자는 2026-10-18에 이 방식을 선택하고 작업용 worktree 1개의 상한 예외를 승인했다.

## 범위와 설계

- 기존 `deploy/robot/pinky_pro/sd/setup-moved-device.ps1`를 재사용한다.
  로봇 주소를 생략하면 새 카드 준비, 명시하면 기존 이동 카드 SETUP 검사를 수행한다.
  빈 주소를 명시한 경우는 잘못된 입력으로 중단한다.
- 카드 쓰기와 검증은 기존 `prepare-rosy-sd.ps1` 및 `write-card.ps1`에 남긴다.
  `core` 계획, REGISTER·ERASE 확인, 시리얼 재확인, 전체 readback을 유지한다.
- Wi-Fi와 등록부가 없으면 필요한 준비를 안내한다. 등록부를 자동 초기화하지 않는다.
- 첫 부팅·자동 업데이트 구현은 바꾸지 않는다. 실제 timer/status 확인 명령을 안내한다.
- 새 GUI, 자동 디스크 삭제, 모터·주행 활성화는 이번 범위에 포함하지 않는다.

## 실행 단계

- [x] 기존 SD·first-boot·D-412 자동 업데이트 경로 및 저장소 규칙 확인.
- [x] 작업 공간 상한 60개 및 정리 가능 항목 0개 확인.
- [x] 사용자 예외 승인 후 공식 도구로 `.worktrees/pinky-sd-ready`,
  `feat/pinky-sd-ready` 생성.
- [x] 새 카드에 주소가 필수여서 실패하는 PowerShell 회귀를 먼저 재현.
- [x] 주소 생략 경로, 잘못된 명시 주소 차단, 업데이트 상태 안내 구현.
- [x] 실제 카드 대신 fixture를 사용하는 네이티브 PowerShell self-check 추가.
- [x] 운영 런북에 단일 시작 명령, 준비물, 로그·receipt·첫 부팅·업데이트 확인 추가.
- [x] 최종 네이티브 self-check, 커밋 후 원격 관련 pytest, known_failures 비교.
- [ ] 서명된 현재 이미지 확보 및 source revision 확인.
- [ ] 지정한 실제 SD 기록/readback, Pinky 첫 부팅 및 자동 업데이트 상태 확인.

## 산출물과 검증

- 제품 변경: `deploy/robot/pinky_pro/sd/setup-moved-device.ps1`.
- 검증: `deploy/robot/pinky_pro/sd/test/Setup-MovedDevice.Tests.ps1`,
  `test/test_sd_guided_setup.py`. 네이티브 검증은 주소 생략 준비, 잘못된 주소,
  누락 등록부·Wi-Fi, 이동 카드 SETUP 게이트, 기존 작성기 위임을 실행한다.
  HTTP·디스크·하위 작성기는 fixture이며 실제 서명 또는 매체 검증을 대신하지 않는다.
- 운영 절차: `docs/deployment/pinky-pro-first-device-runbook.md`.
- 원격 검증은 커밋된 HEAD만 사용한다. Windows PowerShell이 없는 호스트의 skip은
  통과로 세지 않고 네이티브 self-check 결과와 구분한다. 노트북 pytest는 실행하지 않는다.

### 실행 결과

- 제품 코드 커밋: `efa12a92be` (`feat/pinky-sd-ready`). 작업 시작 기준선은
  `34e4ca99339bbbaf491fb9278bd313134ea6fdbb`이며 변경은 9개 파일이다.
- Windows PowerShell 네이티브 self-check: 6개 PASS. 작성기와 디스크는 fixture다.
- AI PC 원격: `test_sd_guided_setup`, `test_new_device_setup`,
  `test_sd_write_card_entrypoint`, `test_sd_personalization`, `test_rosy_auto_update`,
  `test_image_layer_sync`의 6개 파일에서 **366 passed, 30 skipped**, 137.95초.
  Windows PowerShell 전용 회귀는 원격 Linux에서 건너뛰므로 네이티브 결과와 구분한다.
- `test/known_failures.py`: **0 new, 0 known, 0 flaky**.
  로그는 저장소 밖 `%TEMP%\rosy-pinky-sd-ready\run-1.txt`에 보존했다.
- 기존 `rosy-new-device-setup.py` HTML 문자열의 `\d` SyntaxWarning 2건은 남아 있다.
  해당 런타임 파일은 이번 작업에서 변경하지 않았다.
- 독립 전체 변경 리뷰: material finding 0건. 리뷰어는 시험을 재실행하지 않았다.
- harness generate 실행, lint **0 errors**(기존 상태 노후화 등 33 warnings),
  size-range 및 diff whitespace 검사 통과. 영향 선택은 `affected`, FULL 승격 없음.
  영향 선택의 전체 25개 경로 시험이나 전체 저장소 suite는 이번에 실행하지 않았다.

## 확인한 배포 제약

2026-10-18 GitHub 조회에서 최신 flashable-image 성공 실행은 `37854726829`,
source revision `5a3f6ad6e543d843fd1816366aa510584d2d6369`,
2026-10-09 07:38 KST다. 해당 실행의 현재 Actions artifacts 목록은 비어 있다.
`livsbittt/rosy-os`의 조회된 releases에도 `.img.xz` asset이 없다.
payload release `payload-2026.10.10-164`는 tarball과 rollout 서명 asset을 제공하지만,
그것은 새 SD에 기록할 전체 이미지가 아니다. 보관된 서명 이미지를 검증하거나
별도의 이미지 빌드·서명이 필요하다. 빌드 성공 이력을 서명·실기 수용으로 취급하지 않는다.

로컬 작업 폴더·Downloads·임시 폴더에서 찾은 실물 크기의 전체 이미지는
`Rosy/artifacts/2026.09.22-001-58c9e8ad/`의 `2026.09.22-001`이다.
공식 `verify-image-release.py`로 공개키 서명과 전체 파일 checksum 검증을 통과했다.
기록된 source revision은 `58c9e8ad7016e0cac8a346e1f78f3c49d75bda66`으로
D-412 자동 업데이트 도입 전의 기준선이다. 이를 최신 자동 업데이트 이미지로
선택하지 않는다. 새 배포 이미지를 빌드·서명하거나, 다른 보관 위치의 최신 서명
이미지를 제공받아 검증하는 것이 다음 단계다.

병합·푸시·릴리스 공개는 수행하지 않는다. 대상 카드와 장치가 정해지기 전에는
물리 디스크를 지우지 않는다. 코드·호스트 시험, SD readback, 첫 부팅, 실제 자동
업데이트는 각각의 증거가 있어야 완료로 표시한다.

## 반영·이미지 빌드 승인 후 진행 (2026-10-18)

사용자가 변경 반영·push와 새 이미지 빌드 진행을 승인했다. 로컬 main에는 원격에
없는 커밋 426개가 있어, 이를 함께 발행하지 않고 이번 작업의 두 커밋만 원격
`3a77b51c185a6473c8b086245a41e88b3b180ab0` 위에 재적용했다. 기존 검증 브랜치는
`docs/pinky-sd-verified-local`로 보존했다. 기록 충돌은 원격 기록을 유지한 뒤
이번 작업 행만 붙이고 index를 재생성했다. PR 검증 후 원격 main에 반영한다.

원격 기준에는 안내 도구의 `X:\DevTemp` 고정 경로가 남아 있어 네이티브 회귀가
실패했다. `ROSY_SCRATCH` 또는 Windows 임시 폴더를 쓰도록 보완해 동일한
6개 self-check가 다시 통과했다. 이전 AI PC 366 PASS는 이전 기준선의 증거이며,
재적용 후 커밋의 원격 검증·pre-push·CI는 별도로 기록한다.

- [x] 최신 원격 기준으로 작업 커밋만 재적용, 네이티브 6개 재검증.
- [ ] 반영할 커밋의 원격 pre-push 검증, 작업 브랜치 push, PR·CI·병합.
- [ ] 병합된 source revision으로 native ARM64 전체 이미지 빌드.
- [ ] unsigned handoff 확보·검증, 기존 신뢰 키의 승인된 서명 환경에서 서명·검증.
- [ ] 실제 카드와 Pinky를 지정한 뒤 기록/readback·첫 부팅 확인.
