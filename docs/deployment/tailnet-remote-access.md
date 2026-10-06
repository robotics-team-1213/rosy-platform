# 테일넷 원격 접속 안내 (D-477)

팀원 4명이 현장 LAN 밖에서 로봇 SSH와 관제 콘솔을 함께 쓰기 위한 망 구성 안내다.
결정과 이유는 [D-477](../adr/D-477-tailscale-tailnet-team-remote-access.md),
SSH 세 갈은 [로봇 SSH 접속 안내](robot-ssh-access.md)가 정본이다.

- **tailnet은 전송 계층이다.** 도달성만 준다. SSH는 여전히 D-418의 키(화면 코드 등록·팀 키)가,
  콘솔은 D-276의 site 계정이 각각 필요한 2단계 구조 그대로다. Tailscale SSH(대리 로그인)는 쓰지 않는다.
- 로봇 임시 비밀번호는 현장 LAN(RFC1918) 전용이다. tailnet 대역(100.64.0.0/10)에서는 켜지 않는다.
- 이 저장소는 공개다. 실제 tailnet 이름·주소·키는 문서에 적지 않고 `private/`(D-226)에 둔다.
- 로봇은 `tag:rosy-robot` 태그의 tagged resource로 등록한다(개인 계정 소유가 아니므로 담당자 변동과 무관).

## 1. tailnet 준비 (Tailscale 관리 콘솔, 한 번)

1. 소유자가 기존 tailnet(model·site PC가 이미 붙어 있는 것)을 팀 망으로 쓴다.
   플랜은 Personal(무료, 사용 6명 한계, 비상업 한정)이다. Rosy가 상업으로 전환되면
   Standard로 승격한다 — tailnet은 그대로 유지된다(D-477 R2가 이 전환 트리거다).
2. 팀원 3명을 각자 계정으로 초대한다. 개인 노트북은 사용자 기기라 인원만 센다.
3. 태그를 정의하고 ACL을 최소화한다: `tag:rosy-robot`, `tag:rosy-site-pc`.
   기본 전체 허용을 그대로 두지 않고, 팀원 → 로봇·site 방향만 열고 기기 → 팀원 기기 방향은 막는다.
4. **auth key**를 발급한다: 태그 `tag:rosy-robot` 사전 승인(auth key)으로. 만료는 짧게(1일 권장).
   키는 아래 2의 경로에만 둔다.

## 2. auth key 보관

```
private/tailscale-auth-key.txt    # gitignored. 양식은 sd/tailscale-auth-key.template.txt
```

키는 저장소·채팅·영수증·로그에 남기지 않는다. 카드 번들은 첫 부팅 뒤 스스로 사라지고,
운영 영수증에는 지문(sha256 앞 16자리)만 기록된다.

## 3. 로봇 가입 — 개발 기기 1대부터 (D-477 7항)

**새 카드를 구울 때:** 카드 준비 단계에서 join 키를 번들로 전달한다
(`tailscale_auth_key`, 선택 `tailscale_tags`). 첫 부팅이 `/etc/rosy/tailscale-join.json`(0600)을 쓰고
`rosy-tailscale-join.service`가 키를 한 번 소진한다. 키가 없으면 이 단계 전체가 건너뛰어진다(LAN 전용 로봇).

**이미 돌아가는 로봇에 수동으로:** 이미 키 등록으로 SSH가 되는 운영자가 join 파일을 쓰고 유닛을 시작한다.

```sh
# 로봇에서 (operator SSH 접속 후)
sudo install -m 0600 /dev/null /etc/rosy/tailscale-join.json
sudo tee /etc/rosy/tailscale-join.json >/dev/null <<'EOF'
{"auth_key": "tskey-auth-...", "tags": ["tag:rosy-robot"], "hostname": "rosy-pinky-xxxx"}
EOF
sudo systemctl start rosy-tailscale-join.service
```

`hostname`은 로봇의 공용 이름(`rosy-pinky-xxxx`) 그대로다. MagicDNS 이름은
`rosy-pinky-xxxx.<tailnet>.ts.net`으로 결정된다.

**확인:**

```sh
systemctl status rosy-tailscale-join.service        # joined / already_joined
sudo cat /var/lib/rosy/tailscale/join-result.json   # 결과 기록(키 없음)
sudo tailscale status
journalctl -u rosy-tailscale-join -u tailscaled --no-pager | tail -40
```

join이 실패하면(키 만료·업링크 없음) 결과 파일의 `error`를 보고, 새 키로 join 파일을 다시 쓰고
유닛을 다시 시작한다. 실패한 시도는 키를 소진하지 않는다.

## 4. 관제 콘솔 원격 허용 (site PC, 한 번)

site PC는 이미 tailnet에 있다. 방화벽 허용 목록에 `tailscale0`을 추가한다.

```sh
# site PC의 /etc/rosy/site/site.env
ROSY_SITE_LAN_IFACE=wlan0,tailscale0
```

변경 뒤 `sudo systemctl restart rosy-site-firewall.service`(또는 site 스택 재시작)로 적용한다.
포트 포워딩·공인 노출은 하지 않는다. 팀원은 브라우저로 `https://<site-pc>.<tailnet>.ts.net:8443/console`을
열고 자기 site 계정으로 로그인한다(D-276 역할 그대로).

## 5. 팀원 접속 요약

| 하려는 일 | 경로 | 필요한 것 |
|---|---|---|
| 관제 콘솔 | 브라우저 → tailnet의 site 주소 | tailnet 계정 + site 계정 |
| 로봇 SSH (오래 쓸 사람) | `rosy_ssh_enroll.py <로봇의 tailnet 이름>` | tailnet 계정 + LCD administrator 코드 |
| 로봇 SSH (짧은 기간) | 팀 키 묶음 | tailnet 계정 + 팀 키 passphrase |

등록·회수 절차는 [로봇 SSH 접속 안내](robot-ssh-access.md) 그대로다. `<robot-ip>` 자리에
로봇의 MagicDNS 이름이나 tailnet 주소를 넣으면 된다.

## 6. 회수

- 팀원 퇴장: tailnet 콘솔에서 사용자 제거 **그리고** 그 사람의 SSH 라벨 회수(D-418 `revoke`)를 함께 한다.
- 로봇 빼기: tailnet 콘솔에서 기기 제거. 로봇 쪽 `sudo tailscale logout`으로 상태를 지운다.
- 남은 auth key는 발급 화면에서 폐기한다.

## 경계

- 이미지의 tailscale deb 조각(`inputs.lock.yaml` `tailscale:`)은 아직 `verified: false`다.
  native arm64 이미지 빌드가 실제로 내려받아 설치하기 전까지 "이미지에 들어간다"가 아니다.
- TWIN(가입·이름 해석)과 DEVICE(개발 기기 1대, 자동 업데이트·재부팅 뒤 생존) 검증은 별도 증거로 남긴다
  (D-477 Validation). 호스트 테스트 통과는 장치 수용이 아니다.
