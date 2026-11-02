# ROSY Monitoring 사이트 overlay 현장 수용 — 2026-11-01

서명 후보 `site-2ba97ac2c346`(source `2ba97ac2c346`, PR #224 merge)가 2026-11-01 00:17 UTC에 사이트 호스트에 설치됐고,
같은 날 `compose.monitoring.yaml` overlay가 `site.env`에서 활성화됐다(백업 `site.env.bak-monitoring-20261101-105026`,
compose 순서 workcell→monitoring→Account). 본 기록은 그 배포에 대한 실제 단절·거부·TLS 수용 관측이다.
호스트에서 실제 컨테이너 정지·재시작으로 관측했고, 원격 클라이언트(관제망 노트북)에서 TLS를 확인했다.
시각은 UTC. 관측 프로토콜: 프록시 `https://<site>:8443`, reader 키는 `/etc/rosy/monitoring/secrets/site_read`(값 미기록).

## 기준선(P0)

`/monitoring-health` 200, `/monitoring/` 200, `GET /api/monitoring/v1/snapshot`(Bearer site_read) 200.

## 인증 거부(P1)

- 자격 없음: snapshot → **401**.
- 용도가 다른 키(fleet_upstream)를 reader로 사용: snapshot → **401**.

## 범위 거부(P2)

등록 scope 밖 사이트의 `GET /api/monitoring/v1/sites/nonexistent-site/events` → **403**.

## Fleet 원천 단절(P3)

`docker stop rosy-site-fleet-1`(약 18초) 뒤 8초 시점:
`/monitoring-health` **200**(수집기 독립), snapshot의 fleet 노드 `age_s` 9.19 / `valid_for_s` 15 —
**원천 판정과 신선도가 구별**된다(신선도 만료 전 관측). `docker start` 후 약 24초 만에 fleet 회복(healthz 200),
snapshot 시퀀스 계속 증가하며 fleet 원천이 다시 fresh로 돌아왔다.

## 모니터링 서비스 단절(P4)

`docker stop rosy-site-monitoring-1` 직후: `/monitoring-health` **502**(프록시가 backend 단절 보고),
같은 순간 Fleet `/healthz` **200**, `/console/` **307**(정상 리다이렉트) — Fleet/콘솔 무영향.
`docker start` 뒤 200으로 회복.

## 원격 클라이언트 TLS(P5)

관제망(tailnet) 노트북에서 `--resolve`로 사이트 이름을 고정해 관측:

- TLS 핸드셰이크 성공(네트워크 경로 정상), 기본 신뢰 저장소는 거부(schannel `untrusted root`,
  CA 등록 후 `CRYPT_E_NO_REVOCATION_CHECK` — 사설 CA 무폐기목록 문제로 [런북](../../deploy/site/README.md)의
  `--ssl-revoke-best-effort` 진단 한정 사용).
- 사용자 신뢰 저장소에 사이트 CA 등록 + 해당 옵션으로 `/monitoring-health` **200**, `/console/login` **200**.
- 제한: 폐기 상태 검증은 아니며(런북 제한 그대로), 브라우저 화면 육안 확인은 사람 온보딩 시행 예정.

## 한계와 남은 관측

- 로봇이 2026-10-10 이후 오프라인이어서 **로봇 원천 단절 관측은 보류** — 로봇 연결 뒤 snapshot의
  robot 노드 신선도로 동일 시나리오를 보강한다.
- 단일 사이트 배치라 중앙 집계·peer 전달 경로는 이번 범위가 아니다(D-876 peer 시험은 별도).
- 관측 창은 분 단위다. 장기 안정성·메모리 상한(256 MiB 시작값)은 운영 관측로 조정한다.

## 함께 기록하는 발견

1. **vault 잔존은 현재 제품 의존이다.** `deploy/site/account_tls_renew.py:104` `reload_vault_proxy()`가
   `rosy-vault-proxy-1`(compose project `rosy-vault`)을 "Vault TLS consumer"로 요구하고, 없으면
   RuntimeError로 갱신이 실패한다. 저장소는 2026-10-24 vault를 은퇴했지만 사이트 TLS 갱신 경로는
   여전히 이 컨테이너를 필요로 한다 — 제거는 갱신 스크립트에서 이 소비자를 걷어내는 제품 변경 뒤에만 가능하다.
2. **대역 외 서명 관행.** `site-fa3aeeed4d92`·`site-2ba97ac2c346`의 `release.json.sig`는 자동서명기 감사 밖에서
   만들어져 제목이 "(unsigned)"로 남았다. 2026-11-02 정본 `verify_manifest_signature`(등록 키
   `rosy-site-bench-20261003`)로 **두 서명 모두 유효** 확인 후 제목·본문을 "(signed)"로 바로잡았다.
   근본 문제(녹색 CI 전 수동 서명이 출처 심사·감사·재제목을 우회)는 README 서명 절에 규칙을 추가해 막는다.
