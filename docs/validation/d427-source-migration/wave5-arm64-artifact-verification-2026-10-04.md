# D-427 wave5 ARM64 산출물 검증

소스 `1722ca6ec6d7`, 후보 릴리스 `2026.10.04-035`의 실제 unsigned 산출물을 확인했다. 034는 앞선 unsigned 빌드가 사용했으므로 재사용하지 않았다. 전체 CI의 10개 시험 matrix와 scope·ci-result는 모두 실제 SUCCESS다. 이 기록은 서명·발행·기기 수용을 뜻하지 않는다.

## 실제 빌드와 네이티브 payload

- [native run 37180857889](https://github.com/livsbittt/rosy-os/actions/runs/37180857889)과 [SD run 37180861394](https://github.com/livsbittt/rosy-os/actions/runs/37180861394)는 같은 소스에서 모두 SUCCESS다. ARM64 colcon은 각각 28개 패키지를 완료했다.
- native GitHub ZIP은 100,529,388 bytes이며 내려받은 bytes의 SHA256이 GitHub artifact digest와 일치한다. 내부 unsigned tar는 49,525,891 bytes, 2,878 members다. tar에서 추출한 실제 2,547 manifest 파일과 2,548 SHA256SUMS 항목을 전부 검증했고 누락·추가·위험 경로가 없다. ZIP 디렉터리만으로 서명하면 dotfile과 Linux mode를 잃을 수 있으므로 후속 서명 입력은 tar다.
- installed Skill/Motion Python 소스 5개가 해당 Git 소스와 byte 일치한다. 빌드 로그는 release 내부 namespace에서 실제 ARM64 import를 확인했다. 독립 검토는 설치된 소스 49개와 변경된 Python bytecode 36개도 확인했다.
- 서명된 033과 ROSY 패키지 28개·필수 패키지 13개의 이름이 같고 삭제된 설치 경로는 없다. 설치 경로는 35개 추가됐다. 소스·bytecode·dist-info·IMU 환경 hook에 해당하며, 기존 경로의 해시 변경은 86개다. native driver 소스는 033과 byte 일치하지만 ELF text·relocation까지 완전 동등하다는 주장은 하지 않는다.
- 빌드에 기록된 ROS deb 342개의 이름과 버전은 033과 같다. 이는 build-to-build 비교이며 현재 로봇의 ABI 확인을 대신하지 않는다.

## SD 이미지와 factory metadata

- 실제 ZIP 2,703,688,791 bytes의 digest와 14개 외부 SHA256SUMS 파일을 전부 검증했다. 이미지 XZ를 끝까지 해제해 오류가 없음을 확인했고 해제 크기 12,869,835,264 bytes는 bmap ImageSize와 같다. 로컬에서 파일 시스템을 mount하거나 실제 로봇을 부팅한 검사는 아니다.
- ZIP SHA256: `517a15f039920125e847affdf62064864b8e9e177da49403ac6cebca0cfc9e60`.
- 이미지 XZ SHA256: `25ac8a6e9422090498302a33a13d258adba5d58b90f84c924f18d838afd7d5ce`.
- 실제 outer/build/factory 기록은 같은 소스·릴리스·ARM64 Pinky target/runtime을 가리킨다. 033·native·SD metadata 비교의 21개 항목이 모두 통과했다. factory manifest와 SHA256SUMS의 기록도 일치한다. exported metadata를 읽은 비교와 실제 image 내부 bytes 검증을 구분한다.
- SD 빌드 로그에는 release 내부 Skill/Motion import, CORE probe 54 modules, IO probe 8 modules/3 packages, display probe 10 modules/4 stages가 있다. display GPIO 검사는 non-Pi builder 제약을 기록했다. 물리 GPIO 동작을 확인한 것은 아니다.
- 빌드 중 image root에서 unsigned factory release 2,547파일을 seal했고, `verify-mounted-image.py`의 성공과 `ROOTFS_CUSTOMIZED`를 확인했다. unsigned 호출은 설치 상태와 sealed 파일 존재·shape를 검사한다. signed factory signature 검증은 호출하지 않았으며 BUILD_GO를 주장하지 않는다.
- SD factory와 native manifest의 파일 경로 2,547개는 같다. 646개 해시 차이는 bytecode 596, setup shell 42, 생성 description C 4, ELF 2, parent prefix 1, deb inventory 1이다. Python·JS·계약 소스의 기록된 해시는 같다. 경로 차이·재빌드 결과를 원인으로 추정할 수 있지만, image 내부 파일 bytes를 별도 추출하지 않았으므로 모든 차이의 실행 동등성을 확정하지 않는다. 033 대비 SD 설치 해시 변경은 685개, 추가 경로 35개, 삭제 0개다.

## 남은 수용 조건

현재 canary의 읽기 전용 SSH ABI 조회는 exit 255와 연결 시간 초과로 끝났다. 현재 release·CORE 상태·ABI는 미검증이며 예전 033 정상 기록을 현재 상태로 대체하지 않는다. 실제 `prepare_payload_release.py`도 후보의 342 ROS deb와 필수 패키지를 읽은 뒤 ABI 조회 실패를 이유로 exit 1을 반환했고, extract·sign 단계에 들어가지 않았다. `--skip-abi`를 사용하지 않았고 새 릴리스를 서명하거나 발행하지 않았다. 접속·현재 사용 조율·calibration/maintenance guard 확인 후 035를 서명·발행하고 canary 및 로봇 readback을 확인해야 한다.

site PC model-watch는 대상 identity와 접속 정보가 미확정이어서 NOT_RUN이다. peer 안내는 실제 Rosy 채널의 delivery/ack가 없어 NOT_SENT다. 기존 등록·자격증명을 보존한다. firmware S7 bad_cycle/uint32는 다음 개정이며 flash·motion·E-Stop reset은 실행하지 않았다.
