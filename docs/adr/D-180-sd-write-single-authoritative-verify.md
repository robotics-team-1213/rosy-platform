## D-180 SD 카드 기록은 전체 readback 한 번으로만 검증하고, Imager 검증과 raw 해시 사전 패스는 끈다

**Status:** Accepted (2026-09-23). D-173(첫 카드 기록 절차)의 WRITE 단계를 바꾼다.
[2026-09-21 SD 개인화 설계](../plans/2026-09-21-rosy-sd-personalization-design.md) 설계 단계 6
("write verification을 끄지 않는다")을 대체한다.

**Context:** 32 GB 카드에 릴리스 `2026.09.23-005`를 굽는 데 약 50분, 같은 카드에 `004`는 48분이 걸렸다.
시간은 이미지 전체를 세 번 훑는 데 쓰인다.

| # | 패스 | 하는 일 | 실측 |
|---|---|---|---|
| 1 | `verify-media-readback.py --image-only` | 8.5 GB `.img.xz`를 전부 풀어 Imager `--sha256`에 넣을 raw SHA-256만 계산 | 약 12분 |
| 2a | `rpi-imager --cli --sha256 <raw>` 쓰기 | 카드 기록 | 약 20분 |
| 2b | Imager 기본 read-back verify | 카드 전체를 다시 읽어 raw 해시 비교 | 약 10분 |
| 3 | `verify-media-readback.py --image --device` | 이미지를 다시 풀면서 장치와 byte 단위 비교(FAT32 boot 파티션은 파일 단위), 같은 패스에서 `image_raw_sha256`·`device_sha256` 계산 | 카드 속도 한계 |

패스 1과 2b는 패스 3과 중복이다.

- **입력 진위**는 쓰기 전에 이미 확정된다. 압축 이미지의 SHA-256을 오프라인 서명된 `SHA256SUMS`와
  `verify-image-release.py`로 대조하고, 이것은 디스크 탐색보다 먼저 실행된다.
- **매체 정합성**은 패스 3이 끝에서 끝까지 확정한다. 패스 3은 전 구간 byte 비교이고 boot 파티션의 허용
  필드까지 따로 보고하므로 Imager의 해시 하나 비교보다 엄격하다. personalization·receipt·registry는 모두
  패스 3 뒤에만 실행된다.
- 설계 단계 6은 전체 readback이 없던 때에 쓰였다. D-173이 전체 readback을 넣은 뒤로 Imager 검증은 같은
  사실을 한 번 더, 더 약하게 확인할 뿐이다.

**Decision:**

1. `prepare-rosy-sd.ps1`에서 `--image-only` 사전 패스를 없앤다.
2. Imager는 `--cli --disable-verify "<image>" "<device>"`로 부른다. `--sha256`은 넘기지 않는다.
   설치된 Imager v2.0.8 실행 파일의 옵션 테이블에 `disable-verify`("Disable verification")가 있다.
3. 패스 3은 그대로 둔다. 불일치면 bundle·receipt·registry 전에 멈춘다. 스크립트는 readback 증거에
   64자리 hex `image_raw_sha256`·`device_sha256`와 양수 `bytes_verified`가 있는지 확인한다(사전 패스가
   하던 raw 해시 형식 검사를 여기로 옮겼다). receipt의 `media_readback`에 `image_raw_sha256`,
   `device_sha256`, `bytes_verified`, `verified: true`가 남는다.
4. 쓰기 전 안전장치는 바꾸지 않는다: 압축 이미지 서명 검증, `ERASE SERIAL …` 확인 문구, 시리얼 기반
   디스크 선택(USB instance serial fallback 포함), 쓰기 직전 디스크 fingerprint 재확인.

**Alternatives:**

- 현 상태 유지(세 패스) — 같은 사실을 세 번 확인하며 카드 한 장에 약 50분.
- Imager 검증만 남기고 패스 3 제거 — Imager 검증은 해시 하나만 비교하고 불일치 위치와 boot 파티션
  변경을 보고하지 않는다. receipt에 남길 증거가 약해진다.
- raw 해시를 릴리스 manifest에 넣어 사전 패스만 없애기 — 릴리스 형식과 서명 대상이 바뀌고, Imager
  read-back(약 10분)은 여전히 남는다.

**Consequences:** 카드 한 장 기록이 약 50분에서 약 25-30분으로 줄 것으로 본다(쓰기 한 번 + readback 한 번,
카드 속도 한계). 무결성은 패스 3이, 진위는 서명된 `SHA256SUMS`가 계속 보증한다. Imager 쓰기와 패스 3 사이에
카드가 바뀌거나 쓰기가 틀려도 패스 3이 잡는다. Imager가 exit 0을 내도 그것만으로는 성공이 아니다.
더 줄이려면 운영자 쪽 수단을 쓴다: A1/A2 또는 U3 등급 카드, USB 3.0 리더기.

**Validation / Transition:** `test/test_sd_writer_contract.py`가 writer 인자를 `--cli --disable-verify`로,
`--sha256`·`--image-only` 부재를, readback 호출이 한 번뿐임을 고정한다. readback 불일치(짧은 매체, 1 byte
반전)는 bundle·receipt·registry 전에 멈춘다. 실제 카드 기록 시간은 다음 카드에서 잰다.
