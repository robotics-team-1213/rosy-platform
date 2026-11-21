## 2026-11-21 · uncommitted · Account LAN 로그인 별칭 overlay(D-1064)

- 변경: deploy/site에 옵트인 compose.account-lan.yaml·Caddyfile.account-lan(8443 호스트 블록, 로그인 경로 허용 목록, 나머지 404), rosy-mdns-alias@.service 템플릿, account-lan-cert.sh(site CA leaf)를 더하고 후보 묶음·검증기·자동 갱신 overlay 순서에 등록했다. 방화벽·LAN 443은 그대로다.
- 증거: test/test_site_account_lan.py 12개 통과(로컬), Caddy 2.10.2 로컬 기동으로 허용 9개 200·차단 23개 404 확인, R에서 별칭 유닛 주소 추출 셸 읽기 전용 확인
- gate 변화: 원격 시험·R 활성화 전
- 결정: D-1064
- 교훈: 없음
