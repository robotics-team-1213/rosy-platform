## D-230 카드 재기록은 마지막 수단이다 — 기존 로봇은 서명 payload 전환으로 갱신하고, 남는 재기록은 리더·재개·이미지 크기로 줄인다

**Status:** Proposed (2026-09-25).

**Context:**

1. 수정마다 카드 전체를 다시 굽고 있다. 원본 이미지는 8,574,867,968 B이고, 한 번 굽는 데 쓰기와
   전체 readback이 약 15~18분 걸린다. 여기에 GitHub ARM64 이미지 빌드가 약 35분 더 든다.
   2026-09-24 release 010 기록은 같은 카드에 55분이 걸렸다. 첫 시도가 8.4 MB(99.9%)를 남기고
   멈췄고, 부분 기록이 디스크 서명을 바꿔 재시도가 "다른 카드"로 거부됐다. 55분 중 37분이
   성공 시도 전 재시도에 쓰였다
   (`F:\tmp\rosy-release\cards\write-2026.09.24-010-rosy-pinky-e4us-*.log`).
2. 병목은 카드 리더다. 운영 PC의 리더는 USB 2.0 "Genesys Logic USB2.0 Card Reader"
   (VID_05E3 PID_0727)이고, preflight 읽기 19.6 MB/s, 쓰기 17.5 MB/s, readback 19.9 MB/s로
   모두 여기서 묶인다. bmap 매핑 비율은 90.6%(7.77 GB)라서 sparse 쓰기로 얻을 몫이 작다.
   Imager 2.0.8 `--cli`는 모든 바이트를 쓰고, `verify-media-readback.py`는 모든 바이트를 비교한다.
3. 로봇 위에는 이미 서명된 원자적 릴리스 전환이 있다. `deploy/robot/native/native_release.py`는
   `/opt/rosy/current`·`previous` 링크, Ed25519 `SHA256SUMS.sig`, manifest 파일 목록,
   Python 런타임 일치 검사, journal 기반 activate/rollback/recover를 갖는다. 다만 host tmpdir
   검증만 됐고 `UPDATE_GO`는 HOLD다(`docs/deployment/pi5-acceptance-checklist.md`).
   다음 세 가지가 비어 있어서 실제로는 쓰이지 않는다.
   - 독립 payload 빌드가 없다. `build-pinky-image.yml`은 이미지 안에서만 payload를 만든다.
   - 로봇까지 보내는 전송 경로가 없다.
   - 이미지에 든 공장 릴리스가 서명되지 않았다. 그래서 공장 릴리스로 rollback할 수 없고,
     첫 전환 중 전원이 끊기면 부팅 복구가 실패한다.
4. 기기에서 증명된 유일한 무재기록 경로는 D-179 dev overlay다. CORE Python과 웹 토큰만
   덮고, 덮인 장치는 `device_runtime=HOLD`로 읽힌다.
5. 010→011(47 커밋, 806 파일, 대부분 폴더 이동) 가운데 `/opt/rosy/current` 바깥을 건드린
   것은 두 가지뿐이다. 부트 cmdline/getty UART 수정은 `configure-uart-pi5.sh`와 재부팅으로
   소급할 수 있고, first-boot Wi-Fi 재시도는 새 카드에만 의미가 있다. apt 집합과
   `device-python-requirements.txt`는 그대로였다. 그러니 **기존 로봇에는 재기록이 필요 없었다.**

**Decision:**

1. **변경 계층을 셋으로 나누고, 재기록은 이미지 계층에만 쓴다.**

   | 계층 | 예 | 기존 로봇 갱신 방법 |
   |---|---|---|
   | 이미지 | base OS, apt/deb, 커널, ROS base, `device-python-requirements.txt`, 사용자·그룹·udev | 재기록(새 이미지 릴리스) |
   | 부트·호스트 | `config.txt`/`cmdline.txt`, getty mask, systemd unit, `/opt/rosy/native-runtime` | 해당 스크립트를 기기에서 재실행하고 재부팅. 재기록하지 않는다 |
   | payload | `install/` 아래 ROS 패키지·launch·config·웹 자산 | 서명 payload 전환(`native_release.py activate`) |

   새 카드와 새 로봇은 계속 서명 이미지로 시작한다(D-164, D-212). 이미지 릴리스는 이미지
   계층 변경이 쌓였을 때와 새 카드가 필요할 때만 자른다.
2. **payload 전환 경로를 완성한다. 기존 부품을 잇는 일이고 새 업데이트 체계를 들이지 않는다.**
   1. payload 전용 CI job: `ubuntu-24.04-arm`에서 `build-native-payload.sh`만 돌려
      `native_release.py`가 읽는 `manifest.json`과 `SHA256SUMS`를 낸다. 서명은
      `sign_image_release.py`처럼 오프라인 파일럿 키로 한다(D-145/D-146 handoff 유지).
   2. 이미지 안의 공장 릴리스를 서명한다. 그래야 공장 릴리스로 rollback할 수 있고,
      첫 전환의 recover도 성립한다.
   3. 운영 PC에 `deploy/robot/rosy-release-push.ps1`을 둔다. 기존 운영자 SSH 키로 서명
      tarball을 보내 `/opt/rosy/releases/<id>`에 풀고 `activate-release.sh`를 부른다.
      GitHub polling updater(`deploy/release/cli.py`, Docker 전용, D-197/D-198 퇴역)는
      되살리지 않는다.
   4. 판정: e4us에서 activate → rollback → 전원 차단 중 recover를 한 번씩 증명하면
      `UPDATE_GO`를 GO로 올린다. 그 전까지 payload 전환은 개발용이고 DEVICE 증거가 아니다.
