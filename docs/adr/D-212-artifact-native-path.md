## D-212 ARTIFACT 네이티브 경로 — Pi 5에서 서명 이미지까지만 간다

**Status:** Proposed (2026-09-25).

**Context:**

1. D-78은 ARTIFACT 빌더를 네이티브 ARM64 Pi로 고정한다. D-145/D-146은 unsigned 페이로드 → 오프라인 서명 handoff 절차를 정한다. D-164는 제품 산출물이 ISO가 아니라 서명된 Pi 디스크 이미지임을 정한다. D-197은 제품 체인에서 Docker 신규 의존을 금지한다.
2. QEMU 빌드(HUB hollow 이미지 실패, `arm64-build-notes.md` §2026-09-17)는 HOLD로 확정됐고, 기존 개발 후보 이미지 ID 재사용은 금지(D-66)다.
3. 빌드 호스트는 Pi 5 1대 네이티브로 확보됐다(2026-09-25 결정).

**Decision:**

1. ARTIFACT 인정 경로는 **Pi 5 네이티브 빌드 → unsigned payload → 오프라인 Ed25519 서명 → manifest + immutable digest + SBOM + 입력 lock**만이다. x86 QEMU 결과 발행 금지.
2. CORE 이미지는 `control`/OpenCV를 포함하지 않는다(D-66). vision/omx 프로파일은 카메라·OMX 게이트 통과 전까지 번들에 넣지 않는다.
3. `deploy/image/verify-artifacts.sh`(마운트된 이미지 트리 대상) 통과가 `BUILD_GO`다. 배포 디렉터리만 검사는 BUILD_GO가 아니다.
4. 이미지 존재·컨테이너 health만으로 DEVICE/BOOT를 승격하지 않는다.
5. 비밀(PSK·토큰·개인키)은 이미지에 넣지 않으며 `secret_scan`으로 검증한다.

**Consequences:** 서명·digest·SBOM 없는 빌드는 개발 후보로만 부르고 ARTIFACT HOLD를 유지한다. D-212 경로를 우회하는 제품 이미지 시도는 이 ADR 위반이다.

**Validation:**

```bash
python3 -m pytest test/test_arm64_release_builder.py test/test_unsigned_handoff_import.py test/test_release_manifest.py test/test_release_signing.py -q
ROSY_IMAGE_MOUNT=/mnt/rosy ./deploy/image/verify-artifacts.sh dist/<release-id>
```

**References:** D-78(네이티브 빌더), D-145/D-146(unsigned handoff), D-164(플래시 이미지), D-197(Docker 퇴역), D-66(CORE 이미지 경계), `docs/deployment/arm64-build-notes.md`, `docs/deployment/pi5-acceptance-checklist.md` §3.
