# 장치 네트워크 복구 검증 기록

상태: 소프트웨어 통합 검증 중. 배포·실물 수용 완료 기록이 아니다.
검증 기준 브랜치: `feat/network-recovery`, `feat/device-network-recovery`.
결정 D-863/API v1.311. 최종 병합 후보는 검증된 checkpoint의 동일 소스에서 구성한다.

모든 pytest는 공식 remote runner가 커밋된 revision에서 실행했다. 개발 PC에서 pytest를
실행하지 않았다. 로그 루트는 개발 PC의 `%TEMP%`이며 아래 폴더의 `run-1.txt`다.
표의 개수는 선택별로 겹치므로 합산하지 않는다.

| Revision | 로그 폴더 | 선택/결과 |
|---|---|---|
| `3b29e960ce` | rosy-network-recovery-core-launcher-green-20261024 | CORE host cards, recovery launcher/auth: 107 passed |
| `9198a18c7b` | rosy-network-recovery-boundary-green-20261024 | CORE cards, launcher, native agent/transaction/handoff, firstboot, fallback/runtime, generic HostAgent, artifact impact: 332 passed |
| `9198a18c7b` | rosy-network-recovery-ui-green2-20261024 | `ROSY_RUN_BROWSER_TESTS=1` dashboard host operations + recovery browser: 10 passed, no skips |
| `e9423852f7` | rosy-network-recovery-update-green3-20261024 | publisher, push entry/claim, boot/image layer, updater apply/resume/check/eligibility/resync, display/face: 680 passed, 60 skipped |
| `797d58a9a0` | rosy-network-recovery-install-green-20261024 | installed isolated imports, native authority, launcher/display: 41 passed |
| `c60d6046bb` | rosy-device-network-recovery-final-green-20261024 | final source: native units/agent, firstboot, transaction/handoff/fallback/runtime, launcher/display/face, CORE cards: 633 passed, 1 skipped |

각 GREEN 로그의 `test/known_failures.py` 비교는 NEW 0 / known 0 / flaky 0이다.
원격 PowerShell 부재 등을 포함한 60 skips는 통과 근거로 사용하지 않는다. 개발 PC의
PowerShell로 실제 operator 스크립트 `-PrintCommands`를 두 번(SkipImageLayerSync 포함)
실행해 inverse 순서를 확인했고, SSH를 로컬 fake script로 대체한 두 실패 주입에서
preflight 실패→native rollback 미실행, inverse apply 실패→구형 sync 미실행 및 claim
해제를 확인했다. 이는 실제 SSH·systemd·장치 검증이 아니다.

독립 검토에서 세 경로를 추가 발견했다: 시작 시 유지보수 불가였던 미완료 작업의 재처리,
fallback AP와 updater claim 경합, boot reconcile 실패를 무시하던 systemd 접두사.
각 RED를 재현하고 `137692cfd6`에 수정했다. 권한 inventory와 파일 크기 분리까지 반영한
`c60d6046bb`에서 해당 경로를 포함한 633 passed를 확인했다. 최종 unit 소스는 독립
계약 리뷰에서 `8441815543`에 결속했고 이후 디렉터리 조건과 Python user-site 차단을 추가했다.

검증하지 않은 범위: signed ARM64 이미지 생성/실행, 실제 NM 프로필·radio 전환, 사람의
TLS 지문 등록, LCD 실제 표시, Pinky 재부팅·정전 중단, 기존 이미지→bridge→기능 OTA 및
실물 rollback. 인터넷/전원이 없는 장치에 OTA가 적용됐다고 주장하지 않는다.
