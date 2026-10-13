# Site functional verification activation

기존 D-441 선택적 GET 검사 설정을 실제 현장에 활성화한다. 기존 운영자 토큰을 자동 검증에 재사용하는 대신 별도 viewer principal과 root 전용 토큰 파일을 둔다. 기존 사용자의 digest, 로봇 enrollment/credential key, 카메라 calibration과 updater hold 상태는 보존한다.

- 설치 전 기존 운영자 자격으로 Fleet state, enrollment와 Vision source 목록을 조회한다. 인증값과 preview lease는 출력하지 않는다.
- 설치기는 updater lock 안에서 설정을 다시 읽고, 진행 중 전환/작업이 있으면 멈춘다. 기존 구성·사용자와 원래 타이머 상태를 백업하고 중단 복구 기록을 남긴다.
- viewer digest만 사용자 registry에 추가하며 raw token은 root0600 파일에만 둔다. Fleet을 재시작하여 읽기 권한이 실제 적용된 것을 확인한다. 다른 사용자는 보존한다.
- 기능 검사는 등록된 로봇 ID와 지정된 Vision source를 요구한다. ID 존재는 online/physical acceptance를 뜻하지 않는다. 짧은 source lease로 실제 JPEG 순번·freshness를 별도로 확인한다.
- 두 로봇의 live 서비스·연결·안전 상태는 읽기 전용으로 검증한다. roster 정적 alias와 enrollment의 충돌을 기록하며, 이미 승인된 marker/calibration을 추측해 수정하지 않는다. 구동 또는 E-Stop 해제는 별도 현장 승인과 조건을 요구한다.

기존 운영자 자격 재사용은 설치 중 조회에만 한정한다. viewer를 직접 생성할 수 없는 환경은 승인된 secret manager로 발급한 기존 viewer 파일을 사용한다. 실제 token, 주소, 장치 목록은 public repo에 두지 않는다.
