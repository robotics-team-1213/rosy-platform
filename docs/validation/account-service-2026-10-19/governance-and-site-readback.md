# D-807 문서 관문과 운영 설정 추가 확인

2026-10-19 추가 기록. 앞선 [구현·검증 결과](results.md)를 수정하지 않고 후속 관찰을 기록한다. 실제 주소·계정 값·키는 공개 기록에서 제외한다.

## 문서 관문

커밋 `6a80a63e55`를 모델 PC에서 아래 명령으로 실행했다.

```powershell
python tools/remote/remote_pytest.py --sha 6a80a63e55 --log-dir <external-log-dir> -- test/test_harness_contracts.py test/test_network_topology_contracts.py test/architecture/test_document_placement.py test/architecture/test_folder_layout.py -q
python test/known_failures.py <external-log-dir>/run-1.txt
```

실제 결과: 142 passed, 0 skipped, exit 0, NEW/known/flaky 0. 원격 로그는 `%TEMP%/rosy-account-rollout-20261019/final-governance/run-1.txt`, SHA-256 `be26641f253ba8b6d5a12608b43935bfb330ee426179f118b8f1e4258ddb3701`이다. 로컬 harness generate·lint exit 0, lint 오류 0·기존 freshness 경고 32개, git diff --check 통과를 확인했다. 전체 CI·착지 관문을 대체하지 않는다.

## 운영 readback

사용자는 기존 관리자 로그인 ID 후보를 알려줬고 issuer/설정 위치는 모른다고 답했다. 기존 승인된 현장 SSH와 Docker의 읽기 전용 조회로 확인했다. Docker inspect 전체 환경을 출력하지 않고 필요한 비밀 아닌 설정만 선택했다. 기존 사용자 파일은 컨테이너 UID10001로 읽고 정확한 후보 일치 개수만 반환했다. 비밀번호/해시·키 원문은 출력하지 않았다.

- 실행 중인 Fleet의 `ROSY_ACCOUNT_CONFIG`는 빈 문자열이다. 이번 readback에서 중앙 Account 활성화는 꺼져 있다.
- Account 마운트의 호스트 디렉터리는 비어 있다. 현장 site.env는 현재 SSH 계정에 읽기 권한이 없으며 비대화식 sudo는 인증을 요구한다. Docker의 높은 권한으로 이 파일을 우회해서 읽거나 쓰지 않았다.
- 기존 관리자 로그인 후보는 site-users의 구조화된 항목에 정확히 1개 존재한다. 이는 Account 마이그레이션·관리 권한 부여·실제 로그인 성공의 증거가 아니다.
- 기존 proxy는 HTTPS 8443을 호스트에 공개한다. 443은 공개 바인딩이 없다. 인증서 SAN은 기존 `.local` 이름과 내부 서비스 이름이며 Android에 필요한 신뢰된 HTTPS 도메인 인증서가 아니다.
- 기존 tailnet의 사이트 MagicDNS 이름은 확인했다. `tailscale serve status --json`은 빈 설정이다. 이 이름은 issuer 후보일 뿐, tailnet HTTPS 발급/443 연결·신뢰·앱 callback 검증이 완료되지 않았다.

따라서 issuer를 사용자에게 추측해서 입력하게 하는 대신 기존 tailnet 이름·신뢰된 인증서·tailnet 한정 443 연결을 먼저 검토한다. 실행 가능한 전환에는 해당 관리 권한, 승인된 도메인/접근 정책, 정확한 receiver callback/resource와 native 설치 signer가 필요하다. 기존 `.local:8443`을 Android SSO 완료로 처리하지 않는다. site.env 변경·새 인증서 발급·serve 활성화·계정 승격·키 생성·서비스 재시작·서명 배포는 수행하지 않았다.

소스 수정과 지정 원격 검증은 끝났지만 운영 전환·운영 설정 포함 native 빌드·실사용·격리 복구는 남아 있다. 지속 목표는 active이며 완료로 바꾸지 않는다.
