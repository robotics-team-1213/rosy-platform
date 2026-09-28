# 전원 차단 장치의 SD no-drive 복구

적용 대상은 현장 구동 설정이 `/etc/rosy/runtime.env`에 지속 저장된 뒤 전원이
차단된 Pinky Pro다. 이 절차는 **카드 설정만** 복구한다. 전원 차단 상태,
현장 정지 경로, 카드 분리 여부는 작업자가 직접 확인한다. PC에서 SSH가
끊겼다는 사실만으로 전원 차단을 추정하지 않는다.

1. 장치 전원을 차단하고 SD를 꺼내 Linux PC의 카드 리더에 넣는다.
   카드의 **ext4 root 파티션**을 `/mnt/rosy-card-root`처럼 별도 경로에
   마운트한다. 마운트 대상은 장치명·크기·파티션을 현장에서 확인한다.
   Windows `read-card-diagnostics.py`는 읽기 전용이고, USB SD에 대한
   `wsl --mount` 경로는 지원되지 않는다.
2. 카드 밖의 별도 저장장치에 비어 있는 백업 디렉터리를 준비한다.
   아래 기본 명령은 읽기만 하며 UID·이름·번호·현재 활성 릴리스와 현재 모드,
   drive flag, 파일 해시만 출력한다. 출력과 현장 카드 식별을 대조한다.

   ```bash
   sudo python3 deploy/robot/pinky_pro/sd/recover-no-drive.py \
     --root /mnt/rosy-card-root
   ```

3. 결과가 예상한 **동일 카드**이고 `motor`/`true`일 때만 정확한 네 값과
   백업 디렉터리를 전달한다. 잘못된 값, 중복 키, symlink, 기존 백업,
   ext4가 아닌 마운트는 쓰기 전에 중단된다.

   ```bash
   sudo python3 deploy/robot/pinky_pro/sd/recover-no-drive.py \
     --root /mnt/rosy-card-root --apply \
     --backup-dir /media/backup/rosy-recovery \
     --device-uid '<inspected-uid>' --device-name '<inspected-name>' \
     --robot-number '<inspected-number>' --release-id '<inspected-release>'
   ```

4. 도구는 원본 바이트를 카드 **밖**에 no-overwrite 백업하고 SHA-256을
   읽어 확인한 뒤 `ROSY_RUNTIME_MODE=core`로 바꾸고
   `ROSY_IO_DRIVE_ENABLED`를 제거한다. 원자 교체·readback이 성공해야
   `NO_DRIVE_RESTORED_ON_CARD` 영수증을 남긴다. `HOLD`가 출력되거나
   영수증이 없으면 복구 성공으로 취급하지 않는다. `sync` 후 언마운트하고
   카드를 다시 꽂는다.
5. 재전원은 현장 사람이 전원 차단 수단을 잡고 진행한다. 첫 부팅에서
   CORE E-Stop, `core` 모드, I/O drive disabled, 두 모터 torque disabled를
   장치에서 읽어 확인한다. 카드 영수증만으로 이 부팅 확인이나 G4 승인을
   대체하지 않는다. 설치된 구형 릴리스의 motor helper를 다시 실행하면
   persistent `drive=true`가 재생성되므로, boot-bound lease가 설치되기
   전에는 그 helper를 다시 사용하지 않는다.

관련 결정: [D-321](../adr/D-321-attended-calibration-g4-mapping.md).
