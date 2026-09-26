## D-222 First-boot 소비자는 `rosy-first-boot.py` 하나다 — `apply-sd-provision.py` stub을 폐기한다

**Status:** Accepted (2026-09-25). stub 삭제 + `test_first_boot_provisioning.py` 23 passed.

**Context:**

1. `docs/plans/2026-09-21-rosy-sd-personalization.md` Task 4는 Pi 첫 부팅 소비자 역할을
   `deploy/robot/apply-sd-provision.py`에 배정했다. 그 파일은 1행 TODO stub 그대로다.
2. 실제 구현은 D-161 네이티브 전환 과정에서 `deploy/image/first-boot/rosy-first-boot.py`에 착지했다
   ("Apply a one-time ROSY SD personalization bundle", `complete.json` 기록,
   `deploy/sd/personalization` 검증 사용). 시험 `test/test_first_boot_provisioning.py`도 존재한다.
3. stub를 가리키는 살아있는 참조는 없다 — dated plan 문서 2건만 남았다. 즉 역할이 이사했는데
   옛 주소가 그대로 남아 있는 상태다.

**Decision:**

1. First-boot 소비자의 유일한 정본은 `deploy/image/first-boot/`다
   (`rosy-first-boot.py` + `rosy-first-boot.service` + retry timer).
   `deploy/robot/apply-sd-provision.py` stub을 삭제하고, plan의 경로 지정은 superseded로 본다.
2. 첫 부팅 identity·네트워크 기록자는 둘일 수 없다. 두 소비자가 공존하면 같은 파일들
   (`/etc/hostname`, identity, NetworkManager profile)을 두고 쓰는 split-brain이 된다.

**Alternatives:** stub을 구현하는 안 — 이미 동작하는 소비자와 중복되며, 어느 쪽이 `complete.json`의
주인인지 모호해진다. stub을 남기는 안 — 다음 작업자가 "구현해야 할 것"으로 오해한다
(이미 한 번 그렇게 보였다).

**Consequences:** first-boot 관련 변경은 `deploy/image/first-boot/`와 그 계약 시험에서만 한다.
`native/rosy-sd-provision.service`의 게이트(`complete.json`)는 그대로다.

**Validation:** stub 삭제 후 `grep apply-sd-provision`이 dated plan以外에 걸리지 않고,
`python -m pytest test/test_first_boot_provisioning.py -q` 통과.
