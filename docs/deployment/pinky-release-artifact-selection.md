# Pinky 릴리스 산출물 빠른 선택

기준: [D-325](../adr/D-325-pinky-deployment-artifact-selection.md) · 기존 장치의 카드 재기록 정책: [D-225](../adr/D-225-update-without-reflash-and-faster-card-writes.md)

먼저 배포 기록의 **설치한 이미지의 서명된 소스 커밋**과 배포할 candidate revision을 비교한다. 현재 v1 이미지 manifest에는 source 필드가 없으며, 같은 서명 목록의 `source-revision.txt`와 `build-provenance.json`으로 입증한다. SD 안내 도구는 두 파일의 source/release 일치를 확인하고 `verified-image.json`에 남긴다. active native payload의 `git_revision`은 이미지 revision과 다를 수 있으므로 둘을 혼동하지 않는다. 서명된 이미지 출처를 입증할 수 없으면 full-image 검토로 보내고, 추정한 `main`/`HEAD`로 빠른 경로를 선택하지 않는다.

```powershell
python deploy\robot\pinky_pro\release\artifact_impact.py `
  --base <installed-image-source-revision> `
  --head <candidate-commit> `
  --json
```

| 결과 | 다음 경로 |
|---|---|
| `none` | Pinky 이미지/payload를 만들지 않는다. 해당 변경의 CI, 문서 또는 Site/OMX 검증만 수행한다. |
| `native-payload` | [Build Pinky Pro native payload](../../.github/workflows/build-native-payload.yml)를 실행한다. 서명 전에 payload `ros-packages.txt`와 대상 이미지의 ROS deb inventory가 일치하는지 확인한다. 불일치하면 중단하고 전체 이미지 경로를 검토한다. |
| `flashable-image` | native ARM64 [flashable image](../../.github/workflows/build-pinky-image.yml)를 빌드한다. 새 장치, 확인되지 않은 기준선, OS/boot/host service/board/trust-anchor 변경에 사용한다. |
| `review` 또는 명령 오류 | HOLD. 분류되지 않은 Pinky 경로, 잘못된 revision, diff 실패를 검토한다. 결과를 `none`으로 덮지 않는다. `review`는 exit code 3을 반환한다. |

혼합 변경은 image가 payload보다 우선하고, 미분류 경로 하나라도 있으면 review가 우선한다. Selector는 변경 경로의 필요 artifact만 제안한다. 실제 release는 기존 테스트, native ARM64 build, 오프라인 서명과 검증을 통과해야 한다. 장치 설치는 명시적으로 선택한 target에만 수행하고 signed artifact·identity·release revision·health·ROS graph·최종 `cmd_vel` publisher를 readback으로 확인한다. 안전·동작·정지·지도 변경은 해당 DEVICE/FIELD 수용 게이트를 별도로 통과해야 한다.

## 자동 게시의 비교와 분류 경계

coordinator의 `base_source_revision`은 실제 설치된 서명 image/payload에서 인증한
기준선이다. 여러 장치의 설치 revision이 다르면 각각을 보존하고, 공통 비교 기준은
그 설치 source들의 입증된 공통 조상으로 둔다. 새 main을 이미 전달된 기준선으로
넣어 변경을 건너뛰지 않는다. 이 기준선은 앞의 이미지 출처 검증을 대신하지 않는다.

GitHub compare의 파일 목록은 큰 변경에서 잘릴 수 있다. `source_inventory.py`는
300개 이상인 응답에 한해 exact commit→tree 두 쌍을 읽고 returned SHA,
`truncated: false`, 개수 상한·정상 경로·중복·type/mode를 확인한다. 완전한 증거가
없으면 HOLD한다. 디렉터리 hash는 leaf 변경으로 풀고 rename은 추가/삭제로 처리한다.
mode/type 변경·symlink·submodule은 경로 분류에 남기되 byte-only delta에는 쓰지 않는다.
incoming main의 코드를 운영 PC에서 실행해서 분류하지 않는다.

분류는 파일 확장자보다 실제 소비자를 따른다. `tools/packaging/fleet_sources.py`는
Fleet setup의 실행 입력이고 `release/host_lane_perception.py`는 native installer와
OTA mirror가 복사하므로 payload 대상이다. `sd/`는 builder가 image-overlay에 통째로
복사하는 closure이며 테스트를 포함해 OS 대상으로 둔다. `.gitattributes`도 checkout
bytes에 영향을 주므로 보수적으로 OS 대상으로 분류한다.

PC 전용의 검토된 exact 파일과 좁은 host 역할 폴더만 `none`으로 둔다. 개발용 Pinky
Dockerfile/Compose, PC에서 실행하는 calibration guard와 SSH stdin probe helper는
제품의 영속 설치 closure에 포함되지 않는다. 이 guard 두 파일은 exact 예외이며
Pinky operator 폴더 전체를 제외하지 않는다. `tools/`나 `deploy/hosts/` 전체를
제외하지 않으며 새 미분류 경로는 계속 review다. `none`은 Pinky artifact가 필요 없다는
뜻이다. 호스트 배포·검토된 고정 signer snapshot 갱신·실행 권한 승인을 대신하지 않는다.

## 측정 근거

2026-09-27/28 GitHub Actions 기록:

- Flashable image `36415015940`: 전체 약 30분 25초. `Build unsigned flashable image` 1,619초; 준비 93초, 이미지 검증 78초, 업로드 19초.
- Native payload `36319224327`: 전체 약 5분. `Build native payload tree` 201초; 준비 73초, dependency 확인 8초, 조립·업로드 14초.

실행별 실제 시간이며 이후 실행의 성능 보장은 아니다. 대상 source가 같고 재사용 가능한 서명 artifact가 이미 있어도 SHA/release identity가 다르면 새 artifact로 바꿔 쓸 수 없다.
