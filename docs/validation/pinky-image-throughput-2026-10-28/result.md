# Pinky OS 입력 압축 시간 측정

2026-10-28, `fix/pinky-image-throughput`. OS 입력 exporter의 XZ preset만 6에서 1로 낮춘다. XZ/CRC64, 원본·압축본 SHA-256, GPT·소유권 검사, 변경 감지와 원자 발행은 유지한다. API·옵션·의존성을 추가하지 않는다.

## 실제 native 빌드에서 시간이 든 곳

Source commit `28f95ef47e45c6346196dbdf173026954e73c63d`, native run `40643866173`, job `122668032833`의 성공 로그를 사용했다. 로그의 출력 경계로 잰 시간이며 함수별 CPU profile은 아니다.

| 구간 (UTC) | 시간 | 관측 경계 |
|---|---:|---|
| 06:46:02.520–07:24:54.819 | 2,332.30 s | A/B 조립 완료 → OS 입력 export JSON |
| 07:24:56.556–07:47:30.063 | 1,353.51 s | 마지막 filesystem 검사 출력 → 최종 이미지 완료 |
| 07:47:30.063–07:50:28.373 | 178.31 s | 이미지 완료 → artifact 검사 성공 |
| 07:50:29.311–07:54:05.764 | 216.45 s | handoff 검사 시작 → checksum 결과 |

exporter는 root_a·boot_a를 Python LZMA preset 6으로 순차 압축한다. finalizer는 같은 OS를 포함한 전체 A/B 디스크를 다시 `xz --threads=0 -6`으로 압축하고 검사한다. 앞의 두 구간이 약 61분 26초다. 두 번째 구간에는 bmap 생성·압축·완전성 검사가 포함된다.

## 제한된 실제 rootfs 표본

검증된 release `2026.10.28-172`의 `os-bundle-inputs/rootfs.ext4.xz`에서 처음 256 MiB를 사용했다. 전체 이미지 사본은 옮기지 않았다. 압축 prefix 128 MiB만 기존 승인된 비현장 x86_64 시험 PC에 전송하고 그곳에서 표본 추출·압축을 실행했다. 표본 SHA-256은 `d35cfaf7d32bb089ac7a1b812ab621c5360f0087b4186ecbf6a1bc2a65ada4b3`이다.

명령은 `xz --threads=1 --check=crc64 -<preset> --stdout <sample>`이며 preset 6, 3, 1 순서로 한 번씩 실행했다. 각 결과에 `xz --test`와 전체 해제 후 원본 SHA-256 대조를 적용해 모두 통과했다. 단일 thread는 exporter의 Python LZMA 경로와 맞춘 것이다. 프로세스는 기존 SSH 설정과 `systemd-run --user --scope`, MemoryMax 2G, CPUQuota 200%, nice 15, ionice 3, 1,800초 제한을 사용했다. 새 패키지·외부 비용은 없다.

목적값은 압축 시간 + 검사 시간 + 결과 bytes / 1,800,000이다. 전송 항은 Windows에서 관측한 약 1.8 MB/s로 계산한 추정값이며 이 표본의 WAN 전송을 실측한 값은 아니다.

| preset | 압축 s | 검사 s | 결과 bytes | 전송 추정 s | 목적값 s |
|---|---:|---:|---:|---:|---:|
| 6 | 51.366 | 2.706 | 79,266,876 | 44.037 | 98.110 |
| 3 | 43.909 | 2.660 | 80,448,888 | 44.694 | 91.263 |
| 1 | 22.573 | 2.452 | 80,784,548 | 44.880 | 69.905 |

preset 1은 표본 압축 시간을 56.1%, 목적값을 28.7% 줄였으며 결과 크기는 1.91% 늘었다. 이 근거로 exporter의 기본 preset만 바꾼다. finalizer의 다중 thread·전체 이미지 workload는 측정하지 않았으므로 이번에는 바꾸지 않는다.

## 검증과 한계

기준 커밋 `7b92ed0409`에서 기존 `test_os_bundle_export.py`, `test_ab_image_pipeline.py`, `test_flashable_image_layout.py`를 원격 실행해 22 passed, 0 skipped를 확인했다. 변경 커밋의 동일 회귀와 독립 안전 검토는 후속 증거에서 확인한다. 이 시험은 실제 GPT 범위 해제·원본/압축 SHA-256·입력 거부·실패 cleanup·source mutation 거부를 검사한다. CLI 단독 import와 native 전체 빌드 수용을 증명하지 않는다.

원문 로그·측정 스크립트·결과는 Git 밖 `Rosy/artifacts/receipts/2026-10-28-image-throughput/`에 보존했다. 기준 회귀는 `baseline/run-1.txt`, 표본 결과는 `benchmark-stdout.jsonl`이다. 표본은 partition 시작 부분 하나이며 반복·ARM CPU·전체 rootfs·다중 thread·동시 작업 간섭에 대한 일반화는 하지 않는다. 제품 이미지 크기와 native 전체 시간은 다음 별도 빌드에서 확인해야 한다. frozen SD172·OTA173은 재빌드하거나 변경하지 않았다.

CE: 해당 없음 — 원인·선택 조건·실측 한계를 이 검증 기록과 단일 preset 변경으로 복원할 수 있어 별도 해결 교훈을 추가하지 않는다. 실물·운영 수용은 수행하지 않았다.

## 통합 이행

원본 commit 6f823421388cf3a907b8086d36398eadbe5b9511의 변경 회귀는22 passed/0 skipped/0 NEW와 독립 producer-consumer 검토를 통과했다. 이후 GitHub OS 전송 통합 브랜치에 같은 단일 preset 변경을 이행한다. 원본 측정은 제한된 x86 표본이며, 다음 ARM 이미지의 전체 시간·크기는 새 빌드에서 따로 확인한다.