3. **남는 재기록은 검증 보장을 약하게 하지 않는 방법으로만 줄인다.**
   1. 운영 PC 카드 리더를 USB 3 UHS-I로 바꾼다. 코드 변경이 없고 한 번에 약 8~10분을 줄인다.
      preflight가 `read_mbps < 30`이면 리더를 교체하라는 안내를 로그에 남긴다.
   2. Imager가 멈췄을 때 기록량이 원본 크기의 99.9% 이상이면 전체 재기록 대신
      `-ResumeAfterWrite`(readback부터 재실행)를 먼저 안내한다. 지금은
      `$written -ge $imageRawSize`일 때만 안내한다(`prepare-rosy-sd.ps1`). readback이 모든
      바이트를 비교하는 권위 검사(D-187)는 그대로여서, 덜 쓰인 카드는 거기서 실패하고
      bundle과 receipt 전에 멈춘다.
   3. 이미지 축소: customize가 끝난 뒤 rootfs를 `resize2fs -M`에 여유를 두고 줄여 자르고,
      첫 부팅의 growpart에 맡긴다. 약 1.2~1.4 GB, 2분쯤 준다. 첫 부팅 확장이 실기에서
      증명되기 전에는 채택하지 않는다.

**Alternatives:**

- **bmap sparse 쓰기와 매핑 구간만 검증**: 약 3분 절약. 매핑되지 않은 블록에 이전 카드
  내용이 남는다. 재기록 카드라면 이전 로봇의 자격 증명이 빈 공간에 남을 수 있다.
  `device_sha256 == image_raw_sha256` 보장도 구간별 해시로 약해진다. D-180(Imager와
  전체 비교 1회)을 뒤집는 데 비해 이득이 리더 교체보다 작다. 기각.
- **RAUC / Mender / SWUpdate / OSTree / Ubuntu Core**: Pi 5와 Ubuntu 24.04 조합에서 지원이
  없거나 비공식이다. Mender는 이 조합을 지원하지 않고, RAUC의 Pi 5 tryboot backend는 아직
  열린 PR이며 서명이 X.509/CMS다. Ubuntu Core는 플랫폼을 옮겨야 한다. 2~10대 규모에는
  과하고, 이미 있는 `native_release.py`가 payload 전환을 덮는다. 기각.
- **Pi 펌웨어 A/B(`autoboot.txt` + `tryboot`)**: 이미지 계층 변경(커널·apt)이 잦아질 때 다시
  본다. 6-파티션 재배치와 commit 에이전트, watchdog이 필요하다. 보류.
- **dev overlay 확장만으로 끝내기**: 싸지만 덮인 장치가 HOLD로 남고, CORE 밖(control,
  bringup, emotion)은 unit drop-in이 늘어난다. 개발 반복용으로만 유지하고 운용 경로로 삼지 않는다.
- **NFS root / 네트워크 부팅**: 유선이 필요하다. 벤치 개발용으로만 고려한다.

**Consequences:**

- 기존 로봇의 코드 수정은 이미지 빌드(35분)와 카드 기록(15~18분) 대신 payload 빌드와 전송,
  전환으로 끝난다. 재기록은 이미지 계층 변경과 새 카드에만 남는다.
- 부트·호스트 계층(unit, native-runtime)은 아직 릴리스 전환과 함께 움직이지 않는다. unit을
  릴리스 안으로 옮기고 전환 시 `/etc/systemd/system`을 갱신하는 일은 후속 ADR이다
  (D-161/D-164 후속).
- `device-python-requirements.txt` 변경은 계속 이미지 계층이다. 전환 검사가 런타임
  불일치를 거부한다.
- 이미지 릴리스 사이의 폴더 이동 규칙(D-191)은 payload 계층에서도 같다. 패키지 이름이
  바뀌면 `install/` 배치가 바뀐다.

**Validation:**

1. payload 경로: e4us에서 `rosy-release-push.ps1`로 서명 payload를 activate한 뒤
   `/opt/rosy/current`가 새 id를 가리키고 CORE_READY인지 본다. `rollback-release.sh`로 공장
   릴리스까지 되돌리고, 전환 중 전원을 끊은 뒤 `rosy-release-recover.service`가 일관된
   상태로 복구하는지 본다. 세 가지가 통과하면 `UPDATE_GO`를 GO로 올린다.
2. 재개 안내: 99.9%에서 멈춘 기록을 흉내 낸 `test/test_sd_writer_contract.py` 사례가
   전체 재기록이 아니라 `-ResumeAfterWrite`를 안내하고, 덜 쓰인 카드에서는 readback이
   실패하는지 고정한다.
3. 리더: 교체 뒤 preflight `read_mbps`와 기록 로그의 쓰기·readback 시간을
   `deploy/logs.md`에 남긴다.

**References:** D-145/D-146(unsigned handoff), D-161(네이티브 런타임), D-164(플래시 이미지),
D-179(dev overlay), D-180/D-187/D-188(SD writer), D-191(이미지 릴리스 사이 이동),
D-197/D-198(Docker updater 퇴역), D-212(ARTIFACT 네이티브 경로),
`deploy/robot/native/native_release.py`, `deploy/sd/prepare-rosy-sd.ps1`,
`deploy/sd/verify-media-readback.py`, `.github/workflows/build-pinky-image.yml`.
외부 근거: Raspberry Pi `config.txt` tryboot/autoboot 문서, bmaptool README, Raspberry Pi
"Trimming the FAT" 공지, Mender 포럼 Pi 5 + Ubuntu 24.04 스레드, Bootlin RAUC on Pi 5 글.
