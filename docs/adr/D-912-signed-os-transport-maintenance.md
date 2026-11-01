## D-912 Signed OS transport maintenance with independent authority and durable recovery

**Status:** Proposed

### Context

사용자는 이미 기록한 Pinky 기준 카드에서 GitHub OS OTA를 시험하고 이후에는 바뀐 부분만 갱신하기를 요구했다. 기존 기준 OS의 전송기는 큰 GitHub asset 분할과 engineering canary 게시를 지원하지 않는다. 앱 SDK의 image-layer sync는 D-888에 따라 OS bootstrap을 바꿀 수 없다. 다음 OS 슬롯으로 넘어가도 그 슬롯에 내장된 bootstrap을 사용하므로, 오래된 전송기로 되돌아가는 설치를 지속 업데이트 완료로 취급할 수 없다.

### Decision

- 별도 운영자 실행의 OS 유지보수 경로로 전송기만 갱신한다. 대상은 frozen runtime의 `os_update_feed.py`, `os_update_stage.py`, `os_update_transport.py` 세 파일로 고정한다. controller, 정책 판정기, watchdog, health, commit, bootloader, 상태 저장소, 신뢰 앵커, systemd unit은 대상이 아니다. 앱 updater에 bootstrap 쓰기 권한을 추가하지 않는다.
- 정확한 원본 source/release, 대상 source, 파일별 preimage와 새 size/SHA, 운영자 canary와 installer 자체 SHA를 manifest에 묶는다. 같은 raw manifest에 기존 Ed25519 서명과 독립 OS CMS 서명을 모두 요구한다. 앱 서명키만으로 OS 쓰기 권한을 얻을 수 없다. CMS 신뢰는 이미지에 고정된 OS 앵커에서 가져오며 입력 package가 앵커 경로를 고르지 못한다. 개인키는 운영자 PC에만 둔다.
- 운영자는 SSH host key를 먼저 신뢰 경로로 확인하고 package와 실행할 installer의 서명·SHA를 검증한다. installer는 고정 OS 라이브러리를 사용한다. 새 전송기나 candidate hook을 설치 검증 과정에서 실행하지 않는다.
- controller와 native updater 잠금, 장치 claim, pending 없음, tryboot 없음, 기준 committed boot와 canary, 현재 파일의 exact preimage 및 서비스 idle을 확인한다. 진행 중인 OS 설치나 trial을 중단·덮어쓰지 않는다.
- 원래 정책과 백업을 private staging에 완성하고 PREPARED를 fsync한 뒤 유지보수 journal로 게시한다. 파일 교체 전 공유 업데이트 정책을 disabled로 내구 기록한다. 원래 정책이 disabled였다면 그대로 복원한다. 전체 파일 집합의 교체를 단일 파일 rename의 원자성으로 설명하지 않는다.
- COMMIT_INTENT 전 중단은 검증된 preimage로 복구하고, COMMIT_INTENT 뒤에는 새 파일 집합을 검증해 완료한다. 알 수 없는 현재 파일·정책·백업은 덮어쓰지 않고 HOLD한다. 정상 rollback 뒤 같은 인증 package를 다시 적용할 수 있어야 한다. 초기 백업 중단, 각 파일 교체, commit과 정책 복원 경계에서 실제 프로세스 종료 후 복구를 시험한다.
- 정책 freeze는 Python import의 원자성을 뜻하지 않는다. 유지보수 중 timer가 시작되면 일시적으로 client import가 실패할 수 있으나, 기존 잠금과 disabled 정책이 설치를 막고 다음 실행은 일관된 파일 집합을 사용해야 한다. 새로운 service 제어나 후보 코드 실행으로 이 경계를 우회하지 않는다.
- 전송기 유지보수 뒤에는 새 전송기를 포함한 N+1 OS를 기존 서명·A/B lifecycle로 설치한다. 이전 전송기가 들어 있는 OS로 돌아간 상태를 자동 업데이트 완료로 기록하지 않는다. 장치 신원·Wi-Fi·보정·영속 데이터의 소유권은 바꾸지 않는다.

### Consequences

기준 카드 재기록 없이 OS 전송기를 이행할 수 있지만, 이 유지보수는 새로 검증해야 하는 OS 소유 경로다. 기존 앱 배포 권한과 혼동하지 않는다. GitHub 배포용 분할 파일은 원래 bundle 서명·해시를 유지하고 재조립 후 전체 검증을 통과해야 한다. Engineering prerelease는 서명된 canary만 허용하며 일반 배포 승격을 뜻하지 않는다.

SOURCE와 모델링된 중단 복구 시험, ARM 이미지 구성, MEDIA, 실제 boot와 OTA·rollback은 서로 다른 증거다. 이 결정은 구현 또는 실물 수용 완료를 선언하지 않는다.
