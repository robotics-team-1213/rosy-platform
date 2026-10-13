# 숙고 호스트 설치·수용 경계 검증

- Tested source: `c21b8bea0c` / `fix/deliberation-host-admission`.
- Contract: D-640, D-672, D-516. 기존 결정·배포 계약의 구현 보강이다.
- 원격 Model PC 회귀 및 구조 검사: 66 passed, exit 0. `known_failures` 비교는 NEW 0.
- Log: `X:/DevTemp/projects/rosy-platform/2026-10-12--023355--deliberation-host-admission--4a3286/logs/final-source-3/run-1.txt`.
- Log SHA256: `b71f5d8a0c3f785c3ea422e0078f31b215bc3bffc90d4efcdc3a68e43e6c015d`.

Model PC와 AI PC의 실제 bwrap 실행이 실패했고, kernel audit의 `unprivileged_userns` capability 거절과 양쪽 `sudo -n` 암호 요구를 확인했다. 설치된 호스트 수용 PASS는 없다.

전용 root 소유 bwrap 경로와 단독 system 계정에만 namespace 예외를 설치하는 도구를 추가했다. 설치 후 계정·그룹 변경도 같은 읽기 전용 검사로 거절한다. systemd에서 수집된 scope는 실제 `LoadState=not-found` readback으로 확인하고, 다른 서비스 이름을 거절한다. 실제 살아 있는 setsid 자식의 cgroup을 관측한 후 취소·시간 초과 종료를 확인하는 preflight를 제공한다. 회귀 시험에서 설치 거절·계정 drift·빈 관측의 오인 통과·실제 user manager의 수집된 scope 확인을 검사했다.

Source는 검증됐으나 관리자 설치와 실제 preflight 성공은 미확인이다. [적용 계획](../../plans/2026-10-12-deliberation-host-admission.md)에 고정 digest와 관리자 명령을 기록했다. `PASS_HOST_OFFLINE_ONLY`도 실제 모델 호출이나 FIELD 수용을 뜻하지 않는다.

운영 숙고는 AI PC, 독립 평가·학습은 Model PC의 역할을 유지한다. Discord는 별도 세션 소유이며 변경하지 않았다. 모델 ID·인증·의존성·네트워크·비용 한계와 팀의 Pinky 정답/평가 한계 확인은 아직 열려 있다. 로봇 명령·실제 제공자 호출·자동 학습 승격을 수행하지 않았다.
