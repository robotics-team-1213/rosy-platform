---
title: "The site updater's post-switch firewall check needs netlink inside its sandbox"
date: "2026-11-20"
module: "Site host automatic update (D-441)"
problem_type: runtime_error
component: deployment
severity: high
symptoms:
  - "rosy-site-autoupdate logged recovery-pending every 15 minutes: ROSY-SITE-INGRESS does not admit only lo,enp1s0,tailscale0; run: systemctl restart rosy-site-firewall.service."
  - "The live mangle chain matched the candidate's expected listing exactly, and the same check passed under sudo."
  - "R never moved past a manually installed image; merged console fixes did not reach the site."
root_cause: config_error
resolution_type: config_change
tags: ["site", "autoupdate", "systemd", "iptables", "netlink", "firewall"]
---

# 사이트 갱신기의 방화벽 검사는 netlink가 있어야 돈다

## 문제와 원인

`rosy-site-autoupdate.service`는 `RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6`로 돌았다.
전환 뒤 `site-firewall.py check`가 `iptables -t mangle -S`를 부르는데, iptables는 netlink 소켓을 연다.
샌드박스 안에서는 이 호출이 실패하고 check는 "규칙이 다르다"로 보고한다. 힌트대로 방화벽을
재시작해도 규칙은 이미 맞으므로 아무것도 바뀌지 않는다. R은 11-09 이전 뒤 수동 설치만 했기 때문에
2026-11-20 첫 자동 전환에서 처음 드러났다.

## 확인 방법

같은 check를 두 번 돌려 비교한다. 규칙을 바꾸지 않는 읽기 전용 확인이다.

```bash
sudo systemd-run --quiet --wait --pipe -p "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6" \
  python3 /opt/rosy/candidate/deploy/site/site-firewall.py check --env-file /etc/rosy/site/site.env \
  --compose-file /opt/rosy/candidate/deploy/site/compose.yaml      # 실패
# AF_NETLINK를 더하면 "port 8443 is limited to ..."로 통과
```

## 해결

유닛에 `AF_NETLINK`를 더했다(`deploy/site/rosy-site-autoupdate.service`, `test/test_site_autoupdate.py`가 고정).
설치된 호스트는 같은 줄을 drop-in(`rosy-site-autoupdate.service.d/20-netlink.conf`)으로 넣고
`systemctl start rosy-site-autoupdate.service`를 두 번 돌렸다. 첫 실행은 남아 있던 전환을 정상 롤백했고(recovered),
둘째 실행이 서명 후보 `ce408cd608`을 설치했다(installed).

## 다음에 적용할 조건

- 갱신기 판정이 `recovery-pending`이고 사유가 방화벽·네트워크 도구의 실패라면, 규칙을 고치기 전에
  같은 명령을 그 유닛의 샌드박스 속성으로 다시 돌려 본다.
- 샌드박스 유닛에서 외부 도구를 새로 부르게 바꾸면 그 도구가 여는 소켓 종류(netlink 등)를 확인한다.
- 방화벽 힌트(`systemctl restart rosy-site-firewall.service`)는 규칙이 실제로 다를 때만 의미가 있다.
